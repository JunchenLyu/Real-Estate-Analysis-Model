"""数据上传分析服务：CSV/Excel → 统计摘要 + 指标识别 + 风险评分"""
import math

import pandas as pd


def _finite_stat(value):
    number = float(value)
    return round(number, 2) if math.isfinite(number) else None

from ..models import risk as risk_model

INDICATOR_MAP = {  # 列名关键词 → 指标
    "收入": "revenue", "营收": "revenue", "销售额": "revenue",
    "负债率": "debt", "资产负债率": "debt",
    "现金流": "cashflow", "现金": "cashflow",
    "需求": "market", "市场": "market", "价格": "market", "房价": "market",
}


def analyze_file(path: str, filename: str) -> dict:
    df = pd.read_csv(path) if filename.lower().endswith(".csv") else pd.read_excel(path)
    summary = {
        "filename": filename,
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing": {c: int(v) for c, v in df.isna().sum().items() if v > 0},
        "describe": {},
    }
    num_cols = df.select_dtypes("number").columns
    for c in num_cols:
        s = df[c].dropna()
        if len(s):
            summary["describe"][c] = {
                "mean": _finite_stat(s.mean()), "std": _finite_stat(s.std()),
                "min": _finite_stat(s.min()), "max": _finite_stat(s.max()),
                "latest": _finite_stat(s.iloc[-1]),
            }

    # 识别风险指标列 → 若齐全则计算风险评分
    detected = {}
    change_markers = ("变化", "变动", "同比", "环比", "增速", "增长", "下降", "%", "百分比")
    for col in df.columns:
        for kw, tag in INDICATOR_MAP.items():
            if kw not in col:
                continue
            # 风险模型接收的是变动百分比；绝对收入、现金流、价格不能直接当作百分比。
            if tag in {"revenue", "cashflow", "market"} and not any(
                    marker in str(col) for marker in change_markers):
                continue
            detected[tag] = col
            break
    if not df.empty and {"revenue", "debt"} <= detected.keys():
        last = df.iloc[-1]
        values = {tag: pd.to_numeric(last[col], errors="coerce")
                  for tag, col in detected.items()}
        if all(pd.notna(v) and math.isfinite(float(v)) for v in values.values()):
            result = risk_model.compute_risk_score(
                revenue_change=float(values["revenue"]),
                debt_ratio=float(values["debt"]),
                cash_flow_change=float(values.get("cashflow", 0)),
                market_change=float(values.get("market", 0)),
            )
            summary["risk_evaluation"] = {
                "detected_indicators": {k: str(v) for k, v in detected.items()},
                **result,
            }
        else:
            summary["risk_evaluation_note"] = "最新一期风险指标存在缺失、非数值或非有限值，未计算评分。"
    summary["analysis_note"] = (
        f"数据共 {df.shape[0]} 行 × {df.shape[1]} 列，数值列 {len(num_cols)} 个。"
        + (f"识别到风险指标并完成评分：{summary['risk_evaluation']['risk_score']}（{summary['risk_evaluation']['risk_level']}）。"
           if "risk_evaluation" in summary else "未识别到完整的风险指标列（收入/负债率等）。")
    )
    return summary
