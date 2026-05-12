"""crofai API client — unified interface for all model calls.

Thin wrapper around httpx for OpenAI-compatible chat completions.
Handles auth, streaming, retries, caching, and context management.
"""

import hashlib
import json
import os
import time
from typing import Optional

import httpx

from config import Config, ModelConfig

# Cache directory for API responses (disabled by default)
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".api-cache")


def _cache_key(model: ModelConfig, messages: list[dict], system_prompt: Optional[str]) -> str:
    """Generate a deterministic cache key from request parameters."""
    raw = f"{model.name}|{json.dumps(messages, sort_keys=True)}|{system_prompt or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _read_cache(cache_key: str) -> Optional[str]:
    """Read cached response if caching is enabled and key exists."""
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data["response"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    return None


def _write_cache(cache_key: str, response: str):
    """Write response to cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"response": response}, f)
    except OSError:
        pass  # Cache writes are best-effort


def _unwrap_json(text: str) -> str:
    """Strip markdown code fences from model output.

    Many models wrap JSON in ```json ... ``` fences. This utility
    strips fences and returns clean JSON text.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        cleaned = [l for l in lines if not l.startswith("```")]
        text = "\n".join(cleaned)
    return text


def _repair_json(text: str) -> str:
    """Attempt to repair common JSON model output issues.

    Handles:
    1. Literal newlines inside string values (escape them)
    2. Bare parenthetical annotations like 'age: 10 (child) / 26 (adult)'
    """
    import re

    # 1. Escape literal newlines inside JSON strings.
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            result.append(ch)
            continue
        if ch == chr(92):
            escape = True
            result.append(ch)
            continue
        if ch == chr(34):
            in_string = not in_string
            result.append(ch)
            continue
        if ch == chr(10) and in_string:
            result.append(chr(92) + 'n')
            continue
        result.append(ch)
    text = ''.join(result)

    # 2. Fix bare unquoted values with parenthetical annotations on their own lines.
    #    Only apply to lines that are unparseable by normal JSON.
    #    First try parsing the cleaned text.
    try:
        import json as _json
        _json.loads(text)
        return text  # Already valid after step 1
    except _json.JSONDecodeError:
        pass

    # 3. Line-level repair for unquoted annotations
    lines = text.split(chr(10))
    fixed_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip structural lines
        if stripped in ('{', '}', '[', ']', '', ',') or stripped.startswith('//'):
            fixed_lines.append(line)
            continue
        if chr(58) in stripped:
            colon_idx = stripped.index(chr(58))
            key_part = stripped[:colon_idx]
            val_part = stripped[colon_idx + 1:].strip()

            if val_part and not val_part.startswith(chr(34)) and not val_part.startswith(chr(91)) and not val_part.startswith(chr(123)):
                has_paren = chr(40) in val_part
                slash = chr(47)
                has_slash = slash in val_part.replace('//', chr(32))
                has_number = bool(re.search(r'[0-9]', val_part))
                if (has_paren or has_slash) and has_number:
                    comma = chr(44) if val_part.endswith(chr(44)) else ''
                    clean_val = val_part.rstrip(chr(44))
                    indent = line[:len(line) - len(line.lstrip())]
                    new_line = indent + key_part + chr(58) + chr(32) + chr(34) + clean_val + chr(34) + comma
                    fixed_lines.append(new_line)
                    continue
        fixed_lines.append(line)

    return chr(10).join(fixed_lines)
def parse_json_output(content: str, label: str = "response") -> dict:
    """Parse a model's JSON output, handling markdown wrapping and errors.

    Args:
        content: Raw model response text
        label: Human-readable label for error messages

    Returns:
        Parsed dict

    Raises:
        RuntimeError: If JSON cannot be extracted
    """
    content = _unwrap_json(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end+1])
            except json.JSONDecodeError:
                pass
        # Try repair before giving up
        repaired = _repair_json(content)
        if repaired != content:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                start2 = repaired.find("{")
                end2 = repaired.rfind("}")
                if start2 != -1 and end2 != -1 and end2 > start2:
                    try:
                        return json.loads(repaired[start2:end2+1])
                    except json.JSONDecodeError:
                        pass
        raise RuntimeError(
            f"Failed to parse {label} as JSON. "
            f"Response preview: {content[:300]}"
        )


def _is_retryable(status_code: int) -> bool:
    """Determine if an HTTP status code should be retried.

    Only retry on:
    - 429 (rate limited) — may succeed after backoff
    - 5xx (server errors) — transient issues
    """
    return status_code == 429 or (500 <= status_code < 600)


class CrofaiClient:
    """HTTP client for crofai OpenAI-compatible API."""

    def __init__(self, config: Optional[Config] = None, use_cache: bool = False):
        self.config = config or Config()
        self._http = httpx.Client(timeout=600.0)
        self.use_cache = use_cache

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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
        # Check cache first
        ck = _cache_key(model, messages, system_prompt)
        if self.use_cache:
            cached = _read_cache(ck)
            if cached is not None:
                return cached

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
            result = data["choices"][0]["message"]["content"]

            # Cache the result
            if self.use_cache:
                _write_cache(ck, result)

            return result
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            detail = ""
            try:
                detail = e.response.text[:500]
            except Exception:
                pass
            raise RuntimeError(f"API error {status}: {detail}") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"API timeout after {self._http.timeout}s") from e

    def chat_with_retry(
        self,
        model: ModelConfig,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_retries: int = 2,
        **kwargs,
    ) -> str:
        """Chat completion with smart retry.

        Only retries on transient errors (429 rate limit, 5xx server errors).
        401 (auth), 404, and 400 (bad request) fail immediately.
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return self.chat(model, messages, system_prompt, **kwargs)
            except RuntimeError as e:
                last_error = e
                err_msg = str(e)

                # Extract status code from error message
                status_code = 0
                for prefix in ["API error ", "crofai API error "]:
                    if prefix in err_msg:
                        try:
                            code_str = err_msg.split(prefix)[1].split(":")[0].strip()
                            status_code = int(code_str)
                        except (ValueError, IndexError):
                            pass
                        break

                # Don't retry non-transient errors
                if status_code and not _is_retryable(status_code):
                    raise

                if attempt < max_retries:
                    delay = 2 ** attempt
                    time.sleep(delay)

        raise RuntimeError(f"All {max_retries + 1} attempts failed: {last_error}")

    def close(self):
        self._http.close()
