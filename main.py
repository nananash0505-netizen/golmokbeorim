from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "골목버림 서버 실행 성공!"}
@app.get("/stations")
def get_stations():
    import sqlite3

    conn = sqlite3.connect("garbage.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stations")

    stations = cursor.fetchall()
    result = [dict(row) for row in stations]

    conn.close()

    return result