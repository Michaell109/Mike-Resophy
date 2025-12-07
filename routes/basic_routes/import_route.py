"""
Zotero RDF 导入路由
处理从 Zotero 导入论文的功能
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

import requests
from flask import Flask, Response, jsonify, request
from werkzeug.utils import secure_filename

from basic_tools.upload_paper import (
    fetch_bibtex_from_dblp,
    fetch_paper_by_arxiv_id_fast,
    search_arxiv_by_title_and_author_fast,
)
from core.base_paper import Paper
from core.paper_store import PaperStore


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
    def __call__(self, category_path: list[str]) -> str: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


# 导入任务状态存储（支持断线重连）
import_tasks: Dict[str, Dict[str, Any]] = {}
import_tasks_lock = threading.Lock()

# 当前活跃的导入任务ID（全局只允许一个导入任务）
current_import_task_id: Optional[str] = None


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
    """下载 arXiv PDF（优先使用 export.arxiv.org）"""
    # 优先尝试 export.arxiv.org
    pdf_urls = [
        f"https://export.arxiv.org/pdf/{arxiv_id}.pdf",
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    ]
    
    for pdf_url in pdf_urls:
        try:
            print(f"[Import] 正在从 arXiv 下载 PDF: {pdf_url}")
            response = requests.get(pdf_url, timeout=60, stream=True)
            response.raise_for_status()
            pdf_content = response.content
            filename = f"{arxiv_id}.pdf"
            print(f"[Import] 成功下载 PDF, 大小: {len(pdf_content)} bytes")
            return pdf_content, filename
        except requests.exceptions.RequestException as exc:
            print(f"[Import] 从 {pdf_url} 下载失败: {exc}")
            continue
    
    print(f"[Import] 所有 URL 都下载失败")
    return None


def _clean_filename(text: Optional[str]) -> Optional[str]:
    """清理文件名"""
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 100:
        cleaned = cleaned[:100] + "..."
    return cleaned or None


def _parse_category_path(category_str: str) -> List[str]:
    """
    解析 category 字符串为路径列表

    例如:
    - "Scene Text Recognition" -> ["Scene Text Recognition"]
    - "Multi Modality/LLaVA" -> ["Multi Modality", "LLaVA"]
    - "A; B/C" -> 只取第一个最长的路径 ["B", "C"]
    """
    if not category_str:
        return []

    # 如果有分号，取第一个（最长的路径）
    parts = category_str.split(";")
    if parts:
        category_str = parts[0].strip()

    # 按 / 分割
    path_parts = [p.strip() for p in category_str.split("/") if p.strip()]
    return path_parts


def _find_or_create_category(
    categories: Dict[str, Any],
    category_path: List[str],
    save_categories: SaveCategoriesFn,
    create_category_folder: CreateCategoryFolderFn,
) -> Optional[str]:
    """
    查找或创建分类，返回分类 ID

    Args:
        categories: 分类树数据
        category_path: 分类路径，如 ["Multi Modality", "LLaVA"]
        save_categories: 保存分类的函数
        create_category_folder: 创建分类文件夹的函数

    Returns:
        分类 ID，失败返回 None
    """
    if not category_path:
        return None

    def find_or_create_in_children(
        children: List[Dict], path: List[str], current_path: List[str]
    ) -> Optional[str]:
        if not path:
            return None

        target_name = path[0]
        remaining_path = path[1:]

        # 查找现有分类
        for child in children:
            if child.get("name") == target_name:
                if remaining_path:
                    # 继续查找子分类
                    if "children" not in child:
                        child["children"] = []
                    return find_or_create_in_children(
                        child["children"], remaining_path, current_path + [target_name]
                    )
                else:
                    # 找到了目标分类
                    return child.get("id")

        # 没找到，创建新分类
        new_id = str(uuid.uuid4())
        new_category = {"id": new_id, "name": target_name, "children": []}
        children.append(new_category)

        # 创建文件夹
        full_path = current_path + [target_name]
        try:
            create_category_folder(full_path)
            print(f"[Import] 创建分类文件夹: {'/'.join(full_path)}")
        except Exception as e:
            print(f"[Import] 创建分类文件夹失败: {e}")

        if remaining_path:
            # 继续创建子分类
            return find_or_create_in_children(
                new_category["children"], remaining_path, full_path
            )
        else:
            return new_id

    # 从根节点开始查找
    root_children = categories.get("children", [])
    result = find_or_create_in_children(root_children, category_path, [])

    # 保存更新后的分类
    if result:
        save_categories(categories)

    return result


def _find_or_create_category_under_parent(
    categories: Dict[str, Any],
    parent_category_id: str,
    category_path: List[str],
    save_categories: SaveCategoriesFn,
    create_category_folder: CreateCategoryFolderFn,
) -> Optional[str]:
    """
    在指定父目录下查找或创建分类，返回分类 ID

    例如：parent_category_id 对应 "Project A"，category_path 为 ["Multi Modality", "LLaVA"]
    则会创建 "Project A/Multi Modality/LLaVA"

    Args:
        categories: 分类树数据
        parent_category_id: 父目录ID
        category_path: 分类路径，如 ["Multi Modality", "LLaVA"]
        save_categories: 保存分类的函数
        create_category_folder: 创建分类文件夹的函数

    Returns:
        分类 ID，失败返回 None
    """
    if not category_path:
        # 如果没有 category_path，直接返回父目录ID
        return parent_category_id

    # 查找父目录节点
    def find_node_by_id(
        node: Dict[str, Any], target_id: str
    ) -> Optional[Dict[str, Any]]:
        if node.get("id") == target_id:
            return node
        for child in node.get("children", []):
            result = find_node_by_id(child, target_id)
            if result:
                return result
        return None

    parent_node = find_node_by_id(categories, parent_category_id)
    if not parent_node:
        # 父目录不存在，回退到根目录
        return _find_or_create_category(
            categories, category_path, save_categories, create_category_folder
        )

    # 获取父目录的路径（用于创建文件夹）
    def get_path_to_node(
        root: Dict[str, Any], target_id: str, path: List[str] = None
    ) -> Optional[List[str]]:
        if path is None:
            path = []
        if root.get("id") == target_id:
            return path + [root.get("name", "")]
        for child in root.get("children", []):
            result = get_path_to_node(child, target_id, path + [root.get("name", "")])
            if result:
                return result
        return None

    parent_path = get_path_to_node(categories, parent_category_id)
    if not parent_path:
        parent_path = []
    else:
        # 移除 "Root" 如果存在
        parent_path = [p for p in parent_path if p and p != "Root"]

    # 在父目录下查找或创建分类
    def find_or_create_in_children(
        children: List[Dict], path: List[str], current_folder_path: List[str]
    ) -> Optional[str]:
        if not path:
            return None

        target_name = path[0]
        remaining_path = path[1:]

        # 查找现有分类
        for child in children:
            if child.get("name") == target_name:
                if remaining_path:
                    # 继续查找子分类
                    if "children" not in child:
                        child["children"] = []
                    return find_or_create_in_children(
                        child["children"],
                        remaining_path,
                        current_folder_path + [target_name],
                    )
                else:
                    # 找到了目标分类
                    return child.get("id")

        # 没找到，创建新分类
        new_id = str(uuid.uuid4())
        new_category = {"id": new_id, "name": target_name, "children": []}
        children.append(new_category)

        # 创建文件夹
        full_folder_path = current_folder_path + [target_name]
        try:
            create_category_folder(full_folder_path)
            print(f"[Import] 创建分类文件夹: {'/'.join(full_folder_path)}")
        except Exception as e:
            print(f"[Import] 创建分类文件夹失败: {e}")

        if remaining_path:
            # 继续创建子分类
            return find_or_create_in_children(
                new_category["children"], remaining_path, full_folder_path
            )
        else:
            return new_id

    # 确保父目录有 children 列表
    if "children" not in parent_node:
        parent_node["children"] = []

    # 从父目录开始查找
    result = find_or_create_in_children(
        parent_node["children"], category_path, parent_path
    )

    # 保存更新后的分类
    if result:
        save_categories(categories)

    return result


def _get_full_category_path(
    categories: Dict[str, Any],
    category_id: str,
    path: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """获取分类的完整路径"""
    if path is None:
        path = ["Root"]

    if categories.get("id") == category_id:
        return path + [categories.get("name", "")]

    for child in categories.get("children", []):
        result = _get_full_category_path(
            child, category_id, path + [categories.get("name", "")]
        )
        if result:
            return result

    return None


def register_import_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    save_categories: SaveCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
    paper_store: PaperStore,
    upload_folder: str,
) -> None:
    """注册导入相关的路由"""

    def _load_reading_list() -> list[str]:
        try:
            with open(reading_list_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("papers", [])
        except Exception:
            return []

    def _save_reading_list(paper_ids: list[str]) -> None:
        try:
            with open(reading_list_file, "w", encoding="utf-8") as f:
                json.dump({"papers": paper_ids}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _add_to_reading_list(paper_id: str) -> None:
        paper_ids = _load_reading_list()
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
            _save_reading_list(paper_ids)

    def _check_duplicate_in_folder(folder_path: str, title: str) -> bool:
        """检查文件夹中是否已存在同名论文"""
        if not os.path.exists(folder_path):
            return False

        clean_title = _clean_filename(title)
        if not clean_title:
            return False

        # 检查是否有同名 PDF 或 JSON
        expected_pdf = f"{clean_title}.pdf"
        expected_json = f"{clean_title}.json"

        for filename in os.listdir(folder_path):
            if filename.lower() == expected_pdf.lower():
                return True
            # 也检查 JSON 文件中的标题
            if filename.endswith(".json"):
                try:
                    json_path = os.path.join(folder_path, filename)
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if (
                            data.get("title", "").strip().lower()
                            == title.strip().lower()
                        ):
                            return True
                except Exception:
                    pass
        return False

    def _update_task_progress(task_id: str, **kwargs):
        """更新任务进度（线程安全）"""
        with import_tasks_lock:
            task = import_tasks.get(task_id)
            if task:
                task.update(kwargs)
                task["last_update"] = datetime.now().isoformat()

    def _import_papers_task(
        task_id: str, papers_data: List[Dict[str, Any]], target_category_id: str = ""
    ):
        """后台导入任务

        Args:
            task_id: 任务ID
            papers_data: 论文数据列表
            target_category_id: 目标目录ID，如果指定则作为父目录，Zotero 分类结构将在其下创建
        """
        global current_import_task_id

        with import_tasks_lock:
            task = import_tasks.get(task_id)
            if not task:
                return

        total = len(papers_data)
        success_count = 0
        failed_count = 0
        skipped_count = 0
        duplicate_count = 0  # 重复数量
        others_count = 0  # 进入 Others 的数量

        # 如果指定了目标目录，预先获取其信息
        parent_category_id = None
        parent_category_path = None
        print(
            f"[Import] 接收到的目标目录ID: '{target_category_id}' (类型: {type(target_category_id).__name__})"
        )
        if target_category_id:
            categories = get_categories()
            print(f"[Import] 正在查找目标目录...")
            parent_category_path = get_category_path(categories, target_category_id)
            print(f"[Import] 查找结果: {parent_category_path}")
            if parent_category_path:
                parent_category_id = target_category_id
                print(
                    f"[Import] ✅ 将在目录 '{'/'.join(parent_category_path[1:])}' 下导入，保留 Zotero 分类结构"
                )
            else:
                print(
                    f"[Import] ❌ 目标目录不存在: {target_category_id}，将在根目录下按 Zotero 分类导入"
                )
        else:
            print("[Import] 未指定目标目录，将在根目录下按 Zotero 分类导入")

        for idx, paper_data in enumerate(papers_data):
            try:
                # 更新进度状态
                _update_task_progress(
                    task_id,
                    status="importing",
                    progress=int((idx / total) * 100),
                    current=idx + 1,
                    total=total,
                    message=f"正在处理: {paper_data.get('title', '未知标题')[:50]}...",
                    success_count=success_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    duplicate_count=duplicate_count,
                    others_count=others_count,
                )

                # 检查 category
                category_str = paper_data.get("extra", {}).get(
                    "category"
                ) or paper_data.get("category")

                # 解析 category 路径
                if category_str:
                    category_path = _parse_category_path(category_str)
                else:
                    category_path = []

                # 标记是否进入 Others
                is_others = False

                # 如果没有 category 或者 category 就是 "Others"，放到 Others 目录
                if not category_path or (
                    len(category_path) == 1 and category_path[0].lower() == "others"
                ):
                    category_path = ["Others"]
                    is_others = True
                    print(
                        f"[Import] 无分类论文，放入 Others: {paper_data.get('title', '未知')[:50]}"
                    )

                # 查找或创建分类
                # 如果指定了父目录，在父目录下创建分类结构
                categories = get_categories()
                if parent_category_id:
                    category_id = _find_or_create_category_under_parent(
                        categories,
                        parent_category_id,
                        category_path,
                        save_categories,
                        create_category_folder,
                    )
                else:
                    category_id = _find_or_create_category(
                        categories,
                        category_path,
                        save_categories,
                        create_category_folder,
                    )

                if not category_id:
                    print(f"[Import] 创建分类失败: {category_path}")
                    failed_count += 1
                    continue

                # 获取分类的完整路径（用于 paper_store）
                categories = get_categories()  # 重新获取更新后的分类
                full_category_path = get_category_path(categories, category_id)
                if not full_category_path:
                    full_category_path = ["Root"] + category_path

                # 尝试从 arXiv 获取论文
                arxiv_id = None
                paper_info = None

                # 1. 检查 URL 中是否有 arXiv
                url = paper_data.get("extra", {}).get("url") or paper_data.get(
                    "url", ""
                )
                if "arxiv.org" in url.lower():
                    arxiv_id = _extract_arxiv_id_from_url(url)
                    if arxiv_id:
                        print(f"[Import] 从 URL 提取 arXiv ID: {arxiv_id}")
                        paper_info = fetch_paper_by_arxiv_id_fast(arxiv_id)

                # 2. 如果没有 arXiv URL，用标题+作者搜索
                if not paper_info:
                    title = paper_data.get("title", "")
                    authors = paper_data.get("authors", "")
                    if title:
                        # 构造搜索查询
                        search_title = f"{title} {authors}" if authors else title
                        print(f"[Import] 使用标题搜索 arXiv: {search_title[:50]}...")

                        # 提取第一个作者
                        first_author = authors.split(",")[0].strip() if authors else ""
                        if first_author:
                            paper_info = search_arxiv_by_title_and_author_fast(
                                title, first_author
                            )

                        if paper_info:
                            arxiv_id = paper_info.get("arxiv_id")

                # 3. 如果还是找不到，跳过
                if not paper_info or not arxiv_id:
                    print(
                        f"[Import] 无法从 arXiv 获取论文: {paper_data.get('title', '未知')[:50]}"
                    )
                    skipped_count += 1
                    continue

                # 获取完整的文件夹路径（包含父目录）
                # full_category_path 格式为 ["Root", "ParentDir", "Category", ...]
                # 创建文件夹时需要去掉 "Root"
                folder_path_parts = full_category_path[1:] if len(full_category_path) > 1 else category_path
                
                # 检查目标目录是否已有同名论文（重复检测）
                category_folder = create_category_folder(folder_path_parts)
                paper_title = paper_info.get("title", "")
                if paper_title and _check_duplicate_in_folder(
                    category_folder, paper_title
                ):
                    print(f"[Import] 跳过重复论文: {paper_title[:50]}")
                    duplicate_count += 1
                    continue

                # 下载 PDF
                pdf_result = _download_arxiv_pdf(arxiv_id)
                if not pdf_result:
                    print(f"[Import] 下载 PDF 失败: {arxiv_id}")
                    failed_count += 1
                    continue

                pdf_content, pdf_filename = pdf_result

                # 创建分类文件夹并保存 PDF（使用完整路径）
                category_folder = create_category_folder(folder_path_parts)

                # 使用论文标题作为文件名
                clean_title = _clean_filename(paper_info.get("title"))
                if clean_title:
                    pdf_filename = f"{clean_title}.pdf"

                file_path = os.path.join(category_folder, pdf_filename)

                # 处理文件名冲突
                counter = 1
                original_filename = pdf_filename
                while os.path.exists(file_path):
                    name, ext = os.path.splitext(original_filename)
                    pdf_filename = f"{name}_{counter}{ext}"
                    file_path = os.path.join(category_folder, pdf_filename)
                    counter += 1

                # 保存 PDF
                with open(file_path, "wb") as f:
                    f.write(pdf_content)
                print(f"[Import] PDF 已保存: {file_path}")

                # 创建 Paper 对象
                paper_id = str(uuid.uuid4())
                new_paper = Paper(
                    id=paper_id,
                    filename=pdf_filename,
                    original_filename=pdf_filename,
                    file_path=file_path,
                    upload_date=datetime.now().isoformat(),
                    title=paper_info.get("title", ""),
                    authors=paper_info.get("authors", ""),
                    arxiv_id=arxiv_id,
                    arxiv_published_date=paper_info.get("published_date"),
                    year=paper_info.get("year", ""),
                    abstract=paper_info.get("abstract", ""),
                    summary=paper_info.get("summary", ""),
                    bibtex="",
                    notes=paper_data.get("notes", ""),
                    upload_source="zotero_import",
                )

                # 注册到 paper_store
                registered_paper = paper_store.upsert(
                    new_paper, category_id=category_id, category_path=full_category_path
                )

                # 保存元数据
                save_paper_metadata(file_path, registered_paper)

                # 注意：导入的论文不添加到待读列表

                success_count += 1
                if is_others:
                    others_count += 1
                print(f"[Import] ✅ 成功导入: {paper_info.get('title', '')[:50]}")

                # 后台获取 DBLP BibTeX（异步）
                if paper_info.get("title") and paper_info.get("authors"):
                    threading.Thread(
                        target=_fetch_dblp_bibtex_async,
                        args=(
                            paper_id,
                            paper_info["title"],
                            paper_info["authors"],
                            arxiv_id,
                            file_path,
                            category_id,
                            full_category_path,
                        ),
                        daemon=True,
                    ).start()

            except Exception as e:
                print(f"[Import] ❌ 导入论文失败: {e}")
                import traceback

                traceback.print_exc()
                failed_count += 1

        # 导入完成
        _update_task_progress(
            task_id,
            status="completed",
            progress=100,
            current=total,
            total=total,
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            duplicate_count=duplicate_count,
            others_count=others_count,
            message="导入完成",
        )

        # 清除当前任务标记
        global current_import_task_id
        current_import_task_id = None

        print(
            f"[Import] 导入完成: 成功 {success_count}, 失败 {failed_count}, 跳过 {skipped_count}, 重复 {duplicate_count}, Others {others_count}"
        )

    def _fetch_dblp_bibtex_async(
        paper_id: str,
        title: str,
        authors: str,
        arxiv_id: str,
        file_path: str,
        category_id: str,
        category_path: List[str],
    ):
        """异步获取 DBLP BibTeX"""
        try:
            bibtex = fetch_bibtex_from_dblp(title, authors, arxiv_id)
            if bibtex:
                paper = paper_store.get(paper_id)
                if paper:
                    paper.bibtex = bibtex
                    paper_store.upsert(
                        paper, category_id=category_id, category_path=category_path
                    )
                    save_paper_metadata(file_path, paper)
                    print(f"[Import DBLP] ✅ BibTeX 已更新: {paper_id}")
        except Exception as e:
            print(f"[Import DBLP] ❌ 获取 BibTeX 失败: {e}")

    @app.route("/api/import/zotero", methods=["POST"])
    def api_import_zotero():
        """上传并解析 Zotero RDF 文件"""
        if "file" not in request.files:
            return jsonify({"success": False, "error": "未提供文件"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "未选择文件"}), 400

        if not file.filename.lower().endswith(".rdf"):
            return jsonify({"success": False, "error": "请上传 .rdf 格式的文件"}), 400

        # 获取测试模式参数
        test_mode = request.form.get("test_mode", "false").lower() == "true"
        print(f"[Import] 测试模式: {test_mode}")

        # 获取目标目录参数（可选）
        target_category_id = request.form.get("target_category_id", "").strip()
        print(f"[Import] 目标目录ID: {target_category_id or '（按Zotero分类）'}")

        try:
            # 保存临时文件
            temp_dir = os.path.join(upload_folder, ".temp")
            os.makedirs(temp_dir, exist_ok=True)

            temp_filename = f"zotero_{uuid.uuid4().hex[:8]}.rdf"
            temp_path = os.path.join(temp_dir, temp_filename)
            file.save(temp_path)
            print(f"[Import] RDF 文件已保存: {temp_path}")

            # 解析 RDF 文件
            try:
                from basic_tools.zotero_parser import ZoteroRDFParser

                parser = ZoteroRDFParser(temp_path)
                papers = parser.parse()

                # 转换为字典列表
                papers_data = []
                for paper in papers:
                    paper_dict = paper.to_dict()
                    papers_data.append(paper_dict)

                print(f"[Import] 解析完成，找到 {len(papers_data)} 篇论文")

                # 测试模式：只取前20篇
                if test_mode and len(papers_data) > 20:
                    papers_data = papers_data[:20]
                    print(f"[Import] 测试模式：只导入前 20 篇论文")

            finally:
                # 清理临时文件
                try:
                    os.remove(temp_path)
                    fixed_path = temp_path.replace(".rdf", "_fixed.rdf")
                    if os.path.exists(fixed_path):
                        os.remove(fixed_path)
                except Exception:
                    pass

            if not papers_data:
                return jsonify({"success": False, "error": "未找到任何论文"}), 400

            # 检查是否已有正在进行的导入任务
            global current_import_task_id
            if current_import_task_id:
                with import_tasks_lock:
                    existing_task = import_tasks.get(current_import_task_id)
                    if existing_task and existing_task.get("status") not in [
                        "completed",
                        "error",
                    ]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "已有导入任务正在进行中",
                                    "task_id": current_import_task_id,
                                }
                            ),
                            400,
                        )

            # 创建导入任务
            task_id = str(uuid.uuid4())
            current_import_task_id = task_id

            with import_tasks_lock:
                import_tasks[task_id] = {
                    "status": "starting",
                    "progress": 0,
                    "current": 0,
                    "total": len(papers_data),
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "duplicate_count": 0,
                    "others_count": 0,
                    "message": "正在准备导入...",
                    "start_time": datetime.now().isoformat(),
                    "last_update": datetime.now().isoformat(),
                }

            # 启动后台导入任务（不使用 daemon=True，确保任务完成）
            thread = threading.Thread(
                target=_import_papers_task,
                args=(task_id, papers_data, target_category_id),
            )
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "task_id": task_id,
                    "total_papers": len(papers_data),
                    "message": f"开始导入 {len(papers_data)} 篇论文",
                }
            )

        except Exception as e:
            print(f"[Import] 解析 RDF 失败: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": f"解析失败: {str(e)}"}), 500

    @app.route("/api/import/zotero/status")
    def api_import_status():
        """获取当前导入任务状态（用于页面刷新后恢复）"""
        global current_import_task_id

        if not current_import_task_id:
            return jsonify({"has_task": False})

        with import_tasks_lock:
            task = import_tasks.get(current_import_task_id)
            if not task:
                current_import_task_id = None
                return jsonify({"has_task": False})

            return jsonify(
                {
                    "has_task": True,
                    "task_id": current_import_task_id,
                    "status": task.get("status"),
                    "progress": task.get("progress", 0),
                    "current": task.get("current", 0),
                    "total": task.get("total", 0),
                    "message": task.get("message", ""),
                    "success_count": task.get("success_count", 0),
                    "failed_count": task.get("failed_count", 0),
                    "skipped_count": task.get("skipped_count", 0),
                    "duplicate_count": task.get("duplicate_count", 0),
                    "others_count": task.get("others_count", 0),
                }
            )

    @app.route("/api/import/zotero/progress/<task_id>")
    def api_import_progress(task_id):
        """获取导入进度（SSE，从任务状态读取）"""

        def generate():
            last_status = None

            while True:
                with import_tasks_lock:
                    task = import_tasks.get(task_id)
                    if not task:
                        yield f"data: {json.dumps({'status': 'error', 'message': '任务不存在'})}\n\n"
                        return

                    # 构建进度数据
                    progress_data = {
                        "status": task.get("status"),
                        "progress": task.get("progress", 0),
                        "current": task.get("current", 0),
                        "total": task.get("total", 0),
                        "message": task.get("message", ""),
                        "success_count": task.get("success_count", 0),
                        "failed_count": task.get("failed_count", 0),
                        "skipped_count": task.get("skipped_count", 0),
                        "duplicate_count": task.get("duplicate_count", 0),
                        "others_count": task.get("others_count", 0),
                    }

                # 只有状态变化时才发送
                current_key = (
                    progress_data["status"],
                    progress_data["current"],
                    progress_data["message"],
                )
                if current_key != last_status:
                    yield f"data: {json.dumps(progress_data)}\n\n"
                    last_status = current_key

                # 如果完成或出错，结束流
                if progress_data["status"] in ["completed", "error"]:
                    break

                # 短暂休眠，避免 CPU 过载
                time.sleep(0.5)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/api/import/from-export", methods=["POST"])
    def api_import_from_export():
        """导入从导出功能生成的 ZIP 文件"""
        import zipfile
        import tempfile
        import shutil
        
        if "file" not in request.files:
            return jsonify({"success": False, "error": "未提供文件"}), 400

        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"success": False, "error": "未选择文件"}), 400

        # 检查文件扩展名
        if not file.filename.lower().endswith(".zip"):
            return jsonify({"success": False, "error": "仅支持 ZIP 文件"}), 400

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="import_export_")
        
        try:
            # 保存上传的 ZIP 文件
            zip_path = os.path.join(temp_dir, "export.zip")
            file.save(zip_path)
            
            # 解压 ZIP 文件
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            
            print(f"[Import] 解压 ZIP 文件到: {extract_dir}")
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(extract_dir)
            
            # 检查是否有 papers 文件夹
            papers_folder = os.path.join(extract_dir, "papers")
            if not os.path.exists(papers_folder) or not os.path.isdir(papers_folder):
                return jsonify({"success": False, "error": "无效的导出文件：缺少 papers 文件夹"}), 400
            
            # 1. 先复制整个文件夹结构到目标位置（这样目录树立即可见）
            print(f"[Import] 开始复制文件夹结构到: {upload_folder}")
            for item in os.listdir(papers_folder):
                src_path = os.path.join(papers_folder, item)
                dst_path = os.path.join(upload_folder, item)
                
                if os.path.isdir(src_path):
                    # 复制整个目录
                    if os.path.exists(dst_path):
                        # 如果目标目录已存在，合并内容
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                    else:
                        shutil.copytree(src_path, dst_path)
                else:
                    # 复制文件
                    shutil.copy2(src_path, dst_path)
            
            print(f"[Import] 文件夹复制完成")
            
            # 计算 JSON 文件数量（论文数量）
            total_papers = sum([len([f for f in files if f.endswith('.json')]) for _, _, files in os.walk(upload_folder)])
            
            # 检查是否已有正在进行的导入任务
            global current_import_task_id
            if current_import_task_id:
                with import_tasks_lock:
                    existing_task = import_tasks.get(current_import_task_id)
                    if existing_task and existing_task.get("status") not in ["completed", "error"]:
                        return jsonify({
                            "success": False,
                            "error": "已有导入任务正在进行中",
                            "task_id": current_import_task_id,
                        }), 400
            
            # 创建导入任务
            task_id = str(uuid.uuid4())
            current_import_task_id = task_id

            with import_tasks_lock:
                import_tasks[task_id] = {
                    "status": "starting",
                    "progress": 0,
                    "current": 0,
                    "total": total_papers,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "duplicate_count": 0,
                    "others_count": 0,
                    "message": "文件夹已复制，开始重建论文...",
                    "start_time": datetime.now().isoformat(),
                    "last_update": datetime.now().isoformat(),
                }

            # 2. 启动后台任务重建论文（从 arXiv 下载 PDF）
            thread = threading.Thread(
                target=_rebuild_papers_from_json,
                args=(task_id, upload_folder),
                daemon=False,
            )
            thread.start()

            # 清理临时目录
            shutil.rmtree(temp_dir, ignore_errors=True)

            return jsonify({
                "success": True,
                "task_id": task_id,
                "total_papers": total_papers,
                "message": "文件夹已导入，正在后台重建论文"
            })

        except zipfile.BadZipFile:
            return jsonify({"success": False, "error": "无效的 ZIP 文件"}), 400
        except Exception as e:
            print(f"导入失败: {e}")
            import traceback
            traceback.print_exc()
            # 清理临时目录
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({"success": False, "error": str(e)}), 500

    def _rebuild_papers_from_json(
        task_id: str,
        papers_folder: str,
    ):
        """后台任务：从 JSON 元数据重建论文（从 arXiv 下载 PDF）"""
        global current_import_task_id
        
        def update_progress(status=None, progress=None, current=None, total=None, message=None, 
                          success_count=None, failed_count=None, skipped_count=None, duplicate_count=None):
            """更新任务进度"""
            with import_tasks_lock:
                if task_id in import_tasks:
                    task = import_tasks[task_id]
                    if status is not None:
                        task["status"] = status
                    if progress is not None:
                        task["progress"] = progress
                    if current is not None:
                        task["current"] = current
                    if total is not None:
                        task["total"] = total
                    if message is not None:
                        task["message"] = message
                    if success_count is not None:
                        task["success_count"] = success_count
                    if failed_count is not None:
                        task["failed_count"] = failed_count
                    if skipped_count is not None:
                        task["skipped_count"] = skipped_count
                    if duplicate_count is not None:
                        task["duplicate_count"] = duplicate_count
                    task["last_update"] = datetime.now().isoformat()
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        duplicate_count = 0
        
        try:
            # 1. 收集所有 JSON 文件（排除配置文件）
            json_files = []
            exclude_files = {'categories.json', 'reading_list.json', 'user_settings.json', 
                           'reading_history.json', 'agentic_settings.json', 'daily_arxiv_settings.json'}
            
            for root, dirs, files in os.walk(papers_folder):
                # 排除隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if file.endswith('.json') and file not in exclude_files:
                        json_path = os.path.join(root, file)
                        json_files.append(json_path)
            
            total_papers = len(json_files)
            print(f"[Import] 找到 {total_papers} 个论文 JSON 文件")
            
            update_progress(
                status="importing",
                progress=0,
                current=0,
                total=total_papers,
                message="开始导入论文...",
            )
            
            # 2. 逐个处理 JSON 文件
            for idx, json_path in enumerate(json_files):
                try:
                    # 读取 JSON 元数据
                    with open(json_path, 'r', encoding='utf-8') as f:
                        paper_meta = json.load(f)
                    
                    title = paper_meta.get('title', '')
                    authors = paper_meta.get('authors', '')
                    arxiv_id = paper_meta.get('arxiv_id', '')
                    
                    if not title:
                        print(f"[Import] 跳过：缺少标题")
                        skipped_count += 1
                        continue
                    
                    # 更新进度
                    update_progress(
                        status="importing",
                        progress=int((idx / total_papers) * 100),
                        current=idx,
                        total=total_papers,
                        message=f"正在导入: {title[:50]}...",
                        success_count=success_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        duplicate_count=duplicate_count,
                    )
                    
                    # 获取论文所在目录
                    paper_dir = os.path.dirname(json_path)
                    
                    # 检查该目录下是否已有 PDF
                    pdf_exists = False
                    expected_pdf_name = os.path.basename(json_path).replace('.json', '.pdf')
                    expected_pdf_path = os.path.join(paper_dir, expected_pdf_name)
                    
                    if os.path.exists(expected_pdf_path):
                        print(f"[Import] PDF 已存在，跳过下载: {title[:50]}")
                        # 但仍需要注册到系统
                        pdf_exists = True
                        pdf_path = expected_pdf_path
                    
                    # 3. 如果 PDF 不存在，从 arXiv 下载
                    if not pdf_exists:
                        pdf_content = None
                        pdf_filename = None
                        
                        if arxiv_id:
                            # 有 arXiv ID，直接下载
                            result = _download_arxiv_pdf(arxiv_id)
                            if result:
                                pdf_content, pdf_filename = result
                        else:
                            # 没有 arXiv ID，尝试搜索
                            if title and authors:
                                print(f"[Import] 尝试搜索 arXiv: {title[:50]}...")
                                paper_info = search_arxiv_by_title_and_author_fast(title, authors)
                                if paper_info and paper_info.get('arxiv_id'):
                                    result = _download_arxiv_pdf(paper_info['arxiv_id'])
                                    if result:
                                        pdf_content, pdf_filename = result
                                        # 更新元数据中的 arXiv ID
                                        paper_meta['arxiv_id'] = paper_info['arxiv_id']
                                        if not paper_meta.get('arxiv_url'):
                                            paper_meta['arxiv_url'] = paper_info.get('url', '')
                        
                        if not pdf_content:
                            print(f"[Import] 无法下载 PDF: {title[:50]}")
                            failed_count += 1
                            continue
                        
                        # 4. 保存 PDF
                        pdf_path = expected_pdf_path
                        with open(pdf_path, 'wb') as f:
                            f.write(pdf_content)
                    
                    # 5. 更新元数据
                    paper_meta['file_path'] = pdf_path
                    if not paper_meta.get('id'):
                        paper_meta['id'] = str(uuid.uuid4())
                    paper_meta['upload_source'] = 'export_import'
                    
                    # 保存更新后的 JSON
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(paper_meta, f, ensure_ascii=False, indent=2)
                    
                    # 6. 注册到 paper_store
                    from core.base_paper import Paper
                    new_paper = Paper(
                        id=paper_meta['id'],
                        title=paper_meta.get('title', ''),
                        authors=paper_meta.get('authors', ''),
                        file_path=pdf_path,
                        upload_date=paper_meta.get('upload_date', ''),
                        filename=paper_meta.get('filename', ''),
                        original_filename=paper_meta.get('original_filename', ''),
                        arxiv_url=paper_meta.get('arxiv_url') or paper_meta.get('url', ''),
                        arxiv_id=paper_meta.get('arxiv_id', ''),
                        arxiv_published_date=paper_meta.get('arxiv_published_date', ''),
                        year=paper_meta.get('year', ''),
                        abstract=paper_meta.get('abstract', ''),
                        summary=paper_meta.get('summary', ''),
                        bibtex=paper_meta.get('bibtex', ''),
                        notes=paper_meta.get('notes', ''),
                        upload_source='export_import',
                        affiliation=paper_meta.get('affiliation', ''),
                        journal=paper_meta.get('journal', ''),
                        subject=paper_meta.get('subject', ''),
                        keywords=paper_meta.get('keywords', ''),
                        starred=paper_meta.get('starred', False),
                        read_time=paper_meta.get('read_time', 0),
                        analysis_view_time=paper_meta.get('analysis_view_time', 0),
                        translation_time=paper_meta.get('translation_time', 0),
                        analysis_time=paper_meta.get('analysis_time', 0),
                    )
                    
                    # 获取分类路径（相对于 papers_folder）
                    rel_dir = os.path.relpath(paper_dir, papers_folder)
                    category_path_parts = rel_dir.split(os.sep) if rel_dir != '.' else []
                    
                    if category_path_parts:
                        # 查找或创建分类
                        current_categories = get_categories()
                        category_id = _find_or_create_category(
                            current_categories,
                            category_path_parts,
                            save_categories,
                            create_category_folder,
                        )
                        
                        if category_id:
                            category_path = ['root'] + category_path_parts
                            paper_store.upsert(new_paper, category_id=category_id, category_path=category_path)
                            save_paper_metadata(pdf_path, new_paper)
                    else:
                        # 根目录下的论文
                        paper_store.upsert(new_paper, category_id='root', category_path=['root'])
                        save_paper_metadata(pdf_path, new_paper)
                    
                    success_count += 1
                    print(f"[Import] ✅ 成功导入: {title[:50]}")
                
                except Exception as e:
                    print(f"[Import] ❌ 处理失败: {json_path}, 错误: {e}")
                    import traceback
                    traceback.print_exc()
                    failed_count += 1
            
            # 导入完成
            update_progress(
                status="completed",
                progress=100,
                current=total_papers,
                total=total_papers,
                message="导入完成",
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                duplicate_count=duplicate_count,
            )
            
            print(f"[Import] 导入完成: 成功 {success_count}, 失败 {failed_count}, 跳过 {skipped_count}, 重复 {duplicate_count}")
        
        except Exception as e:
            print(f"[Import] 导入任务失败: {e}")
            import traceback
            traceback.print_exc()
            
            update_progress(
                status="error",
                message=f"导入失败: {str(e)}",
            )
        
        finally:
            # 清除当前任务标记
            current_import_task_id = None

    def _import_from_export_task_old(
        task_id: str,
        papers_list: List[Dict[str, Any]],
        extract_dir: str,
        manifest: Dict[str, Any],
    ):
        """后台任务：导入从导出功能生成的论文"""
        success_count = 0
        failed_count = 0
        skipped_count = 0
        duplicate_count = 0
        others_count = 0
        total = len(papers_list)

        try:
            # 恢复分类结构
            exported_categories = manifest.get("categories", {})
            current_categories = get_categories()
            
            # 合并分类结构（简单的追加到根目录）
            # TODO: 可以更智能地合并分类
            
            for idx, paper_info in enumerate(papers_list):
                try:
                    _update_task_progress(
                        task_id,
                        status="importing",
                        progress=int((idx / total) * 100),
                        current=idx,
                        total=total,
                        success_count=success_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        duplicate_count=duplicate_count,
                        others_count=others_count,
                        message=f"正在导入: {paper_info['metadata'].get('title', '')[:50]}...",
                    )
                    
                    paper_metadata = paper_info["metadata"]
                    category_path_list = paper_info["category_path"]  # ['CS', 'ML']
                    
                    # 确保目标分类存在
                    full_category_path = ["root"] + category_path_list
                    category_id = None
                    
                    # 遍历分类路径，创建不存在的分类
                    current_node = current_categories
                    for cat_name in category_path_list:
                        # 查找子分类
                        found = False
                        for child in current_node.get("children", []):
                            if child.get("name") == cat_name:
                                current_node = child
                                category_id = child.get("id")
                                found = True
                                break
                        
                        # 如果不存在，创建新分类
                        if not found:
                            # 创建新分类
                            new_cat_id = str(uuid.uuid4())
                            new_category = {
                                "id": new_cat_id,
                                "name": cat_name,
                                "children": [],
                                "isPinned": False,
                            }
                            if "children" not in current_node:
                                current_node["children"] = []
                            current_node["children"].append(new_category)
                            current_node = new_category
                            category_id = new_cat_id
                            
                            # 保存分类树
                            save_categories(current_categories)
                    
                    if not category_id:
                        print(f"[Import] ⚠️ 无法创建分类路径: {category_path_list}")
                        failed_count += 1
                        continue
                    
                    # 创建分类文件夹
                    category_folder = create_category_folder(full_category_path)
                    
                    # 检查是否已存在相同的论文
                    paper_id = paper_metadata.get("id")
                    existing_paper = paper_store.get(paper_id) if paper_id else None
                    if existing_paper:
                        print(f"[Import] 📋 论文已存在，跳过: {paper_metadata.get('title', '')[:50]}")
                        duplicate_count += 1
                        continue
                    
                    # 生成新的 paper_id
                    new_paper_id = str(uuid.uuid4())
                    
                    # 复制 PDF 文件
                    pdf_filename = os.path.basename(paper_metadata.get("file_path", ""))
                    if not pdf_filename:
                        pdf_filename = f"{new_paper_id}.pdf"
                    
                    zip_pdf_path = os.path.join(extract_dir, "papers", "/".join(category_path_list), pdf_filename)
                    
                    if not os.path.exists(zip_pdf_path):
                        print(f"[Import] ⚠️ PDF 文件不存在: {zip_pdf_path}")
                        skipped_count += 1
                        continue
                    
                    # 复制 PDF 到目标位置
                    dest_pdf_path = os.path.join(category_folder, pdf_filename)
                    shutil.copy2(zip_pdf_path, dest_pdf_path)
                    
                    # 复制中文翻译（如果有）
                    chinese_path = paper_metadata.get("chinese_version_path")
                    if chinese_path:
                        chinese_filename = os.path.basename(chinese_path)
                        zip_chinese_path = os.path.join(extract_dir, "papers", "/".join(category_path_list), chinese_filename)
                        if os.path.exists(zip_chinese_path):
                            dest_chinese_path = os.path.join(category_folder, chinese_filename)
                            shutil.copy2(zip_chinese_path, dest_chinese_path)
                            paper_metadata["chinese_version_path"] = dest_chinese_path
                    
                    # 复制 AI 解读（如果有）
                    analysis_path = paper_metadata.get("analysis_result_path")
                    if analysis_path:
                        analysis_filename = os.path.basename(analysis_path)
                        zip_analysis_path = os.path.join(extract_dir, "papers", "/".join(category_path_list), analysis_filename)
                        if os.path.exists(zip_analysis_path):
                            dest_analysis_path = os.path.join(category_folder, analysis_filename)
                            shutil.copy2(zip_analysis_path, dest_analysis_path)
                            paper_metadata["analysis_result_path"] = dest_analysis_path
                            
                            # 复制图片文件夹
                            images_folder_name = analysis_filename.replace("_analysis.md", "_images")
                            zip_images_path = os.path.join(extract_dir, "papers", "/".join(category_path_list), images_folder_name)
                            if os.path.exists(zip_images_path) and os.path.isdir(zip_images_path):
                                dest_images_path = os.path.join(category_folder, images_folder_name)
                                if os.path.exists(dest_images_path):
                                    shutil.rmtree(dest_images_path)
                                shutil.copytree(zip_images_path, dest_images_path)
                    
                    # 创建 Paper 对象
                    new_paper = Paper(
                        id=new_paper_id,
                        title=paper_metadata.get("title", ""),
                        authors=paper_metadata.get("authors", ""),
                        file_path=dest_pdf_path,
                        url=paper_metadata.get("url", ""),
                        arxiv_id=paper_metadata.get("arxiv_id", ""),
                        arxiv_published_date=paper_metadata.get("arxiv_published_date", ""),
                        year=paper_metadata.get("year", ""),
                        abstract=paper_metadata.get("abstract", ""),
                        summary=paper_metadata.get("summary", ""),
                        bibtex=paper_metadata.get("bibtex", ""),
                        notes=paper_metadata.get("notes", ""),
                        upload_source="export_import",
                        has_chinese_version=paper_metadata.get("has_chinese_version", False),
                        chinese_version_path=paper_metadata.get("chinese_version_path", ""),
                        has_analysis_result=paper_metadata.get("has_analysis_result", False),
                        analysis_result_path=paper_metadata.get("analysis_result_path", ""),
                        read_time=paper_metadata.get("read_time", 0),
                        analysis_view_time=paper_metadata.get("analysis_view_time", 0),
                    )
                    
                    # 注册到 paper_store
                    registered_paper = paper_store.upsert(
                        new_paper, category_id=category_id, category_path=full_category_path
                    )
                    
                    # 保存元数据
                    save_paper_metadata(dest_pdf_path, registered_paper)
                    
                    success_count += 1
                    print(f"[Import] ✅ 成功导入: {paper_metadata.get('title', '')[:50]}")
                    
                except Exception as e:
                    print(f"[Import] ❌ 导入论文失败: {e}")
                    import traceback
                    traceback.print_exc()
                    failed_count += 1
            
            # 导入完成
            _update_task_progress(
                task_id,
                status="completed",
                progress=100,
                current=total,
                total=total,
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                duplicate_count=duplicate_count,
                others_count=others_count,
                message="导入完成",
            )
            
            # TODO: 恢复待读列表、阅读历史、用户设置
            # reading_list = manifest.get("reading_list", [])
            # reading_history = manifest.get("reading_history", {})
            # user_settings = manifest.get("user_settings", {})
            
        except Exception as e:
            print(f"[Import] ❌ 导入任务失败: {e}")
            import traceback
            traceback.print_exc()
            
            update_progress(
                status="error",
                message=f"导入失败: {str(e)}",
            )
        
        finally:
            # 清除当前任务标记
            global current_import_task_id
            current_import_task_id = None
            
            # 清理临时目录
            temp_dir = os.path.dirname(extract_dir)
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as e:
                    print(f"[Import] 清理临时目录失败: {e}")
            
            print(f"[Import] 导入完成: 成功 {success_count}, 失败 {failed_count}, 跳过 {skipped_count}, 重复 {duplicate_count}")
