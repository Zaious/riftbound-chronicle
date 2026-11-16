#!/usr/bin/env python3
"""The closed environment's catalogue (C2, package 13; GPT 2026-10-15 rulings 1 and 4).

The public engine defines the catalogue's shape and reads it; the catalogue itself - built from the private overlay's
signed card programs - stays in the overlay. A catalogue pins the environment (1v1, the Core the engine executes, the
card pool) and records, for every card in the pool, the object an instance of it is - every static field the engine
reads, whole - its activated ability rows, the symbolic programs its plays and abilities run, and, when part of the
card could not be assembled, what (`incomplete`): a state holding such a card is not proved.

  validate_catalogue(catalogue)          the shape, every record, row and program, and the catalogue's own hash
  place(catalogue, ref, owner=, object_id=, controller=)
                                         an effect-state object of that card, carrying card_ref; ability and trigger
                                         ids namespaced by the object, program ids by the card, its triggers its
                                         controller's; a fresh game state
  place_battlefield(catalogue, ref, battlefield_id)
                                         a Battlefield entry of that card, its own references bound to its id
  instantiate_program(catalogue, ref, key, bindings)
                                         a riftbound-effect-program.v1 with the five symbols bound
  environment_problems(state, catalogue) why this state is not a state of the environment: not 1v1, an object with no
                                         card_ref or an unknown one, a card not fully assembled, an object whose
                                         fields other than the DYNAMIC ones differ from its record in any way, a
                                         legacy list entry, or source-backed Replacement Effects other than exactly
                                         those the engine materializes for the state's objects

A symbol is one of SYMBOLS; a 1v1 game binds each to one value.
"""
from __future__ import annotations

import state_copy
from typing import Any

from effect_ir import (APPENDABLE_TRIGGER_FIELDS, CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, RULE_NUMBERING, hash_value,
                       materialize_printed_replacements, validate_condition)

CATALOGUE_VERSION = "closed-environment-catalogue.v1"
SYMBOLS = ("$controller", "$opponent", "$chain_item", "$source_object", "$card")
FORMAT = "1v1"
KINDS = ("unit", "gear", "spell", "legend", "rune", "battlefield")
# Every object field the engine writes while a game is played (measured over the engine's modules 2026-10-15) - game
# state, not the card. Every other field of an environment object is the card's, and equals its record.
DYNAMIC_FIELDS = frozenset({"owner", "controller", "control_changed", "exhausted", "damage", "might_modifiers", "stunned",
                            "buffed", "buff_count", "empowered", "attached_to", "combat_designation", "identity",
                            "modes_chosen", "pending_recall",
                            # set 2 (measured 2026-11-17): the turn a card was attached (attach), the lifecycle of a
                            # copying card's attaches (Svellsongur), the units a card's linked ability banished (The Zero
                            # Drive) - effect_ir writes and validates each
                            "attached_on_turn", "copy_lifecycle", "linked_banished"})
# What an attached card wrote on its Top-Most card (effect_ir: an Effect Text's rows, a copy's rows and keys), recorded
# in that card's `copied_text`: not the Top-Most card's printed text. environment_problems takes each record's writing out
# of the object before comparing it with its record, and holds the writing itself to what that attached card writes
WRITTEN_RECORD = "copied_text"
# A card field some of whose entries a play adds (each naming the chain item that added it): those entries are game
# state, the rest - a printed "This enters exhausted." - the card's
PLAY_BOUND_ENTRIES = {"entry_replacements": "chain_item"}


def _card_fields(obj: dict[str, Any]) -> dict[str, Any]:
    """The object's fields that are the card's: no DYNAMIC field, and no entry a play added."""
    out = {}
    for key, value in obj.items():
        if key in DYNAMIC_FIELDS:
            continue
        if key in PLAY_BOUND_ENTRIES and isinstance(value, list):
            value = [e for e in value if not (isinstance(e, dict) and PLAY_BOUND_ENTRIES[key] in e)]
            if not value:
                continue
        out[key] = value
    return out
RECORD_KEYS = frozenset({"object", "activated_abilities", "programs", "incomplete"})
# The legacy state-level lists: an environment's cards carry their statics on their objects (printed_damage_modifiers,
# printed_might_auras, printed_replacements), so an environment state holds no entry in these
LEGACY_LISTS = ("damage_modifiers", "might_auras")
# A token the pool's cards make (Core 185): the fields its play_token instruction gives the object it creates
# (effect_ir play_token) - what it is, apart from where and whose
TOKEN_FIELDS = ("kind", "base_might", "keywords", "tags")
# set 2 (the Gold gear token): a token card may print activated abilities, with the programs they run
TOKEN_OPTIONAL_FIELDS = ("activated_abilities", "programs")


def token_abilities(obj: dict[str, Any], object_id: str) -> dict[str, Any] | None:
    """A token object's activated abilities as its catalogue record writes them: ids and programs un-namespaced, the
    token's own id back to "$token" (effect_ir play_token wrote them the other way); None when it has none."""
    rows = obj.get("activated_abilities")
    if not rows:
        return None
    prefix, program_prefix = f"{object_id}:", f"{obj.get('token_id')}#"
    return {key[len(prefix):] if key.startswith(prefix) else key:
            {**_bind_some(state_copy.deepcopy(row), {object_id: "$token"}),
             "effect_program_id": row["effect_program_id"][len(program_prefix):]
             if row["effect_program_id"].startswith(program_prefix) else row["effect_program_id"]}
            for key, row in rows.items()}


def token_record(effect: dict[str, Any]) -> dict[str, Any]:
    """The token a play_token instruction makes, as a catalogue records it."""
    keywords = (effect.get("event_modifiers") or {}).get("result_keywords", []) if effect.get("token_kind") == "unit" else []
    record = {"kind": effect.get("token_kind"), "base_might": effect.get("base_might"), "keywords": list(keywords),
              "tags": list(effect.get("tags") or [])}
    if effect.get("activated_abilities"):
        record["activated_abilities"] = state_copy.deepcopy(effect["activated_abilities"])
    return record


def _token_ops(value: Any, out: list) -> list:
    if isinstance(value, dict):
        if value.get("op") == "play_token":
            out.append(value)
        for v in value.values():
            _token_ops(v, out)
    elif isinstance(value, list):
        for v in value:
            _token_ops(v, out)
    return out


# A card the player cannot see, in a player's view (action_receipt.actor_view): only what is public - whose it is,
# where it is, that it is there (its identity token counts the zone changes everyone saw); the zones it may be in
MASK_ZONES = ("hand", "main_deck", "rune_deck")


def mask(obj: dict[str, Any], *, rune: bool = False) -> dict[str, Any]:
    out = {"owner": obj.get("owner"), "controller": obj.get("controller"), "kind": "rune" if rune else "spell",
           "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False, "masked": True}
    if "identity" in obj:
        out["identity"] = obj["identity"]
    return out


# A record's trigger descriptor: its controller and source are bound per object, its order is the controller's choice
# when several trigger together (Core 383.3.d - never fixed in a record), its program is one of the card's
TRIGGER_SYMBOLIC = {"controller": "$controller", "source_object": "$source_object", "controller_order": 0}
# every field a record's descriptors live in: an object's (effect_ir.APPENDABLE_TRIGGER_FIELDS) and a Battlefield's own
# "When a unit moves from here" (effect_ir validates it on a Battlefield only)
TRIGGER_FIELDS = APPENDABLE_TRIGGER_FIELDS + ("move_from_triggers",)
# a Battlefield's: no controller or source of its own - its controller's (Core 190.6.a; effect_ir refuses either)
BATTLEFIELD_TRIGGER_SYMBOLIC = {"controller_order": 0}
# The fields of a Battlefield entry the engine writes in play (measured 2026-10-15); a Battlefield card's other fields
# are its record's. Its Facedown Zone's cards are game state; its capacity is the card's (1 unless the card says more)
BATTLEFIELD_DYNAMIC = frozenset({"controller", "contested", "contested_by", "control_changed", "objects", "facedown"})


def catalogue_hash(catalogue: dict[str, Any]) -> str:
    return hash_value({k: v for k, v in catalogue.items() if k != "catalogue_hash"})


def validate_catalogue(catalogue: Any) -> list[str]:
    if not isinstance(catalogue, dict):
        return ["catalogue must be an object"]
    errors: list[str] = []
    if set(catalogue) - {"tokens"} != {"schema_version", "environment", "cards", "catalogue_hash"}:
        errors.append("catalogue carries exactly schema_version, environment, cards, catalogue_hash, and tokens")
        return errors
    tokens = catalogue.get("tokens") or {}
    if not isinstance(tokens, dict) or any(not isinstance(t, dict) or not set(TOKEN_FIELDS) <= set(t)
                                           or set(t) - set(TOKEN_FIELDS) - set(TOKEN_OPTIONAL_FIELDS)
                                           or (("activated_abilities" in t) != ("programs" in t))
                                           or any(not isinstance(r, dict) or r.get("effect_program_id") not in (t.get("programs") or {})
                                                  for r in (t.get("activated_abilities") or {}).values())
                                           for t in tokens.values()):
        errors.append(f"tokens maps token ids to {{{', '.join(TOKEN_FIELDS)}}} and, together, activated_abilities whose "
                      f"programs are among its programs")
        tokens = {}
    if catalogue["schema_version"] != CATALOGUE_VERSION:
        errors.append(f"schema_version must be {CATALOGUE_VERSION}")
    environment = catalogue["environment"]
    want = {"format": FORMAT, "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING}
    if not isinstance(environment, dict) or set(environment) != set(want) | {"card_pool"} \
            or any(environment.get(k) != v for k, v in want.items()) \
            or not isinstance(environment.get("card_pool"), str) or not environment["card_pool"]:
        errors.append(f"environment must be {want} with a card_pool name")
    cards = catalogue["cards"]
    if not isinstance(cards, dict) or not cards:
        errors.append("cards must be a non-empty map of card_ref to record")
        return errors
    for ref, record in sorted(cards.items()):
        label = f"cards[{ref!r}]"
        if not isinstance(record, dict) or set(record) - RECORD_KEYS or not isinstance(record.get("object"), dict):
            errors.append(f"{label} carries object and may carry activated_abilities, programs, incomplete")
            continue
        static = record["object"]
        if static.get("kind") not in KINDS:
            errors.append(f"{label}.object.kind must be one of {list(KINDS)}")
        if set(static) & (DYNAMIC_FIELDS | {"card_ref", "activated_abilities"}) or static != _card_fields(static):
            errors.append(f"{label}.object carries game-state fields or play-bound entries")
        incomplete = record.get("incomplete")
        if incomplete is not None and (not isinstance(incomplete, list) or not incomplete
                                       or any(not isinstance(i, str) or not i for i in incomplete)):
            errors.append(f"{label}.incomplete names what of the card is not assembled, as non-empty strings")
        programs = record.get("programs") or {}
        if not isinstance(programs, dict) or any(not isinstance(p, dict) or set(p) - {"effects", "modal", "conditional_triggers"}
                                                  or not isinstance(p.get("effects", []), list) for p in programs.values()):
            errors.append(f"{label}.programs maps program keys to {{effects, modal?, conditional_triggers?}}")
            programs = {}
        for key, template in programs.items():
            for index, ct in enumerate(template.get("conditional_triggers") or []):
                if not isinstance(ct, dict) or ct.get("controller") != "$controller" or ct.get("source_object") != "$source_object" \
                        or ct.get("effect_program_id") not in programs or ct.get("effect_program_id") == key:
                    errors.append(f"{label}.programs[{key!r}].conditional_triggers[{index}] must be the program's own "
                                  f"($controller, $source_object) and run another of the card's programs")
        trigger_ids: set[str] = set()
        battlefield = static.get("kind") == "battlefield"
        symbolic = BATTLEFIELD_TRIGGER_SYMBOLIC if battlefield else TRIGGER_SYMBOLIC
        for field in TRIGGER_FIELDS:
            for index, descriptor in enumerate(static.get(field) or []):
                where = f"{label}.object.{field}[{index}]"
                if not isinstance(descriptor, dict) or any(descriptor.get(k) != v for k, v in symbolic.items()) \
                        or "effect_program_hash" in descriptor or not isinstance(descriptor.get("optional_at_finalize"), bool) \
                        or (battlefield and ({"controller", "source_object"} & set(descriptor))):
                    errors.append(f"{where} must carry {symbolic}, optional_at_finalize, and no program hash"
                                  + (" - and no controller or source (a Battlefield's)" if battlefield else ""))
                    continue
                if descriptor.get("effect_program_id") not in programs:
                    errors.append(f"{where} runs {descriptor.get('effect_program_id')!r}, which is not one of its programs")
                if not isinstance(descriptor.get("trigger_id"), str) or descriptor["trigger_id"] in trigger_ids:
                    errors.append(f"{where}.trigger_id is missing or repeats another of the card's")
                trigger_ids.add(descriptor.get("trigger_id"))
        # ADR-0017 §1: an Effect Text's triggers are the card's too - symbolic, unhashed, each running one of its programs
        text = static.get("effect_text")
        for field, rows_ in ((text.get("triggers") or {}).items() if isinstance(text, dict) else []):
            for index, descriptor in enumerate(rows_ or []):
                where = f"{label}.object.effect_text.triggers.{field}[{index}]"
                if not isinstance(descriptor, dict) or any(descriptor.get(k) != v for k, v in TRIGGER_SYMBOLIC.items()) \
                        or "effect_program_hash" in descriptor or not isinstance(descriptor.get("optional_at_finalize"), bool):
                    errors.append(f"{where} must carry {TRIGGER_SYMBOLIC}, optional_at_finalize, and no program hash")
                    continue
                if descriptor.get("effect_program_id") not in programs:
                    errors.append(f"{where} runs {descriptor.get('effect_program_id')!r}, which is not one of its programs")
                if not isinstance(descriptor.get("trigger_id"), str) or descriptor["trigger_id"] in trigger_ids:
                    errors.append(f"{where}.trigger_id is missing or repeats another of the card's")
                trigger_ids.add(descriptor.get("trigger_id"))
        for index, template in enumerate(static.get("printed_replacements") or []):
            # a materialized entry is compared whole with what the engine materializes: a use count would drift
            if not isinstance(template, dict) or template.get("uses_remaining") is not None or "uses_per_turn" in template:
                errors.append(f"{label}.object.printed_replacements[{index}] must not count its uses")
        for ability_id, row in (record.get("activated_abilities") or {}).items():
            if row.get("effect_program_id") not in programs:
                errors.append(f"{label}.activated_abilities[{ability_id!r}] runs {row.get('effect_program_id')!r}, "
                              f"which is not one of its programs")
            for index, condition in enumerate(row.get("activation_conditions") or []):
                errors += [f"{label}.activated_abilities[{ability_id!r}] {e}"
                           for e in validate_condition(condition, f"activation_conditions[{index}]")]
        for effect in _token_ops(programs, []):
            if effect.get("token_id") not in tokens or {k: v for k, v in tokens[effect["token_id"]].items()
                                                         if k != "programs"} != token_record(effect):
                errors.append(f"{label} makes token {effect.get('token_id')!r} as {token_record(effect)}, which the "
                              f"catalogue's tokens do not record so")
        if static.get("kind") == "spell" and "play" not in programs and not record.get("incomplete"):
            errors.append(f"{label} is a spell with no play program, and does not say it is incomplete")
    if not errors and catalogue["catalogue_hash"] != catalogue_hash(catalogue):
        errors.append("catalogue_hash does not hash the catalogue")
    return errors


def ability_id(object_id: str, local: str) -> str:
    return f"{object_id}:{local}"


def program_id(ref: str, key: str) -> str:
    return f"{ref}#{key}"


def place(catalogue: dict[str, Any], ref: str, *, owner: str, object_id: str, controller: str | None = None) -> dict[str, Any]:
    """An effect-state object of card `ref` with id `object_id`, owned by `owner` and controlled by `controller` (its
    owner unless given): its record's static fields, its activated abilities (ids namespaced by the object, programs by
    the card), its triggered abilities (ids namespaced by the object, programs by the card, its controller's - Core
    191.5.a), card_ref, and a fresh game state (ready, undamaged, unmodified)."""
    record = catalogue["cards"][ref]
    if record["object"].get("kind") == "battlefield":
        raise ValueError(f"{ref!r} is a Battlefield, not an object")
    controller = owner if controller is None else controller
    obj = state_copy.deepcopy(record["object"])
    obj.update({"owner": owner, "controller": controller, "might_modifiers": [], "damage": 0, "exhausted": False,
                "card_ref": ref})
    for field in TRIGGER_FIELDS:
        if obj.get(field):
            obj[field] = [{**descriptor, "trigger_id": ability_id(object_id, descriptor["trigger_id"]), "controller": controller,
                           "source_object": object_id, "effect_program_id": program_id(ref, descriptor["effect_program_id"])}
                          for descriptor in obj[field]]
    text = obj.get("effect_text")
    if isinstance(text, dict) and isinstance(text.get("triggers"), dict):
        # ADR-0017 §1: an Equipment's Effect Text triggers - ids namespaced by this object (two copies stay apart),
        # programs by the card; their source and controller are the Top-Most card's, written when it attaches
        # (effect_ir.append_effect_text), and $source_object binds to that source when one resolves (game_loop.item_program)
        text["triggers"] = {field: [{**descriptor, "trigger_id": ability_id(object_id, descriptor["trigger_id"]),
                                     "controller": controller, "source_object": object_id,
                                     "effect_program_id": program_id(ref, descriptor["effect_program_id"])}
                                    for descriptor in rows_]
                            for field, rows_ in text["triggers"].items()}
    obj.setdefault("base_might", 0)
    rows = record.get("activated_abilities") or {}
    if rows:
        # a row's own object (its [Exhaust], its own Buff) is this object; nothing else in a row is bound here
        own = {"$source_object": object_id, "$card": object_id}
        obj["activated_abilities"] = {ability_id(object_id, local): {**_bind_some(state_copy.deepcopy(row), own),
                                                                     "effect_program_id": program_id(ref, row["effect_program_id"])}
                                      for local, row in sorted(rows.items())}
    # an ability's own Dependent condition (a Legion gate) is keyed by its id, so it follows the id's namespace; one that
    # names its own ability ("Use only once per turn": ability_uses_this_turn_below) names it in that namespace too (as a
    # copy's does, effect_ir.copied_text_bundle)
    if isinstance(obj.get("ability_conditions"), dict):
        obj["ability_conditions"] = {
            ability_id(object_id, local): ({**condition, "ability": ability_id(object_id, local)}
                                           if isinstance(condition, dict) and condition.get("ability") == local else condition)
            for local, condition in sorted(obj["ability_conditions"].items())}
    return obj


def _bind_some(value: Any, bindings: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _bind_some(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [_bind_some(v, bindings) for v in value]
    return bindings.get(value, value) if isinstance(value, str) else value


def place_battlefield(catalogue: dict[str, Any], ref: str, battlefield_id: str) -> dict[str, Any]:
    """A Battlefield entry of Battlefield card `ref` with id `battlefield_id`: uncontrolled and empty, its record's fields
    (its own references - a Bonus Damage to units at itself - bound to its id), card_ref."""
    record = catalogue["cards"][ref]
    if record["object"].get("kind") != "battlefield":
        raise ValueError(f"{ref!r} is not a Battlefield")
    entry = {k: _bind_some(state_copy.deepcopy(v), {"$source_object": battlefield_id})
             for k, v in record["object"].items() if k != "kind"}
    for field in TRIGGER_FIELDS:
        if entry.get(field):
            entry[field] = [{**descriptor, "trigger_id": ability_id(battlefield_id, descriptor["trigger_id"]),
                             "effect_program_id": program_id(ref, descriptor["effect_program_id"])}
                            for descriptor in entry[field]]
    entry.update({"controller": None, "objects": [], "card_ref": ref})
    return entry


def _battlefield_card_fields(entry: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in entry.items() if k not in BATTLEFIELD_DYNAMIC}
    out["facedown_capacity"] = (entry.get("facedown") or {}).get("capacity", 1)
    return out


def bind(value: Any, bindings: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: bind(v, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    if isinstance(value, str) and value in SYMBOLS:
        return bindings[value]
    return value


def instantiate_program(catalogue: dict[str, Any], ref: str, key: str, bindings: dict[str, str]) -> dict[str, Any]:
    """Program `key` of card `ref`, its symbols bound (every symbol of SYMBOLS must be bound)."""
    missing = sorted(set(SYMBOLS) - set(bindings))
    if missing:
        raise ValueError(f"unbound symbols {missing}")
    # a card's program, or a token card's (set 2: the Gold gear token's ability)
    template = (catalogue["cards"].get(ref) or (catalogue.get("tokens") or {}).get(ref))["programs"][key]
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
               "program_id": program_id(ref, key), "controller": bindings["$controller"],
               "source_object": bindings["$source_object"], "effects": bind(template.get("effects") or [], bindings)}
    if "modal" in template:
        program["modal"] = bind(template["modal"], bindings)
    if template.get("conditional_triggers"):
        # each one's id per source, its program per card (Core 388: added to the Chain as the program resolves)
        program["conditional_triggers"] = [{**bind(ct, bindings),
                                            "trigger_id": ability_id(bindings["$source_object"], ct["trigger_id"]),
                                            "effect_program_id": program_id(ref, ct["effect_program_id"])}
                                           for ct in template["conditional_triggers"]]
    return program


def _copy_bundle(state: dict[str, Any], attached_id: str, host_id: str, printed_host: dict[str, Any]) -> dict[str, Any] | None:
    """A copying card's bundle (Svellsongur, effect_ir.copied_text_bundle) over the Top-Most card as its record prints it
    (its dynamic fields as they are), at the copying card's lifecycle; None when the engine refuses the copy."""
    from effect_ir import copied_text_bundle
    probe = state_copy.deepcopy(state)
    live = probe["objects"][host_id]
    probe["objects"][host_id] = {**printed_host, **{k: v for k, v in live.items() if k in DYNAMIC_FIELDS}}
    try:
        return copied_text_bundle(probe, attached_id, host_id, int(probe["objects"][attached_id].get("copy_lifecycle") or 0))
    except Exception:  # noqa: BLE001 - a copy the engine refuses writes nothing that could be its
        return None


def _written_replacements(state: dict[str, Any], catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    """The Replacement Effects attached cards wrote, as effect_ir.append_effect_text writes them from each attached card's
    record now: an Effect Text's (Guardian Angel) sourced from the attached card, about the Top-Most card, its controller
    the attached card's; a copy's (Svellsongur) the Top-Most card's own, its controller the Top-Most card's."""
    from effect_ir import EFFECT_TEXT_COPY
    objects = state.get("objects") or {}
    cards = catalogue.get("cards") or {}
    out = []
    for attached_id, attached in sorted(objects.items()):
        host_id = attached.get("attached_to")
        host = objects.get(host_id) if isinstance(host_id, str) else None
        if host is None:
            continue
        base = f"effect_text:{attached_id}:{host_id}"
        if attached.get("effect_text_copy") == EFFECT_TEXT_COPY:
            if host.get("card_ref") not in cards:
                continue
            printed = place(catalogue, host["card_ref"], owner=host.get("owner"), object_id=host_id,
                            controller=host.get("controller"))
            bundle = _copy_bundle(state, attached_id, host_id, printed)
            for index, template in enumerate((bundle or {}).get("copy_replacements") or []):
                out.append({**state_copy.deepcopy(template), "replacement_id": f"{base}:replacement:copy:{index}",
                            "controller": host.get("controller"), "source_object": host_id})
        elif isinstance(attached.get("effect_text"), dict):
            for index, template in enumerate(attached["effect_text"].get("replacements") or []):
                out.append({**state_copy.deepcopy(template), "replacement_id": f"{base}:replacement:{index}",
                            "controller": attached.get("controller"), "source_object": attached_id,
                            "target_object_id": host_id})
    return out


def _written_by(state: dict[str, Any], attached_id: str, host_id: str, printed_host: dict[str, Any]) -> dict[str, Any] | None:
    """What the attached card writes on the Top-Most card under its copied_text record ({rows, keys, values}), as
    effect_ir writes it: an Effect Text's rows (EFFECT_TEXT_ROW_FIELDS), each id made the attached card's; a copy's rows,
    keys and values (Svellsongur) - copied_text_bundle over the Top-Most card as its record prints it, at the attached
    card's lifecycle. None when that card is not attached to it or writes nothing there."""
    from effect_ir import EFFECT_TEXT_COPY, EFFECT_TEXT_ROW_FIELDS
    attached = (state.get("objects") or {}).get(attached_id) or {}
    if attached.get("attached_to") != host_id:
        return None
    if attached.get("effect_text_copy") == EFFECT_TEXT_COPY:
        bundle = _copy_bundle(state, attached_id, host_id, printed_host)
        if bundle is None:
            return None
        copied = bundle["copy"]
        return {"rows": copied["rows"], "keys": {field: sorted(keyed) for field, keyed in copied["keys"].items()},
                "values": copied["values"]}
    text = attached.get("effect_text")
    rows = text.get("rows") if isinstance(text, dict) else None
    if not rows:
        return None
    suffix = f":effect_text:{attached_id}"
    written = {}
    for field, entries in rows.items():
        id_key = EFFECT_TEXT_ROW_FIELDS.get(field)
        written[field] = [{**row, id_key: f"{row[id_key]}{suffix}"} if id_key and isinstance(row.get(id_key), str) else row
                          for row in entries]
    return {"rows": written, "keys": {}, "values": {}}


def _printed_projection(state: dict[str, Any], object_id: str, obj: dict[str, Any],
                        printed: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The object's printed fields - its card fields with what attached cards wrote on it taken out (its copied_text
    record, row by row and key by key) - and why any of that writing is not what the attached card writes. Nothing is let
    off by field: a printed row edited, a row no record names, a record's row missing from the object, or a record
    writing other than its attached card does, each is a problem."""
    fields = _card_fields(obj)
    record = fields.pop(WRITTEN_RECORD, None)
    if record is None:
        return fields, []
    if not isinstance(record, dict):
        return fields, [f"{object_id}.{WRITTEN_RECORD} is not a record of attached cards"]
    problems = []
    for attached_id, written in sorted(record.items()):
        if not isinstance(written, dict) or written != _written_by(state, attached_id, object_id, printed):
            problems.append(f"{object_id}.{WRITTEN_RECORD}[{attached_id!r}] is not what that attached card writes")
            if not isinstance(written, dict):
                continue
        for field, rows in (written.get("rows") or {}).items():
            kept = list(fields.get(field) or [])
            for row in rows:
                if row in kept:
                    kept.remove(row)
                else:
                    problems.append(f"{object_id}.{field} lacks a row {attached_id!r} wrote")
            if kept:
                fields[field] = kept
            else:
                fields.pop(field, None)
        for field, keys in (written.get("keys") or {}).items():
            kept = {k: v for k, v in (fields.get(field) or {}).items() if k not in set(keys)}
            if kept:
                fields[field] = kept
            else:
                fields.pop(field, None)
    return fields, problems


def environment_problems(state: dict[str, Any], catalogue: dict[str, Any]) -> list[str]:
    """Why `state` is not a state of this environment (empty when it is): not 1v1; an object with no card_ref or one
    the catalogue lacks; a card the catalogue says is not fully assembled; an object whose fields other than the
    DYNAMIC ones are not exactly its record's - none missing, none added, none edited - once what attached cards wrote
    on it (its copied_text record) is taken out; and writing that is not what the attached card writes
    (_printed_projection)."""
    problems = []
    if len(state.get("players") or {}) != 2:
        problems.append(f"the environment is {FORMAT}; the state has {len(state.get('players') or {})} players")
    cards = catalogue["cards"]
    tokens = catalogue.get("tokens") or {}
    from effect_ir import find_location as _where
    for object_id, obj in sorted((state.get("objects") or {}).items()):
        if obj.get("masked") is True:
            # a player's view: a mask only where a card can be unseen, and nothing but what a mask carries
            where = _where(state, object_id)
            unseen = where is not None and (where[0] == "facedown" or (where[0] == "player" and where[2] in MASK_ZONES))
            if not unseen or obj != mask(obj, rune=where is not None and where[0] == "player" and where[2] == "rune_deck"):
                problems.append(f"{object_id} is masked where a card is seen, or carries more than a mask")
            continue
        if obj.get("is_token") is True:
            # a token the pool's cards make: what it is is its record's (Core 185)
            record = tokens.get(obj.get("token_id"))
            if record is None:
                problems.append(f"{object_id} is a token the catalogue's cards do not make ({obj.get('token_id')!r})")
            elif {k: obj.get(k, [] if k in ("keywords", "tags") else None) for k in TOKEN_FIELDS} \
                    != {k: record[k] for k in TOKEN_FIELDS} or token_abilities(obj, object_id) != record.get("activated_abilities"):
                problems.append(f"{object_id} is token {obj['token_id']!r} with fields other than its record's")
            continue
        ref = obj.get("card_ref")
        if ref is None:
            problems.append(f"{object_id} carries no card_ref")
            continue
        if ref not in cards:
            problems.append(f"{object_id} is {ref!r}, which the catalogue does not have")
            continue
        if cards[ref].get("incomplete"):
            problems.append(f"{object_id} is {ref!r}, which the catalogue has not fully assembled: {cards[ref]['incomplete']}")
        want = place(catalogue, ref, owner=obj.get("owner"), object_id=object_id, controller=obj.get("controller"))
        static_have, written = _printed_projection(state, object_id, obj, want)
        problems += written
        static_want = _card_fields(want)
        for field in sorted(set(static_have) | set(static_want)):
            if static_have.get(field, "<absent>") != static_want.get(field, "<absent>"):
                problems.append(f"{object_id}.{field} differs from {ref!r}'s record")
    for battlefield_id, entry in sorted((state.get("battlefields") or {}).items()):
        ref = entry.get("card_ref")
        if ref is None:
            problems.append(f"Battlefield {battlefield_id} carries no card_ref")
            continue
        record = cards.get(ref)
        if record is None or record["object"].get("kind") != "battlefield":
            problems.append(f"Battlefield {battlefield_id} is {ref!r}, which the catalogue has as no Battlefield")
            continue
        if record.get("incomplete"):
            problems.append(f"Battlefield {battlefield_id} is {ref!r}, which the catalogue has not fully assembled")
        have, want = _battlefield_card_fields(entry), _battlefield_card_fields(place_battlefield(catalogue, ref, battlefield_id))
        for field in sorted(set(have) | set(want)):
            if have.get(field, "<absent>") != want.get(field, "<absent>"):
                problems.append(f"Battlefield {battlefield_id}.{field} differs from {ref!r}'s record")
    # no legacy list entry; the source-backed Replacement Effects are exactly what the engine materializes for the
    # state's objects and what attached cards wrote (_written_replacements; a granted or created one is game state)
    for name in LEGACY_LISTS:
        if state.get(name):
            problems.append(f"the state's {name} hold entries no environment card adds (its statics are on its objects)")
    own = [r for r in state.get("replacement_effects") or [] if "source_object" in r]
    rest = state_copy.deepcopy({k: v for k, v in state.items() if k != "replacement_effects"})
    rest["replacement_effects"] = [r for r in state.get("replacement_effects") or [] if "source_object" not in r]
    materialize_printed_replacements(rest)
    want = [r for r in rest["replacement_effects"] if "source_object" in r] + _written_replacements(state, catalogue)
    if sorted(json_key(r) for r in own) != sorted(json_key(r) for r in want):
        problems.append("the state's source-backed replacement_effects are not exactly those its objects' printed ones "
                        "materialize to")
    return problems


def json_key(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
