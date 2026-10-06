#!/usr/bin/env python3
"""A spell played from the trash and recycled as it leaves the Chain (package 9, Kai'Sa - Evolutionary).

"When I conquer, you may play a spell from your trash with Energy cost less than your points without paying its Energy
cost. Then recycle it. (You must still pay its Power cost.)" GPT 2026-10-04 (PACKAGE8_INVENTORY section 6, ruling 2):
"Then recycle it" is, by Core 390.3.a, a delayed replacement bound to that spell - once it is a Finalized Chain item,
if it would leave the Chain and that leaving is not instructed by its own execution, it is recycled instead; not a
recycle of the Pending spell while the ability resolves, not an unconditional recycle after it resolves normally; the
countered path is witnessed too.

The engine's shape: selector field energy_cost_below_points; op recycle_when_leaving_chain {linked: {effect_id}} binding
chain_items[item].leave_replacement {kind recycle}; the resolution bridge (its resolution done) and counter recycle it.

  K1 resolved      the spell (printed [3][Fury], p1 at 4 points) played from the trash paying [Fury] only, then
                   resolved: its instruction done, it goes to the BOTTOM of p1's Main Deck, not the trash; a new object
  K2 countered     the same spell countered while it is on the Chain: recycled, not trashed
  K3 unbound       the same play without "Then recycle it": the resolved spell goes to the trash as before
  K4 nothing      the chosen spell left the trash before the ability resolved: nothing played, nothing bound
  K5 below points  printed [3] with 3 points is not a legal target; [3] with 4 points is; a card with no printed cost
                   is refused by name
  K6 cancelled     the Power unpayable: the play cancelled before it was Finalized (358.5) - the card back in the
                   trash where it was, not recycled
  S  shapes        linked to a non-play, an extra field, energy_cost_below_points false - each refused

    python skill/scripts/check_chain_leave_recycle.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, evaluate_target, hash_value,  # noqa: E402
                       object_identity, validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import complete_limited_play, resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def program(program_id: str, source: str, effects: list[dict], controller: str = "p1") -> dict:
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": program_id, "controller": controller,
            "source_object": source, "effects": effects}


TARGET = {"decision_ref": "t", "kind": "spell", "location": "trash", "zone_owner_relation": "own",
          "chosen_zone_class": "non_board", "energy_cost_below_points": True}
PLAY = {"op": "limited_play", "effect_id": "lp", "target": dict(TARGET), "cost_basis": {"kind": "ignore_energy"}}
RECYCLE = {"op": "recycle_when_leaving_chain", "effect_id": "rc", "linked": {"effect_id": "lp"}}
KAISA = program("kaisa-effects", "kaisa", [PLAY, RECYCLE])
UNBOUND = program("kaisa-effects", "kaisa", [PLAY])
# the spell played from the trash: it draws 1 as it resolves
ZAP = program("zap-effects", "zap", [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])


def board(*, points: int = 4, fury: int = 1) -> dict:
    state = base_state()
    state["objects"]["kaisa"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False, "printed_cost": {"energy": 1, "power": {}}}
    state["objects"]["zap"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                               "damage": 0, "exhausted": False, "printed_cost": {"energy": 3, "power": {"fury": 1}}}
    state["players"]["p1"]["zones"].setdefault("hand", []).append("kaisa")
    state["players"]["p1"]["zones"]["trash"].append("zap")
    state["players"]["p1"]["points"] = points
    state["players"]["p1"]["resources"] = {"energy": 1, "power": {"fury": fury} if fury else {}}
    assert not validate_state(state), validate_state(state)
    return state


def resolve_kaisa(state: dict, prog: dict, target: str | None = "zap") -> dict:
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": [target] if target else [], "selection_identities": {target: object_identity(state, target)} if target else {}}]}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-kaisa", "actor": "p1", "card": "kaisa",
            "effect_program_id": prog["program_id"], "chain_item": {"id": "spell-k", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "payment_context": CLOSED}
    played = play_card(fixture(), state, decl, engine_decisions=decisions, effect_program=prog)
    if not played.get("committed"):
        return {"refused": played.get("reason_code") or played.get("reason")}
    timing = played["next_timing_state"]
    if next_procedure(timing).get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, "spell-k", played["next_effect_state"], prog)


def resolve_kaisa_with_target_moved(state: dict) -> dict:
    """Kai'Sa's ability played choosing zap in the trash on `state`; zap then put in p1's hand before it resolves."""
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": ["zap"], "selection_identities": {"zap": object_identity(state, "zap")}}]}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-kaisa", "actor": "p1", "card": "kaisa",
            "effect_program_id": KAISA["program_id"], "chain_item": {"id": "spell-k", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 1, "power": {}}}, "payment_context": CLOSED}
    played = play_card(fixture(), state, decl, engine_decisions=decisions, effect_program=KAISA)
    if not played.get("committed"):
        return {"refused": played.get("reason_code") or played.get("reason")}
    effect = copy.deepcopy(played["next_effect_state"])
    effect["players"]["p1"]["zones"]["trash"].remove("zap")
    effect["players"]["p1"]["zones"]["hand"].append("zap")
    effect["objects"]["zap"]["identity"] = "zap@9"
    timing = played["next_timing_state"]
    if next_procedure(timing).get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, "spell-k", effect, KAISA)


def zap_on_chain(state: dict, prog: dict = KAISA) -> tuple[dict | None, dict | None, str | None]:
    done = resolve_kaisa(state, prog)
    if not done.get("committed"):
        return None, None, f"Kai'Sa's ability did not resolve: {done.get('refused') or done.get('reason')}"
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
    if not completed.get("committed"):
        return None, None, f"the play did not complete: {completed.get('reason')} {completed.get('message')}"
    return completed["next_timing_state"], completed["next_effect_state"], None


def resolve_zap(timing: dict, effect: dict) -> dict:
    item = next(i for i in timing["chain"]["items"] if i.get("limited_play"))
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, item["id"], effect, ZAP)


def where(state: dict, card: str) -> str | None:
    for player, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if card in ids:
                return f"{player}:{zone}"
    return None


def main() -> int:
    # K1
    s = board()
    before = object_identity(s, "zap")
    t, e, why = zap_on_chain(s)
    if why:
        fail("K1 resolved", why)
    else:
        if e["players"]["p1"]["resources"] != {"energy": 0, "power": {"fury": 0}}:
            fail("K1 Power paid", f"its Energy ignored and its [Fury] paid: {e['players']['p1']['resources']}")
        entry = next((v for v in (e.get("chain_items") or {}).values() if v.get("card") == "zap"), {})
        if (entry.get("leave_replacement") or {}).get("kind") != "recycle":
            fail("K1 bound", f"the play's chain item carries no leave replacement: {entry}")
        hand = len(e["players"]["p1"]["zones"]["hand"])
        done = resolve_zap(t, e)
        after = done.get("next_effect_state")
        if after is None:
            fail("K1 resolved", f"the spell did not resolve: {done.get('reason')}")
        else:
            if after["players"]["p1"]["zones"]["main_deck"][-1:] != ["zap"] or "zap" in after["players"]["p1"]["zones"]["trash"]:
                fail("K1 recycled", f"the spell is at {where(after, 'zap')}, not the bottom of p1's Main Deck")
            if len(after["players"]["p1"]["zones"]["hand"]) != hand + 1:
                fail("K1 its instruction", "the spell's own draw did not happen first")
            if object_identity(after, "zap") == before:
                fail("K1 new object", "the recycled card is the same object (Core 124)")
        # K2: countered while on the Chain
        item = next(k for k, v in e["chain_items"].items() if v.get("card") == "zap")
        countered = apply_program(e, program("counter", "o-spell", [{"op": "counter", "effect_id": "c", "chain_item_id": item}], "p2"))
        if not countered.get("committed") or where(countered["next_state"], "zap") != "p1:main_deck" \
                or countered["next_state"]["players"]["p1"]["zones"]["main_deck"][-1] != "zap":
            fail("K2 countered", f"{countered.get('reason') or countered.get('errors')} {where(countered.get('next_state') or s, 'zap')}")
    # K3: unbound
    t, e, why = zap_on_chain(board(), UNBOUND)
    if why:
        fail("K3 unbound", why)
    else:
        after = resolve_zap(t, e).get("next_effect_state") or {}
        if where(after, "zap") != "p1:trash":
            fail("K3 unbound", f"without the instruction the spell went to {where(after, 'zap')}, not the trash")
    # K4: nothing played - the chosen spell left the trash before the ability resolved (359.3.e.2), so the play is
    # ignored and nothing is bound ("you may" itself is the trigger's optionality at finalization, Core 383.3)
    done = resolve_kaisa_with_target_moved(board())
    steps = [(x.get("op"), x.get("outcome")) for x in ((done.get("trace") or {}).get("effect") or [])]
    if not done.get("committed") or ("recycle_when_leaving_chain", "no_op") not in steps:
        fail("K4 nothing played", f"{done.get('reason') or done.get('refused')} {steps}")
    # K5: below points
    for points, ok in ((3, False), (4, True)):
        st = board(points=points)
        legal, reason = evaluate_target(st, {**TARGET, "object_id": "zap"}, "p1")
        if legal is not ok:
            fail("K5 below points", f"printed [3] with {points} points: legal={legal} ({reason})")
    blind = board()
    del blind["objects"]["zap"]["printed_cost"]
    legal, reason = evaluate_target(blind, {**TARGET, "object_id": "zap"}, "p1")
    if legal or not str(reason).startswith("target_cost_not_observed"):
        fail("K5 no printed cost", f"{legal} {reason}")
    # K6: cancelled before Finalized
    s = board(fury=0)
    done = resolve_kaisa(s, KAISA)
    if done.get("committed"):
        cancelled = complete_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
        e2 = cancelled.get("next_effect_state") or {}
        if not cancelled.get("committed") or where(e2, "zap") != "p1:trash" \
                or e2["players"]["p1"]["zones"]["trash"].index("zap") != s["players"]["p1"]["zones"]["trash"].index("zap"):
            fail("K6 cancelled", f"{cancelled.get('reason')} {where(e2, 'zap') if e2 else None}")
    else:
        fail("K6 cancelled", f"Kai'Sa's ability did not resolve: {done.get('reason') or done.get('refused')}")
    # S
    if validate_program(KAISA):
        fail("S shapes", f"the Kai'Sa shape is refused: {validate_program(KAISA)}")
    for label, bad in (("linked to a draw", [{"op": "draw", "effect_id": "lp", "player": "p1", "count": 1}, RECYCLE]),
                       ("an extra field", [PLAY, {**RECYCLE, "to": "hand"}]),
                       ("below points false", [{**PLAY, "target": {**TARGET, "energy_cost_below_points": False}}, RECYCLE])):
        if not validate_program({**KAISA, "effects": copy.deepcopy(bad)}):
            fail("S shapes", f"{label} was accepted")
    if errors:
        print("FAILED: chain leave recycle checks")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("OK: a spell played from the trash is recycled as it leaves the Chain once Finalized - resolved or "
          "countered - and not when its play is cancelled (K1-K6, S)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
