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
    settings_file_path: str,
    default_settings: Dict[str, Any],
    user_settings_file: str,
    default_user_settings: Dict[str, Any],
    reading_history_file: str,
    translation_settings_file: str,
    default_translation_settings: Dict[str, Any],
    analysis_settings_file: str,
    default_analysis_settings: Dict[str, Any],
    avatars_dir: str,
) -> None:

    # ========================================
    # General Settings
    # ========================================
    @app.route("/api/settings/general", methods=["GET", "POST"])
    def api_general_settings():
        if request.method == "GET":
            try:
                with open(settings_file_path, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"读取设置失败: {exc}")
                settings = {}
            merged = default_settings.copy()
            merged.update(settings)
            return jsonify(merged)

        data = request.json or {}
        try:
            with open(settings_file_path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

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
        """记录今日阅读时间"""
        try:
            data = request.json or {}
            minutes = data.get("minutes", 0)
            date = data.get("date")  # YYYY-MM-DD

            if not date:
                from datetime import datetime

                date = datetime.now().strftime("%Y-%m-%d")

            # 读取现有历史
            try:
                with open(reading_history_file, "r", encoding="utf-8") as fp:
                    history = json.load(fp)
            except:
                history = {}

            # 累加今日阅读时间
            history[date] = history.get(date, 0) + minutes

            with open(reading_history_file, "w", encoding="utf-8") as fp:
                json.dump(history, fp, ensure_ascii=False, indent=2)

            return jsonify({"success": True, "total": history[date]})
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

    # ========================================
    # Translation Settings
    # ========================================
    @app.route("/api/settings/translation", methods=["GET", "POST"])
    def api_translation_settings():
        if request.method == "GET":
            try:
                with open(translation_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"读取翻译设置失败: {exc}")
                settings = {}
            merged = default_translation_settings.copy()
            merged.update(settings)
            return jsonify(merged)

        data = request.json or {}
        try:
            with open(translation_settings_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # AI Analysis Settings
    # ========================================
    @app.route("/api/settings/analysis", methods=["GET", "POST"])
    def api_analysis_settings():
        if request.method == "GET":
            try:
                with open(analysis_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"读取AI解读设置失败: {exc}")
                settings = {}
            merged = default_analysis_settings.copy()
            merged.update(settings)
            return jsonify(merged)

        data = request.json or {}
        try:
            with open(analysis_settings_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
