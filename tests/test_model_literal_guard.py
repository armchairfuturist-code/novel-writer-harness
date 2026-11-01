"""No vendor model id may appear outside the alias table in config.py.

The table is the one place a model name is allowed to live. A literal anywhere
else is a role that quietly stopped being reassignable, which is the failure
this repo's model-agnostic contract exists to prevent.
"""

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "reference", "fixtures", ".api-cache"}
ALLOWED = {os.path.join(REPO, "config.py")}


def is_test_path(path):
    """Tests pin the shipped defaults, so they are allowed to name a model id."""
    parts = path.split(os.sep)
    return os.path.basename(path).startswith("test_") or "tests" in parts

# Vendor model ids, not aliases: an alias such as "flash" is a role-ish word and
# is fine anywhere, while a provider's product name pins that provider.
VENDOR = re.compile(
    r"\b(?:kimi-k2\.6[a-z0-9.\-]*|glm-[0-9][0-9.\-]*|deepseek-v[0-9][a-z0-9.\-]*"
    r"|qwen[0-9][0-9.\-]*[a-z\-]*|claude-[a-z0-9.\-]+|gpt-[0-9][0-9.\-]*"
    r"|o[0-9]-[a-z]+|llama-[0-9][0-9.\-]*|mistral-[a-z0-9.\-]+)\b"
)


def shipped_python_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


class ModelLiteralGuardTest(unittest.TestCase):
    def test_no_vendor_id_outside_the_alias_table(self):
        offenders = []
        for path in shipped_python_files():
            if path in ALLOWED or is_test_path(path):
                continue
            text = open(path, encoding="utf-8", errors="replace").read()
            for number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for hit in VENDOR.findall(line):
                    offenders.append(f"{os.path.relpath(path, REPO)}:{number}: {hit}")
        self.assertEqual(
            offenders,
            [],
            "Vendor model ids belong in the config.py alias table only. Route the "
            "role through Config.model_for_phase / model_for_interview / "
            "model_for_debate, or add an alias.\n" + "\n".join(offenders),
        )

    def test_the_guard_actually_sees_a_literal(self):
        """A guard that cannot find the thing it forbids guards nothing."""
        self.assertTrue(VENDOR.search('name = "kimi-k2.6-precision"'))
        self.assertTrue(VENDOR.search('x = "gpt-5.2"'))
        self.assertTrue(VENDOR.search('y = "claude-opus-5"'))
        self.assertIsNone(VENDOR.search('alias = "flash"'))
        self.assertIsNone(VENDOR.search('role = "draft"'))

    def test_test_paths_are_the_only_exception(self):
        self.assertTrue(is_test_path(os.path.join(REPO, "tests", "test_pipeline.py")))
        self.assertTrue(is_test_path(os.path.join(REPO, "test_e2e.py")))
        self.assertFalse(is_test_path(os.path.join(REPO, "pipeline", "api.py")))
        self.assertFalse(is_test_path(os.path.join(REPO, "storyforge.py")))

    def test_config_py_is_the_only_allowed_home(self):
        self.assertEqual(len(ALLOWED), 1)
        self.assertTrue(os.path.exists(next(iter(ALLOWED))))


if __name__ == "__main__":
    unittest.main()
