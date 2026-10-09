#!/usr/bin/env python3
"""The source in one slot of a pair of Units (package 10, Carnivorous Snapvine: "When you play me, choose an enemy unit
at a battlefield. We deal damage equal to our Mights to each other.").

"We" is the ability's source and the one Unit chosen. The source is not chosen and is not a target: its slot is the typed
reference {object_ref: program_source}, resolved as the instruction executes. A source that is gone then - off the board,
or a new object - cannot have its Might read or be dealt damage, so the pair is ignored as source-unavailable; it is never
an illegal target, because it was never targeted. The chosen Unit stays a target as before.

  P1 both          the source and the chosen Unit deal their Mights to each other, read before either Deal
  P2 source gone   the source left the board: ignored as source-unavailable, nothing dealt, not an illegal target
  P3 new object    the program bound to the source's earlier identity: ignored as source-unavailable, nothing dealt
  P4 target gone   the chosen Unit left the board: the pair is skipped as an illegal target, the source undamaged
  P5 anywhere      the source at a Battlefield and the chosen Unit in a Base: the pair still deals (no place is named)
  F1 finalization  the targets checked as the ability is finalized are the chosen Unit alone - the source's slot is not
                   a target (no decision asked for it, no legality test on it); a chosen ally is still refused there
  V1 two sources   both slots naming the source: refused by validation
  V2 extra field   a source slot that also carries a decision_ref: refused by validation
  V3 not permanent a source that is a spell: refused by name, nothing dealt

    python skill/scripts/check_source_pair_damage.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, SOURCE_UNAVAILABLE_OUTCOME, apply_program,  # noqa: E402
                       hash_value, object_identity, validate_program, validate_state)

errors: list[str] = []
SOURCE = {"object_id": {"object_ref": "program_source"}, "chosen_zone_class": "board", "kind": "unit"}
CHOSEN = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(units, *, source="u1", identity="default", state=None):
    out = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
           "program_id": "snapvine", "controller": "p1", "source_object": source,
           "effects": [{"op": "mutual_damage_current_might", "effect_id": "duel", "units": units}]}
    if identity == "default":
        out["source_identity"] = object_identity(state, source)
    elif identity is not None:
        out["source_identity"] = identity
    return out


def decide(state, pick="u2"):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [pick], "selection_identities": {pick: object_identity(state, pick)}}]}


def run(state, **kwargs):
    return apply_program(state, program([dict(SOURCE), dict(CHOSEN)], state=state, **kwargs), decisions=decide(state))


def duel_event(got):
    return next((e for e in got.get("trace") or [] if e.get("effect_id") == "duel"), {})


def moved(state, unit, to_zone):
    out = copy.deepcopy(state)
    for player in out["players"].values():
        for name, zone in player["zones"].items():
            if unit in zone:
                zone.remove(unit)
    for bf in out["battlefields"].values():
        if unit in bf["objects"]:
            bf["objects"].remove(unit)
    owner = out["objects"][unit]["owner"]
    if to_zone == "bf1":
        out["battlefields"]["bf1"]["objects"].append(unit)
        out["battlefields"]["bf1"]["controller"] = out["objects"][unit]["controller"]
    else:
        out["players"][owner]["zones"].setdefault(to_zone, []).append(unit)
    return out


def main() -> int:
    s = base_state()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    # u1 (p1, the source): Might 3, damage 1. u2 (p2, the chosen Unit): Might 4, damage 0
    got = run(s)
    after = got.get("next_state") or {}
    if not got.get("committed") or after["objects"]["u2"]["damage"] != 3 or after["objects"]["u1"]["damage"] != 5:
        fail("P1 both", f"{got.get('reason_code')} {got.get('reason') or got.get('errors')} "
                        f"{[(after.get('objects') or {}).get(o, {}).get('damage') for o in ('u1', 'u2')]}")
    elif (duel_event(got).get("source_slot") or {}).get("resolved_to") != "u1":
        fail("P1 both", f"the trace does not record the source slot resolved to u1 ({duel_event(got).get('source_slot')})")

    gone = moved(s, "u1", "trash")
    got = apply_program(gone, program([dict(SOURCE), dict(CHOSEN)], state=s), decisions=decide(gone))
    event = duel_event(got)
    if event.get("outcome") != SOURCE_UNAVAILABLE_OUTCOME or (got.get("next_state") or gone)["objects"]["u2"]["damage"] != 0:
        fail("P2 source gone", f"{event.get('outcome')} {got.get('reason_code')} {got.get('reason') or got.get('errors')}")
    if "illegal" in str(event.get("outcome")) or "invalid_targets" in event:
        fail("P2 source gone", "the source was reported as an illegal target; it was never targeted")

    got = run(s, identity="u1@7")
    if duel_event(got).get("outcome") != SOURCE_UNAVAILABLE_OUTCOME or (got.get("next_state") or s)["objects"]["u2"]["damage"] != 0:
        fail("P3 new object", f"{duel_event(got).get('outcome')} {got.get('reason_code')} {got.get('reason')}")

    left = moved(s, "u2", "trash")
    decisions = decide(s)
    decisions["input_hash"] = hash_value(left)
    got = apply_program(left, program([dict(SOURCE), dict(CHOSEN)], state=left), decisions=decisions)
    event = duel_event(got)
    if got.get("committed") and (event.get("outcome") != "ignored_illegal_target"
                                 or got["next_state"]["objects"]["u1"]["damage"] != 1):
        fail("P4 target gone", f"{event.get('outcome')} {got.get('reason_code')}")
    if not got.get("committed") and got.get("valid") is False:
        fail("P4 target gone", f"invalid: {got.get('errors')}")

    away = moved(s, "u1", "bf1")
    got = run(away)
    after = got.get("next_state") or {}
    if not got.get("committed") or after["objects"]["u2"]["damage"] != 3 or after["objects"]["u1"]["damage"] != 5:
        fail("P5 anywhere", f"{got.get('reason_code')} {got.get('reason') or got.get('errors')}")

    from play_transaction import PlayError, _check_play_targets
    staged = program([dict(SOURCE), dict(CHOSEN)], state=s)
    try:
        _check_play_targets(s, "p1", staged, decide(s), stage="trigger_finalization")
    except Exception as exc:  # the source's slot taken for a target, or a decision asked for it
        fail("F1 finalization", f"{type(exc).__name__}: {exc}")
    ally = copy.deepcopy(s)
    ally["objects"]["u3"] = {**copy.deepcopy(s["objects"]["u1"]), "damage": 0}
    ally["players"]["p1"]["zones"]["base"].append("u3")
    try:
        _check_play_targets(ally, "p1", staged, decide(ally, "u3"), stage="trigger_finalization")
        fail("F1 finalization", "a friendly unit was accepted for the enemy slot")
    except PlayError:
        pass
    except Exception as exc:
        fail("F1 finalization", f"{type(exc).__name__}: {exc}")

    if not validate_program(program([dict(SOURCE), dict(SOURCE)], state=s)):
        fail("V1 two sources", "validated")
    if not validate_program(program([{**SOURCE, "decision_ref": "t"}, dict(CHOSEN)], state=s)):
        fail("V2 extra field", "validated")

    spell = program([dict(SOURCE), dict(CHOSEN)], source="c1", identity=None)
    got = apply_program(s, spell, decisions=decide(s))
    if got.get("committed") and got["next_state"]["objects"]["u2"]["damage"] != 0 or got.get("committed"):
        fail("V3 not permanent", f"{got.get('committed')} {duel_event(got).get('outcome')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: source-pair damage checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the source in one slot of a Unit pair is resolved as the instruction executes - both Mights dealt; a source "
          "that left the board or is a new object makes the pair source-unavailable, never an illegal target; a departed "
          "chosen Unit skips the pair; finalization checks the chosen Unit alone; two source slots, a source slot with a "
          "decision, or a spell source are refused (P1-P5, F1, V1-V3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
