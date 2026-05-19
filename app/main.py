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
from fastapi.responses import FileResponse, RedirectResponse
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


def build_kiosk_payload(dashboard: dict[str, Any] | None, settings: Settings) -> dict[str, Any]:
    """
    키오스크(웹 인터페이스)에 필요한 형식으로 데이터를 가공합니다.
    """
    if dashboard is None:
        return {
            "dashboard": None,
            "kiosk": {
                "has_plant": False,
                "message": "등록된 식물이 없습니다.",
            },
        }

    latest_state = dashboard.get("latest_state") or {}
    latest_analysis = dashboard.get("latest_analysis") or {}
    health_status = latest_analysis.get("health_status") or latest_state.get("latest_health_status")
    
    # AI가 직접 분석한 건강 점수 (0점도 유효한 값이므로 명시적 None 체크)
    health_score = latest_analysis.get("health_score")
    if health_score is None:
        health_score = latest_state.get("latest_health_score")
    
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
            "health_status": health_status,
            "health_label": STATUS_LABELS.get(health_status, "대기"),
            "health_score": health_score if health_score is not None else 100,  # 기본값 100
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


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    """
    FastAPI 애플리케이션 인스턴스를 생성하고 라우트를 설정합니다.
    """
    runtime = build_runtime(custom_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """앱의 시작과 종료 시 실행될 로직을 정의합니다."""
        app.state.runtime = runtime

        try:
            yield
        finally:
            # 앱 종료 시 DB 연결 해제
            runtime.database.close()

    app = FastAPI(title=runtime.settings.app_name, lifespan=lifespan)
    # 정적 파일(JS, CSS 등) 제공 설정
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- 화면 관련 ---
    @app.get("/")
    async def root() -> RedirectResponse:
        """루트 경로 접속 시 키오스크 화면으로 리다이렉트합니다."""
        return RedirectResponse(url="/kiosk")

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
            "active_plant_id": current_plant["id"] if current_plant else None,
        }

    @app.post("/api/plants/identify-species")
    async def identify_species() -> dict:
        """카메라로 실물 사진을 찍어 식물의 종을 추정합니다."""
        try:
            species = await runtime.monitoring_service.ai_client.identify_plant_species()
            return {"species": species}
        except Exception as error:
            import sys
            # 터미널(백그라운드)에 상세 에러(문구만) 출력
            print(f"\n[Error] 이미지 식물 추정 실패: {str(error)}", file=sys.stderr)
            # 클라이언트(키오스크)에는 일반적인 메시지만 반환
            raise HTTPException(
                status_code=500, 
                detail="식물 종 추정에 실패했습니다. 다시 시도해 주세요."
            )

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
