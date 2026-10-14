import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models import association, input_output as io
from app.services.research import ResearchRequest, analyze, catalog


class AssociationResearchTests(unittest.TestCase):
    def test_real_dataset_catalog_and_traceability(self):
        result = catalog()
        self.assertEqual(result["metadata"]["region"], "全国")
        self.assertEqual(len(result["metadata"]["sha256"]), 64)
        self.assertTrue(all(field["sample_count"] >= 24 for field in result["fields"]))
        self.assertTrue(any("当月同比" in field["name"] for field in result["fields"]))

    def test_grey_relation_is_bounded_and_descriptive(self):
        reference = {f"2020-{month:02d}": float(month) for month in range(1, 13)}
        candidate = {key: value * 2 for key, value in reference.items()}
        result = association.grey_relation(reference, {"same_shape": candidate})
        self.assertEqual(result["sample_count"], 12)
        self.assertAlmostEqual(result["ranking"][0]["grade"], 1.0)
        self.assertIn("不是相关系数", result["warnings"][0])

    def test_lag_sign_calendar_gaps_and_sample_count(self):
        dates = [association._shift("2020-01", i) for i in range(30)]
        rng = random.Random(42)
        x = {date: rng.random() for date in dates}
        y = {association._shift(date, 2): value for date, value in x.items()
             if association._shift(date, 2) <= "2022-12"}
        y.pop("2020-10")
        result = association.lag_correlation(x, y, max_lag=3, window=12)
        best = result["strongest_absolute_correlation"]
        self.assertEqual(best["lag_months"], 2)
        self.assertEqual(best["correlation"], 1.0)
        self.assertIn("X领先Y", result["lag_definition"])

    def test_network_direction_and_pagerank_normalization(self):
        result = association.network_metrics(io.A, io.SECTOR_NAMES)
        self.assertEqual(result["node_count"], len(io.SECTOR_NAMES))
        self.assertEqual(len(result["ranking"]), len(io.SECTOR_NAMES))
        self.assertAlmostEqual(sum(row["pagerank"] for row in result["ranking"]), 1.0, places=5)
        self.assertIn("供应行业i → 使用行业j", result["edge_direction"])

    def test_api_result_keeps_national_series_and_beijing_network_separate(self):
        result = analyze(ResearchRequest())
        self.assertEqual(result["metadata"]["region"], "全国")
        self.assertIn("全国", result["network"]["source"]["source"])
        self.assertGreaterEqual(result["grey"]["sample_count"], 12)
        self.assertLessEqual(min(r["sample_count"] for r in result["lag"]["lags"]), 96)
        self.assertIn("不混合计算", result["scope"])


class V2ReportTests(unittest.TestCase):
    def test_report_enrichment_is_rendered_without_mutating_input(self):
        from app.services.report import build_markdown
        report = {"question": "新开工变化", "summary": "原摘要", "executive_summary": "执行摘要", "impact": None}
        text = build_markdown(report)
        for value in ("执行摘要", "中游贸易信用风险前置", "金融监管部门", "金融机构", "高校与研究人员", "投资者与普通公众", "局限与下一步"):
            self.assertIn(value, text)
        self.assertNotIn("mechanism_notes", report)

    def test_new_case_keeps_source_and_unverified_status(self):
        from app.knowledge.cases import retrieve_similar_cases
        from app.services.report import build_markdown
        cases = retrieve_similar_cases("全国水泥行业新开工需求变化", top_k=10)
        self.assertTrue(any(case["id"] == "v2_cement_demand" for case in cases))
        text = build_markdown({"impact": None, "similar_cases": cases})
        self.assertIn("智能体V2.0迭代内容(3).docx", text)
        self.assertIn("证据状态", text)
        self.assertIn("未作为因果证据", text)


if __name__ == "__main__":
    unittest.main()
