"""
센서 시뮬레이터 서비스
식물별로 특징적인 센서 데이터(토양 수분, 습도, 온도, 조도)를 생성하는 역할을 합니다.
실제 하드웨어 센서가 없는 환경에서 테스트 데이터를 제공하기 위해 사용됩니다.
"""

from __future__ import annotations

import random


class SensorSimulator:
    """
    식물의 이름을 기반으로 적절한 센서 데이터를 생성하는 클래스입니다.
    """
    def __init__(self) -> None:
        # 식물 종류별 기본 수치 프로필 (이 수치를 기준으로 랜덤한 변화를 줌)
        self._profiles = {
            "몬스테라": {"moisture": 52.0, "humidity": 63.0, "temperature": 24.0, "light": 6200.0},
            "스투키": {"moisture": 34.0, "humidity": 46.0, "temperature": 23.0, "light": 6800.0},
            "로즈마리": {"moisture": 39.0, "humidity": 44.0, "temperature": 22.0, "light": 7800.0},
            "산세베리아": {"moisture": 36.0, "humidity": 42.0, "temperature": 24.0, "light": 7000.0},
            "기본": {"moisture": 48.0, "humidity": 56.0, "temperature": 23.0, "light": 5900.0},
        }

    def generate(self, plant: dict, source: str = "periodic-simulator") -> dict:
        """
        식물 정보에 맞춰 랜덤한 센서 데이터 스냅샷을 생성합니다.
        
        Args:
            plant: 식물 정보 딕셔너리 (name 필드 포함)
            source: 데이터 생성 출처 구분값
            
        Returns:
            생성된 센서 데이터 (수분, 습도, 온도, 조도 등)
        """
        # 식물 이름에 맞는 프로필 선택
        profile = self._select_profile(plant["name"])
        
        # 데이터에 약간의 하락 추세(drift)를 랜덤하게 섞음
        drift = random.choice([0, 0, 1, 1, 2])
        
        return {
            # 토양 수분: 프로필 기준값 + 랜덤 오차 - 하락 추세 (0~100 사이로 제한)
            "moisture_value": round(max(0.0, min(100.0, profile["moisture"] + random.uniform(-12, 10) - drift * 2.4)), 1),
            # 공기 습도: 프로필 기준값 + 랜덤 오차 (0~100 사이로 제한)
            "humidity": round(max(0.0, min(100.0, profile["humidity"] + random.uniform(-8, 7))), 1),
            # 온도: 프로필 기준값 + 랜덤 오차 (-5~40 사이로 제한)
            "temperature": round(max(-5.0, min(40.0, profile["temperature"] + random.uniform(-2.5, 3.0))), 1),
            # 조도(밝기): 프로필 기준값 + 랜덤 오차 (0~20000 사이로 제한)
            "light_level": round(max(0.0, min(20000.0, profile["light"] + random.uniform(-1700, 2100))), 1),
            "source": source,
        }

    def _select_profile(self, plant_name: str) -> dict:
        """
        식물 이름에 특정 키워드가 포함되어 있는지 확인하여 프로필을 선택합니다.
        """
        for keyword, profile in self._profiles.items():
            if keyword != "기본" and keyword in plant_name:
                return profile
        # 매칭되는 키워드가 없으면 기본 프로필 사용
        return self._profiles["기본"]
