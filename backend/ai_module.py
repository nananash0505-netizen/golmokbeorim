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


# ── 공개 함수 3: 무단투기 판단 (모음터·골목 사진) ─────────
VERDICTS = ["무단투기 의심", "정상 배출", "판단 어려움"]

DUMPING_PROMPT = f"""당신은 한국 빌라촌 골목의 쓰레기 배출 상태를 점검하는 도우미 '골목버림'입니다.
모음터(공동 배출 거점)나 골목을 찍은 사진을 보고, 무단투기인지 판단해 신고 문구까지 만들어 줍니다.

<rules>
{json.dumps(RULES["categories"], ensure_ascii=False, indent=1)}
</rules>

무단투기로 보는 경우 (하나라도 해당하면 "무단투기 의심"):
- 종량제 봉투가 아닌 일반 비닐봉투·종이봉투에 쓰레기를 담아 내놓음
- 재활용품을 품목별로 나누지 않고 한 봉투에 섞어 버림, 음식물이 묻은 채로 버림
- 상자를 접거나 묶지 않고 그대로 쌓아 둠
- 음식물쓰레기를 전용 용기·봉투 없이 버림
- 수거함 밖 바닥, 보행로, 건물 벽 앞에 쌓아 두어 통행을 막음
- 대형폐기물(가구, 가전 등)을 신고 스티커 없이 내놓음

판단 원칙:
1. verdict는 반드시 다음 중 하나: {", ".join(VERDICTS)}
2. 사진에서 실제로 보이는 것만 근거로 쓰고, 보이지 않는 것은 추측하지 마세요.
3. 사람을 묘사하거나 알아보려 하지 마세요. 사람 얼굴이나 차량 번호판이 보이면 privacy_note에 "개인정보 가림 필요"라고만 적으세요.
4. 상표나 가게 이름은 적지 말고 물건 종류로만 적으세요 (예: "치킨 포장 봉투").
5. report_text는 지자체나 골목 지킴이에게 보낼 신고 문구로, 장소 설명 없이 상황만 2~3문장으로 쓰세요.
6. severity는 통행 방해·악취·양을 보고 "높음 | 보통 | 낮음"으로 적으세요.

출력 형식: 아래 JSON 하나만 출력하세요. 설명이나 코드블록 표시는 붙이지 마세요.
{{
  "verdict": "무단투기 의심",
  "severity": "높음",
  "summary": "한 문장 요약",
  "violations": ["보이는 위반 사항 한 문장씩, 최대 5개"],
  "items": [{{"name": "물건", "category": "분류 이름", "problem": "무엇이 문제인지 한 문장"}}],
  "estimated_bags": 0,
  "blocks_path": true,
  "report_text": "신고 문구",
  "action": "정리 방법 한 문장",
  "privacy_note": ""
}}"""


def _dumping_error(message: str) -> dict:
    return {"ok": False, "verdict": "판단 어려움", "severity": "낮음", "summary": message, "violations": [],
            "items": [], "estimated_bags": 0, "blocks_path": False, "report_text": "", "action": "",
            "privacy_note": "", "error": message, "model": MODEL}


def _validate_dumping(r: dict) -> dict:
    verdict = r.get("verdict") if r.get("verdict") in VERDICTS else "판단 어려움"
    severity = r.get("severity") if r.get("severity") in ("높음", "보통", "낮음") else "보통"
    items = []
    for it in (r.get("items") or [])[:8]:
        cat = it.get("category", UNSURE)
        items.append({"name": str(it.get("name", "")), "category": cat if cat in CATEGORIES else UNSURE,
                      "problem": str(it.get("problem", ""))})
    return {
        "ok": True,
        "verdict": verdict,
        "severity": severity,
        "summary": str(r.get("summary", "")),
        "violations": [str(v) for v in (r.get("violations") or [])][:5],
        "items": items,
        "estimated_bags": int(r.get("estimated_bags") or 0),
        "blocks_path": bool(r.get("blocks_path")),
        "report_text": str(r.get("report_text", "")),
        "action": str(r.get("action", "")),
        "privacy_note": str(r.get("privacy_note", "")),
        "model": MODEL,
    }


def analyze_dumping(image_bytes: bytes, place: str = "") -> dict:
    """
    모음터·골목 사진을 보고 무단투기 여부를 판단한다.
    반환: {"ok", "verdict", "severity", "summary", "violations", "items", "estimated_bags",
           "blocks_path", "report_text", "action", "privacy_note"}
    """
    try:
        data, media_type = _shrink_if_needed(image_bytes)
    except Exception as e:
        return _dumping_error(f"이미지 처리 실패: {e}")

    text = "이 사진의 쓰레기 배출 상태를 점검해 주세요."
    if place:
        text += f"\n장소: {place}"
    messages = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()}},
        {"type": "text", "text": text},
    ]}]

    for attempt in range(2):
        try:
            response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=DUMPING_PROMPT, messages=messages)
        except anthropic.APIError as e:
            return _dumping_error(f"AI 호출 실패: {e}")
        out = "".join(b.text for b in response.content if b.type == "text")
        if DEBUG:
            print(f"[DEBUG] 무단투기 시도 {attempt + 1}\n{out}\n")
        try:
            return _validate_dumping(_extract_json(out))
        except (ValueError, json.JSONDecodeError):
            messages.append({"role": "assistant", "content": out or "(빈 응답)"})
            messages.append({"role": "user", "content": "지정한 JSON 형식 하나만 다시 출력해 주세요."})
    return _dumping_error("AI 응답을 해석하지 못했어요. 다시 시도해 주세요.")


# ── 공개 함수 4: AI 골목 브리핑 (규칙·통계 신호 → AI가 할 일을 정리) ──
BRIEFING_PROMPT = """당신은 관리사무소가 없는 빌라촌 골목의 '디지털 관리사무소' 역할을 하는 AI 도우미 '골목버림'입니다.
서버가 센서 기록과 규칙으로 계산한 신호(모음터 적재율, 가득 찰 예상 시각, 장비 이상 의심, 무단투기 신고, 오늘 배출 일정)를 JSON으로 받습니다.
이 신호를 해석해서 주민, 골목 지킴이, 수거업체가 오늘 해야 할 일을 정리해 주세요.

원칙:
1. 받은 데이터에 있는 장소, 숫자, 시각만 쓰세요. 없는 사실이나 숫자를 지어내지 마세요.
2. 시각은 "오늘 밤 10시", "내일 아침 8시"처럼 사람이 읽기 쉽게 바꾸되, 기준 시각(now)을 기준으로 판단하세요.
3. 주민 공지는 해요체로 2~3문장. 오늘 버릴 수 있는 것과 가득 찰 모음터를 피해서 버릴 곳을 알려 주세요.
4. pickup_priority는 수거업체가 먼저 비울 통 순서로 최대 3개. 적재율과 가득 찰 시각을 함께 보고 정하세요.
5. equipment는 장비 이상 의심(status가 suspect)인 통마다 하나씩. 신호 유형으로 가능성 높은 원인과 현장에서 확인할 것을 쓰고,
   수거업체에 보낼 수리 요청 문구(1~2문장)를 써 주세요. 이상이 없으면 빈 배열.
   - spike(무게가 갑자기 튐): 센서 오작동, 무거운 이물질 투입 가능성
   - stuck(문은 열리는데 무게 변화 없음): 저울(로드셀) 고장, 투입구 막힘 가능성
6. guardian_todo는 이번 주 골목 지킴이가 할 일 2~4개 (무단투기 정리 포함).
7. dumping은 처리 안 된 무단투기 신고를 한두 문장으로 요약. 없으면 빈 문자열.
8. risk_level은 오늘 골목 상황 전체를 "높음 | 보통 | 낮음" 중 하나로.

출력 형식: 아래 JSON 하나만 출력하세요. 설명이나 코드블록 표시는 붙이지 마세요.
{
  "headline": "오늘 골목 상황 한 문장",
  "risk_level": "보통",
  "resident_notice": "주민 공지문",
  "pickup_priority": [{"place": "모음터 B · 재활용", "fill": 91, "when": "오늘 밤 10시 전", "reason": "이유 한 문장"}],
  "equipment": [{"place": "모음터 B · 음식물", "likely_cause": "가능성 높은 원인", "check": "현장에서 확인할 것", "request_text": "수리 요청 문구"}],
  "guardian_todo": ["할 일"],
  "dumping": "무단투기 요약"
}"""


def _briefing_error(message: str) -> dict:
    return {"ok": False, "headline": message, "risk_level": "보통", "resident_notice": "", "pickup_priority": [],
            "equipment": [], "guardian_todo": [], "dumping": "", "error": message, "model": MODEL}


def _validate_briefing(r: dict) -> dict:
    def _s(v):
        return str(v or "").strip()
    pickup = []
    for p in (r.get("pickup_priority") or [])[:3]:
        try:
            fill = int(round(float(p.get("fill"))))
        except (TypeError, ValueError):
            fill = None
        pickup.append({"place": _s(p.get("place")), "fill": fill, "when": _s(p.get("when")), "reason": _s(p.get("reason"))})
    equipment = [{"place": _s(e.get("place")), "likely_cause": _s(e.get("likely_cause")),
                  "check": _s(e.get("check")), "request_text": _s(e.get("request_text"))}
                 for e in (r.get("equipment") or [])[:5]]
    return {
        "ok": True,
        "headline": _s(r.get("headline")),
        "risk_level": r.get("risk_level") if r.get("risk_level") in ("높음", "보통", "낮음") else "보통",
        "resident_notice": _s(r.get("resident_notice")),
        "pickup_priority": pickup,
        "equipment": equipment,
        "guardian_todo": [_s(t) for t in (r.get("guardian_todo") or []) if _s(t)][:4],
        "dumping": _s(r.get("dumping")),
        "model": MODEL,
    }


def generate_briefing(context: dict) -> dict:
    """
    서버가 모은 골목 신호(context)를 AI가 해석해 오늘 할 일을 정리한다.
    반환: {"ok", "headline", "risk_level", "resident_notice", "pickup_priority", "equipment", "guardian_todo", "dumping"}
    """
    messages = [{"role": "user", "content": "오늘 골목 신호입니다. 정리해 주세요.\n" +
                 json.dumps(context, ensure_ascii=False, indent=1)}]
    for attempt in range(2):
        try:
            response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=BRIEFING_PROMPT, messages=messages)
        except anthropic.APIError as e:
            return _briefing_error(f"AI 호출 실패: {e}")
        out = "".join(b.text for b in response.content if b.type == "text")
        if DEBUG:
            print(f"[DEBUG] 브리핑 시도 {attempt + 1}\n{out}\n")
        try:
            return _validate_briefing(_extract_json(out))
        except (ValueError, json.JSONDecodeError):
            messages.append({"role": "assistant", "content": out or "(빈 응답)"})
            messages.append({"role": "user", "content": "지정한 JSON 형식 하나만 다시 출력해 주세요."})
    return _briefing_error("AI 응답을 해석하지 못했어요. 다시 시도해 주세요.")
