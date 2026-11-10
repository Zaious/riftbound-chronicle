#!/usr/bin/env python3
"""clause-grammar.v1, second version: sub-grammars and composable productions.

DP-84: a production is a template over sub-grammar slots, not a literal
sentence. DP-85: the keyword production's alternatives are generated from
`keyword-catalog.v1`, which is the single source of truth for what a keyword
is and whether the engine implements it.

Fixtures are synthetic or Wave A only; real Wave B card text stays in the
private overlay (Round H repo-boundary ruling).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# The checkout this script lives in. It was a hard-coded absolute path to one
# delegation worktree, so running it from any other checkout rewrote THAT worktree's
# grammar and left this one stale (found 2026-09-22).
ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "skill" / "data" / "clause_grammar" / "clause_grammar.json"
CATALOGUE = ROOT / "skill" / "data" / "keyword_catalog" / "keyword_catalog.json"
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
from effect_ir import GRANTABLE_KEYWORDS, UNTIMED_GRANTABLE_KEYWORDS  # noqa: E402

N = "clause-grammar.v1/normalize"


def keyword_alternatives() -> dict:
    """Every keyword the catalogue names, with whether the engine implements
    it. A keyword the catalogue does not name is not a keyword to this
    grammar — that is what makes the catalogue the single source (DP-85)."""
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    alternatives = {}
    for entry in catalogue["entries"]:
        name = entry["name"]
        key = name.lower()
        # the printed name is what the pattern reads; the catalogue id is the keyword the engine knows - the same for
        # every keyword but Quick-Draw (2026-11-03, ADR-0017: "quick-draw" is not a group name, quick_draw is the id)
        ident = entry["keyword_id"]
        alternatives[ident] = {
            "pattern": rf"\[{re.escape(key)}(?: (?P<{ident}_value>\d+))?\]",
            "value": {"keyword": ident, "implemented": bool(entry.get("production"))},
        }
    return alternatives


def printed_name(keyword_id: str) -> str:
    """The keyword as a card prints it ("Quick-Draw" for quick_draw), from the catalogue."""
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return next(entry["name"] for entry in catalogue["entries"] if entry["keyword_id"] == keyword_id)


def grantable_alternatives() -> dict:
    """The keywords an effect may grant for a duration — the engine's own
    `GRANTABLE_KEYWORDS`, intersected with the catalogue."""
    catalogue = {e["name"].lower() for e in json.loads(CATALOGUE.read_text(encoding="utf-8"))["entries"]}
    return {
        keyword: {"pattern": rf"\[{keyword}(?: (?P<{keyword}_grant_value>\d+))?\]", "value": {"keyword": keyword}}
        # 2026-09-27: Temporary is granted with no duration (Core 801.3.a.3) by its own rows, not here
        for keyword in sorted((GRANTABLE_KEYWORDS - UNTIMED_GRANTABLE_KEYWORDS) & catalogue)
    }


SUB_GRAMMARS = {
    "selector": {
        "note": "who an instruction acts on. `me` is the source object itself.",
        "alternatives": {
            "a_unit": {"pattern": "a unit", "value": {"scope": "target", "kind": "unit"}},
            "a_friendly_unit": {"pattern": "a friendly unit", "value": {"scope": "target", "kind": "unit", "controller_relation": "friendly"}},
            "an_enemy_unit": {"pattern": "an enemy unit", "value": {"scope": "target", "kind": "unit", "controller_relation": "enemy"}},
            "friendly_units": {"pattern": "friendly units", "value": {"scope": "affected", "kind": "unit", "controller_relation": "friendly"}},
            "enemy_units": {"pattern": "enemy units", "value": {"scope": "affected", "kind": "unit", "controller_relation": "enemy"}},
            "me": {"pattern": "me", "value": {"scope": "source"}},
            # DP-86: a referent names the object an earlier part of the same
            # clause already chose. It carries no criteria of its own, so it
            # cannot re-find another unit that merely also matches.
            # Round H: "another" is this object excluded by identity, not by
            # name - the engine resolves the exclusion from the program's own
            # source_object when the choice is made.
            "another_unit": {"pattern": "another unit", "value": {"scope": "target", "kind": "unit", "exclude_source": True}},
            "another_friendly_unit": {"pattern": "another friendly unit",
                                      "value": {"scope": "target", "kind": "unit", "controller_relation": "friendly", "exclude_source": True}},
            "it": {"pattern": "it", "value": {"scope": "referent"}},
            "that_unit": {"pattern": "that unit", "value": {"scope": "referent"}},
        },
    },
    "might_delta": {
        "note": "a signed Might change, with the floor the printed text states.",
        "alternatives": {
            "increase": {"pattern": r"\+(?P<increase_amount>\d+)", "value": {"direction": "increase"}},
            "decrease": {"pattern": r"-(?P<decrease_amount>\d+)", "value": {"direction": "decrease"}},
        },
    },
    "duration": {
        "note": "how long a granted characteristic lasts.",
        "alternatives": {
            "this_turn": {"pattern": "this turn", "value": {"duration": "this_turn"}},
            "this_combat": {"pattern": "this combat", "value": {"duration": "this_combat"}},
        },
    },
    "keyword": {"note": "generated from keyword-catalog.v1 (DP-85).", "alternatives": keyword_alternatives()},
    "grantable_keyword": {"note": "the keywords an effect may grant, from the engine's own list.",
                          "alternatives": grantable_alternatives()},
}

# Slot pairs whose alternatives jointly change the meaning, so the goldens must
# cover their cross product, not merely each alternative once (Codex, DP-84).
JOINT = [["selector", "might_delta"], ["selector", "grantable_keyword"], ["might_delta", "duration"]]

PRODUCTIONS = [
    {
        "production_id": "give_might_for_duration",
        "form": "Give <selector> <might_delta> [M] <duration>[, to a minimum of N].",
        "template": r"give {selector} {might_delta} \[m\] {duration}(?:, to a minimum of (?P<floor>\d+) \[m\])?",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "friendly_units", "enemy_units", "me",
                               "it", "that_unit", "another_unit", "another_friendly_unit"],
                  "might_delta": ["increase", "decrease"], "duration": ["this_turn", "this_combat"]},
        "normalization": N,
        "rule_locators": ["Core 478", "Core 481", "Core 317.2"],
        "ast_node": "instruction",
        "required_capability": ["modify_might", "targeting"],
        "boundary": "One signed Might change for a duration. A second linked grant, or a value read from the board, is a different production.",
        "golden": [
            "Give a unit +1 [M] this turn.", "Give a friendly unit +3 [M] this turn.",
            "Give an enemy unit +1 [M] this turn.", "Give friendly units +2 [M] this turn.",
            "Give enemy units +1 [M] this turn.", "Give me +2 [M] this turn.",
            "Give a unit -1 [M] this turn.", "Give a friendly unit -1 [M] this turn.",
            "Give an enemy unit -3 [M] this turn, to a minimum of 0 [M].",
            "Give friendly units -1 [M] this turn.", "Give enemy units -2 [M] this turn.",
            "Give me -1 [M] this turn.",
            "Give another unit +1 [M] this turn.", "Give another unit -1 [M] this turn.",
            "Give another friendly unit +2 [M] this turn.", "Give another friendly unit -2 [M] this turn.",
            "Give it +1 [M] this turn.", "Give it -1 [M] this turn.",
            "Give that unit +2 [M] this turn.", "Give that unit -2 [M] this turn.",
            "Give a unit +1 [M] this combat.", "Give me -1 [M] this combat.",
            "Give friendly units +1 [M] this combat.", "Give an enemy unit -1 [M] this combat.",
        ],
        "negative": [
            "Give the strongest unit +1 [M] this turn.",
            "Give a unit +X [M] this turn.",
            "Give a unit +1 [M] permanently.",
            "Give a unit +1 [M] this turn, then an additional +1 [M] this turn.",
        ],
    },
    {
        "production_id": "grant_keyword_for_duration",
        "form": "Give <selector> <grantable_keyword> <duration>.",
        "template": r"give {selector} {grantable_keyword} {duration}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "friendly_units", "enemy_units", "me",
                               "it", "that_unit", "another_unit", "another_friendly_unit"],
                  "grantable_keyword": sorted(grantable_alternatives()), "duration": ["this_turn", "this_combat"]},
        "normalization": N,
        "rule_locators": ["Core 479.3", "Core 317.2"],
        "ast_node": "instruction",
        "required_capability": ["grant_keyword", "targeting"],
        "boundary": "Only the keywords the engine can grant. A keyword outside that list is a different clause and stays unparsed.",
        "golden": [
            "Give a unit [Shield 2] this turn.", "Give a friendly unit [Shield 1] this turn.",
            "Give an enemy unit [Shield 1] this turn.", "Give friendly units [Shield 1] this turn.",
            "Give enemy units [Shield 1] this turn.", "Give me [Shield 2] this turn.",
            "Give a unit [Tank] this turn.", "Give a friendly unit [Tank] this turn.",
            "Give an enemy unit [Tank] this turn.", "Give friendly units [Tank] this turn.",
            "Give enemy units [Tank] this turn.", "Give me [Tank] this turn.",
            "Give a unit [Ganking] this turn.", "Give a friendly unit [Ganking] this turn.",
            "Give an enemy unit [Ganking] this turn.", "Give friendly units [Ganking] this turn.",
            "Give enemy units [Ganking] this turn.", "Give me [Ganking] this turn.",
            "Give a unit [Backline] this turn.", "Give a friendly unit [Backline] this turn.",
            "Give an enemy unit [Backline] this turn.", "Give friendly units [Backline] this turn.",
            "Give enemy units [Backline] this turn.", "Give me [Backline] this turn.",
            "Give another unit [Shield 1] this turn.", "Give another unit [Tank] this turn.",
            "Give another unit [Ganking] this turn.", "Give another unit [Backline] this turn.",
            "Give another friendly unit [Shield 2] this turn.", "Give another friendly unit [Tank] this turn.",
            "Give another friendly unit [Ganking] this turn.", "Give another friendly unit [Backline] this turn.",
            "Give it [Shield 1] this turn.", "Give it [Tank] this turn.",
            "Give it [Ganking] this turn.", "Give it [Backline] this turn.",
            "Give that unit [Shield 2] this turn.", "Give that unit [Tank] this turn.",
            "Give that unit [Ganking] this turn.", "Give that unit [Backline] this turn.",
            "Give a unit [Shield 1] this combat.", "Give me [Tank] this combat.",
            "Give friendly units [Ganking] this combat.", "Give an enemy unit [Backline] this combat.",
            # 2026-09-27: Assault is grantable (Core 807.2's own example is "Give a unit [Assault 3]
            # this turn."); a bare [Assault] is Assault 1 (807.1.b.3)
            "Give a unit [Assault 3] this turn.", "Give a friendly unit [Assault 2] this turn.",
            "Give an enemy unit [Assault] this turn.", "Give friendly units [Assault 1] this turn.",
            "Give enemy units [Assault 2] this turn.", "Give me [Assault 2] this turn.",
            "Give another unit [Assault 3] this turn.", "Give another friendly unit [Assault 1] this turn.",
            "Give it [Assault 2] this turn.", "Give that unit [Assault 3] this turn.",
            "Give a unit [Assault 2] this combat.",
        ],
        "negative": [
            "Give a unit [Assault 3] permanently.",
            "Give the strongest unit [Tank] this turn.",
            "Give a unit [Tank] permanently.",
            "Give a unit [Temporary] this turn.",
        ],
    },
    {
        "production_id": "while_a_friendly_unit_defends_alone_it_gets_might",
        "form": "While a friendly unit defends alone, it gets <might_delta> [M].",
        "template": r"while a friendly unit defends alone, it gets {might_delta} \[m\]",
        "slots": {"might_delta": ["increase", "decrease"]},
        "normalization": N,
        "rule_locators": ["Core 479.4", "Core 462", "Core 464"],
        "ast_node": "passive",
        "required_capability": ["might_aura", "combat_state"],
        "boundary": ("A standing Might aura whose condition the engine names exactly: a lone defender. "
                     "The aura is not a target and grants nothing else; a different combat condition, "
                     "or a keyword instead of Might, is a different production."),
        "golden": ["While a friendly unit defends alone, it gets +2 [M].",
                   "While a friendly unit defends alone, it gets +1 [M].",
                   "While a friendly unit defends alone, it gets -1 [M]."],
        "negative": ["While a friendly unit defends, it gets +2 [M].",
                     "While a friendly unit attacks alone, it gets +2 [M].",
                     "While a friendly unit defends alone, it gets [Tank].",
                     "While a friendly unit defends alone, it gets +2 [M] this turn."],
    },
    {
        "production_id": "ready_selector",
        "form": "Ready <selector>.",
        "template": r"ready {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 416", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["ready", "targeting"],
        "boundary": "One chosen object is readied. A count ('ready up to 2 runes') or a rune selector is a different production.",
        "golden": [
            "Ready a unit.", "Ready a friendly unit.", "Ready an enemy unit.", "Ready me.",
            "Ready another unit.", "Ready another friendly unit.", "Ready it.", "Ready that unit.",
        ],
        "negative": ["Ready up to 2 runes.", "Ready all friendly units.", "Ready the strongest unit."],
    },
    {
        "production_id": "stun_selector",
        "form": "Stun <selector>.",
        "template": r"stun {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 424", "Core 424.1", "Core 424.2", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["stun", "targeting"],
        "boundary": ("Direct application only: one chosen Unit on the board becomes Stunned until the "
                     "Expiration Step. A trigger on stunning, a condition or aura reading the status, a "
                     "replacement for being Stunned, and a cost condition are each a different clause "
                     "and stay unparsed."),
        "golden": ["Stun a unit.", "Stun a friendly unit.", "Stun an enemy unit.", "Stun me.",
                   "Stun another unit.", "Stun another friendly unit.", "Stun it.", "Stun that unit."],
        "negative": ["Stun all enemy units.", "Stun up to 2 units.", "Stun the strongest unit."],
    },
    {
        "production_id": "move_selector",
        "form": "Move <selector>.",
        "template": r"move {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 421", "Core 355.4", "Core 355.4.a", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["move_board_object", "targeting"],
        "boundary": ("One chosen object moves to a board Location its controller's opponent does not "
                     "get to pick. The destination is a resolution-stage choice made by the effect's "
                     "controller from the Locations this board actually has; a named destination "
                     "('move it to your base') is a different production."),
        "golden": ["Move a unit.", "Move a friendly unit.", "Move an enemy unit.", "Move me.",
                   "Move another unit.", "Move another friendly unit.", "Move it.", "Move that unit."],
        "negative": ["Move a unit to your base.", "Move all enemy units.", "Move up to 2 units."],
    },
    {
        # 2026-09-25 (Yasuo - Unforgiven): the chosen Move narrowed by "to or from its base"
        "production_id": "move_selector_to_or_from_its_base",
        "form": "Move <selector> to or from its base.",
        "template": r"move {selector} to or from its base",
        "slots": {"selector": ["a_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 421", "Core 355.4", "Core 355.4.a", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["move_board_object", "targeting"],
        "boundary": ("One chosen friendly unit moves: from a Battlefield only to its own Base, from its Base "
                     "only to a Battlefield; where exactly is its controller's resolution-stage choice. 'Move it "
                     "to your base' or an unnarrowed Move is a different production."),
        "golden": ["Move a friendly unit to or from its base."],
        "negative": ["Move a friendly unit to its base.", "Move a friendly unit.", "Move an enemy unit to or from its base."],
    },
    {
        "production_id": "heal_selector",
        "form": "Heal <selector>.",
        "template": r"heal {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 442", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["heal_all_damage", "targeting"],
        "boundary": "All damage is removed from one chosen object. 'Heal N' is a different production.",
        "golden": ["Heal a unit.", "Heal a friendly unit.", "Heal an enemy unit.", "Heal me.",
                   "Heal another unit.", "Heal another friendly unit.", "Heal it.", "Heal that unit."],
        "negative": ["Heal 2 damage from a unit.", "Heal all friendly units.", "Heal the strongest unit."],
    },
    {
        "production_id": "exhaust_selector",
        "form": "Exhaust <selector>.",
        "template": r"exhaust {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 417", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["exhaust", "targeting"],
        "boundary": "One chosen object is exhausted. A count or a rune selector is a different production.",
        "golden": ["Exhaust a unit.", "Exhaust a friendly unit.", "Exhaust an enemy unit.", "Exhaust me.",
                   "Exhaust another unit.", "Exhaust another friendly unit.", "Exhaust it.", "Exhaust that unit."],
        "negative": ["Exhaust 2 runes.", "Exhaust all enemy units.", "Exhaust the strongest unit."],
    },
    {
        "production_id": "recall_selector",
        "form": "Recall <selector>.",
        "template": r"recall {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 435", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["recall", "targeting"],
        "boundary": "One chosen object is sent to its controller's Base. Recall is not a Move (435.1).",
        "golden": ["Recall a unit.", "Recall a friendly unit.", "Recall an enemy unit.", "Recall me.",
                   "Recall another unit.", "Recall another friendly unit.", "Recall it.", "Recall that unit."],
        "negative": ["Recall a unit exhausted.", "Recall all friendly units.", "Recall the strongest unit."],
    },
    {
        "production_id": "buff_selector",
        "form": "Buff <selector>.",
        "template": r"buff {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 427.1", "Core 702"],
        "ast_node": "instruction",
        "required_capability": ["buff", "targeting"],
        "boundary": "One chosen Unit gets a Buff counter. A Unit that already has one is still chosen and is not Buffed again (427.1.c).",
        "golden": [
            "Buff a unit.", "Buff a friendly unit.", "Buff an enemy unit.", "Buff me.",
            "Buff another unit.", "Buff another friendly unit.", "Buff it.", "Buff that unit.",
        ],
        "negative": ["Buff all friendly units.", "Buff 2 units.", "Buff the strongest unit."],
    },
    {
        "production_id": "keyworded_ability",
        "form": "[<keyword>][>] <ability> — Core 135.2.e.7, 808.1.d",
        "template": r"{keyword}\[>\] (?P<inner>.+)",
        "slots": {"keyword": sorted(keyword_alternatives())},
        "normalization": N,
        "rule_locators": ["Core 135.2.e.7", "Core 808.1", "Core 808.2"],
        "ast_node": "keyworded_ability",
        "required_capability": ["keyword_catalogue_v1"],
        "boundary": "The binder makes the keyword the ability's trigger condition. Only a keyword the engine implements as a trigger compiles; the rest are known_unsupported, and an ability the grammar cannot read makes the whole clause unparsed.",
        # a Dependent Keyword (727.1) gates an ability form, not an instruction
        "golden": [f"[{printed_name(name)}][>] " + ("When you play me, draw 1." if name == "legion" else "Draw 1.")
                   for name in sorted(keyword_alternatives())],
        "negative": ["[Nonesuch][>] Draw 1.", "[Deathknell] Draw 1.", "[Deathknell][>] Summon a dragon."],
    },
    {
        "production_id": "object_keyword",
        "form": "[<keyword>] — a printed keyword on the object",
        "template": r"{keyword}",
        "slots": {"keyword": sorted(keyword_alternatives())},
        "normalization": N,
        "rule_locators": ["Core 813", "Core 814", "Core 815"],
        "ast_node": "keyword",
        "required_capability": ["keyword_catalogue_v1"],
        "boundary": "A bare printed keyword the catalogue names. One it does not name stays unparsed; one it names but the engine does not implement is known_unsupported, not parsed.",
        "golden": [f"[{printed_name(name)}]" for name in sorted(keyword_alternatives())],
        "negative": ["[Nonesuch]", "gains [Shield 2] this combat", "[Shield] and [Tank]"],
    },
]

LITERAL = [
    ("draw_n", r"draw (?P<count>\d+)", ["Core 414", "Core 432"], "instruction", ["draw"],
     "The controller draws. 'Each player draws' and 'draw until' are not this production.",
     ["Draw 1.", "Draw 2."], ["each player draws 1", "draw 1, then discard 1"]),
    # 2026-09-25 (Jinx - Loose Cannon): a draw conditioned on the controller's own hand size, read
    # as the instruction executes (effect_ir predicate state_holds)
    ("draw_n_if_you_have_one_or_fewer_cards_in_your_hand",
     r"draw (?P<count>\d+) if you have one or fewer cards in your hand",
     ["Core 414", "Core 359.3.d"], "instruction", ["draw", "condition_v1"],
     "A draw that happens only if the controller holds at most one card when it executes. Another count or zone is a different clause.",
     ["Draw 1 if you have one or fewer cards in your hand."],
     ["draw 1 if you have two or fewer cards in your hand", "draw 1 if an opponent has one or fewer cards in their hand", "draw 1"]),
    # 2026-09-27 (Kadregrin the Infernal): a draw counted as it executes - the printed number for
    # each unit its controller controls that is Mighty, Might 5 or greater (Core 708, 710)
    ("draw_n_for_each_of_your_mighty_units", r"draw (?P<count>\d+) for each of your \[mighty\] units",
     ["Core 414", "Core 708", "Core 710"], "instruction", ["draw"],
     "The controller draws the number times how many units they control are Mighty when it executes; none is no draw. "
     "Another quality, or another player's units, is a different clause.",
     ["Draw 1 for each of your [Mighty] units."],
     ["draw 1 for each of your units", "draw 1 for each enemy [mighty] unit", "draw 1 if you control a [mighty] unit"]),
    # 2026-09-25: the controller discards N from their own hand, chosen privately (Core 423.1);
    # a hand shorter than N discards what it has, an empty hand ignores it (423.4). Returned
    # now that ", then" no longer makes the next instruction depend on it (GPT 2026-09-25).
    ("discard_n", r"discard (?P<count>\d+)", ["Core 423.1", "Core 423.1.a", "Core 423.4"], "instruction",
     ["private_discard"],
     "The controller discards from their own hand. Discarding at random, or another player's discard, is a different production.",
     ["Discard 1.", "Discard 2."], ["discard 2 at random", "each player discards 1", "discard your hand"]),
    ("deal_n_to_a_unit_at_a_battlefield", r"deal (?P<amount>\d+) to a unit at (?:a )?battlefield",
     ["Core 418", "Core 355.9"], "instruction", ["deal_damage", "targeting"],
     "One chosen Unit at a Battlefield. A Might restriction on the target is a different production.",
     ["Deal 2 to a unit at a battlefield.", "Deal 3 to a unit at battlefield."],
     ["deal 2 to a unit at a battlefield with 3 [m] or less", "deal 2 to all units at a battlefield"]),
    # 2026-09-25 (The Syren): a chosen friendly Unit at a Battlefield goes to its own Base
    # 2026-10-06 package 9 (Kayn - Unleashed, GPT ruling 8): a printed statement - while the card has really moved
    # at least twice this turn, every Deal to it is prevented, combat damage included (Core 370, 418)
    ("if_i_have_moved_twice_this_turn_i_dont_take_damage", r"if i have moved twice this turn, i don't take damage",
     ["Core 370", "Core 205", "Core 418.6.c", "Core 421", "Core 124"], "passive", ["replacement_effects", "condition_v1"],
     "The card's own replacement: a Deal to it is prevented while it has made two or more real Moves this turn. A "
     "Recall is not a Move; a new object starts at zero. 'I don't take combat damage' or 'the first time ...' are "
     "different productions.",
     ["If I have moved twice this turn, I don't take damage."],
     ["if i have moved this turn, i don't take damage", "i don't take damage",
      "if i have moved twice this turn, i have +2 might"]),
    # set 2 (2026-10-29, Counter Strike): one Unit chosen as the spell is played; the next Deal to it this turn - any
    # source's - is prevented, once; unused, it ends with the turn (317.2.c). Bound to the identity chosen (124). Then a draw
    ("choose_a_unit_the_next_time_that_unit_would_be_dealt_damage_this_turn_prevent_it_draw_n",
     r"choose a unit\. the next time that unit would be dealt damage this turn, prevent it\. draw (?P<count>\d+)",
     ["Core 370", "Core 205", "Core 355.5", "Core 124", "Core 317.2.c", "Core 414"], "instruction",
     ["grant_replacement", "targeting"],
     "One Unit chosen at play; a one-use prevention of the next damage dealt to it this turn, then a draw. Another "
     "event ('would die'), another duration, a choice of a friendly or enemy unit, or no draw is a different production.",
     ["Choose a unit. The next time that unit would be dealt damage this turn, prevent it. Draw 1."],
     ["choose a friendly unit. the next time that unit would be dealt damage this turn, prevent it. draw 1",
      "choose a unit. the next time that unit would be dealt damage, prevent it. draw 1",
      "choose a unit. the next time that unit would die this turn, prevent it. draw 1"]),
    # 2026-10-06 package 9 (Highlander, GPT ruling 11): one friendly Unit chosen as the spell is played; the next time
    # it would die this turn, the death is replaced - all its damage removed, exhausted, recalled to its Base (a Recall
    # is not a Move) - once; unused, it ends with the turn (317.2.c). Bound to the identity chosen (124)
    ("choose_a_friendly_unit_the_next_time_it_would_die_this_turn_heal_exhaust_and_recall_it_instead",
     r"choose a friendly unit\. the next time it would die this turn, heal it, exhaust it, and recall it instead",
     ["Core 370", "Core 355.5", "Core 355.10.c", "Core 124", "Core 317.2.c"], "instruction",
     ["grant_replacement", "targeting"],
     "One friendly Unit chosen at play; a one-use death replacement granted to it for this turn. Another "
     "replacement ('kill this instead'), another duration, or an enemy Unit is a different production.",
     ["Choose a friendly unit. The next time it would die this turn, heal it, exhaust it, and recall it instead."],
     ["choose an enemy unit. the next time it would die this turn, heal it, exhaust it, and recall it instead",
      "choose a friendly unit. the next time it would die, heal it, exhaust it, and recall it instead",
      "heal it, exhaust it, and recall it"]),
    # 2026-10-08 package 10 (Teemo - Swift Scout, GPT ruling 1): the Legend lets its controller take the same Hide for N
    # Energy instead of the usual one Power of any Domain
    ("you_may_pay_energy_to_hide_a_card_with_hidden_instead_of_power_any",
     r"you may pay \[e(?P<energy>\d+)\] to hide a card with \[hidden\] instead of \[a\]",
     ["Core 811.1", "Core 356.1.a"], "passive", ["hide_action"],
     "A printed static of a Legend: its controller may take a Hide for the named Energy in place of the usual cost - one "
     "Hide, one cost, never both; other changes to a Hide's cost apply to the one chosen. Another keyword's cost, or an "
     "additional cost, is a different clause.",
     ["You may pay :rb_energy_1: to hide a card with [Hidden] instead of :rb_rune_rainbow:."],
     ["you may pay :rb_energy_1: to hide a card", "pay :rb_energy_1: to hide a card with [hidden] instead of :rb_rune_rainbow:",
      "you may pay :rb_energy_1: to play a card with [hidden] instead of :rb_rune_rainbow:"]),
    # 2026-10-08 package 10 (Teemo - Swift Scout): one unit of the named tag that the controller owns, chosen as the ability
    # is activated, from the board or the controller's own Champion Zone, into its owner's hand
    ("put_a_tag_unit_you_own_into_your_hand_from_your_champion_zone_or_the_board",
     r"put an? (?P<tag>[a-z][a-z'-]*) unit you own into your hand from your champion zone or the board",
     ["Core 133.8", "Core 108.3", "Core 355.10.a.1", "Core 124"], "instruction", ["return_to_hand", "targeting"],
     "One unit carrying the tag, owned (not merely controlled) by the controller, chosen from the board or the "
     "controller's own Champion Zone, goes to its owner's hand. A unit they control, another zone, or a card that is "
     "not a unit is a different production.",
     ["Put a Teemo unit you own into your hand from your Champion Zone or the board."],
     ["put a teemo unit you control into your hand from your champion zone or the board",
      "put a teemo unit you own into your hand from the board", "put a teemo card you own into your hand from your trash"]),
    # 2026-10-08 package 10 (Pack of Wonders): one of the controller's other gear, units or facedown cards, chosen as the
    # ability is activated, into its owner's hand
    ("return_another_friendly_gear_unit_or_facedown_card_to_its_owners_hand",
     r"return another friendly gear, unit, or facedown card to its owner's hand",
     ["Core 107.3", "Core 355.10.a.1", "Core 124"], "instruction", ["return_to_hand", "targeting"],
     "One object its controller controls other than the source - a Gear or a Unit on the board, or a card in a Facedown "
     "Zone - goes to its owner's hand. An enemy object, the source itself, or a Rune is a different production.",
     ["Return another friendly gear, unit, or facedown card to its owner's hand."],
     ["return another friendly gear or unit to its owner's hand", "return a friendly gear, unit, or facedown card to "
      "its owner's hand", "return another enemy gear, unit, or facedown card to its owner's hand"]),
    # 2026-10-08 package 10 (Sett - The Boss, GPT 2026-10-08 ruling 12): an optional death replacement of the card's own,
    # paid as it applies - Power of any Domain and the source exhausted
    ("when_a_buffed_unit_you_control_would_die_you_may_pay_a_and_exhaust_me_to_spend_its_buff_and_recall_it_exhausted_instead",
     r"when a buffed unit you control would die, you may pay \[a\] and exhaust me to spend its buff and recall it exhausted "
     r"instead",
     ["Core 370.1", "Core 370.1.b", "Core 372", "Core 702.2.b", "Core 356.1"], "passive", ["bounded_replacement", "kill"],
     "While the card is on the board, a buffed unit its controller controls that would die may instead lose its buff and "
     "go to its Base exhausted, if the controller pays a Power of any Domain and exhausts the card as it applies; declined "
     "or unpayable, the unit dies. An unbuffed unit, or another payment, is a different production.",
     ["When a buffed unit you control would die, you may pay :rb_rune_rainbow: and exhaust me to spend its buff and recall it exhausted instead."],
     ["when a buffed unit you control would die, you may pay [a] to recall it instead",
      "when a buffed unit you control would die, spend its buff and recall it exhausted instead"]),
    # 2026-10-13 package 11 (Sett - The Boss, its official errata text - package 10 had read the printed one): the same
    # optional, paid replacement, its unit healed, exhausted and recalled
    ("if_a_buffed_unit_you_control_would_die_you_may_pay_a_exhaust_me_and_spend_its_buff_to_heal_it_exhaust_it_and_recall_it_instead",
     r"if a buffed unit you control would die, you may pay \[a\], exhaust me, and spend its buff to heal it, exhaust it, "
     r"and recall it instead",
     ["Core 370.1", "Core 370.1.b", "Core 372", "Core 702.2.b", "Core 356.1"], "passive", ["bounded_replacement", "kill"],
     "While the card is on the board, a buffed unit its controller controls that would die may instead lose its buff, be "
     "healed, exhausted and recalled to its Base, if the controller pays a Power of any Domain and exhausts the card as it "
     "applies; declined or unpayable, the unit dies. The printed 2026 text (no heal), an unbuffed unit, or another "
     "payment is a different production.",
     ["If a buffed unit you control would die, you may pay :rb_rune_rainbow:, exhaust me, and spend its buff to heal it, exhaust it, and recall it instead."],
     ["when a buffed unit you control would die, you may pay [a] and exhaust me to spend its buff and recall it exhausted instead",
      "if a buffed unit you control would die, you may pay [a], exhaust me, and spend its buff to recall it instead",
      "if a buffed unit you control would die, you may pay [a], exhaust me, and spend its buff to heal it and recall it instead"]),
    # 2026-10-08 package 10 (Unlicensed Armory): Highlander's grant, optional and paid as it applies
    ("choose_a_friendly_unit_the_next_time_it_would_die_this_turn_you_may_pay_rune_to_heal_exhaust_and_recall_it_instead",
     r"choose a friendly unit\. the next time it would die this turn, you may pay \[rune:(?P<domain>[a-z]+)\] to heal it, "
     r"exhaust it, and recall it instead",
     ["Core 370", "Core 355.5", "Core 356.1", "Core 317.2.c"], "instruction", ["grant_replacement", "targeting"],
     "One friendly unit chosen as the ability is activated: the next time this turn it would die, its controller may pay "
     "one Power of the named Domain to heal, exhaust and recall it instead; declined or unpayable, it dies.",
     ["Choose a friendly unit. The next time it would die this turn, you may pay [rune:fury] to heal it, exhaust it, and recall it instead."],
     ["choose a friendly unit. the next time it would die this turn, heal it, exhaust it, and recall it instead",
      "choose an enemy unit. the next time it would die this turn, you may pay [rune:fury] to heal it, exhaust it, and recall it instead"]),
    # 2026-10-08 package 10 (Fox-Fire, GPT 2026-10-08 ruling 5): any number of units at one Battlefield, their Mights
    # together at most N as they are chosen; a group grown past it as it resolves is cut to a subset its controller keeps
    ("kill_any_number_of_units_at_a_battlefield_with_total_might_n_or_less",
     r"kill any number of units at a battlefield with total might (?P<total>\d+) or less",
     ["Core 355.11", "Core 355.11.a", "Core 355.11.b", "Core 355.13", "Core 418"], "instruction", ["kill", "targeting"],
     "Any number of units, all at one Battlefield, whose Mights add up to at most N as they are chosen, are killed; if "
     "their total has grown past N as it resolves, its controller keeps a subset of them within it, at one Battlefield "
     "(not necessarily the first). A count, or units anywhere, is a different production.",
     ["Kill any number of units at a battlefield with total Might 4 or less."],
     ["kill any number of units with total might 4 or less", "kill up to 2 units at a battlefield with total might 4 or less",
      "kill any number of units at a battlefield"]),
    # 2026-10-08 package 10 (Facebreaker): two targets that meet a requirement together (Core 355.11)
    ("stun_a_friendly_unit_and_an_enemy_unit_at_the_same_battlefield",
     r"stun a friendly unit and an enemy unit at the same battlefield",
     ["Core 424", "Core 355.11", "Core 355.11.a", "Core 355.11.b"], "instruction", ["stun", "targeting"],
     "One friendly and one enemy unit, both at one Battlefield as they are chosen, are Stunned; if they no longer stand "
     "together as it resolves, its controller keeps one of them. Two units of one side, or any Battlefield each, is a "
     "different production.",
     ["Stun a friendly unit and an enemy unit at the same battlefield."],
     ["stun a friendly unit and an enemy unit", "stun two enemy units at the same battlefield",
      "stun a unit at a battlefield"]),
    # 2026-10-08 package 10 (Guerilla Warfare): for the rest of the turn its controller's Hides cost nothing
    ("you_can_hide_cards_ignoring_costs_this_turn", r"you can hide cards ignoring costs this turn",
     ["Core 811.1", "Core 317.2.c"], "instruction", ["hide_action"],
     "For the rest of the turn its controller may take Hide actions without paying their cost. Playing cards ignoring "
     "costs, or a lasting effect, is a different production.",
     ["You can hide cards ignoring costs this turn."],
     ["you can play cards ignoring costs this turn", "you can hide cards ignoring costs",
      "opponents can hide cards ignoring costs this turn"]),
    # 2026-10-08 package 10 (Dr. Mundo - Expert): the controller recycles N cards of their own trash, chosen by them
    ("recycle_n_from_your_trash", r"recycle (?P<count>\d+) from your trash",
     ["Core 417.1", "Core 417.4", "Core 417.5"], "instruction", ["recycle"],
     "The controller picks N cards from their own Trash as it resolves and recycles them (several together: shuffled "
     "under the deck, per the locators); with fewer there, every one. 'Up to N', another player's trash, or a named card "
     "is a different production.",
     ["Recycle 3 from your trash."],
     ["recycle up to 3 from your trash", "recycle 3 from a trash", "recycle me from your trash"]),
    # 2026-10-12 package 11 (Forge of the Future): up to N cards of any players' trashes, chosen as it resolves
    ("recycle_up_to_n_cards_from_trashes", r"recycle up to (?P<count>\d+) cards from trashes",
     ["Core 417.1", "Core 417.5", "Core 417.6", "Core 355.13"], "instruction", ["recycle"],
     "The controller picks up to N cards from any players' trashes as it resolves - not targets (Core 417.6) - and each "
     "is recycled to its owner's deck; zero is allowed (355.13). 'From your trash', an exact N, or 'a card' is a different "
     "production.",
     ["Recycle up to 4 cards from trashes."],
     ["recycle up to 4 cards from your trash", "recycle 4 cards from trashes", "recycle up to 4 units from trashes"]),
    # 2026-10-08 package 10 (Karthus - Eternal): its controller's Deathknell triggers each trigger once more while it is
    # on the board; 2026-10-12 package 11: order-independent over simultaneous deaths (effect_ir.group_pending_triggers)
    ("your_deathknell_effects_trigger_an_additional_time",
     r"your \[deathknell\] effects trigger an additional time",
     ["Core 383.3", "Core 808.1.d.2", "Core 808.3"], "passive", ["self_death_triggers"],
     "A printed static: each Deathknell trigger of its controller's units triggers one additional time while the card is "
     "on the board as the deaths are noted (a copy of the trigger the game generated, never of a copy); dying with them "
     "at the same time still counts. An opponent's Deathknell, another death trigger, another keyword, or 'twice' is a "
     "different clause.",
     ["Your [Deathknell] effects trigger an additional time."],
     ["your [deathknell] effects trigger twice", "your [vision] effects trigger an additional time",
      "deathknell effects trigger an additional time"]),
    # 2026-10-08 package 10 (Imperial Decree): for the rest of this turn, every unit that takes damage is killed
    ("when_any_unit_takes_damage_this_turn_kill_it",
     r"when any unit takes damage this turn, kill it",
     ["Core 383.1", "Core 317.2", "Core 359.3.f.3"], "instruction", ["create_delayed_trigger", "watched_triggers"],
     "A delayed trigger that, until this turn ends, triggers every time a unit takes damage, and kills that unit. 'The "
     "next time', a friendly or enemy unit only, or a lasting one is a different production.",
     ["When any unit takes damage this turn, kill it."],
     ["when a unit takes damage, kill it", "the next time any unit takes damage this turn, kill it",
      "when any enemy unit takes damage this turn, kill it"]),
    # set 2 (2026-10-29, Sudden Storm): one unit at a Battlefield chosen at play; dealt the larger amount instead if it is
    # attacking as the spell resolves
    ("deal_n_to_a_unit_at_a_battlefield_if_its_attacking_deal_m_to_it_instead",
     r"deal (?P<amount>\d+) to a unit at a battlefield\. if it's attacking, deal (?P<more>\d+) to it instead",
     ["Core 355.5", "Core 359.3.d", "Core 418", "Core 466.2"], "instruction", ["deal_damage", "targeting"],
     "One unit at a Battlefield chosen at play, dealt the second amount instead of the first if it is attacking as the "
     "spell resolves - one Deal either way. Defending, another selector, or both amounts dealt is a different production.",
     ["Deal 2 to a unit at a battlefield. If it's attacking, deal 4 to it instead."],
     ["deal 2 to a unit at a battlefield. if it's defending, deal 4 to it instead",
      "deal 2 to a unit. if it's attacking, deal 4 to it instead",
      "deal 2 to a unit at a battlefield. if it's attacking, deal 4 to it"]),
    # set 2 (2026-10-29, Rally the Troops): a delayed trigger that, until this turn ends, triggers every time its
    # controller plays a unit, and buffs that unit; then a draw
    ("when_a_friendly_unit_is_played_this_turn_buff_it_draw_n",
     r"when a friendly unit is played this turn, buff it\. draw (?P<count>\d+)",
     ["Core 383.1", "Core 420.4.a", "Core 427", "Core 317.2", "Core 359.3.f.3"], "instruction",
     ["create_delayed_trigger", "watched_triggers"],
     "A delayed trigger that, until this turn ends, triggers every time its controller plays a unit, and buffs that unit; "
     "then a draw. 'The next time', an enemy unit, a lasting one, or no draw is a different production.",
     ["When a friendly unit is played this turn, buff it. Draw 1."],
     ["when a friendly unit is played, buff it. draw 1", "when an enemy unit is played this turn, buff it. draw 1",
      "the next time a friendly unit is played this turn, buff it. draw 1"]),
    # 2026-10-08 package 10 (Noxian Guillotine, GPT ruling 13): the chosen unit killed the next time it takes damage this
    # turn - or now instead, with Legion
    ("choose_a_unit_kill_it_the_next_time_it_takes_damage_this_turn_legion_kill_it_now_instead",
     # (the [Legion] marker is the card's keyword declaration; a body read with it split off still lowers here - the
     # "instead" half runs only while legion_active, which reads that keyword on the card itself, Core 812.3)
     r"choose a unit\. kill it the next time it takes damage this turn\. (?:\[legion\] (?:-|—) )?kill it now instead",
     ["Core 355.5", "Core 383.1", "Core 317.2", "Core 158.2", "Core 812.1.c"], "instruction",
     ["create_delayed_trigger", "watched_triggers", "targeting"],
     "One unit chosen at play. Without Legion, a one-shot delayed trigger bound to that unit kills it the next time it "
     "takes damage this turn; with Legion it is killed as the spell resolves instead and no delayed trigger is made.",
     ["Choose a unit. Kill it the next time it takes damage this turn. [Legion] — Kill it now instead."],
     ["choose a unit. kill it the next time it takes damage this turn",
      "choose a unit. kill it the next time it takes damage. [legion] — kill it now instead",
      "choose an enemy unit. kill it the next time it takes damage this turn. [legion] — kill it now instead"]),
    # 2026-10-08 package 10 (Shakedown, GPT ruling 7): one enemy unit chosen at play; as the Deal resolves, that unit's
    # controller lets it happen or has the caster draw instead
    ("choose_an_enemy_unit_deal_n_to_it_unless_its_controller_has_you_draw_n",
     r"choose an enemy unit\. deal (?P<amount>\d+) to it unless its controller has you draw (?P<draw>\d+)",
     ["Core 355.5", "Core 355.10.e", "Core 359.3.e.14"], "instruction", ["deal_damage", "targeting"],
     "One enemy Unit chosen at play is the Deal's target; as the Deal resolves, that Unit's controller either lets it "
     "happen or has the caster draw the named number instead, and then nothing is dealt. A choice by the caster, or a "
     "different 'instead', is a different production.",
     ["Choose an enemy unit. Deal 6 to it unless its controller has you draw 2."],
     ["choose an enemy unit. deal 6 to it unless you draw 2",
      "choose a friendly unit. deal 6 to it unless its controller has you draw 2",
      "deal 6 to it unless its controller has you draw 2"]),
    # set 2 package A2 (Card Sharp): each player's own optional Gold token, then one more Gold for its controller per
    # opponent who took one
    ("you_and_each_opponent_may_play_a_gold_gear_token_exhausted_for_each_opponent_who_did_you_play_one",
     r"you and each opponent may play a gold gear token exhausted\. for each opponent who did, you play a gold gear token "
     r"exhausted",
     ["Core 355.10.e", "Core 355.12", "Core 184", "Core 350.2"], "instruction", ["each_player", "play_token"],
     "Each player, its controller first and then in turn order, decides as it resolves whether to play a Gold gear token "
     "exhausted (each their own choice); then its controller plays one more Gold gear token exhausted for each opponent "
     "who played one. Each Gold is the catalogued token with its printed ability.",
     ["You and each opponent may play a Gold gear token exhausted. For each opponent who did, you play a Gold gear token "
      "exhausted."],
     ["each opponent may play a gold gear token exhausted. for each opponent who did, you play a gold gear token exhausted",
      "you and each opponent may play a gold gear token exhausted",
      "you and each opponent may play a gold gear token. for each opponent who did, draw 1"]),
    # set 2 package A2 (Strike Down): an equipped friendly unit and an enemy unit chosen at play; the first deals damage
    # equal to its Might to the second; then one Equipment is detached from the first
    ("choose_an_equipped_friendly_unit_it_deals_damage_equal_to_its_might_to_an_enemy_unit_then_detach",
     r"choose an equipped friendly unit\. it deals damage equal to its might to an enemy unit\. then detach an equipment "
     r"from it",
     ["Core 355.5", "Core 418.6.b.3", "Core 436.1", "Core 436.1.a", "Core 359.3.e.6"], "instruction",
     ["mutual_damage_current_might", "targeting", "detach"],
     "Two target slots chosen at play - a friendly Unit with an Equipment attached, and an enemy Unit anywhere on the "
     "board; the first deals damage equal to its current Might to the second (the Unit is the source); then one Equipment "
     "attached to the first is detached, its controller picking when there are several. Two-way damage, an enemy unit at a "
     "battlefield, or no detach is a different production.",
     ["Choose an equipped friendly unit. It deals damage equal to its Might to an enemy unit. Then detach an Equipment "
      "from it."],
     ["choose a friendly unit. it deals damage equal to its might to an enemy unit. then detach an equipment from it",
      "choose an equipped friendly unit. it deals damage equal to its might to an enemy unit",
      "choose an equipped friendly unit and an enemy unit. they deal damage equal to their mights to each other"]),
    # set 2 package A2 (Angle Shot): a unit and an Equipment of the same controller chosen at play; attach it to the unit or
    # detach it from the unit, chosen as it resolves; then draw
    ("choose_a_unit_and_an_equipment_with_the_same_controller_attach_or_detach_draw_n",
     r"choose a unit and an equipment with the same controller\. attach that equipment to that unit or detach that "
     r"equipment from that unit\. draw (?P<count>\d+)",
     ["Core 355.5", "Core 355.9", "Core 435.1", "Core 436.1", "Core 436.1.a"], "instruction",
     ["targeting", "attach", "detach"],
     "Two target slots chosen at play - a Unit on the board, and an Equipment on the board controlled by that Unit's "
     "controller; as it resolves its controller chooses to attach the Equipment to the Unit or to detach it from the Unit "
     "(nothing when it is not attached to that Unit); then they draw N. Units of different controllers, or a choice made "
     "at play, is a different production.",
     ["Choose a unit and an Equipment with the same controller. Attach that Equipment to that unit or detach that "
      "Equipment from that unit. Draw 1."],
     ["choose a unit and an equipment. attach that equipment to that unit or detach that equipment from that unit. draw 1",
      "choose a unit and an equipment with the same controller. attach that equipment to that unit. draw 1",
      "choose a unit and a gear with the same controller. attach that gear to that unit or detach that gear from that "
      "unit. draw 1"]),
    # set 2 package A2 (Marching Orders): Challenge's pair with its own two choices - a friendly unit anywhere on the board,
    # an enemy unit at a Battlefield
    ("choose_a_friendly_unit_anywhere_and_an_enemy_unit_at_a_battlefield_they_deal_damage_to_each_other",
     r"choose a friendly unit anywhere and an enemy unit at a battlefield\. they deal damage equal to their mights to each "
     r"other",
     ["Core 355.5", "Core 355.7", "Core 418.6.b"], "instruction", ["mutual_damage_current_might", "targeting"],
     "Two target slots chosen at play, a friendly Unit at any Location and an enemy Unit at a Battlefield; each deals "
     "damage equal to its own Might to the other. Two friendly units, an enemy unit anywhere, or a one-way Deal is a "
     "different production.",
     ["Choose a friendly unit anywhere and an enemy unit at a battlefield. They deal damage equal to their Mights to each "
      "other."],
     ["choose a friendly unit and an enemy unit. they deal damage equal to their mights to each other",
      "choose a friendly unit anywhere and an enemy unit anywhere. they deal damage equal to their mights to each other",
      "choose a friendly unit anywhere and an enemy unit at a battlefield. it deals damage equal to its might to the other"]),
    # 2026-10-06 package 9 (Convergent Mutation, GPT ruling 7): two different friendly Units chosen at play; at
    # resolution the first's Might is raised, this turn, to the second's - an increase only, read once
    ("choose_a_friendly_unit_this_turn_increase_its_might_to_the_might_of_another_friendly_unit",
     r"choose a friendly unit\. this turn, increase its might to the might of another friendly unit",
     ["Core 479.4.a", "Core 355.8", "Core 359.3.e.5", "Core 370.1.a"], "instruction",
     ["raise_might_to_match", "targeting"],
     "Two different friendly Units chosen at play; the first gets, this turn, the difference when the second's Might "
     "is higher, read once at resolution - never a decrease. 'Set its Might', an enemy Unit, or a lasting change is a "
     "different production.",
     ["Choose a friendly unit. This turn, increase its Might to the Might of another friendly unit."],
     ["choose a friendly unit. this turn, increase its might to the might of an enemy unit",
      "choose a friendly unit. increase its might to the might of another friendly unit",
      "this turn, increase its might to the might of another friendly unit"]),
    # 2026-10-06 package 9 (Portal Rescue, GPT ruling 2): a friendly Unit chosen at play is banished (a new object in
    # its owner's Banishment, Core 428), then its OWNER plays it - and so controls it (127.1, 420.1) - to their own
    # Base (355.2.b), its base cost's Energy and Power ignored (356.1.b.1), any additional cost offered as usual
    ("banish_a_friendly_unit_then_its_owner_plays_it_to_their_base_ignoring_its_cost",
     r"banish a friendly unit, then its owner plays it to their base, ignoring its cost",
     ["Core 428", "Core 420.3", "Core 127.1", "Core 420.1", "Core 355.2.b", "Core 356.1.b.1"], "instruction",
     ["banish", "limited_play", "targeting"],
     "One friendly Unit chosen at play, banished, then played by its owner to their Base ignoring its cost. 'You play "
     "it', 'here', or 'ignoring its Energy cost' are different productions.",
     ["Banish a friendly unit, then its owner plays it to their base, ignoring its cost."],
     ["banish a friendly unit, then play it to your base, ignoring its cost",
      "banish an enemy unit, then its owner plays it to their base, ignoring its cost",
      "banish a friendly unit, then its owner plays it, ignoring its energy cost"]),
    # set 2 package A2 (Ezreal - Dashing): the card's own statement - its Might is not part of its side's combat damage
    # (Core 467.2.a); it is still a combatant and is dealt damage as any other
    ("i_dont_deal_combat_damage", r"i don't deal combat damage",
     ["Core 467.2.a", "Core 467.2.b"], "passive", ["keyword_catalogue_v1"],
     "As its side's combat damage is summed, this unit contributes nothing (a Stunned unit's way, 424.1.b); it is still "
     "an attacker or defender, can be assigned damage and is dealt it. 'I don't take combat damage' or another unit's "
     "statement are different productions.",
     ["I don't deal combat damage."],
     ["i don't take combat damage", "friendly units don't deal combat damage", "i don't deal damage"]),
    # 2026-10-06 package 9 (Caitlyn - Patrolling, GPT ruling 4): the card's own statement of the Backline shape - an
    # attacker assigns it combat damage only after every other defender has lethal (Core 467.2.c.7)
    ("i_must_be_assigned_combat_damage_last", r"i must be assigned combat damage last",
     ["Core 467.2.c.7", "Core 365.1"], "passive", ["keyword_catalogue_v1"],
     "The card's own combat-damage order: last, as [Backline]. 'First' is [Tank]'s; another object's order is a "
     "different production.",
     ["I must be assigned combat damage last."],
     ["i must be assigned combat damage first", "other friendly units must be assigned combat damage last",
      "i must be assigned damage last"]),
    # 2026-10-06 package 9 (Caitlyn - Patrolling, GPT ruling 4): one chosen Unit at a Battlefield takes damage equal to
    # the source's Might as the instruction executes; a source no longer on the board has no Might, and nothing is dealt
    ("deal_damage_equal_to_my_might_to_a_unit_at_a_battlefield",
     r"deal damage equal to my might to a unit at (?:a )?battlefield",
     ["Core 418", "Core 355.9", "Core 359.3.e.12"], "instruction", ["deal_damage", "targeting"],
     "One chosen Unit at a Battlefield, of either side, takes damage equal to the source's Might when the instruction "
     "executes. 'An enemy unit here', 'its Might' or a printed number are different productions.",
     ["Deal damage equal to my Might to a unit at a battlefield."],
     ["deal damage equal to my might to an enemy unit here", "deal damage equal to its might to a unit at a battlefield",
      "deal 3 to a unit at a battlefield"]),
    # 2026-10-06 package 9 (Lee Sin - Ascetic, GPT ruling 12): the card's permission to be Buffed several times
    ("i_can_have_any_number_of_buffs", r"i can have any number of buffs",
     ["Core 427.1.b.2", "Core 702.3", "Core 703"], "passive", ["buff"],
     "The card itself may have any number of buffs; each adds +1 Might. Another unit's, or a number of buffs, is a "
     "different production.",
     ["I can have any number of buffs."],
     ["other friendly units can have any number of buffs", "i can have two buffs", "i can't be buffed"]),
    # 2026-10-06 package 9 (Nocturne - Horrifying): the card's own statement, working from its owner's Main Deck - seen
    # from the top by its owner, it may be banished, and then played for [A] once the effect that looked is done
    ("as_you_look_at_or_reveal_me_from_the_top_of_your_deck_banish_me_then_play_me_for_a",
     r"as you look at or reveal me from the top of your deck, you may banish me\. if you do, you may play me for \[a\]",
     ["Core 428", "Core 420.3", "Core 356.1.a", "Core 385.1"], "passive", ["banish", "limited_play"],
     "The card's own permission, from the top of its owner's Main Deck as its owner looks at or reveals it: banish it, "
     "and then play it for [A]. A draw is not a look; another card's, or another cost, is a different production.",
     ["As you look at or reveal me from the top of your deck, you may banish me. If you do, you may play me for :rb_rune_rainbow:."],
     ["as you draw me, you may banish me. if you do, you may play me for [a]",
      "as you look at or reveal me from the top of your deck, you may banish me",
      "as you look at me from the top of your deck, you may play me for [a]"]),
    # 2026-10-06 package 9 (The Grand Plaza): an effect that instructs its controller to win (Core 195); the game
    # ends at once (196)
    ("you_win_the_game", r"you win the game", ["Core 195", "Core 196"], "instruction", ["win_game"],
     "The instruction's controller wins and the game ends at once. 'You lose the game' and 'an opponent wins the "
     "game' are different productions.",
     ["You win the game."], ["you lose the game", "you win", "an opponent wins the game"]),
    # set 2 package A2 (Relentless Pursuit): a friendly unit moved, chosen at play with up to one Equipment of its
    # controller's; the attach optional as it resolves; then the unit has a conquer trigger this turn
    ("move_a_friendly_unit_attach_up_to_one_equipment_grant_conquer_move_to_base",
     r'move a friendly unit\. you may attach up to one equipment with the same controller to it\. this turn, that unit has '
     r'"when i conquer, you may move me to my base\."',
     ["Core 355.5", "Core 355.13", "Core 421", "Core 435", "Core 355.12", "Core 479.3", "Core 383.3.a"], "instruction",
     ["move_board_object", "attach", "grant_trigger"],
     "One friendly unit, and none or one Equipment its controller controls, chosen as the spell is played; the unit moves "
     "where its controller chooses; then its controller may attach the Equipment to it; then, this turn, it has the "
     "triggered ability 'When I conquer, you may move me to my base.' (its own, the 'you may' decided as that ability is "
     "finalized).",
     ['Move a friendly unit. You may attach up to one Equipment with the same controller to it. This turn, that unit has '
      '"When I conquer, you may move me to my base."'],
     ["move a friendly unit. you may attach up to one equipment with the same controller to it",
      'move an enemy unit. you may attach up to one equipment with the same controller to it. this turn, that unit has '
      '"when i conquer, you may move me to my base."',
      'move a friendly unit. this turn, that unit has "when i conquer, you may move me to my base."']),
    # set 2 package A2 (Azir - Ascendant): a unit its controller controls chosen as the ability is played; the source and
    # it swap locations (Tideturner's two Moves); then, if it carries Equipment, its controller may attach one of them to
    # the source - decided and picked as it resolves
    ("choose_a_unit_you_control_swap_with_me_attach_one_of_its_equipment_to_me",
     r"choose a unit you control\. move me to its location and it to my original location\. if it's equipped, you may "
     r"attach one of its equipment to me",
     ["Core 355.5", "Core 421", "Core 355.12", "Core 355.10", "Core 435", "Core 436.1.a"], "instruction",
     ["move_board_object", "attach", "targeting"],
     "One unit its controller controls is chosen as it is played; the source moves to that unit's location and that unit "
     "to the source's original one (the Tideturner pair, check_swap_locations); then its controller may attach one "
     "Equipment attached to that unit to the source, picked as it resolves when there are several - none attached, nothing "
     "happens.",
     ["Choose a unit you control. Move me to its location and it to my original location. If it's equipped, you may "
      "attach one of its Equipment to me."],
     ["choose a unit you control. move me to its location and it to my original location",
      "choose an enemy unit. move me to its location and it to my original location. if it's equipped, you may attach one "
      "of its equipment to me",
      "choose a unit you control. move me to its location and it to my original location. attach one of its equipment to "
      "me"]),
    # set 2 package A2 (The Zero Drive): the units its linked ability banished, each played ignoring its cost
    ("play_all_units_banished_with_this_ignoring_their_costs", r"play all units banished with this, ignoring their costs",
     ["Core 396", "Core 398", "Core 420.3", "Core 356.1.b.1"], "instruction", ["limited_play"],
     "Each unit card the source's linked ability banished, still in its owner's Banishment as that object, is played by "
     "this ability's controller ignoring its cost - one effect-driven play each. A unit banished by anything else is not.",
     ["Play all units banished with this, ignoring their costs."],
     ["play all units banished this turn, ignoring their costs", "play a unit banished with this, ignoring its cost",
      "play all units banished with this"]),
    # set 2 package A2 (Ezreal - Dashing): the source itself, to its controller's Base (Core 421, 355.4.a)
    # set 2 package A2 (Azir - Emperor of the Sands): one Sand Soldier unit token of the printed Might, to its controller's
    # Base (the eff_487 token, the eff_203 'to your base' place)
    ("play_a_n_might_sand_soldier_unit_token_to_your_base",
     r"play an? (?P<might>\d+) \[m\] sand soldier unit token to your base",
     ["Core 185.2.a", "Core 184.2"], "instruction", ["play_token"],
     "One Sand Soldier unit token of the printed Might, its controller's, in its controller's Base. Another token, 'here' "
     "or no place are different productions.",
     ["Play a 2 :rb_might: Sand Soldier unit token to your base."],
     ["play a 2 [m] sand soldier unit token here", "play a 3 [m] mech unit token to your base",
      "play a 2 [m] sand soldier unit token to a battlefield"]),
    ("move_me_to_your_base", r"move me to your base",
     ["Core 421", "Core 355.4.a"], "instruction", ["move_board_object"],
     "The source itself moves to its controller's Base; nothing is chosen. Another unit, 'its base', or a Battlefield "
     "destination are different productions.",
     ["Move me to your base."],
     ["move a friendly unit to your base", "move me to a battlefield", "move me"]),
    ("move_a_friendly_unit_at_a_battlefield_to_its_base", r"move a friendly unit at (?:a )?battlefield to its base",
     ["Core 421", "Core 355.4", "Core 355.4.a", "Core 355.9"], "instruction", ["move_board_object", "targeting"],
     "One chosen friendly Unit at a Battlefield moves to its own Base. A Unit in a Base, an enemy Unit, or "
     "'to or from its base' is a different production.",
     ["Move a friendly unit at a battlefield to its base."],
     ["move a friendly unit to its base", "move an enemy unit at a battlefield to its base",
      "move a friendly unit to or from its base"]),
    # set 2 package A2 (Jax - Grandmaster At Arms): an Equipment its controller controls, detached or attached, chosen with a
    # Unit its controller controls, and attached to it (Core 435, 355.5)
    # set 2 package A2 (Forge of the Fluft): while its controller controls it, each of their Legends has the [Exhaust]
    # ability (Core 190.6, 377)
    ("while_you_control_this_battlefield_friendly_legends_have_exhaust_attach_an_equipment",
     r'while you control this battlefield, friendly legends have (?:&quot;|")?:rb_exhaust:: attach an equipment you control to a unit you control\.?(?:&quot;|")?',
     ["Core 190.6", "Core 377", "Core 435"], "passive", ["attach", "targeting"],
     "The Battlefield's own text: while its controller controls it, each Legend of theirs has an [Exhaust] ability that "
     "attaches an Equipment they control to a Unit they control, both chosen as it is activated. An opponent's Legends, "
     "Units, or another ability are different clauses.",
     ["While you control this battlefield, friendly legends have &quot;:rb_exhaust:: Attach an Equipment you control to a unit you control.&quot;"],
     ["while you control this battlefield, friendly units have &quot;:rb_exhaust:: attach an equipment you control to a unit you control.&quot;",
      "friendly legends have &quot;:rb_exhaust:: attach an equipment you control to a unit you control.&quot;",
      "while you control this battlefield, enemy legends have &quot;:rb_exhaust:: attach an equipment you control to a unit you control.&quot;"]),
    ("attach_a_detached_or_attached_equipment_you_control_to_a_unit_you_control",
     r"attach an? (?P<state>detached|attached) equipment you control to a unit you control",
     ["Core 435", "Core 435.2.a", "Core 355.5"], "instruction", ["attach", "targeting"],
     "One Equipment its controller controls - attached to nothing now, or attached to a unit now - and one Unit its "
     "controller controls, both chosen; the Equipment is attached to that Unit (from any other it was attached to). An "
     "enemy Equipment, any Gear, or a unit chosen by another player is a different production.",
     ["Attach a detached Equipment you control to a unit you control.",
      "Attach an attached Equipment you control to a unit you control."],
     ["attach an equipment you control to a unit you control", "attach a detached equipment to a unit you control",
      "attach a detached gear you control to a unit you control"]),
    ("move_a_unit_from_a_battlefield_to_its_base", r"move a unit from (?:a )?battlefield to its base",
     ["Core 421", "Core 355.4", "Core 355.4.a", "Core 141.1.a.1", "Core 144.4.b", "Core 355.9.b", "Core 355.10.b"],
     "instruction", ["move_board_object", "targeting"],
     "One chosen Unit at a Battlefield, of either side, moves to its own Base (its controller's). A Unit in a "
     "Base is not a legal target; 'a friendly unit at a battlefield' is a different production.",
     ["Move a unit from a battlefield to its base."],
     ["move a unit to its base", "move a friendly unit from a battlefield to its base",
      "move a unit from a battlefield to your base"]),
    ("deal_n_to_all_enemy_units_at_a_battlefield", r"deal (?P<amount>\d+) to all enemy units at a battlefield",
     ["Core 418", "Core 355.10.b", "Core 715.2"], "instruction", ["deal_damage", "criteria_expansion"],
     "One chosen Battlefield, then every enemy Unit there.",
     ["Deal 3 to all enemy units at a battlefield."],
     ["deal 3 to all units at a battlefield", "deal 3 to all enemy units in combat"]),
    # GPT 2026-09-23: "here" - the resolving program's own source's current
    # Battlefield (Core 359.3.f.1, 359.3.f.2) - takes no decision at all,
    # unlike "at a battlefield"'s own Battlefield choice above. Anivia - Primal
    # is this production's real card (round 2 / D, when i attack).
    ("deal_n_to_all_enemy_units_here", r"deal (?P<amount>\d+) to all enemy units here",
     ["Core 418", "Core 355.10.b", "Core 715.2", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction",
     ["deal_damage", "criteria_expansion"],
     "The resolving program's own source's current Battlefield, read fresh at execution - not a decision.",
     ["Deal 3 to all enemy units here."],
     ["deal 3 to all enemy units at a battlefield", "deal 3 to all units here"]),
    # 2026-09-23, the single-target "here": ONE chosen enemy Unit, which must be at the
    # resolving program's own source's current Battlefield when it is chosen and when it
    # is used (Core 359.3.f.1, 359.3.f.2) - a target selector carrying location_ref.
    # Literal rows, not a selector alternative: the selector table is pinned by the
    # signed binding specs, and "here" is not a selector phrase in every production.
    # Crackshot Corsair, Leona - Determined and Ahri - Inquisitive are the real cards.
    # 2026-09-27 package 5 (Volibear - Furious): a split deal - the Targets chosen at finalization,
    # no more than the damage, each at the source's current Battlefield; the division at resolution
    ("deal_n_damage_split_among_any_number_of_enemy_units_here",
     r"deal (?P<amount>\d+) damage split among any number of enemy units here",
     ["Core 418", "Core 355.14", "Core 355.14.a", "Core 355.14.b", "Core 355.14.c", "Core 355.14.e",
      "Core 355.14.f", "Core 355.14.h", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction", ["deal_damage", "targeting"],
     ("Up to N chosen enemy Units at the source's current Battlefield, the N divided among them at resolution, a "
      "positive amount each. Damage to every enemy Unit here, one chosen Unit, a split at a chosen Battlefield, or a "
      "split whose amount is read off the board is a different production."),
     ["Deal 5 damage split among any number of enemy units here."],
     ["deal 5 damage split among any number of enemy units at a battlefield", "deal 5 to all enemy units here",
      "deal 5 to an enemy unit here", "deal damage equal to its might split among enemy units at battlefields"]),
    # 2026-10-13 package 11 (Twisted Fate - Gambler's Fury branch): one chosen enemy unit here, and every OTHER enemy
    # unit here found by criteria
    ("deal_n_to_an_enemy_unit_here_and_m_to_all_other_enemy_units_here",
     r"deal (?P<amount>\d+) to an enemy unit here and (?P<rest>\d+) to all other enemy units here",
     ["Core 418", "Core 355.9", "Core 355.10.d", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction",
     ["deal_damage", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield takes the first amount; every other enemy Unit there, "
     "found by criteria (none chosen), takes the second. Friendly units, or enemy units elsewhere, are untouched.",
     ["Deal 2 to an enemy unit here and 1 to all other enemy units here."],
     ["deal 2 to an enemy unit here and 1 to all enemy units here", "deal 2 to an enemy unit here",
      "deal 2 to an enemy unit at a battlefield and 1 to all other enemy units there"]),
    # 'it' bound inside the one sentence: the rune that reveal showed, still that object (recycle revealed_by)
    ("reveal_the_top_rune_of_your_rune_deck_then_recycle_it",
     r"reveal the top rune of your rune deck, then recycle it",
     ["Core 425", "Core 425.2", "Core 417", "Core 124"], "instruction", ["reveal", "recycle"],
     "The top card of its controller's Rune Deck is shown to all, its Domains noted, then that same rune goes to the "
     "bottom of its owner's Rune Deck. An empty Rune Deck reveals and recycles nothing.",
     ["Reveal the top rune of your rune deck, then recycle it."],
     ["reveal the top rune of your rune deck, then channel it", "reveal the top card of your main deck, then recycle it",
      "reveal the top 2 runes of your rune deck, then recycle them"]),
    ("reveal_the_top_rune_of_your_rune_deck", r"reveal the top rune of your rune deck",
     ["Core 425", "Core 425.2", "Core 105"], "instruction", ["reveal"],
     "The top card of its controller's Rune Deck is shown to all and stays where it is; its Domains are noted as it "
     "is revealed. An empty Rune Deck reveals nothing.",
     ["Reveal the top rune of your rune deck."],
     ["reveal the top card of your main deck", "reveal the top 2 runes of your rune deck", "channel the top rune"]),
    # 2026-10-13 package 11 (Mageseeker Warden, GPT ruling 17): two restrictions while the card is at a Battlefield
    ("while_im_at_a_battlefield_opponents_can_only_play_units_to_their_base",
     r"while i'm at a battlefield, opponents can only play units to their base",
     ["Core 355.2", "Core 358.3.a", "Core 358.5"], "passive", ["battlefield_restrictions"],
     "While the card is at a Battlefield, an opponent playing a Unit has only their Base as a valid location; an "
     "effect that would play an opponent's Unit to a Battlefield still resolves, and that play is skipped.",
     ["While I'm at a battlefield, opponents can only play units to their base."],
     ["while i'm at a battlefield, opponents can't play units", "opponents can only play units to their base",
      "while i'm at a battlefield, you can only play units to your base"]),
    # 2026-10-14 package 12 (Noxus Saboteur; the site owner's reading - a provisional reading, not a published ruling)
    ("your_opponents_hidden_cards_cant_be_revealed_here",
     r"your opponents' \[hidden\] cards can't be revealed here",
     ["Core 811.1", "Core 811.5.a", "Core 425"], "passive", ["battlefield_restrictions"],
     "While the card is at a Battlefield, its controller's opponents cannot play their facedown cards there (doing so "
     "would turn them face up); a facedown card that changes zones is still shown as it goes.",
     ["Your opponents' [Hidden] cards can't be revealed here."],
     ["your opponents' [hidden] cards can't be revealed", "your [hidden] cards can't be revealed here",
      "your opponents' cards can't be revealed here"]),
    ("while_im_at_a_battlefield_spells_and_abilities_cant_ready_enemy_units_and_gear",
     r"while i'm at a battlefield, spells and abilities can't ready enemy units and gear",
     ["Core 358.3.a", "Core 416"], "passive", ["battlefield_restrictions"],
     "While the card is at a Battlefield, a spell's or ability's instruction to ready an enemy Unit or Gear is "
     "skipped as it resolves; the Awaken Step still readies them.",
     ["While I'm at a battlefield, spells and abilities can't ready enemy units and gear."],
     ["spells and abilities can't ready enemy units and gear", "while i'm at a battlefield, enemy units can't ready",
      "while i'm at a battlefield, spells can't ready enemy units"]),
    ("deal_n_to_an_enemy_unit_here", r"deal (?P<amount>\d+) to an enemy unit here",
     ["Core 418", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction", ["deal_damage", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield. 'For each', a second target, or "
     "damage to all enemy Units here is a different production.",
     ["Deal 1 to an enemy unit here."],
     ["deal 1 to an enemy unit at a battlefield", "deal 1 to all enemy units here",
      "deal 1 to an enemy unit here for each card with [hidden]"]),
    # "equal to my Might": the amount is the source's current Might, read on execution
    # (Core 359.3.f.2's own Yasuo, Remorseful example, Stupefied in response); the target
    # is "an enemy unit here" as above.
    ("deal_damage_equal_to_my_might_to_an_enemy_unit_here", r"deal damage equal to my might to an enemy unit here",
     ["Core 418", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2", "Core 359.3.f.4"], "instruction",
     ["deal_damage", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield takes damage equal to the source's Might "
     "as it is when the instruction executes.",
     ["Deal damage equal to my Might to an enemy unit here."],
     ["deal damage equal to my might to an enemy unit", "deal 3 to an enemy unit here",
      "deal damage equal to its might to an enemy unit here"]),
    ("stun_an_enemy_unit_here", r"stun an enemy unit here",
     ["Core 424", "Core 424.1", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction", ["stun", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield becomes Stunned.",
     ["Stun an enemy unit here."],
     ["stun an enemy unit", "stun all enemy units here", "stun a unit here"]),
    ("give_an_enemy_unit_here_might_this_turn",
     r"give an enemy unit here (?P<sign>[+-])(?P<amount>\d+) \[m\] this turn(?:, to a minimum of (?P<floor>\d+) \[m\])?",
     ["Core 478", "Core 481", "Core 317.2", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction",
     ["modify_might", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield, a signed Might change this turn, with "
     "the floor the text states.",
     ["Give an enemy unit here -2 [M] this turn, to a minimum of 1 [M].", "Give an enemy unit here -1 [M] this turn.",
      "Give an enemy unit here +1 [M] this turn."],
     ["give an enemy unit -2 [m] this turn", "give enemy units here -2 [m] this turn",
      "give an enemy unit here -2 [m] this combat"]),
    ("deal_n_to_all_enemy_units_in_combat", r"deal (?P<amount>\d+) to all enemy units in combat",
     ["Core 418", "Core 715.2", "Core 462"], "instruction", ["deal_damage", "criteria_expansion", "combat_state"],
     "The Combat in progress. Outside one the instruction finds nothing.",
     ["Deal 2 to all enemy units in combat."],
     ["deal 2 to all enemy units at a battlefield", "deal 2 to all units in combat"]),
    ("deal_n_to_all_units_at_battlefields", r"deal (?P<amount>\d+) to all units at battlefields",
     ["Core 418", "Core 355.10.b"], "instruction", ["deal_damage", "criteria_expansion"],
     "Every Unit at every Battlefield, and none in a Base.",
     ["Deal 3 to all units at battlefields."],
     ["deal 3 to all enemy units at a battlefield", "deal 3 to all units at a battlefield"]),
    ("channel_n_rune_exhausted", r"channel (?P<count>\d+) runes? exhausted",
     ["Core 431", "Core 431.3"], "instruction", ["channel_rune"],
     "Entering exhausted. A Channel with no entry state is a different production.",
     ["Channel 1 rune exhausted."], ["channel 1 rune", "channel 1 rune ready"]),
    ("return_a_unit_from_your_trash_to_your_hand", r"return a unit from your trash to your hand",
     ["Core 416", "Core 124"], "instruction", ["return_to_hand", "targeting"],
     "A Unit, from the controller's own Trash.",
     ["Return a unit from your trash to your hand."],
     ["return a spell from your trash to your hand", "return a unit at a battlefield to its owner's hand"]),
    ("while_you_have_n_runes_i_have_might", r"while you have (?P<runes>\d+)\+ runes, i have \+(?P<amount>\d+) \[m\]",
     ["Core 364.3", "Core 478", "Core 481"], "conditional_might", ["continuous_effects", "condition_v1"],
     "A condition on the controller's own Runes on the board.",
     ["While you have 8+ runes, I have +4 [M]."],
     ["while i'm attacking or defending alone, i have +2 [m]", "while you have 8+ runes, i have [tank]"]),
    # 2026-09-27 package 5: a turn-long prohibition on the opponents' card plays (Brynhir
    # Thundersong). Cards are Main Deck cards (Core 052), so an activated ability is untouched;
    # Can't beats Can (054.1); it expires with the turn (317.2.c).
    ("opponents_cant_play_cards_this_turn", r"opponents can't play cards this turn",
     ["Core 054.1", "Core 052", "Core 317.2.c"], "instruction", ["grant_turn_effect"],
     ("A turn effect its controller creates: each opponent of that player can't play a card for the rest of "
      "the turn. The controller's own plays, an activated ability, a later turn, and a prohibition on one kind "
      "of card are outside it."),
     ["Opponents can't play cards this turn."],
     ["opponents can't play spells this turn", "you can't play cards this turn",
      "opponents can't play cards", "opponents can't activate abilities this turn"]),
    # 2026-09-27 (Fading Memories): one chosen permanent - a unit at a battlefield OR a gear - is granted
    # Temporary with no duration, so while it stays on the board (Core 816.1.a, 801.3.a.3)
    ("give_a_unit_at_a_battlefield_or_a_gear_temporary", r"give a unit at (?:a )?battlefield or a gear \[temporary\]",
     ["Core 816", "Core 816.1.a", "Core 801.3.a.3", "Core 355.9"], "instruction", ["grant_keyword", "targeting"],
     "One chosen object that is a unit at a battlefield or a gear anywhere on the board gains Temporary for as long "
     "as it stays there. A unit in a base, a duration, or another keyword is a different clause.",
     ["Give a unit at a battlefield or a gear [Temporary]."],
     ["give a unit or a gear [temporary]", "give a unit at a battlefield or a gear [temporary] this turn",
      "give a unit at a battlefield or a gear [tank]"]),
    ("units_you_play_this_turn_enter_ready", r"units you play this turn enter ready",
     ["Core 317.2", "Core 420.4"], "instruction", ["grant_turn_effect"],
     "Entry state for this turn's own plays.",
     ["Units you play this turn enter ready."],
     ["units you play this turn enter exhausted", "i enter ready"]),
    # 2026-09-27: delayed passives for the NEXT card of a kind played this turn, spent by that play
    # (Core 391.4, 392): a discount on the next spell's cost (356.4), and the next unit's entry state
    # set 2 package A2 (Temporal Portal): a [Repeat] for the next spell its controller plays this turn, its cost the spell's
    # printed cost (Core 820.1, 206); spent by that play, paid or not
    ("give_the_next_spell_you_play_this_turn_repeat_equal_to_its_cost",
     r"give the next spell you play this turn \[repeat\] equal to its cost",
     ["Core 391.4", "Core 392", "Core 820.1", "Core 206"], "instruction", ["grant_turn_effect"],
     "The next spell its controller plays this turn offers a [Repeat] whose cost is the spell's printed cost, chosen as it "
     "is played; spent by that play whether or not it is paid. Another card kind, or a fixed Repeat cost, is a different "
     "clause.",
     ["Give the next spell you play this turn [Repeat] equal to its cost."],
     ["give the next unit you play this turn [repeat] equal to its cost", "give the next spell you play this turn [repeat]",
      "give the next spell you play [repeat] equal to its cost"]),
    ("the_next_spell_you_play_this_turn_costs_n_less",
     r"the next spell you play this turn costs \[e(?P<amount>\d+)\] less",
     ["Core 391.4", "Core 392", "Core 356.4", "Core 356.6"], "instruction", ["grant_turn_effect"],
     "One discount of a fixed Energy amount on the next spell its controller plays this turn, spent by that play "
     "whether or not it lowered anything. Every spell, a Power amount, or a unit is a different clause.",
     ["The next spell you play this turn costs :rb_energy_5: less."],
     ["spells you play this turn cost :rb_energy_1: less", "the next unit you play this turn costs :rb_energy_2: less",
      "the next spell you play this turn costs :rb_rune_rainbow: less"]),
    # 2026-10-06 package 9 (Ravenborn Tome, GPT ruling 15): the first spell its controller plays after this, this turn -
    # each of that spell's own Deals gets +N (Core 713-715); spent by that play
    ("the_next_spell_you_play_this_turn_deals_n_bonus_damage",
     r"the next spell you play this turn deals (?P<amount>\d+) bonus damage",
     ["Core 391.4", "Core 392", "Core 713", "Core 714", "Core 715.1"], "instruction", ["grant_turn_effect"],
     "A Bonus Damage of N bound to the next spell its controller plays this turn: each of that spell's own Deals. Every "
     "spell, a unit, or 'your spells and abilities' is a different clause.",
     ["The next spell you play this turn deals 1 Bonus Damage."],
     ["your spells and abilities deal 1 bonus damage", "the next spell you play this turn costs :rb_energy_1: less",
      "the next unit you play this turn deals 1 bonus damage"]),
    ("the_next_unit_you_play_this_turn_enters_ready", r"the next unit you play this turn enters ready",
     ["Core 391.4", "Core 392", "Core 369.3", "Core 143.4"], "instruction", ["grant_turn_effect"],
     "The next unit its controller plays this turn enters ready: bound to that play as an entry replacement, "
     "then spent. Every unit this turn is 'Units you play this turn enter ready.'",
     ["The next unit you play this turn enters ready."],
     ["units you play this turn enter ready", "the next spell you play this turn enters ready",
      "the next unit you play this turn enters exhausted"]),
    ("self_cost_reduction_score",
     r"if an opponent's score is within (?P<within>\d+) points? of the victory score, this costs \[e(?P<amount>\d+)\] less",
     ["Core 356.4", "Core 194.1"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text, a fixed Energy amount, and the one condition leaf this wave registered. A reduction of Power, a variable amount, or a value read off the board is a different clause and stays unparsed.",
     ["If an opponent's score is within 3 points of the Victory Score, this costs :rb_energy_2: less."],
     ["if an opponent's score is within 3 points of the victory score, this costs :rb_rune_rainbow: less",
      "this spell's energy cost is reduced by the highest might among units you control",
      "i cost :rb_energy_2: less"]),
    # set 2 package A2 (Brutalizer [Effect Text]): more Might while the Equipment was attached to the card this turn
    ("attached_this_turn_more_might",
     r"if this was attached to me this turn, i have an additional \+(?P<amount>\d+) \[m\]",
     ["Core 435.1.c", "Core 479.4", "Core 364.3.a"], "passive", ["continuous_effects"],
     ("An Effect Text's conditional Might: while the Equipment it belongs to is attached to its Top-Most card by an "
      "attach made this turn. Another duration or another condition is a different clause."),
     ["If this was attached to me this turn, I have an additional +2 :rb_might:."],
     ["i have an additional +2 :rb_might:", "if this was attached to me, i have +2 :rb_might:",
      "if you attached an equipment this turn, i have an additional +2 :rb_might:"]),
    # set 2 package A2 (Skyfall of Areion [Effect Text]): the Top-Most card's hold and conquer abilities interchangeable
    ("my_hold_effects_are_also_conquer_effects_and_vice_versa",
     r"my hold effects are also conquer effects, and vice versa",
     ["Core 435.1.c", "Core 383.4.c", "Core 383.4.d"], "passive", ["continuous_effects"],
     ("An Effect Text: while it is its Top-Most card's, that card's own abilities that trigger when it holds also trigger "
      "when it conquers, and the other way round. One direction only, or another player's, is a different clause."),
     ["My hold effects are also conquer effects, and vice versa."],
     ["my hold effects are also conquer effects", "your hold effects are also conquer effects, and vice versa",
      "my conquer effects are also hold effects"]),
    # set 2 package A2 (Experimental Hexplate [Effect Text]): the card's own text gives it a tag (Core 133.8)
    ("i_am_a_tag", r"i am an? (?P<tag>mech|dragon|poro|yordle|sand soldier|recruit|bird|cat|dog|spirit)",
     ["Core 133.8"], "passive", ["continuous_effects"],
     "A tag the card's own text gives it, beside whatever tags it is printed with - as an Effect Text, its Top-Most card's.",
     ["I am a Mech."],
     ["i am mighty", "your units are mechs", "i am a unit"]),
    # set 2 package A2 (Void Drone, Drag Under): the same fixed reduction, only for a play whose source is not the hand
    ("self_cost_reduction_not_from_hand", r"i cost \[e(?P<amount>\d+)\] less to play from anywhere other than your hand",
     ["Core 356.4", "Core 350.1"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text and a fixed Energy amount, applied only when the card is played from somewhere other than its player's hand (a facedown zone, a trash, a deck); played from the hand it costs what it costs.",
     ["I cost :rb_energy_2: less to play from anywhere other than your hand."],
     ["i cost :rb_energy_2: less to play from your hand", "i cost :rb_energy_2: less to play from your trash",
      "i cost :rb_rune_rainbow: less to play from anywhere other than your hand"]),
    ("self_cost_reduction_fixed", r"i cost \[e(?P<amount>\d+)\] less",
     ["Core 356.4"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text and a fixed Energy amount. It is the ability a [Legion] gates (812.1.b.1); a variable amount, Power, or a value read off the board is a different clause.",
     ["I cost :rb_energy_2: less."],
     ["i cost :rb_rune_rainbow: less", "i cost [e] less", "units cost :rb_energy_2: less"]),
    # set 2 package A2 (Undertitan): as the card is revealed from its owner's Main Deck, its owner adds Energy
    ("as_im_revealed_from_your_deck_add_energy", r"as i'm revealed from your deck, \[add\] \[e(?P<amount>\d+)\]",
     ["Core 425", "Core 430", "Core 364.3"], "passive", ["continuous_effects"],
     "As a reveal instruction reveals this card from its owner's Main Deck, its owner adds the Energy to their Rune Pool. "
     "Looked at privately, or revealed from another zone, it adds nothing. Power, or another player's pool, is a different "
     "clause.",
     ["As I'm revealed from your deck, [Add] :rb_energy_2:."],
     ["as i'm revealed from your hand, [add] :rb_energy_2:", "when you reveal me, draw 1",
      "as i'm revealed from your deck, [add] :rb_rune_rainbow:"]),
    # set 2 package A2 (Ornn's Forge): a Battlefield's static - its controller's first non-token Gear each turn costs less
    ("while_you_control_this_battlefield_the_first_friendly_non_token_gear_played_each_turn_costs_n_less",
     r"while you control this battlefield, the first friendly non-token gear played each turn costs \[e(?P<amount>\d+)\] less",
     ["Core 356.4.b", "Core 420", "Core 190.6"], "passive", ["evaluated_cost_modifications"],
     "While its controller controls this Battlefield, the first non-token Gear card that player plays each turn costs the "
     "amount of Energy less. A token, a later Gear, or a Power discount is a different clause.",
     ["While you control this battlefield, the first friendly non-token gear played each turn costs :rb_energy_1: less."],
     ["while you control this battlefield, friendly gear costs :rb_energy_1: less",
      "the first friendly non-token gear played each turn costs :rb_energy_1: less",
      "while you control this battlefield, the first friendly unit played each turn costs :rb_energy_1: less"]),
    # set 2 package A2 (GPT A2 ruling 16): "[1] or [A] less" - one component, the payer's choice
    ("optional_additional_costs_you_pay_cost_energy_or_any_power_less",
     r"optional additional costs you pay cost \[e1\] or \[a\] less",
     ["Core 356.4.c", "Core 356.4.c.2", "Core 356.4.f", "Core 356.2.b"], "passive", ["evaluated_cost_modifications"],
     "Each optional additional cost its controller chooses to pay, on a card that player plays while this is on the board, "
     "costs one Energy or one Power less - the payer chooses which, on that cost's own Energy or Power, never both and "
     "never below 0. A mandatory cost, or every cost, is a different clause.",
     ["Optional additional costs you pay cost :rb_energy_1: or :rb_rune_rainbow: less."],
     ["optional additional costs you pay cost :rb_energy_1: less", "additional costs you pay cost :rb_energy_1: or "
      ":rb_rune_rainbow: less", "optional additional costs you pay cost :rb_energy_2: or :rb_rune_rainbow: less"]),
    ("your_spells_that_choose_me_cost_energy_or_any_power_less",
     r"your spells that choose me cost \[e1\] or \[a\] less",
     ["Core 356.4.c", "Core 356.4.c.2", "Core 355.5"], "passive", ["evaluated_cost_modifications"],
     "Each spell its controller plays that chooses this card costs one Energy or one Power less - the payer chooses which "
     "component of the spell's cost, never both and never below 0. A spell that does not choose it, or a unit, is not "
     "reduced.",
     ["Your spells that choose me cost :rb_energy_1: or :rb_rune_rainbow: less."],
     ["your spells cost :rb_energy_1: or :rb_rune_rainbow: less", "your spells that choose me cost :rb_energy_1: less",
      "your units that choose me cost :rb_energy_1: or :rb_rune_rainbow: less"]),
    # set 2 package A2 (Vex - Cheerless): a Unit's passive while it is in a Combat - its controller's spells cost less,
    # its opponents' spells more, each by one Energy and one Power of any Domain
    ("while_im_in_combat_friendly_spells_cost_less_enemy_spells_cost_more",
     r"while i'm in combat, friendly spells cost \[e(?P<less>\d+)\]\[a\] less to a minimum of \[e(?P<minimum>\d+)\], "
     r"and enemy spells cost \[e(?P<more>\d+)\]\[a\] more",
     ["Core 356.3", "Core 356.4", "Core 356.4.c", "Core 356.4.e", "Core 364.3.a"], "passive",
     ["evaluated_cost_modifications"],
     "While the Unit is in a Combat (designated an attacker or a defender), each spell its controller plays costs the "
     "Energy less, never below the minimum by this discount, and one Power of any Domain less (the payer chooses the "
     "Domain when the spell's cost has Power of more than one); each spell an opponent plays costs the Energy and one "
     "Power of any Domain more. Out of combat, nothing.",
     ["While I'm in combat, friendly spells cost :rb_energy_1::rb_rune_rainbow: less to a minimum of :rb_energy_1:, and "
      "enemy spells cost :rb_energy_1::rb_rune_rainbow: more."],
     ["while i'm at a battlefield, friendly spells cost :rb_energy_1::rb_rune_rainbow: less to a minimum of "
      ":rb_energy_1:, and enemy spells cost :rb_energy_1::rb_rune_rainbow: more",
      "while i'm in combat, friendly spells cost :rb_energy_1: less",
      "while i'm in combat, friendly units cost :rb_energy_1::rb_rune_rainbow: less to a minimum of :rb_energy_1:, and "
      "enemy units cost :rb_energy_1::rb_rune_rainbow: more"]),
    # set 2 package A2 (Renata Glasc - Chem-Baroness): while its controller's score is within N of the Victory Score,
    # each Add ability of a Gold token they control adds Energy more
    ("while_your_score_is_within_n_your_gold_add_an_additional_energy",
     r"while your score is within (?P<within>\d+) points of the victory score, your gold \[add\] an additional "
     r"\[e(?P<amount>\d+)\]",
     ["Core 364.3.a", "Core 430", "Core 187"], "passive", ["continuous_effects"],
     "While its controller's score is within N points of the Victory Score (read as each Add resolves), each Add ability "
     "of a Gold token that player controls adds the Energy more, beside what it prints. An opponent's score, another "
     "token's Add, or a Power bonus is a different clause.",
     ["While your score is within 3 points of the Victory Score, your Gold [ADD] an additional :rb_energy_1:."],
     ["while an opponent's score is within 3 points of the victory score, your gold [add] an additional :rb_energy_1:",
      "while your score is within 3 points of the victory score, your mechs [add] an additional :rb_energy_1:",
      "your gold [add] an additional :rb_energy_1:"]),
    # set 2 package A2 (Marai Spire): a Battlefield's static - its controller's [Repeat] costs cost less Energy
    ("while_you_control_this_battlefield_friendly_repeat_costs_cost_n_less",
     r"while you control this battlefield, friendly \[repeat\] costs cost \[e(?P<amount>\d+)\] less",
     ["Core 356.4.c", "Core 356.4.c.2", "Core 820.1", "Core 190.6"], "passive", ["continuous_effects"],
     "While its controller controls this Battlefield, each [Repeat] cost of a card that player plays has its Energy "
     "reduced by the amount, not below 0 (a discount on that one component). A Power discount, or every cost, is a "
     "different clause.",
     ["While you control this battlefield, friendly [Repeat] costs cost :rb_energy_1: less."],
     ["friendly [repeat] costs cost :rb_energy_1: less", "while you control this battlefield, spells cost :rb_energy_1: less",
      "while you control this battlefield, friendly [repeat] costs cost :rb_rune_rainbow: less"]),
    # set 2 package A2 (Tianna Crownguard): while the card is at a Battlefield, its controller's opponents gain no point
    ("while_im_at_a_battlefield_opponents_cant_gain_points", r"while i'm at a battlefield, opponents can't gain points",
     ["Core 054.1", "Core 473.1", "Core 364.3.a"], "passive", ["continuous_effects"],
     "While the card is at a Battlefield, its controller's opponents gain no point - from a Score (the battlefield is still "
     "scored and its Score abilities trigger), an instruction, or a Burn Out. Another player, another condition, or "
     "scoring prevented altogether is a different clause.",
     ["While I'm at a battlefield, opponents can't gain points."],
     ["opponents can't gain points", "while i'm at a battlefield, you can't gain points",
      "while i'm at a battlefield, opponents can't score"]),
    # set 2 package A2 (Ornn - Forge God): the card's own Might, more for each Gear its controller controls on the board
    ("i_have_n_might_for_each_friendly_gear", r"i have \+(?P<amount>\d+) \[m\] for each friendly gear",
     ["Core 479.4", "Core 479.4.b", "Core 364.3"], "dynamic_might", ["continuous_effects"],
     "A passive increase of the card's own Might by the amount for each Gear its controller controls on the board, "
     "computed fresh each time (479.4.b). Units, enemy Gear, or Gear off the board are a different clause.",
     ["I have +1 :rb_might: for each friendly gear."],
     ["i have +1 :rb_might: for each friendly unit", "i have +1 :rb_might: for each enemy gear",
      "i have +1 :rb_might:"]),
    ("my_might_is_increased_by_your_points", r"my might is increased by your points",
     ["Core 479.4", "Core 479.4.b", "Core 364.3"], "dynamic_might", ["continuous_effects"],
     "A passive increase of the card's own Might by its controller's points, computed fresh each time (479.4.b). Another quantity, or another object's Might, is a different clause.",
     ["My Might is increased by your points."],
     ["my might is increased by your opponent's points", "your units' might is increased by your points", "my might is doubled"]),
    ("self_cost_reduction_per_trash_card", r"i cost \[e(?P<amount>\d+)\] less for each card in your trash",
     ["Core 356.4", "Core 356.6"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text, a fixed Energy amount per card in its controller's trash; 356.6 keeps the Energy cost at 0 or above. Another zone, or a count of something else, is a different clause.",
     ["I cost :rb_energy_1: less for each card in your trash."],
     ["i cost :rb_energy_1: less for each card in your hand", "i cost :rb_energy_1: less for each unit you control"]),
    # 2026-09-27 package 5: a spell's own Energy reduction by a value read off the board as the
    # cost is determined - the highest Might among the Units its player controls (Core 356.4.e's
    # and 206's own example card). 1 per point, 0 with no Unit, never below 0 (356.6).
    # set 2 package A2 (Battering Ram): the card's own fixed Energy amount per card its player has played this turn,
    # stopping at the printed minimum (Core 356.4, 356.4.e, 420.4.b)
    ("self_cost_reduction_per_card_played",
     r"i cost \[e(?P<amount>\d+)\] less for each card you've played this turn, to a minimum of \[e(?P<minimum>\d+)\]",
     ["Core 356.4", "Core 356.4.e", "Core 420.4.b"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text: a fixed Energy amount per card its player has played this turn, the card being played not "
      "among them, never below the printed minimum. Another player's cards, spells only, or no minimum is a different "
      "clause."),
     ["I cost :rb_energy_1: less for each card you've played this turn, to a minimum of :rb_energy_1:."],
     ["i cost :rb_energy_1: less for each card your opponents have played this turn, to a minimum of :rb_energy_1:",
      "i cost :rb_energy_1: less for each spell you've played this turn, to a minimum of :rb_energy_1:",
      "i cost :rb_energy_1: less for each card you've played this turn"]),
    # set 2 package A2 (Jaull-Fish): the card's own fixed Energy amount per Mighty Unit its player controls on the board
    # (Core 356.4, 708), the count of Kadregrin the Infernal's draw
    ("self_cost_reduction_per_mighty_unit", r"i cost \[e(?P<amount>\d+)\] less for each of your \[mighty\] units",
     ["Core 356.4", "Core 356.6", "Core 708"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text: a fixed Energy amount per Mighty Unit (5+ Might) its player controls on the board, read as "
      "the cost is determined; 356.6 keeps it at 0 or above. An opponent's Units or a Power reduction is a different "
      "clause."),
     ["I cost :rb_energy_2: less for each of your [Mighty] units."],
     ["i cost :rb_energy_2: less for each of your opponents' [mighty] units",
      "i cost :rb_rune_body: less for each of your [mighty] units",
      "i cost :rb_energy_2: less for each of your units"]),
    # set 2 package A2 (Needlessly Large Yordle): the card's own Energy and one Power of a Domain per point its player
    # scored from Holding this turn (Core 356.4, 471.2, 473.1)
    ("self_cost_reduction_per_hold_point",
     r"i cost \[e(?P<amount>\d+)\]\[rune:(?P<domain>[a-z]+)\] less for each point you scored from holding this turn",
     ["Core 356.4", "Core 356.6", "Core 471.2", "Core 473.1"], "self_cost_reduction",
     ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text: a fixed Energy amount and one Power of the printed Domain per point its player gained by "
      "Holding this turn, read as the cost is determined; 356.6 keeps each at 0 or above. Points from Conquering, an "
      "opponent's points, or another count are different clauses."),
     ["I cost :rb_energy_2::rb_rune_calm: less for each point you scored from holding this turn."],
     ["i cost :rb_energy_2::rb_rune_calm: less for each point you scored from conquering this turn",
      "i cost :rb_energy_2::rb_rune_calm: less for each point your opponents scored from holding this turn",
      "i cost :rb_energy_2: less for each point you scored this turn"]),
    ("self_cost_reduction_highest_might",
     r"this spell's energy cost is reduced by the highest might among units you control",
     ["Core 356.4", "Core 356.4.b", "Core 356.4.e", "Core 356.6", "Core 355.9.a.1", "Core 206"],
     "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text: its Energy cost reduced by the highest Might among the Units its player controls on the "
      "board, read as the cost is determined. The sum of their Might, an opponent's Units, a Power reduction or a "
      "unit's printed Might are different clauses."),
     ["This spell's Energy cost is reduced by the highest Might among units you control."],
     ["this spell's energy cost is reduced by the highest might among units your opponents control",
      "this spell's energy cost is reduced by the total might of units you control",
      "this spell's power cost is reduced by the highest might among units you control"]),
    # 2026-09-27 package 5: a card's own fixed Energy reduction gated by a death this turn (Core
    # 356.4, 429.1): a Unit on the named side of its player died this turn.
    ("self_cost_reduction_unit_died",
     r"if an? (?P<relation>enemy|friendly) unit has died this turn, this costs \[e(?P<amount>\d+)\] less",
     ["Core 356.4", "Core 356.4.b", "Core 429.1", "Core 429.2.a"], "self_cost_reduction",
     ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text, a fixed Energy amount, gated by a Unit of the named side having died this turn - the "
      "side as it was when it died. A unit that died last turn, a unit that left the board another way, or a "
      "Power reduction is a different clause."),
     ["If an enemy unit has died this turn, this costs :rb_energy_2: less."],
     ["if an enemy unit has died this turn, this costs :rb_rune_rainbow: less",
      "if an enemy unit died last turn, this costs :rb_energy_2: less",
      "if an enemy unit has been banished this turn, this costs :rb_energy_2: less"]),
    # set 2 package A2 (Production Surge): a card's own fixed Energy reduction gated by its player controlling a Unit of a
    # printed tag on the board (Core 356.4, 356.4.b; controls_units with tag, read as the cost is determined)
    ("self_cost_reduction_control_tag",
     r"this costs \[e(?P<amount>\d+)\] less if you control an? (?P<tag>poro|dragon|mech)",
     ["Core 356.4", "Core 356.4.b"], "self_cost_reduction",
     ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text, a fixed Energy amount, gated by its player controlling a Unit of the named tag on the board "
      "as the cost is determined. A count of more than one, a tag on a Gear, or a Power reduction is a different clause."),
     ["This costs :rb_energy_2: less if you control a Mech."],
     ["this costs :rb_rune_rainbow: less if you control a mech",
      "this costs :rb_energy_2: less if you control two mechs",
      "this costs :rb_energy_2: less if an opponent controls a mech"]),
    # 2026-09-24: a unit's printed static aura - a continuous Might effect over the other
    # friendly units at its own Battlefield, read live off the object while it is on the
    # board (effect_ir.printed_aura_effects; check_static_auras.py).
    ("other_friendly_units_have_might_here",
     r"other friendly units have \+(?P<amount>\d+) \[m\] here",
     ["Core 365.1", "Core 478", "Core 479.4", "Core 481"], "passive", ["might_aura"],
     ("A printed aura: +N Might to every other friendly Unit at the Battlefield where the source is, while the "
      "source is on the board. Not a target, not snapshotted. A keyword instead of Might, a whole-board aura, "
      "or an aura on enemy units is a different clause."),
     ["Other friendly units have +1 :rb_might: here."],
     ["other friendly units have +2 :rb_might:", "other friendly units here have [assault]",
      "friendly units have +1 :rb_might: here", "stunned enemy units here have -8 :rb_might:"]),
    ("other_buffed_friendly_units_at_my_battlefield_have_might",
     r"other buffed friendly units at my battlefield have \+(?P<amount>\d+) \[m\]",
     ["Core 365.1", "Core 478", "Core 479.4", "Core 481", "Core 427.1.b"], "passive", ["might_aura"],
     ("The same aura restricted to Units with a Buff counter: a Unit that loses its Buff stops receiving it at "
      "once. An unbuffed or a whole-board variant is a different clause."),
     ["Other buffed friendly units at my battlefield have +2 :rb_might:."],
     ["other friendly units at my battlefield have +2 :rb_might:", "buffed friendly units have +2 :rb_might:",
      "other buffed friendly units have [deflect]"]),
    ("units_here_have_might",
     r"units here have \+(?P<amount>\d+) \[m\]",
     ["Core 365.1", "Core 190.6", "Core 478", "Core 479.4", "Core 481"], "passive", ["might_aura"],
     ("A Battlefield's printed aura: +N Might to every Unit at it, whoever controls it, while the Battlefield is "
      "in play. A keyword instead of Might, or 'friendly' / 'enemy' units, is a different clause."),
     ["Units here have +1 :rb_might:."],
     ["units here have [ganking]", "friendly units here have +1 :rb_might:", "units have +1 :rb_might:"]),
    # 2026-09-27 package 6: Recruit unit tokens played at the source's current Battlefield ("here",
    # location_ref read as it executes) - what a [Legion] over "When you play me, ..." needs to read
    ("play_n_might_recruit_unit_tokens_here",
     r"play (?P<count>a|two|three|four) (?P<might>\d+) \[m\] recruit unit tokens? here",
     ["Core 185.2", "Core 187.1", "Core 359.3.f.2"], "instruction", ["play_token"],
     ("One to four catalogued Recruit unit tokens (187.1) with the printed Might, each played at the Battlefield the "
      "program's source is at when it executes (359.3.f.2); none if it is not at one. 'In your base', a token "
      "without a place, or another token is a different clause."),
     ["Play two 1 :rb_might: Recruit unit tokens here.", "Play a 1 :rb_might: Recruit unit token here."],
     ["play two 1 :rb_might: recruit unit tokens into your base", "play two 1 :rb_might: recruit unit tokens",
      "play a 3 :rb_might: sprite unit token here", "play five 1 :rb_might: recruit unit tokens here"]),
    # 2026-09-27 package 6: a permanent's printed replacement on how the OTHER Units of its side
    # enter the board (369.3) - played cards and tokens alike - while it is on the board (365.1);
    # effect_ir.granted_entry_states, check_granted_entry_state.py
    ("other_friendly_units_enter_ready",
     r"other friendly units enter ready",
     ["Core 369.3", "Core 365.1", "Core 143.4"], "passive", ["entry_replacements"],
     ("While the source is on the board, each other Unit that enters the board under its controller's side - a "
      "Unit card played, or a Unit token - enters ready instead of exhausted (143.4). The source's own entry, an "
      "opponent's Units, a timed grant ('this turn'), or 'exhausted' is a different clause."),
     ["Other friendly units enter ready."],
     ["units you play this turn enter ready", "i enter ready", "other friendly units enter exhausted",
      "other units enter ready", "friendly units enter ready"]),
    # 2026-09-27 package 6: a printed decrease over the Stunned enemy units at the source's
    # Battlefield, with its own floor - re-applied each time Might is computed (a passive does not
    # snapshot, 479.4.b); effect_ir.printed_aura_effects, check_stunned_aura.py
    ("stunned_enemy_units_here_have_might_to_a_minimum",
     r"stunned enemy units here have -(?P<amount>\d+) \[m\], to a minimum of (?P<floor>\d+) \[m\]",
     ["Core 365.1", "Core 424.1.a", "Core 478", "Core 479.4", "Core 479.4.b", "Core 481"], "passive", ["might_aura"],
     ("A printed aura: -N Might, to a minimum of M, to every enemy Unit at the Battlefield where the source is that "
      "is Stunned right now (424.1.a), while the source is on the board. The floor is applied fresh each time the "
      "Might is computed (479.4.b). Friendly or unstunned units, a decrease without the floor, or a whole-board "
      "aura is a different clause."),
     ["Stunned enemy units here have -8 :rb_might:, to a minimum of 1 :rb_might:."],
     ["stunned enemy units here have -8 :rb_might:", "enemy units here have -8 :rb_might:, to a minimum of 1 :rb_might:",
      "stunned friendly units here have -8 :rb_might:, to a minimum of 1 :rb_might:",
      "stunned enemy units have -8 :rb_might:, to a minimum of 1 :rb_might:"]),
    # 2026-09-27: printed keyword auras - a keyword granted in the Ability layer (479.3, 479.3.b),
    # read live off the source (effect_ir.printed_aura_effects; check_keyword_auras.py). Each
    # admits only the keywords its gate exercises.
    ("units_here_have_keyword",
     r"units here have \[(?P<keyword>ganking)\]",
     ["Core 365.1", "Core 190.6", "Core 478", "Core 479.3", "Core 479.3.b", "Core 810.1.b"], "passive", ["might_aura", "layer_engine"],
     ("A Battlefield's printed keyword aura: every Unit at it, whoever controls it, has the keyword while it is "
      "there. A Might amount, 'friendly' / 'enemy' units, a keyword with a value, or a timed grant is a different clause."),
     ["Units here have [Ganking]."],
     ["units here have +1 :rb_might:", "friendly units here have [ganking]", "units have [ganking]",
      "units here have [ganking] this turn"]),
    # set 2 package A2 (Guardian Angel [Effect Text]): two printed sentences, one Replacement Effect about the Top-Most card
    ("if_i_would_die_kill_this_equipment_instead_heal_exhaust_recall_me",
     r"if i would die, kill (?P<name>[a-z' ]+) instead\. heal me, exhaust me, and recall me",
     ["Core 370.1.b", "Core 435.1.c", "Core 429", "Core 416"], "passive", ["replacement_effects"],
     ("An Effect Text: the Top-Most card's death is replaced - the Equipment the text belongs to is killed instead, and "
      "the card is healed, exhausted and recalled. The card the name points at is the Equipment itself; a death of "
      "another unit, or a different instead, is a different clause."),
     ["If I would die, kill Guardian Angel instead. Heal me, exhaust me, and recall me."],
     ["if a friendly unit would die, kill this instead. heal me, exhaust me, and recall me",
      "if i would die, kill guardian angel instead", "if i would die, heal me, exhaust me, and recall me instead"]),
    # set 2 package A2 (Gearhead): the printed Might Bonus of each Equipment attached to the card counted twice
    ("each_equipment_attached_to_me_gives_double_its_base_might_bonus",
     r"each equipment attached to me gives double its base might bonus",
     ["Core 159.1", "Core 435.1", "Core 479.4"], "passive", ["might_aura", "layer_engine"],
     ("The card's own text: each Equipment attached to it adds twice its printed Might Bonus instead of once, while the "
      "card's text is active. Another multiplier, another card's Equipment, or gear that is not Equipment is a different "
      "clause."),
     ["Each Equipment attached to me gives double its base Might bonus."],
     ["each equipment attached to me gives its base might bonus", "each equipment you control gives double its base "
      "might bonus", "each gear attached to me gives double its base might bonus"]),
    # set 2 package A3 (Svellsongur): its Effect Text a copy of its Top-Most card's printed text while attached
    ("as_this_is_attached_copy_that_units_text_to_its_effect_text",
     r"as this is attached to a unit, copy that unit's text to this equipment's effect text for as long as this is "
     r"attached to it",
     ["Core 435.1", "Core 479.1.b", "Core 479.1.d", "Core 479.3.c"], "passive", ["layer_engine"],
     ("The card's own text: while it is attached, its Effect Text is a copy of its Top-Most card's printed text (copyable "
      "traits only - nothing appended or granted, not Might), appended back to that card. A copy of another object, of "
      "traits other than text, or one that outlasts the attachment is a different clause."),
     ["As this is attached to a unit, copy that unit's text to this Equipment's effect text for as long as this is "
      "attached to it."],
     ["as this is attached to a unit, copy that unit's might to this equipment", "copy that unit's text to this "
      "equipment's effect text", "as this is attached to a unit, copy that unit's text to this equipment's effect text "
      "this turn"]),
    # set 2 package A2 (Jax - Unmatched): Quick-Draw given to the controller's Equipment wherever each is
    ("your_equipment_everywhere_have_quick_draw",
     r"your equipment everywhere have \[quick-draw\]",
     ["Core 365.1", "Core 479.3", "Core 819.1.b", "Core 819.1.d"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every Equipment its controller controls or owns, in any zone (a card in the hand "
      "included), while the source is on the board: each has Quick-Draw - Reaction timing, and the attach as it is "
      "played. Another keyword, enemy Equipment, or only the board is a different clause."),
     ["Your Equipment everywhere have [Quick-Draw]."],
     ["your equipment have [quick-draw]", "your gear everywhere have [quick-draw]",
      "your equipment everywhere have [assault]"]),
    # set 2 package A2 (Shurelya's Requiem [Effect Text]): the same aura with the source itself among the Units
    ("your_units_here_have_keyword",
     r"your units here have \[(?P<keyword>ganking|assault|shield|vision|deflect|tank)\]",
     ["Core 365.1", "Core 478", "Core 479.3", "Core 479.3.b"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every friendly Unit at the Battlefield where the source is - the source included - "
      "while the source is on the board. A Might amount, other units only, or a whole-board aura is a different clause."),
     ["Your units here have [Ganking]."],
     ["other friendly units here have [ganking]", "your units have [ganking]", "your units here have +1 :rb_might:"]),
    ("other_friendly_units_here_have_keyword",
     r"other friendly units here have \[(?P<keyword>assault|shield)\]",
     ["Core 365.1", "Core 478", "Core 479.3", "Core 479.3.b", "Core 807.2", "Core 814.2"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every other friendly Unit at the Battlefield where the source is, while the source "
      "is on the board; values are summed with the Unit's own (807.2, 814.2). A Might amount, the source itself, "
      "a whole-board aura or a keyword with a value is a different clause."),
     ["Other friendly units here have [Assault].", "Other friendly units here have [Shield]."],
     ["other friendly units here have +1 :rb_might:", "friendly units here have [assault]",
      "other friendly units have [assault]", "other friendly units here have [assault 2]"]),
    # 2026-10-08 package 10 (Spirit's Refuge): a keyword aura over friendly buffed Units that gives the keyword only to
    # one that does not otherwise have it - never a second instance summed onto its own
    ("friendly_buffed_units_have_keyword_if_they_didnt_already",
     r"friendly buffed units have \[(?P<keyword>deflect)\] if they didn't already",
     ["Core 365.1", "Core 479.3", "Core 479.3.b", "Core 702.2.a"], "passive", ["might_aura", "layer_engine", "buff_counters"],
     ("A printed keyword aura over the friendly Units that have a buff, while the source is on the board: each that does "
      "not otherwise have the keyword gets it; one that already has it keeps exactly its own. 'Other', an unbuffed set, or "
      "an aura that adds on top is a different clause."),
     ["Friendly buffed units have [Deflect] if they didn't already."],
     ["friendly buffed units have [deflect]", "friendly units have [deflect] if they didn't already",
      "other friendly buffed units have [deflect] if they didn't already"]),
    # set 2 (2026-10-29): a keyword aura over every friendly Unit on the board - "other" not printed, so a source that
    # is a Unit is covered too (a Gear printing it covers the Units only)
    # set 2 package A2 (Rumble - Mechanized Menace, Breakneck Mech, Forecaster, Rumble - Hotheaded): a keyword aura over
    # every Unit of one tag its controller controls on the board, the source too when it carries the tag
    # set 2 package A2 (Azir - Emperor of the Sands): the same keyword aura over the friendly Units of a NAME - the
    # Sand Soldier token's (it carries no Sand Soldier tag; TOKEN_ENTRY_SAND_SOLDIER: Shurima)
    ("your_named_units_have_keywords",
     r"your (?P<name>sand soldier)s have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 365.1", "Core 478", "Core 479.3", "Core 479.3.b", "Core 185.2.a"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura, while the source is active, over every friendly Unit of that name (the Sand Soldier "
      "token). Another name, a tag, enemy units or 'here' is a different clause."),
     ["Your Sand Soldiers have [Weaponmaster]."],
     ["your mechs have [weaponmaster]", "enemy sand soldiers have [weaponmaster]", "your sand soldiers here have [shield]"]),
    ("your_tag_units_have_keywords",
     r"your (?P<tag>mech)s (?:each )?have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 365.1", "Core 478", "Core 479.3", "Core 479.3.b", "Core 133.8"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura, while the source is on the board, over every friendly Unit carrying the tag - the "
      "source itself when it does. Another tag, enemy units, 'other' or 'here' is a different clause."),
     ["Your Mechs have [Shield].", "Your Mechs have [Deflect] and [Ganking].", "Your Mechs each have [Assault]."],
     ["your poros have [shield]", "enemy mechs have [shield]", "your other mechs have [shield]",
      "your mechs here have [shield]"]),
    # set 2 package A2 (Rumble - Scrapper: "... (including me)."): the same aura, a Might amount
    ("your_tag_units_have_might", r"your (?P<tag>mech)s have \+(?P<amount>\d+) \[m\]",
     ["Core 365.1", "Core 478", "Core 479.4", "Core 481", "Core 133.8"], "passive", ["might_aura"],
     ("A printed aura: +N Might to every friendly Unit carrying the tag while the source is on the board, the source "
      "itself when it does. Another tag, a decrease or 'here' is a different clause."),
     ["Your Mechs have +1 :rb_might:."],
     ["your poros have +1 :rb_might:", "your mechs have -1 :rb_might:", "your mechs here have +1 :rb_might:"]),
    # set 2 package A2 (Forgotten Monument): no player scores here before beginning their Nth turn (Core 471, 472)
    ("players_cant_score_here_until_their_nth_turn", r"players can't score here until their (?P<nth>second|third|fourth) turn",
     ["Core 471", "Core 472", "Core 190.6"], "passive", ["move_restriction"],
     ("A Battlefield's printed restriction on Scoring there: a player whose Nth turn has not begun gets no point and no "
      "Score trigger from conquering or holding it; control is established as usual."),
     ["Players can't score here until their third turn."],
     ["players can't score here", "you can't score here until your third turn", "players can't score until their third turn"]),
    # set 2 package A2 (Perched Grimwyrm): the card's only legal location, a Battlefield its player conquered this turn
    ("play_me_only_to_a_battlefield_you_conquered_this_turn", r"play me only to a battlefield you conquered this turn",
     ["Core 355.2", "Core 471.1"], "passive", ["move_restriction"],
     ("The card's own entry restriction: it may be played only to a Battlefield its player conquered this turn - not its "
      "Base, not another Battlefield, whatever permission would otherwise reach one."),
     ["Play me only to a battlefield you conquered this turn."],
     ["play me only to a battlefield you control", "play me to a battlefield you conquered this turn",
      "play me only to a battlefield you held this turn"]),
    # set 2 package A2 (Rockfall Path): a Battlefield's own restriction - no Unit is played there (Core 355.2)
    ("units_cant_be_played_here", r"units can't be played here",
     ["Core 355.2", "Core 190.6"], "passive", ["move_restriction"],
     ("A Battlefield's printed restriction: no Unit, either player's, may be played to it, whatever permission would "
      "otherwise reach it. A Move there, or a Gear, is not restricted by it."),
     ["Units can't be played here."],
     ["units can't move here", "spells can't be played here", "enemy units can't be played here"]),
    # set 2 package A2 (Lucian - Purifier): each attached Equipment of the controller's gives its unit [Assault]
    ("your_equipment_each_give_assault", r"your equipment each give \[assault\]",
     ["Core 807.1", "Core 807.2", "Core 435", "Core 365.1"], "passive", ["might_aura", "layer_engine"],
     ("A printed aura: while the source is on the board, every Equipment its controller controls that is attached "
      "gives the unit it is attached to one Assault - two Equipment, Assault 2 (807.2). Another keyword, or 'your units', "
      "is a different clause."),
     ["Your Equipment each give [Assault]."],
     ["your equipment each give [shield]", "your units each have [assault]", "your equipment have [assault]"]),
    # set 2 package A2 (Minotaur Reckoner): while the card is on the board, no Unit moves to a Base (Core 144.4, 359.3.e.6)
    ("units_cant_move_to_base", r"units can't move to base",
     ["Core 144.4", "Core 359.3.e.6", "Core 365.1"], "passive", ["move_restriction"],
     ("A printed restriction of a permanent: while it is on the board, no Unit, either player's, may move to a Base - a "
      "Standard Move to one is not an action, a Move instruction to one is ignored. 'From here' (a Battlefield's own "
      "restriction) is a different clause."),
     ["Units can't move to base."],
     ["units can't move from here to base", "units can't move to a battlefield", "enemy units can't move to base"]),
    # set 2 package A2 (Ruin Runner): an opponent's spells and abilities may not choose the card (Core 355.5)
    ("i_cant_be_chosen_by_enemy_spells_and_abilities", r"i can't be chosen by enemy spells and abilities",
     ["Core 355.5", "Core 355.9", "Core 365.1"], "passive", ["targeting"],
     ("A printed restriction of the card's own: a choice made for an opponent's spell or ability cannot name it, while "
      "its own controller's may. Every spell, or 'abilities' alone, is a different clause."),
     ["I can't be chosen by enemy spells and abilities."],
     ["i can't be chosen by spells and abilities", "i can't be chosen by enemy spells",
      "friendly units can't be chosen by enemy spells and abilities"]),
    ("friendly_units_have_keyword",
     r"friendly units have \[(?P<keyword>deflect)\]",
     ["Core 365.1", "Core 478", "Core 479.3", "Core 479.3.b"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every friendly Unit on the board while the source is there. 'Other', 'here', "
      "enemy units, or another keyword is a different clause."),
     ["Friendly units have [Deflect]."],
     ["other friendly units have [deflect]", "friendly units here have [deflect]", "enemy units have [deflect]",
      "friendly units have [tank]"]),
    # set 2 (2026-10-29, Renata Glasc - Industrialist): every Unit token its controller's side makes enters ready
    ("your_tokens_enter_ready", r"your tokens enter ready",
     ["Core 369.3", "Core 365.1", "Core 143.4", "Core 187.1"], "passive", ["entry_replacements"],
     ("A replacement the permanent applies, while it is on the board, to the entry of each Unit token its controller's "
      "side makes (a Gear token enters ready anyway). A card played that is not a token, or 'other friendly units', is a "
      "different clause."),
     ["Your tokens enter ready."],
     ["other friendly units enter ready", "your tokens enter exhausted", "your units enter ready"]),
    # set 2 (2026-10-29, Void Hatchling): before its controller reveals from the top of a deck, a look and a recycle
    ("if_you_would_reveal_cards_from_a_deck_look_at_the_top_card_first_you_may_recycle_it_then_reveal_those_cards",
     r"if you would reveal cards from a deck, look at the top card first\. you may recycle it\. then reveal those cards",
     ["Core 370.1", "Core 425", "Core 417", "Core 128.4"], "passive", ["continuous_effects", "replacement_effects"],
     ("While the card is on the board, each time its controller would reveal cards from the top of a deck - theirs or "
      "another player's - they first look at its top card, may recycle it, and then reveal from the deck as it is. "
      "A hand reveal, a look, or an opponent's reveal is a different clause."),
     ["If you would reveal cards from a deck, look at the top card first. You may recycle it. Then reveal those cards."],
     ["if you would look at cards from a deck, look at the top card first", "if an opponent would reveal cards from a deck, "
      "look at the top card first. you may recycle it. then reveal those cards", "if you would reveal your hand, look at it first"]),
    # set 2 (2026-10-29, Soraka - Wanderer): Core 374's own example as printed
    ("if_another_unit_you_control_here_would_die_if_it_has_less_might_than_me_instead_heal_exhaust_and_recall_it",
     r"if another unit you control here would die, if it has less might than me, instead heal it, exhaust it, and recall it",
     ["Core 370.1", "Core 374", "Core 429", "Core 416", "Core 411"], "passive", ["continuous_effects", "replacement_effects"],
     ("While the card is on the board, the death of another Unit its controller controls at the same location with less "
      "Might than the card is replaced: that Unit is healed, exhausted and recalled. An enemy unit, equal Might, or "
      "another location is a different clause."),
     ["If another unit you control here would die, if it has less Might than me, instead heal it, exhaust it, and recall it."],
     ["if another unit you control would die, instead heal it, exhaust it, and recall it",
      "if another unit you control here would die, if it has more might than me, instead heal it, exhaust it, and recall it",
      "if an enemy unit here would die, if it has less might than me, instead heal it, exhaust it, and recall it"]),
    # set 2 (2026-10-29, Rek'Sai - Breacher): a keyword the card's side's Units have while played from elsewhere
    ("friendly_units_played_from_anywhere_other_than_a_players_hand_have_keyword",
     r"friendly units played from anywhere other than a player's hand have \[(?P<keyword>accelerate)\]",
     ["Core 365.1", "Core 805.1.b", "Core 805.2.a", "Core 805.3"], "passive", ["continuous_effects", "layer_engine"],
     ("While the card is on the board, a Unit its controller's side plays from any zone but a hand - a Trash, a "
      "Banishment, a Champion Zone, the top of a deck - has the keyword while it is played, so its optional cost is "
      "offered; from a hand, nothing. Units on the board, or every friendly unit, is a different clause."),
     ["Friendly units played from anywhere other than a player's hand have [Accelerate]."],
     ["friendly units have [accelerate]", "friendly units played from your hand have [accelerate]",
      "enemy units played from anywhere other than a player's hand have [accelerate]"]),
    # set 2 (2026-10-29, Ancient Warmonger): a summed keyword valued by a count, as the board is now
    ("i_have_assault_equal_to_the_number_of_enemy_units_here",
     r"i have \[assault\] equal to the number of enemy units here",
     ["Core 365.1", "Core 479.3", "Core 807.1.c", "Core 807.2", "Core 479.4.b"], "passive",
     ["continuous_effects", "layer_engine"],
     ("The card's own Assault, one instance for each enemy Unit at the Battlefield it is at, read as the board is now; "
      "none in a Base. Friendly units, or another keyword, is a different clause."),
     ["I have [Assault] equal to the number of enemy units here."],
     ["i have [assault] equal to the number of friendly units here", "i have [shield] equal to the number of enemy units here",
      "i have [assault] equal to the number of enemy units"]),
    # set 2 (2026-10-29, Sivir - Mercenary): the card's own Might and keyword while its controller has spent N Power
    ("if_youve_spent_at_least_power_this_turn_i_have_might_and_keyword",
     r"if you've spent at least (?P<power>(?:\[a\])+) this turn, i have \+(?P<amount>\d+) \[m\] and \[(?P<keyword>ganking)\]",
     ["Core 364.3", "Core 364.3.a", "Core 357.1", "Core 479.3", "Core 479.4"], "conditional_might",
     ["continuous_effects", "condition_v1", "conditional_passives"],
     ("+N Might and a keyword on the card itself while its controller has spent at least that much Power, of any "
      "Domain, this turn - read off the per-turn ledger every Power payment writes. Energy spent, or an opponent's "
      "Power, is a different clause."),
     ["If you've spent at least :rb_rune_rainbow::rb_rune_rainbow: this turn, I have +2 :rb_might: and [Ganking]."],
     ["if you've spent at least [a][a] this turn, i have +2 [m]", "if an opponent has spent at least [a] this turn, i have [ganking]",
      "if you've spent at least :rb_energy_2: this turn, i have +2 [m] and [ganking]"]),
    # set 2 (2026-10-29, Trusty Ramhound): the card's own Might while another friendly Unit is at its Battlefield
    ("while_you_have_another_unit_here_i_have_might",
     r"while you have another unit here, i have \+(?P<amount>\d+) \[m\]",
     ["Core 364.3", "Core 364.3.a", "Core 478", "Core 479.4"], "conditional_might", ["continuous_effects", "condition_v1"],
     ("The card's Might while a Unit its controller controls, other than the card, is at the Battlefield the card is at; "
      "none in a Base. An enemy unit, or units anywhere, is a different clause."),
     ["While you have another unit here, I have +1 [M]."],
     ["while you have a unit here, i have +1 [m]", "while an opponent has another unit here, i have +1 [m]",
      "while you have another unit here, i have [tank]"]),
    ("other_friendly_units_have_keyword",
     r"other friendly units have \[(?P<keyword>vision)\]",
     ["Core 365.1", "Core 478", "Core 479.3", "Core 479.3.b", "Core 817.2"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every other friendly Unit on the board, while the source is there. Each "
      "instance of Vision triggers separately (817.2), so a Unit with its own Vision played under this aura "
      "triggers twice. 'here', the source itself, or another keyword is a different clause."),
     ["Other friendly units have [Vision]."],
     ["other friendly units here have [vision]", "friendly units have [vision]", "other friendly units have [tank]"]),
    # 2026-09-27: a card's own conditional keywords (364.3.a), each a keyword_grant on the card
    # itself that applies only while its condition holds; the condition is evaluated in the
    # Ability layer - for Mighty (708) from the layer result in progress (478.3, 478.4).
    ("while_im_buffed_i_have_keywords",
     r"while i'm buffed, i have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 364.3", "Core 364.3.a", "Core 365.1", "Core 479.3", "Core 702.2.a"], "conditional_keywords",
     ["continuous_effects", "condition_v1", "conditional_passives", "buff_counters"],
     ("The card's own keywords while it has a Buff counter (702.2.a); spent, it no longer has them. Another "
      "object's Buff, a Might amount, or a keyword with a value is a different clause."),
     ["While I'm buffed, I have [Ganking]."],
     ["while i'm buffed, i have an additional +1 :rb_might:", "while a friendly unit is buffed, i have [ganking]",
      "while i'm buffed, i have [ganking 2]"]),
    ("if_you_discarded_a_card_this_turn_i_have_keywords",
     r"if you've discarded a card this turn, i have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 364.3", "Core 364.3.a", "Core 365.1", "Core 479.3", "Core 423.1"], "conditional_keywords",
     ["continuous_effects", "condition_v1", "conditional_passives", "private_discard"],
     ("The card's own keywords while its controller has discarded at least one card this turn - by an "
      "instruction or as a cost (423.1, 423.3). An opponent's discard, another turn, or a count other than one "
      "is a different clause."),
     ["If you've discarded a card this turn, I have [Assault] and [Ganking]."],
     ["if an opponent has discarded a card this turn, i have [assault]", "if you've discarded two cards this turn, i have [assault]",
      "when you discard a card, i have [assault]"]),
    ("while_im_mighty_i_have_keywords",
     r"while i'm \[mighty\], i have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 364.3", "Core 364.3.a", "Core 365.1", "Core 478.3", "Core 478.4", "Core 479.3", "Core 708"], "conditional_keywords",
     ["continuous_effects", "condition_v1", "conditional_passives", "layer_engine"],
     ("The card's own keywords while its own Might is 5 or more (708), read from the layers in progress: a Buff "
      "added in the Arithmetic layer makes it Mighty and the Ability layer is evaluated again (478.3); once the "
      "grant is disqualified it is not re-applied (478.4). Another unit's Might is a different clause."),
     ["While I'm [Mighty], I have [Deflect], [Ganking], and [Shield]."],
     ["while a friendly unit is [mighty], i have [ganking]", "while i'm [mighty], i have +2 :rb_might:",
      "when i become [mighty], i have [ganking]"]),
    ("while_im_buffed_i_have_an_additional_might",
     r"while i'm buffed, i have an additional \+(?P<amount>\d+) \[m\]",
     ["Core 364.3", "Core 364.3.a", "Core 702.2.a", "Core 703", "Core 479.4"], "conditional_might",
     ["continuous_effects", "condition_v1", "conditional_passives", "buff_counters"],
     ("+N Might on the card itself while it has a Buff counter, on top of the Buff's own +1 (703). Another "
      "object's Buff or a keyword is a different clause."),
     ["While I'm buffed, I have an additional +1 :rb_might:."],
     ["while i'm buffed, i have [ganking]", "while a friendly unit is buffed, i have an additional +1 :rb_might:",
      "while i'm buffed, i have +1 :rb_might:"]),
    ("i_get_might_for_each_buffed_friendly_unit_at_my_battlefield",
     r"i get \+(?P<amount>\d+) \[m\] for each buffed friendly unit at my battlefield",
     ["Core 364.1", "Core 479.4", "Core 479.4.b", "Core 702.2.a"], "dynamic_might", ["continuous_effects", "buff_counters"],
     ("A passive increase of the card's own Might by the number of Units with a Buff counter, friendly to its "
      "controller, at the Battlefield it is at - itself included ('friendly', not 'other'); none while it is in "
      "a Base. Computed fresh each time (479.4.b). Enemy or unbuffed units, or 'here' elsewhere, are a different clause."),
     ["I get +1 :rb_might: for each buffed friendly unit at my battlefield."],
     ["i get +1 :rb_might: for each friendly unit at my battlefield", "i get +1 :rb_might: for each buffed enemy unit at my battlefield",
      "i get +1 :rb_might: for each other buffed friendly unit at my battlefield"]),
    ("my_might_is_increased_by_the_number_of_cards_in_your_trash",
     r"my might is increased by the number of cards in your trash",
     ["Core 364.1", "Core 479.4", "Core 479.4.b", "Core 108.2.b"], "dynamic_might", ["continuous_effects"],
     ("A passive increase of the card's own Might by the number of cards in its controller's Trash, a public "
      "zone, computed fresh each time (479.4.b). An opponent's Trash, or another zone, is a different clause."),
     ["My Might is increased by the number of cards in your trash."],
     ["my might is increased by the number of cards in your hand", "my might is increased by your points",
      "my might is increased by the number of cards in your opponent's trash"]),
    # 2026-09-27: a card's own conditional entry (364.3.a, 369.3) - an
    # entry_replacements entry whose condition resolution_bridge.entry_state_for reads as it enters
    ("if_an_opponents_score_is_within_n_i_enter_ready",
     r"if an opponent's score is within (?P<within>\d+) points? of the victory score, i enter ready",
     ["Core 364.3.a", "Core 369.3", "Core 143.4", "Core 194.3"], "passive", ["entry_replacements", "condition_v1"],
     ("The card enters ready when, as it enters, its one opponent's score is within N of the Mode of Play's "
      "Victory Score; otherwise exhausted (143.4). Teams, several opponents, or a Mode that does not state its "
      "Victory Score are refused by name, not guessed."),
     ["If an opponent's score is within 3 points of the Victory Score, I enter ready."],
     ["if an opponent's score is within 3 points of the victory score, this costs :rb_energy_2: less",
      "if your score is within 3 points of the victory score, i enter ready", "i enter ready"]),
    ("if_an_opponent_controls_a_battlefield_i_enter_ready",
     r"if an opponent controls a battlefield, i enter ready",
     ["Core 364.3.a", "Core 369.3", "Core 143.4", "Core 190.2.b"], "passive", ["entry_replacements", "condition_v1"],
     ("The card enters ready when, as it enters, a Battlefield is controlled by a player who is not on its "
      "controller's side; otherwise exhausted (143.4). 'You control', or a named Battlefield, is a different clause."),
     ["If an opponent controls a battlefield, I enter ready."],
     ["if you control a battlefield, i enter ready", "if an opponent controls a battlefield, i enter exhausted",
      "i enter ready"]),
    # set 2 (2026-10-29): three more conditional entries, each an entry_replacements entry with a condition
    ("i_enter_ready_if_you_control_another_tag",
     r"i enter ready if you control another (?P<tag>dragon|mech)",
     ["Core 364.3.a", "Core 369.3", "Core 143.4", "Core 133.8.a"], "passive", ["entry_replacements", "condition_v1"],
     ("The card enters ready when, as it enters, its controller controls a Unit with the printed tag other than the "
      "card itself; otherwise exhausted (143.4). The tag is a closed table (PRINTED_TAGS); 'a' Dragon (the card "
      "counted) or an opponent's is a different clause."),
     ["I enter ready if you control another Dragon.", "I enter ready if you control another Mech."],
     ["i enter ready if you control a dragon", "i enter ready if an opponent controls another dragon",
      "i enter ready if you control another poro", "i enter ready"]),
    ("i_enter_ready_if_you_have_n_or_more_other_units_in_your_base",
     r"i enter ready if you have (?P<count>two|three|\d+) or more other units in your base",
     ["Core 364.3.a", "Core 369.3", "Core 143.4", "Core 107.2.b"], "passive", ["entry_replacements", "condition_v1"],
     ("The card enters ready when, as it enters, its controller controls at least N Units other than the card in "
      "their Base; otherwise exhausted (143.4). Units at a Battlefield are not counted. 'Units' without 'other', or "
      "units anywhere, is a different clause."),
     ["I enter ready if you have two or more other units in your base."],
     ["i enter ready if you have two or more units in your base",
      "i enter ready if you have two or more other units at a battlefield", "i enter ready"]),
    ("if_you_have_n_or_fewer_cards_in_your_hand_i_enter_ready",
     r"if you have (?P<count>two|three|\d+) or fewer cards in your hand, i enter ready",
     ["Core 364.3.a", "Core 369.3", "Core 143.4"], "passive", ["entry_replacements", "condition_v1"],
     ("The card enters ready when, as it enters, its controller's hand holds N cards or fewer - the card itself, "
      "played, is no longer there; otherwise exhausted (143.4). Their own hand, so nothing hidden from them is read. "
      "'Or more', or an opponent's hand, is a different clause."),
     ["If you have two or fewer cards in your hand, I enter ready."],
     ["if you have two or more cards in your hand, i enter ready",
      "if an opponent has two or fewer cards in their hand, i enter ready", "i enter ready"]),
    # 2026-09-27 (package 5): a Battlefield's printed Bonus Damage over the Units at it - every
    # Deal of a spell or ability, whoever controls it, to a Unit there (effect_ir.bonus_damage,
    # scope `location`); check_battlefield_passives.py
    # set 2 package A2 (Rabadon's Deathcrown's Effect Text): the controller's own spells and abilities deal N more to
    # whatever they damage (Core 713-715), read while the source is on the board
    ("your_spells_and_abilities_deal_n_bonus_damage", r"your spells and abilities deal (?P<amount>\d+) bonus damage",
     ["Core 713", "Core 714", "Core 715.1"], "passive", ["bonus_damage"],
     ("A printed Bonus Damage of the controller's sources: each of their spells and abilities deals N more when it deals "
      "damage, while the source is on the board. 'To units here', an opponent's sources, or the next spell only is a "
      "different clause."),
     ["Your spells and abilities deal 3 Bonus Damage."],
     ["spells and abilities deal 1 bonus damage to units here", "your spells deal 1 bonus damage",
      "the next spell you play this turn deals 1 bonus damage"]),
    ("spells_and_abilities_deal_n_bonus_damage_to_units_here",
     r"spells and abilities deal (?P<amount>\d+) bonus damage to units here",
     ["Core 713", "Core 714", "Core 715.1", "Core 715.2"], "passive", ["bonus_damage"],
     ("A Battlefield's printed Bonus Damage: each Deal of any player's spell or ability adds N to the damage it "
      "deals to a Unit at this Battlefield, and only to such a Unit (715.2: each target separately), while the "
      "Battlefield is in play. 'Your spells and abilities' (a controller's sources) or 'enemy units here' is a "
      "different clause."),
     ["Spells and abilities deal 1 Bonus Damage to units here."],
     ["your spells and abilities deal 1 bonus damage", "spells and abilities deal 1 bonus damage to enemy units here",
      "spells deal 1 bonus damage to units here", "spells and abilities deal 1 bonus damage to units"]),
    # 2026-09-27 (package 5): a Battlefield's printed Facedown Zone occupancy of one more card
    # (107.3.b.1); hidden.hide_card reads the capacity; check_battlefield_passives.py
    ("you_may_hide_an_additional_card_here",
     r"you may hide an additional card here",
     ["Core 107.3.b", "Core 107.3.b.1", "Core 107.3.c", "Core 422.1"], "passive", ["facedown_zone", "hide_action"],
     ("A Battlefield's printed statement: its Facedown Zone holds one card more than the one of 107.3.b - two - "
      "while it is in play. Only this Battlefield's zone; hiding still needs control of it (107.3.c). 'Two "
      "additional cards', or a statement on another object, is a different clause."),
     ["You may hide an additional card here."],
     ["you may hide a card here", "you may hide an additional card", "you may hide two additional cards here",
      "you may play an additional card here"]),
    # 2026-10-08 package 10 (Clockwork Keeper): one Power of a printed Domain offered as an optional additional cost
    # set 2 package A2 (Sea Monkey; Blast Corps Cadet): the same optional offer for the card's own play, of Energy, or of
    # Energy and one Power of a printed Domain
    ("you_may_pay_energy_as_an_additional_cost_to_play_me",
     r"you may pay \[e(?P<energy>\d+)\] as an additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1"], "passive", ["card_self_optional_cost"],
     ("The card offers an amount of Energy as an optional additional cost for its own play; paying it is the "
      "controller's choice as the card is played (355.1.a)."),
     ["You may pay :rb_energy_1: as an additional cost to play me."],
     ["pay :rb_energy_1: as an additional cost to play me", "you may pay :rb_energy_1: as an additional cost to play another unit",
      "you may pay :rb_energy_1::rb_rune_fury: as an additional cost to play me"]),
    ("you_may_pay_energy_and_a_rune_as_an_additional_cost_to_play_me",
     r"you may pay \[e(?P<energy>\d+)\]\[rune:(?P<domain>[a-z]+)\] as an additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1"], "passive", ["card_self_optional_cost"],
     ("The card offers an amount of Energy and one Power of the printed Domain together as one optional additional cost "
      "for its own play; paying it is the controller's choice as the card is played (355.1.a)."),
     ["You may pay :rb_energy_1::rb_rune_fury: as an additional cost to play me."],
     ["you may pay :rb_energy_1: as an additional cost to play me",
      "you may pay :rb_energy_1::rb_rune_fury: as an additional cost to play another unit"]),
    # set 2 package A3 (Akshan - Mischievous: [Body][Body]): two Power of one printed Domain, the same optional offer
    ("you_may_pay_two_runes_as_an_additional_cost_to_play_me",
     r"you may pay \[rune:(?P<domain>[a-z]+)\]\[rune:(?P=domain)\] as an additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1"], "passive", ["card_self_optional_cost"],
     ("The card offers two Power of the printed Domain together as one optional additional cost for its own play; "
      "paying it is the controller's choice as the card is played (355.1.a)."),
     ["You may pay [rune:body][rune:body] as an additional cost to play me."],
     ["you may pay [rune:body] as an additional cost to play me",
      "you may pay [rune:body][rune:calm] as an additional cost to play me",
      "you may pay [rune:body][rune:body] as an additional cost to play another unit"]),
    ("you_may_pay_a_rune_as_an_additional_cost_to_play_me",
     r"you may pay \[rune:(?P<domain>[a-z]+)\] as an additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1"], "passive", ["card_self_optional_cost"],
     ("The card offers one Power of the printed Domain as an optional additional cost for its own play; paying it is the "
      "controller's choice as the card is played (355.1.a)."),
     ["You may pay [rune:calm] as an additional cost to play me."],
     ["pay [rune:calm] as an additional cost to play me", "you may pay [rune:calm] as an additional cost to play another unit",
      "you may pay [c] as an additional cost to play me"]),
    ("you_may_pay_own_domain_power_as_additional_cost_to_play_me",
     r"you may pay \[c\] as additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1", "Core 820.1"], "passive", ["card_self_optional_cost", "domain_power"],
     ("The card offers one Power of its own Domain as an optional additional cost for its own play. "
      "[C] is the card's Domain, not any Domain ([A]) - a card whose Domains are not observed abstains "
      "at play time rather than being offered an unpayable or an over-payable cost."),
     ["You may pay [C] as additional cost to play me."],
     ["you may pay [a] as additional cost to play me",
      "you may pay [c] as additional cost to play another unit",
      "pay [c] as additional cost to play me"]),
    # 2026-09-27 (package 6): a card's own printed non-resource additional costs (Core 356.2.a.1,
    # 356.2.b.1, 356.7); play_transaction.printed_cost_components pays them; check_printed_costs.py
    # set 2 package A2 (Zaun Punk): an OPTIONAL printed cost paid by killing a friendly Gear
    ("you_may_kill_a_friendly_gear_as_an_additional_cost_to_play_me",
     r"you may (?P<cost>kill a friendly gear) as an additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1", "Core 357.2", "Core 429.1.a.1", "Core 355.10.c"], "passive",
     ["card_self_optional_cost", "kill"],
     ("An OPTIONAL additional cost the card prints for its own play: one friendly Gear on the board, chosen by the payer "
      "as the card is played, killed as the cost is paid (not a target, 355.10.c). Declined, nothing is killed."),
     ["You may kill a friendly gear as an additional cost to play me."],
     ["you may kill a friendly unit as an additional cost to play me", "you may kill a gear as an additional cost to play me",
      "as an additional cost to play me, kill a friendly gear"]),
    # set 2 package A2 (Bard - Mercurial): an OPTIONAL printed cost paid by exhausting its player's Legend
    ("you_may_exhaust_your_legend_as_an_additional_cost_to_play_me",
     r"you may (?P<cost>exhaust your legend) as an additional cost to play me",
     ["Core 356.2.b", "Core 356.2.b.1", "Core 357.2", "Core 107.4.d", "Core 174.8"], "passive",
     ["card_self_optional_cost"],
     ("An OPTIONAL additional cost the card prints for its own play: its player's Legend, in their Legend Zone, exhausted "
      "as the cost is paid; an exhausted Legend cannot pay it (Core 203.3). Declined, nothing is exhausted."),
     ["You may exhaust your legend as an additional cost to play me."],
     ["you may exhaust a friendly unit as an additional cost to play me",
      "exhaust your legend as an additional cost to play me",
      "you may exhaust your legend as an additional cost to play this"]),
    # set 2 package A2 (Legion Quartermaster): the same mandatory printed cost, paid by returning a friendly Gear
    ("as_an_additional_cost_to_play_me_return_a_friendly_gear",
     r"as an additional cost to play me, (?P<cost>return a friendly gear to its owner's hand)",
     ["Core 356.2.a", "Core 356.2.a.1", "Core 356.7", "Core 357.2", "Core 448.2"], "passive",
     ["card_self_optional_cost"],
     ("A MANDATORY additional cost the card prints for its own play: one friendly Gear on the board, chosen by the payer "
      "as the card is played, returned to its owner's hand as the cost is paid. No friendly Gear, no play (203.3)."),
     ["As an additional cost to play me, return a friendly gear to its owner's hand."],
     ["as an additional cost to play me, return a friendly unit to its owner's hand",
      "as an additional cost to play me, kill a friendly gear", "return a friendly gear to its owner's hand"]),
    ("as_an_additional_cost_to_play_me_kill_a_friendly_unit",
     r"as an additional cost to play me, (?P<cost>kill a friendly unit)",
     ["Core 356.2.a", "Core 356.2.a.1", "Core 356.7", "Core 357.2", "Core 355.10.c"], "passive",
     ["card_self_optional_cost", "kill"],
     ("A MANDATORY additional cost the card prints for its own play: killing one friendly Unit on the board, "
      "chosen by the payer as the card is played and killed as the cost is paid (not a target, 355.10.c). "
      "No friendly Unit, no play (203.3). 'You may', another object's play, or another kind of unit is a "
      "different clause."),
     ["As an additional cost to play me, kill a friendly unit."],
     ["as an additional cost to play me, kill an enemy unit", "as an additional cost to play me, kill a unit",
      "as an additional cost to play another unit, kill a friendly unit", "as you play me, kill a friendly unit"]),
    # 2026-10-08 (package 10, Meditation): the same optional printed cost, worded "As an additional cost to play this, you
    # may ..." - what it switches on is the clause after it ("If you do, ..." / "Otherwise, ..." read the decision to pay)
    ("as_an_additional_cost_to_play_this_you_may_exhaust_a_friendly_unit",
     r"as an additional cost to play (?:me|this), you may (?P<cost>exhaust a friendly unit)",
     ["Core 356.2.b", "Core 356.2.b.1", "Core 355.1.a", "Core 356.7", "Core 357.2"], "passive",
     ["card_self_optional_cost"],
     ("An OPTIONAL additional cost the card prints for its own play: exhausting one friendly Unit on the board, chosen "
      "by the payer as the card is played (not a target, 355.10.c). Paying it is the controller's choice as the card is "
      "played (355.1.a); 'If you do' / 'Otherwise' after it read that decision (356.4.f.1)."),
     ["As an additional cost to play this, you may exhaust a friendly unit."],
     ["as an additional cost to play this, exhaust a friendly unit",
      "as an additional cost to play this, you may exhaust an enemy unit",
      "as an additional cost to play another unit, you may exhaust a friendly unit"]),
    ("as_you_play_me_you_may_pay_a_cost_as_an_additional_cost",
     r"as you play (?:me|this), you may (?P<cost>discard (?P<amount>\d+)|spend a buff|kill any number of friendly units"
     r"|spend any number of buffs) as an additional cost",
     ["Core 356.2.b", "Core 356.2.b.1", "Core 355.1.a", "Core 356.7", "Core 357.2", "Core 355.13"], "passive",
     ["card_self_optional_cost", "discard_recycle_costs", "spend_costs", "kill"],
     ("An OPTIONAL additional cost the card prints for its own play: discard N cards, spend one buff, or kill / "
      "spend any number (355.13) of friendly Units / buffs. Paying it is the controller's choice as the card is "
      "played (355.1.a); what it switches on is the clause after it ('If you do, ...', 'Reduce my cost by ... for "
      "each ...'). Without 'you may', or without 'as an additional cost', it is a different clause."),
     ["As you play me, you may discard 2 as an additional cost.", "As you play this, you may spend a buff as an additional cost.",
      "As you play me, you may kill any number of friendly units as an additional cost.",
      "As you play me, you may spend any number of buffs as an additional cost."],
     ["as you play me, discard 1 as an additional cost", "as you play me, you may discard 1",
      "as you play me, you may kill any number of enemy units as an additional cost",
      "when you play me, you may discard 1 as an additional cost",
      "as you play me, you may spend any number of buffs"]),
    # 2026-09-27 (package 6): a permanent's discount on its controller's cards of one tag
    # (play_transaction.granted_cost_discounts); check_granted_cost_discounts.py
    ("your_tags_energy_costs_are_reduced_to_a_minimum",
     r"your (?P<tag>[a-z]+)s' energy costs are reduced by \[e(?P<amount>\d+)\], to a minimum of \[e(?P<minimum>\d+)\]",
     ["Core 356.4", "Core 356.4.a", "Core 356.4.b", "Core 356.4.e", "Core 356.6", "Core 133.8"], "passive",
     ["evaluated_cost_modifications", "typed_cost_modification_input"],
     ("While this permanent is on the board, each card its controller plays that has the tag (as printed) costs "
      "N Energy less, never below M by this discount (356.4.e). Another player's card, a card without the tag, "
      "and Power are untouched. 'Cost [N] less' with no minimum, or 'your units', is a different clause."),
     ["Your Poros' Energy costs are reduced by [E1], to a minimum of [E1]."],
     ["your dragons' power costs are reduced by [e2], to a minimum of [e1]", "your dragons' energy costs are reduced by [e2]",
      "dragons' energy costs are reduced by [e2], to a minimum of [e1]",
      "your dragon energy costs are reduced by [e2], to a minimum of [e1]"]),
    ("while_im_at_a_battlefield_spells_you_play_cost_less",
     r"while i'm at a battlefield, the energy costs for spells you play (?:is|are) reduced by \[e(?P<amount>\d+)\], "
     r"to a minimum of \[e(?P<minimum>\d+)\]",
     ["Core 364.3.a", "Core 356.4", "Core 356.4.a", "Core 356.4.b", "Core 356.4.e", "Core 356.6"], "passive",
     ["evaluated_cost_modifications", "typed_cost_modification_input", "conditional_passives"],
     ("While this permanent is at a Battlefield (not its Base), each spell its controller plays costs N Energy less, "
      "never below M by this discount (356.4.e). Units, another player's spells, and Power are untouched; 'while I'm "
      "attacking', or no minimum, is a different clause."),
     ["While I'm at a battlefield, the Energy costs for spells you play are reduced by [E2], to a minimum of [E1]."],
     ["while i'm at a battlefield, the energy costs for units you play is reduced by [e1], to a minimum of [e1]",
      "while i'm in your base, the energy costs for spells you play is reduced by [e1], to a minimum of [e1]",
      "the energy costs for spells you play is reduced by [e1], to a minimum of [e1]",
      "while i'm at a battlefield, the energy costs for spells you play is reduced by [e1]"]),
    # 2026-10-12 package 11 (Symbol of the Solari)
    ("if_a_combat_where_you_are_the_attacker_ends_in_a_tie_recall_all_units_instead",
     r"if a combat where you are the attacker ends in a tie, recall all units instead",
     ["Core 468.3.d", "Core 370.1", "Core 457"], "passive", ["combat_result", "recall"],
     ("The result of a Combat its controller attacked in, when it is a tie (No Result, 468.3.d), is replaced: every unit "
      "still at that Battlefield, either side's, is recalled. As the defender, or with a winner, nothing changes."),
     ["If a combat where you are the attacker ends in a tie, recall ALL units instead."],
     ["if a combat where you are the defender ends in a tie, recall all units instead",
      "if a combat ends in a tie, recall all units instead",
      "if a combat where you are the attacker ends in a tie, recall all enemy units instead"]),
    ("if_a_friendly_unit_would_die_kill_this_instead",
     r"if a friendly unit would die, kill this instead",
     ["Core 367", "Core 370.1.b", "Core 373.1"], "passive", ["replacement_effects", "kill"],
     ("A source-backed Replacement Effect over the death of a friendly Unit. What happens instead "
      "starts with killing the source; a following clause may add to it, and its referents name the "
      "unit that would have died."),
     ["If a friendly unit would die, kill this instead."],
     ["if a unit would die, kill this instead",
      "if a friendly unit would die, prevent it",
      "the next time a friendly unit would die, kill this instead"]),
    ("counter_a_spell_within_a_cost_limit",
     r"counter a spell that costs no more than \[e(?P<energy>\d+)\] and no more than \[a\]",
     ["Core 367", "Core 355.9", "Core 356.1"], "instruction", ["counter", "typed_selectors"],
     ("Counter one chosen spell whose cost is within the printed limits. Which of the three costs "
      "'costs no more than' reads is not something this clause decides - the Core Rules never define "
      "the phrase - so the production leaves cost_basis unset and a card mapping must supply it. "
      "Without one the clause abstains rather than picking a reading."),
     ["Counter a spell that costs no more than [E4] and no more than [A]."],
     ["counter a spell that costs no more than [e4]",
      "counter a spell",
      "counter a spell that costs no more than [e4] and no more than [c]"]),
    # 2026-10-08 (package 10, Wind Wall): one spell on the Chain, chosen as the countering card is played (Core 355.7,
    # 355.5), countered (Core 426.1)
    # 2026-10-13 package 11 (Treasure Trove: "[C], [T]: Kill this."): the ability's own source killed - its typed
    # self-reference, resolved as the instruction executes (gone or a new object: ignored, Core 359.3.e.6)
    # 2026-10-13 package 11 (Time Warp): an Additional Turn for the card's controller, and the spell banishing itself
    # 2026-10-13 package 11 (Possession, GPT ruling 12): one enemy unit at a Battlefield chosen as the spell is played;
    # its controller becomes the caster, then it is recalled - to its NEW controller's Base
    ("choose_an_enemy_unit_at_a_battlefield_take_control_of_it_and_recall_it",
     r"choose an enemy unit at a battlefield\. take control of it and recall it",
     ["Core 189", "Core 191.4", "Core 355.5", "Core 457", "Core 458.1"], "instruction", ["gain_control", "recall", "targeting"],
     "One enemy Unit at a Battlefield, chosen as the spell is played (the same chosen object for both instructions): "
     "its controller becomes the spell's controller - its owner, damage, exhaustion and buff unchanged - and it is "
     "recalled to that new controller's Base (not a Move). A friendly Unit, or one in a Base, is not a legal choice.",
     ["Choose an enemy unit at a battlefield. Take control of it and recall it."],
     ["choose an enemy unit. take control of it and recall it", "choose an enemy unit at a battlefield. take control of it",
      "choose an enemy unit at a battlefield. recall it"]),
    # set 2 package A3 (Hostile Takeover): a control effect ended by the delayed trigger made with it, at the end of this
    # turn; the unit then recalled to its controller's base
    ("take_control_of_an_enemy_unit_at_a_battlefield_ready_it_lose_control_of_that_unit_and_recall_it_at_end_of_turn",
     r"take control of an enemy unit at a battlefield\. ready it\. lose control of that unit and recall it at end of turn",
     ["Core 189", "Core 190.3.a.2", "Core 355.5", "Core 359.3.e.16", "Core 457", "Core 479.2.a"], "instruction",
     ["gain_control", "ready", "create_delayed_trigger", "lose_control", "recall", "targeting"],
     "One enemy Unit at a Battlefield, chosen as the spell is played: its controller becomes the spell's controller "
     "until the end of this turn (a control effect; Contested applied there when the new controller does not control "
     "it), and it is readied. At the end of the turn a delayed trigger bound to that unit ends the control effect and "
     "recalls it to the base of whoever controls it then; a unit that left the board meanwhile is a new object, and the "
     "trigger is dropped. Made during this turn's Ending Phase, it is not generated.",
     ["Take control of an enemy unit at a battlefield. Ready it. Lose control of that unit and recall it at end of turn."],
     ["take control of an enemy unit at a battlefield. ready it",
      "take control of an enemy unit. ready it. lose control of that unit and recall it at end of turn",
      "take control of an enemy unit at a battlefield. lose control of that unit and recall it at end of turn"]),
    # set 2 package A3 (Akshan - Mischievous): the gear moved to the controller's base and controlled while the source
    # stays on the board; an Equipment attached to the source
    ("move_an_enemy_gear_to_your_base_you_control_it_until_i_leave_the_board_if_its_an_equipment_attach_it_to_me",
     r"move an enemy gear to your base\. you control it until i leave the board\. if it's an equipment, attach it to me",
     ["Core 355.5", "Core 359.3.e.16", "Core 435", "Core 479.2.a", "Core 719.5"], "instruction",
     ["move_board_object", "gain_control", "attach", "targeting"],
     "One enemy gear on the board, chosen as the trigger is finalized, moved to the base of the trigger's controller; the trigger's "
     "controller controls it while the source stays on the board (when the source leaves, control reverts), and if it "
     "is an Equipment it is attached to the source. The source gone before this resolves: no control is gained.",
     ["Move an enemy gear to your base. You control it until I leave the board. If it's an Equipment, attach it to me."],
     ["move an enemy gear to your base. you control it until i leave the board",
      "move an enemy unit to your base. you control it until i leave the board. if it's an equipment, attach it to me",
      "move a friendly gear to your base. you control it until i leave the board. if it's an equipment, attach it to me"]),
    # 2026-10-13 package 11 (Reckoner's Arena, GPT ruling 15): Core 383.4.g.1's own example
    ("activate_the_conquer_effects_of_units_here",
     r"activate the conquer effects of units here",
     ["Core 383.4.g", "Core 383.4.g.1", "Core 383.4.c"], "instruction", ["activate_conquer_effects"],
     "Each conquer effect of each unit at the source's Battlefield - of either side - is checked as if its conquer part "
     "were fulfilled; one whose other conditions hold becomes a Pending item like a fresh trigger, controlled by "
     "that unit's controller.",
     ["Activate the conquer effects of units here."],
     ["activate the conquer effects of friendly units here", "activate the hold effects of units here",
      "activate the conquer effects of units at a battlefield"]),
    # 2026-10-13 package 11 (Heimerdinger - Inventor, GPT ruling 14)
    ("i_have_all_exhaust_abilities_of_all_friendly_legends_units_and_gear",
     r"i have all :rb_exhaust: abilities of all friendly legends, units, and gear",
     ["Core 377", "Core 191.5", "Core 359.3.f.1"], "passive", ["copied_abilities"],
     "The card has every activated ability with [Exhaust] in its cost that a friendly Legend, Unit or Gear on the Board "
     "prints, for as long as that permanent is there: 'me'/'this' is the card, its [Exhaust] exhausts the card, every "
     "other printed cost is paid as printed.",
     ["I have all :rb_exhaust: abilities of all friendly legends, units, and gear."],
     ["i have all abilities of all friendly units", "i have all :rb_exhaust: abilities of all enemy units",
      "i have all :rb_exhaust: abilities of all friendly units"]),
    # 2026-10-13 package 11 (Mystic Reversal, GPT ruling 13; Core 750-755)
    ("gain_control_of_a_spell_you_may_make_new_choices_for_it",
     r"gain control of a spell\. you may make new choices for it",
     ["Core 191.3", "Core 191.5.b", "Core 751", "Core 752.1", "Core 753.1", "Core 755"], "instruction",
     ["gain_control_of_spell", "make_new_choices", "counter"],
     "One spell on the Chain, chosen as this is played, becomes its controller's - what was paid for it moves nowhere - "
     "and that player may then remake any of its targets, destinations or mode, each new choice something it did not "
     "choose before and legal now; what is not remade stays.",
     ["Gain control of a spell. You may make new choices for it."],
     ["gain control of a spell", "gain control of a unit. you may make new choices for it",
      "gain control of a spell. make new choices for it"]),
    ("take_a_turn_after_this_one",
     r"take a turn after this one",
     ["Core 735", "Core 736", "Core 737", "Core 738"], "instruction", ["take_additional_turn"],
     ("Its controller takes an Additional Turn after the current one: queued ahead of any queued before it, the Turn "
      "Order unchanged; after it the turns resume as they were queued. Another player's turn, or 'an additional turn' "
      "with a condition, is a different production."),
     ["Take a turn after this one."],
     ["take an additional turn after this one", "each player takes a turn after this one", "skip your next turn"]),
    ("banish_this",
     r"banish this",
     ["Core 157", "Core 428.1", "Core 124"], "instruction", ["banish_this"],
     ("The resolving spell's own instruction: it leaves the Chain for its owner's banishment, not the trash. Not on the "
      "Chain, nothing is banished. 'Banish it' or 'banish a unit' is a different production."),
     ["Banish this."],
     ["banish it", "banish a unit", "banish this instead"]),
    ("kill_this",
     r"kill this",
     ["Core 429", "Core 359.3.f.1", "Core 359.3.e.6"], "instruction", ["kill"],
     ("The ability's own source is killed (object_ref program_source): no target, nothing chosen. 'Kill it', a chosen "
      "unit, or 'kill this instead' (a replacement) is a different production."),
     ["Kill this."],
     ["kill it", "kill a unit", "kill this instead"]),
    # set 2 package A2 (Hard Bargain): the countered spell's controller may pay Energy, as the Counter resolves, and then
    # nothing is countered
    ("counter_a_spell_unless_its_controller_pays_energy",
     r"counter a spell unless its controller pays \[e(?P<energy>\d+)\]",
     ["Core 426.1", "Core 355.7", "Core 355.10.e"], "instruction", ["counter", "typed_selectors"],
     ("Counter one chosen spell on the Chain, unless that spell's controller pays the Energy as the Counter resolves; "
      "paid, nothing is countered. A payment by the caster, a Power cost, or a different 'instead' is a different "
      "production."),
     ["Counter a spell unless its controller pays [E2]."],
     ["counter a spell unless you pay [e2]", "counter a unit unless its controller pays [e2]",
      "counter a spell unless its controller has you draw 2"]),
    ("counter_a_spell",
     r"counter a spell",
     ["Core 426.1", "Core 355.7", "Core 355.5"], "instruction", ["counter", "typed_selectors"],
     ("Counter one chosen spell on the Chain: its card leaves the Chain to its owner's trash, it was not played and no "
      "cost is refunded (Core 426.1). The target is chosen as the countering card is played."),
     ["Counter a spell."],
     ["counter a spell that costs no more than [e4] and no more than [a]", "counter an ability",
      "counter a unit", "counter target spell"]),
    ("choose_an_opponent",
     r"choose an opponent",
     ["Core 355.1", "Core 355.18"], "instruction", ["choose_player"],
     ("The whole instruction is a choice of one opponent. It changes nothing; what it leaves is the "
      "receipt the clauses after it read, so 'they' means this opponent and not whoever matches later."),
     ["Choose an opponent."],
     ["choose a player", "choose an opponent unit", "each opponent"]),
    ("they_reveal_their_hand",
     r"they reveal their hand",
     ["Core 425.2.b", "Core 128.4"], "instruction", ["reveal"],
     ("The opponent an earlier clause chose reveals their whole hand (425.2.b: a hand reveal shows every "
      "card, so it takes no count). The clause abstains unless an earlier clause chose the player."),
     ["They reveal their hand."],
     ["reveal your hand", "they reveal 2 cards", "each opponent reveals their hand"]),
    ("choose_a_non_unit_card_from_it_and_recycle_that_card",
     r"choose a non-unit card from it, and recycle that card",
     ["Core 425.3.a", "Core 434", "Core 355.10.a"], "instruction", ["recycle", "reveal"],
     ("One card from what the preceding reveal actually put on the table, excluding Units, recycled. "
      "The candidates are the reveal's own marks, so nothing still private is choosable."),
     ["Choose a non-unit card from it, and recycle that card."],
     ["choose a card from it, and recycle that card",
      "choose a non-unit card from their hand, and recycle that card",
      "choose a non-unit card from it"]),
    # 2026-10-08 package 10 (Mindsplitter)
    ("choose_a_card_from_it_and_they_discard_that_card",
     r"choose a card from it, and they discard that card",
     ["Core 425.2.b", "Core 423.1", "Core 128.4", "Core 355.10.a"], "instruction", ["discard", "reveal"],
     ("One card from what the preceding reveal actually put on the table, chosen by the caster; the player an earlier "
      "clause chose discards it. The candidates are the reveal's own marks in that player's hand, so nothing still "
      "private is choosable; nothing revealed, nothing is discarded."),
     ["Choose a card from it, and they discard that card."],
     ["choose a card from it, and recycle that card", "they discard a card",
      "choose a card from their hand, and they discard that card"]),
    ("you_may_play_me_to_an_occupied_enemy_battlefield",
     r"you may play me to an occupied enemy battlefield",
     ["Core 355.2.a", "Core 355.2.b", "Core 170.11.a", "Core 323.5"], "passive",
     ["occupied_enemy_battlefield"],
     ("A printed permission that widens where this card may enter, and nothing else: 170.11.a makes "
      "'occupied' a Unit being there, of anyone's, and 'enemy' is the controller relation. It does not "
      "widen timing. The conditional form ('if an enemy unit is already there') and the granting form "
      "('friendly units may be played to...') are different clauses and stay unparsed."),
     ["You may play me to an occupied enemy battlefield."],
     ["you may play me to an open battlefield",
      "you may play me to an occupied battlefield",
      "friendly units may be played to open battlefields",
      "i can be played to an occupied battlefield if an enemy unit is already there"]),
    # 2026-09-24: the open-battlefield sibling - 170.11.c makes "open" no controller and
    # nothing on it; the engine's play path already honours the permission
    # (check_permanent_play.py). The granting form stays a different clause.
    ("you_may_play_me_to_an_open_battlefield",
     r"you may play me to an open battlefield",
     ["Core 355.2.a", "Core 355.2.b", "Core 170.11.c"], "passive",
     ["open_battlefield"],
     ("A printed permission that widens where this card may enter, and nothing else: 170.11.c makes "
      "'open' a Battlefield no one controls with nothing on it. It does not widen timing. The granting "
      "form ('friendly units may be played to open battlefields') is a different clause and stays unparsed."),
     ["You may play me to an open battlefield."],
     ["you may play me to an occupied enemy battlefield",
      "friendly units may be played to open battlefields",
      "you may play a unit to an open battlefield"]),
    # set 2 package A2 (Rengar - Pouncing): one more place the card may enter - a Battlefield its player is attacking
    ("i_can_be_played_to_a_battlefield_youre_attacking",
     r"i can be played to a battlefield you're attacking",
     ["Core 355.2.a", "Core 355.2.b", "Core 466.2.c"], "passive", ["open_battlefield"],
     ("A printed permission that widens where this card may enter: a Battlefield where one of its player's Units is "
      "designated Attacker now. It does not widen timing (the card's own [Reaction] does). Defending, or a battlefield "
      "merely occupied, is a different clause."),
     ["I can be played to a battlefield you're attacking."],
     ["i can be played to a battlefield you're defending", "you may play me to an open battlefield",
      "units can be played to a battlefield you're attacking"]),
    # 2026-09-27 package 5: a permanent's printed grant to its side's unit plays (Miss Fortune -
    # Buccaneer), read while it is on the board (Core 355.2.b, 170.11.c)
    ("friendly_units_may_be_played_to_open_battlefields",
     r"friendly units may be played to open battlefields",
     ["Core 355.2.a", "Core 355.2.b", "Core 170.11.c"], "passive", ["open_battlefield"],
     ("A permission this permanent grants while it is on the board: a unit card its controller's side plays may "
      "enter an open Battlefield. An enemy's unit, a gear, an occupied or controlled Battlefield, and the permanent "
      "off the board are outside it."),
     ["Friendly units may be played to open battlefields."],
     ["friendly units may be played to occupied enemy battlefields", "you may play me to an open battlefield",
      "enemy units may be played to open battlefields"]),
    # 2026-09-27: a printed replacement on how this permanent enters (Core 369.3). A Gear would
    # otherwise enter ready (359.2.d); a Unit already enters exhausted (143.4, 359.2.c).
    ("this_enters_exhausted",
     r"this enters exhausted",
     ["Core 369.3", "Core 359.2.d", "Core 143.4"], "passive", ["entry_replacements"],
     ("The permanent's own entry replacement: it enters the board exhausted (resolution_bridge."
      "entry_state_for reads it). A timed or granted form ('units you play this turn enter exhausted'), "
      "or 'ready', is a different clause and stays unparsed."),
     ["This enters exhausted."],
     ["this enters ready",
      "units you play enter exhausted",
      "i enter ready"]),
    ("units_cant_move_from_here_to_base",
     r"units can't move from here to base",
     ["Core 144.4.b", "Core 359.3.e.6", "Core 190.6.a"], "passive", ["move_restriction"],
     ("The one restriction shape this wave reads, printed on a Battlefield. It is not a targeting rule: "
      "a Standard Move there is simply not an available action, while a spell may still choose that "
      "destination and have its move instruction ignored at resolution (359.3.e.6). A global, a "
      "self-only, or a timed restriction is a different clause and stays unparsed."),
     ["Units can't move from here to base."],
     ["units can't move to base",
      "i can't move to base",
      "they can't move it this turn",
      "units can't move from here to a battlefield"]),
    # 2026-09-27 package 6: a state the chosen object or the set must be in (Core 415.2 Exhausted,
    # 416.2 Ready, 142 damage marked), bounded and criteria buffs, and two effect conditions read as
    # the instruction executes (Core 383.2.a.1: an "if" not right after the trigger condition)
    ("buff_an_exhausted_friendly_unit", r"buff an exhausted friendly unit",
     ["Core 427.1", "Core 702.2.a", "Core 415.2", "Core 355.9", "Core 359.3.e.2"], "instruction", ["buff", "targeting"],
     "One chosen friendly Unit that is Exhausted when chosen and when buffed. Any friendly unit, an enemy unit, "
     "a Ready unit, or every exhausted unit is a different clause.",
     ["Buff an exhausted friendly unit."],
     ["buff a friendly unit", "buff an exhausted enemy unit", "buff a ready friendly unit",
      "buff all exhausted friendly units"]),
    ("ready_something_else_thats_exhausted", r"ready something else that's exhausted",
     ["Core 416.1", "Core 415.2", "Core 355.9.a", "Core 359.3.e.2"], "instruction", ["ready", "targeting"],
     "One chosen object of any type on the board, or a Legend in its Legend Zone (GPT 2026-10-02), not the source "
     "itself, that is Exhausted when chosen and when readied. The source included, a Ready object, or one type only "
     "is a different clause.",
     ["Ready something else that's exhausted."],
     ["ready something that's exhausted", "ready another unit", "ready something else",
      "ready a unit that's exhausted"]),
    ("give_me_might_this_turn_if_there_is_a_ready_enemy_unit_here",
     r"give me (?P<sign>[+-])(?P<amount>\d+) \[m\] this turn if there is a ready enemy unit here",
     ["Core 478", "Core 481", "Core 317.2", "Core 383.2.a.1", "Core 416.2", "Core 359.3.f.2"], "instruction",
     ["modify_might", "condition_v1"],
     "The source's own Might this turn, only if an enemy Unit that is Ready stands at the source's Battlefield as "
     "the instruction executes. Any enemy unit, an exhausted one, or a condition right after the trigger "
     "condition is a different clause.",
     ["Give me +2 [M] this turn if there is a ready enemy unit here."],
     ["give me +2 [m] this turn if there is an enemy unit here", "give me +2 [m] this turn",
      "give me +2 [m] this turn if there is an exhausted enemy unit here",
      "give me +2 [m] this turn if there is a ready friendly unit here"]),
    ("buff_up_to_two_other_friendly_units", r"buff up to two other friendly units",
     ["Core 427.1", "Core 355.13", "Core 355.8", "Core 359.3.e.8"], "instruction", ["buff", "targeting"],
     "One choice of zero to two friendly Units, the source not among them, each buffed on its own. The source "
     "allowed, exactly two, or every friendly unit is a different clause.",
     ["Buff up to two other friendly units."],
     ["buff up to two friendly units", "buff two other friendly units", "buff all other friendly units",
      "buff up to three other friendly units"]),
    ("buff_all_friendly_units", r"(?:then )?buff all friendly units",
     ["Core 427.1", "Core 427.1.b.1", "Core 355.10.d"], "instruction", ["buff", "criteria_expansion"],
     "Every friendly Unit on the board - Bases and Battlefields - found by criteria, not targeted. Other friendly "
     "units, enemy units, or friendly units at one place is a different clause.",
     ["Buff all friendly units.", "Then buff all friendly units."],
     ["buff all other friendly units", "buff all enemy units", "buff all friendly units here",
      "buff a friendly unit"]),
    ("if_i_am_at_a_battlefield_buff_all_other_friendly_units_there",
     r"(?:then, )?if i am at (?:a )?battlefield, buff all other friendly units there",
     ["Core 427.1", "Core 355.10.d", "Core 359.3.f.2", "Core 383.2.a.1", "Core 107.2.b"], "instruction",
     ["buff", "criteria_expansion", "condition_v1"],
     "Only if the source stands at a Battlefield as the instruction executes: every friendly Unit at that "
     "Battlefield but the source. The source included, every friendly unit, or a condition right after the "
     "trigger condition is a different clause.",
     ["If I am at a battlefield, buff all other friendly units there.",
      "Then, if I am at a battlefield, buff all other friendly units there."],
     ["if i am at a battlefield, buff all friendly units there", "buff all other friendly units there",
      "if i am at a battlefield, buff all other friendly units", "if i am in my base, buff all other friendly units there"]),
    ("kill_all_damaged_enemy_units_here", r"kill all damaged enemy units here",
     ["Core 429", "Core 142", "Core 355.10.d", "Core 359.3.f.2"], "instruction", ["kill", "criteria_expansion"],
     "Every enemy Unit at the source's current Battlefield with damage marked on it as the instruction executes. "
     "Undamaged units, friendly units, or units at another place is a different clause.",
     ["Kill all damaged enemy units here."],
     ["kill all enemy units here", "kill all damaged units here", "kill all damaged enemy units",
      "kill a damaged enemy unit here"]),
    ("no_rules_text", r"\(no rules text\)", ["Core 185"], "empty", [],
     "A card with nothing to compile. It is a parsed clause, not an unparsed one.",
     ["(no rules text)"], ["no rules text", "(vanilla)"]),
    ("play_timing_keyword", r"\[(?P<timing>action|reaction)\]", ["Core 806", "Core 807", "Core 309.1.a"],
     "play_timing", ["timing_permission_v1"],
     "Only the two printed timing keywords.",
     ["[Action]", "[Reaction]"], ["[Action] this turn", "action"]),
]

WRAPPERS = [
    # 2026-09-27 package 6 (Poro Herder): before when_you_play_me, which would take the condition for
    # the instruction; the tag is a closed alternation (clause_grammar.PRINTED_TAGS)
    ("when_you_play_me_if_you_control_a_tag", r"when you play me, if you control an? (?P<tag>poro), (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 383.2.a.1", "Core 133.8.a"], ["play_triggers", "condition_v1"],
     ["When you play me, if you control a Poro, draw 1."],
     ["when you play me, draw 1 if you control a poro", "when you play me, if you control a unit, draw 1",
      "when you play a poro, draw 1", "when i move, if you control a poro, draw 1"]),
    # set 2 (2026-10-29, Dropboarder): before when_you_play_me, as the tag row
    ("when_you_play_me_if_you_control_n_or_more_gear",
     r"when you play me, if you control (?P<count>two|three|\d+) or more gear, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 383.2.a.1"], ["play_triggers", "condition_v1"],
     ["When you play me, if you control two or more gear, ready me."],
     ["when you play me, if you control two or more units, ready me", "when you play me, ready me",
      "when i move, if you control two or more gear, ready me"]),
    # 2026-10-08 package 10 (Clockwork Keeper): before when_you_play_me, which would take the condition for the instruction
    ("when_you_play_me_if_you_paid_the_additional_cost", r"when you play me, if you paid the additional cost, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 383.2.a.1", "Core 356.4.f.1"], ["play_triggers"],
     ["When you play me, if you paid the additional cost, draw 1."],
     ["when you play me, draw 1", "when you play me, if you paid the cost, draw 1",
      "when i move, if you paid the additional cost, draw 1"]),
    # 2026-10-12 package 11 (Blitzcrank - Impassive): before when_you_play_me, which would not take "to a battlefield"
    ("when_you_play_me_to_a_battlefield", r"when you play me to a battlefield, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a"], ["play_triggers"],
     ["When you play me to a battlefield, draw 1."],
     ["when you play me, draw 1", "when i move to a battlefield, draw 1", "when you play me to your base, draw 1"]),
    ("when_you_play_me", r"when you play me, (?P<inner>.+)", ["Core 383.1", "Core 420.4.a"], ["play_triggers"],
     ["When you play me, channel 1 rune exhausted.", "When you play me, draw 1."],
     ["when you play a unit, draw 1", "when i move, draw 1"]),
    # set 2 package A2 (Edge of Night): the card's own play trigger, met only by a play from facedown (Core 811.1.c.3)
    ("when_you_play_this_from_face_down", r"when you play this from face down, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 811.1.c.3"], ["play_triggers"],
     ["When you play this from face down, draw 1."],
     ["when you play this, draw 1", "when you play a card from face down, draw 1", "when you hide this, draw 1"]),
    # 2026-10-08 package 10: a Gear's "When you play this" - the card's own play trigger, as "When you play me"
    ("when_you_play_this", r"when you play this, (?P<inner>.+)", ["Core 383.1", "Core 420.4.a"], ["play_triggers"],
     ["When you play this, draw 1."],
     ["when you play a gear, draw 1", "when you play me, draw 1"]),
    # 2026-10-12 package 11 (Treasure Trove)
    ("when_this_leaves_the_board", r"when this leaves the board, (?P<inner>.+)", ["Core 383.1", "Core 319.6", "Core 359.3.e.13"],
     ["leave_board_triggers"],
     ["When this leaves the board, draw 1."],
     ["when i die, draw 1", "when this moves, draw 1", "when a unit leaves the board, draw 1"]),
    ("when_i_move", r"when i move, (?P<inner>.+)", ["Core 383.1", "Core 421"], ["move_triggers"],
     ["When I move, draw 1."], ["when a unit moves, draw 1", "when you play me, draw 1"]),
    # 2026-09-24: the same Move trigger, met only when the completed Move's destination is a
    # Battlefield (effect_ir: condition moved_to_battlefield, read on move_triggers only)
    ("when_i_move_to_a_battlefield", r"when i move to a battlefield, (?P<inner>.+)", ["Core 383.1", "Core 421"],
     ["move_triggers"], ["When I move to a battlefield, draw 1."],
     ["when i move, draw 1", "when i move to base, draw 1", "when a unit moves to a battlefield, draw 1"]),
    # set 2 (2026-10-29, Harpoon Squad)
    ("when_i_move_from_a_battlefield", r"when i move from a battlefield, (?P<inner>.+)", ["Core 383.1", "Core 421"],
     ["move_triggers"], ["When I move from a battlefield, draw 1."],
     ["when i move, draw 1", "when i move from my base, draw 1", "when a unit moves from a battlefield, draw 1"]),
    # 2026-10-06 package 9 (The Grand Plaza): the conditional statement right after "When you hold here" is part of
    # the Trigger Condition (Core 383.2.a.1) - on the Battlefield's hold descriptor, read as the Hold is processed
    # set 2 package A2 (Sunken Temple): the Conquer here, met only with N or more of the controller's Mighty Units here
    ("when_you_conquer_here_with_n_or_more_mighty_units",
     r"when you conquer here with (?P<count>one|two|three|\d+) or more \[mighty\] units, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 471.1", "Core 190.6.a", "Core 383.2.a.1", "Core 708"], ["conquer_triggers"],
     ["When you conquer here with one or more [Mighty] units, draw 1."],
     ["when you conquer here, draw 1", "when you hold here with one or more [mighty] units, draw 1",
      "when you conquer here with one or more units, draw 1"]),
    ("when_you_hold_here_if_you_have_n_units_here",
     r"when you hold here, if you have (?P<count>\d+)\+ units here, (?P<inner>.+)",
     ["Core 471.2", "Core 190.6.a", "Core 383.2.a.1"], ["hold_triggers"],
     ["When you hold here, if you have 7+ units here, you win the game."],
     ["when you hold here, you win the game", "when you conquer here, if you have 7+ units here, draw 1",
      "when you hold here, if you control 7 units, draw 1"]),
    ("when_you_hold_here", r"when you hold here, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 471.2", "Core 190.6.a", "Core 383.3"], ["hold_triggers"],
     ["When you hold here, draw 1.", "When you hold here, you may channel 1 rune exhausted."],
     ["when you conquer here, draw 1", "when i hold, draw 1", "when you hold here, summon a dragon"]),
    # A Battlefield's own Conquer trigger: its controller - the player who just established
    # control there and Conquered (Core 348.2.a, 471.1) - controls it (190.6.a); it goes on
    # the Chain with the Score's other triggers (473.2). Distinct from a Unit's "When I conquer".
    ("when_you_conquer_here", r"when you conquer here, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 471.1", "Core 473.2", "Core 190.6.a", "Core 383.3"], ["conquer_triggers"],
     ["When you conquer here, draw 1.", "When you conquer here, you may channel 1 rune exhausted."],
     ["when you hold here, draw 1", "when i conquer, draw 1", "when you conquer, draw 1"]),
    # A Battlefield's own Defend trigger: it triggers when its controller gains the Defender
    # designation in a Combat there (Core 383.4.f, 190.6.a, 190.6.d); open_combat schedules
    # it after the Attack triggers (466.2.d.1). Distinct from a Unit's "When I defend".
    ("when_you_defend_here", r"when you defend here, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 383.4.f", "Core 190.6.a", "Core 190.6.d", "Core 466.2.d.1", "Core 383.3"], ["defend_triggers"],
     ["When you defend here, draw 1.", "When you defend here, you may channel 1 rune exhausted."],
     ["when you attack here, draw 1", "when i defend, draw 1", "when you conquer here, draw 1"]),
    # A Unit's own Hold Effect (Core 383.4.d): it goes on the Chain after the Unit is present
    # at a Battlefield its controller Holds and scores from (383.4.d.2.a) - the Scoring Step's
    # unit_here scope. Distinct from the Battlefield's own "When you hold here".
    # set 2 package A2 (Last Rites [Effect Text]): ONE ability with two trigger conditions - the Unit's own conquer or
    # its own hold; the same descriptor in both fields, so one scoring schedules it once
    ("when_i_conquer_or_hold", r"when i conquer or hold, (?P<inner>.+)",
     ["Core 471.1", "Core 471.2", "Core 383.4.c", "Core 383.4.d"], ["conquer_triggers", "hold_triggers"],
     ["When I conquer or hold, draw 1."], ["when i conquer, draw 1", "when you conquer or hold, draw 1",
                                          "when i conquer or defend, draw 1"]),
    ("when_i_hold", r"when i hold, (?P<inner>.+)", ["Core 471.2", "Core 383.4.d", "Core 383.4.d.2.a"], ["hold_triggers"],
     ["When I hold, draw 1."], ["when you hold here, draw 1", "when i conquer, draw 1", "when i move, draw 1"]),
    # set 2 package A2 (Lucian - Merciless): the card's own conquer trigger, on its first conquer of the turn only
    ("the_first_time_i_conquer_each_turn", r"the first time i conquer each turn, (?P<inner>.+)",
     ["Core 471.1", "Core 383.1"], ["conquer_triggers"],
     ["The first time I conquer each turn, draw 1."],
     ["when i conquer, draw 1", "the first time i hold each turn, draw 1", "the first time you conquer each turn, draw 1"]),
    ("when_i_conquer", r"when i conquer, (?P<inner>.+)", ["Core 471.1", "Core 383.1"], ["conquer_triggers"],
     ["When I conquer, draw 1."], ["when you conquer, draw 1", "when i hold, draw 1", "when i move, draw 1"]),
    # A Unit's own Attack Trigger (Core 383.4.e): it goes on the Chain the first time this
    # combat the Unit becomes an Attacker (383.4.e.2, .2.a), attacker before
    # defender (466.2.d.1). Distinct from the player-level "When you attack" (not modelled).
    ("when_i_attack", r"when i attack, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.e.1", "Core 383.4.e.2", "Core 383.4.e.2.a", "Core 466.2.d", "Core 466.2.d.1"],
     ["attack_triggers"],
     ["When I attack, draw 1."], ["when you attack, draw 1", "when i defend, draw 1", "when i conquer, draw 1"]),
    # 2026-10-12 package 11 (Teemo - Strategist): a Unit's own Defend trigger (Core 383.4.f), the object-level
    # defend_triggers the attack-or-defend row already files its descriptor under
    ("when_i_defend", r"when i defend, (?P<inner>.+)",
     ["Core 383.4.f", "Core 383.4.f.1", "Core 383.4.f.2", "Core 383.4.f.2.a", "Core 466.2.d", "Core 466.2.d.1"],
     ["attack_triggers"],
     ["When I defend, draw 1."], ["when you defend here, draw 1", "when i attack, draw 1", "when i conquer, draw 1"]),
    # One Unit ability with two trigger conditions (Core 383.4.e, 383.4.f): it goes on the
    # Chain the first time this Combat the Unit becomes an Attacker, or a Defender - never
    # both, since a Unit holds one designation per Combat.
    ("when_i_attack_or_defend", r"when i attack or defend, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.e.2.a", "Core 383.4.f", "Core 383.4.f.2.a", "Core 466.2.d", "Core 466.2.d.1"],
     ["attack_triggers"],
     ["When I attack or defend, draw 1."],
     ["when i attack, draw 1", "when i defend, draw 1", "when you attack or defend, draw 1"]),
    # 2026-09-27: one Unit ability with two trigger conditions of different kinds - a Play Effect
    # (Core 383.4.a, 420.4.a: on play completion) and a Conquer Effect (383.4.c, 383.4.c.2.a: the
    # Unit present at the Battlefield Conquered). The same descriptor in play_triggers and
    # conquer_triggers; the two events are different, so each schedules it at most once.
    ("when_im_played_and_when_i_conquer", r"when i'm played and when i conquer, (?P<inner>.+)",
     ["Core 383.4.a", "Core 420.4.a", "Core 383.4.c", "Core 383.4.c.2.a", "Core 471.1"],
     ["play_triggers", "conquer_triggers"],
     ["When I'm played and when I conquer, draw 1."],
     ["when i'm played, draw 1", "when i conquer, draw 1", "when i'm played or when i hold, draw 1"]),
    # set 2 (2026-10-29, Ornn - Blacksmith): a Play Effect (383.4.a, 420.4.a) or a Hold Effect (383.4.d, 383.4.d.2.a) - one
    # ability in play_triggers and hold_triggers, as above
    ("when_you_play_me_or_when_i_hold", r"when you play me or when i hold, (?P<inner>.+)",
     ["Core 383.4.a", "Core 420.4.a", "Core 383.4.d", "Core 383.4.d.2.a", "Core 471.2"],
     ["play_triggers", "hold_triggers"],
     ["When you play me or when I hold, draw 1."],
     ["when you play me, draw 1", "when i hold, draw 1", "when i'm played and when i conquer, draw 1"]),
    # 2026-09-25 (Jinx - Loose Cannon): a Beginning Phase trigger (turn_cycle schedules it with
    # the Beginning Step's other effects, Core 315.2.a); both printed spellings
    # 2026-09-27 (Mushroom Pouch): BEFORE the plain row, which would take the condition as its inner
    # instruction and refuse it. The condition is the trigger's (Core 383.2.a.1), not the effect's
    ("at_the_start_of_your_beginning_phase_if_you_control_a_facedown_card_at_a_battlefield",
     r"at (?:the )?start of your beginning phase, if you control a facedown card at a battlefield, (?P<inner>.+)",
     ["Core 315.2.a", "Core 383.2.a.1", "Core 355.9.a.3", "Core 107.3.f"], ["beginning_phase_triggers"],
     ["At the start of your Beginning Phase, if you control a facedown card at a battlefield, draw 1."],
     ["at the start of your beginning phase, draw 1 if you control a facedown card at a battlefield",
      "at the start of your beginning phase, if you control a unit at a battlefield, draw 1",
      "at the start of each player's beginning phase, if you control a facedown card at a battlefield, draw 1"]),
    ("at_the_start_of_your_beginning_phase", r"at (?:the )?start of your beginning phase, (?P<inner>.+)",
     ["Core 315.2.a", "Core 315.2.a.1", "Core 383.1"], ["beginning_phase_triggers"],
     ["At the start of your Beginning Phase, draw 1.", "At start of your Beginning Phase, draw 1."],
     ["at the start of each player's beginning phase, draw 1", "at the end of your turn, draw 1"]),
    # 2026-10-08 (package 10, Sona - Harmonious): the Trigger Condition right after it (Core 383.2.a.1)
    ("at_the_end_of_your_turn_if_im_at_a_battlefield", r"at the end of your turn, if i'm at a battlefield, (?P<inner>.+)",
     ["Core 317.1", "Core 383.1", "Core 383.2.a.1"], ["end_of_turn_triggers"],
     ["At the end of your turn, if I'm at a battlefield, draw 1."],
     ["at the end of your turn, draw 1", "at the end of your turn, if i'm at base, draw 1",
      "at the end of your turn, if you control a battlefield, draw 1"]),
    ("at_the_end_of_your_turn", r"at the end of your turn, (?P<inner>.+)", ["Core 317.1", "Core 383.1"],
     ["end_of_turn_triggers"], ["At the end of your turn, draw 1."],
     ["at the end of each turn, draw 1", "at the beginning of your turn, draw 1"]),
    # 2026-09-24: triggers that watch what happens to ANYTHING, not to the card itself - an
    # event_triggers descriptor with a typed watch (watchers.py), woken by the play
    # transaction ("played") and by every resolution's events. Each row states its watch.
    ("when_you_play_a_spell", r"when you play a spell, (?P<inner>.+)", ["Core 383.1", "Core 420.4.a"],
     ["event_triggers"], ["When you play a spell, draw 1."],
     ["when you play a spell that costs 5 or more, draw 1", "when you play me, draw 1", "when you play a gear, draw 1"]),
    ("when_you_play_a_spell_that_costs_n_or_more",
     r"when you play a spell that costs \[e(?P<cost>\d+)\] or more, (?P<inner>.+)", ["Core 383.1", "Core 420.4.a", "Core 206"],
     ["event_triggers"], ["When you play a spell that costs :rb_energy_5: or more, draw 1."],
     ["when you play a spell, draw 1", "when you play a spell that costs :rb_energy_5: or less, draw 1",
      "when you play a unit that costs :rb_energy_5: or more, draw 1"]),
    ("when_you_play_a_gear", r"when you play a gear, (?P<inner>.+)", ["Core 383.1", "Core 420.4.a"],
     ["event_triggers"], ["When you play a gear, draw 1."], ["when you play a spell, draw 1", "when you play me, draw 1"]),
    ("when_you_play_another_unit", r"when you play another unit, (?P<inner>.+)", ["Core 383.1", "Core 420.4.a"],
     ["event_triggers"], ["When you play another unit, draw 1."], ["when you play a unit, draw 1", "when you play me, draw 1"]),
    # 2026-10-06 package 9 (Volibear - Imposing): an opponent's Move to a Battlefield the source is not at
    ("when_an_opponent_moves_to_a_battlefield_other_than_mine",
     r"when an opponent moves to a battlefield other than mine, (?P<inner>.+)",
     ["Core 383.1", "Core 421", "Core 412.1", "Core 412.4"], ["event_triggers"],
     ["When an opponent moves to a battlefield other than mine, draw 1."],
     ["when an opponent moves to my battlefield, draw 1", "when you move to a battlefield other than mine, draw 1",
      "when an opponent moves to a battlefield, draw 1"]),
    # 2026-09-27: "a [Mighty] unit" - a Unit whose current Might is 5 or greater (Core 708, 710)
    ("when_you_play_a_mighty_unit", r"when you play a \[mighty\] unit, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 708", "Core 710"], ["event_triggers"],
     ["When you play a [Mighty] unit, draw 1."],
     ["when you play a unit, draw 1", "when you play another unit, draw 1", "when an opponent plays a [mighty] unit, draw 1",
      "when a unit becomes [mighty], draw 1", "when you play a [mighty] gear, draw 1"]),
    ("when_you_play_a_card_on_an_opponents_turn", r"when you play a card on an opponent's turn, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a"], ["event_triggers"], ["When you play a card on an opponent's turn, draw 1."],
     ["when you play a card, draw 1", "when an opponent plays a card, draw 1"]),
    # set 2 package A2 (Chemtech Cask)
    ("when_you_play_a_spell_on_an_opponents_turn", r"when you play a spell on an opponent's turn, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a"], ["event_triggers"], ["When you play a spell on an opponent's turn, draw 1."],
     ["when you play a card on an opponent's turn, draw 1", "when you play a spell, draw 1",
      "when an opponent plays a spell, draw 1"]),
    # set 2 package A2 (Yordle Explorer): [A] is one Power of any Domain; the count of them is N
    ("when_you_play_a_card_with_power_cost_n_or_more",
     r"when you play a card with power cost (?P<cost>(?:\[a\])+) or more, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 206"], ["event_triggers"],
     ["When you play a card with Power cost :rb_rune_rainbow::rb_rune_rainbow: or more, draw 1."],
     ["when you play a card with power cost :rb_rune_rainbow::rb_rune_rainbow: or less, draw 1",
      "when you play a card with energy cost :rb_energy_2: or more, draw 1",
      "when you play a spell, draw 1"]),
    # set 2 package A2 (Draven - Glorious Executioner; Corrupt Enforcer): a won combat, the player's (Core 468.3.a) or
    # the Unit's own (468.3.c)
    ("when_you_win_a_combat", r"when you win a combat, (?P<inner>.+)", ["Core 383.1", "Core 468.3", "Core 468.3.a"],
     ["event_triggers"], ["When you win a combat, draw 1."],
     ["when you lose a combat, draw 1", "when an opponent wins a combat, draw 1", "when i win a combat, draw 1"]),
    # set 2 package A2 (Draven - Audacious): the card's own won combat, the first of the turn only
    ("the_first_time_i_win_a_combat_each_turn", r"the first time i win a combat each turn, (?P<inner>.+)",
     ["Core 383.1", "Core 468.3", "Core 468.3.c"], ["event_triggers"],
     ["The first time I win a combat each turn, draw 1."],
     ["when i win a combat, draw 1", "the first time you win a combat each turn, draw 1",
      "the first time i lose a combat each turn, draw 1"]),
    # set 2 package A2 (Draven - Audacious): "When I die" (Core 808.2's own wording of a death trigger) met only when the
    # card was an Attacker or a Defender as its death was noted
    ("when_i_die_in_combat", r"when i die in combat, (?P<inner>.+)", ["Core 383.1", "Core 383.2.a.1", "Core 429", "Core 466"],
     ["self_death_triggers"], ["When I die in combat, draw 1."],
     ["when i die, draw 1", "when a unit dies in combat, draw 1", "when i win a combat, draw 1"]),
    ("when_i_win_a_combat", r"when i win a combat, (?P<inner>.+)", ["Core 383.1", "Core 468.3", "Core 468.3.c"],
     ["event_triggers"], ["When I win a combat, draw 1."],
     ["when you win a combat, draw 1", "when i lose a combat, draw 1", "the first time i win a combat each turn, draw 1"]),
    # set 2 package A2 (Aphelios - Exalted, Jax - Unrelenting): its controller attaches an Equipment to the source
    # (Core 435, 436) - the attach's host is the card itself, the object attached is tagged Equipment
    ("when_you_attach_an_equipment_to_me", r"when you attach an equipment to me, (?P<inner>.+)",
     ["Core 383.1", "Core 435", "Core 436", "Core 133.8"], ["event_triggers"],
     ["When you attach an Equipment to me, draw 1."],
     ["when you attach an equipment, draw 1", "when an equipment is attached to me, draw 1",
      "when you attach an equipment to a unit, draw 1"]),
    # set 2 package A2 (Fae Dragon): each buff its controller spends (Core 702.2.b)
    ("when_you_spend_a_buff", r"when you spend a buff, (?P<inner>.+)", ["Core 383.1", "Core 702.2.b"],
     ["event_triggers"], ["When you spend a buff, draw 1."],
     ["when you buff a unit, draw 1", "when an opponent spends a buff, draw 1"]),
    # set 2 package A2 (Sivir - Battle Mistress): each rune its controller recycles (Core 417)
    ("when_you_recycle_a_rune", r"when you recycle a rune, (?P<inner>.+)", ["Core 383.1", "Core 417"],
     ["event_triggers"], ["When you recycle a rune, draw 1."],
     ["when you recycle a card, draw 1", "when you channel a rune, draw 1"]),
    # set 2 package A2 (Sivir - Battle Mistress): one or more Units of the other side dying together, once (Core 429)
    # set 2 package A2 (Fiora - Worthy, Fiora - Grand Duelist): a Unit its controller controls becomes Mighty - its Might
    # goes from less than 5 to 5 or more on the board (Core 709, 710)
    ("when_a_unit_you_control_becomes_mighty",
     r"when (?:a unit you control|one of your units) becomes \[mighty\], (?P<inner>.+)",
     ["Core 383.1", "Core 708", "Core 709", "Core 710"], ["event_triggers"],
     ["When a unit you control becomes [Mighty], draw 1.", "When one of your units becomes [Mighty], draw 1."],
     ["when a unit becomes [mighty], draw 1", "when an enemy unit becomes [mighty], draw 1",
      "when a unit you control is [mighty], draw 1"]),
    # set 2 package A2: Targeting Effects (Core 383.4.b) - the card itself chosen by its controller's spell (Jae
    # Medarda); a friendly unit chosen by its controller's spell or ability (Spirit Wheel, Irelia - Blade Dancer)
    ("when_you_choose_me_with_a_spell", r"when you choose me with a spell, (?P<inner>.+)",
     ["Core 383.1", "Core 383.4.b", "Core 383.4.b.3", "Core 355.10"], ["event_triggers"],
     ["When you choose me with a spell, draw 1."],
     ["when you choose me, draw 1", "when an opponent chooses me with a spell, draw 1",
      "when you choose me with an ability, draw 1"]),
    # set 2 package A2 (Irelia - Fervent): the card itself chosen by its controller's spell or ability, or readied by its
    # controller - each such event its own trigger
    ("when_you_choose_or_ready_me", r"when you choose or ready me, (?P<inner>.+)",
     ["Core 383.1", "Core 383.4.b", "Core 355.10", "Core 416"], ["event_triggers"],
     ["When you choose or ready me, draw 1."],
     ["when you choose me, draw 1", "when an opponent chooses or readies me, draw 1",
      "when you choose or ready a friendly unit, draw 1"]),
    ("when_you_choose_a_friendly_unit", r"when you choose a friendly unit, (?P<inner>.+)",
     ["Core 383.1", "Core 383.4.b", "Core 383.4.b.3", "Core 355.10"], ["event_triggers"],
     ["When you choose a friendly unit, draw 1."],
     ["when you choose an enemy unit, draw 1", "when you choose a unit, draw 1",
      "when an opponent chooses a friendly unit, draw 1"]),
    # set 2 package A2 (Prize of Progress): its controller uses an activated ability of a Gear (Core 377.2)
    ("when_you_use_an_activated_ability_of_a_gear", r"when you use an activated ability of a gear, (?P<inner>.+)",
     ["Core 383.1", "Core 377", "Core 377.2"], ["event_triggers"],
     ["When you use an activated ability of a gear, draw 1."],
     ["when you use an activated ability of a unit, draw 1", "when you play a gear, draw 1",
      "when an opponent uses an activated ability of a gear, draw 1"]),
    ("when_one_or_more_enemy_units_die", r"when one or more enemy units die, (?P<inner>.+)",
     ["Core 383.1", "Core 429", "Core 429.1"], ["event_triggers"], ["When one or more enemy units die, draw 1."],
     ["when an enemy unit dies, draw 1", "when one or more friendly units die, draw 1"]),
    ("when_you_play_a_card_from_hidden", r"when you play a card from \[hidden\], (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 811.1"], ["event_triggers"], ["When you play a card from [Hidden], draw 1."],
     ["when you play a card, draw 1", "when you hide a card, draw 1"]),
    ("when_you_stun_one_or_more_enemy_units", r"when you stun one or more enemy units, (?P<inner>.+)",
     ["Core 383.1", "Core 424"], ["event_triggers"], ["When you stun one or more enemy units, draw 1."],
     ["when you stun an enemy unit, draw 1", "when a unit is stunned, draw 1"]),
    ("when_you_stun_an_enemy_unit", r"when you stun an enemy unit, (?P<inner>.+)",
     ["Core 383.1", "Core 424", "Core 424.1.a.1"], ["event_triggers"], ["When you stun an enemy unit, draw 1."],
     ["when you stun one or more enemy units, draw 1", "when you stun a unit, draw 1", "when a unit is stunned, draw 1"]),
    ("when_you_discard_one_or_more_cards", r"when you discard one or more cards, (?P<inner>.+)",
     ["Core 383.1", "Core 423", "Core 423.1.b"], ["event_triggers"], ["When you discard one or more cards, draw 1."],
     ["when you discard a card, draw 1", "when an opponent discards one or more cards, draw 1", "when you discard me, draw 1"]),
    ("when_you_recycle_one_or_more_cards_to_your_main_deck",
     r"when you recycle one or more cards to your main deck, (?P<inner>.+)", ["Core 383.1", "Core 421"],
     ["event_triggers"], ["When you recycle one or more cards to your Main Deck, draw 1."],
     ["when you recycle a card, draw 1", "when a card is recycled, draw 1"]),
    ("when_a_buffed_friendly_unit_dies", r"when a buffed friendly unit dies, (?P<inner>.+)",
     ["Core 383.1", "Core 418", "Core 427"], ["event_triggers"], ["When a buffed friendly unit dies, draw 1."],
     ["when a friendly unit dies, draw 1", "when a buffed enemy unit dies, draw 1"]),
    # 2026-09-27: "you kill" - a kill you are responsible for (Core 412.4, 429.5); "stunned", as the unit was
    ("when_you_kill_a_stunned_enemy_unit", r"when you kill a stunned enemy unit, (?P<inner>.+)",
     ["Core 383.1", "Core 412.4", "Core 429.5.b", "Core 429.5.c.1", "Core 429.5.c.2", "Core 424"], ["event_triggers"],
     ["When you kill a stunned enemy unit, draw 1."],
     ["when you kill an enemy unit, draw 1", "when a stunned enemy unit dies, draw 1", "when you kill a stunned unit, draw 1",
      "when you stun an enemy unit, draw 1", "when an opponent kills a stunned enemy unit, draw 1"]),
    # 2026-10-08 (package 10): a Ready / a Buff the player performs on a friendly Unit (Pirate's Haven, Mistfall)
    ("when_you_ready_a_friendly_unit", r"when you ready a friendly unit, (?P<inner>.+)",
     ["Core 383.1", "Core 416", "Core 315.1.b", "Core 416.3.a", "Core 359.3.f.3"], ["event_triggers"],
     ["When you ready a friendly unit, draw 1."],
     ["when you ready a unit, draw 1", "when a friendly unit becomes ready, draw 1", "when you ready an enemy unit, draw 1",
      "when you exhaust a friendly unit, draw 1"]),
    # set 2 (2026-10-29, Simian Ancestor, Altar of Memories)
    ("when_you_buff_me", r"when you buff me, (?P<inner>.+)",
     ["Core 383.1", "Core 702"], ["event_triggers"],
     ["When you buff me, draw 1."],
     ["when you buff a friendly unit, draw 1", "when i'm buffed, draw 1", "when an opponent buffs me, draw 1"]),
    ("when_a_friendly_unit_dies", r"when a friendly unit dies, (?P<inner>.+)",
     ["Core 383.1", "Core 418", "Core 429.1"], ["event_triggers"],
     ["When a friendly unit dies, draw 1."],
     ["when a buffed friendly unit dies, draw 1", "when an enemy unit dies, draw 1",
      "the first time a friendly unit dies each turn, draw 1"]),
    ("when_you_buff_a_friendly_unit", r"when you buff a friendly unit, (?P<inner>.+)",
     ["Core 383.1", "Core 702", "Core 359.3.f.3"], ["event_triggers"],
     ["When you buff a friendly unit, draw 1."],
     ["when you buff a unit, draw 1", "when a friendly unit is buffed, draw 1", "when you buff an enemy unit, draw 1",
      "when you spend a buff, draw 1"]),
    ("the_first_time_a_friendly_unit_dies_each_turn", r"the first time a friendly unit dies each turn, (?P<inner>.+)",
     ["Core 383.1", "Core 418", "Core 383.3.e"], ["event_triggers"],
     ["The first time a friendly unit dies each turn, draw 1."],
     ["when a friendly unit dies, draw 1", "the first time an enemy unit dies each turn, draw 1"]),
    # 2026-09-27: "the Nth time I move" - a watch over the card's own `moved` events (a Standard
    # Move or an effect's, Core 421.2, 448.1), counted per turn and per object; the count reaching
    # N triggers it once (Core 383.1, 383.1.b)
    ("the_first_time_i_move_each_turn", r"the first time i move each turn, (?P<inner>.+)",
     ["Core 383.1", "Core 383.1.b", "Core 421.2", "Core 448.1"], ["event_triggers"],
     ["The first time I move each turn, draw 1."],
     ["the first time a friendly unit dies each turn, draw 1", "when i move, draw 1",
      "the third time i move in a turn, draw 1", "the first time i move each combat, draw 1"]),
    ("the_third_time_i_move_in_a_turn", r"the third time i move in a turn, (?P<inner>.+)",
     ["Core 383.1", "Core 383.1.b", "Core 421.2", "Core 448.1"], ["event_triggers"],
     ["The third time I move in a turn, draw 1."],
     ["the first time i move each turn, draw 1", "the second time i move in a turn, draw 1",
      "when i move, draw 1", "the third time a unit moves in a turn, draw 1"]),
    # 2026-09-27: a player-level Conquer Effect (Core 383.4.c.2.b) - any source the Conquering
    # player controls where its abilities work, a Legend in its Legend Zone included
    # 2026-10-08 (package 10, Garen - Might of Demacia (Starter)): the Trigger Condition right after it (Core 383.2.a.1)
    # 2026-10-14 package 12 (Tryndamere - Barbarian; the site owner's ruling: the community reading, a provisional
    # reading and not a published ruling)
    ("when_i_conquer_after_an_attack_if_you_assigned_n_or_more_excess_damage_to_enemy_units",
     r"when i conquer after an attack, if you assigned (?P<amount>\d+) or more excess damage to enemy units, (?P<inner>.+)",
     ["Core 471.1", "Core 383.4.c", "Core 383.2.a.1", "Core 467.2.c.4"], ["conquer_triggers"],
     ["When I conquer after an attack, if you assigned 5 or more excess damage to enemy units, draw 1."],
     ["when i conquer, if you assigned 5 or more excess damage to enemy units, draw 1",
      "when i conquer after an attack, draw 1",
      "when you conquer after an attack, if you assigned 5 or more excess damage to enemy units, draw 1"]),
    ("when_you_conquer_if_you_have_n_units_at_that_battlefield",
     r"when you conquer, if you have (?P<count>\d+)\+ units at that battlefield, (?P<inner>.+)",
     ["Core 471.1", "Core 383.4.c", "Core 383.4.c.2.b", "Core 383.2.a.1"], ["conquer_triggers"],
     ["When you conquer, if you have 4+ units at that battlefield, draw 2."],
     ["when you conquer, draw 2", "when you conquer here, if you have 4+ units here, draw 2",
      "when you conquer, if you have 4+ units, draw 2", "when you hold, if you have 4+ units at that battlefield, draw 2"]),
    # set 2 package A2 (Yone - Blademaster): the unit's own conquer, of a Battlefield that had no controller before it
    ("when_i_conquer_a_battlefield_that_was_uncontrolled",
     r"when i conquer a battlefield that was uncontrolled, (?P<inner>.+)",
     ["Core 471.1", "Core 383.4.c", "Core 383.4.c.2.a", "Core 383.2.a.1", "Core 190.2.b"],
     ["conquer_triggers"], ["When I conquer a battlefield that was uncontrolled, draw 1."],
     ["when i conquer, draw 1", "when i conquer a battlefield that was controlled, draw 1",
      "when you conquer a battlefield that was uncontrolled, draw 1"]),
    ("when_you_conquer", r"when you conquer, (?P<inner>.+)", ["Core 471.1", "Core 383.4.c", "Core 383.4.c.2.b"],
     ["conquer_triggers"], ["When you conquer, draw 1."],
     ["when you conquer here, draw 1", "when i conquer, draw 1", "when you hold, draw 1",
      "when an opponent conquers, draw 1"]),
    # set 2 package A2 (Renata Glasc - Chem-Baroness): a player-level Hold Effect (Core 383.4.d.2.b), scope controller as
    # "When you conquer"; "or an ally" names a teammate, and the engine models no teams - in its two-player games the
    # Holds are its controller's
    ("when_you_or_an_ally_hold", r"when you or an ally hold, (?P<inner>.+)", ["Core 471.2", "Core 383.4.d",
                                                                              "Core 383.4.d.2.b"],
     ["hold_triggers"], ["When you or an ally hold, draw 1."],
     ["when you hold here, draw 1", "when i hold, draw 1", "when you or an ally conquer, draw 1",
      "when an opponent holds, draw 1"]),
    # 2026-09-27 (package 6): the Nth card a player plays in a turn - every play of the turn counts,
    # one per play Finalized (Core 420.4.b), the ones before the watching card was on the board too
    ("when_you_play_your_second_card_in_a_turn", r"when you play your second card in a turn, (?P<inner>.+)",
     ["Core 383.1", "Core 420.4.a", "Core 420.4.b"], ["event_triggers"],
     ["When you play your second card in a turn, draw 1."],
     ["when you play a card, draw 1", "when you play your third card in a turn, draw 1",
      "when an opponent plays their second card in a turn, draw 1", "when you play a spell, draw 1"]),
    # 2026-09-27 (package 6): a death watched with the dying unit's tags as it was (Core 133.8, 418;
    # a Recruit token has the Recruit tag by Core 187.1); the watching card must still be on the board
    # after the death (Core 383.2.c.2: dying with it, it does not trigger)
    ("when_another_non_recruit_unit_you_control_dies",
     r"when another non-recruit unit you control dies, (?P<inner>.+)",
     ["Core 383.1", "Core 383.2.c.2", "Core 429", "Core 133.8", "Core 187.1"], ["event_triggers"],
     ["When another non-Recruit unit you control dies, draw 1."],
     ["when another unit you control dies, draw 1", "when a non-recruit unit you control dies, draw 1",
      "when another non-recruit unit an opponent controls dies, draw 1", "when a buffed friendly unit dies, draw 1"]),
    # 2026-09-27 (package 6): "When you discard me" works from the trash, the zone discarding puts the
    # card in (Core 423.1, 423.1.b): it is evaluated as the card enters it (383.2.c.1) - from the hand
    # it could not be, since the card leaves the hand as the condition is met (383.2.c.2)
    ("when_you_discard_me", r"when you discard me, (?P<inner>.+)",
     ["Core 383.1", "Core 383.2.c.1", "Core 385.2", "Core 423.1", "Core 423.1.b"], ["event_triggers"],
     ["When you discard me, draw 1."],
     ["when you discard one or more cards, draw 1", "when i am discarded, draw 1",
      "when an opponent discards me, draw 1", "when you discard a card, draw 1"]),
    # 2026-09-27 (package 6): a kill attributed to a spell (Core 429.5.b, 429.5.c, 429.5.d) its controller
    # is responsible for (429.5.c.1)
    ("when_you_kill_a_unit_with_a_spell", r"when you kill a unit with a spell, (?P<inner>.+)",
     ["Core 383.1", "Core 429.5", "Core 429.5.b", "Core 429.5.c", "Core 429.5.c.1", "Core 429.5.d"], ["event_triggers"],
     ["When you kill a unit with a spell, draw 1."],
     ["when you kill a unit, draw 1", "when a unit dies, draw 1", "when an opponent kills a unit with a spell, draw 1",
      "when you kill a gear with a spell, draw 1"]),
    # 2026-09-28: watches over a Unit gaining a combat designation (combat emits `attacked` /
    # `defended`, Core 466.2.c.3), their other requirements read then (383.4.e.2.b, 383.4.f.2.b).
    # The inner clause's "it" is the Unit the event is about (REFERENT_WRAPPERS, Core 359.3.f.3)
    ("when_an_enemy_unit_attacks_a_battlefield_you_control",
     r"when an enemy unit attacks a battlefield you control, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.e.2.b", "Core 466.2.c.3", "Core 190.4.b", "Core 359.3.f.3"],
     ["event_triggers", "combat_designations", "trigger_referent"],
     ["When an enemy unit attacks a battlefield you control, draw 1.",
      "When an enemy unit attacks a battlefield you control, give it -2 :rb_might: this turn, to a minimum of 1 :rb_might:."],
     ["when an enemy unit attacks, draw 1", "when a friendly unit attacks a battlefield you control, draw 1",
      "when an enemy unit defends a battlefield you control, draw 1", "when you attack a battlefield, draw 1"]),
    # set 2 package A2 (Loyal Pup): its controller defends at a Battlefield - its Units gain the Defender designation
    # there, once per combat (Core 383.4.f, 466.2.c.3)
    ("when_you_defend_at_a_battlefield", r"when you defend at a battlefield, (?P<inner>.+)",
     ["Core 383.1", "Core 383.4.f", "Core 466.2.c.3"], ["event_triggers"],
     ["When you defend at a battlefield, draw 1."],
     ["when you attack at a battlefield, draw 1", "when an opponent defends at a battlefield, draw 1",
      "when you defend here, draw 1"]),
    # set 2 package A2 (Fiora - Peerless): the card's own designation, it and the one enemy Unit there both alone
    ("when_i_attack_or_defend_one_on_one", r"when i attack or defend one on one, (?P<inner>.+)",
     ["Core 383.1", "Core 383.4.e", "Core 383.4.f", "Core 740.2.b"], ["event_triggers"],
     ["When I attack or defend one on one, draw 1."],
     ["when i attack or defend alone, draw 1", "when a friendly unit attacks or defends one on one, draw 1",
      "when i attack one on one, draw 1"]),
    ("when_a_friendly_unit_attacks_or_defends_alone", r"when a friendly unit attacks or defends alone, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.f", "Core 383.4.e.2.b", "Core 383.4.f.2.b", "Core 740.2.a", "Core 359.3.f.3"],
     ["event_triggers", "combat_designations", "trigger_referent"],
     ["When a friendly unit attacks or defends alone, draw 1.",
      "When a friendly unit attacks or defends alone, give it +2 :rb_might: this turn."],
     ["when a friendly unit attacks or defends, draw 1", "when a friendly unit attacks alone, draw 1",
      "when an enemy unit attacks or defends alone, draw 1", "when i attack or defend alone, draw 1"]),
    # a Battlefield's own: a Unit's Move whose location before was this Battlefield (Core 448.1); the
    # Battlefield's controller controls it, or, uncontrolled, the Turn Player (190.6.a, 190.6.b)
    ("when_a_unit_moves_from_here", r"when a unit moves from here, (?P<inner>.+)",
     ["Core 383.1", "Core 448.1", "Core 190.6.a", "Core 190.6.b", "Core 359.3.f.3"],
     ["move_from_triggers", "trigger_referent"],
     ["When a unit moves from here, draw 1.", "When a unit moves from here, give it +2 :rb_might: this turn."],
     ["when a unit moves here, draw 1", "when a unit moves to here, draw 1", "when i move from here, draw 1",
      "when a friendly unit moves from here, draw 1"]),
]


# DP-84 wrote the grammar's capability names by hand, and they drifted into a
# second vocabulary: "targeting" for what the engine calls typed_selectors,
# "keyword_catalogue_v1" for keyword_catalog. Every clause then looked like it
# needed a capability the manifest had never heard of, which is exactly the
# drift the manifest exists to prevent. Authoring keeps the readable name; the
# emitted data carries the engine's, and the build fails if a name maps to
# nothing the engine declares.
CAPABILITY_ALIAS = {
    "targeting": "typed_selectors",
    "condition_v1": "typed_conditions",
    "keyword_catalogue_v1": "keyword_catalog",
    "combat_state": "active_combat_criteria",
    "replacement_effects": "bounded_replacement",
    "conquer_triggers": "score_triggers",
    "hold_triggers": "hold_scoring",
    "defend_triggers": "battlefield_defend_triggers",
    "attack_triggers": "attack_defend_triggers",
    "move_restriction": "standard_move",
    "end_of_turn_triggers": "ending_step",
    "might_aura": "continuous_effects",
    "domain_power": "typed_cost_payment",
    "card_self_optional_cost": "self_costs",
    "self_card_conditional_fixed_energy_reduction.v1": "evaluated_cost_modifications",
    "timing_permission_v1": "timing_permission_classification",
    "occupied_enemy_battlefield": "occupied_enemy_battlefield_permission",
    "open_battlefield": "open_battlefield_permission",
    "event_triggers": "watched_triggers",
    "move_from_triggers": "battlefield_move_from_triggers",
}


def engine_capabilities() -> set[str]:
    """Everything this build of the engine declares it supports: its operations
    and every supported scope its check kinds name."""
    from capability_manifest import build_manifest
    manifest = build_manifest()
    return ({entry["id"] for entry in manifest["operations"]}
            | {scope for component in manifest["components"] for scope in component["supported_scope"]})


def resolve_capabilities(names, production_id: str, declared: set[str]) -> list[str]:
    resolved = [CAPABILITY_ALIAS.get(name, name) for name in names]
    unknown = sorted(set(resolved) - declared)
    if unknown:
        raise ValueError(f"{production_id} requires {unknown}, which this engine does not declare; "
                         "add the capability to the engine or map it in CAPABILITY_ALIAS")
    return sorted(dict.fromkeys(resolved))


def main() -> int:
    declared = engine_capabilities()
    productions = list(PRODUCTIONS)
    for pid, pattern, locators, node, capability, boundary, golden, negative in LITERAL:
        productions.append({"production_id": pid, "form": golden[0], "template": pattern, "slots": {},
                            "normalization": N, "rule_locators": locators, "ast_node": node,
                            "required_capability": capability, "boundary": boundary,
                            "golden": golden, "negative": negative})
    for pid, pattern, locators, capability, golden, negative in WRAPPERS:
        productions.append({"production_id": pid, "form": golden[0], "template": pattern, "slots": {},
                            "normalization": N, "rule_locators": locators, "ast_node": "triggered",
                            "required_capability": capability,
                            "boundary": "Wraps one instruction this grammar already has; an unparsed instruction makes the whole clause unparsed.",
                            "golden": golden, "negative": negative})
    for production in productions:
        production["required_capability"] = resolve_capabilities(
            production["required_capability"], production["production_id"], declared)
    grammar = {
        "schema_version": "clause-grammar.v1",
        "version": "2026-09-08.1",
        "ruleset": {"core": __import__("effect_ir").CORE_RULESET, "faq_as_of": __import__("effect_ir").FAQ_AS_OF},
        "complete_grammar": False,
        "note": ("A production is a template over sub-grammar slots (DP-84), not a literal sentence. Its goldens must "
                 "exercise every alternative of every slot it admits, and the cross product of every slot pair listed "
                 "in `jointly_meaningful`; its negatives must include one near-miss per slot. Keyword alternatives are "
                 "generated from keyword-catalog.v1 (DP-85): a keyword the catalogue does not name is not a keyword "
                 "here, and one it names without a production is known_unsupported rather than parsed. Every fixture "
                 "is synthetic or Wave A; real card text beyond the seed stays in the private overlay."),
        "sub_grammars": SUB_GRAMMARS,
        "jointly_meaningful": JOINT,
        "productions": productions,
    }
    OUT.write_text(json.dumps(grammar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(productions)} productions, {len(SUB_GRAMMARS)} sub-grammars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
