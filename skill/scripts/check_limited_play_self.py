#!/usr/bin/env python3
"""A triggered ability that plays its own card from the trash, after a base cost (package 8, group 1).

"When you kill a unit with a spell, you may pay [1][Fury] to play me from your trash." (Immortal Phoenix) and
"When you discard me, you may pay [Fury] to play me." (Flame Chompers). GPT 2026-10-04 (PACKAGE8_INVENTORY
section 6, ruling 1): X is the triggered ability's base cost, paid as it is finalized (Core 204.3.a, 383.3.b);
the card is then played paying its own cost - X is not a "for X" replacement (356.1.a). The engine's shape:
`trigger_base_cost` X, then `limited_play` with `self: {from: trash}` and cost basis `printed` (419.3.b: the
steps are the normal ones). The card is the program's own source as the chain item recorded it; it is not
chosen, so it is not a target (355.7).

Held here (each on its own board; this file shares no witness with check_limited_play.py):

  S1 played        X paid at finalization ([1][Fury]); resolved, the card is on the Chain, Pending, out of the
                   trash; completed, it is in its Base, its printed cost paid on top of X, and the declaration
                   carries no cost_override
  S2 Fury only     the same with X = [Fury] (Flame Chompers' shape)
  S3 declined      the "you may" declined at finalization: nothing paid, nothing played (383.3.a.2)
  S4 gone          the card left the trash before the ability resolved: nothing is played, X stays paid
  S5 new object    it left and came back (Core 124): not the "me" the ability is about - nothing is played
  S6 underpayment  the printed cost cannot be paid when the play is carried out: the play is cancelled (358.5),
                   the card back in the trash; X stays paid (it was the ability's cost, not the play's)
  S7 forged        a declaration that claims a cost_override for this play is refused
  S8 shapes        self with a decision_ref, self from the hand, self beside a target - each refused

    python skill/scripts/check_limited_play_self.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import (complete_limited_play, dispatch_program, finalize_limited_play,  # noqa: E402
                               finalize_trigger, program_hash, resolve_with_program)
from rules_core import finalize_oldest_pending, next_procedure, pass_priority, schedule_triggered_items  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
BASE = {"kind": "base"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def program(program_id: str, source: str, effects: list[dict]) -> dict:
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": program_id, "controller": "p1",
            "source_object": source, "effects": effects}


def self_play(payment: list[dict]) -> list[dict]:
    return [{"op": "trigger_base_cost", "effect_id": "cost", "payment": payment},
            {"op": "limited_play", "effect_id": "lp", "self": {"from": "trash"}, "cost_basis": {"kind": "printed"}}]


PHOENIX = program("phoenix-effects", "phx", self_play([{"kind": "energy", "amount": 1}, {"kind": "power", "domain": "fury", "amount": 1}]))
CHOMPERS = program("chompers-effects", "phx", self_play([{"kind": "power", "domain": "fury", "amount": 1}]))


def board(*, energy: int = 4, fury: int = 2) -> dict:
    """p1's unit `phx` (Energy 3, Power 1 fury) in its trash; p1 has `energy` Energy and `fury` fury Power."""
    state = base_state()
    state["objects"]["phx"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                               "damage": 0, "exhausted": False, "printed_cost": {"energy": 3, "power": {"fury": 1}},
                               "domains": ["fury"]}
    state["players"]["p1"]["zones"]["trash"].append("phx")
    state["players"]["p1"]["resources"] = {"energy": energy, "power": {"fury": fury}}
    problems = validate_state(state)
    assert not problems, problems
    return state


def pending(state: dict, prog: dict) -> dict:
    descriptor = {"trigger_id": "phx-trigger", "controller": "p1", "source_object": "phx", "controller_order": 0,
                  "effect_program_id": prog["program_id"], "optional_at_finalize": True,
                  "effect_program_hash": program_hash(prog), "trigger_kind": "triggered",
                  "source_identity": object_identity(state, "phx")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    assert scheduled.get("applied"), scheduled
    return scheduled["next_state"]


def to_resolution(timing: dict) -> dict:
    if next_procedure(timing).get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return timing


def run(state: dict, prog: dict, *, before_resolution=None, perform: bool = True) -> dict:
    registry = {prog["program_id"]: prog}
    timing = pending(state, prog)
    fin = finalize_trigger(timing, state, registry, None, perform_optional_trigger=perform, pay_trigger_cost=perform,
                           payment_context=CLOSED)
    if not fin.get("committed"):
        return {"fin": fin}
    if not perform:
        return {"fin": fin}
    paid = fin["next_effect_state"]
    board_now = copy.deepcopy(paid)
    if before_resolution is not None:
        before_resolution(board_now)
    ready = to_resolution(fin["next_timing_state"])
    chain_item = next(i for i in ready["chain"]["items"] if i["id"] == "phx-trigger")
    prog_bound, refusal = dispatch_program(registry, chain_item)
    assert refusal is None, refusal
    return {"fin": fin, "paid": paid, "done": resolve_with_program(ready, "phx-trigger", board_now, prog_bound)}


def limited_item(timing: dict) -> dict | None:
    return next((i for i in timing["chain"]["items"] if i.get("limited_play")), None)


def check_played(label: str, prog: dict, x: dict) -> None:
    state = board()
    out = run(state, prog)
    done = out.get("done") or {}
    if not done.get("committed"):
        return fail(label, f"{done.get('stage')} {done.get('reason')}")
    paid = out["paid"]["players"]["p1"]["resources"]
    if paid != {"energy": 4 - x["energy"], "power": {"fury": 2 - x["fury"]}}:
        fail(label + " X", f"the base cost X was not what was paid at finalization: {paid}")
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    item = limited_item(t1)
    record = ((e1.get("chain_items") or {}).get((item or {}).get("id")) or {}).get("limited_play") or {}
    if item is None or item.get("status") != "pending" or "phx" in e1["players"]["p1"]["zones"]["trash"] \
            or record.get("source_zone") != "trash" or record.get("cost_basis") != {"kind": "printed"}:
        return fail(label + " resolved", f"the card is not on the Chain from the trash: {record}")
    completed = complete_limited_play(t1, e1, entry_location=BASE, payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or {}
    if not completed.get("committed") or "phx" not in e2["players"]["p1"]["zones"]["base"]:
        return fail(label + " completed", f"{completed.get('reason')} {completed.get('message')}")
    after = e2["players"]["p1"]["resources"]
    if after != {"energy": 4 - x["energy"] - 3, "power": {"fury": 2 - x["fury"] - 1}}:
        fail(label + " printed cost", f"the card's own cost [3][Fury] was not paid on top of X: {after}")
    receipt = completed.get("cost_receipt") or {}
    if receipt.get("base") != {"energy": 3, "power": {"fury": 1}} \
            or receipt.get("after_base_modifications") != receipt.get("base"):
        fail(label + " no override", f"the play's base cost was modified: {receipt.get('base')} -> "
                                     f"{receipt.get('after_base_modifications')}")


def check_declined() -> None:
    state = board()
    out = run(state, PHOENIX, perform=False)
    fin = out["fin"]
    if not fin.get("committed") or (fin.get("transition") or {}).get("type") != "optional_trigger_declined":
        return fail("S3 declined", f"{fin.get('reason')} {fin.get('transition')}")
    after = fin.get("next_effect_state") or state
    if after["players"]["p1"]["resources"] != state["players"]["p1"]["resources"] or "phx" not in after["players"]["p1"]["zones"]["trash"]:
        fail("S3 declined", "declining paid something or moved the card")


def check_gone() -> None:
    def recycle(board_now: dict) -> None:
        board_now["players"]["p1"]["zones"]["trash"].remove("phx")
        board_now["players"]["p1"]["zones"]["main_deck"].append("phx")
    out = run(board(), PHOENIX, before_resolution=recycle)
    done = out.get("done") or {}
    steps = [(s.get("op"), s.get("outcome"), s.get("reason")) for s in (done.get("trace") or {}).get("effect", [])]
    if not done.get("committed") or ("limited_play", "no_op", "source_not_in_zone") not in steps or limited_item(done["next_timing_state"]):
        return fail("S4 gone", f"{done.get('reason')} {steps}")
    if done["next_effect_state"]["players"]["p1"]["resources"] != out["paid"]["players"]["p1"]["resources"]:
        fail("S4 gone", "X was refunded or something else was paid")


def check_new_object() -> None:
    def renew(board_now: dict) -> None:
        board_now["objects"]["phx"]["identity"] = "phx@9"
    out = run(board(), PHOENIX, before_resolution=renew)
    done = out.get("done") or {}
    steps = [(s.get("op"), s.get("outcome"), s.get("reason")) for s in (done.get("trace") or {}).get("effect", [])]
    if not done.get("committed") or ("limited_play", "no_op", "source_identity_changed") not in steps or limited_item(done["next_timing_state"]):
        fail("S5 new object", f"{done.get('reason')} {steps}")


def check_underpayment() -> None:
    state = board(energy=1, fury=1)   # X ([1][Fury]) is affordable, the card's [3][Fury] then is not
    out = run(state, PHOENIX)
    done = out.get("done") or {}
    if not done.get("committed"):
        return fail("S6 underpayment", f"resolution failed: {done.get('reason')}")
    completed = complete_limited_play(done["next_timing_state"], done["next_effect_state"], entry_location=BASE, payment_context=CLOSED)
    e2 = completed.get("next_effect_state") or done["next_effect_state"]
    cancelled = completed.get("cancelled") or (completed.get("committed") and "phx" in e2["players"]["p1"]["zones"]["trash"])
    if not cancelled or "phx" in e2["players"]["p1"]["zones"]["base"]:
        return fail("S6 underpayment", f"the play was not cancelled: {completed.get('committed')} {completed.get('reason')}")
    if "phx" not in e2["players"]["p1"]["zones"]["trash"]:
        fail("S6 underpayment", "the cancelled card is not back in the trash")
    if e2["players"]["p1"]["resources"] != {"energy": 0, "power": {"fury": 0}}:
        fail("S6 underpayment", f"X was refunded: {e2['players']['p1']['resources']}")


def check_forged() -> None:
    out = run(board(), PHOENIX)
    done = out.get("done") or {}
    t1, e1 = done["next_timing_state"], done["next_effect_state"]
    item = limited_item(t1)
    from play_transaction import DECLARATION_VERSION, play_card
    forged = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "forged", "actor": "p1", "card": "phx",
              "chain_item": {"id": item["id"], "object_kind": "unit", "timing": "default"},
              "cost": {"base": {"energy": 3, "power": {"fury": 1}}}, "source": {"kind": "trash"},
              "source_permission": {"granted_by": "phx"}, "cost_override": {"kind": "ignore_base_cost", "source": "phx"},
              "timing_source": "limited_play", "payment_context": CLOSED, "entry_location": BASE}
    got = play_card(t1, e1, forged)
    if got.get("committed"):
        fail("S7 forged", "a declaration that ignores the printed cost of a 'printed' play was accepted")


def check_shapes() -> None:
    base = self_play([{"kind": "power", "domain": "fury", "amount": 1}])[1]
    for label, bad in (("decision_ref", {**base, "decision_ref": "c"}), ("from hand", {**base, "self": {"from": "hand"}}),
                       ("beside a target", {**base, "target": {"decision_ref": "t", "kind": "unit", "location": "trash",
                                                                "zone_owner_relation": "own", "chosen_zone_class": "non_board"}})):
        if not validate_program(program("bad", "phx", [bad])):
            fail("S8 shapes", f"self with {label} validated")
    if validate_program(PHOENIX) or validate_program(CHOMPERS):
        fail("S8 shapes", f"the two shapes do not validate: {validate_program(PHOENIX)} {validate_program(CHOMPERS)}")


def main() -> int:
    check_played("S1 played", PHOENIX, {"energy": 1, "fury": 1})
    check_played("S2 Fury only", CHOMPERS, {"energy": 0, "fury": 1})
    check_declined()
    check_gone()
    check_new_object()
    check_underpayment()
    check_forged()
    check_shapes()
    if errors:
        print("FAILED: a triggered ability playing its own card from the trash")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'pay X to play me' from the trash - X paid at finalization, the card played from the trash paying its own "
          "cost (no override); declined, gone, a new object, underpayment (cancelled, X kept), a forged override, shapes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
