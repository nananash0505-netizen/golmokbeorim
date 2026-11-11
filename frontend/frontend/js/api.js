// =============================================================
// 골목버림 프론트엔드 - 데이터 연결 파일
// 지금은 USE_MOCK = true 라서 아래 가짜 데이터를 씁니다.
// 팀원 2의 백엔드가 완성되면 false 로 바꾸기만 하면
// 같은 함수가 진짜 API(FastAPI)를 호출합니다.
// =============================================================

const USE_MOCK = false;
const API_BASE = "http://127.0.0.1:8000";

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
async function request(path, options) {
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) throw new Error("API 오류: " + res.status);
  return res.json();
}

async function getStations() {
  if (USE_MOCK) return MOCK.stations;

  const stations = await request("/stations");

  return stations.map(station => {
    const mockStation = MOCK.stations.find(
      s => s.id === station.id
    );

    return {
      ...station,
      bins: station.bins ?? mockStation?.bins ?? []
    };
  });
}

async function getTodaySchedule() {
  if (USE_MOCK) return MOCK.scheduleToday;

  const data = await request("/schedule/today");

  if (Array.isArray(data)) {
    return {
      date: new Date().toLocaleDateString("en-CA"),
      items: data,
      notice: MOCK.scheduleToday.notice
    };
  }

  return data;
}

async function getReadings(binId) {
  if (USE_MOCK) return makeFakeReadings(binId);
  return request(`/bins/${binId}/readings`);
}

async function getPrediction(binId) {
  if (USE_MOCK) {
    const bin = MOCK.stations.flatMap(s => s.bins).find(b => b.id === binId);
    return { bin_id: binId, full_at: bin ? bin.full_at : null };
  }
  return request(`/bins/${binId}/predict`);
}

async function getCluster(id) {
  if (USE_MOCK) return MOCK.cluster;
  return request(`/clusters/${id}`);
}

async function joinCluster(id, data) {
  if (USE_MOCK) {
    MOCK.cluster.current += Number(data.households || 0);
    MOCK.cluster.buildings.push({ name: data.building, households: Number(data.households) });
    return MOCK.cluster;
  }
  return request(`/clusters/${id}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
   body: JSON.stringify({
  name: data.building,
  households: Number(data.households)
})
  });
}

async function classifyImage(file) {
  if (USE_MOCK) {
    await new Promise(r => setTimeout(r, 800)); // 분석하는 척 잠깐 기다림
    return MOCK.classifyResult;
  }
  const form = new FormData();
  form.append("image", file);
  return request("/classify", { method: "POST", body: form });
}

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
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:00`;
}