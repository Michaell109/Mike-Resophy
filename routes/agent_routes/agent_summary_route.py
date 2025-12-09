from __future__ import annotations

import os
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request, send_file

from tools.agent_tools.summary_pdf import AnalysisDependencies, analyze_paper_task
from core.base_paper import Paper
from core.paper_store import paper_store

CategoryPath = List[str]


def register_agent_summary_routes(
    app,
    *,
    analysis_tasks: Dict[str, Dict[str, Any]],
    analysis_tasks_lock: threading.Lock,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    save_paper_metadata: Callable[[str, Any], None],
) -> None:
    @app.route("/api/paper/analyze", methods=["POST"])
    def api_analyze_paper():
        """AI解读PDF论文 - 启动后台任务"""
        try:
            data = request.json or {}
            paper_id = data.get("paper_id")
            mineru_server_url = data.get("mineru_server_url")
            openai_base_url = data.get("openai_base_url")
            openai_api_key = data.get("openai_api_key")
            system_prompt = data.get("system_prompt", "")  # 允许为空，使用默认值

            if (
                not paper_id
                or not mineru_server_url
                or not openai_base_url
                or not openai_api_key
            ):
                return jsonify({"success": False, "error": "缺少必要参数"}), 400

            with analysis_tasks_lock:
                for task_id, task_info in analysis_tasks.items():
                    if (
                        task_info["paper_id"] == paper_id
                        and task_info["status"] == "running"
                    ):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "该论文已有解读任务在运行",
                                    "task_id": task_id,
                                }
                            ),
                            400,
                        )

            # 首先尝试从 paper_store 中查找论文（支持 _ReadingListTemp 目录）
            entry = paper_store.get_entry(paper_id)
            if entry:
                paper = entry.paper
                category_path = list(entry.category_path)
            else:
                # 如果 paper_store 中找不到，使用递归搜索分类树
                categories = get_categories()

                def search_paper_recursive(node):
                    category_path = get_category_path(categories, node["id"])
                    if category_path:
                        papers = get_papers_in_category(node["id"], category_path)
                        for paper in papers:
                            if paper.id == paper_id:
                                return paper, category_path

                    if "children" in node:
                        for child in node["children"]:
                            result = search_paper_recursive(child)
                            if result:
                                return result

                    return None

                result = None
                for child in categories.get("children", []):
                    result = search_paper_recursive(child)
                    if result:
                        break

                if not result:
                    return jsonify({"success": False, "error": "论文未找到"}), 404

                paper, category_path = result
            pdf_path = paper.file_path

            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({"success": False, "error": "PDF文件不存在"}), 404

            pdf_dir = os.path.dirname(pdf_path)
            pdf_filename = os.path.basename(pdf_path)

            task_id = str(uuid.uuid4())

            with analysis_tasks_lock:
                analysis_tasks[task_id] = {
                    "paper_id": paper_id,
                    "status": "queued",
                    "step": None,
                    "logs": [],
                    "log_lock": threading.Lock(),
                    "process": None,
                    "start_time": datetime.now().isoformat(),
                    "result": None,
                }

            deps = AnalysisDependencies(
                analysis_tasks=analysis_tasks,
                analysis_tasks_lock=analysis_tasks_lock,
                get_categories=get_categories,
                get_category_path=get_category_path,
                get_papers_in_category=get_papers_in_category,
                save_paper_metadata=save_paper_metadata,
            )

            thread = threading.Thread(
                target=analyze_paper_task,
                args=(
                    task_id,
                    paper_id,
                    pdf_path,
                    pdf_dir,
                    pdf_filename,
                    mineru_server_url,
                    openai_base_url,
                    openai_api_key,
                    system_prompt,
                    deps,
                ),
            )
            thread.daemon = True
            thread.start()

            return jsonify(
                {"success": True, "message": "解读任务已启动", "task_id": task_id}
            )

        except Exception as exc:  # noqa: BLE001
            print(f"启动解读任务失败: {exc}")
            import traceback

            traceback.print_exc()
            return (
                jsonify({"success": False, "error": f"启动解读任务失败: {str(exc)}"}),
                500,
            )

    @app.route("/api/paper/analyze/active", methods=["GET"])
    def api_get_active_analysis():
        """获取所有进行中的解读任务"""
        with analysis_tasks_lock:
            active_tasks = []
            for task_id, task_info in analysis_tasks.items():
                if task_info["status"] in ["queued", "running"]:
                    active_tasks.append(
                        {
                            "task_id": task_id,
                            "paper_id": task_info["paper_id"],
                            "status": task_info["status"],
                            "step": task_info.get("step"),
                            "start_time": task_info["start_time"],
                        }
                    )
            return jsonify({"success": True, "tasks": active_tasks})

    @app.route("/api/paper/analyze/<task_id>/logs", methods=["GET"])
    def api_get_analysis_logs(task_id):
        """获取解读任务的日志"""
        with analysis_tasks_lock:
            if task_id not in analysis_tasks:
                return jsonify({"success": False, "error": "任务不存在"}), 404

            task_info = analysis_tasks[task_id]
            with task_info["log_lock"]:
                logs = task_info["logs"].copy()

            return jsonify(
                {
                    "success": True,
                    "status": task_info["status"],
                    "step": task_info.get("step"),
                    "logs": logs,
                    "start_time": task_info["start_time"],
                    "result": task_info.get("result"),
                }
            )

    @app.route("/api/paper/analyze/<task_id>/cancel", methods=["POST"])
    def api_cancel_analysis(task_id):
        """取消解读任务"""
        with analysis_tasks_lock:
            if task_id not in analysis_tasks:
                return jsonify({"success": False, "error": "任务不存在"}), 404

            task_info = analysis_tasks[task_id]

            if task_info["status"] in ["completed", "failed", "cancelled"]:
                return (
                    jsonify({"success": False, "error": "任务已结束，无法取消"}),
                    400,
                )

            process = task_info.get("process")
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                except Exception as exc:  # noqa: BLE001
                    print(f"终止进程失败: {exc}")

            task_info["status"] = "cancelled"
            task_info["result"] = {"success": False, "error": "解读已取消"}

            return jsonify({"success": True, "message": "解读任务已取消"})

    @app.route("/api/paper/<paper_id>/analysis/result")
    def api_get_analysis_result(paper_id):
        """获取解读结果文件"""
        # 首先尝试从 paper_store 中查找论文（支持 _ReadingListTemp 目录）
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
        else:
            # 如果 paper_store 中找不到，使用递归搜索分类树
            categories = get_categories()

            def search_paper_recursive(node):
                category_path = get_category_path(categories, node["id"])
                if category_path:
                    papers = get_papers_in_category(node["id"], category_path)
                    for paper in papers:
                        if paper.id == paper_id:
                            return paper, category_path

                if "children" in node:
                    for child in node["children"]:
                        result = search_paper_recursive(child)
                        if result:
                            return result

                return None

            result = None
            for child in categories.get("children", []):
                result = search_paper_recursive(child)
                if result:
                    break

            if not result:
                return jsonify({"error": "论文未找到"}), 404

            paper, _ = result
        pdf_path = paper.file_path

        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDF文件不存在"}), 404

        pdf_dir = os.path.dirname(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")

        result_file = None
        if os.path.exists(outputs_dir):
            exact_result = os.path.join(outputs_dir, base_name, "vlm", "result.md")
            if os.path.exists(exact_result):
                result_file = exact_result
            else:
                for item in os.listdir(outputs_dir):
                    item_path = os.path.join(outputs_dir, item)
                    if os.path.isdir(item_path):
                        vlm_dir = os.path.join(item_path, "vlm")
                        if os.path.exists(vlm_dir):
                            potential_result = os.path.join(vlm_dir, "result.md")
                            if os.path.exists(potential_result):
                                result_file = potential_result
                                break

        if not result_file or not os.path.exists(result_file):
            return jsonify({"error": "解读结果文件不存在"}), 404

        try:
            with open(result_file, "r", encoding="utf-8") as f:
                content = f.read()
            return jsonify(
                {"success": True, "content": content, "file_path": result_file}
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"读取结果文件失败: {str(exc)}"}), 500

    @app.route("/api/paper/<paper_id>/analysis/image")
    def api_get_analysis_image(paper_id):
        """获取解读结果中的图片"""
        # 首先尝试从 paper_store 中查找论文（支持 _ReadingListTemp 目录）
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
        else:
            # 如果 paper_store 中找不到，使用递归搜索分类树
            categories = get_categories()

            def search_paper_recursive(node):
                category_path = get_category_path(categories, node["id"])
                if category_path:
                    papers = get_papers_in_category(node["id"], category_path)
                    for paper in papers:
                        if paper.id == paper_id:
                            return paper, category_path

                if "children" in node:
                    for child in node["children"]:
                        result = search_paper_recursive(child)
                        if result:
                            return result

                return None

            result = None
            for child in categories.get("children", []):
                result = search_paper_recursive(child)
                if result:
                    break

            if not result:
                return jsonify({"error": "论文未找到"}), 404

            paper, _ = result
        pdf_path = paper.file_path

        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDF文件不存在"}), 404

        image_path = request.args.get("path")
        if not image_path:
            return jsonify({"error": "未提供图片路径"}), 400

        pdf_dir = os.path.dirname(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")

        image_file = None
        if os.path.exists(outputs_dir):
            vlm_dir_specific = os.path.join(outputs_dir, base_name, "vlm")
            if os.path.exists(vlm_dir_specific):
                if image_path.startswith("images/"):
                    potential_image = os.path.join(vlm_dir_specific, image_path)
                else:
                    potential_image = os.path.join(
                        vlm_dir_specific, "images", image_path
                    )

                if os.path.exists(potential_image) and os.path.isfile(potential_image):
                    image_file = potential_image
            if not image_file:
                for item in os.listdir(outputs_dir):
                    item_path = os.path.join(outputs_dir, item)
                    if os.path.isdir(item_path):
                        vlm_dir = os.path.join(item_path, "vlm")
                        if os.path.exists(vlm_dir):
                            if image_path.startswith("images/"):
                                potential_image = os.path.join(vlm_dir, image_path)
                            else:
                                potential_image = os.path.join(
                                    vlm_dir, "images", image_path
                                )

                            if os.path.exists(potential_image) and os.path.isfile(
                                potential_image
                            ):
                                image_file = potential_image
                                break

        if not image_file or not os.path.exists(image_file):
            return jsonify({"error": "图片文件不存在"}), 404

        return send_file(image_file, mimetype="image/jpeg")
