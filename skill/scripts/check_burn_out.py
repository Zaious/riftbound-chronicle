#!/usr/bin/env python3
"""
Gate for C-37 (ADR-0010 §2): Burn Out on Draw, randomization receipts and
the terminal bridge.

Must hold:
  - a Draw within the Main Deck is unchanged; a Draw beyond it Burns Out:
    with cards in the Trash the recycle order must arrive as a randomization
    receipt for that operation (missing → randomization_receipt_required,
    nothing changes; a permutation that is not the Trash → invalid_input;
    another player's receipt → invalid_input), every recycled card is a new
    object, the sole opponent gains one point that is not a Score, and the
    remaining cards are drawn from the recycled deck;
  - with two or more opponents the beneficiary is a player_selection of the
    Burning Out player (missing → player_selection_required; a non-opponent
    → invalid_input; another controller → decision_controller_mismatch);
  - with an empty Trash the sequence repeats: the first Burn Out never wins
    at once (its point waits for Cleanup step 1), from the second one a
    beneficiary at the Victory Score with a strict lead wins immediately
    and the rest of the Draw is skipped; a repeated Burn Out without a Mode
    of Play is unsupported; the loop bound is derived from the scores;
  - every Draw entry bridges the terminal: a resolving spell writes
    timing.terminal in its own commit and skips Cleanup and triggers; the
    G2 draw-instead commits control, ledger, point and terminal together, or
    commits nothing when the receipt is missing; a program's later effects
    are skipped_after_terminal;
  - a Burn Out with teammates is unsupported; a stale envelope is invalid;
    determinism, purity, engine-check wrapping (external_input /
    player_choice), CLI off-cwd.
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

from battlefield_control import resolve_battlefield_control  # noqa: E402
from check_control_resolution import decided_combat  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from randomization_receipt import validate_randomization_receipt  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import validate_state as validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def receipt(operation_id, player, permutation, receipt_id="rnd-1"):
    return {"schema_version": "randomization-receipt.v1", "receipt_id": receipt_id, "operation": "recycle_trash", "operation_id": operation_id,
            "player": player, "permutation": list(permutation), "provenance": {"provider": "chronicle-harness", "method": "fisher-yates", "seed": "7"}}


def envelope(state, *, receipts=(), decisions=()):
    value = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": list(decisions)}
    if receipts:
        value["randomization_receipts"] = list(receipts)
    return value


def draw(player, count, effect_id="dr"):
    return program(f"draw-{player}", {"op": "draw", "effect_id": effect_id, "player": player, "count": count})


def main() -> int:
    errors: list[str] = []

    # --- plain draw and the first Burn Out with a Trash -----------------------------------------------------
    state = base_state()  # p1: deck c1 c2, trash c3; p2: deck c4, trash empty
    state["mode"] = {"victory_score": 8}
    plain = apply_program(state, draw("p1", 2))
    if not plain.get("committed") or plain["next_state"]["players"]["p1"]["zones"]["hand"] != ["c1", "c2"] or plain["trace"][0].get("burn_outs") != [] or plain.get("terminal_event") is not None:
        errors.append(f"a draw within the deck changed: {plain.get('reason')}")
    op = "burn_out:p1:turn-0:1"
    snap = copy.deepcopy(state)
    missing = apply_program(state, draw("p1", 3))
    if missing.get("committed") or missing.get("reason_code") != "randomization_receipt_required" or missing.get("decision_ids") != [op] or state != snap:
        errors.append(f"a Burn Out without a receipt was not refused as external input: {missing.get('reason_code')} {missing.get('decision_ids')}")
    check = build_engine_check("effect", missing, input_hashes={"effect_state": hash_value(state)})
    if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "external_input" or check["decision_required"]["decision_ids"] != [op]:
        errors.append(f"the missing receipt did not wrap as external_input: {check.get('decision_required')}")
    env = envelope(state, receipts=[receipt(op, "p1", ["c3"])])
    burned = apply_program(state, draw("p1", 3), decisions=env)
    if not burned.get("committed"):
        errors.append(f"a Burn Out with its receipt did not commit: {burned.get('reason') or burned.get('errors')}")
    else:
        ns = burned["next_state"]; ev = burned["trace"][0]
        if ns["players"]["p1"]["zones"]["hand"] != ["c1", "c2", "c3"] or ns["players"]["p1"]["zones"]["main_deck"] != [] or ns["players"]["p1"]["zones"]["trash"] != []:
            errors.append(f"the Trash was not recycled and drawn: {ns['players']['p1']['zones']}")
        if ns["players"]["p2"].get("points") != 1 or ns["players"]["p2"].get("scored_this_turn") or ns["players"]["p1"].get("points", 0) != 0:
            errors.append("the sole opponent did not gain exactly one non-Score point (431.2.c, 194.1.d)")
        if object_identity(ns, "c3") != "c3@2" or ev["burn_outs"][0].get("recycled") != ["c3"] or ev["burn_outs"][0].get("provenance", {}).get("method") != "fisher-yates" or ev["burn_outs"][0].get("immediate_victory") is not False:
            errors.append(f"the Burn Out record or the recycled identity is wrong: {ev.get('burn_outs')} {object_identity(ns, 'c3')}")
        if burned.get("terminal_event") is not None or validate_state(ns):
            errors.append("a first Burn Out ended the game or produced an invalid state")
        if apply_program(state, draw("p1", 3), decisions=env) != burned or state != snap:
            errors.append("the Burn Out draw is not deterministic or mutated its input")
    wrong = apply_program(state, draw("p1", 3), decisions=envelope(state, receipts=[receipt(op, "p1", ["c3", "c9"])]))
    if wrong.get("valid") is not False:
        errors.append("a permutation that is not the Trash was accepted")
    other = apply_program(state, draw("p1", 3), decisions=envelope(state, receipts=[receipt(op, "p2", ["c3"])]))
    if other.get("valid") is not False:
        errors.append("another player's receipt was accepted")
    stale = envelope(state, receipts=[receipt(op, "p1", ["c3"])]); stale["input_hash"] = "sha256:" + "0" * 64
    if apply_program(state, draw("p1", 3), decisions=stale).get("valid") is not False:
        errors.append("a stale envelope was accepted")
    if validate_randomization_receipt({**receipt(op, "p1", ["c3"]), "provenance": {"provider": "x"}}) == []:
        errors.append("a receipt without a method validated")

    # --- several opponents: the beneficiary is a choice -------------------------------------------------------
    three = copy.deepcopy(state)
    three["players"]["p3"] = copy.deepcopy(three["players"]["p2"]); three["players"]["p3"]["zones"] = {z: [] for z in three["players"]["p3"]["zones"]}
    ask = apply_program(three, draw("p1", 3), decisions=envelope(three, receipts=[receipt(op, "p1", ["c3"])]))
    if ask.get("reason_code") != "player_selection_required" or ask.get("decision_ids") != ["burn_out:p1:turn-0:beneficiary:1"] or ask.get("decision_controller") != "p1":
        errors.append(f"with two opponents the beneficiary was not asked of the Burning Out player: {ask.get('reason_code')} {ask.get('decision_ids')}")
    else:
        check = build_engine_check("effect", ask, input_hashes={"effect_state": hash_value(three)})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "player_choice":
            errors.append("the beneficiary choice did not wrap as player_choice")
    pick = {"decision_id": "burn_out:p1:turn-0:beneficiary:1", "stage": "resolution", "kind": "player_selection", "controller": "p1", "value": "p3"}
    chosen = apply_program(three, draw("p1", 3), decisions=envelope(three, receipts=[receipt(op, "p1", ["c3"])], decisions=[pick]))
    if not chosen.get("committed") or chosen["next_state"]["players"]["p3"].get("points") != 1 or chosen["next_state"]["players"]["p2"].get("points", 0) != 0:
        errors.append(f"the chosen beneficiary did not gain the point: {chosen.get('reason') or chosen.get('errors')}")
    if apply_program(three, draw("p1", 3), decisions=envelope(three, receipts=[receipt(op, "p1", ["c3"])], decisions=[{**pick, "value": "p1"}])).get("valid") is not False:
        errors.append("the Burning Out player was accepted as beneficiary")
    if apply_program(three, draw("p1", 3), decisions=envelope(three, receipts=[receipt(op, "p1", ["c3"])], decisions=[{**pick, "controller": "p2"}])).get("reason_code") != "decision_controller_mismatch":
        errors.append("an opponent chose the beneficiary")

    # --- two opponents fed in turn: the bound admits the whole legal sequence (Codex review-fix) --------------------------
    duel3 = copy.deepcopy(state)
    duel3["players"]["p3"] = copy.deepcopy(duel3["players"]["p2"]); duel3["players"]["p3"]["zones"] = {z: [] for z in duel3["players"]["p3"]["zones"]}
    for card in ("c1", "c2", "c3"):
        del duel3["objects"][card]
    duel3["players"]["p1"]["zones"]["main_deck"] = []; duel3["players"]["p1"]["zones"]["trash"] = []
    duel3["mode"] = {"victory_score": 8}

    def alternating(n):
        return [{"decision_id": f"burn_out:p1:turn-0:beneficiary:{k}", "stage": "resolution", "kind": "player_selection", "controller": "p1", "value": "p2" if k % 2 else "p3"} for k in range(1, n + 1)]
    short = apply_program(duel3, draw("p1", 1), decisions=envelope(duel3, decisions=alternating(8)))
    if short.get("committed") or short.get("reason_code") != "player_selection_required" or short.get("decision_ids") != ["burn_out:p1:turn-0:beneficiary:9"]:
        errors.append(f"eight alternating beneficiaries were refused instead of asking for the ninth: {short.get('reason_code')} {short.get('errors')}")
    long = apply_program(duel3, draw("p1", 1), decisions=envelope(duel3, decisions=alternating(16)))
    if not long.get("committed"):
        errors.append(f"the alternating sequence was refused before its immediate victory: {long.get('reason_code')} {long.get('reason') or long.get('errors')}")
    else:
        ev = long["trace"][0]; pts = {p: long["next_state"]["players"][p].get("points", 0) for p in ("p1", "p2", "p3")}
        if len(ev["burn_outs"]) != 15 or pts != {"p1": 0, "p2": 8, "p3": 7} or long.get("terminal_event", {}).get("winner") != "p2" or ev.get("loop_bound") != 17:
            errors.append(f"the fifteenth Burn Out did not end the game for p2 at 8 over p3 at 7 within a bound of 17: {len(ev['burn_outs'])} {pts} {long.get('terminal_event')} {ev.get('loop_bound')}")

    # --- the empty-Trash sequence and the immediate victory --------------------------------------------------------
    empty = copy.deepcopy(state)
    for card in ("c1", "c2", "c3"):
        del empty["objects"][card]
    empty["players"]["p1"]["zones"]["main_deck"] = []; empty["players"]["p1"]["zones"]["trash"] = []
    empty["mode"] = {"victory_score": 3}; empty["players"]["p2"]["points"] = 1
    looped = apply_program(empty, program("loop", {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}, {"op": "heal_all_damage", "effect_id": "later"}))
    if not looped.get("committed"):
        errors.append(f"the empty-Trash sequence did not commit: {looped.get('reason') or looped.get('errors')}")
    else:
        ev = looped["trace"][0]; term = looped.get("terminal_event")
        if [b["immediate_victory"] for b in ev["burn_outs"]] != [False, True] or looped["next_state"]["players"]["p2"]["points"] != 3 or ev.get("skipped_after_terminal") != 1 or ev.get("completion") != "none":
            errors.append(f"the sequence did not win on the second Burn Out with the draw skipped: {ev.get('burn_outs')} {ev.get('completion')}")
        if not term or term.get("reason") != "burn_out_victory" or term.get("winner") != "p2" or term.get("immediate") is not True:
            errors.append(f"no immediate burn_out_victory event: {term}")
        if looped["trace"][1].get("outcome") != "skipped_after_terminal" or ev.get("loop_bound") != 3:  # (target 3 - p2's 1) + 1
            errors.append(f"the program's later effect ran after the terminal, or the bound is wrong: {looped['trace'][1].get('outcome')} {ev.get('loop_bound')}")
    no_mode = copy.deepcopy(empty); del no_mode["mode"]
    unsupported = apply_program(no_mode, draw("p1", 1))
    if unsupported.get("committed") or unsupported.get("unsupported") is not True or "Burn Out" not in unsupported.get("reason", ""):
        errors.append("a repeated Burn Out without a Mode of Play was not refused as unsupported")
    ahead = copy.deepcopy(empty); ahead["players"]["p2"]["points"] = 2; ahead["players"]["p1"]["points"] = 0
    first_only = copy.deepcopy(ahead); first_only["players"]["p1"]["zones"]["trash"] = ["c9"]; first_only["objects"]["c9"] = copy.deepcopy(state["objects"]["c3"])
    single = apply_program(first_only, draw("p1", 1), decisions=envelope(first_only, receipts=[receipt(op, "p1", ["c9"])]))
    if not single.get("committed") or single.get("terminal_event") is not None or single["next_state"]["players"]["p2"]["points"] != 3:
        errors.append(f"a first Burn Out that reaches the Victory Score ended the game at once instead of waiting for Cleanup step 1 (431.3.c): {single.get('terminal_event')} {single.get('reason')}")
    team = copy.deepcopy(empty); team["players"]["p1"]["team_id"] = "A"
    if apply_program(team, draw("p1", 1)).get("unsupported") is not True:
        errors.append("a Burn Out with teammates was attempted")

    # --- the resolution bridge writes the terminal ------------------------------------------------------------------
    spell_state = copy.deepcopy(empty)
    spell_state["objects"]["s1"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
    spell_state["chain_items"] = {"spell-1": {"card": "s1", "controller": "p1"}}
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    bridged = resolve_with_program(timing, "spell-1", spell_state, {**draw("p1", 1), "program_id": "draw-p1", "controller": "p1"})
    if not bridged.get("committed"):
        errors.append(f"the bridge did not commit a Draw that ended the game: {bridged.get('reason')} {bridged.get('effect_result', {}).get('errors')}")
    else:
        tt = bridged["next_timing_state"]
        if tt.get("terminal", {}).get("reason") != "burn_out_victory" or tt["terminal"].get("winner") != "p2" or tt["terminal"].get("immediate") is not True or validate_timing(tt):
            errors.append(f"the bridge did not write the terminal into the timing state: {tt.get('terminal')} {validate_timing(tt)}")
        if bridged["trace"].get("skipped_after_terminal", {}).get("lethal_cleanup") is not True or "s1" not in bridged["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
            errors.append("the bridge ran Cleanup after the terminal or left the spell on the chain")
        check = build_engine_check("resolution", bridged, input_hashes={"timing_state": hash_value(timing), "effect_state": hash_value(spell_state)})
        if check["outcome"] != "supported" or "terminal_event_bridge" not in check["coverage"]["supported_scope"]:
            errors.append("engine-check did not wrap the bridged terminal")
    with_trash = copy.deepcopy(spell_state); with_trash["players"]["p1"]["zones"]["trash"] = ["c9"]; with_trash["objects"]["c9"] = copy.deepcopy(state["objects"]["c3"])
    waiting = resolve_with_program(timing, "spell-1", with_trash, {**draw("p1", 1), "program_id": "draw-p1", "controller": "p1"})
    if waiting.get("committed") or waiting.get("effect_result", {}).get("reason_code") != "randomization_receipt_required":
        errors.append(f"the bridge committed a Burn Out without its receipt: {waiting.get('reason')}")

    # --- the G2 draw-instead is a Draw ---------------------------------------------------------------------------------
    def two_battlefields(s):
        s["battlefields"]["bf2"] = {"controller": None, "objects": []}

    def empty_deck(s):
        two_battlefields(s)
        for card in s["players"]["p1"]["zones"]["main_deck"]:
            del s["objects"][card]
        s["players"]["p1"]["zones"]["main_deck"].clear()
    t, e = decided_combat(victory_score=3, points=2, extra=empty_deck)  # p1 at 2 of 3 conquers bf1 with bf2 unscored: draw instead; deck empty, trash c3
    op_score = "burn_out:p1:turn-0:score:bf1:1"
    held_back = resolve_battlefield_control(t, e)
    if held_back.get("committed") or held_back.get("reason_code") != "randomization_receipt_required" or held_back.get("decision_ids") != [op_score]:
        errors.append(f"the draw-instead Burn Out committed without its receipt: {held_back.get('reason_code')} {held_back.get('decision_ids')}")
    else:
        check = build_engine_check("control_step", held_back, input_hashes={"timing_state": hash_value(t), "effect_state": hash_value(e)})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "external_input":
            errors.append("the control transaction's missing receipt did not wrap as external_input")
    env_score = {"schema_version": "engine-decisions.v1", "input_hash": held_back.get("input_hash", ""), "decisions": [], "randomization_receipts": [receipt(op_score, "p1", ["c3"])]}
    done = resolve_battlefield_control(t, e, env_score)
    if not done.get("committed"):
        errors.append(f"the draw-instead with its receipt did not commit: {done.get('reason_code')} {done.get('reason') or done.get('errors')}")
    else:
        ee = done["next_effect_state"]
        if ee["battlefields"]["bf1"]["controller"] != "p1" or ee["players"]["p1"].get("points") != 2 or ee["players"]["p2"].get("points") != 1 or "c3" not in ee["players"]["p1"]["zones"]["hand"] or "terminal" in done["next_timing_state"]:
            errors.append(f"the draw-instead did not conquer, keep the points, Burn Out and draw the recycled card together: {ee['players']['p1']} {ee['players']['p2']}")
    def empty_all(s):
        empty_deck(s)
        s["players"]["p1"]["zones"]["trash"].clear(); del s["objects"]["c3"]
        s["players"]["p2"]["points"] = 1
    t2, e2 = decided_combat(victory_score=3, points=2, extra=empty_all)
    ended = resolve_battlefield_control(t2, e2)
    if not ended.get("committed") or ended["next_timing_state"].get("terminal", {}).get("reason") != "burn_out_victory" or ended["next_timing_state"]["terminal"].get("winner") != "p2":
        errors.append(f"the draw-instead with an empty deck and Trash did not end the game for the opponent in the same commit: {ended.get('reason_code')} {ended.get('next_timing_state', {}).get('terminal')}")
    elif ended["next_effect_state"]["battlefields"]["bf1"]["controller"] != "p1" or ended["trace"].get("skipped_after_terminal") is None or validate_timing(ended["next_timing_state"]):
        errors.append("the control change was lost or triggers were scheduled after the terminal")

    with tempfile.TemporaryDirectory(prefix="burnout-") as temp_name:
        temp = Path(temp_name)
        (temp / "s.json").write_text(json.dumps(state), encoding="utf-8"); (temp / "p.json").write_text(json.dumps(draw("p1", 3)), encoding="utf-8")
        (temp / "d.json").write_text(json.dumps(env), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "effect", str(temp / "s.json"), str(temp / "p.json"), "--decisions", str(temp / "d.json"), "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI effect with a randomization receipt failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: burn out checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: a Draw beyond the Main Deck Burns Out with an external randomization receipt and a beneficiary that is automatic for one opponent and a choice among several, recycled cards are new objects, the point is not a Score, an empty Trash repeats the Burn Out and wins immediately only from the second one, and every Draw entry writes the terminal inside its own commit or commits nothing while an input is missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
