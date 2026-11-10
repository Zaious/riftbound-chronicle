#!/usr/bin/env python3
"""Regression gate (set 2 package A3: Akshan - Mischievous, "You may pay [Body][Body] as an additional cost to play me. When
you play me, if you paid the additional cost, move an enemy gear to your base. You control it until I leave the board. If
it's an Equipment, attach it to me."): control bound to the source's presence.

Readings (Core 2026-10-09): "until I leave the board" is a delayed passive (359.3.e.16) - a control effect (479.2.a) that
ends when its source leaves the board, the gear's controller again whoever controls it without it (its owner here); the
Equipment attached to the source detaches where the source was (719.5, 436.4.b) and the next Cleanup recalls a gear left
in another player's base to its controller's base (149.3, 459.1); an Equipment moved to another unit meanwhile stays
attached, its control unaffected by that unit's (718.5.e-f); the source gone before its trigger resolves - no control
is gained even for a moment (359.3.e.16).

  G1 grammar      the offer lowers to two Body Power as an optional additional cost; the trigger wraps the body, which
                  lowers to move (enemy gear, to your base) -> gain_control (while_source_on_board) -> attach to the
                  source if it is an Equipment; the near misses do not parse
  O1 paid         played with the offer paid: two Body Power spent, the offer on the receipt as paid
  K1 Equipment    the trigger resolves on p2's Equipment eq in p2's base: eq is in p1's base, p1's (owner p2), attached
                  to Akshan
  K2 gear         on p2's gear gr (no Equipment tag): in p1's base, p1's, not attached
  K3 leaves       Akshan killed: eq detaches in p1's base, p2's again; the next Cleanup recalls it to p2's base
  K4 in response  Akshan killed before the trigger resolves: eq is moved but p2 keeps it, nothing is attached; the next
                  Cleanup sends it home
  K5 moved on     eq attached to p1's u1 before Akshan leaves: it stays on u1 and is p2's again (718.5.e-f)
  K6 newer        p2 takes eq back with a control effect of its own while Akshan stays; Akshan then leaves: eq stays p2's
  K7 attached     p2's Equipment eq attached to p2's u2: the trigger moves it to p1's base (off u2), p1 controls it and it
                  is attached to Akshan; u2 is otherwise unchanged (GPT's A3 review; the Vendetta FAQ's Akshan entry)
  V  validation   gain_control while_source_on_board with no control_id does not validate

    python skill/scripts/check_akshan_mischievous.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as cg  # noqa: E402
import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
from battlefield_control import run_board_cleanup  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_printed_costs import component, decisions, intent, play, state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from resolution_bridge import dispatch_program, finalize_trigger, program_hash, resolve_with_program  # noqa: E402
from rules_core import schedule_triggered_items  # noqa: E402

RULESET = {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF}
OFFER = "You may pay [rune:body][rune:body] as an additional cost to play me."
TRIGGER = ("When you play me, if you paid the additional cost, move an enemy gear to your base. You control it until I "
           "leave the board. If it's an Equipment, attach it to me.")
errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def substitute(value, mapping):
    if isinstance(value, dict):
        return {k: substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def body():
    got = cg.compile_clause(TRIGGER, cg.load_grammar())
    return got, substitute(got.get("program_effects") or [], {"$controller": "p1", "$source_object": "ak"})


def unit(owner, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def gear(owner, *tags):
    return {"owner": owner, "controller": owner, "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, **({"tags": list(tags)} if tags else {})}


def board():
    """Akshan (ak) in p1's base beside p1's u1; p2's Equipment eq and gear gr in p2's base."""
    s = base_state()
    s["objects"].update({"ak": unit("p1"), "eq": gear("p2", "Equipment"), "gr": gear("p2")})
    s["players"]["p1"]["zones"]["base"].append("ak")
    s["players"]["p2"]["zones"]["base"] += ["eq", "gr"]
    return s


def resolve(s, pick, *, before_resolving=None):
    """The play trigger scheduled from Akshan, finalized choosing `pick`, resolved. `before_resolving` changes the
    state while the trigger waits on the Chain (a response)."""
    _, effects = body()
    prog = {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "ak-play", "controller": "p1",
            "source_object": "ak", "effects": effects}
    registry = {prog["program_id"]: prog}
    descriptor = {"trigger_id": "ak", "controller": "p1", "source_object": "ak", "controller_order": 0,
                  "effect_program_id": prog["program_id"], "optional_at_finalize": False,
                  "effect_program_hash": program_hash(prog), "trigger_kind": "triggered",
                  "source_identity": IR.object_identity(s, "ak")}
    scheduled = schedule_triggered_items(fixture(), [descriptor])
    chosen = {"schema_version": "engine-decisions.v1", "input_hash": IR.hash_value(s), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
         "value": [pick], "selection_identities": {pick: IR.object_identity(s, pick)}}]}
    fin = finalize_trigger(scheduled["next_state"], s, registry, chosen)
    if not fin.get("committed"):
        return {"refused": fin.get("reason")}
    t, now = fin["next_timing_state"], fin["next_effect_state"]
    if before_resolving is not None:
        now = before_resolving(now)
    while RC.next_procedure(t).get("procedure") != "resolve_newest_finalized":
        holder = t.get("priority")
        passed = RC.pass_priority(t, holder) if holder else {}
        if not passed.get("next_state"):
            break
        t = passed["next_state"]
    item = next(i for i in t["chain"]["items"] if i["id"] == "ak")
    prog_now, _ = dispatch_program(registry, item)
    return resolve_with_program(t, "ak", now, prog_now)


def run(state, program_effects, controller="p1"):
    return IR.apply_program(state, {"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "x",
                                    "controller": controller, "effects": program_effects})


def kill(state, oid):
    got = run(state, [{"op": "kill", "effect_id": "k", "object_id": oid}], controller="p2")
    return got.get("next_state") if got.get("committed") else None


def cleanup(state):
    got = run_board_cleanup(fixture(), state, steps=("recall_remove",), within_cleanup=True)
    return got.get("next_effect_state") if got.get("committed") else None


def where(s, oid):
    loc = IR.find_location(s, oid) if s.get("players") else None
    return None if loc is None else (f"{loc[1]}:{loc[2]}" if loc[0] == "player" else loc[1])


def main() -> int:
    g = cg.load_grammar()
    # G1
    offer = cg.compile_clause(OFFER, g)
    offers = ((((offer.get("passive") or {}).get("object_fields")) or offer.get("object_fields") or {})
              .get("optional_additional_costs") or [{}])
    got, effects = body()
    ops = [e.get("op") for e in effects]
    if offers[0].get("payment") != {"kind": "power", "domain": "body", "amount": 2} \
            or got.get("production_id") != "when_you_play_me_if_you_paid_the_additional_cost" \
            or ops != ["move_board_object", "gain_control", "attach"] \
            or effects[1].get("duration") != "while_source_on_board":
        fail("G1 grammar", f"{offer.get('production_id')} {offers} {got.get('production_id')} {ops}")
    for near in ("You may pay [rune:body] as an additional cost to play me.",
                 "move an enemy gear to your base. you control it until i leave the board"):
        if cg.compile_clause(near, g).get("production_id") in (offer.get("production_id"), "move_an_enemy_gear_to_your_base_"
                                                                "you_control_it_until_i_leave_the_board_if_its_an_equipment_attach_it_to_me"):
            fail("G1 grammar", f"a near miss parsed: {near!r}")
    # O1: the offer paid
    fields = {"optional_additional_costs": [substitute(offers[0], {"$clause_id": "ak"})]}
    s = state(fields, energy=6, power={"body": 2}, printed=(4, None))
    paid = play(s, printed=(4, None), with_decisions=decisions(s, intent("self_offer:ak", True)))
    spent = (paid.get("next_effect_state") or {}).get("players", {}).get("p1", {}).get("resources", {}).get("power")
    if not paid.get("committed") or not (component(paid, "self_offer:ak") or {}).get("paid") or (spent or {}).get("body"):
        fail("O1 paid", f"{paid.get('reason_code')} {paid.get('reason')} power left {spent}")
    # K1
    k1 = resolve(board(), "eq")
    k1s = k1.get("next_effect_state") or {}
    eq = (k1s.get("objects") or {}).get("eq") or {}
    if not k1.get("committed") or where(k1s, "eq") != "p1:base" or eq.get("controller") != "p1" or eq.get("owner") != "p2" \
            or eq.get("attached_to") != "ak" or IR.validate_state(k1s):
        fail("K1 Equipment", f"{k1.get('refused') or k1.get('reason')} at {where(k1s, 'eq')} {eq} {IR.validate_state(k1s)[:1]}")
        return report()
    # K7 (GPT's A3 review; the Vendetta FAQ discusses Akshan taking an attached Shady Spectacles): p2's Equipment eq
    # attached to p2's unit u2 - the trigger moves it to p1's base, which unattaches it from u2 (an attached card moves
    # only with or off its Top-Most card, 718.5.c), controls it, and attaches it to Akshan; u2 is otherwise untouched
    worn = board()                                     # base_state's u2 is p2's unit in p2's base
    on_u2 = run(worn, [{"op": "attach", "effect_id": "a", "object_id": "eq", "to": "u2"}], controller="p2")
    if not on_u2.get("committed") or on_u2["next_state"]["objects"]["eq"].get("attached_to") != "u2":
        fail("K7 attached", f"the fixture did not attach eq to u2: {on_u2.get('reason') or on_u2.get('errors')}")
    else:
        k7 = resolve(on_u2["next_state"], "eq")
        k7s = k7.get("next_effect_state") or {}
        eq7, u27 = (k7s.get("objects") or {}).get("eq") or {}, (k7s.get("objects") or {}).get("u2") or {}
        u2_before = {k: v for k, v in on_u2["next_state"]["objects"]["u2"].items() if k != "attachments"}
        if not k7.get("committed") or eq7.get("controller") != "p1" or eq7.get("attached_to") != "ak" \
                or where(k7s, "eq") != "p1:base" or "eq" in (IR.attachments(k7s, "u2") or []) \
                or where(k7s, "u2") != "p2:base" or {k: v for k, v in u27.items() if k != "attachments"} != u2_before \
                or IR.validate_state(k7s):
            fail("K7 attached", f"{k7.get('refused') or k7.get('reason')} eq {eq7} at {where(k7s, 'eq')} "
                                f"u2 {u27} {IR.validate_state(k7s)[:1]}")
    # K2
    k2 = resolve(board(), "gr")
    k2s = k2.get("next_effect_state") or {}
    gr = (k2s.get("objects") or {}).get("gr") or {}
    if not k2.get("committed") or where(k2s, "gr") != "p1:base" or gr.get("controller") != "p1" or gr.get("attached_to"):
        fail("K2 gear", f"{k2.get('reason')} at {where(k2s, 'gr')} {gr}")
    # K3: Akshan leaves
    gone = kill(k1s, "ak")
    eq3 = (gone or {}).get("objects", {}).get("eq") or {}
    swept = cleanup(gone) if gone else None
    if gone is None or eq3.get("attached_to") or eq3.get("controller") != "p2" or where(gone, "eq") != "p1:base" \
            or eq3.get("control_effects") or IR.validate_state(gone) or swept is None or where(swept, "eq") != "p2:base":
        fail("K3 leaves", f"eq {eq3} at {where(gone or {}, 'eq')}; after the Cleanup at {where(swept or {}, 'eq')}")
    # K4: Akshan killed before the trigger resolves - no control, nothing attached
    k4 = resolve(board(), "eq", before_resolving=lambda now: kill(now, "ak"))
    k4s = k4.get("next_effect_state") or {}
    eq4 = (k4s.get("objects") or {}).get("eq") or {}
    home = cleanup(k4s) if k4.get("committed") else None
    if not k4.get("committed") or eq4.get("controller") != "p2" or eq4.get("attached_to") or eq4.get("control_effects") \
            or home is None or where(home, "eq") != "p2:base":
        fail("K4 in response", f"{k4.get('refused') or k4.get('reason')} eq {eq4} at {where(k4s, 'eq')}; after the Cleanup "
                               f"{where(home or {}, 'eq')}")
    # K5: moved on to u1 before Akshan leaves
    moved = run(k1s, [{"op": "attach", "effect_id": "a", "object_id": "eq", "to": "u1"}])
    if not moved.get("committed") or moved["next_state"]["objects"]["eq"].get("attached_to") != "u1":
        fail("K5 moved on", f"attach to u1: {moved.get('errors') or moved.get('reason')}")
    else:
        gone5 = kill(moved["next_state"], "ak")
        eq5 = (gone5 or {}).get("objects", {}).get("eq") or {}
        if gone5 is None or eq5.get("attached_to") != "u1" or eq5.get("controller") != "p2":
            fail("K5 moved on", f"eq {eq5}")
    # K6: a newer control effect stays
    back = run(k1s, [{"op": "gain_control", "effect_id": "g", "object_id": "eq", "player": "p2"}], controller="p2")
    gone6 = kill(back["next_state"], "ak") if back.get("committed") else None
    if gone6 is None or gone6["objects"]["eq"].get("controller") != "p2" or gone6["objects"]["eq"].get("control_effects") \
            != [e for e in gone6["objects"]["eq"].get("control_effects") or [] if e.get("duration") == "permanent"]:
        fail("K6 newer", f"{(gone6 or {}).get('objects', {}).get('eq')}")
    # V
    if not IR.validate_program({"schema_version": IR.PROGRAM_VERSION, "ruleset": RULESET, "program_id": "v",
                                "controller": "p1", "effects": [{"op": "gain_control", "effect_id": "g", "object_id": "eq",
                                                                 "player": "p1", "duration": "while_source_on_board"}]}):
        fail("V", "gain_control while_source_on_board with no control_id validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: Akshan - Mischievous")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: Akshan - Mischievous - two Body Power as an optional cost; its play trigger moves an enemy gear to its "
          "controller's base, controls it while Akshan stays on the board and attaches an Equipment to him; when he "
          "leaves, control reverts and the Cleanup sends the gear home; gone before it resolves, no control at all; an "
          "Equipment moved on stays where it is; a newer control effect kept; an Equipment worn by an enemy unit taken off it and attached to him (G1, O1, K1-K7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
