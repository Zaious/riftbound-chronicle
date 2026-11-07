#!/usr/bin/env python3
"""Regression gate: "When you defend at a battlefield, you may move me there." (set 2 package A2: Loyal Pup).

  D1  p2 attacks bf1, which p1 holds with two Units: the watcher in p1's Base triggers once (one per combat); finalized
      choosing bf1 - "there", where the Defender the event names is - and resolved, it is at bf1
  D2  a destination other than "there" (p1's Base, bf2) is refused as the ability is finalized
  D3  p1 attacks: nothing (p1 is not defending); the printed form lowers to the watch
  D4  resolved, the card is designated a Defender at bf1: p1 already defended this combat - no second trigger
      (Core 383.4.f.2.a)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from check_trigger_referent import board, into_combat, items, program_of, unit  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402

TEXT = "When you defend at a battlefield, draw 1."
MOVE = [{"op": "move_board_object", "effect_id": "mv", "object_id": {"object_ref": "program_source"},
         "destination": {"decision_ref": "dest", "restriction": "trigger_event_location"}}]


def with_pup(state, descriptor):
    unit(state, "pup", "p1", might=2)
    state["objects"]["pup"]["event_triggers"] = [{**copy.deepcopy(descriptor), "controller": "p1", "source_object": "pup",
                                                  "effect_program_id": "pup-program"}]
    return state


def finalize_with(timing, effect, registry, place):
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(effect), "decisions": [
        {"decision_id": "dest", "kind": "location_selection", "stage": "trigger_finalization", "controller": "p1",
         "value": place}]}
    return finalize_trigger(timing, effect, registry, decisions)


def main() -> int:
    errors: list[str] = []
    got = CG.compile_clause(TEXT)
    rows = ((got.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or []
    if got.get("production_id") != "when_you_defend_at_a_battlefield" or len(rows) != 1 or rows[0]["watch"] != {
            "kinds": ["defended"], "scope": "controller", "filter": {"object_kind": "unit"}, "grouping": "one_per_action"}:
        print(f"defend-and-move-there checks FAILED:\n  - D3: lowered to {got.get('production_id')} {rows}")
        return 1
    descriptor = rows[0]
    registry = {"pup-program": program_of("pup-program", "pup", MOVE)}
    state = with_pup(board(bf1_controller="p1", p1_at_bf1=("d1", "d2"), p2_base=("e1",)), descriptor)
    state["battlefields"]["bf2"] = {"controller": None, "objects": [], "contested": False, "contested_by": None}
    opened, why = into_combat(state, "e1", actor="p2")
    if opened is None:
        errors.append(f"D1: no combat ({why})")
    else:
        timing, effect = opened
        mine = items(timing, "on-you-defend@")
        if len(mine) != 1:
            errors.append(f"D1: two defenders scheduled {[i['id'] for i in timing['chain']['items']]}")
        else:
            for place in ("base:p1", "battlefield:bf2"):
                wrong = finalize_with(timing, effect, registry, place)
                if wrong.get("committed"):
                    errors.append(f"D2: a destination of {place} was accepted")
            done = finalize_with(timing, effect, registry, "battlefield:bf1")
            if not done.get("committed"):
                errors.append(f"D1: finalizing to bf1 was refused: {done.get('reason')} {done.get('message')}")
            else:
                t, e = done["next_timing_state"], done.get("next_effect_state") or effect
                while RC.next_procedure(t).get("procedure") != "resolve_newest_finalized":
                    holder = t.get("priority")
                    passed = RC.pass_priority(t, holder) if holder else {}
                    if not passed.get("next_state"):
                        break
                    t = passed["next_state"]
                resolved = resolve_with_program(t, mine[0]["id"], e, registry["pup-program"])
                if not resolved.get("committed") or IR.find_location(resolved["next_effect_state"], "pup") != ("battlefield", "bf1", None):
                    errors.append(f"D1: resolved, the card is at {IR.find_location((resolved.get('next_effect_state') or e), 'pup')} "
                                  f"({resolved.get('reason')} {resolved.get('reason_code')})")
                else:
                    # D4: at bf1 the card itself gains the Defender designation (Core 466.2.c.3.a), but p1 already
                    # gained it this combat - a Defend trigger's condition is checked once per combat (383.4.f.2.a)
                    again = [i["id"] for i in resolved["next_timing_state"]["chain"]["items"] if "on-you-defend@" in i["id"]]
                    if again:
                        errors.append(f"D4: the card moving into the combat woke the watcher again: {again}")
    attack = with_pup(board(bf1_controller="p2", p2_at_bf1=("e1",), p1_base=("a1",)), descriptor)
    opened, why = into_combat(attack, "a1", actor="p1")
    if opened is None or items(opened[0], "on-you-defend@"):
        errors.append(f"D3: p1 attacking triggered it, or no combat ({why})")
    if errors:
        print("defend-and-move-there checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("defend-and-move-there checks passed: a defence wakes the watcher once per combat; 'there' is the defender's "
          "Battlefield, elsewhere refused; resolved, the card moves there and does not wake it again; attacking wakes nothing; "
          "lowered (D1-D4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
