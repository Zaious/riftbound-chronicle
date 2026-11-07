#!/usr/bin/env python3
"""Regression gate (set 2 package A2, Forge of the Fluft: "While you control this battlefield, friendly legends have
'[Exhaust]: Attach an Equipment you control to a unit you control.'"): a Battlefield's grant of an [Exhaust] ability to
its controller's Legends (battlefields.<id>.legend_ability_grants, Core 190.6, 377), activated naming the grant
(activation.granted_by) and checked before anything is paid.

  G1 granted      p1 controls bf1: p1's Legend activates it, exhausted for it; it resolves: the Equipment is attached
  G2 not theirs   bf1 is p2's: refused (granted_ability_not_had), nothing paid
  G3 program      the activation runs other instructions: refused (granted_ability_program_mismatch)
  G4 not a legend a Unit of p1's names the grant: refused
  G5 cost         declared without its [Exhaust]: refused (granted_ability_cost_mismatch)
  G6 grammar      the printed line lowers to exactly that grant
  G7 control lost activated while p1 controls bf1, then bf1's controller becomes p2 before it resolves: the ability
                  is its own Chain item, already legally activated - it still resolves and attaches the Equipment
                  (Core 190.6, 377.3)
  G8 no longer    after control of bf1 passed to p2, p1's (readied) Legend activating it again: refused
                  (granted_ability_not_had) - losing control stops new activations
  G9 targets      the Equipment ("e") and the unit ("u") are recorded on the Chain item as chosen at activation
                  (played_targets, stage play_declaration, Core 355.5), not supplied at resolution
  V               a grant with another cost does not validate
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import PROGRAM_VERSION, hash_value, object_identity, validate_state  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, finalize_oldest_pending, next_procedure, pass_priority  # noqa: E402

errors: list[str] = []
TEXT = ("While you control this battlefield, friendly legends have &quot;:rb_exhaust:: Attach an Equipment you control to "
        "a unit you control.&quot;")
GRANTS = CG.compile_clause(TEXT, CG.load_grammar())["passive"]["battlefield_fields"]["legend_ability_grants"]


def board(*, holder="p1"):
    s = base_state()
    s["battlefields"]["bf1"] = {"controller": holder, "objects": [], "legend_ability_grants": copy.deepcopy(GRANTS)}
    s["objects"]["lg"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"].setdefault("legend_zone", []).append("lg")
    s["objects"]["eq"] = {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Equipment"]}
    s["players"]["p1"]["zones"]["base"].append("eq")
    return s


def activate(s, *, source="lg", effects=None, exhaust=True):
    prog = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "forge-grant", "controller": "p1", "source_object": source,
            "effects": copy.deepcopy(GRANTS[0]["effects"] if effects is None else effects)}
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "act-forge", "actor": "p1", "card": source,
            "chain_item": {"id": "ability-forge", "object_kind": "ability", "timing": "default", "ability_kind": "standard"},
            "activation": {"source_object": source, "ability_id": f"{source}:granted:bf1:attach-equipment",
                           "granted_by": {"battlefield": "bf1", "grant_id": "attach-equipment"}},
            "cost": {"base": {"energy": 0, "power": {}},
                     **({"additional": [{"cost_id": "exhaust-self", "mandatory": True,
                                         "payment": {"kind": "exhaust", "object_id": source}}]} if exhaust else {})},
            "effect_program_id": "forge-grant", "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(s), "decisions": [
        {"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": [oid],
         "selection_identities": {oid: object_identity(s, oid)}} for ref, oid in (("e", "eq"), ("u", "u1"))]}
    return PT.play_card(fixture(), s, decl, engine_decisions=decisions, effect_program=prog), prog


def to_resolution(timing):
    """Finalizes and passes until the newest finalized item resolves next."""
    for _ in range(8):
        step = next_procedure(timing)
        if step.get("procedure") == "resolve_newest_finalized":
            break
        if step.get("procedure") == "finalize_oldest_pending":
            timing = finalize_oldest_pending(timing)["next_state"]
            continue
        timing = (pass_priority(timing, timing.get("priority")) or {}).get("next_state") or timing
    return timing


def main() -> int:
    s = board()
    if validate_state(s):
        errors.append(f"board: {validate_state(s)[:2]}")
    played, prog = activate(s)
    if not played.get("committed") or not played["next_effect_state"]["objects"]["lg"].get("exhausted"):
        errors.append(f"G1 granted: {played.get('reason_code')} {played.get('reason')}")
    else:
        done = resolve_with_program(to_resolution(played["next_timing_state"]), "ability-forge", played["next_effect_state"], prog)
        if not done.get("committed") or done["next_effect_state"]["objects"]["eq"].get("attached_to") != "u1":
            errors.append(f"G1 granted: resolution {done.get('reason')} {(done.get('next_effect_state') or {}).get('objects', {}).get('eq')}")
        # G9: both choices were made as it was activated and are the Chain item's record
        record = (played["next_effect_state"].get("chain_items") or {}).get("ability-forge", {}).get("played_targets") or []
        chosen = {r.get("decision_id"): (r.get("stage"), r.get("value")) for r in record}
        if chosen != {"e": ("play_declaration", ["eq"]), "u": ("play_declaration", ["u1"])}:
            errors.append(f"G9 targets: the activation's chain item records {chosen}, not e=eq and u=u1 chosen at play")
        # G7: bf1 changes controller while the ability waits on the Chain - it still resolves
        lost = copy.deepcopy(played["next_effect_state"])
        lost["battlefields"]["bf1"]["controller"] = "p2"
        if validate_state(lost):
            errors.append(f"G7 control lost: the board with bf1 p2's does not validate: {validate_state(lost)[:2]}")
        kept = resolve_with_program(to_resolution(played["next_timing_state"]), "ability-forge", lost, prog)
        if not kept.get("committed") or kept["next_effect_state"]["objects"]["eq"].get("attached_to") != "u1":
            errors.append(f"G7 control lost: the already-activated ability did not resolve: {kept.get('stage')} "
                          f"{kept.get('reason_code')} {kept.get('reason')} "
                          f"{(kept.get('next_effect_state') or {}).get('objects', {}).get('eq')}")
        else:
            # G8: from there, p1's Legend (readied) activating it again is refused - p1 no longer controls bf1
            again = copy.deepcopy(kept["next_effect_state"])
            again["objects"]["lg"]["exhausted"] = False
            again["objects"]["eq"].pop("attached_to", None)
            refused, _ = activate(again)
            if refused.get("committed") or refused.get("reason_code") != "granted_ability_not_had":
                errors.append(f"G8 no longer: {refused.get('committed')} {refused.get('reason_code')} {refused.get('reason')}")
            # negative mutation: the same board with bf1 back under p1's control activates, so the refusal is control
            regained = copy.deepcopy(again)
            regained["battlefields"]["bf1"]["controller"] = "p1"
            if not activate(regained)[0].get("committed"):
                errors.append(f"G8 no longer: negative mutation - with bf1 p1's again the activation was refused too: "
                              f"{activate(regained)[0].get('reason_code')}")
    for label, got, code in (("G2 not theirs", activate(board(holder="p2"))[0], "granted_ability_not_had"),
                             ("G3 program", activate(s, effects=[{**GRANTS[0]["effects"][0], "effect_id": "other"}])[0],
                              "granted_ability_program_mismatch"),
                             ("G4 not a legend", activate(s, source="u1")[0], "granted_ability_not_had"),
                             ("G5 cost", activate(s, exhaust=False)[0], "granted_ability_cost_mismatch")):
        if got.get("committed") or got.get("reason_code") != code:
            errors.append(f"{label}: {got.get('committed')} {got.get('reason_code')} {got.get('reason')}")
    grant = GRANTS[0]
    if grant.get("cost") != {"energy": 0, "power": {}, "exhaust": True} or grant["effects"][0].get("op") != "attach":
        errors.append(f"G6 grammar: {GRANTS}")
    bad = board()
    bad["battlefields"]["bf1"]["legend_ability_grants"][0]["cost"] = {"energy": 1, "power": {}, "exhaust": True}
    if not any("legend_ability_grants" in p for p in validate_state(bad)):
        errors.append("V: a grant costing [1] validated")
    if errors:
        print("FAILED: a Battlefield's ability granted to its controller's Legends")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: while p1 controls the Battlefield its Legends have the granted [Exhaust] ability - activated, paid, resolved; "
          "another controller, other instructions, a Unit, or the cost without [Exhaust] refused before payment; targets "
          "recorded at activation; losing control after activation does not stop it resolving, only new activations (G1-G9, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
