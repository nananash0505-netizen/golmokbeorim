"""
분류 정확도 테스트 (발표용 수치 만들기)

준비:
  test_images/ 폴더에 사진을 넣고, test_images/answers.csv 를 만든다.
    filename,expected
    pet_bottle.jpg,투명 페트병
    chicken_bone.jpg,일반쓰레기
    food_tray.jpg,음식물쓰레기+플라스틱/일반쓰레기

  정답 적는 법
    한 가지:          일반쓰레기          (AI 답의 첫 번째 물건으로 채점)
    여러 물건 모두:    음식물쓰레기+일반쓰레기   (적힌 분류가 결과에 모두 있어야 정답)
    둘 중 하나:        플라스틱/일반쓰레기       (헹구면 플라스틱, 안 씻기면 일반처럼 둘 다 맞는 경우)

실행:
  python test_classify.py
  CLAUDE_MODEL=claude-haiku-5-5 python test_classify.py   ← 모델 비교용

결과: 정확도 출력 + test_results_<모델>.csv 저장
"""

import csv
import time
from pathlib import Path

from ai_module import MODEL, classify_image

TEST_DIR = Path("test_images")

IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".png", ".webp", ".gif"}


def find_image(name: str):
    """적힌 이름 그대로 있으면 그 파일, 없으면 확장자만 다른 같은 이름의 사진을 찾는다 (test_06.jpg → test_06.png)."""
    path = TEST_DIR / name.strip()
    if path.exists():
        return path
    stem = Path(name.strip()).stem
    for p in TEST_DIR.iterdir():
        if p.stem == stem and p.suffix.lower() in IMAGE_EXTS:
            return p
    return None


rows = [r for r in csv.DictReader(open(TEST_DIR / "answers.csv", encoding="utf-8-sig")) if r.get("filename")]
results, correct, total_sec, skipped = [], 0, 0.0, []

for row in rows:
    path = find_image(row["filename"])
    if path is None:
        skipped.append(row["filename"])
        print(f"-  {row['filename']:<14} 사진 파일을 찾지 못해 건너뜀")
        continue
    start = time.time()
    res = classify_image(path.read_bytes())
    sec = time.time() - start
    total_sec += sec

    found = [i["category"] for i in res.get("items", [])]
    predicted = " + ".join(found) if found else ("오류" if not res["ok"] else "쓰레기 아님")
    expected = row["expected"].strip()
    if "+" in expected:
        # 여러 물건 사진: 적힌 분류가 모두 결과에 있어야 정답 ("/"는 둘 중 하나면 됨)
        hit = all(any(alt.strip() in found for alt in part.split("/")) for part in expected.split("+"))
    else:
        # 물건 하나 사진: 첫 번째 물건 기준 ("/"는 둘 중 하나면 됨)
        hit = bool(found) and found[0] in [alt.strip() for alt in expected.split("/")]
    correct += hit
    results.append({**row, "predicted": predicted, "correct": hit, "seconds": round(sec, 1),
                    "how": res["items"][0]["how"] if res.get("items") else res.get("error", "")})
    print(f"{'O' if hit else 'X'}  {row['filename']:<14} 정답={expected}\n   예측={predicted}  ({sec:.1f}초)")

n = len(results)
if n == 0:
    raise SystemExit("채점한 사진이 없어요. test_images 폴더와 answers.csv의 파일 이름을 확인해 주세요.")
print(f"\n모델: {MODEL}")
print(f"정확도: {correct}/{n} = {correct / n:.0%}   평균 응답시간: {total_sec / n:.1f}초")
if skipped:
    print(f"건너뛴 사진 {len(skipped)}장: {', '.join(skipped)}")

out = Path(f"test_results_{MODEL}.csv")
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)
print(f"상세 결과 저장: {out}  (틀린 사례는 rules.json이나 프롬프트 수정에 활용)")
