import os
from pathlib import Path
from ultralytics import YOLO

def main():
    # 프로젝트 루트 경로 계산
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    
    # data.yaml 파일의 절대 경로 설정
    data_yaml_path = PROJECT_ROOT / "data" / "leaves.v1i.yolov8" / "data.yaml"
    
    if not data_yaml_path.exists():
        print(f"오류: 데이터셋 설정 파일을 찾을 수 없습니다: {data_yaml_path}")
        return

    print("YOLOv8 모델을 초기화합니다...")
    # 사전 학습된 가벼운 nano 모델을 기반으로 시작 (만약 기존 가중치에서 이어서 학습하려면 'weights/best.pt' 사용 가능)
    model = YOLO('yolov8n.pt') 

    print(f"학습을 시작합니다... (데이터셋: {data_yaml_path})")
    
    # 학습 실행
    # 윈도우 개발 PC 환경과 라즈베리파이 배포를 고려한 기본 파라미터입니다.
    results = model.train(
        data=str(data_yaml_path),
        epochs=50,                  # 전체 데이터셋을 몇 번 반복 학습할지 (기본 50, 상황에 따라 조절)
        patience=15,                # 15 epoch 동안 성능 향상이 없으면 조기 종료 (과적합 방지)
        batch=16,                   # 한 번에 처리할 이미지 수 (메모리가 부족하면 8로 줄이세요)
        imgsz=640,                  # 학습에 사용할 이미지 크기
        project=str(PROJECT_ROOT / "runs" / "train"), # 학습 결과물이 저장될 최상위 폴더
        name="leaf_detection",      # 현재 학습 결과가 저장될 폴더 이름
        workers=0,                  # 윈도우 환경 오류 방지를 위해 workers=0 설정 권장
        # device=0                  # 만약 윈도우에 NVIDIA GPU(CUDA)가 있다면 주석을 해제하세요. (주석 처리 시 자동 판별)
    )
    
    print("\n========================================================")
    print("🎉 학습이 성공적으로 완료되었습니다!")
    new_weights_path = PROJECT_ROOT / "runs" / "train" / "leaf_detection" / "weights" / "best.pt"
    print(f"👉 새로운 모델 가중치 저장 위치: {new_weights_path}")
    print("적용하시려면 위 위치의 best.pt를 프로젝트의 'weights/' 폴더 안으로 덮어쓰기 하세요.")
    print("========================================================")

if __name__ == '__main__':
    main()
