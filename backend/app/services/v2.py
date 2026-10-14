"""V2 knowledge, mechanism, simulation, strategy and case interfaces."""
import json
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import DATA_DIR, KB_DOCS_DIR
from ..models import input_output as io

router = APIRouter(prefix="/api/v2", tags=["V2工作台"])


def _content() -> dict:
    return json.loads((DATA_DIR / "v2_content.json").read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return json.loads((DATA_DIR / "cases.json").read_text(encoding="utf-8"))


@router.get("/overview")
def overview():
    content = _content()
    cases = _cases()
    return {
        **content,
        "io_metadata": io._IO["metadata"],
        "knowledge_document_count": len(list(KB_DOCS_DIR.glob("*.md"))),
        "case_count": len(cases),
        "case_evidence_counts": {
            "with_status": sum(bool(case.get("evidence_status")) for case in cases),
            "without_status": sum(not case.get("evidence_status") for case in cases),
        },
    }


@router.get("/cases")
def cases():
    return {"items": _cases()}


@router.get("/strategies")
def strategies(stakeholder: str | None = None):
    content = _content()
    items = content["strategies"]
    if stakeholder:
        items = [item for item in items if item["id"] == stakeholder]
        if not items:
            raise HTTPException(404, "当前知识库暂不支持该主体，请更换查询主体")
    return {"items": items, "disclaimer": content["disclaimer"]}


class SimulationRequest(BaseModel):
    shock_percent: float = Field(default=15, ge=1, le=50)
    direction: str = Field(default="下降", pattern="^(下降|上升)$")


def _bounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


@router.post("/simulate")
def simulate(request: SimulationRequest):
    impact = io.analyze_shock(request.shock_percent, request.direction)
    severity = min(100.0, request.shock_percent / 20 * 100)
    timeline = []
    for month in range(25):
        timeline.append({
            "month": month,
            "trade_credit": _bounded(severity * (0.82 * math.exp(-month / 6) + 0.08)),
            "upstream_demand": _bounded(severity * math.exp(-((month - 3) / 5) ** 2)),
            "downstream_completion": _bounded(severity * 0.82 * math.exp(-((month - 18) / 6) ** 2)),
            "negative_feedback": _bounded(severity * 0.55 / (1 + math.exp(-(month - 8) / 3))),
        })
    content = _content()
    mechanisms = {item["id"]: item for item in content["mechanisms"]}
    milestones = [
        {"month": 0, **mechanisms["trade-credit"]},
        {"month": 3, **mechanisms["upstream-demand"]},
        {"month": 12, **mechanisms["downstream-completion"]},
        {"month": 6, **mechanisms["negative-feedback"]},
    ]
    return {
        "scenario": impact["scenario"],
        "direction": request.direction,
        "shock_percent": request.shock_percent,
        "timeline": timeline,
        "milestones": milestones,
        "industry_impact": impact["impact_matrix"],
        "total_output_change_yi": impact["total_output_change_yi"],
        "model": impact["model"],
        "model_scope": "时间曲线为机制化压力指数，用于比较传播节奏；产出影响来自静态Leontief情景。二者不构成动态预测。",
        "source_refs": ["data-national-io-2023", "data-long-cycle", "trade-credit", "upstream-demand", "downstream-completion"],
    }
