#!/usr/bin/env python3
"""
Gate for C-33 (ADR-0009 §1–2, §5–7, §11): Battlefield control resolution,
Conquer scoring and Score triggers.

Must hold:
  - after a decided Combat the one player whose Units remain establishes
    control if they did not hold it, Contested is cleared, the Combat moves
    to control_resolved and only then closes; a winner who already controls
    the Battlefield gains nothing; no Units left makes it Uncontrolled;
  - Conquer gains one point and records the Battlefield in the turn's
    ledger; the same Battlefield scored again this turn changes control
    without a point or a trigger (470);
  - the Final Point (471.1.b): at Victory Score − 1 a Conquer gains the point
    only when every Battlefield was scored this turn, otherwise the player
    draws instead and the Score trigger still fires; an empty Main Deck
    refuses the whole transaction as unsupported burn_out and nothing
    changes — not the controller, not the ledger, not the chain;
  - Score triggers: the scoring player's Unit at the Battlefield scored
    (unit_here) and any board object they control (controller) fire, the
    loser's Units and a Unit at another Battlefield do not, the Battlefield's
    own trigger belongs to the new controller; close_combat waits for that
    chain;
  - a missing mode or any team_id is unsupported; a both-remain restage and
    an undecided Combat refuse; victory facts name threshold_met,
    strict_leader and tied_at_threshold and enact nothing;
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

from battlefield_control import resolve_battlefield_control, victory_check  # noqa: E402
from check_combat_damage_assignment import add_unit, closed_combat  # noqa: E402
from check_combat_staging import trigger  # noqa: E402
from combat import assign_combat_damage, close_combat, combat_cleanup, deal_combat_damage, determine_combat_result  # noqa: E402
from effect_ir import hash_value, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from rules_core import state_hash, validate_state as validate_timing  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"


def decided_combat(*, victory_score=8, points=0, extra=None, defender_might=3):
    """u1 (p1, 5 Might) kills d1 (p2) at bf1; the result is determined and the chain is empty."""
    t, e = closed_combat([("d1", {"might": defender_might})], attacker_might=5)
    e["mode"] = {"victory_score": victory_score}
    e["players"]["p1"]["points"] = points
    if extra:
        extra(e)
    a = assign_combat_damage(t, e); d = deal_combat_damage(a["next_timing_state"], a["next_effect_state"]); c = combat_cleanup(d["next_timing_state"], d["next_effect_state"])
    r = determine_combat_result(c["next_timing_state"], c["next_effect_state"])
    assert r.get("committed"), r.get("reason") or r.get("errors")
    return r["next_timing_state"], r["next_effect_state"]


def main() -> int:
    errors: list[str] = []

    # --- a plain Conquer -----------------------------------------------------------------------------
    t, e = decided_combat()
    snap_t, snap_e = copy.deepcopy(t), copy.deepcopy(e)
    if close_combat(t, e).get("reason_code") != "control_resolution_pending":
        errors.append("the Combat closed before control was resolved (466.5 before 466.7)")
    resolved = resolve_battlefield_control(t, e)
    if not resolved.get("committed"):
        errors.append(f"control resolution did not commit: {resolved.get('reason_code')} {resolved.get('reason') or resolved.get('errors')}")
        print("FAILED: control resolution checks" + chr(10) + "  - " + "; ".join(errors)); return 1
    tr, er = resolved["next_timing_state"], resolved["next_effect_state"]
    bf = er["battlefields"]["bf1"]
    if bf.get("controller") != "p1" or bf.get("contested") is not False or bf.get("contested_by") is not None:
        errors.append(f"the winner did not establish control with Contested cleared: {bf}")
    if er["players"]["p1"].get("points") != 1 or er["players"]["p1"].get("scored_this_turn") != {"turn-0": ["bf1"]}:
        errors.append(f"the Conquer did not score once: {er['players']['p1'].get('points')} {er['players']['p1'].get('scored_this_turn')}")
    if tr["combat"]["status"] != "control_resolved" or resolved["trace"].get("atomic") is not True or resolved["trace"]["scoring"].get("gain") != "point":
        errors.append(f"the record or trace is wrong: {tr['combat']['status']} {resolved['trace'].get('scoring')}")
    if validate_timing(tr) or validate_state(er):
        errors.append(f"states after control resolution invalid: {validate_timing(tr)} {validate_state(er)}")
    if t != snap_t or e != snap_e or resolve_battlefield_control(t, e) != resolved:
        errors.append("resolve_battlefield_control mutated its inputs or is not deterministic")
    closed = close_combat(tr, er)
    if not closed.get("committed") or "combat" in closed["next_timing_state"] or closed["trace"].get("control_step") != "control_established":
        errors.append(f"the Combat did not close after control resolution: {closed.get('reason_code')} {closed.get('reason')}")
    if resolve_battlefield_control(tr, er).get("reason_code") != "control_resolution_not_pending":
        errors.append("control was resolved twice")
    check = build_engine_check("control_step", resolved, input_hashes={"timing_state": state_hash(t), "effect_state": hash_value(e)})
    if check["outcome"] != "supported" or "conquer_scoring" not in check["coverage"]["supported_scope"] or "terminal_state" not in check["coverage"]["unsupported_scope"]:
        errors.append(f"engine-check did not wrap control resolution with its scope: {check['outcome']}")
    facts = resolved["trace"]["victory_check"]
    if facts.get("threshold_met") != [] or facts.get("strict_leader") is not None or facts.get("tied_at_threshold") is not False:
        errors.append(f"victory facts wrong below the threshold: {facts}")

    # --- the winner already controls: no Conquer ---------------------------------------------------------
    t, e = decided_combat(extra=lambda s: s["battlefields"]["bf1"].__setitem__("controller", "p1"))
    same = resolve_battlefield_control(t, e)
    if not same.get("committed") or same["trace"]["control_step"] != "controller_unchanged" or same["next_effect_state"]["players"]["p1"].get("points", 0) != 0 or same["next_effect_state"]["battlefields"]["bf1"].get("contested") is not False:
        errors.append(f"a winner who already controlled the Battlefield scored or kept Contested: {same.get('reason_code')} {same.get('trace', {}).get('control_step')}")
    # --- already scored this turn: control changes, nothing scores ------------------------------------------
    t, e = decided_combat(extra=lambda s: s["players"]["p1"].__setitem__("scored_this_turn", {"turn-0": ["bf1"]}))
    e["objects"]["u1"]["conquer_triggers"] = [trigger("u1-conquer", "p1", "u1")]
    again = resolve_battlefield_control(t, e)
    if not again.get("committed") or again["next_effect_state"]["battlefields"]["bf1"]["controller"] != "p1" or again["next_effect_state"]["players"]["p1"].get("points", 0) != 0 or again["next_timing_state"]["chain"]["items"] or again["trace"]["scoring"].get("reason") != "already_scored_this_turn":
        errors.append(f"a Battlefield already scored this turn scored or triggered again (470, 471.2.c): {again.get('trace', {}).get('scoring')}")
    # --- no Units left: Uncontrolled ---------------------------------------------------------------------------
    t, e = decided_combat(defender_might=5)
    e["battlefields"]["bf1"]["controller"] = "p2"
    empty = resolve_battlefield_control(t, e)
    if not empty.get("committed") or empty["trace"]["control_step"] != "uncontrolled" or empty["next_effect_state"]["battlefields"]["bf1"]["controller"] is not None:
        errors.append(f"an emptied Battlefield did not become Uncontrolled (466.5.b): {empty.get('reason_code')} {empty.get('trace', {}).get('control_step')}")

    # --- Score triggers --------------------------------------------------------------------------------------
    def arm(s):
        s["objects"]["u1"]["conquer_triggers"] = [trigger("u1-conquer", "p1", "u1")]
        add_unit(s, "g1", "p1", "base:p1", might=0, kind="gear", conquer_triggers=[{**trigger("g1-you-conquer", "p1", "g1", order=1), "scope": "controller"}])
        s["battlefields"]["bf2"] = {"controller": None, "objects": []}
        add_unit(s, "u3", "p1", "bf2", might=2, conquer_triggers=[trigger("u3-conquer", "p1", "u3")])
        s["battlefields"]["bf1"]["conquer_triggers"] = [{"trigger_id": "bf1-conquer", "controller_order": 2, "effect_program_id": "bf1-conquer-effects", "optional_at_finalize": False}]
        s["objects"]["u2"]["conquer_triggers"] = [trigger("u2-conquer", "p2", "u2")]  # the loser's, at its Base
    t, e = decided_combat(extra=arm)
    armed = resolve_battlefield_control(t, e)
    items = [i["id"] for i in armed.get("next_timing_state", {}).get("chain", {}).get("items", [])]
    if not armed.get("committed") or sorted(items) != ["bf1-conquer", "g1-you-conquer", "u1-conquer"]:
        errors.append(f"Score triggers fired for the wrong sources: {items} {armed.get('reason')}")
    else:
        bf_item = next(i for i in armed["next_timing_state"]["chain"]["items"] if i["id"] == "bf1-conquer")
        if bf_item["controller"] != "p1" or bf_item["source_object"] != "bf1":
            errors.append("the Battlefield's own Conquer trigger does not belong to its new controller")
        if close_combat(armed["next_timing_state"], armed["next_effect_state"]).get("reason_code") != "combat_chain_unfinished":
            errors.append("the Combat closed with Score triggers pending (466.6)")
    if validate_state(e):
        errors.append(f"score triggers rejected by the validator: {validate_state(e)}")
    colliding = copy.deepcopy(e); colliding["objects"]["g1"]["conquer_triggers"][0]["controller_order"] = 0
    collision = resolve_battlefield_control(t, colliding)
    if collision.get("committed") or collision.get("reason_code") != "trigger_order_required" or collision.get("decision_ids") != ["trigger_order:score:bf1:turn-0:conquer:p1"]:
        errors.append(f"two Score triggers of one controller with the same order were not left to that controller's choice (383.3.d.1): {collision.get('reason_code')} {collision.get('decision_ids')}")

    # --- the Final Point (471.1.b) ---------------------------------------------------------------------------
    def two_battlefields(s):
        s["battlefields"]["bf2"] = {"controller": None, "objects": []}
        s["objects"]["u1"]["conquer_triggers"] = [trigger("u1-conquer", "p1", "u1")]
    t, e = decided_combat(victory_score=3, points=2, extra=two_battlefields)
    drew = resolve_battlefield_control(t, e)
    if not drew.get("committed"):
        errors.append(f"the draw-instead Conquer did not commit: {drew.get('reason_code')} {drew.get('reason')}")
    else:
        ee = drew["next_effect_state"]
        if ee["players"]["p1"].get("points") != 2 or len(ee["players"]["p1"]["zones"]["hand"]) != 1 or drew["trace"]["scoring"].get("gain") != "draw_instead" or [i["id"] for i in drew["next_timing_state"]["chain"]["items"]] != ["u1-conquer"]:
            errors.append(f"at Victory Score - 1 without every Battlefield scored the player did not draw instead with the trigger still firing: {drew['trace'].get('scoring')} {ee['players']['p1'].get('points')}")
    t, e = decided_combat(victory_score=3, points=2, extra=lambda s: (two_battlefields(s), s["players"]["p1"].__setitem__("scored_this_turn", {"turn-0": ["bf2"]})))
    final = resolve_battlefield_control(t, e)
    if not final.get("committed") or final["next_effect_state"]["players"]["p1"].get("points") != 3 or final["trace"]["scoring"].get("gain") != "final_point":
        errors.append(f"with every Battlefield scored this turn the Final Point was not gained: {final.get('trace', {}).get('scoring')}")
    else:
        facts = final["trace"]["victory_check"]
        if facts.get("threshold_met") != ["p1"] or facts.get("strict_leader") != "p1" or facts.get("tied_at_threshold") is not False or "combat" not in final["next_timing_state"]:
            errors.append(f"victory facts at the threshold are wrong or the state was ended: {facts}")
    def empty_deck(s):
        two_battlefields(s)
        for card in s["players"]["p1"]["zones"]["main_deck"]:
            del s["objects"][card]
        s["players"]["p1"]["zones"]["main_deck"].clear()
    t, e = decided_combat(victory_score=3, points=2, extra=empty_deck)
    burned = resolve_battlefield_control(t, e)
    if burned.get("committed") or burned.get("unsupported") is not True or burned.get("reason_code") != "burn_out":
        errors.append(f"a draw-instead from an empty deck was not refused whole as burn_out: {burned.get('reason_code')}")
    tie = copy.deepcopy(e); tie["players"]["p2"]["points"] = 3; tie["players"]["p1"]["points"] = 3
    facts = victory_check(tie)
    if facts.get("threshold_met") != ["p1", "p2"] or facts.get("strict_leader") is not None or facts.get("tied_at_threshold") is not True:
        errors.append(f"a tie at the threshold is not reported as such: {facts}")

    # --- refusals -----------------------------------------------------------------------------------------------
    t, e = decided_combat()
    no_mode = copy.deepcopy(e); del no_mode["mode"]
    if resolve_battlefield_control(t, no_mode).get("reason_code") != "mode_unknown" or resolve_battlefield_control(t, no_mode).get("unsupported") is not True:
        errors.append("scoring without a Mode of Play guessed a Victory Score")
    team = copy.deepcopy(e); team["players"]["p1"]["team_id"] = "A"
    if resolve_battlefield_control(t, team).get("reason_code") != "team_scoring":
        errors.append("team scoring was attempted")
    undecided = copy.deepcopy(t); undecided["combat"]["status"] = "cleanup_done"
    if resolve_battlefield_control(undecided, e).get("reason_code") != "control_resolution_not_pending":
        errors.append("control was resolved before the result")
    stale = {"schema_version": "engine-decisions.v1", "input_hash": "sha256:" + "1" * 64, "decisions": []}
    if resolve_battlefield_control(t, e, stale).get("valid") is not False:
        errors.append("a stale decision envelope was accepted")
    bad = copy.deepcopy(e); bad["players"]["p1"]["scored_this_turn"] = {"turn-0": ["bf9"]}
    if not validate_state(bad):
        errors.append("a ledger naming an unknown battlefield was accepted")
    with tempfile.TemporaryDirectory(prefix="control-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(t), encoding="utf-8"); (temp / "e.json").write_text(json.dumps(e), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "control-step", str(temp / "t.json"), str(temp / "e.json"), "--step", "resolve", "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI control-step failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: control resolution checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: after a decided Combat the sole remaining player establishes control atomically with Contested cleared and one Conquer point per Battlefield per turn, a holder gains nothing, an emptied Battlefield becomes Uncontrolled, the Final Point draws instead or refuses whole on Burn Out, Score triggers come from the scoring player's board objects and the Battlefield and hold the close, and the victory condition is reported as facts only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
