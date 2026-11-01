#!/usr/bin/env python3
"""
Regression gate (2026-11-01, set 2 A1, GPT's first review): three instruction shapes the review asked for.

  P  a public choice among revealed cards (Void Rush, Rek'Sai: "Reveal the top 2 cards ... You may banish one") -
     the revealed cards are known to every player (Core 425.1), so the choice is public:
       P1  the pending choice lists its options (no count-and-hash summary, no options_visible_to)
       P2  the choice made is listed in the trace (chosen_objects), and the banish follows it
       P3  the other player's view of the state shows the revealed cards (action_receipt.actor_view), and a card only
           looked at stays masked for them
       P4  a public choice over a card shown to fewer than all players (a look's) is refused, never shown
       P5  the private form is unchanged: a count and a hash, visible to the chooser
  L  "ready your legend" (Hall of Legends; Core 355.10.g) - not a target; with more than one legend, one is chosen as
     the ability resolves:
       L1  two legends of p1's: the choice is asked as it resolves, among p1's two only (not p2's), and the one chosen
           is readied
       L2  one legend: nothing is asked, it is readied
       L3  a decision made at another stage than resolution is refused
       L4  the opponent's legend cannot be chosen
       L5  read as it resolves: the same program, run on a state that changed after it was put on the Chain (p1's
           legend gone, another there), readies the legend p1 controls then - nothing was bound earlier
       L6  no legend: nothing happens
  D  "Return all units and gear to their owners' hands." (Downwell) - one instruction over both kinds:
       D1  every unit and gear on the board, of either player, in a base or at a battlefield, goes to its owner's
           hand in one instruction with one set found once (one criteria snapshot); legends and runes stay
       D2  kinds is refused beside kind, with one kind, with a rune, and off the whole board

    python skill/scripts/check_set2_a1_review.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import action_receipt as AR  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from effect_ir import PROGRAM_VERSION, apply_program, hash_value, object_identity, validate_program  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def program(effects, pid="p"):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": pid, "controller": "p1", "effects": effects}


def decisions(state, *entries):
    return {"schema_version": "engine-decisions.v1", "input_hash": hash_value(state), "decisions": list(entries)}


# --- P: a public choice among revealed cards ---------------------------------------------------------------------------

def deck_state():
    state = base_state()
    for card, kind in (("top1", "unit"), ("top2", "spell")):
        state["objects"][card] = {"owner": "p1", "controller": "p1", "kind": kind, "base_might": 2, "might_modifiers": [],
                                  "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["main_deck"][:0] = ["top1", "top2"]
    return state


def pick(visibility):
    return {"op": "choose_objects", "effect_id": "pick", "decision_ref": "pick", "group": "kept",
            "choice": {"selection_kind": "unordered_set", "from": "revealed", "by": "controller", "count": {"up_to": 1},
                       "visibility": visibility}}


REVEAL = {"op": "reveal", "effect_id": "rv", "from": "main_deck_top", "count": 2, "player": "p1"}
LOOK = {"op": "look_at_top", "effect_id": "lk", "player": "p1", "count": 2}
BANISH = {"op": "banish", "effect_id": "ban", "player": "p1", "group_ref": "kept"}


def check_public_revealed() -> None:
    state = deck_state()
    asked = apply_program(state, program([REVEAL, pick("public"), BANISH]))
    choice = asked.get("choice") or {}
    if asked.get("reason_code") != "card_selection_required" or choice.get("visibility") != "public" \
            or sorted(o.get("object_id") for o in choice.get("options") or []) != ["top1", "top2"] \
            or "options_visible_to" in choice:
        fail("P1", f"the pending public choice: {asked.get('reason_code')} {choice}")
    done = apply_program(state, program([REVEAL, pick("public"), BANISH]), decisions=decisions(state, {
        "decision_id": "pick", "stage": "resolution", "kind": "card_selection", "controller": "p1", "value": ["top1"],
        "selection_identities": {"top1": object_identity(state, "top1")}}))
    chose = next((t for t in done.get("trace") or [] if t.get("op") == "choose_objects"), {})
    if not done.get("committed") or chose.get("chosen_objects") != ["top1"] or "objects_visible_to" in chose \
            or "Core 425.1" not in chose.get("rule_locators", []):
        fail("P2", f"the choice made: {done.get('reason') or done.get('errors')} {chose}")
    elif "top1" not in done["next_state"]["players"]["p1"]["zones"]["banishment"] and not any(
            o in done["next_state"]["players"]["p1"]["zones"]["banishment"]
            for o in (next((t for t in done["trace"] if t.get("op") == "banish"), {}).get("objects") or [])):
        fail("P2", f"the card chosen was not banished: {done['next_state']['players']['p1']['zones']}")

    # P3: the other player's view - a revealed card is shown, a looked-at one is not
    view_state = deck_state()
    IR._mark_reveals(view_state, "p1", "main_deck", ["top1"], "all", "rv", "reveal")
    IR._mark_reveals(view_state, "p1", "main_deck", ["top2"], ["p1"], "lk", "look")
    view = AR.actor_view(view_state, "p2")
    shown = [o for o in view["objects"] if o == "top1"]
    if not shown or view["objects"]["top1"].get("masked") or view["objects"]["top1"].get("kind") != "unit":
        fail("P3", f"p2 does not see the revealed card: {view['objects'].get('top1')}")
    if "top2" in view["objects"] and not view["objects"]["top2"].get("masked"):
        fail("P3", f"p2 sees a card only p1 looked at: {view['objects']['top2']}")

    looked = apply_program(state, program([LOOK, pick("public"), BANISH]))
    if looked.get("valid") is not False or "not revealed to all" not in " ".join(looked.get("errors") or []):
        fail("P4", f"a public choice over a look was not refused: {looked.get('reason') or looked.get('errors')}")

    private = apply_program(state, program([REVEAL, pick("private_to_chooser"), BANISH]))
    summary = private.get("choice") or {}
    if summary.get("visibility") != "private_to_chooser" or "options" in summary or summary.get("options_visible_to") != ["p1"]:
        fail("P5", f"the private form changed: {summary}")


# --- L: "ready your legend" -------------------------------------------------------------------------------------------

def legend_state(*legends):
    state = base_state()
    for oid, owner in legends:
        state["objects"][oid] = {"owner": owner, "controller": owner, "kind": "legend", "base_might": 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": True}
        state["players"][owner]["zones"].setdefault("legend_zone", []).append(oid)
    return state


YOUR_LEGEND = [{"op": "choose_objects", "effect_id": "lg", "decision_ref": "lg", "group": "legend",
                "choice": {"selection_kind": "single", "from": "legend_zone", "by": "controller"}},
               {"op": "ready", "effect_id": "rd", "group_ref": "legend"}]


def legend_pick(state, oid, stage="resolution"):
    return decisions(state, {"decision_id": "lg", "stage": stage, "kind": "target_selection", "controller": "p1",
                             "value": [oid], "selection_identities": {oid: object_identity(state, oid)}})


def check_your_legend() -> None:
    problems = validate_program(program(YOUR_LEGEND))
    if problems:
        fail("L shape", problems)
        return
    if any(e.get("target") or e.get("targets") for e in YOUR_LEGEND):
        fail("L shape", "the program names a target")
    two = legend_state(("L1", "p1"), ("L2", "p1"), ("L3", "p2"))
    asked = apply_program(two, program(YOUR_LEGEND))
    options = sorted(o.get("object_id") for o in (asked.get("choice") or {}).get("options") or [])
    if not asked.get("choice_required") or options != ["L1", "L2"]:
        fail("L1", f"two legends of p1's: {asked.get('reason')} {options}")
    done = apply_program(two, program(YOUR_LEGEND), decisions=legend_pick(two, "L2"))
    if not done.get("committed") or [done["next_state"]["objects"][o]["exhausted"] for o in ("L1", "L2", "L3")] != [True, False, True]:
        fail("L1", f"the legend chosen: {done.get('reason') or done.get('errors')}")
    chose = next((t for t in done.get("trace") or [] if t.get("op") == "choose_objects"), {})
    if "Core 355.10.g" not in chose.get("rule_locators", []):
        fail("L1", f"the choice does not cite Core 355.10.g: {chose.get('rule_locators')}")

    one = legend_state(("L1", "p1"), ("L3", "p2"))
    done = apply_program(one, program(YOUR_LEGEND))
    if not done.get("committed") or done["next_state"]["objects"]["L1"]["exhausted"] or not done["next_state"]["objects"]["L3"]["exhausted"]:
        fail("L2", f"one legend: {done.get('reason') or done.get('errors')}")

    early = apply_program(two, program(YOUR_LEGEND), decisions=legend_pick(two, "L1", stage="finalization"))
    if early.get("committed"):
        fail("L3", "a decision made at finalization was taken")

    theirs = apply_program(two, program(YOUR_LEGEND), decisions=legend_pick(two, "L3"))
    if theirs.get("committed"):
        fail("L4", "the opponent's legend was readied")

    # L5: put on the Chain over L1; by the time it resolves L1 is gone and L2 is p1's legend
    changed = legend_state(("L2", "p1"), ("L3", "p2"))
    done = apply_program(changed, program(YOUR_LEGEND))
    if not done.get("committed") or done["next_state"]["objects"]["L2"]["exhausted"]:
        fail("L5", f"the legend p1 controls as it resolves: {done.get('reason') or done.get('errors')}")

    none = legend_state(("L3", "p2"))
    done = apply_program(none, program(YOUR_LEGEND))
    if not done.get("committed") or not done["next_state"]["objects"]["L3"]["exhausted"]:
        fail("L6", f"no legend: {done.get('reason') or done.get('errors')}")


# --- D: Downwell --------------------------------------------------------------------------------------------------------

def downwell_state():
    state = base_state()
    for oid, owner, controller, kind in (("g1", "p1", "p1", "gear"), ("g2", "p2", "p2", "gear"),
                                         ("u3", "p2", "p1", "unit"), ("L1", "p1", "p1", "legend")):
        state["objects"][oid] = {"owner": owner, "controller": controller, "kind": kind, "base_might": 2 if kind == "unit" else 0,
                                 "might_modifiers": [], "damage": 0, "exhausted": False}
    state["players"]["p1"]["zones"]["base"] += ["g1", "r1"]
    state["players"]["p1"]["zones"]["rune_deck"] = []
    state["players"]["p2"]["zones"]["base"] += ["g2"]
    state["players"]["p1"]["zones"]["legend_zone"] = ["L1"]
    state["battlefields"]["bf1"] = {"controller": "p1", "objects": ["u3"]}
    return state


DOWNWELL = [{"op": "return_to_hand", "effect_id": "r", "affected": {"criteria": {"location": "board", "kinds": ["unit", "gear"]}}}]


def check_downwell() -> None:
    problems = validate_program(program(DOWNWELL))
    if problems:
        fail("D1", f"refused: {problems}")
        return
    state = downwell_state()
    done = apply_program(state, program(DOWNWELL))
    if not done.get("committed"):
        fail("D1", f"refused: {done.get('reason') or done.get('errors')}")
        return
    z = done["next_state"]["players"]
    events = [t for t in done["trace"] if t.get("effect_id") == "r"]
    if len(events) != 1 or sorted(events[0].get("affected_objects") or []) != ["g1", "g2", "u1", "u2", "u3"] \
            or not events[0].get("criteria_snapshot_hash"):
        fail("D1", f"not one instruction over the set: {[(e.get('affected_objects'), e.get('criteria_snapshot_hash')) for e in events]}")
    hands = {p: sorted(object_identity(done["next_state"], o) and done["next_state"]["objects"][o]["kind"] for o in z[p]["zones"]["hand"])
             for p in ("p1", "p2")}
    if hands != {"p1": ["gear", "unit"], "p2": ["gear", "unit", "unit"]}:
        fail("D1", f"the owners' hands: {hands}")
    if z["p1"]["zones"]["legend_zone"] != ["L1"] or "r1" not in z["p1"]["zones"]["base"] or z["p2"]["zones"]["base"] \
            or [o for o in z["p1"]["zones"]["base"] if o != "r1"] or done["next_state"]["battlefields"]["bf1"]["objects"]:
        fail("D1", f"something else moved, or a unit or gear stayed: {z['p1']['zones']} {z['p2']['zones']['base']}")

    for label, criteria in (("beside kind", {"location": "board", "kind": "unit", "kinds": ["unit", "gear"]}),
                            ("one kind", {"location": "board", "kinds": ["unit"]}),
                            ("a rune", {"location": "board", "kinds": ["unit", "rune"]}),
                            ("off the whole board", {"location": "any_battlefield", "kinds": ["unit", "gear"]})):
        bad = copy.deepcopy(DOWNWELL)
        bad[0]["affected"]["criteria"] = criteria
        if not validate_program(program(bad)):
            fail("D2", f"kinds {label} validated")


def main() -> int:
    check_public_revealed()
    check_your_legend()
    check_downwell()
    if errors:
        print("FAILED: set 2 A1 review shapes")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: public choice among revealed cards (P1-P5), 'ready your legend' chosen as it resolves (L1-L6), one "
          "instruction over units and gear (D1-D2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
