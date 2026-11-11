// =============================================================
// 골목버림 프론트엔드 - 데이터 연결 파일
// 지금은 USE_MOCK = true 라서 아래 가짜 데이터를 씁니다.
// 팀원 2의 백엔드가 완성되면 false 로 바꾸기만 하면
// 같은 함수가 진짜 API(FastAPI)를 호출합니다.
// =============================================================

const USE_MOCK = false;  // 서버를 켜지 않고 화면만 볼 때는 true로 바꾸세요
const API_BASE = "http://localhost:8000";

// ---------- 시연 동네 기준점 ----------
// 오래3길 한가운데 좌표로 이 두 숫자만 바꾸면
// 모음터 3곳이 모두 그 주변으로 함께 옮겨집니다.
// (좌표 찾는 법: map.html에서 원하는 곳을 클릭하면 좌표가 나옵니다)
const DEMO_AREA = {
  name: "화성시 봉담읍 오래3길",
  lat: 37.2201,   // 위도 
  lng: 126.9546   // 경도 
};

// 기준점에서 조금씩 떨어진 위치 (약 100~150m)
const OFFSET = (dLat, dLng) => ({ lat: DEMO_AREA.lat + dLat, lng: DEMO_AREA.lng + dLng });

// ---------- 가짜 데이터 (API 명세와 같은 모양) ----------
const MOCK = {
  stations: [
    { id: 1, name: "모음터 A (오래3길 끝 주차장)", lat: 37.22044, lng: 126.95515,
      bins: [
        { id: 11, type: "음식물", fill: 82, full_at: "2026-11-12T08:00" },
        { id: 12, type: "재활용", fill: 45, full_at: "2026-11-13T20:00" },
        { id: 13, type: "일반", fill: 30, full_at: "2026-11-14T10:00" }
      ] },
    { id: 2, name: "모음터 B (골목 모퉁이 빈터)", lat: 37.22016, lng: 126.95456,
      bins: [
        { id: 21, type: "음식물", fill: 38, full_at: "2026-11-13T07:00" },
        { id: 22, type: "재활용", fill: 91, full_at: "2026-11-11T22:00" },
        { id: 23, type: "일반", fill: 55, full_at: "2026-11-13T15:00" }
      ] },
    { id: 3, name: "모음터 C (오래3길 입구 공터)", lat: 37.22075, lng: 126.95377,
      bins: [
        { id: 31, type: "음식물", fill: 15, full_at: "2026-11-14T09:00" },
        { id: 32, type: "재활용", fill: 20, full_at: "2026-11-15T12:00" },
        { id: 33, type: "일반", fill: 64, full_at: "2026-11-12T19:00" }
      ] }
  ],

  scheduleToday: {
    date: "2026-11-11",
    items: [
      { type: "음식물", ok: true, time: "20:00 이후" },
      { type: "재활용", ok: true, time: "20:00 이후" },
      { type: "일반", ok: false, time: "내일(목) 20:00 이후" }
    ],
    notice: "다음 주 수요일은 공휴일이라 수거가 없습니다. 음식물은 냉동 보관해 주세요."
  },

  cluster: { id: 1, name: "오래3길 골목 단지", target: 60, current: 47,
    buildings: [
      { name: "행복빌", households: 12 },
      { name: "금성주택", households: 16 },
      { name: "J.B 타운", households: 9 },
      { name: "신영빌라트", households: 10 }
    ] },

  classifyResult: {
    item: "배달 플라스틱 용기",
    category: "플라스틱",
    steps: ["남은 음식물은 음식물쓰레기로", "용기는 물로 헹구기", "뚜껑 비닐 필름은 떼서 일반쓰레기로"],
    confidence: 0.91
  }
};

// 적재율 기록(최근 24시간)을 그럴듯하게 만들어 주는 함수
function makeFakeReadings(binId) {
  const station = MOCK.stations.flatMap(s => s.bins).find(b => b.id === binId);
  const end = station ? station.fill : 50;
  const result = [];
  const now = new Date("2026-11-11T12:00");
  for (let i = 23; i >= 0; i--) {
    const t = new Date(now.getTime() - i * 3600 * 1000);
    const fill = Math.max(0, Math.round(end - i * (end / 30) + (Math.random() * 4 - 2)));
    result.push({ time: t.toISOString().slice(0, 16), fill });
  }
  return result;
}

// ---------- 화면에서 쓰는 함수들 ----------
// 서버에 연결되지 않으면 자동으로 예시 데이터로 바꿔서 화면이 깨지지 않게 합니다.
let useMock = USE_MOCK;

function showOfflineNotice() {
  const put = () => {
    if (document.getElementById("offlineNotice")) return;
    const d = document.createElement("div");
    d.id = "offlineNotice";
    d.setAttribute("role", "status");
    d.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:3000;max-width:340px;background:#fde6e6;color:#8a2a2a;" +
      "border-radius:12px;padding:12px 16px;font-size:14px;line-height:1.5;box-shadow:0 6px 18px rgba(0,0,0,.15)";
    d.innerHTML = "<b>서버에 연결되지 않았어요</b><br>지금은 예시 데이터로 보여드려요. backend 폴더에서 서버를 켠 뒤 새로고침해 주세요.";
    document.body.appendChild(d);
  };
  if (document.body) put(); else document.addEventListener("DOMContentLoaded", put);
}

async function request(path, options) {
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch (e) {}
    const err = new Error(detail || "API 오류: " + res.status);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// 서버 먼저 시도 → 연결 자체가 안 되면 예시 데이터
async function fromServer(serverCall, mockCall) {
  if (useMock) return mockCall();
  try {
    return await serverCall();
  } catch (e) {
    if (e.status) throw e;          // 서버는 켜져 있는데 오류를 돌려준 경우는 그대로 알림
    useMock = true;                 // 연결 실패 → 이후 요청은 모두 예시 데이터
    showOfflineNotice();
    return mockCall();
  }
}

async function getStations() {
  return fromServer(() => request("/stations"), () => MOCK.stations);
}

async function getTodaySchedule() {
  return fromServer(() => request("/schedule/today"), () => MOCK.scheduleToday);
}

async function getReadings(binId) {
  return fromServer(() => request(`/bins/${binId}/readings`), () => makeFakeReadings(binId));
}

async function getPrediction(binId) {
  return fromServer(() => request(`/bins/${binId}/predict`), () => {
    const bin = MOCK.stations.flatMap(s => s.bins).find(b => b.id === binId);
    return { bin_id: binId, full_at: bin ? bin.full_at : null };
  });
}

async function getCluster(id) {
  return fromServer(() => request(`/clusters/${id}`), () => MOCK.cluster);
}

async function joinCluster(id, data) {
  return fromServer(
    () => request(`/clusters/${id}/join`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    }),
    () => {
      MOCK.cluster.current += Number(data.households || 0);
      MOCK.cluster.buildings.push({ name: data.building, households: Number(data.households) });
      return MOCK.cluster;
    });
}

// 사진 분류는 가짜 답을 보여주면 헷갈리므로, 서버 연결이 안 되면 이유를 알려 줍니다.
async function classifyImage(file) {
  if (USE_MOCK) {  // 직접 예시 모드를 켠 경우에만 예시 답변
    await new Promise(r => setTimeout(r, 800));
    return { ...MOCK.classifyResult, item: MOCK.classifyResult.item + " (예시 답변)" };
  }
  const form = new FormData();
  form.append("image", file);
  try {
    return await request("/classify", { method: "POST", body: form });
  } catch (e) {
    if (!e.status) {
      showOfflineNotice();
      throw new Error("서버에 연결되지 않았어요. 터미널에서 서버를 켠 뒤 다시 눌러 주세요.");
    }
    throw e;  // 예: API 키가 없을 때 서버가 보낸 안내 문구
  }
}

// 장비 고장 감지 (서버: GET /bins/{id}/fault)
async function getFault(binId) {
  return fromServer(() => request(`/bins/${binId}/fault`), () => detectFault(binId));
}

// ---------- 무단투기: 사진 판단 → 신고 ----------
// 사진 판단은 AI가 꼭 필요하므로 예시 답 대신 이유를 알려 줍니다.
async function analyzeDumpingPhoto(file, stationId) {
  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 900));
    return MOCK_DUMPING_RESULT;
  }
  const form = new FormData();
  form.append("image", file);
  if (stationId) form.append("station_id", stationId);
  try {
    return await request("/dumping/analyze", { method: "POST", body: form });
  } catch (e) {
    if (!e.status) {
      showOfflineNotice();
      throw new Error("서버에 연결되지 않았어요. 터미널에서 서버를 켠 뒤 다시 눌러 주세요.");
    }
    throw e;
  }
}

async function sendDumpingReport(data) {
  return fromServer(
    () => request("/dumping/report", {
      method: "POST", headers: { "Content-Type": "application/json", ...authHeader() }, body: JSON.stringify(data)
    }),
    () => ({ id: Date.now(), created_at: new Date().toISOString().slice(0, 16), status: "접수", ...data })
  );
}

async function getDumpingReports() {
  return fromServer(() => request("/dumping/reports"), () => []);
}

async function markReportDone(id) {
  return fromServer(() => request(`/dumping/reports/${id}/done`, { method: "POST" }), () => ({ id, status: "처리 완료" }));
}

// 서버 없이 화면만 볼 때(USE_MOCK = true) 쓰는 예시 판단 결과
const MOCK_DUMPING_RESULT = {
  ok: true, verdict: "무단투기 의심", severity: "높음",
  summary: "건물 벽 앞 보행로에 분리되지 않은 봉투와 펼친 상자가 쌓여 있어요 (예시 답변)",
  violations: ["종량제 봉투가 아닌 일반 비닐봉투에 담아 버림", "재활용품이 한 봉투에 섞여 있음",
               "상자를 접지 않고 쌓아 둠", "음식물이 묻은 포장재를 그대로 버림", "보행로를 막고 있음"],
  items: [{ name: "페트병 묶음", category: "플라스틱", problem: "라벨을 떼지 않고 다른 쓰레기와 섞임" },
          { name: "택배 상자", category: "종이", problem: "접지 않고 펼친 채 쌓임" }],
  estimated_bags: 12, blocks_path: true,
  report_text: "건물 앞 보행로에 종량제 봉투가 아닌 비닐봉투 10여 개와 상자가 분리되지 않은 채 쌓여 있습니다. 통행을 막고 있어 수거와 정리를 요청드립니다.",
  action: "재활용품은 품목별로 나누고, 상자는 접어서 모음터 재활용칸으로 옮겨 주세요.",
  privacy_note: ""
};

// ---------- AI 골목 브리핑 (서버: GET /briefing) ----------
// 규칙·통계 신호를 AI가 해석한 결과라 가짜 답 대신 연결 문제를 알려 줍니다.
async function getBriefing(refresh) {
  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 900));
    return MOCK_BRIEFING;
  }
  try {
    return await request("/briefing" + (refresh ? "?refresh=true" : ""));
  } catch (e) {
    if (!e.status) {
      showOfflineNotice();
      throw new Error("서버에 연결되지 않았어요. 터미널에서 서버를 켠 뒤 다시 눌러 주세요.");
    }
    throw e;
  }
}

// 서버 없이 화면만 볼 때(USE_MOCK = true) 쓰는 예시 브리핑
const MOCK_BRIEFING = {
  ok: true, risk_level: "높음", generated_at: "2026-11-11T19:00", cached: false,
  signals: { bins: 9, faults: 2, open_reports: 1 },
  headline: "모음터 B 재활용통이 곧 가득 차고, 장비 두 곳에 이상 신호가 있어요 (예시 답변)",
  resident_notice: "오늘은 음식물과 재활용을 버리는 날이에요. 모음터 B 재활용통이 거의 찼으니 재활용은 모음터 A나 C에 버려 주세요.",
  pickup_priority: [
    { place: "모음터 B · 재활용", fill: 91, when: "오늘 오후 3시 전", reason: "이미 91%이고 시간당 3%씩 차고 있어요" },
    { place: "모음터 A · 음식물", fill: 82, when: "오늘 저녁 6시 반 전", reason: "음식물은 악취가 나기 쉬워 먼저 비워야 해요" }
  ],
  equipment: [
    { place: "모음터 B · 음식물", likely_cause: "저울(로드셀) 고장 또는 투입구 막힘", check: "투입구 안쪽 막힘과 저울 표시값 확인",
      request_text: "모음터 B 음식물통 저울이 4시간째 같은 값을 보여요. 점검 부탁드립니다." }
  ],
  guardian_todo: ["모음터 A 옆 바닥 비닐봉투 정리", "모음터 B 음식물통 투입구 막힘 확인"],
  dumping: "모음터 A 옆에 종량제 봉투가 아닌 비닐봉투가 방치돼 있어요."
};

// ---------- 공통 도우미 ----------
function fillColor(fill) {
  if (fill >= 80) return "#b83232";
  if (fill >= 60) return "#b9770e";
  return "#1d7a55";
}

function fillBadge(fill) {
  if (fill >= 80) return '<span class="badge full">곧 가득</span>';
  if (fill >= 60) return '<span class="badge warn">보통</span>';
  return '<span class="badge ok">여유</span>';
}

function formatTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}


// =============================================================
// 회원가입 · 로그인
// 로그인하면 서버가 준 토큰을 이 브라우저에 저장해 두고,
// 신고처럼 로그인이 필요한 요청에 함께 보냅니다.
// =============================================================
const AUTH_KEY = "golmok_auth";

function getAuth() {
  try { return JSON.parse(localStorage.getItem(AUTH_KEY)) || null; } catch (e) { return null; }
}
function getCurrentUser() { const a = getAuth(); return a ? a.user : null; }
function saveAuth(data) { try { localStorage.setItem(AUTH_KEY, JSON.stringify(data)); } catch (e) {} }
function clearAuth() { try { localStorage.removeItem(AUTH_KEY); } catch (e) {} }
function authHeader() { const a = getAuth(); return a ? { Authorization: "Bearer " + a.token } : {}; }

async function authRequest(path, body) {
  try {
    return await request(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
  } catch (e) {
    if (!e.status) throw new Error("서버에 연결되지 않았어요. 터미널에서 서버를 켠 뒤 다시 눌러 주세요.");
    throw e;
  }
}

async function signup(form) {
  const data = await authRequest("/auth/signup", form);
  saveAuth(data);
  return data.user;
}

async function login(username, password) {
  const data = await authRequest("/auth/login", { username, password });
  saveAuth(data);
  return data.user;
}

async function logout() {
  try { await request("/auth/logout", { method: "POST", headers: authHeader() }); } catch (e) {}
  clearAuth();
}

// 저장된 토큰이 아직 유효한지 서버에 확인 (서버가 꺼져 있으면 저장된 정보를 그대로 씀)
async function refreshMe() {
  if (!getAuth()) return null;
  try {
    const user = await request("/auth/me", { headers: authHeader() });
    saveAuth({ ...getAuth(), user });
    return user;
  } catch (e) {
    if (e.status === 401) { clearAuth(); return null; }
    return getCurrentUser();
  }
}

// 로그인 화면 주소 (로그인 후 지금 화면으로 돌아오게)
function loginUrl() {
  const here = location.pathname.split("/").pop() + location.hash;
  return "login.html?next=" + encodeURIComponent(here || "index.html");
}
