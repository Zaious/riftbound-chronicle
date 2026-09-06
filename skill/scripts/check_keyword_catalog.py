#!/usr/bin/env python3
"""
Regression gate for C-51 (ADR-0013 §4; Codex G-2 on DP-70): the keyword
catalogue and the rule that no keyword is claimed without a production.

Must hold:
  - the committed catalogue validates, stays draft, and every entry carries an
    official locator, an active zone, an identity / duration boundary and a
    review record;
  - `verify` is derived from the engine, not from the file: every keyword the
    engine can carry is catalogued, every production named resolves to a real
    module and symbol, and every fixture named exists;
  - a keyword that some engine procedure reads may not claim `production:
    null` — removing a production from the file is caught (negative mutation),
    and so is claiming one for a keyword nothing reads;
  - a validator's allow-list is vocabulary, not behaviour: `temporary` appears
    in a shape check and still holds `production: null`, which is what lets
    the engine refuse it by name;
  - `keyword_supported` answers `keyword_not_implemented` for an uncatalogued
    keyword and for a catalogued one without a production, and names the
    production otherwise;
  - the effect scope declares the catalogue and its boundary.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from engine_check import KIND_CONFIG  # noqa: E402
from keyword_catalog import (  # noqa: E402
    DEFAULT_PATH, engine_keywords, keyword_supported, load_catalog, validate_catalog, verify,
)


def main() -> int:
    errors: list[str] = []
    catalog = load_catalog()

    # --- the committed file ---------------------------------------------------------------
    problems = validate_catalog(catalog)
    if problems:
        errors.append(f"the committed catalogue is invalid: {problems}")
    if catalog.get("status") != "draft":
        errors.append("the catalogue must stay draft")
    schema = json.loads((SKILL_DIR / "schemas" / "keyword-catalog.schema.json").read_text(encoding="utf-8"))
    if schema["properties"]["schema_version"]["const"] != catalog["schema_version"]:
        errors.append("the schema and the file disagree on the version")
    if "review" not in schema["properties"]["entries"]["items"]["required"]:
        errors.append("the schema does not require a review record")

    # --- derived from the engine -----------------------------------------------------------------
    found = verify(catalog)
    if found:
        errors.append(f"the committed catalogue disagrees with the engine: {found}")
    carried = engine_keywords()
    if not {"shield", "tank", "ganking", "deflect", "ambush", "hidden", "repeat"} <= set(carried):
        errors.append(f"the derivation missed keywords the engine carries: {sorted(carried)}")

    acted = [k for k, facts in carried.items() if facts["acted_on"]]
    if not acted:
        errors.append("no keyword was derived as acted on; the measurement is broken")
    stripped = copy.deepcopy(catalog)
    for entry in stripped["entries"]:
        if entry["keyword_id"] == acted[0]:
            entry["production"] = None
    if not any("claims no production" in p for p in verify(stripped)):
        errors.append(f"negative mutation failed: removing {acted[0]}'s production was not caught")
    invented = copy.deepcopy(catalog)
    for entry in invented["entries"]:
        if entry["keyword_id"] == "temporary":
            entry["production"] = {"module": "effect_ir", "symbol": "has_keyword", "layer": "ability"}
    if not any("not implemented by being spellable" in p for p in verify(invented)):
        errors.append("a production claimed for a keyword nothing reads was accepted")
    missing = copy.deepcopy(catalog)
    missing["entries"] = [e for e in missing["entries"] if e["keyword_id"] != "shield"]
    if not any("does not list it" in p for p in verify(missing)):
        errors.append("a keyword the engine carries but the catalogue omits was accepted")
    broken = copy.deepcopy(catalog)
    for entry in broken["entries"]:
        if entry["keyword_id"] == "shield":
            entry["production"] = {"module": "effect_ir", "symbol": "no_such_symbol", "layer": "ability"}
    if not any("does not exist" in p for p in verify(broken)):
        errors.append("a production naming a symbol the engine does not have was accepted")

    # --- temporary is vocabulary, not behaviour -----------------------------------------------------
    temporary = next(e for e in catalog["entries"] if e["keyword_id"] == "temporary")
    if temporary["production"] is not None:
        errors.append("Temporary claims a production; the engine only lets the word be written (816 is not implemented)")
    supported, note = keyword_supported(catalog, "temporary")
    if supported or "keyword_not_implemented" not in note:
        errors.append(f"an unimplemented keyword did not answer keyword_not_implemented: {note}")
    supported, note = keyword_supported(catalog, "shield")
    if not supported or "shield_total" not in note:
        errors.append(f"an implemented keyword did not name its production: {note}")
    supported, note = keyword_supported(catalog, "assault")
    if supported or "not in the keyword catalogue" not in note:
        errors.append(f"an uncatalogued keyword was not refused by name: {note}")

    # --- scope and determinism -------------------------------------------------------------------------
    scope = KIND_CONFIG["effect"]
    if "keyword_catalog" not in scope["supported"] or "keyword_not_implemented" not in scope["unsupported"]:
        errors.append("the effect scope does not declare the keyword catalogue and its boundary")
    if load_catalog(DEFAULT_PATH) != catalog or verify(catalog) != found:
        errors.append("the catalogue or its verification is not deterministic")

    if errors:
        print("FAILED: keyword catalogue checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("keyword catalogue checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
