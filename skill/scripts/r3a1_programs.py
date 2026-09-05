#!/usr/bin/env python3
"""
R3-A1 / R3-A2 card programs: portable templates, per-scenario binding,
fixture runs, and the derived behavior manifest (C-18, C-25; ADR-0004,
ADR-0005, ADR-0007; Codex Rounds B and C).

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

C-25 (ADR-0007) adds three template pieces. A clause may carry a `passive`:
the state the card contributes while it exists (an object's play_triggers,
move_triggers, entry_replacements, play_permissions, keywords,
conditional_might, or a state-level damage_modifiers entry), written with
the same symbols and applied to the scenario before it runs. A fixture may
name a `probe` — a program or play declaration that is not the card's own
text but exercises the passive (an opponent's spell choosing a Deflect
unit, a Move that raises a move trigger) — and a `run` path: `play`,
`resolution`, `effect`, or `play_entry` (a permanent is played with its
entry_location and then resolves by the entry procedure, so "When you play
me" is observed as the Pending item it schedules). A passive-only clause
derives `program_id` passive:<clause_id> with no implemented ops.

C-32 (ADR-0008) adds Combat scenarios. A fixture with a `combat` block
({battlefield, attacker: $controller | $opponent, phase: open |
showdown_closed}) is staged and opened by the real procedures after its
setup (Contested applied by the named attacker), optionally closed by every
player passing Focus, and optionally edited afterwards (`after_combat_setup`,
for Units that arrive after the opening); the Combat's id is then bound as
`$combat_id`, also inside composite strings such as decision ids. Runs:
`combat_open` observes the opening itself (designations, Combat Chain,
Battlefield triggers, the reads of effective_might); `combat_step` runs one
named Combat step (`assign`, `deal`, ...) with procedure-stage decisions
bound to the combined timing/effect hash; `standard_move` runs the player
action with a bound declaration; `resolution` / `effect` under a `combat`
block resolve on the Combat Chain (a spell, or a `triggered` item of the
bound source) with the Combat context. A vanilla Unit declares
`intrinsic: unit_combat` and is probed, never given invented text.
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
from combat import STEPS as COMBAT_STEPS, combined_input_hash, open_combat, stage_combat, standard_move  # noqa: E402
from check_rules_core import fixture as timing_fixture, item as timing_item  # noqa: E402
from effect_ir import CORE_RULESET, FAQ_AS_OF, PROGRAM_VERSION, apply_program, current_might, effective_might, entity_identity, hash_value, object_identity  # noqa: E402
from engine_check import build_engine_check  # noqa: E402
from play_transaction import DECLARATION_VERSION, play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402
from rules_core import pass_focus, state_hash  # noqa: E402

PROGRAMS_VERSION = "r3a1-card-programs.v3"
CLAIMS = {"full", "partial", "unsupported", "stale"}
FIXTURE_KINDS = {"positive", "negative", "missing_information", "target_invalidated", "not_applicable"}
SYMBOLS = ("$controller", "$opponent", "$card", "$chain_item", "$source_object", "$combat_id")
# Bound by the engine when the effect runs (grant_replacement binds
# $granted_target at grant time), never by a scenario.
ENGINE_SYMBOLS = {"$granted_target"}
COMBAT_RUNS = {"combat_open", "combat_step", "standard_move"}
RUNS = {"play", "resolution", "effect", "play_entry"} | COMBAT_RUNS
_SYMBOL_TOKEN = re.compile(r"\$([a-z_]+)")
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
    elif isinstance(value, str):
        found += _PLAYER_TOKEN.findall(value)  # same word-bound token as swap_players: base:p1, p2.hand, ...
    return found


def bind(template: Any, bindings: dict[str, str]) -> Any:
    """Pure: substitute symbolic references; an unbound symbol is an error."""
    if isinstance(template, dict):
        return {(bind(k, bindings) if isinstance(k, str) and "$" in k else k): bind(v, bindings) for k, v in template.items()}  # keys bind too (unit_identities)
    if isinstance(template, list):
        return [bind(v, bindings) for v in template]
    if isinstance(template, str) and "$" in template:
        if template in ENGINE_SYMBOLS:
            return template

        def substitute(match: re.Match) -> str:
            key = match.group(1)
            if key not in bindings:
                raise ValueError(f"unbound symbol ${key}")
            return bindings[key]
        return _SYMBOL_TOKEN.sub(substitute, template)  # whole symbols and composites such as "damage_assignment:$combat_id:attacker"
    return template


_PLAYER_TOKEN = re.compile(r"\b(p1|p2)\b")


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
        return _resolution_timing()
    if kind == "open_opponent_turn":
        # the opponent's Neutral Open state: their turn, their priority
        timing = timing_fixture(priority="p2")
        timing["turn_player"] = "p2"
        timing["turn_order"] = ["p2", "p1"]
        return timing
    raise ValueError(f"unknown timing fixture {kind!r}")


def _resolution_timing(item_id: str = "spell-1", object_kind: str = "spell", actor: str = "p1") -> dict[str, Any]:
    """The actor's finalized item about to resolve on the actor's turn, both
    players having passed. Built with p1 and mirrored per run, or built from
    an already-bound actor."""
    other = "p2" if actor == "p1" else "p1"
    timing = timing_fixture(priority=other, items=[timing_item(item_id, actor, object_kind, "default", "finalized")], passes=[actor, other])
    timing["players"] = [actor, other]
    timing["turn_player"] = actor
    timing["turn_order"] = [actor, other]
    return timing


def _detach(state: dict[str, Any], object_id: str) -> None:
    for player in state["players"].values():
        for ids in player["zones"].values():
            if object_id in ids:
                ids.remove(object_id)
    for bf in state["battlefields"].values():
        if object_id in bf["objects"]:
            bf["objects"].remove(object_id)


def _place(state: dict[str, Any], object_id: str, dest: str) -> None:
    """dest: base:<player> | <battlefield id> | hand:<player> | trash:<player> | rune_deck:<player> | main_deck:<player>."""
    if ":" in dest:
        zone, player = dest.split(":", 1)
        state["players"][player]["zones"][zone].append(object_id)
    else:
        state["battlefields"][dest]["objects"].append(object_id)


def _new_object(owner: str, **fields: Any) -> dict[str, Any]:
    return {"owner": owner, "controller": fields.pop("controller", owner), "kind": fields.pop("kind", "unit"), "base_might": fields.pop("might", 0),
            "might_modifiers": [], "damage": fields.pop("damage", 0), "exhausted": fields.pop("exhausted", False), **fields}


def materialise(setup: list[dict[str, Any]]) -> dict[str, Any]:
    return apply_edits(base_state(), setup)


def apply_edits(state: dict[str, Any], setup: list[dict[str, Any]] | None) -> dict[str, Any]:
    for edit in setup or []:
        if "move" in edit:
            _detach(state, edit["move"])
            _place(state, edit["move"], edit["to"])
        elif "add" in edit:
            # a new object the base state lacks (a stand-in permanent, an extra unit)
            state["objects"][edit["add"]] = _new_object(edit["owner"], **{k: v for k, v in edit.items() if k not in {"add", "owner", "to"}})
            _place(state, edit["add"], edit.get("to", f"base:{edit['owner']}"))
        elif "add_runes" in edit:
            for n in range(edit["count"]):
                rune_id = f"{edit.get('prefix', 'rr')}{n + 1}"
                state["objects"][rune_id] = _new_object(edit["add_runes"], kind="rune", exhausted=bool(edit.get("exhausted", False)))
                _place(state, rune_id, edit.get("to", f"base:{edit['add_runes']}"))
        elif "turn_id" in edit:
            state["turn_id"] = edit["turn_id"]
        elif "turn_effect" in edit:
            state.setdefault("turn_effects", []).append(copy.deepcopy(edit["turn_effect"]))
        elif "damage_modifier" in edit:
            state.setdefault("damage_modifiers", []).append(copy.deepcopy(edit["damage_modifier"]))
        elif "battlefield" in edit:
            state["battlefields"].setdefault(edit["battlefield"], {"controller": None, "objects": []})[edit["field"]] = edit["value"]
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


def apply_passive(state: dict[str, Any], passive: dict[str, Any], bindings: dict[str, str]) -> None:
    """The state a card contributes while it exists (ADR-0007): fields on the
    bound object (default $source_object) and entries appended to state-level
    lists. Bound with the scenario's bindings, so a mirrored run mirrors it."""
    bound = bind(copy.deepcopy(passive), bindings)
    if bound.get("object_fields"):
        state["objects"][bound.get("object", bindings["source_object"])].update(bound["object_fields"])
    if bound.get("battlefield_fields"):
        state["battlefields"][bound.get("battlefield", bindings["source_object"])].update(bound["battlefield_fields"])
    for key, entries in (bound.get("state_lists") or {}).items():
        state.setdefault(key, []).extend(entries)


def _program(template: dict[str, Any], bindings: dict[str, str]) -> dict[str, Any]:
    program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}, "controller": bindings["controller"]}
    program.update(bind(copy.deepcopy(template), bindings))
    return program


def _compile_targets(program: dict[str, Any], fixture: dict[str, Any], state: dict[str, Any]) -> None:
    """The post-play form: decision_refs replaced by concrete selectors bound to
    the identities the objects had when chosen (ADR-0005 §1, §3)."""
    single = fixture.get("compiled_target")
    multi = fixture.get("compiled_targets")
    units = fixture.get("compiled_units")
    single_ids = (single.get("effect_ids") or [single["effect_id"]]) if single else []
    for effect in program["effects"]:
        if units and effect.get("effect_id") == units["effect_id"] and isinstance(effect.get("units"), list):
            compiled = []
            for selector, object_id in zip(effect["units"], units["object_ids"]):
                concrete = {k: v for k, v in selector.items() if k != "decision_ref"}
                concrete["object_id"] = object_id
                concrete["bound_identity"] = (units.get("bound_identities") or {}).get(object_id) or entity_identity(state, object_id) or f"{object_id}@0"
                compiled.append(concrete)
            effect["units"] = compiled
        if single and effect.get("effect_id") in single_ids and isinstance(effect.get("target"), dict):
            selector = {k: v for k, v in effect["target"].items() if k != "decision_ref"}
            selector["object_id"] = single["object_id"]
            selector["bound_identity"] = single.get("bound_identity") or entity_identity(state, single["object_id"]) or f"{single['object_id']}@0"
            effect["target"] = selector
            if not effect.get("affected"):  # an area instruction targets the battlefield; its units are not its object
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


def _decisions(fixture: dict[str, Any], state: dict[str, Any], bindings: dict[str, str], input_hash: str | None = None) -> dict[str, Any] | None:
    entries = fixture.get("decisions")
    if not entries:
        return None
    out = []
    for entry in entries:
        entry = bind(copy.deepcopy(entry), bindings)
        if entry["kind"] in {"target_selection", "card_selection"} and "selection_identities" not in entry:
            entry["selection_identities"] = {o: entity_identity(state, o) or f"{o}@0" for o in entry["value"]}
        if entry["kind"] == "damage_assignment" and "selection_identities" not in entry:
            amounts = entry["value"]["amounts"] if isinstance(entry["value"], dict) and "amounts" in entry["value"] else entry["value"]
            entry["selection_identities"] = {o: entity_identity(state, o) or f"{o}@0" for o in amounts}
        out.append(entry)
    return {"schema_version": "engine-decisions.v1", "input_hash": input_hash or hash_value(state), "decisions": out}


def _declaration(clause: dict[str, Any], fixture: dict[str, Any], program_id: str | None, bindings: dict[str, str]) -> dict[str, Any]:
    probe = fixture.get("probe") or clause["execution"].get("probe") or {}
    template = fixture.get("play_declaration") or probe.get("declaration") or clause["execution"].get("play_declaration") or clause["execution"].get("declaration")
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

def _combat_scenario(fixture: dict[str, Any], bindings: dict[str, str], mirror, state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    """Stage and open the fixture's Combat by the real procedures (ADR-0008
    §2), optionally close its Showdown by Focus passes, then apply the edits
    that happen after the opening. Returns (timing, effect, open result,
    bindings with $combat_id)."""
    spec = fixture["combat"]
    battlefield = spec.get("battlefield", "bf1")
    attacker = bind(spec.get("attacker", "$controller"), bindings)
    state["battlefields"][battlefield]["contested"] = True
    state["battlefields"][battlefield]["contested_by"] = attacker
    timing = mirror(_timing("open"))
    staged = stage_combat(timing, state)
    if not staged.get("committed"):
        raise ValueError(f"combat scenario could not stage: {staged.get('reason') or staged.get('errors')}")
    opened = open_combat(staged["next_timing_state"], state)
    if not opened.get("committed"):
        raise ValueError(f"combat scenario could not open: {opened.get('reason') or opened.get('errors')}")
    timing, state = opened["next_timing_state"], opened["next_effect_state"]
    if spec.get("phase") == "showdown_closed":
        if timing["chain"]["items"]:
            raise ValueError("the Combat Chain must resolve before the Showdown can close")
        focus = timing["showdown"]["focus"]
        order = timing["turn_order"]
        for player in order[order.index(focus):] + order[:order.index(focus)]:
            passed = pass_focus(timing, player)
            if not passed.get("applied"):
                raise ValueError(f"combat scenario could not pass Focus: {passed.get('reason_code')}")
            timing = passed["next_state"]
    if fixture.get("after_combat_setup"):
        state = apply_edits(copy.deepcopy(state), mirror(fixture["after_combat_setup"]))
    return timing, state, opened, {**bindings, "combat_id": timing["combat"]["combat_id"]}


def _combat_context(timing: dict[str, Any]) -> dict[str, Any]:
    record = timing["combat"]
    return {"combat": {"combat_id": record["combat_id"], "battlefield": record["battlefield"], "battlefield_identity": record["battlefield_identity"]}}


def _execute(clause: dict[str, Any], fixture: dict[str, Any], receipts: dict[str, dict[str, Any]], bindings: dict[str, str], *, mirrored: bool = False) -> dict[str, Any]:
    """One run of a fixture under given bindings. Returns the engine result,
    the engine-check, and the next state, or raises for malformed fixtures."""
    execution = clause["execution"]
    probe = fixture.get("probe") or execution.get("probe") or {}
    run = fixture.get("run") or execution["kind"]
    if run not in RUNS:
        raise ValueError(f"unknown run path {run!r}")
    template = probe.get("program") or execution.get("program")
    program_id = template["program_id"] if template else None
    mirror = swap_players if mirrored else (lambda v: v)

    def scenario() -> dict[str, Any]:
        state = mirror(materialise(fixture.get("setup")))
        if execution.get("passive"):
            apply_passive(state, execution["passive"], bindings)
        return state

    if fixture.get("combat"):
        before = scenario()
        timing, state, opened, bindings = _combat_scenario(fixture, bindings, mirror, before)
        if run == "combat_open":
            check = build_engine_check("combat_step", opened, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(before)})
            return {"result": opened, "check": check, "next_state": opened["next_effect_state"], "state": before, "timing": timing, "bindings": bindings}
        if run == "combat_step":
            decisions = _decisions(fixture, state, bindings, combined_input_hash(timing, state))
            result = COMBAT_STEPS[fixture["step"]](timing, state, decisions)
            check = build_engine_check("combat_step", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state)})
            return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing, "bindings": bindings}
        if run == "resolution":
            other = next(p for p in timing["players"] if p != bindings["controller"])
            scheduled = [i["id"] for i in timing["chain"]["items"]]
            if scheduled and fixture.get("chain_item_kind") == "triggered" and scheduled == [bindings["chain_item"]]:
                # the opening itself scheduled the bound trigger (a Battlefield's own): finalize it and let both players pass
                timing["chain"]["items"][0]["status"] = "finalized"
                timing["chain"]["consecutive_passes"] = [bindings["controller"], other]
            elif scheduled:
                raise ValueError(f"the fixture's Combat opened with a Combat Chain {scheduled}; resolve it first")
            elif fixture.get("chain_item_kind") == "triggered":
                item = timing_item(bindings["chain_item"], bindings["controller"], "ability", "triggered", "finalized", "standard")
                item.update({"source_object": bindings["source_object"], "effect_program_id": program_id, "optional_at_finalize": False, "trigger_kind": "triggered", "batch_sequence": 0, "batch_id": "fixture"})
                timing["chain"] = {"initiated_by": "triggered_ability", "items": [item], "consecutive_passes": [bindings["controller"], other]}
            else:
                timing["chain"] = {"initiated_by": "played_card", "items": [timing_item(bindings["chain_item"], bindings["controller"], "spell", "reaction", "finalized")], "consecutive_passes": [bindings["controller"], other]}
            timing["priority"] = other
            program = _program(template, bindings)
            _compile_targets(program, fixture, state)
            decisions = _decisions(fixture, state, bindings)
            result = resolve_with_program(timing, bindings["chain_item"], state, program, engine_decisions=decisions)
            check = build_engine_check("resolution", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "effect_program": canonical_hash(program)})
            return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing, "bindings": bindings}
        if run == "effect":
            program = _program({**template, **fixture.get("program_override", {})}, bindings)
            _compile_targets(program, fixture, state)
            decisions = _decisions(fixture, state, bindings)
            result = apply_program(state, program, decisions=decisions, context=_combat_context(timing))
            check = build_engine_check("effect", result, input_hashes={"effect_state": hash_value(state), "effect_program": canonical_hash(program)})
            return {"result": result, "check": check, "next_state": result.get("next_state"), "state": state, "bindings": bindings}
        raise ValueError(f"run {run!r} does not take a combat block")
    if run == "standard_move":
        timing = mirror(_timing(fixture.get("timing", "open")))
        state = scenario()
        declaration = bind(copy.deepcopy(fixture.get("declaration") or probe.get("declaration")), bindings)
        result = standard_move(timing, state, declaration)
        check = build_engine_check("standard_move", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "move_declaration": canonical_hash(declaration)})
        return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing, "bindings": bindings}
    if run in COMBAT_RUNS:
        raise ValueError(f"run {run!r} needs a combat block")

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
    if run == "play_entry":
        # ADR-0007 §1–2: the permanent is played with its entry_location, then
        # resolves by the entry procedure; its play triggers show up as the
        # Pending items that resolution schedules. No program is attached to
        # the permanent itself.
        timing = mirror(_timing(fixture.get("timing", "open")))
        state = scenario()
        decisions = _decisions(fixture, state, bindings)
        declaration = _declaration(clause, fixture, None, bindings)
        played = play_card(timing, state, declaration, engine_decisions=decisions)
        if not played.get("committed"):
            check = build_engine_check("play", played, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "play_declaration": canonical_hash(declaration)})
            return {"result": played, "check": check, "next_state": played.get("next_effect_state"), "state": state, "timing": timing}
        on_chain = played["next_effect_state"]
        res_timing = _resolution_timing(bindings["chain_item"], declaration["chain_item"]["object_kind"], declaration["actor"])
        result = resolve_with_program(res_timing, bindings["chain_item"], on_chain, None)
        check = build_engine_check("resolution", result, input_hashes={"timing_state": state_hash(res_timing), "effect_state": hash_value(on_chain)})
        return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": res_timing, "play_result": played}
    if run == "play" or fixture.get("timing") not in (None, "resolution"):
        timing = mirror(_timing(fixture["timing"]))
        state = scenario()
        decisions = _decisions(fixture, state, bindings)
        program = _program(template, bindings) if template else None
        declaration = _declaration(clause, fixture, program_id, bindings)
        result = play_card(timing, state, declaration, engine_decisions=decisions, effect_program=program)
        check = build_engine_check("play", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "play_declaration": canonical_hash(declaration)})
        if result.get("committed") and not mirrored:
            receipts[fixture["fixture_id"]] = {"receipt": result["cost_receipt"], "state": result["next_effect_state"]}
        return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing}
    if run == "resolution":
        # the item about to resolve belongs to the bound controller, on their turn
        timing = _resolution_timing(bindings["chain_item"], "spell", bindings["controller"]) if fixture["timing"] == "resolution" else mirror(_timing(fixture["timing"]))
        state = scenario()
        program = _program(template, bindings)
        _compile_targets(program, fixture, state)
        decisions = _decisions(fixture, state, bindings)
        result = resolve_with_program(timing, bindings["chain_item"], state, program, engine_decisions=decisions)
        check = build_engine_check("resolution", result, input_hashes={"timing_state": state_hash(timing), "effect_state": hash_value(state), "effect_program": canonical_hash(program)})
        return {"result": result, "check": check, "next_state": result.get("next_effect_state"), "state": state, "timing": timing}
    state = scenario()
    program = _program({**template, **fixture.get("program_override", {})}, bindings)
    _compile_targets(program, fixture, state)
    decisions = _decisions(fixture, state, bindings)
    result = apply_program(state, program, decisions=decisions)
    check = build_engine_check("effect", result, input_hashes={"effect_state": hash_value(state), "effect_program": canonical_hash(program)})
    return {"result": result, "check": check, "next_state": result.get("next_state"), "state": state}


def _nested_reason_code(value: Any) -> str | None:
    """The first reason_code in the result, breadth-first (top level first)."""
    queue = [value]
    while queue:
        item = queue.pop(0)
        if isinstance(item, dict):
            if isinstance(item.get("reason_code"), str):
                return item["reason_code"]
            queue.extend(item.values())
        elif isinstance(item, list):
            queue.extend(item)
    return None


def _compare(fixture: dict[str, Any], run: dict[str, Any]) -> list[str]:
    expected = bind(copy.deepcopy(fixture["expected"]), run.get("bindings") or fixture["bindings"]) if "$" in json.dumps(fixture["expected"]) else fixture["expected"]
    result, check, next_state = run["result"], run["check"], run["next_state"]
    problems: list[str] = []
    for item in expected.get("assert", []):
        if "trace_path" in item:
            value = result.get("trace")
            for key in item["trace_path"]:
                if isinstance(value, list) and isinstance(key, int):
                    value = value[key] if key < len(value) else None
                else:
                    value = (value or {}).get(key) if isinstance(value, dict) else None
            if value != item["equals"]:
                problems.append(f"trace.{'.'.join(str(k) for k in item['trace_path'])} = {value!r}, expected {item['equals']!r}")
        elif "combat_status" in item:
            status = (result.get("next_timing_state") or {}).get("combat", {}).get("status") if isinstance(result.get("next_timing_state"), dict) else None
            if status != item["combat_status"]:
                problems.append(f"combat status {status!r}, expected {item['combat_status']!r}")
    if check["outcome"] != expected["outcome"]:
        problems.append(f"outcome {check['outcome']!r}, expected {expected['outcome']!r} ({check['reason']['message'][:160]})")
    got_code = _nested_reason_code(result)  # a refusal nested in a resolution's effect result carries the code
    if "reason_code" in expected and got_code != expected["reason_code"]:
        problems.append(f"reason_code {got_code!r}, expected {expected['reason_code']!r}")
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
        elif "trace_path" in item or "combat_status" in item:
            pass  # handled above
        elif "receipt_absent" in item:
            if any(c["cost_id"] == item["receipt_absent"] for c in result.get("cost_receipt", {}).get("components", [])):
                problems.append(f"receipt component {item['receipt_absent']} is present")
        elif "field" in item:
            value = next_state
            for key in item["field"]:
                if isinstance(value, list) and isinstance(key, int):
                    value = value[key] if key < len(value) else None
                else:
                    value = (value or {}).get(key) if isinstance(value, dict) else None
            if value != item["equals"]:
                problems.append(f"{'.'.join(str(k) for k in item['field'])} = {value!r}, expected {item['equals']!r}")
        elif "entry" in item:
            entry = (result.get("trace") or {}).get("chain_card", [{}])[0] if isinstance(result.get("trace"), dict) else {}
            if entry.get(item["entry"]) != item["equals"]:
                problems.append(f"entry.{item['entry']} = {entry.get(item['entry'])!r}, expected {item['equals']!r}")
        elif "effective_might" in item:
            got = effective_might(next_state, item["effective_might"]) if next_state and item["effective_might"] in next_state.get("objects", {}) else None
            if got != item["equals"]:
                problems.append(f"effective might of {item['effective_might']} is {got}, expected {item['equals']}")
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
            stripped = [strip(x) for x in v]
            if stripped and all(isinstance(x, str) and re.fullmatch(r"p[12]", x) for x in stripped):
                return sorted(stripped)  # a list of player ids is a set here: its alphabetical order is not player-relative
            return stripped
        if isinstance(v, str) and v.startswith("sha256:"):
            return "<hash>"
        if isinstance(v, str):
            return re.sub(r"[0-9a-f]{12}", "<hash>", v)  # batch ids embed a state-hash prefix
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
    if clause.get("execution"):
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
    templates = {k: v for k, v in execution.items() if k in {"program", "declaration", "play_declaration", "passive"}}
    probes = [fx.get("probe") for fx in clause.get("fixtures", []) if fx.get("probe")]
    per_fixture = [{k: v for k, v in fx.items() if k in {"declaration", "combat", "decisions"}} for fx in clause.get("fixtures", [])]
    return not literal_players(templates) and not literal_players(probes) and not literal_players(per_fixture)


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
            if status not in {"full", "partial"}:
                program_id = None
            elif "program" in execution:
                program_id = execution["program"]["program_id"]
            elif execution.get("intrinsic"):
                program_id = f"intrinsic:{execution['intrinsic']}:{clause['clause_id']}"  # a vanilla Unit's inherent Combat behaviour, probed — never invented text
            elif execution.get("passive"):
                program_id = f"passive:{clause['clause_id']}"
            else:
                program_id = f"play:{clause['clause_id']}"
            ops = sorted({e["op"] for e in execution.get("program", {}).get("effects", [])}) if status in {"full", "partial"} else []
            if status in {"full", "partial"} and execution.get("kind") == "play" and not execution.get("passive"):
                declaration = execution.get("declaration", {})
                ops = sorted({add["payment"]["kind"] for add in declaration.get("cost", {}).get("additional", []) if add["payment"]["kind"] in {"exhaust", "kill"}})
            unsupported = list(clause.get("unsupported_mechanics", [])) if status in {"partial", "unsupported"} else (base["unsupported_mechanics"] if status in {"unsupported", "stale"} else [])
            if status == "unsupported" and not unsupported:
                unsupported = list(base["unsupported_mechanics"]) or ["fixtures_not_passing"]
            clause_rows.append({
                "clause_id": clause["clause_id"], "source_id": base["source_id"], "locator": base["locator"], "text_hash": base["text_hash"],
                "status": status, "program_id": program_id, "implemented_ops": ops, "unsupported_mechanics": unsupported,
                "test_ids": [r["fixture_id"] for r in rows if not r.get("skipped") and r["passed"]] if status in {"full", "partial"} else [],
                "notes": f"{'C-32' if execution.get('intrinsic') or any(fx.get('combat') or fx.get('run') in COMBAT_RUNS for fx in clause.get('fixtures', [])) else 'C-25' if execution.get('passive') or any(fx.get('probe') or fx.get('run') for fx in clause.get('fixtures', [])) else 'C-18'} derived: {reason}."
                         f"{' passive state, probed by fixtures.' if execution.get('passive') else ''} text: {clause['text']} | rules: {', '.join(clause.get('rule_locators', []))}",
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
    lines = ["# R3-A1 / R3-A2 / R3-A3 card programs — fixture run and derived statuses", "",
             "Generated by `r3a1_programs.py`. Templates carry symbolic references and are bound per fixture; every executed fixture also runs mirrored (players swapped) and must agree. Passives (the state a card contributes) are applied to the scenario and probed; `play_entry` fixtures play a permanent and resolve its entry. Statuses are derived from fixtures passing against the engine, never copied from a claim. The manifest stays `draft`; nothing here activates a pack.", ""]
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
