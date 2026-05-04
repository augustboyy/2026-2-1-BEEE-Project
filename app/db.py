from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


CURRENT_SCHEMA_VERSION = 2


BASE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    species TEXT,
    location TEXT,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS uploaded_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS sensor_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    moisture_value REAL NOT NULL,
    humidity REAL,
    temperature REAL,
    light_level REAL,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS latest_sensor_state (
    plant_id INTEGER PRIMARY KEY,
    latest_sensor_log_id INTEGER,
    moisture_value REAL,
    humidity REAL,
    temperature REAL,
    light_level REAL,
    source TEXT,
    received_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (latest_sensor_log_id) REFERENCES sensor_logs (id)
);

CREATE TABLE IF NOT EXISTS watering_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    mode TEXT NOT NULL,
    amount_ml REAL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    job_id TEXT NOT NULL UNIQUE,
    image_id INTEGER,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    request_note TEXT,
    prompt_text TEXT,
    response_json TEXT NOT NULL,
    raw_response_text TEXT,
    health_status TEXT NOT NULL,
    condition_summary TEXT NOT NULL,
    advice TEXT NOT NULL,
    observed_issues_json TEXT NOT NULL,
    watering_need TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (image_id) REFERENCES uploaded_images (id)
);

CREATE TABLE IF NOT EXISTS latest_state (
    plant_id INTEGER PRIMARY KEY,
    latest_analysis_id INTEGER,
    latest_sensor_log_id INTEGER,
    latest_watering_log_id INTEGER,
    latest_image_id INTEGER,
    latest_health_status TEXT,
    latest_condition_summary TEXT,
    latest_advice TEXT,
    latest_watering_need TEXT,
    latest_confidence REAL,
    ai_updated_at TEXT,
    ai_confirmed_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (latest_analysis_id) REFERENCES analysis_results (id),
    FOREIGN KEY (latest_sensor_log_id) REFERENCES sensor_logs (id),
    FOREIGN KEY (latest_watering_log_id) REFERENCES watering_logs (id),
    FOREIGN KEY (latest_image_id) REFERENCES uploaded_images (id)
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);
"""


EXTENDED_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS species_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    species_name TEXT NOT NULL UNIQUE,
    common_name TEXT,
    description TEXT,
    recommended_moisture_min REAL,
    recommended_moisture_max REAL,
    recommended_temperature_min REAL,
    recommended_temperature_max REAL,
    recommended_humidity_min REAL,
    recommended_humidity_max REAL,
    recommended_light_min REAL,
    recommended_light_max REAL,
    watering_interval_days INTEGER,
    care_notes_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS camera_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    image_id INTEGER,
    purpose TEXT NOT NULL,
    image_path TEXT NOT NULL,
    original_name TEXT,
    mime_type TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (image_id) REFERENCES uploaded_images (id)
);

CREATE TABLE IF NOT EXISTS ai_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    analysis_id INTEGER,
    camera_capture_id INTEGER,
    alert_type TEXT NOT NULL DEFAULT 'diagnosis',
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (analysis_id) REFERENCES analysis_results (id),
    FOREIGN KEY (camera_capture_id) REFERENCES camera_captures (id)
);

CREATE TABLE IF NOT EXISTS alert_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    plant_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    note TEXT,
    actor TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (alert_id) REFERENCES ai_alerts (id),
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS care_guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    species_profile_id INTEGER,
    provider TEXT,
    model_name TEXT,
    guide_type TEXT NOT NULL DEFAULT 'general',
    summary TEXT NOT NULL,
    content_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (species_profile_id) REFERENCES species_profiles (id)
);

CREATE TABLE IF NOT EXISTS user_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    question_text TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    provider TEXT,
    model_name TEXT,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS watering_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL UNIQUE,
    mode TEXT NOT NULL DEFAULT 'manual',
    is_enabled INTEGER NOT NULL DEFAULT 0,
    threshold_moisture REAL,
    target_moisture REAL,
    cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    max_duration_seconds INTEGER,
    amount_ml REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);

CREATE TABLE IF NOT EXISTS watering_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL,
    watering_rule_id INTEGER,
    watering_log_id INTEGER,
    event_type TEXT NOT NULL DEFAULT 'simulation',
    status TEXT NOT NULL DEFAULT 'completed',
    trigger_source TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    amount_ml REAL,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id),
    FOREIGN KEY (watering_rule_id) REFERENCES watering_rules (id),
    FOREIGN KEY (watering_log_id) REFERENCES watering_logs (id)
);

CREATE TABLE IF NOT EXISTS device_heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER,
    device_type TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    received_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants (id)
);
"""


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_plants_active_created
    ON plants (is_active, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_uploaded_images_plant_created
    ON uploaded_images (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_logs_plant_received
    ON sensor_logs (plant_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_watering_logs_plant_created
    ON watering_logs (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_results_plant_created
    ON analysis_results (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_logs_plant_created
    ON activity_logs (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_logs_plant_created
    ON error_logs (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_camera_captures_plant_captured
    ON camera_captures (plant_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_camera_captures_plant_purpose_captured
    ON camera_captures (plant_id, purpose, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_alerts_plant_status_created
    ON ai_alerts (plant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_alerts_status_created
    ON ai_alerts (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_alerts_analysis
    ON ai_alerts (analysis_id);
CREATE INDEX IF NOT EXISTS idx_alert_actions_alert_created
    ON alert_actions (alert_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_care_guides_plant_updated
    ON care_guides (plant_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_questions_plant_created
    ON user_questions (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_watering_rules_plant_enabled
    ON watering_rules (plant_id, is_enabled);
CREATE INDEX IF NOT EXISTS idx_watering_events_plant_created
    ON watering_events (plant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_watering_events_rule_created
    ON watering_events (watering_rule_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_device_heartbeats_device_received
    ON device_heartbeats (device_type, device_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_device_heartbeats_plant_received
    ON device_heartbeats (plant_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_device_heartbeats_status_received
    ON device_heartbeats (status, received_at DESC);
"""


SCHEMA_SQL = BASE_SCHEMA_SQL + EXTENDED_SCHEMA_SQL + INDEX_SQL


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON;")
        self._connection.execute("PRAGMA journal_mode = WAL;")
        self._connection.execute("PRAGMA busy_timeout = 5000;")

    def init_schema(self) -> None:
        with self._lock:
            version = self._get_user_version()
            migrations = (
                (1, BASE_SCHEMA_SQL),
                (2, EXTENDED_SCHEMA_SQL + INDEX_SQL),
            )
            for target_version, migration_sql in migrations:
                if version < target_version:
                    self._connection.executescript(migration_sql)
                    self._connection.execute(f"PRAGMA user_version = {target_version};")
                    version = target_version
            self._connection.commit()

    def _get_user_version(self) -> int:
        row = self._connection.execute("PRAGMA user_version;").fetchone()
        return int(row[0])

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            is_outer_transaction = self._transaction_depth == 0
            if is_outer_transaction:
                self._connection.execute("BEGIN;")
            self._transaction_depth += 1
            try:
                yield
            except Exception:
                self._transaction_depth -= 1
                if is_outer_transaction:
                    self._connection.rollback()
                    self._transaction_depth = 0
                raise
            else:
                self._transaction_depth -= 1
                if is_outer_transaction:
                    self._connection.commit()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._connection.execute(query, params)
            if self._transaction_depth == 0:
                self._connection.commit()
            return cursor

    def fetchone(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._connection.execute(query, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
