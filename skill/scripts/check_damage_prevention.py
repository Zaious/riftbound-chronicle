#!/usr/bin/env python3
"""
Gate (package 9): damage prevention - Unyielding Spirit and Kayn - Unleashed.

GPT 2026-10-06 rulings 8 and 9.
  Unyielding Spirit "Prevent all spell and ability damage this turn." - every Deal this turn whose source is a spell or
  an ability is prevented, on any player's object, a spell played after it included; combat damage is not (its source
  is the units, Core 417.6.c), nor a Deal a spell names a Unit as the source of (417.6.b.3).
  Kayn - Unleashed "If I have moved twice this turn, I don't take damage." - at least two real Moves this turn (the
  third does not undo it); a standard Move and an effect's Move both count, a Recall does not; read each time he would
  take damage; combat damage included; a new object with the same id does not keep the old one's Moves (Core 124).

Must hold:
  U1  after create_turn_replacement, a spell's Deal to p2's unit and to p1's unit is prevented (replaced_prevented)
  U2  an ability's Deal (a program whose source is a gear) is prevented too
  U3  a Deal a spell names a Unit as the source of (source_kind unit) is NOT prevented
  U4  combat damage is NOT prevented: both units take what was assigned
  U5  the next turn's Expiration Step clears it; a Deal after that is applied
  K1  Kayn moved twice this turn: a spell's Deal to him is prevented, and so is combat damage assigned to him
  K2  moved once: the Deal is applied
  K3  moved three times: still prevented
  K4  a Recall is not a Move: moved once and recalled, the Deal is applied
  K5  Kayn leaves and returns (a new identity): his earlier Moves do not count
  S   shapes: a created replacement of another shape, damage_sources on a non-deal replacement, an unknown
      damage source, a malformed moves_this_turn ledger - refused
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_combat_damage_assignment import add_unit, both, closed_combat  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from combat import assign_combat_damage, deal_combat_damage  # noqa: E402
from effect_ir import _bump_identity, apply_program, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import run_expiration_step  # noqa: E402
import watchers  # noqa: E402

errors: list[str] = []
SPIRIT = {"op": "create_turn_replacement", "effect_id": "us", "controller": "p1", "created_by": "unyielding-spirit",
          "replacement": {"mode": "prevent_event", "event_op": "deal_damage", "damage_sources": ["spell", "ability"]}}
KAYN_REPLACEMENT = {"replacement_id": "kayn-no-damage", "controller": "p1", "source_object": "u1", "target_object_id": "u1",
                    "mode": "prevent_event", "event_op": "deal_damage", "optional": False, "uses_remaining": None,
                    "condition": {"kind": "moved_this_turn_at_least", "count": 2}}


def fail(label, why):
    errors.append(f"{label}: {why}")


def outcome(result):
    return result["trace"][0].get("outcome") if result.get("committed") else f"refused: {result.get('reason') or result.get('errors')}"


def spirit_state():
    got = apply_program(base_state(), program("us", SPIRIT))
    if not got.get("committed") or validate_state(got["next_state"]):
        fail("U0", f"create_turn_replacement did not commit cleanly: {got.get('reason') or validate_state(got['next_state'])}")
    return got["next_state"]


def moves(state, object_id, n):
    """n real Moves of object_id this turn, counted as real play counts them (watchers.schedule_live)."""
    for i in range(n):
        dest = "base:p1" if i % 2 == 0 else "bf1"
        moved = apply_program(state, program(f"mv{i}", {"op": "move_board_object", "effect_id": f"mv{i}", "object_id": object_id,
                                                         "destination": {"kind": "base", "player_relation": "object_controller"}
                                                         if dest == "base:p1" else {"kind": "battlefield", "battlefield": "bf1"}}))
        if not moved.get("committed"):
            fail(f"move {i}", f"{moved.get('reason') or moved.get('errors')}")
            return state
        _, state = watchers.schedule_live(moved["next_state"], moved.get("events") or [], turn_id=state.get("turn_id", "turn-0"),
                                          batch_label=f"mv{i}")
    return state


def kayn_state():
    state = base_state()
    state["replacement_effects"].append(copy.deepcopy(KAYN_REPLACEMENT))
    return state


def bolt(state, target, **extra):
    return apply_program(state, program("bolt", {"op": "deal_damage", "effect_id": "d", "object_id": target, "amount": 2, **extra}))


def combat_damage(spirit=False, kayn_moves=None):
    t, e = closed_combat([("d1", {"might": 2})], attacker_might=3)
    if spirit:
        e = apply_program(e, program("us", SPIRIT))["next_state"]
    if kayn_moves is not None:
        e["replacement_effects"].append(copy.deepcopy(KAYN_REPLACEMENT))
        e.setdefault("moves_this_turn", {})[e.get("turn_id", "turn-0")] = {object_identity(e, "u1"): kayn_moves}
    assigned = assign_combat_damage(t, e, both(t, e, {"d1": 3}, {"u1": 2}))
    if not assigned.get("committed"):
        return None, f"assign: {assigned.get('reason_code')} {assigned.get('reason')}"
    dealt = deal_combat_damage(assigned["next_timing_state"], assigned["next_effect_state"])
    if not dealt.get("committed"):
        return None, f"deal: {dealt.get('reason_code')} {dealt.get('reason')}"
    after = dealt["next_effect_state"]
    return {u: (after["objects"].get(u) or {}).get("damage") if u in after["objects"] else "gone" for u in ("u1", "d1")}, None


def main() -> int:
    s = spirit_state()
    # U1
    for target in ("u2", "u1"):
        got = bolt(s, target)
        if outcome(got) != "replaced_prevented" or got["next_state"]["objects"][target]["damage"] != s["objects"][target]["damage"]:
            fail("U1", f"a spell's Deal to {target} was not prevented: {outcome(got)}")
    # U2: an ability's Deal - the program's source is a gear on the board
    gear_state = copy.deepcopy(s)
    add_unit(gear_state, "g1", "p1", "base:p1", might=0)
    gear_state["objects"]["g1"]["kind"] = "gear"
    ability = apply_program(gear_state, {**program("ballista", {"op": "deal_damage", "effect_id": "d", "object_id": "u2", "amount": 2}),
                                         "source_object": "g1"})
    if outcome(ability) != "replaced_prevented":
        fail("U2", f"an ability's Deal was not prevented: {outcome(ability)}")
    # U3
    named = bolt(s, "u2", source_object="u1", source_kind="unit")
    if outcome(named) != "applied":
        fail("U3", f"a Deal whose source the spell names as a Unit was prevented: {outcome(named)}")
    # U4
    dmg, why = combat_damage(spirit=True)
    if why or dmg != {"u1": 2, "d1": "gone"} and dmg != {"u1": 2, "d1": 3}:
        fail("U4", f"combat damage under Unyielding Spirit was not dealt as assigned: {dmg} {why}")
    # U5
    from check_rules_core import fixture
    timing = fixture()
    timing.update({"phase": "ending", "priority": None,
                   "ending_step": {"status": "triggers_scheduled", "turn_id": s.get("turn_id", "turn-0")}})
    expired = run_expiration_step(timing, s)
    after = (expired or {}).get("next_effect_state")
    if after is None or any("created" in r for r in after["replacement_effects"]) or outcome(bolt(after, "u2")) != "applied":
        fail("U5", f"the turn's Expiration Step did not end the prevention: {expired and expired.get('reason')}")
    # K1-K3
    for n, want in ((2, "replaced_prevented"), (1, "applied"), (3, "replaced_prevented")):
        state = moves(kayn_state(), "u1", n)
        if outcome(bolt(state, "u1")) != want:
            fail(f"K{ {2: 1, 1: 2, 3: 3}[n] }", f"after {n} Moves the Deal to Kayn was {outcome(bolt(state, 'u1'))}, not {want}")
    dmg, why = combat_damage(kayn_moves=2)
    if why or dmg.get("u1") != 0:
        fail("K1 combat", f"combat damage assigned to Kayn after two Moves was not prevented: {dmg} {why}")
    dmg, why = combat_damage(kayn_moves=1)
    if why or dmg.get("u1") != 2:
        fail("K2 combat", f"combat damage to Kayn after one Move was prevented: {dmg} {why}")
    # K4: moved once, then recalled
    state = moves(kayn_state(), "u1", 1)
    recalled = apply_program(state, program("rc", {"op": "recall", "effect_id": "rc", "object_id": "u1"}))
    if recalled.get("committed"):
        _, state = watchers.schedule_live(recalled["next_state"], recalled.get("events") or [], turn_id="turn-0", batch_label="rc")
    if outcome(bolt(state, "u1")) != "applied":
        fail("K4", f"a Recall counted as a Move: {outcome(bolt(state, 'u1'))}")
    # K5: a new identity starts at zero
    state = moves(kayn_state(), "u1", 2)
    _bump_identity(state, "u1")
    if outcome(bolt(state, "u1")) != "applied":
        fail("K5", "a new object with the same id kept the old one's Moves")
    # S
    bad = copy.deepcopy(s)
    bad["replacement_effects"][-1]["mode"] = "replace_with"
    if not validate_state(bad):
        fail("S", "a created replacement of another shape validated")
    wrong = base_state()
    wrong["replacement_effects"].append({**copy.deepcopy(KAYN_REPLACEMENT), "event_op": "kill", "damage_sources": ["spell"]})
    if not validate_state(wrong):
        fail("S", "damage_sources on a non-deal replacement validated")
    other = copy.deepcopy(SPIRIT)
    other["replacement"] = {**other["replacement"], "damage_sources": ["spell", "combat"]}
    if not validate_program(program("x", other)):
        fail("S", "an unknown damage source validated")
    ledger = base_state()
    ledger["moves_this_turn"] = {"turn-0": {"u1": 2}}
    if not validate_state(ledger):
        fail("S", "a moves_this_turn ledger keyed by a non-identity validated")
    if errors:
        print("FAILED: damage prevention checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: Unyielding Spirit prevents every spell's and ability's Deal this turn on any player's object, not a Deal a "
          "spell names a Unit as the source of nor combat damage, and expires with the turn; Kayn takes no damage - "
          "spells' or combat's - after two real Moves this turn (three too), takes it after one, a Recall is no Move, "
          "and a new object starts at zero; four shapes refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
