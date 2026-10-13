#!/usr/bin/env python3
"""A tied combat's result replaced: every unit still there recalled (package 11, Symbol of the Solari: "If a combat where
you are the attacker ends in a tie, recall ALL units instead.").

GPT 2026-10-08 (package 10 ruling 14), affirmed 2026-10-12: the result is read after combat damage and the Combat Cleanup;
under Core 466.3.d a tie is No Result - both players still with units there, neither, or attackers recalled in step 3d
because defenders remained. "ALL units" are the units still at that Battlefield. A permanent's field combat_tie_replacement
{mode: recall_all_units, when: controller_is_attacker} is read by combat.determine_combat_result: while its controller is
the combat's attacker and it is on the board, a tie recalls every unit still at the Battlefield, either side's, to its
controller's Base (Core 455; not a Move, 456.1), and no Combat is staged again.

  T1 tie (3d recall)   p1 attacks with the gear in its Base, both units survive damage: the attacker is recalled in the
                       Cleanup; the result recalls the defender too; nobody is left, the Battlefield ends uncontrolled
  T2 no gear           the same combat without it: the defender stays and keeps the Battlefield
  T3 defender's gear   p2 controls it and defends: nothing changes
  T4 a winner          p1's attacker kills the defender: not a tie, nothing is recalled
  T5 neither           both die: a tie with nobody to recall; nothing else happens
  T6 off the board     the gear in p1's trash: nothing changes
  T7 both remain       a both-remain No Result with the gear: both units recalled, no Combat staged again
  V  shape / grammar   only the one shape validates; the printed sentence lowers to it; the near misses do not

    python skill/scripts/check_combat_tie_recall_all.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from battlefield_control import resolve_battlefield_control  # noqa: E402
from check_combat_damage_assignment import closed_combat  # noqa: E402
from combat import assign_combat_damage, close_combat, combat_cleanup, deal_combat_damage, determine_combat_result  # noqa: E402
from effect_ir import COMBAT_TIE_RECALL_ALL, find_location, validate_state  # noqa: E402

errors: list[str] = []
GEAR = {"owner": None, "controller": None, "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
        "exhausted": False, "combat_tie_replacement": dict(COMBAT_TIE_RECALL_ALL)}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def with_gear(effect, controller, zone="base"):
    e = copy.deepcopy(effect)
    e["objects"]["solari"] = {**copy.deepcopy(GEAR), "owner": controller, "controller": controller}
    e["players"][controller]["zones"][zone].append("solari")
    return e


def through_cleanup(timing, effect):
    a = assign_combat_damage(timing, effect)
    d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"]) if a.get("committed") else {}
    c = combat_cleanup(d["next_timing_state"], d["next_effect_state"]) if d.get("committed") else {}
    if not c.get("committed"):
        return None, f"{a.get('reason_code')} {d.get('reason_code')} {c.get('reason_code')} {c.get('reason')}"
    t = copy.deepcopy(c["next_timing_state"])
    t["chain"] = {"initiated_by": None, "items": [], "consecutive_passes": []}
    return (t, c["next_effect_state"]), None


def at(state, oid):
    loc = find_location(state, oid)
    return None if loc is None else (f"battlefield:{loc[1]}" if loc[0] == "battlefield" else f"{loc[1]}:{loc[2]}")


def survive(gear_for=None, zone="base"):
    """u1 (p1, 5) attacks d1 (p2, 6) at bf1; a Prevent 5 on u1, so both survive the damage."""
    t, e = closed_combat([("d1", {"might": 6})], attacker_might=5)
    e["replacement_effects"] = [{"replacement_id": "u1-ward", "controller": "p1", "source_object": "u1", "mode": "reduce_damage",
                                 "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 5,
                                 "target_object_id": "u1"}]
    if gear_for:
        e = with_gear(e, gear_for, zone)
    return through_cleanup(t, e)


def main() -> int:
    # T1 / T2 / T3 / T6 on the tie by a 3d recall
    for label, gear_for, zone, want_d1, replaced in (("T1 tie (3d recall)", "p1", "base", "p2:base", True),
                                                       ("T2 no gear", None, "base", "battlefield:bf1", False),
                                                       ("T3 defender's gear", "p2", "base", "battlefield:bf1", False),
                                                       ("T6 off the board", "p1", "trash", "battlefield:bf1", False)):
        got, why = survive(gear_for, zone)
        if got is None:
            fail(label, why)
            continue
        r = determine_combat_result(*got)
        if not r.get("committed"):
            fail(label, f"{r.get('reason_code')} {r.get('reason')}")
            continue
        res = r["next_timing_state"]["combat"]["result"]
        e = r["next_effect_state"]
        if at(e, "d1") != want_d1 or at(e, "u1") != "p1:base" or bool(res.get("tie_replaced_by")) != replaced \
                or res.get("outcome") != "no_result":
            fail(label, f"d1 at {at(e, 'd1')}, u1 at {at(e, 'u1')}, result {res}")
        if replaced:
            held = copy.deepcopy(e); held["mode"] = {"victory_score": 8}
            rc = resolve_battlefield_control(r["next_timing_state"], held)
            closed = close_combat(rc["next_timing_state"], rc["next_effect_state"]) if rc.get("committed") else {}
            if not closed.get("committed") or closed["next_effect_state"]["battlefields"]["bf1"].get("controller") is not None \
                    or closed["next_timing_state"].get("combat"):
                fail(label, f"the Battlefield did not end uncontrolled with nothing staged: {rc.get('reason_code')} "
                            f"{closed.get('reason_code')} {(closed.get('next_effect_state') or {}).get('battlefields', {}).get('bf1')}")
    # T4 a winner
    t, e = closed_combat([("d1", {"might": 3})], attacker_might=5)
    got, why = through_cleanup(t, with_gear(e, "p1"))
    r = determine_combat_result(*got) if got else {}
    if not r.get("committed") or r["next_timing_state"]["combat"]["result"].get("outcome") != "win" \
            or at(r["next_effect_state"], "u1") != "battlefield:bf1":
        fail("T4 a winner", why or f"{r.get('reason_code')} {(r.get('next_timing_state') or {}).get('combat', {}).get('result')}")
    # T5 neither
    t, e = closed_combat([("d1", {"might": 5})], attacker_might=5)
    got, why = through_cleanup(t, with_gear(e, "p1"))
    r = determine_combat_result(*got) if got else {}
    res = (r.get("next_timing_state") or {}).get("combat", {}).get("result") or {}
    if not r.get("committed") or res.get("reason") != "neither_remains" or res.get("recalled_all") != [] \
            or r["next_effect_state"]["objects"] != got[1]["objects"]:
        fail("T5 neither", why or f"{r.get('reason_code')} {res}")
    # T7 both remain (a crafted state, as check_combat_resolution builds it)
    got, why = survive("p1")
    if got:
        bt, be = copy.deepcopy(got[0]), copy.deepcopy(got[1])
        bt["combat"]["cleanup"]["recalled"] = []
        be["players"]["p1"]["zones"]["base"].remove("u1"); be["battlefields"]["bf1"]["objects"].append("u1")
        be["objects"]["u1"]["combat_designation"] = {"combat_id": bt["combat"]["combat_id"], "role": "attacker"}
        r = determine_combat_result(bt, be)
        res = (r.get("next_timing_state") or {}).get("combat", {}).get("result") or {}
        if not r.get("committed") or res.get("restage_required") or sorted(res.get("recalled_all") or []) != ["d1", "u1"] \
                or at(r["next_effect_state"], "u1") != "p1:base" or at(r["next_effect_state"], "d1") != "p2:base":
            fail("T7 both remain", f"{r.get('reason_code')} {res}")
    else:
        fail("T7 both remain", why)
    # V
    bad = with_gear(survive()[0][1], "p1")
    bad["objects"]["solari"]["combat_tie_replacement"] = {"mode": "recall_all_units", "when": "always"}
    if not validate_state(bad):
        fail("V shape", "another shape validated")
    grammar = cg.load_grammar()
    card = cg.compile_card([{"text": "If a combat where you are the attacker ends in a tie, recall ALL units instead."}], grammar)
    fields = (card.get("passive") or {}).get("object_fields") or {}
    if card.get("unsupported_clauses") or fields.get("combat_tie_replacement") != COMBAT_TIE_RECALL_ALL:
        fail("V grammar", f"{card.get('unsupported_clauses')} {fields}")
    for near in ("If a combat where you are the defender ends in a tie, recall ALL units instead.",
                 "If a combat ends in a tie, recall ALL units instead."):
        if not cg.compile_card([{"text": near}], grammar).get("unsupported_clauses"):
            fail("V grammar", f"a near miss parsed: {near}")
    if errors:
        print("FAILED: a tied combat recalls all units")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: with its controller attacking, a tie (3d recall, both or neither remaining) recalls every unit still at the "
          "Battlefield, which ends uncontrolled and is not staged again; without it, as the defender's, off the board, or "
          "with a winner nothing changes; one shape, lowered from the printed sentence only (T1-T7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
