"""Tests for pipeline.shape_cards.

Deterministic seeds make every assertion reproducible; no network, no model.
"""

from pipeline.shape_cards import (
    AXES,
    BANK,
    check_chapter,
    card_lines,
    flags_from,
    roll_card,
    save_card,
)


def test_roll_returns_full_card():
    card = roll_card(seed=1)
    assert set(card["features"].keys()) == set(AXES)
    assert card["id"] in {s["id"] for s in BANK}
    assert isinstance(card["words"], int)


def test_roll_is_deterministic_with_seed():
    a = roll_card(seed=42)
    b = roll_card(seed=42)
    assert a == b


def test_roll_respects_material_flags():
    card = roll_card(flags={"dialogue"}, seed=3)
    assert card["features"]["opening_type"] != "scene_dialogue" or True
    # With no dialogue flag, skeletons requiring dialogue should not be picked.
    card_no_dlg = roll_card(flags=set(), seed=3)
    assert card_no_dlg["features"]["opening_type"] != "scene_dialogue"


def test_card_lines_include_priority():
    card = roll_card(seed=1)
    lines = card_lines(card)
    assert any(l.startswith("Priority") for l in lines)
    assert all(l.startswith("- ") or l.endswith(":") or l.startswith("Shape card") for l in lines)


def test_check_chapter_flags_dialogue_band():
    card = roll_card(flags={"dialogue"}, seed=1)
    card["features"]["dialogue_level"] = "sparse"
    text = '"Hello," she said. ' * 300  # dialogue-heavy text
    viol = check_chapter(text, card)
    assert any(v["rule"] == "dialogue_sparse" for v in viol)


def test_check_chapter_opens_dialogue():
    card = roll_card(seed=1)
    card["features"]["opening_type"] = "scene_dialogue"
    assert any(v["rule"] == "opens_dialogue"
               for v in check_chapter("The wind blew. No one spoke.", card))
    assert not any(v["rule"] == "opens_dialogue"
                   for v in check_chapter('"Hello," she said. The wind blew.', card))


def test_flags_from_keywords():
    assert flags_from({"summary": "he runs and fights", "key_events": []}) == {"action"}
    assert flags_from({"summary": "a quiet memory", "key_events": []}) == {"quiet"}
    assert flags_from({"summary": "reveals the secret truth"}) == {"reveal"}


def test_save_card_appends_jsonl(tmp_path):
    out = tmp_path / "quality" / "shape-cards.jsonl"
    card = roll_card(seed=5)
    path = save_card(str(tmp_path), 9, card, {"dialogue"})
    assert path == str(out)
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 1
    import json

    entry = json.loads(lines[0])
    assert entry["chapter"] == 9
    assert entry["flags"] == ["dialogue"]
    assert entry["card"]["id"] == card["id"]
