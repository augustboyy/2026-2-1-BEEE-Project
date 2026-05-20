# Plant Pulse Vision Dashboard

식물 사진을 외부 AI(GPT 또는 Gemini)에 HTTP로 보내 분석하고, 그 결과를 센서값과 급수 기록과 함께 SQLite에 저장한 뒤 Streamlit 대시보드에 표시하는 프로젝트입니다.

## 프로젝트 목표

- 식물 사진 분석 결과를 외부 AI에서 받아오기
- 토양 수분, 온도, 습도, 광량 같은 센서 데이터를 주기적으로 저장하기
- 급수 기록과 AI 분석 기록을 한 DB에서 함께 관리하기
- 사용자가 현재 상태, 최신 AI 조언, 업데이트 시각, 확인 시각을 한 번에 이해할 수 있게 하기

## 구조

### 1. 수신과 저장

- FastAPI가 센서 JSON 수신과 사진 업로드 분석 요청을 담당합니다.
- 외부 AI 호출은 모두 HTTP로 처리합니다.
- SQLite는 다음 테이블을 사용합니다.
  - `plants`
  - `uploaded_images`
  - `sensor_logs`
  - `latest_sensor_state`
  - `watering_logs`
  - `analysis_results`
  - `latest_state`
  - `activity_logs`
  - `error_logs`

### 2. AI 분석

- `AI_PROVIDER=mock | openai | gemini` 중 하나를 선택할 수 있습니다.
- `openai` 선택 시 사진을 OpenAI Vision 모델에 전송합니다.
- `gemini` 선택 시 사진을 Gemini Vision 모델에 전송합니다.
- 응답은 JSON 표준 형식으로 정규화해서 저장합니다.

### 3. 화면

- Streamlit 대시보드가 DB를 읽어 현재 상태를 표시합니다.
- 시작 화면, 식물 등록, 사진 업로드 분석, 센서 입력, 급수 입력, 이력 확인 흐름을 제공합니다.

## 실행 방법

### 1. 가상환경 생성

```powershell
python -m venv .venv
```

### 2. 가상환경 활성화

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. 패키지 설치

```powershell
pip install -r requirements.txt
```

### 4. 전체 실행

```powershell
python start_project.py
```

실행 후 주소:

- API: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Dashboard: [http://127.0.0.1:8501](http://127.0.0.1:8501)

## 환경 변수

`.env.example`를 참고하세요.

### OpenAI 사용

```powershell
$env:AI_PROVIDER="openai"
$env:OPENAI_API_KEY="YOUR_KEY"
python start_project.py
```

프로젝트 안의 예시 파일:

- [`.env.openai.example`](C:\Users\nemoj\Documents\Rockstar Games\Desktop\전공기프로젝트\.env.openai.example)

### Gemini 사용

```powershell
$env:AI_PROVIDER="gemini"
$env:GEMINI_API_KEY="YOUR_KEY"
python start_project.py
```

프로젝트 안의 예시 파일:

- [`.env.gemini.example`](C:\Users\nemoj\Documents\Rockstar Games\Desktop\전공기프로젝트\.env.gemini.example)

## 라즈베리파이 센서 JSON 예시

기본 전송 형식은 아래와 같습니다.

```json
{
  "plant_id": 1,
  "moisture_value": 43.7,
  "humidity": 56.2,
  "temperature": 24.1,
  "light_level": 6280.0,
  "source": "raspberry-pi"
}
```

예시 파일:

- [`examples/raspberry_pi_sensor_payload.json`](C:\Users\nemoj\Documents\Rockstar Games\Desktop\전공기프로젝트\examples\raspberry_pi_sensor_payload.json)

HTTP 전송 대상:

- `POST /api/external/sensor-data`

라즈베리파이에서 한 번만 전송:

```powershell
python examples/raspberry_pi_send_sensor.py --plant-id 1
```

15초마다 반복 전송:

```powershell
python examples/raspberry_pi_send_sensor.py --plant-id 1 --loop --interval 15
```

예시 스크립트:

- [`examples/raspberry_pi_send_sensor.py`](C:\Users\nemoj\Documents\Rockstar Games\Desktop\전공기프로젝트\examples\raspberry_pi_send_sensor.py)

스크립트의 `read_sensor_values_real()` 함수에 실제 센서 라이브러리 코드를 넣으면 됩니다.

## 주요 API

- `POST /api/plants`
  식물 등록
- `POST /api/plants/activate`
  현재 활성 식물 전환
- `GET /api/plants/{plant_id}/dashboard`
  대시보드 데이터 조회
- `POST /api/plants/{plant_id}/sensor-logs`
  수동 센서값 저장
- `POST /api/external/sensor-data`
  외부 장치가 JSON 센서 데이터를 전송
- `POST /api/plants/{plant_id}/watering-logs`
  급수 기록 저장
- `POST /api/plants/{plant_id}/analyze-photo`
  사진 업로드 후 외부 AI 분석 요청
- `POST /api/analyses/{analysis_id}/confirm`
  사용자가 최신 AI 분석 결과를 확인 처리

## 테스트

```powershell
pytest
```
