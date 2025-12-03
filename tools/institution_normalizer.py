"""
机构名称标准化工具

将 LLM 提取的各种机构名称变体统一映射到标准的缩写形式
"""

import json
import os
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


class InstitutionNormalizer:
    """机构名称标准化器"""

    def __init__(self, mapping_file: Optional[str] = None, custom_mapping_file: Optional[str] = None):
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
        self._build_reverse_index()

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
            print(f"[InstitutionNormalizer] 警告: 系统映射文件不存在 {self.mapping_file}")
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
        """构建反向索引，用于快速精确匹配"""
        self.reverse_index: Dict[str, str] = {}

        for standard_name, variants in self.institution_map.items():
            # 标准名称本身也加入索引（指向自己）
            self.reverse_index[standard_name.lower()] = standard_name

            # 所有变体也加入索引（指向标准名称）
            for variant in variants:
                self.reverse_index[variant.lower()] = standard_name

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
        标准化机构名称

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

        # 1. 首先尝试精确匹配（使用反向索引）
        exact_match = self.reverse_index.get(name.lower())
        if exact_match:
            return exact_match

        # 2. 如果启用模糊匹配，尝试模糊匹配
        if fuzzy:
            fuzzy_match = self._fuzzy_match(name, threshold)
            if fuzzy_match:
                print(
                    f"[InstitutionNormalizer] 模糊匹配: '{name}' -> '{fuzzy_match}'"
                )
                return fuzzy_match

        # 3. 无法匹配，返回原名称
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

