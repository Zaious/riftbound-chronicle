#!/usr/bin/env python3
"""Regression gate (set 2 package A2: Azir - Ascendant, ":rb_rune_calm:: [Action] - Choose a unit you control. Move me to
its location and it to my original location. If it's equipped, you may attach one of its Equipment to me. Use only once
per turn.").

The body: Tideturner's two Moves (check_swap_locations) on a unit its controller controls, then an attach of one Equipment
attached to that unit to the source - "you may" decided as it resolves (Core 355.12), the Equipment picked then when there
are several (355.10); none attached, nothing happens (436.1.a). "Use only once per turn.": a use restriction (377.2.b)
read from the ledger of this object's activations of the ability this turn (ability_uses_this_turn_below).

  A1 swap+attach  z (the source) in p1's Base, f1 at bf1 carrying eq1: z goes to bf1, f1 to p1's Base, eq1 attached to z
  A2 two          f1 carries eq1 and eq2: the pick is asked (card_selection, both candidates); picking eq2 attaches it
  A3 declined     "you may" declined: eq1 stays on f1
  A4 none         f1 carries nothing: the attach does nothing
  A5 asked        no answer: the optional is asked first, as it resolves
  A6 not mine     the choice admits a unit its controller controls, not an enemy unit
  A7 unasked      f1 carries nothing and no answer is given: the condition does not hold, so the "you may" is not
                  asked; the swap stands and the ability resolves (the attach a no_op)
  U1 once         activated once this turn: committed, the ledger has it; a second activation is refused
                  (activation_condition_not_met); next turn it may be activated again; another object of the same card
                  (a new identity) is not limited by the first one's use
  G  grammar      the body lowers to the two Moves and the attach; near misses do not
  V               an attach with pick but `to` other than the source, or no `from`, does not validate
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
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, evaluate_target, hash_value,  # noqa: E402
                       object_identity, validate_program)

TEXT = ("Choose a unit you control. Move me to its location and it to my original location. If it's equipped, you may "
        "attach one of its Equipment to me.")
PRODUCTION = "choose_a_unit_you_control_swap_with_me_attach_one_of_its_equipment_to_me"


def unit(owner, might=2, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def gear(owner, host=None):
    return {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, "tags": ["Equipment"], **({"attached_to": host} if host else {})}


def board(equipment=("eq1",)):
    s = base_state()
    s["objects"]["z"] = unit("p1", 3)
    s["objects"]["f1"] = unit("p1", 2)
    s["players"]["p1"]["zones"]["base"].append("z")
    s["battlefields"]["bf1"]["objects"] = [o for o in s["battlefields"]["bf1"]["objects"]] + ["f1"]
    for oid in equipment:
        s["objects"][oid] = gear("p1", "f1")
        s["battlefields"]["bf1"]["objects"].append(oid)
    for oid in list(s["battlefields"]["bf1"]["objects"]):
        if s["objects"][oid]["controller"] != "p1":
            s["battlefields"]["bf1"]["objects"].remove(oid)
            s["players"][s["objects"][oid]["controller"]]["zones"]["base"].append(oid)
    s["battlefields"]["bf1"]["controller"] = "p1"
    return s


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "azir", "controller": "p1", "source_object": "z", "effects": copy.deepcopy(effects)}


def run(s, effects, *, chosen="f1", may=True, pick=None):
    out = [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
            "value": [chosen], "selection_identities": {chosen: object_identity(s, chosen)}},
           {"decision_id": "d1", "stage": "play_declaration", "kind": "location_selection", "controller": "p1",
            "value": "battlefield:bf1"},
           {"decision_id": "d2", "stage": "play_declaration", "kind": "location_selection", "controller": "p1",
            "value": "base:p1"}]
    if may is not None:
        out.append({"decision_id": "may-attach", "stage": "resolution", "kind": "optional_choice", "controller": "p1",
                    "value": may})
    if pick:
        out.append({"decision_id": "eq", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                    "value": [pick], "selection_identities": {pick: object_identity(s, pick)}})
    return apply_program(s, program(effects), decisions={"schema_version": "engine-decisions.v1",
                                                         "input_hash": hash_value(s), "decisions": out})


def at(state, oid):
    for p, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if oid in ids:
                return f"{p}:{zone}"
    for b, data in state["battlefields"].items():
        if oid in data["objects"]:
            return b
    return None


def activate(state, card="z", turn=None, n=1):
    s = copy.deepcopy(state)
    if turn:
        s["turn_id"] = turn
    s["players"]["p1"]["resources"] = {"energy": 0, "power": {"calm": 1}}
    prog = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": f"{card}-ability", "controller": "p1", "source_object": card,
            "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]}
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"activate-{card}-{n}", "actor": "p1", "card": card,
            "chain_item": {"id": f"ab-{card}-{n}", "object_kind": "ability", "timing": "action", "ability_kind": "standard"},
            "activation": {"source_object": card, "ability_id": f"{card}:a1"},
            "cost": {"base": {"energy": 0, "power": {"calm": 1}}}, "effect_program_id": prog["program_id"],
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return PT.play_card(fixture(), s, decl, effect_program=prog)


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT, CG.load_grammar())
    effects = got.get("program_effects")
    if got.get("production_id") != PRODUCTION or [e.get("op") for e in effects or []] != \
            ["move_board_object", "move_board_object", "attach"]:
        print(f"azir-ascendant checks FAILED:\n  - G grammar: {got.get('production_id')} {effects}")
        return 1
    for near in ("Choose a unit you control. Move me to its location and it to my original location.",
                 "Choose an enemy unit. Move me to its location and it to my original location. If it's equipped, you may "
                 "attach one of its Equipment to me.",
                 "Choose a unit you control. Move me to its location and it to my original location. Attach one of its "
                 "Equipment to me."):
        if CG.compile_clause(near, CG.load_grammar()).get("production_id") == PRODUCTION:
            errors.append(f"G grammar: the near miss {near!r} parsed")
    if validate_program(program(effects)):
        errors.append(f"V: {validate_program(program(effects))[:2]}")
    s = board()
    done = run(s, effects)
    a = done.get("next_state") or {}
    if not done.get("committed") or (at(a, "z"), at(a, "f1"), a["objects"]["eq1"].get("attached_to"), at(a, "eq1")) \
            != ("bf1", "p1:base", "z", "bf1"):
        errors.append(f"A1 swap+attach: {done.get('reason') or done.get('errors')} "
                      f"{(at(a, 'z'), at(a, 'f1'), (a.get('objects') or {}).get('eq1', {}).get('attached_to')) if a else None}")
    s2 = board(("eq1", "eq2"))
    asked = run(s2, effects)
    if asked.get("committed") or asked.get("decision_ids") != ["eq"] or sorted(asked.get("candidates") or []) != ["eq1", "eq2"]:
        errors.append(f"A2 two: {asked.get('reason_code')} {asked.get('decision_ids')} {asked.get('candidates')}")
    picked = run(s2, effects, pick="eq2")
    a = picked.get("next_state") or {}
    if not picked.get("committed") or a["objects"]["eq2"].get("attached_to") != "z" or a["objects"]["eq1"].get("attached_to") != "f1":
        errors.append(f"A2 two: picked {picked.get('reason') or picked.get('errors')}")
    no = run(s, effects, may=False)
    a = no.get("next_state") or {}
    if not no.get("committed") or a["objects"]["eq1"].get("attached_to") != "f1":
        errors.append(f"A3 declined: {no.get('reason') or no.get('errors')}")
    bare = run(board(()), effects)
    if not bare.get("committed") or [e.get("outcome") for e in bare.get("trace") or []][-1:] != ["no_op"]:
        errors.append(f"A4 none: {bare.get('reason') or bare.get('errors')} {[e.get('outcome') for e in bare.get('trace') or []]}")
    # A7 (GPT's A2 review): not equipped, nothing answered - "If it's equipped" does not hold, so no "you may" is asked;
    # the swap stands and the ability resolves
    unasked = run(board(()), effects, may=None)
    if not unasked.get("committed") or [e.get("outcome") for e in unasked.get("trace") or []] != ["applied", "applied", "no_op"]:
        errors.append(f"A7 not equipped: {unasked.get('reason_code')} {[e.get('outcome') for e in unasked.get('trace') or []]}")
    first = run(s, effects, may=None)
    if first.get("committed") or first.get("decision_ids") != ["may-attach"]:
        errors.append(f"A5 asked: {first.get('reason_code')} {first.get('decision_ids')}")
    s6 = board()
    s6["objects"]["e1"] = unit("p2", 2)
    s6["players"]["p2"]["zones"]["base"].append("e1")
    selector = {k: v for k, v in effects[1]["target"].items() if k != "decision_ref"}
    if evaluate_target(s6, {**selector, "object_id": "e1"}, "p1")[0] or not evaluate_target(s6, {**selector, "object_id": "f1"}, "p1")[0]:
        errors.append("A6 not mine: the choice is not 'a unit you control'")
    bad = copy.deepcopy(effects)
    bad[2]["to"] = "f1"
    if not validate_program(program(bad)):
        errors.append("V: an attach with pick to another object validated")
    bad = copy.deepcopy(effects)
    bad[2].pop("from")
    if not validate_program(program(bad)):
        errors.append("V: an attach with pick and no from validated")
    # U1: once per turn
    u = board()
    u["objects"]["z"]["ability_conditions"] = {"z:a1": {"kind": "ability_uses_this_turn_below", "ability": "z:a1", "count": 1}}
    once = activate(u)
    after = once.get("next_effect_state") or {}
    ledger = ((after.get("players") or {}).get("p1") or {}).get("ability_uses_this_turn") or {}
    if not once.get("committed") or ledger.get(after.get("turn_id", "turn-0")) != [f"{object_identity(u, 'z')}:z:a1"]:
        errors.append(f"U1 once: first {once.get('reason_code')} {once.get('reason')} {ledger}")
    else:
        twice = activate(after, n=2)
        if twice.get("committed") or twice.get("reason_code") != "activation_condition_not_met":
            errors.append(f"U1 once: second {twice.get('committed')} {twice.get('reason_code')}")
        later = activate(after, turn="turn-9", n=3)
        if not later.get("committed"):
            errors.append(f"U1 once: next turn {later.get('reason_code')} {later.get('reason')}")
        fresh = copy.deepcopy(after)
        fresh["objects"]["z"]["identity"] = "z@1"
        again = activate(fresh, n=4)
        if not again.get("committed"):
            errors.append(f"U1 once: a new object refused {again.get('reason_code')}")
    if errors:
        print("azir-ascendant checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("azir-ascendant checks passed: swap with a unit its controller controls, then one of its Equipment attached to "
          "the source (asked, picked among several, declined, none); an enemy unit refused; once per turn by this "
          "object's ledger, again next turn; grammar; validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
