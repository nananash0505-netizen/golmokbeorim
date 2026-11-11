"""
골목버림 AI 모듈 (팀원 1 담당)

백엔드(팀원 2)는 아래 함수만 import해서 쓰면 됩니다.

    from ai_module import classify_image, today_schedule
    from sensor_sim import generate_readings, predict_full_time

- classify_image(image_bytes)   → POST /classify
- today_schedule()              → GET  /schedule/today
- generate_readings(...)        → GET  /bins/{id}/readings  (seed 데이터)
- predict_full_time(readings)   → GET  /bins/{id}/predict
"""

import base64
import json
import os
import re
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()  # .env 파일에서 ANTHROPIC_API_KEY, CLAUDE_MODEL 읽기

# ── 설정 ──────────────────────────────────────────────
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")  # 더 빠르고 싸게: claude-haiku-5-5
RULES_PATH = Path(__file__).parent / "rules.json"
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB 넘으면 축소 (API 한도는 base64 기준 10MB)
MAX_TOKENS = 8000  # 생각 + 답변 합계 한도. 물건이 많은 사진에서 답이 잘리지 않도록 넉넉히
DEBUG = os.getenv("DEBUG") == "1"  # .env에 DEBUG=1을 넣으면 AI 원본 답변을 터미널에 출력

with open(RULES_PATH, encoding="utf-8") as f:
    RULES = json.load(f)

CATEGORIES = list(RULES["categories"].keys())
UNSURE = "판단 어려움"

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수를 자동으로 사용


# ── 프롬프트 ──────────────────────────────────────────
def _build_system_prompt() -> str:
    rules_text = json.dumps(RULES["categories"], ensure_ascii=False, indent=1)
    return f"""당신은 한국 빌라촌 주민을 돕는 분리배출 안내 도우미 '골목버림'입니다.
주민이 버리려는 물건의 사진을 보고, 아래 <rules>에 따라 어떻게 버려야 하는지 알려줍니다.

<rules>
{rules_text}
</rules>

판단 원칙:
1. 반드시 <rules>에 있는 분류 이름 중 하나만 category로 쓰세요: {", ".join(CATEGORIES)}
2. <rules>에 근거가 없거나 사진만으로 재질·오염 여부를 확신할 수 없으면 category를 "{UNSURE}"로 하고, 무엇을 확인하면 되는지 how에 적으세요. 추측으로 단정하지 마세요.
3. 한 물건이 여러 재질로 되어 있으면(예: 페트병 본체와 라벨, 용기와 뚜껑 필름) 부분별로 나눠 items에 각각 적으세요.
   사진에 물건이 여러 개면 가장 눈에 띄는 것부터 최대 8개까지만 적고, 쓰레기가 아닌 물건(노트북, 가방, 필기구 등)은 빼세요.
4. 음식물이 묻어 있으면 "헹구면 재활용 가능"인지 "씻기지 않아 일반쓰레기"인지 구분해 how에 적으세요.
5. 음식물쓰레기 중에서도 뼈·껍데기·씨처럼 일반쓰레기로 가야 하는 것은 따로 분리해 알려주세요.
6. 사진에 쓰레기가 없거나 너무 흐려서 알아볼 수 없으면 is_waste를 false로 하고 items는 빈 배열로 두세요.
7. how는 주민이 바로 따라 할 수 있게 한국어 한 문장(40자 안팎)으로 쓰세요. how와 tip에는 "<rules>", "규칙 파일" 같은 내부 표현을 쓰지 말고, 판단이 어려우면 "구청 안내를 확인해 주세요"처럼 주민 입장에서 쓰세요.
8. 음식물쓰레기가 보이면 food_quality에 물기와 이물질 상태를 적으세요. 없으면 null로 두세요.

출력 형식: 아래 JSON 하나만 출력하세요. 설명 문장이나 코드블록 표시는 붙이지 마세요.
{{
  "is_waste": true,
  "items": [
    {{"name": "물건 이름", "category": "분류 이름", "how": "배출 방법 한 문장", "confidence": "high | medium | low"}}
  ],
  "tip": "전체에 대한 짧은 팁 한 문장 또는 빈 문자열",
  "food_quality": {{"moisture": "적음 | 보통 | 많음", "foreign_matter": "없음 | 의심 | 있음", "comment": "한 문장"}}
}}"""


SYSTEM_PROMPT = _build_system_prompt()


# ── 내부 도우미 함수 ──────────────────────────────────
def _detect_media_type(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise ValueError("지원하지 않는 이미지 형식입니다 (jpg, png, webp, gif만 가능)")


def _shrink_if_needed(data: bytes) -> tuple[bytes, str]:
    """큰 사진은 긴 변 1568px로 줄여서 JPEG로 변환 (응답 속도·비용 절약)."""
    media_type = _detect_media_type(data)
    if len(data) <= MAX_IMAGE_BYTES:
        return data, media_type
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(data)).convert("RGB")
    img.thumbnail((1568, 1568))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _extract_json(text: str) -> dict:
    """모델 답변에서 JSON 부분만 꺼내기 (```json 감싸기가 붙어도 처리)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON을 찾을 수 없음")
    return json.loads(text[start : end + 1])


CONFIDENCE_SCORE = {"high": 0.9, "medium": 0.7, "low": 0.4}


def _add_frontend_fields(res: dict) -> dict:
    """
    프론트엔드 scan.html이 읽는 모양(item, category, steps, confidence 숫자)을 함께 넣는다.
    기존 필드(items, tip, food_quality …)는 그대로 두므로 더 자세한 화면에도 쓸 수 있다.
    """
    if not res["ok"]:
        res.update(item="인식 실패", category="다시 시도", steps=[res.get("error", "")], confidence=0)
    elif not res["is_waste"] or not res["items"]:
        res.update(item="쓰레기를 찾지 못했어요", category="다시 찍어 주세요",
                   steps=["물건이 화면 가운데 오도록 밝은 곳에서 다시 찍어 주세요"], confidence=0)
    else:
        items = res["items"]
        steps = [f"{i['name']}: {i['how']}" if len(items) > 1 else i["how"] for i in items]
        if res.get("tip"):
            steps.append(res["tip"])
        fq = res.get("food_quality")
        if fq and fq.get("comment"):
            steps.append(f"음식물 상태: {fq['comment']}")
        res.update(
            item=items[0]["name"],
            category=items[0]["category"],
            steps=steps,
            # 화면에 보이는 확신도 = 물건별 확신도의 평균 (가장 낮은 값을 쓰면 물건이 많을 때 지나치게 낮아짐)
            confidence=round(sum(CONFIDENCE_SCORE.get(i["confidence"], 0.4) for i in items) / len(items), 2),
        )
    return res


def _validate(result: dict) -> dict:
    """모델이 규칙 밖의 분류를 지어내면 '판단 어려움'으로 바꾸고, 공식 규칙 문장을 붙인다."""
    items = []
    for item in result.get("items", []) or []:
        category = item.get("category", UNSURE)
        if category not in CATEGORIES:
            category = UNSURE
        rule = RULES["categories"].get(category)
        items.append(
            {
                "name": str(item.get("name", "알 수 없음")),
                "category": category,
                "how": str(item.get("how", "")),
                "confidence": item.get("confidence", "low"),
                # AI가 아니라 rules.json에서 가져온 공식 안내 (환각 방지용 근거)
                "official_rule": rule["how"] if rule else None,
            }
        )
    return _add_frontend_fields({
        "ok": True,
        "is_waste": bool(result.get("is_waste", bool(items))),
        "items": items,
        "tip": result.get("tip", ""),
        "food_quality": result.get("food_quality"),
        "model": MODEL,
    })


def _error(message: str) -> dict:
    return _add_frontend_fields({"ok": False, "is_waste": False, "items": [], "tip": "", "food_quality": None,
                                 "error": message, "model": MODEL})


# ── 공개 함수 1: 사진 분류 ────────────────────────────
def classify_image(image_bytes: bytes, user_note: str = "") -> dict:
    """
    쓰레기 사진을 받아 분리배출 방법을 돌려준다.

    image_bytes: 업로드된 사진의 바이트 (FastAPI라면 await file.read())
    user_note:   주민이 덧붙인 설명 (예: "기름 묻은 배달 용기") — 선택
    반환: {"ok", "is_waste", "items":[{name, category, how, confidence, official_rule}], "tip", "food_quality"}
    """
    try:
        data, media_type = _shrink_if_needed(image_bytes)
    except Exception as e:
        return _error(f"이미지 처리 실패: {e}")

    user_text = "이 쓰레기를 어떻게 버려야 하나요?"
    if user_note:
        user_text += f"\n주민 설명: {user_note}"

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()},
                },
                {"type": "text", "text": user_text},
            ],
        }
    ]

    # JSON 파싱 실패 시 한 번만 다시 시도
    last_text, last_stop = "", ""
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=MODEL,
                # 생각(thinking)도 이 한도 안에서 쓰므로 넉넉하게. 실제로 쓴 만큼만 과금됨
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
        except anthropic.APIError as e:
            return _error(f"AI 호출 실패: {e}")

        # 응답에 thinking 블록이 섞일 수 있으므로 text 블록만 모은다
        text = "".join(block.text for block in response.content if block.type == "text")
        last_text, last_stop = text, response.stop_reason
        if DEBUG:
            print(f"[DEBUG] 시도 {attempt + 1} stop_reason={response.stop_reason}\n{text}\n")
        try:
            return _validate(_extract_json(text))
        except (ValueError, json.JSONDecodeError):
            if attempt == 0:
                if response.stop_reason == "max_tokens":
                    # 길어서 잘린 경우: 이어 붙이지 말고 처음부터 더 짧게 다시 요청
                    messages[-1]["content"][-1]["text"] = user_text + "\n물건이 많으면 주요 물건 6개까지만, how는 짧게 써 주세요."
                else:
                    messages.append({"role": "assistant", "content": text or "(빈 응답)"})
                    messages.append({"role": "user", "content": "지정한 JSON 형식 하나만 다시 출력해 주세요."})
    return _error(f"AI 응답을 해석하지 못했습니다 (stop_reason={last_stop}, 답변 끝부분: {last_text[-120:]!r})")


# ── 공개 함수 2: 오늘 버릴 수 있는 종류 (AI 없이 규칙으로) ──
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


# rules.json의 이름 → 프론트엔드 화면에 쓰는 짧은 이름
SCHEDULE_KINDS = [("음식물쓰레기", "음식물"), ("재활용", "재활용"), ("일반쓰레기", "일반")]


def _can_throw_on(kind: str, d: date) -> bool:
    sched = RULES["schedule"]
    return d.isoformat() not in sched.get("수거 중단일", []) and WEEKDAYS[d.weekday()] in sched.get(kind, [])


def today_schedule(target: date | None = None) -> dict:
    """
    오늘 버릴 수 있는 종류. 프론트엔드 index.html이 읽는 모양으로 돌려준다.
    {"date", "items": [{"type": "음식물", "ok": true, "time": "19:00 이후"}, ...], "notice"}
    """
    from datetime import timedelta

    target = target or date.today()
    sched = RULES["schedule"]
    start_time = sched.get("배출 시간", "19:00").split("~")[0].strip()
    stopped = target.isoformat() in sched.get("수거 중단일", [])

    items = []
    for kind, short in SCHEDULE_KINDS:
        if _can_throw_on(kind, target):
            items.append({"type": short, "ok": True, "time": f"{start_time} 이후"})
            continue
        # 다음으로 버릴 수 있는 날 찾기 (최대 2주)
        next_text = "일정 확인 필요"
        for k in range(1, 15):
            d = target + timedelta(days=k)
            if _can_throw_on(kind, d):
                label = "내일" if k == 1 else f"{d.month}/{d.day}"
                next_text = f"{label}({WEEKDAYS[d.weekday()]}) {start_time} 이후"
                break
        items.append({"type": short, "ok": False, "time": next_text})

    notice = "오늘은 수거 중단일이에요. 음식물은 냉동 보관해 주세요." if stopped else ""
    week_later = (target + timedelta(days=7)).isoformat()
    upcoming = sorted(s for s in sched.get("수거 중단일", []) if target.isoformat() < s <= week_later)
    if not notice and upcoming:
        notice = f"{upcoming[0]}부터 수거 중단 기간이 있어요. 미리 확인해 주세요."
    return {"date": target.isoformat(), "items": items, "notice": notice}


# ── 직접 실행해서 확인: python ai_module.py 사진.jpg ──
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용법: python ai_module.py <사진 경로> [설명]")
        sys.exit(1)
    note = sys.argv[2] if len(sys.argv) > 2 else ""
    result = classify_image(Path(sys.argv[1]).read_bytes(), note)
    print(json.dumps(result, ensure_ascii=False, indent=2))
