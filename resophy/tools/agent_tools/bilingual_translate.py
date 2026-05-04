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
5. CRITICAL: Keep ALL AI/ML technical terms in English. NEVER translate model names (e.g. Transformer, Diffusion, GAN), technical concepts (e.g. attention, embedding, latent, backbone), or dataset names (e.g. ImageNet, COCO). These are proper names of technical concepts and MUST retain their English form.
6. Translate naturally and fluently, not word-by-word
7. Output ONLY the translated text, no explanations or notes
"""

# Number of segments to translate in a single API call.
# Automatically halves on parse failure (20 -> 10 -> 5 -> 2 -> 1).
BATCH_SIZE = 20

# Glossary of AI/ML terms that MUST stay in English during translation
GLOSSARY_PATH = os.path.join(os.path.dirname(__file__), "glossary.json")


def _load_glossary() -> dict:
    """Load glossary terms from JSON file. Returns {category: [terms]}."""
    try:
        if os.path.exists(GLOSSARY_PATH):
            with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


_glossary = _load_glossary()


def _format_glossary_prompt() -> str:
    """Format glossary terms into a constraint line for the translation prompt."""
    if not _glossary:
        return ""
    all_terms = []
    for terms in _glossary.values():
        for t in terms:
            if t not in all_terms:
                all_terms.append(t)
    return (
        "CRITICAL glossary — The following AI/ML terms MUST remain in English, "
        "DO NOT translate them:\n" + ", ".join(all_terms)
    )

# Max conversation tokens before reset. Model supports ~1M context; leave generous
# headroom for the response and per-message overhead.
MAX_CONVERSATION_TOKENS = 800000
# Number of recent turns to keep when resetting conversation
RESET_KEEP_TURNS = 10


@dataclass
class BilingualDependencies:
    bilingual_tasks: Dict[str, Dict[str, Any]]
    bilingual_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def split_markdown_into_segments(md_text: str) -> List[Dict[str, str]]:
    """Split markdown into segments by natural paragraphs.

    Each segment is a dict with 'type' ('heading' or 'paragraph') and 'content'.
    Headings are separate segments. Each natural paragraph (separated by blank lines)
    is its own segment, so that the bilingual viewer can display one paragraph of
    original text followed by one paragraph of translation.
    """
    lines = md_text.split("\n")
    segments = []
    current_lines = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Handle code blocks
        if stripped.startswith("```"):
            if in_code_block:
                current_lines.append(line)
                content = "\n".join(current_lines).strip()
                if content:
                    segments.append({"type": "paragraph", "content": content})
                current_lines = []
                in_code_block = False
                continue
            else:
                # Flush current paragraph before code block
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if content:
                        segments.append({"type": "paragraph", "content": content})
                    current_lines = []
                in_code_block = True
                current_lines.append(line)
                continue

        if in_code_block:
            current_lines.append(line)
            continue

        # Handle headings as separate segments
        if stripped.startswith("#"):
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    segments.append({"type": "paragraph", "content": content})
                current_lines = []
            segments.append({"type": "heading", "content": stripped})
            continue

        # Blank line = paragraph separator
        if stripped == "":
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    segments.append({"type": "paragraph", "content": content})
                current_lines = []
            continue

        current_lines.append(line)

    # Flush last paragraph
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            segments.append({"type": "paragraph", "content": content})

    return segments


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

    # Try removing year prefix from base_name (e.g. "2026_DiT4DiT..." -> "DiT4DiT...")
    import re as _re
    base_stripped = _re.sub(r"^\d{4}[-_]", "", base_name)
    if base_stripped != base_name:
        exact_md2 = os.path.join(outputs_dir, base_name, "vlm", f"{base_stripped}.md")
        if os.path.exists(exact_md2):
            return exact_md2

    # Search for a directory matching the PDF name (by substring match)
    for item in sorted(os.listdir(outputs_dir)):
        item_path = os.path.join(outputs_dir, item)
        if not os.path.isdir(item_path):
            continue
        vlm_dir = os.path.join(item_path, "vlm")
        if not os.path.exists(vlm_dir):
            continue
        if base_name == item or base_name in item or item in base_name:
            for f in sorted(os.listdir(vlm_dir)):
                if f.endswith(".md") and f != "result.md":
                    found = os.path.join(vlm_dir, f)
                    # Verify content matches this paper
                    try:
                        with open(found, "r") as _fh:
                            first_line = _fh.readline(300).lower()
                        base_lower = base_name.lower()
                        core_words = [w for w in base_lower.replace("_", " ").split()
                                      if len(w) > 4 and not w.isdigit()]
                        if not core_words or not any(w in first_line for w in core_words):
                            continue  # Content doesn't match — try next
                    except Exception:
                        pass
                    return found

    # Last resort: return the first .md from any vlm directory
    for item in sorted(os.listdir(outputs_dir)):
        item_path = os.path.join(outputs_dir, item)
        if os.path.isdir(item_path):
            vlm_dir = os.path.join(item_path, "vlm")
            if os.path.exists(vlm_dir):
                for f in sorted(os.listdir(vlm_dir)):
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

        # Output path — write to .new during translation, rename on completion
        # so old bilingual.json stays intact during re-translation
        vlm_dir = os.path.dirname(md_file)
        bilingual_json_path = os.path.join(vlm_dir, "bilingual.json")
        bilingual_temp_path = bilingual_json_path + ".new"

        # Initialize OpenAI client
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

        # Translate segments in batches with automatic size backoff.
        # Tries BATCH_SIZE first; halves on parse failure.
        translated_segments = []
        conversation_messages = []  # [system, user, assistant, user, assistant, ...]
        conversation_token_estimate = 0

        def estimate_tokens(text: str) -> int:
            return int(len(text) * 0.7)

        def parse_batch_translations(
            text: str, expected_count: int
        ) -> dict[int, str] | None:
            """Parse batch LLM response into {index: translation} dict."""
            text = text.strip()

            # Try direct JSON parse first
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "translations" in data:
                    result = {}
                    for item in data["translations"]:
                        if isinstance(item, dict) and "index" in item and "translated" in item:
                            result[int(item["index"])] = item["translated"]
                    if len(result) == expected_count:
                        return result
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

            # Try extracting JSON from code block or inline
            for pattern in [
                r"```(?:json)?\s*\n?(.*?)\n?```",
                r"\{[^{}]*\"translations\"[^{}]*\}",
            ]:
                for m in re.finditer(pattern, text, re.DOTALL):
                    try:
                        data = json.loads(m.group(0) if m.lastindex is None else m.group(1))
                        if isinstance(data, dict) and "translations" in data:
                            result = {
                                int(item["index"]): item["translated"]
                                for item in data["translations"]
                            }
                            if len(result) == expected_count:
                                return result
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        continue

            return None

        class _Cancelled(Exception):
            pass

        def _check_cancelled() -> None:
            with deps.bilingual_tasks_lock:
                if deps.bilingual_tasks[task_id].get("status") == "cancelled":
                    raise _Cancelled()

        def _save_and_report() -> None:
            """Incremental save to .new file + progress update."""
            try:
                with open(bilingual_temp_path, "w", encoding="utf-8") as f:
                    json.dump(translated_segments, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log(f"Failed to save intermediate result: {e}")
            with deps.bilingual_tasks_lock:
                deps.bilingual_tasks[task_id]["progress"] = {
                    "current": len(translated_segments),
                    "total": len(segments),
                }

        def _ensure_conversation_space(needed_tokens: int) -> None:
            """Reset conversation history if approaching 1M token limit."""
            nonlocal conversation_token_estimate
            if (
                conversation_token_estimate + needed_tokens > MAX_CONVERSATION_TOKENS
                and len(conversation_messages) > RESET_KEEP_TURNS * 2 + 1
            ):
                keep_count = RESET_KEEP_TURNS * 2
                kept = conversation_messages[-keep_count:]
                conversation_messages.clear()
                conversation_messages.append({"role": "system", "content": SYSTEM_PROMPT})
                conversation_messages.extend(kept)
                conversation_token_estimate = sum(
                    estimate_tokens(m["content"]) for m in conversation_messages
                )
                log(
                    f"Conversation reset to last {RESET_KEEP_TURNS} turns "
                    f"(~{conversation_token_estimate} tokens)"
                )

        def _try_batch(group: list) -> bool:
            """Translate a group of segments in one LLM call. Returns success."""
            _check_cancelled()
            _ensure_conversation_space(
                estimate_tokens("\n".join(s["content"] for s in group))
            )

            batch_parts = [
                f"---SEGMENT {j}---\n{s['content']}"
                for j, s in enumerate(group)
            ]
            glossary_prompt = _format_glossary_prompt()
            user_content = (
                "Translate the following academic paper segments to Chinese.\n\n"
                "IMPORTANT: Return ONLY valid JSON (no other text) in this exact format:\n"
                '{"translations": [{"index": 0, "translated": "..."}, '
                '{"index": 1, "translated": "..."}]}\n\n'
                + (glossary_prompt + "\n\n" if glossary_prompt else "")
                + "\n\n".join(batch_parts)
            )

            if not conversation_messages:
                msgs = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ]
            else:
                msgs = conversation_messages + [
                    {"role": "user", "content": user_content}
                ]

            try:
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=msgs,
                    temperature=0.3,
                )
                resp_text = response.choices[0].message.content.strip()
                translations = parse_batch_translations(resp_text, len(group))
                if translations is None:
                    return False

                for j, seg in enumerate(group):
                    translated_segments.append(
                        {
                            "original": seg["content"],
                            "translated": translations.get(j, "[Translation failed]"),
                            "type": seg["type"],
                        }
                    )

                nonlocal conversation_token_estimate

                if not conversation_messages:
                    conversation_messages.extend(
                        [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                            {"role": "assistant", "content": resp_text},
                        ]
                    )
                else:
                    conversation_messages.append(
                        {"role": "user", "content": user_content}
                    )
                    conversation_messages.append(
                        {"role": "assistant", "content": resp_text}
                    )
                conversation_token_estimate += estimate_tokens(
                    user_content
                ) + estimate_tokens(resp_text)

                _save_and_report()
                return True
            except Exception:
                return False

        def _translate_group(group: list, batch_size: int) -> None:
            """Translate group with automatic size backoff on failure."""
            _check_cancelled()
            if not group:
                return

            if batch_size >= len(group):
                if _try_batch(group):
                    return

                if batch_size == 1:
                    # Single segment failed even individually
                    seg = group[0]
                    translated_segments.append(
                        {
                            "original": seg["content"],
                            "translated": "[Translation failed]",
                            "type": seg["type"],
                        }
                    )
                    _save_and_report()
                    return

                # Split in half and retry with smaller batch size
                mid = len(group) // 2
                log(
                    f"Batch of {len(group)} failed, splitting into "
                    f"{len(group[:mid])} + {len(group[mid:])} "
                    f"(next size: {max(1, batch_size // 2)})"
                )
                _translate_group(group[:mid], max(1, batch_size // 2))
                _translate_group(group[mid:], max(1, batch_size // 2))
            else:
                for i in range(0, len(group), batch_size):
                    _translate_group(group[i : i + batch_size], batch_size)

        log(
            f"Starting batch translation "
            f"(initial size={BATCH_SIZE}, {len(segments)} segments)"
        )
        _translate_group(segments, BATCH_SIZE)
        log(f"Translation complete: {len(translated_segments)} segments")

        # Atomic rename: .new -> bilingual.json
        # This ensures old bilingual.json stays intact during re-translation
        if os.path.exists(bilingual_temp_path):
            os.replace(bilingual_temp_path, bilingual_json_path)
            log(f"Saved translation to {bilingual_json_path}")

        # Update paper metadata
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
            paper.mark_bilingual_version(bilingual_json_path)
            paper.has_chinese_version = True
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
                            paper.has_chinese_version = True
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
