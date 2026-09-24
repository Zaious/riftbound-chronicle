#!/usr/bin/env python3
"""
Regression gate: a token a card program cannot name (2026-09-24).

A card program resolves once per copy and per replay, so it cannot carry a literal token
object_id - the second resolution was refused ("play_token requires a new unique
object_id"). `object_id_ref {kind: fresh}` has the engine mint the id at execution (Core
124: every token is a new object), deterministically from the state. And "here" as where a
token enters is the program source's current Battlefield, read at execution (Core
359.3.f.1, 359.3.f.2) through the same resolver as a target's location_ref.

Must hold:
  - two fresh tokens in one program get two ids; the same program run again on the result
    mints two more, and nothing collides; each object carries its token_id;
  - a literal object_id still works exactly as before;
  - "here" plays the token at the source's Battlefield; a source in its Base plays no token
    (no_op, location_ref_source_not_at_battlefield); a source whose identity changed plays
    none either;
  - invalid: an object_id_ref other than {kind: fresh}; both object_id and object_id_ref;
    a location_ref destination that also names a Battlefield, or is not a Battlefield.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, object_identity, validate_program  # noqa: E402

RECRUIT = {"op": "play_token", "owner": "p1", "controller": "p1", "token_kind": "unit", "base_might": 1,
           "token_id": "recruit"}


def fresh(effect_id, destination):
    return {**RECRUIT, "effect_id": effect_id, "object_id_ref": {"kind": "fresh"}, "destination": destination}


def tokens(state):
    return sorted(o for o, obj in state["objects"].items() if obj.get("is_token"))


def main() -> int:
    errors: list[str] = []
    base = {"kind": "base", "player": "p1"}

    # --- fresh ids, twice -------------------------------------------------------------------
    two = program("two-recruits", fresh("a", base), fresh("b", base))
    first = apply_program(base_state(), two)
    if not first.get("committed") or tokens(first["next_state"]) != ["token:recruit:1", "token:recruit:2"]:
        errors.append(f"two fresh tokens did not get two ids: {first.get('reason') or first.get('errors')} "
                      f"{tokens(first.get('next_state') or base_state())}")
    else:
        again = apply_program(first["next_state"], two)
        if not again.get("committed") or tokens(again["next_state"]) != [f"token:recruit:{n}" for n in (1, 2, 3, 4)]:
            errors.append(f"the same program run again collided or did not mint: {again.get('reason') or again.get('errors')}")
        if any(again.get("next_state", {}).get("objects", {}).get(t, {}).get("token_id") != "recruit"
               for t in tokens(again.get("next_state") or {"objects": {}})):
            errors.append("a minted token does not carry its token_id")
    literal = apply_program(base_state(), program("literal", {**RECRUIT, "effect_id": "a", "object_id": "t1", "destination": base}))
    if not literal.get("committed") or "t1" not in literal["next_state"]["objects"]:
        errors.append(f"a literal token object_id no longer works: {literal.get('reason') or literal.get('errors')}")

    # --- "here" --------------------------------------------------------------------------------
    here = {"kind": "battlefield", "location_ref": {"kind": "program_source_current_battlefield"}}
    at_bf = base_state()
    at_bf["players"]["p1"]["zones"]["base"].remove("u1")
    at_bf["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"]}
    sourced = {**program("here", fresh("a", here)), "source_object": "u1", "source_identity": object_identity(at_bf, "u1") or "u1@0"}
    played = apply_program(at_bf, sourced)
    minted = tokens(played.get("next_state") or {"objects": {}})
    if not played.get("committed") or not minted or minted[0] not in played["next_state"]["battlefields"]["bf1"]["objects"]:
        errors.append(f"'here' did not play the token at the source's battlefield: {played.get('reason') or played.get('errors')}")
    in_base = {**program("here-base", fresh("a", here)), "source_object": "u1", "source_identity": object_identity(base_state(), "u1") or "u1@0"}
    none = apply_program(base_state(), in_base)
    step = (none.get("trace") or [{}])[0]
    if not none.get("committed") or tokens(none["next_state"]) or step.get("outcome") != "no_op" \
            or step.get("reason") != "location_ref_source_not_at_battlefield":
        errors.append(f"a source in its Base played a token 'here': {step}")
    moved = {**sourced, "source_identity": "u1@99"}
    stale = apply_program(at_bf, moved)
    if tokens(stale.get("next_state") or {"objects": {}}) or (stale.get("trace") or [{}])[0].get("outcome") != "no_op":
        errors.append(f"a source whose identity changed still played a token 'here': {(stale.get('trace') or [{}])[0]}")

    # --- invalid --------------------------------------------------------------------------------
    for label, effect in (
            ("an object_id_ref other than fresh", {**fresh("a", base), "object_id_ref": {"kind": "named"}}),
            ("both object_id and object_id_ref", {**fresh("a", base), "object_id": "t1"}),
            ("a location_ref that also names a battlefield", fresh("a", {**here, "battlefield": "bf1"})),
            ("a location_ref into a base", fresh("a", {"kind": "base", "player": "p1", "location_ref": here["location_ref"]}))):
        if not validate_program(program("bad", effect)):
            errors.append(f"{label} validated")

    if errors:
        print("FAILED: token minting checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: fresh token ids are minted at execution and never collide on a second resolution, each token carries "
          "its token_id, a literal id still works, 'here' plays at the source's Battlefield and plays nothing from a "
          "Base or after the source changed, and four malformed programs are refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
