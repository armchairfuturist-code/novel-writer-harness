"""Canonical naming, address styles, and the roster block drafting prompts carry.

Design after EdwardAThomson/NovelWriter (MIT; commits 9da577900e, eba4e915ec,
6e18581e84):

* one canonical name per character - the title or honorific lives in its own
  field and ``display_name`` composes the two, so a prompt can carry both
  "Sister Ondre" and "Ondre" without ambiguity;
* ``NameRegistry.unique_name(build)`` relaxes in stages - given name plus full
  name unseen, then full name alone, then keep the last candidate - so a
  collision is recorded and audited, never raised;
* ``reserve_person_names`` takes faction leaders and other named world persons
  out of the pool before a new character is named;
* ``summarize_character_roster`` renders the roster block, and the block always
  ends with ``CLOSING_LINE``.

Nothing here touches the network. Every function tolerates the loose JSON an
LLM returns: missing keys, string entries, relationship maps as a string, a
list of dicts, or a dict of lists.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

# The line every roster block ends with. Prompt hygiene depends on it being
# verbatim, so tests assert on this constant rather than on a copy.
CLOSING_LINE = "Never invent names that are not in the roster."

ROSTER_HEADING = "CHARACTER ROSTER - canonical names, use these exact spellings:"

# What a prompt carries when no cast is on file yet. The rule still travels,
# so a first chapter cannot invent names freely.
NO_ROSTER = (
    "CHARACTER ROSTER - none on file yet. Use only names this manuscript has\n"
    "already established, and keep every new name consistent once introduced.\n"
    + CLOSING_LINE
)

# Honorifics and titles that belong in `title`, never in `name`.
HONORIFICS = (
    "mr", "mrs", "ms", "miss", "dr", "prof", "professor",
    "captain", "capt", "commander", "cmdr", "colonel", "col",
    "general", "gen", "major", "maj", "lieutenant", "lt",
    "sergeant", "sgt", "admiral", "adm", "marshal",
    "lord", "lady", "sir", "dame", "king", "queen", "prince", "princess",
    "duke", "duchess", "baron", "baroness", "count", "countess", "earl",
    "archduke", "emperor", "empress", "highness", "majesty",
    "elder", "mother", "father", "brother", "sister", "reverend", "pastor",
    "rabbi", "imam", "magister", "master", "mistress", "madam", "madame",
    "agent", "detective", "inspector", "deputy", "sheriff", "mayor",
)

_ARTICLES = ("the", "a", "an")

_WS_RE = re.compile(r"\s+")
_HONORIFIC_RE = re.compile(
    r"^(?:" + "|".join(re.escape(h) for h in HONORIFICS) + r")\b\.?\s+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Name shapes
# ---------------------------------------------------------------------------

def normalize_name(raw: Any) -> str:
    """Collapse whitespace and trim wrapping punctuation from a name."""
    text = "" if raw is None else str(raw)
    text = text.replace("\u00a0", " ")
    text = _WS_RE.sub(" ", text).strip()
    return text.strip(" \t\r\n\"'`,;:.")


def name_parts(name: Any) -> tuple[str, str]:
    """Return (given name, family name) for a canonical name.

    Leading articles are dropped, so "The Cartographer-General" yields
    ("Cartographer-General", ""). A single-token name has no family name.
    """
    tokens = [t for t in normalize_name(name).split(" ") if t]
    while tokens and tokens[0].lower() in _ARTICLES:
        tokens = tokens[1:]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], tokens[-1]


def compose_display(title: Any, name: Any) -> str:
    """Build the display form from a title and a canonical name."""
    title = normalize_name(title)
    name = normalize_name(name)
    if not title:
        return name
    if not name:
        return title
    if name.lower().startswith(title.lower()):
        return name
    return f"{title} {name}"


def split_name(raw: Any, explicit_title: Any = None) -> dict[str, str]:
    """Split one generated name into its canonical parts.

    Returns a dict with `name` (canonical, no title), `title`, `first`,
    `last`, `display_name` and `source` (what the model actually wrote).
    A name that is only a title - "Sister", "Captain" - keeps itself as the
    canonical name rather than coming back empty.
    """
    text = normalize_name(raw)
    title = normalize_name(explicit_title)
    body = text

    if title:
        # Trust the explicit field and strip a duplicated prefix from the name.
        if body.lower().startswith(title.lower()):
            body = normalize_name(body[len(title):]) or body
    else:
        match = _HONORIFIC_RE.match(text)
        if match:
            rest = normalize_name(text[match.end():])
            if rest:  # never leave a character nameless
                title = normalize_name(match.group(0))
                body = rest

    body = body or text or "Unnamed"
    first, last = name_parts(body)
    return {
        "name": body,
        "title": title,
        "first": first,
        "last": last,
        "display_name": compose_display(title, body),
        "source": text,
    }


def iter_characters(characters: Any) -> list[Any]:
    """Return the character list from any of the payload shapes we accept."""
    if isinstance(characters, dict):
        for key in ("characters", "raw_characters", "cast", "profiles"):
            value = characters.get(key)
            if isinstance(value, list):
                return value
        return []
    if isinstance(characters, list):
        return characters
    return []


# ---------------------------------------------------------------------------
# Address styles
# ---------------------------------------------------------------------------

ADDRESS_STYLE_DEFAULT = "default"

ADDRESS_STYLES: dict[str, dict[str, str]] = {
    "intimate": {
        "form": "given name only",
        "rule": "Use the given name. Drop every title and honorific.",
        "example": "'Renna,' he said, and did not wait for an answer.",
    },
    "formal": {
        "form": "title plus family name",
        "rule": "Use the recorded title with the family name. If no title is "
                "on file, use the full canonical name. Never shorten it.",
        "example": "'Sister Ondre will see you now.'",
    },
    "professional": {
        "form": "title plus family name, given name once trust is earned",
        "rule": "Open formal. Move to the given name only after the chapter "
                "earns it, and never move back.",
        "example": "'Vance.' A nod. Later: 'Aelith, hold the lamp.'",
    },
    "hostile": {
        "form": "family name alone",
        "rule": "Drop the title. Use the family name or the epithet on file. "
                "Never use the intimate form.",
        "example": "'Vance.' The word landed like a stone in a well.",
    },
    "deferential": {
        "form": "honorific plus title",
        "rule": "Always use the full titled form, in narration and in "
                "dialogue alike. Never shorten it.",
        "example": "'As the Cartographer-General orders.'",
    },
    "default": {
        "form": "given name",
        "rule": "Use the given name unless the profile says otherwise.",
        "example": "'Bren,' she said. 'Walk with me.'",
    },
}

_INTIMATE = ("lover", "wife", "husband", "spouse", "sister", "brother",
             "mother", "father", "son", "daughter", "childhood", "closest",
             "intimate", "friend", "kin", "married", "sibling", "family")
_HOSTILE = ("enemy", "rival", "hate", "hatred", "despis", "betrayer",
            "betray", "antagonist", "villain", "hunt", "wants dead", "feud",
            "foe", "nemesis", "resent")
_DEFERENTIAL = ("mentor", "apprentice", "servant", "worship", "priest",
                "obeys", "revere", "loyal", "superior", "devotee",
                "disciple", "queen", "king", "sworn to")
_PROFESSIONAL = ("colleague", "partner", "boss", "employer", "employee",
                 "client", "ally", "allies", "crew", "team", "guild",
                 "professional", "contract", "comrade")


def classify_relationship(dynamic: Any) -> str:
    """Map a relationship phrase to an address style key."""
    text = str(dynamic or "").lower()
    if not text.strip():
        return ADDRESS_STYLE_DEFAULT
    for style, words in (
        ("hostile", _HOSTILE),
        ("intimate", _INTIMATE),
        ("deferential", _DEFERENTIAL),
        ("professional", _PROFESSIONAL),
    ):
        if any(w in text for w in words):
            return style
    return ADDRESS_STYLE_DEFAULT


def _matches(candidate: str, name: str) -> bool:
    """Loose name match: equal, or one contains the other as a whole token."""
    a = normalize_name(candidate).lower()
    b = normalize_name(name).lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    return a in b.split(" ") or b in a.split(" ") or a in b or b in a


def _relationship_pairs(relationship_map: Any) -> list[tuple[str, str, str]]:
    """Normalize every relationship shape into (speaker, subject, dynamic)."""
    pairs: list[tuple[str, str, str]] = []
    if isinstance(relationship_map, str):
        if relationship_map.strip():
            pairs.append(("", "", relationship_map.strip()))
    elif isinstance(relationship_map, dict):
        for speaker, value in relationship_map.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        other = item.get("with") or item.get("to") or item.get("name") or ""
                        dyn = item.get("dynamic") or item.get("type") or ""
                        pairs.append((str(speaker), str(other), str(dyn)))
                    else:
                        pairs.append((str(speaker), str(item), ""))
            else:
                pairs.append((str(speaker), "", str(value)))
    elif isinstance(relationship_map, list):
        for item in relationship_map:
            if isinstance(item, dict):
                a = item.get("from") or item.get("with") or item.get("a") or ""
                b = item.get("to") or item.get("target") or item.get("b") or ""
                dyn = (item.get("type") or item.get("dynamic")
                       or item.get("relationship") or "")
                pairs.append((str(a), str(b), str(dyn)))
            elif isinstance(item, (tuple, list)):
                # A (speaker, subject, dynamic) triple, as roster_entries
                # and address_style_for pass it. Dropping the dynamic here
                # would flatten every form of address to the default.
                parts = [str(p) for p in item]
                if len(parts) >= 3:
                    pairs.append((parts[0], parts[1], parts[2]))
                elif len(parts) == 2:
                    pairs.append((parts[0], parts[1], ""))
            elif isinstance(item, str):
                pairs.append(("", "", item))
    return pairs


def _address_form(style: str, info: dict[str, str]) -> str:
    """The concrete string a speaker uses, with no invented honorifics."""
    if style == "hostile":
        return info["last"] or info["name"]
    if style in ("formal", "deferential", "professional"):
        return info["display_name"]
    return info["first"] or info["name"]


def address_style_for(speaker: Any, subject: Any,
                      relationship_map: Any = None) -> dict[str, Any]:
    """How `speaker` names `subject`, given the story's relationship data.

    Returns a dict with `style`, `form`, `rule`, `example`, `address_as`
    (the concrete string to write), `speaker`, `subject` and `dynamic`.
    Unknown pairings fall back to ADDRESS_STYLE_DEFAULT rather than guessing.
    """
    speaker_name = normalize_name(speaker)
    subject_info = split_name(subject)
    dynamic = ""
    for a, b, dyn in _relationship_pairs(relationship_map):
        if not dyn:
            continue
        if (_matches(a, speaker_name) and _matches(b, subject_info["display_name"])) or \
           (_matches(b, speaker_name) and _matches(a, subject_info["display_name"])):
            dynamic = dyn
            break
    style = classify_relationship(dynamic)
    entry: dict[str, Any] = dict(ADDRESS_STYLES[style])
    entry.update({
        "style": style,
        "speaker": speaker_name,
        "subject": subject_info["display_name"],
        "dynamic": dynamic,
        "address_as": _address_form(style, subject_info),
    })
    return entry


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _key(name: Any) -> str:
    return normalize_name(name).lower()


class NameRegistry:
    """Tracks canonical names so a new character cannot take one in use."""

    def __init__(self) -> None:
        self._full: dict[str, str] = {}
        self._first: dict[str, str] = {}
        self._reserved: list[dict[str, str]] = []
        self.history: list[dict[str, Any]] = []
        self.last_result: dict[str, Any] = {}

    # -- queries -----------------------------------------------------------
    def names(self) -> list[str]:
        return list(self._full.values())

    def reserved_names(self) -> list[str]:
        return [r["name"] for r in self._reserved]

    def is_taken(self, name: Any) -> bool:
        return _key(name) in self._full

    def is_reserved(self, name: Any) -> bool:
        return any(r["key"] == _key(name) for r in self._reserved)

    def first_taken(self, name: Any) -> bool:
        first, _ = name_parts(name)
        return bool(first) and _key(first) in self._first

    def match_reserved(self, info: dict[str, str]) -> str:
        """Return the reserved name this character is, or ""."""
        for candidate in (info.get("display_name", ""), info.get("name", ""),
                          info.get("source", "")):
            candidate = normalize_name(candidate)
            if candidate and self.is_reserved(candidate):
                return candidate
        return ""

    # -- writes ------------------------------------------------------------
    def add(self, name: Any, note: str = "") -> str:
        """Register a canonical name and its given name."""
        canonical = normalize_name(name) or "Unnamed"
        self._full[_key(canonical)] = canonical
        first, _ = name_parts(canonical)
        if first:
            self._first.setdefault(_key(first), canonical)
        if note:
            self._reserved.append({"name": canonical, "key": _key(canonical),
                                   "why": note})
        return canonical

    def reserve(self, name: Any, why: str = "reserved") -> bool:
        """Reserve a name. True when it was not reserved before."""
        canonical = normalize_name(name)
        if not canonical:
            return False
        key = _key(canonical)
        if any(r["key"] == key for r in self._reserved):
            return False
        self._reserved.append({"name": canonical, "key": key, "why": why})
        self._full.setdefault(key, canonical)
        first, _ = name_parts(canonical)
        if first:
            self._first.setdefault(_key(first), canonical)
        return True

    def unique_name(self, build: Callable[[], Any], max_tries: int = 6) -> str:
        """Return a free name, relaxing the rule in stages.

        `build` is called up to `max_tries` times and yields candidates.
        Stage 1 wants the given name and the full name both unseen. Stage 2
        accepts a full name whose given name is already in use. Stage 3 keeps
        the last candidate instead of raising, and records the collision in
        `last_result` and `history`.
        """
        tries = max(1, int(max_tries))
        candidates: list[str] = []
        for _ in range(tries):
            candidate = build() if callable(build) else build
            candidate = normalize_name(candidate)
            if candidate and (not candidates or candidates[-1] != candidate):
                candidates.append(candidate)
        if not candidates:
            candidates = ["Unnamed"]

        chosen = ""
        stage = ""
        for candidate in candidates:
            if not self.is_taken(candidate) and not self.first_taken(candidate):
                chosen, stage = candidate, "first_and_full"
                break
        if not chosen:
            for candidate in candidates:
                if not self.is_taken(candidate):
                    chosen, stage = candidate, "full_only"
                    break
        if not chosen:
            chosen, stage = candidates[-1], "keep_last"

        conflict = self.is_taken(chosen)
        self.add(chosen)
        self.last_result = {
            "name": chosen,
            "stage": stage,
            "attempts": len(candidates),
            "conflict": conflict,
        }
        self.history.append(dict(self.last_result))
        return chosen

    @classmethod
    def from_characters(cls, characters: Any, world: Any = None) -> "NameRegistry":
        """Build a registry from a characters payload plus the world."""
        registry = cls()
        reserve_person_names(registry, world)
        for raw in iter_characters(characters):
            entry = raw if isinstance(raw, dict) else {"name": raw}
            info = split_name(entry.get("name"), entry.get("title"))
            registry.add(info["display_name"])
            registry.add(info["name"])
        return registry


# ---------------------------------------------------------------------------
# World persons: names a new character may not take
# ---------------------------------------------------------------------------

_FACTION_KEYS = ("factions", "organizations", "organisations", "groups",
                 "houses", "guilds", "powers", "clans", "orders", "courts")
_PERSON_KEYS = ("leader", "leaders", "head", "heads", "ruler", "founder",
                "champion", "notable_members", "members", "named_persons",
                "people", "agents", "key_figures", "officers", "council")


def _collect_names(value: Any, out: list[str], depth: int = 0) -> None:
    if depth > 3:
        return
    if isinstance(value, str):
        text = normalize_name(value)
        if text:
            out.append(text)
    elif isinstance(value, dict):
        for key in ("name", "title", "person", "leader", "who", "figure"):
            if isinstance(value.get(key), str):
                out.append(normalize_name(value[key]))
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                _collect_names(nested, out, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _collect_names(item, out, depth + 1)


def iter_world_persons(world: Any) -> list[str]:
    """Names of persons the world already claims, faction leaders first."""
    found: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if lowered in _PERSON_KEYS:
                    _collect_names(value, found)
                elif isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(world)
    seen: set[str] = set()
    unique: list[str] = []
    for name in found:
        if name and _key(name) not in seen:
            seen.add(_key(name))
            unique.append(name)
    return unique


def iter_faction_names(world: Any) -> list[str]:
    """Faction names, so no character is ever named after an organization."""
    found: list[str] = []
    if isinstance(world, dict):
        for key, value in world.items():
            if str(key).lower() in _FACTION_KEYS:
                _collect_names(value, found)
            elif isinstance(value, (dict, list)):
                for item in (value if isinstance(value, list) else [value]):
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        pass
    seen: set[str] = set()
    out: list[str] = []
    for name in found:
        if name and _key(name) not in seen:
            seen.add(_key(name))
            out.append(name)
    return out


def reserve_person_names(registry: NameRegistry, world_or_faction_data: Any) -> list[str]:
    """Reserve every person and faction the world names.

    Returns the names newly reserved. Call this before naming a new character:
    a reserved name then fails both relaxation stages, so the new character is
    pushed to a different name instead of stealing a leader's.
    """
    reserved: list[str] = []
    if registry is None:
        return reserved
    for raw in iter_world_persons(world_or_faction_data):
        info = split_name(raw)
        for candidate in (info["display_name"], info["name"]):
            candidate = normalize_name(candidate)
            if candidate and registry.reserve(candidate, why="world person"):
                reserved.append(candidate)
    for raw in iter_faction_names(world_or_faction_data):
        candidate = normalize_name(raw)
        if candidate and registry.reserve(candidate, why="faction"):
            reserved.append(candidate)
    return reserved


# ---------------------------------------------------------------------------
# Roster block
# ---------------------------------------------------------------------------

def _relationship_index(characters: Any) -> list[tuple[str, str, str]]:
    """All (speaker, subject, dynamic) triples in the payload."""
    pairs: list[tuple[str, str, str]] = []
    if isinstance(characters, dict):
        pairs.extend(_relationship_pairs(characters.get("relationship_map")))
    for entry in iter_characters(characters):
        if not isinstance(entry, dict):
            continue
        owner = normalize_name(entry.get("display_name") or entry.get("name"))
        relations = entry.get("relationships")
        if isinstance(relations, list):
            for item in relations:
                if isinstance(item, dict):
                    other = normalize_name(item.get("with") or item.get("to")
                                           or item.get("name"))
                    dyn = str(item.get("dynamic") or item.get("type") or "")
                    if other:
                        pairs.append((owner, other, dyn))
                elif isinstance(item, str):
                    pairs.append((owner, item, ""))
        elif isinstance(relations, (dict, str)):
            pairs.extend(_relationship_pairs(relations))
    return pairs


def roster_entries(characters: Any, world: Any = None) -> list[dict[str, Any]]:
    """One normalized entry per character, with its address lines."""
    pairs = _relationship_index(characters)
    entries: list[dict[str, Any]] = []
    for raw in iter_characters(characters):
        entry = dict(raw) if isinstance(raw, dict) else {"name": normalize_name(raw)}
        info = split_name(entry.get("display_name") or entry.get("name"),
                          entry.get("title"))
        record = dict(entry)
        record.update({
            "name": info["name"] or entry.get("name"),
            "title": entry.get("title") or info["title"],
            "display_name": entry.get("display_name") or info["display_name"],
            "first": info["first"],
            "last": info["last"],
        })
        address: list[str] = []
        seen_forms: set[str] = set()
        for speaker, subject, dynamic in pairs:
            if not _matches(subject, record["display_name"]) and \
               not _matches(subject, record["name"]):
                continue
            styled = address_style_for(speaker, record["display_name"],
                                       [(speaker, subject, dynamic)])
            line = f'{normalize_name(speaker) or "Others"} says "{styled["address_as"]}"'
            if line in seen_forms:
                continue
            seen_forms.add(line)
            address.append(line)
            if len(address) >= 3:
                break
        record["address_lines"] = address
        entries.append(record)
    return entries


def summarize_character_roster(characters: Any, world: Any = None) -> str:
    """Render the roster block for a drafting or review prompt.

    The block always ends with CLOSING_LINE, so a prompt assembled from it
    carries the instruction even when the caller adds nothing else.
    """
    entries = roster_entries(characters, world)
    lines: list[str] = [ROSTER_HEADING]
    if not entries:
        lines.append("- (no characters on file yet)")
    for record in entries:
        title = record.get("title") or "none"
        role = record.get("role") or "unassigned"
        lines.append(
            f'- {record["display_name"]} | role: {role} | title: {title}'
            f' | canonical: {record["name"]}'
        )
        if record.get("address_lines"):
            lines.append("    Address: " + "; ".join(record["address_lines"]) + ".")
        else:
            lines.append(f'    Address: use "{record["display_name"]}"; '
                         "no relationship data on file.")
        if record.get("world_person"):
            lines.append(f'    Also a world person: {record["world_person"]}.')
        if record.get("name_note"):
            lines.append(f'    Note: {record["name_note"]}')

    reserved = []
    if isinstance(characters, dict) and isinstance(characters.get("reserved_names"), list):
        reserved = [normalize_name(r) for r in characters["reserved_names"]]
    elif world is not None:
        registry = NameRegistry()
        reserved = reserve_person_names(registry, world)
    if reserved:
        lines.append("")
        lines.append("RESERVED NAMES - in the world already, never reuse for a new character:")
        for name in reserved[:12]:
            lines.append(f"- {name}")

    lines.append("")
    lines.append(CLOSING_LINE)
    return "\n".join(lines)


def roster_for_prompt(characters: Any, world: Any = None) -> str:
    """Roster text for a prompt, reusing the block the characters phase built."""
    if isinstance(characters, dict):
        cached = characters.get("roster")
        if isinstance(cached, str) and cached.strip():
            return cached
    return summarize_character_roster(characters, world)


def _alternatives(info: dict[str, str]) -> Callable[[], str]:
    """A candidate generator that relaxes a name instead of failing."""
    ordered: list[str] = []
    for candidate in (
        info.get("name", ""),
        compose_display(info.get("title", ""), info.get("last", "")),
        info.get("last", ""),
        compose_display("", info.get("first", "")),
        info.get("display_name", ""),
    ):
        candidate = normalize_name(candidate)
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    if not ordered:
        ordered = ["Unnamed"]
    state = {"i": 0}

    def build() -> str:
        candidate = ordered[min(state["i"], len(ordered) - 1)]
        state["i"] += 1
        return candidate

    return build


def apply_registry(characters: Any, world: Any = None) -> Any:
    """Normalize a characters payload through a NameRegistry.

    Adds, per character: canonical `name`, `title`, `first`, `last`,
    `display_name`. Adds, at the top level: `roster` (the prompt block),
    `reserved_names`, and `name_notes` when anything was renamed or collided.
    Returns the payload it was given. Never raises, never drops a character:
    a name that cannot be freed is kept as written and reported.
    """
    if not isinstance(characters, dict):
        return characters

    people = iter_characters(characters)
    registry = NameRegistry()
    reserved = reserve_person_names(registry, world)
    notes: list[str] = []
    normalized: list[Any] = []

    for raw in people:
        entry = dict(raw) if isinstance(raw, dict) else {"name": normalize_name(raw)}
        info = split_name(entry.get("name"), entry.get("title"))

        claimed = registry.match_reserved(info)
        if claimed:
            # This character IS the world person; do not rename them.
            registry.add(info["display_name"])
            registry.add(info["name"])
            entry["world_person"] = claimed
        else:
            chosen = registry.unique_name(_alternatives(info), max_tries=4)
            result = dict(registry.last_result)
            if result.get("conflict"):
                note = (f'kept as written: "{info["display_name"]}" duplicates a '
                        f'name already in the roster ({result["stage"]})')
                entry["name_note"] = note
                notes.append(note)
                registry.add(info["display_name"])
            elif normalize_name(chosen) != normalize_name(info["name"]):
                note = (f'renamed "{info["display_name"]}" to "{chosen}" '
                        f'({result["stage"]}) to avoid a clash')
                entry["name_note"] = note
                notes.append(note)
                info = split_name(chosen, entry.get("title"))

        entry["name"] = info["name"]
        entry["title"] = info["title"]
        entry["first"] = info["first"]
        entry["last"] = info["last"]
        entry["display_name"] = info["display_name"]
        entry["canonical_source"] = info["source"]
        normalized.append(entry)

    if normalized:
        characters["characters"] = normalized
    characters["reserved_names"] = reserved
    if notes:
        characters["name_notes"] = notes
    characters["roster"] = summarize_character_roster(characters, world)
    return characters
