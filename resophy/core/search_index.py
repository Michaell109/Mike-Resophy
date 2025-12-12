"""
SQLite 搜索索引模块

提供论文搜索索引的数据库管理功能，使用 SQLite FTS5 全文搜索。
数据库文件存储在 papers-dir 目录下。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from resophy.core.base_paper import Paper


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
        self._last_checkpoint_time = 0  # 上次 checkpoint 的时间戳
        self._checkpoint_interval = 300  # 每 5 分钟执行一次 checkpoint
        self._init_database()

    def set_rebuild_callback(self, callback):
        """设置重建索引的回调函数"""
        self._rebuild_callback = callback

    def _maybe_checkpoint(self, force: bool = False) -> None:
        """
        定期执行 WAL checkpoint，防止 WAL 文件过大导致数据库损坏

        Args:
            force: 是否强制执行 checkpoint（忽略时间间隔）
        """
        import time

        current_time = time.time()

        # 如果距离上次 checkpoint 超过间隔时间，或者强制执行
        if (
            force
            or (current_time - self._last_checkpoint_time) >= self._checkpoint_interval
        ):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                try:
                    # 执行被动 checkpoint（不会阻塞其他连接）
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    self._last_checkpoint_time = current_time
                finally:
                    conn.close()
            except Exception as e:
                # checkpoint 失败不影响主操作，只记录日志
                print(f"WAL checkpoint 失败: {e}")

    def _extract_context_snippet(
        self, text: str, query: str, context_chars: int = 150
    ) -> str:
        """
        提取包含关键词的上下文片段

        Args:
            text: 原始文本
            query: 搜索关键词
            context_chars: 关键词前后各提取的字符数（默认150）

        Returns:
            包含关键词的上下文片段，如果未找到关键词则返回文本开头
        """
        if not text or not query:
            return text[: context_chars * 2] if text else ""

        text_lower = text.lower()
        query_lower = query.lower().strip()

        # 首先尝试查找完整查询短语
        match = None
        escaped_query = re.escape(query_lower)
        match = re.search(escaped_query, text_lower)

        # 如果找不到完整短语，尝试查找所有单词都出现的位置
        if not match:
            query_words = [w.strip() for w in query_lower.split() if w.strip()]
            if len(query_words) > 1:
                # 查找所有单词都出现的位置（单词之间可以有其他字符）
                # 构建正则表达式：单词1...单词2...单词3（顺序出现）
                pattern = r"\b.*\b".join(re.escape(w) for w in query_words)
                match = re.search(pattern, text_lower, re.IGNORECASE)

            # 如果还是找不到，尝试查找第一个单词
            if not match and query_words:
                first_word = query_words[0]
                match = re.search(re.escape(first_word), text_lower)

        # 对于中文，如果还是找不到，尝试查找中文字符（不区分顺序）
        if not match:
            # 检测是否包含中文字符
            chinese_chars = [
                char for char in query_lower if "\u4e00" <= char <= "\u9fff"
            ]
            if chinese_chars:
                # 尝试查找第一个中文字符的位置
                first_char = chinese_chars[0]
                match = re.search(re.escape(first_char), text_lower)

        # 如果仍然找不到，返回文本开头
        if not match:
            return (
                text[: context_chars * 2] + "..."
                if len(text) > context_chars * 2
                else text
            )

        # 获取匹配位置
        start_pos = match.start()
        end_pos = match.end()

        # 计算上下文范围
        snippet_start = max(0, start_pos - context_chars)
        snippet_end = min(len(text), end_pos + context_chars)

        # 提取片段
        snippet = text[snippet_start:snippet_end]

        # 如果片段不是从文本开头开始，添加省略号
        if snippet_start > 0:
            snippet = "..." + snippet
        # 如果片段不是到文本结尾，添加省略号
        if snippet_end < len(text):
            snippet = snippet + "..."

        return snippet

    def _check_database_integrity(self) -> bool:
        """检查数据库完整性"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
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
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            try:
                # 启用 WAL 模式（Write-Ahead Logging）
                conn.execute("PRAGMA journal_mode=WAL")
                # 设置同步模式为 FULL（更安全，避免数据损坏）
                conn.execute("PRAGMA synchronous=FULL")
                # 设置缓存大小
                conn.execute("PRAGMA cache_size=-64000")  # 64MB
                # 设置 WAL 自动 checkpoint（当 WAL 文件超过 10MB 时自动 checkpoint）
                conn.execute("PRAGMA wal_autocheckpoint=10000")  # 10MB
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
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
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
                # 定期执行 checkpoint 以防止 WAL 文件过大
                self._maybe_checkpoint()
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
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
                    conn.commit()
                finally:
                    conn.close()
                self._maybe_checkpoint()
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
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE papers SET category_id = ?, updated_at = datetime('now') WHERE id = ?",
                        (category_id or "", paper_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
                self._maybe_checkpoint()
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
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                cursor = conn.cursor()

                # 构建 FTS 查询
                query_cleaned = query.strip()

                # 如果查询为空，直接返回空结果
                if not query_cleaned:
                    return []

                # 检测是否包含中文字符
                has_chinese = any(
                    "\u4e00" <= char <= "\u9fff" for char in query_cleaned
                )

                # 转义查询中的特殊字符
                # FTS5 中的特殊字符：", *, AND, OR, NOT, NEAR
                query_cleaned_escaped = query_cleaned.replace('"', '""')

                # 对于中文查询，使用 LIKE 查询（FTS5 对中文支持不好）
                # 对于英文查询，使用 FTS5 全文搜索
                if has_chinese:
                    # 使用 LIKE 查询，支持部分匹配
                    # 转义 LIKE 中的特殊字符：%, _
                    like_query = query_cleaned.replace("%", "\\%").replace("_", "\\_")

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
                                0.0 as rank
                            FROM papers
                            WHERE papers.category_id = ?
                                AND (
                                    papers.title LIKE ? 
                                    OR papers.authors LIKE ?
                                    OR papers.abstract LIKE ?
                                    OR papers.notes LIKE ?
                                )
                            ORDER BY 
                                CASE 
                                    WHEN papers.title LIKE ? THEN 1
                                    WHEN papers.authors LIKE ? THEN 2
                                    WHEN papers.abstract LIKE ? THEN 3
                                    WHEN papers.notes LIKE ? THEN 4
                                    ELSE 5
                                END,
                                length(papers.title) ASC
                            LIMIT ?
                        """
                        like_pattern = f"%{like_query}%"
                        params = (
                            category_id,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            limit,
                        )
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
                                0.0 as rank
                            FROM papers
                            WHERE (
                                papers.title LIKE ? 
                                OR papers.authors LIKE ?
                                OR papers.abstract LIKE ?
                                OR papers.notes LIKE ?
                            )
                            ORDER BY 
                                CASE 
                                    WHEN papers.title LIKE ? THEN 1
                                    WHEN papers.authors LIKE ? THEN 2
                                    WHEN papers.abstract LIKE ? THEN 3
                                    WHEN papers.notes LIKE ? THEN 4
                                    ELSE 5
                                END,
                                length(papers.title) ASC
                            LIMIT ?
                        """
                        like_pattern = f"%{like_query}%"
                        params = (
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            limit,
                        )

                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                else:
                    # 对于英文查询，使用 FTS5 全文搜索（保持原有逻辑）
                    fts_query = f'"{query_cleaned_escaped}"'

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
                    abstract_snippet = None
                    notes_snippet = None
                    if title and query_lower in (title or "").lower():
                        matched_fields.append("title")
                    if authors and query_lower in (authors or "").lower():
                        matched_fields.append("authors")
                    if abstract and query_lower in (abstract or "").lower():
                        matched_fields.append("abstract")
                        # 提取包含关键词的上下文片段
                        abstract_snippet = self._extract_context_snippet(
                            abstract, query, context_chars=150
                        )
                    if notes and query_lower in (notes or "").lower():
                        matched_fields.append("notes")
                        # 提取包含关键词的上下文片段
                        notes_snippet = self._extract_context_snippet(
                            notes, query, context_chars=150
                        )

                    # 不再做"默认认为命中 title"的 fallback，
                    # 这样前端看到的 matched_fields 一定是真实包含 query 的字段集合

                    similarity = max(0.5, 1.0 - abs(rank) / 20.0) if rank else 0.5

                    result_item = {
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
                    # 如果提取了摘要片段，添加到结果中
                    if abstract_snippet:
                        result_item["abstract_snippet"] = abstract_snippet
                    # 如果提取了备注片段，添加到结果中
                    if notes_snippet:
                        result_item["notes_snippet"] = notes_snippet

                    results.append(result_item)

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
                conn = sqlite3.connect(
                    self.db_path, timeout=60.0
                )  # 重建索引需要更长时间
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
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
                    # 重建后执行完整 checkpoint
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
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
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
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
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM papers")
                    cursor.execute("DELETE FROM papers_fts")
                    conn.commit()
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    print(f"清空索引时数据库损坏: {e}")
                    self._repair_database()
                else:
                    raise
