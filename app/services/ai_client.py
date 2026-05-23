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
        },
    },
    "required": [
        "health_score",
        "condition_summary",
        "advice",
        "observed_issues",
        "watering_need",
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
        mime_type: str,
        image_bytes: bytes | None = None,
        image_path: str | None = None,
        latest_sensor: dict[str, Any] | None = None,
        latest_watering: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """
        Gemini를 호출하여 식물을 분석합니다.
        메모리 부족을 막기 위해 8MP 원본 대신 1536px로 축소/전처리된 임시 파일을 사용합니다.
        """
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

        import os
        import uuid
        from app.services.camera import create_preprocessed_temp
        
        temp_1536_path = os.path.join(self.settings.uploads_dir, f"temp_1536_{uuid.uuid4().hex}.jpg")
        
        try:
            # 1. 1536px 전처리본 생성 (파일 경로가 주어졌으면 파일에서, 바이트면 바이트에서)
            if image_path and os.path.exists(image_path):
                create_preprocessed_temp(image_path, temp_1536_path, max_dim=1536, apply_enhancement=True)
            elif image_bytes:
                # API로 수동 업로드된 경우 바이트 사용
                with open(temp_1536_path, "wb") as f:
                    f.write(image_bytes)
                create_preprocessed_temp(temp_1536_path, temp_1536_path, max_dim=1536, apply_enhancement=True)
            else:
                raise ValueError("image_bytes 또는 image_path 둘 중 하나는 제공되어야 합니다.")

            # 2. PIL로 가볍게 열기
            img = Image.open(temp_1536_path)

            prompt = self._build_prompt(plant, latest_sensor, latest_watering, note)
            
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
        finally:
            if 'img' in locals():
                img.close()
            if os.path.exists(temp_1536_path):
                try: os.remove(temp_1536_path)
                except: pass

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
        note_text = note.strip() if note else ""
        abnormality_note = f" (이상 징후: {note_text})" if note_text else ""
        note_summary = note_text or "없음"
        
        return (
            "당신은 식물 병해충 및 생육 상태를 분석하는 20년 경력의 수목의학 전문가이자 식물 클리닉 원장입니다. "
            f"현재 식물에 이상이 감지되어 정밀 진단이 필요한 상황입니다.{abnormality_note} "
            "제공된 사진과 환경 데이터를 바탕으로 전문가의 시각에서 식물을 철저히 분석하세요.\n\n"
            "반드시 아래의 JSON 형식을 지켜 답변하세요:\n"
            "{\n"
            '  "health_score": 0~100 사이의 정수 (100점 만점 기준의 건강도 점수),\n'
            '  "condition_summary": "현재 식물 상태에 대한 전문가적 요약",\n'
            '  "advice": "구체적이고 실천 가능한 조치 방안",\n'
            '  "observed_issues": ["감지된 문제점 리스트"],\n'
            '  "watering_need": "급수가 필요하다고 판단되면 \'급수를 하는걸 추천합니다\'라고 작성, 아니면 빈 문자열(\'\')로 작성"\n'
            "}\n\n"
            f"식물 이름: {plant['name']}\n"
            f"식물 종류: {plant.get('species') or '미입력'}\n"
            f"식물 위치: {plant.get('location') or '미입력'}\n"
            f"최근 센서 데이터: {sensor_text}\n"
            f"최근 급수 기록: {watering_text}\n"
            f"특이 사항: {note_summary}"
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

        health_score = int(parsed.get("health_score", 0))
        health_score = max(0, min(100, health_score))
        
        # 점수에 따른 상태값 도출
        if health_score <= 30:
            health_status = "critical"
        elif health_score <= 60:
            health_status = "warning"
        else:
            health_status = "healthy"

        result = {
            "health_status": health_status,
            "health_score": health_score,
            "condition_summary": str(parsed.get("condition_summary", "")).strip(),
            "advice": str(parsed.get("advice", "")).strip(),
            "observed_issues": [str(item).strip() for item in observed_issues if str(item).strip()],
            "watering_need": str(parsed.get("watering_need", "")).strip(),
            "confidence": 1.0, # DB 스키마 호환성을 위해 1.0 고정 (UI에선 숨김)
        }

        if not result["condition_summary"]:
            result["condition_summary"] = "AI가 사진을 분석했지만 요약 문장을 충분히 반환하지 않았습니다."
        if not result["advice"]:
            result["advice"] = "사진을 다시 촬영해 분석하거나 최근 센서값과 함께 재요청해 주세요."
        return result

    async def identify_plant_species(self) -> str:
        """
        카메라로 실물을 촬영하고, 사진을 AI에게 보내 식물이 무엇인지 한 가지 추측값만 반환받습니다.
        """
        from app.services.camera import capture_photo_to_disk, create_preprocessed_temp
        import os
        import uuid
        
        original_path = os.path.join(self.settings.uploads_dir, f"temp_species_{uuid.uuid4().hex}.jpg")
        temp_1536_path = os.path.join(self.settings.uploads_dir, f"temp_1536_{uuid.uuid4().hex}.jpg")
        
        try:
            # 1. 고해상도 촬영 후 디스크 저장
            capture_photo_to_disk(original_path)
            # 2. 1536px로 리사이징
            create_preprocessed_temp(original_path, temp_1536_path, max_dim=1536)
            
            # 3. 이미지 처리
            img = Image.open(temp_1536_path) 
            
            prompt = "이 식물이 무엇인지 가장 가능성 높은 식물 종(species) 단 하나만 문자열로 알려줘. 다른 설명, 인사말, 구두점 없이 딱 이름만 말해."
            
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
        finally:
            if 'img' in locals(): img.close()
            if os.path.exists(temp_1536_path):
                try: os.remove(temp_1536_path)
                except: pass
            if os.path.exists(original_path):
                try: os.remove(original_path)
                except: pass

    async def ask_plant_question(self, plant: dict[str, Any], image_path: str, question: str) -> str:
        """
        카메라로 찍은 사진과 사용자의 텍스트 질문을 Gemini에게 보내서 직접적인 답변을 받습니다.
        메모리 부족을 방지하기 위해 8MP 원본 대신 1536px로 전처리된 임시 파일을 생성하여 사용 후 삭제합니다.
        """
        if not self.settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

        import os
        import uuid
        from app.services.camera import create_preprocessed_temp
        
        temp_1536_path = os.path.join(self.settings.uploads_dir, f"temp_1536_{uuid.uuid4().hex}.jpg")
        
        try:
            create_preprocessed_temp(image_path, temp_1536_path, max_dim=1536, apply_enhancement=True)
            img = Image.open(temp_1536_path)

            prompt = (
                f"당신은 친절하고 전문적인 20년 경력의 식물 전문가(수목의학 전문가)입니다.\n"
                f"현재 식물 이름: {plant['name']}\n"
                f"식물 종류: {plant.get('species') or '미입력'}\n"
                f"사용자의 질문: \"{question}\"\n\n"
                f"첨부된 사진은 지금 막 촬영된 식물의 현재 상태입니다.\n"
                f"이 사진을 자세히 관찰하고 사용자의 질문에 대해 명확, 친절하고 도움이 되는 답변을 작성해주세요.\n"
                f"단, 키오스크 화면에 표시되어야 하므로 **답변은 반드시 4문장 이내로 짧고 간결하게 작성**해 주세요."
            )

            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, img],
                config={"temperature": 0.3}
            )
            return response.text.strip()
        except Exception as e:
            raise RuntimeError(f"Gemini AI 질문 처리 중 오류 발생: {str(e)}")
        finally:
            if 'img' in locals(): img.close()
            if os.path.exists(temp_1536_path):
                try: os.remove(temp_1536_path)
                except: pass
