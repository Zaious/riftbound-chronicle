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

Rule locators use the 2026-10-09 numbering (RULE_NUMBERING; 2026-07-16 until C3): discretionary actions 411.1, limited actions 411.2, Play
420.2, the Standard Move 421.3, Hide 422.2, activated abilities 377, Priority and Focus 312-313, ending the turn 316.9.
"""
from __future__ import annotations

import copy
from typing import Any

# --------------------------------------------------------------------------------------------- the kinds of action
ACTION_KINDS: dict[str, dict[str, Any]] = {
    "play_card": {"declaration": "play", "rule_locators": ["Core 411.1", "Core 420.1", "Core 420.2"]},
    "activate_ability": {"declaration": "play", "rule_locators": ["Core 411.1", "Core 377", "Core 377.3"]},
    "standard_move": {"declaration": "standard_move", "rule_locators": ["Core 411.1", "Core 421.3"]},
    "hide": {"declaration": "hide", "rule_locators": ["Core 411.1", "Core 422.2", "Core 811.1"]},
    "pass_priority": {"declaration": None, "rule_locators": ["Core 312", "Core 338.1.b", "Core 339"]},
    "pass_focus": {"declaration": None, "rule_locators": ["Core 313", "Core 347.2"]},
    "end_main_phase": {"declaration": None, "rule_locators": ["Core 305", "Core 316.9"]},
}
# The game actions of 414-444 a player takes only when a spell, an ability or the turn's progression instructs it
# (Core 411.2) - never at will, so no enumerator family. Play (420), Move (421, the Standard Move) and Hide (422) are
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
    # package 15 (found by the corpus: a printed cost's decision 'cost:<play id>:...' under play ids that hold a ':'
    # themselves - 'broad:p2c39', 'play:p2c39'): an id is taken out as a whole run of parts, the longest first
    padded = f":{decision_id}:"
    for system_id in sorted({s for s in system_ids if s}, key=len, reverse=True):
        while f":{system_id}:" in padded:
            padded = padded.replace(f":{system_id}:", ":@:")
    return padded[1:-1]


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
        # 2026-10-18 package 15: a Non-Unit Gear enters its controller's Base (Core 359.2.d) - its declaration may name
        # that or name nothing (play_transaction.validate_declaration), one play either way
        if kind == "play_card" and (declaration.get("chain_item") or {}).get("object_kind") == "gear" \
                and "entry_location" not in fields:
            fields["entry_location"] = {"kind": "base"}
        key["declaration"] = fields
    decisions = []
    for entry in action.get("decisions") or []:
        value = entry.get("value")
        if entry.get("kind") in {"target_selection", "card_selection"} and isinstance(value, list):
            value = sorted(value)
        if entry.get("kind") == "resource_allocation" and isinstance(value, dict):
            # package 15 (found by the corpus: the enumerator names every pool at 0, the procedure's own options only
            # the ones it takes from): nothing taken from a pool is no part of the allocation
            value = {k: v for k, v in value.items() if v not in (0, None)}
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
# package 15 (GPT PACKAGE15 ruling 2): the tries a screened slot's refused members get against the other slots' values
# before the screening is unproved by name - never a silent cut
CONTEXT_CAP = 1 << 10


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

    def _kept(declaration, prog, decisions, got):
        # a decision the procedure does not need (forced, or not read) is no choice: dropped when the commit without it
        # is the same state
        kept = list(decisions)
        for entry in list(decisions):
            trial = [d for d in kept if d is not entry]
            again = play(declaration, prog, trial)
            if again.get("committed") and again.get("next_effect_state_hash") == got.get("next_effect_state_hash"):
                kept = trial
        return kept

    def play(declaration, prog, decisions):
        calls[0] += 1
        if calls[0] > PLAY_BROAD_CAP:
            raise OverCap(f"more than {PLAY_BROAD_CAP} calls")
        at_play = None if any("cost_offer_id" in (e.get("predicate") or {}) for e in (prog or {}).get("effects") or []) else prog
        # package 15 (found by the corpus: Garbage Grabber's "Recycle 3 from your trash" puts three cards on the Main
        # Deck's bottom at random, Core 417.5): chance inside an action is nature's, and whether the action is legal does
        # not depend on its order - tried in the cards' identity order, as the discovery tries it (play_space)
        receipts: list = []
        for _ in range(4):
            envelope = ({"schema_version": "engine-decisions.v1", "input_hash": effect_ir.hash_value(effect_state),
                         "decisions": decisions, **({"randomization_receipts": list(receipts)} if receipts else {})}
                        if decisions or receipts else None)
            got = play_transaction.play_card(timing_state, effect_state, declaration, engine_decisions=envelope,
                                             effect_program=at_play)
            chance = got.get("chance")
            if got.get("reason_code") != "randomization_receipt_required" or not isinstance(chance, dict) \
                    or any(r["operation_id"] == chance["operation_id"] for r in receipts):
                return got
            receipts.append({"schema_version": "randomization-receipt.v1", "receipt_id": f"broad:{chance['operation_id']}",
                             "operation": chance["operation"], "operation_id": chance["operation_id"],
                             "player": chance["player"], "permutation": list(chance["permute"]),
                             "provenance": {"provider": "action_space", "method": "identity"}})
        return got

    # package 15: a skeleton whose cost waits for the order of its discounts (Core 356.4.c.1) is tried again with each
    # order declared (cost.discount_order) - the discounts the procedure names, every order of them (an event's values by
    # the rule, as decision_space's event slots); each set of discounts once
    work, ordered = list(skeletons), set()
    while work:
        declaration, prog = work.pop(0)
        bare = play(declaration, prog, [])
        if not bare.get("committed") and bare.get("reason_code") not in play_transaction.DECISION_REASONS \
                and bare.get("reason_code") not in CONTRACT_REQUESTS:
            continue        # the skeleton itself is refused before any choice (its source, timing or location)
        stages = contract_slots(declaration, prog, effect_state, actor)
        known = {slot[0] for stage in stages.values() for slot in stage} | {slot[0] for slot in stages.get(None, [])}
        for mode, slots in stages.items():
            slots, witnesses = _screened_targets(slots, lambda decisions: play(declaration, prog, decisions), actor,
                                                 effect_state, prog)
            for values in _combinations_with_witnesses(slots, witnesses):
                decisions = [_entry(slot_id, kind, value, actor, effect_state)
                             for (slot_id, kind, _), value in zip(slots, values) if value is not _ABSENT]
                got = play(declaration, prog, decisions)
                if got.get("reason_code") == "discount_order_required" and got.get("discount_ids") \
                        and not (declaration.get("cost") or {}).get("discount_order"):
                    key = (declaration["play_id"], effect_ir.hash_value(declaration), tuple(got["discount_ids"]))
                    if key not in ordered:
                        ordered.add(key)
                        import math
                        if math.factorial(len(got["discount_ids"])) > BROAD_CAP:
                            raise OverCap(f"{math.factorial(len(got['discount_ids']))} discount orders exceed {BROAD_CAP}")
                        from itertools import permutations
                        work += [({**declaration, "cost": {**declaration["cost"], "discount_order": list(order)}}, prog)
                                 for order in permutations(got["discount_ids"])]
                asked = set(got.get("decision_ids") or []) if got.get("reason_code") in CONTRACT_REQUESTS else set()
                deflect_id = f"power_any:{declaration['play_id']}"
                if asked == {deflect_id} and deflect_id not in known:
                    # package 15 (found by the corpus: Cleave choosing a Unit with [Deflect]): each time a play chooses an
                    # opposing object with Deflect it costs that much Power of any Domain more (Core 809.1.c-d, 809.2) -
                    # an event of the choices made, named by the procedure; its values by the rule: the Deflect of the
                    # objects these decisions choose, every split of it over the player's Power
                    amount = _deflect_owed(effect_state, actor, decisions)
                    for split in _power_splits(effect_state["players"][actor]["resources"].get("power") or {}, amount):
                        with_split = decisions + [_entry(deflect_id, "resource_allocation", split, actor, effect_state)]
                        paid = play(declaration, prog, with_split)
                        if paid.get("committed"):
                            out.append({"kind": family, "declaration": declaration,
                                        "decisions": _kept(declaration, prog, with_split, paid)})
                    continue
                if asked - known:
                    raise OverCap(f"the procedure asks {sorted(asked - known)} for {declaration['play_id']}, which the "
                                  f"contract does not show")
                if not got.get("committed"):
                    continue
                out.append({"kind": family, "declaration": declaration, "decisions": _kept(declaration, prog, decisions, got)})
    return out


_ABSENT = object()
PLAY_BROAD_CAP = 1 << 17


def _payment_pool(payment: dict[str, Any], effect_state: dict[str, Any], actor: str) -> list[str]:
    """The objects a printed additional cost's payment can take by the rules: a discard, a card of the player's hand
    (Core 423.1.a); a buff spent, a buffed Unit the player controls (702.2.b); a kill or an exhaust paid as a cost, a
    permanent the player controls on the Board (357.1). Any other kind: every object (no pool is assumed)."""
    import effect_ir
    objects = effect_state.get("objects") or {}
    kind = payment.get("kind")
    if kind == "discard":
        return sorted(effect_state["players"][actor]["zones"].get("hand") or [])
    board = [o for o, obj in objects.items() if obj.get("controller") == actor
             and effect_ir.zone_class(effect_ir.find_location(effect_state, o)) == "board"]
    if kind == "spend_buff":
        return sorted(o for o in board if objects[o].get("kind") == "unit" and (objects[o].get("buffed") or objects[o].get("buff_count")))
    if kind in {"kill", "exhaust"}:
        # the cards that print these costs kill or exhaust Units the player controls (Commander Ledros, Cruel Patron,
        # Meditation); a Rune or Gear named for one is a witness, never assumed
        return sorted(o for o in board if objects[o].get("kind") == "unit")
    return sorted(objects)


def _deflect_owed(effect_state: dict[str, Any], actor: str, decisions: list[dict[str, Any]]) -> int:
    """The Power of any Domain a play's choices owe for Deflect (Core 809.1.c-d, 809.2): each opposing object it chooses
    as a target, each time, its Deflect value - read off the state (effect_ir.deflect_total), not the procedure."""
    import effect_ir
    import play_transaction
    owed = 0
    for entry in decisions:
        if entry.get("kind") != "target_selection" or not isinstance(entry.get("value"), list):
            continue
        for object_id in entry["value"]:
            obj = (effect_state.get("objects") or {}).get(object_id)
            if obj is not None and not play_transaction._same_team(effect_state, actor, obj.get("controller")):
                owed += int(effect_ir.deflect_total(effect_state, object_id) or 0)
    return owed


def _power_splits(power: dict[str, int], amount: int) -> list[dict[str, int]]:
    """Every way to take `amount` from this Power pool, by Domain (counted first)."""
    from itertools import product
    domains = sorted(d for d, n in power.items() if n)
    count = 1
    for d in domains:
        count *= min(power[d], amount) + 1
    if count > BROAD_CAP:
        raise OverCap(f"{count} splits of {amount} Power exceed {BROAD_CAP}")
    return [dict((d, n) for d, n in zip(domains, split) if n)
            for split in product(*[range(min(power[d], amount) + 1) for d in domains]) if sum(split) == amount] if amount else []


class CardSpace:
    """Every set of up to `high` of `pool` - a cost's cards before _screened_targets builds them; every object outside the
    pool is a witness (tried alone), so a procedure that took one would list a play the enumerator does not."""

    def __init__(self, pool: list[str], members: list[str], high: int):
        self.pool, self.outside, self.high = sorted(pool), sorted(set(members) - set(pool)), high

    def __bool__(self) -> bool:
        return True

    def __iter__(self):
        raise TypeError("a CardSpace is built by _screened_targets before its values are read")


def _slot_templates(program: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """{decision ref: the chosen-target selector of the program that names it} - a single target, a composite's Unit
    slot, or a bounded `targets` (its restrictions, on the Board unless they say otherwise)."""
    out: dict[str, dict[str, Any]] = {}

    def walk(effects):
        for effect in effects or []:
            target = effect.get("target")
            if isinstance(target, dict) and target.get("decision_ref"):
                out.setdefault(target["decision_ref"], target)
            for unit in effect.get("units") or []:
                if isinstance(unit, dict) and unit.get("decision_ref"):
                    out.setdefault(unit["decision_ref"], unit)
            spec = effect.get("targets")
            if isinstance(spec, dict) and spec.get("decision_ref"):
                restrictions = dict(spec.get("restrictions") or {})
                restrictions.setdefault("chosen_zone_class", "board")
                out.setdefault(spec["decision_ref"], restrictions)
            walk(effect.get("effects"))
    walk((program or {}).get("effects"))
    for option in ((program or {}).get("modal") or {}).get("options") or []:
        walk(option.get("effects"))
    return out


class TargetSpace:
    """Every set of up to `high` of `members` (package 15) - a target slot's values before _screened_targets builds them.
    Truthy; it is never iterated as values (a caller that did would meet a TypeError, never a silently empty slot)."""

    def __init__(self, members: list[str], high: int, low: int = 0):
        # `high` is one past what the rules allow (a single target is one; a bounded `targets` its max) and `low` what
        # they ask at least: the sizes outside [low, high - 1] are tried as witnesses, never multiplied (package 15:
        # Icathian Rain's six single targets, each with every pair of the board's units, outgrew any cap)
        self.members, self.high, self.low = sorted(members), high, low

    def __bool__(self) -> bool:
        return bool(self.members)

    def __iter__(self):
        raise TypeError("a TargetSpace is built by _screened_targets before its values are read")


def _screened_targets(slots: list[tuple[str, str, list]], play, actor: str, effect_state: dict[str, Any],
                      program: dict[str, Any] | None = None) -> tuple[list[tuple[str, str, list]], dict[str, list]]:
    """2026-10-18 package 15: a target slot's values - every set of up to two (or a spec's max plus one) of every object
    and Battlefield - multiplied by the other slots' outgrow any cap in a real game's state (Charm, "move an enemy unit":
    about 130,000 plays). The procedure checks a chosen target set member by member (a target outside the selector
    refuses the play whatever else is chosen), so a slot's sets are those of the values it does not refuse alone: each
    value is tried alone, every other slot left unanswered - one the procedure commits, or answers by asking for another
    decision, is viable; one it refuses, or asks this same slot again for, is not. That reading is checked, not assumed:
    every value it does not take alone is kept alone, and beside a viable value, in the slot's values - a procedure that
    took a set holding a value it refuses alone would commit a play the enumerator does not list, and the differential
    fails."""
    from itertools import combinations
    out, witnesses = [], {}
    # the target slots are screened in the program's order, the order the procedure checks them (Core 355.5;
    # play_transaction._check_play_targets): an earlier slot holds one value it took, so a later slot's value is judged
    # by the procedure's own answer to it - never by the procedure asking for the earlier one. An earlier slot with no
    # value it takes leaves no play to commit: the later slots have none either (their values kept as witnesses)
    earlier: list = []
    blocked = False
    reasons = CONTRACT_REQUESTS | set(__import__("play_transaction").DECISION_REASONS)
    templates = _slot_templates(program)
    for slot_id, kind, values in slots:
        if isinstance(values, CardSpace):
            from math import comb
            count = sum(comb(len(values.pool), size) for size in range(0, min(values.high, len(values.pool)) + 1))
            if count > BROAD_CAP:
                raise OverCap(f"{count} sets of {slot_id}'s cards exceed {BROAD_CAP}")
            out.append((slot_id, kind, [list(c) for size in range(0, min(values.high, len(values.pool)) + 1)
                                        for c in combinations(values.pool, size)]))
            witnesses[slot_id] = [[o] for o in values.outside]
            continue
        if kind != "target_selection" or not values:
            out.append((slot_id, kind, values))
            continue
        if isinstance(values, TargetSpace):
            high, members = values.high, list(values.members)
        else:
            high = max(len(v) for v in values)
            members = sorted({o for v in values for o in v})
        viable, refused = [], []
        answered = {entry["decision_id"] for entry in earlier} | {slot_id}

        def takes(context, member):
            got = play(context + [_entry(slot_id, kind, [member], actor, effect_state)])
            asked = set(got.get("decision_ids") or [])
            return got.get("committed") or (got.get("reason_code") in reasons and asked and not asked & answered)
        if slot_id in templates and program is not None:
            # package 15 (Wallop: the procedure asks for its optional cost before it reads the target, so a member tried
            # alone met the cost's question, never the target's): the members the procedure refuses as this slot's
            # choice whatever the other slots hold (play_transaction.refused_targets: the procedure's own test of a
            # chosen target, bound from the state, the program and this selector - never another slot's choice; GPT
            # PACKAGE15 ruling 2) are out; every other member is a value
            out_ = __import__("play_transaction").refused_targets(effect_state, actor, program, templates[slot_id])
            viable = [m for m in members if m not in out_]
            refused = [m for m in members if m in out_]
            members = []
        for member in members:
            if blocked:
                refused.append(member)
                continue
            (viable if takes(earlier, member) else refused).append(member)
        if refused and members and len(earlier) and not blocked:
            # a member refused with the earlier slots holding their first values may be taken with others: each refused
            # member is tried with every combination of the earlier slots' values, counted first - more than
            # CONTEXT_CAP is unproved by name, never cut short (GPT PACKAGE15 ruling 2)
            from math import prod
            domains = [[v for v in values_ if v not in ([], None)] for sid, _, values_ in out
                       if sid in {entry["decision_id"] for entry in earlier}]
            contexts = prod(len(d) for d in domains)
            if contexts * len(refused) > CONTEXT_CAP:
                raise OverCap(f"unproved: {len(refused)} members of {slot_id} refused with the earlier slots' first "
                              f"values, against {contexts} combinations of theirs, exceed {CONTEXT_CAP} tries")
            from itertools import product as _product
            ids = [entry["decision_id"] for entry in earlier]
            kinds = {sid: k for sid, k, _ in out}
            for member in list(refused):
                for combo in _product(*domains):
                    context = [_entry(sid, kinds[sid], value, actor, effect_state) for sid, value in zip(ids, combo)]
                    if takes(context, member):
                        refused.remove(member)
                        viable.append(member)
                        break
            viable.sort(key=lambda m: members.index(m))
        if viable:
            earlier.append(_entry(slot_id, kind, [viable[0]], actor, effect_state))
        else:
            blocked = True
        from math import comb
        low = values.low if isinstance(values, TargetSpace) else 0
        top = high - 1 if isinstance(values, TargetSpace) else high
        count = sum(comb(len(viable), size) for size in range(low, min(top, len(viable)) + 1))
        if count > BROAD_CAP:
            raise OverCap(f"{count} target sets of {len(viable)} viable members of {slot_id} exceed {BROAD_CAP}")
        screened = [list(c) for size in range(low, min(top, len(viable)) + 1) for c in combinations(viable, size)]
        witnesses[slot_id] = [[u] for u in refused] + ([[viable[0], u] for u in refused] if viable and high >= 2 else [])
        if isinstance(values, TargetSpace):
            # the counts the rules do not allow: fewer than low (none, for a single target), and one more than allowed
            # (the first `high` viable members), each a witness
            under = sum(comb(len(viable), size) for size in range(0, low))
            if under > CONTEXT_CAP:
                raise OverCap(f"unproved: {under} sets of {slot_id} smaller than its least count exceed {CONTEXT_CAP}")
            witnesses[slot_id] += [list(c) for size in range(0, low) for c in combinations(viable, size)]
            if len(viable) >= high:
                witnesses[slot_id].append(viable[:high])
        out.append((slot_id, kind, screened))
    return out, witnesses


def _combinations_with_witnesses(slots: list[tuple[str, str, list]], witnesses: dict[str, list]):
    """Every combination of the slots' values (each also left out) - and each witness value of a screened slot
    (_screened_targets: a value refused alone, alone or beside a viable one) twice: with every other slot left out, and
    with every other slot holding its first value that is not empty. The reading the witness checks (a value refused
    alone is refused in any set) is of that slot, whatever the others hold; package 15 (Icathian Rain, six target slots:
    each witness against each value of each other slot made 126,000 plays of one card) tries it at both ends."""
    from itertools import product
    yield from product(*[[_ABSENT] + list(v) for _, _, v in slots])
    filled = [next((v for v in values if v not in ([], None)), _ABSENT) for _, _, values in slots]
    for index, (slot_id, _, _) in enumerate(slots):
        for witness in witnesses.get(slot_id) or []:
            alone = [_ABSENT] * len(slots)
            alone[index] = witness
            yield tuple(alone)
            beside = list(filled)
            beside[index] = witness
            if beside != alone:
                yield tuple(beside)
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
    from math import comb
    # 2026-10-18 package 15: counted before any is built (building first exhausted the machine's memory)
    count = sum(comb(len(items), size) for size in range(low, min(high, len(items)) + 1))
    if count > BROAD_CAP:
        raise OverCap(f"{count} sets exceed {BROAD_CAP}")
    return [list(c) for size in range(low, min(high, len(items)) + 1) for c in combinations(sorted(items), size)]


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
            # package 15 (Wallop: every set of up to two of every object, 5,672, times its target's): the cards a
            # payment kind can take by the rules, every other object kept as a witness (CardSpace)
            pool = _payment_pool(offer["payment"], effect_state, actor)
            costs.append((play_transaction.printed_cost_decision_id(play_id, cost_id), "card_selection",
                          CardSpace(pool, objects, len(pool) if many else 2)))
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
            # package 15: a target slot's sets are described, not built - every set of up to `high` of these members -
            # and built by _screened_targets once the members the procedure refuses alone are known
            if isinstance(target, dict) and target.get("decision_ref"):
                out.append((target["decision_ref"], "target_selection", TargetSpace(everything, 2, low=1)))
            for slot in effect.get("units") or []:
                if isinstance(slot, dict) and slot.get("decision_ref"):
                    out.append((slot["decision_ref"], "target_selection", TargetSpace(everything, 2, low=1)))
            spec = effect.get("targets")
            if isinstance(spec, dict) and spec.get("decision_ref"):
                out.append((spec["decision_ref"], "target_selection",
                            TargetSpace(everything, spec.get("max", len(everything)) + 1, low=spec.get("min", 0))))
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
        # forgets is still in D(s): every unit object, every destination the validator's shape admits.
        # 2026-10-18 package 15: every set of every unit object (2^50 in a game's state, its decks' units among them) is
        # out of reach; the procedure is conjunctive over the units it moves (combat.standard_move: the timing and the
        # destination are read once, every other refusal names one unit and reads no other - Core 144.2, 144.4,
        # 359.3.e.6), so the sets are those of the units it takes alone, for each destination. That reading is checked,
        # not assumed: every unit it refuses alone is also tried alone and with every unit it takes (here, in D(s)) - a
        # procedure that took a set it refuses a member of would list a Move the enumerator does not, and the
        # differential fails
        units = sorted(o for o, obj in (effect_state.get("objects") or {}).items() if obj.get("kind") == "unit")
        destinations = [{"kind": "base"}] + [{"kind": "battlefield", "battlefield": bf}
                                              for bf in sorted(effect_state.get("battlefields") or {})]

        def move(group, d):
            return {"kind": family, "declaration": {
                "schema_version": combat.STANDARD_MOVE_DECLARATION_VERSION, "actor": actor, "units": list(group),
                "unit_identities": {u: effect_ir.object_identity(effect_state, u) or f"{u}@0" for u in group},
                "destination": dict(d), "cost_confirmation": {"exhaust_confirmed": True}}}
        out = []
        for d in destinations:
            alone, refused = [], []
            for u in units:
                got = combat.standard_move(timing_state, effect_state, move([u], d)["declaration"])
                if got.get("committed") is True:
                    alone.append(u)
                    continue
                refused.append(u)
                # package 15 (GPT PACKAGE15 ruling 2): a unit is out of the sets only for a refusal that is its own (the
                # procedure checks each moved unit by these, reading no other: any set holding it is refused too) or the
                # Move's own (its timing or destination: every set is refused); any other outcome alone - an invalid
                # Move, a Cleanup that fails - is unproved by name, never read as "refused in every set"
                code = got.get("reason_code")
                if code not in combat.STANDARD_MOVE_UNIT_REFUSALS and code not in combat.STANDARD_MOVE_WHOLE_REFUSALS \
                        and "timing_verdict" not in got:
                    raise OverCap(f"unproved: {u} moved alone to {d} ends {got.get('valid')}/{code}, neither its own "
                                  f"refusal nor the Move's")
            out += [move(group, d) for group in _subsets(alone)]
            out += [move([u], d) for u in refused] + [move(alone + [u], d) for u in refused if alone]
        return out
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
        got = combat.standard_move(timing_state, effect_state, action["declaration"])
        if got.get("replacement_decision_required"):
            # package 15 (GPT PACKAGE15 round 3): the Move's Cleanup asks a Replacement Effect decision, which this action
            # space does not enumerate for a Standard Move - unproved by name, never read as a Move refused
            raise OverCap(f"unproved: a Standard Move of {action['declaration'].get('units')} asks its Cleanup's "
                          f"Replacement Effect decision ({got.get('replacement_decision')}), not enumerated here")
        return got.get("committed") is True
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
    import effect_ir
    # package 15: the one input state every declaration of D(s) is tried on is held frozen - its hash and validation
    # computed once (effect_ir.frozen_inputs), and checked unchanged afterwards
    try:
        with effect_ir.frozen_inputs(effect_state):
            broad = broad_actions(family, timing_state, effect_state, actor, catalogue)
            if family in {"play_card", "activate_ability"}:
                want = {action_key_hash(a): a for a in broad}       # D(s) here holds only what the procedure committed
            else:
                want = {action_key_hash(a): a for a in broad if accepts(family, timing_state, effect_state, a)}
    except OverCap as exc:
        return {"family": family, "complete": False, "stopped": f"over_cap: {exc}"}
    got = {action_key_hash(a): a for a in enumerated_actions(result, family)}
    missing = [canonical_action_key(want[k]) for k in sorted(set(want) - set(got))]
    extra = [canonical_action_key(got[k]) for k in sorted(set(got) - set(want))]
    return {"family": family, "complete": not missing and not extra, "stopped": None, "broad": len(broad),
            "accepted": len(want), "enumerated": len(got), "missing": missing, "extra": extra}
