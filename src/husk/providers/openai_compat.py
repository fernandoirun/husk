"""A minimal OpenAI-compatible chat client.

The ``/v1/chat/completions`` shape is a de-facto standard: OpenAI, DeepSeek,
Together, Groq, vLLM and Ollama all speak it. So one small client reaches every
provider -- you only change three environment variables.

    HUSK_BASE_URL        e.g. https://api.openai.com/v1  (default)
                              https://api.deepseek.com/v1
                              http://localhost:11434/v1   (Ollama)
    HUSK_API_KEY         bearer token (blank for local servers)
    HUSK_MODEL           e.g. gpt-4o-mini, deepseek-chat, llama3.1
    HUSK_CONTEXT_WINDOW  token window, used for compaction (default 128000)
"""
from __future__ import annotations

import os

import httpx


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        context_window: int | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("HUSK_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("HUSK_API_KEY", "")
        self.model = model or os.getenv("HUSK_MODEL", "gpt-4o-mini")
        self.context_window = context_window or int(os.getenv("HUSK_CONTEXT_WINDOW", "128000"))
        self._client = httpx.Client(timeout=timeout)

    def chat(self, messages: list, tools: list | None = None) -> dict:
        """Send one chat-completion request; return the assistant message dict."""
        payload: dict = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        resp = self._client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()  # raises on 4xx/5xx
        # A 200 is not a guarantee of a usable body: gateways pass provider
        # errors through as 200 {"error": ...}, content filters return a choice
        # with no message, empty completions return {"choices": []}. Parse
        # defensively and surface a clear error instead of a KeyError/IndexError.
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"provider returned a non-JSON body: {e}") from e
        choices = data.get("choices")
        if not choices:
            err = data.get("error")
            detail = err.get("message") if isinstance(err, dict) else err
            raise RuntimeError(f"provider returned no choices: {detail or data}")
        msg = choices[0].get("message")
        if msg is None:
            raise RuntimeError(f"provider choice had no message (finish_reason={choices[0].get('finish_reason')})")
        # Strip null-valued keys: some servers reject a null 'content' on the
        # next round-trip when the assistant turn is tool-calls only.
        return {k: v for k, v in msg.items() if v is not None}

    def close(self) -> None:
        self._client.close()
