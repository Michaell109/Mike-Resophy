from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store

PaperList = List[Paper]
CategoryPath = List[str]


@dataclass
class AnalysisDependencies:
    analysis_tasks: Dict[str, Dict[str, Any]]
    analysis_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def _build_paper_info_block(paper_title: str, paper_metadata: dict | None) -> str:
    """Build a markdown block with paper metadata to prepend before the markdown content."""
    if not paper_metadata:
        return ""

    parts = []
    if paper_title:
        parts.append(f"- **Title**: {paper_title}")
    if paper_metadata.get("authors"):
        parts.append(f"- **Authors**: {paper_metadata['authors']}")
    if paper_metadata.get("affiliation"):
        parts.append(f"- **Affiliation**: {paper_metadata['affiliation']}")
    if paper_metadata.get("journal"):
        parts.append(f"- **Venue**: {paper_metadata['journal']}")
    if paper_metadata.get("year"):
        parts.append(f"- **Year**: {paper_metadata['year']}")
    if paper_metadata.get("arxiv_published_date"):
        parts.append(f"- **arXiv Date**: {paper_metadata['arxiv_published_date']}")
    elif paper_metadata.get("arxiv_url"):
        parts.append(f"- **arXiv**: {paper_metadata['arxiv_url']}")
    if paper_metadata.get("homepage"):
        parts.append(f"- **Project**: {paper_metadata['homepage']}")
    if paper_metadata.get("github"):
        parts.append(f"- **GitHub**: {paper_metadata['github']}")

    if not parts:
        return ""

    return "\n".join(parts) + "\n\n"


def _inject_images_to_result(result_content: str, markdown_content: str) -> str:
    """Inject images from the original MinerU markdown into the LLM-generated result.

    Uses a two-pass strategy:
    Pass 1 — Match images with explicit figure captions (Fig. N / 图N) to the
             corresponding figure references in the result.
    Pass 2 — For any remaining figure references (图N) in the result that weren't
             filled, fill them with images in MinerU document order as a fallback.
    """
    if not markdown_content:
        return result_content

    # Check if the LLM already embedded images
    if "![](images/" in result_content:
        return result_content

    lines = markdown_content.split("\n")

    # ------------------------------------------------------------------
    # Pass 1: match images to figure captions
    # ------------------------------------------------------------------
    # Collect all figure-number references from the result (e.g. 图1, 图2)
    fig_refs_in_result = set()
    for m in re.finditer(r"图\s*(\d+)", result_content):
        fig_refs_in_result.add(m.group(1))

    # Determine which images in MinerU are inside <details> or followed by it
    is_details_image = [False] * len(lines)
    for i, line in enumerate(lines):
        if "<details>" in line or not line.startswith("![](images/"):
            continue
        next_text = "".join(lines[i + 1 : min(i + 4, len(lines))])
        if "<details>" in next_text:
            is_details_image[i] = True

    figure_images: dict[str, list[str]] = {}
    # Collect ALL standalone images (including <details> ones) in order
    all_standalone_images: list[str] = []
    # Collect only "clean" standalone images (not details, not text_image)
    clean_standalone_images: list[str] = []

    for i, line in enumerate(lines):
        m = re.match(
            r"!\[\]\(images/([^)]+\.(?:jpg|jpeg|png|gif|webp))\)",
            line,
        )
        if not m:
            continue

        img_path = f"images/{m.group(1)}"
        all_standalone_images.append(img_path)

        # Skip images inside <details>
        if "<details>" in line or is_details_image[i]:
            # Only include if it's NOT a text_image or natural_image
            next_text = "".join(lines[i + 1 : min(i + 5, len(lines))])
            if "text_image" in next_text or "natural_image" in next_text:
                continue
            clean_standalone_images.append(img_path)
            continue

        clean_standalone_images.append(img_path)

        # Try figure-caption matching (same line or next 5 lines)
        rest = line[m.end():]
        caption_m = re.search(
            r"(?:Fig(?:ure)?\.?\s*(\d+)|图\s*(\d+)[\s：:])",
            rest, re.IGNORECASE,
        )
        if caption_m:
            fig_num = caption_m.group(1) or caption_m.group(2)
            figure_images.setdefault(fig_num, []).append(img_path)
            continue

        for j in range(i + 1, min(i + 6, len(lines))):
            caption_m = re.search(
                r"(?:Fig(?:ure)?\.?\s*(\d+)|图\s*(\d+)[\s：:])",
                lines[j], re.IGNORECASE,
            )
            if caption_m:
                fig_num = caption_m.group(1) or caption_m.group(2)
                figure_images.setdefault(fig_num, []).append(img_path)
                break

    result = result_content

    # Inject images matched by figure caption
    matched_refs = set()
    for fig_num in sorted(
        figure_images.keys(), key=lambda x: int(x) if x.isdigit() else 999
    ):
        img_paths = figure_images[fig_num]
        img_placeholder = "\n\n" + "\n".join(f"![]({p})" for p in img_paths) + "\n\n"

        for ref_text, ref_pat in [
            (f"图{fig_num}", rf'(图\s*{fig_num})'),
            (f"Fig. {fig_num}", rf'(Fig(?:ure)?\.?\s*{fig_num}\b)'),
            (f"Figure {fig_num}", rf'(Figure\s+{fig_num}\b)'),
        ]:
            ref_match = re.search(ref_pat, result)
            if ref_match:
                pos = ref_match.start()
                if "![](" in result[max(0, pos - 150) : pos]:
                    continue
                result = result[:pos] + img_placeholder + result[pos:]
                matched_refs.add(fig_num)
                break

    # ------------------------------------------------------------------
    # Pass 2: fill remaining figure references with unmatched images
    # ------------------------------------------------------------------
    matched_images_in_pass1 = set()
    for paths in figure_images.values():
        for p in paths:
            matched_images_in_pass1.add(p)

    unused_clean = [p for p in clean_standalone_images if p not in matched_images_in_pass1]
    unused_clean.reverse()  # pop from end for easy iteration

    # Find unfilled figure references in the result
    unfilled_refs = sorted(
        [r for r in fig_refs_in_result if r not in matched_refs],
        key=int,
    )

    # For each unfilled reference, take the next unused image (in MinerU order)
    # and inject it. We scan refs in numeric order and images in document order.
    for fig_num in unfilled_refs:
        if not unused_clean:
            break
        # Pick the next unused image (earliest in document order = last in reversed list)
        img_path = unused_clean.pop()
        img_md = f"\n\n![]({img_path})\n\n"

        for ref_text, ref_pat in [
            (f"图{fig_num}", rf'(图\s*{fig_num})'),
        ]:
            ref_match = re.search(ref_pat, result)
            if ref_match:
                pos = ref_match.start()
                result = result[:pos] + img_md + result[pos:]
                break

    return result


def analyze_paper_task(
    task_id: str,
    paper_id: str,
    pdf_path: str,
    pdf_dir: str,
    pdf_filename: str,
    mineru_config: dict,
    openai_base_url: str,
    openai_api_key: str,
    system_prompt: str,
    ai_language: str,
    deps: AnalysisDependencies,
    paper_metadata: dict | None = None,
    llm_model_name: str | None = None,
) -> None:
    """Background AI interpretation task - two steps: PDF2MD -> LLM interpretation."""
    # If no system_prompt is provided, select language-specific default prompt.
    if not system_prompt:
        # Chinese default prompt
        zh_prompt = """请以中文 markdown 的形式为这篇论文撰写一篇结构清晰、内容详尽的技术解读文章。

文章开头必须先输出论文信息头（如果输入中提供了论文信息），格式如下：
> **Title**: 论文标题
> **Authors**: 作者列表
> **Affiliation**: 机构列表
> **Venue**: 会议/期刊名称
> **Year**: 发表年份
> **arXiv Date**: arXiv发布日期
> **Project**: 项目主页链接
> **GitHub**: GitHub仓库链接

然后按以下三个部分撰写正文：

## 1. 研究动机
详细阐述本文要解决的问题是什么，现有的方法存在哪些痛点和不足，为什么这个问题值得研究。不要一笔带过，要让读者理解问题的来龙去脉。

## 2. 方法详解
这是文章的核心部分，请详细讲解本文提出的方法：
- 整体框架和核心思路
- 每个关键模块的作用和工作方式
- **必须保留原文中的所有重要公式**（使用原始 LaTeX 格式），并逐一解释每个公式的含义和其中各符号的物理意义。**所有 LaTeX 公式必须用 `$...$` 包裹（行内公式）或 `$$...$$` 包裹（独立公式行）**，例如：行内公式 $x_{\tau} = (1 - \tau) x_{0}$，独立公式 $$x_{\tau} = (1 - \tau) \cdot x_{0} + \tau \cdot z$$
- 关键设计选择的理由
- 如果有模型结构图、流程图等，必须插入到对应位置
- **如果论文包含算法（Algorithm），必须将算法伪代码完整呈现**，使用普通文本格式（行号用"数字:"格式），不要使用代码块包裹。同时必须对算法的整体流程和每一步的作用进行详细文字说明，帮助读者理解算法的输入输出、核心步骤和关键技巧

## 3. 实验结果
充分展示实验内容，包括：
- 主要实验结果和对比
- 消融实验及其分析
- 重要的结果图、表格必须插入到对应位置

注意：
- 图片（模型结构、teaser、结果图、阐释图等）必须直接插入到正文对应位置，不要放到最后
- 公式必须保留原始 LaTeX 格式，不要省略或简化。所有公式必须用 `$...$`（行内）或 `$$...$$`（独立行）包裹
- 算法伪代码**不要使用代码块**（```）包裹，必须使用普通文本格式呈现，行号用"数字:"格式，这样LaTeX公式才能正确渲染。例如：
  1: $\mathbf{z}_t^0 \gets \mathrm{VAE_{enc}}(\mathbf{o}_t)$ ▷ 编码观测
  2: $\tau_v \sim \mathcal{U}[0,1]$ ▷ 采样时间步
- 内容要详细充分，不要过度压缩

INPUT: <MARKDOWN>"""

        # English default prompt
        en_prompt = """Please write a structured, detailed technical review of this paper in English Markdown format.

At the beginning of the article, you must output a paper information header (if provided in the input), in the following format:
> **Title**: Paper title
> **Authors**: Author list
> **Affiliation**: Affiliation list
> **Venue**: Conference/Journal name
> **Year**: Publication year
> **arXiv Date**: arXiv publication date
> **Project**: Project homepage URL
> **GitHub**: GitHub repository URL

Then write the review covering the following three sections:

## 1. Motivation
Explain in detail what problem this paper addresses, what are the pain points and limitations of existing methods, and why this problem is worth studying. Do not gloss over this — help the reader understand the full context of the problem.

## 2. Method Details
This is the core section. Provide a detailed explanation of the proposed method:
- Overall framework and core ideas
- The role and mechanism of each key module
- **All important formulas from the original paper must be preserved** (in original LaTeX format), with explanations of each formula's meaning and the physical significance of each symbol. **All LaTeX formulas MUST be wrapped with `$...$` for inline math or `$$...$$` for display math**, e.g.: inline $x_{\tau} = (1 - \tau) x_{0}$, display $$x_{\tau} = (1 - \tau) \cdot x_{0} + \tau \cdot z$$
- Rationale behind key design choices
- If there are model architecture diagrams, flowcharts, etc., they must be inserted at the corresponding positions
- **If the paper contains algorithms, the full pseudocode must be presented** using plain text format with line numbers in "number:" format (NOT wrapped in code blocks). Additionally, you must provide a detailed textual explanation of the algorithm's overall flow, the purpose of each step, its inputs/outputs, and any key techniques or tricks used

## 3. Experimental Results
Provide comprehensive coverage of the experiments, including:
- Main results and comparisons
- Ablation studies and their analysis
- Important result figures and tables must be inserted at the corresponding positions

Notes:
- Images (model architecture, teaser, results, explanatory diagrams, etc.) must be inserted directly at the corresponding positions in the text, not placed at the end
- Formulas must be preserved in their original LaTeX format — do not omit or oversimplify them. All formulas MUST be wrapped with `$...$` (inline) or `$$...$$` (display)
- Algorithm pseudocode **MUST NOT be wrapped in code blocks** (```). Use plain text format with line numbers in "number:" format so that LaTeX formulas render correctly. For example:
  1: $\mathbf{z}_t^0 \gets \mathrm{VAE_{enc}}(\mathbf{o}_t)$ ▷ Encode observation
  2: $\tau_v \sim \mathcal{U}[0,1]$ ▷ Sample timestep
- Content should be detailed and thorough — do not over-compress

INPUT: <MARKDOWN>"""

        if ai_language and ai_language.lower().startswith("zh"):
            system_prompt = zh_prompt
        else:
            system_prompt = en_prompt

    start_time = datetime.now()  # Recording start time
    with deps.analysis_tasks_lock:
        task_info = deps.analysis_tasks[task_id]
        task_info["status"] = "running"
        task_info["step"] = "pdf2md"
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None

    def read_output(pipe, label):
        """Read subprocess output in real time"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    print(f"[{label}] {line}")
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
        except Exception as e:  # noqa: BLE001
            print(f"Error while reading output: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["step"] = "pdf2md"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("Step one: start toPDFparsed asMarkdown...")
                log_lines.append("=" * 50)

        base_name = os.path.splitext(pdf_filename)[0]
        pdf_output_dir = os.path.join(pdf_dir, "outputs", base_name, "vlm")

        # Check if using API mode or local CLI mode
        use_api = mineru_config.get("useApi", False)

        if use_api:
            # API Mode: Use MinerU cloud API
            with log_lock:
                log_lines.append("Using MinerU Cloud API mode")

            from resophy.tools.basic_tools.mineru_api_client import MinerUAPIClient

            api_token = mineru_config.get("apiToken", "")
            if not api_token:
                raise Exception("MinerU API token is not configured")

            client = MinerUAPIClient(api_token)

            # Progress callback
            def on_progress(state, extracted_pages, total_pages):
                with log_lock:
                    if state == "waiting-file":
                        log_lines.append("Waiting for file upload...")
                    elif state == "pending":
                        log_lines.append("In queue...")
                    elif state == "running":
                        log_lines.append(
                            f"Parsing progress: {extracted_pages}/{total_pages} pages"
                        )
                    elif state == "converting":
                        log_lines.append("Format converting...")

            # Create output directory
            os.makedirs(pdf_output_dir, exist_ok=True)

            # Parse PDF to Markdown using API
            md_file = client.parse_pdf_to_markdown(
                pdf_path=pdf_path,
                output_dir=pdf_output_dir,
                progress_callback=on_progress,
            )

            if not md_file:
                raise Exception("API parsing failed")

            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append(
                    "The first step is completed:PDFhas been parsed asMarkdown"
                )
                log_lines.append(f"Markdowndocument: {md_file}")
                log_lines.append("=" * 50)
        else:
            # Local CLI Mode: Use mineru command
            with log_lock:
                log_lines.append("Using Local MinerU CLI mode")

            mineru_server_url = mineru_config.get("serverUrl", "")
            if not mineru_server_url:
                raise Exception("MinerU Server URL is not configured")

            os.chdir(pdf_dir)

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

            print(f"implementPDF2MDOrder: {' '.join(cmd)}")
            print(f"working directory: {pdf_dir}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            with deps.analysis_tasks_lock:
                deps.analysis_tasks[task_id]["process"] = process

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

            return_code = process.wait(timeout=3600)

            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            if return_code != 0:
                raise Exception(f"PDF2MDfail (exit code: {return_code})")

            outputs_dir = os.path.join(pdf_dir, "outputs")

            if not os.path.exists(pdf_output_dir):
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
                raise Exception("not foundPDFparse output directory")

            with log_lock:
                log_lines.append(f"Find the output directory: {pdf_output_dir}")

            vlm_items = os.listdir(pdf_output_dir)
            md_file = None
            for item in vlm_items:
                item_path = os.path.join(pdf_output_dir, item)
                if item == "images" and os.path.isdir(item_path):
                    continue
                elif item.endswith(".md") and os.path.isfile(item_path):
                    md_file = item_path
                    continue
                else:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        with log_lock:
                            log_lines.append(f"delete directory: {item}")
                    else:
                        os.remove(item_path)
                        with log_lock:
                            log_lines.append(f"Delete files: {item}")

            if not md_file:
                raise Exception("Generated not foundMarkdowndocument")

            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append(
                    "The first step is completed:PDFhas been parsed asMarkdown"
                )
                log_lines.append(f"Markdowndocument: {md_file}")
                log_lines.append("=" * 50)

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["step"] = "llm_analysis"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("Step 2: StartLLMInterpretation...")
                log_lines.append("=" * 50)

        with open(md_file, "r", encoding="utf-8") as f:
            markdown_content = f.read()

        # 1. Remove # References Everything after (case insensitive)
        references_pattern = re.compile(
            r"^#\s+references?\s*$", re.IGNORECASE | re.MULTILINE
        )
        match = references_pattern.search(markdown_content)
        if match:
            markdown_content = markdown_content[: match.start()]
            with log_lock:
                log_lines.append(
                    f"Removed References part (from section {match.start()} characters starting)"
                )

        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        # Use the configured model name (e.g. deepseek-ai/DeepSeek-V3.2)
        # Only fallback to models.list() first model if no model is configured
        model = llm_model_name
        models = None
        if not model:
            try:
                models = client.models.list()
                model = models.data[0].id if models.data else None
                if not model:
                    raise Exception("Unable to get model list")
            except Exception as e:  # noqa: BLE001
                raise Exception(f"Failed to get model list: {str(e)}") from e

        # 2. Try to get the maximum length of the model (only truncate if successful)
        max_input_tokens = None
        try:
            # Try to get from model information context_length / max_model_len / max_tokens
            if models is None:
                try:
                    models = client.models.list()
                except Exception:  # noqa: BLE001
                    models = None
            model_info = None
            if models and models.data:
                for m in models.data:
                    if m.id == model:
                        model_info = m
                        break

            if model_info:
                # different API Provider field names may differ
                if hasattr(model_info, "context_length"):
                    max_input_tokens = model_info.context_length
                elif hasattr(model_info, "max_model_len"):
                    max_input_tokens = model_info.max_model_len
                elif hasattr(model_info, "max_tokens"):
                    max_input_tokens = model_info.max_tokens
        except Exception as e:  # noqa: BLE001
            with log_lock:
                log_lines.append(
                    f"Unable to get maximum length from model information: {e}, will skip the truncation logic"
                )

        # Only after successfully obtaining max_input_tokens Truncated only when；Otherwise, it will not be truncated at all.
        if max_input_tokens is not None:
            # Calculate the maximum number of text characters (token number * 3, rough estimate:1 token ≈ 3-4 character, conservatively 3）
            max_text_chars = max_input_tokens * 3

            # Estimate system_prompt The number of characters (excluding <MARKDOWN> placeholder)
            system_prompt_without_placeholder = system_prompt.replace("<MARKDOWN>", "")
            system_prompt_chars = len(system_prompt_without_placeholder)

            # calculate markdown Maximum number of characters allowed for content
            max_markdown_chars = (
                max_text_chars - system_prompt_chars - 100
            )  # Keep 100 character buffer

            original_markdown_length = len(markdown_content)
            if original_markdown_length > max_markdown_chars:
                # Truncate markdown content
                markdown_content = markdown_content[:max_markdown_chars]
                with log_lock:
                    log_lines.append(
                        f"Markdown Content is too long ({original_markdown_length} characters), truncated to {max_markdown_chars} character"
                    )
                    log_lines.append(
                        f"Model maximum input token: {max_input_tokens}, estimating the maximum number of text characters: {max_text_chars}"
                    )
            else:
                with log_lock:
                    log_lines.append(
                        f"Markdown content length: {original_markdown_length} characters, within limits (maximum: {max_markdown_chars} character)"
                    )
        else:
            with log_lock:
                log_lines.append(
                    "Failed to get maximum length from model information, will not be correct Markdown The content is truncated (there may be risks of overlength)"
                )

        # Inject paper metadata header before the markdown content
        paper_title = None
        if paper_metadata:
            paper_title = paper_metadata.get("title")
        paper_info_block = _build_paper_info_block(paper_title, paper_metadata)
        prompt = system_prompt.replace("<MARKDOWN>", paper_info_block + markdown_content)
        messages = [{"role": "user", "content": prompt}]

        with log_lock:
            log_lines.append(f"Use model: {model}")
            log_lines.append("Start callingLLM API...")

        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
        )

        result_content = chat_completion.choices[0].message.content
        result_content = re.sub(
            r"<think>[\s\S]*?</think>", "", result_content, flags=re.IGNORECASE
        )

        # Inject images from original MinerU markdown into result
        result_content = _inject_images_to_result(result_content, markdown_content)

        result_file = os.path.join(pdf_output_dir, "result.md")
        result_temp = result_file + ".new"
        # Append model info to the paper information block at the top
        # Use the actual model returned by the API response, not the configured name
        display_model = chat_completion.model or model
        # Find the end of the blockquote header (last > line before a blank line or ## heading)
        model_line = f"> **Generated by**: {display_model}\n"
        # Insert after the last > line in the header block
        lines = result_content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith(">"):
                insert_idx = i + 1
        if insert_idx > 0:
            lines.insert(insert_idx, model_line)
            result_content = "\n".join(lines)
        else:
            result_content = model_line + "\n" + result_content
        # Write to .new first, then atomically rename — keeps old result.md
        # intact during re-analysis
        with open(result_temp, "w", encoding="utf-8") as f:
            f.write(result_content)
        os.replace(result_temp, result_file)

        with log_lock:
            log_lines.append("=" * 50)
            log_lines.append("The second step is completed:LLMInterpretation completed")
            log_lines.append(f"result file: {result_file}")
            log_lines.append("=" * 50)

        # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
            paper.mark_analysis_result(result_file)
            deps.save_paper_metadata(pdf_path, paper)
        else:
            # if paper_store Not found in , use recursive search of classification tree
            categories = deps.get_categories()

            def search_and_update_paper(node):
                category_path = deps.get_category_path(categories, node["id"])
                if category_path:
                    papers_list = deps.get_papers_in_category(node["id"], category_path)
                    for paper in papers_list:
                        if paper.id == paper_id:
                            paper.mark_analysis_result(result_file)
                            deps.save_paper_metadata(pdf_path, paper)
                            return True
                if "children" in node:
                    for child in node["children"]:
                        if search_and_update_paper(child):
                            return True
                return False

            for child in categories.get("children", []):
                if search_and_update_paper(child):
                    break

        end_time = datetime.now()
        analysis_duration = int((end_time - start_time).total_seconds())

        # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
            paper.analysis_time = max(
                getattr(paper, "analysis_time", 0), analysis_duration
            )
            path = paper.file_path
            if path and os.path.exists(path):
                deps.save_paper_metadata(path, paper)
        else:
            # if paper_store Not found in , use recursive search of classification tree
            categories = deps.get_categories()

            def search_and_update_analysis_time(node):
                category_path = deps.get_category_path(categories, node["id"])
                if category_path:
                    papers = deps.get_papers_in_category(node["id"], category_path)
                    for paper in papers:
                        if paper.id == paper_id:
                            paper.analysis_time = max(
                                getattr(paper, "analysis_time", 0), analysis_duration
                            )
                            path = paper.file_path
                            if path and os.path.exists(path):
                                deps.save_paper_metadata(path, paper)
                            return True
                if "children" in node:
                    for child in node["children"]:
                        if search_and_update_analysis_time(child):
                            return True
                return False

            for child in categories.get("children", []):
                if search_and_update_analysis_time(child):
                    break

        # Sync analysis results to duplicate papers across all directories
        try:
            from resophy.tools.basic_tools.paper_repository import (
                sync_results_to_duplicates,
            )

            entry = paper_store.get_entry(paper_id)
            if entry:
                sync_results_to_duplicates(
                    entry.paper, deps.save_paper_metadata
                )
        except Exception as e:  # noqa: BLE001
            print(f"[Sync] Failed to sync analysis to duplicates: {e}")

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "completed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": True,
                "result_file": result_file,
                "markdown_file": md_file,
            }

    except subprocess.TimeoutExpired:
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "failed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": "Interpretation timeout",
            }
        if process:
            process.kill()
    except Exception as e:  # noqa: BLE001
        print(f"An error occurred during interpretation: {str(e)}")
        import traceback

        traceback.print_exc()
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "failed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": f"Interpretation failed: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        os.chdir(original_cwd)
