from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store

PaperList = List[Paper]
CategoryPath = List[str]


@dataclass
class TranslationDependencies:
    translation_tasks: Dict[str, Dict[str, Any]]
    translation_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def translate_paper_task(
    task_id: str,
    paper_id: str,
    pdf_path: str,
    pdf_dir: str,
    pdf_filename: str,
    openai_model: str,
    openai_base_url: str,
    openai_api_key: str,
    deps: TranslationDependencies,
) -> None:
    """Background translation tasks"""
    start_time = datetime.now()  # Recording start time
    with deps.translation_tasks_lock:
        task_info = deps.translation_tasks[task_id]
        task_info["status"] = "running"
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None

    def read_output(pipe, label):
        """Read subprocess output in real time"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    print(f"[{label}] {line}")
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
        except Exception as e:  # noqa: BLE001
            print(f"Error while reading output: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        os.chdir(pdf_dir)
        cmd = [
            "babeldoc",
            "--openai",
            "--openai-model",
            openai_model,
            "--openai-base-url",
            openai_base_url,
            "--openai-api-key",
            openai_api_key,
            "--files",
            pdf_filename,
        ]

        print(f"Execute translation command: {' '.join(cmd)}")
        print(f"working directory: {pdf_dir}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        with deps.translation_tasks_lock:
            deps.translation_tasks[task_id]["process"] = process

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

        with deps.translation_tasks_lock:
            if return_code == 0:
                base_name = os.path.splitext(pdf_filename)[0]
                dual_file = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
                mono_file = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")

                if os.path.exists(dual_file):
                    if os.path.exists(mono_file):
                        os.remove(mono_file)

                    # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
                    entry = paper_store.get_entry(paper_id)
                    if entry:
                        paper = entry.paper
                        paper.mark_chinese_version(dual_file)
                        target_path = paper.file_path or pdf_path
                        if target_path:
                            deps.save_paper_metadata(target_path, paper)
                    else:
                        # if paper_store Not found in , use recursive search of classification tree
                        categories = deps.get_categories()

                        def search_and_update_paper(node):
                            category_path = deps.get_category_path(categories, node["id"])
                            if category_path:
                                papers = deps.get_papers_in_category(
                                    node["id"], category_path
                                )
                                for paper in papers:
                                    if paper.id == paper_id:
                                        paper.mark_chinese_version(dual_file)
                                        target_path = paper.file_path or pdf_path
                                        if target_path:
                                            deps.save_paper_metadata(target_path, paper)
                                        return True
                            if "children" in node:
                                for child in node["children"]:
                                    if search_and_update_paper(child):
                                        return True
                            return False

                        for child in categories.get("children", []):
                            if search_and_update_paper(child):
                                break

                    log_file = os.path.join(pdf_dir, f"{base_name}.translate.log")
                    try:
                        with open(log_file, "w", encoding="utf-8") as f:
                            f.write("\n".join(log_lines))
                    except Exception as e:  # noqa: BLE001
                        print(f"Failed to save log file: {e}")

                    end_time = datetime.now()
                    translation_duration = int((end_time - start_time).total_seconds())

                    # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
                    entry = paper_store.get_entry(paper_id)
                    if entry:
                        paper = entry.paper
                        paper.translation_time = max(
                            getattr(paper, "translation_time", 0),
                            translation_duration,
                        )
                        path = paper.file_path
                        if path and os.path.exists(path):
                            deps.save_paper_metadata(path, paper)
                    else:
                        # if paper_store Not found in , use recursive search of classification tree
                        categories = deps.get_categories()

                        def search_and_update_time(node):
                            category_path = deps.get_category_path(categories, node["id"])
                            if category_path:
                                papers = deps.get_papers_in_category(
                                    node["id"], category_path
                                )
                                for paper in papers:
                                    if paper.id == paper_id:
                                        paper.translation_time = max(
                                            getattr(paper, "translation_time", 0),
                                            translation_duration,
                                        )
                                        path = paper.file_path
                                        if path and os.path.exists(path):
                                            deps.save_paper_metadata(path, paper)
                                        return True
                            if "children" in node:
                                for child in node["children"]:
                                    if search_and_update_time(child):
                                        return True
                            return False

                        for child in categories.get("children", []):
                            if search_and_update_time(child):
                                break

                    deps.translation_tasks[task_id]["status"] = "completed"
                    deps.translation_tasks[task_id]["result"] = {
                        "success": True,
                        "chinese_version_path": dual_file,
                        "log_file": log_file,
                    }
                else:
                    deps.translation_tasks[task_id]["status"] = "failed"
                    deps.translation_tasks[task_id]["result"] = {
                        "success": False,
                        "error": "Translation file not generated",
                    }
            else:
                deps.translation_tasks[task_id]["status"] = "failed"
                deps.translation_tasks[task_id]["result"] = {
                    "success": False,
                    "error": f"Translation failed (exit code: {return_code})",
                }

    except subprocess.TimeoutExpired:
        with deps.translation_tasks_lock:
            deps.translation_tasks[task_id]["status"] = "failed"
            deps.translation_tasks[task_id]["result"] = {
                "success": False,
                "error": "Translation timeout",
            }
        if process:
            process.kill()
    except Exception as e:  # noqa: BLE001
        print(f"An error occurred during translation: {str(e)}")
        import traceback

        traceback.print_exc()
        with deps.translation_tasks_lock:
            deps.translation_tasks[task_id]["status"] = "failed"
            deps.translation_tasks[task_id]["result"] = {
                "success": False,
                "error": f"Translation failed: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        os.chdir(original_cwd)
