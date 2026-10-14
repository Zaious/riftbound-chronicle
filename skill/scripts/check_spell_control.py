#!/usr/bin/env python3
"""Gaining control of a spell on the Chain and making new choices for it (package 11, Mystic Reversal: "[Reaction] Gain
control of a spell. You may make new choices for it.").

GPT 2026-10-12 (PACKAGE11 ruling 13): the new controller's "you", "friendly" and "enemy" apply to the text still to execute,
read as it executes (Core 359.3.f.4); new choices follow Core 750-755 - in the 10-09 text (in effect 2026-10-16,
package 12): every choice of the Chain item is remade, the same one again allowed (753), each legal (753.1) and within
the item's restrictions (753.3); with no legal set the instruction is negated (753.2). (The 07-16 text asked for a
subset, each choice new - 751.1 - and package 11 was built so.) What the first controller paid is neither refunded nor
transferred (755). The engine's shape: op
gain_control_of_spell (the Chain item and its card change controller; the timing chain follows); op make_new_choices
(optional; the spell's own program supplied by the caller as chain_programs); the bridge rebinds the spell's program to
its new controller when it resolves.

  M1 control        p1's Reversal takes p2's spell "Deal 3 to an enemy unit" (targeting p1's a1): the Chain item and
                    the card are p1's, in the timing chain too; p2's paid Energy is not given back
  M2 no new choices declined: the old target stands (not recomputed), but the spell now resolves for p1 and "an
                    enemy unit" is read for p1 as it executes - p1's own a1 is no longer a legal target, so nothing is
                    dealt (Core 359.3.f.4, 359.3.e.2)
  M3 retarget       p1 remakes the target to p2's e1: the spell resolves for p1 and e1 is dealt 3, a1 nothing
  M4 same again     the Move spell's target and destination chosen again as they were: accepted (753, 10-09)
  M5 illegal        remaking it to p1's own a2 or a1 ("an enemy unit" for p1 now): refused (753.1)
  M6 mode           a modal spell of p2's ("Choose one - Draw 1; or Deal 2 to an enemy unit"), chosen "draw": p1
                    remakes the mode to the Deal with a new target e1 - e1 dealt 2; the new mode without its target:
                    refused as incomplete; the same mode again: accepted
  M7 no program     new choices asked with the spell's program not supplied: refused as unsupported by name
  M8 the card       the spell's card goes to its OWNER's (p2's) trash after it resolves
  M9 destination   a Move spell of p2's (e1 to bf1): p1 remakes target and destination, e1 to bf2 - e1 goes to bf2
  M10 none made     chosen to make new choices and none made: the choices are asked for (new_choices_required)
  M11 incomplete    only the Move's destination remade: refused - every choice is remade (753)
  M12 facedown      the spell played from facedown at bf1: a new target at bf2 refused, one at bf1 accepted (753.3)
  M13 none legal    no enemy unit for p1 anywhere: the instruction is negated (753.2) and the spell keeps its choices
  M14 paid by p2    a spell whose optional cost p2 paid ('If you do, draw 2. Otherwise, draw 1'), its program bound for
                    p2: taken by p1, it draws 2 for p1 - the check reads the payment, not who controls it now (10-09
                    135.2.b.7), and the players its text names are exchanged with its controller (359.3.f.4)
  V  shape/grammar  make_new_choices not optional, or not linked to a gain of control, does not validate; the card's
                    text lowers to the two ops

    python skill/scripts/check_spell_control.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, hash_value, object_identity, validate_program,  # noqa: E402
                       validate_state)
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
errors: list[str] = []
ENEMY = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}
SHOT = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "shot-effects", "controller": "p2",
        "effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": 3, "target": dict(ENEMY)}]}
MODAL = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "modal-effects", "controller": "p2",
         "modal": {"choose": 1, "decision_ref": "mode", "timing": "play_declaration", "options": [
             {"option_id": "draw", "effects": [{"op": "draw", "effect_id": "d", "player": "p2", "count": 1}]},
             {"option_id": "deal", "effects": [{"op": "deal_damage", "effect_id": "dm", "amount": 2, "target": dict(ENEMY)}]}]},
         "effects": []}
MOVE = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "move-effects", "controller": "p2",
        "effects": [{"op": "move_board_object", "effect_id": "mv",
                     "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"},
                     "destination": {"decision_ref": "dest", "restriction": "battlefield"}}]}
MEDITATE = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "meditate-effects", "controller": "p2",
            "effects": [{"op": "draw", "effect_id": "dr-0", "player": "p2", "count": 2,
                         "predicate": {"kind": "cost_paid", "cost_id": "self_offer:k1-cost", "cost_offer_id": "k1-cost"}},
                        {"op": "draw", "effect_id": "dr-1", "player": "p2", "count": 1,
                         "predicate": {"kind": "cost_not_paid", "cost_id": "self_offer:k1-cost", "cost_offer_id": "k1-cost"}}]}
REVERSAL = {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "reversal-effects", "controller": "p1",
            "effects": [{"op": "gain_control_of_spell", "effect_id": "gcs", "player": "p1",
                         "target": {"decision_ref": "s", "chosen_zone_class": "non_board", "location": "chain", "kind": "spell"}},
                        {"op": "make_new_choices", "effect_id": "new", "linked": {"effect_id": "gcs"}, "optional": {"decision_ref": "may"}}]}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might=4):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(modal=False):
    """p1's a1 and a2, p2's e1 at bf1. On the Chain: p2's spell (shot - targeting a1; or the modal one, 'draw' chosen),
    then p1's Reversal (rev) targeting it, on top."""
    state = base_state()
    for oid, owner in (("a1", "p1"), ("a2", "p1"), ("e1", "p2")):
        state["objects"][oid] = unit(owner)
    state["battlefields"]["bf1"]["objects"] += ["a1", "a2", "e1"]
    for oid, owner in (("shot", "p2"), ("rev", "p1")):
        state["objects"][oid] = {"owner": owner, "controller": owner, "kind": "spell", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False}
    spell = {"card": "shot", "controller": "p2", "effect_program_id": "modal-effects" if modal else "shot-effects",
             "cost_receipt": None}
    spell.pop("cost_receipt")
    if modal:
        spell["mode_selection"] = {"decision_id": "mode", "option_id": "draw"}
    else:
        spell["played_targets"] = [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection",
                                    "controller": "p2", "value": ["a1"], "selection_identities": {"a1": "a1@0"}}]
    state["chain_items"] = {"spell-shot": spell,
                            "spell-rev": {"card": "rev", "controller": "p1", "effect_program_id": "reversal-effects",
                                          "played_targets": [{"decision_id": "s", "stage": "play_declaration",
                                                              "kind": "target_selection", "controller": "p1",
                                                              "value": ["shot"], "selection_identities": {"shot": "shot@0"}}]}}
    state["players"]["p2"]["resources"] = {"energy": 0, "power": {}}
    return settle_contested(state)


def timing():
    return fixture(priority="p2", items=[item("spell-shot", "p2", "spell", "default", "finalized"),
                                         item("spell-rev", "p1", "spell", "reaction", "finalized")], passes=["p1", "p2"])


def reverse(state, *, may=None, remake=None, mode=None, programs=True, spell=SHOT, destination=None):
    decisions = []
    if destination is not None:
        decisions.append({"decision_id": "new:dest", "stage": "resolution", "kind": "location_selection", "controller": "p1",
                          "value": destination})
    if may is not None:
        decisions.append({"decision_id": "may", "stage": "resolution", "kind": "optional_choice", "controller": "p1", "value": may})
    for ref, values in (remake or {}).items():
        decisions.append({"decision_id": f"new:{ref}", "stage": "resolution", "kind": "target_selection", "controller": "p1",
                          "value": values, "selection_identities": {v: object_identity(state, v) for v in values}})
    if mode is not None:
        decisions.append({"decision_id": "new:mode", "stage": "resolution", "kind": "option_selection", "controller": "p1",
                          "value": mode})
    env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": decisions}
    return resolve_with_program(timing(), "spell-rev", state, REVERSAL, engine_decisions=env,
                                chain_programs={"spell-shot": spell} if programs else None)


def resolve_spell(done, spell=SHOT):
    t = done["next_timing_state"]
    for _ in range(6):
        if next_procedure(t).get("procedure") == "resolve_newest_finalized":
            break
        t = (pass_priority(t, t.get("priority")) or {}).get("next_state") or t
    return resolve_with_program(t, "spell-shot", done["next_effect_state"], spell)


def code(got):
    """The refusal's reason code, whether the bridge or the effect program gave it."""
    return got.get("reason_code") or (got.get("effect_result") or {}).get("reason_code")


def unsupported(got):
    return got.get("unsupported") is True or (got.get("effect_result") or {}).get("unsupported") is True


def dmg(state):
    return {o: state["objects"][o]["damage"] for o in ("a1", "a2", "e1")}


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    # M1 / M2
    declined = reverse(s, may=False)
    if not declined.get("committed"):
        fail("M1 control", f"{declined.get('reason')} {declined.get('reason_code')}")
        return report()
    e = declined["next_effect_state"]
    shot_item = next(i for i in declined["next_timing_state"]["chain"]["items"] if i["id"] == "spell-shot")
    if e["chain_items"]["spell-shot"]["controller"] != "p1" or e["objects"]["shot"]["controller"] != "p1" \
            or shot_item["controller"] != "p1" or e["players"]["p2"]["resources"]["energy"] != 0:
        fail("M1 control", f"{e['chain_items']['spell-shot']} timing {shot_item.get('controller')}")
    got = resolve_spell(declined)
    trace = got.get("trace") if isinstance(got.get("trace"), dict) else {}
    step = next((x for x in trace.get("effect") or [] if x.get("effect_id") == "dmg"), {})
    if not got.get("committed") or dmg(got["next_effect_state"]) != {"a1": 0, "a2": 0, "e1": 0} \
            or step.get("outcome") != "ignored_illegal_target":
        fail("M2 no new choices", f"{got.get('reason') or got.get('reason_code')} {dmg(got.get('next_effect_state') or s)} "
                                  f"{step.get('outcome')}")
    elif "shot" not in got["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        fail("M8 the card", "the spell did not go to its owner's trash")
    # M3
    redone = reverse(s, may=True, remake={"t": ["e1"]})
    got = resolve_spell(redone) if redone.get("committed") else redone
    if not got.get("committed") or dmg(got["next_effect_state"]) != {"a1": 0, "a2": 0, "e1": 3}:
        fail("M3 retarget", f"{got.get('reason') or got.get('reason_code')} {dmg(got.get('next_effect_state') or s)}")
    # M5 (p1's own units are not "an enemy unit" for p1)
    for label, values in (("M5 illegal", ["a2"]), ("M5 illegal", ["a1"])):
        refused = reverse(s, may=True, remake={"t": values})
        if refused.get("committed") or code(refused) != "new_choice_illegal":
            fail(label, f"{refused.get('committed')} {code(refused)}")
    # M6
    m = board(modal=True)
    redone = reverse(m, may=True, mode="deal", remake={"t": ["e1"]}, spell=MODAL)
    got = resolve_spell(redone, MODAL) if redone.get("committed") else redone
    if not got.get("committed") or dmg(got["next_effect_state"])["e1"] != 2:
        fail("M6 mode", f"{got.get('reason') or got.get('reason_code')} {dmg(got.get('next_effect_state') or m)}")
    lacking = reverse(m, may=True, mode="deal", spell=MODAL)
    if lacking.get("committed") or code(lacking) != "new_choices_incomplete":
        fail("M6 mode", f"the new mode without its target: {lacking.get('committed')} {code(lacking)}")
    same_mode = reverse(m, may=True, mode="draw", spell=MODAL)
    if not same_mode.get("committed"):
        fail("M6 mode", f"the same mode again was refused (753 allows it): {code(same_mode)}")
    # M9: a Move's destination remade
    mv = board()
    mv["battlefields"]["bf2"] = {"controller": None, "objects": []}
    mv["battlefields"]["bf1"]["objects"].remove("e1")
    mv["players"]["p2"]["zones"]["base"].append("e1")
    mv["chain_items"]["spell-shot"].update(effect_program_id="move-effects", played_targets=[
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p2", "value": ["e1"],
         "selection_identities": {"e1": "e1@0"}},
        {"decision_id": "dest", "stage": "play_declaration", "kind": "location_selection", "controller": "p2",
         "value": "battlefield:bf1"}])
    from check_effect_ir import settle_contested as settle
    mv = settle(mv)
    redone = reverse(mv, may=True, spell=MOVE, remake={"t": ["e1"]}, destination="battlefield:bf2")
    got = resolve_spell(redone, MOVE) if redone.get("committed") else redone
    where_e1 = [b for b, v in (got.get("next_effect_state") or {}).get("battlefields", {}).items() if "e1" in v["objects"]]
    if not got.get("committed") or where_e1 != ["bf2"]:
        fail("M9 destination", f"{got.get('reason') or code(got)} e1 at {where_e1}")
    # M4: the same target and destination again - allowed in the 10-09 text (753); the 07-16 751.1 refused it
    again = reverse(mv, may=True, spell=MOVE, remake={"t": ["e1"]}, destination="battlefield:bf1")
    got = resolve_spell(again, MOVE) if again.get("committed") else again
    where_e1 = [b for b, v in (got.get("next_effect_state") or {}).get("battlefields", {}).items() if "e1" in v["objects"]]
    if not got.get("committed") or where_e1 != ["bf1"]:
        fail("M4 same again", f"{got.get('reason') or code(got)} e1 at {where_e1}")
    # M11: only the destination remade - every choice is remade (753)
    part = reverse(mv, may=True, spell=MOVE, destination="battlefield:bf2")
    asked = part.get("decision_ids") or (part.get("effect_result") or {}).get("decision_ids") or []
    if part.get("committed") or code(part) != "new_choices_incomplete" or "new:t" not in asked:
        fail("M11 incomplete", f"{part.get('committed')} {code(part)} {asked}")
    # M10: chosen to make new choices, none made - the choices are asked for
    none = reverse(s, may=True)
    if none.get("committed") or code(none) != "new_choices_required":
        fail("M10 none made", f"{none.get('committed')} {code(none)}")
    # M12: played from facedown at bf1 (753.3) - p2's e2 at bf2 is an enemy unit for p1 but not at bf1
    h = board()
    h["battlefields"]["bf2"] = {"controller": None, "objects": ["e2"]}
    h["objects"]["e2"] = unit("p2")
    h["chain_items"]["spell-shot"]["played_from_hidden"] = "bf1"
    h = settle_contested(h)
    outside = reverse(h, may=True, remake={"t": ["e2"]})
    if outside.get("committed") or code(outside) != "new_choice_illegal":
        fail("M12 facedown", f"a new target outside the facedown battlefield: {outside.get('committed')} {code(outside)}")
    inside = reverse(h, may=True, remake={"t": ["e1"]})
    if not inside.get("committed"):
        fail("M12 facedown", f"a new target at the facedown battlefield was refused: {code(inside)}")
    # M13: no enemy unit for p1 anywhere - negated (753.2); the spell keeps its choices (a1, now illegal for p1)
    n = board()
    n["battlefields"]["bf1"]["objects"].remove("e1")
    del n["objects"]["e1"]
    n = settle_contested(n)
    negated = reverse(n, may=True)
    trace = negated.get("trace") if isinstance(negated.get("trace"), dict) else {}
    nstep = next((x for x in trace.get("effect") or [] if x.get("effect_id") == "new"), {})
    kept = ((negated.get("next_effect_state") or {}).get("chain_items") or {}).get("spell-shot", {}).get("played_targets")
    if not negated.get("committed") or nstep.get("negated") is not True or nstep.get("reason") != "no_legal_new_choices" \
            or (kept or [{}])[0].get("value") != ["a1"]:
        fail("M13 none legal", f"{negated.get('reason') or code(negated)} {nstep}")
    # M14 (Core 2026-10-09 135.2.b.7): an instruction checking what was done as the spell was finalized checks the action,
    # not who controls the spell now - p2 paid Meditation's optional cost; taken, the spell draws 2 for p1
    med = board()
    zero = {"energy": 0, "power": {}}
    med["chain_items"]["spell-shot"].update(effect_program_id="meditate-effects", cost_receipt={
        "schema_version": "riftbound-cost-receipt.v1", "play_id": "play-shot", "actor": "p2", "card": "shot",
        "chain_item": "spell-shot", "order_provenance": "printed", "base": dict(zero), "after_base_modifications": dict(zero),
        "total": dict(zero), "paid": True, "rule_locators": ["Core 356"], "discount_order": [],
        "aggregate": {"energy": {"before_total_discounts": 0, "reductions": 0, "final": 0}},
        "payment_events": [{"event_id": "ex1", "kind": "pay_exhaust", "object_id": "e1"}],
        "components": [{"cost_id": "self_offer:k1-cost", "cost_offer_id": "k1-cost", "kind": "exhaust", "mandatory": False,
                        "intent": True, "requested": 1, "increases": [], "reductions": [], "final": 1,
                        "payment_refs": [{"event_id": "ex1"}], "paid": True, "rule_locators": ["Core 356.2.b.1"]}]})
    med["chain_items"]["spell-shot"].pop("played_targets", None)
    for card in ("d1", "d2", "d3"):
        med["objects"][card] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                "damage": 0, "exhausted": False}
        med["players"]["p1"]["zones"]["main_deck"].append(card)
    med = settle_contested(med)
    # the caller hands the spell's program the receipt of its play, as the real resolution does
    paid = {**MEDITATE, "cost_receipt": med["chain_items"]["spell-shot"]["cost_receipt"]}
    taken = reverse(med, may=False, spell=paid)
    hand = len(med["players"]["p1"]["zones"]["hand"])
    got = resolve_spell(taken, paid) if taken.get("committed") else taken
    drawn = len((got.get("next_effect_state") or med)["players"]["p1"]["zones"]["hand"]) - hand
    if not got.get("committed") or drawn != 2:
        fail("M14 paid by p2", f"{got.get('reason') or code(got)}: p1 drew {drawn}, not 2")
    # M7
    blind = reverse(s, may=True, remake={"t": ["e1"]}, programs=False)
    if blind.get("committed") or code(blind) != "new_choices_program_unknown" or not unsupported(blind):
        fail("M7 no program", f"{blind.get('committed')} {code(blind)}")
    # V
    for label, mutate in (("not optional", lambda p: p["effects"][1].pop("optional")),
                          ("not linked", lambda p: p["effects"][1].update(linked={"effect_id": "nothing"}))):
        bad = copy.deepcopy(REVERSAL)
        mutate(bad)
        if not validate_program(bad):
            fail("V shape", f"make_new_choices {label} validated")
    low = cg.compile_clause("Gain control of a spell. You may make new choices for it.", cg.load_grammar())
    if [e.get("op") for e in low.get("program_effects") or []] != ["gain_control_of_spell", "make_new_choices"]:
        fail("V grammar", f"{low.get('production_id')} {low.get('program_effects')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: gaining control of a spell and making new choices for it")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: a spell taken on the Chain is its new controller's - card, Chain item and timing chain - and resolves for "
          "them; nothing paid moves; declined, its choices stand unrecomputed; remade, each new target legal for "
          "the new controller, every choice remade - the same one again allowed - within the item's restrictions, none legal "
          "negated (10-09 753); without the spell's program, refused by name (M1-M13, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
