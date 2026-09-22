#!/usr/bin/env python3
"""Regression gate for Legion (Core 812; 727.1; 419.4.b).

    812.1.b.1  Legion is short for "If you have played another card this turn, this card
               gains [Text]."
    812.1.c    active as long as a card different from the one with Legion has been
               Finalized by you this turn
    812.2      one card satisfies every Legion that player controls
    419.4.b    non-triggered checks of cards played read whether they were Finalized -
               a countered card still counts
    812.3      Legion is a characteristic

Must hold, through the real play transaction and the real play completion:
  - play_card records each card it Finalizes, per player and per turn; an activated
    ability is not a card and is not recorded;
  - the condition: the Legion card itself does not count; another card does; the
    opponent's card does not; last turn's card does not; a card without Legion has none;
  - "[Legion][>] I cost N less." lowered by the engine grammar: without another card the
    full cost is due, after another card the reduction applies;
  - "[Legion][>] When you play me, ..." lowered by the engine grammar: the trigger is
    scheduled at play completion only if another card was Finalized this turn;
  - a Legion condition is refused on any trigger but a play trigger;
  - an activated ability gated by Legion (GPT 2026-09-22, option b) does not exist while
    the condition fails: activation_condition_not_met before anything is paid or
    exhausted; after another card it activates; the gate is the source's, per ability;
  - mutation: without the ledger no Legion is ever active.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import evaluate_condition, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
LEGION = {"kind": "another_card_finalized_this_turn"}


def lowered(text):
    return (CG.compile_clause(text, CG.load_grammar()).get("passive") or {}).get("object_fields") or {}


def board(*, energy=3, legion_fields=None):
    """c1: an ordinary spell in hand (0 cost); c2: the Legion unit in hand (cost 3)."""
    state = base_state()
    state["turn_id"] = "turn-3"
    for card in ("c1", "c2"):
        state["players"]["p1"]["zones"]["main_deck"].remove(card)
        state["players"]["p1"]["zones"]["hand"].append(card)
    state["objects"]["c2"].update({"kind": "unit", "base_might": 2})
    state["objects"]["c2"].update(copy.deepcopy(legion_fields or {}))
    state["players"]["p1"]["resources"] = {"energy": energy, "power": {}}
    return state


def spell(card="c1", play_id="play-0", item_id="spell-0"):
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": play_id, "actor": "p1", "card": card,
            "chain_item": {"id": item_id, "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}}, "payment_context": dict(CLOSED)}


def unit(card="c2"):
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": card,
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 3, "power": {}}}, "entry_location": {"kind": "base"},
            "payment_context": dict(CLOSED)}


def after_spell(state):
    played = PT.play_card(fixture(), state, spell())
    assert played.get("committed"), played.get("reason")
    after = copy.deepcopy(played["next_effect_state"])
    # the spell is taken off the chain as if it had been countered: it was Finalized (419.4.b)
    after["chain_items"].pop("spell-0")
    if not after["chain_items"]:
        del after["chain_items"]
    after["players"]["p1"]["zones"]["trash"].append("c1")
    return played, after


def main() -> int:
    errors: list[str] = []

    # --- the ledger ------------------------------------------------------------------------------
    played, countered = after_spell(board())
    ledger = played["next_effect_state"]["players"]["p1"].get("cards_finalized_this_turn")
    if ledger != {"turn-3": ["c1"]}:
        errors.append(f"play_card did not record the Finalized card: {ledger}")
    if validate_state(countered):
        errors.append(f"the state after a Finalized, countered spell is invalid: {validate_state(countered)}")
    if IR.cards_finalized_this_turn(countered, "p1") != ["c1"]:
        errors.append("a countered card no longer counts as Finalized (419.4.b)")

    import check_legend_activation as LA
    legend = LA.legend_board()
    activated = PT.play_card(fixture(), legend, LA.activation(), engine_decisions=LA.target(legend), effect_program=LA.BUFF)
    if not activated.get("committed") or activated["next_effect_state"]["players"]["p1"].get("cards_finalized_this_turn"):
        errors.append(f"an activated ability was recorded as a Finalized card: {activated.get('reason_code')}")

    # --- the condition ---------------------------------------------------------------------------
    no_keyword = copy.deepcopy(countered)
    if evaluate_condition(no_keyword, LEGION, controller="p1", object_id="c2") is not False:
        errors.append("a card without Legion was treated as having an active Legion (812.3)")
    for card in ("c1", "c2"):
        countered["objects"][card]["keywords"] = ["legion"]
    if evaluate_condition(countered, LEGION, controller="p1", object_id="c2") is not True:
        errors.append("another card Finalized this turn did not make Legion active (812.1.c)")
    if evaluate_condition(countered, LEGION, controller="p1", object_id="c1") is not False:
        errors.append("the Legion card itself counted as 'another card'")
    if evaluate_condition(countered, LEGION, controller="p2", object_id="c2") is not False:
        errors.append("p1's card made p2's Legion active")
    last_turn = copy.deepcopy(countered); last_turn["turn_id"] = "turn-4"
    if evaluate_condition(last_turn, LEGION, controller="p1", object_id="c2") is not False:
        errors.append("a card Finalized last turn made Legion active this turn")
    bad = copy.deepcopy(countered); bad["players"]["p1"]["cards_finalized_this_turn"] = {"turn-3": ["c1", "c1"]}
    if not validate_state(bad):
        errors.append("a ledger listing a card twice was accepted")

    # --- "[Legion][>] I cost N less." --------------------------------------------------------------
    cost_fields = lowered("[Legion][>] I cost :rb_energy_2: less.")
    if cost_fields.get("keywords") != ["legion"] or [m.get("condition") for m in cost_fields.get("printed_cost_modifications", [])] != [LEGION]:
        errors.append(f"the Legion cost reduction did not lower to a conditioned printed reduction: {cost_fields}")
    fresh = board(energy=1, legion_fields=cost_fields)
    alone = PT.play_card(fixture(), fresh, unit())
    if alone.get("committed") or alone.get("reason_code") != "cost_unpayable":
        errors.append(f"the Legion reduction applied with no other card played this turn: {alone.get('reason_code')}")
    _, primed = after_spell(board(energy=1, legion_fields=cost_fields))
    with_other = PT.play_card(fixture(), primed, unit())
    if not with_other.get("committed"):
        errors.append(f"the Legion reduction did not apply after another card: {with_other.get('reason_code')} {with_other.get('reason')}")
    elif with_other["next_effect_state"]["players"]["p1"]["resources"]["energy"] != 0:
        errors.append("the Legion reduction was not the printed 2")
    elif with_other["next_effect_state"]["players"]["p1"]["cards_finalized_this_turn"] != {"turn-3": ["c1", "c2"]}:
        errors.append("the Legion unit's own play was not recorded after the first card")

    # --- "[Legion][>] When you play me, ..." --------------------------------------------------------
    trig_fields = lowered("[Legion][>] When you play me, buff me.")
    triggers = trig_fields.get("play_triggers") or []
    if trig_fields.get("keywords") != ["legion"] or [t.get("condition") for t in triggers] != [LEGION]:
        errors.append(f"the Legion play trigger did not lower to a conditioned play trigger: {trig_fields}")
    concrete = [{**t, "controller": "p1", "source_object": "c2", "effect_program_id": "c2-on-play"} for t in triggers]

    def completed(state):
        state["objects"]["c2"]["play_triggers"] = copy.deepcopy(concrete)
        state["objects"]["c2"]["keywords"] = ["legion"]
        play = PT.play_card(fixture(), state, unit())
        assert play.get("committed"), play.get("reason")
        timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
        return resolve_with_program(timing, "unit-1", play["next_effect_state"], None)

    quiet = completed(board(energy=3))
    if not quiet.get("committed") or quiet["next_timing_state"]["chain"]["items"]:
        errors.append(f"the Legion play trigger fired with no other card played: {quiet.get('reason')}")
    elif [t["reason"] for t in quiet["trace"]["chain_card"][0].get("play_triggers_inactive", [])] != ["legion_not_active"]:
        errors.append("the inactive Legion trigger was not named in the trace")
    _, primed = after_spell(board(energy=3))
    loud = completed(primed)
    items = loud.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not loud.get("committed") or [i["id"] for i in items] != ["on-play"]:
        errors.append(f"the Legion play trigger did not fire after another card: {loud.get('reason')} {[i.get('id') for i in items]}")
    if IR.has_keyword(primed | {"objects": {**primed["objects"], "c2": {**primed["objects"]["c2"], "keywords": ["legion"]}}}, "c2", "legion") is not True:
        errors.append("Legion is not a characteristic other effects can read (812.3)")

    # --- Legion over an activated ability (GPT 2026-09-22, option b) ------------------------------
    # the ability does not exist while the condition fails: refused before anything is paid
    def gated_legend():
        state = LA.legend_board()
        state["turn_id"] = "turn-3"
        state["objects"]["l1"].update({"keywords": ["legion"], "ability_conditions": {"l1:a1": dict(LEGION)}})
        state["players"]["p1"]["zones"]["main_deck"].remove("c1")
        state["players"]["p1"]["zones"]["hand"].append("c1")
        return state
    closed = gated_legend()
    if validate_state(closed):
        errors.append(f"a Legion-gated ability is not a valid state: {validate_state(closed)}")
    refused = PT.play_card(fixture(), closed, LA.activation(), engine_decisions=LA.target(closed), effect_program=LA.BUFF)
    if refused.get("committed") or refused.get("reason_code") != "activation_condition_not_met":
        errors.append(f"a Legion-gated ability was activated with no other card played: {refused.get('reason_code')}")
    elif any(step.get("stage") == "payment" for step in refused.get("trace", [])) or refused.get("next_effect_state_hash") != refused.get("input_effect_state_hash"):
        errors.append("the refused Legion ability paid or exhausted something first; it must not exist, not be paid for and left empty")
    opened = gated_legend()
    spelled = PT.play_card(fixture(), opened, spell())
    after = copy.deepcopy(spelled["next_effect_state"])
    after["chain_items"].pop("spell-0")
    if not after["chain_items"]:
        del after["chain_items"]
    after["players"]["p1"]["zones"]["trash"].append("c1")
    allowed = PT.play_card(fixture(), after, LA.activation(), engine_decisions=LA.target(after), effect_program=LA.BUFF)
    if not allowed.get("committed"):
        errors.append(f"a Legion-gated ability was refused after another card was played: {allowed.get('reason_code')} {allowed.get('reason')}")
    forged = gated_legend(); forged["objects"]["l1"]["ability_conditions"] = {"l1:a1": {"kind": "nonesuch"}}
    if not validate_state(forged):
        errors.append("an ability condition that is no condition.v1 was accepted")

    # --- a Legion condition belongs on a play trigger only -----------------------------------------
    wrong = board()
    wrong["objects"]["c2"]["death_triggers"] = [{**concrete[0], "trigger_id": "dk"}]
    if not validate_state(wrong):
        errors.append("a Legion condition on a death trigger was accepted; nothing would read it there")
    other = lowered("[Legion][>] Draw 1.")
    if other:
        errors.append(f"a Legion over an ability form the engine does not gate was lowered: {other}")

    # --- mutation: no ledger, no Legion --------------------------------------------------------------
    saved = IR.cards_finalized_this_turn
    try:
        IR.cards_finalized_this_turn = lambda *_a, **_k: []
        mutated = PT.play_card(fixture(), after_spell(board(energy=1, legion_fields=cost_fields))[1], unit())
    finally:
        IR.cards_finalized_this_turn = saved
    if mutated.get("committed"):
        errors.append("mutation not caught: with an empty ledger the Legion reduction still applied")

    if errors:
        print("FAILED: Legion checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: play_card records each Finalized card per player and turn, a countered one included (419.4.b); Legion "
          "is active only after another card of its controller this turn (812.1.c); the lowered cost reduction and "
          "play trigger apply only then; a Legion condition off a play trigger is refused; an empty ledger is caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
