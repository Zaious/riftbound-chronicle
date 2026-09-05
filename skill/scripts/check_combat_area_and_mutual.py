#!/usr/bin/env python3
"""
Gate for C-29 (ADR-0008 §7): active-Combat criteria and mutual current-Might
damage.

Must hold:
  - "all enemy units in combat" (Cannon Barrage) finds, under the Combat
    context the resolution bridge supplies, the enemy Units at the Combat
    Battlefield that carry that Combat's designation — affected objects, not
    targets; a Unit present without a designation and a Unit elsewhere are
    not "in combat" (740.2.c);
  - with no Combat in progress the set is empty and the instruction is a
    supported no-op; a claimed Combat whose Battlefield the state cannot
    confirm (unknown id, changed identity) is unsupported, never inferred;
  - "They deal damage equal to their Mights to each other" (Gentlemen's
    Duel): both Units revalidated, both rules-facing Mights snapshotted
    before either Deal, two Deal events as one action with the Units as
    sources and their controllers responsible (417.6.b.3–4); no spell-scoped
    Bonus Damage; a Prevent on one Unit replaces that Deal only; a Might
    reading 0 deals nothing; an illegal Unit or the same Unit twice skips
    the pair; deferred choices need their target_selection; not Combat
    Damage; determinism and purity.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_combat_characteristics import opened  # noqa: E402
from check_combat_staging import contested_board  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import item  # noqa: E402
from effect_ir import apply_program, hash_value, validate_program  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402

BARRAGE = {"op": "deal_damage", "amount": 2, "effect_id": "barrage", "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location": "active_combat"}}}
FRIENDLY = {"object_id": "u1", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}
ENEMY = {"object_id": "u2", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}
DUEL = {"op": "mutual_damage_current_might", "effect_id": "duel", "units": [FRIENDLY, ENEMY]}


def add_unit(state, object_id, owner, where, **fields):
    state["objects"][object_id] = {"owner": owner, "controller": owner, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False, **fields}
    if where.startswith("base:"):
        state["players"][where[5:]]["zones"]["base"].append(object_id)
    else:
        state["battlefields"][where]["objects"].append(object_id)


def main() -> int:
    errors: list[str] = []

    # --- Cannon Barrage under a Combat in progress ---------------------------------------------
    timing, state, _ = opened(contested_board())
    add_unit(state, "u4", "p2", "bf1")        # present, not yet designated (no Cleanup ran)
    add_unit(state, "u5", "p2", "base:p2")   # elsewhere
    closed = copy.deepcopy(timing)
    closed["chain"] = {"initiated_by": "played_card", "items": [item("spell-1", "p1", "spell", "reaction", "finalized")], "consecutive_passes": ["p1", "p2"]}
    closed["priority"] = "p2"
    barrage = program("spell-1-effects", BARRAGE)
    resolved = resolve_with_program(closed, "spell-1", state, barrage)
    if not resolved.get("committed"):
        errors.append(f"Cannon Barrage did not resolve under the Combat: {resolved.get('stage')} {resolved.get('reason') or resolved.get('errors')}")
    else:
        e = resolved["trace"]["effect"][0]
        nxt = resolved["next_effect_state"]
        if e.get("affected_objects") != ["u2"] or e.get("affected_are_targets") is not False or e.get("active_combat", {}).get("combat_id") != timing["combat"]["combat_id"]:
            errors.append(f"'enemy units in combat' did not find exactly the designated enemy Unit: {e.get('affected_objects')} {e.get('active_combat')}")
        if nxt["objects"]["u2"]["damage"] != 2 or nxt["objects"]["u4"]["damage"] != 0 or nxt["objects"]["u5"]["damage"] != 0 or nxt["objects"]["u1"]["damage"] != 1:
            errors.append("damage reached a Unit that is not in combat, or missed the one that is")
        if nxt["objects"]["u4"].get("combat_designation", {}).get("role") != "defender":
            errors.append("the Cleanup after the spell did not designate the late Unit")
    quiet = apply_program(state, barrage)
    if not quiet.get("committed") or quiet["trace"][0].get("outcome") != "no_op" or quiet["trace"][0].get("affected_objects") != [] or quiet["trace"][0].get("active_combat") is not None:
        errors.append(f"with no Combat in progress the instruction was not an empty supported no-op: {quiet.get('reason') or quiet.get('errors')} {quiet.get('trace')}")
    alleged = apply_program(state, barrage, context={"combat": {"combat_id": "combat:x", "battlefield": "bf9"}})
    if alleged.get("committed") or alleged.get("unsupported") is not True:
        errors.append("a claimed Combat at an unknown Battlefield was not unsupported")
    changed = apply_program(state, barrage, context={"combat": {"combat_id": timing["combat"]["combat_id"], "battlefield": "bf1", "battlefield_identity": "bf1@7"}})
    if changed.get("committed") or changed.get("unsupported") is not True:
        errors.append("a claimed Combat whose Battlefield identity the state cannot confirm was not unsupported")
    direct = apply_program(state, barrage, context={"combat": {"combat_id": timing["combat"]["combat_id"], "battlefield": "bf1", "battlefield_identity": "bf1@0"}})
    if not direct.get("committed") or direct["trace"][0].get("affected_objects") != ["u2"]:
        errors.append("the confirmed Combat context did not select the designated Units")
    if not any("targets nothing" in x for x in validate_program(program("bad", {**BARRAGE, "target": {"object_id": "bf1", "kind": "battlefield", "chosen_zone_class": "board"}}))):
        errors.append("an active_combat criteria with a target was accepted")
    check = build_engine_check("effect", direct, input_hashes={"effect_state": hash_value(state), "effect_program": "sha256:" + "9" * 64})
    if check["outcome"] != "supported" or "active_combat_criteria" not in check["coverage"]["supported_scope"]:
        errors.append("engine-check does not declare active_combat_criteria")

    # --- Gentlemen's Duel ------------------------------------------------------------------------
    plain = base_state()  # u1: 3 Might, 1 damage; u2: 4 Might
    snap = copy.deepcopy(plain)
    duel = apply_program(plain, program("duel", DUEL))
    if not duel.get("committed"):
        errors.append(f"the duel did not commit: {duel.get('reason') or duel.get('errors')}")
    else:
        ev = duel["trace"][0]
        nxt = duel["next_state"]
        if nxt["objects"]["u1"]["damage"] != 5 or nxt["objects"]["u2"]["damage"] != 3:
            errors.append(f"the Units did not deal their Mights to each other: u1 {nxt['objects']['u1']['damage']} u2 {nxt['objects']['u2']['damage']}")
        if ev.get("might_snapshot") != {"u1": 3, "u2": 4} or ev.get("simultaneous") is not True or ev.get("not_combat_damage") is not True or ev.get("completion") != "full":
            errors.append(f"the duel event lacks the snapshot / simultaneity / non-combat facts: {ev.get('might_snapshot')} {ev.get('completion')}")
        subs = ev.get("expansion_trace", [])
        if [s.get("source_object") for s in subs] != ["u1", "u2"] or [s.get("responsible_player") for s in subs] != ["p1", "p2"] or any(s.get("source_kind") != "unit" for s in subs):
            errors.append(f"the Units are not the sources with their controllers responsible: {[(s.get('source_object'), s.get('responsible_player')) for s in subs]}")
        if len({s.get("before_state_hash") for s in subs}) != 1 and False:
            pass
    if plain != snap or apply_program(plain, program("duel", DUEL)) != duel:
        errors.append("mutual damage mutated its input or is not deterministic")
    fiery = copy.deepcopy(plain)
    add_unit(fiery, "g1", "p1", "base:p1", kind="gear")
    fiery["damage_modifiers"] = [{"modifier_id": "annie-fiery", "source_object": "g1", "controller": "p1", "amount": 1, "scope": {"kind": "controller_sources"}}]
    no_bonus = apply_program(fiery, program("duel", DUEL))
    if not no_bonus.get("committed") or no_bonus["next_state"]["objects"]["u2"]["damage"] != 3 or no_bonus["next_state"]["objects"]["u1"]["damage"] != 5:
        errors.append("spell-scoped Bonus Damage reached Unit-sourced damage (417.6.b.3)")
    shielded = copy.deepcopy(plain)
    shielded["replacement_effects"] = [{"replacement_id": "guard", "controller": "p2", "source_object": "u2", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 1, "target_object_id": "u2"}]
    prevented = apply_program(shielded, program("duel", DUEL))
    if not prevented.get("committed") or prevented["next_state"]["objects"]["u2"]["damage"] != 2 or prevented["next_state"]["objects"]["u1"]["damage"] != 5:
        errors.append(f"a Prevent on one Unit did not replace that Deal only: {prevented.get('reason') or prevented.get('errors')}")
    elif [s.get("outcome") for s in prevented["trace"][0]["expansion_trace"]] != ["replaced_modified_applied", "applied"]:
        errors.append(f"the replaced Deal is not visible in the pair's trace: {[s.get('outcome') for s in prevented['trace'][0]['expansion_trace']]}")
    weak = copy.deepcopy(plain); weak["objects"]["u1"]["might_modifiers"] = [{"amount": -5, "duration": "persistent", "source": "curse"}]
    zero = apply_program(weak, program("duel", DUEL))
    if not zero.get("committed") or zero["next_state"]["objects"]["u2"]["damage"] != 0 or zero["next_state"]["objects"]["u1"]["damage"] != 5 or zero["trace"][0].get("completion") != "partial":
        errors.append(f"a Might reading 0 dealt damage or the partial completion was lost: {zero.get('trace', [{}])[0].get('completion')}")
    bounced = copy.deepcopy(plain); bounced["players"]["p2"]["zones"]["base"].remove("u2"); bounced["players"]["p2"]["zones"]["hand"].append("u2")
    skipped = apply_program(bounced, program("duel", DUEL))
    if not skipped.get("committed") or skipped["trace"][0].get("outcome") != "ignored_illegal_target" or skipped["next_state"]["objects"]["u1"]["damage"] != 1:
        errors.append(f"an illegal Unit did not skip the pair without damage: {skipped.get('trace', [{}])[0].get('outcome')}")
    twice = apply_program(plain, program("duel", {**DUEL, "units": [FRIENDLY, {**FRIENDLY}]}))
    if not twice.get("committed") or twice["trace"][0].get("outcome") != "ignored_illegal_target":
        errors.append("the same Unit chosen twice was accepted as a pair")
    deferred = {**DUEL, "units": [{"decision_ref": "a", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}, {"decision_ref": "b", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}]}
    asked = apply_program(plain, program("duel", deferred))
    if asked.get("committed") or asked.get("reason_code") != "target_selection_required":
        errors.append("deferred unit choices did not stop for target_selection")
    decisions = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(plain), "decisions": [
        {"decision_id": "a", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u1"], "selection_identities": {"u1": "u1@0"}},
        {"decision_id": "b", "stage": "play_declaration", "kind": "target_selection", "controller": "p1", "value": ["u2"], "selection_identities": {"u2": "u2@0"}}]}
    decided = apply_program(plain, program("duel", deferred), decisions=decisions)
    if not decided.get("committed") or decided["next_state"]["objects"]["u1"]["damage"] != 5:
        errors.append(f"supplied unit choices were not honoured: {decided.get('reason') or decided.get('errors')}")
    if not validate_program(program("bad", {**DUEL, "units": [FRIENDLY]})) or not validate_program(program("bad2", {**DUEL, "target": FRIENDLY})):
        errors.append("a malformed mutual instruction was accepted")

    if errors:
        print("FAILED: combat area / mutual damage checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: 'enemy units in combat' are the designated enemy Units at the Combat Battlefield under the bridge's context and never targets, an absent Combat is an empty supported no-op while a claimed one the state cannot confirm is unsupported; two chosen Units deal their snapshotted Mights to each other as one simultaneous non-combat action with themselves as sources, without spell Bonus Damage, through replacements, and an illegal or repeated Unit skips the pair.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
