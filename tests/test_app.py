from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


def build_test_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="Plant Pulse Test",
        app_host="127.0.0.1",
        app_port=8010,
        api_base_url="http://127.0.0.1:8010",
        dashboard_host="127.0.0.1",
        dashboard_port=8510,
        database_path=str(tmp_path / "test.db"),
        uploads_dir=str(tmp_path / "uploads"),
        sensor_interval_seconds=999,
        enable_sensor_loop=False,
        ai_provider="mock",
        ai_timeout_seconds=5.0,
        max_upload_mb=5,
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        gemini_api_key=None,
        gemini_model="gemini-2.0-flash",
    )


def make_test_image_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), color=(120, 180, 120))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_full_photo_analysis_flow(tmp_path: Path) -> None:
    app = create_app(build_test_settings(tmp_path))

    with TestClient(app) as client:
        create_response = client.post(
            "/api/plants",
            json={"name": "몬스테라", "species": "관엽식물", "location": "실험실"},
        )
        assert create_response.status_code == 200
        dashboard = create_response.json()["dashboard"]
        plant_id = dashboard["plant"]["id"]
        assert dashboard["latest_sensor_state"] is not None

        sensor_response = client.post(
            f"/api/plants/{plant_id}/sensor-logs",
            json={
                "moisture_value": 31.5,
                "humidity": 42.0,
                "temperature": 25.0,
                "light_level": 5300.0,
                "source": "integration-test",
            },
        )
        assert sensor_response.status_code == 200
        assert sensor_response.json()["sensor_log"]["source"] == "integration-test"

        watering_response = client.post(
            f"/api/plants/{plant_id}/watering-logs",
            json={
                "mode": "manual",
                "amount_ml": 180,
                "duration_seconds": 20,
                "note": "오전 급수",
            },
        )
        assert watering_response.status_code == 200
        assert watering_response.json()["watering_log"]["mode"] == "manual"

        photo_response = client.post(
            f"/api/plants/{plant_id}/analyze-photo",
            files={"image": ("plant.png", make_test_image_bytes(), "image/png")},
            data={"note": "잎 끝이 조금 노랗습니다."},
        )
        assert photo_response.status_code == 200
        payload = photo_response.json()

        assert payload["analysis"]["provider"] == "mock"
        assert payload["analysis"]["health_status"] in {"healthy", "warning", "critical"}
        assert payload["dashboard"]["latest_uploaded_image"] is not None
        analysis_id = payload["analysis"]["id"]

        confirm_response = client.post(f"/api/analyses/{analysis_id}/confirm")
        assert confirm_response.status_code == 200
        assert confirm_response.json()["dashboard"]["latest_analysis"]["confirmed_at"] is not None


def test_external_sensor_and_activation_endpoints(tmp_path: Path) -> None:
    app = create_app(build_test_settings(tmp_path))

    with TestClient(app) as client:
        first = client.post("/api/plants", json={"name": "스투키"}).json()["dashboard"]["plant"]
        second = client.post("/api/plants", json={"name": "로즈마리"}).json()["dashboard"]["plant"]

        activate_response = client.post("/api/plants/activate", json={"plant_id": first["id"]})
        assert activate_response.status_code == 200
        assert activate_response.json()["dashboard"]["plant"]["id"] == first["id"]

        sensor_response = client.post(
            "/api/external/sensor-data",
            json={
                "plant_id": first["id"],
                "moisture_value": 44.0,
                "humidity": 48.0,
                "temperature": 22.2,
                "light_level": 6100.0,
                "source": "raspberry-pi",
            },
        )
        assert sensor_response.status_code == 200
        assert sensor_response.json()["sensor_log"]["source"] == "raspberry-pi"

        dashboard_response = client.get(f"/api/plants/{second['id']}/dashboard")
        assert dashboard_response.status_code == 200
        assert dashboard_response.json()["dashboard"]["plant"]["name"] == "로즈마리"


def test_kiosk_ui_state_and_alert_confirmation(tmp_path: Path) -> None:
    app = create_app(build_test_settings(tmp_path))

    with TestClient(app) as client:
        kiosk_response = client.get("/kiosk")
        assert kiosk_response.status_code == 200
        assert "시작하기" in kiosk_response.text

        static_response = client.get("/static/kiosk.js")
        assert static_response.status_code == 200
        assert "/api/kiosk/state" in static_response.text

        empty_state = client.get("/api/kiosk/state")
        assert empty_state.status_code == 200
        assert empty_state.json()["dashboard"] is None
        assert empty_state.json()["kiosk"]["has_plant"] is False

        create_response = client.post("/api/plants", json={"name": "Kiosk Basil", "species": "Basil"})
        assert create_response.status_code == 200
        plant_id = create_response.json()["dashboard"]["plant"]["id"]

        sensor_response = client.post(
            f"/api/plants/{plant_id}/sensor-logs",
            json={
                "moisture_value": 20.0,
                "humidity": 38.0,
                "temperature": 27.0,
                "light_level": 4200.0,
                "source": "kiosk-test",
            },
        )
        assert sensor_response.status_code == 200

        photo_response = client.post(
            f"/api/plants/{plant_id}/analyze-photo",
            files={"image": ("plant.png", make_test_image_bytes(), "image/png")},
            data={"note": "dry leaves"},
        )
        assert photo_response.status_code == 200
        analysis_id = photo_response.json()["analysis"]["id"]

        state_response = client.get("/api/kiosk/state")
        assert state_response.status_code == 200
        payload = state_response.json()
        assert payload["dashboard"]["plant"]["id"] == plant_id
        assert payload["kiosk"]["sensor_synced"] is True
        assert payload["kiosk"]["alert_level"] == "critical"
        assert payload["kiosk"]["latest_analysis_id"] == analysis_id
        assert payload["kiosk"]["can_confirm_action"] is True
        assert isinstance(payload["kiosk"]["health_score"], int)

        confirm_response = client.post(f"/api/analyses/{analysis_id}/confirm")
        assert confirm_response.status_code == 200

        confirmed_state = client.get("/api/kiosk/state").json()
        assert confirmed_state["kiosk"]["alert_level"] == "critical"
        assert confirmed_state["kiosk"]["can_confirm_action"] is False
