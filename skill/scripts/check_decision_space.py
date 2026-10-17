#!/usr/bin/env python3
"""Gate: every decision of a procedure point, and its options (package 14, C2; GPT PACKAGE13 ruling 1's second half).

On a synthetic catalogue, at procedure points reached by the game's own transitions (game_loop) - an end-of-turn trigger
that readies up to two units, one that may be performed, one with a base cost; a spell that draws and then discards a
card of its controller's choice, one that recycles two cards of the trash (chance orders them), one that spends any
number of buffs from a unit that has two; a Combat whose defenders are a Unit that cannot be dealt damage and another:

  D1 options     each point's request, decider and options are exactly the rules': the up-to-two targets every set of
                 0..2 units; the optional trigger performed or not; the base cost paid or not (and declined, the trigger
                 leaves); the discard any card of the hand as it is after the draw - private to its chooser: no result names
                 them, a trusted verifier's own record does (effect_ir.recording_private_options); the recycle any two cards of the trash, then chance every order of them; the buff
                 spend 0, 1 or 2 of the unit's two buffs
  D2 the same    every point's complete ways (procedure_ways) are exactly D(s) (contract_ways: the program's slots with
                 the state's sets, events by the rule, the procedure as V), way for way
  D3 unasked     (the counterexample) the procedure's domain made to lose a legal target (legal_target_options drops one
                 unit): discovery loses its ways, and the differential names them missing - D(s) never reads that domain
  D4 cross-check a contract missing the trigger's target slot stops D(s) by name: the procedure asks what it does not show
  D5 unproved    a request with no domain, a request asked again after it was answered, and a space past its cap make the
                 point unproved by name - never a partial set
  D6 closure     every request code the engine's modules can make is answered (ANSWERED, PLAY_REQUESTS) or named as not
                 a procedure point's decision (NOT_DECISIONS); every decision kind (engine_decisions.KINDS) is one this
                 module answers
  D8 chance      an ability whose cost recycles two cards of the trash to the Main Deck (Core 416.5): enumerated, once
                 per pair, carrying no receipt (whether it is legal does not depend on the order); applied without one,
                 the procedure asks chance for it; with the receipt chance gives, it commits
  D9 sequences   (found playing set one) a Cleanup's lethal batch where one controller has two Replacement Effects, one
                 over each of two dying units: the controller orders its own sequences (Core 372) - both orders are
                 ways the Cleanup commits (the one replacement_order map is read by what it orders:
                 effect_ir.apply_simultaneous_kill_batch). Where the two overlap on one unit, an order can leave the
                 batch to a follow-up iteration that asks the same question again, and the engine hands decisions to a
                 Cleanup's first iteration only: that point is unproved by name (asked again), never guessed
  D10 chance     (GPT PACKAGE14 ruling 4) recycling five of six cards of the trash to the Main Deck: 120 orders, past
                 CHANCE_CAP. The player's choice before it is enumerated (the representative order's way shows it legal);
                 the point's complete ways are unproved by name - the random successors are not all there
  D7 465.2.c.10  (GPT PACKAGE14 ruling 1) the attacker's 5 damage among a Unit that cannot be dealt damage and a 2-Might
                 Unit: all six splits - the exempt Unit may take damage before the other has its lethal (GPT's own
                 counterexample: all 5 on it). With two 2-Might Units beside it, 465.2.c.3 and c.4 still hold between
                 them: both partial, or one above its lethal while the other lacks it, is refused; all on the exempt
                 Unit is not. A Unit whose prevention is used up after one Deal (Counter Strike's shape) is still
                 refused by name

    python skill/scripts/check_decision_space.py
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import closed_environment as CE  # noqa: E402
import decision_space as DS  # noqa: E402
import engine_decisions as ED  # noqa: E402
import game_loop as GL  # noqa: E402
import play_space as PS  # noqa: E402
import play_transaction as PT  # noqa: E402
import rules_core as RC  # noqa: E402
from check_combat_damage_assignment import closed_combat  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, RULE_NUMBERING  # noqa: E402

errors: list[str] = []
counts: dict[str, int] = {}


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def eot(program_id: str, optional: bool = False) -> list[dict]:
    return [{"trigger_id": program_id, "controller": "$controller", "source_object": "$source_object", "controller_order": 0,
             "effect_program_id": program_id, "optional_at_finalize": optional}]


DRAW = {"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1}


def unit(might=2, **extra):
    return {"kind": "unit", "printed_cost": {"energy": 0, "power": {}}, "base_might": might, "domains": ["fury"], **extra}


def spell(effects):
    return {"object": {"kind": "spell", "printed_cost": {"energy": 0, "power": {}}, "domains": ["fury"]},
            "programs": {"play": {"effects": effects}}}


def catalogue() -> dict:
    value = {
        "schema_version": CE.CATALOGUE_VERSION,
        "environment": {"format": "1v1", "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING,
                        "card_pool": "synthetic"},
        "cards": {
            "Bell": {"object": unit(end_of_turn_triggers=eot("ready")), "programs": {"ready": {"effects": [
                {"op": "ready", "effect_id": "rd", "targets": {"min": 0, "max": 2, "decision_ref": "t",
                                                              "restrictions": {"chosen_zone_class": "board", "kind": "unit"}}}]}}},
            "Maybe": {"object": unit(end_of_turn_triggers=eot("draw", optional=True)), "programs": {"draw": {"effects": [DRAW]}}},
            "Toll": {"object": unit(end_of_turn_triggers=eot("toll")), "programs": {"toll": {"effects": [
                {"op": "trigger_base_cost", "effect_id": "cost", "payment": [{"kind": "exhaust", "object_id": {"object_ref": "program_source"}}]},
                DRAW]}}},
            "TollShot": {"object": unit(end_of_turn_triggers=eot("tollshot")), "programs": {"tollshot": {"effects": [
                {"op": "trigger_base_cost", "effect_id": "cost", "payment": [{"kind": "exhaust", "object_id": {"object_ref": "program_source"}}]},
                {"op": "ready", "effect_id": "rd", "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}]}}},
            "Pick": spell([DRAW, {"op": "discard", "effect_id": "dc", "player": "$controller", "count": 1, "decision_ref": "pick"}]),
            "Shuffle": spell([{"op": "recycle", "effect_id": "rc", "player": "$controller", "decision_ref": "two",
                               "choice": {"selection_kind": "unordered_set", "from": "trash", "by": "controller",
                                          "count": {"exactly": 2}}}]),
            "Shuffle5": spell([{"op": "recycle", "effect_id": "rc", "player": "$controller", "decision_ref": "five",
                                "choice": {"selection_kind": "unordered_set", "from": "trash", "by": "controller",
                                           "count": {"exactly": 5}}}]),
            "Spender": spell([{"op": "spend_buffs", "effect_id": "sb", "player": "$controller", "decision_ref": "sb"}]),
            "Monk": {"object": unit(any_number_of_buffs=True)},
            "Sifter": {"object": {"kind": "gear", "printed_cost": {"energy": 0, "power": {}}, "domains": ["fury"]},
                       "activated_abilities": {"a1": {"cost": {"energy": 0, "power": {}, "additional": [
                           {"cost_id": "text-cost", "mandatory": True, "payment": {"kind": "recycle_trash", "amount": 2}}]},
                           "effect_program_id": "draw"}},
                       "programs": {"draw": {"effects": [DRAW]}}},
            "Grunt": {"object": unit()},
            "Field": {"object": {"kind": "battlefield"}},
        },
        "catalogue_hash": "",
    }
    value["catalogue_hash"] = CE.catalogue_hash(value)
    return value


def environment(cat: dict, placed: list[tuple[str, str, str, str]]) -> dict:
    state = {"schema_version": "riftbound-effect-state.v1", "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
             "players": {p: {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [],
                                       "rune_deck": [], "champion_zone": []},
                             "resources": {"energy": 0, "power": {}}, "points": 0} for p in ("p1", "p2")},
             "objects": {}, "battlefields": {"bf1": CE.place_battlefield(cat, "Field", "bf1")},
             "replacement_effects": [], "mode": {"victory_score": 8}, "turn_id": "turn-1"}
    state["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": []}
    for object_id, ref, owner, zone in placed:
        state["objects"][object_id] = CE.place(cat, ref, owner=owner, object_id=object_id)
        state["players"][owner]["zones"][zone].append(object_id)
    return state


def settle(cat, t, e, until=lambda t: False, limit=12):
    """Run procedures until a request is due (or `until`); (timing, effect) at that procedure point."""
    for _ in range(limit):
        procedure = RC.next_procedure(t)
        if until(t) or procedure.get("discretionary_actions_allowed") or procedure.get("procedure") == "game_over":
            return t, e
        step = GL.run_procedure(t, e, cat)
        if not step["committed"]:
            return t, e
        t, e = step["next_timing_state"], step["next_effect_state"]
    return t, e


def ending_point(cat, card):
    """p1's Main Phase ends with `card` on its Board: the Ending Step's trigger, at its finalization."""
    e = environment(cat, [("x", card, "p1", "base"), ("g1", "Grunt", "p1", "base"), ("g2", "Grunt", "p2", "base"),
                          ("d1", "Grunt", "p1", "main_deck")])
    step = GL.run_action(fixture(), e, cat, {"kind": "end_main_phase", "actor": "p1"})
    return settle(cat, step["next_timing_state"], step["next_effect_state"],
                  until=lambda t: any(i["status"] == "pending" for i in t["chain"]["items"]) and not t["outstanding_tasks"])


def resolving_point(cat, card, extra):
    """p1 plays `card` (no choice at play); both pass: the spell resolving."""
    e = environment(cat, [("s1", card, "p1", "hand")] + extra)
    declaration = next(d for d, _ in PS.play_skeletons(e, cat, "p1") if d["card"] == "s1")
    played = GL.run_action(fixture(), e, cat, {"kind": "play_card", "declaration": declaration})
    if not played["committed"]:
        fail("fixture", f"{card} not played: {played['result'].get('reason_code')} {played['result'].get('reason')}")
        return None, None
    t, e = settle(cat, played["next_timing_state"], played["next_effect_state"])
    for player in ("p1", "p2"):
        passed = GL.run_action(t, e, cat, {"kind": "pass_priority", "actor": t["priority"] or player})
        t, e = passed["next_timing_state"], passed["next_effect_state"]
    return t, e


def values(point) -> list:
    out = []
    for option in point["options"]:
        a = option["answer"]
        out.append(a["settings"] or (a["decisions"][0]["value"] if a["decisions"] else (a["receipts"][0]["permutation"] if a["receipts"] else None)))
    return out


def same_set(got, want) -> bool:
    key = lambda v: repr(sorted(v.items()) if isinstance(v, dict) else v)  # noqa: E731
    return sorted(map(key, got)) == sorted(map(key, want))


def d1_d2(cat) -> list:
    points = []
    t, e = ending_point(cat, "Bell")
    p = DS.decision_point(t, e, cat)
    want = [[], ["g1"], ["g2"], ["x"], ["g1", "g2"], ["g1", "x"], ["g2", "x"]]
    if p["status"] != "enumerated" or (p.get("request") or {}).get("code") != "target_selection_required" \
            or p["decider"] != "p1" or not same_set(values(p), want):
        fail("D1 options", f"up to two targets: {p['status']} {p.get('request')} {p.get('decider')} {values(p)} {p.get('reason')}")
    points.append(("Bell", t, e))
    t, e = ending_point(cat, "Maybe")
    p = DS.decision_point(t, e, cat)
    if (p.get("request") or {}).get("kind") != "perform_optional_trigger" or not same_set(values(p), [{"perform_optional_trigger": True}, {"perform_optional_trigger": False}]):
        fail("D1 options", f"optional trigger: {p.get('request')} {values(p)} {p.get('reason')}")
    points.append(("Maybe", t, e))
    t, e = ending_point(cat, "Toll")
    p = DS.decision_point(t, e, cat)
    if (p.get("request") or {}).get("kind") != "pay_trigger_cost" or not same_set(values(p), [{"pay_trigger_cost": True}, {"pay_trigger_cost": False}]):
        fail("D1 options", f"base cost: {p.get('request')} {values(p)} {p.get('reason')}")
    declined = GL.run_procedure(t, e, cat, settings={"pay_trigger_cost": False})
    if not declined["committed"] or any(i.get("effect_program_id") == "Toll#toll" for i in declined["next_timing_state"]["chain"]["items"]):
        fail("D1 options", "a declined base cost did not take the trigger off the Chain (Core 404.2)")
    points.append(("Toll", t, e))
    t, e = ending_point(cat, "TollShot")     # its target bound before its cost is paid or declined (Core 402, 404)
    points.append(("TollShot", t, e))
    t, e = resolving_point(cat, "Pick", [("h1", "Grunt", "p1", "hand"), ("dk", "Grunt", "p1", "main_deck")])
    if t is not None:
        p = DS.decision_point(t, e, cat)
        if (p.get("request") or {}).get("kind") != "card_selection" or not same_set(values(p), [["h1"], ["dk"]]):
            fail("D1 options", f"discard after the draw: {p.get('request')} {values(p)} {p.get('reason')}")
        step = GL.run_procedure(t, e, cat)
        summary = (step["request"] or {}).get("payload", {}).get("choice") or {}
        if "options" in summary or "chooser_options" in repr(step["result"]) or "private_options" in repr(step["result"]):
            fail("D1 options", "the result of a private choice lists the hand's cards (Core 128.4)")
        trusted = DS._run(t, e, cat)
        if sorted(o["object_id"] for o in (trusted["request"].get("private_options") or {}).get("pick") or []) != ["dk", "h1"]:
            fail("D1 options", "the trusted record does not hold the chooser's options")
        points.append(("Pick", t, e))
    t, e = resolving_point(cat, "Shuffle", [("t1", "Grunt", "p1", "trash"), ("t2", "Grunt", "p1", "trash"), ("t3", "Grunt", "p1", "trash")])
    if t is not None:
        p = DS.decision_point(t, e, cat)
        if (p.get("request") or {}).get("kind") != "card_selection" or not same_set(values(p), [["t1", "t2"], ["t1", "t3"], ["t2", "t3"]]):
            fail("D1 options", f"recycle two: {p.get('request')} {values(p)} {p.get('reason')}")
        chosen = p["options"][0]["answer"] if p["options"] else DS._answer()
        nxt = DS.decision_point(t, e, cat, chosen)
        pair = chosen["decisions"][0]["value"] if chosen["decisions"] else []
        if (nxt.get("request") or {}).get("kind") != "chance" or nxt.get("decider") is not None \
                or not same_set(values(nxt), [pair, pair[::-1]]):
            fail("D1 options", f"chance after the choice: {nxt.get('request')} {nxt.get('decider')} {values(nxt)} {nxt.get('reason')}")
        points.append(("Shuffle", t, e))
    t, e = resolving_point(cat, "Spender", [("m1", "Monk", "p1", "base")])
    if t is not None:
        e["objects"]["m1"].update({"buffed": True, "buff_count": 2})
        p = DS.decision_point(t, e, cat)
        if (p.get("request") or {}).get("kind") != "buff_spend" or not same_set(values(p), [{}, {"m1": 1}, {"m1": 2}]):
            fail("D1 options", f"buff spend: {p.get('request')} {values(p)} {p.get('reason')}")
        points.append(("Spender", t, e))
    for name, t, e in points:
        diff = DS.differential(t, e, cat)
        counts[f"D2 {name}"] = diff.get("contract", 0)
        if not diff["complete"]:
            fail("D2 the same", f"{name}: stopped {diff.get('stopped')} missing {[w['decisions'] for w in diff.get('missing', [])][:2]} "
                                f"extra {[w['decisions'] for w in diff.get('extra', [])][:2]}")
    return points


def d3_unasked(cat, points) -> None:
    name, t, e = points[0]
    real = PT.legal_target_options

    def losing(state, actor, program, selector):
        return [o for o in real(state, actor, program, selector) if o != "g2"]
    PT.legal_target_options = losing
    try:
        diff = DS.differential(t, e, cat)
    finally:
        PT.legal_target_options = real
    if diff.get("complete") or not any(any("g2" in (d.get("value") or []) for d in w["decisions"]) for w in diff.get("missing", [])):
        fail("D3 unasked", f"a domain that loses g2 was not caught by D(s): {diff.get('stopped')} {len(diff.get('missing', []))}")


def d4_cross_check(cat, points) -> None:
    name, t, e = points[0]
    real = DS.program_slots

    def missing_target(*args, **kw):
        return [s for s in real(*args, **kw) if s[1] != "target_selection"]
    DS.program_slots = missing_target
    try:
        contract = DS.contract_ways(t, e, cat)
    finally:
        DS.program_slots = real
    if contract["status"] != "over_cap" or "does not show" not in contract["reason"]:
        fail("D4 cross-check", f"a contract without the target slot was not stopped by name: {contract['status']} {contract.get('reason')}")


def d5_unproved(cat, points) -> None:
    name, t, e = points[0]
    real = GL.run_procedure

    def unknown(*args, **kw):
        step = real(*args, **kw)
        if step["request"]:
            step = {**step, "request": {**step["request"], "code": "mystery_required"}}
        return step
    GL.run_procedure = unknown
    try:
        p = DS.decision_point(t, e, cat)
    finally:
        GL.run_procedure = real
    if p["status"] != "unproved" or "no domain" not in p["reason"]:
        fail("D5 unproved", f"a request with no domain: {p['status']} {p.get('reason')}")

    def deaf(timing, effect, catalogue, decisions=(), settings=None, receipts=()):
        return real(timing, effect, catalogue)      # never reads an answer: asks the same again
    GL.run_procedure = deaf
    try:
        ways = DS.procedure_ways(t, e, cat)
    finally:
        GL.run_procedure = real
    if ways["status"] != "unproved" or "asked again" not in ways["reason"]:
        fail("D5 unproved", f"a request asked again after its answer: {ways['status']} {ways.get('reason')}")
    cap = DS.VALUE_CAP
    DS.VALUE_CAP = 3
    try:
        p = DS.decision_point(t, e, cat)
    finally:
        DS.VALUE_CAP = cap
    if p["status"] != "unproved" or "exceed" not in p["reason"]:
        fail("D5 unproved", f"a space past its cap: {p['status']} {p.get('reason')}")


def d6_closure() -> None:
    codes = set()
    for name in ("effect_ir", "combat", "resolution_bridge", "turn_cycle", "battlefield_control", "rules_core", "play_transaction",
                 "trigger_cost", "hidden", "terminal"):
        source = (SCRIPT_DIR / f"{name}.py").read_text(encoding="utf-8")
        codes |= set(re.findall(r'"([a-z_]+_required)"', source))
    codes |= {f"{kind}_required" for kind in ED.KINDS}     # a ChoiceRequired's own code, from its decision kind
    covered = set(DS.ANSWERED) | set(DS.PLAY_REQUESTS) | set(DS.NOT_DECISIONS) | set(PS.REQUESTS_LEFT)
    # a decision kind's code no procedure makes on its own (answered under another request's name) is listed with why
    as_named = {"replacement_order_required": "replacement_decision_required", "replacement_choice_required": "replacement_decision_required",
                "trigger_order_required": "trigger_order_required", "damage_assignment_required": "damage_assignment_required",
                "resource_allocation_required": "resource_allocation_required", "location_selection_required": "location_selection_required",
                "damage_division_required": "damage_division_required", "mode_selection_required": "mode_selection_required"}
    left = sorted(c for c in codes - covered if c not in as_named)
    if left:
        fail("D6 closure", f"request codes the engine can make that this module neither answers nor names: {left}")
    counts["D6 codes"] = len(codes)


def d7_exempt() -> None:
    import copy as _copy
    cat = {"cards": {}, "tokens": {}}
    exempt = {"replacement_id": "k-no-damage", "controller": "p2", "source_object": "k", "target_object_id": "k",
              "mode": "prevent_event", "event_op": "deal_damage", "optional": False, "uses_remaining": None}
    t, e = closed_combat([("k", {"might": 3}), ("d2", {"might": 2})], attacker_might=5)
    e["replacement_effects"].append(dict(exempt))
    p = DS.decision_point(t, e, cat)
    got = sorted((v.get("d2"), v.get("k")) for v in values(p)) if p["status"] == "enumerated" else p.get("reason")
    if (p.get("request") or {}).get("kind") != "damage_assignment" or got != [(n, 5 - n) for n in range(6)]:
        fail("D7 465.2.c.10", f"the attacker's options among an exempt and a 2-Might Unit: {got}")
    t3, e3 = closed_combat([("k", {"might": 3}), ("d2", {"might": 2}), ("d3", {"might": 2})], attacker_might=5)
    e3["replacement_effects"].append(dict(exempt))
    q = DS.decision_point(t3, e3, cat)
    legal = {(v.get("d2"), v.get("d3"), v.get("k")) for v in values(q)} if q["status"] == "enumerated" else set()
    for split, want in (((0, 0, 5), True), ((1, 0, 4), True), ((2, 2, 1), True), ((2, 3, 0), True),
                        ((1, 1, 3), False), ((3, 0, 2), False), ((3, 1, 1), False)):
        if (split in legal) != want:
            fail("D7 465.2.c.10", f"with two ordinary Units, {split} (d2, d3, exempt) is {'refused' if want else 'admitted'}: "
                                  f"{q['status']} {q.get('reason')}")
    used_up = _copy.deepcopy(e)
    used_up["replacement_effects"][-1]["uses_remaining"] = 1
    r = DS.decision_point(t, used_up, cat)
    if r["status"] != "unproved" or "assignment_lethal_not_reachable" not in r.get("reason", ""):
        fail("D7 465.2.c.10", f"a once-only prevention was not refused by name: {r['status']} {r.get('reason')}")


def d8_chance(cat) -> None:
    e = environment(cat, [("g", "Sifter", "p1", "base"), ("t1", "Grunt", "p1", "trash"), ("t2", "Grunt", "p1", "trash"),
                          ("t3", "Grunt", "p1", "trash")])
    got = PS.enumerate_family("activate_ability", fixture(), e, "p1", cat)
    pairs = sorted(sorted(d["value"]) for a in got["actions"] for d in a["decisions"] if d["kind"] == "card_selection")
    if got["status"] != "enumerated" or pairs != [["t1", "t2"], ["t1", "t3"], ["t2", "t3"]]:
        fail("D8 chance", f"the recycle cost was not enumerated once per pair: {got['status']} {got.get('reason')} {pairs}")
        return
    action = got["actions"][0]
    bare = GL.run_action(fixture(), e, cat, action)
    request = bare["request"] or {}
    chance = (request.get("payload") or {}).get("chance") or {}
    if bare["committed"] or request.get("code") != "randomization_receipt_required" or len(chance.get("permute") or []) != 2:
        fail("D8 chance", f"applied with no receipt, chance was not asked: {bare['committed']} {request.get('code')} {chance}")
        return
    receipt = {"schema_version": "randomization-receipt.v1", "receipt_id": "seed-0", "operation": chance["operation"],
               "operation_id": chance["operation_id"], "player": chance["player"], "permutation": list(reversed(chance["permute"])),
               "provenance": {"provider": "check_decision_space", "method": "fixed"}}
    done = GL.run_action(fixture(), e, cat, action, receipts=[receipt])
    if not done["committed"] or done["next_effect_state"]["players"]["p1"]["zones"]["main_deck"][-2:] != receipt["permutation"]:
        fail("D8 chance", f"with chance's receipt it did not commit in that order: {(done['result'] or {}).get('reason')}")


def d9_sequences() -> None:
    from check_effect_ir import base_state

    def guarded(second_target):
        e = base_state()
        for object_id in ("u3", "u4", "u5"):
            e["objects"][object_id] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2,
                                       "might_modifiers": [], "damage": 0, "exhausted": False}
            e["players"]["p2"]["zones"]["base"].append(object_id)
        e["objects"]["u2"]["damage"] = 4
        e["objects"]["u3"]["damage"] = 2
        e["replacement_effects"] = [
            {"replacement_id": "guard-a", "controller": "p2", "source_object": "u4", "mode": "prevent_event", "event_op": "kill",
             "optional": False, "uses_remaining": None, **second_target[0]},
            {"replacement_id": "guard-b", "controller": "p2", "source_object": "u5", "mode": "prevent_event", "event_op": "kill",
             "optional": False, "uses_remaining": None, **second_target[1]}]
        return e
    t = fixture(priority=None, tasks=["cleanup"])
    apart = DS.procedure_ways(t, guarded(({"target_object_id": "u3"}, {"target_object_id": "u2"})), {"cards": {}, "tokens": {}})
    orders = sorted(tuple(next(iter(d["value"].values()))) for w in apart.get("ways") or [] for d in w["decisions"]
                    if d["kind"] == "replacement_order" and "p2" in d["value"])
    if apart["status"] != "enumerated" or orders != [("guard-a", "guard-b"), ("guard-b", "guard-a")]:
        fail("D9 sequences", f"two of p2's Replacement Effects, one over each unit: {apart['status']} {apart.get('reason')} {orders}")
    counts["D9 ways"] = len(apart.get("ways") or [])
    overlap = DS.procedure_ways(t, guarded(({"target_controller_relation": "friendly"}, {"target_object_id": "u2"})),
                                {"cards": {}, "tokens": {}})
    if overlap["status"] != "unproved" or "asked again" not in overlap.get("reason", ""):
        fail("D9 sequences", f"an overlap whose follow-up iteration asks again was not named: {overlap['status']} {overlap.get('reason')}")


def d10_chance_cap(cat) -> None:
    trash = [(f"t{i}", "Grunt", "p1", "trash") for i in range(6)]
    t, e = resolving_point(cat, "Shuffle5", trash)
    if t is None:
        return
    point = DS.decision_point(t, e, cat)
    if point["status"] != "enumerated" or (point.get("request") or {}).get("kind") != "card_selection" or len(point["options"]) != 6:
        fail("D10 chance", f"the choice before a large chance node was not enumerated: {point['status']} {point.get('reason')}")
    ways = DS.procedure_ways(t, e, cat)
    if ways["status"] != "unproved" or "chance node" not in ways.get("reason", ""):
        fail("D10 chance", f"the complete ways past {DS.CHANCE_CAP} orders were reported {ways['status']}: {ways.get('reason')}")


def main() -> int:
    cat = catalogue()
    problems = CE.validate_catalogue(cat)
    if problems:
        fail("catalogue", str(problems[:3]))
        print("FAILED: decision space checks" + chr(10) + "  - " + chr(10).join(errors))
        return 1
    points = d1_d2(cat)
    if points:
        d3_unasked(cat, points)
        d4_cross_check(cat, points)
        d5_unproved(cat, points)
    d6_closure()
    d7_exempt()
    d8_chance(cat)
    d9_sequences()
    d10_chance_cap(cat)
    if errors:
        print("FAILED: decision space checks")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"OK: each procedure point's request, decider and options are the rules' - targets, an optional trigger, a base "
          f"cost, a private discard after a draw, a recycle and the chance after it, a buff spend from a unit with two; "
          f"every point's ways are exactly D(s); a domain that loses a target is caught by D(s), a contract missing a slot "
          f"stops by name; no domain, a repeated request and a cap are unproved by name; every request code is answered or "
          f"named; 465.2.c.10's exempt Unit takes damage at any point while c.3/c.4 hold among the others; chance inside an action is asked when it is applied; a controller's own replacement sequences are answered (D1-D10) {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
