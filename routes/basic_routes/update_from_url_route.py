from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

import requests
from flask import Flask, jsonify, request

from basic_tools.upload_paper import fetch_paper_by_arxiv_id
from core.base_paper import Paper
from core.paper_store import PaperStore


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


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """从 URL 中提取 arXiv ID"""
    patterns = [
        r"arxiv\.org/pdf/([\d.]+(?:v\d+)?)",
        r"arxiv\.org/abs/([\d.]+(?:v\d+)?)",
        r"^([\d.]+(?:v\d+)?)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            if "v" in arxiv_id:
                arxiv_id = arxiv_id.split("v")[0]
            return arxiv_id
    return None


def _download_arxiv_pdf(arxiv_id: str) -> Optional[tuple[bytes, str]]:
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    try:
        print(f"正在从 arXiv 下载 PDF: {pdf_url}")
        response = requests.get(pdf_url, timeout=30, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower():
            print(f"警告: Content-Type 不是 PDF: {content_type}")
        pdf_content = response.content
        filename = f"{arxiv_id}.pdf"
        print(f"成功下载 PDF, 大小: {len(pdf_content)} bytes")
        return pdf_content, filename
    except requests.exceptions.RequestException as exc:
        print(f"下载 arXiv PDF 失败: {exc}")
        return None


def _clean_filename(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 100:
        cleaned = cleaned[:100] + "..."
    return cleaned or None


def register_update_from_url_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
    paper_store: PaperStore,
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

    @app.route("/api/upload/arxiv", methods=["POST"])
    def api_upload_arxiv():
        """从 arXiv URL 下载并导入 PDF"""
        try:
            data = request.json or {}
            arxiv_url = data.get("arxiv_url", "").strip()
            category_id = data.get("category_id")

            if not arxiv_url:
                return jsonify({"success": False, "error": "未提供 arXiv URL"}), 400

            if not category_id:
                return jsonify({"success": False, "error": "未选择分类"}), 400

            arxiv_id = _extract_arxiv_id_from_url(arxiv_url)
            if not arxiv_id:
                return (
                    jsonify({"success": False, "error": "无法从 URL 中提取 arXiv ID"}),
                    400,
                )

            print(f"提取的 arXiv ID: {arxiv_id}")

            result = _download_arxiv_pdf(arxiv_id)
            if not result:
                return jsonify({"success": False, "error": "下载 PDF 失败"}), 500

            pdf_content, filename = result

            categories = get_categories()
            category_path = get_category_path(categories, category_id)

            if not category_path:
                return jsonify({"success": False, "error": "分类未找到"}), 404

            category_folder = create_category_folder(category_path[1:])
            file_path = os.path.join(category_folder, filename)

            counter = 1
            original_filename = filename
            while os.path.exists(file_path):
                name, ext = os.path.splitext(original_filename)
                filename = f"{name}_{counter}{ext}"
                file_path = os.path.join(category_folder, filename)
                counter += 1

            with open(file_path, "wb") as f:
                f.write(pdf_content)

            print(f"PDF 已保存到: {file_path}")

            # 使用新的统一接口获取论文信息
            paper_info = fetch_paper_by_arxiv_id(arxiv_id)

            if not paper_info:
                print(f"警告: 无法从 arXiv API 获取信息")
                paper_info = {"arxiv_id": arxiv_id}
            else:
                print(f"成功从 arXiv API 获取论文信息: {paper_info.get('title')}")

            # 统一使用 paper_info 作为 metadata
            metadata = paper_info

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
                "original_filename": filename,
                "file_path": file_path,
                "upload_date": datetime.now().isoformat(),
                "title": metadata.get("title", arxiv_id),
                "authors": metadata.get("authors", ""),
                "arxiv_id": arxiv_id,
                "arxiv_published_date": metadata.get("arxiv_published_date"),
                "affiliation": metadata.get("affiliation", ""),
                "year": metadata.get("year", ""),
                "journal": "",
                "abstract": metadata.get("abstract", ""),
                "summary": metadata.get("summary", ""),  # 新增
                "bibtex": metadata.get("bibtex", ""),  # 新增
                "keywords": metadata.get("keywords", ""),
                "subject": metadata.get("subject", ""),
                "notes": "",  # 用户备注
                "starred": False,
                "read_time": 0,
                "translation_time": 0,
                "analysis_time": 0,
            }

            paper = Paper.from_dict(paper_info)
            if not paper:
                return jsonify({"success": False, "error": "创建论文对象失败"}), 500

            registered_paper = paper_store.upsert(
                paper, category_id=category_id, category_path=category_path
            )
            save_paper_metadata(file_path, registered_paper)
            _add_to_reading_list(registered_paper.id)

            return jsonify({"success": True, "paper": registered_paper.to_dict()})

        except Exception as exc:  # noqa: BLE001
            print(f"从 arXiv 导入失败: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": f"导入失败: {str(exc)}"}), 500
