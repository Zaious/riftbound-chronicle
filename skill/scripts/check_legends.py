#!/usr/bin/env python3
"""
Regression gate for C-47 (ADR-0012 §5, §7; Codex G-1 on DP-68 / DP-69):
Legends and the Champion Zone as engine objects, passives sourced by a Legend,
and the typed copy request that fails closed.

Must hold:
  - a legend exists only in a Legend Zone or Banishment (107.4.d): the
    validator accepts both, refuses a legend at a Base, at a Battlefield or
    in a hand, and refuses a non-legend in a Legend Zone;
  - a passive whose source is a Legend in the Legend Zone is active even
    though the Legend is not on the Board (365.1, 107.4.d) — Bonus Damage and
    a Might aura both apply; the same passive with the Legend in Banishment
    contributes nothing (negative mutation), so the rule is about the Legend
    Zone and not about legends in general;
  - a generic Board effect never reaches a Legend: a board-class target on it
    fails, a `unit` requirement fails, and only a selector naming
    location legend_zone with non_board class finds it (355.9.b, 355.10.a);
  - copy_object is typed and fails closed: the validator refuses a missing
    source or request id, the resolver answers unsupported naming
    copy_characteristics, nothing changes, and engine-check wraps it as
    unsupported;
  - the effect scope declares legend objects and keeps copy characteristics
    unsupported; the manifest cites copy_object; determinism and purity.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from capability_manifest import build_manifest  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import OP_RULES, apply_program, bonus_damage, effective_might, evaluate_target, hash_value, source_active, validate_program, validate_state  # noqa: E402
from engine_check import KIND_CONFIG, build_engine_check  # noqa: E402


def with_legend(zone="legend_zone"):
    state = base_state()
    state["objects"]["l1"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False, "champion_legend": True}
    state["players"]["p1"]["zones"].setdefault(zone, []).append("l1")
    return state


def main() -> int:
    errors: list[str] = []
    state = with_legend()

    # --- where a legend may be -----------------------------------------------------------------
    if validate_state(state):
        errors.append(f"a Legend in the Legend Zone is invalid: {validate_state(state)}")
    banished = with_legend("banishment")
    if validate_state(banished):
        errors.append(f"a Legend in Banishment is invalid: {validate_state(banished)}")
    for label, zone in (("a Base", "base"), ("a hand", "hand"), ("a trash", "trash")):
        misplaced = base_state()
        misplaced["objects"]["l1"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
        misplaced["players"]["p1"]["zones"][zone].append("l1")
        if not any("legend" in e for e in validate_state(misplaced)):
            errors.append(f"a legend in {label} was accepted (107.4.d)")
    on_board = base_state()
    on_board["objects"]["l1"] = {"owner": "p1", "controller": "p1", "kind": "legend", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
    on_board["battlefields"]["bf1"]["objects"].append("l1")
    if not any("legend" in e for e in validate_state(on_board)):
        errors.append("a legend at a Battlefield was accepted (107.4.d)")
    intruder = copy.deepcopy(state)
    intruder["players"]["p1"]["zones"]["main_deck"].remove("c1")
    intruder["players"]["p1"]["zones"]["legend_zone"].append("c1")
    if not any("legend_zone" in e for e in validate_state(intruder)):
        errors.append("a non-legend card in the Legend Zone was accepted")

    # --- a Legend is an active source ------------------------------------------------------------------
    if not source_active(state, "l1") or source_active(banished, "l1"):
        errors.append("a Legend in the Legend Zone is not active, or one in Banishment is")
    damage = copy.deepcopy(state)
    damage["damage_modifiers"] = [{"modifier_id": "fiery", "source_object": "l1", "controller": "p1", "amount": 1, "scope": {"kind": "controller_sources"}}]
    total, sources = bonus_damage(damage, "p1", "u2")
    if total != 1 or not sources:
        errors.append(f"a Legend's Bonus Damage did not apply: {total} {sources}")
    dead_source = copy.deepcopy(damage)
    dead_source["players"]["p1"]["zones"]["legend_zone"].remove("l1")
    dead_source["players"]["p1"]["zones"]["banishment"].append("l1")
    if bonus_damage(dead_source, "p1", "u2")[0] != 0:
        errors.append("negative mutation failed: a banished Legend still gave Bonus Damage, so the rule is not about the Legend Zone")
    aura = copy.deepcopy(state)
    aura["players"]["p1"]["zones"]["base"].remove("u1")
    aura["battlefields"]["bf1"]["objects"].append("u1")
    aura["objects"]["u1"]["combat_designation"] = {"combat_id": "combat-1", "role": "defender"}
    aura["might_auras"] = [{"modifier_id": "wuju", "source_object": "l1", "controller": "p1", "amount": 2, "condition": {"kind": "friendly_unit_defends_alone"}}]
    if effective_might(aura, "u1") != 5:
        errors.append(f"a Legend's Might aura did not apply: {effective_might(aura, 'u1')}")
    aura_dead = copy.deepcopy(aura)
    aura_dead["players"]["p1"]["zones"]["legend_zone"].remove("l1")
    aura_dead["players"]["p1"]["zones"]["banishment"].append("l1")
    if effective_might(aura_dead, "u1") != 3:
        errors.append("negative mutation failed: a banished Legend still gave its aura")

    # --- a Legend is not a Board object -------------------------------------------------------------------
    board_target = {"object_id": "l1", "chosen_zone_class": "board"}
    legal, reason = evaluate_target(state, board_target, "p1")
    if legal or reason != "target_changed_board_zone_class":
        errors.append(f"a board-class target reached the Legend: {legal} {reason}")
    as_unit = {"object_id": "l1", "chosen_zone_class": "non_board", "kind": "unit"}
    if evaluate_target(state, as_unit, "p1")[0]:
        errors.append("a 'unit' requirement matched a Legend (355.9.b)")
    named = {"object_id": "l1", "chosen_zone_class": "non_board", "kind": "legend", "location": "legend_zone"}
    legal, reason = evaluate_target(state, named, "p1")
    if not legal:
        errors.append(f"a selector naming the Legend Zone could not find the Legend: {reason}")
    elsewhere = {"object_id": "l1", "chosen_zone_class": "non_board", "kind": "legend", "location": "legend_zone"}
    if evaluate_target(banished, elsewhere, "p1")[0]:
        errors.append("a Legend Zone selector matched a banished Legend")

    # --- copy: the modelled traits apply, the rest is refused (C-53) ---------------------------------------
    copy_program = program("cp", {"op": "copy_object", "effect_id": "c", "object_id": "u1", "source_object": "u2", "request_id": "reflection-1"})
    if validate_program(copy_program):
        errors.append(f"a typed copy request was refused by the validator: {validate_program(copy_program)}")
    for missing in ({"op": "copy_object", "effect_id": "c", "request_id": "r"}, {"op": "copy_object", "effect_id": "c", "source_object": "u2"}):
        if not validate_program(program("bad", missing)):
            errors.append(f"an incomplete copy request was accepted: {missing}")
    copied = apply_program(state, copy_program)
    if not copied.get("committed"):
        errors.append(f"copying the modelled traits was refused: {copied.get('reason_code')} {copied.get('reason')}")
    refused = apply_program(state, program("cp2", {"op": "copy_object", "effect_id": "c", "object_id": "u1", "source_object": "u2",
                                                   "request_id": "reflection-2", "traits": ["type", "cost"]}))
    if refused.get("unsupported") is not True or "copy_unmodelled_traits" not in str(refused.get("reason")) or refused.get("committed"):
        errors.append(f"a copy needing an unmodelled trait did not fail closed: {refused.get('reason_code')} {refused.get('reason')}")
    else:
        check = build_engine_check("effect", refused, input_hashes={"effect_state": hash_value(state), "effect_program": "sha256:" + "8" * 64})
        if check["outcome"] != "unsupported":
            errors.append(f"the refused copy wrapped as {check['outcome']}")

    # --- scope, manifest, determinism -------------------------------------------------------------------------
    scope = KIND_CONFIG["effect"]
    if not {"legend_objects", "legend_zone_passives"} <= set(scope["supported"]) or "copy_unmodelled_traits" not in scope["unsupported"]:
        errors.append("the effect scope does not declare Legend objects or the copy boundary")
    cited = {o["id"]: o["rule_locators"] for o in build_manifest()["operations"]}
    if cited.get("copy_object") != OP_RULES["copy_object"]:
        errors.append("the manifest does not cite copy_object")
    snapshot = copy.deepcopy(state)
    if apply_program(state, copy_program) != copied or state != snapshot:
        errors.append("the copy request is not deterministic or mutated its input")

    if errors:
        print("FAILED: legend / champion zone / copy checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("legend / champion zone / copy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
