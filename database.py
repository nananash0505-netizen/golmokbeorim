import sqlite3

conn = sqlite3.connect("garbage.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS stations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    capacity INTEGER NOT NULL
)
""")

cursor.execute("SELECT COUNT(*) FROM stations")
count = cursor.fetchone()[0]

if count == 0:
    cursor.execute(
        "INSERT INTO stations VALUES (?, ?, ?)",
        (1, "모음터 A", 80)
    )
    cursor.execute(
        "INSERT INTO stations VALUES (?, ?, ?)",
        (2, "모음터 B", 45)
    )

conn.commit()
conn.close()

print("데이터베이스 생성 완료!")
conn = sqlite3.connect("garbage.db")
cursor = conn.cursor()

cursor.execute(
    "UPDATE stations SET capacity = 90 WHERE id = 1"
)

conn.commit()
conn.close()