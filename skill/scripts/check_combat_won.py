#!/usr/bin/env python3
"""Regression gate: a won combat wakes its watchers as the result is determined (set 2 package A2; Core 468.3.a, 468.3.c).

  W1  p1's attacker kills the defender: "When you win a combat" on a p1 permanent is scheduled once; "When I win a
      combat" on the attacker is scheduled for it; the same watch on another p1 unit not in the combat is not; p2's
      "When you win a combat" is not
  W2  the triggers are on the Chain as the result is determined, so control is established after them (468.4):
      resolve_battlefield_control refuses while they are pending
  W3  a tie (both die): nothing is scheduled
  W4  the grammar lowers both printed forms to these watches
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from battlefield_control import resolve_battlefield_control  # noqa: E402
from check_combat_damage_assignment import closed_combat  # noqa: E402
from check_combat_tie_recall_all import through_cleanup  # noqa: E402
from combat import combined_input_hash, determine_combat_result  # noqa: E402

errors: list[str] = []
YOU = {"trigger_id": "you-win", "controller_order": 0, "effect_program_id": "p", "optional_at_finalize": False,
       "watch": {"kinds": ["won_combat"], "scope": "actor", "grouping": "one_or_more"}}
ME = {"trigger_id": "i-win", "controller_order": 0, "effect_program_id": "p", "optional_at_finalize": False,
      "watch": {"kinds": ["won_combat"], "scope": "self", "grouping": "each"}}


def watched(effect):
    e = copy.deepcopy(effect)
    for oid, owner, descriptor in (("p1-banner", "p1", YOU), ("p2-banner", "p2", YOU)):
        e["objects"][oid] = {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False,
                             "event_triggers": [{**descriptor, "trigger_id": f"{descriptor['trigger_id']}:{oid}",
                                                 "controller": owner, "source_object": oid}]}
        e["players"][owner]["zones"]["base"].append(oid)
    e["objects"]["u1"]["event_triggers"] = [{**ME, "controller": "p1", "source_object": "u1"}]
    e["objects"]["p1-bystander"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                                    "damage": 0, "exhausted": False,
                                    "event_triggers": [{**ME, "trigger_id": "i-win:bystander", "controller": "p1",
                                                        "source_object": "p1-bystander"}]}
    e["players"]["p1"]["zones"]["base"].append("p1-bystander")
    return e


def scheduled(result):
    items = result["next_timing_state"]["chain"]["items"]
    return sorted((i.get("source_object") or i.get("source"), i.get("trigger_id", "")) for i in items)


def main() -> int:
    t, e = closed_combat([("d1", {"might": 3})], attacker_might=5)
    got, why = through_cleanup(t, watched(e))
    if got is None:
        errors.append(f"W1: the combat did not reach its result: {why}")
    else:
        r = determine_combat_result(*got)
        if r.get("reason_code") == "trigger_order_required":
            # p1's two abilities triggered together: their order is p1's choice (Core 383.3.d)
            r = determine_combat_result(*got, {"schema_version": "engine-decisions.v1",
                                               "input_hash": combined_input_hash(*got), "decisions": [
                {"decision_id": r["decision_ids"][0], "stage": "resolution", "kind": "trigger_order",
                 "controller": r["decision_controller"], "value": list(r["trigger_ids"])}]})
        if not r.get("committed") or r["next_timing_state"]["combat"]["result"].get("outcome") != "win":
            errors.append(f"W1: {r.get('reason_code')} {r.get('reason')}")
        else:
            items = r["next_timing_state"]["chain"]["items"]
            sources = sorted(str(i.get("source_object") or (i.get("source") or {}).get("object")) for i in items)
            if sources != ["p1-banner", "u1"]:
                errors.append(f"W1: scheduled from {sources} ({[i.get('id') for i in items]}), not p1-banner and u1")
            control = resolve_battlefield_control(r["next_timing_state"], r["next_effect_state"])
            if control.get("committed") or control.get("reason_code") != "combat_chain_unfinished":
                errors.append(f"W2: control was established with the result's triggers pending: {control.get('reason_code')}")
    t, e = closed_combat([("d1", {"might": 5})], attacker_might=5)
    got, why = through_cleanup(t, watched(e))
    r = determine_combat_result(*got) if got else {}
    if not r.get("committed") or r["next_timing_state"]["chain"]["items"]:
        errors.append(f"W3: a tie scheduled {(r.get('next_timing_state') or {}).get('chain', {}).get('items')} ({why})")
    grammar = cg.load_grammar()
    for text, want in (("When you win a combat, draw 1.", YOU["watch"]), ("When I win a combat, draw 1.", ME["watch"])):
        got = cg.compile_clause(text, grammar)
        watch = ((((got.get("passive") or got).get("object_fields") or {}).get("event_triggers") or [{}])[0]).get("watch")
        if watch != want:
            errors.append(f"W4: {text!r} lowered to {watch}")
    if errors:
        print("combat won checks FAILED:")
        for e_ in errors:
            print(f"  - {e_}")
        return 1
    print("combat won checks passed: a won combat schedules the winner's 'When you win a combat' once and each winning "
          "unit's own, before control is established; a tie schedules nothing; both printed forms lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
