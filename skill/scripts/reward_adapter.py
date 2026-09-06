#!/usr/bin/env python3
"""
Reward projection — ADR-0010 §10 (G3).

A versioned, read-only consumer projection over the timing state's
`terminal` record, for the internal harness and R5 tooling. It reads nothing
but the terminal: in a two-player non-team game the winner gets +1, the
other player −1; an ongoing game or an ending with no winner is 0. It never
reads point margins, turn counts or strategy, and it is not an engine check
— it does not enter the engine-check.v1 envelope.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from rules_core import is_terminal, state_hash, validate_state  # noqa: E402

REWARD_VERSION = "riftbound-terminal-reward.v1"


def terminal_reward(timing_state: dict[str, Any], player: str) -> dict[str, Any]:
    base = {"schema_version": REWARD_VERSION, "player": player, "input_timing_state_hash": state_hash(timing_state) if isinstance(timing_state, dict) else None}
    errors = validate_state(timing_state) if isinstance(timing_state, dict) else ["timing state must be an object"]
    if errors:
        return {**base, "valid": False, "errors": errors}
    if player not in timing_state["players"]:
        return {**base, "valid": False, "errors": [f"{player!r} is not a player of this game"]}
    if len(timing_state["players"]) != 2:
        return {**base, "valid": True, "unsupported": True, "reason_code": "non_two_player_reward", "reason": "the reward projection is defined for a two-player non-team game only", "reward": None}
    if not is_terminal(timing_state):
        return {**base, "valid": True, "reward": 0, "reason": "ongoing", "terminal_reason": None, "winner": None, "terminal_hash": None}
    terminal = timing_state["terminal"]
    winner = terminal.get("winner")
    if winner is None:
        reward, reason = 0, "no_winner"
    elif winner == player:
        reward, reason = 1, "winner"
    else:
        reward, reason = -1, "loser"
    return {**base, "valid": True, "reward": reward, "reason": reason, "terminal_reason": terminal["reason"], "winner": winner,
            "terminal_hash": state_hash(timing_state), "zero_sum": True, "reads": ["terminal"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicle terminal reward projection (ADR-0010 §10)")
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("player")
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.timing_state.read_text(encoding="utf-8"))
        output = terminal_reward(value, args.player)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
