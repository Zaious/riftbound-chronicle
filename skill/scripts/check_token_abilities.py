#!/usr/bin/env python3
"""A token card's printed activated abilities (set 2: the Gold gear token, "kill this and exhaust it: add one Power of
any Domain" as a Reaction-timed [Add]).

On a synthetic catalogue whose token "goldtest" is such a gear token:

  T1 catalogue   a token record may carry activated abilities with the programs they run; one whose ability runs a
                 program the token does not have, or one with programs and no abilities, is refused
  T2 made        play_token carrying the abilities makes a token whose ability ids are namespaced by the new object,
                 whose program is the token card's ("goldtest#add"), and whose "$token" is the token itself
  T3 listed      with the token ready, the legal actions list its ability (the program found on the catalogue's token)
  T4 used        activated, the cost is paid - the token exhausted and killed - and p1 has one more Power
  T5 consistent  a card program making the token with other abilities than the catalogue records is refused
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_space as A  # noqa: E402
import closed_environment as CE  # noqa: E402
import play_space as PS  # noqa: E402
import play_transaction as PT  # noqa: E402
import rules_core as RC  # noqa: E402
from check_play_space import enumerate_for, environment  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, RULE_NUMBERING, apply_program, find_location  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

FAILS: list[str] = []
ROW = {"cost": {"energy": 0, "power": {}, "exhaust": True,
                "additional": [{"cost_id": "kill-this", "mandatory": True,
                                "payment": {"kind": "kill_this", "object_id": "$token"}}]},
       "effect_program_id": "add", "timing": "reaction", "ability_kind": "add"}
ADD = {"effects": [{"op": "add_resource", "effect_id": "add", "player": "$controller", "resource": "power",
                    "universal": True, "amount": 1}]}
MAKE = {"op": "play_token", "effect_id": "gold", "owner": "$controller", "controller": "$controller", "token_kind": "gear",
        "base_might": 0, "token_id": "goldtest", "object_id_ref": {"kind": "fresh"},
        "destination": {"kind": "base", "player": "$controller"}, "tags": ["Gold"],
        "activated_abilities": {"a1": copy.deepcopy(ROW)}}


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + str(detail)) if detail != '' and not ok else ''}")
    if not ok:
        FAILS.append(name)


def catalogue(make=MAKE, token=None) -> dict:
    value = {
        "schema_version": CE.CATALOGUE_VERSION,
        "environment": {"format": "1v1", "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING,
                        "card_pool": "synthetic"},
        "cards": {
            "Miner": {"object": {"kind": "spell", "printed_cost": {"energy": 1, "power": {}}, "domains": ["fury"]},
                      "programs": {"play": {"effects": [copy.deepcopy(make)]}}},
            "Pawn": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1, "domains": ["calm"]}},
            "Field": {"object": {"kind": "battlefield"}},
        },
        "tokens": {"goldtest": token or {"kind": "gear", "base_might": 0, "keywords": [], "tags": ["Gold"],
                                         "activated_abilities": {"a1": copy.deepcopy(ROW)}, "programs": {"add": ADD}}},
        "catalogue_hash": "",
    }
    value["catalogue_hash"] = CE.catalogue_hash(value)
    return value


def main() -> int:
    cat = catalogue()
    check("T1 a token with abilities and their programs validates", not CE.validate_catalogue(cat), CE.validate_catalogue(cat))
    missing = catalogue(token={"kind": "gear", "base_might": 0, "keywords": [], "tags": ["Gold"],
                               "activated_abilities": {"a1": copy.deepcopy(ROW)}, "programs": {"other": ADD}})
    check("T1 an ability running a program the token lacks is refused", bool(CE.validate_catalogue(missing)))
    half = catalogue(token={"kind": "gear", "base_might": 0, "keywords": [], "tags": ["Gold"], "programs": {"add": ADD}})
    check("T1 programs without abilities are refused", bool(CE.validate_catalogue(half)))
    other = dict(copy.deepcopy(MAKE), activated_abilities={"a1": {**copy.deepcopy(ROW), "timing": "default"}})
    check("T5 a card making the token with other abilities than recorded is refused",
          bool(CE.validate_catalogue(catalogue(make=other))))

    state = environment(cat, [("a", "Pawn", "p1", "base")])
    program = CE.instantiate_program(cat, "Miner", "play", {"$controller": "p1", "$opponent": "p2", "$chain_item": "i",
                                                             "$source_object": "m", "$card": "m"})
    made = apply_program(state, program)
    check("T2 the program makes the token", made.get("committed"), made.get("reason") or made.get("errors"))
    if not made.get("committed"):
        print(f"check_token_abilities: FAILED {', '.join(FAILS)}")
        return 1
    after = made["next_state"]
    token = next(o for o, obj in after["objects"].items() if obj.get("token_id") == "goldtest")
    rows = after["objects"][token].get("activated_abilities") or {}
    row = rows.get(f"{token}:a1") or {}
    check("T2 its ability is namespaced, runs the token card's program, and names the token as its own",
          list(rows) == [f"{token}:a1"] and row.get("effect_program_id") == "goldtest#add"
          and row["cost"]["additional"][0]["payment"]["object_id"] == token, rows)

    after["objects"][token]["exhausted"] = False
    listed = [a for a in A.enumerated_actions(enumerate_for(after, cat), "activate_ability") if a["declaration"]["card"] == token]
    check("T3 the token's ability is a legal action", len(listed) == 1, len(listed))
    if listed:
        declaration = listed[0]["declaration"]
        ability = PS._program(cat, after, token, "add", "p1", declaration["chain_item"]["id"])
        played = PT.play_card(fixture(), after, declaration, effect_program=ability)
        state2 = played.get("next_effect_state") or {}
        if played.get("committed"):
            timing = RC.finalize_oldest_pending(played["next_timing_state"]).get("next_state") or played["next_timing_state"]
            for _ in range(4):
                if RC.next_procedure(timing).get("procedure") == "resolve_newest_finalized":
                    break
                timing = RC.pass_priority(timing, timing["priority"])["next_state"]
            done = resolve_with_program(timing, declaration["chain_item"]["id"], state2, ability)
            state2 = done.get("next_effect_state") or state2
        def pool(st):
            # Domain Power and any-domain (Universal) Power alike
            resources = (st.get("players") or {}).get("p1", {}).get("resources") or {}
            return sum((resources.get("power") or {}).values()) + resources.get("universal_power", 0)
        before_power, power = pool(after), pool(state2)
        check("T4 activated: the token is killed and p1 has one more Power", played.get("committed")
              and find_location(state2, token) != ("player", "p1", "base") and power == before_power + 1,
              (played.get("reason"), find_location(state2, token), before_power, power,
               state2.get("players", {}).get("p1", {}).get("resources")))
    print(f"check_token_abilities: {'FAILED ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
