"""Tool 1: 产业链影响分析 —— 列昂惕夫投入产出模型 X = (I-A)^(-1) Y"""
import json
import numpy as np

from ..config import DATA_DIR

_IO = json.loads((DATA_DIR / "io_table.json").read_text(encoding="utf-8"))
SECTOR_NAMES = [s["name"] for s in _IO["sectors"]]
A = np.array(_IO["A"], dtype=float)
X_BASE = np.array(_IO["base_output"], dtype=float)
Y_BASE = np.array(_IO["base_final_demand"], dtype=float)
DEBT = _IO["debt_ratio"]
N = len(SECTOR_NAMES)

# 房地产投资冲击直接作用的部门（资本形成端）
RE_SECTORS = ["房地产", "建筑业"]


def leontief_inverse(a: np.ndarray) -> np.ndarray:
    """完全需求系数矩阵 L = (I - A)^(-1)"""
    return np.linalg.inv(np.eye(len(a)) - a)


def impact_multiplier(a: np.ndarray, j: int) -> float:
    """部门j最终需求变动1单位对总产出的拉动（后向联动乘数）"""
    return float(leontief_inverse(a)[:, j].sum())


def analyze_shock(shock_percent: float, direction: str = "下降",
                  shock_sectors=None) -> dict:
    """
    房地产冲击的产业链影响矩阵。
    shock_percent: 冲击幅度（正数，如15表示15%）
    direction: "下降" 或 "上升"
    """
    sectors = shock_sectors or RE_SECTORS
    sign = -1.0 if direction in ("下降", "下跌", "回落") else 1.0
    dY = np.zeros(N)
    for s in sectors:
        if s in SECTOR_NAMES:
            i = SECTOR_NAMES.index(s)
            dY[i] = sign * (shock_percent / 100.0) * Y_BASE[i]

    L = leontief_inverse(A)
    dX = L @ dY  # 总产出变动（直接+间接）

    rows = []
    for i, name in enumerate(SECTOR_NAMES):
        impact_pct = float(dX[i] / X_BASE[i] * 100.0)
        direct = float(dY[i])
        indirect = float(dX[i] - dY[i])
        if abs(impact_pct) < 0.01 and abs(dX[i]) < 50:
            continue
        rows.append({
            "industry": name,
            "delta_output_yi": round(float(dX[i]), 1),      # 亿元
            "impact_pct": round(impact_pct, 2),              # 产出变动%
            "direct_effect_yi": round(direct, 1),
            "indirect_effect_yi": round(indirect, 1),
            "multiplier": round(float(dX[i] / dY[i]), 2) if abs(dY[i]) > 1 else None,
            "debt_ratio": DEBT.get(name, 50),
        })
    rows.sort(key=lambda r: abs(r["impact_pct"]), reverse=True)

    total_delta = float(dX.sum())
    return {
        "model": "Leontief Input-Output Model, X = (I-A)^(-1) Y",
        "scenario": (f"房地产—建筑业联合最终需求{direction} {shock_percent}%（复合压力测试情景："
                     f"将冲击等幅施加于房地产与建筑业最终需求，非对单一现实指标的一一映射）"
                     if len(sectors) > 1 else
                     f"{sectors[0]}最终需求{direction} {shock_percent}%"),
        "sector_order": SECTOR_NAMES,
        "impact_matrix": rows,
        "total_output_change_yi": round(total_delta, 1),
        "total_output_change_pct": round(total_delta / float(X_BASE.sum()) * 100, 3),
        "real_estate_multiplier": round(impact_multiplier(A, SECTOR_NAMES.index("房地产")), 2),
        "construction_multiplier": round(impact_multiplier(A, SECTOR_NAMES.index("建筑业")), 2),
        "transmission_stages": _stage_forecast(rows, shock_percent, direction),
    }


def _stage_forecast(rows: list, shock_pct: float, direction: str, kind: str = "demand") -> dict:
    """传导三阶段预判：需求侧用六案例归纳框架，供给侧用供给约束传导框架"""
    import json as _json
    from ..config import DATA_DIR as _DD
    try:
        fw = _json.loads((_DD / "transmission_stages.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    if direction == "上升" or shock_pct == 0:
        return {}
    stage_list = fw.get("stages_supply") if kind == "supply" else fw.get("stages")
    if not stage_list:
        return {}
    impact_by_ind = {r["industry"]: r["impact_pct"] for r in rows}
    severity = min(abs(shock_pct) / 30.0, 1.0)  # 冲击幅度 → 严重度 0~1
    stages = []
    for st in stage_list:
        # 各阶段命中行业 × 该行业受冲击幅度 → 阶段压力分（0~100）
        hits = []
        for ind in st["hit_industries"]:
            p = impact_by_ind.get(ind)
            if p is not None:
                hits.append({"industry": ind, "impact_pct": p})
        pressure = min(100, round(severity * st["hit_hardness"] / 3 * 100
                                  + sum(abs(h["impact_pct"]) for h in hits) / max(len(hits), 1) * 3))
        stages.append({
            "name": st["name"], "window": st["window"],
            "mechanism": st["mechanism"], "channels": st["channels"],
            "hit_industries": st["hit_industries"],
            "verify_indicators": st["verify_indicators"],
            "case_evidence": st["case_evidence"],
            "pressure": pressure,
        })
    if kind == "supply":
        meta = {"framework": fw.get("framework_supply", ""), "source": fw.get("source_supply", ""),
                "cross_case_rules": fw.get("cross_case_rules_supply", [])}
    else:
        meta = {"framework": fw.get("framework", ""), "source": fw.get("source", ""),
                "cross_case_rules": fw.get("cross_case_rules", [])}
    meta["stages"] = stages
    return meta


def ghosh_supply_shock(shock_sector: str, shock_percent: float, direction: str = "下降") -> dict:
    """Ghosh 供给侧冲击模型（标准口径）：ΔX = ΔV · (I-B)^(-1)

    B 为供给分配系数矩阵，按卖方部门总产出进行系数化：
        B = D⁻¹Z，其中 D = diag(X)，即 B_ij = Z_ij / X_i
    （B 的行和不要求等于 1；与直接消耗矩阵的关系：B = D⁻¹AD，相似矩阵
    谱半径相同 ρ(B)=ρ(A)<1，因此 (I-B) 可正常求逆。）

    口径提示：竞争型投入产出表包含进口中间品，B 应解释为各下游部门
    对该产品的中间使用暴露与产业关联强度指标，而不是企业销售预测。
    """
    if shock_sector not in SECTOR_NAMES:
        return {"error": f"未知部门: {shock_sector}"}
    j = SECTOR_NAMES.index(shock_sector)
    sign = -1.0 if direction in ("下降", "下跌", "减产", "回落") else 1.0

    # ---- 供给分配系数矩阵 B = D⁻¹Z（按卖方部门总产出系数化）----
    Z = A * X_BASE[None, :]                          # 中间流量矩阵（亿元）
    B = Z / np.where(X_BASE[:, None] > 0, X_BASE[:, None], np.inf)
    B = np.nan_to_num(B)
    G = np.linalg.inv(np.eye(N) - B)                 # Ghosh 逆矩阵 (I-B)^(-1)

    # ---- 冲击向量：部门初始投入（增加值）变动 ----
    VA = X_BASE - (A * X_BASE[None, :]).sum(axis=0)  # 各部门增加值
    dV = np.zeros(N)
    dV[j] = sign * (shock_percent / 100.0) * VA[j]
    dX = dV @ G                                      # 行向量左乘 Ghosh 逆

    rows = []
    for i, name in enumerate(SECTOR_NAMES):
        impact_pct = float(dX[i] / X_BASE[i] * 100.0)
        if abs(impact_pct) < 0.05:
            continue
        rows.append({"industry": name, "impact_pct": round(impact_pct, 2),
                     "delta_output_yi": round(float(dX[i]), 1),
                     "debt_ratio": DEBT.get(name, 55)})
    rows.sort(key=lambda r: abs(r["impact_pct"]), reverse=True)

    # 供给推动乘数：部门j初始投入变动1单位对总产出的拉动（Ghosh 逆第 j 行和）
    supply_mult = float(G[j, :].sum())
    return {
        "model": "Ghosh Supply-Side Model, ΔX = ΔV·(I-B)^(-1)",
        "scenario": f"{shock_sector}供给侧（增加值）{direction} {shock_percent}%",
        "sector_order": SECTOR_NAMES,
        "impact_matrix": rows,
        "total_output_change_yi": round(float(dX.sum()), 1),
        "transmission_stages": _stage_forecast(rows, shock_percent, direction, kind="supply"),
        "total_output_change_pct": round(float(dX.sum()) / float(X_BASE.sum()) * 100, 3),
        "real_estate_multiplier": round(impact_multiplier(A, SECTOR_NAMES.index("房地产")), 2),
        "construction_multiplier": round(impact_multiplier(A, SECTOR_NAMES.index("建筑业")), 2),
        "supply_multiplier": round(supply_mult, 2),
        "note": "标准Ghosh口径（B=D⁻¹Z，按卖方部门总产出系数化，与A相似故谱半径相同可稳定求逆）。"
                "竞争型投入产出表包含进口中间品，B反映各下游部门对该产品的中间使用暴露强度；"
                "测算结果应解读为供给侧投入压力沿产业链传导的情景值，"
                "而非对全国各行业实际产出变化的确定性预测",
    }


def supply_chain_graph(impact: dict | None = None) -> dict:
    """生成产业链关系图（供前端 ECharts graph）"""
    nodes, links = [], []
    weight = {r["industry"]: abs(r["impact_pct"]) for r in (impact or {}).get("impact_matrix", [])}
    for i, name in enumerate(SECTOR_NAMES):
        nodes.append({
            "id": name, "name": name,
            "value": round(weight.get(name, 0), 2),
            "symbolSize": 30 + min(weight.get(name, 0) * 6, 45),
            "category": 0 if name in ("房地产", "建筑业") else 1,
        })
    for j, to in enumerate(SECTOR_NAMES):
        for i, frm in enumerate(SECTOR_NAMES):
            w = A[i][j]
            if w >= 0.03:
                links.append({"source": frm, "target": to, "value": round(float(w), 3)})
    return {"nodes": nodes, "links": links}
