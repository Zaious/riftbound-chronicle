#!/usr/bin/env python3
"""
Regression gate for C-46 (ADR-0012 §4; Codex G-1 on DP-66): attachments, the
Top-Most card, the Might Bonus, and the rule-derived destination when a host
leaves.

Must hold:
  - attach links two board cards: the attached card takes the Top-Most card's
    location (434.4) and keeps everything else — an exhausted Equipment stays
    exhausted (434.5.a); attaching to a new host detaches it from the old one
    (434.2.a); attaching to its current host is a no_op (434.2.b); attaching
    to a card that is not on the board, to itself, or to a card that is
    itself attached is refused;
  - the Top-Most card's Might is modulated by every attached card's Might
    Bonus (159.1) and stops as soon as the card detaches;
  - detach puts the card where its Top-Most card is (435.4); a detached Gear
    that lands at a Battlefield records the Cleanup Recall (435.4.a) rather
    than moving early, and the same Gear detaching at a Base records none
    (negative mutation); detaching an unattached card does nothing (435.1.a);
  - a host that leaves the board for a non-board zone detaches to the last
    board location it occupied (435.4.b) — killed, banished, returned to hand
    and recycled hosts all route through the one derivation, and the
    attachment never follows the host into the trash (negative mutation: the
    host itself does go there);
  - a host that moves on the board carries its attachments (434.4);
  - the program validator refuses a malformed attach or detach; the effect
    scope declares attachments and keeps nested attachments and Effect Text
    unsupported; the manifest cites both operations; determinism and purity.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from capability_manifest import build_manifest  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import OP_RULES, apply_program, attachments, effective_might, find_location, validate_program, validate_state  # noqa: E402
from engine_check import KIND_CONFIG  # noqa: E402


def ev(result, index=0):
    return result["trace"][index] if result.get("committed") else {}


def equipped_state():
    """u1 at bf1 with a Gear (g1) in p1's Base, ready to be equipped."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"]["objects"].append("u1")
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": True, "might_bonus": 2}
    state["players"]["p1"]["zones"]["base"].append("g1")
    return state


def main() -> int:
    errors: list[str] = []
    state = equipped_state()
    attach = program("eq", {"op": "attach", "effect_id": "a", "object_id": "g1", "to": "u1"})

    # --- attach ---------------------------------------------------------------------------------
    attached = apply_program(state, attach)
    if not attached.get("committed"):
        errors.append(f"attaching the Gear failed: {attached.get('reason_code')} {attached.get('reason')}")
    else:
        after = attached["next_state"]
        if after["objects"]["g1"].get("attached_to") != "u1" or attachments(after, "u1") != ["g1"]:
            errors.append(f"the attachment was not recorded in one direction: {after['objects']['g1'].get('attached_to')}")
        if find_location(after, "g1") != ("battlefield", "bf1", None):
            errors.append(f"the attached card did not take its Top-Most card's location: {find_location(after, 'g1')}")
        if after["objects"]["g1"]["exhausted"] is not True or ev(attached).get("not_a_move") is not True:
            errors.append("attaching readied the Equipment or counted as a Move (434.5.a, 434.4)")
        if effective_might(after, "u1") != effective_might(state, "u1") + 2:
            errors.append(f"the Might Bonus did not reach the Top-Most card: {effective_might(after, 'u1')} vs {effective_might(state, 'u1')}")
        if validate_state(after):
            errors.append(f"the state after attaching is invalid: {validate_state(after)}")
    again = apply_program(attached["next_state"], attach)
    if not again.get("committed") or ev(again).get("outcome") != "no_op":
        errors.append(f"attaching to the current Top-Most card was not a no_op: {ev(again).get('outcome')}")
    two_hosts = copy.deepcopy(attached["next_state"])
    move_host = apply_program(two_hosts, program("re", {"op": "attach", "effect_id": "a", "object_id": "g1", "to": "u2"}))
    if not move_host.get("committed") or move_host["next_state"]["objects"]["g1"]["attached_to"] != "u2" or ev(move_host).get("detached_from") != "u1":
        errors.append(f"attaching to a new host did not detach from the old one: {ev(move_host)}")
    elif effective_might(move_host["next_state"], "u1") != effective_might(state, "u1"):
        errors.append("the old Top-Most card kept the Might Bonus after the card left it")
    off_board = copy.deepcopy(state)
    off_board["battlefields"]["bf1"]["objects"].remove("u1")
    off_board["players"]["p1"]["zones"]["hand"].append("u1")
    if apply_program(off_board, attach).get("reason_code") != "illegal_operation":
        errors.append("attaching to a card that is not on the board was accepted")
    if apply_program(state, program("self", {"op": "attach", "effect_id": "a", "object_id": "g1", "to": "g1"})).get("reason_code") != "illegal_operation":
        errors.append("attaching a card to itself was accepted")
    nested = copy.deepcopy(attached["next_state"])
    nested["objects"]["c1"] = dict(nested["objects"]["c2"])
    stacked = apply_program(nested, program("nest", {"op": "attach", "effect_id": "a", "object_id": "u2", "to": "g1"}))
    if stacked.get("unsupported") is not True or "nested_attachments" not in str(stacked.get("reason")):
        errors.append(f"a nested attachment was not refused as unsupported: {stacked.get('reason_code')} {stacked.get('reason')}")

    # --- detach ----------------------------------------------------------------------------------------
    at_battlefield = attached["next_state"]
    detached = apply_program(at_battlefield, program("de", {"op": "detach", "effect_id": "d", "object_id": "g1"}))
    if not detached.get("committed") or detached["next_state"]["objects"]["g1"].get("attached_to") is not None:
        errors.append(f"detaching failed: {detached.get('reason_code')} {detached.get('reason')}")
    else:
        after = detached["next_state"]
        if find_location(after, "g1") != ("battlefield", "bf1", None):
            errors.append(f"the detached card did not stay at its Top-Most card's location (435.4): {find_location(after, 'g1')}")
        if after["objects"]["g1"].get("pending_recall") != {"reason": "detached_gear_at_battlefield", "battlefield": "bf1"}:
            errors.append(f"a detached Gear at a Battlefield did not record the Cleanup Recall (435.4.a): {after['objects']['g1'].get('pending_recall')}")
        if effective_might(after, "u1") != effective_might(state, "u1"):
            errors.append("the Might Bonus survived the detach")
    at_base = copy.deepcopy(state)
    at_base["battlefields"]["bf1"]["objects"].remove("u1")
    at_base["players"]["p1"]["zones"]["base"].append("u1")
    base_attached = apply_program(at_base, attach)["next_state"]
    base_detached = apply_program(base_attached, program("de", {"op": "detach", "effect_id": "d", "object_id": "g1"}))
    if not base_detached.get("committed") or base_detached["next_state"]["objects"]["g1"].get("pending_recall") is not None:
        errors.append("negative mutation failed: a Gear detaching at a Base also recorded a Recall, so the 435.4.a record is not about the Battlefield")
    idle = apply_program(state, program("de", {"op": "detach", "effect_id": "d", "object_id": "g1"}))
    if not idle.get("committed") or ev(idle).get("outcome") != "no_op":
        errors.append(f"detaching an unattached card was not a no_op (435.1.a): {ev(idle).get('outcome')}")

    # --- the host leaves the board ------------------------------------------------------------------------
    for label, effect, host_zone in (
        ("killed", {"op": "kill", "effect_id": "k", "object_id": "u1"}, ("player", "p1", "trash")),
        ("banished", {"op": "banish", "effect_id": "b", "object_id": "u1"}, ("player", "p1", "banishment")),
        ("returned to hand", {"op": "return_to_hand", "effect_id": "r", "object_id": "u1"}, ("player", "p1", "hand")),
        ("recycled", {"op": "recycle_one", "effect_id": "r", "object_id": "u1"}, ("player", "p1", "main_deck")),
    ):
        gone = apply_program(at_battlefield, program("host", effect))
        if not gone.get("committed"):
            errors.append(f"a {label} host failed: {gone.get('reason_code')} {gone.get('reason')}")
            continue
        after = gone["next_state"]
        if find_location(after, "u1") != host_zone:
            errors.append(f"negative mutation failed: the {label} host did not reach {host_zone}, so the attachment's fate proves nothing")
        if find_location(after, "g1") != ("battlefield", "bf1", None) or after["objects"]["g1"].get("attached_to") is not None:
            errors.append(f"the attachment of a {label} host did not detach to its last board location (435.4.b): {find_location(after, 'g1')}")
        if after["objects"]["g1"].get("pending_recall", {}).get("battlefield") != "bf1":
            errors.append(f"the detached Gear of a {label} host did not record the Cleanup Recall")
        if not ev(gone).get("detached"):
            errors.append(f"the {label} trace does not record the detach")
        if validate_state(after):
            errors.append(f"the state after a {label} host is invalid: {validate_state(after)}")

    moved = apply_program(at_battlefield, program("mv", {"op": "move_board_object", "effect_id": "m", "object_id": "u1", "destination": {"kind": "base", "player": "p1"}}))
    if not moved.get("committed") or find_location(moved["next_state"], "g1") != ("player", "p1", "base") or moved["next_state"]["objects"]["g1"].get("attached_to") != "u1":
        errors.append(f"a moving host did not carry its attachment (434.4): {find_location(moved['next_state'], 'g1') if moved.get('committed') else moved.get('reason')}")

    # --- validation, scope, manifest, determinism -------------------------------------------------------------
    if not validate_program(program("bad", {"op": "attach", "effect_id": "a", "object_id": "g1"})):
        errors.append("an attach without a Top-Most card was accepted")
    if not validate_program(program("bad2", {"op": "detach", "effect_id": "d", "object_id": "g1", "to": "u1"})):
        errors.append("a detach carrying a `to` was accepted")
    cycle = copy.deepcopy(at_battlefield)
    cycle["objects"]["u1"]["attached_to"] = "g1"
    if not validate_state(cycle):
        errors.append("a nested / cyclic attachment was accepted by the validator")
    scope = KIND_CONFIG["effect"]
    if not {"attachments", "top_most_might_bonus", "derived_detach_destination"} <= set(scope["supported"]) or "nested_attachments" not in scope["unsupported"] or "effect_text_append" not in scope["unsupported"]:
        errors.append("the effect scope does not declare attachments and their boundary")
    cited = {o["id"]: o["rule_locators"] for o in build_manifest()["operations"]}
    for op in ("attach", "detach"):
        if cited.get(op) != OP_RULES[op]:
            errors.append(f"the manifest does not cite {op}")
    snapshot = copy.deepcopy(state)
    if apply_program(state, attach) != attached or state != snapshot:
        errors.append("attach is not deterministic or mutated its input")

    if errors:
        print("FAILED: attachment checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("attachment checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
