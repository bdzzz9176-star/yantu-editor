from __future__ import annotations

import sys
import unittest
import json
import locale
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from validate_case import validate_score_bounds  # noqa: E402


def score_facts(count: int, minimum: float, maximum: float, average: float):
    common = {
        "entity": "测试大学/测试学院/085400电子信息",
        "academic_year": 2026,
        "scope": {"admission_type": "统考"},
    }
    return [
        {**common, "field": "admitted_count", "value": count},
        {**common, "field": "admitted_score_min", "value": minimum},
        {**common, "field": "admitted_score_max", "value": maximum},
        {**common, "field": "admitted_score_avg", "value": average},
    ]


class ScoreBoundsTests(unittest.TestCase):
    def test_impossible_average_blocks_generation(self):
        issues = validate_score_bounds(score_facts(10, 265, 346, 345))
        self.assertEqual(issues[0]["code"], "score_average_outside_possible_range")
        self.assertEqual(issues[0]["severity"], "block")

    def test_possible_average_passes(self):
        issues = validate_score_bounds(score_facts(10, 265, 346, 320))
        self.assertEqual(issues, [])

    def test_user_override_allows_case_with_warning(self):
        case_file = PROJECT_ROOT / "data" / "cases" / "dalian_maritime" / "case.json"
        completed = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_case.py"), str(case_file)],
            check=False,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
        )
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(result["generation_allowed"])
        self.assertEqual(result["generation_status"], "approved_with_risk")
        self.assertTrue(result["issues"][0]["waived"])


if __name__ == "__main__":
    unittest.main()

