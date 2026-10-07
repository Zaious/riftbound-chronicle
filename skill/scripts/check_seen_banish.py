#!/usr/bin/env python3
"""A card that may banish itself as its owner looks at or reveals it from the top of their deck, then be played for [A]
(package 9, Nocturne - Horrifying).

"As you look at or reveal me from the top of your deck, you may banish me. If you do, you may play me for [A]." GPT
2026-10-06 (PACKAGE9_INVENTORY section 4): the optional banish is handled as it is looked at or revealed - no ordinary
triggered Chain item; only after the banish is it played with [A] from Banishment (Core 356.1.a), the original effect
finishing first; Predict, an explicit look at the top, and a reveal of the top all count; a plain draw does not. GPT
2026-10-07: inside a Predict the offer comes as the card is looked at, before Predict recycles or puts it back.

The engine's shape: object field banish_when_seen {play_for_power_any}; apply_program offers the banish (optional_choice
seen-banish:<program>:<instruction>:<card>, its owner's) right after an instruction in SEEN_FROM_TOP_OPS, and - when it
was banished - the play (optional_choice seen-play:<program>:<card>) once every instruction of the program is done:
limited_play cost_basis for_power_any, the base cost replaced and [A] paid as a mandatory power_any component.

  N1 look           p1's spell: look at the top 2 of p1's deck, Nocturne on top - banished, then played for [A]: on the
                    Chain as p1's Pending play from p1's Banishment; completed, it enters p1's Base, one Power of any
                    Domain paid, no Energy
  N2 declined       the banish declined: Nocturne stays on top, no play offered
  N3 not played     banished, the play declined: it stays in p1's Banishment
  N4 draw           a draw of the top card offers nothing
  N5 not yours      p2 looks at the top of p1's deck: nothing offered (it is "you", its owner, who looks)
  N6 reveal         p1 reveals from the top until a unit, Nocturne the unit: offered, banished
  N7 effect first   look at the top 1, then draw 1: the draw takes the next card (Nocturne already banished) and the
                    play is offered only after the draw
  N8 Power short    no Power to pay [A]: the play cancelled, the card back in Banishment
  N9 Predict, banished  p1 predicts 2, Nocturne on top: the banish is asked FIRST, before Predict's recycle; banished,
                    it is neither recycled nor put back (a recycle choice naming it is refused). The banish does not undo
                    the look (GPT 2026-10-08): the receipt still reads looked_count 2, looked_hash over both cards,
                    completion full, applied; only c9 is left for Predict (disposable_count 1, put back 1)
  N10 Predict, declined  the banish declined: Predict recycles it (the bottom of p1's deck); looked 2, full
  N11 Predict, declined  the banish declined: Predict puts it back on top; looked 2, full
  N12 Predict 1      p1 predicts 1, only Nocturne looked at and banished: a completed look - looked_count 1, completion
                    full, applied, never no_op; nothing left to recycle or put back
  S  shapes         banish_when_seen and the cost basis typed; a declaration without the [A] component refused

    python skill/scripts/check_seen_banish.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, _ids_hash, apply_program, hash_value, object_identity,  # noqa: E402
                       validate_program,
                       validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import complete_limited_play, finalize_limited_play, resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects, controller="p1"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": "peek-effects", "controller": controller,
            "source_object": "peek", "effects": effects}


def board(*, power=1, owner_of_peek="p1") -> dict:
    """p1's Nocturne (noc, printed [4][Chaos], Might 4) on top of p1's Main Deck, c9 under it; the spell `peek` in its
    caster's hand; p1 holds `power` Power of Fury (any Domain pays [A])."""
    state = base_state()
    state["objects"]["noc"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 4, "might_modifiers": [],
                               "damage": 0, "exhausted": False, "printed_cost": {"energy": 4, "power": {"chaos": 1}},
                               "banish_when_seen": {"play_for_power_any": 1}}
    state["objects"]["c9"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "printed_cost": {"energy": 1, "power": {}}}
    state["players"]["p1"]["zones"]["main_deck"] = ["noc", "c9"] + state["players"]["p1"]["zones"]["main_deck"]
    state["objects"]["peek"] = {"owner": owner_of_peek, "controller": owner_of_peek, "kind": "spell", "base_might": 0,
                                "might_modifiers": [], "damage": 0, "exhausted": False, "printed_cost": {"energy": 0, "power": {}}}
    state["players"][owner_of_peek]["zones"].setdefault("hand", []).append("peek")
    state["players"]["p1"]["resources"] = {"energy": 0, "power": {"fury": power} if power else {}}
    state["players"]["p2"]["resources"] = {"energy": 0, "power": {}}
    assert not validate_state(state), validate_state(state)
    return state


def cast(state, prog, choices: dict[str, bool]) -> dict:
    """Play `peek` running `prog`, then resolve it, answering each optional choice the engine asks from `choices`."""
    caster = prog["controller"]
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-peek", "actor": caster, "card": "peek",
            "effect_program_id": prog["program_id"], "chain_item": {"id": "spell-peek", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}}, "payment_context": CLOSED}
    timing = fixture()
    if caster == "p2":
        timing = {**timing, "turn_player": "p2", "priority": "p2"}
    played = play_card(timing, state, decl, effect_program=prog)
    assert played.get("committed"), (played.get("reason_code"), played.get("reason"))
    t = played["next_timing_state"]
    if next_procedure(t).get("procedure") == "finalize_oldest_pending":
        t = finalize_oldest_pending(t)["next_state"]
    for actor in (caster, "p1" if caster == "p2" else "p2"):
        t = (pass_priority(t, actor) or {}).get("next_state") or t
    effect = played["next_effect_state"]
    decisions, asked = [], []
    for _ in range(6):
        env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(effect), "decisions": list(decisions)} if decisions else None
        done = resolve_with_program(t, "spell-peek", effect, prog, engine_decisions=env)
        er = done.get("effect_result") or {}
        if done.get("committed") or not er.get("optional_choice_required"):
            return {**done, "asked": asked}
        ref = er["decision_ids"][0]
        asked.append(ref)
        key = next((k for k in choices if ref.startswith(k)), None)
        if key is None:
            return {**done, "asked": asked, "unanswered": ref}
        decisions.append({"decision_id": ref, "stage": "resolution", "kind": "optional_choice",
                          "controller": er["decision_controller"], "value": choices[key]})
    return {"asked": asked, "loop": True}


def where(state, card):
    for player, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if card in ids:
                return f"{player}:{zone}"
    for k, v in (state.get("chain_items") or {}).items():
        if v.get("card") == card:
            return f"chain:{k}"
    return None


LOOK2 = [{"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 2}]
PREDICT2 = program([{"op": "predict", "effect_id": "pr", "player": "p1", "count": 2}])


def run_predict(state, banish: bool, recycle: list[str], order: list[str] | None = None, count: int = 2) -> tuple[dict, list[str]]:
    """apply_program over p1's Predict `count`, answering each decision it asks in turn: the banish (as asked), the cards
    to recycle (`recycle`), the order of the rest (`order`, else as they are). Returns (the result, the decisions asked)."""
    prog = PREDICT2 if count == 2 else program([{"op": "predict", "effect_id": "pr", "player": "p1", "count": count}])
    decisions, asked = [], []
    for _ in range(6):
        env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": list(decisions)} \
            if decisions else None
        got = apply_program(state, prog, decisions=env)
        if got.get("committed") or not got.get("decision_ids"):
            return got, asked
        ref = got["decision_ids"][0]
        asked.append(ref)
        if ref.startswith("seen-banish"):
            decisions.append({"decision_id": ref, "stage": "resolution", "kind": "optional_choice", "controller": "p1",
                              "value": banish})
        elif ref.startswith("seen-play"):
            decisions.append({"decision_id": ref, "stage": "resolution", "kind": "optional_choice", "controller": "p1",
                              "value": False})
        elif ref.endswith(":recycle"):
            decisions.append({"decision_id": ref, "stage": "resolution", "kind": "card_selection", "controller": "p1",
                              "value": list(recycle), "selection_identities": {c: object_identity(state, c) for c in recycle}})
        elif ref.endswith(":put_back"):
            rest = order if order is not None else (got.get("choice") or {}).get("options") or []
            decisions.append({"decision_id": ref, "stage": "resolution", "kind": "card_ordering", "controller": "p1",
                              "value": list(rest), "selection_identities": {c: object_identity(state, c) for c in rest}})
        else:
            return got, asked
    return {"loop": True}, asked


def predict_receipt(label: str, got: dict, looked: list[str], **want) -> None:
    """The Predict trace entry reads the cards actually looked at (GPT 2026-10-08): looked_count, looked_hash over exactly
    `looked` (each with its identity after the instruction, as for every Predict), completion and outcome - and any
    other field named in `want`."""
    entry = next((t for t in got.get("trace") or [] if t.get("op") == "predict"), None)
    if entry is None:
        fail(label, "no predict entry in the trace")
        return
    expected = {"looked_count": len(looked), "looked_hash": _ids_hash(got["next_state"], looked), "completion": "full",
                "outcome": "applied", **want}
    wrong = {k: (entry.get(k), v) for k, v in expected.items() if entry.get(k) != v}
    if wrong:
        fail(label, f"the receipt (got, wanted): {wrong}")


def predict(errors_out: list[str]) -> None:
    def deck(result):
        return result["next_state"]["players"]["p1"]["zones"]["main_deck"]

    # N9: banished as it is looked at - Predict cannot recycle it, nor put it back; the look itself stands
    got, asked = run_predict(board(), True, [], ["c9"])
    if not got.get("committed") or where(got["next_state"], "noc") != "p1:banishment" or "noc" in deck(got):
        fail("N9 banished first", f"{got.get('reason') or got.get('errors')} asked {asked} "
                                  f"{where(got['next_state'], 'noc') if got.get('committed') else None}")
    elif not asked or not asked[0].startswith("seen-banish"):
        fail("N9 banished first", f"the banish was not asked before Predict's own choices: {asked}")
    else:
        predict_receipt("N9 banished first", got, ["noc", "c9"], disposable_count=1, recycled_count=0, put_back_count=1)
    tried, _ = run_predict(board(), True, ["noc"])
    if tried.get("committed") or "cannot be chosen" not in str(tried.get("reason")):
        fail("N9 banished first", f"Predict's recycle naming the banished card was not refused as a choice it cannot "
                                  f"make: {tried.get('committed')} {tried.get('reason')}")
    # N10: declined - Predict recycles it
    got, asked = run_predict(board(), False, ["noc"])
    if not got.get("committed") or deck(got)[-1:] != ["noc"] or not asked[0].startswith("seen-banish"):
        fail("N10 declined, recycled", f"{got.get('reason') or got.get('errors')} asked {asked}")
    else:
        predict_receipt("N10 declined, recycled", got, ["noc", "c9"], recycled_count=1, put_back_count=1)
    # N11: declined - Predict puts it back on top
    got, asked = run_predict(board(), False, [], ["noc", "c9"])
    if not got.get("committed") or deck(got)[:1] != ["noc"] or where(got["next_state"], "noc") != "p1:main_deck":
        fail("N11 declined, put back", f"{got.get('reason') or got.get('errors')} asked {asked}")
    else:
        predict_receipt("N11 declined, put back", got, ["noc", "c9"], recycled_count=0, put_back_count=2)
    # N12: Predict 1, its only card banished as it is looked at - still a completed look, not a no_op
    got, asked = run_predict(board(), True, [], [], count=1)
    if not got.get("committed") or where(got["next_state"], "noc") != "p1:banishment":
        fail("N12 Predict 1", f"{got.get('reason') or got.get('errors')} asked {asked}")
    else:
        predict_receipt("N12 Predict 1", got, ["noc"], requested_count=1, disposable_count=0, recycled_count=0,
                        put_back_count=0)


def main() -> int:
    # N1
    done = cast(board(), program(LOOK2), {"seen-banish": True, "seen-play": True})
    e = done.get("next_effect_state")
    if not done.get("committed") or e is None:
        fail("N1 look", f"{done.get('reason')} asked {done.get('asked')} {done.get('unanswered')}")
    else:
        if [a.split(":")[0] for a in done["asked"]] != ["seen-banish", "seen-play"]:
            fail("N1 look", f"asked {done['asked']}")
        item = next((k for k, v in (e.get("chain_items") or {}).items() if v.get("card") == "noc"), None)
        record = ((e.get("chain_items") or {}).get(item) or {}).get("limited_play") or {}
        if item is None or record.get("source_zone") != "banishment" or record.get("cost_basis") != {"kind": "for_power_any", "amount": 1}:
            fail("N1 look", f"not on the Chain as a play from Banishment for [A]: {where(e, 'noc')} {record}")
        else:
            completed = complete_limited_play(done["next_timing_state"], e, entry_location={"kind": "base"}, payment_context=CLOSED)
            after = completed.get("next_effect_state") or {}
            if not completed.get("committed") or where(after, "noc") != "p1:base":
                fail("N1 played", f"{completed.get('reason')} {completed.get('message')} {where(after, 'noc') if after else None}")
            elif after["players"]["p1"]["resources"] != {"energy": 0, "power": {"fury": 0}}:
                fail("N1 [A] paid", f"{after['players']['p1']['resources']}")
            # S: the same play declared without its [A] component is refused, not played for nothing
            t1 = done["next_timing_state"]
            pending = next(i for i in t1["chain"]["items"] if i.get("limited_play"))
            forged = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "forged", "actor": "p1",
                      "card": "noc", "chain_item": {"id": pending["id"], "object_kind": "unit", "timing": "default"},
                      "cost": {"base": copy.deepcopy(e["objects"]["noc"]["printed_cost"])},
                      "source": {"kind": "banishment"}, "source_permission": {"granted_by": record["granted_by"]},
                      "cost_override": {"kind": "for_cost", "cost": {"energy": 0, "power": {}}, "source": record["granted_by"]},
                      "timing_source": "limited_play", "payment_context": CLOSED, "entry_location": {"kind": "base"}}
            refused = play_card(t1, e, forged)
            if refused.get("committed") or "limited:for_power_any" not in str(refused.get("reason")):
                fail("S forged", f"a play without its [A] was {refused.get('reason_code') or 'committed'}")
    # N2
    done = cast(board(), program(LOOK2), {"seen-banish": False})
    if not done.get("committed") or where(done["next_effect_state"], "noc") != "p1:main_deck" \
            or done["next_effect_state"]["players"]["p1"]["zones"]["main_deck"][0] != "noc" \
            or any(a.startswith("seen-play") for a in done["asked"]):
        fail("N2 declined", f"{done.get('reason')} {done.get('asked')}")
    # N3
    done = cast(board(), program(LOOK2), {"seen-banish": True, "seen-play": False})
    if not done.get("committed") or where(done["next_effect_state"], "noc") != "p1:banishment":
        fail("N3 not played", f"{done.get('reason')} {where(done.get('next_effect_state') or board(), 'noc')}")
    # N4
    done = cast(board(), program([{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]), {})
    if not done.get("committed") or done["asked"] or where(done["next_effect_state"], "noc") != "p1:hand":
        fail("N4 draw", f"{done.get('reason')} {done.get('asked')}")
    # N5
    theirs = board(owner_of_peek="p2")
    done = cast(theirs, program([{"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 2}], controller="p2"), {})
    if not done.get("committed") or done["asked"]:
        fail("N5 not yours", f"{done.get('reason')} {done.get('asked')}")
    # N6
    done = cast(board(), program([{"op": "reveal_until", "effect_id": "rev", "player": "p1", "until": {"kind": "unit"}}]),
                {"seen-banish": True, "seen-play": False})
    if not done.get("committed") or where(done["next_effect_state"], "noc") != "p1:banishment":
        fail("N6 reveal", f"{done.get('reason')} {done.get('asked')}")
    # N7
    prog = program([{"op": "look_at_top", "effect_id": "look", "player": "p1", "count": 1},
                    {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])
    done = cast(board(), prog, {"seen-banish": True, "seen-play": False})
    trace = (done.get("trace") or {}).get("effect") or []
    order = [t.get("effect_id") for t in trace]
    if not done.get("committed") or where(done["next_effect_state"], "c9") != "p1:hand" \
            or order[:3] != ["look", "look:seen:noc", "dr"]:
        fail("N7 effect first", f"{done.get('reason')} {order}")
    # N8
    done = cast(board(power=0), program(LOOK2), {"seen-banish": True, "seen-play": True})
    if done.get("committed"):
        cancelled = finalize_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location={"kind": "base"},
                                          payment_context=CLOSED)
        if not cancelled.get("committed") or where(cancelled["next_effect_state"], "noc") != "p1:banishment":
            fail("N8 Power short", f"{cancelled.get('reason')} {where(cancelled.get('next_effect_state') or board(), 'noc')}")
    else:
        fail("N8 Power short", f"{done.get('reason')} {done.get('asked')}")
    # N9-N12: Predict (GPT 2026-10-07, 2026-10-08) - the banish is offered as the card is looked at, BEFORE Predict decides what to
    # recycle or put back
    predict(errors)
    # S
    bad = board()
    bad["objects"]["noc"]["banish_when_seen"] = {"play_for_power_any": 0}
    if not validate_state(bad):
        fail("S shapes", "banish_when_seen with 0 accepted")
    lp = {"op": "limited_play", "effect_id": "lp", "linked": {"effect_id": "ban", "from": "banishment"},
          "cost_basis": {"kind": "for_power_any"}}
    if not validate_program(program([{"op": "banish", "effect_id": "ban", "object_id": "noc"}, lp])):
        fail("S shapes", "for_power_any without its amount accepted")
    if errors:
        print("FAILED: seen banish checks")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("OK: a card seen from the top of its owner's deck may be banished then, and played for [A] once the effect is "
          "done (N1-N12, S)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
