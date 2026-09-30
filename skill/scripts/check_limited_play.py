#!/usr/bin/env python3
"""An effect-driven play goes through the normal play transaction, from the Chain it was put on.

Core 419.3 / 419.3.a / 419.3.b: an effect may have a card played as it resolves - a Limited Action
whose steps are the normal ones except as the effect notes. GPT 2026-09-25 (The Harrowing,
Soulgorger): the play goes through the normal play transaction and the Chain, never straight onto the
board; the trash is a public zone, so the card is a target bound when the effect is played or
finalized; a choice already certain to lead to an illegal action later may not be made (355.16); a
Power cost that cannot be paid when the play is carried out means that play cannot complete, and the
effect's earlier instructions stand; Soulgorger's "you may" is decided at finalization and, declined,
asks for no target.

The engine's shape: the `limited_play` instruction takes the play's step 1 - the card leaves its zone
for the Chain as a Pending item, a new object (Core 354, 124) - and the rest waits until the effect has
finished resolving (354.3): the resolution bridge puts the item on the timing Chain ahead of anything
the resolution triggered, and resolution_bridge.finalize_limited_play takes steps 2 to 5 through
play_card with the effect's permission and cost change (356.1.b), no timing permission asked (419.3.a).
A Unit resolves as soon as it is Finalized (337.2): complete_limited_play.

Held here:

  W1 a real Chain     a spell "Play a unit from your trash, ignoring its Energy cost." played from the
                      hand, its target a unit in its controller's trash bound at play; resolved, the
                      unit is on the Chain, Pending, and NOT on the board; completed, the unit is in
                      its Base exhausted (359.2.c), a new object, its Power cost paid and no Energy,
                      and its own "When you play me" is on the Chain (419.4.a)
  W2 a trigger        "When you play me, you may play a unit from your trash, ignoring its Energy
                      cost." declined at the "you may" (383.3.a.2): removed, no target asked, the
                      trash unchanged; performed: the target bound at finalization, resolved, completed
  W3 a Chain under it the play made in reaction, above an opponent's Finalized spell: completed, the
                      opponent's spell is still on the Chain and the newest item's controller has
                      Priority (340.4)
  W4 its own place    a program that kills a unit with a death trigger and then plays: the play's
                      item is Pending BEFORE the death trigger, and is the one finalized first (354)
  W5 ignoring its     "ignoring its cost" (356.1.b.1): nothing paid, no Add window asked
     cost
  C1 underpayment     Power short with the Add window closed: the play is cancelled (358.5) - the card
                      back in the trash at its place as the object it was, the item gone, never
                      finalized, not countered - and the instruction before it (a draw) stands;
                      the Add window not confirmed: a decision, nothing changed
  C2 target changed   the card left the trash and came back before the spell resolved (359.3.e.4):
                      the instruction is ignored, nothing is played, the card stays in the trash
  C3 355.16           a unit whose Power could never be paid (pool, Runes and the Add abilities the
                      actor's permanents record counted) may not be chosen; with a Rune of its Domain
                      on the board it may; with a ready unit that records an Add of that Domain it may,
                      exhausted it may not; with a unit whose Add abilities are not recorded it may (not
                      certain, GPT 2026-09-27: Add Reactions count, 357.1.a); with its cost ignored it may
  C4 forged           timing_source limited_play on a card in hand; a lower cost.base; another
                      cost_override; another permission; a limited play that is not the oldest
                      Pending item; an ability declared as a limited play - each refused
  C5 op alone         apply_program never puts the card on the board; _apply_one refuses the op
  C6 no target        nothing chosen -> a decision; a spell in the trash, an opponent's unit, a unit
                      in the hand -> refused at play; a unit with no printed cost -> unsupported
  C7 entry location   none given -> a decision naming the legal places (355.2.a); a Battlefield the
                      player neither controls nor may enter -> refused, nothing changed (not cancelled)
  C8 shapes           a hand target, no zone_owner_relation own, an unknown cost basis, an extra field,
                      a malformed record on the chain entry - each refused by validation
  C9 prohibited       "opponents can't play cards this turn" in force on its player: cancelled (054.1)
  H  a hand choice    "When I attack, you may pay [C] to play a card with [Hidden] from your hand, ignoring its
     and 'here'       cost. If it's a unit, play it here." (Ava Achiever's shape): the base cost [C] is one Power
                      of the card's own Domain (a card with two Domains, or none recorded, cannot pay it); the card
                      is chosen from the hand as the ability resolves - private, not a target (Core 355.10.a) - and
                      only a card with [Hidden]; choosing none is allowed (128.6), and with none in hand nothing is
                      asked (419.3.c); a unit enters the source's Battlefield though its player does not control it
                      (355.2.b), and no other location is taken; a gear enters its Base; the source gone from the
                      Battlefield names no location, which is then chosen (355.2.a); a cancelled play puts the card
                      back in the hand at its place

    python skill/scripts/check_limited_play.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, _apply_one, apply_program, hash_value,  # noqa: E402
                       object_identity, validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card, validate_declaration  # noqa: E402
from resolution_bridge import (complete_limited_play, dispatch_program, finalize_limited_play,  # noqa: E402
                               finalize_trigger, program_hash, resolve_with_program)
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
BASE = {"kind": "base"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def program(program_id: str, source: str, effects: list[dict], controller: str = "p1") -> dict:
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": program_id,
            "controller": controller, "source_object": source, "effects": effects}


def trash_target(ref: str = "t", **extra) -> dict:
    return {"decision_ref": ref, "kind": "unit", "location": "trash", "zone_owner_relation": "own",
            "chosen_zone_class": "non_board", **extra}


def play_it(basis: str = "ignore_energy", ref: str = "t", effect_id: str = "lp") -> dict:
    return {"op": "limited_play", "effect_id": effect_id, "target": trash_target(ref), "cost_basis": {"kind": basis}}


HARROWING = program("harrowing-effects", "harrowing", [play_it()])


def card(owner: str, kind: str, cost: dict | None, might: int = 0, **extra) -> dict:
    out = {"owner": owner, "controller": owner, "kind": kind, "base_might": might, "might_modifiers": [], "damage": 0,
           "exhausted": False, **extra}
    if cost is not None:
        out["printed_cost"] = cost
    return out


def board(*, power: int = 1, energy: int = 2, spell_timing: str | None = None) -> dict:
    """p1: The Harrowing in hand; in its trash a spell and the unit `tu` (Energy 4, Power 1 chaos) with
    its own play trigger; p2: a unit in its trash. p1 has the spell's Energy and `power` chaos."""
    state = base_state()
    state["objects"]["harrowing"] = card("p1", "spell", {"energy": 2, "power": {}},
                                         **({"play_timing": spell_timing} if spell_timing else {}))
    tu_trigger = program("tu-on-play-effects", "tu", [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])
    state["objects"]["tu"] = card("p1", "unit", {"energy": 4, "power": {"chaos": 1}}, might=3,
                                  play_triggers=[{"trigger_id": "tu-on-play", "controller": "p1", "source_object": "tu",
                                                  "controller_order": 0, "effect_program_id": tu_trigger["program_id"],
                                                  "optional_at_finalize": False,
                                                  "effect_program_hash": program_hash(tu_trigger)}])
    state["objects"]["ou"] = card("p2", "unit", {"energy": 1, "power": {}}, might=2)
    state["objects"]["cheap"] = card("p1", "unit", {"energy": 1, "power": {}}, might=1)
    state["players"]["p1"]["zones"]["hand"].append("harrowing")
    state["players"]["p1"]["zones"]["trash"].extend(["tu", "cheap"])
    state["players"]["p2"]["zones"]["trash"].append("ou")
    state["players"]["p1"]["resources"] = {"energy": energy, "power": {"chaos": power} if power else {}}
    problems = validate_state(state)
    assert not problems, problems
    return state


def target_decision(state: dict, ref: str, object_id: str, stage: str = "play_declaration", controller: str = "p1") -> dict:
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
            "decisions": [{"decision_id": ref, "stage": stage, "kind": "target_selection", "controller": controller,
                           "value": [object_id], "selection_identities": {object_id: object_identity(state, object_id)}}]}


def harrowing_decl(timing: str = "default", item_id: str = "spell-h") -> dict:
    return {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": f"play-{item_id}", "actor": "p1",
            "card": "harrowing", "effect_program_id": HARROWING["program_id"],
            "chain_item": {"id": item_id, "object_kind": "spell", "timing": timing},
            "cost": {"base": {"energy": 2, "power": {}}}, "payment_context": CLOSED}


def play_harrowing(state: dict, target: str = "tu", *, prog: dict = HARROWING, timing_state: dict | None = None,
                   timing: str = "default") -> dict:
    return play_card(timing_state or fixture(), state, {**harrowing_decl(timing), "effect_program_id": prog["program_id"]},
                     engine_decisions=target_decision(state, "t", target), effect_program=prog)


def to_resolution(timing: dict) -> dict:
    step = next_procedure(timing)
    if step.get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return timing


def resolved_harrowing(state: dict | None = None, prog: dict = HARROWING, target: str = "tu") -> dict:
    state = state if state is not None else board()
    played = play_harrowing(state, target, prog=prog)
    assert played.get("committed"), (played.get("reason_code"), played.get("reason"))
    timing = to_resolution(played["next_timing_state"])
    done = resolve_with_program(timing, "spell-h", played["next_effect_state"], prog)
    assert done.get("committed"), (done.get("stage"), done.get("reason"))
    return done


def pending_play(timing: dict) -> dict | None:
    return next((i for i in timing["chain"]["items"] if i.get("limited_play")), None)


# --- W1 ----------------------------------------------------------------------------------------

def check_real_chain() -> None:
    state = board()
    done = resolved_harrowing(state)
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    lp = pending_play(t1)
    if lp is None or lp["status"] != "pending" or [i["id"] for i in t1["chain"]["items"]] != [lp["id"]]:
        return fail("W1 resolved", f"the chain after the spell is {t1['chain']['items']}")
    entry = (e1.get("chain_items") or {}).get(lp["id"]) or {}
    if entry.get("card") != "tu" or "tu" in e1["players"]["p1"]["zones"]["trash"]:
        fail("W1 resolved", f"tu is not on the Chain as the play's item: {entry}")
    if "tu" in e1["players"]["p1"]["zones"]["base"] or any("tu" in bf["objects"] for bf in e1["battlefields"].values()):
        fail("W1 resolved", "the unit reached the board before its play's steps (Core 354.3)")
    if "harrowing" not in e1["players"]["p1"]["zones"]["trash"]:
        fail("W1 resolved", "the spell did not go to its owner's trash as it finished resolving")
    if next_procedure(t1).get("procedure") != "finalize_oldest_pending":
        fail("W1 resolved", f"the next procedure is {next_procedure(t1).get('procedure')}, not finalizing the play")
    bypass = finalize_oldest_pending(t1)
    if bypass.get("applied") or bypass.get("reason_code") != "limited_play_steps_required":
        fail("W1 resolved", f"the play was marked Finalized without its steps (Core 419.3.b): {bypass.get('reason_code')}")
    identity_on_chain = object_identity(e1, "tu")
    if identity_on_chain == object_identity(state, "tu"):
        fail("W1 resolved", "the card kept its identity leaving the trash (Core 124)")
    completed =complete_limited_play(t1, e1, entry_location=BASE, payment_context=CLOSED)
    if not completed.get("committed") or completed.get("removed"):
        return fail("W1 completed", f"{completed.get('stage')} {completed.get('reason')} {completed.get('message')}")
    e2, t2 = completed["next_effect_state"], completed["next_timing_state"]
    tu = e2["objects"]["tu"]
    if "tu" not in e2["players"]["p1"]["zones"]["base"] or not tu.get("exhausted"):
        fail("W1 completed", f"tu is not in p1's Base exhausted (Core 359.2.c): base={e2['players']['p1']['zones']['base']}")
    if e2["players"]["p1"]["resources"] != {"energy": 0, "power": {"chaos": 0}}:
        fail("W1 completed", f"the pool is {e2['players']['p1']['resources']}; only the Power cost is paid (356.1.b.2)")
    receipt = completed.get("cost_receipt") or {}
    if receipt.get("after_base_modifications") != {"energy": 0, "power": {"chaos": 1}} or receipt.get("base") != {"energy": 4, "power": {"chaos": 1}}:
        fail("W1 completed", f"the receipt does not show the printed cost with its Energy ignored: {receipt.get('base')} -> "
                             f"{receipt.get('after_base_modifications')}")
    if object_identity(e2, "tu") in (object_identity(state, "tu"),):
        fail("W1 completed", "the unit on the board is the object that was in the trash (Core 124)")
    if (e2.get("chain_items") or {}):
        fail("W1 completed", f"the Chain still holds {sorted(e2['chain_items'])}")
    if [(i["id"], i["status"]) for i in t2["chain"]["items"]] != [("tu-on-play", "pending")]:
        fail("W1 completed", f"the unit's own play trigger is not on the Chain (419.4.a): {t2['chain']['items']}")
    if "tu" not in (e2["players"]["p1"].get("cards_finalized_this_turn") or {}).get(e2.get("turn_id", "turn-0"), []):
        fail("W1 completed", "the card played is not recorded as Finalized this turn (419.4.b)")
    # the program run names the step it took: the card's move is a "play_started" with its zone change
    alone = apply_program(state_after_play_of(state), HARROWING, decisions=target_decision(state_after_play_of(state), "t", "tu"))
    kinds = [(ev["kind"], ev.get("object")) for ev in alone.get("events") or []]
    if ("play_started", "tu") not in kinds or ("left_location", "tu") not in kinds or ("entered_location", "tu") not in kinds:
        fail("W1 events", f"the program's events do not name the play's step: {kinds}")
    if alone.get("event_coverage") != "complete":
        fail("W1 events", f"event coverage {alone.get('event_coverage')}")


def state_after_play_of(state: dict) -> dict:
    """The board as the spell's program sees it: the spell on the Chain (its targets bound)."""
    played = play_harrowing(state)
    return played["next_effect_state"]


# --- W2 ----------------------------------------------------------------------------------------

SOUL_PROGRAM = program("soul-on-play-effects", "soul", [play_it()])
SOUL_REGISTRY = {SOUL_PROGRAM["program_id"]: SOUL_PROGRAM}


def soul_entered(state: dict | None = None) -> tuple[dict, dict]:
    state = copy.deepcopy(state if state is not None else board())
    state["objects"]["soul"] = card("p1", "unit", {"energy": 2, "power": {}}, might=4,
                                    play_triggers=[{"trigger_id": "soul-on-play", "controller": "p1", "source_object": "soul",
                                                    "controller_order": 0, "effect_program_id": SOUL_PROGRAM["program_id"],
                                                    "optional_at_finalize": True,
                                                    "effect_program_hash": program_hash(SOUL_PROGRAM)}])
    state["players"]["p1"]["zones"]["hand"].append("soul")
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-soul", "actor": "p1", "card": "soul",
            "chain_item": {"id": "unit-soul", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}}, "payment_context": CLOSED, "entry_location": BASE}
    played = play_card(fixture(), state, decl)
    assert played.get("committed"), played.get("reason")
    timing = finalize_oldest_pending(played["next_timing_state"])["next_state"]
    entered = resolve_with_program(timing, "unit-soul", played["next_effect_state"], None)
    assert entered.get("committed"), entered.get("reason")
    return entered["next_timing_state"], entered["next_effect_state"]


def check_trigger() -> None:
    timing, state = soul_entered()
    if [(i["id"], i["status"]) for i in timing["chain"]["items"]] != [("soul-on-play", "pending")]:
        return fail("W2", f"the play did not schedule the trigger: {timing['chain']['items']}")
    declined = finalize_trigger(timing, state, SOUL_REGISTRY, None, perform_optional_trigger=False)
    if not declined.get("committed") or (declined.get("transition") or {}).get("type") != "optional_trigger_declined" \
            or declined["next_timing_state"]["chain"]["items"]:
        fail("W2 declined", f"{declined.get('reason')} {declined.get('transition')}")
    if hash_value(declined.get("next_effect_state") or state) != hash_value(state):
        fail("W2 declined", "declining changed the board")
    ask = finalize_trigger(timing, state, SOUL_REGISTRY, None, perform_optional_trigger=True)
    if ask.get("committed") or ask.get("reason") != "target_selection_required":
        fail("W2 performed", f"performed without a target it should ask for one, got {ask.get('reason')}")
    fin = finalize_trigger(timing, state, SOUL_REGISTRY, target_decision(state, "t", "tu", "trigger_finalization"),
                           perform_optional_trigger=True)
    if not fin.get("committed"):
        return fail("W2 performed", f"{fin.get('stage')} {fin.get('reason')} {fin.get('message')}")
    ready = to_resolution(fin["next_timing_state"])
    chain_item = next(i for i in ready["chain"]["items"] if i["id"] == "soul-on-play")
    prog, refusal = dispatch_program(SOUL_REGISTRY, chain_item)
    if refusal:
        return fail("W2 performed", refusal)
    done = resolve_with_program(ready, "soul-on-play", fin.get("next_effect_state") or state, prog)
    if not done.get("committed") or pending_play(done["next_timing_state"]) is None:
        return fail("W2 resolved", f"{done.get('stage')} {done.get('reason')}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE,
                                      payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "tu" not in e2["players"]["p1"]["zones"]["base"] \
            or "soul" not in e2["players"]["p1"]["zones"]["base"]:
        fail("W2 completed", f"{completed.get('reason')} {completed.get('message')}")


# --- W3 ----------------------------------------------------------------------------------------

def check_chain_underneath() -> None:
    state = board(spell_timing="reaction")
    state["objects"]["o-spell"] = card("p2", "spell", {"energy": 1, "power": {}})
    state["chain_items"] = {"spell-o": {"card": "o-spell", "controller": "p2"}}
    under = fixture(priority="p1", items=[item("spell-o", "p2", "spell", "default")])
    played = play_harrowing(state, timing_state=under, timing="reaction")
    if not played.get("committed"):
        return fail("W3 play", f"{played.get('reason_code')} {played.get('reason')}")
    timing = to_resolution(played["next_timing_state"])
    step = next_procedure(timing)
    if step.get("subject") != "spell-h":
        return fail("W3", f"the reaction is not the next to resolve: {step}")
    done = resolve_with_program(timing, "spell-h", played["next_effect_state"], HARROWING)
    if not done.get("committed"):
        return fail("W3 resolve", done.get("reason"))
    ids = [(i["id"], i["status"]) for i in done["next_timing_state"]["chain"]["items"]]
    if len(ids) != 2 or ids[0] != ("spell-o", "finalized") or ids[1][1] != "pending":
        return fail("W3 resolve", f"the Chain is {ids}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE,
                                      payment_context=CLOSED)
    t2 = completed.get("next_timing_state") or {"chain": {"items": []}}
    after = [(i["id"], i["status"]) for i in t2["chain"]["items"]]
    if not completed.get("committed") or after[:1] != [("spell-o", "finalized")] or "o-spell" not in [
            e["card"] for e in (completed["next_effect_state"].get("chain_items") or {}).values()]:
        fail("W3 completed", f"the opponent's spell is not still on the Chain: {after}")
    elif ("tu-on-play", "pending") not in after:
        fail("W3 completed", f"the unit's own play trigger is missing: {after}")


# --- W4 ----------------------------------------------------------------------------------------

def check_own_place() -> None:
    state = board()
    victim = program("victim-dies-effects", "u2", [{"op": "draw", "effect_id": "dr", "player": "p2", "count": 1}])
    state["objects"]["u2"]["death_triggers"] = [{"trigger_id": "u2-dies", "controller": "p2", "source_object": "u2",
                                                  "controller_order": 0, "effect_program_id": victim["program_id"],
                                                  "optional_at_finalize": False}]
    prog = program("harrowing-effects", "harrowing", [
        {"op": "kill", "effect_id": "kl", "target": {"decision_ref": "k", "kind": "unit", "chosen_zone_class": "board"}},
        play_it()])
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state),
                 "decisions": target_decision(state, "t", "tu")["decisions"]
                 + target_decision(state, "k", "u2")["decisions"]}
    played = play_card(fixture(), state, harrowing_decl(), engine_decisions=decisions, effect_program=prog)
    if not played.get("committed"):
        return fail("W4 play", f"{played.get('reason_code')} {played.get('reason')}")
    done = resolve_with_program(to_resolution(played["next_timing_state"]), "spell-h", played["next_effect_state"], prog)
    if not done.get("committed"):
        return fail("W4 resolve", done.get("reason"))
    order = [(i["id"], i.get("limited_play", False)) for i in done["next_timing_state"]["chain"]["items"]]
    if len(order) != 2 or not order[0][1] or order[1][0] != "u2-dies":
        return fail("W4", f"the play's item is not ahead of the death trigger: {order}")
    if next_procedure(done["next_timing_state"]).get("subject") != order[0][0]:
        fail("W4", "the play is not the item finalized first")


# --- W5 ----------------------------------------------------------------------------------------

def check_ignore_all() -> None:
    prog = program("harrowing-effects", "harrowing", [play_it("ignore_all")])
    done = resolved_harrowing(board(power=0), prog)
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "tu" not in e2["players"]["p1"]["zones"]["base"]:
        return fail("W5", f"a play ignoring its cost needed {completed.get('reason')} {completed.get('message')}")
    if (completed.get("cost_receipt") or {}).get("total") != {"energy": 0, "power": {}}:
        fail("W5", f"the total is {(completed.get('cost_receipt') or {}).get('total')}, not zero (356.1.b.1)")


# --- C1 ----------------------------------------------------------------------------------------

def check_underpayment() -> None:
    prog = program("harrowing-effects", "harrowing", [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}, play_it()])
    state = board()
    done = resolved_harrowing(state, prog)
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    hand_after_draw = list(e1["players"]["p1"]["zones"]["hand"])
    # the Power is spent before the play is carried out (the 355.16 bound was met when it was chosen)
    e1 = copy.deepcopy(e1)
    e1["players"]["p1"]["resources"]["power"] = {}
    ask = finalize_limited_play(t1, e1, entry_location=BASE)
    if ask.get("committed") or ask.get("reason") != "add_window_confirmation_required":
        fail("C1 window", f"a resource cost without the Add window confirmed should be a decision, got {ask.get('reason')}")
    cancelled = finalize_limited_play(t1, e1, entry_location=BASE, payment_context=CLOSED)
    lp = pending_play(t1)
    if not cancelled.get("committed") or not cancelled.get("removed") \
            or (cancelled.get("transition") or {}).get("type") != "limited_play_cancelled":
        return fail("C1 cancelled", f"{cancelled.get('reason')} {cancelled.get('transition')}")
    e2 = cancelled["next_effect_state"]
    trash = e2["players"]["p1"]["zones"]["trash"]
    if trash.index("tu") != state["players"]["p1"]["zones"]["trash"].index("tu"):
        fail("C1 cancelled", f"tu is not back at its place in the trash: {trash}")
    if object_identity(e2, "tu") != object_identity(state, "tu") or e2["objects"]["tu"]["controller"] != "p1":
        fail("C1 cancelled", "the card came back as another object (Core 358.5 undoes the play's steps)")
    if lp["id"] in (e2.get("chain_items") or {}) or any(i["id"] == lp["id"] for i in cancelled["next_timing_state"]["chain"]["items"]):
        fail("C1 cancelled", "the play's item is still on the Chain")
    if cancelled["transition"].get("countered") is not False or cancelled["transition"].get("never_finalized") is not True:
        fail("C1 cancelled", f"a cancelled play is neither countered nor finalized: {cancelled['transition']}")
    if e2["players"]["p1"]["zones"]["hand"] != hand_after_draw or len(hand_after_draw) != len(state["players"]["p1"]["zones"]["hand"]):
        fail("C1 cancelled", "the draw before the play did not stand (GPT 2026-09-25)")
    if validate_state(e2):
        fail("C1 cancelled", f"the state does not validate: {validate_state(e2)[:2]}")


# --- C2 ----------------------------------------------------------------------------------------

def check_target_changed() -> None:
    state = board()
    played = play_harrowing(state)
    moved = copy.deepcopy(played["next_effect_state"])
    # tu leaves the trash and comes back: a new object (359.3.e.4)
    moved["objects"]["tu"]["identity"] = "tu@5"
    timing = to_resolution(played["next_timing_state"])
    done = resolve_with_program(timing, "spell-h", moved, HARROWING)
    if not done.get("committed"):
        return fail("C2", done.get("reason"))
    outcomes = [s.get("outcome") for s in done["trace"]["effect"]]
    if outcomes != ["ignored_illegal_target"] or pending_play(done["next_timing_state"]) is not None \
            or "tu" not in done["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
        fail("C2", f"a target that changed zones was played: {outcomes}")


# --- C3 ----------------------------------------------------------------------------------------

def check_355_16() -> None:
    state = board(power=0)
    # p1's unit in its Base records no Add ability (observed), so the bound is certain
    state["objects"]["u1"]["add_abilities"] = []
    refused = play_harrowing(state)
    if refused.get("committed") or refused.get("reason_code") != "limited_play_cost_unobtainable":
        fail("C3 refused", f"a unit whose Power could never be paid was chosen: {refused.get('reason_code')}")
    # a Rune of its Domain on the board could add that Power (164.2.b): the choice is not certain to fail
    with_rune = copy.deepcopy(state)
    with_rune["objects"]["r1"]["domains"] = ["chaos"]
    with_rune["players"]["p1"]["zones"]["rune_deck"].remove("r1")
    with_rune["players"]["p1"]["zones"]["base"].append("r1")
    allowed = play_harrowing(with_rune)
    if not allowed.get("committed"):
        fail("C3 rune", f"a Rune of the unit's Domain did not count: {allowed.get('reason_code')} {allowed.get('reason')}")
    other_rune = copy.deepcopy(with_rune)
    other_rune["objects"]["r1"]["domains"] = ["calm"]
    if play_harrowing(other_rune).get("reason_code") != "limited_play_cost_unobtainable":
        fail("C3 rune", "a Rune of another Domain counted for this Power")
    # an Add ability of that Domain on a ready permanent could pay it (357.1.a); exhausted, it could not
    adder = copy.deepcopy(state)
    adder["objects"]["u1"]["add_abilities"] = [{"power": {"chaos": 1}}]
    if not play_harrowing(adder).get("committed"):
        fail("C3 add", "a ready unit's recorded Add of the unit's Domain did not count")
    adder["objects"]["u1"]["exhausted"] = True
    if play_harrowing(adder).get("reason_code") != "limited_play_cost_unobtainable":
        fail("C3 add", "an exhausted unit's Add counted")
    # a permanent whose Add abilities nobody recorded: the choice is not certain to fail, so it is made
    unknown = copy.deepcopy(state)
    del unknown["objects"]["u1"]["add_abilities"]
    if play_harrowing(unknown).get("reason_code") == "limited_play_cost_unobtainable":
        fail("C3 unknown", "a choice was refused as certain to fail while a permanent's Add abilities were unknown")
    ignoring = program("harrowing-effects", "harrowing", [play_it("ignore_all")])
    if not play_harrowing(state, prog=ignoring).get("committed"):
        fail("C3 ignore", "a unit whose cost the effect ignores was refused")
    # the bound is Power: a unit that costs no Power is always choosable when its Energy is ignored
    if not play_harrowing(state, "cheap").get("committed"):
        fail("C3 cheap", "a unit whose only cost is ignored Energy was refused")


# --- C4 ----------------------------------------------------------------------------------------

def check_forged() -> None:
    done = resolved_harrowing()
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    lp = pending_play(t1)
    good = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "forged", "actor": "p1", "card": "tu",
            "chain_item": {"id": lp["id"], "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 4, "power": {"chaos": 1}}}, "source": {"kind": "trash"},
            "source_permission": {"granted_by": "harrowing"}, "cost_override": {"kind": "ignore_energy", "source": "harrowing"},
            "timing_source": "limited_play", "payment_context": CLOSED, "entry_location": BASE}
    if not play_card(t1, e1, good).get("committed"):
        fail("C4 control", "the effect's own declaration did not commit")
    for label, change in (("a lower cost.base", {"cost": {"base": {"energy": 0, "power": {}}}}),
                          ("another override", {"cost_override": {"kind": "ignore_base_cost", "source": "harrowing"}}),
                          ("another permission", {"source_permission": {"granted_by": "someone"}}),
                          ("another source", {"source": {"kind": "hand"}}),
                          ("reaction timing", {"chain_item": {"id": lp["id"], "object_kind": "unit", "timing": "reaction"}})):
        result = play_card(t1, e1, {**good, **change})
        if result.get("committed") or result.get("reason_code") not in {"limited_play_declaration_mismatch", "invalid_input"}:
            fail("C4 " + label, f"accepted or refused for the wrong reason: {result.get('reason_code')} {result.get('reason')}")
    # a card in hand declared as a limited play: nothing started it
    state = board()
    hand = play_card(fixture(), state, {**harrowing_decl(), "timing_source": "limited_play",
                                        "source": {"kind": "hand"}, "cost_override": {"kind": "ignore_energy", "source": "x"}},
                     engine_decisions=target_decision(state, "t", "tu"), effect_program=HARROWING)
    if hand.get("committed") or hand.get("reason_code") != "invalid_input" or "limited_play_not_started" not in str(hand.get("reason")) and "is not on the Chain" not in str(hand.get("reason")):
        fail("C4 not started", f"{hand.get('reason_code')} {hand.get('reason')}")
    # not the oldest Pending item: an earlier Pending item must be finalized first (337.1.b)
    earlier = copy.deepcopy(t1)
    earlier["chain"]["items"].insert(0, item("spell-x", "p2", "spell", "default", "pending"))
    e_earlier = copy.deepcopy(e1)
    e_earlier["objects"]["xs"] = card("p2", "spell", {"energy": 0, "power": {}})
    e_earlier["chain_items"]["spell-x"] = {"card": "xs", "controller": "p2"}
    result = play_card(earlier, e_earlier, good)
    if result.get("committed") or result.get("reason_code") != "limited_play_not_next":
        fail("C4 not next", f"{result.get('reason_code')} {result.get('reason')}")
    if finalize_limited_play(earlier, e_earlier, entry_location=BASE, payment_context=CLOSED).get("reason") != "pending_item_is_not_a_limited_play":
        fail("C4 not next", "finalize_limited_play did not refuse a non-limited oldest Pending item")
    ability = {**good, "chain_item": {"id": "ab", "object_kind": "ability", "timing": "default"},
               "activation": {"source_object": "u1", "ability_id": "x"}, "card": "u1"}
    if not any("an ability is not played" in e for e in validate_declaration(ability)):
        fail("C4 ability", "an ability declared as a limited play was not refused")


# --- C5 ----------------------------------------------------------------------------------------

def check_op_alone() -> None:
    state = state_after_play_of(board())
    run = apply_program(state, HARROWING, decisions=target_decision(state, "t", "tu"))
    after = run.get("next_state") or {}
    if not run.get("committed") or [s.get("outcome") for s in run["trace"]] != ["applied"]:
        return fail("C5", f"{run.get('reason')} {run.get('errors')}")
    if "tu" in after["players"]["p1"]["zones"]["base"] or any("tu" in bf["objects"] for bf in after["battlefields"].values()):
        fail("C5", "the instruction alone put the card on the board")
    if not run.get("limited_plays") or run["limited_plays"][0]["card"] != "tu":
        fail("C5", f"the result does not name the play it started: {run.get('limited_plays')}")
    try:
        _apply_one(state, {"op": "limited_play", "effect_id": "x", "object_id": "tu", "cost_basis": {"kind": "ignore_all"}})
        fail("C5", "_apply_one ran the play as a bare instruction")
    except ValueError:
        pass


# --- C6 ----------------------------------------------------------------------------------------

def check_no_target() -> None:
    state = board()
    ask = play_card(fixture(), state, harrowing_decl(), effect_program=HARROWING)
    if ask.get("committed") or ask.get("reason_code") != "target_selection_required":
        fail("C6 none", f"{ask.get('reason_code')}")
    for label, object_id in (("a spell in the trash", "c3"), ("an opponent's unit", "ou"), ("a unit on the board", "u1")):
        result = play_harrowing(state, object_id)
        if result.get("committed") or result.get("reason_code") != "target_illegal_at_play":
            fail(f"C6 {label}", f"{result.get('reason_code')} {result.get('reason')}")
    blind = copy.deepcopy(state)
    del blind["objects"]["tu"]["printed_cost"]
    result = play_harrowing(blind)
    if result.get("committed") or result.get("reason_code") != "limited_play_cost_not_observed" or not result.get("unsupported"):
        fail("C6 no printed cost", f"{result.get('reason_code')} unsupported={result.get('unsupported')}")


# --- C7 ----------------------------------------------------------------------------------------

def check_entry_location() -> None:
    done = resolved_harrowing()
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    ask = finalize_limited_play(t1, e1, payment_context=CLOSED)
    if ask.get("committed") or ask.get("reason") != "entry_location_required" or {"kind": "base"} not in ask.get("location_candidates", []):
        fail("C7 ask", f"{ask.get('reason')} {ask.get('location_candidates')}")
    bad = finalize_limited_play(t1, e1, entry_location={"kind": "battlefield", "battlefield": "bf1"}, payment_context=CLOSED)
    if bad.get("committed") or bad.get("reason") != "entry_location_illegal":
        fail("C7 illegal", f"an illegal location was not refused (or cancelled the play): {bad.get('reason')} {bad.get('removed')}")


# --- C8 ----------------------------------------------------------------------------------------

def check_shapes() -> None:
    for label, change in (("a hand target", {"target": trash_target(location="hand")}),
                          ("no own zone", {"target": {k: v for k, v in trash_target().items() if k != "zone_owner_relation"}}),
                          ("a board zone class", {"target": trash_target(chosen_zone_class="board")}),
                          ("an unknown basis", {"cost_basis": {"kind": "ignore_most"}}),
                          ("an extra field", {"entry": {"kind": "base"}}),
                          ("a rune", {"target": trash_target(kind="rune")})):
        wrong = program("x", "harrowing", [{**play_it(), **change}])
        if not validate_program(wrong):
            fail("C8 " + label, "validated")
    done = resolved_harrowing()
    e1 = copy.deepcopy(done["next_effect_state"])
    lp = pending_play(done["next_timing_state"])
    e1["chain_items"][lp["id"]]["limited_play"]["cost_basis"] = {"kind": "free"}
    if not validate_state(e1):
        fail("C8 record", "a malformed limited-play record validated")


# --- C9 ----------------------------------------------------------------------------------------

def check_prohibited() -> None:
    done = resolved_harrowing()
    e1 = copy.deepcopy(done["next_effect_state"])
    e1["turn_effects"] = [{"effect_id": "brynhir", "kind": "cards_play_prohibited", "controller": "p2",
                           "turn_id": e1.get("turn_id", "turn-0"), "value": "opponents", "source": "brynhir"}]
    cancelled = finalize_limited_play(done["next_timing_state"], e1, entry_location=BASE, payment_context=CLOSED)
    if not cancelled.get("removed") or (cancelled.get("transition") or {}).get("reason_code") != "play_prohibited":
        fail("C9", f"{cancelled.get('reason')} {cancelled.get('transition')}")


# --- H: a hand choice, the location the effect names, [C] ------------------------------------------

AVA_PROGRAM = program("ava-on-attack-effects", "ava", [
    {"op": "trigger_base_cost", "effect_id": "cost", "payment": [{"kind": "power_own_domain", "amount": 1}]},
    {"op": "limited_play", "effect_id": "lp", "decision_ref": "c",
     "choice": {"from": "hand", "selection_kind": "unordered_set", "count": {"up_to": 1}, "by": "controller",
                "visibility": "private_to_chooser"}, "card_filter": {"hidden": True},
     "entry": {"kind": "unit_at_source_battlefield"}, "cost_basis": {"kind": "ignore_all"}}])
AVA_REGISTRY = {AVA_PROGRAM["program_id"]: AVA_PROGRAM}


def ava_board(*, domains=("mind",), hand=("hid-unit", "hid-gear", "plain")) -> dict:
    """Ava (p1, Domain mind) at bf1, which p2 controls, with p2's unit there (contested by Ava's arrival); p1's
    hand holds a unit and a gear with [Hidden] and a unit without; p1 has one mind Power."""
    state = base_state()
    state["objects"]["ava"] = card("p1", "unit", {"energy": 3, "power": {}}, might=3,
                                   **({"domains": list(domains)} if domains is not None else {}))
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"] = {"controller": "p2", "objects": ["u2", "ava"], "contested": True, "contested_by": "p1"}
    state["players"]["p2"]["zones"]["base"].remove("u2")
    state["players"]["p1"]["zones"]["base"].append("u1")
    pool = {"hid-unit": card("p1", "unit", {"energy": 5, "power": {"mind": 2}}, might=4, hidden=True),
            "hid-gear": card("p1", "gear", {"energy": 2, "power": {}}, hidden=True),
            "plain": card("p1", "unit", {"energy": 1, "power": {}}, might=1)}
    for name in hand:
        state["objects"][name] = pool[name]
        state["players"]["p1"]["zones"]["hand"].append(name)
    state["players"]["p1"]["resources"] = {"energy": 0, "power": {"mind": 1}}
    problems = validate_state(state)
    assert not problems, problems
    return state


def ava_pending(state: dict) -> dict:
    from rules_core import schedule_triggered_items
    descriptor = {"trigger_id": "ava-on-attack", "controller": "p1", "source_object": "ava", "controller_order": 0,
                  "effect_program_id": AVA_PROGRAM["program_id"], "optional_at_finalize": True,
                  "effect_program_hash": program_hash(AVA_PROGRAM), "trigger_kind": "triggered",
                  "source_identity": object_identity(state, "ava")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    assert scheduled.get("applied"), scheduled
    return scheduled["next_state"]


def ava_resolved(state: dict, chosen: list[str] | None, *, move_away: bool = False) -> dict:
    timing = ava_pending(state)
    fin = finalize_trigger(timing, state, AVA_REGISTRY, None, perform_optional_trigger=True, pay_trigger_cost=True,
                           payment_context=CLOSED)
    assert fin.get("committed") and not fin.get("removed"), (fin.get("reason"), fin.get("message"))
    board_now = copy.deepcopy(fin["next_effect_state"])
    if move_away:
        board_now["battlefields"]["bf1"]["objects"].remove("ava")
        board_now["players"]["p1"]["zones"]["base"].append("ava")
        board_now["battlefields"]["bf1"].update({"contested": False, "contested_by": None})
    decisions = None
    if chosen is not None:
        decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(board_now),
                     "decisions": [{"decision_id": "c", "stage": "resolution", "kind": "card_selection", "controller": "p1",
                                    "value": list(chosen), "selection_identities": {c: object_identity(board_now, c) for c in chosen}}]}
    ready = to_resolution(fin["next_timing_state"])
    item_ = next(i for i in ready["chain"]["items"] if i["id"] == "ava-on-attack")
    prog, refusal = dispatch_program(AVA_REGISTRY, item_)
    assert refusal is None, refusal
    return {"done": resolve_with_program(ready, "ava-on-attack", board_now, prog, engine_decisions=decisions),
            "paid": fin["next_effect_state"]}


def check_hand_choice() -> None:
    state = ava_board()
    run = ava_resolved(state, ["hid-unit"])
    done = run["done"]
    if not done.get("committed"):
        return fail("H unit", f"{done.get('stage')} {done.get('reason')}")
    if run["paid"]["players"]["p1"]["resources"]["power"].get("mind") != 0:
        fail("H cost", f"[C] did not take ava's one mind Power: {run['paid']['players']['p1']['resources']}")
    lp = pending_play(done["next_timing_state"])
    record = ((done["next_effect_state"].get("chain_items") or {}).get((lp or {}).get("id")) or {}).get("limited_play") or {}
    if lp is None or record.get("source_zone") != "hand" or record.get("entry_location") != {"kind": "battlefield", "battlefield": "bf1"}:
        return fail("H unit", f"the play did not start from the hand with 'here' named: {record}")
    other = finalize_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE, payment_context=CLOSED)
    if other.get("committed") or other.get("reason") != "entry_location_named_by_the_effect":
        fail("H named", f"another location than 'here' was taken: {other.get('reason')}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "hid-unit" not in e2["battlefields"]["bf1"]["objects"]:
        return fail("H unit", f"the unit is not at bf1: {completed.get('reason')} {completed.get('message')}")
    if e2["players"]["p1"]["resources"] != {"energy": 0, "power": {"mind": 0}} or "hid-unit" in e2["players"]["p1"]["zones"]["hand"]:
        fail("H unit", f"the play paid something or left the card in hand: {e2['players']['p1']['resources']}")
    # choosing none (128.6), and nothing to choose (419.3.c)
    declined = ava_resolved(state, [])["done"]
    if [s.get("outcome") for s in declined["trace"]["effect"]] != ["paid_at_finalization", "no_op"] or pending_play(declined["next_timing_state"]):
        fail("H none chosen", f"{[s.get('outcome') for s in declined['trace']['effect']]}")
    empty = ava_resolved(ava_board(hand=("plain",)), None)["done"]
    if not empty.get("committed") or [s.get("reason") for s in empty["trace"]["effect"]][1:] != ["no_eligible_card"]:
        fail("H no hidden card", f"{empty.get('reason')} {[s.get('reason') for s in (empty.get('trace') or {}).get('effect', [])]}")
    asked = ava_resolved(state, None)["done"]
    asked_effect = asked.get("effect_result") or {}
    if asked.get("committed") or not asked_effect.get("choice_required") or asked_effect.get("decision_controller") != "p1":
        fail("H ask", f"the choice was made for the player: {asked_effect.get('reason_code')} {asked.get('reason')}")
    plain = ava_resolved(state, ["plain"])["done"]
    if plain.get("committed"):
        fail("H no [Hidden]", "a card without [Hidden] was played")
    # a gear with [Hidden]: 'If it's a unit' names no location; it enters its Base
    gear = ava_resolved(state, ["hid-gear"])["done"]
    gear_done = complete_limited_play(gear["next_timing_state"], gear["next_effect_state"], payment_context=CLOSED)
    if not gear_done.get("committed") or "hid-gear" not in gear_done["next_effect_state"]["players"]["p1"]["zones"]["base"]:
        fail("H gear", f"{gear_done.get('reason')} {gear_done.get('message')}")
    # the source gone from the Battlefield: no 'here'; the location is the player's choice (355.2.a)
    away = ava_resolved(state, ["hid-unit"], move_away=True)["done"]
    ask = finalize_limited_play(away["next_timing_state"], away["next_effect_state"], payment_context=CLOSED)
    if ask.get("reason") != "entry_location_required":
        fail("H here gone", f"{ask.get('reason')}")
    # cancelled (the player cannot play cards): back in the hand at its place
    prohibited = copy.deepcopy(done["next_effect_state"])
    prohibited["turn_effects"] = [{"effect_id": "stop", "kind": "cards_play_prohibited", "controller": "p2",
                                   "turn_id": prohibited.get("turn_id", "turn-0"), "value": "opponents", "source": "x"}]
    cancel = finalize_limited_play(done["next_timing_state"], prohibited, payment_context=CLOSED)
    hand = (cancel.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("zones", {}).get("hand", [])
    if not cancel.get("removed") or hand.index("hid-unit") != state["players"]["p1"]["zones"]["hand"].index("hid-unit"):
        fail("H cancelled", f"the card is not back in the hand at its place: {hand}")
    # [C] with two Domains, or none recorded: no one Domain to pay
    for label, domains in (("two Domains", ("mind", "calm")), ("no Domain recorded", None)):
        other_board = ava_board(domains=domains)
        fin = finalize_trigger(ava_pending(other_board), other_board, AVA_REGISTRY, None, perform_optional_trigger=True,
                               pay_trigger_cost=True, payment_context=CLOSED)
        if fin.get("committed") or fin.get("reason") != "trigger_cost_domain_not_single":
            fail(f"H [C] {label}", f"{fin.get('reason')}")
    for label, change in (("one card counted exactly", {"count": {"exactly": 1}}), ("from the trash", {"from": "trash"}),
                          ("chosen by the opponent", {"by": "opponent"}), ("a single choice", {"selection_kind": "single", "count": {"one": True}})):
        wrong = program("x", "ava", [{**AVA_PROGRAM["effects"][1], "choice": {**AVA_PROGRAM["effects"][1]["choice"], **change}}])
        if not validate_program(wrong):
            fail(f"H shape: {label}", "validated")
    both = program("x", "ava", [{**AVA_PROGRAM["effects"][1], "target": trash_target()}])
    if not validate_program(both):
        fail("H shape: a target and a choice", "validated")


def main() -> int:
    for check in (check_real_chain, check_trigger, check_chain_underneath, check_own_place, check_ignore_all,
                  check_underpayment, check_target_changed, check_355_16, check_forged, check_op_alone,
                  check_no_target, check_entry_location, check_shapes, check_prohibited, check_hand_choice):
        try:
            check()
        except AssertionError as exc:
            fail(check.__name__, f"setup failed: {exc}")
        except (KeyError, TypeError, IndexError, ValueError, AttributeError) as exc:
            # a board the engine should have produced and did not (the play never queued, say)
            fail(check.__name__, f"{type(exc).__name__}: {exc}")
    if errors:
        print("FAILED: effect-driven play (Core 419.3)")
        for problem in errors:
            print("  - " + problem)
        return 1
    print("OK: effect-driven play - step 1 at the instruction, steps 2-5 through the play transaction from the Chain "
          "(real Chain, trigger performed/declined, a Chain underneath, its place before triggers, cost ignored, "
          "underpayment cancelled with the effect standing, target changed, 355.16, forged declarations, no target, "
          "entry location, shapes, prohibition; a hand choice with the location the effect names and a base cost of "
          "the card's own Domain)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
