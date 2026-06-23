"""Mock CrofaiClient for inventory testing.

This module provides a deterministic mock for the LLM API used throughout
the StoryForge pipeline. Every call to CrofaiClient.chat() returns a
pre-canned response that matches the type of request being made.

The mock:
- Implements the same public surface (chat, chat_with_retry, chat_parse_with_retry)
- Routes responses by inspecting system_prompt + message content
- Returns realistic structured JSON or prose per request type
- Supports failure injection (timeouts, 429, 5xx, malformed JSON, truncation)
- Records every call for later inspection
- Has no network dependency
"""

import json
import os
import sys
import re
import time
import threading
from typing import Optional
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from pipeline.api import CrofaiClient
from config import Config, ModelConfig


# ──────────────────────────────────────────────────────────────
# Failure injection modes
# ──────────────────────────────────────────────────────────────

class FailureMode:
    NONE = "none"
    TIMEOUT = "timeout"
    RATE_LIMIT = "429"
    SERVER_ERROR = "500"
    EMPTY_RESPONSE = "empty"
    MALFORMED_JSON = "malformed_json"
    TRUNCATED = "truncated"
    AUTH_ERROR = "401"


# ──────────────────────────────────────────────────────────────
# Response templates per request type
# ──────────────────────────────────────────────────────────────

def _seed_response() -> str:
    return json.dumps({
        "title": "The Hollow Crown",
        "genre": "fantasy",
        "premise": "A disgraced cartographer's apprentice must redraw the kingdom's failing ward-stones.",
        "tone": "atmospheric, elegiac",
        "tense": "past",
        "pov": "third-person limited",
        "target_length": 95000,
        "target_chapters": 24,
        "themes": ["memory", "cartography", "duty"],
        "unique_angle": "Fantasy told through the lens of survey work.",
        "initial_direction": "Open with the protagonist's mentor's funeral.",
    })


def _worldbuilding_response() -> str:
    return json.dumps({
        "world_name": "The Sundered Marches",
        "geography": {"regions": ["Lowland Reaches", "Ash Vale", "Glassreach"]},
        "history": {"eras": ["First Survey", "Hollow Wars", "Long Peace", "Present"]},
        "factions": ["The Survey Cartel", "The Keepers of the Stones", "The Hollow Court"],
        "power_system": {"name": "Ward-Mapping", "rules": ["A ward-stone holds as long as its map remains true."]},
        "central_conflict": "The kingdom's ward-stones are failing.",
    })


def _characters_response() -> str:
    return json.dumps({
        "characters": [
            {"name": "Aelith Vance", "role": "protagonist", "age": 24, "traits": ["perceptive"], "arc": "Reluctant Master Surveyor."},
            {"name": "Bren Coldwell", "role": "ally", "age": 38, "traits": ["laconic"], "arc": "Sworn companion."},
            {"name": "Sister Ondre", "role": "mentor", "age": 61, "traits": ["patient"], "arc": "Reveals the truth."},
            {"name": "The Cartographer-General", "role": "antagonist", "age": 58, "traits": ["charming"], "arc": "Revealed as Hollow Court."},
        ],
        "relationship_map": [
            {"from": "Aelith Vance", "to": "Bren Coldwell", "type": "allies"},
            {"from": "Aelith Vance", "to": "Sister Ondre", "type": "mentor"},
        ],
    })


def _outline_response() -> str:
    acts = []
    for i, name in enumerate(["Funeral", "Crossing", "Trials", "Darkest Hour", "Final Quest"], 1):
        chs = []
        for c in range(1, 25):
            if (i == 1 and c <= 3) or (i == 2 and 4 <= c <= 8) or (i == 3 and 9 <= c <= 14) or (i == 4 and 15 <= c <= 18) or (i == 5 and 19 <= c <= 24):
                chs.append({
                    "chapter": c,
                    "title": f"Chapter {c}",
                    "pov": "Aelith Vance",
                    "summary": f"Summary of chapter {c}.",
                    "key_events": [f"Event in chapter {c}"],
                    "emotional_arc": "rising",
                })
        acts.append({"name": f"Act {i}: {name}", "chapters": chs})
    return json.dumps({
        "acts": acts,
        "story_structure": "five_act",
        "pov_strategy": "rotating",
    })


def _chapter_draft_response(chapter_num: int) -> str:
    return (
        f"The morning of chapter {chapter_num} broke slow and gray over the "
        f"cartographer's workshop. Aelith Vance stood at the window, watching "
        f"the mist rise off the river. She had a long road ahead and a short "
        f"supply of hope, but she had her master's compass, and that would have "
        f"to be enough. The road waited. The road always waited.\n\n"
        f"She tucked the compass into her coat and went downstairs. Bren was "
        f"already there, sharpening a knife that did not need sharpening, the "
        f"way he did when he was worried. 'Ready?' he asked. 'As I'll ever be,' "
        f"she said, though neither of them was fooled. They stepped out into the "
        f"gray morning, and the door closed behind them with a sound like a "
        f"closing book.\n"
    )


def _revision_response(original: str) -> str:
    # Simulate an improved revision (slightly different from original)
    return original.replace("gray", "lead-colored").replace("hope", "conviction") + "\n\nThe road waited."


def _literary_critic_response() -> str:
    return json.dumps({
        "prose_craft": 8.0,
        "pacing": 7.5,
        "character_depth": 8.5,
        "dialogue": 7.0,
        "structure": 8.0,
        "overall_score": 7.8,
        "commentary": "Strong atmospheric prose, effective dialogue, minor pacing issues in middle.",
    })


def _professor_response() -> str:
    return json.dumps({
        "thematic_coherence": 8.5,
        "narrative_ambition": 8.0,
        "subtext": 7.5,
        "emotional_truth": 8.0,
        "overall_score": 8.0,
        "commentary": "Thematic work is well-integrated; subtext deepens the central metaphor.",
    })


def _outline_validation_response() -> str:
    return json.dumps({
        "overall": "PASS",
        "dimensions": {
            "character_coverage": {"severity": "PASS", "issues": []},
            "foreshadowing_completeness": {"severity": "PASS", "issues": []},
            "emotional_arc_progression": {"severity": "PASS", "issues": []},
            "beat_density": {"severity": "PASS", "issues": []},
            "information_boundaries": {"severity": "PASS", "issues": []},
        },
    })


def _drilling_response() -> str:
    return json.dumps([
        {"question": "Can you say more about Aelith's relationship with her sister?", "dimension": "characters"},
        {"question": "What does the failing ward-stone look like to Aelith when she first sees it?", "dimension": "world_setting"},
        {"question": "Who, specifically, is the Cartographer-General, and what does he want?", "dimension": "plot_structure"},
    ])


def _story_bible_response() -> str:
    return json.dumps({
        "spec": {
            "title": "The Hollow Crown",
            "premise": "A disgraced cartographer's apprentice must redraw the kingdom's failing ward-stones.",
            "genre": "fantasy",
            "tone": "atmospheric, elegiac",
            "tense": "past",
            "pov": "third-person limited",
            "target_length": 95000,
            "target_chapters": 24,
            "themes": ["memory", "cartography", "duty"],
            "unique_angle": "Fantasy told through the lens of survey work.",
            "initial_direction": "Open with the protagonist's mentor's funeral.",
        },
        "enrichments": {
            "concept": "A cartographer's apprentice finishes a forbidden survey.",
            "world": "The Sundered Marches, ringed by thirteen ward-stones.",
            "characters": "Aelith Vance, Bren Coldwell, Sister Ondre, the Cartographer-General.",
            "plot": "Aelith retraces her master's forbidden survey routes.",
            "theme": "Memory, erasure, and the power of the map.",
            "market": "Compares to The Goblin Emperor, Piranesi, Earthsea.",
        },
    })


def _compilation_response() -> str:
    return _story_bible_response()


def _debate_lore_response() -> str:
    return json.dumps({
        "issues": [],
        "severity": "PASS",
        "commentary": "All world-facts remain consistent with the prior chapters.",
    })


def _debate_plot_response() -> str:
    return json.dumps({
        "issues": [],
        "severity": "PASS",
        "commentary": "Plot threads remain coherent and forward-moving.",
    })


def _debate_mechanical_response() -> str:
    return json.dumps({
        "issues": [],
        "severity": "PASS",
        "mechanical_score": 8.0,
    })


def _change_declarations_response() -> str:
    return (
        "\n\n---CHANGES---\n"
        "[\n"
        "  {\"category\": \"character_state\", \"subject\": \"Aelith Vance\", \"delta\": \"commits to the road\"},\n"
        "  {\"category\": \"location_state\", \"subject\": \"The workshop\", \"delta\": \"left behind\"}\n"
        "]\n"
    )


# ──────────────────────────────────────────────────────────────
# Response router
# ──────────────────────────────────────────────────────────────

class MockCrofaiClient(CrofaiClient):
    """Mock CrofaiClient that returns deterministic responses by request type.

    Inspects the system_prompt and message content to choose a response.
    Records every call in self.calls for later inspection.
    """

    def __init__(self, config: Optional[Config] = None, use_cache: bool = False,
                 failure_mode: str = FailureMode.NONE, failure_count: int = 0):
        # Bypass the real __init__ — we don't want to require an API key
        self.config = config or Config()
        self._http = MagicMock()
        self.use_cache = use_cache
        self.failure_mode = failure_mode
        self.failure_count = failure_count
        self.calls = []
        self._lock = threading.Lock()
        self._call_count = 0

    def _route_response(self, model, messages, system_prompt):
        """Pick a response based on system_prompt + user message content."""
        sp = (system_prompt or "").lower()
        user_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content += " " + m.get("content", "").lower()
        combined = sp + " " + user_content

        # Heuristics ordered most specific → least
        if "outline" in combined and "validat" in combined:
            return _outline_validation_response()
        if "drilling" in combined or "follow-up" in combined or "follow_up" in combined:
            return _drilling_response()
        if "literary critic" in combined or "literary_critic" in combined:
            return _literary_critic_response()
        if "professor" in combined:
            return _professor_response()
        if "story bible" in combined or "compile" in combined and "bible" in combined:
            return _compilation_response()
        if "debate" in combined and "lore" in combined:
            return _debate_lore_response()
        if "debate" in combined and "plot" in combined:
            return _debate_plot_response()
        if "debate" in combined and "mechanical" in combined:
            return _debate_mechanical_response()
        # Outline must come BEFORE the seed heuristic, because the outline
        # user template also contains "Premise: ..." which trips the seed check.
        if "outline" in combined and "act" in combined:
            return _outline_response()
        if "seed" in combined or ("concept" in combined and "premise" in combined and len(messages) < 3):
            return _seed_response()
        if "world" in combined and "build" in combined:
            return _worldbuilding_response()
        if "character" in combined and "profil" in combined:
            return _characters_response()
        if "revision" in combined:
            user_text = messages[0].get("content", "") if messages else ""
            return _revision_response(user_text[:500])
        if "draft" in combined or "chapter" in combined and "writ" in combined:
            # Extract chapter number if possible
            m = re.search(r"chapter\s+(\d+)", combined)
            ch_num = int(m.group(1)) if m else 1
            text = _chapter_draft_response(ch_num)
            if "---changes---" in combined or "change declaration" in combined:
                return text + _change_declarations_response()
            return text
        # Default
        return json.dumps({"ok": True, "model": model.name if model else "unknown"})

    def _maybe_inject_failure(self):
        with self._lock:
            self._call_count += 1
            if self.failure_mode == FailureMode.NONE:
                return None
            if self.failure_count > 0 and self._call_count <= self.failure_count:
                if self.failure_mode == FailureMode.TIMEOUT:
                    return ("timeout", "API timeout after 600.0s")
                if self.failure_mode == FailureMode.RATE_LIMIT:
                    return ("http", 429, "API error 429: rate limit")
                if self.failure_mode == FailureMode.SERVER_ERROR:
                    return ("http", 500, "API error 500: internal server error")
                if self.failure_mode == FailureMode.AUTH_ERROR:
                    return ("http", 401, "API error 401: invalid key")
            return None

    def chat(self, model, messages, system_prompt=None, temperature=None,
             max_tokens=None, stream=False):
        with self._lock:
            self.calls.append({
                "model": model.name if model else "unknown",
                "system_prompt_len": len(system_prompt or ""),
                "user_msg_len": sum(len(m.get("content", "")) for m in messages if m.get("role") == "user"),
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
        fail = self._maybe_inject_failure()
        if fail is not None:
            if fail[0] == "timeout":
                raise RuntimeError(fail[1])
            if fail[0] == "http":
                status = fail[1]
                detail = fail[2]
                # Simulate the real client's error path
                if status == 401:
                    raise RuntimeError(detail)
                # 429 and 5xx bubble up so chat_with_retry can retry
                raise RuntimeError(detail)
        if self.failure_mode == FailureMode.EMPTY_RESPONSE and self._call_count % 5 == 0:
            return ""
        if self.failure_mode == FailureMode.MALFORMED_JSON and self._call_count % 7 == 0:
            return "this is { not valid json: ["
        if self.failure_mode == FailureMode.TRUNCATED and self._call_count % 11 == 0:
            return '{"title": "Test", "acts": [{"name": "A'
        return self._route_response(model, messages, system_prompt)

    def close(self):
        pass


def install_mock_env(api_key: str = "test-key-no-network"):
    """Set up environment so Config can be instantiated without real key."""
    os.environ["LLM_API_KEY"] = api_key
    os.environ["LLM_BASE_URL"] = "http://mock.invalid/v1"


def uninstall_mock_env():
    for k in ("LLM_API_KEY", "LLM_BASE_URL"):
        if k in os.environ:
            del os.environ[k]


def patch_crofai_client(monkeypatch, failure_mode=FailureMode.NONE, failure_count=0):
    """Patch CrofaiClient so that any instantiation returns a MockCrofaiClient."""
    from pipeline import api as api_mod
    real_init = CrofaiClient.__init__
    real_chat = CrofaiClient.chat
    real_chat_with_retry = CrofaiClient.chat_with_retry
    real_chat_parse = CrofaiClient.chat_parse_with_retry

    # Save the mock instance so callers can inspect it
    mock_holder = {"instance": None, "all_instances": []}

    def factory(config=None, use_cache=False, **kwargs):
        m = MockCrofaiClient(config=config, use_cache=use_cache,
                              failure_mode=failure_mode, failure_count=failure_count)
        mock_holder["instance"] = m
        mock_holder["all_instances"].append(m)
        return m

    # Patch every common import path
    for path in [
        "pipeline.api.CrofaiClient",
        "pipeline.seed.CrofaiClient",
        "pipeline.worldbuilding.CrofaiClient",
        "pipeline.characters.CrofaiClient",
        "pipeline.outline.CrofaiClient",
        "pipeline.draft.CrofaiClient",
        "pipeline.review.CrofaiClient",
        "pipeline.factcheck.CrofaiClient",
        "pipeline.backprop.CrofaiClient",
        "pipeline.iterative_backprop.CrofaiClient",
        "pipeline.adversarial_edit.CrofaiClient",
        "pipeline.export.CrofaiClient",
        "pipeline.outline_validator.CrofaiClient",
        "interview.drilling.CrofaiClient",
        "interview.chapter_feedback.CrofaiClient",
        "agents.orchestrator.CrofaiClient",
        "agents.writer.CrofaiClient",
        "agents.critic.CrofaiClient",
    ]:
        try:
            monkeypatch.setattr(path, factory, raising=False)
        except Exception:
            pass

    return mock_holder
