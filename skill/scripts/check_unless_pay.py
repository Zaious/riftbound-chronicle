#!/usr/bin/env python3
"""Regression gate: "Counter a spell unless its controller pays [2]." (set 2 package A2: Hard Bargain).

A Counter whose target's controller may, as it resolves, pay Energy instead (unless {decision_ref, instead: [pay_energy
{amount}]}): the choice is the TARGET's controller's (Core 355.10.e), as Shakedown's is. Chosen "instead", that player's
Energy pool drops by the amount and nothing is countered; let happen, the spell is countered (Core 426.1). A player whose
pool holds less than the amount cannot choose to pay. GPT A2 ruling 8 (Core 445.2.c): told to pay, the payer may first
activate [Add] abilities with the Reaction keyword - a payment window the payer closes (payment_window:<ref>) before the
pool is read; game_loop runs the [Add]s while it is open (setting payment_adds), each finalized and resolved at once.

  P1 asked          the resolution stops for p1 (the countered spell's controller): option_selection_required
  P2 instruction    p1 lets it happen: c1 countered, p1's Energy unchanged
  P3 instead        p1 pays, the window closed: p1's Energy 3 -> 1, c1 still on the Chain (outcome chose_instead); the
                    payment event names the Energy paid and the window
  P4 cannot pay     p1 holds 1 Energy, answers instead and closes the window: refused (unless_cannot_pay), nothing changed
  W1 window         p1 answers instead without closing the window: the resolution stops for p1 (payment_window_required,
                    the Energy due); closed by p2: still asked
  W2 Add then pay   p1 holds 1 Energy and a ready Rune: game_loop.payment_adds runs its [E]: Add [1] (the Rune exhausted,
                    p1 at 2) and the same resolution then pays - p1 at 0, c1 still on the Chain
  W3 still short    p1 holds 0 Energy and one Rune: after its Add, 1 Energy - the window closed, still unless_cannot_pay
  W4 not an Add     a payment_adds entry that is not an [Add] Reaction is refused (not_an_add_reaction)
  W5 answers        decision_space answers the window: closed with no Add, and after every state the payer's two Runes'
                    [Add]s reach (each Rune's Energy and Power Adds, any number of them - GPT's A2 review, blocker 3;
                    check_payment_window_adds.py holds the set whole): twenty answers, both Energy Adds among them
  P5 wrong chooser  p2 (the counter's controller) answers: refused
  V  shapes         pay_energy with no amount, amount 0, or a player beside it does not validate; a draw instead still does
  G  grammar        the card's line lowers to exactly this instruction; its near misses do not

    python skill/scripts/check_unless_pay.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_counter_target import TARGET, board  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402

COUNTER = {"op": "counter", "effect_id": "ctr", "target": dict(TARGET),
           "unless": {"decision_ref": "un", "instead": [{"op": "pay_energy", "effect_id": "pay", "amount": 2}]}}
errors: list[str] = []


def program(effect):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "hb", "controller": "p2", "effects": [copy.deepcopy(effect)]}


def run(state, answer=None, by="p1", window="p1"):
    decisions = [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p2",
                  "value": ["c1"], "selection_identities": {"c1": object_identity(state, "c1") or "c1@0"}}]
    if answer is not None:
        decisions.append({"decision_id": "un", "stage": "resolution", "kind": "option_selection", "controller": by,
                          "value": answer})
    if answer == "instead" and window:
        decisions.append({"decision_id": "payment_window:un", "stage": "resolution", "kind": "optional_choice",
                          "controller": window, "value": True})
    return apply_program(state, program(COUNTER), decisions={"schema_version": "engine-decisions.v1",
                                                              "input_hash": hash_value(state), "decisions": decisions})


def scene(energy):
    s = board()
    s["players"]["p1"]["resources"] = {"energy": energy, "power": {}}
    return s


def with_runes(energy, runes):
    """scene(energy) with p1's ready Fury Runes from check_game_loop's catalogue in p1's Base; (state, catalogue)."""
    import check_game_loop as CGL
    cat = CGL.catalogue()
    placed = CGL.environment(cat, [(r, "Fury Rune", "p1", "base") for r in runes])
    s = scene(energy)
    for r in runes:
        s["objects"][r] = placed["objects"][r]
        s["players"]["p1"]["zones"]["base"].append(r)
    return s, cat


def window_cases() -> None:
    import decision_space as DS
    import game_loop as GL
    import play_space as PS
    from check_rules_core import fixture, item
    timing = fixture(priority=None, items=[item("spell-1", "p1", "spell", "default"), item("hb", "p2", "spell", "default")])
    asked = run(scene(3), "instead", window=None)
    if asked.get("committed") or asked.get("reason_code") != "payment_window_required" \
            or asked.get("decision_controller") != "p1" or asked.get("decision_ids") != ["payment_window:un"] \
            or asked.get("payment_due") != {"player": "p1", "energy": 2}:
        errors.append(f"W1 window: {asked.get('reason_code')} {asked.get('decision_controller')} {asked.get('payment_due')}")
    if run(scene(3), "instead", window="p2").get("reason_code") != "payment_window_required":
        errors.append("W1 window: closed by p2 (not the payer) was accepted")
    s, cat = with_runes(1, ["fr1"])
    adds = [d for d, _p in PS.ability_skeletons(s, cat, "p1") if d["activation"]["ability_id"].endswith(":exhaust")]
    added = GL.payment_adds(timing, s, cat, adds)
    after = added.get("next_effect_state") or {}
    if not added.get("committed") or after["players"]["p1"]["resources"]["energy"] != 2 or not after["objects"]["fr1"]["exhausted"]:
        errors.append(f"W2 Add then pay: the Add {added.get('reason_code')} {added.get('reason')}")
    else:
        paid = run(after, "instead")
        end = paid.get("next_state") or {}
        if not paid.get("committed") or end["players"]["p1"]["resources"]["energy"] != 0 \
                or "spell-1" not in (end.get("chain_items") or {}):
            errors.append(f"W2 Add then pay: {paid.get('reason_code')} {paid.get('reason')}")
    s, cat = with_runes(0, ["fr1"])
    adds = [d for d, _p in PS.ability_skeletons(s, cat, "p1") if d["activation"]["ability_id"].endswith(":exhaust")]
    added = GL.payment_adds(timing, s, cat, adds)
    short = run(added.get("next_effect_state") or s, "instead")
    if not added.get("committed") or short.get("committed") or short.get("reason_code") != "unless_cannot_pay":
        errors.append(f"W3 still short: {added.get('reason_code')} {short.get('committed')} {short.get('reason_code')}")
    s, cat = with_runes(1, ["fr1"])
    bogus = GL.payment_adds(timing, s, cat, [{"actor": "p1", "chain_item": {"id": "x", "object_kind": "spell",
                                                                            "timing": "default"}}])
    if bogus.get("committed") or bogus.get("reason_code") != "not_an_add_reaction":
        errors.append(f"W4 not an Add: {bogus.get('reason_code')}")
    s, cat = with_runes(1, ["fr1", "fr2"])
    request = {"code": "payment_window_required", "decision_ids": ["payment_window:un"], "controller": "p1",
               "payload": run(s, "instead", window=None)}
    kind, decider, out = DS.answers(request, timing, s, cat, "resolve:spell")
    sources = [tuple((d["activation"]["source_object"], d["activation"]["ability_id"].rsplit(":", 1)[-1])
                     for d in (a.get("settings") or {}).get("payment_adds") or []) for a in out]
    if kind != "payment_window" or decider != "p1" or len(sources) != 20 or sources[0] != () \
            or (("fr1", "exhaust"), ("fr2", "exhaust")) not in sources \
            or any(a["decisions"][0]["decision_id"] != "payment_window:un" or a["decisions"][0]["value"] is not True
                   for a in out):
        errors.append(f"W5 answers: {kind} {decider} {sources}")


def main() -> int:
    if validate_program(program(COUNTER)):
        errors.append(f"V: the program does not validate: {validate_program(program(COUNTER))[:2]}")
    asked = run(scene(3))
    if asked.get("committed") or asked.get("reason_code") != "option_selection_required" or asked.get("decision_controller") != "p1":
        errors.append(f"P1 asked: {asked.get('committed')} {asked.get('reason_code')} {asked.get('decision_controller')}")
    let = run(scene(3), "instruction")
    after = let.get("next_state") or {}
    if not let.get("committed") or "spell-1" in (after.get("chain_items") or {}) \
            or "c1" not in after["players"]["p1"]["zones"]["trash"] or after["players"]["p1"]["resources"]["energy"] != 3:
        errors.append(f"P2 instruction: {let.get('reason_code')} {let.get('errors') or let.get('reason')}")
    paid = run(scene(3), "instead")
    after = paid.get("next_state") or {}
    event = next(iter(paid.get("trace") or []), {})
    if not paid.get("committed") or "spell-1" not in (after.get("chain_items") or {}) \
            or after["players"]["p1"]["resources"]["energy"] != 1 \
            or [t.get("outcome") for t in paid.get("trace") or []] != ["chose_instead"] \
            or event.get("paid") != {"player": "p1", "energy": 2} or event.get("payment_window") != "payment_window:un":
        errors.append(f"P3 instead: {paid.get('reason_code')} {paid.get('errors') or paid.get('reason')} "
                      f"{[t.get('outcome') for t in paid.get('trace') or []]}")
    short = run(scene(1), "instead")
    if short.get("committed") or short.get("reason_code") != "unless_cannot_pay":
        errors.append(f"P4 cannot pay: {short.get('committed')} {short.get('reason_code')}")
    wrong = run(scene(3), "instead", by="p2")
    if wrong.get("committed") or wrong.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"P5 wrong chooser: {wrong.get('committed')} {wrong.get('reason_code')}")
    for label, instead in (("no amount", {"op": "pay_energy", "effect_id": "pay"}),
                           ("amount 0", {"op": "pay_energy", "effect_id": "pay", "amount": 0}),
                           ("a player", {"op": "pay_energy", "effect_id": "pay", "amount": 2, "player": "$controller"})):
        bad = {**COUNTER, "unless": {"decision_ref": "un", "instead": [instead]}}
        if not validate_program(program(bad)):
            errors.append(f"V: pay_energy with {label} validated")
    window_cases()
    grammar = CG.load_grammar()
    body = CG.compile_clause("Counter a spell unless its controller pays :rb_energy_2:.", grammar)
    if body.get("unsupported") or body.get("program_effects") != [COUNTER]:
        errors.append(f"G grammar: {body.get('production_id')} {body.get('program_effects')}")
    for near in ("Counter a spell unless you pay :rb_energy_2:.", "Counter a unit unless its controller pays :rb_energy_2:.",
                 "Counter a spell unless its controller has you draw 2."):
        if CG.compile_clause(near, grammar).get("production_id") == body.get("production_id"):
            errors.append(f"G grammar: the near miss {near!r} lowered to the row")
    if errors:
        print("unless-pay checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("unless-pay checks passed: the countered spell's controller lets it happen or pays the Energy instead, after a "
          "payment window it closes (Core 445.2.c) in which game_loop runs its [Add] Reactions; a pool short after the "
          "window cannot pay, the counter's controller cannot answer, decision_space answers the window, and the line lowers "
          "to exactly this")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
