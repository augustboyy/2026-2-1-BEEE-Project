from __future__ import annotations

import random


class SensorSimulator:
    def __init__(self) -> None:
        self._profiles = {
            "몬스테라": {"moisture": 52.0, "humidity": 63.0, "temperature": 24.0, "light": 6200.0},
            "스투키": {"moisture": 34.0, "humidity": 46.0, "temperature": 23.0, "light": 6800.0},
            "로즈마리": {"moisture": 39.0, "humidity": 44.0, "temperature": 22.0, "light": 7800.0},
            "산세베리아": {"moisture": 36.0, "humidity": 42.0, "temperature": 24.0, "light": 7000.0},
            "기본": {"moisture": 48.0, "humidity": 56.0, "temperature": 23.0, "light": 5900.0},
        }

    def generate(self, plant: dict, source: str = "periodic-simulator") -> dict:
        profile = self._select_profile(plant["name"])
        drift = random.choice([0, 0, 1, 1, 2])
        return {
            "moisture_value": round(max(0.0, min(100.0, profile["moisture"] + random.uniform(-12, 10) - drift * 2.4)), 1),
            "humidity": round(max(0.0, min(100.0, profile["humidity"] + random.uniform(-8, 7))), 1),
            "temperature": round(max(-5.0, min(40.0, profile["temperature"] + random.uniform(-2.5, 3.0))), 1),
            "light_level": round(max(0.0, min(20000.0, profile["light"] + random.uniform(-1700, 2100))), 1),
            "source": source,
        }

    def _select_profile(self, plant_name: str) -> dict:
        for keyword, profile in self._profiles.items():
            if keyword != "기본" and keyword in plant_name:
                return profile
        return self._profiles["기본"]
