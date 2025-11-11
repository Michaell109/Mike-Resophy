from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import requests


def fetch_arxiv_abstract(arxiv_id: str) -> Optional[dict]:
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
        title_elem = entry.find("{http://www.w3.org/2005/Atom}title")
        if title_elem is not None and title_elem.text:
            result["title"] = title_elem.text.strip()

        authors = []
        for author in entry.findall("{http://www.w3.org/2005/Atom}author"):
            name_elem = author.find("{http://www.w3.org/2005/Atom}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        if authors:
            result["authors"] = ", ".join(authors)

        summary = entry.find("{http://www.w3.org/2005/Atom}summary")
        if summary is not None and summary.text:
            abstract = summary.text.strip()
            abstract = re.sub(r"\s+", " ", abstract)
            result["abstract"] = abstract

        published = entry.find("{http://www.w3.org/2005/Atom}published")
        if published is not None and published.text:
            try:
                published_date_str = published.text.strip().rstrip("Z")
                if "." in published_date_str:
                    dt = datetime.strptime(published_date_str, "%Y-%m-%dT%H:%M:%S.%f")
                else:
                    dt = datetime.strptime(published_date_str, "%Y-%m-%dT%H:%M:%S")
                result["published_date"] = dt.isoformat()
            except Exception as exc:
                original = published.text.strip() if published is not None else "None"
                print(f"解析 arXiv 发布时间失败: {exc}, 原始字符串: {original}")
        return result if result else None
    except Exception as exc:
        print(f"获取 arXiv 信息失败: {exc}")
        return None
