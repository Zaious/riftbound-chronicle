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


def _trigger(field: str, trigger_id: str) -> dict[str, Any]:
    return {"object_fields": {field: [{"trigger_id": trigger_id, "controller": "$controller",
                                       "source_object": "$source_object", "controller_order": 0,
                                       "effect_program_id": "$clause_id", "optional_at_finalize": False}]}}




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
    criteria = {k: v for k, v in selector.items() if k in {"kind", "controller_relation"}}
    if selector["scope"] == "affected":
        return {"affected": {"criteria": {**criteria, "location": "board"}}}
    return {"target": {"decision_ref": "t", "chosen_zone_class": "board", **criteria}}


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


COMPOSABLE = {
    "keyworded_ability": _lower_keyworded_ability,
    "give_might_for_duration": _lower_give_might,
    "grant_keyword_for_duration": _lower_grant_keyword,
    "object_keyword": _lower_object_keyword,
}

LOWERINGS = {
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
    "when_you_play_me": ("play_triggers", "on-play"),
    "when_i_move": ("move_triggers", "on-move"),
    "at_the_end_of_your_turn": ("end_of_turn_triggers", "eot"),
}


# --------------------------------------------------------------------------
# compiling
# --------------------------------------------------------------------------


def compile_clause(text: str, grammar: dict[str, Any] | None = None) -> dict[str, Any]:
    """One clause in, one typed result out. Deterministic: the same text
    always produces the same production, AST and program."""
    grammar = grammar or load_grammar()
    normalized = normalize(text)
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
            inner = compile_clause(match.group("inner"), grammar)
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
            field, trigger_id = TRIGGER_WRAPPERS[production_id]
            inner = compile_clause(params["inner"], grammar)
            if inner.get("unsupported"):
                return {"production_id": production_id, "unsupported": True, "reason_code": "clause_unparsed",
                        "text": text, "inner_text": params["inner"],
                        "reason": f"the wrapper parsed but its instruction did not: {params['inner']!r}"}
            return {
                "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
                "params": params, "rule_locators": production["rule_locators"] + inner["rule_locators"],
                "ast": {"node": "triggered", "on": production_id, "then": inner["ast"]},
                "passive": _trigger(field, trigger_id),
                "program_effects": inner.get("program_effects", []),
                "required_capability": sorted(set(production["required_capability"]) | set(inner["required_capability"])),
            }
        lowered = COMPOSABLE[production_id](params, slots) if production_id in COMPOSABLE else LOWERINGS[production_id](params)
        if "object_fields" in lowered:
            lowered = {**{k: v for k, v in lowered.items() if k != "object_fields"},
                       "passive": {"object_fields": lowered["object_fields"]}}
        known = lowered.pop("known_unsupported", None)
        if known is not None:
            # Named by the catalogue, not implemented by the engine (DP-85).
            # It is a boundary the grammar knows, not a clause it read.
            return {"production_id": production_id, "unsupported": True, "reason_code": known,
                    "text": text, "normalized": normalized, "slots": slots, "ast": lowered.get("ast"),
                    "rule_locators": list(production["rule_locators"]),
                    "reason": f"{production_id} recognised the clause, but the engine does not implement it"}
        return {
            "production_id": production_id, "unsupported": False, "text": text, "normalized": normalized,
            "params": params, "slots": slots, "rule_locators": list(production["rule_locators"]),
            "required_capability": list(production["required_capability"]),
            **lowered,
        }
    return {"production_id": None, "unsupported": True, "reason_code": "clause_unparsed", "text": text,
            "normalized": normalized, "reason": "no production in clause-grammar.v1 matches this clause"}


def compile_card(clauses: list[dict[str, Any]], grammar: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every clause of one card, in order. The card's own declaration — its
    printed cost, its type, where it enters — is not a clause's business, so
    the compiler does not invent one."""
    grammar = grammar or load_grammar()
    compiled = [compile_clause(clause["text"], grammar) for clause in clauses]
    effects: list[dict[str, Any]] = []
    passive: dict[str, Any] = {}
    for entry in compiled:
        for effect in entry.get("program_effects", []) or []:
            effects.append(copy.deepcopy(effect))
        for field, value in (entry.get("passive", {}).get("object_fields", {}) or {}).items():
            passive.setdefault(field, []).extend(copy.deepcopy(value))
    return {
        "schema_version": GRAMMAR_VERSION,
        "grammar_version": grammar["version"],
        "clauses": compiled,
        "program_effects": effects,
        "passive": {"object_fields": passive} if passive else None,
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
