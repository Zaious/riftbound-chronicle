#!/usr/bin/env python3
"""
Regression gate for C-40 (ADR-0011 §1–2, §6; Codex G-1 on DP-60 / DP-61):
the typed choice specification, `mode_selection` and `card_ordering`
decision kinds, modal programs, and private-option redaction.

Must hold:
  - the specification validator refuses a bad selection kind / count / source /
    chooser / visibility, a public hand, an ordered permutation counted
    'exactly', and accepts the discard, trash and put-back shapes;
  - a private choice (discard from a two-card hand) stops as
    card_selection_required naming the decision and the player, carries the
    options count and hash, and never the hand's ids — in the effect result,
    and in an engine-check built with include_raw (negative mutation: the
    same result over a *public* source lists its options, so the redaction is
    keyed on visibility, not absent);
  - a public choice (recycle_one from the trash) lists options with
    identities; a decision outside the candidates is illegal_operation, by
    another player decision_controller_mismatch, the wrong count or a stale
    identity invalid_input; a single candidate is forced without a decision;
  - a modal program refuses to carry top-level effects, needs two options
    with unique stable ids, stops as mode_selection_required (engine-check
    kind mode_choice) without a decision, refuses an integer index, an
    unknown option, another stage or another controller, and runs only the
    chosen option's instructions, reporting `mode`;
  - the play transaction requires the mode of a modal spell at play
    (mode_selection_required at stage choices), checks only the chosen
    option's targets, records the mode on the chain entry, and the bridge
    resolves the recorded mode without re-supplying it; an envelope that
    contradicts the recorded mode is invalid_input;
  - card_ordering decisions need identities, a unique array and the
    resolution stage; mode_selection values are strings at play / trigger
    stages; both schemas list the new kinds; engine-check kinds include
    mode_choice and card_ordering;
  - determinism and input purity.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import engine_decisions as ed  # noqa: E402
from check_effect_ir import base_state, program  # noqa: E402
from check_play_transaction import CLOSED, declaration, effect_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import apply_program, hash_value, object_identity, validate_program  # noqa: E402
from engine_check import DECISION_REASON_CODES, build_engine_check  # noqa: E402
from play_transaction import play_card  # noqa: E402
from resolution_bridge import resolve_with_program  # noqa: E402


def envelope(state, *decisions):
    return {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(state), "decisions": list(decisions)}


def card_decision(kind, decision_id, value, state, controller="p1", stage="resolution", identities=None):
    return {"decision_id": decision_id, "stage": stage, "kind": kind, "controller": controller, "value": value,
            "selection_identities": identities if identities is not None else {i: object_identity(state, i) or f"{i}@0" for i in value}}


def main() -> int:
    errors: list[str] = []

    # --- specification validator -------------------------------------------------------
    good = [
        {"selection_kind": "unordered_set", "count": {"exactly": 1}, "from": "hand", "by": "p1", "visibility": "private_to_chooser"},
        {"selection_kind": "single", "from": "trash"},
        {"selection_kind": "ordered_permutation", "count": {"any_number": True}, "from": "revealed"},
        {"selection_kind": "single", "from": "players", "players": "opponents"},
        {"selection_kind": "unordered_set", "count": {"up_to": 2}, "from": "board", "criteria": {"kind": "unit", "controller_relation": "friendly"}},
    ]
    for spec in good:
        if ed.validate_choice_spec(spec):
            errors.append(f"a valid specification was refused: {spec} {ed.validate_choice_spec(spec)}")
    bad = [
        ({"selection_kind": "some", "from": "hand"}, "selection_kind"),
        ({"selection_kind": "unordered_set", "count": {"exactly": 0}, "from": "hand"}, "count"),
        ({"selection_kind": "unordered_set", "count": {"exactly": 1}, "from": "pocket"}, "from"),
        ({"selection_kind": "unordered_set", "count": {"exactly": 1}, "from": "hand", "visibility": "public"}, "private information"),
        ({"selection_kind": "ordered_permutation", "count": {"exactly": 2}, "from": "revealed"}, "orders every candidate"),
        ({"selection_kind": "single", "from": "board"}, "criteria"),
        ({"selection_kind": "single", "from": "main_deck_top"}, "top"),
        ({"selection_kind": "unordered_set", "count": {"exactly": 1}, "from": "hand", "by": ""}, "by"),
    ]
    for spec, needle in bad:
        problems = ed.validate_choice_spec(spec)
        if not problems or not any(needle in p for p in problems):
            errors.append(f"specification {spec} should be refused mentioning {needle!r}: {problems}")

    # --- private choice: the hand is never listed ------------------------------------------
    hand2 = base_state()
    hand2["players"]["p1"]["zones"]["hand"] = ["c1", "c2"]
    hand2["players"]["p1"]["zones"]["main_deck"] = []
    ask = apply_program(hand2, program("d", {"op": "discard", "player": "p1", "count": 1, "decision_ref": "pick", "effect_id": "d"}))
    if ask.get("committed") or ask.get("reason_code") != "card_selection_required" or ask.get("decision_ids") != ["pick"] or ask.get("decision_controller") != "p1" or ask.get("choice_required") is not True:
        errors.append(f"a private choice did not stop as card_selection_required: {ask.get('reason_code')} {ask.get('errors')}")
    summary = ask.get("choice") or {}
    if summary.get("visibility") != "private_to_chooser" or summary.get("options_count") != 2 or not str(summary.get("options_hash", "")).startswith("sha256:") or "options" in summary or summary.get("options_visible_to") != ["p1"]:
        errors.append(f"private choice summary is wrong: {summary}")
    dumped = json.dumps({k: v for k, v in ask.items() if k != "trace"})
    if '"c1"' in dumped or '"c2"' in dumped:
        errors.append("the private decision_required result listed the hand")
    raw_check = build_engine_check("effect", ask, input_hashes={"effect_state": hash_value(hand2), "effect_program": "sha256:" + "4" * 64}, include_raw=True)
    if '"c1"' in json.dumps(raw_check) or '"c2"' in json.dumps(raw_check):
        errors.append("an engine-check with raw_result leaked the hand")
    if raw_check["outcome"] != "decision_required" or raw_check["decision_required"]["kind"] != "card_choice":
        errors.append(f"private choice wrapped as {raw_check['outcome']} {raw_check.get('decision_required')}")

    # --- public choice: options are listed with identities -----------------------------------
    trash2 = base_state()
    trash2["players"]["p1"]["zones"]["trash"] = ["c3", "c2"]
    trash2["players"]["p1"]["zones"]["main_deck"] = ["c1"]
    recycle_spec = {"selection_kind": "single", "from": "trash", "by": "controller"}
    rec = program("rec", {"op": "recycle_one", "effect_id": "r", "choice": recycle_spec, "decision_ref": "which"})
    if validate_program(rec):
        errors.append(f"recycle_one with a choice was refused: {validate_program(rec)}")
    ask_pub = apply_program(trash2, rec)
    pub = ask_pub.get("choice") or {}
    if ask_pub.get("reason_code") != "card_selection_required" or pub.get("visibility") != "public" or pub.get("options") != [{"object_id": "c3", "identity": "c3@0"}, {"object_id": "c2", "identity": "c2@0"}]:
        errors.append(f"a public choice did not list its options: {ask_pub.get('reason_code')} {pub}")
    pub_check = build_engine_check("effect", ask_pub, input_hashes={"effect_state": hash_value(trash2), "effect_program": "sha256:" + "4" * 64}, include_raw=True)
    if '"c3"' not in json.dumps(pub_check):
        errors.append("negative mutation failed: a public choice's options did not reach the raw engine-check, so the private redaction is not keyed on visibility")
    chosen = apply_program(trash2, rec, decisions=envelope(trash2, card_decision("card_selection", "which", ["c2"], trash2)))
    if not chosen.get("committed") or chosen["next_state"]["players"]["p1"]["zones"]["main_deck"][-1] != "c2" or chosen["trace"][0].get("selection", {}).get("decision_id") != "which":
        errors.append(f"a public choice was not consumed: {chosen.get('reason') or chosen.get('errors')}")
    outside = apply_program(trash2, rec, decisions=envelope(trash2, card_decision("card_selection", "which", ["c1"], trash2)))
    if outside.get("reason_code") != "illegal_operation":
        errors.append(f"a choice outside the candidates was not illegal: {outside.get('reason_code')} {outside.get('errors')}")
    other = apply_program(trash2, rec, decisions=envelope(trash2, card_decision("card_selection", "which", ["c2"], trash2, controller="p2")))
    if other.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"another player's choice was not refused: {other.get('reason_code')}")
    two = apply_program(trash2, rec, decisions=envelope(trash2, card_decision("card_selection", "which", ["c2", "c3"], trash2)))
    if two.get("valid") is not False or not any("exactly one" in e for e in two.get("errors", [])):
        errors.append(f"a two-card value for a single choice was not invalid_input: {two.get('errors')}")
    stale = apply_program(trash2, rec, decisions=envelope(trash2, card_decision("card_selection", "which", ["c2"], trash2, identities={"c2": "c2@7"})))
    if stale.get("valid") is not False:
        errors.append("a stale identity was accepted")
    one = copy.deepcopy(trash2); one["players"]["p1"]["zones"]["trash"] = ["c3"]; one["players"]["p1"]["zones"]["main_deck"] = ["c1", "c2"]
    forced = apply_program(one, rec)
    if not forced.get("committed") or forced["trace"][0].get("selection", {}).get("forced") is not True:
        errors.append(f"a single candidate was not forced: {forced.get('reason_code')} {forced.get('errors')}")
    empty = copy.deepcopy(trash2); empty["players"]["p1"]["zones"]["trash"] = []; empty["players"]["p1"]["zones"]["main_deck"] = ["c1", "c2", "c3"]
    nothing = apply_program(empty, rec)
    if not nothing.get("committed") or nothing["trace"][0].get("outcome") != "no_op":
        errors.append(f"an empty source did not no_op: {nothing.get('reason_code')} {nothing.get('errors')} {nothing.get('trace')}")

    # --- modal programs -------------------------------------------------------------------------
    state = base_state()
    modal = {
        "schema_version": rec["schema_version"], "ruleset": rec["ruleset"], "program_id": "blind-fury", "controller": "p1", "effects": [],
        "modal": {"choose": 1, "timing": "play_declaration", "decision_ref": "mode:blind-fury", "options": [
            {"option_id": "damage", "effects": [{"op": "deal_damage", "effect_id": "dmg", "object_id": "u2", "amount": 2, "target": {"object_id": "u2", "chosen_zone_class": "board"}}]},
            {"option_id": "draw", "effects": [{"op": "draw", "effect_id": "dr", "player": "p1", "count": 1}]},
        ]},
    }
    if validate_program(modal):
        errors.append(f"a modal program was refused: {validate_program(modal)}")
    with_effects = copy.deepcopy(modal); with_effects["effects"] = [{"op": "draw", "player": "p1", "count": 1}]
    if not validate_program(with_effects):
        errors.append("a modal program with top-level effects was accepted")
    dup = copy.deepcopy(modal); dup["modal"]["options"][1]["option_id"] = "damage"
    if not any("duplicated" in e for e in validate_program(dup)):
        errors.append("duplicate option ids were accepted")
    lone = copy.deepcopy(modal); lone["modal"]["options"] = lone["modal"]["options"][:1]
    if not validate_program(lone):
        errors.append("a one-option modal was accepted")
    no_mode = apply_program(state, modal)
    if no_mode.get("reason_code") != "mode_selection_required" or no_mode.get("decision_ids") != ["mode:blind-fury"] or no_mode.get("decision_controller") != "p1" or no_mode.get("mode_options") != ["damage", "draw"]:
        errors.append(f"a modal program without a mode did not stop: {no_mode.get('reason_code')} {no_mode.get('errors')}")
    else:
        check = build_engine_check("effect", no_mode, input_hashes={"effect_state": hash_value(state), "effect_program": "sha256:" + "4" * 64})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "mode_choice" or check["decision_required"]["decision_ids"] != ["mode:blind-fury"]:
            errors.append(f"mode_selection_required wrapped as {check['outcome']} {check.get('decision_required')}")

    def mode(value, controller="p1", stage="play_declaration"):
        return envelope(state, {"decision_id": "mode:blind-fury", "stage": stage, "kind": "mode_selection", "controller": controller, "value": value})

    chosen_mode = apply_program(state, modal, decisions=mode("draw"))
    if not chosen_mode.get("committed") or [e["op"] for e in chosen_mode["trace"]] != ["draw"] or chosen_mode.get("mode", {}).get("option_id") != "draw" or chosen_mode["next_state"]["objects"]["u2"]["damage"] != 0:
        errors.append(f"the chosen mode did not run only its option: {chosen_mode.get('reason') or chosen_mode.get('errors')} {[e.get('op') for e in chosen_mode.get('trace', [])]}")
    by_index = apply_program(state, modal, decisions=mode(1))
    if by_index.get("valid") is not False or not any("stable option id" in e for e in by_index.get("errors", [])):
        errors.append(f"an index-valued mode was accepted: {by_index.get('errors')}")
    unknown = apply_program(state, modal, decisions=mode("heal"))
    if unknown.get("valid") is not False or not any("does not have" in e for e in unknown.get("errors", [])):
        errors.append(f"an unknown option was accepted: {unknown.get('errors')}")
    wrong_stage = apply_program(state, modal, decisions=mode("draw", stage="trigger_finalization"))
    if wrong_stage.get("valid") is not False:
        errors.append("a mode chosen at another stage was accepted")
    wrong_player = apply_program(state, modal, decisions=mode("draw", controller="p2"))
    if wrong_player.get("reason_code") != "decision_controller_mismatch":
        errors.append(f"another player's mode was accepted: {wrong_player.get('reason_code')}")

    # --- the play transaction: mode at play, recorded on the chain, resolved by the bridge -----
    timing = fixture()
    effects = effect_state(energy=3, hand=("c1",))
    effects["players"]["p1"]["zones"]["main_deck"] = ["c2"]
    effects["objects"]["c2"] = {"owner": "p1", "controller": "p1", "kind": "spell", "base_might": 0, "might_modifiers": [], "damage": 0, "exhausted": False}
    effects["objects"]["u1"]["might_modifiers"] = [{"amount": 10, "duration": "this_turn", "source": "x"}]  # 13 Might: illegal for a max_might 3 target
    play_modal = copy.deepcopy(modal)
    play_modal["modal"]["options"][0]["effects"] = [{"op": "deal_damage", "effect_id": "dmg", "object_id": "u1", "amount": 2, "target": {"object_id": "u1", "chosen_zone_class": "board", "max_might": 3}}]
    decl = declaration(cost={"base": {"energy": 1, "power": {}}}, effect_program_id="blind-fury")
    missing = play_card(timing, effects, decl, effect_program=play_modal)
    if missing.get("reason_code") != "mode_selection_required" or missing.get("stage") != "choices" or missing.get("decision_ids") != ["mode:blind-fury"] or missing.get("mode_options") != ["damage", "draw"]:
        errors.append(f"a modal spell played without a mode did not stop at choices: {missing.get('reason_code')} {missing.get('reason')}")
    else:
        check = build_engine_check("play", missing, input_hashes={"timing_state": "sha256:" + "1" * 64, "effect_state": hash_value(effects), "play_declaration": "sha256:" + "2" * 64})
        if check["outcome"] != "decision_required" or check["decision_required"]["kind"] != "mode_choice":
            errors.append(f"play-time mode wrapped as {check['outcome']}")
    play_env = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(effects), "decisions": [{"decision_id": "mode:blind-fury", "stage": "play_declaration", "kind": "mode_selection", "controller": "p1", "value": "draw"}]}
    played = play_card(timing, effects, decl, engine_decisions=play_env, effect_program=play_modal)
    if not played.get("committed") or played["next_effect_state"]["chain_items"]["spell-1"].get("mode_selection") != {"decision_id": "mode:blind-fury", "option_id": "draw"}:
        errors.append(f"a modal spell with its mode did not commit with the mode recorded: {played.get('reason_code')} {played.get('reason')}")
    else:
        # the unchosen option's illegal target was not checked
        damage_env = copy.deepcopy(play_env); damage_env["decisions"][0]["value"] = "damage"
        illegal = play_card(timing, effects, decl, engine_decisions=damage_env, effect_program=play_modal)
        if illegal.get("reason_code") != "target_illegal_at_play":
            errors.append(f"negative mutation failed: choosing the damage option should hit the 355.9 check: {illegal.get('reason_code')}")
        # resolution reads the recorded mode; no envelope needed
        next_effects = played["next_effect_state"]
        from rules_core import finalize_oldest_pending
        fin = finalize_oldest_pending(played["next_timing_state"])["next_state"]
        fin["chain"]["consecutive_passes"] = ["p1", "p2"]  # every player passed: the item is next to resolve
        resolved = resolve_with_program(fin, "spell-1", next_effects, play_modal)
        if not resolved.get("committed") or [e["op"] for e in resolved["trace"]["effect"]] != ["draw"] or "c2" not in resolved["next_effect_state"]["players"]["p1"]["zones"]["hand"]:
            errors.append(f"the bridge did not resolve the recorded mode: {resolved.get('reason')} {resolved.get('stage')} {resolved.get('effect_result', {}).get('errors')}")
        contradict = {"schema_version": ed.DECISIONS_VERSION, "input_hash": hash_value(next_effects), "decisions": [{"decision_id": "mode:blind-fury", "stage": "play_declaration", "kind": "mode_selection", "controller": "p1", "value": "damage"}]}
        clash = resolve_with_program(fin, "spell-1", next_effects, play_modal, engine_decisions=contradict)
        if clash.get("committed") or clash.get("effect_result", {}).get("valid") is not False:
            errors.append(f"an envelope contradicting the recorded mode was accepted: {clash.get('stage')} {clash.get('reason')}")

    # --- decision kinds and schemas ----------------------------------------------------------------
    ordering = envelope(state, card_decision("card_ordering", "order", ["c1", "c2"], state))
    if ed.validate_engine_decisions(ordering):
        errors.append(f"a valid card_ordering was refused: {ed.validate_engine_decisions(ordering)}")
    no_ids = copy.deepcopy(ordering); del no_ids["decisions"][0]["selection_identities"]
    dup_ids = envelope(state, card_decision("card_ordering", "order", ["c1", "c1"], state))
    for label, env in (("without identities", no_ids), ("with a repeated card", dup_ids)):
        if not ed.validate_engine_decisions(env):
            errors.append(f"a card_ordering {label} was accepted")
    # Codex G-1 §11.7: an empty ordering is the answer when nothing is left to
    # put back; completeness is judged against the candidates, not at the envelope.
    empty_order = envelope(state, {"decision_id": "order", "stage": "resolution", "kind": "card_ordering", "controller": "p1", "value": [], "selection_identities": {}})
    if ed.validate_engine_decisions(empty_order):
        errors.append(f"an empty card_ordering was refused by the envelope: {ed.validate_engine_decisions(empty_order)}")
    permutation = {"selection_kind": "ordered_permutation", "count": {"any_number": True}, "from": "revealed", "by": "p1"}
    entry = empty_order["decisions"][0]
    if ed.check_choice_entry(permutation, entry, "p1", [], {})[1] is not None:
        errors.append("an empty ordering was refused although nothing was left to order")
    if ed.check_choice_entry(permutation, entry, "p1", ["c1", "c2"], {"c1": "c1@0", "c2": "c2@0"})[1] != "invalid":
        errors.append("negative mutation failed: the same empty ordering passed against two candidates, so completeness is not checked")
    # A card choice may carry the play_declaration stage only while a cost is
    # being paid (Core 357.2); a resolution-time instruction refuses it.
    at_play = apply_program(trash2, rec, decisions=envelope(trash2, card_decision("card_selection", "which", ["c2"], trash2, stage="play_declaration")))
    if at_play.get("valid") is not False or not any("resolution-stage" in e for e in at_play.get("errors", [])):
        errors.append(f"a resolution instruction accepted a play-stage card choice: {at_play.get('reason_code')} {at_play.get('errors')}")
    int_mode = envelope(state, {"decision_id": "m", "stage": "play_declaration", "kind": "mode_selection", "controller": "p1", "value": 0})
    res_mode = envelope(state, {"decision_id": "m", "stage": "resolution", "kind": "mode_selection", "controller": "p1", "value": "a"})
    for label, env in (("with an integer value", int_mode), ("at resolution stage", res_mode)):
        if not ed.validate_engine_decisions(env):
            errors.append(f"a mode_selection {label} was accepted")
    schema = json.loads((SKILL_DIR / "schemas" / "engine-decisions.schema.json").read_text(encoding="utf-8"))
    kinds = schema["properties"]["decisions"]["items"]["properties"]["kind"]["enum"]
    if set(kinds) != set(ed.KINDS) or "card_ordering" not in schema["properties"]["decisions"]["items"]["allOf"][0]["if"]["properties"]["kind"]["enum"]:
        errors.append("engine-decisions schema does not list the module's kinds (mode_selection, card_ordering with identities)")
    ec = json.loads((SKILL_DIR / "schemas" / "engine-check.schema.json").read_text(encoding="utf-8"))
    ec_kinds = set(ec["properties"]["decision_required"]["properties"]["kind"]["enum"])
    if not {"mode_choice", "card_ordering"} <= ec_kinds or set(DECISION_REASON_CODES.values()) - ec_kinds:
        errors.append("engine-check schema does not list every decision kind the reason-code table maps to")
    ep = json.loads((SKILL_DIR / "schemas" / "effect-program.schema.json").read_text(encoding="utf-8"))
    if "modal" not in ep["properties"] or "choice" not in ep["$defs"] or "choice" not in ep["properties"]["effects"]["items"]["properties"]:
        errors.append("effect-program schema lacks modal / choice")

    # --- determinism and purity -----------------------------------------------------------------------
    snapshot = copy.deepcopy(trash2)
    if apply_program(trash2, rec) != ask_pub or trash2 != snapshot:
        errors.append("choice resolution is not deterministic or mutated its input")

    if errors:
        print("FAILED: choice grammar checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("choice grammar checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
