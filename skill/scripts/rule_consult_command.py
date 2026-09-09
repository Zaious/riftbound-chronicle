#!/usr/bin/env python3
"""One consultation command over the five engine entries, at all three tiers.

The pipeline is fixed and every stage is somebody else's module:

    state-assumption.v1  build the minimum state the question needs (S-01)
      -> engine entry     timing / effect / combat_step / control_step / legal_action
      -> evidence-pack.v1 the check, its inputs, and the engine identity, re-runnable
      -> source retrieval what the rules corpus actually returns for this question
      -> claim surface    templates rendered from closed slots, never authored prose
      -> fact-ledger.v1   one claim, one entry, verified against this context (S-02)

The answer surface is the part worth reading twice. A producer here does not
write sentences. It picks a template from a closed table and fills that
template's slots, and every slot type is closed — to the players in the state
that was built, to the object kinds the timing kernel knows, to a step in the
combat table, to a slot the assumption artifact carries, or, for a locator or a
card, to a shape the retriever recognises rather than to prose. There is no
free-text slot type, so there is no way to put a sentence into a claim, so a
claim cannot carry two of them.

That is the guarantee: one claim is one assertion because the producer never
composed it. The lexical marker layer in fact_ledger is a backstop against
hand-written ledgers arriving from elsewhere; it is not what holds atomicity
here, and it was never strong enough to.

Three tiers, one path
---------------------
A claim is one of two classes, and the class is a property of its template:

  position_conclusion   "p1 may play a spell in this position." Requires an
                        engine check of the right kind that reached a verdict.
                        There is no other way to make one.
  source_statement      "Core 312 is official text retrieved for this question."
                        Requires a retrieved source. It may not take a player
                        slot and may not use the legality vocabulary, so it
                        cannot be bent into a statement about what anyone may
                        do — checked against the template table by the gate.

So tier A is a run that carries a position conclusion, tier B a run that
carries only source statements, and tier C an abstention. The engine declining
does not end the run any more: it removes every position conclusion from reach,
because their templates require a verdict, and what is left is the B route —
here is the text, and here is the statement that the engine has not compiled
this mechanism, so nothing is concluded about the position. That statement is
derived by this module when the engine declines, not offered by a producer, so
it cannot be omitted from a run that needs it or attached to one that does not.

What the B route is not is a second way to answer the mechanical question. A
locator cannot become "you may play this" because no template joins the two,
and the gate re-runs a declined question with a perfectly good locator claim to
show that it still yields no position conclusion.

Sources come from retrieval
---------------------------
A producer naming a locator is not a source. A retriever answers with the
document id, the document version, the locator and the text hash, and
fact_ledger binds all four; a document revised under the same locator fails
verification afterwards. Not found, conflicting, or superseded is not a source
either, and each is named rather than folded into the others. Those land at C.

Two checks read a run, and they are not the same check
------------------------------------------------------
  validate_run(run)            structural. Shape, every claim's text re-rendered
                               from its template and slots, atomicity, the
                               derived coverage statement, the local hash. It
                               reads no context, so it cannot know whether a
                               ledger record marked "verified" ever was.
  verify_run(run, ...context)  bound. Re-runs the whole consultation from the
                               request the run carries, against the engine,
                               retriever and snapshots supplied now, and
                               compares every derived field.

Only the second is verification. A run that passed the first has been checked
for self-consistency and nothing else.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import fact_ledger
import rules_core
import state_builder
import verify_evidence_pack as evidence
from battlefield_control import STEPS as CONTROL_STEPS
from combat import STEPS as COMBAT_STEPS
from engine_check import canonical_hash
from fact_ledger import build_ledger, verify_ledger
from legal_action import validate_observation


SCHEMA_VERSION = "consultation-run.v1"
CORE_RULESET = rules_core.CORE_RULESET
FAQ_AS_OF = rules_core.FAQ_AS_OF

ENTRIES = {
    "timing": {"check_kind": "timing", "needs_effect_state": False, "inputs": ("action",)},
    "effect": {"check_kind": "effect", "needs_effect_state": True, "inputs": ("program",)},
    "combat_step": {"check_kind": "combat_step", "needs_effect_state": True, "inputs": ("step",)},
    "control_step": {"check_kind": "control_step", "needs_effect_state": True, "inputs": ("step",)},
    "legal_action": {"check_kind": "legal_action", "needs_effect_state": True, "inputs": ("acting_player",)},
}

STATUSES = ("answered", "abstained", "not_attempted")

NOT_ATTEMPTED_REASONS = frozenset({
    "entry_not_covered",
    "state_not_built",
    "entry_inputs_missing",
    "claim_binding_invalid",
    "no_claims_offered",
    "evidence_not_reproducible",
})

DECIDING_OUTCOMES = fact_ledger.DECIDING_OUTCOMES

# The sentence a declined engine ruling earns. Derived here, never offered: a
# run that needs it cannot omit it, and a run that does not cannot carry it.
COVERAGE_STATEMENT = ("The engine has not compiled this mechanism, so this answer "
                      "draws no conclusion about the position.")

# Carried by every run that reaches tier B, whether the engine declined or the
# producer simply made no position claim. A reader of a B-tier answer must be
# told that it concluded nothing about their position, and telling them is the
# artifact's job rather than the interface's.
POSITION_STATEMENT = ("This answer reports what the rules text says and draws no "
                      "conclusion about this position.")

CLAIM_CLASSES = ("position_conclusion", "conditional_rule", "source_statement")

# A conditional rule says what the text says, in the text's own terms. It is
# allowed the legality vocabulary — a rule about what a player may do cannot be
# stated without it — and is kept from becoming a position conclusion by a
# different line: it may not name anyone in this position. No player slot, and
# the subject is whoever the rule describes, not p1.
#
# "Core 312 is official text retrieved for this question" is a source
# statement. It is true, it is bound, and it answers nothing. A tier-B answer
# that consists only of those has cited its way out of saying anything, which
# is why the two classes are separate and why a corpus can require one and not
# the other.

# A source statement talks about what the corpus holds. If it can use this
# vocabulary it is talking about what someone may do instead, which is the A
# tier wearing the B tier's clothes. Checked against the template table, not
# against a producer's output — producers do not write text here.
LEGALITY_VOCABULARY = (
    "may", "may not", "cannot", "can not", "can't", "must", "must not",
    "is legal", "is not legal", "is illegal", "is allowed", "is not allowed",
    "you can", "you may", "has priority", "holds priority", "resolves",
    "is destroyed", "wins", "loses", "completes", "takes effect",
)

# "Core 312", "Core 359.3.e.6", "FAQ 12.1". Not a sentence: a locator is one or
# two words and then a dotted number, so prose cannot pass for one. A retriever
# may recognise more than this; it may not recognise less.
LOCATOR_SHAPE = re.compile(r"^[A-Z][A-Za-z]{1,15}(?:\s[A-Za-z]{1,15})?\s\d+(?:\.[0-9A-Za-z]+)*$")
# A card snapshot id: one token, no spaces.
SNAPSHOT_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class ConsultationError(ValueError):
    pass


class TableRetriever:
    """A source retriever over a fixed table, for tests and for callers without an index.

    The service passes one backed by the rules index. What every retriever owes
    this module is the same: say whether a string is a locator at all, say what
    a question surfaced, and answer about one locator with a record carrying its
    document id, document version, locator and text hash — or with the reason it
    is not a source right now.
    """

    def __init__(self, table: dict[str, Any], surfaced: dict[str, list[str]] | None = None) -> None:
        self.table = copy.deepcopy(table)
        self.surfaced = copy.deepcopy(surfaced or {})

    def is_locator(self, value: Any) -> bool:
        return isinstance(value, str) and bool(LOCATOR_SHAPE.match(value))

    def catalogue(self) -> list[str]:
        return sorted(self.table)

    def retrieve_for(self, question: str) -> list[dict[str, Any]]:
        locators = self.surfaced.get(question, self.catalogue())
        return [copy.deepcopy(self.table[loc]["record"]) for loc in locators
                if self.table.get(loc, {}).get("status") == "retrieved"]

    def retrieve(self, locator: str) -> dict[str, Any]:
        return copy.deepcopy(self.table.get(locator, {"status": "not_found", "record": None}))


def _is_retriever(value: Any) -> bool:
    return all(hasattr(value, name) for name in ("is_locator", "retrieve", "retrieve_for"))


# --- the claim surface ------------------------------------------------------

def _players(ctx: dict[str, Any]) -> set[str]:
    return set((ctx.get("timing_state") or {}).get("players", []))


SLOT_TYPES: dict[str, dict[str, Any]] = {
    "player": {
        "admits": lambda ctx, v: v in _players(ctx),
        "samples": lambda ctx: sorted(_players(ctx)),
    },
    "object_kind": {
        "admits": lambda ctx, v: v in rules_core.OBJECT_KINDS,
        "samples": lambda ctx: sorted(rules_core.OBJECT_KINDS),
    },
    "phase": {
        "admits": lambda ctx, v: v in rules_core.PHASES,
        "samples": lambda ctx: sorted(rules_core.PHASES),
    },
    "combat_step": {
        "admits": lambda ctx, v: v in COMBAT_STEPS,
        "samples": lambda ctx: sorted(COMBAT_STEPS),
    },
    "control_step": {
        "admits": lambda ctx, v: v in CONTROL_STEPS,
        "samples": lambda ctx: sorted(CONTROL_STEPS),
    },
    "assumption_slot": {
        "admits": lambda ctx, v: v in (ctx.get("assumption_slots") or set()),
        "samples": lambda ctx: sorted(ctx.get("assumption_slots") or ()),
    },
    # Shape-closed rather than list-closed, on purpose. A locator that does not
    # exist is still a locator, and the contract puts it at tier C — an
    # abstention with a named reason — rather than treating it as a malformed
    # claim. Prose is not locator-shaped, so nothing is opened up by this.
    "locator": {
        "admits": lambda ctx, v: bool(ctx.get("retriever")) and ctx["retriever"].is_locator(v),
        "samples": lambda ctx: (ctx["retriever"].catalogue()[:1] if ctx.get("retriever") else []),
    },
    "card_snapshot": {
        "admits": lambda ctx, v: isinstance(v, str) and bool(SNAPSHOT_SHAPE.match(v)),
        "samples": lambda ctx: sorted(ctx.get("card_snapshots") or ()),
    },
}

# --- T-01: the rule families' lexicons ---------------------------------------
# A conditional rule is a fixed sentence over closed lexicons. Each lexicon
# maps the id a producer may choose to the phrase the sentence renders it as;
# a value outside it is refused as free text like any other slot. Adding a
# rule the surface cannot yet state means adding a lexicon entry here, in
# review, never a sentence at run time.
RULE_ACTORS = {
    "any_player": "a player",
    "no_player": "no player",
    "the_turn_player": "the Turn Player",
    "a_player_other_than_the_turn_player": "a player other than the Turn Player",
    "a_player_with_focus_but_not_priority": "a player who holds Focus but not Priority",
    "only_the_turn_player": "only the Turn Player",
}
RULE_MODALITIES = {"may": "may", "may_not": "may not", "must": "must",
                   # a capability the text grants to one party, not a permission checked per card
                   "has_the_ability_to": "has the ability to"}
RULE_ACTIONS = {
    "take_a_discretionary_action": "take a Discretionary Action",
    "take_a_limited_action": "take a Limited Action",
    "play_a_spell_or_activate_an_ability": "play a spell or activate an ability",
    "play_spells_or_activate_abilities": "play spells or activate abilities",
}
RULE_CONDITIONS = {
    "unconditionally": "",
    "while_no_player_holds_priority": " while no player holds Priority",
    "when_instructed_regardless_of_priority": " when instructed, regardless of Priority",
    "if_a_forbidden_action_or_game_state_would_result":
        " if a forbidden action or game state would result",
    "at_will": " at will",
    "when_instructed_or_at_its_occasion_in_the_turn":
        " when instructed or at its occasion in the turn",
    "in_a_neutral_open_state": " in a Neutral Open State",
}
RULE_OCCASIONS = {
    "when_showdown_begins": "as a Showdown begins, ",
    "when_priority_is_passed": "when a player passes Priority, ",
    "in_a_neutral_state": "while the turn is in a Neutral State, ",
    "when_the_chain_resolves": "when the chain resolves, ",
    "when_combat_opens": "when Combat opens, ",
}
RULE_ROLES = {
    "focus": "Focus is held by",
    "attacker": "the Attacker is",
    "defender": "the Defender is",
    "resolving_chain_item": "the Chain Item that resolves is",
}
RULE_HOLDERS = {
    "applied_contested": "the player who applied Contested status to the Battlefield",
    "did_not_apply_contested": "the player who did not apply Contested status to the Battlefield",
    "the_passing_player": "the player who passed",
    "no_player": "no player",
    "the_attacker": "the Attacker",
    "newest_finalized_chain_item": "the newest Finalized Chain Item",
}
RULE_STEPS = {
    "assigning_combat_damage": "assigning Combat Damage",
    "dealing_combat_damage": "dealing Combat Damage",
    "assigning_all_combat_damage": "assigning all Combat Damage",
    "dealing_combat_damage_simultaneously": "dealing all of it simultaneously",
    "assigning_lethal_damage_in_full_to_one_unit": "assigning lethal damage in full to one unit",
    "assigning_damage_to_another_unit": "assigning damage to a different unit",
    "exhausting_the_units_that_can_still_be_assigned_damage":
        "running out of units that can still be assigned damage",
    "assigning_a_unit_more_than_its_minimum_lethal_damage":
        "assigning a unit more than the minimum that is lethal to it",
    "assigning_lethal_damage_to_a_tank_unit": "assigning lethal damage to a unit with Tank",
    "assigning_damage_to_a_non_tank_unit_of_the_same_controller":
        "assigning damage to a unit without Tank under the same controller",
    "scoring_every_battlefield_this_turn": "Scoring every Battlefield this turn",
    "gaining_the_final_point_by_conquer": "gaining the Final Point through a Conquer",
}
RULE_ORDER_RELATIONS = {
    "is_required_before": "must be complete before",
    "comes_before": "comes before",
    "is_distinct_from": "is not the same action as",
}
RULE_QUANTITIES = {
    "scores_per_battlefield_per_turn_per_player":
        "the number of times a player may Score one Battlefield in a turn",
    "hold_ability_triggers_per_battlefield_per_turn_per_player":
        "the number of times a Battlefield's Hold abilities trigger for a player in a turn",
    "victory_score_by_default": "the Victory Score by default",
    "a_players_points": "a player's point total",
    "discretionary_actions_a_player_may_take_in_a_turn":
        "the number of Discretionary Actions a player may take in a turn",
    "discretionary_actions_a_player_may_take_in_the_main_phase":
        "the number of Discretionary Actions a player may take in the Main Phase",
    "shield_value_when_x_is_omitted": "the Shield Value when X is omitted",
    "shield_value_from_several_sources":
        "the Shield Value of a unit granted Shield from more than one source",
    "tank_instances_in_effect_on_a_unit": "the number of Tank instances that take effect on one unit",
    "players_whose_units_are_in_one_combat": "the number of players whose units are in one Combat",
}
# relation -> (phrase, whether a value follows)
RULE_QUANTITY_RELATIONS = {
    "is": ("is", True),
    "at_least": ("is at least", True),
    "at_most": ("is at most", True),
    "exactly": ("is exactly", True),
    "unbounded": ("is not limited", False),
    "is_the_sum_of_the_values": ("is the sum of the granted Shield Values", False),
}

# T-02. Event-consequence rules and the ways points are gained. Every event
# and consequence below is used by one rule today; they are lexicon entries
# rather than literal templates so that the same sentence frame, the same
# binding rule and the same registry cover them.
RULE_EVENTS = {
    "a_chain_item_is_finalized": "a Chain Item is finalized",
    "a_finalized_chain_item_is_a_unit_gear_or_add_ability":
        "the finalized Chain Item is a Unit, Gear, or an ability that Adds resources",
    "the_final_point_by_conquer_is_withheld":
        "a Conquer would give the Final Point and not every Battlefield has been Scored this turn",
    "a_point_is_gained_from_a_source_other_than_conquer":
        "a point is gained from a source other than a Conquer",
    "a_battlefield_is_scored_by_hold": "a Battlefield is Scored by being Held",
    "a_mode_of_play_or_card_effect_alters_the_victory_score":
        "a Mode of Play or a card effect alters the Victory Score",
    "a_cleanup_finds_more_than_one_player_at_or_above_the_victory_score_with_equal_points":
        "a cleanup finds more than one player at or above the Victory Score with the same points",
    "a_player_at_zero_points_would_lose_points": "a player at 0 points would lose one or more points",
    "a_cleanup_finds_one_player_at_or_above_the_victory_score_and_ahead":
        "a cleanup finds a player at or above the Victory Score with more points than any other player",
    "a_player_wins": "a player wins the game",
    "a_unit_keeps_its_defender_designation": "a Unit keeps its Defender designation",
    "a_choice_would_put_more_than_two_players_in_one_combat":
        "a choice would put more than two players in one Combat",
}
RULE_CONSEQUENCES = {
    "priority_is_not_passed": "Priority is not passed",
    "it_resolves_immediately": "it resolves immediately",
    "the_player_draws_a_card_instead": "that player draws a card instead",
    "the_final_point_restriction_does_not_apply": "the Final Point restriction does not apply to it",
    "its_hold_abilities_trigger": "its Hold abilities trigger",
    "that_victory_score_applies": "that Victory Score applies",
    "play_continues_until_a_cleanup_finds_one_player_ahead":
        "play continues until a cleanup finds one player with more points",
    "nothing_occurs": "nothing occurs",
    "that_player_wins": "that player wins the game",
    "the_game_ends": "the game ends",
    "its_shield_remains_in_effect": "its Shield remains in effect",
    "the_choice_is_invalid": "the choice is invalid and cannot be completed",
}
RULE_POINT_SOURCES = {
    "holding_a_battlefield": "Holding a Battlefield",
    "conquering_a_battlefield": "Conquering a Battlefield",
    "an_effect_that_instructs_it": "a spell or ability that instructs the player to gain points",
    "an_opponents_burn_out": "an opponent Burning Out and choosing that player",
}


def _lexicon(table: dict[str, str]) -> dict[str, Any]:
    return {
        "admits": lambda ctx, v: isinstance(v, str) and v in table,
        "samples": lambda ctx: sorted(table),
        "render": lambda v: table[v],
    }


SLOT_TYPES.update({
    "rule_actor": _lexicon(RULE_ACTORS),
    "rule_modality": _lexicon(RULE_MODALITIES),
    "rule_action": _lexicon(RULE_ACTIONS),
    "rule_condition": _lexicon(RULE_CONDITIONS),
    "rule_occasion": _lexicon(RULE_OCCASIONS),
    "rule_role": _lexicon(RULE_ROLES),
    "rule_holder": _lexicon(RULE_HOLDERS),
    "rule_step": _lexicon(RULE_STEPS),
    "rule_order_relation": _lexicon(RULE_ORDER_RELATIONS),
    "rule_quantity": _lexicon(RULE_QUANTITIES),
    "rule_quantity_relation": _lexicon({k: v[0] for k, v in RULE_QUANTITY_RELATIONS.items()}),
    "rule_event": _lexicon(RULE_EVENTS),
    "rule_consequence": _lexicon(RULE_CONSEQUENCES),
    "rule_point_source": _lexicon(RULE_POINT_SOURCES),
    # A number or nothing. Not a string: "eight" is prose.
    "rule_value": {
        "admits": lambda ctx, v: v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= 0),
        "samples": lambda ctx: [1],
        "render": lambda v: "" if v is None else f" {v}",
    },
})


def _quantity_coheres(slots: dict[str, Any]) -> str | None:
    needs_value = RULE_QUANTITY_RELATIONS[slots["relation"]][1]
    if needs_value and slots["value"] is None:
        return f"relation {slots['relation']!r} states a number and none was given"
    if not needs_value and slots["value"] is not None:
        return f"relation {slots['relation']!r} takes no number; {slots['value']!r} was given"
    return None

CLAIM_TEMPLATES: dict[str, dict[str, Any]] = {
    "timing_play_permitted": {
        "class": "position_conclusion",
        "text": "{actor} may play a {object_kind} in this position.",
        "slots": {"actor": "player", "object_kind": "object_kind"},
        "basis": {"kind": "engine", "check_kind": "timing", "outcomes": ("supported",)},
    },
    "timing_play_refused": {
        "class": "position_conclusion",
        "text": "{actor} cannot play a {object_kind} in this position.",
        "slots": {"actor": "player", "object_kind": "object_kind"},
        "basis": {"kind": "engine", "check_kind": "timing", "outcomes": ("illegal",)},
    },
    "effect_program_applies": {
        "class": "position_conclusion",
        "text": "The effect applies as written.",
        "slots": {},
        "basis": {"kind": "engine", "check_kind": "effect", "outcomes": ("supported",)},
    },
    "effect_program_refused": {
        "class": "position_conclusion",
        "text": "The effect does not apply here.",
        "slots": {},
        "basis": {"kind": "engine", "check_kind": "effect", "outcomes": ("illegal",)},
    },
    "combat_step_completes": {
        "class": "position_conclusion",
        "text": "The {step} step of Combat completes in this position.",
        "slots": {"step": "combat_step"},
        "basis": {"kind": "engine", "check_kind": "combat_step", "outcomes": ("supported",)},
    },
    "combat_step_refused": {
        "class": "position_conclusion",
        "text": "The {step} step of Combat cannot be taken in this position.",
        "slots": {"step": "combat_step"},
        "basis": {"kind": "engine", "check_kind": "combat_step", "outcomes": ("illegal",)},
    },
    "control_step_completes": {
        "class": "position_conclusion",
        "text": "The {step} control step completes in this position.",
        "slots": {"step": "control_step"},
        "basis": {"kind": "engine", "check_kind": "control_step", "outcomes": ("supported",)},
    },
    "control_step_refused": {
        "class": "position_conclusion",
        "text": "The {step} control step cannot be taken in this position.",
        "slots": {"step": "control_step"},
        "basis": {"kind": "engine", "check_kind": "control_step", "outcomes": ("illegal",)},
    },
    "legal_action_available": {
        "class": "position_conclusion",
        "text": "{actor} has at least one legal action in this position.",
        "slots": {"actor": "player"},
        "basis": {"kind": "engine", "check_kind": "legal_action", "outcomes": ("supported",)},
    },
    # --- the B route. Nothing below says what anyone may do. -----------------
    # --- conditional rules: what the text says, never about this position ---
    # T-01. Four families, each a fixed sentence over closed lexicons. The
    # locator slot comes first: it is the claim's source.
    "rule_action_permission": {
        "class": "conditional_rule",
        "text": "Under {locator}, {actor} {modality} {action}{condition}.",
        "slots": {"locator": "locator", "actor": "rule_actor", "modality": "rule_modality",
                  "action": "rule_action", "condition": "rule_condition"},
        "basis": {"kind": "official_text"},
    },
    "rule_role_holder": {
        "class": "conditional_rule",
        "text": "Under {locator}, {occasion}{role} {holder}.",
        "slots": {"locator": "locator", "occasion": "rule_occasion", "role": "rule_role",
                  "holder": "rule_holder"},
        "basis": {"kind": "official_text"},
    },
    "rule_step_order": {
        "class": "conditional_rule",
        "text": "Under {locator}, {first} {relation} {second}.",
        "slots": {"locator": "locator", "first": "rule_step", "relation": "rule_order_relation",
                  "second": "rule_step"},
        "basis": {"kind": "official_text"},
    },
    "rule_quantity": {
        "class": "conditional_rule",
        "text": "Under {locator}, {quantity} {relation}{value}.",
        "slots": {"locator": "locator", "quantity": "rule_quantity",
                  "relation": "rule_quantity_relation", "value": "rule_value"},
        "basis": {"kind": "official_text"},
        "coheres": _quantity_coheres,
    },
    "rule_event_consequence": {
        "class": "conditional_rule",
        "text": "Under {locator}, when {event}, {consequence}.",
        "slots": {"locator": "locator", "event": "rule_event", "consequence": "rule_consequence"},
        "basis": {"kind": "official_text"},
    },
    "rule_point_source": {
        "class": "conditional_rule",
        "text": "Under {locator}, {source} is a way a player gains points.",
        "slots": {"locator": "locator", "source": "rule_point_source"},
        "basis": {"kind": "official_text"},
    },
    "official_text_recorded": {
        "class": "source_statement",
        "text": "{locator} is official text retrieved for this question.",
        "slots": {"locator": "locator"},
        "basis": {"kind": "official_text"},
    },
    "card_text_recorded": {
        "class": "source_statement",
        "text": "{card} is card text retrieved for this question.",
        "slots": {"card": "card_snapshot"},
        "basis": {"kind": "card_text"},
    },
    "assumption_stands": {
        "class": "source_statement",
        "text": "This answer rests on the assumption {assumption_slot}, open to your correction.",
        "slots": {"assumption_slot": "assumption_slot"},
        "basis": {"kind": "assumption"},
    },
}


def template_slot_types() -> set[str]:
    return {slot_type for template in CLAIM_TEMPLATES.values() for slot_type in template["slots"].values()}


def render(template_id: str, slots: dict[str, str]) -> str:
    """The claim's text. Producers do not have another way to make one."""
    template = CLAIM_TEMPLATES[template_id]
    if set(slots) != set(template["slots"]):
        raise ConsultationError(f"{template_id} takes exactly {sorted(template['slots'])}")
    rendered = {slot: SLOT_TYPES[template["slots"][slot]].get("render", lambda v: v)(value)
                for slot, value in slots.items()}
    return template["text"].format(**rendered)


def _bind_claims(bindings: Iterable[Any], *, context: dict[str, Any],
                 check: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn the producer's template choices into claims, or say why they do not bind."""
    claims: list[dict[str, Any]] = []
    problems: list[str] = []
    for position, binding in enumerate(bindings):
        label = f"claims[{position}]"
        if not isinstance(binding, dict) or set(binding) - {"template", "slots"} or \
                {"template", "slots"} - set(binding):
            problems.append(f"{label} must carry exactly template and slots; a claim's source is "
                            f"determined by its template, not supplied")
            continue
        template_id = binding["template"]
        template = CLAIM_TEMPLATES.get(template_id)
        if template is None:
            problems.append(f"{label} names the unknown template {template_id!r}")
            continue
        slots = binding["slots"]
        if not isinstance(slots, dict) or set(slots) != set(template["slots"]):
            problems.append(f"{label} must fill exactly {sorted(template['slots'])} for {template_id}")
            continue
        bad = False
        for slot, value in slots.items():
            slot_type = template["slots"][slot]
            if not SLOT_TYPES[slot_type]["admits"](context, value):
                problems.append(f"{label}.slots.{slot}={value!r} is not one of this run's "
                                f"{slot_type} values; a slot is a choice, not free text")
                bad = True
        if bad:
            continue
        if (incoherent := template.get("coheres", lambda s: None)(slots)) is not None:
            problems.append(f"{label} does not cohere: {incoherent}")
            continue
        bound_id = None
        if template["class"] == "conditional_rule":
            # T-02. Closed values can still be paired into a sentence the
            # text does not say. The claim binds only as a reading someone
            # reviewed for this exact retrieved text: document, version,
            # locator and hash all as the retriever returned them. The
            # binding's id is recorded on the claim; the producer never
            # supplies it.
            retriever, registry = context.get("retriever"), context.get("semantic_bindings")
            if retriever is None or registry is None:
                problems.append(f"{label} states a rule, and this run has no retriever or no "
                                f"semantic-binding registry to read it against")
                continue
            retrieval = retriever.retrieve(slots["locator"])
            if retrieval.get("status") != "retrieved":
                problems.append(f"{label} reads {slots['locator']!r}, which was not retrieved "
                                f"({retrieval.get('status')!r})")
                continue
            record = retrieval["record"]
            binding = registry.lookup(record, template_id, slots)
            if binding is None:
                problems.append(f"{label} reads {template_id} {json.dumps({k: v for k, v in slots.items() if k != 'locator'}, sort_keys=True)} into "
                                f"{record['locator']} ({record['document_id']}@{record['document_version']}, "
                                f"{record['text_hash'][:23]}…), which is not a reviewed reading of that text")
                continue
            bound_id = binding["binding_id"]

        basis = template["basis"]
        if basis["kind"] == "engine":
            # An engine claim's source is this run's check. The producer cannot
            # name it, both because it could not know the id before the run and
            # because letting it choose is how a claim ends up citing a check
            # that answered some other question.
            if check is None:
                problems.append(f"{label} needs an engine check and this run has none")
                continue
            if check["check_kind"] != basis["check_kind"]:
                problems.append(f"{label} is a {basis['check_kind']} claim, but the check is "
                                f"a {check['check_kind']} one")
                continue
            if check["outcome"] not in basis["outcomes"]:
                problems.append(f"{label} needs an outcome in {list(basis['outcomes'])}; "
                                f"the engine returned {check['outcome']!r}")
                continue
            ref = check["check_id"]
        else:
            # A source claim's ref is the slot it already filled: the locator,
            # the snapshot, the assumption. There is nothing left to supply.
            ref = slots["locator"] if "locator" in slots else next(iter(slots.values()))

        claims.append({
            "claim_id": f"claim-{position + 1}",
            "template": template_id,
            "claim_class": template["class"],
            "slots": dict(slots),
            "text": render(template_id, slots),
            "source": f"{basis['kind']}:{ref}",
            "binding_id": bound_id,
        })
    return claims, problems


# --- the pipeline -----------------------------------------------------------

def _seal(run: dict[str, Any]) -> dict[str, Any]:
    run["run_hash"] = canonical_hash({k: v for k, v in run.items() if k != "run_hash"})
    return run


def _not_attempted(run: dict[str, Any], reason: str, detail: str) -> dict[str, Any]:
    run["status"] = "not_attempted"
    run["not_attempted_reason"] = reason
    run["detail"] = detail
    # An abstention is tier C whether the pipeline stopped or the ledger
    # refused. The three tiers are exhaustive over runs, so a caller never has
    # to read the status to know how much authority an answer carries.
    run["tier"] = "C"
    return _seal(run)


def run_consultation(*, question: str, entry: str, draft: Any, question_kind: str = "timing_priority",
                     effect_draft: Any = None, effect_question_kind: str = "unit_damage",
                     entry_inputs: dict[str, Any] | None = None,
                     claims: Iterable[Any] = (), source_retriever: Any = None,
                     card_snapshots: dict[str, Any] | None = None,
                     semantic_bindings: Any = None) -> dict[str, Any]:
    """Run one consultation end to end, or stop and say where."""
    if not isinstance(question, str) or not question.strip():
        raise ConsultationError("question must be a non-empty string")
    if source_retriever is not None and not _is_retriever(source_retriever):
        raise ConsultationError("a source retriever must offer is_locator, retrieve_for and retrieve")
    entry_inputs = dict(entry_inputs or {})
    claims = list(claims)

    # The request records what this run actually used. An entry that needs no
    # effect state does not carry one, so the run hash moves only with inputs
    # that could have moved the answer.
    profile = ENTRIES.get(entry)
    wants_effect = bool(profile and profile["needs_effect_state"])
    request = {
        "entry": entry,
        "question_kind": question_kind,
        "effect_question_kind": effect_question_kind if wants_effect else None,
        "draft": copy.deepcopy(draft),
        "effect_draft": copy.deepcopy(effect_draft) if wants_effect else None,
        "entry_inputs": copy.deepcopy(entry_inputs),
        "claim_bindings": copy.deepcopy(claims),
    }
    run: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "question": question,
        "entry": entry,
        "request": request,
        "status": "not_attempted",
        "not_attempted_reason": None,
        "detail": "",
        "tier": None,
        "engine_declined": False,
        "coverage_statement": None,
        "position_statement": None,
        "state_assumptions": [],
        "retrieved_sources": [],
        "engine_check": None,
        "evidence_pack": None,
        "evidence_verification": None,
        "claims": [],
        "ledger": None,
    }

    if profile is None:
        return _not_attempted(run, "entry_not_covered", f"{entry!r} is not one of {sorted(ENTRIES)}")

    missing_inputs = [name for name in profile["inputs"] if name not in entry_inputs]
    if missing_inputs:
        return _not_attempted(run, "entry_inputs_missing", f"the {entry} entry needs {missing_inputs}")

    # Stage 1: every state in this run comes through S-01, so every assumption
    # it rests on is one the reader can see and correct.
    timing_artifact = state_builder.build_state_assumption(
        question=question, question_kind=question_kind, draft=draft)
    run["state_assumptions"].append(timing_artifact)
    if not timing_artifact["buildable"]:
        down = timing_artifact["downgrade"]
        return _not_attempted(run, "state_not_built",
                              f"the timing state could not be built: {down['reason']} "
                              f"{down['missing_fields'] or down['rejected_fields']}")

    effect_artifact = None
    if profile["needs_effect_state"]:
        if effect_draft is None:
            return _not_attempted(run, "entry_inputs_missing",
                                  f"the {entry} entry needs an effect_draft as well as a timing draft")
        effect_artifact = state_builder.build_state_assumption(
            question=question, question_kind=effect_question_kind, draft=effect_draft)
        run["state_assumptions"].append(effect_artifact)
        if not effect_artifact["buildable"]:
            down = effect_artifact["downgrade"]
            return _not_attempted(run, "state_not_built",
                                  f"the effect state could not be built: {down['reason']} "
                                  f"{down['missing_fields'] or down['rejected_fields']}")

    if effect_artifact is not None:
        record = timing_artifact["state"].get("combat")
        named = {obj["combat_designation"]["combat_id"]
                 for obj in effect_artifact["state"]["objects"].values()
                 if obj.get("combat_designation")}
        if record is not None and named and named != {record["combat_id"]}:
            return _not_attempted(run, "entry_inputs_missing",
                                  f"the timing draft names Combat {record['combat_id']!r} and the "
                                  f"board's designations name {sorted(named)}; the two halves "
                                  f"of one position describe one Combat")
        if record is None and named:
            return _not_attempted(run, "entry_inputs_missing",
                                  "the board carries Combat designations but the timing draft "
                                  "states no Combat")

    # Stage 2: the engine, wrapped in a pack that can be re-run by someone else.
    if entry == "timing":
        inputs = {"timing_state": timing_artifact["state"], "timing_action": entry_inputs["action"]}
    elif entry == "effect":
        inputs = {"effect_state": effect_artifact["state"], "effect_program": entry_inputs["program"]}
    elif entry in {"combat_step", "control_step"}:
        inputs = {"timing_state": timing_artifact["state"], "effect_state": effect_artifact["state"],
                  "step": entry_inputs["step"]}
    else:
        observation = entry_inputs.get("observation")
        if observation is None:
            return _not_attempted(run, "entry_inputs_missing",
                                  "the legal_action entry needs an observation")
        if problems := validate_observation(observation):
            return _not_attempted(run, "entry_inputs_missing",
                                  f"the observation is not a legal-action observation: {problems}")
        inputs = {"observation": observation, "acting_player": entry_inputs["acting_player"]}
    if "decisions" in entry_inputs:
        inputs["engine_decisions"] = entry_inputs["decisions"]

    try:
        pack = evidence.build_pack(profile["check_kind"], inputs, note=f"consultation: {question}")
    except evidence.EvidencePackError as exc:
        return _not_attempted(run, "entry_inputs_missing", f"the engine refused the inputs: {exc}")
    check = pack["engine_check"]
    run["engine_check"] = check
    run["evidence_pack"] = pack

    verification = evidence.verify_pack(pack)
    run["evidence_verification"] = verification
    if not verification["verified"]:
        return _not_attempted(run, "evidence_not_reproducible",
                              f"the pack did not re-run on this engine: {verification['reason_code']}")

    # A declined ruling does not end the run. It puts every position conclusion
    # out of reach — their templates require a verdict — and leaves the B route.
    if check["outcome"] not in DECIDING_OUTCOMES:
        run["engine_declined"] = True
        run["coverage_statement"] = COVERAGE_STATEMENT

    # Stage 3: what retrieval actually returned for this question, recorded
    # whether or not a producer went on to cite any of it.
    if source_retriever is not None:
        run["retrieved_sources"] = copy.deepcopy(source_retriever.retrieve_for(question))

    assumption_slots = {e["slot"] for artifact in run["state_assumptions"] for e in artifact["assumptions"]}
    context = {
        "timing_state": timing_artifact["state"],
        "retriever": source_retriever,
        "semantic_bindings": semantic_bindings,
        "assumption_slots": assumption_slots,
        "card_snapshots": card_snapshots or {},
    }
    bound, problems = _bind_claims(claims, context=context, check=check)
    if problems:
        return _not_attempted(run, "claim_binding_invalid", "; ".join(problems))
    if not bound:
        return _not_attempted(run, "no_claims_offered",
                              "the engine declined and no source statement was offered"
                              if run["engine_declined"] else
                              "the engine decided, but no claim was offered to carry the answer")
    run["claims"] = bound

    # Stage 4: one claim, one ledger entry. Every one of them mechanical.
    sentences = [{"text": claim["text"], "mechanical": True, "sources": [claim["source"]]}
                 for claim in bound]
    ledger_context = {
        "engine_checks": [check],
        "locator_index": source_retriever,
        "card_snapshots": card_snapshots,
        "assumption_artifact": timing_artifact,
    }
    ledger = build_ledger(question=question, sentences=sentences, **ledger_context)
    run["ledger"] = ledger
    if problems := verify_ledger(ledger, **ledger_context):
        return _not_attempted(run, "claim_binding_invalid",
                              f"the ledger this run just built does not verify: {problems}")

    run["tier"] = ledger["admissible_tier"]
    if run["tier"] == "B":
        run["position_statement"] = POSITION_STATEMENT
    run["status"] = "answered" if ledger["admissible"] else "abstained"
    if not ledger["admissible"]:
        run["detail"] = "; ".join(f"{v['code']} at claim {v['entry'] + 1}" for v in ledger["violations"])
    return _seal(run)


REQUIRED_TOP = {"schema_version", "ruleset", "question", "entry", "request", "status",
                "not_attempted_reason", "detail", "tier", "engine_declined", "coverage_statement",
                "position_statement", "state_assumptions", "retrieved_sources", "engine_check",
                "evidence_pack", "evidence_verification", "claims", "ledger", "run_hash"}
CLAIM_FIELDS = {"claim_id", "template", "claim_class", "slots", "text", "source", "binding_id"}


def validate_run(value: Any) -> list[str]:
    """Structural validation only: shape, re-rendered claim text, atomicity, local hash.

    This reads no context. It can tell that a run is internally consistent; it
    cannot tell whether the ledger records inside it were ever verified against
    anything, nor whether its evidence pack still re-runs. That is
    verify_run's job, and a run that only passed this check has not been
    verified.
    """
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["run must be a JSON object"]
    if missing := REQUIRED_TOP - set(value):
        errors.append(f"missing top-level fields: {sorted(missing)}")
    if unknown := set(value) - REQUIRED_TOP:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    if missing:
        return errors

    if value["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if value["ruleset"] != {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}:
        errors.append("ruleset must match the kernel baseline")
    if value["status"] not in STATUSES:
        errors.append(f"status must be one of {list(STATUSES)}")
    if value["entry"] not in ENTRIES and value["not_attempted_reason"] != "entry_not_covered":
        errors.append(f"entry must be one of {sorted(ENTRIES)}")
    if not isinstance(value["request"], dict) or value["request"].get("entry") != value["entry"]:
        errors.append("request must be the request this run was made from")
    if value["tier"] not in fact_ledger.TIERS:
        errors.append(f"tier must be one of {list(fact_ledger.TIERS)}; every run has one")

    # The coverage statement is derived, so it is neither omissible nor
    # attachable: it is present exactly when the engine declined, and it is the
    # sentence this module writes.
    if value["engine_declined"]:
        if value["coverage_statement"] != COVERAGE_STATEMENT:
            errors.append("a declined ruling carries the coverage statement, unedited")
    elif value["coverage_statement"] is not None:
        errors.append("a run whose engine ruled carries no coverage statement")

    # Derived the same way and for the same reason: a tier-B answer says so in
    # the artifact, and a run at any other tier does not carry the sentence.
    if value["tier"] == "B":
        if value["position_statement"] != POSITION_STATEMENT:
            errors.append("a tier-B answer carries the position statement, unedited")
    elif value["position_statement"] is not None:
        errors.append("only a tier-B answer carries the position statement")

    if value["status"] == "not_attempted":
        if value["not_attempted_reason"] not in NOT_ATTEMPTED_REASONS:
            errors.append(f"not_attempted_reason must be one of {sorted(NOT_ATTEMPTED_REASONS)}")
        if not isinstance(value["detail"], str) or not value["detail"].strip():
            errors.append("a run that was not attempted says why")
        if value["claims"] or value["ledger"] is not None:
            errors.append("a run that was not attempted carries no claims and no ledger")
        if value["tier"] != "C":
            errors.append("a run that was not attempted is an abstention, and abstentions are tier C")
    else:
        if value["not_attempted_reason"] is not None:
            errors.append("an attempted run carries no not_attempted_reason")
        if not value["claims"]:
            errors.append("an attempted run carries at least one claim")
        if not isinstance(value["ledger"], dict):
            errors.append("an attempted run carries its ledger")
        else:
            errors.extend(f"ledger: {e}" for e in fact_ledger.validate_ledger(value["ledger"]))
            if len(value["ledger"]["entries"]) != len(value["claims"]):
                errors.append(f"one claim is one ledger entry: {len(value['claims'])} claims, "
                              f"{len(value['ledger']['entries'])} entries")
        if value["status"] == "answered" and value["tier"] == "C":
            errors.append("a run answered at tier C is an abstention, and must say so")
        if value["status"] == "abstained" and value["tier"] != "C":
            errors.append("an abstention is tier C")
        # Tier A is a position conclusion. A run that reports A while carrying
        # only source statements has claimed an authority its claims do not have.
        has_position = any(isinstance(c, dict) and c.get("claim_class") == "position_conclusion"
                           for c in value["claims"])
        if value["tier"] == "A" and not has_position:
            errors.append("tier A requires a position conclusion; this run carries only source statements")
        if value["tier"] == "B" and has_position:
            errors.append("a run carrying a position conclusion is not tier B")
        classes = {c.get("claim_class") for c in value["claims"] if isinstance(c, dict)}
        if unknown_classes := sorted(classes - set(CLAIM_CLASSES)):
            errors.append(f"claims carry unknown classes {unknown_classes}")
        if value["engine_declined"] and has_position:
            errors.append("the engine declined, so no position conclusion can stand in this run")

    for position, claim in enumerate(value["claims"]):
        label = f"claims[{position}]"
        if not isinstance(claim, dict) or set(claim) != CLAIM_FIELDS:
            errors.append(f"{label} must carry exactly {sorted(CLAIM_FIELDS)}")
            continue
        template = CLAIM_TEMPLATES.get(claim["template"])
        if template is None:
            errors.append(f"{label} names the unknown template {claim['template']!r}")
            continue
        if claim["claim_class"] != template["class"]:
            errors.append(f"{label} is a {claim['claim_class']!r} claim, but {claim['template']!r} "
                          f"is a {template['class']!r} template")
        if set(claim["slots"]) != set(template["slots"]):
            errors.append(f"{label} must fill exactly {sorted(template['slots'])}")
            continue
        # The text is re-rendered. A claim whose text was edited after the fact
        # is a claim someone wrote, which is what this surface exists to prevent.
        expected = render(claim["template"], claim["slots"])
        if claim["text"] != expected:
            errors.append(f"{label}.text is {claim['text']!r}, but its template renders {expected!r}")
        if fact_ledger.is_multi_sentence(claim["text"]):
            errors.append(f"{label} renders more than one sentence")
        if not isinstance(claim["source"], str) or fact_ledger.parse_source(claim["source"]) is None:
            errors.append(f"{label}.source must be one '<kind>:<ref>' source")
        # A rule claim names the reviewed binding it rests on; nothing else
        # carries one. The id is checked against context by verify_run.
        if template["class"] == "conditional_rule":
            if not isinstance(claim["binding_id"], str) or not claim["binding_id"].startswith("ssb-"):
                errors.append(f"{label} states a rule and names no reviewed binding")
        elif claim["binding_id"] is not None:
            errors.append(f"{label} is not a rule claim and carries a binding id")

    if not errors:
        expected_hash = canonical_hash({k: v for k, v in value.items() if k != "run_hash"})
        if value["run_hash"] != expected_hash:
            errors.append("run_hash is not the hash of this run")
    return errors


def verify_run(run: Any, *, source_retriever: Any = None,
               card_snapshots: dict[str, Any] | None = None,
               semantic_bindings: Any = None) -> list[str]:
    """Consultation verification: re-run from the run's own request, and compare.

    Nothing the run says about its sources, its engine check, its ledger or its
    tier is believed. The request it carries is run again against the engine,
    retriever and snapshots supplied now, and every derived field is compared to
    what the run claims. A mismatch is named by field.
    """
    errors = validate_run(run)
    if errors:
        return [f"structural: {error}" for error in errors]

    request = run["request"]
    rebuilt = run_consultation(
        question=run["question"], entry=request["entry"], draft=request["draft"],
        question_kind=request["question_kind"], effect_draft=request["effect_draft"],
        effect_question_kind=request["effect_question_kind"] or "unit_damage",
        entry_inputs=request["entry_inputs"], claims=request["claim_bindings"],
        source_retriever=source_retriever, card_snapshots=card_snapshots,
        semantic_bindings=semantic_bindings)

    for field in ("status", "tier", "not_attempted_reason", "engine_declined", "coverage_statement"):
        if run[field] != rebuilt[field]:
            errors.append(f"{field} claims {run[field]!r}; rebuilt against this context it is "
                          f"{rebuilt[field]!r}")

    if len(run["claims"]) != len(rebuilt["claims"]):
        errors.append(f"claims claims {len(run['claims'])}; rebuilt {len(rebuilt['claims'])}")
    else:
        for position, (claimed, actual) in enumerate(zip(run["claims"], rebuilt["claims"])):
            for field in ("template", "claim_class", "slots", "text", "source", "binding_id"):
                if claimed[field] != actual[field]:
                    errors.append(f"claims[{position}].{field} claims {claimed[field]!r}; "
                                  f"rebuilt {actual[field]!r}")

    # The ledger is verified against the same context, by the module that owns
    # that judgment. A record marked verified is checked, not read.
    if isinstance(run["ledger"], dict):
        ledger_problems = verify_ledger(
            run["ledger"], [run["engine_check"]] if run["engine_check"] else [],
            source_retriever, card_snapshots,
            run["state_assumptions"][0] if run["state_assumptions"] else None)
        errors.extend(f"ledger: {problem}" for problem in ledger_problems)

    # The evidence pack is re-run, not trusted. A check swapped under its own
    # id, or inputs edited beneath it, fails here.
    if isinstance(run["evidence_pack"], dict):
        verification = evidence.verify_pack(run["evidence_pack"])
        if not verification["verified"]:
            errors.append(f"evidence pack does not re-run: {verification['reason_code']}")
        if run["engine_check"] != run["evidence_pack"]["engine_check"]:
            errors.append("the run's engine check is not the one inside its evidence pack")
        if rebuilt["engine_check"] and run["engine_check"]["result_hash"] != rebuilt["engine_check"]["result_hash"]:
            errors.append("the engine no longer reproduces this run's result")

    if run["state_assumptions"] != rebuilt["state_assumptions"]:
        errors.append("the state this run was built on is not the state its request builds now")
    if run["retrieved_sources"] != rebuilt["retrieved_sources"]:
        errors.append("retrieval returns something different for this question now")
    if run["run_hash"] != rebuilt["run_hash"]:
        errors.append("run_hash differs from the hash of the run rebuilt against this context")
    return errors


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _registry_from(path: str | None) -> Any:
    if not path:
        return None
    import source_semantic_bindings
    return source_semantic_bindings.load_registry(path)


def _retriever_from(path: str | None) -> Any:
    if not path:
        return None
    payload = _load(path)
    return TableRetriever(payload.get("table", payload), payload.get("surfaced"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run, validate, or verify one consultation over the five engine entries.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one consultation end to end")
    run.add_argument("--question", required=True)
    run.add_argument("--entry", required=True, choices=sorted(ENTRIES))
    run.add_argument("--request", required=True,
                     help="path to the request: draft, effect_draft, entry_inputs, claims")
    run.add_argument("--sources", help="path to a source retrieval table")
    run.add_argument("--bindings", help="path to a source-semantic-bindings registry")

    check = sub.add_parser("validate", help="structural validation only; this is not verification")
    check.add_argument("run")

    verify = sub.add_parser("verify", help="re-run the consultation against the given context and compare")
    verify.add_argument("run")
    verify.add_argument("--sources", help="path to a source retrieval table")
    verify.add_argument("--bindings", help="path to a source-semantic-bindings registry")
    verify.add_argument("--card-snapshots", help="path to a snapshot map")

    sub.add_parser("templates", help="list the claim templates and their slots")
    args = parser.parse_args(argv)

    if args.command == "templates":
        json.dump({name: {"class": t["class"], "text": t["text"], "slots": t["slots"],
                          "basis": t["basis"]} for name, t in sorted(CLAIM_TEMPLATES.items())},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0
    if args.command == "validate":
        problems = validate_run(_load(args.run))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("structurally valid (not verified)" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1
    if args.command == "verify":
        problems = verify_run(_load(args.run), source_retriever=_retriever_from(args.sources),
                              card_snapshots=_load(args.card_snapshots) if args.card_snapshots else None,
                              semantic_bindings=_registry_from(args.bindings))
        for problem in problems:
            print(problem, file=sys.stderr)
        print("verified against the given context" if not problems else f"{len(problems)} problem(s)")
        return 0 if not problems else 1

    request = _load(args.request)
    result = run_consultation(
        question=args.question, entry=args.entry,
        draft=request.get("draft"), question_kind=request.get("question_kind", "timing_priority"),
        effect_draft=request.get("effect_draft"),
        effect_question_kind=request.get("effect_question_kind", "unit_damage"),
        entry_inputs=request.get("entry_inputs"), claims=request.get("claims", ()),
        source_retriever=_retriever_from(args.sources),
        card_snapshots=request.get("card_snapshots"),
        semantic_bindings=_registry_from(args.bindings))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if result["status"] == "answered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
