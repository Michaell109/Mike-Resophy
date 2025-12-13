import requests


def _download_arxiv_pdf(arxiv_id: str):
    # 优先尝试 export.arxiv.org
    pdf_urls = [
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",  # 备用
        f"https://export.arxiv.org/pdf/{arxiv_id}.pdf",  # 优先
    ]

    for pdf_url in pdf_urls:
        try:
            response = requests.get(pdf_url, timeout=5, stream=True)
            response.raise_for_status()
            pdf_content = response.content  # 读取全部内容到内存
            filename = f"{arxiv_id}.pdf"
            return pdf_content, filename
        except:
            continue  # 尝试下一个 URL

    return None  # 所有 URL 都失败


if __name__ == "__main__":
    import time

    start_time = time.time()
    pdf_content, filename = _download_arxiv_pdf("2512.10955")
    print("download success")
    end_time = time.time()
    print(f"download time: {end_time - start_time} seconds")
