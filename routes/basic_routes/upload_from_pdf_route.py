from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Protocol

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from basic_tools.arxiv_client import search_arxiv_by_title_enhanced
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


class ExtractPdfMetadataFn(Protocol):
    def __call__(self, file_path: str) -> Dict[str, Optional[str]]: ...


class SearchArxivByTitleFn(Protocol):
    def __call__(
        self, title: str, max_results: int = 5
    ) -> Optional[list[Dict[str, Any]]]: ...


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
    search_arxiv_by_title: SearchArxivByTitleFn,
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

    def _process_pdf_metadata_background(
        paper_id: str,
        file_path: str,
        original_filename: str,
        category_id: str,
        category_path: list[str],
        category_folder: str,
    ):
        """后台处理：提取元数据、arXiv 搜索、重命名文件"""
        try:
            print(f"[后台] 开始处理PDF元数据: {file_path}")

            # 步骤1: 提取 PDF 元数据（获取标题）
            metadata = extract_pdf_metadata(file_path)

            # 步骤2: 通过标题搜索 arXiv
            arxiv_id = None
            arxiv_published_date = None

            if metadata.get("title"):
                print(f"[后台] 通过标题搜索 arXiv: {metadata['title'][:50]}...")
                search_results = search_arxiv_by_title_enhanced(
                    metadata["title"], max_results=1
                )

                if search_results and len(search_results) > 0:
                    best_match = search_results[0]
                    print(f"[后台] 找到匹配论文: {best_match.get('title')[:50]}...")

                    # 使用 arXiv 完整数据更新
                    metadata.update(
                        {
                            "title": best_match.get("title", metadata.get("title")),
                            "authors": best_match.get(
                                "authors", metadata.get("authors", "")
                            ),
                            "abstract": best_match.get(
                                "abstract", metadata.get("abstract", "")
                            ),
                            "summary": best_match.get("summary", ""),
                            "year": best_match.get("year", metadata.get("year", "")),
                            "bibtex": best_match.get("bibtex", ""),
                        }
                    )
                    arxiv_id = best_match.get("arxiv_id", "")
                    arxiv_published_date = best_match.get("published_date")
                else:
                    print("[后台] 未在 arXiv 找到匹配，使用 PDF 提取信息")
            else:
                print("[后台] 无法提取标题，跳过 arXiv 搜索")

            # 步骤3: 根据标题重命名文件
            current_filename = os.path.basename(file_path)
            new_filename = current_filename
            new_file_path = file_path

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
                        print(f"[后台] 文件已重命名为: {new_filename}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[后台] 重命名文件失败: {exc}")
                        new_file_path = file_path
                        new_filename = current_filename

            # 步骤4: 更新 Paper 对象
            paper = paper_store.get(paper_id)
            if paper:
                paper.filename = new_filename
                paper.file_path = new_file_path
                paper.title = metadata.get("title") or paper.title
                paper.authors = metadata.get("authors", "")
                paper.arxiv_id = arxiv_id
                paper.arxiv_published_date = arxiv_published_date
                paper.affiliation = metadata.get("affiliation", "")
                paper.year = metadata.get("year", "")
                paper.abstract = metadata.get("abstract", "")
                paper.summary = metadata.get("summary", "")
                paper.bibtex = metadata.get("bibtex", "")
                paper.keywords = metadata.get("keywords", "")
                paper.subject = metadata.get("subject", "")

                # 保存更新后的 paper
                paper_store.upsert(
                    paper, category_id=category_id, category_path=category_path
                )
                save_paper_metadata(new_file_path, paper)
                print(f"[后台] 论文元数据处理完成: {new_filename}")
            else:
                print(f"[后台] 警告: 找不到 paper {paper_id}")

        except Exception as exc:  # noqa: BLE001
            print(f"[后台] 处理PDF元数据失败: {exc}")
            import traceback

            traceback.print_exc()

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

        # 处理文件名冲突
        counter = 1
        original_filename = filename
        while os.path.exists(file_path):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            file_path = os.path.join(category_folder, filename)
            counter += 1

        # 立即保存文件
        file.save(file_path)
        print(f"文件已保存: {file_path}")

        # 创建占位符 Paper 对象（使用原始文件名）
        paper_id = str(uuid.uuid4())
        paper_info = {
            "id": paper_id,
            "filename": filename,
            "original_filename": file.filename,
            "file_path": file_path,
            "upload_date": datetime.now().isoformat(),
            "title": os.path.splitext(file.filename)[0],  # 临时使用文件名作为标题
            "authors": "",
            "arxiv_id": None,
            "arxiv_published_date": None,
            "affiliation": "",
            "year": "",
            "journal": "",
            "abstract": "",
            "summary": "",
            "bibtex": "",
            "keywords": "",
            "subject": "",
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

        # 立即注册 paper（让用户看到）
        registered_paper = paper_store.upsert(
            paper, category_id=category_id, category_path=category_path
        )
        save_paper_metadata(file_path, registered_paper)
        _add_to_reading_list(registered_paper.id)

        # 启动后台线程处理元数据
        thread = threading.Thread(
            target=_process_pdf_metadata_background,
            args=(
                paper_id,
                file_path,
                file.filename,
                category_id,
                category_path,
                category_folder,
            ),
            daemon=True,
        )
        thread.start()

        print(f"[立即返回] 论文已添加，后台处理中: {filename}")
        return jsonify({"success": True, "paper": registered_paper.to_dict()})
