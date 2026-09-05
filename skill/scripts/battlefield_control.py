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
from combat import IN_PROGRESS as COMBAT_IN_PROGRESS, _base as _combat_base, _commit, _invalid, _refuse, _unsupported, _validate_both, combined_input_hash, units_at  # noqa: E402
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
        next_timing["staged_showdowns"] = [s for s in next_timing.get("staged_showdowns", []) if s["battlefield"] != battlefield_id]
    scheduled = schedule_triggered_items(next_timing, triggers)
    if scheduled.get("applied") is not True:
        return _refuse(base, scheduled.get("reason_code", "trigger_schedule_failed"), "; ".join(scheduled.get("errors", [])) or "Score triggers could not be scheduled", ["Core 471.2"], trigger_result=scheduled)
    trace = {"source": source, "battlefield": battlefield_id, "remaining": remaining, "control_step": control_step, "controller_before": battlefield.get("controller"),
             "controller_after": next_effect["battlefields"][battlefield_id].get("controller"), "scoring": scoring, "scheduled_triggers": [t["trigger_id"] for t in triggers],
             "trigger_schedule": scheduled.get("transition"), "victory_check": victory_check(next_effect), "atomic": True}
    return _commit(base, scheduled["next_state"], next_effect, trace=trace,
                   locators=["Core 190.4", "Core 466.5", "Core 466.5.a", "Core 466.5.b", "Core 466.5.d", "Core 466.5.e", "Core 348.2.a", "Core 348.2.a.1", "Core 469.1", "Core 470", "Core 471", "Core 471.2"])


# ------------------------------------------------ Non-Combat Showdowns --

def _ongoing_at(timing_state: dict[str, Any], battlefield_id: str) -> str | None:
    """What is ongoing at the Battlefield (ADR-0009 §9: a merely staged
    Showdown or Combat is not ongoing and exempts nothing)."""
    showdown = timing_state["showdown"]
    if showdown.get("active") and showdown.get("battlefield") == battlefield_id:
        return "showdown"
    combat = timing_state.get("combat")
    if combat is not None and combat["battlefield"] == battlefield_id and combat["status"] in COMBAT_IN_PROGRESS:
        return "combat"
    return None


def showdown_candidates(timing_state: dict[str, Any], effect_state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Battlefields where a Non-Combat Showdown is Staged (316.8.b, 323.8,
    323.8.a, 344.2): Contested was applied, the applier's Units are present,
    no other player's Units are (that is a Combat, 461), and nothing is
    ongoing there."""
    candidates: list[dict[str, Any]] = []
    considered: list[dict[str, Any]] = []
    for battlefield_id in sorted(effect_state["battlefields"]):
        battlefield = effect_state["battlefields"][battlefield_id]
        applier = battlefield.get("contested_by")
        controllers = sorted(units_at(effect_state, battlefield_id))
        record = {"battlefield": battlefield_id, "contested": bool(battlefield.get("contested")), "contested_by": applier, "controllers": controllers}
        if not battlefield.get("contested") or applier is None:
            record["verdict"] = "not_contested"
        elif applier not in controllers:
            record["verdict"] = "applier_absent"
        elif len(controllers) > 1:
            record["verdict"] = "opposing_units_present"
        elif (ongoing := _ongoing_at(timing_state, battlefield_id)) is not None:
            record["verdict"] = f"{ongoing}_ongoing"
        else:
            record["verdict"] = "staged"
            candidates.append({"battlefield": battlefield_id, "battlefield_identity": battlefield_identity(effect_state, battlefield_id) or f"{battlefield_id}@0", "contested_by": applier})
        considered.append(record)
    return candidates, considered


def _cleanup_boundary(timing_state: dict[str, Any]) -> str | None:
    if timing_state["chain"]["items"] or timing_state["outstanding_tasks"]:
        return "requires_quiet_cleanup_boundary"
    return None


def stage_showdown(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 323.8: at a quiet Cleanup boundary, rebuild the set of staged
    Non-Combat Showdowns from the board. Zero candidates is a supported no-op
    that also drops stale entries (323.8.a)."""
    base = _base("stage_showdown", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if code := _cleanup_boundary(timing_state):
        return _refuse(base, code, "Showdowns are staged during a Cleanup with nothing on the chain and no outstanding task (323.8)", ["Core 318", "Core 323.8"])
    candidates, considered = showdown_candidates(timing_state, effect_state)
    next_timing = copy.deepcopy(timing_state)
    next_timing["staged_showdowns"] = candidates
    trace = {"considered": considered, "staged": [c["battlefield"] for c in candidates], "dropped": sorted({s["battlefield"] for s in timing_state.get("staged_showdowns", [])} - {c["battlefield"] for c in candidates}),
             "outcome": "staged" if candidates else "no_staged_showdown"}
    return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=["Core 316.8.b", "Core 323.8", "Core 323.8.a", "Core 344.2"])


def open_showdown(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 323.12, 345: in a Neutral Open State with staged Non-Combat
    Showdowns and no Combat staged, the Turn Player chooses one (several need
    a location_selection `showdown_location`); it opens as a non_combat
    Showdown whose Focus goes to the player who applied Contested."""
    base = _base("open_showdown", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if code := _cleanup_boundary(timing_state):
        return _refuse(base, code, "a Showdown opens during a Cleanup with nothing on the chain and no outstanding task (323.12)", ["Core 318", "Core 323.12"])
    if timing_state["showdown"]["active"]:
        return _refuse(base, "not_neutral_open_state", "323.12 opens a Showdown only from a Neutral Open State; one is already ongoing", ["Core 323.12", "Core 344"])
    combat = timing_state.get("combat")
    if combat is not None and combat["status"] != "closed":
        return _refuse(base, "combat_staged", f"a Combat ({combat['combat_id']}) is staged or in progress; 323.12 opens Non-Combat Showdowns before 323.13 stages Combat (ADR-0009 §3)", ["Core 323.12", "Core 323.13"])
    staged = timing_state.get("staged_showdowns", [])
    if not staged:
        return _refuse(base, "no_staged_showdown", "no Non-Combat Showdown is staged; run stage_showdown at the Cleanup boundary first (323.8)", ["Core 323.8", "Core 323.12"])
    current, _ = showdown_candidates(timing_state, effect_state)
    still = {c["battlefield"]: c for c in current}
    live = [s for s in staged if s["battlefield"] in still and still[s["battlefield"]] == s]
    if not live:
        return _refuse(base, "showdown_no_longer_staged", f"none of the staged Showdowns {[s['battlefield'] for s in staged]} is still staged (323.8.a); re-run stage_showdown", ["Core 323.8.a"], staged_now=sorted(still))
    turn_player = timing_state["turn_player"]
    options = [s["battlefield"] for s in live]
    if len(live) == 1:
        chosen, selection = live[0], "sole_candidate"
    else:
        entry = next((e for e in _ed.entries(engine_decisions, kind="location_selection") if e["decision_id"] == SHOWDOWN_LOCATION_DECISION_ID), None)
        if entry is None:
            return {**base, "valid": True, "committed": False, "reason_code": "location_selection_required",
                    "reason": f"Showdowns are staged at {options}; the Turn Player {turn_player} chooses where one begins (323.12)",
                    "decision_ids": [SHOWDOWN_LOCATION_DECISION_ID], "decision_controller": turn_player, "options": options, "rule_locators": ["Core 323.12"]}
        if entry["controller"] != turn_player:
            return _refuse(base, "decision_controller_mismatch", f"the Showdown location was chosen by {entry['controller']!r}; it is the Turn Player's choice (323.12)", ["Core 323.12"])
        if entry["value"] not in options:
            return _invalid(base, [f"location_selection {SHOWDOWN_LOCATION_DECISION_ID} names {entry['value']!r}; the staged Showdowns are {options}"])
        chosen, selection = next(s for s in live if s["battlefield"] == entry["value"]), "turn_player_decision"
    next_timing = copy.deepcopy(timing_state)
    next_timing["showdown"] = {"active": True, "kind": "non_combat", "focus": chosen["contested_by"], "battlefield": chosen["battlefield"], "focus_passes": []}
    next_timing["priority"] = chosen["contested_by"]
    next_timing["staged_showdowns"] = [s for s in live if s["battlefield"] != chosen["battlefield"]]
    trace = {"options": options, "chosen": chosen["battlefield"], "selection": selection, "focus": chosen["contested_by"], "still_staged": [s["battlefield"] for s in next_timing["staged_showdowns"]]}
    return _commit(base, next_timing, copy.deepcopy(effect_state), trace=trace, locators=["Core 323.12", "Core 344.2", "Core 345", "Core 316.8.b.1.a"])


# ----------------------------------------------------------- board Cleanup --

def run_board_cleanup(timing_state: dict[str, Any], effect_state: dict[str, Any], engine_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Core 323.6, 323.11, 323.11.a in an Open State: per Battlefield with no
    ongoing Showdown or Combat, a controller with no Units there loses control
    (step 4), Contested goes where its applier has no Units (step 8), and a
    removal that leaves Units of one non-controller re-applies Contested by
    that player (323.11.a); two different non-controllers is unsupported. The
    victory facts are reported. 323.7 (Recall of Gear/Runes) is not modelled."""
    base = _base("run_board_cleanup", timing_state, effect_state)
    if problem := _validate_both(base, timing_state, effect_state, engine_decisions):
        return problem
    if code := _cleanup_boundary(timing_state):
        return _refuse(base, code, "the board Cleanup runs in an Open State with no outstanding task (323.6, 323.11)", ["Core 318", "Core 323.6", "Core 323.11"])
    next_effect = copy.deepcopy(effect_state)
    steps: list[dict[str, Any]] = []
    exempt: list[dict[str, Any]] = []
    removed: list[str] = []
    for battlefield_id in sorted(next_effect["battlefields"]):
        if (ongoing := _ongoing_at(timing_state, battlefield_id)) is not None:
            exempt.append({"battlefield": battlefield_id, "ongoing": ongoing})
            continue
        battlefield = next_effect["battlefields"][battlefield_id]
        present = units_at(next_effect, battlefield_id)
        controller = battlefield.get("controller")
        if controller is not None and controller not in present:
            battlefield["controller"] = None
            steps.append({"step": "control_lost", "battlefield": battlefield_id, "player": controller, "rule_locators": ["Core 323.6", "Core 190.4.c"]})
    for battlefield_id in sorted(next_effect["battlefields"]):
        if _ongoing_at(timing_state, battlefield_id) is not None:
            continue
        battlefield = next_effect["battlefields"][battlefield_id]
        present = units_at(next_effect, battlefield_id)
        applier = battlefield.get("contested_by")
        if battlefield.get("contested") and applier not in present:
            battlefield["contested"] = False
            battlefield["contested_by"] = None
            removed.append(battlefield_id)
            steps.append({"step": "contested_removed", "battlefield": battlefield_id, "applier": applier, "rule_locators": ["Core 323.11"]})
            others = sorted(p for p in present if p != battlefield.get("controller"))
            if len(others) > 1:
                return _unsupported(base, "contested_reapplication_ambiguous", f"Units of {others}, none of whom controls {battlefield_id}, are there after Contested was removed; 323.11.a names one applier and the engine does not choose", ["Core 323.11.a"], battlefield=battlefield_id)
            if others:
                battlefield["contested"] = True
                battlefield["contested_by"] = others[0]
                steps.append({"step": "contested_reapplied", "battlefield": battlefield_id, "applier": others[0], "rule_locators": ["Core 323.11.a"]})
    trace = {"steps": steps, "exempt": exempt, "contested_removed": removed, "victory_check": victory_check(next_effect), "gear_rune_recall": "not_modelled (323.7)"}
    return _commit(base, copy.deepcopy(timing_state), next_effect, trace=trace, locators=["Core 190.4.a", "Core 190.4.c", "Core 323.6", "Core 323.11", "Core 323.11.a"])


# ------------------------------------------------------------------------ CLI --

def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


STEPS = {"resolve": resolve_battlefield_control, "stage_showdown": stage_showdown, "open_showdown": open_showdown, "board_cleanup": run_board_cleanup}


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
