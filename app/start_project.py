"""
이 파일은 프로젝트의 메인 진입점(Entry Point)입니다.
FastAPI 기반의 API 서버와 Streamlit 기반의 대시보드를 동시에 실행하는 역할을 합니다.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# 패키지 실행/스크립트 실행 모두에서 app 모듈을 찾도록 프로젝트 루트를 보장합니다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    env.setdefault("SERIAL_PORT", "auto")
    env.setdefault("SERIAL_BAUD", "115200")
    env.setdefault("SERIAL_TIMEOUT", "1.0")
    env.setdefault("SERIAL_RECONNECT_DELAY", "5.0")

    # 프로세스 그룹/세션 생성 옵션 (하위 프로세스 통째로 종료하기 위함)
    popen_kwargs = {}
    if os.name == 'nt':
        popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs['start_new_session'] = True

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
        **popen_kwargs
    )

    dashboard_script = str((PROJECT_ROOT / "app" / "dashboard.py").resolve())
    local_ai_script = str((PROJECT_ROOT / "app" / "local_AI.py").resolve())
    serial_listener_script = str((PROJECT_ROOT / "app" / "serial_listener.py").resolve())

    # 2. 대시보드 (Streamlit) 실행
    dashboard_process = subprocess.Popen(
        [
            python_executable,
            "-m",
            "streamlit",
            "run",
            dashboard_script,
            "--server.headless=true",
            f"--server.address={settings.dashboard_host}",
            f"--server.port={settings.dashboard_port}",
        ],
        env=env,
        **popen_kwargs
    )

    # 3. 로컬 AI 카메라 서비스 실행 (10분 간격 촬영)
    local_ai_process = subprocess.Popen(
        [python_executable, local_ai_script],
        env=env,
        **popen_kwargs
    )
    
    # 4. 시리얼 리스너 실행 (SERIAL_PORT가 설정된 경우)
    serial_process = subprocess.Popen(
        [python_executable, serial_listener_script],
        env=env,
        **popen_kwargs
    )

    # 실행 중인 서버들의 주소를 출력합니다.
    print(f"API: {settings.api_base_url}/api/health")
    print(f"Dashboard: http://{settings.dashboard_host}:{settings.dashboard_port}")
    print("Local AI: Background camera service started (10-min interval)")
    print("Serial Listener: Arduino JSON listener started")
    print("중지하려면 Ctrl+C 를 누르세요.")

    try:
        # 프로세스들이 실행 중인 동안 무한 루프를 돌며 상태를 체크합니다.
        while True:
            # 어느 한 프로세스라도 종료되면 루프를 빠져나갑니다.
            if (api_process.poll() is not None or 
                dashboard_process.poll() is not None or 
                local_ai_process.poll() is not None):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        # 사용자가 Ctrl+C를 눌렀을 때의 예외 처리입니다.
        print("\n종료 신호를 받았습니다. 모든 프로세스를 종료합니다...")
        pass
    finally:
        # OS별 하위 프로세스 트리 완벽 종료 로직 (윈도우 & 라즈베리파이/리눅스 호환)
        processes = [local_ai_process, dashboard_process, api_process]
        processes.insert(0, serial_process)
        for process in processes:
            if process.poll() is None:
                try:
                    if os.name == 'nt':
                        # 윈도우: CTRL_BREAK_EVENT를 프로세스 그룹에 전송하여 하위 트리까지 종료
                        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
                        # 안전장치로 taskkill도 한 번 더 시도
                        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        # 리눅스/라즈베리파이: 프로세스 그룹 ID(PGID)를 찾아 SIGTERM 전송
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except Exception as e:
                    # 실패 시 최후의 수단으로 기본 terminate 호출
                    process.terminate()
        
        # 프로세스들이 완전히 죽을 때까지 잠시 대기
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill() # 3초 후에도 안 죽으면 강제 킬(SIGKILL)

if __name__ == "__main__":
    main()
