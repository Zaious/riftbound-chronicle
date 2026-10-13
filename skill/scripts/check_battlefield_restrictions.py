#!/usr/bin/env python3
"""Restrictions a permanent imposes while it is at a Battlefield (package 11, Mageseeker Warden: "While I'm at a
battlefield, opponents can only play units to their base. While I'm at a battlefield, spells and abilities can't ready
enemy units and gear.").

GPT 2026-10-12 (PACKAGE11 ruling 17), two paths. A Unit played directly: the restriction narrows its valid locations as it
is played (Core 355.2) - a Battlefield is not offered and a play declared there is refused, never played and skipped
later. An effect that instructs an action the restriction forbids (Core 358.3.a, whose own example is this card): the
effect is still played and finalized, and as it resolves that action is skipped - a unit it would play to a Battlefield is
not played; a "ready" on an enemy Unit or Gear does nothing. Once the card has left the Battlefield, neither binds.

  W1 direct play    p2 (the card's opponent) plays a Unit to bf2, which p2 controls: refused
                    (entry_location_units_to_base_only); to p2's Base: played. bf2 is not among the locations offered
  W2 own side       p1, the card's controller, plays a Unit to bf2 it controls: played
  W3 effect play    p2's effect plays a Unit of p2's 'here' (a Battlefield): the effect resolves, the unit is not played
                    (limited_play_units_to_base_only), it stays in p2's hand
  W4 ready          p2's spell readies p2's exhausted unit and gear: neither readied (ready_prevented); p1's spell readies
                    p1's own exhausted unit: readied
  W5 Awaken         p2's Awaken Step readies p2's exhausted unit (not a spell or ability)
  W6 left           the card in p1's Base: p2's play to bf2 and p2's ready both go through
  V  shape/grammar  a restriction flag that is not true does not validate; both sentences lower to their flags
                    and a near miss does not

    python skill/scripts/check_battlefield_restrictions.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, battlefield_restriction, hash_value, object_identity, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402
from turn_cycle import run_awaken_step  # noqa: E402

errors: list[str] = []
RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
FLAGS = {"restricts_opponent_units_to_base": True, "prevents_ready_enemy_units_gear": True}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(where="bf1"):
    """p1's ward (the card) at bf1 - or in p1's Base; bf2 controlled by p2 (p2's x2 there), bf3 by p1 (p1's x1 there).
    p2's exhausted e1 at bf2 and exhausted gear g2 in p2's Base; p1's exhausted f1 in p1's Base. In hand: p2's h2 and
    p1's h1, Units costing 1."""
    state = base_state()
    state["objects"]["ward"] = unit("p1", **FLAGS)
    state["objects"].update({"x2": unit("p2"), "x1": unit("p1"), "e1": unit("p2", exhausted=True),
                             "f1": unit("p1", exhausted=True),
                             "g2": {**unit("p2", exhausted=True), "kind": "gear", "base_might": 0},
                             "h2": {**unit("p2"), "printed_cost": {"energy": 1, "power": {}}},
                             "h1": {**unit("p1"), "printed_cost": {"energy": 1, "power": {}}}})
    if where == "bf1":
        state["battlefields"]["bf1"]["objects"].append("ward")
    else:
        state["players"]["p1"]["zones"]["base"].append("ward")
    state["battlefields"]["bf2"] = {"controller": "p2", "objects": ["x2", "e1"]}
    state["battlefields"]["bf3"] = {"controller": "p1", "objects": ["x1"]}
    state["players"]["p2"]["zones"]["base"].append("g2")
    state["players"]["p1"]["zones"]["base"].append("f1")
    state["players"]["p2"]["zones"]["hand"].append("h2")
    state["players"]["p1"]["zones"]["hand"].append("h1")
    for p in ("p1", "p2"):
        state["players"][p]["resources"] = {"energy": 1, "power": {}}
    return settle_contested(state)


def play(state, actor, card, location):
    timing = fixture(priority=actor)
    timing["turn_player"] = actor
    declared = {"schema_version": PT.DECLARATION_VERSION, "ruleset": RULESET, "play_id": f"play-{card}", "actor": actor,
                "card": card, "chain_item": {"id": f"unit-{card}", "object_kind": "unit", "timing": "default"},
                "cost": {"base": {"energy": 1, "power": {}}}, "entry_location": location,
                "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    got = PT.play_card(timing, state, declared)
    return "played" if got.get("committed") else got.get("reason_code")


def program(controller, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": f"{controller}-fx", "controller": controller,
            "effects": effects, **extra}


def ready(state, controller, *objects):
    got = apply_program(state, program(controller, [{"op": "ready", "effect_id": f"r{i}", "object_id": o}
                                                    for i, o in enumerate(objects)]))
    if not got.get("committed"):
        return {"refused": got.get("reason") or got.get("errors")}
    return {o: got["next_state"]["objects"][o]["exhausted"] for o in objects} | {
        "reasons": sorted({e.get("reason") for e in got.get("trace") or [] if e.get("reason")})}


def main() -> int:
    s = board()
    if validate_state(s):
        fail("board", validate_state(s)[:2])
        return report()
    # W1
    if play(s, "p2", "h2", {"kind": "battlefield", "battlefield": "bf2"}) != "entry_location_units_to_base_only":
        fail("W1 direct play", f"p2's Unit to bf2: {play(s, 'p2', 'h2', {'kind': 'battlefield', 'battlefield': 'bf2'})}")
    if play(s, "p2", "h2", {"kind": "base"}) != "played":
        fail("W1 direct play", f"p2's Unit to its Base: {play(s, 'p2', 'h2', {'kind': 'base'})}")
    if any(PT.battlefield_entry_paths(s, "h2", "p2", "bf2").values()):
        fail("W1 offered", "bf2 is still a way in for p2's Unit")
    # W2
    if play(s, "p1", "h1", {"kind": "battlefield", "battlefield": "bf3"}) != "played":
        fail("W2 own side", f"p1's Unit to bf3: {play(s, 'p1', 'h1', {'kind': 'battlefield', 'battlefield': 'bf3'})}")
    # W3: p2's effect plays h2 'here' - its source x2 is at bf2
    # (the shape of Ava Achiever's play from the hand, engine check_limited_play.py H)
    effect = program("p2", [{"op": "limited_play", "effect_id": "lp", "decision_ref": "c",
                             "choice": {"from": "hand", "selection_kind": "unordered_set", "count": {"up_to": 1},
                                        "by": "controller", "visibility": "private_to_chooser"},
                             "entry": {"kind": "unit_at_source_battlefield"}, "cost_basis": {"kind": "ignore_all"}}],
                     source_object="x2", source_identity="x2@0")
    pick = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": "c", "stage": "resolution", "kind": "card_selection", "controller": "p2", "value": ["h2"],
         "selection_identities": {"h2": object_identity(s, "h2")}}]}
    got = apply_program(s, effect, decisions=pick)
    step = next((e for e in got.get("trace") or [] if e.get("effect_id") == "lp"), {})
    if not got.get("committed") or step.get("reason") != "limited_play_units_to_base_only" \
            or "h2" not in got["next_state"]["players"]["p2"]["zones"]["hand"]:
        fail("W3 effect play", f"{got.get('reason') or got.get('errors')} {step.get('outcome')} {step.get('reason')}")
    # W4
    theirs = ready(s, "p2", "e1", "g2")
    if theirs != {"e1": True, "g2": True, "reasons": ["ready_prevented"]}:
        fail("W4 ready", f"p2's spell on p2's unit and gear: {theirs}")
    mine = ready(s, "p1", "f1")
    if mine != {"f1": False, "reasons": []}:
        fail("W4 ready", f"p1's spell on p1's unit: {mine}")
    # W5: p2's Awaken Step
    t = fixture(priority=None)
    t.update({"turn_player": "p2", "phase": "awaken", "turns_taken": {"p1": 2, "p2": 2}, "outstanding_tasks": [],
              "turn_progress": {"turn_id": "turn-0", "first_turn": {"extra_channel": False, "skip_draw": False,
                                                                     "source": "not_first_turn"}}})
    woke = run_awaken_step(t, s)
    if not woke.get("committed") or woke["next_effect_state"]["objects"]["e1"]["exhausted"] is not False:
        fail("W5 Awaken", f"{woke.get('reason_code')} {woke.get('reason') or woke.get('errors')}")
    # W6
    away = board("base")
    if play(away, "p2", "h2", {"kind": "battlefield", "battlefield": "bf2"}) != "played" \
            or ready(away, "p2", "e1") != {"e1": False, "reasons": []} \
            or battlefield_restriction(away, "opponent_units_to_base_only", "p2") is not None:
        fail("W6 left", f"{play(away, 'p2', 'h2', {'kind': 'battlefield', 'battlefield': 'bf2'})} {ready(away, 'p2', 'e1')}")
    # V
    bad = copy.deepcopy(s)
    bad["objects"]["ward"]["prevents_ready_enemy_units_gear"] = "yes"
    if not validate_state(bad):
        fail("V shape", "a restriction flag that is not true validated")
    grammar = cg.load_grammar()
    for text, flag in (("While I'm at a battlefield, opponents can only play units to their base.", "restricts_opponent_units_to_base"),
                       ("While I'm at a battlefield, spells and abilities can't ready enemy units and gear.",
                        "prevents_ready_enemy_units_gear")):
        got = cg.compile_clause(text, grammar)
        if ((got.get("passive") or {}).get("object_fields") or {}) != {flag: True}:
            fail("V grammar", f"{text!r} lowered to {got.get('production_id')} {got.get('passive')}")
    near = cg.compile_clause("Opponents can only play units to their base.", grammar)
    if (near.get("passive") or {}).get("object_fields"):
        fail("V grammar", "a near miss lowered")
    return report()


def report() -> int:
    if errors:
        print("FAILED: restrictions while a permanent is at a Battlefield")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: while the card is at a Battlefield an opponent's Unit has only its Base as a location when played, an "
          "effect's play of one to a Battlefield is skipped as it resolves, and a spell's or ability's ready on an enemy "
          "Unit or Gear does nothing - the Awaken Step still readies; with the card gone, neither binds (W1-W6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
