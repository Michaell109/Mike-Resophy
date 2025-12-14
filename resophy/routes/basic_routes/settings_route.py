from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Dict

from flask import Flask, jsonify, request, send_from_directory


def register_settings_routes(
    app: Flask,
    *,
    user_settings_file: str,
    default_user_settings: Dict[str, Any],
    reading_history_file: str,
    agentic_settings_file: str,
    default_agentic_settings: Dict[str, Any],
    avatars_dir: str,
    start_daily_arxiv_callback=None,
) -> None:

    # ========================================
    # User Settings (name, avatar, heatmap color)
    # ========================================
    @app.route("/api/settings/user", methods=["GET", "POST"])
    def api_user_settings():
        if request.method == "GET":
            try:
                with open(user_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"读取用户设置失败: {exc}")
                settings = {}
            merged = default_user_settings.copy()
            merged.update(settings)
            return jsonify(merged)

        data = request.json or {}
        try:
            # 读取现有设置
            try:
                with open(user_settings_file, "r", encoding="utf-8") as fp:
                    current = json.load(fp)
            except:
                current = default_user_settings.copy()

            # 更新设置
            current.update(data)

            with open(user_settings_file, "w", encoding="utf-8") as fp:
                json.dump(current, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Avatar Upload
    # ========================================
    @app.route("/api/settings/avatar", methods=["POST"])
    def api_upload_avatar():
        try:
            data = request.json or {}
            avatar_data = data.get("avatarData")  # Base64 encoded image

            if not avatar_data:
                return jsonify({"success": False, "error": "No avatar data"}), 400

            # 解析 Base64 数据
            if "," in avatar_data:
                header, encoded = avatar_data.split(",", 1)
                # 获取文件类型
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                elif "png" in header:
                    ext = "png"
                elif "gif" in header:
                    ext = "gif"
                else:
                    ext = "jpg"
            else:
                encoded = avatar_data
                ext = "jpg"

            # 解码并保存
            image_data = base64.b64decode(encoded)
            filename = f"avatar.{ext}"
            filepath = os.path.join(avatars_dir, filename)

            with open(filepath, "wb") as f:
                f.write(image_data)

            # 更新用户设置
            try:
                with open(user_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except:
                settings = default_user_settings.copy()

            settings["avatar"] = filename

            with open(user_settings_file, "w", encoding="utf-8") as fp:
                json.dump(settings, fp, ensure_ascii=False, indent=2)

            return jsonify({"success": True, "avatar": filename})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/avatar", methods=["GET"])
    def api_get_avatar():
        """获取头像图片"""
        try:
            with open(user_settings_file, "r", encoding="utf-8") as fp:
                settings = json.load(fp)
            avatar_file = settings.get("avatar")
            if avatar_file and os.path.exists(os.path.join(avatars_dir, avatar_file)):
                return send_from_directory(avatars_dir, avatar_file)
            return jsonify({"error": "No avatar"}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ========================================
    # Reading History (daily reading time)
    # ========================================
    @app.route("/api/settings/reading-history", methods=["GET", "POST"])
    def api_reading_history():
        if request.method == "GET":
            try:
                with open(reading_history_file, "r", encoding="utf-8") as fp:
                    history = json.load(fp)
            except FileNotFoundError:
                history = {}
            except Exception as exc:
                print(f"读取阅读历史失败: {exc}")
                history = {}
            return jsonify(history)

        data = request.json or {}
        try:
            # 读取现有历史
            try:
                with open(reading_history_file, "r", encoding="utf-8") as fp:
                    current = json.load(fp)
            except:
                current = {}

            # 更新历史（合并）
            for date, minutes in data.items():
                if date in current:
                    current[date] = current[date] + minutes
                else:
                    current[date] = minutes

            with open(reading_history_file, "w", encoding="utf-8") as fp:
                json.dump(current, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/record", methods=["POST"])
    def api_record_reading():
        """记录今日阅读时间（兼容新旧格式）"""
        try:
            data = request.json or {}
            minutes = data.get("minutes", 0)
            date = data.get("date")  # YYYY-MM-DD
            paper_id = data.get("paper_id")  # 可选，论文ID

            if not date:
                from datetime import datetime

                date = datetime.now().strftime("%Y-%m-%d")

            # 读取现有历史
            try:
                with open(reading_history_file, "r", encoding="utf-8") as fp:
                    history = json.load(fp)
            except:
                history = {}

            # 更新阅读历史（兼容新旧格式）
            if date in history:
                if isinstance(history[date], dict):
                    # 新格式
                    history[date]["total"] = history[date].get("total", 0) + minutes
                    if paper_id and paper_id not in history[date].get("papers", []):
                        if "papers" not in history[date]:
                            history[date]["papers"] = []
                        history[date]["papers"].append(paper_id)
                else:
                    # 旧格式，转换为新格式
                    old_minutes = history[date]
                    history[date] = {
                        "total": old_minutes + minutes,
                        "papers": [paper_id] if paper_id else [],
                    }
            else:
                history[date] = {
                    "total": minutes,
                    "papers": [paper_id] if paper_id else [],
                }

            with open(reading_history_file, "w", encoding="utf-8") as fp:
                json.dump(history, fp, ensure_ascii=False, indent=2)

            total = (
                history[date]["total"]
                if isinstance(history[date], dict)
                else history[date]
            )
            return jsonify({"success": True, "total": total})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/clear", methods=["POST"])
    def api_clear_reading_history():
        """清除所有阅读历史"""
        try:
            with open(reading_history_file, "w", encoding="utf-8") as fp:
                json.dump({}, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/week-papers", methods=["GET"])
    def api_week_papers():
        """获取本周阅读的论文列表"""
        try:
            from datetime import datetime, timedelta

            # 读取阅读历史
            try:
                with open(reading_history_file, "r", encoding="utf-8") as fp:
                    history = json.load(fp)
            except:
                history = {}

            # 计算本周的日期范围（周一到今天）
            today = datetime.now().date()
            day_of_week = today.weekday()  # 0 = Monday, 6 = Sunday
            monday = today - timedelta(days=day_of_week)

            # 收集本周阅读的论文ID
            week_paper_ids = set()
            current_date = monday
            while current_date <= today:
                date_str = current_date.strftime("%Y-%m-%d")
                if date_str in history:
                    entry = history[date_str]
                    if isinstance(entry, dict):
                        # 新格式
                        papers = entry.get("papers", [])
                        week_paper_ids.update(papers)
                    # 旧格式没有论文ID信息，跳过

                current_date += timedelta(days=1)

            return jsonify(
                {
                    "success": True,
                    "papers": list(week_paper_ids),
                    "count": len(week_paper_ids),
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Agentic Settings (统一的AI功能配置)
    # ========================================
    @app.route("/api/settings/agentic", methods=["GET", "POST"])
    def api_agentic_settings():
        """
        统一的AI功能配置接口
        包括: LLM API配置, PDF解析服务配置, AI解读提示词等
        """
        if request.method == "GET":
            try:
                with open(agentic_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"读取AI功能设置失败: {exc}")
                settings = {}
            merged = default_agentic_settings.copy()
            merged.update(settings)
            
            # 如果用户没有自定义 System Prompt，返回默认值供前端显示
            if not merged.get("analysisSystemPrompt"):
                default_prompt = """请以中文 markdown 的形式为这篇文章写一个公众号风格的包含有详细内容的长推文，内容要详细且丰富，
实验内容也要充分，比如包括消融实验。注意你一定要使用原始markdown 中的图片和表格来让你的公众号文章更加清晰，
图片,比如模型结构，teaser，或者一些结果图，阐释图直接插入到正文对应位置之中，不要放到最后。图片对于一个公众号文章来说很重要

INPUT: <MARKDOWN>"""
                merged["analysisSystemPrompt"] = default_prompt
                merged["_isDefaultPrompt"] = True  # 标记这是默认提示词
            
            return jsonify(merged)

        data = request.json or {}
        try:
            # 检查 LLM 配置是否完整
            llm_model = data.get("llmModel", "").strip()
            llm_base_url = data.get("llmBaseUrl", "").strip()
            llm_api_key = data.get("llmApiKey", "").strip()
            is_llm_configured = bool(llm_model and llm_base_url and llm_api_key)

            # 读取之前的配置，检查是否之前未配置完整
            was_llm_configured = False
            old_settings = {}
            try:
                with open(agentic_settings_file, "r", encoding="utf-8") as fp:
                    old_settings = json.load(fp)
                    old_model = old_settings.get("llmModel", "").strip()
                    old_base_url = old_settings.get("llmBaseUrl", "").strip()
                    old_api_key = old_settings.get("llmApiKey", "").strip()
                    was_llm_configured = bool(old_model and old_base_url and old_api_key)
            except FileNotFoundError:
                old_settings = {}
            except Exception as exc:
                print(f"读取旧设置失败: {exc}")
                old_settings = {}

            # 合并新旧配置（新配置优先，但保留旧配置中未提供的字段）
            merged_settings = default_agentic_settings.copy()
            merged_settings.update(old_settings)  # 先应用旧设置
            merged_settings.update(data)  # 再应用新设置（覆盖）

            # 检查 LLM 配置是否发生变化
            llm_config_changed = False
            if was_llm_configured and is_llm_configured:
                # 配置完整，检查是否发生变化
                old_model = old_settings.get("llmModel", "").strip()
                old_base_url = old_settings.get("llmBaseUrl", "").strip()
                old_api_key = old_settings.get("llmApiKey", "").strip()
                
                new_model = merged_settings.get("llmModel", "").strip()
                new_base_url = merged_settings.get("llmBaseUrl", "").strip()
                new_api_key = merged_settings.get("llmApiKey", "").strip()
                
                # 如果任何一个配置项发生变化，认为配置已更改
                if (old_model != new_model or 
                    old_base_url != new_base_url or 
                    old_api_key != new_api_key):
                    llm_config_changed = True
                    print(f"[Settings] 检测到 LLM 配置已更改")

            # 保存合并后的配置
            print(f"[Settings] 保存 Agentic 设置到: {agentic_settings_file}")
            print(f"[Settings] 配置内容: llmModel={merged_settings.get('llmModel', '')[:20]}..., llmBaseUrl={merged_settings.get('llmBaseUrl', '')[:30]}..., mineruServerUrl={merged_settings.get('mineruServerUrl', '')[:30]}...")
            with open(agentic_settings_file, "w", encoding="utf-8") as fp:
                json.dump(merged_settings, fp, ensure_ascii=False, indent=2)
            print(f"[Settings] ✅ 设置已保存")

            # 如果 LLM 配置完整且发生变化，或者从未配置变为已配置，触发 Daily arXiv 抓取
            if is_llm_configured and (llm_config_changed or not was_llm_configured):
                try:
                    from resophy.tools.basic_tools.daily_arxiv import get_manager
                    import threading
                    # 获取 Daily arXiv 设置文件路径（从 agentic_settings_file 推断）
                    papers_dir = os.path.dirname(agentic_settings_file)
                    daily_arxiv_settings_file = os.path.join(
                        papers_dir, "daily_arxiv_settings.json"
                    )
                    temp_papers_dir = os.path.join(
                        papers_dir, ".daily_arxiv_temp"
                    )
                    # 获取 manager 实例（单例模式，会返回同一个实例）
                    manager = get_manager(temp_papers_dir, daily_arxiv_settings_file)
                    
                    # 清除失败状态
                    if hasattr(manager, "_llm_api_failed"):
                        manager._llm_api_failed = False
                        manager._llm_api_error_message = ""
                        print("[Settings] 已清除 Daily arXiv 的失败状态")
                    
                    # 启动调度器（如果未运行）
                    if not manager._scheduler_running:
                        if start_daily_arxiv_callback:
                            start_daily_arxiv_callback()
                        else:
                            manager.start_scheduler()
                        print("[Settings] LLM 配置已保存，已启动 Daily arXiv 调度器（调度器会自动触发一次抓取）")
                    else:
                        # 调度器已在运行，手动触发一次抓取
                        def trigger_fetch():
                            try:
                                manager._do_scheduled_fetch()
                                print("[Settings] LLM 配置已保存，已触发一次 Daily arXiv 抓取")
                            except Exception as e:
                                print(f"[Settings] 触发 Daily arXiv 抓取失败: {e}")
                        
                        # 在后台线程中触发抓取，避免阻塞保存响应
                        thread = threading.Thread(target=trigger_fetch, daemon=True)
                        thread.start()
                        print("[Settings] LLM 配置已保存，已在后台触发 Daily arXiv 抓取")
                except Exception as e:
                    # 如果触发抓取时出错，不影响保存结果
                    print(f"[Settings] 触发 Daily arXiv 抓取时出错（不影响保存）: {e}")

            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # 保留旧的API端点以兼容性（返回重定向提示）
    @app.route("/api/settings/translation", methods=["GET", "POST"])
    def api_translation_settings_deprecated():
        """已废弃，请使用 /api/settings/agentic"""
        return (
            jsonify(
                {
                    "error": "This endpoint is deprecated. Use /api/settings/agentic instead"
                }
            ),
            410,
        )

    @app.route("/api/settings/analysis", methods=["GET", "POST"])
    def api_analysis_settings_deprecated():
        """已废弃，请使用 /api/settings/agentic"""
        return (
            jsonify(
                {
                    "error": "This endpoint is deprecated. Use /api/settings/agentic instead"
                }
            ),
            410,
        )

    # ========================================
    # API Test Endpoints
    # ========================================
    @app.route("/api/settings/test/llm", methods=["POST"])
    def api_test_llm():
        """测试 LLM API 连接"""
        try:
            data = request.json or {}
            llm_model = data.get("llmModel", "").strip()
            llm_base_url = data.get("llmBaseUrl", "").strip()
            llm_api_key = data.get("llmApiKey", "").strip()

            if not llm_model or not llm_base_url or not llm_api_key:
                return jsonify(
                    {
                        "success": False,
                        "error": "请填写完整的 LLM API 配置（Model、Base URL、API Key）",
                    }
                ), 400

            # 导入 OpenAI 客户端
            try:
                from openai import OpenAI
            except ImportError:
                return jsonify(
                    {
                        "success": False,
                        "error": "OpenAI 库未安装，请运行: pip install openai",
                    }
                ), 500

            # 创建客户端
            client = OpenAI(
                base_url=llm_base_url,
                api_key=llm_api_key,
                timeout=30.0,  # 30秒超时
            )

            # 发送测试消息
            test_message = "Can you see my message, if you can, respond with Yes."
            try:
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=[
                        {"role": "user", "content": test_message},
                    ],
                    max_tokens=50,  # 限制回复长度
                )

                # 检查回复
                if response.choices and len(response.choices) > 0:
                    reply = response.choices[0].message.content.strip()
                    # 检查是否包含 "Yes"（不区分大小写）
                    if "yes" in reply.lower():
                        # 测试成功，清除 Daily arXiv 的失败状态并触发抓取
                        try:
                            from resophy.tools.basic_tools.daily_arxiv import get_manager
                            import threading
                            # 获取 Daily arXiv 设置文件路径（从 agentic_settings_file 推断）
                            # agentic_settings_file 和 daily_arxiv_settings_file 在同一目录下
                            papers_dir = os.path.dirname(agentic_settings_file)
                            daily_arxiv_settings_file = os.path.join(
                                papers_dir, "daily_arxiv_settings.json"
                            )
                            temp_papers_dir = os.path.join(
                                papers_dir, ".daily_arxiv_temp"
                            )
                            # 获取 manager 实例（单例模式，会返回同一个实例）
                            manager = get_manager(temp_papers_dir, daily_arxiv_settings_file)
                            # 清除失败状态
                            if hasattr(manager, "_llm_api_failed"):
                                manager._llm_api_failed = False
                                manager._llm_api_error_message = ""
                                print("[Settings] LLM API 测试成功，已清除 Daily arXiv 的失败状态")
                            
                            # 启动调度器（如果未运行）
                            if not manager._scheduler_running:
                                manager.start_scheduler()
                                print("[Settings] LLM API 测试成功，已启动 Daily arXiv 调度器（调度器会自动触发一次抓取）")
                            else:
                                # 调度器已在运行，手动触发一次抓取
                                def trigger_fetch():
                                    try:
                                        manager._do_scheduled_fetch()
                                        print("[Settings] LLM API 测试成功，已触发一次 Daily arXiv 抓取")
                                    except Exception as e:
                                        print(f"[Settings] 触发 Daily arXiv 抓取失败: {e}")
                                
                                # 在后台线程中触发抓取，避免阻塞测试响应
                                thread = threading.Thread(target=trigger_fetch, daemon=True)
                                thread.start()
                                print("[Settings] LLM API 测试成功，已在后台触发 Daily arXiv 抓取")
                        except Exception as e:
                            # 如果处理失败状态时出错，不影响测试结果
                            print(f"[Settings] 处理 Daily arXiv 失败状态时出错（不影响测试）: {e}")
                        
                        return jsonify(
                            {
                                "success": True,
                                "message": "LLM API 连接成功！",
                                "reply": reply,
                            }
                        )
                    else:
                        return jsonify(
                            {
                                "success": False,
                                "error": f"LLM API 返回了回复，但不符合预期。回复内容: {reply}",
                                "reply": reply,
                            }
                        )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": "LLM API 返回了空回复",
                        }
                    )

            except Exception as e:
                error_msg = str(e)
                # 提供更友好的错误信息
                if "401" in error_msg or "Unauthorized" in error_msg:
                    return jsonify(
                        {
                            "success": False,
                            "error": "API Key 无效或未授权",
                        }
                    )
                elif "404" in error_msg or "Not Found" in error_msg:
                    return jsonify(
                        {
                            "success": False,
                            "error": "API 端点不存在，请检查 Base URL 是否正确",
                        }
                    )
                elif "timeout" in error_msg.lower():
                    return jsonify(
                        {
                            "success": False,
                            "error": "连接超时，请检查网络连接和 Base URL",
                        }
                    )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": f"LLM API 调用失败: {error_msg}",
                        }
                    )

        except Exception as exc:
            return jsonify({"success": False, "error": f"测试失败: {str(exc)}"}), 500

    @app.route("/api/settings/test/mineru", methods=["POST"])
    def api_test_mineru():
        """测试 MinerU API 连接"""
        try:
            import requests

            data = request.json or {}
            mineru_server_url = data.get("mineruServerUrl", "").strip()

            if not mineru_server_url:
                return jsonify(
                    {
                        "success": False,
                        "error": "请填写 MinerU Server URL",
                    }
                ), 400

            # 移除末尾的斜杠
            mineru_server_url = mineru_server_url.rstrip("/")

            # 尝试连接 MinerU 服务
            # 通常 MinerU 服务可能有健康检查端点，如果没有则尝试根路径
            test_urls = [
                f"{mineru_server_url}/health",
                f"{mineru_server_url}/",
                f"{mineru_server_url}/api/health",
            ]

            last_error = None
            for test_url in test_urls:
                try:
                    response = requests.get(
                        test_url,
                        timeout=10.0,  # 10秒超时
                        allow_redirects=True,
                    )
                    # 如果返回 200-299 状态码，认为连接成功
                    if 200 <= response.status_code < 300:
                        return jsonify(
                            {
                                "success": True,
                                "message": "MinerU API 连接成功！",
                                "status_code": response.status_code,
                                "tested_url": test_url,
                            }
                        )
                    # 如果是其他状态码，继续尝试下一个 URL
                    last_error = f"HTTP {response.status_code}"
                except requests.exceptions.Timeout:
                    last_error = "连接超时"
                    continue
                except requests.exceptions.ConnectionError:
                    last_error = "无法连接到服务器"
                    continue
                except Exception as e:
                    last_error = str(e)
                    continue

            # 所有 URL 都失败
            return jsonify(
                {
                    "success": False,
                    "error": f"MinerU API 连接失败: {last_error}。请检查 URL 是否正确，服务是否正在运行",
                }
            )

        except ImportError:
            return jsonify(
                {
                    "success": False,
                    "error": "requests 库未安装，请运行: pip install requests",
                }
            ), 500
        except Exception as exc:
            return jsonify({"success": False, "error": f"测试失败: {str(exc)}"}), 500
