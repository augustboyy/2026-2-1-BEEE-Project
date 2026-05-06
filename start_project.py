"""
이 파일은 프로젝트의 메인 진입점(Entry Point)입니다.
FastAPI 기반의 API 서버와 Streamlit 기반의 대시보드를 동시에 실행하는 역할을 합니다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from app.config import load_settings


def main() -> None:
    """
    프로젝트의 전체 시스템을 시작하는 메인 함수입니다.
    설정 정보를 로드하고 API 서버와 대시보드를 서브프로세스로 실행합니다.
    """
    # 환경 설정(설정 정보)을 불러옵니다.
    settings = load_settings()
    # 현재 실행 중인 파이썬 실행 파일의 경로를 가져옵니다.
    python_executable = sys.executable
    # 현재 프로세스의 환경 변수를 복사합니다.
    env = os.environ.copy()

    # 1. API 서버 (FastAPI + Uvicorn) 실행
    api_process = subprocess.Popen(
        [
            python_executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            settings.app_host,
            "--port",
            str(settings.app_port),
        ],
        env=env,
    )

    # 2. 대시보드 (Streamlit) 실행
    dashboard_process = subprocess.Popen(
        [
            python_executable,
            "-m",
            "streamlit",
            "run",
            "dashboard.py",
            "--server.headless=true",
            f"--server.address={settings.dashboard_host}",
            f"--server.port={settings.dashboard_port}",
        ],
        env=env,
    )

    # 실행 중인 서버들의 주소를 출력합니다.
    print(f"API: {settings.api_base_url}/api/health")
    print(f"Dashboard: http://{settings.dashboard_host}:{settings.dashboard_port}")
    print("중지하려면 Ctrl+C 를 누르세요.")

    try:
        # 프로세스들이 실행 중인 동안 무한 루프를 돌며 상태를 체크합니다.
        while True:
            # 어느 한 프로세스라도 종료되면 루프를 빠져나갑니다.
            if api_process.poll() is not None or dashboard_process.poll() is not None:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        # 사용자가 Ctrl+C를 눌렀을 때의 예외 처리입니다.
        pass
    finally:
        # 프로그램 종료 시 실행 중인 서브프로세스들을 안전하게 종료합니다.
        for process in (dashboard_process, api_process):
            if process.poll() is None:
                process.terminate()


if __name__ == "__main__":
    main()
