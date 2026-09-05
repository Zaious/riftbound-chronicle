#!/usr/bin/env python3
"""
Gate for C-18: R3-A1 card programs and the derived behavior manifest.

Must hold:
  - the programs file is well-formed: known claims, fixture kinds, every
    clause id exists in inventory.draft.json, fixture ids unique;
  - every non-n/a fixture passes against the engine; a `full`/`partial`
    clause has a passing positive and negative fixture, and a choice clause
    a missing_information one;
  - the committed manifest and report equal a fresh build (deterministic);
  - the derived manifest validates; a claim never outranks its evidence
    (a full clause with failing fixtures derives unsupported); stale
    inventory clauses stay stale with no program_id; unsupported clauses
    carry no program_id and name a mechanic; card status is full only when
    every clause is full; the manifest stays draft;
  - inventory.draft.json is untouched by this pipeline;
  - text hashes equal the inventory's (the same "current text");
  - Vision clauses, when present, are unsupported with predict named;
  - C-32: every R3-A3 clause is in the pack; vanilla Units are probed through
    intrinsic unit_combat; Tank covers Backline and Tank+Backline; the Legend
    clause stays partial; combat blocks and declarations are portable;
  - C-25: every R3-A2 clause is in the pack; passives and probes are portable;
    "When you play me" has a play_entry fixture; the four stale cards derive
    stale with no program_id / test_ids even though they carry programs;
    passive-only clauses derive passive:<clause_id> with no ops; Annie - Fiery
    is partial naming the unmodelled Legend object;
  - off-cwd run.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import r3a1_programs as rp  # noqa: E402
from card_behavior_coverage import validate_manifest  # noqa: E402


def main() -> int:
    errors: list[str] = []
    programs = rp.load_programs()
    inventory = rp.load_inventory()
    inv_clauses = {c["clause_id"]: (card, c) for card in inventory["cards"] for c in card["clauses"]}
    if programs.get("schema_version") != rp.PROGRAMS_VERSION or programs.get("ruleset") != inventory["ruleset"]:
        errors.append("programs file version/ruleset mismatch")
    fixture_ids: set[str] = set()
    for card in programs["cards"]:
        if card["card_key"] not in {c["card_key"] for c in inventory["cards"]}:
            errors.append(f"{card['card']} is not in the inventory")
        for clause in card["clauses"]:
            if clause["claim"] not in rp.CLAIMS:
                errors.append(f"{clause['clause_id']} has an unknown claim")
            if clause["clause_id"] not in inv_clauses:
                errors.append(f"{clause['clause_id']} is not an inventory clause")
            if clause["claim"] in {"full", "partial"} and "execution" not in clause:
                errors.append(f"{clause['clause_id']} claims {clause['claim']} without an execution")
            for fx in clause.get("fixtures", []):
                if fx["kind"] not in rp.FIXTURE_KINDS:
                    errors.append(f"{fx['fixture_id']} has an unknown kind")
                if fx["fixture_id"] in fixture_ids:
                    errors.append(f"{fx['fixture_id']} is duplicated")
                fixture_ids.add(fx["fixture_id"])
                if fx["kind"] != "not_applicable" and (not fx.get("expected", {}).get("rule_locators") or not fx.get("why")):
                    errors.append(f"{fx['fixture_id']} lacks a cited expectation")

    report = rp.run_all(programs)
    for card in report["cards"]:
        for cl in card["clauses"]:
            for r in cl["fixtures"]:
                if not r["passed"]:
                    errors.append(f"{r['fixture_id']}: " + "; ".join(r["problems"]))
            real = {r["kind"] for r in cl["fixtures"] if not r.get("skipped") and r["passed"]}
            if cl["claim"] in {"full", "partial"} and not {"positive", "negative"} <= real:
                errors.append(f"{cl['clause_id']} claims {cl['claim']} without positive and negative fixtures")
    manifest = rp.build_manifest(programs, report)
    if validate_manifest(manifest):
        errors.append(f"derived manifest invalid: {validate_manifest(manifest)}")
    if manifest["status"] != "draft":
        errors.append("manifest must stay draft; activation is a separate gate (ADR-0004)")
    for card in manifest["cards"]:
        inv_card = next(c for c in inventory["cards"] if c["card_key"] == card["card_key"])
        if card["current_text_hash"] != inv_card["current_text_hash"]:
            errors.append(f"{card['canonical_name']} text hash differs from the inventory")
        for cl in card["clauses"]:
            inv = inv_clauses[cl["clause_id"]][1]
            if cl["text_hash"] != inv["text_hash"]:
                errors.append(f"{cl['clause_id']} text hash differs from the inventory")
            if inv["status"] == "stale" and (cl["status"] != "stale" or cl["program_id"] is not None):
                errors.append(f"{cl['clause_id']} is stale in the inventory but activated here")
            if cl["status"] == "unsupported" and (cl["program_id"] is not None or not cl["unsupported_mechanics"]):
                errors.append(f"{cl['clause_id']} unsupported clause carries a program or names no mechanic")
            if cl["status"] in {"full", "partial"} and (not cl["program_id"] or not cl["test_ids"]):
                errors.append(f"{cl['clause_id']} {cl['status']} without program/test evidence")
            if "vision" in cl["notes"].lower() and cl["status"] != "unsupported":
                errors.append(f"{cl['clause_id']} Vision must stay unsupported this round")
        statuses = {c["status"] for c in card["clauses"]}
        if card["behavior_status"] == "full" and statuses != {"full"}:
            errors.append(f"{card['canonical_name']} claims full with clauses {sorted(statuses)}")
    # injection test: the literal-player guard must catch composite strings too
    for poison in ("base:p1", "p2.hand", "p1", "lethal-cleanup:p2:0"):
        if not rp.literal_players({"destination": {"kind": "base", "player": poison}}):
            errors.append(f"literal-player guard missed {poison!r}")
    if rp.literal_players({"x": "spell-1", "y": "$controller", "z": "up1"}):
        errors.append("literal-player guard flagged a non-player token")
    # Codex Round B acceptance: portability is proven, not assumed
    for card in programs["cards"]:
        for clause in card["clauses"]:
            if not rp.template_is_portable(clause):
                errors.append(f"{clause['clause_id']} template carries a literal player id")
    for card in report["cards"]:
        for cl in card["clauses"]:
            for r in cl["fixtures"]:
                if not r.get("skipped") and r.get("mirrored") is not True and cl["claim"] in {"full", "partial"}:
                    errors.append(f"{r['fixture_id']} did not pass under the mirrored (players swapped) binding")
    flash = next(cl for c in programs["cards"] if c["card"] == "Flash" for cl in c["clauses"] if cl["clause_id"] == "flash#7a92a690")
    if flash["execution"]["program"]["effects"][0]["destination"] != {"kind": "base", "player_relation": "object_controller"}:
        errors.append("Flash's Move destination is bound to a fixture player instead of each unit's own controller (355.4.a)")
    morbid = next(cl for c in programs["cards"] if c["card"] == "Morbid Return" for cl in c["clauses"] if cl["clause_id"] == "morbid return#f3c76e58")
    if morbid["execution"]["program"]["effects"][0]["target"].get("zone_owner_relation") != "own":
        errors.append("Morbid Return does not restrict the choice to the caster's own trash")
    rows = {r["fixture_id"]: r for c in report["cards"] for cl in c["clauses"] for r in cl["fixtures"]}
    if rows.get("morbid return#f3c76e58:opponent_trash", {}).get("outcome") != "illegal":
        errors.append("p1 returning a unit from p2's trash was not illegal")
    if rows.get("incinerate#08866b32:add_window_unconfirmed", {}).get("outcome") != "decision_required":
        errors.append("a sufficient pool without a confirmed Add window did not stop for confirmation (429.3)")
    # a claim never outranks its evidence
    probe = copy.deepcopy(programs)
    target = next(cl for c in probe["cards"] for cl in c["clauses"] if cl["claim"] == "full" and cl.get("fixtures"))
    for fx in target["fixtures"]:
        if fx["kind"] == "positive":
            fx["expected"]["outcome"] = "illegal"
    probe_manifest = rp.build_manifest(probe, rp.run_all(probe))
    derived = next(cl for c in probe_manifest["cards"] for cl in c["clauses"] if cl["clause_id"] == target["clause_id"])
    if derived["status"] != "unsupported" or derived["program_id"] is not None:
        errors.append("a full claim with a failing fixture still derived a supported status")
    # C-25 (ADR-0007): every R3-A2 clause is in the pack; passives and probes are
    # portable; "When you play me" is observed through a play_entry fixture; the
    # four stale cards may carry programs but derive no program_id or test_ids;
    # a passive-only clause derives passive:<clause_id> with no implemented ops.
    r3a2 = {c["clause_id"] for card in inventory["cards"] for c in card["clauses"] if "R3-A2-play-conditions-continuous" in c["notes"]}
    in_pack = {cl["clause_id"] for c in programs["cards"] for cl in c["clauses"]}
    if missing := sorted(r3a2 - in_pack):
        errors.append(f"R3-A2 clauses absent from the pack: {missing}")
    for card in programs["cards"]:
        for clause in card["clauses"]:
            execution = clause.get("execution") or {}
            if execution.get("passive") and rp.literal_players(execution["passive"]):
                errors.append(f"{clause['clause_id']} passive carries a literal player id")
            if rp.literal_players([fx.get("probe") for fx in clause.get("fixtures", []) if fx.get("probe")]):
                errors.append(f"{clause['clause_id']} probe carries a literal player id")
            if any(fx.get("run") not in (None, *rp.RUNS) for fx in clause.get("fixtures", [])):
                errors.append(f"{clause['clause_id']} names an unknown run path")
            if clause["text"].startswith("When you play me") and not any(fx.get("run") == "play_entry" and fx["kind"] == "positive" for fx in clause.get("fixtures", [])):
                errors.append(f"{clause['clause_id']} has no play_entry fixture showing the trigger scheduled on play completion")
    manifest_rows = {cl["clause_id"]: cl for card in manifest["cards"] for cl in card["clauses"]}
    for stale_card in ("annie - dark child (starter)", "void gate", "highlander", "disintegrate"):
        card = next((c for c in manifest["cards"] if c["card_key"] == stale_card), None)
        if card is None or card["behavior_status"] != "stale" or any(cl["program_id"] or cl["test_ids"] or cl["status"] != "stale" for cl in card["clauses"]):
            errors.append(f"{stale_card} must derive stale with no program_id or test_ids")
    for cid in ("highlander#b9d95a9d", "void gate#3aa2e8f7", "annie - dark child (starter)#223039b2"):
        if not next((cl.get("execution") for c in programs["cards"] for cl in c["clauses"] if cl["clause_id"] == cid), None):
            errors.append(f"{cid} should carry a program in the pack even though it stays stale")
    for cid, expected_ops in (("pouty poro#f8dcb74f", []), ("master yi - honed#0be72750", []), ("sai scout#0ede37d4", []), ("tibbers#ca766089", ["deal_damage"])):
        row = manifest_rows.get(cid, {})
        if row.get("status") != "full" or row.get("implemented_ops") != expected_ops or not row.get("program_id"):
            errors.append(f"{cid} derived {row.get('status')} / {row.get('implemented_ops')} / {row.get('program_id')}, expected full with ops {expected_ops}")
        if not expected_ops and not row.get("program_id", "").startswith("passive:"):
            errors.append(f"{cid} passive-only clause should derive a passive program id")
    fiery = manifest_rows.get("annie - fiery#24035ea0", {})
    if fiery.get("status") != "partial" or "legend_zone_object" not in fiery.get("unsupported_mechanics", []):
        errors.append("Annie - Fiery must derive partial naming the unmodelled Legend object")
    for card in programs["cards"]:
        for clause in card["clauses"]:
            execution = clause.get("execution", {})
            has_draw = any(effect.get("op") == "draw" for effect in execution.get("program", {}).get("effects", []))
            if has_draw and (clause.get("claim") == "full" or "burn_out" not in clause.get("unsupported_mechanics", [])):
                errors.append(f"{clause['clause_id']} uses draw while Burn Out is unsupported, but does not derive partial with burn_out named")
    if rows.get("pouty poro#f8dcb74f:missing_information", {}).get("outcome") != "decision_required":
        errors.append("two Power domains for a Deflect cost were not left to the opponent's allocation")
    if rows.get("traveling merchant#92d985e1:recall_is_not_a_move", {}).get("outcome") != "supported":
        errors.append("the recall probe for Traveling Merchant did not run")
    # C-32 (ADR-0008 §11): every R3-A3 clause is in the pack; vanilla Units are
    # probed through a named intrinsic behaviour and carry no invented program;
    # Tank fixtures cover Backline and the Tank+Backline choice; Cannon Barrage
    # has its no-Combat no-op; Fortified Position its uncontrolled case; the
    # Legend clause stays partial; combat scenarios and declarations are portable.
    r3a3 = {c["clause_id"] for card in inventory["cards"] for c in card["clauses"] if "R3-A3" in c["notes"]}
    if missing := sorted(r3a3 - in_pack):
        errors.append(f"R3-A3 clauses absent from the pack: {missing}")
    for card in programs["cards"]:
        for clause in card["clauses"]:
            execution = clause.get("execution") or {}
            fixtures = clause.get("fixtures", [])
            if clause["text"] == "(no rules text)" and (execution.get("intrinsic") != "unit_combat" or "program" in execution):
                errors.append(f"{clause['clause_id']}: a vanilla Unit must be probed through intrinsic unit_combat and carry no program")
            if clause["text"] == "[Tank]" and clause["claim"] in {"full", "partial"}:
                ids = {fx["fixture_id"].rsplit(":", 1)[1] for fx in fixtures}
                if not {"backline_before_plain", "both_requirements_choice", "both_requirements_tank", "both_requirements_backline", "two_tanks"} <= ids:
                    errors.append(f"{clause['clause_id']}: Tank claims full without the Backline and Tank+Backline fixtures (ADR-0008 §8)")
            if clause["clause_id"] == "cannon barrage#3c6691c9" and not any(fx.get("run") == "effect" and fx["kind"] == "negative" for fx in fixtures):
                errors.append("Cannon Barrage lacks the no-Combat no-op fixture")
            if clause["clause_id"] == "fortified position#d0ee5f77" and not any(fx["fixture_id"].endswith(":uncontrolled") for fx in fixtures):
                errors.append("Fortified Position lacks the uncontrolled-Battlefield fixture (190.6.d)")
            for fx in fixtures:
                if fx.get("run") in rp.COMBAT_RUNS and not (fx.get("combat") or fx.get("run") == "standard_move"):
                    errors.append(f"{fx['fixture_id']} runs a combat path without a combat block")
    wuju = manifest_rows.get("master yi - wuju bladesman (starter)#96ecd8e6", {})
    if wuju.get("status") != "partial" or "legend_zone_object" not in wuju.get("unsupported_mechanics", []):
        errors.append("Master Yi - Wuju Bladesman must derive partial naming the unmodelled Legend object")
    for cid in ("mountain drake#a95a0531", "playful phantom#a95a0531"):
        row = manifest_rows.get(cid, {})
        if row.get("status") != "full" or not row.get("program_id", "").startswith("intrinsic:unit_combat:") or row.get("implemented_ops"):
            errors.append(f"{cid} derived {row.get('status')} / {row.get('program_id')}; expected full with an intrinsic probe and no ops")
    for cid in ("master yi - honed#ba87989e", "stalwart poro#8b9eb35a", "zephyr sage#8b9eb35a", "wielder of water#d2dd9c3e", "cannon barrage#3c6691c9", "fortified position#d0ee5f77", "fortified position#9b46c0cf", "gentlemen's duel#fd48e5d0"):
        if manifest_rows.get(cid, {}).get("status") != "full":
            errors.append(f"{cid} derived {manifest_rows.get(cid, {}).get('status')}; its procedure gates pass, so the fixtures must carry it to full")
    # Codex Round D: the Combat Damage assignment is a bounded slice of 465.2.c
    # (Prevent-only preview, no damage-exemption sources) and the mutual Deal
    # batch is bounded (Prevent-only, no shared descriptor): those clauses stay
    # partial naming the gap, whatever their fixtures pass.
    for cid, gaps in (("maddened marauder#7a66c5e8", {"damage_exemption_sources", "assignment_replacement_modes"}), ("stormclaw ursine#7a66c5e8", {"damage_exemption_sources", "assignment_replacement_modes"}), ("gentlemen's duel#26a3859b", {"simultaneous_replacement_modes"})):
        row = manifest_rows.get(cid, {})
        if row.get("status") != "partial" or not gaps <= set(row.get("unsupported_mechanics", [])):
            errors.append(f"{cid} must derive partial naming {sorted(gaps)}; got {row.get('status')} {row.get('unsupported_mechanics')}")
    # committed outputs are current and deterministic
    outs = rp.outputs()
    for path, text in outs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            errors.append(f"{path.name} is stale; re-run r3a1_programs.py and commit the diff")
    if rp.outputs() != outs:
        errors.append("program run is not deterministic")
    inv_text = (rp.PACK / "inventory.draft.json").read_text(encoding="utf-8")
    if '"program_id": "' in inv_text:
        errors.append("inventory.draft.json gained a program_id; the draft must stay a draft")
    run = subprocess.run([sys.executable, str(SCRIPT_DIR / "r3a1_programs.py"), "--check"], cwd=Path.home(), text=True, capture_output=True, check=False)
    if run.returncode != 0:
        errors.append(f"off-cwd run failed: {run.stderr.strip()}")

    counts = {s: sum(1 for c in manifest["cards"] for cl in c["clauses"] if cl["status"] == s) for s in ("full", "partial", "unsupported", "stale")}
    fixtures = sum(1 for c in report["cards"] for cl in c["clauses"] for r in cl["fixtures"] if not r.get("skipped"))
    if errors:
        print("FAILED: R3-A1 program checks" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print(f"OK: R3-A1 / R3-A2 / R3-A3 card programs — {len(manifest['cards'])} cards, {fixtures} fixtures passing with cited expectations; derived clause statuses full={counts['full']} partial={counts['partial']} unsupported={counts['unsupported']} stale={counts['stale']}; manifest draft, validated, deterministic, inventory untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
