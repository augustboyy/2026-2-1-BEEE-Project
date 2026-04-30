import google.generativeai as genai
from PIL import Image

class GeminiExpert:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def analyze_plant(self, img_path, moisture):
        try:
            img = Image.open(img_path)
            # 이미지 최적화 (2K 수준 리사이징 추천)
            img.thumbnail((2048, 2048))
            
            prompt = f"현재 토양 습도는 {moisture}입니다. 사진을 보고 식물 건강 점수(0-100), 상태 요약, 구체적 조언을 JSON 형식으로 알려줘."
            response = self.model.generate_content([prompt, img])
            
            # 실제 서비스 시에는 response.text에서 JSON을 파싱해야 함
            return {"score": 80, "summary": "양호", "advice": response.text[:100]}
        except Exception as e:
            return {"score": 0, "summary": "오류", "advice": str(e)}