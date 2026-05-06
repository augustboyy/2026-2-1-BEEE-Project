"""
이 파일은 애플리케이션의 초기화 및 의존성 주입(Dependency Injection)을 담당합니다.
데이터베이스, 저장소(Repository), 서비스들을 생성하고 연결하여 하나의 런타임 객체로 묶어줍니다.
"""

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
    """
    애플리케이션 실행에 필요한 모든 주요 객체들을 담고 있는 컨테이너 클래스입니다.
    """
    settings: Settings
    database: Database
    repository: PlantRepository
    monitoring_service: MonitoringService


def build_runtime(custom_settings: Settings | None = None) -> Runtime:
    """
    설정 정보를 바탕으로 데이터베이스 초기화 및 각종 서비스 객체들을 생성하여 Runtime 객체를 빌드합니다.
    
    Args:
        custom_settings: 수동으로 전달할 설정 정보 (없으면 기본 설정을 로드함)
        
    Returns:
        초기화가 완료된 Runtime 객체
    """
    # 1. 설정 정보 로드
    settings = custom_settings or load_settings()
    
    # 2. 데이터베이스 초기화 및 스키마 생성
    database = Database(settings.database_path)
    database.init_schema()
    
    # 3. 데이터 저장소(Repository) 생성
    repository = PlantRepository(database)
    
    # 4. 모니터링 서비스 생성 (AI 클라이언트, 센서 시뮬레이터 등을 주입)
    monitoring_service = MonitoringService(
        settings=settings,
        repository=repository,
        ai_client=AIClient(settings),
        simulator=SensorSimulator(),
    )
    
    # 5. 모든 객체를 담은 Runtime 반환
    return Runtime(
        settings=settings,
        database=database,
        repository=repository,
        monitoring_service=monitoring_service,
    )
