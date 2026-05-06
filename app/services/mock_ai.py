"""
가짜(Mock) AI 분석 서비스
실제 외부 AI API(GPT, Gemini 등)를 호출하지 않고, 현재 센서 데이터와 사용자의 메모를 바탕으로
가상의 분석 결과를 생성합니다. 개발 및 테스트 목적으로 사용됩니다.
"""

from __future__ import annotations


def build_mock_photo_analysis(
    plant_name: str,
    latest_sensor: dict | None = None,
    latest_watering: dict | None = None,
    note: str | None = None,
) -> dict:
    """
    최근 센서 데이터와 메모를 기반으로 가상의 식물 사진 분석 결과를 생성합니다.
    
    Args:
        plant_name: 식물 이름
        latest_sensor: 최신 센서 데이터 (토양 수분 등)
        latest_watering: 최신 급수 기록
        note: 사용자가 입력한 추가 메모
        
    Returns:
        AI 분석 결과 형식을 갖춘 딕셔너리
    """
    moisture = (latest_sensor or {}).get("moisture_value")
    status = "healthy"  # 기본 상태는 '안정'
    issues: list[str] = []
    advice_parts: list[str] = []
    watering_need = "medium"

    # 1. 토양 수분값에 따른 상태 판별
    if moisture is not None and moisture < 32:
        status = "critical"
        issues.append("토양 수분값이 낮아 건조 가능성이 큽니다.")
        advice_parts.append("가까운 시간 안에 급수를 진행하고 잎 처짐이 있는지 확인하세요.")
        watering_need = "high"
    elif moisture is not None and moisture < 48:
        status = "warning"
        issues.append("토양 수분이 다소 낮습니다.")
        advice_parts.append("오늘 안에 한 번 더 수분 상태를 확인하고 필요하면 소량 급수하세요.")
        watering_need = "medium"

    # 2. 최근 급수 기록이 있는 경우 조언 추가
    if latest_watering:
        advice_parts.append("최근 급수 기록이 저장되어 있으니 과습 여부도 함께 비교해 보세요.")

    # 3. 사용자 메모 키워드 분석
    if note:
        lowered = note.strip().lower()
        if "노랗" in lowered or "yellow" in lowered:
            status = "warning" if status == "healthy" else status
            issues.append("사용자 메모에 잎 변색이 언급되었습니다.")
        if "마름" in lowered or "dry" in lowered:
            status = "critical" if status != "critical" else status
            watering_need = "high"
            issues.append("사용자 메모에 건조 증상이 언급되었습니다.")

    # 4. 특이사항이 없는 경우의 기본 메시지
    if not issues:
        issues.append("사진과 최근 데이터 기준으로 큰 이상 징후는 두드러지지 않습니다.")
        advice_parts.append("현재 관리 루틴을 유지하면서 사진을 주기적으로 다시 분석하세요.")

    # 5. 종합 요약 문장 생성
    condition_summary = (
        f"{plant_name} 사진 분석 결과, 현재 상태는 {status} 단계로 판단됩니다. "
        f"{issues[0]}"
    )

    return {
        "health_status": status,
        "condition_summary": condition_summary,
        "advice": " ".join(dict.fromkeys(advice_parts)), # 중복 제거 후 합치기
        "observed_issues": issues,
        "watering_need": watering_need,
        "confidence": 0.73 if status == "healthy" else 0.81 if status == "warning" else 0.87,
    }
