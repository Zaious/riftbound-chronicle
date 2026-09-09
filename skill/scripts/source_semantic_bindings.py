#!/usr/bin/env python3
"""source-semantic-bindings.v1: which readings a piece of official text admits, and who said so.

A conditional-rule claim is a template with closed slot values, bound to a
locator. Closed values are not enough on their own: two values that are each
in their lexicon can still be paired into a sentence the locator does not say,
and that sentence would carry the right document hash under the wrong meaning.
So the answer surface binds a rule claim only as a reading someone reviewed:
the registry records that this exact {template, slots} is a reading of this
exact text — document id, document version, locator, text hash — and who
reviewed it, when. A locator that exists but was never registered with this
reading is refused; a registered reading whose text has since changed hash is
refused; the same template with other slot values is refused; a reading whose
review status is anything but `human_reviewed` carries no authority.

Registry-first. The registry is written by review, never by a run:

  runs  ->  proposed bindings   (this module's `propose`; status `proposed`)
        ->  private review against the official source
        ->  approved registry   (status `approved`, every entry `human_reviewed`)
        ->  runs consume approved bindings only

Nothing at run time generates, updates or promotes a registry. `propose` is a
maintainer's draft tool: its output is marked `proposed`, the loader refuses
it, and it will not write to the approved registry's file name. The approved
registry lives outside the public repository, on the pack paths
(`CHRONICLE_PACK_PATHS`); the public repository carries the schema, this
verifier, and a fixture registry marked `fixture` that the loader also refuses.

Every approved binding:

  binding_id         content-addressed: sha256 over document, version, locator,
                     hash, template and canonical slots, so replacing any of
                     them is a different binding
  document_id        the document the retriever names
  document_version   its version
  locator            the rule, as the retriever names it ("Core 345")
  text_hash          sha256 of the normalized chunk text, as the index digests it
  template           a conditional_rule template on the answer surface
  slots              the exact slot values, locator included
  rendered_text_hash sha256 of the sentence those slots render to. Slot values
                     are ids that render through lexicons in code; a phrase
                     edited in a lexicon would change what the reviewer read
                     without changing any slot, so the approved sentence is
                     pinned here and a registry whose sentences no longer
                     render the same is refused
  source_page        the printed page the reviewer read
  review_status      human_reviewed
  reviewed_by        who
  reviewed_at        when, YYYY-MM-DD

The registry carries digests of the rules text and never the text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import rule_consult_command as rcc
from rules_index import normalize

SCHEMA_VERSION = "source-semantic-bindings.v1"
STATUSES = ("approved", "proposed", "fixture")
REVIEW_STATUSES = ("human_reviewed", "proposed", "rejected")
AUTHORITATIVE_REVIEW = "human_reviewed"
BINDING_FIELDS = {"binding_id", "document_id", "document_version", "locator", "text_hash", "template",
                  "slots", "rendered_text_hash", "source_page", "review_status", "reviewed_by", "reviewed_at"}
RECORD_FIELDS = ("document_id", "document_version", "locator", "text_hash")
APPROVED_FILENAME = "source_semantic_bindings.json"
DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FREE_TEXT_FIELDS = ()  # every field is an id, a digest, a page, a date or a closed value


def text_digest(text: str) -> str:
    """The digest the rules index anchors use: normalized chunk text, sha256."""
    return "sha256:" + hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def rendered_hash(template: str, slots: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(rcc.render(template, slots).encode("utf-8")).hexdigest()


def _key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(record.get(field) for field in RECORD_FIELDS)  # type: ignore[return-value]


def _reading(template: str, slots: dict[str, Any]) -> str:
    return json.dumps({"template": template, "slots": slots}, sort_keys=True, ensure_ascii=False)


def binding_id(record: dict[str, Any], template: str, slots: dict[str, Any]) -> str:
    """Content-addressed: any change to what is bound is a different binding."""
    body = json.dumps({"record": {k: record.get(k) for k in RECORD_FIELDS},
                       "reading": json.loads(_reading(template, slots))},
                      sort_keys=True, ensure_ascii=False)
    return "ssb-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def _entry_errors(entry: Any, label: str, *, status: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict) or set(entry) != BINDING_FIELDS:
        return [f"{label} carries exactly {sorted(BINDING_FIELDS)}"]
    for field in RECORD_FIELDS:
        if not isinstance(entry[field], str) or not entry[field].strip():
            errors.append(f"{label}.{field} must be a non-empty string")
    if not str(entry["text_hash"]).startswith("sha256:"):
        errors.append(f"{label}.text_hash is a sha256 digest")
    if not rcc.LOCATOR_SHAPE.match(str(entry["locator"])):
        errors.append(f"{label}.locator is not locator-shaped")
    page = entry["source_page"]
    if not (page is None or (isinstance(page, int) and not isinstance(page, bool) and page > 0)):
        errors.append(f"{label}.source_page is a page number or null")
    if entry["review_status"] not in REVIEW_STATUSES:
        errors.append(f"{label}.review_status must be one of {list(REVIEW_STATUSES)}")
    if status == "approved":
        if entry["review_status"] != AUTHORITATIVE_REVIEW:
            errors.append(f"{label}: an approved registry holds only {AUTHORITATIVE_REVIEW} bindings")
        if not isinstance(entry["reviewed_by"], str) or not entry["reviewed_by"].strip():
            errors.append(f"{label}.reviewed_by names the reviewer")
        if not isinstance(entry["reviewed_at"], str) or not DATE_SHAPE.match(entry["reviewed_at"]):
            errors.append(f"{label}.reviewed_at is YYYY-MM-DD")
        if page is None:
            errors.append(f"{label}.source_page: a reviewed binding names the page that was read")
    elif status == "proposed":
        if entry["review_status"] != "proposed" or entry["reviewed_by"] is not None \
                or entry["reviewed_at"] is not None:
            errors.append(f"{label}: a proposed binding is not reviewed by anyone")
    template = rcc.CLAIM_TEMPLATES.get(entry["template"])
    if template is None:
        errors.append(f"{label} names the unknown template {entry['template']!r}")
        return errors
    if template["class"] != "conditional_rule":
        errors.append(f"{label}: {entry['template']} is not a conditional rule; only rule "
                      f"readings are registered")
        return errors
    slots = entry["slots"]
    if not isinstance(slots, dict) or set(slots) != set(template["slots"]):
        errors.append(f"{label}: {entry['template']} takes exactly {sorted(template['slots'])}")
        return errors
    if slots.get("locator") != entry["locator"]:
        errors.append(f"{label}: the reading's locator slot must be the entry's locator")
    bad = False
    for slot, value in slots.items():
        slot_type = template["slots"][slot]
        if slot_type == "locator":
            continue
        if not rcc.SLOT_TYPES[slot_type]["admits"]({}, value):
            errors.append(f"{label}.slots.{slot}={value!r} is not a {slot_type} value")
            bad = True
    if bad:
        return errors
    if (incoherent := template.get("coheres", lambda s: None)(slots)) is not None:
        errors.append(f"{label} does not cohere: {incoherent}")
    expected = binding_id(entry, entry["template"], slots)
    if entry["binding_id"] != expected:
        errors.append(f"{label}.binding_id is {entry['binding_id']!r}; the binding it carries is {expected!r}")
    if entry["rendered_text_hash"] != rendered_hash(entry["template"], slots):
        errors.append(f"{label}: the sentence these slots render to is not the sentence that was "
                      f"registered; the lexicon moved under a reviewed binding")
    return errors


def validate_registry(payload: Any) -> list[str]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "status", "bindings"}:
        return ["a registry carries exactly schema_version, status and bindings"]
    if payload["schema_version"] != SCHEMA_VERSION:
        return [f"schema_version must be {SCHEMA_VERSION!r}"]
    if payload["status"] not in STATUSES:
        return [f"status must be one of {list(STATUSES)}"]
    if not isinstance(payload["bindings"], list):
        return ["bindings must be an array"]
    errors: list[str] = []
    seen: set[str] = set()
    hash_by_locator: dict[tuple[str, str, str], str] = {}
    for index, entry in enumerate(payload["bindings"]):
        label = f"bindings[{index}]"
        entry_errors = _entry_errors(entry, label, status=payload["status"])
        errors.extend(entry_errors)
        if entry_errors or not isinstance(entry, dict):
            continue
        if entry["binding_id"] in seen:
            errors.append(f"{label} repeats a reading already registered")
        seen.add(entry["binding_id"])
        locator_key = (entry["document_id"], entry["document_version"], entry["locator"])
        if hash_by_locator.setdefault(locator_key, entry["text_hash"]) != entry["text_hash"]:
            errors.append(f"{label}: {entry['locator']} carries two different text hashes in one "
                          f"document version")
    return errors


class BindingRegistry:
    """The reviewed readings a document admits, indexed by the retriever's record.

    Only an `approved` registry carries authority. A `fixture` registry is
    admitted solely when a gate says so; a `proposed` one never is.
    """

    def __init__(self, payload: dict[str, Any], *, allow_fixture: bool = False) -> None:
        if problems := validate_registry(payload):
            raise ValueError(f"registry does not validate: {problems[:3]}")
        if payload["status"] == "proposed":
            raise ValueError("a proposed registry carries no authority; review it first")
        if payload["status"] == "fixture" and not allow_fixture:
            raise ValueError("a fixture registry carries no authority outside its gate")
        self.status = payload["status"]
        self._readings: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = {}
        for entry in payload["bindings"]:
            self._readings.setdefault(_key(entry), {})[_reading(entry["template"], entry["slots"])] = entry

    def lookup(self, record: Any, template: str, slots: dict[str, Any]) -> dict[str, Any] | None:
        """The reviewed binding for this reading of this record, or None."""
        if not isinstance(record, dict):
            return None
        entry = self._readings.get(_key(record), {}).get(_reading(template, slots))
        if entry is None or entry["review_status"] != AUTHORITATIVE_REVIEW:
            return None
        return entry

    def is_registered(self, record: Any, template: str, slots: dict[str, Any]) -> bool:
        return self.lookup(record, template, slots) is not None

    def readings_for(self, record: Any) -> list[dict[str, Any]]:
        if not isinstance(record, dict):
            return []
        return [json.loads(r) for r in sorted(self._readings.get(_key(record), {}))]

    def __len__(self) -> int:
        return sum(len(v) for v in self._readings.values())


def load_registry(path: Path | str) -> BindingRegistry:
    """One approved registry file. Refuses proposed and fixture registries."""
    return BindingRegistry(json.loads(Path(path).read_text(encoding="utf-8")))


def approved_registry_paths(pack_paths: str | None = None) -> list[Path]:
    """The approved registries on the pack paths. The public seed carries none."""
    from pack_locator import pack_files
    return pack_files(APPROVED_FILENAME, pack_paths)


def load_approved(pack_paths: str | None = None) -> BindingRegistry | None:
    """The approved readings the pack paths carry, merged; None where there are none.

    Two registries that disagree about one locator's text hash, or register the
    same reading twice, are refused rather than merged: the pack paths carry
    one authority or none.
    """
    paths = approved_registry_paths(pack_paths)
    if not paths:
        return None
    merged: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "status": "approved", "bindings": []}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if problems := validate_registry(payload):
            raise ValueError(f"{path}: {problems[:3]}")
        if payload["status"] != "approved":
            raise ValueError(f"{path} is a {payload['status']} registry on the approved file name")
        merged["bindings"].extend(payload["bindings"])
    return BindingRegistry(merged)


# --- the maintainer's draft tool ----------------------------------------------

def propose(runs: dict[str, Any], *, pages: dict[str, int] | None = None) -> dict[str, Any]:
    """Proposed bindings from a runs file: one per rule claim per record, marked proposed.

    A draft for review, not a registry: every entry says `proposed`, nobody is
    named as reviewer, and `write_proposed` will not put it on the approved
    file name.
    """
    retriever = rcc.TableRetriever(runs["sources"], {})
    entries: dict[str, dict[str, Any]] = {}
    for question_id, inputs in sorted(runs["runs"].items()):
        for claim in inputs.get("claims", []):
            template = rcc.CLAIM_TEMPLATES.get(claim["template"])
            if template is None or template["class"] != "conditional_rule":
                continue
            retrieval = retriever.retrieve(claim["slots"]["locator"])
            if retrieval.get("status") != "retrieved":
                continue
            record = retrieval["record"]
            bid = binding_id(record, claim["template"], claim["slots"])
            entries.setdefault(bid, {
                "binding_id": bid,
                **{k: record[k] for k in RECORD_FIELDS},
                "template": claim["template"], "slots": dict(claim["slots"]),
                "rendered_text_hash": rendered_hash(claim["template"], claim["slots"]),
                "source_page": (pages or {}).get(record["locator"]),
                "review_status": "proposed", "reviewed_by": None, "reviewed_at": None,
            })
    bindings = sorted(entries.values(),
                      key=lambda e: (e["locator"], e["template"], json.dumps(e["slots"], sort_keys=True)))
    return {"schema_version": SCHEMA_VERSION, "status": "proposed", "bindings": bindings}


def write_proposed(payload: dict[str, Any], path: Path | str) -> Path:
    path = Path(path)
    if payload.get("status") != "proposed":
        raise ValueError("write_proposed writes proposed registries only")
    if path.name == APPROVED_FILENAME:
        raise ValueError(f"a proposed registry is not written to {APPROVED_FILENAME!r}; that name is "
                         f"the approved registry's, and review is what puts a binding there")
    if problems := validate_registry(payload):
        raise ValueError(f"the proposal does not validate: {problems[:3]}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="validate a registry file of any status")
    check.add_argument("registry")
    draft = sub.add_parser("propose", help="draft proposed bindings from a runs file (maintainer tool)")
    draft.add_argument("--runs", required=True)
    draft.add_argument("--out", required=True)
    draft.add_argument("--pages", help="JSON map locator -> printed page, if known")
    args = parser.parse_args(argv)

    if args.command == "validate":
        payload = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        problems = validate_registry(payload)
        for problem in problems:
            print(problem, file=sys.stderr)
        if not problems:
            locators = {(e["document_id"], e["document_version"], e["locator"]) for e in payload["bindings"]}
            print(f"valid {payload['status']} registry: {len(payload['bindings'])} bindings over "
                  f"{len(locators)} locators")
        return 0 if not problems else 1

    runs = json.loads(Path(args.runs).read_text(encoding="utf-8"))
    pages = json.loads(Path(args.pages).read_text(encoding="utf-8")) if args.pages else None
    payload = propose(runs, pages=pages)
    written = write_proposed(payload, args.out)
    print(f"proposed {len(payload['bindings'])} bindings -> {written} (status proposed; review before use)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
