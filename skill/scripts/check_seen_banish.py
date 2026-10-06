#!/usr/bin/env python3
"""A card that may banish itself as its owner looks at or reveals it from the top of their deck, then be played for [A]
(package 9, Nocturne - Horrifying).

"As you look at or reveal me from the top of your deck, you may banish me. If you do, you may play me for [A]." GPT
2026-10-06 (PACKAGE9_INVENTORY section 4): the optional banish is handled as it is looked at or revealed - no ordinary
triggered Chain item; only after the banish is it played with [A] from Banishment (Core 356.1.a), the original effect
finishing first; Predict, an explicit look at the top, and a reveal of the top all count; a plain draw does not.

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
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, hash_value, object_identity, validate_program,  # noqa: E402
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
          "done (N1-N8, S)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
