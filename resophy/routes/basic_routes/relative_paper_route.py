"""
Related paper search route module

Provides API endpoints for searching related papers:
- Start search task
- Query progress
- Cancel task
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, jsonify, request

from resophy.tools.basic_tools.relative_paper_searcher import (
    cancel_search,
    cleanup_task,
    get_search_progress,
    start_search,
)


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class SaveCategoriesFn(Protocol):
    def __call__(self, categories: Dict[str, Any]) -> None: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


class CreateCategoryFolderFn(Protocol):
    def __call__(self, category_path: List[str]) -> str: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Any) -> None: ...


def _find_category_by_name(categories: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Search category tree for a node with the given name."""
    for child in categories.get("children", []):
        if child.get("name") == name:
            return child
        result = _find_category_by_name(child, name)
        if result:
            return result
    return None


def register_relative_paper_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    save_categories: SaveCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    agentic_settings_file: str,
    upload_folder: str,
    paper_store: Any,
) -> None:

    def _get_llm_config() -> Dict[str, str]:
        try:
            with open(agentic_settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _is_llm_configured() -> bool:
        cfg = _get_llm_config()
        return bool(cfg.get("llmBaseUrl") and cfg.get("llmApiKey") and cfg.get("llmModel"))

    @app.route("/api/relative-paper/start", methods=["POST"])
    def api_relative_paper_start():
        """Start a related paper search task."""
        try:
            if not _is_llm_configured():
                return jsonify({
                    "success": False,
                    "error": "Please configure LLM API in settings first (Model, Base URL, API Key)",
                }), 400

            data = request.json or {}
            paper_id = data.get("paper_id")
            target_count = data.get("target_count", 50)
            sources = data.get("sources", ["baseline", "related_work", "recommendation"])

            if not paper_id:
                return jsonify({"success": False, "error": "paper_id is required"}), 400

            # Get reference paper data
            entry = paper_store.get_entry(paper_id)
            if not entry:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            ref_paper = entry.paper
            ref_paper_data = ref_paper.to_dict()

            # Build category name: "relative paper of {title}"
            safe_title = ref_paper.title[:80].strip() if ref_paper.title else paper_id[:20]
            for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                safe_title = safe_title.replace(ch, '')
            category_name = f"relative paper of {safe_title}"

            # Find or create the category
            categories = get_categories()
            existing = _find_category_by_name(categories, category_name)

            if existing:
                category_id = existing["id"]
                category_path = get_category_path(categories, category_id)
            else:
                # Create new category at root level
                category_id = str(uuid.uuid4())
                new_node = {
                    "id": category_id,
                    "name": category_name,
                    "children": [],
                }
                if "children" not in categories:
                    categories["children"] = []
                categories["children"].append(new_node)
                save_categories(categories)
                category_path = ["Root", category_name]

            if not category_path:
                category_path = ["Root", category_name]

            # Create the folder on disk
            target_dir = create_category_folder(category_path[1:])

            # Get LLM config
            llm_config = _get_llm_config()

            # Create task
            task_id = f"relpaper_{int(time.time() * 1000)}"

            # Validate sources
            valid_sources = ["baseline", "citation", "recommendation", "keyword", "related_work"]
            sources = [s for s in sources if s in valid_sources]
            if not sources:
                sources = valid_sources

            start_search(
                task_id=task_id,
                ref_paper_id=paper_id,
                ref_paper_data=ref_paper_data,
                target_dir=target_dir,
                target_count=target_count,
                sources=sources,
                llm_base_url=llm_config["llmBaseUrl"],
                llm_api_key=llm_config["llmApiKey"],
                llm_model=llm_config["llmModel"],
                save_paper_metadata_fn=save_paper_metadata,
                paper_store=paper_store,
                category_id=category_id,
                category_path=category_path,
            )

            return jsonify({
                "success": True,
                "task_id": task_id,
                "category_id": category_id,
                "category_name": category_name,
                "paper_title": ref_paper.title or "",
                "message": f"Started searching related papers for: {ref_paper.title[:50] if ref_paper.title else paper_id}",
            })

        except Exception as exc:
            print(f"[RelativePaper] Start search failed: {exc}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/relative-paper/progress/<task_id>", methods=["GET"])
    def api_relative_paper_progress(task_id: str):
        """Get progress of a related paper search task."""
        result = get_search_progress(task_id)
        if result is None:
            return jsonify({"success": False, "error": "Task not found"}), 404
        return jsonify({"success": True, "progress": result})

    @app.route("/api/relative-paper/cancel/<task_id>", methods=["POST"])
    def api_relative_paper_cancel(task_id: str):
        """Cancel a running search task."""
        success = cancel_search(task_id)
        if success:
            return jsonify({"success": True, "message": "Task cancelled"})
        return jsonify({"success": False, "error": "Task not found"}), 404

    @app.route("/api/relative-paper/cleanup/<task_id>", methods=["POST"])
    def api_relative_paper_cleanup(task_id: str):
        """Clean up a completed task from memory."""
        cleanup_task(task_id)
        return jsonify({"success": True})

    @app.route("/api/paper/title/<paper_id>", methods=["GET"])
    def api_paper_title(paper_id: str):
        """Get the title of a paper by its ID."""
        try:
            entry = paper_store.get_entry(paper_id)
            if not entry:
                return jsonify({"success": False, "error": "Paper not found"}), 404
            title = entry.paper.title or ""
            return jsonify({"success": True, "title": title})
        except Exception as exc:
            print(f"[PaperTitle] Lookup failed: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500
