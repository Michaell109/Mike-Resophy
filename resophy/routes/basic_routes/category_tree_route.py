from __future__ import annotations

import os
import shutil
import uuid
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, jsonify, request, send_file
from io import BytesIO


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class SaveCategoriesFn(Protocol):
    def __call__(self, categories: Dict[str, Any]) -> None: ...


class FindCategoryNodeFn(Protocol):
    def __call__(
        self, categories: Dict[str, Any], category_id: str
    ) -> Optional[Dict[str, Any]]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_id: str, category_path: List[str]) -> List[Any]: ...


class AddPdfCountsFn(Protocol):
    def __call__(
        self, categories: Dict[str, Any], count_func: Callable[[str], int]
    ) -> Dict[str, Any]: ...


class GetCategoryPdfCountFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        get_papers_in_category: GetPapersInCategoryFn,
    ) -> int: ...


class PaperStore(Protocol):
    def list_by_category(self, category_id: str) -> List[Any]: ...
    def remove(self, paper_id: str) -> Optional[Any]: ...


def register_category_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    save_categories: SaveCategoriesFn,
    find_category_node: FindCategoryNodeFn,
    get_category_path: GetCategoryPathFn,
    get_papers_in_category: GetPapersInCategoryFn,
    add_pdf_counts_to_categories: AddPdfCountsFn,
    get_category_pdf_count: GetCategoryPdfCountFn,
    paper_store: PaperStore,
    upload_folder: str,
) -> None:
    @app.route("/api/categories")
    def api_categories():
        categories = get_categories()
        categories_with_counts = add_pdf_counts_to_categories(
            categories,
            lambda cid: get_category_pdf_count(categories, cid, get_papers_in_category),
        )
        return jsonify(categories_with_counts)

    @app.route("/api/categories", methods=["POST"])
    def api_add_category():
        data = request.json or {}
        parent_id = data.get("parent_id")
        name = data.get("name")

        if not name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        categories = get_categories()
        if not parent_id or parent_id in {"root", categories.get("id")}:
            parent_node = categories
        else:
            parent_node = find_category_node(categories, parent_id)

        if parent_node is None:
            return (
                jsonify({"success": False, "error": "Parent category not found"}),
                404,
            )

        new_category = {"id": str(uuid.uuid4()), "name": name, "children": []}
        parent_node.setdefault("children", []).append(new_category)
        save_categories(categories)
        return jsonify({"success": True, "category": new_category})

    @app.route("/api/categories/<category_id>", methods=["PUT"])
    def api_rename_category(category_id):
        data = request.json or {}
        new_name = data.get("name")

        if not new_name:
            return (
                jsonify({"success": False, "error": "Category name is required"}),
                400,
            )

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["name"] = new_name
        save_categories(categories)
        return jsonify({"success": True})

    @app.route("/api/categories/<category_id>/pin", methods=["PUT"])
    def api_pin_category(category_id):
        """置顶/取消置顶分类"""
        data = request.json or {}
        pinned = data.get("pinned", False)

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["pinned"] = pinned
        save_categories(categories)
        return jsonify({"success": True, "pinned": pinned})

    @app.route("/api/categories/<category_id>/color", methods=["PUT"])
    def api_change_category_color(category_id):
        """更改分类图标颜色"""
        data = request.json or {}
        color = data.get("color")

        if not color:
            return (
                jsonify({"success": False, "error": "Color is required"}),
                400,
            )

        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if category_node is None:
            return jsonify({"success": False, "error": "Category not found"}), 404

        category_node["iconColor"] = color
        save_categories(categories)
        return jsonify({"success": True, "color": color})

    @app.route("/api/categories/<category_id>", methods=["DELETE"])
    def api_delete_category(category_id):
        categories = get_categories()

        def collect_all_category_ids(node: Dict[str, Any]) -> List[str]:
            """递归收集分类及其所有子分类的 ID"""
            ids = [node.get("id")]
            for child in node.get("children", []):
                ids.extend(collect_all_category_ids(child))
            return ids

        def delete_papers_in_categories(category_ids: List[str]) -> int:
            """从 paper_store 中删除指定分类下的所有论文"""
            deleted_count = 0
            for cat_id in category_ids:
                papers = paper_store.list_by_category(cat_id)
                for paper in papers:
                    paper_id = paper.id if hasattr(paper, 'id') else paper.get('id')
                    if paper_id:
                        paper_store.remove(paper_id)
                        deleted_count += 1
            return deleted_count

        def delete_category_recursive(node: Dict[str, Any], target_id: str) -> bool:
            children = node.get("children", [])
            for index, child in enumerate(children):
                if child["id"] == target_id:
                    # 1. 收集要删除的所有分类 ID（包括子分类）
                    all_category_ids = collect_all_category_ids(child)
                    
                    # 2. 从 paper_store 中删除所有相关论文
                    deleted_papers = delete_papers_in_categories(all_category_ids)
                    print(f"已从 paper_store 删除 {deleted_papers} 篇论文")
                    
                    # 3. 删除物理文件夹
                    category_path = get_category_path(categories, target_id)
                    if category_path and len(category_path) > 1:
                        folder_path = os.path.join(upload_folder, *category_path[1:])
                        if os.path.exists(folder_path):
                            shutil.rmtree(folder_path)
                            print(f"已删除分类文件夹: {folder_path}")

                    # 4. 从分类树中删除节点
                    del children[index]
                    return True
                if delete_category_recursive(child, target_id):
                    return True
            return False

        if delete_category_recursive(categories, category_id):
            save_categories(categories)
            return jsonify({"success": True})

        return jsonify({"success": False, "error": "Category not found"}), 404

    @app.route("/api/categories/<category_id>/move", methods=["PUT"])
    def api_move_category(category_id):
        """
        移动分类到新的父分类下
        
        请求体:
        {
            "target_parent_id": "目标父分类ID" 或 "root" 表示移动到根目录
        }
        """
        data = request.json or {}
        target_parent_id = data.get("target_parent_id")
        
        if not target_parent_id:
            return jsonify({"success": False, "error": "目标父分类ID不能为空"}), 400
        
        categories = get_categories()
        
        # 不能移动根分类
        if category_id == categories.get("id") or category_id == "root":
            return jsonify({"success": False, "error": "不能移动根分类"}), 400
        
        # 不能移动到自己
        if category_id == target_parent_id:
            return jsonify({"success": False, "error": "不能将分类移动到自身"}), 400
        
        # 检查是否试图将分类移动到其子分类下（会造成循环）
        def is_descendant(node: Dict[str, Any], ancestor_id: str, target_id: str) -> bool:
            """检查 target_id 是否是 ancestor_id 的子孙节点"""
            if node.get("id") == ancestor_id:
                # 找到了祖先节点，现在检查 target_id 是否在其子树中
                def find_in_subtree(n: Dict[str, Any]) -> bool:
                    if n.get("id") == target_id:
                        return True
                    for child in n.get("children", []):
                        if find_in_subtree(child):
                            return True
                    return False
                return find_in_subtree(node)
            
            for child in node.get("children", []):
                if is_descendant(child, ancestor_id, target_id):
                    return True
            return False
        
        if is_descendant(categories, category_id, target_parent_id):
            return jsonify({"success": False, "error": "不能将分类移动到其子分类下"}), 400
        
        # 获取原路径（用于移动文件夹）
        old_path = get_category_path(categories, category_id)
        
        # 找到并移除分类节点
        category_node = None
        
        def remove_from_parent(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            children = node.get("children", [])
            for index, child in enumerate(children):
                if child["id"] == category_id:
                    return children.pop(index)
                result = remove_from_parent(child)
                if result:
                    return result
            return None
        
        category_node = remove_from_parent(categories)
        
        if not category_node:
            return jsonify({"success": False, "error": "分类不存在"}), 404
        
        # 找到目标父节点并添加分类
        if target_parent_id in {"root", categories.get("id")}:
            target_parent = categories
        else:
            target_parent = find_category_node(categories, target_parent_id)
        
        if not target_parent:
            # 恢复原状态
            # 这里简化处理，实际上应该恢复到原来的位置
            return jsonify({"success": False, "error": "目标父分类不存在"}), 404
        
        target_parent.setdefault("children", []).append(category_node)
        
        # 获取新路径
        new_path = get_category_path(categories, category_id)
        
        # 移动物理文件夹
        if old_path and new_path and len(old_path) > 1 and len(new_path) > 1:
            old_folder = os.path.join(upload_folder, *old_path[1:])
            new_folder = os.path.join(upload_folder, *new_path[1:])
            
            if os.path.exists(old_folder) and old_folder != new_folder:
                # 确保新路径的父目录存在
                new_parent_folder = os.path.dirname(new_folder)
                os.makedirs(new_parent_folder, exist_ok=True)
                
                # 如果目标位置已存在同名文件夹，需要处理
                if os.path.exists(new_folder):
                    print(f"[移动分类] 目标位置已存在文件夹: {new_folder}")
                    # 可以选择合并或返回错误
                    return jsonify({"success": False, "error": "目标位置已存在同名文件夹"}), 400
                
                try:
                    shutil.move(old_folder, new_folder)
                    print(f"[移动分类] 文件夹已移动: {old_folder} -> {new_folder}")
                except Exception as e:
                    print(f"[移动分类] 移动文件夹失败: {e}")
                    # 继续保存分类结构，即使文件夹移动失败
        
        save_categories(categories)
        
        return jsonify({
            "success": True,
            "category": category_node,
            "old_path": old_path,
            "new_path": new_path
        })

    @app.route("/api/categories/<category_id>/export-bibtex", methods=["GET"])
    def api_export_category_bibtex(category_id: str):
        """
        导出分类及其所有子分类下所有论文的 BibTeX
        
        递归遍历分类树，收集所有论文的 BibTeX，合并成一个 .bib 文件
        """
        try:
            categories = get_categories()
            category_node = find_category_node(categories, category_id)
            
            if not category_node:
                return jsonify({"error": "Category not found"}), 404
            
            # 递归收集所有论文的 BibTeX
            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                """递归收集分类及其子分类下的所有论文"""
                papers = []
                
                # 获取当前分类的论文
                node_path = get_category_path(categories, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)
                
                # 递归处理子分类
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))
                
                return papers
            
            all_papers = collect_papers_recursive(category_node)
            
            if not all_papers:
                return jsonify({"error": "该分类下没有论文"}), 404
            
            # 收集所有 BibTeX
            bibtex_entries = []
            for paper in all_papers:
                # paper 可能是 Paper 对象或字典
                if hasattr(paper, 'bibtex'):
                    bibtex = paper.bibtex
                elif isinstance(paper, dict):
                    bibtex = paper.get("bibtex", "")
                else:
                    bibtex = ""
                
                if bibtex and bibtex.strip():
                    bibtex_entries.append(bibtex.strip())
            
            if not bibtex_entries:
                return jsonify({"error": "该分类下的论文都没有 BibTeX"}), 404
            
            # 合并所有 BibTeX 条目
            bibtex_content = "\n\n".join(bibtex_entries)
            
            # 生成文件名（使用分类名称）
            category_name = category_node.get("name", "export")
            # 清理文件名（移除特殊字符）
            safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '' for c in category_name)
            safe_name = safe_name.strip().replace(' ', '_')
            filename = f"{safe_name}_bibtex.bib"
            
            # 创建文件对象
            bibtex_bytes = bibtex_content.encode('utf-8')
            bibtex_file = BytesIO(bibtex_bytes)
            
            print(f"[导出 BibTeX] 分类: {category_name}, 论文数: {len(all_papers)}, BibTeX 条目数: {len(bibtex_entries)}")
            
            return send_file(
                bibtex_file,
                mimetype='application/x-bibtex',
                as_attachment=True,
                download_name=filename
            )
            
        except Exception as exc:
            print(f"导出 BibTeX 失败: {exc}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"导出失败: {str(exc)}"}), 500

    @app.route("/api/categories/<category_id>/copy-arxiv-urls", methods=["GET"])
    def api_copy_category_arxiv_urls(category_id: str):
        """
        获取分类及其所有子分类下所有论文的 arXiv URL
        
        返回格式：title：URL，title：URL
        """
        try:
            categories = get_categories()
            category_node = find_category_node(categories, category_id)
            
            if not category_node:
                return jsonify({"error": "Category not found"}), 404
            
            # 递归收集所有论文
            def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
                """递归收集分类及其子分类下的所有论文"""
                papers = []
                
                # 获取当前分类的论文
                node_path = get_category_path(categories, node["id"])
                if node_path:
                    node_papers = get_papers_in_category(node["id"], node_path)
                    papers.extend(node_papers)
                
                # 递归处理子分类
                for child in node.get("children", []):
                    papers.extend(collect_papers_recursive(child))
                
                return papers
            
            all_papers = collect_papers_recursive(category_node)
            
            if not all_papers:
                return jsonify({"error": "该分类下没有论文"}), 404
            
            # 收集所有有 arXiv URL 的论文
            arxiv_entries = []
            for paper in all_papers:
                # paper 可能是 Paper 对象或字典
                arxiv_url = None
                arxiv_id = None
                title = ""
                
                if hasattr(paper, 'arxiv_url'):
                    arxiv_url = paper.arxiv_url
                    arxiv_id = getattr(paper, 'arxiv_id', None)
                    title = paper.title or paper.filename or ""
                elif isinstance(paper, dict):
                    arxiv_url = paper.get("arxiv_url")
                    arxiv_id = paper.get("arxiv_id")
                    title = paper.get("title") or paper.get("filename") or ""
                else:
                    continue
                
                # 如果没有 arxiv_url 但有 arxiv_id，根据 arxiv_id 构建 URL
                if not arxiv_url or not arxiv_url.strip():
                    if arxiv_id and arxiv_id.strip():
                        arxiv_url = f"https://arxiv.org/abs/{arxiv_id.strip()}"
                    else:
                        continue  # 既没有 arxiv_url 也没有 arxiv_id，跳过
                
                # 处理有 arXiv URL 的论文
                if arxiv_url and arxiv_url.strip():
                    arxiv_entries.append({
                        "title": title.strip() if title else "未命名论文",
                        "url": arxiv_url.strip()
                    })
            
            if not arxiv_entries:
                return jsonify({"error": "该分类下的论文都没有 arXiv URL"}), 404
            
            # 格式化为 "title：URL\n\ntitle：URL" 格式（不同论文之间用两个换行符分隔）
            formatted_text = "\n\n".join([f"{entry['title']}：{entry['url']}" for entry in arxiv_entries])
            
            print(f"[复制 arXiv URL] 分类: {category_node.get('name', 'export')}, 总论文数: {len(all_papers)}, 有 arXiv URL 的论文数: {len(arxiv_entries)}")
            if len(all_papers) > len(arxiv_entries):
                skipped_count = len(all_papers) - len(arxiv_entries)
                print(f"[复制 arXiv URL] 警告: 跳过了 {skipped_count} 篇没有 arXiv URL/ID 的论文")
            
            return jsonify({
                "success": True,
                "text": formatted_text,
                "count": len(arxiv_entries)
            })
            
        except Exception as exc:
            print(f"获取 arXiv URL 失败: {exc}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(exc)}), 500
