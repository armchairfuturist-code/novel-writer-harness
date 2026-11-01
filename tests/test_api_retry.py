"""Tests for the retry-by-kind policy in pipeline.api.chat_with_retry.

No real network and no real sleeps: chat() is stubbed to raise scripted
errors, the sleeper is captured, and the jitter rng is pinned to zero.
"""
import os
import random
import sys
import unittest
from unittest import mock

import httpx

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("LLM_API_KEY", "test-key-no-network")
os.environ.setdefault("LLM_BASE_URL", "http://mock.invalid/v1")

from config import Config, ModelConfig
from pipeline.api import (
    RETRY_CAPS,
    CrofaiClient,
    _backoff_delay,
    _is_retryable,
    _retry_kind,
    _status_of,
)


class ZeroRng:
    """A jitter source that always returns 0, so backoff sequences are exact."""

    def uniform(self, a, b):
        return 0.0


def with_status(status, message):
    """A RuntimeError whose __cause__ carries a real httpx response."""
    request = httpx.Request("POST", "http://mock.invalid/v1/chat/completions")
    cause = httpx.HTTPStatusError(
        message, request=request,
        response=httpx.Response(status, request=request),
    )
    e = RuntimeError(message)
    e.__cause__ = cause
    return e


class TestRetryClassification(unittest.TestCase):
    def test_429_message_is_rate_limit(self):
        self.assertEqual(_retry_kind(RuntimeError("API error 429: rate limited")), "rate_limit")

    def test_429_via_cause_is_rate_limit(self):
        e = with_status(429, "API error 429: rate limited")
        self.assertEqual(_status_of(e), 429)
        self.assertEqual(_retry_kind(e), "rate_limit")

    def test_timeout_is_network(self):
        self.assertEqual(_retry_kind(RuntimeError("API timeout after 600.0s")), "network")

    def test_connection_error_via_cause_is_network(self):
        e = RuntimeError("wrapped")
        e.__cause__ = httpx.ConnectError("connection refused")
        self.assertEqual(_retry_kind(e), "network")

    def test_5xx_is_other(self):
        self.assertEqual(_retry_kind(RuntimeError("API error 503: bad gateway")), "other")

    def test_401_is_other_kind_but_not_retryable(self):
        e = RuntimeError("API error 401: bad key")
        self.assertEqual(_retry_kind(e), "other")
        self.assertEqual(_status_of(e), 401)
        self.assertFalse(_is_retryable(401))

    def test_truncated_is_parse(self):
        self.assertEqual(_retry_kind(RuntimeError("TRUNCATED: Failed to parse x as JSON")), "parse")

    def test_malformed_is_parse(self):
        self.assertEqual(_retry_kind(RuntimeError("Failed to parse characters as JSON. Response preview: {}")), "parse")

    def test_empty_response_is_other(self):
        self.assertEqual(_retry_kind(RuntimeError("API returned empty response (transient)")), "other")


class TestBackoff(unittest.TestCase):
    def test_rate_limit_sequence(self):
        delays = [_backoff_delay("rate_limit", n, ZeroRng()) for n in range(7)]
        self.assertEqual(delays, [3.0, 6.0, 12.0, 24.0, 48.0, 60.0, 60.0])

    def test_network_sequence(self):
        delays = [_backoff_delay("network", n, ZeroRng()) for n in range(7)]
        self.assertEqual(delays, [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0])

    def test_parse_is_linear(self):
        self.assertEqual([_backoff_delay("parse", n, ZeroRng()) for n in range(3)],
                         [1.0, 2.0, 3.0])

    def test_jitter_bounded_by_seeded_rng(self):
        rng = random.Random(42)
        d = _backoff_delay("network", 0, rng)
        self.assertGreaterEqual(d, 2.0)
        self.assertLessEqual(d, 2.0 * 1.3)

    def test_caps_table(self):
        self.assertEqual(RETRY_CAPS, {"rate_limit": 7, "network": 7, "other": 3, "parse": 2})


class RetryHarness(unittest.TestCase):
    """A client whose chat() raises scripted errors and records every sleep."""

    def setUp(self):
        Config._instance = None
        self.sleeps = []
        self.client = CrofaiClient(sleeper=self.sleeps.append, rng=ZeroRng())
        self.model = ModelConfig(name="test-model")

    def tearDown(self):
        self.client.close()
        Config._instance = None

    def run_scripted(self, errors, max_retries=None):
        """chat() raises errors[i] on call i, then succeeds.

        Returns (result, attempts)."""
        calls = {"n": 0}

        def chat_side_effect(*a, **k):
            i = calls["n"]
            calls["n"] += 1
            if i < len(errors):
                raise errors[i]
            return "ok"

        kwargs = {} if max_retries is None else {"max_retries": max_retries}
        with mock.patch.object(self.client, "chat", side_effect=chat_side_effect):
            result = self.client.chat_with_retry(
                self.model, [{"role": "user", "content": "hi"}], **kwargs)
        return result, calls["n"]

    def test_429_retries_up_to_cap(self):
        errors = [RuntimeError("API error 429: rl")] * RETRY_CAPS["rate_limit"]
        result, attempts = self.run_scripted(errors)
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, RETRY_CAPS["rate_limit"] + 1)
        self.assertEqual(len(self.sleeps), RETRY_CAPS["rate_limit"])
        self.assertEqual(self.sleeps, [3.0, 6.0, 12.0, 24.0, 48.0, 60.0, 60.0])

    def test_5xx_retries_up_to_cap(self):
        errors = [RuntimeError("API error 500: boom")] * RETRY_CAPS["other"]
        result, attempts = self.run_scripted(errors)
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, RETRY_CAPS["other"] + 1)
        self.assertEqual(self.sleeps, [2.0, 4.0, 8.0])

    def test_timeout_retries_up_to_cap(self):
        errors = [RuntimeError("API timeout after 600.0s")] * RETRY_CAPS["network"]
        result, attempts = self.run_scripted(errors)
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, RETRY_CAPS["network"] + 1)

    def test_401_fails_immediately(self):
        with self.assertRaises(RuntimeError):
            self.run_scripted([RuntimeError("API error 401: bad key")])
        self.assertEqual(self.sleeps, [])

    def test_400_fails_immediately(self):
        with self.assertRaises(RuntimeError):
            self.run_scripted([RuntimeError("API error 400: bad request")])
        self.assertEqual(self.sleeps, [])

    def test_422_fails_immediately(self):
        with self.assertRaises(RuntimeError):
            self.run_scripted([RuntimeError("API error 422: unprocessable")])
        self.assertEqual(self.sleeps, [])

    def test_exhausted_kind_raises_with_attempts(self):
        errors = [RuntimeError("API error 503: down")] * (RETRY_CAPS["other"] + 1)
        with self.assertRaises(RuntimeError) as ctx:
            self.run_scripted(errors)
        self.assertIn("4 attempts failed", str(ctx.exception))
        self.assertEqual(len(self.sleeps), RETRY_CAPS["other"])

    def test_max_retries_caps_the_kind(self):
        # Two 429s would succeed under the kind's own cap of 7; an explicit
        # max_retries=1 stops it at two attempts and one sleep.
        errors = [RuntimeError("API error 429: rl")] * 2
        with self.assertRaises(RuntimeError) as ctx:
            self.run_scripted(errors, max_retries=1)
        self.assertIn("2 attempts failed", str(ctx.exception))
        self.assertEqual(self.sleeps, [3.0])

    def test_parse_retries_are_linear_and_capped(self):
        errors = [RuntimeError("TRUNCATED: nope")] * (RETRY_CAPS["parse"] + 1)
        with self.assertRaises(RuntimeError):
            self.run_scripted(errors)
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_success_after_transient_then_recovers(self):
        errors = [RuntimeError("API returned empty response (transient)"),
                  RuntimeError("API error 502: bad gateway")]
        result, attempts = self.run_scripted(errors)
        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 3)


if __name__ == "__main__":
    unittest.main()
