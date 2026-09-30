#!/usr/bin/env python3
"""
Gate: "When you kill a stunned enemy unit" (2026-09-27, Solari Shrine) - who is responsible for a kill.

If an ability triggers when "you" do something, it triggers when a game action you are responsible for
happens (Core 411.4). A Kill instruction kills (428.5.b) and its controller performs it (411.1); a Unit
killed in a Cleanup is attributed to the spell or ability that resolved just before and dealt it damage,
and that deal's player is responsible (428.5.c, 428.5.c.1); a Combat Cleanup's kills belong to the
Combat Damage's sources and their controller (428.5.c.2). A game action performed by the game's own
procedures is nobody's (411.2). Every `died` event now carries `responsible_player` and `was_stunned`
(the unit as it was, like `was_buffed`); the watch scope `responsible` and the fact `object_was_stunned`
read them, never guessing.

Must hold, each through resolve_with_program / apply_program / the Combat and turn Cleanups:
  - the golden sentence lowers to kinds [died], scope responsible, filter {object_kind unit,
    object_controller_relation enemy, object_was_stunned}; near misses are not this production;
  - p1's Kill of a stunned enemy Unit schedules one trigger; of an unstunned enemy, of a stunned friendly
    Unit, none; p2's Kill of its own stunned Unit, none (not p1's kill);
  - p1's lethal damage to a stunned enemy Unit: the Cleanup kill is p1's (one trigger); p2's lethal damage
    to its own stunned Unit, none; a stunned enemy that dies in p1's resolution's Cleanup although p1's
    program never damaged it (a Might cut) is nobody's kill (none);
  - the Combat Cleanup: p1's attacker kills a stunned p2 defender - p1's watcher schedules, p2's does not;
  - a turn's Cleanup (Beginning Phase) kills a stunned enemy Unit: nobody's kill (none);
  - the events: a Kill's died event names its controller, a Cleanup's with no damage names None, and
    `was_stunned` follows the unit; a died event with no `responsible_player` is refused by name under
    the scope, never read as "not you";
  - validation: object_was_stunned only `true`; responsible is a scope of the catalogue.
Negative mutations: the Cleanup attribution removed (the lethal-damage case stops firing); the stun
fact ignored (the unstunned kill fires); the scope read as the event's controller (p2's own kill fires).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import watchers  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from check_watch_wiring import resolve, scheduled_from, watcher  # noqa: E402
from effect_ir import apply_program, validate_state  # noqa: E402

GOLDEN = "When you kill a stunned enemy unit, draw 1."
NEAR = ("When you kill an enemy unit, draw 1.", "When a stunned enemy unit dies, draw 1.",
        "When you kill a stunned unit, draw 1.", "When you stun an enemy unit, draw 1.",
        "When an opponent kills a stunned enemy unit, draw 1.")


def watch_of(sentence: str) -> dict:
    return copy.deepcopy(cg.compile_clause(sentence, cg.load_grammar())["passive"]["object_fields"]["event_triggers"][0]["watch"])


def stunned(state: dict, *objects: str) -> dict:
    for object_id in objects:
        got = apply_program(state, {**program(f"stun-{object_id}", {"op": "stun", "effect_id": "s", "object_id": object_id}),
                                    "controller": state["objects"][object_id]["controller"]})
        assert got.get("committed"), got.get("reason")
        state = got["next_state"]
    return state


def with_friend(state: dict) -> dict:
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("u3")
    return state


def resolution_cases(watch: dict) -> list[tuple[str, dict, int]]:
    kill = lambda o: [{"op": "kill", "effect_id": "k", "object_id": o}]  # noqa: E731
    deal = lambda o, n: [{"op": "deal_damage", "effect_id": "d", "object_id": o, "amount": n}]  # noqa: E731
    out = []
    out.append(("p1 kills a stunned enemy unit", resolve(stunned(watcher(base_state(), watch), "u2"), kill("u2")), 1))
    out.append(("p1 kills an unstunned enemy unit", resolve(watcher(base_state(), watch), kill("u2")), 0))
    out.append(("p1 kills a stunned friendly unit", resolve(stunned(with_friend(watcher(base_state(), watch)), "u3"), kill("u3")), 0))
    out.append(("p2 kills its own stunned unit", resolve(stunned(watcher(base_state(), watch), "u2"), kill("u2"), controller="p2"), 0))
    out.append(("p1's lethal damage to a stunned enemy (Cleanup, Core 428.5.c.1)",
                resolve(stunned(watcher(base_state(), watch), "u2"), deal("u2", 9)), 1))
    out.append(("p2's lethal damage to its own stunned unit",
                resolve(stunned(watcher(base_state(), watch), "u2"), deal("u2", 9), controller="p2"), 0))
    cut = stunned(watcher(base_state(), watch), "u2")
    cut["objects"]["u2"]["damage"] = 3
    out.append(("a stunned enemy dies in p1's Cleanup from a Might cut, undamaged by p1's program",
                resolve(cut, [{"op": "modify_might", "effect_id": "m", "object_id": "u2", "amount": -2, "duration": "this_turn",
                               "source": "spell-1"}]), 0))
    return out


def combat_case(watch: dict, owner: str) -> list[str]:
    """p1's attacker u1 (Might 5) kills p2's stunned defender d1 (Might 3) in the Combat Cleanup."""
    from check_combat_damage_assignment import closed_combat
    from combat import assign_combat_damage, combat_cleanup, deal_combat_damage
    t, e = closed_combat([("d1", {"stunned": True})], attacker_might=5)
    e = watcher(e, watch, owner=owner)
    assigned = assign_combat_damage(t, e)
    dealt = deal_combat_damage(assigned["next_timing_state"], assigned["next_effect_state"]) if assigned.get("committed") else assigned
    cleaned = combat_cleanup(dealt["next_timing_state"], dealt["next_effect_state"]) if dealt.get("committed") else dealt
    if not cleaned.get("committed") or "d1" not in cleaned["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        return [f"harness: the combat did not kill d1 ({cleaned.get('reason_code')} {cleaned.get('reason')})"]
    return [i["id"] for i in cleaned["next_timing_state"]["chain"]["items"] if str(i.get("id", "")).startswith("w@")]


def turn_cleanup_case(watch: dict) -> list:
    from turn_cycle import run_cleanup
    timing = fixture()
    timing.update({"outstanding_tasks": ["cleanup"], "phase": "beginning", "priority": None})
    state = stunned(watcher(base_state(), watch), "u2")
    state["mode"] = {"victory_score": 8}
    state["objects"]["u2"]["damage"] = 9
    ran = run_cleanup(timing, state)
    if not ran.get("committed") or "u2" not in ran["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        return [f"harness: the Beginning Phase Cleanup did not kill u2 ({ran.get('reason')})"]
    return [i["id"] for i in ran["next_timing_state"]["chain"]["items"] if str(i.get("id", "")).startswith("w@")]


def held(watch: dict) -> dict[str, bool]:
    out = {label: bool(result.get("committed")) and len(scheduled_from(result)) == wanted
           for label, result, wanted in resolution_cases(watch)}
    out["combat: p1's watcher"] = len(combat_case(watch, "p1")) == 1
    out["combat: p2's watcher"] = combat_case(watch, "p2") == []
    out["a Beginning Phase Cleanup kill"] = turn_cleanup_case(watch) == []
    return out


def main() -> int:
    errors: list[str] = []
    got = cg.compile_clause(GOLDEN, cg.load_grammar())
    watch = watch_of(GOLDEN) if not got.get("unsupported") else {}
    if watch != {"kinds": ["died"], "scope": "responsible",
                 "filter": {"object_kind": "unit", "object_controller_relation": "enemy", "object_was_stunned": True}}:
        errors.append(f"the golden sentence lowers to another watch: {watch} ({got.get('reason_code')})")
    for sentence in NEAR:
        other = cg.compile_clause(sentence, cg.load_grammar())
        fields = ((other.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or []
        if any((d.get("watch") or {}).get("scope") == "responsible" for d in fields):
            errors.append(f"a near miss was lowered as the kill watch: {sentence!r}")

    for label, result, wanted in resolution_cases(watch):
        if not result.get("committed") or len(scheduled_from(result)) != wanted:
            errors.append(f"{label}: scheduled {len(scheduled_from(result))}, wanted {wanted} ({result.get('reason')})")
        # every case is a real death (else a 0 proves nothing), but the kill of an unstunned or friendly unit
        elif "u2" not in result["next_effect_state"]["players"]["p2"]["zones"]["trash"] and "friendly" not in label:
            errors.append(f"{label}: harness - u2 did not die")
    mine, theirs = combat_case(watch, "p1"), combat_case(watch, "p2")
    if len(mine) != 1 or theirs != []:
        errors.append(f"the Combat Cleanup kill (Core 428.5.c.2): p1's watcher {mine}, p2's {theirs}")
    if (turn := turn_cleanup_case(watch)) != []:
        errors.append(f"a Beginning Phase Cleanup kill was someone's: {turn}")

    # the events themselves
    killed = apply_program(stunned(base_state(), "u2"), program("k", {"op": "kill", "effect_id": "k", "object_id": "u2"}))
    died = [e for e in killed.get("events") or [] if e["kind"] == "died"]
    if [(e.get("responsible_player"), e.get("was_stunned")) for e in died] != [("p1", True)]:
        errors.append(f"a Kill's died event does not name its controller and the stun: {died}")
    plain = apply_program(base_state(), program("k", {"op": "kill", "effect_id": "k", "object_id": "u2"}))
    if [e.get("was_stunned") for e in plain.get("events") or [] if e["kind"] == "died"] != [False]:
        errors.append("an unstunned unit's died event says it was stunned")
    event = {"kind": "died", "object": "u2", "controller": "p2", "event_id": "x#1"}
    try:
        watchers.watch_matches(base_state(), {"kinds": ["died"], "scope": "responsible"}, event, source_object="w1", controller="p1")
        errors.append("a died event with no responsible_player was read, not refused")
    except watchers.WatchUnsupported as exc:
        if exc.reason_code != "responsibility_not_recorded":
            errors.append(f"a died event with no responsible_player was refused as {exc.reason_code!r}")
    for bad in (False, "yes", 1):
        state = watcher(base_state(), {**watch, "filter": {**watch["filter"], "object_was_stunned": bad}})
        if bad is not True and not any("object_was_stunned" in e for e in validate_state(state)):
            errors.append(f"object_was_stunned = {bad!r} was not refused")
    if not any("scope" in e for e in validate_state(watcher(base_state(), {**watch, "scope": "killer"}))):
        errors.append("an unknown scope was accepted")

    # negative mutations
    import resolution_bridge as RB
    real_filter, real_matches = watchers._filter_holds, watchers.watch_matches

    def no_stun(state, event_filter, event, **kw):
        return real_filter(state, {k: v for k, v in event_filter.items() if k != "object_was_stunned"}, event, **kw)

    def as_controller(state, watch_, event, **kw):
        if watch_.get("scope") == "responsible":
            watch_ = {**watch_, "scope": "any"}
        return real_matches(state, watch_, event, **kw)

    mutants = {"the stun fact ignored": ("_filter_holds", no_stun), "the scope read as any killer": ("watch_matches", as_controller)}
    for label, (name, fake) in mutants.items():
        setattr(watchers, name, fake)
        try:
            broken = [k for k, ok in held(watch).items() if not ok]
        finally:
            watchers._filter_holds, watchers.watch_matches = real_filter, real_matches
        if not broken:
            errors.append(f"negative mutation not caught: {label}")
    # the Cleanup attribution removed (resolution_bridge's 428.5.c.1 step undone before the watchers read the
    # events): the lethal-damage case must stop firing
    real_schedule = watchers.schedule_live

    def schedule_without_attribution(state, events, **kw):
        return real_schedule(state, [{**e, "responsible_player": None} if e.get("kind") == "died"
                                     and "Core 428.5.c.1" in (e.get("rule_locators") or []) else e for e in events], **kw)

    watchers.schedule_live = schedule_without_attribution
    try:
        lethal = [r for label, r, _w in resolution_cases(watch) if "lethal damage to a stunned enemy" in label][0]
    finally:
        watchers.schedule_live = real_schedule
    if scheduled_from(lethal):
        errors.append("negative mutation not caught: the Cleanup attribution removed")

    if errors:
        print("FAILED: kill responsibility checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'When you kill a stunned enemy unit' lowers to a died watch, scope responsible, enemy, was stunned; p1's "
          "Kill of a stunned enemy and p1's lethal damage to one (Cleanup, 428.5.c.1) and p1's attacker's Combat Damage "
          "(428.5.c.2) schedule it; an unstunned enemy, a stunned friend, p2 killing its own, a death p1's program did "
          "not damage, a Beginning Phase Cleanup, and p2's watcher on p1's combat kill do not; died events carry "
          "responsible_player and was_stunned; a missing responsibility is refused by name; three mutations caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
