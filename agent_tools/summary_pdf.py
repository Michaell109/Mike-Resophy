from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List

from core.base_paper import Paper

PaperList = List[Paper]
CategoryPath = List[str]


@dataclass
class AnalysisDependencies:
    analysis_tasks: Dict[str, Dict[str, Any]]
    analysis_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def analyze_paper_task(
    task_id: str,
    paper_id: str,
    pdf_path: str,
    pdf_dir: str,
    pdf_filename: str,
    mineru_server_url: str,
    openai_base_url: str,
    openai_api_key: str,
    system_prompt: str,
    deps: AnalysisDependencies,
) -> None:
    """后台AI解读任务 - 两步：PDF2MD -> LLM解读"""
    start_time = datetime.now()  # 记录开始时间
    with deps.analysis_tasks_lock:
        task_info = deps.analysis_tasks[task_id]
        task_info["status"] = "running"
        task_info["step"] = "pdf2md"
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None

    def read_output(pipe, label):
        """实时读取子进程输出"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    print(f"[{label}] {line}")
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
        except Exception as e:  # noqa: BLE001
            print(f"读取输出时出错: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["step"] = "pdf2md"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("第一步：开始将PDF解析为Markdown...")
                log_lines.append("=" * 50)

        os.chdir(pdf_dir)

        cmd = [
            "mineru",
            "-p",
            pdf_filename,
            "-o",
            "outputs",
            "-b",
            "vlm-http-client",
            "-u",
            mineru_server_url,
        ]

        print(f"执行PDF2MD命令: {' '.join(cmd)}")
        print(f"工作目录: {pdf_dir}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["process"] = process

        stdout_thread = threading.Thread(
            target=read_output, args=(process.stdout, "STDOUT")
        )
        stderr_thread = threading.Thread(
            target=read_output, args=(process.stderr, "STDERR")
        )
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        return_code = process.wait(timeout=3600)

        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

        if return_code != 0:
            raise Exception(f"PDF2MD失败 (退出码: {return_code})")

        base_name = os.path.splitext(pdf_filename)[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")

        pdf_output_dir = os.path.join(outputs_dir, base_name, "vlm")
        if not os.path.exists(pdf_output_dir):
            candidate = None
            for item in os.listdir(outputs_dir):
                item_path = os.path.join(outputs_dir, item)
                if os.path.isdir(item_path) and base_name in item:
                    vlm_dir = os.path.join(item_path, "vlm")
                    if os.path.exists(vlm_dir):
                        candidate = vlm_dir
                        break
            if candidate:
                pdf_output_dir = candidate

        if not pdf_output_dir or not os.path.exists(pdf_output_dir):
            raise Exception("未找到PDF解析输出目录")

        with log_lock:
            log_lines.append(f"找到输出目录: {pdf_output_dir}")

        vlm_items = os.listdir(pdf_output_dir)
        md_file = None
        for item in vlm_items:
            item_path = os.path.join(pdf_output_dir, item)
            if item == "images" and os.path.isdir(item_path):
                continue
            elif item.endswith(".md") and os.path.isfile(item_path):
                md_file = item_path
                continue
            else:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    with log_lock:
                        log_lines.append(f"删除目录: {item}")
                else:
                    os.remove(item_path)
                    with log_lock:
                        log_lines.append(f"删除文件: {item}")

        if not md_file:
            raise Exception("未找到生成的Markdown文件")

        with log_lock:
            log_lines.append("=" * 50)
            log_lines.append("第一步完成：PDF已解析为Markdown")
            log_lines.append(f"Markdown文件: {md_file}")
            log_lines.append("=" * 50)

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["step"] = "llm_analysis"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("第二步：开始LLM解读...")
                log_lines.append("=" * 50)

        with open(md_file, "r", encoding="utf-8") as f:
            markdown_content = f.read()

        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        try:
            models = client.models.list()
            model = models.data[0].id if models.data else None
            if not model:
                raise Exception("无法获取模型列表")
        except Exception as e:  # noqa: BLE001
            raise Exception(f"获取模型列表失败: {str(e)}") from e

        prompt = system_prompt.replace("<MARKDOWN>", markdown_content)
        messages = [{"role": "user", "content": prompt}]

        with log_lock:
            log_lines.append(f"使用模型: {model}")
            log_lines.append("开始调用LLM API...")

        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
        )

        result_content = chat_completion.choices[0].message.content

        result_file = os.path.join(pdf_output_dir, "result.md")
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(result_content)

        with log_lock:
            log_lines.append("=" * 50)
            log_lines.append("第二步完成：LLM解读完成")
            log_lines.append(f"结果文件: {result_file}")
            log_lines.append("=" * 50)

        categories = deps.get_categories()

        def search_and_update_paper(node):
            category_path = deps.get_category_path(categories, node["id"])
            if category_path:
                papers_list = deps.get_papers_in_category(node["id"], category_path)
                for paper in papers_list:
                    if paper.id == paper_id:
                        paper.mark_analysis_result(result_file)
                        deps.save_paper_metadata(pdf_path, paper)
                        return True
            if "children" in node:
                for child in node["children"]:
                    if search_and_update_paper(child):
                        return True
            return False

        for child in categories.get("children", []):
            if search_and_update_paper(child):
                break

        end_time = datetime.now()
        analysis_duration = int((end_time - start_time).total_seconds())

        categories = deps.get_categories()

        def search_and_update_analysis_time(node):
            category_path = deps.get_category_path(categories, node["id"])
            if category_path:
                papers = deps.get_papers_in_category(node["id"], category_path)
                for paper in papers:
                    if paper.id == paper_id:
                        paper.analysis_time = max(
                            getattr(paper, "analysis_time", 0), analysis_duration
                        )
                        path = paper.file_path
                        if path and os.path.exists(path):
                            deps.save_paper_metadata(path, paper)
                        return True
            if "children" in node:
                for child in node["children"]:
                    if search_and_update_analysis_time(child):
                        return True
            return False

        for child in categories.get("children", []):
            if search_and_update_analysis_time(child):
                break

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "completed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": True,
                "result_file": result_file,
                "markdown_file": md_file,
            }

    except subprocess.TimeoutExpired:
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "failed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": "解读超时",
            }
        if process:
            process.kill()
    except Exception as e:  # noqa: BLE001
        print(f"解读过程出错: {str(e)}")
        import traceback

        traceback.print_exc()
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "failed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": f"解读失败: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        os.chdir(original_cwd)
