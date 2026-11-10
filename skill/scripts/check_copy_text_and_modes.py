#!/usr/bin/env python3
"""Regression gate (set 2 package A3: Svellsongur and Aphelios - Exalted).

Svellsongur ("As this is attached to a unit, copy that unit's text to this Equipment's effect text for as long as this is
attached to it."): its Effect Text is a copy of its Top-Most card's printed text (Core 479.1.b, 479.1.b.1, 479.1.d; the
official Spiritforged FAQ of 2026-01-14 and the Unleashed and Radiance patch notes: printed text only, nothing appended or
granted), appended back to that card (479.3.c) - each printed ability there twice, each working on its own. The copied
text is not there when the attach that makes it executes (official Vendetta FAQ, 2026-08-14).

  C1 copied        u1 prints [Assault 2] and a conquer trigger: attached, it has Assault 4 (2 printed + 2 copied) and two
                   conquer triggers, the second its own instance (its own trigger id); its Might is not copied
  C2 not granted   a granted [Assault 3] and another Equipment's appended trigger are not copied: Assault 7, not 10; the
                   other Equipment's trigger once
  C3 attach event  u1's "When you attach an Equipment to me" watch: the attach of Svellsongur wakes the printed one only;
                   a later attach of another Equipment wakes both instances
  C4 detached      detached, the copy is gone: one conquer trigger of u1's own, Assault 5 (2 + the granted 3)
  C5 three         three copies of the text give four instances of each printed ability, not eight
  C6 activated     u1 prints an activated ability costing its own exhaust: the copy is a second ability with its own
                   id, usable on its own; using either exhausts u1, so the other cannot be paid; detached, one again
  C7 aura          u1 prints a static aura (+1 Might to other friendly units here): u3 gets +2 with the copy (each
                   instance applies, Core 479.3.c); detached, +1 and the copied row gone
  C8 cond. Might   u1 prints +4 Might while a condition holds: +8 with the copy, +0 when it does not hold
  C9 refused       text no unit prints (a combat tie replacement) on the Top-Most card: refused by name
  C10 doubled      Gearhead's "double its base Might bonus" on the Top-Most card: refused by name (two doublings of the
                   base, Core 433.1, are not settled)
  C11 second set   Heimerdinger's borrowed [Exhaust] abilities: refused by name (a second set of ability identities
                   with their own uses is not modelled)
                   (copy_text_unmodelled), never half-copied
  V  validation    effect_text_copy of another value, or beside an effect_text of its own, does not validate
  G  grammar       the printed sentence lowers to effect_text_copy top_most_printed_text; its near misses do not

Aphelios - Exalted ("When you attach an Equipment to me, choose one that hasn't been chosen this turn - Ready 2 runes.
Channel 1 rune exhausted. Buff a friendly unit."): a modal triggered ability, its mode chosen as it is finalized
(Core 403.2), among the modes this INSTANCE has not chosen this turn (official Spiritforged FAQ: each instance tracks
its own); a mode whose choices cannot be made is not a legal choice, and with no mode left it leaves the Chain (403.4).
"Ready 2 runes" is exactly two runes on the board, any player's (355.9.a.1, 355.10, 355.13 - not "up to").

  A1 two runes     p1's exhausted rune and p2's exhausted rune: the ready mode chooses both; resolved, both are ready
  A2 one rune      only one rune on the board: the ready mode is not offered (403.2, 403.4.b), the other two are
  A3 instances     after the printed instance chose ready, the copied instance (Svellsongur) may still choose it; the
                   printed one may not
  A4 none left     every mode chosen this turn by that instance: it leaves the Chain (403.4)
  A5 refreshed     a Svellsongur detached and attached again (Vendetta FAQ): its copy is a new instance - a new id
                   (:copy:<card>:<lifecycle>), every mode offered again though the old copy chose ready
  A6 others kept   the printed instance's record and another Svellsongur's copy's record survive the re-attach
  A7 old on Chain  the old copy, still waiting on the Chain, reads its own record, never the new copy's; the new
                   copy's choice is its own
  A8 uses          a copied 'Use only once per turn' ability counts its own uses, this lifecycle's only: used once
                   it is refused, the printed one still usable, the next attach's copy usable again

    python skill/scripts/check_copy_text_and_modes.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_effect_ir import base_state, program, settle_contested  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, effective_might,  # noqa: E402
                       hash_value, keyword_values, object_identity, object_triggers, validate_state)
from play_transaction import modes_chosen_this_turn, record_mode_chosen  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import pass_priority, schedule_triggered_items  # noqa: E402
import watchers as W  # noqa: E402

ERRORS: list[str] = []


def fail(label: str, why: object) -> None:
    ERRORS.append(f"{label}: {why}")


def trigger(trigger_id, source, controller="p1", **extra):
    return {"trigger_id": trigger_id, "controller": controller, "source_object": source, "controller_order": 0,
            "effect_program_id": f"{trigger_id}-effects", "optional_at_finalize": False, **extra}


ATTACH_WATCH = {"kinds": ["attached"], "scope": "actor", "filter": {"attached_to_source": True, "object_tagged": "Equipment"}}


def gear(gear_id, **fields):
    return {"owner": "p1", "controller": "p1", "kind": "gear", "base_might": 0, "might_modifiers": [], "damage": 0,
            "exhausted": False, "tags": ["Equipment"], "might_bonus": 0, **fields}


def scene(*, activated=False):
    """u1 (p1) at bf1 printing [Assault 2], a conquer trigger and an attach watch; Svellsongur copies sv, sv2, sv3, an
    Equipment ge whose Effect Text carries a conquer trigger, and a plain Equipment g3, all in p1's Base."""
    state = base_state()
    state["players"]["p1"]["zones"]["base"].remove("u1")
    state["battlefields"]["bf1"]["objects"].append("u1")
    u1 = state["objects"]["u1"]
    u1.update({"keywords": ["assault"], "assault_value": 2, "conquer_triggers": [trigger("u1-conq", "u1")],
               "event_triggers": [trigger("u1-attach", "u1", watch=copy.deepcopy(ATTACH_WATCH))]})
    if activated:
        u1["activated_abilities"] = {"u1-act": {"cost": {"energy": 1, "power": {}, "exhaust": True},
                                                "effect_program_id": "u1-act-fx#u1-act"}}
    for sv in ("sv", "sv2", "sv3"):
        state["objects"][sv] = gear(sv, effect_text_copy="top_most_printed_text")
    state["objects"]["ge"] = gear("ge", effect_text={"triggers": {"conquer_triggers": [trigger("ge-text", "ge")]}})
    state["objects"]["g3"] = gear("g3")
    state["players"]["p1"]["zones"]["base"] += ["sv", "sv2", "sv3", "ge", "g3"]
    return settle_contested(state)


def attach(state, gear_id, host="u1"):
    return apply_program(state, program("eq", {"op": "attach", "effect_id": "a", "object_id": gear_id, "to": host}))


def attached(state, gear_id, host="u1"):
    result = attach(state, gear_id, host)
    if not result.get("committed"):
        raise SystemExit(f"attach {gear_id} -> {host} failed: {result.get('reason_code')} {result.get('reason')}")
    return result["next_state"]


def grant_assault(state, amount):
    """A granted [Assault N] on u1 (Cleave-shaped), not printed."""
    state = copy.deepcopy(state)
    state.setdefault("continuous_effects", []).append({
        "effect_id": "cleave", "kind": "keyword_grant", "source": {"object": "u1", "identity": object_identity(state, "u1"),
                                                                    "name": "cleave"},
        "affects": {"scope": "object", "object": "u1", "identity": object_identity(state, "u1")}, "layer": "ability",
        "timestamp": 1000, "value": {"keyword": "assault", "value": amount}, "duration": {"kind": "permanent"},
        "passive": False})
    return state


def conquer_ids(state, host="u1"):
    return sorted(d["trigger_id"] for d in object_triggers(state, host, "conquer_triggers"))


def assault(state, host="u1"):
    return keyword_values(state, host).get("assault")


def woken(state, gear_id, host="u1", label="b"):
    event = {"event_id": f"attach:{gear_id}", "kind": "attached", "object": gear_id, "to": host, "actor": "p1",
             "controller": "p1", "player": "p1", "action_id": f"attach:{gear_id}"}
    found, _ = W.schedule_live(state, [event], turn_id=state.get("turn_id", "turn-0"), batch_label=label)
    return sorted(d["trigger_id"].split("@", 1)[0] for d in found)


SVELLSONGUR = ("As this is attached to a unit, copy that unit's text to this Equipment's effect text for as long as this is "
               "attached to it.")


def grammar() -> None:
    """G: the printed sentence lowers to effect_text_copy; its near misses do not parse."""
    import clause_grammar as CG
    got = CG.compile_clause(SVELLSONGUR)
    if got.get("production_id") != "as_this_is_attached_copy_that_units_text_to_its_effect_text" \
            or ((got.get("passive") or {}).get("object_fields") or {}) != {"effect_text_copy": "top_most_printed_text"}:
        fail("G grammar", f"{got.get('production_id')} {got.get('passive')}")
    for near in ("As this is attached to a unit, copy that unit's Might to this Equipment.",
                 "Copy that unit's text to this Equipment's effect text."):
        if CG.compile_clause(near).get("production_id") == "as_this_is_attached_copy_that_units_text_to_its_effect_text":
            fail("G grammar", f"{near!r} lowered as the copy")


def svellsongur() -> None:
    grammar()
    s = scene()
    if validate_state(s):
        fail("scene", validate_state(s)[:2])
        return
    might_before = effective_might(s, "u1")
    on = attached(s, "sv")
    if validate_state(on):
        fail("C1 copied", f"state invalid: {validate_state(on)[:2]}")
    if conquer_ids(on) != ["u1-conq", "u1-conq:copy:sv:1"] or assault(on) != 4 or effective_might(on, "u1") != might_before:
        fail("C1 copied", f"{conquer_ids(on)} assault {assault(on)} might {effective_might(on, 'u1')} (was {might_before})")
    granted = attached(attached(grant_assault(s, 3), "ge"), "sv")
    if assault(granted) != 7 or conquer_ids(granted) != ["ge-text", "u1-conq", "u1-conq:copy:sv:1"]:
        fail("C2 not granted", f"assault {assault(granted)} conquer {conquer_ids(granted)}")
    if woken(on, "sv") != ["u1-attach"]:
        fail("C3 attach event", f"the attach of the copying card woke {woken(on, 'sv')}")
    later = attached(on, "g3")
    if woken(later, "g3") != ["u1-attach", "u1-attach:copy:sv:1"]:
        fail("C3 attach event", f"a later attach woke {woken(later, 'g3')}")
    off = apply_program(granted, program("eq", {"op": "detach", "effect_id": "d", "object_id": "sv"}))
    after = off.get("next_state") or {}
    if not off.get("committed") or conquer_ids(after) != ["ge-text", "u1-conq"] or assault(after) != 5:
        fail("C4 detached", f"{off.get('reason')} {conquer_ids(after) if after else None} assault {assault(after) if after else None}")
    three = attached(attached(attached(s, "sv"), "sv2"), "sv3")
    if conquer_ids(three) != ["u1-conq", "u1-conq:copy:sv2:1", "u1-conq:copy:sv3:1", "u1-conq:copy:sv:1"] or assault(three) != 8:
        fail("C5 three", f"{conquer_ids(three)} assault {assault(three)}")
    activated()
    passives()
    odd = scene()
    odd["objects"]["u1"]["combat_tie_replacement"] = {"mode": "recall_all_units", "when": "controller_is_attacker"}
    refused = attach(odd, "sv")
    if refused.get("committed") or "copy_text_unmodelled" not in str(refused.get("reason") or refused.get("errors") or ""):
        fail("C9 refused", f"{refused.get('committed')} {refused.get('reason_code')} {refused.get('reason')}")
    # C10 / C11 (GPT's A3 review): a second instance no rule or model settles is refused by name, never kept single -
    # Gearhead's "double its base Might bonus" twice (Core 433.1), Heimerdinger's borrowed abilities as a second set
    for label, field, value in (("C10 doubled twice", "equipment_bonus_multiplier", 2),
                                ("C11 a second set", "has_exhaust_abilities_of", ["legend", "unit", "gear"])):
        host = scene()
        host["objects"]["u1"][field] = value
        refused = attach(host, "sv")
        if refused.get("committed") or "copy_text_unmodelled" not in str(refused.get("reason") or refused.get("errors") or ""):
            fail(label, f"{refused.get('committed')} {refused.get('reason_code')} {refused.get('reason')}")
    for label, fields in (("another value", {"effect_text_copy": "everything"}),
                          ("beside its own", {"effect_text_copy": "top_most_printed_text",
                                              "effect_text": {"keywords": [{"keyword": "tank"}]}})):
        bad = copy.deepcopy(s)
        bad["objects"]["sv"].update(fields)
        if not validate_state(bad):
            fail("V", f"effect_text_copy {label} validated")


def use(state, ability_id):
    """Really activate u1's ability `ability_id` (its cost: exhaust u1), its body drawing 1 (play_card, Core 377.3)."""
    from play_transaction import DECLARATION_VERSION, EXHAUST_SELF_COST_ID, play_card
    decl = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": f"use-{ability_id}", "actor": "p1", "card": "u1",
            "chain_item": {"id": f"ability-{ability_id}", "object_kind": "ability", "timing": "default"},
            "activation": {"source_object": "u1", "ability_id": ability_id},
            "cost": {"base": {"energy": 0, "power": {}},
                     "additional": [{"cost_id": EXHAUST_SELF_COST_ID, "mandatory": True,
                                     "payment": {"kind": "exhaust", "object_id": "u1"}}]},
            "effect_program_id": "u1-act-fx"}
    body = program("u1-act-fx", {"op": "draw", "effect_id": "dr", "player": "p1", "count": 1})
    body["controller"] = "p1"
    body["source_object"] = "u1"
    return play_card(fixture(), state, decl, effect_program=body)


def activated() -> None:
    """C6: u1 prints an activated ability whose cost exhausts it; the copy is a second instance with its own id - each
    usable on its own, the one cost blocking the other (an exhausted unit cannot pay it again)."""
    s = scene(activated=True)
    on = attached(s, "sv")
    rows = sorted((on["objects"]["u1"].get("activated_abilities") or {}))
    if rows != ["u1-act", "u1-act:copy:sv:1"]:
        fail("C6 activated", f"abilities {rows}")
        return
    copy_first = use(on, "u1-act:copy:sv:1")
    if not copy_first.get("committed"):
        fail("C6 activated", f"the copy could not be used: {copy_first.get('reason_code')} {copy_first.get('reason')}")
        return
    blocked = use(copy_first["next_effect_state"], "u1-act")
    if blocked.get("committed"):
        fail("C6 activated", "the printed ability was used again with u1 already exhausted by the copy's cost")
    printed_first = use(on, "u1-act")
    if not printed_first.get("committed") or use(printed_first["next_effect_state"], "u1-act:copy:sv:1").get("committed"):
        fail("C6 activated", "the printed one was refused, or the copy was used with u1 exhausted")
    off = apply_program(on, program("eq", {"op": "detach", "effect_id": "d", "object_id": "sv"}))
    if sorted((off["next_state"]["objects"]["u1"].get("activated_abilities") or {})) != ["u1-act"]:
        fail("C6 activated", f"detached, abilities {sorted(off['next_state']['objects']['u1'].get('activated_abilities') or {})}")


def passives() -> None:
    """C7: u1 prints a static aura (+1 Might to other friendly units here): with the copy u3 has +2 - two instances, each
    applying (Core 479.3.c). C8: u1 prints a conditional Might (+4 while the condition holds): +8 with the copy, +0 when
    it does not hold; detached, back to one instance."""
    s = scene()
    s["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["battlefields"]["bf1"]["objects"].append("u3")
    s["objects"]["u1"]["static_auras"] = [{"aura_id": "here", "amount": 1, "criteria": {
        "kind": "unit", "controller_relation": "friendly", "exclude_source": True, "at_source_battlefield": True}}]
    s["objects"]["u1"]["conditional_might"] = [{"modifier_id": "clause", "amount": 4,
                                                "condition": {"kind": "runes_at_least", "count": 0}}]
    if validate_state(s):
        fail("C7 aura", f"scene invalid: {validate_state(s)[:2]}")
        return
    u3_before, u1_before = effective_might(s, "u3"), effective_might(s, "u1")
    on = attached(s, "sv")
    if validate_state(on):
        fail("C7 aura", f"invalid with the copy: {validate_state(on)[:2]}")
    if effective_might(on, "u3") != u3_before + 1:
        fail("C7 aura", f"u3 {effective_might(on, 'u3')} (was {u3_before}): the copied aura did not apply once more")
    if effective_might(on, "u1") != u1_before + 4:
        fail("C8 conditional Might", f"u1 {effective_might(on, 'u1')} (was {u1_before})")
    unmet = copy.deepcopy(on)
    for row in unmet["objects"]["u1"]["conditional_might"]:
        row["condition"] = {"kind": "runes_at_least", "count": 99}
    if effective_might(unmet, "u1") != s["objects"]["u1"]["base_might"]:
        fail("C8 conditional Might", f"with the condition unmet u1 {effective_might(unmet, 'u1')}")
    off = apply_program(on, program("eq", {"op": "detach", "effect_id": "d", "object_id": "sv"}))["next_state"]
    if effective_might(off, "u3") != u3_before or effective_might(off, "u1") != u1_before \
            or off["objects"]["u1"].get("copied_text") or len(off["objects"]["u1"]["static_auras"]) != 1:
        fail("C7 aura", f"detached: u3 {effective_might(off, 'u3')} u1 {effective_might(off, 'u1')} "
                        f"auras {len(off['objects']['u1']['static_auras'])}")


RUNE = {"kind": "rune", "might_modifiers": [], "damage": 0, "exhausted": True, "base_might": 0}
MODES = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
         "program_id": "ap-fx", "controller": "p1", "source_object": "ap",
         "modal": {"choose": 1, "timing": "trigger_finalization", "decision_ref": "mode", "not_chosen_this_turn": True,
                   "options": [
                       {"option_id": "ready", "effects": [{"op": "ready", "effect_id": "rd", "targets": {
                           "min": 2, "max": 2, "decision_ref": "t",
                           "restrictions": {"kind": "rune", "chosen_zone_class": "board"}}}]},
                       {"option_id": "channel", "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]},
                       {"option_id": "buff", "effects": [{"op": "buff", "effect_id": "bf", "target": {
                           "decision_ref": "b", "chosen_zone_class": "board", "kind": "unit",
                           "controller_relation": "friendly"}}]}]}}
REGISTRY = {"ap-fx": MODES}


def aphelios_board(runes=(("rn1", "p1"), ("rn2", "p2"))):
    s = base_state()
    s["objects"]["ap"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    s["players"]["p1"]["zones"]["base"].append("ap")
    for rune, owner in runes:
        s["objects"][rune] = {**RUNE, "owner": owner, "controller": owner}
        s["players"][owner]["zones"]["base"].append(rune)
    return s


def pending(state, trigger_id):
    descriptor = {"trigger_id": trigger_id, "controller": "p1", "source_object": "ap", "controller_order": 0,
                  "effect_program_id": "ap-fx", "optional_at_finalize": False, "trigger_kind": "triggered",
                  "batch_sequence": 0, "batch_id": f"attach:{trigger_id}", "source_identity": object_identity(state, "ap")}
    return schedule_triggered_items(fixture(), [descriptor])["next_state"]


def envelope(state, mode, targets=None):
    out = [{"decision_id": "mode", "stage": "trigger_finalization", "kind": "mode_selection", "controller": "p1",
            "value": mode}]
    if targets:
        out.append({"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1",
                    "value": list(targets), "selection_identities": {t: object_identity(state, t) for t in targets}})
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": out}


def copy_ids(state, host="ap"):
    return sorted(d["trigger_id"] for d in object_triggers(state, host, "event_triggers") if ":copy:" in d["trigger_id"])


def lifecycle() -> None:
    """A5-A8 (Vendetta FAQ, 2026-08-14: detached and attached again, the copied abilities are new instances): each attach
    of a copying card is a lifecycle of its own - its copies keep no record of an earlier one, and no other instance's
    record is touched."""
    s = aphelios_board()
    s["objects"]["ap"]["event_triggers"] = [trigger("ap-attach", "ap", watch=copy.deepcopy(ATTACH_WATCH))]
    for sv in ("sv", "sv2"):
        s["objects"][sv] = gear(sv, effect_text_copy="top_most_printed_text")
        s["players"]["p1"]["zones"]["base"].append(sv)
    on = attached(attached(s, "sv", "ap"), "sv2", "ap")
    if copy_ids(on) != ["ap-attach:copy:sv2:1", "ap-attach:copy:sv:1"]:
        fail("A5 refreshed", f"copies on the first attach {copy_ids(on)}")
        return
    record_mode_chosen(on, "ap", "p1", "buff")                                         # the printed instance's record
    record_mode_chosen(on, "ap", "p1", "channel", "ap-attach:copy:sv2:1")              # the other copy's record
    old = pending(on, "ap-attach:copy:sv:1")                                           # the old copy, on the Chain
    used = finalize_trigger(old, on, REGISTRY, envelope(on, "ready", ["rn1", "rn2"]))
    if not used.get("committed"):
        fail("A5 refreshed", f"the first copy did not choose ready: {used.get('reason')}")
        return
    off = apply_program(used["next_effect_state"], program("d", {"op": "detach", "effect_id": "d", "object_id": "sv"}))
    again = attached(off["next_state"], "sv", "ap")
    # A5: the new attach is a new instance - a new id, every mode offered again
    asked = finalize_trigger(pending(again, "ap-attach:copy:sv:2"), again, REGISTRY, None)
    if "ap-attach:copy:sv:2" not in copy_ids(again) or "ap-attach:copy:sv:1" in copy_ids(again) \
            or asked.get("mode_options") != ["ready", "channel", "buff"]:
        fail("A5 refreshed", f"{copy_ids(again)} options {asked.get('mode_options')}")
    # A6: the printed instance's record and the other copy's are kept
    if modes_chosen_this_turn(again, "ap", "p1") != ["buff"] \
            or modes_chosen_this_turn(again, "ap", "p1", "ap-attach:copy:sv2:1") != ["channel"] \
            or modes_chosen_this_turn(again, "ap", "p1", "ap-attach:copy:sv:1") != ["ready"]:
        fail("A6 others kept", f"printed {modes_chosen_this_turn(again, 'ap', 'p1')} sv2 "
                               f"{modes_chosen_this_turn(again, 'ap', 'p1', 'ap-attach:copy:sv2:1')}")
    # A7: the new copy's choice is its own - the old copy's record (an item already on the Chain) is not the new one's,
    # and the new one's choice does not appear under the old
    took = finalize_trigger(pending(again, "ap-attach:copy:sv:2"), again, REGISTRY, envelope(again, "ready", ["rn1", "rn2"]))
    after = took.get("next_effect_state") or {}
    if not took.get("committed") or modes_chosen_this_turn(after, "ap", "p1", "ap-attach:copy:sv:2") != ["ready"] \
            or modes_chosen_this_turn(after, "ap", "p1", "ap-attach:copy:sv:1") != ["ready"]:
        fail("A7 old on the Chain", f"{took.get('reason')} new "
                                   f"{modes_chosen_this_turn(after, 'ap', 'p1', 'ap-attach:copy:sv:2') if after else None}")
    old_left = finalize_trigger(pending(again, "ap-attach:copy:sv:1"), again, REGISTRY, None)
    if old_left.get("mode_options") != ["channel", "buff"]:
        fail("A7 old on the Chain", f"the old copy's own record not read: {old_left.get('mode_options')}")
    # A8: a copied ability with "Use only once per turn" counts its own uses, this lifecycle's only
    u = scene(activated=True)
    u["objects"]["u1"]["ability_conditions"] = {"u1-act": {"kind": "ability_uses_this_turn_below", "ability": "u1-act",
                                                           "count": 1}}
    first = attached(u, "sv")
    gate = (first["objects"]["u1"].get("ability_conditions") or {}).get("u1-act:copy:sv:1") or {}
    once = use(first, "u1-act:copy:sv:1")
    st = once.get("next_effect_state") or first
    st = copy.deepcopy(st)
    st["objects"]["u1"]["exhausted"] = False
    twice = use(st, "u1-act:copy:sv:1")
    printed = use(st, "u1-act")
    off = apply_program(st, program("d", {"op": "detach", "effect_id": "d", "object_id": "sv"}))
    back = copy.deepcopy(attached(off["next_state"], "sv"))
    back["objects"]["u1"]["exhausted"] = False
    renewed = use(back, "u1-act:copy:sv:2")
    if gate.get("ability") != "u1-act:copy:sv:1" or not once.get("committed") or twice.get("committed") \
            or not printed.get("committed") or not renewed.get("committed"):
        fail("A8 uses per lifecycle", f"gate {gate} once {once.get('reason_code')} twice {twice.get('committed')} "
                                      f"printed {printed.get('reason_code')} renewed {renewed.get('reason_code')}")


def aphelios() -> None:
    s = aphelios_board()
    if validate_state(s):
        fail("aphelios board", validate_state(s)[:2])
        return
    fin = finalize_trigger(pending(s, "ap-attach"), s, REGISTRY, envelope(s, "ready", ["rn1", "rn2"]))
    if not fin.get("committed"):
        fail("A1 two runes", f"finalize {fin.get('reason')} {fin.get('message')}")
    else:
        t, e = fin["next_timing_state"], fin["next_effect_state"]
        for actor in ("p1", "p2"):
            t = (pass_priority(t, actor) or {}).get("next_state") or t
        done = resolve_with_program(t, "ap-attach", e, MODES)
        after = done.get("next_effect_state") or {}
        if not done.get("committed") or after["objects"]["rn1"].get("exhausted") or after["objects"]["rn2"].get("exhausted"):
            fail("A1 two runes", f"{done.get('reason')} r1 {after.get('objects', {}).get('r1', {}).get('exhausted')} "
                                 f"r2 {after.get('objects', {}).get('r2', {}).get('exhausted')}")
    one = aphelios_board(runes=(("rn1", "p1"),))
    asked = finalize_trigger(pending(one, "ap-attach"), one, REGISTRY, None)
    if asked.get("reason") != "mode_selection_required" or asked.get("mode_options") != ["channel", "buff"]:
        fail("A2 one rune", f"{asked.get('reason')} {asked.get('mode_options')}")
    used = copy.deepcopy(s)
    record_mode_chosen(used, "ap", "p1", "ready")
    printed = finalize_trigger(pending(used, "ap-attach"), used, REGISTRY, None)
    copied = finalize_trigger(pending(used, "ap-attach:copy:sv:1"), used, REGISTRY, None)
    if printed.get("mode_options") != ["channel", "buff"] or copied.get("mode_options") != ["ready", "channel", "buff"]:
        fail("A3 instances", f"printed {printed.get('mode_options')} copied {copied.get('mode_options')}")
    took = finalize_trigger(pending(used, "ap-attach:copy:sv:1"), used, REGISTRY, envelope(used, "ready", ["rn1", "rn2"]))
    if not took.get("committed") or modes_chosen_this_turn(took["next_effect_state"], "ap", "p1", "ap-attach:copy:sv:1") \
            != ["ready"] or modes_chosen_this_turn(took["next_effect_state"], "ap", "p1") != ["ready"]:
        fail("A3 instances", f"the copy's choice was not kept apart: {took.get('reason')}")
    lifecycle()
    spent = copy.deepcopy(s)
    for mode in ("ready", "channel", "buff"):
        record_mode_chosen(spent, "ap", "p1", mode)
    gone = finalize_trigger(pending(spent, "ap-attach"), spent, REGISTRY, None)
    if not gone.get("removed") or (gone.get("transition") or {}).get("type") != "no_legal_choices":
        fail("A4 none left", f"{gone.get('reason')} {gone.get('transition')}")


def main() -> int:
    svellsongur()
    aphelios()
    if ERRORS:
        print("copy-text-and-modes checks FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("copy-text-and-modes checks passed: Svellsongur copies its Top-Most card's printed text only - triggers and "
          "keywords, not Might, nothing granted or appended - each printed ability there once more, not on the attach "
          "that made it, gone when detached, three copies four instances, its activated abilities, auras and conditional Might twice, text no unit prints and two unsettled doublings refused by name, lowered (C1-C11, V, G); "
          "Aphelios's modes per instance, a mode without its choices not offered, exactly two runes of any player "
          "(A1-A4); each attach of a copy a new lifecycle, every other instance's record kept (A5-A8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
