"""Module 5: structured report generation in Markdown and PDF."""
import json
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape

from ..config import DATA_DIR, REPORTS_DIR


def _fmt(v, fmt_str="{:+,.0f}"):
    return fmt_str.format(v) if isinstance(v, (int, float)) else "-"


def _degree(p) -> str:
    """产出变动幅度 → 定性冲击描述（无精确测算时使用）"""
    if not isinstance(p, (int, float)):
        return "待测算"
    a = abs(p)
    if a >= 10:
        return "重度冲击"
    if a >= 5:
        return "显著冲击"
    if a >= 2:
        return "中度冲击"
    return "轻度冲击"


def _industries_md(rows: list[dict]) -> str:
    if not rows:
        return "无量化测算结果（问题未涉及冲击情景）。"
    lines = ["| 行业 | 产出变动% | 产出变动(亿元) | 直接效应 | 间接效应 | 冲击程度 | 风险评分 |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        pct_v = r.get("impact_pct")
        pct_s = f"{pct_v:+.2f}%" if isinstance(pct_v, (int, float)) else "—"
        delta = _fmt(r.get("delta_output_yi"))
        if delta == "-" and pct_s != "—":  # 无亿元数据但有比例 → 给定性描述
            delta = _degree(pct_v)
        lines.append(
            f"| {r.get('industry', '—')} | {pct_s} | "
            f"{delta} | "
            f"{_fmt(r.get('direct_effect_yi'))} | "
            f"{_fmt(r.get('indirect_effect_yi'))} | "
            f"{_degree(pct_v)} | "
            f"{r.get('risk_score', '—')} |"
        )
    return "\n".join(lines)


def enrich_v2(report: dict) -> dict:
    content = json.loads((DATA_DIR / "v2_content.json").read_text(encoding="utf-8"))
    source_labels = {
        **{item["id"]: item["title"] for item in content["theories"]},
        **{item["id"]: item["title"] for item in content["mechanisms"]},
        **{item["id"]: item["label"] for item in content["sources"]},
    }
    label_refs = lambda refs: [source_labels.get(ref, ref) for ref in refs]
    impact = report.get("impact") or {}
    expansion = impact.get("total_output_change_yi", 0) > 0
    context = "数量扩张情景：关注承接能力和资金占用，不能据此推断违约风险上升。" if expansion else "收缩或未量化情景：核验订单、回款和现金流，不据此推断具体企业必然违约。"
    report["report_version"] = "2.0"
    report["mechanism_notes"] = [{
        "id": item["id"], "name": item["title"], "window": item["window"],
        "path": " → ".join(item["path"]), "indicators": item["indicators"],
        "boundary": item["boundary"], "source_refs": label_refs(item["source_refs"]),
    } for item in content["mechanisms"]]
    report["stakeholder_recommendations"] = [
        {**item, "source_refs": label_refs(item["source_refs"])}
        for item in content["strategies"]
    ]
    report["strategy_disclaimer"] = content["disclaimer"]
    report["model_registry"] = content["models"]
    report["analysis_limitations"] = [context, "静态投入产出结果不是未来实际产出的预测；固定系数未考虑替代、产能约束与价格变化。", "风险评分是演示性指标，不是违约概率；案例只能提供机制线索，不能证明统一时滞。", "产业关联研究可在独立研究页运行，灰色关联及网络中心性不能替代价格模型。"]
    return report


def build_markdown(report: dict) -> str:
    report = enrich_v2(dict(report))
    has_model = report.get("impact") is not None  # 是否有有效数量模型结果
    rs = report.get("risk_score")
    rs_s = f"{rs}" if isinstance(rs, (int, float)) else "未计算"
    lines = [
        "# 中国房地产产业链波动传导分析报告",
        f"\n> 分析问题：**{report.get('question', '')}**  "
        + (f"\n> 综合风险评分：**{rs_s} / 100（{report.get('risk_level', '')}）**  " if has_model else "")
        + f"\n> 生成时间：{report.get('created_at', '')}",
        "\n## 1. Executive Summary",
        "\n" + (report.get("executive_summary") or report.get("summary", "")),
    ]
    if has_model:
        lines += [
            "\n## 2. Risk Assessment",
            f"\n- 综合风险评分：**{rs_s}**\n- 风险等级：**{report.get('risk_level', '—')}**",
            "\n### 行业风险评分（多指标加权模型）",
        ]
        for s in report.get("industry_scores", []):
            lines.append(f"- **{s.get('industry', '—')}**：{s.get('risk_score', '—')}（{s.get('risk_level', '—')}）")
    lines += ["\n## 3. Transmission Mechanism（传导机制）"]
    for i, step in enumerate(report.get("transmission_path", []), 1):
        lines.append(f"{i}. {step}")
    # 传导三阶段预判（标题按模型类型动态）
    stages = (report.get("impact") or {}).get("transmission_stages") or {}
    if stages.get("stages"):
        model_tag = (report.get("impact") or {}).get("model", "")
        fw_label = "供给约束传导框架" if model_tag.startswith("Ghosh") else "六案例归纳框架"
        lines += [f"\n### 传导三阶段预判（{fw_label}）"]
        for s in stages["stages"]:
            lines.append(f"\n**{s['name']}**（{s['window']}，压力指数 {s['pressure']}/100）")
            lines.append(f"- 机制：{s['mechanism']}")
            lines.append(f"- 命中行业：{'、'.join(s['hit_industries'])}")
            lines.append(f"- 验证指标：{'、'.join(s['verify_indicators'][:3])}")
        rules = stages.get("cross_case_rules") or []
        if rules:
            lines.append("\n跨案例规律：")
            lines += [f"- {r}" for r in rules]
    if has_model:
        lines += ["\n## 4. Affected Industries（影响矩阵）",
                  "\n" + _industries_md(report.get("affected_industries", []))]
    else:
        # 无模型结果：按 analysis_status 生成对应原因说明
        status = report.get("analysis_status", "knowledge_only")
        STATUS_NOTES = {
            "sector_unresolved": (
                "该问题属于数量型供给冲击，但问题中的行业无法映射至当前 13 部门模型口径，"
                "因此未执行 Ghosh 数量测算。系统不会将其强行映射至近似行业。"),
            "price_qualitative": (
                "该问题属于价格/成本冲击。当前 Leontief/Ghosh 模块均为数量模型，"
                "不用于直接量化价格效应，因此本次仅进行成本传导机制分析。"
                "精确量化需进一步引入投入产出价格模型。"),
            "asset_price_qualitative": (
                "房价变化属于资产价格变化，不能直接等价为最终需求数量冲击，"
                "因此不调用 Leontief/Ghosh 数量模型，本次仅分析财富效应、"
                "抵押品渠道和投资预期渠道。"),
            "missing_magnitude": (
                "该问题未提供明确的量化冲击幅度，服务端不会自行假设默认值，"
                "因此本次仅提供定性分析；如需数量测算，请明确冲击幅度。"),
            "knowledge_only": None,  # 纯知识问答：不显示适用性说明
        }
        note = STATUS_NOTES.get(status)
        if note:
            lines += [
                "\n## 4. 模型适用性说明",
                f"\n{note}",
                "\n系统不会将冲击强行映射到近似行业进行猜测性量化。若需继续分析，可：",
                "- 明确行业至当前模型口径（房地产/建筑/钢铁/建材/化工/机械设备/家用电器/家具制造/"
                "金融/批发零售/交通运输/电力热力/专业服务）后重新提问；",
                "- 或参考知识库中相近行业的历史案例与传导机制。",
            ]
    if report.get("similar_cases"):
        lines += ["\n### 历史对比"]
        for c in report["similar_cases"]:
            lines.append(f"- **{c['title']}**：{c.get('peak_impact', '')} —— {c.get('lessons', '')}")
            if c.get("source_url"):
                lines.append(f"  - 资料链接：{c['source_url']}（需核验是否直接支持本案例的数值及时间窗口）")
            if c.get("source_document"):
                lines.append(f"  - 文档出处：{c['source_document']}")
            if c.get("evidence_status"):
                lines.append(f"  - 证据状态：{c['evidence_status']}")
            lines.append("  - 证据边界：历史案例提供机制线索，不足以证明普遍因果关系或固定时滞。")
    lines += [
        "\n## 5. Model Explanation（模型依据）",
        "\n" + report.get("model_basis", ""),
    ]
    # 冲击模型类型（Leontief需求侧 / Ghosh供给侧）
    model_tag = (report.get("impact") or {}).get("model", "")
    if model_tag:
        kind = "Ghosh 供给侧模型（初始投入收缩情景，ΔX = ΔV·(I-B)⁻¹，B=D⁻¹Z 供给分配系数）" if model_tag.startswith("Ghosh") \
            else "Leontief 需求侧模型（最终需求冲击，X = (I-A)⁻¹Y）"
        lines.append(f"\n> 本次分析采用：**{kind}**")
    lines += [
        "\n### 数据依据",
    ]
    for d in report.get("data_basis", []):
        lines.append(f"- {d}")
    lines += ["\n## 6. Conclusion（结论与建议关注指标）"]
    for k in report.get("key_indicators", []):
        lines.append(f"- {k}")
    lines += ["\n## 7. 机制分析与验证边界"]
    for item in report["mechanism_notes"]:
        lines += [f"\n### {item['name']}（{item['window']}）", item["path"],
                  f"- 验证指标：{'、'.join(item['indicators'])}", f"- 边界：{item['boundary']}",
                  f"- 理论依据：{'、'.join(item['source_refs'])}"]
    lines += ["\n## 8. 分主体行动建议（研究参考）"]
    for item in report["stakeholder_recommendations"]:
        lines.append(f"\n### {item['stakeholder']}")
        lines.extend(f"- {action}" for action in item["actions"])
        lines.append(f"- 关注指标：{'、'.join(item['indicators'])}")
        lines.append(f"- 理论依据：{'、'.join(item['source_refs'])}")
    lines.append(f"\n> {report['strategy_disclaimer']}")
    lines += ["\n## 9. 局限与下一步"]
    lines.extend(f"- {item}" for item in report["analysis_limitations"])
    lines += ["\n---\n*本报告由中国房地产产业链波动传导分析金融智能体自动生成（LLM Agent + 投入产出模型 + 风险评分模型 + RAG知识库），仅供研究演示，不构成投资建议。*"]
    return "\n".join(lines)


def save_report(report: dict) -> str:
    md = build_markdown(report)
    path = REPORTS_DIR / f"{report['report_id']}.md"
    path.write_text(md, encoding="utf-8")
    return str(path)


def build_brief_markdown(report: dict) -> str:
    report = enrich_v2(dict(report))
    impacts = (report.get("affected_industries") or [])[:5]
    mechanisms = report["mechanism_notes"][:3]
    lines = [
        "# 中国房地产产业链波动传导分析精简摘要",
        f"\n**问题：** {report.get('question', '—')}",
        f"\n{report.get('executive_summary') or report.get('summary') or '暂无摘要'}",
    ]
    if impacts:
        lines += ["\n## 核心量化结果"]
        lines.extend(f"- {item['industry']}：产出变动 {item.get('impact_pct', '—')}%" for item in impacts)
    lines += ["\n## 关键传导机制"]
    lines.extend(f"- {item['name']}（{item['window']}）：{item['path']}" for item in mechanisms)
    lines += ["\n## 优先关注指标"]
    lines.extend(f"- {item}" for item in (report.get("key_indicators") or [])[:6])
    lines += ["\n## 结论边界"]
    lines.extend(f"- {item}" for item in report["analysis_limitations"][:3])
    lines.append(f"\n> {report['strategy_disclaimer']}")
    return "\n".join(lines)


def _plain_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return escape(text.strip())


def build_pdf(report: dict, path: str | Path, brief: bool = False) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = "ReportCJK"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        windows_fonts = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
        candidates = [
            os.getenv("PDF_FONT_PATH"),
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            str(windows_fonts / "msyh.ttc"),
            str(windows_fonts / "simsun.ttc"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                try:
                    pdfmetrics.registerFont(TTFont(font_name, candidate, subfontIndex=0))
                    break
                except Exception:
                    continue
        else:
            font_name = "STSong-Light"
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    base = getSampleStyleSheet()
    title_size, title_after = (17, 6 * mm) if brief else (19, 10 * mm)
    heading_size, heading_before = (12, 3 * mm) if brief else (13, 5 * mm)
    body_size, body_leading, body_after = (9, 13, 1.1 * mm) if brief else (9.5, 15, 1.8 * mm)
    quote_size, quote_leading = (8.5, 12) if brief else (9, 14)
    styles = {
        "title": ParagraphStyle("CNTitle", parent=base["Title"], fontName=font_name, fontSize=title_size,
                                leading=23 if brief else 25, textColor=colors.HexColor("#111827"), spaceAfter=title_after),
        "h2": ParagraphStyle("CNH2", parent=base["Heading2"], fontName=font_name, fontSize=heading_size,
                             leading=16 if brief else 18, textColor=colors.HexColor("#111827"),
                             spaceBefore=heading_before, spaceAfter=1.5 * mm if brief else 2 * mm),
        "h3": ParagraphStyle("CNH3", parent=base["Heading3"], fontName=font_name, fontSize=11,
                             leading=16, textColor=colors.HexColor("#1F2937"), spaceBefore=3 * mm, spaceAfter=1.5 * mm),
        "body": ParagraphStyle("CNBody", parent=base["BodyText"], fontName=font_name, fontSize=body_size,
                               leading=body_leading, textColor=colors.HexColor("#374151"), spaceAfter=body_after),
        "quote": ParagraphStyle("CNQuote", parent=base["BodyText"], fontName=font_name, fontSize=quote_size,
                                leading=quote_leading, leftIndent=5 * mm, textColor=colors.HexColor("#4B5563"),
                                borderColor=colors.HexColor("#9CA3AF"), borderWidth=0, borderPadding=2 * mm),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                                 topMargin=(14 if brief else 16) * mm,
                                 bottomMargin=(14 if brief else 16) * mm,
                                 title="中国房地产产业链波动传导分析报告")
    story = []
    markdown = build_brief_markdown(report) if brief else build_markdown(report)
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index].strip()
        if not raw or raw == "---":
            index += 1
            continue
        if raw.startswith("|") and index + 1 < len(lines) and re.match(r"^\|[-| :]+\|$", lines[index + 1].strip()):
            rows = [[_plain_markdown(cell) for cell in raw.strip("|").split("|")]]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([_plain_markdown(cell) for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            cells = [[Paragraph(cell, styles["body"]) for cell in row] for row in rows]
            widths = [document.width / len(cells[0])] * len(cells[0])
            table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.extend([table, Spacer(1, 3 * mm)])
            continue
        if raw.startswith("# "):
            story.append(Paragraph(_plain_markdown(raw[2:]), styles["title"]))
        elif raw.startswith("## "):
            story.append(Paragraph(_plain_markdown(raw[3:]), styles["h2"]))
        elif raw.startswith("### "):
            story.append(Paragraph(_plain_markdown(raw[4:]), styles["h3"]))
        elif raw.startswith("> "):
            story.append(Paragraph(_plain_markdown(raw[2:]), styles["quote"]))
        elif re.match(r"^(?:- |\d+\. )", raw):
            story.append(Paragraph("• " + _plain_markdown(re.sub(r"^(?:- |\d+\. )", "", raw)), styles["body"]))
        else:
            story.append(Paragraph(_plain_markdown(raw), styles["body"]))
        index += 1

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawCentredString(A4[0] / 2, 8 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return str(path)
