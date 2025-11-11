from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Protocol

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from core.base_paper import Paper


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


class CreateCategoryFolderFn(Protocol):
    def __call__(self, category_path: list[str]) -> str: ...


class ExtractPdfMetadataFn(Protocol):
    def __call__(self, file_path: str) -> Dict[str, Optional[str]]: ...


class FetchArxivAbstractFn(Protocol):
    def __call__(self, arxiv_id: str) -> Optional[Dict[str, Any]]: ...


def _clean_filename(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 100:
        cleaned = cleaned[:100] + "..."
    return cleaned or None


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


def register_upload_from_pdf_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    extract_pdf_metadata: ExtractPdfMetadataFn,
    fetch_arxiv_abstract: FetchArxivAbstractFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
) -> None:
    def _load_reading_list() -> list[str]:
        try:
            with open(reading_list_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("papers", [])
        except Exception as exc:  # noqa: BLE001
            print(f"读取待读列表失败: {exc}")
            return []

    def _save_reading_list(paper_ids: list[str]) -> None:
        try:
            with open(reading_list_file, "w", encoding="utf-8") as f:
                json.dump({"papers": paper_ids}, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            print(f"保存待读列表失败: {exc}")

    def _add_to_reading_list(paper_id: str) -> None:
        paper_ids = _load_reading_list()
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
            _save_reading_list(paper_ids)

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"})

        file = request.files["file"]
        category_id = request.form.get("category_id")

        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"})

        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"success": False, "error": "Only PDF files are allowed"})

        categories = get_categories()
        category_path = get_category_path(categories, category_id)

        if not category_path:
            return jsonify({"success": False, "error": "Category not found"})

        category_folder = create_category_folder(category_path[1:])  # 跳过 Root
        filename = secure_filename(file.filename)
        file_path = os.path.join(category_folder, filename)

        counter = 1
        original_filename = filename
        while os.path.exists(file_path):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            file_path = os.path.join(category_folder, filename)
            counter += 1

        file.save(file_path)

        print(f"正在提取PDF元数据: {file_path}")
        metadata: Dict[str, Any] = {}
        client_metadata_raw = request.form.get("metadata")
        if client_metadata_raw:
            try:
                metadata = json.loads(client_metadata_raw)
            except Exception as exc:  # noqa: BLE001
                print(f"解析前端metadata失败，将回退服务端提取: {exc}")
                metadata = {}

        server_md = extract_pdf_metadata(file_path)
        for key, value in server_md.items():
            if key == "abstract":
                continue
            if not metadata.get(key):
                metadata[key] = value

        arxiv_id = (metadata.get("arxiv_id") or "").strip()
        arxiv_published_date = None
        if arxiv_id:
            arxiv_info = fetch_arxiv_abstract(arxiv_id)
            if arxiv_info:
                if "abstract" in arxiv_info:
                    metadata["abstract"] = arxiv_info["abstract"]
                if "published_date" in arxiv_info:
                    arxiv_published_date = arxiv_info["published_date"]
            else:
                metadata["abstract"] = metadata.get("abstract") or ""

        new_filename = filename
        if metadata.get("title"):
            clean_title = _clean_filename(metadata["title"])
            if clean_title:
                new_filename = f"{clean_title}.pdf"
                new_file_path = os.path.join(category_folder, new_filename)

                counter = 1
                original_new_filename = new_filename
                while os.path.exists(new_file_path):
                    name, ext = os.path.splitext(original_new_filename)
                    new_filename = f"{name}_{counter}{ext}"
                    new_file_path = os.path.join(category_folder, new_filename)
                    counter += 1

                try:
                    os.rename(file_path, new_file_path)
                    file_path = new_file_path
                    filename = new_filename
                    print(f"文件已重命名为: {filename}")
                except Exception as exc:  # noqa: BLE001
                    print(f"重命名文件失败: {exc}")

        paper_info = {
            "id": str(uuid.uuid4()),
            "filename": filename,
            "original_filename": file.filename,
            "file_path": file_path,
            "upload_date": datetime.now().isoformat(),
            "title": metadata.get("title") or os.path.splitext(file.filename)[0],
            "authors": metadata.get("authors") or "",
            "arxiv_id": arxiv_id,
            "arxiv_published_date": arxiv_published_date,
            "affiliation": metadata.get("affiliation") or "",
            "year": metadata.get("year") or "",
            "journal": "",
            "abstract": metadata.get("abstract") or "",
            "keywords": metadata.get("keywords") or "",
            "subject": metadata.get("subject") or "",
            "notes": "",
            "starred": False,
            "read_time": 0,
            "analysis_view_time": 0,
            "translation_time": 0,
            "analysis_time": 0,
        }

        paper = Paper.from_dict(paper_info)
        if not paper:
            return jsonify({"success": False, "error": "创建论文对象失败"}), 500

        save_paper_metadata(file_path, paper)
        _add_to_reading_list(paper.id)
        return jsonify({"success": True, "paper": paper.to_dict()})
