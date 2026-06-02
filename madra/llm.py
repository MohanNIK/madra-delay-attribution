from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol
from urllib import request, error


class LLMClient(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict[str, Any]:
        ...


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat-completions client using only stdlib.

    Environment variables:
    - DASHSCOPE_API_KEY or OPENAI_API_KEY: API key.
    - OPENAI_BASE_URL: defaults to Qwen/DashScope compatible mode in China.
    - OPENAI_MODEL or DASHSCOPE_MODEL: defaults to qwen-plus.

    This also works with many OpenAI-compatible providers when their base URL
    ends at /v1 and supports /chat/completions.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: int = 120,
    ):
        self.api_key = api_key or first_env("DASHSCOPE_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY")
        self.base_url = (
            base_url
            or first_env("DASHSCOPE_BASE_URL", "QWEN_BASE_URL", "OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self.model = model or first_env("DASHSCOPE_MODEL", "QWEN_MODEL", "OPENAI_MODEL") or "qwen-plus"
        self.temperature = temperature
        self.timeout = timeout
        self.madra_stats = {
            "api_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "malformed_output_count": 0,
        }
        if not self.api_key:
            raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY.")
        if not self.model:
            raise RuntimeError("Missing DASHSCOPE_MODEL or QWEN_MODEL. Set it explicitly for reproducible experiments.")

    def complete_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API HTTP {exc.code}: {detail}") from exc

        self.madra_stats["api_calls"] += 1
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        self.madra_stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.madra_stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        self.madra_stats["total_tokens"] += int(usage.get("total_tokens") or 0)
        content = data["choices"][0]["message"]["content"]
        try:
            return parse_json_object(content)
        except Exception:
            self.madra_stats["malformed_output_count"] += 1
            raise


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object from the LLM.")
    return parsed
