#!/usr/bin/env python3
"""
Gate for C-36 (ADR-0010 §3, §4, §10): the terminal state, the shared
game-over guard and the reward projection.

Must hold:
  - check_terminal (Cleanup step 1) ends the game for the one player at or
    above the Victory Score with more points than every other player, with
    a derived victory_score record naming the winner, the final points and
    the turn; a tie at the threshold continues (continue_tied); below the
    threshold nothing changes; a higher score beats a lower one at the
    threshold; a missing Mode of Play is unsupported;
  - after the terminal the snapshot is frozen with its chain items:
    next_procedure reports game_over, validate_timing is illegal, every
    kernel mutator, every two-state procedure, resolve_with_program,
    begin_ending_step and play_card refuse game_over, check_terminal
    refuses a second time, and the frozen state still validates;
  - declare_terminal records a concession (the other player wins) or an
    external ending (winner optional) with derived false, refuses a derived
    reason, an unknown player, a wrong winner and a three-player concession;
  - the reward projection reads only the terminal: winner +1, the other −1,
    ongoing 0, no winner 0, unknown player invalid, three players
    unsupported, and the two rewards of one ending sum to zero;
  - determinism, purity, engine-check wrapping, CLI off-cwd.
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

from battlefield_control import run_board_cleanup, run_scoring_step, stage_showdown  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import stage_combat, standard_move  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import begin_ending_step, resolve_with_program  # noqa: E402
from reward_adapter import terminal_reward  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, add_pending_item, complete_resolution, derive_permissions, finalize_oldest_pending, next_procedure, pass_focus, pass_priority, schedule_triggered_items, state_hash, validate_state as validate_timing, validate_timing as legality  # noqa: E402
from terminal import check_terminal, declare_terminal  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def scored(p1=0, p2=0, victory_score=8):
    state = base_state()
    state["mode"] = {"victory_score": victory_score}
    state["players"]["p1"]["points"] = p1
    state["players"]["p2"]["points"] = p2
    return state


def main() -> int:
    errors: list[str] = []
    quiet = fixture()

    # --- Cleanup step 1 ------------------------------------------------------------------------------------
    e = scored(8, 3)
    snap_t, snap_e = copy.deepcopy(quiet), copy.deepcopy(e)
    ended = check_terminal(quiet, e)
    if not ended.get("committed"):
        errors.append(f"a strict leader at the Victory Score did not end the game: {ended.get('reason_code')} {ended.get('reason') or ended.get('errors')}")
        print("FAILED: terminal state checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    t_end = ended["next_timing_state"]
    record = t_end.get("terminal", {})
    if record.get("status") != "ended" or record.get("reason") != "victory_score" or record.get("winner") != "p1" or record.get("derived") is not True or record.get("final_points") != {"p1": 8, "p2": 3} or record.get("turn_id") != "turn-0":
        errors.append(f"the terminal record is wrong: {record}")
    if ended["trace"].get("outcome") != "ended" or ended["next_effect_state"] != e or validate_timing(t_end):
        errors.append(f"the ending touched the effect state or produced an invalid timing state: {validate_timing(t_end)}")
    if quiet != snap_t or e != snap_e or check_terminal(quiet, e) != ended:
        errors.append("check_terminal mutated its inputs or is not deterministic")
    tied = check_terminal(quiet, scored(8, 8))
    if not tied.get("committed") or "terminal" in tied["next_timing_state"] or tied["trace"].get("outcome") != "continue_tied":
        errors.append(f"a tie at the threshold ended the game or was not reported (194.2.b): {tied.get('trace', {}).get('outcome')}")
    below = check_terminal(quiet, scored(7, 7))
    if not below.get("committed") or "terminal" in below["next_timing_state"] or below["trace"].get("outcome") != "below_threshold":
        errors.append("below the threshold something happened")
    higher = check_terminal(quiet, scored(8, 9))
    if not higher.get("committed") or higher["next_timing_state"].get("terminal", {}).get("winner") != "p2":
        errors.append("with two players at the threshold the higher score did not win (194.2.a)")
    no_mode = scored(8, 3); del no_mode["mode"]
    if check_terminal(quiet, no_mode).get("reason_code") != "mode_unknown" or check_terminal(quiet, no_mode).get("unsupported") is not True:
        errors.append("the victory condition was judged without a Mode of Play")
    check = build_engine_check("turn_step", ended, input_hashes={"timing_state": state_hash(quiet), "effect_state": hash_value(e)})
    if check["outcome"] != "supported" or "terminal_state" not in check["coverage"]["supported_scope"] or "complete_game" not in check["coverage"]["unsupported_scope"]:
        errors.append(f"engine-check did not wrap the terminal step with its scope: {check['outcome']}")

    # --- the frozen snapshot -------------------------------------------------------------------------------
    busy = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default")])
    frozen_result = check_terminal(busy, e)
    frozen = frozen_result.get("next_timing_state", {})
    if not frozen_result.get("committed") or [i["id"] for i in frozen["chain"]["items"]] != ["spell-1"] or frozen_result["trace"].get("frozen_chain_items") != ["spell-1"] or validate_timing(frozen):
        errors.append(f"the chain was not frozen with the ending: {frozen_result.get('reason_code')} {validate_timing(frozen)}")
    if next_procedure(frozen).get("procedure") != "game_over" or next_procedure(frozen).get("subject") != "p1" or next_procedure(frozen).get("discretionary_actions_allowed") is not False:
        errors.append(f"next_procedure did not report game_over: {next_procedure(frozen)}")
    if legality(frozen, {"actor": "p2", "kind": "pass_priority"}).get("legal") is not False or legality(frozen, {"actor": "p2", "kind": "pass_priority"}).get("reason_code") != "game_over":
        errors.append("validate_timing allowed an action after the game ended")
    perms = derive_permissions(frozen)["permissions"]
    if any(v["play_timings"] or v["activate_timings"] or v["may_pass_focus"] or v["may_pass_priority"] for v in perms.values()):
        errors.append("permissions remained after the game ended")
    kernel = {
        "pass_priority": pass_priority(frozen, "p2"),
        "finalize": finalize_oldest_pending({**frozen, "chain": {**frozen["chain"], "items": [item("spell-1", "p1", "spell", "default", "pending")]}}),
        "complete_resolution": complete_resolution({**frozen, "chain": {**frozen["chain"], "items": [item("spell-1", "p1", "spell", "default", "finalized")], "consecutive_passes": ["p1", "p2"]}}, "spell-1", effect_execution_confirmed=True),
        "add_pending_item": add_pending_item(frozen, {"actor": "p2", "kind": "play_card", "item": item("reaction-2", "p2", "spell", "reaction")}),
        "schedule_triggered_items": schedule_triggered_items(frozen, [{"trigger_id": "t1", "controller": "p1", "source_object": "u1", "effect_program_id": "t1-effects", "optional_at_finalize": False}]),
    }
    showdown_frozen = {**t_end, "showdown": {"active": True, "kind": "non_combat", "focus": "p1", "battlefield": "bf1", "focus_passes": []}, "priority": "p1"}
    kernel["pass_focus"] = pass_focus(showdown_frozen, "p1")
    for name, result in kernel.items():
        if result.get("applied") is not False or result.get("reason_code") != "game_over":
            errors.append(f"kernel mutator {name} ran after the game ended: {result.get('reason_code')} {result.get('errors')}")
    board = scored(8, 3)
    two_state = {
        "stage_combat": stage_combat(t_end, board), "stage_showdown": stage_showdown(t_end, board), "run_board_cleanup": run_board_cleanup(t_end, board),
        "run_scoring_step": run_scoring_step({**t_end, "phase": "beginning", "priority": None}, board),
        "standard_move": standard_move(t_end, board, {"actor": "p1", "units": ["u1"], "destination": {"kind": "battlefield", "battlefield": "bf1"}, "unit_identities": {"u1": "u1@0"}, "cost_confirmation": True}),
        "check_terminal": check_terminal(t_end, board),
    }
    for name, result in two_state.items():
        if result.get("committed") or result.get("reason_code") != "game_over" or result.get("valid") is not True:
            errors.append(f"two-state procedure {name} ran after the game ended: {result.get('reason_code')} {result.get('errors')}")
    bridge = resolve_with_program({**frozen, "chain": {**frozen["chain"], "items": [item("spell-1", "p1", "spell", "default", "finalized")], "consecutive_passes": ["p1", "p2"]}}, "spell-1", board, {"program_id": "p", "effects": [{"op": "draw", "player": "p1", "count": 1}]})
    if bridge.get("committed") or bridge.get("reason_code") != "game_over":
        errors.append(f"resolve_with_program ran after the game ended: {bridge.get('reason')}")
    if begin_ending_step(t_end, board).get("reason_code") != "game_over":
        errors.append("begin_ending_step ran after the game ended")
    in_hand = copy.deepcopy(board); in_hand["players"]["p1"]["zones"]["main_deck"].remove("c1"); in_hand["players"]["p1"]["zones"]["hand"].append("c1")
    in_hand["objects"]["c1"].update({"kind": "unit", "base_might": 2}); in_hand["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"}, "cost": {"base": {"energy": 2, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}, "entry_location": {"kind": "base"}}
    played = play_card(t_end, in_hand, decl)
    if played.get("committed") or played.get("reason_code") != "game_over":
        errors.append(f"play_card ran after the game ended: {played.get('reason_code')} {played.get('reason')}")

    # --- declared endings ------------------------------------------------------------------------------------
    e0 = scored(2, 5)
    conceded = declare_terminal(quiet, e0, declaration={"reason": "concession", "player": "p1"})
    rec = conceded.get("next_timing_state", {}).get("terminal", {})
    if not conceded.get("committed") or rec.get("reason") != "concession" or rec.get("winner") != "p2" or rec.get("derived") is not False or rec.get("declared_by") != "p1" or rec.get("final_points") != {"p1": 2, "p2": 5}:
        errors.append(f"a concession was not recorded with the other player as winner: {conceded.get('reason_code')} {rec}")
    external = declare_terminal(quiet, e0, declaration={"reason": "external", "winner": None, "note": "time"})
    if not external.get("committed") or external["next_timing_state"]["terminal"].get("winner") is not None or validate_timing(external["next_timing_state"]):
        errors.append("an external ending without a winner was not recorded")
    if declare_terminal(quiet, e0, declaration={"reason": "victory_score", "winner": "p1"}).get("valid") is not False:
        errors.append("a derived reason was accepted from a declaration")
    if declare_terminal(quiet, e0, declaration={"reason": "concession", "player": "p9"}).get("valid") is not False or declare_terminal(quiet, e0, declaration={"reason": "concession", "player": "p1", "winner": "p1"}).get("valid") is not False:
        errors.append("an unknown conceding player or a wrong winner was accepted")
    three_t = {**quiet, "players": ["p1", "p2", "p3"], "turn_order": ["p1", "p2", "p3"]}
    three_e = copy.deepcopy(e0); three_e["players"]["p3"] = copy.deepcopy(three_e["players"]["p2"]); three_e["players"]["p3"]["zones"] = {z: [] for z in three_e["players"]["p3"]["zones"]}
    if declare_terminal(three_t, three_e, declaration={"reason": "concession", "player": "p1"}).get("reason_code") != "multi_player_concession":
        errors.append("a three-player concession was resolved")
    bad = copy.deepcopy(t_end); bad["terminal"]["derived"] = False
    if not validate_timing(bad):
        errors.append("a derived reason marked as declared was accepted by the validator")
    if declare_terminal(t_end, e0, declaration={"reason": "external", "winner": None}).get("reason_code") != "game_over":
        errors.append("a second ending was declared over a finished game")

    # --- the reward projection -------------------------------------------------------------------------------
    rewards = {p: terminal_reward(t_end, p) for p in ("p1", "p2")}
    if rewards["p1"].get("reward") != 1 or rewards["p2"].get("reward") != -1 or rewards["p1"].get("reason") != "winner" or rewards["p2"].get("terminal_reason") != "victory_score" or rewards["p1"].get("terminal_hash") != state_hash(t_end):
        errors.append(f"the reward projection is wrong: {rewards}")
    if sum(r["reward"] for r in rewards.values()) != 0:
        errors.append("the two rewards of one ending do not sum to zero")
    if terminal_reward(quiet, "p1").get("reward") != 0 or terminal_reward(quiet, "p1").get("reason") != "ongoing":
        errors.append("an ongoing game did not project 0")
    if terminal_reward(external["next_timing_state"], "p1").get("reason") != "no_winner" or terminal_reward(external["next_timing_state"], "p1").get("reward") != 0:
        errors.append("an ending without a winner did not project 0")
    if terminal_reward(t_end, "p9").get("valid") is not False:
        errors.append("an unknown player got a reward")
    if terminal_reward(three_t, "p1").get("unsupported") is not True:
        errors.append("a three-player game got a reward")
    if terminal_reward(t_end, "p1") != rewards["p1"] or "reads" not in rewards["p1"] or rewards["p1"]["reads"] != ["terminal"]:
        errors.append("the reward projection is not deterministic or reads more than the terminal")

    with tempfile.TemporaryDirectory(prefix="terminal-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(quiet), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(e), encoding="utf-8")
        (temp / "d.json").write_text(json.dumps({"reason": "concession", "player": "p2"}), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "turn-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "check_terminal", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI turn-step check_terminal failed off-cwd: {run.stderr.strip()}")
        run = subprocess.run([sys.executable, str(RUNNER), "turn-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "declare_terminal", "--declaration", str(temp / "d.json"), "--output", str(temp / "o2.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o2.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI turn-step declare_terminal failed off-cwd: {run.stderr.strip()}")
        (temp / "tt.json").write_text(json.dumps(t_end), encoding="utf-8")
        run = subprocess.run([sys.executable, str(SCRIPT_DIR / "reward_adapter.py"), str(temp / "tt.json"), "p2"], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads(run.stdout)["reward"] != -1:
            errors.append(f"reward_adapter CLI failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: terminal state checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: Cleanup step 1 ends the game only for a strict leader at the Victory Score and lets a tie continue, the frozen snapshot refuses every kernel mutator, two-state procedure, resolution and play as game_over while still validating with its chain, declared endings record a concession or an external ruling without a derived reason, and the reward projection reads nothing but the terminal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
