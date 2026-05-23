"""
이 파일은 실물 카메라를 제어하여 사진을 촬영하는 역할을 담당합니다.
"""

import cv2
import os
from PIL import Image, ImageEnhance

def capture_photo_to_disk(file_path: str) -> None:
    """
    기본 카메라(0번)를 열어 사진을 한 장 촬영하고, 메모리를 최소화하며 디스크에 직접 저장합니다.
    라즈베리파이의 카메라(예: 8MP) 고해상도 원본 사진을 디스크에 기록합니다.
    """
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("카메라 장치를 열 수 없습니다. 장치가 연결되어 있는지 확인해 주세요.")
        
    # 최대 해상도(8MP 이상)로 설정 시도
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3264)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2448)
        
    for _ in range(5):
        cap.read()
        
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        raise RuntimeError("카메라에서 사진을 촬영할 수 없습니다.")
        
    # cv2.imwrite는 인코딩 결과를 파이썬 RAM에 크게 들고 있지 않고 디스크에 직접 기록합니다.
    success = cv2.imwrite(file_path, frame)
    if not success:
        raise RuntimeError("사진을 디스크에 저장할 수 없습니다.")

def create_preprocessed_temp(original_path: str, temp_path: str, max_dim: int, apply_enhancement: bool = False) -> None:
    """
    디스크에 있는 고해상도(8MP) 이미지를 읽어들여, 지정된 최대 긴 축(max_dim)에 맞춰
    비율을 유지하며 축소한 뒤, 다른 임시 파일로 저장합니다. 
    메모리 절약을 위해 처리 직후 객체를 해제합니다.
    """
    try:
        # PIL은 JPEG 로딩 시 thumbnail을 쓰면 디코딩 단계에서부터 메모리를 절약할 수 있습니다.
        with Image.open(original_path) as img:
            img.thumbnail((max_dim, max_dim))
            
            if apply_enhancement:
                # 식물 잎맥 및 병변 판단을 돕기 위해 대비(Contrast)를 1.2배 향상
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.2)
                
            # 품질 85로 저장하여 용량 최적화
            img.save(temp_path, format="JPEG", quality=85)
    except Exception as e:
        raise RuntimeError(f"이미지 전처리 중 오류 발생: {e}")
