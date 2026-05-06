"""
이 파일은 API 요청 시 사용되는 데이터 모델(Schema)을 정의합니다.
Pydantic을 사용하여 데이터의 형식을 검증하고 유효성을 체크합니다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlantCreateRequest(BaseModel):
    """새로운 식물 등록 요청을 위한 모델입니다."""
    name: str = Field(..., min_length=1, max_length=60)  # 식물 이름 (필수, 1~60자)
    species: str | None = Field(default=None, max_length=60)  # 식물 종류 (선택)
    location: str | None = Field(default=None, max_length=60)  # 식물 위치 (선택)


class SensorLogRequest(BaseModel):
    """센서 데이터 전송 요청을 위한 모델입니다."""
    plant_id: int | None = None  # 식물 ID (선택)
    moisture_value: float = Field(..., ge=0, le=100)  # 토양 수분 (0~100%)
    humidity: float | None = Field(default=None, ge=0, le=100)  # 습도 (0~100%)
    temperature: float | None = Field(default=None, ge=-20, le=60)  # 온도 (-20~60°C)
    light_level: float | None = Field(default=None, ge=0, le=30000)  # 광량 (0~30000 lux)
    source: str = Field(default="external-device", max_length=60)  # 데이터 출처


class WateringLogRequest(BaseModel):
    """급수 기록 전송 요청을 위한 모델입니다."""
    started_at: str | None = None  # 시작 시간 (ISO 포맷)
    ended_at: str | None = None  # 종료 시간 (ISO 포맷)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)  # 급수 지속 시간(초)
    mode: str = Field(default="manual", max_length=20)  # 급수 모드 (수동/자동)
    amount_ml: float | None = Field(default=None, ge=0, le=10000)  # 급수량(ml)
    note: str | None = Field(default=None, max_length=300)  # 추가 메모


class PlantActivationRequest(BaseModel):
    """식물 활성화 요청을 위한 모델입니다."""
    plant_id: int  # 활성화할 식물의 ID
