"""
Zotero RDF 文件解析器
用于解析从 Zotero 导出的 RDF 文件，并转换为项目的 Paper 格式
"""

import html
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根目录到 Python 路径，以便可以导入 core 模块
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from rdflib import RDF, RDFS, Graph, Literal, Namespace
    from rdflib.namespace import DC, DCTERMS, FOAF
except ImportError:
    print("需要安装 rdflib: pip install rdflib")
    raise

from core.base_paper import Paper

# 定义命名空间
Z = Namespace("http://www.zotero.org/namespaces/export#")
BIB = Namespace("http://purl.org/net/biblio#")
VCARD = Namespace("http://nwalsh.com/rdf/vCard#")
LINK = Namespace("http://purl.org/rss/1.0/modules/link/")


class ZoteroRDFParser:
    """解析 Zotero RDF 文件的解析器"""

    def __init__(self, rdf_file_path: str):
        """
        初始化解析器

        Args:
            rdf_file_path: RDF 文件路径
        """
        self.rdf_file_path = Path(rdf_file_path)
        self.graph = Graph()
        self.papers: List[Paper] = []
        self.memos: Dict[str, str] = {}  # 存储备注信息
        self.attachments: Dict[str, List[Dict[str, str]]] = {}  # 存储附件信息
        self.collections: Dict[str, Dict[str, Any]] = (
            {}
        )  # 存储 Collection 信息 {collection_id: {title, children, papers}}
        self.paper_to_collections: Dict[str, List[str]] = (
            {}
        )  # 存储论文到 Collection 的映射 {paper_id: [collection_paths]}
        self.paper_subjects: Dict[str, str] = (
            {}
        )  # 存储论文的原始 subject {paper_id: original_subject}

    def _fix_rdf_errors(self):
        """修复 RDF 文件中的常见格式错误"""
        import re

        fixed_file = self.rdf_file_path.parent / f"{self.rdf_file_path.stem}_fixed.rdf"

        # 如果修复文件已存在，直接使用
        if fixed_file.exists():
            return

        try:
            # 读取原文件
            with open(self.rdf_file_path, "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")

            # 修复无效的 rdf:resource 元素
            content = re.sub(r'<rdf:resource rdf:resource="[^"]+"/>', "", content)

            # 保存修复后的文件
            with open(fixed_file, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"已创建修复后的文件: {fixed_file}")
        except Exception as e:
            print(f"修复文件时出错: {e}")

    def parse(self) -> List[Paper]:
        """
        解析 RDF 文件并返回 Paper 列表

        Returns:
            Paper 对象列表
        """
        print(f"正在解析 RDF 文件: {self.rdf_file_path}")

        # 先尝试修复常见的 RDF 格式错误
        self._fix_rdf_errors()

        # 加载 RDF 文件
        try:
            self.graph.parse(str(self.rdf_file_path), format="xml")
        except Exception as e:
            print(f"解析错误: {e}")
            print("尝试使用修复后的文件...")
            # 如果解析失败，尝试使用修复后的版本
            fixed_file = (
                self.rdf_file_path.parent / f"{self.rdf_file_path.stem}_fixed.rdf"
            )
            if fixed_file.exists():
                self.graph.parse(str(fixed_file), format="xml")
            else:
                raise

        # 先解析备注和附件
        self._parse_memos()
        self._parse_attachments()

        # 解析 Collection 层级结构
        self._parse_collections()

        # 解析论文条目
        self._parse_papers()

        # 为论文分配 Collection 路径
        self._assign_collections_to_papers()

        print(f"解析完成，共找到 {len(self.papers)} 篇论文")
        return self.papers

    def _parse_memos(self):
        """解析备注信息"""
        for memo_subj, memo_pred, memo_obj in self.graph.triples(
            (None, RDF.type, BIB.Memo)
        ):
            memo_id = str(memo_subj)
            # 获取备注内容
            for _, _, value in self.graph.triples((memo_subj, RDF.value, None)):
                memo_text = str(value)
                # 移除 HTML 标签
                memo_text = re.sub(r"<[^>]+>", "", memo_text)
                memo_text = html.unescape(memo_text).strip()
                self.memos[memo_id] = memo_text

    def _parse_attachments(self):
        """解析附件信息"""
        for attach_subj, attach_pred, attach_obj in self.graph.triples(
            (None, RDF.type, Z.Attachment)
        ):
            attach_id = str(attach_subj)

            # 获取附件标题
            title = ""
            for _, _, title_obj in self.graph.triples((attach_subj, DC.title, None)):
                title = str(title_obj)

            # 获取附件类型
            attach_type = ""
            for _, _, type_obj in self.graph.triples((attach_subj, LINK.type, None)):
                attach_type = str(type_obj)

            # 找到引用此附件的论文
            for paper_subj, _, _ in self.graph.triples((None, LINK.link, attach_subj)):
                paper_id = str(paper_subj)
                if paper_id not in self.attachments:
                    self.attachments[paper_id] = []
                self.attachments[paper_id].append(
                    {"title": title, "type": attach_type, "id": attach_id}
                )

    def _normalize_collection_id(self, coll_id: str) -> str:
        """规范化 Collection ID，提取 #collection_XX 部分"""
        if "#collection_" in coll_id:
            return "#" + coll_id.split("#")[-1]
        return coll_id

    def _parse_collections(self):
        """解析 Collection 层级结构"""
        # 首先收集所有 Collection 的基本信息
        for coll_subj, _, _ in self.graph.triples((None, RDF.type, Z.Collection)):
            coll_id_raw = str(coll_subj)
            coll_id = self._normalize_collection_id(coll_id_raw)

            # 获取 Collection 标题
            title = ""
            for _, _, title_obj in self.graph.triples((coll_subj, DC.title, None)):
                title = str(title_obj).strip()

            if not title:
                continue  # 跳过没有标题的 Collection

            # 初始化 Collection 信息
            if coll_id not in self.collections:
                self.collections[coll_id] = {
                    "title": title,
                    "children": [],  # 子 Collection IDs
                    "papers": [],  # 直接包含的论文 IDs
                    "raw_id": coll_id_raw,  # 保存原始 ID 用于匹配
                }

            # 获取 hasPart 关系
            for _, _, part_obj in self.graph.triples(
                (coll_subj, DCTERMS.hasPart, None)
            ):
                part_id_raw = str(part_obj)
                part_id = self._normalize_collection_id(part_id_raw)

                # 判断是子 Collection 还是论文
                # 如果以 #collection_ 开头，是子 Collection
                if part_id.startswith("#collection_"):
                    if part_id not in self.collections[coll_id]["children"]:
                        self.collections[coll_id]["children"].append(part_id)
                else:
                    # 否则是论文（可能是 URI 或 item ID）
                    if part_id_raw not in self.collections[coll_id]["papers"]:
                        self.collections[coll_id]["papers"].append(part_id_raw)

        print(f"解析到 {len(self.collections)} 个 Collection")

    def _build_collection_path(self, collection_id: str, visited: set = None) -> str:
        """
        构建 Collection 的完整路径

        Args:
            collection_id: Collection ID
            visited: 已访问的 Collection（防止循环）

        Returns:
            Collection 的完整路径，如 "Diffusion/Auto Regressive"
        """
        if visited is None:
            visited = set()

        if collection_id in visited:
            return ""  # 防止循环

        if collection_id not in self.collections:
            return ""

        visited.add(collection_id)
        title = self.collections[collection_id]["title"]

        # 查找父 Collection
        parent_id = None
        for coll_id, coll_info in self.collections.items():
            if collection_id in coll_info["children"]:
                parent_id = coll_id
                break

        if parent_id:
            parent_path = self._build_collection_path(parent_id, visited)
            if parent_path:
                return f"{parent_path}/{title}"
            else:
                return title
        else:
            return title

    def _assign_collections_to_papers(self):
        """为每篇论文分配 Collection 路径"""
        # 构建论文 ID 到 Paper 对象的映射
        paper_map = {}
        for paper in self.papers:
            # 尝试多种可能的 ID 格式
            possible_ids = [paper.id]
            # 从 paper_subjects 中找到原始 subject
            for orig_id, orig_subj in self.paper_subjects.items():
                if paper.id in orig_id or orig_id.replace(":", "_") == paper.id:
                    possible_ids.append(orig_subj)
                    possible_ids.append(orig_id)
                    # 如果原始 ID 包含 urn:isbn，同时添加原始格式和转换格式
                    if "urn:isbn:" in orig_id:
                        # 添加原始格式
                        possible_ids.append(orig_id)
                        # 添加转换后的格式（如果还没有）
                        converted_id = orig_id.replace("urn:", "").replace(":", "_")
                        if converted_id not in possible_ids:
                            possible_ids.append(converted_id)
                    break
            # 添加 URL
            if "url" in paper.extra:
                possible_ids.append(paper.extra["url"])

            # 处理 ISBN 格式：如果 paper.id 是 isbn_xxx，也添加 urn:isbn:xxx 格式
            if paper.id.startswith("isbn_"):
                isbn_number = paper.id.replace("isbn_", "")
                possible_ids.append(f"urn:isbn:{isbn_number}")
                possible_ids.append(f"isbn:{isbn_number}")

            for pid in possible_ids:
                paper_map[pid] = paper

        # 为每篇论文找到它所属的所有 Collection
        for coll_id, coll_info in self.collections.items():
            category_path = self._build_collection_path(coll_id)
            if not category_path:
                continue

            # 检查此 Collection 包含的所有论文引用
            for paper_ref in coll_info["papers"]:
                # 尝试匹配论文
                matched_paper = None

                # 直接匹配
                if paper_ref in paper_map:
                    matched_paper = paper_map[paper_ref]
                else:
                    # 尝试部分匹配（处理 URI 格式差异）
                    for paper_id, paper in paper_map.items():
                        # 检查各种匹配方式
                        if (
                            paper_ref == paper_id
                            or paper_ref.endswith(paper_id)
                            or paper_id.endswith(paper_ref)
                            or paper_ref in paper_id
                            or paper_id in paper_ref
                        ):
                            # 更严格的匹配：检查是否是同一个资源
                            if "arxiv.org" in paper_ref and "arxiv.org" in paper_id:
                                matched_paper = paper
                                break
                            elif "http" in paper_ref and "http" in paper_id:
                                # 提取路径部分进行比较
                                ref_path = paper_ref.split("/")[-1]
                                id_path = paper_id.split("/")[-1]
                                if (
                                    ref_path == id_path
                                    or ref_path in id_path
                                    or id_path in ref_path
                                ):
                                    matched_paper = paper
                                    break
                            elif "#item_" in paper_ref or "#item_" in paper_id:
                                # 提取 item ID
                                ref_item = (
                                    paper_ref.split("#item_")[-1]
                                    if "#item_" in paper_ref
                                    else ""
                                )
                                id_item = (
                                    paper_id.split("#item_")[-1]
                                    if "#item_" in paper_id
                                    else ""
                                )
                                if ref_item and id_item and ref_item == id_item:
                                    matched_paper = paper
                                    break
                            elif "urn:isbn:" in paper_ref or "isbn_" in paper_id:
                                # 处理 ISBN 格式：urn:isbn:xxx 与 isbn_xxx 的匹配
                                # 提取 ISBN 号码部分
                                ref_isbn = ""
                                if "urn:isbn:" in paper_ref:
                                    ref_isbn = (
                                        paper_ref.split("urn:isbn:")[-1]
                                        .split("/")[0]
                                        .split("%")[0]
                                        .strip()
                                    )
                                elif "isbn:" in paper_ref:
                                    ref_isbn = (
                                        paper_ref.split("isbn:")[-1]
                                        .split("/")[0]
                                        .split("%")[0]
                                        .strip()
                                    )

                                id_isbn = ""
                                if paper_id.startswith("isbn_"):
                                    id_isbn = paper_id.replace("isbn_", "").strip()
                                elif "isbn" in paper_id.lower():
                                    # 尝试从其他格式中提取 ISBN
                                    import re

                                    isbn_match = re.search(r"[\d-]+", paper_id)
                                    if isbn_match:
                                        id_isbn = isbn_match.group(0)

                                if ref_isbn and id_isbn:
                                    # 标准化 ISBN（移除连字符进行比较）
                                    ref_isbn_normalized = ref_isbn.replace(
                                        "-", ""
                                    ).replace(" ", "")
                                    id_isbn_normalized = id_isbn.replace(
                                        "-", ""
                                    ).replace(" ", "")
                                    if (
                                        ref_isbn_normalized == id_isbn_normalized
                                        or ref_isbn in id_isbn
                                        or id_isbn in ref_isbn
                                    ):
                                        matched_paper = paper
                                        break

                if matched_paper:
                    # 添加 category 到论文
                    if "category" not in matched_paper.extra:
                        matched_paper.extra["category"] = []
                    elif isinstance(matched_paper.extra["category"], str):
                        matched_paper.extra["category"] = [
                            matched_paper.extra["category"]
                        ]

                    if category_path not in matched_paper.extra["category"]:
                        matched_paper.extra["category"].append(category_path)

        # 将 category 列表转换为字符串，并移除冗余路径
        for paper in self.papers:
            if "category" in paper.extra:
                if isinstance(paper.extra["category"], list):
                    categories = paper.extra["category"]
                    # 移除冗余路径：如果一个路径是另一个路径的前缀，则移除前缀路径
                    # 只保留最长的（最具体的）路径
                    filtered_categories = []
                    for cat_path in categories:
                        # 检查这个路径是否是其他路径的前缀
                        is_prefix = False
                        for other_path in categories:
                            if cat_path != other_path and other_path.startswith(
                                cat_path + "/"
                            ):
                                is_prefix = True
                                break
                        if not is_prefix:
                            filtered_categories.append(cat_path)

                    # 如果过滤后还有多个路径，按长度排序（最长的在前）
                    filtered_categories.sort(key=len, reverse=True)

                    category_str = "; ".join(filtered_categories)
                    paper.extra["category"] = category_str
                    # 也添加到 subject 字段（如果为空）
                    if not paper.subject and category_str:
                        paper.subject = (
                            filtered_categories[0] if filtered_categories else ""
                        )

    def _parse_papers(self):
        """解析论文条目"""
        # 查找所有论文描述
        paper_descriptions = set()

        # 查找所有 rdf:Description 节点
        for subj, pred, obj in self.graph.triples((None, RDF.type, None)):
            if isinstance(subj, str) or hasattr(subj, "toPython"):
                paper_descriptions.add(subj)

        # 查找所有有 itemType 的条目（论文、期刊文章等）
        for subj, pred, obj in self.graph.triples((None, Z.itemType, None)):
            item_type = str(obj).lower()
            # 只处理论文相关的条目类型（包括 preprint）
            if item_type in [
                "conferencepaper",
                "journalarticle",
                "article",
                "book",
                "booksection",
                "preprint",
            ]:
                paper = self._parse_single_paper(subj)
                if paper:
                    self.papers.append(paper)

    def _parse_single_paper(self, paper_subj) -> Optional[Paper]:
        """解析单个论文条目"""
        paper_id = str(paper_subj)

        # 保存论文的原始 subject（用于匹配 Collection）
        self.paper_subjects[paper_id] = paper_id

        # 创建 Paper 对象
        paper = Paper()
        paper.id = paper_id.replace("urn:", "").replace(":", "_")

        # 解析标题
        for _, _, title_obj in self.graph.triples((paper_subj, DC.title, None)):
            paper.title = str(title_obj).strip()

        # 解析作者
        authors_list = []
        seen_authors = set()  # 用于去重
        for _, _, authors_seq in self.graph.triples((paper_subj, BIB.authors, None)):
            # RDF 序列使用 rdf:_1, rdf:_2 等来表示序列项
            # 遍历所有可能的序列索引（最多100个作者）
            from rdflib import URIRef

            for i in range(1, 101):  # 最多支持100个作者
                rdf_index = URIRef(f"http://www.w3.org/1999/02/22-rdf-syntax-ns#_{i}")
                author_persons = list(self.graph.objects(authors_seq, rdf_index))
                if not author_persons:
                    break  # 没有更多作者了

                for author_person in author_persons:
                    surname = ""
                    given_name = ""
                    for _, _, surname_obj in self.graph.triples(
                        (author_person, FOAF.surname, None)
                    ):
                        surname = str(surname_obj)
                    for _, _, given_obj in self.graph.triples(
                        (author_person, FOAF.givenName, None)
                    ):
                        given_name = str(given_obj)
                    if surname or given_name:
                        author_name = f"{given_name} {surname}".strip()
                        # 使用作者名称去重
                        if author_name and author_name not in seen_authors:
                            authors_list.append(author_name)
                            seen_authors.add(author_name)

        if authors_list:
            paper.authors = ", ".join(authors_list)

        # 解析摘要
        for _, _, abstract_obj in self.graph.triples(
            (paper_subj, DCTERMS.abstract, None)
        ):
            paper.abstract = str(abstract_obj).strip()

        # 解析日期
        for _, _, date_obj in self.graph.triples((paper_subj, DC.date, None)):
            date_str = str(date_obj)
            # 尝试提取年份
            year_match = re.search(r"(\d{4})", date_str)
            if year_match:
                paper.year = year_match.group(1)

        # 解析期刊/会议
        for _, _, journal_obj in self.graph.triples(
            (paper_subj, DCTERMS.isPartOf, None)
        ):
            for _, _, journal_title in self.graph.triples(
                (journal_obj, DC.title, None)
            ):
                paper.journal = str(journal_title).strip()
                break

        # 解析会议信息
        for _, _, conf_obj in self.graph.triples((paper_subj, BIB.presentedAt, None)):
            for _, _, conf_title in self.graph.triples((conf_obj, DC.title, None)):
                if not paper.journal:
                    paper.journal = str(conf_title).strip()
                break

        # 解析出版商
        publisher_list = []
        for _, _, publisher_obj in self.graph.triples((paper_subj, DC.publisher, None)):
            for _, _, org_name in self.graph.triples((publisher_obj, FOAF.name, None)):
                publisher_list.append(str(org_name))
        if publisher_list:
            paper.affiliation = ", ".join(publisher_list)

        # 解析标识符（DOI, URL等）
        for _, _, identifier_obj in self.graph.triples(
            (paper_subj, DC.identifier, None)
        ):
            identifier_str = str(identifier_obj)
            if identifier_str.startswith("DOI"):
                paper.extra["doi"] = identifier_str.replace("DOI", "").strip()
            elif identifier_str.startswith("ISBN"):
                paper.extra["isbn"] = identifier_str.replace("ISBN", "").strip()
            elif isinstance(identifier_obj, str):
                # 可能是 URI
                if "http" in identifier_str:
                    paper.extra["url"] = identifier_str

        # 解析 URI
        for _, _, uri_obj in self.graph.triples((paper_subj, DC.identifier, None)):
            for _, _, uri_value in self.graph.triples((uri_obj, RDF.value, None)):
                uri_str = str(uri_value)
                if uri_str.startswith("http"):
                    paper.extra["url"] = uri_str

        # 解析页码
        for _, _, pages_obj in self.graph.triples((paper_subj, BIB.pages, None)):
            paper.extra["pages"] = str(pages_obj)

        # 解析语言
        for _, _, lang_obj in self.graph.triples((paper_subj, Z.libraryCatalog, None)):
            paper.extra["library_catalog"] = str(lang_obj)

        # 解析提交日期
        for _, _, date_submitted in self.graph.triples(
            (paper_subj, DCTERMS.dateSubmitted, None)
        ):
            paper.upload_date = str(date_submitted).strip()

        # 解析备注
        for _, _, memo_ref in self.graph.triples(
            (paper_subj, DCTERMS.isReferencedBy, None)
        ):
            memo_id = str(memo_ref)
            if memo_id in self.memos:
                paper.notes = self.memos[memo_id]

        # 解析附件
        if paper_id in self.attachments:
            attachments = self.attachments[paper_id]
            # 查找 PDF 附件
            for attach in attachments:
                if attach["type"] == "application/pdf":
                    paper.extra["pdf_attachment"] = attach["title"]
                    break

        # 解析条目类型
        for _, _, item_type in self.graph.triples((paper_subj, Z.itemType, None)):
            paper.extra["item_type"] = str(item_type)

        # 如果没有标题，跳过这个条目
        if not paper.title:
            return None

        return paper

    def export_to_json(self, output_file: Optional[str] = None) -> str:
        """
        将解析结果导出为 JSON 文件

        Args:
            output_file: 输出文件路径，如果为 None 则自动生成

        Returns:
            输出文件路径
        """
        import json

        if output_file is None:
            output_file = str(
                self.rdf_file_path.parent / f"{self.rdf_file_path.stem}_parsed.json"
            )

        papers_data = Paper.to_dict_list(self.papers)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(papers_data, f, ensure_ascii=False, indent=2)

        print(f"已导出 {len(papers_data)} 篇论文到: {output_file}")
        return output_file

    def print_summary(self):
        """打印解析结果摘要"""
        print("\n" + "=" * 60)
        print("解析结果摘要")
        print("=" * 60)
        print(f"总论文数: {len(self.papers)}")

        # 统计有标题的论文
        with_title = sum(1 for p in self.papers if p.title)
        print(f"有标题的论文: {with_title}")

        # 统计有作者的论文
        with_authors = sum(1 for p in self.papers if p.authors)
        print(f"有作者的论文: {with_authors}")

        # 统计有摘要的论文
        with_abstract = sum(1 for p in self.papers if p.abstract)
        print(f"有摘要的论文: {with_abstract}")

        # 统计有备注的论文
        with_notes = sum(1 for p in self.papers if p.notes)
        print(f"有备注的论文: {with_notes}")

        # 统计有分类的论文
        with_category = sum(1 for p in self.papers if "category" in p.extra)
        print(f"有分类的论文: {with_category}")

        # 显示 Collection 统计
        print(f"\nCollection 统计:")
        print(f"总 Collection 数: {len(self.collections)}")
        collections_with_children = sum(
            1 for c in self.collections.values() if c["children"]
        )
        print(f"有子目录的 Collection: {collections_with_children}")

        # 显示前5篇论文的标题
        print("\n前5篇论文:")
        for i, paper in enumerate(self.papers[:5], 1):
            print(
                f"{i}. {paper.title[:60]}..."
                if len(paper.title) > 60
                else f"{i}. {paper.title}"
            )
            if paper.authors:
                print(f"   作者: {paper.authors[:50]}...")
            if paper.year:
                print(f"   年份: {paper.year}")


def main():
    """主函数，用于命令行调用"""
    import sys

    rdf_file = "我的文库.rdf"
    if len(sys.argv) > 1:
        rdf_file = sys.argv[1]

    parser = ZoteroRDFParser(rdf_file)
    papers = parser.parse()
    parser.print_summary()

    # 导出为 JSON
    output_file = parser.export_to_json()
    print(f"\n解析结果已保存到: {output_file}")


if __name__ == "__main__":
    main()
