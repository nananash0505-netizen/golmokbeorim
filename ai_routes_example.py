"""
[팀원 2용 참고 코드] AI 모듈을 FastAPI에 연결하는 예시

팀원 2의 main.py에 필요한 부분만 복사해서 쓰면 됩니다.
DB 대신 seed JSON 파일을 읽는 버전이라, DB가 준비되면 load_* 부분만 DB 조회로 바꾸면 됩니다.

설치:  py -m pip install fastapi uvicorn python-multipart
실행:  py -m uvicorn ai_routes_example:app --reload
확인:  브라우저에서 http://localhost:8000/docs
"""

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from ai_module import classify_image, today_schedule
from sensor_sim import BINS, detect_fault, predict_full_time

app = FastAPI(title="골목버림 API")

# 프론트를 파일로 열거나 다른 포트에서 띄워도 접근할 수 있게 허용 (해커톤용 설정)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE = Path(__file__).parent
READINGS = json.loads((BASE / "seed_readings.json").read_text(encoding="utf-8"))
SENSOR_LOGS = {int(k): v for k, v in json.loads((BASE / "seed_sensor_logs.json").read_text(encoding="utf-8")).items()}

# 모음터 정보 (프론트 api.js의 MOCK.stations와 같은 이름·좌표)
STATIONS = [
    {"id": 1, "name": "모음터 A (오래3길 끝 주차장)", "lat": 37.22044, "lng": 126.95515, "bin_ids": [11, 12, 13]},
    {"id": 2, "name": "모음터 B (골목 모퉁이 빈터)", "lat": 37.22016, "lng": 126.95456, "bin_ids": [21, 22, 23]},
    {"id": 3, "name": "모음터 C (오래3길 입구 공터)", "lat": 37.22075, "lng": 126.95377, "bin_ids": [31, 32, 33]},
]


def load_readings(bin_id: int) -> list[dict]:
    rows = [r for r in READINGS if r["bin_id"] == bin_id]
    if not rows:
        raise HTTPException(404, f"{bin_id}번 통이 없어요")
    return rows


@app.post("/classify")
async def classify(image: UploadFile = File(...)):  # 프론트가 "image"라는 이름으로 보냄
    return classify_image(await image.read())


@app.get("/schedule/today")
def schedule_today():
    return today_schedule()


@app.get("/stations")
def stations():
    result = []
    for s in STATIONS:
        bins = []
        for bin_id in s["bin_ids"]:
            rows = load_readings(bin_id)
            bins.append({
                "id": bin_id,
                "type": BINS[bin_id],
                "fill": round(rows[-1]["fill"]),
                "full_at": predict_full_time(rows)["full_at"],
            })
        result.append({"id": s["id"], "name": s["name"], "lat": s["lat"], "lng": s["lng"], "bins": bins})
    return result


@app.get("/bins/{bin_id}/readings")
def readings(bin_id: int):
    return load_readings(bin_id)[-24:]  # 차트는 최근 24시간만


@app.get("/bins/{bin_id}/predict")
def predict(bin_id: int):
    return predict_full_time(load_readings(bin_id))


@app.get("/bins/{bin_id}/fault")  # 새로 추가된 API: 장비 이상 감지
def fault(bin_id: int):
    return detect_fault(SENSOR_LOGS.get(bin_id, []), bin_id)
