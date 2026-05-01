"""
CSV Import route
Process the function of importing papers from CSV files
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

import requests
from flask import Flask, jsonify, request

from resophy.core.base_paper import Paper
from resophy.core.paper_store import PaperStore
from resophy.tools.basic_tools.paper_repository import (
    _find_source_paper_for_inherit,
    generate_paper_filename,
    inherit_chinese_and_analysis,
)

# Task state storage
csv_import_tasks: Dict[str, Dict[str, Any]] = {}
csv_import_tasks_lock = threading.Lock()


# ============================================================================
# Link resolution helpers
# ============================================================================


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """Extract arXiv ID from URL"""
    patterns = [
        r"arxiv\.org/pdf/([\d.]+(?:v\d+)?)",
        r"arxiv\.org/abs/([\d.]+(?:v\d+)?)",
        r"^([\d.]+(?:v\d+)?)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            if "v" in arxiv_id:
                arxiv_id = arxiv_id.split("v")[0]
            return arxiv_id
    return None


def _resolve_openalex(openalex_url: str) -> Optional[Dict[str, Any]]:
    """Resolve OpenAlex URL to PDF download info

    Returns dict with pdf_url, or None if resolution fails.
    """
    # Extract work ID (e.g., W4404350116)
    match = re.search(r"(W\d+)", openalex_url)
    if not match:
        print(f"[CSV Import] Cannot extract OpenAlex work ID from: {openalex_url}")
        return None

    work_id = match.group(1)
    api_url = f"https://api.openalex.org/{work_id}"

    try:
        resp = requests.get(api_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        pdf_url = (data.get("open_access", {}) or {}).get("oa_url") \
            or ((data.get("primary_location") or {}).get("pdf_url"))

        if not pdf_url:
            print(f"[CSV Import] No PDF URL found for OpenAlex {work_id}")
            return None

        return {"pdf_url": pdf_url}

    except Exception as exc:
        print(f"[CSV Import] OpenAlex API failed for {work_id}: {exc}")
        return None


def _resolve_arxiv(arxiv_url: str) -> Optional[Dict[str, Any]]:
    """Resolve arXiv URL to PDF download info

    Returns dict with pdf_urls (list of candidates) and arxiv_id, or None if resolution fails.
    """
    arxiv_id = _extract_arxiv_id_from_url(arxiv_url)
    if not arxiv_id:
        print(f"[CSV Import] Cannot extract arXiv ID from: {arxiv_url}")
        return None

    # Try export.arxiv.org first, then arxiv.org
    pdf_urls = [
        f"https://export.arxiv.org/pdf/{arxiv_id}.pdf",
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    ]
    return {"pdf_urls": pdf_urls, "arxiv_id": arxiv_id}


def _resolve_link(link: str) -> Optional[Dict[str, Any]]:
    """Resolve a link (OpenAlex or arXiv) to PDF download info"""
    link_lower = link.lower()
    if "openalex.org" in link_lower:
        return _resolve_openalex(link)
    elif "arxiv.org" in link_lower:
        return _resolve_arxiv(link)
    else:
        print(f"[CSV Import] Unsupported link type: {link}")
        return None


def _download_pdf(pdf_urls, timeout: int = 60) -> Optional[bytes]:
    """Download PDF content from URL(s), trying each candidate in order"""
    from resophy.tools.basic_tools.parallel_downloader import RateLimitError

    if isinstance(pdf_urls, str):
        pdf_urls = [pdf_urls]

    for pdf_url in pdf_urls:
        try:
            print(f"[CSV Import] Downloading PDF: {pdf_url}")
            resp = requests.get(pdf_url, timeout=timeout, stream=True)
            if resp.status_code == 429:
                raise RateLimitError(f"429 from {pdf_url}")
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                print(f"[CSV Import] Warning: Content-Type not PDF: {content_type}")
            content = resp.content
            print(f"[CSV Import] Downloaded {len(content)} bytes from {pdf_url}")
            return content
        except RateLimitError:
            raise
        except Exception as exc:
            print(f"[CSV Import] Download failed from {pdf_url}: {exc}")
            continue

    return None


# ============================================================================
# Background task worker
# ============================================================================


def _csv_import_task(
    task_id: str,
    csv_rows: List[Dict[str, str]],
    category_id: str,
    category_path: List[str],
    category_folder: str,
    reading_list_file: str,
    paper_store: PaperStore,
    save_paper_metadata: Callable[[str, Any], None],
):
    """Background worker: process each CSV row, resolve link, download PDF, import"""
    imported_papers: List[Dict[str, str]] = []
    skipped_papers: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []

    def _load_reading_list() -> List[str]:
        try:
            with open(reading_list_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("papers", [])
        except Exception:
            return []

    def _save_reading_list(paper_ids: List[str]) -> None:
        try:
            with open(reading_list_file, "w", encoding="utf-8") as f:
                json.dump({"papers": paper_ids}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _add_to_reading_list(paper_id: str) -> None:
        paper_ids = _load_reading_list()
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
            _save_reading_list(paper_ids)

    total = len(csv_rows)
    with csv_import_tasks_lock:
        csv_import_tasks[task_id]["status"] = "running"
        csv_import_tasks[task_id]["total"] = total

    # Phase 1: Sequential pre-processing — resolve links, check duplicates, build download tasks
    from resophy.tools.basic_tools.parallel_downloader import (
        parallel_download, DownloadTask, RateLimitError, _extract_domain,
    )

    rows_to_download = []  # list of dicts with resolved info

    for idx, row in enumerate(csv_rows):
        # Check cancellation
        with csv_import_tasks_lock:
            if csv_import_tasks[task_id]["status"] == "cancelled":
                print("[CSV Import] Task cancelled")
                break

        # Check pause: block until resumed or cancelled
        while True:
            with csv_import_tasks_lock:
                task_status = csv_import_tasks[task_id]["status"]
            if task_status == "paused":
                time.sleep(0.5)
                continue
            break

        link = (row.get("Link") or "").strip()
        title = (row.get("Title") or "").strip()

        # Update progress
        with csv_import_tasks_lock:
            csv_import_tasks[task_id]["progress"] = idx + 1
            csv_import_tasks[task_id]["current_paper"] = title[:60] if title else link[:60]

        if not link:
            errors.append({"link": "", "title": title, "reason": "Empty link"})
            continue

        # Resolve link to get arxiv_id for duplicate detection
        arxiv_id = _extract_arxiv_id_from_url(link)

        # Duplicate detection: check if paper already exists by arxiv_id or title
        existing_entry = paper_store.find_duplicate(arxiv_id=arxiv_id, title=title)
        if existing_entry and existing_entry.paper.file_path and os.path.exists(existing_entry.paper.file_path):
            existing_paper = existing_entry.paper
            # Determine target filename
            csv_year = (row.get("Year") or "").strip()
            pdf_filename = generate_paper_filename(
                title=title, year=csv_year, arxiv_id=arxiv_id
            )

            file_path = os.path.join(category_folder, pdf_filename)

            # Handle filename collisions
            counter = 1
            original_filename = pdf_filename
            while os.path.exists(file_path):
                name, ext = os.path.splitext(original_filename)
                pdf_filename = f"{name}_{counter}{ext}"
                file_path = os.path.join(category_folder, pdf_filename)
                counter += 1

            # Copy existing PDF and JSON to target folder
            try:
                shutil.copy2(existing_paper.file_path, file_path)
                existing_json = os.path.splitext(existing_paper.file_path)[0] + ".json"
                if os.path.exists(existing_json):
                    shutil.copy2(existing_json, os.path.splitext(file_path)[0] + ".json")
            except Exception as exc:
                errors.append({"link": link, "title": title, "reason": f"Copy failed: {exc}"})
                continue

            # Create new Paper object based on existing, with new id and path
            paper = Paper(
                id=str(uuid.uuid4()),
                filename=pdf_filename,
                original_filename=pdf_filename,
                file_path=file_path,
                upload_date=datetime.now().isoformat(),
                title=existing_paper.title or title or os.path.splitext(pdf_filename)[0],
                authors=existing_paper.authors or (row.get("Authors") or "").strip(),
                abstract=existing_paper.abstract or (row.get("Abstract") or "").strip(),
                year=existing_paper.year or (row.get("Year") or "").strip(),
                keywords=existing_paper.keywords or (row.get("Keywords") or "").strip(),
                affiliation=existing_paper.affiliation or (row.get("Institutions") or "").strip(),
                journal=existing_paper.journal or (row.get("Venue") or "").strip(),
                arxiv_id=existing_paper.arxiv_id or arxiv_id,
                arxiv_url=existing_paper.arxiv_url or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None),
                github=existing_paper.github,
                homepage=existing_paper.homepage,
                upload_source="csv_import",
            )

            # Save metadata for the new copy
            save_paper_metadata(file_path, paper)

            # Register to paper_store
            paper_store.upsert(
                paper,
                category_id=category_id,
                category_path=category_path,
            )

            # Inherit Chinese version / AI interpretation from existing paper
            if existing_paper.has_chinese_version or existing_paper.has_analysis_result:
                target_base = os.path.splitext(pdf_filename)[0]
                if inherit_chinese_and_analysis(existing_paper, category_folder, target_base, paper):
                    paper_store.upsert(
                        paper, category_id=category_id, category_path=category_path
                    )
                    save_paper_metadata(file_path, paper)

            # Add to reading list
            _add_to_reading_list(paper.id)

            skipped_papers.append({"id": paper.id, "title": paper.title})
            print(f"[CSV Import] Skipped duplicate ({idx + 1}/{total}): {title[:50]}...")
            continue

        # Not a duplicate — resolve link to PDF URL
        resolved = _resolve_link(link)
        if not resolved:
            errors.append({"link": link, "title": title, "reason": "Cannot resolve PDF URL"})
            continue

        # Get PDF URL(s) - OpenAlex returns single url, arXiv returns list
        pdf_urls = resolved.get("pdf_urls") or resolved.get("pdf_url")
        if not arxiv_id:
            arxiv_id = resolved.get("arxiv_id")

        # Determine domain for rate limiting
        first_url = pdf_urls[0] if isinstance(pdf_urls, list) and pdf_urls else (pdf_urls if isinstance(pdf_urls, str) else "")
        domain = _extract_domain(first_url) or "export.arxiv.org"

        rows_to_download.append({
            "idx": idx, "row": row, "link": link, "title": title,
            "arxiv_id": arxiv_id, "pdf_urls": pdf_urls, "domain": domain,
        })

    # Phase 2: Parallel download
    if rows_to_download:
        download_tasks = [
            DownloadTask(
                task_id=f"csv_{r['idx']}_{r['arxiv_id'] or r['title'][:20]}",
                fn=lambda urls=r["pdf_urls"]: _download_pdf(urls),
                domain=r["domain"],
            )
            for r in rows_to_download
        ]

        def _on_progress(completed, total_dl, tid):
            with csv_import_tasks_lock:
                if task_id in csv_import_tasks:
                    csv_import_tasks[task_id]["progress"] = completed
                    csv_import_tasks[task_id]["current_paper"] = f"Downloading {completed}/{total_dl}"

        download_results = parallel_download(
            tasks=download_tasks,
            max_workers=3,
            on_progress=_on_progress,
        )

        # Phase 3: Sequential post-processing
        for r, result in zip(rows_to_download, download_results):
            row = r["row"]
            link = r["link"]
            title = r["title"]
            arxiv_id = r["arxiv_id"]

            if not result.success or not result.result:
                errors.append({"link": link, "title": title, "reason": f"PDF download failed: {result.error or 'unknown'}"})
                continue

            pdf_content = result.result

            # Determine filename
            csv_year = (row.get("Year") or "").strip()
            pdf_filename = generate_paper_filename(
                title=title, year=csv_year, arxiv_id=arxiv_id
            )

            file_path = os.path.join(category_folder, pdf_filename)

            # Handle filename collisions
            counter = 1
            original_filename = pdf_filename
            while os.path.exists(file_path):
                name, ext = os.path.splitext(original_filename)
                pdf_filename = f"{name}_{counter}{ext}"
                file_path = os.path.join(category_folder, pdf_filename)
                counter += 1

            # Save PDF file
            try:
                with open(file_path, "wb") as f:
                    f.write(pdf_content)
            except Exception as exc:
                errors.append({"link": link, "title": title, "reason": f"File save failed: {exc}"})
                continue

            # Create Paper object with CSV metadata
            paper = Paper(
                id=str(uuid.uuid4()),
                filename=pdf_filename,
                original_filename=pdf_filename,
                file_path=file_path,
                upload_date=datetime.now().isoformat(),
                title=title or os.path.splitext(pdf_filename)[0],
                authors=(row.get("Authors") or "").strip(),
                abstract=(row.get("Abstract") or "").strip(),
                year=(row.get("Year") or "").strip(),
                keywords=(row.get("Keywords") or "").strip(),
                affiliation=(row.get("Institutions") or "").strip(),
                journal=(row.get("Venue") or "").strip(),
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                upload_source="csv_import",
            )

            # Save metadata
            save_paper_metadata(file_path, paper)

            # Register to paper_store
            paper_store.upsert(
                paper,
                category_id=category_id,
                category_path=category_path,
            )

            # Inherit Chinese version / AI interpretation from existing paper
            source = _find_source_paper_for_inherit(
                paper_store, arxiv_id=arxiv_id, title=paper.title, exclude_paper_id=paper.id
            )
            if source:
                target_base = os.path.splitext(pdf_filename)[0]
                if inherit_chinese_and_analysis(source, category_folder, target_base, paper):
                    paper_store.upsert(
                        paper, category_id=category_id, category_path=category_path
                    )
                    save_paper_metadata(file_path, paper)

            # Add to reading list
            _add_to_reading_list(paper.id)

            imported_papers.append({"id": paper.id, "title": paper.title})
            print(f"[CSV Import] Imported: {title[:50]}...")

    # Finalize
    with csv_import_tasks_lock:
        csv_import_tasks[task_id]["status"] = "completed"
        csv_import_tasks[task_id]["imported_papers"] = imported_papers
        csv_import_tasks[task_id]["skipped_papers"] = skipped_papers
        csv_import_tasks[task_id]["errors"] = errors
        csv_import_tasks[task_id]["imported_count"] = len(imported_papers)
        csv_import_tasks[task_id]["skipped_count"] = len(skipped_papers)
        csv_import_tasks[task_id]["error_count"] = len(errors)

    print(f"[CSV Import] Done: {len(imported_papers)} imported, {len(skipped_papers)} skipped (duplicate), {len(errors)} errors")


# ============================================================================
# Route registration
# ============================================================================


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


class CreateCategoryFolderFn(Protocol):
    def __call__(self, category_path: list[str]) -> str: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


def register_csv_import_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
    reading_list_temp_dir: str,
    paper_store: PaperStore,
) -> None:

    @app.route("/api/csv-import/start", methods=["POST"])
    def api_csv_import_start():
        """Start CSV import task"""
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files["file"]
        category_id = request.form.get("category_id")

        if not file.filename or not file.filename.lower().endswith(".csv"):
            return jsonify({"success": False, "error": "Please upload a CSV file"}), 400

        if not category_id:
            return jsonify({"success": False, "error": "No category selected"}), 400

        # Determine category path and folder
        if category_id == "reading_list_temp":
            category_path = ["Root", "_ReadingListTemp"]
            category_folder = reading_list_temp_dir
        else:
            categories = get_categories()
            category_path = get_category_path(categories, category_id)
            if not category_path:
                return jsonify({"success": False, "error": "Category not found"}), 404
            category_folder = create_category_folder(category_path[1:])

        # Parse CSV
        try:
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)
            csv_rows = [row for row in reader if row.get("Link", "").strip()]
        except Exception as exc:
            return jsonify({"success": False, "error": f"CSV parsing failed: {exc}"}), 400

        if not csv_rows:
            return jsonify({"success": False, "error": "No valid links found in CSV"}), 400

        # Create task
        task_id = f"csv_import_{int(time.time() * 1000)}"

        with csv_import_tasks_lock:
            csv_import_tasks[task_id] = {
                "task_id": task_id,
                "status": "pending",
                "progress": 0,
                "total": len(csv_rows),
                "current_paper": "",
                "imported_papers": [],
                "skipped_papers": [],
                "errors": [],
                "imported_count": 0,
                "skipped_count": 0,
                "error_count": 0,
                "created_at": datetime.now().isoformat(),
            }

        # Start background thread
        thread = threading.Thread(
            target=_csv_import_task,
            args=(
                task_id,
                csv_rows,
                category_id,
                category_path,
                category_folder,
                reading_list_file,
                paper_store,
                save_paper_metadata,
            ),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "task_id": task_id,
            "total": len(csv_rows),
        })

    @app.route("/api/csv-import/status/<task_id>", methods=["GET"])
    def api_csv_import_status(task_id: str):
        """Get CSV import task status"""
        with csv_import_tasks_lock:
            if task_id not in csv_import_tasks:
                return jsonify({"success": False, "error": "Task not found"}), 404

            task = csv_import_tasks[task_id]
            return jsonify({
                "success": True,
                "task": {
                    "task_id": task["task_id"],
                    "status": task["status"],
                    "progress": task["progress"],
                    "total": task["total"],
                    "current_paper": task["current_paper"],
                    "imported_count": task.get("imported_count", 0),
                    "skipped_count": task.get("skipped_count", 0),
                    "error_count": task.get("error_count", 0),
                    "errors": task.get("errors", []),
                },
            })

    @app.route("/api/csv-import/cancel/<task_id>", methods=["POST"])
    def api_csv_import_cancel(task_id: str):
        """Cancel CSV import task"""
        with csv_import_tasks_lock:
            if task_id not in csv_import_tasks:
                return jsonify({"success": False, "error": "Task not found"}), 404

            task = csv_import_tasks[task_id]
            if task["status"] in ["completed", "failed", "cancelled"]:
                return jsonify({"success": False, "error": "Task already ended"}), 400

            task["status"] = "cancelled"

        return jsonify({"success": True, "message": "Task cancelled"})

    @app.route("/api/csv-import/pause/<task_id>", methods=["POST"])
    def api_csv_import_pause(task_id: str):
        """Pause CSV import task"""
        with csv_import_tasks_lock:
            if task_id not in csv_import_tasks:
                return jsonify({"success": False, "error": "Task not found"}), 404

            task = csv_import_tasks[task_id]
            if task["status"] != "running":
                return jsonify({"success": False, "error": "Task is not running"}), 400

            task["status"] = "paused"

        return jsonify({"success": True, "message": "Task paused"})

    @app.route("/api/csv-import/resume/<task_id>", methods=["POST"])
    def api_csv_import_resume(task_id: str):
        """Resume CSV import task"""
        with csv_import_tasks_lock:
            if task_id not in csv_import_tasks:
                return jsonify({"success": False, "error": "Task not found"}), 404

            task = csv_import_tasks[task_id]
            if task["status"] != "paused":
                return jsonify({"success": False, "error": "Task is not paused"}), 400

            task["status"] = "running"

        return jsonify({"success": True, "message": "Task resumed"})
