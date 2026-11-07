#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Angle Shot, "Choose a unit and an Equipment with the same controller. Attach that
Equipment to that unit or detach that Equipment from that unit. Draw 1."): two target slots chosen at play - a unit, and
an Equipment its controller controls (same_controller_as, Core 355.9); attach or detach chosen as it resolves (the
eff_120 choose_option shape); a detach of the chosen card from the chosen unit does nothing unless it is attached there
(Core 436.1.a).

  A1 attach        p1's u3 and p1's free Equipment, attach chosen: attached to u3; p1 draws 1
  A2 detach        p1's Equipment on u1 with u1, detach chosen: detached (no longer on u1); p1 draws 1
  A3 elsewhere     the Equipment on u1 chosen with u3, detach chosen: nothing detached; p1 still draws
  A4 controllers   p1's u3 with p2's Equipment: refused as it is played (target_controller_differs)
  A5 theirs        p2's unit with p2's Equipment: legal (the same controller, not the caster's), attached
  A6 asked         no option made: the resolution asks p1 (option_selection_required) attach or detach
  C1 apart         played on the Chain on p2's unit and p2's Equipment; a response takes the unit (gain_control,
                   recall): as it resolves the controllers differ - the attach is ignored by name
                   (target_controller_differs_now, Core 359.3.e.2), not re-chosen; the Draw still runs
  C2 apart, detach the same with the Equipment on the unit and detach chosen: still attached; the Draw runs
  C3 restored      the response takes the unit and gives it back: the same controller again, legal (359.3.e.3) -
                   attached; the Draw runs
  G  grammar       the card's text lowers to exactly the four instructions; near misses do not
  V  validation    same_controller_as naming its own decision, and a chosen detach with no `from`, do not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXT = ("Choose a unit and an Equipment with the same controller. Attach that Equipment to that unit or detach that "
        "Equipment from that unit. Draw 1.")
errors: list[str] = []


def lowered():
    return CG.compile_clause(TEXT, CG.load_grammar()).get("program_effects")


def board():
    s = base_state()
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"]}
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("u3")
    for oid, owner, host in (("eq-free", "p1", None), ("eq-on", "p1", "u1"), ("eq-p2", "p2", None)):
        s["objects"][oid] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False, "tags": ["Equipment"], **({"attached_to": host} if host else {})}
        (s["battlefields"]["bf1"]["objects"] if host else s["players"][owner]["zones"]["base"]).append(oid)
    return s


def program(effects):
    bound = [{**e, "player": "p1"} if e.get("player") == "$controller" else copy.deepcopy(e) for e in effects]
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "angle", "controller": "p1", "effects": bound}


def decisions(s, unit, card, option=None):
    out = [{"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [oid],
            "selection_identities": {oid: object_identity(s, oid)}} for ref, oid in (("u", unit), ("eq", card))]
    if option:
        out.append({"decision_id": "attach-or-detach", "stage": "resolution", "kind": "option_selection",
                    "controller": "p1", "value": option})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": out}


def resolve(s, effects, unit, card, option=None):
    return apply_program(s, program(effects), decisions=decisions(s, unit, card, option))


def hand(s):
    return len(s["players"]["p1"]["zones"]["hand"])


def main() -> int:
    effects = lowered()
    ops = [e.get("op") for e in effects or []]
    if ops != ["choose_option", "attach", "detach", "draw"] or effects[1]["object_target"].get("same_controller_as") != "u":
        errors.append(f"G grammar: {effects}")
        return report()
    for near in ("Choose a unit and an Equipment. Attach that Equipment to that unit or detach that Equipment from that "
                 "unit. Draw 1.",
                 "Choose a unit and an Equipment with the same controller. Attach that Equipment to that unit. Draw 1."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == \
                "choose_a_unit_and_an_equipment_with_the_same_controller_attach_or_detach_draw_n":
            errors.append(f"G grammar: the near miss {near!r} parsed")
    if validate_program(program(effects)):
        errors.append(f"V: {validate_program(program(effects))[:2]}")
    s = board()
    done = resolve(s, effects, "u3", "eq-free", "attach")
    after = done.get("next_state") or {}
    if not done.get("committed") or after["objects"]["eq-free"].get("attached_to") != "u3" or hand(after) != hand(s) + 1:
        errors.append(f"A1 attach: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    done = resolve(s, effects, "u1", "eq-on", "detach")
    after = done.get("next_state") or {}
    if not done.get("committed") or after["objects"]["eq-on"].get("attached_to") or hand(after) != hand(s) + 1:
        errors.append(f"A2 detach: {done.get('reason_code')} {done.get('reason') or done.get('errors')} "
                      f"{after.get('objects', {}).get('eq-on')}")
    done = resolve(s, effects, "u3", "eq-on", "detach")
    after = done.get("next_state") or {}
    if not done.get("committed") or after["objects"]["eq-on"].get("attached_to") != "u1" or hand(after) != hand(s) + 1:
        errors.append(f"A3 elsewhere: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-as", "actor": "p1", "card": "c1",
            "chain_item": {"id": "spell-as", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}}, "effect_program_id": "angle",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    s2 = copy.deepcopy(s)
    s2["players"]["p1"]["zones"]["main_deck"].remove("c1")
    s2["players"]["p1"]["zones"]["hand"].append("c1")
    s2["objects"]["c1"].update({"kind": "spell", "printed_cost": {"energy": 0, "power": {}}})
    mixed = PT.play_card(fixture(), s2, decl, engine_decisions=decisions(s2, "u3", "eq-p2"), effect_program=program(effects))
    if mixed.get("committed") or mixed.get("reason_code") != "target_controller_differs":
        errors.append(f"A4 controllers: {mixed.get('committed')} {mixed.get('reason_code')}")
    same = PT.play_card(fixture(), s2, decl, engine_decisions=decisions(s2, "u2", "eq-p2"), effect_program=program(effects))
    if not same.get("committed"):
        errors.append(f"A5 theirs: {same.get('reason_code')} {same.get('reason')}")
    else:
        done = resolve(s, effects, "u2", "eq-p2", "attach")
        if not done.get("committed") or done["next_state"]["objects"]["eq-p2"].get("attached_to") != "u2":
            errors.append(f"A5 theirs: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    chain_cases(effects, decl, s2)
    asked = resolve(s, effects, "u3", "eq-free")
    if asked.get("committed") or asked.get("reason_code") != "option_selection_required":
        errors.append(f"A6 asked: {asked.get('committed')} {asked.get('reason_code')}")
    bad = copy.deepcopy(effects)
    bad[1]["object_target"]["same_controller_as"] = "eq"
    if not validate_program(program(bad)):
        errors.append("V: same_controller_as naming its own decision validated")
    bad = copy.deepcopy(effects)
    del bad[2]["from"]
    if not validate_program(program(bad)):
        errors.append("V: a chosen detach with no from validated")
    return report()


def on_the_chain(effects, decl, start, response, option):
    """C1-C3 (GPT's A2 review, blocker 1): Angle Shot played for real on p2's u2 (moved to bf1, contested) and p2's
    Equipment, finalized; a response applied while it waits on the Chain; both pass; it resolves. Returns
    (the state before it resolves, the resolution)."""
    import rules_core as RC
    from resolution_bridge import resolve_with_program
    s = copy.deepcopy(start)
    s["players"]["p2"]["zones"]["base"].remove("u2")
    s["battlefields"]["bf1"]["objects"].append("u2")
    s["battlefields"]["bf1"].update(contested=True, contested_by="p2")
    p = program(effects)
    played = PT.play_card(fixture(), s, decl, engine_decisions=decisions(s, "u2", "eq-p2"), effect_program=p)
    if not played.get("committed"):
        return None, played
    t, state = played["next_timing_state"], played["next_effect_state"]
    if RC.next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = RC.finalize_oldest_pending(t)["next_state"]
    for effects_now in response:
        got = apply_program(state, {**p, "program_id": "response", "controller": "p1", "effects": effects_now})
        if not got.get("committed"):
            return None, got
        state = got["next_state"]
    for actor in ("p1", "p2"):
        t = RC.pass_priority(t, actor).get("next_state", t)
    return state, resolve_with_program(t, "spell-as", state, p, engine_decisions=decisions(state, "u2", "eq-p2", option))


def chain_cases(effects, decl, s2) -> None:
    """Core 359.3.e.2: "with the same controller" still holds as Angle Shot resolves, or the attach / detach is ignored
    (359.3.e.5, 359.3.e.6) and never re-chosen; its Draw still runs. Apart and then the same again: legal (359.3.e.3)."""
    take = [{"op": "gain_control", "effect_id": "take", "object_id": "u2", "player": "p1"},
            {"op": "recall", "effect_id": "back", "object_id": "u2"}]
    give = [{"op": "gain_control", "effect_id": "give", "object_id": "u2", "player": "p2"}]
    attached = copy.deepcopy(s2)
    attached["objects"]["eq-p2"]["attached_to"] = "u2"
    for label, start, response, option, want_on in (
            ("C1 apart, attach", s2, [take], "attach", None),
            ("C2 apart, detach", attached, [take], "detach", "u2"),
            ("C3 apart then the same", s2, [take, give], "attach", "u2")):
        before, done = on_the_chain(effects, decl, start, response, option)
        if before is None or not done.get("committed"):
            errors.append(f"{label}: {done.get('reason_code') or done.get('stage')} {done.get('reason') or done.get('errors')}")
            continue
        after = done["next_effect_state"]
        apart = before["objects"]["u2"]["controller"] != before["objects"]["eq-p2"]["controller"]
        if apart != label.startswith(("C1", "C2")):
            errors.append(f"{label}: the response left the controllers {'apart' if apart else 'the same'}")
        if after["objects"]["eq-p2"].get("attached_to") != want_on:
            errors.append(f"{label}: the Equipment is attached to {after['objects']['eq-p2'].get('attached_to')!r}, "
                          f"not {want_on!r}")
        if hand(after) != hand(before) + 1:
            errors.append(f"{label}: the Draw did not run ({hand(before)} -> {hand(after)})")
        effect_trace = ((done.get("trace") or {}).get("effect") or {})
        effect_trace = effect_trace.get("trace") if isinstance(effect_trace, dict) else effect_trace
        ignored = [e for e in effect_trace or [] if isinstance(e, dict) and e.get("reason") == "target_controller_differs_now"]
        if apart and not ignored and label.startswith("C1"):
            errors.append(f"{label}: the attach was not ignored by name (target_controller_differs_now)")


def report() -> int:
    if errors:
        print("attach-or-detach checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("attach-or-detach checks passed: a unit and an Equipment of its controller chosen at play; attach or detach "
          "chosen as it resolves, a detach from a unit it is not on doing nothing; then the draw; different controllers "
          "refused at play, and read again as it resolves on the Chain (apart: ignored, the Draw kept; the same again: "
          "legal); validated (A1-A6, C1-C3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
