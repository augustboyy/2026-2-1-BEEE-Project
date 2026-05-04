from __future__ import annotations


def build_mock_photo_analysis(
    plant_name: str,
    latest_sensor: dict | None = None,
    latest_watering: dict | None = None,
    note: str | None = None,
) -> dict:
    moisture = (latest_sensor or {}).get("moisture_value")
    status = "healthy"
    issues: list[str] = []
    advice_parts: list[str] = []
    watering_need = "medium"

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

    if latest_watering:
        advice_parts.append("최근 급수 기록이 저장되어 있으니 과습 여부도 함께 비교해 보세요.")

    if note:
        lowered = note.strip().lower()
        if "노랗" in lowered or "yellow" in lowered:
            status = "warning" if status == "healthy" else status
            issues.append("사용자 메모에 잎 변색이 언급되었습니다.")
        if "마름" in lowered or "dry" in lowered:
            status = "critical" if status != "critical" else status
            watering_need = "high"
            issues.append("사용자 메모에 건조 증상이 언급되었습니다.")

    if not issues:
        issues.append("사진과 최근 데이터 기준으로 큰 이상 징후는 두드러지지 않습니다.")
        advice_parts.append("현재 관리 루틴을 유지하면서 사진을 주기적으로 다시 분석하세요.")

    condition_summary = (
        f"{plant_name} 사진 분석 결과, 현재 상태는 {status} 단계로 판단됩니다. "
        f"{issues[0]}"
    )

    return {
        "health_status": status,
        "condition_summary": condition_summary,
        "advice": " ".join(dict.fromkeys(advice_parts)),
        "observed_issues": issues,
        "watering_need": watering_need,
        "confidence": 0.73 if status == "healthy" else 0.81 if status == "warning" else 0.87,
    }
