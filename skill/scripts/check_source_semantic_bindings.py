#!/usr/bin/env python3
"""Executable checks for source-semantic-bindings.v1 (T-02).

The registry is the list of readings the rules text admits, keyed by document,
version, locator and text hash. Three things are checked here:

  * the shipped registry validates, and its validator refuses each of the ways
    a registry could be talked into admitting a reading nothing said —
    an unknown template, a source statement posing as a rule reading, a slot
    value outside its lexicon, a reading whose locator slot is not the entry's
    locator, a duplicated reading, one locator under two hashes, a quantity
    that does not cohere;
  * the registry agrees with the page-verified anchors: where a locator has an
    anchor read off the printed page (I-01), the registry's hash is that
    anchor's digest, so the readings are bound to text someone looked at;
  * the corpus is bound: every rule claim the judge-corpus runs bind is a
    registered reading of the record the runs' retriever returns for it. A
    registry that drifted from the corpus, or a corpus claim nobody registered,
    fails here rather than at the first question that runs.

Where the licensed rules index is installed locally, every registry hash is
also checked against the index's chunk text; that audit is skipped, not
passed, where the index is absent.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from pathlib import Path

import rule_consult_command as rcc
import rules_index
import source_semantic_bindings as ssb

SKILL_DIR = Path(__file__).resolve().parent.parent
REGISTRY = SKILL_DIR / "data" / "source_semantic_bindings.json"
ANCHORS = SKILL_DIR / "data" / "rules_locator_anchors.json"
RUNS = SKILL_DIR / "data" / "judge_corpus_runs.json"
LOCAL_INDEX = rules_index.DEFAULT_RULES_DIR / rules_index.DEFAULT_INDEX_NAME


def main() -> int:
    failures: list[str] = []
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if problems := ssb.validate_registry(payload):
        failures.append(f"the shipped registry does not validate: {problems[:5]}")
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    registry = ssb.BindingRegistry(payload)
    bindings = payload["bindings"]

    # --- the validator refuses what must not be registered -------------------
    def mutated(mutate):
        candidate = copy.deepcopy(payload)
        mutate(candidate["bindings"])
        return candidate

    quantity = next((b for b in bindings if b["template"] == "rule_quantity"), None)
    if quantity is None:
        failures.append("the registry holds no rule_quantity reading, so coherence cannot be exercised")
    cases = [
        ("a reading of a template the surface does not have",
         mutated(lambda b: b[0].__setitem__("template", "rule_invented_here")), "unknown template"),
        ("a source statement registered as a rule reading",
         mutated(lambda b: (b[0].__setitem__("template", "official_text_recorded"),
                            b[0].__setitem__("slots", {"locator": b[0]["locator"]}))),
         "is not a conditional rule"),
        ("a slot value outside its lexicon",
         mutated(lambda b: b[0]["slots"].__setitem__(
             next(k for k in b[0]["slots"] if k != "locator"), "whatever the producer wants")),
         "is not a"),
        ("a reading whose locator slot is another locator",
         mutated(lambda b: b[0]["slots"].__setitem__("locator", "Core 1")), "must be the entry's locator"),
        ("the same reading registered twice",
         mutated(lambda b: b.append(copy.deepcopy(b[0]))), "repeats a reading"),
        ("one locator under two text hashes",
         mutated(lambda b: b.append({**copy.deepcopy(b[0]), "text_hash": "sha256:" + "f" * 64,
                                     "slots": {**b[0]["slots"]}})),
         "two different text hashes"),
        ("a hash that is not a digest",
         mutated(lambda b: b[0].__setitem__("text_hash", "the text of rule 345")), "sha256 digest"),
        ("a reading with a slot its template does not take",
         mutated(lambda b: b[0]["slots"].__setitem__("mood", "confident")), "takes exactly"),
    ]
    if quantity is not None:
        cases.append(("a quantity reading whose relation and number disagree",
                      mutated(lambda b: next(x for x in b if x["template"] == "rule_quantity")["slots"]
                              .__setitem__("value", None if quantity["slots"]["value"] is not None else 3)),
                      "does not cohere"))
    for label, candidate, expected in cases:
        problems = ssb.validate_registry(candidate)
        if not problems:
            failures.append(f"the registry validator accepts {label}")
        elif not any(expected in p for p in problems):
            failures.append(f"{label} was refused, but not by the rule that should have caught it: "
                            f"{problems[:2]}")

    # --- bound to text someone read: the page anchors ------------------------
    anchors = json.loads(ANCHORS.read_text(encoding="utf-8"))
    anchor_hash = {f"Core {a['locator']}": a["text_sha256"] for a in anchors["anchors"]}
    anchored = 0
    for entry in bindings:
        expected = anchor_hash.get(entry["locator"])
        if expected is None:
            continue
        anchored += 1
        if entry["text_hash"] != expected:
            failures.append(f"{entry['locator']} is registered under {entry['text_hash'][:23]}…, but the "
                            f"page anchor digests it as {expected[:23]}…")
    if anchored == 0:
        failures.append("no registered locator has a page anchor; the registry is bound to nothing "
                        "anyone read")

    # --- the corpus is bound ----------------------------------------------
    runs = json.loads(RUNS.read_text(encoding="utf-8"))
    retriever = rcc.TableRetriever(runs["sources"], {})
    rule_claims = 0
    for question_id, inputs in runs["runs"].items():
        for claim in inputs.get("claims", []):
            template = rcc.CLAIM_TEMPLATES.get(claim["template"])
            if template is None or template["class"] != "conditional_rule":
                continue
            rule_claims += 1
            retrieval = retriever.retrieve(claim["slots"]["locator"])
            if retrieval.get("status") != "retrieved":
                failures.append(f"{question_id} reads {claim['slots']['locator']}, which the runs' "
                                f"retriever does not return")
            elif not registry.is_registered(retrieval["record"], claim["template"], claim["slots"]):
                failures.append(f"{question_id} binds {claim['template']} {claim['slots']} and the "
                                f"registry has no such reading of {claim['slots']['locator']}")
    if rule_claims == 0:
        failures.append("the corpus runs bind no rule claim, so the registry covers nothing")

    # --- the local audit: hashes against the index, where it is installed ----
    audit = "skipped (no local rules index)"
    if LOCAL_INDEX.exists():
        connection = sqlite3.connect(LOCAL_INDEX)
        checked, wrong, absent = 0, [], []
        try:
            for entry in bindings:
                body = entry["locator"].split(" ", 1)[1]
                row = connection.execute(
                    "SELECT text FROM chunks WHERE source_id = ? AND locator = ?",
                    (f"core-rules-{entry['document_version']}", body)).fetchone()
                if row is None:
                    absent.append(entry["locator"])
                    continue
                checked += 1
                if ssb.text_digest(row[0]) != entry["text_hash"]:
                    wrong.append(entry["locator"])
        finally:
            connection.close()
        for locator in sorted(set(wrong)):
            failures.append(f"{locator}: the registry's hash is not the digest of the indexed text")
        audit = (f"checked {checked} against the local index"
                 + (f"; not in the index: {sorted(set(absent))}" if absent else ""))

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across source-semantic-bindings.v1")
        return 1

    locators = {(e["document_id"], e["document_version"], e["locator"]) for e in bindings}
    by_template: dict[str, int] = {}
    for entry in bindings:
        by_template[entry["template"]] = by_template.get(entry["template"], 0) + 1
    print(f"source-semantic-bindings.v1: {len(registry)} readings over {len(locators)} locators; "
          f"by template {dict(sorted(by_template.items()))}")
    print(f"registry mutations refused: {len(cases)}; page-anchored locators: {anchored}; "
          f"corpus rule claims bound: {rule_claims}")
    print(f"local index audit: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
