"""Deterministic offline LLM stub for smoke tests.

StoryForge normally spends one API call per phase. This module patches
``pipeline.api.CrofaiClient.chat`` so a whole run completes with no API key,
no network and no cost, and answers each phase with a reply that satisfies the
real parser for that phase.

    from pipeline.stub_provider import stubbed_llm

    with stubbed_llm() as stub:
        run_full_pipeline("a seed phrase", quick=True, feedback_enabled=False,
                          project_dir_override=tmp)
    print(stub.calls)        # one row per answer, for auditing

Answers are derived from the seed phrase, so the generated story is
recognisably the story that was asked for. Chapter prose is spun from word
pools that are consumed without replacement: that keeps the lexical variety
high enough to clear ``prose_lab``'s bands, which is what makes the smoke test
worth reading rather than a rubber stamp.

Nothing here imports a network library. If a phase is not recognised the stub
returns prose rather than raising, so a run degrades into a visible failure in
the report instead of a traceback.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------
# Pools are consumed without replacement and only recycle once exhausted, so a
# 1000-word chapter draws on several hundred distinct words. Every entry avoids
# config.writing.banned_words and prose_lab's tell patterns.

OPENERS = (
    "Later Dusk Rain Brass Smoke Memory Copper Ash Salt River Sugar Iron Glass"
    "Midnight Morning Evening Winter Summer Autumn Spring Harbour Alley Rooftop"
    "Downstairs Upstairs Outside Inside Beyond Beneath Above Across Through"
    "Once Twice Again Still Yet Now Then Afterwards Meanwhile Somewhere"
).split()

ADJS = (
    "chipped lacquered sour hollow rusted gilded brittle sunken crooked braided"
    "damp scorched frayed polished tarnished stubborn tender souring restless"
    "patient furious quiet loud careful reckless weary hungry patient paper"
    "copper wooden velvet tinny salt-stained rain-slicked candle-lit moth-eaten"
    "hand-stitched second-hand borrowed unpaid unspoken half-remembered late"
    "early cold warm sticky slick blunt sharp heavy weightless narrow wide"
).split()

NOUNS = (
    "trumpet valve mouthpiece reed drumhead banjo string rosin case latch hinge"
    "lantern wick kerosene matchbox cigarette ashtray curtain carpet stair rail"
    "ledger receipt invoice debt wager ticket stub coin purse ledger-button"
    "hymn psalm choir organ bell chime whistle horn siren drum fiddle bow"
    "scar bandage gauze tincture bitter-root poultice splint plaster liniment"
    "photograph letter telegram postcard ribbon brooch locket ring cufflink"
    "gutter tramline sidewalk porch shutter awning alley quay wharf levee pier"
    "oyster icebox stove kettle skillet skillet-handle cupboard floorboard"
    "mosquito magnolia cypress kudzu Spanish-moss cicada heron catfish"
).split()

VERBS = (
    "rattled hummed clattered wheezed groaned rattled-off cracked splintered"
    "hissed murmured rasped thundered whispered clanged chimed tolled stuttered"
    "flickered guttered smoked steamed boiled simmered cooled hardened softened"
    "curled folded twisted bent buckled sagged leaned tilted swayed staggered"
    "scraped scrubbed polished buffed hammered filed soldered stitched patched"
    "swollen drained filled emptied spilled splashed dripped pooled evaporated"
).split()
VERBS = list(dict.fromkeys(VERBS))

PLACES = (
    "Basin Street Rampart Basin-story Perdido hallback Storyville Frenchmen"
    "Congo-Square Treme Marigny Bywater riverfront levee-side warehouse-row"
    "cathedral-side cemetery-lane chapel-row hospital-stair boarding-house"
    "dancehall balcony kitchen doorway corridor pantry attic cellar"
).split()

SENSORY = (
    "chicory orange-peel wet-wool river-mud magnolia-rot chicory-coffee"
    "burnt-sugar stale-beer lamp-oil carbolic-soap sea-salt hot-brass"
    "cypress-smoke fried-oyster sour-mash rain-on-tar honeysuckle dust"
).split()

TIMES = (
    "two hours past midnight before the second set after the last tram"
    "at the turn of the tide when the streetlamps failed an hour before dawn"
    "in the thick of the afternoon through the whole long evening"
    "on the night the river rose by the third verse of the hymn"
).split()

QUOTE_VERBS = ("said", "told her", "answered", "muttered", "called back",
               "insisted", "admitted", "repeated", "corrected him", "agreed")

STOP = set("the a an of and or to in on at for with from by".split())


def _keywords(concept: str) -> list[str]:
    """Pull distinctive words out of the seed phrase, in order of appearance."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", concept or "")
    seen, out = set(), []
    for w in words:
        low = w.lower()
        if low in STOP or low in seen:
            continue
        seen.add(low)
        out.append(w)
    return out[:14]


def _title_case(words: list[str], fallback: str) -> str:
    if not words:
        return fallback
    pick = words[:5]
    return " ".join(w if w[:1].isupper() else w.capitalize() for w in pick)


class _Spinner:
    """Consumes pools front-first; recycles only when a pool runs dry."""

    def __init__(self, seed_words: Optional[list[str]] = None):
        self.pools: dict[str, list[str]] = {
            "opener": list(OPENERS), "adj": list(ADJS), "noun": list(NOUNS),
            "verb": list(VERBS), "place": list(PLACES), "sensory": list(SENSORY),
            "time": list(TIMES), "seed": list(seed_words or []),
        }
        self.recycled = 0
        self._quote_i = 0

    def take(self, key: str) -> str:
        pool = self.pools[key]
        if not pool:
            base = {"opener": OPENERS, "adj": ADJS, "noun": NOUNS, "verb": VERBS,
                    "place": PLACES, "sensory": SENSORY, "time": TIMES,
                    "seed": None}[key]
            if base is None:
                self.pools[key] = []
                return "the story"
            self.pools[key] = list(base)
            pool = self.pools[key]
            self.recycled += 1
        return pool.pop(0)

    def quote_verb(self) -> str:
        v = QUOTE_VERBS[self._quote_i % len(QUOTE_VERBS)]
        self._quote_i += 1
        return v


# Sentence forms. Glue words rotate too, so even function words vary.
_FORMS = (
    lambda s, n: f"{s.take('opener')}, the {s.take('adj')} {s.take('noun')} {s.take('verb')} against the {s.take('adj')} {s.take('noun')}.",
    lambda s, n: f"{n} carried the {s.take('noun')} down three flights, past the {s.take('adj')} {s.take('noun')} and the {s.take('noun')} nobody had oiled {s.take('time')}.",
    lambda s, n: f"{s.take('adj').capitalize()} {s.take('noun')}. {s.take('adj').capitalize()} {s.take('noun')}. {s.take('sensory').capitalize()} in the stairwell, {s.take('sensory')} on the {s.take('noun')}.",
    lambda s, n: f"The {s.take('noun')} {s.take('verb')} twice, and the whole {s.take('place')} answered it with a {s.take('adj')} {s.take('noun')} that nobody wrote down.",
    lambda s, n: f"{n} counted {s.take('noun')}s, {s.take('noun')}s, {s.take('noun')}s, {s.take('noun')}s, one {s.take('adj')} {s.take('noun')} after another, until the arithmetic stopped meaning anything.",
    lambda s, n: f"Nobody in the {s.take('place')} would trade a {s.take('adj')} {s.take('noun')} for a {s.take('adj')} {s.take('noun')}, not {s.take('time')}.",
    lambda s, n: f"Every {s.take('noun')} in that room had a price, and the price had a {s.take('noun')}, and the {s.take('noun')} had a {s.take('adj')} {s.take('noun')} waiting behind it.",
    lambda s, n: f"{s.take('opener')} the {s.take('noun')} {s.take('verb')}, and {n} heard the {s.take('sensory')} under it, thick as {s.take('sensory')}.",
    lambda s, n: f"A {s.take('adj')} {s.take('noun')} lay across the {s.take('noun')}, split down the middle, still warm from the {s.take('place')}.",
    lambda s, n: f"{n} played four bars, stopped, played the same four bars against the {s.take('adj')} {s.take('noun')} until the {s.take('noun')} gave.",
    lambda s, n: f"Somewhere below, a {s.take('noun')} {s.take('verb')} into a {s.take('noun')}, and the {s.take('place')} kept the sound the way a jar keeps {s.take('sensory')}.",
    lambda s, n: f"The bargain held for {s.take('time')}: one {s.take('adj')} {s.take('noun')} mended, one {s.take('adj')} {s.take('noun')} taken.",
)

_DIALOGUE = (
    ("You played it again.", "Twice.", "Twice is a habit. Three times is a debt."),
    ("Where does it go, the thing you take?", "Ask the {noun}. The {noun} keeps the accounts.", None),
    ("I can mend the {noun}.", "You can mend a hundred {noun}s and still owe me the {noun}.", None),
    ("Play something honest.", "Honest costs extra.", "Then charge me."),
    ("That {noun} belonged to my mother.", "It belongs to the {place} now. Everything does, {time}.", None),
    ("Stop counting.", "Someone has to.", "Not tonight."),
    ("You heard the {noun} {verb}.", "I heard the {noun}.", "Then you heard what followed it."),
    (None, None, None),
)


def _fill(template: str, s: _Spinner) -> str:
    out = template
    for _ in range(4):
        out = out.replace("{noun}", s.take("noun"), 1)
        out = out.replace("{verb}", s.take("verb"), 1)
        out = out.replace("{time}", s.take("time"), 1)
        out = out.replace("{place}", s.take("place"), 1)
    return out


def spin_prose(seed_words: list[str], speaker: str, paragraphs: int = 14,
               offset: int = 0, dialogue_every: int = 4) -> str:
    """Spin chapter prose. Deterministic for a given (seed_words, offset)."""
    s = _Spinner(seed_words)
    out: list[str] = []
    form_i = offset % len(_FORMS)
    for p in range(paragraphs):
        lines: list[str] = []
        n_sentences = 2 + ((p + offset) % 4)          # 2..5 sentences, varied
        for _ in range(n_sentences):
            if dialogue_every and (len(out) + len(lines)) % dialogue_every == dialogue_every - 1:
                d = _DIALOGUE[(p + offset) % len(_DIALOGUE)]
                if d[0] is not None:
                    bits = [f'"{_fill(x, s)}"' for x in d if x]
                    bits.insert(1, f"{speaker} {s.quote_verb()},")
                    lines.append(" ".join(bits))
                else:
                    lines.append(_FORMS[form_i % len(_FORMS)](s, speaker))
                    form_i += 1
            else:
                lines.append(_FORMS[form_i % len(_FORMS)](s, speaker))
                form_i += 1
        out.append(" ".join(lines))
    return "\n\n".join(out)


def _short_prose(seed_words: list[str], speaker: str) -> str:
    """Deliberately under-length chapter: exercises the redraw path."""
    kw = " ".join(seed_words[:5]) or "the story"
    return (f"{speaker} walked into the {kw} room. The door stuck. "
            f"She played one bar and stopped. Nothing answered.\n\n"
            f"That was the whole of it, for now.")


# ---------------------------------------------------------------------------
# Phase answers
# ---------------------------------------------------------------------------

def _names(seed_words: list[str]) -> list[list[str]]:
    """Seven distinct two-part names, flavoured by the seed phrase.

    Always seven: ``characters_answer`` indexes ``names[(i + 1) % 7]`` and
    ``world_answer`` indexes ``names[3]``, so a short list is an IndexError
    rather than a smaller cast.
    """
    firsts = ["Odalie", "Rue", "Cordel", "Ivory", "Mabry", "Sylvane", "Theron"]
    lasts = ["Beaumont", "Villareal", "Okonjo", "Marchetti", "Devereux",
             "Lafleur", "Quimby"]
    if seed_words:
        stem = seed_words[0][:4].capitalize()
        lasts = [f"{stem}well", lasts[0]] + lasts[1:]
    lasts = (list(lasts) * 2)[:len(firsts)]
    return [[f, l] for f, l in zip(firsts, lasts)]


ABSTRACT_COSTS = (
    "memory", "name", "year", "voice", "dream", "secret", "debt", "breath",
    "song", "face", "hour", "truth", "promise", "colour", "color", "sleep",
)


def _lower_content(concept: str) -> list[str]:
    """Distinctive words that the seed phrase wrote in lower case.

    Capitalised words are usually names and places, and a name makes a poor
    motif: "New Orleans" used to yield the cost word "Orleans". Lower-case
    words are the phrase's own subject matter, so they carry motif and cost.
    """
    out: list[str] = []
    seen: set[str] = set()
    for w in re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", concept or ""):
        if not w.islower():
            continue
        low = w.lower()
        if low in STOP or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


def _pick_motif_cost(concept: str) -> tuple[str, str]:
    """Choose the story's motif and its cost from the phrase's own words."""
    cw = _lower_content(concept)
    nouns = {n.lower() for n in NOUNS}
    motif = next((w for w in cw if w in nouns), "")
    if not motif:
        motif = cw[0] if cw else "trumpet"
    cost = next((w for w in cw if w in ABSTRACT_COSTS), "")
    if not cost:
        tail = [w for w in cw if w != motif]
        cost = tail[-1] if tail else "memory"
    return motif, cost


def _story_title(kw: list[str], motif: str, cost: str) -> str:
    """A title from the phrase's own subject matter, not its proper nouns.

    ``_title_case`` over the raw keywords used to yield "Jazz Musician Orleans
    Heals Wounds": it kept the place name out of "New Orleans". Motif and cost
    come from lower-case words, so a title built from them reads like a title.
    """
    if motif and cost and motif != cost:
        return f"The {cost.title()} of the {motif.title()}"
    return _title_case(kw, "The Untitled Rehearsal")


def _story(seed_phrase: str) -> dict[str, Any]:
    kw = _keywords(seed_phrase)
    names = _names(kw)
    lead = f"{names[0][0]} {names[0][1]}"
    motif, cost = _pick_motif_cost(seed_phrase)
    title = _story_title(kw, motif, cost)
    return {
        "keywords": kw, "names": names, "lead": lead, "title": title,
        "motif": motif, "cost": cost,
        "second": f"{names[1][0]} {names[1][1]}",
        "rival": f"{names[2][0]} {names[2][1]}",
    }


def spec_answer(story: dict, chapters: int = 3) -> dict:
    kw = story["keywords"]
    return {
        "title": story["title"],
        "genre": "historical fantasy",
        "premise": (f"{story['lead']} mends the wounded with the {story['motif']} "
                    f"and pays for each mending with one {story['cost']} of a person "
                    f"she loves."),
        "tone": "tender and bruised",
        "pov": "third limited",
        "tense": "past",
        "target_length": max(1, chapters) * 4000,
        "target_chapters": max(1, chapters),
        "themes": ["the price of gift", "what a city forgets", "debt and devotion"],
        "unique_angle": f"Each healing costs a named {story['cost']}, logged in a ledger.",
        "initial_direction": ("Open on the {0} at work, then the first {1} that goes "
                              "missing, then the ledger that records it. Keep the "
                              "{2} concrete and audible.".format(story["motif"], story["cost"], story["motif"])),
        "seed_keywords": kw,
    }


def world_answer(story: dict) -> dict:
    return {
        "world_name": f"{story['title']} Basin",
        "geography": "A river city of low streets, levees, balconies and one hill.",
        "history": "Two fires, one flood, one epidemic, and a century of music after.",
        "factions": [
            {"name": "The Musicians' Mutual", "goal": "protect players and their pensions",
             "leader": story["second"], "relationship_to_protagonist": "employer"},
            {"name": "The Charity Hospital Board", "goal": "keep the wards cheap",
             "leader": story["rival"], "relationship_to_protagonist": "suspicious patron"},
            {"name": "The River Preachers", "goal": "read the water for omens",
             "leader": story["names"][3][0] + " " + story["names"][3][1],
             "relationship_to_protagonist": "allies with conditions"},
        ],
        "power_system": (f"Gifts run through brass and breath. A mending costs one "
                          f"{story['cost']} from someone the player loves; the cost is "
                          f"recorded whether or not the player writes it down."),
        "cultures": "Creole, Irish, Haitian, German, and one neighbourhood that claims none of them.",
        "central_conflict": (f"{story['lead']} keeps healing people the city cannot afford "
                             f"to lose, while the ledger of stolen {story['cost']}s grows faster "
                             f"than she can read it."),
        "mood_setting": "Humid, loud, generous, and running out of time.",
    }


def characters_answer(story: dict) -> dict:
    roles = ["protagonist", "deuteragonist", "antagonist", "supporting",
             "supporting", "supporting", "supporting"]
    jobs = [
        ("mends the wounded with music and loses a piece of the people she loves",
         "keeps playing after the cost becomes visible", "pride", "the ledger is hers"),
        ("runs the Musicians' Mutual and knows every debt in the ward",
         "chooses the union over the friendship", "loyalty to an institution", "signed the hospital contract"),
        ("chairs the Charity Hospital Board and wants the gift regulated",
         "moves from obstacle to reluctant witness", "control", "funded the first experiment"),
        ("preaches at the river and reads the water",
         "admits the omens are guesses", "certainty", "once healed by the lead"),
        ("keeps the dancehall books", "tells the truth late", "cowardice", "owes the rival"),
        ("plays second trumpet", "learns the cost", "envy", "took one mending for free"),
        ("nurses the epidemic ward", "holds the line", "exhaustion", "lost a brother"),
    ]
    chars = []
    for i, role in enumerate(roles):
        first, last = story["names"][i]
        want, arc, flaw, secret = jobs[i]
        chars.append({
            "name": f"{first} {last}", "title": "", "display_name": first,
            "role": role, "age": ["thirty-one", "fifty-four", "sixty",
                                  "forty-two", "twenty-six", "twenty-nine", "thirty-eight"][i],
            "appearance": f"Carries a {ADJS[i % len(ADJS)]} case; hands marked by {NOUNS[i % len(NOUNS)]} work.",
            "personality": f"{arc.split()[0].capitalize()}, precise, slow to trust.",
            "background": f"Two paragraphs would flatter {first}; one will do. Raised near the {PLACES[i % len(PLACES)]}.",
            "motivation": want, "flaw": flaw, "secret": secret,
            "arc": f"From {flaw} toward {arc}.",
            "voice": ["clipped, no contractions", "long clauses, warm", "official, cold",
                      "biblical, sly", "nervous, fast", "plain, blunt", "dry, brief"][i],
            "relationships": [
                {"with": f"{story['names'][(i + 1) % 7][0]} {story['names'][(i + 1) % 7][1]}",
                 "dynamic": "owes and is owed"},
            ],
        })
    return {
        "characters": chars,
        "relationship_map": ("Seven people, one ledger, and a debt that changes hands "
                             "every time the music plays."),
        "pov_assignment": f"{story['lead']} narrates acts one and three; {story['second']} takes act two.",
    }


def outline_answer(story: dict, n_chapters: int = 3) -> dict:
    chars = characters_answer(story)["characters"]
    titles = ["The First Bar", "What the Ledger Keeps", "A Debt in Brass",
              "The Ward at Midnight", "River Reading"]
    beats = ["wants the gift to stay secret", "counts what the gift has taken",
             "confesses one mending", "breaks the bargain", "pays the ledger down"]
    arcs = ["rising dread", "quiet grief", "confrontation", "release", "costly peace"]
    chapters = []
    for i in range(max(1, n_chapters)):
        chapters.append({
            "chapter": i + 1,
            "title": titles[i % len(titles)],
            "pov": chars[i % len(chars)]["name"],
            "summary": (f"{chars[i % len(chars)]['name']} {beats[i % len(beats)]} "
                        f"while the {story['motif']} work continues."),
            "key_events": [
                f"A mending in the {PLACES[i % len(PLACES)]} costs one {story['cost']}.",
                f"{chars[(i + 1) % len(chars)]['name']} witnesses it and says nothing.",
                "The ledger gains a line nobody wrote.",
            ],
            "character_arc_beat": beats[i % len(beats)],
            "emotional_arc": arcs[i % len(arcs)],
            "foreshadowing": f"The {story['cost']} taken here returns in act three.",
        })
    return {
        "story_structure": "three_act",
        "acts": [
            {"act_number": 1, "name": "Gift", "summary": "The work and its first cost.",
             "chapters": chapters[: max(1, n_chapters // 2 + 1)]},
            {"act_number": 2, "name": "Debt", "summary": "The ledger is discovered.",
             "chapters": chapters[max(1, n_chapters // 2 + 1):] or []},
        ],
        "major_plot_points": ["first mending", "ledger found", "bargain broken", "cost paid"],
        "pacing_notes": "Short chapters, one cost per chapter, no chapter without a sound.",
    }


def validator_answer() -> dict:
    ok = {"status": "PASS", "detail": "No structural defects found.", "issues": []}
    return {
        "chapter_count_check": ok, "pacing_check": ok, "arc_check": ok,
        "foreshadowing_check": ok, "pov_check": ok,
        "overall": "PASS",
        "summary": "Structure holds: three chapters, one cost each, arcs land.",
    }


def critic_answer(story: dict) -> dict:
    return {
        "prose_craft": 8, "narrative_architecture": 8, "character_authenticity": 7,
        "tension_management": 8, "overall_score": 8,
        "specific_failures": [{"quote": "The door stuck.", "failure": "flat beat",
                               "fix": "give the door a sound and a history"}],
        "strengths": ["sensory density", "the cost stays concrete"],
        "fundamental_issues": [],
    }


def professor_answer(story: dict) -> dict:
    return {
        "thematic_coherence": 8, "structural_integrity": 8, "reader_experience": 8,
        "voice_consistency": 8, "overall_score": 8,
        "craft_observations": [{"element": "the ledger",
                                "assessment": "carries the theme without speech",
                                "alternative": "let one entry be wrong"}],
        "what_to_preserve": ["the sound of the instrument"],
        "growth_areas": ["vary paragraph openings"],
    }


def synthesis_answer() -> dict:
    return {
        "unified_score": 8,
        "critical_issues": [{"issue": "one flat beat", "priority": "low",
                             "target": "second paragraph"}],
        "revision_instructions": ["Keep the sound; sharpen the door.",
                                  "Cut one adjective cluster."],
        "preserve": ["the ledger motif"],
        "synthesis_notes": "Both readers agreed the cost stays concrete.",
    }


def debate_answer(story: dict, kind: str) -> dict:
    return {
        "verdict": "SUSTAINED_IN_PART", "severity": "low",
        "complaints": [{"issue": f"the {story['cost']} count differs by one",
                        "canonical_ref": "chapter_1", "severity": "low",
                        "fix": "state the count once"}],
        "continuity_errors": [], "structural_issues": [],
        "summary": f"No blocking defect; one {kind} note.",
    }


def changes_answer(story: dict, chapter_num: int) -> str:
    block = {
        "character_status": [{"character": story["lead"], "change_type": "mental state",
                              "detail": "accepts the cost", "chapter": chapter_num}],
        "conflict_progress": [], "plot_nodes": [],
        "foreshadowing_actions": [{"element": "the ledger", "action": "setup",
                                   "detail": f"one {story['cost']} recorded", }],
    }
    return ("\n---CHANGES---\n" + json.dumps(block, indent=2) + "\n---END CHANGES---")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_ROUTES = (
    ("seed", ("Analyze this story seed", "structured project specification")),
    ("world", ("comprehensive world bible",)),
    ("characters", ("rich character profiles",)),
    ("outline", ("chapter-by-chapter outline",)),
    ("validator", ("Evaluate this novel outline",)),
    ("critic", ("Review this chapter",)),
    ("professor", ("MFA professor",)),
    ("synthesis", ("Synthesize these two reviews",)),
    ("debate_lore", ("continuity errors against the canonical record",)),
    ("debate_plot", ("structural and plot integrity",)),
    ("debate_verdict", ("Render a verdict on Chapter",)),
    ("revision", ("Revise this chapter",)),
    ("draft", ("Write Chapter",)),
)


def classify(prompt: str, system: str = "") -> str:
    text = f"{system}\n{prompt}"
    for phase, marks in _ROUTES:
        if any(m in text for m in marks):
            return phase
    if "chapter" in text.lower() and "outline" not in text.lower():
        return "draft"
    return "fallback"


def _chapter_num(prompt: str) -> int:
    m = re.search(r"Chapter\s+(\d+)", prompt)
    return int(m.group(1)) if m else 1


class StubLLM:
    """Records every answer it gives; ``calls`` is the audit trail."""

    def __init__(self, concept: str = "", short_first: int = 0, chapter_words: int = 1000,
                 chapters: int = 3):
        self.concept = concept or ""
        self.story = _story(self.concept)
        self.short_first = short_first            # how many first drafts come back short
        self.chapter_words = chapter_words
        self.chapters = max(1, int(chapters))     # chapters the outline offers to draft
        self.calls: list[dict] = []
        self._seen: dict[str, int] = {}

    # -- learning -----------------------------------------------------------
    def note_concept(self, prompt: str) -> None:
        """Pick the seed phrase up out of the seed prompt when not given one."""
        if self.concept:
            return
        m = re.search(r"Seed concept:\s*(.+)", prompt)
        if m:
            self.concept = m.group(1).strip()
            self.story = _story(self.concept)

    # -- entry point --------------------------------------------------------
    def answer(self, prompt: str, system: str = "", model: Any = None) -> str:
        phase = classify(prompt, system)
        self.note_concept(prompt)
        key = hashlib.sha1((phase + prompt[:400]).encode()).hexdigest()[:12]
        self._seen[key] = self._seen.get(key, 0) + 1
        first = self._seen[key] == 1
        text = self._render(phase, prompt, first=first)
        self.calls.append({
            "phase": phase, "model": getattr(model, "name", str(model)),
            "first": first, "repeat": self._seen[key],
            "words": len(text.split()), "chars": len(text),
        })
        return text

    def _render(self, phase: str, prompt: str, first: bool) -> str:
        st = self.story
        speaker = st["lead"].split()[0]
        if phase == "seed":
            return json.dumps(spec_answer(st, self.chapters), indent=2)
        if phase == "world":
            return json.dumps(world_answer(st), indent=2)
        if phase == "characters":
            return json.dumps(characters_answer(st), indent=2)
        if phase == "outline":
            n = self.chapters
            m = re.search(r"(\d+)\s+chapters", prompt)
            if m and not self.chapters:
                n = max(1, int(m.group(1)))
            return json.dumps(outline_answer(st, n), indent=2)
        if phase == "validator":
            return json.dumps(validator_answer(), indent=2)
        if phase == "critic":
            return json.dumps(critic_answer(st), indent=2)
        if phase == "professor":
            return json.dumps(professor_answer(st), indent=2)
        if phase == "synthesis":
            return json.dumps(synthesis_answer(), indent=2)
        if phase.startswith("debate"):
            return json.dumps(debate_answer(st, phase), indent=2)

        n = _chapter_num(prompt)
        offset = (n * 5) % len(_FORMS)
        if phase in ("draft", "fallback") and first and self.short_first:
            self.short_first -= 1
            return _short_prose(st["keywords"], speaker)
        paragraphs = max(6, -(-self.chapter_words // 54))   # ceil: ~54 words a paragraph
        prose = spin_prose(st["keywords"], speaker, paragraphs=paragraphs,
                           offset=offset + (0 if phase == "draft" else 3))
        if phase == "revision":
            prose += "\n\n" + spin_prose(st["keywords"], speaker, paragraphs=3,
                                         offset=offset + 9)
        if phase == "draft":
            prose += changes_answer(st, n)
        return prose

    # -- summary ------------------------------------------------------------
    def phases(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.calls:
            out[c["phase"]] = out.get(c["phase"], 0) + 1
        return out


@contextmanager
def stubbed_llm(concept: str = "", short_first: int = 0, chapter_words: int = 1000,
                chapters: int = 3):
    """Patch CrofaiClient.chat with the deterministic stub for the block."""
    from pipeline import api as api_mod

    stub = StubLLM(concept=concept, short_first=short_first,
                   chapter_words=chapter_words, chapters=chapters)

    def _chat(self, model, messages, system_prompt=None, **kwargs):
        prompt = ""
        for m in reversed(messages or []):
            if isinstance(m, dict) and m.get("role") == "user":
                prompt = m.get("content", "")
                break
        return stub.answer(prompt, system_prompt or "", model=model)

    orig_chat, orig_close = api_mod.CrofaiClient.chat, api_mod.CrofaiClient.close
    api_mod.CrofaiClient.chat = _chat
    api_mod.CrofaiClient.close = lambda self: None
    try:
        yield stub
    finally:
        api_mod.CrofaiClient.chat = orig_chat
        api_mod.CrofaiClient.close = orig_close
