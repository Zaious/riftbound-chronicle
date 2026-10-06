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
# The parameterised symbols, in order. Rainbow before the general rune rule, or
# "any Domain" would normalise to a Domain called "rainbow". The forms match the
# card frames' own accessibility rendering: [1][C] for one Energy and a Domain
# Power, [A] for any Domain.
SYMBOL_PATTERNS = (
    (re.compile(r":rb_energy_(\d+):"), r"[e\g<1>]"),
    (re.compile(r":rb_rune_rainbow:"), "[a]"),
    (re.compile(r":rb_rune_([a-z]+):"), r"[rune:\g<1>]"),
)


def normalize(text: str) -> str:
    """One normalization rule, named by every production: symbols spelled out,
    case folded, whitespace collapsed, a single trailing stop removed."""
    normalized = text.strip()
    for symbol, plain in SYMBOLS.items():
        normalized = normalized.replace(symbol, plain)
    for pattern, replacement in SYMBOL_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    normalized = re.sub(r"\s+", " ", normalized).lower()
    return normalized[:-1] if normalized.endswith(".") else normalized


# --------------------------------------------------------------------------
# the grammar
# --------------------------------------------------------------------------


def load_grammar(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or GRAMMAR_PATH).read_text(encoding="utf-8"))


def _battlefield_trigger(field: str, trigger_id: str, optional: bool = False,
                         extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """A trigger printed on a Battlefield. Core 190.6.a: its controller is
    whoever controls the Battlefield when it triggers, so the descriptor names
    none - which is why this is a different shape from an object's trigger and
    not a parameter of one. package 9: `extra` carries a Trigger Condition's
    conditional statement (Core 383.2.a.1) onto the descriptor."""
    return {"battlefield_fields": {field: [{"trigger_id": trigger_id, "controller_order": 0,
                                            "effect_program_id": "$clause_id",
                                            "optional_at_finalize": optional, **(extra or {})}]}}


def _trigger(field: str | tuple[str, ...], trigger_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The object fields a triggered ability lives in. A tuple of fields is ONE ability
    with more than one trigger condition ("When I attack or defend", Core 383.4.e,
    383.4.f): the same descriptor - the same trigger_id - in each field, so whichever
    condition is met schedules it, and one event can never schedule it twice."""
    descriptor = {"trigger_id": trigger_id, "controller": "$controller",
                  "source_object": "$source_object", "controller_order": 0,
                  "effect_program_id": "$clause_id", "optional_at_finalize": False,
                  **(extra or {})}
    fields = (field,) if isinstance(field, str) else tuple(field)
    return {"object_fields": {name: [dict(descriptor)] for name in fields}}




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
    if keyword["keyword"] == "hidden":
        # [Hidden] is not an object keyword to the engine: it is the card's permission to be
        # hidden (Core 811), read by hidden.hide_card as `hidden: true` (effect_ir validates
        # the flag, and OBJECT_KEYWORDS has no "hidden"). Lowering it to keywords made every
        # Hidden card an invalid state (found 2026-09-24).
        return {"passive": {"object_fields": {"hidden": True}}, "ast": ast}
    fields: dict[str, Any] = {"keywords": [keyword["keyword"]]}
    if value is not None:
        # the value belongs to its own keyword: [Shield 3] -> shield_value (Core 814.1.b.2),
        # [Deflect 2] -> deflect_value (809.1.b). Writing every value to shield_value made
        # [Deflect 2] cost 1 (found 2026-09-22, round-1 engine support measurement).
        fields[f"{keyword['keyword']}_value"] = int(value)
    return {"passive": {"object_fields": fields}, "ast": ast}



def _lower_no_damage_after_two_moves(params):
    # package 9 (Kayn - Unleashed): the card's own replacement - prevent_event on a Deal to it, while it has made two
    # or more real Moves this turn (effect_ir condition moved_this_turn_at_least, the moves_this_turn ledger)
    return {
        "state_lists": {"replacement_effects": [{
            "replacement_id": "$clause_id", "controller": "$controller", "source_object": "$source_object",
            "target_object_id": "$source_object", "mode": "prevent_event", "event_op": "deal_damage",
            "optional": False, "uses_remaining": None,
            "condition": {"kind": "moved_this_turn_at_least", "count": 2}}]},
        "ast": {"node": "passive", "kind": "replacement", "params": {"event_op": "deal_damage", "mode": "prevent_event",
                                                                     "condition": "moved_this_turn_at_least 2"}},
    }


def _lower_next_death_heal_exhaust_recall(params):
    # package 9 (Highlander): the public choice is the grant's target, chosen at play (Core 355.5); the grant is bound
    # to that identity, applies once, this turn (effect_ir grant_replacement); each play's grant is its own
    # (granted_by is the chain item), so two of them on one Unit are two replacements
    target = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}
    instead = [{"op": "heal_all_damage", "object_id": "$granted_target"},
               {"op": "exhaust", "object_id": "$granted_target"},
               {"op": "recall", "object_id": "$granted_target"}]
    return {"program_effects": [{"op": "grant_replacement", "effect_id": "grant", "target": target,
                                 "controller": "$controller", "granted_by": "$chain_item",
                                 "replacement": {"mode": "replace_with", "event_op": "kill",
                                                 "replacement_effects": instead}}],
            "ast": {"node": "instruction", "op": "grant_replacement",
                    "params": {"selector": "friendly unit", "event_op": "kill", "duration": "this_turn", "uses": 1,
                               "instead": ["heal_all_damage", "exhaust", "recall"]}}}


def _lower_raise_might_to_match(params):
    # package 9 (Convergent Mutation): the pair of slots - "it" (the public choice, chosen at play) and "another
    # friendly unit" (a second, different target, play_transaction's distinct slots); effect_ir raise_might_to_match
    unit = {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}
    return {"program_effects": [{"op": "raise_might_to_match", "effect_id": "raise",
                                 "units": [{"decision_ref": "t", **unit}, {"decision_ref": "t2", **unit}],
                                 "duration": "this_turn", "source": "$chain_item"}],
            "ast": {"node": "instruction", "op": "raise_might_to_match",
                    "params": {"selector": "friendly unit", "to": "another friendly unit", "duration": "this_turn"}}}


def _lower_banish_then_owner_plays(params):
    # package 9 (Portal Rescue): the banish's target chosen at play; the play is limited_play linked to that banish,
    # by the card's owner, to their Base, ignore_all (effect_ir LIMITED_PLAY_PLAYERS, unit_at_players_base)
    target = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}
    return {"program_effects": [{"op": "banish", "effect_id": "ban", "target": target},
                                {"op": "limited_play", "effect_id": "lp", "linked": {"effect_id": "ban", "from": "banishment"},
                                 "player": "owner", "entry": {"kind": "unit_at_players_base"},
                                 "cost_basis": {"kind": "ignore_all"}}],
            "ast": {"node": "sequence", "of": [
                {"node": "instruction", "op": "banish", "params": {"selector": "friendly unit"}},
                {"node": "instruction", "op": "limited_play",
                 "params": {"linked": "ban", "player": "owner", "entry": "their base", "cost": "ignore_all"}}]}}


def _lower_assigned_combat_damage_last(params):
    # package 9 (Caitlyn - Patrolling): the Backline shape on the card itself (combat.py reads the keyword)
    return {"passive": {"object_fields": {"keywords": ["backline"]}},
            "ast": {"node": "passive", "kind": "combat_damage_order", "params": {"order": "last", "keyword": "backline"}}}


def _lower_deal_my_might_to_unit_at_battlefield(params):
    # package 9 (Caitlyn - Patrolling): amount_ref program_source_current_might - read as it executes; refused by name
    # (amount_ref_source_absent) when the source is no longer on the board
    ref = {"kind": "program_source_current_might"}
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount_ref": dict(ref),
                                 "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                            "location": "battlefield"}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount_ref": dict(ref), "target": {"kind": "unit", "location": "battlefield"}}}}


def _lower_any_number_of_buffs(params):
    # package 9 (Lee Sin - Ascetic): effect_ir any_number_of_buffs / buff_count
    return {"passive": {"object_fields": {"any_number_of_buffs": True}},
            "ast": {"node": "passive", "kind": "buff_permission", "params": {"buffs": "any number"}}}


def _lower_win_game(params):
    # package 9 (The Grand Plaza): Core 195 - the instruction's controller wins; 196 - the game ends
    return {"program_effects": [{"op": "win_game", "effect_id": "win", "player": "$controller"}],
            "ast": {"node": "instruction", "op": "win_game", "params": {"player": "$controller"}}}


def _lower_draw(params):
    count = int(params["count"])
    return {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": count}],
            "ast": {"node": "instruction", "op": "draw", "params": {"count": count, "player": "$controller"}}}


def _lower_draw_if_few_in_hand(params):
    """Core 413: draw N - only if the controller holds at most one card as it executes."""
    count = int(params["count"])
    condition = {"kind": "not", "of": {"kind": "zone_count_at_least", "zone": "hand", "count": 2}}
    return {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": count,
                                 "predicate": {"kind": "state_holds", "condition": condition}}],
            "ast": {"node": "instruction", "op": "draw", "params": {"count": count, "player": "$controller"},
                    "if": condition}}


def _lower_draw_per_mighty_unit(params):
    """Core 413 with a count read on execution: N for each Mighty unit the controller controls
    (708, 710). effect_ir count_per."""
    count = int(params["count"])
    per = {"kind": "units_you_control", "mighty": True}
    return {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": count,
                                 "count_per": dict(per)}],
            "ast": {"node": "instruction", "op": "draw", "params": {"count": count, "player": "$controller",
                                                                     "for_each": dict(per)}}}


def _lower_discard(params):
    """Core 422.1: the controller discards N from their own hand, chosen privately; 422.4: a
    shorter hand discards what it has, an empty one ignores the instruction."""
    count = int(params["count"])
    return {"program_effects": [{"op": "discard", "effect_id": "dc", "player": "$controller", "count": count,
                                 "decision_ref": "discard"}],
            "ast": {"node": "instruction", "op": "discard", "params": {"count": count, "player": "$controller"}}}


def _lower_deal_unit_at_battlefield(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                                 "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                            "location": "battlefield"}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "target": {"kind": "unit", "location": "battlefield"}}}}


def _lower_move_friendly_at_battlefield_to_its_base(params):
    # 2026-09-25 (The Syren): a named destination - the moved unit's own Base, resolved per
    # object as its controller's (Core 355.4.a; effect_ir player_relation object_controller)
    return {"program_effects": [{"op": "move_board_object", "effect_id": "mv",
                                 "destination": {"kind": "base", "player_relation": "object_controller"},
                                 "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                            "controller_relation": "friendly", "location": "battlefield"}}],
            "ast": {"node": "instruction", "op": "move_board_object",
                    "params": {"target": {"kind": "unit", "controller_relation": "friendly", "location": "battlefield"},
                               "destination": "its_base"}}}


def _lower_move_unit_from_battlefield_to_its_base(params):
    # 2026-09-26 (Maddened Marauder): any unit at a battlefield, either side, to its OWN Base -
    # a Unit's Base is its own (Core 141.1.a.1, 144.4.b), resolved per object as its controller's,
    # so an enemy unit goes to its controller's Base. "from a battlefield" restricts the target
    # (355.9.b, 355.10.b)
    return {"program_effects": [{"op": "move_board_object", "effect_id": "mv",
                                 "destination": {"kind": "base", "player_relation": "object_controller"},
                                 "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                            "location": "battlefield"}}],
            "ast": {"node": "instruction", "op": "move_board_object",
                    "params": {"target": {"kind": "unit", "location": "battlefield"}, "destination": "its_base"}}}


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


def _lower_deal_all_enemy_here(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                                 "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy",
                                                           "location_ref": {"kind": "program_source_current_battlefield"}}}}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "affected": {"kind": "unit", "controller_relation": "enemy",
                                                              "location_ref": {"kind": "program_source_current_battlefield"}}}}}


_HERE = {"kind": "program_source_current_battlefield"}


def _here_target():
    return {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
            "controller_relation": "enemy", "location_ref": dict(_HERE)}


def _lower_deal_enemy_unit_here(params):
    amount = int(params["amount"])
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount, "target": _here_target()}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "target": {"kind": "unit", "controller_relation": "enemy",
                                                            "location_ref": dict(_HERE)}}}}


def _lower_deal_split_among_enemy_units_here(params):
    """"Deal N damage split among any number of enemy units here." (Volibear - Furious) - Core
    355.14: each chosen Unit is a Target (355.14.a), chosen as the ability is finalized (355.14.b),
    at most N of them (355.14.c: the amount caps them, so the targets carry no max), each at the
    source's current Battlefield (359.3.f.2); how the N is divided is decided at resolution
    (355.14.e), a positive amount to each Target kept (355.14.f, 355.14.g, 355.14.h)."""
    amount = int(params["amount"])
    restrictions = {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy",
                    "location_ref": dict(_HERE)}
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": amount,
                                 "targets": {"decision_ref": "t", "min": 0, "restrictions": restrictions},
                                 "division_ref": "t-division"}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount": amount, "split": True, "targets": {"min": 0, "max": "amount",
                                                                            "restrictions": dict(restrictions)}}}}


def _lower_deal_my_might_to_enemy_unit_here(params):
    ref = {"kind": "program_source_current_might"}
    return {"program_effects": [{"op": "deal_damage", "effect_id": "dmg", "amount_ref": dict(ref), "target": _here_target()}],
            "ast": {"node": "instruction", "op": "deal_damage",
                    "params": {"amount_ref": dict(ref), "target": {"kind": "unit", "controller_relation": "enemy",
                                                                   "location_ref": dict(_HERE)}}}}


def _lower_stun_enemy_unit_here(params):
    return {"program_effects": [{"op": "stun", "effect_id": "st", "target": _here_target()}],
            "ast": {"node": "instruction", "op": "stun",
                    "params": {"target": {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(_HERE)}}}}


def _lower_give_enemy_unit_here_might(params):
    amount = int(params["amount"]) * (-1 if params["sign"] == "-" else 1)
    effect = {"op": "modify_might", "effect_id": "mm", "amount": amount, "duration": "this_turn",
              "source": "$chain_item", "target": _here_target()}
    if params.get("floor") is not None:
        effect["minimum"] = int(params["floor"])
    return {"program_effects": [effect],
            "ast": {"node": "instruction", "op": "modify_might",
                    "params": {"amount": amount, "duration": "this_turn", "minimum": effect.get("minimum"),
                               "target": {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(_HERE)}}}}


# --- 2026-09-27 package 6: a state a chosen object or a set must be in, bounded and criteria buffs,
# and the conditions "if there is a ready enemy unit here" / "if I am at a battlefield". Each is a
# literal row: the selector table is pinned by the signed binding specs, and none of these phrases
# is a selector alternative there.
_SELF = {"object_ref": "program_source"}


def _lower_buff_exhausted_friendly_unit(params):
    """"Buff an exhausted friendly unit." - one chosen friendly Unit that is Exhausted when it is
    chosen and when the buff is placed (Core 414.2, 426.1, 359.3.e.2)."""
    target = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly",
              "exhausted": True}
    return {"program_effects": [{"op": "buff", "effect_id": "bf", "target": dict(target)}],
            "ast": {"node": "instruction", "op": "buff", "params": {"target": {k: v for k, v in target.items()
                                                                              if k not in ("decision_ref",)}}}}


def _lower_ready_something_else_exhausted(params):
    """"Ready something else that's exhausted." - one chosen object of any type on the board or a Legend in
    its Legend Zone (GPT 2026-10-02: Core 107.4, 355.9.a.4), not the source, Exhausted when chosen and when
    readied (Core 415.1, 414.2)."""
    target = {"decision_ref": "t", "chosen_zone_class": "board", "include_legend_zone": True, "exhausted": True,
              "exclude_source_identity": "$source_identity"}
    return {"program_effects": [{"op": "ready", "effect_id": "rd", "target": dict(target)}],
            "ast": {"node": "instruction", "op": "ready", "params": {"target": {"exhausted": True, "other": True}}}}


def _lower_give_me_might_if_ready_enemy_here(params):
    """"Give me +2 [M] this turn if there is a ready enemy unit here." - the source's Might this turn,
    only if, as the instruction executes, an enemy Unit that is Ready stands at the Battlefield the
    source stands at (Core 383.2.a.1: an "if" not right after the trigger condition is the effect's;
    415.2; 359.3.f.2)."""
    amount = int(params["amount"]) * (-1 if params["sign"] == "-" else 1)
    condition = {"kind": "controls_units", "count": 1, "controller_relation": "enemy", "location": "here",
                 "exhausted": False}
    return {"program_effects": [{"op": "modify_might", "effect_id": "mm", "object_id": dict(_SELF), "amount": amount,
                                 "duration": "this_turn", "source": "$chain_item",
                                 "predicate": {"kind": "state_holds", "condition": dict(condition)}}],
            "ast": {"node": "instruction", "op": "modify_might",
                    "params": {"amount": amount, "duration": "this_turn", "object": "source"}, "if": dict(condition)}}


def _lower_buff_up_to_two_other_friendly_units(params):
    """"Buff up to two other friendly units." - one choice of zero to two friendly Units, the source
    not among them (Core 355.13, 426.1); each chosen one is buffed on its own (426.1.b-c)."""
    restrictions = {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly",
                    "exclude_source_identity": "$source_identity"}
    return {"program_effects": [{"op": "buff", "effect_id": "bf",
                                 "targets": {"decision_ref": "t", "min": 0, "max": 2, "restrictions": dict(restrictions)}}],
            "ast": {"node": "instruction", "op": "buff",
                    "params": {"targets": {"min": 0, "max": 2, "restrictions": {"kind": "unit", "controller_relation": "friendly",
                                                                               "other": True}}}}}


def _lower_buff_all_friendly_units(params):
    """"Buff all friendly units." - every friendly Unit on the board, found by criteria and not targeted
    (Core 355.10.d, 426.1); one that already has a Buff is not buffed again (426.1.b.1)."""
    criteria = {"kind": "unit", "controller_relation": "friendly", "location": "board"}
    return {"program_effects": [{"op": "buff", "effect_id": "bf", "affected": {"criteria": dict(criteria)}}],
            "ast": {"node": "instruction", "op": "buff", "params": {"affected": dict(criteria)}}}


def _lower_if_at_battlefield_buff_all_other_friendly_units_there(params):
    """"If I am at a battlefield, buff all other friendly units there." - only if the source stands at a
    Battlefield as the instruction executes; then every other friendly Unit at that Battlefield (Core
    359.3.f.2, 355.10.d, 426.1). The "if" is not right after a trigger condition, so it is the
    effect's (Core 383.2.a.1)."""
    criteria = {"kind": "unit", "controller_relation": "friendly", "location_ref": dict(_HERE),
                "exclude_source_identity": "$source_identity"}
    condition = {"kind": "at_a_battlefield"}
    return {"program_effects": [{"op": "buff", "effect_id": "bf", "affected": {"criteria": dict(criteria)},
                                 "predicate": {"kind": "state_holds", "condition": dict(condition)}}],
            "ast": {"node": "instruction", "op": "buff",
                    "params": {"affected": {"kind": "unit", "controller_relation": "friendly", "location_ref": dict(_HERE),
                                            "other": True}}, "if": dict(condition)}}


def _lower_kill_all_damaged_enemy_units_here(params):
    """"Kill all damaged enemy units here." - every enemy Unit at the source's current Battlefield
    with damage marked on it as the instruction executes (Core 428, 142, 355.10.d, 359.3.f.2)."""
    criteria = {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(_HERE), "damaged": True}
    return {"program_effects": [{"op": "kill", "effect_id": "kl", "affected": {"criteria": dict(criteria)}}],
            "ast": {"node": "instruction", "op": "kill", "params": {"affected": dict(criteria)}}}


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


def _lower_opponents_cant_play_cards(params):
    """"Opponents can't play cards this turn." - a turn effect of its controller's: each of their
    opponents is refused a card play for the rest of the turn (Core 054.1, 052, 317.2.c)."""
    return {"program_effects": [{"op": "grant_turn_effect", "effect_id": "grant",
                                 "turn_effect_kind": "cards_play_prohibited", "value": "opponents",
                                 "controller": "$controller", "source": "$chain_item"}],
            "ast": {"node": "instruction", "op": "grant_turn_effect",
                    "params": {"turn_effect_kind": "cards_play_prohibited", "value": "opponents"}}}
def _lower_temporary_unit_at_battlefield_or_gear(params):
    """"Give a unit at a battlefield or a gear [Temporary]." (Fading Memories): one chosen object fitting
    either alternative (effect_ir any_of), granted Temporary with no duration (Core 816.1.a, 801.3.a.3)."""
    target = {"decision_ref": "t", "chosen_zone_class": "board",
              "any_of": [{"kind": "unit", "location": "battlefield"}, {"kind": "gear"}]}
    return {"program_effects": [{"op": "grant_keyword", "effect_id": "kw", "keyword": "temporary", "duration": "permanent",
                                 "source": "$chain_item", "target": target}],
            "ast": {"node": "instruction", "op": "grant_keyword",
                    "params": {"keyword": "temporary", "duration": "permanent", "target": dict(target)}}}


def _lower_next_spell_discount(params):
    """"The next spell you play this turn costs [N] less." (Raging Firebrand) - a turn effect the
    play transaction reads as a discount on the next spell and spends (Core 391, 356.4)."""
    amount = int(params["amount"])
    return {"program_effects": [{"op": "grant_turn_effect", "effect_id": "grant",
                                 "turn_effect_kind": "next_spell_cost_reduction", "value": amount,
                                 "controller": "$controller", "source": "$chain_item"}],
            "ast": {"node": "instruction", "op": "grant_turn_effect",
                    "params": {"turn_effect_kind": "next_spell_cost_reduction", "value": amount}}}


def _lower_next_unit_enters_ready(params):
    """"The next unit you play this turn enters ready." (Sun Disc) - bound to that one play as an
    entry replacement, then spent (Core 391, 369.3)."""
    return {"program_effects": [{"op": "grant_turn_effect", "effect_id": "grant",
                                 "turn_effect_kind": "entry_state_for_next_played_unit", "value": "ready",
                                 "controller": "$controller", "source": "$chain_item"}],
            "ast": {"node": "instruction", "op": "grant_turn_effect",
                    "params": {"turn_effect_kind": "entry_state_for_next_played_unit", "value": "ready"}}}


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


def _lower_self_cost_reduction_fixed(params):
    """"I cost N less." - the card's own text, a fixed Energy amount, no
    condition of its own. It is the ability a Legion gates (Noxus Hopeful)."""
    amount = int(params["amount"])
    return {"object_fields": {"printed_cost_modifications": [{
                "modification_id": "own-text", "kind": "energy_reduction", "amount": amount}]},
            "ast": {"node": "self_cost_reduction", "amount": amount}}


def _lower_might_by_points(params):
    """"My Might is increased by your points." - a passive increase of the card's own
    Might by its controller's points, read each time Might is computed (477.3.b)."""
    return {"object_fields": {"dynamic_might": [{"modifier_id": "own-text", "amount": 1, "per": {"kind": "controller_points"}}]},
            "ast": {"node": "dynamic_might", "per": "controller_points", "amount": 1}}


def _lower_self_cost_reduction_per_trash(params):
    """"I cost N less for each card in your trash." - the card's own text, a fixed
    Energy amount per card in its controller's trash (356.4; 356.6 keeps it at 0)."""
    amount = int(params["amount"])
    return {"object_fields": {"printed_cost_modifications": [{
                "modification_id": "own-text", "kind": "energy_reduction", "amount": amount,
                "per_each": {"kind": "zone_count_at_least", "zone": "trash"}}]},
            "ast": {"node": "self_cost_reduction", "amount": amount, "per_each": {"zone": "trash"}}}


def _lower_self_cost_reduction_highest_might(params):
    """"This spell's Energy cost is reduced by the highest Might among units you control." -
    1 Energy per point of the highest Might among the Units its player controls on the board,
    read as the cost is determined (356.4; 356.6 keeps it at 0 or above)."""
    return {"object_fields": {"printed_cost_modifications": [{
                "modification_id": "own-text", "kind": "energy_reduction", "amount": 1,
                "per_each": {"kind": "highest_might_among_units_you_control"}}]},
            "ast": {"node": "self_cost_reduction", "amount": 1, "per_each": {"kind": "highest_might_among_units_you_control"}}}


def _lower_self_cost_reduction_unit_died(params):
    """"If an enemy unit has died this turn, this costs N less." - the card's own text, a fixed
    Energy amount, gated by a Unit of that side having died this turn (356.4, 428.1)."""
    amount = int(params["amount"])
    condition = {"kind": "unit_died_this_turn", "controller_relation": params["relation"]}
    return {"object_fields": {"printed_cost_modifications": [{
                "modification_id": "own-text", "kind": "energy_reduction", "amount": amount,
                "condition": dict(condition)}]},
            "ast": {"node": "self_cost_reduction", "amount": amount, "condition": dict(condition)}}


def _lower_empty(params):
    return {"ast": {"node": "empty"}}


# Composable productions receive the resolved slots as well as the raw groups.
# Core 135.2.e.7 / 808.1.d: `[keyword][>] ability` — the keyword names the
# trigger condition, the inner clause is the effect. Only the keywords the
# engine implements as a trigger get a program; the rest are known_unsupported.
KEYWORDED_TRIGGERS = {"deathknell": ("death_triggers", "deathknell")}
# Core 727.1 / 812.1.b.1: a Dependent Keyword is a condition on the ability after it.
# Legion's condition is a condition.v1 leaf; the ability it gates must be one of the
# two forms the engine reads that condition on. Anything else is known_unsupported.
DEPENDENT_KEYWORDS = {"legion": {"kind": "another_card_finalized_this_turn"}}


def _lower_dependent_keyword(name: str, inner: dict[str, Any]) -> dict[str, Any] | None:
    condition = DEPENDENT_KEYWORDS[name]
    passive = copy.deepcopy((inner.get("passive") or {}).get("object_fields") or {})
    if inner.get("production_id") == "when_you_play_me" and set(passive) == {"play_triggers"}:
        for trigger in passive["play_triggers"]:
            trigger["condition"] = dict(condition)
        return {"object_fields": passive, "program_effects": inner.get("program_effects", []),
                "ast": {"node": "dependent_keyword", "keyword": name, "condition": dict(condition), "then": inner["ast"]}}
    if inner.get("production_id") == "self_cost_reduction_fixed" and set(passive) == {"printed_cost_modifications"}:
        for modification in passive["printed_cost_modifications"]:
            modification["condition"] = dict(condition)
        return {"object_fields": passive, "program_effects": [],
                "ast": {"node": "dependent_keyword", "keyword": name, "condition": dict(condition), "then": inner["ast"]}}
    return None


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


def _lower_single_target_op(op: str, effect_id: str, capability: str, extra: dict[str, Any] | None = None):
    """Ready and Buff are the same shape: one op, one chosen object, no
    parameters of their own. The selector carries every difference. `extra`
    is for an op that needs one more field of its own - a Move needs somewhere
    to go, and where is the controller's choice at resolution."""
    def lower(params, slots):
        effect: dict[str, Any] = {"op": op, "effect_id": effect_id, **copy.deepcopy(extra or {})}
        effect.update(_selector_fields(slots["selector"]))
        return {"program_effects": [effect],
                "ast": {"node": "instruction", "op": op,
                        "params": {"selector": slots["selector"]["alternative"]}}}
    return lower


COMPOSABLE = {
    "while_a_friendly_unit_defends_alone_it_gets_might": _lower_defends_alone_aura,
    "stun_selector": _lower_single_target_op("stun", "st", "stun"),
    "move_selector": _lower_single_target_op("move_board_object", "mv", "move_board_object",
                                            extra={"destination": {"decision_ref": "dest"}}),
    # 2026-09-25 (Yasuo - Unforgiven): the same chosen Move, narrowed to the unit's own Base when
    # it is at a Battlefield and to a Battlefield when it is in its Base (effect_ir restriction)
    "move_selector_to_or_from_its_base": _lower_single_target_op(
        "move_board_object", "mv", "move_board_object",
        extra={"destination": {"decision_ref": "dest", "restriction": "to_or_from_own_base"}}),
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


# 2026-09-27 package 6: a card's printed NON-RESOURCE additional cost for its own play (Core
# 356.2.a.1, 356.2.b.1, 356.7). The words of the cost are a closed table; the engine resolves what
# pays it (which unit, which card) as the card is played (play_transaction.printed_cost_components).
PRINTED_COST_WORDS = {
    "kill a friendly unit": {"kind": "kill", "amount": 1},
    "discard": {"kind": "discard"},             # "discard N": the amount is the production's own
    "spend a buff": {"kind": "spend_buff", "amount": 1},
    "kill any number of friendly units": {"kind": "kill", "any_number": True},
    "spend any number of buffs": {"kind": "spend_buff", "any_number": True},
}


def _lower_printed_cost(mandatory: bool):
    def lower(params):
        words = params["cost"]
        payment = copy.deepcopy(PRINTED_COST_WORDS["discard" if words.startswith("discard ") else words])
        if payment["kind"] == "discard":
            payment["amount"] = int(params["amount"])
        return {
            "object_fields": {"printed_additional_costs": [
                {"cost_offer_id": "$clause_id", "mandatory": mandatory, "payment": payment}]},
            "ast": {"node": "passive", "kind": "printed_additional_cost",
                    "params": {"mandatory": mandatory, "payment": payment}},
        }
    return lower


# "If you do, ..." / "Otherwise, ..." right after a printed OPTIONAL additional cost reads the
# decision to pay it (Core 356.4.f.1, 356.2.b.1's own example) - a cost receipt, not whether an
# instruction was performed (Core 205 is about a payment that is no cost). What it links to is a
# cost modification (applied as the card is played, 356.1 / 356.4) or an instruction (a cost_paid /
# cost_not_paid predicate). A per-each discount counts what an "any number" offer paid.
OFFER_LINK_PREFIXES = {"if you do, ": "cost_paid", "otherwise, ": "cost_not_paid"}
OFFER_LINKED_MODIFICATIONS = (
    (re.compile(r"^reduce my cost by \[e(?P<amount>\d+)\]$"), "energy_reduction"),
    (re.compile(r"^ignore this spell's cost$"), "ignore_base_cost"),
)
OFFER_PER_PAID = re.compile(r"^reduce my cost by \[rune:(?P<domain>[a-z]+)\] for each (?P<what>killed this way|buff you spend)$")
OFFER_PER_PAID_KIND = {"killed this way": "kill", "buff you spend": "spend_buff"}


def _printed_offer_of(previous: dict[str, Any] | None, *, linked_too: bool = False) -> dict[str, Any] | None:
    """The one OPTIONAL printed non-resource offer the previous clause declared ({cost_offer_id,
    payment}), or - for "Otherwise" (linked_too) - the offer the previous clause was itself linked
    to. None when there is none, or more than one."""
    if not isinstance(previous, dict) or previous.get("unsupported"):
        return None
    if linked_too and isinstance(previous.get("offer_link"), dict):
        return previous["offer_link"]
    offers = [o for o in (((previous.get("passive") or {}).get("object_fields", {}) or {})
                          .get("printed_additional_costs") or []) if not o.get("mandatory")]
    return {"cost_offer_id": offers[0]["cost_offer_id"], "payment": offers[0]["payment"]} if len(offers) == 1 else None


def _offer_linked(text: str, normalized: str, previous: dict[str, Any] | None,
                  grammar: dict[str, Any]) -> dict[str, Any] | None:
    """A clause that reads a printed optional offer the previous clause declared, or None (then the
    clause is read as it always was)."""
    per_paid = OFFER_PER_PAID.match(normalized)
    if per_paid:
        offer = _printed_offer_of(previous)
        wanted = OFFER_PER_PAID_KIND[per_paid.group("what")]
        if offer is None or offer["payment"].get("any_number") is not True or offer["payment"]["kind"] != wanted:
            return {"production_id": "offer_linked_modification", "unsupported": True, "reason_code": "cost_offer_not_declared",
                    "text": text, "normalized": normalized,
                    "reason": f"'for each {per_paid.group('what')}' counts an 'any number' offer of {wanted} the clause "
                              "before did not declare"}
        link = {"cost_offer_id": offer["cost_offer_id"], "kind": "power_reduction_per_paid",
                "domain": per_paid.group("domain"), "amount": 1}
        return {"production_id": "offer_linked_modification", "unsupported": False, "text": text, "normalized": normalized,
                "params": {}, "slots": {}, "cost_offer_id": offer["cost_offer_id"], "offer_link": offer,
                "rule_locators": ["Core 356.2.b.1", "Core 356.4", "Core 356.6"],
                "required_capability": ["evaluated_cost_modifications", "self_costs"],
                "ast": {"node": "offer_linked", "reads": offer["cost_offer_id"], "modification": link},
                "passive": {"object_fields": {"offer_linked_cost_modifications": [link]}}}
    for prefix, link_kind in OFFER_LINK_PREFIXES.items():
        if not normalized.startswith(prefix):
            continue
        offer = _printed_offer_of(previous, linked_too=link_kind == "cost_not_paid")
        if offer is None:
            return None     # not after a printed offer: the prefix keeps its ordinary reading
        rest = normalized[len(prefix):]
        for pattern, kind in OFFER_LINKED_MODIFICATIONS:
            found = pattern.match(rest)
            if not found:
                continue
            if link_kind != "cost_paid" or offer["payment"].get("any_number") is True:
                return {"production_id": "offer_linked_modification", "unsupported": True,
                        "reason_code": "cost_offer_not_declared", "text": text, "normalized": normalized,
                        "reason": "a cost modification switched on by paying names one optional offer of one payment"}
            link = {"cost_offer_id": offer["cost_offer_id"], "kind": kind,
                    **({"amount": int(found.group("amount"))} if kind == "energy_reduction" else {})}
            return {"production_id": "offer_linked_modification", "unsupported": False, "text": text,
                    "normalized": normalized, "params": {}, "slots": {}, "link": link_kind,
                    "cost_offer_id": offer["cost_offer_id"], "offer_link": offer,
                    "rule_locators": ["Core 356.2.b.1", "Core 356.4.f.1"]
                                     + (["Core 356.4"] if kind == "energy_reduction" else ["Core 356.1.b", "Core 356.1.b.1"]),
                    "required_capability": ["evaluated_cost_modifications", "self_costs"],
                    "ast": {"node": "offer_linked", "reads": offer["cost_offer_id"], "modification": link},
                    "passive": {"object_fields": {"offer_linked_cost_modifications": [link]}}}
        inner = compile_clause(rest, grammar)
        if inner.get("unsupported"):
            return {"production_id": "offer_linked_prefix", "unsupported": True,
                    "reason_code": inner.get("reason_code", "clause_unparsed"), "text": text,
                    "reason": f"the linked instruction did not parse: {rest!r}"}
        effects = copy.deepcopy(inner.get("program_effects", []))
        predicate = {"kind": link_kind, "cost_id": f"self_offer:{offer['cost_offer_id']}", "cost_offer_id": offer["cost_offer_id"]}
        for effect in effects:
            effect.setdefault("predicate", predicate)
        return {"production_id": "offer_linked_prefix", "unsupported": False, "text": text, "normalized": normalized,
                "params": {}, "slots": {}, "link": link_kind, "cost_offer_id": offer["cost_offer_id"], "offer_link": offer,
                "rule_locators": ["Core 356.4.f.1", "Core 356.2.b.1"] + inner["rule_locators"],
                "required_capability": sorted(set(inner["required_capability"]) | {"cost_predicates"}),
                "ast": {"node": "cost_linked", "link": link_kind, "reads": offer["cost_offer_id"], "then": inner["ast"]},
                "program_effects": effects}
    return None


def _lower_granted_tag_discount(params):
    """2026-09-27 package 6: "Your [Tag]s' Energy costs are reduced by [N], to a minimum of [M]." - a
    permanent's printed discount on its controller's cards of that tag while it is on the board
    (Core 356.4.a, 356.4.b; the minimum is this discount's own, 356.4.e). The tag is named as
    printed: the plural's stem, capitalised ("dragons'" is the tag Dragon)."""
    tag = params["tag"][:1].upper() + params["tag"][1:]
    entry = {"discount_id": "$clause_id", "applies_to": "energy", "amount": int(params["amount"]),
             "minimum": int(params["minimum"]), "card_tag": tag}
    return {"object_fields": {"granted_cost_discounts": [entry]},
            "ast": {"node": "passive", "kind": "granted_cost_discount", "params": {k: v for k, v in entry.items() if k != "discount_id"}}}


def _lower_spell_discount_at_battlefield(params):
    """2026-09-27 package 6: "While I'm at a battlefield, the Energy costs for spells you play is reduced by [N], to a
    minimum of [M]." - a conditional passive (Core 364.3.a) of a permanent: while it is at a Battlefield, each spell
    its controller plays costs N Energy less, never below M by this discount (356.4.a, 356.4.e)."""
    entry = {"discount_id": "$clause_id", "applies_to": "energy", "amount": int(params["amount"]),
             "minimum": int(params["minimum"]), "card_kind": "spell", "source_at": "battlefield"}
    return {"object_fields": {"granted_cost_discounts": [entry]},
            "ast": {"node": "passive", "kind": "granted_cost_discount", "params": {k: v for k, v in entry.items() if k != "discount_id"}}}


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


def _lower_counter_within_cost_limit(params):
    """The clause states the numbers; a card mapping states which cost they are
    compared against and on whose authority. The two are deliberately separate:
    the numbers are printed on the card and the reading is not."""
    return {
        "program_effects": [{
            "op": "counter", "effect_id": "ctr",
            "target": {"decision_ref": "t", "chosen_zone_class": "non_board", "location": "chain",
                       "max_cost": {"energy": int(params["energy"]), "power": 1}},
        }],
        "needs_mapping": "cost_comparison",
        "ast": {"node": "instruction", "op": "counter",
                "params": {"max_energy": int(params["energy"]), "max_power": 1}},
    }


# Sabotage's three clauses share one decision: the opponent chosen by the
# first. The later two name it rather than choosing again - "they" is a
# referent, and re-choosing could land on a different player.
OPPONENT_REF = "chosen-opponent"


def _lower_choose_an_opponent(params):
    return {
        "program_effects": [{"op": "choose_player", "effect_id": "opp", "decision_ref": OPPONENT_REF,
                             "choice": {"selection_kind": "single", "from": "players",
                                        "players": "opponents", "count": {"one": True}}}],
        "declares_player_ref": OPPONENT_REF,
        "ast": {"node": "instruction", "op": "choose_player", "params": {"from": "opponents"}},
    }


def _lower_they_reveal_their_hand(params):
    return {
        "program_effects": [{"op": "reveal", "effect_id": "rv", "from": "hand",
                             "player": {"decision_ref": OPPONENT_REF}}],
        "needs_player_ref": OPPONENT_REF,
        "declares_reveal": "rv",
        "ast": {"node": "instruction", "op": "reveal", "params": {"from": "hand", "player": "$referent_player"}},
    }


def _lower_recycle_a_non_unit_from_the_reveal(params):
    return {
        "program_effects": [{"op": "recycle", "effect_id": "rc", "player": "$controller",
                             "decision_ref": "sabotage-card", "order_ref": "sabotage-order",
                             "choice": {"selection_kind": "single", "from": "revealed",
                                        "by": "controller", "count": {"one": True},
                                        "criteria": {"excluded_kinds": ["unit"]}}}],
        "needs_reveal": True,
        "ast": {"node": "instruction", "op": "recycle",
                "params": {"from": "revealed", "excluded_kinds": ["unit"]}},
    }


def _lower_occupied_enemy_permission(params):
    """Core 355.2.b: the card prints one more place it may enter. The engine
    decides what that place is; the clause only names the permission."""
    return {
        "object_fields": {"play_permissions": ["occupied_enemy_battlefield"]},
        "ast": {"node": "passive", "kind": "play_permission",
                "params": {"permission": "occupied_enemy_battlefield"}},
    }


def _lower_open_permission(params):
    """Core 355.2.b, 170.11.c: the card prints that it may enter an open Battlefield."""
    return {
        "object_fields": {"play_permissions": ["open_battlefield"]},
        "ast": {"node": "passive", "kind": "play_permission", "params": {"permission": "open_battlefield"}},
    }


def _lower_granted_open_permission(params):
    """Core 355.2.b, 170.11.c: while this permanent is on the board, the unit cards its side plays
    may enter an open Battlefield (Miss Fortune - Buccaneer)."""
    grant = {"permission": "open_battlefield", "kind": "unit", "controller_relation": "friendly"}
    return {
        "object_fields": {"granted_play_permissions": [dict(grant)]},
        "ast": {"node": "passive", "kind": "granted_play_permission", "params": dict(grant)},
    }


def _lower_enters_exhausted(params):
    """Core 369.3: a printed replacement on how this permanent enters - exhausted, where a Gear
    would enter ready (359.2.d). resolution_bridge.entry_state_for applies it at entry."""
    return {
        "object_fields": {"entry_replacements": [{"mode": "entry_state", "value": "exhausted"}]},
        "ast": {"node": "passive", "kind": "entry_replacement", "params": {"entry_state": "exhausted"}},
    }


AURA_HERE = {"kind": "unit", "controller_relation": "friendly", "exclude_source": True, "at_source_battlefield": True}


def _lower_aura_here(params):
    """Core 365.1, 476-479: a printed aura over the other friendly Units at the source's
    Battlefield, read by effect_ir.printed_aura_effects while the source is on the board."""
    amount = int(params["amount"])
    return {"object_fields": {"static_auras": [{"aura_id": "here", "amount": amount, "criteria": dict(AURA_HERE)}]},
            "ast": {"node": "passive", "kind": "static_aura", "params": {"amount": amount, "criteria": dict(AURA_HERE)}}}


def _lower_buffed_aura_here(params):
    """The same aura, only over Units with a Buff counter (426.1.b)."""
    amount = int(params["amount"])
    criteria = {**AURA_HERE, "buffed": True}
    return {"object_fields": {"static_auras": [{"aura_id": "buffed-here", "amount": amount, "criteria": criteria}]},
            "ast": {"node": "passive", "kind": "static_aura", "params": {"amount": amount, "criteria": dict(criteria)}}}


TOKEN_COUNTS = {"a": 1, "two": 2, "three": 3, "four": 4}


def _lower_recruit_tokens_here(params):
    """Package 6 (2026-09-27): "Play two 1 [M] Recruit unit tokens here." - one play_token per token, each
    a catalogued Recruit (Core 187.1) with the printed Might, each placed at the program source's current
    Battlefield, read as it executes (location_ref, Core 359.3.f.2) - the signed eff_294 shape, repeated.
    Lowered so a dependent keyword over it ("[Legion][>] When you play me, ...") reads (812.1.b)."""
    count, might = TOKEN_COUNTS[params["count"]], int(params["might"])
    effects = [{"op": "play_token", "effect_id": f"tok{i + 1}" if count > 1 else "tok", "owner": "$controller",
                "controller": "$controller", "token_kind": "unit", "base_might": might, "token_id": "recruit",
                "object_id_ref": {"kind": "fresh"},
                "destination": {"kind": "battlefield", "location_ref": {"kind": "program_source_current_battlefield"}}}
               for i in range(count)]
    # package 7: the Recruit card's printed tag rides on each instruction, from the reviewed catalogue
    from token_catalog import carry_tags
    return {"program_effects": carry_tags(effects),
            "ast": {"node": "instruction", "op": "play_token", "params": {"count": count, "might": might,
                                                                          "token_id": "recruit", "where": "here"}}}


def _lower_other_friendly_units_enter_ready(params):
    """Package 6 (2026-09-27): "Other friendly units enter ready." - a replacement the permanent
    applies, while it is on the board (365.1), to the entry of the other Units its side plays or
    makes (369.3); effect_ir.granted_entry_states reads it at entry and for a token."""
    from effect_ir import GRANTED_ENTRY_CRITERIA
    grant = {"replacement_id": "others-enter-ready", "value": "ready", "criteria": dict(GRANTED_ENTRY_CRITERIA)}
    return {"object_fields": {"granted_entry_states": [grant]},
            "ast": {"node": "passive", "kind": "granted_entry_state",
                    "params": {"value": "ready", "criteria": dict(GRANTED_ENTRY_CRITERIA)}}}


STUNNED_ENEMY_HERE = {"kind": "unit", "controller_relation": "enemy", "at_source_battlefield": True, "stunned": True}


def _lower_stunned_enemy_aura_here(params):
    """Package 6 (2026-09-27): "Stunned enemy units here have -N [M], to a minimum of M [M]." - a
    printed decrease over the enemy Units at the source's Battlefield that are Stunned right now
    (Core 423.1.a), limited to its floor; a passive's limit is applied fresh, never snapshotted
    (477.3.b). effect_ir.printed_aura_effects reads it while the source is on the board (365.1)."""
    amount, floor = -int(params["amount"]), int(params["floor"])
    aura = {"aura_id": "stunned-enemy-here", "amount": amount, "minimum": floor, "criteria": dict(STUNNED_ENEMY_HERE)}
    return {"object_fields": {"static_auras": [aura]},
            "ast": {"node": "passive", "kind": "static_aura",
                    "params": {"amount": amount, "minimum": floor, "criteria": dict(STUNNED_ENEMY_HERE)}}}


def _lower_battlefield_aura(params):
    """Core 365.1, 190.6: a Battlefield's printed aura over every Unit at it (effect_ir
    printed_aura_effects reads a Battlefield's static_auras)."""
    amount = int(params["amount"])
    return {"battlefield_fields": {"static_auras": [{"aura_id": "here", "amount": amount, "criteria": {"kind": "unit"}}]},
            "ast": {"node": "passive", "kind": "static_aura", "params": {"amount": amount, "criteria": {"kind": "unit"},
                                                                         "on": "battlefield"}}}


# 2026-09-27: printed keyword auras (Core 477.2, 477.2.b) and a card's own conditional
# keywords / Might (364.3.a). A keyword granted this
# way is a keyword_grant in the Ability layer, read by whatever uses the keyword off the computed
# characteristics (effect_ir.STATIC_AURA_KEYWORDS).
AURA_OTHER_FRIENDLY = {"kind": "unit", "controller_relation": "friendly", "exclude_source": True}


def _lower_keyword_aura(on, criteria):
    def lower(params):
        keyword = params["keyword"]
        aura = {"aura_id": f"{'here' if criteria.get('at_source_battlefield') or on == 'battlefield' else 'all'}-{keyword}",
                "keyword": keyword, "criteria": dict(criteria)}
        field = "battlefield_fields" if on == "battlefield" else "object_fields"
        return {field: {"static_auras": [aura]},
                "ast": {"node": "passive", "kind": "static_keyword_aura",
                        "params": {"keyword": keyword, "criteria": dict(criteria), **({"on": "battlefield"} if on == "battlefield" else {})}}}
    return lower


KEYWORD_LIST_ITEM = re.compile(r"\[([a-z]+)\]")


def _listed_keywords(text: str) -> list[str] | None:
    """"[a]", "[a] and [b]", "[a], [b], and [c]" - bare keywords, each once, each one the engine
    reads off the computed characteristics; None otherwise."""
    from effect_ir import STATIC_AURA_KEYWORDS
    found = KEYWORD_LIST_ITEM.findall(text)
    if not found or len(found) != len(set(found)) or any(k not in STATIC_AURA_KEYWORDS for k in found):
        return None
    return found


def _lower_conditional_keywords(condition):
    def lower(params):
        keywords = _listed_keywords(params["keywords"])
        if keywords is None:
            return {"ast": {"node": "conditional_keywords", "keywords": params["keywords"], "condition": dict(condition)},
                    "known_unsupported": "keyword_not_implemented"}
        return {"object_fields": {"conditional_keywords": [
                    {"modifier_id": f"own-text-{keyword}", "keyword": keyword, "condition": dict(condition)} for keyword in keywords]},
                "ast": {"node": "conditional_keywords", "keywords": keywords, "condition": dict(condition)}}
    return lower


def _lower_while_buffed_might(params):
    amount = int(params["amount"])
    return {"passive": {"object_fields": {"conditional_might": [
                {"modifier_id": "clause", "amount": amount, "condition": {"kind": "is_buffed"}}]}},
            "ast": {"node": "conditional_might", "amount": amount, "condition": {"kind": "is_buffed"}}}


def _lower_might_per(kind, fixed_amount=None):
    def lower(params):
        amount = int(params["amount"]) if fixed_amount is None else fixed_amount
        return {"object_fields": {"dynamic_might": [{"modifier_id": "own-text", "amount": amount, "per": {"kind": kind}}]},
                "ast": {"node": "dynamic_might", "per": kind, "amount": amount}}
    return lower


def _lower_conditional_enter_ready(condition_of):
    """"If <condition>, I enter ready." - a conditional replacement of the card's own entry state
    (364.3.a, 369.3), its condition read as it enters."""
    def lower(params):
        condition = condition_of(params)
        return {"object_fields": {"entry_replacements": [
                    {"replacement_id": "own-text", "mode": "entry_state", "value": "ready", "condition": condition}]},
                "ast": {"node": "passive", "kind": "conditional_entry", "params": {"value": "ready", "condition": dict(condition)}}}
    return lower
def _lower_battlefield_bonus_damage(params):
    """Core 713-715 (package 5, 2026-09-27): a Battlefield's printed Bonus Damage to the
    Units at it. effect_ir.bonus_damage reads a `location` scope on the affected Unit's current
    Battlefield and ignores whose spell or ability deals; the entry's controller is only the
    state's bookkeeping (a source-backed entry names one)."""
    amount = int(params["amount"])
    return {"state_lists": {"damage_modifiers": [{
                "modifier_id": "$clause_id", "source_object": "$source_object", "controller": "$controller",
                "amount": amount, "scope": {"kind": "location", "battlefield": "$source_object"}}]},
            "ast": {"node": "passive", "kind": "bonus_damage",
                    "params": {"amount": amount, "scope": "location", "on": "battlefield"}}}


def _lower_additional_facedown_card(params):
    """Core 107.3.b, 107.3.b.1 (package 5, 2026-09-27): this Battlefield's Facedown Zone holds
    one card more than 107.3.b's one. hidden.hide_card refuses a hide into a full zone
    (facedown_zone_full); the zone still starts empty."""
    return {"battlefield_fields": {"facedown": {"capacity": 2, "cards": []}},
            "ast": {"node": "passive", "kind": "facedown_capacity",
                    "params": {"base": 1, "additional": 1, "on": "battlefield"}}}


def _lower_move_restriction(params):
    """Core 359.3.e.6: printed on the Battlefield, and read by both Move paths
    - the Standard Move it forbids outright, and the effect-induced Move whose
    instruction it makes impossible at resolution."""
    return {
        "battlefield_fields": {"move_restrictions": [
            {"source_location": "here", "destination_kind": "base", "affected_kind": "unit"}]},
        "ast": {"node": "passive", "kind": "move_restriction",
                "params": {"source_location": "here", "destination_kind": "base", "affected_kind": "unit"}},
    }


LOWERINGS = {
    "units_cant_move_from_here_to_base": _lower_move_restriction,
    "you_may_play_me_to_an_occupied_enemy_battlefield": _lower_occupied_enemy_permission,
    "you_may_play_me_to_an_open_battlefield": _lower_open_permission,
    "friendly_units_may_be_played_to_open_battlefields": _lower_granted_open_permission,
    "this_enters_exhausted": _lower_enters_exhausted,
    "other_friendly_units_have_might_here": _lower_aura_here,
    "other_buffed_friendly_units_at_my_battlefield_have_might": _lower_buffed_aura_here,
    "units_here_have_might": _lower_battlefield_aura,
    # 2026-09-27 package 6 (Leona - Zealot)
    "stunned_enemy_units_here_have_might_to_a_minimum": _lower_stunned_enemy_aura_here,
    # 2026-09-27 package 6 (Magma Wurm)
    "other_friendly_units_enter_ready": _lower_other_friendly_units_enter_ready,
    # 2026-09-27 package 6 (Vanguard Captain)
    "play_n_might_recruit_unit_tokens_here": _lower_recruit_tokens_here,
    # 2026-09-27: keyword auras, conditional keywords and Might, Might per count
    "units_here_have_keyword": _lower_keyword_aura("battlefield", {"kind": "unit"}),
    "other_friendly_units_here_have_keyword": _lower_keyword_aura("object", AURA_HERE),
    "other_friendly_units_have_keyword": _lower_keyword_aura("object", AURA_OTHER_FRIENDLY),
    "while_im_buffed_i_have_keywords": _lower_conditional_keywords({"kind": "is_buffed"}),
    "if_you_discarded_a_card_this_turn_i_have_keywords": _lower_conditional_keywords(
        {"kind": "cards_discarded_this_turn_at_least", "count": 1}),
    "while_im_mighty_i_have_keywords": _lower_conditional_keywords({"kind": "might_at_least", "count": 5}),
    "while_im_buffed_i_have_an_additional_might": _lower_while_buffed_might,
    "i_get_might_for_each_buffed_friendly_unit_at_my_battlefield": _lower_might_per("buffed_friendly_units_at_source_battlefield"),
    "my_might_is_increased_by_the_number_of_cards_in_your_trash": _lower_might_per("controller_trash_count", 1),
    "if_an_opponents_score_is_within_n_i_enter_ready": _lower_conditional_enter_ready(
        lambda params: {"kind": "score_within_of_victory", "count": int(params["within"])}),
    "if_an_opponent_controls_a_battlefield_i_enter_ready": _lower_conditional_enter_ready(
        lambda params: {"kind": "controls_a_battlefield", "controller_relation": "enemy"}),
    "spells_and_abilities_deal_n_bonus_damage_to_units_here": _lower_battlefield_bonus_damage,
    "you_may_hide_an_additional_card_here": _lower_additional_facedown_card,
    "choose_an_opponent": _lower_choose_an_opponent,
    "they_reveal_their_hand": _lower_they_reveal_their_hand,
    "choose_a_non_unit_card_from_it_and_recycle_that_card": _lower_recycle_a_non_unit_from_the_reveal,
    "counter_a_spell_within_a_cost_limit": _lower_counter_within_cost_limit,
    "if_a_friendly_unit_would_die_kill_this_instead": _lower_death_replacement,
    "you_may_pay_own_domain_power_as_additional_cost_to_play_me": _lower_card_self_offer,
    # 2026-09-27 package 6: printed non-resource additional costs (Core 356.2.a.1, 356.2.b.1, 356.7)
    "as_an_additional_cost_to_play_me_kill_a_friendly_unit": _lower_printed_cost(True),
    "as_you_play_me_you_may_pay_a_cost_as_an_additional_cost": _lower_printed_cost(False),
    "your_tags_energy_costs_are_reduced_to_a_minimum": _lower_granted_tag_discount,
    "while_im_at_a_battlefield_spells_you_play_cost_less": _lower_spell_discount_at_battlefield,
    "play_timing_keyword": _lower_play_timing,
    "draw_n": _lower_draw,
    "you_win_the_game": _lower_win_game,
    "i_can_have_any_number_of_buffs": _lower_any_number_of_buffs,
    "i_must_be_assigned_combat_damage_last": _lower_assigned_combat_damage_last,
    "deal_damage_equal_to_my_might_to_a_unit_at_a_battlefield": _lower_deal_my_might_to_unit_at_battlefield,
    "banish_a_friendly_unit_then_its_owner_plays_it_to_their_base_ignoring_its_cost": _lower_banish_then_owner_plays,
    "choose_a_friendly_unit_this_turn_increase_its_might_to_the_might_of_another_friendly_unit":
        _lower_raise_might_to_match,
    "choose_a_friendly_unit_the_next_time_it_would_die_this_turn_heal_exhaust_and_recall_it_instead":
        _lower_next_death_heal_exhaust_recall,
    "if_i_have_moved_twice_this_turn_i_dont_take_damage": _lower_no_damage_after_two_moves,
    "draw_n_for_each_of_your_mighty_units": _lower_draw_per_mighty_unit,
    "discard_n": _lower_discard,
    "draw_n_if_you_have_one_or_fewer_cards_in_your_hand": _lower_draw_if_few_in_hand,
    "deal_n_to_a_unit_at_a_battlefield": _lower_deal_unit_at_battlefield,
    "move_a_friendly_unit_at_a_battlefield_to_its_base": _lower_move_friendly_at_battlefield_to_its_base,
    "move_a_unit_from_a_battlefield_to_its_base": _lower_move_unit_from_battlefield_to_its_base,
    "deal_n_to_all_enemy_units_at_a_battlefield": _lower_deal_all_enemy_at_battlefield,
    "deal_n_to_all_enemy_units_here": _lower_deal_all_enemy_here,
    "deal_n_to_an_enemy_unit_here": _lower_deal_enemy_unit_here,
    "deal_n_damage_split_among_any_number_of_enemy_units_here": _lower_deal_split_among_enemy_units_here,
    "stun_an_enemy_unit_here": _lower_stun_enemy_unit_here,
    "deal_damage_equal_to_my_might_to_an_enemy_unit_here": _lower_deal_my_might_to_enemy_unit_here,
    "give_an_enemy_unit_here_might_this_turn": _lower_give_enemy_unit_here_might,
    "deal_n_to_all_enemy_units_in_combat": _lower_deal_all_enemy_in_combat,
    # 2026-09-27 package 6
    "buff_an_exhausted_friendly_unit": _lower_buff_exhausted_friendly_unit,
    "ready_something_else_thats_exhausted": _lower_ready_something_else_exhausted,
    "give_me_might_this_turn_if_there_is_a_ready_enemy_unit_here": _lower_give_me_might_if_ready_enemy_here,
    "buff_up_to_two_other_friendly_units": _lower_buff_up_to_two_other_friendly_units,
    "buff_all_friendly_units": _lower_buff_all_friendly_units,
    "if_i_am_at_a_battlefield_buff_all_other_friendly_units_there": _lower_if_at_battlefield_buff_all_other_friendly_units_there,
    "kill_all_damaged_enemy_units_here": _lower_kill_all_damaged_enemy_units_here,
    "deal_n_to_all_units_at_battlefields": _lower_deal_all_units_at_battlefields,
    "channel_n_rune_exhausted": _lower_channel_exhausted,
    "return_a_unit_from_your_trash_to_your_hand": _lower_return_from_trash,
    "while_you_have_n_runes_i_have_might": _lower_while_runes_might,
    "units_you_play_this_turn_enter_ready": _lower_units_enter_ready,
    "opponents_cant_play_cards_this_turn": _lower_opponents_cant_play_cards,
    "the_next_spell_you_play_this_turn_costs_n_less": _lower_next_spell_discount,
    "give_a_unit_at_a_battlefield_or_a_gear_temporary": _lower_temporary_unit_at_battlefield_or_gear,
    "the_next_unit_you_play_this_turn_enters_ready": _lower_next_unit_enters_ready,
    "no_rules_text": _lower_empty,
    "self_cost_reduction_score": _lower_self_cost_reduction,
    "self_cost_reduction_fixed": _lower_self_cost_reduction_fixed,
    "my_might_is_increased_by_your_points": _lower_might_by_points,
    "self_cost_reduction_per_trash_card": _lower_self_cost_reduction_per_trash,
    "self_cost_reduction_highest_might": _lower_self_cost_reduction_highest_might,
    "self_cost_reduction_unit_died": _lower_self_cost_reduction_unit_died,
}

# 2026-09-27 package 6: the tags a trigger condition may name, normalized -> as printed (Core 763.1).
# A closed table: a word that is not a tag ("if you control a unit") never becomes one.
PRINTED_TAGS = {"poro": "Poro"}

# Productions that wrap another clause: "When you play me, <inner>."
TRIGGER_WRAPPERS = {
    # 2026-09-27 package 6 (Poro Herder): "When you play me, if you control a Poro, ..." - the conditional
    # statement right after the trigger condition is part of it (Core 383.2.a.1), read as the play
    # completes (resolution_bridge.complete_permanent_play); the tag as printed (Core 133.8.a, 763.1)
    "when_you_play_me_if_you_control_a_tag": ("play_triggers", "on-play", lambda params: {
        "condition": {"kind": "controls_units", "count": 1, "tag": PRINTED_TAGS[params["tag"]]}}),
    "when_you_play_me": ("play_triggers", "on-play", None),
    "when_i_move": ("move_triggers", "on-move", None),
    "when_i_move_to_a_battlefield": ("move_triggers", "on-move-to-battlefield", {"condition": {"kind": "moved_to_battlefield"}}),
    "at_the_end_of_your_turn": ("end_of_turn_triggers", "eot", None),
    "at_the_start_of_your_beginning_phase": ("beginning_phase_triggers", "on-beginning", {"scope": "your_beginning_phase"}),
    # 2026-09-27 (Mushroom Pouch): the conditional statement right after the trigger condition is
    # part of the trigger condition (Core 383.2.a.1) - on the descriptor, not a predicate of the effect
    "at_the_start_of_your_beginning_phase_if_you_control_a_facedown_card_at_a_battlefield": (
        "beginning_phase_triggers", "on-beginning",
        {"scope": "your_beginning_phase", "condition": {"kind": "controls_facedown_card_at_battlefield"}}),
    # Core 469.1: the unit conquering is the one at the Battlefield being
    # scored. That is the engine's default scope for a conquer trigger; the
    # clause states it rather than relying on the default.
    "when_i_conquer": ("conquer_triggers", "on-conquer", {"scope": "unit_here"}),
    # Core 383.4.d.2.a: a Unit's own Hold Effect fires when that Unit is at the Battlefield
    # its controller Holds - the same unit_here scope the Scoring Step already reads.
    "when_i_hold": ("hold_triggers", "on-hold", {"scope": "unit_here"}),
    # Core 383.4.e: a Unit's own Attack Trigger. Unlike conquer/hold, this descriptor is
    # never read by a shared scoring pass across the whole board - open_combat's own
    # _designation_triggers reads it straight off the Unit that just gained the Attacker
    # designation, so there is no separate scope to state (same shape as when_i_move).
    "when_i_attack": ("attack_triggers", "on-attack", None),
    # Core 383.4.e / 383.4.f: one ability, two trigger conditions - the Unit gaining the
    # Attacker OR the Defender designation. A Unit holds one designation per Combat, and
    # both fields carry the same trigger_id, so it goes on the Chain at most once per
    # Combat (383.4.e.2.a, 383.4.f.2.a).
    "when_i_attack_or_defend": (("attack_triggers", "defend_triggers"), "on-attack-or-defend", None),
    # 2026-09-27: one ability, two conditions of different kinds - a Play Effect (Core 383.4.a,
    # 419.4.a) and a Conquer Effect (383.4.c.2.a). The conquer field's default scope is the
    # Unit's own (unit_here, battlefield_control._score_triggers), so no extra is shared.
    "when_im_played_and_when_i_conquer": (("play_triggers", "conquer_triggers"), "on-play-and-conquer", None),
    # 2026-09-24: watched triggers - a typed watch over the semantic events (watchers.py),
    # woken by the play transaction's "played" and by every resolution's events. The player
    # "you" is the event's actor; each fact the text names is a named filter, nothing else.
    "when_you_play_a_spell": ("event_triggers", "on-play-spell", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"object_kind": "spell"}}}),
    # Core 206: "costs [5] or more" compares the spell's PRINTED Energy cost
    "when_you_play_a_spell_that_costs_n_or_more": ("event_triggers", "on-play-costly-spell", lambda params: {"watch": {
        "kinds": ["played"], "scope": "actor",
        "filter": {"object_kind": "spell", "printed_energy_at_least": int(params["cost"])}}}),
    "when_you_play_a_gear": ("event_triggers", "on-play-gear", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"object_kind": "gear"}}}),
    "when_you_play_another_unit": ("event_triggers", "on-play-another-unit", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"object_kind": "unit", "exclude_source": True}}}),
    # 2026-09-27 (Volibear - Relentless Storm): "a [Mighty] unit" is a Unit whose current Might is 5 or
    # greater (Core 708, 710), read off the played Unit when the play wakes the watch
    # 2026-10-06 package 9 (Volibear - Imposing, GPT ruling 14): an opponent's Move - a Standard Move they make or one an
    # effect they control makes (Core 411.1, 411.4) - to a Battlefield the source is not at; one per batch of Moves
    "when_an_opponent_moves_to_a_battlefield_other_than_mine": ("event_triggers", "on-opponent-move", {"watch": {
        "kinds": ["moved"], "scope": "opponent_actor",
        "filter": {"destination_kind": "battlefield", "destination_not_source_battlefield": True},
        "grouping": "one_or_more"}}),
    "when_you_play_a_mighty_unit": ("event_triggers", "on-play-mighty-unit", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"object_kind": "unit", "object_might_at_least": 5}}}),
    "when_you_play_a_card_on_an_opponents_turn": ("event_triggers", "on-play-opponents-turn", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"on_opponents_turn": True}}}),
    "when_you_play_a_card_from_hidden": ("event_triggers", "on-play-from-hidden", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"from_hidden": True}}}),
    "when_you_stun_one_or_more_enemy_units": ("event_triggers", "on-stun-enemies", {"watch": {
        "kinds": ["stunned"], "scope": "actor", "filter": {"object_controller_relation": "enemy"},
        "grouping": "one_or_more"}}),
    # 2026-09-26 package 3: "an enemy unit" is one trigger per stunned enemy unit (Core 383.3.a),
    # where "one or more" above is one per batch
    "when_you_stun_an_enemy_unit": ("event_triggers", "on-stun-enemy", {"watch": {
        "kinds": ["stunned"], "scope": "actor", "filter": {"object_controller_relation": "enemy"}}}),
    # "you discard": the player whose hand the card left (the event's player, Core 422.1), not
    # the controller of the effect that made them discard (an opponent's "discard 1" makes YOU
    # discard); one trigger per batch. A discard paid as a cost counts (Core 422.2.a, 422.3)
    "when_you_discard_one_or_more_cards": ("event_triggers", "on-discard", {"watch": {
        "kinds": ["discarded"], "scope": "player", "grouping": "one_or_more"}}),
    "when_you_recycle_one_or_more_cards_to_your_main_deck": ("event_triggers", "on-recycle", {"watch": {
        "kinds": ["recycled"], "scope": "actor", "filter": {"destination_zone": "main_deck"},
        "grouping": "one_or_more"}}),
    "when_a_buffed_friendly_unit_dies": ("event_triggers", "on-buffed-friendly-death", {"watch": {
        "kinds": ["died"], "scope": "any",
        "filter": {"object_kind": "unit", "object_controller_relation": "friendly", "object_was_buffed": True}}}),
    # 2026-09-27 (Solari Shrine): "you kill" is a kill you are responsible for (Core 411.4, 428.5.b, 428.5.c.1,
    # 428.5.c.2 - the died event's responsible_player); "a stunned enemy unit" is read off the unit as it was
    "when_you_kill_a_stunned_enemy_unit": ("event_triggers", "on-kill-stunned-enemy", {"watch": {
        "kinds": ["died"], "scope": "responsible",
        "filter": {"object_kind": "unit", "object_controller_relation": "enemy", "object_was_stunned": True}}}),
    "the_first_time_a_friendly_unit_dies_each_turn": ("event_triggers", "on-first-friendly-death", {"watch": {
        "kinds": ["died"], "scope": "any", "filter": {"object_kind": "unit", "object_controller_relation": "friendly"},
        "occurrence": "first_each_turn"}}),
    # 2026-09-27: "the Nth time I move" - the card's own Moves this turn, a Standard Move or one an
    # effect makes (Core 420.2, 446.1), counted per object (Core 124); the count reaching N
    # triggers it once (Core 383.1, 383.1.b). A Recall is not a Move (446.1) and emits no `moved`
    "the_first_time_i_move_each_turn": ("event_triggers", "on-first-move", {"watch": {
        "kinds": ["moved"], "scope": "self", "occurrence": "first_each_turn"}}),
    "the_third_time_i_move_in_a_turn": ("event_triggers", "on-third-move", {"watch": {
        "kinds": ["moved"], "scope": "self", "occurrence": "nth_each_turn", "nth": 3}}),
    # 2026-09-27: a player-level Conquer Effect (Core 383.4.c.2.b): it references the player who
    # Conquered, so it fires from any source that player controls where its abilities work - a
    # board object or a Legend in its Legend Zone (battlefield_control._score_triggers). Distinct
    # from a Unit's "When I conquer" (unit_here) and a Battlefield's "When you conquer here"
    "when_you_conquer": ("conquer_triggers", "on-you-conquer", {"scope": "controller"}),
    # 2026-09-27 (package 6): "your second card in a turn" - the play's ordinal, stamped by the play
    # transaction as each play is Finalized (Core 419.4.b), every play of the turn counted
    "when_you_play_your_second_card_in_a_turn": ("event_triggers", "on-play-second-card", {"watch": {
        "kinds": ["played"], "scope": "actor", "filter": {"card_played_ordinal": 2}}}),
    # 2026-09-27 (package 6): "another non-Recruit unit you control" - the dying unit's kind and tags
    # as it was (a token has ceased to exist, Core 186.1; a Recruit token is tagged by Core 187.1)
    "when_another_non_recruit_unit_you_control_dies": ("event_triggers", "on-non-recruit-death", {"watch": {
        "kinds": ["died"], "scope": "any",
        "filter": {"object_kind": "unit", "object_controller_relation": "friendly", "exclude_source": True,
                   "object_not_tagged": "Recruit"}}}),
    # 2026-09-27 (package 6): works from the trash, the zone discarding puts the card in (Core 422.1,
    # 383.2.c.1, 385.2) - watchers.source_active reads `functions_from`, and nothing else does
    "when_you_discard_me": ("event_triggers", "on-discard-me", {"watch": {
        "kinds": ["discarded"], "scope": "self"}, "functions_from": ["trash"]}),
    # 2026-09-27 (package 6): a unit's death attributed to a spell its controller is responsible for
    # (Core 428.5.b-d; resolution_bridge.kill_attributed). Where the ability works is the card's own
    # business: Immortal Phoenix says "from your trash" (Core 385.2) - its descriptor adds functions_from
    "when_you_kill_a_unit_with_a_spell": ("event_triggers", "on-spell-kill", {"watch": {
        "kinds": ["died"], "scope": "any", "filter": {"object_kind": "unit", "killed_by_your_spell": True}}}),
    # 2026-09-28: watches over a Unit gaining a combat designation (combat.open_combat /
    # sync_designations emit `attacked` / `defended`, Core 464.2.c.3). One trigger per Unit
    # (383.3.a); the other requirements are read as the designation is gained (383.4.e.2.b,
    # 383.4.f.2.b). "a battlefield you control": the watcher's controller controlled the combat's
    # Battlefield then (control does not change during the combat, 190.4.b).
    "when_an_enemy_unit_attacks_a_battlefield_you_control": ("event_triggers", "on-enemy-attacks-yours", {"watch": {
        "kinds": ["attacked"], "scope": "any",
        "filter": {"object_kind": "unit", "object_controller_relation": "enemy", "at_battlefield_you_control": True}}}),
    # "attacks or defends alone": one ability, either designation, the Unit alone then (Core 740.2.a)
    "when_a_friendly_unit_attacks_or_defends_alone": ("event_triggers", "on-friendly-alone", {"watch": {
        "kinds": ["attacked", "defended"], "scope": "any",
        "filter": {"object_kind": "unit", "object_controller_relation": "friendly", "alone": True}}}),
}
# 2026-09-28: the wrappers whose watched event is about ONE object that the ability's "it" names -
# the trigger's referent (Core 359.3.f.3). An instruction of the inner clause that points at
# $referent is bound to {object_ref: trigger_event_object}, which the engine resolves from the
# trigger's chain item (effect_ir.resolve_trigger_event_object); an op with no reviewed adoption of
# that reference leaves the clause unsupported (referent_not_bound). No other wrapper binds it: a
# watch over a death or a play would name an object that is no longer (or not yet) on the board.
REFERENT_WRAPPERS = {"when_an_enemy_unit_attacks_a_battlefield_you_control",
                     "when_a_friendly_unit_attacks_or_defends_alone", "when_a_unit_moves_from_here"}

# A Battlefield's own trigger is a different shape from an object's - Core
# 190.6.a leaves its controller unnamed - so it has its own branch rather than
# a row above. Named here so the contract check sees a production that can be
# compiled, which is the whole point of that check.
BATTLEFIELD_TRIGGER_WRAPPERS = {"when_you_hold_here": ("hold_triggers", "on-hold"),
                                # 2026-10-06 package 9 (The Grand Plaza, Core 383.2.a.1): the condition on the
                                # descriptor, {kind controls_units, count N, location here}
                                "when_you_hold_here_if_you_have_n_units_here": ("hold_triggers", "on-hold",
                                                                                lambda params: {"condition": {
                                                                                    "kind": "controls_units",
                                                                                    "count": int(params["count"]),
                                                                                    "location": "here"}}),
                                "when_you_conquer_here": ("conquer_triggers", "on-conquer"),
                                "when_you_defend_here": ("defend_triggers", "on-defend"),
                                # 2026-09-28: a Unit's Move whose location before was this
                                # Battlefield (watchers.BATTLEFIELD_WATCH_FIELDS)
                                "when_a_unit_moves_from_here": ("move_from_triggers", "on-move-from")}


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
    "player_ref_not_declared",         # "they" with no earlier clause that chose a player
    "reveal_not_declared",             # a choice "from it" with no earlier reveal to choose from
    "mapping_not_supplied",            # the clause needs a card mapping the caller did not provide
    "mapping_invalid",                 # a mapping was supplied and does not satisfy its own contract
})


# DP-93: what a card mapping may supply, and the module that validates it.
# The public engine ships the contract and the verifier; which reading a
# particular card takes is service data and lives with the card corpus.
MAPPING_VALIDATORS = {"cost_comparison": ("cost_comparison", "validate_limit")}


def _apply_mapping(compiled: dict[str, Any], mappings: dict[str, Any] | None) -> dict[str, Any]:
    """Fill the one hole a clause deliberately left, or abstain.

    A clause that leaves a hole is not broken - it is a clause whose meaning
    the rules do not fix. Filling it from a default would be inventing a
    ruling; leaving it empty and calling the clause compiled would be worse,
    because the program would then run against an incomplete limit.
    """
    need = compiled.get("needs_mapping")
    if need is None:
        return compiled
    supplied = (mappings or {}).get(need)
    if supplied is None:
        return {"production_id": compiled["production_id"], "unsupported": True,
                "reason_code": "mapping_not_supplied", "text": compiled["text"],
                "normalized": compiled.get("normalized"), "needs_mapping": need,
                "reason": f"this clause needs a {need} mapping; the rules do not fix the reading and "
                          "the grammar will not pick one"}
    module_name, function_name = MAPPING_VALIDATORS[need]
    module = __import__(module_name)
    filled = copy.deepcopy(compiled)
    for effect in filled.get("program_effects", []):
        target = effect.get("target")
        if isinstance(target, dict) and isinstance(target.get("max_cost"), dict):
            target["max_cost"] = {**target["max_cost"], **supplied}
    problems = [problem for effect in filled.get("program_effects", [])
                if isinstance(effect.get("target"), dict) and isinstance(effect["target"].get("max_cost"), dict)
                for problem in getattr(module, function_name)(effect["target"]["max_cost"])]
    if problems:
        return {"production_id": compiled["production_id"], "unsupported": True,
                "reason_code": "mapping_invalid", "text": compiled["text"],
                "normalized": compiled.get("normalized"), "needs_mapping": need,
                "reason": f"the {need} mapping does not satisfy its own contract: {problems}"}
    filled.pop("needs_mapping", None)
    filled["mapping"] = {need: supplied}
    return filled

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
COUNTED_CHANNEL_LINK = re.compile(r"^if you couldn't channel (\d+) runes? this way, ")
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


def _bind_to_trigger_event(effects: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """2026-09-28 (REFERENT_WRAPPERS): point every referent at the object the trigger's event was
    about - {object_ref: trigger_event_object}, resolved by the engine from the chain item, never
    chosen (so the target, and its selector, go). None when an instruction pointing at the referent
    has an op with no reviewed adoption of that reference: refused, not guessed."""
    from effect_ir import TRIGGER_EVENT_OBJECT, TRIGGER_EVENT_OBJECT_OPS
    bound = copy.deepcopy(effects)
    for effect in bound:
        target = effect.get("target")
        if isinstance(target, dict) and target.get("decision_ref") == REFERENT_REF:
            if effect.get("op") not in TRIGGER_EVENT_OBJECT_OPS:
                return None
            effect.pop("target")
            effect["object_id"] = {"object_ref": TRIGGER_EVENT_OBJECT}
    return bound


def _trigger_referent_effects(production_id: str, inner: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The wrapper's program: the inner clause's, with its referent bound to the trigger's event object
    when this wrapper is one of REFERENT_WRAPPERS (None: an op that may not carry it); every other
    wrapper's exactly as before."""
    effects = inner.get("program_effects", [])
    if production_id not in REFERENT_WRAPPERS or not _has_unbound_referent(effects):
        return effects
    return _bind_to_trigger_event(effects)


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
                   previous: dict[str, Any] | None = None,
                   mappings: dict[str, Any] | None = None) -> dict[str, Any]:
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

    # 2026-09-27 package 6: right after a printed optional additional cost, "If you do" /
    # "Otherwise" / "for each killed this way" read that offer (Core 356.2.b.1, 356.4.f.1)
    offer_linked = _offer_linked(text, normalized, previous, grammar)
    if offer_linked is not None:
        return offer_linked

    # Core 430.5's own example (Catalyst of Aeons): "If you couldn't channel 2 runes this
    # way" is "if you can't" with the count spelled out. It reads the SAME receipt - the
    # previous instruction's - and the words must describe that instruction: a Channel of
    # exactly that many runes. Anything else abstains rather than reading another receipt.
    counted = COUNTED_CHANNEL_LINK.match(normalized)
    if counted:
        before = (previous or {}).get("program_effects") or []
        last = before[-1] if before and not (previous or {}).get("unsupported") else None
        if last is None or last.get("op") != "channel_rune" or last.get("count") != int(counted.group(1)):
            return {"production_id": "linked_prefix", "unsupported": True,
                    "reason_code": "link_antecedent_not_that_channel", "text": text, "normalized": normalized,
                    "link": "requested_count_not_reached",
                    "reason": f"{counted.group(0).strip()!r} names a Channel of {counted.group(1)}; the previous "
                              f"instruction is {(last or {}).get('op')!r} of {(last or {}).get('count')!r}"}
        normalized = "if you can't, " + normalized[counted.end():]

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
        if production_id == "keyworded_ability" and slots["keyword"]["keyword"] in DEPENDENT_KEYWORDS:
            name = slots["keyword"]["keyword"]
            inner = compile_clause(match.group("inner"), grammar, previous=previous)
            dependent = None if inner.get("unsupported") else _lower_dependent_keyword(name, inner)
            if dependent is None:
                return {"production_id": production_id, "unsupported": True, "reason_code": "dependent_ability_form_unsupported",
                        "text": text, "normalized": normalized, "slots": slots, "inner_text": match.group("inner"),
                        "rule_locators": list(production["rule_locators"]) + ["Core 727.1", "Core 812.1.b.1"],
                        "reason": f"[{name}] gates {match.group('inner')!r}; the engine reads its condition only on "
                                  "\"When you play me\" and on \"I cost N less\""}
            return {
                "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
                "params": {}, "slots": slots,
                "rule_locators": list(production["rule_locators"]) + ["Core 727.1", "Core 812.1.b.1", "Core 812.1.c"] + inner["rule_locators"],
                "required_capability": sorted(set(production["required_capability"]) | set(inner["required_capability"]) | {"legion_condition"}),
                "ast": dependent["ast"],
                "passive": {"object_fields": {**dependent["object_fields"], "keywords": [name]}},
                "program_effects": dependent["program_effects"],
            }
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
        if production_id in BATTLEFIELD_TRIGGER_WRAPPERS:
            field, trigger_id, *battlefield_extra = BATTLEFIELD_TRIGGER_WRAPPERS[production_id]
            # "You may" is the trigger's own optionality at finalization
            # (383.3), not a separate instruction - the engine already carries
            # it on the descriptor.
            optional = bool(params.get("optional"))
            inner = compile_clause(params["inner"], grammar, previous=previous)
            if inner.get("unsupported"):
                return {"production_id": production_id, "unsupported": True,
                        "reason_code": inner.get("reason_code", "clause_unparsed"),
                        "text": text, "inner_text": params["inner"],
                        "reason": f"the Battlefield trigger parsed but its instruction did not: {params['inner']!r}"}
            inner_effects = _trigger_referent_effects(production_id, inner)
            if inner_effects is None:
                return {"production_id": production_id, "unsupported": True, "reason_code": "referent_not_bound",
                        "text": text, "inner_text": params["inner"],
                        "reason": "'it' names the trigger's object, and the instruction's op has no reviewed adoption of that reference"}
            return {
                "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
                "params": params, "rule_locators": production["rule_locators"] + inner["rule_locators"],
                "ast": {"node": "triggered", "on": production_id, "optional": optional, "then": inner["ast"]},
                "passive": _battlefield_trigger(field, trigger_id, optional,
                                                (battlefield_extra[0](params) if battlefield_extra else None)),
                "program_effects": inner_effects,
                "required_capability": sorted(set(production["required_capability"]) | set(inner["required_capability"])),
            }
        if production_id in TRIGGER_WRAPPERS:
            field, trigger_id, trigger_extra = TRIGGER_WRAPPERS[production_id]
            if callable(trigger_extra):
                # a wrapper with its own parameter ("costs [5] or more") builds its extra from it
                trigger_extra = trigger_extra(params)
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
            inner_effects = _trigger_referent_effects(production_id, inner)
            if inner_effects is None:
                return {"production_id": production_id, "unsupported": True, "reason_code": "referent_not_bound",
                        "text": text, "inner_text": params["inner"],
                        "reason": "'it' names the trigger's object, and the instruction's op has no reviewed adoption of that reference"}
            return {
                "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
                "params": params, "rule_locators": production["rule_locators"] + inner["rule_locators"],
                "ast": {"node": "triggered", "on": production_id, "then": inner["ast"]},
                "passive": _trigger(field, trigger_id, trigger_extra),
                "program_effects": inner_effects,
                "required_capability": sorted(set(production["required_capability"]) | set(inner["required_capability"])),
                # what the inner clause bound to travels with the wrapper, so a
                # card-level check sees it
                **({"modal": {**inner["modal"], "timing": "trigger_finalization"}} if inner.get("modal") else {}),
                **({"cost_offer_id": inner["cost_offer_id"]} if inner.get("cost_offer_id") is not None else {}),
                **({"antecedent_effect_id": inner["antecedent_effect_id"]} if inner.get("antecedent_effect_id") is not None else {}),
            }
        lowered = COMPOSABLE[production_id](params, slots) if production_id in COMPOSABLE else LOWERINGS[production_id](params)
        if any(k in lowered for k in ("object_fields", "battlefield_fields", "state_lists")):
            # ADR-0007: what a card contributes while it exists is either a
            # field on its own object or an entry in a state-level list. An
            # aura is the second kind - it is not a field of the unit it
            # modifies, because it modifies whichever unit is defending alone.
            passive_shape = {k: lowered[k] for k in ("object_fields", "battlefield_fields", "state_lists")
                             if k in lowered}
            lowered = {**{k: v for k, v in lowered.items()
                          if k not in {"object_fields", "battlefield_fields", "state_lists"}},
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
        return _apply_mapping(compiled, mappings)
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
        # ", then " is ORDER, not a condition (GPT 2026-09-25; Core 422.4's own example: with
        # no cards in hand the discard is ignored and the draw still happens). Only a written
        # "If you do" makes a later instruction depend on an earlier one (359.3.e.14), and
        # that is the linked-prefix path (LINK_PREFIXES), not this one.
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


def compile_card(clauses: list[dict[str, Any]], grammar: dict[str, Any] | None = None,
                 mappings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every clause of one card, in order. The card's own declaration — its
    printed cost, its type, where it enters — is not a clause's business, so
    the compiler does not invent one."""
    grammar = grammar or load_grammar()
    compiled: list[dict[str, Any]] = []
    state_lists: dict[str, Any] = {}
    declared_offers = 0
    for clause in clauses:
        entry = compile_clause(clause["text"], grammar, previous=compiled[-1] if compiled else None,
                               mappings=mappings)
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

    # Sabotage: "they" and "from it" name things an earlier clause of the same
    # card established. Checked across the card rather than inside a clause,
    # because that is the only place the earlier clause is visible - and
    # refused rather than defaulted, because defaulting "they" to the sole
    # opponent silently makes a two-player reading of a card that does not
    # say so.
    declared_player_refs: set[str] = set()
    declared_reveals = 0
    for index, entry in enumerate(compiled):
        if entry.get("unsupported"):
            continue
        need_player = entry.get("needs_player_ref")
        if need_player is not None and need_player not in declared_player_refs:
            compiled[index] = {"production_id": entry["production_id"], "unsupported": True,
                               "reason_code": "player_ref_not_declared", "text": entry["text"],
                               "normalized": entry.get("normalized"),
                               "reason": "the clause names a player no earlier clause chose"}
            continue
        if entry.get("needs_reveal") and not declared_reveals:
            compiled[index] = {"production_id": entry["production_id"], "unsupported": True,
                               "reason_code": "reveal_not_declared", "text": entry["text"],
                               "normalized": entry.get("normalized"),
                               "reason": "the clause chooses from a reveal no earlier clause performed"}
            continue
        if entry.get("declares_player_ref"):
            declared_player_refs.add(entry["declares_player_ref"])
        if entry.get("declares_reveal"):
            declared_reveals += 1

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
    battlefield_fields: dict[str, Any] = {}
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
        for field, value in ((entry.get("passive") or {}).get("battlefield_fields", {}) or {}).items():
            battlefield_fields.setdefault(field, []).extend(copy.deepcopy(value))
    modal = [entry["modal"] for entry in compiled if entry.get("modal")]
    return {
        "schema_version": GRAMMAR_VERSION,
        **({"modal": modal[0]} if len(modal) == 1 else {}),
        "grammar_version": grammar["version"],
        "clauses": compiled,
        "program_effects": effects,
        "passive": ({**({"object_fields": passive} if passive else {}),
                     **({"battlefield_fields": battlefield_fields} if battlefield_fields else {}),
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
        if (production_id not in LOWERINGS and production_id not in COMPOSABLE
                and production_id not in TRIGGER_WRAPPERS and production_id not in BATTLEFIELD_TRIGGER_WRAPPERS):
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
