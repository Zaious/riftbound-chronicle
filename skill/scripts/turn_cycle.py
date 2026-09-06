#!/usr/bin/env python3
"""
The Start of Turn state machine and the turn transition — ADR-0010 §1, §6–9.

Core 315: Awaken → Beginning (Beginning Step, Scoring Step) → Channel → Draw,
then the Main Phase begins (316.1). Each procedure here accepts only the
phase and typed `turn_progress` the previous one left, every phase
transition makes a Cleanup outstanding (319.2), and during 315 no
discretionary action is legal. `begin_turn` is the turn transition (317.3):
the first turn keeps the selected first player, later turns advance in Turn
Order; the First Turn Process comes from the Mode of Play (483.7) — the
sanctioned catalogue or explicit facts — never from a guess. The Scoring
Step itself is G2's `run_scoring_step`.
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

from battlefield_control import open_showdown, run_board_cleanup, stage_showdown, victory_check  # noqa: E402
from combat import IN_PROGRESS as COMBAT_IN_PROGRESS, _base as _combat_base, _commit, _invalid, _refuse, _unsupported, _validate_both, combined_input_hash, open_combat, stage_combat, sync_combat_designations  # noqa: E402
from effect_ir import DEFAULT_TURN_ID, ExternalInputRequired, IllegalDecision, PlayerSelectionRequired, find_location, hash_value, object_identity, perform_draw, perform_lethal_cleanup, zone_class  # noqa: E402
from resolution_bridge import TURN_STEP_VERSION, _settle_trigger_orders  # noqa: E402
from rules_core import CLEANUP_TASK, START_OF_TURN_PHASES, apply_terminal_event, is_terminal, schedule_triggered_items, state_hash, terminal_record  # noqa: E402
import engine_decisions as _ed  # noqa: E402

# Core 484–489: the sanctioned Modes of Play this slice can read. `match`
# carries Best-of / Game Win semantics (486.6) and `magma_chamber` teams
# (489.8.d); both are unsupported as a whole rather than half-read.
MODE_CATALOGUE = {
    "duel": {"players": 2, "victory_score": 8, "teams": False, "first_turn": {"extra_channel": ["second"], "skip_draw": []}, "rule_locators": ["Core 485.2", "Core 485.3", "Core 485.7"]},
    "skirmish": {"players": 3, "victory_score": 8, "teams": False, "first_turn": {"extra_channel": ["last"], "skip_draw": ["first"]}, "rule_locators": ["Core 487.2", "Core 487.3", "Core 487.7"]},
    "war": {"players": 4, "victory_score": 8, "teams": False, "first_turn": None, "rule_locators": ["Core 488.2", "Core 488.3"]},
}
UNSUPPORTED_MODES = {"match": ("match_mode", "the Match mode carries Best-of and Game Win semantics (486.6) this slice does not model; it is not read for its Victory Score alone", ["Core 486.6", "Core 486.6.a"]),
                     "magma_chamber": ("team_scoring", "Magma Chamber is a team mode (489.6.a, 489.8.d); teams are not modelled", ["Core 489.6.a", "Core 489.8.d"])}
READYABLE_KINDS = {"unit", "gear", "rune"}
PHASE_TRIGGER_FIELDS = {"beginning": ("beginning_phase_triggers", "your_beginning_phase", ["Core 315.2.a", "Core 315.2.a.1", "Core 383.1"]),
                        "main": ("main_phase_triggers", "your_main_phase", ["Core 316.2", "Core 316.4", "Core 383.1"])}


def _base(step: str, timing_state: dict[str, Any], effect_state: dict[str, Any]) -> dict[str, Any]:
    return {**_combat_base(step, timing_state, effect_state), "schema_version": TURN_STEP_VERSION}


def _quiet(timing_state: dict[str, Any]) -> str | None:
    if timing_state["chain"]["items"]:
        return "chain_not_empty"
    if timing_state["outstanding_tasks"]:
        return "outstanding_tasks_pending"
    if timing_state["showdown"]["active"]:
        return "showdown_ongoing"
    combat = timing_state.get("combat")
    if combat is not None and combat["status"] in COMBAT_IN_PROGRESS:
        return "combat_ongoing"
    return None


def _progress(timing_state: dict[str, Any]) -> dict[str, Any]:
    return timing_state.get("turn_progress") or {}


def _phase_refusal(base: dict[str, Any], timing_state: dict[str, Any], wanted: str, flag: str | None, locators: list[str]) -> dict[str, Any] | None:
    if timing_state.get("phase") != wanted:
        return _refuse(base, "phase_order", f"this step belongs to the {wanted} phase; the turn is in {timing_state.get('phase')!r} (315)", locators)
    if flag is not None and _progress(timing_state).get(flag) is not True:
        return _refuse(base, "phase_step_incomplete", f"turn_progress.{flag} is not set; the previous step of the {wanted} phase has not completed", locators)
    if code := _quiet(timing_state):
        return _refuse(base, code, "Start of Turn steps run with an empty chain, no outstanding task and no Showdown or Combat (315, 319.2)", locators + ["Core 319.2"])
    return None


# ------------------------------------------------------------- Mode of Play --

def first_turn_process(timing_state: dict[str, Any], effect_state: dict[str, Any], player: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The First Turn Process for `player` (483.7): (facts, problem). Facts are
    {extra_channel: bool, skip_draw: bool, source}; a problem is an
    unsupported result's (code, reason, locators)."""
    mode = effect_state.get("mode") if isinstance(effect_state.get("mode"), dict) else {}
    order = timing_state["turn_order"]
    mode_id = mode.get("id")
    if mode_id in UNSUPPORTED_MODES:
        return None, {"code": UNSUPPORTED_MODES[mode_id][0], "reason": UNSUPPORTED_MODES[mode_id][1], "locators": UNSUPPORTED_MODES[mode_id][2]}
    if mode_id in MODE_CATALOGUE:
        entry = MODE_CATALOGUE[mode_id]
        problems = []
        if len(timing_state["players"]) != entry["players"]:
            problems.append(f"mode {mode_id} is a {entry['players']}-player mode; the state has {len(timing_state['players'])}")
        if mode.get("victory_score") != entry["victory_score"] or bool(mode.get("teams", False)) != entry["teams"]:
            problems.append(f"mode {mode_id} has Victory Score {entry['victory_score']} and no teams; the state says {mode.get('victory_score')} / teams={mode.get('teams', False)}")
        if problems:
            return None, {"code": "invalid_mode", "reason": "; ".join(problems), "locators": entry["rule_locators"], "invalid": True}
        if entry["first_turn"] is None and "first_turn" not in mode:
            return None, {"code": "first_turn_process_unknown", "reason": f"the First Turn Process of mode {mode_id} is not in the catalogue; supply mode.first_turn explicitly (483.7)", "locators": entry["rule_locators"] + ["Core 483.7"]}
        if "first_turn" not in mode:
            seats = {"first": order[0], "second": order[1] if len(order) > 1 else None, "last": order[-1]}
            extra = [seats[s] for s in entry["first_turn"]["extra_channel"]]
            skip = [seats[s] for s in entry["first_turn"]["skip_draw"]]
            return {"extra_channel": player in extra, "skip_draw": player in skip, "source": f"mode:{mode_id}", "rule_locators": entry["rule_locators"]}, None
    explicit = mode.get("first_turn")
    if isinstance(explicit, dict):
        return {"extra_channel": player in explicit.get("extra_channel", []), "skip_draw": player in explicit.get("skip_draw", []), "source": "mode.first_turn", "rule_locators": ["Core 483.7"]}, None
    return None, {"code": "first_turn_process_unknown", "reason": f"{player} starts their first turn and neither mode.id nor mode.first_turn says how the First Turn Process applies (483.7); the engine does not guess", "locators": ["Core 483.7"]}


# ----------------------------------------------------------- turn transition --

def begin_turn(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 317.3 / 315: start a turn. From `setup` the selected first player
    keeps the turn; from an expired Ending Phase the next player in Turn Order
    becomes the Turn Player, turn_id advances, the per-turn ledger is pruned
    and the Ending Step record cleared. turns_taken increments for the player
    starting the turn; the First Turn Process is read before the increment
    and recorded in turn_progress. The transition makes a Cleanup outstanding."""
    base = _base("begin_turn", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    phase = timing_state.get("phase")
    if code := _quiet(timing_state):
        return _refuse(base, code, "a turn begins with an empty chain, no outstanding task and no Showdown or Combat (317.3)", ["Core 317.3"])
    taken = dict(timing_state.get("turns_taken") or {p: 0 for p in timing_state["players"]})
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    if phase == "setup":
        if any(taken.values()) or timing_state.get("ending_step"):
            return _refuse(base, "setup_already_left", "setup is the state before the first turn; turns have already been taken", ["Core 315", "Core 317.3"])
        player = timing_state["turn_player"]  # ADR-0010 §6: the selected first player keeps the first turn
        next_turn_id = turn_id
        path = "first_turn"
    elif phase == "ending":
        if (timing_state.get("ending_step") or {}).get("status") != "expired":
            return _refuse(base, "ending_not_expired", "the next turn follows the Expiration Step (317.2, 317.3); run_expiration_step has not completed", ["Core 317.2", "Core 317.3"])
        order = timing_state["turn_order"]
        player = order[(order.index(timing_state["turn_player"]) + 1) % len(order)]
        prefix, _, number = turn_id.rpartition("-")
        if not number.isdigit():
            return _invalid(base, [f"turn_id {turn_id!r} must end in -<n> to advance (ADR-0010 §6)"])
        next_turn_id = f"{prefix or 'turn'}-{int(number) + 1}"
        path = "next_turn"
    else:
        return _refuse(base, "phase_order", f"a turn begins from setup or from an expired Ending Phase, not from {phase!r}", ["Core 315", "Core 317.3"])
    facts, problem = (first_turn_process(timing_state, effect_state, player) if taken.get(player, 0) == 0 else ({"extra_channel": False, "skip_draw": False, "source": "not_first_turn", "rule_locators": ["Core 483.7"]}, None))
    if problem is not None:
        if problem.get("invalid"):
            return _invalid(base, [problem["reason"]])
        return _unsupported(base, problem["code"], problem["reason"], problem["locators"], player=player)
    taken[player] = taken.get(player, 0) + 1
    next_timing = copy.deepcopy(timing_state)
    next_timing.update({"phase": "awaken", "turn_player": player, "priority": None, "turns_taken": taken,
                        "turn_progress": {"turn_id": next_turn_id, "first_turn": {"extra_channel": facts["extra_channel"], "skip_draw": facts["skip_draw"], "source": facts["source"]}},
                        "outstanding_tasks": [CLEANUP_TASK]})
    next_timing.pop("ending_step", None)
    next_timing["showdown"] = {"active": False, "kind": None, "focus": None}
    next_effect = copy.deepcopy(effect_state)
    next_effect["turn_id"] = next_turn_id
    for pl in next_effect["players"].values():
        if "scored_this_turn" in pl:
            pl["scored_this_turn"] = {next_turn_id: pl["scored_this_turn"].get(next_turn_id, [])}
    trace = {"path": path, "turn_player": player, "turn_id": next_turn_id, "turns_taken": taken, "first_turn": next_timing["turn_progress"]["first_turn"], "first_turn_locators": facts["rule_locators"],
             "cleanup_outstanding": True}
    return _commit(base, next_timing, next_effect, trace=trace, locators=["Core 115", "Core 315", "Core 317.3", "Core 319.2", "Core 483.7"])


# ------------------------------------------------------------ Start of Turn --

def run_awaken_step(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 315.1, 415.3.a: the Turn Player readies, at once, every Board object
    they control that can be readied; a known or unknown ready blocker whose
    rule this slice lacks (Stun, 423) is unsupported. Writes awaken_complete."""
    base = _base("run_awaken_step", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if problem := _phase_refusal(base, timing_state, "awaken", None, ["Core 315.1"]):
        return problem
    if _progress(timing_state).get("awaken_complete"):
        return _refuse(base, "step_already_complete", "the Awaken step already completed this turn", ["Core 315.1"])
    player = timing_state["turn_player"]
    next_effect = copy.deepcopy(effect_state)
    readied, already, blocked = [], [], []
    for object_id in sorted(next_effect["objects"]):
        obj = next_effect["objects"][object_id]
        if obj.get("controller") != player or obj.get("kind") not in READYABLE_KINDS or zone_class(find_location(next_effect, object_id)) != "board":
            continue
        if obj.get("stunned"):
            blocked.append(object_id)
        elif obj.get("exhausted"):
            obj["exhausted"] = False
            readied.append(object_id)
        else:
            already.append(object_id)
    if blocked:
        return _unsupported(base, "ready_blocker_unknown", f"{blocked} carry a ready blocker (Stun, 423) whose complete rule this slice does not model; the Awaken step is not guessed around it", ["Core 315.1", "Core 415.1.b", "Core 423"], blocked=blocked)
    next_timing = copy.deepcopy(timing_state)
    next_timing["turn_progress"] = {**_progress(timing_state), "awaken_complete": True}
    trace = {"player": player, "readied": readied, "already_ready": already, "simultaneous": True}
    return _commit(base, next_timing, next_effect, trace=trace, locators=["Core 315.1", "Core 315.1.b", "Core 415.1.b", "Core 415.1.c", "Core 415.3.a"])


def _phase_triggers(effect_state: dict[str, Any], player: str, phase: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """ADR-0010 §8: the Turn Player's active Board sources' 'At the start of
    your Beginning / Main Phase' abilities, as one batch. Opponent or global
    watchers are not claimed."""
    field, scope, locators = PHASE_TRIGGER_FIELDS[phase]
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    descriptors, evaluated = [], []
    for object_id in sorted(effect_state["objects"]):
        obj = effect_state["objects"][object_id]
        for descriptor in obj.get(field, []) or []:
            record = {"trigger_id": descriptor["trigger_id"], "source_object": object_id, "controller": descriptor["controller"], "scheduled": False}
            if obj.get("controller") != player or zone_class(find_location(effect_state, object_id)) != "board":
                record["reason"] = "not the turn player's board object"
                evaluated.append(record); continue
            if descriptor.get("scope", scope) != scope:
                record["reason"] = f"scope {descriptor.get('scope')!r} is not {scope}"
                evaluated.append(record); continue
            condition = descriptor.get("condition")
            if condition is not None and condition["kind"] == "at_battlefield":
                location = find_location(effect_state, object_id)
                if location is None or location[0] != "battlefield":
                    record["reason"] = "condition at_battlefield not met (383.2.a.1)"
                    evaluated.append(record); continue
            copied = {k: v for k, v in descriptor.items() if k not in {"condition", "scope"}}
            copied.update({"trigger_kind": "triggered", "batch_sequence": 0, "batch_id": f"{phase}:{turn_id}", "scope": scope, "source_identity": object_identity(effect_state, object_id) or f"{object_id}@0"})
            descriptors.append(copied)
            record["scheduled"] = True
            evaluated.append(record)
    return descriptors, evaluated


def enter_beginning_phase(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 315.2: after the Awaken step, enter the Beginning Phase — the
    Beginning Step's game effects (315.2.a) are scheduled as one batch, the
    Scoring Step becomes outstanding (315.2.b.1; it waits for that chain) and
    the phase transition makes a Cleanup outstanding (319.2)."""
    base = _base("enter_beginning_phase", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if problem := _phase_refusal(base, timing_state, "awaken", "awaken_complete", ["Core 315.1", "Core 315.2"]):
        return problem
    player = timing_state["turn_player"]
    descriptors, evaluated = _phase_triggers(effect_state, player, "beginning")
    failure = _settle_trigger_orders(descriptors, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    next_timing["phase"] = "beginning"
    next_timing["priority"] = None
    next_timing["turn_progress"] = {**_progress(timing_state), "beginning_entered": True}
    next_timing["outstanding_tasks"] = [CLEANUP_TASK, "scoring_step"]
    scheduled = schedule_triggered_items(next_timing, descriptors)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "Beginning Step triggers could not be scheduled", ["Core 315.2.a"], trigger_result=scheduled)
    trace = {"player": player, "beginning_triggers": evaluated, "scheduled_triggers": [d["trigger_id"] for d in descriptors], "trigger_schedule": scheduled.get("transition"), "tasks": next_timing["outstanding_tasks"]}
    return _commit(base, scheduled["next_state"], copy.deepcopy(effect_state), trace=trace, locators=["Core 315.2", "Core 315.2.a", "Core 315.2.a.1", "Core 315.2.b.1", "Core 319.2"])


def run_channel_step(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 315.3, 430: after the Scoring Step and its Cleanups, enter the
    Channel Phase and Channel two Runes (one more on a first turn the Mode of
    Play says so, 485.7 / 487.7), as many as the Rune Deck has (430.3), ready
    (430.2.a). Writes channel_complete; the transition makes a Cleanup."""
    base = _base("run_channel_step", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if problem := _phase_refusal(base, timing_state, "beginning", "scoring_complete", ["Core 315.2.b", "Core 315.3"]):
        return problem
    player = timing_state["turn_player"]
    extra = 1 if (_progress(timing_state).get("first_turn") or {}).get("extra_channel") else 0
    count = 2 + extra
    next_effect = copy.deepcopy(effect_state)
    rune_deck = next_effect["players"][player]["zones"]["rune_deck"]
    taken = rune_deck[:count]
    del rune_deck[:count]
    identities = {}
    for rune_id in taken:
        next_effect["objects"][rune_id]["exhausted"] = False
        next_effect["players"][player]["zones"]["base"].append(rune_id)
        from effect_ir import _bump_identity
        identities[rune_id] = _bump_identity(next_effect, rune_id)
    next_timing = copy.deepcopy(timing_state)
    next_timing["phase"] = "channel"
    next_timing["turn_progress"] = {**_progress(timing_state), "channel_complete": True}
    next_timing["outstanding_tasks"] = [CLEANUP_TASK]
    trace = {"player": player, "requested": count, "first_turn_extra": extra, "channeled": taken, "identities_after": identities, "entry_state": "ready",
             "completion": "full" if len(taken) == count else ("partial" if taken else "none"), "cleanup_outstanding": True}
    return _commit(base, next_timing, next_effect, trace=trace, locators=["Core 315.3", "Core 315.3.b", "Core 315.3.b.1", "Core 430.2.a", "Core 430.3", "Core 430.4.a", "Core 124", "Core 319.2"])


def run_draw_step(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 315.4: enter the Draw Phase and draw one through the Burn Out-aware
    Draw (315.4.b.1–315.4.b.2, 431) — skipped on a first turn the Mode of
    Play says so (487.7). An immediate Burn Out victory writes the terminal in
    this commit and stops; otherwise draw_complete is written and the
    transition makes a Cleanup."""
    base = _base("run_draw_step", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if problem := _phase_refusal(base, timing_state, "channel", "channel_complete", ["Core 315.3", "Core 315.4"]):
        return problem
    player = timing_state["turn_player"]
    turn_id = effect_state.get("turn_id", DEFAULT_TURN_ID)
    next_effect = copy.deepcopy(effect_state)
    skip = bool((_progress(timing_state).get("first_turn") or {}).get("skip_draw"))
    event: dict[str, Any] | None = None
    if not skip:
        try:
            next_effect, event = perform_draw(next_effect, player, 1, decisions=engine_decisions, operation_prefix=f"burn_out:{player}:{turn_id}:draw_step")
        except (ExternalInputRequired, PlayerSelectionRequired) as exc:
            return {**base, "valid": True, "committed": False, "reason_code": exc.reason_code, "reason": str(exc), "decision_ids": exc.decision_ids, "decision_controller": exc.controller, "rule_locators": ["Core 315.4.b.1", "Core 431.2"]}
        except IllegalDecision as exc:
            return _refuse(base, "decision_controller_mismatch", str(exc), ["Core 431.2.c"])
        except NotImplementedError as exc:
            return _unsupported(base, "burn_out_unsupported", str(exc), ["Core 431"])
        except ValueError as exc:
            return _invalid(base, [str(exc)])
    next_timing = copy.deepcopy(timing_state)
    next_timing["phase"] = "draw"
    terminal = (event or {}).get("terminal_event")
    if terminal is not None:
        final_timing = apply_terminal_event(next_timing, next_effect, terminal)
        trace = {"player": player, "skipped_first_turn_draw": False, "draw": event, "terminal": terminal, "skipped_after_terminal": {"draw_complete": True, "main_phase": True}}
        return _commit(base, final_timing, next_effect, trace=trace, locators=["Core 315.4", "Core 315.4.b.1", "Core 431.3.c.1", "Core 196"])
    next_timing["turn_progress"] = {**_progress(timing_state), "draw_complete": True}
    next_timing["outstanding_tasks"] = [CLEANUP_TASK]
    trace = {"player": player, "skipped_first_turn_draw": skip, "draw": event, "cleanup_outstanding": True}
    return _commit(base, next_timing, next_effect, trace=trace, locators=["Core 315.4", "Core 315.4.b", "Core 413.2.a", "Core 319.2"] + (["Core 487.7"] if skip else []) + (["Core 315.4.b.1", "Core 315.4.b.2", "Core 431"] if event and event.get("burn_outs") else []))


def enter_main_phase(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 316.1–316.4: after the Draw Phase, the Main Phase begins — every
    Rune Pool empties (316.3), the start-of-Main game effects are scheduled
    (316.4), Priority goes to the Turn Player and the transition makes a
    Cleanup outstanding (319.2)."""
    base = _base("enter_main_phase", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if problem := _phase_refusal(base, timing_state, "draw", "draw_complete", ["Core 315.4", "Core 316.1"]):
        return problem
    player = timing_state["turn_player"]
    next_effect = copy.deepcopy(effect_state)
    emptied = {}
    for player_id, pl in next_effect["players"].items():
        emptied[player_id] = copy.deepcopy(pl["resources"])
        pl["resources"] = {"energy": 0, "power": {}}
    descriptors, evaluated = _phase_triggers(next_effect, player, "main")
    failure = _settle_trigger_orders(descriptors, engine_decisions, base)
    if failure is not None:
        return failure
    next_timing = copy.deepcopy(timing_state)
    next_timing["phase"] = "main"
    next_timing["priority"] = player
    next_timing["turn_progress"] = {**_progress(timing_state), "main_entered": True}
    next_timing["outstanding_tasks"] = [CLEANUP_TASK]
    scheduled = schedule_triggered_items(next_timing, descriptors)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "Main Phase triggers could not be scheduled", ["Core 316.4"], trigger_result=scheduled)
    trace = {"player": player, "empty_rune_pools": emptied, "main_triggers": evaluated, "scheduled_triggers": [d["trigger_id"] for d in descriptors], "trigger_schedule": scheduled.get("transition"), "cleanup_outstanding": True}
    return _commit(base, scheduled["next_state"], next_effect, trace=trace, locators=["Core 316.1", "Core 316.2", "Core 316.3", "Core 316.4", "Core 319.2"])


# ------------------------------------------------------------------ Cleanup --

CLEANUP_ITERATION_BOUND = 8


def _unattached_at_battlefields(effect_state: dict[str, Any]) -> list[str]:
    """Core 323.7 applies to non-Unit Gear and Runes at Battlefields; this
    slice has no attachment model, so any such object there is 323.7's case."""
    found = []
    for object_id in sorted(effect_state["objects"]):
        obj = effect_state["objects"][object_id]
        location = find_location(effect_state, object_id)
        if obj.get("kind") in {"gear", "rune"} and location is not None and location[0] == "battlefield":
            found.append(object_id)
    return found


def run_cleanup(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0010 §5 / Core 323: one Cleanup as one atomic run. Steps 1–10a in
    order on a working state — 1 terminal, 2 designations, 3a/3b lethal
    (death triggers go Pending on the chain and nothing resolves, 320), 4
    control loss, 5 (323.7, refused as unsupported whenever it applies), 6
    Showdown staging, 7 Combat staging, 8 Contested maintenance, 9 Showdown
    opening, 10 Combat opening — then, when the run changed anything, the
    322 follow-up Cleanups on the same working state until one changes
    nothing. A terminal at step 1 ends the run with the rest recorded as
    skipped_after_terminal. Any decision_required or unsupported step commits
    nothing. The outstanding Cleanup task, if first, is consumed."""
    base = _base("run_cleanup", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    tasks = list(timing_state["outstanding_tasks"])
    if tasks and tasks[0] != CLEANUP_TASK and CLEANUP_TASK in tasks:
        return _refuse(base, "task_order", f"the outstanding task {tasks[0]!r} precedes the Cleanup; tasks are handled in order", ["Core 318", "Core 319"])
    consumed = bool(tasks) and tasks[0] == CLEANUP_TASK
    working_t = copy.deepcopy(timing_state)
    if consumed:
        working_t["outstanding_tasks"] = tasks[1:]
    working_e = copy.deepcopy(effect_state)
    order_map, choice_map = _ed.replacement_maps(engine_decisions)
    iterations: list[dict[str, Any]] = []
    terminal_written = False

    rebinding: list[dict[str, Any]] = []

    def bound_to(t: dict[str, Any], e: dict[str, Any], iteration: int = 0, step: str = "") -> dict[str, Any] | None:
        """The envelope was bound to this run's input (checked above). Each
        sub-procedure receives it rebound to the working state it acts on and
        revalidates every decision against that state's own candidate set
        (a location not staged now is refused there); the rebinding is
        traced (Codex review-fix on ADR-0010 §5)."""
        if engine_decisions is None:
            return None
        rebound = combined_input_hash(t, e)
        rebinding.append({"iteration": iteration, "step": step, "derived_from_input_hash": engine_decisions["input_hash"], "rebound_input_hash": rebound,
                          "decision_ids": [d.get("decision_id") for d in engine_decisions.get("decisions", [])], "revalidated_against": "working_state_candidates"})
        return {**engine_decisions, "input_hash": rebound}

    def snapshot(t: dict[str, Any], e: dict[str, Any]) -> tuple[str, str]:
        """What 322 compares: the states without bookkeeping that changes on
        every pass (an empty staging set, the designation sync counter)."""
        normalized = {**t, "staged_showdowns": t.get("staged_showdowns", [])}
        if normalized.get("combat") is not None:
            normalized["combat"] = {k: v for k, v in normalized["combat"].items() if k != "sync_count"}
        return state_hash(normalized), hash_value(e)

    def sub(result: dict[str, Any], step: str) -> dict[str, Any] | None:
        """A sub-procedure's non-commit: decisions and unsupported end the whole run uncommitted."""
        if result.get("committed"):
            return None
        if result.get("valid") is False:
            return _invalid(base, [f"step {step}: {result.get('reason')}"])
        if result.get("unsupported"):
            return _unsupported(base, result.get("reason_code", "unsupported_cleanup_step"), f"step {step}: {result.get('reason')}", result.get("rule_locators", []), cleanup_step=step)
        return {**base, "valid": True, "committed": False, "cleanup_step": step, **{k: v for k, v in result.items() if k in {"reason_code", "reason", "decision_ids", "decision_controller", "options", "batch_id", "trigger_ids", "rule_locators", "replacement_decision_required", "replacement_ids", "event_ids"}}}

    for index in range(CLEANUP_ITERATION_BOUND):
        before = snapshot(working_t, working_e)
        record: dict[str, Any] = {"iteration": index, "steps": []}
        iterations.append(record)
        # 1 — Core 323.1
        facts = victory_check(working_e)
        if facts.get("available"):
            if facts["strict_leader"] is not None:
                working_t["terminal"] = terminal_record(working_e, "victory_score", facts["strict_leader"], derived=True, extra={"immediate": False, "source": "cleanup_step_1"})
                record["steps"].append({"step": 1, "outcome": "ended", "winner": facts["strict_leader"]})
                record["skipped_after_terminal"] = ["2", "3a", "3b", "4", "5", "6", "7", "8", "9", "10"]
                terminal_written = True
                break
            record["steps"].append({"step": 1, "outcome": "continue_tied" if facts["tied_at_threshold"] else "below_threshold"})
        elif facts.get("reason") == "mode_unknown" and not any(int(p.get("points", 0)) for p in working_e["players"].values()):
            record["steps"].append({"step": 1, "outcome": "no_points_without_mode"})
        else:
            return _unsupported(base, facts.get("reason", "mode_unknown"), "Cleanup step 1 needs the Mode of Play to judge the victory condition (323.1, 456.3)", ["Core 323.1", "Core 194.3"], cleanup_step="1")
        # 2 — Core 323.2
        combat = working_t.get("combat")
        if combat is not None and combat["status"] in COMBAT_IN_PROGRESS:
            synced = sync_combat_designations(working_t, working_e, bound_to(working_t, working_e, index, "2"))
            if failure := sub(synced, "2"):
                return failure
            working_t, working_e = synced["next_timing_state"], synced["next_effect_state"]
            record["steps"].append({"step": 2, "outcome": "synchronized", "triggers": synced["trace"].get("scheduled_triggers", [])})
        # 3a / 3b — Core 323.3–323.5
        lethal = perform_lethal_cleanup(working_e, replacement_event_order=order_map, replacement_choices=choice_map)
        if lethal.get("committed") is not True:
            if lethal.get("replacement_decision_required"):
                return {**base, "valid": True, "committed": False, "cleanup_step": "3a", "replacement_decision_required": True, "reason": lethal.get("reason"),
                        "replacement_ids": lethal.get("batch_result", {}).get("replacement_ids", []), "event_ids": lethal.get("batch_result", {}).get("event_ids", []), "decision_controller": lethal.get("batch_result", {}).get("decision_controller")}
            if lethal.get("unsupported"):
                return _unsupported(base, "lethal_cleanup_unsupported", f"step 3: {lethal.get('reason')}", ["Core 323.4", "Core 323.5"], cleanup_step="3")
            return _invalid(base, [f"step 3: {lethal.get('reason') or '; '.join(lethal.get('errors', []))}"])
        working_e = lethal["next_state"]
        death_triggers = [dict(t) for t in lethal.get("pending_triggers", [])]
        for trigger in death_triggers:
            trigger["batch_sequence"] = index * 100 + int(trigger.get("batch_sequence", 0))
        if failure := _settle_trigger_orders(death_triggers, engine_decisions, base):
            return failure
        if death_triggers:
            scheduled = schedule_triggered_items(working_t, death_triggers)
            if scheduled.get("applied") is not True:
                return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "death triggers could not be scheduled", ["Core 323.4"], cleanup_step="3a")
            working_t = scheduled["next_state"]
        record["steps"].append({"step": 3, "outcome": "killed" if lethal.get("killed_objects") else "nothing_lethal", "killed": lethal.get("killed_objects", []), "pending_triggers": [t["trigger_id"] for t in death_triggers]})
        # 4 — Core 323.6
        board4 = run_board_cleanup(working_t, working_e, bound_to(working_t, working_e, index, "4"), steps=("control_loss",), within_cleanup=True)
        if failure := sub(board4, "4"):
            return failure
        working_e = board4["next_effect_state"]
        record["steps"].append({"step": 4, "outcome": "applied" if board4["trace"]["steps"] else "no_change", "changes": board4["trace"]["steps"]})
        # 5 — Core 323.7
        unattached = _unattached_at_battlefields(working_e)
        if unattached:
            return _unsupported(base, "gear_rune_recall_cleanup", f"step 5: {unattached} are non-Unit Gear or Runes at a Battlefield; 323.7's Recall is not modelled, so the whole Cleanup fails closed", ["Core 323.7"], cleanup_step="5", objects=unattached)
        record["steps"].append({"step": 5, "outcome": "nothing_to_recall"})
        # 6 — Core 323.8
        staged6 = stage_showdown(working_t, working_e, bound_to(working_t, working_e, index, "6"), within_cleanup=True)
        if failure := sub(staged6, "6"):
            return failure
        working_t = staged6["next_timing_state"]
        record["steps"].append({"step": 6, "outcome": staged6["trace"]["outcome"], "staged": staged6["trace"]["staged"]})
        # 7 / 7a — Core 323.9–323.10
        combat = working_t.get("combat")
        if combat is not None and combat["status"] in COMBAT_IN_PROGRESS:
            record["steps"].append({"step": 7, "outcome": "combat_in_progress", "combat_id": combat["combat_id"]})  # 460: no other Combat while one lasts
        elif working_t.get("phase") == "main":
            staged7 = stage_combat(working_t, working_e, bound_to(working_t, working_e, index, "7"), within_cleanup=True)
            if failure := sub(staged7, "7"):
                return failure
            working_t = staged7["next_timing_state"]
            record["steps"].append({"step": 7, "outcome": staged7["trace"]["outcome"], "combat_id": staged7["trace"].get("combat_id")})
        else:
            record["steps"].append({"step": 7, "outcome": "not_main_phase"})
        # 8 / 8a — Core 323.11
        board8 = run_board_cleanup(working_t, working_e, bound_to(working_t, working_e, index, "8"), steps=("contested",), within_cleanup=True)
        if failure := sub(board8, "8"):
            return failure
        working_e = board8["next_effect_state"]
        record["steps"].append({"step": 8, "outcome": "applied" if board8["trace"]["steps"] else "no_change", "changes": board8["trace"]["steps"]})
        # 9 — Core 323.12
        if working_t.get("staged_showdowns") and not working_t["showdown"]["active"] and (working_t.get("combat") is None or working_t["combat"]["status"] in {"staged", "closed"}):
            opened9 = open_showdown(working_t, working_e, bound_to(working_t, working_e, index, "9"), within_cleanup=True)
            if opened9.get("committed"):
                working_t = opened9["next_timing_state"]
                record["steps"].append({"step": 9, "outcome": "opened", "battlefield": opened9["trace"]["chosen"]})
            elif opened9.get("reason_code") in {"showdown_no_longer_staged"}:
                record["steps"].append({"step": 9, "outcome": "no_longer_staged"})
            elif failure := sub(opened9, "9"):
                return failure
        else:
            record["steps"].append({"step": 9, "outcome": "nothing_staged"})
        # 10 / 10a — Core 323.13–323.14
        combat = working_t.get("combat")
        if combat is not None and combat["status"] == "staged":
            opened10 = open_combat(working_t, working_e, bound_to(working_t, working_e, index, "10"), within_cleanup=True)
            if opened10.get("committed"):
                working_t, working_e = opened10["next_timing_state"], opened10["next_effect_state"]
                record["steps"].append({"step": 10, "outcome": "opened", "combat_id": combat["combat_id"], "triggers": opened10["trace"].get("scheduled_triggers", [])})
            elif opened10.get("reason_code") in {"showdown_elsewhere", "combat_no_longer_staged"}:
                record["steps"].append({"step": 10, "outcome": opened10["reason_code"]})
            elif failure := sub(opened10, "10"):
                return failure
        else:
            record["steps"].append({"step": 10, "outcome": "nothing_staged"})
        after = snapshot(working_t, working_e)
        record["changed"] = after != before
        if after == before:
            break  # 322: no event of this iteration calls for another Cleanup
    else:
        return _unsupported(base, "cleanup_iterations_exceeded", f"{CLEANUP_ITERATION_BOUND} follow-up Cleanups (322) did not reach a stable state", ["Core 322"])
    trace = {"task_consumed": consumed, "iterations": iterations, "terminal_written": terminal_written, "pending_items_kept": [i["id"] for i in working_t["chain"]["items"]],
             "decision_rebinding": rebinding, "victory_check": victory_check(working_e), "atomic": True}
    return _commit(base, working_t, working_e, trace=trace, locators=["Core 318", "Core 319", "Core 320", "Core 322", "Core 322.1", "Core 323", "Core 323.1", "Core 323.2", "Core 323.4", "Core 323.5", "Core 323.6", "Core 323.8", "Core 323.9", "Core 323.11", "Core 323.12", "Core 323.13", "Core 323.14"])


STEPS = {"begin_turn": begin_turn, "awaken": run_awaken_step, "enter_beginning": enter_beginning_phase, "channel": run_channel_step, "draw": run_draw_step, "enter_main": enter_main_phase, "run_cleanup": run_cleanup}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chronicle Start of Turn and turn transition procedures (ADR-0010)")
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
