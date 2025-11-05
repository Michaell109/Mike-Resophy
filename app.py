import json
import os
import re
import shutil
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
# 不再使用统一的papers_db.json文件，改为每个PDF一个JSON文件

# 确保必要的目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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


def fetch_arxiv_abstract(arxiv_id: str) -> str | None:
    """从 arXiv API 获取摘要。返回纯文本摘要，失败返回 None。"""
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
        summary = entry.find("{http://www.w3.org/2005/Atom}summary")
        if summary is None or not summary.text:
            return None
        abstract = summary.text.strip()
        abstract = re.sub(r"\s+", " ", abstract)
        return abstract
    except Exception as e:
        print(f"获取 arXiv 摘要失败: {e}")
        return None


def delete_paper_files(pdf_path):
    """删除PDF文件和对应的JSON文件"""
    json_path = get_paper_json_path(pdf_path)

    # 删除PDF文件
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
        print(f"已删除PDF文件: {pdf_path}")

    # 删除JSON文件
    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"已删除JSON文件: {json_path}")


def scan_papers_in_directory(directory_path):
    """扫描目录中的所有PDF文件并加载其元数据"""
    papers = []
    if not os.path.exists(directory_path):
        return papers

    for filename in os.listdir(directory_path):
        if filename.lower().endswith(".pdf"):
            pdf_path = os.path.join(directory_path, filename)
            paper_data = load_paper_metadata(pdf_path)

            if paper_data:
                # 确保文件路径是最新的
                paper_data["file_path"] = pdf_path
                paper_data["filename"] = filename
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

    # 如果前端提供 arxiv_id 且没有摘要，尝试从 arXiv 获取摘要
    arxiv_id = (metadata.get("arxiv_id") or "").strip()
    if arxiv_id:
        arxiv_abs = fetch_arxiv_abstract(arxiv_id)
        if arxiv_abs:
            metadata["abstract"] = arxiv_abs
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
        "affiliation": metadata.get("affiliation") or "",
        "year": metadata.get("year") or "",
        "journal": "",
        "abstract": metadata.get("abstract") or "",
        "keywords": metadata.get("keywords") or "",
        "subject": metadata.get("subject") or "",
        "notes": "",
    }

    # 保存论文元数据到JSON文件
    save_paper_metadata(file_path, paper_info)

    return jsonify({"success": True, "paper": paper_info})


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
                    if file_path and os.path.exists(file_path):
                        response = send_file(
                            file_path, as_attachment=False, mimetype="application/pdf"
                        )
                        # 添加 CORS 头，允许 PDF.js 访问
                        response.headers["Access-Control-Allow-Origin"] = "*"
                        response.headers["Access-Control-Allow-Methods"] = "GET"
                        response.headers["Access-Control-Allow-Headers"] = (
                            "Content-Type"
                        )
                        return response
                    else:
                        return jsonify({"error": "File not found"}), 404

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


@app.route("/viewer/<paper_id>")
def pdf_viewer(paper_id):
    """PDF阅读器页面"""
    return render_template("pdf_viewer.html", paper_id=paper_id)


if __name__ == "__main__":
    init_categories()
    # 论文数据现在直接存储在PDF文件旁边的JSON文件中
    app.run(host="0.0.0.0", port=5005, debug=True)
