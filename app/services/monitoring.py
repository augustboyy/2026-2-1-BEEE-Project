"""
이 파일은 애플리케이션의 핵심 비즈니스 로직을 담당하는 모니터링 서비스를 정의합니다.
식물 등록, 센서 데이터 로깅, 급수 기록 관리, 그리고 AI 사진 분석 프로세스를 총괄합니다.
저장소(Repository), AI 클라이언트, 시뮬레이터 등을 조합하여 상위 레이어(API 등)에 기능을 제공합니다.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.config import Settings
from app.repository import PlantRepository
from app.schemas import SensorLogRequest, WateringLogRequest
from app.services.ai_client import AIClient
from app.services.sensor_simulator import SensorSimulator


class MonitoringService:
    """모니터링 시스템의 핵심 기능을 조율하는 서비스 클래스입니다."""
    
    def __init__(
        self,
        settings: Settings,
        repository: PlantRepository,
        ai_client: AIClient,
        simulator: SensorSimulator,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.ai_client = ai_client
        self.simulator = simulator
        # 업로드 폴더가 없으면 생성합니다.
        Path(self.settings.uploads_dir).mkdir(parents=True, exist_ok=True)

    def create_plant(self, name: str, species: str | None = None, location: str | None = None) -> dict:
        """식물을 새로 등록하고 초기 센서 데이터를 생성합니다."""
        plant = self.repository.create_plant(name, species, location)
        # 초기 센서 상태 시뮬레이션
        bootstrap_sensor = self.simulator.generate(plant, source="bootstrap-simulator")
        self.repository.add_sensor_log(
            plant["id"],
            bootstrap_sensor["moisture_value"],
            bootstrap_sensor["humidity"],
            bootstrap_sensor["temperature"],
            bootstrap_sensor["light_level"],
            bootstrap_sensor["source"],
        )
        return self.repository.build_dashboard(plant["id"])

    def activate_plant(self, plant_id: int) -> dict | None:
        """선택한 식물을 활성화하고 대시보드 데이터를 반환합니다."""
        plant = self.repository.activate_plant(plant_id)
        if plant is None:
            return None
        return self.repository.build_dashboard(plant_id)

    def log_sensor(self, plant_id: int, payload: SensorLogRequest) -> dict:
        """식물의 센서 로그를 기록합니다."""
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("식물을 찾을 수 없습니다.")
        return self.repository.add_sensor_log(
            plant_id,
            payload.moisture_value,
            payload.humidity,
            payload.temperature,
            payload.light_level,
            payload.source,
        )

    def log_watering(self, plant_id: int, payload: WateringLogRequest) -> dict:
        """식물의 급수 기록을 저장합니다."""
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("식물을 찾을 수 없습니다.")
        return self.repository.add_watering_log(
            plant_id=plant_id,
            mode=payload.mode,
            amount_ml=payload.amount_ml,
            duration_seconds=payload.duration_seconds,
            note=payload.note,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
        )

    def generate_demo_sensor(self, plant_id: int, source: str = "manual-simulator") -> dict | None:
        """테스트를 위한 데모 센서 데이터를 자동 생성하여 저장합니다."""
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            return None
        snapshot = self.simulator.generate(plant, source=source)
        self.repository.add_sensor_log(
            plant_id,
            snapshot["moisture_value"],
            snapshot["humidity"],
            snapshot["temperature"],
            snapshot["light_level"],
            snapshot["source"],
        )
        return self.repository.build_dashboard(plant_id)

    async def analyze_uploaded_photo(
        self,
        plant_id: int,
        file_name: str,
        file_bytes: bytes,
        content_type: str | None,
        note: str | None = None,
    ) -> dict:
        """
        사용자가 업로드한 사진을 외부 AI에게 보내 분석하고 결과를 저장하는 핵심 비즈니스 로직입니다.
        """
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("식물을 찾을 수 없습니다.")

        # 1. 이미지 검증 및 저장
        mime_type = content_type or self._detect_mime_type(file_bytes)
        self._validate_upload(file_name, file_bytes, mime_type)
        image_path = self._store_image(file_name, file_bytes)

        # 2. AI 분석을 위해 최신 센서/급수 데이터 가져오기
        latest_sensor = self.repository.get_latest_sensor_state(plant_id)
        latest_watering = self.repository.get_latest_watering_log(plant_id)

        # 3. 외부 AI 호출 (OpenAI/Gemini 등)
        try:
            ai_payload = await self.ai_client.analyze_plant_photo(
                plant=plant,
                image_bytes=file_bytes,
                mime_type=mime_type,
                latest_sensor=latest_sensor,
                latest_watering=latest_watering,
                note=note,
            )
        except Exception as error:
            self.repository.add_error(
                source="ai-analysis",
                message="외부 AI 사진 분석 요청이 실패했습니다.",
                metadata={"error": str(error), "provider": self.settings.ai_provider},
                plant_id=plant_id,
            )
            raise

        # 4. 분석 결과 및 사진 정보를 DB에 원자적으로(Transaction) 저장
        with self.repository.database.transaction():
            uploaded_image = self.repository.save_uploaded_image(plant_id, image_path, file_name, mime_type)
            camera_capture = self.repository.save_camera_capture(
                plant_id=plant_id,
                purpose="manual_upload",
                image_path=image_path,
                image_id=uploaded_image["id"],
                original_name=file_name,
                mime_type=mime_type,
                metadata={"note": note},
            )
            analysis = self.repository.add_analysis_result(
                plant_id=plant_id,
                job_id=str(uuid.uuid4()),
                image_id=uploaded_image["id"],
                provider=ai_payload["provider"],
                model_name=ai_payload["model_name"],
                request_note=note,
                prompt_text=ai_payload["prompt_text"],
                response_json=ai_payload["result"],
                raw_response_text=ai_payload["raw_response_text"],
                camera_capture_id=camera_capture["id"],
            )
        return {
            "analysis": analysis,
            "dashboard": self.repository.build_dashboard(plant_id),
        }

    def confirm_analysis(self, analysis_id: int) -> dict | None:
        """사용자가 AI 분석 결과를 확인했음을 처리합니다."""
        analysis = self.repository.confirm_analysis(analysis_id)
        if analysis is None:
            return None
        return self.repository.build_dashboard(analysis["plant_id"])

    # --- 헬퍼 메서드 ---
    def _validate_upload(self, file_name: str, file_bytes: bytes, mime_type: str) -> None:
        """업로드된 파일의 유효성(이름, 용량, 형식)을 검사합니다."""
        if not file_name:
            raise ValueError("사진 파일 이름이 비어 있습니다.")
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValueError(f"업로드 가능한 최대 용량은 {self.settings.max_upload_mb}MB 입니다.")
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("지원하는 이미지 형식은 JPG, PNG, WEBP 입니다.")

    def _store_image(self, file_name: str, file_bytes: bytes) -> str:
        """이미지를 고유한 이름으로 서버 로컬 저장소에 저장합니다."""
        extension = Path(file_name).suffix.lower() or ".jpg"
        safe_name = f"{uuid.uuid4().hex}{extension}"
        target_path = Path(self.settings.uploads_dir) / safe_name
        target_path.write_bytes(file_bytes)
        return str(target_path.resolve())

    def _detect_mime_type(self, file_bytes: bytes) -> str:
        """바이트 데이터를 분석하여 이미지의 MIME 타입을 감지합니다."""
        with Image.open(BytesIO(file_bytes)) as image:
            detected = (image.format or "JPEG").upper()
        if detected == "PNG":
            return "image/png"
        if detected == "WEBP":
            return "image/webp"
        return "image/jpeg"
