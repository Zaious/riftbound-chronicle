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
        ],
        "negative": [
            "Give a unit [Assault 3] this turn.",
            "Give the strongest unit [Tank] this turn.",
            "Give a unit [Tank] permanently.",
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
        "production_id": "move_selector",
        "form": "Move <selector>.",
        "template": r"move {selector}",
        "slots": {"selector": ["a_unit", "a_friendly_unit", "an_enemy_unit", "me", "it", "that_unit",
                               "another_unit", "another_friendly_unit"]},
        "normalization": N,
        "rule_locators": ["Core 428", "Core 355.4.a", "Core 355.9"],
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
     r"if an opponent's score is within (?P<within>\d+) points? of the victory score, this costs \[e(?P<amount>\d+)\] less",
     ["Core 356.4", "Core 194.1"], "self_cost_reduction", ["self_card_conditional_fixed_energy_reduction.v1"],
     "The card's own text, a fixed Energy amount, and the one condition leaf this wave registered. A reduction of Power, a variable amount, or a value read off the board is a different clause and stays unparsed.",
     ["If an opponent's score is within 3 points of the Victory Score, this costs :rb_energy_2: less."],
     ["if an opponent's score is within 3 points of the victory score, this costs :rb_rune_rainbow: less",
      "this spell's energy cost is reduced by the highest might among units you control",
      "i cost :rb_energy_2: less"]),
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
    ("when_i_conquer", r"when i conquer, (?P<inner>.+)", ["Core 469.1", "Core 383.1"], ["conquer_triggers"],
     ["When I conquer, draw 1."], ["when you conquer, draw 1", "when i hold, draw 1", "when i move, draw 1"]),
    ("at_the_end_of_your_turn", r"at the end of your turn, (?P<inner>.+)", ["Core 317.1", "Core 383.1"],
     ["end_of_turn_triggers"], ["At the end of your turn, draw 1."],
     ["at the end of each turn, draw 1", "at the beginning of your turn, draw 1"]),
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
    "end_of_turn_triggers": "ending_step",
    "might_aura": "continuous_effects",
    "domain_power": "typed_cost_payment",
    "card_self_optional_cost": "self_costs",
    "self_card_conditional_fixed_energy_reduction.v1": "evaluated_cost_modifications",
    "timing_permission_v1": "timing_permission_classification",
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
