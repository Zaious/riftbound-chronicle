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
        alternatives[key] = {
            "pattern": rf"\[{key}(?: (?P<{key}_value>\d+))?\]",
            "value": {"keyword": key, "implemented": bool(entry.get("production"))},
        }
    return alternatives


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
        "rule_locators": ["Core 476", "Core 479", "Core 317.2"],
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
        "rule_locators": ["Core 477.2", "Core 317.2"],
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
        "rule_locators": ["Core 477.3", "Core 460", "Core 462"],
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
        "rule_locators": ["Core 415", "Core 355.9"],
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
        "rule_locators": ["Core 423", "Core 423.1", "Core 423.2", "Core 355.9"],
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
        "rule_locators": ["Core 420", "Core 355.4", "Core 355.4.a", "Core 355.9"],
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
        "rule_locators": ["Core 420", "Core 355.4", "Core 355.4.a", "Core 355.9"],
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
        "rule_locators": ["Core 441", "Core 355.9"],
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
        "rule_locators": ["Core 416", "Core 355.9"],
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
        "rule_locators": ["Core 434", "Core 355.9"],
        "ast_node": "instruction",
        "required_capability": ["recall", "targeting"],
        "boundary": "One chosen object is sent to its controller's Base. Recall is not a Move (434.1).",
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
        "rule_locators": ["Core 426.1", "Core 702"],
        "ast_node": "instruction",
        "required_capability": ["buff", "targeting"],
        "boundary": "One chosen Unit gets a Buff counter. A Unit that already has one is still chosen and is not Buffed again (426.1.c).",
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
        "golden": [f"[{name.title()}][>] " + ("When you play me, draw 1." if name == "legion" else "Draw 1.")
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
        "golden": [f"[{name.title()}]" for name in sorted(keyword_alternatives())],
        "negative": ["[Nonesuch]", "gains [Shield 2] this combat", "[Shield] and [Tank]"],
    },
]

LITERAL = [
    ("draw_n", r"draw (?P<count>\d+)", ["Core 413", "Core 431"], "instruction", ["draw"],
     "The controller draws. 'Each player draws' and 'draw until' are not this production.",
     ["Draw 1.", "Draw 2."], ["each player draws 1", "draw 1, then discard 1"]),
    # 2026-09-25 (Jinx - Loose Cannon): a draw conditioned on the controller's own hand size, read
    # as the instruction executes (effect_ir predicate state_holds)
    ("draw_n_if_you_have_one_or_fewer_cards_in_your_hand",
     r"draw (?P<count>\d+) if you have one or fewer cards in your hand",
     ["Core 413", "Core 359.3.d"], "instruction", ["draw", "condition_v1"],
     "A draw that happens only if the controller holds at most one card when it executes. Another count or zone is a different clause.",
     ["Draw 1 if you have one or fewer cards in your hand."],
     ["draw 1 if you have two or fewer cards in your hand", "draw 1 if an opponent has one or fewer cards in their hand", "draw 1"]),
    # 2026-09-27 (Kadregrin the Infernal): a draw counted as it executes - the printed number for
    # each unit its controller controls that is Mighty, Might 5 or greater (Core 708, 710)
    ("draw_n_for_each_of_your_mighty_units", r"draw (?P<count>\d+) for each of your \[mighty\] units",
     ["Core 413", "Core 708", "Core 710"], "instruction", ["draw"],
     "The controller draws the number times how many units they control are Mighty when it executes; none is no draw. "
     "Another quality, or another player's units, is a different clause.",
     ["Draw 1 for each of your [Mighty] units."],
     ["draw 1 for each of your units", "draw 1 for each enemy [mighty] unit", "draw 1 if you control a [mighty] unit"]),
    # 2026-09-25: the controller discards N from their own hand, chosen privately (Core 422.1);
    # a hand shorter than N discards what it has, an empty hand ignores it (422.4). Returned
    # now that ", then" no longer makes the next instruction depend on it (GPT 2026-09-25).
    ("discard_n", r"discard (?P<count>\d+)", ["Core 422.1", "Core 422.1.a", "Core 422.4"], "instruction",
     ["private_discard"],
     "The controller discards from their own hand. Discarding at random, or another player's discard, is a different production.",
     ["Discard 1.", "Discard 2."], ["discard 2 at random", "each player discards 1", "discard your hand"]),
    ("deal_n_to_a_unit_at_a_battlefield", r"deal (?P<amount>\d+) to a unit at (?:a )?battlefield",
     ["Core 417", "Core 355.9"], "instruction", ["deal_damage", "targeting"],
     "One chosen Unit at a Battlefield. A Might restriction on the target is a different production.",
     ["Deal 2 to a unit at a battlefield.", "Deal 3 to a unit at battlefield."],
     ["deal 2 to a unit at a battlefield with 3 [m] or less", "deal 2 to all units at a battlefield"]),
    # 2026-09-25 (The Syren): a chosen friendly Unit at a Battlefield goes to its own Base
    # 2026-10-06 package 9 (The Grand Plaza): an effect that instructs its controller to win (Core 195); the game
    # ends at once (196)
    ("you_win_the_game", r"you win the game", ["Core 195", "Core 196"], "instruction", ["win_game"],
     "The instruction's controller wins and the game ends at once. 'You lose the game' and 'an opponent wins the "
     "game' are different productions.",
     ["You win the game."], ["you lose the game", "you win", "an opponent wins the game"]),
    ("move_a_friendly_unit_at_a_battlefield_to_its_base", r"move a friendly unit at (?:a )?battlefield to its base",
     ["Core 420", "Core 355.4", "Core 355.4.a", "Core 355.9"], "instruction", ["move_board_object", "targeting"],
     "One chosen friendly Unit at a Battlefield moves to its own Base. A Unit in a Base, an enemy Unit, or "
     "'to or from its base' is a different production.",
     ["Move a friendly unit at a battlefield to its base."],
     ["move a friendly unit to its base", "move an enemy unit at a battlefield to its base",
      "move a friendly unit to or from its base"]),
    ("move_a_unit_from_a_battlefield_to_its_base", r"move a unit from (?:a )?battlefield to its base",
     ["Core 420", "Core 355.4", "Core 355.4.a", "Core 141.1.a.1", "Core 144.4.b", "Core 355.9.b", "Core 355.10.b"],
     "instruction", ["move_board_object", "targeting"],
     "One chosen Unit at a Battlefield, of either side, moves to its own Base (its controller's). A Unit in a "
     "Base is not a legal target; 'a friendly unit at a battlefield' is a different production.",
     ["Move a unit from a battlefield to its base."],
     ["move a unit to its base", "move a friendly unit from a battlefield to its base",
      "move a unit from a battlefield to your base"]),
    ("deal_n_to_all_enemy_units_at_a_battlefield", r"deal (?P<amount>\d+) to all enemy units at a battlefield",
     ["Core 417", "Core 355.10.b", "Core 715.2"], "instruction", ["deal_damage", "criteria_expansion"],
     "One chosen Battlefield, then every enemy Unit there.",
     ["Deal 3 to all enemy units at a battlefield."],
     ["deal 3 to all units at a battlefield", "deal 3 to all enemy units in combat"]),
    # GPT 2026-09-23: "here" - the resolving program's own source's current
    # Battlefield (Core 359.3.f.1, 359.3.f.2) - takes no decision at all,
    # unlike "at a battlefield"'s own Battlefield choice above. Anivia - Primal
    # is this production's real card (round 2 / D, when i attack).
    ("deal_n_to_all_enemy_units_here", r"deal (?P<amount>\d+) to all enemy units here",
     ["Core 417", "Core 355.10.b", "Core 715.2", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction",
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
     ["Core 417", "Core 355.14", "Core 355.14.a", "Core 355.14.b", "Core 355.14.c", "Core 355.14.e",
      "Core 355.14.f", "Core 355.14.h", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction", ["deal_damage", "targeting"],
     ("Up to N chosen enemy Units at the source's current Battlefield, the N divided among them at resolution, a "
      "positive amount each. Damage to every enemy Unit here, one chosen Unit, a split at a chosen Battlefield, or a "
      "split whose amount is read off the board is a different production."),
     ["Deal 5 damage split among any number of enemy units here."],
     ["deal 5 damage split among any number of enemy units at a battlefield", "deal 5 to all enemy units here",
      "deal 5 to an enemy unit here", "deal damage equal to its might split among enemy units at battlefields"]),
    ("deal_n_to_an_enemy_unit_here", r"deal (?P<amount>\d+) to an enemy unit here",
     ["Core 417", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction", ["deal_damage", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield. 'For each', a second target, or "
     "damage to all enemy Units here is a different production.",
     ["Deal 1 to an enemy unit here."],
     ["deal 1 to an enemy unit at a battlefield", "deal 1 to all enemy units here",
      "deal 1 to an enemy unit here for each card with [hidden]"]),
    # "equal to my Might": the amount is the source's current Might, read on execution
    # (Core 359.3.f.2's own Yasuo, Remorseful example, Stupefied in response); the target
    # is "an enemy unit here" as above.
    ("deal_damage_equal_to_my_might_to_an_enemy_unit_here", r"deal damage equal to my might to an enemy unit here",
     ["Core 417", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2", "Core 359.3.f.4"], "instruction",
     ["deal_damage", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield takes damage equal to the source's Might "
     "as it is when the instruction executes.",
     ["Deal damage equal to my Might to an enemy unit here."],
     ["deal damage equal to my might to an enemy unit", "deal 3 to an enemy unit here",
      "deal damage equal to its might to an enemy unit here"]),
    ("stun_an_enemy_unit_here", r"stun an enemy unit here",
     ["Core 423", "Core 423.1", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction", ["stun", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield becomes Stunned.",
     ["Stun an enemy unit here."],
     ["stun an enemy unit", "stun all enemy units here", "stun a unit here"]),
    ("give_an_enemy_unit_here_might_this_turn",
     r"give an enemy unit here (?P<sign>[+-])(?P<amount>\d+) \[m\] this turn(?:, to a minimum of (?P<floor>\d+) \[m\])?",
     ["Core 476", "Core 479", "Core 317.2", "Core 355.9", "Core 359.3.f.1", "Core 359.3.f.2"], "instruction",
     ["modify_might", "targeting"],
     "One chosen enemy Unit at the source's current Battlefield, a signed Might change this turn, with "
     "the floor the text states.",
     ["Give an enemy unit here -2 [M] this turn, to a minimum of 1 [M].", "Give an enemy unit here -1 [M] this turn.",
      "Give an enemy unit here +1 [M] this turn."],
     ["give an enemy unit -2 [m] this turn", "give enemy units here -2 [m] this turn",
      "give an enemy unit here -2 [m] this combat"]),
    ("deal_n_to_all_enemy_units_in_combat", r"deal (?P<amount>\d+) to all enemy units in combat",
     ["Core 417", "Core 715.2", "Core 460"], "instruction", ["deal_damage", "criteria_expansion", "combat_state"],
     "The Combat in progress. Outside one the instruction finds nothing.",
     ["Deal 2 to all enemy units in combat."],
     ["deal 2 to all enemy units at a battlefield", "deal 2 to all units in combat"]),
    ("deal_n_to_all_units_at_battlefields", r"deal (?P<amount>\d+) to all units at battlefields",
     ["Core 417", "Core 355.10.b"], "instruction", ["deal_damage", "criteria_expansion"],
     "Every Unit at every Battlefield, and none in a Base.",
     ["Deal 3 to all units at battlefields."],
     ["deal 3 to all enemy units at a battlefield", "deal 3 to all units at a battlefield"]),
    ("channel_n_rune_exhausted", r"channel (?P<count>\d+) runes? exhausted",
     ["Core 430", "Core 430.3"], "instruction", ["channel_rune"],
     "Entering exhausted. A Channel with no entry state is a different production.",
     ["Channel 1 rune exhausted."], ["channel 1 rune", "channel 1 rune ready"]),
    ("return_a_unit_from_your_trash_to_your_hand", r"return a unit from your trash to your hand",
     ["Core 415", "Core 124"], "instruction", ["return_to_hand", "targeting"],
     "A Unit, from the controller's own Trash.",
     ["Return a unit from your trash to your hand."],
     ["return a spell from your trash to your hand", "return a unit at a battlefield to its owner's hand"]),
    ("while_you_have_n_runes_i_have_might", r"while you have (?P<runes>\d+)\+ runes, i have \+(?P<amount>\d+) \[m\]",
     ["Core 364.3", "Core 476", "Core 479"], "conditional_might", ["continuous_effects", "condition_v1"],
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
     ["Core 317.2", "Core 419.4"], "instruction", ["grant_turn_effect"],
     "Entry state for this turn's own plays.",
     ["Units you play this turn enter ready."],
     ["units you play this turn enter exhausted", "i enter ready"]),
    # 2026-09-27: delayed passives for the NEXT card of a kind played this turn, spent by that play
    # (Core 390.4, 391): a discount on the next spell's cost (356.4), and the next unit's entry state
    ("the_next_spell_you_play_this_turn_costs_n_less",
     r"the next spell you play this turn costs \[e(?P<amount>\d+)\] less",
     ["Core 390.4", "Core 391", "Core 356.4", "Core 356.6"], "instruction", ["grant_turn_effect"],
     "One discount of a fixed Energy amount on the next spell its controller plays this turn, spent by that play "
     "whether or not it lowered anything. Every spell, a Power amount, or a unit is a different clause.",
     ["The next spell you play this turn costs :rb_energy_5: less."],
     ["spells you play this turn cost :rb_energy_1: less", "the next unit you play this turn costs :rb_energy_2: less",
      "the next spell you play this turn costs :rb_rune_rainbow: less"]),
    ("the_next_unit_you_play_this_turn_enters_ready", r"the next unit you play this turn enters ready",
     ["Core 390.4", "Core 391", "Core 369.3", "Core 143.4"], "instruction", ["grant_turn_effect"],
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
    ("self_cost_reduction_fixed", r"i cost \[e(?P<amount>\d+)\] less",
     ["Core 356.4"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text and a fixed Energy amount. It is the ability a [Legion] gates (812.1.b.1); a variable amount, Power, or a value read off the board is a different clause.",
     ["I cost :rb_energy_2: less."],
     ["i cost :rb_rune_rainbow: less", "i cost [e] less", "units cost :rb_energy_2: less"]),
    ("my_might_is_increased_by_your_points", r"my might is increased by your points",
     ["Core 477.3", "Core 477.3.b", "Core 364.3"], "dynamic_might", ["continuous_effects"],
     "A passive increase of the card's own Might by its controller's points, computed fresh each time (477.3.b). Another quantity, or another object's Might, is a different clause.",
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
    # 356.4, 428.1): a Unit on the named side of its player died this turn.
    ("self_cost_reduction_unit_died",
     r"if an? (?P<relation>enemy|friendly) unit has died this turn, this costs \[e(?P<amount>\d+)\] less",
     ["Core 356.4", "Core 356.4.b", "Core 428.1", "Core 428.2.a"], "self_cost_reduction",
     ["self_card_conditional_fixed_energy_reduction.v1"],
     ("The card's own text, a fixed Energy amount, gated by a Unit of the named side having died this turn - the "
      "side as it was when it died. A unit that died last turn, a unit that left the board another way, or a "
      "Power reduction is a different clause."),
     ["If an enemy unit has died this turn, this costs :rb_energy_2: less."],
     ["if an enemy unit has died this turn, this costs :rb_rune_rainbow: less",
      "if an enemy unit died last turn, this costs :rb_energy_2: less",
      "if an enemy unit has been banished this turn, this costs :rb_energy_2: less"]),
    # 2026-09-24: a unit's printed static aura - a continuous Might effect over the other
    # friendly units at its own Battlefield, read live off the object while it is on the
    # board (effect_ir.printed_aura_effects; check_static_auras.py).
    ("other_friendly_units_have_might_here",
     r"other friendly units have \+(?P<amount>\d+) \[m\] here",
     ["Core 365.1", "Core 476", "Core 477.3", "Core 479"], "passive", ["might_aura"],
     ("A printed aura: +N Might to every other friendly Unit at the Battlefield where the source is, while the "
      "source is on the board. Not a target, not snapshotted. A keyword instead of Might, a whole-board aura, "
      "or an aura on enemy units is a different clause."),
     ["Other friendly units have +1 :rb_might: here."],
     ["other friendly units have +2 :rb_might:", "other friendly units here have [assault]",
      "friendly units have +1 :rb_might: here", "stunned enemy units here have -8 :rb_might:"]),
    ("other_buffed_friendly_units_at_my_battlefield_have_might",
     r"other buffed friendly units at my battlefield have \+(?P<amount>\d+) \[m\]",
     ["Core 365.1", "Core 476", "Core 477.3", "Core 479", "Core 426.1.b"], "passive", ["might_aura"],
     ("The same aura restricted to Units with a Buff counter: a Unit that loses its Buff stops receiving it at "
      "once. An unbuffed or a whole-board variant is a different clause."),
     ["Other buffed friendly units at my battlefield have +2 :rb_might:."],
     ["other friendly units at my battlefield have +2 :rb_might:", "buffed friendly units have +2 :rb_might:",
      "other buffed friendly units have [deflect]"]),
    ("units_here_have_might",
     r"units here have \+(?P<amount>\d+) \[m\]",
     ["Core 365.1", "Core 190.6", "Core 476", "Core 477.3", "Core 479"], "passive", ["might_aura"],
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
    # snapshot, 477.3.b); effect_ir.printed_aura_effects, check_stunned_aura.py
    ("stunned_enemy_units_here_have_might_to_a_minimum",
     r"stunned enemy units here have -(?P<amount>\d+) \[m\], to a minimum of (?P<floor>\d+) \[m\]",
     ["Core 365.1", "Core 423.1.a", "Core 476", "Core 477.3", "Core 477.3.b", "Core 479"], "passive", ["might_aura"],
     ("A printed aura: -N Might, to a minimum of M, to every enemy Unit at the Battlefield where the source is that "
      "is Stunned right now (423.1.a), while the source is on the board. The floor is applied fresh each time the "
      "Might is computed (477.3.b). Friendly or unstunned units, a decrease without the floor, or a whole-board "
      "aura is a different clause."),
     ["Stunned enemy units here have -8 :rb_might:, to a minimum of 1 :rb_might:."],
     ["stunned enemy units here have -8 :rb_might:", "enemy units here have -8 :rb_might:, to a minimum of 1 :rb_might:",
      "stunned friendly units here have -8 :rb_might:, to a minimum of 1 :rb_might:",
      "stunned enemy units have -8 :rb_might:, to a minimum of 1 :rb_might:"]),
    # 2026-09-27: printed keyword auras - a keyword granted in the Ability layer (477.2, 477.2.b),
    # read live off the source (effect_ir.printed_aura_effects; check_keyword_auras.py). Each
    # admits only the keywords its gate exercises.
    ("units_here_have_keyword",
     r"units here have \[(?P<keyword>ganking)\]",
     ["Core 365.1", "Core 190.6", "Core 476", "Core 477.2", "Core 477.2.b", "Core 810.1.b"], "passive", ["might_aura", "layer_engine"],
     ("A Battlefield's printed keyword aura: every Unit at it, whoever controls it, has the keyword while it is "
      "there. A Might amount, 'friendly' / 'enemy' units, a keyword with a value, or a timed grant is a different clause."),
     ["Units here have [Ganking]."],
     ["units here have +1 :rb_might:", "friendly units here have [ganking]", "units have [ganking]",
      "units here have [ganking] this turn"]),
    ("other_friendly_units_here_have_keyword",
     r"other friendly units here have \[(?P<keyword>assault|shield)\]",
     ["Core 365.1", "Core 476", "Core 477.2", "Core 477.2.b", "Core 807.2", "Core 814.2"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every other friendly Unit at the Battlefield where the source is, while the source "
      "is on the board; values are summed with the Unit's own (807.2, 814.2). A Might amount, the source itself, "
      "a whole-board aura or a keyword with a value is a different clause."),
     ["Other friendly units here have [Assault].", "Other friendly units here have [Shield]."],
     ["other friendly units here have +1 :rb_might:", "friendly units here have [assault]",
      "other friendly units have [assault]", "other friendly units here have [assault 2]"]),
    ("other_friendly_units_have_keyword",
     r"other friendly units have \[(?P<keyword>vision)\]",
     ["Core 365.1", "Core 476", "Core 477.2", "Core 477.2.b", "Core 817.2"], "passive", ["might_aura", "layer_engine"],
     ("A printed keyword aura over every other friendly Unit on the board, while the source is there. Each "
      "instance of Vision triggers separately (817.2), so a Unit with its own Vision played under this aura "
      "triggers twice. 'here', the source itself, or another keyword is a different clause."),
     ["Other friendly units have [Vision]."],
     ["other friendly units here have [vision]", "friendly units have [vision]", "other friendly units have [tank]"]),
    # 2026-09-27: a card's own conditional keywords (364.3.a), each a keyword_grant on the card
    # itself that applies only while its condition holds; the condition is evaluated in the
    # Ability layer - for Mighty (708) from the layer result in progress (476.2, 476.3).
    ("while_im_buffed_i_have_keywords",
     r"while i'm buffed, i have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 364.3", "Core 364.3.a", "Core 365.1", "Core 477.2", "Core 702.2.a"], "conditional_keywords",
     ["continuous_effects", "condition_v1", "conditional_passives", "buff_counters"],
     ("The card's own keywords while it has a Buff counter (702.2.a); spent, it no longer has them. Another "
      "object's Buff, a Might amount, or a keyword with a value is a different clause."),
     ["While I'm buffed, I have [Ganking]."],
     ["while i'm buffed, i have an additional +1 :rb_might:", "while a friendly unit is buffed, i have [ganking]",
      "while i'm buffed, i have [ganking 2]"]),
    ("if_you_discarded_a_card_this_turn_i_have_keywords",
     r"if you've discarded a card this turn, i have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 364.3", "Core 364.3.a", "Core 365.1", "Core 477.2", "Core 422.1"], "conditional_keywords",
     ["continuous_effects", "condition_v1", "conditional_passives", "private_discard"],
     ("The card's own keywords while its controller has discarded at least one card this turn - by an "
      "instruction or as a cost (422.1, 422.3). An opponent's discard, another turn, or a count other than one "
      "is a different clause."),
     ["If you've discarded a card this turn, I have [Assault] and [Ganking]."],
     ["if an opponent has discarded a card this turn, i have [assault]", "if you've discarded two cards this turn, i have [assault]",
      "when you discard a card, i have [assault]"]),
    ("while_im_mighty_i_have_keywords",
     r"while i'm \[mighty\], i have (?P<keywords>\[[a-z]+\](?:(?:,? and |, )\[[a-z]+\])*)",
     ["Core 364.3", "Core 364.3.a", "Core 365.1", "Core 476.2", "Core 476.3", "Core 477.2", "Core 708"], "conditional_keywords",
     ["continuous_effects", "condition_v1", "conditional_passives", "layer_engine"],
     ("The card's own keywords while its own Might is 5 or more (708), read from the layers in progress: a Buff "
      "added in the Arithmetic layer makes it Mighty and the Ability layer is evaluated again (476.2); once the "
      "grant is disqualified it is not re-applied (476.3). Another unit's Might is a different clause."),
     ["While I'm [Mighty], I have [Deflect], [Ganking], and [Shield]."],
     ["while a friendly unit is [mighty], i have [ganking]", "while i'm [mighty], i have +2 :rb_might:",
      "when i become [mighty], i have [ganking]"]),
    ("while_im_buffed_i_have_an_additional_might",
     r"while i'm buffed, i have an additional \+(?P<amount>\d+) \[m\]",
     ["Core 364.3", "Core 364.3.a", "Core 702.2.a", "Core 703", "Core 477.3"], "conditional_might",
     ["continuous_effects", "condition_v1", "conditional_passives", "buff_counters"],
     ("+N Might on the card itself while it has a Buff counter, on top of the Buff's own +1 (703). Another "
      "object's Buff or a keyword is a different clause."),
     ["While I'm buffed, I have an additional +1 :rb_might:."],
     ["while i'm buffed, i have [ganking]", "while a friendly unit is buffed, i have an additional +1 :rb_might:",
      "while i'm buffed, i have +1 :rb_might:"]),
    ("i_get_might_for_each_buffed_friendly_unit_at_my_battlefield",
     r"i get \+(?P<amount>\d+) \[m\] for each buffed friendly unit at my battlefield",
     ["Core 364.1", "Core 477.3", "Core 477.3.b", "Core 702.2.a"], "dynamic_might", ["continuous_effects", "buff_counters"],
     ("A passive increase of the card's own Might by the number of Units with a Buff counter, friendly to its "
      "controller, at the Battlefield it is at - itself included ('friendly', not 'other'); none while it is in "
      "a Base. Computed fresh each time (477.3.b). Enemy or unbuffed units, or 'here' elsewhere, are a different clause."),
     ["I get +1 :rb_might: for each buffed friendly unit at my battlefield."],
     ["i get +1 :rb_might: for each friendly unit at my battlefield", "i get +1 :rb_might: for each buffed enemy unit at my battlefield",
      "i get +1 :rb_might: for each other buffed friendly unit at my battlefield"]),
    ("my_might_is_increased_by_the_number_of_cards_in_your_trash",
     r"my might is increased by the number of cards in your trash",
     ["Core 364.1", "Core 477.3", "Core 477.3.b", "Core 108.2.b"], "dynamic_might", ["continuous_effects"],
     ("A passive increase of the card's own Might by the number of cards in its controller's Trash, a public "
      "zone, computed fresh each time (477.3.b). An opponent's Trash, or another zone, is a different clause."),
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
    # 2026-09-27 (package 5): a Battlefield's printed Bonus Damage over the Units at it - every
    # Deal of a spell or ability, whoever controls it, to a Unit there (effect_ir.bonus_damage,
    # scope `location`); check_battlefield_passives.py
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
     ["Core 107.3.b", "Core 107.3.b.1", "Core 107.3.c", "Core 421.1"], "passive", ["facedown_zone", "hide_action"],
     ("A Battlefield's printed statement: its Facedown Zone holds one card more than the one of 107.3.b - two - "
      "while it is in play. Only this Battlefield's zone; hiding still needs control of it (107.3.c). 'Two "
      "additional cards', or a statement on another object, is a different clause."),
     ["You may hide an additional card here."],
     ["you may hide a card here", "you may hide an additional card", "you may hide two additional cards here",
      "you may play an additional card here"]),
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
    ("choose_an_opponent",
     r"choose an opponent",
     ["Core 355.1", "Core 355.17"], "instruction", ["choose_player"],
     ("The whole instruction is a choice of one opponent. It changes nothing; what it leaves is the "
      "receipt the clauses after it read, so 'they' means this opponent and not whoever matches later."),
     ["Choose an opponent."],
     ["choose a player", "choose an opponent unit", "each opponent"]),
    ("they_reveal_their_hand",
     r"they reveal their hand",
     ["Core 424.2.b", "Core 128.4"], "instruction", ["reveal"],
     ("The opponent an earlier clause chose reveals their whole hand (424.2.b: a hand reveal shows every "
      "card, so it takes no count). The clause abstains unless an earlier clause chose the player."),
     ["They reveal their hand."],
     ["reveal your hand", "they reveal 2 cards", "each opponent reveals their hand"]),
    ("choose_a_non_unit_card_from_it_and_recycle_that_card",
     r"choose a non-unit card from it, and recycle that card",
     ["Core 424.3.a", "Core 433", "Core 355.10.a"], "instruction", ["recycle", "reveal"],
     ("One card from what the preceding reveal actually put on the table, excluding Units, recycled. "
      "The candidates are the reveal's own marks, so nothing still private is choosable."),
     ["Choose a non-unit card from it, and recycle that card."],
     ["choose a card from it, and recycle that card",
      "choose a non-unit card from their hand, and recycle that card",
      "choose a non-unit card from it"]),
    ("you_may_play_me_to_an_occupied_enemy_battlefield",
     r"you may play me to an occupied enemy battlefield",
     ["Core 355.2.a", "Core 355.2.b", "Core 170.11.a", "Core 323.6"], "passive",
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
    # 2026-09-27 package 6: a state the chosen object or the set must be in (Core 414.2 Exhausted,
    # 415.2 Ready, 142 damage marked), bounded and criteria buffs, and two effect conditions read as
    # the instruction executes (Core 383.2.a.1: an "if" not right after the trigger condition)
    ("buff_an_exhausted_friendly_unit", r"buff an exhausted friendly unit",
     ["Core 426.1", "Core 702.2.a", "Core 414.2", "Core 355.9", "Core 359.3.e.2"], "instruction", ["buff", "targeting"],
     "One chosen friendly Unit that is Exhausted when chosen and when buffed. Any friendly unit, an enemy unit, "
     "a Ready unit, or every exhausted unit is a different clause.",
     ["Buff an exhausted friendly unit."],
     ["buff a friendly unit", "buff an exhausted enemy unit", "buff a ready friendly unit",
      "buff all exhausted friendly units"]),
    ("ready_something_else_thats_exhausted", r"ready something else that's exhausted",
     ["Core 415.1", "Core 414.2", "Core 355.9.a", "Core 359.3.e.2"], "instruction", ["ready", "targeting"],
     "One chosen object of any type on the board, or a Legend in its Legend Zone (GPT 2026-10-02), not the source "
     "itself, that is Exhausted when chosen and when readied. The source included, a Ready object, or one type only "
     "is a different clause.",
     ["Ready something else that's exhausted."],
     ["ready something that's exhausted", "ready another unit", "ready something else",
      "ready a unit that's exhausted"]),
    ("give_me_might_this_turn_if_there_is_a_ready_enemy_unit_here",
     r"give me (?P<sign>[+-])(?P<amount>\d+) \[m\] this turn if there is a ready enemy unit here",
     ["Core 476", "Core 479", "Core 317.2", "Core 383.2.a.1", "Core 415.2", "Core 359.3.f.2"], "instruction",
     ["modify_might", "condition_v1"],
     "The source's own Might this turn, only if an enemy Unit that is Ready stands at the source's Battlefield as "
     "the instruction executes. Any enemy unit, an exhausted one, or a condition right after the trigger "
     "condition is a different clause.",
     ["Give me +2 [M] this turn if there is a ready enemy unit here."],
     ["give me +2 [m] this turn if there is an enemy unit here", "give me +2 [m] this turn",
      "give me +2 [m] this turn if there is an exhausted enemy unit here",
      "give me +2 [m] this turn if there is a ready friendly unit here"]),
    ("buff_up_to_two_other_friendly_units", r"buff up to two other friendly units",
     ["Core 426.1", "Core 355.13", "Core 355.8", "Core 359.3.e.8"], "instruction", ["buff", "targeting"],
     "One choice of zero to two friendly Units, the source not among them, each buffed on its own. The source "
     "allowed, exactly two, or every friendly unit is a different clause.",
     ["Buff up to two other friendly units."],
     ["buff up to two friendly units", "buff two other friendly units", "buff all other friendly units",
      "buff up to three other friendly units"]),
    ("buff_all_friendly_units", r"(?:then )?buff all friendly units",
     ["Core 426.1", "Core 426.1.b.1", "Core 355.10.d"], "instruction", ["buff", "criteria_expansion"],
     "Every friendly Unit on the board - Bases and Battlefields - found by criteria, not targeted. Other friendly "
     "units, enemy units, or friendly units at one place is a different clause.",
     ["Buff all friendly units.", "Then buff all friendly units."],
     ["buff all other friendly units", "buff all enemy units", "buff all friendly units here",
      "buff a friendly unit"]),
    ("if_i_am_at_a_battlefield_buff_all_other_friendly_units_there",
     r"(?:then, )?if i am at (?:a )?battlefield, buff all other friendly units there",
     ["Core 426.1", "Core 355.10.d", "Core 359.3.f.2", "Core 383.2.a.1", "Core 107.2.b"], "instruction",
     ["buff", "criteria_expansion", "condition_v1"],
     "Only if the source stands at a Battlefield as the instruction executes: every friendly Unit at that "
     "Battlefield but the source. The source included, every friendly unit, or a condition right after the "
     "trigger condition is a different clause.",
     ["If I am at a battlefield, buff all other friendly units there.",
      "Then, if I am at a battlefield, buff all other friendly units there."],
     ["if i am at a battlefield, buff all friendly units there", "buff all other friendly units there",
      "if i am at a battlefield, buff all other friendly units", "if i am in my base, buff all other friendly units there"]),
    ("kill_all_damaged_enemy_units_here", r"kill all damaged enemy units here",
     ["Core 428", "Core 142", "Core 355.10.d", "Core 359.3.f.2"], "instruction", ["kill", "criteria_expansion"],
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
     ["Core 383.1", "Core 419.4.a", "Core 383.2.a.1", "Core 133.8.a"], ["play_triggers", "condition_v1"],
     ["When you play me, if you control a Poro, draw 1."],
     ["when you play me, draw 1 if you control a poro", "when you play me, if you control a unit, draw 1",
      "when you play a poro, draw 1", "when i move, if you control a poro, draw 1"]),
    ("when_you_play_me", r"when you play me, (?P<inner>.+)", ["Core 383.1", "Core 419.4.a"], ["play_triggers"],
     ["When you play me, channel 1 rune exhausted.", "When you play me, draw 1."],
     ["when you play a unit, draw 1", "when i move, draw 1"]),
    ("when_i_move", r"when i move, (?P<inner>.+)", ["Core 383.1", "Core 420"], ["move_triggers"],
     ["When I move, draw 1."], ["when a unit moves, draw 1", "when you play me, draw 1"]),
    # 2026-09-24: the same Move trigger, met only when the completed Move's destination is a
    # Battlefield (effect_ir: condition moved_to_battlefield, read on move_triggers only)
    ("when_i_move_to_a_battlefield", r"when i move to a battlefield, (?P<inner>.+)", ["Core 383.1", "Core 420"],
     ["move_triggers"], ["When I move to a battlefield, draw 1."],
     ["when i move, draw 1", "when i move to base, draw 1", "when a unit moves to a battlefield, draw 1"]),
    # 2026-10-06 package 9 (The Grand Plaza): the conditional statement right after "When you hold here" is part of
    # the Trigger Condition (Core 383.2.a.1) - on the Battlefield's hold descriptor, read as the Hold is processed
    ("when_you_hold_here_if_you_have_n_units_here",
     r"when you hold here, if you have (?P<count>\d+)\+ units here, (?P<inner>.+)",
     ["Core 469.2", "Core 190.6.a", "Core 383.2.a.1"], ["hold_triggers"],
     ["When you hold here, if you have 7+ units here, you win the game."],
     ["when you hold here, you win the game", "when you conquer here, if you have 7+ units here, draw 1",
      "when you hold here, if you control 7 units, draw 1"]),
    ("when_you_hold_here", r"when you hold here, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 469.2", "Core 190.6.a", "Core 383.3"], ["hold_triggers"],
     ["When you hold here, draw 1.", "When you hold here, you may channel 1 rune exhausted."],
     ["when you conquer here, draw 1", "when i hold, draw 1", "when you hold here, summon a dragon"]),
    # A Battlefield's own Conquer trigger: its controller - the player who just established
    # control there and Conquered (Core 348.2.a, 469.1) - controls it (190.6.a); it goes on
    # the Chain with the Score's other triggers (471.2). Distinct from a Unit's "When I conquer".
    ("when_you_conquer_here", r"when you conquer here, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 469.1", "Core 471.2", "Core 190.6.a", "Core 383.3"], ["conquer_triggers"],
     ["When you conquer here, draw 1.", "When you conquer here, you may channel 1 rune exhausted."],
     ["when you hold here, draw 1", "when i conquer, draw 1", "when you conquer, draw 1"]),
    # A Battlefield's own Defend trigger: it triggers when its controller gains the Defender
    # designation in a Combat there (Core 383.4.f, 190.6.a, 190.6.d); open_combat schedules
    # it after the Attack triggers (464.2.e.1). Distinct from a Unit's "When I defend".
    ("when_you_defend_here", r"when you defend here, (?P<optional>you may )?(?P<inner>.+)",
     ["Core 383.4.f", "Core 190.6.a", "Core 190.6.d", "Core 464.2.e.1", "Core 383.3"], ["defend_triggers"],
     ["When you defend here, draw 1.", "When you defend here, you may channel 1 rune exhausted."],
     ["when you attack here, draw 1", "when i defend, draw 1", "when you conquer here, draw 1"]),
    # A Unit's own Hold Effect (Core 383.4.d): it goes on the Chain after the Unit is present
    # at a Battlefield its controller Holds and scores from (383.4.d.2.a) - the Scoring Step's
    # unit_here scope. Distinct from the Battlefield's own "When you hold here".
    ("when_i_hold", r"when i hold, (?P<inner>.+)", ["Core 469.2", "Core 383.4.d", "Core 383.4.d.2.a"], ["hold_triggers"],
     ["When I hold, draw 1."], ["when you hold here, draw 1", "when i conquer, draw 1", "when i move, draw 1"]),
    ("when_i_conquer", r"when i conquer, (?P<inner>.+)", ["Core 469.1", "Core 383.1"], ["conquer_triggers"],
     ["When I conquer, draw 1."], ["when you conquer, draw 1", "when i hold, draw 1", "when i move, draw 1"]),
    # A Unit's own Attack Trigger (Core 383.4.e): it goes on the Chain the first time this
    # combat the Unit becomes an Attacker (383.4.e.2, .2.a), attacker before
    # defender (464.2.e.1). Distinct from the player-level "When you attack" (not modelled).
    ("when_i_attack", r"when i attack, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.e.1", "Core 383.4.e.2", "Core 383.4.e.2.a", "Core 464.2.e", "Core 464.2.e.1"],
     ["attack_triggers"],
     ["When I attack, draw 1."], ["when you attack, draw 1", "when i defend, draw 1", "when i conquer, draw 1"]),
    # One Unit ability with two trigger conditions (Core 383.4.e, 383.4.f): it goes on the
    # Chain the first time this Combat the Unit becomes an Attacker, or a Defender - never
    # both, since a Unit holds one designation per Combat.
    ("when_i_attack_or_defend", r"when i attack or defend, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.e.2.a", "Core 383.4.f", "Core 383.4.f.2.a", "Core 464.2.e", "Core 464.2.e.1"],
     ["attack_triggers"],
     ["When I attack or defend, draw 1."],
     ["when i attack, draw 1", "when i defend, draw 1", "when you attack or defend, draw 1"]),
    # 2026-09-27: one Unit ability with two trigger conditions of different kinds - a Play Effect
    # (Core 383.4.a, 419.4.a: on play completion) and a Conquer Effect (383.4.c, 383.4.c.2.a: the
    # Unit present at the Battlefield Conquered). The same descriptor in play_triggers and
    # conquer_triggers; the two events are different, so each schedules it at most once.
    ("when_im_played_and_when_i_conquer", r"when i'm played and when i conquer, (?P<inner>.+)",
     ["Core 383.4.a", "Core 419.4.a", "Core 383.4.c", "Core 383.4.c.2.a", "Core 469.1"],
     ["play_triggers", "conquer_triggers"],
     ["When I'm played and when I conquer, draw 1."],
     ["when i'm played, draw 1", "when i conquer, draw 1", "when i'm played or when i hold, draw 1"]),
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
    ("at_the_end_of_your_turn", r"at the end of your turn, (?P<inner>.+)", ["Core 317.1", "Core 383.1"],
     ["end_of_turn_triggers"], ["At the end of your turn, draw 1."],
     ["at the end of each turn, draw 1", "at the beginning of your turn, draw 1"]),
    # 2026-09-24: triggers that watch what happens to ANYTHING, not to the card itself - an
    # event_triggers descriptor with a typed watch (watchers.py), woken by the play
    # transaction ("played") and by every resolution's events. Each row states its watch.
    ("when_you_play_a_spell", r"when you play a spell, (?P<inner>.+)", ["Core 383.1", "Core 419.4.a"],
     ["event_triggers"], ["When you play a spell, draw 1."],
     ["when you play a spell that costs 5 or more, draw 1", "when you play me, draw 1", "when you play a gear, draw 1"]),
    ("when_you_play_a_spell_that_costs_n_or_more",
     r"when you play a spell that costs \[e(?P<cost>\d+)\] or more, (?P<inner>.+)", ["Core 383.1", "Core 419.4.a", "Core 206"],
     ["event_triggers"], ["When you play a spell that costs :rb_energy_5: or more, draw 1."],
     ["when you play a spell, draw 1", "when you play a spell that costs :rb_energy_5: or less, draw 1",
      "when you play a unit that costs :rb_energy_5: or more, draw 1"]),
    ("when_you_play_a_gear", r"when you play a gear, (?P<inner>.+)", ["Core 383.1", "Core 419.4.a"],
     ["event_triggers"], ["When you play a gear, draw 1."], ["when you play a spell, draw 1", "when you play me, draw 1"]),
    ("when_you_play_another_unit", r"when you play another unit, (?P<inner>.+)", ["Core 383.1", "Core 419.4.a"],
     ["event_triggers"], ["When you play another unit, draw 1."], ["when you play a unit, draw 1", "when you play me, draw 1"]),
    # 2026-09-27: "a [Mighty] unit" - a Unit whose current Might is 5 or greater (Core 708, 710)
    ("when_you_play_a_mighty_unit", r"when you play a \[mighty\] unit, (?P<inner>.+)",
     ["Core 383.1", "Core 419.4.a", "Core 708", "Core 710"], ["event_triggers"],
     ["When you play a [Mighty] unit, draw 1."],
     ["when you play a unit, draw 1", "when you play another unit, draw 1", "when an opponent plays a [mighty] unit, draw 1",
      "when a unit becomes [mighty], draw 1", "when you play a [mighty] gear, draw 1"]),
    ("when_you_play_a_card_on_an_opponents_turn", r"when you play a card on an opponent's turn, (?P<inner>.+)",
     ["Core 383.1", "Core 419.4.a"], ["event_triggers"], ["When you play a card on an opponent's turn, draw 1."],
     ["when you play a card, draw 1", "when an opponent plays a card, draw 1"]),
    ("when_you_play_a_card_from_hidden", r"when you play a card from \[hidden\], (?P<inner>.+)",
     ["Core 383.1", "Core 419.4.a", "Core 811.1"], ["event_triggers"], ["When you play a card from [Hidden], draw 1."],
     ["when you play a card, draw 1", "when you hide a card, draw 1"]),
    ("when_you_stun_one_or_more_enemy_units", r"when you stun one or more enemy units, (?P<inner>.+)",
     ["Core 383.1", "Core 423"], ["event_triggers"], ["When you stun one or more enemy units, draw 1."],
     ["when you stun an enemy unit, draw 1", "when a unit is stunned, draw 1"]),
    ("when_you_stun_an_enemy_unit", r"when you stun an enemy unit, (?P<inner>.+)",
     ["Core 383.1", "Core 423", "Core 423.1.a.1"], ["event_triggers"], ["When you stun an enemy unit, draw 1."],
     ["when you stun one or more enemy units, draw 1", "when you stun a unit, draw 1", "when a unit is stunned, draw 1"]),
    ("when_you_discard_one_or_more_cards", r"when you discard one or more cards, (?P<inner>.+)",
     ["Core 383.1", "Core 422", "Core 422.1.b"], ["event_triggers"], ["When you discard one or more cards, draw 1."],
     ["when you discard a card, draw 1", "when an opponent discards one or more cards, draw 1", "when you discard me, draw 1"]),
    ("when_you_recycle_one_or_more_cards_to_your_main_deck",
     r"when you recycle one or more cards to your main deck, (?P<inner>.+)", ["Core 383.1", "Core 420"],
     ["event_triggers"], ["When you recycle one or more cards to your Main Deck, draw 1."],
     ["when you recycle a card, draw 1", "when a card is recycled, draw 1"]),
    ("when_a_buffed_friendly_unit_dies", r"when a buffed friendly unit dies, (?P<inner>.+)",
     ["Core 383.1", "Core 417", "Core 426"], ["event_triggers"], ["When a buffed friendly unit dies, draw 1."],
     ["when a friendly unit dies, draw 1", "when a buffed enemy unit dies, draw 1"]),
    # 2026-09-27: "you kill" - a kill you are responsible for (Core 411.4, 428.5); "stunned", as the unit was
    ("when_you_kill_a_stunned_enemy_unit", r"when you kill a stunned enemy unit, (?P<inner>.+)",
     ["Core 383.1", "Core 411.4", "Core 428.5.b", "Core 428.5.c.1", "Core 428.5.c.2", "Core 423"], ["event_triggers"],
     ["When you kill a stunned enemy unit, draw 1."],
     ["when you kill an enemy unit, draw 1", "when a stunned enemy unit dies, draw 1", "when you kill a stunned unit, draw 1",
      "when you stun an enemy unit, draw 1", "when an opponent kills a stunned enemy unit, draw 1"]),
    ("the_first_time_a_friendly_unit_dies_each_turn", r"the first time a friendly unit dies each turn, (?P<inner>.+)",
     ["Core 383.1", "Core 417", "Core 383.3.e"], ["event_triggers"],
     ["The first time a friendly unit dies each turn, draw 1."],
     ["when a friendly unit dies, draw 1", "the first time an enemy unit dies each turn, draw 1"]),
    # 2026-09-27: "the Nth time I move" - a watch over the card's own `moved` events (a Standard
    # Move or an effect's, Core 420.2, 446.1), counted per turn and per object; the count reaching
    # N triggers it once (Core 383.1, 383.1.b)
    ("the_first_time_i_move_each_turn", r"the first time i move each turn, (?P<inner>.+)",
     ["Core 383.1", "Core 383.1.b", "Core 420.2", "Core 446.1"], ["event_triggers"],
     ["The first time I move each turn, draw 1."],
     ["the first time a friendly unit dies each turn, draw 1", "when i move, draw 1",
      "the third time i move in a turn, draw 1", "the first time i move each combat, draw 1"]),
    ("the_third_time_i_move_in_a_turn", r"the third time i move in a turn, (?P<inner>.+)",
     ["Core 383.1", "Core 383.1.b", "Core 420.2", "Core 446.1"], ["event_triggers"],
     ["The third time I move in a turn, draw 1."],
     ["the first time i move each turn, draw 1", "the second time i move in a turn, draw 1",
      "when i move, draw 1", "the third time a unit moves in a turn, draw 1"]),
    # 2026-09-27: a player-level Conquer Effect (Core 383.4.c.2.b) - any source the Conquering
    # player controls where its abilities work, a Legend in its Legend Zone included
    ("when_you_conquer", r"when you conquer, (?P<inner>.+)", ["Core 469.1", "Core 383.4.c", "Core 383.4.c.2.b"],
     ["conquer_triggers"], ["When you conquer, draw 1."],
     ["when you conquer here, draw 1", "when i conquer, draw 1", "when you hold, draw 1",
      "when an opponent conquers, draw 1"]),
    # 2026-09-27 (package 6): the Nth card a player plays in a turn - every play of the turn counts,
    # one per play Finalized (Core 419.4.b), the ones before the watching card was on the board too
    ("when_you_play_your_second_card_in_a_turn", r"when you play your second card in a turn, (?P<inner>.+)",
     ["Core 383.1", "Core 419.4.a", "Core 419.4.b"], ["event_triggers"],
     ["When you play your second card in a turn, draw 1."],
     ["when you play a card, draw 1", "when you play your third card in a turn, draw 1",
      "when an opponent plays their second card in a turn, draw 1", "when you play a spell, draw 1"]),
    # 2026-09-27 (package 6): a death watched with the dying unit's tags as it was (Core 133.8, 417;
    # a Recruit token has the Recruit tag by Core 187.1); the watching card must still be on the board
    # after the death (Core 383.2.c.2: dying with it, it does not trigger)
    ("when_another_non_recruit_unit_you_control_dies",
     r"when another non-recruit unit you control dies, (?P<inner>.+)",
     ["Core 383.1", "Core 383.2.c.2", "Core 428", "Core 133.8", "Core 187.1"], ["event_triggers"],
     ["When another non-Recruit unit you control dies, draw 1."],
     ["when another unit you control dies, draw 1", "when a non-recruit unit you control dies, draw 1",
      "when another non-recruit unit an opponent controls dies, draw 1", "when a buffed friendly unit dies, draw 1"]),
    # 2026-09-27 (package 6): "When you discard me" works from the trash, the zone discarding puts the
    # card in (Core 422.1, 422.1.b): it is evaluated as the card enters it (383.2.c.1) - from the hand
    # it could not be, since the card leaves the hand as the condition is met (383.2.c.2)
    ("when_you_discard_me", r"when you discard me, (?P<inner>.+)",
     ["Core 383.1", "Core 383.2.c.1", "Core 385.2", "Core 422.1", "Core 422.1.b"], ["event_triggers"],
     ["When you discard me, draw 1."],
     ["when you discard one or more cards, draw 1", "when i am discarded, draw 1",
      "when an opponent discards me, draw 1", "when you discard a card, draw 1"]),
    # 2026-09-27 (package 6): a kill attributed to a spell (Core 428.5.b, 428.5.c, 428.5.d) its controller
    # is responsible for (428.5.c.1)
    ("when_you_kill_a_unit_with_a_spell", r"when you kill a unit with a spell, (?P<inner>.+)",
     ["Core 383.1", "Core 428.5", "Core 428.5.b", "Core 428.5.c", "Core 428.5.c.1", "Core 428.5.d"], ["event_triggers"],
     ["When you kill a unit with a spell, draw 1."],
     ["when you kill a unit, draw 1", "when a unit dies, draw 1", "when an opponent kills a unit with a spell, draw 1",
      "when you kill a gear with a spell, draw 1"]),
    # 2026-09-28: watches over a Unit gaining a combat designation (combat emits `attacked` /
    # `defended`, Core 464.2.c.3), their other requirements read then (383.4.e.2.b, 383.4.f.2.b).
    # The inner clause's "it" is the Unit the event is about (REFERENT_WRAPPERS, Core 359.3.f.3)
    ("when_an_enemy_unit_attacks_a_battlefield_you_control",
     r"when an enemy unit attacks a battlefield you control, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.e.2.b", "Core 464.2.c.3", "Core 190.4.b", "Core 359.3.f.3"],
     ["event_triggers", "combat_designations", "trigger_referent"],
     ["When an enemy unit attacks a battlefield you control, draw 1.",
      "When an enemy unit attacks a battlefield you control, give it -2 :rb_might: this turn, to a minimum of 1 :rb_might:."],
     ["when an enemy unit attacks, draw 1", "when a friendly unit attacks a battlefield you control, draw 1",
      "when an enemy unit defends a battlefield you control, draw 1", "when you attack a battlefield, draw 1"]),
    ("when_a_friendly_unit_attacks_or_defends_alone", r"when a friendly unit attacks or defends alone, (?P<inner>.+)",
     ["Core 383.4.e", "Core 383.4.f", "Core 383.4.e.2.b", "Core 383.4.f.2.b", "Core 740.2.a", "Core 359.3.f.3"],
     ["event_triggers", "combat_designations", "trigger_referent"],
     ["When a friendly unit attacks or defends alone, draw 1.",
      "When a friendly unit attacks or defends alone, give it +2 :rb_might: this turn."],
     ["when a friendly unit attacks or defends, draw 1", "when a friendly unit attacks alone, draw 1",
      "when an enemy unit attacks or defends alone, draw 1", "when i attack or defend alone, draw 1"]),
    # a Battlefield's own: a Unit's Move whose location before was this Battlefield (Core 446.1); the
    # Battlefield's controller controls it, or, uncontrolled, the Turn Player (190.6.a, 190.6.b)
    ("when_a_unit_moves_from_here", r"when a unit moves from here, (?P<inner>.+)",
     ["Core 383.1", "Core 446.1", "Core 190.6.a", "Core 190.6.b", "Core 359.3.f.3"],
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
        "ruleset": {"core": "2026-07-16", "faq_as_of": "2026-08-14"},
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
