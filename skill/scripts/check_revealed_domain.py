#!/usr/bin/env python3
"""A rune revealed from the Rune Deck, and one Reflexive Trigger per Domain (package 11, Twisted Fate - Gambler: "When I
attack, reveal the top rune of your rune deck, then recycle it. Do one of the following based on its domain: [Fury] Deal 2
to an enemy unit here and 1 to all other enemy units here. [Mind] Draw 1. [Order] Stun an enemy unit.").

Core 387.1 / 387.1.b: "Do one of the following" marks Reflexive Triggers, the effect saying which goes on the Chain; each
is its own Chain item (388.1), its targets chosen as it is finalized. GPT 2026-10-12 (PACKAGE11 ruling 18): the rune's
identity and Domain are noted as it is revealed, and recycling it does not erase them; an empty Rune Deck, or a Domain no
branch lists, is handled by name, never guessed. The engine's shape: reveal {from: rune_deck_top} notes each rune's
Domains in its trace; conditional_triggers {condition: {kind: revealed_domain, effect_id, domain}} - the bridge adds the
branch whose Domain the revealed rune had (resolution_bridge._domain_reflexive); affected criteria exclude_targets_of
leaves out what an earlier instruction of the program targeted ("all other enemy units here").

  D1 Fury     the rune is recycled to the bottom of p1's Rune Deck; only the Fury branch is added; finalized choosing e1:
              e1 dealt 2, e3 (the other enemy unit at bf1) dealt 1, e2 at bf2 and p1's a1 untouched
  D2 Mind     only the Mind branch: p1 draws 1, nothing chosen
  D3 Order    only the Order branch: finalized choosing e2 (at bf2 - "an enemy unit", anywhere), it is Stunned
  D4 other    a Chaos rune: no branch added, the trace names why; the rune still recycled
  D5 empty    an empty Rune Deck: nothing revealed (rune_deck_empty), nothing recycled, no branch, by name
  D6 several  a rune of two listed Domains: refused as unsupported by name (revealed_card_of_several_listed_domains)
  D7 illegal  the Fury branch's target: p1's own unit, or an enemy unit at bf2, is refused at finalization
  V  shape    revealed_domain without a Domain, or naming no reveal; exclude_targets_of naming no earlier target; each
              refused. The grammar lowers the reveal and the Fury instruction

    python skill/scripts/check_revealed_domain.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from check_effect_ir import base_state, settle_contested  # noqa: E402
from check_rules_core import fixture, item  # noqa: E402
from effect_ir import PROGRAM_VERSION, hash_value, object_identity, validate_program, validate_state  # noqa: E402
from resolution_bridge import finalize_trigger, resolve_with_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF, pass_priority  # noqa: E402

errors: list[str] = []
HERE = {"kind": "program_source_current_battlefield"}
BRANCHES = {"fury": "tf-fury", "mind": "tf-mind", "order": "tf-order"}


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(pid, effects, **extra):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "source_object": "tf", "effects": effects, **extra}


def head():
    return program("tf-attack-fx", [{"op": "reveal", "effect_id": "rv", "player": "p1", "from": "rune_deck_top", "count": 1},
                                    {"op": "recycle", "effect_id": "rc", "player": "p1", "revealed_by": "rv"}],
                   conditional_triggers=[{"trigger_id": f"tf-{d}", "controller": "p1", "source_object": "tf",
                                          "controller_order": i, "effect_program_id": pid, "optional_at_finalize": False,
                                          "condition": {"kind": "revealed_domain", "effect_id": "rv", "domain": d}}
                                         for i, (d, pid) in enumerate(BRANCHES.items())])


TARGET_HERE = {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy",
               "location_ref": dict(HERE)}
REGISTRY = {
    "tf-fury": program("tf-fury", [
        {"op": "deal_damage", "effect_id": "dmg", "amount": 2, "target": dict(TARGET_HERE)},
        {"op": "deal_damage", "effect_id": "dmg-others", "amount": 1,
         "affected": {"criteria": {"kind": "unit", "controller_relation": "enemy", "location_ref": dict(HERE),
                                   "exclude_targets_of": "dmg"}}}]),
    "tf-mind": program("tf-mind", [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]),
    "tf-order": program("tf-order", [{"op": "stun", "effect_id": "st", "target": {
        "decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"}}]),
}


def unit(owner, might):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False}


def board(domains=("fury",), runes=1):
    """tf (p1) with a1 (p1), e1 and e3 (p2) at bf1; e2 (p2) at bf2. p1's Rune Deck: rt (the given Domains) on top of
    rb, or empty when runes is 0."""
    state = base_state()
    state["battlefields"]["bf2"] = {"controller": None, "objects": []}
    for oid, owner, might in (("tf", "p1", 3), ("a1", "p1", 2), ("e1", "p2", 4), ("e3", "p2", 3), ("e2", "p2", 5)):
        state["objects"][oid] = unit(owner, might)
    state["battlefields"]["bf1"]["objects"] += ["tf", "a1", "e1", "e3"]
    state["battlefields"]["bf2"]["objects"] = ["e2"]
    for old in state["players"]["p1"]["zones"]["rune_deck"]:
        state["objects"].pop(old, None)
    state["players"]["p1"]["zones"]["rune_deck"] = []
    for oid, ds in (("rt", list(domains)), ("rb", ["calm"]))[:runes * 2]:
        state["objects"][oid] = {"owner": "p1", "controller": "p1", "kind": "rune", "base_might": 0, "might_modifiers": [],
                                 "damage": 0, "exhausted": False, "domains": ds}
        state["players"]["p1"]["zones"]["rune_deck"].append(oid)
    return settle_contested(state)


def resolve_head(state, prog=None):
    trig = {**item("tf-attack", "p1", "ability", "triggered", "finalized", "standard"), "source_object": "tf",
            "effect_program_id": "tf-attack-fx", "optional_at_finalize": False, "trigger_kind": "triggered",
            "batch_sequence": 0, "batch_id": "attack:tf"}
    timing = fixture(priority="p2", items=[trig], passes=["p1", "p2"])
    return resolve_with_program(timing, "tf-attack", state, prog or head())


def branches(done):
    return [i["id"] for i in done["next_timing_state"]["chain"]["items"] if i.get("trigger_kind") == "reflexive"]


def choose(state, value):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
        {"decision_id": "t", "stage": "trigger_finalization", "kind": "target_selection", "controller": "p1", "value": [value],
         "selection_identities": {value: object_identity(state, value)}}]}


def finish(done, branch, pick=None):
    after = done["next_effect_state"]
    fin = finalize_trigger(done["next_timing_state"], after, REGISTRY, choose(after, pick) if pick else None)
    if not fin.get("committed") or fin.get("removed"):
        return fin
    timing = fin["next_timing_state"]
    for actor in ("p1", "p2"):
        timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
    return resolve_with_program(timing, f"tf-{branch}", fin["next_effect_state"], REGISTRY[BRANCHES[branch]])


def conditional(done):
    return ((done.get("trace") or {}).get("conditional_triggers") or []) if isinstance(done.get("trace"), dict) else []


def main() -> int:
    if validate_state(board()):
        fail("board", validate_state(board())[:2])
        return report()
    # D1
    done = resolve_head(board(("fury",)))
    if not done.get("committed") or branches(done) != ["tf-fury"]:
        fail("D1 Fury", f"{done.get('reason') or done.get('reason_code')} {branches(done) if done.get('committed') else ''}")
    else:
        if done["next_effect_state"]["players"]["p1"]["zones"]["rune_deck"] != ["rb", "rt"]:
            fail("D1 recycled", done["next_effect_state"]["players"]["p1"]["zones"]["rune_deck"])
        got = finish(done, "fury", "e1")
        s = got.get("next_effect_state") or {}
        dmg = {o: (s.get("objects") or {}).get(o, {}).get("damage") for o in ("e1", "e3", "e2", "a1", "tf")}
        if not got.get("committed") or dmg != {"e1": 2, "e3": 1, "e2": 0, "a1": 0, "tf": 0}:
            fail("D1 Fury", f"{got.get('reason') or got.get('reason_code')} {dmg}")
        # D7 illegal targets for the Fury branch
        for label, pick in (("p1's own unit", "a1"), ("an enemy unit at bf2", "e2")):
            refused = finalize_trigger(done["next_timing_state"], done["next_effect_state"], REGISTRY,
                                       choose(done["next_effect_state"], pick))
            if refused.get("committed") and not refused.get("removed"):
                fail("D7 illegal", f"{label} ({pick}) was accepted")
    # D2
    done = resolve_head(board(("mind",)))
    if not done.get("committed") or branches(done) != ["tf-mind"]:
        fail("D2 Mind", f"{done.get('reason')} {branches(done) if done.get('committed') else ''}")
    else:
        hand = len(done["next_effect_state"]["players"]["p1"]["zones"]["hand"])
        got = finish(done, "mind")
        if not got.get("committed") or len(got["next_effect_state"]["players"]["p1"]["zones"]["hand"]) != hand + 1:
            fail("D2 Mind", f"{got.get('reason') or got.get('reason_code')} the draw did not happen")
    # D3
    done = resolve_head(board(("order",)))
    if not done.get("committed") or branches(done) != ["tf-order"]:
        fail("D3 Order", f"{done.get('reason')} {branches(done) if done.get('committed') else ''}")
    else:
        got = finish(done, "order", "e2")
        if not got.get("committed") or not got["next_effect_state"]["objects"]["e2"].get("stunned"):
            fail("D3 Order", f"{got.get('reason') or got.get('reason_code')} e2 not stunned")
    # D4
    done = resolve_head(board(("chaos",)))
    whys = sorted(c.get("why") for c in conditional(done) if not c.get("held"))
    if not done.get("committed") or branches(done) != [] \
            or done["next_effect_state"]["players"]["p1"]["zones"]["rune_deck"] != ["rb", "rt"] \
            or whys != ["revealed_domain_not_fury", "revealed_domain_not_mind", "revealed_domain_not_order"]:
        fail("D4 other", f"{done.get('reason')} {branches(done) if done.get('committed') else ''} {whys}")
    # D5
    done = resolve_head(board(runes=0))
    steps = {e.get("effect_id"): e for e in ((done.get("trace") or {}).get("effect") or [])} if isinstance(done.get("trace"), dict) else {}
    whys = sorted(c.get("why") for c in conditional(done))
    if not done.get("committed") or branches(done) != [] or steps.get("rv", {}).get("reason") != "rune_deck_empty" \
            or whys != ["nothing_revealed"] * 3:
        fail("D5 empty", f"{done.get('reason')} {steps.get('rv', {}).get('reason')} {whys}")
    # D6
    done = resolve_head(board(("fury", "mind")))
    if done.get("committed") or done.get("reason_code") != "revealed_card_of_several_listed_domains" \
            or done.get("unsupported") is not True:
        fail("D6 several", f"{done.get('committed')} {done.get('reason_code')}")
    # V
    bad = copy.deepcopy(head())
    bad["conditional_triggers"][0]["condition"].pop("domain")
    if not validate_program(bad):
        fail("V shape", "revealed_domain without a Domain validated")
    bad = copy.deepcopy(head())
    bad["conditional_triggers"][0]["condition"]["effect_id"] = "rc"
    if not validate_program(bad):
        fail("V shape", "revealed_domain naming a recycle validated")
    bad = copy.deepcopy(REGISTRY["tf-fury"])
    bad["effects"][1]["affected"]["criteria"]["exclude_targets_of"] = "nothing"
    if not validate_program(bad):
        fail("V shape", "exclude_targets_of naming no earlier target validated")
    grammar = cg.load_grammar()
    rv = cg.compile_clause("Reveal the top rune of your rune deck.", grammar)
    fury = cg.compile_clause("Deal 2 to an enemy unit here and 1 to all other enemy units here.", grammar)
    if [(e["op"], e.get("from")) for e in rv.get("program_effects") or []] != [("reveal", "rune_deck_top")]:
        fail("V grammar", f"the reveal lowered to {rv.get('production_id')}")
    both = cg.compile_clause("Reveal the top rune of your rune deck, then recycle it.", grammar)
    if [(e["op"], e.get("revealed_by")) for e in both.get("program_effects") or []] != [("reveal", None), ("recycle", "rv")]:
        fail("V grammar", f"'..., then recycle it' lowered to {both.get('production_id')} {both.get('program_effects')}")
    if [e["op"] for e in fury.get("program_effects") or []] != ["deal_damage", "deal_damage"] \
            or (fury["program_effects"][1]["affected"]["criteria"].get("exclude_targets_of") != "dmg"):
        fail("V grammar", f"the Fury instruction lowered to {fury.get('production_id')}")
    return report()


def report() -> int:
    if errors:
        print("FAILED: a revealed rune and one Reflexive Trigger per Domain")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: the top rune revealed and recycled, its Domain noted as revealed; only that Domain's Reflexive Trigger is "
          "added, its target chosen at finalization - Fury 2 and 1 to every other enemy unit here, Mind a draw, Order a "
          "Stun; another Domain or an empty Rune Deck adds none, by name; a rune of two listed Domains refused (D1-D7, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
