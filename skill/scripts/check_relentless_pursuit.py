#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Relentless Pursuit, "[Action] Move a friendly unit. You may attach up to one Equipment
with the same controller to it. This turn, that unit has "When I conquer, you may move me to my base."").

  P1 all       f1 moved to bf2, eq1 (p1's) chosen and attached, the "you may" performed: f1 at bf2 with eq1; f1 has the
               granted conquer trigger (object_triggers), its source f1, controller p1, optional
  P2 none      no Equipment chosen (up to one: none): the attach does nothing; the grant is still made
  P3 declined  eq1 chosen, the attach declined as it resolves: eq1 stays where it was; the grant is made
  P4 the turn  the next turn f1 no longer has the trigger
  P5 fires     the granted trigger scheduled from f1, finalized performing it, resolved with its program: f1 moves to
               p1's Base
  P6 count     at play the Equipment choice is none or one: two refused; one of p2's refused (same controller)
  G            the body lowers to Move, attach, grant (with the granted program); near misses do not
  V            grant_trigger with another duration, an unknown trigger field, or no program hash does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity,  # noqa: E402
                       object_triggers, validate_program)
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import pass_priority, schedule_triggered_items  # noqa: E402

TEXT = ('Move a friendly unit. You may attach up to one Equipment with the same controller to it. This turn, that unit has '
        '"When I conquer, you may move me to my base."')
PRODUCTION = "move_a_friendly_unit_attach_up_to_one_equipment_grant_conquer_move_to_base"


def unit(owner, might=2):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board():
    s = base_state()
    s["battlefields"]["bf2"] = {"controller": None, "objects": []}
    s["objects"]["f1"] = unit("p1")
    s["players"]["p1"]["zones"]["base"].append("f1")
    for oid, owner in (("eq1", "p1"), ("eq2", "p1"), ("xq", "p2")):
        s["objects"][oid] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False, "tags": ["Equipment"]}
        s["players"][owner]["zones"]["base"].append(oid)
    return settle_contested(s)


def bind(value):
    if isinstance(value, dict):
        return {k: bind(v) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v) for v in value]
    return {"$controller": "p1", "$source_object": "spell-1"}.get(value, value) if isinstance(value, str) else value


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "pursuit", "controller": "p1", "source_object": "spell-1", "effects": bind(copy.deepcopy(effects))}


def decisions(s, eq=("eq1",), may=True, where="battlefield:bf2"):
    out = [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["f1"],
            "selection_identities": {"f1": object_identity(s, "f1")}},
           {"decision_id": "dest", "stage": "play_declaration", "kind": "location_selection", "controller": "p1",
            "value": where},
           {"decision_id": "eq", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
            "value": list(eq), "selection_identities": {o: object_identity(s, o) for o in eq}}]
    if may is not None:
        out.append({"decision_id": "may-attach", "stage": "resolution", "kind": "optional_choice", "controller": "p1",
                    "value": may})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": out}


def at(state, oid):
    for p, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if oid in ids:
                return f"{p}:{zone}"
    for b, data in state["battlefields"].items():
        if oid in data["objects"]:
            return b
    return None


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    effects, granted = got.get("program_effects"), got.get("granted_programs") or {}
    if got.get("production_id") != PRODUCTION or [e.get("op") for e in effects or []] != \
            ["move_board_object", "attach", "grant_trigger"] or len(granted) != 1:
        print(f"relentless-pursuit checks FAILED:\n  - G: {got.get('production_id')} {effects} {list(granted)}")
        return 1
    for near in ("Move a friendly unit. You may attach up to one Equipment with the same controller to it.",
                 'Move a friendly unit. This turn, that unit has "When I conquer, you may move me to my base."'):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == PRODUCTION:
            errors.append(f"G: the near miss {near!r} parsed")
    if validate_program(program(effects)):
        errors.append(f"V: {validate_program(program(effects))[:2]}")
    s = board()
    done = apply_program(s, program(effects), decisions=decisions(s))
    a = done.get("next_state") or {}
    trig = object_triggers(a, "f1", "conquer_triggers") if done.get("committed") else []
    if not done.get("committed") or at(a, "f1") != "bf2" or a["objects"]["eq1"].get("attached_to") != "f1" \
            or len(trig) != 1 or trig[0].get("source_object") != "f1" or trig[0].get("controller") != "p1" \
            or trig[0].get("optional_at_finalize") is not True:
        errors.append(f"P1 all: {done.get('reason') or done.get('errors')} {at(a, 'f1') if a else None} {trig}")
        return report(errors)
    none = apply_program(s, program(effects), decisions=decisions(s, eq=()))
    b = none.get("next_state") or {}
    if not none.get("committed") or any(b["objects"][o].get("attached_to") for o in ("eq1", "eq2")) \
            or len(object_triggers(b, "f1", "conquer_triggers")) != 1:
        errors.append(f"P2 none: {none.get('reason') or none.get('errors')}")
    no = apply_program(s, program(effects), decisions=decisions(s, may=False))
    c = no.get("next_state") or {}
    if not no.get("committed") or c["objects"]["eq1"].get("attached_to") or len(object_triggers(c, "f1", "conquer_triggers")) != 1:
        errors.append(f"P3 declined: {no.get('reason') or no.get('errors')}")
    later = copy.deepcopy(a)
    later["turn_id"] = "turn-later"
    if object_triggers(later, "f1", "conquer_triggers"):
        errors.append("P4 the turn: the trigger outlived the turn")
    registry = {pid: bind(prog) for pid, prog in granted.items()}
    descriptor = {**trig[0], "trigger_kind": "triggered", "batch_sequence": 0, "batch_id": "conquer:bf2",
                  "source_identity": object_identity(a, "f1")}
    timing = schedule_triggered_items(fixture(), [descriptor])["next_state"]
    fin = finalize_trigger(timing, a, registry, None, perform_optional_trigger=True)
    if not fin.get("committed") or fin.get("removed"):
        errors.append(f"P5 fires: finalization {fin.get('reason')} {fin.get('message')}")
    else:
        t, e = fin["next_timing_state"], fin["next_effect_state"]
        for actor in ("p1", "p2"):
            t = (pass_priority(t, actor) or {}).get("next_state") or t
        res = resolve_with_program(t, descriptor["trigger_id"], e, registry[descriptor["effect_program_id"]])
        if not res.get("committed") or at(res.get("next_effect_state") or {}, "f1") != "p1:base":
            errors.append(f"P5 fires: {res.get('reason') or res.get('reason_code')}")
    prog = program(effects)
    for label, eq in (("two", ("eq1", "eq2")), ("p2's", ("xq",))):
        try:
            PT._check_play_targets(s, "p1", prog, decisions(s, eq=eq))
            errors.append(f"P6 count: {label} accepted")
        except PT.PlayError:
            pass
    for label, eq in (("none", ()), ("one", ("eq1",))):
        try:
            PT._check_play_targets(s, "p1", prog, decisions(s, eq=eq))
        except PT.PlayError as exc:
            errors.append(f"P6 count: {label} refused ({exc})")
    for label, change in (("duration", ("duration", "this_combat")), ("field", ("trigger_field", "nope_triggers"))):
        bad = copy.deepcopy(effects)
        bad[2][change[0]] = change[1]
        if not validate_program(program(bad)):
            errors.append(f"V: grant_trigger with another {label} validated")
    bad = copy.deepcopy(effects)
    bad[2]["descriptor"].pop("effect_program_hash")
    if not validate_program(program(bad)):
        errors.append("V: grant_trigger without a program hash validated")
    return report(errors)


def report(errors) -> int:
    if errors:
        print("relentless-pursuit checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("relentless-pursuit checks passed: a friendly unit moved; up to one Equipment of its controller's attached (none, "
          "declined); this turn it has 'When I conquer, you may move me to my base.', gone next turn, and it fires and "
          "resolves; the choice none or one, its controller's; grammar; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
