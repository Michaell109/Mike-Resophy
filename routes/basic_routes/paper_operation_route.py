from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from flask import Flask, jsonify, request, send_file

from core.base_paper import Paper
from core.paper_store import PaperStore
from tools.basic_tools.paper_repository import scan_papers_in_directory
from tools.basic_tools.upload_paper import (
    process_uploaded_pdf,
    search_arxiv_by_title_only,
)


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
    extract_pdf_metadata: Optional[Any],  # 不再使用，保留以兼容
    search_arxiv_by_title: Optional[Any],  # 不再使用，保留以兼容
    reading_list_file: str,
    upload_folder: str,
    paper_store: PaperStore,
) -> None:

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
            all_papers, key=lambda p: p.upload_date or "", reverse=True
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

    @app.route("/api/papers/<category_id>/recursive")
    def api_papers_recursive(category_id: str):
        """递归获取分类及其所有子分类下的论文（用于一级目录/Project）"""
        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if not category_node:
            return jsonify({"error": "Category not found"}), 404

        def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
            """递归收集分类及其子分类下的所有论文"""
            all_papers = []

            # 获取当前分类的论文
            node_path = get_category_path(categories, node["id"])
            if node_path:
                node_papers = get_papers_in_category(node["id"], node_path)
                all_papers.extend(node_papers)

            # 递归处理子分类
            for child in node.get("children", []):
                all_papers.extend(collect_papers_recursive(child))

            return all_papers

        all_papers = collect_papers_recursive(category_node)

        # 按上传时间排序（最新的在前）
        sorted_papers = sorted(
            all_papers, key=lambda p: p.upload_date or "", reverse=True
        )

        return jsonify([paper.to_dict() for paper in sorted_papers])

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

            zh_dual_target = os.path.join(
                target_folder, f"{final_base_name}.zh.dual.pdf"
            )
            zh_mono_target = os.path.join(
                target_folder, f"{final_base_name}.zh.mono.pdf"
            )
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
                print(
                    f"已移动翻译日志: {translate_log_source} -> {translate_log_target}"
                )

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
                            new_item_name = item.replace(
                                source_base_name, final_base_name
                            )
                        else:
                            new_item_name = item

                        target_item_path = os.path.join(
                            target_outputs_dir, new_item_name
                        )

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
                            new_result_path = os.path.join(
                                target_item_path, relative_path
                            )
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

            paper, category_path, category_id = result

            # 检查用户是否手动修改了 title
            old_title = paper.title
            title_changed = False
            if "title" in data and data["title"] != old_title:
                title_changed = True
                new_title = data["title"]
                print(f"[标题更新] 用户修改标题: '{old_title}' → '{new_title}'")

            paper.update_from_dict(data)
            paper.extra["updated_date"] = datetime.now().isoformat()

            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            # 如果用户修改了 title，在后台自动重新抓取
            if title_changed and new_title:

                def _auto_refresh_on_title_change():
                    try:
                        print(f"[自动重抓] 标题已修改，开始重新抓取: {new_title}")

                        # 使用新的接口搜索 arXiv
                        best_match = search_arxiv_by_title_only(new_title)

                        if best_match:
                            print(
                                f"[自动重抓] 找到匹配: {best_match.get('title')[:50]}..."
                            )

                            # 只更新 arXiv 相关信息，不修改用户手动设置的 title
                            paper_obj = paper_store.get(paper_id)
                            if paper_obj:
                                # 更新除 title 外的所有字段
                                paper_obj.authors = best_match.get("authors", "")
                                paper_obj.affiliation = best_match.get(
                                    "affiliation", ""
                                )
                                paper_obj.abstract = best_match.get("abstract", "")
                                paper_obj.year = best_match.get("year", "")
                                paper_obj.bibtex = best_match.get("bibtex", "")
                                paper_obj.arxiv_id = best_match.get("arxiv_id", "")
                                paper_obj.arxiv_published_date = best_match.get(
                                    "published_date"
                                )
                                paper_obj.summary = best_match.get("summary", "")
                                paper_obj.extra["auto_refreshed_date"] = (
                                    datetime.now().isoformat()
                                )

                                # 保存更新
                                paper_store.upsert(
                                    paper_obj,
                                    category_id=category_id,
                                    category_path=category_path,
                                )
                                if paper_obj.file_path:
                                    save_paper_metadata(paper_obj.file_path, paper_obj)

                                print(f"[自动重抓] 完成：已更新作者、单位、摘要等信息")
                            else:
                                print(f"[自动重抓] 警告: 找不到 paper {paper_id}")
                        else:
                            print(f"[自动重抓] 未找到匹配，保持用户输入的信息不变")

                    except Exception as exc:  # noqa: BLE001
                        print(f"[自动重抓] 失败: {exc}")

                # 启动后台线程
                thread = threading.Thread(
                    target=_auto_refresh_on_title_change, daemon=True
                )
                thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": "Paper updated successfully",
                    "paper": paper.to_dict(),
                    "auto_refresh_triggered": title_changed,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"更新论文失败: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/reading-list", methods=["GET"])
    def api_get_reading_list():
        paper_ids = load_reading_list()

        # 自动同步：扫描 _ReadingListTemp 目录，将目录下的论文添加到待读列表
        reading_list_temp_path = os.path.join(upload_folder, "_ReadingListTemp")
        if os.path.exists(reading_list_temp_path):
            # 扫描目录下的所有论文
            temp_papers = scan_papers_in_directory(
                reading_list_temp_path,
                category_id="reading_list_temp",
                category_path=["Root", "_ReadingListTemp"],
            )

            # 将 _ReadingListTemp 目录下的论文添加到待读列表（如果还没有）
            updated = False
            for paper in temp_papers:
                if paper.id not in paper_ids:
                    paper_ids.append(paper.id)
                    updated = True

            # 如果有更新，保存待读列表
            if updated:
                save_reading_list(paper_ids)

        # 返回所有待读列表论文（不再限制数量）
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

        # 获取论文信息
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        paper, category_path, category_id = result

        # 检查是否在临时目录
        # 方法1: 检查 category_id
        # 方法2: 检查文件路径是否包含 _ReadingListTemp
        is_in_temp = (
            category_id == "reading_list_temp"
            or (
                category_path
                and len(category_path) > 1
                and category_path[1] == "_ReadingListTemp"
            )
            or (paper.file_path and "_ReadingListTemp" in paper.file_path)
        )

        # 获取删除选项
        data = request.json or {}
        delete_files = data.get("delete_files", False)

        # 如果在临时目录，需要用户确认删除文件（不管来源）
        if is_in_temp and not delete_files:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "需要确认删除",
                        "requires_confirmation": True,
                        "message": "该论文还未移动到某个目录，是否要删除论文文件、AI解读和AI翻译？",
                    }
                ),
                200,
            )  # 返回 200 以便前端处理

        # 如果确认删除文件，删除论文及其相关文件
        # 只要在 temp 目录就删除文件
        if delete_files and is_in_temp and paper.file_path:
            delete_paper_files(paper.file_path)
            paper_store.remove(paper_id)
        elif not is_in_temp:
            # 如果不在 temp 目录，只从待读列表移除，不删除文件
            # 论文仍然保留在原来的目录中
            pass

        # 从待读列表移除
        remove_from_reading_list(paper_id)

        # 返回是否删除了文件（只有在临时目录且用户确认删除时才删除文件）
        return jsonify({"success": True, "deleted_files": delete_files and is_in_temp})

    @app.route("/api/paper/<paper_id>/read-time", methods=["POST"])
    def api_record_read_time(paper_id: str):
        """记录论文阅读时间（累加增量）"""
        try:
            import json as json_lib
            import os
            from datetime import datetime

            data = request.json or {}
            # 使用增量方式
            increment = data.get("increment", 0)

            if not isinstance(increment, (int, float)) or increment <= 0:
                return jsonify({"success": True, "read_time": 0}), 200

            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # 累加阅读时间增量
            paper.record_read_time(int(increment))

            # 保存到文件
            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            # 同时更新阅读历史，记录论文ID和日期
            reading_history_file = os.path.join(upload_folder, "reading_history.json")

            if os.path.exists(reading_history_file):
                try:
                    with open(reading_history_file, "r", encoding="utf-8") as fp:
                        history = json_lib.load(fp)
                except:
                    history = {}

                # 获取今天的日期
                today = datetime.now().strftime("%Y-%m-%d")
                minutes = int(increment / 60)  # 转换为分钟

                # 更新阅读历史结构
                # 新格式: { "date": { "total": minutes, "papers": ["paper_id1", "paper_id2"] } }
                # 兼容旧格式: { "date": minutes }
                if today in history:
                    if isinstance(history[today], dict):
                        # 新格式
                        history[today]["total"] = (
                            history[today].get("total", 0) + minutes
                        )
                        if paper_id not in history[today].get("papers", []):
                            if "papers" not in history[today]:
                                history[today]["papers"] = []
                            history[today]["papers"].append(paper_id)
                    else:
                        # 旧格式，转换为新格式
                        old_minutes = history[today]
                        history[today] = {
                            "total": old_minutes + minutes,
                            "papers": [paper_id],
                        }
                else:
                    history[today] = {"total": minutes, "papers": [paper_id]}

                # 保存更新后的历史
                with open(reading_history_file, "w", encoding="utf-8") as fp:
                    json_lib.dump(history, fp, ensure_ascii=False, indent=2)
            else:
                # 如果文件不存在，创建新文件
                today = datetime.now().strftime("%Y-%m-%d")
                minutes = int(increment / 60)
                history = {today: {"total": minutes, "papers": [paper_id]}}
                os.makedirs(os.path.dirname(reading_history_file), exist_ok=True)
                with open(reading_history_file, "w", encoding="utf-8") as fp:
                    json_lib.dump(history, fp, ensure_ascii=False, indent=2)

            return jsonify({"success": True, "read_time": paper.read_time})

        except Exception as exc:  # noqa: BLE001
            print(f"记录阅读时间失败: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>/analysis-view-time", methods=["POST"])
    def api_record_analysis_view_time(paper_id: str):
        """记录 AI 解读阅读时间（累加增量）"""
        try:
            data = request.json or {}
            # 使用增量方式
            increment = data.get("increment", 0)

            if not isinstance(increment, (int, float)) or increment <= 0:
                return jsonify({"success": True, "analysis_view_time": 0}), 200

            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # 累加解读阅读时间增量
            paper.record_analysis_view_time(int(increment))

            # 保存到文件
            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            return jsonify(
                {"success": True, "analysis_view_time": paper.analysis_view_time}
            )

        except Exception as exc:  # noqa: BLE001
            print(f"记录解读阅读时间失败: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>/refresh-metadata", methods=["POST"])
    def api_refresh_paper_metadata(paper_id: str):
        """重新抓取 PDF 元数据"""
        try:
            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result
            file_path = paper.file_path

            if not file_path or not os.path.exists(file_path):
                return jsonify({"success": False, "error": "PDF file not found"}), 404

            # 启动后台线程处理
            def _refresh_metadata_async():
                try:
                    print(f"[重新抓取] 开始处理: {file_path}")

                    # 使用新的统一接口处理 PDF
                    filename = os.path.basename(file_path)
                    paper_info = process_uploaded_pdf(file_path, filename)

                    if not paper_info:
                        print("[重新抓取] 无法获取论文信息")
                        return

                    print(f"[重新抓取] 找到匹配: {paper_info.get('title')[:50]}...")

                    # 使用获取的信息
                    metadata = paper_info
                    arxiv_id = paper_info.get("arxiv_id")
                    arxiv_published_date = paper_info.get("published_date")

                    # 步骤2: 根据新标题重命名文件（如果标题改变）
                    current_filename = os.path.basename(file_path)
                    new_filename = current_filename
                    new_file_path = file_path
                    category_folder = os.path.dirname(file_path)

                    if metadata and metadata.get("title"):

                        def _clean_filename(text: Optional[str]) -> Optional[str]:
                            if not text:
                                return None
                            cleaned = text
                            cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
                            cleaned = re.sub(r"\s+", " ", cleaned)
                            cleaned = cleaned.strip()
                            return cleaned[:200] if cleaned else None

                        clean_title = _clean_filename(metadata["title"])
                        if (
                            clean_title
                            and clean_title != os.path.splitext(current_filename)[0]
                        ):
                            new_filename = f"{clean_title}.pdf"
                            new_file_path = os.path.join(category_folder, new_filename)

                            counter = 1
                            original_new_filename = new_filename
                            while (
                                os.path.exists(new_file_path)
                                and new_file_path != file_path
                            ):
                                name, ext = os.path.splitext(original_new_filename)
                                new_filename = f"{name}_{counter}{ext}"
                                new_file_path = os.path.join(
                                    category_folder, new_filename
                                )
                                counter += 1

                            # 重命名文件
                            if new_file_path != file_path:
                                try:
                                    # 同时移动 JSON 文件
                                    old_json_path = get_paper_json_path(file_path)
                                    new_json_path = get_paper_json_path(new_file_path)

                                    os.rename(file_path, new_file_path)
                                    print(f"[重新抓取] 文件已重命名: {new_filename}")

                                    if os.path.exists(old_json_path):
                                        os.rename(old_json_path, new_json_path)
                                        print(f"[重新抓取] JSON 文件已重命名")

                                except Exception as exc:  # noqa: BLE001
                                    print(f"[重新抓取] 重命名失败: {exc}")
                                    new_file_path = file_path
                                    new_filename = current_filename

                    # 步骤3: 更新 Paper 对象
                    paper_obj = paper_store.get(paper_id)
                    if paper_obj and metadata:
                        paper_obj.filename = new_filename
                        paper_obj.file_path = new_file_path
                        paper_obj.title = metadata.get("title") or paper_obj.title
                        paper_obj.authors = metadata.get("authors", "")
                        paper_obj.arxiv_id = arxiv_id
                        # 如果有 arxiv_id，设置 arxiv_url
                        if arxiv_id:
                            paper_obj.arxiv_url = metadata.get("arxiv_url") or f"https://arxiv.org/abs/{arxiv_id}"
                        paper_obj.arxiv_published_date = arxiv_published_date
                        paper_obj.affiliation = metadata.get("affiliation", "")
                        paper_obj.year = metadata.get("year", "")
                        paper_obj.abstract = metadata.get("abstract", "")
                        paper_obj.summary = metadata.get("summary", "")
                        paper_obj.bibtex = metadata.get("bibtex", "")
                        paper_obj.keywords = metadata.get("keywords", "")
                        paper_obj.subject = metadata.get("subject", "")
                        paper_obj.extra["updated_date"] = datetime.now().isoformat()

                        # 保存更新
                        paper_store.upsert(
                            paper_obj,
                            category_id=category_id,
                            category_path=category_path,
                        )
                        save_paper_metadata(new_file_path, paper_obj)
                        print(f"[重新抓取] 完成: {new_filename}")
                    else:
                        print(f"[重新抓取] 警告: 找不到 paper {paper_id}")

                except Exception as exc:  # noqa: BLE001
                    print(f"[重新抓取] 失败: {exc}")

            thread = threading.Thread(target=_refresh_metadata_async, daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": "元数据抓取已启动，将在后台处理",
                    "paper_id": paper_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"启动重新抓取失败: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500
