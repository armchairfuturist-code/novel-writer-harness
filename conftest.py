"""Pytest configuration for StoryForge tests.

Goals:
1. Provide a default fake API key so Config().require_api_key() never blocks tests
2. Reset the Config singleton between tests (each test gets a fresh Config)
3. Document the test environment for future maintainers

This is a minimal conftest. Tests that exercise actual LLM calls should patch
pipeline.api.CrofaiClient with a mock (see tests/fixtures/mock_api.py).
"""

import os
import sys

import pytest


# Ensure repo root is on sys.path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# Provide a default fake API key so any test path that reaches
# Config().require_api_key() does not crash on "no key". Tests that exercise
# the LLM client should still patch it with a mock to avoid real network calls.
os.environ.setdefault("LLM_API_KEY", "test-key-no-network")
os.environ.setdefault("LLM_BASE_URL", "http://mock.invalid/v1")
# Default embeddings to disabled so tests don't try to load sentence-transformers
os.environ.setdefault("LLM_ENABLE_EMBEDDINGS", "")


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """Reset the Config singleton before and after each test.

    Without this, tests that mutate Config state (e.g. set project_dir, enable
    features) leak into subsequent tests and cause flaky failures.
    """
    from config import Config
    Config._instance = None
    yield
    Config._instance = None
