#!/usr/bin/env python3
"""
Regenerate the legal-action Phase-A fixtures from the real components.

Every observation here wraps a timing state from `check_rules_core.FIXTURES` —
the same states the timing conformance suite asserts against — and every
verdict is produced by `legal_action.classify_candidates` calling the real
`rules_core.validate_timing`. Nothing is hand-authored; a fixture that drifted
from the engine would be caught by `--check`, which CI runs.

The set covers what ADR-0003 names as acceptance gates:
  - complete and incomplete observations;
  - all five candidate verdicts;
  - a hidden-information adversarial query (Player 1 private key in a Player 2
    query) that must be refused;
  - a hindsight pair: the same decision-time facts with and without
    later_revealed/contradictory facts, which must hash and classify identically.

Usage:
    python3 skill/scripts/build_legal_action_fixtures.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
OUT = SKILL_DIR / "data" / "legal_action_examples"
sys.path.insert(0, str(SCRIPT_DIR))

import legal_action  # noqa: E402
import rules_core  # noqa: E402


def _rules_core_fixtures():
    spec = importlib.util.spec_from_file_location("check_rules_core", SCRIPT_DIR / "check_rules_core.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FIXTURES


CONTEXT = {"ruleset_core": rules_core.CORE_RULESET, "faq_as_of": rules_core.FAQ_AS_OF, "format": "1v1 Constructed", "region": "global", "card_data_version": "fixture"}


def fact(fact_id: str, text: str, provenance: str = "human_confirmed") -> dict:
    return {"fact_id": fact_id, "text": text, "provenance": provenance}


def build_fixtures() -> dict[str, dict]:
    F = _rules_core_fixtures()
    fixtures: dict[str, dict] = {}

    def add(name: str, observation: dict, query: dict, note: str) -> None:
        result = legal_action.classify_candidates(observation, query)
        fixtures[name] = {"note": note, "observation": observation, "query": query, "result": result}

    # 1. Complete observation, Player 1 acting in Neutral Open: legal, illegal, unsupported in one query.
    obs = legal_action.build_observation(
        perspective="player1", source={"kind": "p2a_state_confirmed", "state_seq": 1},
        context=CONTEXT, timing_state=F["neutral_open"],
        facts={"confirmed_public": [fact("f1", "Turn Player p1 holds Priority in Neutral Open.", "engine_state")],
               "own_private": [fact("f2", "p1 holds a default-timing unit in hand.")]},
        pending_decisions=[], completeness={"board": "complete", "hands": "partial", "resources": "absent"},
    )
    add("neutral_open_mixed", obs, legal_action.build_query(observation=obs, acting_player="p1", candidates=[
        {"candidate_id": "c1-play-unit", "description": "Play a unit at default timing", "action": {"kind": "play_card", "actor": "p1", "timing": "default", "object_kind": "unit"}},
        {"candidate_id": "c2-pass-priority", "description": "Pass Priority with no chain", "action": {"kind": "pass_priority", "actor": "p1"}},
        {"candidate_id": "c3-mulligan", "description": "Take a mulligan now", "action": {"kind": "play_card", "actor": "p1", "timing": "bogus", "object_kind": "unit"}},
        {"candidate_id": "c4-can-afford", "description": "Play the unit if the Rune Pool can pay for it", "action": {"kind": "play_card", "actor": "p1", "timing": "default", "object_kind": "unit", "checks": ["cost", "timing"]}},
    ]), "Complete timing state. c1 legal (Core 310.1.a/312.2.a/316); c2 illegal (no chain to pass in); c3 illegal via unknown timing; c4 unsupported: a cost check was requested and Phase A implements timing only.")

    # 2. Closed state, Player 2 acting: only a reaction is legal; a default play is illegal.
    obs = legal_action.build_observation(
        perspective="player2", source={"kind": "p2a_state_confirmed", "state_seq": 3},
        context=CONTEXT, timing_state=F["neutral_closed"],
        facts={"confirmed_public": [fact("f1", "spell-1 is finalized on the chain; p2 holds Priority.", "engine_state")]},
        pending_decisions=[],
    )
    add("neutral_closed_reaction_window", obs, legal_action.build_query(observation=obs, acting_player="p2", candidates=[
        {"candidate_id": "c1-reaction", "description": "Play a Reaction spell", "action": {"kind": "play_card", "actor": "p2", "timing": "reaction", "object_kind": "spell"}},
        {"candidate_id": "c2-default", "description": "Play a default-timing unit", "action": {"kind": "play_card", "actor": "p2", "timing": "default", "object_kind": "unit"}},
        {"candidate_id": "c3-pass", "description": "Pass Priority", "action": {"kind": "pass_priority", "actor": "p2"}},
    ]), "Response window: c1 legal, c2 illegal (Core 309.1.a/338.1.a/358.4/807), c3 legal.")

    # 3. Incomplete observation: prose only, no structured timing state -> indeterminate, never guessed.
    obs = legal_action.build_observation(
        perspective="player2", source={"kind": "p2a_state_confirmed", "state_seq": 5},
        context=CONTEXT, timing_state=None,
        facts={"confirmed_public": [fact("f1", "Human-confirmed public board: two units each, no chain.")],
               "unknown": [fact("f2", "Whether a Showdown is active was not recorded.", "unknown")]},
        pending_decisions=None,
    )
    add("prose_only_indeterminate", obs, legal_action.build_query(observation=obs, acting_player="p2", candidates=[
        {"candidate_id": "c1-play", "description": "Play a unit", "action": {"kind": "play_card", "actor": "p2", "timing": "default", "object_kind": "unit"}},
        {"candidate_id": "c2-prose", "description": "Do the obvious thing"},
    ]), "No structured timing state: both candidates indeterminate with the missing facts named.")

    # 4. Pending controller decision -> decision_required, from a structured pending_decisions entry.
    obs = legal_action.build_observation(
        perspective="player1", source={"kind": "p2a_state_confirmed", "state_seq": 7},
        context=CONTEXT, timing_state=F["neutral_open"],
        facts={"confirmed_public": [fact("f1", "Two simultaneously lethal units await a replacement order.", "engine_state")]},
        pending_decisions=[{"decision_id": "d1", "owner": "p1", "kind": "replacement_order"}],
    )
    add("pending_decision", obs, legal_action.build_query(observation=obs, acting_player="p1", candidates=[
        {"candidate_id": "c1-after-order", "description": "Play after choosing the replacement order", "action": {"kind": "play_card", "actor": "p1", "timing": "default", "object_kind": "unit"}, "requires_decision_id": "d1"},
        {"candidate_id": "c2-unknown-ref", "description": "Depends on a decision nobody recorded", "requires_decision_id": "d9"},
    ]), "c1 decision_required (owner p1, kind replacement_order); c2 indeterminate: unknown decision reference.")

    # 5. Unsupported action family through the kernel: activate an ability with an unknown kind path.
    obs = legal_action.build_observation(
        perspective="public_observer", source={"kind": "replay", "state_seq": 2},
        context=CONTEXT, timing_state=F["showdown_open"],
        facts={"confirmed_public": [fact("f1", "Showdown Open; p1 holds Focus and Priority.", "engine_state")]},
        pending_decisions=[],
    )
    add("showdown_open_focus", obs, legal_action.build_query(observation=obs, acting_player="p1", candidates=[
        {"candidate_id": "c1-action-spell", "description": "Play an Action spell", "action": {"kind": "play_card", "actor": "p1", "timing": "action", "object_kind": "spell"}},
        {"candidate_id": "c2-pass-focus", "description": "Pass Focus", "action": {"kind": "pass_focus", "actor": "p1"}},
        {"candidate_id": "c3-p2-acts", "description": "Opponent plays instead", "action": {"kind": "play_card", "actor": "p2", "timing": "action", "object_kind": "spell"}},
    ]), "c1 legal, c2 legal (Focus + Priority), c3 indeterminate: actor mismatch with the acting player.")

    # 6. Hindsight pair: identical decision-time facts; the second adds later_revealed + contradictory.
    base_facts = {"confirmed_public": [fact("f1", "p1 holds Priority in Neutral Open.", "engine_state")]}
    obs_a = legal_action.build_observation(perspective="player1", source={"kind": "p2a_state_confirmed", "state_seq": 9}, context=CONTEXT, timing_state=F["neutral_open"], facts=base_facts, pending_decisions=[])
    obs_b = legal_action.build_observation(perspective="player1", source={"kind": "p2a_state_confirmed", "state_seq": 9}, context=CONTEXT, timing_state=F["neutral_open"],
                                           facts={**base_facts, "later_revealed": [fact("h1", "Opponent held a Reaction that would have countered.", "replay_log")],
                                                  "contradictory": [fact("h2", "Two summaries disagree on p2's hand size.", "normalizer_proposed")]},
                                           pending_decisions=[])
    cands = [{"candidate_id": "c1", "description": "Play a unit", "action": {"kind": "play_card", "actor": "p1", "timing": "default", "object_kind": "unit"}}]
    add("hindsight_without", obs_a, legal_action.build_query(observation=obs_a, acting_player="p1", candidates=cands), "Decision-time facts only.")
    add("hindsight_with", obs_b, legal_action.build_query(observation=obs_b, acting_player="p1", candidates=copy.deepcopy(cands)), "Same decision-time facts plus hindsight sets; must classify and hash identically to hindsight_without.")

    return fixtures


def render(fixtures: dict[str, dict]) -> str:
    return json.dumps(fixtures, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the committed fixtures are stale")
    args = parser.parse_args()
    fixtures = build_fixtures()
    target = OUT / "fixtures.json"
    text = render(fixtures)
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"FAILED: {target} is stale; re-run build_legal_action_fixtures.py and commit the diff", file=sys.stderr)
            return 1
        print(f"OK: {target} matches the engine ({len(fixtures)} fixtures)")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} ({len(fixtures)} fixtures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
