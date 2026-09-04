#!/usr/bin/env python3
"""
Regression gate for C-17 (ADR-0005 §5; Codex Q4 (b), Q5): typed linked-result
predicates and `caused_kill` as a conditional reflexive trigger.

Must hold:
  - action_performed reads the earlier instruction's event: applied → true;
    wholly prevented (replaced_prevented) → false; partly prevented
    (replaced_modified_applied) → true (359.3.e.14.c); no_op → false;
    action_not_performed is the negation;
  - requested_count_not_reached: a short Channel (partial) satisfies it, a
    full one does not; a multi-target subset satisfies it;
  - an unknown or forward effect_id is invalid_input; caused_kill as an
    effect predicate is unsupported;
  - conditional_triggers: "If this kills it" builds a Pending reflexive item
    only after Cleanup kills the damaged object, attributed to the resolving
    spell (428.5.c); a prevented death, non-lethal damage, or a prevented
    deal builds nothing; a Kill instruction attributes directly (428.5.b);
  - the bridge stays deterministic and pure; engine-check wraps it.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import apply_program, hash_value, validate_program  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import state_hash  # noqa: E402


def gated_draw(kind, effect_id="dmg"):
    return {"op": "draw", "player": "p1", "count": 1, "effect_id": "then", "predicate": {"kind": kind, "effect_id": effect_id}}


def main() -> int:
    errors: list[str] = []
    state = base_state()
    deal = {"op": "deal_damage", "object_id": "u2", "amount": 3, "effect_id": "dmg"}

    def outcome(result, idx):
        return result["trace"][idx].get("outcome") if result.get("committed") else f"uncommitted:{result.get('reason') or result.get('errors')}"

    # --- action_performed / action_not_performed -----------------------------------------
    plain = apply_program(state, program("a", deal, gated_draw("action_performed")))
    if outcome(plain, 1) != "applied":
        errors.append(f"action_performed after an applied deal did not let the draw through: {outcome(plain, 1)}")
    prevented = copy.deepcopy(state)
    prevented["replacement_effects"] = [{"replacement_id": "ward", "controller": "p2", "source_object": "u2", "mode": "prevent_event", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "target_object_id": "u2"}]
    p1 = apply_program(prevented, program("b", deal, gated_draw("action_performed")))
    if outcome(p1, 0) != "replaced_prevented" or outcome(p1, 1) != "skipped_linked_dependency":
        errors.append(f"a wholly prevented deal still counted as performed: {outcome(p1, 0)} / {outcome(p1, 1)}")
    p2 = apply_program(prevented, program("b2", deal, gated_draw("action_not_performed")))
    if outcome(p2, 1) != "applied":
        errors.append("action_not_performed did not fire after a prevented deal")
    reduced = copy.deepcopy(state)
    reduced["replacement_effects"] = [{"replacement_id": "shield", "controller": "p2", "source_object": "u2", "mode": "reduce_damage", "event_op": "deal_damage", "optional": False, "uses_remaining": None, "prevent_remaining": 1, "target_object_id": "u2"}]
    r1 = apply_program(reduced, program("c", deal, gated_draw("action_performed")))
    if outcome(r1, 0) != "replaced_modified_applied" or outcome(r1, 1) != "applied":
        errors.append(f"a partly prevented deal did not count as performed (359.3.e.14.c): {outcome(r1, 0)} / {outcome(r1, 1)}")
    noop = apply_program(state, program("d", {"op": "heal_damage", "object_id": "u2", "amount": 1, "effect_id": "dmg"}, gated_draw("action_performed")))
    if outcome(noop, 0) != "no_op" or outcome(noop, 1) != "skipped_linked_dependency":
        errors.append(f"a no-op counted as performed: {outcome(noop, 0)} / {outcome(noop, 1)}")
    ev = plain["trace"][1] if plain.get("committed") else {}
    if "Core 205" not in (p1["trace"][1].get("rule_locators", []) if p1.get("committed") else []):
        errors.append("skipped action predicate did not cite Core 205 / 359.3.e.14")

    # --- requested_count_not_reached -----------------------------------------------------------
    short = apply_program(state, program("e", {"op": "channel_rune", "player": "p1", "count": 2, "effect_id": "dmg"}, gated_draw("requested_count_not_reached")))
    if outcome(short, 0) != "applied" or short["trace"][0].get("completion") != "partial" or outcome(short, 1) != "applied":
        errors.append(f"Mobilize's 'If you couldn't' did not fire on a partial channel: {outcome(short, 0)} / {outcome(short, 1)}")
    full = apply_program(state, program("f", {"op": "channel_rune", "player": "p1", "count": 1, "effect_id": "dmg"}, gated_draw("requested_count_not_reached")))
    if outcome(full, 1) != "skipped_linked_dependency":
        errors.append("requested_count_not_reached fired on a full channel")
    subset = apply_program(state, program("g", {"op": "deal_damage", "amount": 1, "effect_id": "dmg", "targets": {"min": 1, "max": 2, "selectors": [
        {"object_id": "u2", "chosen_zone_class": "board", "controller_relation": "enemy"}, {"object_id": "u1", "chosen_zone_class": "board", "controller_relation": "enemy"}]}}, gated_draw("requested_count_not_reached")))
    if outcome(subset, 1) != "applied":
        errors.append(f"a multi-target subset did not satisfy requested_count_not_reached: {outcome(subset, 0)} / {outcome(subset, 1)}")

    # --- invalid / unsupported ---------------------------------------------------------------------
    if not any("earlier instruction" in e for e in validate_program(program("h", deal, gated_draw("action_performed", "nope")))):
        errors.append("an unknown predicate effect_id was accepted")
    if not any("earlier instruction" in e for e in validate_program(program("i", gated_draw("action_performed"), deal))):
        errors.append("a forward predicate reference was accepted")
    malformed_count = validate_program(program("j0", deal, gated_draw("requested_count_not_reached")))
    if not any("count contract" in e for e in malformed_count):
        errors.append("requested_count_not_reached on a single-target deal was not invalid_input")
    ck = apply_program(state, program("j", deal, gated_draw("caused_kill")))
    if ck.get("committed") or ck.get("unsupported") is not True:
        errors.append("caused_kill as an effect predicate was not unsupported")
    if any("conditional" in e for e in validate_program({**program("k", deal), "conditional_triggers": []})):
        errors.append("an empty conditional_triggers list was rejected")
    if not any("not an instruction" in e for e in validate_program({**program("l", deal), "conditional_triggers": [{"trigger_id": "t", "controller": "p1", "source_object": "spell-1", "controller_order": 0, "effect_program_id": "x", "optional_at_finalize": False, "condition": {"kind": "caused_kill", "effect_id": "nope"}}]})):
        errors.append("a conditional trigger on an unknown instruction was accepted")

    # --- conditional reflexive trigger through the bridge -----------------------------------------
    timing = fixture(priority="p2", items=[item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    lethal = copy.deepcopy(state); lethal["objects"]["u2"]["damage"] = 1  # 1 + 3 = 4 = might
    trigger = {"trigger_id": "disintegrate-draw", "controller": "p1", "source_object": "spell-1", "controller_order": 0,
               "effect_program_id": "disintegrate-draw-effects", "optional_at_finalize": False, "condition": {"kind": "caused_kill", "effect_id": "dmg"}}
    disintegrate = {**program("spell-1-effects", deal), "source_object": "spell-1", "conditional_triggers": [trigger]}
    snap_t, snap_e = copy.deepcopy(timing), copy.deepcopy(lethal)
    res = resolve_with_program(timing, "spell-1", lethal, disintegrate)
    items = res.get("next_timing_state", {}).get("chain", {}).get("items", [])
    ct = (res.get("trace", {}).get("conditional_triggers") or [{}])[0]
    if not res.get("committed") or [i["id"] for i in items] != ["disintegrate-draw"] or items[0].get("trigger_kind") != "reflexive" or items[0].get("status") != "pending":
        errors.append(f"'If this kills it' did not build a Pending reflexive item after Cleanup: {res.get('stage')} {res.get('reason')} {[i.get('id') for i in items]}")
    if ct.get("held") is not True or ct.get("killed_objects") != ["u2"] or ct.get("attributed_to") != "spell-1" or "Core 428.5.c" not in ct.get("rule_locators", []):
        errors.append(f"conditional trigger trace lacks attribution: {ct}")
    if res.get("committed") and "u2" not in res["next_effect_state"]["players"]["p2"]["zones"]["trash"]:
        errors.append("Cleanup did not kill the damaged unit")
    if timing != snap_t or lethal != snap_e or resolve_with_program(timing, "spell-1", lethal, disintegrate) != res:
        errors.append("bridge with conditional triggers mutated inputs or is not deterministic")
    guarded = copy.deepcopy(lethal)
    guarded["replacement_effects"] = [{"replacement_id": "guard", "controller": "p2", "source_object": "u2", "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"}]
    saved = resolve_with_program(timing, "spell-1", guarded, disintegrate)
    sct = (saved.get("trace", {}).get("conditional_triggers") or [{}])[0]
    if not saved.get("committed") or saved["next_timing_state"]["chain"]["items"] or sct.get("held") is not False or sct.get("prevented_objects") != ["u2"]:
        errors.append(f"a prevented death still built the trigger: {saved.get('reason')} {saved.get('next_timing_state', {}).get('chain', {}).get('items')} {sct}")
    nonlethal = resolve_with_program(timing, "spell-1", state, disintegrate)
    if not nonlethal.get("committed") or nonlethal["next_timing_state"]["chain"]["items"]:
        errors.append("non-lethal damage built the trigger")
    warded = copy.deepcopy(lethal); warded["replacement_effects"] = prevented["replacement_effects"]
    no_deal = resolve_with_program(timing, "spell-1", warded, disintegrate)
    nct = (no_deal.get("trace", {}).get("conditional_triggers") or [{}])[0]
    if not no_deal.get("committed") or no_deal["next_timing_state"]["chain"]["items"] or nct.get("action_performed") is not False:
        errors.append("a prevented deal built the trigger")
    # same Cleanup kill → death trigger and caused-kill trigger in one batch, Turn Player (p1) first (383.3.d)
    with_death = copy.deepcopy(lethal)
    with_death["objects"]["u2"]["death_triggers"] = [{"trigger_id": "u2-deathknell", "controller": "p2", "source_object": "u2", "controller_order": 0, "effect_program_id": "u2-deathknell-effects", "optional_at_finalize": False}]
    both = resolve_with_program(timing, "spell-1", with_death, disintegrate)
    both_items = both.get("next_timing_state", {}).get("chain", {}).get("items", [])
    if not both.get("committed") or [i["id"] for i in both_items] != ["disintegrate-draw", "u2-deathknell"]:
        errors.append(f"death trigger and caused-kill trigger were not scheduled as one batch in Turn Order: {both.get('reason')} {[i.get('id') for i in both_items]}")
    elif len({i.get("batch_id") for i in both_items}) != 1 or len({i.get("batch_sequence") for i in both_items}) != 1:
        errors.append(f"simultaneous triggers carry different batches: {[(i.get('batch_id'), i.get('batch_sequence')) for i in both_items]}")
    kill_prog = {**program("spell-1-effects", {"op": "kill", "object_id": "u2", "effect_id": "dmg"}), "source_object": "spell-1", "conditional_triggers": [trigger]}
    direct = resolve_with_program(timing, "spell-1", state, kill_prog)
    dct = (direct.get("trace", {}).get("conditional_triggers") or [{}])[0]
    if not direct.get("committed") or [i["id"] for i in direct["next_timing_state"]["chain"]["items"]] != ["disintegrate-draw"] or "Core 428.5.b" not in dct.get("rule_locators", []):
        errors.append(f"a Kill instruction did not attribute directly (428.5.b): {dct}")
    kill_guarded = copy.deepcopy(state); kill_guarded["replacement_effects"] = guarded["replacement_effects"]
    if resolve_with_program(timing, "spell-1", kill_guarded, kill_prog).get("next_timing_state", {}).get("chain", {}).get("items"):
        errors.append("a prevented Kill instruction still built the trigger")
    check = build_engine_check("resolution", res, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(lethal), "effect_program": "sha256:" + "2" * 64})
    if check["outcome"] != "supported" or "Core 428.5.c" not in check["rule_locators"]:
        errors.append(f"engine-check did not wrap the conditional resolution: {check['outcome']}")

    if errors:
        print("FAILED: linked predicate checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print("OK: action predicates read the earlier instruction's event (partly prevented is performed, wholly prevented or replaced is not, a no-op is not), requested_count_not_reached fires on a short Channel or a target subset, unknown or forward references are invalid_input, caused_kill is not an in-program predicate, and 'If this kills it' becomes a Pending reflexive item only after Cleanup kills the object with 428.5.c attribution — never when a replacement prevented the death.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
