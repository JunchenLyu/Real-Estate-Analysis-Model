"""Step 3: Agent Tool Schema（OpenAI Function Calling 格式）与工具执行分发"""
from ..knowledge import rag, cases as kb_cases
from ..models import input_output as io
from ..models import risk as risk_model

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "检索房地产金融知识库（研究论文/投入产出模型资料/政策文件/历史风险案例）。回答任何金融问题前必须优先调用本工具获取依据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题，如'房地产投资下降对上游产业链的影响'"},
                    "top_k": {"type": "integer", "description": "返回条数，默认4", "default": 4},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_industry_chain_impact",
            "description": "基于列昂惕夫投入产出模型 X=(I-A)^(-1)Y，测算房地产需求侧冲击对各行业产出的影响矩阵（直接效应+间接效应）。适用于'投资/销售/需求 上升下降'类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "shock_percent": {"type": "number", "description": "冲击幅度百分比，正数，如15代表15%"},
                    "direction": {"type": "string", "enum": ["下降", "上升"], "description": "冲击方向"},
                },
                "required": ["shock_percent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_supply_shock",
            "description": "基于Ghosh供给侧模型（标准口径 ΔX=ΔV·(I-B)⁻¹，B=D⁻¹Z 为供给分配系数矩阵），测算某行业初始投入（增加值）收缩对全行业产出的影响。适用于'初始投入收缩/资源供给收缩/减产'等数量型供给冲击问题——系统将数量型供给收缩情景映射为同幅度的初始投入冲击进行压力测试，两者非严格等价。注意：价格/成本冲击（如'涨价'）属价格效应，本工具不做精确量化，仅作定性提示。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector": {"type": "string", "description": "冲击行业，如'钢铁'、'建材'、'电力热力'"},
                    "shock_percent": {"type": "number", "description": "初始投入变动幅度百分比，正数"},
                    "direction": {"type": "string", "enum": ["下降", "上升"], "description": "初始投入变动方向"},
                },
                "required": ["sector", "shock_percent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_risk_score",
            "description": "情景风险评分模型（0-100，横向压力比较口径）：四指标加权（收入/债务/现金流/市场需求）。注意：产业链情景中收入、现金流、市场需求分项由冲击测算结果经规则映射得到（代理变量），债务分项采用行业基准负债率；该评分用于受冲击行业间的横向压力比较，并非企业信用评级。",
            "parameters": {
                "type": "object",
                "properties": {
                    "industry": {"type": "string", "description": "行业名称"},
                    "revenue_change": {"type": "number", "description": "收入同比变化%，如-10"},
                    "debt_ratio": {"type": "number", "description": "资产负债率%，如78"},
                    "cash_flow_change": {"type": "number", "description": "经营现金流变化%，如-20"},
                    "market_change": {"type": "number", "description": "市场需求变化%，如-12"},
                },
                "required": ["industry", "revenue_change", "debt_ratio", "cash_flow_change", "market_change"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_similar_cases",
            "description": "检索结构化房地产风险案例与待核验研究线索，用于历史对比和机制参照；带证据状态的条目不得作为已证实事实。",
            "parameters": {
                "type": "object",
                "properties": {
                    "event": {"type": "string", "description": "风险事件描述"},
                    "top_k": {"type": "integer", "default": 2},
                },
                "required": ["event"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_uploaded_data",
            "description": "分析用户上传的数据文件（CSV/Excel），获取统计摘要与风险指标计算结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "上传文件ID"},
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_data",
            "description": "获取风险仪表盘数据：行业风险评分、产业链关系图、历史对比序列。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name: str, arguments: dict, ctx: dict | None = None,
                 question: str = "") -> dict:
    """统一工具执行入口。ctx: {'uploads': {file_id: summary}}
    完整路由守卫：校验 LLM 选择的模型与问题语义是否匹配（服务端硬校验，
    即使 LLM 发错 tool call 也不会执行错误模型）。"""
    ctx = ctx or {}
    # ---- 服务端路由守卫 ----
    from .core_guards import check_tool_allowed
    if name == "compute_risk_score":
        return {"blocked": True, "reason": "风险评分由确定性行业模型或上传数据计算，不接受 LLM 自行提供的指标"}
    if name in ("analyze_industry_chain_impact", "analyze_supply_shock"):
        allowed, reason = check_tool_allowed(name, question)
        if not allowed:
            return {"blocked": True, "reason": reason,
                    "note": "已按模型适用边界拦截本次数量模型调用，请改用定性分析或正确模型"}
        # ---- Canonical Scenario：数量模型参数由服务端从用户原话解析，
        #      不采信 LLM 提交的 shock_percent/direction/sector（防参数篡改与脑补） ----
        from .core import _parse_shock, _supply_sector
        pct, direction, has = _parse_shock(question)
        if not has:
            return {"error": "用户问题未提供明确的量化冲击幅度（shock_percent），本次不执行数量模型",
                    "blocked": True, "final": True,
                    "instruction": "禁止再次调用任何数量模型；请立即基于知识库检索结果输出定性机制分析"}
        if name == "analyze_supply_shock":
            sector_s = _supply_sector(question)
            if not sector_s:
                return {"error": "无法将问题中的行业映射到模型 13 部门口径，本次不执行数量模型",
                        "blocked": True, "final": True,
                        "instruction": "该行业超出模型 13 部门覆盖范围，禁止再次调用任何数量模型；"
                                       "请立即基于知识库检索结果输出定性机制分析，并建议用户明确行业口径"}
            arguments = {"sector": sector_s,
                         "shock_percent": pct, "direction": direction}
        else:
            arguments = {"shock_percent": pct, "direction": direction}
    if name == "search_knowledge_base":
        return {"results": rag.search(arguments.get("query", ""), arguments.get("top_k", 4))}
    if name == "analyze_industry_chain_impact":
        sp = arguments.get("shock_percent")
        if sp is None:
            return {"error": "未提供明确的量化冲击幅度（shock_percent），本次不执行数量模型",
                    "blocked": True, "final": True,
                    "instruction": "禁止再次调用任何数量模型；请立即输出定性机制分析"}
        return io.analyze_shock(float(sp), arguments.get("direction", "下降"))
    if name == "analyze_supply_shock":
        sp = arguments.get("shock_percent")
        if sp is None:
            return {"error": "未提供明确的量化冲击幅度（shock_percent），本次不执行数量模型",
                    "blocked": True, "final": True,
                    "instruction": "禁止再次调用任何数量模型；请立即输出定性机制分析"}
        return io.ghosh_supply_shock(
            arguments.get("sector", "钢铁"),
            float(sp),
            arguments.get("direction", "下降"),
        )
    if name == "compute_risk_score":
        return risk_model.compute_risk_score(
            revenue_change=float(arguments.get("revenue_change", 0)),
            debt_ratio=float(arguments.get("debt_ratio", 50)),
            cash_flow_change=float(arguments.get("cash_flow_change", 0)),
            market_change=float(arguments.get("market_change", 0)),
        ) | {"industry": arguments.get("industry", "")}
    if name == "retrieve_similar_cases":
        res = kb_cases.retrieve_similar_cases(arguments.get("event", ""), arguments.get("top_k", 2))
        # 二次校验：案例必须与用户原始问题相关（防 LLM 改写 event 塞入无关案例）
        res = kb_cases.filter_by_question(res, question)
        if not res:
            return {"cases": [],
                    "note": "当前案例库未检索到与该问题高度相关的案例，不作历史案例强行类比"}
        return {"cases": res}
    if name == "analyze_uploaded_data":
        fid = arguments.get("file_id", "")
        summary = ctx.get("uploads", {}).get(fid)
        return summary or {"error": f"未找到文件 {fid}，请确认已上传"}
    if name == "get_dashboard_data":
        return ctx.get("dashboard", {})
    return {"error": f"未知工具: {name}"}
