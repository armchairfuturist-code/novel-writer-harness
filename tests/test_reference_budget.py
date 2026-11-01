"""A capped reference block says what it had to leave out.

debate.py asks KnowledgeBase.get_references() for at most 500 tokens, so a
query that matches six files gets three of them and, before this test, no
indication that anything was missing. An agent that cannot see the gap treats
a partial rule as the whole rule.

The block now carries a budget note naming what was cut, and the KnowledgeBase
keeps the same facts on last_budget_truncated / last_budget_dropped for logs.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from pipeline.knowledge_base import KnowledgeBase

TOPICS = [
    ("dialogue craft", "Keep speech asymmetric: one character wants, the other stalls."),
    ("hook techniques", "Open on the moment the promise breaks, not the morning before."),
    ("sensory immersion", "One concrete smell beats three adjectives of atmosphere."),
    ("pacing beats", "Alternate pressure and release; two pressured scenes in a row read flat."),
]


def write_kb(root: str) -> None:
    for index, (topic, seed) in enumerate(TOPICS):
        path = os.path.join(root, "craft-%02d.md" % index)
        body = " ".join([seed] * 40)  # ~700 tokens each, so a small budget bites
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("---\n")
            fh.write("topic: %s\n" % topic)
            fh.write("agent_roles: [drafting]\n")
            fh.write("keywords: [dialogue, craft, scene, prose]\n")
            fh.write("---\n\n")
            fh.write("# %s\n\n%s\n" % (topic.title(), body))


class TestReferenceBudgetNote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="kb-budget-")
        write_kb(cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.kb = KnowledgeBase(self.dir)

    def test_a_roomy_budget_reports_nothing_missing(self):
        block = self.kb.get_references("drafting", ["dialogue", "craft"], max_tokens=8000)
        self.assertIn("## Relevant Writing Theory", block)
        self.assertNotIn("budget note", block)
        self.assertEqual(self.kb.last_budget_dropped, [])
        self.assertIsNone(self.kb.last_budget_truncated)
        for topic, _ in TOPICS:
            self.assertIn("### %s" % topic, block)

    def test_a_tight_budget_names_what_it_left_out(self):
        block = self.kb.get_references("drafting", ["dialogue", "craft"], max_tokens=900)
        self.assertIn("> Reference budget note", block)
        self.assertIn("left out for budget", block)
        self.assertTrue(self.kb.last_budget_dropped or self.kb.last_budget_truncated,
                        "a capped block must record what it dropped")
        for topic in self.kb.last_budget_dropped:
            self.assertIn(topic, block, "the note must name each dropped topic")

    def test_a_cut_reference_is_labelled_as_cut(self):
        block = self.kb.get_references("drafting", ["dialogue", "craft"], max_tokens=900)
        if self.kb.last_budget_truncated:
            self.assertIn("(cut short to fit the budget)", block)
            self.assertIn(self.kb.last_budget_truncated, block)

    def test_the_note_tells_the_caller_how_to_fix_it(self):
        block = self.kb.get_references("drafting", ["dialogue", "craft"], max_tokens=900)
        self.assertIn("max_tokens", block)

    def test_no_match_still_returns_empty_and_clears_the_record(self):
        block = self.kb.get_references("drafting", ["quantum", "chromatography"], max_tokens=500)
        self.assertEqual(block, "")
        self.assertEqual(self.kb.last_budget_dropped, [])
        self.assertIsNone(self.kb.last_budget_truncated)


if __name__ == "__main__":
    unittest.main()
