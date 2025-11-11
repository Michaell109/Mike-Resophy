from __future__ import annotations

import json
from typing import Any, Dict

from flask import Flask, jsonify, request


def register_settings_routes(
    app: Flask,
    *,
    settings_file_path: str,
    default_settings: Dict[str, Any],
) -> None:
    @app.route("/api/settings/general", methods=["GET", "POST"])
    def api_general_settings():
        if request.method == "GET":
            try:
                with open(settings_file_path, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            return jsonify({"success": False, "error": str(exc)}), 500
