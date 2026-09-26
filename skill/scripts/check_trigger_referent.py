#!/usr/bin/env python3
"""
Regression gate (2026-09-28): a watched trigger's "it" is the object of the event that met its
condition, as it was then - and three watches that need it: "When an enemy unit attacks a
battlefield you control", "When a friendly unit attacks or defends alone", and a Battlefield's
"When a unit moves from here".

Before this, `{"object_ref": ...}` named only the program's own source (program_source); nothing
recorded which object a watched trigger saw, no event said a Unit had gained a combat
designation, and a Battlefield had no trigger for a Unit leaving it.

Must hold, each through the engine's own procedures (standard_move, run_board_cleanup,
stage_combat, open_combat, sync_designations inside resolve_with_program, finalize_trigger,
resolve_with_program):

  the referent (effect_ir.resolve_trigger_event_object; Core 359.3.f.3, 383.2.c, 124, 359.3.e.6)
    - a watched trigger's chain item records trigger_event {event_id, kind, object, identity}
      (watchers.trigger_event_of -> rules_core.schedule_triggered_items); resolution hands it to
      the program (resolution_bridge.bind_trigger_event), and `{object_ref: trigger_event_object}`
      acts on exactly that object - never the trigger's source, never another object;
    - a referent that moved but stayed on the board is still acted on (a Move is not a zone change);
      one whose controller changed too (it is not a target - nothing was chosen);
    - a referent that died, or went to its owner's hand, before the trigger resolved: that
      instruction is ignored (ignored_source_unavailable) and the rest of the ability resolves;
    - refused by name: a program run with no trigger_event (a program that is not a watched
      trigger's, or run without its chain item); an op with no adoption of the reference (kill);
      the reference beside a target; a registered template that brings its own trigger_event;
      a malformed trigger_event on a descriptor or a chain item;
  designation watchers (combat.open_combat, combat.sync_designations; Core 464.2.c.3, 383.4.e.2.b,
  383.4.f.2.b, 740.2.a, 464.2.e.1)
    - p2's Unit attacks bf1, which p1 controls: a Legend's "When an enemy unit attacks a battlefield
      you control" in p1's Legend Zone triggers once, in the Defender's group, its referent the
      attacking Unit, which ends -1 Might this turn but not below 1; the same Legend banished, p1
      attacking instead (a friendly unit attacks; the enemy unit defends) trigger nothing; a
      designation event at a Battlefield someone else controls does not meet the filter;
    - p1's lone Unit attacks: a Gear's "When a friendly unit attacks or defends alone" triggers,
      in the Attacker's group, +1 on that Unit; two p1 Units attacking together: nothing; p1's lone
      Unit defends: triggers, +1 on it; two p1 defenders: nothing; an enemy attacking alone: nothing;
    - a Unit of the attacking player that arrives mid-combat gains its designation in the
      resolution's Cleanup (464.2.c.3.a) and wakes the watch then, once;
  the Battlefield's own watch (watchers.BATTLEFIELD_WATCH_FIELDS; Core 446.1, 190.6.a, 190.6.b)
    - p1's Unit Standard Moves from bf1 (p1's) to its Base: bf1's trigger is scheduled, source bf1,
      controller p1, referent that Unit (+1 Might this turn on resolution); an effect's Move from
      bf1 triggers it too; a Move TO bf1, a Move from another Battlefield, a Recall: nothing;
    - uncontrolled, the Turn Player controls it (190.6.b); two Units leaving together trigger it
      twice, each with its own referent, ordered by its controller (383.3.d);
    - its referent killed in response: the instruction is ignored, nothing else changes;
  the grammar
    - the three wrappers lower to exactly these descriptors, and their "give it ..." instruction to
      modify_might on {object_ref: trigger_event_object} (no target); "stun it" under them is
      referent_not_bound; a wrapper that is not a referent wrapper leaves $referent unbound; near
      misses stay unparsed.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
import rules_core as RC  # noqa: E402
import watchers  # noqa: E402
from battlefield_control import run_board_cleanup  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from combat import STANDARD_MOVE_DECLARATION_VERSION, open_combat, stage_combat, standard_move  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402

REF = {"object_ref": "trigger_event_object"}
ENEMY_ATTACKS = "When an enemy unit attacks a battlefield you control, give it -1 :rb_might: this turn, to a minimum of 1 :rb_might:."
ALONE = "When a friendly unit attacks or defends alone, give it +1 :rb_might: this turn."
MOVES_FROM = "When a unit moves from here, give it +1 :rb_might: this turn."


def lowered(text):
    """(descriptor field, descriptor, program effects) the grammar makes of `text`."""
    out = CG.compile_clause(text)
    if out.get("unsupported"):
        raise AssertionError(f"{text!r} did not lower: {out.get('reason_code')} {out.get('reason')}")
    passive = out["passive"]
    fields = passive.get("object_fields") or passive.get("battlefield_fields")
    (field, rows), = fields.items()
    return field, copy.deepcopy(rows[0]), copy.deepcopy(out["program_effects"])


def program_of(program_id, source, effects, controller="p1"):
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": program_id, "controller": controller, "source_object": source,
            # "$chain_item" (the grammar's symbol for the resolving chain item) named by the program here
            "effects": [{**copy.deepcopy(e), **({"source": program_id} if e.get("source") == "$chain_item" else {})}
                        for e in effects]}


def unit(state, uid, owner, might=3, *, zone="base", battlefield=None, exhausted=False):
    state["objects"][uid] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": might,
                             "might_modifiers": [], "damage": 0, "exhausted": exhausted}
    if battlefield:
        state["battlefields"][battlefield]["objects"].append(uid)
    else:
        state["players"][owner]["zones"].setdefault(zone, []).append(uid)
    return state


def watcher_object(state, oid, kind, field, descriptor, *, zone):
    state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False,
                             field: [{**descriptor, "controller": "p1", "source_object": oid,
                                      "effect_program_id": f"{oid}-program"}]}
    state["players"]["p1"]["zones"].setdefault(zone, []).append(oid)
    return state


def board(*, bf1_controller, p1_at_bf1=(), p2_at_bf1=(), p1_base=(), p2_base=()):
    """base_state's two players with the Units asked for; bf1 held by `bf1_controller`."""
    state = base_state()
    state["turn_id"] = "turn-7"
    for uid in list(state["objects"]):
        if state["objects"][uid]["kind"] == "unit":
            for zones in (p["zones"] for p in state["players"].values()):
                if uid in zones.get("base", []):
                    zones["base"].remove(uid)
            del state["objects"][uid]
    state["battlefields"]["bf1"] = {"controller": bf1_controller, "objects": [], "contested": False, "contested_by": None}
    for uid in p1_at_bf1:
        unit(state, uid, "p1", battlefield="bf1")
    for uid in p2_at_bf1:
        unit(state, uid, "p2", might=4, battlefield="bf1")
    for uid in p1_base:
        unit(state, uid, "p1")
    for uid in p2_base:
        unit(state, uid, "p2", might=4)
    return state


def smove(state, units, destination, *, actor):
    units = [units] if isinstance(units, str) else list(units)
    timing = fixture(priority=actor)
    timing["turn_player"] = actor
    timing["turn_order"] = [actor, "p2" if actor == "p1" else "p1"]
    decl = {"schema_version": STANDARD_MOVE_DECLARATION_VERSION, "actor": actor, "units": units, "destination": destination,
            "unit_identities": {u: IR.object_identity(state, u) or f"{u}@0" for u in units},
            "cost_confirmation": {"exhaust_confirmed": True}}
    return standard_move(timing, state, decl)


def into_combat(state, units, *, actor, battlefield="bf1"):
    """`actor` Standard Moves `units` into `battlefield`; Cleanup, stage and open the Combat for real."""
    moved = smove(state, units, {"kind": "battlefield", "battlefield": battlefield}, actor=actor)
    if not moved.get("committed"):
        return None, f"move: {moved.get('reason_code')} {moved.get('reason')}"
    timing, effect = moved["next_timing_state"], moved["next_effect_state"]
    for name, step in (("cleanup", run_board_cleanup), ("stage_combat", stage_combat), ("open_combat", open_combat)):
        done = step(timing, effect)
        if not done.get("committed"):
            return None, f"{name}: {done.get('reason_code')} {done.get('reason')}"
        timing, effect = done["next_timing_state"], done["next_effect_state"]
    return (timing, effect), None


def items(timing, prefix):
    return [i for i in timing["chain"]["items"] if str(i["id"]).startswith(prefix)]


def run_trigger(timing, effect, registry, trigger_prefix, *, before_resolve=None):
    """Finalize whatever is pending (the trigger under test included), let both players pass, and
    resolve the trigger with its registered program. `before_resolve(effect) -> effect` changes the
    board between finalization and resolution (a response)."""
    for _ in range(len([i for i in timing["chain"]["items"] if i["status"] == "pending"])):
        done = finalize_trigger(timing, effect, registry, None)
        if not done.get("committed"):
            return None, f"finalize: {done.get('reason')} {done.get('message', '')}"
        timing, effect = done["next_timing_state"], done.get("next_effect_state") or effect
    if before_resolve is not None:
        effect = before_resolve(copy.deepcopy(effect))
    mine = items(timing, trigger_prefix)
    if len(mine) != 1:
        return None, f"expected one item {trigger_prefix}*, found {[i['id'] for i in timing['chain']['items']]}"
    while True:
        procedure = RC.next_procedure(timing)
        if procedure.get("procedure") == "resolve_newest_finalized":
            break
        holder = timing.get("priority")
        passed = RC.pass_priority(timing, holder) if holder else {}
        if not passed.get("next_state"):
            return None, f"priority: {procedure} {passed.get('reason_code')}"
        timing = passed["next_state"]
    if procedure.get("subject") != mine[0]["id"]:
        return None, f"the newest finalized item is {procedure.get('subject')}, not {mine[0]['id']}"
    program = registry[mine[0]["effect_program_id"]]
    done = resolve_with_program(timing, mine[0]["id"], effect, program)
    if not done.get("committed"):
        return None, f"resolve: {done.get('reason')} {done.get('reason_code')} {done.get('errors')}"
    return done, None


def might(state, uid):
    return IR.effective_might(state, uid)


def code(result):
    """The refusal's reason code, whether resolution or the effect program named it."""
    return result.get("reason_code") or (result.get("effect_result") or {}).get("reason_code")


def main() -> int:
    errors: list[str] = []

    # ---------------------------------------------------------------- the grammar ------------------
    field, enemy_desc, enemy_effects = lowered(ENEMY_ATTACKS)
    if field != "event_triggers" or enemy_desc.get("watch") != {
            "kinds": ["attacked"], "scope": "any",
            "filter": {"object_kind": "unit", "object_controller_relation": "enemy", "at_battlefield_you_control": True}}:
        errors.append(f"grammar: 'enemy unit attacks a battlefield you control' lowered to {field} {enemy_desc.get('watch')}")
    want = [{"op": "modify_might", "amount": -1, "duration": "this_turn", "minimum": 1, "object_id": REF}]
    if [{k: v for k, v in e.items() if k in ("op", "amount", "duration", "minimum", "object_id", "target")} for e in enemy_effects] != want:
        errors.append(f"grammar: 'give it -1 ... minimum of 1' under the enemy-attacks wrapper lowered to {enemy_effects}")
    field_a, alone_desc, alone_effects = lowered(ALONE)
    if field_a != "event_triggers" or alone_desc.get("watch") != {
            "kinds": ["attacked", "defended"], "scope": "any",
            "filter": {"object_kind": "unit", "object_controller_relation": "friendly", "alone": True}}:
        errors.append(f"grammar: 'attacks or defends alone' lowered to {field_a} {alone_desc.get('watch')}")
    if [e.get("object_id") for e in alone_effects] != [REF] or any("target" in e for e in alone_effects):
        errors.append(f"grammar: 'give it +1' under the alone wrapper did not bind the referent: {alone_effects}")
    field_m, move_desc, move_effects = lowered(MOVES_FROM)
    if field_m != "move_from_triggers" or set(move_desc) != {"trigger_id", "controller_order", "effect_program_id", "optional_at_finalize"}:
        errors.append(f"grammar: 'a unit moves from here' lowered to {field_m} {move_desc}")
    if [e.get("object_id") for e in move_effects] != [REF]:
        errors.append(f"grammar: 'give it +1' under the move-from wrapper did not bind the referent: {move_effects}")
    stun = CG.compile_clause("When a friendly unit attacks or defends alone, stun it.")
    if not stun.get("unsupported") or stun.get("reason_code") != "referent_not_bound":
        errors.append(f"grammar: 'stun it' under a referent wrapper was not refused (referent_not_bound): {stun.get('reason_code')}")
    other = CG.compile_clause("When a buffed friendly unit dies, give it +1 :rb_might: this turn.")
    if any(e.get("object_id") == REF for e in other.get("program_effects") or []):
        errors.append("grammar: a wrapper that is not a referent wrapper bound 'it' to the trigger's event object")
    for near in ("When an enemy unit attacks, draw 1.", "When a friendly unit attacks alone, draw 1.",
                 "When a unit moves to here, draw 1.", "When a friendly unit attacks or defends, draw 1.",
                 "When an enemy unit defends a battlefield you control, draw 1."):
        if not CG.compile_clause(near).get("unsupported"):
            errors.append(f"grammar: the near miss {near!r} parsed")

    # ------------------------------------------- "When an enemy unit attacks a battlefield you control"
    legend_registry = {"lg-program": program_of("lg-program", "lg", enemy_effects)}

    def ahri_board(*, zone="legend_zone"):
        state = board(bf1_controller="p1", p1_at_bf1=("a1",), p2_base=("e1",))
        return watcher_object(state, "lg", "legend", "event_triggers", enemy_desc, zone=zone)

    opened, why = into_combat(ahri_board(), "e1", actor="p2")
    if opened is None:
        errors.append(f"enemy attacks: could not open the combat ({why})")
    else:
        timing, effect = opened
        mine = items(timing, "on-enemy-attacks-yours@")
        if len(mine) != 1 or not str(mine[0].get("batch_id", "")).endswith(":open:defender"):
            errors.append(f"enemy attacks: expected one trigger in the Defender's group, got "
                          f"{[(i['id'], i.get('batch_id')) for i in timing['chain']['items']]}")
        elif mine[0].get("trigger_event", {}).get("object") != "e1" or mine[0]["trigger_event"].get("identity") != IR.object_identity(effect, "e1") \
                or mine[0]["trigger_event"].get("kind") != "attacked":
            errors.append(f"enemy attacks: the chain item recorded trigger_event {mine[0].get('trigger_event')}, not the attacking e1")
        else:
            before = {u: might(effect, u) for u in ("a1", "e1")}
            done, why = run_trigger(timing, effect, legend_registry, "on-enemy-attacks-yours@")
            if done is None:
                errors.append(f"enemy attacks: {why}")
            else:
                after = done["next_effect_state"]
                if might(after, "e1") != max(1, before["e1"] - 1) or might(after, "a1") != before["a1"]:
                    errors.append(f"enemy attacks: Might {before} -> e1 {might(after, 'e1')}, a1 {might(after, 'a1')}")
            # the floor: a 1-Might attacker stays at 1 (Core 477.3.b)
            weak = ahri_board()
            weak["objects"]["e1"]["base_might"] = 1
            opened_w, why_w = into_combat(weak, "e1", actor="p2")
            done_w, why_w = run_trigger(*opened_w, legend_registry, "on-enemy-attacks-yours@") if opened_w else (None, why_w)
            if done_w is None or might(done_w["next_effect_state"], "e1") != 1:
                errors.append(f"enemy attacks: a 1-Might attacker did not stay at 1 ({why_w})")
    # the same Legend banished: nothing
    banished, why = into_combat(ahri_board(zone="banishment"), "e1", actor="p2")
    if banished is None or items(banished[0], "on-enemy-attacks-yours@"):
        errors.append(f"enemy attacks: a banished Legend triggered, or the combat did not open ({why})")
    # p1 attacks instead: a friendly unit attacks, the enemy unit defends - nothing
    reverse = board(bf1_controller="p2", p2_at_bf1=("e1",), p1_base=("a1",))
    reverse = watcher_object(reverse, "lg", "legend", "event_triggers", enemy_desc, zone="legend_zone")
    rev, why = into_combat(reverse, "a1", actor="p1")
    if rev is None or items(rev[0], "on-enemy-attacks-yours@"):
        errors.append(f"enemy attacks: p1 attacking (the enemy defending) triggered it, or no combat ({why})")
    # the filter: a designation at a Battlefield the watcher's controller does not control
    probe = ahri_board()
    event = {"kind": "attacked", "object": "e1", "controller": "p2", "object_kind": "unit", "battlefield_controller": "p2",
             "identity_after": "e1@0", "alone": True}
    if watchers.watch_matches(probe, enemy_desc["watch"], event, source_object="lg", controller="p1"):
        errors.append("enemy attacks: a designation at a Battlefield p1 does not control met the filter")
    if not watchers.watch_matches(probe, enemy_desc["watch"], {**event, "battlefield_controller": "p1"}, source_object="lg", controller="p1"):
        errors.append("enemy attacks: the filter's positive control did not match")

    # --------------------------------------------- "When a friendly unit attacks or defends alone"
    gear_registry = {"gear-program": program_of("gear-program", "gear", alone_effects)}

    def with_gear(state):
        return watcher_object(state, "gear", "gear", "event_triggers", alone_desc, zone="base")

    att, why = into_combat(with_gear(board(bf1_controller="p2", p2_at_bf1=("e1",), p1_base=("a1",))), "a1", actor="p1")
    if att is None:
        errors.append(f"alone: p1's lone attack did not open a combat ({why})")
    else:
        mine = items(att[0], "on-friendly-alone@")
        if len(mine) != 1 or not str(mine[0].get("batch_id", "")).endswith(":open:attacker") \
                or mine[0].get("trigger_event", {}).get("object") != "a1":
            errors.append(f"alone: a lone attacker did not schedule one trigger in the Attacker's group naming a1: "
                          f"{[(i['id'], i.get('batch_id'), i.get('trigger_event')) for i in att[0]['chain']['items']]}")
        else:
            before = might(att[1], "a1")
            done, why = run_trigger(*att, gear_registry, "on-friendly-alone@")
            if done is None or might(done["next_effect_state"], "a1") != before + 1 \
                    or might(done["next_effect_state"], "e1") != might(att[1], "e1"):
                errors.append(f"alone: the lone attacker did not end +1 ({why})")
    two, why = into_combat(with_gear(board(bf1_controller="p2", p2_at_bf1=("e1",), p1_base=("a1", "a2"))), ["a1", "a2"], actor="p1")
    if two is None or items(two[0], "on-friendly-alone@"):
        errors.append(f"alone: two attackers together triggered it, or no combat ({why})")
    dfd, why = into_combat(with_gear(board(bf1_controller="p1", p1_at_bf1=("a1",), p2_base=("e1",))), "e1", actor="p2")
    if dfd is None:
        errors.append(f"alone: p1's lone defence did not open ({why})")
    else:
        mine = items(dfd[0], "on-friendly-alone@")
        if len(mine) != 1 or mine[0].get("trigger_event", {}).get("object") != "a1" \
                or not str(mine[0].get("batch_id", "")).endswith(":open:defender"):
            errors.append(f"alone: a lone defender did not schedule one trigger naming a1 in the Defender's group")
        else:
            before = might(dfd[1], "a1")
            done, why = run_trigger(*dfd, gear_registry, "on-friendly-alone@")
            if done is None or might(done["next_effect_state"], "a1") != before + 1:
                errors.append(f"alone: the lone defender did not end +1 ({why})")
    pair, why = into_combat(with_gear(board(bf1_controller="p1", p1_at_bf1=("a1", "a2"), p2_base=("e1",))), "e1", actor="p2")
    if pair is None or items(pair[0], "on-friendly-alone@"):
        errors.append(f"alone: two defenders triggered it, or no combat ({why})")
    enemy_alone, why = into_combat(with_gear(board(bf1_controller="p1", p1_at_bf1=("a1", "a2"), p2_base=("e1",))), "e1", actor="p2")
    if enemy_alone is None or items(enemy_alone[0], "on-friendly-alone@"):
        errors.append(f"alone: an enemy attacking alone triggered p1's watch ({why})")

    # a late arrival: a second p2 unit moved in by p2's own effect mid-combat gains the Attacker
    # designation in the resolution's Cleanup (464.2.c.3.a) and wakes the enemy-attacks watch then
    late = ahri_board()
    unit(late, "e2", "p2", might=5)
    opened, why = into_combat(late, "e1", actor="p2")
    if opened is None:
        errors.append(f"late arrival: no combat ({why})")
    else:
        timing, effect = opened
        first_done, why = run_trigger(timing, effect, legend_registry, "on-enemy-attacks-yours@")
        if first_done is None:
            errors.append(f"late arrival: the first trigger did not resolve ({why})")
        else:
            timing, effect = first_done["next_timing_state"], first_done["next_effect_state"]
            timing = {**timing, "chain": {**timing["chain"], "items": timing["chain"]["items"] + [
                item("mover", "p2", "spell", "action", "finalized")], "consecutive_passes": ["p2", "p1"]}}
            timing["priority"] = "p1"
            mover = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
                     "program_id": "mover", "controller": "p2",
                     "effects": [{"op": "move_board_object", "effect_id": "mv", "object_id": "e2",
                                  "destination": {"kind": "battlefield", "battlefield": "bf1"}}]}
            moved = resolve_with_program(timing, "mover", effect, mover)
            late_items = items(moved.get("next_timing_state") or {"chain": {"items": []}}, "on-enemy-attacks-yours@")
            if not moved.get("committed") or len(late_items) != 1 or late_items[0].get("trigger_event", {}).get("object") != "e2":
                errors.append(f"late arrival: e2's designation in the Cleanup did not wake the watch once, naming e2: "
                              f"{moved.get('reason')} {[(i['id'], i.get('trigger_event')) for i in (moved.get('next_timing_state') or {}).get('chain', {}).get('items', [])]}")

    # ---------------------------------------------------------------- "When a unit moves from here"
    bf_registry = {"bf1-program": program_of("bf1-program", "bf1", move_effects)}

    def bar(*, controller="p1", p1_at=("a1",), others=()):
        state = board(bf1_controller=controller, p1_at_bf1=p1_at)
        for uid in others:
            unit(state, uid, "p1")
        if controller is None and p1_at:
            state["battlefields"]["bf1"].update({"contested": True, "contested_by": "p1"})
        state["battlefields"]["bf1"]["move_from_triggers"] = [{**move_desc, "effect_program_id": "bf1-program"}]
        state["battlefields"]["bf2"] = {"controller": "p1", "objects": []}
        return state

    left = smove(bar(), "a1", {"kind": "base"}, actor="p1")
    mine = items(left.get("next_timing_state") or {"chain": {"items": []}}, "on-move-from@")
    if not left.get("committed") or len(mine) != 1 or mine[0].get("source_object") != "bf1" or mine[0].get("controller") != "p1" \
            or mine[0].get("trigger_event", {}).get("object") != "a1":
        errors.append(f"moves from here: a Standard Move from bf1 did not schedule bf1's trigger naming a1: "
                      f"{left.get('reason_code')} {[(i['id'], i.get('source_object'), i.get('trigger_event')) for i in (left.get('next_timing_state') or {}).get('chain', {}).get('items', [])]}")
    else:
        before = might(left["next_effect_state"], "a1")
        done, why = run_trigger(left["next_timing_state"], left["next_effect_state"], bf_registry, "on-move-from@")
        if done is None or might(done["next_effect_state"], "a1") != before + 1:
            errors.append(f"moves from here: the moved unit did not end +1 ({why})")
        # its referent killed in response: ignored, nothing else changes
        def kill_a1(state):
            loc = state["players"]["p1"]["zones"]["base"]
            loc.remove("a1")
            state["players"]["p1"]["zones"]["trash"].append("a1")
            state["objects"]["a1"]["identity"] = "a1@9"
            return state
        gone, why = run_trigger(left["next_timing_state"], left["next_effect_state"], bf_registry, "on-move-from@",
                                before_resolve=kill_a1)
        outcomes = [s.get("outcome") for s in (gone or {}).get("trace", {}).get("effect", [])]
        if gone is None or outcomes != [IR.SOURCE_UNAVAILABLE_OUTCOME]:
            errors.append(f"moves from here: a referent killed in response was not ignored ({why}, {outcomes})")
    # moved back to its Base... and an effect's Move from bf1 triggers it too (the resolution path)
    fx_timing = fixture(priority="p2", items=[item("fx", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    fx = program_of("fx", None, [{"op": "move_board_object", "effect_id": "mv", "object_id": "a1",
                                   "destination": {"kind": "base", "player": "p1"}}])
    fx.pop("source_object")
    by_effect = resolve_with_program(fx_timing, "fx", bar(), fx)
    if not by_effect.get("committed") or len(items(by_effect["next_timing_state"], "on-move-from@")) != 1:
        errors.append(f"moves from here: an effect's Move from bf1 did not trigger it ({by_effect.get('reason')})")
    # near misses: a Move TO bf1; a Move from another Battlefield; a Recall
    to_here = smove(bar(p1_at=(), others=("a2",)), "a2", {"kind": "battlefield", "battlefield": "bf1"}, actor="p1")
    if not to_here.get("committed") or items(to_here["next_timing_state"], "on-move-from@"):
        errors.append(f"moves from here: a Move TO bf1 triggered it ({to_here.get('reason_code')})")
    elsewhere = bar(p1_at=())
    unit(elsewhere, "a3", "p1", battlefield="bf2")
    from_bf2 = smove(elsewhere, "a3", {"kind": "base"}, actor="p1")
    if not from_bf2.get("committed") or items(from_bf2["next_timing_state"], "on-move-from@"):
        errors.append(f"moves from here: a Move from bf2 triggered bf1's watch ({from_bf2.get('reason_code')})")
    recall = program_of("rc", None, [{"op": "recall", "effect_id": "rc", "object_id": "a1"}])
    recall.pop("source_object")
    recalled = resolve_with_program(fixture(priority="p2", items=[item("rc", "p1", "spell", "default", "finalized")],
                                            passes=["p1", "p2"]), "rc", bar(), recall)
    if not recalled.get("committed") or items(recalled["next_timing_state"], "on-move-from@"):
        errors.append(f"moves from here: a Recall (not a Move, Core 446.1) triggered it ({recalled.get('reason')})")
    # uncontrolled: the Turn Player controls it (190.6.b) - here p2's turn, p1's reaction moves a1
    loose = bar(controller=None)
    t2 = fixture(priority="p2", items=[item("fx2", "p1", "spell", "reaction", "finalized")], passes=["p1", "p2"])
    t2.update({"turn_player": "p2", "turn_order": ["p2", "p1"]})
    fx2 = {**copy.deepcopy(fx), "program_id": "fx2"}
    uncontrolled = resolve_with_program(t2, "fx2", loose, fx2)
    got = items(uncontrolled.get("next_timing_state") or {"chain": {"items": []}}, "on-move-from@")
    if not uncontrolled.get("committed") or [i.get("controller") for i in got] != ["p2"]:
        errors.append(f"moves from here: an uncontrolled bf1's trigger is not the Turn Player's: "
                      f"{uncontrolled.get('reason')} {[(i['id'], i.get('controller')) for i in got]}")
    try:
        watchers.schedule_live(loose, [{"kind": "moved", "object": "a1", "object_kind": "unit", "identity_after": "a1@0",
                                        "location_before": {"kind": "battlefield", "battlefield": "bf1"}}],
                               turn_id="turn-7", batch_label="probe")
        errors.append("moves from here: an uncontrolled Battlefield with no Turn Player given was answered, not refused")
    except watchers.WatchUnsupported as exc:
        if exc.reason_code != "battlefield_trigger_controller_unknown":
            errors.append(f"moves from here: refused with {exc.reason_code}")
    # two Units leaving together: two triggers, each its own referent, ordered by p1 (383.3.d)
    pairs = bar(p1_at=("a1", "a2"))
    both = smove(pairs, ["a1", "a2"], {"kind": "base"}, actor="p1")
    if both.get("committed") or both.get("reason_code") != "trigger_order_required":
        errors.append(f"moves from here: two triggers of one controller at once were not left to that controller to order "
                      f"({both.get('reason_code')})")
    else:
        refs = sorted(both.get("decision_ids") or [])
        timing = fixture(priority="p1")
        timing["turn_order"] = ["p1", "p2"]
        decl = {"schema_version": STANDARD_MOVE_DECLARATION_VERSION, "actor": "p1", "units": ["a1", "a2"],
                "destination": {"kind": "base"}, "unit_identities": {u: IR.object_identity(pairs, u) or f"{u}@0" for u in ("a1", "a2")},
                "cost_confirmation": {"exhaust_confirmed": True}}
        order = {"schema_version": "engine-decisions.v1", "input_hash": both.get("input_hash"),
                 "decisions": [{"decision_id": refs[0], "stage": "resolution", "kind": "trigger_order", "controller": "p1",
                                "value": sorted(both.get("trigger_ids") or [])}]} if refs else None
        ordered = standard_move(timing, pairs, decl, order) if order else {}
        got = items(ordered.get("next_timing_state") or {"chain": {"items": []}}, "on-move-from@")
        if sorted(str((i.get("trigger_event") or {}).get("object")) for i in got) != ["a1", "a2"]:
            errors.append(f"moves from here: two units leaving together did not trigger twice, one referent each "
                          f"({ordered.get('reason_code')} {ordered.get('errors')})")

    # ------------------------------------------------------------- the referent, refused by name ------
    state = board(bf1_controller="p1", p1_at_bf1=("a1",))
    timing = fixture(priority="p2", items=[item("t1", "p1", "ability", "triggered", "finalized")], passes=["p1", "p2"])
    timing["chain"]["items"][0].update({"source_object": "bf1", "effect_program_id": "p", "optional_at_finalize": False,
                                        "trigger_kind": "triggered", "batch_sequence": 0, "batch_id": "b",
                                        "ability_kind": "standard"})
    plain = program_of("p", "bf1", move_effects)
    no_event = resolve_with_program(timing, "t1", state, plain)
    if no_event.get("committed") or code(no_event) != IR.OBJECT_REF_NO_TRIGGER_EVENT:
        errors.append(f"refused: a program run with no trigger_event was not refused by name ({code(no_event)})")
    event = {"event_id": "e#1", "kind": "moved", "object": "a1", "identity": IR.object_identity(state, "a1") or "a1@0"}
    recorded = copy.deepcopy(timing)
    recorded["chain"]["items"][0]["trigger_event"] = dict(event)
    kill_it = program_of("p", "bf1", [{"op": "kill", "effect_id": "k", "object_id": REF}])
    refused = resolve_with_program(recorded, "t1", state, kill_it)
    if refused.get("committed") or code(refused) != IR.OBJECT_REF_OP_NOT_ADOPTED:
        errors.append(f"refused: kill on the referent (no adoption) was not refused by name ({code(refused)})")
    beside = program_of("p", "bf1", [{**move_effects[0], "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}])
    refused = resolve_with_program(recorded, "t1", state, beside)
    if refused.get("committed") or code(refused) != IR.OBJECT_REF_NOT_SELF:
        errors.append(f"refused: the referent beside a target was not refused by name ({code(refused)})")
    forged = {**plain, "trigger_event": {**event, "object": "a1-other"}}
    refused = resolve_with_program(recorded, "t1", state, forged)
    if refused.get("committed") or refused.get("reason") != "effect_program_trigger_event_mismatch":
        errors.append(f"refused: a template bringing its own trigger_event was not refused ({refused.get('reason')})")
    applied = resolve_with_program(recorded, "t1", state, plain)
    if not applied.get("committed") or might(applied["next_effect_state"], "a1") != might(state, "a1") + 1:
        errors.append(f"referent: the recorded event object was not acted on ({applied.get('reason_code')})")
    # the referent moved (still on the board) and changed controller: still acted on
    shifted = copy.deepcopy(state)
    shifted["battlefields"]["bf1"]["objects"].remove("a1")
    shifted["players"]["p1"]["zones"]["base"].append("a1")
    shifted["objects"]["a1"]["controller"] = "p2"
    shifted["players"]["p1"]["zones"]["base"].remove("a1")
    shifted["players"]["p2"]["zones"]["base"].append("a1")
    moved_ok = resolve_with_program(recorded, "t1", shifted, plain)
    if not moved_ok.get("committed") or might(moved_ok["next_effect_state"], "a1") != might(shifted, "a1") + 1:
        errors.append(f"referent: a referent that moved and changed controller was not acted on ({moved_ok.get('reason_code')})")
    # returned to its owner's hand (a new object, Core 124): ignored; the next instruction still happens
    handed = copy.deepcopy(state)
    handed["battlefields"]["bf1"]["objects"].remove("a1")
    handed["players"]["p1"]["zones"]["hand"].append("a1")
    handed["objects"]["a1"]["identity"] = "a1@1"
    two_step = program_of("p", "bf1", move_effects + [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}])
    recorded2 = copy.deepcopy(recorded)
    recorded2["chain"]["items"][0]["effect_program_id"] = "p"
    gone = resolve_with_program(recorded2, "t1", handed, two_step)
    outcomes = [s.get("outcome") for s in (gone.get("trace") or {}).get("effect", [])]
    if not gone.get("committed") or outcomes != [IR.SOURCE_UNAVAILABLE_OUTCOME, "applied"]:
        errors.append(f"referent: a referent back in its owner's hand was not ignored with the rest resolving ({outcomes} {gone.get('reason_code')})")
    # a new object at the same id, back on the board (it left for the hand and was played again,
    # Core 124): not the object the trigger saw - ignored
    replayed = copy.deepcopy(state)
    replayed["objects"]["a1"]["identity"] = "a1@2"
    again = resolve_with_program(recorded2, "t1", replayed, two_step)
    outcomes = [s.get("outcome") for s in (again.get("trace") or {}).get("effect", [])]
    if not again.get("committed") or outcomes != [IR.SOURCE_UNAVAILABLE_OUTCOME, "applied"] \
            or might(again["next_effect_state"], "a1") != might(replayed, "a1"):
        errors.append(f"referent: a new object at the referent's id was acted on ({outcomes} {again.get('reason_code')})")
    # off the board with its identity token unchanged (defence in depth: every zone change to a
    # non-board zone makes a new object, but the board check does not rely on it)
    stale = copy.deepcopy(state)
    stale["battlefields"]["bf1"]["objects"].remove("a1")
    stale["players"]["p1"]["zones"]["hand"].append("a1")
    off = resolve_with_program(recorded2, "t1", stale, two_step)
    outcomes = [s.get("outcome") for s in (off.get("trace") or {}).get("effect", [])]
    if not off.get("committed") or outcomes != [IR.SOURCE_UNAVAILABLE_OUTCOME, "applied"]:
        errors.append(f"referent: a referent off the board was acted on ({outcomes} {off.get('reason_code')})")
    # malformed trigger_event on a descriptor / a chain item
    bad = RC.schedule_triggered_items(fixture(), [{"trigger_id": "x", "controller": "p1", "source_object": "bf1",
                                                   "effect_program_id": "p", "optional_at_finalize": False,
                                                   "trigger_event": {"object": "a1"}}])
    if bad.get("applied"):
        errors.append("refused: a descriptor with a malformed trigger_event was scheduled")
    broken = copy.deepcopy(recorded)
    broken["chain"]["items"][0]["trigger_event"] = {"object": "a1", "identity": 3}
    if not RC.validate_state(broken):
        errors.append("refused: a chain item with a malformed trigger_event validated")

    if errors:
        print("FAILED: the trigger's referent and the watches that need it")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("trigger referent: the event's object as it was, acted on or ignored as the rules say; enemy attacks a "
          "battlefield you control, a friendly unit attacks or defends alone, a unit moves from here - each triggered "
          "for real and resolved, their near misses empty; refusals by name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
