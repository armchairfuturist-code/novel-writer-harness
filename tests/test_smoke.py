"""Tests for the seed-phrase smoke harness: pipeline/stub_provider.py + scripts/smoke.py.

The point of these tests is the guarantee the operator asked for - a whole run
from one sentence, with no API key and no network. Every test here is offline:
the httpx tripwire fails a run that tries to leave the machine, and the tests
assert it recorded nothing.
"""

import importlib.util
import io
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pipeline.prose_lab import MIN_WORDS_FOR_SCORE, analyze          # noqa: E402
from pipeline.stub_provider import (                                 # noqa: E402
    StubLLM, _ROUTES, classify, spin_prose, stubbed_llm,
)

# scripts/ is not a package, so load the CLI by path.
_SMOKE_PATH = os.path.join(REPO_ROOT, "scripts", "smoke.py")
_spec = importlib.util.spec_from_file_location("smoke_cli", _SMOKE_PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

PHRASE = ("A jazz musician in 1920s New Orleans heals wounds with her trumpet, "
          "and each healing steals a memory from someone she loves.")


def _run(tmp_path, **kwargs):
    """One offline smoke run into a directory that survives the test."""
    kwargs.setdefault("project_dir", str(tmp_path / "proj"))
    buf = io.StringIO()
    report = smoke.run_smoke(concept=kwargs.pop("concept", PHRASE), stream=buf, **kwargs)
    report["stdout"] = buf.getvalue()
    return report


# ---------------------------------------------------------------------------
# The whole run, offline
# ---------------------------------------------------------------------------

class TestOfflineRun:
    def test_two_chapters_reach_a_manuscript(self, tmp_path):
        r = _run(tmp_path, chapters=2)
        assert r["passed"], r["errors"]
        assert r["mode"] == "offline"
        assert len(r["chapters"]) == 2
        for c in r["chapters"]:
            assert c["words"] >= MIN_WORDS_FOR_SCORE, c
        assert r["manuscript"]["words"] >= MIN_WORDS_FOR_SCORE

    def test_nothing_touched_the_network(self, tmp_path):
        r = _run(tmp_path, chapters=1)
        assert r["network_attempts"] == []
        assert r["errors"] == []
        assert r["api_calls_avoided"] > 0, "the stub answered nothing"

    def test_every_phase_was_recognised(self, tmp_path):
        r = _run(tmp_path, chapters=1)
        assert "fallback" not in r["stub_phases"], r["stub_phases"]
        for name in ("seed", "world", "characters", "outline", "draft"):
            assert r["stub_phases"].get(name), f"{name} phase never asked the stub"

    def test_seed_spec_satisfies_the_schema(self, tmp_path):
        r = _run(tmp_path, chapters=1)
        assert r["passed"], r["errors"]
        with open(os.path.join(r["project_dir"], "spec.json"), encoding="utf-8") as f:
            spec = json.load(f)
        for key in ("genre", "premise", "tone", "target_chapters", "title", "pov"):
            assert key in spec, f"spec.json is missing {key}"
            assert not str(spec[key]).startswith("MISSING"), f"{key} came back MISSING"

    def test_report_prints_a_verdict_line(self, tmp_path):
        r = _run(tmp_path, chapters=1)
        assert r["stdout"].strip().splitlines()[-1].startswith("PASS")

    def test_json_report_round_trips(self, tmp_path):
        buf = io.StringIO()
        r = smoke.run_smoke(concept=PHRASE, chapters=1,
                            project_dir=str(tmp_path / "j"), stream=buf)
        assert r["passed"], r["errors"]
        buf2 = io.StringIO()
        smoke._emit(r, buf2, as_json=True)
        back = json.loads(buf2.getvalue())
        assert back["passed"] is True
        assert back["chapters"][0]["words"] >= MIN_WORDS_FOR_SCORE


# ---------------------------------------------------------------------------
# The length gate, driven through the stub
# ---------------------------------------------------------------------------

class TestRedrawPath:
    def test_short_first_drafts_are_redrawn(self, tmp_path):
        r = _run(tmp_path, chapters=1, short_first=3)
        assert r["passed"], r["errors"]
        ch = r["chapters"][0]
        assert ch["length_redraws"] >= 1, ch
        assert ch["length_attempts"] >= 2, ch
        assert ch["words"] >= MIN_WORDS_FOR_SCORE, "kept a short chapter"

    def test_redraw_count_reaches_the_report(self, tmp_path):
        r = _run(tmp_path, chapters=1, short_first=3)
        draft_row = next(p for p in r["phases"] if p["phase"] == "draft")
        assert "redraw" in draft_row["detail"]


# ---------------------------------------------------------------------------
# The stub itself
# ---------------------------------------------------------------------------

class TestStubProvider:
    @pytest.mark.parametrize("phase,marks", _ROUTES)
    def test_every_route_marker_classifies(self, phase, marks):
        for mark in marks:
            assert classify(mark) == phase, f"{mark!r} did not route to {phase}"

    def test_unknown_prompt_falls_back_to_prose(self):
        assert classify("tell me about the weather") == "fallback"
        stub = StubLLM(concept=PHRASE)
        text = stub.answer("tell me about the weather")
        assert len(text.split()) > 50

    def test_prose_clears_the_real_scorer(self):
        from config import Config
        from pipeline.draft import ChapterScorer

        cfg = Config()
        cfg.chapter.target_words_per_chapter = 1000
        stub = StubLLM(concept=PHRASE, chapter_words=1000)
        text = stub._render("draft", "Write Chapter 1 of the novel", first=True)
        body = text.split("---CHANGES---")[0]
        score = ChapterScorer(cfg).score_chapter(body)
        assert score["prose_pass"], score.get("prose_violations")
        assert score["total_score"] >= cfg.scoring.min_chapter_score, score
        assert not score["banned_words_found"], score["banned_words_found"]

    def test_prose_length_follows_the_target(self):
        stub = StubLLM(concept=PHRASE, chapter_words=1000)
        body = stub._render("draft", "Write Chapter 1", first=True).split("---CHANGES---")[0]
        n = len(body.split())
        assert 900 <= n <= 1400, n
        assert analyze(body)["pass"]

    def test_answers_come_from_the_phrase(self):
        a = StubLLM(concept=PHRASE).story
        b = StubLLM(concept="A lighthouse keeper trades years for calm seas").story
        assert a["title"] != b["title"]
        assert a["lead"] != b["lead"]
        assert a["motif"] == "trumpet" and a["cost"] == "memory", a
        assert b["motif"] == "lighthouse", b

    def test_proper_nouns_do_not_become_the_cost(self):
        story = StubLLM(concept=PHRASE).story
        assert story["cost"].lower() != "orleans"
        assert "Orleans" not in story["title"]

    def test_changes_block_is_attached_to_drafts(self):
        stub = StubLLM(concept=PHRASE)
        text = stub._render("draft", "Write Chapter 2", first=True)
        assert "---CHANGES---" in text and "---END CHANGES---" in text

    def test_stubbed_llm_restores_the_client(self):
        from pipeline import api as api_mod

        original = api_mod.CrofaiClient.chat
        with stubbed_llm(concept=PHRASE) as stub:
            assert api_mod.CrofaiClient.chat is not original
            stub.answer("Analyze this story seed", "")
            assert stub.calls and stub.calls[0]["phase"] == "seed"
        assert api_mod.CrofaiClient.chat is original


# ---------------------------------------------------------------------------
# The tripwire and the CLI
# ---------------------------------------------------------------------------

class TestTripwireAndCli:
    def test_tripwire_blocks_and_records(self):
        import httpx

        with smoke.NetworkTripwire() as trip:
            with pytest.raises(RuntimeError):
                httpx.Client().post("http://mock.invalid/v1/chat/completions")
        assert trip.attempts == ["http://mock.invalid/v1/chat/completions"]

    def test_cli_exits_zero_on_a_passing_run(self, tmp_path, capsys):
        code = smoke.main([PHRASE, "--chapters", "1", "--dir", str(tmp_path / "cli")])
        assert code == 0
        assert "PASS" in capsys.readouterr().out

    def test_cli_live_without_a_key_fails_fast(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(smoke, "_HAD_KEY", False)
        code = smoke.main([PHRASE, "--live", "--dir", str(tmp_path / "live")])
        assert code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out and "LLM_API_KEY" in out

    def test_cli_runs_from_any_directory(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        code = smoke.main([PHRASE, "--chapters", "1", "--dir", str(tmp_path / "cwd")])
        assert code == 0
        assert os.path.exists(os.path.join(str(tmp_path / "cwd"), "manuscript.md"))
