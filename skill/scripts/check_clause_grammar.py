#!/usr/bin/env python3
"""Regression gate for C-60 / C-61 (ADR-0016 §1–2): the clause grammar and
canonical dual-compilation agreement.

Must hold:
  - the contract validates, and every production carries both fixtures it is
    promoted on: each golden clause compiles to that production, and each
    near-miss does **not** match it. A pattern that swallows its own negative
    fixture is a failure, not a warning;
  - every production has a lowering and every lowering has a production;
  - the round trip closes against the corpus: for every clause the grammar
    parses, the program it compiles is canonically equal to the program a
    human wrote for that clause in the card pack. The corpus is the golden
    set, and the gate reports how much of it the grammar reproduces;
  - canonical equality is neither vacuous nor structural-only: renaming an
    instruction is closed automatically with an audit record, changing an
    amount is a semantic disagreement, and two programs of the same shape
    whose linked predicate points at a different instruction disagree;
  - a disagreement escalates once, however many rounds it appears in;
  - a clause outside the grammar is `clause_unparsed` carrying its own text,
    and never a guessed program; `complete_grammar` stays false;
  - compilation is deterministic.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
from pack_locator import pack_files  # noqa: E402


def corpus_clauses():
    for pack in pack_files("r3a1_programs.json"):
        data = json.loads(pack.read_text(encoding="utf-8"))
        for card in data["cards"]:
            for clause in card["clauses"]:
                yield clause


def target_of(execution):
    return {
        "program_effects": (execution.get("program") or {}).get("effects", []),
        "passive": execution.get("passive"),
        "play_timing": (execution.get("declaration") or {}).get("chain_item", {}).get("timing")
        if execution.get("kind") == "play" else None,
    }


def compiled_of(result):
    return {"program_effects": result.get("program_effects", []), "passive": result.get("passive"),
            "play_timing": result.get("play_timing")}


# Synthetic, and synthetic on purpose: the public repo carries the contract and
# the verifier, never a real card's reading.
SYNTHETIC_MAPPINGS = {
    "cost_comparison": {"cost_basis": "printed_cost", "power_measure": "total_printed_power",
                        "authority_status": "house_ruling", "official_status": "unverified",
                        "source": {"platform": "synthetic gate fixture", "recorded_on": "2026-09-08"}},
}


def main() -> int:
    errors: list[str] = []
    grammar = cg.load_grammar()
    if found := cg.validate_grammar(grammar):
        errors.append(f"the grammar contract does not validate: {found}")
    if grammar.get("complete_grammar") is not False:
        errors.append("the grammar claims to be complete")

    # --- the fixtures every production is promoted on -------------------------------------------
    # DP-84: a golden must compile to its own production; the goldens together
    # must exercise every alternative of every slot the production admits and
    # the cross product of every jointly meaningful slot pair; and a near-miss
    # must not match. A `production: null` keyword is a known boundary, so its
    # golden is recognised without being parsed.
    joint_pairs = [tuple(pair) for pair in grammar["jointly_meaningful"]]
    for production in grammar["productions"]:
        production_id = production["production_id"]
        exercised: dict[str, set[str]] = {slot: set() for slot in production["slots"]}
        combinations: set[tuple[str, str, str, str]] = set()
        for text in production["golden"]:
            # A production may deliberately leave a hole the rules do not fill
            # (DP-93's cost basis). Its goldens are compiled with a synthetic
            # mapping, so the gate still proves the production parses without
            # any real card mapping entering the public repo.
            result = cg.compile_clause(text, grammar, mappings=SYNTHETIC_MAPPINGS)
            recognised = result.get("production_id") == production_id
            parsed_or_known = not result.get("unsupported") or result.get("reason_code") == "keyword_not_implemented"
            if not recognised or not parsed_or_known:
                errors.append(f"{production_id} did not compile its own golden fixture {text!r}: "
                              f"{result.get('production_id')} {result.get('reason_code', '')}")
                continue
            for slot, resolved in (result.get("slots") or {}).items():
                exercised.setdefault(slot, set()).add(resolved["alternative"])
            slots = result.get("slots") or {}
            for left, right in joint_pairs:
                if left in slots and right in slots:
                    combinations.add((left, slots[left]["alternative"], right, slots[right]["alternative"]))
        for slot, admitted in production["slots"].items():
            missing = sorted(set(cg.slot_alternatives(grammar, production, slot)) - exercised.get(slot, set()))
            if missing:
                errors.append(f"{production_id} has no golden for {slot} alternatives {missing}; "
                              "every alternative a production admits must be exercised (DP-84)")
        for left, right in joint_pairs:
            if left not in production["slots"] or right not in production["slots"]:
                continue
            wanted = {(left, a, right, b)
                      for a in cg.slot_alternatives(grammar, production, left)
                      for b in cg.slot_alternatives(grammar, production, right)}
            uncovered = sorted(wanted - combinations)
            if uncovered:
                errors.append(f"{production_id} leaves {len(uncovered)} of {len(wanted)} {left}x{right} pairs "
                              f"uncovered, e.g. {uncovered[:2]}; jointly meaningful slots need pairwise goldens (DP-84)")
        for text in production["negative"]:
            result = cg.compile_clause(text, grammar)
            if result.get("production_id") == production_id and not result.get("unsupported"):
                errors.append(f"{production_id} matched its own near-miss {text!r}; the pattern is too wide")
        # one near-miss per slot: a negative that differs only in that slot
        for slot in production["slots"]:
            if not any(cg.compile_clause(text, grammar).get("production_id") != production_id
                       or cg.compile_clause(text, grammar).get("unsupported")
                       for text in production["negative"]):
                errors.append(f"{production_id} has no near-miss that its pattern rejects for slot {slot}")

    # --- every capability the grammar names is one the engine declares ------------------------------
    # Codex, after the ranking misled the target choice: capability gaps must
    # be derived from the engine, not from a second vocabulary kept by hand.
    from capability_manifest import build_manifest
    manifest = build_manifest()
    declared = ({entry["id"] for entry in manifest["operations"]}
                | {scope for component in manifest["components"] for scope in component["supported_scope"]})
    for production in grammar["productions"]:
        unknown = sorted(set(production["required_capability"]) - declared)
        if unknown:
            errors.append(f"{production['production_id']} requires {unknown}, which this engine does not "
                          "declare; a capability the manifest has never heard of cannot be reasoned about")
    # the compile-time branches - sequence, modes, the two linked prefixes -
    # name capabilities inline, so they are checked by compiling one of each
    # rather than by reading the data.
    for text in ("Draw 1 and channel 1 rune exhausted.", "Draw 1 or channel 1 rune exhausted.",
                 "When I move, draw 1, then channel 1 rune exhausted."):
        branch = cg.compile_clause(text, grammar)
        unknown = sorted(set(branch.get("required_capability", [])) - declared)
        if unknown:
            errors.append(f"compiling {text!r} required {unknown}, which this engine does not declare")
    linked = cg.compile_card([{"text": "Channel 1 rune exhausted."}, {"text": "If you do, draw 2."}], grammar)
    offer = cg.compile_card([{"text": "You may pay [C] as additional cost to play me."},
                             {"text": "When you play me, if you paid additional cost, draw 1."}], grammar)
    for label, card in (("a linked prefix", linked), ("a cost link", offer)):
        for clause in card["clauses"]:
            unknown = sorted(set(clause.get("required_capability", [])) - declared)
            if unknown:
                errors.append(f"{label} required {unknown}, which this engine does not declare")

    # --- the round trip against the corpus -----------------------------------------------------
    agree = disagree = unparsed = known = skipped = 0
    semantic: list[dict] = []
    for clause in corpus_clauses():
        result = cg.compile_clause(clause["text"], grammar)
        if result.get("unsupported"):
            # Two different things: the grammar cannot read it, or the
            # catalogue names it and the engine does not implement it (DP-85).
            reason = result.get("reason_code")
            if reason == "keyword_not_implemented":
                known += 1
            else:
                unparsed += 1
            if reason not in cg.ABSTENTION_REASONS or result.get("text") != clause["text"]:
                errors.append(f"an unsupported clause did not carry its own text and reason: {result}")
            if "program_effects" in result or "passive" in result:
                errors.append(f"an unsupported clause produced a program anyway: {clause['text']!r}")
            continue
        execution = clause.get("execution")
        if execution is None:
            skipped += 1
            continue
        verdict = cg.compare_compilations(compiled_of(result), target_of(execution),
                                          label_left="grammar", label_right="corpus")
        if verdict["agree"]:
            agree += 1
        else:
            disagree += 1
            semantic.extend(verdict["escalate"])
    if disagree:
        errors.append(f"the grammar disagrees with the corpus on {disagree} clause(s): "
                      f"{[d['field'] for d in semantic][:4]}")
    if agree < 25:
        errors.append(f"the round trip reproduces only {agree} of the corpus's hand-written programs")


    # --- DP-86: sequencing, referents and linked prefixes ------------------------------------------
    # (1) "and"/"then" are strictly ordered, and never parallelised.
    seq = cg.compile_clause("Draw 1 and channel 1 rune exhausted.", grammar)
    if seq.get("unsupported") or seq["production_id"] != "sequence":
        errors.append(f"a two-instruction 'and' did not compile as a sequence: {seq}")
    else:
        if [e["op"] for e in seq["program_effects"]] != ["draw", "channel_rune"]:
            errors.append(f"the sequence did not keep the written order: {seq['program_effects']}")
        if [e.get("order") for e in seq["program_effects"]] != [0, 1]:
            errors.append("the sequence's program does not carry its own order")
        if not seq["ast"].get("ordered"):
            errors.append("the sequence AST does not declare itself ordered")
    then = cg.compile_clause("Draw 1, then channel 1 rune exhausted.", grammar)
    if then.get("unsupported"):
        errors.append(f"'then' did not compile: {then}")
    else:
        second = then["program_effects"][1]
        if second.get("predicate", {}).get("kind") != "action_performed" or                 second["predicate"]["effect_id"] != then["program_effects"][0]["effect_id"]:
            errors.append(f"'then' did not gate the second instruction on the first's receipt: {second}")
    # a connective outside the white-list joins nothing
    for text in ("Draw 1 and summon a dragon.", "Draw 1 while you have 2 runes."):
        if not cg.compile_clause(text, grammar).get("unsupported"):
            errors.append(f"an unreadable half was joined anyway: {text!r}")
    # "or" is a mode, never a sequence: joining it would perform both halves.
    either = cg.compile_clause("Draw 1 or draw 2.", grammar)
    if either.get("production_id") == "sequence" or either.get("program_effects"):
        errors.append(f"'or' was joined as a sequence: {either.get('production_id')} {either.get('program_effects')}")
    # a wrapper binds before the sequence splits, or "when I move" is torn off
    wrapped_seq = cg.compile_clause("When I move, draw 1, then channel 1 rune exhausted.", grammar)
    if wrapped_seq.get("unsupported") or wrapped_seq["production_id"] != "when_i_move":
        errors.append(f"a trigger wrapper was pre-empted by the sequence split: {wrapped_seq}")

    # (2) a referent binds to the object the earlier part chose, not to a fresh
    #     search. Both halves must carry the *same* decision reference.
    referent = cg.compile_clause(
        "Give a friendly unit +2 :rb_might: this turn and give it [Tank] this turn.", grammar)
    unbound = cg.compile_card([{"text": "Give it [Tank] this turn."}], grammar)
    if unbound["clauses"][0].get("reason_code") != "referent_not_bound":
        errors.append(f"a referent with nothing to refer to was compiled anyway: {unbound['clauses'][0]}")
    if referent.get("unsupported"):
        errors.append(f"a referent sequence did not compile: {referent}")
    else:
        refs = [e.get("target", {}).get("decision_ref") for e in referent["program_effects"]]
        if len(set(r for r in refs if r)) != 1 or cg.REFERENT_REF in refs:
            errors.append(f"'it' did not bind to the earlier decision: {refs}")

    # (3) a linked prefix reads a receipt or abstains; it never guesses one.
    alone = cg.compile_clause("If you do, draw 2.", grammar)
    if not alone.get("unsupported") or alone.get("reason_code") != "link_antecedent_not_available":
        errors.append(f"'if you do' invented an antecedent with nothing before it: {alone}")
    linked_card = cg.compile_card([{"text": "Channel 1 rune exhausted."}, {"text": "If you do, draw 2."},
                                   {"text": "Otherwise, draw 1."}], grammar)
    kinds = [(c.get("link"), c.get("antecedent_effect_id")) for c in linked_card["clauses"][1:]]
    first_id = linked_card["clauses"][0]["program_effects"][0]["effect_id"]
    if kinds != [("action_performed", first_id), ("action_not_performed", first_id)]:
        errors.append(f"the linked prefixes did not both read the first instruction's receipt: {kinds}")
    if any(c.get("unsupported") for c in linked_card["clauses"]):
        errors.append(f"a card whose links all resolve still reported unsupported clauses: {linked_card['unsupported_clauses']}")
    # an unreadable previous clause leaves no receipt, so the link abstains
    blocked = cg.compile_card([{"text": "Summon a dragon."}, {"text": "If you do, draw 2."}], grammar)
    if blocked["clauses"][1].get("reason_code") != "link_antecedent_not_available":
        errors.append(f"a link read a receipt from a clause the grammar could not compile: {blocked['clauses'][1]}")
    # a passive clause performs nothing, so it leaves nothing to test
    passive_first = cg.compile_card([{"text": "[Tank]"}, {"text": "If you do, draw 2."}], grammar)
    if passive_first["clauses"][1].get("reason_code") != "link_antecedent_not_available":
        errors.append(f"a link tested a passive clause as though it were performed: {passive_first['clauses'][1]}")

    # --- canonical equality has teeth -----------------------------------------------------------
    left = {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 1}]}
    renamed = {"program_effects": [{"op": "draw", "effect_id": "draw-1", "player": "$controller", "count": 1}]}
    verdict = cg.compare_compilations(left, renamed)
    if not verdict["agree"] or not verdict["closed_automatically"]:
        errors.append(f"renaming an instruction was not closed as a naming difference: {verdict}")
    if verdict["closed_automatically"][0]["equivalence"] != "instruction_naming":
        errors.append("the audit record does not name the equivalence it closed on")
    changed = {"program_effects": [{"op": "draw", "effect_id": "dr", "player": "$controller", "count": 2}]}
    verdict = cg.compare_compilations(left, changed)
    if verdict["agree"] or not verdict["escalate"]:
        errors.append("changing an amount was not a semantic disagreement")
    # the link a name carried survives the canonicalizer
    linked = {"program_effects": [
        {"op": "discard", "effect_id": "d", "player": "$controller", "count": 1},
        {"op": "draw", "effect_id": "then", "player": "$controller", "count": 1,
         "predicate": {"kind": "action_performed", "effect_id": "d"}}]}
    relinked = copy.deepcopy(linked)
    relinked["program_effects"][1]["predicate"]["effect_id"] = "then"
    if cg.compare_compilations(linked, relinked)["agree"]:
        errors.append("a predicate pointing at a different instruction was called equal; the link did not survive")
    renamed_link = copy.deepcopy(linked)
    renamed_link["program_effects"][0]["effect_id"] = "first"
    renamed_link["program_effects"][1]["predicate"]["effect_id"] = "first"
    if not cg.compare_compilations(linked, renamed_link)["agree"]:
        errors.append("renaming both ends of a link was called a disagreement")
    reordered = cg.compare_compilations({"required_capability": ["draw", "targeting"]},
                                        {"required_capability": ["targeting", "draw"]})
    if not reordered["agree"] or not reordered["closed_automatically"]:
        errors.append(f"an unordered set in a different order was escalated: {reordered}")

    # --- one signature, one escalation -----------------------------------------------------------
    once = cg.compare_compilations(left, changed)["escalate"]
    fresh, seen = cg.dedupe(once)
    again, _ = cg.dedupe(once, seen)
    if len(fresh) != 1 or again:
        errors.append(f"the same disagreement escalated twice: {len(fresh)} then {len(again)}")

    # --- a card, and what it will not compile ------------------------------------------------------
    card = cg.compile_card([{"text": "[Action]"}, {"text": "Draw 1."}, {"text": "Summon a dragon."}], grammar)
    if card["complete_grammar"] is not False:
        errors.append("compile_card claimed a complete grammar")
    if [c["text"] for c in card["unsupported_clauses"]] != ["Summon a dragon."]:
        errors.append(f"compile_card did not report exactly the clause it could not parse: {card['unsupported_clauses']}")
    if len(card["program_effects"]) != 1 or card["program_effects"][0]["op"] != "draw":
        errors.append(f"compile_card did not keep the clauses it could compile: {card['program_effects']}")
    wrapped = cg.compile_clause("When you play me, summon a dragon.", grammar)
    if not wrapped.get("unsupported") or wrapped.get("production_id") != "when_you_play_me":
        errors.append(f"a wrapper with an unparsed instruction was compiled anyway: {wrapped}")

    if cg.compile_clause("Draw 1.", grammar) != cg.compile_clause("Draw 1.", grammar):
        errors.append("compilation is not deterministic")
    if cg.normalize("Give a friendly unit +3 :rb_might: this turn.") != "give a friendly unit +3 [m] this turn":
        errors.append(f"normalization changed: {cg.normalize('Give a friendly unit +3 :rb_might: this turn.')!r}")

    if errors:
        print("FAILED: clause grammar checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"clause grammar checks passed: {len(grammar['productions'])} productions over "
          f"{len(grammar['sub_grammars'])} sub-grammars, corpus round trip {agree} reproduced / {disagree} disagreed / "
          f"{unparsed} unparsed / {known} known-unsupported / {skipped} without a program, complete_grammar false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
