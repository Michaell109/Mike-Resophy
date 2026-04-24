"""
Related paper search module

Given a reference paper, search for related papers from 4 sources
in priority order: C(baseline methods) > B(citations/references) >
A(recommendations) > D(arxiv keyword search).

Source C uses citation-based parsing from the PDF-to-markdown intermediate
file to extract baseline method names and map them to reference papers,
eliminating the need for LLM-based extraction and arXiv title search.
All other sources require LLM-based relevance checking.
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


# ---- Global Semantic Scholar rate limiter ----
# S2 unauthenticated limit: ~1 req/s, ~100 req/5min
# A single session-level lock ensures we never exceed 1 req/s.
_s2_lock = threading.Lock()
_s2_last_call = 0.0
_S2_MIN_INTERVAL = 1.1  # seconds between S2 calls


def _s2_get(url: str, **kwargs) -> requests.Response:
    """Rate-limited GET for Semantic Scholar API."""
    global _s2_last_call
    with _s2_lock:
        elapsed = time.time() - _s2_last_call
        if elapsed < _S2_MIN_INTERVAL:
            time.sleep(_S2_MIN_INTERVAL - elapsed)
        _s2_last_call = time.time()
    resp = requests.get(url, **kwargs)
    # If 429, backoff and retry once
    if resp.status_code == 429:
        with _s2_lock:
            time.sleep(3)
            _s2_last_call = time.time()
        resp = requests.get(url, **kwargs)
    return resp


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
    # Enhanced info for UI display
    matched_methods: int = 0      # Number of baseline methods found in paper
    resolved_methods: int = 0     # Number of methods successfully resolved to papers
    unresolved_methods: List[str] = field(default_factory=list)  # Method names that couldn't be resolved

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "current_step": self.current_step,
            "found": self.found,
            "candidates": [c if isinstance(c, dict) else c.to_dict() for c in self.candidates],
            "downloaded": self.downloaded,
            "total_downloaded": self.total_downloaded,
            "error": self.error,
            "matched_methods": self.matched_methods,
            "resolved_methods": self.resolved_methods,
            "unresolved_methods": self.unresolved_methods,
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
            resp = _s2_get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("paperId")
        if title:
            query = title[:200]
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(query)}&limit=3&fields=paperId,title"
            resp = _s2_get(url, timeout=15)
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
            resp = _s2_get(url, timeout=20)
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
        resp = _s2_get(url, timeout=20)
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


@dataclass
class _RefEntry:
    """A parsed reference entry from the paper's References section."""
    number: int  # Reference number (e.g., 27 from [27])
    title: str  # Paper title
    authors: str  # Author string (e.g., "Kim et al.")
    year: str  # Publication year


def _find_pdf2md_path(ref_paper_data: Dict[str, Any]) -> Optional[str]:
    """Locate the PDF-to-markdown intermediate file for the reference paper."""
    pdf_path = ref_paper_data.get("file_path")
    if not pdf_path or not os.path.exists(pdf_path):
        return None

    try:
        from resophy.tools.agent_tools.bilingual_translate import find_mineru_markdown
        return find_mineru_markdown(pdf_path)
    except Exception:
        # Fallback: reconstruct path manually
        pdf_dir = os.path.dirname(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")
        if not os.path.exists(outputs_dir):
            return None

        # Try exact path
        exact_md = os.path.join(outputs_dir, base_name, "vlm", f"{base_name}.md")
        if os.path.exists(exact_md):
            return exact_md

        # Search for any vlm directory
        for item in os.listdir(outputs_dir):
            item_path = os.path.join(outputs_dir, item)
            if os.path.isdir(item_path):
                vlm_dir = os.path.join(item_path, "vlm")
                if os.path.exists(vlm_dir):
                    for f in os.listdir(vlm_dir):
                        if f.endswith(".md") and f != "result.md":
                            return os.path.join(vlm_dir, f)
        return None


def _parse_references_section(md_content: str) -> Dict[int, _RefEntry]:
    """Parse the References section of a paper's markdown to build number→entry mapping.

    Handles two reference formats:
    1. Numbered: [N] Author1, Author2, ... Title. Venue, year.
    2. Unnumbered: Author1, Author2, ... Title. Venue, year. (each entry on its own line)
    """
    ref_map: Dict[int, _RefEntry] = {}

    # Find References section (could be # References, ## References, # REFERENCES, etc.)
    ref_match = re.search(
        r"^#{1,3}\s*(References|REFERENCES|Bibliography|参考文献)\s*$",
        md_content,
        re.MULTILINE | re.IGNORECASE,
    )
    if not ref_match:
        return ref_map

    # Find where the References section ends (next # header or end of file)
    ref_start = ref_match.end()
    next_header = re.search(r"^#{1,3}\s+", md_content[ref_start:], re.MULTILINE)
    if next_header:
        ref_section = md_content[ref_start:ref_start + next_header.start()]
    else:
        ref_section = md_content[ref_start:]

    # Try numbered format: [N] Author1, Author2, ... Title. Venue, year.
    numbered_pattern = re.compile(r"^\[(\d+)\]\s*(.+?)(?:\s{2,}|\n|$)", re.MULTILINE)
    numbered_matches = list(numbered_pattern.finditer(ref_section))

    if numbered_matches:
        for m in numbered_matches:
            num = int(m.group(1))
            text = m.group(2).strip()
            # Clean up: join lines that were broken across newlines
            text = re.sub(r"\n\s+", " ", text)
            entry = _parse_single_reference(text, num)
            if entry:
                ref_map[num] = entry
        return ref_map

    # Unnumbered format: each reference is on its own line or paragraph
    # Try multiple splitting strategies:
    # 1. Single newline (each line is a reference) — most common for PDF-to-markdown
    # 2. Double newline (paragraph breaks) — if single lines seem too long (merged)
    # 3. Merge lines for multi-line references

    # Try single-line split first
    single_entries = [line.strip() for line in ref_section.strip().split("\n") if line.strip()]

    # Try double-newline split
    dbl_entries = re.split(r"\n\s*\n", ref_section.strip())
    dbl_entries = [e.strip() for e in dbl_entries if e.strip()]

    # Heuristic: use the split that gives more entries and each entry looks like a reference
    # (starts with a capitalized name or organization)
    def _count_valid_entries(entries: List[str]) -> int:
        count = 0
        for e in entries:
            e_stripped = e.strip()
            if not e_stripped or len(e_stripped) < 20:
                continue
            # A reference should have a year
            if re.search(r"\b(?:19|20)\d{2}\b", e_stripped):
                count += 1
        return count

    single_valid = _count_valid_entries(single_entries)
    dbl_valid = _count_valid_entries(dbl_entries)

    if single_valid >= dbl_valid:
        entries = single_entries
    else:
        entries = dbl_entries

    # If still too few, try merging lines that don't start with a capitalized name
    if len(entries) < 3:
        entries = []
        current = ""
        for line in ref_section.strip().split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if re.match(r"^[A-Z]", line_stripped) and current:
                entries.append(current)
                current = line_stripped
            else:
                current += " " + line_stripped
        if current:
            entries.append(current)

    for idx, entry_text in enumerate(entries):
        # Clean up: join broken lines within a single entry
        entry_text = re.sub(r"\n\s+", " ", entry_text).strip()
        if not entry_text or len(entry_text) < 20:
            continue

        entry = _parse_single_reference(entry_text, idx + 1)
        if entry:
            ref_map[idx + 1] = entry

    return ref_map


def _parse_single_reference(text: str, number: int) -> Optional[_RefEntry]:
    """Parse a single reference entry text into a _RefEntry."""
    if not text or len(text) < 10:
        return None

    title = ""
    authors = ""
    year = ""

    # Year extraction
    year_match = re.search(r"\b((?:19|20)\d{2})[a-z]?\s*(?:\.|$|\n)", text)
    if not year_match:
        year_match = re.search(r"\b((?:19|20)\d{2})[a-z]?\b", text)
    if year_match:
        year = year_match.group(1)

    # Strategy: find the title by looking for common patterns
    # 1. Title after "et al." marker
    # 2. Title after a period that follows author names
    # 3. Title is typically the segment containing meaningful words before "arXiv", "In Proceedings", "IEEE", etc.

    # Try: Authors et al. Title. Venue, year.
    et_al_match = re.match(r"^(.*?et\s+al\.?)\.?\s+", text, re.IGNORECASE)
    if et_al_match:
        authors = et_al_match.group(1).strip()
        rest = text[et_al_match.end():]
        # Title is from here until "arXiv", "In ", "Proceedings", "IEEE", "Advances", "The ", "Journal", etc.
        title_end = re.search(
            r"(?:arXiv|In\s|Proceedings|IEEE|Advances\s|The\s+[A-Z]|Journal|Conference|preprint|url\s*=|URL\s*=|http)",
            rest, re.IGNORECASE
        )
        if title_end and title_end.start() > 5:
            title = rest[:title_end.start()].strip().rstrip(".,;:")
        else:
            # Fallback: take up to first period followed by a space and capital
            period_match = re.search(r"\.\s+[A-Z(]", rest)
            if period_match and period_match.start() > 5:
                title = rest[:period_match.start()].strip().rstrip(".,;:")
            else:
                title = rest[:min(len(rest), 150)].strip().rstrip(".,;:")
    else:
        # No "et al." - try to find author boundary by looking for period after short segments
        # Author names are typically short segments separated by commas, ending with a period
        # Then the title follows
        # Pattern: "FirstName LastName, FirstName LastName, and FirstName LastName. Title..."
        author_end = re.match(
            r"^(.*?(?:and\s+[A-Z][a-z]+\s+[A-Z][a-z]+|[A-Z][a-z]+\s+[A-Z][a-z]+))\.\s+",
            text
        )
        if author_end:
            authors = author_end.group(1).strip()
            rest = text[author_end.end():]
            title_end = re.search(
                r"(?:arXiv|In\s|Proceedings|IEEE|Advances\s|The\s+[A-Z]|Journal|Conference|preprint)",
                rest, re.IGNORECASE
            )
            if title_end and title_end.start() > 5:
                title = rest[:title_end.start()].strip().rstrip(".,;:")
            else:
                period_match = re.search(r"\.\s+[A-Z(]", rest)
                if period_match and period_match.start() > 5:
                    title = rest[:period_match.start()].strip().rstrip(".,;:")
                else:
                    title = rest[:min(len(rest), 150)].strip().rstrip(".,;:")
        else:
            # Last resort: try to find title as the first sentence-like segment
            # Skip past initial all-caps or organization names
            # Look for a segment that starts with a capital and has multiple words
            # before "arXiv" or a venue indicator
            whole_match = re.search(
                r"(?:^|\.\s)([A-Z][A-Za-z0-9_\-\s:]+?)(?:\.\s|arXiv|In\s|Proceedings|IEEE)",
                text
            )
            if whole_match:
                title = whole_match.group(1).strip().rstrip(".,;:")
            else:
                # Give up on structured parsing - just take the longest segment
                # that looks like a title (has mixed case, multiple words)
                segments = re.split(r"\.\s+", text)
                if segments:
                    # The title is usually the longest meaningful segment
                    title = max(segments, key=lambda s: len(s) if len(s) > 10 else 0).strip().rstrip(".,;:")

    if not title or len(title) < 3:
        return None

    return _RefEntry(
        number=number,
        title=title,
        authors=authors,
        year=year,
    )


def _extract_experiment_section(md_content: str) -> str:
    """Extract the experiment/results section from the paper markdown."""
    # Find experiment section header (various formats)
    exp_match = re.search(
        r"^#{1,3}\s*(\d+\.?\s*)?(Experiments?|Results?|Experimental\s+Results?|Evaluation|实验)",
        md_content,
        re.MULTILINE | re.IGNORECASE,
    )
    if not exp_match:
        return ""

    start = exp_match.end()

    # Find the next major section that's NOT a subsection (## but not ###)
    # Look for sections like Discussion, Conclusion, Limitations, Related Work, Acknowledgments, References
    next_section = re.search(
        r"^#{1,3}\s*(\d+\.?\s*)?(Discussion|Conclusion|Limitation|Related\s+Work|Acknowledgment|Reference|Appendix|Future\s+Work|总结|讨论|局限|致谢|参考文献)",
        md_content[start:],
        re.MULTILINE | re.IGNORECASE,
    )

    if next_section:
        end = start + next_section.start()
    else:
        end = len(md_content)

    return md_content[start:end]


def _extract_method_citations_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract method names and their citation markers from experiment text.

    Returns a list of dicts, each with:
      - "name": method name string
      - "ref_numbers": list of reference numbers (from [N] citations)
      - "ref_author_year": list of (author, year) tuples (from (Author, Year) citations)
    """
    results = []
    seen_methods = set()

    def _is_valid_method_name(name: str) -> bool:
        """Check if a string looks like a valid method/model name."""
        name = name.strip()
        if len(name) < 2 or len(name) > 60:
            return False
        # Must contain at least one letter (Latin or Greek)
        if not re.search(r"[A-Za-zΑ-Ωα-ωπ]", name):
            return False
        # Reject if starts with common non-method words
        reject_prefixes = (
            "we ", "our ", "the ", "this ", "that ", "a ", "an ",
            "in ", "on ", "for ", "with ", "from ", "to ", "by ",
            "is ", "are ", "was ", "were ", "has ", "have ", "had ",
            "using ", "based ", "via ", "through ", "over ",
            "such ", "both ", "all ", "each ", "some ",
            "not ", "and ", "but ", "or ", "nor ",
            "when ", "where ", "which ", "while ",
            "these ", "those ", "their ", "its ",
            "also ", "even ", "only ", "just ",
            "than ", "then ", "more ", "most ",
            "does ", "does", "how ", "why ", "what ",
            "can ", "will ", "may ", "might ",
            "et al", "figure", "table", "section",
            "appendix", "chapter",
        )
        name_lower = name.lower()
        for prefix in reject_prefixes:
            if name_lower.startswith(prefix):
                return False
        # Reject if looks like a sentence (contains too many common words)
        common_words = {"we", "our", "the", "is", "are", "was", "were", "has", "have",
                        "this", "that", "which", "with", "from", "for", "that", "than"}
        words = name_lower.split()
        if len(words) > 4:
            common_count = sum(1 for w in words if w in common_words)
            if common_count > len(words) * 0.4:
                return False
        # Reject if name is just lowercase words (probably not a method name)
        if name[0].islower() and not re.search(r"\d", name):
            return False
        return True

    def _clean_method_name(name: str) -> str:
        """Clean up a method name by removing trailing noise."""
        name = name.strip()
        # Remove trailing common words
        name = re.sub(
            r"\s+(and|or|the|a|an|of|in|on|for|with|from|to|by|as|vs|versus|compared|against|baseline|method|model|approach|policy|framework|algorithm|system|architecture|variant|version|series|family|et\s+al)$",
            "", name, flags=re.IGNORECASE
        ).strip()
        # Remove trailing punctuation
        name = name.rstrip(".,;: ")
        return name

    # Pattern 0: LaTeX math method names like $\pi _ { 0 . 5 }$ (Author, Year)
    # These appear in PDF-to-markdown as LaTeX formulas
    p0 = re.compile(
        r"\$\\?(?:pi|π)[\s_]*\{?\s*([\d.]+)\s*\}?\$"
        r"\s*\(([^)]+?(?:19|20)\d{2}[a-z]?[^)]*?)\)",
    )

    # Pattern 1: MethodName [N] or MethodName [N1, N2, ...]
    # Method names are capitalized noun phrases, typically 1-4 words
    # e.g., "Diffusion Policy [17]", "OpenVLA [27]", "π0[7]"
    p1 = re.compile(
        r"([A-Z$π][A-Za-z0-9_\-\.\s]{0,40}?)"
        r"\s*\[(\d+(?:\s*,\s*\d+)*)\]"
    )

    # Pattern 2: MethodName (Author et al., Year)
    # Restrict method name to capitalized short phrases (1-4 words, no sentence patterns)
    p2 = re.compile(
        r"([A-Z$π][A-Za-z0-9_\-\s]{0,35}?)"
        r"\s*\(([^)]+?(?:et\s+al\.?[^)]*?)(?:19|20)\d{2}[a-z]?[^)]*?)\)",
    )
    # Also try: MethodName (Author and Author, Year) without "et al."
    p2b = re.compile(
        r"([A-Z$π][A-Za-z0-9_\-\s]{0,35}?)"
        r"\s*\(([^)]+?(?:19|20)\d{2}[a-z]?[^)]*?)\)"
    )

    # Extract LaTeX math method names (e.g., $\pi _ { 0 . 5 }$ (Author, Year))
    for m in p0.finditer(text):
        subscript = m.group(1).replace(" ", "").strip()
        method_name = f"π{subscript}"  # Normalize to π0, π0.5, etc.
        citation_text = m.group(2).strip()
        ay_match = re.search(r"(.+?)\s*,?\s*((?:19|20)\d{2}[a-z]?)", citation_text)
        author = ay_match.group(1).strip().rstrip(",") if ay_match else ""
        year = ay_match.group(2).strip() if ay_match else ""

        key = method_name.lower()
        if key not in seen_methods:
            seen_methods.add(key)
            results.append({
                "name": method_name,
                "ref_numbers": [],
                "ref_author_year": [(author, year)] if author and year else [],
            })

    # Extract [N] style citations
    for m in p1.finditer(text):
        method_name = _clean_method_name(m.group(1))
        if not _is_valid_method_name(method_name):
            continue

        nums = [int(n.strip()) for n in m.group(2).split(",")]

        key = method_name.lower()
        if key not in seen_methods:
            seen_methods.add(key)
            results.append({
                "name": method_name,
                "ref_numbers": nums,
                "ref_author_year": [],
            })

    # Extract (Author, Year) style citations
    # Try p2 first (with "et al."), then p2b as fallback
    for pattern in [p2, p2b]:
        for m in pattern.finditer(text):
            method_name = _clean_method_name(m.group(1))
            if not _is_valid_method_name(method_name):
                continue

            citation_text = m.group(2).strip()
            # Parse author-year: "Brohan et al., 2023" or "Black et al., 2024a"
            ay_match = re.search(
                r"(.+?)\s*,?\s*((?:19|20)\d{2}[a-z]?)",
                citation_text,
            )
            author = ""
            year = ""
            if ay_match:
                author = ay_match.group(1).strip().rstrip(",")
                year = ay_match.group(2).strip()

            key = method_name.lower()
            if key in seen_methods:
                # Add author-year to existing entry
                for r in results:
                    if r["name"].lower() == key:
                        if author and year:
                            r["ref_author_year"].append((author, year))
                        break
            else:
                seen_methods.add(key)
                results.append({
                    "name": method_name,
                    "ref_numbers": [],
                    "ref_author_year": [(author, year)] if author and year else [],
                })

    return results


def _extract_method_citations_from_tables(text: str) -> List[Dict[str, Any]]:
    """Extract method names and citation markers from HTML tables in the markdown."""
    results = []

    # Find all <table>...</table> blocks
    table_pattern = re.compile(r"<table>.*?</table>", re.DOTALL)
    for table_m in table_pattern.finditer(text):
        table_html = table_m.group()

        # Extract all <td>...</td> cells
        cell_pattern = re.compile(r"<td>(.*?)</td>", re.DOTALL)
        cells = [c.group(1).strip() for c in cell_pattern.finditer(table_html)]

        for cell in cells:
            # Pattern: MethodName [N]
            m = re.match(r"^([A-Za-z$π][A-Za-z0-9_\-\.\s]{0,50}?)\s*\[(\d+)\]$", cell.strip())
            if m:
                method_name = m.group(1).strip()
                ref_num = int(m.group(2))
                if len(method_name) >= 2:
                    results.append({
                        "name": method_name,
                        "ref_numbers": [ref_num],
                        "ref_author_year": [],
                    })
                continue

            # Pattern: MethodName (Author et al., Year)
            m = re.match(r"^([A-Za-z$π][A-Za-z0-9_\-\.\s]{0,50}?)\s*\(([^)]+?(?:et\s+al\.?[^)]*?)(?:19|20)\d{2}[^)]*?)\)$", cell.strip())
            if not m:
                m = re.match(r"^([A-Za-z$π][A-Za-z0-9_\-\.\s]{0,50}?)\s*\(([^)]+?(?:19|20)\d{2}[^)]*?)\)$", cell.strip())
            if m:
                method_name = m.group(1).strip()
                citation_text = m.group(2).strip()
                ay_match = re.search(r"(.+?)\s*,?\s*((?:19|20)\d{2}[a-z]?)", citation_text)
                author = ay_match.group(1).strip().rstrip(",") if ay_match else ""
                year = ay_match.group(2).strip() if ay_match else ""
                if len(method_name) >= 2:
                    results.append({
                        "name": method_name,
                        "ref_numbers": [],
                        "ref_author_year": [(author, year)] if author and year else [],
                    })
                continue

    return results


def _normalize_for_matching(text: str) -> str:
    """Normalize text for fuzzy matching — handles LaTeX π, spacing, etc."""
    t = text.lower()
    # Normalize LaTeX pi patterns: $\pi _ { 0 . 5 }$ → pi0.5, $\pi_{0}$ → pi0
    t = re.sub(r"\$?\s*\\?pi\s*_?\s*\{?\s*([\d.]+)\s*\}?\s*\$?", r"pi\1", t)
    # Normalize standalone π
    t = t.replace("π", "pi")
    # Collapse whitespace
    t = re.sub(r"\s+", "", t)
    # Remove common LaTeX artifacts
    t = t.replace("\\", "")
    return t


def _match_method_to_reference(
    method_name: str,
    ref_numbers: List[int],
    ref_author_year: List[Tuple[str, str]],
    ref_map: Dict[int, _RefEntry],
) -> Optional[_RefEntry]:
    """Match a method name to its reference paper entry.

    Priority:
    1. Direct [N] number lookup (one-to-one)
    2. (Author, Year) lookup in ref_map
    3. Substring match of method name in candidate reference titles
    """
    method_lower = method_name.lower().strip()

    # Rule 1: Single reference number → direct lookup
    if len(ref_numbers) == 1:
        entry = ref_map.get(ref_numbers[0])
        if entry:
            return entry

    # Rule 2: Multiple reference numbers → substring match in candidate titles
    if len(ref_numbers) > 1:
        candidates = [ref_map[n] for n in ref_numbers if n in ref_map]
        # Try exact substring match (method name appears in title)
        for entry in candidates:
            if method_lower in entry.title.lower():
                return entry
        # Try normalized match (remove spaces, hyphens)
        method_norm = re.sub(r"[\s\-_]", "", method_lower)
        for entry in candidates:
            title_norm = re.sub(r"[\s\-_]", "", entry.title.lower())
            if method_norm in title_norm:
                return entry
        # No match among candidates → skip (don't guess)

    # Rule 3: (Author, Year) lookup in ref_map
    for author, year in ref_author_year:
        # Normalize author for matching — extract first surname
        author_surname = re.match(r"([A-Z][a-z]+)", author)
        if not author_surname:
            continue
        surname = author_surname.group(1).lower()
        # Normalize year: strip suffix like '2025b' → '2025'
        year_clean = re.match(r"(\d{4})", year)
        year_norm = year_clean.group(1) if year_clean else year

        matches = []
        for entry in ref_map.values():
            if entry.year != year_norm:
                continue
            # Check if author surname matches the FIRST author of the entry
            # Authors in ref_map are formatted as "FirstName LastName, ..." (e.g. "Kevin Black, ...")
            # The surname is the last word before the first comma
            entry_authors_lower = entry.authors.lower()
            first_author_part = entry_authors_lower.split(",")[0].strip()
            first_author_words = first_author_part.split()
            # Take the last word of the first author as surname (e.g. "kevin black" → "black")
            first_author_surname = first_author_words[-1] if first_author_words else ""
            if first_author_surname == surname:
                matches.append(entry)
        if len(matches) == 1:
            return matches[0]
        # If multiple matches with same first author+year, try to also match
        # the method name as substring in the title (normalized for LaTeX)
        if matches:
            method_norm = _normalize_for_matching(method_name)
            for entry in matches:
                title_norm = _normalize_for_matching(entry.title)
                if method_norm in title_norm:
                    return entry

    # Rule 3b: (Author, Year) not found in ref_map — try substring match in ref_map titles
    # This helps when the ref_map is incomplete (unnumbered format)
    if ref_author_year and not ref_numbers:
        method_norm = _normalize_for_matching(method_name)
        matches = []
        for entry in ref_map.values():
            title_norm = _normalize_for_matching(entry.title)
            if method_norm in title_norm:
                matches.append(entry)
        if len(matches) == 1:
            return matches[0]

    # Rule 4: No citation markers → search all references by substring
    if not ref_numbers and not ref_author_year:
        matches = []
        for entry in ref_map.values():
            if method_lower in entry.title.lower():
                matches.append(entry)
            else:
                method_norm = re.sub(r"[\s\-_]", "", method_lower)
                title_norm = re.sub(r"[\s\-_]", "", entry.title.lower())
                if method_norm in title_norm:
                    matches.append(entry)

        if len(matches) == 1:
            return matches[0]
        # Multiple matches or no matches → skip

    return None


def _normalize_search_title(title: str) -> str:
    """Normalize LaTeX in title for search engines."""
    search_title = title
    # Convert LaTeX: $\pi_{0.5}$ or $\pi _ { 0 . 5 }$ → pi0.5
    search_title = re.sub(r"\$\s*\\pi\s*_?\s*\{?\s*([\d.\s]+?)\s*\}?\s*\$", lambda m: "pi" + m.group(1).replace(" ", ""), search_title)
    # Convert standalone LaTeX \pi_{N} (without $)
    search_title = re.sub(r"\\pi\s*_?\s*\{?\s*([\d.]+)\s*\}?", lambda m: "pi" + m.group(1), search_title)
    # Convert Unicode π
    search_title = search_title.replace("π", "pi")
    # Clean up extra whitespace and remove residual LaTeX artifacts
    search_title = re.sub(r"[${}\\]", " ", search_title).strip()
    search_title = re.sub(r"\s+", " ", search_title).strip()
    return search_title


def _resolve_paper_by_title_arxiv_only(title: str) -> Optional[CandidatePaper]:
    """Resolve a paper title using arXiv only (no S2 calls, no rate limit issues)."""
    search_title = _normalize_search_title(title)
    try:
        client = arxiv.Client(page_size=3, delay_seconds=1.0, num_retries=2)
        search = arxiv.Search(
            query=f'ti:"{search_title[:100]}"',
            max_results=3,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        for result in client.results(search):
            result_title = result.title.replace("\n", " ").strip().lower()
            if _titles_match(result_title, title.lower().strip()):
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
                    relevance_score=2,
                    year=str(result.published.year) if result.published else "",
                )
                return cp
    except Exception as e:
        print(f"[RelativePaper] arXiv title search failed for '{title[:50]}': {e}")
    return None


def _resolve_paper_by_title_s2_only(title: str) -> Optional[CandidatePaper]:
    """Resolve a paper title using Semantic Scholar only (handles π, short names)."""
    search_title = _normalize_search_title(title)
    try:
        query = search_title[:200]
        url = (
            f"https://api.semanticscholar.org/graph/v1/paper/search"
            f"?query={requests.utils.quote(query)}&limit=3"
            f"&fields=paperId,title,abstract,authors,year,externalIds"
        )
        resp = _s2_get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                item_title = item.get("title", "").lower().strip()
                orig_title_lower = title.lower().strip()
                if _titles_match(item_title, orig_title_lower):
                    ext_ids = item.get("externalIds", {}) or {}
                    arxiv_id = ext_ids.get("ArXiv")
                    authors_list = item.get("authors", [])
                    authors_str = ", ".join(a.get("name", "") for a in authors_list if a.get("name"))

                    return CandidatePaper(
                        title=item.get("title", ""),
                        abstract=item.get("abstract", "") or "",
                        authors=authors_str,
                        arxiv_id=arxiv_id,
                        arxiv_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None,
                        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
                        source="baseline",
                        relevance_score=2,
                        year=str(item.get("year", "")) if item.get("year") else "",
                    )
    except Exception as e:
        print(f"[RelativePaper] Semantic Scholar title search failed for '{title[:50]}': {e}")
    return None


def _resolve_paper_by_title(title: str) -> Optional[CandidatePaper]:
    """Resolve a paper title using arXiv first, then S2 fallback."""
    cp = _resolve_paper_by_title_arxiv_only(title)
    if cp:
        return cp
    return _resolve_paper_by_title_s2_only(title)


def _titles_match(title1: str, title2: str) -> bool:
    """Check if two paper titles refer to the same paper (fuzzy match)."""
    # Normalize: lowercase, strip, collapse whitespace
    t1 = re.sub(r"\s+", " ", title1.lower().strip())
    t2 = re.sub(r"\s+", " ", title2.lower().strip())

    # Exact match
    if t1 == t2:
        return True

    # One contains the other (titles sometimes get truncated)
    if t1 in t2 or t2 in t1:
        return True

    # Remove punctuation and compare
    t1_clean = re.sub(r"[^\w\s]", "", t1)
    t2_clean = re.sub(r"[^\w\s]", "", t2)
    if t1_clean == t2_clean:
        return True

    # Word overlap ratio
    words1 = set(t1_clean.split())
    words2 = set(t2_clean.split())
    if words1 and words2:
        overlap = len(words1 & words2) / min(len(words1), len(words2))
        if overlap >= 0.8:
            return True

    return False


@dataclass
class CitationExtractionResult:
    """Result from citation-based baseline extraction."""
    matched_method_count: int = 0     # Total methods matched to reference entries
    resolved_method_count: int = 0    # Methods successfully resolved to papers
    unresolved_methods: List[str] = field(default_factory=list)  # Method names that couldn't be resolved
    candidates: List[CandidatePaper] = field(default_factory=list)  # Resolved candidate papers
    ref_map: Optional[Dict[int, Any]] = field(default_factory=dict)  # Reference entries from parsed References section


def _resolve_unresolved_methods_with_llm(
    unresolved_methods: List[str],
    ref_map: Dict[int, Any],
    ref_abstract: str,
    ref_paper_data: Dict[str, Any],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    seen_arxiv_ids: Set[str],
) -> List[CandidatePaper]:
    """Resolve unresolved baseline method names using ref_map + LLM verification.

    Two-phase approach:
    1. HIGH RECALL: For each unresolved method, find candidate ref entries
       from ref_map whose titles might correspond to the method name.
    2. HIGH PRECISION: Resolve candidate ref entries via arXiv/S2 to get
       abstracts, then use LLM to verify the method name matches the paper.
    """
    if not unresolved_methods or not ref_map:
        return []

    # ---- Phase 1: High recall — find candidate ref entries ----
    # For each unresolved method, collect ref_map entries where
    # the method name might be related to the title.
    method_candidates: Dict[str, List[_RefEntry]] = {}  # method_name → [ref entries]

    for method_name in unresolved_methods:
        method_norm = _normalize_for_matching(method_name).lower()
        method_no_punct = re.sub(r"[\s\-_]", "", method_norm)
        candidates = []

        for entry in ref_map.values():
            title_norm = _normalize_for_matching(entry.title).lower()
            title_no_punct = re.sub(r"[\s\-_]", "", title_norm)

            # Check various matching strategies
            matched = False

            # 1. Method name as substring of title (normalized)
            if method_norm in title_norm or method_no_punct in title_no_punct:
                matched = True

            # 2. Significant words from method name appear in title
            # Split method name into words, check if most appear
            method_words = [w for w in re.findall(r"[a-zA-Zπ0-9]+", method_norm) if len(w) > 1]
            if method_words:
                words_in_title = sum(1 for w in method_words if w in title_norm or w in title_no_punct)
                if words_in_title >= max(len(method_words) - 1, 1) and words_in_title >= 1:
                    matched = True

            # 3. Title words as substring of method name (e.g. method="Diffusion Policy", title contains both)
            # Already covered by #1 and #2 above

            if matched:
                candidates.append(entry)

        if candidates:
            method_candidates[method_name] = candidates
            cand_titles = [f"[{c.number}] {c.title[:40]}" for c in candidates]
            print(f"[RelativePaper] Recall phase: '{method_name}' → {len(candidates)} candidates: {cand_titles}")
        else:
            print(f"[RelativePaper] Recall phase: '{method_name}' → no candidates in ref_map")

    if not method_candidates:
        return []

    # ---- Phase 2: High precision — resolve candidates & LLM verify ----
    # For each method with candidates, resolve each candidate via arXiv/S2
    # to get abstracts, then use LLM to pick the best match.
    result_candidates: List[CandidatePaper] = []

    # Batch all candidate titles for resolution, then LLM verify
    # Group by method to resolve and verify per-method
    for method_name, entries in method_candidates.items():
        # Resolve each candidate entry to a CandidatePaper (with abstract)
        resolved_papers: List[Tuple[_RefEntry, CandidatePaper]] = []
        for entry in entries:
            cp = _resolve_paper_by_title_arxiv_only(entry.title)
            if not cp:
                cp = _resolve_paper_by_title_s2_only(entry.title)
            if cp:
                # Skip if already seen
                arxiv_base = re.sub(r"v\d+$", "", cp.arxiv_id) if cp.arxiv_id else ""
                if arxiv_base and arxiv_base in seen_arxiv_ids:
                    continue
                resolved_papers.append((entry, cp))

        if not resolved_papers:
            print(f"[RelativePaper] Precision phase: '{method_name}' — no candidates resolved to papers")
            continue

        if len(resolved_papers) == 1:
            # Only one candidate — accept it directly (no LLM needed)
            entry, cp = resolved_papers[0]
            arxiv_base = re.sub(r"v\d+$", "", cp.arxiv_id) if cp.arxiv_id else ""
            if arxiv_base:
                seen_arxiv_ids.add(arxiv_base)
            result_candidates.append(cp)
            print(f"[RelativePaper] Precision phase: '{method_name}' → single match {cp.title[:50]} (arxiv={cp.arxiv_id})")
            continue

        # Multiple candidates — use LLM to pick the best match
        papers_text = ""
        for idx, (entry, cp) in enumerate(resolved_papers):
            abstract_snippet = (cp.abstract or "")[:300]
            papers_text += f"\n[{idx}] Title: {cp.title}\nAbstract: {abstract_snippet}\n"

        prompt = f"""Given a method name "{method_name}" from a robotics paper, which of these candidate papers is the correct one? The method name may be an abbreviation, acronym, or shorthand for the paper.

Reference paper abstract: {ref_abstract[:500]}

Method name: {method_name}

Candidate papers:{papers_text}

Output a JSON object with "index" (0-based index of the best match) and "confidence" ("high", "medium", or "low"). If none of the candidates match, set "index" to -1.

Example: {{"index": 0, "confidence": "high"}}

Output ONLY the JSON object, no explanation."""

        try:
            from openai import OpenAI

            client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
            response = client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=100,
            )
            result_text = response.choices[0].message.content.strip()
            json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
            if json_match:
                llm_result = json.loads(json_match.group())
                chosen_idx = llm_result.get("index", -1)
                confidence = llm_result.get("confidence", "low")

                if 0 <= chosen_idx < len(resolved_papers) and confidence != "low":
                    entry, cp = resolved_papers[chosen_idx]
                    arxiv_base = re.sub(r"v\d+$", "", cp.arxiv_id) if cp.arxiv_id else ""
                    if arxiv_base:
                        seen_arxiv_ids.add(arxiv_base)
                    result_candidates.append(cp)
                    print(f"[RelativePaper] Precision phase: '{method_name}' → LLM chose [{chosen_idx}] {cp.title[:50]} (confidence={confidence})")
                else:
                    print(f"[RelativePaper] Precision phase: '{method_name}' — LLM rejected (idx={chosen_idx}, confidence={confidence})")
            else:
                print(f"[RelativePaper] Precision phase: '{method_name}' — LLM response parse failed")
        except Exception as e:
            print(f"[RelativePaper] Precision phase LLM failed for '{method_name}': {e}")

    return result_candidates


def _extract_baselines_from_citations(
    ref_paper_data: Dict[str, Any],
) -> CitationExtractionResult:
    """Extract baseline method papers using citation-based parsing.

    Parses the PDF-to-markdown intermediate file to:
    1. Extract method names + citation markers from experiment section
    2. Parse References section to build number→title mapping
    3. Match method names to reference titles
    4. Resolve matched titles to CandidatePaper via Semantic Scholar/arXiv
    """
    # Step 1: Locate the PDF-to-markdown file
    md_path = _find_pdf2md_path(ref_paper_data)
    if not md_path:
        print("[RelativePaper] No PDF-to-markdown file found, skipping citation-based extraction")
        return CitationExtractionResult(candidates=[])

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()
    except Exception as e:
        print(f"[RelativePaper] Failed to read markdown file: {e}")
        return CitationExtractionResult(candidates=[])

    # Step 2: Parse References section
    ref_map = _parse_references_section(md_content)
    if not ref_map:
        print("[RelativePaper] No references found in markdown, skipping citation-based extraction")
        return CitationExtractionResult(candidates=[])
    print(f"[RelativePaper] Parsed {len(ref_map)} reference entries")

    # Step 3: Extract experiment section
    exp_section = _extract_experiment_section(md_content)
    if not exp_section:
        print("[RelativePaper] No experiment section found, skipping citation-based extraction")
        return CitationExtractionResult(candidates=[], ref_map=ref_map)

    # Step 4: Extract method citations from text and tables
    text_methods = _extract_method_citations_from_text(exp_section)
    table_methods = _extract_method_citations_from_tables(exp_section)

    # Merge: table entries supplement text entries (text has priority)
    text_method_names = {m["name"].lower() for m in text_methods}
    for tm in table_methods:
        if tm["name"].lower() not in text_method_names:
            text_methods.append(tm)
            text_method_names.add(tm["name"].lower())
        else:
            # Supplement ref_numbers/ref_author_year from table to text
            for sm in text_methods:
                if sm["name"].lower() == tm["name"].lower():
                    for rn in tm["ref_numbers"]:
                        if rn not in sm["ref_numbers"]:
                            sm["ref_numbers"].append(rn)
                    for ay in tm["ref_author_year"]:
                        if ay not in sm["ref_author_year"]:
                            sm["ref_author_year"].append(ay)
                    break

    print(f"[RelativePaper] Extracted {len(text_methods)} method citations from experiment section")

    # Track resolution status for UI display
    resolved_method_names: Set[str] = set()  # Method names successfully resolved to papers

    # Step 5: Match each method name to a reference entry
    matched_entries: List[Tuple[str, _RefEntry]] = []  # (method_name, ref_entry)
    unresolved_methods: List[Dict[str, Any]] = []  # Methods that couldn't be matched via ref_map
    for method in text_methods:
        entry = _match_method_to_reference(
            method["name"],
            method["ref_numbers"],
            method["ref_author_year"],
            ref_map,
        )
        if entry:
            matched_entries.append((method["name"], entry))
            print(f"[RelativePaper] Matched: '{method['name']}' → [{entry.number}] {entry.title[:60]}")
        else:
            unresolved_methods.append(method)
            print(f"[RelativePaper] Unmatched: '{method['name']}' (refs={method['ref_numbers']}, ay={method['ref_author_year']})")

    # Step 6: Resolve matched titles to CandidatePapers
    # Two-pass strategy: arXiv first (no rate limits), then S2 for remaining.
    # This avoids wasting S2 quota on papers arXiv can already find.
    candidates: List[CandidatePaper] = []
    resolved_arxiv_ids: set = set()  # Track to avoid duplicates across methods
    def _arxiv_id_base(arxiv_id: str) -> str:
        """Strip version suffix for dedup: '2406.02523v1' → '2406.02523'"""
        return re.sub(r"v\d+$", "", arxiv_id) if arxiv_id else ""

    # --- Pass 1: arXiv only (fast, no rate limits) ---
    arxiv_unresolved: List[Tuple[str, _RefEntry]] = []  # (method_name, entry) that arXiv couldn't find
    for method_name, entry in matched_entries:
        cp = _resolve_paper_by_title_arxiv_only(entry.title)
        if cp:
            dedup_key = _arxiv_id_base(cp.arxiv_id) or cp.title.lower().strip()
            if dedup_key in resolved_arxiv_ids:
                print(f"[RelativePaper] Skipping duplicate: '{method_name}' → {cp.title[:50]}")
                resolved_method_names.add(method_name)
                continue
            resolved_arxiv_ids.add(dedup_key)
            candidates.append(cp)
            resolved_method_names.add(method_name)
            print(f"[RelativePaper] arXiv resolved: '{method_name}' → {cp.title[:50]} (arxiv={cp.arxiv_id})")
        else:
            arxiv_unresolved.append((method_name, entry))
            print(f"[RelativePaper] arXiv could not resolve: '{method_name}' → '{entry.title[:60]}'")

    # --- Pass 2: S2 for remaining (handles π, short names, etc.) ---
    for method_name, entry in arxiv_unresolved:
        cp = _resolve_paper_by_title_s2_only(entry.title)
        if cp:
            dedup_key = _arxiv_id_base(cp.arxiv_id) or cp.title.lower().strip()
            if dedup_key in resolved_arxiv_ids:
                print(f"[RelativePaper] Skipping duplicate: '{method_name}' → {cp.title[:50]}")
                resolved_method_names.add(method_name)
                continue
            resolved_arxiv_ids.add(dedup_key)
            candidates.append(cp)
            resolved_method_names.add(method_name)
            print(f"[RelativePaper] S2 resolved: '{method_name}' → {cp.title[:50]} (arxiv={cp.arxiv_id})")
        else:
            print(f"[RelativePaper] Could not resolve: '{method_name}' → '{entry.title[:60]}'")

    # Step 7: For unresolved methods with (Author, Year) citations,
    # try resolving via arXiv first, then Semantic Scholar as fallback.
    # Semantic Scholar handles π and other non-ASCII symbols better than arXiv.

    # Collect already-resolved arxiv_ids to avoid duplicates (strip version suffix)
    resolved_arxiv_ids = {_arxiv_id_base(c.arxiv_id) for c in candidates if c.arxiv_id}

    # Descriptive phrases that are not method names — skip these
    _non_method_keywords = {"benchmark", "dataset", "suite", "tabletop", "task", "experiment", "setting", "environment", "evaluation"}

    for method in unresolved_methods:
        if not method["ref_author_year"]:
            continue
        method_name = method["name"]

        # Skip descriptive phrases that aren't method names
        # E.g. "LIBERO benchmark", "GR1 dataset", "RoboCasa-GR1 tabletop suite"
        name_lower = method_name.lower()
        has_keyword = any(kw in name_lower for kw in _non_method_keywords)
        if has_keyword:
            # Strip trailing keywords repeatedly until no more remain
            stripped = method_name
            changed = True
            while changed:
                changed = False
                for kw in _non_method_keywords:
                    new = re.sub(rf'\s+{kw}\s*$', '', stripped, flags=re.IGNORECASE).strip()
                    if new != stripped:
                        stripped = new
                        changed = True
            # If stripped name is empty, too short, or still contains hyphens+spaces (not a clean name), skip
            if not stripped or len(stripped) <= 2:
                print(f"[RelativePaper] Skipping non-method name: '{method_name}'")
                continue
            # Skip if stripped name looks like a compound descriptor (e.g. "RoboCasa-GR1", "GR1")
            # rather than a real method name — check if it already exists in candidates
            stripped_norm = stripped.lower()
            already_resolved = False
            for c in candidates:
                c_title_norm = c.title.lower()
                # Check if any part of the hyphenated stripped name matches an existing candidate
                if stripped_norm in c_title_norm or c_title_norm.startswith(stripped_norm):
                    already_resolved = True
                    break
                # Also check individual components (e.g. "RoboCasa-GR1" → check "robocasa" and "gr1")
                for part in stripped.replace("-", " ").split():
                    if len(part) > 2 and part.lower() in c_title_norm:
                        already_resolved = True
                        break
                if already_resolved:
                    break
            if already_resolved:
                print(f"[RelativePaper] Skipping non-method name (already resolved): '{method_name}'")
                continue
            elif stripped != method_name:
                print(f"[RelativePaper] Stripping non-method suffix: '{method_name}' → '{stripped}'")
                method_name = stripped

        # Skip if a longer method name containing this name was already resolved
        # E.g. "Diffusion" is redundant if "Diffusion Policy" is already in candidates
        name_norm = method_name.lower().replace("π", "pi")
        is_substring_of_resolved = False
        for c in candidates:
            c_title_norm = c.title.lower().replace("π", "pi")
            # Check if this method name is a proper substring of an already-resolved title
            if name_norm in c_title_norm and name_norm != c_title_norm and len(name_norm) < len(c_title_norm):
                # Also verify the author matches to avoid false positives
                author_match = False
                for author_name, _ in method["ref_author_year"]:
                    author_surname_check = re.match(r"([A-Z][a-z]+)", author_name)
                    if author_surname_check and author_surname_check.group(1).lower() in c.authors.lower():
                        author_match = True
                        break
                if author_match:
                    is_substring_of_resolved = True
                    print(f"[RelativePaper] Skipping '{method_name}' — already covered by resolved '{c.title[:40]}'")
                    break
        if is_substring_of_resolved:
            continue

        author, year_raw = method["ref_author_year"][0]
        year_clean = re.match(r"(\d{4})", year_raw)
        expected_year = year_clean.group(1) if year_clean else year_raw
        author_surname = re.match(r"([A-Z][a-z]+)", author)
        resolved = False

        # --- Try arXiv first ---
        try:
            client = arxiv.Client(page_size=5, delay_seconds=1.0, num_retries=1)
            search = arxiv.Search(
                query=f'ti:"{method_name}"',
                max_results=5,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            for result in client.results(search):
                result_year = str(result.published.year) if result.published else ""
                if result_year == expected_year:
                    arxiv_id = result.entry_id.split("/abs/")[-1]
                    if arxiv_id in resolved_arxiv_ids:
                        resolved = True
                        break
                    authors_str = ", ".join(a.name for a in result.authors)
                    cp = CandidatePaper(
                        title=result.title.replace("\n", " ").strip(),
                        abstract=result.summary.replace("\n", " ").strip() if result.summary else "",
                        authors=authors_str,
                        arxiv_id=arxiv_id,
                        arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
                        pdf_url=result.pdf_url,
                        source="baseline",
                        relevance_score=2,
                        year=result_year,
                    )
                    candidates.append(cp)
                    resolved_arxiv_ids.add(arxiv_id)
                    print(f"[RelativePaper] arXiv resolved: '{method_name}' → {cp.title[:50]} (arxiv={cp.arxiv_id})")
                    resolved = True
                    break

            if not resolved and author_surname:
                # Broader arXiv search with author + method name
                broader_query = f'{method_name} {author_surname.group(1)}'
                search2 = arxiv.Search(
                    query=broader_query,
                    max_results=5,
                    sort_by=arxiv.SortCriterion.Relevance,
                )
                for result in client.results(search2):
                    result_year = str(result.published.year) if result.published else ""
                    if result_year == expected_year:
                        norm_title = re.sub(r"[\s\-_]", "", result.title.lower())
                        norm_method = re.sub(r"[\s\-_]", "", method_name.lower())
                        if method_name.lower() in result.title.lower() or norm_method in norm_title:
                            arxiv_id = result.entry_id.split("/abs/")[-1]
                            if arxiv_id in resolved_arxiv_ids:
                                resolved = True
                                break
                            authors_str = ", ".join(a.name for a in result.authors)
                            cp = CandidatePaper(
                                title=result.title.replace("\n", " ").strip(),
                                abstract=result.summary.replace("\n", " ").strip() if result.summary else "",
                                authors=authors_str,
                                arxiv_id=arxiv_id,
                                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
                                pdf_url=result.pdf_url,
                                source="baseline",
                                relevance_score=2,
                                year=result_year,
                            )
                            candidates.append(cp)
                            resolved_arxiv_ids.add(arxiv_id)
                            print(f"[RelativePaper] arXiv broad resolved: '{method_name}' → {cp.title[:50]} (arxiv={cp.arxiv_id})")
                            resolved = True
                            break
        except Exception as e:
            print(f"[RelativePaper] arXiv resolution failed for '{method_name}': {e}")

        if resolved:
            resolved_method_names.add(method_name)
            continue

        # --- Fallback: Semantic Scholar (handles π etc. better than arXiv) ---
        try:
            query_parts = []
            if author_surname:
                query_parts.append(author_surname.group(1))
            normalized_name = method_name.replace("π", "pi")
            query_parts.append(normalized_name)
            query_parts.append(expected_year)
            s2_query = " ".join(query_parts)
            s2_url = (
                f"https://api.semanticscholar.org/graph/v1/paper/search"
                f"?query={requests.utils.quote(s2_query)}"
                f"&limit=5&fields=paperId,title,authors,year,externalIds,abstract"
            )

            # Rate limit: use global S2 rate limiter
            s2_resp = _s2_get(s2_url, timeout=15)

            if s2_resp.status_code == 200:
                s2_data = s2_resp.json()
                for item in s2_data.get("data", []):
                    item_year = str(item.get("year", ""))
                    if item_year != expected_year:
                        continue
                    item_title = item.get("title", "")
                    norm_title = item_title.lower().replace("π", "pi")
                    norm_method = normalized_name.lower()
                    if norm_method in norm_title or re.sub(r"[\s\-_]", "", norm_method) in re.sub(r"[\s\-_]", "", norm_title):
                        ext_ids = item.get("externalIds", {}) or {}
                        s2_arxiv_id = ext_ids.get("ArXiv", "")
                        if s2_arxiv_id and s2_arxiv_id in resolved_arxiv_ids:
                            resolved = True
                            break
                        s2_authors = ", ".join(a.get("name", "") for a in item.get("authors", []))
                        cp = CandidatePaper(
                            title=item_title.replace("\n", " ").strip(),
                            abstract=item.get("abstract", "") or "",
                            authors=s2_authors,
                            arxiv_id=s2_arxiv_id,
                            arxiv_url=f"https://arxiv.org/abs/{s2_arxiv_id}" if s2_arxiv_id else "",
                            pdf_url="",
                            source="baseline",
                            relevance_score=2,
                            year=item_year,
                        )
                        candidates.append(cp)
                        if s2_arxiv_id:
                            resolved_arxiv_ids.add(s2_arxiv_id)
                        print(f"[RelativePaper] S2 resolved: '{method_name}' → {cp.title[:50]} (arxiv={cp.arxiv_id})")
                        resolved = True
                        break
                if not resolved:
                    print(f"[RelativePaper] Could not resolve: '{method_name}' (neither arXiv nor S2)")
            else:
                print(f"[RelativePaper] S2 search failed ({s2_resp.status_code}) for '{method_name}'")
        except Exception as e:
            print(f"[RelativePaper] S2 resolution failed for '{method_name}': {e}")

    # Collect unresolved method names for UI display and LLM fallback
    all_method_names = {m["name"] for m in text_methods}
    unresolved_method_names = [name for name in all_method_names if name not in resolved_method_names]

    matched_count = len(matched_entries) + len(unresolved_methods)  # Total methods that had some citation info
    resolved_count = len(resolved_method_names)

    print(f"[RelativePaper] Citation extraction summary: {matched_count} methods matched, "
          f"{resolved_count} resolved, {len(unresolved_method_names)} unresolved: {unresolved_method_names}")

    return CitationExtractionResult(
        candidates=candidates,
        matched_method_count=len(all_method_names),
        resolved_method_count=resolved_count,
        unresolved_methods=unresolved_method_names,
        ref_map=ref_map,
    )


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
        resp = requests.get(download_url, headers=headers, timeout=(15, 120), stream=True, allow_redirects=True)
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

            # Primary: citation-based extraction from PDF-to-markdown
            citation_result = _extract_baselines_from_citations(ref_paper_data)
            progress.matched_methods = citation_result.matched_method_count
            progress.resolved_methods = citation_result.resolved_method_count
            progress.unresolved_methods = citation_result.unresolved_methods

            unique = _add_unique(citation_result.candidates)
            all_candidates.extend(unique)
            print(f"[RelativePaper] Citation-based extraction: {len(unique)} papers "
                  f"({citation_result.resolved_method_count}/{citation_result.matched_method_count} methods resolved, "
                  f"{len(citation_result.unresolved_methods)} unresolved: {citation_result.unresolved_methods})")

            progress.current_step = (
                f"Found {citation_result.matched_method_count} baseline methods, "
                f"resolved {citation_result.resolved_method_count}"
            )

            # Fallback 1: LLM-assisted resolution for methods that citation-based
            # parsing found but couldn't resolve to a paper
            if citation_result.unresolved_methods:
                unresolved_names = citation_result.unresolved_methods
                print(f"[RelativePaper] Trying LLM fallback for {len(unresolved_names)} unresolved methods: {unresolved_names}")
                progress.current_step = (
                    f"Resolving {len(unresolved_names)} unresolved methods via LLM..."
                )

                llm_resolved = _resolve_unresolved_methods_with_llm(
                    unresolved_names, citation_result.ref_map,
                    ref_abstract, ref_paper_data,
                    llm_base_url, llm_api_key, llm_model,
                    seen_arxiv_ids,
                )
                if llm_resolved:
                    unique_llm = _add_unique(llm_resolved)
                    all_candidates.extend(unique_llm)
                    progress.resolved_methods += len(unique_llm)
                    progress.unresolved_methods = [
                        m for m in progress.unresolved_methods
                        if not any(m.lower() in c.title.lower() for c in unique_llm)
                    ]
                    print(f"[RelativePaper] LLM fallback resolved {len(unique_llm)} additional methods")

                progress.current_step = (
                    f"Found {progress.matched_methods} baseline methods, "
                    f"resolved {progress.resolved_methods}"
                )

            # Fallback 2: if citation-based found nothing at all, try LLM+arXiv
            if not unique and not citation_result.unresolved_methods:
                print("[RelativePaper] Citation-based found nothing, falling back to LLM+arXiv")
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
                print(f"[RelativePaper] LLM extracted baseline methods: {method_names}")

                for method_name in method_names:
                    if stop_event.is_set():
                        break
                    found = _search_arxiv_by_method(method_name, max_results=3)
                    for cp in found:
                        # LLM+arXiv results need relevance check
                        cp.relevance_score = 0
                    unique = _add_unique(found)
                    if unique:
                        relevant = _check_relevance_with_llm(
                            ref_abstract, unique,
                            llm_base_url, llm_api_key, llm_model,
                        )
                        all_candidates.extend(relevant)
                        print(f"[RelativePaper] Baseline '{method_name}': {len(relevant)} relevant papers")

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

            # Delay between downloads to avoid arXiv rate limits
            if i > 0:
                time.sleep(3)

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
