from __future__ import annotations

import json
import os
from typing import Any, Dict

from flask import Flask, Response, jsonify, request, stream_with_context

from resophy.core.paper_store import paper_store


def register_chat_routes(
    app: Flask,
    *,
    chat_settings_file: str,
    default_chat_settings: Dict[str, Any],
) -> None:

    # ========================================
    # Chat LLM Settings
    # ========================================
    @app.route("/api/settings/chat", methods=["GET", "POST"])
    def api_chat_settings():
        if request.method == "GET":
            try:
                with open(chat_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"Failed to read chat settings: {exc}")
                settings = {}
            merged = default_chat_settings.copy()
            merged.update(settings)
            return jsonify(merged)

        data = request.json or {}
        try:
            try:
                with open(chat_settings_file, "r", encoding="utf-8") as fp:
                    current = json.load(fp)
            except Exception:
                current = default_chat_settings.copy()

            current.update(data)

            with open(chat_settings_file, "w", encoding="utf-8") as fp:
                json.dump(current, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/test/chat-llm", methods=["POST"])
    def api_test_chat_llm():
        try:
            data = request.json or {}
            model = data.get("chatLlmModel", "").strip()
            base_url = data.get("chatLlmBaseUrl", "").strip()
            api_key = data.get("chatLlmApiKey", "").strip()

            if not model or not base_url or not api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please fill in the complete Chat LLM configuration (Model, Base URL, API Key)",
                        }
                    ),
                    400,
                )

            from openai import OpenAI

            client = OpenAI(base_url=base_url, api_key=api_key, timeout=30.0)

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi, please reply with Yes."}],
                max_tokens=50,
            )

            if response.choices and len(response.choices) > 0:
                reply = response.choices[0].message.content.strip()
                return jsonify(
                    {
                        "success": True,
                        "message": "Chat LLM connection successful!",
                        "reply": reply,
                    }
                )
            else:
                return jsonify(
                    {"success": False, "error": "Chat LLM returned an empty reply"}
                )

        except Exception as exc:
            error_msg = str(exc)
            if "401" in error_msg or "Unauthorized" in error_msg:
                return jsonify({"success": False, "error": "API Key is invalid or unauthorized"})
            elif "404" in error_msg or "Not Found" in error_msg:
                return jsonify({"success": False, "error": "API endpoint does not exist, please check Base URL"})
            elif "timeout" in error_msg.lower():
                return jsonify({"success": False, "error": "Connection timed out"})
            else:
                return jsonify({"success": False, "error": f"Chat LLM test failed: {error_msg}"})

    # ========================================
    # Chat API (SSE streaming)
    # ========================================
    @app.route("/api/paper/<paper_id>/chat", methods=["POST"])
    def api_paper_chat(paper_id):
        try:
            data = request.json or {}
            messages = data.get("messages", [])

            if not messages:
                return jsonify({"success": False, "error": "No messages provided"}), 400

            # Read chat LLM settings
            try:
                with open(chat_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except Exception:
                settings = {}

            merged = default_chat_settings.copy()
            merged.update(settings)

            model = merged.get("chatLlmModel", "").strip()
            base_url = merged.get("chatLlmBaseUrl", "").strip()
            api_key = merged.get("chatLlmApiKey", "").strip()

            if not model or not base_url or not api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Chat LLM is not configured. Please configure it in Settings → Chat LLM.",
                        }
                    ),
                    400,
                )

            # Find paper
            entry = paper_store.get_entry(paper_id)
            if entry:
                paper = entry.paper
            else:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            # Load analysis result as context
            paper_context = ""
            if paper.analysis_result_path and os.path.exists(paper.analysis_result_path):
                try:
                    with open(paper.analysis_result_path, "r", encoding="utf-8") as f:
                        paper_context = f.read()
                except Exception as exc:
                    print(f"Failed to read analysis result: {exc}")

            # Also try to read from standard path if analysis_result_path is not set
            if not paper_context and paper.file_path:
                pdf_dir = os.path.dirname(paper.file_path)
                base_name = os.path.splitext(os.path.basename(paper.file_path))[0]
                outputs_dir = os.path.join(pdf_dir, "outputs")

                result_file = None
                if os.path.exists(outputs_dir):
                    exact_result = os.path.join(outputs_dir, base_name, "vlm", "result.md")
                    if os.path.exists(exact_result):
                        result_file = exact_result
                    else:
                        for item in os.listdir(outputs_dir):
                            item_path = os.path.join(outputs_dir, item)
                            if os.path.isdir(item_path):
                                vlm_dir = os.path.join(item_path, "vlm")
                                if os.path.exists(vlm_dir):
                                    potential_result = os.path.join(vlm_dir, "result.md")
                                    if os.path.exists(potential_result):
                                        result_file = potential_result
                                        break

                if result_file:
                    try:
                        with open(result_file, "r", encoding="utf-8") as f:
                            paper_context = f.read()
                    except Exception:
                        pass

            # Build system prompt
            paper_title = paper.title or paper.original_filename or "Unknown"
            paper_authors = paper.authors or ""

            if paper_context:
                system_prompt = (
                    f"You are a helpful research assistant. The user is reading the paper "
                    f'"{paper_title}"'
                    f"{f' by {paper_authors}' if paper_authors else ''}. "
                    f"Below is a detailed analysis of this paper. "
                    f"Answer the user's questions based on this context and your knowledge. "
                    f"Respond in the same language as the user's question.\n\n"
                    f"--- Paper Analysis ---\n{paper_context}"
                )
            else:
                # Fallback: use abstract
                abstract = paper.abstract or paper.summary or ""
                if abstract:
                    system_prompt = (
                        f"You are a helpful research assistant. The user is reading the paper "
                        f'"{paper_title}"'
                        f"{f' by {paper_authors}' if paper_authors else ''}. "
                        f"Below is the abstract. Answer questions based on this and your knowledge. "
                        f"Respond in the same language as the user's question.\n\n"
                        f"--- Abstract ---\n{abstract}"
                    )
                else:
                    system_prompt = (
                        f"You are a helpful research assistant. The user is reading the paper "
                        f'"{paper_title}"'
                        f"{f' by {paper_authors}' if paper_authors else ''}. "
                        f"Answer the user's questions about this paper. "
                        f"Respond in the same language as the user's question."
                    )

            # Build messages for LLM
            llm_messages = [{"role": "system", "content": system_prompt}]
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    llm_messages.append({"role": role, "content": content})

            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url)

            def generate():
                try:
                    stream = client.chat.completions.create(
                        model=model,
                        messages=llm_messages,
                        stream=True,
                    )
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as exc:
                    error_msg = str(exc)
                    yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"

            return Response(
                stream_with_context(generate()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
