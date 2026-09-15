#!/usr/bin/env python3
"""Executable checks for I-01, the rules index's locator/text pairing.

The rules documents are two-column tables: a locator on the left, its text on
the right. An extraction that aligns the two columns line by line drifts as soon
as a text cell wraps, and the result is not a slightly messy index — it is one
where a locator names some other rule's text. That makes wrong citations
retrievable and right ones absent, which is worse for citation than no index.

Everything here runs on synthetic two-column fixtures written in this file. The
licensed documents are not in the public repository and this gate does not need
them: what it checks is the pairing logic, the metric that measures pairing, the
refusal to call an unmeasured index verified, and that a rule running past the
foot of its page keeps the rest of its text — in the splitter and in a built index.

The half that does need the documents is `rules_index.py audit-locators`, which
compares named locators against digests taken when their printed pages were read
directly. That is a local audit, it reports `skipped` where the documents are
absent, and it is exercised here only for its skip path.
"""

from __future__ import annotations

import json
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

# Four pages of the same invented rulebook. 201.1 runs past the foot of page 1;
# 201.2 runs across page 3, which carries no locator at all, and finishes in four
# words at the top of page 4.
SPANNING = [
    "201.        Gadget Handling\n"
    "201.1.      A Gadget that leaves play while a Widget is attached to it\n",
    "            returns that Widget to its holder's hand. Example: A Gadget\n"
    "            destroyed during Cleanup returns its Widget before Tokens are counted.\n"
    "201.2.      A player may attach a Widget only to a Gadget they control, and\n",
    "            only while that Gadget is ready. A Gadget that is exhausted\n"
    "            cannot receive a Widget, and a Widget attached before the Gadget\n"
    "            exhausted stays attached until the Gadget leaves play\n",
    "            or is discarded.\n"
    "202.        Token Handling\n"
    "202.1.      Tokens are spent when an effect instructs a player to spend them.\n",
]

TITLE_PAGE = "Invented Widget Rulebook, a title page with no rule on it\n"

# An FAQ whose first page opens a line with the rule it cites. Its second page
# is a new answer, not the rest of that rule.
FAQ_PAGES = [
    "Q: Does a Widget return when its Gadget leaves play?\n"
    "201.1 says it does, and the Widget goes to its holder's hand.\n",
    "A second page of answers: a Widget attached to an exhausted Gadget stays attached.\n",
]


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


def build_spanning_index() -> dict:
    """Build a real index over the spanning fixture and the FAQ, and return its chunks.

    The build reads its manifest, source registry and extractor from module
    globals. They point at this file's fixtures for the one call and are put
    back after it, so nothing licensed is read and nothing installed is touched.
    """
    documents = {"fixture-rules": ("core_rules", SPANNING), "fixture-faq": ("official_faq", FAQ_PAGES)}
    saved = (ri.MANIFEST_PATH, ri.REGISTRY_PATH, ri.extract_pages_scored)
    with tempfile.TemporaryDirectory(prefix="rules-index-spanning-") as folder:
        root = Path(folder)
        pages_by_name = {}
        for source_id, (_, pages) in documents.items():
            (root / f"{source_id}.pdf").write_bytes(source_id.encode("utf-8"))
            pages_by_name[f"{source_id}.pdf"] = pages
        manifest, registry, index = root / "manifest.json", root / "registry.json", root / "index.sqlite3"
        manifest.write_text(json.dumps({"documents": [
            {"source_id": source_id, "document_id": source_id, "relative_path": f"{source_id}.pdf"}
            for source_id in documents]}), encoding="utf-8")
        registry.write_text(json.dumps({"sources": [
            {"source_id": source_id, "title": source_id, "version": "fixture", "locale": "en-US",
             "region": "global", "document_class": document_class, "authority": "official",
             "status": "active", "superseded_by": None, "controlling_language": True}
            for source_id, (document_class, _) in documents.items()]}), encoding="utf-8")
        try:
            ri.MANIFEST_PATH, ri.REGISTRY_PATH = manifest, registry
            ri.extract_pages_scored = lambda path: (
                pages_by_name[path.name],
                {"mode": "fixture", **ri.pairing_integrity(pages_by_name[path.name])})
            ri.build_index(root, index)
        finally:
            ri.MANIFEST_PATH, ri.REGISTRY_PATH, ri.extract_pages_scored = saved
        connection = sqlite3.connect(index)
        try:
            return {"rows": connection.execute(
                "SELECT source_id, page, locator, text FROM chunks ORDER BY chunk_id").fetchall()}
        finally:
            connection.close()


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

    # --- a page break is not a locator ---------------------------------------
    # Cut page by page, 201.1 lost everything after its page's foot, page 2 grew
    # a context chunk nothing can cite, and the four words that finish 201.2 on
    # page 4 — shorter than a context chunk — vanished outright. A reading
    # reviewed against such a chunk was reviewed against part of a rule.
    by_page = {}
    for page, locator, body in ri.split_document(SPANNING, continuous=True):
        if locator in by_page:
            failures.append(f"{locator} is cut into more than one chunk across its pages")
        by_page[locator] = (page, body)
    continuations = {
        "201.1": (1, "Tokens are counted"),    # the rest of the rule on the next page
        "201.2": (2, "cannot receive a Widget"),  # a whole page with no locator on it
    }
    for locator, (page, fragment) in continuations.items():
        found_page, body = by_page.get(locator, (None, ""))
        if fragment not in body:
            failures.append(f"{locator} does not keep its text from the following page: {body!r}")
        if found_page != page:
            failures.append(f"{locator} must be cited on the page it starts on ({page}), not {found_page}")
    if not by_page.get("201.2", (0, ""))[1].endswith("or is discarded."):
        failures.append("a continuation shorter than a context chunk was dropped from 201.2")
    if any(locator.startswith("page-") for locator in by_page):
        failures.append(f"a continuation was left as a page chunk: "
                        f"{sorted(l for l in by_page if l.startswith('page-'))}")
    # The property itself: the cut does not depend on where the pages break.
    whole = [(locator, body) for locator, body in ri.split_page("\n".join(SPANNING), 1)]
    if [(locator, body) for _, locator, body in ri.split_document(SPANNING, continuous=True)] != whole:
        failures.append("cutting the document across its pages does not give the chunks the "
                        "same document gives with no page breaks at all")
    # And the per-page cut must get it wrong, or the fixture proves nothing.
    per_page = [(l, b) for n, t in enumerate(SPANNING, 1) for l, b in ri.split_page(t, n)]
    if any("Tokens are counted" in b for l, b in per_page if l == "201.1") or \
            any("or is discarded" in b for _, b in per_page):
        failures.append("the spanning fixture cuts correctly page by page, so it demonstrates nothing")

    # Before any rule opens, the title above the first rule is still its own
    # context chunk; there is no rule for it to continue.
    titled = ri.split_document([TITLE_PAGE + SPANNING[0], *SPANNING[1:]], continuous=True)
    if not titled or titled[0][1] != "page-1-context" or \
            next((p for p, l, _ in titled if l == "201.1"), None) != 1:
        failures.append(f"a title above the first rule must stay a context chunk: {titled[:2]}")

    # An FAQ is not carried across pages: its line-opening numbers cite rules.
    faq = ri.split_document(FAQ_PAGES, continuous=False)
    if faq != [(n, l, b) for n, t in enumerate(FAQ_PAGES, 1) for l, b in ri.split_page(t, n)]:
        failures.append("a non-rules document must be cut page by page, as before")
    if any("second page of answers" in b for _, l, b in faq if not l.startswith("page-2-")):
        failures.append("an FAQ page was glued onto a rule it merely cites")
    registry_classes = {s["document_class"] for s in ri.load_json(ri.REGISTRY_PATH)["sources"]}
    expected_continuous = {c for c in registry_classes if c.endswith("_rules")}
    if expected_continuous != set(ri.CONTINUOUS_CLASSES):
        failures.append(f"the rules documents in the source registry are {sorted(expected_continuous)}, "
                        f"but the index carries rules across pages for {sorted(ri.CONTINUOUS_CLASSES)}")

    # The build must use that cut. Without this, build_index could go back to
    # cutting page by page and every check above would still pass, because they
    # call the splitter directly rather than anything the build wrote.
    try:
        built = build_spanning_index()
    except Exception as exc:  # noqa: BLE001 - reporting is the point
        failures.append(f"building an index over the spanning fixture raised {type(exc).__name__}: {exc}")
        built = {}
    core = {locator: (page, text) for source, page, locator, text in built.get("rows", [])
            if source == "fixture-rules"}
    if "Tokens are counted" not in core.get("201.1", (0, ""))[1] or core.get("201.1", (0,))[0] != 1:
        failures.append(f"the built index does not keep 201.1's continuation on its start page: "
                        f"{core.get('201.1')}")
    if not core.get("201.2", (0, ""))[1].endswith("or is discarded."):
        failures.append("the built index dropped 201.2's short continuation")
    if any(locator.startswith("page-") for locator in core):
        failures.append("the built index kept a continuation as a page chunk")
    if not any(locator.startswith("page-2-") for source, _, locator, _ in built.get("rows", [])
               if source == "fixture-faq"):
        failures.append("the built index carried an FAQ page across a page break")

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
    print(f"rules documents ({sorted(ri.CONTINUOUS_CLASSES)}) are cut at locators, not page breaks: "
          f"a continuation, a locator-less page and a four-word tail stay with their rule, in the "
          f"splitter and in a built index; an FAQ is still cut page by page")
    print(f"anchors for the local audit: {len(anchors['anchors'])} digests over pages "
          f"{anchors['verified_pages']}, both single-line and wrapped; no rules text in the file")
    print("an index with no extraction record reports locator_integrity_unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
