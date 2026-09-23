#!/usr/bin/env python3
"""One Unit ability, two trigger conditions: "When I attack or defend" (Core 383.4.e, 383.4.f).

The clause grammar lowers it to the SAME descriptor - the same trigger_id - in both
attack_triggers and defend_triggers. Held here:

  lowering      both fields carry one descriptor each, identical; "When I attack" alone
                still lowers to attack_triggers only
  attacker      combat._designation_triggers, for a Unit carrying the ability and gaining
                the Attacker designation, yields exactly ONE descriptor, role attacker
  defender      the same for the Defender designation: exactly one, role defender
  once          a second designation of the same identity in the same role in the same
                Combat yields nothing (383.4.e.2.a / 383.4.f.2.a)
  neither       a Unit carrying no such ability yields nothing in either role

The real Combat flow (Move -> Contested -> stage -> open) is witnessed card by card in
the private overlay's compiler; this is the engine's own contract.

    python skill/scripts/check_attack_or_defend_trigger.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import combat  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import object_identity  # noqa: E402


def main() -> int:
    errors: list[str] = []
    grammar = CG.load_grammar()
    both = CG.compile_clause("When I attack or defend, draw 1.", grammar)
    fields = (both.get("passive") or {}).get("object_fields") or {}
    if both.get("production_id") != "when_i_attack_or_defend" or set(fields) != {"attack_triggers", "defend_triggers"}:
        errors.append(f"lowering: expected attack_triggers and defend_triggers, got {both.get('production_id')} {sorted(fields)}")
    elif fields["attack_triggers"] != fields["defend_triggers"] or len(fields["attack_triggers"]) != 1:
        errors.append("lowering: the two fields do not carry one identical descriptor")
    alone = CG.compile_clause("When I attack, draw 1.", grammar)
    if set(((alone.get("passive") or {}).get("object_fields") or {})) != {"attack_triggers"}:
        errors.append("lowering: 'When I attack' no longer lowers to attack_triggers alone")

    state = base_state()
    descriptor = {**fields.get("attack_triggers", [{}])[0], "controller": "p1", "source_object": "u1",
                  "effect_program_id": "u1-aod"}
    state["objects"]["u1"]["attack_triggers"] = [copy.deepcopy(descriptor)]
    state["objects"]["u1"]["defend_triggers"] = [copy.deepcopy(descriptor)]

    def record():
        return {"combat_id": "cb1", "battlefield_identity": "bf1@0",
                "triggered_identities": {"attacker": [], "defender": []}}

    for role in ("attacker", "defender"):
        rec = record()
        found, identity = combat._designation_triggers(state, rec, "u1", role, f"b-{role}", 0)
        if len(found) != 1 or found[0].get("role") != role or found[0].get("trigger_id") != descriptor["trigger_id"]:
            errors.append(f"{role}: expected exactly one descriptor for role {role}, got {found}")
            continue
        if found[0].get("source_identity") != object_identity(state, "u1"):
            errors.append(f"{role}: the descriptor does not carry the source's identity")
        rec["triggered_identities"][role].append(identity)
        again, _ = combat._designation_triggers(state, rec, "u1", role, f"b-{role}-2", 0)
        if again:
            errors.append(f"{role}: the same identity triggered twice in one Combat")

    bare = base_state()
    for role in ("attacker", "defender"):
        found, _ = combat._designation_triggers(bare, record(), "u1", role, "b", 0)
        if found:
            errors.append(f"neither: a Unit without the ability triggered as {role}")

    if errors:
        print("FAILED: when I attack or defend")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print("when I attack or defend: one descriptor in both fields; exactly one per designation, "
          "at most once per identity per Combat, none without the ability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
