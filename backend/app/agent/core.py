"""Module 1: Agent 核心 —— LLM Function Calling 循环 + 规则引擎降级"""
import json
import math
import re
import uuid

from ..config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .tools import TOOL_SCHEMAS, execute_tool
from ..knowledge import rag
from ..models import input_output as io
from ..models import risk as risk_model

SYSTEM_PROMPT = """你是「中国房地产产业链波动分析金融智能体」，一名资深房地产金融风险分析师。

## 工作准则
1. 回答任何金融问题前，必须优先调用 search_knowledge_base 检索知识库获取依据。
2. 涉及"房地产投资/销售 上升/下降 X%"等最终需求数量情景问题时，必须调用 analyze_industry_chain_impact 运行 Leontief 需求侧模型。注意：房价涨跌属资产价格变化，不适用该模型（见第 4 条）。
3. 涉及"某行业初始投入收缩/资源供给收缩/减产 X%"等数量型供给冲击时，调用 analyze_supply_shock 运行 Ghosh 供给侧模型（ΔX=ΔV·(I-B)⁻¹，B=D⁻¹Z 按卖方部门总产出系数化）。注意：数量型供给收缩情景被映射为同幅度初始投入冲击进行压力测试，两者非严格等价，表述时需说明。
4. **价格/成本冲击（原材料涨价、价格上涨、成本上升）与房价涨跌（资产价格/估值变化）不调用任何数量模型**——前者属价格效应，后者不能直接等价为最终需求数量冲击。此类问题只做定性机制分析（房价：财富效应/抵押品渠道/投资预期渠道），并注明"精确量化需价格模型或价格-需求弹性，留作后续扩展"。仅当问题同时包含明确的数量指标（投资/新开工/销售面积）时才进入数量模型。
5. 对受影响最大的前几个行业调用 compute_risk_score 计算风险评分。
6. 涉及风险评估时调用 retrieve_similar_cases 做历史对比。
7. 若用户已上传数据（上下文中给出 file_id），调用 analyze_uploaded_data。

## 表述规范（model_basis 与 summary 必须遵守）
- Ghosh 结果必须表述为"供给侧投入压力沿产业链传导的情景测算"，而非对实际产出变化的确定性预测；
- 不得将 B 矩阵解释为"本地产出的销售分配比例"（全国竞争型表中间使用包含进口品，B 反映各下游部门对该产品的中间使用暴露强度）；
- 不得省略公式中的 (I-B)⁻¹ 与 B=D⁻¹Z 口径。

## 最终输出（必须是合法 JSON，不要输出其他任何文字）
{
  "summary": "分析摘要（150-300字，给出核心结论）",
  "transmission_path": ["传导步骤1", "传导步骤2", ...],
  "model_basis": "模型依据（引用投入产出模型计算结果与乘数）",
  "data_basis": ["数据依据1（引用知识库来源）", ...],
  "key_indicators": ["建议关注指标1", ...]
}

## 量化字段的条件输出
- 若数量模型（Leontief/Ghosh）已成功运行并返回结果：在上述 JSON 中附加
  "risk_score" / "risk_level" / "affected_industries" 字段（行业影响数值以工具返回为准，不得自行修改或新增行业）；
- 若数量模型未运行（守卫拦截/行业超出13部门口径）：**省略 risk_score、risk_level、affected_industries**，
  不要自行编造或猜测任何行业与数字，仅输出定性分析。"""


class RiskAgent:
    # 运行模式：auto=配置了LLM则用LLM(失败降级)；offline=强制离线规则引擎；llm_only=仅LLM不降级
    MODES = ("auto", "offline", "llm_only")

    def __init__(self):
        self.mode_setting = "auto"   # 默认自动；可由 /api/agent/mode 运行时切换
        self.client = None
        if LLM_API_KEY:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            except Exception:
                self.client = None

    @property
    def llm_available(self) -> bool:
        """LLM 是否实际可用（配置了Key且客户端初始化成功）"""
        return self.client is not None

    @property
    def mode(self) -> str:
        if not self.llm_available:
            return "规则引擎（未配置LLM_API_KEY，自动降级）"
        if self.mode_setting == "offline":
            return "规则引擎（用户选择离线模式，数据零出网）"
        if self.mode_setting == "llm_only":
            return f"LLM ({LLM_MODEL})"
        return f"LLM ({LLM_MODEL}) · 失败自动降级"

    # ---------------- 主入口 ----------------
    def run(self, question: str, ctx: dict | None = None) -> tuple[dict, list]:
        """返回 (结构化报告, 工具调用轨迹)"""
        report, trace = {}, []
        for ev in self.run_stream(question, ctx or {}):
            if ev["type"] == "tool" and ev.get("status") == "done":
                trace.append({"tool": ev["tool"], "args": ev.get("args", {}),
                              "result_preview": ev.get("result_preview", "")})
            elif ev["type"] == "final":
                report = ev["report"]
            elif ev["type"] == "error":
                raise RuntimeError(ev.get("message", "分析失败"))
        return report, trace

    def run_stream(self, question: str, ctx: dict):
        """生成器：yield {type: tool|final, ...}，供 SSE 流式输出工具轨迹"""
        # 模式路由：offline 强制本地规则引擎；llm_only 不降级（失败直接抛错）
        if self.mode_setting == "llm_only" and not self.client:
            yield {"type": "error", "message": "仅LLM模式不可用：未配置 LLM 客户端，不允许降级"}
            return
        if self.mode_setting == "offline" or not self.client:
            report, trace = self._rule_run(question, ctx)
            report["execution_mode"] = "offline" if self.mode_setting == "offline" else "rule_fallback"
            for t in trace:
                yield {"type": "tool", "status": "done", **t}
            yield {"type": "final", "report": report}
            return
        if self.client:
            try:
                yield from self._llm_stream(question, ctx)
                return
            except Exception as e:
                # llm_only 模式：不降级，直接报错（用户明确要求仅LLM）
                if self.mode_setting == "llm_only":
                    yield {"type": "error", "message": f"LLM 调用失败（仅LLM模式，不降级）: {type(e).__name__}: {e}"}
                    return
                report, trace = self._rule_run(question, ctx)
                report["execution_mode"] = "rule_fallback"
                report["summary"] = f"[LLM调用失败已降级: {type(e).__name__}] " + report.get("summary", "")
                for t in trace:
                    yield {"type": "tool", "status": "done", **t}
                yield {"type": "final", "report": report}
                return
        report, trace = self._rule_run(question, ctx)
        for t in trace:
            yield {"type": "tool", "status": "done", **t}
        yield {"type": "final", "report": report}

    # ---------------- LLM 路径（流式） ----------------
    def _llm_stream(self, question: str, ctx: dict):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        if ctx.get("uploads"):
            files = "; ".join(f"{fid}({s.get('filename', '')})" for fid, s in ctx["uploads"].items())
            # 问题明确提到上传数据时，强制 LLM 调用 analyze_uploaded_data（避免随机跳过）
            if any(k in question for k in ("上传", "数据文件", "上传数据")):
                messages.append({"role": "user", "content": (
                    f"用户已上传数据文件：{files}。本问题要求结合上传数据分析，"
                    f"你必须先调用 analyze_uploaded_data 工具（file_id 任选一个）获取数据摘要后再回答。")})
            else:
                messages.append({"role": "user", "content": f"用户已上传数据文件，file_id 列表：{files}。如与问题相关请分析。"})

        last_impact = None   # 最后一次产业链测算的完整结果
        last_cases = []      # 最后一次案例检索结果
        blocked_tools = set()  # 已被守卫拦截的工具（同问题内不再重试）
        llm_analysis_status = None  # LLM 路径的分析状态（由最后一次有效模型推断）
        for _ in range(8):  # 最多 8 轮工具调用
            resp = self.client.chat.completions.create(
                model=LLM_MODEL, messages=messages,
                tools=TOOL_SCHEMAS, tool_choice="auto", temperature=0.2,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                report = self._parse_report(msg.content or "")
                # 分析状态推断：LLM 实际跑成的模型优先（quantified_*），
                # 未跑模型时按问题语义定性（房价→资产价格 / 价格→成本 / 无幅度→知识问答）
                from .core_guards import scenario_status
                final_status = scenario_status(question)
                if last_impact:
                    final_status = llm_analysis_status
                elif final_status.startswith("quantified_"):
                    # 模型未实际执行时不能标记量化成功；补齐确定性模型结果。
                    report, trace = self._rule_run(question, ctx)
                    for t in trace:
                        yield {"type": "tool", "status": "done", **t}
                    report["execution_mode"] = "llm_with_rule_completion"
                    yield {"type": "final", "report": report}
                    return
                if report is None:
                    # LLM 输出不可解析 → 规则引擎生成完整结构化报告（数字有保证），LLM 原文作参考附注
                    llm_raw = (msg.content or "").strip()
                    report, trace = self._rule_run(question, ctx)
                    for t in trace:
                        yield {"type": "tool", "status": "done", **t}
                    report["summary"] = str(report.get("summary", "")) + (
                        "｜注：LLM 最终输出未能解析为结构化报告（已回退结构化模板），"
                        "LLM 分析要点摘录：" + llm_raw[:260] + "…")
                    report["execution_mode"] = "llm_with_rule_completion"
                    # _rule_run 已内置正确的 analysis_status（含 sector_unresolved/missing 等），不覆盖
                    yield {"type": "final", "report": report}
                    return
                report = self.finalize_report(report, last_impact, last_cases,
                                              status=final_status)
                # 保险：问题要求结合上传数据但 LLM 未调用工具 → 直接融合数据摘要
                if ctx.get("uploads") and any(k in question for k in ("上传", "数据文件")):
                    fid = next(iter(ctx["uploads"]))
                    s = ctx["uploads"][fid]
                    if not any("上传数据" in b or s.get("filename", "") in str(b) for b in report.get("data_basis", [])):
                        report.setdefault("data_basis", []).append(f"上传数据: {s.get('filename', fid)}")
                        note = f"（补充：上传数据 {s.get('filename', '')} 分析结论——{s.get('analysis_note', '')}）"
                        report["summary"] = str(report.get("summary", "")) + note
                report["execution_mode"] = "llm"
                yield {"type": "final", "report": report}
                return
            messages.append(msg)
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                # 守卫记忆：已被拦截的数量模型不再执行（防 LLM 反复重试）
                if tc.function.name in ("analyze_industry_chain_impact", "analyze_supply_shock") \
                        and tc.function.name in blocked_tools:
                    blocked_res = {"blocked": True, "final": True, "error": "该工具此前已被守卫拦截（行业/口径不适用），禁止重复调用",
                                   "instruction": "禁止再调用任何数量模型；请立即基于知识库检索结果输出定性机制分析"}
                    yield {"type": "tool", "status": "done", "tool": tc.function.name,
                           "args": args, "result_preview": blocked_res["error"]}
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps(blocked_res, ensure_ascii=False)[:2000],
                    })
                    continue
                yield {"type": "tool", "status": "start", "tool": tc.function.name, "args": args}
                # Canonical Scenario 校验与参数规范化已下沉至 execute_tool（单一守卫入口）
                result = execute_tool(tc.function.name, args, ctx, question=question)
                # 守卫拦截原因 → analysis_status（sector_unresolved/missing_magnitude）
                if result.get("blocked"):
                    # 守卫可能返回 reason 或 error；两者都必须参与状态推断。
                    blocked_reason = str(result.get("reason") or result.get("error") or "")
                    if "冲击幅度" in blocked_reason or "shock_percent" in blocked_reason:
                        llm_analysis_status = "missing_magnitude"
                    elif "映射" in blocked_reason or "行业" in blocked_reason or "口径" in blocked_reason:
                        llm_analysis_status = "sector_unresolved"
                # blocked（守卫拦截）/error 结果不进入 last_impact（防止空壳 dict 污染报告）
                valid_model_result = (
                    not result.get("blocked") and not result.get("error")
                    and "impact_matrix" in result
                )
                if not valid_model_result and tc.function.name in (
                        "analyze_industry_chain_impact", "analyze_supply_shock"):
                    blocked_tools.add(tc.function.name)  # 记忆：同问题内不再重试该工具
                if tc.function.name == "analyze_industry_chain_impact" and valid_model_result:
                    last_impact = result
                    llm_analysis_status = "quantified_leontief"
                elif tc.function.name == "analyze_supply_shock" and valid_model_result:
                    last_impact = result  # Ghosh 结果同样计入 impact（报告/矩阵共用）
                    llm_analysis_status = "quantified_ghosh"
                elif tc.function.name == "retrieve_similar_cases":
                    last_cases = result.get("cases", [])
                yield {"type": "tool", "status": "done", "tool": tc.function.name, "args": args,
                       "result_preview": json.dumps(result, ensure_ascii=False)[:160]}
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False)[:6000],
                })
        report, trace = self._rule_run(question, ctx)  # 超轮次兜底（_rule_run 已含统一后处理）
        report["execution_mode"] = "llm_with_rule_completion"
        for t in trace:
            yield {"type": "tool", "status": "done", **t}
        yield {"type": "final", "report": report}

    @staticmethod
    def _enrich_report(report: dict, impact: dict | None, cases: list | None = None,
                       status: str = "knowledge_only") -> dict:
        """把工具计算的完整量化数据合并回报告（LLM 只输出部分字段）"""
        if not isinstance(report, dict):
            return report
        if impact:
            report["impact"] = impact  # 模型结果强制覆盖（LLM 不产生数字）
            # 口径声明强制追加到摘要尾部（LLM 措辞不受控，用固定声明保证口径一致）
            disclaimer = ("｜口径说明：本结果为基于2023年全国211部门投入产出表聚合的13部门需求/供给侧"
                          "关联压力情景测算，不解释为全国各行业实际产出变化的确定性预测；"
                          "量化数值以本报告结构化表格（模型引擎计算）为准。")
            if "口径说明" not in str(report.get("summary", "")):
                report["summary"] = str(report.get("summary", "")) + disclaimer
            matrix = {r["industry"]: r for r in impact.get("impact_matrix", [])}
            # affected_industries 强制由模型影响矩阵重建：行业名、排序、全部数值、
            # 风险评分/等级均来自受控引擎——LLM 连“哪5个行业进入结构化影响表”都没有决定权
            rebuilt = []
            for row_m in impact.get("impact_matrix", [])[:5]:
                r = risk_model.industry_risk_from_impact(
                    row_m["industry"], row_m.get("impact_pct", 0), row_m.get("debt_ratio", 55))
                rebuilt.append({
                    "industry": row_m["industry"],
                    "impact_pct": row_m.get("impact_pct", 0),
                    "delta_output_yi": row_m.get("delta_output_yi"),
                    "direct_effect_yi": row_m.get("direct_effect_yi"),
                    "indirect_effect_yi": row_m.get("indirect_effect_yi"),
                    "debt_ratio": row_m.get("debt_ratio", 55),
                    "risk_score": r["risk_score"],
                    "risk_level": r["risk_level"],
                })
            report["affected_industries"] = rebuilt
            # 行业评分明细：强制由评分模型生成（不采纳 LLM 输出）
            if impact.get("impact_matrix"):
                scores = []
                for row_m in impact.get("impact_matrix", [])[:5]:
                    r = risk_model.industry_risk_from_impact(
                        row_m["industry"], row_m.get("impact_pct", 0), row_m.get("debt_ratio", 55))
                    scores.append({"industry": row_m["industry"], "risk_score": r["risk_score"],
                                    "risk_level": r["risk_level"]})
                report["industry_scores"] = scores
                # 综合评分：强制由评分模型聚合（LLM 数字一律丢弃）
                agg = risk_model.aggregate_risk(scores)
                report["risk_score"], report["risk_level"] = agg["risk_score"], agg["risk_level"]
        else:
            # ---- 无有效模型结果（守卫拦截/未执行）：LLM 编造的量化内容一律删除 ----
            # 宁可不给数字，也不乱算（核心原则：没有经过确定性模型验证的结构化结论，
            # 不允许进入最终报告）
            report.pop("impact", None)
            report.pop("affected_industries", None)
            report.pop("industry_scores", None)
            report.pop("risk_score", None)
            report.pop("risk_level", None)
            report.pop("transmission_stages", None)
            reason = ANALYSIS_STATUS_META.get(status, {}).get("no_model_reason", "")
            if reason:
                report["no_model_reason"] = reason
                note = "｜模型状态：" + reason
                if "模型状态" not in str(report.get("summary", "")):
                    report["summary"] = str(report.get("summary", "")) + note
        if isinstance(cases, list):
            # 案例工具结果是唯一权威来源：无条件覆盖（LLM/模板写的案例一律丢弃）
            report["similar_cases"] = [
                {"title": c["title"], "year": c.get("year"),
                 "peak_impact": c.get("peak_impact"), "lessons": c.get("lessons")}
                for c in cases
            ]
        return report

    @classmethod
    def finalize_report(cls, report: dict, impact: dict | None, cases: list | None,
                        status: str = "knowledge_only") -> dict:
        """统一后处理（LLM/规则引擎两路径共用）：
        1) 有有效 impact → 模型数字与评分强制覆盖，量化字段以引擎为准；
        2) 无有效 impact → 删除全部量化表与评分（宁可不给数字，也不乱算）；
        3) 案例检索结果无条件覆盖（工具结果是唯一权威来源，LLM 不能自行创造案例）；
        4) 写入 analysis_status 与 no_model_reason（解释"为什么有/没有数量模型结果"）。"""
        report = cls._enrich_report(report, impact, cases, status=status)
        meta = ANALYSIS_STATUS_META.get(status, ANALYSIS_STATUS_META["knowledge_only"])
        report["analysis_status"] = status
        report["analysis_status_label"] = meta["label"]
        if meta["no_model_reason"]:
            report["no_model_reason"] = meta["no_model_reason"]
        elif "no_model_reason" in report:
            report.pop("no_model_reason", None)
        return report

    @staticmethod
    def _parse_report(content: str) -> dict | None:
        """解析 LLM 最终输出为结构化报告。
        失败返回 None（调用方回退规则引擎生成完整报告，而非裸文本）。"""
        if not content or not content.strip():
            return None
        text = content.strip()
        # 剥离 markdown 代码围栏
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        raw = m.group(0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # 常见错误修复：尾逗号、全角引号包裹的键值、控制字符
        repaired = raw
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)               # 尾逗号
        repaired = repaired.replace(""", '"').replace(""", '"')      # 中文引号
        repaired = repaired.replace(""", '"').replace(""", "'")      # 全角单引号
        repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", repaired)  # 控制字符
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None  # 不可修复 → 调用方回退规则引擎

    # ---------------- 规则引擎路径（无 LLM 时的确定性分析流水线） ----------------
    def _rule_run(self, question: str, ctx: dict) -> tuple[dict, list]:
        trace = []
        q = question

        # 1. 知识库检索（必做）
        kb = rag.search(q, 3)
        trace.append({"tool": "search_knowledge_base", "args": {"query": q}, "result_preview": f"{len(kb)} 条命中"})

        # 2. 解析冲击情景（需求侧 / 供给侧 / 价格与资产价格效应自动判别）
        pct, direction, has_shock = _parse_shock(q)
        supply_hit = _is_supply_side(q)
        price_hit = _is_price_shock(q)
        house_price_hit = _is_house_price_shock(q)
        from .core_guards import scenario_status
        analysis_status = scenario_status(q)
        supply_sector_unresolved = analysis_status == "sector_unresolved"

        impact = None
        if analysis_status == "asset_price_qualitative":
            # 房价涨跌 = 资产价格/估值变化，不直接等价于最终需求数量变化 → 定性分析
            trace.append({"tool": "qualitative_asset_price_analysis",
                          "args": {"question": q},
                          "result_preview": "房价属资产价格变化，不直接等价于最终需求冲击，输出定性机制分析"})
            impact = None
            analysis_status = "asset_price_qualitative"
        elif analysis_status == "price_qualitative":
            # 价格/成本冲击（如"涨价""成本上升"）属价格效应 → 不进数量模型，纯定性
            trace.append({"tool": "qualitative_price_analysis",
                          "args": {"question": q},
                          "result_preview": "价格效应不进入数量模型，输出定性机制分析"})
            impact = None
            analysis_status = "price_qualitative"
        elif analysis_status == "quantified_ghosh":
            # 数量型供给冲击 → Ghosh（行业识别失败则拒绝量化，不猜测默认行业）
            sector = _supply_sector(q)
            if not sector:
                trace.append({"tool": "analyze_supply_shock",
                              "args": {"question": q},
                              "result_preview": "无法将问题中的行业映射到模型13部门，拒绝量化并提示明确口径"})
                impact = None
                supply_sector_unresolved = True
                analysis_status = "sector_unresolved"
            else:
                impact = io.ghosh_supply_shock(sector, pct, direction)
                analysis_status = "quantified_ghosh"
                trace.append({"tool": "analyze_supply_shock",
                              "args": {"sector": sector, "shock_percent": pct, "direction": direction},
                              "result_preview": f"Ghosh供给侧：总产出变动 {impact.get('total_output_change_yi')} 亿元"})
        elif analysis_status == "quantified_leontief":
            # 数量型需求冲击 → Leontief
            impact = io.analyze_shock(pct, direction)
            analysis_status = "quantified_leontief"
            trace.append({"tool": "analyze_industry_chain_impact",
                          "args": {"shock_percent": pct, "direction": direction},
                          "result_preview": f"Leontief需求侧：总产出变动 {impact['total_output_change_yi']} 亿元"})

        # 3. 行业风险评分（受影响前5行业）
        industry_scores = []
        if impact:
            for row in impact["impact_matrix"][:5]:
                r = risk_model.industry_risk_from_impact(row["industry"], row["impact_pct"], row["debt_ratio"])
                industry_scores.append({"industry": row["industry"], "risk_score": r["risk_score"],
                                        "risk_level": r["risk_level"]})
                trace.append({"tool": "compute_risk_score", "args": {"industry": row["industry"]},
                              "result_preview": f"score={r['risk_score']} ({r['risk_level']})"})
        agg = risk_model.aggregate_risk(industry_scores)

        # 4. 历史案例（传入 question 供二次校验；trace 显示实际条数）
        similar = execute_tool("retrieve_similar_cases", {"event": q, "top_k": 3}, question=q)
        n_cases = len(similar.get("cases", []))
        trace.append({"tool": "retrieve_similar_cases", "args": {"event": q},
                      "result_preview": f"{n_cases} 条案例"})

        # 5. 上传数据（如有）
        upload_summary = None
        if ctx.get("uploads"):
            fid = next(iter(ctx["uploads"]))
            upload_summary = execute_tool("analyze_uploaded_data", {"file_id": fid}, ctx)
            trace.append({"tool": "analyze_uploaded_data", "args": {"file_id": fid}, "result_preview": "已分析"})

        # 供给冲击行业无法映射到13部门 → 定性分析（拒绝猜测行业）
        if supply_sector_unresolved:
            rep = _compose_report(q, kb, None, [], agg, similar.get("cases", []),
                                  upload_summary, price_hit, house_price_hit,
                                  sector_unresolved=True)
            rep = self.finalize_report(rep, None, [], status="sector_unresolved")  # 统一后处理
            return rep, trace

        rep = _compose_report(q, kb, impact, industry_scores, agg, similar.get("cases", []),
                              upload_summary, price_hit, house_price_hit)
        rep = self.finalize_report(rep, impact, similar.get("cases", []),
                                   status=analysis_status)  # 统一后处理
        return rep, trace


# ---------------- 情景解析 ----------------


def has_explicit_shock(question: str) -> bool:
    """是否存在明确的数量冲击幅度（如'下降15%'、'减产10%'）。
    模型运行的前提条件：没有明确幅度的问题不进入数量模型（防 LLM 脑补默认值）。"""
    return _parse_shock(question)[2]


# 数量型供给冲击关键词（Ghosh 模型的适用域）；"涨价"属价格效应，不做精确量化
_SUPPLY_KWS = ("减产", "增产", "扩产", "供给收缩", "供给下降", "供给增加", "停产", "限产", "供给减少")
_PRICE_KWS = ("涨价", "价格上升", "价格上涨", "成本上升", "房价上涨", "房价下降",
              "房价下跌", "房价涨", "房价跌")  # 价格/资产估值冲击 → 定性提示，不进数量模型
_DEMAND_BYPASS = ("房地产", "楼市", "销售", "投资", "需求")  # 注意：房价不在需求旁路（它属于价格维度）
_HOUSE_PRICE_KWS = ("房价上涨", "房价下降", "房价下跌", "房价涨", "房价跌", "房价上升")

# ---- 分析状态（analysis_status）：统一解释"为什么有/没有数量模型结果" ----
ANALYSIS_STATUS_META = {
    "quantified_leontief": {
        "label": "Leontief 需求侧量化",
        "no_model_reason": "",
    },
    "quantified_ghosh": {
        "label": "Ghosh 供给侧量化",
        "no_model_reason": "",
    },
    "sector_unresolved": {
        "label": "行业超出模型口径",
        "no_model_reason": ("该问题属于数量型供给冲击，但问题中的行业无法映射至当前 13 部门模型口径，"
                            "因此未执行 Ghosh 数量测算。系统不会将其强行映射至近似行业。"
                            "如需量化，请明确行业至当前口径后重新提问。"),
    },
    "price_qualitative": {
        "label": "价格冲击定性分析",
        "no_model_reason": ("该问题属于价格/成本冲击。当前 Leontief/Ghosh 模块均为数量模型，"
                            "不用于直接量化价格效应，因此本次仅进行成本传导机制分析。"
                            "精确量化需进一步引入投入产出价格模型。"),
    },
    "asset_price_qualitative": {
        "label": "资产价格定性分析",
        "no_model_reason": ("房价变化属于资产价格变化，不能直接等价为最终需求数量冲击，"
                            "因此不调用 Leontief/Ghosh 数量模型，本次仅分析财富效应、"
                            "抵押品渠道和投资预期渠道。"),
    },
    "missing_magnitude": {
        "label": "缺少量化冲击幅度",
        "no_model_reason": ("该问题未提供明确的量化冲击幅度，服务端不会自行假设默认值，"
                            "因此本次仅提供定性分析；如需数量测算，请明确冲击幅度。"),
    },
    "knowledge_only": {
        "label": "知识问答",
        "no_model_reason": "",
    },
}


def _is_house_price_shock(q: str) -> bool:
    """房价涨跌 = 资产价格/估值变化，不直接等价于最终需求数量变化 → 定性分析"""
    return any(k in q for k in _HOUSE_PRICE_KWS)


def _is_price_shock(q: str) -> bool:
    """价格/成本冲击识别：优先级高于数量模型路由"""
    return any(k in q for k in _PRICE_KWS)


def _is_supply_side(q: str) -> bool:
    """判别供给侧冲击：含数量型供给词（减产/限产等），且主体非房地产类需求侧词。
    价格类词（涨价等）单独识别为价格效应提示，不进入 Ghosh 数量测算。"""
    from .core_guards import _has_price, _has_house_price
    if _has_price(q) or _has_house_price(q):
        return False
    return bool(re.search(_SUPPLY_PATTERN, q))


# 行业别名表：自然语言 → 13 部门口径（含口语/常用简称）
_SECTOR_ALIASES = {
    "水泥": "建材", "玻璃": "建材", "装修建材": "建材", "防水材料": "建材",
    "建材": "建材", "建筑材料": "建材",
    "钢材": "钢铁", "螺纹钢": "钢铁", "钢铁": "钢铁", "金属冶炼": "钢铁",
    "家电": "家用电器", "家用电器": "家用电器", "空调": "家用电器", "冰箱": "家用电器",
    "家具": "家具制造", "家居": "家具制造", "家具制造": "家具制造",
    "电力": "电力热力", "电力热力": "电力热力", "能源": "电力热力",
    "工程机械": "机械设备", "机械": "机械设备", "机械设备": "机械设备",
    "装修": "建筑业", "建筑装饰": "建筑业",  # 聚合口径：建筑装饰并入建筑业
    "房地产": "房地产", "地产": "房地产",
    "建筑": "建筑业", "建筑业": "建筑业",
    "金融": "金融业", "银行": "金融业", "金融业": "金融业",
    "批发零售": "批发零售", "零售": "批发零售",
    "交通运输": "交通运输", "物流": "交通运输",
    "化工": "化工", "化学": "化工",
    "专业服务": "专业服务", "服务": "专业服务",
}


def _supply_sector(q: str) -> str:
    """提取供给侧冲击行业：别名表 → 部门名直配 → 识别失败返回空串（不猜测默认行业）
    最终校验：映射结果必须属于模型 13 部门（io.SECTOR_NAMES），否则拒绝。"""
    q = _shock_subject(q)
    result = ""
    # 1) 别名表（长词优先，避免"家具"误命中"家具制造"之外的场景）
    for alias in sorted(_SECTOR_ALIASES, key=len, reverse=True):
        if alias in q:
            result = _SECTOR_ALIASES[alias]
            break
    # 2) 部门名直配
    if not result:
        for s in io.SECTOR_NAMES:
            if s in q:
                result = s
                break
    # 3) 最终校验：必须属于模型部门（防脏映射送进引擎）
    if result and result not in io.SECTOR_NAMES:
        return ""
    return result


_SUPPLY_PATTERN = r"供给收缩|供给下降|供给增加|供给减少|减产|增产|扩产|停产|限产"
_SHOCK_PATTERN = rf"({_SUPPLY_PATTERN}|上升|上涨|增长|下跌|下降|回落|下滑|收缩)"


def _shock_subject(q: str) -> str:
    match = re.search(_SHOCK_PATTERN, q)
    subject = q[:match.start()] if match else q
    return re.split(r"[，,。；;！？!?]", subject)[-1]


def _parse_shock(q: str) -> tuple[float, str, bool]:
    m = re.search(_SHOCK_PATTERN + r"\s*(\d+(?:\.\d+)?)\s*[%％]", q)
    if not m:
        return 0.0, "下降", False
    word, num = m.group(1), float(m.group(2))
    direction = "上升" if word in ("上升", "上涨", "增长", "增产", "扩产", "供给增加") else "下降"
    if not math.isfinite(num) or (direction == "下降" and num > 100):
        return 0.0, direction, False
    return num, direction, True


# ---------------- 报告组装 ----------------
def _compose_report(question, kb, impact, industry_scores, agg, similar_cases, upload_summary,
                    price_hit: bool = False, house_price_hit: bool = False,
                    sector_unresolved: bool = False) -> dict:
    kb_sources = [f"[{k['category']}] {k['source']}" for k in kb[:3]]
    if sector_unresolved and impact is None:
        # 供给冲击行业无法映射到模型13部门 → 定性分析（不猜测行业）
        return {
            "question": question,
            "summary": (
                f"针对「{question}」：问题中提到的行业无法映射到模型覆盖的 13 个部门口径，"
                f"系统不做猜测性量化。定性机制：该行业供给收缩的影响取决于下游对其产品的依赖度、"
                f"替代材料可得性与库存周期。"
                f"请明确行业口径（如钢铁/建材/电力热力等）后再进行量化测算。"
            ),
            "risk_level": "关注",
            "data_basis": kb_sources,
            "transmission_path": [
                "行业供给收缩（未明确到模型部门口径）",
                "下游依赖度决定首轮冲击范围",
                "替代材料与库存缓冲，或沿产业链持续传导",
            ],
            "model_basis": "行业口径超出模型 13 部门覆盖范围，未执行 Ghosh 数量测算；"
                           "请按系统部门口径（房地产/建筑/钢铁/建材/化工/机械设备/家用电器/家具制造/"
                           "金融/批发零售/交通运输/电力热力/专业服务）明确行业后重试",
            "key_indicators": ["明确行业口径后可测算", "或参考知识库中相近行业的历史案例"],
        }
    if house_price_hit and impact is None:
        # 房价涨跌：资产价格/估值变化，不直接等价于最终需求数量冲击 → 定性分析
        return {
            "question": question,
            "summary": (
                f"针对「{question}」：房价变化属于资产价格/估值变化，不能直接等价为最终需求数量冲击，"
                f"因此系统不套用 Leontief/Ghosh 数量模型做精确测算。定性传导机制：房价变动通过三条渠道"
                f"影响产业链——财富效应（居民住房财富变化影响耐用品消费）、抵押品渠道（抵押价值变化影响"
                f"房企与家庭的融资能力）、投资预期渠道（销售预期决定新开工与投资意愿）。"
                f"若需量化房价→投资的传导，需引入价格-需求弹性或资产价格模块，留作后续扩展。"
            ),
            "risk_level": "关注",
            "data_basis": kb_sources,
            "transmission_path": [
                "房价变动（资产价格/估值变化）",
                "财富效应：居民住房财富变化 → 耐用品消费调整",
                "抵押品渠道：抵押价值变化 → 房企与家庭融资能力变化",
                "投资预期渠道：销售预期 → 新开工与投资意愿调整",
                "上述渠道再触发产业链数量型传导（可先用需求侧模型做压力测试）",
            ],
            "model_basis": "房价冲击属资产价格变化，与最终需求数量冲击性质不同；"
                           "精确量化需价格-需求弹性模块或资产价格传导模型，留作后续扩展",
            "key_indicators": ["70城房价指数环比", "二手房挂牌量与成交周期", "居民中长期贷款",
                               "新开工面积同比（先行确认）"],
        }
    if price_hit and impact is None:
        # 价格/成本冲击：定性机制分析，不进入数量模型
        return {
            "question": question,
            "summary": (
                f"针对「{question}」：这属于价格/成本冲击，与数量型供给冲击的传导机制不同，"
                f"系统当前的数量模型（Ghosh 框架）不做精确量化测算。定性机制：原材料价格上涨首先压缩"
                f"依赖该投入的下游行业利润率，随后沿产业链向终端价格传导，传导强度取决于买方议价能力、"
                f"库存周期与替代材料可得性。"
                f"建议关注投入产出价格模型（成本推动型）等相关文献的量化方法。"
            ),
            "risk_level": "关注",
            "data_basis": kb_sources,
            "transmission_path": [
                "原材料价格上涨（成本冲击）",
                "依赖该投入的下游行业利润率压缩（买方议价能力决定转嫁程度）",
                "沿产业链向中下游价格传导，终端消费承压",
                "替代材料与库存策略可部分缓冲，长期或进一步形成成本上升与价格传导压力",
            ],
            "model_basis": "价格/成本冲击属价格效应，系统的 Ghosh 数量框架（初始投入数量冲击）不适用；"
                           "精确量化需投入产出价格模型（成本推动型 Pᵀ = AᵀP + 增加值率），留作后续扩展",
            "key_indicators": ["原材料购进价格指数（PPI分项）", "下游行业毛利率变化", "库存周期", "替代材料价差"],
        }
    if impact:
        top = impact["impact_matrix"][:5]
        top_desc = "、".join(f"{r['industry']}({r['impact_pct']:+.1f}%)" for r in top)
        is_ghosh = str(impact.get("model", "")).startswith("Ghosh")
        if is_ghosh:
            summary = (
                f"针对「{question}」：基于Ghosh供给侧模型（标准供给分配口径 B=D⁻¹Z）测算，情景「{impact['scenario']}」"
                f"将通过中间投入成本渠道带来产业关联层面的总产出情景变动约 {abs(impact['total_output_change_yi']):,.0f} 亿元"
                f"（占全国13部门基准总产出 {abs(impact['total_output_change_pct'])}%）。"
                f"受影响最大的行业依次为：{top_desc}。"
                f"综合风险评分 {agg['risk_score']}（{agg['risk_level']}）。"
                f"供给侧冲击沿'上游供给收缩 → 中间投入成本上升 → 下游生产受阻'传导，"
                f"与需求侧冲击（Leontief）形成互补：本情景属于供给约束型冲击。"
                f"注意：全国竞争型表的中间使用包含进口品，结果应解读为投入需求/产业关联压力的情景测算。"
            )
            model_basis = (f"Ghosh供给侧模型（标准口径）ΔX=ΔV·(I-B)^(-1)，供给分配系数按卖方部门总产出系数化"
                           f"（B=D⁻¹Z，与A为相似矩阵，谱半径相同、数值稳定可解）；"
                           f"以{impact['scenario']}模拟初始投入变动，供给推动乘数 {impact.get('supply_multiplier')}。"
                           f"口径说明：全国竞争型表中间使用包含进口品，B反映各下游部门对该产品的"
                           f"中间使用暴露强度，结果应解读为供给侧投入压力沿产业链传导的情景测算")
            transmission = [
                f"「{impact['scenario'].split('供给侧')[0]}」供给收缩，初始投入（增加值）直接减少",
                "中间投入供给缺口出现：依赖该行业作为原材料的部门生产受阻",
                "下游生产成本上升：制造与建造类行业首当其冲",
                "若持续：成本推动型通胀压力沿产业链向终端消费传导",
            ]
        else:
            summary = (
                f"针对「{question}」：基于13部门投入产出模型（2023年全国211部门表聚合）测算，"
                f"本情景设定为「{impact['scenario']}」，"
                f"测算得投入需求端的产业关联压力约 {abs(impact['total_output_change_yi']):,.0f} 亿元"
                f"（占全国13部门基准总产出 {abs(impact['total_output_change_pct'])}%）。"
                f"受影响最大的行业依次为：{top_desc}。"
                f"综合风险评分 {agg['risk_score']}（{agg['risk_level']}）。"
                f"传导路径为：房地产投资收缩 → 上游原材料需求下降 → 中游建造活动放缓 → 下游耐用品消费承压，"
                f"并通过金融渠道放大。该结果为需求侧投入关联的情景测算，"
                f"不解释为全国各行业实际产出变化的确定性预测。"
            )
            model_basis = (f"列昂惕夫投入产出模型 X=(I-A)^(-1)Y：房地产乘数 {impact['real_estate_multiplier']}、"
                           f"建筑业乘数 {impact['construction_multiplier']}；冲击情景：{impact['scenario']}")
            transmission = [
                f"房地产最终需求{impact['scenario'].split('最终需求')[-1]}，直接冲击房地产与建筑业",
                "上游需求收缩：钢铁、建材、化工订单下降（生产成本渠道）",
                "中游放缓：机械设备、专业服务、建筑装饰活动减少",
                "下游承压：家电、家具等后周期消费需求下滑（收入-消费渠道）",
                "金融传导：房企信用风险暴露，银行敞口与抵押品价值承压（金融加速器渠道）",
            ]
        if impact.get("total_output_change_yi", 0) > 0:
            summary += " 本情景为数量扩张而非收缩，传导方向应按投入增加及关联需求增长理解。"
            transmission = ["初始投入增加" if is_ghosh else "房地产与建筑业最终需求增加",
                            "产业关联投入及需求增加", "上下游产出情景扩张（非实际产出预测）"]
            summary = summary.replace("供给收缩 → 中间投入成本上升 → 下游生产受阻", "初始投入增加 → 中间投入传导 → 下游产出扩张")
            summary = summary.replace("本情景属于供给约束型冲击", "本情景属于供给扩张情景")
            summary = summary.replace("房地产投资收缩 → 上游原材料需求下降 → 中游建造活动放缓 → 下游耐用品消费承压",
                                      "房地产投资增加 → 上游关联需求增长 → 中下游活动扩张")
        # 传导三阶段预判（需求侧：六案例归纳框架；供给侧：供给约束传导框架）
        stages = impact.get("transmission_stages", {})
        if stages:
            st_desc = " → ".join(
                f"{s['name']}({s['window'].split(' ')[-2]}{s['window'].split(' ')[-1]}，压力{s['pressure']})"
                for s in stages.get("stages", []))
            transmission.insert(0, f"【三阶段传导预判】{st_desc}")
        affected = [
            {"industry": r["industry"], "impact_pct": r["impact_pct"],
             "delta_output_yi": r.get("delta_output_yi"),
             "direct_effect_yi": r.get("direct_effect_yi"), "indirect_effect_yi": r.get("indirect_effect_yi"),
             **{"risk_score": next((s["risk_score"] for s in industry_scores if s["industry"] == r["industry"]),
                                    risk_model.industry_risk_from_impact(r["industry"], r["impact_pct"], r["debt_ratio"])["risk_score"])}}
            for r in top
        ]
    else:
        summary = f"针对「{question}」：已检索金融知识库，结合投入产出模型与风险评分框架给出定性分析。{agg['risk_level']}"
        model_basis = "基于投入产出模型与多指标风险评分框架（收入/债务/现金流/市场需求加权）"
        transmission = ["房地产销售/投资变动", "产业链上下游需求传导", "金融体系信用敞口变化"]
        affected = []
        # 无冲击情景时，若上传数据含风险评分则采用其结果
        if upload_summary and "risk_evaluation" in upload_summary:
            ev = upload_summary["risk_evaluation"]
            agg = {"risk_score": ev["risk_score"], "risk_level": ev["risk_level"]}
            summary = (f"针对「{question}」：基于上传数据「{upload_summary['filename']}」的风险指标"
                       f"（{upload_summary.get('shape', ['?'])[0]} 期数据），多指标加权模型测算综合风险评分 "
                       f"{ev['risk_score']}（{ev['risk_level']}）。各分项压力："
                       + "、".join(f"{k} {v}" for k, v in ev["components"].items()) + "。")

    if upload_summary:
        summary += f" 已结合上传数据「{upload_summary.get('filename', '')}」完成分析。"

    if similar_cases:
        case_names = "、".join(c["title"] for c in similar_cases)
        model_basis += f"。历史对标案例：{case_names}"

    return {
        "report_id": str(uuid.uuid4())[:8],
        "question": question,
        "summary": summary,
        "risk_level": agg["risk_level"],
        "risk_score": agg["risk_score"],
        "affected_industries": affected,
        "industry_scores": industry_scores,
        "transmission_path": transmission,
        "model_basis": model_basis,
        "data_basis": kb_sources + ([f"上传数据: {upload_summary['filename']}"] if upload_summary else []),
        "key_indicators": ["商品房销售面积同比", "房地产开发投资完成额同比", "新开工面积同比",
                           "70城房价指数环比", "房企现金短债比", "水泥/粗钢产量同比",
                           "家电与家具零售额同比", "银行房地产不良贷款率"],
        "similar_cases": [{"title": c["title"], "year": c["year"], "peak_impact": c["peak_impact"],
                           "lessons": c["lessons"]} for c in similar_cases],
        "impact": impact,
    }
