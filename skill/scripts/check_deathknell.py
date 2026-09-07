#!/usr/bin/env python3
"""Regression gate for Deathknell (Round H, DP-89; Core 808).

Codex's ruling: Deathknell has to be shown bound to the engine's real death
event, identity and timing — not parsed into a label that happens to sit on an
object. The rule, in its own words:

    808.1  "Deathknell is a Triggered Ability keyword… formatted as
            '[Deathknell][>] [Effect]'."
    808.2  "It is functionally short for 'When I die, [Effect].'"
    808.3  "Each instance of Deathknell a Permanent may have will trigger
            separately. The controller will choose the order…"
           "Deathknell… is a characteristic of the permanent and may be checked
            or referenced by other Game Effects."
    323 step 3a  the ability is added as a Pending Item, noting the card's
            location and attributes, **before** step 3b moves it to the Trash.

Must hold:
  - a permanent that carries the keyword and dies schedules its death trigger,
    and the scheduled trigger is marked as a Deathknell instance;
  - the ability is noted *before* the card reaches the Trash: the trigger
    exists in the same result that moved the card, and the trigger's source
    identity is the one the card had while it lived (Core 124);
  - **negative mutation**: the same object without the keyword still schedules
    its death trigger — 323 step 3a covers "other abilities that trigger on
    their own death" — but it is not marked as Deathknell. So the marking
    tracks the keyword, and the keyword is not what makes a death trigger fire;
  - each instance triggers separately (808.3): two Deathknell abilities on one
    permanent give two scheduled triggers, not one;
  - it is a characteristic other effects can check (`has_keyword`), and one
    granted by a continuous effect counts as much as a printed one;
  - the catalogue's production for it is the path this gate exercises.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import keyword_catalog  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import (  # noqa: E402
    apply_program,
    deathknell_instances,
    has_keyword,
    object_identity,
    perform_lethal_cleanup,
)


def trigger(trigger_id, source="u1", controller="p1"):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False}


def dying_state(*, keyword=True, triggers=("dk-1",)):
    state = base_state()
    state["objects"]["u1"]["death_triggers"] = [trigger(t) for t in triggers]
    if keyword:
        state["objects"]["u1"]["keywords"] = ["deathknell"]
    return state


def main() -> int:
    errors: list[str] = []

    state = dying_state()
    identity_alive = object_identity(state, "u1")
    if not has_keyword(state, "u1", "deathknell"):
        errors.append("a printed Deathknell is not a characteristic the engine can check (808, last paragraph)")
    if [t["trigger_id"] for t in deathknell_instances(state, "u1")] != ["dk-1"]:
        errors.append(f"the Deathknell instances were not read off the object: {deathknell_instances(state, 'u1')}")

    killed = apply_program(state, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    if not killed.get("committed"):
        print("FAILED: Deathknell checks")
        print(f"  - the kill fixture did not commit: {killed.get('reason_code')} {killed.get('reason')}")
        return 1
    scheduled = killed.get("pending_triggers", [])
    if [t["trigger_id"] for t in scheduled] != ["dk-1"]:
        errors.append(f"dying did not schedule the Deathknell ability: {scheduled}")
    elif scheduled[0].get("deathknell") is not True:
        errors.append(f"the scheduled trigger was not marked a Deathknell instance: {scheduled[0]}")

    # --- noted before the card reaches the Trash (323 step 3a) -----------------------------------
    after = killed["next_state"]
    if "u1" not in after["players"]["p1"]["zones"]["trash"]:
        errors.append("the killed card did not reach the Trash at all")
    if not scheduled:
        errors.append("the ability was not noted in the same result that moved the card (323 step 3a)")
    if object_identity(after, "u1") == identity_alive:
        errors.append("the card kept its identity through death (Core 124)")
    if scheduled and scheduled[0].get("source_object") != "u1":
        errors.append(f"the scheduled trigger lost its source: {scheduled[0]}")
    # The ability was read from the state *before* the card moved: the same
    # kill run on a state whose death triggers were stripped schedules nothing,
    # so the collection is not a post-hoc read of wherever the card ended up.
    stripped = dying_state()
    del stripped["objects"]["u1"]["death_triggers"]
    if apply_program(stripped, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"})).get("pending_triggers"):
        errors.append("a permanent with no death trigger still scheduled one")
    dead_again = apply_program(after, program("k2", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    if dead_again.get("committed"):
        errors.append("a card already in the Trash could be killed again, so Deathknell could fire twice")

    # --- negative mutation: the marking tracks the keyword, the trigger does not ------------------
    bare = dying_state(keyword=False)
    bare_killed = apply_program(bare, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    bare_scheduled = bare_killed.get("pending_triggers", [])
    if [t["trigger_id"] for t in bare_scheduled] != ["dk-1"]:
        errors.append("removing the keyword stopped a plain death trigger from firing; 323 step 3a covers those too")
    elif bare_scheduled[0].get("deathknell") is not False:
        errors.append(f"a death trigger with no Deathknell keyword was still marked as one: {bare_scheduled[0]}")
    if deathknell_instances(bare, "u1"):
        errors.append("an object without the keyword reported Deathknell instances")

    # --- each instance triggers separately (808.3) -------------------------------------------------
    twice = dying_state(triggers=("dk-1", "dk-2"))
    both = apply_program(twice, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    marked = [t["trigger_id"] for t in both.get("pending_triggers", []) if t.get("deathknell")]
    if marked != ["dk-1", "dk-2"]:
        errors.append(f"two Deathknell instances did not each trigger (808.3): {marked}")
    if len({t["controller_order"] for t in both.get("pending_triggers", [])}) != 1:
        errors.append("the engine imposed an order the controller is supposed to choose (808.3)")

    # --- a granted Deathknell counts as much as a printed one --------------------------------------
    granted = dying_state(keyword=False)
    granted["objects"]["u1"]["continuous_effects"] = []
    granted.setdefault("continuous_effects", []).append({
        "effect_id": "grant-dk", "kind": "keyword_grant", "source": {"object": "u2", "identity": None},
        "affects": {"scope": "object", "object": "u1", "identity": None}, "layer": "ability", "timestamp": 1,
        "value": {"keyword": "deathknell"}, "duration": {"kind": "permanent"},
    })
    if not has_keyword(granted, "u1", "deathknell"):
        errors.append("a granted Deathknell is not visible as a characteristic (808, last paragraph)")
    granted_killed = apply_program(granted, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    if not granted_killed.get("committed"):
        errors.append(f"the granted fixture did not commit: {granted_killed.get('reason')}")
    elif not all(t.get("deathknell") for t in granted_killed.get("pending_triggers", [])):
        errors.append("a granted Deathknell did not mark the instance")

    # --- the same holds through the Cleanup, which is where deaths usually happen -------------------
    lethal = dying_state()
    lethal["objects"]["u1"]["damage"] = 9
    cleanup = perform_lethal_cleanup(lethal)
    if not cleanup.get("committed"):
        errors.append(f"the lethal Cleanup did not commit: {cleanup.get('reason_code')}")
    else:
        cleanup_triggers = [t for t in cleanup.get("pending_triggers", []) if t["trigger_id"] == "dk-1"]
        if not cleanup_triggers:
            errors.append("a Deathknell permanent dying in Cleanup did not schedule its ability")
        elif cleanup_triggers[0].get("deathknell") is not True:
            errors.append(f"the Cleanup's scheduled trigger was not marked a Deathknell instance: {cleanup_triggers[0]}")

    # --- the catalogue points at the path this gate exercises ---------------------------------------
    catalog = keyword_catalog.load_catalog()
    supported, where = keyword_catalog.keyword_supported(catalog, "deathknell")
    if not supported or where != "effect_ir.deathknell_instances":
        errors.append(f"the catalogue does not name the production this gate exercises: {where}")
    if keyword_catalog.verify(catalog):
        errors.append(f"the catalogue does not verify against the engine: {keyword_catalog.verify(catalog)[:2]}")

    if errors:
        print("FAILED: Deathknell checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("Deathknell checks passed: bound to the real death event, noted before the Trash, each instance separate, "
          "granted counts, and the marking tracks the keyword rather than the trigger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
