import argparse
import os
import re
import time

from deep_translator import GoogleTranslator
from tqdm import tqdm

# 1. 配置：允许处理的文件后缀 (已移除 .json)
ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".html",
    ".css",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".ts",
    ".tsx",
    ".vue",
    ".php",
    ".go",
    ".rb",
    ".txt",
    ".md",
    ".sql",
    ".xml",
    ".yaml",
    ".yml",
    ".sh",
    ".bat",
}

# 2. 配置：忽略的文件夹
IGNORED_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
    "vendor",
    "bin",
    "obj",
}


def contains_chinese(text):
    """检查文本中是否包含中文"""
    return bool(re.search(r"[\u4e00-\u9fa5]", text))


def process_file(file_path):
    """读取 -> 提取中文 -> tqdm进度条翻译 -> 覆盖"""
    try:
        # 读取文件
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 预检查：没中文直接退出，不显示任何信息
        if not contains_chinese(content):
            return

        # 正则：匹配连续的中文及中文标点
        chinese_pattern = re.compile(r"([\u4e00-\u9fa5|。|，|、|？|！|：|“|”|（|）]+)")
        matches = chinese_pattern.findall(content)
        unique_matches = list(set(matches))

        if not unique_matches:
            return

        # 打印当前正在处理的文件名
        print(f"📄 处理文件: {file_path}")

        # 初始化翻译器
        translator = GoogleTranslator(source="auto", target="en")
        translation_map = {}

        # 使用 tqdm 显示该文件的翻译进度
        # ncols控制宽度，unit显示单位，leave=False表示完成后清除进度条(可选，这里保留以便查看历史)
        with tqdm(
            total=len(unique_matches), desc="   翻译进度", unit="词", ncols=80
        ) as pbar:
            for text in unique_matches:
                try:
                    # 翻译
                    translated = translator.translate(text)
                    if not translated:
                        translated = text

                    translation_map[text] = translated

                    # 稍微延时，防止API限流
                    time.sleep(0.1)

                except Exception:
                    # 只有出错时才静默处理（保留原文）
                    translation_map[text] = text

                # 更新进度条
                pbar.update(1)

        # 替换逻辑
        def replace_match(match):
            return translation_map.get(match.group(0), match.group(0))

        new_content = chinese_pattern.sub(replace_match, content)

        # 覆盖写入
        if new_content != content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

    except UnicodeDecodeError:
        pass  # 忽略非文本文件
    except Exception as e:
        print(f"❌ 错误 {file_path}: {e}")


def process_folder(root_folder):
    if not os.path.exists(root_folder):
        print(f"❌ 错误: 路径不存在 '{root_folder}'")
        return

    # 遍历文件
    for root, dirs, files in os.walk(root_folder):
        # 排除忽略的目录
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file in files:
            ext = os.path.splitext(file)[1].lower()

            # 只处理白名单内的后缀
            if ext in ALLOWED_EXTENSIONS:
                full_path = os.path.join(root, file)
                process_file(full_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量翻译代码文件 (带进度条)")
    parser.add_argument("--folder", default="resophy/tools", help="目标文件夹路径")

    args = parser.parse_args()

    print(f"🚀 开始扫描目录: {args.folder} (不含 .json)")
    process_folder(args.folder)
    print("\n🎉 全部完成。")
