"""
SQLite 搜索索引模块

提供论文搜索索引的数据库管理功能，使用 SQLite FTS5 全文搜索。
数据库文件存储在 papers-dir 目录下。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from core.base_paper import Paper


class SearchIndex:
    """线程安全的 SQLite 搜索索引管理器"""

    def __init__(self, db_path: str):
        """
        初始化搜索索引

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._lock = threading.RLock()
        self._rebuild_callback = None  # 重建索引的回调函数
        self._is_rebuilding = False  # 是否正在重建索引
        self._rebuild_lock = threading.Lock()  # 重建操作的锁
        self._init_database()

    def set_rebuild_callback(self, callback):
        """设置重建索引的回调函数"""
        self._rebuild_callback = callback

    def _check_database_integrity(self) -> bool:
        """检查数据库完整性"""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                # 执行完整性检查
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                return result and result[0] == "ok"
            finally:
                conn.close()
        except Exception:
            return False

    def _repair_database(self) -> None:
        """修复损坏的数据库：删除并重建"""
        # 如果已经在重建中，跳过
        with self._rebuild_lock:
            if self._is_rebuilding:
                return

            print(f"检测到数据库损坏，正在修复: {self.db_path}")
            try:
                # 备份损坏的数据库
                if os.path.exists(self.db_path):
                    backup_path = self.db_path + ".corrupted"
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                    os.rename(self.db_path, backup_path)
                    print(f"已备份损坏的数据库到: {backup_path}")

                # 删除损坏的数据库文件
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)

                # 重新初始化数据库
                self._init_database()
                print("数据库修复完成，需要重建索引")

                # 如果有重建回调，调用它（异步，不阻塞）
                if self._rebuild_callback:
                    print("触发索引重建（后台执行）...")
                    import threading

                    threading.Thread(target=self._rebuild_callback, daemon=True).start()
            except Exception as e:
                print(f"修复数据库失败: {e}")
                import traceback

                traceback.print_exc()

    def _init_database(self) -> None:
        """初始化数据库表结构"""
        with self._lock:
            # 使用 WAL 模式提高并发性能
            conn = sqlite3.connect(self.db_path)
            try:
                # 启用 WAL 模式（Write-Ahead Logging）
                conn.execute("PRAGMA journal_mode=WAL")
                # 设置同步模式为 NORMAL（性能更好，但仍安全）
                conn.execute("PRAGMA synchronous=NORMAL")
                # 设置缓存大小
                conn.execute("PRAGMA cache_size=-64000")  # 64MB
                cursor = conn.cursor()

                # 创建论文元数据表（包含 notes 字段，用于全文搜索备注）
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS papers (
                        id TEXT PRIMARY KEY,
                        title TEXT,
                        authors TEXT,
                        abstract TEXT,
                        notes TEXT,
                        filename TEXT,
                        category_id TEXT,
                        file_path TEXT,
                        updated_at TEXT
                    )
                    """
                )

                # 如果是旧版本数据库，可能还没有 notes 列，这里做一次轻量级迁移
                cursor.execute("PRAGMA table_info(papers)")
                columns = [row[1] for row in cursor.fetchall()]  # 第二列是列名
                if "notes" not in columns:
                    cursor.execute("ALTER TABLE papers ADD COLUMN notes TEXT")

                # 创建全文搜索虚拟表（FTS5），包含备注字段
                # 旧版本的 papers_fts 可能没有 notes 列，先检查一下
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_fts'"
                )
                has_fts = cursor.fetchone() is not None
                if has_fts:
                    cursor.execute("PRAGMA table_info(papers_fts)")
                    fts_columns = [row[1] for row in cursor.fetchall()]
                    if "notes" not in fts_columns:
                        # 旧的 FTS 表没有 notes，直接删除，稍后重新创建并重建索引
                        cursor.execute("DROP TABLE IF EXISTS papers_fts")

                cursor.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                        id UNINDEXED,
                        title,
                        authors,
                        abstract,
                        notes,
                        content='papers',
                        content_rowid='rowid'
                    )
                    """
                )

                # 创建触发器，自动更新 FTS 索引
                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS papers_fts_insert AFTER INSERT ON papers BEGIN
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        VALUES (new.rowid, new.id, new.title, new.authors, new.abstract, new.notes);
                    END
                    """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS papers_fts_delete AFTER DELETE ON papers BEGIN
                        DELETE FROM papers_fts WHERE rowid = old.rowid;
                    END
                    """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS papers_fts_update AFTER UPDATE ON papers BEGIN
                        DELETE FROM papers_fts WHERE rowid = old.rowid;
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        VALUES (new.rowid, new.id, new.title, new.authors, new.abstract, new.notes);
                    END
                    """
                )

                # 创建索引以加速查询
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(category_id)"
                )

                conn.commit()
            finally:
                conn.close()

    def index_paper(self, paper: Paper, category_id: Optional[str] = None) -> None:
        """
        索引一篇论文

        Args:
            paper: Paper 对象
            category_id: 论文所属分类ID
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO papers 
                        (id, title, authors, abstract, notes, filename, category_id, file_path, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (
                            paper.id,
                            paper.title or "",
                            paper.authors or "",
                            paper.abstract or "",
                            getattr(paper, "notes", "") or "",
                            paper.filename or "",
                            category_id or "",
                            paper.file_path or "",
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"索引论文时数据库损坏: {e}")
                    self._repair_database()
                else:
                    raise

    def remove_paper(self, paper_id: str) -> None:
        """
        从索引中删除论文

        Args:
            paper_id: 论文ID
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"删除论文时数据库损坏: {e}")
                    self._repair_database()
                else:
                    raise

    def update_paper_category(self, paper_id: str, category_id: Optional[str]) -> None:
        """
        更新论文的分类

        Args:
            paper_id: 论文ID
            category_id: 新的分类ID
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE papers SET category_id = ?, updated_at = datetime('now') WHERE id = ?",
                        (category_id or "", paper_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"更新分类时数据库损坏: {e}")
                    self._repair_database()
                else:
                    raise

    def search(
        self,
        query: str,
        category_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        搜索论文

        Args:
            query: 搜索关键词
            category_id: 限定搜索的分类ID（可选）
            limit: 返回结果数量限制

        Returns:
            搜索结果列表，每个结果包含：
            - id: 论文ID
            - title: 标题
            - authors: 作者
            - abstract: 摘要
            - filename: 文件名
            - category_id: 分类ID
            - matched_fields: 匹配的字段列表
            - similarity: 相似度分数
        """
        with self._lock:
            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                cursor = conn.cursor()

                # 构建 FTS 查询
                # 将查询作为完整短语进行匹配，使用双引号包裹
                # 这样可以确保 "lei zhang" 只会匹配连续的 "lei zhang"，而不是分开的 "lei" 和 "zhang"
                query_cleaned = query.strip()

                # 如果查询为空，直接返回空结果
                if not query_cleaned:
                    return []

                # 转义查询中的特殊字符（双引号需要转义）
                # FTS5 中的特殊字符：", *, AND, OR, NOT, NEAR
                # 在短语查询中，用双引号包裹后这些字符会被视为字面量，但双引号需要转义
                query_cleaned = query_cleaned.replace('"', '""')  # 转义双引号

                # 用双引号包裹查询，使其成为短语查询
                # 如果查询包含多个词，它们必须连续出现才能匹配
                # 例如："lei zhang" 只会匹配连续的 "lei zhang"，不会匹配 "Lei Li" 和 "Zhang" 分开的情况
                fts_query = f'"{query_cleaned}"'

                # 构建 SQL 查询
                if category_id:
                    sql = """
                        SELECT 
                            papers.id,
                            papers.title,
                            papers.authors,
                            papers.abstract,
                            papers.notes,
                            papers.filename,
                            papers.category_id,
                            bm25(papers_fts) as rank
                        FROM papers_fts
                        JOIN papers ON papers.id = papers_fts.id
                        WHERE papers_fts MATCH ? 
                            AND papers.category_id = ?
                        ORDER BY rank ASC, length(papers.title) ASC
                        LIMIT ?
                    """
                    params = (fts_query, category_id, limit)
                else:
                    sql = """
                        SELECT 
                            papers.id,
                            papers.title,
                            papers.authors,
                            papers.abstract,
                            papers.notes,
                            papers.filename,
                            papers.category_id,
                            bm25(papers_fts) as rank
                        FROM papers_fts
                        JOIN papers ON papers.id = papers_fts.id
                        WHERE papers_fts MATCH ?
                        ORDER BY rank ASC, length(papers.title) ASC
                        LIMIT ?
                    """
                    params = (fts_query, limit)

                cursor.execute(sql, params)
                rows = cursor.fetchall()

                # 处理结果
                query_lower = query.lower()
                results = []
                for row in rows:
                    pid, title, authors, abstract, notes, filename, cat_id, rank = row

                    # 确定真实命中的字段（包括备注 notes）
                    matched_fields = []
                    if title and query_lower in (title or "").lower():
                        matched_fields.append("title")
                    if authors and query_lower in (authors or "").lower():
                        matched_fields.append("authors")
                    if abstract and query_lower in (abstract or "").lower():
                        matched_fields.append("abstract")
                    if notes and query_lower in (notes or "").lower():
                        matched_fields.append("notes")

                    # 不再做“默认认为命中 title”的 fallback，
                    # 这样前端看到的 matched_fields 一定是真实包含 query 的字段集合

                    similarity = max(0.5, 1.0 - abs(rank) / 20.0) if rank else 0.5

                    results.append(
                        {
                            "id": pid,
                            "title": title or "",
                            "authors": authors or "",
                            "abstract": abstract or "",
                            "notes": notes or "",
                            "filename": filename or "",
                            "category_id": cat_id or None,
                            "matched_fields": matched_fields,
                            "similarity": similarity,
                        }
                    )

                return results

            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    # 搜索时遇到数据库损坏，不立即触发重建（避免阻塞）
                    # 只记录错误并返回空结果，重建会在后台进行
                    if not self._is_rebuilding:
                        print(f"搜索时检测到数据库损坏: {e}")
                        print("正在后台修复数据库，请稍后重试搜索...")
                        # 异步触发修复和重建，不阻塞搜索
                        import threading

                        threading.Thread(
                            target=self._repair_database, daemon=True
                        ).start()
                    return []
                else:
                    raise
            finally:
                if conn:
                    conn.close()

    def rebuild_index(self, papers: List[Tuple[Paper, Optional[str]]]) -> None:
        """
        重建整个索引

        Args:
            papers: 论文列表，每个元素是 (Paper, category_id) 元组
        """
        # 防止重复重建
        with self._rebuild_lock:
            if self._is_rebuilding:
                print("索引重建已在进行中，跳过本次重建")
                return
            self._is_rebuilding = True

        try:
            with self._lock:
                # 如果数据库损坏，先修复
                if not self._check_database_integrity():
                    print("检测到数据库损坏，先修复...")
                    self._repair_database()

            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                try:
                    cursor = conn.cursor()

                    # 清空现有数据
                    cursor.execute("DELETE FROM papers")
                    cursor.execute("DELETE FROM papers_fts")

                    # 批量插入
                    for paper, category_id in papers:
                        cursor.execute(
                            """
                            INSERT INTO papers 
                            (id, title, authors, abstract, notes, filename, category_id, file_path, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                            """,
                            (
                                paper.id,
                                paper.title or "",
                                paper.authors or "",
                                paper.abstract or "",
                                getattr(paper, "notes", "") or "",
                                paper.filename or "",
                                category_id or "",
                                paper.file_path or "",
                            ),
                        )

                    # 重建 FTS 索引
                    cursor.execute(
                        """
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        SELECT rowid, id, title, authors, abstract, notes FROM papers
                        """
                    )

                    conn.commit()
                    print(f"搜索索引重建完成，共索引 {len(papers)} 篇论文")
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"重建索引时数据库损坏: {e}")
                    self._repair_database()
                    # 修复后重新尝试（重置标志后递归调用）
                    if papers:
                        with self._rebuild_lock:
                            self._is_rebuilding = False
                        self.rebuild_index(papers)
                    return  # 递归调用后直接返回，不再执行 finally
                else:
                    raise
        finally:
            # 重置重建标志（确保无论成功或失败都会重置）
            with self._rebuild_lock:
                self._is_rebuilding = False

    def get_paper_count(self, category_id: Optional[str] = None) -> int:
        """
        获取论文数量

        Args:
            category_id: 分类ID（可选）

        Returns:
            论文数量
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                try:
                    cursor = conn.cursor()
                    if category_id:
                        cursor.execute(
                            "SELECT COUNT(*) FROM papers WHERE category_id = ?",
                            (category_id,),
                        )
                    else:
                        cursor.execute("SELECT COUNT(*) FROM papers")
                    return cursor.fetchone()[0]
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"获取论文数量时数据库损坏: {e}")
                    self._repair_database()
                    return 0
                else:
                    raise

    def clear(self) -> None:
        """清空所有索引数据"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM papers")
                    cursor.execute("DELETE FROM papers_fts")
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"清空索引时数据库损坏: {e}")
                    self._repair_database()
                else:
                    raise
