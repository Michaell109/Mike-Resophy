from __future__ import annotations

from typing import Dict, Optional, Protocol

from flask import Flask, jsonify, request

from resophy.core.search_index import SearchIndex


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


def register_search_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    upload_folder: str,
    search_index: SearchIndex,
) -> None:
    @app.route("/api/search")
    def api_search():
        """
        搜索 title/authors/abstract。支持全局或限定某个分类。
        使用 SQLite FTS5 全文搜索，性能大幅提升。
        """
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"results": []})

        # 获取结果数量限制（默认 100）
        limit = int(request.args.get("limit", 100))

        # 获取分类ID（可选）
        category_id = (request.args.get("category_id") or "").strip() or None

        # 使用数据库搜索
        try:
            results = search_index.search(
                query=query,
                category_id=category_id,
                limit=limit,
            )

            # 按匹配字段数量和相似度排序（数据库已经按 rank 排序，这里做二次排序）
            results.sort(
                key=lambda r: (
                    -len(r.get("matched_fields", [])),  # 匹配字段多者优先
                    -r.get("similarity", 0.0),  # 相似度高者优先
                    r.get("title") or "",  # 标题字母序
                )
            )

            return jsonify({"results": results})
        except Exception as e:
            print(f"搜索失败: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"results": [], "error": str(e)})
