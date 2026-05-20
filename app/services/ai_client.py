"""
이 파일은 Google Gemini AI 서비스를 호출하여 식물을 분석하는 클라이언트를 정의합니다.
이미지 분석 전문가 페르소나를 사용하여 식물의 건강 상태와 점수를 분석합니다.
"""

from __future__ import annotations

import json
import re
from typing import Any
from io import BytesIO

from google import genai
from PIL import Image

from app.config import Settings


# AI로부터 받아올 JSON 데이터의 구조(Schema)를 정의합니다.
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "health_status": {
            "type": "string",
            "enum": ["healthy", "warning", "critical"],
        },
        "health_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        },
        "condition_summary": {"type": "string"},
        "advice": {"type": "string"},
        "observed_issues": {
            "type": "array",
            "items": {"type": "string"},
        },
        "watering_need": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "health_status",
        "health_score",
        "condition_summary",
        "advice",
        "observed_issues",
        "watering_need",
        "confidence",
    ],
    "additionalProperties": False,
}


class AIClient:
    """Google Gemini API와의 통신을 담당하는 클라이언트 클래스입니다."""
    
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Google GenAI 클라이언트 초기화
        self.client = genai.Client(api_key=self.settings.gemini_api_key)
        # 사용할 모델 설정 (settings에 정의된 모델 사용)
        self.model_id = self.settings.gemini_model

    async def analyze_plant_photo(
        self,
        plant: dict[str, Any],
        image_bytes: bytes,
        mime_type: str,
        latest_sensor: dict[str, Any] | None = None,
        latest_watering: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """
        Gemini를 호출하여 식물을 분석합니다.
        """
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

        # 이미지 처리 (PIL을 사용하여 최적화)
        img = Image.open(BytesIO(image_bytes))
        img.thumbnail((2048, 2048))

        prompt = self._build_prompt(plant, latest_sensor, latest_watering, note)
        
        try:
            # Gemini 모델 호출
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, img],
                config={
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                }
            )
            
            raw_text = response.text
            parsed_json = self._extract_json(raw_text)
            
            return {
                "provider": "gemini",
                "model_name": self.model_id,
                "prompt_text": prompt,
                "result": self._normalize_result(parsed_json),
                "raw_response_text": raw_text,
            }
        except Exception as e:
            raise RuntimeError(f"Gemini API 호출 중 오류 발생: {str(e)}")

    def _build_prompt(
        self,
        plant: dict[str, Any],
        latest_sensor: dict[str, Any] | None,
        latest_watering: dict[str, Any] | None,
        note: str | None,
    ) -> str:
        """AI에게 보낼 질문(Prompt)을 생성합니다."""
        sensor_text = json.dumps(latest_sensor or {}, ensure_ascii=False)
        watering_text = json.dumps(latest_watering or {}, ensure_ascii=False)
        note_text = note.strip() if note else "없음"
        
        return (
            "당신은 식물 병해충 및 생육 상태를 분석하는 20년 경력의 수목의학 전문가이자 식물 클리닉 원장입니다. "
            "현재 식물에 이상이 감지되어 정밀 진단이 필요한 상황입니다. "
            "제공된 사진과 환경 데이터를 바탕으로 전문가의 시각에서 식물을 철저히 분석하세요.\n\n"
            "반드시 아래의 JSON 형식을 지켜 답변하세요:\n"
            "{\n"
            '  "health_status": "healthy" | "warning" | "critical",\n'
            '  "health_score": 0~100 사이의 정수 (100점 만점 기준의 건강도 점수),\n'
            '  "condition_summary": "현재 식물 상태에 대한 전문가적 요약",\n'
            '  "advice": "구체적이고 실천 가능한 조치 방안",\n'
            '  "observed_issues": ["감지된 문제점 리스트"],\n'
            '  "watering_need": "low" | "medium" | "high",\n'
            '  "confidence": 0~1 사이의 신뢰도\n'
            "}\n\n"
            f"식물 이름: {plant['name']}\n"
            f"식물 종류: {plant.get('species') or '미입력'}\n"
            f"식물 위치: {plant.get('location') or '미입력'}\n"
            f"최근 센서 데이터: {sensor_text}\n"
            f"최근 급수 기록: {watering_text}\n"
            f"특이 사항: {note_text}"
        )

    def _extract_json(self, text: str) -> dict[str, Any]:
        """응답 텍스트에서 JSON 부분을 추출하여 파싱합니다."""
        stripped = text.strip()
        if stripped.startswith("{"):
            return json.loads(stripped)

        # ```json ... ``` 형태인 경우 내부 텍스트만 추출
        fenced = re.search(r"\{.*\}", stripped, re.DOTALL)
        if fenced:
            return json.loads(fenced.group(0))
        raise ValueError("AI 응답에 유효한 JSON이 포함되어 있지 않습니다.")

    def _normalize_result(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """AI의 응답 데이터를 애플리케이션 표준 형식으로 정제합니다."""
        observed_issues = parsed.get("observed_issues") or []
        if isinstance(observed_issues, str):
            observed_issues = [observed_issues]

        result = {
            "health_status": str(parsed.get("health_status", "warning")).lower(),
            "health_score": int(parsed.get("health_score", 0)),
            "condition_summary": str(parsed.get("condition_summary", "")).strip(),
            "advice": str(parsed.get("advice", "")).strip(),
            "observed_issues": [str(item).strip() for item in observed_issues if str(item).strip()],
            "watering_need": str(parsed.get("watering_need", "medium")).lower(),
            "confidence": float(parsed.get("confidence", 0.0)),
        }

        # 유효하지 않은 값들에 대한 기본값 처리
        if result["health_status"] not in {"healthy", "warning", "critical"}:
            result["health_status"] = "warning"
        
        # 점수 범위 제한
        result["health_score"] = max(0, min(100, result["health_score"]))
        
        if result["watering_need"] not in {"low", "medium", "high"}:
            result["watering_need"] = "medium"
        result["confidence"] = max(0.0, min(1.0, result["confidence"]))
        
        if not result["condition_summary"]:
            result["condition_summary"] = "AI가 사진을 분석했지만 요약 문장을 충분히 반환하지 않았습니다."
        if not result["advice"]:
            result["advice"] = "사진을 다시 촬영해 분석하거나 최근 센서값과 함께 재요청해 주세요."
        return result

    async def identify_plant_species(self) -> str:
        """
        카메라로 실물을 촬영하고, 사진을 AI에게 보내 식물이 무엇인지 한 가지 추측값만 반환받습니다.
        """
        from app.services.camera import capture_photo
        
        try:
            # 1. 카메라 촬영 (새로운 파이썬 파일 호출)
            image_bytes = capture_photo()
        except Exception as e:
            raise RuntimeError(f"카메라 촬영 실패: {e}")

        # 2. 이미지 처리
        img = Image.open(BytesIO(image_bytes)) # 이미지 사용 후 바로 폐기됨
        img.thumbnail((1024, 1024))
        
        prompt = "이 식물이 무엇인지 가장 가능성 높은 식물 종(species) 단 하나만 문자열로 알려줘. 다른 설명, 인사말, 구두점 없이 딱 이름만 말해."
        
        try:
            # Gemini 모델 호출
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, img],
                config={
                    "temperature": 0.1,
                }
            )
            return response.text.strip()
        except Exception as e:
            raise RuntimeError(f"식물 추정 중 오류 발생: {str(e)}")
