#!/usr/bin/env python3
"""A trigger on leaving the board, however it leaves (package 11, Treasure Trove: "When this leaves the board, draw 1 and
channel 1 rune exhausted. [C], [T]: Kill this.").

GPT 2026-10-12 (PACKAGE11 ruling 8): it triggers however the card leaves the board - killed, by its own ability among
others, returned to a hand, banished - each witnessed; the draw and the channel resolve after it has left. The object's
leave_board_triggers are noted before it moves, as a death trigger is (Core 359.3.e.13), and each is one Pending trigger of
the action that moved it (effect_ir.leave_board_triggers).

  L1 killed          a spell kills the gear: its leave trigger is Pending, once
  L2 to hand         returned to its owner's hand: Pending
  L3 banished        banished: Pending
  L4 not leaving     recalled from a battlefield to its Base, or moved: still on the board - nothing
  L5 its own ability "Kill this" from its own program (the source itself): Pending
  L6 resolved        the trigger's program with its source gone: p1 draws 1 and channels 1 rune exhausted
  L7 with a death    a unit with a death trigger and a leave trigger, killed: both Pending, each once
  V  shape/grammar   the field on the board only as a trigger list; "When this leaves the board, ..." lowers to it;
                     "Kill this." lowers to killing the ability's own source

    python skill/scripts/check_leave_board_trigger.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, find_location, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
LEAVE = {"trigger_id": "tr-leave", "controller": "p1", "source_object": "tr", "controller_order": 0,
         "effect_program_id": "tr-leave-fx", "optional_at_finalize": False}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects, controller="p2", **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "x", "controller": controller, "effects": effects, **extra}


def board(where="base"):
    state = base_state()
    state["objects"]["tr"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "leave_board_triggers": [dict(LEAVE)]}
    if where == "base":
        state["players"]["p1"]["zones"]["base"].append("tr")
    else:
        state["battlefields"]["bf1"]["objects"].append("tr")
    return settle_contested(state)


def pending(got):
    return [t["trigger_id"] for t in got.get("pending_triggers") or []] if got.get("committed") else f"refused: {got.get('reason') or got.get('errors')}"


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
    for label, effect in (("L1 killed", {"op": "kill", "effect_id": "k", "object_id": "tr"}),
                          ("L2 to hand", {"op": "return_to_hand", "effect_id": "r", "object_id": "tr"}),
                          ("L3 banished", {"op": "banish", "effect_id": "b", "object_id": "tr"})):
        got = apply_program(s, program([effect]))
        if pending(got) != ["tr-leave"]:
            fail(label, pending(got))
    at_bf = board("bf1")
    for label, effect in (("L4 not leaving (recall)", {"op": "recall", "effect_id": "rc", "object_id": "tr"}),):
        got = apply_program(at_bf, program([effect]))
        if pending(got) != [] or find_location(got["next_state"], "tr") != ("player", "p1", "base"):
            fail(label, pending(got))
    own = apply_program(s, program([{"op": "kill", "effect_id": "k", "object_id": {"object_ref": "program_source"}}],
                                   controller="p1", source_object="tr", source_identity="tr@0"))
    if pending(own) != ["tr-leave"]:
        fail("L5 its own ability", pending(own))
    gone = apply_program(s, program([{"op": "kill", "effect_id": "k", "object_id": "tr"}]))["next_state"]
    deck_before = len(gone["players"]["p1"]["zones"]["main_deck"])
    runes_before = list(gone["players"]["p1"]["zones"]["rune_deck"])
    fx = apply_program(gone, program([{"op": "draw", "effect_id": "d", "player": "p1", "count": 1},
                                      {"op": "channel_rune", "effect_id": "c", "player": "p1", "count": 1,
                                       "entry_state": "exhausted"}], controller="p1", source_object="tr"))
    after = fx.get("next_state") or gone
    channelled = [r for r in runes_before if r not in after["players"]["p1"]["zones"]["rune_deck"]]
    if not fx.get("committed") or len(after["players"]["p1"]["zones"]["main_deck"]) != deck_before - 1 \
            or len(channelled) != 1 or not after["objects"][channelled[0]]["exhausted"]:
        fail("L6 resolved", f"{fx.get('reason') or fx.get('errors')} channelled {channelled}")
    both = copy.deepcopy(s)
    both["objects"]["u1"]["death_triggers"] = [{**LEAVE, "trigger_id": "u1-dies", "source_object": "u1",
                                               "effect_program_id": "u1-dies-fx"}]
    both["objects"]["u1"]["leave_board_triggers"] = [{**LEAVE, "trigger_id": "u1-leaves", "source_object": "u1",
                                                     "effect_program_id": "u1-leaves-fx"}]
    got = apply_program(both, program([{"op": "kill", "effect_id": "k", "object_id": "u1"}]))
    if sorted(pending(got) if isinstance(pending(got), list) else []) != ["u1-dies", "u1-leaves"]:
        fail("L7 with a death", pending(got))
    bad = copy.deepcopy(s)
    bad["objects"]["tr"]["leave_board_triggers"] = [{"trigger_id": "x"}]
    if not validate_state(bad):
        fail("V shape", "a malformed leave trigger validated")
    card = cg.compile_card([{"text": "When this leaves the board, draw 1."}], cg.load_grammar())
    fields = (card.get("passive") or {}).get("object_fields") or {}
    if card.get("unsupported_clauses") or len(fields.get("leave_board_triggers") or []) != 1:
        fail("V grammar", f"{card.get('unsupported_clauses')} {fields}")
    own_line = cg.compile_clause("Kill this.", cg.load_grammar())
    if own_line.get("program_effects") != [{"op": "kill", "effect_id": "kill-self", "object_id": {"object_ref": "program_source"}}]:
        fail("V grammar", f"'Kill this.' (the card's own activated body) did not lower to killing its source: {own_line}")
    for near in ("When a unit leaves the board, draw 1.",):
        if not cg.compile_card([{"text": near}], cg.load_grammar()).get("unsupported_clauses"):
            fail("V grammar", f"a near miss parsed: {near}")
    if errors:
        print("FAILED: a trigger on leaving the board")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'When this leaves the board' is Pending once however the card leaves - killed (by its own ability too), "
          "returned to a hand, banished - and not when it stays on the board; its draw and channel resolve with the card "
          "gone; beside a death trigger both are Pending (L1-L7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
