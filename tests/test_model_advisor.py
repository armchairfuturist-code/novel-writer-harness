"""Test the model advisor + --show-models flag."""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from config import Config


class TestModelAdvisor(unittest.TestCase):
    """AC: model advisor — the user can see and override model selections per role."""

    def setUp(self):
        Config._instance = None

    def tearDown(self):
        Config._instance = None

    def test_default_phase_routing(self):
        """Default phase routing: draft=precision, seed=deepseek, scoring=flash."""
        c = Config()
        self.assertEqual(c.model_for_phase("draft").name, "kimi-k2.6-precision")
        self.assertEqual(c.model_for_phase("seed").name, "deepseek-v4-pro-precision")
        self.assertEqual(c.model_for_phase("scoring").name, "qwen3.5-9b")

    def test_default_debate_routing(self):
        """Default debate routing: lore=deepseek, plot=balanced, mechanical=flash."""
        c = Config()
        self.assertEqual(c.model_for_debate("lore_prosecutor").name, "deepseek-v4-pro-precision")
        self.assertEqual(c.model_for_debate("plot_sentinel").name, "kimi-k2.6-precision")
        self.assertEqual(c.model_for_debate("mechanical_magistrate").name, "qwen3.5-9b")

    def test_env_override_per_role(self):
        """User can override any role's model via LLM_MODEL_{ROLE} env var."""
        os.environ["LLM_MODEL_DRAFT"] = "flash"
        try:
            Config._instance = None
            c = Config()
            self.assertEqual(c.model_for_phase("draft").name, "qwen3.5-9b")
        finally:
            del os.environ["LLM_MODEL_DRAFT"]

    def test_env_override_unknown_alias_falls_back(self):
        """Unknown alias in env var falls back to default routing."""
        os.environ["LLM_MODEL_DRAFT"] = "nonexistent-alias"
        try:
            Config._instance = None
            c = Config()
            # Falls back to phase_models["draft"] which is "kimi-precision"
            self.assertEqual(c.model_for_phase("draft").name, "kimi-k2.6-precision")
        finally:
            del os.environ["LLM_MODEL_DRAFT"]

    def test_model_rationale_complete(self):
        """Every routing role has a rationale entry."""
        c = Config()
        rationale = c.model_rationale
        for role in c.phase_models:
            self.assertIn(role, rationale, f"phase role {role} missing rationale")
        for role in c.interview_models:
            self.assertIn(role, rationale, f"interview role {role} missing rationale")
        for role in c.debate_models:
            self.assertIn(role, rationale, f"debate role {role} missing rationale")

    def test_print_routing_plan_doesnt_crash(self):
        """print_routing_plan prints without raising."""
        c = Config()
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            c.print_routing_plan()
        out = buf.getvalue()
        # Every routing role should appear in the output
        for role in list(c.phase_models.keys())[:3]:
            self.assertIn(role, out)
        # The model advisor header should appear
        self.assertIn("MODEL ROUTING PLAN", out)

    def test_model_agnostic_no_hardcoded_provider(self):
        """The model advisor should NOT hardcode a specific provider name."""
        c = Config()
        # The advisor uses base_url from config (provider-agnostic)
        # and prints the actual model name, never a hardcoded list
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            c.print_routing_plan()
        out = buf.getvalue()
        # Should print the provider from config (could be any OpenAI-compatible URL)
        self.assertIn(c.base_url, out)


class TestShowModelsFlag(unittest.TestCase):
    """AC: --show-models CLI flag prints routing plan and exits."""

    def test_show_models_prints_routing_plan(self):
        """--show-models exits 0 and prints the routing plan."""
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "storyforge.py"), "--show-models"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
            env={**os.environ, "LLM_API_KEY": "test", "LLM_BASE_URL": "http://mock.invalid/v1"},
        )
        self.assertEqual(result.returncode, 0, f"--show-models should exit 0; got {result.returncode}. stderr: {result.stderr[:300]}")
        self.assertIn("MODEL ROUTING PLAN", result.stdout)
        # Should mention key roles
        for role in ["draft", "seed", "critique", "lore_prosecutor"]:
            self.assertIn(role, result.stdout, f"--show-models missing role {role}")

    def test_show_models_does_not_require_api_key(self):
        """--show-models works even without an API key set (it's just printing config)."""
        import subprocess
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("LLM_API_KEY", "CROFAI_API_KEY")}
        # Note: --show-models exits BEFORE require_api_key() is called
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "storyforge.py"), "--show-models"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT, env=clean_env,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

import io
import json
from contextlib import redirect_stdout
from unittest import mock


class TestCheckModelAvailability(unittest.TestCase):
    """AC: model availability — the advisor warns about stale aliases,
    never guesses new names, and never raises when the provider is absent."""

    def _catalog_response(self, ids):
        fake = mock.Mock()
        fake.json.return_value = {"data": [{"id": i} for i in ids]}
        fake.raise_for_status.return_value = None
        return fake

    def test_no_key_never_raises(self):
        old_key = os.environ.get("LLM_API_KEY")
        old_crof = os.environ.pop("CROFAI_API_KEY", None)
        os.environ["LLM_API_KEY"] = ""
        try:
            Config._instance = None
            c = Config()
            r = c.check_model_availability()
            self.assertFalse(r["checked"])
            self.assertFalse(r["ok"])
            self.assertEqual(r["missing"], [])
            self.assertEqual(r["catalog"], [])
        finally:
            os.environ["LLM_API_KEY"] = old_key or "test-key-no-network"
            Config._instance = None

    def test_stubbed_catalog_reports_missing_aliases(self):
        c = Config()
        with mock.patch("httpx.get", return_value=self._catalog_response(
                ["qwen3.5-9b", "deepseek-v4-flash"])):
            r = c.check_model_availability()
        self.assertTrue(r["checked"])
        self.assertFalse(r["ok"])
        self.assertIn("kimi-k2.6-precision", r["missing"])
        self.assertIn("glm-5.1", r["missing"])
        self.assertIn("qwen3.5-9b", r["catalog"])

    def test_stubbed_full_catalog_is_ok(self):
        c = Config()
        names = [cfg.name for cfg in c.models.values()]
        names += [cfg.name for cfg in c.benchmark_models.values()]
        with mock.patch("httpx.get", return_value=self._catalog_response(sorted(set(names)))):
            r = c.check_model_availability()
        self.assertTrue(r["checked"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["missing"], [])

    def test_provider_error_returns_unchecked(self):
        c = Config()
        with mock.patch("httpx.get", side_effect=RuntimeError("no network")):
            r = c.check_model_availability()
        self.assertFalse(r["checked"])
        self.assertEqual(r["catalog"], [])
        self.assertFalse(r["ok"])

    def test_routing_plan_warns_only_when_checked(self):
        c = Config()
        with mock.patch("httpx.get", return_value=self._catalog_response(["qwen3.5-9b"])):
            buf = io.StringIO()
            with redirect_stdout(buf):
                c.print_routing_plan()
            out = buf.getvalue()
        self.assertIn("does not list", out)
        self.assertIn("kimi-k2.6-precision", out)
        self.assertIn("glm-5.1", out)
        unchecked = {"ok": False, "checked": False, "catalog": [], "missing": []}
        with mock.patch.object(Config, "check_model_availability", return_value=unchecked):
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                c.print_routing_plan()
            self.assertNotIn("does not list", buf2.getvalue())
