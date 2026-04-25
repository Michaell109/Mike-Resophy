from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Iterable, List, Optional

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store


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
        # Remove successfully saved log output to reduce console noise (only output on errors)
    except Exception as exc:
        print(f"Failed to save article metadata: {exc}")


def load_paper_metadata(pdf_path: str) -> Optional[Paper]:
    json_path = get_paper_json_path(pdf_path)
    try:
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                return Paper.from_dict(json.load(f))
    except Exception as exc:
        print(f"Failed to load article metadata: {exc}")
    return None


def delete_paper_files(pdf_path: str) -> None:
    json_path = get_paper_json_path(pdf_path)

    if os.path.exists(pdf_path):
        os.remove(pdf_path)
        print(f"DeletedPDFdocument: {pdf_path}")

    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"DeletedJSONdocument: {json_path}")

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_dir = os.path.dirname(pdf_path)
    zh_dual = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
    zh_mono = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")
    for f in (zh_dual, zh_mono):
        try:
            if os.path.exists(f):
                os.remove(f)
                print(f"Chinese translation removedPDF: {f}")
        except Exception as exc:
            print(f"Remove Chinese translationPDFfail: {f}, {exc}")

    outputs_dir = os.path.join(pdf_dir, "outputs")
    if os.path.exists(outputs_dir):
        for item in os.listdir(outputs_dir):
            item_path = os.path.join(outputs_dir, item)
            if os.path.isdir(item_path) and base_name in item:
                shutil.rmtree(item_path)
                print(f"DeletedAIInterpret the output directory: {item_path}")
        try:
            if not os.listdir(outputs_dir):
                os.rmdir(outputs_dir)
                print(f"Empty deletedoutputsTable of contents: {outputs_dir}")
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


def inherit_chinese_and_analysis(
    source_paper: Paper,
    target_dir: str,
    target_base_name: str,
    target_paper: Paper,
) -> bool:
    """Copy Chinese version and AI interpretation from source_paper to target location.

    After copying, re-marks has_chinese_version / has_analysis_result on target_paper.

    Returns True if anything was copied.
    """
    copied = False
    source_base = os.path.splitext(os.path.basename(source_paper.file_path))[0] if source_paper.file_path else ""

    # Chinese version: copy .zh.dual.pdf (and .zh.mono.pdf if present)
    if source_paper.has_chinese_version and source_paper.chinese_version_path:
        source_dir = os.path.dirname(source_paper.chinese_version_path)
        for suffix in [".zh.dual.pdf", ".zh.mono.pdf"]:
            src = os.path.join(source_dir, f"{source_base}{suffix}")
            dst = os.path.join(target_dir, f"{target_base_name}{suffix}")
            if os.path.exists(src) and src != dst:
                try:
                    shutil.copy2(src, dst)
                    copied = True
                except Exception as exc:
                    print(f"[Inherit] Failed to copy {src}: {exc}")

    # AI interpretation: copy outputs/<base_name>* directory
    if source_paper.has_analysis_result and source_paper.analysis_result_path:
        source_dir = os.path.dirname(source_paper.file_path)
        source_outputs = os.path.join(source_dir, "outputs")
        if os.path.exists(source_outputs):
            target_outputs = os.path.join(target_dir, "outputs")
            os.makedirs(target_outputs, exist_ok=True)
            for item in os.listdir(source_outputs):
                item_full = os.path.join(source_outputs, item)
                if os.path.isdir(item_full) and source_base in item:
                    new_item_name = item.replace(source_base, target_base_name)
                    dst_item = os.path.join(target_outputs, new_item_name)
                    if item_full != dst_item:
                        try:
                            shutil.copytree(item_full, dst_item, dirs_exist_ok=True)
                            copied = True
                        except Exception as exc:
                            print(f"[Inherit] Failed to copy outputs/{item}: {exc}")

    # Re-mark on target paper
    dual_file = os.path.join(target_dir, f"{target_base_name}.zh.dual.pdf")
    target_paper.mark_chinese_version(dual_file if os.path.exists(dual_file) else None)

    target_outputs = os.path.join(target_dir, "outputs")
    analysis_result_path = None
    if os.path.exists(target_outputs):
        for item in os.listdir(target_outputs):
            item_path = os.path.join(target_outputs, item)
            if os.path.isdir(item_path) and target_base_name in item:
                vlm_dir = os.path.join(item_path, "vlm")
                if os.path.exists(vlm_dir):
                    result_file = os.path.join(vlm_dir, "result.md")
                    if os.path.exists(result_file):
                        analysis_result_path = result_file
                        break
    target_paper.mark_analysis_result(analysis_result_path)

    if copied:
        print(f"[Inherit] Copied Chinese version/AI interpretation to {target_base_name}")
    return copied


def _find_source_paper_for_inherit(
    paper_store,
    arxiv_id: Optional[str],
    title: Optional[str],
    exclude_paper_id: Optional[str] = None,
) -> Optional[Paper]:
    """Find an existing paper with Chinese version or AI interpretation to inherit from.

    Searches by arxiv_id first, then by title. Skips the paper with exclude_paper_id.
    Returns the first paper that has either has_chinese_version or has_analysis_result.
    """
    entry = paper_store.find_duplicate(arxiv_id=arxiv_id, title=title)
    if entry and entry.paper.id != exclude_paper_id:
        p = entry.paper
        if (p.has_chinese_version and p.chinese_version_path and os.path.exists(p.chinese_version_path)) or \
           (p.has_analysis_result and p.analysis_result_path and os.path.exists(p.analysis_result_path)):
            return p
    return None


def refresh_paper_status(paper: Paper) -> None:
    """Check the file system and update the translation and interpretation status of the paper"""
    if not paper.file_path or not os.path.exists(paper.file_path):
        return
    
    pdf_dir = os.path.dirname(paper.file_path)
    base_name = os.path.splitext(os.path.basename(paper.file_path))[0]
    
    # Check translation files
    dual_file = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
    paper.mark_chinese_version(dual_file if os.path.exists(dual_file) else None)
    
    # Check interpretation results
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


def get_papers_in_category(
    upload_folder: str, category_id: str, category_path: List[str]
) -> List[Paper]:
    if not category_path:
        return []
    if paper_store.is_category_initialized(category_id):
        papers = paper_store.list_by_category(category_id)
        # Refresh status of each paper (check file system)
        for paper in papers:
            old_has_chinese = paper.has_chinese_version
            old_has_analysis = paper.has_analysis_result
            refresh_paper_status(paper)
            # If the status changes, save to JSON document
            if (paper.has_chinese_version != old_has_chinese or 
                paper.has_analysis_result != old_has_analysis):
                if paper.file_path and os.path.exists(paper.file_path):
                    save_paper_metadata(paper.file_path, paper)
        return papers
    directory_path = os.path.join(upload_folder, *category_path[1:])
    return scan_papers_in_directory(
        directory_path, category_id=category_id, category_path=category_path
    )
