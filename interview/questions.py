"""Question bank for StoryForge interactive interview.
Six dimensions, depth-tagged, with follow-up triggers."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Question:
    id: str
    dimension: str
    text: str
    depths: list[str] = field(default_factory=lambda: ["standard", "comprehensive"])
    follow_up_keywords: list[str] = field(default_factory=list)
    required_elements: list[str] = field(default_factory=list)
    genre_specific: Optional[str] = None


CONCEPT = "concept_premise"
WORLD = "world_setting"
CHARACTERS = "characters"
PLOT = "plot_structure"
THEME = "theme_voice"
MARKET = "market_comparisons"

DIMENSION_ORDER = [CONCEPT, WORLD, CHARACTERS, PLOT, THEME, MARKET]

DIMENSION_LABELS = {
    CONCEPT: "Concept & Premise",
    WORLD: "World & Setting",
    CHARACTERS: "Characters",
    PLOT: "Plot & Structure",
    THEME: "Theme & Voice",
    MARKET: "Market & Comparisons",
}


CONCEPT_PREMISE_Q = [
    Question("cp-01", "concept_premise", "What is your story about? Core premise in 2-3 sentences.",
           depths=["quick", "standard", "comprehensive"], follow_up_keywords=[]),
    Question("cp-02", "concept_premise", "What genre(s) does this story belong to?",
           depths=["quick", "standard", "comprehensive"], follow_up_keywords=[]),
    Question("cp-03", "concept_premise", "What makes this story different? Unique angle or hook?",
           depths=["quick", "standard", "comprehensive"], follow_up_keywords=[]),
    Question("cp-04", "concept_premise", "What central question or conflict drives the narrative?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("cp-05", "concept_premise", "Who is your target audience?",
           depths=["standard", "comprehensive"], follow_up_keywords=["everyone", "anyone", "people who"]),
    Question("cp-06", "concept_premise", "What is the tone?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("cp-07", "concept_premise", "Estimated length?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("cp-08", "concept_premise", "Narrative tense?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("cp-09", "concept_premise", "Point of view?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("cp-10", "concept_premise", "What is the inciting incident?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("cp-11", "concept_premise", "Do you know the ending?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("cp-12", "concept_premise", "What central theme?",
           depths=["comprehensive"], follow_up_keywords=["not sure"]),
    Question("cp-13", "concept_premise", "Real-world influences?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("cp-14", "concept_premise", "Mood after opening?",
           depths=["comprehensive"], follow_up_keywords=["good", "interesting"]),
    Question("cp-15", "concept_premise", "Standalone or series?",
           depths=["comprehensive"], follow_up_keywords=[]),
]

WORLD_SETTING_Q = [
    Question("ws-01", "world_setting", "Where and when? Describe primary setting.",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("ws-02", "world_setting", "Key physical locations?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("ws-03", "world_setting", "Tech or magic system?",
           depths=["standard", "comprehensive"], follow_up_keywords=["magic", "tech", "system"]),
    Question("ws-04", "world_setting", "Major cultures or factions?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("ws-05", "world_setting", "Political landscape?",
           depths=["comprehensive"], follow_up_keywords=["not important", "good vs evil"]),
    Question("ws-06", "world_setting", "Economic reality?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-07", "world_setting", "Key historical events?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-08", "world_setting", "Unique natural laws?",
           depths=["comprehensive"], follow_up_keywords=["like real world", "normal"]),
    Question("ws-09", "world_setting", "Daily life for normal person?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-10", "world_setting", "Important symbols or myths?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-11", "world_setting", "How does setting evolve?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-12", "world_setting", "Taboos or forbidden things?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-13", "world_setting", "Sensory snapshot?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ws-14", "world_setting", "Non-human intelligences?",
           depths=["comprehensive"], follow_up_keywords=[]),
]

CHARACTERS_Q = [
    Question("ch-01", "characters", "Who is the protagonist?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("ch-02", "characters", "What do they want?",
           depths=["standard", "comprehensive"], follow_up_keywords=["not sure", "survive", "get by"]),
    Question("ch-03", "characters", "Primary obstacle?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("ch-04", "characters", "Fatal flaw?",
           depths=["standard", "comprehensive"], follow_up_keywords=["none", "too good", "perfect"]),
    Question("ch-05", "characters", "Who is the antagonist?",
           depths=["standard", "comprehensive"], follow_up_keywords=["evil", "bad", "villain"]),
    Question("ch-06", "characters", "Supporting characters?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("ch-07", "characters", "How do they change?",
           depths=["comprehensive"], follow_up_keywords=["not much", "same"]),
    Question("ch-08", "characters", "Backstory?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ch-09", "characters", "Internal conflict?",
           depths=["comprehensive"], follow_up_keywords=["nothing", "fine"]),
    Question("ch-10", "characters", "Who do they love?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ch-11", "characters", "Secret they keep?",
           depths=["comprehensive"], follow_up_keywords=["no secret"]),
    Question("ch-12", "characters", "Antagonist perspective?",
           depths=["comprehensive"], follow_up_keywords=["evil", "bad guy", "just wrong"]),
    Question("ch-13", "characters", "Moral grey areas?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("ch-14", "characters", "Secondary character conflicts?",
           depths=["comprehensive"], follow_up_keywords=[]),
]

PLOT_STRUCTURE_Q = [
    Question("pl-01", "plot_structure", "Overall story structure?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("pl-02", "plot_structure", "Major plot arc in beats?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("pl-03", "plot_structure", "Subplots?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("pl-04", "plot_structure", "First act transition?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-05", "plot_structure", "Midpoint twist?",
           depths=["comprehensive"], follow_up_keywords=["not sure"]),
    Question("pl-06", "plot_structure", "Darkest moment?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-07", "plot_structure", "Climax resolution?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-08", "plot_structure", "Pacing?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-09", "plot_structure", "Flashbacks or time jumps?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-10", "plot_structure", "Central mystery?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-11", "plot_structure", "False victory?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-12", "plot_structure", "Subplot intersections?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-13", "plot_structure", "Exciting scenes?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("pl-14", "plot_structure", "Dreaded scenes?",
           depths=["comprehensive"], follow_up_keywords=[]),
]

THEME_VOICE_Q = [
    Question("th-01", "theme_voice", "Story beneath the plot?",
           depths=["standard", "comprehensive"], follow_up_keywords=["not sure"]),
    Question("th-02", "theme_voice", "Emotional journey?",
           depths=["standard", "comprehensive"], follow_up_keywords=["entertained", "enjoy", "fun"]),
    Question("th-03", "theme_voice", "Narrative voice?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("th-04", "theme_voice", "Theme per character?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("th-05", "theme_voice", "Symbols or motifs?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("th-06", "theme_voice", "Question for reader?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("th-07", "theme_voice", "Influential authors?",
           depths=["comprehensive"], follow_up_keywords=["none", "no one"]),
    Question("th-08", "theme_voice", "Setting and theme?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("th-09", "theme_voice", "Belief questioned?",
           depths=["comprehensive"], follow_up_keywords=[]),
]

MARKET_COMPARISONS_Q = [
    Question("mk-01", "market_comparisons", "Comparable books?",
           depths=["standard", "comprehensive"], follow_up_keywords=["none", "nothing like it", "unique"]),
    Question("mk-02", "market_comparisons", "Publishing goal?",
           depths=["standard", "comprehensive"], follow_up_keywords=[]),
    Question("mk-03", "market_comparisons", "Ideal reader?",
           depths=["comprehensive"], follow_up_keywords=["everyone", "anyone"]),
    Question("mk-04", "market_comparisons", "Bookstore category?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("mk-05", "market_comparisons", "What works handled this theme?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("mk-06", "market_comparisons", "Dream blurb?",
           depths=["comprehensive"], follow_up_keywords=[]),
    Question("mk-07", "market_comparisons", "Timeline?",
           depths=["comprehensive"], follow_up_keywords=[]),
]


QUESTION_BANKS = {
    "concept_premise": CONCEPT_PREMISE_Q,
    "world_setting": WORLD_SETTING_Q,
    "characters": CHARACTERS_Q,
    "plot_structure": PLOT_STRUCTURE_Q,
    "theme_voice": THEME_VOICE_Q,
    "market_comparisons": MARKET_COMPARISONS_Q,
}


def get_questions(depth='standard', genre=None):
    result = []
    for dim in DIMENSION_ORDER:
        for q in QUESTION_BANKS.get(dim, []):
            if depth in q.depths:
                if q.genre_specific and q.genre_specific != genre:
                    continue
                result.append(q)
    return result


def get_dimension_counts(depth='standard', genre=None):
    counts = {}
    for q in get_questions(depth, genre):
        counts[q.dimension] = counts.get(q.dimension, 0) + 1
    return counts
