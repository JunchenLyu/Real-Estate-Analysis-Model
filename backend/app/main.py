"""中国房地产产业链波动传导分析金融智能体 —— FastAPI 入口"""
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .config import DATA_DIR, UPLOAD_DIR, REPORTS_DIR, LLM_API_KEY
from .knowledge import rag
from .agent.core import RiskAgent
from .agent.tools import execute_tool
from .models import input_output as io
from .services import upload as upload_svc
from .services import report as report_svc
from .services import store
from .services.research import router as research_router
from .services.v2 import router as v2_router

STATE = {"reports": {}, "uploads": {}, "dashboard": {}}
AGENT = RiskAgent()


def _default_dashboard() -> dict:
    macro = json.loads((DATA_DIR / "macro_history.json").read_text(encoding="utf-8"))
    monthly = json.loads((DATA_DIR / "macro_monthly.json").read_text(encoding="utf-8"))
    return {
        "risk_score": 0, "risk_level": "-",
        "industry_impact": [], "industry_scores": [], "key_indicators": [],
        "supply_chain": io.supply_chain_graph(),
        "historical_comparison": macro,
        "transmission_monthly": monthly,  # 真实月度序列（2021-10~2026-08）
        "transmission_stages": {},        # 传导三阶段（有分析后填充）
        "updated_at": None,
    }


def _refresh_dashboard(report: dict):
    # 仅当报告含量化分析结果时才刷新仪表盘，避免定性问题清空已有数据
    if not report.get("affected_industries"):
        return
    d = STATE["dashboard"]
    d["risk_score"] = report.get("risk_score", 0)
    d["risk_level"] = report.get("risk_level", "-")
    d["industry_impact"] = [
        {"name": r["industry"], "value": r["impact_pct"]} for r in report.get("affected_industries", [])
    ]
    d["industry_scores"] = report.get("industry_scores", [])
    d["key_indicators"] = report.get("key_indicators", [])
    impact = report.get("impact")
    d["impact_model"] = (impact or {}).get("model", "")  # Leontief / Ghosh 模型类型
    d["supply_chain"] = io.supply_chain_graph(impact)
    d["transmission_stages"] = (impact or {}).get("transmission_stages", {})
    d["similar_cases"] = report.get("similar_cases", [])
    d["updated_at"] = report.get("created_at")


def _rebuild_dashboard():
    STATE["dashboard"] = _default_dashboard()
    reports = sorted(STATE["reports"].values(), key=lambda r: r.get("created_at", ""))
    for report in reports:
        _refresh_dashboard(report)


@asynccontextmanager
async def lifespan(app: FastAPI):
    kb_status = rag.build_knowledge_base()
    # SQLite 持久化恢复（重启后报告/上传历史不丢）
    db = store.init_db()
    STATE["reports"] = store.load_reports()
    STATE["uploads"] = store.load_uploads()
    _rebuild_dashboard()
    print(f"[DB] {db} 恢复: {len(STATE['reports'])} 报告, {len(STATE['uploads'])} 上传  |  Agent 模式: {AGENT.mode}")
    yield


app = FastAPI(title="中国房地产产业链波动传导分析金融智能体", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(research_router)
app.include_router(v2_router)


class ChatRequest(BaseModel):
    question: str


# ---------- Module 1/3/4: Agent 问答 ----------
@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    try:
        report, trace = AGENT.run(req.question, ctx={
            "uploads": STATE["uploads"],
            "dashboard": STATE["dashboard"],
        })
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    report["question"] = req.question  # LLM 输出不含此字段，统一在此设置（报告列表标题用）
    report["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    report["tool_trace"] = trace
    report["agent_mode"] = AGENT.mode
    report["report_id"] = str(uuid.uuid4())[:8]
    report = report_svc.enrich_v2(report)
    STATE["reports"][report["report_id"]] = report
    report_svc.save_report(report)
    store.save_report(report)  # SQLite 持久化
    _refresh_dashboard(report)
    return report


@app.get("/api/chat/stream")
def chat_stream(q: str):
    """SSE 流式问答：实时推送工具调用轨迹 + 最终报告"""
    if not q.strip():
        raise HTTPException(400, "问题不能为空")

    from fastapi.responses import StreamingResponse

    def gen():
        trace = []
        terminal = False
        try:
            for ev in AGENT.run_stream(q, ctx={"uploads": STATE["uploads"],
                                               "dashboard": STATE["dashboard"]}):
                if ev["type"] == "tool":
                    trace.append({k: v for k, v in ev.items() if k != "type"})
                elif ev["type"] == "final":
                    report = ev["report"]
                    report["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    report["question"] = q
                    report["agent_mode"] = AGENT.mode
                    report["tool_trace"] = trace
                    report["report_id"] = str(uuid.uuid4())[:8]
                    report = report_svc.enrich_v2(report)
                    report_svc.save_report(report)
                    store.save_report(report)
                    STATE["reports"][report["report_id"]] = report
                    _refresh_dashboard(report)
                    terminal = True
                elif ev["type"] == "error":
                    terminal = True
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if terminal:
                    break
            if not terminal:
                yield 'data: {"type": "error", "message": "分析未返回完整结果，请重试"}\n\n'
        except Exception:
            import logging
            logging.getLogger(__name__).exception("流式分析失败")
            yield 'data: {"type": "error", "message": "分析或报告保存失败，请重试"}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- Agent 模式管理 ----------
class AgentModeRequest(BaseModel):
    mode: str  # auto / offline / llm_only


@app.get("/api/agent/mode")
def get_agent_mode():
    """当前 Agent 运行模式与可用性"""
    return {"mode": AGENT.mode_setting, "llm_available": AGENT.llm_available,
            "llm_configured": bool(LLM_API_KEY), "description": AGENT.mode}


@app.post("/api/agent/mode")
def set_agent_mode(req: AgentModeRequest):
    """切换 Agent 运行模式：auto=自动(推荐) / offline=强制离线(数据零出网) / llm_only=仅LLM"""
    if req.mode not in AGENT.MODES:
        raise HTTPException(400, f"无效模式: {req.mode}，可选 {AGENT.MODES}")
    if req.mode == "llm_only" and not AGENT.llm_available:
        raise HTTPException(400, "未配置 LLM_API_KEY，无法使用仅LLM模式")
    AGENT.mode_setting = req.mode
    return {"mode": AGENT.mode_setting, "description": AGENT.mode}


# ---------- 数据上传 ----------
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(400, "仅支持 CSV / Excel 文件")
    fid = str(uuid.uuid4())[:8]
    path = UPLOAD_DIR / f"{fid}_{file.filename}"
    path.write_bytes(await file.read())
    try:
        summary = upload_svc.analyze_file(str(path), file.filename)
    except Exception as e:
        raise HTTPException(422, f"文件解析失败: {e}")
    summary["file_id"] = fid
    STATE["uploads"][fid] = summary
    store.save_upload(fid, file.filename, summary)  # SQLite 持久化
    return summary


@app.get("/api/uploads")
def list_uploads():
    """已上传文件列表（含分析摘要）"""
    items = [{
        "file_id": fid,
        "filename": s.get("filename", ""),
        "shape": s.get("shape"),
        "analysis_note": s.get("analysis_note", ""),
        "risk_score": (s.get("risk_evaluation") or {}).get("risk_score"),
        "risk_level": (s.get("risk_evaluation") or {}).get("risk_level"),
    } for fid, s in STATE["uploads"].items()]
    return {"items": items, "uploads_dir": "backend/uploads/"}


@app.get("/api/upload/{fid}")
def get_upload(fid: str):
    """单个上传文件的完整分析结果"""
    if fid not in STATE["uploads"]:
        raise HTTPException(404, "文件不存在（服务重启后内存态清空，原始文件仍在 backend/uploads/）")
    return STATE["uploads"][fid]


@app.get("/api/upload/{fid}/raw")
def get_upload_raw(fid: str):
    """查看上传文件的原始内容（CSV 原文 / Excel 转文本预览）"""
    import pandas as pd
    matches = list(UPLOAD_DIR.glob(f"{fid}_*"))
    if not matches:
        raise HTTPException(404, "原始文件不存在")
    path = matches[0]
    if path.suffix.lower() == ".csv":
        content = path.read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(content, media_type="text/csv")
    # Excel → 前若干行文本预览
    df = pd.read_excel(path, sheet_name=0).head(100)
    return PlainTextResponse(df.to_csv(index=False), media_type="text/csv")


# ---------- 行业画像（图谱节点点击，ROADMAP 4.2） ----------
# 部门 → 月度序列映射（macro_monthly.json）
_IND_MACRO = {
    "房地产": ["开发投资同比", "新开工同比", "施工同比", "销售面积同比"],
    "建筑业": ["新开工同比", "施工同比"],
    "钢铁": ["粗钢产量同比"],
    "建材": ["水泥产量同比", "玻璃产量同比"],
    "家用电器": ["PPI同比"], "家具制造": ["PPI同比"], "化工": ["PPI同比"],
}


@app.get("/api/industry/{name}")
def industry_profile(name: str):
    if name not in io.SECTOR_NAMES:
        raise HTTPException(404, f"未知行业: {name}")
    j = io.SECTOR_NAMES.index(name)
    L = io.leontief_inverse(io.A)
    # 直接消耗结构（该行业每单位产出消耗哪些上游）
    inputs = sorted(
        ({"industry": io.SECTOR_NAMES[i], "coefficient": round(float(io.A[i][j]), 4)}
         for i in range(io.N) if io.A[i][j] >= 0.02),
        key=lambda x: -x["coefficient"])
    # 下游去向（哪些行业使用该行业产品）
    outputs = sorted(
        ({"industry": io.SECTOR_NAMES[k], "coefficient": round(float(io.A[j][k]), 4)}
         for k in range(io.N) if io.A[j][k] >= 0.02),
        key=lambda x: -x["coefficient"])
    # 最新月度数据
    monthly = {}
    try:
        mm = json.loads((DATA_DIR / "macro_monthly.json").read_text(encoding="utf-8"))["series"]
        for key in _IND_MACRO.get(name, []):
            if key in mm and mm[key]:
                last = list(mm[key].items())[-1]
                monthly[key] = {"month": last[0], "value": last[1]}
    except Exception:
        pass
    # 当前评分（若有分析）
    score = next((s for s in STATE["dashboard"].get("industry_scores", [])
                  if s["industry"] == name), None)
    return {
        "industry": name,
        "multiplier": round(float(L[:, j].sum()), 2),      # 影响力乘数
        "base_output_yi": round(float(io.X_BASE[j]), 0),   # 基准总产出（亿元）
        "debt_ratio": io.DEBT.get(name),
        "debt_ratio_source": io._IO.get("debt_ratio_source", {}).get(name, "演示口径"),
        "top_inputs": inputs[:6],
        "top_outputs": outputs[:6],
        "latest_macro": monthly,
        "risk": score,
    }


# ---------- Dashboard ----------
@app.get("/api/dashboard")
def dashboard():
    return STATE["dashboard"]


# ---------- 报告 ----------
@app.get("/api/reports")
def list_reports():
    items = [{"report_id": r["report_id"], "question": r.get("question", ""),
              "risk_level": r.get("risk_level"), "risk_score": r.get("risk_score"),
              "created_at": r.get("created_at")}
             for r in reversed(list(STATE["reports"].values()))]
    return {"items": items, "reports_dir": "backend/reports/"}


@app.get("/api/report/{rid}")
def get_report(rid: str):
    if rid not in STATE["reports"]:
        raise HTTPException(404, "报告不存在（服务重启后内存态清空，Markdown 文件仍在 backend/reports/）")
    report = report_svc.enrich_v2(dict(STATE["reports"][rid]))
    report["markdown"] = report_svc.build_markdown(report)
    report["brief_markdown"] = report_svc.build_brief_markdown(report)
    return report


# ---------- 报告删除 ----------
@app.delete("/api/report/{rid}")
def delete_report(rid: str):
    if rid not in STATE["reports"]:
        raise HTTPException(404, "报告不存在")
    STATE["reports"].pop(rid)
    store.delete_report(rid)
    (REPORTS_DIR / f"{rid}.md").unlink(missing_ok=True)
    (REPORTS_DIR / f"{rid}.pdf").unlink(missing_ok=True)
    (REPORTS_DIR / f"{rid}_brief.pdf").unlink(missing_ok=True)
    _rebuild_dashboard()
    return {"deleted": rid}


@app.delete("/api/reports")
def delete_all_reports():
    """清空全部报告（内存 + SQLite + Markdown 文件）"""
    ids = list(STATE["reports"].keys())
    for rid in ids:
        (REPORTS_DIR / f"{rid}.md").unlink(missing_ok=True)
        (REPORTS_DIR / f"{rid}.pdf").unlink(missing_ok=True)
        (REPORTS_DIR / f"{rid}_brief.pdf").unlink(missing_ok=True)
    STATE["reports"].clear()
    store.clear_reports()
    _rebuild_dashboard()
    return {"deleted_count": len(ids)}


@app.get("/api/report/{rid}/download")
def download_report(rid: str):
    from .config import REPORTS_DIR
    path = REPORTS_DIR / f"{rid}.md"
    if rid in STATE["reports"]:
        report_svc.save_report(STATE["reports"][rid])
    if not path.exists():
        raise HTTPException(404, "报告文件不存在")
    return FileResponse(path, media_type="text/markdown",
                        filename=f"中国房地产产业链波动传导分析报告_{rid}.md")


@app.get("/api/report/{rid}/pdf")
def download_report_pdf(rid: str, brief: bool = False):
    if rid not in STATE["reports"]:
        raise HTTPException(404, "报告不存在")
    suffix = "_brief" if brief else ""
    path = REPORTS_DIR / f"{rid}{suffix}.pdf"
    report_svc.build_pdf(STATE["reports"][rid], path, brief=brief)
    label = "精简摘要" if brief else "完整报告"
    return FileResponse(path, media_type="application/pdf",
                        filename=f"中国房地产产业链波动传导分析{label}_{rid}.pdf")


# ---------- 知识库演示接口 ----------
@app.get("/api/kb/search")
def kb_search(q: str, top_k: int = 4):
    return {"results": rag.search(q, top_k)}


@app.get("/api/kb/status")
def kb_status():
    return {"status": "ok"}


@app.get("/api/health")
def health():
    return {"status": "ok", "agent_mode": AGENT.mode}
