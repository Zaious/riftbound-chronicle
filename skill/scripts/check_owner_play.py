#!/usr/bin/env python3
"""A banished card played by its owner, to their Base (package 9, Portal Rescue).

"Banish a friendly unit, then its owner plays it to their base, ignoring its cost." GPT 2026-10-06 (PACKAGE9_INVENTORY
section 7, ruling 2): the owner plays it to their own Base and controls it (Core 127.1, 419.1); ignoring its cost is the
base cost's Energy and Power set to zero (356.1.b.1), not an additional cost (356.1.b.3).

The engine's shape: limited_play `linked` {effect_id, from: banishment} with player "owner" (only on a linked play) and
entry {kind: unit_at_players_base} - the record names {kind: base}, the Base of the player who plays it (355.2.b).

  O1 own unit      p1's own unit banished and played by p1 to p1's Base: a new object, p1 controls it, nothing paid
                   for its printed [3][Fury] (the receipt's base modifications zero both)
  O2 another's     a unit p1 controls and p2 owns: banished to P2's Banishment, the Pending play is p2's, it enters
                   P2's Base under p2's control; p1's and p2's resources unchanged
  O3 not elsewhere a Battlefield supplied as the entry location is refused (the effect named the Base); the Base is
                   not asked for
  O4 as before     the same play without `player` is the program controller's, as in package 8 (p1 plays p2's card)
  S  shapes        player on a target play, player "controller", entry {kind: base}, an unknown entry kind - refused

    python skill/scripts/check_owner_play.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, object_identity, validate_program, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import complete_limited_play, resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def portal(unit: str, *, owner_plays: bool = True, entry: dict | None = None) -> dict:
    play = {"op": "limited_play", "effect_id": "lp", "linked": {"effect_id": "ban", "from": "banishment"},
            "entry": entry or {"kind": "unit_at_players_base"}, "cost_basis": {"kind": "ignore_all"}}
    if owner_plays:
        play["player"] = "owner"
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "portal-effects", "controller": "p1",
            "source_object": "portal", "effects": [{"op": "banish", "effect_id": "ban", "object_id": unit}, play]}


def board(owner: str) -> dict:
    """p1's [1] spell in hand; u9 - owned by `owner`, controlled by p1, printed [3][Fury] - in p1's Base."""
    state = base_state()
    state["objects"]["portal"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0,
                                  "might_modifiers": [], "damage": 0, "exhausted": False,
                                  "printed_cost": {"energy": 1, "power": {}}}
    state["players"]["p1"]["zones"].setdefault("hand", []).append("portal")
    state["objects"]["u9"] = {"owner": owner, "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                              "damage": 1, "exhausted": True, "printed_cost": {"energy": 3, "power": {"fury": 1}}}
    state["players"]["p1"]["zones"]["base"].append("u9")
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    state["players"]["p2"]["resources"] = {"energy": 0, "power": {}}
    problems = validate_state(state)
    assert not problems, problems
    return state


def resolve(state: dict, prog: dict) -> dict:
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-portal", "actor": "p1",
            "card": "portal", "effect_program_id": prog["program_id"],
            "chain_item": {"id": "spell-portal", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "payment_context": CLOSED}
    played = play_card(fixture(), state, decl, effect_program=prog)
    assert played.get("committed"), (played.get("reason_code"), played.get("reason"))
    timing = played["next_timing_state"]
    if next_procedure(timing).get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, "spell-portal", played["next_effect_state"], prog)


def limited(done: dict) -> tuple[dict, dict]:
    timing = done["next_timing_state"]
    item = next((i for i in timing["chain"]["items"] if i.get("limited_play")), None) or {}
    record = ((done["next_effect_state"].get("chain_items") or {}).get(item.get("id")) or {}).get("limited_play") or {}
    return item, record


def check_own() -> None:
    state = board("p1")
    before = object_identity(state, "u9")
    done = resolve(state, portal("u9"))
    if not done.get("committed"):
        return fail("O1 own unit", f"{done.get('stage')} {done.get('reason')}")
    item, record = limited(done)
    if item.get("controller") != "p1" or record.get("entry_location") != {"kind": "base"} \
            or record.get("source_zone") != "banishment" or record.get("zone_owner") != "p1":
        return fail("O1 own unit", f"the Pending play is not p1's, from p1's Banishment, to the Base: {item} {record}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
    after = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "u9" not in after["players"]["p1"]["zones"]["base"]:
        return fail("O1 played", f"{completed.get('reason')} {completed.get('message')}")
    u9 = after["objects"]["u9"]
    if u9["controller"] != "p1" or u9["owner"] != "p1" or object_identity(after, "u9") == before or u9.get("damage"):
        fail("O1 new object", f"not a new p1 object in p1's Base: {u9} {object_identity(after, 'u9')}")
    if after["players"]["p1"]["resources"] != {"energy": 0, "power": {}}:
        fail("O1 nothing paid", f"its [3][Fury] was paid: {after['players']['p1']['resources']}")
    modified = (completed.get("cost_receipt") or {}).get("after_base_modifications")
    if modified not in ({"energy": 0, "power": {}}, {"energy": 0, "power": {"fury": 0}}):
        fail("O1 ignore_all", f"the base cost is not set to zero (356.1.b.1): {modified}")


def check_another() -> None:
    state = board("p2")
    done = resolve(state, portal("u9"))
    if not done.get("committed"):
        return fail("O2 another's", f"{done.get('stage')} {done.get('reason')}")
    item, record = limited(done)
    if item.get("controller") != "p2" or record.get("zone_owner") != "p2" or record.get("controller_before") != "p1":
        return fail("O2 owner plays", f"the Pending play is not p2's from p2's Banishment: {item} {record}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
    after = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "u9" not in after["players"]["p2"]["zones"]["base"] \
            or "u9" in after["players"]["p1"]["zones"]["base"]:
        return fail("O2 their base", f"not in p2's Base: {completed.get('reason')} {completed.get('message')}")
    if after["objects"]["u9"]["controller"] != "p2" or after["objects"]["u9"]["owner"] != "p2":
        fail("O2 controls", f"p2 plays it and controls it: {after['objects']['u9']}")
    if after["players"]["p1"]["resources"] != {"energy": 0, "power": {}} or after["players"]["p2"]["resources"] != {"energy": 0, "power": {}}:
        fail("O2 nothing paid", f"{after['players']['p1']['resources']} {after['players']['p2']['resources']}")
    # O3: the effect named the Base; a Battlefield is refused, and nothing changes
    refused = complete_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED,
                                    entry_location={"kind": "battlefield", "battlefield": "bf1"})
    if refused.get("committed") or refused.get("reason") != "entry_location_named_by_the_effect":
        fail("O3 not elsewhere", f"a Battlefield was accepted: {refused.get('committed')} {refused.get('reason')}")


def check_as_before() -> None:
    state = board("p2")
    done = resolve(state, portal("u9", owner_plays=False))
    if not done.get("committed"):
        return fail("O4 as before", f"{done.get('stage')} {done.get('reason')}")
    item, record = limited(done)
    if item.get("controller") != "p1" or record.get("zone_owner") != "p2":
        fail("O4 as before", f"without player the program's controller plays it: {item} {record}")


def check_shapes() -> None:
    good = portal("u9")
    if validate_program(good):
        fail("S shapes", f"the Portal Rescue shape is refused: {validate_program(good)}")
    target_play = {"op": "limited_play", "effect_id": "lp", "player": "owner", "cost_basis": {"kind": "ignore_all"},
                   "target": {"decision_ref": "t", "chosen_zone_class": "non_board", "kind": "unit", "location": "trash",
                              "zone_owner_relation": "own"}}
    cases = {"player on a target play": {**good, "effects": [target_play]},
             "player controller": {**good, "effects": [good["effects"][0], {**good["effects"][1], "player": "controller"}]},
             "entry base": {**good, "effects": [good["effects"][0], {**good["effects"][1], "entry": {"kind": "base"}}]},
             "unknown entry": {**good, "effects": [good["effects"][0], {**good["effects"][1], "entry": {"kind": "players_battlefield"}}]}}
    for label, prog in cases.items():
        if not validate_program(prog):
            fail("S shapes", f"{label} was accepted")


def main() -> int:
    check_own()
    check_another()
    check_as_before()
    check_shapes()
    if errors:
        print("FAILED: owner play checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a banished card is played by its owner to their Base, ignoring its base cost (O1-O4, S)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
