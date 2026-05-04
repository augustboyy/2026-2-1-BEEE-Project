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
        Path(self.settings.uploads_dir).mkdir(parents=True, exist_ok=True)

    def create_plant(self, name: str, species: str | None = None, location: str | None = None) -> dict:
        plant = self.repository.create_plant(name, species, location)
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
        plant = self.repository.activate_plant(plant_id)
        if plant is None:
            return None
        return self.repository.build_dashboard(plant_id)

    def log_sensor(self, plant_id: int, payload: SensorLogRequest) -> dict:
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("Plant not found")
        return self.repository.add_sensor_log(
            plant_id,
            payload.moisture_value,
            payload.humidity,
            payload.temperature,
            payload.light_level,
            payload.source,
        )

    def log_watering(self, plant_id: int, payload: WateringLogRequest) -> dict:
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("Plant not found")
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
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("Plant not found")

        mime_type = content_type or self._detect_mime_type(file_bytes)
        self._validate_upload(file_name, file_bytes, mime_type)
        image_path = self._store_image(file_name, file_bytes)

        latest_sensor = self.repository.get_latest_sensor_state(plant_id)
        latest_watering = self.repository.get_latest_watering_log(plant_id)

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
        analysis = self.repository.confirm_analysis(analysis_id)
        if analysis is None:
            return None
        return self.repository.build_dashboard(analysis["plant_id"])

    def _validate_upload(self, file_name: str, file_bytes: bytes, mime_type: str) -> None:
        if not file_name:
            raise ValueError("사진 파일 이름이 비어 있습니다.")
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValueError(f"업로드 가능한 최대 용량은 {self.settings.max_upload_mb}MB 입니다.")
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("지원하는 이미지 형식은 JPG, PNG, WEBP 입니다.")

    def _store_image(self, file_name: str, file_bytes: bytes) -> str:
        extension = Path(file_name).suffix.lower() or ".jpg"
        safe_name = f"{uuid.uuid4().hex}{extension}"
        target_path = Path(self.settings.uploads_dir) / safe_name
        target_path.write_bytes(file_bytes)
        return str(target_path.resolve())

    def _detect_mime_type(self, file_bytes: bytes) -> str:
        with Image.open(BytesIO(file_bytes)) as image:
            detected = (image.format or "JPEG").upper()
        if detected == "PNG":
            return "image/png"
        if detected == "WEBP":
            return "image/webp"
        return "image/jpeg"
