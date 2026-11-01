#!/usr/bin/env python3
"""
Regression gate: two more base costs of a triggered ability, a target by its Combat designation, and a Legend chosen in
its Legend Zone (2026-10-29).

  C1 power_any paid     "you may pay [A][A][A][A] to score 1 point": four Power of any Domains paid as the ability is
                        finalized (Core 383.3.b.1) from two Domains; resolved, the point is gained
  C2 power_any short    three Power: the cost cannot be paid - the ability leaves the Chain (203.3), no point
  C3 kill_this paid     "you may kill me to draw 1": the source is killed as the cost (Core 429.1.a.1) - in its owner's
                        trash after finalization; resolved, the draw happens
  C4 kill_this gone     the source not on the board: the cost cannot be paid
  T1 combat_role        "an attacking unit": a Unit designated Attacker is a legal target, a Defender and an undesignated
                        Unit are not (Core 466.2.c.3)
  T2 legend             "a legend": a Legend in its Legend Zone is a legal target of {kind legend, include_legend_zone}; a
                        Unit is not; "your legend" with controller_relation friendly refuses the opponent's
  V  shape              power_any of 0, kill_this naming another object, combat_role off the board or of another value,
                        include_legend_zone with kind unit: refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_trigger_cost import cost, pending, program, resolve  # noqa: E402
from resolution_bridge import finalize_trigger  # noqa: E402

errors: list[str] = []
PAYMENT = {"add_window_closed": True, "confirmed_by": "harness"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def nexus_board(power):
    state = base_state()
    state["objects"]["nx"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("nx")
    state["players"]["p1"]["resources"] = {"energy": 0, "power": dict(power)}
    state["mode"] = {"victory_score": 8}
    return state


NEXUS = program("nx-effects", "nx", [cost({"kind": "power_any", "amount": 4}),
                                     {"op": "gain_point", "effect_id": "pt", "player": "p1", "amount": 1}])
FAN = program("fan-effects", "fan", [cost({"kind": "kill_this", "object_id": {"object_ref": "program_source"}}),
                                     {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])


def run(state, prog, source):
    reg = {prog["program_id"]: prog}
    fin = finalize_trigger(pending(state, source, prog), state, reg, None, perform_optional_trigger=True,
                           pay_trigger_cost=True, payment_context=PAYMENT)
    return fin, reg


def main() -> int:
    for label, effects in (("power_any 0", [cost({"kind": "power_any", "amount": 0}), NEXUS["effects"][1]]),
                           ("kill_this another object", [cost({"kind": "kill_this", "object_id": "u1"}), FAN["effects"][1]])):
        if not IR.validate_program(program("bad", "nx", effects)):
            fail("V shape", f"{label} validated")
    # C1, C2
    s = nexus_board({"fury": 2, "calm": 2})
    fin, reg = run(s, NEXUS, "nx")
    if not fin.get("committed") or fin.get("removed"):
        fail("C1 power_any paid", f"not finalized: {fin.get('reason')} {fin.get('transition')}")
    else:
        left = fin["next_effect_state"]["players"]["p1"]["resources"]["power"]
        if sum(left.values()) != 0:
            fail("C1 power_any paid", f"Power left after paying four: {left}")
        done = resolve(fin, reg, "nx-trig")
        if not done.get("committed") or done["next_effect_state"]["players"]["p1"].get("points", 0) != 1:
            fail("C1 power_any paid", f"no point: {done.get('reason')}")
    short = nexus_board({"fury": 3})
    fin, _reg = run(short, NEXUS, "nx")
    if not fin.get("removed") or (fin.get("next_effect_state") or short)["players"]["p1"].get("points", 0):
        fail("C2 power_any short", f"{fin.get('reason')} {fin.get('transition')}")
    # C3, C4
    s = base_state()
    s["objects"]["fan"] = unit("p1")
    s["players"]["p1"]["zones"]["base"].append("fan")
    s["objects"]["dk"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["main_deck"].insert(0, "dk")
    fin, reg = run(s, FAN, "fan")
    if not fin.get("committed") or fin.get("removed"):
        fail("C3 kill_this paid", f"not finalized: {fin.get('reason')} {fin.get('transition')}")
    else:
        after = fin["next_effect_state"]
        if "fan" not in after["players"]["p1"]["zones"]["trash"]:
            fail("C3 kill_this paid", f"the source is at {IR.find_location(after, 'fan')}, not in the trash")
        hand = len(after["players"]["p1"]["zones"]["hand"])
        done = resolve(fin, reg, "fan-trig")
        if not done.get("committed") or len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != hand + 1:
            fail("C3 kill_this paid", f"the draw did not happen: {done.get('reason')}")
    gone = copy.deepcopy(s)
    pend = pending(gone, "fan", FAN)
    gone["players"]["p1"]["zones"]["base"].remove("fan")
    gone["players"]["p1"]["zones"]["trash"].append("fan")
    fin = finalize_trigger(pend, gone, {FAN["program_id"]: FAN}, None, perform_optional_trigger=True, pay_trigger_cost=True,
                           payment_context=PAYMENT)
    if not fin.get("removed"):
        fail("C4 kill_this gone", f"{fin.get('reason')} {fin.get('transition')}")
    # T1
    s = base_state()
    for oid, role in (("att", "attacker"), ("dfn", "defender"), ("idle", None)):
        s["objects"][oid] = unit("p2", **({"combat_designation": {"combat_id": "cb1", "role": role}} if role else {}))
        s["battlefields"]["bf1"]["objects"].append(oid)
    seen = {oid: IR.evaluate_target(s, {"object_id": oid, "chosen_zone_class": "board", "kind": "unit",
                                        "combat_role": "attacker", "bound_identity": IR.object_identity(s, oid)}, "p1")[0]
            for oid in ("att", "dfn", "idle")}
    if seen != {"att": True, "dfn": False, "idle": False}:
        fail("T1 combat_role", f"attacking unit legal targets: {seen}")
    for bad in ({"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "combat_role": "blocker"},
                {"decision_ref": "t", "chosen_zone_class": "non_board", "kind": "unit", "combat_role": "attacker"}):
        if not IR._selector_errors(bad):
            fail("V shape", f"combat_role selector validated: {bad}")
    # T2
    s = base_state()
    for oid, owner in (("lg1", "p1"), ("lg2", "p2")):
        s["objects"][oid] = {"owner": owner, "controller": owner, "kind": "legend", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": True}
        s["players"][owner]["zones"].setdefault("legend_zone", []).append(oid)
    legend = {"chosen_zone_class": "board", "include_legend_zone": True, "kind": "legend"}
    ok = {oid: IR.evaluate_target(s, {**legend, "object_id": oid, "bound_identity": IR.object_identity(s, oid)}, "p1")[0]
          for oid in ("lg1", "lg2", "u1")}
    if ok != {"lg1": True, "lg2": True, "u1": False}:
        fail("T2 legend", f"a legend: {ok}")
    yours = {oid: IR.evaluate_target(s, {**legend, "controller_relation": "friendly", "object_id": oid,
                                         "bound_identity": IR.object_identity(s, oid)}, "p1")[0] for oid in ("lg1", "lg2")}
    if yours != {"lg1": True, "lg2": False}:
        fail("T2 legend", f"your legend: {yours}")
    if not IR._selector_errors({"decision_ref": "t", "chosen_zone_class": "board", "include_legend_zone": True, "kind": "unit"}):
        fail("V shape", "include_legend_zone with kind unit validated")
    if IR._selector_errors({"decision_ref": "t", **legend}):
        fail("V shape", f"the legend selector is refused: {IR._selector_errors({'decision_ref': 't', **legend})}")
    if errors:
        print("FAILED: set 2 trigger costs and targets")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a trigger's base cost of any-Domain Power or of killing its own source is paid as it is finalized, or the "
          "ability leaves the Chain (383.3.b.1, 203.3, 429.1.a.1); an attacking unit is chosen by its designation "
          "(466.2.c.3); a Legend is chosen in its Legend Zone; malformed shapes are refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
