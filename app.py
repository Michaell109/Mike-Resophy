import argparse
import json
import os
import threading
from datetime import datetime
from functools import partial
from typing import Optional

from flask import Flask, jsonify, render_template, request

from core.base_paper import Paper
from core.paper_store import paper_store
from core.search_index import SearchIndex
from routes.agent_routes.agent_summary_route import register_agent_summary_routes
from routes.agent_routes.agent_translate_route import register_agent_translate_routes
from routes.basic_routes.category_tree_route import register_category_routes
from routes.basic_routes.daily_arxiv_route import register_daily_arxiv_routes
from routes.basic_routes.export_route import register_export_routes
from routes.basic_routes.import_route import register_import_routes
from routes.basic_routes.institution_mapping_route import (
    register_institution_mapping_routes,
)
from routes.basic_routes.paper_operation_route import register_paper_operation_routes
from routes.basic_routes.search_route import register_search_routes
from routes.basic_routes.settings_route import register_settings_routes
from routes.basic_routes.update_from_url_route import register_update_from_url_routes
from routes.basic_routes.upload_from_pdf_route import register_upload_from_pdf_routes
from tools.basic_tools import category_manager, paper_repository

# 解析命令行参数
parser = argparse.ArgumentParser(description="PaperAgent - 论文管理与阅读系统")
parser.add_argument(
    "--papers-dir",
    type=str,
    default="./test_papers",
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
USER_SETTINGS_FILE = None  # 用户设置（名字、头像等）
READING_HISTORY_FILE = None  # 每日阅读历史
AGENTIC_SETTINGS_FILE = None  # AI 功能设置（统一的LLM配置）
DAILY_ARXIV_SETTINGS_FILE = None  # Daily arXiv 设置
AVATARS_DIR = None  # 头像图片目录
TEMP_PAPERS_DIR = None  # Daily arXiv 临时论文目录
READING_LIST_TEMP_DIR = None  # 待读列表临时论文目录
SEARCH_INDEX_DB = None  # 搜索索引数据库路径
search_index = None  # 搜索索引实例
# 不再使用统一的papers_db.json文件，改为每个PDF一个JSON文件

# 默认用户设置
DEFAULT_USER_SETTINGS = {
    "name": "Paper Reader",
    "avatar": None,  # 头像文件名，如 "avatar.jpg"
    "heatmapColorScheme": "green",
    "onboardingDontShow": False,  # 是否不再显示新手教程
}

# 默认 Agentic 设置（统一的AI功能配置）
DEFAULT_AGENTIC_SETTINGS = {
    "llmModel": "",  # LLM 模型名称
    "llmBaseUrl": "",  # LLM API 基础 URL
    "llmApiKey": "",  # LLM API 密钥
    "mineruServerUrl": "",  # PDF 解析服务地址
    "analysisSystemPrompt": "",  # AI 解读的系统提示词
}

# 默认 Daily arXiv 设置
DEFAULT_DAILY_ARXIV_SETTINGS = {
    "categories": ["cs.CV"],  # arXiv 分区列表
    "checkIntervalMinutes": 30,  # 检查间隔（分钟）
    "retentionDays": 2,  # 保留论文天数
    "maxKeywords": 2,  # 最多关键词数量（1-3）
    "keywordList": [
        "LLM",
        "MLLM",
        "Agent",
        "Image Generation",
        "Video Generation",
        "3D Generation",
        "2D Perception",
        "3D Perception",
        "Embodied AI & Robotics",
        "Audio & Speech",
        "ML Fundamentals & RL",
    ],  # 关键词列表
    "affiliationPrompt": """I will provide you with the first-page information of a paper. You need to extract all affiliations (institution names) from it and also extract the homepage and GitHub repo URL if there is. For affiliations, do not include author names. If an affiliation includes details such as region, department, school, or college, those should be omitted. Only keep the main institution name (e.g., School of Computer Science, Fudan University → Fudan University).

Additional rules:

If the institution is well-known and has a commonly used abbreviation (e.g., University of Illinois Urbana–Champaign → UIUC), return the abbreviation instead of the full name. If the institution is not well-known or does not have a standard abbreviation, keep the full name.

You must also return the nationality (country) for each affiliation, in the same order.

Output the result directly in JSON format, and make sure it is valid JSON. The structure should be:

{
"affiliations": ["Affiliation1", "Affiliation2", ...],
"countries": ["Country_of_Affiliation1", "Country_of_Affiliation2", ...],
"homepage": "homepage_url_or_null",
"github": "github_url_or_null"
}

Notes:
1. If there is no homepage or github url, use the JSON value null (not the string "null" and not Python None).
2. Do NOT add a trailing comma after the last field.
3. Do not include any explanation or extra text, only output the JSON object.

Now the input is:
""",
    "summaryPrompt": """我会给你一篇 AI 文章的英文摘要，以及一个可选关键词列表（英文）。你需要：

用中文简要总结这篇文章在解决什么问题、如何解决的，字数控制在 100-200 字。

从我提供的关键词列表中挑选最能代表文章类型的关键词（英文）

按如下 JSON 格式输出结果：

{"summary": "这篇文章主要解决...的问题。作者提出...方法，通过...实现了...", "keywords": ["Keyword"]}

注意

summary 必须中文，简洁、客观。

keywords 必须来自我提供的关键词列表：[{keyword_list}], 最多{max_keywords}个关键词。一定要是符合这篇文章的关键词，不能随意猜测。

直接输出 JSON，不要有其他解释。

现在输入的摘要是：
""",
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
load_paper_metadata = paper_repository.load_paper_metadata
scan_papers_in_directory = paper_repository.scan_papers_in_directory


def save_paper_metadata(pdf_path: str, paper_data) -> None:
    """保存论文元数据并更新搜索索引"""
    paper_repository.save_paper_metadata(pdf_path, paper_data)

    # 更新搜索索引
    if search_index:
        try:
            if isinstance(paper_data, Paper):
                paper = paper_data
            else:
                paper = Paper.from_dict(paper_data) if paper_data else None

            if paper:
                # 优先从 paper_store 获取最新的分类ID（最准确）
                category_id = None
                entry = paper_store.get_entry(paper.id)
                if entry:
                    category_id = entry.category_id

                # 如果 paper_store 中没有，尝试从论文数据获取
                if not category_id:
                    if hasattr(paper, "category_id") and paper.category_id:
                        category_id = paper.category_id
                    elif isinstance(paper_data, dict):
                        category_id = paper_data.get("category_id")

                search_index.index_paper(paper, category_id)
        except Exception as e:
            print(f"更新搜索索引失败: {e}")


def delete_paper_files(pdf_path: str) -> None:
    """删除论文文件并从搜索索引中移除"""
    # 先获取论文ID（如果可能）
    paper_id = None
    try:
        paper = load_paper_metadata(pdf_path)
        if paper:
            paper_id = paper.id
    except Exception:
        pass

    # 删除文件
    paper_repository.delete_paper_files(pdf_path)

    # 从搜索索引中删除
    if paper_id and search_index:
        try:
            search_index.remove_paper(paper_id)
        except Exception as e:
            print(f"从搜索索引删除失败: {e}")


def init_app(papers_dir=None):
    """初始化应用配置和目录"""
    global UPLOAD_FOLDER, CATEGORIES_FILE, READING_LIST_FILE
    global USER_SETTINGS_FILE, READING_HISTORY_FILE, AGENTIC_SETTINGS_FILE, AVATARS_DIR
    global DAILY_ARXIV_SETTINGS_FILE, TEMP_PAPERS_DIR, READING_LIST_TEMP_DIR
    global SEARCH_INDEX_DB, search_index
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
    USER_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "user_settings.json")
    READING_HISTORY_FILE = os.path.join(UPLOAD_FOLDER, "reading_history.json")
    AGENTIC_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "agentic_settings.json")
    DAILY_ARXIV_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "daily_arxiv_settings.json")
    AVATARS_DIR = os.path.join(UPLOAD_FOLDER, ".avatars")
    TEMP_PAPERS_DIR = os.path.join(UPLOAD_FOLDER, ".daily_arxiv_temp")
    READING_LIST_TEMP_DIR = os.path.join(UPLOAD_FOLDER, "_ReadingListTemp")
    SEARCH_INDEX_DB = os.path.join(UPLOAD_FOLDER, ".search_index.db")

    # 确保必要的目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(AVATARS_DIR, exist_ok=True)
    os.makedirs(TEMP_PAPERS_DIR, exist_ok=True)
    os.makedirs(READING_LIST_TEMP_DIR, exist_ok=True)

    # 初始化搜索索引
    search_index = SearchIndex(SEARCH_INDEX_DB)

    # 初始化待读列表文件
    if not os.path.exists(READING_LIST_FILE):
        with open(READING_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"papers": []}, f, ensure_ascii=False, indent=2)

    # 初始化用户设置文件
    if not os.path.exists(USER_SETTINGS_FILE):
        with open(USER_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_USER_SETTINGS, f, ensure_ascii=False, indent=2)

    # 初始化阅读历史文件
    if not os.path.exists(READING_HISTORY_FILE):
        with open(READING_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

    # 初始化 Agentic 设置文件（统一的AI功能配置）
    if not os.path.exists(AGENTIC_SETTINGS_FILE):
        with open(AGENTIC_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_AGENTIC_SETTINGS, f, ensure_ascii=False, indent=2)

    # 初始化 Daily arXiv 设置文件
    if not os.path.exists(DAILY_ARXIV_SETTINGS_FILE):
        with open(DAILY_ARXIV_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DAILY_ARXIV_SETTINGS, f, ensure_ascii=False, indent=2)

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
    print(f"用户设置: {USER_SETTINGS_FILE}")
    print(f"阅读历史: {READING_HISTORY_FILE}")
    print(f"AI功能设置: {AGENTIC_SETTINGS_FILE}")
    print(f"Daily arXiv设置: {DAILY_ARXIV_SETTINGS_FILE}")
    print(f"头像目录: {AVATARS_DIR}")
    print(f"Daily arXiv临时目录: {TEMP_PAPERS_DIR}")
    print(f"搜索索引数据库: {SEARCH_INDEX_DB}")


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
        search_index=search_index,
    )

    # 先注册 Daily arXiv 路由，获取 manager 实例
    from tools.basic_tools.daily_arxiv import get_manager

    daily_arxiv_manager = get_manager(TEMP_PAPERS_DIR, DAILY_ARXIV_SETTINGS_FILE)

    # 设置 LLM 配置回调
    def get_llm_config():
        try:
            with open(AGENTIC_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    daily_arxiv_manager.set_llm_config_callback(get_llm_config)

    # 检查 LLM 配置是否完整
    def is_llm_configured() -> bool:
        llm_config = get_llm_config()
        return bool(
            llm_config.get("llmBaseUrl")
            and llm_config.get("llmApiKey")
            and llm_config.get("llmModel")
        )

    # 启动 Daily arXiv 的回调函数
    def start_daily_arxiv_if_configured():
        """如果 LLM 配置完整，启动 Daily arXiv 调度器"""
        if is_llm_configured() and not daily_arxiv_manager._scheduler_running:
            daily_arxiv_manager.start_scheduler()
            print("[DailyArxiv] LLM 配置已完整，调度器已启动")

    # 只有在 LLM 配置完整时才启动调度器
    if is_llm_configured():
        daily_arxiv_manager.start_scheduler()
        print("[DailyArxiv] LLM 配置已完整，调度器已启动")
    else:
        print(
            "[DailyArxiv] LLM 配置不完整，调度器未启动。请在设置中配置 LLM API 后手动启动。"
        )

    register_daily_arxiv_routes(
        app,
        daily_arxiv_settings_file=DAILY_ARXIV_SETTINGS_FILE,
        default_daily_arxiv_settings=DEFAULT_DAILY_ARXIV_SETTINGS,
        temp_papers_dir=TEMP_PAPERS_DIR,
        get_categories=get_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        reading_list_temp_dir=READING_LIST_TEMP_DIR,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_settings_routes(
        app,
        user_settings_file=USER_SETTINGS_FILE,
        default_user_settings=DEFAULT_USER_SETTINGS,
        reading_history_file=READING_HISTORY_FILE,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
        default_agentic_settings=DEFAULT_AGENTIC_SETTINGS,
        avatars_dir=AVATARS_DIR,
        start_daily_arxiv_callback=start_daily_arxiv_if_configured,
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
        reading_list_temp_dir=READING_LIST_TEMP_DIR,
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
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_agent_translate_routes(
        app,
        translation_tasks=translation_tasks,
        translation_tasks_lock=translation_tasks_lock,
        get_categories=get_categories,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        save_paper_metadata=save_paper_metadata,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_import_routes(
        app,
        get_categories=get_categories,
        save_categories=save_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        paper_store=paper_store,
        upload_folder=UPLOAD_FOLDER,
    )

    register_export_routes(
        app,
        papers_dir=UPLOAD_FOLDER,
    )

    register_institution_mapping_routes(
        app,
        daily_arxiv_settings_file=DAILY_ARXIV_SETTINGS_FILE,
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

    # 重建搜索索引（在后台线程中执行，避免阻塞启动）
    def rebuild_search_index():
        """在后台线程中重建搜索索引"""
        import threading
        import time

        def _rebuild():
            time.sleep(1)  # 等待1秒，确保其他初始化完成
            print("开始重建搜索索引...")
            try:
                categories = get_categories()
                papers_with_categories = []

                def collect_papers(node, category_path):
                    """递归收集所有论文"""
                    node_path = get_category_path(categories, node.get("id"))
                    if node_path and len(node_path) > 1:
                        directory_path = os.path.join(UPLOAD_FOLDER, *node_path[1:])
                        if os.path.exists(directory_path):
                            papers = scan_papers_in_directory(
                                directory_path,
                                category_id=node.get("id"),
                                category_path=node_path,
                            )
                            for paper in papers:
                                papers_with_categories.append((paper, node.get("id")))

                    for child in node.get("children", []):
                        collect_papers(child, node_path or [])

                for child in categories.get("children", []):
                    collect_papers(child, [])

                if papers_with_categories:
                    print(
                        f"开始重建搜索索引，共 {len(papers_with_categories)} 篇论文..."
                    )
                    search_index.rebuild_index(papers_with_categories)
                    # 完成信息已在 rebuild_index 内部输出，这里不再重复
                else:
                    print("没有找到论文，跳过索引重建")
            except Exception as e:
                print(f"重建搜索索引失败: {e}")
                import traceback

                traceback.print_exc()

        thread = threading.Thread(target=_rebuild, daemon=True)
        thread.start()

    # 设置重建索引回调（在定义 rebuild_search_index 之后）
    if search_index:
        search_index.set_rebuild_callback(rebuild_search_index)

    # 重建搜索索引
    rebuild_search_index()

    # 添加获取 papers 目录路径的 API
    @app.route("/api/papers-dir", methods=["GET"])
    def get_papers_dir():
        """获取 papers 目录的绝对路径"""
        return jsonify({"success": True, "path": os.path.abspath(UPLOAD_FOLDER)})

    # 论文数据现在直接存储在PDF文件旁边的JSON文件中
    print(f"启动服务器: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
