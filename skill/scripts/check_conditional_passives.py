#!/usr/bin/env python3
"""
Regression gate: a card's conditional passives and Might read off a count (2026-09-27).

Core 364.3.a: "if" or "while" marks a conditional passive ability. The card carries:
  - `conditional_keywords` - a keyword it has only while its condition holds, a keyword_grant on
    itself in the Ability layer (477.2), read live like a printed aura;
  - `conditional_might` with the new leaf `is_buffed` ("I have an additional +1 [M]");
  - `dynamic_might` per two new counts: buffed friendly Units at its Battlefield, and the cards
    in its controller's Trash (477.3.b: read fresh, never snapshotted).
Conditions: `is_buffed` (702.2.a), `cards_discarded_this_turn_at_least` over a per-turn ledger
the discard instruction and a Discard cost both write (422.1, 422.3), and `might_at_least` on the
card itself - Mighty (708) - read from the layer result in progress (476.2, 476.3), never through
effective_might, which is the function computing it (the old path recursed forever).

Must hold:
  - buffed: Ganking only while this Unit has a Buff counter - a real Battlefield-to-Battlefield
    Standard Move commits buffed, is refused unbuffed, refused when only another friendly Unit is
    buffed, and refused after the Buff is spent as a real cost; +1 Might on top of the Buff's own;
  - discarded: [Assault] and [Ganking] only after its controller discarded this turn - by the
    discard instruction or as a Discard cost; not when only the opponent discarded, not on a
    later turn; Assault counts while it is the Attacker; the ledger shape is validated;
  - Mighty, read per 476.2-476.3: printed 4 + a Buff is 5 with Deflect, Ganking and Shield,
    6 as a Defender; the same Unit without the Buff is 4 with none; plus the orders the layers
    fix: a Buff and -1 leave it at 4 with none, as a Defender too (the Ability layer first sees
    4, so no Shield props it up), +1 this turn
    makes it Mighty, a Shield from elsewhere as a Defender makes 5 and then 6 with Shield 2, and
    a printed-5 Unit given -1 is disqualified once (4, none); Deflect then costs an opponent's
    spell choosing it 1 Power (809.1.c), Ganking moves it Battlefield to Battlefield;
  - counts: buffed friendly Units at its Battlefield, itself included, none from a Base, enemy
    Units and Units elsewhere not counted; its controller's Trash only, read fresh;
  - invalid: a conditional keyword about another object, with an unknown condition, with a
    keyword the engine does not read, a value on Ganking; an unknown count;
  - mutations caught: the Buff read before the first Arithmetic layer, no disqualification,
    is_buffed read off any friendly Unit, every player's discards counted, the count excluding
    its source.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from combat import STANDARD_MOVE_DECLARATION_VERSION, standard_move  # noqa: E402
from effect_ir import apply_program, effective_might, has_keyword, keyword_values, object_identity, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

MIGHTY = {"kind": "might_at_least", "count": 5}
BUFFED = {"kind": "is_buffed"}
DISCARDED = {"kind": "cards_discarded_this_turn_at_least", "count": 1}


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [],
            "damage": 0, "exhausted": False, **extra}


def conditional(keywords, condition):
    return [{"modifier_id": f"own-text-{k}", "keyword": k, "condition": dict(condition)} for k in keywords]


def at_bf1(state, *units, controller="p1"):
    """The Units at bf1 (p1's), bf2 empty and uncontrolled."""
    state["battlefields"]["bf1"] = {"controller": controller, "objects": list(units)}
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    return state


def move(state, mover, destination="bf2"):
    return standard_move(fixture(), state, {
        "schema_version": STANDARD_MOVE_DECLARATION_VERSION, "actor": "p1", "units": [mover],
        "destination": {"kind": "battlefield", "battlefield": destination},
        "unit_identities": {mover: object_identity(state, mover) or f"{mover}@0"},
        "cost_confirmation": {"exhaust_confirmed": True}})


def spend_buff(state, object_id):
    """p1 plays c1 (a spell) whose cost spends the Buff on `object_id` (702.2.b)."""
    state = copy.deepcopy(state)
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": "p1", "card": "c1",
                "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
                "cost": {"base": {"energy": 0, "power": {}},
                         "additional": [{"cost_id": "bf", "mandatory": True, "payment": {"kind": "spend_buff", "object_id": object_id}}]}}
    played = PT.play_card(fixture(), state, declared)
    return played["next_effect_state"] if played.get("committed") else None


# ------------------------------------------------------------------ "While I'm buffed"
def bully(*, buffed=False, other_buffed=False, elder=False):
    state = at_bf1(base_state(), "bb", "f1")
    fields = ({"conditional_might": [{"modifier_id": "clause", "amount": 1, "condition": dict(BUFFED)}]} if elder
              else {"conditional_keywords": conditional(["ganking"], BUFFED)})
    state["objects"]["bb"] = unit("p1", 2, **fields, **({"buffed": True} if buffed else {}))
    state["objects"]["f1"] = unit("p1", 2, **({"buffed": True} if other_buffed else {}))
    return state


def check_buffed(errors):
    runs = {}
    for label, state in (("buffed", bully(buffed=True)), ("unbuffed", bully()), ("only_another_buffed", bully(other_buffed=True))):
        if found := validate_state(state):
            errors.append(f"the {label} board is invalid: {found}")
            return
        moved = move(state, "bb")
        runs[label] = moved.get("reason_code") if not moved.get("committed") else "moved"
    spent = spend_buff(bully(buffed=True), "bb")
    runs["buff_spent"] = None if spent is None else (move(spent, "bb").get("reason_code") or "moved")
    want = {"buffed": "moved", "unbuffed": "ganking_required", "only_another_buffed": "ganking_required", "buff_spent": "ganking_required"}
    if runs != want:
        errors.append(f"'While I'm buffed, I have [Ganking]' moved the wrong times: {runs}")
    mights = {"buffed": effective_might(bully(buffed=True, elder=True), "bb"), "unbuffed": effective_might(bully(elder=True), "bb"),
              "only_another_buffed": effective_might(bully(other_buffed=True, elder=True), "bb")}
    spent = spend_buff(bully(buffed=True, elder=True), "bb")
    mights["buff_spent"] = effective_might(spent, "bb") if spent else None
    if mights != {"buffed": 4, "unbuffed": 2, "only_another_buffed": 2, "buff_spent": 2}:
        errors.append(f"'While I'm buffed, I have an additional +1 [M]' read wrong (2 printed, +1 Buff, +1): {mights}")


# ------------------------------------------------------------------ "If you've discarded a card this turn"
def soul():
    state = base_state()
    state["objects"]["rs"] = unit("p1", 2, conditional_keywords=conditional(["assault", "ganking"], DISCARDED))
    state["players"]["p1"]["zones"]["base"].append("rs")
    for owner, card in (("p1", "c2"), ("p2", "c4")):
        state["players"][owner]["zones"]["main_deck"].remove(card)
        state["players"][owner]["zones"]["hand"].append(card)
    return state


def discard(state, player):
    done = apply_program(state, program(f"d-{player}", {"op": "discard", "player": player, "count": 1, "effect_id": "d"}))
    return done["next_state"] if done.get("committed") else None


def discard_as_cost(state):
    state = copy.deepcopy(state)
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "play_id": "play-1", "actor": "p1", "card": "c1",
                "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
                "cost": {"base": {"energy": 0, "power": {}},
                         "additional": [{"cost_id": "d", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]}}
    played = PT.play_card(fixture(), state, declared)
    return played["next_effect_state"] if played.get("committed") else None


def attacking(state, oid):
    """`oid` alone as the Attacker at bf1 against p2's u2."""
    state = copy.deepcopy(state)
    state["players"]["p1"]["zones"]["base"].remove(oid)
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["battlefields"]["bf1"] = {"controller": "p2", "objects": [oid, "u2"], "contested": True, "contested_by": "p1"}
    state["objects"][oid]["combat_designation"] = {"combat_id": "cb1", "role": "attacker"}
    state["objects"]["u2"]["combat_designation"] = {"combat_id": "cb1", "role": "defender"}
    return state


def check_discarded(errors):
    fresh = soul()
    by_op = discard(fresh, "p1")
    by_cost = discard_as_cost(fresh)
    theirs = discard(fresh, "p2")
    later = copy.deepcopy(by_op) if by_op else None
    if later:
        later["turn_id"] = "turn-9"
    boards = {"none": fresh, "by_the_discard_instruction": by_op, "as_a_discard_cost": by_cost,
              "only_the_opponent": theirs, "on_a_later_turn": later}
    got = {}
    for label, state in boards.items():
        if state is None or validate_state(state):
            errors.append(f"the {label} discard board did not build: {state and validate_state(state)}")
            return
        values = keyword_values(state, "rs")
        got[label] = sorted(k for k in ("assault", "ganking") if k in values)
    want = {"none": [], "by_the_discard_instruction": ["assault", "ganking"], "as_a_discard_cost": ["assault", "ganking"],
            "only_the_opponent": [], "on_a_later_turn": []}
    if got != want:
        errors.append(f"'If you've discarded a card this turn, I have [Assault] and [Ganking]' read wrong: {got}")
    if by_op and IR.cards_discarded_this_turn(by_op, "p1") != ["c2"]:
        errors.append(f"the discard instruction did not record its card: {IR.cards_discarded_this_turn(by_op, 'p1')}")
    if by_cost and IR.cards_discarded_this_turn(by_cost, "p1") != ["c2"]:
        errors.append(f"the Discard cost did not record its card: {IR.cards_discarded_this_turn(by_cost, 'p1')}")
    mights = {"discarded": effective_might(attacking(by_op, "rs"), "rs"), "not": effective_might(attacking(fresh, "rs"), "rs")}
    if mights != {"discarded": 3, "not": 2}:
        errors.append(f"the conditional [Assault] did not count while the Unit is the Attacker (807.1.c): {mights}")
    for bad in ({"turn-0": "c2"}, {"turn-0": ["nope"]}, ["c2"]):
        broken = copy.deepcopy(by_op)
        broken["players"]["p1"]["cards_discarded_this_turn"] = bad
        if not validate_state(broken):
            errors.append(f"an invalid discard ledger validated: {bad}")


# ------------------------------------------------------------------ "While I'm [Mighty]"
def fiora(*, printed=4, buffed=False, role=None, delta=None, shield_aura=False):
    """The Unit at bf1 (p1's) with "While I'm [Mighty], I have [Deflect], [Ganking], and [Shield].";
    as the Attacker / Defender against p2's u2 when `role` is given; `delta` a Might modifier this
    turn; with p1's t1 beside it granting "Other friendly units here have [Shield]." when asked."""
    state = base_state()
    here = ["fi"] + (["t1"] if shield_aura else [])
    state["objects"]["fi"] = unit("p1", printed, conditional_keywords=conditional(["deflect", "ganking", "shield"], MIGHTY),
                                  **({"buffed": True} if buffed else {}))
    if delta is not None:
        state["objects"]["fi"]["might_modifiers"] = [{"amount": delta, "duration": "this_turn", "source": "spell-x"}]
    if shield_aura:
        state["objects"]["t1"] = unit("p1", 1, static_auras=[{"aura_id": "here-shield", "keyword": "shield", "criteria": {
            "kind": "unit", "controller_relation": "friendly", "exclude_source": True, "at_source_battlefield": True}}])
    if role:
        state["players"]["p2"]["zones"]["base"].remove("u2")
        here.append("u2")
        for oid in here[:-1]:
            state["objects"][oid]["combat_designation"] = {"combat_id": "cb1", "role": role}
        state["objects"]["u2"]["combat_designation"] = {"combat_id": "cb1", "role": "defender" if role == "attacker" else "attacker"}
        state["battlefields"]["bf1"] = {"controller": "p2" if role == "attacker" else "p1", "objects": here,
                                        "contested": True, "contested_by": "p1" if role == "attacker" else "p2"}
    else:
        state["battlefields"]["bf1"] = {"controller": "p1", "objects": here}
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    return state


def read(state):
    return {"might": effective_might(state, "fi"),
            "keywords": sorted(k for k in keyword_values(state, "fi") if k in ("deflect", "ganking", "shield")),
            "shield": keyword_values(state, "fi").get("shield")}


MIGHTY_CASES = {
    # 476.3: printed 4 + a Buff = 5, Mighty; as a Defender, +1 from Shield = 6
    "buffed": ({"buffed": True}, {"might": 5, "keywords": ["deflect", "ganking", "shield"], "shield": 1}),
    "buffed_defending": ({"buffed": True, "role": "defender"}, {"might": 6, "keywords": ["deflect", "ganking", "shield"], "shield": 1}),
    # 476.3: the Buff gone - straight to 4 with no keywords
    "unbuffed_defending": ({"role": "defender"}, {"might": 4, "keywords": [], "shield": None}),
    "unbuffed": ({}, {"might": 4, "keywords": [], "shield": None}),
    # the Ability layer first sees 4 (before the Arithmetic layer adds the Buff and takes 1)
    "buffed_and_minus_one": ({"buffed": True, "delta": -1}, {"might": 4, "keywords": [], "shield": None}),
    # ... and as a Defender: a Shield it never got cannot hold it up at 5
    "buffed_and_minus_one_defending": ({"buffed": True, "delta": -1, "role": "defender"}, {"might": 4, "keywords": [], "shield": None}),
    "plus_one_this_turn": ({"delta": 1}, {"might": 5, "keywords": ["deflect", "ganking", "shield"], "shield": 1}),
    # a Shield from elsewhere: 4 + 1 as a Defender = 5, Mighty, a second Shield: 6
    "defending_with_a_shield_from_elsewhere": ({"role": "defender", "shield_aura": True},
                                               {"might": 6, "keywords": ["deflect", "ganking", "shield"], "shield": 2}),
    # printed 5: Mighty in the first Ability layer, -1 in the Arithmetic layer, disqualified once
    "printed_five_minus_one": ({"printed": 5, "delta": -1}, {"might": 4, "keywords": [], "shield": None}),
}


def mighty_readings():
    out = {}
    for label, (kwargs, _) in MIGHTY_CASES.items():
        state = fiora(**kwargs)
        problems = validate_state(state)
        out[label] = read(state) if not problems else {"invalid": problems[:2]}
    return out


def check_mighty(errors):
    got = mighty_readings()
    want = {label: expected for label, (_, expected) in MIGHTY_CASES.items()}
    for label in want:
        if got[label] != want[label]:
            errors.append(f"Mighty ({label}) read {got[label]}, not {want[label]} (Core 476.2, 476.3, 708)")
    spent = spend_buff(fiora(buffed=True), "fi")
    if spent is None or read(spent) != {"might": 4, "keywords": [], "shield": None}:
        errors.append(f"spending the Buff did not take the Mighty keywords away: {spent and read(spent)}")
    owed = PT.deflect_costs(fiora(buffed=True), "p2", ["fi"])
    if [(c["cost_id"], c["payment"]) for c in owed] != [("deflect:fi:1", {"kind": "power_any", "amount": 1})]:
        errors.append(f"a Mighty Unit's granted Deflect did not cost an opponent's choice 1 Power (809.1.c): {owed}")
    if PT.deflect_costs(fiora(), "p2", ["fi"]):
        errors.append("a Unit that is not Mighty imposed a Deflect cost")
    moves = {"mighty": move(fiora(buffed=True), "fi").get("committed"), "not": move(fiora(), "fi").get("committed")}
    if moves != {"mighty": True, "not": False}:
        errors.append(f"the Mighty Unit's Ganking did not move it Battlefield to Battlefield: {moves}")


# ------------------------------------------------------------------ Might per count
def kingpin(*, self_buffed=False, in_base=False):
    """p1's sk (printed 3, "+1 for each buffed friendly unit at my battlefield") at bf1 with p1's
    buffed f1 and unbuffed f2 and p2's buffed e1 (contested); p1's buffed f3 at bf2; or sk in p1's
    Base with the buffed f4 beside it."""
    state = base_state()
    fields = {"dynamic_might": [{"modifier_id": "own-text", "amount": 1, "per": {"kind": "buffed_friendly_units_at_source_battlefield"}}]}
    state["objects"]["sk"] = unit("p1", 3, **fields, **({"buffed": True} if self_buffed else {}))
    state["objects"]["f1"] = unit("p1", 2, buffed=True)
    state["objects"]["f2"] = unit("p1", 2)
    state["objects"]["f3"] = unit("p1", 2, buffed=True)
    state["objects"]["f4"] = unit("p1", 2, buffed=True)
    state["objects"]["e1"] = unit("p2", 2, buffed=True)
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": (["f1", "f2", "e1"] if in_base else ["sk", "f1", "f2", "e1"]),
                                    "contested": True, "contested_by": "p2"}
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": ["f3"]}
    state["players"]["p1"]["zones"]["base"] += (["sk", "f4"] if in_base else ["f4"])
    return state


def mundo(trash=1, their_trash=0):
    state = base_state()
    state["objects"]["dm"] = unit("p1", 2, dynamic_might=[{"modifier_id": "own-text", "amount": 1, "per": {"kind": "controller_trash_count"}}])
    state["players"]["p1"]["zones"]["base"].append("dm")
    for i in range(trash - 1):          # base_state's p1 trash already holds c3
        state["objects"][f"t{i}"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                     "damage": 0, "exhausted": False}
        state["players"]["p1"]["zones"]["trash"].append(f"t{i}")
    for i in range(their_trash):
        state["objects"][f"o{i}"] = {"owner": "p2", "controller": "p2", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                     "damage": 0, "exhausted": False}
        state["players"]["p2"]["zones"]["trash"].append(f"o{i}")
    return state


def count_readings():
    return {"kingpin_unbuffed": effective_might(kingpin(), "sk"), "kingpin_buffed": effective_might(kingpin(self_buffed=True), "sk"),
            "kingpin_in_base": effective_might(kingpin(in_base=True), "sk"),
            "mundo_one": effective_might(mundo(1), "dm"), "mundo_four": effective_might(mundo(4), "dm"),
            "mundo_one_theirs_five": effective_might(mundo(1, 5), "dm")}


COUNT_WANT = {"kingpin_unbuffed": 4, "kingpin_buffed": 6, "kingpin_in_base": 3,
              "mundo_one": 3, "mundo_four": 6, "mundo_one_theirs_five": 3}


def check_counts(errors):
    for label, state in (("kingpin", kingpin()), ("kingpin_base", kingpin(in_base=True)), ("mundo", mundo(4, 5))):
        if found := validate_state(state):
            errors.append(f"the {label} board is invalid: {found}")
            return
    got = count_readings()
    if got != COUNT_WANT:
        errors.append(f"Might per count read wrong: {got}, not {COUNT_WANT}")
    bad = kingpin()
    bad["objects"]["sk"]["dynamic_might"][0]["per"] = {"kind": "enemy_units_everywhere"}
    if not validate_state(bad):
        errors.append("an unknown per-each count validated")


def check_invalid(errors):
    for bad in ({"modifier_id": "x", "keyword": "ganking", "condition": {"kind": "is_buffed", "object": "f1"}},
                {"modifier_id": "x", "keyword": "ganking", "condition": {"kind": "runes_at_least", "count": 3}},
                {"modifier_id": "x", "keyword": "legion", "condition": dict(BUFFED)},
                {"modifier_id": "x", "keyword": "ganking", "value": 2, "condition": dict(BUFFED)},
                {"modifier_id": "x", "keyword": "assault", "condition": {**DISCARDED, "player": "p2"}},
                {"modifier_id": "x", "keyword": "shield"}):
        broken = bully()
        broken["objects"]["bb"]["conditional_keywords"] = [bad]
        if not validate_state(broken):
            errors.append(f"an invalid conditional keyword validated: {bad}")
    elder = bully(elder=True)
    elder["objects"]["bb"]["conditional_might"][0]["condition"] = {"kind": "is_buffed", "count": 1}
    if not validate_state(elder):
        errors.append("an is_buffed conditional Might carrying a count validated")


def check_mutations(errors):
    saved = IR._layered_own_might

    def buff_first(state, object_id, result, own_might, status, *, pending_buff, arithmetic_ran):
        return saved(state, object_id, result, own_might, status, pending_buff=0, arithmetic_ran=arithmetic_ran)
    try:
        IR._layered_own_might = buff_first
        caught = read(fiora(buffed=True, delta=-1, role="defender")) != MIGHTY_CASES["buffed_and_minus_one_defending"][1]
    finally:
        IR._layered_own_might = saved
    if not caught:
        errors.append("mutation not caught: the Buff counted before the first Arithmetic layer")

    saved_step = IR._own_might_step
    try:
        IR._own_might_step = lambda status, holds: "applied" if status == "unapplied" and holds else status
        caught = read(fiora(printed=5, delta=-1)) != MIGHTY_CASES["printed_five_minus_one"][1]
    finally:
        IR._own_might_step = saved_step
    if not caught:
        errors.append("mutation not caught: a Mighty grant kept after it was disqualified")

    saved_eval = IR.evaluate_condition

    def any_friendly_buffed(state, condition, *, controller=None, object_id=None, perspective=None):
        if condition.get("kind") == "is_buffed":
            return any(o.get("buffed") and o.get("controller") == controller for o in state["objects"].values())
        if condition.get("kind") == "cards_discarded_this_turn_at_least":
            return sum(len(IR.cards_discarded_this_turn(state, p)) for p in state["players"]) >= condition["count"]
        return saved_eval(state, condition, controller=controller, object_id=object_id, perspective=perspective)
    try:
        IR.evaluate_condition = any_friendly_buffed
        buffed_caught = move(bully(other_buffed=True), "bb").get("committed")
        discard_caught = "assault" in keyword_values(discard(soul(), "p2"), "rs")
    finally:
        IR.evaluate_condition = saved_eval
    if not buffed_caught:
        errors.append("mutation not caught: is_buffed read off any friendly Unit")
    if not discard_caught:
        errors.append("mutation not caught: every player's discards counted")

    saved_count = IR.per_count

    def without_source(state, source_id, kind):
        if kind == "buffed_friendly_units_at_source_battlefield" and state["objects"][source_id].get("buffed"):
            return saved_count(state, source_id, kind) - 1
        return saved_count(state, source_id, kind)
    try:
        IR.per_count = without_source
        caught = count_readings() != COUNT_WANT
    finally:
        IR.per_count = saved_count
    if not caught:
        errors.append("mutation not caught: the count excluding its buffed source")


def main() -> int:
    errors: list[str] = []
    try:
        check_buffed(errors)
        check_discarded(errors)
        check_mighty(errors)
        check_counts(errors)
        check_invalid(errors)
        check_mutations(errors)
    except RecursionError:
        errors.append("a self-Might condition recursed (Core 476.3 is read from the layers in progress)")
    if errors:
        print("FAILED: conditional passive checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'while I'm buffed' / 'if you've discarded a card this turn' / 'while I'm [Mighty]' keywords and Might hold "
          "exactly where their condition does (476.2-476.3, no recursion), Might per count reads "
          "buffed friendly units at its battlefield and its controller's trash, invalid shapes are refused, and five "
          "mutations are caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
