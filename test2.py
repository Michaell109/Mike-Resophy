import re

import fitz  # PyMuPDF


def get_title_robust(pdf_path):
    doc = fitz.open(pdf_path)
    page = doc[0]  # 只看第一页
    rect = page.rect  # 获取页面尺寸 (width, height)
    page_width = rect.width
    page_height = rect.height

    # 获取所有文本块
    blocks = page.get_text("dict")["blocks"]

    # 收集所有的文本片段 (text, size, bbox)
    all_spans = []
    for block in blocks:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                # 保存: (字体大小, 文本内容, 边界框)
                all_spans.append((span["size"], text, span["bbox"]))

    # 按字体大小从大到小排序
    # 如果大小相同，按在页面中出现的垂直位置(y0)排序
    all_spans.sort(key=lambda x: (-x[0], x[2][1]))

    if not all_spans:
        return None

    # --- 核心逻辑：寻找真正的标题 ---
    # 我们不仅找最大的，还要过滤掉那是“噪声”的最大文本

    title_candidates = []
    target_size = 0

    for size, text, bbox in all_spans:
        # 1. 内容过滤 (Regex Filter)
        # 如果文本看起来像 arXiv ID、日期、或者只有一两个字符，跳过
        if re.search(r"arxiv:\d{4}\.\d+", text, re.IGNORECASE):
            continue
        if len(text) < 5:  # 标题一般不会短于5个字符
            continue

        # 2. 位置过滤 (Coordinate Filter)
        # bbox = [x0, y0, x1, y1]
        # 如果文本主要位于页面的极左侧边缘 (arXiv sidebar 通常在这里)
        # 例如：右边界(x1) 都在页面宽度的 15% 以内，说明在左侧边栏
        if bbox[2] < page_width * 0.15:
            continue

        # 3. 确定标题
        # 如果我们还没确定标题的字号，那么当前这个通过了过滤的“最大字体”就是标题字号
        if target_size == 0:
            target_size = size
            title_candidates.append(text)
        # 如果当前字体和标题字体一样大（处理多行标题），加入列表
        # 允许微小的浮点误差 (0.1)
        elif abs(size - target_size) < 0.5:
            title_candidates.append(text)
        # 如果字体明显变小了，说明标题部分结束了（进入了作者列表或正文）
        else:
            break

    return " ".join(title_candidates)


# --- 测试 ---
pdf_path = "RexThinker_ICLR.pdf"
title = get_title_robust(pdf_path)
print(f"提取的标题: {title}")
