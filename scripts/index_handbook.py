from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "data" / "workspace"
MATERIALS_FILE = WORKSPACE / "materials.json"
INDEX_DIR = WORKSPACE / "handbooks"


def bookmark_title(item) -> str:
    value = item["/Title"]
    raw = getattr(value, "original_bytes", b"")
    if raw.startswith((b"\xfe\xff", b"\xff\xfe")):
        return raw.decode("utf-16").strip()
    return str(value).strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_school_index(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    outline = reader.outline
    schools = []
    for index, item in enumerate(outline):
        if isinstance(item, list):
            continue
        category = bookmark_title(item)
        normalized_category = category.replace(" ", "")
        if "拟录取分析-" not in normalized_category or not any(name in normalized_category for name in ("985", "四邮四电", "211", "双一流", "普通本科")):
            continue
        children = outline[index + 1] if index + 1 < len(outline) and isinstance(outline[index + 1], list) else []
        next_chapter_page = len(reader.pages) + 1
        for following in outline[index + 1:]:
            if not isinstance(following, list):
                next_chapter_page = reader.get_destination_page_number(following) + 1
                break
        child_items = [child for child in children if not isinstance(child, list)]
        for child_index, child in enumerate(child_items):
            name = bookmark_title(child)
            page_start = reader.get_destination_page_number(child) + 1
            page_end = (reader.get_destination_page_number(child_items[child_index + 1]) if child_index + 1 < len(child_items) else next_chapter_page - 1)
            sample = reader.pages[page_start - 1].extract_text() or ""
            schools.append({
                "school": name,
                "category": category,
                "page_start": page_start,
                "page_end": max(page_start, page_end),
                "start_page_verified": name.replace(" ", "") in sample.replace(" ", ""),
            })
    return {
        "source_file": str(pdf_path),
        "page_count": len(reader.pages),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "school_count": len(schools),
        "schools": schools,
    }


def register_handbook(pdf_path: Path) -> tuple[dict, dict]:
    pdf_path = pdf_path.resolve()
    digest = file_sha256(pdf_path)
    materials = json.loads(MATERIALS_FILE.read_text(encoding="utf-8")) if MATERIALS_FILE.exists() else []
    existing = next((item for item in materials if item.get("sha256") == digest), None)
    material_id = existing["material_id"] if existing else uuid4().hex[:12]
    index = build_school_index(pdf_path)
    index_path = INDEX_DIR / material_id / "school_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    material = existing or {
        "material_id": material_id,
        "original_name": pdf_path.name,
        "stored_name": None,
        "external_path": str(pdf_path),
        "sha256": digest,
        "size": pdf_path.stat().st_size,
        "source_type": "电子通信考研择校手册",
        "year": "2027",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    material.update({"school_index_file": str(index_path.relative_to(ROOT)), "school_count": index["school_count"], "page_count": index["page_count"]})
    if existing:
        materials[materials.index(existing)] = material
    else:
        materials.append(material)
    MATERIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = MATERIALS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(materials, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MATERIALS_FILE)
    return material, index


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    material, index = register_handbook(args.pdf)
    print(json.dumps({"material_id": material["material_id"], "school_count": index["school_count"], "page_count": index["page_count"], "verified": sum(item["start_page_verified"] for item in index["schools"])}, ensure_ascii=False))

