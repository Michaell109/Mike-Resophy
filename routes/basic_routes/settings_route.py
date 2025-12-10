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
            return jsonify(merged)

        data = request.json or {}
        try:
            with open(agentic_settings_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
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
