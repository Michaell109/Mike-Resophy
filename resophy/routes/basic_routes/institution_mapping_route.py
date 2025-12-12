"""
自定义机构映射管理路由
"""

import json
import os

from flask import jsonify, request


def register_institution_mapping_routes(app, daily_arxiv_settings_file: str):
    """
    注册自定义机构映射管理路由

    Args:
        app: Flask 应用实例
        daily_arxiv_settings_file: Daily arXiv 设置文件路径
    """

    def load_settings():
        """加载设置文件"""
        if os.path.exists(daily_arxiv_settings_file):
            with open(daily_arxiv_settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_settings(settings):
        """保存设置文件"""
        with open(daily_arxiv_settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    @app.route("/api/custom-institutions", methods=["GET"])
    def get_custom_institutions():
        """获取用户自定义的机构映射"""
        try:
            settings = load_settings()
            custom_institutions = settings.get("customInstitutions", {})

            # 转换为前端需要的格式
            result = []
            for abbr, variants in custom_institutions.items():
                result.append({"abbreviation": abbr, "variants": variants})

            # 按缩写排序
            result.sort(key=lambda x: x["abbreviation"])

            return jsonify(
                {"success": True, "institutions": result, "total": len(result)}
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/all-known-institutions", methods=["GET"])
    def get_all_known_institutions():
        """获取所有已知机构（系统预设 + 用户自定义）"""
        try:
            import sys

            tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools"
            )
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            from institution_normalizer import InstitutionNormalizer

            # 创建标准化器实例（会加载系统映射 + 用户自定义映射）
            normalizer = InstitutionNormalizer(
                custom_mapping_file=daily_arxiv_settings_file
            )

            # 获取所有标准机构名称（key）
            all_abbrs = list(normalizer.institution_map.keys())

            return jsonify(
                {"success": True, "institutions": all_abbrs, "total": len(all_abbrs)}
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/custom-institutions", methods=["POST"])
    def save_custom_institution():
        """保存或更新单个自定义机构"""
        try:
            data = request.json
            abbreviation = data.get("abbreviation", "").strip()
            variants = data.get("variants", [])

            if not abbreviation:
                return jsonify({"success": False, "error": "缩写不能为空"}), 400

            # 去重并过滤空值
            unique_variants = []
            seen = set()
            for v in variants:
                v_clean = v.strip()
                if v_clean and v_clean not in seen:
                    seen.add(v_clean)
                    unique_variants.append(v_clean)

            if not unique_variants:
                return jsonify({"success": False, "error": "至少需要一个全称变体"}), 400

            # 加载设置
            settings = load_settings()
            if "customInstitutions" not in settings:
                settings["customInstitutions"] = {}

            # 保存机构
            settings["customInstitutions"][abbreviation] = unique_variants
            save_settings(settings)

            # 重新加载标准化器
            reload_normalizer()

            return jsonify({"success": True, "message": f"机构 {abbreviation} 已保存"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/custom-institutions/<abbreviation>", methods=["DELETE"])
    def delete_custom_institution(abbreviation):
        """删除自定义机构"""
        try:
            settings = load_settings()
            custom_institutions = settings.get("customInstitutions", {})

            if abbreviation in custom_institutions:
                del custom_institutions[abbreviation]
                settings["customInstitutions"] = custom_institutions
                save_settings(settings)
                reload_normalizer()

                return jsonify(
                    {"success": True, "message": f"已删除机构 {abbreviation}"}
                )
            else:
                return jsonify({"success": False, "error": "机构不存在"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    def reload_normalizer():
        """重新加载标准化器"""
        try:
            import sys

            tools_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tools"
            )
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            # 强制重新导入标准化器模块
            import importlib

            import institution_normalizer

            importlib.reload(institution_normalizer)

            print("[CustomInstitution] 标准化器已重新加载")
        except Exception as e:
            print(f"[CustomInstitution] 重新加载标准化器失败: {e}")
