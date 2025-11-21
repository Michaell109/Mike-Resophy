"""
使用官方 arxiv 库的增强版 arXiv 客户端
提供更完整的论文信息，包括 BibTeX
"""

from __future__ import annotations

import urllib.request
from typing import Optional

import arxiv


def search_arxiv_by_title_enhanced(
    title: str, max_results: int = 3
) -> Optional[list[dict]]:
    """
    通过标题搜索 arXiv 论文（使用官方 arxiv 库）

    Args:
        title: 论文标题
        max_results: 最多返回结果数

    Returns:
        匹配的论文列表，包含完整信息和 BibTeX
    """
    try:
        client = arxiv.Client()

        # 创建搜索查询
        search = arxiv.Search(
            query=f'ti:"{title}"',
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        print(f"搜索 arXiv: {title}")
        results = []

        for paper in client.results(search):
            arxiv_id = paper.entry_id.split("/")[-1].replace("v", ".").split(".")[0:2]
            arxiv_id = ".".join(arxiv_id)

            # 获取 BibTeX
            bibtex = None
            try:
                bibtex_url = f"https://arxiv.org/bibtex/{arxiv_id}"
                with urllib.request.urlopen(bibtex_url, timeout=10) as response:
                    bibtex = response.read().decode("utf-8")
            except Exception as exc:
                print(f"获取 BibTeX 失败: {exc}")

            result = {
                "title": paper.title,
                "authors": ", ".join([author.name for author in paper.authors]),
                "abstract": paper.summary.replace("\n", " ").strip(),
                "summary": paper.summary,  # 保留原始格式的摘要
                "arxiv_id": arxiv_id,
                "published_date": (
                    paper.published.isoformat() if paper.published else None
                ),
                "year": str(paper.published.year) if paper.published else None,
                "pdf_url": paper.pdf_url,
                "bibtex": bibtex,
                "primary_category": paper.primary_category,
                "categories": paper.categories,
            }
            results.append(result)

        if results:
            print(f"找到 {len(results)} 个匹配结果")
            return results
        else:
            print("未找到匹配的论文")
            return None

    except Exception as exc:
        print(f"搜索 arXiv 失败: {exc}")
        import traceback

        traceback.print_exc()
        return None


def fetch_arxiv_by_id_enhanced(arxiv_id: str) -> Optional[dict]:
    """
    通过 arXiv ID 获取完整论文信息

    Args:
        arxiv_id: arXiv ID (如 2301.12345)

    Returns:
        论文信息字典，包含 BibTeX
    """
    try:
        client = arxiv.Client()

        # 清理 arXiv ID
        arxiv_id = arxiv_id.strip().replace("v", ".").split(".")[0:2]
        arxiv_id = ".".join(arxiv_id) if isinstance(arxiv_id, list) else arxiv_id

        search = arxiv.Search(id_list=[arxiv_id])

        print(f"获取 arXiv 论文: {arxiv_id}")
        paper = next(client.results(search), None)

        if not paper:
            print(f"未找到 arXiv ID: {arxiv_id}")
            return None

        # 获取 BibTeX
        bibtex = None
        try:
            bibtex_url = f"https://arxiv.org/bibtex/{arxiv_id}"
            with urllib.request.urlopen(bibtex_url, timeout=10) as response:
                bibtex = response.read().decode("utf-8")
        except Exception as exc:
            print(f"获取 BibTeX 失败: {exc}")

        result = {
            "title": paper.title,
            "authors": ", ".join([author.name for author in paper.authors]),
            "abstract": paper.summary.replace("\n", " ").strip(),
            "summary": paper.summary,  # 保留原始格式
            "arxiv_id": arxiv_id,
            "published_date": paper.published.isoformat() if paper.published else None,
            "year": str(paper.published.year) if paper.published else None,
            "pdf_url": paper.pdf_url,
            "bibtex": bibtex,
            "primary_category": paper.primary_category,
            "categories": paper.categories,
        }

        print(f"成功获取论文: {result['title'][:50]}...")
        return result

    except Exception as exc:
        print(f"获取 arXiv 论文失败: {exc}")
        import traceback

        traceback.print_exc()
        return None
