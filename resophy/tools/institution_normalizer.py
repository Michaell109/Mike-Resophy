"""
机构名称标准化工具

将 LLM 提取的各种机构名称变体统一映射到标准的缩写形式
"""

import json
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


class InstitutionNormalizer:
    """机构名称标准化器"""

    def __init__(
        self,
        mapping_file: Optional[str] = None,
        custom_mapping_file: Optional[str] = None,
    ):
        """
        初始化标准化器

        Args:
            mapping_file: 系统机构映射文件路径，如果为 None 则使用默认路径
            custom_mapping_file: 用户自定义机构映射文件路径（可选）
        """
        if mapping_file is None:
            # 使用默认路径（与此文件同目录下的 instituionMap.json）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            mapping_file = os.path.join(current_dir, "instituionMap.json")

        self.mapping_file = mapping_file
        self.custom_mapping_file = custom_mapping_file
        self.institution_map: Dict[str, List[str]] = {}
        self._load_mapping()

        # 构建反向索引：全名/变体 -> 标准缩写（用于快速精确匹配）
        # 使用标准化后的字符串作为键
        self._build_reverse_index()

    def _normalize_string(self, text: str) -> str:
        """
        标准化字符串：去除标点、统一大小写、标准化后缀等

        Args:
            text: 原始字符串

        Returns:
            标准化后的字符串
        """
        if not text:
            return ""

        # 1. 去除首尾空格并转换为小写
        normalized = text.strip().lower()

        # 2. 去除标点符号（保留空格和字母数字）
        # 去除常见的标点：逗号、句号、分号、冒号等
        normalized = re.sub(r'[,.;:!?()\[\]{}"\']+', "", normalized)

        # 3. 标准化常见机构后缀
        # 定义后缀映射表
        suffix_mappings = {
            r"\binc\.?\b": "inc",
            r"\binc,\b": "inc",
            r"\bltd\.?\b": "ltd",
            r"\blimited\b": "ltd",
            r"\bcorp\.?\b": "corp",
            r"\bcorporation\b": "corp",
            r"\blab\.?\b": "lab",
            r"\blaboratory\b": "lab",
            r"\buniv\.?\b": "univ",
            r"\buniversity\b": "univ",
            r"\bcollege\b": "college",
            r"\bschool\b": "school",
            r"\binstitute\b": "inst",
            r"\binstitution\b": "inst",
        }

        for pattern, replacement in suffix_mappings.items():
            normalized = re.sub(pattern, replacement, normalized)

        # 4. 去除多余空格（合并连续空格为单个空格）
        normalized = re.sub(r"\s+", " ", normalized)

        # 5. 再次去除首尾空格
        normalized = normalized.strip()

        return normalized

    def _extract_core_words(self, text: str) -> str:
        """
        提取核心词（去除常见后缀和停用词）

        Args:
            text: 标准化后的字符串

        Returns:
            核心词字符串
        """
        if not text:
            return ""

        # 常见停用词和后缀
        stop_words = {"the", "of", "and", "at", "in", "on", "for", "to", "a", "an"}
        suffixes = {
            "inc",
            "ltd",
            "corp",
            "lab",
            "univ",
            "college",
            "school",
            "inst",
            "university",
        }

        # 分割单词
        words = text.split()

        # 过滤停用词和后缀
        core_words = [w for w in words if w not in stop_words and w not in suffixes]

        return " ".join(core_words) if core_words else text

    def _load_mapping(self):
        """加载机构映射文件（系统 + 用户自定义）"""
        # 先加载系统映射
        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                self.institution_map = json.load(f)
            print(
                f"[InstitutionNormalizer] 成功加载系统映射: {len(self.institution_map)} 个机构"
            )
        except FileNotFoundError:
            print(
                f"[InstitutionNormalizer] 警告: 系统映射文件不存在 {self.mapping_file}"
            )
            self.institution_map = {}
        except json.JSONDecodeError as e:
            print(f"[InstitutionNormalizer] 错误: 系统映射文件格式错误 {e}")
            self.institution_map = {}

        # 加载用户自定义映射（会覆盖系统映射中的同名机构）
        if self.custom_mapping_file and os.path.exists(self.custom_mapping_file):
            try:
                with open(self.custom_mapping_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    custom_map = settings.get("customInstitutions", {})

                    if custom_map:
                        # 合并到系统映射中（用户自定义优先）
                        self.institution_map.update(custom_map)
                        print(
                            f"[InstitutionNormalizer] 成功加载用户自定义映射: {len(custom_map)} 个机构"
                        )
            except Exception as e:
                print(f"[InstitutionNormalizer] 加载用户自定义映射失败: {e}")

    def _build_reverse_index(self):
        """
        构建反向索引，用于快速精确匹配
        使用标准化后的字符串作为键，提高匹配成功率
        """
        self.reverse_index: Dict[str, str] = {}
        self.normalized_index: Dict[str, str] = {}  # 标准化后的索引
        self.core_words_index: Dict[str, str] = {}  # 核心词索引

        for standard_name, variants in self.institution_map.items():
            # 1. 原始小写索引（保持向后兼容）
            self.reverse_index[standard_name.lower()] = standard_name
            for variant in variants:
                self.reverse_index[variant.lower()] = standard_name

            # 2. 标准化索引（去除标点、标准化后缀）
            normalized_standard = self._normalize_string(standard_name)
            if normalized_standard:
                self.normalized_index[normalized_standard] = standard_name

            for variant in variants:
                normalized_variant = self._normalize_string(variant)
                if normalized_variant:
                    self.normalized_index[normalized_variant] = standard_name

            # 3. 核心词索引（用于部分匹配）
            core_standard = self._extract_core_words(normalized_standard)
            if core_standard:
                # 如果核心词索引中还没有这个标准名称，添加它
                if core_standard not in self.core_words_index:
                    self.core_words_index[core_standard] = standard_name
                # 如果有多个变体映射到同一个核心词，保持第一个（通常是标准名称）

            for variant in variants:
                normalized_variant = self._normalize_string(variant)
                core_variant = self._extract_core_words(normalized_variant)
                if core_variant and core_variant not in self.core_words_index:
                    self.core_words_index[core_variant] = standard_name

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """
        计算两个字符串的相似度（0-1）

        使用 SequenceMatcher 计算相似度，并考虑多种匹配策略
        """
        s1_lower = str1.lower().strip()
        s2_lower = str2.lower().strip()

        # 1. 完全相同
        if s1_lower == s2_lower:
            return 1.0

        # 2. 一个包含另一个（较短的完全在较长的里面）
        if s1_lower in s2_lower or s2_lower in s1_lower:
            shorter = min(len(s1_lower), len(s2_lower))
            longer = max(len(s1_lower), len(s2_lower))
            # 如果较短的长度占较长的 70% 以上，认为相似度较高
            if shorter / longer > 0.7:
                return 0.88

        # 3. 使用 SequenceMatcher 计算序列相似度
        ratio = SequenceMatcher(None, s1_lower, s2_lower).ratio()

        # 4. 如果相似度较低但包含相同的关键词，可以提升一些分数
        # 提取单词
        words1 = set(s1_lower.split())
        words2 = set(s2_lower.split())
        common_words = words1 & words2

        # 如果有共同的长单词（>3字符），提升相似度
        if common_words:
            long_common_words = [w for w in common_words if len(w) > 3]
            if long_common_words:
                # 提升幅度取决于共同单词的比例
                word_overlap = len(common_words) / max(len(words1), len(words2))
                ratio = max(ratio, 0.7 * word_overlap + 0.3 * ratio)

        return ratio

    def _fuzzy_match(
        self, extracted_name: str, threshold: float = 0.85
    ) -> Optional[str]:
        """
        模糊匹配机构名称

        Args:
            extracted_name: LLM 提取的机构名称
            threshold: 相似度阈值（默认 0.80）

        Returns:
            匹配到的标准缩写，如果没有匹配则返回 None
        """
        best_match = None
        best_score = threshold

        # 遍历所有标准名称及其变体
        for standard_name, variants in self.institution_map.items():
            # 检查标准名称本身
            score = self._calculate_similarity(extracted_name, standard_name)
            if score > best_score:
                best_score = score
                best_match = standard_name

            # 检查所有变体
            for variant in variants:
                score = self._calculate_similarity(extracted_name, variant)
                if score > best_score:
                    best_score = score
                    best_match = standard_name

        return best_match

    def normalize(
        self, extracted_name: str, fuzzy: bool = True, threshold: float = 0.85
    ) -> str:
        """
        标准化机构名称（使用层次化匹配策略）

        Args:
            extracted_name: LLM 提取的机构名称
            fuzzy: 是否使用模糊匹配（默认 True）
            threshold: 模糊匹配的相似度阈值（默认 0.85）

        Returns:
            标准化后的机构缩写（如果无法匹配，返回原名称）
        """
        if not extracted_name or not extracted_name.strip():
            return extracted_name

        name = extracted_name.strip()
        name_lower = name.lower()

        # ===== 第一层：精确匹配（原始小写） =====
        exact_match = self.reverse_index.get(name_lower)
        if exact_match:
            return exact_match

        # ===== 第二层：标准化后精确匹配 =====
        normalized_name = self._normalize_string(name)
        if normalized_name:
            normalized_match = self.normalized_index.get(normalized_name)
            if normalized_match:
                print(
                    f"[InstitutionNormalizer] 标准化匹配: '{name}' -> '{normalized_match}'"
                )
                return normalized_match

        # ===== 第三层：核心词匹配 =====
        core_words = self._extract_core_words(normalized_name)
        if core_words:
            # 检查核心词是否完全匹配
            core_match = self.core_words_index.get(core_words)
            if core_match:
                print(f"[InstitutionNormalizer] 核心词匹配: '{name}' -> '{core_match}'")
                return core_match

            # 检查包含关系：核心词是否包含在某个配置的核心词中，或反之
            for config_core, standard_name in self.core_words_index.items():
                # 如果提取的核心词包含配置的核心词，或配置的核心词包含提取的核心词
                if core_words in config_core or config_core in core_words:
                    # 进一步检查：确保不是太短的匹配（避免误匹配）
                    min_length = min(len(core_words), len(config_core))
                    if min_length >= 3:  # 至少3个字符
                        print(
                            f"[InstitutionNormalizer] 核心词包含匹配: '{name}' -> '{standard_name}'"
                        )
                        return standard_name

        # ===== 第四层：模糊匹配（如果启用） =====
        if fuzzy:
            fuzzy_match = self._fuzzy_match(name, threshold)
            if fuzzy_match:
                print(f"[InstitutionNormalizer] 模糊匹配: '{name}' -> '{fuzzy_match}'")
                return fuzzy_match

        # ===== 无法匹配，返回原名称 =====
        return name

    def normalize_list(
        self,
        extracted_names: List[str],
        fuzzy: bool = True,
        threshold: float = 0.85,
        deduplicate: bool = True,
    ) -> List[str]:
        """
        批量标准化机构名称列表

        Args:
            extracted_names: LLM 提取的机构名称列表
            fuzzy: 是否使用模糊匹配
            threshold: 模糊匹配的相似度阈值
            deduplicate: 是否去重（默认 True）

        Returns:
            标准化后的机构缩写列表
        """
        normalized = []
        seen = set()

        for name in extracted_names:
            standard_name = self.normalize(name, fuzzy=fuzzy, threshold=threshold)

            if deduplicate:
                # 去重：如果标准化后的名称已存在，跳过
                if standard_name.lower() not in seen:
                    seen.add(standard_name.lower())
                    normalized.append(standard_name)
            else:
                normalized.append(standard_name)

        return normalized

    def get_statistics(self) -> Dict[str, int]:
        """
        获取映射统计信息

        Returns:
            包含统计信息的字典
        """
        total_variants = sum(
            len(variants) for variants in self.institution_map.values()
        )
        return {
            "total_institutions": len(self.institution_map),
            "total_variants": total_variants,
            "average_variants_per_institution": (
                total_variants / len(self.institution_map)
                if self.institution_map
                else 0
            ),
        }


# 创建全局单例实例
_normalizer_instance: Optional[InstitutionNormalizer] = None


def get_normalizer() -> InstitutionNormalizer:
    """获取全局标准化器实例（单例模式）"""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = InstitutionNormalizer()
    return _normalizer_instance


def normalize_institution(extracted_name: str) -> str:
    """
    标准化单个机构名称（便捷函数）

    Args:
        extracted_name: LLM 提取的机构名称

    Returns:
        标准化后的机构缩写
    """
    normalizer = get_normalizer()
    return normalizer.normalize(extracted_name)


def normalize_institutions(extracted_names: List[str]) -> List[str]:
    """
    标准化机构名称列表（便捷函数）

    Args:
        extracted_names: LLM 提取的机构名称列表

    Returns:
        标准化后的机构缩写列表
    """
    normalizer = get_normalizer()
    return normalizer.normalize_list(extracted_names)


if __name__ == "__main__":
    # 测试代码
    normalizer = InstitutionNormalizer()

    # 打印统计信息
    stats = normalizer.get_statistics()
    print("\n=== 机构映射统计 ===")
    print(f"标准机构数: {stats['total_institutions']}")
    print(f"总变体数: {stats['total_variants']}")
    print(f"平均每个机构的变体数: {stats['average_variants_per_institution']:.2f}")

    # 测试用例
    test_cases = [
        "Tsinghua University",
        "THU",
        "Massachusetts Institute of Technology",
        "MIT",
        "Google Brain",
        "Google Research",
        "Fudan University",
        "The University of Hong Kong",
        "HKU",
        "University of California Berkeley",
        "Berkeley",
        "Cal",
        "Random University",  # 不存在的机构
        "Tsing hua",  # 拼写错误（模糊匹配测试）
    ]

    print("\n=== 标准化测试 ===")
    for test_name in test_cases:
        normalized = normalizer.normalize(test_name)
        # 检查是否匹配成功（通过反向索引或模糊匹配）
        exact_match = normalizer.reverse_index.get(test_name.lower())
        if exact_match:
            # 精确匹配
            print(f"✓ {test_name:40s} -> {normalized} (精确)")
        elif normalized != test_name:
            # 模糊匹配
            print(f"✓ {test_name:40s} -> {normalized} (模糊)")
        else:
            # 无匹配
            print(f"✗ {test_name:40s} -> (无匹配)")

    # 测试批量标准化
    print("\n=== 批量标准化测试 ===")
    test_list = [
        "Tsinghua University",
        "THU",  # 应该被去重
        "Peking University",
        "PKU",  # 应该被去重
        "MIT",
        "Stanford University",
    ]
    normalized_list = normalizer.normalize_list(test_list, deduplicate=True)
    print(f"输入: {test_list}")
    print(f"输出: {normalized_list}")
