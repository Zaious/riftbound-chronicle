#!/usr/bin/env python3
"""
Standing gate: the engine obeys selection-binding.v1, end to end.

There is an earlier gate over the reference implementation. Passing it proves
the checks are correct; it does not prove the ENGINE runs them, which is the
distinction Codex drew when authorising the eff_010 slice. So every case here
goes through `effect_ir.apply_program` with a real `engine-decisions.v1`
envelope, and reads the refusal out of the result the engine returns.

What is held:

  * the artifact carries the whole binding - the selected objects with their
    identities, the hash of the candidates AND the rule, the visibility, and
    the origin;
  * tampering with any of the five - candidates, rule, visibility, source,
    origin - is refused BY NAME, and the message says which one moved;
  * one selection fans out: "Choose a unit. Buff it. Kill it." runs, both
    consumers reading the same immutable result, while re-establishing the
    same selection is refused as a second selection;
  * `program_ancestry` is checked against nested program ids the ENGINE
    generated during this run, never against hand-written strings;
  * everything outside the slice - OPT, private sources, multi-select,
    ordered permutations - is refused as unsupported, not run half-bound.

    python skill/scripts/check_selection_binding_engine.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir  # noqa: E402
import selection_binding as sb  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import (CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program,  # noqa: E402
                       hash_value, object_identity, validate_program)
from engine_decisions import DECISIONS_VERSION, validate_engine_decisions  # noqa: E402

CHOICE = {"selection_kind": "single", "from": "board", "count": {"one": True},
          "visibility": "public", "criteria": {"kind": "unit", "controller_relation": "friendly"}}


def state_with_two_friendly_units():
    """base_state has a single friendly Unit, which the rules would choose
    without asking (359.3.e). A second one is what makes the choice real."""
    state = base_state()
    state["objects"]["u3"] = {"owner": "p1", "controller": "p1", "kind": "unit",
                              "base_might": 2, "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"].append("u3")
    return state


def program(*effects, program_id="p1"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": program_id, "controller": "p1", "effects": list(effects)}


def choose(selection_id="s1", effect_id="choose", decision_ref="d1", choice=None):
    return {"op": "establish_selection", "effect_id": effect_id, "selection_id": selection_id,
            "decision_ref": decision_ref, "choice": copy.deepcopy(choice or CHOICE)}


def refers(op, selection_id="s1", effect_id=None, **extra):
    return {"op": op, "effect_id": effect_id or op,
            "target": {"selection_ref": selection_id, "chosen_zone_class": "board", "kind": "unit"},
            **extra}


def envelope(state, chosen, *, selection_id="s1", decision_ref="d1", program_id="p1",
             effect_id="choose", binding_overrides=None, drop_binding=False, choice=None):
    """A real engine-decisions.v1 envelope, with the binding the artifact
    carries. `binding_overrides` is how a tampered artifact is built."""
    spec = copy.deepcopy(choice or CHOICE)
    candidates, identities = effect_ir.choice_candidates(state, spec, "p1")
    binding = {
        "selection_id": selection_id,
        "candidate_set_hash": sb.candidate_set_hash(spec, candidates, identities),
        "visibility": "public",
        "source": spec["from"],
        "selection_kind": spec["selection_kind"],
        "count": spec["count"],
        "origin": {"program_id": program_id, "effect_id": effect_id},
    }
    if binding_overrides:
        binding = {**binding, **binding_overrides}
    entry = {"decision_id": decision_ref, "stage": "play_declaration", "kind": "target_selection",
             "controller": "p1", "value": list(chosen),
             "selection_identities": {c: object_identity(state, c) for c in chosen}}
    if not drop_binding:
        entry["binding"] = binding
    return {"schema_version": DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": [entry]}


def main() -> int:
    errors: list[str] = []

    def fail(label, detail):
        errors.append(f"{label}: {detail}")

    def run(state, prog, decisions):
        problems = validate_program(prog) + validate_engine_decisions(decisions or {"schema_version": DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": []})
        if problems:
            return {"_schema_problems": problems}
        return apply_program(state, prog, decisions=decisions)

    def expect_refusal(label, result, code):
        if result.get("_schema_problems"):
            return fail(label, f"the fixture did not even validate: {result['_schema_problems']}")
        if result.get("committed") is not False:
            return fail(label, f"expected the refusal {code}, but the program committed")
        if result.get("reason_code") != code:
            return fail(label, f"expected reason_code {code}, got {result.get('reason_code')!r} "
                               f"({result.get('reason') or result.get('errors')})")

    state = state_with_two_friendly_units()

    # ---- the artifact carries the whole binding, and one selection fans out --
    fan_out = program(choose(), refers("buff"), refers("kill"))
    result = run(state, fan_out, envelope(state, ["u1"]))
    if result.get("_schema_problems"):
        fail("fan-out", f"the fixture did not validate: {result['_schema_problems']}")
    elif result.get("committed") is not True:
        fail("fan-out", f"'Choose a unit. Buff it. Kill it.' did not run: "
                        f"{result.get('reason') or result.get('errors')}")
    else:
        bound = (result.get("selection_bindings") or {}).get("s1")
        if bound is None:
            fail("fan-out", "the result carries no selection_bindings; the binding is in the engine's head, not the artifact")
        else:
            missing = [k for k in ("selection_result_ref", "candidate_set_hash", "visibility",
                                   "origin", "value", "selection_identities", "order_index")
                       if k not in bound]
            if missing:
                fail("fan-out", f"the recorded binding is incomplete: {missing} absent")
            if bound.get("origin", {}).get("program_id") != "p1":
                fail("fan-out", f"origin names {bound.get('origin')}, not the program that chose")
        consumers = [e for e in result["trace"] if e.get("effect_id") in {"buff", "kill"}]
        if len(consumers) != 2:
            fail("fan-out", f"expected buff and kill in the trace, saw {[e.get('effect_id') for e in result['trace']]}")
        elif any(e.get("outcome") not in effect_ir.PERFORMED_OUTCOMES for e in consumers):
            fail("fan-out", f"a consumer did not run: {[(e.get('effect_id'), e.get('outcome')) for e in consumers]}")
        elif len({e.get("object_id") for e in consumers}) != 1:
            fail("fan-out", "the two consumers acted on different objects; they read one immutable result")

    # ---- the decision is genuinely required ---------------------------------
    empty = {"schema_version": DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": []}
    result = run(state, program(choose(), refers("buff")), empty)
    if result.get("committed") is not False or not result.get("choice_required"):
        fail("no decision", f"a missing choice was not requested back: {result.get('reason')}")

    # ---- tampering, one vector at a time ------------------------------------
    tampers = [
        ("candidates", {"candidate_set_hash": "sha256:" + "0" * 64}, sb.CANDIDATES_CHANGED),
        ("rule: count", {"count": {"exactly": 2}}, sb.CANDIDATES_CHANGED),
        ("rule: selection_kind", {"selection_kind": "unordered_set"}, sb.CANDIDATES_CHANGED),
        ("source", {"source": "hand"}, sb.CANDIDATES_CHANGED),
        ("visibility", {"visibility": "private_to_chooser"}, sb.VISIBILITY_MISMATCH),
        ("origin: program", {"origin": {"program_id": "somebody-elses-program", "effect_id": "choose"}}, sb.ORIGIN_UNBOUND),
        ("origin: effect", {"origin": {"program_id": "p1", "effect_id": "some-other-clause"}}, sb.ORIGIN_UNBOUND),
        ("origin: selection_id", {"selection_id": "s9"}, sb.ORIGIN_UNBOUND),
    ]
    for label, override, code in tampers:
        result = run(state, program(choose(), refers("buff")),
                     envelope(state, ["u1"], binding_overrides=override))
        expect_refusal(f"tampered {label}", result, code)

    # A candidate set that really did change: the hash is taken over a board
    # with a third Unit that is not there when the program runs.
    wider = state_with_two_friendly_units()
    wider["objects"]["u4"] = dict(wider["objects"]["u3"])
    wider["players"]["p1"]["zones"]["base"].append("u4")
    stale = sb.candidate_set_hash(CHOICE, *effect_ir.choice_candidates(wider, copy.deepcopy(CHOICE), "p1"))
    result = run(state, program(choose(), refers("buff")),
                 envelope(state, ["u1"], binding_overrides={"candidate_set_hash": stale}))
    expect_refusal("a hash taken over a different board", result, sb.CANDIDATES_CHANGED)

    # ---- an unbound decision cannot establish anything -----------------------
    result = run(state, program(choose(), refers("buff")), envelope(state, ["u1"], drop_binding=True))
    expect_refusal("no binding on the decision", result, sb.ORIGIN_UNBOUND)

    # ---- references that do not hold ----------------------------------------
    result = run(state, program(choose(), refers("buff", selection_id="s2")), envelope(state, ["u1"]))
    expect_refusal("reference to a selection never established", result, sb.ORIGIN_UNBOUND)

    result = run(state, program(refers("buff"), choose()), envelope(state, ["u1"]))
    expect_refusal("reference before the selection is made", result, sb.ORIGIN_UNBOUND)

    # ---- making the same selection twice ------------------------------------
    twice = program(choose(), refers("buff"), choose(effect_id="choose-again", decision_ref="d2"))
    decisions = envelope(state, ["u1"])
    second = copy.deepcopy(decisions["decisions"][0])
    second["decision_id"] = "d2"
    second["binding"] = {**second["binding"], "origin": {"program_id": "p1", "effect_id": "choose-again"}}
    decisions["decisions"].append(second)
    expect_refusal("the same selection established twice", run(state, twice, decisions), sb.ALREADY_CONSUMED)

    # ---- everything outside the slice is refused, not run half-bound ---------
    outside = [
        ("OPT / up to", {**CHOICE, "selection_kind": "unordered_set", "count": {"up_to": 2}}),
        ("any number", {**CHOICE, "selection_kind": "unordered_set", "count": {"any_number": True}}),
        ("multi-select", {**CHOICE, "selection_kind": "unordered_set", "count": {"exactly": 2}}),
        ("ordered permutation", {"selection_kind": "ordered_permutation", "from": "main_deck_top",
                                 "top": 2, "count": {"any_number": True}}),
        ("a private source", {"selection_kind": "single", "from": "hand", "count": {"one": True}}),
    ]
    # Where each refusal came from, counted rather than assumed. A shape the
    # validator rejects never reaches the slice check, so its assertion would
    # not run; an unexercised assertion is a failure, not a pass.
    refused_at = {"validator": 0, "resolution": 0}
    for label, spec in outside:
        prog = program(choose(choice=spec), refers("buff"))
        problems = validate_program(prog)
        if problems:
            refused_at["validator"] += 1
            continue
        refused_at["resolution"] += 1
        result = apply_program(state, prog, decisions=envelope(state, ["u1"]))
        if result.get("committed") is not False:
            fail(f"outside the slice: {label}", "it ran; only single/public/board/one is wired")
        elif not result.get("unsupported") or "selection_binding_slice" not in (result.get("reason") or ""):
            fail(f"outside the slice: {label}",
                 f"expected an unsupported refusal naming the slice, got "
                 f"{result.get('reason_code') or result.get('reason') or result.get('errors')}")
    if refused_at["resolution"] == 0:
        fail("outside the slice", "every unwired shape was stopped by the validator, so the slice "
                                  "check itself was never exercised")

    # ---- program_ancestry against ids the ENGINE generated -------------------
    # Nested programs are named by apply_program itself. Recording the names it
    # actually builds is the only way to know the parser matches the engine;
    # a hand-written "expand:p1:e1" would only prove the parser matches me.
    seen_ids: list[str] = []
    original = effect_ir.apply_program

    def recording(state_, program_, **kwargs):
        if isinstance(program_, dict) and isinstance(program_.get("program_id"), str):
            seen_ids.append(program_["program_id"])
        return original(state_, program_, **kwargs)

    effect_ir.apply_program = recording
    try:
        nested_state = state_with_two_friendly_units()
        # `targets` over two objects -> expand:{parent}:{effect_id}
        recording(nested_state, program(
            {"op": "kill", "effect_id": "sweep",
             "targets": {"min": 2, "max": 2, "selectors": [
                 {"object_id": "u1", "chosen_zone_class": "board", "kind": "unit"},
                 {"object_id": "u3", "chosen_zone_class": "board", "kind": "unit"}]}},
            program_id="parent-program"))
        # `affected` over a criteria -> affected:{parent}:{effect_id}. It reads
        # Battlefields only, never Bases, so the Units have to stand on one.
        on_battlefield = state_with_two_friendly_units()
        for unit in ("u1", "u3"):
            on_battlefield["players"]["p1"]["zones"]["base"].remove(unit)
            on_battlefield["battlefields"]["bf1"]["objects"].append(unit)
            on_battlefield["objects"][unit]["exhausted"] = True
        recording(on_battlefield, program(
            {"op": "ready", "effect_id": "wake",
             "affected": {"criteria": {"location": "any_battlefield", "kind": "unit"}}},
            program_id="parent-program"))
    finally:
        effect_ir.apply_program = original

    generated = sorted({pid for pid in seen_ids if pid != "parent-program"})
    for prefix in ("expand:", "affected:"):
        if not any(pid.startswith(prefix) for pid in generated):
            fail("engine-generated nesting",
                 f"the engine produced no {prefix} program in this run; the ancestry check "
                 f"would have been vacuous. Saw {generated}")
    for pid in generated:
        ancestry = sb.program_ancestry(pid)
        if ancestry[0] != pid:
            fail("ancestry", f"{pid!r} does not begin with itself: {ancestry}")
        if "parent-program" not in ancestry:
            fail("ancestry", f"the engine-generated id {pid!r} does not resolve to its real parent "
                             f"'parent-program': {ancestry}")

    # `simultaneous:{effect_id}` carries no parent id at all. It must yield no
    # ancestor rather than inventing one out of an effect id with a colon in it.
    for made_up in ("simultaneous:kill", "simultaneous:kill:u1"):
        if sb.program_ancestry(made_up) != [made_up]:
            fail("ancestry", f"{made_up!r} has no parent in its name, yet ancestry claims "
                            f"{sb.program_ancestry(made_up)}")

    if errors:
        print("FAILED: selection binding, engine end-to-end")
        for problem in errors:
            print(f"  - {problem}")
        return 1
    print(f"selection binding holds in the engine: the artifact carries the binding, "
          f"{len(tampers) + 1} tampered artifacts are refused by name, one selection fans out to "
          f"two consumers, {refused_at['resolution']} unwired shapes are refused at resolution "
          f"({refused_at['validator']} by the validator), and program_ancestry resolves "
          f"{len(generated)} engine-generated nested ids ({', '.join(generated)}) to their real parent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
