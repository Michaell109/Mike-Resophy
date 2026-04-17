"""
Related paper search module

Given a reference paper, search for related papers from 4 sources
in priority order: C(baseline methods) > B(citations/references) >
A(recommendations) > D(arxiv keyword search).

All sources except C require LLM-based relevance checking.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import arxiv
import requests


@dataclass
class CandidatePaper:
    title: str
    abstract: str = ""
    authors: str = ""
    arxiv_id: Optional[str] = None
    arxiv_url: Optional[str] = None
    pdf_url: Optional[str] = None
    source: str = ""  # "baseline", "citation", "recommendation", "keyword"
    relevance_score: int = 0  # 0=not relevant, 1=partially, 2=highly
    year: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "arxiv_id": self.arxiv_id,
            "arxiv_url": self.arxiv_url,
            "pdf_url": self.pdf_url,
            "source": self.source,
            "relevance_score": self.relevance_score,
            "year": self.year,
        }


@dataclass
class SearchProgress:
    status: str = "idle"  # idle, running, done, error
    current_step: str = ""
    found: int = 0
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    downloaded: int = 0
    total_downloaded: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "current_step": self.current_step,
            "found": self.found,
            "candidates": [c if isinstance(c, dict) else c.to_dict() for c in self.candidates],
            "downloaded": self.downloaded,
            "total_downloaded": self.total_downloaded,
            "error": self.error,
        }


# Active search tasks: task_id -> (SearchProgress, thread, stop_event)
_search_tasks: Dict[str, Tuple[SearchProgress, threading.Thread, threading.Event]] = {}


def _get_semantic_scholar_paper_id(
    arxiv_id: Optional[str] = None, title: Optional[str] = None
) -> Optional[str]:
    """Look up Semantic Scholar paper ID by arxiv_id or title."""
    try:
        if arxiv_id:
            url = f"https://api.semanticscholar.org/graph/v1/paper/ArXiv:{arxiv_id}?fields=paperId"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("paperId")
        if title:
            query = title[:200]
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(query)}&limit=3&fields=paperId,title"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", []):
                    if item.get("title", "").lower().strip() == title.lower().strip():
                        return item.get("paperId")
                # Fallback: return first result if any
                if data.get("data"):
                    return data["data"][0].get("paperId")
    except Exception as e:
        print(f"[RelativePaper] Semantic Scholar lookup failed: {e}")
    return None


def _fetch_citations_and_references(
    s2_paper_id: str,
) -> Tuple[List[CandidatePaper], List[CandidatePaper]]:
    """Fetch citations and references from Semantic Scholar."""
    citations: List[CandidatePaper] = []
    references: List[CandidatePaper] = []

    for endpoint, target_list, label in [
        ("citations", citations, "citation"),
        ("references", references, "reference"),
    ]:
        try:
            url = (
                f"https://api.semanticscholar.org/graph/v1/paper/{s2_paper_id}/{endpoint}"
                f"?fields=title,abstract,authors,year,externalIds,isInfluential"
                f"&limit=100"
            )
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                print(f"[RelativePaper] S2 {endpoint} API returned {resp.status_code}")
                continue

            data = resp.json()
            for item in data.get("data", []):
                # S2 citations endpoint wraps in "citedPaper", references in "citedPaper"
                paper_data = item.get("citedPaper", item)
                if not paper_data or not paper_data.get("title"):
                    continue

                ext_ids = paper_data.get("externalIds", {}) or {}
                arxiv_id = ext_ids.get("ArXiv")
                authors_list = paper_data.get("authors", [])
                authors_str = ", ".join(a.get("name", "") for a in authors_list if a.get("name"))

                cp = CandidatePaper(
                    title=paper_data.get("title", ""),
                    abstract=paper_data.get("abstract", "") or "",
                    authors=authors_str,
                    arxiv_id=arxiv_id,
                    arxiv_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
                    source=label,
                    year=str(paper_data.get("year", "")) if paper_data.get("year") else "",
                )
                target_list.append(cp)
        except Exception as e:
            print(f"[RelativePaper] Fetch {endpoint} failed: {e}")

    return citations, references


def _fetch_recommendations(s2_paper_id: str) -> List[CandidatePaper]:
    """Fetch recommended papers from Semantic Scholar."""
    candidates: List[CandidatePaper] = []
    try:
        url = (
            f"https://api.semanticscholar.org/recommendations/v1/papers/{s2_paper_id}"
            f"?fields=title,abstract,authors,year,externalIds&limit=50"
        )
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            print(f"[RelativePaper] S2 recommendations API returned {resp.status_code}")
            return candidates

        data = resp.json()
        for paper_data in data.get("recommendedPapers", []):
            if not paper_data or not paper_data.get("title"):
                continue

            ext_ids = paper_data.get("externalIds", {}) or {}
            arxiv_id = ext_ids.get("ArXiv")
            authors_list = paper_data.get("authors", [])
            authors_str = ", ".join(a.get("name", "") for a in authors_list if a.get("name"))

            cp = CandidatePaper(
                title=paper_data.get("title", ""),
                abstract=paper_data.get("abstract", "") or "",
                authors=authors_str,
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
                source="recommendation",
                year=str(paper_data.get("year", "")) if paper_data.get("year") else "",
            )
            candidates.append(cp)
    except Exception as e:
        print(f"[RelativePaper] Fetch recommendations failed: {e}")
    return candidates


def _extract_baseline_methods_with_llm(
    abstract: str,
    analysis_text: Optional[str],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
) -> List[str]:
    """Use LLM to extract baseline/comparison method names from paper."""
    prompt = """I will give you a paper's abstract (and optionally its AI analysis). You need to extract the names of baseline/comparison methods mentioned in the paper. These are methods that the paper compares against experimentally.

Output the result as a JSON array of method name strings. Only include specific method names (like "RT-2", "SayCan", "VoxPoser"), not general categories. If no baseline methods are found, return an empty array [].

Examples:
- If the abstract mentions "We compare our method against RT-2, SayCan, and VoxPoser", output: ["RT-2", "SayCan", "VoxPoser"]
- If no comparison methods are mentioned, output: []

Do not include any explanation, only output the JSON array.

The input is:
"""
    content = f"Abstract: {abstract}\n"
    if analysis_text:
        content += f"\nAI Analysis:\n{analysis_text[:3000]}"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
        response = client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": prompt + content}],
            temperature=0.1,
            max_tokens=500,
        )
        result_text = response.choices[0].message.content.strip()

        # Parse JSON
        json_match = re.search(r"\[.*\]", result_text, re.DOTALL)
        if json_match:
            methods = json.loads(json_match.group())
            if isinstance(methods, list):
                return [m for m in methods if isinstance(m, str) and m.strip()]
    except Exception as e:
        print(f"[RelativePaper] LLM extract baselines failed: {e}")
    return []


def _check_relevance_with_llm(
    ref_abstract: str,
    candidates: List[CandidatePaper],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    batch_size: int = 10,
) -> List[CandidatePaper]:
    """Use LLM to check relevance of candidate papers against the reference paper.

    Returns only highly relevant papers (score=2).
    """
    if not candidates:
        return []

    prompt_template = """I will give you a reference paper's abstract and a list of candidate papers. For each candidate, rate its relevance to the reference paper:
- 2: Highly relevant (same problem, same domain, or directly comparable approach)
- 1: Partially relevant (related domain but different problem or approach)
- 0: Not relevant (different research direction)

Reference paper abstract:
{ref_abstract}

Candidate papers:
{candidates_text}

Output a JSON array of objects with "index" (0-based) and "score" (0/1/2) for each candidate. Example:
[{{"index": 0, "score": 2}}, {{"index": 1, "score": 0}}]

Only output the JSON array, no explanation.
"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
        results: List[CandidatePaper] = []

        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            candidates_text = ""
            for idx, cp in enumerate(batch):
                candidates_text += f"\n[{idx}] Title: {cp.title}\nAbstract: {cp.abstract[:500]}\n"

            full_prompt = prompt_template.format(
                ref_abstract=ref_abstract[:1000], candidates_text=candidates_text
            )

            response = client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            result_text = response.choices[0].message.content.strip()

            json_match = re.search(r"\[.*\]", result_text, re.DOTALL)
            if json_match:
                scores = json.loads(json_match.group())
                score_map = {}
                for item in scores:
                    if isinstance(item, dict):
                        score_map[item.get("index", -1)] = item.get("score", 0)

                for idx, cp in enumerate(batch):
                    cp.relevance_score = score_map.get(idx, 0)
                    if cp.relevance_score >= 2:
                        results.append(cp)
            else:
                # If parsing fails, keep all as unverified
                for cp in batch:
                    cp.relevance_score = 1
                    results.append(cp)

        return results
    except Exception as e:
        print(f"[RelativePaper] LLM relevance check failed: {e}")
        # On failure, keep all candidates as partially relevant
        for cp in candidates:
            cp.relevance_score = 1
        return candidates


def _search_arxiv_by_method(method_name: str, max_results: int = 3) -> List[CandidatePaper]:
    """Search arxiv for a specific method name."""
    candidates: List[CandidatePaper] = []
    try:
        client = arxiv.Client(page_size=max_results, delay_seconds=1.0, num_retries=2)
        search = arxiv.Search(
            query=f'ti:"{method_name}"',
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        for result in client.results(search):
            arxiv_id = result.entry_id.split("/abs/")[-1]
            authors = ", ".join(a.name for a in result.authors)
            cp = CandidatePaper(
                title=result.title.replace("\n", " ").strip(),
                abstract=result.summary.replace("\n", " ").strip() if result.summary else "",
                authors=authors,
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=result.pdf_url,
                source="baseline",
                relevance_score=2,  # Baseline methods are directly accepted
            )
            # Extract year from published date
            if result.published:
                cp.year = str(result.published.year)
            candidates.append(cp)
    except Exception as e:
        print(f"[RelativePaper] arxiv search for '{method_name}' failed: {e}")
    return candidates


def _search_arxiv_by_keywords(
    keywords: List[str],
    title: str,
    max_results: int = 20,
) -> List[CandidatePaper]:
    """Search arxiv using keywords from the paper."""
    candidates: List[CandidatePaper] = []
    try:
        # Build query from keywords and title keywords
        query_parts = []
        for kw in keywords[:5]:
            query_parts.append(f'ti:"{kw}"')

        # Also add significant words from title
        title_words = [w for w in re.findall(r"\w+", title) if len(w) > 4 and w.lower() not in {"based", "using", "towards", "learning", "method", "approach", "model", "framework", "system", "novel", "improved", "efficient", "general"}]
        for w in title_words[:3]:
            query_parts.append(f'ti:"{w}"')

        query = " OR ".join(query_parts) if query_parts else title[:100]

        client = arxiv.Client(page_size=max_results, delay_seconds=2.0, num_retries=2)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        one_year_ago = datetime.now().year - 1
        for result in client.results(search):
            arxiv_id = result.entry_id.split("/abs/")[-1]
            authors = ", ".join(a.name for a in result.authors)
            cp = CandidatePaper(
                title=result.title.replace("\n", " ").strip(),
                abstract=result.summary.replace("\n", " ").strip() if result.summary else "",
                authors=authors,
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=result.pdf_url,
                source="keyword",
                year=str(result.published.year) if result.published else "",
            )
            # Filter: only keep papers from recent 1 year
            if result.published and result.published.year >= one_year_ago:
                candidates.append(cp)
    except Exception as e:
        print(f"[RelativePaper] arxiv keyword search failed: {e}")
    return candidates


def _download_pdf(url: str, target_path: str) -> bool:
    """Download a PDF from URL to target path."""
    try:
        # Convert to export.arxiv.org to avoid rate limits
        download_url = url
        if "arxiv.org/pdf/" in download_url:
            download_url = download_url.replace("arxiv.org/pdf/", "export.arxiv.org/pdf/")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/pdf,*/*",
            "Referer": "https://arxiv.org/",
        }
        resp = requests.get(download_url, headers=headers, timeout=60, stream=True, allow_redirects=True)
        if resp.status_code == 200:
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            # Verify file is valid PDF
            if os.path.getsize(target_path) < 1024:
                os.remove(target_path)
                return False
            return True
    except Exception as e:
        print(f"[RelativePaper] Download failed for {url}: {e}")
        if os.path.exists(target_path):
            os.remove(target_path)
    return False


def _sanitize_filename(text: str) -> str:
    """Make a string safe for use as a filename."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:150] if cleaned else "untitled"


def search_related_papers(
    task_id: str,
    ref_paper_id: str,
    ref_paper_data: Dict[str, Any],
    target_dir: str,
    target_count: int,
    sources: List[str],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    save_paper_metadata_fn: Callable,
    paper_store: Any,
    category_id: str,
    category_path: List[str],
    stop_event: threading.Event,
    progress: SearchProgress,
) -> None:
    """
    Main search function. Runs in a background thread.

    Args:
        task_id: Unique task identifier
        ref_paper_id: Reference paper ID
        ref_paper_data: Reference paper dict (with title, abstract, etc.)
        target_dir: Directory to save found papers
        target_count: Desired number of results
        sources: List of enabled sources ["baseline", "citation", "recommendation", "keyword"]
        llm_base_url/api_key/model: LLM config for relevance checking
        save_paper_metadata_fn: Function to save paper metadata
        paper_store: PaperStore instance
        category_id: Category ID for the new papers
        category_path: Category path for the new papers
        stop_event: Threading event to signal stop
        progress: SearchProgress object to update
    """
    try:
        progress.status = "running"

        ref_title = ref_paper_data.get("title", "")
        ref_abstract = ref_paper_data.get("abstract", "")
        ref_arxiv_id = ref_paper_data.get("arxiv_id")
        ref_keywords = ref_paper_data.get("keywords", "")

        # Parse keywords string to list
        keyword_list = []
        if ref_keywords:
            if isinstance(ref_keywords, list):
                keyword_list = ref_keywords
            elif isinstance(ref_keywords, str):
                keyword_list = [k.strip() for k in ref_keywords.split(",") if k.strip()]

        all_candidates: List[CandidatePaper] = []
        seen_titles: Set[str] = set()  # For dedup (case-insensitive)
        seen_arxiv_ids: Set[str] = set()

        # Exclude the reference paper itself
        if ref_arxiv_id:
            seen_arxiv_ids.add(ref_arxiv_id)
        seen_titles.add(ref_title.lower().strip())

        def _add_unique(candidates: List[CandidatePaper]) -> List[CandidatePaper]:
            """Filter duplicates from candidate list."""
            unique = []
            for cp in candidates:
                key = cp.arxiv_id or cp.title.lower().strip()
                if cp.arxiv_id and cp.arxiv_id in seen_arxiv_ids:
                    continue
                if cp.title.lower().strip() in seen_titles:
                    continue
                if cp.arxiv_id:
                    seen_arxiv_ids.add(cp.arxiv_id)
                seen_titles.add(cp.title.lower().strip())
                unique.append(cp)
            return unique

        # ==================== Source C: Baseline Methods ====================
        if "baseline" in sources and not stop_event.is_set():
            progress.current_step = "Extracting baseline methods..."
            print(f"[RelativePaper] Source C: Extracting baseline methods for '{ref_title[:50]}'")

            # Also try to read analysis result for more context
            analysis_text = None
            analysis_path = ref_paper_data.get("analysis_result_path")
            if analysis_path and os.path.exists(analysis_path):
                try:
                    with open(analysis_path, "r", encoding="utf-8") as f:
                        analysis_text = f.read()[:3000]
                except Exception:
                    pass

            method_names = _extract_baseline_methods_with_llm(
                ref_abstract, analysis_text, llm_base_url, llm_api_key, llm_model
            )
            print(f"[RelativePaper] Extracted baseline methods: {method_names}")

            for method_name in method_names:
                if stop_event.is_set():
                    break
                found = _search_arxiv_by_method(method_name, max_results=3)
                unique = _add_unique(found)
                all_candidates.extend(unique)
                print(f"[RelativePaper] Baseline '{method_name}': found {len(unique)} papers")

            progress.found = len(all_candidates)
            progress.candidates = [c.to_dict() for c in all_candidates]

        # ==================== Source B: Citations & References ====================
        s2_paper_id = None  # Initialize at this scope so Source A can reuse it
        if "citation" in sources and not stop_event.is_set():
            progress.current_step = "Fetching citations & references..."
            print(f"[RelativePaper] Source B: Fetching citations & references")

            s2_paper_id = _get_semantic_scholar_paper_id(arxiv_id=ref_arxiv_id, title=ref_title)
            if s2_paper_id:
                citations, references = _fetch_citations_and_references(s2_paper_id)
                combined = citations + references
                unique = _add_unique(combined)
                print(f"[RelativePaper] S2: {len(unique)} unique citation/reference papers")

                # Only keep papers with arxiv_id (we need to download PDF)
                arxiv_candidates = [cp for cp in unique if cp.arxiv_id]
                if arxiv_candidates:
                    progress.current_step = "Checking relevance of citations..."
                    relevant = _check_relevance_with_llm(
                        ref_abstract, arxiv_candidates,
                        llm_base_url, llm_api_key, llm_model,
                    )
                    all_candidates.extend(relevant)
                    print(f"[RelativePaper] After relevance check: {len(relevant)} relevant")
            else:
                print(f"[RelativePaper] Could not find paper on Semantic Scholar")

            progress.found = len(all_candidates)
            progress.candidates = [c.to_dict() for c in all_candidates]

        # ==================== Source A: Recommendations ====================
        if "recommendation" in sources and not stop_event.is_set():
            progress.current_step = "Fetching recommendations..."
            print(f"[RelativePaper] Source A: Fetching recommendations")

            if not s2_paper_id:
                s2_paper_id = _get_semantic_scholar_paper_id(arxiv_id=ref_arxiv_id, title=ref_title)

            if s2_paper_id:
                recs = _fetch_recommendations(s2_paper_id)
                unique = _add_unique(recs)
                print(f"[RelativePaper] S2 recommendations: {len(unique)} unique papers")

                arxiv_candidates = [cp for cp in unique if cp.arxiv_id]
                if arxiv_candidates:
                    progress.current_step = "Checking relevance of recommendations..."
                    relevant = _check_relevance_with_llm(
                        ref_abstract, arxiv_candidates,
                        llm_base_url, llm_api_key, llm_model,
                    )
                    all_candidates.extend(relevant)
                    print(f"[RelativePaper] After relevance check: {len(relevant)} relevant")
            else:
                print(f"[RelativePaper] Could not find paper on Semantic Scholar for recommendations")

            progress.found = len(all_candidates)
            progress.candidates = [c.to_dict() for c in all_candidates]

        # ==================== Source D: Arxiv Keyword Search ====================
        if "keyword" in sources and not stop_event.is_set():
            progress.current_step = "Searching arxiv by keywords..."
            print(f"[RelativePaper] Source D: Keyword search on arxiv")

            kw_candidates = _search_arxiv_by_keywords(keyword_list, ref_title, max_results=30)
            unique = _add_unique(kw_candidates)
            print(f"[RelativePaper] Arxiv keyword search: {len(unique)} unique papers")

            if unique:
                progress.current_step = "Checking relevance of keyword results..."
                relevant = _check_relevance_with_llm(
                    ref_abstract, unique,
                    llm_base_url, llm_api_key, llm_model,
                )
                all_candidates.extend(relevant)
                print(f"[RelativePaper] After relevance check: {len(relevant)} relevant")

            progress.found = len(all_candidates)
            progress.candidates = [c.to_dict() for c in all_candidates]

        # ==================== Dedup & Truncate ====================
        # Already deduped via seen_titles/seen_arxiv_ids during collection
        # Sort by relevance score (desc), then by source priority
        source_priority = {"baseline": 0, "citation": 1, "recommendation": 2, "keyword": 3}
        all_candidates.sort(
            key=lambda c: (-c.relevance_score, source_priority.get(c.source, 99))
        )

        # Truncate to target count (but don't force — if fewer, that's fine)
        if len(all_candidates) > target_count:
            all_candidates = all_candidates[:target_count]

        progress.found = len(all_candidates)
        progress.candidates = [c.to_dict() for c in all_candidates]

        # ==================== Download PDFs ====================
        if stop_event.is_set():
            progress.status = "done"
            return

        os.makedirs(target_dir, exist_ok=True)
        downloaded = 0

        for i, cp in enumerate(all_candidates):
            if stop_event.is_set():
                break
            if not cp.arxiv_id or not cp.pdf_url:
                print(f"[RelativePaper] Skip (no arxiv_id): {cp.title[:50]}")
                continue

            progress.current_step = f"Downloading {i+1}/{len(all_candidates)}: {cp.title[:40]}"
            progress.downloaded = i
            progress.total_downloaded = downloaded

            safe_title = _sanitize_filename(cp.title)
            pdf_filename = f"{safe_title}.pdf"
            target_path = os.path.join(target_dir, pdf_filename)

            # Handle duplicate filenames
            counter = 1
            while os.path.exists(target_path):
                pdf_filename = f"{safe_title}_{counter}.pdf"
                target_path = os.path.join(target_dir, pdf_filename)
                counter += 1

            if _download_pdf(cp.pdf_url, target_path):
                # Create paper metadata
                from resophy.core.base_paper import Paper

                paper = Paper(
                    filename=pdf_filename,
                    original_filename=pdf_filename,
                    file_path=target_path,
                    upload_date=datetime.now().isoformat(),
                    title=cp.title,
                    authors=cp.authors,
                    abstract=cp.abstract,
                    arxiv_id=cp.arxiv_id,
                    arxiv_url=cp.arxiv_url,
                    arxiv_published_date=cp.year or None,
                    year=cp.year,
                    upload_source="relative_paper_search",
                )
                # Mark the source in extra
                paper.extra["relative_paper_source"] = cp.source
                paper.extra["relative_paper_ref_id"] = ref_paper_id

                # Save metadata
                save_paper_metadata_fn(target_path, paper)

                # Register in paper store
                paper_store.upsert(paper, category_id=category_id, category_path=category_path)

                downloaded += 1
                print(f"[RelativePaper] Downloaded: {cp.title[:50]}")
            else:
                print(f"[RelativePaper] Download failed: {cp.title[:50]}")

        progress.downloaded = len(all_candidates)
        progress.total_downloaded = downloaded
        progress.current_step = f"Done. Found {progress.found} candidates, downloaded {downloaded} papers."
        progress.status = "done"

    except Exception as e:
        print(f"[RelativePaper] Search failed: {e}")
        import traceback
        traceback.print_exc()
        progress.status = "error"
        progress.error = str(e)


def start_search(
    task_id: str,
    ref_paper_id: str,
    ref_paper_data: Dict[str, Any],
    target_dir: str,
    target_count: int,
    sources: List[str],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    save_paper_metadata_fn: Callable,
    paper_store: Any,
    category_id: str,
    category_path: List[str],
) -> SearchProgress:
    """Start a background search task."""
    progress = SearchProgress()
    stop_event = threading.Event()

    thread = threading.Thread(
        target=search_related_papers,
        args=(
            task_id, ref_paper_id, ref_paper_data, target_dir,
            target_count, sources,
            llm_base_url, llm_api_key, llm_model,
            save_paper_metadata_fn, paper_store,
            category_id, category_path,
            stop_event, progress,
        ),
        daemon=True,
    )

    _search_tasks[task_id] = (progress, thread, stop_event)
    thread.start()
    return progress


def get_search_progress(task_id: str) -> Optional[Dict[str, Any]]:
    """Get progress of a search task."""
    if task_id in _search_tasks:
        progress, thread, stop_event = _search_tasks[task_id]
        result = progress.to_dict()
        # Clean up completed tasks after returning
        if progress.status in ("done", "error"):
            # Keep for a while so the client can read the final state
            pass
        return result
    return None


def cancel_search(task_id: str) -> bool:
    """Cancel a running search task."""
    if task_id in _search_tasks:
        _, _, stop_event = _search_tasks[task_id]
        stop_event.set()
        return True
    return False


def cleanup_task(task_id: str) -> None:
    """Remove a completed task from memory."""
    _search_tasks.pop(task_id, None)
