from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.services.mock_ai import build_mock_photo_analysis


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "health_status": {
            "type": "string",
            "enum": ["healthy", "warning", "critical"],
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
        "condition_summary",
        "advice",
        "observed_issues",
        "watering_need",
        "confidence",
    ],
    "additionalProperties": False,
}


class AIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze_plant_photo(
        self,
        plant: dict[str, Any],
        image_bytes: bytes,
        mime_type: str,
        latest_sensor: dict[str, Any] | None = None,
        latest_watering: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if self.settings.ai_provider == "mock":
            result = build_mock_photo_analysis(plant["name"], latest_sensor, latest_watering, note)
            return {
                "provider": "mock",
                "model_name": "demo-photo-analyzer",
                "prompt_text": self._build_prompt(plant, latest_sensor, latest_watering, note),
                "result": result,
                "raw_response_text": json.dumps(result, ensure_ascii=False),
            }

        if self.settings.ai_provider == "openai":
            return await self._analyze_with_openai(plant, image_bytes, mime_type, latest_sensor, latest_watering, note)

        if self.settings.ai_provider == "gemini":
            return await self._analyze_with_gemini(plant, image_bytes, mime_type, latest_sensor, latest_watering, note)

        raise RuntimeError(f"Unsupported AI_PROVIDER: {self.settings.ai_provider}")

    def _build_prompt(
        self,
        plant: dict[str, Any],
        latest_sensor: dict[str, Any] | None,
        latest_watering: dict[str, Any] | None,
        note: str | None,
    ) -> str:
        sensor_text = json.dumps(latest_sensor or {}, ensure_ascii=False)
        watering_text = json.dumps(latest_watering or {}, ensure_ascii=False)
        note_text = note.strip() if note else "없음"
        return (
            "당신은 식물 상태를 분석하는 전문가입니다. 업로드된 식물 사진을 보고 건강 상태를 분석하세요. "
            "최근 센서값과 급수 기록도 함께 고려하세요. 반드시 JSON만 반환하세요. "
            "필드: health_status(healthy|warning|critical), condition_summary, advice, "
            "observed_issues(string array), watering_need(low|medium|high), confidence(0~1).\n"
            f"식물 이름: {plant['name']}\n"
            f"식물 종류: {plant.get('species') or '미입력'}\n"
            f"식물 위치: {plant.get('location') or '미입력'}\n"
            f"최근 센서 데이터: {sensor_text}\n"
            f"최근 급수 기록: {watering_text}\n"
            f"사용자 메모: {note_text}"
        )

    async def _analyze_with_openai(
        self,
        plant: dict[str, Any],
        image_bytes: bytes,
        mime_type: str,
        latest_sensor: dict[str, Any] | None,
        latest_watering: dict[str, Any] | None,
        note: str | None,
    ) -> dict[str, Any]:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        encoded = base64.b64encode(image_bytes).decode("utf-8")
        prompt = self._build_prompt(plant, latest_sensor, latest_watering, note)
        body = {
            "model": self.settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You analyze plant photos. Return strict JSON only.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "plant_photo_analysis",
                    "strict": True,
                    "schema": ANALYSIS_SCHEMA,
                },
            },
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()

        raw_text = payload["choices"][0]["message"]["content"]
        return {
            "provider": "openai",
            "model_name": self.settings.openai_model,
            "prompt_text": prompt,
            "result": self._normalize_result(self._extract_json(raw_text)),
            "raw_response_text": raw_text,
        }

    async def _analyze_with_gemini(
        self,
        plant: dict[str, Any],
        image_bytes: bytes,
        mime_type: str,
        latest_sensor: dict[str, Any] | None,
        latest_watering: dict[str, Any] | None,
        note: str | None,
    ) -> dict[str, Any]:
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        encoded = base64.b64encode(image_bytes).decode("utf-8")
        prompt = self._build_prompt(plant, latest_sensor, latest_watering, note)
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.settings.gemini_api_key,
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"

        async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()

        raw_text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return {
            "provider": "gemini",
            "model_name": self.settings.gemini_model,
            "prompt_text": prompt,
            "result": self._normalize_result(self._extract_json(raw_text)),
            "raw_response_text": raw_text,
        }

    def _extract_json(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("{"):
            return json.loads(stripped)

        fenced = re.search(r"\{.*\}", stripped, re.DOTALL)
        if fenced:
            return json.loads(fenced.group(0))
        raise ValueError("AI response did not contain valid JSON.")

    def _normalize_result(self, parsed: dict[str, Any]) -> dict[str, Any]:
        observed_issues = parsed.get("observed_issues") or []
        if isinstance(observed_issues, str):
            observed_issues = [observed_issues]

        result = {
            "health_status": str(parsed.get("health_status", "warning")).lower(),
            "condition_summary": str(parsed.get("condition_summary", "")).strip(),
            "advice": str(parsed.get("advice", "")).strip(),
            "observed_issues": [str(item).strip() for item in observed_issues if str(item).strip()],
            "watering_need": str(parsed.get("watering_need", "medium")).lower(),
            "confidence": float(parsed.get("confidence", 0.0)),
        }

        if result["health_status"] not in {"healthy", "warning", "critical"}:
            result["health_status"] = "warning"
        if result["watering_need"] not in {"low", "medium", "high"}:
            result["watering_need"] = "medium"
        result["confidence"] = max(0.0, min(1.0, result["confidence"]))
        if not result["condition_summary"]:
            result["condition_summary"] = "AI가 사진을 분석했지만 요약 문장을 충분히 반환하지 않았습니다."
        if not result["advice"]:
            result["advice"] = "사진을 다시 촬영해 분석하거나 최근 센서값과 함께 재요청해 주세요."
        return result
