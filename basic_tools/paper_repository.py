from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Iterable, List, Optional

from core.base_paper import Paper
from core.paper_store import paper_store


def get_paper_json_path(pdf_path: str) -> str:
    return os.path.splitext(pdf_path)[0] + ".json"


def save_paper_metadata(pdf_path: str, paper_data) -> None:
    if isinstance(paper_data, Paper):
        data_to_save = paper_data.to_dict()
    else:
        data_to_save = paper_data or {}

    json_path = get_paper_json_path(pdf_path)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"已保存论文元数据: {json_path}")
    except Exception as exc:
        print(f"保存论文元数据失败: {exc}")


def load_paper_metadata(pdf_path: str) -> Optional[Paper]:
    json_path = get_paper_json_path(pdf_path)
    try:
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                return Paper.from_dict(json.load(f))
    except Exception as exc:
        print(f"加载论文元数据失败: {exc}")
    return None


def delete_paper_files(pdf_path: str) -> None:
    json_path = get_paper_json_path(pdf_path)

    if os.path.exists(pdf_path):
        os.remove(pdf_path)
        print(f"已删除PDF文件: {pdf_path}")

    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"已删除JSON文件: {json_path}")

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_dir = os.path.dirname(pdf_path)
    zh_dual = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
    zh_mono = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")
    for f in (zh_dual, zh_mono):
        try:
            if os.path.exists(f):
                os.remove(f)
                print(f"已删除中文翻译PDF: {f}")
        except Exception as exc:
            print(f"删除中文翻译PDF失败: {f}, {exc}")

    outputs_dir = os.path.join(pdf_dir, "outputs")
    if os.path.exists(outputs_dir):
        for item in os.listdir(outputs_dir):
            item_path = os.path.join(outputs_dir, item)
            if os.path.isdir(item_path) and base_name in item:
                shutil.rmtree(item_path)
                print(f"已删除AI解读输出目录: {item_path}")
        try:
            if not os.listdir(outputs_dir):
                os.rmdir(outputs_dir)
                print(f"已删除空的outputs目录: {outputs_dir}")
        except Exception:
            pass


def scan_papers_in_directory(
    directory_path: str,
    *,
    category_id: str,
    category_path: Iterable[str],
) -> List[Paper]:
    category_path_list = list(category_path)
    paper_store.mark_category_initialized(category_id, category_path_list)
    papers: List[Paper] = []
    if not os.path.exists(directory_path):
        return papers

    for filename in os.listdir(directory_path):
        if not filename.lower().endswith(".pdf"):
            continue

        if filename.endswith(".zh.dual.pdf") or filename.endswith(".zh.mono.pdf"):
            continue

        pdf_path = os.path.join(directory_path, filename)
        paper = load_paper_metadata(pdf_path)

        if paper:
            paper.sync_filesystem(pdf_path, filename)
        else:
            paper = Paper.create_default(
                filename=filename,
                file_path=pdf_path,
                original_filename=filename,
                upload_date=datetime.fromtimestamp(
                    os.path.getctime(pdf_path)
                ).isoformat(),
            )

        paper.mark_starred(getattr(paper, "starred", False))

        base_name = os.path.splitext(filename)[0]
        dual_file = os.path.join(directory_path, f"{base_name}.zh.dual.pdf")
        paper.mark_chinese_version(dual_file if os.path.exists(dual_file) else None)
        if not paper.has_chinese_version:
            paper.use_chinese_version = False

        pdf_dir = os.path.dirname(pdf_path)
        outputs_dir = os.path.join(pdf_dir, "outputs")
        analysis_result_path = None
        if os.path.exists(outputs_dir):
            for item in os.listdir(outputs_dir):
                item_path = os.path.join(outputs_dir, item)
                if os.path.isdir(item_path) and base_name in item:
                    vlm_dir = os.path.join(item_path, "vlm")
                    if os.path.exists(vlm_dir):
                        result_file = os.path.join(vlm_dir, "result.md")
                        if os.path.exists(result_file):
                            analysis_result_path = result_file
                            break
        paper.mark_analysis_result(analysis_result_path)

        registered = paper_store.upsert(
            paper, category_id=category_id, category_path=category_path_list
        )
        save_paper_metadata(pdf_path, registered)
        papers.append(registered)

    return papers


def get_papers_in_category(
    upload_folder: str, category_id: str, category_path: List[str]
) -> List[Paper]:
    if not category_path:
        return []
    if paper_store.is_category_initialized(category_id):
        return paper_store.list_by_category(category_id)
    directory_path = os.path.join(upload_folder, *category_path[1:])
    return scan_papers_in_directory(
        directory_path, category_id=category_id, category_path=category_path
    )
