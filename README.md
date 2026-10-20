# 🔍 AI Data Insight Builder

> CSV 파일을 업로드하면 AI가 자동으로 데이터를 분석하고, 자연어 질문으로 인사이트를 추출할 수 있는 웹 애플리케이션입니다.

---

## 📸 주요 화면

| 로그인 | 메인 대시보드 |
|---|---|
| 4자리 비밀번호 인증 | CSV 업로드 → AI 자동 분석 → 시각화 |

---

## ✨ 주요 기능

- **CSV 자동 진단** – 인코딩(UTF-8, CP949, EUC-KR), 헤더 위치, 결측치, 중복 행 자동 감지
- **AI 분석 제안** – Gemini AI가 데이터에 맞는 분석 도구 3~5개를 자동 추천
- **12가지 분석 도구** – 순위, 추이, 그룹 비교, 변화율, 분포, 상관관계 등 순수 Pandas 계산
- **자연어 질문(NL Query)** – "2022년 인터넷 사용률 상위 10개국은?" 같은 자연어 질문 지원
- **인터랙티브 차트** – 분석 결과를 즉시 시각화
- **비밀번호 보호** – 4자리 비밀번호로 접근 제한

---

## 🛠️ 기술 스택

| 구분 | 기술 |
|---|---|
| Backend | Python 3, Flask |
| AI | Google Gemini API (`gemini-2.5-flash`) |
| 데이터 처리 | Pandas, NumPy |
| Frontend | Vanilla JS, CSS3 |
| 환경 관리 | python-dotenv |

---

## 📁 프로젝트 구조

```
data-insight-builder/
├── app.py                  # Flask 메인 서버 (라우팅, 인증, API 엔드포인트)
├── tools.py                # 12개 분석 도구 Pandas 구현
├── requirements.txt        # 의존성 목록
├── .env.example            # 환경변수 예시 파일
├── templates/
│   ├── index.html          # 메인 대시보드 페이지
│   └── login.html          # 로그인 페이지
├── static/
│   ├── app.js              # 프론트엔드 로직
│   └── style.css           # 스타일시트
└── data/                   # 샘플 데이터 (세계은행 인터넷 이용률)
```

---

## ⚙️ 설치 및 실행

### 1. 저장소 클론

```bash
git clone https://github.com/k1myoonj/data-insight-builder.git
cd data-insight-builder
```

### 2. 가상환경 생성 및 활성화

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 환경변수 설정

`.env.example`을 복사하여 `.env` 파일을 만들고 API Key를 입력합니다.

```bash
cp .env.example .env
```

```env
# .env
GEMINI_API_KEY=your_gemini_api_key_here   # Google AI Studio에서 발급
GEMINI_MODEL=gemini-2.5-flash
FLASK_DEBUG=true
MAX_UPLOAD_MB=10
APP_PASSWORD=9990                         # 접속 비밀번호 (기본값: 9990)
SECRET_KEY=your-secret-key-here           # Flask 세션 서명 키
```

> Gemini API Key는 [Google AI Studio](https://aistudio.google.com/)에서 무료로 발급받을 수 있습니다.

### 5. 서버 실행

```bash
python app.py
```

브라우저에서 [http://127.0.0.1:5000](http://127.0.0.1:5000) 접속 → 비밀번호 `9990` 입력

---

## 🔑 인증

- 모든 페이지는 **4자리 비밀번호** 인증 후 접근 가능합니다.
- 기본 비밀번호: `9990`
- `.env` 파일의 `APP_PASSWORD` 값으로 변경할 수 있습니다.
- `/health` 엔드포인트는 인증 없이 서버 상태를 확인할 수 있습니다.

---

## 📊 분석 도구 목록 (12가지)

| 도구 | 설명 |
|---|---|
| `top_bottom_n` | 기준연도 상위·하위 N개 순위 비교 |
| `trend_line` | 주요 항목 연도별 시계열 추이 |
| `compare_one_vs_all` | 특정 항목 vs 전체 평균 벤치마크 비교 |
| `group_summary` | 범주별 그룹 평균/중앙값 요약 |
| `distribution` | 특정 연도 전체 분포 및 히스토그램 |
| `change_rate` | 두 시점 간 증감율/성장률 비교 |
| `describe_numeric` | 수치 열 기술통계 요약 |
| `quality_report` | 데이터 품질 종합 보고서 |
| `year_coverage` | 연도별 데이터 충전율 분석 |
| `detect_aggregates` | 집계/그룹 묶음 행 탐지 |
| `correlation_scatter` | 두 수치 열 간 상관관계 분석 |
| `reshape_wide_to_long` | Wide → Long 형식 변환 |

---

## 🌐 API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/` | 메인 대시보드 |
| `GET` | `/health` | 서버 상태 확인 (인증 불필요) |
| `GET/POST` | `/login` | 로그인 |
| `GET` | `/logout` | 로그아웃 |
| `POST` | `/inspect` | CSV 업로드 및 자동 진단 |
| `POST` | `/suggest` | AI 분석 도구 추천 |
| `POST` | `/run` | 분석 도구 실행 |
| `POST` | `/explain` | 분석 결과 AI 해석 리포트 |
| `POST` | `/ask` | 자연어 질문 |
| `POST` | `/chat` | 후속 대화 |

---

## 📋 환경변수 목록

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | (필수) | Google Gemini API 키 |
| `GEMINI_MODEL` | `gemini-2.5-flash` | 사용할 Gemini 모델명 |
| `FLASK_DEBUG` | `true` | Flask 디버그 모드 |
| `MAX_UPLOAD_MB` | `10` | 최대 CSV 업로드 크기 (MB) |
| `APP_PASSWORD` | `9990` | 접속 비밀번호 |
| `SECRET_KEY` | (내부 기본값) | Flask 세션 서명 키 |

---

## ⚠️ 주의사항

- 업로드된 CSV 파일은 **서버 메모리에만 임시 보관**되며, 서버 재시작 시 삭제됩니다.
- 개발 서버(`FLASK_DEBUG=true`)는 **개인/학습 환경 전용**입니다. 실 서비스 배포 시 Gunicorn 등 WSGI 서버를 사용하세요.
- `.env` 파일은 절대 Git에 커밋하지 마세요. (`.gitignore`에 이미 포함됨)

---

## 📄 라이선스

본 프로젝트는 학습 및 교육 목적으로 제작되었습니다.

---

<p align="center">Made with ❤️ using Flask + Google Gemini AI</p>
