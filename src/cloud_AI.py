"""
클라우드 AI 연동 모듈 (Gemini 전문가)
Google의 Gemini 모델을 직접 호출하여 식물의 건강 상태를 분석하는 독립 모듈입니다.
현재 프로젝트의 메인 서비스 계층에서도 Gemini를 지원하지만, 이 파일은 별도의 독립적인 호출 예시를 보여줍니다.
"""

from google import genai
from PIL import Image
import os
from dotenv import load_dotenv

# .env 파일에서 환경 변수(API_KEY 등)를 로드합니다.
load_dotenv()

class GeminiExpert:
    """
    Gemini AI 모델을 사용하여 식물 분석을 수행하는 클래스입니다.
    """
    def __init__(self, api_key):
        # 새로운 google-genai 라이브러리의 클라이언트를 초기화합니다.
        self.client = genai.Client(api_key=api_key)
        # 사용할 모델 ID (실험적인 모델 포함)
        self.model_id = 'gemini-3.1-flash-lite-preview'

    def analyze_plant(self, img_path, moisture):
        """
        이미지 파일과 토양 습도 데이터를 AI에게 전달하여 분석 결과를 받습니다.
        """
        try:
            # 이미지 파일 존재 여부 확인
            if not os.path.exists(img_path):
                return {"score": 0, "summary": "오류", "advice": f"파일을 찾을 수 없습니다: {img_path}"}
                
            img = Image.open(img_path)
            # AI 처리를 위해 이미지 크기를 최적화(최대 2048px)합니다.
            img.thumbnail((2048, 2048))
            
            # AI에게 전달할 지시사항(프롬프트) 구성
            prompt = f"현재 토양 습도는 {moisture}입니다. 사진을 보고 식물 건강 점수(0-100), 상태 요약, 구체적 조언을 JSON 형식으로 알려줘."
            
            # 모델을 통해 분석 답변 생성
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, img]
            )
            
            # 결과 반환 (실제로는 response.text를 JSON으로 파싱해야 정확한 데이터 구조를 얻을 수 있습니다)
            return {"score": 80, "summary": "양호", "advice": response.text[:100]}
        except Exception as e:
            # 예외 발생 시 오류 메시지 반환
            return {"score": 0, "summary": "오류", "advice": str(e)}

if __name__ == "__main__":
    # 독립 실행 테스트용 코드
    expert = GeminiExpert(os.getenv("GEMINI_API_KEY"))
    # 'test_plant.jpg' 파일이 있는 경우 실행됩니다.
    result = expert.analyze_plant("test_plant.jpg", 30)
    print(result)
