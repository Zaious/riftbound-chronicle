#!/usr/bin/env python3
"""Delayed triggers that wait for an event this turn (package 10, Noxian Guillotine and Imperial Decree).

Guillotine makes a one-shot delayed trigger bound to the unit it chose: the next time THAT unit takes damage this turn,
kill it. Imperial Decree makes one that repeats: whenever any unit takes damage this turn, kill it. Both are matched in
real play batch by batch (watchers.schedule_live), carry the damaged unit as the trigger's own "it" (Core 359.3.f.3), and
stop waiting once the turn they were made in is over (Core 317.2); a bound unit that became a new object is no longer the
one they wait for (Core 124).

  G1 bound         Guillotine's trigger waits, bound to u2's identity
  G2 another       u1 takes damage: nothing scheduled, it still waits
  G3 the target    u2 takes damage: one trigger, "it" is u2; resolving it kills u2; the delayed trigger is spent
  G4 next turn     a new turn, u2 takes damage: nothing scheduled; the trigger is dropped as expired
  G5 new object    u2 left the board and came back (a new object): nothing scheduled; dropped
  D1 repeats       Decree: u1 and u2 damaged in one batch - two triggers, one per unit; it still waits
  D2 again         later, u1 damaged again: another trigger
  D3 resolves      each trigger kills the unit it is about
  D4 next turn     expired
  L1 L2 Legion     the card's own body: without Legion the delayed trigger is made and nothing dies; with it u2 dies now
                   and no delayed trigger is made (GPT ruling 13)
  V  validation    until / repeats / about_target only on an event wait; about_target only with a bound target

    python skill/scripts/check_delayed_event_watch.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import watchers  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, object_identity, validate_program, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
KILL_IT = [{"op": "kill", "effect_id": "k", "object_id": {"object_ref": "trigger_event_object"}}]


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(pid, *effects, trigger_event=None):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "c1", "effects": [copy.deepcopy(e) for e in effects],
            **({"trigger_event": trigger_event} if trigger_event else {})}


def board():
    state = base_state()
    for oid in ("u1", "u2"):
        state["objects"][oid]["base_might"] = 6
        state["objects"][oid]["damage"] = 0
    return state


def guillotine(state):
    return {"op": "create_delayed_trigger", "effect_id": "dl",
            "target": {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit", "bound_identity": object_identity(state, "u2")},
            "delayed": {"delayed_id": "guillotine", "controller": "p1", "source_object": "c1", "target_object": "$own_target",
                        "waits_for": {"kind": "event", "kinds": ["damaged"], "scope": "any"}, "until": "end_of_turn",
                        "about_target": True, "effect_program_id": "guillotine-kill", "optional_at_finalize": False,
                        "controller_order": 0},
            "effects": KILL_IT}


DECREE = {"op": "create_delayed_trigger", "effect_id": "dl",
          "delayed": {"delayed_id": "decree", "controller": "p1", "source_object": "c1",
                      "waits_for": {"kind": "event", "kinds": ["damaged"], "scope": "any"}, "until": "end_of_turn",
                      "repeats": True, "effect_program_id": "decree-kill", "optional_at_finalize": False, "controller_order": 0},
          "effects": KILL_IT}


def damage(state, *targets, turn=None):
    """Deal 1 to each target in one batch; the watchers that batch wakes, and the state they leave."""
    done = apply_program(state, program("dmg", *[{"op": "deal_damage", "effect_id": f"d{i}", "object_id": t, "amount": 1}
                                                 for i, t in enumerate(targets)]))
    if not done.get("committed"):
        return None, None, done.get("reason") or done.get("errors")
    scheduled, after = watchers.schedule_live(done["next_state"], done.get("events") or [],
                                              turn_id=turn or done["next_state"].get("turn_id", "turn-0"), batch_label="b")
    return scheduled, after, None


def waiting(state):
    return [d["delayed_id"] for d in state.get("delayed_triggers") or []]


def main() -> int:
    s = board()
    made = apply_program(s, program("guillotine", guillotine(s)))
    if not made.get("committed") or validate_state(made["next_state"]):
        print(f"FAILED: Guillotine's trigger was not made: {made.get('errors') or validate_state(made['next_state'])}")
        return 1
    g = made["next_state"]
    entry = (g.get("delayed_triggers") or [{}])[0]
    if entry.get("target_object") != "u2" or entry.get("target_identity") != object_identity(g, "u2"):
        fail("G1 bound", entry)
    sch, after, why = damage(g, "u1")
    if why or sch or waiting(after) != ["guillotine"]:
        fail("G2 another", f"{why} {sch} {waiting(after) if after else None}")
    sch, after, why = damage(g, "u2")
    if why or len(sch) != 1 or sch[0].get("trigger_event", {}).get("object") != "u2" or waiting(after):
        fail("G3 the target", f"{why} {sch} {waiting(after) if after else None}")
    else:
        killed = apply_program(after, program("guillotine-kill", *KILL_IT, trigger_event=sch[0]["trigger_event"]))
        if not killed.get("committed") or "u2" not in killed["next_state"]["players"]["p2"]["zones"]["trash"]:
            fail("G3 the target", f"resolving it did not kill u2: {killed.get('reason') or killed.get('errors')}")
    sch, after, why = damage(g, "u2", turn="turn-next")
    if why or sch or waiting(after):
        fail("G4 next turn", f"{why} {sch} {waiting(after) if after else None}")
    moved = copy.deepcopy(g)
    moved["players"]["p2"]["zones"]["base"].remove("u2")
    moved["players"]["p2"]["zones"]["hand"].append("u2")
    renewed = copy.deepcopy(moved)
    renewed["players"]["p2"]["zones"]["hand"].remove("u2")
    renewed["players"]["p2"]["zones"]["base"].append("u2")
    renewed["objects"]["u2"]["identity"] = "u2@9"
    sch, after, why = damage(renewed, "u2")
    if why or sch or waiting(after):
        fail("G5 new object", f"{why} {sch} {waiting(after) if after else None}")
    d = apply_program(board(), program("decree", DECREE))
    if not d.get("committed"):
        fail("D1 repeats", d.get("errors") or d.get("reason"))
    else:
        decree = d["next_state"]
        sch, after, why = damage(decree, "u1", "u2")
        about = sorted(e.get("trigger_event", {}).get("object") for e in sch or [])
        if why or about != ["u1", "u2"] or waiting(after) != ["decree"]:
            fail("D1 repeats", f"{why} {about} {waiting(after) if after else None}")
        else:
            again, later, why = damage(after, "u1")
            if why or len(again) != 1 or waiting(later) != ["decree"]:
                fail("D2 again", f"{why} {again}")
            dead = after
            for entry in sch:
                ran = apply_program(dead, program("decree-kill", *KILL_IT, trigger_event=entry["trigger_event"]))
                if not ran.get("committed"):
                    fail("D3 resolves", ran.get("reason") or ran.get("errors"))
                    break
                dead = ran["next_state"]
            if "u1" not in dead["players"]["p1"]["zones"]["trash"] or "u2" not in dead["players"]["p2"]["zones"]["trash"]:
                fail("D3 resolves", "a damaged unit was not killed")
            sch, after, why = damage(decree, "u1", turn="turn-next")
            if why or sch or waiting(after):
                fail("D4 next turn", f"{why} {sch}")
    # L: the card's own body, lowered by the clause grammar - Legion (Core 812.1.c, GPT ruling 13) decides which half runs
    import clause_grammar as cg
    lowered = cg.compile_clause("Choose a unit. Kill it the next time it takes damage this turn. [Legion] — Kill it now "
                                "instead.", cg.load_grammar())
    for label, legion in (("L1 without Legion", False), ("L2 with Legion", True)):
        s = board()
        s["objects"]["c1"]["keywords"] = ["legion"]
        if legion:
            s["players"]["p1"]["cards_finalized_this_turn"] = {s.get("turn_id", "turn-0"): ["c2"]}
        effects = copy.deepcopy(lowered.get("program_effects") or [])
        for e in effects:
            e["target"] = {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit",
                           "bound_identity": object_identity(s, "u2")}
            if e["op"] == "create_delayed_trigger":
                e["delayed"].update({"controller": "p1", "source_object": "c1"})
        ran = apply_program(s, program("guillotine", *effects))
        if not ran.get("committed"):
            fail(label, ran.get("reason") or ran.get("errors"))
            continue
        dead = "u2" in ran["next_state"]["players"]["p2"]["zones"]["trash"]
        made_one = waiting(ran["next_state"]) == ["guillotine"]
        if (dead, made_one) != ((True, False) if legion else (False, True)):
            fail(label, f"killed now {dead}, delayed trigger made {made_one}")
    bad = copy.deepcopy(made["next_state"])
    bad["delayed_triggers"][0]["waits_for"] = {"kind": "turn", "moment": "end_of_turn", "turn_id": "turn-0"}
    if not validate_state(bad):
        fail("V validation", "until / about_target on a turn wait was accepted")
    bad = copy.deepcopy(made["next_state"])
    bad["delayed_triggers"][0].pop("target_object")
    bad["delayed_triggers"][0].pop("target_identity")
    if not validate_state(bad):
        fail("V validation", "about_target with no bound target was accepted")
    if validate_program(program("decree", DECREE)):
        fail("V validation", f"Decree's own program is invalid: {validate_program(program('decree', DECREE))}")
    if errors:
        print("FAILED: delayed event-watch checks")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: delayed triggers waiting for an event this turn - the bound one fires once on its unit only, the repeating "
          "one on every damaged unit, each 'it' the damaged unit; both stop at the turn's end; a new object is not "
          "waited for (G1-G5, D1-D4, L1-L2, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
