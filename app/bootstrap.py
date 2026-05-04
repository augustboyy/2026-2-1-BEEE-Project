from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, load_settings
from app.db import Database
from app.repository import PlantRepository
from app.services.ai_client import AIClient
from app.services.monitoring import MonitoringService
from app.services.sensor_simulator import SensorSimulator


@dataclass(slots=True)
class Runtime:
    settings: Settings
    database: Database
    repository: PlantRepository
    monitoring_service: MonitoringService


def build_runtime(custom_settings: Settings | None = None) -> Runtime:
    settings = custom_settings or load_settings()
    database = Database(settings.database_path)
    database.init_schema()
    repository = PlantRepository(database)
    monitoring_service = MonitoringService(
        settings=settings,
        repository=repository,
        ai_client=AIClient(settings),
        simulator=SensorSimulator(),
    )
    return Runtime(
        settings=settings,
        database=database,
        repository=repository,
        monitoring_service=monitoring_service,
    )
