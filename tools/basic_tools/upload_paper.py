"""
论文上传处理模块

提供两种论文上传方式：
1. 链接下载：通过 arXiv ID 直接下载并获取信息
2. PDF 上传：多级降级策略从 PDF 提取信息并获取元数据

处理逻辑：
- 方式1（链接下载）：arXiv ID → arXiv API → 获取完整信息 → DBLP 覆盖 BibTeX
- 方式2（PDF上传）：
  2.1 从文件名提取 arXiv ID → 跳转到方式1
  2.2 从 PDF metadata 的 '/arXivID' 提取 → 跳转到方式1
  2.3 从 PDF metadata 的 '/Title' 和 '/Author' 搜索 arXiv
  2.4 使用 PDF 解析提取 title，然后搜索 arXiv
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

import arxiv
import PyPDF2

from tools.basic_tools.arxiv_client import get_bibtex_enhanced
from tools.basic_tools.pdf_extractor import (
    extract_title_by_fontsize,
    extract_title_from_text,
    preprocess_pdf_text,
)

# ============================================================================
# 工具函数
# ============================================================================


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """
    标准化 arXiv ID

    Args:
        arxiv_id: 可能是 "arXiv:2502.05383", "2502.05383", "2502.05383v1" 等格式

    Returns:
        标准化的 arXiv ID（如 "2502.05383"），去掉版本号
    """
    # 移除 "arXiv:" 前缀（不区分大小写）
    arxiv_id = re.sub(r"^arxiv\s*:\s*", "", arxiv_id.strip(), flags=re.IGNORECASE)

    # 移除版本号（v1, v2 等）
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)

    # 提取核心 ID（YYYY.NNNNN 格式）
    match = re.search(r"(\d{4}\.\d{4,5})", arxiv_id)
    if match:
        return match.group(1)

    return arxiv_id


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """
    从 URL 中提取 arXiv ID

    Args:
        url: 可能是 "https://arxiv.org/abs/2511.13720v1" 或 "https://doi.org/10.48550/arXiv.2511.13720"

    Returns:
        提取的 arXiv ID，失败返回 None
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
    从文件名中提取 arXiv ID

    支持格式：
    - 1706.03762v7.pdf
    - arXiv:1706.03762v7.pdf
    - 1706.03762.pdf

    Args:
        filename: PDF 文件名

    Returns:
        提取的 arXiv ID，失败返回 None
    """
    # 移除 .pdf 后缀
    base = os.path.splitext(filename)[0]

    # 匹配 YYYY.NNNNNvN 格式
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", base)
    if match:
        return _normalize_arxiv_id(match.group(0))

    # 匹配 arXiv:YYYY.NNNNNvN 格式
    match = re.search(r"arxiv[:\-\s]?(\d{4}\.\d{4,5})(v\d+)?", base, re.IGNORECASE)
    if match:
        return _normalize_arxiv_id(match.group(0))

    return None


# ============================================================================
# 方式1: 通过 arXiv ID 获取论文信息
# ============================================================================


def fetch_paper_by_arxiv_id_fast(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    快速版本：仅通过 arXiv API 获取论文信息（不等待 DBLP）

    Args:
        arxiv_id: arXiv ID（如 "2502.05383" 或 "arXiv:2502.05383"）

    Returns:
        论文信息字典，bibtex 字段为空（后续由 DBLP 填充）
    """
    try:
        # 标准化 arXiv ID
        arxiv_id = _normalize_arxiv_id(arxiv_id)
        print(f"[arXiv Fast] 通过 arXiv ID 获取论文: {arxiv_id}")

        # 调用 arXiv API
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id])

        paper = next(client.results(search), None)
        if not paper:
            print(f"[arXiv Fast] 未找到 arXiv ID: {arxiv_id}")
            return None

        # 获取作者信息
        authors_list = [author.name for author in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,  # 保留原始格式
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",  # arXiv 链接
            "bibtex": "",  # 暂时为空，后台获取 DBLP 后填充
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        print(f"[arXiv Fast] ✅ 成功获取论文: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[arXiv Fast] ❌ 获取论文失败: {exc}")
        import traceback

        traceback.print_exc()
        return None


def fetch_bibtex_from_dblp(title: str, authors: str, arxiv_id: str) -> Optional[str]:
    """
    从 DBLP 获取 BibTeX（可在后台调用）

    Args:
        title: 论文标题
        authors: 作者字符串
        arxiv_id: arXiv ID

    Returns:
        BibTeX 字符串，失败返回 None
    """
    try:
        print(f"[DBLP] 获取 BibTeX: {title[:50]}...")
        bibtex = get_bibtex_enhanced(title=title, authors=authors, arxiv_id=arxiv_id)
        if bibtex:
            print(f"[DBLP] ✅ 成功获取 BibTeX")
        else:
            print(f"[DBLP] ❌ 未获取到 BibTeX")
        return bibtex
    except Exception as exc:
        print(f"[DBLP] ❌ 获取 BibTeX 失败: {exc}")
        return None


def fetch_paper_by_arxiv_id(arxiv_id: str) -> Optional[Dict[str, Any]]:
    """
    方式1: 通过 arXiv ID 获取完整论文信息（包含 DBLP BibTeX）

    流程：
    1. 标准化 arXiv ID
    2. 调用 arXiv API 获取基本信息（title, authors, abstract, year等）
    3. 使用 title + authors 从 DBLP 获取更好的 BibTeX（如果找到则覆盖）

    Args:
        arxiv_id: arXiv ID（如 "2502.05383" 或 "arXiv:2502.05383"）

    Returns:
        论文信息字典，包含以下字段：
        - title: 论文标题
        - authors: 作者字符串（逗号分隔）
        - abstract: 摘要
        - year: 发表年份
        - arxiv_id: arXiv ID
        - bibtex: BibTeX 引用（优先 DBLP，失败后用 arXiv）
        - published_date: 发布日期
        - pdf_url: PDF 下载链接
        - primary_category: 主要分类
        如果失败返回 None
    """
    # 先快速获取 arXiv 信息
    result = fetch_paper_by_arxiv_id_fast(arxiv_id)
    if not result:
        return None

    # 然后获取 DBLP BibTeX
    bibtex = fetch_bibtex_from_dblp(
        title=result["title"], authors=result["authors"], arxiv_id=result["arxiv_id"]
    )
    if bibtex:
        result["bibtex"] = bibtex

    return result


# ============================================================================
# 方式2: PDF 上传处理（多级降级策略）
# ============================================================================


def extract_pdf_arxiv_metadata(pdf_path: str) -> Dict[str, Optional[str]]:
    """
    从 PDF metadata 中提取 arXiv 相关信息

    查找字段：
    - '/arXivID': arXiv ID（可能是 URL 格式）
    - '/Title': 论文标题
    - '/Author': 作者信息

    Args:
        pdf_path: PDF 文件路径

    Returns:
        包含以下字段的字典：
        - arxiv_id: 提取的 arXiv ID（如果找到）
        - title: 标题（如果找到）
        - authors: 作者（如果找到）
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

            # 查找 '/arXivID' 字段
            arxiv_id_raw = (
                meta.get("/arXivID") or meta.get("/arxiv_id") or meta.get("/ArxivID")
            )
            if arxiv_id_raw:
                arxiv_id_str = str(arxiv_id_raw).strip()
                print(f"[PDF Metadata] 找到 /arXivID: {arxiv_id_str}")

                # 如果是 URL，尝试提取 ID
                arxiv_id = _extract_arxiv_id_from_url(arxiv_id_str)
                if not arxiv_id:
                    # 如果不是 URL，直接作为 ID 处理
                    arxiv_id = _normalize_arxiv_id(arxiv_id_str)

                if arxiv_id:
                    result["arxiv_id"] = arxiv_id
                    print(f"[PDF Metadata] 提取的 arXiv ID: {arxiv_id}")

            # 查找 '/Title' 字段
            title = meta.get("/Title")
            if title and title.strip() and len(title.strip()) > 5:
                result["title"] = title.strip()
                print(f"[PDF Metadata] 找到 /Title: {result['title'][:50]}...")

            # 查找 '/Author' 字段
            authors = meta.get("/Author")
            if authors and authors.strip():
                result["authors"] = authors.strip()
                print(f"[PDF Metadata] 找到 /Author: {result['authors']}")

            return result

    except Exception as exc:
        print(f"[PDF Metadata] 提取失败: {exc}")
        return result


def search_arxiv_by_title_and_author_fast(
    title: str, author: str
) -> Optional[Dict[str, Any]]:
    """
    快速版本：使用标题和作者搜索 arXiv 论文（不等待 DBLP）

    Args:
        title: 论文标题
        author: 作者姓名（可以是第一个作者）

    Returns:
        论文信息字典，bibtex 字段为空
    """
    try:
        # 清理标题中的特殊字符（如冒号）
        clean_title = title.replace(":", " ")

        # 构造查询字符串
        query = f'ti:"{clean_title}" AND au:"{author}"'
        print(f"[方式2.3 Fast] 使用标题+作者搜索 arXiv: [{query}]")

        # 使用 arxiv 库搜索
        client = arxiv.Client()
        search = arxiv.Search(
            query=query, max_results=1, sort_by=arxiv.SortCriterion.Relevance
        )

        paper = next(client.results(search), None)
        if not paper:
            print(f"[方式2.3 Fast] 未找到匹配论文")
            return None

        # 提取 arXiv ID
        arxiv_id = paper.entry_id.split("/")[-1]
        arxiv_id = _normalize_arxiv_id(arxiv_id)

        # 获取作者信息
        authors_list = [a.name for a in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "bibtex": "",  # 暂时为空，后台获取 DBLP 后填充
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        print(f"[方式2.3 Fast] ✅ 找到匹配论文: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[方式2.3 Fast] ❌ 搜索失败: {exc}")
        import traceback

        traceback.print_exc()
        return None


def search_arxiv_by_title_only_fast(title: str) -> Optional[Dict[str, Any]]:
    """
    快速版本：仅使用标题搜索 arXiv 论文（不等待 DBLP）

    Args:
        title: 论文标题

    Returns:
        论文信息字典，bibtex 字段为空
    """
    try:
        print(f"[方式2.4 Fast] 使用标题搜索 arXiv: {title[:50]}...")

        # 使用 arxiv 库搜索
        client = arxiv.Client()
        search = arxiv.Search(
            query=f'ti:"{title}"', max_results=1, sort_by=arxiv.SortCriterion.Relevance
        )

        paper = next(client.results(search), None)
        if not paper:
            print(f"[方式2.4 Fast] 未找到匹配论文")
            return None

        # 提取 arXiv ID
        arxiv_id = paper.entry_id.split("/")[-1]
        arxiv_id = _normalize_arxiv_id(arxiv_id)

        # 获取作者信息
        authors_list = [a.name for a in paper.authors]
        authors_str = ", ".join(authors_list)

        result = {
            "title": paper.title,
            "authors": authors_str,
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,
            "year": str(paper.published.year) if paper.published else None,
            "arxiv_id": arxiv_id,
            "bibtex": "",  # 暂时为空，后台获取 DBLP 后填充
            "published_date": paper.published.isoformat() if paper.published else None,
            "pdf_url": paper.pdf_url,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        print(f"[方式2.4 Fast] ✅ 找到匹配论文: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"[方式2.4 Fast] ❌ 搜索失败: {exc}")
        import traceback

        traceback.print_exc()
        return None


def search_arxiv_by_title_and_author(
    title: str, author: str
) -> Optional[Dict[str, Any]]:
    """
    使用标题和作者搜索 arXiv 论文（包含 DBLP BibTeX）

    使用 arXiv 查询语法: ti:"标题" AND au:"作者"

    Args:
        title: 论文标题
        author: 作者姓名（可以是第一个作者）

    Returns:
        论文信息字典（格式同 fetch_paper_by_arxiv_id），失败返回 None
    """
    # 先快速获取 arXiv 信息
    result = search_arxiv_by_title_and_author_fast(title, author)
    if not result:
        return None

    # 然后获取 DBLP BibTeX
    bibtex = fetch_bibtex_from_dblp(
        title=result["title"], authors=result["authors"], arxiv_id=result["arxiv_id"]
    )
    if bibtex:
        result["bibtex"] = bibtex

    return result


def search_arxiv_by_title_only(title: str) -> Optional[Dict[str, Any]]:
    """
    仅使用标题搜索 arXiv 论文（包含 DBLP BibTeX）

    Args:
        title: 论文标题

    Returns:
        论文信息字典（格式同 fetch_paper_by_arxiv_id），失败返回 None
    """
    # 先快速获取 arXiv 信息
    result = search_arxiv_by_title_only_fast(title)
    if not result:
        return None

    # 然后获取 DBLP BibTeX
    bibtex = fetch_bibtex_from_dblp(
        title=result["title"], authors=result["authors"], arxiv_id=result["arxiv_id"]
    )
    if bibtex:
        result["bibtex"] = bibtex

    return result


def process_uploaded_pdf_fast(pdf_path: str, filename: str) -> Optional[Dict[str, Any]]:
    """
    快速版本：处理上传的 PDF 文件（不等待 DBLP）

    处理流程（与 process_uploaded_pdf 相同，但不等待 DBLP）：
    2.1 从文件名提取 arXiv ID → 如果找到，快速获取 arXiv 信息
    2.2 从 PDF metadata 的 '/arXivID' 提取 → 如果找到，快速获取 arXiv 信息
    2.3 从 PDF metadata 的 '/Title' 和 '/Author' 搜索 arXiv
    2.4 使用 PDF 解析提取 title，然后仅用 title 搜索 arXiv

    Args:
        pdf_path: PDF 文件路径
        filename: PDF 文件名

    Returns:
        论文信息字典，bibtex 字段为空（后续由 DBLP 填充）
    """
    print(f"[方式2 Fast] 开始处理 PDF: {filename}")

    # ========================================================================
    # 2.1 从文件名提取 arXiv ID
    # ========================================================================
    arxiv_id_from_filename = _extract_arxiv_id_from_filename(filename)
    if arxiv_id_from_filename:
        print(f"[方式2.1 Fast] 从文件名提取到 arXiv ID: {arxiv_id_from_filename}")
        result = fetch_paper_by_arxiv_id_fast(arxiv_id_from_filename)
        if result:
            print(f"[方式2.1 Fast] ✅ 成功通过 arXiv ID 获取信息")
            return result
        print(f"[方式2.1 Fast] ❌ 通过 arXiv ID 获取失败，继续降级策略")

    # ========================================================================
    # 2.2 从 PDF metadata 提取 '/arXivID'
    # ========================================================================
    pdf_metadata = extract_pdf_arxiv_metadata(pdf_path)

    if pdf_metadata["arxiv_id"]:
        print(
            f"[方式2.2 Fast] 从 PDF metadata 提取到 arXiv ID: {pdf_metadata['arxiv_id']}"
        )
        result = fetch_paper_by_arxiv_id_fast(pdf_metadata["arxiv_id"])
        if result:
            print(f"[方式2.2 Fast] ✅ 成功通过 arXiv ID 获取信息")
            return result
        print(f"[方式2.2 Fast] ❌ 通过 arXiv ID 获取失败，继续降级策略")

    # ========================================================================
    # 2.3 使用 PDF metadata 的 '/Title' 和 '/Author' 搜索
    # ========================================================================
    if pdf_metadata["title"] and pdf_metadata["authors"]:
        print(f"[方式2.3 Fast] 使用 PDF metadata 的标题和作者搜索")

        # 提取第一个作者（用于搜索）
        authors = pdf_metadata["authors"].split(",")[0].strip()

        result = search_arxiv_by_title_and_author_fast(pdf_metadata["title"], authors)
        if result:
            print(f"[方式2.3 Fast] ✅ 成功找到匹配论文")
            return result
        print(f"[方式2.3 Fast] ❌ 未找到匹配，继续降级策略")

    # ========================================================================
    # 2.4 使用 PDF 解析提取 title，然后搜索
    # ========================================================================
    print(f"[方式2.4 Fast] 使用 PDF 解析提取标题")

    # 尝试使用字体大小提取
    title = None
    if not pdf_metadata["title"]:
        title = extract_title_by_fontsize(pdf_path)
        if title:
            print(f"[方式2.4 Fast] 通过字体大小提取到标题: {title[:50]}...")

    # 如果字体提取失败，尝试文本分析
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
                                f"[方式2.4 Fast] 通过文本分析提取到标题: {title[:50]}..."
                            )
        except Exception as exc:
            print(f"[方式2.4 Fast] 文本提取失败: {exc}")

    # 如果还是没有 title，尝试使用 PDF metadata 的 title
    if not title:
        title = pdf_metadata["title"]

    # 使用提取的 title 搜索
    if title:
        result = search_arxiv_by_title_only_fast(title)
        if result:
            print(f"[方式2.4 Fast] ✅ 成功找到匹配论文")
            return result
        print(f"[方式2.4 Fast] ❌ 未找到匹配论文")
    else:
        print(f"[方式2.4 Fast] ❌ 无法提取标题")

    print(f"[方式2 Fast] ❌ 所有策略都失败，无法获取论文信息")
    return None


def process_uploaded_pdf(pdf_path: str, filename: str) -> Optional[Dict[str, Any]]:
    """
    方式2: 处理上传的 PDF 文件（多级降级策略，包含 DBLP BibTeX）

    处理流程：
    2.1 从文件名提取 arXiv ID → 如果找到，跳转到方式1（fetch_paper_by_arxiv_id）
    2.2 从 PDF metadata 的 '/arXivID' 提取 → 如果找到，跳转到方式1
    2.3 从 PDF metadata 的 '/Title' 和 '/Author' 搜索 arXiv（使用 title+author）
    2.4 使用 PDF 解析提取 title，然后仅用 title 搜索 arXiv

    Args:
        pdf_path: PDF 文件路径
        filename: PDF 文件名

    Returns:
        论文信息字典（格式同 fetch_paper_by_arxiv_id），失败返回 None
    """
    # 先快速获取 arXiv 信息
    result = process_uploaded_pdf_fast(pdf_path, filename)
    if not result:
        return None

    # 然后获取 DBLP BibTeX
    if result.get("title") and result.get("authors") and result.get("arxiv_id"):
        bibtex = fetch_bibtex_from_dblp(
            title=result["title"],
            authors=result["authors"],
            arxiv_id=result["arxiv_id"],
        )
        if bibtex:
            result["bibtex"] = bibtex

    return result
