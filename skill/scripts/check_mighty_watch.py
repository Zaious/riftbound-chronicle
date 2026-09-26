#!/usr/bin/env python3
"""
Gate: "When you play a [Mighty] unit" (2026-09-27, Volibear - Relentless Storm).

A Unit is Mighty while its Might is 5 or greater (Core 708), and a Unit is read at its current
Might, every modifier included (Core 710). The clause grammar lowers the sentence to a watch over
the play transaction's `played` event (Core 383.1, 419.4.a) with the named fact
`object_might_at_least: 5` (watchers.WATCH_FILTERS), read off the PLAYED Unit when the play wakes
the watch.

Must hold, each through play_card with the watch the grammar itself lowers:
  - the golden sentence lowers to kinds [played], scope actor, filter {object_kind unit,
    object_might_at_least 5}; its near misses ("a unit", "another unit", an opponent's play, "becomes
    Mighty", a Mighty gear) are not this production;
  - p1 playing a Unit printed at 5 or 7 schedules one trigger; printed at 4 schedules none;
  - current Might, not printed (Core 710): printed 4 with a +1 modifier schedules; printed 5 with
    a -1 modifier does not;
  - the played Unit is what is read, not the watcher: a 6-Might watcher and a 4-Might Unit played
    schedule none;
  - p2 playing a 5-Might Unit schedules none (the player who plays, Core 411.4); p1 playing a spell
    or a gear schedules none;
  - a Legend's watch works from its Legend Zone: scheduled there, not when it is banished; a
    watcher card in a hand schedules nothing;
  - the fact is a closed range: 0, 21, a string and a boolean are refused by validation;
  - read directly: a spell is never Mighty (False); an object no zone holds is refused by name
    (might_not_readable), never guessed.
Negative mutation: with the fact's branch removed from watchers._filter_holds, the 4-Might case is
caught (the watch no longer tells 4 from 5).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import watchers  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402

HASH = "sha256:" + "b" * 64
GOLDEN = "When you play a [Mighty] unit, draw 1."
NEAR = ("When you play a unit, draw 1.", "When you play another unit, draw 1.",
        "When an opponent plays a [Mighty] unit, draw 1.", "When a unit becomes [Mighty], draw 1.",
        "When you play a [Mighty] gear, draw 1.")


def lowered(sentence: str) -> dict:
    return cg.compile_clause(sentence, cg.load_grammar())


def watch_of(sentence: str) -> dict:
    return copy.deepcopy(lowered(sentence)["passive"]["object_fields"]["event_triggers"][0]["watch"])


def with_watcher(state: dict, watch: dict, *, kind: str = "unit", where: str = "base", might: int = 2) -> dict:
    state["objects"]["w1"] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": might if kind == "unit" else 0,
                              "might_modifiers": [], "damage": 0, "exhausted": False,
                              "event_triggers": [{"trigger_id": "w", "controller": "p1", "source_object": "w1",
                                                  "controller_order": 0, "effect_program_id": "w-program",
                                                  "optional_at_finalize": False, "watch": watch,
                                                  "effect_program_hash": HASH}]}
    state["players"]["p1"]["zones"].setdefault(where, []).append("w1")
    return state


def in_hand(state: dict, card: str, *, actor: str = "p1", kind: str = "unit", might: int = 5,
            modifier: int | None = None) -> dict:
    state["objects"][card] = {"owner": actor, "controller": actor, "kind": kind,
                              "base_might": might if kind == "unit" else 0,
                              "might_modifiers": ([{"amount": modifier, "duration": "permanent", "source": card}]
                                                  if modifier else []),
                              "damage": 0, "exhausted": False}
    state["players"][actor]["zones"]["hand"].append(card)
    state["players"][actor]["resources"] = {"energy": 2, "power": {}}
    return state


def play(state: dict, card: str, *, actor: str = "p1", kind: str = "unit") -> dict:
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"play-{card}", "actor": actor, "card": card,
            "chain_item": {"id": f"{kind}-9", "object_kind": kind, "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"},
            **({"entry_location": {"kind": "base"}} if kind in ("unit", "gear") else {})}
    window = fixture()
    if actor != "p1":
        window.update({"turn_player": actor, "priority": actor, "turn_order": [actor, "p1"]})
    return play_card(window, state, decl)


def scheduled(result: dict) -> list[dict]:
    timing = result.get("next_timing_state") or {}
    return [i for i in timing.get("chain", {}).get("items", []) if str(i.get("id", "")).startswith("w@")]


def cases(watch: dict) -> list[tuple[str, dict, int]]:
    out = []

    def run(label, state, card, wanted, **kw):
        out.append((label, play(state, card, **kw), wanted))

    run("p1 plays a Unit printed at 5", in_hand(with_watcher(base_state(), watch), "h5", might=5), "h5", 1)
    run("p1 plays a Unit printed at 7", in_hand(with_watcher(base_state(), watch), "h7", might=7), "h7", 1)
    run("p1 plays a Unit printed at 4", in_hand(with_watcher(base_state(), watch), "h4", might=4), "h4", 0)
    run("printed 4 with +1 (current Might 5, Core 710)",
        in_hand(with_watcher(base_state(), watch), "h4p", might=4, modifier=1), "h4p", 1)
    run("printed 5 with -1 (current Might 4, Core 710)",
        in_hand(with_watcher(base_state(), watch), "h5m", might=5, modifier=-1), "h5m", 0)
    run("a 6-Might watcher, a 4-Might Unit played (the played Unit is read)",
        in_hand(with_watcher(base_state(), watch, might=6), "h4w", might=4), "h4w", 0)
    run("p2 plays a Unit printed at 5", in_hand(with_watcher(base_state(), watch), "o5", actor="p2", might=5), "o5", 0,
        actor="p2")
    run("p1 plays a spell", in_hand(with_watcher(base_state(), watch), "s1", kind="spell"), "s1", 0, kind="spell")
    run("p1 plays a gear", in_hand(with_watcher(base_state(), watch), "g1", kind="gear"), "g1", 0, kind="gear")
    run("the watch on a Legend in its Legend Zone",
        in_hand(with_watcher(base_state(), watch, kind="legend", where="legend_zone"), "hl", might=5), "hl", 1)
    run("the Legend banished", in_hand(with_watcher(base_state(), watch, kind="legend", where="banishment"), "hb", might=5),
        "hb", 0)
    run("the watcher card in a hand", in_hand(with_watcher(base_state(), watch, where="hand"), "hh", might=5), "hh", 0)
    return out


def main() -> int:
    errors: list[str] = []
    got = lowered(GOLDEN)
    if got.get("production") != "when_you_play_a_mighty_unit" and got.get("unsupported"):
        errors.append(f"the golden sentence is not lowered: {got.get('reason_code')}")
    watch = watch_of(GOLDEN)
    if watch != {"kinds": ["played"], "scope": "actor", "filter": {"object_kind": "unit", "object_might_at_least": 5}}:
        errors.append(f"the golden sentence lowers to another watch: {watch}")
    for sentence in NEAR:
        other = lowered(sentence)
        fields = ((other.get("passive") or {}).get("object_fields") or {}).get("event_triggers") or []
        if any((d.get("watch") or {}).get("filter", {}).get("object_might_at_least") for d in fields):
            errors.append(f"a near miss was lowered as the Mighty watch: {sentence!r}")

    for label, result, wanted in cases(watch):
        if not result.get("committed") or len(scheduled(result)) != wanted:
            errors.append(f"{label}: scheduled {len(scheduled(result))}, wanted {wanted} "
                          f"({result.get('reason_code')} {result.get('reason')})")

    for bad in (0, 21, "5", True):
        state = with_watcher(base_state(), {**watch, "filter": {"object_kind": "unit", "object_might_at_least": bad}})
        if not any("object_might_at_least" in e for e in validate_state(state)):
            errors.append(f"object_might_at_least = {bad!r} was not refused by validation")

    state = in_hand(base_state(), "s2", kind="spell")
    event = {"kind": "played", "object": "s2", "object_kind": "spell"}
    if watchers._filter_holds(state, {"object_might_at_least": 5}, event, source_object="w1", controller="p1"):
        errors.append("a spell was read as Mighty")
    try:
        watchers._filter_holds(base_state(), {"object_might_at_least": 5},
                               {"kind": "played", "object": "gone", "object_kind": "unit"}, source_object="w1", controller="p1")
        errors.append("an object no zone holds was read, not refused")
    except watchers.WatchUnsupported as exc:
        if exc.reason_code != "might_not_readable":
            errors.append(f"an object no zone holds was refused as {exc.reason_code!r}")

    # negative mutation: the fact's branch removed - the watch no longer tells a 4 from a 5
    real = watchers._filter_holds

    def blind(state, event_filter, event, **kw):
        return real(state, {k: v for k, v in event_filter.items() if k != "object_might_at_least"}, event, **kw)

    watchers._filter_holds = blind
    try:
        mutated = {label: len(scheduled(result)) == wanted for label, result, wanted in cases(watch)}
    finally:
        watchers._filter_holds = real
    if all(mutated.values()):
        errors.append("negative mutation failed: with the Might fact ignored every case still held")

    if errors:
        print("FAILED: Mighty watch checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'When you play a [Mighty] unit' lowers to a played watch with object_might_at_least 5 (near misses are "
          "not it); a Unit played at current Might 5 or more schedules one trigger (printed 5 or 7, printed 4 with +1, "
          "from a Legend's Legend Zone), and printed 4, printed 5 with -1, a 6-Might watcher with a 4-Might Unit, p2's "
          "play, a spell, a gear, a banished Legend and a watcher in hand schedule none; out-of-range facts are refused; "
          "a spell is never Mighty and an object in no zone is refused by name; ignoring the fact breaks the 4-Might case.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
