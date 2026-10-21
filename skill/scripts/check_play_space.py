#!/usr/bin/env python3
"""Gate: play_card and activate_ability as full declarations (package 13, C2; GPT 2026-10-15 rulings 1-3).

On a synthetic catalogue - a one-target spell, an up-to-two-targets spell, a modal spell, a unit with Accelerate, a
Champion, a Hidden spell hidden last turn, a Gear with three activated abilities (an [Exhaust] one, one whose cost
kills a unit the payer names, one whose cost discards) - every state is an environment state:

  F1 full        legal_action with the catalogue lists every action with every choice made: the spell once per legal
                 target and never at an illegal one; the two-target spell once per set of 0..2 friendly units; the modal
                 spell once per mode (and per target of the mode that has one); the Accelerate unit with and without
                 Accelerate at each location it may enter; the Champion from the Champion Zone; the Hidden spell from
                 the facedown zone; each ability, the kill cost once per unit it may kill, the discard once per card
  F2 the same    each family's list is exactly D(s) - every object as the card, every source, location and timing
                 source the declaration admits, every decision answered with every value of its kind over the state's
                 own sets - that the procedure commits (action_space.differential), key for key
  F3 unproved    a program whose target the module cannot find, a request it reads no domain for, and a space over its
                 cap each make the family abstain by name (unproved:...), never a partial list
  F5 one target  the one-target spell with no target, or with two, is refused as target_count_out_of_range (found by
                 F2: it was committed with none)
  F7 unasked     (PACKAGE13 ruling 3) D(s) is read off the program and the declaration contract, not off the
                 procedure's requests: with the procedure made to stop asking for the one-target spell's target (it takes
                 a default), the enumerator loses the other target and the differential names it missing
  F8 cross-check the procedure's requests check the contract: a contract missing the Accelerate slot stops D(s) by name
  F6 closure     every choice field of a play declaration (action_space.FIELD_CLASSES) has a generator or a named reason
                 it is not a discretionary choice; every play source (play_transaction.PLAY_SOURCES) is generated or named;
                 every request the procedure makes (DECISION_REASONS) is answered (DECIDED) or named (REQUESTS_LEFT)
  F4 the state   a state not of the catalogue's environment (an object without card_ref) abstains as
                 not_an_environment_state; without a catalogue the families are as before

    python skill/scripts/check_play_space.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_space as A  # noqa: E402
import closed_environment as CE  # noqa: E402
import legal_action as la  # noqa: E402
import play_space as PS  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, RULE_NUMBERING, validate_state  # noqa: E402

errors: list[str] = []
counts: dict[str, int] = {}
DRAW = {"effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1}]}
ZAP = {"op": "deal_damage", "effect_id": "dmg", "amount": 1,
       "target": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"}}


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def spell(energy=1, **extra):
    return {"kind": "spell", "printed_cost": {"energy": energy, "power": {}}, "domains": ["fury"], **extra}


def catalogue() -> dict:
    value = {
        "schema_version": CE.CATALOGUE_VERSION,
        "environment": {"format": "1v1", "core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "rule_numbering": RULE_NUMBERING,
                        "card_pool": "synthetic"},
        "cards": {
            "Zap": {"object": spell(), "programs": {"play": {"effects": [ZAP]}}},
            "Twin": {"object": spell(), "programs": {"play": {"effects": [{
                "op": "modify_might", "effect_id": "mm", "amount": 1, "duration": "this_turn", "source": "$chain_item",
                "targets": {"min": 0, "max": 2, "decision_ref": "t",
                            "restrictions": {"chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"}}}]}}},
            "Choice": {"object": spell(), "programs": {"play": {"modal": {
                "choose": 1, "timing": "play_declaration", "decision_ref": "mode",
                "options": [{"option_id": "m1", "effects": DRAW["effects"]}, {"option_id": "m2", "effects": [ZAP]}]}}}},
            "Grunt": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1,
                                 "domains": ["fury"], "keywords": ["accelerate"]}},
            "Champ": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 2, "domains": ["fury"]}},
            "Sneak": {"object": spell(hidden=True), "programs": {"play": {"effects": [ZAP]}}},
            "Pawn": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1, "domains": ["calm"]}},
            "Guard": {"object": {"kind": "unit", "printed_cost": {"energy": 1, "power": {}}, "base_might": 1, "domains": ["calm"],
                                 "keywords": ["deflect"]}},
            "Totem": {"object": {"kind": "gear", "printed_cost": {"energy": 1, "power": {}}, "domains": ["calm"]},
                      "activated_abilities": {
                          "a1": {"cost": {"energy": 0, "power": {}, "exhaust": True}, "effect_program_id": "draw"},
                          "a2": {"cost": {"energy": 0, "power": {}, "additional": [
                              {"cost_id": "text-cost", "mandatory": True, "payment": {"kind": "kill", "object_kinds": ["unit"]}}]},
                              "effect_program_id": "draw"},
                          "a3": {"cost": {"energy": 1, "power": {}, "additional": [
                              {"cost_id": "text-cost", "mandatory": True, "payment": {"kind": "discard", "amount": 1}}]},
                              "effect_program_id": "draw"}},
                      "programs": {"draw": DRAW}},
            "Field": {"object": {"kind": "battlefield"}},
        },
        "catalogue_hash": "",
    }
    value["catalogue_hash"] = CE.catalogue_hash(value)
    return value


def environment(cat, placed: list[tuple[str, str, str, str]]) -> dict:
    """(object id, card, owner, zone | 'bf1' | 'facedown') each; p1 to act with 3 Energy and 1 fury Power."""
    state = {"schema_version": "riftbound-effect-state.v1", "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
             "players": {p: {"zones": {"main_deck": [], "hand": [], "trash": [], "banishment": [], "base": [],
                                       "rune_deck": [], "champion_zone": []},
                             "resources": {"energy": 0, "power": {}}, "points": 0} for p in ("p1", "p2")},
             "objects": {}, "battlefields": {"bf1": CE.place_battlefield(cat, "Field", "bf1")},
             "replacement_effects": [], "mode": {"victory_score": 8}, "turn_id": "turn-1"}
    state["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": []}
    for object_id, ref, owner, zone in placed:
        state["objects"][object_id] = CE.place(cat, ref, owner=owner, object_id=object_id)
        if zone == "bf1":
            state["battlefields"]["bf1"]["objects"].append(object_id)
        elif zone == "facedown":
            state["battlefields"]["bf1"]["facedown"]["cards"].append(
                {"object_id": object_id, "controller": owner, "hidden_on_turn": "turn-0"})
        else:
            state["players"][owner]["zones"][zone].append(object_id)
    present = [o for o in state["battlefields"]["bf1"]["objects"] if state["objects"][o]["kind"] == "unit"]
    if present:
        state["battlefields"]["bf1"]["controller"] = state["objects"][present[0]]["owner"]
    state["players"]["p1"]["resources"] = {"energy": 3, "power": {"fury": 1}}
    return state


def enumerate_for(state, cat, actor="p1", timing=None):
    observation = la.build_observation(
        perspective={"p1": "player1", "p2": "player2"}[actor], source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard", "card_data_version": "synthetic"},
        timing_state=timing or fixture(), effect_state=state, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"})
    return la.enumerate_actions(observation, actor, catalogue=cat)


def family(result, name):
    return next(f for f in result["enumeration"]["families"] if f["family"] == name)


def keys(result, name, card):
    return sorted(A.canonical_action_key(a)["declaration"].get("entry_location", {}).get("kind", "-") + "|" +
                  ",".join(f"{d['kind']}={d['value']}" for d in A.canonical_action_key(a)["decisions"])
                  for a in A.enumerated_actions(result, name) if a["declaration"]["card"] == card)


BOARDS = {
    "targets": [("z", "Zap", "p1", "hand"), ("w", "Twin", "p1", "hand"), ("a", "Pawn", "p1", "base"),
                ("b", "Pawn", "p2", "bf1")],
    "plays": [("m", "Choice", "p1", "hand"), ("g", "Grunt", "p1", "hand"), ("c", "Champ", "p1", "champion_zone"),
              ("s", "Sneak", "p1", "facedown"), ("a", "Pawn", "p1", "base"), ("f", "Pawn", "p1", "bf1")],
    "abilities": [("t", "Totem", "p1", "base"), ("a", "Pawn", "p1", "base"), ("a2", "Pawn", "p1", "base"),
                  ("h", "Pawn", "p1", "hand"), ("b", "Pawn", "p2", "base")],
}


def main() -> int:
    cat = catalogue()
    if CE.validate_catalogue(cat):
        fail("setup", f"the catalogue does not validate: {CE.validate_catalogue(cat)}")
        return report()
    results = {}
    for name, placed in BOARDS.items():
        state = environment(cat, placed)
        problems = validate_state(state) + CE.environment_problems(state, cat)
        if problems:
            fail("setup", f"{name}: {problems[:3]}")
            return report()
        results[name] = (state, enumerate_for(state, cat))
    # F1
    state, got = results["targets"]
    for name in ("play_card", "activate_ability"):
        if family(got, name)["status"] != "enumerated":
            fail("F1 full", f"{name} on the targets board: {family(got, name)}")
    if keys(got, "play_card", "z") != ["-|target_selection=['a']", "-|target_selection=['b']"]:
        fail("F1 full", f"the one-target spell: {keys(got, 'play_card', 'z')}")
    if keys(got, "play_card", "w") != ["-|target_selection=['a']", "-|target_selection=[]"]:
        fail("F1 full", f"the up-to-two spell over its one friendly unit: {keys(got, 'play_card', 'w')}")
    state, got = results["plays"]
    wanted = {"m": ["-|mode_selection=m1", "-|mode_selection=m2,target_selection=['a']",
                    "-|mode_selection=m2,target_selection=['f']"],
              # its Base, or the Battlefield its controller controls (Core 355.2)
              "g": ["base|optional_choice=False", "base|optional_choice=True", "battlefield|optional_choice=False",
                    "battlefield|optional_choice=True"],
              "c": ["base|", "battlefield|"]}
    for card, want in wanted.items():
        if keys(got, "play_card", card) != want:
            fail("F1 full", f"{card}: {keys(got, 'play_card', card)} != {want}")
    if sorted(k.split("|")[1] for k in keys(got, "play_card", "s")) != ["target_selection=['a']", "target_selection=['f']"]:
        fail("F1 full", f"the Hidden spell from facedown: {keys(got, 'play_card', 's')}")
    state, got = results["abilities"]
    by_ability = {}
    for a in A.enumerated_actions(got, "activate_ability"):
        key = A.canonical_action_key(a)
        paid = [c["payment"].get("object_id") for c in key["declaration"]["cost"].get("additional", [])
                if c["payment"].get("kind") == "kill"]
        chosen = [d["value"] for d in key["decisions"] if d["kind"] == "card_selection"]
        by_ability.setdefault(a["declaration"]["activation"]["ability_id"], []).append((paid, chosen))
    if sorted(by_ability.get("t:a1", [])) != [([], [])] or sorted(by_ability.get("t:a2", [])) != [(["a"], []), (["a2"], [])] \
            or sorted(by_ability.get("t:a3", [])) != [([], [])]:     # one card in hand: the discard is forced
        fail("F1 full", f"the abilities: {by_ability}")
    # F2
    for name, (state, got) in results.items():
        for fam in ("play_card", "activate_ability"):
            diff = A.differential(fam, fixture(), state, "p1", got, catalogue=cat)
            counts[f"{name}/{fam}"] = diff.get("accepted", 0)
            if not diff["complete"]:
                fail("F2 the same", f"{name} {fam}: stopped {diff.get('stopped')} missing {diff.get('missing', [])[:2]} "
                                    f"extra {diff.get('extra', [])[:2]}")
    # F3
    state = results["targets"][0]
    for label, run in (("a target the module finds no selector for", lambda: _blind(state, cat)),
                       ("a request with no domain", lambda: _without_domain(state, cat)),
                       ("over the cap", lambda: _capped(state, cat))):
        got = run()
        if got["status"] != "unproved" or got["actions"] or not got["reason"]:
            fail("F3 unproved", f"{label}: {got['status']} with {len(got['actions'])} actions")
    # F5
    state = results["targets"][0]
    declaration, program = next((d, p) for d, p in PS.play_skeletons(state, cat, "p1") if d["card"] == "z")
    import play_transaction as PT
    from effect_ir import hash_value
    for chosen in ([], ["a", "b"]):
        envelope = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": [
            {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
             "value": chosen, "selection_identities": {o: f"{o}@0" for o in chosen}}]}
        got = PT.play_card(fixture(), state, declaration, engine_decisions=envelope, effect_program=program)
        if got.get("committed") or got.get("reason_code") != "target_count_out_of_range":
            fail("F5 one target", f"{len(chosen)} targets: {got.get('committed')} {got.get('reason_code')}")
    # F7: the procedure stops asking for Zap's target and takes a default - the enumerator, led by its requests, loses
    # the other target; D(s), read off the program, still has it (GPT PACKAGE13 ruling 3)
    import engine_decisions as ED
    state = results["targets"][0]
    original = ED.target_selection

    def silent(decisions, decision_id, _original=original):
        found = _original(decisions, decision_id)
        if found is None and decision_id == "t":
            return {"decision_id": "t", "stage": "play_declaration", "kind": "target_selection", "controller": "p1",
                    "value": ["a"], "selection_identities": {"a": "a@0"}}
        return found
    ED.target_selection = silent
    try:
        got = enumerate_for(state, cat)
        diff = A.differential("play_card", fixture(), state, "p1", got, catalogue=cat)
    finally:
        ED.target_selection = original
    lost = [m for m in diff.get("missing") or [] if m["declaration"].get("card") == "z"]
    if diff["complete"] or not lost:
        fail("F7 unasked", f"a target the procedure stopped asking for was not found missing: {diff.get('stopped')} "
                           f"{diff.get('missing', [])[:1]}")
    # F8: a contract that misses a slot the procedure asks for (Accelerate) stops D(s) by name
    state = results["plays"][0]
    got = enumerate_for(state, cat)
    original = A.contract_slots

    def missing_accelerate(*args, _original=original):
        return {mode: [slot for slot in slots if slot[0] != "accelerate"] for mode, slots in _original(*args).items()}
    A.contract_slots = missing_accelerate
    try:
        diff = A.differential("play_card", fixture(), state, "p1", got, catalogue=cat)
    finally:
        A.contract_slots = original
    if diff["complete"] or "contract does not show" not in str(diff.get("stopped")):
        fail("F8 cross-check", f"a slot missing from the contract: {diff.get('stopped')}")
    # F6
    choice = {k for k, v in A.FIELD_CLASSES["play"].items() if v == A.CHOICE}
    generated = {k for k, v in PS.FIELD_GENERATORS.items() if v}
    if set(PS.FIELD_GENERATORS) != choice or set(PS.NOT_DISCRETIONARY) != choice - generated:
        fail("F6 closure", f"choice fields {sorted(choice)}; generated {sorted(generated)}; named {sorted(PS.NOT_DISCRETIONARY)}")
    import play_transaction as PT
    if set(PS.SOURCES) != set(PT.PLAY_SOURCES):
        fail("F6 closure", f"play sources {sorted(PT.PLAY_SOURCES)} != {sorted(PS.SOURCES)}")
    requests = set(PT.DECISION_REASONS)
    if requests - set(PS.DECIDED) != set(PS.REQUESTS_LEFT) or set(PS.REQUESTS_LEFT) & set(PS.DECIDED):
        fail("F6 closure", f"requests {sorted(requests)}; answered {sorted(PS.DECIDED)}; named {sorted(PS.REQUESTS_LEFT)}")
    # F4
    state = copy.deepcopy(results["targets"][0])
    state["objects"]["a"].pop("card_ref")
    got = enumerate_for(state, cat)
    if family(got, "play_card").get("reason_code") != "not_an_environment_state":
        fail("F4 the state", f"an uncatalogued object: {family(got, 'play_card')}")
    plain = la.enumerate_actions(la.build_observation(
        perspective="player1", source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard", "card_data_version": "synthetic"},
        timing_state=fixture(), effect_state=results["targets"][0], facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"}), "p1")
    if family(plain, "activate_ability").get("reason_code") != "capability_missing:activated_ability_catalogue":
        fail("F4 the state", f"without a catalogue: {family(plain, 'activate_ability')}")
    f9_refused_targets(results)
    f10_deflect(cat)
    return report()


def f10_deflect(cat) -> None:
    """F10 (package 15, found by the corpus: Cleave choosing a Unit with [Deflect]): choosing an opposing Unit with
    Deflect 1 costs [A] more (Core 809.1.c) - an event of the choice the procedure names, its values by the rule. With
    Power of one Domain left the payment is forced and no decision is part of the play; with two, each Domain is a play.
    Both equal D(s)."""
    for power, want in (({"fury": 1}, 0), ({"fury": 1, "calm": 1}, 2)):
        state = environment(cat, [("z", "Zap", "p1", "hand"), ("b", "Guard", "p2", "bf1")])
        state["players"]["p1"]["resources"] = {"energy": 3, "power": dict(power)}
        got = enumerate_for(state, cat)
        diff = A.differential("play_card", fixture(), state, "p1", got, cat)
        allocations = [d for a in A.enumerated_actions(got, "play_card") if a["declaration"]["card"] == "z"
                       for d in a.get("decisions") or [] if d["kind"] == "resource_allocation"]
        if not diff["complete"] or len(allocations) != want:
            fail("F10 deflect", f"Power {power}: {diff.get('stopped')} missing {len(diff.get('missing') or [])} extra "
                                f"{len(diff.get('extra') or [])}, {len(allocations)} allocations (want {want})")
        counts[f"F10 {len(power)} domain(s)"] = len(allocations)


def f9_refused_targets(results) -> None:
    """F9 (package 15, GPT PACKAGE15 ruling 2): the target screening's refusals are the procedure's own - for each
    selector and each object, play_transaction.refused_targets names it exactly when _check_play_targets refuses it as
    that selector's choice (target_illegal_at_play); a selector that does not target, and one that reads another
    instruction's selection, refuse none (the check does not test them at play)."""
    import effect_ir
    import play_transaction as PT
    selectors = {
        "a unit": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit"},
        "a friendly unit": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly"},
        "an enemy unit": {"decision_ref": "t", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "enemy"},
        "a card in a hand": {"decision_ref": "t", "chosen_zone_class": "hand"},
        "another's selection": {"decision_ref": "t", "selection_ref": "earlier"},
    }
    compared = 0
    for board in ("targets", "plays", "abilities"):
        state = results[board][0]
        for name, template in selectors.items():
            program = {"schema_version": "riftbound-effect-program.v1", "ruleset": state["ruleset"], "program_id": "f9",
                       "controller": "p1", "effects": [{"op": "deal_damage", "effect_id": "dmg", "amount": 1, "target": template}]}
            claimed = PT.refused_targets(state, "p1", program, template)
            checked = set()
            for object_id in sorted(state["objects"]) + sorted(state["battlefields"]):
                envelope ={"schema_version": "engine-decisions.v1", "input_hash": effect_ir.hash_value(state),
                            "decisions": [A._entry("t", "target_selection", [object_id], "p1", state)]}
                try:
                    PT._check_play_targets(state, "p1", program, envelope)
                except PT.PlayError as exc:
                    if exc.reason_code == "target_illegal_at_play":
                        checked.add(object_id)
                compared += 1
            if claimed != checked:
                fail("F9 refused", f"{board}, {name}: refused_targets {sorted(claimed)} but the check refuses {sorted(checked)}")
            if name in ("another's selection",) and claimed:
                fail("F9 refused", f"{board}, {name}: a selection read at resolution refuses {sorted(claimed)} at play")
    counts["F9 compared"] = compared


def _blind(state, cat):
    original = PS._templates
    PS._templates = lambda program: {}                     # the module finds no selector for the request
    try:
        return PS.enumerate_family("play_card", fixture(), state, "p1", cat)
    finally:
        PS._templates = original


def _without_domain(state, cat):
    original = dict(PS.DECIDED)
    PS.DECIDED.pop("target_selection_required")
    try:
        return PS.enumerate_family("play_card", fixture(), state, "p1", cat)
    finally:
        PS.DECIDED.clear()
        PS.DECIDED.update(original)


def _capped(state, cat):
    original = PS.CALL_CAP
    PS.CALL_CAP = 2
    try:
        return PS.enumerate_family("play_card", fixture(), state, "p1", cat)
    finally:
        PS.CALL_CAP = original


def report() -> int:
    if errors:
        print("FAILED: play and activation as full declarations")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: with the catalogue every play and activation is listed with every choice made - targets, sets of targets, "
          f"modes, Accelerate, entry locations, the Champion Zone and facedown sources, payer-named and selected costs - "
          f"and each list equals what the procedure commits over D(s) {counts}; an unreadable target, a request with no "
          f"domain and the cap abstain by name; a single target is one object; every choice field, source and request is generated or named; a slot the procedure stops asking for is "
          f"still in D(s), and a slot missing from the contract stops it; a state outside the environment abstains (F1-F8)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
