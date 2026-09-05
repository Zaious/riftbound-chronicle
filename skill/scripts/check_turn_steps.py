#!/usr/bin/env python3
"""
Gate for C-21 (ADR-0007 §6–8): entry replacements, conditional passives,
and the Ending / Expiration steps.

Must hold:
  - "I enter ready" replaces the default exhausted entry and the trace
    shows default, replacement, final; Confront's turn effect makes the
    controller's later units enter ready this turn only, not the opponent's,
    and not after expiration;
  - effective_might adds a conditional passive only while its condition
    holds: "8+ runes" counts the controller's runes on the board, ready or
    exhausted, not in the Rune Deck, not a teammate's; current_might is
    unchanged; target restrictions and lethal Cleanup read effective_might;
  - begin_ending_step needs the Main Phase, an empty chain, no tasks and no
    showdown; it schedules the turn player's end-of-turn triggers as one
    batch, honours the at_battlefield trigger condition, ignores the
    opponent's, and asks for a trigger_order decision on a same-controller
    collision;
  - run_expiration_step is illegal before begin_ending_step, while chain
    items or tasks remain, and in another phase; when legal it heals all
    units, expires this turn's modifiers and turn effects together, keeps
    another turn's, empties every pool; an unknown turn-effect kind is
    unsupported; engine-check kind turn_step and the CLI agree off-cwd.
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
from effect_ir import apply_program, current_might, effective_might, evaluate_target, hash_value, perform_lethal_cleanup, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import begin_ending_step, resolve_with_program, run_expiration_step  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, state_hash  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def unit_in_hand(state=None, **extra):
    state = copy.deepcopy(state) if state else base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update({"kind": "unit", "base_might": 2, **extra})
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return state


def play_and_resolve(state):
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"}, "cost": {"base": {"energy": 2, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}, "entry_location": {"kind": "base"}}
    played = play_card(fixture(), state, decl)
    if not played.get("committed"):
        return played
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    return resolve_with_program(timing, "unit-1", played["next_effect_state"], None)


def main() -> int:
    errors: list[str] = []

    # --- entry replacements ---------------------------------------------------------
    honed = play_and_resolve(unit_in_hand(entry_replacements=[{"mode": "entry_state", "value": "ready"}]))
    entry = honed.get("trace", {}).get("chain_card", [{}])[0] if honed.get("committed") else {}
    if not honed.get("committed") or honed["next_effect_state"]["objects"]["c1"]["exhausted"] or entry.get("default_entry_state") != "exhausted" or entry.get("entry_state") != "ready" or len(entry.get("entry_replacements", [])) != 1:
        errors.append(f"'I enter ready' did not replace the default entry: {honed.get('reason')} {entry}")
    confront_state = base_state(); confront_state["turn_id"] = "turn-7"
    granted = apply_program(confront_state, program("confront", {"op": "grant_turn_effect", "turn_effect_kind": "entry_state_for_played_units", "value": "ready", "controller": "p1", "source": "confront"}))
    if not granted.get("committed") or granted["next_state"].get("turn_effects", [{}])[0].get("turn_id") != "turn-7":
        errors.append(f"grant_turn_effect did not record a turn-stamped effect: {granted.get('reason') or granted.get('errors')}")
    else:
        mine = play_and_resolve(unit_in_hand(granted["next_state"]))
        if not mine.get("committed") or mine["next_effect_state"]["objects"]["c1"]["exhausted"]:
            errors.append("Confront's turn effect did not make the controller's unit enter ready")
        later = copy.deepcopy(granted["next_state"]); later["turn_id"] = "turn-8"
        later_entry = play_and_resolve(unit_in_hand(later))
        if not later_entry.get("committed") or not later_entry["next_effect_state"]["objects"]["c1"]["exhausted"]:
            errors.append("Confront's turn-7 effect still changed entry state in turn-8")
        theirs_state = unit_in_hand(granted["next_state"]); theirs_state["objects"]["c1"]["owner"] = "p2"; theirs_state["objects"]["c1"]["controller"] = "p2"
        theirs_state["players"]["p1"]["zones"]["hand"].remove("c1"); theirs_state["players"]["p2"]["zones"]["hand"].append("c1")
        theirs_state["players"]["p2"]["resources"] = {"energy": 2, "power": {}}
        decl2 = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "play_id": "play-2", "actor": "p2", "card": "c1",
                 "chain_item": {"id": "unit-2", "object_kind": "unit", "timing": "default"}, "cost": {"base": {"energy": 2, "power": {}}},
                 "payment_context": {"add_window_closed": True, "confirmed_by": "human"}, "entry_location": {"kind": "base"}}
        t2 = fixture(priority="p2", turn_player_override=None) if False else fixture()
        t2["turn_player"] = "p2"; t2["priority"] = "p2"; t2["turn_order"] = ["p2", "p1"]
        p2_play = play_card(t2, theirs_state, decl2)
        if p2_play.get("committed"):
            rt = fixture(priority="p1", items=[item("unit-2", "p2", "unit", "default", "finalized")], passes=["p1", "p2"]); rt["turn_player"] = "p2"; rt["turn_order"] = ["p2", "p1"]
            theirs = resolve_with_program(rt, "unit-2", p2_play["next_effect_state"], None)
            if not theirs.get("committed") or not theirs["next_effect_state"]["objects"]["c1"]["exhausted"]:
                errors.append("Confront's turn effect leaked to the opponent's unit")
        else:
            errors.append(f"opponent's play in the Confront scenario failed to commit: {p2_play.get('reason')}")

    # Opposing entry replacements are a controller choice, not source-order
    # precedence hidden in the engine.
    conflict = unit_in_hand(entry_replacements=[{"replacement_id": "self-ready", "mode": "entry_state", "value": "ready"}])
    conflict["turn_id"] = "turn-7"
    conflict["turn_effects"] = [{"effect_id": "forced-exhausted", "kind": "entry_state_for_played_units", "controller": "p1", "value": "exhausted", "turn_id": "turn-7", "source": "test"}]
    conflict_decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "play_id": "play-conflict", "actor": "p1", "card": "c1",
                     "chain_item": {"id": "unit-conflict", "object_kind": "unit", "timing": "default"}, "cost": {"base": {"energy": 2, "power": {}}},
                     "payment_context": {"add_window_closed": True, "confirmed_by": "human"}, "entry_location": {"kind": "base"}}
    conflict_play = play_card(fixture(), conflict, conflict_decl)
    conflict_timing = fixture(priority="p2", items=[item("unit-conflict", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    conflict_ask = resolve_with_program(conflict_timing, "unit-conflict", conflict_play["next_effect_state"], None)
    if conflict_ask.get("replacement_decision_required") is not True or set(conflict_ask.get("replacement_ids", [])) != {"self-ready", "forced-exhausted"}:
        errors.append(f"conflicting entry replacements did not require an order decision: {conflict_ask.get('reason')}")
    conflict_decision = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(conflict_play["next_effect_state"]), "chain_item_id": "unit-conflict",
                         "decisions": [{"decision_id": "entry-order", "stage": "resolution", "kind": "replacement_order", "controller": "p1",
                                        "value": {"enter_board:unit-conflict": ["forced-exhausted", "self-ready"]}}]}
    conflict_done = resolve_with_program(conflict_timing, "unit-conflict", conflict_play["next_effect_state"], None, engine_decisions=conflict_decision)
    if not conflict_done.get("committed") or conflict_done["next_effect_state"]["objects"]["c1"]["exhausted"]:
        errors.append(f"the supplied entry-replacement order was not honored: {conflict_done.get('reason')}")

    # --- effective_might ------------------------------------------------------------------
    med = base_state()
    med["objects"]["u1"]["conditional_might"] = [{"modifier_id": "meditative", "amount": 4, "condition": {"kind": "runes_at_least", "count": 8}}]
    for n in range(2, 10):
        med["objects"][f"r{n}"] = {"owner": "p1", "controller": "p1", "kind": "rune", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": n % 2 == 0}
        med["players"]["p1"]["zones"]["base"].append(f"r{n}")  # r2..r9 = 8 runes on the board; r1 stays in the rune deck
    if validate_state(med):
        errors.append(f"conditional_might rejected: {validate_state(med)}")
    if effective_might(med, "u1") != 7 or current_might(med["objects"]["u1"]) != 3:
        errors.append(f"8 board runes did not grant +4 (or current_might changed): {effective_might(med, 'u1')} / {current_might(med['objects']['u1'])}")
    stamped = copy.deepcopy(med); stamped["turn_id"] = "turn-7"
    stamped["objects"]["u1"]["might_modifiers"] = [{"amount": 5, "duration": "this_turn", "source": "older", "turn_id": "turn-6"}]
    if effective_might(stamped, "u1") != 7 or current_might(stamped["objects"]["u1"]) != 8:
        errors.append("a this_turn Might modifier from another turn was active (or current_might's context-free contract changed)")
    seven = copy.deepcopy(med); seven["players"]["p1"]["zones"]["base"].remove("r9"); seven["players"]["p1"]["zones"]["rune_deck"].append("r9")
    if effective_might(seven, "u1") != 3:
        errors.append("a rune in the Rune Deck counted toward 'you have 8+ runes'")
    team = copy.deepcopy(seven); team["players"]["p1"]["team_id"] = "A"; team["players"]["p2"]["team_id"] = "A"
    team["objects"]["r9"]["owner"] = "p2"; team["objects"]["r9"]["controller"] = "p2"; team["players"]["p1"]["zones"]["rune_deck"].remove("r9"); team["players"]["p2"]["zones"]["base"].append("r9")
    if effective_might(team, "u1") != 3:
        errors.append("a teammate's rune counted as 'yours'")
    ok, reason = evaluate_target(med, {"object_id": "u1", "chosen_zone_class": "board", "max_might": 3}, "p2")
    if ok or reason != "target_might_requirement_failed":
        errors.append("target max_might did not read effective_might")
    lethal = copy.deepcopy(med); lethal["objects"]["u1"]["damage"] = 5
    cleanup = perform_lethal_cleanup(lethal)
    if not cleanup.get("committed") or "u1" in cleanup["next_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append("lethal Cleanup ignored the conditional passive (5 damage on effective Might 7)")
    bad = copy.deepcopy(med); bad["objects"]["u1"]["conditional_might"][0]["condition"] = {"kind": "moon_phase"}
    if not validate_state(bad):
        errors.append("an unknown continuous condition kind was accepted")

    # --- Ending Step --------------------------------------------------------------------------
    board = base_state(); board["turn_id"] = "turn-7"
    board["objects"]["u1"]["end_of_turn_triggers"] = [{"trigger_id": "u1-eot", "controller": "p1", "source_object": "u1", "controller_order": 0, "effect_program_id": "u1-eot-effects", "optional_at_finalize": False}]
    board["objects"]["u2"]["end_of_turn_triggers"] = [{"trigger_id": "u2-eot", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "u2-eot-effects", "optional_at_finalize": False}]
    if validate_state(board):
        errors.append(f"end_of_turn_triggers rejected: {validate_state(board)}")
    main_open = fixture()
    snap_t, snap_e = copy.deepcopy(main_open), copy.deepcopy(board)
    began = begin_ending_step(main_open, board)
    items = began.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not began.get("committed") or [i["id"] for i in items] != ["u1-eot"] or began["next_timing_state"].get("phase") != "ending" or began["next_timing_state"].get("ending_step", {}).get("status") != "triggers_scheduled" or items[0].get("batch_id") != "ending:turn-7":
        errors.append(f"begin_ending_step did not schedule only the turn player's end-of-turn trigger: {began.get('reason')} {[i.get('id') for i in items]} {began.get('next_timing_state', {}).get('phase')}")
    if main_open != snap_t or board != snap_e or begin_ending_step(main_open, board) != began:
        errors.append("begin_ending_step mutated inputs or is not deterministic")
    conditional = copy.deepcopy(board); conditional["objects"]["u1"]["end_of_turn_triggers"][0]["condition"] = {"kind": "at_battlefield"}
    unmet = begin_ending_step(main_open, conditional)
    if not unmet.get("committed") or unmet["next_timing_state"]["chain"]["items"]:
        errors.append("an unmet at_battlefield trigger condition still scheduled the trigger (383.2.a.1)")
    conditional["players"]["p1"]["zones"]["base"].remove("u1"); conditional["battlefields"]["bf1"]["objects"].append("u1")
    met = begin_ending_step(main_open, conditional)
    if not met.get("committed") or [i["id"] for i in met["next_timing_state"]["chain"]["items"]] != ["u1-eot"]:
        errors.append("a met at_battlefield trigger condition did not schedule the trigger")
    busy = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default")])
    if begin_ending_step(busy, board).get("committed") or begin_ending_step(busy, board).get("reason_code") != "turn_not_quiet":
        errors.append("begin_ending_step ran with a chain open")
    collide = copy.deepcopy(board); collide["objects"]["u2"]["controller"] = "p1"; collide["objects"]["u2"]["end_of_turn_triggers"][0]["controller"] = "p1"
    ask = begin_ending_step(main_open, collide)
    if ask.get("committed") or ask.get("reason_code") != "trigger_order_required":
        errors.append(f"two same-controller end-of-turn triggers did not ask for a trigger_order decision: {ask.get('reason_code')}")

    # --- Expiration Step ----------------------------------------------------------------------
    early = run_expiration_step(began["next_timing_state"], board) if began.get("committed") else {}
    if early.get("committed") or early.get("reason_code") != "ending_triggers_unfinished":
        errors.append(f"expiration ran while end-of-turn chain items were pending: {early.get('reason_code')}")
    if run_expiration_step(main_open, board).get("reason_code") != "expiration_requires_ending_step":
        errors.append("expiration ran in the Main Phase")
    quiet = copy.deepcopy(began["next_timing_state"]) if began.get("committed") else fixture()
    quiet["chain"] = {"initiated_by": None, "items": [], "consecutive_passes": []}
    tasked = copy.deepcopy(quiet); tasked["outstanding_tasks"] = ["cleanup"]
    if run_expiration_step(tasked, board).get("reason_code") != "ending_triggers_unfinished":
        errors.append("expiration ran with an outstanding task")
    rich = copy.deepcopy(board)
    rich["objects"]["u1"]["might_modifiers"] = [{"amount": 3, "duration": "this_turn", "source": "en-garde", "turn_id": "turn-7"}, {"amount": 1, "duration": "this_turn", "source": "older", "turn_id": "turn-6"}, {"amount": 2, "duration": "persistent", "source": "gear"}]
    rich["objects"]["u2"]["damage"] = 2
    rich["turn_effects"] = [{"effect_id": "confront-7", "kind": "entry_state_for_played_units", "controller": "p1", "value": "ready", "turn_id": "turn-7", "source": "confront"},
                            {"effect_id": "confront-6", "kind": "entry_state_for_played_units", "controller": "p1", "value": "ready", "turn_id": "turn-6", "source": "confront"}]
    rich["players"]["p1"]["resources"] = {"energy": 3, "power": {"fury": 2}}
    if validate_state(rich):
        errors.append(f"rich expiration state invalid: {validate_state(rich)}")
    expired = run_expiration_step(quiet, rich)
    if not expired.get("committed"):
        errors.append(f"expiration did not commit: {expired.get('reason')} {expired.get('reason_code')}")
    else:
        nxt = expired["next_effect_state"]
        if nxt["objects"]["u1"]["damage"] != 0 or nxt["objects"]["u2"]["damage"] != 0:
            errors.append("expiration did not heal all units (317.2.b)")
        if [m["source"] for m in nxt["objects"]["u1"]["might_modifiers"]] != ["older", "gear"]:
            errors.append(f"expiration removed the wrong modifiers: {nxt['objects']['u1']['might_modifiers']}")
        if [e["effect_id"] for e in nxt.get("turn_effects", [])] != ["confront-6"]:
            errors.append(f"expiration cleared another turn's effect or kept this turn's: {nxt.get('turn_effects')}")
        if any(p["resources"] != {"energy": 0, "power": {}} for p in nxt["players"].values()):
            errors.append("expiration did not empty every pool (317.2.d)")
        if expired["next_timing_state"]["ending_step"]["status"] != "expired" or expired["trace"].get("simultaneous") is not True:
            errors.append("expiration did not mark the step or record simultaneity")
        if run_expiration_step(expired["next_timing_state"], nxt).get("committed"):
            errors.append("expiration ran twice for one turn")
    odd = copy.deepcopy(rich); odd["turn_effects"][0]["kind"] = "mystery"
    if run_expiration_step(quiet, odd).get("unsupported") is not True:
        errors.append("an unknown turn-effect kind was expired instead of unsupported")

    # --- engine-check and CLI ------------------------------------------------------------------
    check = build_engine_check("turn_step", began, input_hashes={"timing_state": state_hash(main_open), "effect_state": hash_value(board)})
    if check["outcome"] != "supported" or check["check_kind"] != "turn_step":
        errors.append(f"engine-check did not wrap begin_ending_step: {check['outcome']}")
    refused = build_engine_check("turn_step", early, input_hashes={"timing_state": state_hash(quiet), "effect_state": hash_value(board)})
    if refused["outcome"] != "illegal":
        errors.append(f"a refused expiration did not wrap as illegal: {refused['outcome']}")
    with tempfile.TemporaryDirectory(prefix="turn-steps-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(quiet), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(rich), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "turn-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "run_expiration", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI turn-step failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: turn step checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: entry replacements turn the default exhausted entry into ready for the object itself or for the controller's units this turn only; effective_might adds conditional passives while their condition holds (board runes, not deck or teammate) without touching current_might and is what targets and lethal Cleanup read; the Ending Step schedules only the turn player's end-of-turn triggers with their conditions checked, and the Expiration Step heals, expires this turn's effects together, empties the pools, and refuses to run early, twice, or over an unknown effect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
