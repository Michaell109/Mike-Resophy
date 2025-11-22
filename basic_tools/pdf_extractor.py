from __future__ import annotations

import re
from typing import Dict, Optional

import PyPDF2
import fitz  # PyMuPDF


def preprocess_pdf_text(text: str) -> str:
    """Normalize raw text extracted from PDF pages."""
    if not text:
        return ""
    t = text
    t = re.sub(r"-\s*\n\s*", "", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\t\f]+", " ", t)
    t = re.sub(r"\u00A0", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    return t


def extract_title_by_fontsize(pdf_path: str) -> Optional[str]:
    """
    通过字体大小提取标题（增强版，带位置过滤）
    
    优先过滤掉 arXiv 侧边栏和页眉页脚的噪声文本，
    然后从剩余文本中找最大字号的作为标题。
    
    Args:
        pdf_path: PDF 文件路径
        
    Returns:
        提取的标题，如果失败返回 None
    """
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None
            
        page = doc[0]  # 只看第一页
        rect = page.rect
        page_width = rect.width
        page_height = rect.height
        
        blocks = page.get_text("dict")["blocks"]
        
        # 收集所有的文本片段 (size, text, bbox)
        all_spans = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text:
                        continue
                    # 保存: (字体大小, 文本内容, 边界框)
                    all_spans.append((span["size"], text, span["bbox"]))
        
        # 按字体大小从大到小排序，如果大小相同按垂直位置排序
        all_spans.sort(key=lambda x: (-x[0], x[2][1]))
        
        if not all_spans:
            doc.close()
            return None
        
        # 寻找真正的标题（过滤噪声）
        title_candidates = []
        target_size = 0
        
        for size, text, bbox in all_spans:
            # 1. 内容过滤
            if re.search(r"arxiv:\d{4}\.\d+", text, re.IGNORECASE):
                continue
            if len(text) < 5:  # 标题一般不会短于5个字符
                continue
            if re.match(r'^[\d\s\.\-]+$', text):  # 纯数字/符号
                continue
            if text.lower() in ['arxiv', 'preprint', 'abstract', 'introduction']:
                continue
            
            # 2. 位置过滤
            # arXiv 左侧边栏通常在页面宽度的 15% 以内，过滤掉
            if bbox[2] < page_width * 0.15:
                continue
            
            # 3. 确定标题
            if target_size == 0:
                target_size = size
                title_candidates.append(text)
            # 字体一样大（处理多行标题）
            elif abs(size - target_size) < 0.5:
                title_candidates.append(text)
            # 字体明显变小，标题部分结束
            else:
                break
        
        doc.close()
        
        if not title_candidates:
            return None
        
        # 拼接并清理标题
        title = " ".join(title_candidates)
        title = re.sub(r'\s+', ' ', title).strip()
        
        # 长度检查
        if 10 < len(title) < 500:
            return title
        
        return None
        
    except Exception as exc:
        print(f"通过字体大小提取标题失败: {exc}")
        return None


def extract_title_from_text(text: str) -> Optional[str]:
    """旧的文本提取方法，作为降级方案"""
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


def extract_authors_from_text(text: str) -> Optional[str]:
    lines = text.strip().split("\n")
    author_patterns = [
        r"^([A-Z][a-z]+ [A-Z][a-z]+(?:, [A-Z][a-z]+ [A-Z][a-z]+)*)",
        r"^([A-Z]\. [A-Z][a-z]+(?:, [A-Z]\. [A-Z][a-z]+)*)",
        r"^([A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+(?:, [A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+)*)",
    ]
    for line in lines[:15]:
        line = line.strip()
        if 5 < len(line) < 200:
            for pattern in author_patterns:
                match = re.match(pattern, line)
                if match:
                    authors = match.group(1)
                    if re.search(r"[A-Z][a-z]+", authors) and not re.search(
                        r"\d", authors
                    ):
                        return authors
    return None


def extract_affiliation_from_text(text: str) -> Optional[str]:
    lines = text.strip().split("\n")
    institution_keywords = [
        r"university",
        r"college",
        r"institute",
        r"laboratory",
        r"lab",
        r"department",
        r"school",
        r"center",
        r"centre",
        r"research",
        r"academy",
        r"corporation",
        r"company",
        r"inc\.",
        r"ltd\.",
        r"google",
        r"microsoft",
        r"openai",
        r"anthropic",
        r"meta",
        r"stanford",
        r"mit",
        r"harvard",
        r"berkeley",
        r"cambridge",
    ]
    affiliations: list[str] = []
    for line in lines[:20]:
        line_stripped = line.strip()
        if 10 < len(line_stripped) < 300:
            for keyword in institution_keywords:
                if re.search(keyword, line_stripped, re.IGNORECASE):
                    if not re.search(
                        r"^(abstract|introduction|keywords|references)",
                        line_stripped.lower(),
                    ):
                        affiliations.append(line_stripped)
                        break
    unique_affiliations: list[str] = []
    for aff in affiliations:
        if aff not in unique_affiliations:
            unique_affiliations.append(aff)
        if len(unique_affiliations) >= 3:
            break
    return "; ".join(unique_affiliations) if unique_affiliations else None


def extract_abstract_from_text(text: str) -> Optional[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    stop_markers = (
        r"keywords|index\s*terms|subject[s]?|introduction|background|materials\s+and\s+methods|"
        r"methods|results|conclusions|references|acknowledg(e)?ments|1\.|i\.|ii\.|iii\."
        r"|关键词|引言|背景|方法|結果|结论|参考文献"
    )
    start_markers = r"abstract|summary|摘要|概要"
    pattern = rf"(?is)\b(?:{start_markers})\b\s*[:\.\-]?\s*(.+?)(?=\n\s*(?:{stop_markers})\b|\n\n\s*[A-Z][A-Za-z ]+\b|\Z)"
    match = re.search(pattern, normalized)
    if match:
        abstract = re.sub(r"\s+", " ", match.group(1).strip())
        if 50 <= len(abstract) <= 5000 and re.search(r"[a-z]", abstract, re.I):
            return abstract

    lines = normalized.split("\n")
    abstract_started = False
    buffer: list[str] = []
    for line in lines:
        line_stripped = line.strip()
        if not abstract_started:
            if re.match(
                r"(?i)^(abstract|summary|摘要|概要)\b\s*[:\-\.]?\s*$", line_stripped
            ) or re.match(
                r"(?i)^(abstract|summary|摘要|概要)\b\s*[:\-\.]?",
                line_stripped,
            ):
                after = re.sub(
                    r"(?i)^(abstract|summary|摘要|概要)\b\s*[:\-\.]?\s*",
                    "",
                    line_stripped,
                )
                if after:
                    buffer.append(after)
                abstract_started = True
            continue
        else:
            if re.match(rf"(?i)^\s*(?:{stop_markers})\b", line_stripped):
                break
            buffer.append(line)

    candidate = re.sub(r"\s+", " ", " ".join(buffer)).strip()
    if 50 <= len(candidate) <= 5000 and re.search(r"[a-z]", candidate, re.I):
        return candidate

    paragraphs = re.split(r"\n\s*\n", normalized)
    for paragraph in paragraphs[:8]:
        p = re.sub(r"\s+", " ", paragraph.strip())
        if (
            120 <= len(p) <= 5000
            and not re.match(
                r"(?i)^(keywords|index\s*terms|introduction|references|acknowledg(e)?ments|参考文献|引言|关键词)",
                p,
            )
            and p.count(".") >= 2
        ):
            return p
    return None


def extract_pdf_metadata(file_path: str) -> Dict[str, Optional[str]]:
    """
    Extract metadata fields from a PDF file.
    
    标题提取逻辑：
    1. 优先使用 PDF metadata 中的 /Title
    2. 如果没有，使用字体大小 + 位置过滤提取标题
    3. 如果还是失败，使用文本分析方法
    
    其他字段从 PDF metadata 和文本内容中补充。
    """
    metadata: Dict[str, Optional[str]] = {
        "title": None,
        "authors": None,
        "affiliation": None,
        "year": None,
        "subject": None,
        "keywords": None,
        "abstract": None,
    }
    try:
        # 第一步：从 PDF metadata 提取基本信息
        with open(file_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            if pdf_reader.metadata:
                meta = pdf_reader.metadata
                
                # 优先使用 metadata 中的标题
                title_from_meta = meta.get("/Title")
                if title_from_meta and title_from_meta.strip() and len(title_from_meta.strip()) > 5:
                    metadata["title"] = title_from_meta.strip()
                    print(f"[PDF Metadata] 标题: {metadata['title'][:50]}...")
                
                author = meta.get("/Author")
                if author and author.strip():
                    metadata["authors"] = author.strip()
                subject = meta.get("/Subject")
                if subject and subject.strip():
                    metadata["subject"] = subject.strip()
                keywords = meta.get("/Keywords")
                if keywords and keywords.strip():
                    metadata["keywords"] = keywords.strip()
                creation_date = meta.get("/CreationDate")
                if creation_date:
                    year_match = re.search(r"(\d{4})", str(creation_date))
                    if year_match:
                        year = int(year_match.group(1))
                        if 1900 <= year <= 2030:
                            metadata["year"] = str(year)
        
        # 第二步：如果 metadata 没有标题，使用字体大小提取
        if not metadata["title"]:
            title_from_font = extract_title_by_fontsize(file_path)
            if title_from_font:
                metadata["title"] = title_from_font
                print(f"[字体提取] 标题: {title_from_font[:50]}...")
        
        # 第三步：提取文本内容补充缺失信息
        with open(file_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            if len(pdf_reader.pages) > 0:
                try:
                    full_text = ""
                    pages_to_extract = min(3, len(pdf_reader.pages))
                    for i in range(pages_to_extract):
                        page = pdf_reader.pages[i]
                        page_text = page.extract_text()
                        if page_text:
                            full_text += page_text + "\n"
                    
                    if full_text:
                        full_text = preprocess_pdf_text(full_text)
                        
                        # 降级：如果前面都没提取到标题，用文本方法
                        if not metadata["title"]:
                            metadata["title"] = extract_title_from_text(full_text)
                            if metadata["title"]:
                                print(f"[文本提取] 标题: {metadata['title'][:50]}...")
                        
                        if not metadata["authors"]:
                            metadata["authors"] = extract_authors_from_text(full_text)
                        
                        if not metadata["affiliation"]:
                            metadata["affiliation"] = extract_affiliation_from_text(full_text)
                        
                        metadata["abstract"] = extract_abstract_from_text(full_text)
                        
                except Exception as exc:  # noqa: BLE001
                    print(f"提取PDF文本内容失败: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"提取PDF元数据失败: {exc}")
    
    return metadata
