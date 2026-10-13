"""
tools.py
AI Data Insight Builder 분석 도구 카탈로그 모듈 (총 12개 도구 전체 구현)

모든 도구 함수는 순수 Pandas로 계산을 수행하며,
공통 규칙에 따라 아래 메타데이터를 반드시 결과에 포함합니다:
- reference_period: 기준 시점
- used_rows: 계산에 사용된 행 수
- excluded_rows: 제외된 행 수
- excluded_reasons: 제외 이유 목록
- used_columns: 사용된 열 목록
- unit: 측정 단위
- caution: 해석 시 주의사항 (상관분석은 '상관관계는 인과관계가 아니다' 필수 포함)
"""

import os
import glob
import math
import numpy as np
import pandas as pd

# 집계/그룹 묶음 행 감지용 키워드 (대소문자 무시)
AGGREGATE_KEYWORDS = [
    'world', 'oecd members', 'euro area', 'european union',
    'high income', 'low income', 'income', 'area', 'total',
    'aggregate', 'dividend', 'states', 'sub-saharan',
    'latin america', 'caribbean', 'middle east', 'north africa',
    'south asia', 'east asia', 'europe & central asia',
    '전국', '전체', '합계', '평균'
]

def sanitize_value(val):
    """NaN, Infinity 등을 JSON 표준 안전 값(None 또는 float/int)으로 변환"""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (np.floating, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        return float(round(val, 4))
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return str(val)

def sanitize_record(record):
    """딕셔너리 내 모든 값 재귀적 직렬화 안전 처리"""
    if isinstance(record, dict):
        return {str(k): sanitize_record(v) for k, v in record.items()}
    if isinstance(record, list):
        return [sanitize_record(v) for v in record]
    return sanitize_value(record)

def detect_label_column(df, explicit_col=None):
    """대표 식별자(국가명/항목명) 열 탐색"""
    if explicit_col and explicit_col in df.columns:
        return explicit_col
    str_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    if str_cols:
        return str_cols[0]
    return df.columns[0]

def get_aggregate_mask(df, label_col=None):
    """집계/그룹 행 여부를 나타내는 불리언 시리즈 반환 (True = 집계 행)"""
    col = detect_label_column(df, label_col)
    series = df[col].astype(str).str.lower()
    mask = series.apply(lambda s: any(kw in s for kw in AGGREGATE_KEYWORDS))
    return mask

def filter_dataframe(df, exclude_aggregates=True, label_col=None):
    """집계 행 필터링 및 제외 통계 반환"""
    if not exclude_aggregates:
        return df.copy(), 0, []
    
    mask = get_aggregate_mask(df, label_col)
    excluded_count = int(mask.sum())
    filtered_df = df[~mask].copy()
    
    reasons = []
    if excluded_count > 0:
        reasons.append(f"전체 통계 왜곡 방지를 위해 집계/그룹 묶음 행 {excluded_count}개 제외")
    
    return filtered_df, excluded_count, reasons


# ==============================================================================
# 도구 1: reshape_wide_to_long (연도 열을 행으로 접기)
# ==============================================================================
def reshape_wide_to_long(df, id_vars=None, var_name="year", value_name="value",
                         exclude_aggregates=True, **kwargs):
    filtered_df, excluded_count, reasons = filter_dataframe(df, exclude_aggregates)

    str_cols = [str(c) for c in filtered_df.columns]
    year_cols = [c for c in str_cols if c.strip().isdigit() and 1800 <= int(c.strip()) <= 2100]

    if not year_cols:
        raise ValueError("언피벗할 4자리 연도 열(예: '1960', '2024')을 찾을 수 없습니다.")

    if id_vars is None:
        id_vars = [c for c in str_cols if c not in year_cols and not c.startswith("Unnamed:")]

    melted = pd.melt(
        filtered_df,
        id_vars=id_vars,
        value_vars=year_cols,
        var_name=var_name,
        value_name=value_name
    )

    melted[value_name] = pd.to_numeric(melted[value_name], errors='coerce')
    na_count = int(melted[value_name].isna().sum())
    valid_melted = melted.dropna(subset=[value_name]).copy()
    if na_count > 0:
        reasons.append(f"연도별 데이터가 없는 결측치 {na_count}건 제외")

    preview_data = [sanitize_record(r) for r in valid_melted.head(20).to_dict(orient="records")]
    label_col = id_vars[0] if id_vars else None
    unique_entities = int(valid_melted[label_col].nunique()) if label_col else 0

    return {
        "tool": "reshape_wide_to_long",
        "result": {
            "total_long_rows": int(len(valid_melted)),
            "unique_entities": unique_entities,
            "year_range": {"min": year_cols[0], "max": year_cols[-1]},
            "columns": list(valid_melted.columns),
            "preview": preview_data
        },
        "chart_data": None,
        "reference_period": None,
        "used_rows": int(len(valid_melted)),
        "excluded_rows": excluded_count + na_count,
        "excluded_reasons": reasons,
        "used_columns": id_vars + [var_name, value_name],
        "unit": "행 (롱 포맷 레코드 수)",
        "caution": "연도가 행으로 전환되어 컴퓨터 분석과 시계열 차트 생성에 최적화된 형태입니다."
    }


# ==============================================================================
# 도구 2: quality_report (결측·중복·타입·이상한 열 이름 진단)
# ==============================================================================
def quality_report(df, exclude_aggregates=False, **kwargs):
    filtered_df, excluded_count, reasons = filter_dataframe(df, exclude_aggregates)
    total_rows = int(len(filtered_df))
    total_cols = int(len(filtered_df.columns))

    column_quality = []
    unnamed_cols = []
    for col in filtered_df.columns:
        col_str = str(col)
        missing_cnt = int(filtered_df[col].isna().sum())
        missing_pct = round((missing_cnt / total_rows * 100), 2) if total_rows > 0 else 0.0
        dtype_str = str(filtered_df[col].dtype)
        unique_cnt = int(filtered_df[col].nunique(dropna=True))

        is_unnamed = col_str.startswith("Unnamed:") or not col_str.strip()
        if is_unnamed:
            unnamed_cols.append(col_str)

        column_quality.append({
            "column": col_str,
            "dtype": dtype_str,
            "missing_count": missing_cnt,
            "missing_ratio": missing_pct,
            "unique_count": unique_cnt,
            "is_unnamed": is_unnamed
        })

    duplicate_rows = int(filtered_df.duplicated().sum())

    return {
        "tool": "quality_report",
        "result": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "duplicate_rows": duplicate_rows,
            "unnamed_columns_count": len(unnamed_cols),
            "unnamed_columns": unnamed_cols,
            "column_quality": column_quality
        },
        "chart_data": None,
        "reference_period": None,
        "used_rows": total_rows,
        "excluded_rows": excluded_count,
        "excluded_reasons": reasons,
        "used_columns": list(filtered_df.columns),
        "unit": "건 / 비율(%)",
        "caution": "결측치가 50% 이상인 열은 통계 분석 시 제외하거나 대체 기법을 고려해야 합니다."
    }


# ==============================================================================
# 도구 3: year_coverage (연도별 값 개수와 권장 기준연도)
# ==============================================================================
def year_coverage(df, exclude_aggregates=True, **kwargs):
    filtered_df, excluded_count, reasons = filter_dataframe(df, exclude_aggregates)
    total_rows = int(len(filtered_df))

    year_cols = [c for c in filtered_df.columns if str(c).strip().isdigit() and 1800 <= int(str(c).strip()) <= 2100]
    if not year_cols:
        raise ValueError("데이터에서 4자리 연도 열을 찾을 수 없습니다.")

    coverage_list = []
    years = []
    counts = []

    for y in year_cols:
        val_cnt = int(filtered_df[y].notna().sum())
        val_ratio = round((val_cnt / total_rows * 100), 2) if total_rows > 0 else 0.0
        coverage_list.append({
            "year": str(y),
            "filled_count": val_cnt,
            "filled_ratio": val_ratio
        })
        years.append(str(y))
        counts.append(val_cnt)

    max_filled = max(counts, default=0)
    solid_years = [y for y, c in zip(years, counts) if c >= max_filled * 0.75]
    recommended_year = solid_years[-1] if solid_years else years[-1]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": years,
            "datasets": [
                {
                    "label": "채워진 데이터 수 (건)",
                    "data": counts,
                    "backgroundColor": ["#3b82f6" if y != recommended_year else "#10b981" for y in years],
                    "borderColor": ["#1d4ed8" if y != recommended_year else "#059669" for y in years],
                    "borderWidth": 1
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"연도별 데이터 수집 완성도 (초록색: 권장 기준연도 {recommended_year})"}
            }
        }
    }

    return {
        "tool": "year_coverage",
        "result": {
            "total_available_years": len(years),
            "year_range": {"start": years[0], "end": years[-1]},
            "recommended_reference_year": recommended_year,
            "max_filled_count": max_filled,
            "coverage": coverage_list
        },
        "chart_data": chart_data,
        "reference_period": recommended_year,
        "used_rows": total_rows,
        "excluded_rows": excluded_count,
        "excluded_reasons": reasons,
        "used_columns": year_cols,
        "unit": "건 (개별 항목 수)",
        "caution": f"최신 연도인 {years[-1]}년은 통계 미완료로 결측이 많을 수 있으므로 {recommended_year}년 사용을 강력 권장합니다."
    }


# ==============================================================================
# 도구 4: detect_aggregates (집계 행 후보 탐지)
# ==============================================================================
def detect_aggregates(df, label_col=None, **kwargs):
    col = detect_label_column(df, label_col)
    total_rows = int(len(df))

    mask = get_aggregate_mask(df, col)
    agg_df = df[mask].copy()
    pure_df = df[~mask].copy()

    detected_items = [{"index": int(idx), "label": str(val)} for idx, val in agg_df[col].items()]

    chart_data = {
        "type": "doughnut",
        "data": {
            "labels": ["순수 개별 항목 (국가 등)", "집계/그룹 묶음 항목"],
            "datasets": [
                {
                    "data": [int(len(pure_df)), int(len(agg_df))],
                    "backgroundColor": ["#3b82f6", "#ef4444"]
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"데이터 구성 비율 (총 {total_rows}개 행)"}
            }
        }
    }

    return {
        "tool": "detect_aggregates",
        "result": {
            "total_rows": total_rows,
            "pure_entities_count": int(len(pure_df)),
            "aggregate_entities_count": int(len(agg_df)),
            "aggregate_ratio": round((len(agg_df) / total_rows * 100), 2) if total_rows > 0 else 0.0,
            "detected_aggregates": detected_items
        },
        "chart_data": chart_data,
        "reference_period": None,
        "used_rows": total_rows,
        "excluded_rows": 0,
        "excluded_reasons": ["전체 데이터셋 구조 탐색 목적이므로 모든 행 분석 대상 포함"],
        "used_columns": [col],
        "unit": "개 (행 수)",
        "caution": "집계 행을 포함한 채로 전체 평균을 내면 개별 국가 수치가 이중으로 계산되어 심각한 오류가 발생합니다."
    }


# ==============================================================================
# 도구 5: describe_numeric (개수·평균·중앙값·최소·최대·표준편차)
# ==============================================================================
def describe_numeric(df, value_column=None, reference_period=None, exclude_aggregates=True, **kwargs):
    filtered_df, agg_excluded, reasons = filter_dataframe(df, exclude_aggregates)

    val_col = value_column or reference_period
    if not val_col:
        num_cols = [c for c in filtered_df.columns if pd.api.types.is_numeric_dtype(filtered_df[c])]
        if num_cols:
            val_col = num_cols[0]
        else:
            raise ValueError("기술통계를 산출할 숫자형 열이나 기준연도를 지정해 주세요.")

    if val_col not in filtered_df.columns:
        raise ValueError(f"데이터셋에 '{val_col}' 열이 존재하지 않습니다.")

    series = pd.to_numeric(filtered_df[val_col], errors='coerce')
    valid_series = series.dropna()

    na_excluded = int(series.isna().sum())
    if na_excluded > 0:
        reasons.append(f"'{val_col}' 열에 값이 없는 결측 행 {na_excluded}개 제외")

    if len(valid_series) == 0:
        raise ValueError(f"'{val_col}' 열에 계산 가능한 유효한 숫자 데이터가 없습니다.")

    stats = {
        "count": int(len(valid_series)),
        "mean": float(round(valid_series.mean(), 4)),
        "median": float(round(valid_series.median(), 4)),
        "std": float(round(valid_series.std(), 4)) if len(valid_series) > 1 else 0.0,
        "min": float(round(valid_series.min(), 4)),
        "max": float(round(valid_series.max(), 4)),
        "q25": float(round(valid_series.quantile(0.25), 4)),
        "q75": float(round(valid_series.quantile(0.75), 4))
    }

    chart_data = {
        "type": "bar",
        "data": {
            "labels": ["최솟값(Min)", "25% 분위수", "중앙값(Median)", "평균(Mean)", "75% 분위수", "최댓값(Max)"],
            "datasets": [
                {
                    "label": f"{val_col} 주요 통계치",
                    "data": [stats["min"], stats["q25"], stats["median"], stats["mean"], stats["q75"], stats["max"]],
                    "backgroundColor": ["#94a3b8", "#60a5fa", "#2563eb", "#10b981", "#60a5fa", "#94a3b8"]
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{val_col} 기술통계치 요약 (표본 수: {stats['count']})"}
            }
        }
    }

    return {
        "tool": "describe_numeric",
        "result": {
            "column": val_col,
            "statistics": stats
        },
        "chart_data": chart_data,
        "reference_period": str(reference_period) if reference_period else (str(val_col) if str(val_col).isdigit() else None),
        "used_rows": int(len(valid_series)),
        "excluded_rows": agg_excluded + na_excluded,
        "excluded_reasons": reasons,
        "used_columns": [val_col],
        "unit": "수치 (해당 지표 단위)",
        "caution": "평균값은 소수의 극단적인 수치에 영향을 크게 받으므로, 중앙값(Median)과 함께 비교해야 분포 왜곡을 방지할 수 있습니다."
    }


# ==============================================================================
# 도구 6: trend_line (선택 항목들의 연도별 추이 선 차트)
# ==============================================================================
def trend_line(df, items=None, label_column=None, exclude_aggregates=False, **kwargs):
    label_col = detect_label_column(df, label_column)
    year_cols = [c for c in df.columns if str(c).strip().isdigit() and 1800 <= int(str(c).strip()) <= 2100]

    if not year_cols:
        raise ValueError("시계열 추이를 그릴 수 있는 연도 열을 찾을 수 없습니다.")

    if not items:
        latest_y = year_cols[-2] if len(year_cols) >= 2 else year_cols[-1]
        temp_df = df.dropna(subset=[latest_y]).copy()
        temp_df[latest_y] = pd.to_numeric(temp_df[latest_y], errors='coerce')
        items = list(temp_df.sort_values(by=latest_y, ascending=False)[label_col].head(3))

    matched_df = df[df[label_col].isin(items)].copy()
    if len(matched_df) == 0:
        raise ValueError(f"지정한 항목({items})을 데이터셋에서 찾을 수 없습니다.")

    used_rows = int(len(matched_df))
    excluded_rows = int(len(df) - used_rows)
    reasons = [f"선택한 {used_rows}개 비교 대상 항목 이외의 {excluded_rows}개 행 제외"]

    colors = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
    datasets = []
    table_rows = []

    for idx, (_, row) in enumerate(matched_df.iterrows()):
        item_name = str(row[label_col])
        series_vals = [sanitize_value(pd.to_numeric(row.get(y), errors='coerce')) for y in year_cols]
        color = colors[idx % len(colors)]
        datasets.append({
            "label": item_name,
            "data": series_vals,
            "borderColor": color,
            "backgroundColor": color,
            "fill": False,
            "tension": 0.2
        })

    recent_years = year_cols[-10:] if len(year_cols) >= 10 else year_cols
    for _, row in matched_df.iterrows():
        entry = {"name": str(row[label_col])}
        for y in recent_years:
            entry[y] = sanitize_value(pd.to_numeric(row.get(y), errors='coerce'))
        table_rows.append(entry)

    chart_data = {
        "type": "line",
        "data": {
            "labels": year_cols,
            "datasets": datasets
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{', '.join(items)} 연도별 추이 비교 ({year_cols[0]} ~ {year_cols[-1]})"}
            }
        }
    }

    return {
        "tool": "trend_line",
        "result": {
            "selected_items": items,
            "year_range": {"start": year_cols[0], "end": year_cols[-1]},
            "recent_years_summary": table_rows
        },
        "chart_data": chart_data,
        "reference_period": f"{year_cols[0]}-{year_cols[-1]}",
        "used_rows": used_rows,
        "excluded_rows": excluded_rows,
        "excluded_reasons": reasons,
        "used_columns": [label_col] + year_cols,
        "unit": "수치 (연도별 변화량)",
        "caution": "특정 연도에 설문 조사가 누락된 경우 선이 끊기거나 평탄화될 수 있으므로 결측 구간에 유의해야 합니다."
    }


# ==============================================================================
# 도구 7: top_bottom_n (기준연도 기준 상위·하위 N 수평 막대)
# ==============================================================================
def top_bottom_n(df, reference_period=None, n=10, value_column=None, label_column=None,
                 exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("top_bottom_n 도구를 실행하려면 'reference_period(기준 시점)' 파라미터가 필수입니다.")

    ref_str = str(reference_period).strip()
    val_col = value_column or ref_str
    if val_col not in df.columns:
        raise ValueError(f"데이터셋에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = detect_label_column(df, label_column)
    filtered_df, agg_excluded, reasons = filter_dataframe(df, exclude_aggregates, label_col)

    numeric_series = pd.to_numeric(filtered_df[val_col], errors='coerce')
    valid_mask = numeric_series.notna()
    na_excluded = int((~valid_mask).sum())
    if na_excluded > 0:
        reasons.append(f"기준 시점({ref_str})에 데이터가 없는 결측 행 {na_excluded}개 제외")

    valid_df = filtered_df[valid_mask].copy()
    valid_df["_val_num"] = numeric_series[valid_mask]

    if len(valid_df) == 0:
        raise ValueError(f"기준 시점 '{ref_str}'에 유효한 수치를 가진 데이터가 없습니다.")

    n = int(n)
    sorted_df = valid_df.sort_values(by="_val_num", ascending=False)
    top_df = sorted_df.head(n)
    bottom_df = sorted_df.tail(n).iloc[::-1]

    top_items = [
        {"rank": i + 1, "label": str(row[label_col]), "value": sanitize_value(row["_val_num"])}
        for i, (_, row) in enumerate(top_df.iterrows())
    ]
    bottom_items = [
        {"rank": len(sorted_df) - i, "label": str(row[label_col]), "value": sanitize_value(row["_val_num"])}
        for i, (_, row) in enumerate(bottom_df.iterrows())
    ]

    chart_data = {
        "type": "bar",
        "data": {
            "labels": [item["label"] for item in top_items],
            "datasets": [
                {
                    "label": f"{ref_str}년 상위 {n} 순위",
                    "data": [item["value"] for item in top_items],
                    "backgroundColor": "#3b82f6"
                }
            ]
        },
        "options": {
            "indexAxis": "y",
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{ref_str}년 상위 {n}개 순위 비교"}
            }
        }
    }

    return {
        "tool": "top_bottom_n",
        "result": {
            "reference_period": ref_str,
            "n": n,
            "total_ranked_count": int(len(sorted_df)),
            "top_n": top_items,
            "bottom_n": bottom_items
        },
        "chart_data": chart_data,
        "reference_period": ref_str,
        "used_rows": int(len(valid_df)),
        "excluded_rows": agg_excluded + na_excluded,
        "excluded_reasons": reasons,
        "used_columns": [label_col, val_col],
        "unit": "수치 (상위/하위 랭킹)",
        "caution": f"모든 항목은 동일한 기준연도({ref_str}) 기준으로만 비교되었으며, 결측치는 순위에서 제외되었습니다."
    }


# ==============================================================================
# 도구 8: group_summary (그룹별 평균·합계·개수 막대)
# ==============================================================================
def group_summary(df, reference_period=None, group_column=None, value_column=None,
                  agg_func="mean", exclude_aggregates=True, **kwargs):
    if not reference_period:
        raise ValueError("group_summary 도구를 실행하려면 'reference_period(기준 시점)' 파라미터가 필수입니다.")

    ref_str = str(reference_period).strip()
    val_col = value_column or ref_str
    if val_col not in df.columns:
        raise ValueError(f"데이터셋에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    working_df = df.copy()
    if group_column not in working_df.columns:
        meta_files = glob.glob("data/**/Metadata_Country*.csv", recursive=True)
        if meta_files:
            try:
                meta_df = pd.read_csv(meta_files[0], encoding='utf-8-sig')
                join_keys = [c for c in ['Country Code', 'CountryCode'] if c in working_df.columns and c in meta_df.columns]
                if join_keys:
                    key = join_keys[0]
                    target_cols = [c for c in ['Region', 'IncomeGroup'] if c in meta_df.columns]
                    working_df = working_df.merge(meta_df[[key] + target_cols], on=key, how='left')
            except Exception:
                pass

    grp_col = group_column
    if not grp_col or grp_col not in working_df.columns:
        for candidate in ['Region', 'IncomeGroup', '대륙', '지역', '그룹']:
            if candidate in working_df.columns:
                grp_col = candidate
                break

    if not grp_col or grp_col not in working_df.columns:
        raise ValueError("그룹화할 범주형 열(예: Region, IncomeGroup)을 찾을 수 없습니다.")

    label_col = detect_label_column(working_df)
    filtered_df, agg_excluded, reasons = filter_dataframe(working_df, exclude_aggregates, label_col)

    grp_na_mask = filtered_df[grp_col].isna() | (filtered_df[grp_col].astype(str).str.strip() == "")
    grp_na_cnt = int(grp_na_mask.sum())
    if grp_na_cnt > 0:
        reasons.append(f"그룹 정보({grp_col})가 없는 행 {grp_na_cnt}개 제외")

    valid_grp_df = filtered_df[~grp_na_mask].copy()

    num_series = pd.to_numeric(valid_grp_df[val_col], errors='coerce')
    val_na_mask = num_series.isna()
    val_na_cnt = int(val_na_mask.sum())
    if val_na_cnt > 0:
        reasons.append(f"기준연도({ref_str}) 수치가 없는 행 {val_na_cnt}개 제외")

    final_df = valid_grp_df[~val_na_mask].copy()
    final_df["_val_num"] = num_series[~val_na_mask]

    if len(final_df) == 0:
        raise ValueError(f"'{grp_col}' 그룹별로 집계할 유효한 데이터가 없습니다.")

    grouped = final_df.groupby(grp_col)["_val_num"].agg(
        count='count',
        mean='mean',
        median='median',
        sum='sum',
        min='min',
        max='max'
    ).reset_index()

    grouped = grouped.sort_values(by="mean", ascending=False)

    summary_records = []
    labels = []
    means = []
    medians = []

    for _, r in grouped.iterrows():
        g_name = str(r[grp_col])
        labels.append(g_name)
        m_val = float(round(r["mean"], 4))
        med_val = float(round(r["median"], 4))
        means.append(m_val)
        medians.append(med_val)
        summary_records.append({
            "group": g_name,
            "count": int(r["count"]),
            "mean": m_val,
            "median": med_val,
            "sum": float(round(r["sum"], 4)),
            "min": float(round(r["min"], 4)),
            "max": float(round(r["max"], 4))
        })

    chart_data = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "그룹 평균",
                    "data": means,
                    "backgroundColor": "#3b82f6"
                },
                {
                    "label": "그룹 중앙값",
                    "data": medians,
                    "backgroundColor": "#10b981"
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{grp_col}별 {ref_str}년 수치 비교"}
            }
        }
    }

    return {
        "tool": "group_summary",
        "result": {
            "group_column": grp_col,
            "reference_period": ref_str,
            "groups_count": len(grouped),
            "summary": summary_records
        },
        "chart_data": chart_data,
        "reference_period": ref_str,
        "used_rows": int(len(final_df)),
        "excluded_rows": agg_excluded + grp_na_cnt + val_na_cnt,
        "excluded_reasons": reasons,
        "used_columns": [grp_col, val_col],
        "unit": "수치 (그룹별 통계량)",
        "caution": "그룹 내 속한 국가 수(표본 수)의 차이가 클 수 있으므로 평균과 중앙값을 함께 고려해야 합니다."
    }


# ==============================================================================
# 도구 9: change_rate (두 시점 사이 변화량·변화율 막대)
# ==============================================================================
def change_rate(df, reference_period=None, base_period=None, n=10, label_column=None,
                exclude_aggregates=True, **kwargs):
    """
    두 시점(base_period -> reference_period) 사이의 변화량(포인트 차이)과 변화율(%)을 계산합니다.
    [공통 규칙]: reference_period 필수!
    """
    if not reference_period:
        raise ValueError("change_rate 도구를 실행하려면 'reference_period(종료 기준 시점)' 파라미터가 필수입니다.")

    ref_str = str(reference_period).strip()
    if ref_str not in df.columns:
        raise ValueError(f"데이터셋에 기준 시점 열 '{ref_str}'이 존재하지 않습니다.")

    # base_period 결정 (없으면 5~10년 전 유효 연도 자동 선정)
    year_cols = [c for c in df.columns if str(c).strip().isdigit() and 1800 <= int(str(c).strip()) <= 2100]
    if not base_period:
        if ref_str in year_cols:
            idx = year_cols.index(ref_str)
            # 10년 전 또는 가능한 가장 오래된 연도
            base_idx = max(0, idx - 10) if idx >= 10 else max(0, idx - 5)
            base_str = year_cols[base_idx]
        else:
            raise ValueError("비교할 시작 시점 'base_period'를 지정해 주세요.")
    else:
        base_str = str(base_period).strip()

    if base_str not in df.columns:
        raise ValueError(f"데이터셋에 비교 시점 열 '{base_str}'이 존재하지 않습니다.")

    label_col = detect_label_column(df, label_column)
    filtered_df, agg_excluded, reasons = filter_dataframe(df, exclude_aggregates, label_col)

    s_base = pd.to_numeric(filtered_df[base_str], errors='coerce')
    s_ref = pd.to_numeric(filtered_df[ref_str], errors='coerce')

    valid_mask = s_base.notna() & s_ref.notna()
    na_excluded = int((~valid_mask).sum())
    if na_excluded > 0:
        reasons.append(f"시작 시점({base_str}) 또는 종료 시점({ref_str}) 중 값이 없는 행 {na_excluded}개 제외")

    valid_df = filtered_df[valid_mask].copy()
    valid_df["_base"] = s_base[valid_mask]
    valid_df["_ref"] = s_ref[valid_mask]
    valid_df["_diff"] = valid_df["_ref"] - valid_df["_base"]  # 변화량 (%p)
    valid_df["_pct_change"] = np.where(
        valid_df["_base"] != 0,
        ((valid_df["_ref"] - valid_df["_base"]) / valid_df["_base"]) * 100,
        np.nan
    )

    if len(valid_df) == 0:
        raise ValueError(f"두 시점({base_str} ~ {ref_str}) 모두 수치가 존재하는 데이터가 없습니다.")

    n = int(n)
    sorted_df = valid_df.sort_values(by="_diff", ascending=False)
    top_growers = sorted_df.head(n)
    bottom_growers = sorted_df.tail(n).iloc[::-1]

    top_items = [
        {
            "label": str(row[label_col]),
            "base_val": sanitize_value(row["_base"]),
            "ref_val": sanitize_value(row["_ref"]),
            "diff": sanitize_value(row["_diff"]),
            "pct_change": sanitize_value(row["_pct_change"])
        }
        for _, row in top_growers.iterrows()
    ]

    bottom_items = [
        {
            "label": str(row[label_col]),
            "base_val": sanitize_value(row["_base"]),
            "ref_val": sanitize_value(row["_ref"]),
            "diff": sanitize_value(row["_diff"]),
            "pct_change": sanitize_value(row["_pct_change"])
        }
        for _, row in bottom_growers.iterrows()
    ]

    # Chart.js 증가량 막대그래프
    chart_data = {
        "type": "bar",
        "data": {
            "labels": [item["label"] for item in top_items],
            "datasets": [
                {
                    "label": f"변화량 (%p, {base_str} -> {ref_str})",
                    "data": [item["diff"] for item in top_items],
                    "backgroundColor": "#10b981"
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"증가량 상위 {n}개 항목 ({base_str} -> {ref_str})"}
            }
        }
    }

    return {
        "tool": "change_rate",
        "result": {
            "base_period": base_str,
            "reference_period": ref_str,
            "top_growth_items": top_items,
            "bottom_growth_items": bottom_items
        },
        "chart_data": chart_data,
        "reference_period": f"{base_str} -> {ref_str}",
        "used_rows": int(len(valid_df)),
        "excluded_rows": agg_excluded + na_excluded,
        "excluded_reasons": reasons,
        "used_columns": [label_col, base_str, ref_str],
        "unit": "%p (포인트 변화량) 및 % (증가율)",
        "caution": "초기에 보급률이 극도로 낮았던 국가는 작은 증가로도 증가율(%)이 수백%로 급등하는 기저 효과(Base Effect)에 주의해야 합니다."
    }


# ==============================================================================
# 도구 10: distribution (구간별 분포 히스토그램)
# ==============================================================================
def distribution(df, reference_period=None, bins=10, value_column=None,
                 exclude_aggregates=True, **kwargs):
    """
    특정 기준연도 수치의 구간별 빈도(히스토그램 분포)를 계산하여 디지털 격차 및 양극화를 파악합니다.
    [공통 규칙]: reference_period 필수!
    """
    if not reference_period:
        raise ValueError("distribution 도구를 실행하려면 'reference_period(기준 시점)' 파라미터가 필수입니다.")

    ref_str = str(reference_period).strip()
    val_col = value_column or ref_str
    if val_col not in df.columns:
        raise ValueError(f"데이터셋에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = detect_label_column(df)
    filtered_df, agg_excluded, reasons = filter_dataframe(df, exclude_aggregates, label_col)

    s_num = pd.to_numeric(filtered_df[val_col], errors='coerce')
    valid_mask = s_num.notna()
    na_excluded = int((~valid_mask).sum())
    if na_excluded > 0:
        reasons.append(f"기준 시점({ref_str}) 수치가 없는 행 {na_excluded}개 제외")

    valid_vals = s_num[valid_mask]
    if len(valid_vals) == 0:
        raise ValueError(f"기준 시점 '{ref_str}'에 유효한 데이터가 없습니다.")

    bins = int(bins)
    v_min = float(valid_vals.min())
    v_max = float(valid_vals.max())

    # 백분율(0~100) 지표 여부 판별
    if 0 <= v_min and v_max <= 100:
        bin_edges = np.linspace(0, 100, bins + 1)
    else:
        bin_edges = np.linspace(v_min, v_max, bins + 1)

    hist_counts, _ = np.histogram(valid_vals, bins=bin_edges)
    total_valid = len(valid_vals)

    bin_data = []
    bin_labels = []
    for i in range(len(hist_counts)):
        b_start = round(bin_edges[i], 1)
        b_end = round(bin_edges[i+1], 1)
        lbl = f"{b_start} ~ {b_end}"
        cnt = int(hist_counts[i])
        ratio = round((cnt / total_valid * 100), 2)
        bin_labels.append(lbl)
        bin_data.append({
            "bin_range": lbl,
            "start": b_start,
            "end": b_end,
            "count": cnt,
            "ratio": ratio
        })

    chart_data = {
        "type": "bar",
        "data": {
            "labels": bin_labels,
            "datasets": [
                {
                    "label": f"해당 구간 국가 수 ({ref_str}년)",
                    "data": [b["count"] for b in bin_data],
                    "backgroundColor": "#6366f1"
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{ref_str}년 수치 분포 히스토그램 (총 {total_valid}개국)"}
            }
        }
    }

    return {
        "tool": "distribution",
        "result": {
            "reference_period": ref_str,
            "total_items": total_valid,
            "min": v_min,
            "max": v_max,
            "bins_count": bins,
            "distribution": bin_data
        },
        "chart_data": chart_data,
        "reference_period": ref_str,
        "used_rows": total_valid,
        "excluded_rows": agg_excluded + na_excluded,
        "excluded_reasons": reasons,
        "used_columns": [val_col],
        "unit": "개 (구간별 빈도 수)",
        "caution": "특정 구간에 빈도가 쏠려 있거나 쌍봉(bimodal) 분포를 띨 경우 전 세계 디지털 양극화(Digital Divide)가 존재함을 의미합니다."
    }


# ==============================================================================
# 도구 11: correlation_scatter (두 숫자 열 상관계수 산점도)
# ==============================================================================
def correlation_scatter(df, reference_period=None, x_column=None, y_column=None,
                        exclude_aggregates=True, **kwargs):
    """
    두 시점 또는 두 변수 간의 피어슨 상관계수(r)를 산출하고 산점도(Scatter) 데이터를 생성합니다.
    [공통 규칙]: reference_period 필수!
    [절대 규칙]: 주의사항에 '상관관계는 인과관계가 아니다'를 반드시 명시!
    """
    if not reference_period:
        raise ValueError("correlation_scatter 도구를 실행하려면 'reference_period(기준 시점)' 파라미터가 필수입니다.")

    ref_str = str(reference_period).strip()
    year_cols = [c for c in df.columns if str(c).strip().isdigit() and 1800 <= int(str(c).strip()) <= 2100]

    # 기본 X, Y축 선정 (지정되지 않았으면 10년 전 vs 기준연도 비교)
    if not y_column:
        y_col = ref_str
    else:
        y_col = str(y_column).strip()

    if not x_column:
        if y_col in year_cols:
            idx = year_cols.index(y_col)
            base_idx = max(0, idx - 10)
            x_col = year_cols[base_idx]
        else:
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != y_col]
            if num_cols:
                x_col = num_cols[0]
            else:
                raise ValueError("상관관계를 비교할 X축 열을 지정해 주세요.")
    else:
        x_col = str(x_column).strip()

    if x_col not in df.columns or y_col not in df.columns:
        raise ValueError(f"데이터셋에 '{x_col}' 또는 '{y_col}' 열이 존재하지 않습니다.")

    label_col = detect_label_column(df)
    filtered_df, agg_excluded, reasons = filter_dataframe(df, exclude_aggregates, label_col)

    sx = pd.to_numeric(filtered_df[x_col], errors='coerce')
    sy = pd.to_numeric(filtered_df[y_col], errors='coerce')

    valid_mask = sx.notna() & sy.notna()
    na_excluded = int((~valid_mask).sum())
    if na_excluded > 0:
        reasons.append(f"'{x_col}' 또는 '{y_col}' 중 결측치가 있는 행 {na_excluded}개 제외")

    valid_df = filtered_df[valid_mask].copy()
    valid_df["_x"] = sx[valid_mask]
    valid_df["_y"] = sy[valid_mask]

    if len(valid_df) < 2:
        raise ValueError("상관계수를 계산하기에 유효한 데이터 쌍(최소 2개)이 부족합니다.")

    r_corr = float(valid_df["_x"].corr(valid_df["_y"]))
    r_squared = float(r_corr ** 2)

    # 상관 강도 해석 텍스트
    abs_r = abs(r_corr)
    if abs_r >= 0.7:
        strength = "매우 강한 상관관계"
    elif abs_r >= 0.4:
        strength = "뚜렷한 상관관계"
    elif abs_r >= 0.2:
        strength = "약한 상관관계"
    else:
        strength = "거의 무시할 수 있는 상관관계"

    direction = "양(+)의 상관관계" if r_corr >= 0 else "음(-)의 상관관계"

    # Chart.js 산점도 데이터 생성
    scatter_points = []
    for _, row in valid_df.iterrows():
        scatter_points.append({
            "x": sanitize_value(row["_x"]),
            "y": sanitize_value(row["_y"]),
            "label": str(row[label_col])
        })

    chart_data = {
        "type": "scatter",
        "data": {
            "datasets": [
                {
                    "label": f"{x_col} vs {y_col} (r = {round(r_corr, 4)})",
                    "data": scatter_points,
                    "backgroundColor": "#3b82f6"
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{x_col}와(과) {y_col}의 상관관계 산점도"}
            },
            "scales": {
                "x": {"title": {"display": True, "text": x_col}},
                "y": {"title": {"display": True, "text": y_col}}
            }
        }
    }

    return {
        "tool": "correlation_scatter",
        "result": {
            "x_column": x_col,
            "y_column": y_col,
            "pearson_r": float(round(r_corr, 4)),
            "r_squared": float(round(r_squared, 4)),
            "interpretation": f"{direction} ({strength})",
            "sample_size": int(len(valid_df))
        },
        "chart_data": chart_data,
        "reference_period": ref_str,
        "used_rows": int(len(valid_df)),
        "excluded_rows": agg_excluded + na_excluded,
        "excluded_reasons": reasons,
        "used_columns": [label_col, x_col, y_col],
        "unit": "피어슨 상관계수 (r)",
        "caution": "⚠️ [중요 경고] 상관관계는 인과관계가 아닙니다. 두 변수가 함께 증가한다고 해서 한쪽이 다른 쪽의 원인이 되지는 않으며, 제3의 잠재 변수(예: 경제 성장)가 작용했을 수 있습니다."
    }


# ==============================================================================
# 도구 12: compare_one_vs_all (특정 항목 vs 전체 평균·중앙값 강조 막대)
# ==============================================================================
def compare_one_vs_all(df, reference_period=None, target_item="Korea, Rep.", value_column=None,
                       label_column=None, exclude_aggregates=True, **kwargs):
    """
    특정 국가/항목(예: 대한민국)의 수치와 전체 평균, 중앙값을 정면 비교하고 세계 내 백분위 순위를 도출합니다.
    [공통 규칙]: reference_period 필수!
    """
    if not reference_period:
        raise ValueError("compare_one_vs_all 도구를 실행하려면 'reference_period(기준 시점)' 파라미터가 필수입니다.")

    ref_str = str(reference_period).strip()
    val_col = value_column or ref_str
    if val_col not in df.columns:
        raise ValueError(f"데이터셋에 기준 시점 열 '{val_col}'이 존재하지 않습니다.")

    label_col = detect_label_column(df, label_column)
    filtered_df, agg_excluded, reasons = filter_dataframe(df, exclude_aggregates, label_col)

    s_num = pd.to_numeric(filtered_df[val_col], errors='coerce')
    valid_mask = s_num.notna()
    na_excluded = int((~valid_mask).sum())
    if na_excluded > 0:
        reasons.append(f"기준 시점({ref_str}) 수치가 없는 행 {na_excluded}개 제외")

    valid_df = filtered_df[valid_mask].copy()
    valid_df["_val_num"] = s_num[valid_mask]

    # 대상 항목 탐색 (한국 등 부분 일치 지원)
    target_matches = valid_df[valid_df[label_col].astype(str).str.lower() == target_item.lower()]
    if len(target_matches) == 0:
        # 부분 일치 검색 (예: 'korea' 검색 시 'Korea, Rep.' 매칭)
        target_matches = valid_df[valid_df[label_col].astype(str).str.lower().str.contains(target_item.lower())]

    if len(target_matches) == 0:
        raise ValueError(f"기준 시점({ref_str}) 유효 데이터 내에서 대상 항목 '{target_item}'을 찾을 수 없습니다.")

    target_row = target_matches.iloc[0]
    target_actual_name = str(target_row[label_col])
    target_val = float(round(target_row["_val_num"], 4))

    # 전체 통계치 산출
    overall_mean = float(round(valid_df["_val_num"].mean(), 4))
    overall_median = float(round(valid_df["_val_num"].median(), 4))
    diff_from_mean = float(round(target_val - overall_mean, 4))
    diff_from_median = float(round(target_val - overall_median, 4))

    # 순위 및 백분위 계산
    valid_df_sorted = valid_df.sort_values(by="_val_num", ascending=False).reset_index(drop=True)
    target_rank = int((valid_df_sorted["_val_num"] > target_val).sum()) + 1
    total_valid = int(len(valid_df))
    percentile = round(((total_valid - target_rank + 1) / total_valid * 100), 2)

    # Chart.js 강조 막대그래프 (선택 항목만 다른 색상으로 강조)
    chart_data = {
        "type": "bar",
        "data": {
            "labels": [target_actual_name, "전체 평균", "전체 중앙값"],
            "datasets": [
                {
                    "label": f"{ref_str}년 수치 비교",
                    "data": [target_val, overall_mean, overall_median],
                    "backgroundColor": ["#ef4444", "#3b82f6", "#10b981"]
                }
            ]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": f"{target_actual_name} vs 전 세계 벤치마크 ({ref_str}년)"}
            }
        }
    }

    return {
        "tool": "compare_one_vs_all",
        "result": {
            "target_item": target_actual_name,
            "reference_period": ref_str,
            "target_value": target_val,
            "overall_mean": overall_mean,
            "overall_median": overall_median,
            "diff_from_mean": diff_from_mean,
            "diff_from_median": diff_from_median,
            "rank": target_rank,
            "total_items": total_valid,
            "percentile": percentile
        },
        "chart_data": chart_data,
        "reference_period": ref_str,
        "used_rows": total_valid,
        "excluded_rows": agg_excluded + na_excluded,
        "excluded_reasons": reasons,
        "used_columns": [label_col, val_col],
        "unit": "수치 (기준 단위)",
        "caution": f"전체 평균({overall_mean})은 모든 국가를 동등한 1표로 계산한 단순 평균이므로 인구 가중 평균과는 다릅니다."
    }


# ==============================================================================
# Gemini 제안용 도구 카탈로그 정의
# ==============================================================================
TOOL_CATALOG = [
    {
        "name": "reshape_wide_to_long",
        "title": "연도 열을 행으로 접기 (롱 포맷 변환)",
        "description": "가로로 길게 나열된 연도 열들을 세로 형태([식별자, 연도, 값])로 언피벗하여 시계열 분석을 가능하게 합니다.",
        "requires_reference_period": False,
        "chart_supported": False
    },
    {
        "name": "quality_report",
        "title": "데이터 품질 종합 진단",
        "description": "열별 결측치 비율, 중복 행, 이상 열 이름(Unnamed), 고유값 수를 한눈에 파악합니다.",
        "requires_reference_period": False,
        "chart_supported": False
    },
    {
        "name": "year_coverage",
        "title": "연도별 데이터 수집 완성도",
        "description": "연도별 유효 데이터 수를 계산하고 가장 완성도가 높은 최신 기준연도를 추천합니다.",
        "requires_reference_period": False,
        "chart_supported": True
    },
    {
        "name": "detect_aggregates",
        "title": "집계/그룹 묶음 행 감지",
        "description": "전체 통계를 왜곡할 수 있는 World, OECD, 소득군 등 묶음 통계 행을 찾아 분리합니다.",
        "requires_reference_period": False,
        "chart_supported": True
    },
    {
        "name": "describe_numeric",
        "title": "기술통계치 요약 (평균/중앙값/분포)",
        "description": "특정 기준연도나 숫자 열의 평균, 중앙값, 표준편차, 최솟값, 최댓값, 분위수를 산출합니다.",
        "requires_reference_period": False,
        "chart_supported": True
    },
    {
        "name": "trend_line",
        "title": "주요 항목 연도별 시계열 추이 비교",
        "description": "선택한 국가/항목들의 연도별 변화 추이를 꺾은선 차트(Line Chart)로 시각화합니다.",
        "requires_reference_period": False,
        "chart_supported": True
    },
    {
        "name": "top_bottom_n",
        "title": "기준연도 상위·하위 랭킹 비교",
        "description": "특정 기준 시점을 기준으로 가장 수치가 높은 상위 N개 및 하위 N개 항목을 순위화합니다.",
        "requires_reference_period": True,
        "chart_supported": True
    },
    {
        "name": "group_summary",
        "title": "대륙/그룹별 평균 및 통계 비교",
        "description": "대륙(Region), 소득군(IncomeGroup) 등 범주별 평균과 중앙값을 그룹화하여 비교합니다.",
        "requires_reference_period": True,
        "chart_supported": True
    },
    {
        "name": "change_rate",
        "title": "두 시점 간 성장량 및 변화율 분석",
        "description": "과거 시점과 기준 시점 사이의 증가량(%p)과 성장률(%)을 계산하여 가장 많이 발전한 국가를 찾습니다.",
        "requires_reference_period": True,
        "chart_supported": True
    },
    {
        "name": "distribution",
        "title": "구간별 수치 분포 (히스토그램)",
        "description": "수치 구간별(예: 0~10%, 10~20%) 빈도를 히스토그램으로 시각화하여 양극화와 격차를 파악합니다.",
        "requires_reference_period": True,
        "chart_supported": True
    },
    {
        "name": "correlation_scatter",
        "title": "두 시점/변수 간 상관관계 분석 (산점도)",
        "description": "두 변수 간의 피어슨 상관계수(r)와 산점도를 분석합니다. (주의: 상관관계는 인과관계가 아님)",
        "requires_reference_period": True,
        "chart_supported": True
    },
    {
        "name": "compare_one_vs_all",
        "title": "특정 항목 vs 전체 평균 벤치마크 비교",
        "description": "특정 국가(예: 대한민국)의 수치와 전 세계 평균, 중앙값을 정면 비교하고 백분위 순위를 확인합니다.",
        "requires_reference_period": True,
        "chart_supported": True
    }
]

def get_tool_catalog():
    """Gemini API에 전달할 12개 도구 목록 반환"""
    return TOOL_CATALOG
