#!/usr/bin/env python3
"""
Regression gate (2026-09-27): a Standard Move wakes watchers, "the Nth time I move" counts
the unit's Moves, and a Legend in its Legend Zone has working Conquer and end-of-turn triggers.

Before this, only a play and a chain resolution woke watchers (watchers.schedule_live); a
Standard Move scheduled a Unit's own move_triggers and nothing else, WATCH_OCCURRENCES knew
only "the first time", and battlefield_control._score_triggers / begin_ending_step read board
objects only, so a Legend's "When you conquer" / "At the end of your turn" never fired.

Must hold, each through the engine's own procedures (standard_move, resolve_with_program,
resolve_battlefield_control after a decided Combat, begin_ending_step):
  - a watch validates `occurrence: nth_each_turn` only with an integer `nth` from 1 to 20, and
    `nth` only beside that occurrence;
  - "The third time I move in a turn" (a self watch on `moved`, nth 3): three Standard Moves
    schedule one trigger, on the third, in the watch batch after the Move's own; the fourth
    schedules nothing; Moves an effect makes count with Standard Moves (Core 420.2, 446.1), and
    a Standard Move that is the third schedules it; a Recall is not a Move (446.1) and does not
    count; another friendly unit's Moves, and the opponent's unit's, do not count; a new turn
    starts a new count; a unit that left the board and came back is a new object (Core 124) and
    counts from zero;
  - "The first time I move each turn": the first Move schedules it, the second does not - even
    when the first trigger was declined at finalization (the count is of Moves, not of
    performances; unlike 383.3.e); two units with that watch moved in one Standard Move
    (Core 144.3) trigger once each, and the controller orders them (383.3.d);
  - a Unit's own move_triggers still fire exactly as before, alongside a watch;
  - a Legend in p1's Legend Zone with a controller-scoped conquer trigger ("When you conquer",
    Core 383.4.c.2.b): p1's Conquer schedules it with the Score's batch; the same Legend
    banished, the opponent's Conquer, a unit_here descriptor on the Legend, and a control change
    that is not a Score (470) schedule nothing; a board gear's controller-scoped trigger still
    fires; a Legend's controller-scoped hold trigger fires on p1's Hold (383.4.d.2.b);
  - a Legend in the turn player's Legend Zone with an end-of-turn trigger is scheduled by
    begin_ending_step (Core 317.1); on the opponent's turn, or banished, it is not;
  - the clause grammar lowers "The first time I move each turn, ...", "The third time I move in
    a turn, ..." and "When you conquer, ..." to exactly those descriptors, and near misses stay
    unparsed.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from battlefield_control import SCORING_TASK, resolve_battlefield_control, run_scoring_step  # noqa: E402
from check_control_resolution import decided_combat  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import STANDARD_MOVE_DECLARATION_VERSION, standard_move  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, object_identity, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import begin_ending_step, finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import finalize_oldest_pending  # noqa: E402
import watchers  # noqa: E402

THIRD = {"kinds": ["moved"], "scope": "self", "occurrence": "nth_each_turn", "nth": 3}
FIRST = {"kinds": ["moved"], "scope": "self", "occurrence": "first_each_turn"}
TO_BF1 = {"kind": "battlefield", "battlefield": "bf1"}
TO_BF2 = {"kind": "battlefield", "battlefield": "bf2"}
TO_BASE = {"kind": "base"}


def descriptor(trigger_id, source, controller="p1", **extra):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False, **extra}


def mover_board(watch=THIRD, *, unit="y1", trigger_id="y-watch", optional=False):
    """p1's ready Ganking unit `unit` in its Base carrying the watch (None: no mover); bf1 and bf2
    are p1's own and empty, so p1's Move there applies no Contested and opens nothing."""
    state = base_state()
    state["turn_id"] = "turn-5"
    state["battlefields"]["bf1"]["controller"] = "p1"
    state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
    if watch is not None:
        add_mover(state, unit, watch, trigger_id=trigger_id, optional=optional)
    return state


def add_mover(state, unit, watch, *, trigger_id, owner="p1", optional=False):
    watched = descriptor(trigger_id, unit, owner, watch=copy.deepcopy(watch))
    watched["optional_at_finalize"] = optional
    state["objects"][unit] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "keywords": ["ganking"],
                              "event_triggers": [watched] if watch else []}
    state["players"][owner]["zones"]["base"].append(unit)
    return state


def smove(state, units, destination, *, actor="p1"):
    units = [units] if isinstance(units, str) else list(units)
    timing = fixture()
    if actor != "p1":
        timing.update({"turn_player": actor, "priority": actor, "turn_order": [actor, "p1"], "players": [actor, "p1"]})
    decl = {"schema_version": STANDARD_MOVE_DECLARATION_VERSION, "actor": actor, "units": units, "destination": destination,
            "unit_identities": {u: object_identity(state, u) for u in units},
            "cost_confirmation": {"exhaust_confirmed": True}}
    return standard_move(timing, state, decl)


def resolve(state, effects, *, controller="p1"):
    timing = fixture(priority="p2", items=[item("spell-1", controller, "spell", "default", "finalized")], passes=["p1", "p2"])
    if controller != "p1":
        timing["turn_player"] = controller
    return resolve_with_program(timing, "spell-1", state, {**program("resolving", *effects), "controller": controller})


def ready(state, unit):
    """A spell readies the unit - what lets it pay a Standard Move's cost again. None if refused."""
    if state is None:
        return None
    done = resolve(state, [{"op": "ready", "effect_id": "rd", "object_id": unit}])
    return done["next_effect_state"] if done.get("committed") else None


def effect_move(state, unit, destination, *, controller="p1"):
    if destination.get("kind") == "base":        # an effect's Move names whose Base
        destination = {"kind": "base", "player": state["objects"][unit]["controller"]}
    return resolve(state, [{"op": "move_board_object", "effect_id": "mv", "object_id": unit, "destination": destination}],
                   controller=controller)


def mine(result, prefix="y-watch@"):
    timing = result.get("next_timing_state") or {}
    return [i for i in timing.get("chain", {}).get("items", []) if str(i.get("id", "")).startswith(prefix)]


def after(result, label, errors):
    if not result.get("committed"):
        errors.append(f"{label}: did not commit ({result.get('reason_code')}: {result.get('reason') or result.get('errors')})")
        return None
    return result["next_effect_state"]


def moves(state, plan, errors, *, unit="y1", prefix="y-watch@", actor="p1"):
    """Run a plan of ("standard"|"effect"|"recall"|"ready", destination) steps, each a Move by
    `actor` (a Standard Move on their turn, or their spell's); return the number of `prefix`
    triggers each Move scheduled, in order."""
    counts = []
    for step, destination in plan:
        if step == "ready":
            state = ready(state, unit)
            if state is None:
                errors.append(f"readying {unit} was refused")
                return counts, None
            continue
        if step == "standard":
            result = smove(state, unit, destination, actor=actor)
        elif step == "effect":
            result = effect_move(state, unit, destination, controller=actor)
        else:
            result = resolve(state, [{"op": "recall", "effect_id": "rc", "object_id": unit}])
        state = after(result, f"{step} {destination}", errors)
        if state is None:
            return counts, None
        counts.append(len(mine(result, prefix)))
    return counts, state


def main() -> int:
    errors: list[str] = []

    # --- the watch shape -------------------------------------------------------------------------
    for label, watch, valid in (("nth 3", THIRD, True), ("first", FIRST, True),
                                ("nth missing", {**THIRD, "nth": None}, False),
                                ("nth 0", {**THIRD, "nth": 0}, False), ("nth true", {**THIRD, "nth": True}, False),
                                ("nth 21", {**THIRD, "nth": 21}, False),
                                ("nth beside first_each_turn", {**FIRST, "nth": 1}, False),
                                ("nth with no occurrence", {"kinds": ["moved"], "scope": "self", "nth": 3}, False)):
        watch = {k: v for k, v in watch.items() if v is not None}
        found = validate_state(mover_board(watch))
        if bool(found) == valid:
            errors.append(f"watch '{label}' validated {not found}, wanted {valid}: {found[:1]}")

    # --- "the third time I move in a turn": Standard Moves ------------------------------------------
    board = mover_board()
    plan = [("standard", TO_BF1), ("ready", None), ("standard", TO_BF2), ("ready", None), ("standard", TO_BASE),
            ("ready", None), ("standard", TO_BF1)]
    counts, _end = moves(board, plan, errors)
    if counts != [0, 0, 1, 0]:
        errors.append(f"four Standard Moves scheduled {counts} third-move triggers, wanted [0, 0, 1, 0]")
    _counts, two = moves(mover_board(), plan[:4], errors)
    third = smove(ready(two, "y1"), "y1", TO_BASE) if two is not None else {}
    items = mine(third)
    if len(items) != 1 or items[0].get("batch_id") != "watch:standard-move:p1" or items[0].get("status") != "pending" \
            or items[0].get("source_identity") != "y1@0" or items[0].get("trigger_kind") != "triggered":
        errors.append(f"the third Standard Move's trigger is not one pending item in the Move's watch batch: {items}")
    if "Core 420.2.b" not in (third.get("rule_locators") or []):
        errors.append("a Standard Move that woke a watcher did not cite Core 420.2.b")

    # an effect's Moves count with Standard Moves; a Standard Move that is the third schedules it
    counts, _ = moves(mover_board(), [("effect", TO_BF1), ("effect", TO_BF2), ("standard", TO_BASE)], errors)
    if counts != [0, 0, 1]:
        errors.append(f"two effect Moves then a Standard Move scheduled {counts}, wanted [0, 0, 1]")
    counts, _ = moves(mover_board(), [("standard", TO_BF1), ("effect", TO_BF2), ("effect", TO_BASE)], errors)
    if counts != [0, 0, 1]:
        errors.append(f"a Standard Move then two effect Moves scheduled {counts}, wanted [0, 0, 1] (the resolution path)")
    # a Recall is not a Move (Core 446.1): Move, Move, Recall schedules nothing; the next Move does
    counts, _ = moves(mover_board(), [("standard", TO_BF1), ("ready", None), ("standard", TO_BF2), ("recall", None),
                                      ("ready", None), ("standard", TO_BF1)], errors)
    if counts != [0, 0, 0, 1]:
        errors.append(f"Move, Move, Recall, Move scheduled {counts}, wanted [0, 0, 0, 1] (a Recall is no Move)")

    # another friendly unit's Moves, and an opponent's unit's, are not "I move"
    other = mover_board()
    add_mover(other, "f1", None, trigger_id="unused")
    counts, _ = moves(other, [("standard", TO_BF1), ("ready", None), ("standard", TO_BF2), ("ready", None),
                              ("standard", TO_BASE)], errors, unit="f1")
    if counts != [0, 0, 0]:
        errors.append(f"another friendly unit's three Moves scheduled {counts} of y1's third-move trigger")
    theirs = mover_board()
    add_mover(theirs, "e1", None, trigger_id="unused", owner="p2")
    counts, _ = moves(theirs, [("effect", TO_BF1), ("effect", TO_BF2), ("effect", TO_BASE)], errors, unit="e1", actor="p2")
    if counts != [0, 0, 0]:
        errors.append(f"the opponent's unit's three Moves scheduled {counts} of p1's third-move trigger")
    # the same watch on the opponent's own unit: its third Move schedules the opponent's trigger
    mirrored = mover_board(None)
    add_mover(mirrored, "e1", THIRD, trigger_id="e-watch", owner="p2")
    counts, _ = moves(mirrored, [("effect", TO_BF1), ("effect", TO_BF2), ("effect", TO_BASE)], errors, unit="e1",
                      actor="p2", prefix="e-watch@")
    if counts != [0, 0, 1]:
        errors.append(f"the opponent's own third-move watch scheduled {counts}, wanted [0, 0, 1] (the control)")

    # a new turn starts a new count: two Moves in turn-5, one in turn-6
    counts, two = moves(mover_board(), [("standard", TO_BF1), ("ready", None), ("standard", TO_BF2)], errors)
    if two is not None and ready(two, "y1") is not None:
        next_turn = ready(two, "y1")
        next_turn["turn_id"] = "turn-6"
        counts, _ = moves(next_turn, [("standard", TO_BASE)], errors)
        if counts != [0]:
            errors.append(f"a Move on a new turn after two last turn scheduled {counts}; the count is per turn")
        same_turn = ready(two, "y1")
        counts, _ = moves(same_turn, [("standard", TO_BASE)], errors)
        if counts != [1]:
            errors.append(f"the control for the new-turn case (same turn) scheduled {counts}, wanted [1]")

    # a unit that left the board and came back is a new object (Core 124): its count starts again
    _counts, two = moves(mover_board(), [("effect", TO_BF1), ("effect", TO_BF2)], errors)
    if two is not None:
        back = after(resolve(two, [{"op": "return_to_hand", "effect_id": "rh", "object_id": "y1"}]), "return to hand", errors)
        if back is not None:
            back["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
            decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                    "play_id": "replay-y1", "actor": "p1", "card": "y1",
                    "chain_item": {"id": "unit-9", "object_kind": "unit", "timing": "default"},
                    "cost": {"base": {"energy": 2, "power": {}}}, "entry_location": {"kind": "base"},
                    "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
            played = play_card(fixture(), back, decl)
            entered = resolve_with_program(fixture(priority="p2", items=[item("unit-9", "p1", "unit", "default", "finalized")],
                                                   passes=["p1", "p2"]), "unit-9", played.get("next_effect_state") or back, None) \
                if played.get("committed") else played
            fresh = after(entered, "replay y1", errors)
            if fresh is not None:
                fresh["objects"]["y1"]["exhausted"] = False     # the card entered exhausted; readiness is not what is tested
                counts, _ = moves(fresh, [("effect", TO_BF1)], errors)
                if object_identity(fresh, "y1") == "y1@0" or counts != [0]:
                    errors.append(f"a unit back on the board as a new object ({object_identity(fresh, 'y1')}) "
                                  f"scheduled {counts} on its first Move; the old object's count carried over")

    # --- "the first time I move each turn" -----------------------------------------------------------
    counts, _ = moves(mover_board(FIRST), [("standard", TO_BF1), ("ready", None), ("standard", TO_BF2),
                                           ("effect", TO_BASE)], errors)
    if counts != [1, 0, 0]:
        errors.append(f"the first-move watch scheduled {counts}, wanted [1, 0, 0]")
    # declined at finalization: still the first Move of the turn, so the second Move schedules nothing
    first = smove(mover_board(FIRST, optional=True), "y1", TO_BF1)
    if len(mine(first)) == 1:
        registry = {"y-watch-effects": {**program("y-watch-effects", {"op": "draw", "effect_id": "dr", "player": "p1",
                                                                     "count": 1}), "source_object": "y1"}}
        declined = finalize_trigger(first["next_timing_state"], first["next_effect_state"], registry, None,
                                    perform_optional_trigger=False)
        if not declined.get("committed") or declined["next_timing_state"]["chain"]["items"]:
            errors.append(f"declining the optional first-move trigger did not remove it: {declined.get('reason')}")
        else:
            readied = ready(declined.get("next_effect_state") or first["next_effect_state"], "y1")
            again = smove(readied, "y1", TO_BF2) if readied is not None else {}
            if not again.get("committed") or mine(again):
                errors.append("a declined first-move trigger triggered again on the second Move (the count is of Moves)")
    else:
        errors.append(f"the optional first-move watch did not schedule on the first Move: {mine(first)}")
    # two units with the watch in one Standard Move (Core 144.3): once each, ordered by their controller
    pair = mover_board(FIRST)
    add_mover(pair, "y2", FIRST, trigger_id="y2-watch")
    together = smove(pair, ["y1", "y2"], TO_BF1)
    if together.get("committed") or together.get("reason_code") != "trigger_order_required" \
            or sorted(t.split("@")[0] for t in together.get("trigger_ids") or []) != ["y-watch", "y2-watch"]:
        errors.append(f"two first-move watches on one Standard Move did not ask p1 to order two triggers: "
                      f"{together.get('reason_code')} {together.get('trigger_ids')}")

    # a Unit's own move_triggers ("When I move") still fire exactly as before, beside a watch
    both = mover_board()
    both["objects"]["y1"]["move_triggers"] = [descriptor("y-on-move", "y1")]
    moved = smove(both, "y1", TO_BF1)
    ids = [i["id"] for i in (moved.get("next_timing_state") or {}).get("chain", {}).get("items", [])]
    if ids != ["y-on-move"]:
        errors.append(f"a first Move of a unit with 'When I move' and a third-move watch scheduled {ids}")

    # --- a Legend in its Legend Zone: "When you conquer" ----------------------------------------------
    def with_legend(field, scope, zone="legend_zone"):
        def extra(e):
            e["objects"]["lg"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                                  "damage": 0, "exhausted": True, "champion_legend": True,
                                  field: [descriptor("lg-trigger", "lg", scope=scope)]}
            e["players"]["p1"]["zones"].setdefault(zone, []).append("lg")
        return extra

    def conquer_ids(extra):
        t, e = decided_combat(extra=extra)
        done = resolve_battlefield_control(t, e)
        if not done.get("committed"):
            return None, done
        return [(i["id"], i.get("batch_id")) for i in done["next_timing_state"]["chain"]["items"]], done

    got, done = conquer_ids(with_legend("conquer_triggers", "controller"))
    if got is None or [g for g in got if g[0] == "lg-trigger"] != [("lg-trigger", f"score:bf1:{done['next_effect_state'].get('turn_id', 'turn-0')}:conquer")]:
        errors.append(f"p1's Conquer did not schedule the Legend's 'When you conquer' with the Score's batch: {got}")
    for label, extra in (("the Legend banished", with_legend("conquer_triggers", "controller", zone="banishment")),
                         ("a unit_here descriptor on the Legend", with_legend("conquer_triggers", "unit_here")),
                         ("the Legend's hold_triggers", with_legend("hold_triggers", "controller"))):
        got, done = conquer_ids(extra)
        if got is None or any(g[0] == "lg-trigger" for g in got):
            errors.append(f"{label}: a Conquer scheduled {got} ({(done or {}).get('reason')})")

    # the opponent Conquers: p1's Legend references p1, not the Conquering player
    def p2_legend(e):
        with_legend("conquer_triggers", "controller")(e)
        for key in ("owner", "controller"):
            e["objects"]["lg"][key] = "p2"
        e["objects"]["lg"]["conquer_triggers"][0]["controller"] = "p2"
        e["players"]["p1"]["zones"]["legend_zone"].remove("lg")
        e["players"]["p2"]["zones"].setdefault("legend_zone", []).append("lg")
    got, done = conquer_ids(p2_legend)
    if got is None or any(g[0] == "lg-trigger" for g in got):
        errors.append(f"p1's Conquer scheduled p2's Legend's 'When you conquer': {got} ({(done or {}).get('reason')})")

    # a control change that is not a Score (bf1 already scored this turn, Core 470): nothing
    def scored_already(e):
        with_legend("conquer_triggers", "controller")(e)
        e["players"]["p1"]["scored_this_turn"] = {e.get("turn_id", "turn-0"): ["bf1"]}
    got, done = conquer_ids(scored_already)
    if got is None or got:
        errors.append(f"a control change that was not a Score scheduled {got} ({(done or {}).get('reason')})")

    # unchanged: a board gear's controller-scoped trigger fires
    def gear(e):
        e["objects"]["g1"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                              "damage": 0, "exhausted": False, "conquer_triggers": [descriptor("g1-trigger", "g1", scope="controller")]}
        e["players"]["p1"]["zones"]["base"].append("g1")
    got, _done = conquer_ids(gear)
    if got is None or [g[0] for g in got] != ["g1-trigger"]:
        errors.append(f"a board gear's controller-scoped conquer trigger no longer fires: {got}")

    # a Legend's "When you hold" (Core 383.4.d.2.b) fires on p1's Hold from the Legend Zone
    hold = base_state()
    hold["mode"] = {"victory_score": 8}
    hold["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"], "contested": False, "contested_by": None}
    hold["players"]["p1"]["zones"]["base"].remove("u1")
    with_legend("hold_triggers", "controller")(hold)
    held = run_scoring_step({**fixture(tasks=[SCORING_TASK]), "phase": "beginning", "priority": None}, hold)
    ids = [i["id"] for i in (held.get("next_timing_state") or {}).get("chain", {}).get("items", [])]
    if not held.get("committed") or ids != ["lg-trigger"]:
        errors.append(f"p1's Hold did not schedule the Legend's controller-scoped hold trigger: {held.get('reason')} {ids}")

    # --- a Legend in its Legend Zone: "At the end of your turn" -------------------------------------
    def eot_board(zone="legend_zone", owner="p1"):
        state = base_state()
        state["turn_id"] = "turn-7"
        state["objects"]["lg"] = {"owner": owner, "controller": owner, "kind": "legend", "base_might": 0, "might_modifiers": [],
                                  "damage": 0, "exhausted": False, "champion_legend": True,
                                  "end_of_turn_triggers": [descriptor("lg-eot", "lg", owner)]}
        state["players"][owner]["zones"].setdefault(zone, []).append("lg")
        return state

    began = begin_ending_step(fixture(), eot_board())
    items = (began.get("next_timing_state") or {}).get("chain", {}).get("items", [])
    if not began.get("committed") or [(i["id"], i.get("batch_id")) for i in items] != [("lg-eot", "ending:turn-7")]:
        errors.append(f"begin_ending_step did not schedule the turn player's Legend's end-of-turn trigger: "
                      f"{began.get('reason')} {[i.get('id') for i in items]}")
    for label, board in (("the Legend banished", eot_board("banishment")), ("the opponent's Legend", eot_board(owner="p2"))):
        other = begin_ending_step(fixture(), board)
        if not other.get("committed") or other["next_timing_state"]["chain"]["items"]:
            errors.append(f"{label}: begin_ending_step scheduled {other.get('reason') or other['next_timing_state']['chain']['items']}")
    theirs_turn = {**fixture(), "turn_player": "p2", "priority": "p2", "turn_order": ["p2", "p1"], "players": ["p2", "p1"]}
    other = begin_ending_step(theirs_turn, eot_board())
    if not other.get("committed") or other["next_timing_state"]["chain"]["items"]:
        errors.append(f"p1's Legend's 'At the end of your turn' was scheduled on p2's turn: {other.get('reason')}")

    # --- the clause grammar ----------------------------------------------------------------------------
    grammar = CG.load_grammar()
    for text, field, extra in (("The first time I move each turn, draw 1.", "event_triggers", {"watch": FIRST}),
                               ("The third time I move in a turn, draw 1.", "event_triggers", {"watch": THIRD}),
                               ("When you conquer, draw 1.", "conquer_triggers", {"scope": "controller"})):
        got = CG.compile_clause(text, grammar)
        fields = ((got.get("passive") or {}).get("object_fields") or {})
        built = (fields.get(field) or [{}])[0]
        if got.get("unsupported") or set(fields) != {field} or any(built.get(k) != v for k, v in extra.items()) \
                or [e.get("op") for e in got.get("program_effects") or []] != ["draw"]:
            errors.append(f"{text!r} did not lower to {field} {extra}: {got.get('reason_code')} {fields}")
    for near in ("The second time I move in a turn, draw 1.", "The third time a unit moves in a turn, draw 1.",
                 "When an opponent conquers, draw 1.", "The first time I move each combat, draw 1."):
        got = CG.compile_clause(near, grammar)
        if not got.get("unsupported"):
            errors.append(f"the near miss {near!r} parsed as {got.get('production_id')}")
    nth_of = getattr(watchers, "occurrence_nth", None)
    if nth_of is None or nth_of(FIRST) != 1 or nth_of(THIRD) != 3 or nth_of({"kinds": ["moved"], "scope": "self"}) is not None:
        errors.append("watchers.occurrence_nth does not read first = 1, nth = 3, none = None")

    if errors:
        print("FAILED: move-count and Legend Zone trigger checks")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: a Standard Move wakes watchers like a resolution does; 'the third time I move in a turn' triggers once on "
          "the unit's third Move of the turn, Standard or effect, never on a Recall, another unit's Move, the fourth, a new "
          "turn's first or a new object's; 'the first time I move each turn' counts Moves, not performances; a Legend in "
          "its Legend Zone has working 'When you conquer', 'When you hold' and 'At the end of your turn' triggers, and not "
          "when banished, on the opponent's Score or turn, or for a control change that is not a Score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
