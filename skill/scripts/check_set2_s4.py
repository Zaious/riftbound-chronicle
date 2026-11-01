#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): tokens that enter ready, a Might while another friendly unit is here, a Might swap
between two units at one battlefield, and a choice of a unit or a gear in the controller's own trash.

  E  "Your tokens enter ready." (Core 369.3, 365.1): with the source on the board a Unit token p1 makes enters ready;
     the source in the trash, the opponent's, or absent - exhausted; a Unit p1 plays that is not a token - exhausted
  M  "While you have another unit here, I have +1 Might." (364.3.a): at a Battlefield with another friendly Unit there -
     +1; alone there, with only an enemy Unit there, or in a Base beside a friendly Unit - none
  S  "Swap the Might of two units at the same battlefield." (355.11): both at bf1 - swapped; one of them moved to bf2
     before it resolves - nothing happens; a group other than same_battlefield - refused
  T  "a unit or gear from your trash": a Unit and a Gear in p1's Trash are legal; a spell there, and a Unit in p2's
     Trash, are not
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from check_granted_entry_state import enter  # noqa: E402

errors: list[str] = []
TOKENS = "Your tokens enter ready."
HERE = "While you have another unit here, I have +1 :rb_might:."


def fail(label, why):
    errors.append(f"{label}: {why}")


def unit(owner, might=2, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def fields(text):
    return (CG.compile_clause(text, CG.load_grammar()).get("passive") or {}).get("object_fields") or {}


def token_board(where="base", owner="p1"):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    if where is not None:
        state["objects"]["rg"] = unit(owner, 4, **copy.deepcopy(fields(TOKENS)))
        state["players"][owner]["zones"]["base" if where == "base" else "trash"].append("rg")
    return state


def make_token(state):
    done = IR.apply_program(state, program("tok", {"op": "play_token", "effect_id": "tok", "object_id": "t1", "owner": "p1",
                                                   "controller": "p1", "token_kind": "unit", "base_might": 1,
                                                   "destination": {"kind": "base", "player": "p1"}}))
    if not done.get("committed"):
        return "refused: " + str(done.get("errors") or done.get("reason"))
    return "exhausted" if done["next_state"]["objects"]["t1"]["exhausted"] else "ready"


def here_board(beside):
    state = base_state()
    state["objects"]["rh"] = unit("p1", 2, **copy.deepcopy(fields(HERE)))
    where = "base" if beside == "friendly_in_base" else "bf1"
    if where == "base":
        state["players"]["p1"]["zones"]["base"].append("rh")
    else:
        state["battlefields"]["bf1"]["objects"].append("rh")
    if beside in ("friendly", "enemy"):
        state["objects"]["nb"] = unit("p1" if beside == "friendly" else "p2")
        state["battlefields"]["bf1"]["objects"].append("nb")
    return settle_contested(state)


def swap_board():
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, might in (("sa", 2), ("sb", 6)):
        state["objects"][oid] = unit("p1", might)
        state["battlefields"]["bf1"]["objects"].append(oid)
    return settle_contested(state)


def swapped(state):
    sel = lambda oid: {"object_id": oid, "chosen_zone_class": "board", "kind": "unit",
                       "bound_identity": IR.object_identity(state, oid)}
    prog = program("sw", {"op": "swap_might", "effect_id": "sw", "units": [sel("sa"), sel("sb")], "duration": "this_turn",
                          "group": {"same_battlefield": True}})
    done = IR.apply_program(state, prog)
    if not done.get("committed"):
        return f"refused: {done.get('errors') or done.get('reason')}"
    after = done["next_state"]
    return (IR.effective_might(after, "sa"), IR.effective_might(after, "sb"))


def main() -> int:
    # E
    want = {"granted_entry_states": [{"replacement_id": "tokens-enter-ready", "value": "ready",
                                      "criteria": {"kind": "unit", "controller_relation": "friendly", "token": True}}]}
    if fields(TOKENS) != want:
        fail("E", f"the sentence lowered to {fields(TOKENS)}")
    for label, run, expected in (("token, source on the board", lambda: make_token(token_board()), "ready"),
                                 ("token, source in the trash", lambda: make_token(token_board("trash")), "exhausted"),
                                 ("token, the opponent's source", lambda: make_token(token_board(owner="p2")), "exhausted"),
                                 ("token, no source", lambda: make_token(token_board(None)), "exhausted"),
                                 ("a played unit, not a token", lambda: enter(token_board()), "exhausted")):
        if (got := run()) != expected:
            fail("E", f"{label}: entered {got}, not {expected} (Core 369.3, 365.1)")
    # M
    for beside, extra in (("friendly", 1), ("alone", 0), ("enemy", 0), ("friendly_in_base", 0)):
        state = here_board(beside)
        if problems := IR.validate_state(state):
            fail("M", f"the {beside} board is invalid: {problems[:2]}")
            continue
        if (got := IR.effective_might(state, "rh")) != 2 + extra:
            fail("M", f"{beside}: Might {got}, not {2 + extra} (Core 364.3.a)")
    # S
    state = swap_board()
    if (got := swapped(state)) != (6, 2):
        fail("S", f"both at bf1: Mights after the swap {got}, not (6, 2)")
    apart = copy.deepcopy(state)
    apart["battlefields"]["bf1"]["objects"].remove("sb")
    apart["battlefields"]["bf2"]["objects"].append("sb")
    apart = settle_contested(apart)
    if (got := swapped(apart)) != (2, 6):
        fail("S", f"no longer at one battlefield: Mights {got}, not unchanged (2, 6) (Core 355.11.b)")
    bad = program("sw", {"op": "swap_might", "effect_id": "sw", "duration": "this_turn", "group": {"total_might_at_most": 3},
                         "units": [{"decision_ref": "a", "chosen_zone_class": "board", "kind": "unit"},
                                   {"decision_ref": "b", "chosen_zone_class": "board", "kind": "unit"}]})
    if not IR.validate_program(bad):
        fail("S", "a swap group other than same_battlefield validated")
    # S2: "any number of friendly units at a battlefield" - no count of its own, the same-battlefield group bounds it
    sb = {"op": "move_board_object", "effect_id": "mv", "destination": {"kind": "base", "player_relation": "object_controller"},
          "targets": {"min": 0, "decision_ref": "t", "subset_ref": "keep", "group": {"same_battlefield": True},
                      "restrictions": {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly",
                                       "location": "battlefield"}}}
    if IR.validate_program(program("any", sb)):
        fail("S2", f"any number at one battlefield refused: {IR.validate_program(program('any', sb))}")
    bare = copy.deepcopy(sb)
    del bare["targets"]["group"]
    del bare["targets"]["subset_ref"]
    if not IR.validate_program(program("any", bare)):
        fail("S2", "targets with no max and no group validated")
    # T
    state = base_state()
    for oid, owner, kind in (("tu", "p1", "unit"), ("tg", "p1", "gear"), ("ts", "p1", "spell"), ("ou", "p2", "unit")):
        state["objects"][oid] = {**unit(owner), "kind": kind}
        state["players"][owner]["zones"]["trash"].append(oid)
    selector = {"chosen_zone_class": "board", "any_of": [
        {"kind": "unit", "location": "trash", "chosen_zone_class": "non_board", "zone_owner_relation": "own"},
        {"kind": "gear", "location": "trash", "chosen_zone_class": "non_board", "zone_owner_relation": "own"}]}
    if IR._selector_errors({**selector, "decision_ref": "t"}):
        fail("T", f"the selector is refused: {IR._selector_errors({**selector, 'decision_ref': 't'})}")
    legal = {oid: IR.evaluate_target(state, {**selector, "object_id": oid,
                                             "bound_identity": IR.object_identity(state, oid)}, "p1")[0]
             for oid in ("tu", "tg", "ts", "ou")}
    if legal != {"tu": True, "tg": True, "ts": False, "ou": False}:
        fail("T", f"a unit or gear from your trash: {legal}")
    if errors:
        print("FAILED: set 2 S4 checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: tokens enter ready under 'Your tokens enter ready.' (369.3); +1 Might only with another friendly unit here "
          "(364.3.a); a same-battlefield swap does nothing once the pair is apart (355.11.b); a unit or gear is chosen from "
          "the controller's own trash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
