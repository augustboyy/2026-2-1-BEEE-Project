import cv2
import subprocess
import os
import shutil
from datetime import datetime
from ultralytics import YOLO

class PlantVision:
    def __init__(self):
        self.model = YOLO('best.pt') 
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

    def is_singularity(curr_m, prev_m, ref_9am_m):

        # 임계값 설정
        T_HEIGHT_GROWTH = 3.0   # 오전 대비 3% 성장
        T_HEIGHT_WILT_ACC = 2.5 # 오전 대비 2.5% 누적 시듦
        T_HEIGHT_WILT_SRT = 1.5 # 직전 대비 1.5% 급격 시듦
        T_YELLOW_LIMIT = 5.0    # 황화 면적 비율 5% 초과 시 위험
    
        is_triggered = False
        reason = []

        # 1. 황화 현상(Chlorosis) 및 괴사 감지 (가장 우선 순위) 
        if curr_m['yellow_ratio'] > T_YELLOW_LIMIT:
            is_triggered = True
            reason.append(f"황화/괴사 지표 임계값 초과 ({curr_m['yellow_ratio']:.1f}%)")

        # 2. 단기 이벤트 분석 (Current vs. Previous) 
        if prev_m:
            # 잎의 개수 변화 (직전과 비교하여 즉각적 탈락/성장 감지)
            if curr_m['leaf_count'] != prev_m['leaf_count']:
                is_triggered = True
                reason.append(f"잎 개수 변화 (Prev): {prev_m['leaf_count']} -> {curr_m['leaf_count']}")
        
            # 직전 대비 급격한 높이 변화 (시듦)
            h_diff_prev = (abs(curr_m['height'] - prev_m['height']) / prev_m['height']) * 100
            if h_diff_prev > T_HEIGHT_WILT_SRT:
                is_triggered = True
                reason.append(f"직전 대비 급격한 스트레스 ({h_diff_prev:.1f}%)")

        # 3. 장기 성장 및 누적 상태 분석 (Current vs. 9 AM Baseline) 
        if ref_9am_m:
            h_diff_9am = ((curr_m['height'] - ref_9am_m['height']) / ref_9am_m['height']) * 100
        
            # 장기 성장 감지 (정(+)의 변화)
            if h_diff_9am > T_HEIGHT_GROWTH:
                is_triggered = True
                reason.append(f"오전 대비 유의미한 성장 ({h_diff_9am:.1f}%)")
                
            # 누적 시듦 감지 (부(-)의 변화)
            if h_diff_9am < -T_HEIGHT_WILT_ACC:
                is_triggered = True
                reason.append(f"오전 대비 누적 시듦/팽압 저하 ({abs(h_diff_9am):.1f}%)")

        return is_triggered, " | ".join(reason)

    def update_reference(self):
        """현재 사진을 다음 루프의 직전 사진으로 교체"""
        if os.path.exists(self.path_curr):
            shutil.copy(self.path_curr, self.path_prev)