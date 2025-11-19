from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from flask import Flask, jsonify, request, send_file

from core.base_paper import Paper
from core.paper_store import PaperStore


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
    def __call__(self, category_id: str, category_path: List[str]) -> List[Paper]: ...


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
    paper_store: PaperStore,
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

    def find_paper(paper_id: str) -> Optional[Tuple[Paper, List[str], str]]:
        entry = paper_store.get_entry(paper_id)
        if not entry:
            return None
        return entry.paper, list(entry.category_path), entry.category_id

    def collect_papers_by_ids(paper_ids: Iterable[str]) -> List[Paper]:
        ordered_ids = list(paper_ids)
        collected: List[Paper] = []
        seen: set[str] = set()
        for pid in ordered_ids:
            if pid in seen:
                continue
            paper = paper_store.get(pid)
            if paper:
                collected.append(paper)
                seen.add(pid)
        return collected

    @app.route("/api/papers/all")
    def api_all_papers():
        """获取所有论文，按上传日期降序排列"""
        all_papers = paper_store.iter_all()
        # 按上传日期降序排序（最新的在前）
        sorted_papers = sorted(
            all_papers,
            key=lambda p: p.upload_date or "",
            reverse=True
        )
        return jsonify([paper.to_dict() for paper in sorted_papers])

    @app.route("/api/papers/<category_id>")
    def api_papers(category_id: str):
        categories = get_categories()
        category_path = get_category_path(categories, category_id)

        if not category_path:
            return jsonify({"error": "Category not found"}), 404

        papers = get_papers_in_category(category_id, category_path)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/paper/<paper_id>")
    def api_paper_info(paper_id: str):
        result = find_paper(paper_id)
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
        result = find_paper(paper_id)
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
            source_dir = os.path.dirname(source_file_path)
            source_base_name = os.path.splitext(os.path.basename(source_file_path))[0]

            os.makedirs(target_folder, exist_ok=True)

            target_file_path = os.path.join(target_folder, paper_obj.filename)
            target_json_path = get_paper_json_path(target_file_path)

            counter = 1
            original_filename = paper_obj.filename
            original_base_name = os.path.splitext(original_filename)[0]
            while os.path.exists(target_file_path):
                name, ext = os.path.splitext(original_filename)
                new_filename = f"{name}_{counter}{ext}"
                target_file_path = os.path.join(target_folder, new_filename)
                target_json_path = get_paper_json_path(target_file_path)
                counter += 1

            # 确定最终的base_name（可能因重名而改变）
            final_base_name = os.path.splitext(os.path.basename(target_file_path))[0]

            # 移动PDF主文件
            if os.path.exists(source_file_path):
                shutil.move(source_file_path, target_file_path)
                print(f"已移动PDF文件: {source_file_path} -> {target_file_path}")

            # 移动JSON文件
            if os.path.exists(source_json_path):
                shutil.move(source_json_path, target_json_path)
                print(f"已移动JSON文件: {source_json_path} -> {target_json_path}")

            # 移动中文翻译文件
            zh_dual_source = os.path.join(source_dir, f"{source_base_name}.zh.dual.pdf")
            zh_mono_source = os.path.join(source_dir, f"{source_base_name}.zh.mono.pdf")
            translate_log_source = os.path.join(
                source_dir, f"{source_base_name}.translate.log"
            )

            zh_dual_target = os.path.join(target_folder, f"{final_base_name}.zh.dual.pdf")
            zh_mono_target = os.path.join(target_folder, f"{final_base_name}.zh.mono.pdf")
            translate_log_target = os.path.join(
                target_folder, f"{final_base_name}.translate.log"
            )

            if os.path.exists(zh_dual_source):
                shutil.move(zh_dual_source, zh_dual_target)
                print(f"已移动中文翻译: {zh_dual_source} -> {zh_dual_target}")
                # 更新Paper对象中的中文版本路径
                paper_obj.chinese_version_path = zh_dual_target

            if os.path.exists(zh_mono_source):
                shutil.move(zh_mono_source, zh_mono_target)
                print(f"已移动中文翻译(mono): {zh_mono_source} -> {zh_mono_target}")

            if os.path.exists(translate_log_source):
                shutil.move(translate_log_source, translate_log_target)
                print(f"已移动翻译日志: {translate_log_source} -> {translate_log_target}")

            # 移动AI解读输出目录
            source_outputs_dir = os.path.join(source_dir, "outputs")
            target_outputs_dir = os.path.join(target_folder, "outputs")

            if os.path.exists(source_outputs_dir):
                os.makedirs(target_outputs_dir, exist_ok=True)

                for item in os.listdir(source_outputs_dir):
                    item_path = os.path.join(source_outputs_dir, item)
                    # 检查是否是当前论文的输出目录
                    if os.path.isdir(item_path) and source_base_name in item:
                        # 重命名输出目录以匹配新的文件名
                        if source_base_name != final_base_name:
                            new_item_name = item.replace(source_base_name, final_base_name)
                        else:
                            new_item_name = item

                        target_item_path = os.path.join(target_outputs_dir, new_item_name)

                        # 如果目标已存在，添加计数器
                        item_counter = 1
                        while os.path.exists(target_item_path):
                            new_item_name = f"{item}_{item_counter}"
                            target_item_path = os.path.join(
                                target_outputs_dir, new_item_name
                            )
                            item_counter += 1

                        shutil.move(item_path, target_item_path)
                        print(f"已移动AI解读输出: {item_path} -> {target_item_path}")

                        # 更新Paper对象中的解读结果路径
                        if (
                            paper_obj.analysis_result_path
                            and paper_obj.analysis_result_path.startswith(item_path)
                        ):
                            relative_path = os.path.relpath(
                                paper_obj.analysis_result_path, item_path
                            )
                            new_result_path = os.path.join(target_item_path, relative_path)
                            paper_obj.analysis_result_path = new_result_path
                            print(f"已更新解读结果路径: {new_result_path}")

                # 清理空的源outputs目录
                try:
                    if not os.listdir(source_outputs_dir):
                        os.rmdir(source_outputs_dir)
                        print(f"已删除空的源outputs目录: {source_outputs_dir}")
                except Exception:
                    pass

            # 更新Paper对象的基本信息
            paper_obj.filename = os.path.basename(target_file_path)
            paper_obj.file_path = target_file_path

            # 保存更新后的元数据
            save_paper_metadata(target_file_path, paper_obj)
            paper_store.update_category(
                paper_id,
                category_id=target_category_id,
                category_path=target_path,
            )

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
        result = find_paper(paper_id)
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
            result = find_paper(paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, _, category_id = result
            if paper.file_path:
                delete_paper_files(paper.file_path)
            paper_store.remove(paper_id)

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
            result = find_paper(paper_id)
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
        paper_ids = load_reading_list()
        settings = load_general_settings()
        max_items = settings.get("reading_list_max_items")
        if isinstance(max_items, int) and max_items > 0:
            paper_ids = paper_ids[:max_items]
        papers = collect_papers_by_ids(paper_ids)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/reading-list/<paper_id>/add", methods=["POST"])
    def api_add_to_reading_list(paper_id: str):
        result = find_paper(paper_id)
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
