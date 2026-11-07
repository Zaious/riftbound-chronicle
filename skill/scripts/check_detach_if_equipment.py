#!/usr/bin/env python3
"""Regression gate: "you may ready a friendly gear. If it's an Equipment, you may detach it." (set 2 package A2:
Veiled Temple). The gear readied is "it" (subject_ref on detach); "If it's an Equipment" reads that gear, still on the
board as itself, carrying the Equipment tag now (predicate linked_object_has_tag; Core 133.8, 359.3.e.14); "you may
detach it" is decided as it resolves (Core 355.12). Detaching a card that is not attached does nothing (436.1.a).

  E1 attached, detached    p1's exhausted Equipment on u1 in p1's Base: readied; detach asked; yes -> unattached
  E2 attached, kept        the same, the detach declined: still on u1, readied
  E3 not an Equipment      an exhausted gear with no Equipment tag: readied; the detach is skipped, nothing asked
  E4 not attached          an Equipment on its own: readied; detach asked; yes -> nothing to detach (no_op)
  E5 referent gone         the readied gear killed between the ready and the Equipment check (a kill instruction
                           interleaved in the program, standing in for the gear leaving mid-resolution): "it" is a new
                           object in the trash (Core 124), so the detach is not asked and does nothing - and the skip
                           must carry a named reason (the referent left), not the same silent trace as E3 (external
                           rules reviewer ruling, 2026-11)
  E6 detached at a bf      u1 and its Equipment at bf1, detach yes: the gear stays at bf1, unattached (Core 436.4; its
                           recall waits for the next Cleanup, 436.4.a - only the state right after the detach is read)
  V  validation           the predicate's closed shape; detach with neither object_id nor subject_ref refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, find_location, hash_value, object_identity,  # noqa: E402
                       validate_program)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

READY = {"op": "ready", "effect_id": "rd", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "gear",
                                                     "controller_relation": "friendly"}}
DETACH = {"op": "detach", "effect_id": "dt", "subject_ref": {"kind": "linked_object", "effect_id": "rd"},
          "optional": {"decision_ref": "dq"},
          "predicate": {"kind": "linked_object_has_tag", "effect_id": "rd", "tag": "Equipment"}}


def board(tags=("Equipment",), attached=True):
    s = base_state()
    s["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "exhausted": True, "tags": list(tags),
                          "base_might": 0, "damage": 0, "might_modifiers": [],
                          **({"attached_to": "u1"} if attached else {})}
    s["players"]["p1"]["zones"]["base"].append("g1")
    return s


def at_battlefield():
    """u1 and its attached Equipment g1 at bf1, controlled by p1."""
    s = board()
    for oid in ("u1", "g1"):
        s["players"]["p1"]["zones"]["base"].remove(oid)
        s["battlefields"]["bf1"]["objects"].append(oid)
    s["battlefields"]["bf1"]["controller"] = "p1"
    return s


def program(killed_between=False):
    effects = [copy.deepcopy(READY), copy.deepcopy(DETACH)]
    if killed_between:
        effects.insert(1, {"op": "kill", "effect_id": "kg", "object_id": "g1"})
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "veiled-temple", "controller": "p1", "source_object": "c1", "effects": effects}


def named_reason(event):
    return event.get("reason_code") or event.get("reason")


def decide(state, detach=None):
    entries = [{"decision_id": "t", "kind": "target_selection", "stage": "play_declaration", "controller": "p1",
                "value": ["g1"], "selection_identities": {"g1": object_identity(state, "g1")}}]
    if detach is not None:
        entries.append({"decision_id": "dq", "kind": "optional_choice", "stage": "resolution", "controller": "p1",
                        "value": detach})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": entries}


def outcomes(done):
    return [t.get("outcome") for t in done.get("trace") or []]


def main() -> int:
    errors: list[str] = []
    if validate_program(program()):
        errors.append(f"V: the card's program is invalid: {validate_program(program())}")
    s = board()
    asked = apply_program(s, program(), decisions=decide(s))
    if asked.get("reason_code") != "optional_choice_required" or asked.get("decision_ids") != ["dq"]:
        errors.append(f"E1 asked: {asked.get('reason_code')} {asked.get('errors')}")
    for label, state, detach, attached_after, want in (
            ("E1 attached, detached", board(), True, None, ["applied", "applied"]),
            ("E2 attached, kept", board(), False, "u1", ["applied", "declined"]),
            ("E3 not an Equipment", board(tags=()), None, "u1", ["applied", "skipped_linked_dependency"]),
            ("E4 not attached", board(attached=False), True, None, ["applied", "no_op"])):
        done = apply_program(state, program(), decisions=decide(state, detach))
        g1 = (done.get("next_state") or {}).get("objects", {}).get("g1") or {}
        if not done.get("committed") or outcomes(done) != want or g1.get("exhausted") is not False \
                or g1.get("attached_to") != attached_after:
            errors.append(f"{label}: {done.get('reason') or done.get('errors')} {outcomes(done)} {g1}")
    # E5: the readied gear is killed before "If it's an Equipment" is read
    s = board()
    if validate_program(program(killed_between=True)):
        errors.append(f"E5: the interleaved program is invalid: {validate_program(program(killed_between=True))}")
    else:
        done = apply_program(s, program(killed_between=True), decisions=decide(s, True))
        after = done.get("next_state") or {}
        detach = next((t for t in done.get("trace") or [] if t.get("effect_id") == "dt"), {})
        s3 = board(tags=())
        e3 = next((t for t in apply_program(s3, program(), decisions=decide(s3)).get("trace") or []
                   if t.get("effect_id") == "dt"), {})
        if not done.get("committed") or "g1" not in after.get("players", {}).get("p1", {}).get("zones", {}).get("trash", []) \
                or detach.get("outcome") not in ("skipped_linked_dependency", "ignored_illegal_target",
                                                 "skipped_illegal_target"):
            errors.append(f"E5 referent gone: {done.get('reason_code')} {done.get('reason') or done.get('errors')} "
                          f"{outcomes(done)} detach {detach}")
        elif not named_reason(detach) or named_reason(detach) == named_reason(e3):
            errors.append(f"E5 referent gone: the detach was skipped ({detach.get('outcome')!r}) but with no reason naming "
                          f"the readied gear as gone - its trace is the same as E3's 'not an Equipment' "
                          f"(reason {named_reason(detach)!r}); effect_ir.apply_program's linked_object_has_tag branch "
                          f"folds 'not on the board as itself' into predicate_result False")
    # E6: detached at a battlefield, the gear stays there, unattached, right after the detach
    s = at_battlefield()
    done = apply_program(s, program(), decisions=decide(s, True))
    after = done.get("next_state") or {}
    g1 = after.get("objects", {}).get("g1") or {}
    if not done.get("committed") or outcomes(done) != ["applied", "applied"] \
            or find_location(after, "g1") != ("battlefield", "bf1", None) or g1.get("attached_to") is not None:
        errors.append(f"E6 detached at a bf: {done.get('reason') or done.get('errors')} {outcomes(done)} "
                      f"g1 at {find_location(after, 'g1') if after else None} {g1}")
    for label, bad in (("an extra key", {**DETACH, "predicate": {**DETACH["predicate"], "x": 1}}),
                       ("no tag", {**DETACH, "predicate": {"kind": "linked_object_has_tag", "effect_id": "rd"}}),
                       ("a later instruction", {**DETACH, "predicate": {**DETACH["predicate"], "effect_id": "zz"}}),
                       ("no object", {k: v for k, v in DETACH.items() if k != "subject_ref"})):
        prog = program()
        prog["effects"][1] = bad
        if not validate_program(prog):
            errors.append(f"V: {label} was accepted")
    if errors:
        print("detach-if-equipment checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("detach-if-equipment checks passed: the readied gear is 'it'; an Equipment is offered the detach, decided as it "
          "resolves; a gear with no Equipment tag is not; an unattached Equipment detaches nothing; a gear gone before "
          "the check is skipped by name; detached at a battlefield it stays there (E1-E6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
