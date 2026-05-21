import asyncio
import datetime
import os
import sys
import time
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

# 프로젝트 루트 경로를 sys.path에 추가하여 'app' 패키지를 임포트할 수 있게 합니다.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.bootstrap import build_runtime
from app.services.camera import capture_photo


# =================================================================
# [알고리즘 기준치 설정] - 여기서 자유롭게 수정 가능합니다.
# =================================================================
THRESHOLDS = {
    # 1. 황화 현상 (Chlorosis) 기준
    "yellow_ratio_threshold": 0.15,  # 잎 전체 면적 대비 노란색 영역 비율 (15% 이상이면 감지)
    
    # 2. 단기 이벤트 (이전 사진 대비)
    "short_leaf_drop_limit": -1,     # 잎의 개수 변화 (1개 이상 줄어들면 이상 감지)
    "short_wilt_height_ratio": 0.90, # 직전 대비 높이가 90% 이하로 줄어들면 시듦으로 판단
    
    # 3. 장기 성장 및 누적 상태 (아침 9시 대비)
    "long_growth_ratio": 1.05,       # 아침 대비 높이가 105% 이상이면 성장으로 판단
    "long_wilt_height_ratio": 0.85,  # 아침 대비 높이가 85% 이하로 줄어들면 심각한 시듦으로 판단
}
# =================================================================


class LocalAnalyzer:
    """YOLOv8 및 OpenCV를 이용한 로컬 영상 분석 클래스"""
    
    _model = None
    
	# 차후 onnx파일로 변경 후 onnx포멧 맞게 yolo모델 실행하는 코드 재작성 (전처리, 후처리 모두 포함) 필요

    @classmethod
    def get_model(cls):
        """YOLO 모델을 싱글톤 방식으로 로드합니다."""
        if cls._model is None:
            # 프로젝트 루트에 있는 best.pt 경로 설정
            model_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), 'best.pt')
            if not os.path.exists(model_path):
                print(f"[Warning] YOLO model not found at {model_path}. Using base yolov8n.pt as fallback.")
                model_path = 'yolov8n.pt'
            cls._model = YOLO(model_path)
        return cls._model

    @classmethod
    def get_plant_metrics(cls, image_bytes: bytes):
        """YOLOv8 모델을 사용하여 이미지에서 잎의 개수, 높이, 황화 비율을 계산합니다."""
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
        
        # 1. YOLOv8을 사용한 잎 감지
        model = cls.get_model()
        # 스트리밍 모드나 메모리 절약을 위해 필요한 옵션 설정
        results = model.predict(img, conf=0.25, verbose=False)
        
        leaf_count = 0
        max_height = 0
        leaf_mask = np.zeros(img.shape[:2], dtype=np.uint8)
        
        if results and len(results[0].boxes) > 0:
            boxes = results[0].boxes
            leaf_count = len(boxes)
            
            # 모든 바운딩 박스를 좌표를 추출 (CPU로 이동하여 메모리 점유 최소화)
            all_boxes = boxes.xyxy.cpu().numpy()
            
            # [이파리가 여러개일 때의 처리]
            # 1. 높이: 가장 위에 있는 잎의 상단부터 가장 아래에 있는 잎의 하단까지의 길이를 전체 높이로 계산
            y1_min = np.min(all_boxes[:, 1])
            y2_max = np.max(all_boxes[:, 3])
            max_height = int(y2_max - y1_min)
            
            # 2. 황화 분석 영역: 감지된 '모든' 잎의 사각형 영역을 합쳐서 마스크 생성
            for box in all_boxes:
                bx1, by1, bx2, by2 = map(int, box)
                cv2.rectangle(leaf_mask, (bx1, by1), (bx2, by2), 255, -1)
        
        # 2. 황화 현상 (Chlorosis) 분석
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # 초록색 영역 (정상)
        lower_green = np.array([35, 40, 40])
        upper_green = np.array([85, 255, 255])
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        green_mask = cv2.bitwise_and(green_mask, leaf_mask)
        
        # 노란색 영역 (황화)
        lower_yellow = np.array([20, 100, 100])
        upper_yellow = np.array([32, 255, 255])
        yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        yellow_mask = cv2.bitwise_and(yellow_mask, leaf_mask)
        
        total_green_area = cv2.countNonZero(green_mask)
        total_yellow_area = cv2.countNonZero(yellow_mask)
        
        yellow_ratio = total_yellow_area / (total_green_area + total_yellow_area + 1e-6)
        
        # 3. [메모리 반환] 사용한 대형 객체들 명시적 삭제 및 가비지 컬렉션
        del img
        del results
        del green_mask
        del yellow_mask
        del leaf_mask
        
        if has_torch and torch.cuda.is_available():
            torch.cuda.empty_cache() # GPU 메모리 파편화 방지 및 반환
        
        gc.collect() # 파이썬 가비지 컬렉터 강제 실행
        
        return {
            "leaf_count": leaf_count,
            "height": max_height,
            "yellow_ratio": yellow_ratio
        }


def get_current_morning_image_id(repository, plant_id: int):
    state = repository.database.fetchone(
        "SELECT morning_image_id FROM latest_state WHERE plant_id = ?", (plant_id,)
    )
    if state and state["morning_image_id"]:
        image = repository.get_uploaded_image(state["morning_image_id"])
        if image:
            created_at = datetime.datetime.fromisoformat(image["created_at"].replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            if created_at.date() == now.date():
                return state["morning_image_id"]
    return None

def delete_image_from_disk_and_db(repository, image_id: int):
    if not image_id: return
    image = repository.get_uploaded_image(image_id)
    if not image: return
    
    file_path = image.get("file_path")
    if file_path and os.path.exists(file_path):
        try: os.remove(file_path)
        except: pass
            
    with repository.database.transaction():
        repository.database.execute("DELETE FROM uploaded_images WHERE id = ?", (image_id,))
        repository.database.execute("DELETE FROM camera_captures WHERE image_id = ?", (image_id,))

async def trigger_cloud_ai(runtime, plant, image_bytes, note):
    """이상이 감지되었을 때 Cloud AI(Gemini)를 호출합니다."""
    print(f"[Trigger] Abnormality detected! Calling Cloud AI for plant: {plant['name']}")
    try:
        # 최신 센서/급수 데이터 가져오기
        latest_sensor = runtime.repository.get_latest_sensor_state(plant["id"])
        latest_watering = runtime.repository.get_latest_watering_log(plant["id"])
        
        # Cloud AI 호출 (기존 ai_client 로직 사용)
        ai_payload = await runtime.monitoring_service.ai_client.analyze_plant_photo(
            plant=plant,
            image_bytes=image_bytes,
            mime_type="image/jpeg",
            latest_sensor=latest_sensor,
            latest_watering=latest_watering,
            note=f"[Local AI 자동 감지] {note}",
        )
        
        # 분석 결과 DB 저장 (repository.add_analysis_result 사용)
        # 1. 먼저 이미지 저장 (수동 업로드와 동일한 경로)
        # Note: 이미지 저장은 loop에서 이미 수행하므로, 저장된 image_id를 넘겨받아야 함.
        # 이 함수를 호출하는 쪽에서 이미 저장된 image_id를 알고 있다고 가정.
        return ai_payload
    except Exception as e:
        print(f"[Error] Cloud AI Trigger failed: {e}")
        return None

async def run_local_ai_loop():
    print("Starting Local AI Analysis & Camera Service...")
    runtime = build_runtime()
    repository = runtime.repository
    analyzer = LocalAnalyzer()
    
    uploads_dir = Path(runtime.settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    while True:
        try:
            plant = repository.get_current_plant()
            if not plant:
                print("[Local AI] No active plant found. Waiting...")
                await asyncio.sleep(60)
                continue
                
            plant_id = plant["id"]
            now = datetime.datetime.now()
            
            # 1. 사진 촬영
            image_bytes = capture_photo()
            file_name = f"local_ai_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
            file_path = uploads_dir / file_name
            with open(file_path, "wb") as f:
                f.write(image_bytes)
                
            # 2. 로컬 분석 수행
            current_metrics = analyzer.get_plant_metrics(image_bytes)
            
            # 3. 이전 데이터와 비교를 위해 DB에서 현재 상태 가져오기
            state = repository.database.fetchone("SELECT * FROM latest_state WHERE plant_id = ?", (plant_id,))
            prev_id = state["previous_image_id"] if state else None
            morning_id = state["morning_image_id"] if state else None
            
            # 비교용 메트릭 추출
            def get_metrics_for_id(img_id):
                if not img_id: return None
                img_data = repository.get_uploaded_image(img_id)
                if not img_data or not os.path.exists(img_data["file_path"]): return None
                with open(img_data["file_path"], "rb") as f:
                    return analyzer.get_plant_metrics(f.read())

            prev_metrics = get_metrics_for_id(prev_id)
            morning_metrics = get_metrics_for_id(morning_id)
            
            # 4. 이상 감지 로직
            abnormality_note = None
            
            # (1) 황화 현상 감지
            if current_metrics["yellow_ratio"] > THRESHOLDS["yellow_ratio_threshold"]:
                abnormality_note = f"황화 현상 감지 (노란색 비율: {current_metrics['yellow_ratio']:.2%})"
            
            # (2) 단기 이벤트 분석
            if not abnormality_note and prev_metrics:
                leaf_diff = current_metrics["leaf_count"] - prev_metrics["leaf_count"]
                if leaf_diff <= THRESHOLDS["short_leaf_drop_limit"]:
                    abnormality_note = f"단기 잎 탈락 감지 (직전 대비 {abs(leaf_diff)}개 감소)"
                
                height_ratio = current_metrics["height"] / (prev_metrics["height"] + 1e-6)
                if height_ratio < THRESHOLDS["short_wilt_height_ratio"]:
                    abnormality_note = f"단기 시듦 감지 (직전 대비 높이 {height_ratio:.1%})"

            # (3) 장기 성장 및 누적 상태 분석
            if not abnormality_note and morning_metrics:
                long_height_ratio = current_metrics["height"] / (morning_metrics["height"] + 1e-6)
                if long_height_ratio < THRESHOLDS["long_wilt_height_ratio"]:
                    abnormality_note = f"누적 시듦 감지 (아침 대비 높이 {long_height_ratio:.1%})"
                elif long_height_ratio > THRESHOLDS["long_growth_ratio"]:
                    # 성장은 긍정적인 신호이므로 이상 감지로 분류하지 않을 수도 있지만, 
                    # 사용자 요청에 따라 지표로 관리. 여기서는 '성장 감지'로 리포트만 하거나 패스.
                    print(f"[Local AI] Growth detected! (Height: {long_height_ratio:.1%})")

            # 5. DB 업데이트 및 사진 3장 유지
            with repository.database.transaction():
                new_image = repository.save_uploaded_image(
                    plant_id=plant_id,
                    file_path=str(file_path.resolve()),
                    original_name=file_name,
                    mime_type="image/jpeg"
                )
                new_image_id = new_image["id"]
                
                # Cloud AI가 이미 호출된 경우 repository 내부에서 latest_state를 업데이트하므로
                # 여기서 중복 호출되지 않도록 주의해야 하지만, analyze_uploaded_photo 내부에서 save_uploaded_image를 호출하므로
                # 구조를 맞춰야 함. 여기서는 loop가 직접 관리하므로 수동으로 처리.
            
            # 6. 이상 감지 시 Cloud AI 호출
            if abnormality_note:
                await trigger_cloud_ai(runtime, plant, image_bytes, abnormality_note)
            
            print(f"[Local AI] Analysis complete. Abnormal: {abnormality_note is not None}. Sleeping...")
            
        except Exception as e:
            import traceback
            print(f"[Error] Local AI loop failed: {e}")
            traceback.print_exc()
            
        await asyncio.sleep(600)

if __name__ == "__main__":
    asyncio.run(run_local_ai_loop())
