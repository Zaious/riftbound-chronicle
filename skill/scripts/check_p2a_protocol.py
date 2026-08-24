#!/usr/bin/env python3
"""Deterministic regression checks for the P2-A authority boundary."""

from __future__ import annotations

import copy
import sys

from p2a_session import (
    add_confirmation,
    add_proposal,
    add_state,
    new_session,
    validate_session,
)


def expect_invalid(name, session, needle, failures):
    errors = validate_session(session)
    if not errors:
        failures.append(f"{name}: expected invalid, but validation passed")
    elif needle and not any(needle in error for error in errors):
        failures.append(f"{name}: expected error containing {needle!r}, got {errors}")


def main():
    failures = []
    session = new_session(
        player1_deck="Human deck",
        player2_deck="Agent deck",
        format_name="1v1 Constructed",
        ruleset_version="test fixture",
        created_by="human operator",
    )
    session = add_state(
        session,
        turn=1,
        turn_player="Player 2",
        phase="Main",
        public_state="Human-confirmed public board",
        player2_private_hand="Player 2's own hand",
        confirmed_by="human operator",
    )
    session = add_proposal(
        session,
        action_id="p2-001",
        objective="Develop the board",
        description="Take the candidate action supplied to the Agent",
        reason="It advances the stated deck plan",
        alternative="Pass and preserve resources",
        assumptions=["The human will confirm legality"],
    )
    session = add_confirmation(
        session,
        action_id="p2-001",
        legal=True,
        confirmed_by="human operator",
        resolution_summary="Human physically resolved the action",
    )

    if validate_session(session):
        failures.append(f"valid P2-A flow failed: {validate_session(session)}")

    updated = add_state(
        session,
        turn=1,
        turn_player="Player 2",
        phase="Main",
        public_state="Human-confirmed resulting board",
        player2_private_hand="Updated Player 2 hand",
        confirmed_by="human operator",
    )
    if validate_session(updated):
        failures.append(f"post-resolution state failed: {validate_session(updated)}")

    bad = copy.deepcopy(session)
    bad["p2s_enabled"] = True
    expect_invalid("P2-S activation", bad, "p2s_enabled", failures)

    bad = copy.deepcopy(session)
    bad["state_authority"] = "engine_derived"
    expect_invalid("engine-derived state", bad, "state_authority", failures)

    bad = copy.deepcopy(session)
    bad["legality_authority"] = "rules_engine"
    expect_invalid("rules-engine legality", bad, "legality_authority", failures)

    bad = copy.deepcopy(session)
    bad["events"][1]["legality_status"] = "legal"
    expect_invalid("pre-confirmed proposal", bad, "legality_status", failures)

    bad = copy.deepcopy(session)
    bad["events"][0]["opponent_private_hand"] = "forbidden"
    expect_invalid("opponent hidden information", bad, "hidden information", failures)

    bad = copy.deepcopy(session)
    bad["events"].append(copy.deepcopy(bad["events"][1]))
    bad["events"][-1]["seq"] = len(bad["events"])
    bad["events"][-1]["action_id"] = "p2-002"
    expect_invalid("proposal before post-resolution snapshot", bad, "must be state_confirmed", failures)

    bad = copy.deepcopy(updated)
    bad["events"][2]["state_transition"] = "engine_derived"
    expect_invalid("derived transition", bad, "state_transition", failures)

    if failures:
        print("[errors]")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\nFAILED: {len(failures)} P2-A protocol regression(s).")
        return 1

    print("OK: P2-A protocol accepts the manual flow and rejects automated authority, hidden opponent data, and skipped human snapshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
