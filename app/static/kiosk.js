const views = ["start", "register", "loading", "main"];

const state = {
  payload: null,
  questionOpen: false,
};

const demoSpecies = [
  { species: "몬스테라 델리시오사", confidence: 84 },
  { species: "스킨답서스", confidence: 81 },
  { species: "필로덴드론", confidence: 79 },
  { species: "산세베리아", confidence: 86 },
];

function $(id) {
  return document.getElementById(id);
}

function showView(name) {
  views.forEach((viewName) => {
    $(`${viewName}-view`).classList.toggle("is-active", viewName === name);
  });
}

function setText(id, value) {
  const node = $(id);
  if (node) {
    node.textContent = value ?? "-";
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function apiRequest(path, options = {}) {
  const headers = options.headers ? { ...options.headers } : {};
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_error) {
      // Keep the HTTP status text when the body is not JSON.
    }
    throw new Error(message);
  }

  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : {};
}

async function loadKioskState() {
  const payload = await apiRequest("/api/kiosk/state");
  state.payload = payload;
  return payload;
}

function formatNumber(value, suffix = "", digits = 1) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return "--";
  }
  const formatted = new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: digits,
  }).format(number);
  return `${formatted}${suffix}`;
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusTitle(status) {
  if (status === "critical") return "위험 알림";
  if (status === "warning") return "주의 알림";
  if (status === "healthy") return "상태 안정";
  return "분석 대기";
}

function pickDemoSpecies() {
  const name = $("plant-name-input").value.trim();
  const seed = Array.from(name || "plant-pulse").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return demoSpecies[seed % demoSpecies.length];
}

function showLoading(title, message) {
  setText("loading-title", title);
  setText("loading-message", message);
  showView("loading");
}

async function startKiosk() {
  showLoading("센서 동기화 중", "현재 등록된 식물과 최신 센서값을 불러오는 중입니다.");
  try {
    const payload = await loadKioskState();
    await sleep(450);
    if (payload.dashboard) {
      renderMain(payload);
      showView("main");
    } else {
      showView("register");
    }
  } catch (error) {
    setText("start-api-state", "연결 실패");
    setText("start-summary", `서버 상태를 확인해 주세요. ${error.message}`);
    showView("start");
  }
}

async function identifySpeciesDemo() {
  const nameInput = $("plant-name-input");
  if (!nameInput.value.trim()) {
    nameInput.focus();
    $("identify-result").textContent = "먼저 식물 이름을 입력해 주세요.";
    return;
  }

  showLoading("AI 종 판별 중", "카메라 촬영 흐름을 데모 결과로 연결하고 있습니다.");
  await sleep(900);
  const result = pickDemoSpecies();
  $("plant-species-input").value = result.species;
  $("identify-result").textContent = `데모 판별: ${result.species} · 확신도 ${result.confidence}%`;
  showView("register");
}

async function registerPlant(event) {
  event.preventDefault();
  const name = $("plant-name-input").value.trim();
  const species = $("plant-species-input").value.trim();
  if (!name) {
    $("plant-name-input").focus();
    return;
  }

  showLoading("식물 등록 중", "초기 센서 상태판을 준비하고 있습니다.");
  try {
    await apiRequest("/api/plants", {
      method: "POST",
      body: JSON.stringify({
        name,
        species: species || null,
        location: "Kiosk",
      }),
    });
    await sleep(500);
    const payload = await loadKioskState();
    renderMain(payload);
    showView("main");
  } catch (error) {
    $("identify-result").textContent = `등록 실패: ${error.message}`;
    showView("register");
  }
}

function renderMain(payload) {
  const dashboard = payload.dashboard;
  const kiosk = payload.kiosk || {};
  if (!dashboard) {
    showView("register");
    return;
  }

  const plant = dashboard.plant || {};
  const sensor = dashboard.latest_sensor_state || {};
  const analysis = dashboard.latest_analysis || {};
  const latestState = dashboard.latest_state || {};
  const wateringLogs = dashboard.recent_watering_logs || [];
  const species = plant.species || "종 정보 미입력";

  setText("plant-title", plant.name || "등록된 식물");
  setText("plant-subtitle", `${species} · 최근 센서 ${formatTime(sensor.received_at || sensor.updated_at)}`);
  setText("health-label", kiosk.health_label || statusTitle(kiosk.health_status));
  setText("health-score", kiosk.health_score ?? "--");
  setText(
    "confidence-line",
    kiosk.confidence_percent === null || kiosk.confidence_percent === undefined
      ? "신뢰도 대기 중"
      : `AI 신뢰도 ${kiosk.confidence_percent}%`
  );

  const statusBadge = $("health-label");
  statusBadge.className = "status-badge";
  if (kiosk.health_status === "warning") statusBadge.classList.add("warning");
  if (kiosk.health_status === "critical") statusBadge.classList.add("critical");

  $("score-fill").style.width = `${Math.max(0, Math.min(100, Number(kiosk.health_score) || 0))}%`;
  setText("sensor-moisture", formatNumber(sensor.moisture_value, "%"));
  setText("sensor-temperature", formatNumber(sensor.temperature, "°C"));
  setText("sensor-humidity", formatNumber(sensor.humidity, "%"));
  setText("sensor-light", formatNumber(sensor.light_level, " lux", 0));

  const analysisTime = analysis.created_at ? `분석 ${formatTime(analysis.created_at)}` : "분석 대기";
  setText("analysis-time", analysisTime);
  setText(
    "diagnosis-summary",
    analysis.condition_summary || latestState.latest_condition_summary || "아직 사진 분석 결과가 없습니다."
  );
  setText("advice-text", analysis.advice || latestState.latest_advice || "사진 분석이 완료되면 추천 조치가 표시됩니다.");

  renderAlert(kiosk, analysis);
  renderWateringList(wateringLogs);
}

function renderAlert(kiosk, analysis) {
  const panel = $("alert-panel");
  const button = $("confirm-action-button");
  const hasAlert = kiosk.alert_level === "warning" || kiosk.alert_level === "critical";
  panel.classList.toggle("hidden", !hasAlert);

  if (!hasAlert) {
    return;
  }

  setText("alert-title", statusTitle(kiosk.alert_level));
  setText("alert-message", kiosk.alert_message || "AI 진단 확인이 필요한 상태입니다.");
  button.disabled = !kiosk.can_confirm_action;
  button.textContent = kiosk.can_confirm_action ? "조치 완료" : analysis.confirmed_at ? "확인 완료됨" : "확인 대기";
}

function renderWateringList(logs) {
  const list = $("watering-list");
  list.textContent = "";

  if (!logs.length) {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = "급수 기록 없음";
    const meta = document.createElement("span");
    meta.textContent = "수동 또는 자동 급수 후 표시됩니다.";
    item.append(label, meta);
    list.appendChild(item);
    return;
  }

  logs.slice(0, 4).forEach((log) => {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    const amount = log.amount_ml ? `${formatNumber(log.amount_ml, " ml", 0)}` : "용량 미기록";
    label.textContent = `${log.mode === "auto" ? "자동" : "수동"} · ${amount}`;
    const meta = document.createElement("span");
    meta.textContent = formatTime(log.created_at || log.started_at);
    item.append(label, meta);
    list.appendChild(item);
  });
}

async function refreshAndRender() {
  showLoading("상태 갱신 중", "최신 센서와 AI 진단을 다시 불러오는 중입니다.");
  const payload = await loadKioskState();
  renderMain(payload);
  showView("main");
}

async function syncDemoSensor() {
  const dashboard = state.payload?.dashboard;
  const plantId = dashboard?.plant?.id;
  if (!plantId) {
    showView("register");
    return;
  }

  showLoading("센서 동기화 중", "하드웨어가 없는 환경에서는 데모 센서값을 생성합니다.");
  try {
    await apiRequest(`/api/plants/${plantId}/demo-sensor`, { method: "POST" });
    await sleep(400);
    await refreshAndRender();
  } catch (error) {
    setText("loading-title", "동기화 실패");
    setText("loading-message", error.message);
    await sleep(900);
    showView("main");
  }
}

async function confirmAction() {
  const analysisId = state.payload?.kiosk?.latest_analysis_id;
  if (!analysisId) {
    return;
  }

  showLoading("조치 확인 저장 중", "AI 경고에 대한 확인 시각을 기록합니다.");
  try {
    await apiRequest(`/api/analyses/${analysisId}/confirm`, { method: "POST" });
    await sleep(350);
    await refreshAndRender();
  } catch (error) {
    setText("loading-title", "저장 실패");
    setText("loading-message", error.message);
    await sleep(900);
    showView("main");
  }
}

function openQuestionModal() {
  $("question-modal").classList.remove("hidden");
  $("question-input").focus();
}

function closeQuestionModal() {
  $("question-modal").classList.add("hidden");
  $("question-input").value = "";
  $("answer-box").textContent = "질문을 입력하면 데모 답변을 보여드립니다.";
}

async function requestPlantQuestionAnswer(question) {
  await sleep(350);
  const sensor = state.payload?.dashboard?.latest_sensor_state || {};
  const moisture = sensor.moisture_value;
  const moistureLine =
    moisture === null || moisture === undefined
      ? "현재 센서값이 없어 최근 사진 분석 결과를 기준으로 판단해야 합니다."
      : `현재 토양 수분은 ${formatNumber(moisture, "%")}입니다.`;
  return `${moistureLine} 질문 답변 API는 준비 중이며, 지금은 데모 안내만 표시합니다.`;
}

async function submitQuestion() {
  const question = $("question-input").value.trim();
  if (!question) {
    $("question-input").focus();
    return;
  }

  $("answer-box").textContent = "답변 준비 중...";
  const answer = await requestPlantQuestionAnswer(question);
  $("answer-box").textContent = answer;
}

async function updateStartState() {
  try {
    const payload = await loadKioskState();
    setText("start-api-state", payload.dashboard ? "식물 등록됨" : "등록 필요");
    setText(
      "start-summary",
      payload.dashboard
        ? `${payload.dashboard.plant.name} 상태판을 바로 열 수 있습니다.`
        : "터치해서 첫 식물을 등록합니다."
    );
  } catch (_error) {
    setText("start-api-state", "서버 확인 필요");
  }
}

function wireEvents() {
  $("start-button").addEventListener("click", startKiosk);
  $("register-back-button").addEventListener("click", () => showView("start"));
  $("plant-form").addEventListener("submit", registerPlant);
  $("mock-identify-button").addEventListener("click", identifySpeciesDemo);
  $("new-plant-button").addEventListener("click", () => showView("register"));
  $("sync-button").addEventListener("click", syncDemoSensor);
  $("confirm-action-button").addEventListener("click", confirmAction);
  $("question-button").addEventListener("click", openQuestionModal);
  $("close-question-button").addEventListener("click", closeQuestionModal);
  $("ask-question-button").addEventListener("click", submitQuestion);
  $("question-modal").addEventListener("click", (event) => {
    if (event.target.id === "question-modal") {
      closeQuestionModal();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireEvents();
  updateStartState();
});
