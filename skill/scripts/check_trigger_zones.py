#!/usr/bin/env python3
"""
Regression gate (2026-09-27, package 6): where a triggered ability works, and three watch facts.

Before this, watchers.source_active admitted a watcher only on the board or in a Legend's Legend
Zone, and battlefield_control._score_triggers read the same places - so an ability that works from
the trash ("When you discard me", Immortal Phoenix, Super Mega Death Rocket!) never triggered; no
watch could say "your second card in a turn" or "a non-Recruit unit".

Must hold, each through the engine's own procedures (resolve_with_program, play_card,
resolve_battlefield_control after a decided Combat):
  - `functions_from` (Core 385.2): a watcher descriptor may name the owner's zones it works from
    (only "trash"); the descriptor's controller must be the card's owner; the field is refused on
    a typed trigger list other than a controller-scoped conquer trigger;
  - it works there and nowhere else: a trash watcher in the hand, on the board or banished does
    not trigger; in its owner's trash it does; recycled out of the trash it stops;
  - the zone is read after the event (Core 383.2.c.1): a trash watcher on a unit killed by the
    very kill it watches triggers (the Immortal Phoenix example); a board watcher whose card dies
    in the same Cleanup as the unit it watches does not (383.2.c.2, the Viktor example), and does
    when only the other unit dies;
  - "When you discard me": discarding the card (alone, or with another card in one discard)
    schedules one trigger; another card discarded, the card already in the trash, and the same
    discard with a board-only watch (no functions_from) schedule nothing;
  - a controller-scoped conquer trigger with functions_from trash on a spell in p1's trash fires
    on p1's Conquer with the Score's batch; in p1's hand, in p2's trash on p1's Conquer, and on a
    unit on p1's board it does not; the same spell in p2's trash fires on p2's own Conquer;
  - card_played_ordinal (Core 419.4.a): every play completed by its card's resolution counts, the
    ones before the watcher was on the board too; the watch with ordinal 2 triggers on the second
    play and not on the first or the third; the opponent's second play does not; the same card
    played twice counts twice; a new turn counts from zero; a countered play is not counted (GPT
    2026-09-27: a countered earlier card was not played); the watching card played as the second
    card triggers for itself (GPT 2026-09-27, package 3 section 7 item 1);
  - object_not_tagged Recruit: a friendly non-Recruit unit (tags observed) dying triggers; a
    Recruit token (tagged Recruit by the play_token that made it, from the reviewed catalogue -
    package 7), a unit tagged Recruit,
    an enemy unit and the watching card itself do not; a unit whose tags were never observed is
    refused by name (object_tags_unknown), never guessed - a Recruit token without tags too;
  - killed_by_your_spell (Core 428.5): the resolution stamps the deaths it caused - a Kill
    instruction of the resolving spell (428.5.b), a Cleanup death of a unit it dealt damage to
    (428.5.c), an ability whose source is a spell (428.5.d) - with the killer and the responsible
    player (428.5.c.1); the watch triggers for p1's spell, and from the trash when the watching
    card is the unit killed (383.2.c.1); not for the opponent's spell, a unit's ability, a program
    resolved with no card on the Chain, or a Cleanup death the spell did not deal damage for;
  - the clause grammar lowers "When you play your second card in a turn, ...", "When another
    non-Recruit unit you control dies, ...", "When you discard me, ..." and "When you kill a unit
    with a spell, ..." to exactly those descriptors, and near misses stay unparsed.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from battlefield_control import resolve_battlefield_control  # noqa: E402
from check_control_resolution import decided_combat  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, object_tags, validate_state  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

TRASH = ["trash"]
DISCARD_ME = {"kinds": ["discarded"], "scope": "self"}
ANY_DEATH = {"kinds": ["died"], "scope": "any", "filter": {"object_kind": "unit"}}
SECOND = {"kinds": ["played"], "scope": "actor", "filter": {"card_played_ordinal": 2}}
NON_RECRUIT = {"kinds": ["died"], "scope": "any",
               "filter": {"object_kind": "unit", "object_controller_relation": "friendly", "exclude_source": True,
                          "object_not_tagged": "Recruit"}}


def descriptor(trigger_id, source, controller="p1", **extra):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False, **extra}


def card(state, object_id, zone, *, owner="p1", kind="unit", watch=None, functions_from=None, trigger_id="w",
         tags=None, might=2, **extra):
    obj = {"owner": owner, "controller": owner, "kind": kind, "base_might": might if kind == "unit" else 0,
           "might_modifiers": [], "damage": 0, "exhausted": False, **extra}
    if watch is not None:
        d = descriptor(trigger_id, object_id, owner, watch=copy.deepcopy(watch))
        if functions_from is not None:
            d["functions_from"] = list(functions_from)
        obj["event_triggers"] = [d]
    if tags is not None:
        obj["tags"] = list(tags)
    state["objects"][object_id] = obj
    state["players"][owner]["zones"].setdefault(zone, []).append(object_id)
    return state


def board():
    state = base_state()
    state["turn_id"] = "turn-3"
    state["objects"]["u1"]["tags"] = []
    state["objects"]["u2"]["tags"] = []
    return state


def _damaged(state):
    """p2's u2 (Might 4) already carries 2 damage - lethal once its Might drops to 2 or less."""
    state["objects"]["u2"]["damage"] = 2
    return state


def resolve(state, effects, *, controller="p1"):
    timing = fixture(priority="p2", items=[item("spell-1", controller, "spell", "default", "finalized")], passes=["p1", "p2"])
    if controller != "p1":
        timing["turn_player"] = controller
    return resolve_with_program(timing, "spell-1", state, {**program("resolving", *effects), "controller": controller})


def woke(result, prefix="w@"):
    timing = result.get("next_timing_state") or {}
    return [i for i in timing.get("chain", {}).get("items", []) if str(i.get("id", "")).startswith(prefix)]


def committed(result, label, errors):
    if not result.get("committed"):
        errors.append(f"{label}: did not commit ({result.get('reason_code')}: {result.get('reason') or result.get('errors')})")
        return False
    return True


def play(state, card_id, *, actor="p1", play_id=None, kind="unit"):
    """`actor` plays `card_id` from their hand for 0 and, for a unit, it resolves (enters its Base)."""
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": play_id or f"play-{card_id}", "actor": actor, "card": card_id,
            "chain_item": {"id": f"item-{play_id or card_id}", "object_kind": kind, "timing": "default"},
            "cost": {"base": {"energy": 0, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if kind in ("unit", "gear"):
        decl["entry_location"] = {"kind": "base"}
    timing = fixture()
    if actor != "p1":
        timing.update({"turn_player": actor, "priority": actor, "turn_order": [actor, "p1"], "players": [actor, "p1"]})
    return play_card(timing, state, decl), decl


def enter(played, decl, *, actor="p1"):
    """The played unit resolves (the entry procedure): the Chain it left is empty again."""
    item_id = decl["chain_item"]["id"]
    timing = fixture(priority="p2" if actor == "p1" else "p1",
                     items=[item(item_id, actor, decl["chain_item"]["object_kind"], "default", "finalized")],
                     passes=["p1", "p2"])
    if actor != "p1":
        timing.update({"turn_player": actor, "turn_order": [actor, "p1"], "players": [actor, "p1"]})
    return resolve_with_program(timing, item_id, played["next_effect_state"], None)


def plays(state, cards, errors, *, actor="p1", prefix="w@"):
    """Each card played and resolved in turn; the number of `prefix` triggers each play woke."""
    counts = []
    for index, card_id in enumerate(cards):
        played, decl = play(state, card_id, actor=actor, play_id=f"p{index}-{card_id}")
        if not committed(played, f"playing {card_id}", errors):
            return counts, None
        entered = enter(played, decl, actor=actor)
        if not committed(entered, f"resolving {card_id}", errors):
            return counts, None
        # Core 419.4.a (packages 3+4): a play trigger wakes when the card's play completes - as it resolves -
        # never at Finalize; the triggers of a play are those its resolution put on the Chain
        counts.append(len(woke(played, prefix)) + len(woke(entered, prefix)))
        state = entered["next_effect_state"]
    return counts, state


def main() -> int:
    errors: list[str] = []

    # --- the descriptor shape ---------------------------------------------------------------------------
    for label, zones, owner_is_controller, valid in (("trash", TRASH, True, True), ("hand", ["hand"], True, False),
                                                     ("empty", [], True, False), ("twice", ["trash", "trash"], True, False),
                                                     ("controller not owner", TRASH, False, False)):
        state = card(board(), "fc", "hand", watch=DISCARD_ME, functions_from=zones)
        if not owner_is_controller:
            state["objects"]["fc"]["event_triggers"][0]["controller"] = "p2"
        found = validate_state(state)
        if bool(found) == valid:
            errors.append(f"functions_from '{label}' validated {not found}, wanted {valid}: {found[:1]}")
    typed = board()
    card(typed, "sp", "trash", kind="spell")
    typed["objects"]["sp"]["conquer_triggers"] = [descriptor("sp-c", "sp", scope="controller", functions_from=TRASH)]
    if validate_state(typed):
        errors.append(f"a controller-scoped conquer trigger with functions_from trash is refused: {validate_state(typed)[:1]}")
    for label, field, extra in (("unit_here scope", "conquer_triggers", {"scope": "unit_here"}),
                                ("a play trigger", "play_triggers", {})):
        bad = board()
        card(bad, "sp", "trash", kind="spell")
        bad["objects"]["sp"][field] = [descriptor("sp-c", "sp", functions_from=TRASH, **extra)]
        if not validate_state(bad):
            errors.append(f"functions_from on {label} was accepted")
    for label, tags, valid in (("a list", ["Noxus"], True), ("empty", [], True), ("duplicated", ["Recruit", "Recruit"], False),
                               ("not a list", "Recruit", False), ("an empty name", [""], False)):
        state = board()
        state["objects"]["u1"]["tags"] = tags
        if bool(validate_state(state)) == valid:
            errors.append(f"tags '{label}' validated {not validate_state(state)}, wanted {valid}")
    counted = board()
    counted["players"]["p1"]["cards_played_count_this_turn"] = {"turn-3": 0}
    if not validate_state(counted):
        errors.append("cards_played_count_this_turn accepted a zero count")

    # --- where it works: the trash, and nowhere else (Core 385.2) ---------------------------------------
    def dying_board(zone, functions_from=TRASH):
        state = board()
        card(state, "ph", zone, watch=ANY_DEATH, functions_from=functions_from)
        return state

    kill_u1 = [{"op": "kill", "effect_id": "k", "object_id": "u1"}]
    for zone, wanted in (("trash", 1), ("hand", 0), ("base", 0), ("banishment", 0)):
        done = resolve(dying_board(zone), kill_u1)
        if committed(done, f"a unit dies while the trash watcher is in the {zone}", errors) and len(woke(done)) != wanted:
            errors.append(f"a trash watcher in the {zone}: a unit's death scheduled {len(woke(done))}, wanted {wanted}")
    # the same watch with no functions_from works on the board, as every watcher did before
    done = resolve(dying_board("base", functions_from=None), kill_u1)
    if committed(done, "a board watcher", errors) and len(woke(done)) != 1:
        errors.append(f"a board watcher in the base scheduled {len(woke(done))} for a unit's death, wanted 1")
    done = resolve(dying_board("trash", functions_from=None), kill_u1)
    if committed(done, "a board watcher in the trash", errors) and woke(done):
        errors.append("a watcher with no functions_from triggered from the trash")
    # recycled out of the trash, it stops: the same death after the card left schedules nothing
    left = resolve(dying_board("trash"), [{"op": "recycle", "effect_id": "rc", "player": "p1", "objects": ["ph"]}])
    if committed(left, "recycling the trash watcher", errors):
        gone = resolve(left["next_effect_state"], kill_u1)
        if committed(gone, "a unit dies after the watcher was recycled", errors) and woke(gone):
            errors.append("a trash watcher recycled to the Main Deck still triggered")
    # its OWNER's trash: p1's card lying in p2's trash (a hand-built board) is not where it works
    misplaced = board()
    card(misplaced, "ph", "trash", watch=ANY_DEATH, functions_from=TRASH)
    misplaced["players"]["p1"]["zones"]["trash"].remove("ph")
    misplaced["players"]["p2"]["zones"]["trash"].append("ph")
    done = resolve(misplaced, kill_u1)
    if committed(done, "p1's trash watcher in p2's trash", errors) and woke(done):
        errors.append("p1's trash watcher triggered from p2's trash; it works from its owner's trash only")
    # a watcher in the OPPONENT's trash is theirs, and works for them: p2's unit dies, p2's watcher wakes
    theirs = board()
    card(theirs, "ph2", "trash", owner="p2", watch=ANY_DEATH, functions_from=TRASH, trigger_id="t2")
    done = resolve(theirs, [{"op": "kill", "effect_id": "k", "object_id": "u2"}])
    if committed(done, "p2's trash watcher", errors):
        items = woke(done, "t2@")
        if len(items) != 1 or items[0].get("controller") != "p2":
            errors.append(f"p2's trash watcher did not wake as p2's trigger: {items}")

    # --- read after the event (Core 383.2.c.1 / 383.2.c.2) ---------------------------------------------
    phoenix = board()
    card(phoenix, "ph", "base", watch=ANY_DEATH, functions_from=TRASH)
    done = resolve(phoenix, [{"op": "kill", "effect_id": "k", "object_id": "ph"}])
    if committed(done, "the trash watcher killed itself", errors):
        items = woke(done)
        if len(items) != 1 or items[0].get("source_object") != "ph" or items[0].get("source_identity") != "ph@1":
            errors.append(f"a trash watcher killed by the kill it watches did not trigger from the trash "
                          f"(Core 383.2.c.1): {items}")
    # the board watcher (Viktor) and the unit it watches die in the same Cleanup: no trigger
    together = board()
    card(together, "vk", "base", watch=NON_RECRUIT, might=2, tags=["Viktor"])
    lethal = [{"op": "deal_damage", "effect_id": "d1", "object_id": "vk", "amount": 5},
              {"op": "deal_damage", "effect_id": "d2", "object_id": "u1", "amount": 5}]
    done = resolve(together, lethal)
    if committed(done, "Viktor and u1 die together", errors):
        dead = set(done["next_effect_state"]["players"]["p1"]["zones"]["trash"])
        if not {"vk", "u1"} <= dead or woke(done):
            errors.append(f"a board watcher dying in the same Cleanup as the unit it watches triggered, or they did not "
                          f"die (Core 383.2.c.2): trash {sorted(dead)}, woke {woke(done)}")
    done = resolve(copy.deepcopy(together), lethal[1:])
    if committed(done, "u1 dies alone", errors) and len(woke(done)) != 1:
        errors.append(f"the control (u1 dies alone in the Cleanup) scheduled {len(woke(done))}, wanted 1")

    # --- "When you discard me" ------------------------------------------------------------------------------
    def discard_board(*, functions_from=TRASH, other=True):
        state = board()
        card(state, "fc", "hand", watch=DISCARD_ME, functions_from=functions_from)
        if other:
            card(state, "h2", "hand", kind="spell")
        return state

    done = resolve(discard_board(other=False), [{"op": "discard", "effect_id": "dc", "player": "p1", "count": 1}])
    if committed(done, "discarding the card", errors):
        items = woke(done)
        if len(items) != 1 or items[0].get("source_object") != "fc" or items[0].get("source_identity") != "fc@1":
            errors.append(f"discarding the card did not schedule its 'When you discard me' from the trash: {items}")
    done = resolve(discard_board(), [{"op": "discard", "effect_id": "dc", "player": "p1", "count": 2}])
    if committed(done, "discarding two cards", errors) and len(woke(done)) != 1:
        errors.append(f"discarding the card with another in one discard scheduled {len(woke(done))}, wanted 1")
    other_only = discard_board()
    other_only["players"]["p1"]["zones"]["hand"].remove("fc")
    other_only["players"]["p1"]["zones"]["trash"].append("fc")
    done = resolve(other_only, [{"op": "discard", "effect_id": "dc", "player": "p1", "count": 1}])
    if committed(done, "another card discarded while the card is in the trash", errors) and woke(done):
        errors.append("another card's discard scheduled 'When you discard me' of a card already in the trash")
    done = resolve(discard_board(functions_from=None, other=False),
                   [{"op": "discard", "effect_id": "dc", "player": "p1", "count": 1}])
    if committed(done, "a board-only discard watch", errors) and woke(done):
        errors.append("a discard watch with no functions_from triggered from the trash: the zone is load-bearing")

    # --- a Conquer trigger that works from the trash --------------------------------------------------------
    def conquer_ids(extra):
        t, e = decided_combat(extra=extra)
        done = resolve_battlefield_control(t, e)
        if not done.get("committed"):
            return None, done
        return [(i["id"], i.get("batch_id"), i.get("controller")) for i in done["next_timing_state"]["chain"]["items"]], done

    def rocket(zone="trash", owner="p1", kind="spell"):
        def extra(e):
            card(e, "rk", zone, owner=owner, kind=kind)
            e["objects"]["rk"]["conquer_triggers"] = [descriptor("rk-c", "rk", owner, scope="controller",
                                                                 functions_from=TRASH)]
        return extra

    got, done = conquer_ids(rocket())
    turn = (done or {}).get("next_effect_state", {}).get("turn_id", "turn-0") if got is not None else None
    if got is None or [g for g in got if g[0] == "rk-c"] != [("rk-c", f"score:bf1:{turn}:conquer", "p1")]:
        errors.append(f"p1's Conquer did not schedule the trash spell's 'When you conquer' with the Score's batch: "
                      f"{got} {(done or {}).get('reason')}")
    for label, extra in (("in p1's hand", rocket(zone="hand")), ("in p2's trash", rocket(owner="p2")),
                         ("a unit on p1's board", rocket(zone="base", kind="unit"))):
        got, done = conquer_ids(extra)
        if got is None or any(g[0] == "rk-c" for g in got):
            errors.append(f"the trash Conquer trigger {label}: p1's Conquer scheduled {got} ({(done or {}).get('reason')})")

    # --- "your second card in a turn" (Core 419.4.b) --------------------------------------------------------
    def play_board(*, darius_zone="base"):
        state = board()
        card(state, "dr", darius_zone, watch=SECOND, tags=["Darius"])
        for name in ("a1", "a2", "a3"):
            card(state, name, "hand", tags=[])
        return state

    counts, _ = plays(play_board(), ["a1", "a2", "a3"], errors)
    if counts != [0, 1, 0]:
        errors.append(f"three plays with the watcher on the board scheduled {counts}, wanted [0, 1, 0]")
    # plays before the watcher was on the board count: a1, then the watching card itself as the second play,
    # then a2 (the third). GPT 2026-09-27 (package 3, section 7 item 1; Core 383.2.c.1, 419.4): the count is the
    # whole turn's, and the card's own play completes as it resolves - its ability is active by then, so the
    # second play (itself) triggers it; the third does not
    counts, _ = plays(play_board(darius_zone="hand"), ["a1", "dr", "a2"], errors)
    if counts != [0, 1, 0]:
        errors.append(f"a1, the watcher itself as the second card, a2 scheduled {counts}, wanted [0, 1, 0]")
    # the opponent's second card is not "your" second card
    theirs = play_board()
    for name in ("b1", "b2"):
        card(theirs, name, "hand", owner="p2", tags=[])
    counts, _ = plays(theirs, ["b1", "b2"], errors, actor="p2")
    if counts != [0, 0]:
        errors.append(f"the opponent's first and second plays scheduled {counts} of p1's second-card trigger")
    # the same card played twice in a turn is two plays (returned to the hand in between)
    _counts, once = plays(play_board(), ["a1"], errors)
    if once is not None:
        back = resolve(once, [{"op": "return_to_hand", "effect_id": "rh", "object_id": "a1"}])
        if committed(back, "returning a1", errors):
            counts, _ = plays(back["next_effect_state"], ["a1"], errors)
            if counts != [1]:
                errors.append(f"the same card played again as the second play scheduled {counts}, wanted [1]")
    # a countered play is not a card played (Core 419.4.a.1; GPT 2026-09-27): a1 played and countered on the
    # Chain, then a2 is the FIRST play completed - it schedules nothing - and a3 the second
    countered_board = play_board()
    first, decl = play(countered_board, "a1", play_id="p0-a1")
    if committed(first, "playing a1 (to be countered)", errors):
        on_chain = first["next_effect_state"]
        # p2's spell on top of a1's chain item counters it (Core 425.1)
        a1_item = decl["chain_item"]["id"]
        timing = fixture(priority="p1", items=[item(a1_item, "p1", "unit", "default", "finalized"),
                                               item("spell-1", "p2", "spell", "default", "finalized")],
                         passes=["p1", "p2"])
        gone = resolve_with_program(timing, "spell-1", on_chain, {**program("counter", {
            "op": "counter", "effect_id": "c", "chain_item_id": a1_item}), "controller": "p2"})
        if committed(gone, "countering a1", errors):
            if "a1" not in gone["next_effect_state"]["players"]["p1"]["zones"]["trash"]:
                errors.append("the countered a1 is not in p1's trash")
            counts, _ = plays(gone["next_effect_state"], ["a2", "a3"], errors)
            if counts != [0, 1]:
                errors.append(f"a1 countered, then a2 and a3 scheduled {counts}, wanted [0, 1] (a countered card "
                              f"was not played)")
    # a new turn counts from zero
    _counts, once = plays(play_board(), ["a1"], errors)
    if once is not None:
        once["turn_id"] = "turn-4"
        counts, _ = plays(once, ["a2", "a3"], errors)
        if counts != [0, 1]:
            errors.append(f"a play last turn then two this turn scheduled {counts}, wanted [0, 1]")

    # --- "another non-Recruit unit you control dies" --------------------------------------------------------
    def viktor(extra=None):
        state = board()
        card(state, "vk", "base", watch=NON_RECRUIT, tags=["Viktor"])
        if extra:
            extra(state)
        return state

    # package 7: a token carries the printed tags play_token brought from the reviewed catalogue
    # (token_catalog.carry_tags); there is no engine table to fall back on
    def recruit_token(state, tags=("Recruit",)):
        state["objects"]["t1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "is_token": True, "token_id": "recruit",
                                  "base_might": 1, "might_modifiers": [], "damage": 0, "exhausted": False,
                                  **({"tags": list(tags)} if tags is not None else {})}
        state["players"]["p1"]["zones"]["base"].append("t1")

    def sprite_token(state):
        state["objects"]["t2"] = {"owner": "p1", "controller": "p1", "kind": "unit", "is_token": True, "token_id": "sprite",
                                  "base_might": 3, "might_modifiers": [], "damage": 0, "exhausted": False, "tags": ["Fae"]}
        state["players"]["p1"]["zones"]["base"].append("t2")

    def recruit_card(state):
        card(state, "rc", "base", tags=["Recruit", "Noxus"])

    if object_tags(viktor(recruit_token), "t1") != ["Recruit"] or object_tags(viktor(sprite_token), "t2") != ["Fae"]:
        errors.append("a token's tags are not the ones its play_token carried")
    bare = resolve(viktor(lambda state: recruit_token(state, tags=None)), [{"op": "kill", "effect_id": "k", "object_id": "t1"}])
    if bare.get("committed") or bare.get("reason_code") != "object_tags_unknown":
        errors.append(f"a Recruit token played without its tags died and the watch did not refuse by name (no engine "
                      f"table may supply them): {bare.get('committed')} {bare.get('reason_code')}")
    for label, extra, victim, wanted in (("a friendly non-Recruit unit", None, "u1", 1),
                                         ("a Sprite token (a non-Recruit unit token)", sprite_token, "t2", 1),
                                         ("a Recruit token", recruit_token, "t1", 0),
                                         ("a unit tagged Recruit", recruit_card, "rc", 0),
                                         ("an enemy unit", None, "u2", 0),
                                         ("the watching card itself", None, "vk", 0)):
        done = resolve(viktor(extra), [{"op": "kill", "effect_id": "k", "object_id": victim}])
        if committed(done, f"{label} dies", errors) and len(woke(done)) != wanted:
            errors.append(f"{label} died: the non-Recruit watch scheduled {len(woke(done))}, wanted {wanted}")
    unseen = viktor()
    unseen["objects"]["u1"].pop("tags")
    done = resolve(unseen, kill_u1)
    if done.get("committed") or done.get("reason_code") != "object_tags_unknown":
        errors.append(f"a unit whose tags were never observed died and the watch did not refuse by name: "
                      f"{done.get('committed')} {done.get('reason_code')}")

    # --- "When you kill a unit with a spell" (Core 428.5) ------------------------------------------------------
    def spell(state, effects, *, spell_id="sp", controller="p1"):
        """`controller`'s spell `spell_id` on the Chain resolves `effects` (its card goes to the trash)."""
        state["objects"][spell_id] = {"owner": controller, "controller": controller, "kind": "spell", "base_might": 0,
                                      "might_modifiers": [], "damage": 0, "exhausted": False}
        state.setdefault("chain_items", {})["sp-item"] = {"card": spell_id, "controller": controller}
        other = "p2" if controller == "p1" else "p1"
        timing = fixture(priority=other, items=[item("sp-item", controller, "spell", "default", "finalized")],
                         passes=["p1", "p2"])
        if controller != "p1":
            timing.update({"turn_player": controller, "turn_order": [controller, "p1"], "players": [controller, "p1"]})
        return resolve_with_program(timing, "sp-item", state, {**program("sp-effects", *effects), "controller": controller})

    def ability(state, effects, *, source):
        """p1's ability whose source is `source` resolves `effects` (no card leaves the Chain)."""
        entry = {**item("ab-1", "p1", "ability", "triggered", "finalized", "standard"), "source_object": source,
                 "effect_program_id": "ab-effects", "optional_at_finalize": False, "trigger_kind": "triggered",
                 "batch_sequence": 0, "batch_id": "b"}
        timing = fixture(priority="p2", items=[entry], passes=["p1", "p2"])
        return resolve_with_program(timing, "ab-1", state, {**program("ab-effects", *effects), "source_object": source})

    SPELL_KILL = {"kinds": ["died"], "scope": "any", "filter": {"object_kind": "unit", "killed_by_your_spell": True}}

    def phoenix_board(zone="trash", functions_from=TRASH):
        state = board()
        card(state, "ph", zone, watch=SPELL_KILL, functions_from=functions_from)
        return state

    kill_u2 = [{"op": "kill", "effect_id": "k", "object_id": "u2"}]
    for label, run, wanted in (
            ("p1's spell kills an enemy unit (428.5.b)", lambda: spell(phoenix_board(), kill_u2), 1),
            ("p1's spell deals lethal damage; the Cleanup kills (428.5.c)",
             lambda: spell(phoenix_board(), [{"op": "deal_damage", "effect_id": "d", "object_id": "u2", "amount": 9}]), 1),
            ("p1's spell kills the watching card itself on the board (383.2.c.1)",
             lambda: spell(phoenix_board("base"), [{"op": "kill", "effect_id": "k", "object_id": "ph"}]), 1),
            ("an ability originating from p1's spell in the trash kills (428.5.d)",
             lambda: ability(card(phoenix_board(), "sp0", "trash", kind="spell"), kill_u2, source="sp0"), 1),
            ("the same kill by a board watcher (no functions_from) in the trash",
             lambda: spell(phoenix_board(functions_from=None), kill_u2), 0),
            ("p2's spell kills p1's unit", lambda: spell(phoenix_board(), kill_u1, controller="p2"), 0),
            ("a unit's ability kills", lambda: ability(phoenix_board(), kill_u2, source="u1"), 0),
            ("a program kill with no card on the Chain (a resolved effect, not a spell)", lambda: resolve(phoenix_board(), kill_u2), 0),
            ("p1's spell makes a damaged unit's damage lethal without dealing it (not 428.5.c)",
             lambda: spell(_damaged(phoenix_board()), [{"op": "modify_might", "effect_id": "mm", "object_id": "u2", "amount": -3,
                                                       "duration": "this_turn", "source": "sp-item"}]), 0)):
        done = run()
        if committed(done, label, errors) and len(woke(done)) != wanted:
            errors.append(f"{label}: 'When you kill a unit with a spell' scheduled {len(woke(done))}, wanted {wanted}")

    # --- the clause grammar -----------------------------------------------------------------------------------
    grammar = CG.load_grammar()
    for text, extra in (("When you play your second card in a turn, draw 1.", {"watch": SECOND}),
                        ("When another non-Recruit unit you control dies, draw 1.", {"watch": NON_RECRUIT}),
                        ("When you discard me, draw 1.", {"watch": DISCARD_ME, "functions_from": TRASH}),
                        ("When you kill a unit with a spell, draw 1.",
                         {"watch": {"kinds": ["died"], "scope": "any",
                                    "filter": {"object_kind": "unit", "killed_by_your_spell": True}}})):
        got = CG.compile_clause(text, grammar)
        fields = ((got.get("passive") or {}).get("object_fields") or {})
        built = (fields.get("event_triggers") or [{}])[0]
        if got.get("unsupported") or set(fields) != {"event_triggers"} or any(built.get(k) != v for k, v in extra.items()) \
                or set(built) - set(extra) != {"trigger_id", "controller", "source_object", "controller_order",
                                                "effect_program_id", "optional_at_finalize"} \
                or [e.get("op") for e in got.get("program_effects") or []] != ["draw"]:
            errors.append(f"{text!r} did not lower to event_triggers {extra}: {got.get('reason_code')} {fields}")
    for text in ("When you play your third card in a turn, draw 1.", "When another unit you control dies, draw 1.",
                 "When an opponent discards me, draw 1.", "When a non-Recruit unit you control dies, draw 1.",
                 "When you kill a unit, draw 1.", "When an opponent kills a unit with a spell, draw 1."):
        got = CG.compile_clause(text, grammar)
        if not got.get("unsupported"):
            errors.append(f"the near miss {text!r} was lowered as {got.get('production_id')}")

    if errors:
        print("FAILED: trigger zones and watch facts")
        for error in errors:
            print("  - " + error)
        return 1
    print("OK: functions_from (the trash, nowhere else, read after the event), 'When you discard me', a Conquer "
          "trigger from the trash, the Nth card played this turn, a non-Recruit death; grammar rows and near misses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
