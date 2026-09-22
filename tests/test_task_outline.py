from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from task_outline import build_task_outline


class TaskOutlineTests(unittest.TestCase):
    def test_outline_uses_current_school_and_available_tables(self) -> None:
        task = {"task_id": "123456789abc", "school": "示例大学", "target_year": "2027"}
        facts = {"programs": [{"college": "电子学院", "code": "081000"}], "admission_2026": [{"college": "电子学院", "code": "081000", "min": 320, "average": 350}], "cutoffs": []}
        outline = build_task_outline(task, facts)
        self.assertIn("示例大学", outline["title_options"][0]["title"])
        self.assertEqual(len(outline["charts"]),1)
        self.assertEqual(outline['charts'][0]['type'],'admission_bands')
        self.assertNotIn("复试线对比表", " ".join(outline["tables"]))
        self.assertEqual(outline["status"], "pending")
        self.assertNotIn('2027招生',outline['sections'][1]['heading'])

    def test_generic_outline_plans_each_college_program(self):
        facts={'parser_mode':'generic_template','programs':[], 'admission_2026':[
            {'college':'甲学院','code':'085400','name':'电子信息','min':350,'average':380},
            {'college':'乙学院','code':'085400','name':'电子信息','min':350,'average':380}]}
        outline=build_task_outline({'task_id':'example','school':'示例大学'},facts)
        self.assertEqual(len(outline['charts']),2)
        self.assertIn('甲学院',outline['charts'][0]['title'])
        self.assertIn('乙学院',outline['charts'][1]['title'])

if __name__ == "__main__":
    unittest.main()

