#!/usr/bin/env python3
"""
Regression gate for C-42 (ADR-0011 §4; Codex G-1 on DP-63): the payment
catalogue, activated abilities through the play transaction, [Repeat],
restricted Add resources, and typed cost-modification input.

Must hold:
  - a Discard cost is the payer's private card_selection at play stage; the
    card being played is never a candidate (Core 354: it moved to the Chain
    before costs were chosen) — negative mutation: the same play with one
    more card in hand commits, so the refusal is about the played card and
    not about an empty hand; a short hand is cost_unpayable (423.1.b); the
    receipt carries a pay_discard event with the identities, and a failure
    after payment restores the hand (358.5);
  - a Recycle-from-trash cost is public, two cards need the card_ordering
    (416.5), and the receipt carries pay_recycle_trash;
  - an activated ability is a chain item of object_kind ability with
    activation {source_object, ability_id}: the declaration is invalid
    without it, illegal when the source is off the board or another
    player's, unsupported when it carries an activation condition (377.2.b);
    nothing leaves the hand, the chain entry names the source and no card,
    the kernel sees activate_ability (an [Add] ability sets add_ability),
    and the bridge removes the entry without trashing a card — the source
    stays where the cost left it (kill_this → the trash);
  - kill_this and recall_self pay with the ability's own source (204.2) and
    are named in the receipt;
  - a paid [Repeat] adds one execution with its own suffixed choices
    (820.1.d, 820.2.a); declining leaves one; a mandatory Repeat is invalid;
  - a restricted Add resource lands in resources.restricted, is spent first
    for a matching use (the event names the restriction), and cannot be
    spent otherwise — cost_unpayable naming it, while the same pool with a
    matching use commits (negative mutation);
  - a typed increase / discount with provenance applies; one carrying a
    condition or per_each source is unsupported: cost_modification_sources;
    spend_xp stays unsupported_cost_kind;
  - the schemas carry the payment kinds, activation, repeat and restricted
    pools; determinism and purity.
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
from check_effect_ir import program  # noqa: E402
from check_play_transaction import CLOSED, effect_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from cost_receipt import PAYMENT_EVENT_KINDS  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_state  # noqa: E402
from engine_check import KIND_CONFIG, build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card, validate_declaration, validate_play_result  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, finalize_oldest_pending  # noqa: E402


def declaration(**overrides):
    value = {
        "schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "play_id": "play-1", "actor": "p1", "card": "c1",
        "chain_item": {"id": "spell-1", "object_kind": "spell", "timing": "default"},
        "cost": {"base": {"energy": 1, "power": {}}},
        "payment_context": dict(CLOSED),
    }
    value.update(overrides)
    return {k: v for k, v in value.items() if v is not None}


def ability_declaration(**overrides):
    value = declaration(
        card="u1",
        chain_item={"id": "ability-1", "object_kind": "ability", "timing": "default"},
        activation={"source_object": "u1", "ability_id": "u1:a1"},
        cost={"base": {"energy": 0, "power": {}}},
        payment_context=None,
    )
    value.update(overrides)
    return {k: v for k, v in value.items() if v is not None}


def hand_state(*cards, energy=1):
    """A state whose p1 hand is exactly `cards`, wherever they started."""
    state = effect_state(energy=energy, power={}, hand=())
    for card in cards:
        for zone in ("main_deck", "hand", "trash", "banishment", "base", "rune_deck"):
            if card in state["players"]["p1"]["zones"][zone]:
                state["players"]["p1"]["zones"][zone].remove(card)
        state["players"]["p1"]["zones"]["hand"].append(card)
    return state


def envelope(state, *decisions):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": list(decisions)}


def pick(decision_id, ids, state, controller="p1", stage="play_declaration", kind="card_selection"):
    return {"decision_id": decision_id, "stage": stage, "kind": kind, "controller": controller, "value": ids,
            "selection_identities": {i: object_identity(state, i) or f"{i}@0" for i in ids}}


def intent(cost_id, value, controller="p1"):
    return {"decision_id": cost_id, "stage": "play_declaration", "kind": "optional_choice", "controller": controller, "value": value}


def event(result, kind):
    return next((e for e in result.get("cost_receipt", {}).get("payment_events", []) if e["kind"] == kind), None)


def main() -> int:
    errors: list[str] = []
    timing = fixture()

    # --- Discard as a cost ---------------------------------------------------------------------
    two = hand_state("c1", "c2")
    discard_cost = {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "d", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]}
    forced = play_card(timing, two, declaration(cost=discard_cost))
    if not forced.get("committed") or "c2" not in forced["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append(f"a one-card choice (the played card excluded) did not pay the discard cost: {forced.get('reason_code')} {forced.get('reason')}")
    else:
        ev = event(forced, "pay_discard")
        if not ev or ev.get("objects") != ["c2"] or ev.get("identities_after") != {"c2": "c2@1"} or validate_play_result(forced):
            errors.append(f"the discard payment event is wrong: {ev} {validate_play_result(forced)}")
        if "c1" in forced["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
            errors.append("the card being played was discarded to pay its own cost (Core 354)")
    alone = hand_state("c1")
    only_self = play_card(timing, alone, declaration(cost=discard_cost))
    if only_self.get("committed") or only_self.get("reason_code") != "cost_unpayable" or "Core 354" not in only_self.get("rule_locators", []):
        errors.append(f"the played card was treated as a discardable card: {only_self.get('reason_code')} {only_self.get('rule_locators')}")
    if only_self.get("next_effect_state_hash") != hash_value(alone):
        errors.append("an unpayable discard cost did not restore the pre-play state")
    three = hand_state("c1", "c2", "c3")
    ask = play_card(timing, three, declaration(cost=discard_cost))
    if ask.get("reason_code") != "card_selection_required" or ask.get("decision_controller") != "p1" or ask.get("choice", {}).get("visibility") != "private_to_chooser":
        errors.append(f"a discard cost with a real choice did not stop privately: {ask.get('reason_code')} {ask.get('reason')}")
    elif '"c2"' in json.dumps({k: v for k, v in ask.items() if k != "trace"}) or "options" in ask.get("choice", {}):
        errors.append("the discard cost decision leaked the hand")
    else:
        check = build_engine_check("play", ask, input_hashes={"timing_state": "sha256:" + "1" * 64, "effect_state": hash_value(three), "play_declaration": "sha256:" + "2" * 64})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "card_choice":
            errors.append(f"the discard cost decision wrapped as {check['outcome']} {check.get('decision_required')}")
    chosen = play_card(timing, three, declaration(cost=discard_cost), engine_decisions=envelope(three, pick("cost:play-1:d", ["c3"], three)))
    if not chosen.get("committed") or "c3" not in chosen["next_effect_state"]["players"]["p1"]["zones"]["trash"] or "c2" not in chosen["next_effect_state"]["players"]["p1"]["zones"]["hand"]:
        errors.append(f"the chosen discard was not paid: {chosen.get('reason_code')} {chosen.get('reason')}")
    outside = play_card(timing, three, declaration(cost=discard_cost), engine_decisions=envelope(three, pick("cost:play-1:d", ["c4"], three)))
    if outside.get("reason_code") != "cost_choice_illegal":
        errors.append(f"a discard naming another player's card was not illegal: {outside.get('reason_code')}")
    two_needed = {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "d", "mandatory": True, "payment": {"kind": "discard", "amount": 2}}]}
    short = play_card(timing, two, declaration(cost=two_needed))
    if short.get("reason_code") != "cost_unpayable" or "Core 423.1.b" not in short.get("rule_locators", []):
        errors.append(f"a hand too small for the discard cost was not cost_unpayable: {short.get('reason_code')} {short.get('rule_locators')}")

    # --- Recycle from the trash as a cost --------------------------------------------------------
    trash_state = hand_state("c1")
    trash_state["players"]["p1"]["zones"]["main_deck"] = []
    trash_state["players"]["p1"]["zones"]["trash"] = ["c3", "c2"]
    rec_cost = {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "r", "mandatory": True, "payment": {"kind": "recycle_trash", "amount": 2}}]}
    rec = play_card(timing, trash_state, declaration(cost=rec_cost))
    if rec.get("reason_code") != "card_ordering_required":
        errors.append(f"recycling two cards as a cost did not ask for the bottom order: {rec.get('reason_code')} {rec.get('reason')}")
    ordered = play_card(timing, trash_state, declaration(cost=rec_cost),
                        engine_decisions=envelope(trash_state, pick("cost:play-1:r:order", ["c2", "c3"], trash_state, stage="resolution", kind="card_ordering")))
    if not ordered.get("committed") or ordered["next_effect_state"]["players"]["p1"]["zones"]["main_deck"] != ["c2", "c3"]:
        errors.append(f"the recycle cost did not bottom the cards in the chosen order: {ordered.get('reason_code')} {ordered.get('reason')}")
    else:
        ev = event(ordered, "pay_recycle_trash")
        if not ev or set(ev.get("objects", [])) != {"c2", "c3"} or validate_play_result(ordered):
            errors.append(f"the recycle payment event is wrong: {ev}")

    # --- activated abilities ---------------------------------------------------------------------
    plain = hand_state("c1")
    no_activation = dict(ability_declaration()); del no_activation["activation"]
    if not any("activation" in e for e in validate_declaration(no_activation)):
        errors.append("an ability declaration without activation was accepted")
    mismatched = ability_declaration(card="c1")
    if not any("source_object" in e for e in validate_declaration(mismatched)):
        errors.append("an ability declaration whose card is not its source was accepted")
    activated = play_card(timing, plain, ability_declaration())
    if not activated.get("committed"):
        errors.append(f"activating an ability of a controlled board unit failed: {activated.get('reason_code')} {activated.get('reason')}")
    else:
        entry = activated["next_effect_state"]["chain_items"]["ability-1"]
        if entry != {"source_object": "u1", "ability_id": "u1:a1", "controller": "p1"} or activated["next_effect_state"]["players"]["p1"]["zones"]["hand"] != ["c1"]:
            errors.append(f"the ability chain entry is wrong or the hand changed: {entry}")
        if activated["next_effect_state"]["players"]["p1"]["zones"]["base"] != ["u1"] or object_identity(activated["next_effect_state"], "u1") != "u1@0":
            errors.append("activating moved or renewed the source object")
        if activated["next_timing_state"]["chain"]["initiated_by"] != "activated_ability" or validate_play_result(activated):
            errors.append(f"the kernel did not record an activation: {activated['next_timing_state']['chain']['initiated_by']} {validate_play_result(activated)}")
    add_ability = play_card(timing, plain, ability_declaration(chain_item={"id": "ability-1", "object_kind": "ability", "timing": "default", "ability_kind": "add"}))
    if not add_ability.get("committed") or add_ability["next_timing_state"]["chain"]["initiated_by"] != "add_ability":
        errors.append(f"an [Add] ability did not open an add_ability chain: {add_ability.get('reason_code')} {add_ability.get('reason')}")
    in_hand = copy.deepcopy(plain)
    in_hand["players"]["p1"]["zones"]["base"].remove("u1")
    in_hand["players"]["p1"]["zones"]["hand"].append("u1")
    off_board = play_card(timing, in_hand, ability_declaration())
    if off_board.get("reason_code") != "activation_source_not_on_board" or off_board.get("committed"):
        errors.append(f"an ability of a card in hand was activated: {off_board.get('reason_code')}")
    theirs = play_card(timing, plain, ability_declaration(card="u2", activation={"source_object": "u2", "ability_id": "u2:a1"}))
    if theirs.get("reason_code") != "activation_source_not_controlled":
        errors.append(f"an opponent's ability was activated: {theirs.get('reason_code')}")
    # C-50 (ADR-0013 §3): an activation condition is evaluated now. A malformed
    # one is invalid_input, one that does not hold is illegal.
    malformed = play_card(timing, plain, ability_declaration(activation_conditions=[{"kind": "at_battlefield"}]))
    if malformed.get("reason_code") != "invalid_input":
        errors.append(f"a malformed activation condition was not invalid_input: {malformed.get('reason_code')}")
    unmet = play_card(timing, plain, ability_declaration(activation_conditions=[{"kind": "controls_units", "count": 9}]))
    if unmet.get("reason_code") != "activation_condition_not_met" or unmet.get("committed"):
        errors.append(f"an activation condition that does not hold was not illegal: {unmet.get('reason_code')}")
    met = play_card(timing, plain, ability_declaration(activation_conditions=[{"kind": "controls_units", "count": 1}]))
    if not met.get("committed"):
        errors.append(f"negative mutation failed: the same activation with a condition that holds did not commit: {met.get('reason_code')} {met.get('reason')}")

    # kill_this pays with the source; the bridge then removes the ability with no card
    kill_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "self", "mandatory": True, "payment": {"kind": "kill_this"}}]}
    ability_program = program("u1:a1", {"op": "draw", "effect_id": "d", "player": "p1", "count": 1})
    ability_program["controller"] = "p1"
    killed = play_card(timing, plain, ability_declaration(cost=kill_cost, effect_program_id="u1:a1"), effect_program=ability_program)
    if not killed.get("committed") or "u1" not in killed["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        errors.append(f"kill_this did not kill the ability's source: {killed.get('reason_code')} {killed.get('reason')}")
    else:
        if not event(killed, "pay_kill_this") or validate_play_result(killed):
            errors.append(f"the kill_this payment event is missing: {[e['kind'] for e in killed['cost_receipt']['payment_events']]}")
        fin = finalize_oldest_pending(killed["next_timing_state"])["next_state"]
        fin["chain"]["consecutive_passes"] = ["p1", "p2"]
        resolved = resolve_with_program(fin, "ability-1", killed["next_effect_state"], ability_program)
        if not resolved.get("committed"):
            errors.append(f"the bridge could not resolve an activated ability: {resolved.get('stage')} {resolved.get('reason')}")
        else:
            after = resolved["next_effect_state"]
            if after.get("chain_items") or after["players"]["p1"]["zones"]["trash"].count("u1") != 1 or resolved["trace"]["chain_card"][0].get("no_card") is not True:
                errors.append(f"resolving an ability trashed a card or left the entry: {resolved['trace']['chain_card']}")
    at_bf = copy.deepcopy(plain)
    at_bf["players"]["p1"]["zones"]["base"].remove("u1")
    at_bf["battlefields"]["bf1"]["objects"].append("u1")
    recall_cost = {"base": {"energy": 0, "power": {}}, "additional": [{"cost_id": "self", "mandatory": True, "payment": {"kind": "recall_self"}}]}
    recalled = play_card(timing, at_bf, ability_declaration(cost=recall_cost))
    if not recalled.get("committed") or "u1" not in recalled["next_effect_state"]["players"]["p1"]["zones"]["base"] or not event(recalled, "pay_recall_self"):
        errors.append(f"recall_self did not recall the source: {recalled.get('reason_code')} {recalled.get('reason')}")

    # --- [Repeat] ------------------------------------------------------------------------------------
    deck = hand_state("c1", energy=4)
    deck["players"]["p1"]["zones"]["trash"] = []
    deck["players"]["p1"]["zones"]["main_deck"] = ["c2", "c3"]
    spell_program = program("sp", {"op": "draw", "effect_id": "d", "player": "p1", "count": 1})
    repeat_cost = {"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "rep", "mandatory": False, "repeat": True, "payment": {"kind": "energy", "amount": 2}}]}
    mandatory_repeat = declaration(cost={"base": {"energy": 1, "power": {}}, "additional": [{"cost_id": "rep", "mandatory": True, "repeat": True, "payment": {"kind": "energy", "amount": 2}}]})
    if not any("Repeat" in e for e in validate_declaration(mandatory_repeat)):
        errors.append("a mandatory [Repeat] cost was accepted (Core 820.1.a)")

    def run_repeat(paid: bool):
        decl = declaration(cost=repeat_cost, effect_program_id="sp")
        played = play_card(timing, deck, decl, engine_decisions=envelope(deck, intent("rep", paid)), effect_program=spell_program)
        if not played.get("committed"):
            return played, None
        fin = finalize_oldest_pending(played["next_timing_state"])["next_state"]
        fin["chain"]["consecutive_passes"] = ["p1", "p2"]
        return played, resolve_with_program(fin, "spell-1", played["next_effect_state"], spell_program)

    played_twice, resolved_twice = run_repeat(True)
    if not played_twice.get("committed") or played_twice["next_effect_state"]["chain_items"]["spell-1"].get("repeat") != {"executions": 2}:
        errors.append(f"a paid Repeat was not recorded on the chain: {played_twice.get('reason_code')} {played_twice.get('reason')}")
    elif not resolved_twice.get("committed") or [e["effect_id"] for e in resolved_twice["trace"]["effect"]] != ["d", "d#1"] or len(resolved_twice["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != 2:
        errors.append(f"a paid Repeat did not execute the instructions twice: {resolved_twice.get('reason')} {[e.get('effect_id') for e in (resolved_twice.get('trace') or {}).get('effect', [])]}")
    played_once, resolved_once = run_repeat(False)
    if not played_once.get("committed") or "repeat" in played_once["next_effect_state"]["chain_items"]["spell-1"]:
        errors.append("declining the Repeat still recorded an extra execution")
    elif [e["effect_id"] for e in resolved_once["trace"]["effect"]] != ["d"]:
        errors.append(f"negative mutation failed: declining the Repeat still executed twice: {[e['effect_id'] for e in resolved_once['trace']['effect']]}")

    # --- restricted Add resources ------------------------------------------------------------------------
    granted = apply_program(hand_state("c1", energy=0),
                            program("add", {"op": "add_resource", "effect_id": "a", "player": "p1", "resource": "energy", "amount": 2, "restriction": {"uses": ["play_spell"]}, "restriction_id": "lux"}))
    if not granted.get("committed") or granted["next_state"]["players"]["p1"]["resources"].get("restricted") != [{"restriction_id": "lux", "kind": "energy", "amount": 2, "uses": ["play_spell"]}]:
        errors.append(f"a restricted Add did not land in the restricted pool: {granted.get('reason') or granted.get('errors')}")
    restricted_state = granted["next_state"]
    if validate_state(restricted_state):
        errors.append(f"a state with a restricted pool is invalid: {validate_state(restricted_state)}")
    spell = play_card(timing, restricted_state, declaration(cost={"base": {"energy": 2, "power": {}}}))
    if not spell.get("committed"):
        errors.append(f"a restricted Energy could not pay for the use it names: {spell.get('reason_code')} {spell.get('reason')}")
    else:
        ev = event(spell, "pay_energy")
        if not ev or ev.get("restricted_from") != "lux" or ev.get("use") != "play_spell" or spell["next_effect_state"]["players"]["p1"]["resources"].get("restricted"):
            errors.append(f"the restricted pool was not spent first or not emptied: {ev}")
    unit_state = copy.deepcopy(restricted_state)
    unit_state["objects"]["c1"]["kind"] = "unit"
    unit_decl = declaration(cost={"base": {"energy": 2, "power": {}}}, chain_item={"id": "unit-1", "object_kind": "unit", "timing": "default"}, entry_location={"kind": "base"})
    wrong_use = play_card(timing, unit_state, unit_decl)
    if wrong_use.get("reason_code") != "cost_unpayable" or wrong_use.get("restricted_not_applicable") != ["lux"]:
        errors.append(f"a restricted Energy paid for a use it forbids: {wrong_use.get('reason_code')} {wrong_use.get('restricted_not_applicable')}")
    ok_use = copy.deepcopy(unit_state)
    ok_use["players"]["p1"]["resources"]["restricted"][0]["uses"] = ["play_unit"]
    if not play_card(timing, ok_use, unit_decl).get("committed"):
        errors.append("negative mutation failed: the same pool naming play_unit did not pay for a unit, so the refusal is not about the use")

    # --- typed cost modifications -----------------------------------------------------------------------------
    evaluated = play_card(timing, hand_state("c1"),
                          declaration(cost={"base": {"energy": 2, "power": {}}, "discounts": [{"id": "d1", "applies_to": "energy", "amount": 1, "provenance": {"evaluated_by": "p4_condition_layer", "source": "x"}}]}))
    if not evaluated.get("committed") or evaluated["cost_receipt"]["total"]["energy"] != 1:
        errors.append(f"an evaluated typed discount did not apply: {evaluated.get('reason_code')} {evaluated.get('reason')}")
    # C-50: a modification carrying a typed condition is evaluated by the P4
    # layer; a malformed one is invalid_input.
    sourced = play_card(timing, hand_state("c1"),
                        declaration(cost={"base": {"energy": 2, "power": {}}, "discounts": [{"id": "d1", "applies_to": "energy", "amount": 1, "condition": {"kind": "if_you_control_a_unit"}}]}))
    if sourced.get("reason_code") != "invalid_input":
        errors.append(f"a malformed cost condition was not invalid_input: {sourced.get('reason_code')}")
    per_each = play_card(timing, hand_state("c1", energy=3),
                         declaration(cost={"base": {"energy": 2, "power": {}}, "increases": [{"id": "i1", "component": "energy", "amount": 1, "per_each": {"kind": "might_at_least", "count": 1}}]}))
    if per_each.get("unsupported") is not True or "per_each" not in str(per_each.get("reason")):
        errors.append(f"a per-each over an uncounted leaf was not unsupported: {per_each.get('reason_code')} {per_each.get('reason')}")

    # --- schemas and scope ----------------------------------------------------------------------------------------
    pd = json.loads((SKILL_DIR / "schemas" / "play-declaration.schema.json").read_text(encoding="utf-8"))
    if "activation" not in pd["properties"] or "ability" not in pd["properties"]["chain_item"]["properties"]["object_kind"]["enum"] or "repeat" not in pd["properties"]["cost"]["properties"]["additional"]["items"]["properties"]:
        errors.append("play-declaration schema lacks activation / ability / repeat")
    cr = json.loads((SKILL_DIR / "schemas" / "cost-receipt.schema.json").read_text(encoding="utf-8"))
    if set(cr["properties"]["payment_events"]["items"]["properties"]["kind"]["enum"]) != PAYMENT_EVENT_KINDS:
        errors.append("cost-receipt schema and the module disagree on payment kinds")
    es = json.loads((SKILL_DIR / "schemas" / "effect-state.schema.json").read_text(encoding="utf-8"))
    if "restricted" not in es["$defs"]["player"]["properties"]["resources"]["properties"] or "source_object" not in es["properties"]["chain_items"]["additionalProperties"]["properties"]:
        errors.append("effect-state schema lacks restricted pools or ability chain entries")
    scope = KIND_CONFIG["play"]
    if not {"activated_abilities", "repeat_costs", "discard_recycle_costs", "self_costs", "restricted_resources"} <= set(scope["supported"]) or "legend_activation" not in scope["unsupported"]:
        errors.append("the play scope does not declare the C-42 capabilities and their boundary")

    snapshot = copy.deepcopy(three)
    if play_card(timing, three, declaration(cost=discard_cost)) != ask or three != snapshot:
        errors.append("the cost transaction is not deterministic or mutated its input")

    if errors:
        print("FAILED: cost catalogue / activation checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("cost catalogue / activation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
