"""
이 파일은 실물 카메라를 제어하여 사진을 촬영하는 역할을 담당합니다.
"""

import cv2

def capture_photo() -> bytes:
    """
    기본 카메라(0번)를 열어 사진을 한 장 촬영하고 JPEG 바이트로 반환합니다.
    """
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("카메라 장치를 열 수 없습니다. 장치가 연결되어 있는지 확인해 주세요.")
        
    # 센서 초기화 및 초점 조절을 위해 프레임을 몇 번 읽어서 버립니다.
    for _ in range(5):
        cap.read()
        
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        raise RuntimeError("카메라에서 사진을 촬영할 수 없습니다.")
        
    success, buffer = cv2.imencode(".jpg", frame)
    if not success:
        raise RuntimeError("사진을 JPEG로 인코딩할 수 없습니다.")
        
    return buffer.tobytes()
