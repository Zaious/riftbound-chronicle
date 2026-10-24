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
    "location_selection_required": "location_selection: the candidates the request carries (Core 463.1, 323.11 at a "
                                   "procedure: a Battlefield id; a Move or a token's place at resolution: a location)",
    "optional_choice_required": "optional_choice: taken or not",
    "option_selection_required": "option_selection: the options the request carries (the instruction's own)",
    "mode_selection_required": "mode_selection: the mode options the request carries (Core 403.2)",
    "player_selection_required": "player_selection: every player (the procedure refuses one it may not name)",
    "card_selection_required": "card_selection: the options the choice offers - public in its summary; private to its "
                               "chooser, in the trusted record (effect_ir.recording_private_options), never a result - in "
                               "the count it states",
    "card_ordering_required": "card_ordering: every order of every card the choice carries",
    "buff_spend_required": "buff_spend: how many of each Unit's buffs, 0 up to what it has (Core 427.1.b.2, 702.2.b)",
    "target_group_subset_required": "card_selection: every subset of the still-legal targets it carries (Core 355.11.b)",
    "trigger_order_required": "trigger_order: every order of the abilities it names (Core 383.3.d)",
    "replacement_decision_required": "replacement_choice (one replacement, one event: applied or not) or "
                                     "replacement_order (every order of the replacements or events it names, Core 372)",
    "damage_assignment_required": "damage_assignment: every split of the available damage among the opposing Units it "
                                  "carries, with a Tank-or-Backline choice for a Unit that has both (Core 467.2.c)",
    "damage_division_required": "damage_division: every division of the amount among as many of the legal Targets as "
                                "it keeps, each a positive amount (Core 355.14.e-h)",
    "resource_allocation_required": "resource_allocation: every amount of each Domain's Power in the pool, none to all "
                                    "(Core 204.3.a, a 'pay any amount')",
    "trigger_finalize_choice_required": "setting perform_optional_trigger: performed or not (Core 383.3.a)",
    "trigger_cost_choice_required": "setting pay_trigger_cost: paid or not (Core 404.1.b.1, 405.2)",
    "entry_location_required": "setting entry_location: the location candidates it carries (Core 355.2)",
    "randomization_receipt_required": "chance: every permutation of the cards it orders (Core 417.5, 432.2.b)",
    "cost_selection_required": "card_selection: one of the Units it carries spends its buff for the trigger's base cost "
                               "(Core 702.2.b, 405.1)",
}
# a limited play's own requests at its finalization are a play's (Core 420.3.b) - answered as play_space answers them
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


# package 15 (GPT PACKAGE15 ruling 2): the combinations a screening run tries of the slots the procedure asks first, and
# the tries a screened slot's refused members get against the earlier slots' values - past either, the screening is
# unproved by name, never cut short
FILL_CAP = 1 << 8
CONTEXT_CAP = 1 << 10


def settle_screening(run, answer: dict[str, Any], *, fills: dict[str, list], screening: str | None, known: set,
                     depth: int = 0) -> dict[str, Any]:
    """One screening run of a member (contract_ways.screened), carried to where the procedure judges it.

    Chance is answered in its identity order: chance is no one's decision, so a member is judged by what the procedure
    does past it (Stacked Deck: the rest recycled at random after the pick); the step returned says so
    (`screen_chance`), and a member refused on such a path is not taken as refused (screened() names it unproved). A
    setting the slots hold (perform an optional trigger, pay its cost) is taken - the path on which the procedure reads
    the member (Tideturner asks whether to perform before it reads its target). A request for another slot listed in
    full (`fills`: its values) is answered by every combination of its values, counted first - more than FILL_CAP is
    unproved by name - and the member is judged by the first combination the procedure goes on with: one value refused
    is that value's fault, not the member's (Baited Hook asks its pick before its rest; Tideturner its unit, then its
    destinations, of which most are illegal)."""
    chanced = False
    for _ in range(8):
        step = run(answer)
        request = step.get("request") or {}
        asked = [i for i in request.get("decision_ids") or [] if i != screening]
        given = {d["decision_id"] for d in answer["decisions"]}
        if not step["committed"] and fills and asked and all(i in fills and i not in given for i in asked):
            if depth >= 4:
                raise Unproved(f"screening {screening}: the procedure asks {asked} after four slots asked first")
            count = 1
            for i in asked:
                count *= len(fills[i])
            if count > FILL_CAP:
                raise Unproved(f"screening {screening}: {count} combinations of {asked}, asked first, exceed {FILL_CAP}")
            tried = step
            for chosen in itertools.product(*[fills[i] for i in asked]):
                tried = settle_screening(run, _plus(answer, _answer(list(chosen))), fills=fills, screening=screening,
                                         known=known, depth=depth + 1)
                if tried["committed"] or (tried.get("request") is not None
                                          and screening not in ((tried.get("request") or {}).get("decision_ids") or [])):
                    break
            return {**tried, "screen_chance": chanced or tried.get("screen_chance", False)}
        chance = (request.get("payload") or {}).get("chance")
        setting = SETTING_REQUESTS.get(request.get("code"))
        if not step["committed"] and setting and f"setting:{setting}" in known and setting not in answer["settings"]:
            answer = _plus(answer, _answer(settings={setting: True}))
            continue
        if step["committed"] or request.get("code") != "randomization_receipt_required" or not chance:
            return {**step, "screen_chance": chanced}
        chanced = True
        answer = _plus(answer, _answer(receipts=[{
            "schema_version": "randomization-receipt.v1", "receipt_id": f"screen:{chance['operation_id']}",
            "operation": chance["operation"], "operation_id": chance["operation_id"], "player": chance["player"],
            "permutation": list(chance["permute"]), "provenance": dict(RECEIPT_PROVENANCE)}]))
    return {**step, "screen_chance": chanced}


def _identity(state: dict[str, Any], object_id: str) -> str:
    return IR.object_identity(state, object_id) or f"{object_id}@0"


def _sets(items: list[str], low: int, high: int | None, *, ordered: bool = False) -> list[list[str]]:
    import math
    items = sorted(items)
    high = len(items) if high is None else min(high, len(items))
    pick = itertools.permutations if ordered else itertools.combinations
    # 2026-10-18 package 15: counted before any is built - "any number" of a real game's 100-odd objects is 2^100 sets,
    # and building them first exhausted the machine's memory (a corpus game grew to 111 GiB)
    count = sum((math.perm if ordered else math.comb)(len(items), size) for size in range(low, high + 1))
    if count > VALUE_CAP:
        raise Unproved(f"{count} selections exceed {VALUE_CAP}")
    return [list(c) for size in range(low, high + 1) for c in pick(items, size)]


def _orders(items: list, exc=None) -> list[list]:
    """Every order of `items` - counted first (package 15: n! orders are built only when there are few enough)."""
    import math
    if math.factorial(len(items)) > VALUE_CAP:
        raise (exc or Unproved)(f"{math.factorial(len(items))} orders of {len(items)} exceed {VALUE_CAP}")
    return [list(o) for o in itertools.permutations(items)]


def _divisions(pool: list[str], amount: int, keeps: list[int], exc=None) -> list[dict[str, int]]:
    """Every split of `amount` (each part at least 1) over every `keep` of `pool` - counted first (package 15)."""
    import math
    count = sum(math.comb(len(pool), keep) * math.comb(amount - 1, keep - 1) for keep in keeps if 0 < keep <= amount)
    if count > VALUE_CAP:
        raise (exc or Unproved)(f"{count} divisions of {amount} exceed {VALUE_CAP}")
    return [dict(zip(kept, split)) for keep in keeps for kept in itertools.combinations(sorted(pool), keep)
            for split in _compositions(amount, keep, 1)]


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
        # a limited play's choices at its own finalization: the play's (Core 420.3.b) - play_space's domains
        card = ((effect.get("chain_items") or {}).get(item["id"]) or {}).get("card")
        # (found by the package 15 corpus survey: the request's payload carries neither the code nor the ids
        # play_space.domain reads off a play's result - given them as the procedure named them)
        per_id = PS.domain({**payload, "reason_code": code, "decision_ids": ids}, effect, {"card": card}, program, decider)
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
        return "trigger_order", decider, entries("trigger_order", _orders(list(payload["trigger_ids"])))
    if code == "replacement_decision_required":
        rids, events = list(payload.get("replacement_ids") or []), list(payload.get("event_ids") or [])
        if not rids or not events:
            raise Unproved("a replacement request names no replacement or no event")
        # package 15 (found by the corpus survey, seed 109): which decision it is, as the request says (or, where it does
        # not, by its counts) - one controller's sequence order over one event looks like that event's order
        which = replacement_kind(payload, rids, events)
        ref = replacement_ref(which, rids, events, int(payload.get("cleanup_iteration") or 0))
        if which == "choice":
            return "replacement_choice", decider, entries("replacement_choice", [{rids[0]: {events[0]: v}} for v in (True, False)], decision_id=ref)
        if which == "event_order":
            return "replacement_order", decider, entries("replacement_order", [{rids[0]: o} for o in _orders(events)], decision_id=ref)
        if which == "object_order":
            return "replacement_order", decider, entries("replacement_order", [{events[0]: o} for o in _orders(rids)], decision_id=ref)
        # one controller's Replacement Effects in one batch: the controller orders its own sequences (Core 373) - keyed
        # by that controller (effect_ir.perform_lethal_cleanup's sequence order)
        return "replacement_order", decider, entries("replacement_order", [{decider: o} for o in _orders(rids)],
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
        return "damage_division", decider, entries("damage_division", _divisions(legal, amount, [keep]), identities=True)
    if code == "resource_allocation_required":
        pool = effect["players"][decider]["resources"]["power"]
        domains = sorted(d for d, n in pool.items() if n)
        values = [{d: k for d, k in zip(domains, split) if k} for split in itertools.product(*[range(pool[d] + 1) for d in domains])]
        if len(values) > VALUE_CAP:
            raise Unproved(f"{len(values)} allocations exceed {VALUE_CAP}")
        return "resource_allocation", decider, entries("resource_allocation", values)
    raise Unproved(f"{code}: no domain for this request ({label})")


def _signature(request: dict[str, Any]) -> tuple:
    # a Replacement Effect request is told by its kind too (package 15: a controller's sequence order and the order on
    # its one Unit name the same effects and event, and both are asked in one batch)
    return (request["code"], tuple(request["decision_ids"]), request.get("controller"),
            request["payload"].get("replacement_decision"), request["payload"].get("cleanup_iteration"),
            tuple((request["payload"].get("replacement_ids") or [])), tuple((request["payload"].get("event_ids") or [])))


def _explore(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any], start: dict[str, Any],
             budget: list[int], to_chance: bool = False) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
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
        if to_chance and (node := large_chance(step)) is not None:
            # package 15 (GPT PACKAGE15 ruling 6): the branch reaches a large chance node - its prefix, the answers read
            # before it, is a way of the point's pre-chance part
            ways.append({**answer, "label": step["label"], "chance": node})
            continue
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


def large_chance(step: dict[str, Any]) -> dict[str, Any] | None:
    """2026-10-19 package 15 (GPT PACKAGE15 ruling 6): the chance a step stops at, when it orders more outcomes than
    CHANCE_CAP - {operation, operation_id, player, cards (sorted)} - else None. Such a node is where a point's
    pre-chance part ends: the decisions made before it cannot read its outcome (none is given yet), so they are whole
    over every outcome; what comes after it is certified once the outcome is a receipt (action_certificate)."""
    request = step.get("request") or {}
    chance = (request.get("payload") or {}).get("chance")
    if step.get("committed") or request.get("code") != "randomization_receipt_required" or not isinstance(chance, dict):
        return None
    import math
    if math.factorial(len(chance.get("permute") or [])) <= CHANCE_CAP:
        return None
    return {"operation": chance.get("operation"), "operation_id": chance.get("operation_id"),
            "player": chance.get("player"), "cards": sorted(chance.get("permute") or [])}


def replacement_kind(payload: dict[str, Any], rids: list[str], events: list[str]) -> str:
    """Which Replacement Effect decision a request is: as it says (`replacement_decision`), or by its counts where it
    does not - one effect over one event its choice, over several events their order, several over one event that
    event's order, several over several the controller's sequence order."""
    which = payload.get("replacement_decision")
    if which in {"choice", "event_order", "object_order", "sequence_order"}:
        return which
    if len(rids) == 1:
        return "choice" if len(events) == 1 else "event_order"
    return "object_order" if len(events) == 1 else "sequence_order"


def replacement_ref(which: str, rids: list[str], events: list[str], iteration: int = 0) -> str:
    """A Replacement Effect decision's id: its kind, its effects and - except a controller's sequence order, one per
    controller and set of effects in a batch (the engine keys it by the player) - its events; and, for a Cleanup's
    follow-up iteration k, "#cleanup<k>" (engine_decisions.CLEANUP_ITERATION_SUFFIX: that iteration's own decision)."""
    suffix = f"#cleanup{iteration}" if iteration else ""
    if which == "sequence_order":
        return f"replacement:{which}:{'+'.join(rids)}{suffix}"
    return f"replacement:{which}:{'+'.join(rids)}:{'+'.join(events)}{suffix}"


def _minimal_way(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any], way: dict[str, Any]) -> dict[str, Any]:
    """A committed way kept to the answers its commit needs: a setting or decision whose removal commits the same states
    and the same record of what happened (_receipt_of) is dropped - the rule contract_ways applies to D(s)'s ways."""
    def outcome(step):
        return (IR.hash_value(step["next_effect_state"]), GL.RC.state_hash(step["next_timing_state"]), _receipt_of(step))
    base = _run(timing, effect, catalogue, way)
    if not base["committed"]:
        raise Unproved(f"a way of the procedure does not commit again ({base['label']})")
    target = outcome(base)
    kept = {"decisions": list(way["decisions"]), "settings": dict(way["settings"]), "receipts": list(way["receipts"])}
    for key in list(kept["settings"]):
        trial = {**kept, "settings": {k: v for k, v in kept["settings"].items() if k != key}}
        again = _run(timing, effect, catalogue, trial)
        if again["committed"] and outcome(again) == target:
            kept = trial
    for index in range(len(kept["decisions"]) - 1, -1, -1):
        trial = {**kept, "decisions": kept["decisions"][:index] + kept["decisions"][index + 1:]}
        again = _run(timing, effect, catalogue, trial)
        if again["committed"] and outcome(again) == target:
            kept = trial
    return {**way, **kept}


def way_key(way: dict[str, Any]) -> str:
    """A complete way, canonically: its decisions (ids, kinds, deciders, values), settings and chance outcomes."""
    # package 15 (found by the corpus: The Candlelit Sanctum's two looked-at cards, chosen as a set, read back from the
    # chooser's view in the other order): a target or card selection is a set - its members compared in order of id
    def value(d):
        v = d["value"]
        return sorted(v) if d["kind"] in {"target_selection", "card_selection"} and isinstance(v, list) else v
    decisions = sorted(({**{k: d[k] for k in ("decision_id", "stage", "kind", "controller")}, "value": value(d)}
                        for d in way["decisions"]), key=lambda d: (d["decision_id"], d["kind"]))
    receipts = sorted(({"operation_id": r["operation_id"], "permutation": r["permutation"]} for r in way["receipts"]),
                      key=lambda r: r["operation_id"])
    return IR.hash_value({"label": way.get("label"), "decisions": decisions, "settings": way["settings"], "receipts": receipts,
                          **({"chance": way["chance"]} if way.get("chance") else {})})


def procedure_ways(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any],
                   given_receipts: list[dict[str, Any]] | tuple = (), to_chance: bool = False,
                   given_prefix: dict[str, Any] | None = None) -> dict[str, Any]:
    budget = [0]
    start = _answer((given_prefix or {}).get("decisions") or (), (given_prefix or {}).get("settings"), list(given_receipts))
    try:
        ways, refused, met = _explore(timing, effect, catalogue, start, budget, to_chance)
    except Unproved as why:
        return {"schema_version": DECISION_SPACE_VERSION, "status": "unproved", "reason": str(why), "ways": [],
                "refused": [], "requests": [], "calls": budget[0]}
    # every answer of a way is one the procedure asked for and read (asked, it is asked again without it), so a way is
    # its answers as given - kept, as D(s) keeps its ways (contract_ways), to the answers the commit needs: one whose
    # removal commits the same states and trace is no part of it (package 15, found by the corpus: Ahri - Inquisitive's
    # target asked before its cost, the cost then declined - the target no part of what happens)
    try:
        ways = [_minimal_way(timing, effect, catalogue, w) if not w.get("chance") else w for w in ways]
    except Unproved as why:
        return {"schema_version": DECISION_SPACE_VERSION, "status": "unproved", "reason": str(why), "ways": [],
                "refused": [], "requests": [], "calls": budget[0]}
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
    "pay_ref": "optional_choice (Core 204.3.a: whether to pay at all)",
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
               "optional_choice_required": "seen_banish", "card_ordering_required": "card_ordering"}
CONTRACT_CAP = 1 << 16
_ABSENT = object()


class OverCap(Exception):
    pass


def _cap(values: list, what: str) -> list:
    if isinstance(values, SetSpace):
        return values
    if len(values) > VALUE_CAP:
        raise OverCap(f"{len(values)} values of {what} exceed {VALUE_CAP}")
    return values


class SetSpace:
    """Every set of `low`..`high` of `members` (package 15) - a program slot too big to list (every object of a real
    game's state, up to 2^106 sets), screened along the procedure's own path before its values are built
    (_screen_spaces). Never iterated as values."""

    def __init__(self, members: list[str], low: int, high: int | None):
        self.members, self.low = sorted(members), low
        self.high = len(self.members) if high is None else min(high, len(self.members))

    def __iter__(self):
        raise TypeError("a SetSpace is screened (_screen_spaces) before its values are read")

    def __len__(self):
        return VALUE_CAP + 1


def _space(items: list[str], low: int, high: int | None):
    """The sets as a list when there are few enough to try them all, else a SetSpace to screen."""
    import math
    top = len(items) if high is None else min(high, len(items))
    if sum(math.comb(len(items), size) for size in range(low, top + 1)) <= VALUE_CAP:
        return _sets(items, low, high)
    return SetSpace(items, low, high)


def _bound_target_controller(effect: dict[str, Any], item: dict[str, Any] | None, ref: str | None) -> str | None:
    """The controller of the object a play or a trigger's finalization bound to target `ref` (its chain item's record)."""
    if not item or not ref:
        return None
    record = (effect.get("chain_items") or {}).get(item.get("id")) or {}
    for entry in list(record.get("played_targets") or []) + list(record.get("finalized_targets") or []):
        if entry.get("decision_id") == ref and entry.get("value"):
            return ((effect.get("objects") or {}).get(entry["value"][0]) or {}).get("controller")
    return None


def _receipt_of(step: dict[str, Any]) -> str:
    """What a committed procedure did, beside its states: its result without the states, and its Cleanup."""
    result = {k: v for k, v in (step.get("result") or {}).items()
              if k not in {"next_effect_state", "next_timing_state", "next_effect_state_hash", "next_timing_state_hash"}}
    return IR.hash_value({"result": result, "cleanup": step.get("cleanup")})


def _target_templates(program: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """{decision ref: the chosen-target selector naming it} - action_space._slot_templates, the play side's own reading."""
    import action_space as AS
    return AS._slot_templates(program)


def finalization_refs(program: dict[str, Any] | None) -> set[str]:
    """The decisions a play or a trigger's finalization makes (Core 355.5, 383.3), as play_transaction checks them
    there: its instructions' targets (`target`, `units`, a bounded `targets`) and Move destinations, the top-level
    instructions of the program and of each of its modes (_check_play_targets reads no nested one), and its mode."""
    out: set[str] = set()
    modal = (program or {}).get("modal") or {}
    if isinstance(modal.get("decision_ref"), str):
        out.add(modal["decision_ref"])
    for effects in [(program or {}).get("effects") or []] + [o.get("effects") or [] for o in modal.get("options") or []]:
        for effect_ in effects:
            if not isinstance(effect_, dict):
                continue
            for field in ("target", "targets", "destination"):
                value = effect_.get(field)
                if isinstance(value, dict) and isinstance(value.get("decision_ref"), str):
                    out.add(value["decision_ref"])
            for unit in effect_.get("units") or []:
                if isinstance(unit, dict) and isinstance(unit.get("decision_ref"), str):
                    out.add(unit["decision_ref"])
    return out


def _forced_refs(program: dict[str, Any] | None) -> set[str]:
    """The choices the rules make for the player: "all" of them (engine_decisions.choice_count) - no choice at all."""
    import engine_decisions as ED
    out: set[str] = set()

    def walk(effects):
        for effect_ in effects or []:
            if not isinstance(effect_, dict):
                continue
            choice = effect_.get("choice")
            if isinstance(choice, dict) and ED.choice_count(choice)[0] == "all":
                # its own ref, or program_slots' default one (choice:<from>:<chooser>, any chooser)
                out.add(effect_.get("decision_ref") or f"choice:{choice.get('from')}:*")
            walk(effect_.get("effects"))
    walk((program or {}).get("effects"))
    for option in ((program or {}).get("modal") or {}).get("options") or []:
        walk(option.get("effects"))
    return out


def unread_here(slot_id: str, kind: str, label: str, program: dict[str, Any] | None, item: dict[str, Any] | None,
                timing: dict[str, Any], effect: dict[str, Any]) -> str | None:
    """2026-10-19 package 15 (GPT PACKAGE15 ruling 7): why the program's contract says this procedure point does not read
    the slot - or None, when it may. A finalization reads its targets, destinations and mode (finalization_refs), its
    trigger's settings and cost, nothing of its resolution; a resolution does not read a target, destination or mode its
    play or finalization already made (its chain item's record); a choice the rules make ("all") is read nowhere."""
    if kind == "setting":
        return None
    if label.endswith("limited_play"):
        # an effect's play finalized (Core 420.3.b): the play's own choices, its payment among them, are read here
        return None
    forced = _forced_refs(program)
    if slot_id in forced or any(f.endswith(":*") and slot_id.startswith(f[:-1]) for f in forced):
        return "the rules choose all of them"
    fin = finalization_refs(program)
    if label.startswith("finalize"):
        import trigger_cost as TC
        if slot_id in fin or (item is not None and slot_id == TC.spend_buff_decision_id(item.get("id"))):
            return None
        return "a choice of its resolution, made when it resolves"
    if label.startswith("resolve") and slot_id in fin and item is not None:
        record = (effect.get("chain_items") or {}).get(item.get("id")) or {}
        made = {e.get("decision_id") for e in list(record.get("played_targets") or []) + list(record.get("finalized_targets") or [])
                + list(item.get("finalized_targets") or [])}
        if slot_id in made or ((program or {}).get("modal") or {}).get("decision_ref") == slot_id:
            return "made when it was played or finalized"
    return None


def _bound_targets(effect: dict[str, Any], item: dict[str, Any] | None, ref: str | None) -> list[str] | None:
    """The objects a play or a trigger's finalization chose for `ref` (its chain item's record), or None."""
    if not item or not ref:
        return None
    record = (effect.get("chain_items") or {}).get(item.get("id")) or {}
    for entry in list(record.get("played_targets") or []) + list(record.get("finalized_targets") or []) \
            + list(item.get("finalized_targets") or []):
        if entry.get("decision_id") == ref and isinstance(entry.get("value"), list):
            return sorted(entry["value"])
    return None


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
            slot(target["decision_ref"], "target_selection", SetSpace(objects, 1, 1))
        for unit in effect_.get("units") or []:
            if isinstance(unit, dict) and unit.get("decision_ref"):
                slot(unit["decision_ref"], "target_selection", SetSpace(objects, 1, 1))
        spec = effect_.get("targets")
        if isinstance(spec, dict):
            if spec.get("decision_ref"):
                slot(spec["decision_ref"], "target_selection", _space(objects, spec.get("min", 0), spec.get("max")))
            if spec.get("subset_ref"):
                # package 15 (found by the corpus: Fox-Fire): which of its targets are kept (Core 355.11.b) - a subset of
                # the targets the play made (its chain item's record), not of every object
                made = _bound_targets(effect, item, spec.get("decision_ref"))
                slot(spec["subset_ref"], "card_selection", _space(made if made is not None else objects, 0, None))
        destination = effect_.get("destination")
        if isinstance(destination, dict) and destination.get("decision_ref"):
            slot(destination["decision_ref"], "location_selection", _locations(effect))
        player = effect_.get("player")
        if isinstance(player, dict) and player.get("decision_ref"):
            slot(player["decision_ref"], "player_selection", sorted(effect["players"]))
        unless = effect_.get("unless")
        if isinstance(unless, dict) and unless.get("decision_ref"):
            # package 15 (found by the corpus: Shakedown, "unless its controller has you draw 2"): the target's
            # controller chooses the instruction or what replaces it (effect_ir's unless: UNLESS_OPTIONS) - the
            # target the play bound (its chain item's played targets), read off the state
            chooser = _bound_target_controller(effect, item, (effect_.get("target") or {}).get("decision_ref")) or who[0]
            who.insert(0, chooser)
            slot(unless["decision_ref"], "option_selection", list(IR.UNLESS_OPTIONS))
            who.pop(0)
        if effect_.get("pay_ref"):
            slot(effect_["pay_ref"], "optional_choice", [True, False])
        # package 15 (found by the corpus: Stacked Deck): a card looked at put into the hand, or drawn - its player's
        # choice of `count` of them (effect_ir's put_in_hand / draw_it), from what the resolution has looked at by then
        if op in {"put_in_hand", "draw_it"} and effect_.get("decision_ref"):
            count = 1 if op == "draw_it" else int(effect_.get("count", 1))
            slot(effect_["decision_ref"], "card_selection", SetSpace(sorted(effect.get("objects") or {}), count, count))
        # package 15 (found by the corpus: [Vision], Core 817.1.b): Predict - its player recycles any number of the cards
        # looked at (Core 437; effect_ir's predict, its recycle_ref or '<effect id>:recycle'); the rest go back in an order
        # the procedure names (an event slot)
        if op == "predict":
            ref = effect_.get("recycle_ref") or f"{effect_.get('effect_id', 'predict')}:recycle"
            slot(ref, "card_selection", SetSpace(sorted(effect.get("objects") or {}), 0, int(effect_.get("count", 1))))
        # package 15 (found by the corpus: Salvage, Mystic Reversal, Whirlwind): an instruction its player may follow
        optional = effect_.get("optional")
        if isinstance(optional, dict) and optional.get("decision_ref"):
            slot(optional["decision_ref"], "optional_choice", [True, False])
        if effect_.get("division_ref"):
            pool = sorted(effect.get("objects") or {})
            amount = effect_.get("amount") or 0
            slot(effect_["division_ref"], "damage_division",
                 _divisions(pool, amount, list(range(1, min(len(pool), amount) + 1)), exc=OverCap))
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
                slot(ref, kind, _sets(pool, low, high, ordered=ordered) if ordered else _space(pool, low, high))
            who.pop(0)
        if op == "discard" and choice is None and effect_.get("whole_hand") is not True and isinstance(effect_.get("count"), int):
            # "discard N": its player's choice from their own hand (Core 423.1.a) - the instruction's own default ref
            ref = effect_.get("decision_ref") or f"discard:{effect_.get('player')}"
            # package 15 (found by the corpus: Jinx - Demolitionist's "discard 2"): from that player's hand as it is when
            # they discard (Core 423.1.a) - a card drawn earlier in the resolution too - so of the cards they own
            owner = effect_.get("player")
            pool = sorted(o for o, obj in (effect.get("objects") or {}).items() if obj.get("owner") == owner) \
                if owner in effect["players"] else sorted(effect.get("objects") or {})
            slot(ref, "card_selection", _space(pool, effect_["count"], effect_["count"]))
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
                slot(ref, "card_selection", _space(units, 0, None))
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
        return "trigger_order", entries("trigger_order", _orders(named, exc=OverCap))
    if code == "replacement_decision_required":
        rids, events = list(payload.get("replacement_ids") or []), list(payload.get("event_ids") or [])
        if not rids or not events:
            raise OverCap("a replacement event names no replacement or no event")
        # package 15 (found by the corpus survey, seed 109: one controller's two Replacement Effects over one dying
        # Unit - its sequence order and that Unit's order look alike by their counts, and the wrong one was given): the
        # request says which decision it is (effect_ir's replacement batch), and its id says so too - the same
        # Replacement Effects and event may need two of them in one batch
        which = replacement_kind(payload, rids, events)
        ref = replacement_ref(which, rids, events, int(payload.get("cleanup_iteration") or 0))
        if which == "choice" and len(rids) == 1 and len(events) == 1:
            return "replacement_choice", entries("replacement_choice", [{rids[0]: {events[0]: v}} for v in (True, False)],
                                                 decision_id=ref)
        if which == "event_order" and len(rids) == 1:
            return "replacement_order", entries("replacement_order", [{rids[0]: o} for o in _orders(events, exc=OverCap)],
                                                decision_id=ref)
        if which == "object_order" and len(events) == 1:
            return "replacement_order", entries("replacement_order", [{events[0]: o} for o in _orders(rids, exc=OverCap)],
                                                decision_id=ref)
        if which == "sequence_order":
            return "replacement_order", entries("replacement_order", [{decider: o} for o in _orders(rids, exc=OverCap)],
                                                decision_id=ref)
        raise OverCap(f"a replacement request of no known decision ({which!r}, {len(rids)} effects, {len(events)} events)")
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
    if code == "optional_choice_required" and str(ids[0]).startswith("seen-play:"):
        # package 15 (found by D15): a card banished as it was seen may then be played for [A] by its owner - asked of
        # the card the procedure names, which must be one that banishes itself so
        card = ids[0].rsplit(":", 1)[-1]
        if not ((effect.get("objects") or {}).get(card) or {}).get("banish_when_seen"):
            raise OverCap(f"{card!r} has no 'banish when seen' for the procedure to offer a play of")
        return "optional_choice", entries("optional_choice", [True, False])
    if code == "card_ordering_required":
        # package 15 (found by the corpus: The Candlelit Sanctum puts back what it did not recycle, Core 425.2): the
        # cards to order are the ones the resolution left looked at - named by the procedure (the event), every order
        # of them by the rule
        listed = [o["object_id"] for options in (request.get("private_options") or {}).values() for o in options] + \
            [o["object_id"] for o in (payload.get("choice") or {}).get("options") or []]
        if not listed or set(listed) - set(effect.get("objects") or {}):
            raise OverCap(f"the cards {listed} the procedure orders are not the state's")
        return "card_ordering", entries("card_ordering", _orders(sorted(set(listed)), exc=OverCap), identities=True)
    raise OverCap(f"{code} {ids}: the contract does not show this decision ({label})")


def contract_ways(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any],
                  given_receipts: list[dict[str, Any]] | tuple = (), to_chance: bool = False,
                  given_prefix: dict[str, Any] | None = None) -> dict[str, Any]:
    """D(s): every combination of the program slots (each also left out), events expanded by the rule, the procedure as
    V; a committed way keeps only the answers the commit needs (one it does not read is no choice)."""
    first = GL.run_procedure(timing, effect, catalogue)
    label = first["label"]
    item = _subject(timing, label)
    program = GL.item_program(catalogue, effect, item) if item else None
    decider = (item or {}).get("controller") or timing.get("turn_player")
    try:
        slots = program_slots(program, effect, label, decider, item)
        if label == "setup:mulligan":
            # package 15: Core 117.1 - the player whose Mulligan it is sets aside up to two cards of their own hand
            import turn_cycle as TCY
            player = timing["mulligans_pending"][0]
            hand = list(effect["players"][player]["zones"]["hand"])
            slots = [(TCY.mulligan_decision_id(player), "card_selection", "resolution", _sets(hand, 0, 2), player)]
        if label.endswith("limited_play") and item is not None:
            # package 15 (found by the corpus: a card banished as it was seen, played for [A]): an effect's play paid in
            # Power of any Domain (its record's cost basis, Core 809.1.c.1's kind of payment) - every split of that
            # amount over the player's Power, the payer's choice where there is more than one
            import action_space as AS
            basis = (((effect.get("chain_items") or {}).get(item["id"]) or {}).get("limited_play") or {}).get("cost_basis") or {}
            if basis.get("kind") == "for_power_any" and int(basis.get("amount") or 0):
                payer = item.get("controller")
                pool = effect["players"][payer]["resources"].get("power") or {}
                try:
                    splits = AS._power_splits(pool, int(basis["amount"]))
                except AS.OverCap as exc:
                    raise OverCap(str(exc)) from exc
                if len(splits) > 1:
                    slots.append((f"power_any:limited:{item['id']}", "resource_allocation", "play_declaration", splits, payer))
    except (OverCap, Unproved) as exc:
        return {"status": "over_cap", "reason": str(exc), "ways": []}
    known = {s[0] for s in slots}
    calls = [0]
    ways: dict[str, dict[str, Any]] = {}
    # an identity is the engine's name for an object as it is when chosen (Core 124): the state's, or - for an object
    # the resolution itself moved before the choice (a new object) - the one the procedure's request gives it; only the
    # identity is taken from a request, never its options.
    # 2026-10-25 package 17 (found by the R5-P corpus, seed 115: Mystic Poro's Vision with a seen-banish): an identity a
    # request gives is the identity for the choices THAT request asks, and no other - the same card is a new object in
    # another branch (banished as seen, it is <id>@1 when the seen-play asks about it; not banished, it is still <id>@0
    # when Vision's recycle asks), so one map for the whole contract bound the recycle to the banished card's identity
    # and lost the way that keeps it
    identities = {o: _identity(effect, o) for o in effect.get("objects") or {}}
    asked_identities: dict[str, dict[str, str]] = {}

    def learn(request):
        payload = request["payload"]
        listing = list((payload.get("choice") or {}).get("options") or []) + \
            [o for options in (request.get("private_options") or {}).values() for o in options]
        for o in listing:
            if o.get("identity"):
                for decision_id in request.get("decision_ids") or []:
                    asked_identities.setdefault(decision_id, {})[o["object_id"]] = o["identity"]

    def identity_of(slot_id, o):
        return (asked_identities.get(slot_id) or {}).get(o) or identities.get(o) or f"{o}@0"

    def run(answer):
        calls[0] += 1
        if calls[0] > CONTRACT_CAP:
            raise OverCap(f"more than {CONTRACT_CAP} calls")
        return _run(timing, effect, catalogue, answer)

    def same(a, b):
        # package 15 (GPT PACKAGE15 ruling 7): the same result is the same states AND the same record of what the
        # procedure did - its result's trace (each instruction's outcome) and its Cleanup - so a decision that changes
        # only what happened (a no-op chosen, an event) is never taken for one the procedure does not read
        return IR.hash_value(a["next_effect_state"]) == IR.hash_value(b["next_effect_state"]) \
            and GL.RC.state_hash(a["next_timing_state"]) == GL.RC.state_hash(b["next_timing_state"]) \
            and _receipt_of(a) == _receipt_of(b)

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
        node = large_chance(step) if to_chance else None
        if node is not None:
            # package 15 (GPT PACKAGE15 ruling 6): a prefix of the pre-chance part - kept to the answers the run needs to
            # reach this same node (one it reaches without is not read before the chance)
            kept = answer
            for key in list(kept["settings"]):
                trial = copy.deepcopy(kept)
                trial["settings"].pop(key)
                if large_chance(run(trial)) == node:
                    kept = trial
            for index in range(len(kept["decisions"]) - 1, -1, -1):
                trial = copy.deepcopy(kept)
                trial["decisions"].pop(index)
                if large_chance(run(trial)) == node:
                    kept = trial
            way = {**kept, "label": step["label"], "chance": node}
            ways.setdefault(way_key(way), way)
            return
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

    def entry_of(slot_id, kind, stage, controller, value):
        entry = {"decision_id": slot_id, "stage": stage, "kind": kind, "controller": controller, "value": value}
        if kind in {"target_selection", "card_selection", "card_ordering", "buff_spend", "damage_division"}:
            entry["selection_identities"] = {o: identity_of(slot_id, o) for o in value}
        return entry

    def settled(answer, fills=None, screening=None):
        return settle_screening(run, answer, fills=fills or {}, screening=screening, known=known)

    def screened(slots_):
        """2026-10-18 package 15: a SetSpace slot's members tried one at a time along the procedure's path - the
        earlier screened slots holding a value they took; a member the procedure commits with, or answers by asking
        for another decision, is viable; one it refuses, or asks this same slot again for, is not. The slot's values
        are then the sets of its viable members; every other member is a witness (alone, and beside a viable one) -
        a procedure that took a set holding a member it refuses alone would commit a way the discovery does not
        find, and the differential fails."""
        out, witness_of, earlier = [], {}, []
        # the slots listed in full, by their values - what a screening run answers when the procedure asks one first
        fills = {slot_id: [entry_of(slot_id, kind, stage, controller, value) for value in values]
                 for slot_id, kind, stage, values, controller in slots_
                 if not isinstance(values, SetSpace) and values and kind != "setting"}
        for slot_id, kind, stage, values, controller in slots_:
            why = unread_here(slot_id, kind, label, program, item, timing, effect)
            if why:
                # package 15 (GPT PACKAGE15 ruling 7): a slot the program's contract says this point does not read (a
                # resolution's choice at its trigger's finalization, a target the play already made, a choice the rules
                # force) is no choice here, and it is left out. That is checked, not assumed: each value alone must
                # commit as the point does without it (the same states and the same trace), or be refused - a value
                # that commits otherwise is a choice the contract missed, unproved by name
                without = settled(_answer(earlier, receipts=list(given_receipts)), fills, slot_id)
                tried = [[m] for m in values.members] if isinstance(values, SetSpace) else list(values)
                for value in tried:
                    step = settled(_answer(earlier + [entry_of(slot_id, kind, stage, controller, value)],
                                           receipts=list(given_receipts)), fills, slot_id)
                    if step["committed"] and not (without["committed"] and same(step, without)):
                        raise Unproved(f"{slot_id} is not read at {label} by its program ({why}), yet {value} changes "
                                       f"what the procedure does")
                out.append((slot_id, kind, stage, [], controller))
                continue
            if not isinstance(values, SetSpace):
                out.append((slot_id, kind, stage, values, controller))
                continue
            viable, refused = [], []
            with IR.recording_ledger() as met:
                without = settled(_answer(earlier, receipts=list(given_receipts)), fills, slot_id)
            if without["committed"] and slot_id not in {decision_id for _, decision_id in met}:
                # package 15 (GPT PACKAGE15 ruling 7; found by the corpus: The Candlelit Sanctum with an empty deck,
                # Fox-Fire whose targets still meet their group): run without it, the procedure commits and meets no
                # need of this choice - its record (effect_ir.recording_ledger) notes every choice that is not forced
                # before it looks for an answer, so a procedure that stopped asking would still note it. Not read here;
                # checked as a slot the contract leaves out: each member alone commits as without it, or is refused
                for member in values.members:
                    step = settled(_answer(earlier + [entry_of(slot_id, kind, stage, controller, [member])],
                                           receipts=list(given_receipts)), fills, slot_id)
                    if step["committed"] and not same(step, without):
                        raise Unproved(f"{slot_id} is met by no need at {label}, yet {member} changes what the procedure does")
                out.append((slot_id, kind, stage, [], controller))
                continue
            ignored = []
            def takes(context, member):
                step = settled(_answer(context + [entry_of(slot_id, kind, stage, controller, [member])],
                                       receipts=list(given_receipts)), fills, slot_id)
                asked = set((step.get("request") or {}).get("decision_ids") or [])
                return step, step["committed"] or (step.get("request") is not None and slot_id not in asked)
            chanced = []
            members = list(values.members)
            if values.low >= 2:
                # one member alone is never a value of a slot of at least two (found by the corpus: "discard 2") - it
                # cannot be judged one member at a time; unproved by name, never screened to nothing
                raise Unproved(f"screening {slot_id}: a slot of at least {values.low} is not judged one member at a time")
            template = _target_templates(program).get(slot_id) if kind == "target_selection" and program else None
            checked = program
            if template is not None and label.startswith("finalize") and item is not None and item.get("timing") == "triggered":
                # the program the finalization checks a target against (resolution_bridge.finalization_program: its
                # source's identity bound - "here" reads it); refused, the member-by-member screening is used instead
                import resolution_bridge as RB
                checked, refusal = RB.finalization_program(program, item, effect)
                if refusal is not None:
                    template = None
            if template is not None:
                # package 15 (GPT PACKAGE15 rulings 2 and 7; found by the corpus: Tideturner with no friendly unit, its
                # trigger removed - the procedure reads no member, yet the slot is one its finalization makes): a target
                # slot's members the procedure refuses as its choice whatever else is chosen are out - the same test,
                # bound from the state, the program and this selector alone, as action_space's
                # (play_transaction.refused_targets); every other member is a value. With none left the slot has no
                # value here (its refused members stay witnesses)
                out_ = PT.refused_targets(effect, controller, checked, template)
                viable = [m for m in members if m not in out_]
                refused = [m for m in members if m in out_]
                members = []
            for member in members:
                step, took = takes(earlier, member)
                if step["committed"] and without["committed"] and same(step, without):
                    ignored.append(member)
                elif took:
                    viable.append(member)
                else:
                    refused.append(member)
                    if step.get("screen_chance"):
                        chanced.append(member)
            if chanced:
                # refused on a path where chance was answered in one order: another order may take it (GPT PACKAGE15
                # ruling 2) - unproved by name
                raise Unproved(f"screening {slot_id}: {len(chanced)} members refused after chance answered in one order")
            if refused and earlier and template is None:
                # a member refused with the earlier slots holding their first values may be taken with others: each
                # refused member is tried with every combination of the earlier slots' values, counted first - more than
                # CONTEXT_CAP tries is unproved by name, never cut short (GPT PACKAGE15 ruling 2)
                domains = [[v for v in values_ if v not in ([], None)] for sid, _, _, values_, _ in out
                           if sid in {e["decision_id"] for e in earlier}]
                contexts = 1
                for d in domains:
                    contexts *= len(d)
                if contexts * len(refused) > CONTEXT_CAP:
                    raise Unproved(f"screening {slot_id}: {len(refused)} refused members against {contexts} combinations "
                                   f"of the earlier slots exceed {CONTEXT_CAP} tries")
                shapes = {sid: (k, st, c) for sid, k, st, _, c in out}
                ids = [e["decision_id"] for e in earlier]
                for member in list(refused):
                    for combo in itertools.product(*domains):
                        context = [entry_of(sid, shapes[sid][0], shapes[sid][1], shapes[sid][2], value)
                                   for sid, value in zip(ids, combo)]
                        step, took = takes(context, member)
                        if step.get("screen_chance") and not took:
                            raise Unproved(f"screening {slot_id}: {member} refused after chance answered in one order")
                        if took:
                            refused.remove(member)
                            viable.append(member)
                            break
            viable = sorted(viable + ignored)
            sets = _sets(viable, values.low, values.high) if len(viable) >= values.low else []
            out.append((slot_id, kind, stage, sets, controller))
            witness_of[slot_id] = [[u] for u in refused] + ([[viable[0], u] for u in refused] if viable and values.high >= 2 else [])
            if viable:
                earlier.append(entry_of(slot_id, kind, stage, controller, [viable[0]]))
        return out, witness_of

    def combinations_(slots_, witness_of, fixed=frozenset()):
        # each witness with the other slots left out, and with each holding its first value that is not empty (as
        # action_space._combinations_with_witnesses); a slot a given prefix answers is never left out
        yield from itertools.product(*[([] if sid in fixed else [_ABSENT]) + list(values) for sid, _, _, values, _ in slots_])
        filled = [next((v for v in values if v not in ([], None)), _ABSENT) for _, _, _, values, _ in slots_]
        for index, (slot_id, _, _, _, _) in enumerate(slots_):
            for witness in witness_of.get(slot_id) or []:
                alone = [_ABSENT] * len(slots_)
                alone[index] = witness
                yield tuple(alone)
                beside = list(filled)
                beside[index] = witness
                if beside != alone:
                    yield tuple(beside)

    try:
        slots, witness_of = screened(slots)
        if given_prefix:
            # package 15 (GPT PACKAGE15 ruling 6): the ways after a large chance node, given the decisions the game made
            # before it - a slot the prefix answers holds that answer only (never left out); every other slot as before
            fixed = {d["decision_id"]: d["value"] for d in given_prefix.get("decisions") or []}
            fixed.update({f"setting:{k}": v for k, v in (given_prefix.get("settings") or {}).items()})
            slots = [(sid, kind, stage, [fixed[sid]], c) if sid in fixed else (sid, kind, stage, values, c)
                     for sid, kind, stage, values, c in slots]
            missing_ = sorted(set(fixed) - {s[0] for s in slots})
            if missing_:
                raise Unproved(f"the prefix answers {missing_}, which the contract does not show")
            witness_of = {sid: w for sid, w in witness_of.items() if sid not in fixed}
        # every slot left out comes first in the product, so a request's identities are learned before any combination
        # that answers it is built (a later slot is asked only once the earlier ones are answered, by a combination
        # that leaves it out)
        for combo in combinations_(slots, witness_of, fixed=set((given_prefix and {d["decision_id"] for d in given_prefix.get("decisions") or []}
                                                                    | {f"setting:{k}" for k in (given_prefix.get("settings") or {})}) or ())):
            answer = _answer(receipts=list(given_receipts))
            for (slot_id, kind, stage, _, controller), value in zip(slots, combo):
                if value is _ABSENT:
                    continue
                if kind == "setting":
                    answer["settings"][slot_id.split(":", 1)[1]] = value
                    continue
                entry = {"decision_id": slot_id, "stage": stage, "kind": kind, "controller": controller, "value": value}
                if kind in {"target_selection", "card_selection", "card_ordering", "buff_spend", "damage_division"}:
                    entry["selection_identities"] = {o: identity_of(slot_id, o) for o in value}
                answer["decisions"].append(entry)
            chase(answer)
    except (OverCap, Unproved) as exc:
        return {"status": "over_cap", "reason": str(exc), "ways": [], "calls": calls[0]}
    return {"status": "enumerated", "reason": "ok", "calls": calls[0], "slots": [(s[0], s[1], len(s[3])) for s in slots],
            "ways": [ways[k] for k in sorted(ways)]}


LEDGER_KINDS = ("trigger_order", "damage_assignment")


def event_ledger(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any], way: dict[str, Any]) -> list[str]:
    """2026-10-18 package 15 (GPT PACKAGE14 ruling 3): the events of one committed way that need a player's decision,
    read off the transition and the rules - never off the procedure's requests - each held to exactly one decision of
    the way (and no decision of those kinds for an event that needs none). A procedure that stopped asking (ordering
    simultaneous triggers itself, picking one of several legal assignments) leaves a needed event without its decision.

      trigger_order      the abilities this transition puts on the Chain, by batch and controller: two or more of one
                         controller in one batch are ordered by that player (Core 383.3.d) - trigger_order:<batch>:<who>
      damage_assignment  at the Combat Damage Step, each side's player assigns its damage when more than one assignment
                         is legal (Core 467.2.c; combat.validate_assignment counts them) -
                         damage_assignment:<combat>:<role>
      replacement        at a Cleanup, a dying Unit with two or more Replacement Effects that apply, or one optional one
                         (Core 370-374), needs a replacement decision (read off the state before the Cleanup)

    2026-10-19 (GPT PACKAGE15 ruling 3): the events the procedure itself meets as it runs the way - noted where the
    rules make a decision needed, before it looks for one (effect_ir.recording_ledger) - each held to exactly one
    decision of the way, and every decision of their kinds to a note (both ways):

      replacement        a controller's own sequences (Core 373), one Replacement Effect's order of the events it
                         qualifies for, an optional one's choice, the order of several on one event - in every iteration
      card_ordering      a player's order of cards that is not forced (put back, Predict's rest; Core 425.2, 437)
      seen_banish        a card that may banish itself as it is looked at, and play itself after (its printed text)
      entry_location     a Unit an effect plays without naming where: its controller places it (Core 355.2)
      location           two or more Combats or Showdowns staged: the Turn Player picks which opens (Core 463.1, 323.11)

    Returns the problems (empty when the way holds exactly the decisions its events need)."""
    import combat as CB
    with IR.recording_ledger() as notes:
        step = _run(timing, effect, catalogue, way)
    if way.get("chance"):
        # a pre-chance prefix (package 15): it must stop at its chance node, and its events are those met before it
        if large_chance(step) != way["chance"]:
            return [f"the prefix does not reach its chance node ({step['label']})"]
    elif not step["committed"]:
        return [f"the way does not commit ({step['label']})"]
    needed: set[str] = set()
    before = {item["id"] for item in timing["chain"]["items"]}
    groups: dict[tuple, int] = {}
    for item in (step.get("next_timing_state") or {"chain": {"items": []}})["chain"]["items"]:
        if item["id"] in before or item.get("timing") != "triggered":
            continue
        key = (item.get("batch_id"), item.get("controller"))
        groups[key] = groups.get(key, 0) + 1
    needed |= {f"trigger_order:{batch}:{controller}" for (batch, controller), n in groups.items() if n >= 2}
    record = timing.get("combat") or {}
    if step["label"] == "combat:assign" and record.get("status") == "showdown_closed":
        sides = CB.combat_sides(record, effect)
        for role in ("attacker", "defender") if sides["attacker"] and sides["defender"] else ():
            candidates, problem = CB.assignment_candidates(record, effect, role, None)
            if problem is not None or not candidates:
                continue
            available, _ = CB.available_combat_damage(effect, sides[role])
            several = any(len(c.get("requirements") or []) == 2 for c in candidates) or (
                available > 0 and len(candidates) > 1 and CB._legal_assignment_count(candidates, available, {}) != 1)
            if several:
                needed.add(f"damage_assignment:{record['combat_id']}:{role}")
    have = [d["decision_id"] for d in way.get("decisions") or [] if d.get("kind") in LEDGER_KINDS]
    problems = [f"{event} needs one decision and the way has {have.count(event)}" for event in sorted(needed)
                if have.count(event) != 1]
    problems += [f"{d} answers no event that needs a decision" for d in sorted(set(have) - needed)]
    noted: dict[str, set[str]] = {}
    for kind, decision_id in notes:
        noted.setdefault(kind, set()).add(decision_id)
    decisions = way.get("decisions") or []
    held = {
        "replacement": [d["decision_id"] for d in decisions if d.get("kind") in ("replacement_order", "replacement_choice")],
        "card_ordering": [d["decision_id"] for d in decisions if d.get("kind") == "card_ordering"],
        "seen_banish": [d["decision_id"] for d in decisions if d.get("kind") == "optional_choice"
                        and str(d["decision_id"]).startswith(("seen-banish:", "seen-play:"))],
        "location": [d["decision_id"] for d in decisions if d.get("kind") == "location_selection"
                     and d["decision_id"] in (CB.LOCATION_DECISION_ID, "showdown_location")],
        "entry_location": [f"entry_location:{(_subject(timing, step['label']) or {}).get('id')}"]
        if "entry_location" in (way.get("settings") or {}) else [],
    }
    for kind, ids in held.items():
        for decision_id in sorted(noted.get(kind, set())):
            if ids.count(decision_id) != 1:
                problems.append(f"{kind} {decision_id} needs one decision and the way has {ids.count(decision_id)}")
        for decision_id in sorted(set(ids) - noted.get(kind, set())):
            problems.append(f"{kind} {decision_id} answers no event that needs a decision")
    if step["label"] == "task:cleanup":
        lethal = [o for o, obj in (effect.get("objects") or {}).items()
                  if obj.get("kind") == "unit" and IR.find_location(effect, o) is not None
                  and IR.zone_class(IR.find_location(effect, o)) == "board"
                  and obj.get("damage", 0) > 0 and obj["damage"] >= IR.effective_might(effect, o)]
        for o in sorted(lethal):
            event = {"effect_id": f"simultaneous-kill:{o}", "op": "kill", "object_id": o,
                     "kill_mode": "passive_lethal_cleanup", "attributed_sources": []}
            applying = IR._applicable_replacements(effect, event)
            if (len(applying) >= 2 or any(d.get("optional") for d in applying)) and not any(
                    d.get("kind") in ("replacement_order", "replacement_choice") for d in way.get("decisions") or []):
                problems.append(f"the death of {o} has {len(applying)} Replacement Effects that apply and the way decides "
                                f"none of them")
    return problems


def differential(timing: dict[str, Any], effect: dict[str, Any], catalogue: dict[str, Any],
                 given_receipts: list[dict[str, Any]] | tuple = (), to_chance: bool = False,
                 given_prefix: dict[str, Any] | None = None) -> dict[str, Any]:
    """E(s) (procedure_ways, discovery) against D(s) (contract_ways), way for way - and every way of both held to the
    events its transition shows need a decision (event_ledger: exactly one decision each, package 15)."""
    # package 15: `given_receipts` - chance's receipts for operations of more outcomes than CHANCE_CAP, the ones the game
    # really used - make both sides the procedure's ways given those outcomes (a state certified as reached)
    # `to_chance` (GPT PACKAGE15 ruling 6): the point's pre-chance part - every way stopped at a chance node of more
    # outcomes than CHANCE_CAP is its prefix, compared and held to its events like a way
    found = procedure_ways(timing, effect, catalogue, given_receipts, to_chance, given_prefix)
    if found["status"] != "enumerated":
        return {"complete": False, "stopped": f"discovery: {found['reason']}"}
    contract = contract_ways(timing, effect, catalogue, given_receipts, to_chance, given_prefix)
    if contract["status"] != "enumerated":
        return {"complete": False, "stopped": f"contract: {contract['reason']}"}
    want = {way_key(w): w for w in contract["ways"]}
    got = {way_key(w): w for w in found["ways"]}
    missing = [want[k] for k in sorted(set(want) - set(got))]
    extra = [got[k] for k in sorted(set(got) - set(want))]
    ledger = sorted({problem for w in list(want.values()) + list(got.values())
                     for problem in event_ledger(timing, effect, catalogue, w)})
    return {"complete": not missing and not extra and not ledger, "stopped": None, "contract": len(want),
            "discovered": len(got), "missing": missing, "extra": extra, "ledger": ledger, "calls": contract["calls"],
            # the prefixes that stop at a large chance node (to_chance): none, and these are the point's whole ways
            "chance_prefixes": sum(1 for w in list(want.values()) + list(got.values()) if w.get("chance"))}
