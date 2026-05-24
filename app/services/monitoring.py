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

WATERING_SIGNAL = "WATER!"
from app.services.ai_client import AIClient


class MonitoringService:
    """모니터링 시스템의 핵심 기능을 조율하는 서비스 클래스입니다."""
    
    def __init__(
        self,
        settings: Settings,
        repository: PlantRepository,
        ai_client: AIClient,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.ai_client = ai_client
        # 업로드 폴더가 없으면 생성합니다.
        Path(self.settings.uploads_dir).mkdir(parents=True, exist_ok=True)

    def create_plant(self, name: str, species: str | None = None, location: str | None = None) -> dict:
        """식물을 새로 등록합니다."""
        plant = self.repository.create_plant(name, species, location)
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
            plant_id=plant_id,
            moisture_value=payload.moisture_value,
            temperature=payload.temperature,
            source=payload.source,
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

    def log_watering_signal(self, plant_id: int | None, signal: str, source: str) -> dict:
        """외부 장치로부터 급수 신호를 받아 로그로 저장합니다."""
        clean_signal = signal.strip()
        if clean_signal != WATERING_SIGNAL:
            raise ValueError(f"지원하지 않는 급수 신호입니다: {clean_signal}")

        if plant_id is None:
            plant = self.repository.get_current_plant()
            if plant is None:
                raise LookupError("활성화된 식물이 없습니다.")
            plant_id = plant["id"]
        else:
            plant = self.repository.get_plant(plant_id)
            if plant is None:
                raise LookupError("식물을 찾을 수 없습니다.")

        return self.repository.add_watering_log(
            plant_id=plant_id,
            mode="external-signal",
            note=f"{source}:{clean_signal}",
        )

    async def analyze_uploaded_photo(
        self,
        plant_id: int,
        file_name: str,
        image_path: str,
        content_type: str | None,
        note: str | None = None,
        save_image: bool = True,
    ) -> dict:
        """
        사용자가 업로드한 사진을 외부 AI에게 보내 분석하고 결과를 저장하는 핵심 비즈니스 로직입니다.
        (메모리 부족 방지를 위해 bytes가 아닌 파일 경로 기반으로 처리)
        """
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("식물을 찾을 수 없습니다.")

        # 1. 파일 검증 (크기 제한 확인)
        import os
        if os.path.getsize(image_path) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"업로드 가능한 최대 용량은 {self.settings.max_upload_mb}MB 입니다.")

        mime_type = content_type or "image/jpeg"

        final_image_path = image_path
        if save_image:
            import shutil
            # 저장용 고유 경로 생성
            extension = Path(file_name).suffix.lower() or ".jpg"
            safe_name = f"{uuid.uuid4().hex}{extension}"
            target_path = Path(self.settings.uploads_dir) / safe_name
            # 임시 파일을 안전한 저장소로 복사 (이동하면 원본 보존 불가 상황 대비)
            shutil.copy2(image_path, target_path)
            final_image_path = str(target_path.resolve())

        # 2. AI 분석을 위해 최신 센서/급수 데이터 가져오기
        latest_sensor = self.repository.get_latest_sensor_state(plant_id)
        latest_watering = self.repository.get_latest_watering_log(plant_id)

        # 3. 외부 AI 호출 (이미 ai_client는 disk path를 받아 temp resizing을 처리함)
        try:
            # AI 호출 시에는 원본 파일 경로를 넘기고 내부에서 1536px로 리사이즈하여 전송
            # ai_client.analyze_plant_photo가 이미 bytes와 path를 모두 지원하는지 확인해야 하지만
            # 여기서는 path를 그대로 넘기기 위해 ai_client 코드를 점검해야 함.
            # 하지만 이미 ask_question은 path를 받음. analyze_plant_photo도 수정 필요함.
            ai_payload = await self.ai_client.analyze_plant_photo(
                plant=plant,
                image_path=final_image_path,  # bytes 대신 path 전달
                mime_type=mime_type,
                latest_sensor=latest_sensor,
                latest_watering=latest_watering,
                note=note,
            )
        except Exception as error:
            self.repository.add_error(
                source="ai-analysis",
                message="외부 AI 사진 분석 요청이 실패했습니다.",
                metadata={"error": str(error)},
                plant_id=plant_id,
            )
            if save_image and final_image_path != image_path:
                try: Path(final_image_path).unlink(missing_ok=True)
                except Exception: pass
            raise

        # 4. 분석 결과 및 사진 정보를 DB에 저장
        with self.repository.database.transaction():
            image_id = None
            camera_capture_id = None
            if save_image and final_image_path:
                uploaded_image = self.repository.save_uploaded_image(plant_id, final_image_path, file_name, mime_type)
                image_id = uploaded_image["id"]
                camera_capture = self.repository.save_camera_capture(
                    plant_id=plant_id,
                    purpose="manual_upload",
                    image_path=final_image_path,
                    image_id=image_id,
                    original_name=file_name,
                    mime_type=mime_type,
                    metadata={"note": note},
                )
                camera_capture_id = camera_capture["id"]

            analysis = self.repository.add_analysis_result(
                plant_id=plant_id,
                job_id=str(uuid.uuid4()),
                image_id=image_id,
                provider=ai_payload["provider"],
                model_name=ai_payload["model_name"],
                request_note=note,
                prompt_text=ai_payload["prompt_text"],
                response_json=ai_payload["result"],
                raw_response_text=ai_payload["raw_response_text"],
                camera_capture_id=camera_capture_id,
            )
        return {
            "analysis": analysis,
            "dashboard": self.repository.build_dashboard(plant_id),
        }

    async def trigger_abnormal_analysis(self, plant_id: int, note: str) -> dict:
        """
        이상이 감지되었을 때 정밀 분석(Gemini)을 수행합니다.
        """
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("식물을 찾을 수 없습니다.")

        latest_image = self.repository.get_latest_uploaded_image(plant_id)
        
        image_path = None
        file_name = "abnormal_trigger.jpg"
        mime_type = "image/jpeg"

        if latest_image and Path(latest_image["file_path"]).exists():
            image_path = latest_image["file_path"]
            file_name = latest_image["original_name"]
            mime_type = latest_image["mime_type"]
        else:
            from app.services.camera import capture_photo_to_disk
            import datetime
            import asyncio
            now_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name = f"auto_capture_{now_str}.jpg"
            image_path = str(Path(self.settings.uploads_dir) / file_name)
            try:
                await asyncio.to_thread(capture_photo_to_disk, image_path)
                new_img_record = self.repository.save_uploaded_image(
                    plant_id=plant_id,
                    file_path=image_path,
                    original_name=file_name,
                    mime_type=mime_type
                )
                latest_image = new_img_record 
            except Exception as e:
                self.repository.add_error("camera", f"이상 감지 자동 촬영 실패: {e}", plant_id=plant_id)
                raise

        # RAM에 올리지 않고 바로 경로로 전달
        result = await self.analyze_uploaded_photo(
            plant_id=plant_id,
            file_name=file_name,
            image_path=image_path,
            content_type=mime_type,
            note=note,
            save_image=False 
        )
        
        if latest_image and not result["analysis"]["image_id"]:
            self.repository.database.execute(
                "UPDATE analysis_results SET image_id = ? WHERE id = ?",
                (latest_image["id"], result["analysis"]["id"])
            )
            result["analysis"]["image_id"] = latest_image["id"]

        return result["analysis"]

    def confirm_analysis(self, analysis_id: int) -> dict | None:
        """사용자가 AI 분석 결과를 확인했음을 처리합니다."""
        analysis = self.repository.confirm_analysis(analysis_id)
        if analysis is None:
            return None
        return self.repository.build_dashboard(analysis["plant_id"])

    async def ask_question_with_camera(self, plant_id: int, question_text: str) -> dict:
        """
        사용자의 질문과 함께 실시간 사진을 찍어 Gemini에게 전달합니다.
        메모리 절약을 위해 임시 파일로 디스크에 저장한 뒤 AI 모듈에 경로만 넘깁니다.
        """
        plant = self.repository.get_plant(plant_id)
        if plant is None:
            raise LookupError("식물을 찾을 수 없습니다.")

        from app.services.camera import capture_photo_to_disk
        import os
        import uuid
        import asyncio

        # 임시 사진 파일 경로 (uploads_dir 내)
        temp_image_path = str(Path(self.settings.uploads_dir) / f"temp_qa_{uuid.uuid4().hex}.jpg")

        try:
            # 1. RAM에 사진 바이트를 담지 않고 디스크로 바로 저장 (이벤트 루프 차단 방지)
            await asyncio.to_thread(capture_photo_to_disk, temp_image_path)

            # 2. AI 질문 호출 (디스크 경로를 전달하여 내부에서 lazy loading 수행)
            answer_text = await self.ai_client.ask_plant_question(plant, temp_image_path, question_text)

            # 3. DB에 Q&A 기록 저장
            question_record = self.repository.save_user_question(
                plant_id=plant_id,
                question_text=question_text,
                answer_text=answer_text,
                provider="gemini",
                model_name=self.ai_client.model_id
            )
            return question_record
        except Exception as e:
            raise RuntimeError(f"질문 처리 중 오류 발생: {e}")
        finally:
            # 4. 사용 완료된 임시 사진은 디스크에서 즉시 삭제
            if os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                except Exception:
                    pass

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
