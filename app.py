import os
import io
import csv
import glob
import json
import logging
import math
import pandas as pd
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from dotenv import load_dotenv
from google import genai
from google.genai import types

import tools

# 환경변수 로드
load_dotenv()

# Backend Log 설정 (Python logging 모듈 사용, print() 배제)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("data-insight-builder")

app = Flask(__name__)

# 업로드 최대 용량 설정 (MB 단위)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# ── 인증 설정 ──────────────────────────────────────────────
app.secret_key = os.getenv("SECRET_KEY", "data-insight-builder-secret-2024")
APP_PASSWORD   = os.getenv("APP_PASSWORD", "9990")

# 인증이 필요 없는 엔드포인트 목록
_PUBLIC_ENDPOINTS = {"login", "logout", "health", "static"}

@app.before_request
def require_login():
    """인증되지 않은 요청은 로그인 페이지로 리다이렉트"""
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return  # 공개 엔드포인트는 통과
    if not session.get("authenticated"):
        # API 요청(JSON)이면 401, 일반 페이지 요청이면 리다이렉트
        if request.is_json or request.path.startswith("/api"):
            return jsonify({"error": "로그인이 필요합니다."}), 401
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    """로그인 페이지 – GET: 폼 표시, POST: 비밀번호 검증"""
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "").strip()
        if pw == APP_PASSWORD:
            session["authenticated"] = True
            logger.info("[AUTH] 로그인 성공")
            return redirect(url_for("index"))
        else:
            error = "비밀번호가 올바르지 않습니다."
            logger.warning("[AUTH] 비밀번호 오류")
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    """세션 초기화 후 로그인 페이지로 이동"""
    session.clear()
    logger.info("[AUTH] 로그아웃")
    return redirect(url_for("login"))
# ─────────────────────────────────────────────────────────



@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# 메모리 기반 데이터셋 보관소 (디스크 영구 저장 금지, 1개 데이터셋만 보관)
CURRENT_DATASET = {
    "df": None,
    "filename": None,
    "file_size": 0,
    "encoding": None,
    "skiprows": 0,
    "inspect_result": None,
    "last_run_result": None,   # /explain에서 참조할 최근 계산 결과
    "last_report_markdown": "", # 대화창에서 참조할 최근 보고서 본문
    "last_report_mode": "B"
}

# 12개 분석 도구 함수 디스패처 맵
TOOL_DISPATCHER = {
    "reshape_wide_to_long": tools.reshape_wide_to_long,
    "quality_report": tools.quality_report,
    "year_coverage": tools.year_coverage,
    "detect_aggregates": tools.detect_aggregates,
    "describe_numeric": tools.describe_numeric,
    "trend_line": tools.trend_line,
    "top_bottom_n": tools.top_bottom_n,
    "group_summary": tools.group_summary,
    "change_rate": tools.change_rate,
    "distribution": tools.distribution,
    "correlation_scatter": tools.correlation_scatter,
    "compare_one_vs_all": tools.compare_one_vs_all
}

def detect_encoding_and_header(raw_bytes):
    """인코딩(utf-8-sig, utf-8, cp949, euc-kr) 순차 시도 및 헤더 줄 자동 감지"""
    encodings = ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']
    decoded_text = None
    successful_encoding = None

    for enc in encodings:
        try:
            decoded_text = raw_bytes.decode(enc)
            successful_encoding = enc
            logger.info(f"[ENCODING] {enc} 성공")
            break
        except (UnicodeDecodeError, LookupError) as e:
            logger.info(f"[ENCODING] {enc} 실패: {e}")
            continue

    if not decoded_text:
        return None, None, None, "지원하는 인코딩(utf-8-sig, utf-8, cp949, euc-kr)으로 파일을 읽을 수 없습니다."

    lines = decoded_text.splitlines()
    if not lines or all(not line.strip() for line in lines):
        return None, None, None, "업로드된 파일이 비어 있습니다."

    parsed_sample = []
    for line in lines[:25]:
        if line.strip():
            try:
                row = next(csv.reader([line]))
                parsed_sample.append(row)
            except Exception:
                continue

    if not parsed_sample:
        return successful_encoding, 0, decoded_text, None

    max_cols = max((len([c for c in r if c.strip()]) for r in parsed_sample), default=0)

    header_row_index = 0
    target_row = None
    for r in parsed_sample:
        valid_cells = [c.strip() for c in r if c.strip()]
        if len(valid_cells) == max_cols and max_cols > 1:
            target_row = r
            break

    if target_row is not None:
        for line_idx, line in enumerate(lines[:25]):
            if line.strip():
                try:
                    row = next(csv.reader([line]))
                    if row == target_row:
                        header_row_index = line_idx
                        break
                except Exception:
                    continue

    logger.info(f"[HEADER] 헤더 줄 감지 완료 (건너뛴 줄 수: {header_row_index})")
    return successful_encoding, header_row_index, decoded_text, None

def sanitize_value_for_json(val):
    """NaN, Infinity 등을 JSON 표준 안전 값(None 또는 문자열)으로 변환"""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (float, int)):
        if math.isinf(val) or math.isnan(val):
            return None
    return val

def get_indicator_metadata():
    """메타데이터 지표 파일이 있으면 정의 및 출처 반환"""
    meta_files = glob.glob("data/**/Metadata_Indicator*.csv", recursive=True)
    if meta_files:
        try:
            with open(meta_files[0], 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    return {
                        "name": r.get("INDICATOR_NAME", ""),
                        "definition": r.get("SOURCE_NOTE", ""),
                        "source": r.get("SOURCE_ORGANIZATION", "")
                    }
        except Exception:
            pass
    return {
        "name": "인터넷 이용률 (% of population)",
        "definition": "지난 3개월 동안 어떤 장소에서든 컴퓨터, 휴대폰, TV 등을 통해 인터넷을 사용한 개인의 비율 (ITU 표준)",
        "source": "세계은행(World Bank) / 국제전기통신연합(ITU)"
    }

@app.route("/", methods=["GET"])
def index():
    logger.info("[REQUEST] GET /")
    template_path = os.path.join(app.template_folder, "index.html")
    if os.path.exists(template_path):
        return render_template("index.html")
    return jsonify({
        "status": "ok",
        "message": "AI Data Insight Builder API 서버가 동작 중입니다.",
        "health_check": "/health",
        "inspect_endpoint": "/inspect",
        "suggest_endpoint": "/suggest",
        "run_endpoint": "/run",
        "explain_endpoint": "/explain",
        "chat_endpoint": "/chat"
    }), 200

@app.route("/health", methods=["GET"])
def health():
    """서버 상태와 Gemini API Key 설정 여부만 반환 (보안 규칙 준수)"""
    logger.info("[REQUEST] GET /health")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    has_api_key = bool(api_key and api_key != "your_gemini_api_key_here")

    response_data = {
        "status": "healthy",
        "gemini_api_key_configured": has_api_key,
        "gemini_model": model,
        "max_upload_mb": MAX_UPLOAD_MB
    }
    logger.info(f"[RESPONSE] status=200 has_api_key={has_api_key} model={model}")
    return jsonify(response_data), 200

@app.route("/inspect", methods=["POST"])
def inspect():
    """CSV 업로드 2차 종합 진단"""
    logger.info("[REQUEST] POST /inspect")
    warnings = []

    if 'file' not in request.files:
        logger.warning("[ERROR] 파일 미선택")
        return jsonify({"error": "업로드할 CSV 파일을 선택해 주세요."}), 400

    file = request.files['file']
    filename = file.filename or ""
    if not filename:
        logger.warning("[ERROR] 파일명 공백")
        return jsonify({"error": "업로드할 CSV 파일을 선택해 주세요."}), 400

    if not filename.lower().endswith('.csv'):
        logger.warning(f"[ERROR] CSV 파일 아님: {filename}")
        return jsonify({"error": "CSV 형식(.csv)의 파일만 업로드할 수 있습니다."}), 400

    raw_bytes = file.read()
    file_size = len(raw_bytes)
    logger.info(f"[FILE] name={filename} size={file_size} bytes")

    if file_size == 0:
        logger.warning("[ERROR] 빈 파일")
        return jsonify({"error": "업로드된 파일이 비어 있습니다."}), 400

    if file_size > MAX_UPLOAD_MB * 1024 * 1024:
        logger.warning(f"[ERROR] 용량 초과: {file_size} bytes")
        return jsonify({"error": f"파일 크기가 너무 큽니다. (최대 {MAX_UPLOAD_MB}MB까지 허용)"}), 413

    encoding, skiprows, decoded_text, err = detect_encoding_and_header(raw_bytes)
    if err:
        logger.warning(f"[ERROR] 인코딩/헤더 감지 실패: {err}")
        return jsonify({"error": err}), 400

    if skiprows > 0:
        warnings.append(f"상단 {skiprows}개 행의 안내/메모 문구를 자동으로 건너뛰고 진짜 표 제목 행을 찾았습니다.")

    try:
        df = pd.read_csv(io.StringIO(decoded_text), skiprows=skiprows)
    except Exception as e:
        logger.error(f"[ERROR] CSV 파싱 오류: {e}", exc_info=True)
        return jsonify({"error": f"CSV 파일을 표로 변환하는 중 오류가 발생했습니다: {str(e)}"}), 400

    total_rows = int(len(df))
    total_cols = int(len(df.columns))
    logger.info(f"[CSV] parsing 완료 rows={total_rows} columns={total_cols}")

    str_cols = [str(c) for c in df.columns]
    year_columns = [col for col in str_cols if col.strip().isdigit() and 1800 <= int(col.strip()) <= 2100]

    date_keywords = ['date', 'year', 'dt', 'time', '연도', '일자', '날짜', '기간']
    date_candidate_columns = [
        col for col in str_cols
        if any(dk in col.lower() for dk in date_keywords) and col not in year_columns
    ]

    numeric_columns = [col for col in str_cols if pd.api.types.is_numeric_dtype(df[col])]
    string_columns = [col for col in str_cols if col not in numeric_columns]

    missing_stats = {}
    unnamed_cols = []
    all_na_cols = []

    for col in str_cols:
        col_series = df[col]
        na_count = int(col_series.isna().sum())
        na_ratio = round((na_count / total_rows * 100), 2) if total_rows > 0 else 0.0
        missing_stats[col] = {
            "missing_count": na_count,
            "missing_ratio": na_ratio
        }

        if col.startswith("Unnamed:") or not col.strip():
            unnamed_cols.append(col)
        if na_count == total_rows:
            all_na_cols.append(col)

    if unnamed_cols:
        warnings.append(f"이름이 없거나 빈 열이 {len(unnamed_cols)}개 감지되었습니다. (예: {unnamed_cols[:3]})")
    if all_na_cols:
        warnings.append(f"모든 데이터가 비어 있는 열이 {len(all_na_cols)}개 있습니다.")

    duplicate_rows = int(df.duplicated().sum())
    if duplicate_rows > 0:
        warnings.append(f"내용이 완전히 일치하는 중복 행이 {duplicate_rows}개 있습니다.")

    year_coverage = []
    recommended_reference_year = None

    if year_columns:
        for y in year_columns:
            filled_count = int(df[y].notna().sum())
            filled_ratio = round((filled_count / total_rows * 100), 2) if total_rows > 0 else 0.0
            year_coverage.append({
                "year": y,
                "filled_count": filled_count,
                "filled_ratio": filled_ratio
            })

        max_filled = max((item["filled_count"] for item in year_coverage), default=0)
        solid_years = [
            item["year"] for item in year_coverage
            if item["filled_count"] >= max_filled * 0.75
        ]
        recommended_reference_year = solid_years[-1] if solid_years else year_columns[-1]

        latest_year_info = year_coverage[-1]
        if latest_year_info["year"] != recommended_reference_year and latest_year_info["filled_ratio"] < 40:
            warnings.append(
                f"최신 연도인 {latest_year_info['year']}년은 데이터가 {latest_year_info['filled_ratio']}%만 채워져 있어 불완전합니다. "
                f"충분한 통계가 확보된 '{recommended_reference_year}년'을 기준연도로 권장합니다."
            )

    agg_keywords = [
        'world', 'oecd members', 'euro area', 'european union',
        'high income', 'low income', 'income', 'area', 'total',
        '합계', '전국', '전체', '평균'
    ]
    aggregate_candidates = []
    label_col = string_columns[0] if string_columns else None
    if label_col:
        for idx, val in df[label_col].dropna().items():
            str_val = str(val).strip()
            if any(kw in str_val.lower() for kw in agg_keywords):
                aggregate_candidates.append({
                    "index": int(idx),
                    "label": str_val
                })

    if aggregate_candidates:
        sample_names = [item["label"] for item in aggregate_candidates[:3]]
        warnings.append(
            f"전체 평균이나 순위를 왜곡할 수 있는 집계/그룹 묶음 행 후보가 {len(aggregate_candidates)}개 감지되었습니다. "
            f"(예: {', '.join(sample_names)} 등)"
        )

    preview_df = df.head(10).copy()
    preview_records = []
    for _, row in preview_df.iterrows():
        record = {str(k): sanitize_value_for_json(v) for k, v in row.items()}
        preview_records.append(record)

    CURRENT_DATASET["df"] = df
    CURRENT_DATASET["filename"] = filename
    CURRENT_DATASET["file_size"] = file_size
    CURRENT_DATASET["encoding"] = encoding
    CURRENT_DATASET["skiprows"] = skiprows

    column_dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}

    inspect_result = {
        "status": "success",
        "file_info": {
            "filename": filename,
            "file_size_bytes": file_size,
            "file_size_kb": round(file_size / 1024, 2),
            "encoding": encoding,
            "skiprows": skiprows
        },
        "dimensions": {
            "rows": total_rows,
            "columns": total_cols
        },
        "columns": str_cols,
        "dtypes": column_dtypes,
        "column_categories": {
            "numeric_columns": numeric_columns,
            "string_columns": string_columns,
            "year_columns": year_columns,
            "date_candidate_columns": date_candidate_columns
        },
        "missing_stats": missing_stats,
        "duplicate_rows": duplicate_rows,
        "unnamed_or_empty_columns": unnamed_cols,
        "year_coverage": year_coverage,
        "recommended_reference_year": recommended_reference_year,
        "aggregate_candidates": aggregate_candidates,
        "preview": preview_records,
        "warnings": warnings,
        "memory_notice": "업로드된 데이터는 서버 메모리에만 임시 보관되며, 서버를 재시작하면 사라집니다."
    }

    CURRENT_DATASET["inspect_result"] = inspect_result
    logger.info(f"[DIAGNOSE] 종합 진단 완료 rows={total_rows} cols={total_cols} warnings={len(warnings)}")
    logger.info("[RESPONSE] status=200")
    return jsonify(inspect_result), 200

@app.route("/suggest", methods=["POST"])
def suggest():
    """Gemini API에 진단 요약과 도구 카탈로그를 전달하여 실행 가능한 분석 도구 3~5개를 JSON으로 제안받음"""
    logger.info("[REQUEST] POST /suggest")

    if CURRENT_DATASET["df"] is None or CURRENT_DATASET["inspect_result"] is None:
        logger.warning("[ERROR] 진단 선행되지 않음")
        return jsonify({"error": "먼저 CSV 파일을 업로드하고 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    if not api_key or api_key == "your_gemini_api_key_here":
        logger.warning("[ERROR] API Key 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 유효한 API Key를 입력해 주세요."}), 400

    inspect_res = CURRENT_DATASET["inspect_result"]
    tool_catalog = tools.get_tool_catalog()
    allowed_tool_names = {t["name"] for t in tool_catalog}

    diag_summary = {
        "filename": inspect_res["file_info"]["filename"],
        "rows": inspect_res["dimensions"]["rows"],
        "columns_count": inspect_res["dimensions"]["columns"],
        "sample_columns": inspect_res["columns"][:10],
        "year_columns_count": len(inspect_res["column_categories"]["year_columns"]),
        "year_range": {
            "start": inspect_res["column_categories"]["year_columns"][0] if inspect_res["column_categories"]["year_columns"] else None,
            "end": inspect_res["column_categories"]["year_columns"][-1] if inspect_res["column_categories"]["year_columns"] else None
        },
        "recommended_reference_year": inspect_res["recommended_reference_year"],
        "aggregate_candidates_count": len(inspect_res["aggregate_candidates"]),
        "warnings": inspect_res["warnings"]
    }

    catalog_for_prompt = [
        {
            "name": t["name"],
            "title": t["title"],
            "description": t["description"],
            "requires_reference_period": t["requires_reference_period"]
        }
        for t in tool_catalog
    ]

    prompt = f"""당신은 교육용 데이터 분석 웹앱의 수석 데이터 분석가입니다.
사용자가 업로드한 CSV 데이터셋의 진단 요약을 확인하고, 등록된 '도구 카탈로그' 중에서 가장 통계적 가치가 높은 분석 3~5개를 골라 제안해 주세요.

[데이터셋 진단 요약]
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}

[등록된 도구 카탈로그]
{json.dumps(catalog_for_prompt, ensure_ascii=False, indent=2)}

[절대 규칙]
1. 반드시 위에 나열된 카탈로그의 'name'에 있는 도구만 제안해야 합니다. (카탈로그 외 도구 제안 절대 금지)
2. 기준연도가 필요한 도구는 반드시 권장 기준연도인 '{inspect_res["recommended_reference_year"]}'를 reference_period로 지정하세요.
3. 분석 가치가 높은 3~5개의 서로 다른 유형(순위, 추이, 그룹 비교, 변화율 등)을 골고루 제안하세요.
4. why(추천 이유)와 caution(주의할 점)은 중학생도 쉽게 이해할 수 있는 친절한 한국어로 작성하세요.
5. 오직 아래 JSON 형식으로만 응답해야 합니다. 마크다운 등 기타 텍스트는 포함하지 마세요.

{{
  "suggestions": [
    {{
      "tool": "카탈로그의_도구_name",
      "params": {{
        "reference_period": "{inspect_res["recommended_reference_year"]}",
        "exclude_aggregates": true
      }},
      "reference_period": "{inspect_res["recommended_reference_year"]}",
      "why": "이 분석이 이 데이터에서 의미 있는 이유",
      "caution": "해석할 때 주의할 점"
    }}
  ]
}}
"""

    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        logger.info(f"[AI] suggest 응답 수신 (응답 길이: {len(response.text)} 글자)")
    except Exception as e:
        logger.error(f"[ERROR] Gemini API 호출 오류: {e}", exc_info=True)
        return jsonify({"error": f"Gemini API 호출 중 오류가 발생했습니다: {str(e)}"}), 500

    try:
        parsed_data = json.loads(response.text)
        raw_suggestions = parsed_data.get("suggestions", [])
    except Exception as e:
        logger.error(f"[ERROR] Gemini 응답 JSON 파싱 실패: {e}\n응답 원문: {response.text}")
        return jsonify({"error": "AI가 반환한 제안 목록을 JSON 형식으로 해석하는 데 실패했습니다."}), 500

    validated_suggestions = []
    for sug in raw_suggestions:
        tool_name = sug.get("tool")
        if tool_name in allowed_tool_names:
            tool_meta = next((t for t in tool_catalog if t["name"] == tool_name), None)
            sug["title"] = tool_meta["title"] if tool_meta else tool_name
            if "params" not in sug or not isinstance(sug["params"], dict):
                sug["params"] = {}
            if "reference_period" not in sug["params"] and sug.get("reference_period"):
                sug["params"]["reference_period"] = sug["reference_period"]
            validated_suggestions.append(sug)
        else:
            logger.warning(f"[AI] 카탈로그에 없는 도구 제안 무시: {tool_name}")

    if not validated_suggestions:
        validated_suggestions = [
            {
                "tool": "top_bottom_n",
                "title": "기준연도 상위·하위 랭킹 비교",
                "params": {"reference_period": inspect_res["recommended_reference_year"], "n": 10, "exclude_aggregates": True},
                "reference_period": inspect_res["recommended_reference_year"],
                "why": f"{inspect_res['recommended_reference_year']}년 인터넷 사용률 상위 및 하위 국가 순위를 비교합니다.",
                "caution": "인구 규모가 작은 도시 국가의 특수성과 결측치를 함께 고려해야 합니다."
            },
            {
                "tool": "trend_line",
                "title": "주요 항목 연도별 시계열 추이 비교",
                "params": {"items": ["Korea, Rep.", "United States", "Japan"], "exclude_aggregates": False},
                "reference_period": f"1990-{inspect_res['recommended_reference_year']}",
                "why": "주요 국가들의 지난 30년간 디지털 발전 흐름을 시계열로 확인합니다.",
                "caution": "과거 특정 연도에 조사가 누락된 결측 구간에 유의해야 합니다."
            },
            {
                "tool": "compare_one_vs_all",
                "title": "특정 항목 vs 전체 평균 벤치마크 비교",
                "params": {"target_item": "Korea, Rep.", "reference_period": inspect_res["recommended_reference_year"], "exclude_aggregates": True},
                "reference_period": inspect_res["recommended_reference_year"],
                "why": f"대한민국의 {inspect_res['recommended_reference_year']}년 수치를 전 세계 평균 및 중앙값과 1:1로 비교합니다.",
                "caution": "전체 평균은 소국과 대국을 1:1로 가중한 단순 평균입니다."
            }
        ]

    logger.info(f"[AI] JSON 파싱 완료 (제안 개수: {len(validated_suggestions)})")
    logger.info("[RESPONSE] status=200")

    return jsonify({
        "status": "success",
        "recommended_reference_year": inspect_res["recommended_reference_year"],
        "suggestions": validated_suggestions
    }), 200

@app.route("/ask", methods=["POST"])
def ask_question():
    """자연어 질문을 받아 도구 매핑 및 Pandas 계산을 수행하고, 데이터에 근거한 답변과 시각화 결과를 반환"""
    logger.info("[REQUEST] POST /ask")

    if CURRENT_DATASET["df"] is None:
        logger.warning("[ERROR] 데이터셋 미업로드 상태에서 /ask 요청")
        return jsonify({"error": "먼저 CSV 파일을 업로드해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 유효한 API Key를 입력해 주세요."}), 400

    data = request.get_json(silent=True) or {}
    user_question = data.get("question", "").strip()
    if not user_question:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    df = CURRENT_DATASET["df"]
    inspect_res = CURRENT_DATASET["inspect_result"] or {}
    tool_catalog = tools.get_tool_catalog()
    allowed_tool_names = {t["name"] for t in tool_catalog}

    client = genai.Client(api_key=api_key)
    year_columns = inspect_res.get("column_categories", {}).get("year_columns", [])
    rec_year = inspect_res.get("recommended_reference_year", "")
    id_col = inspect_res.get("column_categories", {}).get("identifier_column", "")
    sample_items = [str(x) for x in df[id_col].dropna().head(10).tolist()] if id_col and id_col in df.columns else []

    # 1단계: 사용자 자연어 질문 의도 파악 및 도구/파라미터 추출
    intent_prompt = f"""당신은 데이터 분석 시스템의 쿼리 라우터입니다.
사용자가 업로드된 데이터셋에 대해 다음과 같은 자연어 질문을 하였습니다.

[사용자 질문]:
"{user_question}"

[데이터셋 메타정보]:
- 가용 연도 열 목록: {year_columns[-15:] if len(year_columns) > 15 else year_columns}
- 추천 기준연도: {rec_year}
- 주요 식별자(국가/항목) 열: {id_col}
- 일부 항목 예시: {sample_items}

[사용 가능한 분석 도구 카탈로그]:
1. top_bottom_n: 기준 시점(reference_period) 상위·하위 N개 순위 비교 (params: reference_period, n, exclude_aggregates=True)
2. compare_one_vs_all: 특정 대상(target_item)과 전체 평균/중앙값 및 순위 비교 (params: reference_period, target_item, exclude_aggregates=True)
3. trend_line: 주요 항목들의 연도별 시계열 추이 비교 (params: items, exclude_aggregates=False)
4. group_summary: 범주별 그룹 평균/중앙값 요약 (params: reference_period, group_column, exclude_aggregates=True)
5. distribution: 특정 연도의 전체 분포 및 히스토그램 (params: reference_period, bins=10, exclude_aggregates=True)
6. change_rate: 두 시점 간 증감율/성장률 비교 (params: reference_period, base_period, n=10, exclude_aggregates=True)
7. describe_numeric: 특정 수치 열 기술통계 (params: column)

[규칙]:
1. 질문의 의도에 가장 적합한 도구 1개를 선택하세요.
   - 예: "2024년 상위 10개국과 한국 위치" -> tool: "top_bottom_n", params: {{"reference_period": "2024", "n": 10, "exclude_aggregates": true}}, target_items: ["Korea, Rep.", "Korea", "대한민국"]
2. 사용자가 언급한 연도가 가용 연도 열에 없으면, 가장 최근의 가용 연도(예: {rec_year})를 reference_period로 지정하세요.
3. 반드시 아래 JSON 형식으로만 응답하세요:
{{
  "tool": "선택한 도구명",
  "params": {{ ... }},
  "target_items": ["언급된 특정 국가/항목명 (없으면 빈 배열)"],
  "intent_summary": "질문 의도 한 줄 요약"
}}
"""
    try:
        intent_res = client.models.generate_content(
            model=model_name,
            contents=intent_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        parsed_intent = json.loads(intent_res.text)
        tool_name = parsed_intent.get("tool", "top_bottom_n")
        params = parsed_intent.get("params", {}) or {}
        target_items = parsed_intent.get("target_items", []) or []
    except Exception as e:
        logger.warning(f"[AI] 의도 파악 실패, 기본 top_bottom_n 적용: {e}")
        tool_name = "top_bottom_n"
        params = {"reference_period": rec_year, "n": 10, "exclude_aggregates": True}
        target_items = ["Korea, Rep."]

    if tool_name not in allowed_tool_names:
        tool_name = "top_bottom_n"

    # 연도 컬럼 안전성 검증
    year_cols = [c for c in df.columns if str(c).strip().isdigit() and 1800 <= int(str(c).strip()) <= 2100]
    fallback_year = rec_year if (rec_year and rec_year in df.columns) else (year_cols[-1] if year_cols else None)

    ref_p = params.get("reference_period")
    if not ref_p or str(ref_p) not in df.columns:
        params["reference_period"] = fallback_year

    # 2단계: Pandas로 엄격한 통계 계산 수행
    tool_func = TOOL_DISPATCHER[tool_name]
    try:
        run_output = tool_func(df, **params)
    except Exception as e:
        logger.warning(f"[TOOL] 파라미터 보정 후 재시도: {e}")
        params = {"reference_period": fallback_year, "n": 10, "exclude_aggregates": True}
        run_output = tools.top_bottom_n(df, **params)
        tool_name = "top_bottom_n"

    # 추가 팩트: 특정 국가(예: 한국) 순위 및 수치 별도 계산 (질문에 언급되었을 경우)
    target_stats = []
    val_col = params.get("reference_period")
    if val_col and val_col in df.columns:
        filtered_df, _, _ = tools.filter_dataframe(df, exclude_aggregates=True)
        s_num = pd.to_numeric(filtered_df[val_col], errors='coerce')
        valid_df = filtered_df[s_num.notna()].copy()
        valid_df["_val"] = s_num[s_num.notna()]
        valid_df_sorted = valid_df.sort_values(by="_val", ascending=False).reset_index(drop=True)
        total_valid_count = len(valid_df_sorted)

        label_col = tools.detect_label_column(df)
        search_targets = target_items if target_items else ["Korea, Rep.", "Korea", "대한민국"]
        for target in search_targets:
            matches = valid_df_sorted[valid_df_sorted[label_col].astype(str).str.lower().str.contains(target.lower())]
            if not matches.empty:
                for idx, row in matches.iterrows():
                    target_stats.append({
                        "name": str(row[label_col]),
                        "rank": int(idx) + 1,
                        "total_count": int(total_valid_count),
                        "value": float(round(row["_val"], 4)),
                        "percentile": float(round((total_valid_count - (idx + 1) + 1) / total_valid_count * 100, 2)),
                        "reference_period": str(val_col)
                    })
                break

    # 최근 실행 결과로 저장 (시각화 버튼 클릭 시 즉시 활용)
    CURRENT_DATASET["last_run_result"] = run_output

    # 3단계: Pandas 계산 통계 팩트만을 주입하여 자연어 답변 생성
    indicator_meta = get_indicator_metadata()
    answer_prompt = f"""당신은 데이터 인사이트 빌더의 전문 데이터 분석가입니다.
사용자가 업로드된 데이터셋에 대해 자연어 질문을 하였고, 우리 시스템의 Pandas 엔진이 실제 데이터를 계산한 통계 결과가 아래에 나와 있습니다.

[사용자 질문]:
"{user_question}"

[지표 정의 및 단위]:
- 지표명: {indicator_meta['name']} ({indicator_meta['definition']})
- 출처: {indicator_meta['source']}

[Pandas 실제 계산 통계 결과]:
- 실행된 분석 도구: {tool_name}
- 적용된 기준 시점: {run_output.get('reference_period')}
- 계산에 포함된 유효 데이터 수: {run_output.get('used_rows')}개국
- 제외된 집계/결측 행 수: {run_output.get('excluded_rows')}개 ({', '.join(run_output.get('excluded_reasons', []))})
- 도구 계산 결과 상세: {json.dumps(run_output.get('result', {}), ensure_ascii=False)}
- 특정 언급 대상(한국 등) 별도 계산 결과: {json.dumps(target_stats, ensure_ascii=False)}
- 도구 주의사항: {run_output.get('caution', '')}

[답변 작성 절대 원칙]:
1. 오직 위에 제공된 Pandas 실제 계산 결과의 숫자만 언급하세요. 임의로 숫자를 지어내거나 추측하지 마세요.
2. 질문에서 한국(대한민국)의 위치를 물어보았다면, 특정 언급 대상 별도 계산 결과에 나온 실제 순위(예: 전체 N개국 중 M위, 상위 X%)와 수치를 명확하고 친절하게 알려주세요.
3. 상위 10개국 순위와 수치를 보기 좋은 마크다운 표나 리스트로 깔끔하게 정리해 주세요.
4. 사용자가 요청한 연도와 실제 분석 연도가 다를 경우(예: 최신 가용 연도 적용 등) 그 이유를 투명하게 밝혀주세요.
5. 데이터로 알 수 없는 원인(왜 높은지 등)은 '이 데이터로는 확인할 수 없다'고 분명히 선을 긋고, 버뮤다/쿠웨이트 등 소국이나 특수 표본에 대한 통계적 유의점을 덧붙이세요.
6. 답변 마지막에는 자연스럽게 아래의 시각화 버튼을 통해 인터랙티브 차트와 정식 A/B 보고서를 확인할 수 있음을 안내하세요.
"""
    try:
        answer_res = client.models.generate_content(
            model=model_name,
            contents=answer_prompt
        )
        answer_markdown = answer_res.text
        logger.info(f"[AI] ask 답변 수신 (길이: {len(answer_markdown)}자)")
    except Exception as e:
        logger.error(f"[ERROR] 자연어 답변 생성 오류: {e}", exc_info=True)
        return jsonify({"error": f"답변 생성 중 오류가 발생했습니다: {str(e)}"}), 500

    response_payload = {
        "status": "success",
        "success": True,
        "question": user_question,
        "answer_markdown": answer_markdown,
        "tool": tool_name,
        "params": params,
        "run_result": run_output
    }
    logger.info("[RESPONSE] status=200")
    return jsonify(response_payload), 200

@app.route("/run", methods=["POST"])
def run_tool():
    """선택된 분석 도구를 Pandas 엔진으로 실행, 계산 결과 및 차트 데이터 반환"""
    logger.info("[REQUEST] POST /run")

    if CURRENT_DATASET["df"] is None:
        logger.warning("[ERROR] 데이터셋 미업로드 상태에서 /run 요청")
        return jsonify({"error": "먼저 CSV 파일을 업로드해 주세요."}), 400

    df = CURRENT_DATASET["df"]
    data = request.get_json(silent=True) or {}
    tool_name = data.get("tool", "").strip()
    params = data.get("params", {}) or {}

    if "reference_period" in data and "reference_period" not in params:
        params["reference_period"] = data["reference_period"]

    if not tool_name or tool_name not in TOOL_DISPATCHER:
        logger.warning(f"[ERROR] 도구 목록에 없는 도구 요청: {tool_name}")
        return jsonify({"error": f"'{tool_name}'은(는) 지원되지 않는 도구입니다. 카탈로그에 등록된 도구를 선택해 주세요."}), 400

    tool_func = TOOL_DISPATCHER[tool_name]

    requires_ref_period_tools = [
        "top_bottom_n", "group_summary", "change_rate",
        "distribution", "correlation_scatter", "compare_one_vs_all"
    ]
    if tool_name in requires_ref_period_tools:
        ref_period = params.get("reference_period")
        if not ref_period or str(ref_period).strip() == "":
            rec_year = CURRENT_DATASET["inspect_result"].get("recommended_reference_year") if CURRENT_DATASET["inspect_result"] else None
            if rec_year:
                params["reference_period"] = rec_year
                logger.info(f"[TOOL] reference_period 미입력으로 권장 기준연도({rec_year}) 자동 적용")
            else:
                logger.warning(f"[ERROR] {tool_name}에 기준 시점(reference_period) 누락")
                return jsonify({"error": f"'{tool_name}' 도구를 실행하려면 'reference_period(기준 시점)'가 필수입니다."}), 400

    try:
        run_output = tool_func(df, **params)
    except ValueError as ve:
        logger.warning(f"[ERROR] 도구 파라미터 유효성 검증 오류: {ve}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 중 계산 오류: {e}", exc_info=True)
        return jsonify({"error": f"도구 실행 중 오류가 발생했습니다: {str(e)}"}), 500

    used_rows = run_output.get("used_rows", 0)
    excluded_rows = run_output.get("excluded_rows", 0)
    ref_period_val = run_output.get("reference_period")

    logger.info(f"[TOOL] {tool_name}, params={params}, used_rows={used_rows}, excluded_rows={excluded_rows}")

    CURRENT_DATASET["last_run_result"] = run_output

    response_data = {
        "status": "success",
        "tool": tool_name,
        "reference_period": ref_period_val,
        "used_rows": used_rows,
        "excluded_rows": excluded_rows,
        "excluded_reasons": run_output.get("excluded_reasons", []),
        "used_columns": run_output.get("used_columns", []),
        "unit": run_output.get("unit", ""),
        "caution": run_output.get("caution", ""),
        "result": run_output.get("result"),
        "chart_data": run_output.get("chart_data")
    }

    logger.info("[RESPONSE] status=200")
    return jsonify(response_data), 200

@app.route("/explain", methods=["POST"])
def explain():
    """/run의 계산 결과만 Gemini에 전달하여 해석 리포트 반환 (모드 A/B 구현)"""
    logger.info("[REQUEST] POST /explain")

    if CURRENT_DATASET["df"] is None:
        return jsonify({"error": "먼저 CSV 파일을 업로드해 주세요."}), 400

    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "B")).strip().upper()
    if mode not in ("A", "B"):
        mode = "B"

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 유효한 API Key를 입력해 주세요."}), 400

    client = genai.Client(api_key=api_key)
    inspect_res = CURRENT_DATASET["inspect_result"] or {}
    indicator_meta = get_indicator_metadata()

    # 모드 A (비교용): 계산 결과를 주지 않음
    if mode == "A":
        logger.info(f"[AI] explain 요청 시작 (mode=A, model={model_name})")
        diag_brief = {"filename": CURRENT_DATASET["filename"], "rows": inspect_res.get("dimensions", {}).get("rows")}
        prompt_a = f"데이터셋 요약: {json.dumps(diag_brief)}\n이 데이터셋에 대한 분석 보고서를 작성해 주세요. (주의: 실제 구체적인 계산 결과는 주어지지 않았습니다.)"
        res_a = client.models.generate_content(model=model_name, contents=prompt_a)
        CURRENT_DATASET["last_report_markdown"] = res_a.text
        CURRENT_DATASET["last_report_mode"] = "A"
        return jsonify({"status": "success", "mode": "A", "report_markdown": res_a.text}), 200

    # 모드 B (정식): Pandas 계산 결과만 전달 + 8대 규칙 강제
    last_run = CURRENT_DATASET["last_run_result"]
    if not last_run:
        logger.warning("[ERROR] /run 계산 결과 없음")
        return jsonify({"error": "먼저 분석 도구를 실행(/run)하여 계산 결과를 생성해 주세요."}), 400

    tool_name = last_run.get("tool", "")
    ref_period = last_run.get("reference_period", "N/A")
    used_rows = last_run.get("used_rows", 0)
    excluded_rows = last_run.get("excluded_rows", 0)
    excluded_reasons = last_run.get("excluded_reasons", [])
    used_columns = last_run.get("used_columns", [])
    unit = last_run.get("unit", "")
    caution = last_run.get("caution", "")
    calc_result = last_run.get("result", {})

    logger.info(f"[AI] explain 요청 시작 (mode=B, tool={tool_name}, model={model_name})")

    prompt_b = f"""당신은 교육용 데이터 분석 웹앱의 수석 데이터 분석가입니다.
Python Pandas 엔진이 실제 CSV 데이터를 읽어 100% 오차 없이 계산한 결과가 아래에 제공됩니다.
오직 이 계산 결과에 적힌 사실만을 바탕으로 정직하고 명확한 데이터 해석 보고서를 작성해야 합니다.

[분석 도구]: {tool_name}
[기준 시점]: {ref_period}
[사용한 행 수]: {used_rows}개
[제외한 행 수]: {excluded_rows}개 (제외 사유: {', '.join(excluded_reasons) if excluded_reasons else '없음'})
[사용한 열 목록]: {', '.join(used_columns)}
[측정 단위]: {unit}
[주의사항]: {caution}

[지표 정의 및 공식 출처]:
- 지표명: {indicator_meta['name']}
- 공식 정의: {indicator_meta['definition']}
- 출처 기관: {indicator_meta['source']}

[Pandas 실제 계산 결과 (JSON)]:
{json.dumps(calc_result, ensure_ascii=False, indent=2)}

[절대 준수 규칙]
1. 반드시 위에 제공된 계산 결과에 있는 숫자만 사용하세요. 절대로 직접 계산하거나 추정하지 마세요.
2. 계산 결과에 없는 가상의 국가, 연도, 수치를 절대 언급하지 마세요.
3. 기준 시점({ref_period})과 제외된 행 수({excluded_rows}개)를 본문에 반드시 명확히 숫자로 명시하세요.
4. 상관관계를 인과관계(원인과 결과)로 표현하지 마세요.
5. 지표의 정의(최근 3개월 내 접속 등)와 출처를 보고서 앞부분에 반드시 표기하세요.
6. 확인할 수 없는 사실은 반드시 "이 데이터로는 확인할 수 없다"라고 분명히 적으세요.
7. 중학생도 이해할 수 있게 친절하고 명확하게 쓰되, 통계적 정확성을 절대 희생하지 마세요.

[반드시 따라야 하는 7개 고정 마크다운 섹션]
## 무엇을 봤는가
## 데이터 출처와 정의
## 기준 시점과 제외된 항목
## 계산 결과
## 읽어낼 수 있는 것
## 이 데이터로는 알 수 없는 것
## 다음에 확인해볼 것
"""

    res_b = client.models.generate_content(model=model_name, contents=prompt_b)
    CURRENT_DATASET["last_report_markdown"] = res_b.text
    CURRENT_DATASET["last_report_mode"] = "B"
    return jsonify({
        "status": "success",
        "mode": "B",
        "tool": tool_name,
        "reference_period": ref_period,
        "report_markdown": res_b.text
    }), 200

@app.route("/chat", methods=["POST"])
def chat():
    """보고서에 대한 후속 질의응답 (대화창 및 맞춤형 쉬운 설명)"""
    logger.info("[REQUEST] POST /chat")

    if CURRENT_DATASET["df"] is None:
        return jsonify({"error": "먼저 CSV 파일을 업로드해 주세요."}), 400

    data = request.get_json(silent=True) or {}
    user_question = data.get("question", "").strip()

    if not user_question:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다."}), 400

    client = genai.Client(api_key=api_key)
    last_report = CURRENT_DATASET.get("last_report_markdown", "")
    last_run = CURRENT_DATASET.get("last_run_result") or {}
    indicator_meta = get_indicator_metadata()

    logger.info(f"[AI] chat 요청 시작 (질문: {user_question[:50]}...)")

    chat_prompt = f"""당신은 'AI Data Insight Builder'의 친절하고 정직한 AI 데이터 튜터입니다.
사용자가 최근 생성된 데이터 분석 보고서에 대해 후속 질문을 했습니다.

[사용자가 보고 있는 최근 분석 보고서]:
{last_report if last_report else '(보고서가 아직 생성되지 않음)'}

[Pandas 실제 계산 결과 (통계 사실)]:
{json.dumps(last_run.get('result', {}), ensure_ascii=False) if last_run else '{}'}
[기준 시점 / 사용 행 수]: {last_run.get('reference_period', 'N/A')} / {last_run.get('used_rows', 'N/A')}개국

[지표 정의 및 출처]:
{indicator_meta['name']} (정의: {indicator_meta['definition']}, 출처: {indicator_meta['source']})

[사용자의 후속 질문]:
"{user_question}"

[답변 원칙 (절대 준수)]
1. 숫자는 오직 위에 제공된 Pandas 실제 계산 결과에 있는 수치만 언급하세요. 임의로 계산하거나 추측하지 마세요.
2. "중학생도 이해할 수 있게 쉽게 설명해줘" 또는 쉬운 설명을 요구하는 질문이라면, 일상생활의 쉬운 비유(학교 성적, 키 재기, 피자 나누기 등)를 들어서 아주 친절하고 직관적으로 설명해 주세요.
3. 데이터로 알 수 없는 부분(예: 인터넷 속도, 요금, 인과관계 등)은 "이 데이터로는 확인할 수 없습니다"라고 분명하게 선을 그어 주세요.
4. 상관관계를 인과관계로 비약하지 마세요.
5. 마크다운 형식으로 가독성 좋고 따뜻한 어투로 답변해 주세요.
"""

    try:
        chat_res = client.models.generate_content(model=model_name, contents=chat_prompt)
        logger.info(f"[AI] chat 응답 수신 (길이: {len(chat_res.text)}자)")
        logger.info("[RESPONSE] status=200")
        return jsonify({
            "status": "success",
            "success": True,
            "question": user_question,
            "answer_markdown": chat_res.text
        }), 200
    except Exception as e:
        logger.error(f"[ERROR] 후속 질문 답변 생성 오류: {e}", exc_info=True)
        return jsonify({"error": f"답변 생성 중 오류가 발생했습니다: {str(e)}"}), 500

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "true").lower() in ("true", "1", "yes")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
