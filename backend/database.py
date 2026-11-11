
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# 데이터베이스 연결
conn = sqlite3.connect(Path(__file__).parent / "garbage.db")  # main.py 옆의 DB 파일
cursor = conn.cursor()

# 1. 모음터 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS stations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL
)
""")

# 2. 쓰레기통 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS bins (
    id INTEGER PRIMARY KEY,
    station_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    fill INTEGER NOT NULL,
    full_at TEXT,
    FOREIGN KEY (station_id) REFERENCES stations(id)
)
""")

# 3. 적재율 기록 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id INTEGER NOT NULL,
    time TEXT NOT NULL,
    fill INTEGER NOT NULL,
    FOREIGN KEY (bin_id) REFERENCES bins(id)
)
""")

# 4. 배출 일정 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week INTEGER NOT NULL,
    type TEXT NOT NULL,
    ok INTEGER NOT NULL,
    time TEXT NOT NULL
)
""")

# 5. 골목 단지 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    target INTEGER NOT NULL,
    current INTEGER NOT NULL
)
""")

# 6. 참여 건물 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS buildings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    households INTEGER NOT NULL,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id)
)
""")

# 7. 무단투기 신고 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS dumping_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    station_id INTEGER,
    verdict TEXT NOT NULL,
    severity TEXT,
    summary TEXT,
    report_text TEXT,
    target TEXT NOT NULL,
    status TEXT NOT NULL
)
""")

# 모음터 초기 데이터
stations = [
    (1, "모음터 A (오래3길 끝 주차장)", 37.22044, 126.95515),
    (2, "모음터 B (골목 모퉁이 빈터)", 37.22016, 126.95456),
    (3, "모음터 C (오래3길 입구 공터)", 37.22075, 126.95377)
]

cursor.executemany("""
INSERT OR IGNORE INTO stations
(id, name, lat, lng) VALUES (?, ?, ?, ?)
""", stations)

# 쓰레기통 초기 데이터
bins = [
    (11, 1, "음식물", 82, "2026-11-12T08:00"),
    (12, 1, "재활용", 45, "2026-11-13T20:00"),
    (13, 1, "일반", 30, "2026-11-14T10:00"),
    (21, 2, "음식물", 38, "2026-11-13T07:00"),
    (22, 2, "재활용", 91, "2026-11-11T22:00"),
    (23, 2, "일반", 55, "2026-11-13T15:00"),
    (31, 3, "음식물", 15, "2026-11-14T09:00"),
    (32, 3, "재활용", 20, "2026-11-15T12:00"),
    (33, 3, "일반", 64, "2026-11-12T19:00")
]

cursor.executemany("""
INSERT OR IGNORE INTO bins
(id, station_id, type, fill, full_at)
VALUES (?, ?, ?, ?, ?)
""", bins)

# 적재율 기록 초기 데이터
# 프론트엔드의 시연용 그래프와 비슷한 형태
cursor.execute("SELECT COUNT(*) FROM readings")
if cursor.fetchone()[0] == 0:
    end_time = datetime(2026, 11, 11, 12, 0)

    for bin_id, station_id, waste_type, fill, full_at in bins:
        for i in range(24):
            time = end_time - timedelta(hours=23-i)
            value = max(0, round(fill * (i+7) / 30))

            cursor.execute("""
            INSERT INTO readings (bin_id, time, fill)
            VALUES (?, ?, ?)
            """, (
                bin_id,
                time.strftime("%Y-%m-%dT%H:%M"),
                value
            ))

# 배출 일정 초기 데이터
# 프론트엔드의 2026-11-11 시연 일정
schedules = [
    (2, "음식물", 1, "20:00 이후"),
    (2, "재활용", 1, "20:00 이후"),
    (2, "일반", 0, "내일(목) 20:00 이후")
]

cursor.executemany("""
INSERT INTO schedules (day_of_week, type, ok, time)
SELECT ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM schedules
    WHERE day_of_week = ? AND type = ?
)
""", [
    (day, typ, ok, tm, day, typ)
    for day, typ, ok, tm in schedules
])

# 골목 단지 초기 데이터
cursor.execute("""
INSERT OR IGNORE INTO clusters
(id, name, target, current)
VALUES (1, '오래3길 골목 단지', 60, 47)
""")

# 참여 건물 초기 데이터
buildings = [
    (1, "행복빌", 12),
    (1, "금성주택", 16),
    (1, "J.B 타운", 9),
    (1, "신영빌라트", 10)
]

cursor.execute("SELECT COUNT(*) FROM buildings")
if cursor.fetchone()[0] == 0:
    cursor.executemany("""
    INSERT INTO buildings (cluster_id, name, households)
    VALUES (?, ?, ?)
    """, buildings)

# 저장 및 종료
conn.commit()
conn.close()

print("골목버림 데이터베이스 생성 완료!")
