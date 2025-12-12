"""
API 测试工具函数
用于在启动 AI 任务前测试 API 连接
"""

from __future__ import annotations

from typing import Dict, Tuple


def test_llm_api(
    llm_model: str, llm_base_url: str, llm_api_key: str
) -> Tuple[bool, str]:
    """
    测试 LLM API 连接

    Args:
        llm_model: LLM 模型名称
        llm_base_url: LLM API 基础 URL
        llm_api_key: LLM API 密钥

    Returns:
        (success: bool, error_message: str)
        如果成功，error_message 为空字符串
    """
    if not llm_model or not llm_base_url or not llm_api_key:
        return (
            False,
            "请填写完整的 LLM API 配置（Model、Base URL、API Key）",
        )

    # 导入 OpenAI 客户端
    try:
        from openai import OpenAI
    except ImportError:
        return (
            False,
            "OpenAI 库未安装，请运行: pip install openai",
        )

    # 创建客户端
    try:
        client = OpenAI(
            base_url=llm_base_url,
            api_key=llm_api_key,
            timeout=30.0,  # 30秒超时
        )

        # 发送测试消息
        test_message = "Can you see my message, if you can, respond with Yes."
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "user", "content": test_message},
            ],
            max_tokens=50,  # 限制回复长度
        )

        # 检查回复
        if response.choices and len(response.choices) > 0:
            reply = response.choices[0].message.content.strip()
            # 检查是否包含 "Yes"（不区分大小写）
            if "yes" in reply.lower():
                return (True, "")
            else:
                return (
                    False,
                    f"LLM API 返回了回复，但不符合预期。回复内容: {reply}",
                )
        else:
            return (False, "LLM API 返回了空回复")

    except Exception as e:
        error_msg = str(e)
        # 提供更友好的错误信息
        if "401" in error_msg or "Unauthorized" in error_msg:
            return (False, "API Key 无效或未授权")
        elif "404" in error_msg or "Not Found" in error_msg:
            return (False, "API 端点不存在，请检查 Base URL 是否正确")
        elif "timeout" in error_msg.lower():
            return (False, "连接超时，请检查网络连接和 Base URL")
        else:
            return (False, f"LLM API 调用失败: {error_msg}")


def test_mineru_api(mineru_server_url: str) -> Tuple[bool, str]:
    """
    测试 MinerU API 连接

    Args:
        mineru_server_url: MinerU 服务 URL

    Returns:
        (success: bool, error_message: str)
        如果成功，error_message 为空字符串
    """
    if not mineru_server_url:
        return (False, "请填写 MinerU Server URL")

    try:
        import requests
    except ImportError:
        return (False, "requests 库未安装，请运行: pip install requests")

    # 移除末尾的斜杠
    mineru_server_url = mineru_server_url.rstrip("/")

    # 尝试连接 MinerU 服务
    # 通常 MinerU 服务可能有健康检查端点，如果没有则尝试根路径
    test_urls = [
        f"{mineru_server_url}/health",
        f"{mineru_server_url}/",
        f"{mineru_server_url}/api/health",
    ]

    last_error = None
    for test_url in test_urls:
        try:
            response = requests.get(
                test_url,
                timeout=10.0,  # 10秒超时
                allow_redirects=True,
            )
            # 如果返回 200-299 状态码，认为连接成功
            if 200 <= response.status_code < 300:
                return (True, "")
            # 如果是其他状态码，继续尝试下一个 URL
            last_error = f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            last_error = "连接超时"
            continue
        except requests.exceptions.ConnectionError:
            last_error = "无法连接到服务器"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    # 所有 URL 都失败
    return (
        False,
        f"MinerU API 连接失败: {last_error}。请检查 URL 是否正确，服务是否正在运行",
    )


