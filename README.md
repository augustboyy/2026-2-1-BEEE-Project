# 2026-2-1 기초전자공학실험 프로젝트

이 프로젝트는 2026년 1학기 기초전자공학실험 과제를 위한 저장소입니다.

## 🤝 협업 규칙 (Git Flow)

효율적인 협업을 위해 아래의 Git 사용 규칙을 반드시 준수해 주세요.

### 1. 저장소 복제 (Clone)
프로젝트에 처음 참여할 때 저장소를 로컬 PC로 복제합니다.
```bash
git clone <원격-저장소-URL>
```

### 2. 환경 설정 (Setup)
개발에 사용한 파이썬 패키지를 관리하는 법

파이썬 패키지 설치 하는 법
```bash
# 필수 패키지 설치
pip install -r requirements.txt
```

### 3. 브랜치 전략 (Branching)
코드를 수정하거나 새로운 기능을 추가할 때는 **반드시 새로운 브랜치**를 생성해야 합니다.
- **Naming Convention:** `feature/기능이름` (예: `feature/sensor-data`, `feature/ai-model`)
- **브랜치 생성 및 이동:**
  ```bash
  git checkout -b feature/기능이름
  ```

### 3. 변경 사항 반영 (PR & Merge)
기능 구현이 완료되면 `main` 브랜치로 바로 머지하지 말고, **Pull Request (PR)**를 생성하여 팀원의 검토를 거칩니다.
1. 본인의 feature 브랜치에서 작업 완료 후 Push
2. GitHub/GitLab 등 원격 저장소에서 `main` 브랜치로의 PR 생성
3. 코드 리뷰 후 승인되면 Merge

### 4. 패키지 관리 (Dependency Management)
새로운 패키지를 설치하여 작업한 경우, 다른 팀원들도 동일한 환경을 갖출 수 있도록 `requirements.txt`를 업데이트해야 합니다.
```bash
# 새로운 패키지 설치 후 파일 업데이트
pip freeze > requirements.txt
```
*주의1: 커밋 시 업데이트된 `requirements.txt` 파일을 반드시 포함해 주세요.*

*주의2: `requirements.txt` 파일은 반드시 main브랜치에서 수정하고 커밋해주세요!*

---

## 🛠 필수 Git 명령어 가이드

협업을 위해 아래 명령어들의 사용법을 숙지해 주세요.

| 명령어 | 설명 |
| :--- | :--- |
| `git pull` | 원격 저장소의 최신 변경 내용을 로컬로 가져오기 |
| `git add <파일명>` | 변경된 파일을 스테이징 영역에 추가 |
| `git commit -m "메시지"` | 변경 사항을 기록 (커밋 메시지는 명확하게 작성) |
| `git push origin <브랜치명>` | 로컬 커밋을 원격 저장소에 업로드 |
| `git branch` | 현재 브랜치 목록 확인 |
| `git checkout <브랜치명>` | 다른 브랜치로 전환 |
| `git merge <브랜치명>` | 다른 브랜치의 변경 내용을 현재 브랜치로 병합 |

---

## 📁 프로젝트 구조
- `cloud-A.I.py`: AI 관련 메인 로직 (작업 예정)
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
python -m app.start_project
```

실행 후 주소:

- API: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Dashboard: [http://127.0.0.1:8501](http://127.0.0.1:8501)

## 환경 변수

`.env`를 참고하세요.

### OpenAI 사용

```powershell
$env:AI_PROVIDER="openai"
$env:OPENAI_API_KEY="YOUR_KEY"
python -m app.start_project
```

프로젝트 안의 예시 파일: (현재 저장소에는 포함되어 있지 않습니다)

### Gemini 사용

```powershell
$env:AI_PROVIDER="gemini"
$env:GEMINI_API_KEY="YOUR_KEY"
python -m app.start_project
```

프로젝트 안의 예시 파일: (현재 저장소에는 포함되어 있지 않습니다)

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

예시 파일 경로: `examples/raspberry_pi_sensor_payload.json` (현재 저장소에는 포함되어 있지 않습니다)

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

예시 스크립트 경로: `examples/raspberry_pi_send_sensor.py` (현재 저장소에는 포함되어 있지 않습니다)

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
## 📁 프로젝트 구조
- `cloud-A.I.py`: AI 관련 메인 로직 (작업 예정)

## 아두이노 센서 데이터 보내는 방법
- 필요한 실제 데이터:
1. 센서 데이터: 아두이노(Arduino), 라즈베리 파이(Raspberry Pi), 또는 ESP32와 같은 마이크로컨트롤러가 주기적으로 토양 수분, 온/습도, 조도 데이터를 측정해야 합니다.
2. 급수 데이터: 자동 급수 펌프가 작동할 때마다 작동 시간과 급수량을 전송해야 합니다.

  데이터 수신 방법 (REST API 활용):
  물리적 기기는 인터넷에 연결된 후, 다음 엔드포인트로 JSON 데이터를 POST 전송해야 합니다.

  ```bash
   * 센서 로그 수신 API (/api/external/sensor-data)

    POST http://(서버IP):8000/api/external/sensor-data
        {
        "plant_id": 1,
        "moisture_value": 42.5,
	    "humidity": 55.0,
        "temperature": 24.3,
        "light_level": 6500,
        "source": "arduino-sensor-node-1"
		}
   ```
