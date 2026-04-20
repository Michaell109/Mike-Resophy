from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store

PaperList = List[Paper]
CategoryPath = List[str]

SYSTEM_PROMPT = """You are a professional academic paper translator. Translate the following English text to Chinese.

Rules:
1. Preserve ALL LaTeX formulas exactly as-is (both inline $...$ and display $$...$$)
2. Preserve ALL markdown formatting (headings, lists, bold, italic, links)
3. Preserve ALL image references exactly as-is, e.g. ![](images/xxx.jpg)
4. Do NOT translate figure/table numbers (e.g. "Figure 1" → "Figure 1", not "图1")
5. Keep technical terms accurate — use widely-accepted Chinese translations where they exist, otherwise keep the English term
6. Translate naturally and fluently, not word-by-word
7. Output ONLY the translated text, no explanations or notes
"""

# Max conversation tokens before reset (DeepSeek 64K context, leave headroom)
MAX_CONVERSATION_TOKENS = 50000
# Number of recent turns to keep when resetting conversation
RESET_KEEP_TURNS = 3


@dataclass
class BilingualDependencies:
    bilingual_tasks: Dict[str, Dict[str, Any]]
    bilingual_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def split_markdown_into_segments(md_text: str) -> List[Dict[str, str]]:
    """Split markdown into segments by headings and paragraphs.

    Each segment is a dict with 'type' ('heading' or 'paragraph') and 'content'.
    Heading segments include the heading line + all content until the next heading.
    """
    lines = md_text.split("\n")
    segments = []
    current_segment_lines = []
    current_type = "paragraph"

    for line in lines:
        is_heading = line.startswith("#")

        if is_heading and current_segment_lines:
            # Flush current segment
            content = "\n".join(current_segment_lines).strip()
            if content:
                segments.append({"type": current_type, "content": content})
            current_segment_lines = [line]
            current_type = "heading"
        else:
            if not current_segment_lines and is_heading:
                current_type = "heading"
            current_segment_lines.append(line)

    # Flush last segment
    if current_segment_lines:
        content = "\n".join(current_segment_lines).strip()
        if content:
            segments.append({"type": current_type, "content": content})

    # Merge small consecutive paragraphs into larger segments to reduce LLM calls
    merged = []
    buffer_lines = []
    buffer_type = "paragraph"

    for seg in segments:
        if seg["type"] == "heading":
            # Flush buffer
            if buffer_lines:
                merged.append({"type": buffer_type, "content": "\n\n".join(buffer_lines)})
                buffer_lines = []
            merged.append(seg)
            buffer_type = "paragraph"
        else:
            # If segment is short (likely a continuation), buffer it
            line_count = seg["content"].count("\n") + 1
            if line_count <= 3 and buffer_lines:
                buffer_lines.append(seg["content"])
            else:
                if buffer_lines:
                    merged.append({"type": buffer_type, "content": "\n\n".join(buffer_lines)})
                    buffer_lines = []
                buffer_lines = [seg["content"]]

    if buffer_lines:
        merged.append({"type": buffer_type, "content": "\n\n".join(buffer_lines)})

    return merged


def find_mineru_markdown(pdf_path: str) -> str | None:
    """Find the raw MinerU markdown file for a given PDF path."""
    pdf_dir = os.path.dirname(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    outputs_dir = os.path.join(pdf_dir, "outputs")

    if not os.path.exists(outputs_dir):
        return None

    # Try exact path first
    exact_md = os.path.join(outputs_dir, base_name, "vlm", f"{base_name}.md")
    if os.path.exists(exact_md):
        return exact_md

    # Search for any vlm directory
    for item in os.listdir(outputs_dir):
        item_path = os.path.join(outputs_dir, item)
        if os.path.isdir(item_path):
            vlm_dir = os.path.join(item_path, "vlm")
            if os.path.exists(vlm_dir):
                for f in os.listdir(vlm_dir):
                    if f.endswith(".md") and f != "result.md":
                        return os.path.join(vlm_dir, f)

    return None


def bilingual_translate_task(
    task_id: str,
    paper_id: str,
    pdf_path: str,
    openai_base_url: str,
    openai_api_key: str,
    llm_model: str,
    ai_language: str,
    deps: BilingualDependencies,
) -> None:
    """Background bilingual translation task."""
    start_time = datetime.now()
    with deps.bilingual_tasks_lock:
        task_info = deps.bilingual_tasks[task_id]
        task_info["status"] = "running"
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]

    def log(msg: str) -> None:
        print(f"[bilingual] {msg}")
        with log_lock:
            log_lines.append(msg)

    try:
        # Find MinerU markdown
        md_file = find_mineru_markdown(pdf_path)
        if not md_file:
            raise Exception(
                "MinerU markdown not found. Please run AI analysis first to parse the PDF."
            )

        log(f"Found MinerU markdown: {md_file}")

        # Read markdown content
        with open(md_file, "r", encoding="utf-8") as f:
            md_content = f.read()

        # Remove References section
        refs_pattern = re.compile(r"^#\s+references?\s*$", re.IGNORECASE | re.MULTILINE)
        match = refs_pattern.search(md_content)
        if match:
            md_content = md_content[: match.start()]
            log("Removed References section")

        # Split into segments
        segments = split_markdown_into_segments(md_content)
        log(f"Split into {len(segments)} segments")

        # Output path
        vlm_dir = os.path.dirname(md_file)
        bilingual_json_path = os.path.join(vlm_dir, "bilingual.json")

        # Initialize OpenAI client
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

        # Translate segments using multi-turn conversation for cache hit
        translated_segments = []
        conversation_messages = []  # Accumulated [user, assistant, user, assistant, ...]
        conversation_token_estimate = 0

        def estimate_tokens(text: str) -> int:
            # Rough estimate: ~1.5 tokens per Chinese char, ~1 token per English word
            return int(len(text) * 0.7)

        for i, segment in enumerate(segments):
            # Check if task was cancelled
            with deps.bilingual_tasks_lock:
                if deps.bilingual_tasks[task_id].get("status") == "cancelled":
                    log("Task cancelled")
                    return

            with log_lock:
                log_lines.append(f"Translating segment {i + 1}/{len(segments)}...")

            # Check if conversation is approaching token limit — reset if needed
            next_input_estimate = conversation_token_estimate + estimate_tokens(segment["content"])
            if next_input_estimate > MAX_CONVERSATION_TOKENS and len(conversation_messages) > RESET_KEEP_TURNS * 2:
                # Keep only the last RESET_KEEP_TURNS turns (pairs of user+assistant)
                keep_msg_count = RESET_KEEP_TURNS * 2
                kept = conversation_messages[-keep_msg_count:]
                conversation_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + kept
                conversation_token_estimate = sum(estimate_tokens(m["content"]) for m in conversation_messages)
                log(f"Conversation approaching limit, reset to last {RESET_KEEP_TURNS} turns")

            # Build messages for this call
            if not conversation_messages:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": segment["content"]},
                ]
            else:
                messages = conversation_messages + [{"role": "user", "content": segment["content"]}]

            try:
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=messages,
                    temperature=0.3,
                )
                translated = response.choices[0].message.content.strip()
            except Exception as e:
                log(f"Translation failed for segment {i + 1}: {e}")
                translated = f"[Translation failed: {e}]"

            # Update conversation history
            if not conversation_messages:
                conversation_messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": segment["content"]},
                    {"role": "assistant", "content": translated},
                ]
            else:
                conversation_messages.append({"role": "user", "content": segment["content"]})
                conversation_messages.append({"role": "assistant", "content": translated})
            conversation_token_estimate += estimate_tokens(segment["content"]) + estimate_tokens(translated)

            translated_segments.append(
                {
                    "original": segment["content"],
                    "translated": translated,
                    "type": segment["type"],
                }
            )

            # Incremental save
            try:
                with open(bilingual_json_path, "w", encoding="utf-8") as f:
                    json.dump(translated_segments, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log(f"Failed to save intermediate result: {e}")

            # Update progress
            with deps.bilingual_tasks_lock:
                deps.bilingual_tasks[task_id]["progress"] = {
                    "current": i + 1,
                    "total": len(segments),
                }

        log(f"Translation complete: {len(translated_segments)} segments")

        # Update paper metadata
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
            paper.mark_bilingual_version(bilingual_json_path)
            path = paper.file_path
            if path and os.path.exists(path):
                deps.save_paper_metadata(path, paper)
        else:
            categories = deps.get_categories()

            def search_and_update(node):
                category_path = deps.get_category_path(categories, node["id"])
                if category_path:
                    papers = deps.get_papers_in_category(node["id"], category_path)
                    for paper in papers:
                        if paper.id == paper_id:
                            paper.mark_bilingual_version(bilingual_json_path)
                            p = paper.file_path
                            if p and os.path.exists(p):
                                deps.save_paper_metadata(p, paper)
                            return True
                if "children" in node:
                    for child in node["children"]:
                        if search_and_update(child):
                            return True
                return False

            for child in categories.get("children", []):
                if search_and_update(child):
                    break

        end_time = datetime.now()
        duration = int((end_time - start_time).total_seconds())

        with deps.bilingual_tasks_lock:
            deps.bilingual_tasks[task_id]["status"] = "completed"
            deps.bilingual_tasks[task_id]["result"] = {
                "success": True,
                "bilingual_json_path": bilingual_json_path,
                "duration": duration,
                "segments_count": len(translated_segments),
            }

    except Exception as e:
        print(f"Bilingual translation error: {e}")
        import traceback

        traceback.print_exc()
        with deps.bilingual_tasks_lock:
            deps.bilingual_tasks[task_id]["status"] = "failed"
            deps.bilingual_tasks[task_id]["result"] = {
                "success": False,
                "error": str(e),
            }
