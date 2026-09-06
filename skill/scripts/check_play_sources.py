#!/usr/bin/env python3
"""
Regression gate for C-44 (ADR-0012 §1–2; Codex G-1 on DP-69 / DP-65): typed
play sources, cost overrides, Ambush as a play permission, and Unique as the
deck-construction characteristic it is.

Must hold:
  - the default source is still the hand and nothing about it changed; a
    Champion Zone source plays as normal (108.3.e) and the card leaves that
    zone, not the hand; a trash source without a granted permission is
    illegal: play_source_not_permitted, and the same play with the permission
    commits (negative mutation); a card that is not in the named zone is
    illegal: card_not_in_source;
  - cost_override ignore_base_cost zeroes the base before Core 356 runs — the
    receipt shows after_base_modifications at zero and total zero, and the
    play needs no Add window; for_cost replaces it; the receipt names the
    override's source;
  - Ambush lets a Unit enter a Battlefield its controller does not control
    when they have a Unit there, and refuses it when they do not; the same
    card without the ambush permission is refused at the same Battlefield
    (negative mutation); timing_source ambush at a Battlefield without a
    friendly Unit is ambush_location_invalid; the trace records the
    derivation;
  - Unique is recorded and never restricts a play: a second copy of a card
    marked unique commits; the state validator accepts the flag and refuses a
    non-boolean;
  - the Legend and Champion zones are optional player zones the validator
    accepts, an unknown zone is refused, and a legend zone is not a play
    source;
  - the play scope declares play_sources, cost_override and ambush and keeps
    deck_construction unsupported; determinism.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_costs_and_activation import declaration, hand_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import hash_value, object_identity, validate_state  # noqa: E402
from engine_check import KIND_CONFIG, build_engine_check  # noqa: E402
from play_transaction import play_card, validate_declaration  # noqa: E402


def with_zone(state, zone, *cards):
    """Move `cards` into an optional player zone of p1."""
    state = copy.deepcopy(state)
    zones = state["players"]["p1"]["zones"]
    zones.setdefault(zone, [])
    for card in cards:
        for name, ids in zones.items():
            if card in ids:
                ids.remove(card)
        zones[zone].append(card)
    return state


def main() -> int:
    errors: list[str] = []
    timing = fixture()
    base = hand_state("c1")

    # --- sources ------------------------------------------------------------------------------
    from_hand = play_card(timing, base, declaration())
    if not from_hand.get("committed") or from_hand["next_effect_state"]["players"]["p1"]["zones"]["hand"] != []:
        errors.append(f"the default hand source broke: {from_hand.get('reason_code')} {from_hand.get('reason')}")
    champion = with_zone(base, "champion_zone", "c1")
    if validate_state(champion):
        errors.append(f"a state with a Champion Zone is invalid: {validate_state(champion)}")
    from_champion = play_card(timing, champion, declaration(source={"kind": "champion_zone"}))
    if not from_champion.get("committed") or from_champion["next_effect_state"]["players"]["p1"]["zones"]["champion_zone"] != []:
        errors.append(f"the Champion Zone did not play as normal: {from_champion.get('reason_code')} {from_champion.get('reason')}")
    elif from_champion["trace"][0].get("source") != "champion_zone":
        errors.append(f"the trace does not record the source: {from_champion['trace'][0].get('source')}")
    trash = copy.deepcopy(base)
    trash["players"]["p1"]["zones"]["hand"] = []
    trash["players"]["p1"]["zones"]["trash"] = ["c3", "c1"]
    unpermitted = play_card(timing, trash, declaration(source={"kind": "trash"}))
    if unpermitted.get("committed") or unpermitted.get("reason_code") != "play_source_not_permitted":
        errors.append(f"playing from the trash without a permission was accepted: {unpermitted.get('reason_code')} {unpermitted.get('reason')}")
    permitted = play_card(timing, trash, declaration(source={"kind": "trash"}, source_permission={"granted_by": "kennen-flow"}))
    if not permitted.get("committed") or "c1" not in permitted["next_effect_state"]["chain_items"]["spell-1"].values():
        errors.append(f"negative mutation failed: the same play with a granted permission did not commit: {permitted.get('reason_code')} {permitted.get('reason')}")
    elif permitted["next_effect_state"]["players"]["p1"]["zones"]["trash"] != ["c3"]:
        errors.append("the card did not leave the trash it was played from")
    wrong_zone = play_card(timing, base, declaration(source={"kind": "trash"}, source_permission={"granted_by": "x"}))
    if wrong_zone.get("reason_code") != "card_not_in_source":
        errors.append(f"a card that is not in the named source was accepted: {wrong_zone.get('reason_code')}")
    bad_source = validate_declaration(declaration(source={"kind": "legend_zone"}))
    if not any("source.kind" in e for e in bad_source):
        errors.append("the Legend Zone was accepted as a play source (Core 107.4.d: a Legend never leaves it)")

    # --- cost overrides -----------------------------------------------------------------------------
    poor = hand_state("c1", energy=0)
    free = play_card(timing, poor, declaration(cost={"base": {"energy": 2, "power": {}}}, cost_override={"kind": "ignore_base_cost", "source": "hidden"}, payment_context=None))
    if not free.get("committed"):
        errors.append(f"ignoring the base cost did not make the play free: {free.get('reason_code')} {free.get('reason')}")
    else:
        receipt = free["cost_receipt"]
        if receipt["after_base_modifications"] != {"energy": 0, "power": {}} or receipt["total"]["energy"] != 0:
            errors.append(f"the receipt does not show the base cost ignored: {receipt['after_base_modifications']} {receipt['total']}")
        if not any(r.get("source") == "hidden" for c in receipt["components"] for r in c.get("reductions", [])) and receipt["base"] != {"energy": 2, "power": {}}:
            errors.append("the receipt lost the original base cost")
        if free["trace"][0].get("cost_override", {}).get("kind") != "ignore_base_cost":
            errors.append("the choices trace does not record the override")
    for_cost = play_card(timing, hand_state("c1", energy=1), declaration(cost={"base": {"energy": 3, "power": {"fury": 1}}}, cost_override={"kind": "for_cost", "cost": {"energy": 1, "power": {}}, "source": "flow"}))
    if not for_cost.get("committed") or for_cost["cost_receipt"]["total"] != {"energy": 1, "power": {}}:
        errors.append(f"a for_cost override did not replace the base cost: {for_cost.get('reason_code')} {for_cost.get('reason')}")
    if not any("ignore_base_cost carries no cost" in e for e in validate_declaration(declaration(cost_override={"kind": "ignore_base_cost", "cost": {"energy": 0, "power": {}}, "source": "x"}))):
        errors.append("an ignore_base_cost override carrying a cost was accepted")

    # --- Ambush --------------------------------------------------------------------------------------
    board = hand_state("c1")
    board["objects"]["c1"]["kind"] = "unit"
    board["objects"]["c1"]["play_permissions"] = ["ambush"]
    board["battlefields"]["bf1"]["controller"] = "p2"
    board["players"]["p1"]["zones"]["base"].remove("u1")
    board["battlefields"]["bf1"]["objects"].append("u1")  # a friendly Unit is there
    unit_decl = declaration(chain_item={"id": "unit-1", "object_kind": "unit", "timing": "default"}, entry_location={"kind": "battlefield", "battlefield": "bf1"})
    ambushed = play_card(timing, board, unit_decl)
    if not ambushed.get("committed"):
        errors.append(f"Ambush did not open the enemy Battlefield: {ambushed.get('reason_code')} {ambushed.get('reason')}")
    elif ambushed["trace"][0].get("ambush") != {"battlefield": "bf1", "friendly_units": ["u1"]}:
        errors.append(f"the Ambush derivation was not recorded: {ambushed['trace'][0].get('ambush')}")
    no_permission = copy.deepcopy(board)
    no_permission["objects"]["c1"]["play_permissions"] = []
    refused = play_card(timing, no_permission, unit_decl)
    if refused.get("reason_code") != "entry_location_illegal":
        errors.append(f"negative mutation failed: the same entry without the Ambush permission was allowed: {refused.get('reason_code')}")
    alone = copy.deepcopy(board)
    alone["battlefields"]["bf1"]["objects"].remove("u1")
    alone["players"]["p1"]["zones"]["base"].append("u1")
    no_units = play_card(timing, alone, unit_decl)
    if no_units.get("reason_code") != "entry_location_illegal":
        errors.append(f"Ambush was allowed without a friendly Unit there: {no_units.get('reason_code')}")
    claimed = play_card(timing, alone, {**unit_decl, "timing_source": "ambush"})
    if claimed.get("reason_code") != "ambush_location_invalid":
        errors.append(f"a claimed Ambush timing without a friendly Unit was not refused: {claimed.get('reason_code')}")
    else:
        check = build_engine_check("play", claimed, input_hashes={"timing_state": "sha256:" + "1" * 64, "effect_state": hash_value(alone), "play_declaration": "sha256:" + "2" * 64})
        if check["outcome"] != "illegal":
            errors.append(f"an invalid Ambush wrapped as {check['outcome']}")

    # --- Unique is a deck constraint, never a play restriction ------------------------------------------
    twins = hand_state("c1")
    twins["objects"]["c1"]["unique"] = True
    twins["objects"]["u1"]["unique"] = True
    if validate_state(twins):
        errors.append(f"the unique characteristic was refused by the validator: {validate_state(twins)}")
    same_name = play_card(timing, twins, declaration())
    if not same_name.get("committed"):
        errors.append(f"a Unique card was refused at play; Core 825.3 is a deck constraint: {same_name.get('reason_code')} {same_name.get('reason')}")
    broken = copy.deepcopy(twins)
    broken["objects"]["c1"]["unique"] = "yes"
    if not any("unique" in e for e in validate_state(broken)):
        errors.append("a non-boolean unique flag was accepted")

    # --- optional zones -----------------------------------------------------------------------------------
    legend = with_zone(base, "legend_zone", "c2")
    legend["objects"]["c2"]["kind"] = "legend"  # Core 107.4.d: only a legend lives there
    if validate_state(legend):
        errors.append(f"a state with a Legend Zone is invalid: {validate_state(legend)}")
    unknown_zone = copy.deepcopy(base)
    unknown_zone["players"]["p1"]["zones"]["pocket"] = []
    if not any("zones" in e for e in validate_state(unknown_zone)):
        errors.append("an unknown player zone was accepted")
    missing_zone = copy.deepcopy(base)
    del missing_zone["players"]["p1"]["zones"]["banishment"]
    if not any("zones" in e for e in validate_state(missing_zone)):
        errors.append("a state missing a mandatory zone was accepted")

    # --- scope, schema, determinism ------------------------------------------------------------------------
    scope = KIND_CONFIG["play"]
    if not {"play_sources", "cost_override", "ambush"} <= set(scope["supported"]) or "deck_construction" not in scope["unsupported"]:
        errors.append("the play scope does not declare the C-44 capabilities and its deck-construction boundary")
    schema = json.loads((SKILL_DIR / "schemas" / "play-declaration.schema.json").read_text(encoding="utf-8"))
    if not {"hand", "champion_zone", "trash"} <= set(schema["properties"]["source"]["properties"]["kind"]["enum"]) or "cost_override" not in schema["properties"]:
        errors.append("the play-declaration schema does not carry the sources and the override")
    state_schema = json.loads((SKILL_DIR / "schemas" / "effect-state.schema.json").read_text(encoding="utf-8"))
    if "champion_zone" not in state_schema["$defs"]["zones"]["properties"] or "unique" not in state_schema["$defs"]["object"]["properties"]:
        errors.append("the effect-state schema lacks the optional zones or the unique characteristic")
    snapshot = copy.deepcopy(champion)
    if play_card(timing, champion, declaration(source={"kind": "champion_zone"})) != from_champion or champion != snapshot:
        errors.append("a sourced play is not deterministic or mutated its input")
    if object_identity(from_champion["next_effect_state"], "c1") != "c1@1":
        errors.append("a card played from the Champion Zone did not become a new object (124)")

    if errors:
        print("FAILED: play source / cost override / ambush checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("play source / cost override / ambush checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
