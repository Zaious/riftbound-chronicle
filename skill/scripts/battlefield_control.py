#!/usr/bin/env python3
"""
Battlefield control, Conquer, Hold and scoring — ADR-0009 (G2).

Procedures over the timing/effect pair, in the style of combat.py:
`resolve_battlefield_control` (466.5 after a Combat, 348.2 after a Non-Combat
Showdown), `stage_showdown` / `open_showdown` (316.8.b, 323.8, 323.12, 345),
`run_board_cleanup` (323.6, 323.11, 323.11.a), `run_scoring_step` (315.2.b
Hold). Scoring (469–471) is one atomic transaction: control change, ledger,
point or draw-instead, and Score triggers commit together or not at all. The
victory condition (472) is reported as facts and never enacted (G3).
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

import engine_decisions as _ed  # noqa: E402
from combat import _base as _combat_base, _commit, _invalid, _refuse, _unsupported, _validate_both, combined_input_hash, units_at  # noqa: E402
from effect_ir import DEFAULT_TURN_ID, _bump_identity, battlefield_identity, find_location, hash_value, object_identity, same_side, zone_class  # noqa: E402
from rules_core import schedule_triggered_items, state_hash  # noqa: E402

CONTROL_STEP_VERSION = "riftbound-control-step-result.v1"
SCORE_TRIGGER_FIELDS = {"conquer": "conquer_triggers", "hold": "hold_triggers"}
SHOWDOWN_LOCATION_DECISION_ID = "showdown_location"


class ScoringUnsupported(Exception):
    def __init__(self, code: str, reason: str, locators: list[str]):
        super().__init__(reason)
        self.code, self.reason, self.locators = code, reason, locators


def _base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {**_combat_base(step, timing_state, effect_state), "schema_version": CONTROL_STEP_VERSION}


# ------------------------------------------------------------------ facts --

def mode_of_play(effect_state: dict[str, Any]) -> tuple[int | None, ScoringUnsupported | None]:
    """The Victory Score comes from the Mode of Play (456.3); it is never guessed."""
    mode = effect_state.get("mode")
    if not isinstance(mode, dict) or not isinstance(mode.get("victory_score"), int):
        return None, ScoringUnsupported("mode_unknown", "the Mode of Play (Victory Score) is not in the state; scoring needs it (456.3, 471.1)", ["Core 456.3", "Core 471.1"])
    if mode.get("teams") or any(isinstance(p, dict) and p.get("team_id") for p in effect_state["players"].values()):
        return None, ScoringUnsupported("team_scoring", "scoring with teammates (469.1.a, 315.2.b.3) is not modelled", ["Core 469.1.a", "Core 315.2.b.3"])
    return mode["victory_score"], None


def points_of(effect_state: dict[str, Any], player: str) -> int:
    return int(effect_state["players"][player].get("points", 0))


def victory_check(effect_state: dict[str, Any]) -> dict[str, Any]:
    """Core 472 as facts: who is at or above the Victory Score, whether one of
    them alone leads, or whether the threshold is reached in a tie. No winner
    is declared and nothing ends — the terminal state is G3."""
    victory_score, problem = mode_of_play(effect_state)
    if problem is not None:
        return {"available": False, "reason": problem.code}
    scores = {player: points_of(effect_state, player) for player in effect_state["players"]}
    threshold_met = sorted(p for p, s in scores.items() if s >= victory_score)
    top = max(scores.values()) if scores else 0
    leaders = [p for p, s in scores.items() if s == top]
    strict_leader = leaders[0] if len(leaders) == 1 and top >= victory_score else None
    return {"available": True, "victory_score": victory_score, "points": scores, "threshold_met": threshold_met,
            "strict_leader": strict_leader, "tied_at_threshold": bool(threshold_met) and strict_leader is None, "terminal_state": "not_modelled (G3)"}


def scored_this_turn(effect_state: dict[str, Any], player: str, turn_id: str) -> list[str]:
    ledger = effect_state["players"][player].get("scored_this_turn") or {}
    return list(ledger.get(turn_id, []))


# ------------------------------------------------------------------ scoring --

def _score_triggers(effect_state: dict[str, Any], player: str, battlefield_id: str, how: str, turn_id: str) -> list[dict[str, Any]]:
    """Core 471.2 / 383.4.c–d: a Unit's own trigger fires when that Unit, the
    scoring player's, is at the Battlefield scored (scope unit_here); a
    player-referencing trigger fires from any board object the scoring player
    controls (scope controller); the Battlefield's own trigger belongs to its
    controller (190.6). Only modelled board objects can be sources."""
    field = SCORE_TRIGGER_FIELDS[how]
    batch_id = f"score:{battlefield_id}:{turn_id}:{how}"
    descriptors: list[dict[str, Any]] = []
    for object_id in sorted(effect_state["objects"]):
        obj = effect_state["objects"][object_id]
        if obj.get("controller") != player or zone_class(find_location(effect_state, object_id)) != "board":
            continue
        for descriptor in obj.get(field, []) or []:
            scope = descriptor.get("scope", "unit_here")
            if scope == "unit_here" and (obj.get("kind") != "unit" or find_location(effect_state, object_id) != ("battlefield", battlefield_id, None)):
                continue
            copied = {k: v for k, v in descriptor.items() if k != "scope"}
            copied.update({"trigger_kind": "triggered", "batch_id": batch_id, "batch_sequence": 0, "scored_battlefield": battlefield_id, "how": how, "scope": scope,
                           "source_identity": object_identity(effect_state, object_id) or f"{object_id}@0"})
            descriptors.append(copied)
    battlefield = effect_state["battlefields"][battlefield_id]
    controller = battlefield.get("controller")
    if controller == player:
        for descriptor in battlefield.get(field, []) or []:
            descriptors.append({**descriptor, "controller": controller, "source_object": battlefield_id, "trigger_kind": "triggered", "batch_id": batch_id, "batch_sequence": 0,
                                "scored_battlefield": battlefield_id, "how": how, "scope": "battlefield", "source_identity": battlefield_identity(effect_state, battlefield_id) or f"{battlefield_id}@0"})
    return descriptors


def score_battlefield(effect_state: dict[str, Any], player: str, battlefield_id: str, how: str, turn_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Core 469–471 on a copy of the effect state: once per Battlefield per
    turn (470); up to one point (471.1); a Conquer that would reach the
    Victory Score gains the Final Point only if every Battlefield was scored
    this turn, otherwise the player draws instead (471.1.b.1) — a draw that
    would Burn Out raises ScoringUnsupported so the caller commits nothing.
    Returns (next effect, record, Score trigger descriptors)."""
    victory_score, problem = mode_of_play(effect_state)
    if problem is not None:
        raise problem
    working = copy.deepcopy(effect_state)
    ledger_before = scored_this_turn(working, player, turn_id)
    record: dict[str, Any] = {"player": player, "battlefield": battlefield_id, "how": how, "turn_id": turn_id, "points_before": points_of(working, player)}
    if battlefield_id in ledger_before:
        record.update({"scored": False, "reason": "already_scored_this_turn", "points_after": record["points_before"], "rule_locators": ["Core 470", "Core 471.2.c"]})
        return working, record, []
    ledger = ledger_before + [battlefield_id]
    working["players"][player]["scored_this_turn"] = {turn_id: ledger}
    if how == "conquer" and record["points_before"] + 1 >= victory_score:
        if set(ledger) == set(working["battlefields"]):
            working["players"][player]["points"] = record["points_before"] + 1
            record.update({"scored": True, "gain": "final_point", "rule_locators": ["Core 469.1", "Core 471.1.b", "Core 471.1.b.1"]})
        else:
            deck = working["players"][player]["zones"]["main_deck"]
            if not deck:
                raise ScoringUnsupported("burn_out", f"{player} would draw a card instead of the Final Point (471.1.b.1) from an empty Main Deck: Burn Out is not modelled (G3), so the whole control/score transaction is refused", ["Core 471.1.b.1", "Core 431"])
            drawn = deck.pop(0)
            working["players"][player]["zones"]["hand"].append(drawn)
            record.update({"scored": True, "gain": "draw_instead", "drew": drawn, "identity_after": _bump_identity(working, drawn), "rule_locators": ["Core 469.1", "Core 471.1.b", "Core 471.1.b.1", "Core 124"]})
    else:
        working["players"][player]["points"] = record["points_before"] + 1
        record.update({"scored": True, "gain": "point", "rule_locators": ["Core 469.1" if how == "conquer" else "Core 469.2", "Core 471.1"] + (["Core 471.1.a.1"] if how == "hold" else [])})
    record["points_after"] = points_of(working, player)
    triggers = _score_triggers(working, player, battlefield_id, how, turn_id)  # 383.4.c.2.c: a replaced point still triggers
    record["triggers"] = [t["trigger_id"] for t in triggers]
    return working, record, triggers


# ---------------------------------------------------- control resolution --

def resolve_battlefield_control(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0009 §2, §4: after a decided Combat (466.5) or a closing Non-Combat
    Showdown (348.2.a), the one player whose Units remain establishes control
    if they did not hold it, Conquers unless already scored this turn, and
    their Score triggers form the chain; Contested is cleared (466.5.a). After
    a Combat with no Units left the Battlefield becomes Uncontrolled
    (466.5.b); after a Showdown with no Units left nothing changes here and
    the next board Cleanup decides (323.6). One transaction: all or nothing."""
    base = _base("resolve_battlefield_control", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    record = timing_state.get("combat")
    showdown = timing_state["showdown"]
    if record is not None and record.get("status") == "result_determined" and not record.get("result", {}).get("restage_required"):
        source, battlefield_id = "combat", record["battlefield"]
    elif record is not None and record.get("status") == "result_determined":
        return _refuse(base, "control_resolution_not_pending", "a both-remain No Result stages the Combat again (466.3.d.1); no control is established", ["Core 466.3.d.1"])
    elif showdown.get("active") and showdown.get("closing") and showdown.get("kind") == "non_combat":
        source, battlefield_id = "non_combat_showdown", showdown["battlefield"]
    else:
        return _refuse(base, "control_resolution_not_pending", "control is resolved after a decided Combat (466.5) or a closed Non-Combat Showdown (348.2); neither is pending", ["Core 466.5", "Core 348.2"])
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"]:
        return _refuse(base, "combat_chain_unfinished", "the chain and outstanding tasks must be finished first (466.4, 466.6)", ["Core 466.4", "Core 466.6"])
    if battlefield_id not in effect_state["battlefields"]:
        return _invalid(base, [f"battlefield {battlefield_id!r} is not in the state"])
    present = units_at(effect_state, battlefield_id)
    remaining = sorted(present)
    battlefield = effect_state["battlefields"][battlefield_id]
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    next_effect = copy.deepcopy(effect_state)
    scoring = None
    triggers: list[dict[str, Any]] = []
    if len(remaining) == 1:
        player = remaining[0]
        if battlefield.get("controller") == player:
            control_step = "controller_unchanged"
        else:
            next_effect["battlefields"][battlefield_id]["controller"] = player
            try:
                next_effect, scoring, triggers = score_battlefield(next_effect, player, battlefield_id, "conquer", turn_id)
            except ScoringUnsupported as exc:
                return _unsupported(base, exc.code, exc.reason, exc.locators, source=source, would_establish_control=player)
            control_step = "control_established"
        next_effect["battlefields"][battlefield_id]["contested"] = False
        next_effect["battlefields"][battlefield_id]["contested_by"] = None
    elif not remaining:
        if source == "combat":
            next_effect["battlefields"][battlefield_id]["controller"] = None
            next_effect["battlefields"][battlefield_id]["contested"] = False
            next_effect["battlefields"][battlefield_id]["contested_by"] = None
            control_step = "uncontrolled"
        else:
            control_step = "deferred_to_board_cleanup"  # ADR-0009 §4: 466.5.b belongs to Combat; 323.6 decides later
    else:
        return _unsupported(base, "showdown_participants_inconsistent" if source != "combat" else "combat_participants_inconsistent",
                            f"Units of {remaining} are at {battlefield_id}; a decided Combat or a Non-Combat Showdown cannot end with both present (348.2, 466.3)", ["Core 348.2", "Core 466.3"])
    from resolution_bridge import _settle_trigger_orders
    failure = _settle_trigger_orders(triggers, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    if source == "combat":
        next_timing["combat"]["status"] = "control_resolved"
        next_timing["combat"]["control"] = {"step": control_step, "controller_after": next_effect["battlefields"][battlefield_id].get("controller"), "scoring": scoring}
    else:
        next_timing["showdown"] = {"active": False, "kind": None, "focus": None}
        next_timing["priority"] = next_timing["turn_player"] if next_timing.get("phase") == "main" else None
    scheduled = schedule_triggered_items(next_timing, triggers)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "Score triggers could not be scheduled", ["Core 471.2"], trigger_result=scheduled)
    trace = {"source": source, "battlefield": battlefield_id, "remaining": remaining, "control_step": control_step, "controller_before": battlefield.get("controller"),
             "controller_after": next_effect["battlefields"][battlefield_id].get("controller"), "scoring": scoring, "scheduled_triggers": [t["trigger_id"] for t in triggers],
             "trigger_schedule": scheduled.get("transition"), "victory_check": victory_check(next_effect), "atomic": True}
    return _commit(base, scheduled["next_state"], next_effect, trace=trace,
                   locators=["Core 190.4", "Core 466.5", "Core 466.5.a", "Core 466.5.b", "Core 466.5.d", "Core 466.5.e", "Core 348.2.a", "Core 348.2.a.1", "Core 469.1", "Core 470", "Core 471", "Core 471.2"])


# ------------------------------------------------------------------------ CLI --

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


STEPS = {"resolve": resolve_battlefield_control}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicle Battlefield control and scoring procedures (ADR-0009)")
    parser.add_argument("step", choices=sorted(STEPS))
    parser.add_argument("timing_state", type=Path)
    parser.add_argument("effect_state", type=Path)
    parser.add_argument("--decisions", type=Path)
    args = parser.parse_args(argv)
    try:
        decisions = _load(args.decisions) if args.decisions else None
        output = STEPS[args.step](_load(args.timing_state), _load(args.effect_state), decisions)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
