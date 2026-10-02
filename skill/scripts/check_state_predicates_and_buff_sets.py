#!/usr/bin/env python3
"""A state a chosen object or a set must be in, buffs over several objects, and two conditions
read as the instruction executes (2026-09-27, package 6).

  selector state     `exhausted` / `damaged` on a target selector: "an exhausted friendly unit"
                     (exhausted: true - Core 414.2), "something else that's exhausted" (any type
                     on the board, the source excluded, Core 415.1). The state is read when the
                     target is chosen and again when it is used: a target readied in between is no
                     longer legal and the instruction does nothing to it (Core 359.3.e.2).
  criteria state     the same fields on an `affected` set, and `exclude_source_identity` ("other"):
                     "kill all damaged enemy units here" (damage marked, Core 142), "buff all other
                     friendly units there" - found by criteria, not targeted (Core 355.10.d).
  buff over a set    `buff` with `targets {min, max}` ("buff up to two other friendly units", Core
                     355.13) or `affected` ("buff all friendly units"): each object is buffed on its
                     own, and one already buffed is not buffed again (Core 426.1.b.1, 702.3).
  conditions         controls_units narrowed by state and located "here" (the Battlefield the
                     condition's object stands at now), and at_a_battlefield ("if I am at a
                     battlefield"). A state_holds predicate reads them as the instruction executes,
                     about the program's own source when they name no object (Core 383.2.a.1: an
                     "if" not right after the trigger condition belongs to the effect; 359.3.f.2).

Each rule has a case that fails when the rule is removed. Every fixture is synthetic.

    python skill/scripts/check_state_predicates_and_buff_sets.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (apply_program, effective_might, evaluate_condition, find_location, hash_value,  # noqa: E402
                       object_identity, validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
HERE = {"kind": "program_source_current_battlefield"}
UNIT = {"owner": None, "controller": None, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
        "exhausted": False}

# the programs the clause grammar writes for the card sentences (checked against it below)
BUFF_EXHAUSTED = {"op": "buff", "effect_id": "bf", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit",
                                                              "controller_relation": "friendly", "exhausted": True}}
READY_SOMETHING_ELSE = {"op": "ready", "effect_id": "rd", "target": {"decision_ref": "t", "chosen_zone_class": "board",
                                                                     "include_legend_zone": True, "exhausted": True,
                                                                     "exclude_source_identity": "$source_identity"}}
PUMP_IF_READY_ENEMY_HERE = {"op": "modify_might", "effect_id": "mm", "object_id": {"object_ref": "program_source"}, "amount": 2,
                            "duration": "this_turn", "source": "$chain_item",
                            "predicate": {"kind": "state_holds", "condition": {"kind": "controls_units", "count": 1,
                                                                               "controller_relation": "enemy", "location": "here",
                                                                               "exhausted": False}}}
BUFF_UP_TO_TWO_OTHER = {"op": "buff", "effect_id": "bf", "targets": {"decision_ref": "t", "min": 0, "max": 2, "restrictions": {
    "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly", "exclude_source_identity": "$source_identity"}}}
BUFF_ALL_FRIENDLY = {"op": "buff", "effect_id": "bf", "affected": {"criteria": {"kind": "unit", "controller_relation": "friendly",
                                                                                "location": "board"}}}
BUFF_OTHERS_THERE = {"op": "buff", "effect_id": "bf", "affected": {"criteria": {"kind": "unit", "controller_relation": "friendly",
                                                                                "location_ref": dict(HERE),
                                                                                "exclude_source_identity": "$source_identity"}},
                     "predicate": {"kind": "state_holds", "condition": {"kind": "at_a_battlefield"}}}
KILL_DAMAGED_HERE = {"op": "kill", "effect_id": "kl", "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy",
                                                                                "location_ref": dict(HERE), "damaged": True}}}
SENTENCES = {
    "Buff an exhausted friendly unit.": [BUFF_EXHAUSTED],
    "Ready something else that's exhausted.": [READY_SOMETHING_ELSE],
    "Give me +2 [M] this turn if there is a ready enemy unit here.": [PUMP_IF_READY_ENEMY_HERE],
    "Buff up to two other friendly units.": [BUFF_UP_TO_TWO_OTHER],
    "Then buff all friendly units.": [BUFF_ALL_FRIENDLY],
    "Then, if I am at a battlefield, buff all other friendly units there.": [BUFF_OTHERS_THERE],
    "Kill all damaged enemy units here.": [KILL_DAMAGED_HERE],
}


def board() -> dict:
    """p1: u1 (the source) and u3 (exhausted) at bf1, u5 (ready) and gear g1 (exhausted) and rune r1
    (exhausted) in its Base. p2: u2 (exhausted, 1 damage) and u4 (ready, no damage) at bf1, u6 (ready,
    1 damage) at bf2. Every unit has 3 Might."""
    state = base_state()
    state["turn_id"] = "T1"
    p1, p2 = state["players"]["p1"]["zones"], state["players"]["p2"]["zones"]
    for object_id, owner, extra in (("u3", "p1", {"exhausted": True}), ("u5", "p1", {}), ("u4", "p2", {}),
                                    ("u6", "p2", {"damage": 1})):
        state["objects"][object_id] = {**UNIT, "owner": owner, "controller": owner, **extra}
    state["objects"]["u1"].update({"base_might": 3, "damage": 0, "exhausted": True})
    state["objects"]["u2"].update({"base_might": 3, "damage": 1, "exhausted": True})
    state["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": True}
    state["objects"]["r1"]["exhausted"] = True
    p1["rune_deck"].remove("r1")
    p1["base"], p2["base"] = ["u5", "g1", "r1"], []
    state["battlefields"] = {"bf1": {"controller": None, "objects": ["u1", "u3", "u2", "u4"]},
                             "bf2": {"controller": None, "objects": ["u6"]}}
    return settle_contested(state)


def run(state: dict, effects: list[dict], source: str = "u1", **chosen) -> dict:
    doc = program("p1", *copy.deepcopy(effects))
    doc["source_object"] = source
    doc["source_identity"] = object_identity(state, source)
    for effect in doc["effects"]:
        if effect.get("source") == "$chain_item":
            effect["source"] = "c1"
    decisions = None
    if chosen:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                     "decisions": [{"decision_id": ref, "stage": "play_declaration", "kind": "target_selection",
                                    "controller": "p1", "value": list(value),
                                    "selection_identities": {o: object_identity(state, o) for o in value}}
                                   for ref, value in chosen.items()]}
    return apply_program(state, doc, decisions=decisions)


def play(state: dict, effects: list[dict], **chosen) -> dict:
    """The same program played as a spell (c1 from p1's hand): targets are checked where they are chosen."""
    state = copy.deepcopy(state)
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {}}
    doc = {"schema_version": "riftbound-effect-program.v1", "ruleset": RULESET, "program_id": "c1-effects",
           "controller": "p1", "effects": copy.deepcopy(effects)}
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-1", "actor": "p1",
                   "card": "c1", "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
                   "cost": {"base": {"energy": 1, "power": {}}}, "effect_program_id": "c1-effects",
                   "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                 "decisions": [{"decision_id": ref, "stage": "play_declaration", "kind": "target_selection",
                                "controller": "p1", "value": list(value),
                                "selection_identities": {o: object_identity(state, o) for o in value}}
                               for ref, value in chosen.items()]}
    return play_card(fixture(), state, declaration, engine_decisions=decisions, effect_program=doc)


def outcomes(result: dict) -> list:
    return [event.get("outcome") for event in result.get("trace") or []]


def illegal(result: dict) -> bool:
    """The instruction ran with its target no longer legal: nothing done to it (Core 359.3.e.1-2)."""
    return result.get("committed") is True and outcomes(result) in (["ignored_illegal_target"], ["skipped_illegal_target"])


def main() -> int:
    errors: list[str] = []

    def check(label, ok, detail=""):
        if not ok:
            errors.append(f"{label}: {detail}")

    state = board()
    if found := validate_state(state):
        print("\n".join(f"FAILED: fixture invalid: {e}" for e in found))
        return 1
    buffed = lambda s, o: bool(s["objects"][o].get("buffed"))
    where = lambda s, o: find_location(s, o)

    # --- the clause grammar writes exactly these programs --------------------------------------
    grammar = CG.load_grammar()
    for sentence, wanted in SENTENCES.items():
        got = CG.compile_clause(sentence, grammar)
        check(f"grammar: {sentence!r}", not got.get("unsupported") and got.get("program_effects") == wanted,
              f"{got.get('production_id')} {got.get('program_effects')}")
        doc = program("p1", *copy.deepcopy(wanted))
        doc["source_object"] = "u1"
        check(f"validates: {sentence!r}", not validate_program(doc), str(validate_program(doc)))

    # --- a target's state: "Buff an exhausted friendly unit." ----------------------------------
    done = run(state, [BUFF_EXHAUSTED], t=["u3"])
    check("exhausted target is buffed", done.get("committed") and buffed(done["next_state"], "u3"), str(outcomes(done)))
    done = run(state, [BUFF_EXHAUSTED], t=["u5"])
    check("a ready unit is not an exhausted target", done.get("committed") and not buffed(done["next_state"], "u5")
          and illegal(done), str(outcomes(done)))
    played = play(state, [BUFF_EXHAUSTED], t=["u5"])
    check("a ready unit is refused at play (Core 355.8)", played.get("committed") is False
          and played.get("reason_code") == "target_illegal_at_play", f"{played.get('reason_code')} {played.get('reason')}")
    played = play(state, [BUFF_EXHAUSTED], t=["u3"])
    check("an exhausted friendly unit is accepted at play", played.get("committed") is True, str(played.get("reason")))
    readied = copy.deepcopy(state)
    readied["objects"]["u3"]["exhausted"] = False
    chosen_when_exhausted = {"t": ["u3"]}
    doc = program("p1", copy.deepcopy(BUFF_EXHAUSTED))
    doc.update(source_object="u1", source_identity=object_identity(state, "u1"))
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(readied),
                 "decisions": [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
                                "value": ["u3"], "selection_identities": {"u3": object_identity(state, "u3")}}]}
    done = apply_program(readied, doc, decisions=decisions)
    check("readied after it was chosen: no longer a legal target (Core 359.3.e.2)",
          done.get("committed") and not buffed(done["next_state"], "u3") and illegal(done),
          f"{chosen_when_exhausted} {outcomes(done)}")
    for bad in ({"exhausted": "yes"}, {"exhausted": True, "chosen_zone_class": "non_board"}, {"damaged": 1}):
        effect = copy.deepcopy(BUFF_EXHAUSTED)
        effect["target"].update(bad)
        check(f"refused selector state {bad}", bool(validate_program(program("p1", effect))), "validated")

    # --- a kind-less target, the source excluded: "Ready something else that's exhausted." -----
    for other, kind in (("g1", "gear"), ("r1", "rune"), ("u2", "unit"), ("u3", "unit")):
        done = run(state, [READY_SOMETHING_ELSE], t=[other])
        check(f"something else that's exhausted: a {kind} ({other}) is readied",
              done.get("committed") and not done["next_state"]["objects"][other].get("exhausted"), str(outcomes(done)))
    done = run(state, [READY_SOMETHING_ELSE], t=["u1"])
    check("'else': the source is not a legal target", done.get("committed") and done["next_state"]["objects"]["u1"].get("exhausted")
          and illegal(done), str(outcomes(done)))
    done = run(state, [READY_SOMETHING_ELSE], t=["u5"])
    check("'that's exhausted': a ready unit is not a legal target", illegal(done), str(outcomes(done)))
    # GPT 2026-10-02: "something" is not only Units - an exhausted Legend in its Legend Zone is a Game Object that
    # can be readied (Core 107.4, 355.9.a.4, 415.1); a Ready one is not "that's exhausted"
    legends = copy.deepcopy(state)
    for legend, owner, tired in (("lg1", "p1", True), ("lg2", "p2", False)):
        legends["objects"][legend] = {"owner": owner, "controller": owner, "kind": "legend", "base_might": 0,
                                      "might_modifiers": [], "damage": 0, "exhausted": tired, "champion_legend": True}
        legends["players"][owner]["zones"].setdefault("legend_zone", []).append(legend)
    done = run(legends, [READY_SOMETHING_ELSE], t=["lg1"])
    check("something else that's exhausted: an exhausted Legend (lg1, in its Legend Zone) is readied",
          done.get("committed") and not done["next_state"]["objects"]["lg1"].get("exhausted"), str(outcomes(done)))
    done = run(legends, [READY_SOMETHING_ELSE], t=["lg2"])
    check("'that's exhausted': a Ready Legend is not a legal target", illegal(done), str(outcomes(done)))
    narrow = copy.deepcopy(READY_SOMETHING_ELSE)
    narrow["target"].pop("include_legend_zone")
    done = run(legends, [narrow], t=["lg1"])
    check("without include_legend_zone a board target never reaches a Legend (ADR-0012 §5)", illegal(done), str(outcomes(done)))
    for bad in ({"include_legend_zone": False}, {"kind": "unit"}, {"chosen_zone_class": "non_board"}):
        wrong = copy.deepcopy(READY_SOMETHING_ELSE)
        wrong["target"].update(bad)
        check(f"refused include_legend_zone with {bad}", bool(validate_program(program("p1", wrong))), "validated")

    # --- a set narrowed by a state: "Kill all damaged enemy units here." ------------------------
    done = run(state, [KILL_DAMAGED_HERE])
    after = done.get("next_state") or state
    check("damaged enemy here is killed", done.get("committed") and where(after, "u2") == ("player", "p2", "trash"),
          str(outcomes(done)))
    check("an undamaged enemy here is untouched", where(after, "u4") == ("battlefield", "bf1", None), str(where(after, "u4")))
    check("a damaged enemy elsewhere is untouched", where(after, "u6") == ("battlefield", "bf2", None), str(where(after, "u6")))
    for bad in ({"damaged": "yes"}, {"exclude_source_identity": "u1@0"}, {"stunned": True}):
        effect = copy.deepcopy(KILL_DAMAGED_HERE)
        effect["affected"]["criteria"].update(bad)
        check(f"refused criteria {bad}", bool(validate_program(program("p1", effect))), "validated")

    # --- a condition read now, about the source: "... if there is a ready enemy unit here." -----
    base = effective_might(state, "u1")
    done = run(state, [PUMP_IF_READY_ENEMY_HERE])
    check("a ready enemy here: +2", done.get("committed") and effective_might(done["next_state"], "u1") == base + 2,
          str(outcomes(done)))
    tired = copy.deepcopy(state)
    tired["objects"]["u4"]["exhausted"] = True
    done = run(tired, [PUMP_IF_READY_ENEMY_HERE])
    check("only exhausted enemies here: nothing", done.get("committed") and effective_might(done["next_state"], "u1") == base
          and outcomes(done) == ["skipped_linked_dependency"], str(outcomes(done)))
    moved = copy.deepcopy(state)
    moved["battlefields"]["bf1"]["objects"].remove("u4")
    moved["battlefields"]["bf2"]["objects"].append("u4")
    moved["objects"]["u2"]["exhausted"] = True
    done = run(settle_contested(moved), [PUMP_IF_READY_ENEMY_HERE])
    check("a ready enemy at another battlefield: nothing", effective_might(done["next_state"], "u1") == base, str(outcomes(done)))
    home = copy.deepcopy(state)
    home["battlefields"]["bf1"]["objects"].remove("u1")
    home["players"]["p1"]["zones"]["base"].append("u1")
    done = run(home, [PUMP_IF_READY_ENEMY_HERE])
    check("the source in its Base has no 'here': nothing", effective_might(done["next_state"], "u1") == base, str(outcomes(done)))
    check("controls_units here counts at the object's Battlefield",
          evaluate_condition(state, {"kind": "controls_units", "count": 2, "controller_relation": "enemy", "location": "here"},
                             controller="p1", object_id="u1") is True
          and evaluate_condition(state, {"kind": "controls_units", "count": 2, "controller_relation": "enemy", "location": "here",
                                         "exhausted": False}, controller="p1", object_id="u1") is False,
          "counting u2 and u4, then only the ready u4")
    check("controls_units damaged", evaluate_condition(state, {"kind": "controls_units", "count": 2, "controller_relation": "enemy",
                                                              "damaged": True}, controller="p1") is True
          and evaluate_condition(state, {"kind": "controls_units", "count": 3, "controller_relation": "enemy",
                                         "damaged": True}, controller="p1") is False, "u2 and u6 are the damaged enemies")

    # --- "Then, if I am at a battlefield, buff all other friendly units there." -----------------
    done = run(state, [BUFF_OTHERS_THERE])
    after = done.get("next_state") or state
    check("at a battlefield: the other friendly unit there is buffed", done.get("committed") and buffed(after, "u3"), str(outcomes(done)))
    check("'other': the source is not buffed by it", not buffed(after, "u1"), "u1 buffed")
    check("'there': a friendly unit in the Base is not buffed", not buffed(after, "u5"), "u5 buffed")
    check("'friendly': enemies there are not buffed", not buffed(after, "u2") and not buffed(after, "u4"), "an enemy buffed")
    done = run(home, [BUFF_OTHERS_THERE])
    check("the source in its Base: nothing happens", done.get("committed") and outcomes(done) == ["skipped_linked_dependency"]
          and not any(buffed(done["next_state"], o) for o in ("u1", "u3", "u5")), str(outcomes(done)))
    check("at_a_battlefield reads the object's place now",
          evaluate_condition(state, {"kind": "at_a_battlefield"}, controller="p1", object_id="u1") is True
          and evaluate_condition(home, {"kind": "at_a_battlefield"}, controller="p1", object_id="u1") is False
          and evaluate_condition(state, {"kind": "at_a_battlefield"}, controller="p1", object_id=None) is False, "")

    # --- "Buff up to two other friendly units." --------------------------------------------------
    done = run(state, [BUFF_UP_TO_TWO_OTHER], t=["u3", "u5"])
    check("two chosen: both buffed", done.get("committed") and buffed(done["next_state"], "u3") and buffed(done["next_state"], "u5"),
          str(outcomes(done)))
    done = run(state, [BUFF_UP_TO_TWO_OTHER], t=[])
    check("none chosen (Core 355.13): nothing, committed", done.get("committed") and not any(
        buffed(done["next_state"], o) for o in ("u1", "u3", "u5")), str(outcomes(done)))
    played = play(state, [BUFF_UP_TO_TWO_OTHER], t=["u3", "u5", "u1"])
    check("three chosen are refused at play", played.get("committed") is False
          and played.get("reason_code") in ("target_count_out_of_range", "target_illegal_at_play"), str(played.get("reason_code")))
    done = run(state, [BUFF_UP_TO_TWO_OTHER], t=["u1"])
    check("'other': the source is not buffed", not buffed(done.get("next_state") or state, "u1"), str(outcomes(done)))
    done = run(state, [BUFF_UP_TO_TWO_OTHER], t=["u2"])
    check("'friendly': an enemy is not buffed", not buffed(done.get("next_state") or state, "u2"), str(outcomes(done)))
    already = copy.deepcopy(state)
    already["objects"]["u3"]["buffed"] = True
    done = run(already, [BUFF_UP_TO_TWO_OTHER], t=["u3"])
    check("an already buffed unit gets no second buff (Core 426.1.b.1)", done.get("committed")
          and effective_might(done["next_state"], "u3") == effective_might(already, "u3"), str(outcomes(done)))

    # --- "Then buff all friendly units." -------------------------------------------------------
    done = run(state, [BUFF_ALL_FRIENDLY])
    after = done.get("next_state") or state
    check("every friendly unit, Base and Battlefield, is buffed",
          done.get("committed") and all(buffed(after, o) for o in ("u1", "u3", "u5")), str(outcomes(done)))
    check("no enemy is buffed", not any(buffed(after, o) for o in ("u2", "u4", "u6")), "")

    # --- only buff joins: empower still acts on one object -------------------------------------
    check("empower with targets is still refused", bool(validate_program(program("p1", {
        "op": "empower", "effect_id": "em", "targets": {"decision_ref": "t", "min": 0, "max": 2,
                                                         "restrictions": {"chosen_zone_class": "board"}}}))), "validated")

    if errors:
        print("\n".join(f"FAILED: {e}" for e in errors))
        return 1
    print("state predicates, buff sets and here/at-a-battlefield conditions: every case holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
