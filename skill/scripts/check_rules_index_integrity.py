#!/usr/bin/env python3
"""Executable checks for I-01, the rules index's locator/text pairing.

The rules documents are two-column tables: a locator on the left, its text on
the right. An extraction that aligns the two columns line by line drifts as soon
as a text cell wraps, and the result is not a slightly messy index — it is one
where a locator names some other rule's text. That makes wrong citations
retrievable and right ones absent, which is worse for citation than no index.

Everything here runs on synthetic two-column fixtures written in this file. The
licensed documents are not in the public repository and this gate does not need
them: what it checks is the pairing logic, the metric that measures pairing, and
the refusal to call an unmeasured index verified.

The half that does need the documents is `rules_index.py audit-locators`, which
compares named locators against digests taken when their printed pages were read
directly. That is a local audit, it reports `skipped` where the documents are
absent, and it is exercised here only for its skip path.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import rules_index as ri


# A fragment of an invented rulebook, in the shape a correct two-column
# extraction produces: each locator on its own line, followed by its own text.
PAIRED = """101.        Widget Handling
101.1.      A player may hold at most one Widget at a time.
101.1.a.    A Widget still held when the Cleanup begins is discarded by its holder.
101.1.a.1.  Discarding a Widget this way is not an action and does not pass Priority.
101.2.      When a Widget is discarded, its holder gains one Token.
102.        Token Handling
102.1.      Tokens are spent when an effect instructs a player to spend them.
"""

# The same fragment as a line-aligned extraction produces it: the locator column
# runs ahead of the text column, because a wrapped text cell occupies two output
# lines while its locator occupies one. Every row after the first wrap is wrong.
DRIFTED = """101.        Widget Handling
101.1.      A player may hold at most one Widget at a
101.1.a.    time.
101.1.a.1.
102.        A Widget still held when the Cleanup begins is discarded by its
102.1.      holder.
"""


def rows(connection, source_id="doc"):
    return connection.execute(
        "SELECT locator, text FROM chunks WHERE source_id = ? ORDER BY chunk_id",
        (source_id,)).fetchall()


def index_with(folder: Path, extraction: dict | None, name: str) -> Path:
    """A minimal index, optionally carrying an extraction record."""
    path = folder / f"index-{name}.sqlite3"
    connection = sqlite3.connect(path)
    ri.create_schema(connection)
    connection.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("doc", "doc", "Synthetic", "v1", "en-US", "global", "core_rules",
                        "official", "active", None, 1, "doc.pdf", "sha256:0", 1))
    if extraction:
        connection.execute("INSERT INTO extractions VALUES (?, ?, ?, ?, ?, ?)",
                           ("doc", extraction["mode"], extraction["locator_chunks"],
                            extraction["empty_chunks"], extraction["orphan_chunks"],
                            extraction["misfit_rate"]))
    connection.commit()
    connection.close()
    return path


def measure(label, fixture, failures):
    """The metric, with a crash reported rather than raised.

    A gate that dies inside the module it is checking has a correct exit code
    and says nothing about what broke, and everything after it never runs.
    """
    try:
        return ri.pairing_integrity([fixture])
    except Exception as exc:  # noqa: BLE001 - reporting is the point
        failures.append(f"measuring the {label} fixture raised {type(exc).__name__}: {exc}")
        return {"locator_chunks": 0, "empty_chunks": 0, "orphan_chunks": 0, "misfit_rate": None}


def main() -> int:
    failures: list[str] = []

    # --- the metric separates a paired extraction from a drifted one --------
    paired = measure("paired", PAIRED, failures)
    drifted = measure("drifted", DRIFTED, failures)
    if paired["misfit_rate"] != 0.0:
        failures.append(f"a correctly paired fixture must measure 0.0, got {paired}")
    if drifted["misfit_rate"] is None or drifted["misfit_rate"] <= ri.MISFIT_THRESHOLD:
        failures.append(f"a drifted fixture must measure worse than the threshold, got {drifted}")
    if drifted["empty_chunks"] < 1 or drifted["orphan_chunks"] < 1:
        failures.append(f"the drift should show up as both an empty chunk and a mid-sentence "
                        f"one; got {drifted}")
    # The metric must not need the source document to say any of that. The
    # drifted fixture carries one locator fewer only because its last row has
    # no text left to give, which is itself the drift.
    if paired["locator_chunks"] < drifted["locator_chunks"]:
        failures.append("the paired fixture should not find fewer locators than the drifted one")

    # The pattern that finds a locator in a page and the one that recognises a
    # locator on its own must be the same shape. They were separate once and
    # drifted, and the integrity metric silently stopped counting the deepest
    # locators — the exact rules the drift was hiding.
    for sample in ("101", "101.1", "101.1.a", "101.1.a.1", "338.1.a.7", "312.1.b.1"):
        found = ri.RULE_START.match(f"{sample}. text")
        if not found or found.group(1).rstrip(".") != sample:
            failures.append(f"RULE_START does not find {sample}")
        if not ri.LOCATOR_ONLY.match(sample):
            failures.append(f"LOCATOR_ONLY does not recognise {sample}, so the metric skips it")
    for not_a_locator in ("1", "12", "abc", "1.2.3"):
        if ri.LOCATOR_ONLY.match(not_a_locator):
            failures.append(f"LOCATOR_ONLY accepts {not_a_locator!r}, which is not a rule locator")

    # --- locators nest to arbitrary depth ----------------------------------
    # 101.1.a.1 alternates digits and letters twice. A pattern that allows one
    # trailing letter folds it into its parent, and a rule that is not its own
    # chunk cannot be cited at all.
    paired_locators = [locator for locator, _ in ri.split_page(PAIRED, 1)]
    for expected in ("101", "101.1", "101.1.a", "101.1.a.1", "101.2", "102", "102.1"):
        if expected not in paired_locators:
            failures.append(f"{expected} is not its own chunk, so nothing can cite it")
    deep = next((body for locator, body in ri.split_page(PAIRED, 1) if locator == "101.1.a.1"), "")
    if "not an action" not in deep:
        failures.append("101.1.a.1 does not carry its own text")
    if "not an action" in next((b for l, b in ri.split_page(PAIRED, 1) if l == "101.1.a"), ""):
        failures.append("101.1.a swallowed its child's text")

    # --- the pairing itself -------------------------------------------------
    by_locator = dict(ri.split_page(PAIRED, 1))
    expectations = {
        "101.1": "at most one Widget",
        "101.1.a": "Cleanup begins is discarded",
        "101.2": "gains one Token",
        "102.1": "spent when an effect",
    }
    for locator, fragment in expectations.items():
        if fragment not in by_locator.get(locator, ""):
            failures.append(f"{locator} does not carry its own text: {by_locator.get(locator)!r}")
    # And the drifted fixture must get it wrong, or the fixture proves nothing.
    drifted_by_locator = dict(ri.split_page(DRIFTED, 1))
    if "at most one Widget at a time" in drifted_by_locator.get("101.1", ""):
        failures.append("the drifted fixture pairs correctly, so it demonstrates nothing")

    # --- the extraction mode is chosen by measurement, not fixed ------------
    # Without this the mode list could be pinned back to the one that drifts and
    # every check above would still pass, because they all run on text this file
    # wrote rather than on anything extracted.
    if len(ri.PDF_TEXT_MODES) < 2:
        failures.append(f"a single extraction mode is a fixed choice, not a measured one: "
                        f"{list(ri.PDF_TEXT_MODES)}")
    tried: list[str] = []

    def candidate(mode, fixture):
        tried.append(mode)
        return (mode, [fixture])

    chosen = ri.choose_extraction(candidate(mode, fixture) for mode, fixture in
                                  (("drifting-mode", DRIFTED), ("pairing-mode", PAIRED)))
    if chosen is None or chosen[1]["mode"] != "pairing-mode":
        failures.append(f"the better-paired extraction must win however the modes are ordered; "
                        f"got {chosen and chosen[1]}")
    if chosen and chosen[1]["misfit_rate"] != 0.0:
        failures.append("the chosen extraction must carry the score it won with")

    tried.clear()
    first_wins = ri.choose_extraction(candidate(mode, fixture) for mode, fixture in
                                      (("pairing-mode", PAIRED), ("drifting-mode", DRIFTED)))
    if first_wins is None or first_wins[1]["mode"] != "pairing-mode":
        failures.append("a perfectly paired first candidate must win")
    if tried != ["pairing-mode"]:
        failures.append(f"a perfect first candidate should stop the search, not run the rest; "
                        f"tried {tried}")

    # A candidate that could not be extracted at all loses to one that could.
    unmeasurable = ri.choose_extraction([("broken", None), ("pairing-mode", [PAIRED])])
    if unmeasurable is None or unmeasurable[1]["mode"] != "pairing-mode":
        failures.append("an extraction that produced nothing must not win")

    # And when nothing extracted, the answer is "nothing", not an empty
    # document that would index as a perfectly paired zero-rule corpus. The
    # caller falls back to another extractor on None; on an empty result it
    # would index a document with no rules in it and call that fine.
    if ri.choose_extraction([("broken", None), ("also-broken", None)]) is not None:
        failures.append("with every candidate unextractable the choice is None, so the caller "
                        "can fall back rather than index an empty document")

    # --- an index that cannot say how it paired is not verified -------------
    with tempfile.TemporaryDirectory(prefix="rules-index-integrity-") as folder:
        root = Path(folder)
        unscored = ri.integrity_status(index_with(root, None, "unscored"))
        if unscored["status"] != "locator_integrity_unverified":
            failures.append(f"an index with no extraction record must be unverified: {unscored}")

        good = ri.integrity_status(index_with(root, {
            "mode": "-table", "locator_chunks": 100, "empty_chunks": 0,
            "orphan_chunks": 0, "misfit_rate": 0.0}, "paired"))
        if good["status"] != "locator_integrity_verified":
            failures.append(f"a measured, well-paired index must be verified: {good}")

        bad = ri.integrity_status(index_with(root, {
            "mode": "-layout", "locator_chunks": 100, "empty_chunks": 20,
            "orphan_chunks": 20, "misfit_rate": 0.4}, "drifted"))
        if bad["status"] != "locator_integrity_failed":
            failures.append(f"an index paired worse than the threshold must fail, not warn: {bad}")
        if "0.4" not in bad["reason"]:
            failures.append(f"the failure must name the rate it failed at: {bad['reason']}")

        # The local audit is skipped, not passed, where the licensed document
        # the anchors name is absent. A skip that reported success would make
        # every machine without the PDF look like a verified one.
        skipped = ri.audit_locators(index_with(root, None, "no-document"))
        if skipped["status"] != "skipped":
            failures.append(f"the locator audit must skip where its document is absent: {skipped}")
        if skipped["checked"] != 0:
            failures.append("a skipped audit checked nothing and must say so")
        if skipped["locator_integrity"] != "locator_integrity_unverified":
            failures.append("a skipped audit still reports the index's integrity status")

    # --- the anchors file carries digests, not rules text -------------------
    anchors = ri.load_json(ri.ANCHORS_PATH)
    if not anchors["anchors"]:
        failures.append("the anchors file carries no anchors")
    for anchor in anchors["anchors"]:
        if set(anchor) != {"locator", "page", "shape", "text_sha256", "length"}:
            failures.append(f"anchor {anchor.get('locator')} carries fields beyond a digest")
        if not str(anchor.get("text_sha256", "")).startswith("sha256:"):
            failures.append(f"anchor {anchor.get('locator')} must carry a digest")
    if len(set(a["page"] for a in anchors["anchors"])) < 3:
        failures.append("the anchors must sample more than a couple of pages")
    if {a["shape"] for a in anchors["anchors"]} != {"single", "wrapped"}:
        failures.append("the anchors must include rules whose text wraps and rules whose text "
                        "does not; wrapping is what breaks the pairing")
    for page in anchors["verified_pages"]:
        if not any(a["page"] == page for a in anchors["anchors"]):
            failures.append(f"page {page} is listed as verified but contributes no anchor")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) in the rules index integrity checks")
        return 1

    print(f"rules index locator integrity: paired fixture {paired['misfit_rate']}, "
          f"drifted fixture {drifted['misfit_rate']} (threshold {ri.MISFIT_THRESHOLD})")
    print(f"extraction modes tried, best kept: {list(ri.PDF_TEXT_MODES)}")
    print(f"anchors for the local audit: {len(anchors['anchors'])} digests over pages "
          f"{anchors['verified_pages']}, both single-line and wrapped; no rules text in the file")
    print("an index with no extraction record reports locator_integrity_unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
