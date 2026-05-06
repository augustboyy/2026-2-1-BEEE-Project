"""
이 파일은 데이터 저장소(Repository) 패턴을 구현합니다.
데이터베이스와의 직접적인 상호작용을 담당하며, 데이터를 조회, 저장, 수정하는 비즈니스 로직을 제공합니다.
또한, DB에서 읽어온 원본 데이터를 애플리케이션에서 사용하기 좋은 딕셔너리 형태로 가공합니다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import Database


# JSON 문자열로 저장된 필드 중 리스트 형태인 것들을 정의합니다.
JSON_LIST_KEYS = {"observed_issues_json"}


def utc_now_iso() -> str:
    """현재 시간을 UTC 기준 ISO 포맷 문자열로 반환합니다."""
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any, default: Any) -> str:
    """데이터를 JSON 문자열로 변환합니다. 값이 없으면 기본값을 사용합니다."""
    return json.dumps(default if value is None else value, ensure_ascii=False)


def _to_dict(row) -> dict[str, Any] | None:
    """
    SQLite의 Row 객체를 파이썬 딕셔너리로 변환하고,
    _json으로 끝나는 필드들을 파싱하여 실제 객체로 복원합니다.
    """
    if row is None:
        return None

    data = dict(row)
    for key in list(data.keys()):
        if key.endswith("_json") and data.get(key):
            new_key = key.replace("_json", "")
            try:
                data[new_key] = json.loads(data.pop(key))
            except json.JSONDecodeError:
                data[new_key] = data.pop(key)
        elif key.endswith("_json"):
            default_value = [] if key in JSON_LIST_KEYS else {}
            data[key.replace("_json", "")] = default_value
            data.pop(key, None)
    return data


class PlantRepository:
    """
    식물 관련 데이터 처리를 전담하는 저장소 클래스입니다.
    """
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_plant(self, name: str, species: str | None = None, location: str | None = None) -> dict[str, Any]:
        """새로운 식물을 데이터베이스에 등록합니다."""
        created_at = utc_now_iso()
        # 새 식물을 등록할 때 기존 활성 식물들을 비활성화합니다.
        self.database.execute("UPDATE plants SET is_active = 0 WHERE is_active = 1")
        cursor = self.database.execute(
            """
            INSERT INTO plants (name, species, location, created_at, is_active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (name.strip(), (species or "").strip() or None, (location or "").strip() or None, created_at),
        )
        plant_id = cursor.lastrowid
        self.ensure_latest_state(plant_id)
        self.add_activity(
            plant_id,
            "plant_registered",
            f"{name.strip()} 식물을 등록하고 활성 세션으로 설정했습니다.",
            {"species": species, "location": location},
        )
        return self.get_plant(plant_id)

    def ensure_latest_state(self, plant_id: int) -> None:
        """식물의 최신 상태를 담을 레코드가 존재하는지 확인하고 없으면 생성합니다."""
        self.database.execute(
            """
            INSERT INTO latest_state (plant_id, updated_at)
            VALUES (?, ?)
            ON CONFLICT(plant_id) DO NOTHING
            """,
            (plant_id, utc_now_iso()),
        )

    def update_latest_state(self, plant_id: int, **fields: Any) -> None:
        """식물의 최신 요약 상태를 업데이트합니다."""
        self.ensure_latest_state(plant_id)
        fields = {key: value for key, value in fields.items()}
        fields["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = tuple(fields.values()) + (plant_id,)
        self.database.execute(
            f"UPDATE latest_state SET {assignments} WHERE plant_id = ?",
            params,
        )

    def list_plants(self) -> list[dict[str, Any]]:
        """모든 식물 목록을 최신 상태와 함께 가져옵니다."""
        rows = self.database.fetchall(
            """
            SELECT p.*, ls.latest_health_status, ls.ai_updated_at
            FROM plants p
            LEFT JOIN latest_state ls ON ls.plant_id = p.id
            ORDER BY p.is_active DESC, p.created_at DESC
            """
        )
        return [_to_dict(row) for row in rows]

    def get_plant(self, plant_id: int) -> dict[str, Any] | None:
        """식물 ID로 상세 정보를 조회합니다."""
        row = self.database.fetchone("SELECT * FROM plants WHERE id = ?", (plant_id,))
        return _to_dict(row)

    def get_current_plant(self) -> dict[str, Any] | None:
        """현재 활성화되어 모니터링 중인 식물을 가져옵니다."""
        row = self.database.fetchone(
            "SELECT * FROM plants WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        )
        return _to_dict(row)

    def activate_plant(self, plant_id: int) -> dict[str, Any] | None:
        """특정 식물을 현재 활성 상태로 전환합니다."""
        plant = self.get_plant(plant_id)
        if plant is None:
            return None
        self.database.execute("UPDATE plants SET is_active = 0 WHERE is_active = 1")
        self.database.execute("UPDATE plants SET is_active = 1 WHERE id = ?", (plant_id,))
        self.add_activity(plant_id, "plant_activated", f"{plant['name']} 식물을 현재 작업 대상으로 전환했습니다.")
        return self.get_plant(plant_id)

    # --- 종(Species) 프로필 관리 ---
    def create_or_update_species_profile(
        self,
        species_name: str,
        common_name: str | None = None,
        description: str | None = None,
        recommended_moisture_min: float | None = None,
        recommended_moisture_max: float | None = None,
        recommended_temperature_min: float | None = None,
        recommended_temperature_max: float | None = None,
        recommended_humidity_min: float | None = None,
        recommended_humidity_max: float | None = None,
        recommended_light_min: float | None = None,
        recommended_light_max: float | None = None,
        watering_interval_days: int | None = None,
        care_notes: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        """식물 종에 대한 권장 환경 정보(가이드라인)를 저장하거나 수정합니다."""
        clean_species_name = species_name.strip()
        if not clean_species_name:
            raise ValueError("species_name is required.")

        now = utc_now_iso()
        self.database.execute(
            """
            INSERT INTO species_profiles (
                species_name, common_name, description,
                recommended_moisture_min, recommended_moisture_max,
                recommended_temperature_min, recommended_temperature_max,
                recommended_humidity_min, recommended_humidity_max,
                recommended_light_min, recommended_light_max,
                watering_interval_days, care_notes_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(species_name) DO UPDATE SET
                common_name = COALESCE(excluded.common_name, species_profiles.common_name),
                description = COALESCE(excluded.description, species_profiles.description),
                recommended_moisture_min = COALESCE(excluded.recommended_moisture_min, species_profiles.recommended_moisture_min),
                recommended_moisture_max = COALESCE(excluded.recommended_moisture_max, species_profiles.recommended_moisture_max),
                recommended_temperature_min = COALESCE(excluded.recommended_temperature_min, species_profiles.recommended_temperature_min),
                recommended_temperature_max = COALESCE(excluded.recommended_temperature_max, species_profiles.recommended_temperature_max),
                recommended_humidity_min = COALESCE(excluded.recommended_humidity_min, species_profiles.recommended_humidity_min),
                recommended_humidity_max = COALESCE(excluded.recommended_humidity_max, species_profiles.recommended_humidity_max),
                recommended_light_min = COALESCE(excluded.recommended_light_min, species_profiles.recommended_light_min),
                recommended_light_max = COALESCE(excluded.recommended_light_max, species_profiles.recommended_light_max),
                watering_interval_days = COALESCE(excluded.watering_interval_days, species_profiles.watering_interval_days),
                care_notes_json = CASE
                    WHEN excluded.care_notes_json = '{}' THEN species_profiles.care_notes_json
                    ELSE excluded.care_notes_json
                END,
                updated_at = excluded.updated_at
            """,
            (
                clean_species_name,
                (common_name or "").strip() or None,
                (description or "").strip() or None,
                recommended_moisture_min,
                recommended_moisture_max,
                recommended_temperature_min,
                recommended_temperature_max,
                recommended_humidity_min,
                recommended_humidity_max,
                recommended_light_min,
                recommended_light_max,
                watering_interval_days,
                _json_dumps(care_notes, {}),
                now,
                now,
            ),
        )
        return self.get_species_profile_by_name(clean_species_name)

    def get_species_profile(self, species_profile_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM species_profiles WHERE id = ?", (species_profile_id,))
        return _to_dict(row)

    def get_species_profile_by_name(self, species_name: str) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM species_profiles WHERE species_name = ?",
            (species_name.strip(),),
        )
        return _to_dict(row)

    # --- 사진 업로드 관리 ---
    def save_uploaded_image(
        self,
        plant_id: int,
        file_path: str,
        original_name: str,
        mime_type: str,
    ) -> dict[str, Any]:
        """업로드된 식물 사진 메타데이터를 DB에 저장합니다."""
        created_at = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO uploaded_images (plant_id, file_path, original_name, mime_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plant_id, file_path, original_name, mime_type, created_at),
        )
        image_id = cursor.lastrowid
        self.update_latest_state(plant_id, latest_image_id=image_id)
        self.add_activity(
            plant_id,
            "image_uploaded",
            "식물 사진이 업로드되었습니다.",
            {"image_id": image_id, "original_name": original_name},
        )
        return self.get_uploaded_image(image_id)

    def get_uploaded_image(self, image_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM uploaded_images WHERE id = ?", (image_id,))
        return _to_dict(row)

    def get_latest_uploaded_image(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM uploaded_images WHERE plant_id = ? ORDER BY created_at DESC LIMIT 1",
            (plant_id,),
        )
        return _to_dict(row)

    # --- 카메라 캡처 관리 ---
    def save_camera_capture(
        self,
        plant_id: int,
        purpose: str,
        image_path: str,
        image_id: int | None = None,
        original_name: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        """카메라 모듈 등을 통해 캡처된 이미지 정보를 저장합니다."""
        now = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO camera_captures (
                plant_id, image_id, purpose, image_path, original_name, mime_type,
                metadata_json, captured_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                image_id,
                purpose,
                image_path,
                original_name,
                mime_type,
                _json_dumps(metadata, {}),
                captured_at or now,
                now,
            ),
        )
        capture_id = cursor.lastrowid
        if image_id is not None:
            self.update_latest_state(plant_id, latest_image_id=image_id)
        self.add_activity(
            plant_id,
            "camera_capture_saved",
            "카메라 캡처 사진이 저장되었습니다.",
            {"camera_capture_id": capture_id, "purpose": purpose, "image_id": image_id},
        )
        return self.get_camera_capture(capture_id)

    def get_camera_capture(self, capture_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM camera_captures WHERE id = ?", (capture_id,))
        return _to_dict(row)

    def get_latest_camera_capture(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM camera_captures WHERE plant_id = ? ORDER BY captured_at DESC LIMIT 1",
            (plant_id,),
        )
        return _to_dict(row)

    def list_recent_camera_captures(self, plant_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM camera_captures
            WHERE plant_id = ?
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    # --- 센서 로그 관리 ---
    def add_sensor_log(
        self,
        plant_id: int,
        moisture_value: float,
        humidity: float | None,
        temperature: float | None,
        light_level: float | None,
        source: str,
    ) -> dict[str, Any]:
        """센서로부터 수신한 데이터를 로그로 저장하고 최신 상태를 갱신합니다."""
        received_at = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO sensor_logs
            (plant_id, moisture_value, humidity, temperature, light_level, source, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (plant_id, moisture_value, humidity, temperature, light_level, source, received_at),
        )
        log_id = cursor.lastrowid
        # 최신 센서 상태 테이블 업데이트
        self.database.execute(
            """
            INSERT INTO latest_sensor_state
            (plant_id, latest_sensor_log_id, moisture_value, humidity, temperature, light_level, source, received_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plant_id) DO UPDATE SET
                latest_sensor_log_id = excluded.latest_sensor_log_id,
                moisture_value = excluded.moisture_value,
                humidity = excluded.humidity,
                temperature = excluded.temperature,
                light_level = excluded.light_level,
                source = excluded.source,
                received_at = excluded.received_at,
                updated_at = excluded.updated_at
            """,
            (
                plant_id,
                log_id,
                moisture_value,
                humidity,
                temperature,
                light_level,
                source,
                received_at,
                received_at,
            ),
        )
        self.update_latest_state(plant_id, latest_sensor_log_id=log_id)
        self.add_activity(
            plant_id,
            "sensor_received",
            "센서 데이터가 저장되었습니다.",
            {"sensor_log_id": log_id, "source": source, "moisture_value": moisture_value},
        )
        return self.get_sensor_log(log_id)

    def get_sensor_log(self, log_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM sensor_logs WHERE id = ?", (log_id,))
        return _to_dict(row)

    def get_latest_sensor_state(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM latest_sensor_state WHERE plant_id = ?", (plant_id,))
        return _to_dict(row)

    def list_recent_sensor_logs(self, plant_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM sensor_logs
            WHERE plant_id = ?
            ORDER BY received_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    # --- 급수 로그 관리 ---
    def add_watering_log(
        self,
        plant_id: int,
        mode: str,
        amount_ml: float | None = None,
        duration_seconds: int | None = None,
        note: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> dict[str, Any]:
        """급수 실행 기록을 저장합니다."""
        now = datetime.now(timezone.utc)
        started = started_at or now.isoformat()
        if ended_at:
            ended = ended_at
        elif duration_seconds is not None:
            ended = (now + timedelta(seconds=duration_seconds)).isoformat()
        else:
            ended = None

        cursor = self.database.execute(
            """
            INSERT INTO watering_logs
            (plant_id, started_at, ended_at, duration_seconds, mode, amount_ml, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                started,
                ended,
                duration_seconds,
                mode,
                amount_ml,
                note,
                utc_now_iso(),
            ),
        )
        log_id = cursor.lastrowid
        self.update_latest_state(plant_id, latest_watering_log_id=log_id)
        self.add_activity(
            plant_id,
            "watering_logged",
            "급수 기록이 저장되었습니다.",
            {"watering_log_id": log_id, "mode": mode, "amount_ml": amount_ml},
        )
        return self.get_watering_log(log_id)

    def get_watering_log(self, log_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM watering_logs WHERE id = ?", (log_id,))
        return _to_dict(row)

    def get_latest_watering_log(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM watering_logs WHERE plant_id = ? ORDER BY created_at DESC LIMIT 1",
            (plant_id,),
        )
        return _to_dict(row)

    def list_recent_watering_logs(self, plant_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM watering_logs
            WHERE plant_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    # --- AI 분석 결과 관리 ---
    def add_analysis_result(
        self,
        plant_id: int,
        job_id: str,
        image_id: int | None,
        provider: str,
        model_name: str,
        request_note: str | None,
        prompt_text: str,
        response_json: dict[str, Any],
        raw_response_text: str,
        camera_capture_id: int | None = None,
    ) -> dict[str, Any]:
        """AI의 사진 분석 결과를 저장하고 필요 시 알림(Alert)을 생성합니다."""
        created_at = utc_now_iso()
        with self.database.transaction():
            cursor = self.database.execute(
                """
                INSERT INTO analysis_results
                (
                    plant_id, job_id, image_id, provider, model_name, request_note, prompt_text,
                    response_json, raw_response_text, health_status, condition_summary, advice,
                    observed_issues_json, watering_need, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plant_id,
                    job_id,
                    image_id,
                    provider,
                    model_name,
                    request_note,
                    prompt_text,
                    _json_dumps(response_json, {}),
                    raw_response_text,
                    response_json["health_status"],
                    response_json["condition_summary"],
                    response_json["advice"],
                    _json_dumps(response_json.get("observed_issues"), []),
                    response_json["watering_need"],
                    response_json["confidence"],
                    created_at,
                ),
            )
            analysis_id = cursor.lastrowid
            # 최신 상태 업데이트
            self.update_latest_state(
                plant_id,
                latest_analysis_id=analysis_id,
                latest_image_id=image_id,
                latest_health_status=response_json["health_status"],
                latest_condition_summary=response_json["condition_summary"],
                latest_advice=response_json["advice"],
                latest_watering_need=response_json["watering_need"],
                latest_confidence=response_json["confidence"],
                ai_updated_at=created_at,
                ai_confirmed_at=None,
            )
            # 건강 상태가 주의나 위험이면 알림 생성
            if response_json["health_status"] in {"warning", "critical"}:
                self.create_ai_alert(
                    plant_id=plant_id,
                    analysis_id=analysis_id,
                    camera_capture_id=camera_capture_id,
                    severity=response_json["health_status"],
                    title="AI 진단 결과 주의가 필요합니다.",
                    message=response_json["condition_summary"],
                    alert_type="diagnosis",
                    metadata={
                        "watering_need": response_json["watering_need"],
                        "observed_issues": response_json.get("observed_issues", []),
                        "confidence": response_json["confidence"],
                    },
                )
            self.add_activity(
                plant_id,
                "analysis_saved",
                "AI 사진 분석 결과가 저장되었습니다.",
                {"analysis_id": analysis_id, "provider": provider, "health_status": response_json["health_status"]},
            )
        return self.get_analysis_result(analysis_id)

    def get_analysis_result(self, analysis_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM analysis_results WHERE id = ?", (analysis_id,))
        return _to_dict(row)

    def get_latest_analysis(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM analysis_results WHERE plant_id = ? ORDER BY created_at DESC LIMIT 1",
            (plant_id,),
        )
        return _to_dict(row)

    def confirm_analysis(self, analysis_id: int) -> dict[str, Any] | None:
        """사용자가 AI 분석 결과를 확인했음을 기록하고 관련 알림을 종료합니다."""
        analysis = self.get_analysis_result(analysis_id)
        if analysis is None:
            return None

        confirmed_at = utc_now_iso()
        with self.database.transaction():
            self.database.execute(
                "UPDATE analysis_results SET confirmed_at = ? WHERE id = ?",
                (confirmed_at, analysis_id),
            )
            self.update_latest_state(analysis["plant_id"], ai_confirmed_at=confirmed_at)
            # 관련 오픈된 알림들을 모두 완료 상태로 변경
            open_alerts = self.database.fetchall(
                """
                SELECT * FROM ai_alerts
                WHERE analysis_id = ? AND status = 'open'
                ORDER BY created_at DESC
                """,
                (analysis_id,),
            )
            for alert_row in open_alerts:
                self.complete_ai_alert(
                    int(alert_row["id"]),
                    note="분석 결과 확인됨.",
                    actor="user",
                    action_type="analysis_confirmed",
                    metadata={"analysis_id": analysis_id},
                )
            self.add_activity(
                analysis["plant_id"],
                "analysis_confirmed",
                "사용자가 AI 분석 결과를 확인했습니다.",
                {"analysis_id": analysis_id},
            )
        return self.get_analysis_result(analysis_id)

    def list_recent_analyses(self, plant_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM analysis_results
            WHERE plant_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    # --- AI 알림(Alert) 관리 ---
    def create_ai_alert(
        self,
        plant_id: int,
        severity: str,
        title: str,
        message: str,
        analysis_id: int | None = None,
        camera_capture_id: int | None = None,
        alert_type: str = "diagnosis",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """시스템에 중요한 알림을 생성합니다."""
        now = utc_now_iso()
        with self.database.transaction():
            cursor = self.database.execute(
                """
                INSERT INTO ai_alerts (
                    plant_id, analysis_id, camera_capture_id, alert_type, severity,
                    title, message, status, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    plant_id,
                    analysis_id,
                    camera_capture_id,
                    alert_type,
                    severity,
                    title,
                    message,
                    _json_dumps(metadata, {}),
                    now,
                    now,
                ),
            )
            alert_id = cursor.lastrowid
            self.add_activity(
                plant_id,
                "ai_alert_opened",
                "AI 알림이 발생했습니다.",
                {"alert_id": alert_id, "analysis_id": analysis_id, "severity": severity},
            )
        return self.get_ai_alert(alert_id)

    def get_ai_alert(self, alert_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM ai_alerts WHERE id = ?", (alert_id,))
        return _to_dict(row)

    def get_open_alerts(self, plant_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """해결되지 않은(Open) 알림 목록을 가져옵니다."""
        if plant_id is None:
            rows = self.database.fetchall(
                """
                SELECT * FROM ai_alerts
                WHERE status = 'open'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = self.database.fetchall(
                """
                SELECT * FROM ai_alerts
                WHERE plant_id = ? AND status = 'open'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (plant_id, limit),
            )
        return [_to_dict(row) for row in rows]

    def list_recent_ai_alerts(self, plant_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM ai_alerts
            WHERE plant_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    def complete_ai_alert(
        self,
        alert_id: int,
        note: str | None = None,
        actor: str | None = None,
        action_type: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """알림을 완료/해결 상태로 변경합니다."""
        alert = self.get_ai_alert(alert_id)
        if alert is None:
            return None
        if alert["status"] == "completed":
            return alert

        now = utc_now_iso()
        with self.database.transaction():
            self.database.execute(
                """
                UPDATE ai_alerts
                SET status = 'completed', completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, alert_id),
            )
            self.database.execute(
                """
                INSERT INTO alert_actions (
                    alert_id, plant_id, action_type, note, actor, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    alert["plant_id"],
                    action_type,
                    note,
                    actor,
                    _json_dumps(metadata, {}),
                    now,
                ),
            )
            self.add_activity(
                alert["plant_id"],
                "ai_alert_completed",
                "AI 알림이 해결되었습니다.",
                {"alert_id": alert_id, "action_type": action_type, "actor": actor},
            )
        return self.get_ai_alert(alert_id)

    # --- 공통 로그(Activity, Error) 관리 ---
    def get_latest_state(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM latest_state WHERE plant_id = ?", (plant_id,))
        return _to_dict(row)

    def add_activity(
        self,
        plant_id: int | None,
        category: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """일반 활동 로그를 기록합니다."""
        self.database.execute(
            """
            INSERT INTO activity_logs (plant_id, category, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                category,
                message,
                json.dumps(metadata or {}, ensure_ascii=False),
                utc_now_iso(),
            ),
        )

    def list_recent_activity(self, plant_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if plant_id is None:
            rows = self.database.fetchall(
                "SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.database.fetchall(
                """
                SELECT * FROM activity_logs
                WHERE plant_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (plant_id, limit),
            )
        return [_to_dict(row) for row in rows]

    def add_error(
        self,
        source: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        plant_id: int | None = None,
    ) -> None:
        """에러 로그를 기록합니다."""
        self.database.execute(
            """
            INSERT INTO error_logs (plant_id, source, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                source,
                message,
                json.dumps(metadata or {}, ensure_ascii=False),
                utc_now_iso(),
            ),
        )

    def list_recent_errors(self, plant_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if plant_id is None:
            rows = self.database.fetchall(
                "SELECT * FROM error_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.database.fetchall(
                """
                SELECT * FROM error_logs
                WHERE plant_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (plant_id, limit),
            )
        return [_to_dict(row) for row in rows]

    # --- 기타 확장 기능 (관리 가이드, 질문 답변, 급수 규칙 등) ---
    def save_care_guide(
        self,
        plant_id: int,
        summary: str,
        content: dict[str, Any] | list[Any],
        provider: str | None = None,
        model_name: str | None = None,
        guide_type: str = "general",
        species_profile_id: int | None = None,
    ) -> dict[str, Any]:
        """AI가 생성한 식물 관리 가이드를 저장합니다."""
        now = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO care_guides (
                plant_id, species_profile_id, provider, model_name, guide_type,
                summary, content_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                species_profile_id,
                provider,
                model_name,
                guide_type,
                summary,
                _json_dumps(content, {}),
                now,
                now,
            ),
        )
        guide_id = cursor.lastrowid
        self.add_activity(
            plant_id,
            "care_guide_saved",
            "관리 가이드가 저장되었습니다.",
            {"care_guide_id": guide_id, "guide_type": guide_type},
        )
        return self.get_care_guide(guide_id)

    def get_care_guide(self, care_guide_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM care_guides WHERE id = ?", (care_guide_id,))
        return _to_dict(row)

    def get_latest_care_guide(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM care_guides WHERE plant_id = ? ORDER BY updated_at DESC LIMIT 1",
            (plant_id,),
        )
        return _to_dict(row)

    def save_user_question(
        self,
        plant_id: int,
        question_text: str,
        answer_text: str,
        provider: str | None = None,
        model_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """사용자의 질문과 AI의 답변 쌍을 저장합니다."""
        created_at = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO user_questions (
                plant_id, question_text, answer_text, provider, model_name, context_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                question_text,
                answer_text,
                provider,
                model_name,
                _json_dumps(context, {}),
                created_at,
            ),
        )
        question_id = cursor.lastrowid
        self.add_activity(
            plant_id,
            "user_question_saved",
            "식물 관련 질문과 AI 답변이 저장되었습니다.",
            {"user_question_id": question_id, "provider": provider},
        )
        return self.get_user_question(question_id)

    def get_user_question(self, question_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM user_questions WHERE id = ?", (question_id,))
        return _to_dict(row)

    def list_recent_user_questions(self, plant_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM user_questions
            WHERE plant_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    def save_watering_rule(
        self,
        plant_id: int,
        mode: str = "manual",
        is_enabled: bool = False,
        threshold_moisture: float | None = None,
        target_moisture: float | None = None,
        cooldown_minutes: int = 60,
        max_duration_seconds: int | None = None,
        amount_ml: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """자동 급수 등을 위한 규칙을 설정합니다."""
        now = utc_now_iso()
        self.database.execute(
            """
            INSERT INTO watering_rules (
                plant_id, mode, is_enabled, threshold_moisture, target_moisture,
                cooldown_minutes, max_duration_seconds, amount_ml, metadata_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plant_id) DO UPDATE SET
                mode = excluded.mode,
                is_enabled = excluded.is_enabled,
                threshold_moisture = excluded.threshold_moisture,
                target_moisture = excluded.target_moisture,
                cooldown_minutes = excluded.cooldown_minutes,
                max_duration_seconds = excluded.max_duration_seconds,
                amount_ml = excluded.amount_ml,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                plant_id,
                mode,
                1 if is_enabled else 0,
                threshold_moisture,
                target_moisture,
                cooldown_minutes,
                max_duration_seconds,
                amount_ml,
                _json_dumps(metadata, {}),
                now,
                now,
            ),
        )
        self.add_activity(
            plant_id,
            "watering_rule_saved",
            "급수 규칙이 설정되었습니다.",
            {"mode": mode, "is_enabled": is_enabled},
        )
        return self.get_watering_rule(plant_id)

    def get_watering_rule(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM watering_rules WHERE plant_id = ?", (plant_id,))
        return _to_dict(row)

    def create_watering_event(
        self,
        plant_id: int,
        event_type: str = "simulation",
        status: str = "completed",
        watering_rule_id: int | None = None,
        watering_log_id: int | None = None,
        trigger_source: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_seconds: int | None = None,
        amount_ml: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """급수 시스템에서 발생한 구체적인 이벤트(트리거 등)를 기록합니다."""
        now = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO watering_events (
                plant_id, watering_rule_id, watering_log_id, event_type, status,
                trigger_source, started_at, ended_at, duration_seconds, amount_ml,
                reason, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                watering_rule_id,
                watering_log_id,
                event_type,
                status,
                trigger_source,
                started_at or now,
                ended_at,
                duration_seconds,
                amount_ml,
                reason,
                _json_dumps(metadata, {}),
                now,
            ),
        )
        event_id = cursor.lastrowid
        self.add_activity(
            plant_id,
            "watering_event_created",
            "급수 이벤트가 생성되었습니다.",
            {"watering_event_id": event_id, "event_type": event_type, "status": status},
        )
        return self.get_watering_event(event_id)

    def get_watering_event(self, event_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM watering_events WHERE id = ?", (event_id,))
        return _to_dict(row)

    def get_latest_watering_event(self, plant_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone(
            "SELECT * FROM watering_events WHERE plant_id = ? ORDER BY created_at DESC LIMIT 1",
            (plant_id,),
        )
        return _to_dict(row)

    def list_recent_watering_events(self, plant_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT * FROM watering_events
            WHERE plant_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (plant_id, limit),
        )
        return [_to_dict(row) for row in rows]

    def record_device_heartbeat(
        self,
        device_type: str,
        status: str,
        device_id: str = "default",
        plant_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        """장치의 상태(온라인/오프라인 등)를 기록하는 하트비트 기능입니다."""
        now = utc_now_iso()
        cursor = self.database.execute(
            """
            INSERT INTO device_heartbeats (
                plant_id, device_type, device_id, status, metadata_json, received_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plant_id,
                device_type,
                device_id,
                status,
                _json_dumps(metadata, {}),
                received_at or now,
                now,
            ),
        )
        heartbeat_id = cursor.lastrowid
        return self.get_device_heartbeat(heartbeat_id)

    def get_device_heartbeat(self, heartbeat_id: int) -> dict[str, Any] | None:
        row = self.database.fetchone("SELECT * FROM device_heartbeats WHERE id = ?", (heartbeat_id,))
        return _to_dict(row)

    def list_recent_device_heartbeats(
        self,
        plant_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if plant_id is None:
            rows = self.database.fetchall(
                "SELECT * FROM device_heartbeats ORDER BY received_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.database.fetchall(
                """
                SELECT * FROM device_heartbeats
                WHERE plant_id = ? OR plant_id IS NULL
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (plant_id, limit),
            )
        return [_to_dict(row) for row in rows]

    # --- 대시보드 데이터 빌더 ---
    def get_counts(self, plant_id: int) -> dict[str, int]:
        """분석, 센서, 급수 로그의 총 개수를 가져옵니다."""
        analysis_count = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM analysis_results WHERE plant_id = ?",
            (plant_id,),
        )
        sensor_count = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM sensor_logs WHERE plant_id = ?",
            (plant_id,),
        )
        watering_count = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM watering_logs WHERE plant_id = ?",
            (plant_id,),
        )
        return {
            "analysis_count": int(analysis_count["count"]),
            "sensor_count": int(sensor_count["count"]),
            "watering_count": int(watering_count["count"]),
        }

    def build_dashboard(self, plant_id: int) -> dict[str, Any] | None:
        """
        특정 식물에 대한 모든 최신 데이터와 이력을 모아 대시보드용 큰 딕셔너리를 구성합니다.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            return None

        return {
            "plant": plant,
            "latest_state": self.get_latest_state(plant_id),
            "latest_sensor_state": self.get_latest_sensor_state(plant_id),
            "latest_analysis": self.get_latest_analysis(plant_id),
            "latest_watering_log": self.get_latest_watering_log(plant_id),
            "latest_uploaded_image": self.get_latest_uploaded_image(plant_id),
            "latest_camera_capture": self.get_latest_camera_capture(plant_id),
            "open_alerts": self.get_open_alerts(plant_id),
            "recent_ai_alerts": self.list_recent_ai_alerts(plant_id),
            "latest_care_guide": self.get_latest_care_guide(plant_id),
            "recent_user_questions": self.list_recent_user_questions(plant_id),
            "watering_rule": self.get_watering_rule(plant_id),
            "latest_watering_event": self.get_latest_watering_event(plant_id),
            "recent_watering_events": self.list_recent_watering_events(plant_id),
            "recent_device_heartbeats": self.list_recent_device_heartbeats(plant_id),
            "recent_camera_captures": self.list_recent_camera_captures(plant_id),
            "recent_analyses": self.list_recent_analyses(plant_id),
            "recent_sensor_logs": self.list_recent_sensor_logs(plant_id),
            "recent_watering_logs": self.list_recent_watering_logs(plant_id),
            "recent_activity": self.list_recent_activity(plant_id),
            "recent_errors": self.list_recent_errors(plant_id),
            "counts": self.get_counts(plant_id),
            "plant_overview": self.list_plants(),
        }
