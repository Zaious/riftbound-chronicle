#!/usr/bin/env python3
"""One Unit ability, two trigger conditions of different kinds: "When I'm played and when I conquer".

A Play Effect (Core 383.4.a, 419.4.a: it triggers when the act of playing the card is completed by
its resolution) and a Conquer Effect (Core 383.4.c, 383.4.c.2.a: the Unit is present at the
Battlefield its controller Conquers, 469.1) - one ability. The clause grammar lowers it to the
SAME descriptor, the same trigger_id, in play_triggers and conquer_triggers. Held here:

  lowering   both fields carry one identical descriptor each; "When you play me" alone still
             lowers to play_triggers only and "When I conquer" alone to conquer_triggers only;
             "When I'm played" alone is not this production
  played     a Unit carrying it, played to its Base and resolved by the entry procedure,
             schedules exactly ONE Pending triggered item, in the play batch
  conquer    the Scoring Step's conquer pass over a Battlefield where that Unit stands yields
             exactly ONE descriptor for it; the same Unit in its Base yields none (the Unit's
             own scope, 383.4.c.2.a); a Hold of that Battlefield yields none
  neither    a Unit without the ability yields nothing on play or on conquer

The real flows (the play transaction; a Move, Contested, the Showdown, control resolution) are
witnessed card by card in the private overlay's compiler; this is the engine's own contract.

    python skill/scripts/check_played_and_conquer_trigger.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import battlefield_control as BC  # noqa: E402
import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXT = "When I'm played and when I conquer, draw 1."


def fields_of(text: str, grammar: dict) -> tuple[str | None, dict]:
    got = CG.compile_clause(text, grammar)
    return got.get("production_id"), (got.get("passive") or {}).get("object_fields") or {}


def played(descriptors: dict | None) -> list[dict]:
    """Play c1 as a Unit to p1's Base and resolve it; the chain items scheduled."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update(kind="unit", base_might=2)
    for field, entries in (descriptors or {}).items():
        state["objects"]["c1"][field] = [dict(e, source_object="c1") for e in entries]
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    play = play_card(fixture(), state, decl)
    if not play.get("committed"):
        raise AssertionError(f"the play did not commit: {play.get('reason_code')} {play.get('reason')}")
    timing = fixture(priority="p2", items=[item("unit-1", "p1", "unit", "default", "finalized")], passes=["p1", "p2"])
    done = resolve_with_program(timing, "unit-1", play["next_effect_state"], None)
    if not done.get("committed"):
        raise AssertionError(f"the entry did not resolve: {done.get('reason_code')} {done.get('reason')}")
    return done["next_timing_state"]["chain"]["items"]


def scored(descriptors: dict | None, *, where: str, how: str = "conquer") -> list[dict]:
    """The Scoring Step's trigger pass for p1 over bf1, with u1 at bf1 or in its Base."""
    state = base_state()
    for field, entries in (descriptors or {}).items():
        state["objects"]["u1"][field] = [dict(e, source_object="u1") for e in entries]
    if where == "bf1":
        state["players"]["p1"]["zones"]["base"].remove("u1")
        state["battlefields"]["bf1"]["objects"].append("u1")
    state["battlefields"]["bf1"]["controller"] = "p1"
    settle_contested(state)
    problems = validate_state(state)
    if problems:
        raise AssertionError(f"the fixture is not a valid state: {problems[:2]}")
    return BC._score_triggers(state, "p1", "bf1", how, "turn-1")


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    pid, fields = fields_of(TEXT, grammar)
    if pid != "when_im_played_and_when_i_conquer" or set(fields) != {"play_triggers", "conquer_triggers"}:
        errors.append(f"lowering: expected play_triggers and conquer_triggers, got {pid} {sorted(fields)}")
    elif fields["play_triggers"] != fields["conquer_triggers"] or len(fields["play_triggers"]) != 1:
        errors.append("lowering: the two fields do not carry one identical descriptor")
    for text, only in (("When you play me, draw 1.", {"play_triggers"}), ("When I conquer, draw 1.", {"conquer_triggers"})):
        if set(fields_of(text, grammar)[1]) != only:
            errors.append(f"lowering: {text!r} no longer lowers to {sorted(only)} alone")
    if fields_of("When I'm played, draw 1.", grammar)[0] == "when_im_played_and_when_i_conquer":
        errors.append("lowering: 'When I'm played' alone was read as the two-condition ability")

    descriptor = {**fields.get("play_triggers", [{}])[0], "controller": "p1", "effect_program_id": "c1-pc"}
    both = {"play_triggers": [copy.deepcopy(descriptor)], "conquer_triggers": [copy.deepcopy(descriptor)]}
    try:
        items = played(both)
        mine = [i for i in items if i.get("id") == descriptor["trigger_id"]]
        if len(items) != 1 or len(mine) != 1 or mine[0].get("status") != "pending" \
                or mine[0].get("trigger_kind") != "triggered" or mine[0].get("batch_id") != "play:unit-1":
            errors.append(f"played: expected exactly one pending triggered item in the play batch, got "
                          f"{[(i.get('id'), i.get('status'), i.get('batch_id')) for i in items]}")
        if played(None):
            errors.append("neither: a Unit without the ability scheduled something on play")
    except AssertionError as why:
        errors.append(f"played: {why}")

    try:
        found = scored(both, where="bf1")
        if len(found) != 1 or found[0].get("trigger_id") != descriptor["trigger_id"] or found[0].get("how") != "conquer":
            errors.append(f"conquer: expected exactly one descriptor for the Unit at the Battlefield, got {found}")
        if scored(both, where="base"):
            errors.append("conquer: the Unit in its Base triggered on a Conquer of bf1")
        if scored(both, where="bf1", how="hold"):
            errors.append("conquer: a Hold of the Battlefield triggered the ability")
        if scored(None, where="bf1"):
            errors.append("neither: a Unit without the ability triggered on conquer")
    except AssertionError as why:
        errors.append(f"conquer: {why}")

    if errors:
        print("FAILED: when I'm played and when I conquer")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("when I'm played and when I conquer: one descriptor in both fields; exactly one item on play, exactly one "
          "descriptor on a Conquer where the Unit stands, none from its Base, a Hold, or a Unit without the ability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
