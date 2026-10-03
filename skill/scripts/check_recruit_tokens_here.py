#!/usr/bin/env python3
"""
Regression gate: "Play two 1 [M] Recruit unit tokens here." and the Legion ability over it (2026-09-27).

The engine grammar reads "play (a|two|three|four) N [M] Recruit unit token(s) here" as one play_token per
token - a catalogued Recruit (Core 187.1) with the printed Might, placed at the program source's current
Battlefield read as it executes (location_ref, Core 359.3.f.2), the signed single-token shape repeated -
so that "[Legion][>] When you play me, play two 1 [M] Recruit unit tokens here." (Vanguard Captain) is a
Dependent Keyword over a play trigger (Core 727.1, 812.1.b.1) instead of a form the grammar refuses.

Must hold:
  - the clause lowers to exactly N play_token instructions of the Recruit, each with the printed Might and
    the location_ref destination; "a" is one;
  - the Legion clause lowers to a play trigger carrying the Legion condition, and the keyword;
  - executed with its source at bf1: N new Recruit tokens at bf1, the source's controller's, exhausted
    (Core 143.4: units enter exhausted); with its source in its Base, no token is placed there;
  - departure (GPT 2026-09-27, package 3 section 7 item 4): the source dead before the trigger resolves (in
    the trash: no Battlefield is 'here', Core 359.3.e.12, 359.3.f.2), and the source gone with a NEW object of
    the same card back at bf1 (another identity, Core 124 - not the source the ability names) - no token
    is placed at bf1 in either;
  - negatives stay unparsed: five tokens, 'into your base', no place, another token;
  - mutation caught: a lowering that places the tokens in the Base.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

TWO = "Play two 1 :rb_might: Recruit unit tokens here."
LEGION = "[Legion][>] When you play me, play two 1 :rb_might: Recruit unit tokens here."
HERE = {"kind": "battlefield", "location_ref": {"kind": "program_source_current_battlefield"}}


def program_of(text):
    got = CG.compile_clause(text, CG.load_grammar())
    return None if got.get("unsupported") else got.get("program_effects")


def run(effects, *, source_at="bf1"):
    """The effects run as the program of p1's src, a Unit at bf1 (p1's) or in p1's Base; "trash": the source
    died after the ability triggered at bf1; "renewed": it left and a new object of the card is at bf1."""
    state = base_state()
    state["objects"]["src"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                               "damage": 0, "exhausted": False}
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["src"] if source_at in ("bf1", "renewed") else []}
    if source_at == "base":
        state["players"]["p1"]["zones"]["base"].append("src")
    elif source_at == "trash":
        state["players"]["p1"]["zones"]["trash"].append("src")
    # the identity the ability was triggered by: the object at bf1, before it died or was replaced
    identity = IR.object_identity(state, "src") or "src@0"
    if source_at == "renewed":
        state["objects"]["src"]["identity"] = "src@1"      # a new object of the same card (Core 124)
    bound = [{**copy.deepcopy(e), "owner": "p1", "controller": "p1"} for e in effects]
    program = {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF},
               "program_id": "src-on-play-effects", "controller": "p1", "source_object": "src",
               "source_identity": identity, "effects": bound}
    done = IR.apply_program(state, program)
    if not done.get("committed"):
        return "refused"
    after = done["next_state"]
    tokens = sorted(o for o, obj in after["objects"].items() if obj.get("is_token"))
    return [(IR.find_location(after, t)[0] if IR.find_location(after, t) else None, after["objects"][t].get("token_id"),
             after["objects"][t]["base_might"], after["objects"][t]["controller"], after["objects"][t]["exhausted"])
            for t in tokens]


def main() -> int:
    errors: list[str] = []
    two = program_of(TWO)
    # package 7: the lowering carries the Recruit card's printed tags from the reviewed catalogue (none until
    # the owner's amendment adds them)
    from token_catalog import carry_tags
    want = carry_tags([{"op": "play_token", "effect_id": f"tok{i}", "owner": "$controller", "controller": "$controller",
                        "token_kind": "unit", "base_might": 1, "token_id": "recruit", "object_id_ref": {"kind": "fresh"},
                        "destination": HERE} for i in (1, 2)])
    if two != want:
        errors.append(f"'{TWO}' lowered to {two}")
    one = program_of("Play a 1 :rb_might: Recruit unit token here.")
    if not one or len(one) != 1 or one[0]["effect_id"] != "tok" or one[0]["destination"] != HERE:
        errors.append(f"'a' did not lower to one token: {one}")
    legion = CG.compile_clause(LEGION, CG.load_grammar())
    fields = (legion.get("passive") or {}).get("object_fields") or {}
    if legion.get("unsupported") or fields.get("keywords") != ["legion"] \
            or [t.get("condition") for t in fields.get("play_triggers") or []] != [{"kind": "another_card_finalized_this_turn"}] \
            or legion.get("program_effects") != want:
        errors.append(f"the Legion clause did not lower to a Legion-gated play trigger: {legion.get('reason') or fields}")
    placed = run(two)
    if placed != [("battlefield", "recruit", 1, "p1", True)] * 2:
        errors.append(f"with its source at bf1 the tokens were {placed}, not two exhausted Recruits of p1's at bf1")
    home = run(two, source_at="base")
    if home not in ([], "refused"):
        errors.append(f"with its source in its Base, tokens were placed: {home}")
    for departed, label in (("trash", "dead before the trigger resolved"), ("renewed", "replaced by a new object at bf1")):
        gone = run(two, source_at=departed)
        if gone not in ([], "refused") and any(where == "battlefield" for where, *_rest in gone):
            errors.append(f"with its source {label}, tokens were placed at a Battlefield: {gone}")
    for text in ("Play five 1 :rb_might: Recruit unit tokens here.", "Play two 1 :rb_might: Recruit unit tokens into your base.",
                 "Play two 1 :rb_might: Recruit unit tokens.", "Play a 3 :rb_might: Sprite unit token here."):
        if program_of(text) is not None and CG.compile_clause(text, CG.load_grammar()).get("production_id") == \
                "play_n_might_recruit_unit_tokens_here":
            errors.append(f"a near miss lowered as tokens here: {text!r}")
    real = CG.LOWERINGS["play_n_might_recruit_unit_tokens_here"]

    def to_base(params):
        out = real(params)
        for effect in out["program_effects"]:
            effect["destination"] = {"kind": "base", "player": "$controller"}
        return out

    CG.LOWERINGS["play_n_might_recruit_unit_tokens_here"] = to_base
    try:
        mutated = program_of(TWO)
        caught = mutated != want or run(mutated) == placed
    finally:
        CG.LOWERINGS["play_n_might_recruit_unit_tokens_here"] = real
    if not caught:
        errors.append("mutation not caught: tokens lowered into the Base")
    if errors:
        print("FAILED: recruit tokens here")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'Play two 1 [M] Recruit unit tokens here.' lowers to two catalogued Recruit play_tokens at the source's "
          "current Battlefield (359.3.f.2), exhausted, none from a Base, none once the source died or is a new object; the Legion ability over it lowers to a gated play "
          "trigger (812.1.b.1); near misses stay unparsed; a Base-placing lowering is caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
