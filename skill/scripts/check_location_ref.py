#!/usr/bin/env python3
"""
Standing gate: the typed relational reference `{"kind":
"program_source_current_battlefield"}` on the `location_ref` selector field.

GPT 2026-09-23 declined the broad claim that one "program source's current
Battlefield" resolver closes every relational-locator gap the capability
ledger names (14 production_ids, 9 effect families). Core 359.3.f has two
DIFFERENT timing semantics for a relational word:

  359.3.f.2   Yasuo, Remorseful's own worked example: the referent is read at
              INSTRUCTION EXECUTION. Moved back to Base after his attack
              trigger is scheduled, "here" is no longer a Battlefield when the
              instruction runs, and the trigger mistargets.
  359.3.f.3   Lillia, Fae Fawn's own worked example: "there" is captured once,
              when the trigger's CONDITION is fulfilled, and does not move
              with her afterwards.

This capability resolves ONLY the first kind - "here," the resolving
program's own source's CURRENT Battlefield, checked fresh every time an
effect actually runs. It must never be reached for the second kind, and nothing
here narrows or widens the capability_gap_ledger; that stays a separate,
per-production act (mapping review + signature), same as
modifier_ir_contract.v2.2 / widen_might_floor_scope.py's own precedent.

What each case exercises, stated exactly (GPT 2026-09-23 corrected an earlier
claim that all of them ran through apply_program - they do not):

  full apply_program, bulk affected.criteria path only:
      positive, moved, left play, enemy stays put, no auto-widen
  resolve_location_ref() called directly (resolver unit tests):
      positive, moved, left play, identity changed, identity missing
  choice_candidates() called directly (candidate set only):
      establish_selection's board choice at the source's battlefield
  the TARGETED single-target path, end to end through schedule ->
  finalize_trigger -> resolve_with_program (2026-09-23, the vertical slice):
      a target selector carrying location_ref, for each op the cards in scope
      reach (deal_damage, stun, modify_might with a floor): an enemy at the
      source's battlefield is hit; one at another battlefield is refused at
      finalization; a source that moved to another battlefield or to Base
      before resolution makes the recorded target illegal and the instruction
      MISTARGETS (committed, ignored_illegal_target, reason named - Core
      359.3.f.2), never re-chosen; no recorded source identity is refused at
      finalization; location with location_ref, the bound field authored by
      hand, and an unbound location_ref reaching the check are each refused.

  positive         stays at the original Battlefield: resolves there, fires
  moved            moved to a DIFFERENT Battlefield: resolves there fresh, not
                   the one recorded when the descriptor was made
  left play        moved to Base (Core 359.3.f.2's own case): named mistarget,
                   not a resolution to Base or anywhere else
  identity changed same id, a new generation: named refusal, never the new
                   object standing in for the one the reference was about
  identity missing a program with no declared source_identity cannot resolve
                   "here" at all - mandatory here, unlike resolve_object_ref's
                   own optional (and still open) identity check
  enemy stays put  the source's controller changes (Hostile Takeover style);
                   "here" only ever supplies a location - controller_relation
                   still reads the program's OWN controller, never the
                   source's new one (Core 359.3.f.4's own worked example)
  no auto-widen    an ordinary location (active_combat / target_battlefield /
                   any_battlefield) selector, with no location_ref anywhere,
                   behaves exactly as before - this capability changes nothing
                   about the f.3 (Lillia) shape or any existing location value

    python skill/scripts/check_location_ref.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import (LOCATION_REF_KINDS, apply_program, object_identity,  # noqa: E402
                       resolve_location_ref, validate_state)

HERE = {"kind": "program_source_current_battlefield"}


def two_battlefield_state():
    """u1 (p1, the source) and e2 (p2, enemy) at bf1; e3 (p2, enemy) at bf2.
    Nobody in base but the players' other starting objects."""
    state = base_state()
    state["turn_id"] = "T1"
    state["players"]["p1"]["zones"]["base"] = []
    state["players"]["p2"]["zones"]["base"] = []
    state["objects"]["e3"] = {"owner": "p2", "controller": "p2", "kind": "unit",
                              "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
    state["battlefields"] = {
        "bf1": {"controller": None, "objects": ["u1", "u2"]},
        "bf2": {"controller": None, "objects": ["e3"]},
    }
    settle_contested(state)
    return state


def source_identity(state, source="u1"):
    return object_identity(state, source)


def program_with_source(source, *effects):
    doc = program("p1", *effects)
    doc["source_object"] = source
    return doc


def with_source_identity(state, doc, source="u1"):
    return {**doc, "source_identity": source_identity(state, source)}


def deal_damage_here(effect_id="dmg"):
    return {"op": "deal_damage", "amount": 3, "effect_id": effect_id,
            "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(HERE)}}}


def establish_here_choice(effect_id="sel", selection_id="s1", decision_ref="d1"):
    return {"op": "establish_selection", "effect_id": effect_id, "selection_id": selection_id,
            "decision_ref": decision_ref,
            "choice": {"selection_kind": "single", "from": "board",
                      "criteria": {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(HERE)}}}


def main() -> int:
    errors: list[str] = []

    def fail(label, detail):
        errors.append(f"{label}: {detail}")

    def expect_refusal(label, result, code):
        if result.get("committed") is not False:
            return fail(label, f"expected {code}, but the program committed: {result}")
        if result.get("reason_code") != code:
            return fail(label, f"expected {code}, got {result.get('reason_code')!r} "
                               f"({result.get('reason') or result.get('errors')})")

    state = two_battlefield_state()
    if found := validate_state(state):
        fail("fixture", f"the base fixture is invalid: {found}")
        print("\n".join(f"FAILED: {e}" for e in errors))
        return 1

    # --- resolve_location_ref() directly: the six named cases -----------------
    prog = with_source_identity(state, {"source_object": "u1", "controller": "p1"})

    resolved = resolve_location_ref(HERE, state, prog)
    if resolved != "bf1":
        fail("positive: stays at bf1", f"resolved to {resolved!r}, not bf1")

    moved = copy.deepcopy(state)
    moved["battlefields"]["bf1"]["objects"].remove("u1")
    moved["battlefields"]["bf2"]["objects"].append("u1")
    resolved_moved = resolve_location_ref(HERE, moved, with_source_identity(moved, prog))
    if resolved_moved != "bf2":
        fail("moved to a different battlefield", f"resolved to {resolved_moved!r}, not the NEW battlefield bf2 "
                                                  f"- the reference was bound early instead of read fresh")

    left = copy.deepcopy(state)
    left["battlefields"]["bf1"]["objects"].remove("u1")
    left["players"]["p1"]["zones"]["base"].append("u1")
    try:
        resolve_location_ref(HERE, left, with_source_identity(left, prog))
        fail("moved to Base (Core 359.3.f.2's own case)", "resolved instead of mistargeting")
    except effect_ir.SelectionBindingRefused as exc:
        if exc.reason_code != effect_ir.LOCATION_REF_NOT_AT_BATTLEFIELD:
            fail("moved to Base", f"wrong code {exc.reason_code!r}")

    changed = copy.deepcopy(state)
    changed["objects"]["u1"]["identity"] = "u1@9"
    stale_prog = {**prog, "source_identity": "u1@0"}
    try:
        resolve_location_ref(HERE, changed, stale_prog)
        fail("identity changed (new generation, same id)", "resolved against the new object instead of refusing")
    except effect_ir.SelectionBindingRefused as exc:
        if exc.reason_code != effect_ir.LOCATION_REF_IDENTITY_CHANGED:
            fail("identity changed", f"wrong code {exc.reason_code!r}")

    undeclared = {"source_object": "u1", "controller": "p1"}
    try:
        resolve_location_ref(HERE, state, undeclared)
        fail("identity missing (mandatory here)", "resolved with no declared source_identity at all")
    except effect_ir.SelectionBindingRefused as exc:
        if exc.reason_code != effect_ir.LOCATION_REF_ABSENT:
            fail("identity missing", f"wrong code {exc.reason_code!r}")

    no_source = {"controller": "p1", "source_identity": "whatever"}
    try:
        resolve_location_ref(HERE, state, no_source)
        fail("no source_object at all", "resolved with nothing to resolve")
    except effect_ir.SelectionBindingRefused as exc:
        if exc.reason_code != effect_ir.LOCATION_REF_ABSENT:
            fail("no source_object", f"wrong code {exc.reason_code!r}")

    # --- real apply_program, the "affected" bulk path (Anivia's shape) ---------
    real_prog = with_source_identity(state, program_with_source("u1", deal_damage_here()))
    result = apply_program(state, real_prog)
    if result.get("committed") is not True:
        fail("real bulk effect at bf1", f"did not commit: {result.get('reason') or result.get('errors')}")
    else:
        event = next((e for e in result["trace"] if e.get("op") == "deal_damage"), {})
        if event.get("affected_objects") != ["u2"]:
            fail("real bulk effect at bf1", f"affected {event.get('affected_objects')}, expected exactly ['u2'] "
                                            f"(the enemy at u1's OWN battlefield, never e3 at bf2)")

    moved_real = copy.deepcopy(state)
    moved_real["battlefields"]["bf1"]["objects"].remove("u1")
    moved_real["battlefields"]["bf2"]["objects"].append("u1")
    moved_prog = with_source_identity(moved_real, program_with_source("u1", deal_damage_here()))
    result = apply_program(moved_real, moved_prog)
    if result.get("committed") is not True:
        fail("real bulk effect after moving to bf2", f"did not commit: {result.get('reason') or result.get('errors')}")
    else:
        event = next((e for e in result["trace"] if e.get("op") == "deal_damage"), {})
        if event.get("affected_objects") != ["e3"]:
            fail("real bulk effect after moving to bf2", f"affected {event.get('affected_objects')}, expected "
                                                          f"exactly ['e3'] - the dynamic recompute did not happen")

    left_real = copy.deepcopy(state)
    left_real["battlefields"]["bf1"]["objects"].remove("u1")
    left_real["players"]["p1"]["zones"]["base"].append("u1")
    left_prog = with_source_identity(left_real, program_with_source("u1", deal_damage_here()))
    expect_refusal("real bulk effect, source moved to Base (Yasuo's own mistarget)",
                   apply_program(left_real, left_prog), effect_ir.LOCATION_REF_NOT_AT_BATTLEFIELD)

    # --- real apply_program, the establish_selection "board" choice path
    # (Crackshot Corsair / Leona's single-target shape) --------------------------
    import engine_decisions as ed
    sel_prog = with_source_identity(state, program_with_source("u1", establish_here_choice()))
    input_hash = effect_ir.hash_value(state)
    decisions = {"schema_version": ed.DECISIONS_VERSION, "input_hash": input_hash,
                "decisions": [{"decision_id": "d1", "stage": "resolution", "kind": "target_selection",
                              "controller": "p1", "value": ["u2"], "selection_identities": {"u2": source_identity(state, "u2")}}]}
    result = apply_program(state, sel_prog, decisions=decisions)
    if result.get("committed") is not True:
        fail("real establish_selection at bf1", f"did not commit: {result.get('reason') or result.get('errors')}")

    # candidate list itself, at the point the choice would be offered, is
    # exactly the enemy at u1's OWN battlefield - never e3 at bf2
    candidates, _ = effect_ir.choice_candidates(
        state, {"selection_kind": "single", "from": "board",
               "criteria": {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(HERE)}},
        "p1", program=with_source_identity(state, {"source_object": "u1", "controller": "p1"}))
    if candidates != ["u2"]:
        fail("candidate list at bf1", f"candidates were {candidates}, expected exactly ['u2']")

    # --- "here" decides location only - controller_relation still reads the
    # program's OWN controller, never the source's new one (Core 359.3.f.4:
    # Yasuo controlled by Hostile Takeover, his attack trigger's 'enemy' is
    # unaffected) ---------------------------------------------------------------
    takeover = copy.deepcopy(state)
    takeover["objects"]["u1"]["controller"] = "p2"  # u1 changes hands mid-chain
    takeover_prog = with_source_identity(takeover, program_with_source("u1", deal_damage_here()))  # program.controller stays p1
    result = apply_program(takeover, takeover_prog)
    if result.get("committed") is not True:
        fail("controller changed mid-chain", f"did not commit: {result.get('reason') or result.get('errors')}")
    else:
        event = next((e for e in result["trace"] if e.get("op") == "deal_damage"), {})
        # u1 is now p2's; "here" still resolves to bf1 (u1's real current
        # position - location resolution is unaffected by a controller change).
        # "enemy" is read against the PROGRAM's controller (p1, fixed since the
        # ability was created), never u1's own new one - so BOTH p2 units at
        # bf1 count as enemy to p1's program, u1 (the source) included, exactly
        # Core 359.3.f.4's own point: after a takeover, the source itself can
        # become a legitimate enemy target of its own ability. A buggy reading
        # that re-derived "enemy" from the SOURCE's new controller (p2) would
        # instead see p2's own units as friendly and hit nothing.
        if sorted(event.get("affected_objects") or []) != ["u1", "u2"]:
            fail("controller changed mid-chain", f"affected {event.get('affected_objects')}, expected exactly "
                                                  f"['u1', 'u2'] - 'enemy' should stay bound to the program's own "
                                                  f"controller (p1), not drift to the source's new one (p2)")

    # --- no auto-widening: an ordinary location value, no location_ref anywhere,
    # is untouched by this capability (the Lillia / 359.3.f.3 shape stays out) --
    ordinary = {"op": "deal_damage", "amount": 1, "effect_id": "ordinary",
               "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "any_battlefield"}}}
    result = apply_program(state, program("p1", ordinary))
    if result.get("committed") is not True:
        fail("ordinary any_battlefield location, untouched", f"did not commit: {result.get('reason') or result.get('errors')}")
    else:
        event = next((e for e in result["trace"] if e.get("op") == "deal_damage"), {})
        if sorted(event.get("affected_objects") or []) != ["e3", "u2"]:
            fail("ordinary any_battlefield location, untouched", f"affected {event.get('affected_objects')}, "
                                                                  f"expected both enemies at every battlefield - "
                                                                  f"an existing location value's behaviour moved")
    if not effect_ir.is_location_ref(HERE):
        fail("is_location_ref", "the one admitted shape was not recognised as a location_ref")
    if effect_ir.is_location_ref({"kind": "anaphoric_there"}):
        fail("is_location_ref", "an unknown kind (e.g. a future 359.3.f.3 'there') was accepted as if it were this capability")
    if len(LOCATION_REF_KINDS) != 1:
        fail("capability stays narrow", f"LOCATION_REF_KINDS is {LOCATION_REF_KINDS}; GPT 2026-09-23 approved exactly "
                                        f"one kind for this first cut, not a general relational-locator capability")

    # --- the single-target, TARGETED path (Crackshot Corsair's shape: "deal 1 to an
    # enemy unit here"), end to end through schedule -> finalize_trigger -> resolve.
    # The target is chosen at finalization and must be at the source's Battlefield
    # then; it is checked again at resolution, so a source that moved makes it
    # illegal and the instruction mistargets (Core 359.3.f.2) - never re-chosen.
    import check_trigger_source_identity as TS
    from resolution_bridge import finalize_trigger, program_hash, resolve_with_program
    from rules_core import pass_priority, schedule_triggered_items
    from check_rules_core import fixture

    HERE_TARGET = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                   "controller_relation": "enemy", "location_ref": dict(HERE)}
    # the three ops "an enemy unit here" reaches on the cards in scope: Crackshot Corsair
    # (deal_damage), Leona - Determined (stun), Ahri - Inquisitive (modify_might with a floor)
    OPS = {
        "deal_damage": ({"op": "deal_damage", "effect_id": "dmg", "amount": 1},
                        lambda s: s["objects"]["u2"].get("damage", 0) == 1),
        "stun": ({"op": "stun", "effect_id": "st"},
                 lambda s: s["objects"]["u2"].get("stunned") is True),
        "modify_might": ({"op": "modify_might", "effect_id": "mm", "amount": -2, "minimum": 1,
                          "duration": "this_turn", "source": TS.TRIGGER},
                         lambda s: effect_ir.effective_might(s, "u2") == max(1, effect_ir.effective_might(TS.board(), "u2") - 2)),
    }
    current_op = {"name": "deal_damage"}

    def targeted_program():
        doc = TS.program()
        doc["effects"] = [{**OPS[current_op["name"]][0], "target": dict(HERE_TARGET)}]
        return doc

    def pick(board, object_id):
        return {"schema_version": "engine-decisions.v1", "input_hash": effect_ir.hash_value(board),
                "decisions": [{"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection",
                               "controller": "p1", "value": [object_id],
                               "selection_identities": {object_id: object_identity(board, object_id)}}]}

    def targeted(board, chosen, *, identity="own", before_resolution=None):
        entry = TS.descriptor(board, identity=identity)
        entry["effect_program_hash"] = program_hash(targeted_program())
        timing = schedule_triggered_items(fixture(), [entry])["next_state"]
        finalized = finalize_trigger(timing, board, {TS.PROGRAM_ID: targeted_program()}, pick(board, chosen))
        if not finalized.get("committed"):
            return {"stage": "finalize", "result": finalized}
        timing = finalized["next_timing_state"]
        for actor in ("p1", "p2"):
            timing = pass_priority(timing, actor).get("next_state") or timing
        after = copy.deepcopy(board)
        if before_resolution is not None:
            before_resolution(after)
        return {"stage": "resolve", "result": resolve_with_program(timing, TS.TRIGGER, after, targeted_program()),
                "board": after}

    def damage(done, object_id):
        return (done["result"].get("next_effect_state") or {}).get("objects", {}).get(object_id, {}).get("damage", 0)

    board = TS.board()
    for name, (_, landed) in OPS.items():
        current_op["name"] = name
        done = targeted(board, "u2")
        after = done["result"].get("next_effect_state") if done["stage"] == "resolve" else None
        if not (after and done["result"].get("committed") and landed(after)):
            fail(f"targeted {name}: enemy at the source's battlefield", f"stage {done['stage']}, committed "
                 f"{done['result'].get('committed')}, effect landed {bool(after and landed(after))} "
                 f"({done['result'].get('reason')})")
        moved = targeted(board, "u2", before_resolution=lambda s: (s["battlefields"]["bf1"]["objects"].remove("u1"),
                                                                    s["battlefields"]["bf2"]["objects"].append("u1")))
        steps = ((moved["result"].get("trace") or {}).get("effect") or []) if moved["stage"] == "resolve" else []
        step = next((e for e in steps if e.get("op") == name), {})
        if moved["result"].get("committed") is not True or step.get("outcome") != "ignored_illegal_target":
            fail(f"targeted {name}: source moved before resolution", f"expected a committed mistarget, got "
                 f"committed={moved['result'].get('committed')} outcome={step.get('outcome')} {moved['result'].get('reason')}")
    current_op["name"] = "deal_damage"

    done = targeted(board, "e3")
    if done["stage"] != "finalize" or "target_not_at_source_battlefield" not in str(done["result"].get("message") or done["result"].get("reason")):
        fail("targeted: enemy at ANOTHER battlefield refused at finalization",
             f"stage {done['stage']}: {done['result'].get('reason')} {done['result'].get('message')}")

    def source_to(where_to):
        def move(s):
            s["battlefields"]["bf1"]["objects"].remove("u1")
            if where_to == "base":
                s["players"]["p1"]["zones"]["base"].append("u1")
            else:
                s["battlefields"][where_to]["objects"].append("u1")
        return move

    # a mistarget is a COMMITTED resolution whose instruction is ignored for an illegal
    # target, with the reason named - not a refused program, and not a hit
    for label, where_to, reason in (
            ("source moved to another battlefield", "bf2", "target_not_at_source_battlefield"),
            ("source moved to Base (Core 359.3.f.2)", "base", effect_ir.LOCATION_REF_NOT_AT_BATTLEFIELD)):
        done = targeted(board, "u2", before_resolution=source_to(where_to))
        steps = ((done["result"].get("trace") or {}).get("effect") or []) if done["stage"] == "resolve" else []
        step = next((e for e in steps if e.get("op") == "deal_damage"), {})
        if done["stage"] != "resolve" or done["result"].get("committed") is not True:
            fail(f"targeted: {label}", f"expected a committed mistarget, got stage {done['stage']} "
                                       f"committed={done['result'].get('committed')} {done['result'].get('reason')}")
        elif (step.get("outcome"), step.get("reason")) != ("ignored_illegal_target", reason) or damage(done, "u2") or damage(done, "e3"):
            fail(f"targeted: {label}", f"expected ignored_illegal_target / {reason} with nothing hit, got "
                                       f"{step.get('outcome')} / {step.get('reason')} (u2 {damage(done, 'u2')}, e3 {damage(done, 'e3')})")

    done = targeted(board, "u2", identity=None)
    if done["stage"] != "finalize" or effect_ir.LOCATION_REF_ABSENT not in str(done["result"].get("message") or ""):
        fail("targeted: no recorded source identity", f"expected a refusal naming {effect_ir.LOCATION_REF_ABSENT} "
                                                      f"at finalization, got stage {done['stage']}: {done['result'].get('message')}")

    both = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "location": "battlefield", "location_ref": dict(HERE)}
    if not any("both location and location_ref" in e for e in effect_ir._selector_errors(both)):
        fail("targeted: location and location_ref together", "the selector validated")
    forged = {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit", "location_battlefield": "bf1"}
    if not effect_ir._selector_errors(forged):
        fail("targeted: the bound field is not authorable", "a selector carrying location_battlefield validated")
    ok, reason = effect_ir.evaluate_target(board, {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit",
                                                   "location_ref": dict(HERE)}, "p1")
    if ok or reason != "target_location_ref_unresolved":
        fail("targeted: an unbound location_ref", f"evaluate_target said {ok}, {reason!r}")

    if errors:
        print("FAILED: relational location_ref (here)")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("relational location_ref: resolves fresh at instruction execution (positive, moved-to-another-battlefield); "
          "named refusals for Base/off-board, changed identity, and missing identity (mandatory, unlike "
          "resolve_object_ref's own optional one); full apply_program on the bulk 'affected' path; the targeted "
          "single-target path end to end for deal_damage, stun and modify_might (hit at the source's battlefield, "
          "refused elsewhere at finalization, a committed mistarget after the source moves); establish_selection's "
          "board choice is checked at the candidate set, not end to end; controller_relation stays bound "
          "to the program's own controller through a source controller change; an ordinary location value is "
          "untouched; the vocabulary stays exactly one kind, no auto-widening toward a 359.3.f.3 (Lillia/there) shape.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
