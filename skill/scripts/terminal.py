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
from effect_ir import _bump_identity, _remove_from_location, find_location  # noqa: E402
from combat import _base as _combat_base, _commit, _invalid, _refuse, _unsupported, _validate_both  # noqa: E402
from rules_core import DECLARED_TERMINAL_REASONS, TERMINAL_LOCATORS, apply_terminal_event, terminal_event, terminal_record  # noqa: E402,F401

TERMINAL_STEP_VERSION = "riftbound-terminal-step-result.v1"


def _base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {**_combat_base(step, timing_state, effect_state), "schema_version": TERMINAL_STEP_VERSION}


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
            # C-59 (ADR-0015 §3): the Removal of a Player is its own procedure,
            # because the game continues and this one only records endings.
            return _unsupported(base, "multi_player_concession",
                                "a concession with more than two players removes that player and the game continues; run the `concede` step (651.4, 652)",
                                ["Core 651.4", "Core 652"])
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




# ------------------------------------------------------- Removal of a Player --

REMOVAL_LOCATORS = ["Core 651", "Core 651.2", "Core 651.3", "Core 651.4", "Core 652", "Core 652.3", "Core 652.4", "Core 652.5"]


def concede(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None,
            *, player: str | None = None) -> dict[str, Any]:
    """Core 651–652 (ADR-0015 §3). A player may concede at any time and is
    removed from the game in progress. With one other player left, that player
    Wins and the game ends — the engine records it, it does not derive a
    winner from points. With more than one left the game continues and the
    Removal of a Player runs: everything the conceding player owns leaves the
    game, everything they controlled but did not own is Banished, the
    Battlefield they contributed becomes a token Battlefield with no abilities
    while the Units and Hidden cards there do not move, their spells and
    abilities are Countered, and the turn and the Focus pass to the next
    available player in Turn Order.
    """
    base = _base("concede", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    players = timing_state["players"]
    if player not in players:
        return _invalid(base, ["player must be the conceding player"])
    mode = effect_state.get("mode") if isinstance(effect_state.get("mode"), dict) else {}
    if mode.get("teams") or any(isinstance(p, dict) and p.get("team_id") for p in effect_state.get("players", {}).values()):
        return _unsupported(base, "team_scoring", "a concession in a team mode removes the conceding player's Teammates too (652.2.a); teams are not modelled", ["Core 652.2.a"])

    order = [p for p in timing_state["turn_order"] if p != player]
    if len(order) == 1:
        # 651.3: the one remaining player Wins. Recorded, never derived.
        next_timing = copy.deepcopy(timing_state)
        next_timing["terminal"] = terminal_record(effect_state, "concession", order[0], derived=False,
                                                  extra={"immediate": True, "source": "declared", "declared_by": player})
        trace = {"outcome": "ended", "reason": "concession", "winner": order[0], "removed": player,
                 "remaining": order, "derived": False}
        return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=REMOVAL_LOCATORS + ["Core 196"])

    # 652: the game continues, so the Removal of a Player runs in full.
    next_effect = copy.deepcopy(effect_state)
    contributed = [bf for bf, entry in sorted(next_effect["battlefields"].items()) if entry.get("contributed_by") == player]
    if not contributed and any("contributed_by" not in entry for entry in next_effect["battlefields"].values()):
        return _unsupported(base, "contributed_battlefield_unknown",
                            f"the Removal of a Player removes the Battlefield {player} contributed (652.5); no Battlefield in this state says who contributed it",
                            ["Core 652.5"])
    # 652.5: read the chain before anything moves — a card that leaves the
    # game takes its chain item with it, and the Counter has to be recorded.
    countered = [item_id for item_id, entry in sorted((next_effect.get("chain_items") or {}).items())
                 if entry.get("controller") == player]
    banished: list[str] = []
    removed_cards: list[str] = []
    for object_id in sorted(next_effect["objects"]):
        obj = next_effect["objects"][object_id]
        if obj.get("owner") == player:
            removed_cards.append(object_id)
        elif obj.get("controller") == player:
            banished.append(object_id)
    for object_id in banished:
        # 652.3: Banished to their own owner's Banishment; they stay in the game.
        owner = next_effect["objects"][object_id]["owner"]
        _remove_from_location(next_effect, object_id)
        next_effect["players"][owner]["zones"]["banishment"].append(object_id)
        # Control is a board relation: a Banished card is its owner's again,
        # which also keeps the state valid once the seat is gone.
        next_effect["objects"][object_id]["controller"] = owner
        _bump_identity(next_effect, object_id)
    for object_id in removed_cards:
        # 652.4: every card they own leaves the game entirely.
        if find_location(next_effect, object_id) is not None:
            _remove_from_location(next_effect, object_id)
        del next_effect["objects"][object_id]
    replaced: list[dict[str, Any]] = []
    for battlefield_id in contributed:
        battlefield = next_effect["battlefields"][battlefield_id]
        # 652.5.a.1: a token Battlefield with no abilities. What is there does
        # not move, and the old Battlefield's continuous effects cease.
        kept = {"objects": battlefield.get("objects", []), "facedown": battlefield.get("facedown"),
                "controller": battlefield.get("controller"), "contested": battlefield.get("contested", False),
                "contested_by": battlefield.get("contested_by")}
        replaced.append({"battlefield": battlefield_id, "contributed_by": player,
                         "abilities_removed": sorted(set(battlefield) - set(kept) - {"identity"})})
        next_effect["battlefields"][battlefield_id] = {
            **{k: v for k, v in kept.items() if v is not None or k in {"controller", "contested_by"}},
            "is_token": True, "replaced_from": battlefield_id,
        }
        next_effect["battlefields"][battlefield_id].setdefault("objects", [])
    for item_id in countered:
        next_effect.get("chain_items", {}).pop(item_id, None)
    del next_effect["players"][player]
    for entry in next_effect.get("continuous_effects", []) or []:
        pass  # a source that left the game is pruned on read (ADR-0013 §1)
    next_effect["continuous_effects"] = [e for e in next_effect.get("continuous_effects", []) or []
                                         if (e.get("source") or {}).get("object") not in set(removed_cards)]

    next_timing = copy.deepcopy(timing_state)
    next_timing["players"] = [p for p in timing_state["players"] if p != player]
    next_timing["turn_order"] = order
    was_turn_player = timing_state["turn_player"] == player
    if was_turn_player:
        # 652.5.b: play proceeds in Turn Order to the next available player.
        position = timing_state["turn_order"].index(player)
        following = timing_state["turn_order"][position + 1:] + timing_state["turn_order"][:position]
        next_timing["turn_player"] = next(p for p in following if p != player)
    if next_timing.get("priority") == player:
        next_timing["priority"] = next_timing["turn_player"] if next_timing.get("phase") == "main" else None
    showdown = next_timing.get("showdown") or {}
    focus_moved = None
    if showdown.get("focus") == player:
        position = timing_state["turn_order"].index(player)
        following = timing_state["turn_order"][position + 1:] + timing_state["turn_order"][:position]
        focus_moved = next(p for p in following if p != player)
        showdown["focus"] = focus_moved
        if next_timing.get("priority") is None:
            next_timing["priority"] = focus_moved
    next_timing["chain"]["items"] = [i for i in next_timing["chain"]["items"] if i.get("controller") != player]
    next_timing["chain"]["consecutive_passes"] = [p for p in next_timing["chain"].get("consecutive_passes", []) if p != player]

    trace = {"outcome": "removed", "removed": player, "remaining": order, "banished": banished,
             "cards_removed_from_game": removed_cards, "battlefields_replaced": replaced,
             "countered_chain_items": countered, "turn_player_after": next_timing["turn_player"],
             "focus_moved_to": focus_moved, "winner": None,
             "note": "the game continues; no winner is derived from a concession (651.4)"}
    return _commit(base, next_timing, next_effect, trace=trace, locators=REMOVAL_LOCATORS)


STEPS = {"check_terminal": check_terminal, "declare_terminal": declare_terminal, "concede": concede}


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
