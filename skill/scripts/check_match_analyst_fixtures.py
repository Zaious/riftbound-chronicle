#!/usr/bin/env python3
"""
Validate the Match Analyst example logs and uncertainty fixtures.

Match Analyst is specified and not implemented. There is no runner to test, so
what this checks is the corpus a future implementation will be held to -- and,
just as importantly, that the corpus still contains the cases that make it
worth having.

Four kinds, each defending a different failure:

  complete       -- a log with nothing missing. Without it, a system that
                    labels everything uncertain passes the other three.
  partial        -- gaps that look reconstructible. The failure is a fluent
                    reconstruction presented as observation.
  contradictory  -- assertions that cannot both hold. The failure is picking
                    the branch that reads better and narrating it.
  perspective_safe -- hidden and later-revealed information. Two failures: using
                    what the player could not see, and grading a decision by
                    what was revealed after it.

The properties are re-derived here rather than trusted. A fixture that declares
a contradiction must actually contain one; a fixture that declares an event
unusable must actually have labelled it unreadable from the stated perspective.
A label the checker takes on faith is a label that can quietly become false.

This file asserts nothing about Match Analyst being available: it fails if
SKILL.md starts routing it, because that gate belongs to the activation
checklist and not to whoever adds a fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parent
FIXTURES = SKILL_DIR / "data" / "match_analyst_fixtures"
CARDS = SKILL_DIR / "data" / "riftcodex_cards_raw.json"
SKILL_MD = SKILL_DIR / "SKILL.md"
SPEC = REPO_ROOT / "docs" / "match-analyst" / "MATCH_ANALYST_PRODUCT_SPEC.md"

sys.path.insert(0, str(SCRIPT_DIR))

from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

REQUIRED_KINDS = {"complete", "partial", "contradictory", "perspective_safe"}
STATE_LABELS = {"neutral_open", "neutral_closed", "showdown_open", "showdown_closed"}
PHASES = {"beginning", "main", "combat", "ending"}
# The four uncertainty labels the product spec defines for commentary claims.
CERTAINTIES = {"confirmed", "inferred", "unknown", "hindsight_only"}
PERSPECTIVES = {"player1", "player2", "public_observer", "omniscient_replay"}
PLAYER_PERSPECTIVE = {"player1": "p1", "player2": "p2"}
# The seven Review classifications from the spec. A fixture may only expect one
# of these, so the corpus cannot invent a verdict the system is not defined to
# produce.
CLASSIFICATIONS = {
    "rules_execution_error", "missed_response_window", "strategic_misplay",
    "reasonable_alternative", "outcome_bias", "insufficient_information",
    "unsupported_engine_behavior",
}


def visible_to(event: dict, perspective: str) -> bool:
    """Whether one event is readable from a perspective.

    This is the redaction rule the fixtures encode, written once so the corpus
    can be checked against it instead of against its own labels. It is a test
    helper, not an implementation of the system: it decides visibility, not
    what may be concluded from what is visible.
    """
    visibility = event.get("visibility", "public")
    if perspective == "omniscient_replay":
        return True
    if visibility == "public":
        return True
    if visibility == "revealed_later":
        # Public from the moment of the reveal onward, for every perspective.
        return True
    if visibility.startswith("private:"):
        return visibility.split(":", 1)[1] == PLAYER_PERSPECTIVE.get(perspective)
    return False


def derive_contradictions(events: list[dict]) -> set[tuple[str, str, str]]:
    """Find contradictions in the log without consulting what it declares.

    Two rules, both cheap and both real: an object cannot act after it was
    killed in the same turn, and one turn/phase/state cannot have two different
    Priority or Focus holders.
    """
    found: set[tuple[str, str, str]] = set()

    killed: dict[str, tuple[str, int]] = {}
    for event in events:
        action = event.get("action") or {}
        if action.get("kind") == "object_killed" and action.get("object"):
            killed[action["object"]] = (event["event_id"], event.get("turn"))
    for event in events:
        action = event.get("action") or {}
        acting_object = action.get("unit") or action.get("object")
        if not acting_object or acting_object not in killed:
            continue
        killed_at, killed_turn = killed[acting_object]
        if event["event_id"] == killed_at:
            continue
        if event.get("turn") == killed_turn and events.index(event) > next(
                index for index, item in enumerate(events) if item["event_id"] == killed_at):
            found.add((killed_at, event["event_id"], "object_liveness"))

    # Priority and Focus move constantly, so differing holders are only a
    # contradiction when nothing could have moved them in between: two adjacent
    # events, at the same point of the turn, at least one of which is a bare
    # assertion about who holds what. Comparing every pair in a turn would
    # flag an ordinary Focus pass as a conflict.
    for earlier, later in zip(events, events[1:]):
        kinds = {(earlier.get("action") or {}).get("kind"), (later.get("action") or {}).get("kind")}
        if "state_assertion" not in kinds:
            continue
        if (earlier.get("turn"), earlier.get("phase"), earlier.get("state_label")) != \
           (later.get("turn"), later.get("phase"), later.get("state_label")):
            continue
        for field in ("priority", "focus"):
            if earlier.get(field) is None or later.get(field) is None:
                continue
            if earlier[field] != later[field]:
                found.add((earlier["event_id"], later["event_id"], field))
    return found


def main() -> int:
    errors: list[str] = []
    if not FIXTURES.is_dir():
        print(f"FAILED: missing {FIXTURES.relative_to(REPO_ROOT).as_posix()}")
        return 1

    card_names = {card["name"] for card in json.loads(CARDS.read_text(encoding="utf-8"))}
    paths = sorted(path for path in FIXTURES.glob("*.json"))
    fixtures = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]

    kinds = {fixture.get("fixture_kind") for _, fixture in fixtures}
    if missing := sorted(REQUIRED_KINDS - kinds):
        errors.append(f"the corpus is missing {missing}; each kind defends a different failure and none is optional")
    if extra := sorted(kinds - REQUIRED_KINDS):
        errors.append(f"unknown fixture kind(s) {extra}")

    seen_ids: set[str] = set()
    for path, fixture in fixtures:
        name = path.name
        fixture_id = fixture.get("fixture_id", name)
        if fixture_id in seen_ids:
            errors.append(f"{name}: duplicate fixture_id {fixture_id!r}")
        seen_ids.add(fixture_id)

        if fixture.get("schema_version") != "riftbound-match-log-fixture.v1":
            errors.append(f"{name}: unexpected schema_version {fixture.get('schema_version')!r}")
        provenance = fixture.get("provenance") or {}
        if provenance.get("is_real_match") is not False:
            errors.append(f"{name}: provenance must state is_real_match: false; these are synthetic and must not read as a record of a real player's game")

        ruleset = fixture.get("ruleset") or {}
        if ruleset.get("core") != CORE_RULESET or ruleset.get("faq_as_of") != FAQ_AS_OF:
            errors.append(f"{name}: ruleset {ruleset.get('core')}/{ruleset.get('faq_as_of')} does not match the executable baseline "
                          f"{CORE_RULESET}/{FAQ_AS_OF}; a log reconstructed under a different baseline is a different match")

        perspective = fixture.get("perspective")
        if perspective not in PERSPECTIVES:
            errors.append(f"{name}: perspective {perspective!r} is not one the spec defines")

        events = fixture.get("events") or []
        if not events:
            errors.append(f"{name}: has no events")
        event_ids: set[str] = set()
        for event in events:
            event_id = event.get("event_id")
            if not event_id or event_id in event_ids:
                errors.append(f"{name}: missing or duplicate event_id {event_id!r}")
            event_ids.add(event_id)
            if event.get("state_label") not in STATE_LABELS:
                errors.append(f"{name}/{event_id}: state_label {event.get('state_label')!r} is not one of the four rules states")
            if event.get("phase") not in PHASES:
                errors.append(f"{name}/{event_id}: phase {event.get('phase')!r} is unknown")
            if event.get("certainty") not in CERTAINTIES:
                errors.append(f"{name}/{event_id}: certainty {event.get('certainty')!r} is not a spec label")
            visibility = event.get("visibility", "public")
            if visibility not in ("public", "revealed_later") and not visibility.startswith("private:"):
                errors.append(f"{name}/{event_id}: visibility {visibility!r} is not public, revealed_later, or private:<player>")
            card = (event.get("action") or {}).get("card")
            if card and card not in card_names:
                errors.append(f"{name}/{event_id}: card {card!r} is not in the bundled card database")
            for hand_card in (event.get("action") or {}).get("cards", []):
                if hand_card not in card_names:
                    errors.append(f"{name}/{event_id}: card {hand_card!r} is not in the bundled card database")

        for decision in fixture.get("decision_points") or []:
            if decision.get("at_event") not in event_ids:
                errors.append(f"{name}: decision {decision.get('decision_id')!r} points at unknown event {decision.get('at_event')!r}")
        decision_ids = {decision.get("decision_id") for decision in fixture.get("decision_points") or []}

        boundary = fixture.get("expected_analysis_boundary")
        if boundary is None:
            errors.append(f"{name}: has no expected_analysis_boundary; a log without stated obligations tests nothing")
            continue
        for referenced in boundary.get("must_not_use", []):
            if referenced not in event_ids:
                errors.append(f"{name}: boundary must_not_use names unknown event {referenced!r}")
        for referenced in boundary.get("must_classify_insufficient", []):
            if referenced not in decision_ids:
                errors.append(f"{name}: boundary must_classify_insufficient names unknown decision {referenced!r}")
        for event_ref, decision_ref in (boundary.get("must_not_use_before") or {}).items():
            if event_ref not in event_ids:
                errors.append(f"{name}: boundary must_not_use_before names unknown event {event_ref!r}")
            if decision_ref not in decision_ids:
                errors.append(f"{name}: boundary must_not_use_before names unknown decision {decision_ref!r}")
        for decision_ref, expectation in (boundary.get("expected_classification") or {}).items():
            if decision_ref not in decision_ids:
                errors.append(f"{name}: expected_classification names unknown decision {decision_ref!r}")
            if not any(classification in expectation for classification in CLASSIFICATIONS):
                errors.append(f"{name}: expected_classification for {decision_ref!r} names no spec classification")

        kind = fixture.get("fixture_kind")

        # --- each kind must actually be what it claims ---------------------
        if kind == "complete":
            if any(event.get("certainty") != "confirmed" for event in events):
                errors.append(f"{name}: a complete log must have every event confirmed")
            if fixture.get("uncertainty_ledger"):
                errors.append(f"{name}: a complete log must have an empty uncertainty ledger")
            if any(event.get("gap") for event in events):
                errors.append(f"{name}: a complete log must have no gaps")

        if kind == "partial":
            if not any(event.get("gap") or event.get("certainty") == "unknown" for event in events):
                errors.append(f"{name}: a partial log must actually be missing something")
            if not fixture.get("uncertainty_ledger"):
                errors.append(f"{name}: a partial log must carry an uncertainty ledger")
            if not boundary.get("must_classify_insufficient"):
                errors.append(f"{name}: a partial log must name at least one decision an analysis cannot grade")

        if kind == "contradictory":
            declared = {(entry["field"], tuple(sorted(entry["events"])))
                        for entry in fixture.get("declared_contradictions") or []}
            derived = {(field, tuple(sorted((first, second))))
                       for first, second, field in derive_contradictions(events)}
            if not derived:
                errors.append(f"{name}: declares itself contradictory but no contradiction is derivable from its events")
            for entry in sorted(declared - derived):
                errors.append(f"{name}: declares a contradiction that cannot be derived from the log: {entry}")
            for entry in sorted(derived - declared):
                errors.append(f"{name}: contains an underived contradiction {entry} that declared_contradictions does not list")

        if kind == "perspective_safe":
            if perspective not in PLAYER_PERSPECTIVE:
                errors.append(f"{name}: a perspective-safe fixture must be reviewed from one player's seat")
            hidden = [event for event in events if not visible_to(event, perspective)]
            if not hidden:
                errors.append(f"{name}: contains nothing the stated perspective cannot see, so it tests no redaction")
            hidden_ids = {event["event_id"] for event in hidden}
            declared_hidden = set(boundary.get("must_not_use", []))
            if declared_hidden != hidden_ids:
                errors.append(f"{name}: boundary must_not_use {sorted(declared_hidden)} does not match what the perspective "
                              f"actually hides {sorted(hidden_ids)}")
            if not boundary.get("must_not_use_before"):
                errors.append(f"{name}: must name at least one fact that becomes public later and still may not grade an "
                              "earlier decision; excluding only opponent-private events lets hindsight through")
            for event_ref in boundary.get("must_not_use_before") or {}:
                event = next(item for item in events if item["event_id"] == event_ref)
                if event.get("visibility") != "revealed_later":
                    errors.append(f"{name}/{event_ref}: named as hindsight but not marked revealed_later")

    # --- the corpus must not imply the system is available -----------------
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    routing = skill_text.split("## Choose the mode", 1)[-1].split("##", 1)[0]
    if "match-analyst" in routing:
        errors.append("SKILL.md now routes match-analyst; the activation gate in the product spec decides that, not this corpus")
    if not SPEC.is_file():
        errors.append("the Match Analyst product spec is missing; these fixtures encode obligations it defines")

    print(f"[info] Match Analyst corpus: {len(fixtures)} fixtures covering {sorted(kinds)}; "
          "card names, rules vocabulary, and perspective redaction verified against the bundled data. "
          "The system remains unrouted and unimplemented.")
    if errors:
        print("\n[errors]")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(errors)} Match Analyst fixture violation(s).")
        return 1
    print("\nOK: complete, partial, contradictory, and perspective-safe logs each demonstrate the property they claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
