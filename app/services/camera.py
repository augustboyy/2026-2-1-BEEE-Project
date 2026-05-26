"""
이 파일은 실물 카메라를 제어하여 사진을 촬영하는 역할을 담당합니다.
"""

import cv2
import os
import tempfile
import time
from PIL import Image, ImageEnhance
from pathlib import Path

# 파일 기반 락 (Cross-process)
LOCK_FILE_PATH = Path(tempfile.gettempdir()) / "plant_pulse_camera.lock"
LOCK_STALE_SECONDS = 60
PICAM_STILL_RESOLUTION = (1920, 1080)
PICAM_WARMUP_SECONDS = 2.0


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True

class FileLock:
    def __enter__(self):
        for _ in range(50): # 최대 5초 대기
            try:
                # stale lock 체크
                if LOCK_FILE_PATH.exists():
                    stale = False
                    try:
                        raw = LOCK_FILE_PATH.read_text().strip()
                        pid_str, ts_str = raw.split(",", 1)
                        pid = int(pid_str)
                        lock_time = float(ts_str)
                        if not _is_process_alive(pid):
                            stale = True
                        elif time.time() - lock_time > LOCK_STALE_SECONDS:
                            stale = True
                    except Exception:
                        try:
                            if time.time() - LOCK_FILE_PATH.stat().st_mtime > LOCK_STALE_SECONDS:
                                stale = True
                        except Exception:
                            stale = False
                    if stale:
                        # 프로세스가 죽었거나 락이 오래된 경우 강제 삭제
                        try:
                            LOCK_FILE_PATH.unlink()
                        except Exception:
                            pass
                
                # 'x' 모드는 파일이 존재하면 FileExistsError 발생시킴 (Atomic)
                with open(LOCK_FILE_PATH, 'x') as f:
                    f.write(f"{os.getpid()},{time.time()}")
                return self
            except FileExistsError:
                time.sleep(0.1)
        raise RuntimeError("카메라 락을 획득할 수 없습니다. 다른 프로세스가 오랫동안 카메라를 점유하고 있습니다.")

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if LOCK_FILE_PATH.exists():
                os.remove(LOCK_FILE_PATH)
        except Exception:
            pass

def capture_photo_to_disk(file_path: str) -> None:
    """
    라즈베리파이 환경에서는 Picamera2로 8MP 정지화면을 캡처합니다.
    그 외 환경에서는 기본 카메라(0번)를 열어 디스크에 직접 저장합니다.
    """
    with FileLock():
        if _capture_with_picamera2(file_path):
            return
        cap = None
        
        # 카메라가 OS 레벨에서 릴리즈되는 데 시간이 걸릴 수 있으므로 재시도
        for attempt in range(3):
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                break
            cap.release()
            print(f"[Camera] 카메라 열기 재시도 중... ({attempt + 1}/3)")
            time.sleep(1.5)
            
        if not cap or not cap.isOpened():
            raise RuntimeError("카메라 장치를 열 수 없습니다. 장치가 연결되어 있는지 확인해 주세요.")
            
        try:
            # 최대 해상도(8MP 이상)로 설정 시도
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3264)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2448)
                
            # 조도 조절을 위해 여러 프레임 건너뛰기
            for _ in range(8):
                cap.read()
                time.sleep(0.1)
                
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError("카메라에서 유효한 프레임을 읽을 수 없습니다.")
                
            success = cv2.imwrite(file_path, frame)
            if not success:
                raise RuntimeError("사진을 디스크에 저장할 수 없습니다.")
        finally:
            if cap:
                cap.release()


def _capture_with_picamera2(file_path: str) -> bool:
    try:
        from picamera2 import Picamera2
    except Exception:
        return False

    picam2 = Picamera2()
    try:
        config = picam2.create_still_configuration(
            main={"size": PICAM_STILL_RESOLUTION},
            buffer_count=1,
        )
        picam2.configure(config)
        picam2.start()
        time.sleep(PICAM_WARMUP_SECONDS)
        picam2.capture_file(file_path)
    finally:
        try:
            picam2.stop()
        except Exception:
            pass
        try:
            picam2.close()
        except Exception:
            pass

    if not os.path.exists(file_path):
        raise RuntimeError("사진을 디스크에 저장할 수 없습니다.")
    return True

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
