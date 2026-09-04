#!/usr/bin/env python3
"""
Gate for C-19 (ADR-0007 §1–3): permanent entry, play triggers, and the
open-Battlefield permission.

Must hold:
  - a Unit played to its Base resolves by the entry procedure: leaves the
    shared chain, new identity (Core 124), enters exhausted (143.4), no Move
    trigger, Cleanup afterwards; a Gear enters ready at the controller's
    Base (359.2.d); inputs untouched, deterministic;
  - entry_location is chosen at play (355.2): own Base and a controlled
    Battlefield are legal; an open Battlefield only with
    play_permissions open_battlefield (355.2.b); an occupied or opponent
    Battlefield is illegal; an unknown Battlefield is invalid_input; a Unit
    without a location is invalid_input; a spell with one is invalid_input;
  - entering a Battlefield the controller does not control records
    contested / contested_by and nothing else (190.3.a.1);
  - "When you play me" fires only on play completion (419.4.a): a play
    trigger becomes a Pending item in batch play:<item> after the entry, as
    trigger_kind triggered; two same-controller play triggers ask for a
    trigger_order decision; a unit merely placed on the board by a state
    edit raises nothing;
  - a permanent chain item resolves without a program; a spell still needs
    one; engine-check wraps the resolution as supported and the CLI runs
    off-cwd without a program file.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import hash_value, object_identity, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import complete_permanent_play, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, state_hash  # noqa: E402

RUNNER = SCRIPT_DIR / "engine_check.py"
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}


def unit_in_hand(*, permissions=None, triggers=None, kind="unit"):
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"]["kind"] = kind
    state["objects"]["c1"]["base_might"] = 2
    if permissions:
        state["objects"]["c1"]["play_permissions"] = list(permissions)
    if triggers:
        state["objects"]["c1"]["play_triggers"] = list(triggers)
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    return state


def declaration(location, kind="unit"):
    value = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
             "play_id": "play-1", "actor": "p1", "card": "c1",
             "chain_item": {"id": "unit-1", "object_kind": kind, "timing": "default"},
             "cost": {"base": {"energy": 2, "power": {}}}, "payment_context": dict(CLOSED)}
    if location is not None:
        value["entry_location"] = location
    return value


def resolution_timing(kind="unit"):
    return fixture(priority="p2", items=[item("unit-1", "p1", kind, "default", "finalized")], passes=["p1", "p2"])


def trigger(trigger_id, controller="p1", order=0):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": "c1", "controller_order": order,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False}


def main() -> int:
    errors: list[str] = []
    open_timing = fixture()

    # --- play to Base, then resolve by the entry procedure ---------------------------
    state = unit_in_hand()
    played = play_card(open_timing, state, declaration({"kind": "base"}))
    if not played.get("committed") or played["next_effect_state"]["chain_items"]["unit-1"].get("entry_location") != {"kind": "base"}:
        errors.append(f"unit play to Base did not commit with its entry_location on the chain: {played.get('reason')}")
        print("FAILED: permanent play checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors)); return 1
    on_chain = played["next_effect_state"]
    timing = resolution_timing()
    snap_t, snap_e = copy.deepcopy(timing), copy.deepcopy(on_chain)
    resolved = resolve_with_program(timing, "unit-1", on_chain, None)
    if not resolved.get("committed"):
        errors.append(f"unit resolution by the entry procedure did not commit: {resolved.get('stage')} {resolved.get('reason')}")
    else:
        nxt = resolved["next_effect_state"]
        entry = resolved["trace"]["chain_card"][0]
        if "chain_items" in nxt or "c1" not in nxt["players"]["p1"]["zones"]["base"] or object_identity(nxt, "c1") != "c1@2" or not nxt["objects"]["c1"]["exhausted"]:
            errors.append(f"unit did not enter its Base exhausted as a new object: {nxt['players']['p1']['zones']['base']} {object_identity(nxt, 'c1')} {nxt['objects']['c1'].get('exhausted')}")
        if entry.get("default_entry_state") != "exhausted" or entry.get("entry_state") != "exhausted" or entry.get("not_a_move") is not True or "Core 359.2.c" not in entry.get("rule_locators", []):
            errors.append(f"entry trace incomplete: {entry}")
        if resolved["next_timing_state"]["chain"]["items"]:
            errors.append("a unit with no play triggers scheduled a chain item")
        if validate_state(nxt):
            errors.append(f"state after entry invalid: {validate_state(nxt)}")
    if timing != snap_t or on_chain != snap_e or resolve_with_program(timing, "unit-1", on_chain, None) != resolved:
        errors.append("entry procedure mutated inputs or is not deterministic")
    # a spell still needs a program
    spell_state = unit_in_hand(kind="spell")
    spell_play = play_card(open_timing, spell_state, declaration(None, kind="spell") | {"chain_item": {"id": "unit-1", "object_kind": "spell", "timing": "default"}})
    if spell_play.get("committed"):
        no_prog = resolve_with_program(resolution_timing("spell"), "unit-1", spell_play["next_effect_state"], None)
        if no_prog.get("committed") or no_prog.get("reason") != "effect_program_required":
            errors.append("a spell resolved without a program")

    # --- Gear enters ready at the Base -----------------------------------------------
    gear = unit_in_hand(kind="gear")
    gplay = play_card(open_timing, gear, declaration(None, kind="gear"))
    gres = resolve_with_program(resolution_timing("gear"), "unit-1", gplay["next_effect_state"], None) if gplay.get("committed") else {}
    if not gres.get("committed") or gres["next_effect_state"]["objects"]["c1"]["exhausted"] or "c1" not in gres["next_effect_state"]["players"]["p1"]["zones"]["base"]:
        errors.append(f"gear did not enter ready at the Base: {gplay.get('reason')} {gres.get('reason')}")
    if play_card(open_timing, unit_in_hand(kind="gear"), declaration({"kind": "battlefield", "battlefield": "bf1"}, kind="gear")).get("valid") is not False:
        errors.append("gear declared to a battlefield was not invalid_input (359.2.d)")

    # --- entry_location legality at play (355.2) ---------------------------------------
    if play_card(open_timing, unit_in_hand(), declaration(None)).get("valid") is not False:
        errors.append("a Unit without entry_location was accepted")
    if play_card(open_timing, unit_in_hand(kind="spell"), declaration({"kind": "base"}, kind="spell")).get("valid") is not False:
        errors.append("a spell with an entry_location was accepted")
    unknown = play_card(open_timing, unit_in_hand(), declaration({"kind": "battlefield", "battlefield": "bf9"}))
    if unknown.get("valid") is not False or unknown.get("reason_code") != "invalid_input":
        errors.append("an unknown battlefield was not invalid_input")
    open_no_perm = play_card(open_timing, unit_in_hand(), declaration({"kind": "battlefield", "battlefield": "bf1"}))
    if open_no_perm.get("valid") is not True or open_no_perm.get("committed") or open_no_perm.get("reason_code") != "entry_location_illegal":
        errors.append(f"an open battlefield without permission was not illegal: {open_no_perm.get('reason_code')}")
    open_perm = play_card(open_timing, unit_in_hand(permissions=["open_battlefield"]), declaration({"kind": "battlefield", "battlefield": "bf1"}))
    if not open_perm.get("committed"):
        errors.append(f"open battlefield with permission was refused: {open_perm.get('reason')}")
    else:
        res = resolve_with_program(resolution_timing(), "unit-1", open_perm["next_effect_state"], None)
        bf = res.get("next_effect_state", {}).get("battlefields", {}).get("bf1", {})
        if not res.get("committed") or "c1" not in bf.get("objects", []) or bf.get("contested") is not True or bf.get("contested_by") != "p1" or bf.get("controller") is not None:
            errors.append(f"entering an open battlefield did not record contested_by without transferring control: {bf} {res.get('reason')}")
    occupied = unit_in_hand(permissions=["open_battlefield"]); occupied["players"]["p2"]["zones"]["base"].remove("u2"); occupied["battlefields"]["bf1"]["objects"].append("u2")
    if play_card(open_timing, occupied, declaration({"kind": "battlefield", "battlefield": "bf1"})).get("reason_code") != "entry_location_illegal":
        errors.append("an occupied battlefield was accepted as open")
    controlled = unit_in_hand(); controlled["battlefields"]["bf1"]["controller"] = "p1"
    ctrl_play = play_card(open_timing, controlled, declaration({"kind": "battlefield", "battlefield": "bf1"}))
    if not ctrl_play.get("committed"):
        errors.append(f"a controlled battlefield was refused: {ctrl_play.get('reason')}")
    else:
        res = resolve_with_program(resolution_timing(), "unit-1", ctrl_play["next_effect_state"], None)
        if res.get("committed") and res["next_effect_state"]["battlefields"]["bf1"].get("contested"):
            errors.append("entering an own-controlled battlefield was marked contested")
    theirs = unit_in_hand(permissions=["open_battlefield"]); theirs["battlefields"]["bf1"]["controller"] = "p2"
    if play_card(open_timing, theirs, declaration({"kind": "battlefield", "battlefield": "bf1"})).get("reason_code") != "entry_location_illegal":
        errors.append("an opponent-controlled battlefield was accepted")

    # --- play triggers fire on play completion only (419.4.a) ------------------------------
    with_trigger = unit_in_hand(triggers=[trigger("c1-on-play")])
    tplay = play_card(open_timing, with_trigger, declaration({"kind": "base"}))
    tres = resolve_with_program(resolution_timing(), "unit-1", tplay["next_effect_state"], None) if tplay.get("committed") else {}
    items = tres.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not tres.get("committed") or [i["id"] for i in items] != ["c1-on-play"] or items[0].get("status") != "pending" or items[0].get("trigger_kind") != "triggered" or items[0].get("batch_id") != "play:unit-1":
        errors.append(f"play trigger was not scheduled on play completion: {tres.get('reason')} {[(i.get('id'), i.get('batch_id')) for i in items]}")
    if tres.get("committed") and tres["trace"]["chain_card"][0].get("play_triggers") != ["c1-on-play"]:
        errors.append("entry trace does not list the play trigger")
    two = unit_in_hand(triggers=[trigger("c1-a"), trigger("c1-b")])
    tplay2 = play_card(open_timing, two, declaration({"kind": "base"}))
    ask = resolve_with_program(resolution_timing(), "unit-1", tplay2["next_effect_state"], None) if tplay2.get("committed") else {}
    if ask.get("committed") or ask.get("reason_code") != "trigger_order_required" or sorted(ask.get("trigger_ids", [])) != ["c1-a", "c1-b"]:
        errors.append(f"two same-controller play triggers did not ask for a trigger_order decision: {ask.get('reason_code')}")
    # mere placement is not a play: a unit edited onto the board raises nothing
    placed = base_state(); placed["objects"]["u1"]["play_triggers"] = [trigger("u1-on-play") | {"source_object": "u1"}]
    if validate_state(placed):
        errors.append(f"play_triggers on a board unit rejected: {validate_state(placed)}")
    else:
        deal = {"schema_version": "riftbound-effect-program.v1", "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "program_id": "spell-1-effects", "controller": "p1",
                "effects": [{"op": "deal_damage", "object_id": "u2", "amount": 1}]}
        spell_timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
        quiet = resolve_with_program(spell_timing, "spell-1", placed, deal)
        if not quiet.get("committed") or quiet["next_timing_state"]["chain"]["items"]:
            errors.append("a play trigger fired without a play completing")
    # the procedure itself refuses a unit with no location and a gear aimed elsewhere
    broken = copy.deepcopy(on_chain); del broken["chain_items"]["unit-1"]["entry_location"]
    _, err_trace, _ = complete_permanent_play(broken, "unit-1")
    if not err_trace.get("error"):
        errors.append("entry procedure accepted a unit chain entry without entry_location")

    # --- engine-check and CLI --------------------------------------------------------------
    check = build_engine_check("resolution", resolved, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(on_chain)})
    if check["outcome"] != "supported" or "permanent_entry" not in check["coverage"]["supported_scope"] or "Core 359.2.c" not in check["rule_locators"]:
        errors.append(f"engine-check did not wrap the entry as supported with its scope: {check['outcome']}")
    with tempfile.TemporaryDirectory(prefix="permanent-play-") as temp_name:
        temp = Path(temp_name)
        (temp / "t.json").write_text(json.dumps(timing), encoding="utf-8")
        (temp / "e.json").write_text(json.dumps(on_chain), encoding="utf-8")
        run = subprocess.run([sys.executable, str(RUNNER), "resolution", str(temp / "t.json"), "unit-1", str(temp / "e.json"), "--output", str(temp / "o.json")], cwd=temp, text=True, capture_output=True, check=False)
        if run.returncode != 0 or json.loads((temp / "o.json").read_text(encoding="utf-8"))["outcome"] != "supported":
            errors.append(f"CLI resolution without a program failed off-cwd: {run.stderr.strip()}")

    if errors:
        print("FAILED: permanent play checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: permanents leave the shared chain by the entry procedure as new objects (Units exhausted at the location chosen at play, Gear ready at the Base); the location is legal at play only as own Base, a controlled Battlefield, or an open one with permission, and an unknown one is invalid_input; entering an uncontrolled Battlefield records contested_by without transferring control; play triggers fire only on play completion as one batch and same-controller collisions ask; a spell still needs a program; engine-check and the CLI agree off-cwd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
