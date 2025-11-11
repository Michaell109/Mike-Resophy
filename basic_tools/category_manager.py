from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

DEFAULT_CATEGORIES: Dict[str, Any] = {
    "id": "root",
    "name": "Root",
    "children": [
        {
            "id": "mllm",
            "name": "MLLM",
            "children": [
                {"id": "finetuning", "name": "finetuning", "children": []},
                {"id": "post_training", "name": "post_training", "children": []},
            ],
        }
    ],
}


def init_categories(
    categories_file: str, default: Optional[Dict[str, Any]] = None
) -> None:
    if not os.path.exists(categories_file):
        with open(categories_file, "w", encoding="utf-8") as f:
            json.dump(default or DEFAULT_CATEGORIES, f, ensure_ascii=False, indent=2)


def get_categories(categories_file: str) -> Dict[str, Any]:
    with open(categories_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_categories(categories_file: str, categories: Dict[str, Any]) -> None:
    with open(categories_file, "w", encoding="utf-8") as f:
        json.dump(categories, f, ensure_ascii=False, indent=2)


def find_category_node(
    categories: Dict[str, Any], category_id: str
) -> Optional[Dict[str, Any]]:
    if categories.get("id") == category_id:
        return categories
    for child in categories.get("children", []):
        result = find_category_node(child, category_id)
        if result:
            return result
    return None


def get_category_path(
    categories: Dict[str, Any],
    category_id: str,
    path: Optional[List[str]] = None,
) -> Optional[List[str]]:
    if path is None:
        path = []
    if categories.get("id") == category_id:
        return path + [categories["name"]]
    for child in categories.get("children", []):
        result = get_category_path(child, category_id, path + [categories["name"]])
        if result:
            return result
    return None


def create_category_folder(upload_folder: str, category_path: List[str]) -> str:
    folder_path = os.path.join(upload_folder, *category_path)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


def get_category_pdf_count(
    categories: Dict[str, Any],
    category_id: str,
    get_papers_in_category: Callable[[List[str]], List[Any]],
) -> int:
    target_node = find_category_node(categories, category_id)
    if not target_node:
        return 0

    def traverse(node: Dict[str, Any]) -> int:
        total = 0
        path = get_category_path(categories, node["id"])
        if path:
            total += len(get_papers_in_category(path))
        for child in node.get("children", []):
            total += traverse(child)
        return total

    return traverse(target_node)


def add_pdf_counts_to_categories(
    categories: Dict[str, Any],
    count_func: Callable[[str], int],
) -> Dict[str, Any]:
    categories_copy = json.loads(json.dumps(categories))

    def add_counts(node: Dict[str, Any]) -> None:
        node["pdf_count"] = count_func(node["id"])
        for child in node.get("children", []):
            add_counts(child)

    add_counts(categories_copy)
    return categories_copy
