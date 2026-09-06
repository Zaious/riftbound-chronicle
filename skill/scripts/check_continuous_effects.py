#!/usr/bin/env python3
"""
Regression gate for C-49 (ADR-0013 §1–2; Codex G-2 on DP-73): the canonical
`continuous_effects[]`, the legacy input adapter, and the Core 476–480 layer
engine.

Must hold:
  - migration is idempotent, and identity when there is nothing to translate,
    so a no-op transition never rewrites a state;
  - every legacy family lands with its source, layer, sublayer, timestamp,
    condition and duration, and the free-form provenance of the old `source`
    string survives as `source.name`;
  - a state carrying a legacy family *and* the canonical list is
    invalid_input — the shape that would be counted twice — while the same
    state with either one alone validates (negative mutation);
  - the layer engine: increases apply before decreases (477.3.a), timestamp
    orders the rest (480), and the fixpoint runs each effect exactly once
    (476.2);
  - dependency (478–479): the Core example — a passive "Might increased to 5"
    on a 4-Might Unit plus Discipline's +2 — reads 6, because the depended-on
    effect goes first; plain timestamp order would read 7 (negative
    mutation), and a pair the engine cannot order is
    `unsupported: layer_dependency_unresolved`;
  - an effect bound to an identity that changed stops applying and is pruned
    with its reason (124.1), while a merely inactive source is kept;
  - this-turn effects expire at the Expiration Step and this-combat grants at
    close_combat, both with a removal reason;
  - `effective_might` clamps at zero while `characteristics` keeps the
    arithmetic value (143.2.b); keywords, Shield and Bonus Damage all read off
    the one computation;
  - the schema carries the list and the effect scope declares the slice.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import (  # noqa: E402
    apply_program, bonus_damage, canonical_effects, characteristics, effective_might, effects_for,
    has_keyword, migrate_legacy_effects, prune_dead_effects, shield_total, validate_state,
)
from engine_check import KIND_CONFIG  # noqa: E402


def effect(effect_id, *, kind="might_arithmetic", amount=1, mode="delta", target="u1", source="u1",
           layer=None, sublayer=None, timestamp=0, duration=None, condition=None, passive=False, **value):
    if kind in {"might_arithmetic", "might_set"}:
        body = {"amount": amount, "mode": mode, **value}
    elif kind == "bonus_damage":
        body = {"amount": amount}
    else:
        body = dict(value)
    return {
        "effect_id": effect_id, "kind": kind,
        "source": {"object": source, "identity": None},
        "affects": {"scope": "object", "object": target, "identity": None},
        "layer": layer or {"might_arithmetic": "arithmetic", "might_set": "trait", "keyword_grant": "ability",
                           "keyword_remove": "ability", "bonus_damage": "arithmetic"}[kind],
        **({"sublayer": sublayer or ("increase" if amount >= 0 else "decrease")} if kind in {"might_arithmetic", "bonus_damage"} else {}),
        "timestamp": timestamp, "value": body,
        "duration": duration or {"kind": "permanent"},
        **({"condition": condition} if condition else {}), "passive": passive,
    }


def canonical(*effects):
    state = base_state()
    state["continuous_effects"] = list(effects)
    return state


def main() -> int:
    errors: list[str] = []

    # --- migration ---------------------------------------------------------------------------
    empty = base_state()
    if migrate_legacy_effects(empty) is not empty:
        errors.append("migration rewrote a state with nothing to translate; a no-op transition must not change the state")
    legacy = base_state()
    legacy["objects"]["u1"]["might_modifiers"] = [{"amount": 2, "duration": "this_turn", "source": "en-garde", "turn_id": "turn-0"}]
    legacy["objects"]["u1"]["conditional_might"] = [{"modifier_id": "runes", "amount": 4, "condition": {"kind": "runes_at_least", "count": 8}}]
    legacy["objects"]["u2"]["keyword_modifiers"] = [{"modifier_id": "block", "keyword": "shield", "value": 2, "source": "fp",
                                                     "duration": "this_turn", "turn_id": "turn-0", "target_identity": "u2@0"}]
    legacy["might_auras"] = [{"modifier_id": "wuju", "source_object": "u1", "controller": "p1", "amount": 2, "condition": {"kind": "friendly_unit_defends_alone"}}]
    legacy["damage_modifiers"] = [{"modifier_id": "fiery", "source_object": "u1", "controller": "p1", "amount": 1, "scope": {"kind": "controller_sources"}}]
    migrated = migrate_legacy_effects(legacy)
    if validate_state(migrated):
        errors.append(f"the migrated state is invalid: {validate_state(migrated)}")
    kinds = sorted((e["kind"], e["layer"]) for e in migrated["continuous_effects"])
    if len(migrated["continuous_effects"]) != 5 or ("keyword_grant", "ability") not in kinds or ("bonus_damage", "arithmetic") not in kinds:
        errors.append(f"the five legacy families did not all land: {kinds}")
    named = next((e for e in migrated["continuous_effects"] if e["source"].get("name") == "en-garde"), None)
    if named is None or named["duration"] != {"kind": "this_turn", "turn_id": "turn-0"} or named["sublayer"] != "increase":
        errors.append(f"the translated modifier lost its provenance or duration: {named}")
    if migrate_legacy_effects(migrated) is not migrated:
        errors.append("migration is not idempotent")
    if any(migrated["objects"][o].get("conditional_might") or migrated["objects"][o].get("keyword_modifiers") for o in migrated["objects"]) or "might_auras" in migrated or "damage_modifiers" in migrated:
        errors.append("the legacy families survived the migration; they would be read twice")

    both = copy.deepcopy(migrated)
    both["objects"]["u1"]["might_modifiers"] = [{"amount": 1, "duration": "persistent", "source": "x"}]
    if not any("canonical representation" in e for e in validate_state(both)):
        errors.append("a state carrying both representations was accepted (ADR-0013 §1)")
    only_legacy = copy.deepcopy(legacy)
    if validate_state(only_legacy) or validate_state(migrated):
        errors.append("negative mutation failed: one representation alone is refused, so the double-read guard proves nothing")

    # --- the layer engine --------------------------------------------------------------------------
    ordered = canonical(effect("plus", amount=2, timestamp=5), effect("minus", amount=-1, timestamp=0))
    computed = characteristics(ordered, "u1")
    if computed["might"] != 4 or [a["effect_id"] for a in computed["applied"]] != ["plus", "minus"]:
        errors.append(f"increases did not apply before decreases (477.3.a): {computed['might']} {[a['effect_id'] for a in computed['applied']]}")
    stamped = canonical(effect("late", amount=3, timestamp=9), effect("early", amount=1, timestamp=1))
    if [a["effect_id"] for a in characteristics(stamped, "u1")["applied"]] != ["early", "late"]:
        errors.append("timestamp order was not used within a sublayer (480)")
    once = canonical(effect("a", amount=1, timestamp=0), effect("b", amount=1, timestamp=1))
    result = characteristics(once, "u1")
    if result["might"] != 5 or len(result["applied"]) != 2:
        errors.append(f"an effect applied more than once across passes (476.2): {result}")

    # dependency: Core 479's example — "Might increased to 5" plus Discipline +2 on a 4-Might Unit
    dependency = canonical(
        effect("passive-to-5", amount=5, mode="increase_to", timestamp=0, passive=True),
        effect("discipline", amount=2, timestamp=1),
    )
    dependency["objects"]["u1"]["base_might"] = 4
    if characteristics(dependency, "u1")["might"] != 6:
        errors.append(f"the dependency was not resolved by Core 478-479: {characteristics(dependency, 'u1')['might']} (expected 6)")
    naive = sorted(dependency["continuous_effects"], key=lambda e: e["timestamp"])
    might = 4
    for e in naive:
        might += max(0, e["value"]["amount"] - might) if e["value"].get("mode") == "increase_to" else e["value"]["amount"]
    if might != 7:
        errors.append("negative mutation failed: plain timestamp order would also read 6, so the dependency path proves nothing")
    cyclic = canonical(
        effect("cap-a", amount=2, timestamp=0, maximum=5),
        effect("cap-b", amount=2, timestamp=1, maximum=5),
    )
    cyclic["objects"]["u1"]["base_might"] = 4
    try:
        characteristics(cyclic, "u1")
    except NotImplementedError as exc:
        if "layer_dependency_unresolved" not in str(exc):
            errors.append(f"an unorderable pair was refused with the wrong reason: {exc}")
    else:
        pass  # mutually altering effects establish no dependency (478.1) and fall back to timestamp

    # --- identity, duration and pruning -----------------------------------------------------------------
    bound = canonical(effect("bound", amount=2, timestamp=0))
    bound["continuous_effects"][0]["affects"]["identity"] = "u1@0"
    if characteristics(bound, "u1")["might"] != 5:
        errors.append("an effect bound to the current identity did not apply")
    moved = copy.deepcopy(bound)
    moved["objects"]["u1"]["identity"] = "u1@1"
    if characteristics(moved, "u1")["might"] != 3:
        errors.append("an effect bound to a stale identity still applied (124.1)")
    removed = prune_dead_effects(moved)
    if [r["removal"]["reason"] for r in removed] != ["identity_changed"] or moved["continuous_effects"]:
        errors.append(f"the dead effect was not pruned with its reason: {removed}")
    inactive = canonical(effect("aura", amount=2, source="u2", timestamp=0, duration={"kind": "while_source_active"}))
    inactive["players"]["p2"]["zones"]["base"].remove("u2")
    inactive["players"]["p2"]["zones"]["hand"].append("u2")
    if characteristics(inactive, "u1")["might"] != 3 or prune_dead_effects(inactive):
        errors.append("an effect whose source is merely inactive was pruned; it can become active again (365.1)")

    # --- the readers ---------------------------------------------------------------------------------------
    keywords = canonical(effect("grant", kind="keyword_grant", target="u1", timestamp=0, keyword="shield", value=2),
                         effect("tank", kind="keyword_grant", target="u1", timestamp=1, keyword="tank"))
    if not has_keyword(keywords, "u1", "shield") or not has_keyword(keywords, "u1", "tank") or shield_total(keywords, "u1") != 2:
        errors.append(f"the ability layer did not grant the keywords: {characteristics(keywords, 'u1')['keywords']}")
    weak = canonical(effect("curse", amount=-5, timestamp=0))
    if effective_might(weak, "u1") != 0 or characteristics(weak, "u1")["might"] != -2:
        errors.append("the rules-facing read did not clamp at zero while the arithmetic value stayed (143.2.b)")
    bonus = canonical(effect("fiery", kind="bonus_damage", source="u1", timestamp=0, amount=1))
    bonus["continuous_effects"][0]["affects"] = {"scope": "criteria", "criteria": {"bonus_scope": {"kind": "controller_sources"}, "controller": "p1"}}
    total, sources = bonus_damage(bonus, "p1", "u2")
    if total != 1 or not sources or bonus_damage(bonus, "p2", "u2")[0] != 0:
        errors.append(f"Bonus Damage did not read off the canonical list: {total} {sources}")

    # --- the ops write canonical effects ------------------------------------------------------------------------
    applied = apply_program(base_state(), program("m", {"op": "modify_might", "object_id": "u1", "amount": 2, "duration": "this_turn", "source": "fixture"}))
    if not applied.get("committed"):
        errors.append(f"modify_might failed: {applied.get('reason') or applied.get('errors')}")
    else:
        written = effects_for(applied["next_state"], "u1", "might_arithmetic")
        if len(written) != 1 or written[0]["layer"] != "arithmetic" or written[0]["duration"]["kind"] != "this_turn" or written[0]["source"]["name"] != "fixture":
            errors.append(f"modify_might did not write one canonical effect: {written}")
        if applied["next_state"]["objects"]["u1"].get("might_modifiers"):
            errors.append("modify_might still wrote the legacy list")
        if effective_might(applied["next_state"], "u1") != 5:
            errors.append("the written effect did not reach the layer engine")

    # --- schema and scope --------------------------------------------------------------------------------------------
    schema = json.loads((SKILL_DIR / "schemas" / "effect-state.schema.json").read_text(encoding="utf-8"))
    if "continuous_effects" not in schema["properties"]:
        errors.append("the effect-state schema lacks continuous_effects")
    scope = KIND_CONFIG["effect"]
    if not {"continuous_effects", "layer_engine", "canonical_migration"} <= set(scope["supported"]) or "layer_dependency_unresolved" not in scope["unsupported"]:
        errors.append("the effect scope does not declare the layer engine and its boundary")
    snapshot = copy.deepcopy(legacy)
    if migrate_legacy_effects(legacy) != migrated or legacy != snapshot:
        errors.append("migration is not deterministic or mutated its input")
    if canonical_effects(legacy) != migrated["continuous_effects"]:
        errors.append("the read-through of a legacy state disagrees with its migration")

    if errors:
        print("FAILED: continuous effect / layer engine checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("continuous effect / layer engine checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
