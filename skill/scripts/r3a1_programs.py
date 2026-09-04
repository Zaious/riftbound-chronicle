#!/usr/bin/env python3
"""
R3-A1 card programs: portable templates, per-scenario binding, fixture runs,
and the derived behavior manifest (C-18; ADR-0004, ADR-0005; Codex Round B).

`r3a1_programs.json` holds card-program *templates* with symbolic references
— `$controller`, `$opponent`, `$card`, `$chain_item`, `$source_object` — and
never a literal player id. `bind(template, bindings)` is a pure function that
turns a template into a concrete `effect-program.v1` (or play declaration)
for one scenario. Fixtures carry their `bindings`; the runner materialises
the state from `check_effect_ir.base_state()`, binds, runs through the same
play / resolution / effect runners as the engine-check CLI, and compares
against expectations written from the cited Core clause.

Portability is checked, not assumed: every fixture that runs a program is
also run **mirrored** — players swapped in state, timing and bindings — and
the mirrored result must equal the mirror of the original result. A clause
whose template contains a literal player, or whose mirrored run diverges,
cannot be `full` or `partial` whatever its claim says.

The manifest is derived: `full` needs a passing positive and negative
fixture, portability, and no unsupported mechanic; `partial` the same plus a
named one; a failing fixture demotes to `unsupported`; a clause the inventory
marks `stale` stays stale with no program_id. The manifest stays `draft`
(ADR-0004 activation gates).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PACK = SKILL_DIR / "data" / "card_program_packs" / "global-core-origins-v1"
PROGRAMS_PATH = PACK / "r3a1_programs.json"
MANIFEST_PATH = PACK / "r3a1_behavior_manifest.json"
REPORT_PATH = PACK / "R3A1_PROGRAMS.md"
sys.path.insert(0, str(SCRIPT_DIR))

from card_behavior_coverage import validate_manifest  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture as timing_fixture, item as timing_item  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, current_might, hash_value, object_identity  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import state_hash  # noqa: E402

PROGRAMS_VERSION = "r3a1-card-programs.v2"
CLAIMS = {"full", "partial", "unsupported", "stale"}
FIXTURE_KINDS = {"positive", "negative", "missing_information", "target_invalidated", "not_applicable"}
SYMBOLS = ("$controller", "$opponent", "$card", "$chain_item", "$source_object")
PLAYERS = ("p1", "p2")
CLOSED_WINDOW = {"add_window_closed": True, "confirmed_by": "fixture: human-confirmed closed Add window"}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def load_programs() -> dict[str, Any]:
    return json.loads(PROGRAMS_PATH.read_text(encoding="utf-8"))


def load_inventory() -> dict[str, Any]:
    return json.loads((PACK / "inventory.draft.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- binding --

def literal_players(value: Any) -> list[str]:
    """Every literal player id inside a template — a portable template has none."""
    found: list[str] = []
    if isinstance(value, dict):
        for v in value.values():
            found += literal_players(v)
    elif isinstance(value, list):
        for v in value:
            found += literal_players(v)
    elif isinstance(value, str) and value in PLAYERS:
        found.append(value)
    return found


def bind(template: Any, bindings: dict[str, str]) -> Any:
    """Pure: substitute symbolic references; an unbound symbol is an error."""
    if isinstance(template, dict):
        return {k: bind(v, bindings) for k, v in template.items()}
    if isinstance(template, list):
        return [bind(v, bindings) for v in template]
    if isinstance(template, str) and template.startswith("$"):
        key = template[1:]
        if key not in bindings:
            raise ValueError(f"unbound symbol {template}")
        return bindings[key]
    return template


_PLAYER_TOKEN = re.compile(r"(p1|p2)")


def swap_players(value: Any) -> Any:
    """Mirror a state / timing state / bindings / result: p1 ↔ p2 everywhere,
    including inside composite strings such as `base:p1` or `p1.hand`."""
    if isinstance(value, dict):
        return {swap_players(k): swap_players(v) for k, v in value.items()}
    if isinstance(value, list):
        return [swap_players(v) for v in value]
    if isinstance(value, tuple):
        return tuple(swap_players(v) for v in value)
    if isinstance(value, str):
        return _PLAYER_TOKEN.sub(lambda m: "p2" if m.group(1) == "p1" else "p1", value)
    return value


# ------------------------------------------------------------- materialise --

def _timing(kind: str) -> dict[str, Any]:
    if kind == "open":
        return timing_fixture()
    if kind == "closed_p1_priority":
        return timing_fixture(priority="p1", items=[timing_item("spell-0", "p2", "spell", "default")])
    if kind == "closed_p2_priority":
        return timing_fixture(priority="p2", items=[timing_item("spell-0", "p2", "spell", "default")])
    if kind == "resolution":
        return timing_fixture(priority="p2", items=[timing_item("spell-1", "p1", "spell", "default", "finalized")], passes=["p1", "p2"])
    raise ValueError(f"unknown timing fixture {kind!r}")


def _detach(state: dict[str, Any], object_id: str) -> None:
    for player in state["players"].values():
        for ids in player["zones"].values():
            if object_id in ids:
                ids.remove(object_id)
    for bf in state["battlefields"].values():
        if object_id in bf["objects"]:
            bf["objects"].remove(object_id)


def materialise(setup: list[dict[str, Any]]) -> dict[str, Any]:
    state = base_state()
    for edit in setup or []:
        if "move" in edit:
            _detach(state, edit["move"])
            dest = edit["to"]
            if dest.startswith("base:"):
                state["players"][dest.split(":", 1)[1]]["zones"]["base"].append(edit["move"])
            else:
                state["battlefields"][dest]["objects"].append(edit["move"])
        elif "to_hand" in edit:
            obj = edit["to_hand"]; _detach(state, obj)
            state["players"][state["objects"][obj]["owner"]]["zones"]["hand"].append(obj)
        elif "to_trash" in edit:
            obj = edit["to_trash"]; _detach(state, obj)
            state["players"][state["objects"][obj]["owner"]]["zones"]["trash"].append(obj)
        elif "to_deck_top" in edit:
            obj = edit["to_deck_top"]; _detach(state, obj)
            state["players"][state["objects"][obj]["owner"]]["zones"]["main_deck"].insert(0, obj)
        elif "set" in edit:
            state["objects"][edit["set"]][edit["field"]] = edit["value"]
        elif "resources" in edit:
            state["players"][edit["resources"]]["resources"] = {"energy": edit["energy"], "power": dict(edit.get("power", {}))}
        elif "replacement" in edit:
            state["replacement_effects"].append(copy.deepcopy(edit["replacement"]))
        elif "might_mod" in edit:
            state["objects"][edit["might_mod"]]["might_modifiers"].append({"amount": edit["amount"], "duration": "this_turn", "source": edit.get("source", "reaction")})
        elif "identity" in edit:
            state["objects"][edit["identity"]]["identity"] = edit["value"]
        else:
            raise ValueError(f"unknown setup edit {edit}")
    return state


def _program(template: dict[str, Any], bindings: dict[str, str]) -> dict[str, Any]:
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "controller": bindings["controller"]}
    program.update(bind(copy.deepcopy(template), bindings))
    return program


def _compile_targets(program: dict[str, Any], fixture: dict[str, Any], state: dict[str, Any]) -> None:
    """The post-play form: decision_refs replaced by concrete selectors bound to
    the identities the objects had when chosen (ADR-0005 §1, §3)."""
    single = fixture.get("compiled_target")
    multi = fixture.get("compiled_targets")
    for effect in program["effects"]:
        if single and effect.get("effect_id") == single["effect_id"] and isinstance(effect.get("target"), dict):
            selector = {k: v for k, v in effect["target"].items() if k != "decision_ref"}
            selector["object_id"] = single["object_id"]
            selector["bound_identity"] = single.get("bound_identity") or object_identity(state, single["object_id"]) or f"{single['object_id']}@0"
            effect["target"] = selector
            effect.setdefault("object_id", single["object_id"])
        if multi and effect.get("effect_id") == multi["effect_id"] and isinstance(effect.get("targets"), dict):
            restrictions = effect["targets"].get("restrictions", {})
            selectors = []
            for object_id in multi["object_ids"]:
                selector = dict(restrictions)
                selector["object_id"] = object_id
                selector["bound_identity"] = (multi.get("bound_identities") or {}).get(object_id) or object_identity(state, object_id) or f"{object_id}@0"
                selectors.append(selector)
            effect["targets"] = {"min": effect["targets"]["min"], "max": effect["targets"]["max"], "selectors": selectors}


def _decisions(fixture: dict[str, Any], state: dict[str, Any], bindings: dict[str, str]) -> dict[str, Any] | None:
    entries = fixture.get("decisions")
    if not entries:
        return None
    out = []
    for entry in entries:
        entry = bind(copy.deepcopy(entry), bindings)
        if entry["kind"] == "target_selection" and "selection_identities" not in entry:
            entry["selection_identities"] = {o: object_identity(state, o) or f"{o}@0" for o in entry["value"]}
        out.append(entry)
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": out}


def _declaration(clause: dict[str, Any], fixture: dict[str, Any], program_id: str | None, bindings: dict[str, str]) -> dict[str, Any]:
    template = fixture.get("play_declaration") or clause["execution"].get("play_declaration") or clause["execution"].get("declaration")
    declaration = {"schema_version": DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                   "play_id": f"play:{fixture['fixture_id']}", "actor": "$controller", "card": "$card"}
    declaration.update(copy.deepcopy(template))
    if program_id and "effect_program_id" not in declaration:
        declaration["effect_program_id"] = program_id
    # Core 429.3: fixtures state a human-confirmed closed Add window unless the
    # fixture is about the window itself (payment_context: null).
    if "payment_context" in fixture:
        if fixture["payment_context"] is not None:
            declaration["payment_context"] = fixture["payment_context"]
    else:
        declaration.setdefault("payment_context", dict(CLOSED_WINDOW))
    return bind(declaration, bindings)


# ------------------------------------------------------------------- running --

def _execute(clause: dict[str, Any], fixture: dict[str, Any], receipts: dict[str, dict[str, Any]], bindings: dict[str, str], *, mirrored: bool = False) -> dict[str, Any]:
    """One run of a fixture under given bindings. Returns the engine result,
    the engine-check, and the next state, or raises for malformed fixtures."""
    execution = clause["execution"]
    kind = execution["kind"]
    template = execution.get("program")
    program_id = template["program_id"] if template else None
    mirror = swap_players if mirrored else (lambda v: v)

    if fixture.get("receipt_from", "absent") != "absent":
        source = fixture["receipt_from"]
        state = receipts[source]["state"] if source else materialise([])
        state = mirror(state)
        program = _program(template, bindings)
        if source:
            program["cost_receipt"] = mirror(receipts[source]["receipt"])
        result = apply_program(state, program)
        check = build_engine_check("effect", result, input_hashes={"effect_state": hash_value(state), "effect_program": canonical_hash(program)})
        return {"result": result, "check": check, "next_state": result.get("next_state"), "state": state}
    if kind == "play" or fixture.get("timing") not in (None, "resolution"):
        timing = mirror(_timing(fixture["timing"]))
        state = mirror(materialise(fixture.get("setup")))
        decisions = _decisions(fixture, state, bindings)
        program = _program(template, bindings) if template else None
        declaration = _declaration(clause, fixture, program_id, bindings)
        result = play_card(timing, state, declaration, engine_decisions=decisions, effect_program=program)
        check = build_engine_check("play", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "play_declaration": canonical_hash(declaration)})
        if result.get("committed") and not mirrored:
            receipts[fixture["fixture_id"]] = {"receipt": result["cost_receipt"], "state": result["next_effect_state"]}
        return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing}
    if kind == "resolution":
        timing = mirror(_timing(fixture["timing"]))
        state = mirror(materialise(fixture.get("setup")))
        program = _program(template, bindings)
        _compile_targets(program, fixture, state)
        result = resolve_with_program(timing, bindings["chain_item"], state, program)
        check = build_engine_check("resolution", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "effect_program": canonical_hash(program)})
        return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing}
    state = mirror(materialise(fixture.get("setup")))
    program = _program({**template, **fixture.get("program_override", {})}, bindings)
    result = apply_program(state, program)
    check = build_engine_check("effect", result, input_hashes={"effect_state": hash_value(state), "effect_program": canonical_hash(program)})
    return {"result": result, "check": check, "next_state": result.get("next_state"), "state": state}


def _compare(fixture: dict[str, Any], run: dict[str, Any]) -> list[str]:
    expected = fixture["expected"]
    result, check, next_state = run["result"], run["check"], run["next_state"]
    problems: list[str] = []
    if check["outcome"] != expected["outcome"]:
        problems.append(f"outcome {check['outcome']!r}, expected {expected['outcome']!r} ({check['reason']['message'][:160]})")
    if "reason_code" in expected and result.get("reason_code") != expected["reason_code"]:
        problems.append(f"reason_code {result.get('reason_code')!r}, expected {expected['reason_code']!r}")
    if "trace_outcomes" in expected:
        trace = result.get("trace")
        events = trace.get("effect", []) if isinstance(trace, dict) else (trace or [])
        got = [e.get("outcome") for e in events if isinstance(e, dict) and "op" in e]
        if got != expected["trace_outcomes"]:
            problems.append(f"trace outcomes {got}, expected {expected['trace_outcomes']}")
    if "trace_target_outcome" in expected:
        events = result.get("trace", {}).get("effect", []) if isinstance(result.get("trace"), dict) else []
        got = events[0].get("target_outcome") if events else None
        if got != expected["trace_target_outcome"]:
            problems.append(f"target_outcome {got!r}, expected {expected['trace_target_outcome']!r}")
    if expected.get("assert_rolled_back") and (result.get("next_effect_state_hash") != hash_value(run["state"]) or result.get("rolled_back") is not True):
        problems.append("play was not rolled back to the input state")
    for item in expected.get("assert", []):
        if "receipt_paid" in item:
            comp = next((c for c in result.get("cost_receipt", {}).get("components", []) if c["cost_id"] == item["receipt_paid"]), {})
            if comp.get("paid") != item["equals"]:
                problems.append(f"receipt component {item['receipt_paid']} paid={comp.get('paid')}, expected {item['equals']}")
        elif "chain_items" in item:
            items = [i["id"] for i in result.get("next_timing_state", {}).get("chain", {}).get("items", [])]
            if items != item["chain_items"]:
                problems.append(f"timing chain items {items}, expected {item['chain_items']}")
        elif "field" in item:
            value = next_state
            for key in item["field"]:
                value = (value or {}).get(key)
            if value != item["equals"]:
                problems.append(f"{'.'.join(item['field'])} = {value!r}, expected {item['equals']!r}")
        elif "in" in item:
            zone = item["in"]
            if zone.startswith("bf"):
                present = item["object"] in (next_state or {}).get("battlefields", {}).get(zone, {}).get("objects", [])
            else:
                player, name = zone.split(".", 1)
                present = item["object"] in (next_state or {}).get("players", {}).get(player, {}).get("zones", {}).get(name, [])
            if not present:
                problems.append(f"{item['object']} not in {zone}")
        elif "might" in item:
            obj = (next_state or {}).get("objects", {}).get(item["might"])
            if obj is None or current_might(obj) != item["equals"]:
                problems.append(f"might of {item['might']} is {current_might(obj) if obj else None}, expected {item['equals']}")
        elif "hand_size" in item:
            size = len((next_state or {}).get("players", {}).get(item["hand_size"], {}).get("zones", {}).get("hand", []))
            if size != item["equals"]:
                problems.append(f"{item['hand_size']} hand size {size}, expected {item['equals']}")
    return problems


def _strip_volatile(result: dict[str, Any]) -> dict[str, Any]:
    """Drop hashes and ids that legitimately differ between a run and its mirror."""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if not (k.endswith("_hash") or k in {"input_hashes", "check_id", "result_hash", "play_id", "chain_item_id", "program_id", "manifest_id"})}
        if isinstance(v, list):
            return [strip(x) for x in v]
        if isinstance(v, str) and v.startswith("sha256:"):
            return "<hash>"
        return v
    return strip(result)


def run_fixture(clause: dict[str, Any], fixture: dict[str, Any], receipts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if fixture.get("kind") == "not_applicable":
        return {"fixture_id": fixture["fixture_id"], "kind": "not_applicable", "passed": True, "skipped": True, "mirrored": None}
    bindings = fixture["bindings"]
    run = _execute(clause, fixture, receipts, bindings)
    problems = _compare(fixture, run)
    # Portability: the same template bound to the other seat, on the mirrored
    # scenario, must produce the mirror of the same result.
    mirrored_ok = None
    if clause["execution"].get("program") is not None or clause["execution"]["kind"] == "play":
        mirrored_bindings = swap_players(bindings)
        try:
            twin = _execute(clause, fixture, receipts, mirrored_bindings, mirrored=True)
            mirrored_ok = _strip_volatile(swap_players(twin["result"])) == _strip_volatile(run["result"])
            if not mirrored_ok:
                problems.append("mirrored binding (players swapped) did not produce the player-relative same result")
        except Exception as exc:  # noqa: BLE001 — a mirrored run that cannot even execute is a portability failure
            mirrored_ok = False
            problems.append(f"mirrored run failed: {exc}")
    return {"fixture_id": fixture["fixture_id"], "kind": fixture["kind"], "passed": not problems, "problems": problems,
            "outcome": run["check"]["outcome"], "check_id": run["check"]["check_id"], "mirrored": mirrored_ok,
            "rule_locators": fixture["expected"].get("rule_locators", [])}


def run_all(programs: dict[str, Any] | None = None) -> dict[str, Any]:
    programs = programs or load_programs()
    receipts: dict[str, dict[str, Any]] = {}
    report = {"schema_version": "r3a1-program-run.v2", "cards": []}
    for card in programs["cards"]:
        card_rows = []
        for clause in card["clauses"]:
            rows = [run_fixture(clause, fx, receipts) for fx in clause.get("fixtures", [])]
            card_rows.append({"clause_id": clause["clause_id"], "claim": clause["claim"], "portable": template_is_portable(clause), "fixtures": rows})
        report["cards"].append({"card": card["card"], "clauses": card_rows})
    return report


# ------------------------------------------------------------------ manifest --

def template_is_portable(clause: dict[str, Any]) -> bool:
    execution = clause.get("execution")
    if not execution:
        return True
    return not literal_players({k: v for k, v in execution.items() if k in {"program", "declaration", "play_declaration"}})


def derive_status(clause: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[str, str]:
    claim = clause["claim"]
    real = [r for r in rows if not r.get("skipped")]
    failed = [r["fixture_id"] for r in real if not r["passed"]]
    kinds = {r["kind"] for r in real if r["passed"]}
    if claim in {"stale", "unsupported"}:
        return claim, "no program is activated for this clause"
    if not template_is_portable(clause):
        return "unsupported", "template carries a literal player id; not a portable card program"
    if failed:
        return "unsupported", f"claimed {claim} but fixtures failed: {failed}"
    if not {"positive", "negative"} <= kinds:
        return "unsupported", f"claimed {claim} without a passing positive and negative fixture"
    if any(r.get("mirrored") is False for r in real):
        return "unsupported", "mirrored binding diverged; template is not portable"
    if claim == "full" and clause.get("unsupported_mechanics"):
        return "partial", "claimed full while naming unsupported mechanics"
    if claim == "partial" and not clause.get("unsupported_mechanics"):
        return "full", "claimed partial without naming an unsupported mechanic"
    return claim, "every fixture passed, mirrored bindings agree"


def build_manifest(programs: dict[str, Any] | None = None, report: dict[str, Any] | None = None) -> dict[str, Any]:
    programs = programs or load_programs()
    report = report or run_all(programs)
    inventory = load_inventory()
    inv_cards = {c["card_key"]: c for c in inventory["cards"]}
    runs = {c["card"]: {cl["clause_id"]: cl["fixtures"] for cl in c["clauses"]} for c in report["cards"]}
    cards = []
    for card in programs["cards"]:
        inv = inv_cards[card["card_key"]]
        inv_clauses = {c["clause_id"]: c for c in inv["clauses"]}
        clause_rows = []
        for clause in card["clauses"]:
            base = inv_clauses[clause["clause_id"]]
            rows = runs[card["card"]][clause["clause_id"]]
            status, reason = derive_status(clause, rows)
            if base["status"] == "stale":
                status, reason = "stale", "bundled snapshot still carries pre-errata wording; program written against errata text awaits reverification"
            execution = clause.get("execution", {})
            program_id = execution["program"]["program_id"] if status in {"full", "partial"} and "program" in execution else (
                f"play:{clause['clause_id']}" if status in {"full", "partial"} else None)
            ops = sorted({e["op"] for e in execution.get("program", {}).get("effects", [])}) if status in {"full", "partial"} else []
            if status in {"full", "partial"} and execution.get("kind") == "play":
                declaration = execution.get("declaration", {})
                ops = sorted({add["payment"]["kind"] for add in declaration.get("cost", {}).get("additional", []) if add["payment"]["kind"] in {"exhaust", "kill"}})
            unsupported = list(clause.get("unsupported_mechanics", [])) if status in {"partial", "unsupported"} else (base["unsupported_mechanics"] if status in {"unsupported", "stale"} else [])
            if status == "unsupported" and not unsupported:
                unsupported = list(base["unsupported_mechanics"]) or ["fixtures_not_passing"]
            clause_rows.append({
                "clause_id": clause["clause_id"], "source_id": base["source_id"], "locator": base["locator"], "text_hash": base["text_hash"],
                "status": status, "program_id": program_id, "implemented_ops": ops, "unsupported_mechanics": unsupported,
                "test_ids": [r["fixture_id"] for r in rows if not r.get("skipped") and r["passed"]] if status in {"full", "partial"} else [],
                "notes": f"C-18 derived: {reason}. text: {clause['text']} | rules: {', '.join(clause.get('rule_locators', []))}",
            })
        statuses = {c["status"] for c in clause_rows}
        card_status = "stale" if "stale" in statuses else ("full" if statuses == {"full"} else ("unsupported" if statuses == {"unsupported"} else "partial"))
        cards.append({"card_key": card["card_key"], "canonical_name": inv["canonical_name"], "current_text_hash": inv["current_text_hash"],
                      "printing_ids": inv["printing_ids"], "behavior_status": card_status, "clauses": clause_rows})
    content = {"pack_id": inventory["pack_id"], "status": "draft", "ruleset": inventory["ruleset"], "environment": inventory["environment"],
               "verified_at": inventory["verified_at"], "cards": cards}
    manifest = {"schema_version": "card-behavior-manifest.v1", "manifest_id": f"manifest:{canonical_hash(content).split(':', 1)[1][:24]}", **content}
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("derived manifest is invalid: " + "; ".join(errors))
    return manifest


def render_report(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = ["# R3-A1 card programs — fixture run and derived statuses", "",
             "Generated by `r3a1_programs.py`. Templates carry symbolic references and are bound per fixture; every program fixture also runs mirrored (players swapped) and must agree. Statuses are derived from fixtures passing against the engine, never copied from a claim. The manifest stays `draft`; nothing here activates a pack.", ""]
    statuses = {c["clause_id"]: c["status"] for card in manifest["cards"] for c in card["clauses"]}
    card_statuses = {c["canonical_name"]: c["behavior_status"] for c in manifest["cards"]}
    for card in report["cards"]:
        name = next(c["canonical_name"] for c in manifest["cards"] if c["clauses"][0]["clause_id"] == card["clauses"][0]["clause_id"])
        lines += [f"## {name} — `{card_statuses[name]}`", "", "| Clause | Claim | Portable | Derived | Fixtures |", "| --- | --- | --- | --- | --- |"]
        for cl in card["clauses"]:
            cells = ", ".join(
                f"{r['kind']}: n/a" if r.get("skipped") else f"{r['kind']}: {'pass' if r['passed'] else 'FAIL'}" + ("" if r.get("mirrored") is None else (" ⇄" if r["mirrored"] else " ⇄FAIL"))
                for r in cl["fixtures"]) or "—"
            lines.append(f"| `{cl['clause_id']}` | {cl['claim']} | {'yes' if cl['portable'] else 'no'} | **{statuses[cl['clause_id']]}** | {cells} |")
        lines.append("")
    lines.append("⇄ = the mirrored binding (players swapped) produced the player-relative same result.")
    return "\n".join(lines)


def outputs() -> dict[Path, str]:
    programs = load_programs()
    report = run_all(programs)
    manifest = build_manifest(programs, report)
    return {MANIFEST_PATH: json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", REPORT_PATH: render_report(report, manifest) + "\n"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind R3-A1 card-program templates, run their fixtures, derive the behavior manifest.")
    parser.add_argument("--check", action="store_true", help="fail if committed outputs differ from a fresh build")
    args = parser.parse_args(argv)
    outs = outputs()
    if args.check:
        stale = [p.name for p, text in outs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print(f"FAILED: stale R3-A1 program outputs {stale}; re-run r3a1_programs.py and commit the diff", file=sys.stderr)
            return 1
        print("OK: R3-A1 program outputs are current")
        return 0
    for path, text in outs.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
