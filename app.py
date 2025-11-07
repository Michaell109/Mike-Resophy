import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime

import PyPDF2
import requests
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max file size

# 配置文件存储路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "papers")
CATEGORIES_FILE = os.path.join(BASE_DIR, "categories.json")
READING_LIST_FILE = os.path.join(BASE_DIR, "reading_list.json")  # 待读列表文件
# 不再使用统一的papers_db.json文件，改为每个PDF一个JSON文件

# 确保必要的目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 初始化待读列表文件
if not os.path.exists(READING_LIST_FILE):
    with open(READING_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump({"papers": []}, f, ensure_ascii=False, indent=2)

# 翻译任务管理
translation_tasks = (
    {}
)  # {task_id: {paper_id, process, logs, status, start_time, log_lock}}
translation_tasks_lock = threading.Lock()  # 保护翻译任务字典

# AI解读任务管理
analysis_tasks = (
    {}
)  # {task_id: {paper_id, process, logs, status, start_time, log_lock, step}}
analysis_tasks_lock = threading.Lock()  # 保护解读任务字典


# 初始化分类数据
def init_categories():
    if not os.path.exists(CATEGORIES_FILE):
        default_categories = {
            "id": "root",
            "name": "Root",
            "children": [
                {
                    "id": "mllm",
                    "name": "MLLM",
                    "children": [
                        {"id": "finetuning", "name": "finetuning", "children": []},
                        {
                            "id": "post_training",
                            "name": "post_training",
                            "children": [],
                        },
                    ],
                }
            ],
        }
        with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(default_categories, f, ensure_ascii=False, indent=2)


# 论文数据现在直接存储在PDF文件旁边的JSON文件中，不需要初始化统一数据库


# 获取分类数据
def get_categories():
    with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# 获取分类及其子分类的PDF总数
def get_category_pdf_count(category_id):
    """获取分类下的PDF数量（包括子分类）"""

    def count_recursive(categories, target_id):
        total = 0

        # 获取分类路径
        category_path = get_category_path(categories, target_id)
        if category_path:
            # 计算当前分类的PDF数量
            papers = get_papers_in_category(category_path)
            total += len(papers)

        # 递归计算子分类的PDF数量
        category_node = find_category_node(categories, target_id)
        if category_node and "children" in category_node:
            for child in category_node["children"]:
                total += count_recursive(categories, child["id"])

        return total

    categories = get_categories()
    return count_recursive(categories, category_id)


# 为分类树添加PDF数量信息
def add_pdf_counts_to_categories(categories):
    def add_counts_recursive(node):
        # 为当前节点添加PDF数量
        node["pdf_count"] = get_category_pdf_count(node["id"])

        # 递归处理子节点
        if "children" in node:
            for child in node["children"]:
                add_counts_recursive(child)

    # 创建副本以避免修改原始数据
    categories_with_counts = json.loads(json.dumps(categories))
    add_counts_recursive(categories_with_counts)
    return categories_with_counts


def extract_pdf_metadata(file_path):
    """提取PDF元数据"""
    metadata = {
        "title": None,
        "authors": None,
        "affiliation": None,
        "year": None,
        "subject": None,
        "keywords": None,
        "abstract": None,
    }

    try:
        with open(file_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)

            # 获取PDF元数据
            if pdf_reader.metadata:
                # 标题
                if "/Title" in pdf_reader.metadata:
                    title = pdf_reader.metadata["/Title"]
                    if title and title.strip():
                        metadata["title"] = title.strip()

                # 作者
                if "/Author" in pdf_reader.metadata:
                    author = pdf_reader.metadata["/Author"]
                    if author and author.strip():
                        metadata["authors"] = author.strip()

                # 主题
                if "/Subject" in pdf_reader.metadata:
                    subject = pdf_reader.metadata["/Subject"]
                    if subject and subject.strip():
                        metadata["subject"] = subject.strip()

                # 关键词
                if "/Keywords" in pdf_reader.metadata:
                    keywords = pdf_reader.metadata["/Keywords"]
                    if keywords and keywords.strip():
                        metadata["keywords"] = keywords.strip()

                # 创建日期（尝试提取年份）
                if "/CreationDate" in pdf_reader.metadata:
                    creation_date = pdf_reader.metadata["/CreationDate"]
                    if creation_date:
                        # 尝试从创建日期提取年份
                        year_match = re.search(r"(\d{4})", str(creation_date))
                        if year_match:
                            year = int(year_match.group(1))
                            if 1900 <= year <= 2030:
                                metadata["year"] = str(year)

            # 从PDF内容中提取更多信息
            if len(pdf_reader.pages) > 0:
                try:
                    # 提取前几页的文本用于分析
                    full_text = ""
                    pages_to_extract = min(8, len(pdf_reader.pages))  # 提取前8页

                    for i in range(pages_to_extract):
                        page = pdf_reader.pages[i]
                        page_text = page.extract_text()
                        if page_text:
                            full_text += page_text + "\n"

                    if full_text:
                        # 预处理文本：去连字符换行、标准化空白
                        full_text = preprocess_pdf_text(full_text)
                        # 提取标题（如果元数据中没有）
                        if not metadata["title"]:
                            metadata["title"] = extract_title_from_text(full_text)

                        # 提取作者（如果元数据中没有）
                        if not metadata["authors"]:
                            metadata["authors"] = extract_authors_from_text(full_text)

                        # 提取单位
                        metadata["affiliation"] = extract_affiliation_from_text(
                            full_text
                        )

                        # 提取摘要
                        metadata["abstract"] = extract_abstract_from_text(full_text)

                except Exception as e:
                    print(f"提取PDF文本内容失败: {e}")

    except Exception as e:
        print(f"提取PDF元数据失败: {e}")

    return metadata


def preprocess_pdf_text(text: str) -> str:
    """对从PDF提取的原始文本进行规范化，提升后续解析的稳定性。"""
    if not text:
        return ""
    t = text
    # 去除因换行导致的连字符断词（e.g., "infor-\nmation" -> "information"）
    t = re.sub(r"-\s*\n\s*", "", t)
    # 将硬换行标准化为单个换行
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # 某些PDF提取没有换行处加入软换行，这里尽量保留段落结构
    # 合并多余空白
    t = re.sub(r"[\t\f]+", " ", t)
    t = re.sub(r"\u00A0", " ", t)  # 不间断空格
    # 保留段落分隔：将两个以上换行压缩为两个
    t = re.sub(r"\n{3,}", "\n\n", t)
    # 去除每行行首尾多余空白
    t = "\n".join(line.strip() for line in t.split("\n"))
    return t


def extract_title_from_text(text):
    """从文本中提取标题"""
    lines = text.strip().split("\n")

    for line in lines[:10]:  # 检查前10行
        line = line.strip()
        if len(line) > 10 and len(line) < 300:
            # 标题通常不全是大写，包含字母，不包含常见的页眉页脚内容
            if (
                not line.isupper()
                and re.search(r"[a-zA-Z]", line)
                and not re.search(r"^\d+$", line)  # 不是纯数字
                and not re.search(r"^(page|vol|volume|issue|doi|arxiv)", line.lower())
                and not re.search(r"@|\.com|\.org", line.lower())
            ):  # 不包含邮箱或网址
                return line

    return None


def extract_authors_from_text(text):
    """从文本中提取作者"""
    lines = text.strip().split("\n")

    # 常见的作者模式
    author_patterns = [
        r"^([A-Z][a-z]+ [A-Z][a-z]+(?:, [A-Z][a-z]+ [A-Z][a-z]+)*)",  # John Smith, Jane Doe
        r"^([A-Z]\. [A-Z][a-z]+(?:, [A-Z]\. [A-Z][a-z]+)*)",  # J. Smith, J. Doe
        r"^([A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+(?:, [A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+)*)",  # John A. Smith
    ]

    for i, line in enumerate(lines[:15]):  # 检查前15行
        line = line.strip()
        if len(line) > 5 and len(line) < 200:
            for pattern in author_patterns:
                match = re.match(pattern, line)
                if match:
                    authors = match.group(1)
                    # 验证是否看起来像作者名单
                    if re.search(r"[A-Z][a-z]+", authors) and not re.search(
                        r"\d", authors
                    ):
                        return authors

    return None


def extract_affiliation_from_text(text):
    """从文本中提取单位/机构"""
    lines = text.strip().split("\n")

    # 常见的机构关键词
    institution_keywords = [
        r"university",
        r"college",
        r"institute",
        r"laboratory",
        r"lab",
        r"department",
        r"school",
        r"center",
        r"centre",
        r"research",
        r"academy",
        r"corporation",
        r"company",
        r"inc\.",
        r"ltd\.",
        r"google",
        r"microsoft",
        r"openai",
        r"anthropic",
        r"meta",
        r"stanford",
        r"mit",
        r"harvard",
        r"berkeley",
        r"cambridge",
    ]

    affiliations = []

    for i, line in enumerate(lines[:20]):  # 检查前20行
        line = line.strip()
        if len(line) > 10 and len(line) < 300:
            # 检查是否包含机构关键词
            for keyword in institution_keywords:
                if re.search(keyword, line, re.IGNORECASE):
                    # 过滤掉一些明显不是机构的行
                    if not re.search(
                        r"^(abstract|introduction|keywords|references)", line.lower()
                    ):
                        affiliations.append(line)
                        break

    # 去重并返回前3个最可能的机构
    unique_affiliations = []
    for aff in affiliations:
        if aff not in unique_affiliations:
            unique_affiliations.append(aff)
        if len(unique_affiliations) >= 3:
            break

    return "; ".join(unique_affiliations) if unique_affiliations else None


def extract_abstract_from_text(text):
    """从文本中提取摘要（多行、直到下一章节/关键词等停止标记）"""
    # 归一化换行
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # 1) 尝试直接用更强的正则从 Abstract/摘要 开始抓取到明显的停止标记
    stop_markers = (
        r"keywords|index\s*terms|subject[s]?|introduction|background|materials\s+and\s+methods|methods|results|conclusions|references|acknowledg(e)?ments|1\.|i\.|ii\.|iii\."
        r"|关键词|引言|背景|方法|結果|结论|参考文献"
    )
    start_markers = r"abstract|summary|摘要|概要"
    # 允许起始处前后有少量空白/标点，兼容 "Abstract."、"ABSTRACT:" 等
    pattern = rf"(?is)\b(?:{start_markers})\b\s*[:\.\-]?\s*(.+?)(?=\n\s*(?:{stop_markers})\b|\n\n\s*[A-Z][A-Za-z ]+\b|\Z)"
    m = re.search(pattern, normalized)
    if m:
        abstract = m.group(1).strip()
        # 将多行整合为单行，并保留句子间空格
        abstract = re.sub(r"\s+", " ", abstract)
        if 50 <= len(abstract) <= 5000 and re.search(r"[a-z]", abstract, re.I):
            return abstract

    # 2) 处理常见格式：Abstract 独立一行，下一行开始为摘要，多行直到停止标记
    lines = normalized.split("\n")
    abstract_started = False
    buffer = []
    for line in lines:
        line_stripped = line.strip()
        if not abstract_started:
            if re.match(
                r"(?i)^(abstract|summary|摘要|概要)\b\s*[:\-\.]?\s*$", line_stripped
            ) or re.match(r"(?i)^(abstract|summary|摘要|概要)\b\s*[:\-\.]?", line_stripped):
                # 如果这一行有冒号后直接有内容，取冒号后的内容作为第一行
                after = re.sub(
                    r"(?i)^(abstract|summary|摘要|概要)\b\s*[:\-\.]?\s*",
                    "",
                    line_stripped,
                )
                if after:
                    buffer.append(after)
                abstract_started = True
            continue
        else:
            # 到达停止标记则终止
            if re.match(rf"(?i)^\s*(?:{stop_markers})\b", line_stripped):
                break
            # 空行可能是摘要结束，但如果尚未足够长则继续容忍一次
            buffer.append(line)

    candidate = re.sub(r"\s+", " ", " ".join(buffer)).strip()
    if 50 <= len(candidate) <= 5000 and re.search(r"[a-z]", candidate, re.I):
        return candidate

    # 3) 回退策略：取第一段较长、像摘要的段落
    paragraphs = re.split(r"\n\s*\n", normalized)
    for paragraph in paragraphs[:8]:
        p = re.sub(r"\s+", " ", paragraph.strip())
        if (
            120 <= len(p) <= 5000
            and not re.match(
                r"(?i)^(keywords|index\s*terms|introduction|references|acknowledg(e)?ments|参考文献|引言|关键词)",
                p,
            )
            and p.count(".") >= 2
        ):
            return p

    return None


def clean_filename(text):
    """清理文件名，移除不合法字符"""
    if not text:
        return None

    # 移除或替换不合法的文件名字符
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    # 移除多余的空格
    text = re.sub(r"\s+", " ", text).strip()
    # 限制长度
    if len(text) > 100:
        text = text[:100] + "..."

    return text if text else None


def get_paper_json_path(pdf_path):
    """根据PDF路径获取对应的JSON文件路径"""
    return os.path.splitext(pdf_path)[0] + ".json"


def save_paper_metadata(pdf_path, paper_data):
    """保存论文元数据到JSON文件"""
    json_path = get_paper_json_path(pdf_path)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(paper_data, f, ensure_ascii=False, indent=2)
        print(f"已保存论文元数据: {json_path}")
    except Exception as e:
        print(f"保存论文元数据失败: {e}")


def load_paper_metadata(pdf_path):
    """从JSON文件加载论文元数据"""
    json_path = get_paper_json_path(pdf_path)
    try:
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"加载论文元数据失败: {e}")
    return None


# ==================== 待读列表管理 ====================
def get_reading_list():
    """获取待读列表"""
    try:
        if os.path.exists(READING_LIST_FILE):
            with open(READING_LIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("papers", [])
    except Exception as e:
        print(f"读取待读列表失败: {e}")
    return []


def save_reading_list(paper_ids):
    """保存待读列表"""
    try:
        with open(READING_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"papers": paper_ids}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存待读列表失败: {e}")


def add_to_reading_list(paper_id):
    """添加论文到待读列表"""
    paper_ids = get_reading_list()
    if paper_id not in paper_ids:
        paper_ids.append(paper_id)
        save_reading_list(paper_ids)


def remove_from_reading_list(paper_id):
    """从待读列表移除论文"""
    paper_ids = get_reading_list()
    if paper_id in paper_ids:
        paper_ids.remove(paper_id)
        save_reading_list(paper_ids)


def is_in_reading_list(paper_id):
    """检查论文是否在待读列表中"""
    return paper_id in get_reading_list()


def get_paper_total_time(paper_id):
    """获取论文的总阅读时间（阅读PDF时间 + 阅读AI解读时间）"""
    categories = get_categories()

    def search_paper_recursive(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    # 获取阅读时间字段（默认为0）
                    read_time = paper.get("read_time", 0)  # 阅读PDF时间（秒）
                    analysis_view_time = paper.get(
                        "analysis_view_time", 0
                    )  # 阅读AI解读时间（秒）
                    return read_time + analysis_view_time

        if "children" in node:
            for child in node["children"]:
                result = search_paper_recursive(child)
                if result is not None:
                    return result
        return None

    for child in categories.get("children", []):
        result = search_paper_recursive(child)
        if result is not None:
            return result

    return 0


def extract_arxiv_id_from_url(url: str) -> str | None:
    """从 arXiv URL 中提取 arXiv ID"""
    # 支持的格式：
    # https://arxiv.org/pdf/2511.03725.pdf
    # https://arxiv.org/pdf/2511.03725v1.pdf
    # https://arxiv.org/abs/2511.03725
    # https://arxiv.org/abs/2511.03725v1
    # arxiv.org/pdf/2511.03725
    import re

    patterns = [
        r"arxiv\.org/pdf/([\d.]+(?:v\d+)?)",
        r"arxiv\.org/abs/([\d.]+(?:v\d+)?)",
        r"^([\d.]+(?:v\d+)?)$",  # 直接是 arXiv ID
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            # 移除版本号（如果存在）用于API调用
            if "v" in arxiv_id:
                arxiv_id = arxiv_id.split("v")[0]
            return arxiv_id

    return None


def download_arxiv_pdf(arxiv_id: str) -> tuple[bytes, str] | None:
    """从 arXiv 下载 PDF 文件
    返回: (pdf_content, filename) 或 None
    """
    # arXiv PDF URL 格式: https://arxiv.org/pdf/{id}.pdf
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    try:
        print(f"正在从 arXiv 下载 PDF: {pdf_url}")
        response = requests.get(pdf_url, timeout=30, stream=True)
        response.raise_for_status()

        # 检查 Content-Type
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower():
            print(f"警告: Content-Type 不是 PDF: {content_type}")

        # 读取PDF内容
        pdf_content = response.content

        # 生成文件名
        filename = f"{arxiv_id}.pdf"

        print(f"成功下载 PDF, 大小: {len(pdf_content)} bytes")
        return (pdf_content, filename)

    except requests.exceptions.RequestException as e:
        print(f"下载 arXiv PDF 失败: {e}")
        return None


def fetch_arxiv_abstract(arxiv_id: str) -> dict | None:
    """从 arXiv API 获取摘要和发布时间。返回包含 abstract 和 published_date 的字典，失败返回 None。"""
    try:
        url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        from xml.etree import ElementTree as ET

        tree = ET.fromstring(resp.content)
        entry = tree.find("{http://www.w3.org/2005/Atom}entry")
        if entry is None:
            return None

        result = {}

        # 获取标题
        title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
        if title_elem is not None and title_elem.text:
            result["title"] = title_elem.text.strip()

        # 获取作者
        authors = []
        for author in entry.findall("{http://www.w3.org/2005/Atom}author"):
            name_elem = author.find("{http://www.w3.org/2005/Atom}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        if authors:
            result["authors"] = ", ".join(authors)

        # 获取摘要
        summary = entry.find("{http://www.w3.org/2005/Atom}summary")
        if summary is not None and summary.text:
            abstract = summary.text.strip()
            abstract = re.sub(r"\s+", " ", abstract)
            result["abstract"] = abstract

        # 获取发布时间
        published = entry.find("{http://www.w3.org/2005/Atom}published")
        if published is not None and published.text:
            # arXiv API 返回的时间格式类似: 2023-01-15T18:30:00Z 或 2023-01-15T18:30:00.123Z
            try:
                from datetime import datetime

                published_date_str = published.text.strip().rstrip("Z")
                # 尝试解析不同格式
                if "." in published_date_str:
                    # 包含毫秒: 2023-01-15T18:30:00.123
                    dt = datetime.strptime(published_date_str, "%Y-%m-%dT%H:%M:%S.%f")
                else:
                    # 不包含毫秒: 2023-01-15T18:30:00
                    dt = datetime.strptime(published_date_str, "%Y-%m-%dT%H:%M:%S")
                result["published_date"] = dt.isoformat()
            except Exception as e:
                print(
                    f"解析 arXiv 发布时间失败: {e}, 原始字符串: {published.text.strip() if published is not None else 'None'}"
                )

        return result if result else None
    except Exception as e:
        print(f"获取 arXiv 信息失败: {e}")
        return None


def delete_paper_files(pdf_path):
    """删除PDF文件、对应的JSON文件、中文翻译PDF，以及AI解读和PDF2MD的输出"""
    json_path = get_paper_json_path(pdf_path)

    # 删除PDF文件
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
        print(f"已删除PDF文件: {pdf_path}")

    # 删除JSON文件
    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"已删除JSON文件: {json_path}")

    # 删除中文翻译PDF（.zh.dual.pdf / .zh.mono.pdf）
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_dir = os.path.dirname(pdf_path)
    zh_dual = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
    zh_mono = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")
    for f in (zh_dual, zh_mono):
        try:
            if os.path.exists(f):
                os.remove(f)
                print(f"已删除中文翻译PDF: {f}")
        except Exception as e:
            print(f"删除中文翻译PDF失败: {f}, {e}")

    # 删除outputs目录（包含AI解读和PDF2MD的输出）
    outputs_dir = os.path.join(pdf_dir, "outputs")
    if os.path.exists(outputs_dir):
        # 查找与当前PDF对应的outputs子目录
        for item in os.listdir(outputs_dir):
            item_path = os.path.join(outputs_dir, item)
            # 检查是否是当前PDF的输出目录（目录名通常包含PDF文件名）
            if os.path.isdir(item_path) and base_name in item:
                shutil.rmtree(item_path)
                print(f"已删除AI解读输出目录: {item_path}")

        # 如果outputs目录为空，也删除它
        try:
            if not os.listdir(outputs_dir):
                os.rmdir(outputs_dir)
                print(f"已删除空的outputs目录: {outputs_dir}")
        except:
            pass


def scan_papers_in_directory(directory_path):
    """扫描目录中的所有PDF文件并加载其元数据"""
    papers = []
    if not os.path.exists(directory_path):
        return papers

    for filename in os.listdir(directory_path):
        if filename.lower().endswith(".pdf"):
            # 跳过翻译生成的PDF文件（.zh.dual.pdf 和 .zh.mono.pdf）
            if filename.endswith(".zh.dual.pdf") or filename.endswith(".zh.mono.pdf"):
                continue

            pdf_path = os.path.join(directory_path, filename)
            paper_data = load_paper_metadata(pdf_path)

            if paper_data:
                # 确保文件路径是最新的
                paper_data["file_path"] = pdf_path
                paper_data["filename"] = filename
                # 确保 starred 字段存在（向后兼容）
                if "starred" not in paper_data:
                    paper_data["starred"] = False
                # 检查是否有中文版本
                if "has_chinese_version" not in paper_data:
                    base_name = os.path.splitext(filename)[0]
                    dual_file = os.path.join(directory_path, f"{base_name}.zh.dual.pdf")
                    if os.path.exists(dual_file):
                        paper_data["has_chinese_version"] = True
                        paper_data["chinese_version_path"] = dual_file
                    else:
                        paper_data["has_chinese_version"] = False
                # 确保 use_chinese_version 字段存在（默认 False）
                if "use_chinese_version" not in paper_data:
                    paper_data["use_chinese_version"] = False
                # 检查是否有解读结果（只检查当前PDF对应的outputs目录）
                if "has_analysis_result" not in paper_data:
                    # 检查是否存在解读结果文件
                    pdf_dir = os.path.dirname(pdf_path)
                    base_name = os.path.splitext(filename)[0]
                    outputs_dir = os.path.join(pdf_dir, "outputs")
                    has_result = False
                    if os.path.exists(outputs_dir):
                        # 只检查与当前PDF文件名匹配的outputs子目录
                        for item in os.listdir(outputs_dir):
                            item_path = os.path.join(outputs_dir, item)
                            # 确保目录名包含当前PDF的文件名（去掉扩展名）
                            if os.path.isdir(item_path) and base_name in item:
                                vlm_dir = os.path.join(item_path, "vlm")
                                if os.path.exists(vlm_dir):
                                    result_file = os.path.join(vlm_dir, "result.md")
                                    if os.path.exists(result_file):
                                        has_result = True
                                        paper_data["has_analysis_result"] = True
                                        paper_data["analysis_result_path"] = result_file
                                        break
                    if not has_result:
                        paper_data["has_analysis_result"] = False
                papers.append(paper_data)
            else:
                # 如果没有JSON文件，创建基本的论文数据
                paper_data = {
                    "id": str(uuid.uuid4()),
                    "filename": filename,
                    "original_filename": filename,
                    "file_path": pdf_path,
                    "upload_date": datetime.fromtimestamp(
                        os.path.getctime(pdf_path)
                    ).isoformat(),
                    "title": os.path.splitext(filename)[0],
                    "authors": "",
                    "year": "",
                    "journal": "",
                    "abstract": "",
                    "keywords": "",
                    "subject": "",
                    "notes": "",
                    "starred": False,
                }
                # 保存基本数据到JSON文件
                save_paper_metadata(pdf_path, paper_data)
                papers.append(paper_data)

    return papers


def get_papers_in_category(category_path):
    """获取指定分类路径下的所有论文"""
    if not category_path:
        return []

    # 构建目录路径
    directory_path = os.path.join(UPLOAD_FOLDER, *category_path[1:])  # 跳过Root
    return scan_papers_in_directory(directory_path)


# 保存分类数据
def save_categories(categories):
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(categories, f, ensure_ascii=False, indent=2)


# 论文数据管理函数已移至上方的新实现


# 根据分类路径创建文件夹
def create_category_folder(category_path):
    folder_path = os.path.join(UPLOAD_FOLDER, *category_path)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


# 查找分类节点
def find_category_node(categories, category_id):
    if categories["id"] == category_id:
        return categories

    for child in categories.get("children", []):
        result = find_category_node(child, category_id)
        if result:
            return result
    return None


# 获取分类路径
def get_category_path(categories, category_id, path=[]):
    if categories["id"] == category_id:
        return path + [categories["name"]]

    for child in categories.get("children", []):
        result = get_category_path(child, category_id, path + [categories["name"]])
        if result:
            return result
    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/categories")
def api_categories():
    categories = get_categories()
    categories_with_counts = add_pdf_counts_to_categories(categories)
    return jsonify(categories_with_counts)


@app.route("/api/categories", methods=["POST"])
def api_add_category():
    data = request.json
    parent_id = data.get("parent_id")
    name = data.get("name")

    categories = get_categories()
    parent_node = find_category_node(categories, parent_id)

    if parent_node:
        new_category = {"id": str(uuid.uuid4()), "name": name, "children": []}
        parent_node["children"].append(new_category)
        save_categories(categories)
        return jsonify({"success": True, "category": new_category})

    return jsonify({"success": False, "error": "Parent category not found"})


@app.route("/api/categories/<category_id>", methods=["PUT"])
def api_rename_category(category_id):
    data = request.json
    new_name = data.get("name")

    categories = get_categories()
    category_node = find_category_node(categories, category_id)

    if category_node:
        old_name = category_node["name"]
        category_node["name"] = new_name
        save_categories(categories)
        return jsonify({"success": True})

    return jsonify({"success": False, "error": "Category not found"})


@app.route("/api/categories/<category_id>", methods=["DELETE"])
def api_delete_category(category_id):
    categories = get_categories()

    # 查找并删除分类
    def delete_category_recursive(node, target_id):
        if "children" in node:
            for i, child in enumerate(node["children"]):
                if child["id"] == target_id:
                    # 删除分类及其文件夹（包括PDF和JSON文件）
                    category_path = get_category_path(categories, target_id)
                    if category_path and len(category_path) > 1:  # 跳过 Root
                        folder_path = os.path.join(UPLOAD_FOLDER, *category_path[1:])
                        if os.path.exists(folder_path):
                            shutil.rmtree(folder_path)
                            print(f"已删除分类文件夹: {folder_path}")

                    # 从分类树中删除
                    del node["children"][i]
                    return True
                elif delete_category_recursive(child, target_id):
                    return True
        return False

    if delete_category_recursive(categories, category_id):
        save_categories(categories)
        return jsonify({"success": True})

    return jsonify({"success": False, "error": "Category not found"})


@app.route("/api/papers/<category_id>")
def api_papers(category_id):
    """获取指定分类下的所有论文"""
    categories = get_categories()
    category_path = get_category_path(categories, category_id)

    if not category_path:
        return jsonify({"error": "Category not found"}), 404

    papers = get_papers_in_category(category_path)
    return jsonify(papers)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file provided"})

    file = request.files["file"]
    category_id = request.form.get("category_id")

    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected"})

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "Only PDF files are allowed"})

    # 获取分类路径
    categories = get_categories()
    category_path = get_category_path(categories, category_id)

    if not category_path:
        return jsonify({"success": False, "error": "Category not found"})

    # 创建目录并保存文件
    category_folder = create_category_folder(category_path[1:])  # 跳过 Root
    filename = secure_filename(file.filename)
    file_path = os.path.join(category_folder, filename)

    # 如果文件已存在，添加数字后缀
    counter = 1
    original_filename = filename
    while os.path.exists(file_path):
        name, ext = os.path.splitext(original_filename)
        filename = f"{name}_{counter}{ext}"
        file_path = os.path.join(category_folder, filename)
        counter += 1

    file.save(file_path)

    # 优先使用前端上传的元数据（由 PDF.js 提取）
    print(f"正在提取PDF元数据: {file_path}")
    metadata = {}
    client_metadata_raw = request.form.get("metadata")
    if client_metadata_raw:
        try:
            metadata = json.loads(client_metadata_raw)
        except Exception as e:
            print(f"解析前端metadata失败，将回退服务端提取: {e}")
            metadata = {}
    # 如果前端未提供或不足，再回退服务端提取补全（但不使用服务端摘要）
    server_md = extract_pdf_metadata(file_path)
    for k, v in server_md.items():
        if k == "abstract":
            continue
        if not metadata.get(k):
            metadata[k] = v

    # 如果前端提供 arxiv_id 且没有摘要，尝试从 arXiv 获取摘要和发布时间
    arxiv_id = (metadata.get("arxiv_id") or "").strip()
    arxiv_published_date = None
    if arxiv_id:
        arxiv_info = fetch_arxiv_abstract(arxiv_id)
        if arxiv_info:
            if "abstract" in arxiv_info:
                metadata["abstract"] = arxiv_info["abstract"]
            if "published_date" in arxiv_info:
                arxiv_published_date = arxiv_info["published_date"]
        else:
            # 如果 arXiv 未取到，则保持为空（不使用本地解析）
            metadata["abstract"] = metadata.get("abstract") or ""

    # 如果提取到了标题，尝试重命名文件
    new_filename = filename
    if metadata.get("title"):
        clean_title = clean_filename(metadata["title"])
        if clean_title:
            # 生成新的文件名
            new_filename = f"{clean_title}.pdf"
            new_file_path = os.path.join(category_folder, new_filename)

            # 如果新文件名已存在，添加数字后缀
            counter = 1
            original_new_filename = new_filename
            while os.path.exists(new_file_path):
                name, ext = os.path.splitext(original_new_filename)
                new_filename = f"{name}_{counter}{ext}"
                new_file_path = os.path.join(category_folder, new_filename)
                counter += 1

            # 重命名文件
            try:
                os.rename(file_path, new_file_path)
                file_path = new_file_path
                filename = new_filename
                print(f"文件已重命名为: {filename}")
            except Exception as e:
                print(f"重命名文件失败: {e}")

    # 创建论文记录
    paper_info = {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "original_filename": file.filename,
        "file_path": file_path,
        "upload_date": datetime.now().isoformat(),
        "title": metadata.get("title") or os.path.splitext(file.filename)[0],
        "authors": metadata.get("authors") or "",
        "arxiv_id": arxiv_id,
        "arxiv_published_date": arxiv_published_date,  # arXiv 发布时间
        "affiliation": metadata.get("affiliation") or "",
        "year": metadata.get("year") or "",
        "journal": "",
        "abstract": metadata.get("abstract") or "",
        "keywords": metadata.get("keywords") or "",
        "subject": metadata.get("subject") or "",
        "notes": "",
        "starred": False,  # 点赞状态
        "read_time": 0,  # 阅读PDF时间（秒，一次性，取最大值）
        "analysis_view_time": 0,  # 阅读AI解读时间（秒，一次性，取最大值）
        "translation_time": 0,  # 翻译任务耗时（秒）
        "analysis_time": 0,  # 解读任务耗时（秒）
    }

    # 保存论文元数据到JSON文件
    save_paper_metadata(file_path, paper_info)

    # 自动添加到待读列表
    add_to_reading_list(paper_info["id"])

    return jsonify({"success": True, "paper": paper_info})


@app.route("/api/upload/arxiv", methods=["POST"])
def api_upload_arxiv():
    """从 arXiv URL 下载并导入 PDF"""
    try:
        data = request.json
        arxiv_url = data.get("arxiv_url", "").strip()
        category_id = data.get("category_id")

        if not arxiv_url:
            return jsonify({"success": False, "error": "未提供 arXiv URL"}), 400

        if not category_id:
            return jsonify({"success": False, "error": "未选择分类"}), 400

        # 提取 arXiv ID
        arxiv_id = extract_arxiv_id_from_url(arxiv_url)
        if not arxiv_id:
            return (
                jsonify({"success": False, "error": "无法从 URL 中提取 arXiv ID"}),
                400,
            )

        print(f"提取的 arXiv ID: {arxiv_id}")

        # 下载 PDF
        result = download_arxiv_pdf(arxiv_id)
        if not result:
            return jsonify({"success": False, "error": "下载 PDF 失败"}), 500

        pdf_content, filename = result

        # 获取分类路径
        categories = get_categories()
        category_path = get_category_path(categories, category_id)

        if not category_path:
            return jsonify({"success": False, "error": "分类未找到"}), 404

        # 创建目录并保存文件
        category_folder = create_category_folder(category_path[1:])  # 跳过 Root
        file_path = os.path.join(category_folder, filename)

        # 如果文件已存在，添加数字后缀
        counter = 1
        original_filename = filename
        while os.path.exists(file_path):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            file_path = os.path.join(category_folder, filename)
            counter += 1

        # 保存PDF文件
        with open(file_path, "wb") as f:
            f.write(pdf_content)

        print(f"PDF 已保存到: {file_path}")

        # 从 arXiv API 获取元数据
        metadata = {}
        arxiv_info = fetch_arxiv_abstract(arxiv_id)
        if arxiv_info:
            # 优先使用 arXiv API 的元数据（标题、作者、摘要、发布时间）
            if "title" in arxiv_info:
                metadata["title"] = arxiv_info["title"]
            if "authors" in arxiv_info:
                metadata["authors"] = arxiv_info["authors"]
            if "abstract" in arxiv_info:
                metadata["abstract"] = arxiv_info["abstract"]
            if "published_date" in arxiv_info:
                metadata["arxiv_published_date"] = arxiv_info["published_date"]

        # 设置 arXiv ID
        metadata["arxiv_id"] = arxiv_id

        # 尝试从PDF提取更多元数据（如果 arXiv API 没有提供）
        server_md = extract_pdf_metadata(file_path)
        for k, v in server_md.items():
            if k == "abstract":
                continue  # 摘要优先使用 arXiv API 的
            if not metadata.get(k):
                metadata[k] = v

        # 如果提取到了标题，尝试重命名文件
        new_filename = filename
        if metadata.get("title"):
            clean_title = clean_filename(metadata["title"])
            if clean_title:
                new_filename = f"{clean_title}.pdf"
                new_file_path = os.path.join(category_folder, new_filename)

                counter = 1
                original_new_filename = new_filename
                while os.path.exists(new_file_path):
                    name, ext = os.path.splitext(original_new_filename)
                    new_filename = f"{name}_{counter}{ext}"
                    new_file_path = os.path.join(category_folder, new_filename)
                    counter += 1

                try:
                    os.rename(file_path, new_file_path)
                    file_path = new_file_path
                    filename = new_filename
                    print(f"文件已重命名为: {filename}")
                except Exception as e:
                    print(f"重命名文件失败: {e}")

        # 创建论文记录
        paper_info = {
            "id": str(uuid.uuid4()),
            "filename": filename,
            "original_filename": filename,
            "file_path": file_path,
            "upload_date": datetime.now().isoformat(),
            "title": metadata.get("title") or arxiv_id,
            "authors": metadata.get("authors") or "",
            "arxiv_id": arxiv_id,
            "arxiv_published_date": metadata.get("arxiv_published_date"),
            "affiliation": metadata.get("affiliation") or "",
            "year": metadata.get("year") or "",
            "journal": "",
            "abstract": metadata.get("abstract") or "",
            "keywords": metadata.get("keywords") or "",
            "subject": metadata.get("subject") or "",
            "notes": "",
            "starred": False,
            "read_time": 0,  # 阅读时间（秒）
            "translation_time": 0,  # 翻译时间（秒）
            "analysis_time": 0,  # 解读时间（秒）
        }

        # 保存论文元数据到JSON文件
        save_paper_metadata(file_path, paper_info)

        # 自动添加到待读列表
        add_to_reading_list(paper_info["id"])

        return jsonify({"success": True, "paper": paper_info})

    except Exception as e:
        print(f"从 arXiv 导入失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": f"导入失败: {str(e)}"}), 500


@app.route("/api/paper/<paper_id>")
def api_paper_info(paper_id):
    """获取单个论文的详细信息"""
    # 遍历所有分类目录查找论文
    categories = get_categories()

    def search_paper_recursive(node):
        # 获取当前分类的路径
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    return paper

        # 递归搜索子分类
        if "children" in node:
            for child in node["children"]:
                result = search_paper_recursive(child)
                if result:
                    return result

        return None

    # 从根节点开始搜索
    for child in categories.get("children", []):
        paper = search_paper_recursive(child)
        if paper:
            return jsonify(paper)

    return jsonify({"error": "Paper not found"}), 404


@app.route("/api/search")
def api_search():
    """搜索 title/authors/abstract。支持全局或限定某个分类。
    参数：
      - q: 关键字
      - category_id: 可选，若提供则仅搜索该分类（含子目录）
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    q_lower = q.lower()

    # 解析可选分类范围
    base_search_dir = UPLOAD_FOLDER
    category_id = (request.args.get("category_id") or "").strip()
    if category_id:
        cats = get_categories()
        path = get_category_path(cats, category_id)
        if path and len(path) > 1:
            base_search_dir = os.path.join(UPLOAD_FOLDER, *path[1:])

    results = []
    # 扫描目录
    for root, dirs, files in os.walk(base_search_dir):
        for fname in files:
            if not fname.lower().endswith(".json"):
                continue
            json_path = os.path.join(root, fname)
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            pid = data.get("id")
            title = data.get("title") or data.get("filename") or ""
            authors = data.get("authors") or ""
            abstract = data.get("abstract") or ""

            matched_fields = []
            if q_lower in (title or "").lower():
                matched_fields.append("title")
            if q_lower in (authors or "").lower():
                matched_fields.append("authors")
            if q_lower in (abstract or "").lower():
                matched_fields.append("abstract")

            if matched_fields:
                results.append(
                    {
                        "id": pid,
                        "title": title,
                        "authors": authors,
                        "abstract": abstract,
                        "filename": data.get("filename"),
                        "matched_fields": matched_fields,
                    }
                )

    # 可按匹配字段优先级与时间排序（简化为匹配数降序）
    results.sort(key=lambda r: (-len(r["matched_fields"]), r.get("title") or ""))
    return jsonify({"results": results})


@app.route("/api/paper/<paper_id>/move", methods=["PUT"])
def api_move_paper(paper_id):
    data = request.json
    target_category_id = data.get("target_category_id")

    if not target_category_id:
        return (
            jsonify({"success": False, "error": "Target category ID is required"}),
            400,
        )

    categories = get_categories()

    # 查找论文
    def search_paper_for_move(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    return paper, node["id"], category_path

        if "children" in node:
            for child in node["children"]:
                result = search_paper_for_move(child)
                if result:
                    return result

        return None

    # 查找论文
    paper_result = None
    for child in categories.get("children", []):
        paper_result = search_paper_for_move(child)
        if paper_result:
            break

    if not paper_result:
        return jsonify({"success": False, "error": "Paper not found"}), 404

    paper_data, source_category_id, source_path = paper_result

    # 检查目标分类是否存在
    target_category = find_category_node(categories, target_category_id)
    if not target_category:
        return jsonify({"success": False, "error": "Target category not found"}), 404

    # 获取目标路径
    target_path = get_category_path(categories, target_category_id)
    if not target_path:
        return (
            jsonify({"success": False, "error": "Target category path not found"}),
            404,
        )

    # 移动文件到新的目录结构
    try:
        # 构建文件路径
        target_folder = (
            os.path.join(UPLOAD_FOLDER, *target_path[1:])
            if len(target_path) > 1
            else UPLOAD_FOLDER
        )

        source_file_path = paper_data["file_path"]
        source_json_path = get_paper_json_path(source_file_path)

        # 确保目标目录存在
        os.makedirs(target_folder, exist_ok=True)

        # 生成目标文件路径
        target_file_path = os.path.join(target_folder, paper_data["filename"])
        target_json_path = get_paper_json_path(target_file_path)

        # 如果目标文件已存在，重命名
        counter = 1
        original_filename = paper_data["filename"]
        while os.path.exists(target_file_path):
            name, ext = os.path.splitext(original_filename)
            new_filename = f"{name}_{counter}{ext}"
            target_file_path = os.path.join(target_folder, new_filename)
            target_json_path = get_paper_json_path(target_file_path)
            counter += 1

        # 移动PDF文件
        if os.path.exists(source_file_path):
            shutil.move(source_file_path, target_file_path)
            print(f"已移动PDF文件: {source_file_path} -> {target_file_path}")

        # 移动JSON文件
        if os.path.exists(source_json_path):
            shutil.move(source_json_path, target_json_path)
            print(f"已移动JSON文件: {source_json_path} -> {target_json_path}")

        # 更新论文数据中的文件路径和文件名
        paper_data["filename"] = os.path.basename(target_file_path)
        paper_data["file_path"] = target_file_path

        # 保存更新后的论文数据到新的JSON文件
        save_paper_metadata(target_file_path, paper_data)

        return jsonify(
            {
                "success": True,
                "paper": paper_data,
                "source_category": source_category_id,
                "target_category": target_category_id,
            }
        )

    except Exception as e:
        print(f"移动论文失败: {str(e)}")
        return (
            jsonify({"success": False, "error": f"Failed to move file: {str(e)}"}),
            500,
        )


@app.route("/api/paper/<paper_id>/file")
def api_get_paper_file(paper_id):
    """获取PDF文件"""
    categories = get_categories()

    def search_paper_file(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    file_path = paper.get("file_path")
                    if not file_path:
                        print(f"论文 {paper_id} 没有 file_path 字段")
                        # 尝试从filename和category_path重建路径
                        filename = paper.get("filename")
                        if filename and category_path:
                            category_folder = create_category_folder(category_path[1:])
                            file_path = os.path.join(category_folder, filename)
                            print(f"尝试重建路径: {file_path}")

                    if file_path:
                        # 确保是绝对路径
                        if not os.path.isabs(file_path):
                            file_path = os.path.abspath(file_path)

                        print(
                            f"查找PDF文件: {file_path}, 存在: {os.path.exists(file_path)}"
                        )

                        if os.path.exists(file_path):
                            response = send_file(
                                file_path,
                                as_attachment=False,
                                mimetype="application/pdf",
                            )
                            # 添加 CORS 头，允许 PDF.js 访问
                            response.headers["Access-Control-Allow-Origin"] = "*"
                            response.headers["Access-Control-Allow-Methods"] = "GET"
                            response.headers["Access-Control-Allow-Headers"] = (
                                "Content-Type"
                            )
                            return response
                        else:
                            print(f"文件不存在: {file_path}")
                            return (
                                jsonify({"error": f"File not found: {file_path}"}),
                                404,
                            )
                    else:
                        print(f"无法确定文件路径，paper数据: {paper}")
                        return (
                            jsonify({"error": "File path not found in paper data"}),
                            404,
                        )

        if "children" in node:
            for child in node["children"]:
                result = search_paper_file(child)
                if result:
                    return result

        return None

    # 查找论文文件
    for child in categories.get("children", []):
        result = search_paper_file(child)
        if result:
            return result

    return jsonify({"error": "Paper not found"}), 404


@app.route("/api/paper/<paper_id>", methods=["DELETE"])
def api_delete_paper(paper_id):
    """删除论文"""
    try:
        # 遍历所有分类目录查找论文
        categories = get_categories()

        def search_and_delete_paper(node):
            # 获取当前分类的路径
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(category_path)
                for paper in papers:
                    if paper["id"] == paper_id:
                        # 找到论文，删除PDF和JSON文件
                        file_path = paper.get("file_path")
                        if file_path:
                            delete_paper_files(file_path)

                        return {
                            "success": True,
                            "message": "Paper deleted successfully",
                            "paper": paper,
                            "category_id": node["id"],
                        }

            # 递归搜索子分类
            if "children" in node:
                for child in node["children"]:
                    result = search_and_delete_paper(child)
                    if result:
                        return result

            return None

        # 从根节点开始搜索并删除
        for child in categories.get("children", []):
            result = search_and_delete_paper(child)
            if result:
                return jsonify(result)

        return jsonify({"error": "Paper not found"}), 404

    except Exception as e:
        print(f"删除论文失败: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/paper/<paper_id>", methods=["PUT"])
def api_update_paper(paper_id):
    """更新论文信息"""
    try:
        data = request.json
        categories = get_categories()

        def search_and_update_paper(node):
            # 获取当前分类的路径
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(category_path)
                for paper in papers:
                    if paper["id"] == paper_id:
                        # 更新论文信息
                        if "title" in data:
                            paper["title"] = data["title"]
                        if "authors" in data:
                            paper["authors"] = data["authors"]
                        if "affiliation" in data:
                            paper["affiliation"] = data["affiliation"]
                        if "year" in data:
                            paper["year"] = data["year"]
                        if "journal" in data:
                            paper["journal"] = data["journal"]
                        if "abstract" in data:
                            paper["abstract"] = data["abstract"]
                        if "starred" in data:
                            paper["starred"] = data["starred"]
                        if "notes" in data:
                            paper["notes"] = data["notes"]
                        if "keywords" in data:
                            paper["keywords"] = data["keywords"]
                        if "subject" in data:
                            paper["subject"] = data["subject"]

                        paper["updated_date"] = datetime.now().isoformat()

                        # 保存更新后的论文数据到JSON文件
                        file_path = paper.get("file_path")
                        if file_path:
                            save_paper_metadata(file_path, paper)

                        return {
                            "success": True,
                            "message": "Paper updated successfully",
                            "paper": paper,
                        }

            # 递归搜索子分类
            if "children" in node:
                for child in node["children"]:
                    result = search_and_update_paper(child)
                    if result:
                        return result

            return None

        # 从根节点开始搜索并更新
        for child in categories.get("children", []):
            result = search_and_update_paper(child)
            if result:
                return jsonify(result)

        return jsonify({"error": "Paper not found"}), 404

    except Exception as e:
        print(f"更新论文失败: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def translate_paper_task(
    task_id,
    paper_id,
    pdf_path,
    pdf_dir,
    pdf_filename,
    openai_model,
    openai_base_url,
    openai_api_key,
):
    """后台翻译任务"""
    start_time = datetime.now()  # 记录开始时间
    with translation_tasks_lock:
        task_info = translation_tasks[task_id]
        task_info["status"] = "running"
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None

    def read_output(pipe, label):
        """实时读取子进程输出"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    # 打印到控制台
                    print(f"[{label}] {line}")
                    # 保存到日志列表
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
        except Exception as e:
            print(f"读取输出时出错: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        os.chdir(pdf_dir)
        cmd = [
            "babeldoc",
            "--openai",
            "--openai-model",
            openai_model,
            "--openai-base-url",
            openai_base_url,
            "--openai-api-key",
            openai_api_key,
            "--files",
            pdf_filename,
        ]

        print(f"执行翻译命令: {' '.join(cmd)}")
        print(f"工作目录: {pdf_dir}")

        # 使用Popen实时捕获输出
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        # 更新任务信息中的进程
        with translation_tasks_lock:
            translation_tasks[task_id]["process"] = process

        # 启动线程实时读取输出
        stdout_thread = threading.Thread(
            target=read_output, args=(process.stdout, "STDOUT")
        )
        stderr_thread = threading.Thread(
            target=read_output, args=(process.stderr, "STDERR")
        )
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        # 等待进程完成
        return_code = process.wait(timeout=3600)

        # 等待输出线程完成
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

        # 更新任务状态
        with translation_tasks_lock:
            if return_code == 0:
                # 查找生成的翻译文件
                base_name = os.path.splitext(pdf_filename)[0]
                dual_file = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
                mono_file = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")

                if os.path.exists(dual_file):
                    # 删除mono文件
                    if os.path.exists(mono_file):
                        os.remove(mono_file)

                    # 更新论文元数据
                    categories = get_categories()

                    def search_and_update_paper(node):
                        category_path = get_category_path(categories, node["id"])
                        if category_path:
                            papers = get_papers_in_category(category_path)
                            for paper in papers:
                                if paper["id"] == paper_id:
                                    paper["has_chinese_version"] = True
                                    paper["chinese_version_path"] = dual_file
                                    save_paper_metadata(pdf_path, paper)
                                    return True
                        if "children" in node:
                            for child in node["children"]:
                                if search_and_update_paper(child):
                                    return True
                        return False

                    for child in categories.get("children", []):
                        if search_and_update_paper(child):
                            break

                    # 保存日志文件
                    log_file = os.path.join(pdf_dir, f"{base_name}.translate.log")
                    try:
                        with open(log_file, "w", encoding="utf-8") as f:
                            f.write("\n".join(log_lines))
                    except Exception as e:
                        print(f"保存日志文件失败: {e}")

                    # 计算翻译耗时（秒）
                    end_time = datetime.now()
                    translation_duration = int((end_time - start_time).total_seconds())

                    # 更新论文的翻译时间（一次性，取最大值）
                    categories = get_categories()

                    def search_and_update_paper(node):
                        category_path = get_category_path(categories, node["id"])
                        if category_path:
                            papers = get_papers_in_category(category_path)
                            for paper in papers:
                                if paper["id"] == paper_id:
                                    paper["translation_time"] = max(
                                        paper.get("translation_time", 0),
                                        translation_duration,
                                    )
                                    pdf_path = paper.get("file_path")
                                    if pdf_path and os.path.exists(pdf_path):
                                        save_paper_metadata(pdf_path, paper)
                                    return True
                        if "children" in node:
                            for child in node["children"]:
                                if search_and_update_paper(child):
                                    return True
                        return False

                    for child in categories.get("children", []):
                        if search_and_update_paper(child):
                            break

                    translation_tasks[task_id]["status"] = "completed"
                    translation_tasks[task_id]["result"] = {
                        "success": True,
                        "chinese_version_path": dual_file,
                        "log_file": log_file,
                    }
                else:
                    translation_tasks[task_id]["status"] = "failed"
                    translation_tasks[task_id]["result"] = {
                        "success": False,
                        "error": "翻译文件未生成",
                    }
            else:
                translation_tasks[task_id]["status"] = "failed"
                translation_tasks[task_id]["result"] = {
                    "success": False,
                    "error": f"翻译失败 (退出码: {return_code})",
                }

    except subprocess.TimeoutExpired:
        with translation_tasks_lock:
            translation_tasks[task_id]["status"] = "failed"
            translation_tasks[task_id]["result"] = {
                "success": False,
                "error": "翻译超时",
            }
        if process:
            process.kill()
    except Exception as e:
        print(f"翻译过程出错: {str(e)}")
        import traceback

        traceback.print_exc()
        with translation_tasks_lock:
            translation_tasks[task_id]["status"] = "failed"
            translation_tasks[task_id]["result"] = {
                "success": False,
                "error": f"翻译失败: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        os.chdir(original_cwd)


def analyze_paper_task(
    task_id,
    paper_id,
    pdf_path,
    pdf_dir,
    pdf_filename,
    mineru_server_url,
    openai_base_url,
    openai_api_key,
    system_prompt,
):
    """后台AI解读任务 - 两步：PDF2MD -> LLM解读"""
    start_time = datetime.now()  # 记录开始时间
    with analysis_tasks_lock:
        task_info = analysis_tasks[task_id]
        task_info["status"] = "running"
        task_info["step"] = "pdf2md"  # 第一步：PDF转Markdown
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None

    def read_output(pipe, label):
        """实时读取子进程输出"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    # 打印到控制台
                    print(f"[{label}] {line}")
                    # 保存到日志列表
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
        except Exception as e:
            print(f"读取输出时出错: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        # ========== 第一步：PDF转Markdown ==========
        with analysis_tasks_lock:
            analysis_tasks[task_id]["step"] = "pdf2md"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("第一步：开始将PDF解析为Markdown...")
                log_lines.append("=" * 50)

        os.chdir(pdf_dir)

        # 构建 mineru 命令
        cmd = [
            "mineru",
            "-p",
            pdf_filename,
            "-o",
            "outputs",
            "-b",
            "vlm-http-client",
            "-u",
            mineru_server_url,
        ]

        print(f"执行PDF2MD命令: {' '.join(cmd)}")
        print(f"工作目录: {pdf_dir}")

        # 使用Popen实时捕获输出
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        # 更新任务信息中的进程
        with analysis_tasks_lock:
            analysis_tasks[task_id]["process"] = process

        # 启动线程实时读取输出
        stdout_thread = threading.Thread(
            target=read_output, args=(process.stdout, "STDOUT")
        )
        stderr_thread = threading.Thread(
            target=read_output, args=(process.stderr, "STDERR")
        )
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        # 等待进程完成
        return_code = process.wait(timeout=3600)

        # 等待输出线程完成
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

        if return_code != 0:
            raise Exception(f"PDF2MD失败 (退出码: {return_code})")

        # 清理输出目录，只保留 images 和 pdf名称.md
        base_name = os.path.splitext(pdf_filename)[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")

        # 精确定位当前PDF的目录结构：outputs/<base_name>/vlm/
        pdf_output_dir = os.path.join(outputs_dir, base_name, "vlm")
        if not os.path.exists(pdf_output_dir):
            # 兼容历史或异常结构：回退到遍历，但优先匹配包含 base_name 的目录
            candidate = None
            for item in os.listdir(outputs_dir):
                item_path = os.path.join(outputs_dir, item)
                if os.path.isdir(item_path) and base_name in item:
                    vlm_dir = os.path.join(item_path, "vlm")
                    if os.path.exists(vlm_dir):
                        candidate = vlm_dir
                        break
            if candidate:
                pdf_output_dir = candidate

        if not pdf_output_dir or not os.path.exists(pdf_output_dir):
            raise Exception("未找到PDF解析输出目录")

        with log_lock:
            log_lines.append(f"找到输出目录: {pdf_output_dir}")

        # 保留 images 目录和 pdf名称.md 文件，删除其他
        vlm_items = os.listdir(pdf_output_dir)
        md_file = None
        for item in vlm_items:
            item_path = os.path.join(pdf_output_dir, item)
            if item == "images" and os.path.isdir(item_path):
                continue  # 保留 images 目录
            elif item.endswith(".md") and os.path.isfile(item_path):
                md_file = item_path
                continue  # 保留 markdown 文件
            else:
                # 删除其他文件和目录
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    with log_lock:
                        log_lines.append(f"删除目录: {item}")
                else:
                    os.remove(item_path)
                    with log_lock:
                        log_lines.append(f"删除文件: {item}")

        if not md_file:
            raise Exception("未找到生成的Markdown文件")

        with log_lock:
            log_lines.append("=" * 50)
            log_lines.append("第一步完成：PDF已解析为Markdown")
            log_lines.append(f"Markdown文件: {md_file}")
            log_lines.append("=" * 50)

        # ========== 第二步：LLM解读 ==========
        with analysis_tasks_lock:
            analysis_tasks[task_id]["step"] = "llm_analysis"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("第二步：开始LLM解读...")
                log_lines.append("=" * 50)

        # 读取 markdown 文件
        with open(md_file, "r", encoding="utf-8") as f:
            markdown_content = f.read()

        # 构建 LLM 请求
        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        # 获取模型列表并选择第一个
        try:
            models = client.models.list()
            model = models.data[0].id if models.data else None
            if not model:
                raise Exception("无法获取模型列表")
        except Exception as e:
            raise Exception(f"获取模型列表失败: {str(e)}")

        # 构建消息
        prompt = system_prompt.replace("<MARKDOWN>", markdown_content)
        messages = [{"role": "user", "content": prompt}]

        with log_lock:
            log_lines.append(f"使用模型: {model}")
            log_lines.append(f"开始调用LLM API...")

        # 调用 LLM API
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
        )

        result_content = chat_completion.choices[0].message.content

        # 保存结果到 outputs/pdf名称/vlm/result.md
        result_file = os.path.join(pdf_output_dir, "result.md")
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(result_content)

        with log_lock:
            log_lines.append("=" * 50)
            log_lines.append("第二步完成：LLM解读完成")
            log_lines.append(f"结果文件: {result_file}")
            log_lines.append("=" * 50)

        # 更新论文元数据，标记有解读结果
        categories = get_categories()

        def search_and_update_paper(node):
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers_list = get_papers_in_category(category_path)
                for paper in papers_list:
                    if paper["id"] == paper_id:
                        paper["has_analysis_result"] = True
                        paper["analysis_result_path"] = result_file
                        save_paper_metadata(pdf_path, paper)
                        return True
            if "children" in node:
                for child in node["children"]:
                    if search_and_update_paper(child):
                        return True
            return False

        for child in categories.get("children", []):
            if search_and_update_paper(child):
                break

        # 计算解读耗时（秒）
        end_time = datetime.now()
        analysis_duration = int((end_time - start_time).total_seconds())

        # 更新论文的解读时间（一次性，取最大值）
        categories = get_categories()

        def search_and_update_analysis_time(node):
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(category_path)
                for paper in papers:
                    if paper["id"] == paper_id:
                        paper["analysis_time"] = max(
                            paper.get("analysis_time", 0), analysis_duration
                        )
                        pdf_path = paper.get("file_path")
                        if pdf_path and os.path.exists(pdf_path):
                            save_paper_metadata(pdf_path, paper)
                        return True
            if "children" in node:
                for child in node["children"]:
                    if search_and_update_analysis_time(child):
                        return True
            return False

        for child in categories.get("children", []):
            if search_and_update_analysis_time(child):
                break

        # 更新任务状态
        with analysis_tasks_lock:
            analysis_tasks[task_id]["status"] = "completed"
            analysis_tasks[task_id]["result"] = {
                "success": True,
                "result_file": result_file,
                "markdown_file": md_file,
            }

    except subprocess.TimeoutExpired:
        with analysis_tasks_lock:
            analysis_tasks[task_id]["status"] = "failed"
            analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": "解读超时",
            }
        if process:
            process.kill()
    except Exception as e:
        print(f"解读过程出错: {str(e)}")
        import traceback

        traceback.print_exc()
        with analysis_tasks_lock:
            analysis_tasks[task_id]["status"] = "failed"
            analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": f"解读失败: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        os.chdir(original_cwd)


@app.route("/api/paper/translate", methods=["POST"])
def api_translate_paper():
    """翻译PDF论文 - 启动后台任务"""
    try:
        data = request.json
        paper_id = data.get("paper_id")
        openai_model = data.get("openai_model")
        openai_base_url = data.get("openai_base_url")
        openai_api_key = data.get("openai_api_key")

        if (
            not paper_id
            or not openai_model
            or not openai_base_url
            or not openai_api_key
        ):
            return jsonify({"success": False, "error": "缺少必要参数"}), 400

        # 检查是否已有该论文的翻译任务在运行
        with translation_tasks_lock:
            for task_id, task_info in translation_tasks.items():
                if (
                    task_info["paper_id"] == paper_id
                    and task_info["status"] == "running"
                ):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "该论文已有翻译任务在运行",
                                "task_id": task_id,
                            }
                        ),
                        400,
                    )

        # 查找论文
        categories = get_categories()

        def search_paper_recursive(node):
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(category_path)
                for paper in papers:
                    if paper["id"] == paper_id:
                        return paper, category_path

            if "children" in node:
                for child in node["children"]:
                    result = search_paper_recursive(child)
                    if result:
                        return result

            return None

        result = None
        for child in categories.get("children", []):
            result = search_paper_recursive(child)
            if result:
                break

        if not result:
            return jsonify({"success": False, "error": "论文未找到"}), 404

        paper, category_path = result
        pdf_path = paper.get("file_path")

        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"success": False, "error": "PDF文件不存在"}), 404

        # 获取PDF文件所在目录
        pdf_dir = os.path.dirname(pdf_path)
        pdf_filename = os.path.basename(pdf_path)

        # 创建任务ID
        task_id = str(uuid.uuid4())

        # 创建任务信息
        with translation_tasks_lock:
            translation_tasks[task_id] = {
                "paper_id": paper_id,
                "status": "queued",  # queued, running, completed, failed, cancelled
                "logs": [],
                "log_lock": threading.Lock(),
                "process": None,
                "start_time": datetime.now().isoformat(),
                "result": None,
            }

        # 在后台线程中启动翻译任务
        thread = threading.Thread(
            target=translate_paper_task,
            args=(
                task_id,
                paper_id,
                pdf_path,
                pdf_dir,
                pdf_filename,
                openai_model,
                openai_base_url,
                openai_api_key,
            ),
        )
        thread.daemon = True
        thread.start()

        return jsonify(
            {"success": True, "message": "翻译任务已启动", "task_id": task_id}
        )

    except Exception as e:
        print(f"启动翻译任务失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": f"启动翻译任务失败: {str(e)}"}), 500


@app.route("/api/paper/translate/active", methods=["GET"])
def api_get_active_translations():
    """获取所有进行中的翻译任务"""
    with translation_tasks_lock:
        active_tasks = []
        for task_id, task_info in translation_tasks.items():
            if task_info["status"] in ["queued", "running"]:
                active_tasks.append(
                    {
                        "task_id": task_id,
                        "paper_id": task_info["paper_id"],
                        "status": task_info["status"],
                        "start_time": task_info["start_time"],
                    }
                )
        return jsonify({"success": True, "tasks": active_tasks})


@app.route("/api/paper/translate/<task_id>/logs", methods=["GET"])
def api_get_translation_logs(task_id):
    """获取翻译任务的日志"""
    with translation_tasks_lock:
        if task_id not in translation_tasks:
            return jsonify({"success": False, "error": "任务不存在"}), 404

        task_info = translation_tasks[task_id]
        with task_info["log_lock"]:
            logs = task_info["logs"].copy()

        return jsonify(
            {
                "success": True,
                "status": task_info["status"],
                "logs": logs,
                "start_time": task_info["start_time"],
                "result": task_info.get("result"),
            }
        )


@app.route("/api/paper/translate/<task_id>/cancel", methods=["POST"])
def api_cancel_translation(task_id):
    """取消翻译任务"""
    with translation_tasks_lock:
        if task_id not in translation_tasks:
            return jsonify({"success": False, "error": "任务不存在"}), 404

        task_info = translation_tasks[task_id]

        if task_info["status"] in ["completed", "failed", "cancelled"]:
            return jsonify({"success": False, "error": "任务已结束，无法取消"}), 400

        # 终止进程
        process = task_info.get("process")
        if process and process.poll() is None:  # 进程仍在运行
            try:
                process.terminate()
                # 等待进程结束
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 如果5秒内没有结束，强制杀死
                process.kill()
                process.wait()
            except Exception as e:
                print(f"终止进程失败: {e}")

        task_info["status"] = "cancelled"
        task_info["result"] = {"success": False, "error": "翻译已取消"}

        return jsonify({"success": True, "message": "翻译任务已取消"})


@app.route("/api/paper/<paper_id>/chinese/file")
def api_get_chinese_paper_file(paper_id):
    """获取中文版本PDF文件"""
    categories = get_categories()

    def search_paper_file(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    chinese_path = paper.get("chinese_version_path")
                    if chinese_path and os.path.exists(chinese_path):
                        response = send_file(
                            chinese_path,
                            as_attachment=False,
                            mimetype="application/pdf",
                        )
                        response.headers["Access-Control-Allow-Origin"] = "*"
                        response.headers["Access-Control-Allow-Methods"] = "GET"
                        response.headers["Access-Control-Allow-Headers"] = (
                            "Content-Type"
                        )
                        return response
                    else:
                        return jsonify({"error": "中文版本文件不存在"}), 404

        if "children" in node:
            for child in node["children"]:
                result = search_paper_file(child)
                if result:
                    return result

        return None

    for child in categories.get("children", []):
        result = search_paper_file(child)
        if result:
            return result

    return jsonify({"error": "论文未找到"}), 404


@app.route("/api/paper/analyze", methods=["POST"])
def api_analyze_paper():
    """AI解读PDF论文 - 启动后台任务"""
    try:
        data = request.json
        paper_id = data.get("paper_id")
        mineru_server_url = data.get("mineru_server_url")
        openai_base_url = data.get("openai_base_url")
        openai_api_key = data.get("openai_api_key")
        system_prompt = data.get("system_prompt")

        if (
            not paper_id
            or not mineru_server_url
            or not openai_base_url
            or not openai_api_key
            or not system_prompt
        ):
            return jsonify({"success": False, "error": "缺少必要参数"}), 400

        # 检查是否已有该论文的解读任务在运行
        with analysis_tasks_lock:
            for task_id, task_info in analysis_tasks.items():
                if (
                    task_info["paper_id"] == paper_id
                    and task_info["status"] == "running"
                ):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "该论文已有解读任务在运行",
                                "task_id": task_id,
                            }
                        ),
                        400,
                    )

        # 查找论文
        categories = get_categories()

        def search_paper_recursive(node):
            category_path = get_category_path(categories, node["id"])
            if category_path:
                papers = get_papers_in_category(category_path)
                for paper in papers:
                    if paper["id"] == paper_id:
                        return paper, category_path

            if "children" in node:
                for child in node["children"]:
                    result = search_paper_recursive(child)
                    if result:
                        return result

            return None

        result = None
        for child in categories.get("children", []):
            result = search_paper_recursive(child)
            if result:
                break

        if not result:
            return jsonify({"success": False, "error": "论文未找到"}), 404

        paper, category_path = result
        pdf_path = paper.get("file_path")

        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"success": False, "error": "PDF文件不存在"}), 404

        # 获取PDF文件所在目录
        pdf_dir = os.path.dirname(pdf_path)
        pdf_filename = os.path.basename(pdf_path)

        # 创建任务ID
        task_id = str(uuid.uuid4())

        # 创建任务信息
        with analysis_tasks_lock:
            analysis_tasks[task_id] = {
                "paper_id": paper_id,
                "status": "queued",  # queued, running, completed, failed, cancelled
                "step": None,  # pdf2md, llm_analysis
                "logs": [],
                "log_lock": threading.Lock(),
                "process": None,
                "start_time": datetime.now().isoformat(),
                "result": None,
            }

        # 在后台线程中启动解读任务
        thread = threading.Thread(
            target=analyze_paper_task,
            args=(
                task_id,
                paper_id,
                pdf_path,
                pdf_dir,
                pdf_filename,
                mineru_server_url,
                openai_base_url,
                openai_api_key,
                system_prompt,
            ),
        )
        thread.daemon = True
        thread.start()

        return jsonify(
            {"success": True, "message": "解读任务已启动", "task_id": task_id}
        )

    except Exception as e:
        print(f"启动解读任务失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": f"启动解读任务失败: {str(e)}"}), 500


@app.route("/api/paper/analyze/<task_id>/logs", methods=["GET"])
def api_get_analysis_logs(task_id):
    """获取解读任务的日志"""
    with analysis_tasks_lock:
        if task_id not in analysis_tasks:
            return jsonify({"success": False, "error": "任务不存在"}), 404

        task_info = analysis_tasks[task_id]
        with task_info["log_lock"]:
            logs = task_info["logs"].copy()

        return jsonify(
            {
                "success": True,
                "status": task_info["status"],
                "step": task_info.get("step"),
                "logs": logs,
                "start_time": task_info["start_time"],
                "result": task_info.get("result"),
            }
        )


@app.route("/api/paper/analyze/active", methods=["GET"])
def api_get_active_analysis():
    """获取所有进行中的解读任务"""
    with analysis_tasks_lock:
        active_tasks = []
        for task_id, task_info in analysis_tasks.items():
            if task_info["status"] in ["queued", "running"]:
                active_tasks.append(
                    {
                        "task_id": task_id,
                        "paper_id": task_info["paper_id"],
                        "status": task_info["status"],
                        "step": task_info.get("step"),
                        "start_time": task_info["start_time"],
                    }
                )
        return jsonify({"success": True, "tasks": active_tasks})


@app.route("/api/paper/analyze/<task_id>/cancel", methods=["POST"])
def api_cancel_analysis(task_id):
    """取消解读任务"""
    with analysis_tasks_lock:
        if task_id not in analysis_tasks:
            return jsonify({"success": False, "error": "任务不存在"}), 404

        task_info = analysis_tasks[task_id]

        if task_info["status"] in ["completed", "failed", "cancelled"]:
            return jsonify({"success": False, "error": "任务已结束，无法取消"}), 400

        # 终止进程
        process = task_info.get("process")
        if process and process.poll() is None:  # 进程仍在运行
            try:
                process.terminate()
                # 等待进程结束
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 如果5秒内没有结束，强制杀死
                process.kill()
                process.wait()
            except Exception as e:
                print(f"终止进程失败: {e}")

        task_info["status"] = "cancelled"
        task_info["result"] = {"success": False, "error": "解读已取消"}

        return jsonify({"success": True, "message": "解读任务已取消"})


@app.route("/api/paper/<paper_id>/analysis/result")
def api_get_analysis_result(paper_id):
    """获取解读结果文件"""
    categories = get_categories()

    def search_paper_recursive(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    return paper, category_path

        if "children" in node:
            for child in node["children"]:
                result = search_paper_recursive(child)
                if result:
                    return result

        return None

    result = None
    for child in categories.get("children", []):
        result = search_paper_recursive(child)
        if result:
            break

    if not result:
        return jsonify({"error": "论文未找到"}), 404

    paper, category_path = result
    pdf_path = paper.get("file_path")

    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "PDF文件不存在"}), 404

    # 查找 result.md 文件
    pdf_dir = os.path.dirname(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    outputs_dir = os.path.join(pdf_dir, "outputs")

    # 优先精确查找 outputs/当前PDF名/vlm/result.md，避免被其它论文的结果覆盖
    result_file = None
    if os.path.exists(outputs_dir):
        exact_result = os.path.join(outputs_dir, base_name, "vlm", "result.md")
        if os.path.exists(exact_result):
            result_file = exact_result
        else:
            # 兼容历史目录结构：回退到遍历查找（但这可能命中第一个有结果的论文）
            for item in os.listdir(outputs_dir):
                item_path = os.path.join(outputs_dir, item)
                if os.path.isdir(item_path):
                    vlm_dir = os.path.join(item_path, "vlm")
                    if os.path.exists(vlm_dir):
                        potential_result = os.path.join(vlm_dir, "result.md")
                        if os.path.exists(potential_result):
                            result_file = potential_result
                            break

    if not result_file or not os.path.exists(result_file):
        return jsonify({"error": "解读结果文件不存在"}), 404

    # 读取并返回 markdown 内容
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"success": True, "content": content, "file_path": result_file})
    except Exception as e:
        return jsonify({"error": f"读取结果文件失败: {str(e)}"}), 500


@app.route("/api/paper/<paper_id>/analysis/image")
def api_get_analysis_image(paper_id):
    """获取解读结果中的图片"""
    categories = get_categories()

    def search_paper_recursive(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    return paper, category_path

        if "children" in node:
            for child in node["children"]:
                result = search_paper_recursive(child)
                if result:
                    return result

        return None

    result = None
    for child in categories.get("children", []):
        result = search_paper_recursive(child)
        if result:
            break

    if not result:
        return jsonify({"error": "论文未找到"}), 404

    paper, category_path = result
    pdf_path = paper.get("file_path")

    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "PDF文件不存在"}), 404

    # 获取图片路径参数
    image_path = request.args.get("path")
    if not image_path:
        return jsonify({"error": "未提供图片路径"}), 400

    # 查找图片文件
    pdf_dir = os.path.dirname(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    outputs_dir = os.path.join(pdf_dir, "outputs")

    # 优先精确查找 outputs/当前PDF名/vlm/images/图片名
    image_file = None
    if os.path.exists(outputs_dir):
        vlm_dir_specific = os.path.join(outputs_dir, base_name, "vlm")
        if os.path.exists(vlm_dir_specific):
            if image_path.startswith("images/"):
                potential_image = os.path.join(vlm_dir_specific, image_path)
            else:
                potential_image = os.path.join(vlm_dir_specific, "images", image_path)

            if os.path.exists(potential_image) and os.path.isfile(potential_image):
                image_file = potential_image
        if not image_file:
            # 兼容历史目录结构：回退到遍历查找
            for item in os.listdir(outputs_dir):
                item_path = os.path.join(outputs_dir, item)
                if os.path.isdir(item_path):
                    vlm_dir = os.path.join(item_path, "vlm")
                    if os.path.exists(vlm_dir):
                        if image_path.startswith("images/"):
                            potential_image = os.path.join(vlm_dir, image_path)
                        else:
                            potential_image = os.path.join(
                                vlm_dir, "images", image_path
                            )

                        if os.path.exists(potential_image) and os.path.isfile(
                            potential_image
                        ):
                            image_file = potential_image
                            break

    if not image_file or not os.path.exists(image_file):
        return jsonify({"error": "图片文件不存在"}), 404

    # 返回图片文件
    return send_file(image_file, mimetype="image/jpeg")


@app.route("/viewer/<paper_id>")
def pdf_viewer(paper_id):
    """PDF阅读器页面"""
    use_chinese = request.args.get("chinese", "false").lower() == "true"
    return render_template(
        "pdf_viewer.html", paper_id=paper_id, use_chinese=use_chinese
    )


@app.route("/viewer/analysis/<paper_id>")
def analysis_viewer(paper_id):
    """AI 解读 Markdown 全屏查看页面"""
    return render_template("analysis_viewer.html", paper_id=paper_id)


# ==================== 待读列表 API ====================
@app.route("/api/reading-list")
def api_reading_list():
    """获取待读列表中的所有论文，并检查是否应该自动移除"""
    paper_ids = get_reading_list()
    papers = []

    # 读取设置
    SETTINGS_FILE = os.path.join(BASE_DIR, "general_settings.json")
    auto_remove_minutes = 5  # 默认5分钟
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                auto_remove_minutes = settings.get(
                    "reading_list_auto_remove_minutes", 5
                )
    except Exception as e:
        print(f"读取设置失败: {e}")

    auto_remove_seconds = auto_remove_minutes * 60

    # 获取每个论文的详细信息
    categories = get_categories()
    papers_to_remove = []

    for paper_id in paper_ids:

        def search_paper_recursive(node):
            category_path = get_category_path(categories, node["id"])
            if category_path:
                category_papers = get_papers_in_category(category_path)
                for paper in category_papers:
                    if paper["id"] == paper_id:
                        return paper
            if "children" in node:
                for child in node["children"]:
                    result = search_paper_recursive(child)
                    if result:
                        return result
            return None

        for child in categories.get("children", []):
            paper = search_paper_recursive(child)
            if paper:
                # 检查总时间是否超过阈值
                total_time = get_paper_total_time(paper_id)
                if total_time >= auto_remove_seconds:
                    # 自动移除
                    papers_to_remove.append(paper_id)
                else:
                    papers.append(paper)
                break

    # 移除超过阈值的论文
    for paper_id in papers_to_remove:
        remove_from_reading_list(paper_id)

    return jsonify(papers)


@app.route("/api/reading-list/<paper_id>/add", methods=["POST"])
def api_add_to_reading_list(paper_id):
    """添加论文到待读列表"""
    add_to_reading_list(paper_id)
    return jsonify({"success": True})


@app.route("/api/reading-list/<paper_id>/remove", methods=["POST"])
def api_remove_from_reading_list(paper_id):
    """从待读列表移除论文"""
    remove_from_reading_list(paper_id)
    return jsonify({"success": True})


@app.route("/api/reading-list/<paper_id>/check", methods=["GET"])
def api_check_reading_list(paper_id):
    """检查论文是否在待读列表中"""
    in_list = is_in_reading_list(paper_id)
    return jsonify({"in_list": in_list})


@app.route("/api/paper/<paper_id>/read-time", methods=["POST"])
def api_record_read_time(paper_id):
    """记录论文的阅读时间（一次性，不是累计）"""
    data = request.json
    read_time = data.get("read_time", 0)  # 秒

    # 查找论文并更新阅读时间
    categories = get_categories()

    def search_and_update_recursive(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    # 更新阅读时间（一次性，取最大值）
                    paper["read_time"] = max(paper.get("read_time", 0), read_time)
                    # 保存到JSON文件
                    pdf_path = paper.get("file_path")
                    if pdf_path and os.path.exists(pdf_path):
                        save_paper_metadata(pdf_path, paper)
                    return True
        if "children" in node:
            for child in node["children"]:
                if search_and_update_recursive(child):
                    return True
        return False

    for child in categories.get("children", []):
        if search_and_update_recursive(child):
            break

    return jsonify({"success": True})


@app.route("/api/paper/<paper_id>/analysis-view-time", methods=["POST"])
def api_record_analysis_view_time(paper_id):
    """记录论文的AI解读阅读时间（一次性，不是累计）"""
    data = request.json
    view_time = data.get("view_time", 0)  # 秒

    # 查找论文并更新阅读时间
    categories = get_categories()

    def search_and_update_recursive(node):
        category_path = get_category_path(categories, node["id"])
        if category_path:
            papers = get_papers_in_category(category_path)
            for paper in papers:
                if paper["id"] == paper_id:
                    # 更新AI解读阅读时间（一次性，取最大值）
                    paper["analysis_view_time"] = max(
                        paper.get("analysis_view_time", 0), view_time
                    )
                    # 保存到JSON文件
                    pdf_path = paper.get("file_path")
                    if pdf_path and os.path.exists(pdf_path):
                        save_paper_metadata(pdf_path, paper)
                    return True
        if "children" in node:
            for child in node["children"]:
                if search_and_update_recursive(child):
                    return True
        return False

    for child in categories.get("children", []):
        if search_and_update_recursive(child):
            break

    return jsonify({"success": True})


@app.route("/api/settings/general", methods=["GET", "POST"])
def api_general_settings():
    """获取或保存通用设置（包括待读列表自动移除时间阈值）"""
    SETTINGS_FILE = os.path.join(BASE_DIR, "general_settings.json")

    if request.method == "GET":
        # 读取设置
        default_settings = {"reading_list_auto_remove_minutes": 5}  # 默认5分钟
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    # 合并默认值
                    for key, value in default_settings.items():
                        if key not in settings:
                            settings[key] = value
                    return jsonify(settings)
        except Exception as e:
            print(f"读取设置失败: {e}")
        return jsonify(default_settings)

    else:  # POST
        # 保存设置
        data = request.json
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    init_categories()
    # 论文数据现在直接存储在PDF文件旁边的JSON文件中
    app.run(host="0.0.0.0", port=5005, debug=True)
