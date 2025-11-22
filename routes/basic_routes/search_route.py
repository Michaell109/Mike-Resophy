from __future__ import annotations

import json
import os
from difflib import SequenceMatcher
from typing import Dict, Optional, Protocol, Tuple

from flask import Flask, jsonify, request


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


def _fuzzy_match(query: str, text: str, threshold: float = 0.6) -> Tuple[bool, float]:
    """
    模糊匹配函数

    Args:
        query: 查询字符串
        text: 待匹配文本
        threshold: 相似度阈值（0-1），默认 0.6

    Returns:
        (是否匹配, 相似度分数)
    """
    if not query or not text:
        return (False, 0.0)

    query_lower = query.lower()
    text_lower = text.lower()

    # 1. 精确匹配（包含）
    if query_lower in text_lower:
        return (True, 1.0)

    # 2. 单词匹配（查询词作为完整单词出现）
    words = text_lower.split()
    for word in words:
        if query_lower in word or word in query_lower:
            # 计算相似度
            similarity = SequenceMatcher(None, query_lower, word).ratio()
            if similarity >= threshold:
                return (True, similarity)

    # 3. 子序列匹配（查询词的字符按顺序出现在文本中）
    query_chars = list(query_lower)
    text_chars = list(text_lower)

    i = 0
    for char in text_chars:
        if i < len(query_chars) and char == query_chars[i]:
            i += 1

    if i == len(query_chars):
        # 所有字符都找到了，计算相似度
        similarity = SequenceMatcher(None, query_lower, text_lower).ratio()
        if similarity >= threshold:
            return (True, similarity)

    # 4. 通用相似度匹配
    similarity = SequenceMatcher(None, query_lower, text_lower).ratio()
    if similarity >= threshold:
        return (True, similarity)

    return (False, similarity)


def register_search_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    upload_folder: str,
) -> None:
    @app.route("/api/search")
    def api_search():
        """
        搜索 title/authors/abstract。支持全局或限定某个分类。
        支持模糊匹配和精确匹配。
        """
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"results": []})

        # 获取模糊匹配阈值（可选参数，默认 0.6）
        fuzzy_threshold = float(request.args.get("fuzzy_threshold", 0.6))
        use_fuzzy = request.args.get("fuzzy", "true").lower() == "true"

        base_search_dir = upload_folder
        category_id = (request.args.get("category_id") or "").strip()
        if category_id:
            categories = get_categories()
            path = get_category_path(categories, category_id)
            if path and len(path) > 1:
                base_search_dir = os.path.join(upload_folder, *path[1:])

        results = []
        categories = get_categories()

        for root, dirs, files in os.walk(base_search_dir):
            for fname in files:
                if not fname.lower().endswith(".json"):
                    continue
                json_path = os.path.join(root, fname)
                try:
                    with open(json_path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                except Exception:
                    continue

                pid = data.get("id")
                title = data.get("title") or data.get("filename") or ""
                authors = data.get("authors") or ""
                abstract = data.get("abstract") or ""

                matched_fields = []
                max_similarity = 0.0

                # 尝试匹配每个字段
                for field_name, field_text in [
                    ("title", title),
                    ("authors", authors),
                    ("abstract", abstract),
                ]:
                    if not field_text:
                        continue

                    if use_fuzzy:
                        # 使用模糊匹配
                        is_match, similarity = _fuzzy_match(
                            query, field_text, fuzzy_threshold
                        )
                        if is_match:
                            matched_fields.append(field_name)
                            max_similarity = max(max_similarity, similarity)
                    else:
                        # 使用精确匹配（向后兼容）
                        query_lower = query.lower()
                        if query_lower in field_text.lower():
                            matched_fields.append(field_name)
                            max_similarity = 1.0

                if matched_fields:
                    # 尝试从 JSON 文件路径推断分类
                    paper_category_id = None

                    # 方法1: 从 JSON 数据中读取（如果存在）
                    if "category_id" in data:
                        paper_category_id = data.get("category_id")
                    else:
                        # 方法2: 从文件路径推断分类
                        rel_path = os.path.relpath(json_path, upload_folder)
                        path_parts = os.path.dirname(rel_path).split(os.sep)

                        # 过滤掉空字符串和 "."
                        path_parts = [p for p in path_parts if p and p != "."]

                        if path_parts:
                            # 尝试在分类树中查找匹配的分类路径
                            def find_category_by_path(node, target_path):
                                node_path = get_category_path(
                                    categories, node.get("id")
                                )
                                if node_path and len(node_path) > 1:
                                    node_path_parts = list(node_path[1:])  # 去掉 root
                                    # 检查路径是否匹配
                                    if node_path_parts == target_path:
                                        return node.get("id")

                                for child in node.get("children", []):
                                    result = find_category_by_path(child, target_path)
                                    if result:
                                        return result
                                return None

                            paper_category_id = find_category_by_path(
                                categories, path_parts
                            )

                    results.append(
                        {
                            "id": pid,
                            "title": title,
                            "authors": authors,
                            "abstract": abstract,
                            "filename": data.get("filename"),
                            "matched_fields": matched_fields,
                            "similarity": max_similarity,  # 最高相似度
                            "category_id": paper_category_id,  # 论文所属分类
                        }
                    )

        # 排序：先按匹配字段数量，再按相似度，最后按标题
        results.sort(
            key=lambda r: (
                -len(r["matched_fields"]),  # 匹配字段多者优先
                -r.get("similarity", 0.0),  # 相似度高者优先
                r.get("title") or "",  # 标题字母序
            )
        )
        return jsonify({"results": results})
