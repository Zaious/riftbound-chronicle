#!/usr/bin/env python3
"""The action space of the closed environment (C2, package 13; GPT 2026-10-15 rulings 1, 2 and 6).

Three things the completeness proof stands on, each closed and gated (check_action_space.py):

  ACTION_KINDS   every discretionary action the Core defines, with the enumerator family that produces it; the game
                 actions a player only takes when instructed (Limited Actions) named as such. A family the
                 enumerator has and this table does not - or the other way round - fails the gate.
  FIELD_CLASSES  every field each declaration validator accepts, classified: a choice the player makes (part of the
                 canonical action key), a value derived from those choices, or a system field (ids, schema, provenance).
                 A validator field this table does not classify fails the gate, so no declaration field can carry a
                 choice the action space never generates.
  canonical_action_key
                 what makes two actions different (ruling 2): any rule-meaningful choice - source, card, target, mode,
                 destination, additional cost taken, payment allocation - and never a system field. Changing play_id,
                 chain_item.id, a decision id's play prefix, an identity token or a provenance note yields the same key,
                 so the action space of a state is finite.

Rule locators use the 2026-07-16 numbering (RULE_NUMBERING): discretionary actions 410.1, limited actions 410.2, Play
419.2, the Standard Move 420.3, Hide 421.2, activated abilities 377, Priority and Focus 312-313, ending the turn 316.9.
"""
from __future__ import annotations

import copy
from typing import Any

# --------------------------------------------------------------------------------------------- the kinds of action
ACTION_KINDS: dict[str, dict[str, Any]] = {
    "play_card": {"declaration": "play", "rule_locators": ["Core 410.1", "Core 419.1", "Core 419.2"]},
    "activate_ability": {"declaration": "play", "rule_locators": ["Core 410.1", "Core 377", "Core 377.3"]},
    "standard_move": {"declaration": "standard_move", "rule_locators": ["Core 410.1", "Core 420.3"]},
    "hide": {"declaration": "hide", "rule_locators": ["Core 410.1", "Core 421.2", "Core 811.1"]},
    "pass_priority": {"declaration": None, "rule_locators": ["Core 312", "Core 338.1.b", "Core 339"]},
    "pass_focus": {"declaration": None, "rule_locators": ["Core 313", "Core 347.2"]},
    "end_main_phase": {"declaration": None, "rule_locators": ["Core 305", "Core 316.9"]},
}
# The game actions of 413-444 a player takes only when a spell, an ability or the turn's progression instructs it
# (Core 410.2) - never at will, so no enumerator family. Play (419), Move (420, the Standard Move) and Hide (421) are
# the discretionary ones above; every other kind reaches the action space only as part of a cost or an effect.
LIMITED_ACTIONS = ("draw", "exhaust", "ready", "recycle", "deal", "heal", "discard", "stun", "reveal", "counter", "buff",
                   "banish", "kill", "add", "channel", "burn_out", "double", "swap", "attach", "detach", "predict",
                   "prevent", "replace", "create", "burn", "empower", "disempower", "skip", "pay")

# ----------------------------------------------------------------------------------------- the declaration fields
CHOICE, DERIVED, SYSTEM = "choice", "derived", "system"
FIELD_CLASSES: dict[str, dict[str, str]] = {
    "play": {
        "schema_version": SYSTEM, "ruleset": SYSTEM, "play_id": SYSTEM,
        "actor": CHOICE, "card": CHOICE,
        "effect_program_id": DERIVED,       # the card's or the ability's own program
        "chain_item": DERIVED,               # its id is a system id; kind, timing and ability kind follow the card or
                                             # the ability - a timing narrower than the widest printed one is the same play
        "cost": CHOICE,                      # the additional costs taken and how they are paid
        "payment_context": CHOICE,           # add_window_closed is when the Add window closes; confirmed_by is system
        "entry_location": CHOICE,
        "activation": CHOICE,                # which ability, and what it copies
        "activation_conditions": DERIVED,
        "source": CHOICE,                    # the zone (or facedown battlefield) the card is played from
        "source_permission": CHOICE,         # which permission a play from another zone uses
        "cost_override": DERIVED,            # follows from the permission
        "timing_source": DERIVED,            # the permission cited (ambush, hidden, a limited play) follows from the
                                             # source and the entry location, which are the choices
        "hidden_targeting": DERIVED,
    },
    "standard_move": {
        "schema_version": SYSTEM, "actor": CHOICE, "units": CHOICE, "unit_identities": SYSTEM,
        "destination": CHOICE, "cost_confirmation": SYSTEM,
    },
    "hide": {
        "schema_version": SYSTEM, "ruleset": SYSTEM, "hide_id": SYSTEM, "actor": CHOICE, "card": CHOICE,
        "source": CHOICE, "battlefield": CHOICE, "cost": CHOICE, "payment_context": CHOICE, "cost_basis": CHOICE,
    },
}
# system parts inside a choice field: never part of the key
SUBFIELD_SYSTEM = {("chain_item", "id"), ("payment_context", "confirmed_by")}
# keys inside decisions, costs and payments that are provenance, not a choice
NOTE_KEYS = frozenset({"provenance", "selection_identities", "identity", "identities", "source_page", "note"})


def declaration_fields() -> dict[str, frozenset]:
    """The field set each validator accepts - read from the validators' own constants."""
    import combat
    import hidden
    import play_transaction
    return {"play": play_transaction.PLAY_DECLARATION_FIELDS, "standard_move": combat.STANDARD_MOVE_DECLARATION_FIELDS,
            "hide": hidden.HIDE_DECLARATION_FIELDS}


def _notes_dropped(value: Any) -> Any:
    """`value` with provenance keys dropped, at any depth."""
    if isinstance(value, dict):
        return {k: _notes_dropped(v) for k, v in sorted(value.items()) if k not in NOTE_KEYS}
    if isinstance(value, list):
        return [_notes_dropped(v) for v in value]
    return copy.deepcopy(value)


def _decision_role(decision_id: Any, system_ids: tuple[str, ...]) -> Any:
    """A decision id with this declaration's own ids taken out as whole ':'-separated parts - 'cost:play-7:text-cost'
    and 'cost:play-9:text-cost' are the same role; a part that merely contains the id is left alone."""
    if not isinstance(decision_id, str):
        return decision_id
    return ":".join("@" if part in system_ids else part for part in decision_id.split(":"))


def canonical_action_key(action: dict[str, Any]) -> dict[str, Any]:
    """The rule-meaningful content of an action {kind, declaration?, decisions?} (GPT ruling 2).

    Every CHOICE field is kept (with its system sub-fields and provenance removed); DERIVED and SYSTEM fields are
    dropped. A decision is kept by what it decides - stage, kind, controller and value - with the declaration's own ids
    removed from its id, so the same choice under another play_id is the same action. A set-valued choice (the units
    of one Standard Move, the cards of one selection) is order-free."""
    kind = action["kind"]
    if kind not in ACTION_KINDS:
        raise ValueError(f"{kind!r} is not an action kind")
    shape = ACTION_KINDS[kind]["declaration"]
    declaration = action.get("declaration") or {}
    system_ids = tuple(str(v) for v in (declaration.get("play_id"), declaration.get("hide_id"),
                                         (declaration.get("chain_item") or {}).get("id")) if v)
    key: dict[str, Any] = {"kind": kind}
    if shape is None:
        key["actor"] = action.get("actor")
    else:
        classes = FIELD_CLASSES[shape]
        unknown = sorted(set(declaration) - set(classes))
        if unknown:
            raise ValueError(f"a {shape} declaration carries unclassified fields {unknown}")
        fields = {}
        for name, value in sorted(declaration.items()):
            if classes[name] != CHOICE:
                continue
            if isinstance(value, dict):
                value = {k: v for k, v in value.items() if (name, k) not in SUBFIELD_SYSTEM}
            if name == "units" and isinstance(value, list):
                value = sorted(value)
            fields[name] = _notes_dropped(value)
        key["declaration"] = fields
    decisions = []
    for entry in action.get("decisions") or []:
        value = entry.get("value")
        if entry.get("kind") in {"target_selection", "card_selection"} and isinstance(value, list):
            value = sorted(value)
        decisions.append({"id": _decision_role(entry.get("decision_id"), system_ids), "stage": entry.get("stage"),
                          "kind": entry.get("kind"), "controller": entry.get("controller"),
                          "value": _notes_dropped(value)})
    key["decisions"] = sorted(decisions, key=lambda d: (str(d["id"]), str(d["kind"])))
    return key


def action_key_hash(action: dict[str, Any]) -> str:
    from engine_check import canonical_hash
    return canonical_hash(canonical_action_key(action))


# ------------------------------------------------------------------------------- the differential (GPT ruling 3)
# D(s): every syntactically valid declaration whose fields range over the state's own finite sets - all units (any
# controller, any zone), every destination shape; V: the engine's own procedure. The enumerator must equal the
# declarations V accepts, key for key. A space larger than BROAD_CAP stops the comparison by name: that state's
# proof is false (fail closed), never a partial answer.
BROAD_CAP = 1 << 14


class OverCap(Exception):
    pass


def _subsets(items: list[str]):
    from itertools import combinations
    if (1 << len(items)) - 1 > BROAD_CAP:
        raise OverCap(f"{(1 << len(items)) - 1} sets of {len(items)} objects exceed {BROAD_CAP}")
    for size in range(1, len(items) + 1):
        yield from combinations(items, size)


def _broad_play(family: str, timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str,
                catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    import closed_environment
    import effect_ir
    import play_transaction
    from itertools import product
    opponent = next(p for p in effect_state["players"] if p != actor)
    objects = effect_state.get("objects") or {}
    battlefields = sorted(effect_state.get("battlefields") or {})

    def program(object_id, key, item):
        ref = objects[object_id].get("card_ref")
        if ref is None or key not in ((catalogue["cards"].get(ref) or {}).get("programs") or {}):
            return None
        return closed_environment.instantiate_program(catalogue, ref, key, {
            "$controller": actor, "$opponent": opponent, "$chain_item": item, "$source_object": object_id, "$card": object_id})

    skeletons = []
    ruleset = {"core": effect_ir.CORE_RULESET, "faq_as_of": effect_ir.FAQ_AS_OF}
    for card in sorted(objects):
        obj = objects[card]
        if family == "play_card":
            if not isinstance(obj.get("printed_cost"), dict):
                continue
            item = f"broad-item:{card}"
            prog = program(card, "play", item)
            sources = [{"kind": "hand"}, {"kind": "champion_zone"}] + [{"kind": "facedown", "battlefield": bf} for bf in battlefields]
            locations = [None, {"kind": "base"}] + [{"kind": "battlefield", "battlefield": bf} for bf in battlefields]
            for source, location, timing, targeting in product(sources, locations, [None, "ambush", "hidden"],
                                                               [None, "restricted", "free_by_restriction"]):
                d = {"schema_version": play_transaction.DECLARATION_VERSION, "ruleset": ruleset, "play_id": f"broad:{card}",
                     "actor": actor, "card": card,
                     "chain_item": {"id": item, "object_kind": obj.get("kind"), "timing": obj.get("play_timing", "default")},
                     "cost": {"base": dict(obj["printed_cost"])},
                     "payment_context": {"add_window_closed": True, "confirmed_by": "broad"}}
                if source["kind"] != "hand":
                    d["source"] = source
                for k, v in (("entry_location", location), ("timing_source", timing), ("hidden_targeting", targeting)):
                    if v is not None:
                        d[k] = v
                if prog is not None:
                    d["effect_program_id"] = prog["program_id"]
                skeletons.append((d, prog))
        else:
            for ability_id, row in sorted((obj.get("activated_abilities") or {}).items()):
                item = f"broad-item:{ability_id}"
                prog = program(card, row["effect_program_id"].split("#", 1)[-1], item)
                additional = ([{"cost_id": play_transaction.EXHAUST_SELF_COST_ID, "mandatory": True,
                                "payment": {"kind": "exhaust", "object_id": card}}] if row["cost"].get("exhaust") else []) \
                    + [dict(e) for e in row["cost"].get("additional") or []]
                open_ = [i for i, e in enumerate(additional) if "object_id" not in e["payment"]
                         and e["payment"].get("kind") not in play_transaction.CHOICE_COSTS]
                for named in product(*([sorted(objects)] * len(open_))):
                    paid = [{**e, "payment": dict(e["payment"])} for e in additional]
                    for index, object_id in zip(open_, named):
                        paid[index]["payment"]["object_id"] = object_id
                    d = {"schema_version": play_transaction.DECLARATION_VERSION, "ruleset": ruleset,
                         "play_id": f"broad:{ability_id}", "actor": actor, "card": card,
                         "chain_item": {"id": item, "object_kind": "ability", "timing": row.get("timing", "default"),
                                        "ability_kind": row.get("ability_kind", "standard")},
                         "activation": {"source_object": card, "ability_id": ability_id},
                         "cost": {"base": {"energy": row["cost"].get("energy", 0), "power": dict(row["cost"].get("power") or {})},
                                  **({"additional": paid} if paid else {})},
                         "effect_program_id": row["effect_program_id"],
                         "payment_context": {"add_window_closed": True, "confirmed_by": "broad"}}
                    if row.get("activation_conditions"):
                        d["activation_conditions"] = [dict(c) for c in row["activation_conditions"]]
                    skeletons.append((d, prog))
    out, calls = [], [0]

    def play(declaration, prog, decisions):
        calls[0] += 1
        if calls[0] > PLAY_BROAD_CAP:
            raise OverCap(f"more than {PLAY_BROAD_CAP} calls")
        at_play = None if any("cost_offer_id" in (e.get("predicate") or {}) for e in (prog or {}).get("effects") or []) else prog
        envelope = ({"schema_version": "engine-decisions.v1", "input_hash": effect_ir.hash_value(effect_state),
                     "decisions": decisions} if decisions else None)
        return play_transaction.play_card(timing_state, effect_state, declaration, engine_decisions=envelope, effect_program=at_play)

    for declaration, prog in skeletons:
        bare = play(declaration, prog, [])
        stages = contract_slots(declaration, prog, effect_state, actor)
        known = {slot[0] for stage in stages.values() for slot in stage} | {slot[0] for slot in stages.get(None, [])}
        if not bare.get("committed") and bare.get("reason_code") not in play_transaction.DECISION_REASONS \
                and bare.get("reason_code") not in CONTRACT_REQUESTS:
            continue        # the skeleton itself is refused before any choice (its source, timing or location)
        for mode, slots in stages.items():
            for values in product(*[[_ABSENT] + list(v) for _, _, v in slots]):
                decisions = [_entry(slot_id, kind, value, actor, effect_state)
                             for (slot_id, kind, _), value in zip(slots, values) if value is not _ABSENT]
                got = play(declaration, prog, decisions)
                asked = set(got.get("decision_ids") or []) if got.get("reason_code") in CONTRACT_REQUESTS else set()
                if asked - known:
                    raise OverCap(f"the procedure asks {sorted(asked - known)} for {declaration['play_id']}, which the "
                                  f"contract does not show")
                if not got.get("committed"):
                    continue
                # a decision the procedure does not need (forced, or not read) is no choice: dropped when the commit
                # without it is the same state
                kept = list(decisions)
                for entry in list(decisions):
                    trial = [d for d in kept if d is not entry]
                    again = play(declaration, prog, trial)
                    if again.get("committed") and again.get("next_effect_state_hash") == got.get("next_effect_state_hash"):
                        kept = trial
                out.append({"kind": family, "declaration": declaration, "decisions": kept})
    return out


_ABSENT = object()
PLAY_BROAD_CAP = 1 << 17
# the requests the contract slots answer (the procedure's names for them)
CONTRACT_REQUESTS = {"target_selection_required", "optional_cost_intent_required", "mode_selection_required",
                     "card_selection_required", "resource_allocation_required", "move_destination_required"}


def _entry(slot_id: str, kind: str, value: Any, actor: str, effect_state: dict[str, Any]) -> dict[str, Any]:
    import effect_ir
    entry = {"decision_id": slot_id, "stage": "play_declaration", "kind": kind, "controller": actor, "value": value}
    if kind in {"target_selection", "card_selection"}:
        entry["selection_identities"] = {o: effect_ir.object_identity(effect_state, o) or f"{o}@0" for o in value}
    return entry


def _sets(items: list[str], low: int, high: int) -> list[list[str]]:
    from itertools import combinations
    out = [list(c) for size in range(low, min(high, len(items)) + 1) for c in combinations(sorted(items), size)]
    if len(out) > BROAD_CAP:
        raise OverCap(f"{len(out)} sets exceed {BROAD_CAP}")
    return out


def contract_slots(declaration: dict[str, Any], program: dict[str, Any] | None, effect_state: dict[str, Any],
                   actor: str) -> dict[Any, list[tuple[str, str, list]]]:
    """{mode: [(decision id, kind, every value)]} - the choice slots of one skeleton, read off its object, its declaration
    and its program (the decision ids are the declaration contract's names); a mode's slots are its own instructions'
    and the costs'."""
    import play_transaction
    from itertools import product
    play_id = declaration["play_id"]
    objects = sorted(effect_state.get("objects") or {})
    everything = objects + sorted(effect_state.get("battlefields") or {})
    obj = (effect_state.get("objects") or {}).get(declaration["card"]) or {}
    ability = declaration["chain_item"]["object_kind"] == "ability"
    costs: list[tuple[str, str, list]] = []
    if not ability:
        if "accelerate" in (obj.get("keywords") or []):
            costs.append(("accelerate", "optional_choice", [True, False]))
        for offer in obj.get("optional_additional_costs") or []:
            costs.append((f"{play_transaction.CARD_SELF_OFFER_PREFIX}:{offer['cost_offer_id']}", "optional_choice", [True, False]))
        for offer in obj.get("printed_additional_costs") or []:
            prefix = play_transaction.PRINTED_COST_PREFIX if offer["mandatory"] else play_transaction.CARD_SELF_OFFER_PREFIX
            cost_id = f"{prefix}:{offer['cost_offer_id']}"
            if not offer["mandatory"]:
                costs.append((cost_id, "optional_choice", [True, False]))
            many = offer["payment"].get("any_number") is True
            costs.append((play_transaction.printed_cost_decision_id(play_id, cost_id), "card_selection",
                          _sets(objects, 0, len(objects) if many else 2)))
    zones = effect_state["players"][actor]["zones"]
    for entry in (declaration.get("cost") or {}).get("additional") or []:
        payment = entry.get("payment") or {}
        if payment.get("kind") in play_transaction.CHOICE_COSTS:
            pool = zones.get("hand" if payment["kind"] == "discard" else "trash") or []
            costs.append((f"cost:{play_id}:{entry['cost_id']}", "card_selection", _sets(pool, 0, payment["amount"] + 1)))
    # how Power is allocated - a slot only where the contract makes one: Universal Power in the pool (its general
    # amount or a restricted entry, Core 135.2.e.5.b), or an any-Domain Power cost (a power_any payment; Accelerate on a
    # card with no Domain) - each with every split of what could be paid
    resources = effect_state["players"][actor]["resources"]
    power = resources.get("power") or {}
    universal = int(resources.get("universal_power") or 0) + sum(
        int(r.get("amount") or 0) for r in resources.get("restricted") or [] if isinstance(r, dict))
    any_amounts = [int((e.get("payment") or {}).get("amount") or 0) for e in (declaration.get("cost") or {}).get("additional") or []
                   if (e.get("payment") or {}).get("kind") == "power_any"]
    any_amounts += [int((o.get("payment") or {}).get("amount") or 0)
                    for o in (obj.get("printed_additional_costs") or []) + (obj.get("optional_additional_costs") or [])
                    if (o.get("payment") or {}).get("kind") == "power_any"]
    if not ability and "accelerate" in (obj.get("keywords") or []) and not obj.get("domains"):
        any_amounts.append(play_transaction.ACCELERATE_POWER)
    if universal:
        keys = sorted(power) + ["any"]
        splits = [dict(zip(keys, split)) for split in product(*[range(universal + 1) for _ in keys]) if 0 < sum(split) <= universal]
        costs.append((f"universal_power:{play_id}", "resource_allocation", splits))
    if any(any_amounts):
        top = max(any_amounts)
        domains = sorted(power)
        splits = [dict(zip(domains, split)) for split in product(*[range(min(power[d], top) + 1) for d in domains])
                  if 0 < sum(split) <= top]
        costs.append((f"power_any:{play_id}", "resource_allocation", splits))

    def effect_slots(effects):
        out = []
        for effect in effects:
            target = effect.get("target")
            if isinstance(target, dict) and target.get("decision_ref"):
                out.append((target["decision_ref"], "target_selection", _sets(everything, 0, 2)))
            for slot in effect.get("units") or []:
                if isinstance(slot, dict) and slot.get("decision_ref"):
                    out.append((slot["decision_ref"], "target_selection", _sets(everything, 0, 2)))
            spec = effect.get("targets")
            if isinstance(spec, dict) and spec.get("decision_ref"):
                out.append((spec["decision_ref"], "target_selection",
                            _sets(everything, 0, spec.get("max", len(everything)) + 1)))
            destination = effect.get("destination")
            if isinstance(destination, dict) and destination.get("decision_ref"):
                out.append((destination["decision_ref"], "location_selection",
                            [f"base:{p}" for p in sorted(effect_state["players"])]
                            + [f"battlefield:{bf}" for bf in sorted(effect_state.get("battlefields") or {})]))
        seen, unique = set(), []
        for slot in out:
            if slot[0] not in seen:
                seen.add(slot[0])
                unique.append(slot)
        return unique

    modal = (program or {}).get("modal")
    if not modal:
        return {None: effect_slots((program or {}).get("effects") or []) + costs}
    return {option["option_id"]: [(modal["decision_ref"], "mode_selection", [option["option_id"]])]
            + effect_slots(option.get("effects") or []) + costs for option in modal["options"]}


def broad_actions(family: str, timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str,
                  catalogue: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """D(s) for one family: a superset of what the procedure could accept, built from the state's sets alone."""
    import combat
    import effect_ir
    if family in {"play_card", "activate_ability"}:
        if catalogue is None:
            raise ValueError(f"{family}'s broad space reads the catalogue's programs")
        return _broad_play(family, timing_state, effect_state, actor, catalogue)
    if family == "standard_move":
        # built here from the declaration's own shape - never from the enumerator's helpers, so a value the enumerator
        # forgets is still in D(s): every unit object, every destination the validator's shape admits
        units = sorted(o for o, obj in (effect_state.get("objects") or {}).items() if obj.get("kind") == "unit")
        destinations = [{"kind": "base"}] + [{"kind": "battlefield", "battlefield": bf}
                                              for bf in sorted(effect_state.get("battlefields") or {})]
        return [{"kind": family, "declaration": {
                    "schema_version": combat.STANDARD_MOVE_DECLARATION_VERSION, "actor": actor, "units": list(group),
                    "unit_identities": {u: effect_ir.object_identity(effect_state, u) or f"{u}@0" for u in group},
                    "destination": dict(d), "cost_confirmation": {"exhaust_confirmed": True}}}
                for d in destinations for group in _subsets(units)]
    if family == "hide":
        # every object, from each source the shape admits, at every Battlefield, for every base-only cost a Hide could
        # be taken for: [A] as each Domain, nothing, or an Energy amount any object in the state names as a Hide
        # alternative (the procedure refuses any other cost shape outright - check_hidden)
        import hidden
        costs = [({"energy": 0, "power": {d: 1}}, None) for d in effect_ir.DOMAINS] + [({"energy": 0, "power": {}}, None),
                                                                                         ({"energy": 0, "power": {}}, "ignoring_costs")]
        amounts = {obj.get(hidden.HIDE_ALTERNATIVE_FIELD) for obj in (effect_state.get("objects") or {}).values()} - {None}
        costs += [({"energy": n, "power": {}}, "alternative_energy") for n in sorted(amounts)]
        out = []
        for card in sorted(effect_state.get("objects") or {}):
            for source in sorted(hidden.HIDE_SOURCES):
                for bf in sorted(effect_state.get("battlefields") or {}):
                    for base, basis in costs:
                        out.append({"kind": family, "declaration": {
                            "schema_version": hidden.HIDE_DECLARATION_VERSION,
                            "ruleset": {"core": effect_ir.CORE_RULESET, "faq_as_of": effect_ir.FAQ_AS_OF},
                            "hide_id": f"broad:{card}:{bf}", "actor": actor, "card": card, "source": source,
                            "battlefield": bf, "cost": {"base": dict(base)}, **({"cost_basis": basis} if basis else {}),
                            "payment_context": {"add_window_closed": True, "confirmed_by": "broad"}}})
        if len(out) > BROAD_CAP:
            raise OverCap(f"{len(out)} hide declarations exceed {BROAD_CAP}")
        return out
    if family in {"pass_priority", "pass_focus", "end_main_phase"}:
        return [{"kind": family, "actor": actor}]
    raise ValueError(f"no broad declaration space for {family!r} yet")


def accepts(family: str, timing_state: dict[str, Any], effect_state: dict[str, Any], action: dict[str, Any]) -> bool:
    """V: whether the engine's own procedure takes this action."""
    import combat
    import rules_core
    if family == "standard_move":
        return combat.standard_move(timing_state, effect_state, action["declaration"]).get("committed") is True
    if family == "hide":
        import hidden
        return hidden.hide_card(timing_state, effect_state, action["declaration"]).get("committed") is True
    if family in {"pass_priority", "pass_focus", "end_main_phase"}:
        return rules_core.validate_timing(timing_state, {"actor": action["actor"], "kind": family,
                                                         "timing": "default"}).get("legal") is True
    raise ValueError(f"no acceptance check for {family!r} yet")


def enumerated_actions(result: dict[str, Any], family: str) -> list[dict[str, Any]]:
    """The enumerator's actions of one family, as {kind, declaration?, actor?}."""
    out = []
    for item in result["enumeration"]["actions"]:
        if item["family"] != family:
            continue
        action = item["action"]
        out.append({"kind": family, "declaration": action["declaration"],
                    **({"decisions": action["decisions"]} if "decisions" in action else {})} if "declaration" in action
                   else {"kind": family, "actor": action["actor"]})
    return out


def differential(family: str, timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str,
                 result: dict[str, Any], catalogue: dict[str, Any] | None = None) -> dict[str, Any]:
    """E(s) against {d in D(s) : V(s, d)} for one family of one enumeration result."""
    record = next((f for f in result["enumeration"]["families"] if f["family"] == family), None)
    if record is None or record["status"] != "enumerated":
        return {"family": family, "complete": False, "stopped": f"enumerator: {(record or {}).get('reason_code')}"}
    try:
        broad = broad_actions(family, timing_state, effect_state, actor, catalogue)
    except OverCap as exc:
        return {"family": family, "complete": False, "stopped": f"over_cap: {exc}"}
    if family in {"play_card", "activate_ability"}:
        want = {action_key_hash(a): a for a in broad}       # D(s) here holds only what the procedure committed
    else:
        want = {action_key_hash(a): a for a in broad if accepts(family, timing_state, effect_state, a)}
    got = {action_key_hash(a): a for a in enumerated_actions(result, family)}
    missing = [canonical_action_key(want[k]) for k in sorted(set(want) - set(got))]
    extra = [canonical_action_key(got[k]) for k in sorted(set(got) - set(want))]
    return {"family": family, "complete": not missing and not extra, "stopped": None, "broad": len(broad),
            "accepted": len(want), "enumerated": len(got), "missing": missing, "extra": extra}
