"""
Zotero RDF 导入路由
处理从 Zotero 导入论文的功能
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
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
    """下载 arXiv PDF"""
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    try:
        print(f"[Import] 正在从 arXiv 下载 PDF: {pdf_url}")
        response = requests.get(pdf_url, timeout=60, stream=True)
        response.raise_for_status()
        pdf_content = response.content
        filename = f"{arxiv_id}.pdf"
        print(f"[Import] 成功下载 PDF, 大小: {len(pdf_content)} bytes")
        return pdf_content, filename
    except requests.exceptions.RequestException as exc:
        print(f"[Import] 下载 arXiv PDF 失败: {exc}")
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
