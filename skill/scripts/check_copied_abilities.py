#!/usr/bin/env python3
"""Activating an [Exhaust] ability a permanent has from another one (package 11, Heimerdinger - Inventor: "I have all
[Exhaust] abilities of all friendly legends, units, and gear.").

GPT 2026-10-12 (PACKAGE11 ruling 14): in a copied ability, "me" / "this" is Heimerdinger and its [Exhaust] exhausts
Heimerdinger; the abilities it has follow the board as it is; same-named abilities are separate, but each exhausts
Heimerdinger, so one per readying; costs printed besides [Exhaust] are not dropped. The engine's shape: a permanent's
printed activated abilities (activated_abilities {id: {cost, effect_program_id}}), the card's has_exhaust_abilities_of
kinds, and an activation that names copied_from - play_transaction.copied_ability_problem checks it before anything is
paid.

  C1 copied        hm copies p1's u9's "[1], [Exhaust]: buff me": paid 1 Energy, hm exhausted (u9 not), and as it
                   resolves hm is buffed, u9 is not
  C2 a gear        hm copies p1's gear g9's "[Exhaust]: draw 1": p1 draws
  C3 cost          declared without its [1], or exhausting u9 instead of hm: refused (copied_ability_cost_mismatch)
  C4 not [Exhaust] u8's "[1]: ..." has no [Exhaust]: refused (copied_ability_not_had)
  C5 not friendly  p2's e9's [Exhaust] ability: refused
  C6 gone          u9 in p1's trash: refused - hm no longer has it; a gear arriving gives hm its ability (C2)
  C7 twice         after copying u9's, copying g9's at once: refused - hm is exhausted
  C8 no static     the same activation on a unit without the statement: refused
  C9 program       declaring another program than the ability's: refused (copied_ability_program_mismatch)
  C10 me           the copy's program bound to the original (u9) instead of the card: refused
  V  shape/grammar malformed activated_abilities do not validate; the card's statement lowers to its kinds

    python skill/scripts/check_copied_abilities.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
errors: list[str] = []
STATEMENT = "I have all :rb_exhaust: abilities of all friendly legends, units, and gear."


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(pid, effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": pid, "controller": "p1", "effects": effects}


PROGRAMS = {"u9-a1": program("u9-a1", [{"op": "buff", "effect_id": "b", "object_id": {"object_ref": "program_source"}}]),
            "g9-a1": program("g9-a1", [{"op": "draw", "effect_id": "d", "player": "p1", "count": 1}]),
            "u8-a1": program("u8-a1", [{"op": "draw", "effect_id": "d", "player": "p1", "count": 1}]),
            "e9-a1": program("e9-a1", [{"op": "draw", "effect_id": "d", "player": "p2", "count": 1}])}


def unit(owner, kind="unit", **extra):
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": 2 if kind == "unit" else 0,
            "might_modifiers": [], "damage": 0, "exhausted": False, **extra}


def board(*, static=True, gear=True, u9_gone=False):
    """p1's hm (with the statement) and u9, u8 and gear g9 in p1's Base; p2's e9 in p2's Base."""
    state = base_state()
    hm = unit("p1", **({"has_exhaust_abilities_of": ["legend", "unit", "gear"]} if static else {}))
    state["objects"].update({
        "hm": hm,
        "u9": unit("p1", activated_abilities={"u9:a1": {"cost": {"energy": 1, "exhaust": True}, "effect_program_id": "u9-a1"}}),
        "u8": unit("p1", activated_abilities={"u8:a1": {"cost": {"energy": 1}, "effect_program_id": "u8-a1"}}),
        "g9": unit("p1", "gear", activated_abilities={"g9:a1": {"cost": {"exhaust": True}, "effect_program_id": "g9-a1"}}),
        "e9": unit("p2", activated_abilities={"e9:a1": {"cost": {"exhaust": True}, "effect_program_id": "e9-a1"}})})
    state["players"]["p1"]["zones"]["base"] += ["hm", "u8"] + (["g9"] if gear else []) + ([] if u9_gone else ["u9"])
    if u9_gone:
        state["players"]["p1"]["zones"]["trash"].append("u9")
    if not gear:
        state["players"]["p1"]["zones"]["trash"].append("g9")
    state["players"]["p2"]["zones"]["base"].append("e9")
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return state


def declare(source, ability, *, energy, exhaust="hm", prog=None, play_id="act-1"):
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": RULESET, "play_id": play_id, "actor": "p1", "card": "hm",
            "chain_item": {"id": f"ability-{play_id}", "object_kind": "ability", "timing": "default", "ability_kind": "standard"},
            "activation": {"source_object": "hm", "ability_id": f"hm:copy:{ability}",
                           "copied_from": {"source_object": source, "ability_id": ability}},
            "cost": {"base": {"energy": energy, "power": {}},
                     "additional": [{"cost_id": "tap", "mandatory": True, "payment": {"kind": "exhaust", "object_id": exhaust}}]},
            "effect_program_id": prog or f"{source}-a1", "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def bound(decl, source="hm"):
    """The ability's program as the copy runs it: the original's instructions, its source the card that has the copy."""
    prog = PROGRAMS.get(decl["effect_program_id"])
    return {**prog, "source_object": source} if prog else None


def activate(state, decl, source="hm"):
    return PT.play_card(fixture(), state, decl, effect_program=bound(decl, source))


def resolve(played, decl):
    t = played["next_timing_state"]
    if next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = finalize_oldest_pending(t)["next_state"]
    for actor in ("p1", "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    return resolve_with_program(t, decl["chain_item"]["id"], played["next_effect_state"], bound(decl))


def code(got):
    return "committed" if got.get("committed") else got.get("reason_code")


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    # C1
    decl = declare("u9", "u9:a1", energy=1)
    played = activate(s, decl)
    if not played.get("committed"):
        fail("C1 copied", code(played))
    else:
        e = played["next_effect_state"]
        if not e["objects"]["hm"]["exhausted"] or e["objects"]["u9"]["exhausted"] or e["players"]["p1"]["resources"]["energy"] != 1:
            fail("C1 paid", f"hm {e['objects']['hm']['exhausted']} u9 {e['objects']['u9']['exhausted']} {e['players']['p1']['resources']}")
        done = resolve(played, decl)
        after = done.get("next_effect_state") or {}
        if not done.get("committed") or not after["objects"]["hm"].get("buffed") or after["objects"]["u9"].get("buffed"):
            fail("C1 me", f"{done.get('reason') or done.get('reason_code')} hm buffed "
                          f"{(after.get('objects') or {}).get('hm', {}).get('buffed')}")
        # C7: hm is exhausted now
        again = activate(e, declare("g9", "g9:a1", energy=0, play_id="act-2"))
        if again.get("committed"):
            fail("C7 twice", "a second copy activated with hm exhausted")
    # C2
    decl = declare("g9", "g9:a1", energy=0)
    played = activate(s, decl)
    hand = len(s["players"]["p1"]["zones"]["hand"])
    done = resolve(played, decl) if played.get("committed") else played
    if not done.get("committed") or len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != hand + 1:
        fail("C2 a gear", f"{code(played)} {done.get('reason') or done.get('reason_code')}")
    # C3
    for label, d in (("without its [1]", declare("u9", "u9:a1", energy=0)),
                     ("exhausting u9", declare("u9", "u9:a1", energy=1, exhaust="u9"))):
        if code(activate(s, d)) != "copied_ability_cost_mismatch":
            fail("C3 cost", f"{label}: {code(activate(s, d))}")
    # C4, C5
    if code(activate(s, declare("u8", "u8:a1", energy=1))) != "copied_ability_not_had":
        fail("C4 not [Exhaust]", code(activate(s, declare("u8", "u8:a1", energy=1))))
    if code(activate(s, declare("e9", "e9:a1", energy=0))) != "copied_ability_not_had":
        fail("C5 not friendly", code(activate(s, declare("e9", "e9:a1", energy=0))))
    # C6
    if code(activate(board(u9_gone=True), declare("u9", "u9:a1", energy=1))) != "copied_ability_not_had":
        fail("C6 gone", code(activate(board(u9_gone=True), declare("u9", "u9:a1", energy=1))))
    if code(activate(board(gear=False), declare("g9", "g9:a1", energy=0))) != "copied_ability_not_had":
        fail("C6 gone", "a gear in the trash still lent its ability")
    # C8
    if code(activate(board(static=False), declare("u9", "u9:a1", energy=1))) != "copied_ability_not_had":
        fail("C8 no static", code(activate(board(static=False), declare("u9", "u9:a1", energy=1))))
    # C9
    if code(activate(s, declare("u9", "u9:a1", energy=1, prog="g9-a1"))) != "copied_ability_program_mismatch":
        fail("C9 program", code(activate(s, declare("u9", "u9:a1", energy=1, prog="g9-a1"))))
    # C10: the copy run as the ORIGINAL's program (its source u9): refused - "me" is the card that has the copy
    wrong = activate(s, declare("u9", "u9:a1", energy=1), source="u9")
    if wrong.get("committed"):
        fail("C10 me", "the copy ran with the original as its source")
    # V
    bad = copy.deepcopy(s)
    bad["objects"]["u9"]["activated_abilities"]["u9:a1"]["cost"]["tap"] = True
    if not validate_state(bad):
        fail("V shape", "an ability cost with an unknown part validated")
    got = cg.compile_clause(STATEMENT, cg.load_grammar())
    if ((got.get("passive") or {}).get("object_fields") or {}) != {"has_exhaust_abilities_of": ["legend", "unit", "gear"]}:
        fail("V grammar", f"{got.get('production_id')} {got.get('passive')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: activating an [Exhaust] ability had from another permanent")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the card activates a friendly Legend's, Unit's or Gear's [Exhaust] ability as its own - 'me' is the card, "
          "its [Exhaust] exhausts the card, every other printed cost paid; not an ability without [Exhaust], not an "
          "enemy's, not once the original has left; one copy per readying; the program is the original's (C1-C10, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
