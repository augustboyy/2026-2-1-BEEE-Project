from __future__ import annotations

from pydantic import BaseModel, Field


class PlantCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    species: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=60)


class SensorLogRequest(BaseModel):
    plant_id: int | None = None
    moisture_value: float = Field(..., ge=0, le=100)
    humidity: float | None = Field(default=None, ge=0, le=100)
    temperature: float | None = Field(default=None, ge=-20, le=60)
    light_level: float | None = Field(default=None, ge=0, le=30000)
    source: str = Field(default="external-device", max_length=60)


class WateringLogRequest(BaseModel):
    started_at: str | None = None
    ended_at: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    mode: str = Field(default="manual", max_length=20)
    amount_ml: float | None = Field(default=None, ge=0, le=10000)
    note: str | None = Field(default=None, max_length=300)


class PlantActivationRequest(BaseModel):
    plant_id: int
