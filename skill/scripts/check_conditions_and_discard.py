#!/usr/bin/env python3
"""
Gate for C-22 (ADR-0007 §9–10): the named instruction condition, Move
triggers, and discard by a private card_selection.

Must hold:
  - sole_controlled_unit_at_referent_location holds only when the earlier
    instruction's legal referent is the sole unit its controller controls
    there (teammates excluded); it fails on a skipped referent, on company,
    and when the referent moved; failure is skipped_linked_dependency,
    never illegal;
  - a completed move_board_object raises the moved object's move_triggers
    as Pending items; recall, return_to_hand and board entry raise none;
  - discard: a whole-hand discard proceeds without a decision; a larger hand
    stops for card_selection naming the player and never listing the hand;
    a valid selection discards those cards to the trash as new objects; a
    selection outside the hand or by another player is illegal; a stale
    identity is invalid_input; a short hand discards what it has
    (completion partial);
  - "then" is sequence, not a condition (Core 422.4, Undercover Agent's
    "Discard 2, then draw 2"): an empty hand ignores the discard and still
    draws 2, a one-card hand discards 1 and still draws 2, and the draw
    carries no predicate;
  - a real linked instruction ("Discard 1. If you do, draw 1.", Core
    359.3.e.14.b) carries action_performed: an empty hand skips the draw as
    skipped_linked_dependency, a discard that happened lets it through;
  - engine-check wraps the decision as card_choice; determinism, purity,
    off-cwd CLI.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import apply_program, effects_for, hash_value, object_identity, validate_program  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def main() -> int:
    errors: list[str] = []
    state = base_state()

    def ev(result, i=0):
        return result["trace"][i] if result.get("committed") else {}

    # --- En Garde's condition -------------------------------------------------------------
    buff = {"op": "modify_might", "object_id": "u1", "amount": 1, "duration": "this_turn", "source": "en-garde", "effect_id": "first", "target": {"object_id": "u1", "chosen_zone_class": "board", "controller_relation": "friendly"}}
    more = {"op": "modify_might", "object_id": "u1", "amount": 1, "duration": "this_turn", "source": "en-garde", "effect_id": "second", "predicate": {"kind": "sole_controlled_unit_at_referent_location", "effect_id": "first"}}
    alone = apply_program(state, program("en-garde", buff, more))
    if not alone.get("committed") or ev(alone, 1).get("outcome") != "applied" or len(effects_for(alone["next_state"], "u1", "might_arithmetic")) != 2:
        errors.append(f"the sole unit at its base did not get the additional +1: {ev(alone, 1).get('outcome')} {alone.get('reason') or alone.get('errors')}")
    company = copy.deepcopy(state)
    company["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False}
    company["players"]["p1"]["zones"]["base"].append("u3")
    crowded = apply_program(company, program("en-garde", buff, more))
    if ev(crowded, 1).get("outcome") != "skipped_linked_dependency" or ev(crowded, 1).get("completion") != "none":
        errors.append(f"a second controlled unit there did not fail the condition: {ev(crowded, 1)}")
    enemy_company = copy.deepcopy(state); enemy_company["players"]["p2"]["zones"]["base"].remove("u2"); enemy_company["players"]["p1"]["zones"]["base"].append("u2")
    with_enemy = apply_program(enemy_company, program("en-garde", buff, more))
    if ev(with_enemy, 1).get("outcome") != "applied":
        errors.append("an enemy unit at the same location wrongly failed 'the only unit you control'")
    teammate = copy.deepcopy(enemy_company); teammate["players"]["p1"]["team_id"] = "A"; teammate["players"]["p2"]["team_id"] = "A"
    with_teammate = apply_program(teammate, program("en-garde", buff, more))
    if ev(with_teammate, 1).get("outcome") != "applied":
        errors.append("a teammate's unit was counted as one 'you control'")
    gone = copy.deepcopy(state); gone["players"]["p1"]["zones"]["base"].remove("u1"); gone["players"]["p1"]["zones"]["hand"].append("u1")
    skipped_first = apply_program(gone, program("en-garde", buff, more))
    if ev(skipped_first, 0).get("outcome") != "ignored_illegal_target" or ev(skipped_first, 1).get("outcome") != "skipped_linked_dependency":
        errors.append(f"a skipped referent still satisfied the condition: {ev(skipped_first, 0).get('outcome')} / {ev(skipped_first, 1).get('outcome')}")
    if not any("earlier instruction" in e for e in validate_program(program("bad", more))):
        errors.append("a condition on a missing referent instruction was accepted")

    # --- Move triggers ----------------------------------------------------------------------
    merchant = copy.deepcopy(state)
    merchant["objects"]["u1"]["move_triggers"] = [{"trigger_id": "u1-on-move", "controller": "p1", "source_object": "u1", "controller_order": 0, "effect_program_id": "u1-on-move-effects", "optional_at_finalize": False}]
    moved = apply_program(merchant, program("mv", {"op": "move_board_object", "object_id": "u1", "destination": {"kind": "battlefield", "battlefield": "bf1"}}))
    if not moved.get("committed") or [t["trigger_id"] for t in ev(moved).get("pending_triggers", [])] != ["u1-on-move"] or [t["trigger_id"] for t in moved.get("pending_triggers", [])] != ["u1-on-move"]:
        errors.append(f"a completed Move did not raise the move trigger: {ev(moved).get('pending_triggers')} {moved.get('reason')}")
    at_bf = copy.deepcopy(merchant); at_bf["players"]["p1"]["zones"]["base"].remove("u1"); at_bf["battlefields"]["bf1"]["objects"].append("u1")
    recalled = apply_program(at_bf, program("rc", {"op": "recall", "object_id": "u1"}))
    returned = apply_program(at_bf, program("ret", {"op": "return_to_hand", "object_id": "u1"}))
    if ev(recalled).get("pending_triggers") or ev(returned).get("pending_triggers") or recalled.get("pending_triggers") or returned.get("pending_triggers"):
        errors.append("recall or return_to_hand raised a Move trigger")
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    scheduled = resolve_with_program(timing, "spell-1", merchant, program("spell-1-effects", {"op": "move_board_object", "object_id": "u1", "destination": {"kind": "battlefield", "battlefield": "bf1"}}))
    if not scheduled.get("committed") or [i["id"] for i in scheduled["next_timing_state"]["chain"]["items"]] != ["u1-on-move"]:
        errors.append(f"the move trigger was not scheduled as a Pending item: {scheduled.get('reason')} {[i.get('id') for i in scheduled.get('next_timing_state', {}).get('chain', {}).get('items', [])]}")

    # --- discard ----------------------------------------------------------------------------
    hand2 = copy.deepcopy(state)
    for c in ("c1", "c2"):
        hand2["players"]["p1"]["zones"]["main_deck"].remove(c); hand2["players"]["p1"]["zones"]["hand"].append(c)
    hand2["players"]["p1"]["zones"]["main_deck"].append("c3"); hand2["players"]["p1"]["zones"]["trash"].remove("c3")
    ask = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}))
    if ask.get("committed") or ask.get("reason_code") != "card_selection_required" or ask.get("decision_ids") != ["pick"] or ask.get("decision_controller") != "p1":
        errors.append(f"a two-card hand did not stop for card_selection: {ask.get('reason_code')} {ask.get('errors')}")
    dumped = json.dumps({k: v for k, v in ask.items() if k not in {"trace"}})
    if '"c1"' in dumped or '"c2"' in dumped:  # ids as JSON strings; hashes may contain the letters
        errors.append("the decision_required result leaked the hand's contents")
    check = build_engine_check("effect", ask, input_hashes={"effect_state": hash_value(hand2), "effect_program": "sha256:" + "5" * 64})
    if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "card_choice" or check["decision_required"]["controller"] != "p1":
        errors.append(f"card selection did not wrap as card_choice: {check.get('decision_required')}")
    def pick(ids, controller="p1", identities=None):
        return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(hand2), "decisions": [{"decision_id": "pick", "stage": "resolution", "kind": "card_selection", "controller": controller, "value": ids,
                 "selection_identities": identities if identities is not None else {i: object_identity(hand2, i) or f"{i}@0" for i in ids}}]}
    chosen = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}), decisions=pick(["c2"]))
    if not chosen.get("committed") or "c2" not in chosen["next_state"]["players"]["p1"]["zones"]["trash"] or "c1" not in chosen["next_state"]["players"]["p1"]["zones"]["hand"] or object_identity(chosen["next_state"], "c2") != "c2@1" or ev(chosen).get("not_a_target") is not True:
        errors.append(f"a valid card selection did not discard that card as a new object: {chosen.get('reason') or chosen.get('errors')}")
    outside = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}), decisions=pick(["c4"], identities={"c4": "c4@0"}))
    if outside.get("valid") is not True or outside.get("committed") or outside.get("applied") is not False:
        errors.append(f"a selection outside the hand was not illegal: {outside.get('reason_code')} {outside.get('errors')}")
    other = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}), decisions=pick(["c2"], controller="p2"))
    if other.get("committed") or other.get("applied") is not False or other.get("reason_code") != "decision_controller_mismatch":
        errors.append("another player's card selection was accepted")
    stale = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}), decisions=pick(["c2"], identities={"c2": "c2@9"}))
    if stale.get("valid") is not False:
        errors.append("a stale selection identity was accepted")
    unbound_decision = pick(["c2"])
    del unbound_decision["decisions"][0]["selection_identities"]
    unbound = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}), decisions=unbound_decision)
    if unbound.get("valid") is not False:
        errors.append("a card_selection without selection_identities was accepted")
    forced = apply_program(hand2, program("d2", {"op": "discard", "player": "p1", "count": 2, "effect_id": "d"}))
    if not forced.get("committed") or ev(forced).get("selection", {}).get("forced") is not True or sorted(ev(forced).get("objects", [])) != ["c1", "c2"] or ev(forced).get("completion") != "full":
        errors.append(f"a whole-hand discard did not proceed without a decision: {forced.get('reason') or forced.get('errors')} {ev(forced)}")
    short = apply_program(hand2, program("d3", {"op": "discard", "player": "p1", "count": 3, "effect_id": "d"}))
    if not short.get("committed") or ev(short).get("completion") != "partial" or ev(short).get("applied_count") != 2:
        errors.append(f"a short hand did not discard what it had as partial (422.4): {ev(short)}")
    # --- "then" is sequence, not a condition (Core 422.4) ------------------------------------
    # Core 422.4's own example is Undercover Agent, "Discard 2, then draw 2": with no cards in
    # hand the whole discard instruction is ignored, and "regardless of how many cards they
    # discard, they then draw 2". A bare "then" carries no backward reference, so it is not a
    # Core 359.3.e.14 linked instruction and the draw takes no predicate. This fixture used to
    # put an action_performed predicate on exactly this pattern and assert the draw was
    # skipped - the opposite of 422.4 (corrected 2026-09-19).
    undercover = program("undercover-agent", {"op": "discard", "player": "p1", "count": 2, "effect_id": "d"},
                         {"op": "draw", "player": "p1", "count": 2, "effect_id": "then"})
    empty = apply_program(state, undercover)  # base_state: p1's hand is empty, main deck c1, c2
    if not empty.get("committed") or ev(empty).get("outcome") != "no_op" or ev(empty, 1).get("outcome") != "applied" \
            or len(empty["next_state"]["players"]["p1"]["zones"]["hand"]) != 2:
        errors.append(f"an empty-handed 'Discard 2, then draw 2' did not still draw 2 (Core 422.4): "
                      f"{ev(empty).get('outcome')} / {ev(empty, 1).get('outcome')}")
    one = copy.deepcopy(state)
    one["players"]["p1"]["zones"]["main_deck"].remove("c1"); one["players"]["p1"]["zones"]["hand"].append("c1")
    one["players"]["p1"]["zones"]["trash"].remove("c3"); one["players"]["p1"]["zones"]["main_deck"].append("c3")
    short_then = apply_program(one, undercover)  # one card in hand: discard 1, the rest ignored, still draw 2
    if not short_then.get("committed") or ev(short_then).get("completion") != "partial" or ev(short_then, 1).get("outcome") != "applied" \
            or len(short_then["next_state"]["players"]["p1"]["zones"]["hand"]) != 2:
        errors.append(f"a one-card 'Discard 2, then draw 2' did not discard 1 and draw 2 (Core 422.4): "
                      f"{ev(short_then).get('completion')} / {ev(short_then, 1).get('outcome')}")

    # --- a real linked instruction: "if you do" (Core 359.3.e.14.b) --------------------------
    # The action_performed predicate is for an instruction that directly references the
    # earlier game action - Deathgrip's "If you do, ...". Here: "Discard 1. If you do, draw 1."
    if_you_do = program("if-you-do", {"op": "discard", "player": "p1", "count": 1, "effect_id": "d"},
                        {"op": "draw", "player": "p1", "count": 1, "effect_id": "then", "predicate": {"kind": "action_performed", "effect_id": "d"}})
    linked_empty = apply_program(state, if_you_do)
    if not linked_empty.get("committed") or ev(linked_empty).get("outcome") != "no_op" or ev(linked_empty, 1).get("outcome") != "skipped_linked_dependency" \
            or linked_empty["next_state"]["players"]["p1"]["zones"]["hand"]:
        errors.append(f"an empty-handed 'Discard 1. If you do, draw 1.' still drew: {ev(linked_empty).get('outcome')} / {ev(linked_empty, 1).get('outcome')}")
    linked_one = apply_program(one, if_you_do)
    if not linked_one.get("committed") or ev(linked_one, 1).get("outcome") != "applied":
        errors.append("a discard that happened did not let 'If you do, draw 1' through")
    # without the predicate the same two effects would draw on an empty hand - the predicate is
    # what the "if you do" costs, and nothing else here supplies it
    if ev(apply_program(state, undercover), 1).get("outcome") == "skipped_linked_dependency":
        errors.append("a draw with no predicate was skipped; 'then' is being read as a condition")
    snap = copy.deepcopy(hand2)
    if hand2 != snap or apply_program(hand2, program("d2", {"op": "discard", "player": "p1", "count": 2, "effect_id": "d"})) != forced:
        errors.append("discard mutated its input or is not deterministic")
    with tempfile.TemporaryDirectory(prefix="discard-") as temp_name:
        temp = Path(temp_name)
        (temp / "s.json").write_text(json.dumps(hand2), encoding="utf-8")
        (temp / "p.json").write_text(json.dumps(program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"})), encoding="utf-8")
        (temp / "x.json").write_text(json.dumps(pick(["c2"])), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "effect", str(temp / "s.json"), str(temp / "p.json"), "--decisions", str(temp / "x.json"), "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI discard with a card_selection failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: conditions / discard checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: the named condition reads the earlier instruction's legal referent and its current location, counts only the controller's own units, and fails as a skipped instruction; only a completed Move raises move triggers; discard is the player's private card_selection — forced when the whole hand goes, stopped without leaking the hand otherwise, illegal outside the hand or by another player, partial on a short hand; 'then' is sequence (an empty-handed 'Discard 2, then draw 2' still draws 2, Core 422.4) while a real linked 'If you do, draw 1' is skipped when nothing was discarded (Core 359.3.e.14.b).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
