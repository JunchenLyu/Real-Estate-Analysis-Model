from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agent.core import RiskAgent, _parse_shock, _supply_sector
from app.agent.core_guards import scenario_status, check_tool_allowed
from app.agent.tools import execute_tool
from app.models import input_output as io
from app.services.upload import analyze_file


class BugRegressions(unittest.TestCase):
    def test_scenario_routing(self):
        scenarios = {
            "钢铁减产10%对房地产投资有什么影响？": "quantified_ghosh",
            "钢铁减产10%对家用电器有什么影响？": "quantified_ghosh",
            "房地产投资下降100亿元": "missing_magnitude",
            "房地产投资下降101%": "missing_magnitude",
            "房价下降10%对房地产投资有什么影响？": "asset_price_qualitative",
            "电力限产20%": "quantified_ghosh",
            "房地产投资下降10%": "quantified_leontief",
            "钢铁增产10％": "quantified_ghosh",
        }
        for question, expected in scenarios.items():
            with self.subTest(question=question):
                self.assertEqual(scenario_status(question), expected)
        self.assertEqual(_supply_sector("钢铁减产10%对家用电器有什么影响？"), "钢铁")
        self.assertEqual(_parse_shock("钢铁增产10％"), (10.0, "上升", True))

    def test_canonical_supply_parameters(self):
        result = execute_tool("analyze_supply_shock", {"sector": "家用电器", "shock_percent": 90},
                              question="钢铁减产10%对房地产投资有什么影响？")
        expected = io.ghosh_supply_shock("钢铁", 10, "下降")
        self.assertEqual(result["impact_matrix"], expected["impact_matrix"])

    def test_expansion_does_not_use_contraction_stages(self):
        for result in (io.analyze_shock(10, "上升"), io.ghosh_supply_shock("钢铁", 10, "上升"),
                       io.analyze_shock(0)):
            self.assertFalse(result.get("transmission_stages"))

    def test_no_llm_invented_scores(self):
        for question in ("房地产投资下降10%", "房价下降10%", "房地产风险有哪些？"):
            self.assertFalse(check_tool_allowed("compute_risk_score", question)[0])
            self.assertTrue(execute_tool("compute_risk_score", {"debt_ratio": 90}, question=question)["blocked"])
        report = RiskAgent.finalize_report({"risk_score": 99, "transmission_stages": {"fake": True}},
                                          None, [], "knowledge_only")
        self.assertNotIn("risk_score", report)
        self.assertNotIn("transmission_stages", report)

    def test_upload_json_safety(self):
        for csv in ("营收变化,债务率\n", "营收变化,债务率\n-10,80\n",
                    "营收变化,债务率\n-10,80\n未知,未知\n", "营收变化,债务率\ninf,80\n"):
            with self.subTest(csv=csv), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "input.csv"
                path.write_text(csv, encoding="utf-8-sig")
                result = analyze_file(str(path), "input.csv")
                json.dumps(result, allow_nan=False)

    def test_stream_terminal_and_trace(self):
        import asyncio
        from app import main

        async def collect(response):
            return "".join([chunk async for chunk in response.body_iterator])

        events = [{"type": "tool", "name": "test_tool", "result": {}},
                  {"type": "final", "report": {"summary": "测试"}}]
        with patch.dict(main.STATE, {"reports": {}, "uploads": [], "dashboard": {}}, clear=True), \
             patch.object(main, "AGENT") as agent, \
             patch.object(main.report_svc, "save_report"), \
             patch.object(main.store, "save_report") as save, \
             patch.object(main, "_refresh_dashboard"):
            agent.mode = "offline"
            agent.run_stream.return_value = iter(events)
            body = asyncio.run(collect(main.chat_stream("测试")))
            self.assertIn('"type": "final"', body)
            self.assertEqual(save.call_args.args[0]["tool_trace"][0]["name"], "test_tool")
            agent.run_stream.return_value = iter([])
            body = asyncio.run(collect(main.chat_stream("测试")))
            self.assertIn('"type": "error"', body)
            agent.run_stream.side_effect = RuntimeError("test exception")
            with self.assertLogs(main.__name__, level="ERROR"):
                body = asyncio.run(collect(main.chat_stream("测试")))
            self.assertIn('"type": "error"', body)
            self.assertIn("[DONE]", body)

    def test_absolute_values_do_not_become_percentages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            path.write_text("营业收入,现金流\n1000000,200000\n", encoding="utf-8-sig")
            result = analyze_file(str(path), "input.csv")
            self.assertNotIn("risk_evaluation", result)

    def test_offline_and_mock_llm_states(self):
        agent = RiskAgent()
        scenarios = {
            "钢铁减产10%对房地产投资有什么影响？": "quantified_ghosh",
            "房地产投资下降10%": "quantified_leontief",
            "钢铁减产对家电有什么影响？": "missing_magnitude",
            "未知材料减产10%": "sector_unresolved",
            "房价下降10%对房地产投资有什么影响？": "asset_price_qualitative",
        }
        for question, status in scenarios.items():
            with self.subTest(question=question):
                offline, _ = agent._rule_run(question, {})
                self.assertEqual(offline["analysis_status"], status)
                response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=json.dumps({"summary": "测试"}), tool_calls=[]))])
                client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                    create=lambda **kwargs: response)))
                with patch.object(agent, "client", client):
                    events = list(agent._llm_stream(question, {}))
                online = next(ev["report"] for ev in events if ev["type"] == "final")
                self.assertEqual(online["analysis_status"], status)
                if status.startswith("quantified_"):
                    self.assertEqual(online["impact"]["impact_matrix"], offline["impact"]["impact_matrix"])
                else:
                    self.assertNotIn("risk_score", online)
                    self.assertNotIn("impact", online)


if __name__ == "__main__":
    unittest.main()
