import argparse

from openai import OpenAI

# Modify OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "token-abc123"
openai_api_base = "http://192.168.81.133:8080/v1"

SYSTEM_PROMPT = """
请以中文 markdown 的形式为这篇文章写一个公众号风格的包含有详细内容的长推文，内容要详细且丰富，
实验内容也要充分，比如包括消融实验。注意你一定要使用原始markdown 中的图片和表格来让你的公众号文章更加清晰，
图片,比如模型结构，teaser，或者一些结果图，阐释图直接插入到正文对应位置之中，不要放到最后。图片对于一个公众号文章来说很重要

INPUT: <MARKDOWN>
"""

ori_markdown = "ori_markdown.md"
with open(ori_markdown, "r") as f:
    markdown = f.read()

messages = [
    {"role": "user", "content": SYSTEM_PROMPT.replace("<MARKDOWN>", markdown)},
]


client = OpenAI(
    # defaults to os.environ.get("OPENAI_API_KEY")
    api_key=openai_api_key,
    base_url=openai_api_base,
)

models = client.models.list()
model = models.data[0].id

# Chat Completion API
chat_completion = client.chat.completions.create(
    messages=messages,
    model=model,
)

result = chat_completion.choices[0].message.content

with open("result.md", "w") as f:
    f.write(result)
