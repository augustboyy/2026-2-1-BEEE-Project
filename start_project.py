from __future__ import annotations

import os
import subprocess
import sys
import time

from app.config import load_settings


def main() -> None:
    settings = load_settings()
    python_executable = sys.executable
    env = os.environ.copy()

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

    print(f"API: {settings.api_base_url}/api/health")
    print(f"Dashboard: http://{settings.dashboard_host}:{settings.dashboard_port}")
    print("중지하려면 Ctrl+C 를 누르세요.")

    try:
        while True:
            if api_process.poll() is not None or dashboard_process.poll() is not None:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (dashboard_process, api_process):
            if process.poll() is None:
                process.terminate()


if __name__ == "__main__":
    main()
