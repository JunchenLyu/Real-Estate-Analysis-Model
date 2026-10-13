"""可追溯的描述性产业关联分析，不参与风险评分或因果推断。"""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "research_monthly.json"


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def import_long_cycle(path):
    from openpyxl import load_workbook

    path = Path(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    series, fields = {}, []
    try:
        for sheet in list(workbook)[:2]:
            rows = list(sheet.values)
            headers = rows[0]
            for col, name in enumerate(headers[1:], 1):
                if not name or "施工" in name:
                    continue
                cumulative = {}
                for row in rows[1:]:
                    month = str(row[0])
                    try:
                        datetime.strptime(month, "%Y-%m")
                    except ValueError:
                        raise ValueError(f"非法月份：{month}") from None
                    if month in cumulative:
                        raise ValueError(f"重复月份：{month}")
                    cumulative[month] = float(row[col]) if _finite(row[col]) else None
                monthly = {}
                for month, value in sorted(cumulative.items()):
                    year, number = map(int, month.split("-"))
                    previous = cumulative.get(f"{year}-{number - 1:02d}")
                    if number >= 3 and value is not None and previous is not None:
                        change = value - previous
                        if change >= 0:
                            monthly[month] = change
                growth = {}
                for month, value in monthly.items():
                    year, number = map(int, month.split("-"))
                    base = monthly.get(f"{year - 1}-{number:02d}")
                    if base is not None and base > 0:
                        growth[month] = round((value / base - 1) * 100, 6)
                key = str(name).split("_", 1)[0].replace("累计", "") + "当月同比"
                series[key] = growth
                fields.append({"name": key, "sheet": sheet.title, "column": name,
                               "unit": "%", "sample_count": len(growth),
                               "processing": "同年相邻累计值差分为当月量，再与上年同月比较；不插值"})
    finally:
        workbook.close()
    if not series or any(len(values) < 24 for values in series.values()):
        raise ValueError("有效同口径样本不足24个，拒绝发布数据集")
    return {"dataset_id": "long_cycle_monthly_yoy", "metadata": {
        "source_file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "region": "全国", "frequency": "月度", "unit": "%",
        "verification": "用户提供资料，尚未逐项核对原始发布数据",
        "processing": "累计流量差分后计算当月同比；排除施工面积存量；1—2月合并值不拆分",
        "warnings": ["1月、2月无独立月度值，保持缺失，不做插值或跨年差分。",
                     "累计值统计修订可能影响差分；同比重叠、共同趋势及样本选择均可能影响相关性。",
                     "资料中的企业季度样本及信用指标未接入；结果不代表全行业或因果效应。"]},
        "fields": fields, "series": series}


def load_dataset():
    if not DATA_FILE.exists():
        raise ValueError("长周期研究数据尚未导入")
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def grey_relation(reference, candidates, rho=0.5):
    if not 0 < rho <= 1:
        raise ValueError("分辨系数必须在(0,1]内")
    if not candidates:
        raise ValueError("至少选择一个比较序列")
    dates = sorted(set(reference).intersection(*(set(s) for s in candidates.values())))
    dates = [d for d in dates if _finite(reference[d]) and all(_finite(s[d]) for s in candidates.values())]
    if len(dates) < 12:
        raise ValueError("共同有效样本不足12个")

    def normalize(values):
        array = np.array(values, dtype=float)
        span = np.ptp(array)
        if span <= 1e-12:
            raise ValueError("常量序列不能进行趋势关联分析")
        return (array - array.min()) / span

    ref = normalize([reference[d] for d in dates])
    differences = {name: np.abs(normalize([s[d] for d in dates]) - ref)
                   for name, s in candidates.items()}
    minimum = min(float(v.min()) for v in differences.values())
    maximum = max(float(v.max()) for v in differences.values())
    rows = [{"name": name, "grade": round(float(((minimum + rho * maximum) /
             (v + rho * maximum)).mean()), 6) if maximum > 1e-12 else 1.0}
            for name, v in differences.items()]
    return {"method": "Deng灰色关联；各序列极差标准化；全体比较序列统一差值极值",
            "rho": rho, "sample_count": len(dates), "start": dates[0], "end": dates[-1],
            "ranking": sorted(rows, key=lambda row: -row["grade"]),
            "warnings": ["灰色关联度衡量形状接近程度，不是相关系数、传导强度或因果概率。",
                         "排名取决于日期范围、比较序列集合及标准化方式。"]}


def _shift(month, offset):
    year, number = map(int, month.split("-"))
    index = year * 12 + number - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _correlation(pairs):
    if len(pairs) < 12:
        return None
    x, y = np.array(pairs, dtype=float).T
    if np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
        return None
    return round(float(np.corrcoef(x, y)[0, 1]), 6)


def lag_correlation(x, y, max_lag=12, window=24):
    if not 0 <= max_lag <= 24 or not 12 <= window <= 60:
        raise ValueError("最大时滞应为0—24月，滚动窗口应为12—60月")
    lags = []
    for lag in range(-max_lag, max_lag + 1):
        pairs = [(v, y[_shift(d, lag)]) for d, v in sorted(x.items())
                 if _finite(v) and _finite(y.get(_shift(d, lag)))]
        lags.append({"lag_months": lag, "correlation": _correlation(pairs), "sample_count": len(pairs)})
    eligible = [row for row in lags if row["correlation"] is not None]
    best = max(eligible, key=lambda row: abs(row["correlation"])) if eligible else None
    dates = sorted(set(x) | set(y))
    rolling = []
    if dates:
        month = dates[0]
        while month <= dates[-1]:
            start = _shift(month, 1 - window)
            if start >= dates[0]:
                pairs = [(v, y[d]) for d, v in x.items()
                         if start <= d <= month and _finite(v) and _finite(y.get(d))]
                rolling.append({"month": month, "correlation": _correlation(pairs), "sample_count": len(pairs)})
            month = _shift(month, 1)
    return {"method": "Pearson时差相关与同步滚动相关（逐月日历对齐）",
            "lag_definition": "corr(X_t, Y_(t+k))；k>0表示X领先Y，k<0表示Y领先X",
            "max_lag": max_lag, "window_months": window, "lags": lags,
            "strongest_absolute_correlation": best, "rolling": rolling,
            "warnings": ["最大绝对相关仅是样本内扫描结果，不是已确认的传导时滞。",
                         "未校正多重比较、序列自相关或控制共同因素；不作显著性、预测或因果声明。",
                         "滚动窗口按日历月计算，缺失值不填充；少于12对样本或常量窗口不计算。"]}


def network_metrics(matrix, names):
    a = np.array(matrix, dtype=float)
    n = len(names)
    if n == 0 or a.shape != (n, n) or not np.isfinite(a).all() or (a < 0).any():
        raise ValueError("网络矩阵必须为与节点数一致的非负有限方阵")
    weights = a.copy()
    np.fill_diagonal(weights, 0)
    outgoing = weights.sum(axis=1)
    transition = np.divide(weights, outgoing[:, None], out=np.zeros_like(weights), where=outgoing[:, None] > 0)
    transition[outgoing == 0] = 1 / n
    rank = np.full(n, 1 / n)
    for _ in range(1000):
        updated = 0.15 / n + 0.85 * (transition.T @ rank)
        if np.linalg.norm(updated - rank, 1) < 1e-12:
            rank = updated
            break
        rank = updated
    rows = [{"name": name, "in_strength": round(float(weights[:, i].sum()), 6),
             "out_strength": round(float(outgoing[i]), 6), "pagerank": round(float(rank[i]), 6)}
            for i, name in enumerate(names)]
    return {"method": "直接消耗系数有向加权网络；排除自环；PageRank阻尼系数0.85",
            "edge_direction": "供应行业i → 使用行业j，边权A_ij（非货币交易额）",
            "edge_count": int(np.count_nonzero(weights)), "node_count": n,
            "ranking": sorted(rows, key=lambda row: -row["pagerank"]),
            "warnings": ["所有非零边参与计算，不使用展示阈值；结果仅代表所选13部门子网络。",
                         "中心性不是系统性风险概率，也不是GNN训练结果或全国网络。"]}
