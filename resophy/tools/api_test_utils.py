"""
API test utility function
used at startup AI pre-task testing API connect
"""

from __future__ import annotations

from typing import Dict, Tuple


def test_llm_api(
    llm_model: str, llm_base_url: str, llm_api_key: str
) -> Tuple[bool, str]:
    """
    test LLM API connect

    Args:
        llm_model: LLM Model name
        llm_base_url: LLM API Base URL
        llm_api_key: LLM API key

    Returns:
        (success: bool, error_message: str)
        If successful,error_message is an empty string
    """
    if not llm_model or not llm_base_url or not llm_api_key:
        return (
            False,
            "Please fill in the complete LLM API configure(Model、Base URL、API Key）",
        )

    # import OpenAI client
    try:
        from openai import OpenAI
    except ImportError:
        return (
            False,
            "OpenAI The library is not installed, please run: pip install openai",
        )

    # Create client
    try:
        client = OpenAI(
            base_url=llm_base_url,
            api_key=llm_api_key,
            timeout=30.0,  # 30seconds timeout
        )

        # Send test message
        test_message = "Can you see my message, if you can, respond with Yes."
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "user", "content": test_message},
            ],
            max_tokens=50,  # Limit reply length
        )

        # check reply
        if response.choices and len(response.choices) > 0:
            reply = response.choices[0].message.content.strip()
            # Check if it contains "Yes"(not case sensitive)
            if "yes" in reply.lower():
                return (True, "")
            else:
                return (
                    False,
                    f"LLM API A response was returned, but not as expected. Reply content: {reply}",
                )
        else:
            return (False, "LLM API Returned an empty reply")

    except Exception as e:
        error_msg = str(e)
        # Provide friendlier error messages
        if "401" in error_msg or "Unauthorized" in error_msg:
            return (False, "API Key Invalid or unauthorized")
        elif "404" in error_msg or "Not Found" in error_msg:
            return (False, "API Endpoint does not exist, please check Base URL Is it correct?")
        elif "timeout" in error_msg.lower():
            return (False, "Connection timed out, please check network connection and Base URL")
        else:
            return (False, f"LLM API call failed: {error_msg}")


def test_mineru_api(mineru_server_url: str) -> Tuple[bool, str]:
    """
    test MinerU API connect

    Args:
        mineru_server_url: MinerU Serve URL

    Returns:
        (success: bool, error_message: str)
        If successful,error_message is an empty string
    """
    if not mineru_server_url:
        return (False, "Please fill in MinerU Server URL")

    try:
        import requests
    except ImportError:
        return (False, "requests The library is not installed, please run: pip install requests")

    # Remove trailing slash
    mineru_server_url = mineru_server_url.rstrip("/")

    # try to connect MinerU Serve
    # generally MinerU The service may have a health check endpoint, if not then the root path is tried
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
                timeout=10.0,  # 10seconds timeout
                allow_redirects=True,
            )
            # if return 200-299 Status code, the connection is considered successful
            if 200 <= response.status_code < 300:
                return (True, "")
            # If it is another status code, continue to try the next one URL
            last_error = f"HTTP {response.status_code}"
        except requests.exceptions.Timeout:
            last_error = "Connection timeout"
            continue
        except requests.exceptions.ConnectionError:
            last_error = "Unable to connect to server"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    # all URL All failed
    return (
        False,
        f"MinerU API Connection failed: {last_error}. Check, please URL Is it correct and the service is running?",
    )


