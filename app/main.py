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


APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

STATUS_LABELS = {
    "healthy": "안정",
    "warning": "주의",
    "critical": "위험",
}


def _as_percent(value: float | None) -> int | None:
    if value is None:
        return None
    return max(0, min(100, round(float(value) * 100)))


def _derive_health_score(status: str | None, confidence: float | None) -> int:
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
    settings: Settings = app.state.runtime.settings
    repository = app.state.runtime.repository
    monitoring_service = app.state.runtime.monitoring_service

    while True:
        await asyncio.sleep(settings.sensor_interval_seconds)
        plant = repository.get_current_plant()
        if plant is None:
            continue
        try:
            monitoring_service.generate_demo_sensor(plant["id"], source="periodic-simulator")
        except Exception as error:
            repository.add_error(
                source="periodic-sensor-loop",
                message="주기 센서 시뮬레이션 저장에 실패했습니다.",
                metadata={"error": str(error)},
                plant_id=plant["id"],
            )


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    runtime = build_runtime(custom_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime
        sensor_task = None
        if runtime.settings.enable_sensor_loop:
            sensor_task = asyncio.create_task(run_periodic_sensor_updates(app))

        try:
            yield
        finally:
            if sensor_task:
                sensor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sensor_task
            runtime.database.close()

    app = FastAPI(title=runtime.settings.app_name, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/kiosk")
    async def kiosk() -> FileResponse:
        return FileResponse(TEMPLATES_DIR / "kiosk.html", media_type="text/html")

    @app.get("/api/health")
    async def health() -> dict:
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
        return {"plants": runtime.repository.list_plants()}

    @app.get("/api/plants/current")
    async def current_dashboard() -> dict:
        plant = runtime.repository.get_current_plant()
        return {"dashboard": runtime.repository.build_dashboard(plant["id"]) if plant else None}

    @app.get("/api/kiosk/state")
    async def kiosk_state() -> dict:
        plant = runtime.repository.get_current_plant()
        dashboard_payload = runtime.repository.build_dashboard(plant["id"]) if plant else None
        return build_kiosk_payload(dashboard_payload, runtime.settings)

    @app.post("/api/plants")
    async def create_plant(payload: PlantCreateRequest) -> dict:
        return {"dashboard": runtime.monitoring_service.create_plant(payload.name, payload.species, payload.location)}

    @app.post("/api/plants/activate")
    async def activate_plant(payload: PlantActivationRequest) -> dict:
        dashboard = runtime.monitoring_service.activate_plant(payload.plant_id)
        if dashboard is None:
            raise HTTPException(status_code=404, detail="식물 정보를 찾을 수 없습니다.")
        return {"dashboard": dashboard}

    @app.get("/api/plants/{plant_id}/dashboard")
    async def dashboard(plant_id: int) -> dict:
        dashboard_payload = runtime.repository.build_dashboard(plant_id)
        if dashboard_payload is None:
            raise HTTPException(status_code=404, detail="식물 정보를 찾을 수 없습니다.")
        return {"dashboard": dashboard_payload}

    @app.post("/api/plants/{plant_id}/sensor-logs")
    async def add_sensor_log(plant_id: int, payload: SensorLogRequest) -> dict:
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
        dashboard_payload = runtime.monitoring_service.confirm_analysis(analysis_id)
        if dashboard_payload is None:
            raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
        return {"dashboard": dashboard_payload}

    return app


app = create_app()


if __name__ == "__main__":
    settings = load_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
