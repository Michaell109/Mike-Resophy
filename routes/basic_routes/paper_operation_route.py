from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from flask import Flask, jsonify, request, send_file

from core.base_paper import Paper


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class FindCategoryNodeFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
    ) -> Optional[Dict[str, Any]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_path: List[str]) -> List[Paper]: ...


class CreateCategoryFolderFn(Protocol):
    def __call__(self, category_path: List[str]) -> str: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


class GetPaperJsonPathFn(Protocol):
    def __call__(self, pdf_path: str) -> str: ...


class DeletePaperFilesFn(Protocol):
    def __call__(self, pdf_path: str) -> None: ...


class AddToReadingListFn(Protocol):
    def __call__(self, paper_id: str) -> None: ...


class RemoveFromReadingListFn(Protocol):
    def __call__(self, paper_id: str) -> None: ...


def register_paper_operation_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    find_category_node: FindCategoryNodeFn,
    get_papers_in_category: GetPapersInCategoryFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    get_paper_json_path: GetPaperJsonPathFn,
    delete_paper_files: DeletePaperFilesFn,
    reading_list_file: str,
    upload_folder: str,
    general_settings_file: str,
    default_settings: Dict[str, Any],
) -> None:
    def load_general_settings() -> Dict[str, Any]:
        try:
            with open(general_settings_file, "r", encoding="utf-8") as fp:
                settings = json.load(fp)
        except FileNotFoundError:
            settings = {}
        except Exception as exc:  # noqa: BLE001
            print(f"读取常规设置失败: {exc}")
            settings = {}
        merged = default_settings.copy()
        merged.update(settings)
        return merged

    def load_reading_list() -> List[str]:
        try:
            with open(reading_list_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("papers", [])
        except Exception as exc:  # noqa: BLE001
            print(f"读取待读列表失败: {exc}")
            return []

    def save_reading_list(paper_ids: List[str]) -> None:
        try:
            with open(reading_list_file, "w", encoding="utf-8") as f:
                json.dump({"papers": paper_ids}, f, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            print(f"保存待读列表失败: {exc}")

    def add_to_reading_list(paper_id: str) -> None:
        paper_ids = load_reading_list()
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
            save_reading_list(paper_ids)

    def remove_from_reading_list(paper_id: str) -> None:
        paper_ids = load_reading_list()
        if paper_id in paper_ids:
            paper_ids.remove(paper_id)
            save_reading_list(paper_ids)

    def is_in_reading_list(paper_id: str) -> bool:
        return paper_id in load_reading_list()

    def find_paper(
        categories: Dict[str, Any],
        paper_id: str,
    ) -> Optional[Tuple[Paper, List[str], str]]:
        """Return Paper object, category path, and category_id."""

        def search(node: Dict[str, Any]) -> Optional[Tuple[Paper, List[str], str]]:
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(category_path)
                for paper in papers:
                    if paper.id == paper_id:
                        return paper, category_path, node["id"]
            for child in node.get("children", []):
                result = search(child)
                if result:
                    return result
            return None

        for child in categories.get("children", []):
            result = search(child)
            if result:
                return result
        return None

    def collect_papers_by_ids(
        categories: Dict[str, Any],
        paper_ids: Iterable[str],
    ) -> List[Paper]:
        id_order = list(paper_ids)
        id_set = set(id_order)
        collected: Dict[str, Paper] = {}

        def traverse(node: Dict[str, Any]) -> None:
            if not id_set:
                return
            category_path = get_category_path(categories, node["id"])
            if category_path:
                for paper in get_papers_in_category(category_path):
                    if paper.id in id_set:
                        collected[paper.id] = paper
                        id_set.remove(paper.id)
            for child in node.get("children", []):
                if id_set:
                    traverse(child)

        for child in categories.get("children", []):
            traverse(child)
            if not id_set:
                break
        return [collected[pid] for pid in id_order if pid in collected]

    @app.route("/api/papers/<category_id>")
    def api_papers(category_id: str):
        categories = get_categories()
        category_path = get_category_path(categories, category_id)

        if not category_path:
            return jsonify({"error": "Category not found"}), 404

        papers = get_papers_in_category(category_path)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/paper/<paper_id>")
    def api_paper_info(paper_id: str):
        categories = get_categories()
        result = find_paper(categories, paper_id)
        if result:
            paper, _, _ = result
            return jsonify(paper.to_dict())
        return jsonify({"error": "Paper not found"}), 404

    @app.route("/api/paper/<paper_id>/move", methods=["PUT"])
    def api_move_paper(paper_id: str):
        data = request.json or {}
        target_category_id = data.get("target_category_id")

        if not target_category_id:
            return (
                jsonify({"success": False, "error": "Target category ID is required"}),
                400,
            )

        categories = get_categories()
        result = find_paper(categories, paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        paper_obj, source_path, source_category_id = result

        target_category = find_category_node(categories, target_category_id)
        if not target_category:
            return (
                jsonify({"success": False, "error": "Target category not found"}),
                404,
            )

        target_path = get_category_path(categories, target_category_id)
        if not target_path:
            return (
                jsonify({"success": False, "error": "Target category path not found"}),
                404,
            )

        try:
            target_folder = (
                os.path.join(upload_folder, *target_path[1:])
                if len(target_path) > 1
                else upload_folder
            )

            source_file_path = paper_obj.file_path
            source_json_path = get_paper_json_path(source_file_path)

            os.makedirs(target_folder, exist_ok=True)

            target_file_path = os.path.join(target_folder, paper_obj.filename)
            target_json_path = get_paper_json_path(target_file_path)

            counter = 1
            original_filename = paper_obj.filename
            while os.path.exists(target_file_path):
                name, ext = os.path.splitext(original_filename)
                new_filename = f"{name}_{counter}{ext}"
                target_file_path = os.path.join(target_folder, new_filename)
                target_json_path = get_paper_json_path(target_file_path)
                counter += 1

            if os.path.exists(source_file_path):
                shutil.move(source_file_path, target_file_path)
                print(f"已移动PDF文件: {source_file_path} -> {target_file_path}")

            if os.path.exists(source_json_path):
                shutil.move(source_json_path, target_json_path)
                print(f"已移动JSON文件: {source_json_path} -> {target_json_path}")

            paper_obj.filename = os.path.basename(target_file_path)
            paper_obj.file_path = target_file_path

            save_paper_metadata(target_file_path, paper_obj)

            return jsonify(
                {
                    "success": True,
                    "paper": paper_obj.to_dict(),
                    "source_category": source_category_id,
                    "target_category": target_category_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"移动论文失败: {exc}")
            return (
                jsonify({"success": False, "error": f"Failed to move file: {exc}"}),
                500,
            )

    @app.route("/api/paper/<paper_id>/file")
    def api_get_paper_file(paper_id: str):
        categories = get_categories()

        result = find_paper(categories, paper_id)
        if not result:
            return jsonify({"error": "Paper not found"}), 404

        paper, category_path, _ = result
        file_path = paper.file_path

        if not file_path:
            filename = paper.filename
            if filename and category_path:
                category_folder = create_category_folder(category_path[1:])
                file_path = os.path.join(category_folder, filename)
                print(f"尝试重建路径: {file_path}")

        if not file_path:
            return jsonify({"error": "File path not found in paper data"}), 404

        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        print(f"查找PDF文件: {file_path}, 存在: {os.path.exists(file_path)}")
        if not os.path.exists(file_path):
            return jsonify({"error": f"File not found: {file_path}"}), 404

        response = send_file(
            file_path,
            as_attachment=False,
            mimetype="application/pdf",
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.route("/api/paper/<paper_id>", methods=["DELETE"])
    def api_delete_paper(paper_id: str):
        try:
            categories = get_categories()
            result = find_paper(categories, paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, _, category_id = result
            if paper.file_path:
                delete_paper_files(paper.file_path)

            return jsonify(
                {
                    "success": True,
                    "message": "Paper deleted successfully",
                    "paper": paper.to_dict(),
                    "category_id": category_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"删除论文失败: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>", methods=["PUT"])
    def api_update_paper(paper_id: str):
        try:
            data = request.json or {}
            categories = get_categories()
            result = find_paper(categories, paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, _, _ = result
            paper.update_from_dict(data)
            paper.extra["updated_date"] = datetime.now().isoformat()

            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            return jsonify(
                {
                    "success": True,
                    "message": "Paper updated successfully",
                    "paper": paper.to_dict(),
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"更新论文失败: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/reading-list", methods=["GET"])
    def api_get_reading_list():
        categories = get_categories()
        paper_ids = load_reading_list()
        settings = load_general_settings()
        max_items = settings.get("reading_list_max_items")
        if isinstance(max_items, int) and max_items > 0:
            paper_ids = paper_ids[:max_items]
        papers = collect_papers_by_ids(categories, paper_ids)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/reading-list/<paper_id>/add", methods=["POST"])
    def api_add_to_reading_list(paper_id: str):
        categories = get_categories()
        result = find_paper(categories, paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        add_to_reading_list(paper_id)
        return jsonify({"success": True})

    @app.route("/api/reading-list/<paper_id>/remove", methods=["POST"])
    def api_remove_from_reading_list(paper_id: str):
        if not is_in_reading_list(paper_id):
            return (
                jsonify({"success": False, "error": "Paper not in reading list"}),
                404,
            )

        remove_from_reading_list(paper_id)
        return jsonify({"success": True})
