"""
Daily arXiv 爬虫模块

提供每日 arXiv 论文获取功能，支持:
- 自动化定时抓取
- 按日期/分区组织论文
- 进度追踪
- 过期论文清理
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import arxiv

# 机构提取的系统提示词
AFFILIATION_EXTRACTION_PROMPT = """I will provide you with the first-page information of a paper. You need to extract all affiliations (institution names) from it and also extract the homepage and github repo url if there is. For affiliations, do not include author names. If an affiliation includes details such as region, department, school, or college, those should be omitted. Only keep the main institution name (e.g., School of Computer Science, Fudan University → Fudan University).

Output the result directly in JSON format, and make sure it is valid JSON. For example:
{"affiliations": ["Google Brain", "Google Research", "Fudan University"], "homepage": "transformer.github.io", "github": "github.com/transformer"}

Notes:
1. If there is no homepage or github url, use the JSON value null (not the string "null" and not Python None).
2. Do NOT add a trailing comma after the last field.
3. Do not include any explanation or extra text, only output the JSON object.

Now the input is:
"""

# 摘要总结和关键词提取的系统提示词
SUMMARY_EXTRACTION_PROMPT = """我会给你一篇 AI 文章的英文摘要，你需要简要的总结这篇文章在解决怎样的问题，是如何解决的，然后在最后提供关于这篇文章的 文章的类型的 3个 英文关键词，这个类型不需要细分，要按照大类划分，比如 Image Generation，Object Detection，3D Reconstruction 这种，以如下的 JSON 格式输出:

{"summary": "这篇文章主要解决...的问题。作者提出...方法，通过...实现了...", "keywords": ["Keyword1", "Keyword2", "Keyword3"]}

注意：
1. summary 用中文简洁描述，控制在 100-200 字
2. keywords 用英文，提供 3 个最能代表文章的类型的关键词
3. 直接输出 JSON，不要有任何其他解释

现在输入的摘要是:
"""


def get_arxiv_announce_date(submitted: datetime = None) -> datetime:
    """
    获取 arXiv 公布日期

    arXiv 公布时间规则：
    - 周一到周四：当天 UTC 20:00 公布
    - 周五：周一 UTC 20:00 公布
    - 周末不公布

    论文截止时间：UTC 14:00 之前提交的论文在当天公布
    """
    if submitted is None:
        submitted = datetime.utcnow()

    # 获取日期和小时
    submit_date = submitted.date() if hasattr(submitted, "date") else submitted
    submit_hour = submitted.hour if hasattr(submitted, "hour") else 12

    # 如果在 14:00 UTC 之后提交，推迟一天
    if submit_hour >= 14:
        announce_date = submit_date + timedelta(days=1)
    else:
        announce_date = submit_date

    # 调整周末
    weekday = announce_date.weekday()
    if weekday == 5:  # Saturday -> Monday
        announce_date = announce_date + timedelta(days=2)
    elif weekday == 6:  # Sunday -> Monday
        announce_date = announce_date + timedelta(days=1)

    return datetime.combine(announce_date, datetime.min.time())


def get_today_arxiv_date() -> str:
    """
    获取今日日期字符串 (YYYY-MM-DD)
    使用本地时间
    """
    return datetime.now().strftime("%Y-%m-%d")


@dataclass
class ArxivPaper:
    """arXiv 论文数据类"""

    arxiv_id: str
    title: str
    authors: str
    abstract: str
    published: datetime  # 首次提交时间
    updated: datetime  # 最新版本时间
    announced: datetime  # 公布日期（在 arXiv 列表显示的日期）
    pdf_url: str
    categories: List[str]
    primary_category: str
    comment: Optional[str] = None
    journal_ref: Optional[str] = None

    # 本地状态
    local_pdf_path: Optional[str] = None
    thumbnail_path: Optional[str] = None

    # 机构信息
    affiliations: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=list)  # 国家列表，与 affiliations 对应
    affiliations_extracted: bool = False

    # 项目链接
    homepage: Optional[str] = None
    github: Optional[str] = None

    # LLM 提取的摘要和关键词
    summary: Optional[str] = None  # 中文简要总结
    keywords: List[str] = field(default_factory=list)  # 英文关键词
    summary_extracted: bool = False

    # 抓取信息
    fetch_category: Optional[str] = None  # 从哪个分区抓取的
    fetch_date: Optional[str] = None  # 抓取日期 (YYYY-MM-DD)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "published": self.published.isoformat() if self.published else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "announced": self.announced.isoformat() if self.announced else None,
            "pdf_url": self.pdf_url,
            "categories": self.categories,
            "primary_category": self.primary_category,
            "comment": self.comment,
            "journal_ref": self.journal_ref,
            "local_pdf_path": self.local_pdf_path,
            "thumbnail_path": self.thumbnail_path,
            "affiliations": self.affiliations,
            "countries": self.countries,
            "affiliations_extracted": self.affiliations_extracted,
            "homepage": self.homepage,
            "github": self.github,
            "summary": self.summary,
            "keywords": self.keywords,
            "summary_extracted": self.summary_extracted,
            "fetch_category": self.fetch_category,
            "fetch_date": self.fetch_date,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArxivPaper":
        """从字典创建"""

        def parse_datetime(s):
            if not s:
                return None
            if isinstance(s, datetime):
                return s
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except:
                return None

        return cls(
            arxiv_id=data.get("arxiv_id", ""),
            title=data.get("title", ""),
            authors=data.get("authors", ""),
            abstract=data.get("abstract", ""),
            published=parse_datetime(data.get("published")),
            updated=parse_datetime(data.get("updated")),
            announced=parse_datetime(data.get("announced")),
            pdf_url=data.get("pdf_url", ""),
            categories=data.get("categories", []),
            primary_category=data.get("primary_category", ""),
            comment=data.get("comment"),
            journal_ref=data.get("journal_ref"),
            local_pdf_path=data.get("local_pdf_path"),
            thumbnail_path=data.get("thumbnail_path"),
            affiliations=data.get("affiliations", []),
            countries=data.get("countries", []),
            affiliations_extracted=data.get("affiliations_extracted", False),
            homepage=data.get("homepage"),
            github=data.get("github"),
            summary=data.get("summary"),
            keywords=data.get("keywords", []),
            summary_extracted=data.get("summary_extracted", False),
            fetch_category=data.get("fetch_category"),
            fetch_date=data.get("fetch_date"),
        )

    @classmethod
    def from_arxiv_result(
        cls, result: arxiv.Result, fetch_category: str = None
    ) -> "ArxivPaper":
        """从 arxiv 库的 Result 对象创建"""
        # 提取 arXiv ID
        arxiv_id = result.entry_id.split("/abs/")[-1]

        # 格式化作者
        authors = ", ".join(author.name for author in result.authors)

        # 获取分类
        categories = list(result.categories) if result.categories else []
        primary_category = result.primary_category or (
            categories[0] if categories else ""
        )

        # 计算公布日期
        announced = get_arxiv_announce_date(result.published)

        return cls(
            arxiv_id=arxiv_id,
            title=result.title.replace("\n", " ").strip(),
            authors=authors,
            abstract=(
                result.summary.replace("\n", " ").strip() if result.summary else ""
            ),
            published=result.published,
            updated=result.updated,
            announced=announced,
            pdf_url=result.pdf_url,
            categories=categories,
            primary_category=primary_category,
            comment=result.comment,
            journal_ref=result.journal_ref,
            fetch_category=fetch_category,
            fetch_date=get_today_arxiv_date(),
        )


class FetchProgress:
    """抓取进度追踪"""

    def __init__(self):
        self.total = 0
        self.current = 0
        self.status = "idle"  # idle, fetching, processing, done, error
        self.message = ""
        self.current_paper = None
        self.papers = []
        self.lock = threading.Lock()

    def reset(self, total: int = 0):
        with self.lock:
            self.total = total
            self.current = 0
            self.status = "fetching"
            self.message = "正在获取论文列表..."
            self.current_paper = None
            self.papers = []

    def set_processing(self, total: int):
        with self.lock:
            self.total = total
            self.current = 0
            self.status = "processing"
            self.message = f"正在处理 0/{total} 篇论文"

    def update(self, current: int, paper_title: str = None):
        with self.lock:
            self.current = current
            self.current_paper = paper_title
            self.message = f"正在处理 {current}/{self.total} 篇论文"

    def add_paper(self, paper_dict: Dict):
        with self.lock:
            self.papers.append(paper_dict)

    def set_done(self, message: str = "完成"):
        with self.lock:
            self.status = "done"
            self.message = message

    def set_error(self, error: str):
        with self.lock:
            self.status = "error"
            self.message = error

    def to_dict(self) -> Dict:
        with self.lock:
            return {
                "total": self.total,
                "current": self.current,
                "status": self.status,
                "message": self.message,
                "current_paper": self.current_paper,
                "papers": list(self.papers),
            }


class DailyArxivManager:
    """
    Daily arXiv 管理器

    负责：
    - 按日期/分区组织论文文件
    - 自动化定时抓取
    - 进度追踪
    - 过期论文清理
    """

    def __init__(self, base_dir: str, settings_file: str):
        """
        初始化

        Args:
            base_dir: 基础目录，如 papers/.daily_arxiv_temp
            settings_file: 设置文件路径
        """
        self.base_dir = base_dir
        self.settings_file = settings_file
        self.metadata_file = os.path.join(base_dir, "metadata.json")

        os.makedirs(base_dir, exist_ok=True)

        # arXiv 客户端
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3.0,
            num_retries=3,
        )

        # 进度追踪（按分区）
        self.progress: Dict[str, FetchProgress] = {}

        # 调度器
        self._scheduler_thread = None
        self._scheduler_running = False
        self._last_fetch_time: Dict[str, datetime] = {}

        # LLM 配置回调
        self._get_llm_config: Optional[Callable[[], Dict]] = None

        # 加载已有元数据
        self._load_metadata()

    def set_llm_config_callback(self, callback: Callable[[], Dict]):
        """设置获取 LLM 配置的回调函数"""
        self._get_llm_config = callback

    def _load_metadata(self):
        """加载元数据"""
        self._metadata = {}
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
            except Exception as e:
                print(f"[DailyArxiv] 加载元数据失败: {e}")

    def _save_metadata(self):
        """保存元数据"""
        try:
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self._metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DailyArxiv] 保存元数据失败: {e}")

    def get_settings(self) -> Dict:
        """获取设置"""
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def get_date_dir(self, date_str: str) -> str:
        """获取日期目录路径"""
        return os.path.join(self.base_dir, date_str)

    def get_category_dir(self, date_str: str, category: str) -> str:
        """获取分区目录路径"""
        return os.path.join(self.base_dir, date_str, category.replace(".", "_"))

    def get_available_dates(self) -> List[str]:
        """
        获取有论文的日期列表

        Returns:
            日期列表（降序，最新在前）
        """
        dates = []
        if not os.path.exists(self.base_dir):
            return dates

        for name in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if os.path.isdir(path) and name.count("-") == 2:
                # 检查是否有论文
                has_papers = False
                for cat_dir in os.listdir(path):
                    cat_path = os.path.join(path, cat_dir)
                    if os.path.isdir(cat_path):
                        # 检查是否有 JSON 文件
                        for f in os.listdir(cat_path):
                            if f.endswith(".json"):
                                has_papers = True
                                break
                    if has_papers:
                        break

                if has_papers:
                    dates.append(name)

        dates.sort(reverse=True)
        return dates

    def get_papers_for_date(self, date_str: str, category: str = None) -> List[Dict]:
        """
        获取某日期的论文

        Args:
            date_str: 日期字符串 (YYYY-MM-DD)
            category: 分区（可选，不指定则返回所有分区）

        Returns:
            论文字典列表
        """
        papers = []
        date_dir = self.get_date_dir(date_str)

        if not os.path.exists(date_dir):
            return papers

        # 确定要读取的分区目录
        if category:
            cat_dirs = [self.get_category_dir(date_str, category)]
        else:
            cat_dirs = [
                os.path.join(date_dir, d)
                for d in os.listdir(date_dir)
                if os.path.isdir(os.path.join(date_dir, d))
            ]

        for cat_dir in cat_dirs:
            if not os.path.exists(cat_dir):
                continue

            for filename in os.listdir(cat_dir):
                if filename.endswith(".json"):
                    json_path = os.path.join(cat_dir, filename)
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            paper_data = json.load(f)
                            papers.append(paper_data)
                    except Exception as e:
                        print(f"[DailyArxiv] 读取论文失败 {json_path}: {e}")

        return papers

    def get_progress(self, category: str) -> Dict:
        """获取分区的抓取进度"""
        if category not in self.progress:
            self.progress[category] = FetchProgress()
        return self.progress[category].to_dict()

    def fetch_papers(
        self,
        category: str,
        date_str: str = None,
        max_results: int = 3,
        force: bool = False,
    ) -> List[Dict]:
        """
        抓取论文

        Args:
            category: arXiv 分区
            date_str: 日期（用于缓存检查，默认今天）
            max_results: 最大数量
            force: 强制重新抓取

        Returns:
            论文列表（按论文的实际公布日期存储）
        """
        if date_str is None:
            date_str = get_today_arxiv_date()

        # 初始化进度
        if category not in self.progress:
            self.progress[category] = FetchProgress()
        progress = self.progress[category]
        progress.reset(max_results)

        try:
            # 获取论文列表
            print(f"[DailyArxiv] 正在获取 {category} 论文...")
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            results = list(self.client.results(search))
            print(f"[DailyArxiv] 获取到 {len(results)} 篇 {category} 论文")

            if not results:
                progress.set_done("没有找到论文")
                return []

            # 先统计论文的实际公布日期分布
            date_counts = {}
            for result in results:
                paper_tmp = ArxivPaper.from_arxiv_result(
                    result, fetch_category=category
                )
                announce_date = (
                    paper_tmp.announced.strftime("%Y-%m-%d")
                    if paper_tmp.announced
                    else "unknown"
                )
                date_counts[announce_date] = date_counts.get(announce_date, 0) + 1

            # 打印日期分布
            date_info = ", ".join(
                [f"{d}: {c}篇" for d, c in sorted(date_counts.items(), reverse=True)]
            )
            print(f"[DailyArxiv] 论文公布日期分布: {date_info}")

            # 设置处理进度
            progress.set_processing(len(results))

            # 获取 LLM 配置
            llm_config = {}
            if self._get_llm_config:
                llm_config = self._get_llm_config()

            # 获取自定义 prompt
            settings = self.get_settings()
            affiliation_prompt = settings.get("affiliationPrompt")
            summary_prompt = settings.get("summaryPrompt")
            keyword_list = settings.get("keywordList", [])
            max_keywords = settings.get("maxKeywords", 1)

            # 将关键词列表和最多关键词数插入到 prompt 中
            if summary_prompt:
                if keyword_list:
                    keyword_list_str = ", ".join(keyword_list)
                    summary_prompt = summary_prompt.replace(
                        "{keyword_list}", keyword_list_str
                    )
                # 替换最多关键词数占位符
                summary_prompt = summary_prompt.replace(
                    "{max_keywords}", str(max_keywords)
                )

            papers = []
            skipped_count = 0

            for i, result in enumerate(results):
                paper = ArxivPaper.from_arxiv_result(result, fetch_category=category)

                # 使用论文的实际公布日期作为存储目录
                paper_announce_date = (
                    paper.announced.strftime("%Y-%m-%d")
                    if paper.announced
                    else date_str
                )
                paper.fetch_date = paper_announce_date

                # 获取该日期对应的目录
                paper_cat_dir = self.get_category_dir(paper_announce_date, category)
                os.makedirs(paper_cat_dir, exist_ok=True)

                # 检查论文是否已存在（跳过已下载的）
                safe_id = paper.arxiv_id.replace("/", "_").replace(":", "_")
                json_path = os.path.join(paper_cat_dir, f"{safe_id}.json")
                if not force and os.path.exists(json_path):
                    # 已存在，检查是否需要生成缩略图
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            existing_data = json.load(f)
                        paper_dict = existing_data

                        # 如果已有PDF但还没有缩略图，尝试生成
                        if paper_dict.get("local_pdf_path") and not paper_dict.get(
                            "thumbnail_path"
                        ):
                            pdf_path = paper_dict["local_pdf_path"]
                            if os.path.exists(pdf_path):
                                thumbnail_path = self._generate_thumbnail(
                                    pdf_path, paper_cat_dir
                                )
                                if thumbnail_path:
                                    paper_dict["thumbnail_path"] = thumbnail_path
                                    self._save_paper(paper_dict, paper_cat_dir)
                    except Exception as e:
                        print(f"[DailyArxiv] 检查已存在论文缩略图失败: {e}")

                    skipped_count += 1
                    progress.update(i + 1, f"[已存在] {paper.title[:40]}")
                    continue

                progress.update(i + 1, paper.title[:50])

                # 下载 PDF 到正确的日期目录
                pdf_path = self._download_pdf(paper, paper_cat_dir)
                if pdf_path:
                    paper.local_pdf_path = pdf_path

                    # 生成缩略图（PDF第一页上半部分）
                    thumbnail_path = self._generate_thumbnail(pdf_path, paper_cat_dir)
                    if thumbnail_path:
                        paper.thumbnail_path = thumbnail_path

                    # 提取机构、homepage 和 github（从 PDF 第一页）
                    if llm_config.get("openaiBaseUrl") and llm_config.get(
                        "openaiApiKey"
                    ):
                        extraction_result = self._extract_affiliations(
                            pdf_path,
                            llm_config["openaiBaseUrl"],
                            llm_config["openaiApiKey"],
                            prompt=affiliation_prompt,
                        )
                        paper.affiliations = extraction_result.get("affiliations", [])
                        paper.countries = extraction_result.get("countries", [])
                        paper.homepage = extraction_result.get("homepage")
                        paper.github = extraction_result.get("github")
                        paper.affiliations_extracted = True

                # 提取摘要和关键词（从 abstract）
                if (
                    llm_config.get("openaiBaseUrl")
                    and llm_config.get("openaiApiKey")
                    and paper.abstract
                ):
                    summary_result = extract_summary_and_keywords_with_llm(
                        paper.abstract,
                        llm_config["openaiBaseUrl"],
                        llm_config["openaiApiKey"],
                        prompt=summary_prompt,
                    )
                    paper.summary = summary_result.get("summary")
                    paper.keywords = summary_result.get("keywords", [])
                    paper.summary_extracted = True

                # 保存论文元数据到正确的日期目录
                paper_dict = paper.to_dict()
                self._save_paper(paper_dict, paper_cat_dir)

                papers.append(paper_dict)
                progress.add_paper(paper_dict)

            msg = f"完成，新增 {len(papers)} 篇论文"
            if skipped_count > 0:
                msg += f"，跳过 {skipped_count} 篇已存在"
            progress.set_done(msg)
            self._last_fetch_time[category] = datetime.now()

            return papers

        except Exception as e:
            print(f"[DailyArxiv] 抓取 {category} 论文失败: {e}")
            import traceback

            traceback.print_exc()
            progress.set_error(str(e))
            return []

    def _download_pdf(self, paper: ArxivPaper, cat_dir: str) -> Optional[str]:
        """下载 PDF"""
        try:
            safe_id = paper.arxiv_id.replace("/", "_").replace(":", "_")
            pdf_filename = f"{safe_id}.pdf"
            pdf_path = os.path.join(cat_dir, pdf_filename)

            if os.path.exists(pdf_path):
                return pdf_path

            print(f"[DailyArxiv] 下载 PDF: {paper.arxiv_id}")
            urllib.request.urlretrieve(paper.pdf_url, pdf_path)
            return pdf_path

        except Exception as e:
            print(f"[DailyArxiv] 下载 PDF 失败 ({paper.arxiv_id}): {e}")
            return None

    def _generate_thumbnail(self, pdf_path: str, cat_dir: str) -> Optional[str]:
        """生成PDF缩略图"""
        try:
            safe_id = os.path.splitext(os.path.basename(pdf_path))[0]
            thumbnail_filename = f"{safe_id}_thumbnail.jpg"
            thumbnail_path = os.path.join(cat_dir, thumbnail_filename)

            # 如果缩略图已存在，直接返回
            if os.path.exists(thumbnail_path):
                return thumbnail_path

            # 生成缩略图
            return generate_pdf_thumbnail(pdf_path, thumbnail_path, crop_ratio=0.5)
        except Exception as e:
            print(f"[DailyArxiv] 生成缩略图失败: {e}")
            return None

    def _extract_affiliations(
        self,
        pdf_path: str,
        openai_base_url: str,
        openai_api_key: str,
        prompt: str = None,
    ) -> Dict[str, Any]:
        """提取机构信息、国家、homepage 和 github"""
        first_page_text = extract_pdf_first_page_text(pdf_path)
        if not first_page_text:
            return {
                "affiliations": [],
                "countries": [],
                "homepage": None,
                "github": None,
            }

        return extract_affiliations_with_llm(
            first_page_text,
            openai_base_url,
            openai_api_key,
            prompt=prompt,
            settings_file=self.settings_file,
        )

    def _save_paper(self, paper_dict: Dict, cat_dir: str):
        """保存论文元数据"""
        arxiv_id = paper_dict.get("arxiv_id", "unknown")
        safe_id = arxiv_id.replace("/", "_").replace(":", "_")
        json_path = os.path.join(cat_dir, f"{safe_id}.json")

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(paper_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DailyArxiv] 保存论文元数据失败: {e}")

    def cleanup_old_papers(self, retention_days: int = 7):
        """
        清理过期论文

        Args:
            retention_days: 保留天数
        """
        print(f"[DailyArxiv] 清理 {retention_days} 天前的论文...")

        cutoff_date = (datetime.now() - timedelta(days=retention_days)).strftime(
            "%Y-%m-%d"
        )

        if not os.path.exists(self.base_dir):
            return

        for name in os.listdir(self.base_dir):
            path = os.path.join(self.base_dir, name)
            if os.path.isdir(path) and name.count("-") == 2:
                if name < cutoff_date:
                    print(f"[DailyArxiv] 删除过期目录: {name}")
                    try:
                        shutil.rmtree(path)
                    except Exception as e:
                        print(f"[DailyArxiv] 删除失败: {e}")

    def start_scheduler(self):
        """启动调度器"""
        if self._scheduler_running:
            return

        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True
        )
        self._scheduler_thread.start()
        print("[DailyArxiv] 调度器已启动")

    def stop_scheduler(self):
        """停止调度器"""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        print("[DailyArxiv] 调度器已停止")

    def _scheduler_loop(self):
        """调度器主循环"""
        # 启动时立即执行一次
        self._do_scheduled_fetch()

        while self._scheduler_running:
            settings = self.get_settings()
            interval_minutes = settings.get("checkIntervalMinutes", 10)

            # 等待
            for _ in range(interval_minutes * 60):
                if not self._scheduler_running:
                    return
                time.sleep(1)

            # 执行抓取
            self._do_scheduled_fetch()

    def _do_scheduled_fetch(self):
        """执行计划抓取"""
        settings = self.get_settings()

        categories = settings.get("categories", [])
        max_papers = settings.get("maxPapersPerCategory", 3)
        retention_days = settings.get("retentionDays", 7)

        if not categories:
            print("[DailyArxiv] 未配置分区")
            return

        print(f"[DailyArxiv] 开始定时抓取: {categories}")

        # 清理过期论文
        self.cleanup_old_papers(retention_days)

        # 抓取每个分区
        for category in categories:
            try:
                self.fetch_papers(category, max_results=max_papers, force=False)
            except Exception as e:
                print(f"[DailyArxiv] 抓取 {category} 失败: {e}")

            # 分区间间隔，避免请求过快
            time.sleep(2)

        print("[DailyArxiv] 定时抓取完成")


def extract_pdf_first_page_text(pdf_path: str) -> Optional[str]:
    """
    提取 PDF 第一页的文本内容

    Args:
        pdf_path: PDF 文件路径

    Returns:
        第一页文本，失败返回 None
    """
    try:
        # 使用 PyMuPDF (fitz) 提取，它能更好地保留空格
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        if len(doc) > 0:
            page = doc[0]
            text = page.get_text()
            doc.close()
            return text if text else None
        doc.close()
        return None
    except ImportError:
        # 如果没有 PyMuPDF，降级使用 pdfplumber
        try:
            import pdfplumber

            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) > 0:
                    page = pdf.pages[0]
                    text = page.extract_text()
                    return text if text else None
            return None
        except Exception as e:
            print(f"[DailyArxiv] 提取 PDF 第一页文本失败 (pdfplumber): {e}")
            return None
    except Exception as e:
        print(f"[DailyArxiv] 提取 PDF 第一页文本失败: {e}")
        return None


def generate_pdf_thumbnail(
    pdf_path: str, output_path: str = None, crop_ratio: float = 0.5
) -> Optional[str]:
    """
    生成 PDF 第一页上半部分的缩略图

    Args:
        pdf_path: PDF 文件路径
        output_path: 输出图片路径（可选，默认与PDF同目录）
        crop_ratio: 裁剪比例，0.5 表示上半部分

    Returns:
        缩略图路径，失败返回 None
    """
    try:
        import fitz  # PyMuPDF

        # 如果没有指定输出路径，使用PDF同目录
        if output_path is None:
            base_name = os.path.splitext(pdf_path)[0]
            output_path = f"{base_name}_thumbnail.jpg"

        # 打开PDF
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return None

        # 获取第一页
        page = doc[0]

        # 设置缩放因子（提高清晰度）
        zoom = 2.0  # 2倍缩放，生成更清晰的图片
        mat = fitz.Matrix(zoom, zoom)

        # 渲染第一页为图片
        pix = page.get_pixmap(matrix=mat)

        # 转换为PIL Image
        try:
            from io import BytesIO

            from PIL import Image
        except ImportError:
            print(f"[DailyArxiv] 生成缩略图失败: 需要安装 Pillow (pip install Pillow)")
            doc.close()
            return None

        img_data = pix.tobytes("ppm")
        img = Image.open(BytesIO(img_data))

        # 获取图片尺寸
        width, height = img.size

        # 裁剪上半部分（根据 crop_ratio）
        crop_height = int(height * crop_ratio)
        img_cropped = img.crop((0, 0, width, crop_height))

        # 保存为JPEG（压缩以减小文件大小）
        img_cropped.save(output_path, "JPEG", quality=85, optimize=True)

        doc.close()
        print(f"[DailyArxiv] 生成缩略图: {output_path}")
        return output_path

    except ImportError:
        print(f"[DailyArxiv] 生成缩略图失败: 需要安装 PyMuPDF 和 Pillow")
        return None
    except Exception as e:
        print(f"[DailyArxiv] 生成缩略图失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def extract_affiliations_with_llm(
    first_page_text: str,
    openai_base_url: str,
    openai_api_key: str,
    prompt: str = None,
    settings_file: str = None,
) -> Dict[str, Any]:
    """
    使用 LLM 从 PDF 第一页文本中提取机构信息、homepage 和 github

    Args:
        first_page_text: PDF 第一页文本
        openai_base_url: OpenAI API 基础 URL
        openai_api_key: OpenAI API 密钥
        prompt: 自定义提示词（可选）
        settings_file: 配置文件路径（可选，用于读取自定义机构映射）

    Returns:
        包含 affiliations, homepage, github 的字典
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        # 获取可用模型
        try:
            models = client.models.list()
            model = models.data[0].id if models.data else None
            if not model:
                print("[DailyArxiv] 无法获取模型列表")
                return {
                    "affiliations": [],
                    "countries": [],
                    "homepage": None,
                    "github": None,
                }
        except Exception as e:
            print(f"[DailyArxiv] 获取模型列表失败: {e}")
            return {
                "affiliations": [],
                "countries": [],
                "homepage": None,
                "github": None,
            }

        # 构造提示词（使用自定义或默认）
        system_prompt = prompt if prompt else AFFILIATION_EXTRACTION_PROMPT
        full_prompt = system_prompt + first_page_text
        messages = [{"role": "user", "content": full_prompt}]

        print(f"[DailyArxiv] 使用模型 {model} 提取机构信息、homepage 和 github...")

        # 调用 LLM
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
            temperature=0.1,
            max_tokens=800,  # 增加 token 数量以支持更多信息
        )

        result_content = chat_completion.choices[0].message.content.strip()

        # 解析 JSON 结果（新格式：包含 affiliations, homepage, github）
        try:
            # 尝试直接解析 JSON
            if result_content.startswith("{"):
                result = json.loads(result_content)
            else:
                # 尝试从文本中提取 JSON
                import re

                json_match = re.search(r"\{.*\}", result_content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    # 兼容旧格式（只有数组）
                    if result_content.startswith("["):
                        affiliations = json.loads(result_content)
                        result = {
                            "affiliations": affiliations,
                            "countries": [],
                            "homepage": None,
                            "github": None,
                        }
                    else:
                        print(f"[DailyArxiv] 无法解析结果: {result_content[:200]}")
                        return {
                            "affiliations": [],
                            "countries": [],
                            "homepage": None,
                            "github": None,
                        }
        except json.JSONDecodeError as e:
            print(f"[DailyArxiv] JSON 解析失败: {e}")
            print(f"[DailyArxiv] 原始内容: {result_content[:200]}")
            return {
                "affiliations": [],
                "countries": [],
                "homepage": None,
                "github": None,
            }

        # 提取 affiliations（兼容旧格式）
        affiliations = result.get("affiliations", [])
        if not isinstance(affiliations, list):
            affiliations = []

        # 去重并保持顺序
        seen = set()
        unique_affiliations = []
        for aff in affiliations:
            if isinstance(aff, str) and aff.strip() and aff.strip() not in seen:
                seen.add(aff.strip())
                unique_affiliations.append(aff.strip())

        # 提取 countries（与 affiliations 对应）
        countries = result.get("countries", [])
        if not isinstance(countries, list):
            countries = []

        # 确保 countries 列表长度与 affiliations 一致（如果长度不一致，截断或填充）
        if len(countries) > len(unique_affiliations):
            countries = countries[: len(unique_affiliations)]
        elif len(countries) < len(unique_affiliations):
            countries.extend([""] * (len(unique_affiliations) - len(countries)))

        # 去重 countries（使用 set，但保持顺序）
        unique_countries = []
        seen_countries = set()
        for country in countries:
            if isinstance(country, str) and country.strip():
                country_clean = country.strip()
                if country_clean not in seen_countries:
                    seen_countries.add(country_clean)
                    unique_countries.append(country_clean)

        # 提取 homepage 和 github
        homepage = result.get("homepage")
        github = result.get("github")

        # 处理 None 或空字符串
        if homepage == "None" or homepage == "":
            homepage = None
        if github == "None" or github == "":
            github = None

        # 规范化 URL（如果没有协议，添加 https://）
        if homepage and not homepage.startswith(("http://", "https://")):
            homepage = f"https://{homepage}"
        if github and not github.startswith(("http://", "https://")):
            github = f"https://{github}"

        print(
            f"[DailyArxiv] 提取到 {len(unique_affiliations)} 个机构: {unique_affiliations}"
        )
        if unique_countries:
            print(
                f"[DailyArxiv] 提取到 {len(unique_countries)} 个国家: {unique_countries}"
            )
        if homepage:
            print(f"[DailyArxiv] Homepage: {homepage}")
        if github:
            print(f"[DailyArxiv] GitHub: {github}")

        # 标准化机构名称（将各种变体统一为标准缩写）
        try:
            import os
            import sys

            # 添加 tools 目录到 Python 路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            tools_dir = os.path.join(parent_dir, "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)

            from institution_normalizer import InstitutionNormalizer  # type: ignore

            # 创建标准化器实例（包含系统映射 + 用户自定义映射）
            # settings_file 参数传入的是配置文件路径（如果有）
            normalizer = InstitutionNormalizer(custom_mapping_file=settings_file)
            normalized_affiliations = normalizer.normalize_list(unique_affiliations)

            # 如果标准化后的机构列表与原列表不同，打印日志
            if normalized_affiliations != unique_affiliations:
                print(f"[DailyArxiv] 标准化前: {unique_affiliations}")
                print(f"[DailyArxiv] 标准化后: {normalized_affiliations}")

            unique_affiliations = normalized_affiliations
        except Exception as e:
            print(f"[DailyArxiv] 机构名称标准化失败（使用原始名称）: {e}")
            import traceback

            traceback.print_exc()

        return {
            "affiliations": unique_affiliations,
            "countries": unique_countries,
            "homepage": homepage,
            "github": github,
        }

    except Exception as e:
        print(f"[DailyArxiv] 提取机构信息失败: {e}")
        import traceback

        traceback.print_exc()
        return {"affiliations": [], "homepage": None, "github": None}


def extract_summary_and_keywords_with_llm(
    abstract: str,
    openai_base_url: str,
    openai_api_key: str,
    prompt: str = None,
) -> Dict[str, Any]:
    """
    使用 LLM 从论文摘要中提取总结和关键词

    Args:
        abstract: 论文摘要（英文）
        openai_base_url: OpenAI API 基础 URL
        openai_api_key: OpenAI API 密钥
        prompt: 自定义提示词（可选）

    Returns:
        包含 summary 和 keywords 的字典
    """
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        # 获取可用模型
        try:
            models = client.models.list()
            model = models.data[0].id if models.data else None
            if not model:
                print("[DailyArxiv] 无法获取模型列表")
                return {"summary": None, "keywords": []}
        except Exception as e:
            print(f"[DailyArxiv] 获取模型列表失败: {e}")
            return {"summary": None, "keywords": []}

        # 构造提示词（使用自定义或默认）
        system_prompt = prompt if prompt else SUMMARY_EXTRACTION_PROMPT
        # 如果 prompt 中包含 {keyword_list} 占位符，需要在使用前替换（但这里应该已经在调用前替换了）
        full_prompt = system_prompt + abstract
        messages = [{"role": "user", "content": full_prompt}]

        print(f"[DailyArxiv] 使用模型 {model} 提取摘要和关键词...")

        # 调用 LLM
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=800,
        )

        result_content = chat_completion.choices[0].message.content.strip()

        # 解析 JSON 结果
        import re

        # 尝试直接解析
        if result_content.startswith("{"):
            result = json.loads(result_content)
        else:
            # 尝试从文本中提取 JSON
            json_match = re.search(r"\{.*\}", result_content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                print(f"[DailyArxiv] 无法解析摘要和关键词: {result_content[:200]}")
                return {"summary": None, "keywords": []}

        summary = result.get("summary", "")
        keywords = result.get("keywords", [])

        # 确保 keywords 是列表
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]

        print(f"[DailyArxiv] 提取到关键词: {keywords}")
        return {"summary": summary, "keywords": keywords}

    except json.JSONDecodeError as e:
        print(f"[DailyArxiv] JSON 解析失败: {e}")
        return {"summary": None, "keywords": []}
    except Exception as e:
        print(f"[DailyArxiv] 提取摘要和关键词失败: {e}")
        import traceback

        traceback.print_exc()
        return {"summary": None, "keywords": []}


# 全局管理器实例
_manager_instance: Optional[DailyArxivManager] = None


def get_manager(base_dir: str, settings_file: str) -> DailyArxivManager:
    """获取全局管理器实例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = DailyArxivManager(base_dir, settings_file)
    return _manager_instance


# 兼容旧接口
class DailyArxivFetcher:
    """旧接口兼容层"""

    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
        self.client = arxiv.Client(
            page_size=50,
            delay_seconds=3.0,
            num_retries=3,
        )

    def fetch_latest_papers(
        self,
        category: str,
        max_results: int = 3,
        days_back: int = 7,
    ) -> List[ArxivPaper]:
        try:
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            papers = []
            for result in self.client.results(search):
                paper = ArxivPaper.from_arxiv_result(result, fetch_category=category)
                papers.append(paper)

            print(f"[DailyArxiv] 从 {category} 获取了 {len(papers)} 篇论文")
            return papers

        except Exception as e:
            print(f"[DailyArxiv] 获取 {category} 论文失败: {e}")
            return []


def get_fetcher(temp_dir: str) -> DailyArxivFetcher:
    """获取旧式 fetcher 实例"""
    return DailyArxivFetcher(temp_dir)
