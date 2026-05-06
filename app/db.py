"""
이 파일은 SQLite 데이터베이스 연결 및 스키마 관리를 담당합니다.
애플리케이션에서 사용하는 모든 테이블 구조와 인덱스를 정의하며,
트랜잭션 관리 및 쿼리 실행을 위한 래퍼 함수를 제공합니다.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# 데이터베이스 스키마 버전 관리를 위한 변수입니다.
CURRENT_SCHEMA_VERSION = 2


# 기본이 되는 테이블 구조를 정의합니다. (식물, 사진, 센서 로그, 급수 로그, AI 분석 결과 등)
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


# 확장된 기능을 위한 추가 스키마를 정의합니다. (식물 프로필, 카메라 캡처, AI 알림 등)
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


# 검색 성능 향상을 위한 인덱스들을 정의합니다.
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


# 모든 SQL 구문을 합칩니다.
SCHEMA_SQL = BASE_SCHEMA_SQL + EXTENDED_SCHEMA_SQL + INDEX_SQL


class Database:
    """
    SQLite 데이터베이스 작업을 캡슐화한 클래스입니다.
    스레드 안전(Thread-safe)한 접근과 트랜잭션 관리를 지원합니다.
    """
    def __init__(self, db_path: str) -> None:
        """
        데이터베이스 파일 경로를 받아 연결을 초기화합니다.
        
        Args:
            db_path: SQLite DB 파일 경로
        """
        self.db_path = Path(db_path)
        # DB 파일이 들어갈 디렉토리가 없으면 생성합니다.
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 멀티스레드 환경에서의 안전한 접근을 위한 락(Lock)
        self._lock = threading.RLock()
        self._transaction_depth = 0
        
        # SQLite 연결 설정 (WAL 모드 등을 활성화하여 성능 및 동시성 향상)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row  # 결과를 딕셔너리처럼 접근할 수 있게 합니다.
        self._connection.execute("PRAGMA foreign_keys = ON;")  # 외래 키 제약 조건 활성화
        self._connection.execute("PRAGMA journal_mode = WAL;")  # Write-Ahead Logging 활성화
        self._connection.execute("PRAGMA busy_timeout = 5000;")  # DB 잠금 시 대기 시간 설정

    def init_schema(self) -> None:
        """
        정의된 스키마 SQL을 실행하여 테이블과 인덱스를 생성하고 버전을 관리합니다.
        """
        with self._lock:
            version = self._get_user_version()
            migrations = (
                (1, BASE_SCHEMA_SQL),
                (2, EXTENDED_SCHEMA_SQL + INDEX_SQL),
            )
            for target_version, migration_sql in migrations:
                if version < target_version:
                    # 지정된 버전까지 순차적으로 마이그레이션 실행
                    self._connection.executescript(migration_sql)
                    self._connection.execute(f"PRAGMA user_version = {target_version};")
                    version = target_version
            self._connection.commit()

    def _get_user_version(self) -> int:
        """현재 DB의 스키마 버전을 가져옵니다."""
        row = self._connection.execute("PRAGMA user_version;").fetchone()
        return int(row[0])

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """
        트랜잭션 관리를 위한 컨텍스트 매니저입니다.
        예외 발생 시 롤백(Rollback)하고, 성공 시 커밋(Commit)합니다.
        """
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
        """SQL 쿼리를 실행합니다."""
        with self._lock:
            cursor = self._connection.execute(query, params)
            if self._transaction_depth == 0:
                self._connection.commit()
            return cursor

    def fetchone(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        """쿼리 실행 결과 중 첫 번째 행을 반환합니다."""
        with self._lock:
            return self._connection.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """쿼리 실행 결과의 모든 행을 반환합니다."""
        with self._lock:
            return self._connection.execute(query, params).fetchall()

    def close(self) -> None:
        """데이터베이스 연결을 닫습니다."""
        with self._lock:
            self._connection.close()
