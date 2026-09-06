#!/usr/bin/env python3
"""
Regression gate for C-43 (ADR-0011 §5; Codex G-1 on DP-64): Banish, Counter
with its timing-chain removal, and [Burn N].

Must hold:
  - banish moves a card from any zone straight into its owner's Banishment as
    a new object (427.1, 124); a token ceases to exist; it is not a Kill —
    a banished Unit with a death trigger schedules none, while killing the
    same Unit does (negative mutation), and it is not a Discard;
  - a banish driven by a `choice` resolves that choice exactly once: only the
    chosen card moves and the trace names the decision (counterexample for a
    self-resolving op being pre-resolved as a single-object choice);
  - counter clears the effect-side chain entry, sends the card to its owner's
    trash as a new object (425.1.a), records that it was not played (425.1.b)
    and that no cost is refunded (425.1.c); `card_to: hand` returns it
    instead; an ability item has no card; an unknown item is
    illegal_operation; `counterable: false` is unsupported
    (cannot_be_countered);
  - the resolution bridge removes the countered item from the timing chain in
    the same commit and reopens the state when the chain empties; when the
    timing chain does not carry the item, nothing commits (negative mutation
    for the two-state atomicity);
  - burn moves the top cards to the trash as new objects with burn_out false;
    a deck shorter than the count is unsupported: burn_out_non_draw and
    changes nothing, while the same count on a deck one card longer commits,
    and a Draw from the same empty deck still Burns Out (the refusal is the
    non-Draw path, not Burn Out itself);
  - the manifest cites the three operations and remove_chain_item; the effect
    scope declares them and keeps burn_out_non_draw unsupported; determinism.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from capability_manifest import build_manifest  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import OP_RULES, apply_program, hash_value, object_identity, validate_state  # noqa: E402
from engine_check import KIND_CONFIG, build_engine_check  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import remove_chain_item, state_hash  # noqa: E402


def ev(result, index=0):
    return result["trace"][index] if result.get("committed") else {}


def envelope(state, *decisions):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": list(decisions)}


def pick(decision_id, ids, state, controller="p1"):
    return {"decision_id": decision_id, "stage": "resolution", "kind": "card_selection", "controller": controller, "value": ids,
            "selection_identities": {i: object_identity(state, i) or f"{i}@0" for i in ids}}


def main() -> int:
    errors: list[str] = []
    state = base_state()
    state["objects"]["u1"]["death_triggers"] = [{"trigger_id": "t1", "controller": "p1", "source_object": "u1", "controller_order": 0,
                                                 "effect_program_id": "p", "optional_at_finalize": False}]

    # --- banish -------------------------------------------------------------------------------
    from_board = apply_program(state, program("b", {"op": "banish", "effect_id": "b", "object_id": "u1"}))
    if not from_board.get("committed") or "u1" not in from_board["next_state"]["players"]["p1"]["zones"]["banishment"]:
        errors.append(f"banish did not move the unit to Banishment: {from_board.get('reason') or from_board.get('errors')}")
    else:
        e = ev(from_board)
        if object_identity(from_board["next_state"], "u1") != "u1@1" or e.get("not_kill") is not True or e.get("not_discard") is not True:
            errors.append(f"banish did not make a new object or claimed to be a Kill / Discard: {e}")
        if e.get("pending_triggers") or from_board.get("pending_triggers"):
            errors.append("banishing a unit scheduled its death trigger (Core 427.2.a: Banish is not a subset of Kill)")
        if "Core 427.1" not in e.get("rule_locators", []) or validate_state(from_board["next_state"]):
            errors.append(f"banish locators or state are wrong: {e.get('rule_locators')} {validate_state(from_board['next_state'])}")
    killed = apply_program(state, program("k", {"op": "kill", "effect_id": "k", "object_id": "u1"}))
    if not killed.get("committed") or not ev(killed).get("pending_triggers"):
        errors.append("negative mutation failed: killing the same unit scheduled no death trigger, so banish's silence proves nothing")
    from_trash = apply_program(state, program("bt", {"op": "banish", "effect_id": "b", "object_id": "c3"}))
    if not from_trash.get("committed") or "c3" not in from_trash["next_state"]["players"]["p1"]["zones"]["banishment"] or from_trash["next_state"]["players"]["p1"]["zones"]["trash"] != []:
        errors.append(f"banish from the trash failed: {from_trash.get('reason') or from_trash.get('errors')}")
    with_token = apply_program(state, program("tok", {"op": "play_token", "object_id": "t1", "owner": "p1", "controller": "p1", "token_kind": "unit",
                                                     "base_might": 1, "destination": {"kind": "base", "player": "p1"}}))["next_state"]
    gone = apply_program(with_token, program("bk", {"op": "banish", "effect_id": "b", "object_id": "t1"}))
    if not gone.get("committed") or "t1" in gone["next_state"]["objects"] or ev(gone).get("destinations", {}).get("t1") != "ceased_to_exist":
        errors.append(f"a banished token did not cease to exist: {ev(gone)}")
    two_trash = copy.deepcopy(state)
    two_trash["players"]["p1"]["zones"]["trash"] = ["c3", "c2"]
    two_trash["players"]["p1"]["zones"]["main_deck"] = ["c1"]
    choice_banish = program("bc", {"op": "banish", "effect_id": "b", "player": "p1", "decision_ref": "which",
                                   "choice": {"selection_kind": "single", "from": "trash", "by": "p1"}})
    ask = apply_program(two_trash, choice_banish)
    if ask.get("reason_code") != "card_selection_required" or ask.get("decision_ids") != ["which"]:
        errors.append(f"a choice-driven banish did not ask for the choice: {ask.get('reason_code')} {ask.get('errors')}")
    chosen = apply_program(two_trash, choice_banish, decisions=envelope(two_trash, pick("which", ["c2"], two_trash)))
    if not chosen.get("committed") or chosen["next_state"]["players"]["p1"]["zones"]["banishment"] != ["c2"] or chosen["next_state"]["players"]["p1"]["zones"]["trash"] != ["c3"]:
        errors.append(f"a choice-driven banish moved the wrong cards (a second resolution would): {chosen.get('reason_code')} {chosen.get('errors')} {ev(chosen)}")
    elif ev(chosen).get("selection", {}).get("decision_id") != "which":
        errors.append(f"the banish trace does not name the decision it consumed: {ev(chosen).get('selection')}")

    # --- counter ------------------------------------------------------------------------------------
    on_chain = copy.deepcopy(state)
    on_chain["players"]["p1"]["zones"]["main_deck"] = ["c2"]
    on_chain["players"]["p2"]["zones"]["main_deck"] = []
    on_chain["chain_items"] = {"spell-1": {"card": "c1", "controller": "p1"}, "counter-1": {"card": "c4", "controller": "p2"}}
    counter_program = {"schema_version": "riftbound-effect-program.v1", "ruleset": on_chain["ruleset"], "program_id": "counter-prog", "controller": "p2",
                       "effects": [{"op": "counter", "effect_id": "c", "chain_item_id": "spell-1"}]}
    countered = apply_program(on_chain, counter_program)
    if not countered.get("committed") or "spell-1" in (countered["next_state"].get("chain_items") or {}) or "c1" not in countered["next_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append(f"counter did not clear the item and trash its card: {countered.get('reason_code')} {countered.get('errors')}")
    else:
        e = ev(countered)
        if e.get("not_played") is not True or e.get("costs_refunded") is not False or e.get("identity_after") != "c1@1" or countered.get("countered_chain_items") != ["spell-1"]:
            errors.append(f"the counter trace is wrong: {e} {countered.get('countered_chain_items')}")
    to_hand = apply_program(on_chain, {**counter_program, "effects": [{"op": "counter", "effect_id": "c", "chain_item_id": "spell-1", "card_to": "hand"}]})
    if not to_hand.get("committed") or "c1" not in to_hand["next_state"]["players"]["p1"]["zones"]["hand"]:
        errors.append(f"card_to hand did not return the countered card: {to_hand.get('reason_code')} {to_hand.get('errors')}")
    ability_chain = copy.deepcopy(on_chain)
    ability_chain["chain_items"]["spell-1"] = {"source_object": "u1", "ability_id": "u1:a1", "controller": "p1"}
    ability_chain["players"]["p1"]["zones"]["main_deck"] = ["c1", "c2"]
    ability_countered = apply_program(ability_chain, counter_program)
    if not ability_countered.get("committed") or ev(ability_countered).get("no_card") is not True or ability_countered["next_state"]["players"]["p1"]["zones"]["base"] != ["u1"]:
        errors.append(f"countering an activated ability moved a card or failed: {ability_countered.get('reason_code')} {ev(ability_countered)}")
    unknown = apply_program(on_chain, {**counter_program, "effects": [{"op": "counter", "effect_id": "c", "chain_item_id": "nope"}]})
    if unknown.get("reason_code") != "illegal_operation":
        errors.append(f"countering an item that is not on the chain was not illegal: {unknown.get('reason_code')}")
    protected = copy.deepcopy(on_chain)
    protected["chain_items"]["spell-1"]["counterable"] = False
    shielded = apply_program(protected, counter_program)
    if shielded.get("unsupported") is not True or "cannot_be_countered" not in str(shielded.get("reason")):
        errors.append(f"'can't be countered' was not unsupported: {shielded.get('reason_code')} {shielded.get('reason')}")
    if validate_state(protected):
        errors.append(f"a chain entry marked counterable is invalid: {validate_state(protected)}")

    # the bridge removes the timing item in the same commit
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized"), item("counter-1", "p2", "spell", "reaction", "finalized")], passes=["p2", "p1"])
    bridged = resolve_with_program(timing, "counter-1", on_chain, counter_program)
    if not bridged.get("committed"):
        errors.append(f"the bridge refused a counter: {bridged.get('stage')} {bridged.get('reason')}")
    else:
        after_timing, after_effect = bridged["next_timing_state"], bridged["next_effect_state"]
        if [i["id"] for i in after_timing["chain"]["items"]] != []:
            errors.append(f"the countered item stayed on the timing chain: {[i['id'] for i in after_timing['chain']['items']]}")
        if after_timing["priority"] != "p1" or after_timing["chain"]["initiated_by"] is not None:
            errors.append(f"the state did not reopen after the chain emptied: priority {after_timing['priority']}")
        if "c1" not in after_effect["players"]["p1"]["zones"]["trash"] or "c4" not in after_effect["players"]["p2"]["zones"]["trash"]:
            errors.append("the countered card or the countering spell did not reach the trash")
        if not bridged["trace"].get("countered") or bridged["trace"]["countered"][0].get("item_id") != "spell-1":
            errors.append(f"the bridge trace does not record the removal: {bridged['trace'].get('countered')}")
    lonely = fixture(priority="p2", items=[item("counter-1", "p2", "spell", "reaction", "finalized")], passes=["p2", "p1"])
    mismatched = resolve_with_program(lonely, "counter-1", on_chain, counter_program)
    if mismatched.get("committed") or mismatched.get("stage") != "counter" or "next_effect_state" in mismatched:
        errors.append(f"negative mutation failed: a counter whose item is not on the timing chain committed: {mismatched.get('stage')} {mismatched.get('reason')}")
    missing = remove_chain_item(lonely, "spell-1")
    if missing.get("applied") is not False or missing.get("reason_code") != "chain_item_not_found":
        errors.append(f"remove_chain_item accepted an unknown item: {missing.get('reason_code')}")

    # --- burn ---------------------------------------------------------------------------------------
    deck2 = copy.deepcopy(state)
    deck2["players"]["p1"]["zones"]["main_deck"] = ["c1", "c2"]
    burned = apply_program(deck2, program("burn", {"op": "burn", "effect_id": "b", "player": "p1", "count": 2}))
    if not burned.get("committed") or burned["next_state"]["players"]["p1"]["zones"]["main_deck"] != [] or burned["next_state"]["players"]["p1"]["zones"]["trash"] != ["c3", "c1", "c2"]:
        errors.append(f"burn did not move the top cards to the trash in order: {burned.get('reason_code')} {burned.get('errors')}")
    else:
        e = ev(burned)
        if e.get("burn_out") is not False or e.get("identities_after") != {"c1": "c1@1", "c2": "c2@1"} or e.get("burned_count") != 2:
            errors.append(f"the burn trace is wrong: {e}")
    short_deck = copy.deepcopy(deck2)
    short_deck["players"]["p1"]["zones"]["main_deck"] = ["c1"]
    short_deck["players"]["p1"]["zones"]["hand"] = ["c2"]
    short = apply_program(short_deck, program("burn", {"op": "burn", "effect_id": "b", "player": "p1", "count": 2}))
    if short.get("unsupported") is not True or "burn_out_non_draw" not in str(short.get("reason")) or short.get("committed"):
        errors.append(f"[Burn 2] on a one-card deck was not unsupported: {short.get('reason_code')} {short.get('reason')}")
    else:
        check = build_engine_check("effect", short, input_hashes={"effect_state": hash_value(short_deck), "effect_program": "sha256:" + "7" * 64})
        if check["outcome"] != "unsupported":
            errors.append(f"a short burn wrapped as {check['outcome']}")
    empty_deck = copy.deepcopy(short_deck)
    empty_deck["players"]["p1"]["zones"]["main_deck"] = []
    empty_deck["players"]["p1"]["zones"]["trash"] = ["c1"]
    empty_deck["mode"] = {"victory_score": 8}
    draw_instead = apply_program(empty_deck, program("draw", {"op": "draw", "effect_id": "d", "player": "p1", "count": 1}))
    if draw_instead.get("unsupported") is True:
        errors.append("negative mutation failed: a Draw from the same empty deck is also unsupported, so the burn refusal is not about the non-Draw path")

    # --- manifest, scope, determinism -------------------------------------------------------------------
    manifest = build_manifest()
    cited = {o["id"]: o["rule_locators"] for o in manifest["operations"]}
    for op in ("banish", "counter", "burn"):
        if cited.get(op) != OP_RULES[op]:
            errors.append(f"the manifest does not cite {op}")
    if not any(p["id"] == "remove_chain_item" for p in manifest["procedures"]):
        errors.append("the manifest does not list remove_chain_item")
    effect_scope = KIND_CONFIG["effect"]
    if not {"banish", "counter", "burn"} <= set(effect_scope["supported"]) or "burn_out_non_draw" not in effect_scope["unsupported"] or "cannot_be_countered" not in effect_scope["unsupported"]:
        errors.append("the effect scope does not declare the C-43 operations and their boundary")
    if "counter_chain_removal" not in KIND_CONFIG["resolution"]["supported"]:
        errors.append("the resolution scope does not declare the counter chain removal")
    snapshot = copy.deepcopy(on_chain)
    if apply_program(on_chain, counter_program) != countered or on_chain != snapshot:
        errors.append("counter is not deterministic or mutated its input")
    if state_hash(timing) != state_hash(fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized"), item("counter-1", "p2", "spell", "reaction", "finalized")], passes=["p2", "p1"])):
        errors.append("the timing fixture is not stable")

    if errors:
        print("FAILED: banish / counter / burn checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("banish / counter / burn checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
