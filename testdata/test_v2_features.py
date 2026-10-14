import json
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models import input_output as io
from app.services import report
from app.services.v2 import SimulationRequest, overview, simulate, strategies


class NationalInputOutputTests(unittest.TestCase):
    def test_national_table_is_traceable_and_stable(self):
        metadata = io._IO["metadata"]
        self.assertEqual(metadata["region"], "全国")
        self.assertEqual(metadata["source_sector_count"], 211)
        self.assertEqual(len(metadata["source_sha256"]), 64)
        self.assertLess(metadata["spectral_radius"], 1)
        self.assertEqual(sum(len(items) for items in metadata["memberships"].values()), 211)

    def test_demand_and_supply_models_run_on_national_matrix(self):
        demand = io.analyze_shock(15, "下降")
        supply = io.ghosh_supply_shock("钢铁", 10, "下降")
        self.assertIn("Leontief", demand["model"])
        self.assertIn("Ghosh", supply["model"])
        self.assertTrue(demand["impact_matrix"])
        self.assertTrue(supply["impact_matrix"])


class V2WorkspaceTests(unittest.TestCase):
    def test_overview_exposes_all_models_and_gnn_boundary(self):
        data = overview()
        models = {item["id"]: item for item in data["models"]}
        self.assertEqual(set(models), {"leontief", "ghosh", "grey", "gisrn", "gnn"})
        self.assertEqual(models["gnn"]["status"], "待数据")
        self.assertIn("不能宣称", models["gnn"]["boundary"])
        self.assertGreaterEqual(data["case_count"], 20)

    def test_simulation_peaks_match_declared_windows(self):
        data = simulate(SimulationRequest(shock_percent=15, direction="下降"))
        self.assertEqual(len(data["timeline"]), 25)
        self.assertEqual(max(data["timeline"], key=lambda x: x["trade_credit"])["month"], 0)
        self.assertEqual(max(data["timeline"], key=lambda x: x["upstream_demand"])["month"], 3)
        self.assertEqual(max(data["timeline"], key=lambda x: x["downstream_completion"])["month"], 18)
        self.assertLess(data["timeline"][0]["negative_feedback"], data["timeline"][-1]["negative_feedback"])
        self.assertIn("不构成动态预测", data["model_scope"])

    def test_strategy_output_is_source_bound(self):
        data = strategies("financial-institution")
        self.assertEqual(len(data["items"]), 1)
        self.assertTrue(data["items"][0]["source_refs"])
        self.assertIn("不构成任何投资", data["disclaimer"])

    def test_all_new_case_leads_carry_evidence_status(self):
        path = Path(__file__).resolve().parents[1] / "backend/app/data/cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        leads = [item for item in cases if item["id"].startswith("v2_")]
        self.assertGreaterEqual(len(leads), 10)
        self.assertTrue(all(item.get("source_document") and item.get("evidence_status") for item in leads))


class ReportExportTests(unittest.TestCase):
    def _sample(self):
        impact = io.analyze_shock(15, "下降")
        return {
            "report_id": "pdf-test", "question": "房地产最终需求下降15%",
            "created_at": "2026-10-14 12:00", "summary": "用于测试报告导出。",
            "executive_summary": "全国投入产出压力测试摘要。", "risk_score": 62,
            "risk_level": "中", "impact": impact, "affected_industries": impact["impact_matrix"],
            "industry_scores": [], "transmission_path": ["需求变化", "产业链传导"],
            "model_basis": impact["model"], "data_basis": [io._IO["metadata"]["source"]],
            "key_indicators": ["新开工面积", "应收账款周转天数", "竣工面积"],
            "similar_cases": [],
        }

    def test_brief_is_shorter_and_pdf_is_valid(self):
        sample = self._sample()
        full = report.build_markdown(sample)
        brief = report.build_brief_markdown(sample)
        self.assertLess(len(brief), len(full))
        self.assertIn("不构成任何投资", brief)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.pdf"
            report.build_pdf(sample, path)
            reader = PdfReader(str(path))
            self.assertGreaterEqual(len(reader.pages), 2)
            self.assertGreater(path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
