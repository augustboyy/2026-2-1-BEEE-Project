from google import genai
from PIL import Image
import os
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

class GeminiExpert:
    def __init__(self, api_key):
        # 새로운 google.genai Client 사용
        self.client = genai.Client(api_key=api_key)
        self.model_id = 'gemini-3.1-flash-lite-preview'

    def analyze_plant(self, img_path, moisture):
        try:
            if not os.path.exists(img_path):
                return {"score": 0, "summary": "오류", "advice": f"파일을 찾을 수 없습니다: {img_path}"}
                
            img = Image.open(img_path)
            # 이미지 최적화 (2K 수준 리사이징 추천)
            img.thumbnail((2048, 2048))
            
            prompt = f"현재 토양 습도는 {moisture}입니다. 사진을 보고 식물 건강 점수(0-100), 상태 요약, 구체적 조언을 JSON 형식으로 알려줘."
            
            # 새로운 라이브러리의 generate_content 호출 방식
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, img]
            )
            
            # 실제 서비스 시에는 response.text에서 JSON을 파싱해야 함
            return {"score": 80, "summary": "양호", "advice": response.text[:100]}
        except Exception as e:
            return {"score": 0, "summary": "오류", "advice": str(e)}

expert = GeminiExpert(os.getenv("GEMINI_API_KEY"))
result = expert.analyze_plant("test_files/test_plants.jpg", 30)
print(result)
