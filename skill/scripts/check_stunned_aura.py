#!/usr/bin/env python3
"""
Regression gate: a printed decrease over Stunned enemy units, with its own floor (2026-09-27).

"Stunned enemy units here have -8 [M], to a minimum of 1 [M]." is a passive ability of a unit on
the board (Core 365.1): an Arithmetic-layer decrease over the enemy Units at its source's
Battlefield that are Stunned right now (423.1.a - Stunned is a binary state), limited to its floor.
Its source is a passive ability, so the limit is applied fresh each time the Might is computed,
never snapshotted (477.3.b, its second example). The engine grammar lowers the sentence to a
`static_auras` entry with `minimum` and the criterion `stunned` (effect_ir.printed_aura_effects).

Must hold (Units stunned by the engine's own stun instruction, so each board is a valid state):
  - a Stunned enemy Unit of 10 at the source's Battlefield is at 2; one of 3 is held at 1; one
    of 1 stays at 1 (the floor moves nothing, 477.3.c is not needed);
  - an unstunned enemy Unit there, a Stunned enemy Unit at another Battlefield, a Stunned
    friendly Unit there, and the source itself are untouched;
  - the source moved to its Base: nothing at the Battlefield is decreased ("here");
  - the source gone to the trash: nothing is decreased (365.1);
  - the Unit's own +2 this turn applied after the stun: the floor is recomputed on the new
    Might (10+2-8 = 4; 3+2 -> 1 held; no snapshot);
  - the stun expiring (the turn ends): the decrease stops;
  - the grammar lowers the card's sentence to exactly this aura;
  - invalid: a floor on an increase, a negative floor, a floor that is not an integer, and a
    criterion `stunned` that is not true;
  - mutations caught: an engine that ignores the `stunned` criterion; one that drops the floor.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

SENTENCE = "Stunned enemy units here have -8 :rb_might:, to a minimum of 1 :rb_might:."
AURA = {"aura_id": "stunned-enemy-here", "amount": -8, "minimum": 1,
        "criteria": {"kind": "unit", "controller_relation": "enemy", "at_source_battlefield": True, "stunned": True}}
WATCHED = ("L", "e10", "e3", "e1", "eu", "ef", "fs")


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False, **extra}


def stun(state, object_id):
    """The engine's own stun instruction, so the status and its turn_effects entry are real."""
    program = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
               "program_id": f"stun-{object_id}", "controller": "p2",
               "effects": [{"op": "stun", "effect_id": "st", "object_id": object_id}]}
    result = IR.apply_program(state, program)
    if not result.get("committed"):
        raise SystemExit(f"the fixture could not stun {object_id}: {result.get('reason') or result.get('reason_code')}")
    return result["next_state"]


def board(aura=AURA):
    """p1's Leona-like L (4 Might) at bf1 with the aura; at bf1 p2's e10 (10), e3 (3), e1 (1), eu
    (5, not stunned), and p1's fs (2, stunned); p2's ef (6, stunned) at bf2. Every Unit that is
    Stunned was stunned by the engine."""
    state = base_state()
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["L", "fs", "e10", "e3", "e1", "eu"],
                                    "contested": True, "contested_by": "p2"}
    state["battlefields"]["bf2"] = {"controller": "p2", "objects": ["ef"]}
    state["objects"].update({"L": unit("p1", 4, static_auras=[copy.deepcopy(aura)]), "fs": unit("p1", 2),
                             "e10": unit("p2", 10), "e3": unit("p2", 3), "e1": unit("p2", 1), "eu": unit("p2", 5),
                             "ef": unit("p2", 6)})
    for object_id in ("fs", "e10", "e3", "e1", "ef"):
        state = stun(state, object_id)
    return state


def mights(state):
    return {o: IR.effective_might(state, o) for o in WATCHED}


EXPECTED = {"L": 4, "e10": 2, "e3": 1, "e1": 1, "eu": 5, "ef": 6, "fs": 2}
UNTOUCHED = {"L": 4, "e10": 10, "e3": 3, "e1": 1, "eu": 5, "ef": 6, "fs": 2}


def cases():
    """{label: (state, expected mights)} - each board built from scratch."""
    out = {"on_the_board": (board(), EXPECTED)}
    home = board()
    home["battlefields"]["bf1"]["objects"].remove("L")
    home["players"]["p1"]["zones"]["base"].append("L")
    out["source_in_its_base"] = (home, UNTOUCHED)
    gone = board()
    gone["battlefields"]["bf1"]["objects"].remove("L")
    gone["players"]["p1"]["zones"]["trash"].append("L")
    out["source_in_the_trash"] = (gone, {**UNTOUCHED, "L": 4})
    grown = board()
    for object_id in ("e10", "e3"):
        grown = IR.apply_program(grown, {
            "schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": f"grow-{object_id}", "controller": "p2",
            "effects": [{"op": "modify_might", "effect_id": "mm", "object_id": object_id, "amount": 2,
                         "duration": "this_turn", "source": "spell-grow"}]})["next_state"]
    out["plus_two_after_the_stun"] = (grown, {**EXPECTED, "e10": 4, "e3": 1})
    ended = board()
    ended["objects"] = {o: {k: v for k, v in obj.items() if k != "stunned"} for o, obj in ended["objects"].items()}
    ended["turn_effects"] = [e for e in ended.get("turn_effects", []) if e.get("kind") != "stunned_unit"]
    out["stun_expired"] = (ended, UNTOUCHED)
    return out


def main() -> int:
    errors: list[str] = []
    lowered = (CG.compile_clause(SENTENCE, CG.load_grammar()).get("passive") or {}).get("object_fields")
    if lowered != {"static_auras": [AURA]}:
        errors.append(f"the sentence lowered to {lowered}, not {AURA}")
    table = cases()
    for label, (state, want) in table.items():
        if found := IR.validate_state(state):
            errors.append(f"the {label} board is invalid: {found[:2]}")
            continue
        if (got := mights(state)) != want:
            errors.append(f"{label}: Might {got}, expected {want} (Core 365.1, 423.1.a, 477.3.b)")
    for label, bad in (("a floor on an increase", {**AURA, "amount": 2}),
                       ("a negative floor", {**AURA, "minimum": -1}),
                       ("a floor that is not an integer", {**AURA, "minimum": "1"}),
                       ("stunned: false", {**AURA, "criteria": {**AURA["criteria"], "stunned": False}})):
        broken = board()
        broken["objects"]["L"]["static_auras"] = [bad]
        if not IR.validate_state(broken):
            errors.append(f"an invalid aura validated: {label}")
    # mutations: an engine that ignores `stunned`, one that drops the floor - the table must see each
    real_applies, real_effects = IR._printed_aura_applies, IR.printed_aura_effects

    def ignores_stunned(state, criteria, object_id):
        return real_applies(state, {k: v for k, v in criteria.items() if k != "stunned"}, object_id)

    def drops_floor(state):
        out = real_effects(state)
        for effect in out:
            effect.get("value", {}).pop("minimum", None)
        return out

    for label, attribute, replacement in (("ignoring the stunned criterion", "_printed_aura_applies", ignores_stunned),
                                          ("dropping the floor", "printed_aura_effects", drops_floor)):
        setattr(IR, attribute, replacement)
        try:
            seen = [name for name, (state, want) in cases().items() if mights(state) != want]
        finally:
            IR._printed_aura_applies, IR.printed_aura_effects = real_applies, real_effects
        if not seen:
            errors.append(f"mutation not caught: an engine {label} passed every case")
    if errors:
        print("FAILED: stunned aura checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'Stunned enemy units here have -8 [M], to a minimum of 1 [M].' decreases exactly the Stunned enemy Units "
          "at its source's Battlefield, to the floor recomputed each time (477.3.b); not unstunned, friendly, elsewhere, "
          "or once the source left or the stun expired; invalid floors are refused; two engine mutations are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
