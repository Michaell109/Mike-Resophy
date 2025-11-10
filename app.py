import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from agent_tools.summary_pdf import AnalysisDependencies, analyze_paper_task
from agent_tools.translate_pdf import TranslationDependencies, translate_paper_task
from basic_tools.pdf_extractor import extract_pdf_metadata
from core.base_paper import Paper
from routes.agent_routes.agent_summary_route import register_agent_summary_routes
from routes.agent_routes.agent_translate_route import register_agent_translate_routes

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
    if isinstance(paper_data, Paper):
        data_to_save = paper_data.to_dict()
    else:
        data_to_save = paper_data
        if data_to_save is None:
            data_to_save = {}

    json_path = get_paper_json_path(pdf_path)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"已保存论文元数据: {json_path}")
    except Exception as e:
        print(f"保存论文元数据失败: {e}")


def load_paper_metadata(pdf_path):
    """从JSON文件加载论文元数据"""
    json_path = get_paper_json_path(pdf_path)
    try:
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                return Paper.from_dict(json.load(f))
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
                if paper.id == paper_id:
                    # 获取阅读时间字段（默认为0）
                    read_time = getattr(paper, "read_time", 0)  # 阅读PDF时间（秒）
                    analysis_view_time = getattr(
                        paper, "analysis_view_time", 0
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
    papers: list[Paper] = []
    if not os.path.exists(directory_path):
        return papers

    for filename in os.listdir(directory_path):
        if filename.lower().endswith(".pdf"):
            # 跳过翻译生成的PDF文件（.zh.dual.pdf 和 .zh.mono.pdf）
            if filename.endswith(".zh.dual.pdf") or filename.endswith(".zh.mono.pdf"):
                continue

            pdf_path = os.path.join(directory_path, filename)
            paper = load_paper_metadata(pdf_path)

            if paper:
                paper.sync_filesystem(pdf_path, filename)
            else:
                paper = Paper.create_default(
                    filename=filename,
                    file_path=pdf_path,
                    original_filename=filename,
                    upload_date=datetime.fromtimestamp(
                        os.path.getctime(pdf_path)
                    ).isoformat(),
                )

            # 向后兼容：保证字段存在
            paper.mark_starred(getattr(paper, "starred", False))

            base_name = os.path.splitext(filename)[0]
            dual_file = os.path.join(directory_path, f"{base_name}.zh.dual.pdf")
            paper.mark_chinese_version(dual_file if os.path.exists(dual_file) else None)
            if not paper.has_chinese_version:
                paper.use_chinese_version = False

            # 检查是否有解读结果（只检查当前PDF对应的outputs目录）
            pdf_dir = os.path.dirname(pdf_path)
            outputs_dir = os.path.join(pdf_dir, "outputs")
            analysis_result_path = None
            if os.path.exists(outputs_dir):
                for item in os.listdir(outputs_dir):
                    item_path = os.path.join(outputs_dir, item)
                    if os.path.isdir(item_path) and base_name in item:
                        vlm_dir = os.path.join(item_path, "vlm")
                        if os.path.exists(vlm_dir):
                            result_file = os.path.join(vlm_dir, "result.md")
                            if os.path.exists(result_file):
                                analysis_result_path = result_file
                                break
            paper.mark_analysis_result(analysis_result_path)

            # 保存最新的元数据
            save_paper_metadata(pdf_path, paper)
            papers.append(paper)

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
    # 前端在创建顶层分类时会传入 "root" 或空值，这里统一视为根节点
    if not parent_id or parent_id in {"root", categories.get("id")}:
        parent_node = categories
    else:
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
    return jsonify(Paper.to_dict_list(papers))


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

    paper = Paper.from_dict(paper_info)
    # 保存论文元数据到JSON文件
    if paper:
        save_paper_metadata(file_path, paper)
        # 自动添加到待读列表
        add_to_reading_list(paper.id)
        return jsonify({"success": True, "paper": paper.to_dict()})

    return jsonify({"success": False, "error": "创建论文对象失败"}), 500


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
        paper = Paper.from_dict(paper_info)
        if not paper:
            return jsonify({"success": False, "error": "创建论文对象失败"}), 500

        save_paper_metadata(file_path, paper)

        # 自动添加到待读列表
        add_to_reading_list(paper.id)

        return jsonify({"success": True, "paper": paper.to_dict()})

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
                if paper.id == paper_id:
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
            return jsonify(paper.to_dict())

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
                if paper.id == paper_id:
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

    paper_obj, source_category_id, source_path = paper_result

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

        source_file_path = paper_obj.file_path
        source_json_path = get_paper_json_path(source_file_path)

        # 确保目标目录存在
        os.makedirs(target_folder, exist_ok=True)

        # 生成目标文件路径
        target_file_path = os.path.join(target_folder, paper_obj.filename)
        target_json_path = get_paper_json_path(target_file_path)

        # 如果目标文件已存在，重命名
        counter = 1
        original_filename = paper_obj.filename
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
        paper_obj.filename = os.path.basename(target_file_path)
        paper_obj.file_path = target_file_path

        # 保存更新后的论文数据到新的JSON文件
        save_paper_metadata(target_file_path, paper_obj)

        return jsonify(
            {
                "success": True,
                "paper": paper_obj.to_dict(),
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
                if paper.id == paper_id:
                    file_path = paper.file_path
                    if not file_path:
                        print(f"论文 {paper_id} 没有 file_path 字段")
                        # 尝试从filename和category_path重建路径
                        filename = paper.filename
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
                        print(
                            f"无法确定文件路径，paper数据: {paper.to_dict() if hasattr(paper, 'to_dict') else paper}"
                        )
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
                    if paper.id == paper_id:
                        # 找到论文，删除PDF和JSON文件
                        file_path = paper.file_path
                        if file_path:
                            delete_paper_files(file_path)

                        return {
                            "success": True,
                            "message": "Paper deleted successfully",
                            "paper": paper.to_dict(),
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
                    if paper.id == paper_id:
                        # 更新论文信息
                        paper.update_from_dict(data or {})
                        paper.extra["updated_date"] = datetime.now().isoformat()

                        # 保存更新后的论文数据到JSON文件
                        file_path = paper.file_path
                        if file_path:
                            save_paper_metadata(file_path, paper)

                        return {
                            "success": True,
                            "message": "Paper updated successfully",
                            "paper": paper.to_dict(),
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


register_agent_summary_routes(
    app,
    analysis_tasks=analysis_tasks,
    analysis_tasks_lock=analysis_tasks_lock,
    get_categories=get_categories,
    get_category_path=get_category_path,
    get_papers_in_category=get_papers_in_category,
    save_paper_metadata=save_paper_metadata,
)

register_agent_translate_routes(
    app,
    translation_tasks=translation_tasks,
    translation_tasks_lock=translation_tasks_lock,
    get_categories=get_categories,
    get_category_path=get_category_path,
    get_papers_in_category=get_papers_in_category,
    save_paper_metadata=save_paper_metadata,
)


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


if __name__ == "__main__":
    init_categories()
    # 论文数据现在直接存储在PDF文件旁边的JSON文件中
    app.run(host="192.168.81.138", port=5005, debug=True)
