from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List

from flask import Flask, jsonify, request, send_file

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store
from resophy.tools.agent_tools.bilingual_translate import (
    BilingualDependencies,
    bilingual_translate_task,
    find_mineru_markdown,
)

CategoryPath = List[str]


def register_bilingual_routes(
    app: Flask,
    *,
    bilingual_tasks: Dict[str, Dict[str, Any]],
    bilingual_tasks_lock: threading.Lock,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    save_paper_metadata: Callable[[str, Any], None],
    agentic_settings_file: str,
) -> None:

    def _find_paper(paper_id: str):
        entry = paper_store.get_entry(paper_id)
        if entry:
            return entry.paper
        categories = get_categories()

        def search(node):
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(node["id"], category_path)
                for paper in papers:
                    if paper.id == paper_id:
                        return paper
            if "children" in node:
                for child in node["children"]:
                    result = search(child)
                    if result:
                        return result
            return None

        for child in categories.get("children", []):
            result = search(child)
            if result:
                return result
        return None

    @app.route("/api/paper/bilingual-translate", methods=["POST"])
    def api_bilingual_translate():
        try:
            data = request.json or {}
            paper_id = data.get("paper_id")
            if not paper_id:
                return jsonify({"success": False, "error": "paper_id is required"}), 400

            # Read LLM config from agentic settings
            with open(agentic_settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)

            openai_base_url = settings.get("llmBaseUrl", "").strip()
            openai_api_key = settings.get("llmApiKey", "").strip()
            llm_model = settings.get("llmModel", "").strip()

            if not openai_base_url or not openai_api_key or not llm_model:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "LLM is not configured. Please configure it in Settings → Agentic.",
                        }
                    ),
                    400,
                )

            # Check for running task
            with bilingual_tasks_lock:
                for tid, tinfo in bilingual_tasks.items():
                    if tinfo["paper_id"] == paper_id and tinfo["status"] == "running":
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "A bilingual translation task is already running for this paper",
                                    "task_id": tid,
                                }
                            ),
                            400,
                        )

            # Find paper
            paper = _find_paper(paper_id)
            if not paper:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            pdf_path = paper.file_path
            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({"success": False, "error": "PDF file not found"}), 404

            # Check if MinerU markdown exists
            md_file = find_mineru_markdown(pdf_path)
            if not md_file:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "MinerU markdown not found. Please run AI analysis first to parse the PDF into Markdown.",
                        }
                    ),
                    400,
                )

            # Read AI language from user settings
            ai_language = "zh"
            try:
                user_settings_file = os.path.join(
                    os.path.dirname(agentic_settings_file), "user_settings.json"
                )
                with open(user_settings_file, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                ai_language = user_settings.get("aiLanguage", "zh")
            except Exception:
                pass

            task_id = str(uuid.uuid4())

            with bilingual_tasks_lock:
                bilingual_tasks[task_id] = {
                    "paper_id": paper_id,
                    "status": "queued",
                    "logs": [],
                    "log_lock": threading.Lock(),
                    "progress": {"current": 0, "total": 0},
                    "start_time": datetime.now().isoformat(),
                    "result": None,
                }

            deps = BilingualDependencies(
                bilingual_tasks=bilingual_tasks,
                bilingual_tasks_lock=bilingual_tasks_lock,
                get_categories=get_categories,
                get_category_path=get_category_path,
                get_papers_in_category=get_papers_in_category,
                save_paper_metadata=save_paper_metadata,
            )

            thread = threading.Thread(
                target=bilingual_translate_task,
                args=(
                    task_id,
                    paper_id,
                    pdf_path,
                    openai_base_url,
                    openai_api_key,
                    llm_model,
                    ai_language,
                    deps,
                ),
            )
            thread.daemon = True
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": "Bilingual translation task started",
                    "task_id": task_id,
                }
            )

        except Exception as exc:
            print(f"Failed to start bilingual translation: {exc}")
            import traceback

            traceback.print_exc()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Failed to start bilingual translation: {str(exc)}",
                    }
                ),
                500,
            )

    @app.route("/api/paper/bilingual-translate/active", methods=["GET"])
    def api_get_active_bilingual():
        with bilingual_tasks_lock:
            active = []
            for tid, tinfo in bilingual_tasks.items():
                if tinfo["status"] in ["queued", "running"]:
                    active.append(
                        {
                            "task_id": tid,
                            "paper_id": tinfo["paper_id"],
                            "status": tinfo["status"],
                            "progress": tinfo.get("progress", {}),
                            "start_time": tinfo["start_time"],
                        }
                    )
            return jsonify({"success": True, "tasks": active})

    @app.route("/api/paper/bilingual-translate/<task_id>/logs", methods=["GET"])
    def api_get_bilingual_logs(task_id):
        with bilingual_tasks_lock:
            if task_id not in bilingual_tasks:
                return jsonify({"success": False, "error": "Task not found"}), 404
            tinfo = bilingual_tasks[task_id]
            with tinfo["log_lock"]:
                logs = tinfo["logs"].copy()
            return jsonify(
                {
                    "success": True,
                    "status": tinfo["status"],
                    "progress": tinfo.get("progress", {}),
                    "logs": logs,
                    "start_time": tinfo["start_time"],
                    "result": tinfo.get("result"),
                }
            )

    @app.route("/api/paper/bilingual-translate/<task_id>/cancel", methods=["POST"])
    def api_cancel_bilingual(task_id):
        with bilingual_tasks_lock:
            if task_id not in bilingual_tasks:
                return jsonify({"success": False, "error": "Task not found"}), 404
            tinfo = bilingual_tasks[task_id]
            if tinfo["status"] in ["completed", "failed", "cancelled"]:
                return jsonify({"success": False, "error": "Task already ended"}), 400
            tinfo["status"] = "cancelled"
            tinfo["result"] = {"success": False, "error": "Cancelled by user"}
            return jsonify({"success": True, "message": "Task cancelled"})

    @app.route("/api/paper/<paper_id>/bilingual/result", methods=["GET"])
    def api_get_bilingual_result(paper_id):
        paper = _find_paper(paper_id)
        if not paper:
            return jsonify({"error": "Paper not found"}), 404

        bilingual_path = paper.bilingual_version_path
        if not bilingual_path or not os.path.exists(bilingual_path):
            # Try to find bilingual.json from standard path
            pdf_path = paper.file_path
            if pdf_path and os.path.exists(pdf_path):
                md_file = find_mineru_markdown(pdf_path)
                if md_file:
                    vlm_dir = os.path.dirname(md_file)
                    candidate = os.path.join(vlm_dir, "bilingual.json")
                    if os.path.exists(candidate):
                        bilingual_path = candidate

        if not bilingual_path or not os.path.exists(bilingual_path):
            return jsonify({"error": "Bilingual translation not available"}), 404

        try:
            with open(bilingual_path, "r", encoding="utf-8") as f:
                content = f.read()
            return jsonify({"success": True, "content": content, "file_path": bilingual_path})
        except Exception as exc:
            return jsonify({"error": f"Failed to read bilingual file: {str(exc)}"}), 500

    @app.route("/api/paper/<paper_id>/bilingual/image", methods=["GET"])
    def api_get_bilingual_image(paper_id):
        paper = _find_paper(paper_id)
        if not paper:
            return jsonify({"error": "Paper not found"}), 404

        image_path = request.args.get("path")
        if not image_path:
            return jsonify({"error": "Image path not provided"}), 400

        pdf_path = paper.file_path
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDF file not found"}), 404

        md_file = find_mineru_markdown(pdf_path)
        if not md_file:
            return jsonify({"error": "MinerU output not found"}), 404

        vlm_dir = os.path.dirname(md_file)

        if image_path.startswith("images/"):
            potential_image = os.path.join(vlm_dir, image_path)
        else:
            potential_image = os.path.join(vlm_dir, "images", image_path)

        if os.path.exists(potential_image) and os.path.isfile(potential_image):
            return send_file(potential_image, mimetype="image/jpeg")

        return jsonify({"error": "Image file not found"}), 404
