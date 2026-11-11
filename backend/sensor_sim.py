"""
모음터 적재율 가짜 센서 데이터 생성 + 가득 찰 시각 예측 (팀원 1 담당)

    python sensor_sim.py          → seed_readings.json 생성 + 예측 결과 출력
"""

import json
import random
from datetime import datetime, timedelta

# 시간대별 배출 가중치: 저녁 7~10시에 가장 많이 버린다
HOURLY_WEIGHT = [0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 0.6, 0.5, 0.3, 0.3, 0.4,
                 0.6, 0.4, 0.3, 0.3, 0.4, 0.6, 1.0, 2.0, 2.2, 1.8, 1.0, 0.5]
PICKUP_HOUR = 6  # 매일 오전 6시 수거 → 적재율 0%로 초기화


# 프론트엔드 api.js와 같은 통 번호: 모음터 1~3 × (음식물, 재활용, 일반)
BINS = {11: "음식물", 12: "재활용", 13: "일반",
        21: "음식물", 22: "재활용", 23: "일반",
        31: "음식물", 32: "재활용", 33: "일반"}


def generate_readings(bin_ids=tuple(BINS), days=3, end=None, seed=42):
    """
    모음터 통별 1시간 간격 적재율(%) 기록을 만든다.
    반환: [{"bin_id": 11, "time": "2026-11-11T19:00", "fill": 63.2}, ...]
    ("time"은 프론트엔드 api.js가 읽는 이름, "ts"는 같은 값의 예전 이름)
    """
    rng = random.Random(seed)
    end = (end or datetime.now()).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    readings = []
    for bin_id in bin_ids:
        speed = rng.uniform(2.5, 4.5)  # 통마다 차는 속도가 다름 (%/가중치 1 기준)
        fill = rng.uniform(0, 20)
        t = start
        while t <= end:
            if t.hour == PICKUP_HOUR:
                fill = 0.0
            else:
                fill += HOURLY_WEIGHT[t.hour] * speed * rng.uniform(0.6, 1.4)
                fill = min(fill, 100.0)
            stamp = t.isoformat(timespec="minutes")
            readings.append({"bin_id": bin_id, "time": stamp, "ts": stamp, "fill": round(fill, 1)})
            t += timedelta(hours=1)
    return readings


def predict_full_time(readings, window=6):
    """
    한 통의 적재율 기록으로 100%가 될 시각을 예측한다.
    마지막 수거(적재율이 크게 떨어진 지점) 이후 최근 window개 기록에 직선을 맞춰 기울기를 구한다.

    readings: 한 통의 기록 리스트 (시간 오름차순), 각 원소 {"time" 또는 "ts": ISO 문자열/datetime, "fill": float}
    반환: {"bin_id", "full_at", "current_fill", "rate_per_hour", "predicted_full_at", "hours_left", "status"}
          ("full_at"은 프론트엔드 api.js가 읽는 이름, "predicted_full_at"과 같은 값)
    """
    if not readings:
        return {"bin_id": None, "full_at": None, "status": "no_data"}
    result = _predict(readings, window)
    result["bin_id"] = readings[0].get("bin_id")
    result["full_at"] = result.get("predicted_full_at")
    return result


def _predict(readings, window):
    def _t(r):
        v = r.get("time", r.get("ts"))
        return v if isinstance(v, datetime) else datetime.fromisoformat(v)

    pts = [(_t(r), float(r["fill"])) for r in readings]

    # 마지막 수거 이후 구간만 사용 (적재율이 10%p 넘게 떨어진 곳 = 수거)
    last_reset = 0
    for i in range(1, len(pts)):
        if pts[i][1] < pts[i - 1][1] - 10:
            last_reset = i
    segment = pts[last_reset:][-window:]
    now_t, now_fill = segment[-1]

    if now_fill >= 100:
        return {"current_fill": now_fill, "rate_per_hour": None, "predicted_full_at": now_t.isoformat(timespec="minutes"),
                "hours_left": 0, "status": "full"}
    if len(segment) < 2:
        return {"current_fill": now_fill, "rate_per_hour": None, "predicted_full_at": None,
                "hours_left": None, "status": "not_enough_data"}

    # 최소제곱 직선 기울기 (x: 시간[h], y: 적재율[%])
    t0 = segment[0][0]
    xs = [(t - t0).total_seconds() / 3600 for t, _ in segment]
    ys = [f for _, f in segment]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    rate = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0.0

    if rate <= 0.05:
        return {"current_fill": now_fill, "rate_per_hour": round(rate, 2), "predicted_full_at": None,
                "hours_left": None, "status": "stable"}

    hours_left = (100 - now_fill) / rate
    return {
        "current_fill": now_fill,
        "rate_per_hour": round(rate, 2),
        "predicted_full_at": (now_t + timedelta(hours=hours_left)).isoformat(timespec="minutes"),
        "hours_left": round(hours_left, 1),
        "status": "warning" if now_fill >= 80 or hours_left <= 3 else "ok",
    }


# =============================================================
# 장비 이상 감지 (프론트 features.js의 detectFault와 같은 규칙 + 수거 오탐 방지)
# =============================================================

# 판단 기준값. 발표 때 "이 숫자들을 기준으로 이상을 감지한다"고 설명하면 됨
SPIKE_KG = 15.0        # 1시간 사이 무게가 이만큼 넘게 변하면 센서 오류 의심
PICKUP_LEFT_KG = 2.0   # 무게가 이 값 아래로 떨어진 건 수거(통 비움)로 보고 오류에서 제외
STUCK_HOURS = 4        # 최근 몇 시간을 볼지
STUCK_OPENS = 10       # 그동안 문이 이만큼 이상 열렸는데
STUCK_CHANGE_KG = 0.3  # 무게 변화가 이것보다 작으면 저울 고장 의심


def generate_sensor_logs(bin_ids=tuple(BINS), hours=8, end=None, seed=7,
                         faults=None):
    """
    통별 시간당 '문 열린 횟수'와 '통 무게(kg)' 가짜 기록을 만든다.
    faults: 일부러 고장을 넣을 통 {통번호: "stuck" | "spike"}. 기본값은 프론트와 같은 21번(저울 멈춤), 33번(값 튐)
    반환: {통번호: [{"time": "2026-11-11T13:00", "door_opens": 3, "weight_kg": 21.0}, ...]}
    """
    rng = random.Random(seed)
    faults = {21: "stuck", 33: "spike"} if faults is None else faults
    end = (end or datetime.now()).replace(minute=0, second=0, microsecond=0)
    logs = {}
    for bin_id in bin_ids:
        weight = rng.uniform(3, 20)
        per_open = {"음식물": 0.45, "재활용": 0.35, "일반": 0.3}.get(BINS.get(bin_id), 0.35)
        rows = []
        for i in range(hours):
            t = end - timedelta(hours=hours - 1 - i)
            opens = rng.randint(1, 5)
            if faults.get(bin_id) == "stuck" and i >= 2:
                opens = rng.randint(3, 5)          # 문은 계속 열리는데
                shown = rows[-1]["weight_kg"]      # 무게는 그대로 (저울 멈춤)
            else:
                weight += opens * per_open * rng.uniform(0.6, 1.4)
                shown = round(weight, 1)
                if faults.get(bin_id) == "spike" and i == hours // 2:
                    shown = round(weight + 31.0, 1)  # 한 번만 값이 크게 튐
            rows.append({"time": t.isoformat(timespec="minutes"), "door_opens": opens, "weight_kg": shown})
        logs[bin_id] = rows
    return logs


def detect_fault(log, bin_id=None):
    """
    한 통의 센서 기록으로 장비 이상을 판단한다.
    log: [{"door_opens": int, "weight_kg": float, ...}, ...] (시간 오름차순)
         프론트 형식 [[문열림, 무게], ...] 도 받음
    반환: {"bin_id", "status": "normal" | "suspect" | "unknown", "type": "spike" | "stuck" | None, "reason"}
    """
    if not log or len(log) < 2:
        return {"bin_id": bin_id, "status": "unknown", "type": None, "reason": "기록이 부족해요"}

    rows = [(r[0], r[1]) if isinstance(r, (list, tuple)) else (r["door_opens"], r["weight_kg"]) for r in log]

    # 1) 값 튐: 1시간 사이 큰 변화. 단, 거의 0으로 떨어진 건 수거라서 제외
    for i in range(1, len(rows)):
        prev_w, cur_w = rows[i - 1][1], rows[i][1]
        jump = abs(cur_w - prev_w)
        is_pickup = cur_w < prev_w and cur_w <= PICKUP_LEFT_KG
        if jump > SPIKE_KG and not is_pickup:
            return {"bin_id": bin_id, "status": "suspect", "type": "spike",
                    "reason": f"무게 값이 한 시간 만에 {jump:.1f}kg 튀었어요"}

    # 2) 저울 멈춤: 문은 자주 열리는데 무게가 그대로
    recent = rows[-STUCK_HOURS:]
    opens = sum(o for o, _ in recent)
    change = recent[-1][1] - recent[0][1]
    if opens >= STUCK_OPENS and change < STUCK_CHANGE_KG:
        return {"bin_id": bin_id, "status": "suspect", "type": "stuck",
                "reason": f"최근 {len(recent)}시간 동안 문이 {opens}번 열렸는데 무게 변화가 없어요"}

    return {"bin_id": bin_id, "status": "normal", "type": None, "reason": ""}


if __name__ == "__main__":
    end = datetime(2026, 11, 11, 20, 0)

    data = generate_readings(end=end)
    with open("seed_readings.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"seed_readings.json 저장: {len(data)}개 기록")
    for bin_id in sorted({r["bin_id"] for r in data}):
        rows = [r for r in data if r["bin_id"] == bin_id]
        print(bin_id, predict_full_time(rows))

    logs = generate_sensor_logs(end=end)
    with open("seed_sensor_logs.json", "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in logs.items()}, f, ensure_ascii=False, indent=1)
    print(f"\nseed_sensor_logs.json 저장: 통 {len(logs)}개")
    for bin_id, log in logs.items():
        r = detect_fault(log, bin_id)
        print(bin_id, r["status"], r["reason"])
