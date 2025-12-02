import pdfplumber

pdf_path = "2511.21631v1.pdf"
all_text = ""

try:
    with pdfplumber.open(pdf_path) as pdf:
        # 遍历前两页 (索引 0 和 1)
        # 注意：首先检查文件页数是否足够
        max_pages = min(1, len(pdf.pages))

        for i in range(max_pages):
            page = pdf.pages[i]  # page 1 是 pages[0], page 2 是 pages[1]

            # 使用 extract_text() 提取文本
            text = page.extract_text()

            all_text += f"--- 第 {i + 1} 页文本 ---\n"
            all_text += text if text else "（无文本内容）"
            all_text += "\n\n"

    print("=== 前两页提取的文本 ===")
    print(all_text)

except Exception as e:
    print(f"提取过程中发生错误: {e}")
