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
*주의: 커밋 시 업데이트된 `requirements.txt` 파일을 반드시 포함해 주세요.*
'requirments.txt는 반드시 main브랜치에서 수정하고 커밋해주세요!

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