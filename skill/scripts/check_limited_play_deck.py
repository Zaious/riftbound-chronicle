#!/usr/bin/env python3
"""A card taken from a Main Deck, banished, then played from Banishment (package 8, group 3).

Reinforce ("Look at the top 5 cards of your Main Deck. You may banish a unit from among them, then play it, reducing
its cost by [5]. Recycle the remaining cards."), Baited Hook ("Kill a friendly unit. Look at the top 5 cards of your
Main Deck. You may banish a unit from among them that has Might up to 1 more than the killed unit and play it,
ignoring its cost. Then recycle the rest."), Dazzling Aurora ("reveal cards from the top of your Main Deck until you
reveal a unit and banish it. Play it, ignoring its cost, and recycle the rest.") and Blind Fury ("Each opponent
reveals the top card of their Main Deck. Choose one and banish it, then play it, ignoring its cost. Then recycle the
rest."). GPT 2026-10-04 (PACKAGE8_INVENTORY section 6): ruling 4 (another player's card: its owner stays, the player
who plays it controls it, the rest go to each owner's own deck), 6 (Reinforce's reduction is a 356.4 Energy discount,
not below 0, Power still paid), 7 (Baited Hook compares with the killed unit's Might as it died; no unit killed ->
the reference is null, nothing may be chosen by it, the rest is still recycled).

The engine's shape: banish moves the card to its OWNER's Banishment (Core 427, 127.1); limited_play `linked`
{effect_id, from: banishment} plays exactly the card that banish moved, still that object (Core 124) - bound by
the earlier instruction's result, not chosen again; cost bases ignore_all and discount_energy {amount}. A choice
among revealed cards may name a kind and max_might_of {effect_id, plus} (the earlier Kill's might_at_death);
reveal_until reveals from the top until a card of the kind, and banish `linked` takes the card it stopped at.

Held here, each on its own board (this file shares no witness with the trash or hand gates):

  R1 Reinforce      a unit [6][Fury] chosen: banished, played from Banishment paying [1][Fury] (6 - 5); the four
                    other looked-at cards recycled to the bottom of p1's deck in the receipt's order
  R2 floor          a unit [2]: pays nothing of Energy (356.6: not below 0) - its Power cost still paid
  R3 none chosen    nothing banished, nothing played, all five recycled
  R4 forged         a declaration without the effect's discount, or with a larger one, is refused
  H1 Baited Hook    the killed unit had Might 3 (its damage aside): a 4-Might unit may be chosen and is played
                    ignoring its cost; a 5-Might unit is not a candidate
  H2 null           the Kill replaced (the unit saved): no candidate at all, nothing played, and the five
                    looked-at cards are still recycled
  A1 Aurora         two non-units, then a unit, revealed: the unit banished and played ignoring its cost, the two
                    others recycled; the cards below the unit never revealed
  A2 no unit        a deck with no unit: every card revealed, nothing banished or played, all recycled
  B1 Blind Fury     two opponents each reveal their top card; p1 chooses p3's unit: banished to P3's Banishment,
                    played by p1 - p1 controls it, p3 still owns it; p2's card goes back to the bottom of P2's deck
  B2 its leaving    that unit killed afterwards goes to its owner's (p3's) trash
  S  shapes         linked to a non-banish, linked with a choice, a discount of 0, a revealed criterion that is not
                    kind / max_might_of - each refused

    python skill/scripts/check_limited_play_deck.py
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity,  # noqa: E402
                       validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import complete_limited_play, finalize_limited_play, resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
BASE = {"kind": "base"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def program(program_id: str, source: str, effects: list[dict]) -> dict:
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": program_id, "controller": "p1",
            "source_object": source, "effects": effects}


def revealed_choice(ref: str, count: dict, criteria: dict | None = None) -> dict:
    return {"from": "revealed", "selection_kind": "unordered_set", "count": count, "by": "controller",
            "visibility": "private_to_chooser", **({"criteria": criteria} if criteria else {})}


def recycle_rest(ref: str = "rest") -> dict:
    return {"op": "recycle", "effect_id": ref, "player": "p1", "decision_ref": ref, "order_ref": f"{ref}-order",
            "choice": revealed_choice(ref, {"all": True})}


def linked_play(basis: dict, from_effect: str = "ban") -> dict:
    return {"op": "limited_play", "effect_id": "lp", "linked": {"effect_id": from_effect, "from": "banishment"}, "cost_basis": basis}


REINFORCE = program("reinforce-effects", "reinforce", [
    {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 5},
    {"op": "banish", "effect_id": "ban", "player": "p1", "decision_ref": "pick",
     "choice": revealed_choice("pick", {"up_to": 1}, {"kind": "unit"})},
    linked_play({"kind": "discount_energy", "amount": 5}),
    recycle_rest()])
HOOK = program("hook-effects", "hook", [
    {"op": "kill", "effect_id": "kill", "object_id": "u1"},
    {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 5},
    {"op": "banish", "effect_id": "ban", "player": "p1", "decision_ref": "pick",
     "choice": revealed_choice("pick", {"up_to": 1}, {"kind": "unit", "max_might_of": {"effect_id": "kill", "plus": 1}})},
    linked_play({"kind": "ignore_all"}),
    recycle_rest()])
AURORA = program("aurora-effects", "aurora", [
    {"op": "reveal_until", "effect_id": "rev", "player": "p1", "until": {"kind": "unit"}},
    {"op": "banish", "effect_id": "ban", "player": "p1", "linked": {"effect_id": "rev"}},
    linked_play({"kind": "ignore_all"}),
    recycle_rest()])
FURY = program("fury-effects", "fury", [
    {"op": "each_player", "effect_id": "each", "players": "opponents", "order": "turn_order",
     "effects": [{"op": "reveal", "effect_id": "top", "player": "$each_player", "from": "main_deck_top", "count": 1}]},
    {"op": "banish", "effect_id": "ban", "player": "p1", "decision_ref": "pick", "choice": revealed_choice("pick", {"one": True})},
    linked_play({"kind": "ignore_all"}),
    recycle_rest()])


def card(owner: str, kind: str, energy: int, power: dict | None = None, might: int = 0) -> dict:
    return {"owner": owner, "controller": owner, "kind": kind, "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, "printed_cost": {"energy": energy, "power": dict(power or {})}}


def board(source: str, deck: dict[str, dict], *, energy: int = 4, power: dict | None = None, players: int = 2,
          decks: dict[str, dict[str, dict]] | None = None) -> dict:
    """p1's spell `source` in hand ([1] Energy); `deck` on top of p1's Main Deck (or `decks` per player)."""
    state = base_state()
    if players == 3:
        state["players"]["p3"] = copy.deepcopy(state["players"]["p2"])
        state["players"]["p3"]["zones"] = {z: [] for z in state["players"]["p2"]["zones"]}
        state.setdefault("turn_order", ["p1", "p2", "p3"])
        state["turn_order"] = ["p1", "p2", "p3"]
    state["objects"][source] = card("p1", "spell", 1)
    state["players"]["p1"]["zones"]["hand"].append(source)
    for player, cards in (decks or {"p1": deck}).items():
        for oid, obj in cards.items():
            state["objects"][oid] = obj
        state["players"][player]["zones"]["main_deck"] = list(cards) + state["players"][player]["zones"]["main_deck"]
    state["players"]["p1"]["resources"] = {"energy": energy + 1, "power": dict(power or {})}
    problems = validate_state(state)
    assert not problems, problems
    return state


def to_resolution(timing: dict) -> dict:
    if next_procedure(timing).get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in [p for p in ("p1", "p2", "p3")]:
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return timing


def receipt(op_id: str, player: str, permutation: list[str], n: int) -> dict:
    return {"schema_version": "randomization-receipt.v1", "receipt_id": f"rnd-{n}", "operation": "recycle_simultaneous",
            "operation_id": op_id, "player": player, "permutation": list(permutation),
            "provenance": {"provider": "chronicle-harness", "method": "fixed", "seed": "8"}}


def resolve(state: dict, prog: dict, picks: dict[str, list[str]], rest: dict[str, list[str]]) -> dict:
    """Play `prog`'s spell from the hand, resolve it answering each decision from `picks` and each simultaneous
    recycle's random bottom order from `rest` ({player: the cards, in the receipt's order}), then return the result."""
    source = prog["source_object"]
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": f"play-{source}", "actor": "p1",
            "card": source, "effect_program_id": prog["program_id"],
            "chain_item": {"id": f"spell-{source}", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "payment_context": CLOSED}
    timing0 = fixture()
    if "p3" in state["players"]:
        timing0 = {**timing0, "players": ["p1", "p2", "p3"], "turn_order": ["p1", "p2", "p3"]}
    played = play_card(timing0, state, decl, effect_program=prog)
    assert played.get("committed"), (played.get("reason_code"), played.get("reason"))
    timing, eff = to_resolution(played["next_timing_state"]), played["next_effect_state"]
    decisions, receipts = [], []
    for _ in range(8):
        env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(eff), "decisions": list(decisions),
               **({"randomization_receipts": list(receipts)} if receipts else {})}
        done = resolve_with_program(timing, f"spell-{source}", eff, prog, engine_decisions=env if (decisions or receipts) else None)
        if done.get("committed"):
            return done
        er = done.get("effect_result") or {}
        did = (er.get("decision_ids") or [None])[0]
        if er.get("reason_code") == "randomization_receipt_required":
            player = re.search(r"to (p\d)'s Main Deck", er.get("reason") or "").group(1)
            receipts.append(receipt(did, player, rest[player], len(receipts) + 1))
        elif did in picks:
            value = picks[did]
            decisions.append({"decision_id": did, "stage": "resolution", "kind": "card_selection", "controller": "p1",
                              "value": list(value), "selection_identities": {o: object_identity(eff, o) for o in value}})
        elif did == "rest":
            remaining = [o for cards in rest.values() for o in cards]
            decisions.append({"decision_id": did, "stage": "resolution", "kind": "card_selection", "controller": "p1",
                              "value": remaining, "selection_identities": {o: object_identity(eff, o) for o in remaining}})
        else:
            return done
    return done


def limited_item(timing: dict) -> dict | None:
    return next((i for i in timing["chain"]["items"] if i.get("limited_play")), None)


def steps(done: dict) -> list[tuple]:
    return [(s.get("op"), s.get("outcome"), s.get("reason")) for s in (done.get("trace") or {}).get("effect", [])]


def bottom(state: dict, player: str, n: int) -> list[str]:
    return state["players"][player]["zones"]["main_deck"][-n:]


REINFORCE_DECK = {"d1": card("p1", "spell", 1), "d2": card("p1", "unit", 6, {"fury": 1}, might=3), "d3": card("p1", "gear", 1),
                  "d4": card("p1", "unit", 2, might=1), "d5": card("p1", "spell", 1), "d6": card("p1", "unit", 1, might=1)}


def check_reinforce() -> None:
    state = board("reinforce", copy.deepcopy(REINFORCE_DECK), energy=4, power={"fury": 1})
    done = resolve(state, REINFORCE, {"pick": ["d2"]}, {"p1": ["d1", "d3", "d4", "d5"]})
    if not done.get("committed"):
        return fail("R1 Reinforce", f"{done.get('stage')} {done.get('reason')} {steps(done)}")
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    item = limited_item(t1)
    record = ((e1.get("chain_items") or {}).get((item or {}).get("id")) or {}).get("limited_play") or {}
    if record.get("source_zone") != "banishment" or record.get("zone_owner") != "p1" \
            or record.get("cost_basis") != {"kind": "discount_energy", "amount": 5}:
        return fail("R1 Reinforce", f"the card is not on the Chain from p1's Banishment: {record}")
    if bottom(e1, "p1", 4) != ["d1", "d3", "d4", "d5"] or "d6" not in e1["players"]["p1"]["zones"]["main_deck"][:1]:
        fail("R1 recycled", f"the four others are not at the bottom in the receipt's order: {e1['players']['p1']['zones']['main_deck']}")
    completed = complete_limited_play(t1, e1, entry_location=BASE, payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "d2" not in e2["players"]["p1"]["zones"]["base"]:
        return fail("R1 played", f"{completed.get('reason')} {completed.get('message')}")
    if e2["players"]["p1"]["resources"] != {"energy": 3, "power": {"fury": 0}}:
        fail("R1 discount", f"[6][Fury] less [5] Energy should cost [1][Fury]: {e2['players']['p1']['resources']}")
    receipt_ = completed.get("cost_receipt") or {}
    energy = next((c for c in receipt_.get("components", []) if c.get("cost_id") == "base:energy"), {})
    if energy.get("final") != 1 or receipt_.get("after_base_modifications") != receipt_.get("base"):
        fail("R1 discount", f"not a 356.4 discount on the printed base: {energy} {receipt_.get('after_base_modifications')}")
    # R2: a [2] unit - Energy not below 0, Power still paid
    deck = copy.deepcopy(REINFORCE_DECK)
    deck["d4"] = card("p1", "unit", 2, {"calm": 1}, might=1)
    state = board("reinforce", deck, energy=4, power={"calm": 1})
    done = resolve(state, REINFORCE, {"pick": ["d4"]}, {"p1": ["d1", "d2", "d3", "d5"]})
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE, payment_context=CLOSED) \
        if done.get("committed") else {}
    after = (completed.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources")
    if after != {"energy": 4, "power": {"calm": 0}}:
        fail("R2 floor", f"[2][Calm] less [5] should pay no Energy and its Calm: {after} {done.get('reason')} {completed.get('reason')}")
    # R3: none chosen
    state = board("reinforce", copy.deepcopy(REINFORCE_DECK))
    done = resolve(state, REINFORCE, {"pick": []}, {"p1": ["d1", "d2", "d3", "d4", "d5"]})
    if not done.get("committed") or limited_item(done["next_timing_state"]) is not None \
            or bottom(done["next_effect_state"], "p1", 5) != ["d1", "d2", "d3", "d4", "d5"]:
        fail("R3 none", f"{done.get('reason')} {steps(done)}")
    elif ("limited_play", "no_op", "nothing_banished") not in steps(done):
        fail("R3 none", f"the play did not say nothing was banished: {steps(done)}")
    # R4: forged declarations
    state = board("reinforce", copy.deepcopy(REINFORCE_DECK), energy=4, power={"fury": 1})
    done = resolve(state, REINFORCE, {"pick": ["d2"]}, {"p1": ["d1", "d3", "d4", "d5"]})
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    item = limited_item(t1)
    for label, discounts in (("no discount", None), ("a larger one", [{"id": f"limited:{item['id']}", "applies_to": "energy",
                                                                        "amount": 6, "source": "reinforce"}])):
        forged = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "forged", "actor": "p1", "card": "d2",
                  "chain_item": {"id": item["id"], "object_kind": "unit", "timing": "default"},
                  "cost": {"base": {"energy": 6, "power": {"fury": 1}}, **({"discounts": discounts} if discounts else {})},
                  "source": {"kind": "banishment"}, "source_permission": {"granted_by": "reinforce"},
                  "timing_source": "limited_play", "payment_context": CLOSED, "entry_location": BASE}
        if play_card(t1, e1, forged).get("committed"):
            fail("R4 forged", f"a declaration with {label} was accepted")


HOOK_DECK = {"h1": card("p1", "unit", 5, might=4), "h2": card("p1", "unit", 5, might=5), "h3": card("p1", "spell", 1),
             "h4": card("p1", "gear", 1), "h5": card("p1", "spell", 1)}


def check_hook() -> None:
    state = board("hook", copy.deepcopy(HOOK_DECK))
    killed_might = None
    done = resolve(state, HOOK, {"pick": ["h1"]}, {"p1": ["h2", "h3", "h4", "h5"]})
    if not done.get("committed"):
        return fail("H1 Baited Hook", f"{done.get('stage')} {done.get('reason')} {steps(done)}")
    kill = next((s for s in done["trace"]["effect"] if s.get("op") == "kill"), {})
    killed_might = kill.get("might_at_death")
    if killed_might != 3:
        fail("H1 killed Might", f"the Kill did not record the Might it had as it died (3): {killed_might}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE, payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "h1" not in e2["players"]["p1"]["zones"]["base"]:
        fail("H1 played", f"the 4-Might unit was not played: {completed.get('reason')}")
    # a 5-Might unit is not a candidate (3 + 1 = 4)
    wrong = resolve(board("hook", copy.deepcopy(HOOK_DECK)), HOOK, {"pick": ["h2"]}, {"p1": ["h1", "h3", "h4", "h5"]})
    if wrong.get("committed"):
        fail("H1 ceiling", "a 5-Might unit was banished after a 3-Might unit died")
    # H2: the Kill replaced - the unit saved, no unit killed, the reference null
    state = board("hook", copy.deepcopy(HOOK_DECK))
    state["replacement_effects"] = [{"replacement_id": "save", "controller": "p1", "source_object": "u1", "mode": "replace_with",
                                     "event_op": "kill", "optional": False, "uses_remaining": None, "target_object_id": "u1",
                                     "replacement_effects": [{"op": "exhaust", "effect_id": "x", "object_id": "u1"}]}]
    saved = resolve(state, HOOK, {"pick": []}, {"p1": ["h1", "h2", "h3", "h4", "h5"]})
    if not saved.get("committed"):
        return fail("H2 null", f"{saved.get('stage')} {saved.get('reason')} {steps(saved)}")
    e1 = saved["next_effect_state"]
    if "u1" not in e1["players"]["p1"]["zones"]["base"] or limited_item(saved["next_timing_state"]) is not None:
        fail("H2 null", f"the unit was killed or something was played: {steps(saved)}")
    if bottom(e1, "p1", 5) != ["h1", "h2", "h3", "h4", "h5"]:
        fail("H2 null", f"the five looked-at cards were not recycled: {e1['players']['p1']['zones']['main_deck']}")
    asked = resolve(copy.deepcopy(state), HOOK, {"pick": ["h1"]}, {"p1": ["h2", "h3", "h4", "h5"]})
    if asked.get("committed"):
        fail("H2 null", "a unit was chosen by the comparison though no unit was killed")


def check_aurora() -> None:
    deck = {"a1": card("p1", "spell", 1), "a2": card("p1", "gear", 1), "a3": card("p1", "unit", 7, {"order": 2}, might=5),
            "a4": card("p1", "unit", 1, might=1)}
    state = board("aurora", deck)
    done = resolve(state, AURORA, {}, {"p1": ["a1", "a2"]})
    if not done.get("committed"):
        return fail("A1 Aurora", f"{done.get('stage')} {done.get('reason')} {steps(done)}")
    rev = next((s for s in done["trace"]["effect"] if s.get("op") == "reveal_until"), {})
    if [r["object_id"] for r in rev.get("revealed", [])] != ["a1", "a2", "a3"] or rev.get("found") != "a3":
        fail("A1 revealed", f"not the three down to the first unit: {rev.get('revealed')} {rev.get('found')}")
    e1 = done["next_effect_state"]
    if bottom(e1, "p1", 2) != ["a1", "a2"] or e1["players"]["p1"]["zones"]["main_deck"][0] != "a4":
        fail("A1 recycled", f"{e1['players']['p1']['zones']['main_deck']}")
    completed = complete_limited_play(done["next_timing_state"], e1, entry_location=BASE, payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "a3" not in e2["players"]["p1"]["zones"]["base"] \
            or e2["players"]["p1"]["resources"] != e1["players"]["p1"]["resources"]:
        fail("A1 played", f"the unit was not played ignoring its cost: {completed.get('reason')}")
    no_unit = {"n1": card("p1", "spell", 1), "n2": card("p1", "gear", 1)}
    state = board("aurora", no_unit)
    # a deck of only the two non-units: the base board's other deck cards move to the hand
    others = [o for o in state["players"]["p1"]["zones"]["main_deck"] if o not in ("n1", "n2")]
    state["players"]["p1"]["zones"]["hand"].extend(others)
    state["players"]["p1"]["zones"]["main_deck"] = ["n1", "n2"]
    done = resolve(state, AURORA, {}, {"p1": ["n1", "n2"]})
    if not done.get("committed") or limited_item(done["next_timing_state"]) is not None \
            or ("banish", "no_op", None) not in [(a, b, None) for a, b, _c in steps(done)]:
        fail("A2 no unit", f"{done.get('reason')} {steps(done)}")


def check_fury() -> None:
    decks = {"p2": {"o2": card("p2", "spell", 1), "o2b": card("p2", "unit", 1, might=1)},
             "p3": {"o3": card("p3", "unit", 4, {"chaos": 1}, might=3), "o3b": card("p3", "spell", 1)}}
    state = board("fury", {}, players=3, decks=decks)
    done = resolve(state, FURY, {"pick": ["o3"]}, {"p2": ["o2"]})
    if not done.get("committed"):
        return fail("B1 Blind Fury", f"{done.get('stage')} {done.get('reason')} {steps(done)}")
    e1 = done["next_effect_state"]
    reveals = [(s.get("player"), [r["object_id"] for r in s.get("revealed", [])]) for s in done["trace"]["effect"]
               if s.get("op") == "reveal"]
    if reveals != [("p2", ["o2"]), ("p3", ["o3"])]:
        fail("B1 each opponent", f"not exactly each opponent's top card, in Turn Order: {reveals}")
    if e1["players"]["p1"]["zones"]["main_deck"] != state["players"]["p1"]["zones"]["main_deck"]:
        fail("B1 each opponent", "p1's own deck was touched")
    item = limited_item(done["next_timing_state"])
    record = ((e1.get("chain_items") or {}).get((item or {}).get("id")) or {}).get("limited_play") or {}
    if record.get("zone_owner") != "p3" or record.get("source_zone") != "banishment":
        fail("B1 banished", f"the card was not taken from its owner's (p3's) Banishment: {record}")
    if e1["players"]["p2"]["zones"]["main_deck"][0] != "o2b" or bottom(e1, "p2", 1) != ["o2"]:
        fail("B1 rest", f"p2's card did not go to the bottom of p2's own deck: {e1['players']['p2']['zones']['main_deck']}")
    completed = complete_limited_play(done["next_timing_state"], e1, entry_location=BASE, payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "o3" not in e2["players"]["p1"]["zones"]["base"]:
        return fail("B1 played", f"{completed.get('reason')} {completed.get('message')}")
    if e2["objects"]["o3"]["owner"] != "p3" or e2["objects"]["o3"]["controller"] != "p1":
        fail("B1 owner", f"owner {e2['objects']['o3']['owner']} controller {e2['objects']['o3']['controller']}")
    killed = apply_program(e2, program("kill-o3", "u1", [{"op": "kill", "effect_id": "k", "object_id": "o3"}]))
    after = killed.get("next_state") or {}
    if not killed.get("committed") or "o3" not in after["players"]["p3"]["zones"]["trash"]:
        fail("B2 leaving", f"the card did not go to its owner's trash: {killed.get('reason')}")


def check_shapes() -> None:
    bad = {
        "linked to a non-banish": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}, linked_play({"kind": "ignore_all"}, "dr")],
        "a discount of 0": [{"op": "banish", "effect_id": "ban", "objects": ["c1"]}, linked_play({"kind": "discount_energy", "amount": 0})],
    "a choice among revealed cards with a ceiling of another type": [
        {"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 2},
        {"op": "banish", "effect_id": "ban", "player": "p1", "decision_ref": "pick",
         "choice": revealed_choice("pick", {"up_to": 1}, {"kind": "unit", "max_might": "3"})}],
    }
    for label, effects in bad.items():
        prog = program("bad", "x", effects)
        result = apply_program(board("x", {}), prog) if not validate_program(prog) else {"valid": False}
        if result.get("valid") is not False:
            fail("S shapes", f"{label} was accepted")
    chooser = linked_play({"kind": "ignore_all"})
    if not validate_program(program("bad", "x", [{**chooser, "decision_ref": "c"}])):
        fail("S shapes", "linked with a decision_ref validated")
    weird = copy.deepcopy(REINFORCE)
    weird["effects"][1]["choice"]["criteria"] = {"kind": "unit", "max_cost": 3}
    if not validate_program(weird):
        fail("S shapes", "a revealed criterion other than kind / max_might_of validated")
    for prog in (REINFORCE, HOOK, AURORA, FURY):
        if validate_program(prog):
            fail("S shapes", f"{prog['program_id']} does not validate: {validate_program(prog)}")


def main() -> int:
    check_reinforce()
    check_hook()
    check_aurora()
    check_fury()
    check_shapes()
    if errors:
        print("FAILED: a card from a Main Deck, banished, then played from Banishment")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: look / reveal-until / each opponent's reveal -> banish -> play it from its owner's Banishment; a 356.4 Energy "
          "discount not below 0 with Power still paid; the killed unit's Might as it died, null when the Kill was replaced; "
          "another player's card owned by them and controlled by its player; the rest recycled to each owner's deck")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
