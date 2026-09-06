#!/usr/bin/env python3
"""
Regression gate for C-48 (ADR-0012 §6; Codex G-1 on DP-67): the token
catalogue and its manual promotion.

Must hold:
  - the committed catalogue validates against its schema and its own
    relations, and stays `draft`;
  - promotion is manual: an entry without a review record is refused, so is a
    duplicate id, and the accepted entry's `text_sha256` is derived from the
    text the reviewer approved — supplying a wrong hash cannot get in
    (negative mutation: the same entry with a review record does get in);
  - an entry whose text is edited afterwards fails validation, so an errata
    cannot slip in unreviewed;
  - `play_token` carries the `token_id` it was compiled from: a pack whose
    play_token names an uncatalogued token fails verify-pack, one naming a
    catalogued token passes, and one naming none fails;
  - the committed card packs pass verify-pack against the committed
    catalogue;
  - the effect scope names the boundary (token_not_in_catalogue) and
    `play_token` accepts the provenance field; the CLI exits non-zero on a
    bad catalogue; determinism.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import apply_program, validate_program  # noqa: E402
from engine_check import KIND_CONFIG  # noqa: E402
from token_catalog import DEFAULT_PATH, entry_of, load_catalog, promote, text_hash, validate_catalog, verify_pack  # noqa: E402

REVIEWED = {
    "token_id": "sand-soldier",
    "name": "Sand Soldier",
    "kind": "unit",
    "base_might": 2,
    "keywords": [],
    "text": "",
    "text_sha256": "sha256:" + "0" * 64,
    "source_cards": [{"name": "Desert's Call", "locator": "OGN-123"}],
    "review": {"reviewer": "archon", "date": "2026-09-06", "source": "Core Rules 2026-07-16 + card face", "note": "no rules text on the token"},
}


def main() -> int:
    errors: list[str] = []

    # --- the committed catalogue ---------------------------------------------------------------
    catalog = load_catalog()
    problems = validate_catalog(catalog)
    if problems:
        errors.append(f"the committed catalogue is invalid: {problems}")
    if catalog.get("status") != "draft":
        errors.append("the catalogue must stay draft")
    schema = json.loads((SKILL_DIR / "schemas" / "token-catalog.schema.json").read_text(encoding="utf-8"))
    if schema["properties"]["schema_version"]["const"] != catalog["schema_version"]:
        errors.append("the catalogue schema and the file disagree on the version")
    if "review" not in schema["properties"]["entries"]["items"]["required"]:
        errors.append("the schema does not require a review record on every entry")

    # --- promotion is manual --------------------------------------------------------------------------
    without_review = {k: v for k, v in REVIEWED.items() if k != "review"}
    try:
        promote(catalog, without_review)
        errors.append("an entry without a review record was promoted")
    except ValueError as exc:
        if "review" not in str(exc):
            errors.append(f"the refusal did not name the missing review: {exc}")
    wrong_hash = copy.deepcopy(REVIEWED)
    wrong_hash["text"] = "It has \"When I attack, you may banish a unit from your trash.\""
    promoted = promote(catalog, wrong_hash)
    entry = entry_of(promoted, "sand-soldier")
    if entry is None or entry["text_sha256"] != text_hash(wrong_hash["text"]):
        errors.append("promotion did not derive the hash from the reviewed text")
    if validate_catalog(promoted):
        errors.append(f"a promoted entry made the catalogue invalid: {validate_catalog(promoted)}")
    try:
        promote(promoted, REVIEWED)
        errors.append("a duplicate token_id was promoted")
    except ValueError as exc:
        if "already in the catalogue" not in str(exc):
            errors.append(f"the duplicate refusal is wrong: {exc}")
    edited = copy.deepcopy(promoted)
    edited["entries"][0]["text"] = edited["entries"][0]["text"] + " (errata)"
    if not any("text_sha256" in e for e in validate_catalog(edited)):
        errors.append("an entry edited after its review passed validation; the hash must catch it")

    # --- packs name catalogued tokens ------------------------------------------------------------------
    token_effect = {"op": "play_token", "effect_id": "t", "object_id": "t1", "owner": "p1", "controller": "p1", "token_kind": "unit",
                    "base_might": 2, "destination": {"kind": "base", "player": "p1"}, "token_id": "sand-soldier"}
    catalogued = program("tok", token_effect)
    if validate_program(catalogued):
        errors.append(f"play_token with a token_id was refused: {validate_program(catalogued)}")
    if verify_pack(catalogued, promoted):
        errors.append(f"a pack naming a catalogued token failed: {verify_pack(catalogued, promoted)}")
    if not verify_pack(catalogued, catalog):
        errors.append("negative mutation failed: the same pack passed against a catalogue without that token")
    anonymous = program("tok", {k: v for k, v in token_effect.items() if k != "token_id"})
    if not verify_pack(anonymous, promoted):
        errors.append("a play_token naming no token was accepted")
    played = apply_program(base_state(), catalogued)
    if not played.get("committed") or played["trace"][0].get("token_id") != "sand-soldier":
        errors.append(f"play_token did not record the catalogue provenance: {played.get('reason') or played.get('errors')}")
    for pack in sorted((SKILL_DIR / "data" / "card_program_packs").glob("*/r3a1_programs.json")):
        found = verify_pack(json.loads(pack.read_text(encoding="utf-8")), catalog)
        if found:
            errors.append(f"{pack.name} plays tokens that are not in the catalogue: {found}")

    # --- the CLI and the scope -------------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="token-catalog-") as tmp:
        bad = Path(tmp) / "bad.json"
        broken = copy.deepcopy(catalog)
        broken["status"] = "active"
        bad.write_text(json.dumps(broken), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT_DIR / "token_catalog.py"), "validate", str(bad)], capture_output=True, text=True, cwd=tmp)
        if result.returncode == 0:
            errors.append("the CLI accepted a catalogue that is not draft")
        ok = subprocess.run([sys.executable, str(SCRIPT_DIR / "token_catalog.py"), "validate", str(DEFAULT_PATH)], capture_output=True, text=True, cwd=tmp)
        if ok.returncode != 0:
            errors.append(f"the CLI rejected the committed catalogue off-cwd: {ok.stdout} {ok.stderr}")
    if "token_not_in_catalogue" not in KIND_CONFIG["effect"]["unsupported"]:
        errors.append("the effect scope does not name the token catalogue boundary")
    if promote(catalog, wrong_hash) != promoted:
        errors.append("promotion is not deterministic")

    if errors:
        print("FAILED: token catalogue checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("token catalogue checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
