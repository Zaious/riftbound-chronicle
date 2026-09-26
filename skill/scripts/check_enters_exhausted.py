#!/usr/bin/env python3
"""A printed entry replacement: "This enters exhausted." (Core 369.3, 359.2.d, 143.4).

The clause grammar lowers the sentence to the permanent's own entry_replacements
[{mode: entry_state, value: exhausted}], which resolution_bridge.entry_state_for applies when the
permanent enters. Held here:

  lowering   exactly that one replacement; "This enters ready." and a granted form stay unparsed
  gear       a Gear carrying it, played and resolved by the entry procedure, is in its Base
             exhausted; the same Gear without it enters ready (359.2.d) - the replacement is what
             exhausts it
  unit       a Unit enters exhausted with or without it (143.4): nothing to replace

    python skill/scripts/check_enters_exhausted.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402


def entered(kind: str, fields: dict) -> tuple[bool | None, list | None]:
    """(exhausted?, where) of c1 played as `kind` to p1's Base and resolved."""
    state = base_state()
    state["players"]["p1"]["zones"]["main_deck"].remove("c1")
    state["players"]["p1"]["zones"]["hand"].append("c1")
    state["objects"]["c1"].update(kind=kind, base_might=2 if kind == "unit" else 0, **fields)
    state["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-1", "actor": "p1", "card": "c1",
            "chain_item": {"id": "perm-1", "object_kind": kind, "timing": "default"},
            "cost": {"base": {"energy": 2, "power": {}}},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    if kind == "unit":
        decl["entry_location"] = {"kind": "base"}
    play = play_card(fixture(), state, decl)
    if not play.get("committed"):
        return None, [play.get("reason_code"), play.get("reason")]
    timing = fixture(priority="p2", items=[item("perm-1", "p1", kind, "default", "finalized")], passes=["p1", "p2"])
    done = resolve_with_program(timing, "perm-1", play["next_effect_state"], None)
    if not done.get("committed"):
        return None, [done.get("reason_code"), done.get("reason")]
    after = done["next_effect_state"]
    return bool(after["objects"]["c1"].get("exhausted")), ["base"] if "c1" in after["players"]["p1"]["zones"]["base"] else None


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    got = CG.compile_clause("This enters exhausted.", grammar)
    fields = (got.get("passive") or {}).get("object_fields") or {}
    if got.get("production_id") != "this_enters_exhausted" or fields != {"entry_replacements": [{"mode": "entry_state", "value": "exhausted"}]}:
        errors.append(f"lowering: {got.get('production_id')} {fields}")
    for text in ("This enters ready.", "Units you play enter exhausted."):
        if not CG.compile_clause(text, grammar).get("unsupported"):
            errors.append(f"lowering: {text!r} was parsed")
    for kind, with_it, want in (("gear", True, True), ("gear", False, False), ("unit", True, True), ("unit", False, True)):
        exhausted, where = entered(kind, fields if with_it else {})
        if exhausted is not want or where != ["base"]:
            errors.append(f"{kind} {'with' if with_it else 'without'} the replacement: exhausted {exhausted} at {where}, "
                          f"expected {want} in its Base")
    if errors:
        print("FAILED: this enters exhausted")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("this enters exhausted: one entry replacement; a Gear with it enters exhausted and without it ready; a Unit "
          "enters exhausted either way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
