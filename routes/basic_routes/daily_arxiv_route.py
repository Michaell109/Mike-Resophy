"""
Daily arXiv 路由模块

提供 Daily arXiv 功能的 API 接口
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from flask import Flask, jsonify, request, send_file

from core.base_paper import Paper
from core.paper_store import paper_store
from tools.basic_tools.daily_arxiv import (
    DailyArxivManager,
    extract_affiliations_with_llm,
    extract_pdf_first_page_text,
    get_manager,
    get_today_arxiv_date,
)


def register_daily_arxiv_routes(
    app: Flask,
    *,
    daily_arxiv_settings_file: str,
    default_daily_arxiv_settings: Dict[str, Any],
    temp_papers_dir: str,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], List[str] | None],
    create_category_folder: Callable[[List[str]], str],
    save_paper_metadata: Callable[[str, Any], None],
    reading_list_file: str,
    reading_list_temp_dir: str,
    agentic_settings_file: str = None,
) -> None:
    """
    注册 Daily arXiv 相关路由
    """

    # 确保临时目录存在
    os.makedirs(temp_papers_dir, exist_ok=True)

    # 获取管理器实例
    manager = get_manager(temp_papers_dir, daily_arxiv_settings_file)

    # 设置 LLM 配置回调
    def get_llm_config():
        if agentic_settings_file:
            try:
                with open(agentic_settings_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}

    manager.set_llm_config_callback(get_llm_config)

    # 启动调度器
    manager.start_scheduler()

    # ========================================
    # Daily arXiv Settings
    # ========================================
    @app.route("/api/settings/daily-arxiv", methods=["GET", "POST"])
    def api_daily_arxiv_settings():
        """获取或设置 Daily arXiv 配置"""
        if request.method == "GET":
            try:
                with open(daily_arxiv_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"读取 Daily arXiv 设置失败: {exc}")
                settings = {}
            # 合并默认设置，但对于 categories，如果设置文件中为空则使用默认值
            merged = default_daily_arxiv_settings.copy()
            for key, value in settings.items():
                if key == "categories":
                    # 只有当用户设置的 categories 非空时才覆盖
                    if value and len(value) > 0:
                        merged[key] = value
                else:
                    merged[key] = value
            return jsonify(merged)

        # POST: 保存设置
        data = request.json or {}
        try:
            with open(daily_arxiv_settings_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Get Available Dates
    # ========================================
    @app.route("/api/daily-arxiv/dates", methods=["GET"])
    def api_get_available_dates():
        """获取有论文的日期列表"""
        try:
            dates = manager.get_available_dates()
            today = get_today_arxiv_date()
            return jsonify(
                {
                    "success": True,
                    "dates": dates,
                    "today": today,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Get Papers for Date
    # ========================================
    @app.route("/api/daily-arxiv/papers/<date_str>", methods=["GET"])
    def api_get_papers_for_date(date_str: str):
        """获取某日期的论文"""
        try:
            category = request.args.get("category")
            papers = manager.get_papers_for_date(date_str, category)

            # 为每篇论文添加 paper_id（如果已在库中）
            for paper in papers:
                arxiv_id = paper.get("arxiv_id")
                if arxiv_id:
                    # 从 paper_store 中查找论文
                    entry = paper_store.get_by_arxiv_id(arxiv_id)
                    if entry:
                        paper["paper_id"] = entry.paper.id

            return jsonify(
                {
                    "success": True,
                    "papers": papers,
                    "date": date_str,
                    "category": category,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Fetch Papers (Trigger Manual Fetch)
    # ========================================
    @app.route("/api/daily-arxiv/fetch", methods=["POST"])
    def api_fetch_daily_arxiv():
        """手动触发抓取论文（自动抓取指定日期的所有论文）"""
        try:
            data = request.json or {}
            category = data.get("category")
            date_str = data.get("date", get_today_arxiv_date())
            force = data.get("force", False)

            if not category:
                return jsonify({"success": False, "error": "请指定 arXiv 分区"}), 400

            # 在后台线程中执行抓取
            def do_fetch():
                manager.fetch_papers(
                    category,
                    date_str=date_str,
                    force=force,
                )
                # 抓取完成后清除缩略图缓存
                with _thumbnail_cache_lock:
                    cache_key = f"{date_str}_{category}"
                    _thumbnail_cache.pop(cache_key, None)

            thread = threading.Thread(target=do_fetch, daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": f"开始抓取 {category} 论文",
                    "category": category,
                    "date": date_str,
                }
            )

        except Exception as exc:
            print(f"获取 Daily arXiv 论文失败: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Get Fetch Progress
    # ========================================
    @app.route("/api/daily-arxiv/progress/<category>", methods=["GET"])
    def api_get_fetch_progress(category: str):
        """获取抓取进度"""
        try:
            progress = manager.get_progress(category)
            return jsonify(
                {
                    "success": True,
                    "progress": progress,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Fetch All Categories
    # ========================================
    @app.route("/api/daily-arxiv/fetch-all", methods=["POST"])
    def api_fetch_all_categories():
        """抓取所有配置的分区（自动抓取今天所有论文）"""
        try:
            data = request.json or {}
            force = data.get("force", False)

            settings = manager.get_settings()
            categories = settings.get("categories", [])

            if not categories:
                return jsonify({"success": False, "error": "未配置分区"}), 400

            date_str = get_today_arxiv_date()

            # 在后台线程中执行抓取
            def do_fetch_all():
                for cat in categories:
                    manager.fetch_papers(
                        cat,
                        date_str=date_str,
                        force=force,
                    )
                # 抓取完成后清除所有缩略图缓存
                with _thumbnail_cache_lock:
                    _thumbnail_cache.clear()

            thread = threading.Thread(target=do_fetch_all, daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": f"开始抓取 {len(categories)} 个分区",
                    "categories": categories,
                    "date": date_str,
                }
            )

        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Add Paper to Library
    # ========================================
    @app.route("/api/daily-arxiv/add-to-library", methods=["POST"])
    def api_add_arxiv_to_library():
        """将 arXiv 论文添加到文库"""
        try:
            data = request.json or {}
            arxiv_id = data.get("arxiv_id")
            category_id = data.get("category_id")
            date_str = data.get("date", get_today_arxiv_date())
            fetch_category = data.get("fetch_category")
            use_temp_dir = data.get("use_temp_dir", False)  # 是否使用待读列表临时目录

            if not arxiv_id:
                return jsonify({"success": False, "error": "缺少 arxiv_id"}), 400

            # 如果使用 temp 目录，直接使用 temp 目录路径
            if use_temp_dir:
                folder_path = reading_list_temp_dir
                category_path = ["Root", "_ReadingListTemp"]
                category_id = "reading_list_temp"  # 使用特殊 ID
            else:
                if not category_id:
                    return jsonify({"success": False, "error": "请选择目标分类"}), 400

                # 获取分类路径
                categories = get_categories()
                category_path = get_category_path(categories, category_id)
                if not category_path:
                    return jsonify({"success": False, "error": "分类不存在"}), 404

                # 创建分类文件夹
                folder_path = create_category_folder(category_path[1:])

            # 从存储中获取论文信息
            paper_info = None
            papers = manager.get_papers_for_date(date_str, fetch_category)
            for p in papers:
                if p.get("arxiv_id") == arxiv_id:
                    paper_info = p
                    break

            if not paper_info:
                return jsonify({"success": False, "error": "论文信息未找到"}), 404

            # 构造安全文件名
            safe_title = paper_info.get("title", arxiv_id)
            for char in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
                safe_title = safe_title.replace(char, "")
            safe_title = safe_title[:100].strip()

            pdf_filename = f"{safe_title}.pdf"
            target_path = os.path.join(folder_path, pdf_filename)

            # 检查是否已存在：如果已存在，则复用已有的 Paper，而不是报错
            if os.path.exists(target_path):
                # 尝试在 paper_store 中找到对应的论文（通过 arxiv_id 或 file_path）
                existing_paper = None
                try:
                    all_papers = paper_store.iter_all()
                    for p in all_papers:
                        if (
                            getattr(p, "arxiv_id", None) == arxiv_id
                            or getattr(p, "file_path", None) == target_path
                        ):
                            existing_paper = p
                            break
                except Exception as e:
                    print(f"查找已有论文失败: {e}")

                if existing_paper:
                    # 确保该论文在指定分类下注册
                    paper_store.upsert(
                        existing_paper,
                        category_id=category_id,
                        category_path=category_path,
                    )

                    # 如果使用 temp 目录，添加到待读列表
                    if use_temp_dir:
                        try:
                            # 加载待读列表
                            with open(reading_list_file, "r", encoding="utf-8") as f:
                                reading_list_data = json.load(f)
                            paper_ids = reading_list_data.get("papers", [])

                            # 如果论文 ID 不在列表中，添加它
                            if existing_paper.id not in paper_ids:
                                paper_ids.append(existing_paper.id)
                                with open(
                                    reading_list_file, "w", encoding="utf-8"
                                ) as f:
                                    json.dump(
                                        {"papers": paper_ids},
                                        f,
                                        ensure_ascii=False,
                                        indent=2,
                                    )
                        except Exception as e:
                            print(f"添加到待读列表失败: {e}")

                    return jsonify(
                        {
                            "success": True,
                            "paper_id": existing_paper.id,
                            "file_path": existing_paper.file_path,
                            "message": f"该论文已存在于 {'/'.join(category_path[1:])}",
                        }
                    )

                # 找不到对应 Paper，则保持原有报错逻辑
                return (
                    jsonify({"success": False, "error": "该论文已存在于目标分类中"}),
                    400,
                )

            # 复制或下载 PDF
            source_pdf = paper_info.get("local_pdf_path")
            if source_pdf and os.path.exists(source_pdf):
                import shutil

                shutil.copy2(source_pdf, target_path)
            else:
                # 下载
                import urllib.request

                pdf_url = (
                    paper_info.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                )
                print(f"[DailyArxiv] 下载论文到文库: {arxiv_id} -> {target_path}")
                urllib.request.urlretrieve(pdf_url, target_path)

            # 创建论文元数据
            import uuid

            paper = Paper(
                id=str(uuid.uuid4()),
                filename=pdf_filename,
                original_filename=pdf_filename,
                file_path=target_path,
                upload_date=datetime.now().isoformat(),
                title=paper_info.get("title", ""),
                authors=paper_info.get("authors", ""),
                abstract=paper_info.get("abstract", ""),
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
                arxiv_published_date=paper_info.get("published"),
                upload_source="daily_arxiv",
            )

            # 保存元数据
            save_paper_metadata(target_path, paper)

            # 注册到 paper_store
            paper_store.upsert(
                paper,
                category_id=category_id,
                category_path=category_path,
            )

            # 如果使用 temp 目录，添加到待读列表
            if use_temp_dir:
                try:
                    # 加载待读列表
                    with open(reading_list_file, "r", encoding="utf-8") as f:
                        reading_list_data = json.load(f)
                    paper_ids = reading_list_data.get("papers", [])

                    # 如果论文 ID 不在列表中，添加它
                    if paper.id not in paper_ids:
                        paper_ids.append(paper.id)
                        with open(reading_list_file, "w", encoding="utf-8") as f:
                            json.dump(
                                {"papers": paper_ids}, f, ensure_ascii=False, indent=2
                            )
                except Exception as e:
                    print(f"添加到待读列表失败: {e}")

            return jsonify(
                {
                    "success": True,
                    "paper_id": paper.id,
                    "file_path": target_path,
                    "message": f"已添加到 {'/'.join(category_path[1:])}",
                    "is_temp": use_temp_dir,  # 标记是否在 temp 目录
                }
            )

        except Exception as exc:
            print(f"添加论文到文库失败: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Extract Affiliations
    # ========================================
    @app.route("/api/daily-arxiv/extract-affiliations", methods=["POST"])
    def api_extract_affiliations():
        """手动提取论文机构信息、homepage 和 github"""
        try:
            data = request.json or {}
            arxiv_id = data.get("arxiv_id")
            date_str = data.get("date", get_today_arxiv_date())
            fetch_category = data.get("fetch_category")

            if not arxiv_id:
                return jsonify({"success": False, "error": "缺少 arxiv_id"}), 400

            # 从 Agentic Settings 获取 LLM 配置
            llm_config = get_llm_config()
            openai_base_url = llm_config.get("llmBaseUrl")
            openai_api_key = llm_config.get("llmApiKey")

            if not openai_base_url or not openai_api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "请先在设置中配置 Agentic Settings 的 LLM API",
                        }
                    ),
                    400,
                )

            # 获取论文信息
            papers = manager.get_papers_for_date(date_str, fetch_category)
            paper_info = None
            for p in papers:
                if p.get("arxiv_id") == arxiv_id:
                    paper_info = p
                    break

            if not paper_info:
                return jsonify({"success": False, "error": "论文信息未找到"}), 404

            # 获取PDF路径
            pdf_path = paper_info.get("local_pdf_path")
            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({"success": False, "error": "PDF文件不存在"}), 404

            # 获取自定义 prompt
            settings = manager.get_settings()
            affiliation_prompt = settings.get("affiliationPrompt")

            # 提取机构、homepage 和 github
            extraction_result = extract_affiliations_with_llm(
                extract_pdf_first_page_text(pdf_path) or "",
                openai_base_url,
                openai_api_key,
                prompt=affiliation_prompt,
                settings_file=daily_arxiv_settings_file,
            )

            if not extraction_result:
                return (
                    jsonify({"success": False, "error": "提取失败，无法获取结果"}),
                    500,
                )

            # 更新论文信息
            paper_info["affiliations"] = extraction_result.get("affiliations", [])
            paper_info["countries"] = extraction_result.get("countries", [])
            paper_info["homepage"] = extraction_result.get("homepage")
            paper_info["github"] = extraction_result.get("github")
            paper_info["affiliations_extracted"] = True

            # 保存更新后的论文信息
            safe_id = arxiv_id.replace("/", "_").replace(":", "_")
            if fetch_category:
                paper_cat_dir = manager.get_category_dir(date_str, fetch_category)
            else:
                # 如果没有指定分区，尝试从论文信息中获取
                paper_cat_dir = os.path.dirname(pdf_path)

            json_path = os.path.join(paper_cat_dir, f"{safe_id}.json")
            if os.path.exists(json_path):
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(paper_info, f, ensure_ascii=False, indent=2)

            return jsonify(
                {
                    "success": True,
                    "affiliations": extraction_result.get("affiliations", []),
                    "countries": extraction_result.get("countries", []),
                    "homepage": extraction_result.get("homepage"),
                    "github": extraction_result.get("github"),
                }
            )

        except Exception as exc:
            print(f"提取机构信息失败: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": f"提取失败: {str(exc)}"}), 500

    # ========================================
    # Get Thumbnail
    # ========================================
    # 缓存：日期+分区 -> 论文列表的映射
    _thumbnail_cache = {}
    _thumbnail_cache_lock = threading.Lock()

    @app.route("/api/daily-arxiv/clear-thumbnail-cache", methods=["POST"])
    def api_clear_thumbnail_cache():
        """清除缩略图缓存（当重新抓取论文时调用）"""
        try:
            with _thumbnail_cache_lock:
                _thumbnail_cache.clear()
            return jsonify({"success": True, "message": "缓存已清除"})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/daily-arxiv/thumbnail/<date_str>/<category>/<arxiv_id>")
    def api_get_thumbnail(date_str: str, category: str, arxiv_id: str):
        """获取论文缩略图（带缓存优化）"""
        try:
            # URL解码
            from urllib.parse import unquote

            category = unquote(category)
            arxiv_id = unquote(arxiv_id)

            # 使用缓存避免重复读取论文列表
            cache_key = f"{date_str}_{category}"

            with _thumbnail_cache_lock:
                if cache_key not in _thumbnail_cache:
                    # 第一次请求：读取并缓存论文列表
                    papers = manager.get_papers_for_date(date_str, category)
                    # 构建 arxiv_id -> paper 的映射
                    _thumbnail_cache[cache_key] = {
                        p.get("arxiv_id"): p for p in papers if p.get("arxiv_id")
                    }
                    # 限制缓存大小，只保留最近20个日期+分区的数据
                    if len(_thumbnail_cache) > 20:
                        # 删除最早的条目
                        oldest_key = next(iter(_thumbnail_cache))
                        del _thumbnail_cache[oldest_key]

                paper_map = _thumbnail_cache.get(cache_key, {})

            paper = paper_map.get(arxiv_id)

            # 如果缓存中找不到论文，重新读取文件系统（可能在爬取过程中新增了论文）
            if not paper:
                print(f"[DailyArxiv] 缓存中未找到论文 {arxiv_id}，重新读取文件系统...")
                papers = manager.get_papers_for_date(date_str, category)
                # 更新缓存
                with _thumbnail_cache_lock:
                    paper_map = {
                        p.get("arxiv_id"): p for p in papers if p.get("arxiv_id")
                    }
                    _thumbnail_cache[cache_key] = paper_map

                paper = paper_map.get(arxiv_id)
                if not paper:
                    return jsonify({"success": False, "error": "论文未找到"}), 404

            thumbnail_path = paper.get("thumbnail_path")
            if not thumbnail_path:
                return jsonify({"success": False, "error": "缩略图不存在"}), 404

            # 确保路径是绝对路径
            if not os.path.isabs(thumbnail_path):
                thumbnail_path = os.path.abspath(thumbnail_path)

            if not os.path.exists(thumbnail_path):
                return jsonify({"success": False, "error": "缩略图文件不存在"}), 404

            # 添加缓存头，让浏览器缓存图片（7天）
            response = send_file(
                thumbnail_path, mimetype="image/jpeg", as_attachment=False
            )
            response.headers["Cache-Control"] = (
                "public, max-age=604800"  # 7天 = 7*24*60*60
            )
            response.headers["ETag"] = (
                f'"{arxiv_id}-{date_str}"'  # 使用 arxiv_id 和日期作为 ETag
            )
            return response
        except Exception as exc:
            print(f"获取缩略图失败: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Cleanup Old Papers
    # ========================================
    @app.route("/api/daily-arxiv/cleanup", methods=["POST"])
    def api_cleanup_old_papers():
        """清理过期论文"""
        try:
            data = request.json or {}
            retention_days = data.get("retention_days")

            if retention_days is None:
                settings = manager.get_settings()
                retention_days = settings.get("retentionDays", 7)

            manager.cleanup_old_papers(retention_days)

            return jsonify(
                {"success": True, "message": f"已清理 {retention_days} 天前的论文"}
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
