from __future__ import annotations

import os
import shutil
import uuid
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, jsonify, request, send_file
from io import BytesIO


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class SaveCategoriesFn(Protocol):
    def __call__(self, categories: Dict[str, Any]) -> None: ...


class FindCategoryNodeFn(Protocol):
    def __call__(
        self, categories: Dict[str, Any], category_id: str
    ) -> Optional[Dict[str, Any]]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_id: str, category_path: List[str]) -> List[Any]: ...


class AddPdfCountsFn(Protocol):
    def __call__(
        self, categories: Dict[str, Any], count_func: Callable[[str], int]
    ) -> Dict[str, Any]: ...


class GetCategoryPdfCountFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        get_papers_in_category: GetPapersInCategoryFn,
    ) -> int: ...


class PaperStore(Protocol):
    def list_by_category(self, category_id: str) -> List[Any]: ...


def register_category_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    save_categories: SaveCategoriesFn,
    find_category_node: FindCategoryNodeFn,
    get_category_path: GetCategoryPathFn,
    get_papers_in_category: GetPapersInCategoryFn,
    add_pdf_counts_to_categories: AddPdfCountsFn,
    get_category_pdf_count: GetCategoryPdfCountFn,
    paper_store: PaperStore,
    upload_folder: str,
) -> None:
    @app.route("/api/categories")
    def api_categories():
        categories = get_categories()
        categories_with_counts = add_pdf_counts_to_categories(
            categories,
            lambda cid: get_category_pdf_count(categories, cid, get_papers_in_category),
        )
        return jsonify(categories_with_counts)

    @app.route("/api/categories", methods=["POST"])
    def api_add_category():
        data = request.json or {}
        parent_id = data.get("parent_id")
        name = data.get("name")

        if not name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        categories = get_categories()
        if not parent_id or parent_id in {"root", categories.get("id")}:
            parent_node = categories
        else:
            parent_node = find_category_node(categories, parent_id)

        if parent_node is None:
            return (
                jsonify({"success": False, "error": "Parent category not found"}),
                404,
            )

        new_category = {"id": str(uuid.uuid4()), "name": name, "children": []}
        parent_node.setdefault("children", []).append(new_category)
        save_categories(categories)
        return jsonify({"success": True, "category": new_category})

    @app.route("/api/categories/<category_id>", methods=["PUT"])
    def api_rename_category(category_id):
        data = request.json or {}
        new_name = data.get("name")

        if not new_name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["name"] = new_name
        save_categories(categories)
        return jsonify({"success": True})

    @app.route("/api/categories/<category_id>", methods=["DELETE"])
    def api_delete_category(category_id):
        categories = get_categories()

        def delete_category_recursive(node: Dict[str, Any], target_id: str) -> bool:
            children = node.get("children", [])
            for index, child in enumerate(children):
                if child["id"] == target_id:
                    category_path = get_category_path(categories, target_id)
                    if category_path and len(category_path) > 1:
                        folder_path = os.path.join(upload_folder, *category_path[1:])
                        if os.path.exists(folder_path):
                            shutil.rmtree(folder_path)
                            print(f"已删除分类文件夹: {folder_path}")

                    del children[index]
                    return True
                if delete_category_recursive(child, target_id):
                    return True
            return False

        if delete_category_recursive(categories, category_id):
            save_categories(categories)
            return jsonify({"success": True})

        return jsonify({"success": False, "error": "Category not found"}), 404

    @app.route("/api/categories/<category_id>/export-bibtex", methods=["GET"])
    def api_export_category_bibtex(category_id: str):
        """
        导出分类及其所有子分类下所有论文的 BibTeX
        
        递归遍历分类树，收集所有论文的 BibTeX，合并成一个 .bib 文件
        """
        try:
            categories = get_categories()
            category_node = find_category_node(categories, category_id)
            
            if not category_node:
                return jsonify({"error": "Category not found"}), 404
            
            # 递归收集所有论文的 BibTeX
            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                """递归收集分类及其子分类下的所有论文"""
                papers = []
                
                # 获取当前分类的论文
                node_path = get_category_path(categories, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)
                
                # 递归处理子分类
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))
                
                return papers
            
            all_papers = collect_papers_recursive(category_node)
            
            if not all_papers:
                return jsonify({"error": "该分类下没有论文"}), 404
            
            # 收集所有 BibTeX
            bibtex_entries = []
            for paper in all_papers:
                # paper 可能是 Paper 对象或字典
                if hasattr(paper, 'bibtex'):
                    bibtex = paper.bibtex
                elif isinstance(paper, dict):
                    bibtex = paper.get("bibtex", "")
                else:
                    bibtex = ""
                
                if bibtex and bibtex.strip():
                    bibtex_entries.append(bibtex.strip())
            
            if not bibtex_entries:
                return jsonify({"error": "该分类下的论文都没有 BibTeX"}), 404
            
            # 合并所有 BibTeX 条目
            bibtex_content = "\n\n".join(bibtex_entries)
            
            # 生成文件名（使用分类名称）
            category_name = category_node.get("name", "export")
            # 清理文件名（移除特殊字符）
            safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '' for c in category_name)
            safe_name = safe_name.strip().replace(' ', '_')
            filename = f"{safe_name}_bibtex.bib"
            
            # 创建文件对象
            bibtex_bytes = bibtex_content.encode('utf-8')
            bibtex_file = BytesIO(bibtex_bytes)
            
            print(f"[导出 BibTeX] 分类: {category_name}, 论文数: {len(all_papers)}, BibTeX 条目数: {len(bibtex_entries)}")
            
            return send_file(
                bibtex_file,
                mimetype='application/x-bibtex',
                as_attachment=True,
                download_name=filename
            )
            
        except Exception as exc:
            print(f"导出 BibTeX 失败: {exc}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"导出失败: {str(exc)}"}), 500
