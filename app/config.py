from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


@dataclass(slots=True)
class Settings:
    app_name: str
    app_host: str
    app_port: int
    api_base_url: str
    dashboard_host: str
    dashboard_port: int
    database_path: str
    uploads_dir: str
    sensor_interval_seconds: int
    enable_sensor_loop: bool
    ai_provider: str
    ai_timeout_seconds: float
    max_upload_mb: int
    openai_api_key: str | None
    openai_model: str
    gemini_api_key: str | None
    gemini_model: str


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    app_host = os.getenv("APP_HOST", "127.0.0.1")
    app_port = int(os.getenv("APP_PORT", "8000"))
    api_base_url = os.getenv("API_BASE_URL", f"http://127.0.0.1:{app_port}")
    dashboard_host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    dashboard_port = int(os.getenv("DASHBOARD_PORT", "8501"))

    return Settings(
        app_name=os.getenv("APP_NAME", "Plant Pulse Vision Dashboard"),
        app_host=app_host,
        app_port=app_port,
        api_base_url=api_base_url,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        database_path=_resolve_path(os.getenv("DATABASE_PATH", "data/plant_monitor.db")),
        uploads_dir=_resolve_path(os.getenv("UPLOADS_DIR", "data/uploads")),
        sensor_interval_seconds=int(os.getenv("SENSOR_INTERVAL_SECONDS", "15")),
        enable_sensor_loop=_get_bool("ENABLE_SENSOR_LOOP", True),
        ai_provider=os.getenv("AI_PROVIDER", "mock").strip().lower(),
        ai_timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "20")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    )
