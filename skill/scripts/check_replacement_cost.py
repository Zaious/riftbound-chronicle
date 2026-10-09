#!/usr/bin/env python3
"""An optional Replacement Effect that costs something to apply (package 10, Sett - The Boss and Unlicensed Armory; GPT
2026-10-08 ruling 12).

"You may pay X to ... instead": the replacement is its controller's option, and choosing it pays X as it applies - Power
of a Domain, Power of any Domain, exhausting its own source. Declined, nothing is paid and the event happens; unpayable
now, it is no option at all (the event happens, nothing is asked). Power of any Domain comes from the one Domain that can
pay it; when the payer could choose between Domains, that choice is not modelled and is refused by name.

  S1 Sett, yes      a buffed friendly unit killed, the replacement chosen: its buff spent, recalled to p1's Base
                    exhausted; one Power paid; the card exhausted
  S2 Sett, no       declined: the unit dies; nothing paid; the card ready
  S3 unbuffed       an unbuffed friendly unit: dies, nothing asked
  S4 unpayable      the card already exhausted, or p1's pool empty: dies, nothing asked
  S5 two Domains    the pool could pay from two Domains: refused by name (replacement_cost_domain_choice_unsupported)
  L  Legend         the source a Legend in p1's Legend Zone (Sett - The Boss is one): the replacement works there and
                    "exhaust me" exhausts it; the Legend in Banishment: the replacement is no longer there
  A1 Armory, yes    the granted replacement on the chosen unit, chosen: one Fury paid; healed, exhausted, recalled
  A2 Armory, no     declined, or no Fury: the unit dies
  V  shape          a cost on a replacement that is not optional, or exhaust_source on a granted one, does not validate
  G  grammar        both lines lower to exactly these shapes; near misses do not lower to the rows

    python skill/scripts/check_replacement_cost.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, hash_value, validate_state  # noqa: E402

errors: list[str] = []
SETT = "When a buffed unit you control would die, you may pay :rb_rune_rainbow: and exhaust me to spend its buff and recall it exhausted instead."
ARMORY = "Choose a friendly unit. The next time it would die this turn, you may pay :rb_rune_fury: to heal it, exhaust it, and recall it instead."


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def bind(value, bindings):
    if isinstance(value, dict):
        return {k: bind(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    return bindings.get(value, value) if isinstance(value, str) else value


def board(power=None, sett_exhausted=False, buffed=True):
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["sett"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4, "might_modifiers": [],
                                "damage": 0, "exhausted": sett_exhausted}
    state["objects"]["u1"]["damage"] = 1
    if buffed:
        state["objects"]["u1"]["buffed"] = True
    state["players"]["p1"]["zones"]["base"] = ["sett"]
    state["battlefields"]["bf1"]["objects"] = ["u1"]
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["players"]["p1"]["resources"] = {"energy": 0, "power": dict(power if power is not None else {"chaos": 1})}
    return state


def with_sett(state, lowered):
    entries = copy.deepcopy(lowered["passive"]["state_lists"]["replacement_effects"])
    state["replacement_effects"] = bind(entries, {"$clause_id": "sett-r", "$controller": "p1", "$source_object": "sett"})
    return state


def kill(state, choice=None, rid="sett-r"):
    decisions = None
    if choice is not None:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
            {"decision_id": "rc", "stage": "resolution", "kind": "replacement_choice", "controller": "p1",
             "value": {rid: {"k": choice}}}]}
    prog = program("kill-u1", {"op": "kill", "effect_id": "k", "object_id": "u1"})
    prog["controller"] = "p2"
    return apply_program(state, prog, decisions=decisions)


def where(state, oid):
    for p, pl in state["players"].items():
        for z, ids in pl["zones"].items():
            if oid in ids:
                return f"{p}:{z}"
    for b, bf in state["battlefields"].items():
        if oid in bf["objects"]:
            return f"battlefield:{b}"
    return None


def main() -> int:
    grammar = cg.load_grammar()
    sett = cg.compile_clause(SETT, grammar)
    armory = cg.compile_clause(ARMORY, grammar)
    if sett.get("unsupported") or armory.get("unsupported"):
        fail("G grammar", f"{sett.get('reason')} {armory.get('reason')}")
        return report()
    start = with_sett(board(), sett)
    if validate_state(start):
        fail("board", validate_state(start)[:2])
        return report()
    # S1
    yes = kill(start, True)
    after = yes.get("next_state") or {}
    if not yes.get("committed") or where(after, "u1") != "p1:base" or after["objects"]["u1"].get("buffed") \
            or after["objects"]["u1"]["exhausted"] is not True or after["objects"]["sett"]["exhausted"] is not True \
            or after["players"]["p1"]["resources"]["power"].get("chaos", 0) != 0:
        fail("S1 Sett, yes", f"{yes.get('reason') or yes.get('errors')} u1 at {where(after, 'u1') if after else None}")
    # S2
    no = kill(start, False)
    after = no.get("next_state") or {}
    if not no.get("committed") or where(after, "u1") != "p1:trash" or after["objects"]["sett"]["exhausted"] \
            or after["players"]["p1"]["resources"]["power"].get("chaos", 0) != 1:
        fail("S2 Sett, no", f"{no.get('reason') or no.get('errors')}")
    asked = kill(start)
    if asked.get("committed") or not asked.get("replacement_decision_required"):
        fail("S2 Sett, no", f"no choice given and none asked: {asked.get('reason')}")
    # S3, S4: nothing asked, the unit dies
    for label, state in (("S3 unbuffed", with_sett(board(buffed=False), sett)),
                         ("S4 card exhausted", with_sett(board(sett_exhausted=True), sett)),
                         ("S4 empty pool", with_sett(board(power={}), sett))):
        died = kill(state)
        if not died.get("committed") or where(died["next_state"], "u1") != "p1:trash":
            fail(label, f"{died.get('reason') or died.get('errors')}")
    # S5
    two = kill(with_sett(board(power={"chaos": 1, "fury": 1}), sett), True)
    if two.get("committed") or not two.get("unsupported") or "replacement_cost_domain_choice_unsupported" not in str(two.get("reason")):
        fail("S5 two Domains", f"committed={two.get('committed')} {two.get('reason')}")
    # L: the source a Legend in its Legend Zone (Core 107.4)
    legend = board()
    legend["objects"]["sett"]["kind"] = "legend"
    legend["players"]["p1"]["zones"]["base"].remove("sett")
    legend["players"]["p1"]["zones"]["legend_zone"] = ["sett"]
    legend = with_sett(legend, sett)
    if validate_state(legend):
        fail("L Legend", f"a Legend's replacement in its Legend Zone does not validate: {validate_state(legend)[:2]}")
    else:
        saved = kill(legend, True)
        after = saved.get("next_state") or {}
        if not saved.get("committed") or where(after, "u1") != "p1:base" or after["objects"]["sett"]["exhausted"] is not True:
            fail("L Legend", f"{saved.get('reason') or saved.get('errors')}")
        gone = copy.deepcopy(legend)
        gone["players"]["p1"]["zones"]["legend_zone"] = []
        gone["players"]["p1"]["zones"]["banishment"].append("sett")
        gone["replacement_effects"] = []
        died = kill(gone)
        if not died.get("committed") or where(died["next_state"], "u1") != "p1:trash":
            fail("L Legend", "with the Legend in Banishment the unit was saved")
    # A1, A2: the granted replacement
    granted_state = board(power={"fury": 1})
    granted_state["objects"]["u1"].pop("buffed")
    grant = copy.deepcopy(armory["program_effects"][0])
    grant.pop("target")
    grant.update({"object_id": "u1", "controller": "p1", "granted_by": "armory-item"})
    made = apply_program(granted_state, program("armory", grant))
    if not made.get("committed"):
        fail("A1 Armory", f"the grant did not commit: {made.get('reason') or made.get('errors')}")
        return report()
    rid = made["next_state"]["replacement_effects"][-1]["replacement_id"]
    saved = kill(made["next_state"], True, rid)
    after = saved.get("next_state") or {}
    if not saved.get("committed") or where(after, "u1") != "p1:base" or after["objects"]["u1"]["damage"] != 0 \
            or after["objects"]["u1"]["exhausted"] is not True or after["players"]["p1"]["resources"]["power"].get("fury", 0) != 0:
        fail("A1 Armory, yes", f"{saved.get('reason') or saved.get('errors')}")
    declined = kill(made["next_state"], False, rid)
    if not declined.get("committed") or where(declined["next_state"], "u1") != "p1:trash":
        fail("A2 Armory, no", f"{declined.get('reason') or declined.get('errors')}")
    broke = copy.deepcopy(made["next_state"])
    broke["players"]["p1"]["resources"]["power"] = {}
    poor = kill(broke)
    if not poor.get("committed") or where(poor["next_state"], "u1") != "p1:trash":
        fail("A2 Armory, no Fury", f"{poor.get('reason') or poor.get('errors')}")
    # V
    rigid = with_sett(board(), sett)
    rigid["replacement_effects"][0]["optional"] = False
    if not validate_state(rigid):
        fail("V not optional", "a cost on a mandatory replacement validated")
    exhausting = copy.deepcopy(made["next_state"])
    exhausting["replacement_effects"][-1]["cost"] = {"exhaust_source": True}
    if not validate_state(exhausting):
        fail("V granted exhaust", "exhaust_source on a granted replacement validated")
    # G
    if sett.get("production_id") != "when_a_buffed_unit_you_control_would_die_you_may_pay_a_and_exhaust_me_to_spend_its_buff_and_recall_it_exhausted_instead":
        fail("G grammar", sett.get("production_id"))
    for near in ("When a buffed unit you control would die, you may pay :rb_rune_rainbow: to recall it instead.",
                 "Choose a friendly unit. The next time it would die this turn, heal it, exhaust it, and recall it instead."):
        got = cg.compile_clause(near, grammar).get("production_id") or ""
        if "you_may_pay" in got:
            fail("G grammar", f"{near!r} lowered to {got}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: replacement cost checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: an optional replacement that costs something - paid as it applies, nothing when declined, no option when "
          "unpayable, a Domain choice refused by name; a Legend's in its Legend Zone (S1-S5, L, A1-A2, V, G)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
