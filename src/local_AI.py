import cv2
import subprocess
import os
import shutil
from datetime import datetime
from ultralytics import YOLO

class PlantVision:
    def __init__(self):
        self.model = YOLO('yolov8n.pt') 
        self.path_9am = "ref_9am.jpg"
        self.path_prev = "ref_prev.jpg"
        self.path_curr = "current.jpg"

    def capture_12mp(self):
        """12MP 촬영 및 로컬 분석용 리사이징"""
        subprocess.run(["libcamera-still", "-o", self.path_curr, "--immediate", "--nopreview"])
        
        # 오전 9시 기준본 업데이트
        now = datetime.now()
        if now.hour == 9 and now.minute < 10:
            shutil.copy(self.path_curr, self.path_9am)
            
        return cv2.imread(self.path_curr)

    def get_metrics(self, frame):
        """YOLO 기반 높이 측정 (픽셀 단위)"""
        frame_small = cv2.resize(frame, (640, 640))
        results = self.model(frame_small, verbose=False)[0]
        height = 0
        if len(results.boxes) > 0:
            b = results.boxes[0].xyxy[0]
            height = b[3] - b[1]
        return float(height)

    def is_singularity(self, current_h):
        """특이점 판단: 9시 대비 3% 혹은 직전 대비 1.5% 변화 시"""
        # (비교 로직 생략 및 기본값 반환 - 실제 구현 시 저장된 수치와 비교)
        return True 

    def update_reference(self):
        """현재 사진을 다음 루프의 직전 사진으로 교체"""
        if os.path.exists(self.path_curr):
            shutil.copy(self.path_curr, self.path_prev)