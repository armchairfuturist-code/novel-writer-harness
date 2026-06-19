"""LLM API client — unified interface for all model calls.

Thin wrapper around httpx for OpenAI-compatible chat completions.
Works with any OpenAI-compatible provider (OpenAI, crof.ai, Together, etc.).
Set LLM_BASE_URL + LLM_API_KEY env vars for your provider.
crof.ai users can continue using just CROFAI_API_KEY (unchanged).
Handles auth, streaming, retries, caching, and context management.

Usage:
    from pipeline.api import CrofaiClient
    client = CrofaiClient()
    response = client.chat(model_config, messages)
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

    # 3. Line-level repair for unquoted annotations.
    #    Only wrap the value up to the next comma or close-bracket.
    import re as _re3
    lines = text.split(chr(10))
    fixed_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip structural lines
        if stripped in ('{', '}', '[', ']', '', ',') or stripped.startswith('//'):
            fixed_lines.append(line)
            continue
        # Match 'key': bare_value_pattern up to comma or end
        m = _re3.match(r'^([^:]+):\s*(\d[^,}]*?)([,}])(.*)$', stripped)
        if m:
            key_part = m.group(1)
            bare_val = m.group(2).rstrip()
            closer = m.group(3)
            rest = m.group(4)
            # Check for parenthetical or annotated values
            if (chr(40) in bare_val or chr(47) in bare_val) and _re3.search(r'[0-9]', bare_val):
                indent = line[:len(line) - len(line.lstrip())]
                comma = chr(44) if closer == chr(44) else ''
                new_line = indent + key_part + chr(58) + chr(32) + chr(34) + bare_val + chr(34) + closer + rest
                fixed_lines.append(new_line)
                continue
        fixed_lines.append(line)

    # 4. Final fallback: brace-counting extraction as dict
    extracted = _extract_json(text)
    if extracted is not None:
        return json.dumps(extracted)
    return chr(10).join(fixed_lines)

def _extract_json(text: str) -> dict:
    """Extract the outermost JSON object from text, handling common issues."""
    import re as _re
    
    # Remove trailing commas before ] or }
    text = _re.sub(r',\s*(?=[}\]])', '', text)
    
    # Find outermost { ... } via brace counting  
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == chr(123):
            if depth == 0:
                start = i
            depth += 1
        elif ch == chr(125):
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start:i+1]
                try:
                    import json as _json
                    return _json.loads(candidate)
                except _json.JSONDecodeError:
                    pass
    return None


def _looks_truncated(text: str) -> bool:
    """Heuristic: response looks cut off mid-stream.

    True when the response is clearly incomplete: doesn't end with a
    closing brace after unwrap, OR ends inside an unterminated string
    (odd number of unescaped quotes in the tail).
    """
    stripped = text.rstrip()
    if not stripped:
        return False
    # Healthy JSON ends with } (object) or ] (array). Allow trailing whitespace.
    if stripped[-1] in ("}", "]"):
        return False
    # Otherwise it's incomplete — confirm by checking for unbalanced braces.
    depth = 0
    in_string = False
    escape = False
    for ch in stripped:
        if escape:
            escape = False
            continue
        if ch == chr(92):
            escape = True
            continue
        if ch == chr(34):
            in_string = not in_string
            continue
        if not in_string:
            if ch == chr(123):
                depth += 1
            elif ch == chr(125):
                depth -= 1
    # If still open OR ended inside a string, it's truncated.
    return depth > 0 or in_string


def _looks_truncated_prose(text: str, min_chars: int = 200,
                           tail_window: int = 80) -> bool:
    """Heuristic: free-form prose response looks cut off mid-stream.

    Distinct from _looks_truncated (JSON-shape aware). For prose we look at
    the last `tail_window` characters and check that the text ends on a
    terminal sentence boundary. If the final window has NO terminal
    punctuation, the model stopped mid-thought — flag as truncated.

    The check intentionally tolerates:
    - Dialogue tags after closing quotes ('"Yes." He left.' is complete)
    - Trailing whitespace/newlines
    - Markdown structures (#, *, -, > endings)

    Args:
        text: Response text to evaluate
        min_chars: Don't flag short responses (likely intentional fragments)
        tail_window: Size of trailing window to scan for terminal punctuation

    Returns:
        True if the prose clearly stops mid-sentence.
    """
    stripped = text.rstrip()
    if not stripped or len(stripped) < min_chars:
        return False

    # Markdown structural endings are considered complete by intent.
    last = stripped[-1]
    if last in "#*-":
        return False
    # Look at the last 5 characters. A response ending on a terminal
    # sentence-ender (period, !, ?, or closing quote) is complete. An
    # ending with no ender in this tight window is mid-thought.
    # Using a tight window (5 chars) avoids false-positives from quotes
    # that are mid-dialogue, opening italics, etc.
    last_5 = stripped[-5:]
    # Sentence-enders: terminal punctuation, closing quotes. We treat
    # any straight " as an ender when it appears at the very end OR is
    # immediately followed by a space, capital, or EOL. This avoids
    # treating opening quotes ('"The' in '"The press') as completion.
    enders = set('.!?)\u201d\u2019\u2014')
    for ch in last_5:
        if ch in enders:
            return False
    # Last char is straight double-quote and it IS at the very end
    # of the response (true closing quote) — also complete.
    if last_5[-1] == '\"':
        return False
    # No terminal punctuation in the last 5 chars. Mid-thought.
    return True


def parse_json_output(content: str, label: str = "response") -> dict:
    """Parse a model's JSON output, handling markdown wrapping and errors.

    Args:
        content: Raw model response text
        label: Human-readable label for error messages

    Returns:
        Parsed dict

    Raises:
        RuntimeError: If JSON cannot be extracted. The message starts with
            "TRUNCATED:" when the response looks cut off mid-stream (vs. a
            malformed-but-complete response) so callers can distinguish and
            retry the upstream chat call.
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
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            # Brace-counting extraction as final attempt
            extracted = _extract_json(repaired)
            if extracted is not None:
                return extracted
        # Classify: truncated vs malformed
        if _looks_truncated(content):
            raise RuntimeError(
                f"TRUNCATED: Failed to parse {label} as JSON (response cut off mid-stream). "
                f"Response preview: {content[:300]}"
            )
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
    """HTTP client for OpenAI-compatible LLM APIs.

    Works with any provider that exposes an OpenAI-compatible /chat/completions endpoint.
    Configure via LLM_BASE_URL + LLM_API_KEY env vars, or use provider-specific fallbacks.
    """

    def __init__(self, config: Optional[Config] = None, use_cache: bool = False):
        self.config = config or Config()
        self.config.require_api_key()  # Validate key exists before making requests
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

            # Treat empty responses as transient — surface so chat_with_retry can retry.
            if not result or not result.strip():
                raise RuntimeError("API returned empty response (transient)")

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
        max_retries: int = 3,
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
                for prefix in ["API error "]:
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
                    delay = 2 ** (attempt + 3)
                    time.sleep(delay)

        raise RuntimeError(f"All {max_retries + 1} attempts failed: {last_error}")

    def chat_parse_with_retry(
        self,
        model: ModelConfig,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        label: str = "response",
        max_parse_retries: int = 2,
        **kwargs,
    ) -> dict:
        """Chat completion with parse_json_output, retrying on truncated responses.

        Wraps chat_with_retry + parse_json_output. When the upstream chat returns
        a response that parse_json_output identifies as TRUNCATED, the chat is
        re-issued (up to max_parse_retries extra attempts) before giving up.
        Malformed-but-complete responses propagate immediately.

        Args:
            model: ModelConfig for routing
            messages: Chat messages
            system_prompt: Optional system message
            label: Label passed to parse_json_output for error messages
            max_parse_retries: Extra chat retries on truncation
            **kwargs: Forwarded to chat_with_retry

        Returns:
            Parsed dict from parse_json_output

        Raises:
            RuntimeError: If all retries exhausted or non-truncation parse error.
        """
        total_attempts = max_parse_retries + 1
        last_error: Optional[Exception] = None
        for attempt in range(total_attempts):
            try:
                content = self.chat_with_retry(
                    model, messages, system_prompt, **kwargs
                )
                return parse_json_output(content, label=label)
            except RuntimeError as e:
                last_error = e
                if str(e).startswith("TRUNCATED:") and attempt < total_attempts - 1:
                    # Backoff before re-issuing chat
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
        # Defensive — loop above should always raise or return
        raise RuntimeError(
            f"All {total_attempts} attempts failed for {label}: {last_error}"
        )


    def close(self):
        self._http.close()