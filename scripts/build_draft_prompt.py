from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "data" / "cases" / "dalian_maritime"


def build_prompt() -> tuple[str, str]:
    system = (PROJECT_ROOT / "prompts" / "single_school_system.md").read_text(encoding="utf-8")
    outline = json.loads((CASE_DIR / "outline.json").read_text(encoding="utf-8"))
    data = json.loads((CASE_DIR / "manual_data.json").read_text(encoding="utf-8"))
    selected = next(item for item in outline["title_options"] if item["id"] == outline["selected_title_id"])
    payload = {
        "confirmed_title": selected["title"],
        "audience": outline["audience"],
        "opening_angle": outline["opening_angle"],
        "core_conclusions": outline["core_conclusions"],
        "sections": outline["sections"],
        "tables": outline["tables"],
        "charts": outline["charts"],
        "required_disclosures": outline["required_disclosures"],
        "user_notes": (outline.get("approval") or {}).get("notes", ""),
        "source_data": data,
    }
    user = "请严格依据以下JSON生成初稿：\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    return system, user


if __name__ == "__main__":
    system_prompt, user_prompt = build_prompt()
    print(json.dumps({"system": system_prompt, "user": user_prompt}, ensure_ascii=False, indent=2))

