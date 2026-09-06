#!/usr/bin/env python3
"""
The terminal state — ADR-0010 §3–4 (G3).

`check_terminal` is Cleanup step 1 (Core 323.1, 194.2): the one player at or
above the Victory Score with more points than every other player wins and
the game ends (196); a tie at the threshold continues (194.2.b). Two reasons
are derived and only the engine writes them (`victory_score`,
`burn_out_victory`); two are declared by the caller through
`declare_terminal` (`concession`, `external`) and recorded, never derived.
`apply_terminal_event` is the bridge every Draw entry uses to write a typed
terminal_event into the timing state inside its own two-state commit (§2).
After the terminal the snapshot is frozen: the timing kernel and the shared
two-state validators refuse every procedure as `game_over`.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from battlefield_control import victory_check  # noqa: E402
from combat import _base as _combat_base, _commit, _invalid, _refuse, _unsupported, _validate_both  # noqa: E402
from effect_ir import DEFAULT_TURN_ID  # noqa: E402
from rules_core import DECLARED_TERMINAL_REASONS, DERIVED_TERMINAL_REASONS, TERMINAL_EVENT_KIND, is_terminal  # noqa: E402

TERMINAL_STEP_VERSION = "riftbound-terminal-step-result.v1"
TERMINAL_LOCATORS = {"victory_score": ["Core 194.2", "Core 194.2.a", "Core 196", "Core 323.1", "Core 472"],
                     "burn_out_victory": ["Core 431.3.c", "Core 431.3.c.1", "Core 196"],
                     "concession": ["Core 196"], "external": ["Core 196"]}


def _base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {**_combat_base(step, timing_state, effect_state), "schema_version": TERMINAL_STEP_VERSION}


def terminal_record(effect_state: dict[str, Any], reason: str, winner: str | None, *, derived: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The frozen record: who won, why, with what points, on which turn."""
    record = {"status": "ended", "reason": reason, "winner": winner,
              "final_points": {p: int(player.get("points", 0)) for p, player in effect_state["players"].items()},
              "turn_id": effect_state.get("turn_id", DEFAULT_TURN_ID), "derived": derived, "rule_locators": list(TERMINAL_LOCATORS[reason])}
    if extra:
        record.update(extra)
    return record


def terminal_event(reason: str, winner: str, *, immediate: bool, source: str) -> dict[str, Any]:
    """The typed event a Draw emits when 431.3.c ends the game; the effect IR
    never writes the timing state itself (ADR-0010 §2)."""
    if reason not in DERIVED_TERMINAL_REASONS:
        raise ValueError(f"a terminal_event carries a derived reason, not {reason!r}")
    return {"kind": TERMINAL_EVENT_KIND, "reason": reason, "winner": winner, "immediate": immediate, "source": source, "rule_locators": list(TERMINAL_LOCATORS[reason])}


def apply_terminal_event(timing_state: dict[str, Any], effect_state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Write one terminal_event into a copy of the timing state. Callers
    commit it together with the effect state that produced the event."""
    if not isinstance(event, dict) or event.get("kind") != TERMINAL_EVENT_KIND or event.get("reason") not in DERIVED_TERMINAL_REASONS or event.get("winner") not in timing_state["players"]:
        raise ValueError("terminal_event must carry a derived reason and a winning player")
    if is_terminal(timing_state):
        raise ValueError("the game already ended")
    next_timing = copy.deepcopy(timing_state)
    next_timing["terminal"] = terminal_record(effect_state, event["reason"], event["winner"], derived=True,
                                              extra={"immediate": bool(event.get("immediate")), "source": event.get("source")})
    return next_timing


def check_terminal(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cleanup step 1 (323.1): end the game for a strict leader at or above
    the Victory Score; a tie at the threshold continues (194.2.b); below it
    nothing happens. Refuses `game_over` once ended (through the shared
    validator) and is unsupported without a Mode of Play."""
    base = _base("check_terminal", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    facts = victory_check(effect_state)
    if not facts.get("available"):
        return _unsupported(base, facts["reason"], "the victory condition needs the Mode of Play and no teams (456.3, 469.1.a)", ["Core 194.3", "Core 472"])
    next_timing = copy.deepcopy(timing_state)
    if facts["strict_leader"] is not None:
        next_timing["terminal"] = terminal_record(effect_state, "victory_score", facts["strict_leader"], derived=True, extra={"immediate": False, "source": "cleanup_step_1"})
        outcome = "ended"
    elif facts["tied_at_threshold"]:
        outcome = "continue_tied"
    else:
        outcome = "below_threshold"
    trace = {"outcome": outcome, "victory_check": facts, "winner": facts["strict_leader"], "frozen_chain_items": [i["id"] for i in timing_state["chain"]["items"]] if outcome == "ended" else [],
             "frozen_outstanding_tasks": list(timing_state["outstanding_tasks"]) if outcome == "ended" else []}
    return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=["Core 194.2", "Core 194.2.a", "Core 194.2.b", "Core 196", "Core 323.1", "Core 472"])


def declare_terminal(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None, *, declaration: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record a game end the rules do not derive: a concession (the other
    player of a two-player game wins) or an external ruling (winner optional).
    Never writes a derived reason."""
    base = _base("declare_terminal", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if not isinstance(declaration, dict) or declaration.get("reason") not in DECLARED_TERMINAL_REASONS:
        return _invalid(base, [f"declaration.reason must be one of {sorted(DECLARED_TERMINAL_REASONS)}; derived reasons are written by the engine only"])
    players = timing_state["players"]
    reason = declaration["reason"]
    if reason == "concession":
        conceding = declaration.get("player")
        if conceding not in players:
            return _invalid(base, ["declaration.player must be the conceding player"])
        if len(players) != 2:
            return _unsupported(base, "multi_player_concession", "a concession in a game of more than two players removes one player and continues; that is not modelled", ["Core 196"])
        winner = next(p for p in players if p != conceding)
        if declaration.get("winner") not in (None, winner):
            return _invalid(base, [f"declaration.winner must be {winner!r}, the other player, or absent"])
        extra = {"immediate": True, "source": "declared", "declared_by": conceding}
    else:
        winner = declaration.get("winner")
        if winner is not None and winner not in players:
            return _invalid(base, ["declaration.winner must be a player id or null"])
        extra = {"immediate": True, "source": "declared", "note": str(declaration.get("note", ""))[:200]}
    next_timing = copy.deepcopy(timing_state)
    next_timing["terminal"] = terminal_record(effect_state, reason, winner, derived=False, extra=extra)
    trace = {"outcome": "ended", "reason": reason, "winner": winner, "derived": False, "frozen_chain_items": [i["id"] for i in timing_state["chain"]["items"]]}
    return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=["Core 196"])


STEPS = {"check_terminal": check_terminal, "declare_terminal": declare_terminal}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicle terminal-state procedures (ADR-0010)")
    parser.add_argument("step", choices=sorted(STEPS))
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("effect_state", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--declaration", type=Path)
    args = parser.parse_args(argv)
    try:
        decisions = _load(args.decisions) if args.decisions else None
        declaration = _load(args.declaration) if args.declaration else None
        if args.step == "declare_terminal":
            output = declare_terminal(_load(args.timing_state), _load(args.effect_state), decisions, declaration=declaration)
        else:
            output = check_terminal(_load(args.timing_state), _load(args.effect_state), decisions)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
