from __future__ import annotations

import json
import mimetypes
import argparse
import base64
import difflib
import hashlib
import os
import re
import urllib.error
import urllib.request
import shutil
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, quote, unquote, urlparse
from uuid import uuid4

import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
CASE_FILE = PROJECT_ROOT / "data" / "cases" / "dalian_maritime" / "case.json"
OUTLINE_FILE = PROJECT_ROOT / "data" / "cases" / "dalian_maritime" / "outline.json"
OUTPUT_DIR = Path(os.environ.get("YANTU_OUTPUT_DIR", str(PROJECT_ROOT / "outputs" / "dalian_maritime")))
WORKSPACE_DIR = Path(os.environ.get("YANTU_WORKSPACE_DIR", str(PROJECT_ROOT / "data" / "workspace")))
TASKS_FILE = WORKSPACE_DIR / "tasks.json"
MATERIALS_FILE = WORKSPACE_DIR / "materials.json"
MATERIALS_DIR = WORKSPACE_DIR / "materials"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from build_draft_prompt import build_prompt  # noqa: E402
from evaluate_draft import evaluate as evaluate_draft  # noqa: E402
from secret_store import forget_credentials, load_credentials, save_credentials  # noqa: E402
from generate_charts import generate_all_charts  # noqa: E402
from build_word import build as build_word_document  # noqa: E402

CREDENTIAL_FILE = Path(os.environ.get(
    "YANTU_CREDENTIAL_FILE",
    str(PROJECT_ROOT / "config" / "model_credentials.dpapi.json"),
))
try:
    _stored_credentials = load_credentials(CREDENTIAL_FILE)
    CREDENTIAL_LOAD_ERROR = None
except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
    _stored_credentials = None
    CREDENTIAL_LOAD_ERROR = str(error)
DEFAULT_MODEL = "deepseek-chat"
MODEL_CONFIG = _stored_credentials or {"api_key": None, "base_url": "https://api.deepseek.com", "model": DEFAULT_MODEL}
MODEL_CONFIG_LOCK = Lock()


def read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def write_json_list(path: Path, value: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class YantuHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = unquote(parsed_url.path)
        query = parse_qs(parsed_url.query)
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/tasks.html")
            self.end_headers()
            return
        if path == "/api/case":
            self.send_json(json.loads(CASE_FILE.read_text(encoding="utf-8")))
            return
        if path == "/api/outline":
            task_id = query.get("task_id", [""])[0]
            if task_id:
                task = next((item for item in read_json_list(TASKS_FILE) if item.get("task_id") == task_id), None)
                outline_path = WORKSPACE_DIR / "tasks" / task_id / "outline.json"
                if not task or not outline_path.is_file():
                    self.send_json({"error": "该任务还没有专属框架，请先确认数据"}, status=404); return
                self.send_json(json.loads(outline_path.read_text(encoding="utf-8")))
            else:
                self.send_json(json.loads(OUTLINE_FILE.read_text(encoding="utf-8")))
            return
        if path == "/api/model/config":
            with MODEL_CONFIG_LOCK:
                self.send_json({
                    "configured": bool(MODEL_CONFIG["api_key"]),
                    "base_url": MODEL_CONFIG["base_url"],
                    "model": MODEL_CONFIG["model"],
                    "storage": "windows_dpapi" if CREDENTIAL_FILE.exists() else "memory_only",
                    "remembered": CREDENTIAL_FILE.exists(),
                    "credential_error": CREDENTIAL_LOAD_ERROR,
                })
            return
        if path == "/api/draft":
            draft_file = OUTPUT_DIR / "draft.md"
            if not draft_file.exists():
                self.send_json({"exists": False})
            else:
                evaluation_file = OUTPUT_DIR / "evaluation.json"
                evaluation = json.loads(evaluation_file.read_text(encoding="utf-8")) if evaluation_file.exists() else None
                self.send_json({"exists": True, "content": draft_file.read_text(encoding="utf-8"), "evaluation": evaluation})
            return
        if path == "/api/revisions":
            log_file = OUTPUT_DIR / "revision_log.json"
            revisions = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else []
            for item in revisions:
                diff_path = OUTPUT_DIR / "revisions" / f"revision_{item.get('revision_id')}.diff"
                diff = diff_path.read_text(encoding="utf-8") if diff_path.is_file() else ""
                item["added_lines"] = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
                item["removed_lines"] = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
                item["diff_preview"] = diff[:20_000]
            self.send_json({"revisions": revisions})
            return
        if path == "/api/tasks":
            self.send_json({"tasks": read_json_list(TASKS_FILE)})
            return
        task_match = re.fullmatch(r"/api/tasks/([a-f0-9]{12})", path)
        if task_match:
            task = next((item for item in read_json_list(TASKS_FILE) if item.get("task_id") == task_match.group(1)), None)
            if not task:
                self.send_json({"error": "任务不存在"}, status=404); return
            materials_by_id = {item["material_id"]: item for item in read_json_list(MATERIALS_FILE)}
            task_materials = [materials_by_id[item] for item in task.get("material_ids", []) if item in materials_by_id]
            extraction = None
            facts = None
            extract_file = task.get("extract_file")
            if extract_file:
                extract_path = WORKSPACE_DIR / extract_file
                if extract_path.is_file():
                    data = json.loads(extract_path.read_text(encoding="utf-8"))
                    extraction = {key: data[key] for key in ("extracted_at", "page_count", "character_count", "page_summaries")}
            facts_file = task.get("facts_file")
            if facts_file:
                facts_path = WORKSPACE_DIR / facts_file
                if facts_path.is_file():
                    facts = json.loads(facts_path.read_text(encoding="utf-8"))
            self.send_json({"task": task, "materials": task_materials, "extraction": extraction, "facts": facts})
            return
        task_artifacts_match = re.fullmatch(r"/api/tasks/([a-f0-9]{12})/artifacts", path)
        if task_artifacts_match:
            root = WORKSPACE_DIR / "tasks" / task_artifacts_match.group(1) / "outputs"
            draft = root / "draft.md"; charts_file = root / "charts" / "manifest.json"; meta_file=root/"draft_meta.json"
            meta=json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
            from task_artifacts import assess_draft_quality,load_bundle,read_task_draft
            content=draft.read_text(encoding='utf-8') if draft.is_file() else ''
            validation_error=None
            if draft.is_file() and meta.get('operation')!='validation_fallback':
                try:
                    _,facts,_=load_bundle(WORKSPACE_DIR,TASKS_FILE,task_artifacts_match.group(1))
                    content=read_task_draft(WORKSPACE_DIR,task_artifacts_match.group(1),facts)
                except (ValueError,OSError) as error:validation_error=str(error)
            evaluation=assess_draft_quality(content) if draft.is_file() else {"generation_ready_for_word":False,"findings":[],"metrics":{}}
            if validation_error:
                evaluation['generation_ready_for_word']=False
                evaluation['findings'].append({'severity':'block','code':'admission_contract','detail':validation_error})
            word_files = sorted(root.glob("*_最新.docx"), key=lambda item: item.stat().st_mtime, reverse=True) if root.is_dir() else []
            deliverable=meta.get("operation")!="validation_fallback" and evaluation["generation_ready_for_word"]
            self.send_json({"draft": {"exists": draft.is_file(), "content": content, "meta":meta, "evaluation":evaluation, "deliverable":deliverable}, "charts": json.loads(charts_file.read_text(encoding="utf-8")) if charts_file.is_file() else {"charts": []}, "word": {"exists": bool(word_files) and deliverable, "filename": word_files[0].name if word_files and deliverable else None, "url": f"/generated/tasks/{task_artifacts_match.group(1)}/word/{quote(word_files[0].name)}" if word_files and deliverable else None}})
            return
        task_versions_match=re.fullmatch(r"/api/tasks/([a-f0-9]{12})/versions",path)
        if task_versions_match:
            task_id=task_versions_match.group(1);out=WORKSPACE_DIR/'tasks'/task_id/'outputs'
            versions_file=out/'versions.json';versions=json.loads(versions_file.read_text(encoding='utf-8')) if versions_file.is_file() else []
            for item in versions:
                item['draft_url']=f"/generated/tasks/{task_id}/draft-version/{quote(Path(item['draft_file']).name)}"
            words=[]
            latest=next(iter(sorted(out.glob('*_最新.docx'),key=lambda x:x.stat().st_mtime,reverse=True)),None) if out.is_dir() else None
            if latest:words.append({'filename':latest.name,'current':True,'saved_at':datetime.fromtimestamp(latest.stat().st_mtime,timezone.utc).isoformat(),'url':f"/generated/tasks/{task_id}/word/{quote(latest.name)}"})
            history=out/'word_history'
            if history.is_dir():
                for file in sorted(history.glob('*.docx'),key=lambda x:x.stat().st_mtime,reverse=True):words.append({'filename':file.name,'current':False,'saved_at':datetime.fromtimestamp(file.stat().st_mtime,timezone.utc).isoformat(),'url':f"/generated/tasks/{task_id}/word-version/{quote(file.name)}"})
            self.send_json({'versions':list(reversed(versions)),'word_versions':words});return
        if path == "/api/materials":
            self.send_json({"materials": read_json_list(MATERIALS_FILE)})
            return
        if path == "/api/schools":
            schools = []
            for material in read_json_list(MATERIALS_FILE):
                index_file = material.get("school_index_file")
                if not index_file:
                    continue
                index_path = PROJECT_ROOT / index_file
                if index_path.is_file():
                    for item in json.loads(index_path.read_text(encoding="utf-8")).get("schools", []):
                        schools.append({**item, "material_id": material["material_id"], "material_name": material["original_name"]})
            self.send_json({"schools": schools})
            return
        if path == "/api/word/versions":
            current_meta = OUTPUT_DIR / "word_generation.json"
            current = json.loads(current_meta.read_text(encoding="utf-8")) if current_meta.exists() else None
            history_dir = OUTPUT_DIR / "word_history"
            history = []
            if history_dir.is_dir():
                for file in sorted(history_dir.glob("*.docx"), key=lambda item: item.stat().st_mtime, reverse=True):
                    history.append({
                        "filename": file.name,
                        "url": f"/generated/word-history/{file.name}",
                        "size": file.stat().st_size,
                        "saved_at": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(),
                    })
            self.send_json({"current": current, "history": history})
            return
        if path == "/api/charts":
            manifest_file = OUTPUT_DIR / "charts" / "charts_manifest.json"
            if not manifest_file.exists():
                self.send_json({"exists": False, "charts": []})
            else:
                self.send_json({"exists": True, **json.loads(manifest_file.read_text(encoding="utf-8"))})
            return
        if path == "/api/word":
            metadata_file = OUTPUT_DIR / "word_generation.json"
            if not metadata_file.exists():
                self.send_json({"exists": False})
            else:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                draft_file = OUTPUT_DIR / "draft.md"
                word_file = OUTPUT_DIR / metadata.get("filename", "")
                needs_update = draft_file.exists() and (not word_file.exists() or draft_file.stat().st_mtime > word_file.stat().st_mtime)
                self.send_json({"exists": True, "needs_update": needs_update, **metadata})
            return
        if path == "/api/health":
            self.send_json({"status": "ok", "project": "研途编辑"})
            return

        if path.startswith("/generated/charts/"):
            filename = path.removeprefix("/generated/charts/")
            if not filename or Path(filename).name != filename or not filename.endswith(".png"):
                self.send_error(403)
                return
            requested_chart = (OUTPUT_DIR / "charts" / filename).resolve()
            try:
                requested_chart.relative_to((OUTPUT_DIR / "charts").resolve())
            except ValueError:
                self.send_error(403)
                return
            if not requested_chart.is_file():
                self.send_error(404)
                return
            content = requested_chart.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path.startswith("/generated/word/"):
            filename = path.removeprefix("/generated/word/")
            if not filename or Path(filename).name != filename or not filename.endswith(".docx"):
                self.send_error(403)
                return
            requested_word = (OUTPUT_DIR / filename).resolve()
            try:
                requested_word.relative_to(OUTPUT_DIR.resolve())
            except ValueError:
                self.send_error(403)
                return
            if not requested_word.is_file():
                self.send_error(404)
                return
            content = requested_word.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path.startswith("/generated/word-history/"):
            filename = path.removeprefix("/generated/word-history/")
            if not filename or Path(filename).name != filename or not filename.endswith(".docx"):
                self.send_error(403)
                return
            history_root = (OUTPUT_DIR / "word_history").resolve()
            requested_word = (history_root / filename).resolve()
            try:
                requested_word.relative_to(history_root)
            except ValueError:
                self.send_error(403)
                return
            if not requested_word.is_file():
                self.send_error(404)
                return
            content = requested_word.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        generated_task_match = re.fullmatch(r"/generated/tasks/([a-f0-9]{12})/(charts|word|draft-version|word-version)/([^/]+)", path)
        if generated_task_match:
            task_id, kind, filename = generated_task_match.groups()
            if Path(filename).name != filename:
                self.send_error(403); return
            sub={'charts':'charts','word':'','draft-version':'versions','word-version':'word_history'}[kind]
            root = (WORKSPACE_DIR / "tasks" / task_id / "outputs" / sub).resolve()
            requested = (root / filename).resolve()
            try: requested.relative_to(root)
            except ValueError: self.send_error(403); return
            if not requested.is_file() or (kind == "charts" and requested.suffix != ".png") or (kind in ('word','word-version') and requested.suffix != ".docx") or (kind=='draft-version' and requested.suffix!='.md'):
                self.send_error(404); return
            content=requested.read_bytes(); self.send_response(200); self.send_header("Content-Type", "image/png" if kind == "charts" else "text/markdown; charset=utf-8" if kind=='draft-version' else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            if kind != "charts": self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Content-Length",str(len(content))); self.end_headers(); self.wfile.write(content); return

        relative = path.lstrip("/")
        requested = (STATIC_DIR / relative).resolve()
        try:
            requested.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not requested.is_file():
            self.send_error(404)
            return

        content_type, _ = mimetypes.guess_type(requested.name)
        content = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/model/config":
            self.configure_model()
            return
        if path == "/api/model/test":
            self.test_model()
            return
        if path == "/api/model/forget":
            self.forget_model()
            return
        if path == "/api/draft/generate":
            self.generate_draft()
            return
        if path == "/api/draft/revise":
            self.revise_draft()
            return
        if path == "/api/tasks":
            self.create_task()
            return
        task_extract_match = re.fullmatch(r"/api/tasks/([a-f0-9]{12})/extract", path)
        if task_extract_match:
            self.extract_task_materials(task_extract_match.group(1))
            return
        task_confirm_match = re.fullmatch(r"/api/tasks/([a-f0-9]{12})/confirm-facts", path)
        if task_confirm_match:
            self.confirm_task_facts(task_confirm_match.group(1))
            return
        task_operation_match = re.fullmatch(r"/api/tasks/([a-f0-9]{12})/(generate-draft|revise-draft|generate-charts|generate-word)", path)
        if task_operation_match:
            self.task_artifact_operation(task_operation_match.group(1), task_operation_match.group(2))
            return
        if path == "/api/materials/upload":
            self.upload_material()
            return
        if path == "/api/charts/generate":
            try:
                manifest = generate_all_charts(output_dir=OUTPUT_DIR / "charts")
                self.send_json({"status": "generated", **manifest})
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                self.send_json({"error": f"图表生成失败：{error}"}, status=500)
            return
        if path == "/api/word/generate":
            self.generate_word()
            return
        if path != "/api/outline/approve":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("请求内容大小不合法")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            task_id = str(payload.get("task_id", ""))
            outline_path = WORKSPACE_DIR / "tasks" / task_id / "outline.json" if task_id else OUTLINE_FILE
            if not outline_path.is_file():
                raise ValueError("找不到当前任务的文章框架")
            outline = json.loads(outline_path.read_text(encoding="utf-8"))
            valid_title_ids = {item["id"] for item in outline["title_options"]}
            if payload.get("selected_title_id") not in valid_title_ids:
                raise ValueError("请选择有效标题")
            outline["selected_title_id"] = payload["selected_title_id"]
            outline["status"] = "approved"
            outline["approval"] = {
                "decided_by": "user",
                "decided_at": payload.get("decided_at"),
                "notes": str(payload.get("notes", ""))[:1000],
            }
            temporary = outline_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(outline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(outline_path)
            self.send_json({"status": "approved", "next_stage": "draft_generation"})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, status=400)

    def do_DELETE(self) -> None:
        path=unquote(urlparse(self.path).path);match=re.fullmatch(r"/api/tasks/([a-f0-9]{12})",path)
        if not match:self.send_error(404);return
        task_id=match.group(1);tasks=read_json_list(TASKS_FILE);task=next((x for x in tasks if x.get('task_id')==task_id),None)
        if not task:self.send_json({'error':'任务不存在'},status=404);return
        write_json_list(TASKS_FILE,[x for x in tasks if x.get('task_id')!=task_id])
        root=WORKSPACE_DIR/'tasks'/task_id
        if root.exists():
            trash=WORKSPACE_DIR/'.trash';trash.mkdir(exist_ok=True);target=trash/f"{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}";shutil.move(str(root),str(target))
        self.send_json({'status':'deleted','task_id':task_id})

    def read_json_body(self, max_bytes: int = 32_768) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_bytes:
            raise ValueError("请求内容大小不合法")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求必须是JSON对象")
        return payload

    def create_task(self) -> None:
        try:
            payload = self.read_json_body()
            topic_type = str(payload.get("topic_type", "")).strip()
            if topic_type not in {"school_analysis", "employment", "major_direction"}:
                raise ValueError("请选择有效的选题类型")
            school = str(payload.get("school", "")).strip()[:100]
            title = str(payload.get("title", "")).strip()[:160]
            if not title and topic_type == "school_analysis" and school:
                title = f"{school}电子通信考研择校分析"
            if not title:
                raise ValueError("请填写任务名称")
            raw_material_ids = payload.get("material_ids", [])
            if not isinstance(raw_material_ids, list):
                raise ValueError("资料引用格式不正确")
            material_ids = [str(item) for item in raw_material_ids]
            all_materials=read_json_list(MATERIALS_FILE)
            known_ids = {item["material_id"] for item in all_materials}
            if any(item not in known_ids for item in material_ids):
                raise ValueError("任务引用了不存在的资料")
            source_refs = []
            materials_by_id = {item["material_id"]: item for item in all_materials}
            for material_id in material_ids:
                material = materials_by_id[material_id]
                index_file = material.get("school_index_file")
                material_name = material.get('stored_name') or material.get('external_path') or material.get('original_name') or ''
                if school and Path(material_name).suffix.lower()=='.docx' and not index_file:
                    source_refs.append({"material_id":material_id,"school":school,"page_start":1,"page_end":1,"category":"用户补充Word资料（学校章节）","location_kind":"docx_school_section"})
                    continue
                if not school or not index_file:
                    continue
                index_path = PROJECT_ROOT / index_file
                if index_path.is_file():
                    school_item = next((item for item in json.loads(index_path.read_text(encoding="utf-8")).get("schools", []) if item["school"] == school), None)
                    if school_item:source_refs.append({"material_id": material_id, "school": school, "page_start": school_item["page_start"], "page_end": school_item["page_end"], "category": school_item["category"]})
            tasks = read_json_list(TASKS_FILE)
            task = {
                "task_id": uuid4().hex[:12], "title": title, "topic_type": topic_type,
                "school": school, "college": str(payload.get("college", "")).strip()[:100],
                "target_year": str(payload.get("target_year", "")).strip()[:10],
                "material_ids": material_ids, "source_refs": source_refs, "status": "materials_pending_review",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            tasks.append(task); write_json_list(TASKS_FILE, tasks)
            self.send_json({"status": "created", "task": task}, status=201)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, status=400)

    def upload_material(self) -> None:
        try:
            payload = self.read_json_body(max_bytes=140 * 1024 * 1024)
            filename = Path(str(payload.get("filename", ""))).name
            suffix = Path(filename).suffix.lower()
            if not filename or suffix not in {".pdf", ".docx", ".html", ".xlsx", ".csv", ".txt", ".md"}:
                raise ValueError("仅支持PDF、Word、HTML、Excel、CSV和文本资料")
            content = base64.b64decode(str(payload.get("content_base64", "")), validate=True)
            if not content or len(content) > 100 * 1024 * 1024:
                raise ValueError("单个资料必须在100MB以内")
            digest = hashlib.sha256(content).hexdigest()
            materials = read_json_list(MATERIALS_FILE)
            existing = next((item for item in materials if item["sha256"] == digest), None)
            if existing:
                self.send_json({"status": "reused", "material": existing}); return
            MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
            material_id = uuid4().hex[:12]
            stored_name = f"{material_id}{suffix}"
            (MATERIALS_DIR / stored_name).write_bytes(content)
            material = {
                "material_id": material_id, "original_name": filename, "stored_name": stored_name,
                "sha256": digest, "size": len(content),
                "source_type": str(payload.get("source_type", "用户上传"))[:40],
                "year": str(payload.get("year", ""))[:10],
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            materials.append(material); write_json_list(MATERIALS_FILE, materials)
            self.send_json({"status": "uploaded", "material": material}, status=201)
        except (ValueError, json.JSONDecodeError, base64.binascii.Error) as error:
            self.send_json({"error": str(error)}, status=400)

    def extract_task_materials(self, task_id: str) -> None:
        try:
            from pypdf import PdfReader
            from handbook_parser import parse_handbook_pages
            tasks = read_json_list(TASKS_FILE)
            task = next((item for item in tasks if item.get("task_id") == task_id), None)
            if not task:
                self.send_json({"error": "任务不存在"}, status=404); return
            if not task.get("source_refs"):
                self.send_json({"error": "任务还没有可解析的手册页码"}, status=409); return
            materials = {item["material_id"]: item for item in read_json_list(MATERIALS_FILE)}
            pages = [];page_sets=[]
            for source_ref in task["source_refs"]:
                material = materials.get(source_ref["material_id"])
                if not material:
                    raise ValueError("任务引用的资料不存在")
                source_path = Path(material.get("external_path") or (MATERIALS_DIR / material.get("stored_name", "")))
                if not source_path.is_file():
                    raise ValueError(f"找不到原始资料：{material['original_name']}")
                material_pages=[]
                if source_path.suffix.lower()=='.pdf':
                    reader = PdfReader(str(source_path))
                    for page_number in range(source_ref["page_start"], source_ref["page_end"] + 1):
                        text = (reader.pages[page_number - 1].extract_text() or "").strip()
                        material_pages.append({"material_id": material["material_id"], "material_name":material['original_name'],"page_number": page_number, "text": text, "character_count": len(text)})
                    from ocr_fallback import enrich_sparse_admission_pages,extract_cutoff_grid,extract_admission_grids
                    enrich_sparse_admission_pages(source_path,material_pages)
                    cutoff_heading = re.compile(r'(?:近[\u4e00-三两\d]年)?(?:复试|录取)(?:分数)?线(?:变化)?(?:情况)?')
                    for page in material_pages:
                        if re.search(r'20\d{2}\s*年\s*[|｜]?\s*一志愿',page.get('text','')):
                            page['ocr_admission_rows']=extract_admission_grids(source_path,int(page['page_number']))
                        if cutoff_heading.search(page.get('text','')):
                            page['ocr_cutoff_rows']=extract_cutoff_grid(source_path,int(page['page_number']))
                elif source_path.suffix.lower()=='.docx':
                    from material_extract import extract_docx_school_section
                    text=extract_docx_school_section(source_path,source_ref.get('school') or task.get('school',''))
                    material_pages.append({"material_id":material['material_id'],"material_name":material['original_name'],"page_number":1,"location_label":"Word学校章节","text":text,"character_count":len(text)})
                else:raise ValueError('当前学校手册解析支持PDF和Word资料')
                pages.extend(material_pages)
                page_sets.append((material['material_id'], source_path.suffix.lower(), material_pages))
            extracted_at = datetime.now(timezone.utc).isoformat()
            extraction = {
                "task_id": task_id, "school": task.get("school"), "extracted_at": extracted_at, "parser_revision":"cutoff-grid-v2",
                "page_count": len(pages), "character_count": sum(item["character_count"] for item in pages),
                "page_summaries": [{"page_number": item["page_number"], "character_count": item["character_count"], "preview": item["text"][:160]} for item in pages],
                "pages": pages,
            }
            task_dir = WORKSPACE_DIR / "tasks" / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            extract_path = task_dir / "source_extract.json"
            extract_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            parsed_sets=[];parsed_material_ids=[];unparsed_material_ids=[]
            for material_id,source_suffix,material_pages in page_sets:
                parsed=parse_handbook_pages(task.get("school", ""),material_pages)
                if source_suffix=='.docx':
                    from handbook_parser import parse_vertical_cutoff_table
                    vertical=parse_vertical_cutoff_table(material_pages[0]['text'],material_pages[0]['page_number'])
                    if vertical:
                        parsed=parsed or {'schema_version':'1.3','parser_mode':'docx_vertical_tables','school':task.get('school',''),'colleges':[],'programs':[],'admission_2026':[],'cutoffs':[],'course_notes':[],'score_formulas':[],'school_profile':{},'warnings':[],'excluded_pages':[],'review_status':'pending_user_review'}
                        if not parsed.get('cutoffs'):parsed['cutoffs']=vertical
                if parsed:
                    for section in ('programs','admission_2026','cutoffs','course_notes','score_formulas'):
                        for row in parsed.get(section,[]):row['material_id']=material_id
                    parsed_sets.append((material_id,parsed));parsed_material_ids.append(material_id)
                else:unparsed_material_ids.append(material_id)
            if len(parsed_sets)>1:
                from fact_merge import merge_fact_sets
                facts=merge_fact_sets(task.get('school',''),parsed_sets)
            else:facts=parsed_sets[0][1] if parsed_sets else None
            if facts:
                facts['source_material_ids']=parsed_material_ids
                facts['unparsed_material_ids']=unparsed_material_ids
                if unparsed_material_ids:facts.setdefault('warnings',[]).append('部分资料已成功提取原文，但其排版尚未形成可合并的结构化字段；请结合原文预览人工核对。')
                facts_path = task_dir / "structured_facts.json"
                if facts_path.is_file():
                    from fact_merge import preserve_reviewed_overrides
                    facts=preserve_reviewed_overrides(json.loads(facts_path.read_text(encoding='utf-8')),facts)
                facts_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                task.update({"facts_file": str(facts_path.relative_to(WORKSPACE_DIR)), "status": "facts_pending_review"})
            else:
                task.update({"status": "materials_extracted"})
            task.update({"extracted_at": extracted_at, "extract_file": str(extract_path.relative_to(WORKSPACE_DIR))})
            write_json_list(TASKS_FILE, tasks)
            self.send_json({"status": "extracted", "task": task, "facts": facts, "extraction": {key: extraction[key] for key in ("extracted_at", "page_count", "character_count", "page_summaries")}})
        except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
            self.send_json({"error": f"资料解析失败：{error}"}, status=500)

    def confirm_task_facts(self, task_id: str) -> None:
        tasks = read_json_list(TASKS_FILE)
        task = next((item for item in tasks if item.get("task_id") == task_id), None)
        if not task:
            self.send_json({"error": "任务不存在"}, status=404); return
        if not task.get("facts_file"):
            self.send_json({"error": "请先完成结构化解析"}, status=409); return
        task["status"] = "facts_confirmed"
        task["facts_confirmed_at"] = datetime.now(timezone.utc).isoformat()
        from task_outline import build_task_outline
        facts_path = WORKSPACE_DIR / task["facts_file"]
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        outline = build_task_outline(task, facts)
        outline_path = WORKSPACE_DIR / "tasks" / task_id / "outline.json"
        outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        task["outline_file"] = str(outline_path.relative_to(WORKSPACE_DIR))
        write_json_list(TASKS_FILE, tasks)
        self.send_json({"status": "confirmed", "task": task, "next_url": f"/outline.html?task_id={task_id}"})

    def task_artifact_operation(self, task_id: str, operation: str) -> None:
        from source_notes import sources_at_end
        from task_artifacts import assess_draft_quality, build_prompt as build_task_prompt, build_word, generate_charts, persist_draft,load_bundle,read_task_draft,task_assets
        from admission_document import compile_draft
        try:
            if operation == "generate-draft":
                system, user = build_task_prompt(WORKSPACE_DIR, TASKS_FILE, PROJECT_ROOT, task_id)
                content, usage, _ = call_chat_completion(system, user, max_tokens=7000, temperature=0.35)
                meta = persist_draft(WORKSPACE_DIR, task_id, content, usage)
                _,facts,_=load_bundle(WORKSPACE_DIR,TASKS_FILE,task_id)
                content=read_task_draft(WORKSPACE_DIR,task_id,facts)
                self.send_json({"status": "generated", "content": content, "evaluation": assess_draft_quality(content), "meta": meta}); return
            if operation == "revise-draft":
                payload=self.read_json_body(); instructions=str(payload.get("instructions","")).strip()
                if not instructions: raise ValueError("修改意见不能为空")
                root=WORKSPACE_DIR/"tasks"/task_id/"outputs"; draft=root/"draft.md"
                if not draft.is_file(): raise ValueError("当前任务还没有初稿")
                system, source = build_task_prompt(WORKSPACE_DIR,TASKS_FILE,PROJECT_ROOT,task_id)
                _,facts,_=load_bundle(WORKSPACE_DIR,TASKS_FILE,task_id)
                current=read_task_draft(WORKSPACE_DIR,task_id,facts)
                contract=build_revision_contract(instructions)
                prompt=f"请按照编辑意见修订完整文章，不输出修改说明。修改必须在相关段落中形成明显可见的变化；要求简化时，删除重复数字解说、推测和冗长建议，只保留表格结论与必要解释。不得新增来源字段中不存在的数字。\n\n编辑意见：\n{instructions}\n\n当前文章：\n{current}\n\n事实约束：\n{source}"
                content,usage,_=call_chat_completion(system,prompt,max_tokens=7000,temperature=0.2)
                # The model may correctly return deterministic handbook and
                # admission placeholders. Expand them before comparing tables
                # with the current rendered draft, otherwise a valid revision
                # is falsely reported as deleting every table.
                content=compile_draft(content,facts,task_assets(WORKSPACE_DIR,task_id,facts),add_default_charts=False)
                compliance=verify_revision_contract(current,content,contract)
                failed=[x for x in compliance if x['status']=='failed']
                if failed:
                    raise ValueError('修改意见未实际落实，已保留原稿：'+'；'.join(x['evidence'] for x in failed))
                persist_draft(WORKSPACE_DIR,task_id,content,usage,"revision",instructions,compliance)
                content=read_task_draft(WORKSPACE_DIR,task_id,facts)
                self.send_json({"status":"revised","content":content,"evaluation":assess_draft_quality(content),"compliance":compliance}); return
            if operation == "generate-charts":
                self.send_json({"status":"generated",**generate_charts(WORKSPACE_DIR,TASKS_FILE,task_id)}); return
            target=build_word(WORKSPACE_DIR,TASKS_FILE,task_id)
            self.send_json({"status":"generated","filename":target.name,"url":f"/generated/tasks/{task_id}/word/{quote(target.name)}"})
        except ValueError as error: self.send_json({"error":str(error)},status=409)
        except ModelRequestError as error: self.send_json({"error":str(error)},status=502)
        except (OSError,RuntimeError,json.JSONDecodeError) as error: self.send_json({"error":f"任务处理失败：{error}"},status=500)

    @staticmethod
    def evaluate_task_draft(content: str) -> dict:
        from task_artifacts import assess_draft_quality
        return assess_draft_quality(content)

    def configure_model(self) -> None:
        global CREDENTIAL_LOAD_ERROR
        try:
            payload = self.read_json_body()
            api_key = str(payload.get("api_key", "")).strip()
            base_url = str(payload.get("base_url", "")).strip().rstrip("/")
            model = str(payload.get("model", "")).strip()
            remember = bool(payload.get("remember", False))
            parsed = urlparse(base_url)
            if not api_key:
                raise ValueError("API密钥不能为空")
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("模型地址必须是有效的HTTPS地址")
            if not model or len(model) > 120:
                raise ValueError("模型ID不能为空或过长")
            with MODEL_CONFIG_LOCK:
                MODEL_CONFIG.update({"api_key": api_key, "base_url": base_url, "model": model})
            if remember:
                save_credentials(CREDENTIAL_FILE, api_key, base_url, model)
                CREDENTIAL_LOAD_ERROR = None
            else:
                forget_credentials(CREDENTIAL_FILE)
                CREDENTIAL_LOAD_ERROR = None
            self.send_json({"configured": True, "base_url": base_url, "model": model, "storage": "windows_dpapi" if remember else "memory_only", "remembered": remember})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, status=400)
        except (OSError, RuntimeError) as error:
            self.send_json({"error": f"密钥安全保存失败：{error}"}, status=500)

    def forget_model(self) -> None:
        forget_credentials(CREDENTIAL_FILE)
        with MODEL_CONFIG_LOCK:
            MODEL_CONFIG.update({"api_key": None, "base_url": "https://api.deepseek.com", "model": DEFAULT_MODEL})
        self.send_json({"configured": False, "remembered": False, "storage": "memory_only"})

    def test_model(self) -> None:
        try:
            models = list_models()
            with MODEL_CONFIG_LOCK:
                configured_model = MODEL_CONFIG["model"]
                api_key = MODEL_CONFIG["api_key"]
                base_url = MODEL_CONFIG["base_url"]
            selected_model = select_available_model(configured_model, models)
            changed = selected_model != configured_model
            if changed:
                with MODEL_CONFIG_LOCK:
                    MODEL_CONFIG["model"] = selected_model
                if CREDENTIAL_FILE.exists() and api_key:
                    save_credentials(CREDENTIAL_FILE, api_key, base_url, selected_model)
            self.send_json({
                "status": "ok",
                "model": selected_model,
                "previous_model": configured_model if changed else None,
                "model_changed": changed,
                "reply": f"连接成功，已使用模型 {selected_model}",
            })
        except ModelRequestError as error:
            self.send_json({"error": str(error)}, status=502)

    def generate_draft(self) -> None:
        outline = json.loads(OUTLINE_FILE.read_text(encoding="utf-8"))
        if outline.get("status") != "approved" or not outline.get("selected_title_id"):
            self.send_json({"error": "文章框架尚未确认"}, status=409)
            return
        try:
            system_prompt, user_prompt = build_prompt()
            content, usage, finish_reason = call_chat_completion(system_prompt, user_prompt, max_tokens=7000, temperature=0.35)
            result = persist_draft(content, usage, finish_reason, operation="generation")
            self.send_json({"status": "generated", "content": content, "usage": usage, **result})
        except ModelRequestError as error:
            self.send_json({"error": str(error)}, status=502)

    def revise_draft(self) -> None:
        draft_file = OUTPUT_DIR / "draft.md"
        if not draft_file.exists():
            self.send_json({"error": "当前没有可修改的初稿"}, status=409)
            return
        try:
            payload = self.read_json_body()
            instructions = str(payload.get("instructions", "")).strip()
            if not instructions:
                raise ValueError("修改意见不能为空")
            if len(instructions) > 4000:
                raise ValueError("修改意见不能超过4000字")
            current = draft_file.read_text(encoding="utf-8")
            contract = build_revision_contract(instructions)
            checklist = "\n".join(f"{index + 1}. {item['request']}" for index, item in enumerate(contract))
            system_prompt, source_prompt = build_prompt()
            revision_user = (
                "请先逐条理解下面的编辑要求，再修订全文。每一条都必须落实；不要只做同义改写。编辑意见只改变表达、结构和强调重点；所有事实仍受原始资料约束。\n\n"
                f"<REQUIREMENT_CHECKLIST>\n{checklist}\n</REQUIREMENT_CHECKLIST>\n\n"
                f"<EDITOR_FEEDBACK>\n{instructions}\n</EDITOR_FEEDBACK>\n\n"
                f"<CURRENT_DRAFT>\n{current}\n</CURRENT_DRAFT>\n\n"
                f"<SOURCE_CONSTRAINTS>\n{source_prompt}\n</SOURCE_CONSTRAINTS>"
            )
            content, usage, finish_reason = call_chat_completion(
                system_prompt + "\n\n修订时输出完整文章，不输出修改说明，不得新增资料中不存在的数字。",
                revision_user,
                max_tokens=7000,
                temperature=0.25,
            )
            manual_data = (PROJECT_ROOT / "data" / "cases" / "dalian_maritime" / "manual_data.json").read_text(encoding="utf-8")
            unknown_numbers = find_unapproved_numbers(content, current + "\n" + manual_data)
            if unknown_numbers:
                self.send_json({"error": "修订稿出现资料中不存在的新数字，已停止保存。", "unknown_numbers": unknown_numbers}, status=409)
                return
            compliance = verify_revision_contract(current, content, contract)
            failed = [item for item in compliance if item["status"] == "failed"]
            if failed:
                self.send_json({"error": "修改稿未落实全部硬性意见，已停止保存。", "compliance": compliance}, status=422)
                return
            result = persist_draft(content, usage, finish_reason, operation="revision", instructions=instructions, compliance=compliance)
            self.send_json({"status": "revised", "content": content, "usage": usage, "compliance": compliance, **result})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, status=400)
        except ModelRequestError as error:
            self.send_json({"error": str(error)}, status=502)

    def generate_word(self) -> None:
        draft_file = OUTPUT_DIR / "draft.md"
        if not draft_file.exists():
            self.send_json({"error": "当前没有可用于生成Word的初稿"}, status=409)
            return
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            latest = OUTPUT_DIR / "大连海事大学电子通信考研择校分析_最新.docx"
            history_dir = OUTPUT_DIR / "word_history"
            archived = None
            if latest.exists():
                history_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archived = history_dir / f"大连海事大学电子通信考研择校分析_{stamp}.docx"
                latest.replace(archived)
            build_word_document(latest)
            generated_at = datetime.now(timezone.utc).isoformat()
            metadata = {
                "filename": latest.name,
                "url": f"/generated/word/{latest.name}",
                "generated_at": generated_at,
                "size": latest.stat().st_size,
                "archived_previous": str(archived.relative_to(PROJECT_ROOT)) if archived else None,
                "template_type": "single_school_analysis",
            }
            temporary = OUTPUT_DIR / ".word_generation.json.tmp"
            temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(OUTPUT_DIR / "word_generation.json")
            self.send_json({"status": "generated", **metadata})
        except (OSError, ValueError, RuntimeError) as error:
            self.send_json({"error": f"Word生成失败：{error}"}, status=500)

    def send_json(self, payload: object, status: int = 200) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[研途编辑] {self.address_string()} - {format % args}")


def find_unapproved_numbers(candidate: str, allowed_text: str) -> list[str]:
    pattern = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?%?")
    allowed = set(pattern.findall(allowed_text))
    return sorted(set(pattern.findall(candidate)) - allowed)


def build_revision_contract(instructions: str) -> list[dict]:
    requests = [item.strip(" -\t") for item in re.split(r"[\n；;。]+", instructions) if item.strip(" -\t")]
    contract = []
    for request in requests or [instructions.strip()]:
        lowered = request.lower()
        if "图" in request and any(word in request for word in ("删除", "删掉", "去掉", "不需要", "不要")):
            kind = "remove_chart"
        elif "表格" in request and any(word in request for word in ("保留", "不要删", "不能删")):
            kind = "preserve_tables"
        elif any(word in request for word in ("简单", "简化", "精简", "概括", "太复杂", "太长", "啰嗦")):
            kind = "simplify"
        else:
            kind = "human_review"
        contract.append({"request": request, "kind": kind})
    return contract


def verify_revision_contract(previous: str, revised: str, contract: list[dict]) -> list[dict]:
    results = []
    previous_tables = sum(1 for line in previous.splitlines() if line.strip().startswith("|"))
    revised_tables = sum(1 for line in revised.splitlines() if line.strip().startswith("|"))
    changed = previous.strip() != revised.strip()
    for item in contract:
        kind = item["kind"]
        if kind == "remove_chart":
            passed = "[图表建议" not in revised
            status, evidence = ("passed", "对应图表标记已删除") if passed else ("failed", "正文仍保留图表标记")
        elif kind == "preserve_tables":
            passed = revised_tables >= previous_tables
            status, evidence = ("passed", f"表格行数保持为{revised_tables}行") if passed else ("failed", f"表格行数从{previous_tables}行减少到{revised_tables}行")
        elif kind == "simplify":
            # A simplification request must make a measurable reduction. Merely
            # rephrasing the same amount of text is not accepted as completed.
            old_len=len(re.sub(r"\s+", "", previous));new_len=len(re.sub(r"\s+", "", revised))
            passed=changed and new_len <= old_len*0.9
            status="passed" if passed else "failed"
            evidence=(f"正文由{old_len}字精简到{new_len}字" if passed else f"正文长度由{old_len}字变为{new_len}字，没有达到明确精简的标准")
        else:
            status = "human_review" if changed else "failed"
            evidence = "正文已发生变化，需要人工确认修改是否专业、有效" if changed else "正文没有发生实质变化"
        results.append({**item, "status": status, "evidence": evidence})
    return results


def persist_draft(
    content: str,
    usage: dict,
    finish_reason: str,
    operation: str,
    instructions: str = "",
    compliance: list[dict] | None = None,
) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    draft_file = OUTPUT_DIR / "draft.md"
    evaluation_file = OUTPUT_DIR / "evaluation.json"
    metadata_file = OUTPUT_DIR / "generation.json"
    history_dir = OUTPUT_DIR / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    previous_content = draft_file.read_text(encoding="utf-8") if draft_file.exists() else None
    previous_evaluation = json.loads(evaluation_file.read_text(encoding="utf-8")) if evaluation_file.exists() else None
    evaluation = evaluate_draft(content)

    temporary_draft = OUTPUT_DIR / ".draft.md.tmp"
    temporary_draft.write_text(content.rstrip() + "\n", encoding="utf-8")
    version = None
    if draft_file.exists():
        version = 1
        while (history_dir / f"draft_v{version}.md").exists():
            version += 1
        draft_file.replace(history_dir / f"draft_v{version}.md")
        if evaluation_file.exists():
            evaluation_file.replace(history_dir / f"evaluation_v{version}.json")
        if metadata_file.exists():
            metadata_file.replace(history_dir / f"generation_v{version}.json")
    temporary_draft.replace(draft_file)
    evaluation_file.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with MODEL_CONFIG_LOCK:
        safe_config = {"base_url": MODEL_CONFIG["base_url"], "model": MODEL_CONFIG["model"]}
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **safe_config,
        "operation": operation,
        "usage": usage,
        "finish_reason": finish_reason,
        "prompt_version": "single_school_style_v2",
        "api_key_stored": False,
    }
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    revision_record = None
    if operation == "revision" and previous_content is not None:
        revisions_dir = OUTPUT_DIR / "revisions"
        revisions_dir.mkdir(parents=True, exist_ok=True)
        log_file = OUTPUT_DIR / "revision_log.json"
        log = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else []
        revision_number = len(log) + 1
        diff = "".join(difflib.unified_diff(
            previous_content.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"draft_v{version}.md",
            tofile="draft.md",
            lineterm="\n",
        ))
        diff_path = revisions_dir / f"revision_{revision_number}.diff"
        diff_path.write_text(diff, encoding="utf-8")
        revision_record = {
            "revision_id": revision_number,
            "revised_at": metadata["generated_at"],
            "instructions": instructions,
            "previous_version": version,
            "diff_file": str(diff_path.relative_to(PROJECT_ROOT)),
            "previous_ready_for_word": previous_evaluation.get("generation_ready_for_word") if previous_evaluation else None,
            "current_ready_for_word": evaluation["generation_ready_for_word"],
            "compliance": compliance or [],
        }
        log.append(revision_record)
        temporary_log = log_file.with_suffix(".json.tmp")
        temporary_log.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_log.replace(log_file)

    return {"evaluation": evaluation, "revision": revision_record}


class ModelRequestError(RuntimeError):
    pass


def chat_endpoint(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return base_url + "/chat/completions"
    return base_url + "/chat/completions"


def models_endpoint(base_url: str) -> str:
    if base_url.endswith("/v1"):
        return base_url + "/models"
    return base_url + "/models"


def list_models() -> list[str]:
    with MODEL_CONFIG_LOCK:
        api_key = MODEL_CONFIG["api_key"]
        base_url = MODEL_CONFIG["base_url"]
    if not api_key:
        raise ModelRequestError("请先在页面中配置API密钥")
    request = urllib.request.Request(
        models_endpoint(base_url),
        method="GET",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise ModelRequestError(f"模型列表接口返回HTTP {error.code}：{detail}") from error
    except urllib.error.URLError as error:
        raise ModelRequestError(f"无法连接模型接口：{error.reason}") from error
    try:
        return [item["id"] for item in result["data"] if isinstance(item.get("id"), str)]
    except (KeyError, TypeError) as error:
        raise ModelRequestError("模型列表响应格式不正确") from error


def select_available_model(configured_model: str, models: list[str]) -> str:
    """Resolve a usable chat model without making users guess provider model IDs."""
    if configured_model in models:
        return configured_model
    for preferred in (DEFAULT_MODEL, "deepseek-reasoner"):
        if preferred in models:
            return preferred
    chat_models = [model for model in models if "chat" in model.lower()]
    if chat_models:
        return chat_models[0]
    if models:
        return models[0]
    raise ModelRequestError("连接成功，但服务商没有返回任何可用模型")


def call_chat_completion(system: str, user: str, max_tokens: int, temperature: float) -> tuple[str, dict, str]:
    with MODEL_CONFIG_LOCK:
        api_key = MODEL_CONFIG["api_key"]
        base_url = MODEL_CONFIG["base_url"]
        model = MODEL_CONFIG["model"]
    if not api_key:
        raise ModelRequestError("请先在页面中配置API密钥")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        chat_endpoint(base_url),
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=660) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise ModelRequestError(f"模型接口返回HTTP {error.code}：{detail}") from error
    except urllib.error.URLError as error:
        raise ModelRequestError(f"无法连接模型接口：{error.reason}") from error
    except TimeoutError as error:
        raise ModelRequestError("模型接口响应超时，请稍后重试") from error
    try:
        choice = result["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice["finish_reason"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelRequestError("模型响应缺少choices[0].message.content") from error
    if not isinstance(content, str) or not content.strip():
        raise ModelRequestError("模型返回了空内容")
    if finish_reason != "stop":
        labels = {"length": "输出被长度限制截断", "content_filter": "内容被过滤", "insufficient_system_resource": "模型资源不足"}
        raise ModelRequestError(labels.get(finish_reason, f"模型未正常结束：{finish_reason}"))
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return content.strip(), usage, finish_reason


def main() -> None:
    parser = argparse.ArgumentParser(description="启动研途编辑本地网页")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    host = "127.0.0.1"
    port = args.port
    server = ThreadingHTTPServer((host, port), YantuHandler)
    print(f"研途编辑已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

