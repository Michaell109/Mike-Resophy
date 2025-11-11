from __future__ import annotations

import os
import shutil
import uuid
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, jsonify, request


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
