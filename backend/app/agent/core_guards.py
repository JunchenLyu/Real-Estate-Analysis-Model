"""模型适用边界守卫（服务端硬校验，架构级模型路由保证）

完整路由守卫：不仅拦截价格/房价问题，还校验 LLM 选择的模型是否与问题类型匹配：
  - 数量型需求冲击（房地产投资/销售…）→ 仅允许 Leontief
  - 数量型供给冲击（钢铁减产/供给收缩…）→ 仅允许 Ghosh
  - 价格/成本、房价（资产价格）问题 → 禁止一切数量模型
不信任 LLM 对提示词的遵守，服务端最终裁决。
"""


def _has_house_price(q: str) -> bool:
    return any(k in q for k in ("房价上涨", "房价下降", "房价下跌", "房价涨", "房价跌", "房价上升"))


def _has_price(q: str) -> bool:
    return any(k in q for k in ("涨价", "降价", "价格", "成本上升", "成本上涨", "成本下降", "原材料上涨"))


def _has_supply(q: str) -> bool:
    return any(k in q for k in ("减产", "增产", "供给收缩", "供给下降", "供给增加", "停产", "限产", "供给减少"))


def scenario_status(question: str) -> str:
    """在线和离线共用的情景分类，不依赖 LLM 是否尝试调用工具。"""
    from .core import _is_supply_side, _supply_sector
    if _has_house_price(question) and not any(
        k in question for k in ("投资", "新开工", "销售面积", "施工")
    ):
        return "asset_price_qualitative"
    if _has_price(question):
        return "price_qualitative"
    supply = _is_supply_side(question)
    demand = any(k in question for k in ("房地产", "房产", "楼市", "开发")) and any(
        k in question for k in ("投资", "销售", "新开工", "施工", "需求")
    )
    if not has_explicit_shock(question):
        return "missing_magnitude" if supply or demand else "knowledge_only"
    if supply:
        return "quantified_ghosh" if _supply_sector(question) else "sector_unresolved"
    if demand:
        return "quantified_leontief"
    return "sector_unresolved"


def has_explicit_shock(question: str) -> bool:
    """是否存在明确的数量冲击幅度（如'下降15%'、'减产10%'）。
    模型运行的前提条件：没有明确幅度的问题不进入数量模型（防 LLM 脑补默认值）。"""
    from .core import _parse_shock
    return _parse_shock(question)[2]


def expected_model(question: str) -> str:
    """按问题语义判定应使用的模型：'leontief' / 'ghosh' / 'qualitative' / 'none'
    'qualitative' = 价格/成本冲击或房价（资产价格）变化 → 定性机制分析；
    'none' = 无明确量化冲击幅度，或行业无法映射到模型 13 部门口径 → 数量模型全部禁止。
    注意：价格/房价判断优先于幅度检查（带幅度的价格冲击仍属定性范畴）。"""
    status = scenario_status(question)
    if status == "quantified_ghosh":
        return "ghosh"
    if status == "quantified_leontief":
        return "leontief"
    if status in ("price_qualitative", "asset_price_qualitative"):
        return "qualitative"
    return "none"


def quantity_model_allowed(question: str) -> tuple[bool, str]:
    """旧接口兼容：数量模型（Leontief/Ghosh）是否被允许"""
    em = expected_model(question)
    if em == "qualitative":
        return False, _qualitative_reason(question)
    if em == "none":
        return False, _unresolved_reason(question)
    return True, ""


def check_tool_allowed(tool: str, question: str) -> tuple[bool, str]:
    """完整路由守卫：校验模型调用是否满足适用条件。返回 (allowed, reason)。
    四层检查：明确冲击幅度 → 问题类型 → 模型匹配。"""
    em = expected_model(question)
    if em == "none":
        if tool in ("analyze_industry_chain_impact", "analyze_supply_shock"):
            return False, _unresolved_reason(question)
        return True, ""
    if em == "qualitative":
        if tool in ("analyze_industry_chain_impact", "analyze_supply_shock"):
            return False, _qualitative_reason(question)
        return True, ""
    if em == "ghosh" and tool == "analyze_industry_chain_impact":
        return False, "本问题属数量型供给冲击，应使用 Ghosh 供给侧模型（analyze_supply_shock），不适用 Leontief 需求侧模型"
    if em == "leontief" and tool == "analyze_supply_shock":
        return False, "本问题属数量型需求冲击，应使用 Leontief 需求侧模型（analyze_industry_chain_impact），不适用 Ghosh 供给侧模型"
    return True, ""


def _unresolved_reason(question: str) -> str:
    if scenario_status(question) == "sector_unresolved":
        return "问题中的冲击行业或需求口径无法映射到当前模型，数量模型不适用；请明确行业及冲击对象"
    return "问题未提供明确的量化冲击幅度（如'下降15%'），数量模型不适用"


def _qualitative_reason(question: str) -> str:
    if _has_house_price(question):
        return "房价变化属资产价格变化，不直接等价于最终需求数量冲击，数量模型不适用"
    if not has_explicit_shock(question):
        return "问题未提供明确的量化冲击幅度，数量模型不适用"
    return "价格/成本冲击属价格效应，Ghosh/Leontief 数量框架不适用，仅作定性机制分析"
