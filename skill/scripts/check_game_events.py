#!/usr/bin/env python3
"""Regression gate for C-54 (ADR-0014 §1): the semantic event catalogue.

Must hold:
  - the catalogue is closed over the engine: every supported operation names a
    semantic event, every named event is in the catalogue, and every catalogue
    entry is either produced by an operation or a declared structural event —
    so no kind exists that nothing can emit, and no operation can slip through
    unnamed;
  - one game action emits one *or more* causally linked events under one
    `action_id`: a Move emits `moved` with `left_location` and
    `entered_location` hanging off it, a Kill emits `died` with the card's
    departure and arrival, a token that is Recycled `ceased_to_exist` and
    never enters anywhere;
  - every event carries the identity before and after (Core 124) and the
    location before and after, taken from the real state, not from the trace's
    own wording;
  - visibility is two questions: the fact is public, the identity is private
    only while the card is hidden at both ends. A draw is private to the
    drawer, a discard out of the hand is public in the Trash, and the look /
    reveal family's own Core 424 audience wins over both;
  - `redact_event` hands a non-viewer the occurrence without the card;
  - the whole card-program corpus derives events with no coverage hole: every
    instruction that was performed emits at least one event, and every object
    whose location or identity changed is named by one;
  - negative mutations: an operation removed from the catalogue makes the
    engine refuse and not commit (`event_kind_unknown`); an engine that does
    not observe the state change reports the hole instead of a clean log; a
    generic one-event-per-operation log is rejected by the validator.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import game_events as ge  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import SUPPORTED_OPS, apply_program  # noqa: E402

PACKS = SCRIPT_DIR.parent / "data" / "card_program_packs"


def kinds(events, kind):
    return [event for event in events if event["kind"] == kind]


def run(state, *effects, program_id="p", decisions=None):
    return apply_program(state, program(program_id, *effects), decisions=decisions)


def hand_state(*cards):
    """base_state with `cards` moved into p1's hand from wherever they were."""
    state = base_state()
    for card in cards:
        for zones in (p["zones"] for p in state["players"].values()):
            for ids in zones.values():
                if card in ids:
                    ids.remove(card)
        state["players"]["p1"]["zones"]["hand"].append(card)
    return state


def corpus_coverage(errors):
    """Every program run of every pack derives a complete, valid event log."""
    import effect_ir
    import r3a1_programs as rp

    seen: set[str] = set()
    runs = {"programs": 0, "events": 0}
    real_program, real_batch = effect_ir.apply_program, effect_ir.apply_simultaneous_kill_batch

    def collect(result):
        coverage = result.get("event_coverage")
        if isinstance(coverage, list):
            errors.extend(f"corpus coverage hole: {problem}" for problem in coverage)
        events = result.get("events") or []
        runs["programs"] += 1
        runs["events"] += len(events)
        for event in events:
            seen.add(event["kind"])
        for error in ge.validate_events(events):
            errors.append(f"corpus event log invalid: {error}")
        return result

    wrapped = {"apply_program": lambda *a, **k: collect(real_program(*a, **k)),
               "apply_simultaneous_kill_batch": lambda *a, **k: collect(real_batch(*a, **k))}
    # The bridge and the pack runner imported these by name, so patching the
    # defining module alone would miss most of the corpus.
    bound = [(module, name) for module in list(sys.modules.values()) if module is not None
             for name in wrapped if getattr(module, name, None) in (real_program, real_batch)]
    for module, name in bound:
        setattr(module, name, wrapped[name])
    try:
        for pack in sorted(PACKS.glob("*/r3a1_programs.json")):
            rp.run_all(json.loads(pack.read_text(encoding="utf-8")))
    finally:
        for module, name in bound:
            setattr(module, name, real_program if name == "apply_program" else real_batch)
    if runs["programs"] < 100 or runs["events"] < 100:
        errors.append(f"the corpus barely exercised the event log: {runs}")
    return runs, seen


def main() -> int:
    errors: list[str] = []

    # --- the catalogue is closed over the engine -------------------------------------------
    missing = sorted(SUPPORTED_OPS - set(ge.OP_PRIMARY))
    if missing:
        errors.append(f"supported operations with no semantic event: {missing}")
    stray = sorted(set(ge.OP_PRIMARY) - SUPPORTED_OPS - ge.NON_PROGRAM_OPS)
    if stray:
        errors.append(f"the catalogue names operations the engine does not have: {stray}")
    unnamed = sorted(set(ge.OP_PRIMARY.values()) - set(ge.EVENT_KINDS))
    if unnamed:
        errors.append(f"operations mapped to kinds outside the catalogue: {unnamed}")
    unreachable = sorted(set(ge.EVENT_KINDS) - set(ge.OP_PRIMARY.values()) - ge.STRUCTURAL_KINDS)
    if unreachable:
        errors.append(f"catalogue kinds no operation can emit and not declared structural: {unreachable}")
    for kind, entry in ge.EVENT_KINDS.items():
        if entry["about"] not in {"object", "player", "chain"} or not entry["rules"]:
            errors.append(f"{kind} is not a well-formed catalogue entry: {entry}")

    # --- one action, several causally linked events ----------------------------------------
    moved = run(base_state(), {"op": "move_board_object", "effect_id": "m", "object_id": "u1",
                               "destination": {"kind": "battlefield", "battlefield": "bf1"}}, program_id="mv")
    if not moved.get("committed"):
        print("FAILED: semantic event checks")
        print(f"  - the Move fixture did not commit: {moved.get('reason_code')} {moved.get('reason')}")
        return 1
    events = moved["events"]
    if [e["kind"] for e in events] != ["moved", "left_location", "entered_location"]:
        errors.append(f"a Move did not emit its three semantic events: {[e['kind'] for e in events]}")
    elif len({e["action_id"] for e in events}) != 1 or events[0]["action_id"] != "mv:m":
        errors.append(f"the Move's events do not share one action_id: {[e['action_id'] for e in events]}")
    elif [e["causal_parent"] for e in events[1:]] != [events[0]["event_id"]] * 2:
        errors.append("the location events do not hang off the Move that caused them")
    elif events[1]["location_before"] != {"kind": "player_zone", "player": "p1", "zone": "base"} or \
            events[2]["location_after"] != {"kind": "battlefield", "battlefield": "bf1"}:
        errors.append(f"the Move's locations are wrong: {events[1]['location_before']} -> {events[2]['location_after']}")
    if any(e["identity_before"] != e["identity_after"] for e in events):
        errors.append("a Move between board locations changed the object's identity (Core 124)")
    if moved.get("event_coverage") != "complete":
        errors.append(f"the Move left a coverage hole: {moved.get('event_coverage')}")

    killed = run(base_state(), {"op": "kill", "effect_id": "k", "object_id": "u1"}, program_id="kl")
    events = killed["events"]
    if [e["kind"] for e in events] != ["died", "left_location", "entered_location"]:
        errors.append(f"a Kill did not emit died with the card's departure and arrival: {[e['kind'] for e in events]}")
    elif events[2]["location_after"] != {"kind": "player_zone", "player": "p1", "zone": "trash"}:
        errors.append(f"the dead card did not arrive in the Trash: {events[2]['location_after']}")
    elif events[0]["identity_before"] == events[0]["identity_after"]:
        errors.append("dying did not change the card's identity (Core 124)")

    token = run(base_state(), {"op": "play_token", "effect_id": "t", "object_id": "t1", "owner": "p1", "controller": "p1",
                               "token_kind": "unit", "base_might": 1, "destination": {"kind": "base", "player": "p1"}},
                program_id="tk")
    if [e["kind"] for e in token["events"]] != ["token_created", "entered_location"]:
        errors.append(f"a token entering the board did not emit its two events: {[e['kind'] for e in token['events']]}")
    gone = run(token["next_state"], {"op": "recycle_one", "effect_id": "r", "object_id": "t1"}, program_id="rc")
    if [e["kind"] for e in gone["events"]] != ["recycled", "left_location", "ceased_to_exist"]:
        errors.append(f"a Recycled token did not cease to exist (186.1): {[e['kind'] for e in gone['events']]}")
    elif kinds(gone["events"], "entered_location"):
        errors.append("a token that ceased to exist still entered a Location")

    # --- visibility ------------------------------------------------------------------------
    drawn = run(base_state(), {"op": "draw", "effect_id": "d", "player": "p1", "count": 1}, program_id="dw")
    first = drawn["events"][0]
    if first["kind"] != "drawn" or first["visibility"] != {"fact": "public", "identity": ["p1"]}:
        errors.append(f"a draw is not a public fact with a private card: {first.get('kind')} {first.get('visibility')}")
    if any(e["visibility"]["identity"] != ["p1"] for e in drawn["events"]):
        errors.append("a draw's location events leaked the card to everyone")

    discarded = run(hand_state("c1"), {"op": "discard", "effect_id": "d", "player": "p1", "count": 1}, program_id="dc")
    if not discarded.get("committed"):
        errors.append(f"the discard fixture did not commit: {discarded.get('reason')}")
    elif [e["kind"] for e in discarded["events"]] != ["discarded", "left_location", "entered_location"]:
        errors.append(f"a discard did not emit its three events: {[e['kind'] for e in discarded['events']]}")
    elif any(e["visibility"]["identity"] != "public" for e in discarded["events"]):
        errors.append("a card discarded out of the hand stayed private in the Trash")

    looked = run(base_state(), {"op": "look_at_top", "effect_id": "l", "player": "p1", "count": 2}, program_id="lk")
    if [e["kind"] for e in looked["events"]] != ["looked_at", "looked_at"]:
        errors.append(f"a look did not emit one event per card seen: {[e['kind'] for e in looked['events']]}")
    elif any(e["visibility"] != {"fact": "public", "identity": ["p1"]} for e in looked["events"]):
        errors.append("a look is not a public fact with a private card (Core 424.1)")
    elif any(e["location_before"] != e["location_after"] for e in looked["events"]):
        errors.append("looking at the top of the deck moved the cards")

    resourced = run(base_state(), {"op": "add_resource", "effect_id": "a", "player": "p1", "resource": "energy", "amount": 2},
                    program_id="rs")
    if [e["kind"] for e in resourced["events"]] != ["resource_added"] or resourced["events"][0]["object"] is not None:
        errors.append(f"a player-scoped action is not a player event: {resourced['events']}")
    elif resourced["events"][0]["player"] != "p1" or resourced["events"][0]["visibility"]["identity"] != "public":
        errors.append(f"the resource event names the wrong player or audience: {resourced['events'][0]}")

    # a Unit returned to hand was public on the board: the opponent saw it leave
    at_battlefield = base_state()
    at_battlefield["players"]["p1"]["zones"]["base"].remove("u1")
    at_battlefield["battlefields"]["bf1"]["objects"].append("u1")
    returned = run(at_battlefield, {"op": "return_to_hand", "effect_id": "r", "object_id": "u1"}, program_id="rh")
    if any(e["visibility"]["identity"] != "public" for e in returned["events"]):
        errors.append("a Unit returned from the board to hand was hidden from the opponent who watched it leave")

    viewer_blind = ge.redact_event(drawn["events"][0], "p2")
    if viewer_blind.get("object") is not None or viewer_blind.get("redacted") is not True:
        errors.append(f"redaction did not hide the drawn card from the opponent: {viewer_blind}")
    if viewer_blind.get("kind") != "drawn" or viewer_blind.get("player") != "p1":
        errors.append("redaction hid the fact of the draw, which is public")
    if ge.redact_event(drawn["events"][0], "p1") != dict(drawn["events"][0]):
        errors.append("redaction hid the drawn card from the player who drew it")

    # --- a prevented event did not happen; the replacement did ------------------------------
    guarded = base_state()
    guarded["replacement_effects"] = [{
        "replacement_id": "shield-u2", "controller": "p2", "source_object": "u2",
        "mode": "prevent_event", "event_op": "deal_damage", "optional": False,
        "uses_remaining": 1, "target_object_id": "u2",
    }]
    prevented = run(guarded, {"op": "deal_damage", "effect_id": "dd", "object_id": "u2", "amount": 2}, program_id="pv")
    if [e["kind"] for e in prevented["events"]] != ["replacement_applied"]:
        errors.append(f"a prevented deal did not record the replacement and nothing else: {[e['kind'] for e in prevented['events']]}")
    elif prevented["events"][0].get("prevented_kind") != "damaged" or kinds(prevented["events"], "damaged"):
        errors.append("a prevented deal still emitted a damage event (Core 205)")

    # --- the whole corpus -------------------------------------------------------------------
    runs, corpus_kinds = corpus_coverage(errors)

    # --- negative mutations -----------------------------------------------------------------
    saved = dict(ge.OP_PRIMARY)
    try:
        del ge.OP_PRIMARY["move_board_object"]
        refused = run(base_state(), {"op": "move_board_object", "effect_id": "m", "object_id": "u1",
                                     "destination": {"kind": "battlefield", "battlefield": "bf1"}}, program_id="mv")
        if refused.get("unsupported") is not True or refused.get("reason_code") != "event_kind_unknown":
            errors.append(f"an operation with no semantic event did not fail closed: {refused.get('reason_code')}")
        elif refused.get("committed") or "next_state" in refused:
            errors.append("the engine handed back a state whose events it could not name")
    finally:
        ge.OP_PRIMARY.clear()
        ge.OP_PRIMARY.update(saved)

    # The location events are read from the state, not written from the
    # trace's own words: the same entry against an unchanged state produces
    # the primary event and no departure or arrival.
    before = ge.snapshot(base_state())
    blind = ge.EventLog("blind", actor="p1")
    blind.record(before, before, dict(moved["trace"][0]))
    if kinds(blind.events, "left_location") or kinds(blind.events, "entered_location"):
        errors.append("negative mutation failed: location events were fabricated from the trace, not read from the state")
    healthy = ge.EventLog("mv", actor="p1")
    healthy.record(before, ge.snapshot(moved["next_state"]), dict(moved["trace"][0]))
    if [e["kind"] for e in healthy.events] != ["moved", "left_location", "entered_location"] or healthy.problems:
        errors.append(f"the same entry against the real after-state did not reproduce the Move: "
                      f"{[e['kind'] for e in healthy.events]} {healthy.problems}")
    # A Core 124 identity change that no event accounts for is a hole, not a
    # silent pass: it is a new object nobody was told about.
    smuggled = ge.snapshot(moved["next_state"])
    smuggled["c3"] = {**smuggled["c3"], "identity": "c3@7"}
    caught = ge.EventLog("mv", actor="p1")
    caught.record(before, smuggled, dict(moved["trace"][0]))
    if not any("c3" in problem for problem in caught.problems):
        errors.append(f"negative mutation failed: an unexplained identity change passed as complete: {caught.problems}")
    # A no-op that changed the state is the same hole seen from the other side.
    idle = ge.EventLog("mv", actor="p1")
    idle.record(before, smuggled, {**moved["trace"][0], "outcome": "no_op"})
    if idle.events or not idle.problems:
        errors.append(f"negative mutation failed: a no-op that changed the state was accepted: {idle.problems}")

    generic = [{**moved["events"][0], "kind": entry["op"], "event_id": f"generic#{index}", "causal_parent": None}
               for index, entry in enumerate(moved["trace"])]
    if not ge.validate_events(generic):
        errors.append("negative mutation failed: a generic one-event-per-operation log passed the validator")
    hidden_fact = copy.deepcopy(moved["events"][0])
    hidden_fact["visibility"]["fact"] = ["p1"]
    if not ge.validate_event(hidden_fact):
        errors.append("an event that hides its own occurrence was accepted")
    orphan = [copy.deepcopy(moved["events"][1])]
    if not ge.validate_events(orphan):
        errors.append("an event whose causal parent is not in the log was accepted")

    if apply_program(base_state(), program("mv", {"op": "move_board_object", "effect_id": "m", "object_id": "u1",
                                                  "destination": {"kind": "battlefield", "battlefield": "bf1"}})) != moved:
        errors.append("the event log is not deterministic")

    if errors:
        print("FAILED: semantic event checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"semantic event checks passed: {len(ge.EVENT_KINDS)} catalogue kinds over {len(ge.OP_PRIMARY)} operations; "
          f"corpus {runs['programs']} program runs, {runs['events']} events, {len(corpus_kinds)} kinds, no coverage hole")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
