"""独立研究接口，与既有问答和风险评分隔离。"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..models import association, input_output as io

router = APIRouter(prefix="/api/research", tags=["产业关联研究"])


class ResearchRequest(BaseModel):
    reference: str = "房屋新开工面积当月同比"
    target: str = "水泥产量当月同比"
    start: str | None = None
    end: str | None = None
    rho: float = Field(default=0.5, gt=0, le=1)
    max_lag: int = Field(default=12, ge=0, le=24)
    window: int = Field(default=24, ge=12, le=60)


@router.get("/catalog")
def catalog():
    try:
        dataset = association.load_dataset()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    dates = sorted(set().union(*(set(s) for s in dataset["series"].values())))
    return {"dataset_id": dataset["dataset_id"], "metadata": dataset["metadata"],
            "fields": dataset["fields"], "start": dates[0], "end": dates[-1]}


@router.post("/analyze")
def analyze(request: ResearchRequest):
    try:
        dataset = association.load_dataset()
        series = dataset["series"]
        if request.reference not in series or request.target not in series:
            raise ValueError("所选指标不存在")
        if request.reference == request.target:
            raise ValueError("参考指标与目标指标不能相同")
        for date in (request.start, request.end):
            if date is not None:
                datetime.strptime(date, "%Y-%m")
                if len(date) != 7:
                    raise ValueError("日期格式应为YYYY-MM")
        if request.start and request.end and request.start > request.end:
            raise ValueError("开始日期不能晚于结束日期")
        selected = {name: {d: v for d, v in values.items()
                          if (not request.start or d >= request.start) and (not request.end or d <= request.end)}
                    for name, values in series.items()}
        grey = association.grey_relation(selected[request.reference],
                                          {k: v for k, v in selected.items() if k != request.reference}, request.rho)
        lag = association.lag_correlation(selected[request.reference], selected[request.target],
                                           request.max_lag, request.window)
        network = association.network_metrics(io.A, io.SECTOR_NAMES)
        network["source"] = {"source": io._IO["metadata"]["source"],
                             "year": io._IO["metadata"].get("year"),
                             "region": io._IO["metadata"].get("region"),
                             "sha256": io._IO["metadata"].get("source_sha256"),
                             "note": io._IO["metadata"]["aggregation"]}
        dates = sorted({d for values in selected.values() for d in values})
        return {"dataset_id": dataset["dataset_id"], "metadata": dataset["metadata"],
                "parameters": request.model_dump(), "grey": grey, "lag": lag, "network": network,
                "plot": {"dates": dates, "reference": [selected[request.reference].get(d) for d in dates],
                         "target": [selected[request.target].get(d) for d in dates]},
                "scope": "描述性研究，不计入风险评分；全国时间序列与全国投入产出子网络分别展示，时序与网络不混合计算"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
