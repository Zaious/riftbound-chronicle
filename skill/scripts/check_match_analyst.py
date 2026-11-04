#!/usr/bin/env python3
"""Match Analyst: the four fixture logs' boundaries, the engine-trace path, determinism, and Review/Commentary agreement.

  fixtures     each log in skill/data/match_analyst_fixtures, analyzed from its own perspective, must keep the
               obligations its expected_analysis_boundary states: events it may not use are absent from all three
               artifacts (and no card only they named appears anywhere), decisions it cannot grade are
               insufficient_information, a later reveal is never evidence for an earlier decision, every declared
               contradiction is found and none is narrated as confirmed, and the complete log is not abstained on
  trace        a small engine trace built here: a pass in a closed state while a Reaction was playable is
               missed_response_window; the opponent's draw and options do not reach a player perspective
  determinism  the same input gives byte-identical artifacts
  agreement    a commentary segment calling a contested event confirmed, or a review citing a later event, is caught
  schemas      the artifacts validate against skill/schemas/match-*.schema.json (when jsonschema is installed)
  runner       `match_analyst_runner.py analyze` writes the three files from another working directory

    python skill/scripts/check_match_analyst.py [--trace FILE]   (FILE: a trace from `match_analyst_runner.py trace`)
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
FIXTURES = SKILL_DIR / "data" / "match_analyst_fixtures"
SCHEMAS = SKILL_DIR / "schemas"
sys.path.insert(0, str(SCRIPT_DIR))

import match_analyst as MA  # noqa: E402

errors: list[str] = []


def fail(where: str, why: str) -> None:
    errors.append(f"{where}: {why}")


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def source_ids(analysis: dict, eids) -> set[str]:
    by = {e["event_id"]: e for e in analysis["timeline"]}
    return {s for eid in eids if eid in by for s in by[eid]["source_event_ids"]}


def check_fixture(path: Path) -> None:
    log = json.loads(path.read_text(encoding="utf-8"))
    name = path.name
    out = MA.run(log, length="full")
    a, r, c = out["analysis"], out["review"], out["commentary"]
    for p in out["problems"]:
        fail(name, p)
    boundary = log.get("expected_analysis_boundary") or {}
    text = dump([a, r, c])
    used_sources = {s for e in a["timeline"] for s in e["source_event_ids"]}

    banned = set(boundary.get("must_not_use") or [])
    if banned & used_sources:
        fail(name, f"uses events it may not: {sorted(banned & used_sources)}")
    # a card only the banned events named must not appear anywhere in the output
    banned_cards, usable_cards = set(), set()
    for ev in log["events"]:
        cards = [(ev.get("action") or {}).get("card")] + list((ev.get("action") or {}).get("cards") or [])
        (banned_cards if ev["event_id"] in banned else usable_cards).update(x for x in cards if x)
    for card in sorted(banned_cards - usable_cards):
        if card in text:
            fail(name, f"the card {card!r} reached the output, though only an event it may not use named it")

    items = {i["decision_id"]: i for i in r["items"]}
    for d in boundary.get("must_classify_insufficient") or []:
        if (items.get(d) or {}).get("classification") != "insufficient_information":
            fail(name, f"{d} must be insufficient_information, got {(items.get(d) or {}).get('classification')}")
    for event_ref, decision_ref in (boundary.get("must_not_use_before") or {}).items():
        item = items.get(decision_ref)
        if item is None:
            fail(name, f"{decision_ref} is not reviewed")
            continue
        if event_ref in source_ids(a, item["information"]["evidence_events"]):
            fail(name, f"{decision_ref} is graded with {event_ref}, which came after it")
        if event_ref not in source_ids(a, (item.get("hindsight_guard") or {}).get("later_events", [])):
            fail(name, f"{decision_ref} does not name {event_ref} as hindsight it excluded")
    for d, expectation in (boundary.get("expected_classification") or {}).items():
        allowed = [cls for cls in MA.CLASSIFICATIONS if cls in expectation]
        if (items.get(d) or {}).get("classification") not in allowed:
            fail(name, f"{d} is {(items.get(d) or {}).get('classification')}, expected one of {allowed}")

    if log.get("fixture_kind") == "contradictory":
        declared = {(x["field"], tuple(sorted(x["events"]))) for x in log.get("declared_contradictions") or []}
        found = {(x["field"], tuple(sorted(source_ids(a, x["events"])))) for x in a["contradictions"]}
        if declared != found:
            fail(name, f"contradictions found {sorted(found)}, declared {sorted(declared)}")
    contested = {e for x in a["contradictions"] for e in x["events"]}
    for seg in c["segments"]:
        if seg["label"] == "confirmed" and contested & set(seg["event_ids"]):
            fail(name, f"{seg['segment_id']} narrates a contested event as confirmed")
    if log.get("fixture_kind") == "complete":
        if any(i["classification"] == "insufficient_information" for i in r["items"]):
            fail(name, "abstains on a complete log")
        if any(s["label"] == "unknown" for s in c["segments"]):
            fail(name, "labels part of a complete log unknown")
        if not a["engine_checks"] or any(x["outcome"] != "supported" for x in a["engine_checks"]):
            fail(name, "the complete log's actions are not all bound to supported engine timing checks")

    again = MA.run(copy.deepcopy(log), length="full")
    for key in ("analysis", "review", "commentary"):
        if dump(again[key]) != dump(out[key]):
            fail(name, f"{key} is not deterministic")
    schema_check(name, out)


def schema_check(name: str, out: dict) -> None:
    try:
        import jsonschema
    except ImportError:
        return
    for key in ("analysis", "review", "commentary"):
        schema = json.loads((SCHEMAS / f"match-{key}.schema.json").read_text(encoding="utf-8"))
        for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors(out[key]), key=str)[:3]:
            fail(name, f"{key} schema: {list(e.path)} {e.message[:120]}")


def synthetic_trace() -> dict:
    """Two players; p1 plays a unit; p2 draws; p2 passes on a Chain while holding a playable Reaction; p1 scores."""
    def view(turn, label, priority, chain=()):
        return {"turn": turn, "turn_player": "p1", "phase": "main", "state_label": label, "priority": priority,
                "focus": None, "showdown": {"active": False}, "chain": [{"card": x} for x in chain],
                "points": {"p1": 0, "p2": 0}, "battlefields": {}}
    h = {"timing": "sha256:" + "0" * 64, "effect": "sha256:" + "1" * 64}
    opts_p1 = {"complete_action_set": False, "count": 2, "abstained": [], "items": [
        {"kind": "play_card", "card": "Pakaa Cub", "timing": "default", "chosen": True, "add_ability": False},
        {"kind": "end_main_phase", "chosen": False, "add_ability": False}]}
    opts_p2 = {"complete_action_set": False, "count": 2, "abstained": [], "items": [
        {"kind": "pass_priority", "chosen": True, "add_ability": False},
        {"kind": "play_card", "card": "Ki Barrier", "timing": "reaction", "chosen": False, "add_ability": False}]}
    steps = [
        {"k": 0, "kind": "action", "actor": "p1", "view": view(1, "neutral_open", "p1"), "before": h, "after": h,
         "action": {"kind": "play_card", "card": "Pakaa Cub", "timing": "default"}, "options": opts_p1,
         "changes": [{"kind": "played", "card": "Pakaa Cub", "owner": "p1", "object": "o1", "visibility": "public",
                      "from": {"zone": "hand"}, "to": {"zone": "chain"}},
                     {"kind": "drew", "card": "Incinerate", "owner": "p2", "object": "o9", "visibility": "private:p2",
                      "from": {"zone": "main_deck"}, "to": {"zone": "hand"}}]},
        {"k": 1, "kind": "action", "actor": "p2", "view": view(1, "neutral_closed", "p2", ["Pakaa Cub"]), "before": h,
         "after": h, "action": {"kind": "pass_priority"}, "options": opts_p2, "changes": []},
        {"k": 2, "kind": "procedure", "label": "task:scoring", "answers": [], "view": view(1, "neutral_open", "p1"),
         "before": h, "after": h, "changes": [{"kind": "scored", "player": "p1", "from": 0, "to": 1, "delta": 1,
                                                "visibility": "public"}]}]
    return {"schema_version": MA.TRACE_VERSION, "source": {"kind": "engine_replay", "steps_replayed": 3,
                                                           "hashes_verified": True, "is_real_match": False},
            "ruleset": {}, "players": {"p1": {"legend": "Rengar - Pridestalker"}, "p2": {"legend": "Rengar - Pridestalker"}},
            "start": h, "final": h, "steps": steps, "end": {"outcome": "truncated"}, "trace_hash": "sha256:" + "2" * 64}


def check_trace(trace: dict, name: str, expect: dict | None = None) -> None:
    for perspective in ("omniscient_replay", "player1"):
        out = MA.run(trace, perspective=perspective)
        for p in out["problems"]:
            fail(f"{name}/{perspective}", p)
        schema_check(f"{name}/{perspective}", out)
        if perspective == "player1":
            mine = {e["actor"] for e in out["analysis"]["timeline"] if e.get("kind") == "drew" and e["data"].get("card")}
            if "p2" in mine:
                fail(name, "p2's drawn card reached p1's perspective")
            if any(i["actor"] != "p1" for i in out["review"]["items"]):
                fail(name, "p1's perspective reviews p2's decisions, whose options it cannot see")
        if expect and perspective == "omniscient_replay":
            got = {i["decision_id"]: i["classification"] for i in out["review"]["items"]}
            if got != expect:
                fail(name, f"review classifications {got}, expected {expect}")
            if "Incinerate" not in dump(out["analysis"]):
                fail(name, "the omniscient analysis lost p2's drawn card")
        if expect and perspective == "player1" and "Incinerate" in dump([out["analysis"], out["review"], out["commentary"]]):
            fail(name, "p2's drawn card is named in p1's artifacts")


def check_agreement_negative() -> None:
    log = json.loads((FIXTURES / "contradictory-record.json").read_text(encoding="utf-8"))
    out = MA.run(log)
    a, r, c = out["analysis"], out["review"], copy.deepcopy(out["commentary"])
    contested = a["contradictions"][0]["events"][0]
    c["segments"].append({"segment_id": "s999", "level": "event", "event_ids": [contested], "label": "confirmed",
                          "text": {"zh-Hant": "x", "en": "x"}})
    if not MA.agreement_problems(a, r, c):
        fail("agreement", "a contested event narrated as confirmed was not caught")
    log = json.loads((FIXTURES / "perspective-safe-hidden.json").read_text(encoding="utf-8"))
    out = MA.run(log)
    a, r = out["analysis"], copy.deepcopy(out["review"])
    r["items"][0]["information"]["evidence_events"].append(a["timeline"][-1]["event_id"])
    if not MA.agreement_problems(a, r, out["commentary"]):
        fail("agreement", "a review citing an event after its decision was not caught")


def check_runner() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "match_analyst_runner.py"), "analyze", "--log",
                               str(FIXTURES / "perspective-safe-hidden.json"), "--out-dir", tmp],
                              cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            fail("runner", f"exit {proc.returncode}: {proc.stdout[-300:]} {proc.stderr[-300:]}")
        for n in ("analysis", "review", "commentary"):
            if not (Path(tmp) / f"{n}.json").is_file():
                fail("runner", f"{n}.json not written")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", help="also check a trace written by match_analyst_runner.py trace")
    args = parser.parse_args(argv)
    fixtures = sorted(FIXTURES.glob("*.json"))
    for path in fixtures:
        check_fixture(path)
    check_trace(synthetic_trace(), "synthetic-trace", {"d-0": "reasonable_alternative", "d-1": "missed_response_window"})
    if args.trace:
        check_trace(json.loads(Path(args.trace).read_text(encoding="utf-8")), Path(args.trace).name)
    check_agreement_negative()
    check_runner()
    print(f"[info] Match Analyst: {len(fixtures)} fixture logs, 1 synthetic engine trace"
          + (f", 1 recorded trace ({Path(args.trace).name})" if args.trace else "")
          + "; boundaries, redaction, determinism, agreement, schemas, runner.")
    if errors:
        print("\n[errors]")
        for e in errors:
            print(f"  - {e}")
        print(f"\nFAILED: {len(errors)} Match Analyst violation(s).")
        return 1
    print("\nOK: every fixture keeps its stated boundary; Review and Commentary agree on one confirmed timeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
