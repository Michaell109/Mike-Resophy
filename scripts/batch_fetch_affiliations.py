"""
Batch script: fetch affiliations for all existing papers via OpenAlex.

Scans all paper JSON metadata files, finds those with arxiv_id but
no affiliation data, fetches via OpenAlex API, and updates the JSON.
"""

import json
import os
import sys
import time
import glob

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from resophy.tools.basic_tools.upload_paper import fetch_arxiv_affiliations

PAPERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "papers")


def needs_affiliation(paper: dict) -> bool:
    """Check if a paper needs affiliation data."""
    # Must have arxiv_id
    arxiv_id = paper.get("arxiv_id")
    if not arxiv_id:
        return False

    # Check if affiliation is empty / nan
    aff = (paper.get("affiliation") or "").strip()
    if aff and aff.lower() != "nan":
        # Already has affiliation; check if extra.affiliations is also populated
        extra = paper.get("extra") or {}
        if extra.get("affiliations"):
            return False
        # Has affiliation string but missing the array in extra — still update
        return True

    return True


def update_paper_metadata(filepath: str, paper: dict, affiliations: list) -> None:
    """Update a paper JSON file with affiliation data."""
    paper["affiliation"] = "; ".join(affiliations)
    # Ensure extra dict exists
    if "extra" not in paper or paper["extra"] is None:
        paper["extra"] = {}
    paper["extra"]["affiliations"] = affiliations

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(paper, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Updated: {paper.get('title', '?')[:60]}...")


def main():
    papers_dir = os.environ.get("PAPERS_DIR", PAPERS_DIR)
    print(f"Scanning papers in: {papers_dir}")

    json_files = glob.glob(
        os.path.join(papers_dir, "**", "*.json"), recursive=True
    )

    # Filter out non-paper files
    skip_patterns = (
        "categories.json",
        "reading_list.json",
        "reading_history.json",
        "agentic_settings.json",
        "user_settings.json",
        "chat_settings.json",
        "daily_arxiv_settings.json",
        "paper_store.json",
        "search_index",
        "avatars",
    )
    json_files = [
        f
        for f in json_files
        if not any(p in f for p in skip_patterns)
    ]

    print(f"Found {len(json_files)} paper JSON files")

    # Find papers that need affiliation
    to_process = []
    for filepath in json_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                paper = json.load(f)
            if needs_affiliation(paper):
                to_process.append((filepath, paper))
        except Exception as e:
            print(f"  ⚠ Error reading {filepath}: {e}")

    print(f"\nPapers needing affiliation fetch: {len(to_process)}")
    if not to_process:
        print("All done!")
        return

    # Process in order with rate limiting
    success = 0
    failed = 0
    skipped = 0

    for i, (filepath, paper) in enumerate(to_process, 1):
        arxiv_id = paper.get("arxiv_id", "")
        title = paper.get("title", "")
        print(f"\n[{i}/{len(to_process)}] arXiv:{arxiv_id} - {title[:60]}...")

        try:
            affiliations = fetch_arxiv_affiliations(arxiv_id, title=title)
            if affiliations:
                update_paper_metadata(filepath, paper, affiliations)
                success += 1
            else:
                print(f"  ⚠ No affiliations found via OpenAlex")
                # Still mark as processed to avoid re-checking
                paper["affiliation"] = ""
                if "extra" not in paper or paper["extra"] is None:
                    paper["extra"] = {}
                paper["extra"]["affiliations"] = []
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(paper, f, ensure_ascii=False, indent=2)
                skipped += 1
        except Exception as e:
            print(f"  ❌ Error: {e}")
            failed += 1

        # Polite delay between requests (OpenAlex has generous limits but be nice)
        if i < len(to_process):
            time.sleep(0.3)

    print(f"\n=== Done ===")
    print(f"  Success: {success}")
    print(f"  Skipped (no data): {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Total processed: {len(to_process)}")


if __name__ == "__main__":
    main()
