import argparse
import json
import os
import threading
from datetime import datetime
from functools import partial

from flask import Flask, jsonify, render_template, request

from basic_tools import category_manager, paper_repository
from core.paper_store import paper_store
from routes.agent_routes.agent_summary_route import register_agent_summary_routes
from routes.agent_routes.agent_translate_route import register_agent_translate_routes
from routes.basic_routes.category_tree_route import register_category_routes
from routes.basic_routes.paper_operation_route import register_paper_operation_routes
from routes.basic_routes.search_route import register_search_routes
from routes.basic_routes.settings_route import register_settings_routes
from routes.basic_routes.update_from_url_route import register_update_from_url_routes
from routes.basic_routes.upload_from_pdf_route import register_upload_from_pdf_routes

# 解析命令行参数
parser = argparse.ArgumentParser(description="PaperAgent - 论文管理与阅读系统")
parser.add_argument(
    "--papers-dir",
    type=str,
    default="./leizhang_papers",
    help="论文存储目录路径（默认: ./papers）",
)
parser.add_argument(
    "--host",
    type=str,
    default="192.168.81.138",
    help="服务器监听地址（默认: 192.168.81.138）",
)
parser.add_argument(
    "--port", type=int, default=5005, help="服务器监听端口（默认: 5005）"
)
parser.add_argument("--debug", action="store_true", help="启用调试模式")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max file size

# 配置文件存储路径（将在 main 函数中根据参数设置）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = None  # 将在 main 中设置
CATEGORIES_FILE = None  # 将在 main 中设置
READING_LIST_FILE = None  # 将在 main 中设置
GENERAL_SETTINGS_FILE = None  # 将在 main 中设置
# 不再使用统一的papers_db.json文件，改为每个PDF一个JSON文件

# 默认通用设置
DEFAULT_GENERAL_SETTINGS = {
    "reading_list_max_items": 100,
}

# 全局变量（将在 init_app 中初始化）
init_categories = None
get_categories = None
save_categories = None
create_category_folder = None
find_category_node = category_manager.find_category_node
get_category_path = category_manager.get_category_path
add_pdf_counts_to_categories = category_manager.add_pdf_counts_to_categories
get_category_pdf_count = category_manager.get_category_pdf_count

get_papers_in_category = None
get_paper_json_path = paper_repository.get_paper_json_path
save_paper_metadata = paper_repository.save_paper_metadata
load_paper_metadata = paper_repository.load_paper_metadata
delete_paper_files = paper_repository.delete_paper_files
scan_papers_in_directory = paper_repository.scan_papers_in_directory


def init_app(papers_dir=None):
    """初始化应用配置和目录"""
    global UPLOAD_FOLDER, CATEGORIES_FILE, READING_LIST_FILE, GENERAL_SETTINGS_FILE
    global init_categories, get_categories, save_categories, create_category_folder, get_papers_in_category

    # 设置论文目录
    if papers_dir:
        # 如果指定了相对路径，则相对于当前工作目录
        if not os.path.isabs(papers_dir):
            UPLOAD_FOLDER = os.path.abspath(papers_dir)
        else:
            UPLOAD_FOLDER = papers_dir
    else:
        UPLOAD_FOLDER = os.path.join(BASE_DIR, "papers")

    # 配置文件都放在论文目录下
    CATEGORIES_FILE = os.path.join(UPLOAD_FOLDER, "categories.json")
    READING_LIST_FILE = os.path.join(UPLOAD_FOLDER, "reading_list.json")
    GENERAL_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "general_settings.json")

    # 确保必要的目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # 初始化待读列表文件
    if not os.path.exists(READING_LIST_FILE):
        with open(READING_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"papers": []}, f, ensure_ascii=False, indent=2)

    # 初始化通用设置文件
    if not os.path.exists(GENERAL_SETTINGS_FILE):
        with open(GENERAL_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_GENERAL_SETTINGS, f, ensure_ascii=False, indent=2)

    # 基础工具函数绑定
    init_categories = partial(category_manager.init_categories, CATEGORIES_FILE)
    get_categories = partial(category_manager.get_categories, CATEGORIES_FILE)
    save_categories = partial(category_manager.save_categories, CATEGORIES_FILE)
    create_category_folder = partial(
        category_manager.create_category_folder, UPLOAD_FOLDER
    )
    get_papers_in_category = partial(
        paper_repository.get_papers_in_category, UPLOAD_FOLDER
    )

    print(f"论文目录: {UPLOAD_FOLDER}")
    print(f"分类配置: {CATEGORIES_FILE}")
    print(f"待读列表: {READING_LIST_FILE}")
    print(f"通用设置: {GENERAL_SETTINGS_FILE}")


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


@app.route("/")
def index():
    return render_template("index.html")


def register_routes():
    """注册所有路由（必须在 init_app 之后调用）"""
    register_category_routes(
        app,
        get_categories=get_categories,
        save_categories=save_categories,
        find_category_node=find_category_node,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        add_pdf_counts_to_categories=add_pdf_counts_to_categories,
        get_category_pdf_count=get_category_pdf_count,
        paper_store=paper_store,
        upload_folder=UPLOAD_FOLDER,
    )

    register_search_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        upload_folder=UPLOAD_FOLDER,
    )

    register_settings_routes(
        app,
        settings_file_path=GENERAL_SETTINGS_FILE,
        default_settings=DEFAULT_GENERAL_SETTINGS,
    )

    register_paper_operation_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        find_category_node=find_category_node,
        get_papers_in_category=get_papers_in_category,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        get_paper_json_path=get_paper_json_path,
        delete_paper_files=delete_paper_files,
        extract_pdf_metadata=None,  # 不再需要，使用新的 upload_paper 模块
        search_arxiv_by_title=None,  # 不再需要，使用新的 upload_paper 模块
        reading_list_file=READING_LIST_FILE,
        upload_folder=UPLOAD_FOLDER,
        general_settings_file=GENERAL_SETTINGS_FILE,
        default_settings=DEFAULT_GENERAL_SETTINGS,
        paper_store=paper_store,
    )

    register_upload_from_pdf_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        paper_store=paper_store,
    )

    register_update_from_url_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        paper_store=paper_store,
    )

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
    paper_title = None
    paper = paper_store.get(paper_id)
    if paper:
        paper_title = paper.title or paper.filename or paper.original_filename
    return render_template(
        "pdf_viewer.html",
        paper_id=paper_id,
        use_chinese=use_chinese,
        paper_title=paper_title,
    )


@app.route("/viewer/analysis/<paper_id>")
def analysis_viewer(paper_id):
    """AI 解读 Markdown 全屏查看页面"""
    return render_template("analysis_viewer.html", paper_id=paper_id)


if __name__ == "__main__":
    # 解析命令行参数
    args = parser.parse_args()

    # 初始化应用（配置论文目录等）
    init_app(papers_dir=args.papers_dir)

    # 注册路由（必须在 init_app 之后）
    register_routes()

    # 初始化分类系统
    init_categories()

    # 论文数据现在直接存储在PDF文件旁边的JSON文件中
    print(f"启动服务器: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
