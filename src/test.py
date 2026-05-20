from ultralytics import YOLO

# 다운로드한 best.pt 경로 입력
model = YOLO('best.pt')

# 이미지 한 장 예측해보기
results = model.predict(source="test_files/test_plants.jpg", save=True, conf=0.5)

# 결과 확인
results[0].show()