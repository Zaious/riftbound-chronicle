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

ROOT = Path(r"P:\MyOpenSource\riftbound-chronicle-claude-16")
OUT = ROOT / "skill" / "data" / "clause_grammar" / "clause_grammar.json"
CATALOGUE = ROOT / "skill" / "data" / "keyword_catalog" / "keyword_catalog.json"
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
from effect_ir import GRANTABLE_KEYWORDS  # noqa: E402

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
        for keyword in sorted(GRANTABLE_KEYWORDS & catalogue)
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
                               "it", "that_unit"],
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
                               "it", "that_unit"],
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
            "Give it [Shield 1] this turn.", "Give it [Tank] this turn.",
            "Give it [Ganking] this turn.", "Give it [Backline] this turn.",
            "Give that unit [Shield 2] this turn.", "Give that unit [Tank] this turn.",
            "Give that unit [Ganking] this turn.", "Give that unit [Backline] this turn.",
            "Give a unit [Shield 1] this combat.", "Give me [Tank] this combat.",
            "Give friendly units [Ganking] this combat.", "Give an enemy unit [Backline] this combat.",
        ],
        "negative": [
            "Give a unit [Assault 3] this turn.",
            "Give the strongest unit [Tank] this turn.",
            "Give a unit [Tank] permanently.",
        ],
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
        "golden": [f"[{name.title()}][>] Draw 1." for name in sorted(keyword_alternatives())],
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
    ("deal_n_to_a_unit_at_a_battlefield", r"deal (?P<amount>\d+) to a unit at (?:a )?battlefield",
     ["Core 437", "Core 355.9"], "instruction", ["deal_damage", "targeting"],
     "One chosen Unit at a Battlefield. A Might restriction on the target is a different production.",
     ["Deal 2 to a unit at a battlefield.", "Deal 3 to a unit at battlefield."],
     ["deal 2 to a unit at a battlefield with 3 [m] or less", "deal 2 to all units at a battlefield"]),
    ("deal_n_to_all_enemy_units_at_a_battlefield", r"deal (?P<amount>\d+) to all enemy units at a battlefield",
     ["Core 437", "Core 355.10.b", "Core 715.2"], "instruction", ["deal_damage", "criteria_expansion"],
     "One chosen Battlefield, then every enemy Unit there.",
     ["Deal 3 to all enemy units at a battlefield."],
     ["deal 3 to all units at a battlefield", "deal 3 to all enemy units in combat"]),
    ("deal_n_to_all_enemy_units_in_combat", r"deal (?P<amount>\d+) to all enemy units in combat",
     ["Core 437", "Core 715.2", "Core 460"], "instruction", ["deal_damage", "criteria_expansion", "combat_state"],
     "The Combat in progress. Outside one the instruction finds nothing.",
     ["Deal 2 to all enemy units in combat."],
     ["deal 2 to all enemy units at a battlefield", "deal 2 to all units in combat"]),
    ("deal_n_to_all_units_at_battlefields", r"deal (?P<amount>\d+) to all units at battlefields",
     ["Core 437", "Core 355.10.b"], "instruction", ["deal_damage", "criteria_expansion"],
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
    ("units_you_play_this_turn_enter_ready", r"units you play this turn enter ready",
     ["Core 317.2", "Core 419.4"], "instruction", ["grant_turn_effect"],
     "Entry state for this turn's own plays.",
     ["Units you play this turn enter ready."],
     ["units you play this turn enter exhausted", "i enter ready"]),
    ("self_cost_reduction_score",
     r"if an opponent's score is within (?P<within>\d+) points? of the victory score, this costs :rb_energy_(?P<amount>\d+): less",
     ["Core 356.4", "Core 194.1"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text, a fixed Energy amount, and the one condition leaf this wave registered. A reduction of Power, a variable amount, or a value read off the board is a different clause and stays unparsed.",
     ["If an opponent's score is within 3 points of the Victory Score, this costs :rb_energy_2: less."],
     ["if an opponent's score is within 3 points of the victory score, this costs :rb_rune_rainbow: less",
      "this spell's energy cost is reduced by the highest might among units you control",
      "i cost :rb_energy_2: less"]),
    ("no_rules_text", r"\(no rules text\)", ["Core 185"], "empty", [],
     "A card with nothing to compile. It is a parsed clause, not an unparsed one.",
     ["(no rules text)"], ["no rules text", "(vanilla)"]),
    ("play_timing_keyword", r"\[(?P<timing>action|reaction)\]", ["Core 806", "Core 807", "Core 309.1.a"],
     "play_timing", ["timing_permission_v1"],
     "Only the two printed timing keywords.",
     ["[Action]", "[Reaction]"], ["[Action] this turn", "action"]),
]

WRAPPERS = [
    ("when_you_play_me", r"when you play me, (?P<inner>.+)", ["Core 383.1", "Core 419.4.a"], ["play_triggers"],
     ["When you play me, channel 1 rune exhausted.", "When you play me, draw 1."],
     ["when you play a unit, draw 1", "when i move, draw 1"]),
    ("when_i_move", r"when i move, (?P<inner>.+)", ["Core 383.1", "Core 428"], ["move_triggers"],
     ["When I move, draw 1."], ["when a unit moves, draw 1", "when you play me, draw 1"]),
    ("at_the_end_of_your_turn", r"at the end of your turn, (?P<inner>.+)", ["Core 317.1", "Core 383.1"],
     ["end_of_turn_triggers"], ["At the end of your turn, draw 1."],
     ["at the end of each turn, draw 1", "at the beginning of your turn, draw 1"]),
]


def main() -> int:
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
