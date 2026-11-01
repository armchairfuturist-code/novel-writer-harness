"""Any model, any role: the routing seam that keeps StoryForge provider-agnostic.

These tests pin the contract an agent or a user relies on when they point one
role at a model this repo has never heard of. Nothing here needs an API key.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402

_PREFIXES = ("LLM_", "CROFAI_")


class RoutingAgnosticTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items() if k.startswith(_PREFIXES)}
        for key in list(os.environ):
            if key.startswith(_PREFIXES):
                os.environ.pop(key)
        Config._instance = None
        self.cfg = Config()

    def tearDown(self):
        for key in [k for k in os.environ if k.startswith(_PREFIXES)]:
            os.environ.pop(key, None)
        os.environ.update(self._saved)
        Config._instance = None

    def _set(self, name, value):
        os.environ[name] = value
        Config._instance = None
        self.cfg = Config()

    def test_routing_default_is_labeled(self):
        """With no override the routing table answers, and says so."""
        self.cfg.model_for_phase("draft")
        row = self.cfg.resolution_log[-1]
        self.assertEqual(row["source"], "routing")
        self.assertEqual(row["key"], self.cfg.phase_models["draft"])

    def test_known_alias_override_is_labeled(self):
        self._set("LLM_MODEL_DRAFT", "flash")
        model = self.cfg.model_for_phase("draft")
        self.assertEqual(model.name, self.cfg.models["flash"].name)
        self.assertEqual(self.cfg.resolution_log[-1]["source"], "env-alias")

    def test_raw_model_id_override_is_honored(self):
        """A model id from any OpenAI-compatible provider works with no edit."""
        self._set("LLM_MODEL_DRAFT", "claude-opus-5")
        model = self.cfg.model_for_phase("draft")
        self.assertEqual(model.name, "claude-opus-5")
        self.assertEqual(self.cfg.resolution_log[-1]["source"], "env-raw")

    def test_raw_id_keeps_the_config_base_url(self):
        self._set("LLM_MODEL_DRAFT", "some-model")
        self._set("LLM_BASE_URL", "https://example.test/v1")
        self.assertEqual(self.cfg.model_for_phase("draft").base_url, "https://example.test/v1")

    def test_per_role_base_url_points_one_role_elsewhere(self):
        """One role can live on a second provider while the rest stay put."""
        self._set("LLM_BASE_URL", "https://example.test/v1")
        self._set("LLM_MODEL_CRITIQUE", "other-model")
        self._set("LLM_MODEL_CRITIQUE_BASE_URL", "https://other.test/v1")
        self.assertEqual(self.cfg.model_for_phase("critique").base_url, "https://other.test/v1")
        self.assertEqual(self.cfg.model_for_phase("draft").base_url, "https://example.test/v1")

    def test_raw_override_notes_once_per_value(self):
        """The note is a startup signal, not one line per call."""
        self._set("LLM_MODEL_DRAFT", "typo-alias")
        err = io.StringIO()
        with redirect_stderr(err):
            self.cfg.model_for_phase("draft")
            self.cfg.model_for_phase("draft")
        self.assertEqual(err.getvalue().count("typo-alias"), 1)
        self.assertIn("not a known alias", err.getvalue())

    def test_known_alias_override_is_silent(self):
        self._set("LLM_MODEL_DRAFT", "flash")
        err = io.StringIO()
        with redirect_stderr(err):
            self.cfg.model_for_phase("draft")
        self.assertEqual(err.getvalue(), "")

    def test_interview_override_takes_a_raw_id(self):
        model = self.cfg.model_for_interview("concept_premise", override="mistral-large-3")
        self.assertEqual(model.name, "mistral-large-3")

    def test_debate_role_takes_a_raw_id(self):
        role = next(iter(self.cfg.debate_models))
        self._set(f"LLM_MODEL_{role.upper()}", "deepseek-v4-pro")
        self.assertEqual(self.cfg.model_for_debate(role).name, "deepseek-v4-pro")

    def test_every_role_resolves_without_a_key(self):
        """Planning the run needs no credentials, so an agent can inspect it."""
        plan = self.cfg.resolve_routing()
        self.assertFalse(plan["api_key_set"])
        for role, row in plan["roles"].items():
            self.assertTrue(row["model"], role)
            self.assertEqual(row["env_var"], f"LLM_MODEL_{role.upper()}")
            self.assertIn(row["table"], ("phase", "interview", "debate"))

    def test_resolve_routing_covers_every_table(self):
        plan = self.cfg.resolve_routing()
        expected = set(self.cfg.phase_models) | set(self.cfg.interview_models) | set(self.cfg.debate_models)
        self.assertEqual(set(plan["roles"]), expected)

    def test_resolve_routing_leaves_the_run_log_alone(self):
        """Inspecting the plan must not pollute the provenance of a real run."""
        self.cfg.model_for_phase("draft")
        before = len(self.cfg.resolution_log)
        self.cfg.resolve_routing()
        self.assertEqual(len(self.cfg.resolution_log), before)

    def test_plan_rows_name_the_alias_table(self):
        plan = self.cfg.resolve_routing()
        for alias, name in plan["aliases"].items():
            self.assertEqual(name, self.cfg.models[alias].name)


if __name__ == "__main__":
    unittest.main()
