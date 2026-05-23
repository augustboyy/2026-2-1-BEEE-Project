import asyncio
import datetime
import os
import sys
import time
import uuid
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

# 프로젝트 루트 경로를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.bootstrap import build_runtime
from app.services.camera import capture_photo_to_disk, create_preprocessed_temp

# [알고리즘 기준치 설정]
THRESHOLDS = {
    "yellow_ratio_threshold": 0.15,     # 노란색 영역 15% 이상 시 황화 현상으로 판단
    "short_leaf_drop_limit": -1,        # 잎 개수가 1개 이상 줄어들면 이상 감지
    "short_wilt_height_ratio": 0.90,    # 직전 대비 높이 90% 미만 시 단기 시듦
    "long_wilt_height_ratio": 0.85,     # 오늘 아침 대비 높이 85% 미만 시 누적 시듦
}

class LocalAnalyzer:
    """YOLOv8 및 OpenCV를 이용한 로컬 영상 분석 클래스"""
    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            model_path = PROJECT_ROOT / "weights" / "best.pt"
            if not model_path.exists():
                print(f"[Warning] YOLO model not found at {model_path}. Using base yolov8n.pt.")
                model_path = Path("yolov8n.pt")
            cls._model = YOLO(str(model_path))
        return cls._model

    @classmethod
    def get_plant_metrics(cls, image_bytes: bytes):
        import gc
        try:
            import torch
            has_torch = True
        except ImportError:
            has_torch = False

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        
        model = cls.get_model()
        results = model.predict(img, conf=0.25, verbose=False)
        
        leaf_count = 0
        max_height = 0
        leaf_mask = np.zeros(img.shape[:2], dtype=np.uint8)
        
        if results and len(results[0].boxes) > 0:
            boxes = results[0].boxes
            leaf_count = len(boxes)
            all_boxes = boxes.xyxy.cpu().numpy()
            y1_min = np.min(all_boxes[:, 1])
            y2_max = np.max(all_boxes[:, 3])
            max_height = int(y2_max - y1_min)
            
            # YOLO가 감지한 잎 사각형 영역만 마스킹 (배경 노이즈 제거)
            for box in all_boxes:
                bx1, by1, bx2, by2 = map(int, box)
                cv2.rectangle(leaf_mask, (bx1, by1), (bx2, by2), 255, -1)
        
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # 초록색/노란색 범위 필터링 (잎 영역 내부에서만)
        lower_green = np.array([35, 40, 40]); upper_green = np.array([85, 255, 255])
        green_mask = cv2.bitwise_and(cv2.inRange(hsv, lower_green, upper_green), leaf_mask)
        lower_yellow = np.array([20, 100, 100]); upper_yellow = np.array([32, 255, 255])
        yellow_mask = cv2.bitwise_and(cv2.inRange(hsv, lower_yellow, upper_yellow), leaf_mask)
        
        total_green = cv2.countNonZero(green_mask)
        total_yellow = cv2.countNonZero(yellow_mask)
        yellow_ratio = total_yellow / (total_green + total_yellow + 1e-6)
        
        del img, results, green_mask, yellow_mask, leaf_mask
        if has_torch and torch.cuda.is_available(): torch.cuda.empty_cache()
        gc.collect()
        
        return {"leaf_count": leaf_count, "height": max_height, "yellow_ratio": yellow_ratio}

async def run_local_ai_loop():
    print("Starting Local AI Analysis & Camera Service...")
    runtime = build_runtime()
    repository = runtime.repository
    analyzer = LocalAnalyzer()
    uploads_dir = Path(runtime.settings.uploads_dir)
    
    while True:
        try:
            plant = repository.get_current_plant()
            if not plant:
                await asyncio.sleep(60); continue
                
            plant_id = plant["id"]
            now = datetime.datetime.now()
            
            # 1. 고해상도(8MP) 촬영
            file_name = f"local_ai_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
            original_path = uploads_dir / file_name
            capture_photo_to_disk(str(original_path))
            
            # 2. 현재 상태 분석 (640px 메모리 최적화)
            temp_path = uploads_dir / f"temp_640_{uuid.uuid4().hex}.jpg"
            create_preprocessed_temp(str(original_path), str(temp_path), max_dim=640)
            with open(temp_path, "rb") as f: curr_metrics = analyzer.get_plant_metrics(f.read())
            if temp_path.exists(): os.remove(temp_path)
            if not curr_metrics: continue

            # 3. 비교 데이터 준비 (직전 사진, 아침 사진)
            state = repository.get_latest_state(plant_id)
            prev_id = state["previous_image_id"] if state else None
            morning_id = state["morning_image_id"] if state else None
            
            def get_safe_metrics(img_id):
                if not img_id: return None
                img_data = repository.get_uploaded_image(img_id)
                if not img_data or not os.path.exists(img_data["file_path"]): return None
                t_path = uploads_dir / f"temp_comp_{uuid.uuid4().hex}.jpg"
                try:
                    create_preprocessed_temp(img_data["file_path"], str(t_path), max_dim=640)
                    with open(t_path, "rb") as f: return analyzer.get_plant_metrics(f.read())
                except: return None
                finally:
                    if t_path.exists(): os.remove(t_path)

            prev_metrics = get_safe_metrics(prev_id)
            morning_metrics = get_safe_metrics(morning_id)
            
            # 4. 복합 이상 감지 로직
            note = None
            # (1) 황화 현상 체크
            if curr_metrics["yellow_ratio"] > THRESHOLDS["yellow_ratio_threshold"]:
                note = f"황화 현상({curr_metrics['yellow_ratio']:.1%})"
            
            # (2) 단기 변화 체크 (직전 사진 대비)
            elif prev_metrics:
                diff = curr_metrics["leaf_count"] - prev_metrics["leaf_count"]
                if diff <= THRESHOLDS["short_leaf_drop_limit"]:
                    note = f"잎 탈락({abs(diff)}개)"
                elif curr_metrics["height"] / (prev_metrics["height"] + 1e-6) < THRESHOLDS["short_wilt_height_ratio"]:
                    note = "시듦 감지(단기)"
            
            # (3) 장기 변화 체크 (오늘 아침 사진 대비)
            if not note and morning_metrics:
                if curr_metrics["height"] / (morning_metrics["height"] + 1e-6) < THRESHOLDS["long_wilt_height_ratio"]:
                    note = "시듦 감지(누적)"

            # 5. DB 저장 및 이상 발생 시 Gemini 즉시 호출
            with repository.database.transaction():
                repository.save_uploaded_image(plant_id, str(original_path.resolve()), file_name, "image/jpeg")
            
            if note:
                await runtime.monitoring_service.trigger_abnormal_analysis(plant_id, f"[로컬감지] {note}")
            
            print(f"[Local AI] {now.strftime('%H:%M:%S')} - 분석 완료 (이상: {note is not None})")
            
        except Exception as e:
            print(f"[Error] Local AI Loop 실패: {e}")
            
        await asyncio.sleep(600) # 10분 주기

if __name__ == "__main__":
    asyncio.run(run_local_ai_loop())
