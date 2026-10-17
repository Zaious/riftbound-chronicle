#!/usr/bin/env python3
"""One transition of a game of the closed environment (C2, package 14): a player's discretionary action, or the
procedure the timing kernel says is due - and the Cleanup the transition makes outstanding.

The engine's procedures are atomic and each is called on its own (engine_check runs one at a time). A game is their
sequence, and two things only a sequence has are kept here:

  dispatch      rules_core.next_procedure names what is due; `run_procedure` calls the engine's own procedure for it, with
                the program the chain item recorded (closed_environment.instantiate_program from its effect_program_id)
                and the choices made so far. A Unit, Gear or [Add] ability is resolved as soon as it is Finalized (Core
                337.2), in the same transition (as resolution_bridge.complete_limited_play does for a limited play).
  the Cleanup   Core 319: a Cleanup is made an Outstanding Task after each of 319.1-319.8. The procedures run only the
                lethal part of it themselves (effect_ir.perform_lethal_cleanup) and turn_cycle makes the transition
                Cleanup outstanding (319.2); every other qualifying transition is read here, from the states before and
                after (`cleanup_clauses`), and the Cleanup task appended - so a Move to a Battlefield stages its Showdown
                in the next Cleanup (323.7), not at the next turn. A Cleanup's own follow-ups are its own (322:
                turn_cycle.run_cleanup iterates until nothing changes).

A transition that needs a choice returns the request the procedure made (`request`), nothing changed; the caller
supplies `decisions` (engine-decisions.v1 entries) and `settings` (the choices a procedure takes as arguments:
SETTINGS) and calls again. Which choices are legal is decision_space's question; this module only runs them.

    run_procedure(timing, effect, catalogue, decisions=(), settings=None) -> step
    run_action(timing, effect, catalogue, action) -> step
    step = {kind, label, committed, next_timing_state, next_effect_state, cleanup: [clauses], request, result}
"""
from __future__ import annotations

import copy
import json
from typing import Any

import battlefield_control as BC
import closed_environment as CE
import combat as CB
import effect_ir as IR
import play_transaction as PT
import resolution_bridge as RB
import rules_core as RC
import turn_cycle as TC
from effect_ir import find_location, hash_value, zone_class

LOOP_VERSION = "game-loop-step.v1"
DECISIONS_VERSION = "engine-decisions.v1"
# The Add window, closed: an [Add] is an activate_ability action of its own (package 13, GPT ruling 6); a procedure
# that pays a cost pays from the pool
PAYMENT_CONTEXT = {"add_window_closed": True, "confirmed_by": "game_loop"}
# the choices a procedure takes as arguments rather than as engine decisions, and the procedure that asks each
SETTINGS = {"perform_optional_trigger": "resolution_bridge.finalize_trigger (Core 383.3.a)",
            "pay_trigger_cost": "resolution_bridge.finalize_trigger (Core 403.1.b.1, 404)",
            "entry_location": "resolution_bridge.finalize_limited_play (Core 355.2)"}
# rules_core.next_procedure's procedures and what runs each (DISCRETIONARY: a player acts - run_action)
DISCRETIONARY = {"execute_or_pass_priority", "showdown_focus_window", "neutral_turn_window"}
PROCEDURES = {
    "game_over": None,
    "handle_outstanding_tasks": "turn_cycle.run_cleanup (cleanup) / battlefield_control.run_scoring_step (scoring_step)",
    "finalize_oldest_pending": "resolution_bridge.finalize_trigger / complete_limited_play / rules_core.finalize_oldest_pending",
    "resolve_newest_finalized": "resolution_bridge.resolve_with_program",
    "begin_turn_pending": "turn_cycle.begin_turn",
    "turn_start_step_pending": "turn_cycle: awaken, beginning, channel, draw, main",
    "open_showdown_pending": "battlefield_control.open_showdown",
    "control_resolution_pending": "battlefield_control.resolve_battlefield_control",
    "open_combat_pending": "combat.open_combat",
    "combat_step_pending": "combat: assign, deal, cleanup, result; battlefield_control.resolve_battlefield_control; close",
    "ending_step": "resolution_bridge.run_expiration_step, then turn_cycle.begin_turn (Core 317.2, 315)",
}
COMBAT_STEPS = {"showdown_closed": ("assign", lambda t, e, d: CB.assign_combat_damage(t, e, d)),
                "damage_assigned": ("deal", lambda t, e, d: CB.deal_combat_damage(t, e)),
                "damage_dealt": ("cleanup", lambda t, e, d: CB.combat_cleanup(t, e, d)),
                "cleanup_done": ("result", lambda t, e, d: CB.determine_combat_result(t, e)),
                "result_determined": ("control", lambda t, e, d: BC.resolve_battlefield_control(t, e, d)),
                "control_resolved": ("close", lambda t, e, d: CB.close_combat(t, e))}
TURN_STEPS = (("awaken_complete", "awaken", TC.run_awaken_step), ("beginning_entered", "beginning", TC.enter_beginning_phase),
              ("channel_complete", "channel", TC.run_channel_step), ("draw_complete", "draw", TC.run_draw_step),
              ("main_entered", "main", TC.enter_main_phase))
# Core 319's occasions, read from the states before and after a transition
CLEANUP_CLAUSES = {"319.1": "the game went from an Open to a Closed state or back",
                   "319.2": "the game went from one Phase to another",
                   "319.3": "a Pending Item was added to the Chain",
                   "319.4": "a Pending Item became Finalized",
                   "319.5": "a Chain Item was removed from the Chain",
                   "319.6": "a Game Object entered or left the Board",
                   "319.7": "the status of a Game Object changed - a status of Core 124.2 or an applied Layer effect, "
                            "read through STATUS_PROJECTION (an engine-internal field is not a status)",
                   "319.8": "a Move was completed (an object on the Board changed Location)"}
REQUEST_SUFFIX = "_required"
# the triggered abilities whose program is the engine's (a keyword that is the whole ability), by program id prefix
ENGINE_PROGRAMS = {IR.TEMPORARY_PROGRAM_PREFIX: IR.temporary_program, IR.VISION_PROGRAM_PREFIX: IR.vision_program}


def envelope(effect_state: dict[str, Any], decisions: list[dict[str, Any]] | tuple = (),
             receipts: list[dict[str, Any]] | tuple = (), *, timing_state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """engine-decisions.v1 for the state: the choices made, and the randomization receipts chance supplied (ADR-0010 §2:
    a receipt is not a choice - it rides in the same envelope). Bound to the effect state, or - for the two-state
    procedures (turn_cycle, battlefield_control, combat: ADR-0008 §2) - to both (`timing_state`)."""
    decisions, receipts = list(decisions), list(receipts)
    if not decisions and not receipts:
        return None
    bound = CB.combined_input_hash(timing_state, effect_state) if timing_state is not None else hash_value(effect_state)
    return {"schema_version": DECISIONS_VERSION, "input_hash": bound, "decisions": decisions,
            **({"randomization_receipts": receipts} if receipts else {})}


def _reads_receipt(program: dict[str, Any]) -> bool:
    return any("cost_offer_id" in (e.get("predicate") or {}) for e in program.get("effects") or [] if isinstance(e, dict))


def _card_ref(effect_state: dict[str, Any], object_id: str | None) -> str | None:
    if object_id in (effect_state.get("objects") or {}):
        return effect_state["objects"][object_id].get("card_ref")
    return ((effect_state.get("battlefields") or {}).get(object_id) or {}).get("card_ref")


def _delayed(value: Any, program_id: str) -> dict[str, Any] | None:
    """The create_delayed_trigger instruction of a program that makes delayed trigger `program_id`."""
    if isinstance(value, dict):
        if value.get("op") == "create_delayed_trigger" and (value.get("delayed") or {}).get("effect_program_id") == program_id:
            return value
        values = value.values()
    elif isinstance(value, list):
        values = value
    else:
        return None
    return next((found for v in values if (found := _delayed(v, program_id)) is not None), None)


def item_program(catalogue: dict[str, Any], effect_state: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    """The program a chain item recorded, its symbols bound to the item: a card's program by its effect_program_id
    ('<card>#<program>'); a delayed trigger's (Core 390) is the instructions the create_delayed_trigger that made it
    carries, found on its source's card (resolution_bridge.dispatch_program then checks them against the hash the
    trigger carried - a mismatch is refused by name, never run)."""
    program_id = item.get("effect_program_id")
    if not isinstance(program_id, str):
        return None
    controller = item["controller"]
    opponents = [p for p in effect_state["players"] if p != controller]
    entry = (effect_state.get("chain_items") or {}).get(item["id"]) or {}
    # a triggered ability's source is on its item; a played card's is its card; an activated ability's, its entry's
    source = item.get("source_object") or entry.get("card") or entry.get("source_object")
    bindings = {"$controller": controller, "$opponent": opponents[0], "$chain_item": item["id"], "$source_object": source,
                "$card": source}
    for prefix, build in ENGINE_PROGRAMS.items():
        if program_id == f"{prefix}:{source}":
            # a keyword that is the whole ability: the engine's own program (effect_ir), not a card's
            return build(effect_state, source, controller)
    if "#" in program_id:
        ref, key = program_id.split("#", 1)
        if key not in ((catalogue["cards"].get(ref) or catalogue.get("tokens", {}).get(ref) or {}).get("programs") or {}):
            return None
        program = CE.instantiate_program(catalogue, ref, key, bindings)
        receipt = ((effect_state.get("chain_items") or {}).get(item["id"]) or {}).get("cost_receipt")
        if receipt is not None and _reads_receipt(program):
            # Core 356.4.f.1: a body that reads what was paid for it reads the play's own receipt, kept on its chain entry
            program["cost_receipt"] = copy.deepcopy(receipt)
        return program
    ref = _card_ref(effect_state, source)
    instruction = _delayed((catalogue["cards"].get(ref) or {}).get("programs") or {}, program_id) if ref else None
    if instruction is None:
        return None
    return {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "program_id": program_id, "controller": controller, "source_object": source,
            "effects": CE.bind(copy.deepcopy(instruction["effects"]), bindings)}


def _step(kind: str, label: str, timing: dict[str, Any], effect: dict[str, Any], result: dict[str, Any] | None,
          committed: bool, next_timing: dict[str, Any] | None = None, next_effect: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {"schema_version": LOOP_VERSION, "kind": kind, "label": label, "committed": committed,
           "input_timing_state_hash": RC.state_hash(timing), "input_effect_state_hash": hash_value(effect),
           "result": result, "request": None, "cleanup": []}
    if committed:
        clauses = [] if label == "task:cleanup" else cleanup_clauses(timing, effect, next_timing, next_effect)
        if clauses and RC.CLEANUP_TASK not in next_timing["outstanding_tasks"] and not RC.is_terminal(next_timing):
            next_timing = copy.deepcopy(next_timing)
            # ahead of the Scoring Step, which follows the Beginning Step's effects and their Cleanups (Core 315.2)
            tasks = list(next_timing["outstanding_tasks"])
            at = tasks.index(BC.SCORING_TASK) if BC.SCORING_TASK in tasks else len(tasks)
            next_timing["outstanding_tasks"] = tasks[:at] + [RC.CLEANUP_TASK] + tasks[at:]
        out.update({"next_timing_state": next_timing, "next_effect_state": next_effect, "cleanup": clauses})
    else:
        out["request"] = request_of(result)
    return out


def _done(kind: str, label: str, timing: dict[str, Any], effect: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """A step from an engine result: committed (timing-only results carry next_state) or not."""
    if result is None:
        return _step(kind, label, timing, effect, {"reason_code": "no_procedure", "reason": label}, False)
    if result.get("committed") is True or (result.get("applied") is True and "next_state" in result):
        next_timing = result.get("next_timing_state") or result.get("next_state")
        next_effect = result.get("next_effect_state") or effect
        return _step(kind, label, timing, effect, result, True, next_timing, next_effect)
    return _step(kind, label, timing, effect, result, False)


def request_of(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """The decision a refused result asks for, from the innermost result that asks - {code, decision_ids, controller,
    payload} - or None (a refusal, not a request)."""
    if not isinstance(result, dict):
        return None
    for sub in ("effect_result", "resolution", "timing_result", "trigger_result", "cleanup_result"):
        inner = request_of(result.get(sub))
        if inner is not None:
            return inner
    code = result.get("reason_code") if str(result.get("reason_code") or "").endswith(REQUEST_SUFFIX) else result.get("reason")
    if result.get("replacement_decision_required"):
        code = "replacement_decision_required"
    if not (isinstance(code, str) and code.endswith(REQUEST_SUFFIX)):
        return None
    return {"code": code, "decision_ids": list(result.get("decision_ids") or []),
            "controller": result.get("decision_controller"), "payload": result}


def run_procedure(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any],
                  decisions: list[dict[str, Any]] | tuple = (), settings: dict[str, Any] | None = None,
                  receipts: list[dict[str, Any]] | tuple = ()) -> dict[str, Any]:
    settings = dict(settings or {})
    unknown = sorted(set(settings) - set(SETTINGS))
    if unknown:
        raise ValueError(f"settings {unknown} are not procedure arguments ({sorted(SETTINGS)})")
    procedure = RC.next_procedure(timing)
    name = procedure.get("procedure")
    env = envelope(effect, decisions, receipts)
    both = envelope(effect, decisions, receipts, timing_state=timing)    # the two-state procedures' binding
    if procedure.get("valid") is False:
        return _step("procedure", "invalid", timing, effect, procedure, False)
    if name in DISCRETIONARY and not (name == "neutral_turn_window" and timing.get("phase") == "ending"):
        return _step("procedure", f"discretionary:{name}", timing, effect,
                     {"reason_code": "discretionary_point", "reason": f"{name}: a player acts (run_action)"}, False)
    if name == "game_over":
        return _step("procedure", "game_over", timing, effect, {"reason_code": "game_over"}, False)
    if name == "handle_outstanding_tasks":
        task = procedure["subject"]
        if task == RC.CLEANUP_TASK:
            return _done("procedure", "task:cleanup", timing, effect, TC.run_cleanup(timing, effect, both))
        if task == BC.SCORING_TASK:
            return _done("procedure", "task:scoring", timing, effect, BC.run_scoring_step(timing, effect, both))
        return _done("procedure", f"task:{task}", timing, effect, None)
    if name == "finalize_oldest_pending":
        item = next(i for i in timing["chain"]["items"] if i["status"] == "pending")
        program = item_program(catalogue, effect, item)
        if item.get("limited_play"):
            return _done("procedure", "finalize:limited_play", timing, effect, RB.complete_limited_play(
                timing, effect, env, entry_location=settings.get("entry_location"), payment_context=PAYMENT_CONTEXT,
                effect_program=program))
        if item.get("timing") == "triggered":
            registry = {program["program_id"]: program} if program else {}
            return _done("procedure", "finalize:trigger", timing, effect, RB.finalize_trigger(
                timing, effect, registry, env, perform_optional_trigger=settings.get("perform_optional_trigger"),
                pay_trigger_cost=settings.get("pay_trigger_cost"), payment_context=PAYMENT_CONTEXT))
        finalized = RC.finalize_oldest_pending(timing)
        if finalized.get("applied") is not True or not (finalized.get("transition") or {}).get("immediate_resolution_required"):
            return _done("procedure", f"finalize:{item.get('object_kind')}", timing, effect, finalized)
        # Core 337.2: a Unit, Gear or [Add] ability resolves as soon as it is Finalized - in this same transition
        resolved = RB.resolve_with_program(finalized["next_state"], item["id"], effect, program, None, env)
        return _done("procedure", f"finalize_and_resolve:{item.get('object_kind')}", timing, effect, resolved)
    if name == "resolve_newest_finalized":
        item = timing["chain"]["items"][-1]
        return _done("procedure", f"resolve:{item.get('object_kind')}", timing, effect,
                     RB.resolve_with_program(timing, item["id"], effect, item_program(catalogue, effect, item), None, env))
    if name == "begin_turn_pending":
        return _done("procedure", "turn:begin", timing, effect, TC.begin_turn(timing, effect, both))
    if name == "turn_start_step_pending":
        progress = timing.get("turn_progress") or {}
        flag, label, run = next(((f, l, r) for f, l, r in TURN_STEPS if not progress.get(f)), TURN_STEPS[-1])
        return _done("procedure", f"turn:{label}", timing, effect, run(timing, effect, both))
    if name == "open_showdown_pending":
        return _done("procedure", "showdown:open", timing, effect, BC.open_showdown(timing, effect, both))
    if name == "control_resolution_pending":
        return _done("procedure", "showdown:control", timing, effect, BC.resolve_battlefield_control(timing, effect, both))
    if name == "open_combat_pending":
        return _done("procedure", "combat:open", timing, effect, CB.open_combat(timing, effect, both))
    if name == "combat_step_pending":
        label, run = COMBAT_STEPS.get(timing["combat"]["status"], (timing["combat"]["status"], None))
        return _done("procedure", f"combat:{label}", timing, effect, run(timing, effect, both) if run else None)
    if name == "neutral_turn_window":   # the Ending Phase (Core 317): its Expiration Step, then the next turn
        if (timing.get("ending_step") or {}).get("status") == "triggers_scheduled":
            return _done("procedure", "turn:expiration", timing, effect, RB.run_expiration_step(timing, effect))
        return _done("procedure", "turn:next", timing, effect, TC.begin_turn(timing, effect, both))
    return _done("procedure", f"unknown:{name}", timing, effect, None)


def action_program(catalogue: dict[str, Any], effect: dict[str, Any], declaration: dict[str, Any]) -> dict[str, Any] | None:
    """The program a play or activation declares, as play_space plays it (a body reading its own receipt is bound
    after the play, so the play takes none)."""
    import play_space as PS
    program_id = declaration.get("effect_program_id")
    if not program_id:
        return None
    key = program_id.split("#", 1)[-1]
    program = PS._program(catalogue, effect, declaration["card"], key, declaration["actor"], declaration["chain_item"]["id"])
    return None if PS._reads_receipt(program) else program


def run_action(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any], action: dict[str, Any],
               receipts: list[dict[str, Any]] | tuple = ()) -> dict[str, Any]:
    """A discretionary action (action_space.ACTION_KINDS) as legal_action enumerates it - with the randomization receipts
    chance gives, when its cost recycles cards to a Main Deck (an action carries none: play_space.CHANCE_ORDER)."""
    kind = action["kind"]
    actor = action.get("actor") or (action.get("declaration") or {}).get("actor")
    if kind in ("play_card", "activate_ability"):
        declaration = action["declaration"]
        return _done("action", kind, timing, effect, PT.play_card(
            timing, effect, declaration, engine_decisions=envelope(effect, action.get("decisions") or [], receipts),
            effect_program=action_program(catalogue, effect, declaration)))
    if kind == "standard_move":
        return _done("action", kind, timing, effect, CB.standard_move(timing, effect, action["declaration"],
                                                                      envelope(effect, action.get("decisions") or [], timing_state=timing)))
    if kind == "hide":
        import hidden
        return _done("action", kind, timing, effect, hidden.hide_card(timing, effect, action["declaration"]))
    if kind == "pass_priority":
        return _done("action", kind, timing, effect, RC.pass_priority(timing, actor))
    if kind == "pass_focus":
        return _done("action", kind, timing, effect, RC.pass_focus(timing, actor))
    if kind == "end_main_phase":
        return _done("action", kind, timing, effect, RB.end_main_phase(timing, effect, actor))
    raise ValueError(f"no action kind {kind!r}")


def _board(effect: dict[str, Any]) -> dict[str, Any]:
    """{object id: its Location} for every object on the Board."""
    out = {}
    for object_id in effect["objects"]:
        where = find_location(effect, object_id)
        if zone_class(where) == "board":
            out[object_id] = where
    return out


# Core 124.2's statuses (its list is not exhaustive, but not every field the engine keeps is a game state - GPT PACKAGE14
# ruling 5), each read from where the engine keeps it; an object's characteristics are its applied Layer effects:
#   Exhausted / Readied   exhausted             Stunned               stunned
#   Buffed                buffed, buff_count    Empowered             empowered
#   Controlled            controller            Attacking / Defending combat_designation
#   Attached / Equipped   attached_to           Revealed              the state's reveal marks
#   Layer effects         every applied Layer effect (Core 124.2, 476-480: effect_ir.characteristics) - which
#                         effects apply, in which layer, and what they make of the object: its kind (Trait layer:
#                         copy_traits), its triggered abilities (Ability layer: ability_append, a copy's rules text),
#                         its keywords and its Might (Arithmetic); and the rules-facing Might (effective_might)
#   a Battlefield's       controller, contested, contested_by (Core 190: control; 190.3.a: Contested is a status)
# Not statuses: identity (a new object is 319.6), owner, modes_chosen, control_changed, pending_recall (the engine's own
# records); damage (Core 124.1: a temporary modification - dealt only by resolutions and Combat steps, whose own
# lethal Cleanup and 319.5 / phase Cleanups follow it)
STATUS_FIELDS = ("exhausted", "stunned", "buffed", "buff_count", "empowered", "controller", "combat_designation", "attached_to")
BATTLEFIELD_STATUS_FIELDS = ("controller", "contested", "contested_by")
NOT_STATUS_FIELDS = ("identity", "owner", "modes_chosen", "control_changed", "pending_recall", "damage", "might_modifiers")


def status_projection(effect: dict[str, Any]) -> dict[str, Any]:
    """Every rules-meaningful status of every object on the Board and every Battlefield (STATUS_FIELDS above)."""
    out: dict[str, Any] = {}
    for object_id in _board(effect):
        obj = effect["objects"][object_id]
        record = {k: obj.get(k) for k in STATUS_FIELDS}
        if obj.get("kind") in {"unit", "gear", "legend"}:
            try:
                # GPT PACKAGE14 round-two review: the applied Layer effects themselves, not only the Might and keywords
                # they leave (a copy's rules text changes neither)
                layered = IR.characteristics(effect, object_id)
                record["layers"] = {"kind": layered.get("kind"), "might": layered.get("might"),
                                    "keywords": layered.get("keywords"), "triggers": layered.get("triggers"),
                                    "applied": sorted((a.get("effect_id"), a.get("layer")) for a in layered.get("applied") or [])}
                record["might"] = IR.effective_might(effect, object_id) if obj.get("kind") == "unit" else None
            except Exception as exc:  # noqa: BLE001 - an unreadable characteristic is a change, never a silent same
                record["characteristics_unreadable"] = f"{type(exc).__name__}"
        out[f"object:{object_id}"] = record
    for bf, entry in (effect.get("battlefields") or {}).items():
        out[f"battlefield:{bf}"] = {k: entry.get(k) for k in BATTLEFIELD_STATUS_FIELDS}
    out["revealed"] = sorted(json.dumps({"object": m.get("object_id"), "to": m.get("visible_to")}, sort_keys=True)
                             for m in effect.get("reveals") or [])
    return out


def cleanup_clauses(t0: dict[str, Any], e0: dict[str, Any], t1: dict[str, Any], e1: dict[str, Any]) -> list[str]:
    """The Core 319 occasions between two states, by clause number (CLEANUP_CLAUSES)."""
    out = []
    if bool(t0["chain"]["items"]) != bool(t1["chain"]["items"]):
        out.append("319.1")
    if t0.get("phase") != t1.get("phase"):
        out.append("319.2")
    before = {i["id"]: i["status"] for i in t0["chain"]["items"]}
    after = {i["id"]: i["status"] for i in t1["chain"]["items"]}
    if any(status == "pending" and i not in before for i, status in after.items()):
        out.append("319.3")
    if any(before.get(i) == "pending" and status == "finalized" for i, status in after.items()):
        out.append("319.4")
    if set(before) - set(after):
        out.append("319.5")
    board0, board1 = _board(e0), _board(e1)
    if set(board0) != set(board1):
        out.append("319.6")
    before, after = status_projection(e0), status_projection(e1)
    if any(before.get(k) != v for k, v in after.items() if k.startswith("battlefield:") or k == "revealed"
           or k.removeprefix("object:") in board0):
        out.append("319.7")
    if any(board0[o] != board1[o] for o in set(board0) & set(board1)):
        out.append("319.8")
    return out
