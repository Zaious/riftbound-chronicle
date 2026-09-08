#!/usr/bin/env python3
"""source-semantic-bindings.v1: which readings a piece of official text admits.

A conditional-rule claim is a template with closed slot values, bound to a
locator. Closed values are not enough on their own: two values that are each
in their lexicon can still be paired into a sentence the locator does not say,
and that sentence would carry the right document hash under the wrong meaning.
So the answer surface binds a rule claim only when the registry here has
recorded that exact {template, slots} as a reading of that exact text —
document id, document version, locator and text hash all matching what the
retriever returned. A locator that exists but was never registered with this
reading is refused; a registered reading whose text has since changed hash is
refused; the same template with other slot values is refused.

The registry carries digests of the rules text and never the text: a digest
cannot be inverted, so this file is safe in the public repository.

Every entry:

  document_id        the document the retriever names
  document_version   its version
  locator            the rule, as the retriever names it ("Core 345")
  text_hash          sha256 of the normalized chunk text, as the index digests it
  template           a conditional_rule template on the answer surface
  slots              the exact slot values, locator included

`is_registered(record, template, slots)` answers the one question the command
asks. `validate_registry(payload)` checks shape and that every entry could be
bound at all: the template exists and is a conditional rule, the slots are
its slots, every value is admitted, the reading coheres, and one locator
carries one hash per document version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import rule_consult_command as rcc
from rules_index import normalize

SCHEMA_VERSION = "source-semantic-bindings.v1"
BINDING_FIELDS = {"document_id", "document_version", "locator", "text_hash", "template", "slots"}
RECORD_FIELDS = ("document_id", "document_version", "locator", "text_hash")
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "source_semantic_bindings.json"


def text_digest(text: str) -> str:
    """The digest the rules index anchors use: normalized chunk text, sha256."""
    return "sha256:" + hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(record.get(field) for field in RECORD_FIELDS)  # type: ignore[return-value]


def _reading(template: str, slots: dict[str, Any]) -> str:
    return json.dumps({"template": template, "slots": slots}, sort_keys=True, ensure_ascii=False)


def validate_registry(payload: Any) -> list[str]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "bindings"}:
        return ["a registry carries exactly schema_version and bindings"]
    if payload["schema_version"] != SCHEMA_VERSION:
        return [f"schema_version must be {SCHEMA_VERSION!r}"]
    if not isinstance(payload["bindings"], list):
        return ["bindings must be an array"]
    errors: list[str] = []
    seen: set[tuple[Any, ...]] = set()
    hash_by_locator: dict[tuple[str, str, str], str] = {}
    for index, entry in enumerate(payload["bindings"]):
        label = f"bindings[{index}]"
        if not isinstance(entry, dict) or set(entry) != BINDING_FIELDS:
            errors.append(f"{label} carries exactly {sorted(BINDING_FIELDS)}")
            continue
        for field in RECORD_FIELDS:
            if not isinstance(entry[field], str) or not entry[field].strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        if not str(entry["text_hash"]).startswith("sha256:"):
            errors.append(f"{label}.text_hash is a sha256 digest")
        if not rcc.LOCATOR_SHAPE.match(str(entry["locator"])):
            errors.append(f"{label}.locator is not locator-shaped")
        template = rcc.CLAIM_TEMPLATES.get(entry["template"])
        if template is None:
            errors.append(f"{label} names the unknown template {entry['template']!r}")
            continue
        if template["class"] != "conditional_rule":
            errors.append(f"{label}: {entry['template']} is not a conditional rule; only rule "
                          f"readings are registered")
            continue
        slots = entry["slots"]
        if not isinstance(slots, dict) or set(slots) != set(template["slots"]):
            errors.append(f"{label}: {entry['template']} takes exactly {sorted(template['slots'])}")
            continue
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
            continue
        if (incoherent := template.get("coheres", lambda s: None)(slots)) is not None:
            errors.append(f"{label} does not cohere: {incoherent}")
        key = (*_key(entry), _reading(entry["template"], slots))
        if key in seen:
            errors.append(f"{label} repeats a reading already registered")
        seen.add(key)
        locator_key = (entry["document_id"], entry["document_version"], entry["locator"])
        if hash_by_locator.setdefault(locator_key, entry["text_hash"]) != entry["text_hash"]:
            errors.append(f"{label}: {entry['locator']} carries two different text hashes in one "
                          f"document version")
    return errors


class BindingRegistry:
    """The readings a document admits, indexed by the retriever's record."""

    def __init__(self, payload: dict[str, Any]) -> None:
        if problems := validate_registry(payload):
            raise ValueError(f"registry does not validate: {problems[:3]}")
        self._readings: dict[tuple[str, str, str, str], set[str]] = {}
        for entry in payload["bindings"]:
            self._readings.setdefault(_key(entry), set()).add(_reading(entry["template"], entry["slots"]))

    def is_registered(self, record: Any, template: str, slots: dict[str, Any]) -> bool:
        if not isinstance(record, dict):
            return False
        return _reading(template, slots) in self._readings.get(_key(record), set())

    def readings_for(self, record: Any) -> list[dict[str, Any]]:
        if not isinstance(record, dict):
            return []
        return [json.loads(r) for r in sorted(self._readings.get(_key(record), set()))]

    def __len__(self) -> int:
        return sum(len(v) for v in self._readings.values())


def load_registry(path: Path | str = DEFAULT_PATH) -> BindingRegistry:
    return BindingRegistry(json.loads(Path(path).read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a source-semantic-bindings registry.")
    parser.add_argument("registry", nargs="?", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    problems = validate_registry(payload)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        registry = BindingRegistry(payload)
        locators = {(e["document_id"], e["document_version"], e["locator"]) for e in payload["bindings"]}
        print(f"valid: {len(registry)} readings over {len(locators)} locators")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
