from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


UNSUPPORTED_PHRASES = [
    "行业内具备一定认可度",
    "全国数百所高校中已属中上游",
    "性价比较高",
    "报考人数同样众多",
    "吸引大量考生",
    "集中报考",
    "希望求稳",
]

REQUIRED_TOPICS = {
    "programs": ["初试科目", "复试科目"],
    "cutoffs": ["2024", "2025", "2026", "复试线"],
    "admission": ["复试人数", "录取人数", "复录比", "平均分"],
    "subject": ["807", "专业课"],
    "risk": ["085408", "异常"],
    "source": ["数据说明", "手册"],
}


def evaluate(text: str) -> dict:
    heading_count = len(re.findall(r"^##\s+", text, flags=re.MULTILINE))
    table_count = len(re.findall(r"^\|\s*:?-", text, flags=re.MULTILINE))
    conclusion_count = len(re.findall(r"\*\*结论[：:]", text))
    unsupported = [phrase for phrase in UNSUPPORTED_PHRASES if phrase in text]
    missing_topics = [name for name, tokens in REQUIRED_TOPICS.items() if not all(token in text for token in tokens)]
    internal_leaks = [token for token in ["提示词", "大模型", "JSON输入", "内部工作流"] if token in text]
    findings = []
    if conclusion_count >= 3:
        findings.append({"severity": "revise", "code": "repetitive_conclusion_cadence", "detail": f"重复出现{conclusion_count}次粗体结论句式。"})
    if unsupported:
        findings.append({"severity": "revise", "code": "unsupported_generalizations", "detail": unsupported})
    if missing_topics:
        findings.append({"severity": "block", "code": "missing_required_topics", "detail": missing_topics})
    if internal_leaks:
        findings.append({"severity": "block", "code": "internal_process_leak", "detail": internal_leaks})
    if table_count < 4:
        findings.append({"severity": "revise", "code": "insufficient_data_tables", "detail": f"仅识别到{table_count}张Markdown表格。"})
    return {
        "metrics": {
            "characters": len(text),
            "level_2_headings": heading_count,
            "markdown_tables": table_count,
            "bold_conclusion_openers": conclusion_count,
        },
        "generation_ready_for_word": not any(item["severity"] in {"block", "revise"} for item in findings),
        "findings": findings,
        "human_review_required": ["事实可靠性", "分析专业度", "样本意识", "读者价值", "公众号表达", "可编辑性"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.draft.read_text(encoding="utf-8"))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if not result["generation_ready_for_word"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

