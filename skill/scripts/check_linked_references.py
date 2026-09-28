#!/usr/bin/env python3
"""Linked instructions (Core 359.3.e.14): "its" in a later instruction names what an earlier
instruction of the same card acted on.

Three typed references, each naming the earlier instruction by effect_id:

  player {object_player: {effect_id, relation}}   "Its controller draws 2." (Hidden Blade),
                                                   "Its owner channels 1 rune exhausted." (Retreat)
  amount_ref {kind: linked_object_current_might}  "It deals damage equal to its Might ..." (Last
  + source_ref {effect_id}                         Breath) - the object's Might as THIS instruction
                                                   executes (359.3.f.2), and the object is the Deal's
                                                   source, not the spell (417.6.b.3)
  amount_ref {kind: linked_card_printed_energy}   "Deal its Energy cost as damage ..." (Get Excited!)
                                                   - the discarded card's PRINTED Energy cost (206)

Must hold (each on a real apply_program run):
  Hidden Blade   an enemy unit killed: ITS controller (p2) draws 2, p1 draws nothing; a friendly
                 unit killed: p1 draws; a unit p1 controls but p2 owns: p1 (the controller it had
                 when it was killed) draws, and the owner reading would have been p2; the kill
                 mistargeted (the unit moved to its base first): the draw is ignored too
                 (359.3.e.14.a); the kill replaced (a prevent-death replacement): the draw still
                 happens (359.3.e.14.b)
  Retreat        a friendly unit p2 owns returned: it goes to p2's hand and p2 channels 1 rune
                 exhausted, p1 channels nothing; p1's own unit: p1 channels; the return
                 mistargeted: nobody channels
  Last Breath    the readied unit deals its current Might (a +2 given before resolution counts)
                 to the enemy unit, as the source (source_object, responsible player p1); an
                 already-ready unit still deals (the ready executed, it changed nothing); the
                 ready mistargeted: no damage; a unit with 0 Might: no damage (417.1.e)
  Get Excited!   the discarded card's printed Energy (5) is dealt, not the other card's (3); a
                 0-cost card deals nothing; an empty hand ignores the discard and the damage;
                 a card with no observed printed cost is refused by name, never guessed
  gone / many    (review 5 R2-5) "its Might" alone and "it deals 2" alone, the readied unit killed
                 before the Deal: nothing dealt, each by its own reason (on one Deal the two hid
                 each other); a discard of two cards then "its Energy cost": 'its' names one, the
                 Deal is ignored; a token killed (it ceases to exist, 186.1): its controller is
                 read as it stood before the kill and draws
  Repeat         (review 5 R1-4, Core 820.2.a) Hidden Blade twice: each kill's own controller draws;
                 "you may kill" twice: the copy's decision is its own; Last Breath twice: the
                 copy's Might and source are its own readied unit's
  validator      a reference to a later or unknown instruction, an unknown relation, source_ref
                 on another op, source_ref with source_object - each refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program, validate_state  # noqa: E402

UNIT = {"kind": "unit", "might_modifiers": [], "damage": 0, "exhausted": False}


def board() -> dict:
    """u1 (p1, Might 3) and u2 (p2, Might 4) at bf1; s1 - a unit p1 controls and p2 OWNS - at
    bf1 too; both players with a deck and runes; p1 holds two cards with printed costs."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["objects"]["u1"]["damage"] = 0
    state["objects"]["s1"] = {**UNIT, "owner": "p2", "controller": "p1", "base_might": 2}
    state["battlefields"]["bf1"]["objects"] += ["u1", "u2", "s1"]
    for player, prefix in (("p1", "a"), ("p2", "b")):
        deck = state["players"][player]["zones"]["main_deck"]
        for n in range(3):
            card = f"{prefix}deck{n}"
            state["objects"][card] = {**UNIT, "kind": "spell", "owner": player, "controller": player, "base_might": 0}
            deck.append(card)
        runes = state["players"][player]["zones"]["rune_deck"]
        for n in range(2):
            rune = f"{prefix}rune{n}"
            state["objects"][rune] = {**UNIT, "kind": "rune", "owner": player, "controller": player, "base_might": 0}
            runes.append(rune)
    for card, energy in (("h5", 5), ("h3", 3), ("h0", 0)):
        state["objects"][card] = {**UNIT, "kind": "spell", "owner": "p1", "controller": "p1", "base_might": 0,
                                  "printed_cost": {"energy": energy, "power": {}}}
    state["players"]["p1"]["zones"]["hand"] += ["h5", "h3"]
    state["players"]["p1"]["zones"]["banishment"].append("h0")
    return settle_contested(state)


def target(state: dict, object_id: str, **criteria) -> dict:
    return {"object_id": object_id, "chosen_zone_class": "board", "kind": "unit",
            "bound_identity": object_identity(state, object_id) or f"{object_id}@0", **criteria}


def hand(state, player):
    return len(state["players"][player]["zones"]["hand"])


def runes_in_base(state, player):
    return [o for o in state["players"][player]["zones"]["base"] if state["objects"][o]["kind"] == "rune"]


def run(state, *effects, decisions=None):
    doc = program("linked", *copy.deepcopy(list(effects)))
    envelope = None
    if decisions:
        envelope = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": decisions}
    return apply_program(state, doc, decisions=envelope)


def event(result, effect_id):
    return next((e for e in result.get("trace") or [] if e.get("effect_id") == effect_id), {})


def hidden_blade(state, victim, relation="controller"):
    kill = {"op": "kill", "effect_id": "kl", "target": target(state, victim, location="battlefield")}
    draw = {"op": "draw", "effect_id": "dr", "count": 2,
            "player": {"object_player": {"effect_id": "kl", "relation": relation}}}
    return run(state, kill, draw)


def retreat(state, unit, relation="owner"):
    ret = {"op": "return_to_hand", "effect_id": "ret", "target": target(state, unit, controller_relation="friendly")}
    ch = {"op": "channel_rune", "effect_id": "ch", "count": 1, "entry_state": "exhausted",
          "player": {"object_player": {"effect_id": "ret", "relation": relation}}}
    return run(state, ret, ch)


def last_breath(state, unit, enemy="u2"):
    ready = {"op": "ready", "effect_id": "rd", "target": target(state, unit, controller_relation="friendly")}
    deal = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "linked_object_current_might", "effect_id": "rd"},
            "source_ref": {"effect_id": "rd"}, "target": target(state, enemy, controller_relation="enemy", location="battlefield")}
    return run(state, ready, deal)


def get_excited(state, card, victim="u2"):
    discard = {"op": "discard", "effect_id": "d", "player": "p1", "count": 1, "decision_ref": "pick"}
    deal = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "linked_card_printed_energy", "effect_id": "d"},
            "target": target(state, victim, location="battlefield")}
    decisions = None
    if card is not None:
        decisions = [{"decision_id": "pick", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                      "value": [card], "selection_identities": {card: object_identity(state, card) or f"{card}@0"}}]
    return run(state, discard, deal, decisions=decisions)


def repeat_cases(errors: list[str], start: dict, tired: dict) -> None:
    """Core 820.2.a: a Repeat execution makes its own choices, and its linked references name its
    OWN earlier instruction (review 5 R1-4)."""
    def pick(state, ref, object_id):
        return {"decision_id": ref, "kind": "target_selection", "stage": "play_declaration", "controller": "p1",
                "value": [object_id], "selection_identities": {object_id: object_identity(state, object_id)}}

    def repeated(state, effects, decisions):
        envelope = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": decisions}
        return apply_program(state, program("repeat", *copy.deepcopy(effects)), decisions=envelope,
                             context={"repeat": {"executions": 2}})

    # Hidden Blade twice: the first kills p2's u2, the copy p1's u1 - each 'its controller' draws 2
    kill = {"op": "kill", "effect_id": "kl", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                                        "location": "battlefield"}}
    draw = {"op": "draw", "effect_id": "dr", "count": 2, "player": {"object_player": {"effect_id": "kl", "relation": "controller"}}}
    got = repeated(start, [kill, draw], [pick(start, "t", "u2"), pick(start, "t#1", "u1")])
    if not got.get("committed") or hand(got["next_state"], "p1") != hand(start, "p1") + 2 \
            or hand(got["next_state"], "p2") != hand(start, "p2") + 2:
        errors.append(f"Hidden Blade repeated (u2, then u1): each kill's controller draws 2 - the copy's 'its' names "
                      f"the copy's kill: {got.get('reason') or got.get('errors')} "
                      f"{[(e.get('effect_id'), (e.get('player_read') or {}).get('object_id')) for e in got.get('trace') or []]}")
    # an optional instruction repeated: the copy decides for itself - kill u2, decline the copy
    may_kill = {**kill, "optional": {"decision_ref": "may"}}
    decisions = [pick(start, "t", "u2"), pick(start, "t#1", "u1"),
                 {"decision_id": "may", "kind": "optional_choice", "stage": "resolution", "controller": "p1", "value": True},
                 {"decision_id": "may#1", "kind": "optional_choice", "stage": "resolution", "controller": "p1", "value": False}]
    got = repeated(start, [may_kill], decisions)
    if not got.get("committed") or "u2" in got["next_state"]["battlefields"]["bf1"]["objects"] \
            or "u1" not in got["next_state"]["battlefields"]["bf1"]["objects"]:
        errors.append(f"'you may kill' repeated, the first accepted and the copy declined: u2 dies, u1 stays: "
                      f"{got.get('reason') or got.get('errors')}")
    # Last Breath twice: the copy readies s1 (Might 2) and IT deals its Might - 3 + 2, not 3 + 3
    both = copy.deepcopy(tired)
    both["objects"]["s1"]["exhausted"] = True
    ready_t = {"op": "ready", "effect_id": "rd", "target": {"decision_ref": "r", "chosen_zone_class": "board", "kind": "unit",
                                                            "controller_relation": "friendly"}}
    deal_t = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "linked_object_current_might", "effect_id": "rd"},
              "source_ref": {"effect_id": "rd"}, "target": {"decision_ref": "e", "chosen_zone_class": "board", "kind": "unit",
                                                            "controller_relation": "enemy", "location": "battlefield"}}
    got = repeated(both, [ready_t, deal_t], [pick(both, "r", "u1"), pick(both, "e", "u2"), pick(both, "r#1", "s1"),
                                             pick(both, "e#1", "u2")])
    sources = [e.get("source_object") for e in got.get("trace") or [] if e.get("op") == "deal_damage"]
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 5 or sources != ["u1", "s1"]:
        errors.append(f"Last Breath repeated (u1, then s1): 3 + 2 dealt, by u1 then s1: "
                      f"{(got.get('next_state') or {}).get('objects', {}).get('u2')} {sources} {got.get('reason') or got.get('errors')}")


def main() -> int:
    errors: list[str] = []
    start = board()
    if validate_state(start):
        print(f"FAILED: the board is invalid: {validate_state(start)}")
        return 1

    # --- Hidden Blade ------------------------------------------------------------------------
    got = hidden_blade(start, "u2")
    after = got.get("next_state") or {}
    if not got.get("committed") or hand(after, "p2") != hand(start, "p2") + 2 or hand(after, "p1") != hand(start, "p1") \
            or event(got, "dr").get("player_read", {}).get("player") != "p2":
        errors.append(f"an enemy unit killed: its controller p2 did not draw 2 ({got.get('reason') or got.get('errors')})")
    got = hidden_blade(start, "u1")
    if not got.get("committed") or hand(got["next_state"], "p1") != hand(start, "p1") + 2:
        errors.append("a friendly unit killed: p1 did not draw 2")
    got = hidden_blade(start, "s1")
    if not got.get("committed") or hand(got["next_state"], "p1") != hand(start, "p1") + 2 \
            or hand(got["next_state"], "p2") != hand(start, "p2"):
        errors.append("a unit p1 controls and p2 owns was killed: p1 (its controller when killed) should draw 2")
    if "s1" not in got.get("next_state", {}).get("players", {}).get("p2", {}).get("zones", {}).get("trash", []):
        errors.append("the killed unit p2 owns is not in p2's trash")
    owner_read = hidden_blade(start, "s1", relation="owner")
    if not owner_read.get("committed") or hand(owner_read["next_state"], "p2") != hand(start, "p2") + 2:
        errors.append("the owner reading of the same kill should have been p2 (the relation is read, not assumed)")
    moved = copy.deepcopy(start)
    moved["battlefields"]["bf1"]["objects"].remove("u2")
    moved["players"]["p2"]["zones"]["base"].append("u2")
    got = hidden_blade(moved, "u2")
    if not got.get("committed") or hand(got["next_state"], "p2") != hand(moved, "p2") \
            or event(got, "dr").get("outcome") != "skipped_linked_dependency" \
            or event(got, "kl").get("outcome") != "ignored_illegal_target":
        errors.append(f"the kill mistargeted: the draw must be ignored too (359.3.e.14.a): {[e.get('outcome') for e in got.get('trace') or []]}")
    guarded = copy.deepcopy(start)
    guarded["replacement_effects"] = [{"replacement_id": "guard", "controller": "p2", "source_object": "u2",
                                       "mode": "prevent_event", "event_op": "kill", "optional": False,
                                       "uses_remaining": 1, "target_object_id": "u2"}]
    got = hidden_blade(guarded, "u2")
    if not got.get("committed") or hand(got["next_state"], "p2") != hand(guarded, "p2") + 2 \
            or "u2" not in got["next_state"]["battlefields"]["bf1"]["objects"]:
        errors.append(f"the kill replaced: the draw still happens (359.3.e.14.b): "
                      f"{[e.get('outcome') for e in got.get('trace') or []]} {got.get('reason') or got.get('errors')}")

    # --- Retreat -----------------------------------------------------------------------------
    got = retreat(start, "s1")
    after = got.get("next_state") or {}
    if not got.get("committed") or "s1" not in after["players"]["p2"]["zones"]["hand"] \
            or len(runes_in_base(after, "p2")) != len(runes_in_base(start, "p2")) + 1 \
            or len(runes_in_base(after, "p1")) != len(runes_in_base(start, "p1")) \
            or not all(after["objects"][r]["exhausted"] for r in runes_in_base(after, "p2")):
        errors.append(f"a friendly unit p2 owns returned: p2 should channel 1 exhausted, p1 nothing "
                      f"({got.get('reason') or got.get('errors')})")
    wrong = retreat(start, "s1", relation="controller")
    if wrong.get("committed") and len(runes_in_base(wrong["next_state"], "p2")) != len(runes_in_base(start, "p2")):
        errors.append("the controller reading of Retreat still channelled for p2 - the relation is not read")
    got = retreat(start, "u1")
    if not got.get("committed") or len(runes_in_base(got["next_state"], "p1")) != len(runes_in_base(start, "p1")) + 1:
        errors.append("p1's own unit returned: p1 should channel 1")
    stolen_back = copy.deepcopy(start)
    stolen_back["objects"]["s1"]["controller"] = "p2"      # no longer friendly when Retreat resolves
    stolen_back = settle_contested(stolen_back)
    got = retreat(stolen_back, "s1")
    if not got.get("committed") or event(got, "ch").get("outcome") != "skipped_linked_dependency" \
            or len(runes_in_base(got["next_state"], "p2")) != len(runes_in_base(stolen_back, "p2")):
        errors.append(f"the return mistargeted: nobody channels (359.3.e.14.a): {[e.get('outcome') for e in got.get('trace') or []]}")

    # --- Last Breath -------------------------------------------------------------------------
    tired = copy.deepcopy(start)
    tired["objects"]["u1"]["exhausted"] = True
    got = last_breath(tired, "u1")
    dealt = event(got, "dmg")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 3 \
            or dealt.get("source_object") != "u1" or dealt.get("responsible_player") != "p1" \
            or got["next_state"]["objects"]["u1"]["exhausted"]:
        errors.append(f"Last Breath: the readied u1 (Might 3) should deal 3 to u2 as the source: {dealt} "
                      f"{got.get('reason') or got.get('errors')}")
    pumped = copy.deepcopy(tired)
    pumped["continuous_effects"] = [{"effect_id": "pump", "kind": "might_arithmetic", "source": {"object": "u1", "identity": None, "name": "pump"},
                                     "affects": {"scope": "object", "object": "u1", "identity": object_identity(pumped, "u1") or "u1@0"},
                                     "layer": "arithmetic", "sublayer": "increase", "timestamp": 1, "value": {"amount": 2, "mode": "delta"},
                                     "duration": {"kind": "permanent"}, "passive": False}]
    got = last_breath(pumped, "u1")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 5:
        errors.append(f"Last Breath: the Might is read as the damage executes (359.3.f.2) - 5, not 3: "
                      f"{(got.get('next_state') or {}).get('objects', {}).get('u2')} {got.get('reason') or got.get('errors')}")
    # read when the Deal executes, not when the ready did: a +2 given BETWEEN the two counts
    ready = {"op": "ready", "effect_id": "rd", "target": target(tired, "u1", controller_relation="friendly")}
    between = {"op": "modify_might", "effect_id": "mm", "object_id": "u1", "amount": 2, "duration": "this_turn", "source": "linked"}
    deal = {"op": "deal_damage", "effect_id": "dmg", "amount_ref": {"kind": "linked_object_current_might", "effect_id": "rd"},
            "source_ref": {"effect_id": "rd"}, "target": target(tired, "u2", controller_relation="enemy", location="battlefield")}
    got = run(tired, ready, between, deal)
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 5:
        errors.append(f"Last Breath: a +2 given after the ready and before the Deal must count (359.3.f.2): "
                      f"{(got.get('next_state') or {}).get('objects', {}).get('u2')} {got.get('reason') or got.get('errors')}")
    # the unit gone before the Deal executes: its Might and the source read null (359.3.e.12)
    killed = {"op": "kill", "effect_id": "kl", "object_id": "u1"}
    got = run(tired, ready, killed, deal)
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 0 \
            or event(got, "dmg").get("outcome") != "no_op":
        errors.append(f"Last Breath: the unit left the board before the Deal - nothing is dealt (359.3.e.12): "
                      f"{[(e.get('effect_id'), e.get('outcome'), e.get('reason')) for e in got.get('trace') or []]}")
    got = last_breath(start, "u1")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 3:
        errors.append("Last Breath: an already-ready unit still deals its Might (the ready executed and changed nothing)")
    gone = copy.deepcopy(tired)
    gone["objects"]["u1"]["controller"] = "p2"
    gone = settle_contested(gone)
    got = last_breath(gone, "u1")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 0 \
            or event(got, "dmg").get("outcome") != "skipped_linked_dependency":
        errors.append(f"Last Breath: the ready mistargeted - no damage (359.3.e.14.a): {[e.get('outcome') for e in got.get('trace') or []]}")
    weak = copy.deepcopy(tired)
    weak["objects"]["u1"]["base_might"] = 0
    got = last_breath(weak, "u1")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 0 \
            or event(got, "dmg").get("outcome") != "no_op":
        errors.append("Last Breath: a 0 Might unit deals nothing (417.1.e)")

    # --- Get Excited! ------------------------------------------------------------------------
    got = get_excited(start, "h5")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 5 \
            or "h5" not in got["next_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append(f"Get Excited!: the discarded card's printed Energy 5 should be dealt: "
                      f"{(got.get('next_state') or {}).get('objects', {}).get('u2')} {got.get('reason') or got.get('errors')}")
    got = get_excited(start, "h3")
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 3:
        errors.append("Get Excited!: discarding the 3-cost card should deal 3 (it is the discarded card's cost, not any card's)")
    zero = copy.deepcopy(start)
    zero["players"]["p1"]["zones"]["banishment"].remove("h0")
    zero["players"]["p1"]["zones"]["banishment"] += ["h5", "h3"]
    zero["players"]["p1"]["zones"]["hand"] = ["h0"]
    got = get_excited(zero, None)
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 0 or event(got, "dmg").get("outcome") != "no_op":
        errors.append(f"Get Excited!: a 0-cost card deals nothing: {[e.get('outcome') for e in got.get('trace') or []]}")
    empty = copy.deepcopy(start)
    empty["players"]["p1"]["zones"]["banishment"] += ["h5", "h3"]
    empty["players"]["p1"]["zones"]["hand"] = []
    got = get_excited(empty, None)
    if not got.get("committed") or event(got, "dmg").get("outcome") != "skipped_linked_dependency":
        errors.append(f"Get Excited!: an empty hand ignores the discard and the damage (422.4, 359.3.e.14.a): "
                      f"{[e.get('outcome') for e in got.get('trace') or []]}")
    blank = copy.deepcopy(start)
    blank["objects"]["h5"].pop("printed_cost")
    got = get_excited(blank, "h5")
    if got.get("committed") or not got.get("unsupported"):
        errors.append("Get Excited!: a card with no observed printed cost must be refused, never guessed")

    # --- the linked object gone, each reference on its own (review 5 R2-5) ------------------------
    # The case above has both references on one Deal, and whichever is checked first hides the
    # other. Apart: "deal damage equal to its Might" (amount only) and "it deals 2" (source only),
    # the readied unit killed before the Deal - neither reads the unit in its trash (359.3.e.12)
    enemy = target(tired, "u2", controller_relation="enemy", location="battlefield")
    for label, deal_only, reason in (
            ("its Might", {"op": "deal_damage", "effect_id": "dmg", "target": enemy,
                           "amount_ref": {"kind": "linked_object_current_might", "effect_id": "rd"}}, "amount_ref_null"),
            ("it deals", {"op": "deal_damage", "effect_id": "dmg", "target": enemy, "amount": 2,
                          "source_ref": {"effect_id": "rd"}}, "source_ref_object_unavailable")):
        alive = run(tired, ready, deal_only)
        got = run(tired, ready, killed, deal_only)
        if not alive.get("committed") or alive["next_state"]["objects"]["u2"]["damage"] == 0:
            errors.append(f"linked '{label}' alone: the unit still there dealt nothing - the case does not bite")
        if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 0 \
                or event(got, "dmg").get("reason") != reason:
            errors.append(f"linked '{label}' alone, the unit killed before the Deal: nothing is dealt ({reason}, 359.3.e.12): "
                          f"{[(e.get('effect_id'), e.get('outcome'), e.get('reason')) for e in got.get('trace') or []]}")
    # the linked instruction acted on two objects: "its" names one, so the later one is ignored
    # ("Discard 2. Deal its Energy cost ..." is not a card; it is the shape the reference refuses)
    two = [{"decision_id": "pick", "stage": "resolution", "kind": "card_selection", "controller": "p1",
            "value": ["h5", "h3"], "selection_identities": {c: object_identity(start, c) for c in ("h5", "h3")}}]
    got = run(start, {"op": "discard", "effect_id": "d", "player": "p1", "count": 2, "decision_ref": "pick"},
              {"op": "deal_damage", "effect_id": "dmg", "target": target(start, "u2", location="battlefield"),
               "amount_ref": {"kind": "linked_card_printed_energy", "effect_id": "d"}}, decisions=two)
    if not got.get("committed") or got["next_state"]["objects"]["u2"]["damage"] != 0 \
            or event(got, "dmg").get("outcome") != "skipped_linked_dependency":
        errors.append(f"'its Energy cost' after a discard of two cards: 'its' names one, the Deal is ignored: "
                      f"{[(e.get('effect_id'), e.get('outcome')) for e in got.get('trace') or []]}")
    # the killed unit was a token, which ceased to exist (186.1): 'its controller' is read as it
    # stood BEFORE the kill (the token is not in the state after it), so p2 still draws 2
    token = copy.deepcopy(start)
    token["objects"]["tk"] = {**UNIT, "owner": "p2", "controller": "p2", "base_might": 1, "is_token": True}
    token["battlefields"]["bf1"]["objects"].append("tk")
    token = settle_contested(token)
    got = hidden_blade(token, "tk")
    if not got.get("committed") or hand(got["next_state"], "p2") != hand(token, "p2") + 2 or "tk" in got["next_state"]["objects"]:
        errors.append(f"a token killed: its controller p2 (read before the kill) should draw 2: "
                      f"{got.get('reason') or got.get('errors')}")
    repeat_cases(errors, start, tired)

    # --- validator ---------------------------------------------------------------------------
    later = program("v", {"op": "draw", "effect_id": "dr", "count": 1, "player": {"object_player": {"effect_id": "kl", "relation": "controller"}}},
                    {"op": "kill", "effect_id": "kl", "object_id": "u2"})
    if not validate_program(later):
        errors.append("a player read off a LATER instruction validated")
    odd = program("v", {"op": "kill", "effect_id": "kl", "object_id": "u2"},
                  {"op": "draw", "effect_id": "dr", "count": 1, "player": {"object_player": {"effect_id": "kl", "relation": "master"}}})
    if not validate_program(odd):
        errors.append("an unknown relation validated")
    stray = program("v", {"op": "ready", "effect_id": "rd", "object_id": "u1"},
                    {"op": "kill", "effect_id": "kl", "object_id": "u2", "source_ref": {"effect_id": "rd"}})
    if not validate_program(stray):
        errors.append("source_ref on a kill validated")
    both = program("v", {"op": "ready", "effect_id": "rd", "object_id": "u1"},
                   {"op": "deal_damage", "effect_id": "dm", "object_id": "u2", "amount": 1, "source_ref": {"effect_id": "rd"}, "source_object": "u1"})
    if not validate_program(both):
        errors.append("source_ref with source_object validated")
    unknown = program("v", {"op": "deal_damage", "effect_id": "dm", "object_id": "u2",
                            "amount_ref": {"kind": "linked_object_current_might", "effect_id": "nowhere"}})
    if not validate_program(unknown):
        errors.append("a linked amount_ref naming no earlier instruction validated")

    if errors:
        print("FAILED: linked references" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'its controller' / 'its owner' / 'its Might' (as the source) / 'its Energy cost' read the object the "
          "earlier instruction acted on (359.3.e.14): Hidden Blade, Retreat, Last Breath and Get Excited! each on "
          "its real board, the ignored link ignores the later instruction (14.a), a replaced kill still links (14.b), "
          "stolen units split controller from owner, and the validator refuses the malformed shapes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
