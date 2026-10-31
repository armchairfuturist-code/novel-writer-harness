"""Deterministic prose instrument: numbers a chapter can be gated on.

StoryForge's quality loop used to run on one regex count and a flat base score,
so a clean chapter exited revision on round 0 and a 165-word stub could outrank
a full chapter. This module adds a cheap, model-free measurement pass that sits
in front of every expensive judge call: it reports phrase-level tells, rhythm,
vocabulary rarity and dialogue share as rates per 1,000 words, each against a
band, and folds them into one 0-10 number with a list of violations that carry
their own fix text (so a revision prompt can quote them).

Design notes, with attribution:
- Category taxonomy (arrival scaffolding, hedge trail, warm-up, belt-and-
  suspenders, overcompletion) follows the revision-residue types described by
  Compound Writing's tracks and ai-check skills. Rules and fix text here are
  written for this repo, not copied; that project ships no license.
- Rarity over rules follows milesoncken/longtail: humans sit near the 84th
  percentile of feature-space rarity while checklist-driven "humanized" prose
  forms a new dense cluster. So the lexis rules flag LOW rarity, and the dash
  rule flags both extremes instead of banning a mark.
- Bands are per-batch. `bands_from()` fits the manuscript's own running
  distribution and `drift()` scores one chapter against it, which is how voice
  consistency across 300 pages gets a number instead of an opinion.

Stdlib only, no network, no model calls. CLI exits 1 below threshold so CI can
gate on it:  python -m pipeline.prose_lab chapter.md [more.md ...]
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------
# Each rule: (name, category, compiled pattern, band per 1k words, weight, fix)
# `band` is the rate the prose may carry for free; above it, the excess is
# penalised by `weight`. Single words already in config.banned_words are
# deliberately absent so nothing is penalised twice.

_RULE_SPECS: list[tuple[str, str, str, float, float, str]] = [
    # -- emotion naming / mental scaffolding (the "hedge trail") -------------
    ("felt_naming", "tell", r"\b(?:he|she|they|i|you)\s+felt\b", 3.0, 1.0,
     "Name the sensation in the body or the action it causes, not the feeling word."),
    ("wave_of_emotion", "tell", r"\ba\s+(?:wave|surge|rush|pang|jolt)\s+of\s+\w+", 2.0, 1.0,
     "Cut the metaphor; show one physical consequence instead."),
    ("mental_verb_that", "tell", r"\b(?:knew|realized|thought|decided|understood|noticed)\s+that\b", 4.0, 0.8,
     "Drop the framing clause and state what the character perceives."),
    ("seemed_appeared", "tell", r"\b(?:seemed|appeared|looked)\s+to\b", 3.0, 0.8,
     "Commit to the observation or give the character the doubt in dialogue."),
    ("could_not_help", "tell", r"\bcould(?:n[o']t| not)\s+help\s+but\b", 1.0, 1.2,
     "Let the character act; the compulsion is the action."),
    ("it_was_clear", "tell", r"\bit\s+was\s+(?:clear|obvious|apparent|evident|plain)\s+that\b", 1.5, 1.2,
     "Show the evidence and let the reader conclude."),

    # -- arrival sequence / scene-entry scaffolding -------------------------
    ("began_to", "arrival", r"\b(?:began|started|proceeded|set about)\s+to\b", 4.0, 0.9,
     "Start the sentence at the action itself: 'began to walk' -> 'walked'."),
    ("made_way", "arrival", r"\bmade\s+(?:his|her|their|my)\s+way\s+(?:to|toward|towards|back|through|into)\b",
     2.0, 1.0, "Cut the transit; open on the arrival beat that changes something."),
    ("entering_clause", "arrival",
     r"\bas\s+(?:he|she|they|i)\s+(?:walked|stepped|entered|came|arrived|climbed|headed|turned)\b",
     3.0, 0.9, "Anchor the entrance to a detail the POV character would notice."),

    # -- belt-and-suspenders / overcompletion ------------------------------
    ("moment_filler", "cliche", r"\b(?:in|at|for)\s+(?:that|a|one)\s+(?:brief\s+|long\s+)?moment\b", 4.0, 0.9,
     "Cut the beat marker; the scene change carries the pause."),
    ("testament_to", "cliche", r"\b(?:a\s+)?testament\s+to\b", 0.5, 1.5,
     "Delete: it states the theme the reader should infer."),
    ("little_did", "cliche", r"\blittle\s+did\s+(?:he|she|they|i)\s+know\b", 0.5, 1.5,
     "Delete the narratorial tease; dramatise the consequence when it lands."),
    ("spine_shiver", "cliche", r"\bshiver\w*\s+(?:ran|went|coursed|down)\b|\bdown\s+(?:his|her|their|my)\s+spine\b",
     1.0, 1.2, "Replace with a specific, non-standard physical reaction."),
    ("heart_raced", "cliche", r"\bheart\s+(?:raced|pounded|hammered|thundered|leapt|sank|stuttered)\b", 2.0, 1.0,
     "Use one fresh signal of fear, or let the dialogue show it."),
    ("breath_caught", "cliche", r"\bbreath\s+(?:caught|hitched|left|stalled)\b|\bcaught\s+(?:his|her|their|my)\s+breath\b",
     1.5, 1.0, "Cut; find the perception that actually changes for the character."),
    ("time_stopped", "cliche", r"\btime\s+(?:seemed\s+to\s+)?(?:slowed|stopped|stood\s+still|froze)\b", 0.8, 1.3,
     "Delete the cliche and slow the prose instead: shorter clauses, more detail."),
    ("weight_of", "cliche", r"\bthe\s+weight\s+of\b", 2.5, 0.8,
     "Name the specific obligation or grief rather than the metaphor."),
    ("silence_hung", "cliche", r"\bsilence\s+(?:hung|filled|stretched|settled|thickened)\b", 1.5, 1.0,
     "Put something audible in the room instead."),
    ("knowing_smile", "cliche", r"\ba\s+(?:knowing|sly|secret|wry|thin|tight)\s+smile\b", 2.0, 0.9,
     "Let the smile do something, or replace it with the line of dialogue it hides."),
    ("eye_verb", "cliche", r"\beyes\s+(?:widened|narrowed|darkened|softened|searched|flickered|gleamed)\b",
     3.0, 0.8, "Vary the tell; eyes carry too much of the emotional load in AI prose."),
    ("not_x_but_y", "cliche", r"\bnot\s+\w[\w\s,']{0,30}?,\s+but\s+\w", 4.0, 0.7,
     "Break the negative-parallelism rhythm; state the second half directly."),
    ("it_wasnt_x_it_was", "cliche", r"\bit\s+was(?:n[o']t| not)\s+\w[\w\s']{0,25}?,\s+it\s+was\b", 1.5, 1.1,
     "Cut the correction scaffold and keep the observation."),
    ("delve_tapestry", "cliche",
     r"\b(?:delve|delving|tapestry|testament|realm|landscape|journey|embark|nuanced|multifaceted)\b",
     1.0, 1.3, "Replace the abstract noun with a concrete, scene-specific one."),
    ("reminded_of", "cliche", r"\breminded\s+(?:him|her|them|me)\s+of\b", 3.0, 0.7,
     "Give the comparison as an image in-scene, not as a memory footnote."),

    # -- summarising / narratorial over-explanation -------------------------
    ("in_summary", "overcompletion",
     r"\b(?:in the end|ultimately|all in all|when all was said and done|by the time)\b", 2.0, 1.0,
     "Cut the wrap-up; end the scene on an image or a line of dialogue."),
    ("explained_that", "overcompletion",
     r"\b(?:explained|clarified|pointed out|noted|added)\s+that\b", 3.0, 0.8,
     "Trust the dialogue tag or drop it; the speech should carry the meaning."),
    ("as_you_know", "overcompletion",
     r"\bas\s+(?:you|he|she|they)\s+(?:know|knew|already\s+know)\b", 1.0, 1.2,
     "Delete the information-boundary scaffold; reveal only what this POV can see."),
]

RULES: list[dict[str, Any]] = [
    {"name": n, "category": c, "re": re.compile(p, re.IGNORECASE), "band": b, "weight": w, "fix": f}
    for (n, c, p, b, w, f) in _RULE_SPECS
]

# Marks that should be banded on both sides: models overuse or scrub them.
_DASH_RE = re.compile(r"[\u2014\u2013]|--")
_PAREN_RE = re.compile(r"\([^)]{3,}\)")

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'\u201c\u2018A-Z])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\u2019-]*")
_DIALOGUE_RE = re.compile(r"[\"\u201c][^\"\u201d]{1,600}[\"\u201d]")
_WEATHER_OPEN_RE = re.compile(
    r"^\s*(?:the\s+)?(?:sun|morning|evening|night|rain|snow|wind|storm|fog|clock|street|city|day|dark|light)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _std(xs: Iterable[float]) -> float:
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _strip_front_matter(text: str) -> str:
    """Drop a YAML block and markdown headers/blockquotes so they do not skew lexis."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    lines = [ln for ln in text.splitlines()
             if not ln.lstrip().startswith(("#", ">", "|", "```"))]
    return "\n".join(lines)


def measure(text: str) -> dict[str, float]:
    """Raw stylometric features. No bands, no score: this is the input to drift()."""
    body = _strip_front_matter(text)
    words = _WORD_RE.findall(body)
    n_words = len(words)
    if n_words == 0:
        return {"word_count": 0, "sentence_mean": 0.0, "sentence_sd": 0.0,
                "paragraph_mean": 0.0, "paragraph_sd": 0.0, "dialogue_share": 0.0,
                "type_token": 0.0, "hapax_ratio": 0.0, "dash_per_1k": 0.0,
                "paren_per_1k": 0.0, "comma_per_sentence": 0.0, "open_repeat": 0.0}

    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(body) if len(s.strip()) > 1]
    s_lens = [len(_WORD_RE.findall(s)) for s in sentences] or [0]
    paras = _paragraphs(body)
    p_lens = [len(_WORD_RE.findall(p)) for p in paras] or [0]

    lower = [w.lower() for w in words]
    counts = Counter(lower)
    types = len(counts)
    hapax = sum(1 for w, c in counts.items() if c == 1)

    dialogue_words = sum(len(_WORD_RE.findall(m)) for m in _DIALOGUE_RE.findall(body))

    # Sentence-initial repetition: how often the same opener starts a run.
    openers = [re.match(r"[A-Za-z'\u201c]+", s).group(0).lower()
               for s in sentences if re.match(r"[A-Za-z'\u201c]+", s)]
    open_repeat = 0.0
    if len(openers) >= 3:
        for i in range(len(openers) - 2):
            if openers[i] == openers[i + 1] == openers[i + 2]:
                open_repeat += 1.0
        open_repeat = open_repeat / max(len(openers) - 2, 1)

    k = 1000.0 / n_words
    return {
        "word_count": float(n_words),
        "sentence_mean": sum(s_lens) / len(s_lens),
        "sentence_sd": _std(s_lens),
        "paragraph_mean": sum(p_lens) / len(p_lens),
        "paragraph_sd": _std(p_lens),
        "dialogue_share": dialogue_words / n_words,
        # Rarity proxies: low values mean the prose sits in a dense cluster.
        "type_token": types / n_words,
        "hapax_ratio": hapax / max(types, 1),
        "dash_per_1k": len(_DASH_RE.findall(body)) * k,
        "paren_per_1k": len(_PAREN_RE.findall(body)) * k,
        "comma_per_sentence": body.count(",") / max(len(sentences), 1),
        "open_repeat": open_repeat,
    }


# Bands for features that get a score of their own. (low, high) = acceptable.
# Deliberately wide: these flag machine-flat prose, not a house style.
FEATURE_BANDS: dict[str, tuple[float, float, float, str]] = {
    "sentence_sd": (4.0, 40.0, 1.0, "Vary sentence length; a flat rhythm reads as generated."),
    "sentence_mean": (9.0, 30.0, 0.8, "Shift the average sentence length toward the scene's pace."),
    "paragraph_sd": (5.0, 200.0, 0.6, "Break up uniform paragraph blocks."),
    "hapax_ratio": (0.35, 1.01, 0.8, "Widen the vocabulary: repeated lexis is the densest AI signal."),
    "dialogue_share": (0.0, 0.9, 0.4, "Rebalance narration and dialogue for the scene type."),
    "open_repeat": (0.0, 0.12, 0.7, "Vary sentence openers; three identical starts in a row is a tell."),
}

# Absolute floors that no band can excuse.
MIN_WORDS_FOR_SCORE = 300


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(text: str, min_prose_score: float = 7.0) -> dict[str, Any]:
    """Score one chapter. Deterministic, stdlib only.

    Returns a dict with `features`, `violations`, `prose_score`, `pass` and
    `tell_rate_per_1k`. Every violation carries its own `fix` string so a
    revision prompt can quote it verbatim.
    """
    body = _strip_front_matter(text)
    feats = measure(body)
    n_words = int(feats["word_count"])
    result: dict[str, Any] = {
        "features": {k: round(v, 4) for k, v in feats.items()},
        "violations": [],
        "tell_rate_per_1k": 0.0,
        "prose_score": 0.0,
        "pass": False,
        "too_short": n_words < MIN_WORDS_FOR_SCORE,
    }
    if n_words == 0:
        return result

    lower = body.lower()
    k = 1000.0 / n_words
    penalty = 0.0
    tell_hits = 0

    for rule in RULES:
        matches = rule["re"].findall(body) if rule["re"].groups == 0 else \
            [m for m in rule["re"].finditer(body)]
        count = len(matches)
        if count == 0:
            continue
        rate = count * k
        excess = rate - rule["band"]
        example = ""
        m0 = re.search(rule["re"].pattern, body, re.IGNORECASE)
        if m0:
            start = max(0, m0.start() - 40)
            example = ("..." if start else "") + body[start:m0.end() + 40].replace("\n", " ").strip() + "..."
        if excess > 0:
            tell_hits += count
            penalty += excess * rule["weight"]
            result["violations"].append({
                "rule": rule["name"],
                "category": rule["category"],
                "count": count,
                "rate_per_1k": round(rate, 2),
                "band": rule["band"],
                "excess_per_1k": round(excess, 2),
                "example": example[:140],
                "fix": rule["fix"],
            })
        else:
            # Under band: reported, not penalised. Keeps the number explainable.
            result["violations"].append({
                "rule": rule["name"], "category": rule["category"], "count": count,
                "rate_per_1k": round(rate, 2), "band": rule["band"],
                "excess_per_1k": 0.0, "example": "", "fix": rule["fix"],
                "under_band": True,
            })

    for name, (low, high, weight, fix) in FEATURE_BANDS.items():
        value = feats.get(name)
        if value is None:
            continue
        if low <= value <= high:
            continue
        distance = (low - value) if value < low else (value - high)
        scale = max(abs(high), abs(low), 1.0)
        penalty += min(3.0, (distance / scale) * 6.0) * weight
        result["violations"].append({
            "rule": name, "category": "rhythm" if name.endswith("_sd") or name == "sentence_mean"
            else "lexis" if name in ("hapax_ratio", "type_token") else "shape",
            "count": 1, "rate_per_1k": round(value, 3), "band": [low, high],
            "excess_per_1k": round(distance, 3), "example": "", "fix": fix,
        })

    result["violations"].sort(key=lambda v: -v["excess_per_1k"])
    result["tell_rate_per_1k"] = round(tell_hits * k, 2)
    score = 10.0 - penalty
    result["prose_score"] = round(max(0.0, min(10.0, score)), 1)
    result["pass"] = (not result["too_short"]) and result["prose_score"] >= min_prose_score
    return result


def penalise_length(word_count: int, target_words: int) -> float:
    """Length penalty for the composite score: a stub cannot win on style alone.

    No penalty below the scoreability floor: short texts already fail
    `too_short`, and unit-test snippets are not chapters."""
    if target_words <= 0 or word_count < MIN_WORDS_FOR_SCORE:
        return 0.0
    ratio = word_count / target_words
    if ratio >= 1.0:
        return 0.0
    if ratio >= 0.6:
        return round((1.0 - ratio) * 2.0, 2)      # up to -0.8
    return round(2.0 + (0.6 - ratio) * 12.0, 2)    # steep below 60%


# ---------------------------------------------------------------------------
# Voice drift: bands fitted on the manuscript itself
# ---------------------------------------------------------------------------

_DRIFT_FEATURES = ("sentence_mean", "sentence_sd", "paragraph_mean", "dialogue_share",
                   "type_token", "hapax_ratio", "dash_per_1k", "comma_per_sentence")


def bands_from(texts: list[str]) -> dict[str, Any]:
    """Fit per-manuscript bands. Longtail's caution: a fixed absolute gate
    becomes the new cluster, so the reference is the book's own distribution."""
    rows = [measure(_strip_front_matter(t)) for t in texts]
    rows = [r for r in rows if r["word_count"] >= MIN_WORDS_FOR_SCORE]
    if len(rows) < 3:
        return {"n": len(rows), "bands": {}, "note": "need >=3 chapters to fit bands"}
    bands = {}
    for f in _DRIFT_FEATURES:
        vals = [r[f] for r in rows]
        mean = sum(vals) / len(vals)
        sd = _std(vals)
        bands[f] = {"mean": round(mean, 4), "sd": round(sd, 4),
                    "min": round(min(vals), 4), "max": round(max(vals), 4)}
    return {"n": len(rows), "bands": bands}


def drift(text_or_features: Any, fitted: dict[str, Any], z: float = 2.0) -> list[dict[str, Any]]:
    """Return the features where one chapter leaves its own book's band."""
    feats = text_or_features if isinstance(text_or_features, dict) else \
        measure(_strip_front_matter(text_or_features))
    out = []
    for f, stats in (fitted.get("bands") or {}).items():
        sd = stats["sd"]
        if sd <= 1e-9 or f not in feats:
            continue
        score = (feats[f] - stats["mean"]) / sd
        if abs(score) >= z:
            out.append({"feature": f, "value": round(feats[f], 4),
                        "mean": stats["mean"], "sd": sd, "z": round(score, 2),
                        "direction": "above" if score > 0 else "below"})
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def revision_lines(result: dict[str, Any], limit: int = 8) -> list[str]:
    """Violation lines for a revision prompt: what broke, the number, the fix."""
    lines = []
    for v in result["violations"]:
        if v.get("under_band"):
            continue
        band = v["band"]
        band_txt = f"{band[0]}-{band[1]}" if isinstance(band, list) else str(band)
        lines.append(f"- {v['rule']} ({v['category']}): {v['rate_per_1k']}/1k vs band {band_txt}. {v['fix']}")
        if v.get("example"):
            lines.append(f"    e.g. {v['example']}")
        if len(lines) >= limit * 2:
            break
    return lines[:limit * 2]


def report(result: dict[str, Any], label: str = "") -> str:
    top = [v for v in result["violations"] if not v.get("under_band")][:6]
    head = f"{label}: prose {result['prose_score']}/10 " \
           f"({'PASS' if result['pass'] else 'FAIL'}, " \
           f"{int(result['features']['word_count'])} words, " \
           f"tells {result['tell_rate_per_1k']}/1k)"
    if result.get("too_short"):
        head += f" [too short: <{MIN_WORDS_FOR_SCORE} words, not scoreable]"
    lines = [head]
    for v in top:
        lines.append(f"  {v['rule']:22s} {v['rate_per_1k']:>6}/1k  band {v['band']}  {v['fix']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="prose_lab", description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="chapter .md files")
    ap.add_argument("--min", type=float, default=float(os.environ.get("LLM_MIN_PROSE_SCORE", 7.0)))
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--bands", action="store_true", help="fit per-manuscript bands and report drift")
    args = ap.parse_args(argv)

    texts, results = [], []
    for p in args.paths:
        with open(p, encoding="utf-8") as f:
            t = f.read()
        texts.append(t)
        results.append((p, analyze(t, args.min)))

    if args.json:
        print(json.dumps([{"path": p, **r} for p, r in results], indent=2))
    else:
        for p, r in results:
            print(report(r, os.path.basename(p)))
        if args.bands and len(texts) >= 3:
            fitted = bands_from(texts)
            print(f"\nbands fitted on {fitted['n']} chapters")
            for p, r in results:
                d = drift(r["features"], fitted)
                if d:
                    print(f"  {os.path.basename(p)}: " +
                          ", ".join(f"{x['feature']} z={x['z']:+.1f}" for x in d))

    failed = [p for p, r in results if not r["pass"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
