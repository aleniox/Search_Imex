import os
import requests

LLM_API = os.getenv("LLM_API_URL", "http://localhost:8080/v1/chat/completions")


def call_chat_api(messages, model="", stream=True, max_token=40000, host=LLM_API):
    payload = {
        "model": model, "messages": messages, "stream": stream,
        "options": {"temperature": 0.0, "top_p": 0.95, "top_k": 64, "num_ctx": max_token},
    }
    return requests.post(host, json=payload, stream=stream)


class LLMClient:
    def __init__(self, api_url: str = None):
        self.api_url = api_url or LLM_API

    def call(self, system_prompt: str, user_msg: str = None) -> str | None:
        messages = [{"role": "system", "content": system_prompt}]
        if user_msg:
            messages.append({"role": "user", "content": user_msg})
        resp = call_chat_api(messages=messages, stream=False, host=self.api_url)
        if resp.status_code != 200:
            return None
        return resp.json()["choices"][0]["message"]["content"]
