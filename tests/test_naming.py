"""Tests for pipeline/naming.py: canonical names, address styles, roster block.

Covers the v0.8 naming-hygiene layer: one canonical name per character with
the title in its own field, a staged-relaxation registry, reserved world and
faction names, per-relationship address styles, and the roster block that
every drafting and debate prompt carries.
"""
import unittest

from pipeline.naming import (
    ADDRESS_STYLES,
    ADDRESS_STYLE_DEFAULT,
    CLOSING_LINE,
    NO_ROSTER,
    ROSTER_HEADING,
    NameRegistry,
    address_style_for,
    apply_registry,
    classify_relationship,
    compose_display,
    iter_world_persons,
    name_parts,
    normalize_name,
    reserve_person_names,
    roster_entries,
    roster_for_prompt,
    split_name,
    summarize_character_roster,
)


WORLD = {
    "world_name": "Verrel",
    "factions": [
        {"name": "The Gilded Choir", "leader": "Mother Vesper"},
        {"name": "Iron Ledger", "head": "Cassik Drayle"},
    ],
    "central_conflict": "The Choir hoards the healing songs.",
}


def cast():
    """A small cast in the shape the characters phase returns."""
    return {
        "characters": [
            {
                "name": "Sister Ondre Vael",
                "role": "protagonist",
                "arc": "from obedience to refusal",
                "relationships": [
                    {"with": "Renna Cole", "dynamic": "sworn enemy"},
                    {"with": "Bren Ashby", "dynamic": "childhood friend"},
                ],
            },
            {
                "name": "Renna Cole",
                "role": "antagonist",
                "arc": "from grief to cruelty",
                "relationships": [
                    {"with": "Sister Ondre Vael", "dynamic": "her apprentice once"},
                ],
            },
            {"name": "Bren Ashby", "role": "supporting", "arc": "from doubt to loyalty"},
        ],
        "relationship_map": "Ondre and Renna were once close; Bren serves both.",
    }


class TestNameShapes(unittest.TestCase):
    def test_normalize_collapses_whitespace_and_punctuation(self):
        self.assertEqual(normalize_name('  "Ada   Lovelace,"  '), "Ada Lovelace")
        self.assertEqual(normalize_name(None), "")

    def test_name_parts_drops_a_leading_article(self):
        self.assertEqual(name_parts("The Cartographer-General"),
                         ("Cartographer-General", ""))
        self.assertEqual(name_parts("Ada Lovelace"), ("Ada", "Lovelace"))

    def test_split_name_moves_the_honorific_into_its_own_field(self):
        info = split_name("Sister Ondre Vael")
        self.assertEqual(info["title"], "Sister")
        self.assertEqual(info["name"], "Ondre Vael")
        self.assertEqual(info["first"], "Ondre")
        self.assertEqual(info["last"], "Vael")
        self.assertEqual(info["display_name"], "Sister Ondre Vael")
        self.assertEqual(info["source"], "Sister Ondre Vael")

    def test_split_name_trusts_an_explicit_title_and_strips_the_duplicate(self):
        info = split_name("Captain Renna Cole", "Captain")
        self.assertEqual(info["title"], "Captain")
        self.assertEqual(info["name"], "Renna Cole")
        self.assertEqual(info["display_name"], "Captain Renna Cole")

    def test_a_title_only_name_never_comes_back_empty(self):
        info = split_name("Sister")
        self.assertTrue(info["name"])
        self.assertTrue(info["display_name"])

    def test_compose_display_never_doubles_the_title(self):
        self.assertEqual(compose_display("Sister", "Sister Ondre"), "Sister Ondre")
        self.assertEqual(compose_display("Sister", "Ondre Vael"), "Sister Ondre Vael")
        self.assertEqual(compose_display("", "Ondre Vael"), "Ondre Vael")


class TestAddressStyles(unittest.TestCase):
    def test_every_style_carries_form_rule_and_example(self):
        for style, body in ADDRESS_STYLES.items():
            for key in ("form", "rule", "example"):
                self.assertTrue(body.get(key), f"{style} missing {key}")
        self.assertIn(ADDRESS_STYLE_DEFAULT, ADDRESS_STYLES)

    def test_classify_relationship_maps_each_stance(self):
        self.assertEqual(classify_relationship("sworn enemy"), "hostile")
        self.assertEqual(classify_relationship("childhood friend"), "intimate")
        self.assertEqual(classify_relationship("her apprentice"), "deferential")
        self.assertEqual(classify_relationship("guild colleague"), "professional")
        self.assertEqual(classify_relationship(""), ADDRESS_STYLE_DEFAULT)
        self.assertEqual(classify_relationship("met once at a market"),
                         ADDRESS_STYLE_DEFAULT)

    def test_hostile_uses_the_family_name_alone(self):
        styled = address_style_for(
            "Renna Cole", "Ondre Vael",
            [{"from": "Renna Cole", "to": "Ondre Vael", "dynamic": "sworn enemy"}],
        )
        self.assertEqual(styled["style"], "hostile")
        self.assertEqual(styled["address_as"], "Vael")

    def test_deferential_uses_the_full_titled_form(self):
        styled = address_style_for(
            "Bren Ashby", "Sister Ondre Vael",
            [{"from": "Bren Ashby", "to": "Sister Ondre Vael",
              "dynamic": "her apprentice"}],
        )
        self.assertEqual(styled["style"], "deferential")
        self.assertEqual(styled["address_as"], "Sister Ondre Vael")

    def test_intimate_uses_the_given_name(self):
        styled = address_style_for(
            "Bren Ashby", "Ondre Vael",
            [{"from": "Bren Ashby", "to": "Ondre Vael", "dynamic": "childhood friend"}],
        )
        self.assertEqual(styled["style"], "intimate")
        self.assertEqual(styled["address_as"], "Ondre")

    def test_an_unknown_pairing_falls_back_rather_than_guessing(self):
        styled = address_style_for("Some Stranger", "Ondre Vael", None)
        self.assertEqual(styled["style"], ADDRESS_STYLE_DEFAULT)
        self.assertEqual(styled["address_as"], "Ondre")
        self.assertEqual(styled["dynamic"], "")


class TestNameRegistry(unittest.TestCase):
    def test_stage_one_takes_the_first_and_full_name_when_both_are_free(self):
        reg = NameRegistry()
        chosen = reg.unique_name(iter_candidates("Ada Lovelace", "Ada L", "Lovelace"))
        self.assertEqual(chosen, "Ada Lovelace")
        self.assertEqual(reg.last_result["stage"], "first_and_full")
        self.assertFalse(reg.last_result["conflict"])

    def test_stage_two_accepts_a_full_name_whose_given_name_is_taken(self):
        reg = NameRegistry()
        reg.add("Ada Lovelace")
        chosen = reg.unique_name(iter_candidates("Ada Byron", "Ada Lovelace"))
        self.assertEqual(chosen, "Ada Byron")
        self.assertEqual(reg.last_result["stage"], "full_only")
        self.assertFalse(reg.last_result["conflict"])

    def test_stage_three_keeps_the_last_candidate_instead_of_raising(self):
        reg = NameRegistry()
        reg.add("Ada Lovelace")
        chosen = reg.unique_name(iter_candidates("Ada Lovelace"))
        self.assertEqual(chosen, "Ada Lovelace")
        self.assertEqual(reg.last_result["stage"], "keep_last")
        self.assertTrue(reg.last_result["conflict"])
        self.assertEqual(len(reg.history), 1)

    def test_a_plain_string_build_works_too(self):
        reg = NameRegistry()
        self.assertEqual(reg.unique_name("Wren Halloway"), "Wren Halloway")

    def test_add_registers_the_given_name_as_taken(self):
        reg = NameRegistry()
        reg.add("Renna Cole")
        self.assertTrue(reg.is_taken("Renna Cole"))
        self.assertTrue(reg.first_taken("Renna Something"))
        self.assertFalse(reg.is_taken("Bren Ashby"))

    def test_reserve_is_idempotent_and_reports_the_first_claim(self):
        reg = NameRegistry()
        self.assertTrue(reg.reserve("Mother Vesper", why="world person"))
        self.assertFalse(reg.reserve("Mother Vesper", why="world person"))
        self.assertIn("Mother Vesper", reg.reserved_names())
        self.assertTrue(reg.is_reserved("mother vesper"))

    def test_from_characters_registers_the_cast_and_the_world(self):
        reg = NameRegistry.from_characters(cast(), WORLD)
        self.assertTrue(reg.is_taken("Sister Ondre Vael"))
        self.assertTrue(reg.is_taken("Renna Cole"))
        self.assertTrue(reg.is_reserved("Mother Vesper"))


def iter_candidates(*names):
    """A build callable that yields the given candidates in order."""
    state = {"i": 0}

    def build():
        candidate = names[min(state["i"], len(names) - 1)]
        state["i"] += 1
        return candidate

    return build


class TestReservePersonNames(unittest.TestCase):
    def test_world_persons_and_factions_are_reserved(self):
        reg = NameRegistry()
        reserved = reserve_person_names(reg, WORLD)
        self.assertIn("Mother Vesper", reserved)
        self.assertIn("The Gilded Choir", reserved)
        self.assertTrue(reg.is_reserved("Cassik Drayle"))

    def test_a_new_character_cannot_take_a_faction_leaders_name(self):
        reg = NameRegistry()
        reserve_person_names(reg, WORLD)
        chosen = reg.unique_name(iter_candidates("Mother Vesper", "Wren Halloway"))
        self.assertEqual(chosen, "Wren Halloway")
        self.assertEqual(reg.last_result["stage"], "first_and_full")

    def test_when_only_the_taken_name_is_offered_it_is_kept_and_flagged(self):
        reg = NameRegistry()
        reserve_person_names(reg, WORLD)
        chosen = reg.unique_name(iter_candidates("Mother Vesper"))
        self.assertEqual(chosen, "Mother Vesper")
        self.assertTrue(reg.last_result["conflict"])

    def test_iter_world_persons_finds_leaders_in_nested_shapes(self):
        persons = iter_world_persons({"factions": [{"leader": "Mother Vesper"}],
                                      "ruler": "King Aldous"})
        self.assertIn("Mother Vesper", persons)

    def test_no_world_data_reserves_nothing(self):
        reg = NameRegistry()
        self.assertEqual(reserve_person_names(reg, None), [])
        self.assertEqual(reserve_person_names(reg, {}), [])


class TestRoster(unittest.TestCase):
    def test_the_roster_block_ends_with_the_exact_closing_line(self):
        text = summarize_character_roster(cast(), WORLD)
        self.assertTrue(text.rstrip().endswith(CLOSING_LINE))
        self.assertEqual(CLOSING_LINE, "Never invent names that are not in the roster.")
        self.assertTrue(text.startswith(ROSTER_HEADING))

    def test_each_entry_carries_name_role_title_and_address(self):
        text = summarize_character_roster(cast(), WORLD)
        self.assertIn("Sister Ondre Vael", text)
        self.assertIn("role: protagonist", text)
        self.assertIn("title: Sister", text)
        self.assertIn("canonical: Ondre Vael", text)
        self.assertIn("Address:", text)

    def test_address_lines_follow_the_relationship_data(self):
        entries = roster_entries(cast(), WORLD)
        by_display = {e["display_name"]: e for e in entries}
        ondre = by_display["Sister Ondre Vael"]
        self.assertTrue(ondre["address_lines"])
        # Renna was once Ondre's apprentice, so she uses the full titled form.
        self.assertTrue(any('"Sister Ondre Vael"' in line for line in ondre["address_lines"]),
                        ondre["address_lines"])
        # Ondre regards Renna as a sworn enemy, so she drops to the family name.
        renna = by_display["Renna Cole"]
        self.assertTrue(any('"Cole"' in line for line in renna["address_lines"]),
                        renna["address_lines"])

    def test_reserved_names_are_listed_for_the_prompt(self):
        text = summarize_character_roster(cast(), WORLD)
        self.assertIn("RESERVED NAMES", text)
        self.assertIn("Mother Vesper", text)

    def test_an_empty_cast_still_carries_the_rule(self):
        text = summarize_character_roster({"characters": []})
        self.assertIn("no characters on file", text)
        self.assertTrue(text.rstrip().endswith(CLOSING_LINE))

    def test_no_roster_placeholder_carries_the_rule_too(self):
        self.assertTrue(NO_ROSTER.rstrip().endswith(CLOSING_LINE))

    def test_roster_for_prompt_reuses_the_cached_block(self):
        payload = cast()
        payload["roster"] = "CACHED ROSTER\n" + CLOSING_LINE
        self.assertEqual(roster_for_prompt(payload, WORLD), payload["roster"])

    def test_roster_for_prompt_renders_when_nothing_is_cached(self):
        text = roster_for_prompt(cast(), WORLD)
        self.assertIn(ROSTER_HEADING, text)
        self.assertTrue(text.rstrip().endswith(CLOSING_LINE))


class TestApplyRegistry(unittest.TestCase):
    def test_it_adds_the_canonical_fields_and_the_roster(self):
        payload = apply_registry(cast(), WORLD)
        first = payload["characters"][0]
        for key in ("name", "title", "first", "last", "display_name"):
            self.assertIn(key, first)
        self.assertEqual(first["display_name"], "Sister Ondre Vael")
        self.assertEqual(first["name"], "Ondre Vael")
        self.assertIn("roster", payload)
        self.assertIn("Mother Vesper", payload["reserved_names"])

    def test_it_is_idempotent_over_an_already_registered_cast(self):
        once = apply_registry(cast(), WORLD)
        names_first = [c["display_name"] for c in once["characters"]]
        twice = apply_registry(once, WORLD)
        names_second = [c["display_name"] for c in twice["characters"]]
        self.assertEqual(names_first, names_second)
        self.assertEqual(len(once["name_notes"]) if "name_notes" in once else 0,
                         len(twice["name_notes"]) if "name_notes" in twice else 0)

    def test_a_duplicate_cast_member_is_moved_off_the_taken_name(self):
        payload = {"characters": [{"name": "Renna Cole", "role": "antagonist"},
                                  {"name": "Renna Cole", "role": "supporting"}]}
        out = apply_registry(payload)
        names = [c["display_name"] for c in out["characters"]]
        self.assertEqual(len(set(names)), 2, names)
        self.assertTrue(out.get("name_notes"))

    def test_it_never_drops_a_character(self):
        payload = cast()
        payload["characters"].append("Plain String Name")
        out = apply_registry(payload, WORLD)
        self.assertEqual(len(out["characters"]), 4)

    def test_a_world_person_is_not_renamed(self):
        payload = {"characters": [{"name": "Mother Vesper", "role": "antagonist"}]}
        out = apply_registry(payload, WORLD)
        entry = out["characters"][0]
        self.assertEqual(entry["display_name"], "Mother Vesper")
        self.assertEqual(entry["world_person"], "Mother Vesper")
        self.assertFalse(out.get("name_notes"))

    def test_a_non_dict_payload_comes_back_untouched(self):
        self.assertEqual(apply_registry("not a payload"), "not a payload")
        self.assertIsNone(apply_registry(None))


if __name__ == "__main__":
    unittest.main()
