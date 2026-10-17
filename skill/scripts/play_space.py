#!/usr/bin/env python3
"""The full play and activation declarations of a state (C2, package 13; GPT 2026-10-15 rulings 1-4).

A declaration is complete when it carries every choice the player makes as the card is played or the ability
activated: where the card is played from and where a permanent enters, which ability, the costs the payer names, the
optional costs taken, the targets, the mode, a Move's destination, how Power is allocated, what pays a selection cost.
The procedure itself - play_transaction.play_card, on a copy - is the only judge:

  skeletons     every play source the player has (hand, Champion Zone, their facedown cards) x every entry location a
                permanent could name, and every catalogued activated ability of the permanents and Legend they control
                x every object a payer-named cost could name
  discovery     each skeleton is played with the decisions made so far; the procedure accepts it (a legal action), refuses
                it (excluded, with its reason), or asks for a decision - and the request carries or implies its domain:
                  target_selection    play_transaction.legal_target_options over the instruction's own selector
                  optional_choice     taken or not
                  mode_selection      the procedure's mode_options
                  card_selection      the procedure's candidates (a printed cost) or the choice it describes (a Discard
                                      or Recycle: the payer's own zone), in the counts it states
                  resource_allocation the procedure's allocation_options
                  location_selection  every Base and every Battlefield
                every value is tried; a request with no domain here, an unreadable selector, or more calls than CALL_CAP
                makes the family's answer unproved, by name - never a partial set offered as the whole
  key           actions are deduplicated by action_space.canonical_action_key (system ids aside)

The catalogue supplies each catalogued object's programs (closed_environment.instantiate_program); an object without a
program plays with none.
"""
from __future__ import annotations

import copy
import itertools
from typing import Any

import action_space as AS
import closed_environment as CE
import effect_ir as IR
import play_transaction as PT
from effect_ir import find_location, hash_value, object_identity, zone_class

DECISIONS_VERSION = "engine-decisions.v1"
STAGE = "play_declaration"
# the requests this module reads a domain for, and the decision kind each answers with
DECIDED = {"target_selection_required": "target_selection", "optional_cost_intent_required": "optional_choice",
           "mode_selection_required": "mode_selection", "card_selection_required": "card_selection",
           "resource_allocation_required": "resource_allocation", "move_destination_required": "location_selection",
           # 2026-10-16 package 14: the three package 13 left by name
           "card_ordering_required": "card_ordering", "trigger_order_required": "trigger_order",
           "randomization_receipt_required": "chance"}
# The closure (GPT ruling 1), gated against the procedure's own constants (check_play_space F6): how each choice field of
# a play declaration is generated, which play sources are a player's to choose, and what each request the procedure can
# make is answered with - or why it is not a choice of a discretionary play
FIELD_GENERATORS = {
    "actor": "the player the enumeration is for",
    "card": "every card of the player's in a source they play from (play_skeletons), every object with a catalogued "
            "ability they control where it works (ability_skeletons)",
    "source": "the hand, the Champion Zone, each Battlefield's facedown zone where the player has a card",
    "entry_location": "the Base and every Battlefield, for a unit or gear",
    "cost": "a catalogued card's printed cost (Core 206; what the state grants or adds the procedure adds) / the ability "
            "row's cost; an object a payer-named cost names: every object on the Board",
    "activation": "every catalogued ability id of the object",
    "payment_context": "the Add window closed: an [Add] is an activate_ability action of its own, taken before the play "
                       "(Core 429.3)",
    "source_permission": None,
}
NOT_DISCRETIONARY = {
    "source_permission": "only a play from the trash or banishment carries one, and only an effect's limited play "
                         "reaches those (Core 419.3): the play's steps are a procedure of that effect's resolution - "
                         "decision_space enumerates them at the limited play's finalization (package 14)",
}
SOURCES = {"hand": "play_skeletons", "champion_zone": "play_skeletons", "facedown": "play_skeletons",
           "trash": "a limited play only (Core 419.3): decision_space, at its finalization",
           "banishment": "a limited play only (Core 419.3): decision_space, at its finalization"}
REQUESTS_LEFT = {
    "add_window_confirmation_required": "never asked: every declaration closes the Add window (payment_context)",
    "discount_order_required": "a catalogued card's cost is its printed one; an order of two discounts that differ is "
                               "declared in cost.discount_order, which a catalogued play does not carry - unproved by "
                               "name if asked",
}
# Chance inside an action (a cost that recycles two or more cards to a Main Deck, Core 416.5) is nature's, not a choice
# of the action: whether the action is legal does not depend on the order, so discovery checks it under the cards'
# own order; the action carries no receipt - whoever applies it supplies the one chance gives (game_loop.run_action)
CHANCE_ORDER = "identity"
# the procedure's calls one family may make for one state; past it the family's answer is unproved (ruling 3)
CALL_CAP = 1 << 15
PLAY_KINDS = ("unit", "gear", "spell")


class Unproved(Exception):
    """A family whose action set this module cannot prove whole for the state."""


def _opponent(state: dict[str, Any], actor: str) -> str:
    others = [p for p in state.get("players") or {} if p != actor]
    if len(others) != 1:
        raise Unproved(f"{len(others)} opponents: the environment is 1v1")
    return others[0]


def _program(catalogue: dict[str, Any] | None, state: dict[str, Any], object_id: str, key: str, actor: str,
             item: str) -> dict[str, Any] | None:
    obj = state["objects"][object_id]
    ref = obj.get("card_ref")
    if catalogue is None or ref is None or key not in ((catalogue["cards"].get(ref) or {}).get("programs") or {}):
        return None
    return CE.instantiate_program(catalogue, ref, key, {"$controller": actor, "$opponent": _opponent(state, actor),
                                                        "$chain_item": item, "$source_object": object_id, "$card": object_id})


def _reads_receipt(program: dict[str, Any] | None) -> bool:
    """A body that reads the play's own cost receipt (Core 356.4.f.1) is bound to it after the play - the play takes no
    program (compile_timing_markers' own play of it)."""
    effects = (program or {}).get("effects") or []
    return any("cost_offer_id" in (e.get("predicate") or {}) for e in effects if isinstance(e, dict))


def _base(play_id: str, actor: str, card: str, item: dict[str, Any], cost: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
            "play_id": play_id, "actor": actor, "card": card, "chain_item": item, "cost": cost,
            "payment_context": {"add_window_closed": True, "confirmed_by": "play_space"}}


def entry_locations(state: dict[str, Any], actor: str) -> list[dict[str, Any]]:
    return [{"kind": "base"}] + [{"kind": "battlefield", "battlefield": bf} for bf in sorted(state.get("battlefields") or {})]


def play_skeletons(state: dict[str, Any], catalogue: dict[str, Any] | None, actor: str) -> list[tuple[dict, dict | None]]:
    """(declaration, program) for every way the player could start playing a card they may play."""
    zones = state["players"][actor]["zones"]
    sources = [(card, {"kind": "hand"}, None) for card in zones.get("hand") or []]
    sources += [(card, {"kind": "champion_zone"}, None) for card in zones.get("champion_zone") or []]
    for bf in sorted(state.get("battlefields") or {}):
        for entry in ((state["battlefields"][bf].get("facedown") or {}).get("cards") or []):
            card = entry.get("object_id")
            if card in state["objects"] and find_location(state, card) == ("facedown", bf, actor):
                sources.append((card, {"kind": "facedown", "battlefield": bf}, "hidden"))
    out = []
    for card, source, timing_source in sources:
        obj = state["objects"][card]
        kind = obj.get("kind")
        if kind not in PLAY_KINDS or not isinstance(obj.get("printed_cost"), dict):
            continue
        item_id = f"item:{card}"
        program = _program(catalogue, state, card, "play", actor, item_id)
        item = {"id": item_id, "object_kind": kind, "timing": obj.get("play_timing", "default")}
        base = _base(f"play:{card}", actor, card, item, {"base": copy.deepcopy(obj["printed_cost"])})
        if source["kind"] != "hand":
            base["source"] = source
        if program is not None:
            base["effect_program_id"] = program["program_id"]
        timings = [timing_source] if timing_source else [None, "ambush"]
        targeting = [None, "restricted", "free_by_restriction"] if source["kind"] == "facedown" and kind == "spell" else [None]
        locations = entry_locations(state, actor) if kind in {"unit", "gear"} else [None]
        for timing, hidden_targeting, location in itertools.product(timings, targeting, locations):
            declaration = copy.deepcopy(base)
            if timing:
                declaration["timing_source"] = timing
            if hidden_targeting:
                declaration["hidden_targeting"] = hidden_targeting
            if location is not None:
                declaration["entry_location"] = location
            out.append((declaration, program))
    return out


def ability_skeletons(state: dict[str, Any], catalogue: dict[str, Any] | None, actor: str) -> list[tuple[dict, dict | None]]:
    """(declaration, program) for every catalogued activated ability of an object the player controls where its abilities
    work, with every object a cost the payer names could name."""
    out = []
    board = sorted(o for o in state["objects"] if zone_class(find_location(state, o)) == "board")
    for object_id in sorted(state["objects"]):
        obj = state["objects"][object_id]
        rows = obj.get("activated_abilities") or {}
        if not rows or obj.get("controller") != actor:
            continue
        where = find_location(state, object_id)
        if not (zone_class(where) == "board" or (where is not None and where[0] == "player" and where[2] == "legend_zone")):
            continue
        for ability_id, row in sorted(rows.items()):
            key = row["effect_program_id"].split("#", 1)[-1]
            item_id = f"item:{ability_id}"
            program = _program(catalogue, state, object_id, key, actor, item_id)
            item = {"id": item_id, "object_kind": "ability", "timing": row.get("timing", "default"),
                    "ability_kind": row.get("ability_kind", "standard")}
            additional = ([{"cost_id": PT.EXHAUST_SELF_COST_ID, "mandatory": True,
                            "payment": {"kind": "exhaust", "object_id": object_id}}] if row["cost"].get("exhaust") else [])
            open_ = []
            for entry in row["cost"].get("additional") or []:
                entry = copy.deepcopy(entry)
                if "object_id" not in entry["payment"] and entry["payment"].get("kind") not in PT.CHOICE_COSTS:
                    open_.append(len(additional))
                additional.append(entry)
            base_cost = {"energy": row["cost"].get("energy", 0), "power": dict(row["cost"].get("power") or {})}
            for named in itertools.product(*([board] * len(open_))):
                cost = {"base": copy.deepcopy(base_cost)}
                paid = copy.deepcopy(additional)
                for index, object_named in zip(open_, named):
                    paid[index]["payment"]["object_id"] = object_named
                if paid:
                    cost["additional"] = paid
                declaration = _base(f"activate:{ability_id}", actor, object_id, item, cost)
                declaration["activation"] = {"source_object": object_id, "ability_id": ability_id}
                declaration["effect_program_id"] = row["effect_program_id"]
                if row.get("activation_conditions"):
                    declaration["activation_conditions"] = copy.deepcopy(row["activation_conditions"])
                out.append((declaration, program))
    return out


def _templates(program: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Every chosen-target selector of the program by its decision ref (a modal program's options' too)."""
    out: dict[str, dict[str, Any]] = {}
    effects = list((program or {}).get("effects") or [])
    for option in ((program or {}).get("modal") or {}).get("options") or []:
        effects += option.get("effects") or []
    for effect in effects:
        if isinstance(effect.get("target"), dict) and effect["target"].get("decision_ref"):
            out.setdefault(effect["target"]["decision_ref"], effect["target"])
        for slot in effect.get("units") or []:
            if isinstance(slot, dict) and slot.get("decision_ref"):
                out.setdefault(slot["decision_ref"], slot)
        spec = effect.get("targets")
        if isinstance(spec, dict) and spec.get("decision_ref"):
            # a bounded number of targets (Core 355.13): each object as its restrictions admit it, as the procedure
            # reads them (play_transaction._check_play_targets), in a count min..max
            restrictions = dict(spec.get("restrictions") or {})
            restrictions.setdefault("chosen_zone_class", "board")
            out.setdefault(spec["decision_ref"], {**restrictions, "_count": (spec.get("min", 0), spec.get("max")),
                                                  "_divided": effect.get("division_ref") is not None})
    return out


def _identity(state: dict[str, Any], object_id: str) -> str:
    return object_identity(state, object_id) or f"{object_id}@0"


def _subsets(items: list[str], form: str, n: int | None) -> list[list[str]]:
    if form in {"one"}:
        sizes = [1]
    elif form == "exactly":
        sizes = [n or 0]
    elif form == "up_to":
        sizes = list(range(0, (n or 0) + 1))
    elif form == "any_number":
        sizes = list(range(0, len(items) + 1))
    else:
        raise Unproved(f"a selection counted {form!r}")
    out = [list(c) for size in sizes for c in itertools.combinations(sorted(items), size)]
    if len(out) > CALL_CAP:
        raise Unproved(f"{len(out)} selections exceed {CALL_CAP}")
    return out


def domain(result: dict[str, Any], state: dict[str, Any], declaration: dict[str, Any], program: dict[str, Any] | None,
           actor: str) -> list[list[dict[str, Any]]]:
    """For each decision the procedure asked for, every entry that could answer it."""
    reason = result["reason_code"]
    kind = DECIDED[reason]
    per_id = []
    for decision_id in result.get("decision_ids") or []:
        entries = []
        if kind == "target_selection":
            template = _templates(program).get(decision_id)
            if template is None:
                raise Unproved(f"target {decision_id!r}: no selector of the program names it")
            selector = {k: v for k, v in template.items() if not k.startswith("_")}
            options = PT.legal_target_options(state, actor, program, selector)
            if "_count" in template:
                low, high = template["_count"]
                high = len(options) if high is None else min(high, len(options))
                chosen_sets = [list(c) for size in range(low, high + 1) for c in itertools.combinations(sorted(options), size)]
                if len(chosen_sets) > CALL_CAP:
                    raise Unproved(f"target {decision_id!r}: {len(chosen_sets)} sets exceed {CALL_CAP}")
            else:
                chosen_sets = [[option] for option in options]
            for chosen in chosen_sets:
                entries.append({"value": chosen, "selection_identities": {o: _identity(state, o) for o in chosen}})
        elif kind == "optional_choice":
            entries = [{"value": True}, {"value": False}]
        elif kind == "mode_selection":
            entries = [{"value": option} for option in result.get("mode_options") or []]
        elif kind == "card_selection":
            if "candidates" in result:
                form, n = next(iter((result.get("selection_count") or {"one": True}).items()))
                pool = list(result["candidates"])
            elif isinstance(result.get("choice"), dict):
                summary = result["choice"]
                form, n = next(iter(summary["count"].items()))
                if summary.get("options") is not None:
                    pool = [o["object_id"] for o in summary["options"]]
                elif summary.get("chooser") == actor and summary["from"] in {"hand", "trash"}:
                    pool = [c for c in state["players"][actor]["zones"][summary["from"]] if c != declaration["card"]]
                else:
                    raise Unproved(f"selection {decision_id!r} from {summary['from']!r} is not the payer's to see")
            else:
                raise Unproved(f"selection {decision_id!r} carries no domain")
            entries = [{"value": chosen, "selection_identities": {c: _identity(state, c) for c in chosen}}
                       for chosen in _subsets(pool, form, n if isinstance(n, int) and not isinstance(n, bool) else None)]
        elif kind == "resource_allocation":
            if "allocation_options" not in result:
                raise Unproved(f"allocation {decision_id!r} carries no domain")
            entries = [{"value": dict(option)} for option in result["allocation_options"]]
        elif kind == "location_selection":
            entries = [{"value": f"base:{p}"} for p in sorted(state["players"])] + \
                      [{"value": f"battlefield:{bf}"} for bf in sorted(state.get("battlefields") or {})]
        elif kind == "trigger_order":
            # Core 383.3.d: every order of the abilities the play's costs triggered together
            per_id.append([{"decision_id": decision_id, "stage": "resolution", "kind": kind, "controller": actor,
                            "value": list(order)} for order in itertools.permutations(result.get("trigger_ids") or [])])
            continue
        elif kind == "card_ordering":
            listing = (result.get("choice") or {}).get("options") or (result.get("_private_options") or {}).get(decision_id)
            if listing is None:
                raise Unproved(f"ordering {decision_id!r} carries no cards")
            bound = {o["object_id"]: o.get("identity") or _identity(state, o["object_id"]) for o in listing}
            entries = [{"value": list(order), "selection_identities": {c: bound[c] for c in order}}
                       for order in itertools.permutations(sorted(bound))]
            if len(entries) > CALL_CAP:
                raise Unproved(f"ordering {decision_id!r}: {len(entries)} orders exceed {CALL_CAP}")
        per_id.append([{"decision_id": decision_id, "stage": STAGE, "kind": kind, "controller": actor, **e} for e in entries])
    return per_id


def discover(timing_state: dict[str, Any], state: dict[str, Any], declaration: dict[str, Any],
             program: dict[str, Any] | None, actor: str, budget: list[int]) -> tuple[list[list[dict]], list[str]]:
    """(every decision list with which the procedure accepts the declaration, the reasons it refused the others)."""
    at_play = None if _reads_receipt(program) else program
    accepted, refused = [], []
    # each branch with its own receipts: what chance orders depends on what was chosen before it
    stack: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = [([], [])]
    while stack:
        decisions, receipts = stack.pop()
        budget[0] += 1
        if budget[0] > CALL_CAP:
            raise Unproved(f"more than {CALL_CAP} calls of the procedure")
        envelope = ({"schema_version": DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": decisions,
                     **({"randomization_receipts": list(receipts)} if receipts else {})}
                    if decisions or receipts else None)
        try:
            with IR.recording_private_options() as private:
                got = PT.play_card(timing_state, state, declaration, engine_decisions=envelope, effect_program=at_play)
            if private:
                got = {**got, "_private_options": dict(private)}    # the trusted record, local to this module
        except Exception as exc:  # noqa: BLE001 - a crash is never a refusal
            raise Unproved(f"the procedure failed on {declaration['play_id']}: {type(exc).__name__}: {exc}") from exc
        if got.get("committed"):
            accepted.append(decisions)
            continue
        reason = got.get("reason_code") or "refused"
        if reason in DECIDED and got.get("decision_controller") not in (None, actor):
            # a choice another player makes as this one plays (ruling 5): not this player's to enumerate
            raise Unproved(f"{declaration['play_id']}: {reason} is {got['decision_controller']}'s to decide")
        if reason in DECIDED and DECIDED[reason] == "chance":
            chance = got.get("chance")
            if not isinstance(chance, dict) or any(r["operation_id"] == chance["operation_id"] for r in receipts):
                raise Unproved(f"{declaration['play_id']}: chance with no operation, or asked again")
            stack.append((decisions, receipts + [{
                "schema_version": "randomization-receipt.v1", "receipt_id": f"play_space:{chance['operation_id']}",
                "operation": chance["operation"], "operation_id": chance["operation_id"], "player": chance["player"],
                "permutation": list(chance["permute"]), "provenance": {"provider": "play_space", "method": CHANCE_ORDER}}]))
            continue
        if reason in DECIDED:
            per_id = domain(got, state, declaration, program, actor)
            if any(not entries for entries in per_id):
                refused.append(f"no_legal_{DECIDED[reason]}")     # a choice with nothing legal to choose (Core 355.8)
            for combination in itertools.product(*per_id):
                stack.append((decisions + list(combination), receipts))
        elif reason in PT.DECISION_REASONS or got.get("unsupported"):
            raise Unproved(f"{declaration['play_id']}: {reason} ({(got.get('reason') or '')[:120]})")
        else:
            refused.append(reason)
    return accepted, refused


def enumerate_family(family: str, timing_state: dict[str, Any], state: dict[str, Any], actor: str,
                     catalogue: dict[str, Any] | None) -> dict[str, Any]:
    """{status: enumerated | unproved, actions, excluded, reason} for play_card or activate_ability."""
    skeletons = play_skeletons(state, catalogue, actor) if family == "play_card" else ability_skeletons(state, catalogue, actor)
    actions: dict[str, dict[str, Any]] = {}
    excluded: dict[str, list[str]] = {}
    budget = [0]
    try:
        for declaration, program in skeletons:
            accepted, refused = discover(timing_state, state, declaration, program, actor, budget)
            for decisions in accepted:
                action = {"kind": family, "declaration": declaration, "decisions": decisions}
                actions.setdefault(AS.action_key_hash(action), action)
                if len(actions) > CALL_CAP:
                    raise Unproved(f"more than {CALL_CAP} actions")
            if refused and not accepted:
                excluded.setdefault(declaration["card"], []).extend(sorted(set(refused)))
    except Unproved as why:
        return {"family": family, "status": "unproved", "reason": str(why), "actions": [], "excluded": {}}
    return {"family": family, "status": "enumerated", "reason": "ok", "calls": budget[0],
            "actions": [actions[k] for k in sorted(actions)], "excluded": {k: sorted(set(v)) for k, v in excluded.items()}}
