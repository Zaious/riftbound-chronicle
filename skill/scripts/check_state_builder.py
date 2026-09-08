#!/usr/bin/env python3
"""Executable checks for state-assumption.v1, the S-01 minimum state builder.

The labelled fixtures carry the claim; this gate is what makes the claim cost
something. It proves four things the contract turns on:

  * a key outside the slot vocabulary is refused, and refused *because of that
    key* — the same draft without it builds, so nothing was quietly cleaned;
  * a question that cannot be built downgrades with the missing field named;
  * a correction re-runs the whole build and never patches the old artifact;
  * a buildable artifact's state is one the engine's own validator accepts, and
    its hash is the hash of the state that is actually carried.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import state_builder
from state_builder import (
    DOWNGRADE_REASONS,
    DOWNGRADE_TIERS,
    QUESTION_KINDS,
    SLOTS,
    StateBuilderError,
    apply_correction,
    build_state_assumption,
    validate_assumption_artifact,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
CASES = SKILL_DIR / "data" / "state_builder_cases.json"


def _contains(value, needle: str) -> bool:
    if isinstance(value, dict):
        return any(key == needle or _contains(child, needle) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains(child, needle) for child in value)
    return value == needle


def main() -> int:
    failures: list[str] = []
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases = payload["cases"]

    built: dict[str, dict] = {}
    seen_reasons: set[str] = set()
    stated_slots: set[str] = set()
    kind_outcomes: dict[str, set[bool]] = {kind: set() for kind in QUESTION_KINDS}

    # S-01b. The slots that are never assumed have no default and are required
    # by every kind that names them. Making one optional would either default
    # it — which is the assumption the rule forbids — or crash the builder on
    # its None; both are caught here, before any draft is read.
    for slot in state_builder.UNDEFAULTABLE:
        if SLOTS[slot]["default"] is not None:
            failures.append(f"slot {slot!r} is never assumed and must carry no default; "
                            f"it carries {SLOTS[slot]['default']!r}")
        for kind, profile in QUESTION_KINDS.items():
            if slot in profile["optional"]:
                failures.append(f"the {kind!r} kind lists {slot!r} as optional; a slot with no "
                                f"default is required or absent, never optional")
    if not any("combat" in p["required"] for p in QUESTION_KINDS.values()):
        failures.append("no kind requires the combat slot, so a Combat can never be stated")
    # The builder's mode vocabulary is the kernel's, by identity — not a copy
    # that happens to match today.
    import effect_ir as _effect_ir
    if state_builder.SANCTIONED_MODES is not _effect_ir.SANCTIONED_MODES:
        failures.append("state_builder.SANCTIONED_MODES must be effect_ir.SANCTIONED_MODES itself, "
                        "not a restatement")
    if not any("mode" in p["required"] for p in QUESTION_KINDS.values()):
        failures.append("no kind requires the mode slot, so a Mode of Play can never be stated")
    if not any("turn_effects" in p["required"] for p in QUESTION_KINDS.values()):
        failures.append("no kind requires the turn_effects slot, so a Stun can never be stated with its owner")

    for case in cases:
        case_id = case["case_id"]
        expected = case["expected"]
        try:
            artifact = build_state_assumption(question=case["question"],
                                              question_kind=case["question_kind"],
                                              draft=case["draft"])
        except StateBuilderError as exc:
            # The builder refusing by name is the right behaviour; a gate that
            # dies on it has the right exit code and says nothing.
            failures.append(f"{case_id}: the builder refused to run: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — any crash is reported by case, never raised
            # Third time this shape came up (S-01b, I-01, S-01c): a crash inside
            # one build must name the case, not end the report.
            failures.append(f"{case_id}: the builder crashed: {type(exc).__name__}: {exc}")
            continue
        built[case_id] = artifact

        if problems := validate_assumption_artifact(artifact):
            failures.append(f"{case_id}: its own artifact does not validate: {problems}")

        if artifact["buildable"] is not expected["buildable"]:
            failures.append(f"{case_id}: expected buildable={expected['buildable']}, "
                            f"got {artifact['buildable']} ({artifact['downgrade']})")
            continue

        if isinstance(case["draft"], dict):
            stated_slots |= set(case["draft"]) & set(SLOTS)
        if case["question_kind"] in kind_outcomes:
            kind_outcomes[case["question_kind"]].add(artifact["buildable"])

        if artifact["buildable"]:
            if not any(entry["origin"] == "derived" for entry in artifact["assumptions"]):
                failures.append(f"{case_id}: a built state always names what materialization derived")
            assumed = sorted(entry["slot"] for entry in artifact["assumptions"] if entry["origin"] == "default")
            if assumed != expected["assumed_slots"]:
                failures.append(f"{case_id}: assumed {assumed}, expected {expected['assumed_slots']}")
            continue

        downgrade = artifact["downgrade"]
        seen_reasons.add(downgrade["reason"])
        for field in ("tier", "reason"):
            if downgrade[field] != expected[field]:
                failures.append(f"{case_id}: {field} was {downgrade[field]!r}, expected {expected[field]!r}")
        for field in ("missing_fields", "rejected_fields"):
            if field in expected and downgrade[field] != expected[field]:
                failures.append(f"{case_id}: {field} was {downgrade[field]}, expected {expected[field]}")
        if downgrade["reason"] in state_builder.NAMES_MISSING and not downgrade["missing_fields"]:
            failures.append(f"{case_id}: a downgrade for a missing slot must name it")
        if downgrade["reason"] == "engine_rejected_state" and not downgrade["engine_errors"]:
            failures.append(f"{case_id}: an engine refusal carries the engine's own words")

    # A built Combat lists the record fields the kernel filled in, each as a
    # derived assumption, so the reader can see what the position rests on.
    for case in cases:
        run = built.get(case["case_id"])
        if not run or not run["buildable"] or "combat" not in (case["draft"] or {}):
            continue
        derived = {e["slot"] for e in run["assumptions"] if e["origin"] == "derived"}
        for name in ("combat_participants", "combat_battlefield_identity",
                     "combat_triggered_identities", "showdown_at_combat_battlefield"):
            if name not in derived:
                failures.append(f"{case['case_id']}: a built Combat must list the derived "
                                f"assumption {name!r}")

    # S-01c. A stated Mode of Play and stated points reach the state the
    # kernel reads, unchanged: the shape effect_ir validates and the scoring
    # kernel reads. A builder that accepted them and dropped them would hand
    # the kernel the very state that made it decline before S-01c.
    for case in cases:
        run = built.get(case["case_id"])
        draft = case["draft"] or {}
        if not run or not run["buildable"]:
            continue
        state = run["state"]
        if "mode" in draft and state.get("mode") != draft["mode"]:
            failures.append(f"{case['case_id']}: the stated mode {draft['mode']} is not in the "
                            f"built state (found {state.get('mode')!r})")
        if "points" in draft:
            found = {p: state["players"].get(p, {}).get("points") for p in draft["players"]}
            if found != draft["points"]:
                failures.append(f"{case['case_id']}: the stated points {draft['points']} are not "
                                f"in the built state (found {found})")
        # S-01d. A stated Stun reaches the object, and its turn effect reaches
        # the state in the kernel's own shape, with the turn the draft named.
        for unit in draft.get("units", []) or []:
            if unit.get("stunned") and not state["objects"].get(unit["object_id"], {}).get("stunned"):
                failures.append(f"{case['case_id']}: unit {unit['object_id']} was stated Stunned and is not "
                                f"in the built state")
        if "turn_effects" in draft:
            built_effects = state.get("turn_effects") or []
            if {(e["kind"], e["object_id"], e["controller"], e["turn_id"]) for e in built_effects} != \
                    {(e["kind"], e["object_id"], e["controller"], e["turn_id"]) for e in draft["turn_effects"]}:
                failures.append(f"{case['case_id']}: the stated turn effects are not in the built state")
            if state.get("turn_id") != draft.get("turn_id"):
                failures.append(f"{case['case_id']}: the stated turn {draft.get('turn_id')!r} is not the "
                                f"built state's turn ({state.get('turn_id')!r})")

    # Coverage. A kind that only ever builds, or only ever refuses, is a kind
    # whose boundary this fixture set has not located.
    for kind, outcomes in kind_outcomes.items():
        if outcomes != {True, False}:
            failures.append(f"question kind {kind!r} needs a case that builds and one that does not; saw {outcomes}")
    if missing_reasons := sorted(DOWNGRADE_REASONS - seen_reasons):
        failures.append(f"no case exercises the downgrade reasons {missing_reasons}")
    if missing_slots := sorted(set(SLOTS) - stated_slots):
        failures.append(f"no case states the slots {missing_slots}")

    # Contract 1, the counterexample that matters: the draft with a key outside
    # the vocabulary is refused for that key, and the same draft without it
    # builds. If the builder were sanitising, both would build and this pair
    # would be indistinguishable.
    dirty = next(case for case in cases if case["case_id"] == "SB-005")
    if "SB-005" not in built or "SB-002" not in built or "SB-001" not in built \
            or "SB-019" not in built:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s); the cases the later sections rely on did not build")
        return 1
    dirty_artifact = built["SB-005"]
    if dirty_artifact["buildable"] or (dirty_artifact["downgrade"] or {}).get("reason") != "schema_outside_field":
        failures.append("SB-005 must be refused as a schema-outside field, not cleaned and accepted")
    if dirty_artifact["state"] is not None:
        failures.append("SB-005 must not carry a state")
    if _contains(dirty_artifact["state"], "opponent_hand_count") or _contains(
            dirty_artifact["assumptions"], "opponent_hand_count"):
        failures.append("the rejected key leaked out of the refusal")
    cleaned = {k: v for k, v in dirty["draft"].items() if k != "opponent_hand_count"}
    if not build_state_assumption(question=dirty["question"], question_kind=dirty["question_kind"],
                                  draft=cleaned)["buildable"]:
        failures.append("the same draft without the offending key must build; "
                        "otherwise SB-005 proves nothing about that key")
    if not _contains(dirty_artifact["input_draft"], "opponent_hand_count"):
        failures.append("the refused draft is kept verbatim so the user can see what was sent")

    # Contract 2: a correction re-runs the whole build and leaves the old
    # artifact alone.
    original = built["SB-002"]
    before = copy.deepcopy(original)
    corrected = apply_correction(original, {"priority": "p2"})
    if original != before:
        failures.append("apply_correction mutated the artifact it was given")
    if not corrected["buildable"]:
        failures.append(f"the corrected build should succeed: {corrected['downgrade']}")
    elif corrected["state_hash"] == original["state_hash"]:
        failures.append("correcting Priority left the state unchanged")
    elif corrected["state"]["priority"] != "p2":
        failures.append("the correction did not reach the built state")
    if "priority" in {e["slot"] for e in corrected["assumptions"] if e["origin"] == "default"}:
        failures.append("a corrected slot is still reported as an assumption")
    if {"slot": "priority", "origin": "stated"} not in corrected["supplied"]:
        failures.append("a corrected slot must be reported as stated")
    if corrected["input_draft"] == original["input_draft"]:
        failures.append("the corrected artifact must carry the corrected draft")

    # A correction is held to the same contract as the first draft.
    dirty_correction = apply_correction(original, {"opponent_hand_count": 4})
    if dirty_correction["buildable"] or dirty_correction["downgrade"]["reason"] != "schema_outside_field":
        failures.append("a correction carrying a schema-outside key must be refused too")
    dropped = apply_correction(original, {}, drop=("turn_player",))
    if dropped["buildable"] or dropped["downgrade"]["missing_fields"] != ["turn_player"]:
        failures.append("dropping a required slot must downgrade and name it")
    try:
        apply_correction({"schema_version": "state-assumption.v1"}, {})
    except StateBuilderError:
        pass
    else:
        failures.append("correcting an invalid artifact must raise")

    # The validator is the artifact's own gate, so it has to refuse the shapes
    # a hand-written or drifting artifact would take.
    good = copy.deepcopy(built["SB-001"])
    mutations = [
        ("a state the engine rejects", lambda a: a["state"].__setitem__("turn_player", "p9")),
        ("a hash that is not this state's", lambda a: a.__setitem__("state_hash", "sha256:0")),
        ("buildable with no state", lambda a: (a.__setitem__("state", None), a.__setitem__("state_hash", None))),
        ("a required slot demoted to an assumption", lambda a: (
            a["supplied"].remove({"slot": "phase", "origin": "stated"}),
            a["assumptions"].append({"slot": "phase", "origin": "default", "value": "main",
                                     "material": True, "text": "The turn is in its main phase."}))),
        ("a slot both stated and assumed", lambda a: a["assumptions"].append(
            {"slot": "phase", "origin": "default", "value": "main", "material": True,
             "text": "The turn is in its main phase."})),
        ("an unreadable assumption", lambda a: a["assumptions"].__setitem__(
            0, {**a["assumptions"][0], "text": "  "}) if a["assumptions"] else None),
        ("a state family that does not match the kind", lambda a: a.__setitem__("state_family", "effect")),
        ("an unknown top-level field", lambda a: a.__setitem__("note", "trust me")),
    ]
    for label, mutate in mutations:
        candidate = copy.deepcopy(good)
        mutate(candidate)
        if not validate_assumption_artifact(candidate):
            failures.append(f"the validator accepts {label}")

    refused = copy.deepcopy(built["SB-019"])
    refusal_mutations = [
        ("a C reason relabelled as tier B", lambda a: a["downgrade"].__setitem__("tier", "B")),
        ("a refusal with no detail", lambda a: a["downgrade"].__setitem__("detail", "")),
        ("a refusal that quietly carries assumptions", lambda a: a["assumptions"].append(
            {"slot": "phase", "origin": "default", "value": "main", "material": True, "text": "assumed"})),
        ("an unknown reason", lambda a: a["downgrade"].__setitem__("reason", "just_because")),
        ("engine errors on a non-engine refusal", lambda a: a["downgrade"].__setitem__("engine_errors", ["nope"])),
    ]
    for label, mutate in refusal_mutations:
        candidate = copy.deepcopy(refused)
        mutate(candidate)
        if not validate_assumption_artifact(candidate):
            failures.append(f"the validator accepts {label}")

    # The reason-to-tier mapping is the contract, so nothing may be missing from
    # it and nothing may sit outside the two tiers the service knows.
    if set(DOWNGRADE_TIERS) != set(DOWNGRADE_REASONS):
        failures.append("every downgrade reason needs a tier")
    if set(DOWNGRADE_TIERS.values()) - {"B", "C"}:
        failures.append("a downgrade lands at tier B or C; there is no other place to go")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"\n{len(failures)} failure(s) across {len(cases)} state-builder cases")
        return 1

    builds = sum(1 for artifact in built.values() if artifact["buildable"])
    print(f"state-assumption.v1: {len(cases)} cases, {builds} build, {len(cases) - builds} refuse")
    print(f"downgrade reasons exercised: {len(seen_reasons)}/{len(DOWNGRADE_REASONS)}; "
          f"question kinds: {len(QUESTION_KINDS)}; slots: {len(SLOTS)}")
    print(f"validator mutations refused: {len(mutations) + len(refusal_mutations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
