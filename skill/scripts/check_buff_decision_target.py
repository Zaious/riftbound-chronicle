#!/usr/bin/env python3
"""
Regression gate: buff / empower / disempower accept a typed decision_ref target.

Until 2026-09-09 `validate_program` demanded a literal `object_id` for these
three ops while stun, kill, ready, exhaust and deal_damage took the same typed
`target` with a `decision_ref` that decision resolution turns into an object id.
The consequence was concrete: clause-grammar.v1's own `buff_selector` output for
"Buff a friendly unit." failed the engine's own validator, and only "Buff me."
(a literal `$source_object`) could be a valid program.

Codex's ruling fixing it (P1b, 2026-09-09) set the scope, and this gate holds
each edge of it:

  - "Buff a friendly unit." goes through `decision_ref`: the decision names a
    friendly Unit on the board, the program commits, the counter lands;
  - a decision that names the wrong object is refused, one way per wrong:
      * an enemy Unit against `controller_relation: friendly` is skipped as
        an illegal target and nothing is buffed;
      * a non-Unit is skipped the same way;
      * an id the state does not hold is an invalid program, not a buff;
      * no decision at all stops with target_decision_required;
  - the literal path is untouched: `object_id` alone still commits, and a
    second Buff on the same Unit is still the 426.1.b no_op;
  - no new semantics: `affected` and `targets` on buff/empower/disempower are
    refused at validation, so "Buff all friendly units." stays a blocker;
  - the grammar and the validator agree again: buff_selector's program for
    "Buff a friendly unit." validates, and clause-grammar.v1 still returns
    unsupported for "Buff all friendly units.".
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
import engine_decisions as ed  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, validate_program  # noqa: E402


def program(*effects, controller="p1"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "buff-decision", "controller": controller, "effects": list(effects)}


def decision(state, object_id, controller="p1"):
    """The decisions envelope apply_program checks: version, the state's hash, one target_selection."""
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": controller,
         "value": [object_id], "selection_identities": {object_id: f"{object_id}@0"}}]}


FRIENDLY_UNIT = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}


def buff_via_decision(target=FRIENDLY_UNIT):
    return program({"op": "buff", "effect_id": "bf", "target": dict(target)})


def ev(result):
    return (result.get("trace") or [{}])[-1]


def main() -> int:
    errors: list[str] = []
    state = base_state()

    # --- the fix: a decision_ref target validates and buffs the chosen friendly Unit ---------------
    prog = buff_via_decision()
    schema = validate_program(prog)
    if schema:
        errors.append(f"a decision_ref buff no longer validates: {schema}")
    ok = apply_program(state, prog, decisions=decision(state, "u1"))
    if not ok.get("committed") or ok["next_state"]["objects"]["u1"].get("buffed") is not True or ev(ok).get("was_buffed") is not True:
        errors.append(f"'Buff a friendly unit.' through a decision did not place the counter: {ok.get('reason_code')} {ok.get('reason')} {ok.get('errors')}")

    # --- wrong decisions are refused, each in its own way ----------------------------------------
    enemy = apply_program(state, prog, decisions=decision(state, "u2"))
    if enemy.get("next_state", {}).get("objects", {}).get("u2", {}).get("buffed") or ev(enemy).get("outcome") != "ignored_illegal_target":
        errors.append(f"an enemy Unit against controller_relation=friendly was not skipped as illegal: {ev(enemy)}")
    non_unit = apply_program(state, prog, decisions=decision(state, "c1"))
    if non_unit.get("next_state", {}).get("objects", {}).get("c1", {}).get("buffed") or ev(non_unit).get("outcome") != "ignored_illegal_target":
        errors.append(f"a non-Unit target was not skipped as illegal: {ev(non_unit)}")
    # An id the state does not hold is an illegal target, and Core 359.3.e treats
    # an illegal target the same way for every instruction: the effect is skipped
    # with target_object_missing and the program goes on. Stun and kill already
    # behave this way; buff must match them, not invent a harder refusal.
    ghost = apply_program(state, prog, decisions=decision(state, "u9"))
    if ev(ghost).get("outcome") != "ignored_illegal_target" or ev(ghost).get("reason") != "target_object_missing" \
            or any(o.get("buffed") for o in ghost.get("next_state", {}).get("objects", {}).values()):
        errors.append(f"an object the state does not hold was not skipped as target_object_missing: {ev(ghost)}")
    stale = apply_program(state, prog, decisions=None)
    if stale.get("committed") or stale.get("reason_code") != "target_selection_required":
        errors.append(f"a missing decision did not stop with target_selection_required: {stale.get('reason_code')} {stale.get('reason')}")

    # --- the literal path is untouched -----------------------------------------------------------
    literal = apply_program(state, program({"op": "buff", "effect_id": "bf", "object_id": "u1"}))
    if not literal.get("committed") or literal["next_state"]["objects"]["u1"].get("buffed") is not True:
        errors.append("the literal object_id buff no longer commits")
    twice = apply_program(literal["next_state"], program({"op": "buff", "effect_id": "bf", "object_id": "u1"}))
    if ev(twice).get("outcome") != "no_op" or ev(twice).get("was_buffed") is not False:
        errors.append(f"a second Buff counter was placed (426.1.b): {ev(twice)}")

    # --- no new semantics: one object only --------------------------------------------------------
    for op_name in ("buff", "empower", "disempower"):
        over_set = program({"op": op_name, "effect_id": "x", "affected": {"criteria": {"kind": "unit", "controller_relation": "friendly", "location": "any_battlefield"}}})
        if not any("one object" in e for e in validate_program(over_set)):
            errors.append(f"{op_name} over `affected` was accepted; 'Buff all ...' must stay refused")
        bare = program({"op": op_name, "effect_id": "x"})
        if not any("needs the object it acts on" in e for e in validate_program(bare)):
            errors.append(f"{op_name} with neither object_id nor target was accepted")

    # --- grammar and validator agree again ---------------------------------------------------------
    grammar = cg.load_grammar()
    parsed = cg.compile_clause("Buff a friendly unit.", grammar)
    if parsed.get("unsupported") or parsed.get("production_id") != "buff_selector":
        errors.append(f"clause-grammar.v1 no longer parses 'Buff a friendly unit.' to buff_selector: {parsed.get('production_id')}")
    else:
        from_grammar = program(*copy.deepcopy(parsed["program_effects"]))
        if validate_program(from_grammar):
            errors.append(f"buff_selector's own program still fails validate_program: {validate_program(from_grammar)}")
    if not cg.compile_clause("Buff all friendly units.", grammar).get("unsupported"):
        errors.append("clause-grammar.v1 now claims 'Buff all friendly units.'; that must remain unsupported")

    if errors:
        print("FAILED: buff decision_ref target")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("buff / empower / disempower accept a typed decision_ref target; wrong decisions are refused each in its own way; "
          "the literal path and the 426.1.b no_op are unchanged; affected/targets stay refused; buff_selector's program validates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
