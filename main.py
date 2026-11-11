import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5501",
        "http://localhost:5501",
        "http://127.0.0.1:5500",
        "http://localhost:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 데이터베이스 연결 함수
def get_db():
    conn = sqlite3.connect("garbage.db")
    conn.row_factory = sqlite3.Row
    return conn


# 1. 서버 실행 확인
@app.get("/")
def home():
    return {"message": "골목버림 서버 실행 성공!"}


# 2. 모음터 전체 조회
@app.get("/stations")
def get_stations():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM stations")
    stations = cursor.fetchall()

    result = []

    for station in stations:
        cursor.execute(
            "SELECT * FROM bins WHERE station_id = ?",
            (station["id"],)
        )
        bins = cursor.fetchall()

        result.append({
            "id": station["id"],
            "name": station["name"],
            "lat": station["lat"],
            "lng": station["lng"],
            "bins": [
                {
                    "id": b["id"],
                    "type": b["type"],
                    "fill": b["fill"],
                    "full_at": b["full_at"]
                }
                for b in bins
            ]
        })

    conn.close()
    return result


# 3. 특정 모음터 조회
@app.get("/stations/{station_id}")
def get_station(station_id: int):
    stations = get_stations()

    for station in stations:
        if station["id"] == station_id:
            return station

    raise HTTPException(
        status_code=404,
        detail="모음터를 찾을 수 없습니다."
    )


# 4. 쓰레기통 적재율 기록 조회
@app.get("/bins/{bin_id}/readings")
def get_readings(bin_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT time, fill FROM readings WHERE bin_id = ? ORDER BY time",
        (bin_id,)
    )

    readings = cursor.fetchall()
    conn.close()

    return [dict(row) for row in readings]


# 5. 쓰레기통 가득 차는 시간 조회
@app.get("/bins/{bin_id}/predict")
def get_prediction(bin_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT full_at FROM bins WHERE id = ?",
        (bin_id,)
    )

    bin_data = cursor.fetchone()
    conn.close()

    if bin_data is None:
        raise HTTPException(
            status_code=404,
            detail="쓰레기통을 찾을 수 없습니다."
        )

    return {
        "bin_id": bin_id,
        "full_at": bin_data["full_at"]
    }

# 6. 오늘의 쓰레기 배출 일정 조회

@app.get("/schedule/today")
def get_today_schedule():
    from datetime import datetime

    now = datetime.now()
    today = now.weekday()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT type, ok, time FROM schedules WHERE day_of_week = ?",
        (today,)
    )

    schedules = cursor.fetchall()
    conn.close()

    return {
        "date": now.strftime("%Y-%m-%d"),
        "items": [
            {
                "type": row["type"],
                "ok": bool(row["ok"]),
                "time": row["time"]
            }
            for row in schedules
        ],
        "notice": "지역별 배출 일정을 확인해 주세요."
    }

# 7. 골목 단지 정보 조회
@app.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM clusters WHERE id = ?",
        (cluster_id,)
    )
    cluster = cursor.fetchone()

    if cluster is None:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="골목 단지를 찾을 수 없습니다."
        )

    cursor.execute(
        "SELECT id, name, households FROM buildings WHERE cluster_id = ?",
        (cluster_id,)
    )
    buildings = cursor.fetchall()

    result = {
        "id": cluster["id"],
        "name": cluster["name"],
        "target": cluster["target"],
        "current": cluster["current"],
        "buildings": [dict(row) for row in buildings]
    }

    conn.close()
    return result

class JoinRequest(BaseModel):
    name: str
    households: int


# 8. 골목 단지 참여 신청
@app.post("/clusters/{cluster_id}/join")
def join_cluster(cluster_id: int, request: JoinRequest):
    if not request.name.strip() or request.households <= 0:
        raise HTTPException(
            status_code=422,
            detail="건물 이름과 가구 수를 올바르게 입력해 주세요."
        )

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM clusters WHERE id = ?",
        (cluster_id,)
    )
    cluster = cursor.fetchone()

    if cluster is None:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="골목 단지를 찾을 수 없습니다."
        )

    cursor.execute(
        """INSERT INTO buildings
        (cluster_id, name, households)
        VALUES (?, ?, ?)""",
        (cluster_id, request.name, request.households)
    )

    cursor.execute(
        """UPDATE clusters
        SET current = current + ?
        WHERE id = ?""",
        (request.households, cluster_id)
    )

    conn.commit()
    conn.close()

    return {
        "message": "골목 단지 참여 신청 완료!",
        "name": request.name,
        "households": request.households
    }