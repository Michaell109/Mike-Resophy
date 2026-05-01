from __future__ import annotations

import re
from typing import Optional

import fitz  # PyMuPDF


def preprocess_pdf_text(text: str) -> str:
    """Normalize raw text extracted from PDF pages."""
    if not text:
        return ""
    t = text
    t = re.sub(r"-\s*\n\s*", "", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\t\f]+", " ", t)
    t = re.sub(r" ", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    return t


def extract_title_by_fontsize(pdf_path: str) -> Optional[str]:
    """
    Extract titles by font size (enhanced version with position filtering)

    Filter out first arXiv Noisy text in sidebar and header footer,
    Then find the largest font size from the remaining text as the title.
    """
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None

        page = doc[0]
        rect = page.rect
        page_width = rect.width
        page_height = rect.height

        blocks = page.get_text("dict")["blocks"]

        all_spans = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text:
                        continue
                    all_spans.append((span["size"], text, span["bbox"]))

        all_spans.sort(key=lambda x: (-x[0], x[2][1]))

        if not all_spans:
            doc.close()
            return None

        title_candidates = []
        target_size = 0

        for size, text, bbox in all_spans:
            if re.search(r"arxiv:\d{4}\.\d+", text, re.IGNORECASE):
                continue
            if len(text) < 5:
                continue
            if re.match(r"^[\d\s\.\-]+$", text):
                continue
            if text.lower() in ["arxiv", "preprint", "abstract", "introduction"]:
                continue
            if bbox[2] < page_width * 0.15:
                continue

            if target_size == 0:
                target_size = size
                title_candidates.append(text)
            elif abs(size - target_size) < 0.5:
                title_candidates.append(text)
            else:
                break

        doc.close()

        if not title_candidates:
            return None

        title = " ".join(title_candidates)
        title = re.sub(r"\s+", " ", title).strip()

        if 10 < len(title) < 500:
            return title

        return None

    except Exception as exc:
        print(f"Failed to extract title by font size: {exc}")
        return None


def extract_title_from_text(text: str) -> Optional[str]:
    """Extract title from raw text as a downgrade solution"""
    lines = text.strip().split("\n")
    for line in lines[:10]:
        line = line.strip()
        if 10 < len(line) < 300:
            if (
                not line.isupper()
                and re.search(r"[a-zA-Z]", line)
                and not re.search(r"^\d+$", line)
                and not re.search(r"^(page|vol|volume|issue|doi|arxiv)", line.lower())
                and not re.search(r"@|\.com|\.org", line.lower())
            ):
                return line
    return None
