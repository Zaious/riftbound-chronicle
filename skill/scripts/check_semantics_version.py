#!/usr/bin/env python3
"""Gate: the Core whose behaviour the engine executes is one explicit, checked field (package 12, 2026-10-14).

`ruleset.core` names the Core Rules the engine EXECUTES - 2026-10-09, in effect 2026-10-16. The rule locators it cites
are numbered by the 2026-10-09 document too since C3 (package 16, 2026-10-22; until then by 2026-07-16); that numbering
is still its own field (RULE_NUMBERING, engine_check.rule_numbering, the capability manifest's rule_numbering) and never
stands in for the executed Core.

  V1 constants    effect_ir and rules_core agree: executed Core 2026-10-09, in effect 2026-10-16, locators numbered
                  2026-10-09; the capability manifest states both, apart
  V2 M1 new       "Move a friendly unit and ready it" with the Move forbidden, labelled 2026-10-09: the Move is negated
                  and the unit is readied (Core 2026-10-09 359.3.e.6, 359.3.e.14.a/b)
  V3 M1 old       the same state and program labelled 2026-07-16: refused - an older label never runs the newer
                  behaviour, and nothing is applied
  V4 M5 new       a spell taken by Mystic Reversal, its same mode chosen again, labelled 2026-10-09: accepted (753)
  V5 M5 old       the same resolution with the effect state, timing state and programs labelled 2026-07-16: refused
  V6 the check    an engine check carries ruleset.core 2026-10-09 and rule_numbering 2026-10-09; one labelled with
                  another Core, or without its numbering field, or with its locators numbered by 2026-07-16, does not
                  validate
  V7 consumers    a consultation reading Core 2026-07-16 refuses the check (engine_version_mismatch) and one reading
                  2026-10-09 takes it; a legal-action observation whose context names 2026-07-16 does not validate.
                  The consultation command's own hold - an engine verdict against rules text of another Core, or with
                  no Core text retrieved, no retriever, or a record without a version (fails closed, 2026-10-15) - is
                  in check_rule_consult_command.py and check_judge_corpus.py

    python skill/scripts/check_semantics_version.py
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

import capability_manifest  # noqa: E402
import check_move_restriction as MR  # noqa: E402
import check_spell_control as SC  # noqa: E402
import effect_ir  # noqa: E402
import legal_action  # noqa: E402
import rules_core  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, hash_value  # noqa: E402
from engine_check import RULE_NUMBERING_FIELD, build_engine_check, validate_engine_check  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rule_consult import ConsultationError, attach_engine_check, new_consultation  # noqa: E402

OLD = "2026-07-16"
errors: list[str] = []


def fail(label: str, why: str) -> None:
    errors.append(f"{label}: {why}")


def relabel(value, core=OLD):
    """A deep copy whose every `ruleset` names `core`."""
    if isinstance(value, dict):
        out = {k: relabel(v, core) for k, v in value.items()}
        if isinstance(out.get("ruleset"), dict) and "core" in out["ruleset"]:
            out["ruleset"] = {**out["ruleset"], "core": core}
        return out
    if isinstance(value, list):
        return [relabel(v, core) for v in value]
    return copy.deepcopy(value)


def linked_move():
    state = MR.board()
    state["objects"]["u1"]["exhausted"] = True
    program = MR.program("ride-the-wind-ready",
                         {"op": "move_board_object", "effect_id": "mv", "object_id": "u1",
                          "destination": {"kind": "base", "player": "p1"}},
                         {"op": "ready", "effect_id": "rd", "object_id": "u1", "depends_on": "mv",
                          "dependency_mode": "unless_ignored"})
    program["source_object"] = "u2"
    return state, program


def same_mode(state, timing, reversal, modal):
    decisions = [{"decision_id": "may", "stage": "resolution", "kind": "optional_choice", "controller": "p1", "value": True},
                 {"decision_id": "new:mode", "stage": "resolution", "kind": "option_selection", "controller": "p1",
                  "value": "draw"}]
    env = {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": decisions}
    return resolve_with_program(timing, "spell-rev", state, reversal, engine_decisions=env,
                                chain_programs={"spell-shot": modal})


def main() -> int:
    # V1
    if (effect_ir.CORE_RULESET, rules_core.CORE_RULESET) != ("2026-10-09", "2026-10-09"):
        fail("V1 constants", f"executed Core {effect_ir.CORE_RULESET} / {rules_core.CORE_RULESET}")
    if (effect_ir.CORE_EFFECTIVE, rules_core.CORE_EFFECTIVE) != ("2026-10-16", "2026-10-16"):
        fail("V1 constants", f"in effect {effect_ir.CORE_EFFECTIVE} / {rules_core.CORE_EFFECTIVE}")
    if (effect_ir.RULE_NUMBERING, rules_core.RULE_NUMBERING) != ("2026-10-09", "2026-10-09"):
        fail("V1 constants", f"numbering {effect_ir.RULE_NUMBERING} / {rules_core.RULE_NUMBERING}")
    manifest = capability_manifest.build_manifest()
    if manifest["ruleset"]["core"] != effect_ir.CORE_RULESET or manifest["rule_numbering"] != RULE_NUMBERING_FIELD:
        fail("V1 manifest", f"{manifest['ruleset']} {manifest.get('rule_numbering')}")

    # V2 / V3
    state, program = linked_move()
    new = apply_program(state, program)
    if not new.get("committed") or new["next_state"]["objects"]["u1"].get("exhausted") is not False:
        fail("V2 M1 new", f"{new.get('reason') or new.get('errors')}: the linked Ready did not run after the negated Move")
    old = apply_program(relabel(state), relabel(program))
    if old.get("committed") or old.get("next_state"):
        fail("V3 M1 old", "a state and program labelled 2026-07-16 were executed")

    # V4 / V5
    board = SC.board(modal=True)
    accepted = same_mode(board, SC.timing(), SC.REVERSAL, SC.MODAL)
    if not accepted.get("committed"):
        fail("V4 M5 new", f"the same mode again was refused: {SC.code(accepted)}")
    refused = same_mode(relabel(board), relabel(SC.timing()), relabel(SC.REVERSAL), relabel(SC.MODAL))
    if refused.get("committed"):
        fail("V5 M5 old", "making new choices ran under a 2026-07-16 label")
    if relabel(SC.timing())["ruleset"]["core"] != OLD or relabel(board)["ruleset"]["core"] != OLD:
        fail("V5 M5 old", "the relabel did not reach both states, so the refusal proves nothing")

    # V6
    check = build_engine_check("effect", new, input_hashes={"effect_state": hash_value(state)})
    if validate_engine_check(check) or check["ruleset"]["core"] != effect_ir.CORE_RULESET \
            or check["rule_numbering"] != {"core": "2026-10-09", "applies_to": "rule_locators"}:
        fail("V6 the check", f"{validate_engine_check(check)} {check.get('ruleset')} {check.get('rule_numbering')}")
    for label, broken in (("another Core", {**check, "ruleset": {**check["ruleset"], "core": OLD}}),
                          ("no numbering", {k: v for k, v in check.items() if k != "rule_numbering"}),
                          ("its locators numbered by 2026-07-16", {**check, "rule_numbering": {"core": OLD,
                                                                                               "applies_to": "rule_locators"}})):
        if not validate_engine_check(broken):
            fail("V6 the check", f"a check with {label} validated")

    # V7
    for ruleset_as_of, attached in ((OLD, False), (effect_ir.CORE_RULESET, True)):
        consultation = new_consultation(question_type="specific_interaction", question="Version fixture?",
                                        format_name="1v1 Constructed", ruleset_as_of=ruleset_as_of, created_by="gate")
        try:
            attach_engine_check(consultation, check)
            took = True
        except ConsultationError as exc:
            took = False
            if "engine_version_mismatch" not in str(exc):
                fail("V7 consumers", f"refused for another reason: {exc}")
        if took != attached:
            fail("V7 consumers", f"a consultation reading Core {ruleset_as_of} {'took' if took else 'refused'} the check")
    for core, valid in ((OLD, False), (rules_core.CORE_RULESET, True)):
        observation = legal_action.build_observation(
            perspective="player1", source={"kind": "engine_state", "state_seq": 1},
            context={"ruleset_core": core, "faq_as_of": rules_core.FAQ_AS_OF, "format": "standard",
                     "card_data_version": "synthetic"},
            timing_state=fixture(), effect_state=state, facts={}, pending_decisions=[],
            completeness={"hands": "complete", "board": "complete", "resources": "complete",
                          "pending_decisions": "complete"})
        if (not legal_action.validate_observation(observation)) != valid:
            fail("V7 consumers", f"an observation under Core {core}: {legal_action.validate_observation(observation)}")

    if errors:
        print("FAILED: the executed Core and the rule numbering")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: the engine executes Core {effect_ir.CORE_RULESET} (in effect {effect_ir.CORE_EFFECTIVE}) and refuses "
          f"any other label - M1 and M5 run under it and are refused under {OLD}; its locators are numbered "
          f"{effect_ir.RULE_NUMBERING}, a field of their own; consumers reading another Core refuse its result (V1-V7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
