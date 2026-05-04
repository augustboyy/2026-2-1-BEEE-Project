from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import CURRENT_SCHEMA_VERSION, Database
from app.repository import PlantRepository


def build_repository(tmp_path: Path) -> tuple[Database, PlantRepository]:
    database = Database(str(tmp_path / "plant.db"))
    database.init_schema()
    return database, PlantRepository(database)


def table_exists(database: Database, table_name: str) -> bool:
    row = database.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return row is not None


def index_exists(database: Database, index_name: str) -> bool:
    row = database.fetchone(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    )
    return row is not None


def test_empty_database_initializes_latest_schema(tmp_path: Path) -> None:
    database, _ = build_repository(tmp_path)
    try:
        version = database.fetchone("PRAGMA user_version")[0]
        assert version == CURRENT_SCHEMA_VERSION

        for table_name in {
            "plants",
            "analysis_results",
            "species_profiles",
            "camera_captures",
            "ai_alerts",
            "alert_actions",
            "care_guides",
            "user_questions",
            "watering_rules",
            "watering_events",
            "device_heartbeats",
        }:
            assert table_exists(database, table_name)

        for index_name in {
            "idx_sensor_logs_plant_received",
            "idx_analysis_results_plant_created",
            "idx_ai_alerts_plant_status_created",
            "idx_user_questions_plant_created",
            "idx_device_heartbeats_device_received",
        }:
            assert index_exists(database, index_name)
    finally:
        database.close()


def test_user_version_zero_database_upgrades_without_data_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE plants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            species TEXT,
            location TEXT,
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        """
        INSERT INTO plants (name, species, location, created_at, is_active)
        VALUES ('Legacy Basil', 'Basil', 'Shelf', '2026-01-01T00:00:00+00:00', 1)
        """
    )
    connection.commit()
    connection.close()

    database = Database(str(db_path))
    try:
        database.init_schema()

        assert database.fetchone("PRAGMA user_version")[0] == CURRENT_SCHEMA_VERSION
        assert table_exists(database, "watering_events")
        assert table_exists(database, "device_heartbeats")

        row = database.fetchone("SELECT name, species FROM plants WHERE name = ?", ("Legacy Basil",))
        assert row is not None
        assert row["species"] == "Basil"
    finally:
        database.close()


def test_analysis_creates_and_completes_open_alert(tmp_path: Path) -> None:
    database, repository = build_repository(tmp_path)
    try:
        plant = repository.create_plant("Alert Plant", "Basil", "Desk")
        analysis = repository.add_analysis_result(
            plant_id=plant["id"],
            job_id="analysis-alert-test",
            image_id=None,
            provider="mock",
            model_name="demo-photo-analyzer",
            request_note="dry leaves",
            prompt_text="Analyze the plant.",
            response_json={
                "health_status": "critical",
                "condition_summary": "Leaves look dry.",
                "advice": "Water soon.",
                "observed_issues": ["dry leaves"],
                "watering_need": "high",
                "confidence": 0.91,
            },
            raw_response_text="{}",
        )

        open_alerts = repository.get_open_alerts(plant["id"])
        assert len(open_alerts) == 1
        assert open_alerts[0]["analysis_id"] == analysis["id"]
        assert open_alerts[0]["metadata"]["watering_need"] == "high"

        completed = repository.complete_ai_alert(open_alerts[0]["id"], note="Watered.", actor="tester")
        assert completed is not None
        assert completed["status"] == "completed"
        assert repository.get_open_alerts(plant["id"]) == []
        assert repository.list_alert_actions(completed["id"])[0]["note"] == "Watered."
    finally:
        database.close()


def test_watering_rules_and_events_are_saved(tmp_path: Path) -> None:
    database, repository = build_repository(tmp_path)
    try:
        plant = repository.create_plant("Water Plant")
        rule = repository.save_watering_rule(
            plant_id=plant["id"],
            mode="automatic",
            is_enabled=True,
            threshold_moisture=32.0,
            target_moisture=55.0,
            cooldown_minutes=120,
            amount_ml=180.0,
            metadata={"source": "test"},
        )
        event = repository.create_watering_event(
            plant_id=plant["id"],
            watering_rule_id=rule["id"],
            event_type="simulation",
            status="completed",
            trigger_source="rule-engine",
            amount_ml=180.0,
            reason="below threshold",
            metadata={"moisture_value": 28.4},
        )

        assert rule["is_enabled"] == 1
        assert rule["metadata"]["source"] == "test"
        assert event["watering_rule_id"] == rule["id"]
        assert repository.get_latest_watering_event(plant["id"])["id"] == event["id"]
    finally:
        database.close()


def test_user_questions_care_guides_and_heartbeats_are_saved(tmp_path: Path) -> None:
    database, repository = build_repository(tmp_path)
    try:
        plant = repository.create_plant("Care Plant", "Basil", "Kitchen")
        profile = repository.create_or_update_species_profile(
            "Basil",
            recommended_moisture_min=35.0,
            recommended_moisture_max=65.0,
            care_notes={"watering": "Keep soil lightly moist."},
        )
        guide = repository.save_care_guide(
            plant_id=plant["id"],
            species_profile_id=profile["id"],
            provider="mock",
            model_name="guide-model",
            summary="Keep it bright and evenly moist.",
            content={"tips": ["Rotate weekly", "Avoid cold drafts"]},
        )
        question = repository.save_user_question(
            plant_id=plant["id"],
            question_text="Why are the leaves curling?",
            answer_text="Check watering consistency and light exposure.",
            provider="mock",
            model_name="qa-model",
            context={"latest_moisture": 29.0},
        )
        heartbeat = repository.record_device_heartbeat(
            device_type="camera",
            device_id="camera-1",
            status="online",
            plant_id=plant["id"],
            metadata={"fps": 15},
        )

        dashboard = repository.build_dashboard(plant["id"])
        assert guide["content"]["tips"][0] == "Rotate weekly"
        assert question["context"]["latest_moisture"] == 29.0
        assert heartbeat["metadata"]["fps"] == 15
        assert dashboard["latest_care_guide"]["id"] == guide["id"]
        assert dashboard["recent_user_questions"][0]["id"] == question["id"]
        assert dashboard["recent_device_heartbeats"][0]["id"] == heartbeat["id"]
    finally:
        database.close()
