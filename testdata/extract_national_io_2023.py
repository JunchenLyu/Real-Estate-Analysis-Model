# -*- coding: utf-8 -*-
"""Aggregate the supplied 2023 national input-output table to the app's 13 sectors."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


SECTOR_NAMES = [
    "房地产", "建筑业", "钢铁", "建材", "化工", "机械设备", "家用电器",
    "家具制造", "金融业", "批发零售", "交通运输", "电力热力", "专业服务",
]

# Source table positions are one-based and follow its published 211-sector order.
GROUPS = {
    "房地产": {183},
    "建筑业": set(range(145, 156)),
    "钢铁": {12, 13, *range(82, 98)},
    "建材": {14, 15, *range(73, 82)},
    "化工": {10, 11, *range(54, 73)},
    "机械设备": {*range(98, 124), *range(125, 139)},
    "家用电器": {124},
    "家具制造": set(range(45, 49)),
    "金融业": set(range(178, 183)),
    "批发零售": {156, 157},
    "交通运输": set(range(158, 171)),
    "电力热力": {9, *range(139, 145)},
}

DEBT = {
    "房地产": 78, "建筑业": 70, "钢铁": 55, "建材": 58, "化工": 55,
    "机械设备": 55, "家用电器": 50, "家具制造": 50, "金融业": 92,
    "批发零售": 60, "交通运输": 58, "电力热力": 65, "专业服务": 45,
}


def build(source: Path) -> dict:
    frame = pd.read_excel(source, sheet_name=0, header=None)
    source_names = [str(value).strip() for value in frame.iloc[4, 3:214].tolist()]
    row_names = [str(value).strip() for value in frame.iloc[6:217, 1].tolist()]
    if len(source_names) != 211 or source_names != row_names:
        raise ValueError("2023 national table layout or sector order has changed")

    z = frame.iloc[6:217, 3:214].apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy(float)
    y = pd.to_numeric(frame.iloc[6:217, 224], errors="coerce").fillna(0).to_numpy(float)
    x = pd.to_numeric(frame.iloc[6:217, 226], errors="coerce").fillna(0).to_numpy(float)
    if not np.isfinite(z).all() or not np.isfinite(y).all() or not np.isfinite(x).all():
        raise ValueError("table contains non-finite numeric values")

    assignment = np.full(211, SECTOR_NAMES.index("专业服务"), dtype=int)
    claimed = set()
    for target, positions in GROUPS.items():
        overlap = claimed.intersection(positions)
        if overlap:
            raise ValueError(f"overlapping aggregation positions: {sorted(overlap)}")
        claimed.update(positions)
        for position in positions:
            assignment[position - 1] = SECTOR_NAMES.index(target)

    n = len(SECTOR_NAMES)
    z_agg = np.zeros((n, n))
    y_agg = np.zeros(n)
    x_agg = np.zeros(n)
    for i in range(n):
        for j in range(n):
            z_agg[i, j] = z[np.ix_(assignment == i, assignment == j)].sum()
    np.add.at(y_agg, assignment, y)
    np.add.at(x_agg, assignment, x)
    if (x_agg <= 0).any():
        raise ValueError("aggregated total output must be positive")

    a = z_agg / x_agg[None, :]
    radius = float(max(abs(np.linalg.eigvals(a))))
    if radius >= 1:
        raise ValueError(f"unstable direct-requirements matrix, spectral radius={radius}")

    unit = 1e4
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    memberships = {
        target: [source_names[i] for i in range(211) if assignment[i] == index]
        for index, target in enumerate(SECTOR_NAMES)
    }
    return {
        "metadata": {
            "source": "2023年全国投入产出表（211部门，竞争型表，当年生产者价格）",
            "source_file": source.name,
            "source_sha256": digest,
            "region": "全国",
            "year": 2023,
            "source_sector_count": 211,
            "aggregation": "211部门按房地产产业链研究口径互斥聚合为13部门",
            "unit": "亿元（原始表万元/1e4）",
            "method": "A_ij = 聚合中间流量 / 聚合总产出（直接消耗系数，列归一化）",
            "spectral_radius": round(radius, 8),
            "boundary": "专业服务为剩余部门汇总项；13部门结果适合宏观压力测试，不替代211部门细分分析。",
            "memberships": memberships,
        },
        "sectors": [{"code": f"S{i + 1:02d}", "name": name} for i, name in enumerate(SECTOR_NAMES)],
        "A": [[round(float(a[i, j]), 8) for j in range(n)] for i in range(n)],
        "base_output": [round(float(value) / unit, 2) for value in x_agg],
        "base_final_demand": [round(float(value) / unit, 2) for value in y_agg],
        "debt_ratio": DEBT,
        "debt_ratio_source": {
            "房地产": "国资委全行业口径（演示基准）",
            "建筑业/钢铁/建材/家用电器": "申万行业近5年均值（演示基准）",
            "其余部门": "研究演示假设，不代表统计或评级口径",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backend/app/data/io_table.json"))
    args = parser.parse_args()
    data = build(args.source)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output} from {args.source.name}; spectral radius={data['metadata']['spectral_radius']}")


if __name__ == "__main__":
    main()
