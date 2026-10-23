#!/usr/bin/env python3
"""Gate: the action space is closed - its kinds, its declaration fields and its action key (package 13, C2).

  K1 kinds       action_space.ACTION_KINDS names exactly the enumerator's families (legal_action.ENUMERABLE_FAMILIES)
  K2 timing      every kind the timing kernel judges is one it knows (no unsupported_action_kind); hide is judged by
                 the hide procedure itself
  K3 limited     no Limited Action (Core 411.2) is also a discretionary kind
  F1 fields      each declaration validator's accepted fields are exactly the fields FIELD_CLASSES classifies, each
                 as a choice, a derived value or a system field
  C1 same        two plays differing only in system fields - play_id, chain_item.id, payment_context.confirmed_by,
                 the play's own id inside a decision id, identity tokens, provenance - have one key
  C2 different   a different card, source, entry location, target, mode, additional cost or Universal allocation is a
                 different key
  C3 moves       the units of one Standard Move are a set (order-free); another destination is another key
  C4 closed      a declaration carrying a field FIELD_CLASSES does not classify is refused, not keyed
  C5 ids         a decision-id part equal to the play's id is the role; a part merely containing it is left alone

    python skill/scripts/check_action_space.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_space as A  # noqa: E402
import legal_action  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from rules_core import validate_timing  # noqa: E402

errors: list[str] = []


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


PLAY = {"schema_version": "riftbound-play-declaration.v1", "ruleset": {"core": "x", "faq_as_of": "y"},
        "play_id": "play-7", "actor": "p1", "card": "c1",
        "chain_item": {"id": "spell-7", "object_kind": "spell", "timing": "default"},
        "cost": {"base": {"energy": 2, "power": {}}, "additional": [{"cost_id": "opt", "mandatory": False,
                                                                     "payment": {"kind": "exhaust", "object_id": "g1"}}]},
        "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
DECISIONS = [{"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
              "value": ["u2"], "selection_identities": {"u2": "u2@0"}},
             {"decision_id": "universal_power:play-7", "stage": "play_declaration", "kind": "resource_allocation",
              "controller": "p1", "value": {"fury": 1}}]


def play(declaration=None, decisions=None):
    return {"kind": "play_card", "declaration": declaration or copy.deepcopy(PLAY),
            "decisions": decisions if decisions is not None else copy.deepcopy(DECISIONS)}


def key(action):
    return A.canonical_action_key(action)


def main() -> int:
    # K1 - K3
    if set(A.ACTION_KINDS) != set(legal_action.ENUMERABLE_FAMILIES):
        fail("K1 kinds", f"table {sorted(A.ACTION_KINDS)} vs enumerator {sorted(legal_action.ENUMERABLE_FAMILIES)}")
    for kind, spec in A.ACTION_KINDS.items():
        if not spec.get("rule_locators"):
            fail("K1 kinds", f"{kind} cites no rule")
        if kind != "hide":
            got = validate_timing(fixture(), {"actor": "p1", "kind": kind, "timing": "default"})
            if got.get("reason_code") == "unsupported_action_kind":
                fail("K2 timing", f"the timing kernel does not know {kind}")
    if set(A.LIMITED_ACTIONS) & set(A.ACTION_KINDS):
        fail("K3 limited", f"{sorted(set(A.LIMITED_ACTIONS) & set(A.ACTION_KINDS))}")
    # F1
    accepted = A.declaration_fields()
    if set(accepted) != set(A.FIELD_CLASSES):
        fail("F1 fields", f"declaration shapes {sorted(accepted)} vs {sorted(A.FIELD_CLASSES)}")
    for shape, fields in accepted.items():
        classified = A.FIELD_CLASSES.get(shape, {})
        if set(fields) != set(classified):
            fail("F1 fields", f"{shape}: unclassified {sorted(set(fields) - set(classified))}, "
                              f"not accepted {sorted(set(classified) - set(fields))}")
        if set(classified.values()) - {A.CHOICE, A.DERIVED, A.SYSTEM}:
            fail("F1 fields", f"{shape}: a class outside choice/derived/system")
    # C1
    base = key(play())
    renamed = copy.deepcopy(PLAY)
    renamed.update(play_id="play-9", chain_item={**PLAY["chain_item"], "id": "spell-9"},
                   payment_context={"add_window_closed": True, "confirmed_by": "someone else"})
    renamed["cost"]["additional"][0]["provenance"] = {"evaluated_by": "declaration"}
    redecided = copy.deepcopy(DECISIONS)
    redecided[0]["selection_identities"] = {"u2": "u2@3"}
    redecided[1]["decision_id"] = "universal_power:play-9"
    if key(play(renamed, redecided)) != base:
        fail("C1 same", "system fields changed the key")
    if key(play(decisions=list(reversed(copy.deepcopy(DECISIONS))))) != base:
        fail("C1 same", "the order decisions are listed in changed the key")
    # C2
    variants = {"card": lambda d, x: d.update(card="c2"),
                "source": lambda d, x: d.update(source={"kind": "trash"}),
                "entry location": lambda d, x: d.update(entry_location={"kind": "battlefield", "battlefield": "bf1"}),
                "additional cost": lambda d, x: d["cost"]["additional"][0].update(payment={"kind": "exhaust", "object_id": "g2"}),
                "Add window": lambda d, x: d["payment_context"].update(add_window_closed=False),
                "target": lambda d, x: x[0].update(value=["u3"]),
                "Universal allocation": lambda d, x: x[1].update(value={"calm": 1}),
                "mode": lambda d, x: x.append({"decision_id": "mode", "stage": "play_declaration", "kind": "mode_selection",
                                               "controller": "p1", "value": "m2"})}
    for label, change in variants.items():
        declaration, decisions = copy.deepcopy(PLAY), copy.deepcopy(DECISIONS)
        change(declaration, decisions)
        if key(play(declaration, decisions)) == base:
            fail("C2 different", f"a different {label} has the same key")
    # C3
    move = {"kind": "standard_move", "declaration": {"schema_version": "v", "actor": "p1", "units": ["u1", "u2"],
                                                     "unit_identities": {"u1": "u1@0", "u2": "u2@0"},
                                                     "destination": {"kind": "battlefield", "battlefield": "bf1"},
                                                     "cost_confirmation": {"exhaust_confirmed": True}}}
    swapped = copy.deepcopy(move)
    swapped["declaration"]["units"] = ["u2", "u1"]
    swapped["declaration"]["unit_identities"] = {"u1": "u1@4", "u2": "u2@4"}
    if key(move) != key(swapped):
        fail("C3 moves", "the order of the units, or their identity tokens, changed the key")
    elsewhere = copy.deepcopy(move)
    elsewhere["declaration"]["destination"] = {"kind": "battlefield", "battlefield": "bf2"}
    if key(elsewhere) == key(move):
        fail("C3 moves", "another destination has the same key")
    # C4
    smuggled = copy.deepcopy(PLAY)
    smuggled["secret_choice"] = 1
    try:
        key(play(smuggled))
        fail("C4 closed", "an unclassified field was keyed")
    except ValueError:
        pass
    # C5
    if A._decision_role("cost:play-7:text-cost", ("play-7",)) != "cost:@:text-cost" \
            or A._decision_role("cost:replay-7x:text-cost", ("play-7",)) != "cost:replay-7x:text-cost":
        fail("C5 ids", "a decision id's role is not read part by part")
    # C6 (package 15, GPT PACKAGE15 ruling 2): every refusal standard_move names is classed - a moved unit's own (in a
    # loop over the units, reading that unit) or the Move's - so D(s) excludes a unit only for a refusal that refuses
    # every set holding it; one added unclassed fails here (and, at run time, is unproved by name)
    import combat
    import inspect
    import re as _re
    source = inspect.getsource(combat.standard_move)
    named = set(_re.findall(r'_refuse\(base, "([a-z_]+)"', source))
    loose = named - combat.STANDARD_MOVE_UNIT_REFUSALS - combat.STANDARD_MOVE_WHOLE_REFUSALS - {"standard_move_timing_illegal"}
    if not named or loose:
        fail("C6 move refusals", f"standard_move refuses by {sorted(loose)} unclassed (named {sorted(named)})")
    if "restriction[\"reason_code\"]" not in source or not {"move_restricted_by_location"} <= combat.STANDARD_MOVE_UNIT_REFUSALS:
        fail("C6 move refusals", "the Battlefield restriction's refusal is not classed as a unit's own")

    if errors:
        print("FAILED: the action space")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {len(A.ACTION_KINDS)} discretionary kinds match the enumerator's families, {len(A.LIMITED_ACTIONS)} "
          f"limited actions apart; every field of the {len(A.FIELD_CLASSES)} declaration shapes is classified; the action "
          f"key keeps every rule-meaningful choice and no system field; every Standard Move refusal is classed (K1-K3, F1, C1-C6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
