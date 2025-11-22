"""
使用官方 arxiv 库的增强版 arXiv 客户端
提供更完整的论文信息，包括 BibTeX
优先使用 DBLP 获取 BibTeX，失败后使用 arXiv
"""

from __future__ import annotations

import re
import urllib.request
from typing import Optional

import arxiv
import requests


def _extract_author_names(authors_str: str, max_authors: int = 3) -> str:
    """
    从作者字符串中提取前 N 个作者的姓氏

    Args:
        authors_str: 作者字符串，格式如 "First Last, First Last, ..."
        max_authors: 最多提取的作者数量

    Returns:
        前 N 个作者的姓氏，用空格分隔
    """
    if not authors_str:
        return ""

    # 分割作者
    authors = [a.strip() for a in authors_str.split(",")]
    author_names = []

    for author in authors[:max_authors]:
        # 提取姓氏（最后一个词）
        parts = author.split()
        if parts:
            # 取最后一个词作为姓氏
            last_name = parts[-1]
            author_names.append(last_name)

    return " ".join(author_names)


def get_bibtex_from_dblp(title: str, authors: Optional[str] = None) -> Optional[str]:
    """
    通过 DBLP API 获取论文的 BibTeX

    Args:
        title: 论文标题
        authors: 作者字符串（可选），格式如 "First Last, First Last, ..."

    Returns:
        成功则返回 BibTeX 字符串，失败则返回 None
    """
    try:
        # 提取前三个作者的姓氏
        author_query = ""
        if authors:
            author_names = _extract_author_names(authors, max_authors=3)
            if author_names:
                author_query = author_names

        # 构造搜索查询
        if author_query:
            query_string = f"{title} {author_query}"
        else:
            query_string = title

        search_url = "https://dblp.org/search/publ/api"
        params = {"q": query_string, "format": "json", "h": 1}

        print(f"[DBLP] 搜索: [{query_string}]")

        # 设置超时
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 解析搜索结果
        try:
            hits = data["result"]["hits"]["hit"]
        except KeyError:
            print("[DBLP] 返回数据格式异常")
            return None

        if not hits:
            print("[DBLP] 未找到相关论文")
            return None

        # 获取 BibTeX Key
        first_hit = hits[0]["info"]
        paper_key = first_hit["key"]
        bib_url = f"https://dblp.org/rec/{paper_key}.bib"

        # 获取 BibTeX
        bib_response = requests.get(bib_url, params={"view": 0}, timeout=10)
        bib_response.raise_for_status()

        bibtex = bib_response.text
        print(f"[DBLP] 成功获取 BibTeX")
        return bibtex

    except requests.exceptions.RequestException as e:
        print(f"[DBLP] 网络请求错误: {e}")
        return None
    except Exception as e:
        print(f"[DBLP] 发生错误: {e}")
        return None


def get_bibtex_enhanced(
    title: str, authors: Optional[str] = None, arxiv_id: Optional[str] = None
) -> Optional[str]:
    """
    获取论文的 BibTeX，优先使用 DBLP，失败后使用 arXiv

    Args:
        title: 论文标题
        authors: 作者字符串（可选）
        arxiv_id: arXiv ID（可选），作为降级方案

    Returns:
        BibTeX 字符串，如果都失败则返回 None
    """
    # 优先尝试 DBLP（更准确，特别是对于已发表的论文）
    if title:
        bibtex = get_bibtex_from_dblp(title, authors)
        if bibtex:
            return bibtex

    # DBLP 失败，如果有 arXiv ID，尝试从 arXiv 获取
    if arxiv_id:
        try:
            bibtex_url = f"https://arxiv.org/bibtex/{arxiv_id}"
            with urllib.request.urlopen(bibtex_url, timeout=10) as response:
                bibtex = response.read().decode("utf-8")
                if bibtex and not bibtex.startswith("Error"):
                    print(f"[arXiv] 成功获取 BibTeX (ID: {arxiv_id})")
                    return bibtex
        except Exception as exc:
            print(f"[arXiv] 获取 BibTeX 失败: {exc}")

    print("[BibTeX] 所有来源都失败")
    return None
