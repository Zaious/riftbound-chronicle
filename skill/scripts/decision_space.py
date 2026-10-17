#!/usr/bin/env python3
"""Every decision of a procedure point, and the options of each (C2, package 14; GPT PACKAGE13 ruling 1's second half).

At a procedure point no one acts at will: the timing kernel names the procedure due (rules_core.next_procedure), and
game_loop.run_procedure runs it. The procedure may ask for choices first - a target as a triggered ability is
finalized, a card as an instruction resolves, a Combat's damage assignment, the order of abilities that triggered
together - each a request (game_loop.request_of). A request is answered by a decision of its kind
(engine_decisions.KINDS), by a procedure argument (game_loop.SETTINGS), or by a randomization receipt (chance, not a
choice: ADR-0010 §2). This module says, for a procedure point, every way the procedure can be completed:

  discovery     the procedure is run with the answers given so far; it commits (a complete way, a `leaf`), refuses (with
                its reason), or asks - and each request's domain (`answers`) is read from what the request carries, or,
                where it carries none, from the state and the rules (ANSWERED below says which); every value is tried.
                A request this module has no domain for, a request asked again after it was answered (the procedure does
                not read that answer), more calls than CALL_CAP, or a chance node with more outcomes than CHANCE_CAP
                followed by another request makes the point's answer unproved, by name - never a partial set offered
                as the whole.
  a point       `decision_point`: the first request of the point, its decider, and every answer to it that some
                complete way of the procedure begins with (the decider's options); the answers with none are excluded
                with the reasons the procedure gave. A point the procedure completes with no request has no decider.
  completion    `procedure_ways`: every complete way (the answers of every request, in order), keyed canonically.

Chance: a request for a randomization receipt is nature's move. Its outcomes are every permutation of what it orders;
up to CHANCE_CAP of them each is tried, past it only the identity order is (GPT PACKAGE14 ruling 4 keeps the two claims
apart): a player's option is legal when some complete way begins with it, and the representative order's way shows
that - but an option with no way found under a sampled chance node is not shown illegal (unproved), and the point's
complete ways under a sampled node are not all of them (procedure_ways unproved: the random successors are the seeded
receipts' and the replay's to cover, package 15).

    decision_point(timing, effect, catalogue, made=None) -> point
    procedure_ways(timing, effect, catalogue) -> {status, ways, refused, calls, reason}
"""
from __future__ import annotations

import copy
import itertools
from typing import Any

import effect_ir as IR
import game_loop as GL
import play_space as PS
import play_transaction as PT

DECISION_SPACE_VERSION = "c2-decision-space.v1"
CALL_CAP = 1 << 14
VALUE_CAP = 1 << 12
CHANCE_CAP = 24
RECEIPT_PROVENANCE = {"provider": "decision_space", "method": "every_permutation"}

# every request a procedure makes, and how this module answers it (the closure gate, check_decision_space D6, holds
# this against the request codes the engine's modules can produce)
ANSWERED = {
    "target_selection_required": "target_selection: the program's selector (play_space._templates) over "
                                 "play_transaction.legal_target_options, in the counts it states (Core 355.5)",
    "move_destination_required": "location_selection: every Base and every Battlefield (Core 355.4)",
    "location_selection_required": "location_selection: the candidates the request carries (Core 461.1, 323.11 at a "
                                   "procedure: a Battlefield id; a Move or a token's place at resolution: a location)",
    "optional_choice_required": "optional_choice: taken or not",
    "option_selection_required": "option_selection: the options the request carries (the instruction's own)",
    "mode_selection_required": "mode_selection: the mode options the request carries (Core 402.2)",
    "player_selection_required": "player_selection: every player (the procedure refuses one it may not name)",
    "card_selection_required": "card_selection: the options the choice offers - public in its summary; private to its "
                               "chooser, in the trusted record (effect_ir.recording_private_options), never a result - in "
                               "the count it states",
    "card_ordering_required": "card_ordering: every order of every card the choice carries",
    "buff_spend_required": "buff_spend: how many of each Unit's buffs, 0 up to what it has (Core 426.1.b.2, 702.2.b)",
    "target_group_subset_required": "card_selection: every subset of the still-legal targets it carries (Core 355.11.b)",
    "trigger_order_required": "trigger_order: every order of the abilities it names (Core 383.3.d)",
    "replacement_decision_required": "replacement_choice (one replacement, one event: applied or not) or "
                                     "replacement_order (every order of the replacements or events it names, Core 372)",
    "damage_assignment_required": "damage_assignment: every split of the available damage among the opposing Units it "
                                  "carries, with a Tank-or-Backline choice for a Unit that has both (Core 465.2.c)",
    "damage_division_required": "damage_division: every division of the amount among as many of the legal Targets as "
                                "it keeps, each a positive amount (Core 355.14.e-h)",
    "resource_allocation_required": "resource_allocation: every amount of each Domain's Power in the pool, none to all "
                                    "(Core 204.3.b, a 'pay any amount')",
    "trigger_finalize_choice_required": "setting perform_optional_trigger: performed or not (Core 383.3.a)",
    "trigger_cost_choice_required": "setting pay_trigger_cost: paid or not (Core 403.1.b.1, 404.2)",
    "entry_location_required": "setting entry_location: the location candidates it carries (Core 355.2)",
    "randomization_receipt_required": "chance: every permutation of the cards it orders (Core 416.5, 431.2.b)",
    "cost_selection_required": "card_selection: one of the Units it carries spends its buff for the trigger's base cost "
                               "(Core 702.2.b, 404.1)",
}
# a limited play's own requests at its finalization are a play's (Core 419.3.b) - answered as play_space answers them
PLAY_REQUESTS = dict(PS.DECIDED)
SETTING_REQUESTS = {"trigger_finalize_choice_required": "perform_optional_trigger",
                    "trigger_cost_choice_required": "pay_trigger_cost", "entry_location_required": "entry_location"}
# the request codes the engine's modules can make that are not a decision of a procedure point, each with why
NOT_DECISIONS = {
    "priority_required": "a timing refusal of an action (rules_core.validate_timing): no procedure asks it",
    "focus_required": "a timing refusal of an action", "focus_and_priority_required": "a timing refusal of an action",
    "finalized_item_required": "a timing refusal (rules_core.complete_resolution of a Pending item)",
    "neutral_open_turn_window_required": "a timing refusal of an action",
    "limited_play_steps_required": "rules_core refuses to mark a limited play Finalized without its steps; game_loop "
                                   "finalizes it through resolution_bridge.complete_limited_play",
    "immediate_resolution_required": "a flag on a Finalized Unit, Gear or [Add]: game_loop resolves it in the same "
                                     "transition (Core 337.2)",
    "effect_execution_confirmation_required": "rules_core.complete_resolution's argument, given by resolution_bridge",
    "effect_program_required": "a program-binding refusal: game_loop.item_program supplies the item's program",
    "ganking_required": "a Standard Move's refusal (an action, package 13)",
    "cost_confirmation_required": "a Standard Move's declaration field (an action, package 13)",
    "restage_required": "a Combat result's flag, read by combat.close_combat",
    "add_window_confirmation_required": "game_loop closes the Add window (PAYMENT_CONTEXT): an [Add] is an action",
    "new_choices_required": "Core 753's new choices: no program of the environment makes them (check_decision_space "
                            "D6 holds that no catalogued program carries the instruction that asks)",
    "external_input_required": "the flag beside randomization_receipt_required on the same result (reason_code is "
                               "randomization_receipt_required)",
    "choice_required": "the flag beside a choice's own code (<decision kind>_required) on the same result",
    "target_decision_required": "the flag beside target_selection_required on the same result",
    "decision_required": "an outcome class (engine_check, trigger_cost's error kind), not a request code",
}


class Unproved(Exception):
    """A procedure point whose ways this module cannot prove whole."""


def _identity(state: dict[str, Any], object_id: str) -> str:
    return IR.object_identity(state, object_id) or f"{object_id}@0"


def _sets(items: list[str], low: int, high: int | None, *, ordered: bool = False) -> list[list[str]]:
    items = sorted(items)
    high = len(items) if high is None else min(high, len(items))
    pick = itertools.permutations if ordered else itertools.combinations
    out = [list(c) for size in range(low, high + 1) for c in pick(items, size)]
    if len(out) > VALUE_CAP:
        raise Unproved(f"{len(out)} selections exceed {VALUE_CAP}")
    return out


def _compositions(total: int, parts: int, low: int) -> list[tuple[int, ...]]:
    """Every way to write `total` as `parts` ordered integers, each at least `low`."""
    if parts == 0:
        return [()] if total == 0 else []
    out = []
    for first in range(low, total - low * (parts - 1) + 1):
        out += [(first,) + rest for rest in _compositions(total - first, parts - 1, low)]
        if len(out) > VALUE_CAP:
            raise Unproved(f"more than {VALUE_CAP} splits of {total} into {parts}")
    return out


def stage_of(label: str, kind: str) -> str:
    """The engine-decisions stage a decision of `kind` is made at, in the procedure `label` runs."""
    if kind in {"replacement_order", "replacement_choice", "trigger_order", "option_selection", "damage_division",
                "buff_spend"}:
        return "resolution"
    if kind == "damage_assignment":
        return "procedure"
    head = label.split(":", 1)[0]
    if head == "finalize" and label.endswith("limited_play"):
        return "play_declaration"
    if head == "finalize" and label.endswith("trigger"):
        return "trigger_finalization"
    if head in {"combat", "showdown", "task", "turn"} and kind in {"location_selection", "player_selection"}:
        return "procedure"
    return "resolution"


def _subject(timing: dict[str, Any], label: str) -> dict[str, Any] | None:
    """The chain item the procedure works on: the oldest Pending to finalize, the newest to resolve."""
    items = timing["chain"]["items"]
    if label.startswith("finalize"):
        return next((i for i in items if i["status"] == "pending"), None)
    if label.startswith("resolve") and items:
        return items[-1]
    return None


def _run(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any], answer: dict[str, Any] | None = None
         ) -> dict[str, Any]:
    """game_loop.run_procedure with the answers given - and, for a request, what a choice private to its chooser offers
    (effect_ir.recording_private_options: the trusted verifier's record; no result carries it)."""
    answer = answer or _answer()
    with IR.recording_private_options() as log:
        step = GL.run_procedure(timing, effect, catalogue, answer["decisions"], answer["settings"], answer["receipts"])
    if step["request"] is not None:
        step = {**step, "request": {**step["request"], "private_options": dict(log)}}
    return step


def _answer(decisions=(), settings=None, receipts=()) -> dict[str, Any]:
    return {"decisions": list(decisions), "settings": dict(settings or {}), "receipts": list(receipts)}


def _plus(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {"decisions": a["decisions"] + b["decisions"], "settings": {**a["settings"], **b["settings"]},
            "receipts": a["receipts"] + b["receipts"]}


def answers(request: dict[str, Any], timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any],
            label: str) -> tuple[str, str | None, list[dict[str, Any]]]:
    """(kind, decider, every answer) for one request; Unproved when it has no domain here."""
    code, payload = request["code"], request["payload"]
    ids = request["decision_ids"]
    item = _subject(timing, label)
    program = GL.item_program(catalogue, effect, item) if item else None
    decider = request.get("controller") or (item or {}).get("controller") or (
        timing.get("turn_player") if label.split(":", 1)[0] in {"combat", "showdown", "task", "turn"} else None)

    def entries(kind, values, *, decision_id=None, identities=False):
        """`identities`: True binds each object as the state names it; a map binds it as the request does (an object
        that changed zone during the resolution is a new object, Core 124 - the request knows its identity now)."""
        out = []
        for value in values:
            entry = {"decision_id": decision_id or ids[0], "stage": stage_of(label, kind), "kind": kind,
                     "controller": decider, "value": value}
            if identities:
                known = identities if isinstance(identities, dict) else {}
                entry["selection_identities"] = {o: known.get(o) or _identity(effect, o) for o in value}
            out.append(_answer([entry]))
        return out

    if label.endswith("limited_play") and code in PLAY_REQUESTS and PLAY_REQUESTS[code] != "chance":
        # a limited play's choices at its own finalization: the play's (Core 419.3.b) - play_space's domains
        card = ((effect.get("chain_items") or {}).get(item["id"]) or {}).get("card")
        per_id = PS.domain(payload, effect, {"card": card}, program, decider)
        return PLAY_REQUESTS[code], decider, [_answer([{**e, "stage": "play_declaration"} for e in combo])
                                              for combo in itertools.product(*per_id)]
    if code in SETTING_REQUESTS:
        setting = SETTING_REQUESTS[code]
        values = payload.get("location_candidates") if setting == "entry_location" else [True, False]
        if not values:
            raise Unproved(f"{code} carries no candidates")
        return setting, decider, [_answer(settings={setting: copy.deepcopy(v)}) for v in values]
    if code == "randomization_receipt_required":
        chance = payload.get("chance")
        if not isinstance(chance, dict):
            raise Unproved("a randomization request carries no operation (what chance orders)")
        cards = list(chance["permute"])
        many = 1
        for n in range(2, len(cards) + 1):
            many *= n
        orders = itertools.permutations(cards) if many <= CHANCE_CAP else [tuple(cards)]
        out = [_answer(receipts=[{"schema_version": "randomization-receipt.v1", "receipt_id": f"ds:{chance['operation_id']}:{k}",
                                  "operation": chance["operation"], "operation_id": chance["operation_id"],
                                  "player": chance["player"], "permutation": list(order),
                                  "provenance": dict(RECEIPT_PROVENANCE)}]) for k, order in enumerate(orders)]
        if many > CHANCE_CAP:
            for a in out:
                a["sampled_chance"] = many
        return "chance", None, out
    if isinstance(payload.get("choice"), dict) and code not in {"buff_spend_required"} \
            and payload["choice"].get("decision_kind") in {"target_selection", "player_selection"}:
        # an instruction's own choice (effect_ir.resolve_choice) - of the board or of the players - answered from what
        # the choice offers, by its chooser (an each_player copy's is that player's, Core 355.10.e)
        summary = payload["choice"]
        decider = summary.get("chooser") or decider
        listing = summary.get("options") if summary.get("options") is not None else \
            (request.get("private_options") or {}).get(ids[0])
        if listing is None:
            raise Unproved(f"{code}: the choice carries neither its options nor its chooser's")
        kind = summary["decision_kind"]
        pool = [o["object_id"] for o in listing]
        if kind == "player_selection":
            return kind, decider, entries(kind, pool)
        bound = {o["object_id"]: o.get("identity") for o in listing if o.get("identity")}
        form, n = next(iter(summary["count"].items()))
        n = n if isinstance(n, int) and not isinstance(n, bool) else None
        low, high = {"one": (1, 1), "exactly": (n, n), "up_to": (0, n), "any_number": (0, None), "all": (len(pool), len(pool))}[form]
        return kind, decider, entries(kind, _sets(pool, low, high), identities=bound or True)
    if code == "target_selection_required":
        if program is None:
            raise Unproved(f"target {ids} asked with no program for the item")
        # the program as the procedure runs it for this item: its source's identity and its event bound (a Battlefield's
        # "here" is read through them, resolution_bridge.bind_source_identity)
        import resolution_bridge as RB
        bound, refusal = RB.bind_source_identity(program, item) if item is not None else (program, None)
        program = bound if refusal is None else program
        templates = PS._templates(program)
        per_id = []
        for ref in ids:
            template = templates.get(ref)
            if template is None:
                raise Unproved(f"target {ref!r}: no selector of the program names it")
            selector = {k: v for k, v in template.items() if not k.startswith("_")}
            options = PT.legal_target_options(effect, decider, program, selector)
            sets = _sets(options, *template["_count"]) if "_count" in template else [[o] for o in sorted(options)]
            per_id.append([{"decision_id": ref, "stage": stage_of(label, "target_selection"), "kind": "target_selection",
                            "controller": decider, "value": s, "selection_identities": {o: _identity(effect, o) for o in s}}
                           for s in sets])
        return "target_selection", decider, [_answer(list(c)) for c in itertools.product(*per_id)]
    if code == "move_destination_required":
        values = [f"base:{p}" for p in sorted(effect["players"])] + [f"battlefield:{b}" for b in sorted(effect["battlefields"])]
        per_id = [[{"decision_id": ref, "stage": stage_of(label, "location_selection"), "kind": "location_selection",
                    "controller": decider, "value": v} for v in values] for ref in ids]
        return "location_selection", decider, [_answer(list(c)) for c in itertools.product(*per_id)]
    if code == "location_selection_required":
        values = payload.get("options") or payload.get("location_candidates") or payload.get("candidates")
        if not values:
            raise Unproved("a location request carries no candidates")
        return "location_selection", decider, entries("location_selection", list(values))
    if code == "optional_choice_required":
        return "optional_choice", decider, entries("optional_choice", [True, False])
    if code == "option_selection_required":
        if not payload.get("options"):
            raise Unproved("an option request carries no options")
        return "option_selection", decider, entries("option_selection", list(payload["options"]))
    if code == "mode_selection_required":
        if not payload.get("mode_options"):
            raise Unproved("a mode request carries no options")
        return "mode_selection", decider, entries("mode_selection", list(payload["mode_options"]))
    if code == "player_selection_required":
        return "player_selection", decider, entries("player_selection", sorted(effect["players"]))
    if code in {"card_selection_required", "card_ordering_required", "buff_spend_required"} and isinstance(payload.get("choice"), dict):
        summary = payload["choice"]
        decider = summary.get("chooser") or decider
        listing = summary.get("options") if summary.get("options") is not None else \
            (request.get("private_options") or {}).get(ids[0])
        if listing is None:
            raise Unproved(f"{code}: the choice carries neither its options nor its chooser's")
        pool = [o["object_id"] for o in listing]
        bound = {o["object_id"]: o.get("identity") for o in listing if o.get("identity")}
        kind = summary.get("decision_kind") or code[: -len(GL.REQUEST_SUFFIX)]
        if kind == "buff_spend":
            counts = summary["buff_counts"]
            units = sorted(counts)
            values = [{u: n for u, n in zip(units, split) if n} for split in itertools.product(*[range(counts[u] + 1) for u in units])]
            if len(values) > VALUE_CAP:
                raise Unproved(f"{len(values)} buff spends exceed {VALUE_CAP}")
            return kind, decider, entries(kind, values, identities=bound or True)
        form, n = next(iter(summary["count"].items()))
        n = n if isinstance(n, int) and not isinstance(n, bool) else None
        low, high = {"one": (1, 1), "exactly": (n, n), "up_to": (0, n), "any_number": (0, None), "all": (len(pool), len(pool))}[form]
        ordered = kind == "card_ordering" or summary.get("selection_kind") == "ordered_permutation"
        if kind == "card_ordering":
            low = high = len(pool)
        return kind, decider, entries(kind, _sets(pool, low, high, ordered=ordered), identities=bound or True)
    if code == "cost_selection_required":
        units = list(payload.get("candidates") or [])
        return "card_selection", decider, entries("card_selection", [[u] for u in units], identities=True)
    if code == "target_group_subset_required":
        legal = list(payload.get("subset_candidates") or [])
        return "card_selection", decider, entries("card_selection", _sets(legal, 0, None), identities=True)
    if code == "trigger_order_required":
        orders = [list(o) for o in itertools.permutations(payload["trigger_ids"])]
        if len(orders) > VALUE_CAP:
            raise Unproved(f"{len(orders)} orders exceed {VALUE_CAP}")
        return "trigger_order", decider, entries("trigger_order", orders)
    if code == "replacement_decision_required":
        rids, events = list(payload.get("replacement_ids") or []), list(payload.get("event_ids") or [])
        if not rids or not events:
            raise Unproved("a replacement request names no replacement or no event")
        ref = f"replacement:{'+'.join(rids)}:{'+'.join(events)}"
        if len(rids) == 1 and len(events) == 1:
            return "replacement_choice", decider, entries("replacement_choice", [{rids[0]: {events[0]: v}} for v in (True, False)], decision_id=ref)
        if len(rids) == 1:
            return "replacement_order", decider, entries("replacement_order", [{rids[0]: list(o)} for o in itertools.permutations(events)], decision_id=ref)
        if len(events) == 1:
            return "replacement_order", decider, entries("replacement_order", [{events[0]: list(o)} for o in itertools.permutations(rids)], decision_id=ref)
        # several of one controller's Replacement Effects over several simultaneous events: the controller orders its own
        # sequences (Core 372) - keyed by that controller (effect_ir.perform_lethal_cleanup's sequence order)
        return "replacement_order", decider, entries("replacement_order", [{decider: list(o)} for o in itertools.permutations(rids)],
                                                     decision_id=ref)
    if code == "damage_assignment_required":
        units = [c["unit"] for c in payload["candidates"]]
        both = [c["unit"] for c in payload["candidates"] if len(c.get("requirements") or []) == 2]
        values = []
        for split in _compositions(payload["available"], len(units), 0):
            amounts = dict(zip(units, split))
            for picks in itertools.product(*[["tank", "backline"] for _ in both]):
                values.append({"amounts": amounts, "requirement_choices": dict(zip(both, picks))} if both else amounts)
        if len(values) > VALUE_CAP:
            raise Unproved(f"{len(values)} damage assignments exceed {VALUE_CAP}")
        out = []
        for value in values:
            amounts = value.get("amounts", value) if isinstance(value, dict) and "amounts" in value else value
            out.append(_answer([{"decision_id": ids[0], "stage": "procedure", "kind": "damage_assignment", "controller": decider,
                                 "value": value, "selection_identities": {u: _identity(effect, u) for u in amounts}}]))
        return "damage_assignment", decider, out
    if code == "damage_division_required":
        legal, amount, keep = list(payload["division_candidates"]), payload["division_amount"], payload["division_keeps"]
        values = [dict(zip(kept, split)) for kept in itertools.combinations(sorted(legal), keep)
                  for split in _compositions(amount, keep, 1)]
        return "damage_division", decider, entries("damage_division", values, identities=True)
    if code == "resource_allocation_required":
        pool = effect["players"][decider]["resources"]["power"]
        domains = sorted(d for d, n in pool.items() if n)
        values = [{d: k for d, k in zip(domains, split) if k} for split in itertools.product(*[range(pool[d] + 1) for d in domains])]
        if len(values) > VALUE_CAP:
            raise Unproved(f"{len(values)} allocations exceed {VALUE_CAP}")
        return "resource_allocation", decider, entries("resource_allocation", values)
    raise Unproved(f"{code}: no domain for this request ({label})")


def _signature(request: dict[str, Any]) -> tuple:
    return (request["code"], tuple(request["decision_ids"]), request.get("controller"),
            tuple((request["payload"].get("replacement_ids") or [])), tuple((request["payload"].get("event_ids") or [])))


def _explore(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any], start: dict[str, Any],
             budget: list[int]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """(the complete ways from `start`, the refusals, the requests met) - depth first, every answer tried."""
    ways, refused, met = [], [], []
    stack = [(start, frozenset(), 0)]
    while stack:
        answer, asked, sampled = stack.pop()
        budget[0] += 1
        if budget[0] > CALL_CAP:
            raise Unproved(f"more than {CALL_CAP} calls of the procedure")
        try:
            step = _run(timing, effect, catalogue, answer)
        except Exception as exc:  # noqa: BLE001 - a crash is never a refusal
            raise Unproved(f"the procedure failed: {type(exc).__name__}: {exc}") from exc
        if step["committed"]:
            ways.append({**answer, "label": step["label"], "next_effect_state_hash": IR.hash_value(step["next_effect_state"]),
                         "next_timing_state_hash": GL.RC.state_hash(step["next_timing_state"]),
                         **({"sampled_chance": sampled} if sampled else {})})
            continue
        request = step["request"]
        if request is None:
            result = step["result"] or {}
            if result.get("unsupported"):
                raise Unproved(f"{step['label']}: unsupported {result.get('reason_code')} ({str(result.get('reason'))[:120]})")
            refused.append(("sampled: " if sampled else "") + str(result.get("reason_code") or result.get("reason") or "refused"))
            continue
        signature = _signature(request)
        if signature in asked:
            raise Unproved(f"{step['label']}: {request['code']} {request['decision_ids']} asked again after it was answered "
                           f"- the procedure does not read that answer")
        kind, decider, options = answers(request, timing, effect, catalogue, step["label"])
        met.append({"label": step["label"], "code": request["code"], "kind": kind, "decider": decider,
                    "decision_ids": request["decision_ids"], "options": len(options)})
        if not options:
            refused.append(("sampled: " if sampled else "") + f"no_legal_{kind}")
        for option in options:
            stack.append((_plus(answer, option), asked | {signature}, max(sampled, option.get("sampled_chance") or 0)))
    return ways, refused, met


def way_key(way: dict[str, Any]) -> str:
    """A complete way, canonically: its decisions (ids, kinds, deciders, values), settings and chance outcomes."""
    decisions = sorted(({k: d[k] for k in ("decision_id", "stage", "kind", "controller", "value")} for d in way["decisions"]),
                       key=lambda d: (d["decision_id"], d["kind"]))
    receipts = sorted(({"operation_id": r["operation_id"], "permutation": r["permutation"]} for r in way["receipts"]),
                      key=lambda r: r["operation_id"])
    return IR.hash_value({"label": way.get("label"), "decisions": decisions, "settings": way["settings"], "receipts": receipts})


def procedure_ways(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    budget = [0]
    try:
        ways, refused, met = _explore(timing, effect, catalogue, _answer(), budget)
    except Unproved as why:
        return {"schema_version": DECISION_SPACE_VERSION, "status": "unproved", "reason": str(why), "ways": [],
                "refused": [], "requests": [], "calls": budget[0]}
    # every answer of a way is one the procedure asked for and read (asked, it is asked again without it), so a way is
    # its answers as given
    keyed = {way_key(w): w for w in ways}
    sampled = max([w.get("sampled_chance") or 0 for w in ways] + [0])
    if sampled or any(r.startswith("sampled: ") for r in refused):
        return {"schema_version": DECISION_SPACE_VERSION, "status": "unproved",
                "reason": f"a chance node orders more outcomes than {CHANCE_CAP} and only the identity order was run: the "
                          f"random successors are not all here (seeded receipts and replay, package 15)",
                "ways": [keyed[k] for k in sorted(keyed)], "refused": sorted(set(refused)), "requests": met, "calls": budget[0]}
    return {"schema_version": DECISION_SPACE_VERSION, "status": "enumerated", "reason": "ok", "calls": budget[0],
            "ways": [keyed[k] for k in sorted(keyed)], "refused": sorted(set(refused)), "requests": met}


def decision_point(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any],
                   made: dict[str, Any] | None = None) -> dict[str, Any]:
    """The next request of a procedure point after the answers `made` (none: the point's first), its decider, and every
    answer to it that begins some complete way; a point with no request left has no decider and one option: go on."""
    made = made or _answer()
    budget = [0]
    base = {"schema_version": DECISION_SPACE_VERSION, "procedure": GL.RC.next_procedure(timing).get("procedure")}
    try:
        step = _run(timing, effect, catalogue, made)
        if step["committed"]:
            return {**base, "status": "enumerated", "label": step["label"], "request": None, "decider": None,
                    "options": [{"answer": _answer(), "ways": 1}], "excluded": [], "calls": 1}
        request = step["request"]
        if request is None:
            result = step["result"] or {}
            if result.get("unsupported"):
                raise Unproved(f"{step['label']}: unsupported {result.get('reason_code')} ({str(result.get('reason'))[:120]})")
            return {**base, "status": "refused", "label": step["label"], "request": None, "decider": None, "options": [],
                    "excluded": [str(result.get("reason_code") or result.get("reason"))], "calls": 1,
                    "reason": str(result.get("reason") or "")[:200]}
        kind, decider, options = answers(request, timing, effect, catalogue, step["label"])
        kept, excluded = [], []
        for option in options:
            ways, refused, _ = _explore(timing, effect, catalogue, _plus(made, option), budget)
            if not ways and any(r.startswith("sampled: ") for r in refused):
                raise Unproved(f"an option found no complete way under a chance node of more than {CHANCE_CAP} outcomes, "
                               f"where only the identity order was run - it is not shown illegal")
            if ways:
                kept.append({"answer": option, "ways": len(ways)})
            else:
                excluded.append({"answer": option, "refused": sorted(set(refused))})
    except Unproved as why:
        return {**base, "status": "unproved", "reason": str(why), "request": None, "decider": None, "options": [],
                "excluded": [], "calls": budget[0]}
    return {**base, "status": "enumerated", "label": step["label"],
            "request": {"code": request["code"], "kind": kind, "decision_ids": request["decision_ids"]},
            "decider": decider, "options": kept, "excluded": excluded, "calls": budget[0] + 1}


# --------------------------------------------------------------------------------------------- the contract: D(s) --
# GPT PACKAGE13 ruling 3, for decisions: D(s) is read off the chain item's program and the procedure's own contract,
# not off the requests discovery answers. Two kinds of slot:
#   program slots  a decision the program names (PROGRAM_SLOT_FIELDS): its id and its kind from where it stands in the
#                  program, its values the state's own sets for that kind (every object, every player, every location,
#                  both truth values, the instruction's own options) - never a request's list
#   event slots    a decision the procedure names as an event happens (EVENT_SLOTS: abilities that triggered together,
#                  a replacement meeting an event, a Combat side, a staged location, chance): the contract checks the
#                  event against the state (its abilities, replacements, Units or cards are the state's) and gives its
#                  values by the rule (every order, both truth values, every split, every Battlefield)
# A request that is neither a program slot nor an event slot stops D(s) by name: the contract does not show it.
PROGRAM_SLOT_FIELDS = {
    "target / units[] decision_ref": "target_selection - one object",
    "targets.decision_ref": "target_selection - min..max objects",
    "destination.decision_ref": "location_selection",
    "player.decision_ref": "player_selection",
    "modal.decision_ref": "mode_selection - the modal options",
    "unless.decision_ref": "optional_choice",
    "pay_ref": "optional_choice (Core 204.3.b: whether to pay at all)",
    "an instruction's choice (decision_ref, or its default choice:<from>:<chooser>)": "the choice's kind (engine_decisions."
                                                                                       "choice_decision_kind)",
    "spend_buffs decision_ref (or spend_buffs:<player>)": "buff_spend, or card_selection where no Unit has two buffs",
    "choose_option decision_ref": "option_selection - the instruction's options",
    "pay_any_amount decision_ref": "resource_allocation",
    "division_ref": "damage_division",
    "targets.subset_ref": "card_selection (Core 355.11.b)",
    "a finalized trigger's settings": "perform_optional_trigger where the item is optional; pay_trigger_cost where the "
                                      "program has a base cost or chooses something (Deflect, 809.1.c)",
}
EVENT_SLOTS = {"trigger_order_required": "trigger_order", "replacement_decision_required": "replacement",
               "damage_assignment_required": "damage_assignment", "randomization_receipt_required": "chance",
               "location_selection_required": "location_selection", "entry_location_required": "entry_location",
               "optional_choice_required": "seen_banish"}
CONTRACT_CAP = 1 << 16
_ABSENT = object()


class OverCap(Exception):
    pass


def _cap(values: list, what: str) -> list:
    if len(values) > VALUE_CAP:
        raise OverCap(f"{len(values)} values of {what} exceed {VALUE_CAP}")
    return values


def _everything(effect: dict[str, Any]) -> list[str]:
    return sorted(effect.get("objects") or {}) + sorted(effect.get("battlefields") or {})


def _locations(effect: dict[str, Any]) -> list[str]:
    return [f"base:{p}" for p in sorted(effect["players"])] + [f"battlefield:{b}" for b in sorted(effect["battlefields"])]


def program_slots(program: dict[str, Any] | None, effect: dict[str, Any], label: str, decider: str | None,
                  item: dict[str, Any] | None) -> list[tuple[str, str, str, list]]:
    """[(decision id, kind, stage, every value)] the program names, read off the program and the state's sets."""
    import engine_decisions as ED
    import trigger_cost as TC
    objects = _everything(effect)
    out: list[tuple[str, str, str, list]] = []
    deciders: dict[str, str | None] = {}
    who = [decider]

    def slot(ref, kind, values):
        if ref not in {s[0] for s in out}:
            out.append((ref, kind, stage_of(label, kind), _cap(values, ref)))
            deciders[ref] = who[0]

    def instruction(effect_):
        op = effect_.get("op")
        if op == "each_player":
            # each player's own copy (Core 355.10.e): its refs suffixed by the player, its choices that player's - as
            # effect_ir.each_player_copies makes them
            players = sorted(effect["players"])
            if effect_.get("players") in {"others", "opponents"}:
                players = [p for p in players if p != decider]
            for player in players:
                who.insert(0, player)
                for copied in IR.each_player_copies(effect_, player):
                    instruction(copied)
                who.pop(0)
            return
        target = effect_.get("target")
        if isinstance(target, dict) and target.get("decision_ref"):
            slot(target["decision_ref"], "target_selection", [[o] for o in objects])
        for unit in effect_.get("units") or []:
            if isinstance(unit, dict) and unit.get("decision_ref"):
                slot(unit["decision_ref"], "target_selection", [[o] for o in objects])
        spec = effect_.get("targets")
        if isinstance(spec, dict):
            if spec.get("decision_ref"):
                slot(spec["decision_ref"], "target_selection", _sets(objects, spec.get("min", 0), spec.get("max")))
            if spec.get("subset_ref"):
                slot(spec["subset_ref"], "card_selection", _sets(objects, 0, None))
        destination = effect_.get("destination")
        if isinstance(destination, dict) and destination.get("decision_ref"):
            slot(destination["decision_ref"], "location_selection", _locations(effect))
        player = effect_.get("player")
        if isinstance(player, dict) and player.get("decision_ref"):
            slot(player["decision_ref"], "player_selection", sorted(effect["players"]))
        unless = effect_.get("unless")
        if isinstance(unless, dict) and unless.get("decision_ref"):
            slot(unless["decision_ref"], "optional_choice", [True, False])
        if effect_.get("pay_ref"):
            slot(effect_["pay_ref"], "optional_choice", [True, False])
        if effect_.get("division_ref"):
            pool = sorted(effect.get("objects") or {})
            amount = effect_.get("amount") or 0
            values = [dict(zip(kept, split)) for keep in range(1, min(len(pool), amount) + 1)
                      for kept in itertools.combinations(pool, keep) for split in _compositions(amount, keep, 1)]
            slot(effect_["division_ref"], "damage_division", values)
        choice = effect_.get("choice")
        if isinstance(choice, dict) and op not in {"spend_buffs"}:
            others = [p for p in effect["players"] if p != decider]
            chooser = {"controller": decider, "opponent": others[0] if others else None}.get(choice.get("by", "controller"),
                                                                                             choice.get("by"))
            who.insert(0, chooser)
            ref = effect_.get("decision_ref") or f"choice:{choice['from']}:{chooser}"
            kind = ED.choice_decision_kind(choice)
            if kind == "player_selection":
                slot(ref, kind, sorted(effect["players"]))
            else:
                form, n = ED.choice_count(choice)
                low, high = {"one": (1, 1), "exactly": (n, n), "up_to": (0, n), "any_number": (0, None), "all": (0, None)}[form]
                ordered = kind == "card_ordering" or choice.get("selection_kind") == "ordered_permutation"
                pool = _everything(effect) if kind == "target_selection" else sorted(effect.get("objects") or {})
                slot(ref, kind, _sets(pool, low, high, ordered=ordered))
            who.pop(0)
        if op == "discard" and choice is None and effect_.get("whole_hand") is not True and isinstance(effect_.get("count"), int):
            # "discard N": its player's choice from their own hand (Core 422.1.a) - the instruction's own default ref
            ref = effect_.get("decision_ref") or f"discard:{effect_.get('player')}"
            slot(ref, "card_selection", _sets(sorted(effect.get("objects") or {}), effect_["count"], effect_["count"]))
        if op == "spend_buffs" and effect_.get("object_id") is None:
            player_id = effect_.get("player")
            ref = effect_.get("decision_ref") or f"spend_buffs:{player_id}"
            units = sorted(o for o, obj in (effect.get("objects") or {}).items() if obj.get("kind") == "unit")
            counts = {u: IR.buff_count(effect["objects"][u]) for u in units}
            if any(n > 1 for n in counts.values()):
                values = [{u: k for u, k in zip(units, split) if k}
                          for split in itertools.product(*[range(counts[u] + 1) for u in units])]
                slot(ref, "buff_spend", values)
            else:
                slot(ref, "card_selection", _sets(units, 0, None))
        if op == "choose_option" and effect_.get("decision_ref"):
            slot(effect_["decision_ref"], "option_selection", list(effect_.get("options") or []))
        if op == "pay_any_amount" and effect_.get("decision_ref"):
            pool = effect["players"][decider]["resources"]["power"] if decider in effect["players"] else {}
            domains = sorted(IR.DOMAINS)
            slot(effect_["decision_ref"], "resource_allocation",
                 [{d: k for d, k in zip(domains, split) if k}
                  for split in itertools.product(*[range(pool.get(d, 0) + 1) for d in domains])])
        if op != "create_delayed_trigger":
            for nested in effect_.get("effects") or []:
                if isinstance(nested, dict):
                    instruction(nested)

    modal = (program or {}).get("modal")
    if modal and label.endswith("trigger"):
        slot(modal["decision_ref"], "mode_selection", [o["option_id"] for o in modal["options"]])
    for effect_ in (program or {}).get("effects") or []:
        instruction(effect_)
    for option in (modal or {}).get("options") or []:
        for effect_ in option.get("effects") or []:
            instruction(effect_)
    if label.endswith("trigger") and item is not None:
        if item.get("optional_at_finalize"):
            out.append(("setting:perform_optional_trigger", "setting", "", [True, False]))
            deciders["setting:perform_optional_trigger"] = decider
        if TC.base_cost(program) is not None or any(s[1] == "target_selection" for s in out):
            out.append(("setting:pay_trigger_cost", "setting", "", [True, False]))
            deciders["setting:pay_trigger_cost"] = decider
        if TC.base_cost(program) is not None:
            units = sorted(o for o, obj in (effect.get("objects") or {}).items() if obj.get("kind") == "unit")
            slot(TC.spend_buff_decision_id(item["id"]), "card_selection", [[u] for u in units])
    return [(ref, kind, stage, values, deciders.get(ref, decider)) for ref, kind, stage, values in out]


def _event_values(request: dict[str, Any], timing: dict[str, Any], effect: dict[str, Any], label: str,
                  decider: str | None) -> tuple[str, list[dict[str, Any]]]:
    """An event slot the procedure named: checked against the state, its values by the rule."""
    code, payload = request["code"], request["payload"]
    ids = request["decision_ids"]

    def entries(kind, values, *, decision_id=None, identities=False):
        return [_answer([{"decision_id": decision_id or ids[0], "stage": stage_of(label, kind), "kind": kind,
                          "controller": decider, "value": v,
                          **({"selection_identities": {o: _identity(effect, o) for o in v}} if identities else {})}])
                for v in values]
    if code == "trigger_order_required":
        sources = set(effect.get("objects") or {}) | set(effect.get("battlefields") or {})
        named = list(payload.get("trigger_ids") or [])
        if any(t.split(":", 1)[0] not in sources and not t.startswith(("delayed", "keyword")) for t in named):
            raise OverCap(f"the abilities {named} the procedure orders are not the state's")
        return "trigger_order", entries("trigger_order", _cap([list(o) for o in itertools.permutations(named)], "an order"))
    if code == "replacement_decision_required":
        rids, events = list(payload.get("replacement_ids") or []), list(payload.get("event_ids") or [])
        if not rids or not events:
            raise OverCap("a replacement event names no replacement or no event")
        ref = f"replacement:{'+'.join(rids)}:{'+'.join(events)}"
        if len(rids) == 1 and len(events) == 1:
            return "replacement_choice", entries("replacement_choice", [{rids[0]: {events[0]: v}} for v in (True, False)],
                                                 decision_id=ref)
        if len(rids) == 1:
            return "replacement_order", entries("replacement_order", [{rids[0]: list(o)} for o in itertools.permutations(events)],
                                                decision_id=ref)
        if len(events) == 1:
            return "replacement_order", entries("replacement_order", [{events[0]: list(o)} for o in itertools.permutations(rids)],
                                                decision_id=ref)
        return "replacement_order", entries("replacement_order", [{decider: list(o)} for o in itertools.permutations(rids)],
                                            decision_id=ref)
    if code == "damage_assignment_required":
        import combat as CB
        record = timing.get("combat") or {}
        role = payload.get("role")
        sides = CB.combat_sides(record, effect)
        opposing = sides["defender" if role == "attacker" else "attacker"]
        available, _ = CB.available_combat_damage(effect, sides[role])
        both = [u for u in opposing if IR.has_keyword(effect, u, "tank") and IR.has_keyword(effect, u, "backline")]
        values = []
        for split in _compositions(available, len(opposing), 0):
            amounts = dict(zip(opposing, split))
            for picks in itertools.product(*[["tank", "backline"] for _ in both]):
                values.append({"amounts": amounts, "requirement_choices": dict(zip(both, picks))} if both else amounts)
        return "damage_assignment", [_answer([{"decision_id": ids[0], "stage": "procedure", "kind": "damage_assignment",
                                               "controller": decider, "value": v,
                                               "selection_identities": {u: _identity(effect, u) for u in (v["amounts"] if "amounts" in v else v)}}])
                                     for v in _cap(values, "damage assignment")]
    if code == "randomization_receipt_required":
        chance = payload.get("chance") or {}
        if not chance or set(chance.get("permute") or []) - set(effect.get("objects") or {}):
            raise OverCap("chance orders cards that are not the state's")
        kind, _, out = answers(request, timing, effect, {"cards": {}}, label)
        return kind, out
    if code == "location_selection_required" and stage_of(label, "location_selection") == "procedure":
        return "location_selection", entries("location_selection", sorted(effect.get("battlefields") or {}))
    if code == "entry_location_required":
        values = [{"kind": "base"}] + [{"kind": "battlefield", "battlefield": b} for b in sorted(effect.get("battlefields") or {})]
        return "entry_location", [_answer(settings={"entry_location": v}) for v in values]
    if code == "optional_choice_required" and str(ids[0]).startswith("seen-banish:"):
        card = ids[0].rsplit(":", 1)[-1]
        if not ((effect.get("objects") or {}).get(card) or {}).get("banish_when_seen"):
            raise OverCap(f"{card!r} has no 'banish when seen' for the procedure to ask about")
        return "optional_choice", entries("optional_choice", [True, False])
    raise OverCap(f"{code} {ids}: the contract does not show this decision ({label})")


def contract_ways(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    """D(s): every combination of the program slots (each also left out), events expanded by the rule, the procedure as
    V; a committed way keeps only the answers the commit needs (one it does not read is no choice)."""
    first = GL.run_procedure(timing, effect, catalogue)
    label = first["label"]
    item = _subject(timing, label)
    program = GL.item_program(catalogue, effect, item) if item else None
    decider = (item or {}).get("controller") or timing.get("turn_player")
    try:
        slots = program_slots(program, effect, label, decider, item)
    except (OverCap, Unproved) as exc:
        return {"status": "over_cap", "reason": str(exc), "ways": []}
    known = {s[0] for s in slots}
    calls = [0]
    ways: dict[str, dict[str, Any]] = {}
    # an identity is the engine's name for an object as it is when chosen (Core 124): the state's, or - for an object
    # the resolution itself moved before the choice (a new object) - the one the procedure's request gives it; only the
    # identity is taken from a request, never its options
    identities = {o: _identity(effect, o) for o in effect.get("objects") or {}}

    def learn(request):
        payload = request["payload"]
        listing = list((payload.get("choice") or {}).get("options") or []) + \
            [o for options in (request.get("private_options") or {}).values() for o in options]
        for o in listing:
            if o.get("identity"):
                identities[o["object_id"]] = o["identity"]

    def run(answer):
        calls[0] += 1
        if calls[0] > CONTRACT_CAP:
            raise OverCap(f"more than {CONTRACT_CAP} calls")
        return _run(timing, effect, catalogue, answer)

    def same(a, b):
        return IR.hash_value(a["next_effect_state"]) == IR.hash_value(b["next_effect_state"]) \
            and GL.RC.state_hash(a["next_timing_state"]) == GL.RC.state_hash(b["next_timing_state"])

    def chase(answer, depth=0):
        """Run one candidate; expand the event slots the procedure names; record what commits."""
        step = run(answer)
        if step["committed"]:
            kept = answer
            for key in list(kept["settings"]):
                trial = copy.deepcopy(kept)
                trial["settings"].pop(key)
                again = run(trial)
                if again["committed"] and same(again, step):
                    kept = trial
            for index in range(len(kept["decisions"]) - 1, -1, -1):
                trial = copy.deepcopy(kept)
                trial["decisions"].pop(index)
                again = run(trial)
                if again["committed"] and same(again, step):
                    kept = trial
            way = {**kept, "label": step["label"]}
            ways.setdefault(way_key(way), way)
            return
        request = step["request"]
        if request is None or depth > 12:
            return
        learn(request)
        named = set(request["decision_ids"])
        setting = SETTING_REQUESTS.get(request["code"])
        if setting and f"setting:{setting}" in known:
            return      # a setting slot this combination leaves out: it asks for it, and is not a way
        if named and named <= known:
            return      # a program slot left out
        if request["code"] in EVENT_SLOTS:
            _, values = _event_values(request, timing, effect, step["label"], request.get("controller") or decider)
            for value in values:
                chase(_plus(answer, value), depth + 1)
            return
        raise OverCap(f"the procedure asks {request['code']} {sorted(named)} ({step['label']}), which the contract does not show")

    try:
        # every slot left out comes first in the product, so a request's identities are learned before any combination
        # that answers it is built (a later slot is asked only once the earlier ones are answered, by a combination
        # that leaves it out)
        for combo in itertools.product(*[[_ABSENT] + list(values) for _, _, _, values, _ in slots]):
            answer = _answer()
            for (slot_id, kind, stage, _, controller), value in zip(slots, combo):
                if value is _ABSENT:
                    continue
                if kind == "setting":
                    answer["settings"][slot_id.split(":", 1)[1]] = value
                    continue
                entry = {"decision_id": slot_id, "stage": stage, "kind": kind, "controller": controller, "value": value}
                if kind in {"target_selection", "card_selection", "card_ordering", "buff_spend", "damage_division"}:
                    entry["selection_identities"] = {o: identities.get(o) or f"{o}@0" for o in value}
                answer["decisions"].append(entry)
            chase(answer)
    except (OverCap, Unproved) as exc:
        return {"status": "over_cap", "reason": str(exc), "ways": [], "calls": calls[0]}
    return {"status": "enumerated", "reason": "ok", "calls": calls[0], "slots": [(s[0], s[1], len(s[3])) for s in slots],
            "ways": [ways[k] for k in sorted(ways)]}


def differential(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    """E(s) (procedure_ways, discovery) against D(s) (contract_ways), way for way."""
    found = procedure_ways(timing, effect, catalogue)
    if found["status"] != "enumerated":
        return {"complete": False, "stopped": f"discovery: {found['reason']}"}
    contract = contract_ways(timing, effect, catalogue)
    if contract["status"] != "enumerated":
        return {"complete": False, "stopped": f"contract: {contract['reason']}"}
    want = {way_key(w): w for w in contract["ways"]}
    got = {way_key(w): w for w in found["ways"]}
    missing = [want[k] for k in sorted(set(want) - set(got))]
    extra = [got[k] for k in sorted(set(got) - set(want))]
    return {"complete": not missing and not extra, "stopped": None, "contract": len(want), "discovered": len(got),
            "missing": missing, "extra": extra, "calls": contract["calls"]}
