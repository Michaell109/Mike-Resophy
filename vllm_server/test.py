from openai import OpenAI

client = OpenAI(
    base_url="http://192.168.81.130:8080/v1",
    api_key="token-abc123",
)

completion = client.chat.completions.create(
    model="/comp_robot/jiangqing/projects/2023/research/R1/QwenSFTOfficial/mounted_files/checkpoints/Qwen/Qwen2.5-7B-Instruct",
    messages=[
        {"role": "user", "content": "Write a long ghost story with 10000 words"},
    ],
)

print(completion.choices[0].message)
