"""
골목버림 API 서버 (팀원 2의 DB 서버 + 팀원 1의 AI 기능을 하나로 합친 것)

실행:  python3 -m uvicorn main:app --reload      (backend 폴더 안에서)
확인:  http://localhost:8000/docs

고친 점
 ① POST /classify          사진 분류 (팀원 1 classify_image)
 ② GET  /bins/{id}/fault   장비 고장 감지 (팀원 1 detect_fault)
 ③ 참여 신청은 building / name 둘 다 받음
 ④ 참여 신청 후 바뀐 단지 정보 전체를 돌려줌
 ⑤ 오늘 배출 일정은 요일 규칙(rules.json)으로 계산, 안 되면 DB 값 사용
 ⑥ CORS 전체 허용, 적재 기록은 최근 24개만
 +  DB 파일은 main.py 옆의 garbage.db를 정확히 가리킴
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE = Path(__file__).parent
DB_PATH = BASE / "garbage.db"
load_dotenv(BASE / ".env")  # 어느 폴더에서 실행해도 backend/.env를 읽음

from sensor_sim import detect_fault, predict_full_time  # noqa: E402

# AI 모듈은 API 키가 없으면 불러오다 실패할 수 있어, 서버 전체가 멈추지 않게 따로 처리
try:
    import ai_module
    AI_ERROR = None
except Exception as e:  # 키 없음, 패키지 없음 등
    ai_module = None
    AI_ERROR = str(e)

app = FastAPI(title="골목버림 API")

# ⑥ 해커톤용: Live Server(5500), 파일로 연 화면 등 어디서든 접근 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    if not DB_PATH.exists():
        raise HTTPException(500, "garbage.db가 없어요. backend 폴더에서 python3 database.py를 먼저 실행해 주세요.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


SENSOR_LOGS = {
    int(k): v for k, v in json.loads((BASE / "seed_sensor_logs.json").read_text(encoding="utf-8")).items()
}


# 1. 서버 실행 확인
@app.get("/")
def home():
    return {
        "message": "골목버림 서버 실행 성공!",
        "ai": "사용 가능" if ai_module else f"사용 불가 ({AI_ERROR})",
    }


# 2. 모음터 전체 조회
@app.get("/stations")
def get_stations():
    conn = get_db()
    cur = conn.cursor()
    stations = cur.execute("SELECT * FROM stations ORDER BY id").fetchall()
    result = []
    for s in stations:
        bins = cur.execute("SELECT * FROM bins WHERE station_id = ? ORDER BY id", (s["id"],)).fetchall()
        result.append({
            "id": s["id"], "name": s["name"], "lat": s["lat"], "lng": s["lng"],
            "bins": [{"id": b["id"], "type": b["type"], "fill": b["fill"], "full_at": b["full_at"]} for b in bins],
        })
    conn.close()
    return result


# 3. 특정 모음터 조회
@app.get("/stations/{station_id}")
def get_station(station_id: int):
    for s in get_stations():
        if s["id"] == station_id:
            return s
    raise HTTPException(404, "모음터를 찾을 수 없습니다.")


# 4. 적재율 기록 (⑥ 최근 24개만, 시간 순서대로)
@app.get("/bins/{bin_id}/readings")
def get_readings(bin_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT time, fill FROM (SELECT time, fill FROM readings WHERE bin_id = ? ORDER BY time DESC LIMIT 24) ORDER BY time",
        (bin_id,),
    ).fetchall()
    conn.close()
    if not rows:
        raise HTTPException(404, f"{bin_id}번 통의 기록이 없어요.")
    return [dict(r) for r in rows]


# 5. 가득 차는 시각 (DB 값 우선, 없으면 기록으로 AI 예측)
@app.get("/bins/{bin_id}/predict")
def get_prediction(bin_id: int):
    conn = get_db()
    b = conn.execute("SELECT full_at FROM bins WHERE id = ?", (bin_id,)).fetchone()
    conn.close()
    if b is None:
        raise HTTPException(404, "쓰레기통을 찾을 수 없습니다.")
    if b["full_at"]:
        return {"bin_id": bin_id, "full_at": b["full_at"]}
    predicted = predict_full_time(get_readings(bin_id))
    return {"bin_id": bin_id, "full_at": predicted.get("full_at")}


# ② 장비 고장 감지
@app.get("/bins/{bin_id}/fault")
def get_fault(bin_id: int):
    return detect_fault(SENSOR_LOGS.get(bin_id, []), bin_id)


# ⑤ 오늘의 배출 일정: 요일 규칙(rules.json)으로 계산
@app.get("/schedule/today")
def get_today_schedule():
    if ai_module:
        try:
            return ai_module.today_schedule()
        except Exception:
            pass
    # AI 모듈을 못 쓰면 DB 값으로 대신 보여줌
    now = datetime.now()
    conn = get_db()
    rows = conn.execute("SELECT type, ok, time FROM schedules WHERE day_of_week = ?", (now.weekday(),)).fetchall()
    conn.close()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "items": [{"type": r["type"], "ok": bool(r["ok"]), "time": r["time"]} for r in rows],
        "notice": "" if rows else "오늘 배출 일정 정보가 없어요. 구청 안내를 확인해 주세요.",
    }


# 7. 골목 단지 정보
@app.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: int):
    conn = get_db()
    c = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
    if c is None:
        conn.close()
        raise HTTPException(404, "골목 단지를 찾을 수 없습니다.")
    buildings = conn.execute(
        "SELECT id, name, households FROM buildings WHERE cluster_id = ? ORDER BY id", (cluster_id,)
    ).fetchall()
    conn.close()
    return {
        "id": c["id"], "name": c["name"], "target": c["target"], "current": c["current"],
        "buildings": [dict(b) for b in buildings],
    }


# ③ 화면은 building, 기존 서버는 name → 둘 다 받음
class JoinRequest(BaseModel):
    building: Optional[str] = None
    name: Optional[str] = None
    households: int


# 8. 골목 단지 참여 신청 (④ 바뀐 단지 정보를 돌려줌)
@app.post("/clusters/{cluster_id}/join")
def join_cluster(cluster_id: int, request: JoinRequest):
    name = (request.building or request.name or "").strip()
    if not name or request.households <= 0:
        raise HTTPException(422, "빌라 이름과 세대수를 올바르게 입력해 주세요.")

    conn = get_db()
    if conn.execute("SELECT 1 FROM clusters WHERE id = ?", (cluster_id,)).fetchone() is None:
        conn.close()
        raise HTTPException(404, "골목 단지를 찾을 수 없습니다.")
    conn.execute("INSERT INTO buildings (cluster_id, name, households) VALUES (?, ?, ?)",
                 (cluster_id, name, request.households))
    conn.execute("UPDATE clusters SET current = current + ? WHERE id = ?", (request.households, cluster_id))
    conn.commit()
    conn.close()
    return get_cluster(cluster_id)


# ① 사진 분류 (프론트가 "image"라는 이름으로 사진을 보냄)
@app.post("/classify")
async def classify(image: UploadFile = File(...)):
    if ai_module is None:
        raise HTTPException(503, f"AI 기능을 쓸 수 없어요. ({AI_ERROR})")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "API 키가 없어요. backend/.env 파일에 ANTHROPIC_API_KEY를 넣고 서버를 다시 켜 주세요.")
    try:
        return ai_module.classify_image(await image.read())
    except Exception as e:  # 예상 못 한 오류도 화면이 읽을 수 있는 모양으로 돌려줌
        return ai_module._error(f"AI 호출 중 오류: {e}")


# =========================================================
# 무단투기: 사진 판단 → 신고 저장 → 신고 목록
# =========================================================
def ensure_report_table():
    """신고 표가 없으면 만든다 (예전 garbage.db에도 자동으로 추가됨)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dumping_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            station_id INTEGER,
            verdict TEXT NOT NULL,
            severity TEXT,
            summary TEXT,
            report_text TEXT,
            target TEXT NOT NULL,          -- guardian(골목 지킴이) | city(지자체)
            status TEXT NOT NULL           -- 접수 | 처리 완료
        )""")
    conn.commit()
    conn.close()


if DB_PATH.exists():
    ensure_report_table()


# 사진을 보고 무단투기인지 판단 (저장은 하지 않음)
@app.post("/dumping/analyze")
async def dumping_analyze(image: UploadFile = File(...), station_id: Optional[int] = Form(None)):
    if ai_module is None:
        raise HTTPException(503, f"AI 기능을 쓸 수 없어요. ({AI_ERROR})")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "API 키가 없어요. backend/.env 파일에 ANTHROPIC_API_KEY를 넣고 서버를 다시 켜 주세요.")
    place = ""
    if station_id:
        s = next((x for x in get_stations() if x["id"] == station_id), None)
        place = s["name"] if s else ""
    try:
        return ai_module.analyze_dumping(await image.read(), place)
    except Exception as e:
        return ai_module._dumping_error(f"AI 호출 중 오류: {e}")


class ReportRequest(BaseModel):
    station_id: Optional[int] = None
    verdict: str
    severity: Optional[str] = None
    summary: Optional[str] = ""
    report_text: str
    target: str = "city"   # guardian | city


# 신고 저장
@app.post("/dumping/report")
def dumping_report(req: ReportRequest):
    if req.target not in ("guardian", "city"):
        raise HTTPException(422, "신고 대상은 guardian 또는 city만 가능해요.")
    if not req.report_text.strip():
        raise HTTPException(422, "신고 문구를 입력해 주세요.")
    ensure_report_table()
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO dumping_reports (created_at, station_id, verdict, severity, summary, report_text, target, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, '접수')""",
        (datetime.now().strftime("%Y-%m-%dT%H:%M"), req.station_id, req.verdict, req.severity,
         req.summary, req.report_text.strip(), req.target),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM dumping_reports WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


# 신고 목록 (최근 것부터)
@app.get("/dumping/reports")
def dumping_reports():
    ensure_report_table()
    conn = get_db()
    rows = conn.execute("SELECT * FROM dumping_reports ORDER BY id DESC LIMIT 30").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# 신고 처리 완료로 바꾸기
@app.post("/dumping/reports/{report_id}/done")
def dumping_report_done(report_id: int):
    ensure_report_table()
    conn = get_db()
    cur = conn.execute("UPDATE dumping_reports SET status = '처리 완료' WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "신고를 찾을 수 없어요.")
    return {"id": report_id, "status": "처리 완료"}
