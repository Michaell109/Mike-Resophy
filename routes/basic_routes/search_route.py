from __future__ import annotations

import json
import os
from typing import Dict, Optional, Protocol

from flask import Flask, jsonify, request


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


def register_search_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    upload_folder: str,
) -> None:
    @app.route("/api/search")
    def api_search():
        """搜索 title/authors/abstract。支持全局或限定某个分类."""
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"results": []})
        query_lower = query.lower()

        base_search_dir = upload_folder
        category_id = (request.args.get("category_id") or "").strip()
        if category_id:
            categories = get_categories()
            path = get_category_path(categories, category_id)
            if path and len(path) > 1:
                base_search_dir = os.path.join(upload_folder, *path[1:])

        results = []
        for root, dirs, files in os.walk(base_search_dir):
            for fname in files:
                if not fname.lower().endswith(".json"):
                    continue
                json_path = os.path.join(root, fname)
                try:
                    with open(json_path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                except Exception:
                    continue

                pid = data.get("id")
                title = data.get("title") or data.get("filename") or ""
                authors = data.get("authors") or ""
                abstract = data.get("abstract") or ""

                matched_fields = []
                if query_lower in title.lower():
                    matched_fields.append("title")
                if query_lower in authors.lower():
                    matched_fields.append("authors")
                if query_lower in abstract.lower():
                    matched_fields.append("abstract")

                if matched_fields:
                    results.append(
                        {
                            "id": pid,
                            "title": title,
                            "authors": authors,
                            "abstract": abstract,
                            "filename": data.get("filename"),
                            "matched_fields": matched_fields,
                        }
                    )

        results.sort(key=lambda r: (-len(r["matched_fields"]), r.get("title") or ""))
        return jsonify({"results": results})
