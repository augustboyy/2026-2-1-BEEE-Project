"""
이 파일은 FastAPI 웹 애플리케이션의 메인 서버 코드입니다.
API 엔드포인트를 정의하고, 요청을 처리하며, 백그라운드 작업을 관리합니다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import build_runtime
from app.config import Settings, load_settings
from app.schemas import PlantActivationRequest, PlantCreateRequest, SensorLogRequest, WateringLogRequest


# 앱 관련 디렉토리 경로 설정
APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

# 상태값에 따른 한국어 레이블
STATUS_LABELS = {
    "healthy": "안정",
    "warning": "주의",
    "critical": "위험",
}


def _as_percent(value: float | None) -> int | None:
    """소수점 형태의 값을 퍼센트(0-100) 정수로 변환합니다."""
    if value is None:
        return None
    return max(0, min(100, round(float(value) * 100)))


def _derive_health_score(status: str | None, confidence: float | None) -> int:
    """
    상태와 신뢰도를 바탕으로 시각적인 '건강 점수'를 계산합니다.
    (실제 로직 변경 없이 주석만 추가)
    """
    confidence_percent = _as_percent(confidence)
    if status == "healthy":
        return max(88, confidence_percent or 0)
    if status == "warning":
        return max(45, min(75, confidence_percent or 62))
    if status == "critical":
        if confidence_percent is None:
            return 34
        return max(10, min(45, 100 - confidence_percent // 2))
    return confidence_percent or 72


def build_kiosk_payload(dashboard: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    """
    키오스크(웹 인터페이스)에 필요한 형식으로 데이터를 가공합니다.
    """
    if dashboard is None:
        return {
            "dashboard": None,
            "kiosk": {
                "has_plant": False,
                "demo_mode": settings.ai_provider == "mock",
                "message": "등록된 식물이 없습니다.",
            },
        }

    latest_state = dashboard.get("latest_state") or {}
    latest_analysis = dashboard.get("latest_analysis") or {}
    health_status = latest_analysis.get("health_status") or latest_state.get("latest_health_status")
    confidence = latest_analysis.get("confidence")
    if confidence is None:
        confidence = latest_state.get("latest_confidence")

    alert_level = health_status if health_status in {"warning", "critical"} else None
    can_confirm_action = bool(
        latest_analysis
        and alert_level
        and latest_analysis.get("id")
        and not latest_analysis.get("confirmed_at")
    )

    return {
        "dashboard": dashboard,
        "kiosk": {
            "has_plant": True,
            "demo_mode": settings.ai_provider == "mock",
            "health_status": health_status,
            "health_label": STATUS_LABELS.get(health_status, "대기"),
            "health_score": _derive_health_score(health_status, confidence),
            "confidence_percent": _as_percent(confidence),
            "alert_level": alert_level,
            "alert_message": (
                "AI 진단에서 즉시 확인이 필요한 상태가 감지되었습니다."
                if health_status == "critical"
                else "AI 진단에서 관리 주의가 필요한 상태가 감지되었습니다."
                if health_status == "warning"
                else None
            ),
            "latest_analysis_id": latest_analysis.get("id"),
            "can_confirm_action": can_confirm_action,
            "sensor_synced": bool(dashboard.get("latest_sensor_state")),
        },
    }


async def run_periodic_sensor_updates(app: FastAPI) -> None:
    """
    주기적으로 센서 데이터를 시뮬레이션하여 업데이트하는 백그라운드 태스크입니다.
    """
    settings: Settings = app.state.runtime.settings
    repository = app.state.runtime.repository
    monitoring_service = app.state.runtime.monitoring_service

    while True:
        await asyncio.sleep(settings.sensor_interval_seconds)
        plant = repository.get_current_plant()
        if plant is None:
            continue
        try:
            # 설정된 주기에 맞춰 데모 센서값을 생성합니다.
            monitoring_service.generate_demo_sensor(plant["id"], source="periodic-simulator")
        except Exception as error:
            # 실패 시 에러 로그를 기록합니다.
            repository.add_error(
                source="periodic-sensor-loop",
                message="주기 센서 시뮬레이션 저장에 실패했습니다.",
                metadata={"error": str(error)},
                plant_id=plant["id"],
            )


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    """
    FastAPI 애플리케이션 인스턴스를 생성하고 라우트를 설정합니다.
    """
    runtime = build_runtime(custom_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """앱의 시작과 종료 시 실행될 로직을 정의합니다."""
        app.state.runtime = runtime
        sensor_task = None
        # 센서 루프가 활성화되어 있으면 백그라운드 태스크를 시작합니다.
        if runtime.settings.enable_sensor_loop:
            sensor_task = asyncio.create_task(run_periodic_sensor_updates(app))

        try:
            yield
        finally:
            # 앱 종료 시 태스크 취소 및 DB 연결 해제
            if sensor_task:
                sensor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sensor_task
            runtime.database.close()

    app = FastAPI(title=runtime.settings.app_name, lifespan=lifespan)
    # 정적 파일(JS, CSS 등) 제공 설정
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- 화면 관련 ---
    @app.get("/kiosk")
    async def kiosk() -> FileResponse:
        """키오스크 HTML 페이지를 반환합니다."""
        return FileResponse(TEMPLATES_DIR / "kiosk.html", media_type="text/html")

    # --- API 엔드포인트 ---
    @app.get("/api/health")
    async def health() -> dict:
        """API 서버 및 AI 설정 상태를 확인합니다."""
        current_plant = runtime.repository.get_current_plant()
        return {
            "status": "ok",
            "app_name": runtime.settings.app_name,
            "ai_provider": runtime.settings.ai_provider,
            "active_plant_id": current_plant["id"] if current_plant else None,
            "sensor_loop_enabled": runtime.settings.enable_sensor_loop,
        }

    @app.get("/api/plants")
    async def list_plants() -> dict:
        """등록된 모든 식물 목록을 가져옵니다."""
        return {"plants": runtime.repository.list_plants()}

    @app.get("/api/plants/current")
    async def current_dashboard() -> dict:
        """현재 활성화된 식물의 대시보드 데이터를 가져옵니다."""
        plant = runtime.repository.get_current_plant()
        return {"dashboard": runtime.repository.build_dashboard(plant["id"]) if plant else None}

    @app.get("/api/kiosk/state")
    async def kiosk_state() -> dict:
        """키오스크 화면용 가공된 상태 데이터를 반환합니다."""
        plant = runtime.repository.get_current_plant()
        dashboard_payload = runtime.repository.build_dashboard(plant["id"]) if plant else None
        return build_kiosk_payload(dashboard_payload, runtime.settings)

    @app.post("/api/plants")
    async def create_plant(payload: PlantCreateRequest) -> dict:
        """새로운 식물을 등록합니다."""
        return {"dashboard": runtime.monitoring_service.create_plant(payload.name, payload.species, payload.location)}

    @app.post("/api/plants/activate")
    async def activate_plant(payload: PlantActivationRequest) -> dict:
        """특정 식물을 활성 세션으로 전환합니다."""
        dashboard = runtime.monitoring_service.activate_plant(payload.plant_id)
        if dashboard is None:
            raise HTTPException(status_code=404, detail="식물 정보를 찾을 수 없습니다.")
        return {"dashboard": dashboard}

    @app.get("/api/plants/{plant_id}/dashboard")
    async def dashboard(plant_id: int) -> dict:
        """특정 식물의 대시보드 데이터를 가져옵니다."""
        dashboard_payload = runtime.repository.build_dashboard(plant_id)
        if dashboard_payload is None:
            raise HTTPException(status_code=404, detail="식물 정보를 찾을 수 없습니다.")
        return {"dashboard": dashboard_payload}

    @app.post("/api/plants/{plant_id}/sensor-logs")
    async def add_sensor_log(plant_id: int, payload: SensorLogRequest) -> dict:
        """수동으로 센서 로그를 추가합니다."""
        try:
            log = runtime.monitoring_service.log_sensor(plant_id, payload)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "sensor_log": log,
            "dashboard": runtime.repository.build_dashboard(plant_id),
        }

    @app.post("/api/external/sensor-data")
    async def receive_external_sensor_data(payload: SensorLogRequest) -> dict:
        """외부 장치로부터 센서 데이터를 수신합니다."""
        if payload.plant_id is None:
            raise HTTPException(status_code=400, detail="plant_id is required.")
        try:
            log = runtime.monitoring_service.log_sensor(payload.plant_id, payload)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "sensor_log": log,
            "dashboard": runtime.repository.build_dashboard(payload.plant_id),
        }

    @app.post("/api/plants/{plant_id}/watering-logs")
    async def add_watering_log(plant_id: int, payload: WateringLogRequest) -> dict:
        """급수 기록을 추가합니다."""
        try:
            log = runtime.monitoring_service.log_watering(plant_id, payload)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "watering_log": log,
            "dashboard": runtime.repository.build_dashboard(plant_id),
        }

    @app.post("/api/plants/{plant_id}/demo-sensor")
    async def create_demo_sensor(plant_id: int) -> dict:
        """테스트용 데모 센서 데이터를 생성합니다."""
        dashboard_payload = runtime.monitoring_service.generate_demo_sensor(plant_id)
        if dashboard_payload is None:
            raise HTTPException(status_code=404, detail="식물 정보를 찾을 수 없습니다.")
        return {"dashboard": dashboard_payload}

    @app.post("/api/plants/{plant_id}/analyze-photo")
    async def analyze_photo(
        plant_id: int,
        image: UploadFile = File(...),
        note: str | None = Form(default=None),
    ) -> dict:
        """식물 사진을 업로드하여 외부 AI(GPT, Gemini 등)에게 분석을 요청합니다."""
        try:
            payload = await runtime.monitoring_service.analyze_uploaded_photo(
                plant_id=plant_id,
                file_name=image.filename or "plant-image.jpg",
                file_bytes=await image.read(),
                content_type=image.content_type,
                note=note,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return payload

    @app.post("/api/analyses/{analysis_id}/confirm")
    async def confirm_analysis(analysis_id: int) -> dict:
        """사용자가 AI의 분석 결과를 확인했음을 기록합니다."""
        dashboard_payload = runtime.monitoring_service.confirm_analysis(analysis_id)
        if dashboard_payload is None:
            raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
        return {"dashboard": dashboard_payload}

    return app


# 애플리케이션 인스턴스 생성
app = create_app()


if __name__ == "__main__":
    # 서버 직접 실행 시 사용되는 설정
    settings = load_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
