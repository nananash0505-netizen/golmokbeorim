// =============================================================
// 모든 화면 공통: 상단 메뉴, 하위 탭, 남색 안내 띠(당번 + 7시 알림),
// 마무리 문구, 아래쪽 정보, 알림 토스트
//
// 각 HTML에서 쓰는 값
//   <body data-tab="home|scan|fill|alley" data-closing="1">
//   window.SUBTABS = [{ key: "map", label: "골목 지도", feature: "guardian"(선택) }]
//   하위 탭에 속한 구역에는 data-sub="map" 을 붙입니다.
// =============================================================

const MENU = [
  { key: "home", name: "홈", href: "index.html" },
  { key: "scan", name: "사진 분리배출", href: "scan.html" },
  { key: "fill", name: "적재량", href: "dashboard.html" },
  { key: "alley", name: "골목단지", href: "join.html" }
];

function showToast(title, body) {
  let t = document.getElementById("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    t.setAttribute("role", "status");
    document.body.appendChild(t);
  }
  t.innerHTML = `<div class="t-title"><img src="img/logo.png" alt="">${title}</div><div class="t-body">${body}</div>`;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 5000);
}

function sendEveningAlert(message) {
  showToast("골목버림 · 저녁 7시 알림", message);
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("골목버림", { body: message, icon: "img/logo.png" });
    }
  } catch (e) {}
}

async function previewEveningAlert() {
  try {
    if ("Notification" in window && Notification.permission === "default") {
      await Notification.requestPermission();
    }
  } catch (e) {}
  sendEveningAlert(await buildEveningMessage());
}

// 페이지를 켜 둔 상태로 저녁 7시가 되면 알림을 띄웁니다.
function scheduleEveningAlert(message) {
  const now = new Date();
  const seven = new Date(now);
  seven.setHours(19, 0, 0, 0);
  if (seven - now > 0) setTimeout(() => sendEveningAlert(message), seven - now);
}

// ---------- 하위 탭 ----------
function visibleSubtabs() {
  const f = getFeatures();
  return (window.SUBTABS || []).filter(s => !s.feature || f[s.feature]);
}

function showSub(key) {
  const tabs = visibleSubtabs();
  if (!tabs.length) return;
  if (!tabs.some(t => t.key === key)) key = tabs[0].key;
  document.querySelectorAll("[data-sub]").forEach(el => { el.hidden = el.dataset.sub !== key; });
  document.querySelectorAll(".subtabs a").forEach(a => {
    const on = a.dataset.key === key;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  document.dispatchEvent(new CustomEvent("subtabchange", { detail: key }));
}

// ---------- 마무리 문구 (집 앞 배출로 돌아가려는 마음을 붙잡는 문구) ----------
function closingHTML() {
  return `
    <section class="closing">
      <div class="eyebrow-en">Together, we make a zero-waste alley</div>
      <h2>모두가 함께하면,<br><b>쓰레기 없는 골목</b>을 만들 수 있습니다</h2>
      <p>오늘 하루쯤 집 앞에 두고 싶은 날도 있어요. 그럴 땐 모음터까지 딱 한 번만 더 걸어 주세요.
         한 집이 지키면, 골목 전체가 깨끗해집니다.</p>
      <p class="small">집 앞 배출이 다시 늘면 골목버림이 먼저 알려드릴게요</p>
    </section>`;
}

async function renderShell() {
  const active = document.body.dataset.tab;
  const features = getFeatures();
  const msg = await buildEveningMessage();
  scheduleEveningAlert(msg);

  if (active !== "home") {
    const head = document.createElement("div");
    const menu = MENU.map(m =>
      `<a href="${m.href}" class="${m.key === active ? "active" : ""}"${m.key === active ? ' aria-current="page"' : ""}>${m.name}</a>`
    ).join("");
    const subs = visibleSubtabs().map(s => `<a href="#${s.key}" data-key="${s.key}">${s.label}</a>`).join("");

    let info = "";
    if (features.guardian || features.eveningAlert) {
      const d = getMyDutyInfo();
      info = `
        <div class="infobar">
          ${features.guardian ? `<span>내 지킴이 당번까지 <strong>${d.left}번</strong> 남았어요 (${d.week})</span>` : ""}
          ${features.eveningAlert ? `<span><span class="hl">${new Date().getHours() >= 19 ? "저녁 7시 알림" : "오늘 저녁 7시 알림"}</span> ${msg}</span>` : ""}
          ${features.eveningAlert ? '<a href="#" id="previewAlert">알림 미리보기</a>' : ""}
        </div>`;
    }

    head.innerHTML = `
      <header class="topbar">
        <a class="logo" href="index.html"><img src="img/logo.png" alt=""><span>골목버림</span></a>
        <nav class="mainmenu" aria-label="주요 메뉴">${menu}</nav>
      </header>
      ${subs ? `<nav class="subtabs" aria-label="하위 메뉴">${subs}</nav>` : ""}
      ${info}`;
    document.body.prepend(head);

    const p = document.getElementById("previewAlert");
    if (p) p.onclick = e => { e.preventDefault(); previewEveningAlert(); };

    document.querySelectorAll(".subtabs a").forEach(a => a.onclick = e => {
      e.preventDefault();
      history.replaceState(null, "", "#" + a.dataset.key);
      showSub(a.dataset.key);
    });
    showSub(location.hash.slice(1));
  }

  if (document.body.dataset.closing === "1") {
    document.body.insertAdjacentHTML("beforeend", closingHTML());
  }
  document.body.insertAdjacentHTML("beforeend", `
    <footer><b>골목버림</b> · 관리사무소 없는 빌라촌을 위한 AI 쓰레기 도우미 · AI+라이프스타일 해커톤 · 화면의 수치는 예시 데이터입니다</footer>`);
}

renderShell();
