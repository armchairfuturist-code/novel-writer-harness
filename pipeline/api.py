"""crofai API client - unified interface for all model calls.

Thin wrapper around httpx for OpenAI-compatible chat completions.
Handles auth, streaming, retries, and error formatting.
"""

import json
import time
from typing import Optional

import httpx

from config import Config, ModelConfig


class CrofaiClient:
    """HTTP client for crofai OpenAI-compatible API."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._http = httpx.Client(timeout=120.0)

    def chat(
        self,
        model: ModelConfig,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> str:
        """Send a chat completion request and return the response text.

        Args:
            model: ModelConfig for routing
            messages: Conversation messages [{"role": "user", "content": "..."}, ...]
            system_prompt: Optional system message prepended to messages
            temperature: Override model default
            max_tokens: Override model default

        Returns:
            Response text content
        """
        full_messages = list(messages)
        if system_prompt:
            full_messages.insert(0, {"role": "system", "content": system_prompt})

        body = {
            "model": model.name,
            "messages": full_messages,
            "temperature": temperature if temperature is not None else model.temperature,
            "max_tokens": max_tokens if max_tokens is not None else model.max_tokens,
            "top_p": model.top_p,
            "stream": stream,
        }

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = self._http.post(
                f"{self.config.base_url}/chat/completions",
                headers=headers,
                content=json.dumps(body),
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.text
            except Exception:
                pass
            raise RuntimeError(f"crofai API error {e.response.status_code}: {detail}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"crofai API timeout after {self._http.timeout}s") from e

    def chat_with_retry(
        self,
        model: ModelConfig,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_retries: int = 2,
        **kwargs,
    ) -> str:
        """Chat completion with automatic retry on failure."""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return self.chat(model, messages, system_prompt, **kwargs)
            except RuntimeError as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"All {max_retries + 1} attempts failed: {last_error}")

    def close(self):
        self._http.close()
