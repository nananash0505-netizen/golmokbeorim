# 골목버림

관리사무소 없는 빌라촌을 위한 AI 쓰레기 도우미 (AI+라이프스타일 해커톤)

```
golmok/
├─ backend/    서버 (팀원 2 DB 서버 + 팀원 1 AI 기능)
├─ frontend/   화면 (팀원 3)
└─ .gitignore  .env 등 올리면 안 되는 파일 목록
```

## 처음 한 번만

1. **API 키 넣기**
   `backend/.env.example`을 복사해서 이름을 `.env`로 바꾸고, `ANTHROPIC_API_KEY=` 뒤에 키를 붙여 넣습니다.
   키가 없어도 서버는 켜지고, 사진 분류만 안내 문구가 나옵니다.

2. **필요한 프로그램 설치** (터미널에서)
   ```bash
   cd backend
   python3 -m pip install -r requirements.txt
   ```
   윈도우는 `python3` 대신 `py`를 씁니다.

3. **DB 파일 확인**
   `backend/garbage.db`가 이미 들어 있습니다. 처음부터 다시 만들고 싶으면 `garbage.db`를 지우고 `python3 database.py`를 실행합니다.

## 실행할 때마다

1. **서버 켜기** (터미널은 켜 둔 채로 두세요)
   ```bash
   cd backend
   python3 -m uvicorn main:app --reload
   ```
   브라우저에서 http://localhost:8000/docs 를 열면 API를 하나씩 시험할 수 있습니다.

2. **화면 열기**
   VS Code에서 `frontend` 폴더를 열고 `index.html`을 Live Server로 엽니다.

서버 없이 화면만 보고 싶으면 `frontend/js/api.js` 맨 위의 `USE_MOCK = false`를 `true`로 바꾸세요.

## API 목록

| 주소 | 하는 일 |
|---|---|
| GET `/` | 서버·AI 상태 확인 |
| GET `/stations` | 모음터와 통별 적재율 |
| GET `/bins/{id}/readings` | 통의 최근 24시간 적재율 |
| GET `/bins/{id}/predict` | 가득 찰 예상 시각 |
| GET `/bins/{id}/fault` | 장비 이상 의심 여부 |
| GET `/schedule/today` | 오늘 버릴 수 있는 종류 (rules.json 요일 규칙) |
| GET `/clusters/{id}` | 골목 단지 정보 |
| POST `/clusters/{id}/join` | 빌라 참여 신청 (`building`, `households`) |
| POST `/classify` | 사진 분리배출 안내 (사진 필드 이름 `image`, 호출마다 API 요금 발생) |

## 주의

- `.env`는 절대 GitHub에 올리지 않습니다.
- 지킴이 당번, 무단투기, 참여 현황은 아직 DB에 없어 `frontend/js/features.js`의 예시 데이터를 씁니다.
