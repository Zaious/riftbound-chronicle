#!/usr/bin/env python3
"""Executable checks for source-semantic-bindings.v1 (T-02, registry-first).

Two registries are in play. The public fixture registry, marked `fixture`,
is what this gate mutates: it proves the validator refuses each way a registry
could be talked into admitting a reading nobody reviewed — an unknown
template, a source statement posing as a rule reading, a slot value outside
its lexicon, a locator slot that is not the entry's locator, a duplicated
reading, one locator under two hashes, a hash that is not a digest, a slot the
template does not take, a quantity that does not cohere, a binding id that
does not address its content, a reviewed binding with no reviewer or no page,
and an approved registry holding a binding that is not `human_reviewed`.

The approved registry, when the pack paths carry one, is what the corpus
runs consume. Where it is present this gate checks that it is approved and
valid, that every rule claim in the judge-corpus runs is exactly one of its
reviewed bindings by id, that registered hashes agree with the page-read
anchors (I-01), and — where the licensed rules index is installed — that every
registered hash is the digest of the indexed text. Where it is absent the gate
says so: semantic authority is pending, and the corpus gate reports every rule
question as awaiting its binding.

Run time never writes a registry. The maintainer's draft tool marks its output
`proposed`, refuses the approved file name, and the loader refuses proposed and
fixture registries; each is checked here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import rule_consult_command as rcc
import rules_index
import source_semantic_bindings as ssb

SKILL_DIR = Path(__file__).resolve().parent.parent
FIXTURE = SKILL_DIR / "data" / "source_semantic_bindings_fixture.json"
ANCHORS = SKILL_DIR / "data" / "rules_locator_anchors.json"
RUNS = SKILL_DIR / "data" / "judge_corpus_runs.json"
LOCAL_INDEX = rules_index.DEFAULT_RULES_DIR / rules_index.DEFAULT_INDEX_NAME


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures: list[str] = []
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if problems := ssb.validate_registry(fixture):
        failures.append(f"the fixture registry does not validate: {problems[:5]}")
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    if fixture["status"] != "fixture":
        failures.append("the public registry is a fixture and must say so")

    # --- the validator refuses what must not be registered -------------------
    def mutated(mutate, status=None):
        candidate = copy.deepcopy(fixture)
        if status:
            candidate["status"] = status
        mutate(candidate["bindings"])
        return candidate

    def reid(b):
        b["binding_id"] = ssb.binding_id(b, b["template"], b["slots"])

    def with_slot(b, slot, value):
        b["slots"][slot] = value
        reid(b)
        try:
            b["rendered_text_hash"] = ssb.rendered_hash(b["template"], b["slots"])
        except Exception:  # noqa: BLE001 — an unrenderable value is what the validator must name
            pass

    quantity = next(b for b in fixture["bindings"] if b["template"] == "rule_quantity")
    cases = [
        ("a reading of a template the surface does not have",
         mutated(lambda b: (b[0].__setitem__("template", "rule_invented_here"), reid(b[0]))), "unknown template"),
        ("a source statement registered as a rule reading",
         mutated(lambda b: (b[0].__setitem__("template", "official_text_recorded"),
                            b[0].__setitem__("slots", {"locator": b[0]["locator"]}), reid(b[0]))),
         "is not a conditional rule"),
        ("a slot value outside its lexicon",
         mutated(lambda b: with_slot(b[0], next(k for k in b[0]["slots"] if k != "locator"),
                                     "whatever the producer wants")),
         "is not a"),
        ("a reading whose locator slot is another locator",
         mutated(lambda b: with_slot(b[0], "locator", "Core 1")), "must be the entry's locator"),
        ("the same reading registered twice",
         mutated(lambda b: b.append(copy.deepcopy(b[0]))), "repeats a reading"),
        ("one locator under two text hashes",
         mutated(lambda b: (b.append(copy.deepcopy(b[0])), b[-1].__setitem__("text_hash", "sha256:" + "f" * 64),
                            reid(b[-1]))),
         "two different text hashes"),
        ("a hash that is not a digest",
         mutated(lambda b: (b[0].__setitem__("text_hash", "the text of rule 345"), reid(b[0]))), "sha256 digest"),
        ("a reading with a slot its template does not take",
         mutated(lambda b: b[0]["slots"].__setitem__("mood", "confident")), "takes exactly"),
        ("a quantity reading whose relation and number disagree",
         mutated(lambda b: with_slot(next(x for x in b if x["template"] == "rule_quantity"), "value",
                                     None if quantity["slots"]["value"] is not None else 3)),
         "does not cohere"),
        # Content addressing: any of template, slots, version, hash moved
        # without the id moving is refused; the id is the binding.
        ("a binding id that does not address its content",
         mutated(lambda b: b[0].__setitem__("binding_id", "ssb-" + "0" * 24)), "the binding it carries is"),
        ("another binding's reading moved under a kept binding id",
         mutated(lambda b: (b[0].__setitem__("template", b[1]["template"]),
                            b[0].__setitem__("slots", dict(b[1]["slots"])))),
         "the binding it carries is"),
        ("a document version moved under a kept binding id",
         mutated(lambda b: b[0].__setitem__("document_version", "2027-01-01")), "the binding it carries is"),
        ("a text hash moved under a kept binding id",
         mutated(lambda b: b[0].__setitem__("text_hash", "sha256:" + "e" * 64)), "the binding it carries is"),
        ("a lexicon phrase edited under a reviewed binding (the sentence no longer renders the same)",
         mutated(lambda b: b[0].__setitem__("rendered_text_hash", "sha256:" + "c" * 64)),
         "the lexicon moved under a reviewed binding"),
        ("a review status the schema does not know",
         mutated(lambda b: b[0].__setitem__("review_status", "looks fine")), "review_status must be one of"),
        ("an approved registry holding a binding that is not human_reviewed",
         mutated(lambda b: (b[0].__setitem__("review_status", "proposed"), b[0].__setitem__("reviewed_by", None),
                            b[0].__setitem__("reviewed_at", None)), status="approved"),
         "holds only human_reviewed"),
        ("an approved binding with no reviewer",
         mutated(lambda b: b[0].__setitem__("reviewed_by", ""), status="approved"), "names the reviewer"),
        ("an approved binding with a prose review date",
         mutated(lambda b: b[0].__setitem__("reviewed_at", "last week"), status="approved"), "is YYYY-MM-DD"),
        ("an approved binding with no page read",
         mutated(lambda b: b[0].__setitem__("source_page", None), status="approved"), "names the page"),
        ("a proposed registry naming a reviewer",
         mutated(lambda b: b[0].__setitem__("review_status", "proposed"), status="proposed"),
         "not reviewed by anyone"),
        ("a registry status outside the schema",
         mutated(lambda b: None, status="draft"), "status must be one of"),
    ]
    for label, candidate, expected in cases:
        problems = ssb.validate_registry(candidate)
        if not problems:
            failures.append(f"the registry validator accepts {label}")
        elif not any(expected in p for p in problems):
            failures.append(f"{label} was refused, but not by the rule that should have caught it: "
                            f"{problems[:2]}")

    # --- authority: proposed and fixture registries carry none; a reviewed
    # binding is looked up by exact content, and a proposed one is not found.
    for status in ("proposed", "fixture"):
        candidate = copy.deepcopy(fixture)
        candidate["status"] = status
        if status == "proposed":
            for b in candidate["bindings"]:
                b.update(review_status="proposed", reviewed_by=None, reviewed_at=None)
        try:
            ssb.BindingRegistry(candidate)
        except ValueError:
            pass
        else:
            failures.append(f"a {status} registry must be refused by the loader")
    registry = ssb.BindingRegistry(fixture, allow_fixture=True)
    reviewed = next(b for b in fixture["bindings"] if b["review_status"] == "human_reviewed")
    if registry.lookup(reviewed, reviewed["template"], reviewed["slots"]) is None:
        failures.append("a reviewed fixture binding must be found by its exact content")
    other = dict(reviewed, text_hash="sha256:" + "d" * 64)
    if registry.lookup(other, reviewed["template"], reviewed["slots"]) is not None:
        failures.append("a moved text hash must find nothing")
    unreviewed = [b for b in fixture["bindings"] if b["review_status"] != "human_reviewed"]
    if not unreviewed:
        failures.append("the fixture carries no unreviewed binding, so its refusal is not exercised")
    for b in unreviewed:
        if registry.lookup(b, b["template"], b["slots"]) is not None:
            failures.append(f"an unreviewed binding ({b['review_status']}) must carry no authority")

    # --- run time never writes a registry ------------------------------------
    runs = json.loads(RUNS.read_text(encoding="utf-8"))
    proposal = ssb.propose(runs)
    if proposal["status"] != "proposed" or any(b["review_status"] != "proposed" or b["reviewed_by"]
                                              for b in proposal["bindings"]):
        failures.append("the draft tool's output must be marked proposed, reviewed by nobody")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            ssb.write_proposed(proposal, Path(tmp) / ssb.APPROVED_FILENAME)
        except ValueError:
            pass
        else:
            failures.append("the draft tool must refuse to write to the approved registry's file name")
        drafted = ssb.write_proposed(proposal, Path(tmp) / "source_semantic_bindings.proposed.json")
        try:
            ssb.load_registry(drafted)
        except ValueError:
            pass
        else:
            failures.append("the loader must refuse the draft tool's output")
    approved_paths = ssb.approved_registry_paths()
    before = {p: _digest(p) for p in approved_paths}
    fixture_before = _digest(FIXTURE)

    # --- the approved registry on the pack paths, if any ---------------------
    authority = "pending: no approved registry on the pack paths"
    if approved_paths:
        merged = ssb.load_approved()
        payloads = [json.loads(p.read_text(encoding="utf-8")) for p in approved_paths]
        bindings = [b for p in payloads for b in p["bindings"]]
        retriever = rcc.TableRetriever(runs["sources"], {})
        rule_claims, unbound = 0, []
        for question_id, inputs in runs["runs"].items():
            for claim in inputs.get("claims", []):
                template = rcc.CLAIM_TEMPLATES.get(claim["template"])
                if template is None or template["class"] != "conditional_rule":
                    continue
                rule_claims += 1
                retrieval = retriever.retrieve(claim["slots"]["locator"])
                if retrieval.get("status") != "retrieved":
                    unbound.append((question_id, claim["slots"]["locator"], "not retrieved"))
                    continue
                found = merged.lookup(retrieval["record"], claim["template"], claim["slots"])
                if found is None:
                    unbound.append((question_id, claim["slots"]["locator"], "no reviewed binding"))
                elif found["binding_id"] != ssb.binding_id(retrieval["record"], claim["template"], claim["slots"]):
                    unbound.append((question_id, claim["slots"]["locator"], "binding id does not address the claim"))
        for question_id, locator, why in unbound:
            failures.append(f"{question_id} reads {locator}: {why}")
        anchors = json.loads(ANCHORS.read_text(encoding="utf-8"))
        anchor_hash = {f"Core {a['locator']}": a["text_sha256"] for a in anchors["anchors"]}
        anchored = 0
        for entry in bindings:
            expected = anchor_hash.get(entry["locator"])
            if expected is None:
                continue
            anchored += 1
            if entry["text_hash"] != expected:
                failures.append(f"{entry['locator']} is approved under {entry['text_hash'][:23]}…, but the "
                                f"page anchor digests it as {expected[:23]}…")
        audit = "skipped (no local rules index)"
        if LOCAL_INDEX.exists():
            connection = sqlite3.connect(LOCAL_INDEX)
            checked, wrong = 0, []
            try:
                for entry in bindings:
                    row = connection.execute(
                        "SELECT text FROM chunks WHERE source_id = ? AND locator = ?",
                        (f"core-rules-{entry['document_version']}", entry["locator"].split(" ", 1)[1])).fetchone()
                    if row is None:
                        continue
                    checked += 1
                    if ssb.text_digest(row[0]) != entry["text_hash"]:
                        # An index that cut rules at page breaks gave some
                        # readings a digest of the rule's first page only. That
                        # is a reading signed on part of a rule, and it is named
                        # as such: it needs re-review, not a new hash.
                        words = ssb.normalize(row[0]).split(" ")
                        partial = any(ssb.text_digest(" ".join(words[:n])) == entry["text_hash"]
                                      for n in range(1, len(words)))
                        wrong.append((entry["locator"], partial))
            finally:
                connection.close()
            for locator, partial in sorted(set(wrong)):
                failures.append(
                    f"{locator}: approved on a leading part of the indexed text, which continues past "
                    f"where the reviewed text stops; the reading needs re-review against the whole rule"
                    if partial else f"{locator}: the approved hash is not the digest of the indexed text")
            audit = f"checked {checked} against the local index"
        reviewers = sorted({b["reviewed_by"] for b in bindings})
        authority = (f"closed: {len(merged)} reviewed bindings in {len(approved_paths)} file(s); corpus rule "
                     f"claims bound {rule_claims}; page-anchored {anchored}; reviewers {reviewers}; "
                     f"local index audit: {audit}")

    # Running the corpus against the registry changed no registry file.
    judge_runner = __import__("judge_corpus_runner")
    corpus = json.loads((SKILL_DIR / "data" / "judge_corpus.json").read_text(encoding="utf-8"))
    judge_runner.run_corpus(corpus, runs)
    if {p: _digest(p) for p in approved_paths} != before or _digest(FIXTURE) != fixture_before:
        failures.append("running the corpus changed a registry file; run time must never write one")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across source-semantic-bindings.v1")
        return 1

    print(f"source-semantic-bindings.v1: fixture registry {len(fixture['bindings'])} bindings; "
          f"registry mutations refused: {len(cases)}; proposed/fixture refused by the loader; "
          f"draft tool refuses the approved file name")
    print(f"semantic authority: {authority}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
