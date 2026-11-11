"""问题编译器与回执的回归测试。

运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kb import KnowledgeBase  # noqa: E402
from planner import compile_question  # noqa: E402


def plan(question: str) -> dict:
    return compile_question(question, [])


class PlannerTests(unittest.TestCase):
    def test_single_color_clog(self) -> None:
        p = plan("拓竹 A1 单色打龟壳，PETG，喷头堵料，已停止打印、退料、关机，室温30度")
        s = p["slots"]
        self.assertEqual(s["brand"], "拓竹")
        self.assertEqual(s["model"], "A1")
        self.assertIn("PETG", s["materials"])
        self.assertIn("clog", s["symptom_ids"])
        self.assertEqual(s["intent"]["multi_color"], False)
        self.assertTrue(any(x["kind"] == "stop_print" for x in s["tried"]))
        self.assertTrue(any(x["kind"] == "ambient_temp" for x in s["environment"]))

    def test_solution_is_not_tried(self) -> None:
        p = plan(
            "拓竹 A1，PETG，打印龟壳时喷头堵料，已停止打印、退料、关机，室温30度。"
            "解决方法：开机，撞针疏通喷头，加热喷头230度再进料。"
        )
        kinds = {x["kind"] for x in p["slots"]["tried"]}
        self.assertNotIn("heat_feed", kinds)
        self.assertNotIn("needle", kinds)
        self.assertIn("stop_print", kinds)

    def test_multi_color_queries(self) -> None:
        p = plan("拓竹 A1 打多色，AMS Lite，PLA 和 PETG 混用，换色时喷头堵料，单色不堵，室温28度")
        s = p["slots"]
        self.assertIn("multi_color", s["symptom_ids"])
        self.assertIn("clog", s["symptom_ids"])
        self.assertTrue(s["intent"]["multi_color"])
        self.assertTrue(any("AMS" in q["text"] for q in p["queries"]))
        self.assertTrue(any(g["type"] == "multi_color_setting" for g in p["gaps"]))

    def test_first_layer_dedupes_warping(self) -> None:
        p = plan("拓竹 A1 打小船，首层不沾，底部不在热床，已经停打，室温28度")
        ids = p["slots"]["symptom_ids"]
        self.assertIn("warping", ids)
        self.assertNotIn("first_layer", ids)

    def test_region_environment(self) -> None:
        p = plan("浙江，多色打印，喷头堵料，AMS Lite，PLA")
        labels = " ".join(x["label"] for x in p["slots"]["environment"])
        self.assertIn("浙江", labels)

    def test_cases_and_notes_counts(self) -> None:
        cases = json.loads((ROOT / "data" / "cases.json").read_text(encoding="utf-8"))
        notes = json.loads((ROOT / "data" / "kb_seed.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 7)
        self.assertEqual(len(notes), 20)


class ReceiptTests(unittest.TestCase):
    def test_three_receipts_become_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeBase(pathlib.Path(tmp) / "kb.sqlite3").init()
            for i in range(3):
                kb.add_receipt(
                    {
                        "run_id": f"run-{i}",
                        "step_title": "先停打、退料",
                        "model": "A1",
                        "material": "PLA/PETG",
                        "symptom": "clog",
                        "outcome": "fixed",
                        "note": "",
                        "client_id": f"client-{i}",
                    }
                )
            rows = kb.receipt_summary("A1", "PLA/PETG", "clog")
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["visible"])
            self.assertEqual(rows[0]["fixed"], 3)
            kb.conn.close()


if __name__ == "__main__":
    unittest.main()
