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
  D8 chance      an ability whose cost recycles two cards of the trash to the Main Deck (Core 417.5): enumerated, once
                 per pair, carrying no receipt (whether it is legal does not depend on the order); applied without one,
                 the procedure asks chance for it; with the receipt chance gives, it commits
  D9 sequences   (found playing set one) a Cleanup's lethal batch where one controller has two Replacement Effects, one
                 over each of two dying units: the controller orders its own sequences (Core 372) - both orders are
                 ways the Cleanup commits (the one replacement_order map is read by what it orders:
                 effect_ir.apply_simultaneous_kill_batch). Where the two overlap on one unit, an order can leave the
                 batch to a follow-up iteration that asks again; package 15 (GPT PACKAGE14 ruling 7): every iteration
                 now gets its own batch's decisions (effect_ir._iteration_decisions), so that point is enumerated - and
                 its ways equal D(s), way for way. A decision no iteration uses is refused (an unknown Replacement
                 Effect in the answer)
  D10 chance     (GPT PACKAGE14 ruling 4) recycling five of six cards of the trash to the Main Deck: 120 orders, past
                 CHANCE_CAP. The player's choice before it is enumerated (the representative order's way shows it legal);
                 the point's complete ways are unproved by name - the random successors are not all there
  D7 467.2.c.10  (GPT PACKAGE14 ruling 1) the attacker's 5 damage among a Unit that cannot be dealt damage and a 2-Might
                 Unit: all six splits - the exempt Unit may take damage before the other has its lethal (GPT's own
                 counterexample: all 5 on it). With two 2-Might Units beside it, 467.2.c.3 and c.4 still hold between
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
import effect_ir as IR  # noqa: E402
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
            # package 15 (D15): look at two, put them back in any order; a unit that may banish itself as it is seen
            "Peek": spell([{"op": "look_at_top", "effect_id": "l", "player": "$controller", "count": 2},
                           {"op": "put_back", "effect_id": "pb", "player": "$controller", "decision_ref": "order"}]),
            "Seer": {"object": unit(banish_when_seen={"play_for_power_any": 1})},
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
        fail("D1 options", "a declined base cost did not take the trigger off the Chain (Core 405.2)")
    points.append(("Toll", t, e))
    t, e = ending_point(cat, "TollShot")     # its target bound before its cost is paid or declined (Core 403, 405)
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
        # package 15 (GPT PACKAGE14 ruling 3): the drawn card is chosen as the object it is when the discard reads it - a
        # new object since it left the Main Deck (Core 124); the identity it had before the draw is refused
        drawn = next((o for o in p["options"] if o["answer"]["decisions"][0]["value"] == ["dk"]), None)
        import effect_ir as IR
        before = IR.object_identity(e, "dk") or "dk@0"
        if drawn is not None:
            entry = drawn["answer"]["decisions"][0]
            stale = {**entry, "selection_identities": {"dk": before}}
            now = GL.run_procedure(t, e, cat, [entry])
            then = GL.run_procedure(t, e, cat, [stale])
            if entry["selection_identities"].get("dk") == before or not now["committed"] or then["committed"]:
                fail("D1 options", f"the drawn card's identity at the discard: as read {entry['selection_identities'].get('dk')} "
                                   f"(committed {now['committed']}), as before the draw {before} (committed {then['committed']})")
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
        fail("D7 467.2.c.10", f"the attacker's options among an exempt and a 2-Might Unit: {got}")
    t3, e3 = closed_combat([("k", {"might": 3}), ("d2", {"might": 2}), ("d3", {"might": 2})], attacker_might=5)
    e3["replacement_effects"].append(dict(exempt))
    q = DS.decision_point(t3, e3, cat)
    legal = {(v.get("d2"), v.get("d3"), v.get("k")) for v in values(q)} if q["status"] == "enumerated" else set()
    for split, want in (((0, 0, 5), True), ((1, 0, 4), True), ((2, 2, 1), True), ((2, 3, 0), True),
                        ((1, 1, 3), False), ((3, 0, 2), False), ((3, 1, 1), False)):
        if (split in legal) != want:
            fail("D7 467.2.c.10", f"with two ordinary Units, {split} (d2, d3, exempt) is {'refused' if want else 'admitted'}: "
                                  f"{q['status']} {q.get('reason')}")
    used_up = _copy.deepcopy(e)
    used_up["replacement_effects"][-1]["uses_remaining"] = 1
    r = DS.decision_point(t, used_up, cat)
    if r["status"] != "unproved" or "assignment_lethal_not_reachable" not in r.get("reason", ""):
        fail("D7 467.2.c.10", f"a once-only prevention was not refused by name: {r['status']} {r.get('reason')}")


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
    overlapping = guarded(({"target_controller_relation": "friendly"}, {"target_object_id": "u2"}))
    overlap = DS.procedure_ways(t, overlapping, {"cards": {}, "tokens": {}})
    against = DS.differential(t, overlapping, {"cards": {}, "tokens": {}})
    if overlap["status"] != "enumerated" or not against.get("complete") or against.get("contract", 0) < 2:
        fail("D9 sequences", f"an overlap whose follow-up iteration asks again is not enumerated equal to D(s): "
                             f"{overlap['status']} {overlap.get('reason')} {against.get('stopped')} {against.get('contract')}")
    counts["D9 overlap ways"] = len(overlap.get("ways") or [])
    # a decision that names a Replacement Effect no iteration has is refused, never ignored
    import effect_ir as IR
    answered = IR.perform_lethal_cleanup(guarded(({"target_object_id": "u3"}, {"target_object_id": "u2"})),
                                         replacement_event_order={"p2": ["guard-a", "guard-b"]})
    bogus = IR.perform_lethal_cleanup(guarded(({"target_object_id": "u3"}, {"target_object_id": "u2"})),
                                      replacement_event_order={"p2": ["guard-a", "guard-b"]},
                                      replacement_choices={"guard-z": {"u2": True}})
    if answered.get("committed") is not True or bogus.get("valid") is not False:
        fail("D9 sequences", f"a cleanup decision naming no applicable Replacement Effect was not refused: {bogus.get('reason')}")


def d12_mulligan(cat) -> None:
    """Package 15: Setup's Mulligan (Core 117) - p1 with four cards in hand may set aside none, one or two (1 + 4 + 6
    answers, a choice private to p1: p2's receipt lists none); two set aside go to the Main Deck's bottom in a random
    order (417.5: chance's two orders), so the ways are 5 + 6 x 2; three are refused (117.1); the first turn waits for
    every Mulligan (118), and begins once both are made."""
    import turn_cycle as TCY
    hand = [(f"h{i}", "Grunt", "p1", "hand") for i in range(4)] + [(f"k{i}", "Grunt", "p2", "hand") for i in range(4)]
    deck = [(f"d{i}", "Grunt", "p1", "main_deck") for i in range(6)] + [(f"e{i}", "Grunt", "p2", "main_deck") for i in range(6)]
    e = environment(cat, hand + deck)
    t = {**fixture(priority=None), "phase": "setup", "turns_taken": {"p1": 0, "p2": 0}, "mulligans_pending": ["p1", "p2"]}
    point = DS.decision_point(t, e, cat)
    sizes = sorted(len(o["answer"]["decisions"][0]["value"]) for o in point.get("options") or [])
    whole = DS.differential(t, e, cat)
    if point["status"] != "enumerated" or point.get("decider") != "p1" or sizes != [0] + [1] * 4 + [2] * 6 \
            or not whole.get("complete") or whole.get("contract") != 5 + 6 * 2:
        fail("D12 mulligan", f"{point['status']} {point.get('decider')} {sizes} {whole.get('stopped')} {whole.get('contract')}")
    import action_receipt as AR
    other = AR.state_receipt(t, e, "p2", cat)
    if not other["complete"] or other["actions"]:
        fail("D12 mulligan", f"p2's receipt at p1's Mulligan: {other['complete']} {other['actions'][:2]} {other['why'][:2]}")
    three = [{"decision_id": TCY.mulligan_decision_id("p1"), "stage": "resolution", "kind": "card_selection",
              "controller": "p1", "value": ["h0", "h1", "h2"],
              "selection_identities": {c: IR.object_identity(e, c) or f"{c}@0" for c in ("h0", "h1", "h2")}}]
    if GL.run_procedure(t, e, cat, three)["committed"]:
        fail("D12 mulligan", "three cards set aside were taken (Core 117.1: up to two)")
    if TCY.begin_turn(t, e)["committed"]:
        fail("D12 mulligan", "the first turn began before the Mulligans (Core 118)")
    none = next(o for o in point["options"] if not o["answer"]["decisions"][0]["value"])
    first = GL.run_procedure(t, e, cat, none["answer"]["decisions"])
    t2, e2 = first["next_timing_state"], first["next_effect_state"]
    second = DS.decision_point(t2, e2, cat)
    keep = next(o for o in second["options"] if not o["answer"]["decisions"][0]["value"])
    done = GL.run_procedure(t2, e2, cat, keep["answer"]["decisions"])
    after = GL.RC.next_procedure(done["next_timing_state"]).get("procedure") if done.get("committed") else None
    if second.get("decider") != "p2" or after != "begin_turn_pending":
        fail("D12 mulligan", f"after p1's Mulligan p2's ({second.get('decider')}), then the first turn ({after})")
    counts["D12 ways"] = whole.get("contract")


def d11_ledger() -> None:
    """Package 15 (GPT PACKAGE14 ruling 3): two of p2's units die in one Cleanup, each with a death trigger - one batch,
    one controller, two abilities: every way orders them (decision_space.event_ledger finds the event from the
    transition, not from a request), and with the request deleted (the procedure ordering them itself) the
    differential fails by the ledger."""
    from check_effect_ir import base_state
    import turn_cycle as TCY
    e = base_state()
    for object_id in ("u3", "u4"):
        e["objects"][object_id] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2,
                                   "might_modifiers": [], "damage": 2, "exhausted": False,
                                   "death_triggers": [{"trigger_id": f"{object_id}:dies", "controller": "p2",
                                                       "source_object": object_id, "controller_order": 0,
                                                       "effect_program_id": f"{object_id}:dies",
                                                       "optional_at_finalize": False}]}
        e["players"]["p2"]["zones"]["base"].append(object_id)
    t = fixture(priority=None, tasks=["cleanup"])
    cat = {"cards": {}, "tokens": {}}
    found = DS.procedure_ways(t, e, cat)
    orders = [d for w in found.get("ways") or [] for d in w["decisions"] if d["kind"] == "trigger_order"]
    whole = DS.differential(t, e, cat)
    if found["status"] != "enumerated" or len(orders) != 2 or not whole.get("complete") or whole.get("ledger"):
        fail("D11 ledger", f"two simultaneous death triggers of p2: {found['status']} {found.get('reason')} orders={len(orders)} "
                           f"{whole.get('stopped')} {whole.get('ledger')}")
    counts["D11 orders"] = len(orders)
    real = TCY._settle_trigger_orders

    def silent(triggers, decisions, base):
        # the request deleted: the procedure orders one controller's simultaneous triggers itself
        seen: dict = {}
        for trigger in triggers:
            key = (trigger.get("batch_sequence"), trigger.get("batch_id"), trigger["controller"])
            trigger["controller_order"] = seen.get(key, 0)
            seen[key] = trigger["controller_order"] + 1
        return None
    TCY._settle_trigger_orders = silent
    try:
        deleted = DS.differential(t, e, cat)
    finally:
        TCY._settle_trigger_orders = real
    if deleted.get("complete") or not any("trigger_order" in p for p in deleted.get("ledger") or []):
        fail("D11 ledger", f"with the trigger order request deleted the differential did not fail by the ledger: "
                           f"{deleted.get('complete')} {deleted.get('stopped')} {deleted.get('ledger')}")


def d13_screening_bounds() -> None:
    """Package 15 (GPT PACKAGE15 ruling 2): screening never cuts short. On a synthetic procedure (the engine's run
    replaced): a member taken only with the 17th value of a slot the procedure asks first is found, and past FILL_CAP
    the run is unproved by name; a member refused with the earlier slot's first value but taken with its second is found
    (its way is in D(s)), and past CONTEXT_CAP the point is unproved by name; a member refused after chance was answered
    in one order is marked so."""
    def entry(slot, value):
        return {"decision_id": slot, "stage": "resolution", "kind": "target_selection", "controller": "p1", "value": value}

    def step(committed, request=None, state=None):
        return {"committed": committed, "label": "resolve:fake", "request": request,
                "next_effect_state": state or {}, "next_timing_state": {}}

    def ask(*ids):
        return {"code": "target_selection_required", "decision_ids": list(ids), "payload": {}, "controller": "p1"}

    fills = {"f": [entry("f", [f"v{i}"]) for i in range(20)]}

    def run_fill(answer):
        got = {d["decision_id"]: d["value"] for d in answer["decisions"]}
        if "f" not in got:
            return step(False, ask("f"))
        return step(got["f"] == ["v16"], state={"f": got["f"]})
    found = DS.settle_screening(run_fill, DS._answer([entry("m", ["x"])]), fills=fills, screening="m", known={"f", "m"})
    if not found["committed"]:
        fail("D13 fill", "a member taken only with the 17th value of a slot asked first was refused")
    real_cap = DS.FILL_CAP
    DS.FILL_CAP = 16
    try:
        DS.settle_screening(run_fill, DS._answer([entry("m", ["x"])]), fills=fills, screening="m", known={"f", "m"})
        fail("D13 fill", f"20 values of a slot asked first, past a cap of 16, were not unproved")
    except DS.Unproved:
        pass
    finally:
        DS.FILL_CAP = real_cap

    def run_chance(answer):
        if not answer["receipts"]:
            return step(False, {"code": "randomization_receipt_required", "decision_ids": [], "payload": {"chance": {
                "operation": "recycle", "operation_id": "op1", "player": "p1", "permute": ["c1", "c2"]}}})
        return step(False)
    if not DS.settle_screening(run_chance, DS._answer([entry("m", ["x"])]), fills={}, screening="m", known={"m"}).get("screen_chance"):
        fail("D13 chance", "a member refused after chance was answered in one order was not marked")

    # two slots: a (x, y) asked first, b (p, q); the procedure takes (x, p) and (y, q) only - q is refused with a's first
    # value and taken with its second
    slots = [("a", "target_selection", "resolution", DS.SetSpace(["x", "y"], 1, 1), "p1"),
             ("b", "target_selection", "resolution", DS.SetSpace(["p", "q"], 1, 1), "p1")]

    def run_pair(timing, effect, catalogue, answer=None):
        got = {d["decision_id"]: d["value"] for d in (answer or DS._answer())["decisions"]}
        if "a" not in got:
            return step(False, ask("a"))
        if "b" not in got:
            return step(False, ask("b"))
        pair = (got["a"], got["b"])
        return step(pair in ((["x"], ["p"]), (["y"], ["q"])), state={"pair": [got["a"], got["b"]]})
    saved = (DS._run, DS.program_slots, DS._subject, GL.run_procedure, GL.item_program)
    DS._run = run_pair
    DS.program_slots = lambda *a, **k: list(slots)
    DS._subject = lambda *a, **k: {"controller": "p1"}
    GL.run_procedure = lambda *a, **k: step(False, ask("a"))
    GL.item_program = lambda *a, **k: {}
    try:
        t, e = {"turn_player": "p1"}, {"objects": {}}
        ways = DS.contract_ways(t, e, {})
        pairs = sorted(tuple(tuple(d["value"]) for d in w["decisions"]) for w in ways.get("ways") or [])
        if ways["status"] != "enumerated" or pairs != [(("x",), ("p",)), (("y",), ("q",))]:
            fail("D13 context", f"a member taken only with the earlier slot's second value: {ways['status']} {ways.get('reason')} {pairs}")
        counts["D13 ways"] = len(pairs)
        real_context = DS.CONTEXT_CAP
        DS.CONTEXT_CAP = 0
        try:
            capped = DS.contract_ways(t, e, {})
        finally:
            DS.CONTEXT_CAP = real_context
        if capped["status"] == "enumerated" or "screening b" not in capped.get("reason", ""):
            fail("D13 context", f"past CONTEXT_CAP the point was not unproved by name: {capped['status']} {capped.get('reason')}")
    finally:
        DS._run, DS.program_slots, DS._subject, GL.run_procedure, GL.item_program = saved


def d14_unread_by_contract() -> None:
    """Package 15 (GPT PACKAGE15 ruling 7): whether a point reads a slot is the program's contract, the states only a
    check of it. On a synthetic procedure: a resolution's choice whose members all leave the same states but different
    records of what happened (a card revealed) is a choice - every member is a way; a slot the contract says a
    finalization does not read, whose member changes what the procedure did, is unproved by name."""
    def step(committed, request=None, trace=None):
        return {"committed": committed, "label": "x", "request": request, "next_effect_state": {"same": 1},
                "next_timing_state": {}, "result": {"trace": trace or {}}, "cleanup": []}

    slots = [("r", "card_selection", "resolution", DS.SetSpace(["x", "y"], 1, 1), "p1")]

    noting = [True]

    def run_reveal(timing, effect, catalogue, answer=None):
        # the choice noted as needed where the procedure meets it, as the engine's choices do (effect_ir.resolve_choice)
        if noting[0]:
            IR.ledger_note("choice", "r")
        got = {d["decision_id"]: d["value"] for d in (answer or DS._answer())["decisions"]}
        return step(True, trace={"revealed": got.get("r")})
    saved = (DS._run, DS.program_slots, DS._subject, GL.run_procedure, GL.item_program)
    DS._run = run_reveal
    DS.program_slots = lambda *a, **k: list(slots)
    DS._subject = lambda *a, **k: {"controller": "p1", "id": "item"}
    GL.item_program = lambda *a, **k: {"effects": []}
    try:
        t, e = {"turn_player": "p1"}, {"objects": {}}
        GL.run_procedure = lambda *a, **k: {**step(True), "label": "resolve:spell"}
        ways = DS.contract_ways(t, e, {})
        values = sorted(str([d["value"] for d in w["decisions"]]) for w in ways.get("ways") or [])
        if ways["status"] != "enumerated" or values != ["[['x']]", "[['y']]", "[]"]:
            fail("D14 unread", f"a choice that changes only what happened was not kept: {ways['status']} {ways.get('reason')} {values}")
        counts["D14 ways"] = len(values)
        # the same procedure noting no need of the choice it reads (one that stopped asking and stopped noting): the slot
        # is taken as not read here, and a member that changes what happens makes it unproved by name
        noting[0] = False
        silent = DS.contract_ways(t, e, {})
        if silent["status"] == "enumerated" or "met by no need" not in silent.get("reason", ""):
            fail("D14 unread", f"a choice read with no need noted was not unproved: {silent['status']} {silent.get('reason')}")
        noting[0] = True
        GL.run_procedure = lambda *a, **k: {**step(True), "label": "finalize:trigger"}
        capped = DS.contract_ways(t, e, {})
        if capped["status"] == "enumerated" or "is not read at finalize:trigger" not in capped.get("reason", ""):
            fail("D14 unread", f"a slot the contract says is not read, yet read: {capped['status']} {capped.get('reason')}")
    finally:
        DS._run, DS.program_slots, DS._subject, GL.run_procedure, GL.item_program = saved


def _deleting(codes):
    """The procedure with these requests deleted: asked one, it answers it itself with the first value the rules give
    (a procedure that stopped asking and took a default) and runs on - no request of these codes ever leaves it."""
    real = GL.run_procedure

    def run(timing, effect, catalogue, decisions=None, settings=None, receipts=None):
        decisions, settings = list(decisions or []), dict(settings or {})
        step = None
        for _ in range(8):
            with IR.recording_private_options() as log:
                step = real(timing, effect, catalogue, decisions, settings, list(receipts or []))
            request = step.get("request")
            if step["committed"] or request is None or request["code"] not in codes:
                return step
            _, answers = DS._event_values({**request, "private_options": dict(log)}, timing, effect, step["label"],
                                          request.get("controller"))
            decisions += answers[0]["decisions"]
            settings.update(answers[0]["settings"])
        return step
    return run


def d15_ledger_kinds(cat) -> None:
    """Package 15 (GPT PACKAGE15 ruling 3): each kind of event a procedure names - a player's order of cards put back, a
    card that may banish itself as it is seen, a Unit an effect plays without naming where, two staged Combats, the
    Replacement Effects of one Cleanup - is held by the ledger to its decisions, read from what the procedure meets as it
    runs (effect_ir.recording_ledger), not from its requests: each point is enumerated equal to D(s) with the ledger
    clean, and with that request deleted (the procedure answering itself with a default) the differential fails by the
    ledger, naming the kind. A replacement decision no event needs fails it too (both ways)."""
    from check_cleanup_orchestration import with_task
    from check_combat_staging import contested_board
    from check_effect_ir import base_state
    import check_limited_play as LP
    empty = {"cards": {}, "tokens": {}}
    points = []
    t, e = resolving_point(cat, "Peek", [("g1", "Grunt", "p1", "main_deck"), ("g2", "Grunt", "p1", "main_deck")])
    points.append(("card_ordering", cat, t, e, {"card_ordering_required", "card_selection_required"}))
    t, e = resolving_point(cat, "Peek", [("sr", "Seer", "p1", "main_deck"), ("g2", "Grunt", "p1", "main_deck")])
    points.append(("seen_banish", cat, t, e, {"optional_choice_required"}))
    done = LP.resolved_harrowing()
    points.append(("entry_location", empty, done["next_timing_state"], done["next_effect_state"], {"entry_location_required"}))
    two = contested_board(extra_units=(("u3", "p1", "bf2"), ("u4", "p2", "bf2")))
    two["battlefields"]["bf2"].update({"contested": True, "contested_by": "p2"})
    two["mode"] = {"victory_score": 8}
    two["objects"]["u1"]["damage"] = 0
    points.append(("location", empty, with_task(fixture()), two, {"location_selection_required"}))
    guarded = base_state()
    for object_id in ("u3", "u4", "u5"):
        guarded["objects"][object_id] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2,
                                         "might_modifiers": [], "damage": 0, "exhausted": False}
        guarded["players"]["p2"]["zones"]["base"].append(object_id)
    guarded["objects"]["u2"]["damage"] = 4
    guarded["objects"]["u3"]["damage"] = 2
    guarded["replacement_effects"] = [
        {"replacement_id": "guard-a", "controller": "p2", "source_object": "u4", "mode": "prevent_event", "event_op": "kill",
         "optional": False, "uses_remaining": None, "target_controller_relation": "friendly"},
        {"replacement_id": "guard-b", "controller": "p2", "source_object": "u5", "mode": "prevent_event", "event_op": "kill",
         "optional": False, "uses_remaining": None, "target_object_id": "u2"}]
    points.append(("replacement", empty, fixture(priority=None, tasks=["cleanup"]), guarded, {"replacement_decision_required"}))
    real = GL.run_procedure
    for kind, catalogue_, t, e, codes in points:
        if t is None:
            continue
        whole = DS.differential(t, e, catalogue_)
        if not whole.get("complete") or whole.get("ledger"):
            fail("D15 ledger", f"{kind}: not enumerated equal to D(s) with a clean ledger: {whole.get('stopped')} "
                               f"{whole.get('ledger')} missing {len(whole.get('missing') or [])} extra {len(whole.get('extra') or [])}")
            continue
        counts[f"D15 {kind}"] = whole.get("contract")
        GL.run_procedure = _deleting(codes)
        try:
            deleted = DS.differential(t, e, catalogue_)
        finally:
            GL.run_procedure = real
        if deleted.get("complete") or not any(p.startswith(kind) for p in deleted.get("ledger") or []):
            fail("D15 ledger", f"{kind}: with its request deleted the differential did not fail by the ledger: "
                               f"{deleted.get('complete')} {deleted.get('stopped')} {(deleted.get('ledger') or [])[:2]}")
        if kind == "replacement":
            way = DS.procedure_ways(t, e, catalogue_)["ways"][0]
            extra = copy.deepcopy(way)
            extra["decisions"].append({"decision_id": "replacement:choice:guard-b:u3", "stage": "resolution",
                                       "kind": "replacement_choice", "controller": "p2", "value": {"guard-b": {"u3": False}}})
            problems = DS.event_ledger(t, e, catalogue_, extra)
            if not problems:
                fail("D15 ledger", "a replacement decision no event needs was not named")


def d16_iterations() -> None:
    """Package 15 (GPT PACKAGE15 round 2, ruling 1): a Cleanup's follow-up iteration decides for itself. A Unit with
    lethal damage and three single-use "prevent its death" Replacement Effects of its controller: the first iteration
    orders three sequences (one applies and is spent), the follow-up iteration orders the two left - its own decision
    (id "#cleanup1"), which may differ for the same first choices; every way equals D(s) with a clean ledger. With the
    follow-up made to reuse the first iteration's decisions (the old behavior), that choice is gone."""
    from check_effect_ir import base_state
    import engine_decisions as ED
    e = base_state()
    e["objects"]["u3"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 2, "exhausted": False}
    e["players"]["p2"]["zones"]["base"].append("u3")
    e["replacement_effects"] = [{"replacement_id": f"guard-{x}", "controller": "p2", "source_object": "u3",
                                 "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": 1,
                                 "target_object_id": "u3"} for x in "abc"]
    t = fixture(priority=None, tasks=["cleanup"])
    cat = {"cards": {}, "tokens": {}}

    def follow_ups(found):
        by_first: dict = {}
        for way in found.get("ways") or []:
            first = tuple(sorted((d["decision_id"], repr(d["value"])) for d in way["decisions"] if "#cleanup" not in d["decision_id"]))
            later = tuple(sorted((d["decision_id"], repr(d["value"])) for d in way["decisions"] if "#cleanup" in d["decision_id"]))
            by_first.setdefault(first, set()).add(later)
        return any(any(later) for laters in by_first.values() for later in laters), \
            any(len(laters) > 1 for laters in by_first.values())
    found = DS.procedure_ways(t, e, cat)
    own, differ = follow_ups(found)
    whole = DS.differential(t, e, cat)
    if found["status"] != "enumerated" or not own or not differ or not whole.get("complete") or whole.get("ledger"):
        fail("D16 iterations", f"{found['status']} {found.get('reason')} own={own} differ={differ} "
                               f"{whole.get('stopped')} {whole.get('ledger')}")
    counts["D16 ways"] = len(found.get("ways") or [])
    real = ED.later_iteration_maps
    ED.later_iteration_maps = lambda decisions: None     # every iteration reads the first's decisions, as before
    try:
        old = DS.procedure_ways(t, e, cat)
    finally:
        ED.later_iteration_maps = real
    if old["status"] == "enumerated" and all(follow_ups(old)):
        fail("D16 iterations", "with the follow-up iteration reusing the first's decisions, it still chose for itself")


def d17_public_ids() -> None:
    """Package 15 (GPT PACKAGE15 round 2, ruling 5): an engine-made id depends on nothing a player cannot see. A Cleanup
    stages a Combat on a contested Battlefield, both players holding cards in hand and Main Deck: its Combat id is the
    same with each Main Deck reordered, a hand card swapped for another, and on each player's view (action_receipt.
    actor_view) as on the true state. With the id made from the whole state again (the old behavior), it is not."""
    from check_cleanup_orchestration import with_task
    from check_combat_staging import contested_board
    import action_receipt as AR
    import turn_cycle as TCY

    def board():
        e = contested_board()
        e["mode"] = {"victory_score": 8}
        e["objects"]["u1"]["damage"] = 0
        for player, cards in (("p1", ("a1", "a2", "a3")), ("p2", ("b1", "b2", "b3"))):
            for index, card in enumerate(cards):
                e["objects"][card] = {"owner": player, "controller": player, "kind": "unit", "base_might": 1 + index,
                                      "might_modifiers": [], "damage": 0, "exhausted": False}
            e["players"][player]["zones"]["main_deck"] += list(cards[:2])
            e["players"][player]["zones"]["hand"].append(cards[2])
        return e

    def combat_id(e):
        got = TCY.run_cleanup(with_task(fixture()), e)
        return ((got.get("next_timing_state") or {}).get("combat") or {}).get("combat_id"), got.get("reason_code")

    def variants():
        e = board()
        out = {"true": e}
        shuffled = copy.deepcopy(e)
        for player in ("p1", "p2"):
            shuffled["players"][player]["zones"]["main_deck"].reverse()
        out["decks reordered"] = shuffled
        swapped = copy.deepcopy(e)
        swapped["objects"]["b3"]["base_might"] = 9
        out["a hand card changed"] = swapped
        for player in ("p1", "p2"):
            out[f"{player}'s view"] = AR.actor_view(e, player)
        return out

    def check():
        ids = {name: combat_id(state) for name, state in variants().items()}
        return ids, len({i for i, _ in ids.values()}) == 1 and None not in {i for i, _ in ids.values()}
    ids, same = check()
    if not same:
        fail("D17 public ids", f"the Combat id depends on what a player cannot see: {ids}")
    counts["D17 ids"] = len(ids)
    real = IR.public_projection
    IR.public_projection = lambda state: copy.deepcopy(state)   # the whole state, as before
    try:
        old_ids, old_same = check()
    finally:
        IR.public_projection = real
    if old_same:
        fail("D17 public ids", f"made from the whole state, the Combat id still did not change: {old_ids}")


def d18_move_cleanup() -> None:
    """Package 15 (GPT PACKAGE15 round 3): a Standard Move's Cleanup is given the Move's decisions. p1 moves a Unit from
    its Base to a Battlefield; an opposing Unit with lethal damage has three single-use "prevent its death" Replacement
    Effects of its controller. Without a choice the Move asks it by name; with legal choices - each follow-up iteration's
    its own, in either order - it commits; and C2's Standard Move family is unproved by name there (the action space does
    not enumerate these choices), never complete with the Move silently missing. With the Cleanup given no decisions (the
    old behavior), the choices are not read (the Move never commits) - and C2 still names it unproved."""
    from check_effect_ir import base_state
    import combat as CB
    import legal_action as LA
    import action_receipt as AR
    import action_space as AS
    e = base_state()
    e["objects"]["m1"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 0, "exhausted": False}
    e["players"]["p1"]["zones"]["base"].append("m1")
    e["objects"]["u5"] = {"owner": "p2", "controller": "p2", "kind": "unit", "base_might": 2, "might_modifiers": [],
                          "damage": 2, "exhausted": False}
    e["players"]["p2"]["zones"]["base"].append("u5")
    e["replacement_effects"] = [{"replacement_id": f"guard-{x}", "controller": "p2", "source_object": "u5",
                                 "mode": "prevent_event", "event_op": "kill", "optional": False, "uses_remaining": 1,
                                 "target_object_id": "u5"} for x in "abc"]
    t = fixture()
    declaration = {"schema_version": CB.STANDARD_MOVE_DECLARATION_VERSION, "actor": "p1", "units": ["m1"],
                   "destination": {"kind": "battlefield", "battlefield": "bf1"},
                   "unit_identities": {"m1": IR.object_identity(e, "m1") or "m1@0"},
                   "cost_confirmation": {"exhaust_confirmed": True}}

    def move(decisions):
        # a Standard Move's decisions bind to its three inputs (combat.standard_move's base input_hash)
        envelope = {"schema_version": "engine-decisions.v1",
                    "input_hash": IR.hash_value({"timing_state": t, "effect_state": e, "declaration": declaration}),
                    "decisions": decisions} if decisions else None
        return CB.standard_move(t, e, declaration, envelope)

    def answered(flip_later):
        decisions = []
        for _ in range(12):
            got = move(decisions)
            if got.get("committed") or not got.get("replacement_decision_required"):
                return got, decisions
            rids, events, which = list(got["replacement_ids"]), list(got["event_ids"]), got.get("replacement_decision")
            k = int(got.get("cleanup_iteration") or 0)
            if flip_later and k:
                rids = list(reversed(rids))
            value = {"sequence_order": {got.get("decision_controller"): rids}, "object_order": {events[0]: rids},
                     "event_order": {rids[0]: events}, "choice": {rids[0]: {events[0]: True}}}[which]
            decisions.append({"decision_id": DS.replacement_ref(which, sorted(got["replacement_ids"]), got["event_ids"], k),
                              "stage": "resolution", "kind": "replacement_choice" if which == "choice" else "replacement_order",
                              "controller": got.get("decision_controller"), "value": value})
        return got, decisions
    asked = move([])
    if not asked.get("replacement_decision_required") or asked.get("committed"):
        fail("D18 move cleanup", f"with no choice the Move did not ask its Cleanup's: {asked.get('reason_code')} {asked.get('reason')}")
    first, first_decisions = answered(False)
    flipped, flipped_decisions = answered(True)
    later = [d for d in flipped_decisions if "#cleanup" in d["decision_id"]]
    if not first.get("committed") or not flipped.get("committed") or not later \
            or [d["value"] for d in first_decisions] == [d["value"] for d in flipped_decisions]:
        fail("D18 move cleanup", f"legal choices did not commit, or no follow-up iteration chose for itself: "
                                 f"{first.get('reason')} {flipped.get('reason')} later={len(later)}")
    counts["D18 decisions"] = len(first_decisions)

    def family():
        result = LA.enumerate_actions(AR._observation(t, e, "p1"), "p1")
        return AS.differential("standard_move", t, e, "p1", result)
    diff = family()
    if diff.get("complete") or "unproved" not in str(diff.get("stopped")):
        fail("D18 move cleanup", f"C2's Standard Move family was not unproved by name: {diff.get('complete')} {diff.get('stopped')}")
    real = IR.perform_lethal_cleanup
    IR.perform_lethal_cleanup = lambda state, **kwargs: real(state)     # the Cleanup given no decisions, as before
    try:
        old_first, _ = answered(False)
        old = family()
    finally:
        IR.perform_lethal_cleanup = real
    if old_first.get("committed"):
        fail("D18 move cleanup", "with the Cleanup given no decisions the choices were still read")
    # (C2 names it there too, as round 2's refusal classing does: the Move alone ends neither its own refusal nor the
    # Move's - the family is unproved, never silently complete)
    if old.get("complete"):
        fail("D18 move cleanup", f"with the Cleanup given no decisions the family was silently complete: {old.get('stopped')}")


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
    d11_ledger()
    d12_mulligan(cat)
    d13_screening_bounds()
    d14_unread_by_contract()
    d15_ledger_kinds(cat)
    d16_iterations()
    d17_public_ids()
    d18_move_cleanup()
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
          f"named; 467.2.c.10's exempt Unit takes damage at any point while c.3/c.4 hold among the others; chance inside an action is asked when it is applied; a controller's own replacement sequences are answered (D1-D10) {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
