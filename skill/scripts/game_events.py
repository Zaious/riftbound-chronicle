#!/usr/bin/env python3
"""C-54 (ADR-0014 §1): the semantic event catalogue.

One game action carries one `action_id` and emits one or more *semantic*
events — a Move emits `moved` with `left_location` and `entered_location`
under it, a Kill emits `died` with `left_location`, a Draw emits one `drawn`
per card. There is no generic "an operation happened" event: an operation the
catalogue does not name is reported as `event_kind_unknown` and the caller
fails closed rather than inventing a shape for it.

Every event carries who caused it (`source`), who performed it (`actor`), the
controller of the affected object, the object's identity before and after
(Core 124), where it was and where it went, the event it derives from
(`causal_parent`), and who may see it.

Visibility has two levels, and they are not the same question:

  * `fact` — that the action happened. Every action in the catalogue is
    publicly known to have happened: an opponent sees you draw, sees a card go
    facedown, sees you look at the top of your deck. The validator requires
    `public` so that an op which really does hide its own occurrence has to
    extend this catalogue deliberately instead of arriving by accident.
  * `identity` — which card it was. Engine convention, not a Core rule: the
    identity is private only when the card was hidden before *and* after the
    event. A card discarded out of the hand becomes public in the Trash; a
    Unit returned to hand was public on the board and the opponent saw it
    leave. A trace entry that already computed the audience — the look /
    reveal / put-back family, which follows Core 424 — overrides this with
    its own `objects_visible_to`.

The module holds no state and imports the engine lazily, so `effect_ir` can
import it at module scope.
"""

from __future__ import annotations

from typing import Any

EVENT_VERSION = "riftbound-event.v1"

# Player zones whose contents are not public knowledge. `base`, `trash`,
# `banishment`, the Legend Zone and the Champion Zone are open.
HIDDEN_PLAYER_ZONES = {"hand", "main_deck", "rune_deck"}

# The catalogue. `about` says what the event is predicated on, which decides
# whether it is emitted once per affected object or once for the action.
EVENT_KINDS: dict[str, dict[str, Any]] = {
    # --- structure -------------------------------------------------------
    "left_location": {"about": "object", "rules": ["Core 186", "Core 124"]},
    "entered_location": {"about": "object", "rules": ["Core 186", "Core 124"]},
    "ceased_to_exist": {"about": "object", "rules": ["Core 186.1", "Core 416"]},
    "replacement_applied": {"about": "object", "rules": ["Core 370", "Core 373"]},
    # --- object fates ----------------------------------------------------
    "died": {"about": "object", "rules": ["Core 417"]},
    "banished": {"about": "object", "rules": ["Core 419"]},
    "discarded": {"about": "object", "rules": ["Core 421"]},
    "recycled": {"about": "object", "rules": ["Core 420"]},
    "drawn": {"about": "object", "rules": ["Core 413", "Core 431"]},
    "returned_to_hand": {"about": "object", "rules": ["Core 415"]},
    "recalled": {"about": "object", "rules": ["Core 429"]},
    "moved": {"about": "object", "rules": ["Core 428"]},
    "token_created": {"about": "object", "rules": ["Core 416"]},
    "rune_channeled": {"about": "object", "rules": ["Core 430"]},
    "put_in_hand": {"about": "object", "rules": ["Core 424.4"]},
    "hidden_away": {"about": "object", "rules": ["Core 811.1", "Core 107.3.f"]},
    "hidden_removed": {"about": "object", "rules": ["Core 323.7", "Core 811"]},
    # --- object state ----------------------------------------------------
    "damaged": {"about": "object", "rules": ["Core 437"]},
    "healed": {"about": "object", "rules": ["Core 438"]},
    "readied": {"about": "object", "rules": ["Core 440"]},
    "exhausted": {"about": "object", "rules": ["Core 439"]},
    "might_modified": {"about": "object", "rules": ["Core 476", "Core 479"]},
    "keyword_granted": {"about": "object", "rules": ["Core 477.2"]},
    "empowered": {"about": "object", "rules": ["Core 441"]},
    "disempowered": {"about": "object", "rules": ["Core 443"]},
    "buffed": {"about": "object", "rules": ["Core 426"]},
    "attached": {"about": "object", "rules": ["Core 434", "Core 435"]},
    "detached": {"about": "object", "rules": ["Core 435.4"]},
    "copied": {"about": "object", "rules": ["Core 477.1"]},
    "replacement_granted": {"about": "object", "rules": ["Core 370", "Core 124"]},
    "revealed": {"about": "object", "rules": ["Core 424.2"]},
    "looked_at": {"about": "object", "rules": ["Core 424.1"]},
    # --- player ----------------------------------------------------------
    # Sabotage: the instruction that only chooses. The event is what every
    # later instruction of the same program reads instead of choosing again.
    "player_chosen": {"about": "player", "rules": ["Core 355.1", "Core 355.17"]},
    "resource_added": {"about": "player", "rules": ["Core 446", "Core 447"]},
    "xp_gained": {"about": "player", "rules": ["Core 730"]},
    "burned_out": {"about": "player", "rules": ["Core 431.2"]},
    "cards_put_back": {"about": "player", "rules": ["Core 424.3"]},
    "predicted": {"about": "player", "rules": ["Core 432"]},
    "turn_effect_granted": {"about": "player", "rules": ["Core 317.2"]},
    "delayed_trigger_created": {"about": "player", "rules": ["Core 383.1", "Core 124"]},
    # --- chain -----------------------------------------------------------
    "countered": {"about": "chain", "rules": ["Core 359.3", "Core 361"]},
    "burned": {"about": "chain", "rules": ["Core 362"]},
    "reflexive_emitted": {"about": "chain", "rules": ["Core 355.13"]},
}

# op -> the primary semantic event it emits. An op that is absent is
# `event_kind_unknown`: the engine refuses rather than inventing a kind.
OP_PRIMARY: dict[str, str] = {
    "draw": "drawn",
    "draw_it": "drawn",
    "recycle_one": "recycled",
    "recycle": "recycled",
    "move_board_object": "moved",
    "modify_might": "might_modified",
    "deal_damage": "damaged",
    "mutual_damage_current_might": "damaged",
    "heal_damage": "healed",
    "heal_all_damage": "healed",
    "ready": "readied",
    "exhaust": "exhausted",
    "add_resource": "resource_added",
    "play_token": "token_created",
    "kill": "died",
    "emit_reflexive": "reflexive_emitted",
    "return_to_hand": "returned_to_hand",
    "recall": "recalled",
    "channel_rune": "rune_channeled",
    "grant_turn_effect": "turn_effect_granted",
    "discard": "discarded",
    "grant_replacement": "replacement_granted",
    "grant_keyword": "keyword_granted",
    "choose_player": "player_chosen",
    "look_at_top": "looked_at",
    "reveal": "revealed",
    "put_back": "cards_put_back",
    "put_in_hand": "put_in_hand",
    "predict": "predicted",
    "banish": "banished",
    "counter": "countered",
    "burn": "burned",
    "attach": "attached",
    "detach": "detached",
    "copy_object": "copied",
    "empower": "empowered",
    "disempower": "disempowered",
    "buff": "buffed",
    "gain_xp": "xp_gained",
    "hide_card": "hidden_away",
    "create_delayed_trigger": "delayed_trigger_created",
    "remove_hidden": "hidden_removed",
}

# Actions performed outside an effect program, so their op is not in
# effect_ir.SUPPORTED_OPS: Hide is a Discretionary Action of the play
# transaction (Core 811.1), not an instruction of a resolving effect.
NON_PROGRAM_OPS = {"hide_card"}

# Structural events that no single op names: they hang under a primary event.
STRUCTURAL_KINDS = {"left_location", "entered_location", "ceased_to_exist", "replacement_applied", "burned_out"}

# Outcomes in which the action happened. Mirrors effect_ir.PERFORMED_OUTCOMES;
# kept here so the catalogue can be read without importing the engine.
PERFORMED = {"applied", "replaced_modified_applied", "augmented_applied"}
# A replacement that prevented the original: the replacement applied, the
# original event did not happen (Core 205, 359.3.e.14.b).
PREVENTED = {"replaced_prevented"}


class EventKindUnknown(NotImplementedError):
    """An operation the semantic catalogue does not name."""

    reason_code = "event_kind_unknown"


def snapshot(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Where every object is and which object it is, in one pass.

    Taken before and after each instruction. Scalars only, so a later in-place
    mutation of the state cannot rewrite a snapshot already taken.
    """
    out: dict[str, dict[str, Any]] = {}
    for player_id, player in (state.get("players") or {}).items():
        for zone, ids in (player.get("zones") or {}).items():
            if not isinstance(ids, list):
                continue
            for object_id in ids:
                out.setdefault(object_id, {})["location"] = {"kind": "player_zone", "player": player_id, "zone": zone}
    for battlefield_id, battlefield in (state.get("battlefields") or {}).items():
        for object_id in battlefield.get("objects") or []:
            out.setdefault(object_id, {})["location"] = {"kind": "battlefield", "battlefield": battlefield_id}
        for entry in (battlefield.get("facedown") or {}).get("cards", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("object_id"), str):
                out.setdefault(entry["object_id"], {})["location"] = {
                    "kind": "facedown", "battlefield": battlefield_id, "controller": entry.get("controller")}
    for item_id, entry in (state.get("chain_items") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("card"), str):
            out.setdefault(entry["card"], {})["location"] = {"kind": "chain", "chain_item": item_id}
    for mark in state.get("reveals") or []:
        if isinstance(mark, dict) and isinstance(mark.get("object_id"), str):
            visible = mark.get("visible_to")
            out.setdefault(mark["object_id"], {})["revealed_to"] = "all" if visible == "all" else sorted(visible or [])
    for object_id, obj in (state.get("objects") or {}).items():
        record = out.setdefault(object_id, {})
        record.setdefault("location", None)
        record["identity"] = obj.get("identity", f"{object_id}@0")
        record["owner"] = obj.get("owner")
        record["controller"] = obj.get("controller")
        record["exists"] = True
    for record in out.values():
        record.setdefault("location", None)
        record.setdefault("identity", None)
        record.setdefault("exists", False)
        record.setdefault("revealed_to", None)
    return out


def _hidden(location: dict[str, Any] | None) -> bool:
    if not isinstance(location, dict):
        return False
    if location["kind"] == "facedown":
        return True
    return location["kind"] == "player_zone" and location["zone"] in HIDDEN_PLAYER_ZONES


def _audience(location: dict[str, Any] | None, owner: str | None) -> list[str]:
    """Who may see a card that is here."""
    if isinstance(location, dict) and location["kind"] == "facedown":
        return [location["controller"]] if location.get("controller") else []
    if isinstance(location, dict) and location["kind"] == "player_zone":
        return [location["player"]]
    return [owner] if owner else []


def identity_visibility(before: dict[str, Any] | None, after: dict[str, Any] | None, owner: str | None,
                        override: Any = None) -> Any:
    """`public`, or the players who may know which card this is.

    The override is the audience a trace entry already computed under Core 424
    (look / reveal / put back); it wins, because only that instruction knows
    whom it showed the cards to.
    """
    if isinstance(override, list):
        return sorted({p for p in override if isinstance(p, str)})
    if _hidden(before) and _hidden(after):
        return sorted(set(_audience(after, owner) + _audience(before, owner)))
    return "public"


def _kinds_of(entry: dict[str, Any]) -> str:
    op = entry.get("op")
    kind = OP_PRIMARY.get(op)
    if kind is None:
        raise EventKindUnknown(f"no semantic event is defined for operation {op!r} (ADR-0014 §1)")
    return kind


def _objects_of(entry: dict[str, Any]) -> list[str]:
    """The objects this trace entry acted on, in the order it recorded them."""
    op = entry.get("op")
    if op == "counter":
        return [entry["card"]] if isinstance(entry.get("card"), str) else []
    found: list[str] = []
    if isinstance(entry.get("object_id"), str):
        found.append(entry["object_id"])
    for field in ("objects", "revealed", "burned"):
        for item in entry.get(field) or []:
            if isinstance(item, str):
                found.append(item)
            elif isinstance(item, dict) and isinstance(item.get("object_id"), str):
                found.append(item["object_id"])
    return list(dict.fromkeys(found))


def _visible_to_override(entry: dict[str, Any]) -> Any:
    for field in ("objects_visible_to", "order_visible_to"):
        if isinstance(entry.get(field), list):
            return entry[field]
    return None


class EventLog:
    """Derives the semantic events of one program run, in order."""

    def __init__(self, action_prefix: str | None, *, actor: str | None = None, source_object: str | None = None,
                 source_kind: str = "object") -> None:
        self.action_prefix = action_prefix or "program"
        self.actor = actor
        self.source = {"object": source_object, "kind": source_kind if source_object else "rule"}
        self.events: list[dict[str, Any]] = []
        self.problems: list[str] = []
        self._counter = 0

    # -- construction ---------------------------------------------------

    def _new(self, kind: str, action_id: str, *, object_id: str | None = None, player: str | None = None,
             before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
             parent: str | None = None, visible_to: Any = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise EventKindUnknown(f"{kind!r} is not in the semantic event catalogue (ADR-0014 §1)")
        self._counter += 1
        before = before or {}
        after = after or {}
        owner = after.get("owner") or before.get("owner")
        event = {
            "schema_version": EVENT_VERSION,
            "event_id": f"{action_id}#{self._counter}",
            "action_id": action_id,
            "kind": kind,
            "source": dict(self.source),
            "actor": self.actor,
            "controller": after.get("controller") or before.get("controller"),
            "object": object_id,
            "player": player if player is not None else owner,
            "identity_before": before.get("identity"),
            "identity_after": after.get("identity"),
            "location_before": before.get("location"),
            "location_after": after.get("location"),
            "causal_parent": parent,
            "visibility": {
                "fact": "public",
                "identity": "public" if object_id is None else identity_visibility(
                    before.get("location"), after.get("location"), owner, visible_to),
            },
            "rule_locators": list(EVENT_KINDS[kind]["rules"]),
        }
        if extra:
            event.update(extra)
        self.events.append(event)
        return event

    # -- derivation -----------------------------------------------------

    def record(self, before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]],
               entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Derive the events of one trace entry. Returns the new events."""
        start = len(self.events)
        action_id = f"{self.action_prefix}:{entry.get('effect_id', entry.get('index'))}"
        outcome = entry.get("outcome")
        moved = self._identity_or_location_changes(before, after)

        if outcome in PREVENTED:
            # The replacement applied; the event it replaced did not happen.
            # A prevented event names its object as `affected_object_id`: the
            # instruction did not act on it, the replacement did.
            object_id = next(iter(_objects_of(entry)), None) or entry.get("affected_object_id")
            self._new("replacement_applied", action_id, object_id=object_id,
                      before=before.get(object_id or "", {}), after=after.get(object_id or "", {}),
                      extra={"replacement_id": entry.get("replacement_id"),
                             "prevented_kind": OP_PRIMARY.get(entry.get("op")),
                             "rule_locators": ["Core 370", "Core 205", "Core 359.3.e.14.b"]})
            return self.events[start:]
        if outcome not in PERFORMED:
            if moved:
                self.problems.append(
                    f"{action_id}: outcome {outcome!r} changed the location or identity of {sorted(moved)}")
            return []

        # The look / reveal family keeps card ids out of its public trace on
        # purpose (Core 424, ADR-0011 §3). The state still knows which cards
        # they were, so the events name them and restrict who may see them
        # rather than losing them.
        fallback = sorted(self._newly_revealed(before, after)) or sorted(moved)
        parent_of: dict[str, str] = {}
        if entry.get("expansion_trace"):
            # A composite instruction (a multi-object expansion, the mutual
            # deal): the semantics live in the sub-entries, each of which
            # names its own object. They share this action_id.
            for sub in entry["expansion_trace"]:
                if sub.get("outcome") in PERFORMED:
                    self._primary_events(sub, action_id, before, after, parent_of, fallback)
        else:
            self._primary_events(entry, action_id, before, after, parent_of, fallback)

        for record in entry.get("burn_outs") or []:
            self._new("burned_out", action_id, player=record.get("beneficiary"),
                      extra={"operation_id": record.get("operation_id"), "sequence": record.get("sequence"),
                             "recycled": list(record.get("recycled") or []),
                             "rule_locators": list(record.get("rule_locators") or EVENT_KINDS["burned_out"]["rules"])})

        # Core 186: every card that changed Location says so, under the event
        # that caused it. A change no primary event claims is a hole, not a
        # generic "something moved" event.
        for object_id in sorted(moved):
            self._location_events(object_id, action_id, before.get(object_id, {}), after.get(object_id, {}),
                                  parent_of.get(object_id), _visible_to_override(entry))
        for object_id in sorted(moved):
            if not any(e["object"] == object_id for e in self.events[start:]):
                self.problems.append(f"{action_id}: {object_id} changed location or identity with no event")
        if len(self.events) == start:
            self.problems.append(f"{action_id}: operation {entry.get('op')!r} was performed but emitted no event")
        return self.events[start:]

    def _primary_events(self, entry: dict[str, Any], action_id: str, before: dict[str, dict[str, Any]],
                        after: dict[str, dict[str, Any]], parent_of: dict[str, str],
                        fallback: list[str] | None = None) -> None:
        kind = _kinds_of(entry)
        about = EVENT_KINDS[kind]["about"]
        visible_to = _visible_to_override(entry)
        objects = _objects_of(entry) or (fallback if about == "object" else [])
        if about == "object":
            for object_id in objects:
                event = self._new(kind, action_id, object_id=object_id, before=before.get(object_id, {}),
                                  after=after.get(object_id, {}), visible_to=visible_to,
                                  extra=self._extra(entry, kind))
                parent_of[object_id] = event["event_id"]
            if not objects:
                self.problems.append(f"{action_id}: {kind} is about an object but the trace names none")
            return
        extra = self._extra(entry, kind)
        if about == "chain":
            extra["chain_item_id"] = entry.get("chain_item_id")
        event = self._new(kind, action_id, player=entry.get("player"), visible_to=visible_to, extra=extra)
        for object_id in objects:
            parent_of.setdefault(object_id, event["event_id"])

    @staticmethod
    def _extra(entry: dict[str, Any], kind: str) -> dict[str, Any]:
        carried = {
            "damaged": ("amount", "source_object", "responsible_player"),
            "healed": ("amount",),
            "might_modified": ("amount", "duration"),
            "keyword_granted": ("keyword", "value", "duration"),
            "resource_added": ("resource", "amount", "domain"),
            "xp_gained": ("amount",),
            "drawn": ("player",),
            "attached": ("to",),
            "detached": ("destination",),
            "copied": ("source_object",),
            "countered": ("chain_item_id", "destination"),
            "burned": ("player", "burned_count"),
            "predicted": ("player",),
            "cards_put_back": ("player", "count", "position"),
            "looked_at": ("player", "looked_count"),
            "replacement_granted": ("replacement_id",),
            "delayed_trigger_created": ("delayed_id", "waits_for", "target_object", "target_identity"),
        }.get(kind, ())
        return {field: entry[field] for field in carried if field in entry}

    def _location_events(self, object_id: str, action_id: str, before: dict[str, Any], after: dict[str, Any],
                         parent: str | None, visible_to: Any) -> None:
        if before.get("location") == after.get("location"):
            return
        if before.get("location") is not None:
            self._new("left_location", action_id, object_id=object_id, before=before, after=after,
                      parent=parent, visible_to=visible_to)
        if after.get("location") is not None:
            self._new("entered_location", action_id, object_id=object_id, before=before, after=after,
                      parent=parent, visible_to=visible_to)
        elif not after.get("exists"):
            self._new("ceased_to_exist", action_id, object_id=object_id, before=before, after=after, parent=parent)

    @staticmethod
    def _newly_revealed(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> set[str]:
        """Cards that gained a look / reveal mark in this instruction."""
        return {object_id for object_id, record in after.items()
                if record.get("revealed_to") and before.get(object_id, {}).get("revealed_to") != record["revealed_to"]}

    @staticmethod
    def _identity_or_location_changes(before: dict[str, dict[str, Any]],
                                      after: dict[str, dict[str, Any]]) -> set[str]:
        changed = set()
        for object_id in set(before) | set(after):
            was, now = before.get(object_id, {}), after.get(object_id, {})
            if was.get("location") != now.get("location") or was.get("identity") != now.get("identity"):
                changed.add(object_id)
        return changed


def validate_event(event: Any, path: str = "event") -> list[str]:
    errors: list[str] = []
    if not isinstance(event, dict):
        return [f"{path} must be an object"]
    if event.get("schema_version") != EVENT_VERSION:
        errors.append(f"{path}.schema_version must be {EVENT_VERSION}")
    kind = event.get("kind")
    if kind not in EVENT_KINDS:
        errors.append(f"{path}.kind {kind!r} is not in the semantic catalogue")
    required = ("event_id", "action_id", "kind", "source", "actor", "controller", "object", "player",
                "identity_before", "identity_after", "location_before", "location_after", "causal_parent",
                "visibility", "rule_locators")
    for field in required:
        if field not in event:
            errors.append(f"{path}.{field} is required")
    visibility = event.get("visibility")
    if not isinstance(visibility, dict) or set(visibility) != {"fact", "identity"}:
        errors.append(f"{path}.visibility must be {{fact, identity}}")
    else:
        if visibility["fact"] != "public":
            errors.append(f"{path}.visibility.fact must be public; an action that hides its own occurrence "
                          "has to extend the catalogue (ADR-0014 §1)")
        identity = visibility["identity"]
        if identity != "public" and not (isinstance(identity, list) and all(isinstance(p, str) for p in identity)):
            errors.append(f"{path}.visibility.identity must be 'public' or a list of players")
    if kind in EVENT_KINDS and EVENT_KINDS[kind]["about"] == "object" and not isinstance(event.get("object"), str):
        errors.append(f"{path}.object is required for {kind}")
    if not isinstance(event.get("rule_locators"), list) or not event["rule_locators"]:
        errors.append(f"{path}.rule_locators must be a non-empty array")
    return errors


def validate_events(events: Any, path: str = "events") -> list[str]:
    if not isinstance(events, list):
        return [f"{path} must be an array"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, event in enumerate(events):
        errors.extend(validate_event(event, f"{path}[{index}]"))
        if isinstance(event, dict):
            event_id = event.get("event_id")
            if event_id in seen:
                errors.append(f"{path}[{index}].event_id {event_id!r} is duplicated")
            seen.add(event_id)
    for index, event in enumerate(events):
        if isinstance(event, dict) and event.get("causal_parent") is not None and event["causal_parent"] not in seen:
            errors.append(f"{path}[{index}].causal_parent {event['causal_parent']!r} names no event in this log")
    return errors


def redact_event(event: dict[str, Any], viewer: str | None) -> dict[str, Any]:
    """The event as `viewer` may see it: the occurrence always, the card's
    identity only when they are in the audience."""
    identity = event.get("visibility", {}).get("identity")
    if identity == "public" or (viewer is not None and viewer in (identity or [])):
        return dict(event)
    redacted = dict(event)
    redacted.update({"object": None, "identity_before": None, "identity_after": None, "redacted": True})
    for field in ("location_before", "location_after"):
        location = redacted.get(field)
        if isinstance(location, dict) and location.get("kind") == "player_zone":
            redacted[field] = {"kind": "player_zone", "player": location["player"], "zone": location["zone"]}
    return redacted


def events_about(events: list[dict[str, Any]], object_id: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("object") == object_id]


def causal_children(events: list[dict[str, Any]], event_id: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("causal_parent") == event_id]
