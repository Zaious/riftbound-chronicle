#!/usr/bin/env python3
"""C-60 / C-61 (ADR-0016): the clause grammar and its compiler.

`clause-grammar.v1` is data — `skill/data/clause_grammar/clause_grammar.json`
holds the productions, each with a stable id, the rule locators it implements,
its normalization rule, the AST it produces, the engine capability it needs,
its boundary, and the two fixtures it must satisfy: a golden clause it has to
compile, and a near-miss it must **not** match. The lowering from AST to an
effect program lives here, keyed by production id; a production without a
lowering, or a lowering without a production, is a gate failure.

Agreement between two compilations is canonical, not structural (DP-82): the
canonicalizer erases what is naming — instruction ids, decision references,
program ids — and keeps everything that is meaning, including the links those
names carried, which become positions. Anything that survives is a
disagreement, classified as semantic (escalated) or as a known equivalence
(closed with an audit record).

A clause no production parses is `unsupported: clause_unparsed` carrying its
own text. It never becomes a guessed program.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

GRAMMAR_VERSION = "clause-grammar.v1"
GRAMMAR_PATH = SCRIPT_DIR.parent / "data" / "clause_grammar" / "clause_grammar.json"

# Names, not meanings: erased by the canonicalizer. The links they carried are
# kept as positions, so "this instruction depends on that one" survives.
NAMING_FIELDS = ("effect_id", "decision_ref", "program_id", "trigger_id", "modifier_id",
                 "effect_program_id", "request_id", "restriction_id", "source_note")
REFERENCE_FIELDS = ("effect_id",)  # inside predicate / depends_on payloads

# Differences that are a rewrite rather than a disagreement. Each is closed
# automatically after canonicalization, with an audit record.
KNOWN_EQUIVALENCES = {
    "instruction_naming": "instruction ids and decision references are names, not meanings",
    "unordered_set_order": "the order of an unordered set of criteria does not change the meaning",
}


class ClauseUnparsed(ValueError):
    """A clause outside the grammar. Carries its own text, never a guess."""

    reason_code = "clause_unparsed"


# --------------------------------------------------------------------------
# normalization
# --------------------------------------------------------------------------

SYMBOLS = {":rb_might:": "[m]", ":rb_energy:": "[e]", "’": "'", "‘": "'",
           "“": '"', "”": '"', "–": "-", "—": "-"}


def normalize(text: str) -> str:
    """One normalization rule, named by every production: symbols spelled out,
    case folded, whitespace collapsed, a single trailing stop removed."""
    normalized = text.strip()
    for symbol, plain in SYMBOLS.items():
        normalized = normalized.replace(symbol, plain)
    normalized = re.sub(r"\s+", " ", normalized).lower()
    return normalized[:-1] if normalized.endswith(".") else normalized


# --------------------------------------------------------------------------
# the grammar
# --------------------------------------------------------------------------


def load_grammar(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or GRAMMAR_PATH).read_text(encoding="utf-8"))


def _trigger(field: str, trigger_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"object_fields": {field: [{"trigger_id": trigger_id, "controller": "$controller",
                                       "source_object": "$source_object", "controller_order": 0,
                                       "effect_program_id": "$clause_id", "optional_at_finalize": False,
                                       **(extra or {})}]}}




# --------------------------------------------------------------------------
# sub-grammars (DP-84)
# --------------------------------------------------------------------------


def slot_alternatives(grammar: dict[str, Any], production: dict[str, Any], slot: str) -> list[str]:
    """The alternatives of `slot` this production admits — all of the
    sub-grammar's, unless the production names a subset."""
    declared = (production.get("slots") or {}).get(slot)
    available = list(grammar["sub_grammars"][slot]["alternatives"])
    if declared is None:
        return available
    unknown = [name for name in declared if name not in available]
    if unknown:
        raise KeyError(f"{production['production_id']} names alternatives {unknown} that {slot} does not have")
    return list(declared)


def build_pattern(grammar: dict[str, Any], production: dict[str, Any]) -> str:
    """The production's template with each `{slot}` replaced by an alternation
    over the alternatives it admits, each tagged so the match says which one
    it was. A template with no slots is its own pattern."""
    pattern = production["template"]
    for slot in (production.get("slots") or {}):
        alternatives = grammar["sub_grammars"][slot]["alternatives"]
        branches = [f"(?P<{slot}__{name}>{alternatives[name]['pattern']})"
                    for name in slot_alternatives(grammar, production, slot)]
        pattern = pattern.replace("{" + slot + "}", "(?:" + "|".join(branches) + ")")
    return pattern


def resolve_slots(grammar: dict[str, Any], production: dict[str, Any], match: re.Match) -> dict[str, Any]:
    """Which alternative each slot matched, and the value the sub-grammar
    gives it."""
    resolved: dict[str, Any] = {}
    for slot in (production.get("slots") or {}):
        for name in slot_alternatives(grammar, production, slot):
            if match.groupdict().get(f"{slot}__{name}") is not None:
                alternative = grammar["sub_grammars"][slot]["alternatives"][name]
                resolved[slot] = {"alternative": name, **copy.deepcopy(alternative["value"])}
                break
    return resolved



# -- lowerings: AST -> what the pack calls `execution` ----------------------
# Each returns {"program_effects": [...]} and/or {"passive": {...}} /
# {"play_timing": ...}. The card's own declaration is not a clause's business.

def _lower_play_timing(params):
    return {"play_timing": params["timing"], "ast": {"node": "play_timing", "timing": params["timing"]}}




def _lower_give_might(params, slots):
    selector, delta = slots["selector"], slots["might_delta"]
    amount = int(params.get(f"{delta['alternative']}_amount"))
    signed = amount if delta["direction"] == "increase" else -amount
    effect: dict[str, Any] = {"op": "modify_might", "effect_id": "buff", "amount": signed,
                              "duration": slots["duration"]["duration"], "source": "$chain_item"}
    if params.get("floor") is not None:
        effect["minimum"] = int(params["floor"])
    effect.update(_selector_fields(selector))
    return {"program_effects": [effect],
            "ast": {"node": "instruction", "op": "modify_might",
                    "params": {"amount": signed, "duration": slots["duration"]["duration"],
                               "selector": selector["alternative"],
                               **({"minimum": int(params["floor"])} if params.get("floor") is not None else {})}}}


def _lower_grant_keyword(params, slots):
    selector, keyword = slots["selector"], slots["grantable_keyword"]
    value = params.get(f"{keyword['keyword']}_grant_value")
    effect: dict[str, Any] = {"op": "grant_keyword", "effect_id": "kw", "keyword": keyword["keyword"],
                              "duration": slots["duration"]["duration"], "source": "$chain_item"}
    if value is not None:
        effect["value"] = int(value)
    effect.update(_selector_fields(selector))
    return {"program_effects": [effect],
            "ast": {"node": "instruction", "op": "grant_keyword",
                    "params": {"keyword": keyword["keyword"], "duration": slots["duration"]["duration"],
                               "selector": selector["alternative"],
                               **({"value": int(value)} if value is not None else {})}}}


def _selector_fields(selector: dict[str, Any]) -> dict[str, Any]:
    """How the engine names the thing a selector picks: a chosen target, a
    criteria expansion, or the source object itself."""
    if selector["scope"] == "source":
        return {"object_id": "$source_object"}
    if selector["scope"] == "referent":
        # DP-86: no criteria, no zone class - the object is whichever one the
        # earlier decision produced. The sequence rebinds this reference; a
        # clause that never gets one stays unbound and is reported as such.
        return {"target": {"decision_ref": REFERENT_REF}}
    criteria = {k: v for k, v in selector.items() if k in {"kind", "controller_relation"}}
    if selector["scope"] == "affected":
        return {"affected": {"criteria": {**criteria, "location": "board"}}}
    target = {"decision_ref": "t", "chosen_zone_class": "board", **criteria}
    if selector.get("exclude_source"):
        # Round H: "another". The engine binds the sentinel to the program's
        # own source_object at selection time, so the exclusion is by identity.
        target["exclude_source_identity"] = "$source_identity"
    return {"target": target}


def _lower_object_keyword(params, slots):
    keyword = slots["keyword"]
    value = params.get(f"{keyword['keyword']}_value")
    ast = {"node": "keyword", "keyword": keyword["keyword"],
           "value": int(value) if value is not None else None,
           "implemented": keyword["implemented"]}
    if not keyword["implemented"]:
        # DP-85: the catalogue names it, the engine does not implement it.
        # That is a known boundary, not a parse - it never becomes a program.
        return {"ast": ast, "known_unsupported": "keyword_not_implemented"}
    fields: dict[str, Any] = {"keywords": [keyword["keyword"]]}
    if value is not None:
        fields["shield_value"] = int(value)
    return {"passive": {"object_fields": fields}, "ast": ast}



def _lower_draw(params):
    count = int(params["count"])
    return {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": count}],
            "ast": {"node": "instruction", "op": "draw", "params": {"count": count, "player": "$controller"}}}


def _lower_deal_unit_at_battlefield(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                                 "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                            "location": "battlefield"}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "target": {"kind": "unit", "location": "battlefield"}}}}


def _lower_deal_all_enemy_at_battlefield(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                                 "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "battlefield"},
                                 "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy",
                                                           "location": "target_battlefield"}}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "target": {"kind": "battlefield"},
                               "affected": {"kind": "unit", "controller_relation": "enemy",
                                            "location": "target_battlefield"}}}}


def _lower_deal_all_enemy_in_combat(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "barrage", "amount": amount,
                                 "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy",
                                                           "location": "active_combat"}}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "affected": {"kind": "unit", "controller_relation": "enemy",
                                                              "location": "active_combat"}}}}


def _lower_deal_all_units_at_battlefields(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                                 "affected": {"criteria": {"kind": "unit", "location": "any_battlefield"}}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "affected": {"kind": "unit", "location": "any_battlefield"}}}}


def _lower_channel_exhausted(params):
    count = int(params["count"])
    return {"program_effects": [{"op": "channel_rune", "effect_id": "ch", "player": "$controller", "count": count,
                                 "entry_state": "exhausted"}],
            "ast": {"node": "instruction", "op": "channel_rune",
                    "params": {"count": count, "entry_state": "exhausted", "player": "$controller"}}}


def _lower_return_from_trash(params):
    return {"program_effects": [{"op": "return_to_hand", "effect_id": "ret",
                                 "target": {"decision_ref": "t", "chosen_zone_class": "non_board", "kind": "unit",
                                            "location": "trash", "zone_owner_relation": "own"}}],
            "ast": {"node": "instruction", "op": "return_to_hand",
                    "params": {"target": {"kind": "unit", "location": "trash", "zone_owner_relation": "own"}}}}


def _lower_while_runes_might(params):
    runes, amount = int(params["runes"]), int(params["amount"])
    return {"passive": {"object_fields": {"conditional_might": [
                {"modifier_id": "clause", "amount": amount,
                 "condition": {"kind": "runes_at_least", "count": runes}}]}},
            "ast": {"node": "conditional_might", "amount": amount,
                    "condition": {"kind": "runes_at_least", "count": runes}}}


def _lower_units_enter_ready(params):
    return {"program_effects": [{"op": "grant_turn_effect", "effect_id": "grant",
                                 "turn_effect_kind": "entry_state_for_played_units", "value": "ready",
                                 "controller": "$controller", "source": "$chain_item"}],
            "ast": {"node": "instruction", "op": "grant_turn_effect",
                    "params": {"turn_effect_kind": "entry_state_for_played_units", "value": "ready"}}}


def _lower_self_cost_reduction(params):
    """Round H: "If <condition>, this costs N less." — the card's own text,
    a fixed Energy amount, a registered condition leaf. The program is not an
    instruction: it is a printed characteristic the play transaction reads."""
    return {
        "object_fields": {"printed_cost_modifications": [{
            "modification_id": "own-text", "kind": "energy_reduction", "amount": int(params["amount"]),
            "condition": {"kind": "score_within_of_victory", "count": int(params["within"])},
        }]},
        "ast": {"node": "self_cost_reduction", "amount": int(params["amount"]),
                "condition": {"kind": "score_within_of_victory", "count": int(params["within"])}},
    }


def _lower_empty(params):
    return {"ast": {"node": "empty"}}


# Composable productions receive the resolved slots as well as the raw groups.
# Core 135.2.e.7 / 808.1.d: `[keyword][>] ability` — the keyword names the
# trigger condition, the inner clause is the effect. Only the keywords the
# engine implements as a trigger get a program; the rest are known_unsupported.
KEYWORDED_TRIGGERS = {"deathknell": ("death_triggers", "deathknell")}


def _lower_keyworded_ability(params, slots):
    keyword = slots["keyword"]
    name = keyword["keyword"]
    if name not in KEYWORDED_TRIGGERS or not keyword["implemented"]:
        return {"ast": {"node": "keyworded_ability", "keyword": name, "implemented": False},
                "known_unsupported": "keyword_not_implemented"}
    field, trigger_id = KEYWORDED_TRIGGERS[name]
    return {"passive": _trigger(field, trigger_id),
            "object_fields_extra": {"keywords": [name]},
            "ast": {"node": "keyworded_ability", "keyword": name, "trigger_field": field}}


def _lower_defends_alone_aura(params, slots):
    """Core 477.3 / 460: a standing arithmetic modifier over a named combat
    condition. The engine already carries exactly this condition
    (AURA_CONDITION_KINDS), so the clause supplies the amount and nothing else."""
    delta = slots["might_delta"]
    signed = int(params["increase_amount"]) if delta["direction"] == "increase" else -int(params["decrease_amount"])
    return {
        "state_lists": {"might_auras": [{
            "modifier_id": "$clause_id", "source_object": "$source_object", "controller": "$controller",
            "amount": signed, "condition": {"kind": "friendly_unit_defends_alone"},
        }]},
        "ast": {"node": "passive", "kind": "might_aura",
                "params": {"amount": signed, "condition": "friendly_unit_defends_alone"}},
    }


def _lower_single_target_op(op: str, effect_id: str, capability: str):
    """Ready and Buff are the same shape: one op, one chosen object, no
    parameters of their own. The selector carries every difference."""
    def lower(params, slots):
        effect: dict[str, Any] = {"op": op, "effect_id": effect_id}
        effect.update(_selector_fields(slots["selector"]))
        return {"program_effects": [effect],
                "ast": {"node": "instruction", "op": op,
                        "params": {"selector": slots["selector"]["alternative"]}}}
    return lower


COMPOSABLE = {
    "while_a_friendly_unit_defends_alone_it_gets_might": _lower_defends_alone_aura,
    "heal_selector": _lower_single_target_op("heal_all_damage", "hl", "heal_all_damage"),
    "exhaust_selector": _lower_single_target_op("exhaust", "ex", "exhaust"),
    "recall_selector": _lower_single_target_op("recall", "rc", "recall"),
    "ready_selector": _lower_single_target_op("ready", "rd", "ready"),
    "buff_selector": _lower_single_target_op("buff", "bf", "buff"),
    "keyworded_ability": _lower_keyworded_ability,
    "give_might_for_duration": _lower_give_might,
    "grant_keyword_for_duration": _lower_grant_keyword,
    "object_keyword": _lower_object_keyword,
}

def _lower_card_self_offer(params):
    """Core 356.2.b: the card prints the offer; the engine resolves the Power
    to the card's own Domain when the play is declared, and abstains when the
    Domains are not observed. Nothing here reads the board."""
    return {
        "object_fields": {"optional_additional_costs": [
            {"cost_offer_id": "$clause_id", "payment": {"kind": "power_own_domain", "amount": 1}}]},
        "ast": {"node": "passive", "kind": "optional_additional_cost",
                "params": {"payment": "power_own_domain", "amount": 1}},
    }


def _lower_death_replacement(params):
    """Core 370.1.b: what happens instead of the death. The list starts with
    killing the source; a following clause of the same card adds to it, and
    its referents name the unit that would have died rather than re-choosing
    one (Codex: the subject is captured, not re-found)."""
    return {
        "state_lists": {"replacement_effects": [{
            "replacement_id": "$clause_id", "controller": "$controller", "source_object": "$source_object",
            "mode": "replace_with", "event_op": "kill", "optional": False, "uses_remaining": None,
            "target_controller_relation": "friendly",
            "replacement_effects": [{"op": "kill", "effect_id": "kill-self", "object_id": "$source"}],
        }]},
        "replacement_continuation": "$clause_id",
        "ast": {"node": "passive", "kind": "replacement", "params": {"event_op": "kill", "mode": "replace_with"}},
    }


LOWERINGS = {
    "if_a_friendly_unit_would_die_kill_this_instead": _lower_death_replacement,
    "you_may_pay_own_domain_power_as_additional_cost_to_play_me": _lower_card_self_offer,
    "play_timing_keyword": _lower_play_timing,
    "draw_n": _lower_draw,
    "deal_n_to_a_unit_at_a_battlefield": _lower_deal_unit_at_battlefield,
    "deal_n_to_all_enemy_units_at_a_battlefield": _lower_deal_all_enemy_at_battlefield,
    "deal_n_to_all_enemy_units_in_combat": _lower_deal_all_enemy_in_combat,
    "deal_n_to_all_units_at_battlefields": _lower_deal_all_units_at_battlefields,
    "channel_n_rune_exhausted": _lower_channel_exhausted,
    "return_a_unit_from_your_trash_to_your_hand": _lower_return_from_trash,
    "while_you_have_n_runes_i_have_might": _lower_while_runes_might,
    "units_you_play_this_turn_enter_ready": _lower_units_enter_ready,
    "no_rules_text": _lower_empty,
    "self_cost_reduction_score": _lower_self_cost_reduction,
}

# Productions that wrap another clause: "When you play me, <inner>."
TRIGGER_WRAPPERS = {
    "when_you_play_me": ("play_triggers", "on-play", None),
    "when_i_move": ("move_triggers", "on-move", None),
    "at_the_end_of_your_turn": ("end_of_turn_triggers", "eot", None),
    # Core 469.1: the unit conquering is the one at the Battlefield being
    # scored. That is the engine's default scope for a conquer trigger; the
    # clause states it rather than relying on the default.
    "when_i_conquer": ("conquer_triggers", "on-conquer", {"scope": "unit_here"}),
}


# --------------------------------------------------------------------------
# DP-86: sequencing, referents and linked prefixes
# --------------------------------------------------------------------------

# The decision reference a referent target carries until the sequence binds it
# to the one the earlier part actually used.
REFERENT_REF = "$referent"

# Every way a clause can come back unsupported. Gates that check reason codes
# import this rather than keeping their own copy, so adding a way to abstain
# cannot leave a gate silently accepting fewer of them (the DP-85 lesson).
ABSTENTION_REASONS = frozenset({
    "clause_unparsed",                 # no production matches
    "keyword_not_implemented",         # the catalogue names it, the engine does not implement it
    "link_antecedent_not_available",   # "if you do" with no readable previous instruction (DP-86)
    "referent_not_bound",              # "it" with nothing before it to be (DP-86)
    "cost_offer_not_declared",         # "if you paid additional cost" with no offer on this card
})

# A closed white-list. A connective outside it does not join anything; the
# clause is unparsed rather than guessed at.
SEQUENCE_CONNECTIVES = (", then ", ", and ", " and ")
# The three prefixes that read the *previous clause's* receipt. Core 359.3.e.14
# and 430.5: they test what the earlier instruction did, not what the state
# looks like now.
LINK_PREFIXES = {
    "if you do, ": "action_performed",
    "if you can't, ": "requested_count_not_reached",
    "otherwise, ": "action_not_performed",
}
# The one prefix that reads a *cost* receipt instead of an operation receipt.
# It is bound to an offer an earlier clause of the same card declared, so it
# can never read another card's payment (Codex's three-way binding).
COST_LINK_PREFIXES = {
    "if you paid additional cost, ": "cost_paid",
    "if you did not pay additional cost, ": "cost_not_paid",
}


def _offer_of(previous: dict[str, Any] | None) -> str | None:
    """The card-self cost offer the previous clause declared, if it declared
    exactly one. Two offers make "the additional cost" ambiguous, and the
    clause abstains rather than picking one."""
    if not isinstance(previous, dict) or previous.get("unsupported"):
        return None
    offers = ((previous.get("passive") or {}).get("object_fields", {}) or {}).get("optional_additional_costs") or []
    return offers[0]["cost_offer_id"] if len(offers) == 1 else None


# Core 402.2: "X or Y" is a mode chosen by the controller, not two things
# that both happen. It is deliberately *not* one of the sequence connectives -
# a sequence performs both parts, and reading "or" as one would silently do
# twice what the card says to do once.
MODE_CONNECTIVE = " or "


def _split_modes(normalized: str) -> list[str] | None:
    """The modes of a modal clause, or None. Exactly one "or": a clause with
    two is a nesting the grammar does not read, and guessing which binds
    tighter would change what the card does."""
    if normalized.count(MODE_CONNECTIVE) != 1:
        return None
    return [part.strip() for part in normalized.split(MODE_CONNECTIVE)]


def _split_sequence(normalized: str) -> list[str] | None:
    """The parts of a sequenced clause, in the order they are performed.

    "A, then B" is two; "A, B, and C" is three. Splitting is strictly by the
    white-listed connectives, and the Oxford comma is only honoured when an
    "and" closes the list — so a clause whose comma belongs to one instruction
    ("to a minimum of 0") is never torn in half.
    """
    for connective in (", then ",):
        if connective in normalized:
            head, tail = normalized.split(connective, 1)
            return [head.strip(), tail.strip()]
    for connective in (", and ", " and "):
        if connective in normalized:
            head, tail = normalized.rsplit(connective, 1)
            parts = [p.strip() for p in head.split(", ")] if connective == ", and " else [head.strip()]
            return [p for p in parts + [tail.strip()] if p]
    return None


def _antecedent_of(previous: dict[str, Any] | None) -> str | None:
    """The instruction whose receipt a linked prefix reads: the last one the
    previous clause actually emitted. None when there is nothing to read -
    no previous clause, a clause the grammar could not read, or one that
    performed nothing (a passive-only clause leaves no receipt)."""
    if not isinstance(previous, dict) or previous.get("unsupported"):
        return None
    if previous.get("production_id") == "linked_prefix":
        # "If you do, X. Otherwise, Y." - both branches test the *same*
        # receipt. Chaining the second onto the first's own instruction would
        # make Y depend on X having happened, which is the opposite of what
        # "otherwise" says.
        return previous.get("antecedent_effect_id")
    effects = previous.get("program_effects") or []
    return effects[-1].get("effect_id") if effects else None


def _referent_of(effects: list[dict[str, Any]]) -> str | None:
    """The decision an earlier instruction chose its object with. Sharing it is
    how "it" and "that unit" name *that* object rather than another one that
    happens to match (Codex's DP-86 contract)."""
    for effect in reversed(effects):
        target = effect.get("target")
        if isinstance(target, dict) and isinstance(target.get("decision_ref"), str):
            return target["decision_ref"]
    return None


# Core 359.3.e.4: the object the replaced event was acting on, and the
# identity it had at that moment. Both are bound by the engine when the
# replacement applies.
REPLACEMENT_SUBJECT = {"object_id": "$affected", "subject_identity": "$affected_identity"}


def _bind_to_replacement_subject(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Point every referent at the object that would have died. It carries the
    identity that object had when the replacement applied, so a later
    instruction cannot land on a different object at the same id - and it is
    never re-chosen, so it can never become the Gear or a fresh target."""
    bound = copy.deepcopy(effects)
    for effect in bound:
        target = effect.get("target")
        if isinstance(target, dict) and target.get("decision_ref") == REFERENT_REF:
            effect.pop("target")
            effect.update(copy.deepcopy(REPLACEMENT_SUBJECT))
    return bound


def _has_unbound_referent(effects: list[dict[str, Any]]) -> bool:
    """True while an instruction still points at $referent: it names an object
    no decision has produced yet, so it cannot be run."""
    return any(isinstance(e.get("target"), dict) and e["target"].get("decision_ref") == REFERENT_REF
               for e in effects)


def _rebind_referents(effects: list[dict[str, Any]], decision_ref: str) -> list[dict[str, Any]]:
    """Point every referent target at the decision the earlier part used."""
    bound = copy.deepcopy(effects)
    for effect in bound:
        target = effect.get("target")
        if isinstance(target, dict) and target.get("decision_ref") == REFERENT_REF:
            target["decision_ref"] = decision_ref
    return bound



# --------------------------------------------------------------------------
# compiling
# --------------------------------------------------------------------------


def compile_clause(text: str, grammar: dict[str, Any] | None = None,
                   previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """One clause in, one typed result out. Deterministic: the same text
    always produces the same production, AST and program.

    ``previous`` is the compiled result of the clause immediately before this
    one on the same card. It is the only thing "if you do" is allowed to read
    (DP-86): the receipt of what that instruction did, never the state now and
    never a re-reading of the text.
    """
    grammar = grammar or load_grammar()
    normalized = normalize(text)

    # DP-86: a prefix that tests the previous clause's receipt. Without a
    # previous clause in view there is no receipt to test, and guessing one
    # from the text is exactly what Core 359.3.e.14 forbids - so abstain.
    for prefix, link in COST_LINK_PREFIXES.items():
        if not normalized.startswith(prefix):
            continue
        offer = _offer_of(previous)
        if offer is None:
            return {"production_id": "cost_linked_prefix", "unsupported": True,
                    "reason_code": "cost_offer_not_declared", "text": text, "normalized": normalized, "link": link,
                    "reason": f"{prefix.strip()!r} reads an additional cost this card has not declared exactly once"}
        inner = compile_clause(normalized[len(prefix):], grammar)
        if inner.get("unsupported"):
            return {"production_id": "cost_linked_prefix", "unsupported": True,
                    "reason_code": inner.get("reason_code", "clause_unparsed"), "text": text,
                    "reason": f"the linked instruction did not parse: {normalized[len(prefix):]!r}"}
        effects = copy.deepcopy(inner.get("program_effects", []))
        predicate = {"kind": link, "cost_id": f"self_offer:{offer}", "cost_offer_id": offer}
        for effect in effects:
            effect.setdefault("predicate", predicate)
        return {
            "production_id": "cost_linked_prefix", "unsupported": False, "text": text, "normalized": normalized,
            "params": {}, "slots": {}, "link": link, "cost_offer_id": offer,
            "rule_locators": ["Core 356.4.f.1", "Core 356.2.b.1"] + inner["rule_locators"],
            "required_capability": sorted(set(inner["required_capability"]) | {"cost_predicates"}),
            "ast": {"node": "cost_linked", "link": link, "reads": offer, "then": inner["ast"]},
            "program_effects": effects,
        }

    for prefix, link in LINK_PREFIXES.items():
        if not normalized.startswith(prefix):
            continue
        antecedent = _antecedent_of(previous)
        if antecedent is None:
            return {"production_id": "linked_prefix", "unsupported": True,
                    "reason_code": "link_antecedent_not_available", "text": text, "normalized": normalized,
                    "link": link,
                    "reason": f"{prefix.strip()!r} tests the previous instruction's receipt, "
                              f"and no readable previous instruction is in view"}
        inner = compile_clause(normalized[len(prefix):], grammar)
        if inner.get("unsupported"):
            return {"production_id": "linked_prefix", "unsupported": True,
                    "reason_code": inner.get("reason_code", "clause_unparsed"), "text": text,
                    "reason": f"the linked instruction did not parse: {normalized[len(prefix):]!r}"}
        effects = copy.deepcopy(inner.get("program_effects", []))
        if referent := _referent_of(previous.get("program_effects", []) or []):
            effects = _rebind_referents(effects, referent)
        predicate = {"kind": link, "effect_id": antecedent}
        for effect in effects:
            effect.setdefault("predicate", predicate)
        return {
            "production_id": "linked_prefix", "unsupported": False, "text": text, "normalized": normalized,
            "params": {}, "slots": {}, "link": link, "antecedent_effect_id": antecedent,
            "rule_locators": ["Core 359.3.e.14", "Core 430.5"] + inner["rule_locators"],
            "required_capability": sorted(set(inner["required_capability"]) | {"instruction_conditions"}),
            "ast": {"node": "linked", "link": link, "reads": antecedent, "then": inner["ast"]},
            "program_effects": effects,
        }

    for production in grammar["productions"]:
        match = re.fullmatch(build_pattern(grammar, production), normalized)
        if match is None:
            continue
        slots = resolve_slots(grammar, production, match)
        params = {k: v for k, v in match.groupdict().items() if v is not None and "__" not in k}
        production_id = production["production_id"]
        if production_id == "keyworded_ability":
            lowered = _lower_keyworded_ability(match.groupdict(), slots)
            if lowered.pop("known_unsupported", None) is not None:
                return {"production_id": production_id, "unsupported": True, "reason_code": "keyword_not_implemented",
                        "text": text, "normalized": normalized, "slots": slots, "ast": lowered.get("ast"),
                        "rule_locators": list(production["rule_locators"]),
                        "reason": f"the catalogue names {slots['keyword']['keyword']!r} but the engine does not implement it as a trigger"}
            inner = compile_clause(match.group("inner"), grammar, previous=previous)
            if inner.get("unsupported"):
                return {"production_id": production_id, "unsupported": True, "reason_code": inner.get("reason_code", "clause_unparsed"),
                        "text": text, "inner_text": match.group("inner"),
                        "reason": f"the keyword bound an ability the grammar cannot read: {match.group('inner')!r}"}
            fields = dict(lowered["passive"]["object_fields"])
            fields.update(lowered.pop("object_fields_extra", {}))
            return {
                "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
                "params": {}, "slots": slots,
                "rule_locators": list(production["rule_locators"]) + inner["rule_locators"],
                "required_capability": sorted(set(production["required_capability"]) | set(inner["required_capability"])),
                "ast": {"node": "keyworded_ability", "keyword": slots["keyword"]["keyword"], "then": inner["ast"]},
                "passive": {"object_fields": fields},
                "program_effects": inner.get("program_effects", []),
            }
        if production_id in TRIGGER_WRAPPERS:
            field, trigger_id, trigger_extra = TRIGGER_WRAPPERS[production_id]
            inner = compile_clause(params["inner"], grammar, previous=previous)
            if inner.get("unsupported"):
                # The wrapper keeps the inner clause's own reason. "The
                # trigger parsed and its instruction did not" and "the
                # instruction reads a cost this card never declared" are
                # different findings, and only the second names a fix.
                return {"production_id": production_id, "unsupported": True,
                        "reason_code": inner.get("reason_code", "clause_unparsed"),
                        "text": text, "inner_text": params["inner"],
                        "reason": f"the wrapper parsed but its instruction did not: {params['inner']!r} "
                                  f"({inner.get('reason', '')})"}
            return {
                "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
                "params": params, "rule_locators": production["rule_locators"] + inner["rule_locators"],
                "ast": {"node": "triggered", "on": production_id, "then": inner["ast"]},
                "passive": _trigger(field, trigger_id, trigger_extra),
                "program_effects": inner.get("program_effects", []),
                "required_capability": sorted(set(production["required_capability"]) | set(inner["required_capability"])),
                # what the inner clause bound to travels with the wrapper, so a
                # card-level check sees it
                **({"modal": {**inner["modal"], "timing": "trigger_finalization"}} if inner.get("modal") else {}),
                **({"cost_offer_id": inner["cost_offer_id"]} if inner.get("cost_offer_id") is not None else {}),
                **({"antecedent_effect_id": inner["antecedent_effect_id"]} if inner.get("antecedent_effect_id") is not None else {}),
            }
        lowered = COMPOSABLE[production_id](params, slots) if production_id in COMPOSABLE else LOWERINGS[production_id](params)
        if "object_fields" in lowered or "state_lists" in lowered:
            # ADR-0007: what a card contributes while it exists is either a
            # field on its own object or an entry in a state-level list. An
            # aura is the second kind - it is not a field of the unit it
            # modifies, because it modifies whichever unit is defending alone.
            passive_shape = {k: lowered[k] for k in ("object_fields", "state_lists") if k in lowered}
            lowered = {**{k: v for k, v in lowered.items() if k not in {"object_fields", "state_lists"}},
                       "passive": passive_shape}
        known = lowered.pop("known_unsupported", None)
        if known is not None:
            # Named by the catalogue, not implemented by the engine (DP-85).
            # It is a boundary the grammar knows, not a clause it read.
            return {"production_id": production_id, "unsupported": True, "reason_code": known,
                    "text": text, "normalized": normalized, "slots": slots, "ast": lowered.get("ast"),
                    "rule_locators": list(production["rule_locators"]),
                    "reason": f"{production_id} recognised the clause, but the engine does not implement it"}
        compiled = {
            "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
            "params": params, "slots": slots, "rule_locators": list(production["rule_locators"]),
            "required_capability": list(production["required_capability"]),
            **lowered,
        }
        if _has_unbound_referent(compiled.get("program_effects", [])):
            compiled["needs_referent"] = True
        return compiled
    # Round H: a mode. Both halves must be instructions the grammar reads and
    # neither may contribute a passive - a mode that changes what the card *is*
    # rather than what it does is not something Core 402.2 covers.
    modes = _split_modes(normalized)
    if modes:
        compiled = [compile_clause(part, grammar) for part in modes]
        problem = next((f"{part!r} did not parse" for part, entry in zip(modes, compiled) if entry.get("unsupported")), None)
        if problem is None:
            problem = next((f"{part!r} is a passive, not an instruction" for part, entry in zip(modes, compiled)
                            if entry.get("passive")), None)
        if problem is None and any(entry.get("modal") for entry in compiled):
            problem = "a mode may not itself be modal"
        if problem is not None:
            return {"production_id": "modal_choice", "unsupported": True, "reason_code": "clause_unparsed",
                    "text": text, "normalized": normalized,
                    "reason": f"the clause offers a choice the grammar cannot read: {problem}"}
        return {
            "production_id": "modal_choice", "unsupported": False, "text": text, "normalized": normalized,
            "params": {}, "slots": {},
            "rule_locators": sorted({"Core 402.2", "Core 820.2.a"} | {loc for e in compiled for loc in e["rule_locators"]}),
            "required_capability": sorted({"modal_abilities"} | {c for e in compiled for c in e["required_capability"]}),
            "ast": {"node": "modal", "choose": 1, "of": [entry["ast"] for entry in compiled]},
            "program_effects": [],
            "modal": {
                "choose": 1,
                # A spell chooses as it is played; a triggered ability chooses
                # when the trigger is finalized. The wrapper knows which this
                # is and rewrites the timing; on its own a clause is the first.
                "timing": "play_declaration",
                "decision_ref": "mode",
                "options": [{"option_id": f"mode-{index}",
                             "effects": copy.deepcopy(entry.get("program_effects", []))}
                            for index, entry in enumerate(compiled)],
            },
        }

    # DP-86: a sequence. Every part must parse on its own - "and" joins two
    # instructions the grammar already reads, or it joins nothing.
    parts = _split_sequence(normalized)
    if parts and len(parts) > 1:
        compiled = [compile_clause(part, grammar) for part in parts]
        if any(entry.get("unsupported") for entry in compiled):
            failed = next(part for part, entry in zip(parts, compiled) if entry.get("unsupported"))
            return {"production_id": "sequence", "unsupported": True, "reason_code": "clause_unparsed",
                    "text": text, "normalized": normalized,
                    "reason": f"a connective joined an instruction the grammar cannot read: {failed!r}"}
        sequential = ", then " in normalized
        effects: list[dict[str, Any]] = []
        for index, entry in enumerate(compiled):
            part_effects = copy.deepcopy(entry.get("program_effects", []))
            if index and (referent := _referent_of(effects)):
                part_effects = _rebind_referents(part_effects, referent)
            for position, effect in enumerate(part_effects):
                effect["effect_id"] = f"{index}:{effect.get('effect_id', position)}"
                # 359.3: the parts of a sequenced clause are performed in the
                # order written. Carrying the order in the program keeps a
                # consumer from treating the list as a set.
                effect["order"] = len(effects) + position
            if index and sequential and part_effects and effects:
                # "then": the later instruction happens only if the earlier one
                # did, read off its receipt rather than recomputed (359.3.e.14).
                part_effects[0]["predicate"] = {"kind": "action_performed", "effect_id": effects[-1]["effect_id"]}
            effects.extend(part_effects)
        passive: dict[str, Any] = {}
        for entry in compiled:
            for field, value in (entry.get("passive", {}).get("object_fields", {}) or {}).items():
                passive.setdefault(field, []).extend(copy.deepcopy(value))
        return {
            "production_id": "sequence", "unsupported": False, "text": text, "normalized": normalized,
            "params": {}, "slots": {}, "parts": [entry["production_id"] for entry in compiled],
            "rule_locators": sorted({loc for entry in compiled for loc in entry["rule_locators"]}),
            "required_capability": sorted({cap for entry in compiled for cap in entry["required_capability"]}),
            "ast": {"node": "sequence", "ordered": True, "of": [entry["ast"] for entry in compiled]},
            "program_effects": effects,
            **({"passive": {"object_fields": passive}} if passive else {}),
        }

    return {"production_id": None, "unsupported": True, "reason_code": "clause_unparsed", "text": text,
            "normalized": normalized, "reason": "no production in clause-grammar.v1 matches this clause"}


def compile_card(clauses: list[dict[str, Any]], grammar: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every clause of one card, in order. The card's own declaration — its
    printed cost, its type, where it enters — is not a clause's business, so
    the compiler does not invent one."""
    grammar = grammar or load_grammar()
    compiled: list[dict[str, Any]] = []
    state_lists: dict[str, Any] = {}
    declared_offers = 0
    for clause in clauses:
        entry = compile_clause(clause["text"], grammar, previous=compiled[-1] if compiled else None)
        if not entry.get("unsupported") and entry.get("cost_offer_id") is not None and declared_offers > 1:
            # "the additional cost" names one offer. A card that prints two has
            # not said which, and the clause abstains rather than taking the
            # nearest one (Codex: bind the same cost_offer_id, do not guess it).
            entry = {"production_id": entry["production_id"], "unsupported": True,
                     "reason_code": "cost_offer_not_declared", "text": entry["text"],
                     "normalized": entry.get("normalized"),
                     "reason": f"this card declares {declared_offers} optional additional costs; "
                               "'the additional cost' does not name one of them"}
        declared_offers += len(((entry.get("passive") or {}).get("object_fields", {}) or {})
                               .get("optional_additional_costs") or [])
        compiled.append(entry)

    # Round H: a clause that continues an open replacement. "Heal that unit,
    # exhaust it, and recall it." is not something the card does on its own -
    # it is the rest of what happens instead of the death, and its referents
    # name the unit that would have died.
    for index, entry in enumerate(compiled[:-1] if compiled else []):
        replacement_id = entry.get("replacement_continuation")
        following = compiled[index + 1]
        if replacement_id is None or following.get("unsupported") or not following.get("program_effects"):
            continue
        if not _has_unbound_referent(following["program_effects"]):
            continue  # it names its own targets, so it is a clause of its own
        replacements = ((entry.get("passive") or {}).get("state_lists", {}) or {}).get("replacement_effects") or []
        if len(replacements) != 1:
            continue
        replacements[0]["replacement_effects"] = (replacements[0]["replacement_effects"]
                                                  + _bind_to_replacement_subject(following["program_effects"]))
        compiled[index + 1] = {**following, "program_effects": [],
                               "absorbed_into": replacements[0]["replacement_id"]}

    # DP-86, checked once the replacement above has had its chance to bind: a
    # referent with nothing before it to be. Refusing here is the point - the
    # alternative is re-finding an object that merely matches, which is what
    # the contract forbids.
    for index, entry in enumerate(compiled):
        if entry.get("unsupported") or not _has_unbound_referent(entry.get("program_effects", [])):
            continue
        compiled[index] = {"production_id": entry["production_id"], "unsupported": True,
                           "reason_code": "referent_not_bound", "text": entry["text"],
                           "normalized": entry.get("normalized"),
                           "reason": "the clause names a referent no earlier instruction chose"}
    effects: list[dict[str, Any]] = []
    passive: dict[str, Any] = {}
    conflicts: list[str] = []
    for entry in compiled:
        for effect in entry.get("program_effects", []) or []:
            effects.append(copy.deepcopy(effect))
        for field, value in ((entry.get("passive") or {}).get("object_fields", {}) or {}).items():
            # Two shapes of printed field: a list a card may contribute to more
            # than once (its triggers, its keywords), and a scalar it either
            # has or has not (its play timing). Extending the second would
            # silently turn "reaction" into a list nothing reads; two clauses
            # setting it differently is a card the grammar cannot represent.
            if isinstance(value, list):
                passive.setdefault(field, []).extend(copy.deepcopy(value))
            elif field in passive and passive[field] != value:
                conflicts.append(f"{field}: {passive[field]!r} then {value!r}")
            else:
                passive[field] = copy.deepcopy(value)
        for field, value in ((entry.get("passive") or {}).get("state_lists", {}) or {}).items():
            state_lists.setdefault(field, []).extend(copy.deepcopy(value))
    modal = [entry["modal"] for entry in compiled if entry.get("modal")]
    return {
        "schema_version": GRAMMAR_VERSION,
        **({"modal": modal[0]} if len(modal) == 1 else {}),
        "grammar_version": grammar["version"],
        "clauses": compiled,
        "program_effects": effects,
        "passive": ({**({"object_fields": passive} if passive else {}),
                     **({"state_lists": state_lists} if state_lists else {})} or None),
        **({"passive_conflicts": conflicts} if conflicts else {}),
        "unsupported_clauses": [{"text": e["text"], "reason_code": e["reason_code"]} for e in compiled if e.get("unsupported")],
        "complete_grammar": False,
    }


# --------------------------------------------------------------------------
# canonical comparison (DP-82)
# --------------------------------------------------------------------------


def canonical_effects(effects: list[dict[str, Any]] | None) -> list[Any]:
    """The meaning of an instruction list: names erased, the links they
    carried kept as positions, every mapping ordered."""
    effects = effects or []
    index = {effect.get("effect_id"): position for position, effect in enumerate(effects)
             if isinstance(effect, dict) and effect.get("effect_id") is not None}

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, item in sorted(value.items()):
                if key in NAMING_FIELDS:
                    if key in REFERENCE_FIELDS and item in index:
                        out["effect_index"] = index[item]
                    continue
                if key == "depends_on" and item in index:
                    out["depends_on_index"] = index[item]
                    continue
                out[key] = strip(item)
            return out
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return [strip(effect) for effect in effects]


def canonical_passive(passive: dict[str, Any] | None) -> dict[str, Any]:
    fields = (passive or {}).get("object_fields", {}) or {}
    out: dict[str, Any] = {}
    for field, value in sorted(fields.items()):
        if isinstance(value, list) and value and isinstance(value[0], dict):
            out[field] = [{k: v for k, v in sorted(entry.items()) if k not in NAMING_FIELDS} for entry in value]
        else:
            out[field] = sorted(value) if isinstance(value, list) else value
    return out


def signature(disagreement: dict[str, Any]) -> str:
    payload = json.dumps({k: disagreement[k] for k in ("field", "left", "right") if k in disagreement},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compare_compilations(left: dict[str, Any], right: dict[str, Any], *, label_left: str = "a",
                         label_right: str = "b") -> dict[str, Any]:
    """Canonical equality over the fields DP-82 names. Everything the
    canonicalizer erased is recorded as closed, with its reason; everything
    that survives is a disagreement to escalate."""
    disagreements: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []

    for field, canon in (("program_effects", canonical_effects), ("passive", canonical_passive)):
        a, b = canon(left.get(field)), canon(right.get(field))
        if a != b:
            disagreements.append({"field": field, "kind": "semantic", "left": a, "right": b})
        elif json.dumps(left.get(field), sort_keys=True, default=str) != json.dumps(right.get(field), sort_keys=True, default=str):
            closed.append({"field": field, "equivalence": "instruction_naming",
                           "note": KNOWN_EQUIVALENCES["instruction_naming"]})
    for field in ("production_id", "play_timing", "unsupported", "reason_code", "required_capability", "rule_locators"):
        if field in left or field in right:
            a, b = left.get(field), right.get(field)
            if a == b:
                continue
            if isinstance(a, list) and isinstance(b, list) and sorted(map(str, a)) == sorted(map(str, b)):
                # The same set in a different order: a rewrite, not a meaning.
                closed.append({"field": field, "equivalence": "unordered_set_order",
                               "note": KNOWN_EQUIVALENCES["unordered_set_order"]})
                continue
            disagreements.append({"field": field, "kind": "semantic", "left": a, "right": b})

    for entry in disagreements:
        entry["signature"] = signature(entry)
    return {
        "agree": not disagreements,
        "compared": [label_left, label_right],
        "disagreements": disagreements,
        "escalate": [d for d in disagreements if d["kind"] == "semantic"],
        "closed_automatically": closed,
        "audit": {"canonicalizer": GRAMMAR_VERSION, "known_equivalences": sorted(KNOWN_EQUIVALENCES)},
    }


def dedupe(disagreements: list[dict[str, Any]], seen: set[str] | None = None) -> tuple[list[dict[str, Any]], set[str]]:
    """One signature, one escalation, however many rounds it appears in."""
    seen = set(seen or ())
    fresh = []
    for entry in disagreements:
        if entry["signature"] in seen:
            continue
        seen.add(entry["signature"])
        fresh.append(entry)
    return fresh, seen


def validate_grammar(grammar: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(grammar, dict) or grammar.get("schema_version") != GRAMMAR_VERSION:
        return [f"grammar schema_version must be {GRAMMAR_VERSION}"]
    if not isinstance(grammar.get("version"), str) or not grammar["version"]:
        errors.append("grammar version must be a non-empty string")
    if grammar.get("complete_grammar") is not False:
        errors.append("complete_grammar must be false; the grammar states its own size")
    productions = grammar.get("productions")
    if not isinstance(productions, list) or not productions:
        return errors + ["productions must be a non-empty array"]
    sub_grammars = grammar.get("sub_grammars")
    if not isinstance(sub_grammars, dict) or not sub_grammars:
        errors.append("sub_grammars must be an object; a production is a template over them (DP-84)")
        sub_grammars = {}
    for name, sub in sub_grammars.items():
        if not isinstance(sub, dict) or set(sub) != {"note", "alternatives"} or not sub["alternatives"]:
            errors.append(f"sub_grammars.{name} must be {{note, alternatives}} with at least one alternative")
            continue
        for alt_name, alternative in sub["alternatives"].items():
            if not isinstance(alternative, dict) or set(alternative) != {"pattern", "value"}:
                errors.append(f"sub_grammars.{name}.{alt_name} must be {{pattern, value}}")
                continue
            try:
                re.compile(alternative["pattern"])
            except re.error as exc:
                errors.append(f"sub_grammars.{name}.{alt_name}.pattern is not a regular expression: {exc}")
    joint = grammar.get("jointly_meaningful")
    if not isinstance(joint, list) or any(not isinstance(pair, list) or len(pair) != 2 for pair in joint):
        errors.append("jointly_meaningful must be a list of slot pairs whose alternatives interact (DP-84)")
        joint = []
    for pair in joint:
        unknown = [slot for slot in pair if slot not in sub_grammars]
        if unknown:
            errors.append(f"jointly_meaningful names slots that are not sub-grammars: {unknown}")

    required = {"production_id", "form", "template", "slots", "normalization", "rule_locators", "ast_node",
                "required_capability", "boundary", "golden", "negative"}
    seen: set[str] = set()
    for index, production in enumerate(productions):
        path = f"productions[{index}]"
        if not isinstance(production, dict) or set(production) != required:
            errors.append(f"{path} must carry exactly {sorted(required)}")
            continue
        production_id = production["production_id"]
        if production_id in seen:
            errors.append(f"{path}.production_id {production_id!r} is duplicated")
        seen.add(production_id)
        if production_id not in LOWERINGS and production_id not in COMPOSABLE and production_id not in TRIGGER_WRAPPERS:
            errors.append(f"{path} has no lowering; a production that cannot be compiled is not promoted")
        if not production["rule_locators"] or not isinstance(production["required_capability"], list):
            errors.append(f"{path} must name its locators and list the capability it needs")
        if not isinstance(production["golden"], list) or not production["golden"]:
            errors.append(f"{path} has no golden fixture; it is not promoted (ADR-0016 §1)")
        if not isinstance(production["negative"], list) or not production["negative"]:
            errors.append(f"{path} has no negative fixture; it is not promoted (ADR-0016 §1)")
        if production["normalization"] != "clause-grammar.v1/normalize":
            errors.append(f"{path}.normalization must name this grammar's own rule")
        slots = production["slots"]
        if not isinstance(slots, dict):
            errors.append(f"{path}.slots must be an object mapping a slot to the alternatives it admits")
            continue
        for slot in slots:
            if slot not in sub_grammars:
                errors.append(f"{path}.slots names {slot!r}, which is not a sub-grammar")
            elif "{" + slot + "}" not in production["template"]:
                errors.append(f"{path}.slots names {slot!r}, which its template never uses")
        for placeholder in re.findall(r"\{(\w+)\}", production["template"]):
            if placeholder not in slots:
                errors.append(f"{path}.template uses {{{placeholder}}}, which its slots do not admit")
        try:
            re.compile(build_pattern(grammar, production))
        except (re.error, KeyError) as exc:
            errors.append(f"{path} does not build a regular expression: {exc}")
    missing = sorted((set(LOWERINGS) | set(COMPOSABLE) | set(TRIGGER_WRAPPERS)) - seen)
    if missing:
        errors.append(f"lowerings with no production in the contract: {missing}")
    return errors
