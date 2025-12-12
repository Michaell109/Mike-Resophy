"""
数据导出路由
处理论文和配置数据的导出功能
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from flask import Flask, Response, jsonify, request, send_file
from werkzeug.utils import secure_filename


# 导出任务状态存储
export_tasks: Dict[str, Dict[str, Any]] = {}
export_tasks_lock = threading.Lock()

# 当前活跃的导出任务ID
current_export_task_id: Optional[str] = None


def _should_exclude_file(rel_path: str) -> bool:
    """判断文件是否应该被排除（只导出 JSON 元数据和目录结构）"""
    # 排除临时目录和索引文件（但保留 .avatars）
    excluded_dirs = ['.daily_arxiv_temp', '.temp']
    excluded_files = ['.search_index.db', '.search_index.db.corrupted']
    
    # 检查是否在排除的目录中
    path_parts = rel_path.split(os.sep)
    for excluded_dir in excluded_dirs:
        if excluded_dir in path_parts:
            return True
    
    # 检查是否是排除的文件
    filename = os.path.basename(rel_path)
    if filename in excluded_files:
        return True
    
    # 只保留 JSON 文件、目录结构和 .avatars
    # 排除所有 PDF、outputs 目录、_analysis.md、_images 文件夹
    if filename.endswith('.pdf'):
        return True
    if 'outputs' in path_parts:
        return True
    if filename.endswith('_analysis.md') or '_images' in path_parts:
        return True
    
    return False


def _export_papers_folder_to_zip(
    papers_dir: str,
    zip_path: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
):
    """将整个 papers 文件夹的 JSON 元数据导出到 ZIP 文件，保留原始目录结构"""
    print(f"[Export] 开始导出文件夹元数据: {papers_dir}")
    
    # 计算总文件数
    total_files = 0
    for root, dirs, files in os.walk(papers_dir):
        dirs[:] = [d for d in dirs if d not in ['.daily_arxiv_temp', '.temp']]
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, papers_dir)
            if not _should_exclude_file(rel_path):
                total_files += 1
    
    print(f"[Export] 共找到 {total_files} 个文件")
    
    # 开始打包
    processed_files = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(papers_dir):
            # 排除临时目录
            dirs[:] = [d for d in dirs if d not in ['.daily_arxiv_temp', '.temp']]
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, papers_dir)
                
                # 检查是否应该排除
                if _should_exclude_file(rel_path):
                    continue
                
                # 添加到 ZIP
                zip_file_path = f"papers/{rel_path}"
                try:
                    zipf.write(file_path, zip_file_path)
                    processed_files += 1
                    
                    if progress_callback and processed_files % 10 == 0:
                        progress_callback(processed_files, total_files, f"正在打包: {rel_path}")
                except Exception as e:
                    print(f"[Export] 打包文件失败: {file_path}, 错误: {e}")
    
    print(f"[Export] 打包完成，共处理 {processed_files} 个文件")


def register_export_routes(
    app: Flask,
    papers_dir: str,
):
    """注册导出相关路由"""
    
    @app.route("/api/export/start", methods=["POST"])
    def api_export_start():
        """开始导出任务"""
        global current_export_task_id
        
        # 检查是否已有导出任务在运行
        with export_tasks_lock:
            if current_export_task_id and current_export_task_id in export_tasks:
                task = export_tasks[current_export_task_id]
                if task["status"] in ["running", "pending"]:
                    return jsonify({
                        "success": False,
                        "error": "已有导出任务正在运行",
                        "task_id": current_export_task_id
                    }), 400
        
        # 导出选项固定为只导出 JSON 元数据
        export_options = {}  # 不再需要选项
        
        # 创建任务ID
        task_id = f"export_{int(time.time() * 1000)}"
        
        # 初始化任务状态
        with export_tasks_lock:
            export_tasks[task_id] = {
                "task_id": task_id,
                "status": "pending",
                "progress": 0,
                "total": 0,
                "current_paper": "",
                "error": None,
                "zip_path": None,
                "options": export_options,
                "created_at": datetime.now().isoformat(),
            }
            current_export_task_id = task_id
        
        # 启动后台导出任务
        thread = threading.Thread(
            target=_export_task,
            args=(
                task_id,
                papers_dir,
                export_options,
            ),
            daemon=True,
        )
        thread.start()
        
        return jsonify({
            "success": True,
            "task_id": task_id,
            "message": "导出任务已启动"
        })
    
    @app.route("/api/export/status/<task_id>", methods=["GET"])
    def api_export_status(task_id: str):
        """查询导出任务状态"""
        with export_tasks_lock:
            if task_id not in export_tasks:
                return jsonify({
                    "success": False,
                    "error": "任务不存在"
                }), 404
            
            task = export_tasks[task_id]
            return jsonify({
                "success": True,
                "task": {
                    "task_id": task["task_id"],
                    "status": task["status"],
                    "progress": task["progress"],
                    "total": task["total"],
                    "current_paper": task["current_paper"],
                    "error": task["error"],
                    "created_at": task["created_at"],
                }
            })
    
    @app.route("/api/export/download/<task_id>", methods=["GET"])
    def api_export_download(task_id: str):
        """下载导出的 ZIP 文件"""
        with export_tasks_lock:
            if task_id not in export_tasks:
                return jsonify({
                    "success": False,
                    "error": "任务不存在"
                }), 404
            
            task = export_tasks[task_id]
            if task["status"] != "completed":
                return jsonify({
                    "success": False,
                    "error": "导出任务未完成"
                }), 400
            
            zip_path = task.get("zip_path")
            if not zip_path or not os.path.exists(zip_path):
                return jsonify({
                    "success": False,
                    "error": "导出文件不存在"
                }), 404
        
        # 生成下载文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_filename = f"Resophy_Export_{timestamp}.zip"
        
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=download_filename,
            mimetype="application/zip"
        )
    
    @app.route("/api/export/cancel/<task_id>", methods=["POST"])
    def api_export_cancel(task_id: str):
        """取消导出任务"""
        global current_export_task_id
        
        with export_tasks_lock:
            if task_id not in export_tasks:
                return jsonify({
                    "success": False,
                    "error": "任务不存在"
                }), 404
            
            task = export_tasks[task_id]
            if task["status"] in ["completed", "failed", "cancelled"]:
                return jsonify({
                    "success": False,
                    "error": "任务已结束，无法取消"
                }), 400
            
            # 标记为取消
            task["status"] = "cancelled"
            task["error"] = "用户取消"
            
            if current_export_task_id == task_id:
                current_export_task_id = None
        
        return jsonify({
            "success": True,
            "message": "导出任务已取消"
        })


def _export_task(
    task_id: str,
    papers_dir: str,
    export_options: Dict[str, Any],
):
    """后台导出任务（只导出 JSON 元数据）"""
    global current_export_task_id
    
    def update_progress(progress: int, total: int, current_item: str):
        with export_tasks_lock:
            if task_id in export_tasks:
                export_tasks[task_id]["progress"] = progress
                export_tasks[task_id]["total"] = total
                export_tasks[task_id]["current_paper"] = current_item
    
    try:
        # 更新状态为运行中
        with export_tasks_lock:
            if task_id not in export_tasks:
                return
            export_tasks[task_id]["status"] = "running"
        
        print(f"[Export] 开始导出任务: {task_id}")
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="paper_export_")
        zip_path = os.path.join(temp_dir, "export.zip")
        
        try:
            # 导出 papers 文件夹的 JSON 元数据
            print(f"[Export] 开始打包文件夹元数据: {papers_dir}")
            _export_papers_folder_to_zip(
                papers_dir,
                zip_path,
                progress_callback=update_progress,
            )
            
            print(f"[Export] 导出完成: {zip_path}")
            
            # 更新任务状态为完成
            with export_tasks_lock:
                if task_id in export_tasks:
                    export_tasks[task_id]["status"] = "completed"
                    export_tasks[task_id]["zip_path"] = zip_path
                    export_tasks[task_id]["current_paper"] = "导出完成"
        
        except Exception as e:
            print(f"[Export] 导出失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 更新任务状态为失败
            with export_tasks_lock:
                if task_id in export_tasks:
                    export_tasks[task_id]["status"] = "failed"
                    export_tasks[task_id]["error"] = str(e)
            
            # 清理临时文件
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    finally:
        # 清理当前任务ID
        with export_tasks_lock:
            if current_export_task_id == task_id:
                current_export_task_id = None
