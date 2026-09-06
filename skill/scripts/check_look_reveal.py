#!/usr/bin/env python3
"""
Regression gate for C-41 (ADR-0011 §3; Codex G-1 on DP-62): look-at / reveal
marks, the player's `card_ordering` put-back, taking a looked-at card,
multi-card Recycle as one action, and Predict.

Must hold:
  - look_at_top marks the top cards for the controller only, leaves the deck
    order and identities alone, and its trace carries a count and hash but no
    ids (negative mutation: reveal from main_deck_top lists ids and
    identities in its trace because it is public); a short deck looks at as
    many as possible with completion partial and no Burn Out (431.1.c);
  - put_back over two looked cards stops as card_ordering_required with a
    private summary; a card_selection for it is invalid_input (kind
    mismatch); a permutation missing a card is invalid_input; one naming a
    card that was not looked at is illegal_operation; the supplied order
    becomes the deck's top order with identities unchanged, and the trace
    carries the ordering's hash and who may see it, never the order; one
    looked card needs no decision;
  - the reveal marks are gone from the committed state (424.3.a) and the
    result says how many ended; a draw of a looked card drops its mark;
  - put_in_hand takes the chosen looked card as a new object; draw_it does
    the same and marks the event as a Draw;
  - recycle of two trash cards to one deck needs the card_ordering, applies
    it to the bottom as one action with new identities; one card needs no
    decision; a token ceases to exist;
  - predict 2 stops for the recycle choice (private card_selection); with
    none recycled it stops for the put-back order, then puts both back in
    that order; with both recycled it needs the bottom order; on an empty
    deck it is a no_op without Burn Out; with a 1-card deck it is partial;
  - the schemas list the ops and the `reveals` state; the manifest cites
    every op; determinism and purity.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from capability_manifest import build_manifest  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import OP_RULES, apply_program, hash_value, object_identity, validate_state  # noqa: E402
from engine_check import build_engine_check  # noqa: E402


def envelope(state, *decisions):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": list(decisions)}


def ordering(decision_id, value, state, controller="p1", kind="card_ordering", identities=None):
    return {"decision_id": decision_id, "stage": "resolution", "kind": kind, "controller": controller, "value": value,
            "selection_identities": identities if identities is not None else {i: object_identity(state, i) or f"{i}@0" for i in value}}


def deck3():
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"] = ["c1", "c2", "c3"]
    state["players"]["p1"]["zones"]["trash"] = []
    return state


def ev(result, index=0):
    return result["trace"][index] if result.get("committed") else {}


def leaks(payload, *ids):
    dumped = json.dumps(payload)
    return [i for i in ids if f'"{i}"' in dumped]


def main() -> int:
    errors: list[str] = []
    state = deck3()

    # --- look_at_top ---------------------------------------------------------------------------------
    look2 = program("look", {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 2}, {"op": "put_back", "effect_id": "pb", "player": "p1", "decision_ref": "order"})
    ask = apply_program(state, look2)
    if ask.get("reason_code") != "card_ordering_required" or ask.get("decision_ids") != ["order"] or ask.get("decision_controller") != "p1":
        errors.append(f"put_back over two looked cards did not stop for card_ordering: {ask.get('reason_code')} {ask.get('errors')}")
    else:
        looked = ask["trace"][0]
        if looked.get("looked_count") != 2 or looked.get("objects_visible_to") != ["p1"] or looked.get("deck_order_unchanged") is not True or not str(looked.get("objects_hash", "")).startswith("sha256:"):
            errors.append(f"look trace is wrong: {looked}")
        if leaks(looked, "c1", "c2") or leaks({k: v for k, v in ask.items() if k != "trace"}, "c1", "c2"):
            errors.append("a look listed the looked cards publicly")
        summary = ask.get("choice") or {}
        if summary.get("decision_kind") != "card_ordering" or summary.get("visibility") != "private_to_chooser" or summary.get("options_count") != 2 or "options" in summary:
            errors.append(f"card_ordering summary is wrong: {summary}")
        check = build_engine_check("effect", ask, input_hashes={"effect_state": hash_value(state), "effect_program": "sha256:" + "6" * 64}, include_raw=True)
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "card_ordering" or leaks(check, "c1", "c2"):
            errors.append(f"card_ordering wrapped as {check['outcome']} {check.get('decision_required')} or leaked")
    # negative mutation: a public reveal lists ids
    reveal = apply_program(state, program("rv", {"op": "reveal", "effect_id": "r", "player": "p1", "from": "main_deck_top", "count": 2}))
    if not reveal.get("committed") or ev(reveal).get("revealed") != [{"object_id": "c1", "identity": "c1@0"}, {"object_id": "c2", "identity": "c2@0"}] or ev(reveal).get("visible_to") != "all":
        errors.append(f"a public reveal did not list its cards: {reveal.get('reason') or reveal.get('errors')} {ev(reveal)}")
    elif "reveals" in reveal["next_state"] or reveal.get("reveals_ended") != 2 or reveal["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c1", "c2", "c3"]:
        errors.append("reveal marks outlived the program or the deck moved")
    short = apply_program(state, program("look5", {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 5}))
    if not short.get("committed") or ev(short).get("looked_count") != 3 or ev(short).get("completion") != "partial" or ev(short).get("burn_out") is not False or short["next_state"]["players"]["p1"]["zones"]["trash"] != []:
        errors.append(f"a short look did not stop at the deck's end without Burn Out: {ev(short)}")

    # --- put_back decisions ----------------------------------------------------------------------------
    wrong_kind = apply_program(state, look2, decisions=envelope(state, ordering("order", ["c2", "c1"], state, kind="card_selection")))
    if wrong_kind.get("valid") is not False or not any("card_ordering" in e for e in wrong_kind.get("errors", [])):
        errors.append(f"a card_selection was accepted as a put-back order: {wrong_kind.get('reason_code')} {wrong_kind.get('errors')}")
    missing = apply_program(state, look2, decisions=envelope(state, ordering("order", ["c2"], state)))
    if missing.get("valid") is not False or not any("every candidate" in e for e in missing.get("errors", [])):
        errors.append(f"an incomplete permutation was accepted: {missing.get('errors')}")
    foreign = apply_program(state, look2, decisions=envelope(state, ordering("order", ["c2", "c3"], state)))
    if foreign.get("reason_code") != "illegal_operation":
        errors.append(f"an order naming an unlooked card was not illegal: {foreign.get('reason_code')} {foreign.get('errors')}")
    swapped = apply_program(state, look2, decisions=envelope(state, ordering("order", ["c2", "c1"], state)))
    if not swapped.get("committed") or swapped["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c2", "c1", "c3"]:
        errors.append(f"the put-back order was not applied to the top: {swapped.get('reason') or swapped.get('errors')} {swapped.get('next_state', {}).get('players', {}).get('p1', {}).get('zones', {}).get('main_deck')}")
    else:
        pb = swapped["trace"][1]
        if object_identity(swapped["next_state"], "c1") != "c1@0" or pb.get("order_visible_to") != ["p1"] or not str(pb.get("ordering_hash", "")).startswith("sha256:") or leaks(pb, "c1", "c2"):
            errors.append(f"put_back changed identities or exposed the order: {pb}")
        if "reveals" in swapped["next_state"] or validate_state(swapped["next_state"]):
            errors.append(f"marks survived or state invalid after put_back: {validate_state(swapped['next_state'])}")
    bottom = apply_program(state, program("lb", {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 1}, {"op": "put_back", "effect_id": "pb", "player": "p1", "position": "bottom"}))
    if not bottom.get("committed") or bottom["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c2", "c3", "c1"] or bottom["trace"][1].get("selection", {}).get("forced") is not True:
        errors.append(f"a single looked card was not put back at the bottom without a decision: {bottom.get('reason') or bottom.get('errors')}")
    # a Draw of a looked card drops its mark
    drawn = apply_program(state, program("ld", {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 2}, {"op": "draw", "effect_id": "d", "player": "p1", "count": 1}, {"op": "put_back", "effect_id": "pb", "player": "p1"}))
    if not drawn.get("committed") or drawn["next_state"]["players"]["p1"]["zones"]["hand"] != ["c1"] or drawn["trace"][2].get("count") != 1:
        errors.append(f"a drawn looked card kept its mark: {drawn.get('reason') or drawn.get('errors')} {drawn.get('trace', [{}])[-1]}")

    # --- put_in_hand / draw_it -------------------------------------------------------------------------------
    take = program("take", {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 2}, {"op": "put_in_hand", "effect_id": "ph", "player": "p1", "decision_ref": "pick"}, {"op": "put_back", "effect_id": "pb", "player": "p1"})
    ask_take = apply_program(state, take)
    if ask_take.get("reason_code") != "card_selection_required" or ask_take.get("choice", {}).get("visibility") != "private_to_chooser":
        errors.append(f"put_in_hand did not stop for a private card_selection: {ask_take.get('reason_code')} {ask_take.get('errors')}")
    taken = apply_program(state, take, decisions=envelope(state, ordering("pick", ["c2"], state, kind="card_selection")))
    if not taken.get("committed") or taken["next_state"]["players"]["p1"]["zones"]["hand"] != ["c2"] or object_identity(taken["next_state"], "c2") != "c2@1" or taken["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c1", "c3"] or taken["trace"][1].get("draw_event") is not False:
        errors.append(f"put_in_hand did not take the chosen card as a new object: {taken.get('reason') or taken.get('errors')}")
    draw_it = program("di", {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 2}, {"op": "draw_it", "effect_id": "dr", "player": "p1", "decision_ref": "pick"})
    drew = apply_program(state, draw_it, decisions=envelope(state, ordering("pick", ["c1"], state, kind="card_selection")))
    if not drew.get("committed") or drew["trace"][1].get("draw_event") is not True or drew["trace"][1].get("drawn") != 1 or "c1" not in drew["next_state"]["players"]["p1"]["zones"]["hand"] or "reveals" in drew["next_state"]:
        errors.append(f"draw_it did not draw the chosen card: {drew.get('reason') or drew.get('errors')} {drew.get('trace', [{}, {}])[1] if drew.get('trace') else None}")

    # --- recycle (multi) ------------------------------------------------------------------------------------------
    trash = base_state()
    trash["players"]["p1"]["zones"]["trash"] = ["c3", "c2"]
    trash["players"]["p1"]["zones"]["main_deck"] = ["c1"]
    rec = program("rec", {"op": "recycle", "effect_id": "r", "player": "p1", "objects": ["c3", "c2"], "order_ref": "bottom"})
    ask_rec = apply_program(trash, rec)
    if ask_rec.get("reason_code") != "card_ordering_required" or ask_rec.get("decision_ids") != ["bottom"]:
        errors.append(f"recycling two cards did not ask for the bottom order: {ask_rec.get('reason_code')} {ask_rec.get('errors')}")
    recycled = apply_program(trash, rec, decisions=envelope(trash, ordering("bottom", ["c2", "c3"], trash)))
    if not recycled.get("committed") or recycled["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c1", "c2", "c3"] or ev(recycled).get("simultaneous") is not True or ev(recycled).get("identities_after") != {"c2": "c2@1", "c3": "c3@1"}:
        errors.append(f"multi-card recycle did not apply the order to the bottom as one action: {recycled.get('reason') or recycled.get('errors')} {ev(recycled)}")
    one = apply_program(trash, program("rec1", {"op": "recycle", "effect_id": "r", "player": "p1", "objects": ["c3"]}))
    if not one.get("committed") or one["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c1", "c3"] or ev(one).get("order_decision") is not None:
        errors.append(f"a single recycle asked for an order: {one.get('reason') or one.get('errors')}")
    with_token = apply_program(trash, program("tok", {"op": "play_token", "object_id": "t1", "owner": "p1", "controller": "p1", "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"}}))["next_state"]
    gone = apply_program(with_token, program("rect", {"op": "recycle", "effect_id": "r", "player": "p1", "objects": ["t1", "c3"]}))
    if not gone.get("committed") or "t1" in gone["next_state"]["objects"] or ev(gone).get("destinations", {}).get("t1") != "ceased_to_exist" or ev(gone).get("order_decision") is not None:
        errors.append(f"a recycled token did not cease to exist (and the single deck card needed no order): {gone.get('reason') or gone.get('errors')} {ev(gone)}")

    # --- predict --------------------------------------------------------------------------------------------------
    pred = program("pred", {"op": "predict", "effect_id": "p", "player": "p1", "count": 2, "recycle_ref": "rc", "order_ref": "ro", "put_back_ref": "pb"})
    ask_pred = apply_program(state, pred)
    if ask_pred.get("reason_code") != "card_selection_required" or ask_pred.get("decision_ids") != ["rc"] or ask_pred.get("choice", {}).get("visibility") != "private_to_chooser" or leaks({k: v for k, v in ask_pred.items() if k != "trace"}, "c1", "c2"):
        errors.append(f"predict did not stop for the private recycle choice: {ask_pred.get('reason_code')} {ask_pred.get('errors')}")
    none_env = envelope(state, {"decision_id": "rc", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": [], "selection_identities": {}})
    ask_order = apply_program(state, pred, decisions=none_env)
    if ask_order.get("reason_code") != "card_ordering_required" or ask_order.get("decision_ids") != ["pb"]:
        errors.append(f"predict with nothing recycled did not ask for the put-back order: {ask_order.get('reason_code')} {ask_order.get('errors')}")
    kept = apply_program(state, pred, decisions=envelope(state, none_env["decisions"][0], ordering("pb", ["c2", "c1"], state)))
    if not kept.get("committed") or kept["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c2", "c1", "c3"] or ev(kept).get("recycled_count") != 0 or ev(kept).get("put_back_count") != 2 or ev(kept).get("burn_out") is not False:
        errors.append(f"predict did not put both back in the chosen order: {kept.get('reason') or kept.get('errors')} {ev(kept)}")
    both = apply_program(state, pred, decisions=envelope(state, ordering("rc", ["c1", "c2"], state, kind="card_selection")))
    if both.get("reason_code") != "card_ordering_required" or both.get("decision_ids") != ["ro"]:
        errors.append(f"predict recycling two cards did not ask for the bottom order: {both.get('reason_code')} {both.get('errors')}")
    both_done = apply_program(state, pred, decisions=envelope(state, ordering("rc", ["c1", "c2"], state, kind="card_selection"), ordering("ro", ["c1", "c2"], state)))
    if not both_done.get("committed") or both_done["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c3", "c1", "c2"] or ev(both_done).get("recycled_count") != 2 or ev(both_done).get("put_back_count") != 0 or object_identity(both_done["next_state"], "c1") != "c1@0":
        errors.append(f"predict recycling both did not bottom them in order (same deck, same identity): {both_done.get('reason') or both_done.get('errors')} {ev(both_done)}")
    one_of_two = apply_program(state, pred, decisions=envelope(state, ordering("rc", ["c1"], state, kind="card_selection")))
    if not one_of_two.get("committed") or one_of_two["next_state"]["players"]["p1"]["zones"]["main_deck"] != ["c2", "c3", "c1"]:
        errors.append(f"predict recycling one of two needed a decision it should not: {one_of_two.get('reason_code')} {one_of_two.get('errors')}")
    empty = copy.deepcopy(state); empty["players"]["p1"]["zones"]["main_deck"] = []; empty["players"]["p1"]["zones"]["trash"] = ["c1", "c2", "c3"]
    nothing = apply_program(empty, pred)
    if not nothing.get("committed") or ev(nothing).get("outcome") != "no_op" or ev(nothing).get("burn_out") is not False or nothing["next_state"]["players"]["p1"]["zones"]["trash"] != ["c1", "c2", "c3"]:
        errors.append(f"predict on an empty deck Burned Out or failed: {nothing.get('reason_code')} {nothing.get('errors')} {ev(nothing)}")
    one_card = copy.deepcopy(state); one_card["players"]["p1"]["zones"]["main_deck"] = ["c1"]; one_card["players"]["p1"]["zones"]["trash"] = ["c2", "c3"]
    partial = apply_program(one_card, pred, decisions=envelope(one_card, {"decision_id": "rc", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": [], "selection_identities": {}}))
    if not partial.get("committed") or ev(partial).get("completion") != "partial" or ev(partial).get("looked_count") != 1:
        errors.append(f"predict 2 on a 1-card deck was not partial: {partial.get('reason_code')} {partial.get('errors')} {ev(partial)}")

    # --- schemas, manifest, determinism -----------------------------------------------------------------------------
    ep = json.loads((SKILL_DIR / "schemas" / "effect-program.schema.json").read_text(encoding="utf-8"))
    ops = set(ep["properties"]["effects"]["items"]["properties"]["op"]["enum"])
    new_ops = {"look_at_top", "reveal", "put_back", "put_in_hand", "draw_it", "recycle", "predict"}
    if not new_ops <= ops:
        errors.append(f"effect-program schema lacks {sorted(new_ops - ops)}")
    es = json.loads((SKILL_DIR / "schemas" / "effect-state.schema.json").read_text(encoding="utf-8"))
    if "reveals" not in es["properties"]:
        errors.append("effect-state schema lacks reveals")
    manifest = build_manifest()
    cited = {o["id"]: o["rule_locators"] for o in manifest["operations"]}
    for op in new_ops:
        if op not in cited or cited[op] != OP_RULES[op] or not cited[op]:
            errors.append(f"manifest does not cite {op}")
    snapshot = copy.deepcopy(state)
    if apply_program(state, look2, decisions=envelope(state, ordering("order", ["c2", "c1"], state))) != swapped or state != snapshot:
        errors.append("look / put_back is not deterministic or mutated its input")

    if errors:
        print("FAILED: look / reveal / put_back / recycle / predict checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("look / reveal / put_back / recycle / predict checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
