"""Style Engine — quantitative prose feature extraction and profile binding.

Builds on the 4 hardcoded rhetorical strategies (STYLE_PROFILES in draft.py)
with quantitative style extraction, reusable style profiles, and
profile-to-draft binding. Two modes:
- **Extract**: analyze existing prose into a StyleProfile dataclass
- **Bind**: apply a saved profile to a chapter draft

Design:
- Pure-Python extraction (no LLM call, no API cost)
- 10 quantitative dimensions computed from raw text
- Profiles serialized as JSON to project_dir/styles/
- Profile comparison for style drift detection
- Compatible with the existing STYLE_PROFILES system
"""

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Style Profile Dataclass ──────────────────────────────────────────

@dataclass
class StyleProfile:
    """Quantitative prose style fingerprint for a chapter or reference text."""
    name: str = ""
    source_chapter: int = 0
    source_word_count: int = 0

    # Rhythm
    sentence_length_mean: float = 0.0
    sentence_length_std: float = 0.0
    paragraph_length_mean: float = 0.0

    # Dialogue
    dialogue_density: float = 0.0          # ratio of quoted words to total words

    # Vocabulary
    vocabulary_tier: float = 0.0           # ratio of uncommon (>6 char) to total words
    sensory_density: float = 0.0           # sight/sound/touch/smell/taste keywords per 1000 words

    # Pacing
    pacing_action_ratio: float = 0.0       # action verbs / total verbs
    pacing_reflection_ratio: float = 0.0   # cognitive verbs / total verbs
    pacing_description_ratio: float = 0.0  # be/have/exist verbs / total verbs

    # POV distance
    pov_distance: float = 0.0              # 0=omniscient (he thought, she felt), 10=close 3rd (no filter words)

    # Hook density
    hook_density: float = 0.0              # cliffhanger sentences per 1000 words

    # Emotional register (normalized counts per 1000 words)
    emotion_anger: float = 0.0
    emotion_fear: float = 0.0
    emotion_sadness: float = 0.0
    emotion_joy: float = 0.0
    emotion_surprise: float = 0.0
    emotion_trust: float = 0.0


# ── Keyword Dictionaries ─────────────────────────────────────────────

_SENSORY_WORDS = {
    "sight": {"saw", "looked", "gazed", "stared", "watched", "observed", "noticed",
              "glimpsed", "peered", "glanced", "visible", "bright", "dark", "shadow",
              "color", "red", "blue", "green", "yellow", "white", "black", "gray",
              "golden", "silver", "glow", "shimmer", "gleam", "flicker", "sparkle"},
    "sound": {"heard", "listened", "sound", "noise", "voice", "whisper", "shout",
              "scream", "echo", "silence", "quiet", "loud", "bang", "crash", "rustle",
              "footstep", "creak", "buzz", "hum", "roar", "murmur", "cry"},
    "touch": {"felt", "touched", "hard", "soft", "cold", "hot", "warm", "cool",
              "rough", "smooth", "wet", "dry", "sharp", "dull", "heavy", "light",
              "pressure", "grip", "grasp", "stroke", "brush", "tingle", "numb"},
    "smell": {"smelled", "scent", "odor", "fragrance", "stench", "aroma", "perfume",
              "reek", "stink", "whiff"},
    "taste": {"tasted", "sweet", "bitter", "sour", "salty", "savory", "spicy",
              "bland", "rich", "flavor"},
}

_ACTION_VERBS = {"ran", "jumped", "grabbed", "pulled", "pushed", "threw", "struck",
                 "hit", "fell", "rose", "ran", "walked", "moved", "turned", "stood",
                 "sat", "ran", "fled", "chased", "climbed", "leapt", "dove", "spun",
                 "swung", "kicked", "punched", "slashed", "cut", "broke", "shattered",
                 "burst", "exploded", "sprinted", "dashed", "darted", "lunged"}

_COGNITIVE_VERBS = {"thought", "wondered", "realized", "knew", "understood", "believed",
                    "remembered", "forgot", "imagined", "considered", "decided", "chose",
                    "hoped", "feared", "worried", "suspected", "doubted", "trusted",
                    "regretted", "anticipated", "expected", "meant", "intended",
                    "questioned", "puzzled", "reflected", "contemplated", "meditated"}

_BE_HAVE_VERBS = {"was", "were", "is", "are", "been", "being", "am", "had", "has",
                  "have", "seemed", "appeared", "looked", "became", "remained",
                  "existed", "lived", "stayed", "kept", "held"}

_EMOTION_KEYWORDS = {
    "anger": {"angry", "furious", "rage", "fury", "enraged", "irate", "wrath",
              "livid", "outraged", "seething", "mad", "cross", "irritated",
              "frustrated", "annoyed", "resentful", "bitter"},
    "fear": {"afraid", "scared", "frightened", "terrified", "terrified",
             "panicked", "anxious", "nervous", "dread", "horror", "terror",
             "alarmed", "petrified", "shaken", "worried", "uneasy"},
    "sadness": {"sad", "sorrow", "grief", "mournful", "miserable", "depressed",
                "melancholy", "despair", "hopeless", "forlorn", "wretched",
                "heartbroken", "wept", "cried", "tears", "sobbed", "sighed"},
    "joy": {"happy", "joy", "delight", "pleased", "glad", "elated", "ecstatic",
            "thrilled", "cheerful", "content", "satisfied", "grinned", "smiled",
            "laughed", "beamed", "radiant", "excited", "wonderful", "bliss"},
    "surprise": {"surprised", "shocked", "stunned", "astonished", "amazed",
                 "startled", "taken aback", "caught off guard", "unexpected",
                 "bewildered", "dumbfounded", "jaw dropped"},
    "trust": {"trusted", "believed", "confident", "certain", "sure", "faith",
              "loyalty", "devoted", "reliable", "dependable", "honest",
              "sincere", "genuine", "frank", "open"},
}

_CLIFFHANGER_PATTERNS = [
    r'\b(then|suddenly|just then|at that moment)\b.{0,30}[.!?]',
    r'(?:didn\'t|couldn\'t|wouldn\'t)\s+\w+\s+\w+[.!?]',
    r'(?:question|mystery|secret|unknown)\s+\w+(?:\s+\w+){0,5}[.!?]',
    r'(?:only|just|barely)\s+\w+\s+(?:before|when|as)[.!?]',
    r'(?:but|however|yet)\s+\w+(?:\s+\w+){2,8}[.!?]$',
]


# ── Helper utils ──────────────────────────────────────────────────────

def _tokenize_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Handle common abbreviations before splitting
    text = re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof|St)\.', r'\1<DOT>', text)
    sentences = re.split(r'[.!?]+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 3]


def _word_count(text: str) -> int:
    return len(re.findall(r'\b\w+\b', text.lower()))


# ── Extraction ────────────────────────────────────────────────────────

def extract_style(chapter_text: str, chapter_num: int = 0, name: str = "") -> StyleProfile:
    """Extract a StyleProfile from raw chapter text.

    Pure Python — no LLM call, no API cost. Runs in ~10ms for a 4000-word chapter.

    Args:
        chapter_text: Full chapter text to analyze.
        chapter_num: Chapter number for the profile source tag.
        name: Optional human-readable name. Auto-generated if empty.

    Returns:
        StyleProfile with all 10 quantitative dimensions populated.
    """
    text = chapter_text.strip()
    words = re.findall(r'\b\w+\b', text.lower())
    total_words = len(words)
    sentences = _tokenize_sentences(text)
    total_sentences = max(len(sentences), 1)

    if not name:
        name = f"chapter-{chapter_num:03d}"

    profile = StyleProfile(
        name=name,
        source_chapter=chapter_num,
        source_word_count=total_words,
    )

    # ── Rhythm ────────────────────────────────────────────────────
    sent_lengths = [len(re.findall(r'\b\w+\b', s.lower())) for s in sentences]
    sent_lengths = [l for l in sent_lengths if l > 0]
    if sent_lengths:
        profile.sentence_length_mean = sum(sent_lengths) / len(sent_lengths)
        if len(sent_lengths) > 1:
            variance = sum((l - profile.sentence_length_mean) ** 2 for l in sent_lengths) / (len(sent_lengths) - 1)
            profile.sentence_length_std = math.sqrt(variance)

    # Paragraph length
    paragraphs = [p for p in re.split(r'\n\s*\n', text) if p.strip()]
    para_lens = [_word_count(p) for p in paragraphs]
    if para_lens:
        profile.paragraph_length_mean = sum(para_lens) / len(para_lens)

    # ── Dialogue density ──────────────────────────────────────────
    dialog_words = len(re.findall(r'\b\w+\b', " ".join(
        re.findall(r'["\u201c][^"\u201d]*["\u201d]', text)
    ).lower()))
    profile.dialogue_density = dialog_words / max(total_words, 1)

    # ── Vocabulary tier ───────────────────────────────────────────
    uncommon = sum(1 for w in words if len(w) > 6)
    profile.vocabulary_tier = uncommon / max(total_words, 1)

    # ── Sensory density ───────────────────────────────────────────
    sensory_total = 0
    for sense, kw_set in _SENSORY_WORDS.items():
        for kw in kw_set:
            sensory_total += sum(1 for w in words if w == kw)
    profile.sensory_density = sensory_total / max(total_words, 1) * 1000

    # ── Pacing profile ────────────────────────────────────────────
    action_count = sum(1 for w in words if w in _ACTION_VERBS)
    cognitive_count = sum(1 for w in words if w in _COGNITIVE_VERBS)
    be_have_count = sum(1 for w in words if w in _BE_HAVE_VERBS)
    all_verb_count = action_count + cognitive_count + be_have_count
    if all_verb_count > 0:
        profile.pacing_action_ratio = action_count / all_verb_count
        profile.pacing_reflection_ratio = cognitive_count / all_verb_count
        profile.pacing_description_ratio = be_have_count / all_verb_count

    # ── POV distance ──────────────────────────────────────────────
    # Filter words = "he thought", "she felt", "he knew" — omniscient signals
    filter_patterns = [
        r'\b(?:he|she|they|it)\s+(?:thought|felt|knew|realized|wondered|decided|believed|suspected|noticed|imagined|remembered)\b',
        r'\b(?:was|were|seemed|appeared)\s+(?:to\s+)?(?:be|feel|look|seem|sound)\b',
    ]
    filter_count = 0
    text_lower = text.lower()
    for pat in filter_patterns:
        filter_count += len(re.findall(pat, text_lower))
    # Normalize: 0 = many filter words (omniscient), 10 = none (close 3rd)
    filter_per_k = filter_count / max(total_words, 1) * 1000
    profile.pov_distance = max(0.0, min(10.0, 10.0 - filter_per_k * 2))

    # ── Hook density ──────────────────────────────────────────────
    hook_count = 0
    for pat in _CLIFFHANGER_PATTERNS:
        hook_count += len(re.findall(pat, text_lower))
    profile.hook_density = hook_count / max(total_words, 1) * 1000

    # ── Emotional register ────────────────────────────────────────
    for emotion_label in _EMOTION_KEYWORDS:
        kw_set = _EMOTION_KEYWORDS[emotion_label]
        count = sum(1 for w in words if w in kw_set)
        setattr(profile, f"emotion_{emotion_label}", count / max(total_words, 1) * 1000)

    return profile


# ── Format / Bind ─────────────────────────────────────────────────────

def format_style_for_prompt(profile: StyleProfile) -> str:
    """Render a StyleProfile as a compact prose direction block.

    Used to inject style guidance into the CHAPTER_DRAFT_TEMPLATE,
    replacing or supplementing the current rhetorical strategy string.

    Example output:
        Style direction: Sentence rhythm: 18w avg, high variance (std 12).
        22% dialogue. Lean on touch and sound. Close 3rd POV (8/10).
        Emotional register: 40% tension, 30% wonder. Hook density: 1.2/1k words.
    """
    parts = ["Style direction (profile: {})".format(profile.name)]

    # Rhythm
    if profile.sentence_length_mean > 0:
        var_label = "high variance" if profile.sentence_length_std > 10 else (
            "moderate variance" if profile.sentence_length_std > 5 else "uniform")
        parts.append(
            f"Sentence rhythm: {profile.sentence_length_mean:.0f}w avg, {var_label} (std {profile.sentence_length_std:.0f})."
        )

    # Dialogue
    parts.append(f"{profile.dialogue_density:.0%} dialogue.")

    # Pacing
    parts.append(
        f"Pacing: action={profile.pacing_action_ratio:.0%}, "
        f"reflection={profile.pacing_reflection_ratio:.0%}, "
        f"description={profile.pacing_description_ratio:.0%}."
    )

    # Sensory direction
    if profile.sensory_density > 5:
        parts.append(f"High sensory density ({profile.sensory_density:.0f}/1k words).")

    # POV
    pov_label = "close 3rd" if profile.pov_distance > 7 else (
        "mid-distance" if profile.pov_distance > 4 else "omniscient-leaning")
    parts.append(f"POV: {pov_label} ({profile.pov_distance:.0f}/10).")

    # Hooks
    if profile.hook_density > 0.5:
        parts.append(f"Hook density: {profile.hook_density:.1f}/1k words.")

    # Emotional register
    emotions = [
        ("anger", profile.emotion_anger),
        ("fear", profile.emotion_fear),
        ("sadness", profile.emotion_sadness),
        ("joy", profile.emotion_joy),
        ("surprise", profile.emotion_surprise),
        ("trust", profile.emotion_trust),
    ]
    top_emotions = sorted(emotions, key=lambda x: -x[1])[:3]
    if top_emotions[0][1] > 0:
        emotion_str = ", ".join(f"{label}={val:.0f}/1k" for label, val in top_emotions if val > 0)
        parts.append(f"Emotional register: {emotion_str}.")

    return "\n".join(parts)


# ── Persistence ───────────────────────────────────────────────────────

def save_style_profile(profile: StyleProfile, project_dir: str) -> str:
    """Save a StyleProfile as JSON to project_dir/styles/{name}.json.

    Returns the file path.
    """
    styles_dir = os.path.join(project_dir, "styles")
    os.makedirs(styles_dir, exist_ok=True)

    path = os.path.join(styles_dir, f"{profile.name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, indent=2)

    return path


def load_style_profile(name: str, project_dir: str) -> Optional[StyleProfile]:
    """Load a named StyleProfile from project_dir/styles/{name}.json.

    Returns None if the file doesn't exist or is malformed.
    """
    path = os.path.join(project_dir, "styles", f"{name}.json")
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return StyleProfile(**{k: v for k, v in data.items() if k in StyleProfile.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError, OSError):
        return None


def list_style_profiles(project_dir: str) -> list[str]:
    """List all saved style profile names in the project."""
    styles_dir = os.path.join(project_dir, "styles")
    if not os.path.isdir(styles_dir):
        return []

    profiles = []
    for fn in os.listdir(styles_dir):
        if fn.endswith(".json"):
            profiles.append(fn.replace(".json", ""))
    return sorted(profiles)


# ── Comparison ────────────────────────────────────────────────────────

def compare_profiles(a: StyleProfile, b: StyleProfile) -> dict:
    """Compute dimension-by-dimension delta between two profiles.

    Returns a dict with the same shape as StyleProfile plus a 'summary'
    string describing the most significant shifts.
    """
    delta = {}
    shifts = []

    for field_name in StyleProfile.__dataclass_fields__:
        if field_name in ("name", "source_chapter", "source_word_count"):
            continue
        a_val = getattr(a, field_name)
        b_val = getattr(b, field_name)
        diff = b_val - a_val
        delta[field_name] = round(diff, 4)

        # Flag significant shifts (> 20% of max possible)
        abs_max = max(abs(a_val), abs(b_val), 0.001)
        if abs_max > 0.001 and abs(diff) / abs_max > 0.2:
            direction = "↑" if diff > 0 else "↓"
            label = field_name.replace("_", " ")
            shifts.append(f"{label}: {a_val:.2f} → {b_val:.2f} {direction}")

    summary = "; ".join(shifts[:5]) if shifts else "No significant style shifts detected"

    delta["summary"] = summary
    return delta
