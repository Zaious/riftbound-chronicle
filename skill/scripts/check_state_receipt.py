#!/usr/bin/env python3
"""Gate: the per-state completeness receipt (package 13, C2; GPT 2026-10-15 rulings 1, 3 and 5).

On check_play_space's synthetic catalogue and boards:

  R1 complete    p1 at a Neutral Open priority point on each board: complete, every action kind enumerated, the
                 actions those families list, the information checks independent; the receipt hashes itself
  R2 the point   the same board with a pending item on the Chain (a procedure is due): not complete,
                 procedure_due:finalize_oldest_pending
  R3 a family    a family over its cap: not complete, naming it
  R4 the state   an object without card_ref: not complete, not_an_environment_state
  R5 hidden      an action set that would change with the opponent's hand (a doctored enumeration that reads it) is
                 named depends_on_hidden:the opponent's hand; one that would change with the Main Decks' order,
                 depends_on_hidden:the order of the Main Decks
  R6 another     a play whose procedure asks another player for a decision is unproved, by name
  R8 Zap/Twin    GPT's round-two control, standing: an enumeration that lists one more action only when the opponent's
                 unseen hand card is Twin. With Zap there, and with Pawn (the old check's one substitute), the true set
                 is the view's - nothing shows; the published sets of the Zap, Pawn and Twin states are one set (the
                 view's: no private value reaches it), and the Twin state's receipt is not complete
                 (depends_on_hidden:the opponent's hand)
  R7 private     (PACKAGE13 ruling 4) the opponent's facedown card is varied as another card and the set stays; an action
                 naming the opponent's unseen hand card is named leaks:; a card shown to the opponent alone outside every
                 varied dimension makes the receipt incomplete (unvaried_private:)

    python skill/scripts/check_state_receipt.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_receipt as R  # noqa: E402
import action_space as AS  # noqa: E402
import check_play_space as G  # noqa: E402
import legal_action as LA  # noqa: E402
import play_space as PS  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import hash_value  # noqa: E402

errors: list[str] = []


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def with_hidden(state: dict) -> dict:
    """The board with the opponent holding a card in hand and both players a two-card Main Deck."""
    cat = G.catalogue()
    state = copy.deepcopy(state)
    import closed_environment as CE
    for object_id, ref, owner, zone in (("oh", "Zap", "p2", "hand"), ("d1", "Pawn", "p1", "main_deck"),
                                        ("d2", "Zap", "p1", "main_deck"), ("e1", "Pawn", "p2", "main_deck"),
                                        ("e2", "Zap", "p2", "main_deck")):
        state["objects"][object_id] = CE.place(cat, ref, owner=owner, object_id=object_id)
        state["players"][owner]["zones"][zone].append(object_id)
    return state


def main() -> int:
    cat = G.catalogue()
    boards = {name: with_hidden(G.environment(cat, placed)) for name, placed in G.BOARDS.items()}
    # R1
    for name, state in boards.items():
        receipt = R.state_receipt(fixture(), state, "p1", cat)
        if not receipt["complete"] or set(receipt["families"]) != set(AS.ACTION_KINDS) \
                or any(f["status"] != "enumerated" for f in receipt["families"].values()) \
                or receipt["information"] != {"the opponent's hand": "masked", "the Main Decks": "masked"} \
                or receipt["receipt_hash"] != hash_value({k: v for k, v in receipt.items() if k != "receipt_hash"}):
            fail("R1 complete", f"{name}: {receipt['why']} {receipt['information']}")
        if name == "targets" and len(receipt["actions"]) < 4:
            fail("R1 complete", f"{name}: {len(receipt['actions'])} actions")
    state = boards["targets"]
    # R2
    pending = fixture(items=[item("spell-1", "p1", "spell", "default", "pending")])
    receipt = R.state_receipt(pending, state, "p1", cat)
    if receipt["complete"] or "procedure_due:finalize_oldest_pending" not in receipt["why"]:
        fail("R2 the point", f"{receipt['why']}")
    # R3
    original = PS.CALL_CAP
    PS.CALL_CAP = 2
    try:
        receipt = R.state_receipt(fixture(), state, "p1", cat)
    finally:
        PS.CALL_CAP = original
    if receipt["complete"] or not any(w.startswith("play_card:unproved") for w in receipt["why"]):
        fail("R3 a family", f"{receipt['why']}")
    # R4
    bare = copy.deepcopy(state)
    bare["objects"]["a"].pop("card_ref")
    receipt = R.state_receipt(fixture(), bare, "p1", cat)
    if receipt["complete"] or not any(w.startswith("not_an_environment_state") for w in receipt["why"]):
        fail("R4 the state", f"{receipt['why']}")
    # R5 (and R7: the opponent's facedown card is varied, and an action naming a private object leaks)
    import closed_environment as CE
    hidden_board = copy.deepcopy(state)
    hidden_board["objects"]["of"] = CE.place(cat, "Sneak", owner="p2", object_id="of")
    hidden_board["battlefields"]["bf1"]["facedown"]["cards"].append({"object_id": "of", "controller": "p2", "hidden_on_turn": "turn-0"})
    receipt = R.state_receipt(fixture(), hidden_board, "p1", cat)
    if not receipt["complete"] or receipt["information"].get("the opponent's facedown cards") != "masked":
        fail("R7 private", f"the opponent's facedown card: {receipt['why']} {receipt['information']}")
    original = LA.enumerate_actions

    def naming(observation, actor, catalogue=None, _original=original):
        result = _original(observation, actor, catalogue=catalogue)
        result["enumeration"]["actions"].append({"candidate_id": "pass_priority:oh", "family": "pass_priority",
                                                 "action": {"kind": "pass_priority", "actor": "oh"}, "required_facts": []})
        return result
    LA.enumerate_actions = naming
    try:
        receipt = R.state_receipt(fixture(), state, "p1", cat)
    finally:
        LA.enumerate_actions = original
    if receipt["complete"] or not any(w.startswith("leaks:oh") for w in receipt["why"]):
        fail("R7 private", f"an action naming the opponent's hand card: {receipt['why']}")
    # the same card revealed to everyone is not private: naming it leaks nothing
    revealed = copy.deepcopy(state)
    revealed["reveals"] = [{"object_id": "oh", "identity": "oh@0", "zone": "hand", "visible_to": "all", "session": "s0",
                            "kind": "reveal"}]
    LA.enumerate_actions = naming
    try:
        receipt = R.state_receipt(fixture(), revealed, "p1", cat)
    finally:
        LA.enumerate_actions = original
    if any(w.startswith("leaks:") for w in receipt["why"]):
        fail("R7 private", f"a card revealed to all was treated as private: {receipt['why']}")
    shown = copy.deepcopy(state)
    shown["objects"]["ob"] = CE.place(cat, "Pawn", owner="p2", object_id="ob")
    shown["players"]["p2"]["zones"]["banishment"].append("ob")
    shown["reveals"] = [{"object_id": "ob", "identity": "ob@0", "zone": "banishment", "visible_to": ["p2"],
                         "session": "s1", "kind": "look"}]
    receipt = R.state_receipt(fixture(), shown, "p1", cat)
    if receipt["complete"] or not any(w.startswith("unvaried_private:ob") for w in receipt["why"]):
        fail("R7 private", f"a card shown to the opponent only, outside every varied dimension: {receipt['why']}")
    for label, reads in (("the opponent's hand", lambda s: [s["objects"][o].get("card_ref") for o in s["players"]["p2"]["zones"]["hand"]]),
                         ("the Main Decks", lambda s: list(s["players"]["p1"]["zones"]["main_deck"])),
                         ("the opponent's facedown cards", lambda s: [s["objects"][c["object_id"]].get("card_ref")
                                                                      for c in s["battlefields"]["bf1"]["facedown"]["cards"]])):
        original = LA.enumerate_actions

        def doctored(observation, actor, catalogue=None, _reads=reads, _original=original):
            result = _original(observation, actor, catalogue=catalogue)
            seen = _reads(observation["component_states"]["effect_state"]["state"])
            result["enumeration"]["actions"].append({"candidate_id": f"pass_priority:{seen}", "family": "pass_priority",
                                                     "action": {"kind": "pass_priority", "actor": f"p1:{seen}"},
                                                     "required_facts": []})
            return result
        LA.enumerate_actions = doctored
        try:
            receipt = R.state_receipt(fixture(), hidden_board if "facedown" in label else state, "p1", cat)
        finally:
            LA.enumerate_actions = original
        if receipt["complete"] or not any(w.startswith("depends_on_hidden:") and label in w for w in receipt["why"]):
            fail("R5 hidden", f"{label}: {receipt['why']}")
    # R8: GPT's round-two control - an enumeration that lists one more action only when the opponent's unseen hand card
    # is Twin. The board's card is Zap; the old check's one substitute for Zap was Pawn, and Pawn shows nothing
    r8(cat, state)
    # R6
    original = PT.play_card

    def asks_the_opponent(*args, **kwargs):
        got = original(*args, **kwargs)
        if got.get("reason_code") == "target_selection_required":
            got = {**got, "decision_controller": "p2"}
        return got
    PT.play_card = asks_the_opponent
    try:
        got = PS.enumerate_family("play_card", fixture(), state, "p1", cat)
    finally:
        PT.play_card = original
    if got["status"] != "unproved" or "p2's to decide" not in got["reason"]:
        fail("R6 another", f"{got['status']} {got.get('reason')}")
    return report()


def r8(cat: dict, state: dict) -> None:
    import closed_environment as CE
    original = LA.enumerate_actions

    def twin_reader(observation, actor, catalogue=None, _original=original):
        result = _original(observation, actor, catalogue=catalogue)
        seen = observation["component_states"]["effect_state"]["state"]
        if any(seen["objects"][o].get("card_ref") == "Twin" for o in seen["players"]["p2"]["zones"]["hand"]):
            result["enumeration"]["actions"].append({"candidate_id": "pass_priority:twin", "family": "pass_priority",
                                                     "action": {"kind": "pass_priority", "actor": "p1:twin"},
                                                     "required_facts": []})
        return result

    def holding(ref):
        board = copy.deepcopy(state)
        board["objects"]["oh"] = CE.place(cat, ref, owner="p2", object_id="oh")
        return board
    LA.enumerate_actions = twin_reader
    try:
        zap, pawn, twin = (R.state_receipt(fixture(), holding(ref), "p1", cat) for ref in ("Zap", "Pawn", "Twin"))
        _, zap_true = R.action_keys(fixture(), holding("Zap"), "p1", cat)
        _, pawn_true = R.action_keys(fixture(), holding("Pawn"), "p1", cat)
    finally:
        LA.enumerate_actions = original
    # the gap GPT found: one substitute (Pawn) shows nothing, so trying substitutes could not prove the dimension
    if zap_true != pawn_true:
        fail("R8 Zap / Pawn / Twin", "the control no longer reproduces the gap: Pawn changes the set")
    # the view's set is the same for every card the player cannot see - Twin's included - and Twin's state, whose true
    # set differs, is not complete
    if not (zap["actions"] == pawn["actions"] == twin["actions"]):
        fail("R8 Zap / Pawn / Twin", "the published sets differ with a card the player cannot see")
    if twin["complete"] or not any(w.startswith("depends_on_hidden:the opponent's hand") for w in twin["why"]):
        fail("R8 Zap / Pawn / Twin", f"Twin's state: {twin['complete']} {twin['why']}")
    if not zap["complete"] or not pawn["complete"]:
        fail("R8 Zap / Pawn / Twin", f"Zap's or Pawn's state, whose true set is the view's: {zap['why']} {pawn['why']}")


def report() -> int:
    if errors:
        print("FAILED: the per-state completeness receipt")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a priority point of an environment state with every action kind enumerated and its set independent of "
          "the opponent's hand and the decks' order has a complete receipt; a due procedure, an unproved family, a state "
          "outside the environment, a set reading hidden information, an action naming it, an unvaried private part and a "
          "choice another player makes are each named and the receipt is not complete; the published set is the player's "
          "view's, the same for Zap, Pawn and Twin, and Twin's state is not complete (R1-R8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
