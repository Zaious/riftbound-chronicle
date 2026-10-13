#!/usr/bin/env python3
"""Additional turns, and a spell that banishes itself (package 11, Time Warp: "Take a turn after this one. Banish this.").

Core 735-738, in this engine's words: the effect gives that player one extra turn, placed right behind the turn being
played; nobody's place in the Turn Order moves; once it is over, play goes on with whatever was lined up before; two made
in a row are each placed right behind the turn being played, so the one made later is played first (738's second
example). The engine's shape: op take_additional_turn queues {player, created_by, effect_id, turn_id} at the
front of effect_state.additional_turns; turn_cycle.begin_turn takes the front one (path additional_turn) and remembers the
regular turn the queue resumes after (turn_queue_resume_after). "Banish this." (op banish_this) marks the resolving chain
item, and the resolution bridge sends the card to its owner's banishment instead of the trash.

  T1 resolved       Time Warp played from p1's hand and resolved: p1's Additional Turn queued, the card in p1's
                    banishment (a new object), not the trash
  T2 taken          after p1's turn expires, p1 begins the next turn (path additional_turn); the Turn Order unchanged
  T3 resumes        after that turn expires, p2's turn - the queue returns to the turns queued before
  T4 two of one     two Additional Turns made in p1's turn: p1, p1, then p2 (738, first example)
  T5 four players   in p1's turn p4's then p2's are made: p2, p4, then p2, p3, p4 (738, second example)
  T6 countered      Time Warp countered on the Chain: no turn queued, the card in the trash
  T7 before first   an Additional Turn for a player who has taken no turn yet: refused as unsupported by name
  T8 not resolving  "Banish this." run outside a resolving chain item: nothing banished (no_op)
  V  shape/grammar  malformed additional_turns or ops do not validate; both sentences lower to their ops

    python skill/scripts/check_additional_turn.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, hash_value, object_identity,  # noqa: E402
                       validate_program, validate_state)
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import begin_ending_step, resolve_with_program, run_expiration_step  # noqa: E402
from rules_core import finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402
from turn_cycle import begin_turn  # noqa: E402

RULESET = {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}
CLOSED = {"add_window_closed": True, "confirmed_by": "human"}
errors: list[str] = []


def fail(label: str, why) -> None:
    errors.append(f"{label}: {why}")


def program(program_id: str, effects: list[dict], controller: str = "p1", source: str | None = None) -> dict:
    return {"schema_version": PROGRAM_VERSION, "ruleset": RULESET, "program_id": program_id, "controller": controller,
            **({"source_object": source} if source else {}), "effects": effects}


WARP = program("warp-effects", [{"op": "take_additional_turn", "effect_id": "turn", "player": "p1"},
                                {"op": "banish_this", "effect_id": "banish-self"}])


def board() -> dict:
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["warp"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [],
                                "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["hand"].append("warp")
    state["players"]["p1"]["resources"] = {"energy": 3, "power": {}}
    assert not validate_state(state), validate_state(state)
    return state


def warp_on_chain(state: dict) -> tuple[dict, dict]:
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": RULESET, "play_id": "play-warp", "actor": "p1", "card": "warp",
            "effect_program_id": WARP["program_id"], "chain_item": {"id": "spell-w", "object_kind": "spell", "timing": "default"},
            "cost": {"base": {"energy": 3, "power": {}}}, "payment_context": CLOSED}
    played = play_card(fixture(), state, decl, effect_program=WARP)
    if not played.get("committed"):
        raise RuntimeError(f"Time Warp was not played: {played.get('reason_code') or played.get('reason')}")
    timing = played["next_timing_state"]
    if next_procedure(timing).get("procedure") == "finalize_oldest_pending":
        timing = finalize_oldest_pending(timing)["next_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return timing, played["next_effect_state"]


def where(state: dict, card: str) -> str | None:
    for player, data in state["players"].items():
        for zone, ids in data["zones"].items():
            if card in ids:
                return f"{player}:{zone}"
    return None


def timing_at_main(players=("p1", "p2"), turn_player="p1") -> dict:
    t = fixture(priority=None)
    t.update({"players": list(players), "turn_order": list(players), "turn_player": turn_player,
              "turns_taken": {p: 2 for p in players}, "outstanding_tasks": []})
    return t


def next_turn(timing: dict, effect: dict) -> tuple[dict | None, dict | None, dict]:
    """The current turn ended and expired, then the next turn begun; the Cleanup it makes outstanding handled."""
    ended = begin_ending_step(timing, effect)
    if not ended.get("committed"):
        return None, None, ended
    expired = run_expiration_step(ended["next_timing_state"], ended["next_effect_state"])
    if not expired.get("committed"):
        return None, None, expired
    began = begin_turn(expired["next_timing_state"], expired["next_effect_state"])
    if not began.get("committed"):
        return None, None, began
    t = copy.deepcopy(began["next_timing_state"])
    t["outstanding_tasks"] = [x for x in t["outstanding_tasks"] if x != "cleanup"]
    t["phase"] = "main"   # the Start of Turn's own procedures are check_turn_cycle's; this check reads who takes the turn
    t["turn_progress"] = {}
    return t, began["next_effect_state"], began


def sequence(timing: dict, effect: dict, n: int) -> tuple[list, list]:
    players, paths = [], []
    for _ in range(n):
        timing, effect, began = next_turn(timing, effect)
        if timing is None:
            players.append(f"refused: {began.get('reason_code')} {began.get('reason') or began.get('errors')}")
            break
        players.append(timing["turn_player"])
        paths.append(began["trace"]["path"])
    return players, paths


def queued(effect: dict, *players: str) -> dict:
    effect = copy.deepcopy(effect)
    for p in players:
        got = apply_program(effect, program(f"warp-{p}-{len(effect.get('additional_turns') or [])}",
                                            [{"op": "take_additional_turn", "effect_id": "turn", "player": p}], controller=p))
        if not got.get("committed"):
            raise RuntimeError(f"take_additional_turn for {p}: {got.get('reason') or got.get('errors')}")
        effect = got["next_state"]
    return effect


def main() -> int:
    # T1
    s = board()
    before = object_identity(s, "warp")
    timing, effect = warp_on_chain(s)
    done = resolve_with_program(timing, "spell-w", effect, WARP)
    after = done.get("next_effect_state") or {}
    if not done.get("committed"):
        fail("T1 resolved", done.get("reason") or done.get("errors"))
    else:
        if [q["player"] for q in after.get("additional_turns") or []] != ["p1"]:
            fail("T1 queued", after.get("additional_turns"))
        if where(after, "warp") != "p1:banishment":
            fail("T1 banished", f"the card is at {where(after, 'warp')}, not p1's banishment")
        if object_identity(after, "warp") == before:
            fail("T1 new object", "the banished card is the same object (Core 124)")
        if validate_state(after):
            fail("T1 state", validate_state(after)[:2])
    # T2, T3
    e = copy.deepcopy(after) if after else queued(base_state(), "p1")
    e.pop("chain_items", None)
    players, paths = sequence(timing_at_main(), e, 2)
    if players[:1] != ["p1"] or paths[:1] != ["additional_turn"]:
        fail("T2 taken", f"{players} {paths}")
    if players[1:2] != ["p2"] or paths[1:2] != ["next_turn"]:
        fail("T3 resumes", f"{players} {paths}")
    # T4
    players, _ = sequence(timing_at_main(), queued(base_state(), "p1", "p1"), 3)
    if players != ["p1", "p1", "p2"]:
        fail("T4 two of one", players)
    # T5: four players, p1's turn; p4's Time Warp resolves first, then p2's
    four = ("p1", "p2", "p3", "p4")
    e4 = base_state()
    for p in ("p3", "p4"):
        e4["players"][p] = copy.deepcopy(e4["players"]["p2"])
        e4["players"][p]["zones"] = {z: [] for z in e4["players"]["p2"]["zones"]}
    if validate_state(e4):
        fail("T5 board", validate_state(e4)[:2])
    else:
        players, _ = sequence(timing_at_main(four), queued(e4, "p4", "p2"), 5)
        if players != ["p2", "p4", "p2", "p3", "p4"]:
            fail("T5 four players", players)
    # T6: countered
    timing, effect = warp_on_chain(board())
    countered = apply_program(effect, program("counter", [{"op": "counter", "effect_id": "c", "chain_item_id": "spell-w"}], "p2"))
    if not countered.get("committed") or where(countered["next_state"], "warp") != "p1:trash" \
            or countered["next_state"].get("additional_turns"):
        fail("T6 countered", f"{countered.get('reason') or countered.get('errors')} "
                             f"{where(countered.get('next_state') or board(), 'warp')}")
    # T7: an Additional Turn before its owner's first turn
    t7 = timing_at_main()
    t7["turns_taken"] = {"p1": 1, "p2": 0}
    refused = next_turn(t7, queued(base_state(), "p2"))[2]
    if refused.get("reason_code") != "additional_turn_before_first_turn" or refused.get("unsupported") is not True:
        fail("T7 before first", f"{refused.get('reason_code')} {refused.get('committed')}")
    # T8: not resolving
    loose = apply_program(board(), program("loose", [{"op": "banish_this", "effect_id": "b"}]))
    steps = [(x.get("op"), x.get("outcome")) for x in loose.get("trace") or []]
    if not loose.get("committed") or steps != [("banish_this", "no_op")] or where(loose["next_state"], "warp") != "p1:hand":
        fail("T8 not resolving", f"{loose.get('reason') or loose.get('errors')} {steps}")
    # V
    bad = base_state()
    bad["additional_turns"] = [{"player": "p9", "created_by": "x", "effect_id": "t", "turn_id": "turn-0"}]
    if not validate_state(bad):
        fail("V shape", "an Additional Turn for an unknown player validated")
    for effects in ([{"op": "take_additional_turn", "effect_id": "t", "player": "p1", "count": 2}],
                    [{"op": "banish_this", "effect_id": "b", "object_id": "warp"}]):
        if not validate_program(program("bad", effects)):
            fail("V shape", f"a malformed op validated: {effects}")
    grammar = cg.load_grammar()
    for text, op in (("Take a turn after this one.", "take_additional_turn"), ("Banish this.", "banish_this")):
        got = cg.compile_clause(text, grammar)
        if [e.get("op") for e in got.get("program_effects") or []] != [op]:
            fail("V grammar", f"{text!r} lowered to {got.get('production_id')} {got.get('program_effects')}")
    for near in ("Take an additional turn after this one.", "Banish it."):
        got = cg.compile_clause(near, grammar)
        if got.get("production_id") in ("take_a_turn_after_this_one", "banish_this"):
            fail("V grammar", f"a near miss lowered to {got.get('production_id')}: {near}")
    if errors:
        print("FAILED: additional turns and a spell that banishes itself")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: 'Take a turn after this one' queues an Additional Turn after the current turn - the later made taken "
          "first, the Turn Order unchanged, the queue resuming after it; 'Banish this' sends the resolving spell to its "
          "owner's banishment; countered, nothing queued and the card in the trash (T1-T8, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
