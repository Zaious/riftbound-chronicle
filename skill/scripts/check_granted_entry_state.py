#!/usr/bin/env python3
"""
Regression gate: a permanent's replacement on how the OTHER units of its side enter (2026-09-27).

"Other friendly units enter ready." is a passive ability of a permanent (Core 365.1: active while it
is on the board) and a replacement effect on how units enter the board (369.3: it describes how
they enter; 143.4: units enter exhausted). The engine grammar lowers it to the object field
`granted_entry_states`; effect_ir.granted_entry_states finds the grants that apply, and both entry
paths read it: resolution_bridge.entry_state_for (a Unit card played, 359.2.c) and play_token (a
Unit token made by an instruction).

Must hold, through the real play transaction and entry, and the real play_token instruction:
  - p1's source on the board (its Base): a Unit card p1 plays enters ready; a Unit token p1 makes
    enters ready;
  - the source in its owner's trash: both enter exhausted (365.1);
  - the source is p2's: p1's Unit and p1's token enter exhausted (not friendly);
  - no source: exhausted;
  - the card's own "I enter ready." beside the grant: ready, no order decision (one value);
  - a Gear token is untouched (ready by default, 359.2.d);
  - the grammar lowers the card's sentence to exactly this grant;
  - invalid: an 'exhausted' grant, an enemy criterion, a missing id, a duplicated id;
  - mutations caught: a grant read off a source that is not on the board; one read for either
    side; a token path that ignores grants.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

SENTENCE = "Other friendly units enter ready."
GRANT = {"replacement_id": "others-enter-ready", "value": "ready",
         "criteria": {"kind": "unit", "controller_relation": "friendly", "exclude_source": True}}


def board(source_owner="p1", where="base", own=None):
    """p1's c1, a 2-Might Unit, in hand (with `own` fields); the source w1 (a Unit with the grant),
    owned and controlled by `source_owner`, in its Base or its trash (or absent: where=None)."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, **copy.deepcopy(own or {})})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    if where is not None:
        state["objects"]["w1"] = {"owner": source_owner, "controller": source_owner, "kind": "unit", "base_might": 5,
                                  "might_modifiers": [], "damage": 0, "exhausted": False,
                                  "granted_entry_states": [copy.deepcopy(GRANT)]}
        state["players"][source_owner]["zones"]["base" if where == "base" else "trash"].append("w1")
    return state


def enter(state):
    """Really play c1 to p1's Base and resolve its entry: 'ready', 'exhausted', or the refusal."""
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": "p1", "card": "c1",
                "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    played = PT.play_card(fixture(), state, declared)
    if not played.get("committed"):
        return f"play refused: {played.get('reason_code')}"
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    done = resolve_with_program(timing, "unit-1", played["next_effect_state"], None)
    if not done.get("committed"):
        return "refused: " + str(done.get("reason") or done.get("reason_code"))
    return "exhausted" if done["next_effect_state"]["objects"]["c1"]["exhausted"] else "ready"


def make_token(state, kind="unit"):
    """p1's program plays a 1-Might token into p1's Base (no entry state named)."""
    program = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
               "program_id": "make-token", "controller": "p1",
               "effects": [{"op": "play_token", "effect_id": "tok", "object_id": "t1", "owner": "p1", "controller": "p1",
                            "token_kind": kind, "base_might": 1 if kind == "unit" else 0,
                            "destination": {"kind": "base", "player": "p1"}}]}
    result = IR.apply_program(state, program)
    if not result.get("committed"):
        return "refused: " + str(result.get("errors") or result.get("reason"))
    return "exhausted" if result["next_state"]["objects"]["t1"]["exhausted"] else "ready"


def cases():
    return {
        "card_source_on_the_board": (lambda: enter(board()), "ready"),
        "card_source_in_the_trash": (lambda: enter(board(where="trash")), "exhausted"),
        "card_source_is_the_opponents": (lambda: enter(board(source_owner="p2")), "exhausted"),
        "card_no_source": (lambda: enter(board(where=None)), "exhausted"),
        "card_its_own_i_enter_ready_too": (lambda: enter(board(own={"entry_replacements": [
            {"mode": "entry_state", "value": "ready"}]})), "ready"),
        "token_source_on_the_board": (lambda: make_token(board()), "ready"),
        "token_source_in_the_trash": (lambda: make_token(board(where="trash")), "exhausted"),
        "token_source_is_the_opponents": (lambda: make_token(board(source_owner="p2")), "exhausted"),
        "token_no_source": (lambda: make_token(board(where=None)), "exhausted"),
        "gear_token_source_on_the_board": (lambda: make_token(board(), kind="gear"), "ready"),
    }


def main() -> int:
    errors: list[str] = []
    lowered = (CG.compile_clause(SENTENCE, CG.load_grammar()).get("passive") or {}).get("object_fields")
    if lowered != {"granted_entry_states": [GRANT]}:
        errors.append(f"the sentence lowered to {lowered}")
    for label in ("base", "trash"):
        if found := IR.validate_state(board(where=label)):
            errors.append(f"the board with the source in its {label} is invalid: {found[:2]}")
    for label, (run, want) in cases().items():
        if (got := run()) != want:
            errors.append(f"{label}: entered {got}, not {want} (Core 369.3, 365.1, 143.4)")
    for label, bad in (("an exhausted grant", [{**GRANT, "value": "exhausted"}]),
                       ("an enemy criterion", [{**GRANT, "criteria": {**GRANT["criteria"], "controller_relation": "enemy"}}]),
                       ("a missing id", [{k: v for k, v in GRANT.items() if k != "replacement_id"}]),
                       ("a duplicated id", [GRANT, GRANT])):
        broken = board()
        broken["objects"]["w1"]["granted_entry_states"] = copy.deepcopy(bad)
        if not IR.validate_state(broken):
            errors.append(f"an invalid grant validated: {label}")
    real_grants, real_zone = IR.granted_entry_states, IR.zone_class

    def any_zone(state, entering, kind, controller):
        saved = IR.zone_class
        IR.zone_class = lambda location: "board"
        try:
            return real_grants(state, entering, kind, controller)
        finally:
            IR.zone_class = saved

    def either_side(state, entering, kind, controller):
        return real_grants(state, entering, kind, controller) + real_grants(state, entering, kind, "p2" if controller == "p1" else "p1")

    def no_token_grants(state, entering, kind, controller):
        return [] if entering is None else real_grants(state, entering, kind, controller)

    for label, replacement in (("a grant read off a source not on the board", any_zone),
                               ("a grant read for either side", either_side),
                               ("a token path that ignores grants", no_token_grants)):
        IR.granted_entry_states = replacement
        try:
            wrong = [name for name, (run, want) in cases().items() if run() != want]
        finally:
            IR.granted_entry_states, IR.zone_class = real_grants, real_zone
        if not wrong:
            errors.append(f"mutation not caught: {label} passed every case")
    if errors:
        print("FAILED: granted entry state checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'Other friendly units enter ready.' makes the other Units its side plays or makes enter ready while its "
          "source is on the board (369.3, 365.1), not an opponent's, not once the source left; a Gear token is untouched; "
          "invalid grants are refused; three engine mutations are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
