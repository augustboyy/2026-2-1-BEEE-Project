from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from app.bootstrap import build_runtime
from app.config import load_settings


STATUS_META = {
    "healthy": {"label": "안정", "color": "#2f7d4a"},
    "warning": {"label": "주의", "color": "#d97706"},
    "critical": {"label": "위험", "color": "#c2410c"},
    None: {"label": "대기", "color": "#3558ff"},
}

WATERING_META = {
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
    None: "-",
}


@st.cache_resource
def get_runtime():
    return build_runtime()


def api_request(method: str, path: str, **kwargs) -> dict[str, Any]:
    settings = load_settings()
    with httpx.Client(base_url=settings.api_base_url, timeout=60) as client:
        response = client.request(method, path, **kwargs)
        if response.is_error:
            detail = response.text
            try:
                payload = response.json()
                detail = payload.get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(detail)
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return {}


def fmt_time(value: str | None) -> str:
    if not value:
        return "-"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def apply_page_style() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: linear-gradient(180deg, #f9f5eb 0%, #f2efe7 100%); }
        .hero-box, .section-box, .metric-box {
          border: 2px solid #171717; border-radius: 24px; background: rgba(255,255,255,0.82);
          box-shadow: 8px 8px 0 rgba(53,88,255,0.14); padding: 1.2rem 1.3rem;
        }
        .hero-box { padding: 2rem; }
        .metric-box { min-height: 128px; }
        .status-pill {
          display: inline-block; padding: 0.45rem 0.9rem; border-radius: 999px;
          font-weight: 700; border: 2px solid #171717; margin-bottom: 0.6rem;
        }
        .step-chip {
          display: inline-block; padding: 0.35rem 0.8rem; border-radius: 999px;
          background: #dce4ff; border: 1px solid #171717; margin-right: 0.4rem; font-size: 0.9rem;
        }
        .eyebrow { color: #3558ff; font-weight: 800; letter-spacing: 0.08em; font-size: 0.8rem; }
        .subtle { color: #5f584e; font-size: 0.92rem; }
        .issue-item {
          padding: 0.4rem 0.7rem; border-radius: 12px; background: #fff7ed;
          border: 1px solid rgba(23,23,23,0.15); margin-bottom: 0.4rem;
        }
        .info-table th, .info-table td { text-align: left !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_start_screen() -> None:
    st.markdown(
        """
        <div class="hero-box">
          <div class="eyebrow">AI PLANT MONITOR</div>
          <h1 style="margin:0.3rem 0 0.8rem 0;">식물 사진을 외부 AI가 분석하고, 센서와 급수 기록을 함께 보여줍니다.</h1>
          <p class="subtle">
            문서의 권장 구조에 맞춰 데이터 수신, SQLite 저장, 화면 표시를 분리했습니다.
            먼저 식물을 등록한 뒤 사진 업로드 분석을 시작하세요.
          </p>
          <div style="margin-top:1rem;">
            <span class="step-chip">1. 식물 등록</span>
            <span class="step-chip">2. 사진 업로드</span>
            <span class="step-chip">3. AI 분석 저장</span>
            <span class="step-chip">4. 센서/급수 이력 확인</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_registration_form() -> None:
    st.subheader("식물 등록")
    with st.form("register_plant"):
        name = st.text_input("식물 이름", placeholder="예: 몬스테라")
        species = st.text_input("식물 종류", placeholder="예: 천남성과")
        location = st.text_input("식물 위치", placeholder="예: 실험실 창가")
        submitted = st.form_submit_button("모니터링 시작", use_container_width=True)
        if submitted:
            if not name.strip():
                st.error("식물 이름을 입력해 주세요.")
            else:
                with st.spinner("식물을 등록하고 초기 센서 상태를 만드는 중입니다..."):
                    api_request(
                        "POST",
                        "/api/plants",
                        json={
                            "name": name.strip(),
                            "species": species.strip() or None,
                            "location": location.strip() or None,
                        },
                    )
                st.session_state.selected_plant_id = None
                st.session_state.show_register = False
                st.rerun()


def plant_label(plant: dict[str, Any]) -> str:
    status = plant.get("latest_health_status") or "대기"
    return f"{plant['name']} ({status})"


def render_sidebar(runtime) -> dict[str, Any] | None:
    st.sidebar.title("대시보드 제어")
    st.sidebar.caption("센서 수집과 AI 분석 결과는 SQLite에 저장됩니다.")
    plants = runtime.repository.list_plants()

    if st.sidebar.button("새 식물 등록", use_container_width=True):
        st.session_state.show_register = True

    if st.sidebar.button("화면 새로고침", use_container_width=True):
        st.rerun()

    if not plants:
        return None

    active_plant = runtime.repository.get_current_plant() or plants[0]
    labels = [plant_label(plant) for plant in plants]
    active_index = next((index for index, plant in enumerate(plants) if plant["id"] == active_plant["id"]), 0)
    chosen_label = st.sidebar.selectbox("현재 볼 식물", labels, index=active_index)
    selected_plant = plants[labels.index(chosen_label)]
    st.session_state.selected_plant_id = selected_plant["id"]

    if not selected_plant["is_active"]:
        if st.sidebar.button("이 식물을 활성 세션으로 전환", use_container_width=True):
            api_request("POST", "/api/plants/activate", json={"plant_id": selected_plant["id"]})
            st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.write("실시간 구성")
    st.sidebar.write(f"- API 주소: `{load_settings().api_base_url}`")
    st.sidebar.write(f"- AI 제공자: `{load_settings().ai_provider}`")
    st.sidebar.write(f"- 센서 주기: `{load_settings().sensor_interval_seconds}초`")
    return selected_plant


def render_status_banner(dashboard: dict[str, Any]) -> None:
    latest_state = dashboard.get("latest_state") or {}
    latest_analysis = dashboard.get("latest_analysis") or {}
    meta = STATUS_META.get(latest_state.get("latest_health_status"), STATUS_META[None])
    st.markdown(
        f"""
        <div class="hero-box">
          <div class="eyebrow">CURRENT PLANT STATUS</div>
          <span class="status-pill" style="background:{meta['color']}22; color:{meta['color']};">{meta['label']}</span>
          <h2 style="margin:0;">{dashboard['plant']['name']}</h2>
          <p class="subtle" style="margin-top:0.6rem;">
            AI 업데이트: {fmt_time(latest_state.get('ai_updated_at'))} |
            사용자 확인: {fmt_time(latest_state.get('ai_confirmed_at'))} |
            최근 분석 모델: {latest_analysis.get('model_name', '-')}
          </p>
          <p style="margin:0.8rem 0 0 0;">{latest_state.get('latest_condition_summary') or '아직 사진 분석 결과가 없습니다.'}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(dashboard: dict[str, Any]) -> None:
    sensor = dashboard.get("latest_sensor_state") or {}
    latest_state = dashboard.get("latest_state") or {}
    watering = dashboard.get("latest_watering_log") or {}
    counts = dashboard.get("counts") or {}
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(
        f"<div class='metric-box'><div class='eyebrow'>토양 수분</div><h3>{sensor.get('moisture_value', '-')}%</h3><div class='subtle'>{fmt_time(sensor.get('received_at'))}</div></div>",
        unsafe_allow_html=True,
    )
    col2.markdown(
        f"<div class='metric-box'><div class='eyebrow'>온도 / 습도</div><h3>{sensor.get('temperature', '-')}°C / {sensor.get('humidity', '-')}%</h3><div class='subtle'>광량 {sensor.get('light_level', '-')} lux</div></div>",
        unsafe_allow_html=True,
    )
    col3.markdown(
        f"<div class='metric-box'><div class='eyebrow'>급수 필요도</div><h3>{WATERING_META.get(latest_state.get('latest_watering_need'))}</h3><div class='subtle'>최근 급수 {fmt_time(watering.get('created_at'))}</div></div>",
        unsafe_allow_html=True,
    )
    col4.markdown(
        f"<div class='metric-box'><div class='eyebrow'>누적 기록</div><h3>AI {counts.get('analysis_count', 0)} / 센서 {counts.get('sensor_count', 0)}</h3><div class='subtle'>급수 {counts.get('watering_count', 0)}건</div></div>",
        unsafe_allow_html=True,
    )


def render_overview_tab(dashboard: dict[str, Any]) -> None:
    left, right = st.columns([0.95, 1.05])
    latest_analysis = dashboard.get("latest_analysis") or {}
    latest_image = dashboard.get("latest_uploaded_image") or {}

    with left:
        st.markdown("<div class='section-box'>", unsafe_allow_html=True)
        st.subheader("식물 기본 정보")
        st.write(f"- 이름: {dashboard['plant']['name']}")
        st.write(f"- 종류: {dashboard['plant'].get('species') or '-'}")
        st.write(f"- 위치: {dashboard['plant'].get('location') or '-'}")
        st.write(f"- 등록 시각: {fmt_time(dashboard['plant']['created_at'])}")
        if latest_image and latest_image.get("file_path"):
            st.image(latest_image["file_path"], caption="최근 업로드한 식물 사진", use_container_width=True)
        else:
            st.info("아직 업로드한 식물 사진이 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='section-box'>", unsafe_allow_html=True)
        st.subheader("최신 AI 사진 분석")
        if latest_analysis:
            meta = STATUS_META.get(latest_analysis.get("health_status"), STATUS_META[None])
            st.markdown(
                f"<span class='status-pill' style='background:{meta['color']}22; color:{meta['color']};'>{meta['label']}</span>",
                unsafe_allow_html=True,
            )
            st.write(latest_analysis.get("condition_summary"))
            st.markdown("**AI 조언**")
            st.write(latest_analysis.get("advice"))
            st.markdown("**관찰 이슈**")
            for issue in latest_analysis.get("observed_issues", []):
                st.markdown(f"<div class='issue-item'>{issue}</div>", unsafe_allow_html=True)
            st.write(f"신뢰도: {round(float(latest_analysis.get('confidence', 0)) * 100)}%")
            st.write(f"업데이트 시각: {fmt_time(latest_analysis.get('created_at'))}")
            st.write(f"확인 시각: {fmt_time(latest_analysis.get('confirmed_at'))}")
            if st.button("최신 AI 분석 확인 완료", use_container_width=True):
                api_request("POST", f"/api/analyses/{latest_analysis['id']}/confirm")
                st.rerun()
        else:
            st.info("사진을 업로드하면 GPT 또는 Gemini 분석 결과가 여기에 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    action_col1, action_col2, action_col3 = st.columns(3)
    with action_col1:
        render_photo_upload_form(dashboard["plant"]["id"])
    with action_col2:
        render_sensor_form(dashboard["plant"]["id"])
    with action_col3:
        render_watering_form(dashboard["plant"]["id"])


def render_photo_upload_form(plant_id: int) -> None:
    st.markdown("<div class='section-box'>", unsafe_allow_html=True)
    st.subheader("식물 사진 업로드 분석")
    with st.form("photo_upload_form"):
        uploaded = st.file_uploader("식물 사진", type=["jpg", "jpeg", "png", "webp"])
        note = st.text_area("추가 메모", placeholder="예: 잎 끝이 노랗게 보임")
        submitted = st.form_submit_button("외부 AI 분석 요청", use_container_width=True)
        if submitted:
            if uploaded is None:
                st.error("분석할 식물 사진을 업로드해 주세요.")
            else:
                with st.spinner("사진을 외부 AI에 보내 분석하고 있습니다..."):
                    api_request(
                        "POST",
                        f"/api/plants/{plant_id}/analyze-photo",
                        files={
                            "image": (uploaded.name, uploaded.getvalue(), uploaded.type or "image/jpeg"),
                        },
                        data={"note": note},
                    )
                st.success("AI 사진 분석 결과를 저장했습니다.")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_sensor_form(plant_id: int) -> None:
    st.markdown("<div class='section-box'>", unsafe_allow_html=True)
    st.subheader("센서 입력 / 데모 생성")
    with st.form("sensor_form"):
        moisture = st.number_input("토양 수분(%)", min_value=0.0, max_value=100.0, value=45.0, step=0.1)
        humidity = st.number_input("습도(%)", min_value=0.0, max_value=100.0, value=55.0, step=0.1)
        temperature = st.number_input("온도(°C)", min_value=-20.0, max_value=60.0, value=23.0, step=0.1)
        light_level = st.number_input("광량(lux)", min_value=0.0, max_value=30000.0, value=6500.0, step=10.0)
        submitted = st.form_submit_button("센서값 저장", use_container_width=True)
        if submitted:
            api_request(
                "POST",
                f"/api/plants/{plant_id}/sensor-logs",
                json={
                    "moisture_value": moisture,
                    "humidity": humidity,
                    "temperature": temperature,
                    "light_level": light_level,
                    "source": "streamlit-manual",
                },
            )
            st.success("센서값을 저장했습니다.")
            st.rerun()

    if st.button("데모 센서값 자동 생성", use_container_width=True):
        api_request("POST", f"/api/plants/{plant_id}/demo-sensor")
        st.success("데모 센서값을 추가했습니다.")
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_watering_form(plant_id: int) -> None:
    st.markdown("<div class='section-box'>", unsafe_allow_html=True)
    st.subheader("급수 기록")
    with st.form("watering_form"):
        mode = st.selectbox("급수 방식", ["manual", "auto"], format_func=lambda x: "수동" if x == "manual" else "자동")
        amount_ml = st.number_input("급수량(ml)", min_value=0.0, max_value=10000.0, value=200.0, step=10.0)
        duration_seconds = st.number_input("지속 시간(초)", min_value=0, max_value=86400, value=20, step=1)
        note = st.text_input("메모", placeholder="예: 오전 실험 후 수동 급수")
        submitted = st.form_submit_button("급수 기록 저장", use_container_width=True)
        if submitted:
            api_request(
                "POST",
                f"/api/plants/{plant_id}/watering-logs",
                json={
                    "mode": mode,
                    "amount_ml": amount_ml,
                    "duration_seconds": duration_seconds,
                    "note": note or None,
                },
            )
            st.success("급수 기록을 저장했습니다.")
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_history_tab(dashboard: dict[str, Any]) -> None:
    st.subheader("센서 / AI / 급수 이력")
    sensor_logs = list(reversed(dashboard.get("recent_sensor_logs", [])))
    if sensor_logs:
        sensor_df = pd.DataFrame(sensor_logs)
        sensor_df["received_at"] = pd.to_datetime(sensor_df["received_at"])
        sensor_df = sensor_df.set_index("received_at")
        st.line_chart(sensor_df[["moisture_value", "humidity", "temperature"]], use_container_width=True)
        st.dataframe(
            sensor_df.reset_index()[["received_at", "moisture_value", "humidity", "temperature", "light_level", "source"]],
            use_container_width=True,
        )
    else:
        st.info("아직 센서 이력이 없습니다.")

    analysis_df = pd.DataFrame(dashboard.get("recent_analyses", []))
    if not analysis_df.empty:
        st.markdown("**AI 분석 기록**")
        st.dataframe(
            analysis_df[["created_at", "provider", "model_name", "health_status", "watering_need", "confidence", "confirmed_at"]],
            use_container_width=True,
        )

    watering_df = pd.DataFrame(dashboard.get("recent_watering_logs", []))
    if not watering_df.empty:
        st.markdown("**급수 기록**")
        st.dataframe(
            watering_df[["created_at", "mode", "amount_ml", "duration_seconds", "note"]],
            use_container_width=True,
        )


def render_system_tab(dashboard: dict[str, Any]) -> None:
    st.subheader("전체 현황과 시스템 로그")
    overview_df = pd.DataFrame(dashboard.get("plant_overview", []))
    if not overview_df.empty:
        st.dataframe(
            overview_df[["name", "species", "location", "is_active", "latest_health_status", "ai_updated_at", "created_at"]],
            use_container_width=True,
        )

    st.markdown("**최근 활동 로그**")
    for item in dashboard.get("recent_activity", []):
        st.write(f"- {fmt_time(item.get('created_at'))} | {item.get('message')}")

    if dashboard.get("recent_errors"):
        st.markdown("**최근 오류 로그**")
        for item in dashboard.get("recent_errors", []):
            st.error(f"{fmt_time(item.get('created_at'))} | {item.get('message')}")


def main() -> None:
    st.set_page_config(page_title="Plant Pulse Vision Dashboard", layout="wide")
    apply_page_style()
    runtime = get_runtime()

    st.session_state.setdefault("show_register", False)
    selected_plant = render_sidebar(runtime)

    st.title("Plant Pulse Vision Dashboard")
    st.caption("사진 분석은 외부 AI HTTP API로 보내고, 결과는 SQLite에 저장한 뒤 대시보드에 다시 표시합니다.")

    try:
        health = api_request("GET", "/api/health")
        st.success(
            f"API 연결됨 | AI 제공자: {health['ai_provider']} | 센서 루프: {'ON' if health['sensor_loop_enabled'] else 'OFF'}"
        )
    except Exception as error:
        st.error(f"FastAPI 서버 연결 실패: {error}")
        st.info("먼저 `python start_project.py` 또는 FastAPI 서버를 실행해 주세요.")
        return

    if selected_plant is None or st.session_state.show_register:
        render_start_screen()
        render_registration_form()
        return

    dashboard = runtime.repository.build_dashboard(selected_plant["id"])
    if dashboard is None:
        st.error("선택한 식물의 대시보드를 불러오지 못했습니다.")
        return

    render_status_banner(dashboard)
    render_metrics(dashboard)
    tab1, tab2, tab3 = st.tabs(["현재 상태", "상세 이력", "전체 현황"])
    with tab1:
        render_overview_tab(dashboard)
    with tab2:
        render_history_tab(dashboard)
    with tab3:
        render_system_tab(dashboard)


if __name__ == "__main__":
    main()
