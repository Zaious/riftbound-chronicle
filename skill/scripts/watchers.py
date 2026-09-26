#!/usr/bin/env python3
"""C-55 (ADR-0014 §2): watchers, delayed triggers, per-turn counters and
trigger multipliers.

The typed trigger lists an object carries answer "what happens to *me*".
A watcher answers "what happens to anything I am told to watch": it names the
event kinds it reacts to, a scope, and an optional `condition.v1`, and it is
matched against the semantic events of C-54 rather than against a fixed
moment in the turn.

Four rules of the trigger chapter live here, each as behaviour rather than
prose:

  * 383.3.e — a trigger marked "once each turn" or "N times each turn" does
    not trigger at all once it has been performed that many times this turn.
  * 383.3.e.2.b — declining a "you may" at finalization means the ability was
    *not* performed, so it has not spent its use and can trigger again.
  * 124 — a delayed trigger is bound to the identities it was created with; a
    target that became a new object no longer matches, and the delayed trigger
    is dropped with its reason.
  * The visibility boundary of ADR-0013 §3 — a watcher may react to a public
    fact, but a watcher whose condition reads a card its controller may not
    see is refused rather than answered.

A multiplier ("this ability triggers an additional time") is not a
characteristic, so it is not a Core 476–480 layer: it lives in its own state
list and multiplies scheduling. It never applies to the copies it produced,
and a request beyond the declared depth is refused by name.
"""

from __future__ import annotations

from typing import Any

# "actor": the player who performed the event - "When YOU stun ..." is about who stunned,
# not whose unit was stunned (2026-09-24; "controller" compares the affected object's side).
# "player": the player the event happened to - "When YOU discard" is about whose hand the card
# left (the event's `player`), not whose effect it was nor the card's controller field
# (2026-09-26; Core 422.1: a player's hand into their trash)
WATCH_SCOPES = {"self", "controller", "location", "any", "actor", "player"}
# 2026-09-24: typed facts of the EVENT a watch may require, each named, none guessed.
#   object_kind              the object the event is about is a spell / unit / gear
#   object_controller_relation   that object is the watcher controller's (friendly) or not (enemy)
#   exclude_source           the object is not the watcher's own source ("another unit")
#   on_opponents_turn        the event happened on a turn that is not the controller's
#   from_hidden              a card played from a facedown zone (Core 811)
#   object_was_buffed        the object had a buff when the event happened (a death reads the
#                            object as it was, Core 417 - not the card in the trash)
#   destination_zone         the zone it went to (a recycle to the Main Deck)
#   destination_kind         the kind of Location it went to (a move to a Battlefield)
#   printed_energy_at_least  the object's PRINTED Energy cost is at least N - "a spell that costs
#                            [5] or more"; Core 206: an effect that needs a card's cost for any
#                            purpose uses its printed (or copied) cost, never what was paid
#   card_played_ordinal      (2026-09-27, package 6) the card played is the Nth card its player has
#                            played this turn - "When you play your second card in a turn"; counted
#                            when each play is Finalized (Core 419.4.b), every play of the turn, the
#                            ones before the watching card was on the board included
#   killed_by_your_spell     (2026-09-27, package 6) a death the watcher's controller is responsible for,
#                            attributed to a spell (Core 428.5: a spell's own Kill instruction, a
#                            Cleanup death of a unit it dealt damage to, or an ability originating from
#                            a spell - resolution_bridge.kill_attributed stamps it) - "When you kill a
#                            unit with a spell"
#   object_not_tagged        (2026-09-27, package 6) the object did not have this tag when the event
#                            happened - "another non-Recruit unit"; tags are categories (Core 133.8)
#                            read off the object as it was (a death, Core 428.1), a token's by the rule
#                            that makes it (Core 187.1); an object whose tags were never observed is
#                            refused by name, never guessed
WATCH_FILTERS = {
    "object_kind": {"spell", "unit", "gear"},
    "object_controller_relation": {"friendly", "enemy"},
    "exclude_source": {True},
    "on_opponents_turn": {True},
    "from_hidden": {True},
    "object_was_buffed": {True},
    "destination_zone": {"main_deck"},
    "destination_kind": {"battlefield"},
    "printed_energy_at_least": set(range(1, 21)),
    "card_played_ordinal": set(range(1, 21)),
    "object_not_tagged": {"Recruit"},
    "killed_by_your_spell": {True},
}
# 2026-09-27 (package 6): where a triggered ability works when that is not the board. Core 385.1-385.2:
# an ability of a card outside the board says where it works, and works there and nowhere else - a
# descriptor naming `functions_from` listens only while its source is in that zone of its OWNER (a
# trash is its owner's, Core 108.2.a, 428.2, and so is the ability, 191.4.a.1). It is read on the state after the event, so a card that
# enters that zone as the condition is met triggers (Core 383.2.c.1: Immortal Phoenix killed by the very
# spell whose kill it watches) and one that leaves it at the same time does not (383.2.c.2). A
# descriptor without it works where every other ability works: the board, or a Legend's Legend Zone.
FUNCTIONS_FROM_ZONES = {"trash"}
# "each": one trigger per matching event (Core 383.3.a); "one_or_more": one per batch of
# simultaneous events however many match ("When you stun one or more enemy units").
WATCH_GROUPINGS = {"each", "one_or_more"}
# "first_each_turn": only the first matching event of the turn triggers it ("The first time a
# friendly unit dies each turn") - counted whether or not the trigger was performed, unlike
# per_turn_limit (383.3.e), which counts performances.
# "nth_each_turn" (2026-09-27): only the watch's `nth` matching event of the turn triggers it
# ("The third time I move in a turn", Core 383.1) - counted the same way; first_each_turn is
# its nth = 1. Events met together that cross the count trigger it once (383.1.b).
WATCH_OCCURRENCES = {"first_each_turn", "nth_each_turn"}
MAX_NTH = 20
WAIT_KINDS = {"event", "turn"}
TURN_MOMENTS = {"end_of_turn", "beginning_of_turn"}
# A multiplier applies to the trigger the game generated, never to a copy it
# made: one level, by construction (ADR-0014 §2).
MAX_CAUSAL_DEPTH = 1

DESCRIPTOR_FIELDS = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id",
                     "optional_at_finalize", "watch", "per_turn_limit", "ability_id", "effect_program_hash",
                     "functions_from"}
DELAYED_FIELDS = {"delayed_id", "controller", "source_object", "source_identity", "target_object", "target_identity",
                  "waits_for", "effect_program_id", "optional_at_finalize", "controller_order", "snapshot",
                  "created_turn"}
MULTIPLIER_FIELDS = {"multiplier_id", "controller", "source_object", "applies_to", "extra_times"}


class WatchUnsupported(NotImplementedError):
    """A watch the engine will not answer, named rather than guessed."""

    def __init__(self, message: str, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _watch_errors(watch: Any, path: str) -> list[str]:
    from effect_ir import validate_condition
    from game_events import EVENT_KINDS

    if not isinstance(watch, dict) or set(watch) - {"kinds", "scope", "condition", "filter", "grouping", "occurrence", "nth"}:
        return [f"{path} must be {{kinds, scope, condition?, filter?, grouping?, occurrence?, nth?}}"]
    problems: list[str] = []
    event_filter = watch.get("filter")
    if event_filter is not None:
        if not isinstance(event_filter, dict) or not event_filter:
            problems.append(f"{path}.filter must be a non-empty object")
        else:
            for key, value in event_filter.items():
                if key not in WATCH_FILTERS or value not in WATCH_FILTERS[key]:
                    problems.append(f"{path}.filter.{key} = {value!r} is not a named event fact")
    if watch.get("grouping", "each") not in WATCH_GROUPINGS:
        problems.append(f"{path}.grouping must be one of {sorted(WATCH_GROUPINGS)}")
    if "occurrence" in watch and watch["occurrence"] not in WATCH_OCCURRENCES:
        problems.append(f"{path}.occurrence must be one of {sorted(WATCH_OCCURRENCES)}")
    # "the Nth time": the count is part of the watch, and only there (Core 383.1)
    nth = watch.get("nth")
    if watch.get("occurrence") == "nth_each_turn":
        if not isinstance(nth, int) or isinstance(nth, bool) or not 1 <= nth <= MAX_NTH:
            problems.append(f"{path}.nth must be an integer from 1 to {MAX_NTH} for occurrence nth_each_turn")
    elif "nth" in watch:
        problems.append(f"{path}.nth belongs only to occurrence nth_each_turn")
    if problems:
        return problems
    errors: list[str] = []
    kinds = watch.get("kinds")
    if not isinstance(kinds, list) or not kinds:
        errors.append(f"{path}.kinds must be a non-empty array")
    else:
        unknown = [kind for kind in kinds if kind not in EVENT_KINDS]
        if unknown:
            errors.append(f"{path}.kinds names events outside the catalogue: {sorted(unknown)}")
    if watch.get("scope") not in WATCH_SCOPES:
        errors.append(f"{path}.scope must be one of {sorted(WATCH_SCOPES)}")
    if "condition" in watch:
        errors.extend(validate_condition(watch["condition"], f"{path}.condition"))
    return errors


def functions_from_errors(descriptor: dict[str, Any], obj: Any, path: str) -> list[str]:
    """`functions_from` (Core 385.2): a non-empty list of the owner's zones the ability works from, and
    nothing else; the ability of a source outside the board is controlled by the source's owner (Core
    191.4.a.1), so the descriptor's controller must be the card's owner."""
    if "functions_from" not in descriptor:
        return []
    zones = descriptor["functions_from"]
    if not isinstance(zones, list) or not zones or len(zones) != len(set(zones)) \
            or any(zone not in FUNCTIONS_FROM_ZONES for zone in zones):
        return [f"{path}.functions_from must be a non-empty list of {sorted(FUNCTIONS_FROM_ZONES)} (Core 385.2)"]
    if not isinstance(obj, dict) or descriptor.get("controller") != obj.get("owner"):
        return [f"{path}.controller must be the card's owner: an ability of a card outside the board is its "
                f"owner's (Core 191.4.a.1)"]
    return []


def _limit_errors(value: Any, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return [f"{path} must be a positive integer (Core 383.3.e)"]
    return []


def validate_watch_state(state: dict[str, Any]) -> list[str]:
    """The C-55 additions to the effect state; every one of them is optional,
    so a state written before they existed stays valid."""
    errors: list[str] = []
    players = state.get("players") if isinstance(state.get("players"), dict) else {}
    objects = state.get("objects") if isinstance(state.get("objects"), dict) else {}

    seen_triggers: set[str] = set()
    for object_id, obj in objects.items():
        descriptors = obj.get("event_triggers", []) if isinstance(obj, dict) else []
        if not isinstance(descriptors, list):
            errors.append(f"objects.{object_id}.event_triggers must be an array")
            continue
        for index, descriptor in enumerate(descriptors):
            path = f"objects.{object_id}.event_triggers[{index}]"
            if not isinstance(descriptor, dict) or set(descriptor) - DESCRIPTOR_FIELDS or \
                    not {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id",
                         "optional_at_finalize", "watch"} <= set(descriptor):
                errors.append(f"{path} must carry a trigger descriptor and a watch, and only {sorted(DESCRIPTOR_FIELDS)}")
                continue
            if descriptor["source_object"] != object_id or descriptor["controller"] not in players:
                errors.append(f"{path} has an invalid source or controller")
            if descriptor["trigger_id"] in seen_triggers:
                errors.append(f"{path}.trigger_id {descriptor['trigger_id']!r} is duplicated")
            seen_triggers.add(descriptor["trigger_id"])
            errors.extend(_watch_errors(descriptor["watch"], f"{path}.watch"))
            errors.extend(_limit_errors(descriptor.get("per_turn_limit"), f"{path}.per_turn_limit"))
            errors.extend(functions_from_errors(descriptor, obj, path))

    delayed = state.get("delayed_triggers", [])
    if not isinstance(delayed, list):
        errors.append("delayed_triggers must be an array")
        delayed = []
    seen_delayed: set[str] = set()
    for index, entry in enumerate(delayed):
        path = f"delayed_triggers[{index}]"
        required = {"delayed_id", "controller", "source_object", "source_identity", "waits_for",
                    "effect_program_id", "optional_at_finalize", "controller_order", "created_turn"}
        if not isinstance(entry, dict) or set(entry) - DELAYED_FIELDS or not required <= set(entry):
            errors.append(f"{path} must carry {sorted(required)} and only {sorted(DELAYED_FIELDS)}")
            continue
        if entry["delayed_id"] in seen_delayed:
            errors.append(f"{path}.delayed_id is duplicated")
        seen_delayed.add(entry["delayed_id"])
        if entry["controller"] not in players:
            errors.append(f"{path}.controller is not a player")
        waits = entry["waits_for"]
        if not isinstance(waits, dict) or waits.get("kind") not in WAIT_KINDS:
            errors.append(f"{path}.waits_for.kind must be one of {sorted(WAIT_KINDS)}")
        elif waits["kind"] == "event":
            errors.extend(_watch_errors({k: v for k, v in waits.items() if k != "kind"}, f"{path}.waits_for"))
        elif waits.get("moment") not in TURN_MOMENTS or set(waits) - {"kind", "moment", "turn_id"}:
            errors.append(f"{path}.waits_for must be {{kind: turn, moment, turn_id}} with moment in {sorted(TURN_MOMENTS)}")
        if ("target_object" in entry) != ("target_identity" in entry):
            errors.append(f"{path} must bind a target identity with its target object (Core 124)")

    uses = state.get("trigger_uses", {})
    if not isinstance(uses, dict) or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in uses.values()):
        errors.append("trigger_uses must map a use key to a non-negative count")
    seen_events = state.get("watch_occurrences", {})
    if not isinstance(seen_events, dict) or any(not isinstance(v, int) or isinstance(v, bool) or v < 0
                                                for v in seen_events.values()):
        errors.append("watch_occurrences must map a use key to a non-negative count")

    multipliers = state.get("trigger_multipliers", [])
    if not isinstance(multipliers, list):
        errors.append("trigger_multipliers must be an array")
        multipliers = []
    seen_multipliers: set[str] = set()
    for index, entry in enumerate(multipliers):
        path = f"trigger_multipliers[{index}]"
        if not isinstance(entry, dict) or set(entry) != MULTIPLIER_FIELDS:
            errors.append(f"{path} must carry exactly {sorted(MULTIPLIER_FIELDS)}")
            continue
        if entry["multiplier_id"] in seen_multipliers:
            errors.append(f"{path}.multiplier_id is duplicated")
        seen_multipliers.add(entry["multiplier_id"])
        if entry["controller"] not in players:
            errors.append(f"{path}.controller is not a player")
        if not isinstance(entry["extra_times"], int) or isinstance(entry["extra_times"], bool) or entry["extra_times"] < 1:
            errors.append(f"{path}.extra_times must be a positive integer")
        errors.extend(_watch_errors(entry["applies_to"], f"{path}.applies_to"))
    return errors


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------


def _may_see(event: dict[str, Any], player: str | None) -> bool:
    identity = (event.get("visibility") or {}).get("identity")
    return identity == "public" or (player is not None and player in (identity or []))


def _same_location(state: dict[str, Any], left: str | None, right: str | None) -> bool:
    from effect_ir import find_location

    if not left or not right:
        return False
    return find_location(state, left) == find_location(state, right)


def watch_matches(state: dict[str, Any], watch: dict[str, Any], event: dict[str, Any], *,
                  source_object: str | None, controller: str | None) -> bool:
    """Does this event fall inside the watch? Raises rather than guessing when
    the answer would need a card the watcher's controller may not see."""
    from effect_ir import evaluate_condition

    if event.get("kind") not in watch["kinds"]:
        return False
    scope = watch["scope"]
    subject = event.get("object")
    if scope == "self":
        if subject != source_object:
            return False
    elif scope == "controller":
        if (event.get("controller") or event.get("player")) != controller:
            return False
    elif scope == "actor":
        if event.get("actor") != controller:
            return False
    elif scope == "player":
        if event.get("player") != controller:
            return False
    elif scope == "location":
        # The event's Location, before or after: a Unit that died at my
        # Battlefield died there even though it now sits in the Trash.
        if not (_same_location(state, subject, source_object)
                or (event.get("location_before") is not None
                    and event["location_before"] == _location_of(state, source_object))):
            return False
    if not _filter_holds(state, watch.get("filter") or {}, event, source_object=source_object, controller=controller):
        return False
    condition = watch.get("condition")
    if condition is None:
        return True
    if subject is not None and not _may_see(event, controller):
        raise WatchUnsupported(
            f"a watcher controlled by {controller!r} cannot test a condition on a card it may not see "
            f"(event {event.get('event_id')!r}, ADR-0013 §3)", "watch_beyond_visibility")
    return evaluate_condition(state, condition, controller=controller, object_id=subject, perspective=controller)


def _filter_holds(state: dict[str, Any], event_filter: dict[str, Any], event: dict[str, Any], *,
                  source_object: str | None, controller: str | None) -> bool:
    """Every named fact the watch requires holds for this event (WATCH_FILTERS)."""
    subject = event.get("object")
    obj = (state.get("objects") or {}).get(subject) or {}
    for key, wanted in event_filter.items():
        if key == "object_kind":
            if (event.get("object_kind") or obj.get("kind")) != wanted:
                return False
        elif key == "object_controller_relation":
            side = event.get("controller") or obj.get("controller")
            if (side == controller) != (wanted == "friendly"):
                return False
        elif key == "exclude_source":
            if subject == source_object:
                return False
        elif key == "on_opponents_turn":
            if event.get("turn_player") in (None, controller):
                return False
        elif key == "from_hidden":
            if event.get("from_hidden") is not True:
                return False
        elif key == "object_was_buffed":
            if event.get("was_buffed") is not True:
                return False
        elif key == "destination_zone":
            after = event.get("location_after") or {}
            if after.get("kind") != "player_zone" or after.get("zone") != wanted:
                return False
        elif key == "destination_kind":
            if (event.get("location_after") or {}).get("kind") != wanted:
                return False
        elif key == "printed_energy_at_least":
            printed = (obj.get("printed_cost") or {}).get("energy")
            if not isinstance(printed, int):
                raise WatchUnsupported(f"{subject!r} carries no printed Energy cost to compare (Core 206)",
                                       "printed_cost_unknown")
            if printed < wanted:
                return False
        elif key == "card_played_ordinal":
            # the ordinal the play transaction stamped on its own `played` event (Core 419.4.b)
            if event.get("kind") != "played" or event.get("play_ordinal") != wanted:
                return False
        elif key == "killed_by_your_spell":
            killed = event.get("killed_by") or {}
            if event.get("kind") != "died" or killed.get("responsible_player") != controller or not any(
                    ((state.get("objects") or {}).get(o) or {}).get("kind") == "spell" for o in killed.get("objects") or []):
                return False
        elif key == "object_not_tagged":
            tags = event_object_tags(state, event)
            if tags is None:
                raise WatchUnsupported(f"{subject!r} carries no observed tags, so whether it is a {wanted} is "
                                       f"not known (Core 133.8); refused rather than guessed", "object_tags_unknown")
            if wanted in tags:
                return False
        else:
            return False
    return True


def event_object_tags(state: dict[str, Any], event: dict[str, Any]) -> list[str] | None:
    """The tags of the object the event is about, as it was when the event happened: a death carries
    them (game_events: read off the object before it left the board, Core 428.1 - a token has ceased
    to exist by now, Core 186.1); any other event reads the object now. None when never observed."""
    if "object_tags" in event:
        return event["object_tags"]
    from effect_ir import object_tags

    subject = event.get("object")
    return object_tags(state, subject) if subject in (state.get("objects") or {}) else None


def source_active(state: dict[str, Any], source_object: str | None, functions_from: list[str] | None = None) -> bool:
    """A watcher listens only while its source is where its abilities work: on the board
    (a Base or a Battlefield) or in its controller's Legend Zone. A card in a hand, a deck
    or a trash has no triggered abilities working (2026-09-24) - unless the ability says where
    it works (2026-09-27, Core 385.2: `functions_from`), and then only there: in that zone of the
    card's owner, and not on the board or anywhere else."""
    from effect_ir import find_location, zone_class

    if source_object not in (state.get("objects") or {}):
        return False
    location = find_location(state, source_object)
    if functions_from:
        owner = state["objects"][source_object].get("owner")
        return location is not None and location[0] == "player" and location[1] == owner \
            and location[2] in functions_from
    return zone_class(location) == "board" or (location is not None and location[0] == "player"
                                               and location[2] == "legend_zone")


def _location_of(state: dict[str, Any], object_id: str | None) -> dict[str, Any] | None:
    from game_events import snapshot

    if object_id is None:
        return None
    return snapshot(state).get(object_id, {}).get("location")


# --------------------------------------------------------------------------
# per-turn counters (Core 383.3.e)
# --------------------------------------------------------------------------


def use_key(state: dict[str, Any], descriptor: dict[str, Any], turn_id: str) -> str:
    """Keyed by the source's *identity*, so a Unit that left and came back is a
    new object with a fresh count (Core 124)."""
    from effect_ir import object_identity

    source = descriptor.get("source_object")
    identity = object_identity(state, source) if source in (state.get("objects") or {}) else source
    ability = descriptor.get("ability_id") or descriptor.get("effect_program_id") or descriptor.get("trigger_id")
    return f"{identity}|{ability}|{turn_id}"


def uses_spent(state: dict[str, Any], descriptor: dict[str, Any], turn_id: str) -> int:
    return int((state.get("trigger_uses") or {}).get(use_key(state, descriptor, turn_id), 0))


def at_limit(state: dict[str, Any], descriptor: dict[str, Any], turn_id: str) -> bool:
    limit = descriptor.get("per_turn_limit")
    return limit is not None and uses_spent(state, descriptor, turn_id) >= limit


def record_performed(state: dict[str, Any], descriptor: dict[str, Any], turn_id: str, *,
                     performed: bool = True) -> dict[str, Any]:
    """Core 383.3.e.2.b: the use is spent when the ability was performed. A
    "you may" the controller declined at finalization was not performed, so it
    keeps its use."""
    import copy

    if not performed or descriptor.get("per_turn_limit") is None:
        return state
    new_state = copy.deepcopy(state)
    uses = new_state.setdefault("trigger_uses", {})
    key = use_key(new_state, descriptor, turn_id)
    uses[key] = int(uses.get(key, 0)) + 1
    return new_state


def reset_turn_uses(state: dict[str, Any], turn_id: str) -> dict[str, Any]:
    """The counters are per turn, so the ledger keeps only this turn's rows."""
    import copy

    uses = state.get("trigger_uses")
    if not uses:
        return state
    kept = {key: count for key, count in uses.items() if key.rsplit("|", 1)[-1] == turn_id}
    if kept == uses:
        return state
    new_state = copy.deepcopy(state)
    if kept:
        new_state["trigger_uses"] = kept
    else:
        new_state.pop("trigger_uses", None)
    return new_state


# --------------------------------------------------------------------------
# scheduling
# --------------------------------------------------------------------------


def _scheduled(descriptor: dict[str, Any], event: dict[str, Any], *, trigger_kind: str, depth: int = 0,
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = {
        "trigger_id": descriptor["trigger_id"],
        "controller": descriptor["controller"],
        "source_object": descriptor["source_object"],
        "controller_order": descriptor["controller_order"],
        "effect_program_id": descriptor["effect_program_id"],
        "optional_at_finalize": descriptor["optional_at_finalize"],
        # To the timing kernel a watcher is an ordinary Triggered Ability
        # (Core 383); how it woke is the engine's own bookkeeping.
        "trigger_kind": "triggered",
        "watch_kind": trigger_kind,
        "watched_event": event.get("event_id"),
        "watched_kind": event.get("kind"),
        "watched_object": event.get("object"),
        "causal_depth": depth,
    }
    if descriptor.get("per_turn_limit") is not None:
        entry["per_turn_limit"] = descriptor["per_turn_limit"]
    if descriptor.get("ability_id") is not None:
        entry["ability_id"] = descriptor["ability_id"]
    if extra:
        entry.update(extra)
    return entry


def schedule_watchers(state: dict[str, Any], events: list[dict[str, Any]], *, turn_id: str) -> list[dict[str, Any]]:
    """Every watcher this batch of events woke, in a deterministic order:
    by the object that carries it, then by the event that woke it."""
    scheduled: list[dict[str, Any]] = []
    for object_id in sorted(state.get("objects") or {}):
        for descriptor in state["objects"][object_id].get("event_triggers", []) or []:
            for event in events:
                if not watch_matches(state, descriptor["watch"], event,
                                     source_object=descriptor["source_object"], controller=descriptor["controller"]):
                    continue
                if at_limit(state, descriptor, turn_id):
                    # 383.3.e: performed its allowance already, so it does not
                    # trigger at all — not "triggers and does nothing".
                    continue
                scheduled.append(_scheduled(descriptor, event, trigger_kind="watched"))
    return scheduled


def occurrence_nth(watch: dict[str, Any]) -> int | None:
    """Which matching event of the turn the watch waits for: 1 for "the first time", the
    watch's `nth` for "the Nth time", None for a watch that triggers on every match."""
    occurrence = watch.get("occurrence")
    if occurrence == "first_each_turn":
        return 1
    if occurrence == "nth_each_turn":
        return int(watch["nth"])
    return None


def schedule_live(state: dict[str, Any], events: list[dict[str, Any]], *, turn_id: str,
                  batch_label: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The watchers one batch of events wakes in real play (2026-09-24). Returns (the
    trigger descriptors to schedule, the state with this batch's occurrences counted).

    Unlike schedule_watchers (the scheduling rule on its own), this is what the resolution
    bridge, the play transaction and the Standard Move call: a watcher listens only while its
    source is on the board or in its Legend Zone; "one_or_more" wakes once per batch;
    "first_each_turn" wakes only on the turn's first matching event and "nth_each_turn" only on
    its nth, counted whether or not it was performed; each
    scheduled trigger gets its own id, carries the program hash its descriptor names, and is
    bound to its source's identity now (Core 124)."""
    import copy
    from effect_ir import object_identity

    scheduled: list[dict[str, Any]] = []
    counted = copy.deepcopy(state)
    occurrences = counted.setdefault("watch_occurrences", {})
    for object_id in sorted(state.get("objects") or {}):
        for descriptor in state["objects"][object_id].get("event_triggers", []) or []:
            if not source_active(state, descriptor["source_object"], descriptor.get("functions_from")):
                continue
            watch = descriptor["watch"]
            matched = [event for event in events
                       if watch_matches(state, watch, event, source_object=descriptor["source_object"],
                                        controller=descriptor["controller"])]
            if not matched:
                continue
            key = use_key(state, descriptor, turn_id)
            nth = occurrence_nth(watch)
            if nth is not None:
                # the turn's count of matching events, per source identity (Core 124): the
                # ability triggers once, on the event that makes the count reach nth - several
                # met together that cross it are one trigger (Core 383.1.b); later ones, none
                earlier = occurrences.get(key, 0)
                occurrences[key] = earlier + len(matched)
                matched = [matched[nth - earlier - 1]] if earlier < nth <= earlier + len(matched) else []
            if watch.get("grouping") == "one_or_more":
                matched = matched[:1]
            if at_limit(state, descriptor, turn_id):
                continue
            for index, event in enumerate(matched):
                entry = _scheduled(descriptor, event, trigger_kind="watched")
                entry["trigger_id"] = f"{descriptor['trigger_id']}@{batch_label}" + (f"#{index}" if index else "")
                entry["source_identity"] = object_identity(state, descriptor["source_object"])
                if descriptor.get("effect_program_hash"):
                    entry["effect_program_hash"] = descriptor["effect_program_hash"]
                scheduled.append(entry)
    if not occurrences:
        counted.pop("watch_occurrences", None)
    return scheduled, counted


def delayed_matches(state: dict[str, Any], events: list[dict[str, Any]] | None = None, *, turn_id: str,
                    moment: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (scheduled, dropped). A delayed trigger fires once, and one
    whose bound identity is gone is dropped with its reason (Core 124)."""
    from effect_ir import object_identity

    def bound_identity(entry: dict[str, Any], event: dict[str, Any] | None) -> str | None:
        """The identity the binding is tested against. An event *about* the
        target is what changed its identity — dying moves the card to the Trash
        and makes a new object (Core 124) — so the binding is tested against
        the identity the event saw, not the one it left behind."""
        target = entry["target_object"]
        if event is not None and event.get("object") == target:
            return event.get("identity_before")
        return object_identity(state, target) if target in (state.get("objects") or {}) else None

    scheduled: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for entry in state.get("delayed_triggers") or []:
        source_now = object_identity(state, entry["source_object"]) if entry["source_object"] in (state.get("objects") or {}) else None
        waits = entry["waits_for"]
        if entry.get("target_object") is not None and waits["kind"] == "turn":
            found = bound_identity(entry, None)
            if found != entry["target_identity"]:
                dropped.append({"delayed_id": entry["delayed_id"], "reason": "target_identity_changed",
                                "bound_to": entry["target_identity"], "found": found,
                                "rule_locators": ["Core 124"]})
                continue
        if waits["kind"] == "turn":
            if moment == waits["moment"] and waits.get("turn_id", turn_id) == turn_id:
                scheduled.append(_scheduled(entry | {"trigger_id": entry["delayed_id"]}, {},
                                            trigger_kind="delayed",
                                            extra={"delayed_id": entry["delayed_id"], "moment": waits["moment"],
                                                   "snapshot": entry.get("snapshot"),
                                                   "source_identity_at_creation": entry["source_identity"],
                                                   "source_identity_now": source_now}))
            continue
        matched_but_unbound: dict[str, Any] | None = None
        for event in events or []:
            watch = {k: v for k, v in waits.items() if k != "kind"}
            if not watch_matches(state, watch, event, source_object=entry["source_object"], controller=entry["controller"]):
                continue
            if entry.get("target_object") is not None:
                found = bound_identity(entry, event)
                if found != entry["target_identity"]:
                    matched_but_unbound = {"delayed_id": entry["delayed_id"], "reason": "target_identity_changed",
                                           "bound_to": entry["target_identity"], "found": found,
                                           "rule_locators": ["Core 124"]}
                    continue
            if True:
                scheduled.append(_scheduled(entry | {"trigger_id": entry["delayed_id"]}, event,
                                            trigger_kind="delayed",
                                            extra={"delayed_id": entry["delayed_id"], "snapshot": entry.get("snapshot"),
                                                   "source_identity_at_creation": entry["source_identity"],
                                                   "source_identity_now": source_now}))
                matched_but_unbound = None
                break  # it fires once
        if matched_but_unbound is not None:
            dropped.append(matched_but_unbound)
    return scheduled, dropped


def settle_delayed(state: dict[str, Any], fired: list[dict[str, Any]], dropped: list[dict[str, Any]]) -> dict[str, Any]:
    """Remove the delayed triggers that fired and the ones that lost their
    binding. Everything else waits."""
    import copy

    spent = {entry.get("delayed_id") for entry in fired} | {entry["delayed_id"] for entry in dropped}
    if not spent or not state.get("delayed_triggers"):
        return state
    new_state = copy.deepcopy(state)
    remaining = [entry for entry in new_state["delayed_triggers"] if entry["delayed_id"] not in spent]
    if remaining:
        new_state["delayed_triggers"] = remaining
    else:
        new_state.pop("delayed_triggers", None)
    return new_state


def apply_multipliers(state: dict[str, Any], scheduled: list[dict[str, Any]],
                      events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """"Triggers an additional time": every multiplier that applies adds its
    copies of the trigger the game generated. A multiplier never applies to a
    copy — that is what `causal_depth` guards — and a depth beyond the declared
    bound is refused by name rather than bounded by a recursion limit."""
    by_id = {event.get("event_id"): event for event in events}
    expanded: list[dict[str, Any]] = []
    for entry in scheduled:
        depth = entry.get("causal_depth", 0)
        if depth > MAX_CAUSAL_DEPTH:
            raise WatchUnsupported(
                f"trigger {entry.get('trigger_id')!r} arrived at causal depth {depth}, beyond the declared bound "
                f"{MAX_CAUSAL_DEPTH} (ADR-0014 §2)", "trigger_multiplier_depth")
        expanded.append(entry)
        if depth == MAX_CAUSAL_DEPTH:
            continue  # a copy is never itself multiplied
        event = by_id.get(entry.get("watched_event")) or {}
        for multiplier in state.get("trigger_multipliers") or []:
            if not watch_matches(state, multiplier["applies_to"], event,
                                 source_object=entry.get("source_object"), controller=multiplier["controller"]):
                continue
            for copy_index in range(multiplier["extra_times"]):
                expanded.append({**entry, "causal_depth": depth + 1,
                                 "multiplied_by": multiplier["multiplier_id"],
                                 "copy_index": copy_index,
                                 "rule_locators": ["Core 383.3"]})
    return expanded
