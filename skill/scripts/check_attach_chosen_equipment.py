#!/usr/bin/env python3
"""Regression gate (set 2 package A2, Jax - Grandmaster At Arms: "Attach a detached Equipment you control to a unit you
control." / "Attach an attached Equipment you control to a unit you control."): an attach whose card attached is itself
a target (object_target), chosen with its Top-Most card as the ability is played (Core 355.5), and checked again as it
resolves (359.3.e); the selector state `attached` asks whether a card is attached now (Core 435, 436).

  J1 detached     p1's free Equipment and u3 chosen: the Equipment is attached to u3, at u3's location
  J2 attached     p1's Equipment on u1 and u3 chosen: it is attached to u3 now, no longer to u1 (Core 435.2.a)
  J3 wrong state  the free Equipment chosen for "an attached Equipment": refused as the ability is played
  J4 not equipment a Gear with no Equipment tag chosen: refused as it is played
  J5 changed      the free Equipment attached elsewhere before the ability resolves: no longer "detached" - ignored
  G               the grammar lowers both lines to exactly these instructions
  V               object_target beside object_id does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []
LINES = {"detached": "Attach a detached Equipment you control to a unit you control.",
         "attached": "Attach an attached Equipment you control to a unit you control."}


def lowered(state_word):
    return CG.compile_clause(LINES[state_word], CG.load_grammar()).get("program_effects")


def board():
    s = base_state()
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("u3")
    s["players"]["p1"]["zones"]["base"].remove("u1")
    s["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u1"]}
    for oid, tags, host in (("eq-free", ["Equipment"], None), ("eq-on", ["Equipment"], "u1"), ("plain", [], None)):
        s["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                             "damage": 0, "exhausted": False, "tags": tags, **({"attached_to": host} if host else {})}
        (s["battlefields"]["bf1"]["objects"] if host else s["players"]["p1"]["zones"]["base"]).append(oid)
    s["objects"]["jx"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"].setdefault("legend_zone", []).append("jx")
    return s


def program(effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "jx-a", "controller": "p1", "source_object": "jx", "effects": copy.deepcopy(effects)}


def picks(s, card, host):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
         "value": [oid], "selection_identities": {oid: object_identity(s, oid)}} for ref, oid in (("e", card), ("u", host))]}


def activate(s, effects, card, host):
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "act-jx", "actor": "p1", "card": "jx",
            "chain_item": {"id": "ability-jx", "object_kind": "ability", "timing": "default", "ability_kind": "standard"},
            "activation": {"source_object": "jx", "ability_id": "jx:a1"},
            "cost": {"base": {"energy": 0, "power": {}}}, "effect_program_id": "jx-a",
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return PT.play_card(fixture(), s, decl, engine_decisions=picks(s, card, host), effect_program=program(effects))


def main() -> int:
    detached, attached = lowered("detached"), lowered("attached")
    want = {"detached": False, "attached": True}
    for word, effects in (("detached", detached), ("attached", attached)):
        if not effects or effects[0].get("op") != "attach" or effects[0]["object_target"].get("attached") is not want[word] \
                or effects[0]["object_target"].get("with_tag") != "Equipment" or "decision_ref" not in effects[0]["target"]:
            errors.append(f"G: {word} lowered to {effects}")
    if errors:
        return report()
    s = board()
    for label, effects, card in (("J1 detached", detached, "eq-free"), ("J2 attached", attached, "eq-on")):
        done = apply_program(s, program(effects), decisions=picks(s, card, "u3"))
        got = (done.get("next_state") or {}).get("objects", {}).get(card) or {}
        if not done.get("committed") or got.get("attached_to") != "u3" \
                or card not in done["next_state"]["players"]["p1"]["zones"]["base"]:
            errors.append(f"{label}: {done.get('reason') or done.get('errors')} {got}")
    for label, effects, card in (("J3 wrong state", attached, "eq-free"), ("J4 not equipment", detached, "plain")):
        refused = activate(s, effects, card, "u3")
        if refused.get("committed") or refused.get("reason_code") != "target_illegal_at_play":
            errors.append(f"{label}: {refused.get('committed')} {refused.get('reason_code')}")
    if not activate(s, detached, "eq-free", "u3").get("committed"):
        errors.append("J1 detached: the activation itself was refused")
    changed = copy.deepcopy(s)
    changed["objects"]["eq-free"]["attached_to"] = "u1"
    changed["players"]["p1"]["zones"]["base"].remove("eq-free")
    changed["battlefields"]["bf1"]["objects"].append("eq-free")
    late = apply_program(changed, program(detached), decisions=picks(changed, "eq-free", "u3"))
    if not late.get("committed") or [t.get("outcome") for t in late.get("trace") or []] != ["ignored_illegal_target"]:
        errors.append(f"J5 changed: {late.get('reason') or late.get('errors')} {[t.get('outcome') for t in late.get('trace') or []]}")
    bad = program([{**detached[0], "object_id": "eq-free"}])
    if not validate_program(bad):
        errors.append("V: object_target beside object_id validated")
    return report()


def report() -> int:
    if errors:
        print("FAILED: attach a chosen Equipment")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'attach a detached / an attached Equipment you control to a unit you control' - both chosen as it is "
          "played, the Equipment's state read then and again as it resolves; attached at the unit's location (J1-J5, G, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
