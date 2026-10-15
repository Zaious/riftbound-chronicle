#!/usr/bin/env python3
"""Gate: ending the Main Phase is a discretionary action of its own (package 13, C2; GPT 2026-10-15 ruling 6).

Core 316.9: the player who has no more Discretionary Actions to take indicates the turn is ending, which ends the Main
Phase. It is not passing Priority - that is only legal while a Chain exists - and it is the Turn Player's alone.

  E1 offered     Neutral Open, Chain empty, p1's Main Phase: the timing check allows it for p1, the enumerator offers
                 it, and resolution_bridge.end_main_phase enters the Ending Step exactly as begin_ending_step does
  E2 a Chain     the Chain holds an item: refused, not offered
  E3 Showdown    a Showdown is open: refused, not offered
  E4 not yours   p2 in p1's Main Phase: refused, not offered, and the transition refuses p2 by name
  E5 a task      an outstanding task: refused
  E6 not a pass  in that same Neutral Open, passing Priority is not legal and not offered - the two are different actions

    python skill/scripts/check_end_main_phase.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import legal_action as la  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from resolution_bridge import begin_ending_step, end_main_phase  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, validate_timing  # noqa: E402

errors: list[str] = []


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def offered(timing, effect, actor) -> set[str]:
    observation = la.build_observation(
        perspective={"p1": "player1", "p2": "player2"}[actor], source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard",
                 "card_data_version": "synthetic"},
        timing_state=timing, effect_state=effect, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"})
    result = la.enumerate_actions(observation, actor)
    if la.validate_result(result):
        fail("result", f"{la.validate_result(result)[:2]}")
    return {a["family"] for a in result["enumeration"]["actions"]}


def verdict(timing, actor):
    return validate_timing(timing, {"actor": actor, "kind": "end_main_phase", "timing": "default"})


def main() -> int:
    effect = base_state()
    open_state = fixture()
    # E1
    allowed = verdict(open_state, "p1")
    if allowed.get("legal") is not True:
        fail("E1 offered", f"refused: {allowed.get('reason_code')}")
    if "end_main_phase" not in offered(open_state, effect, "p1"):
        fail("E1 offered", "the enumerator did not offer it")
    via_action = end_main_phase(copy.deepcopy(open_state), copy.deepcopy(effect), "p1")
    direct = begin_ending_step(copy.deepcopy(open_state), copy.deepcopy(effect))
    if not via_action.get("committed") or {k: v for k, v in via_action.items() if k != "procedure"} \
            != {k: v for k, v in direct.items() if k != "procedure"}:
        fail("E1 offered", f"the action did not enter the Ending Step as begin_ending_step does: "
                           f"{via_action.get('reason_code')} {via_action.get('committed')}")
    # E2 - E5
    for label, timing, actor, reason in (
            ("E2 a Chain", fixture(items=[item("spell-1", "p1", "spell", "default")]), "p1",
             "end_main_phase_requires_neutral_open"),
            ("E3 Showdown", fixture(showdown=True, focus="p1"), "p1", "end_main_phase_requires_neutral_open"),
            ("E4 not yours", fixture(priority="p2"), "p2", "end_main_phase_requires_own_main_phase"),
            ("E5 a task", fixture(tasks=["cleanup"]), "p1", None)):
        got = verdict(timing, actor)
        if got.get("legal") is not False or (reason is not None and got.get("reason_code") != reason):
            fail(label, f"{got.get('legal')} {got.get('reason_code')}")
        if label != "E5 a task" and "end_main_phase" in offered(timing, effect, actor):
            fail(label, "the enumerator offered it")
    refused = end_main_phase(fixture(priority="p2"), copy.deepcopy(effect), "p2")
    if refused.get("committed") or refused.get("reason_code") != "end_main_phase_requires_own_main_phase":
        fail("E4 not yours", f"the transition took p2's action: {refused.get('committed')} {refused.get('reason_code')}")
    # E6
    if validate_timing(open_state, {"actor": "p1", "kind": "pass_priority", "timing": "default"}).get("legal") is not False:
        fail("E6 not a pass", "passing Priority was legal in Neutral Open")
    if "pass_priority" in offered(open_state, effect, "p1"):
        fail("E6 not a pass", "passing Priority was offered in Neutral Open")

    if errors:
        print("FAILED: ending the Main Phase")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: ending the Main Phase is the Turn Player's own discretionary action in Neutral Open with the Chain empty - "
          "offered, and entering the Ending Step; refused and not offered with a Chain, in a Showdown, to the other "
          "player or with a task outstanding; not a pass (E1-E6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
