from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def fact_key(fact: dict[str, Any]) -> tuple[str, int | None, str]:
    return fact["entity"], fact["academic_year"], json.dumps(fact.get("scope", {}), ensure_ascii=False, sort_keys=True)


def validate_score_bounds(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int | None, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for fact in facts:
        grouped[fact_key(fact)][fact["field"]] = fact

    issues: list[dict[str, Any]] = []
    for key, fields in grouped.items():
        required = {"admitted_count", "admitted_score_min", "admitted_score_max", "admitted_score_avg"}
        if not required.issubset(fields):
            continue
        count = int(fields["admitted_count"]["value"])
        minimum = float(fields["admitted_score_min"]["value"])
        maximum = float(fields["admitted_score_max"]["value"])
        average = float(fields["admitted_score_avg"]["value"])
        if count <= 0 or minimum > maximum:
            issues.append({"code": "invalid_score_bounds", "severity": "block", "key": key})
            continue

        greatest_possible_average = (minimum + (count - 1) * maximum) / count
        least_possible_average = (maximum + (count - 1) * minimum) / count
        if not least_possible_average <= average <= greatest_possible_average:
            issues.append(
                {
                    "code": "score_average_outside_possible_range",
                    "severity": "block",
                    "key": key,
                    "observed_average": average,
                    "possible_average_range": [round(least_possible_average, 2), round(greatest_possible_average, 2)],
                    "message": "录取人数、最低分、最高分和平均分无法同时成立，必须核验原始名单。",
                }
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="校验研途编辑单个案例的数据一致性")
    parser.add_argument("case_file", type=Path)
    args = parser.parse_args()

    case = json.loads(args.case_file.read_text(encoding="utf-8"))
    issues = validate_score_bounds(case.get("facts", []))
    overrides = {item["issue_code"]: item for item in case.get("manual_overrides", [])}
    for issue in issues:
        override = overrides.get(issue["code"])
        if override:
            issue["waived"] = True
            issue["override"] = override
    blocking = [
        issue for issue in issues
        if issue["severity"] == "block" and not issue.get("waived", False)
    ]
    result = {
        "case_id": case.get("case_id"),
        "generation_allowed": not blocking and case.get("generation_status") != "blocked",
        "generation_status": case.get("generation_status"),
        "warnings": case.get("warnings", []),
        "issues": issues,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())

