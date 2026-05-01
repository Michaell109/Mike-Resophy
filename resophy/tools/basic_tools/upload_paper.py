"""
Paper upload processing module

Two methods for uploading papers are provided:
1. Link to download: via arXiv ID Download directly and get information
2. PDF Upload: Multi-level downgrade strategy from PDF Extract information and get metadata

Processing logic:
- Way1(Link to download):arXiv ID → arXiv API → Get complete information → DBLP cover BibTeX
- Way2（PDFUpload):
  2.1 Extract from file name arXiv ID → Jump to method1
  2.2 from PDF metadata of '/arXivID' extract → Jump to method1
  2.3 from PDF metadata of '/Title' and '/Author' search arXiv
  2.4 use PDF Parse and extract title, then search for arXiv
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import arxiv
import PyPDF2
import requests

from resophy.tools.basic_tools.arxiv_client import get_bibtex_enhanced
from resophy.tools.basic_tools.pdf_extractor import (
    extract_title_by_fontsize,
    extract_title_from_text,
    preprocess_pdf_text,
)

# ============================================================================
# Utility function
# ============================================================================


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """
    standardization arXiv ID

    Args:
        arxiv_id: may be "arXiv:2502.05383", "2502.05383", "2502.05383v1" etc format

    Returns:
        standardized arXiv ID(like "2502.05383"), remove the version number
    """
    # Remove "arXiv:" prefix (case insensitive)
    arxiv_id = re.sub(r"^arxiv\s*:\s*", "", arxiv_id.strip(), flags=re.IGNORECASE)

    # Remove version number (v1, v2 wait)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)

    # Extract core ID（YYYY.NNNNN Format)
    match = re.search(r"(\d{4}\.\d{4,5})", arxiv_id)
    if match:
        return match.group(1)

    return arxiv_id


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """
    from URL extracted from arXiv ID

    Args:
        url: may be "https://arxiv.org/abs/2511.13720v1" or "https://doi.org/10.48550/arXiv.2511.13720"

    Returns:
        extracted arXiv ID, return on failure None
    """
    patterns = [
        r"arxiv\.org/(?:abs|pdf)/([\d.]+(?:v\d+)?)",
        r"doi\.org/10\.48550/arXiv\.([\d.]+)",
        r"arxiv\.org/abs/([\d.]+(?:v\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            return _normalize_arxiv_id(arxiv_id)

    return None


def _extract_arxiv_id_from_filename(filename: str) -> Optional[str]:
    """
    Extract from file name arXiv ID

    Supported formats:
    - 1706.03762v7.pdf
    - arXiv:1706.03762v7.pdf
    - 1706.03762.pdf

    Args:
        filename: PDF file name

    Returns:
        extracted arXiv ID, return on failure None
    """
    # Remove .pdf suffix
    base = os.path.splitext(filename)[0]

    # match YYYY.NNNNNvN Format
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", base)
    if match:
        return _normalize_arxiv_id(match.group(0))

    # match arXiv:YYYY.NNNNNvN Format
    match = re.search(r"arxiv[:\-\s]?(\d{4}\.\d{4,5})(v\d+)?", base, re.IGNORECASE)
    if match:
        return _normalize_arxiv_id(match.group(0))

    return None


# ============================================================================
# Affiliation helper: fetch author affiliations via OpenAlex API
# ============================================================================

_OPENALEX_MAILTO = "resophy.app@gmail.com"


def _extract_affiliations_from_openalex_work(data: dict) -> List[str]:
    """Extract unique institution names from an OpenAlex work response."""
    affiliations: List[str] = []
    authorships = data.get("authorships", [])
    for authorship in authorships:
        for inst in authorship.get("institutions") or []:
            name = inst.get("display_name", "")
            if name and name not in affiliations:
                affiliations.append(name)
    return affiliations


def fetch_arxiv_affiliations(
    arxiv_id: str, title: Optional[str] = None,
) -> List[str]:
    """
    Fetch author affiliations for an arXiv paper using OpenAlex API.

    OpenAlex is a free, open scholarly index with generous rate limits.
    Falls back to title-based search if arXiv DOI query yields no data.

    Args:
        arxiv_id: Normalized arXiv ID (e.g., "2502.05383")
        title: Optional paper title for fallback search (recommended).

    Returns:
        List of unique institution names, empty list if not available.
    """
    try:
        # 1. Try by arXiv DOI
        url = (
            f"https://api.openalex.org/works/doi:10.48550/arXiv.{arxiv_id}"
            f"?mailto={_OPENALEX_MAILTO}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            affiliations = _extract_affiliations_from_openalex_work(data)
            if affiliations:
                print(
                    f"[Affiliations] Found {len(affiliations)} institutions for arXiv:{arxiv_id}"
                )
                return affiliations

        # 2. Fallback: search by title (may find published version with better data)
        if title:
            query = title[:200]
            search_url = (
                f"https://api.openalex.org/works"
                f"?search={requests.utils.quote(query)}"
                f"&per_page=5&mailto={_OPENALEX_MAILTO}"
            )
            resp2 = requests.get(search_url, timeout=10)
            if resp2.status_code == 200:
                for item in resp2.json().get("results", []):
                    affs = _extract_affiliations_from_openalex_work(item)
                    if affs:
                        print(
                            f"[Affiliations] Found {len(affs)} institutions via title search "
                            f"for arXiv:{arxiv_id}"
                        )
                        return affs

        print(f"[Affiliations] No affiliations found for arXiv:{arxiv_id}")
        return []
    except Exception as exc:
        print(f"[Affiliations] OpenAlex fetch failed for {arxiv_id}: {exc}")
        return []


def _add_affiliations_to_result(result: Dict[str, Any], arxiv_id: str) -> None:
    """Helper: fetch and attach affiliation data to a paper info dict."""
    title = result.get("title")
    affiliations = fetch_arxiv_affiliations(arxiv_id, title=title)
    result["affiliations"] = affiliations
    result["affiliation"] = "; ".join(affiliations) if affiliations else ""


# ============================================================================
# Way1: pass arXiv ID Get paper information
# ============================================================================


def fetch_paper_by_arxiv_id(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    Quick version: Pass only arXiv API Get paper information (without waiting DBLP）

    Args:
        arxiv_id: arXiv ID(like "2502.05383" or "arXiv:2502.05383"）

    Returns:
        Dissertation Information Dictionary,bibtex The field is empty (followed by DBLP filling)
    """
    try:
        # standardization arXiv ID
        arxiv_id = _normalize_arxiv_id(arxiv_id)
        print(f"[arXiv Fast] pass arXiv ID Get the paper: {arxiv_id}")

        # call arXiv API
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id])

        paper = next(client.results(search), None)
        if not paper:
            print(f"[arXiv Fast] not found arXiv ID: {arxiv_id}")
            return None

        # Get author information
        authors_list = [author.name for author in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,  # Keep original format
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",  # arXiv Link
            "bibtex": "",  # Temporarily empty, obtained in the background DBLP post-fill
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        # Fetch affiliations via OpenAlex
        _add_affiliations_to_result(result, arxiv_id)

        print(f"[arXiv Fast] ✅ Successfully obtained the paper: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[arXiv Fast] ❌ Failed to get the paper: {exc}")
        import traceback

        traceback.print_exc()
        return None


def fetch_bibtex_from_dblp(title: str, authors: str, arxiv_id: str) -> Optional[str]:
    """
    from DBLP get BibTeX(Can be called in the background)

    Args:
        title: Paper title
        authors: author string
        arxiv_id: arXiv ID

    Returns:
        BibTeX String, returned on failure None
    """
    try:
        print(f"[DBLP] get BibTeX: {title[:50]}...")
        bibtex = get_bibtex_enhanced(title=title, authors=authors, arxiv_id=arxiv_id)
        if bibtex:
            print(f"[DBLP] ✅ successfully obtained BibTeX")
        else:
            print(f"[DBLP] ❌ Not obtained BibTeX")
        return bibtex
    except Exception as exc:
        print(f"[DBLP] ❌ get BibTeX fail: {exc}")
        return None


# ============================================================================
# Way2: PDF Upload processing (multi-level downgrade strategy)
# ============================================================================


def extract_pdf_arxiv_metadata(pdf_path: str) -> Dict[str, Optional[str]]:
    """
    from PDF metadata extracted from arXiv Related information

    Find fields:
    - '/arXivID': arXiv ID(may be URL Format)
    - '/Title': Paper title
    - '/Author': Author information

    Args:
        pdf_path: PDF file path

    Returns:
        A dictionary containing the following fields:
        - arxiv_id: extracted arXiv ID(if found)
        - title: Title (if found)
        - authors: Author (if found)
    """
    result = {
        "arxiv_id": None,
        "title": None,
        "authors": None,
    }

    try:
        with open(pdf_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            if not pdf_reader.metadata:
                return result

            meta = pdf_reader.metadata

            # Find '/arXivID' Field
            arxiv_id_raw = (
                meta.get("/arXivID") or meta.get("/arxiv_id") or meta.get("/ArxivID")
            )
            if arxiv_id_raw:
                arxiv_id_str = str(arxiv_id_raw).strip()
                print(f"[PDF Metadata] turn up /arXivID: {arxiv_id_str}")

                # in the case of URL, try to extract ID
                arxiv_id = _extract_arxiv_id_from_url(arxiv_id_str)
                if not arxiv_id:
                    # if not URL, directly as ID deal with
                    arxiv_id = _normalize_arxiv_id(arxiv_id_str)

                if arxiv_id:
                    result["arxiv_id"] = arxiv_id
                    print(f"[PDF Metadata] extracted arXiv ID: {arxiv_id}")

            # Find '/Title' Field
            title = meta.get("/Title")
            if title and title.strip() and len(title.strip()) > 5:
                result["title"] = title.strip()
                print(f"[PDF Metadata] turn up /Title: {result['title'][:50]}...")

            # Find '/Author' Field
            authors = meta.get("/Author")
            if authors and authors.strip():
                result["authors"] = authors.strip()
                print(f"[PDF Metadata] turn up /Author: {result['authors']}")

            return result

    except Exception as exc:
        print(f"[PDF Metadata] Failed to extract: {exc}")
        return result


def search_arxiv_by_title_and_author(
    title: str, author: str
) -> Optional[Dict[str, Any]]:
    """
    Quick version: Search using title and author arXiv Thesis (no waiting DBLP）

    Args:
        title: Paper title
        author: Author name (can be the first author)

    Returns:
        Dissertation Information Dictionary,bibtex Field is empty
    """
    try:
        # Clean special characters (like colons) in titles
        clean_title = title.replace(":", " ")

        # Construct query string
        query = f'ti:"{clean_title}" AND au:"{author}"'
        print(f"[Way2.3 Fast] Use titles+Author search arXiv: [{query}]")

        # use arxiv library search
        client = arxiv.Client()
        search = arxiv.Search(
            query=query, max_results=1, sort_by=arxiv.SortCriterion.Relevance
        )

        paper = next(client.results(search), None)
        if not paper:
            print(f"[Way2.3 Fast] No matching paper found")
            return None

        # extract arXiv ID
        arxiv_id = paper.entry_id.split("/")[-1]
        arxiv_id = _normalize_arxiv_id(arxiv_id)

        # Get author information
        authors_list = [a.name for a in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "bibtex": "",  # Temporarily empty, obtained in the background DBLP post-fill
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        # Fetch affiliations via OpenAlex
        _add_affiliations_to_result(result, arxiv_id)

        print(f"[Way2.3 Fast] ✅ Find matching papers: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[Way2.3 Fast] ❌ Search failed: {exc}")
        import traceback

        traceback.print_exc()
        return None


def search_arxiv_by_title_only(title: str) -> Optional[Dict[str, Any]]:
    """
    Quick version: search using title only arXiv Thesis (no waiting DBLP）

    Args:
        title: Paper title

    Returns:
        Dissertation Information Dictionary,bibtex Field is empty
    """
    try:
        print(f"[Way2.4 Fast] Search using titles arXiv: {title[:50]}...")

        # use arxiv library search
        client = arxiv.Client()
        search = arxiv.Search(
            query=f'ti:"{title}"', max_results=1, sort_by=arxiv.SortCriterion.Relevance
        )

        paper = next(client.results(search), None)
        if not paper:
            print(f"[Way2.4 Fast] No matching paper found")
            return None

        # extract arXiv ID
        arxiv_id = paper.entry_id.split("/")[-1]
        arxiv_id = _normalize_arxiv_id(arxiv_id)

        # Get author information
        authors_list = [a.name for a in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "bibtex": "",  # Temporarily empty, obtained in the background DBLP post-fill
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        # Fetch affiliations via OpenAlex
        _add_affiliations_to_result(result, arxiv_id)

        print(f"[Way2.4 Fast] ✅ Find matching papers: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[Way2.4 Fast] ❌ Search failed: {exc}")
        import traceback

        traceback.print_exc()
        return None


def process_uploaded_pdf(pdf_path: str, filename: str) -> Optional[Dict[str, Any]]:
    """
    Quick version: handles uploads PDF file(no wait DBLP）

    processing flow (with process_uploaded_pdf Same, but without waiting DBLP）：
    2.1 Extract from file name arXiv ID → If found, get it quickly arXiv information
    2.2 from PDF metadata of '/arXivID' extract → If found, get it quickly arXiv information
    2.3 from PDF metadata of '/Title' and '/Author' search arXiv
    2.4 use PDF Parse and extract title, and then just use title search arXiv

    Args:
        pdf_path: PDF file path
        filename: PDF file name

    Returns:
        Dissertation Information Dictionary,bibtex The field is empty (followed by DBLP filling)
    """
    print(f"[Way2 Fast] Start processing PDF: {filename}")

    # ========================================================================
    # 2.1 Extract from file name arXiv ID
    # ========================================================================
    arxiv_id_from_filename = _extract_arxiv_id_from_filename(filename)
    if arxiv_id_from_filename:
        print(f"[Way2.1 Fast] Extract from file name to arXiv ID: {arxiv_id_from_filename}")
        result = fetch_paper_by_arxiv_id(arxiv_id_from_filename)
        if result:
            print(f"[Way2.1 Fast] ✅ passed successfully arXiv ID Get information")
            return result
        print(f"[Way2.1 Fast] ❌ pass arXiv ID Failed to obtain, continue to downgrade strategy")

    # ========================================================================
    # 2.2 from PDF metadata extract '/arXivID'
    # ========================================================================
    pdf_metadata = extract_pdf_arxiv_metadata(pdf_path)

    if pdf_metadata["arxiv_id"]:
        print(
            f"[Way2.2 Fast] from PDF metadata Extract to arXiv ID: {pdf_metadata['arxiv_id']}"
        )
        result = fetch_paper_by_arxiv_id(pdf_metadata["arxiv_id"])
        if result:
            print(f"[Way2.2 Fast] ✅ passed successfully arXiv ID Get information")
            return result
        print(f"[Way2.2 Fast] ❌ pass arXiv ID Failed to obtain, continue to downgrade strategy")

    # ========================================================================
    # 2.3 use PDF metadata of '/Title' and '/Author' search
    # ========================================================================
    if pdf_metadata["title"] and pdf_metadata["authors"]:
        print(f"[Way2.3 Fast] use PDF metadata Title and author search")

        # Extract the first author (for search)
        authors = pdf_metadata["authors"].split(",")[0].strip()

        result = search_arxiv_by_title_and_author(pdf_metadata["title"], authors)
        if result:
            print(f"[Way2.3 Fast] ✅ Successfully found matching paper")
            return result
        print(f"[Way2.3 Fast] ❌ No match found, continue with downgrade strategy")

    # ========================================================================
    # 2.4 use PDF Parse and extract title, then search for
    # ========================================================================
    print(f"[Way2.4 Fast] use PDF Parse and extract titles")

    # Try using font size extraction
    title = None
    if not pdf_metadata["title"]:
        title = extract_title_by_fontsize(pdf_path)
        if title:
            print(f"[Way2.4 Fast] Extract title by font size: {title[:50]}...")

    # If font extraction fails, try text analysis
    if not title:
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                if len(pdf_reader.pages) > 0:
                    full_text = ""
                    pages_to_extract = min(3, len(pdf_reader.pages))
                    for i in range(pages_to_extract):
                        page_text = pdf_reader.pages[i].extract_text()
                        if page_text:
                            full_text += page_text + "\n"

                    if full_text:
                        full_text = preprocess_pdf_text(full_text)
                        title = extract_title_from_text(full_text)
                        if title:
                            print(
                                f"[Way2.4 Fast] Extract titles through text analysis: {title[:50]}..."
                            )
        except Exception as exc:
            print(f"[Way2.4 Fast] Text extraction failed: {exc}")

    # if still not title, try using PDF metadata of title
    if not title:
        title = pdf_metadata["title"]

    # Use the extracted title search
    if title:
        result = search_arxiv_by_title_only(title)
        if result:
            print(f"[Way2.4 Fast] ✅ Successfully found matching paper")
            return result
        print(f"[Way2.4 Fast] ❌ No matching paper found")
    else:
        print(f"[Way2.4 Fast] ❌ Unable to extract title")

    print(f"[Way2 Fast] ❌ All strategies failed, unable to obtain paper information")
    return None


