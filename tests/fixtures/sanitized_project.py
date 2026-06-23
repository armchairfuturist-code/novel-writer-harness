"""Sanitized, production-scale fixture data for StoryForge.

These fixtures represent a complete, realistic long-form novel project state
mid-pipeline. All names, settings, and content are sanitized — no copyrighted
material, no real-person PII. Built to mirror what `~/storyforge-projects/`
would look like after running the full pipeline on a 24-chapter fantasy novel.
"""

import json
import os
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent

# ──────────────────────────────────────────────────────────────
# Sanitized spec (output of seed phase)
# ──────────────────────────────────────────────────────────────

SANITIZED_SPEC = {
    "title": "The Hollow Crown",
    "genre": "fantasy",
    "premise": (
        "A disgraced cartographer's apprentice discovers that the kingdom's ancient "
        "wardstones are failing one by one, and only by retracing her master's "
        "forbidden survey routes can she prevent the old darkness from returning."
    ),
    "tone": "atmospheric, elegiac, with moments of stark horror",
    "tense": "past",
    "pov": "third-person limited, rotating",
    "target_length": 95000,
    "target_chapters": 24,
    "themes": ["memory and erasure", "cartography as power", "duty vs grief"],
    "unique_angle": (
        "Fantasy told through the lens of survey work — the magic is in the "
        "mapping, not the swordsmanship."
    ),
    "initial_direction": "Open with the protagonist's mentor's funeral.",
    "genre_template": "fantasy",
    "genre_beats": [
        {"phase": "ordinary_world", "chapter_range": [1, 3]},
        {"phase": "crossing_threshold", "chapter_range": [4, 8]},
        {"phase": "trials_and_allies", "chapter_range": [9, 14]},
        {"phase": "darkest_hour", "chapter_range": [15, 18]},
        {"phase": "final_quest", "chapter_range": [19, 24]},
    ],
    "tracking_items": [
        "magic_system_rules",
        "world_lore_reveals",
        "artifact_tracking",
        "prophecy_elements",
    ],
}


# ──────────────────────────────────────────────────────────────
# Sanitized world bible
# ──────────────────────────────────────────────────────────────

SANITIZED_WORLD = {
    "world_name": "The Sundered Marches",
    "geography": {
        "regions": [
            {"name": "The Lowland Reaches", "climate": "temperate, riverine"},
            {"name": "The Ash Vale", "climate": "cold, volcanic"},
            {"name": "The Glassreach", "climate": "arid plateau"},
        ],
        "notable_features": [
            "The River Vael — silver-tinted, runs north to the salt sea",
            "The Warding Stones — 13 standing stones ringing the kingdom",
        ],
    },
    "history": {
        "eras": [
            {"name": "The First Survey", "year_range": [-800, -200]},
            {"name": "The Hollow Wars", "year_range": [-200, 50]},
            {"name": "The Long Peace", "year_range": [50, 750]},
            {"name": "The Present", "year_range": [750, 810]},
        ],
    },
    "factions": [
        {"name": "The Survey Cartel", "alignment": "neutral mercantile"},
        {"name": "The Keepers of the Stones", "alignment": "lawful warden"},
        {"name": "The Hollow Court", "alignment": "hidden antagonist"},
    ],
    "power_system": {
        "name": "Ward-Mapping",
        "rules": [
            "A ward-stone holds against corruption as long as its map remains true.",
            "Erasing a ward from a map severs its protection.",
            "Only a Master Surveyor can redraw a ward-stone's line.",
        ],
    },
    "central_conflict": "The kingdom's ward-stones are failing; the only known surveyors are dead or disgraced.",
}


# ──────────────────────────────────────────────────────────────
# Sanitized character profiles (24 chapters worth — 6 main + 2 secondary)
# ──────────────────────────────────────────────────────────────

SANITIZED_CHARACTERS = {
    "characters": [
        {
            "name": "Aelith Vance",
            "role": "protagonist",
            "age": 24,
            "traits": ["perceptive", "grieving", "stubborn"],
            "arc": "Disgraced apprentice → reluctant Master Surveyor who redraws the kingdom.",
            "background": "Apprentice to Master Surveyor Halden; blamed for his death.",
            "motivation": "Restore her master's reputation by finishing his final survey.",
        },
        {
            "name": "Bren Coldwell",
            "role": "ally",
            "age": 38,
            "traits": ["laconic", "physically imposing", "secretly kind"],
            "arc": "Road-weary mercenary → sworn companion.",
            "background": "Former soldier, now a road-warden for hire.",
            "motivation": "Pay off a debt to Halden's memory.",
        },
        {
            "name": "Sister Ondre",
            "role": "mentor / keeper",
            "age": 61,
            "traits": ["patient", "cryptic", "burdened by secrets"],
            "arc": "Keeper who knows the truth about the failing stones.",
            "background": "Senior Keeper of the Stones; knew Halden in his youth.",
            "motivation": "Find a worthy successor before the stones fall silent.",
        },
        {
            "name": "The Cartographer-General",
            "role": "antagonist",
            "age": 58,
            "traits": ["charming", "ruthlessly pragmatic", "obsessed with control"],
            "arc": "Public servant → revealed as agent of the Hollow Court.",
            "background": "Head of the Survey Cartel; orchestrated Halden's disgrace.",
            "motivation": "Centralize all map-making under one hand.",
        },
        {
            "name": "Mira Vance",
            "role": "secondary",
            "age": 19,
            "traits": ["anxious", "loving", "overwhelmed"],
            "arc": "Aelith's younger sister who stays home and tends the workshop.",
            "background": "Keeps Aelith's workshop running in her absence.",
            "motivation": "Keep the family name from total ruin.",
        },
        {
            "name": "Old Tomas",
            "role": "mentor figure / information broker",
            "age": 74,
            "traits": ["mercurial", "mischievous", "sharp as broken glass"],
            "arc": "Grizzled ink-maker who knows every map in the archives.",
            "background": "Was Halden's ink-maker for forty years.",
            "motivation": "Pass on his knowledge to someone who'll use it.",
        },
    ],
    "relationship_map": [
        {"from": "Aelith Vance", "to": "Bren Coldwell", "type": "allies, growing trust"},
        {"from": "Aelith Vance", "to": "Sister Ondre", "type": "mentor / reluctant pupil"},
        {"from": "Aelith Vance", "to": "The Cartographer-General", "type": "nemesis"},
        {"from": "Aelith Vance", "to": "Mira Vance", "type": "family, protective"},
        {"from": "Aelith Vance", "to": "Old Tomas", "type": "mentor's friend"},
    ],
}


# ──────────────────────────────────────────────────────────────
# Sanitized outline (24 chapters across 5 acts)
# ──────────────────────────────────────────────────────────────

def _make_outline():
    acts = [
        {
            "name": "Act I — The Funeral and the Failed Stone",
            "chapters": [
                {
                    "chapter": 1,
                    "title": "The Surveyor's Wake",
                    "pov": "Aelith Vance",
                    "summary": "Aelith attends Halden's funeral; Mira pressures her to give up surveying.",
                    "key_events": [
                        "Halden's body is brought down from the Ash Vale",
                        "Aelith learns the funeral is a quiet disgrace",
                    ],
                    "emotional_arc": "grief → resolve",
                    "foreshadowing": "the broken ward-stone in the chapel",
                    "character_arc_beat": "Aelith refuses to abandon the survey.",
                },
                {
                    "chapter": 2,
                    "title": "The Cartographer-General's Summons",
                    "pov": "Aelith Vance",
                    "summary": "The Cartographer-General offers Aelith a desk post; she refuses.",
                    "key_events": ["Aelith is offered a quiet clerkship", "She is publicly rebuked"],
                    "emotional_arc": "anger → stubbornness",
                    "foreshadowing": "the map in the General's office is wrong",
                    "character_arc_beat": "Aelith commits to the road.",
                },
                {
                    "chapter": 3,
                    "title": "An Ink-Maker's Warning",
                    "pov": "Old Tomas",
                    "summary": "Old Tomas warns Aelith that Halden was silenced, not lost.",
                    "key_events": [
                        "Tomas shows Aelith a half-finished ward-map",
                        "He gives her Halden's compass",
                    ],
                    "emotional_arc": "unease → inheritance",
                    "foreshadowing": "the compass needle twitches toward the Vale",
                    "character_arc_beat": "Aelith receives the calling to finish the survey.",
                },
            ],
        },
        {
            "name": "Act II — Crossing the Marches",
            "chapters": [
                {
                    "chapter": 4,
                    "title": "The Road North",
                    "pov": "Aelith Vance",
                    "summary": "Aelith and Bren leave the city; the first ward-stone is silent.",
                    "key_events": [
                        "Aelith and Bren depart at dawn",
                        "They find the first ward-stone cracked and dark",
                    ],
                    "emotional_arc": "determination → dread",
                    "foreshadowing": "the broken stone whispers",
                    "character_arc_beat": "Aelith confirms something is very wrong.",
                },
                {
                    "chapter": 5,
                    "title": "The Hollow's Edge",
                    "pov": "Bren Coldwell",
                    "summary": "Bren's POV of a night ambush by Hollow Court agents.",
                    "key_events": [
                        "Three riders waylay them",
                        "Bren is wounded; Aelith's compass guides them out",
                    ],
                    "emotional_arc": "competence → fear",
                    "foreshadowing": "the attackers' maps are blank",
                    "character_arc_beat": "Bren accepts the danger is real.",
                },
                {
                    "chapter": 6,
                    "title": "The Glassreach",
                    "pov": "Aelith Vance",
                    "summary": "The pair reach a survey outpost; the surveyor there has vanished.",
                    "key_events": [
                        "The outpost is intact but empty",
                        "Aelith finds Halden's mark carved into a table",
                    ],
                    "emotional_arc": "searching → mourning again",
                    "foreshadowing": "the marks point east, not west",
                    "character_arc_beat": "Aelith realizes the survey was a ruse.",
                },
                {
                    "chapter": 7,
                    "title": "The Sister's Letter",
                    "pov": "Mira Vance",
                    "summary": "Mira at home; she finds a letter from Sister Ondre.",
                    "key_events": [
                        "Mira receives Ondre's letter",
                        "The Cartographer-General's men search the workshop",
                    ],
                    "emotional_arc": "fear → determination",
                    "foreshadowing": "Mira hides Halden's true maps",
                    "character_arc_beat": "Mira chooses to help, in her own way.",
                },
                {
                    "chapter": 8,
                    "title": "The Crossing",
                    "pov": "Aelith Vance",
                    "summary": "Aelith and Bren cross the river into the Ash Vale.",
                    "key_events": [
                        "The river is silver-thick and slow",
                        "Aelith has a vision of Halden in the water",
                    ],
                    "emotional_arc": "rite of passage → grief transmuted",
                    "foreshadowing": "the river's silver is a map in itself",
                    "character_arc_beat": "Aelith accepts the burden of Master Surveyor.",
                },
            ],
        },
        {
            "name": "Act III — Trials and Allies",
            "chapters": [
                {
                    "chapter": 9,
                    "title": "The Ash Vale",
                    "pov": "Aelith Vance",
                    "summary": "They climb into the Vale; find a warden-camp abandoned.",
                    "key_events": [
                        "Climbing the ash slopes",
                        "The camp is scorched, not abandoned",
                    ],
                    "emotional_arc": "horror → cold resolve",
                    "foreshadowing": "the stones here have been deliberately broken",
                    "character_arc_beat": "Aelith understands the threat is organized.",
                },
                {
                    "chapter": 10,
                    "title": "Bren's Confession",
                    "pov": "Bren Coldwell",
                    "summary": "Bren reveals he was once in the Hollow Court's employ.",
                    "key_events": [
                        "Bren admits his past",
                        "He swears to Aelith he left before the worst",
                    ],
                    "emotional_arc": "shame → honesty",
                    "foreshadowing": "Bren knows the layout of the Hollow Court",
                    "character_arc_beat": "The trust between the two deepens.",
                },
                {
                    "chapter": 11,
                    "title": "The Warden's Tale",
                    "pov": "Sister Ondre",
                    "summary": "Interlude: Sister Ondre in the Keepers' chapter house.",
                    "key_events": [
                        "Ondre is summoned by the Chapter",
                        "She refuses to name Aelith",
                    ],
                    "emotional_arc": "duty → defiance",
                    "foreshadowing": "The Chapter is no longer unified",
                    "character_arc_beat": "Ondre commits to defying the order.",
                },
                {
                    "chapter": 12,
                    "title": "The Twelfth Stone",
                    "pov": "Aelith Vance",
                    "summary": "Aelith reaches the twelfth ward-stone; it's still intact but silent.",
                    "key_events": [
                        "The stone stands in a ring of ash",
                        "Aelith redraws its line — the stone flares",
                    ],
                    "emotional_arc": "despair → triumph",
                    "foreshadowing": "the stone's flare is seen across the kingdom",
                    "character_arc_beat": "Aelith redraws her first ward.",
                },
                {
                    "chapter": 13,
                    "title": "The Road Back",
                    "pov": "Aelith Vance",
                    "summary": "Aelith and Bren return to the city with the redrawn map.",
                    "key_events": [
                        "They reach the city at nightfall",
                        "The Cartographer-General's men wait at the gate",
                    ],
                    "emotional_arc": "hope → confrontation",
                    "foreshadowing": "the General's seal is on the wanted poster",
                    "character_arc_beat": "Aelith refuses to hide.",
                },
                {
                    "chapter": 14,
                    "title": "The General's Trap",
                    "pov": "The Cartographer-General",
                    "summary": "The General's POV; he springs the trap at the workshop.",
                    "key_events": [
                        "The General confronts Mira",
                        "He seizes Halden's true maps",
                    ],
                    "emotional_arc": "triumph → barely-contained fury",
                    "foreshadowing": "the maps are incomplete without the compass",
                    "character_arc_beat": "The General's obsession deepens.",
                },
            ],
        },
        {
            "name": "Act IV — The Darkest Hour",
            "chapters": [
                {
                    "chapter": 15,
                    "title": "The Workshop Burns",
                    "pov": "Mira Vance",
                    "summary": "Mira's POV as the workshop burns; she escapes with the compass.",
                    "key_events": [
                        "The workshop is set ablaze",
                        "Mira flees with Halden's compass and Ondre's letter",
                    ],
                    "emotional_arc": "terror → clarity",
                    "foreshadowing": "the compass points to Aelith",
                    "character_arc_beat": "Mira becomes an active agent.",
                },
                {
                    "chapter": 16,
                    "title": "The Regrouping",
                    "pov": "Aelith Vance",
                    "summary": "Aelith, Bren, Mira, and Ondre meet at a hidden wayhouse.",
                    "key_events": [
                        "The four reunite",
                        "Ondre reveals the truth about the ward-stones",
                    ],
                    "emotional_arc": "grief → strategic resolve",
                    "foreshadowing": "there are only three stones left",
                    "character_arc_beat": "The party is now formed.",
                },
                {
                    "chapter": 17,
                    "title": "The Hollow Court's Offer",
                    "pov": "Aelith Vance",
                    "summary": "Aelith is captured; the Hollow Court offers her mastery in exchange.",
                    "key_events": [
                        "Aelith is taken by the Court",
                        "They offer her everything she has lost",
                    ],
                    "emotional_arc": "temptation → refusal",
                    "foreshadowing": "the offer is sincere, not a trap",
                    "character_arc_beat": "Aelith refuses and escapes.",
                },
                {
                    "chapter": 18,
                    "title": "The Fall of the Thirteenth Stone",
                    "pov": "Aelith Vance",
                    "summary": "The last great stone falls in a public square; darkness pours out.",
                    "key_events": [
                        "The thirteenth stone cracks at dusk",
                        "Citizens flee; Aelith is the only one who can respond",
                    ],
                    "emotional_arc": "catastrophe → acceptance of burden",
                    "foreshadowing": "the darkness is not mindless",
                    "character_arc_beat": "Aelith accepts the role of Master Surveyor fully.",
                },
            ],
        },
        {
            "name": "Act V — The Final Quest",
            "chapters": [
                {
                    "chapter": 19,
                    "title": "The First Redrawing",
                    "pov": "Aelith Vance",
                    "summary": "Aelith redraws the thirteenth stone; the darkness retreats one step.",
                    "key_events": [
                        "Aelith performs the redrawing in the open",
                        "The citizens watch in silence",
                    ],
                    "emotional_arc": "exhaustion → communion",
                    "foreshadowing": "each redrawing costs her something",
                    "character_arc_beat": "Aelith takes on the burden of all thirteen.",
                },
                {
                    "chapter": 20,
                    "title": "The Sister's Stand",
                    "pov": "Sister Ondre",
                    "summary": "Ondre leads the Keepers in defense of the chapter house.",
                    "key_events": [
                        "The Keepers are attacked",
                        "Ondre holds the line",
                    ],
                    "emotional_arc": "duty → sacrifice",
                    "foreshadowing": "Ondre is wounded, not killed",
                    "character_arc_beat": "Ondre becomes a legend.",
                },
                {
                    "chapter": 21,
                    "title": "The General's Last Map",
                    "pov": "The Cartographer-General",
                    "summary": "The General retreats to the throne room with his completed map.",
                    "key_events": [
                        "The General is acclaimed by his hidden allies",
                        "He begins the final re-drawing",
                    ],
                    "emotional_arc": "triumph → unraveling",
                    "foreshadowing": "his map has one line wrong",
                    "character_arc_beat": "The General overreaches.",
                },
                {
                    "chapter": 22,
                    "title": "The Final Survey",
                    "pov": "Aelith Vance",
                    "summary": "Aelith leads a small band to the throne room.",
                    "key_events": [
                        "The band enters the throne room",
                        "Aelith confronts the General",
                    ],
                    "emotional_arc": "confrontation → grief again",
                    "foreshadowing": "the General's wrong line is her lever",
                    "character_arc_beat": "Aelith reclaims her craft.",
                },
                {
                    "chapter": 23,
                    "title": "The Redrawing of the Kingdom",
                    "pov": "Aelith Vance",
                    "summary": "Aelith redraws the General's map over his own line by line.",
                    "key_events": [
                        "Aelith begins the re-drawing",
                        "The kingdom's stones begin to sing",
                    ],
                    "emotional_arc": "craft → transcendence",
                    "foreshadowing": "the cost will be her sight",
                    "character_arc_beat": "Aelith pays the price willingly.",
                },
                {
                    "chapter": 24,
                    "title": "The New Cartographer",
                    "pov": "Aelith Vance",
                    "summary": "A final quiet chapter; Aelith, now blind, takes a new apprentice.",
                    "key_events": [
                        "Aelith teaches her first apprentice",
                        "The kingdom is at peace, for now",
                    ],
                    "emotional_arc": "loss → legacy",
                    "foreshadowing": "the apprentice's name is not given",
                    "character_arc_beat": "The cycle begins again.",
                },
            ],
        },
    ]
    return {
        "acts": acts,
        "story_structure": "five_act",
        "pov_strategy": "rotating, Aelith primary",
        "estimated_words": 95000,
    }


SANITIZED_OUTLINE = _make_outline()


# ──────────────────────────────────────────────────────────────
# Sanitized chapter text samples (prose-only, no real content)
# ──────────────────────────────────────────────────────────────

def _make_chapter_text(num: int, title: str, pov: str, brief: dict) -> dict:
    """Generate a realistic ~800-word chapter sample for testing."""
    base_prose = (
        f"The morning of chapter {num} broke slow and gray. Aelith stood at the "
        f"window of the workshop, watching the mist rise off the Vael. {title} — "
        f"she had written the heading in Halden's old ledger, and her hand had "
        f"trembled. She was a cartographer's apprentice, not a poet. But there "
        f"was no one else to write the heading, and the work had to be done.\n\n"
    )
    middle = (
        f"Bren was downstairs, sharpening a knife that did not need sharpening. "
        f"He did this when he was worried. Aelith had learned the signs. The "
        f"compass in her pocket tugged gently at the silk lining, pointing north-"
        f"east, toward the Ash Vale, toward the broken stones. {brief['emotional_arc']}. "
        f"That was the line Halden had taught her: feel the line, then walk it.\n\n"
        f"There was a knock at the door — three raps, then two, then three. "
        f"The old waystation signal. Sister Ondre, then, or someone who knew the "
        f"old signals. Aelith set down the pen and went to the window. Below, in "
        f"the courtyard, a single figure stood in the gray light, hood up, hands "
        f"visible. The Cartographer-General's men came with hands hidden. So this "
        f"was a friend, or at least not an enemy. She went down to open the door.\n\n"
    )
    end = (
        f"What followed was a long conversation, and then a longer silence, and "
        f"then a decision. By dusk, the road was chosen. Aelith packed the "
        f"compass, the half-finished ward-map, and a small jar of Old Tomas's "
        f"ink. She left a note for Mira on the workbench. Then she and Bren went "
        f"out into the evening, where the mist had already begun to thicken "
        f"along the river, and the first of the broken ward-stones was waiting "
        f"for them at the end of the road.\n\n"
    )
    body = base_prose + middle + end
    return {
        "chapter": num,
        "title": title,
        "pov": pov,
        "content": body,
        "word_count": len(body.split()),
    }


def get_sanitized_chapters() -> list[dict]:
    """Return all 24 chapter text dicts."""
    chapters = []
    for act in SANITIZED_OUTLINE["acts"]:
        for ch in act["chapters"]:
            chapters.append(_make_chapter_text(
                num=ch["chapter"],
                title=ch["title"],
                pov=ch["pov"],
                brief=ch,
            ))
    return chapters


def get_sanitized_interview_answers() -> list[dict]:
    """Return a realistic interview answer set for testing interview/bible paths."""
    return [
        {
            "question_id": "concept-premise-001",
            "dimension": "concept_premise",
            "question": "In one sentence, what is your story about?",
            "answer": "A disgraced cartographer's apprentice who must redraw the kingdom's failing ward-stones to keep the old darkness at bay.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:00:00",
        },
        {
            "question_id": "concept-premise-002",
            "dimension": "concept_premise",
            "question": "What is the central conflict?",
            "answer": "The Cartographer-General is erasing the kingdom's ward-stones from the official maps, and only Aelith knows how to redraw them before the darkness returns.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:01:00",
        },
        {
            "question_id": "world-setting-001",
            "dimension": "world_setting",
            "question": "Describe the setting in a few sentences.",
            "answer": "The Sundered Marches, a kingdom of lowland river-reaches and a cold volcanic Ash Vale, ringed by thirteen ancient ward-stones that hold the darkness back.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:02:00",
        },
        {
            "question_id": "characters-001",
            "dimension": "characters",
            "question": "Who is the protagonist?",
            "answer": "Aelith Vance, 24, a cartographer's apprentice blamed for her mentor's death, stubborn and grief-touched.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:03:00",
        },
        {
            "question_id": "characters-002",
            "dimension": "characters",
            "question": "Who is the antagonist?",
            "answer": "The Cartographer-General, 58, charming and ruthless, secretly serving the Hollow Court.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:04:00",
        },
        {
            "question_id": "plot-structure-001",
            "dimension": "plot_structure",
            "question": "What is the climax?",
            "answer": "Aelith re-draws the General's throne-room map by hand, restoring the ward-stones at the cost of her sight.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:05:00",
        },
        {
            "question_id": "theme-voice-001",
            "dimension": "theme_voice",
            "question": "What is the dominant emotional register?",
            "answer": "Elegiac and atmospheric, with moments of stark horror in the Ash Vale chapters.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:06:00",
        },
        {
            "question_id": "market-comparisons-001",
            "dimension": "market_comparisons",
            "question": "What published novels share this DNA?",
            "answer": "The Goblin Emperor by Katherine Addison; Piranesi by Susanna Clarke; the Earthsea novels.",
            "is_thin": False,
            "timestamp": "2026-01-15T10:07:00",
        },
    ]


def get_sanitized_checkpoint(partial: bool = False) -> dict:
    """Return a realistic checkpoint.json for resume testing."""
    completed = ["seed", "worldbuilding", "characters", "outline"]
    if not partial:
        completed.append("draft")
    return {
        "completed_phases": completed,
        "version": 1,
    }


def write_sanitized_project(project_dir: str, partial: bool = False) -> str:
    """Write a complete sanitized project to the given directory.

    Returns the project_dir path.
    """
    os.makedirs(project_dir, exist_ok=True)
    os.makedirs(os.path.join(project_dir, "chapters"), exist_ok=True)

    # Phase outputs
    with open(os.path.join(project_dir, "spec.json"), "w") as f:
        json.dump(SANITIZED_SPEC, f, indent=2)
    with open(os.path.join(project_dir, "world.json"), "w") as f:
        json.dump(SANITIZED_WORLD, f, indent=2)
    with open(os.path.join(project_dir, "characters.json"), "w") as f:
        json.dump(SANITIZED_CHARACTERS, f, indent=2)
    with open(os.path.join(project_dir, "outline.json"), "w") as f:
        json.dump(SANITIZED_OUTLINE, f, indent=2)

    # Chapters
    if not partial:
        for ch in get_sanitized_chapters():
            fn = f"chapter-{ch['chapter']:03d}.md"
            path = os.path.join(project_dir, "chapters", fn)
            with open(path, "w") as f:
                f.write(f"> POV: {ch['pov']}\n\n# {ch['title']}\n\n{ch['content']}")

    # Checkpoint
    with open(os.path.join(project_dir, "checkpoint.json"), "w") as f:
        json.dump(get_sanitized_checkpoint(partial=partial), f, indent=2)

    return project_dir
