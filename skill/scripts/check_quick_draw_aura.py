#!/usr/bin/env python3
"""Regression gate: "Your Equipment everywhere have [Quick-Draw]." (set 2 package A2: Jax - Unmatched). A printed keyword
aura over the controller's Equipment in every zone (criteria everywhere), while its source is on the board; a granted
Quick-Draw is the card's Reaction too (Core 819.1.b) and its attach as it is played (819.1.d).

  A1  jax on the board, p1's Equipment c1 in p1's hand (printed: no Quick-Draw, default timing): c1 has Quick-Draw
  A2  c1 declared at Reaction timing: committed; its play completion schedules the Quick-Draw trigger
  A3  jax not on the board (in p1's hand): c1 has no Quick-Draw, and Reaction timing is refused (timing_not_printed)
  A4  p2's Equipment in p2's hand: no Quick-Draw from p1's jax
  GPT A2 ruling 12 (friendly by control / ownership, not by zone):
  A5  jax's control passes to p2: p1's c1 loses Quick-Draw, p2's g2 gains it
  A6  on the board, an Equipment p2 owns that p1 controls has it; one p1 owns that p2 controls does not
  A7  Hidden: c1 hidden facedown at bf1 by p1 has it; played from facedown (at Reaction) its attach trigger is scheduled
  A8  the source leaves after c1 was played: the Quick-Draw trigger already on the Chain still resolves, attaching c1
  V   an "everywhere" aura of another keyword, and a Quick-Draw aura over units, do not validate
  G   the printed line lowers to exactly this aura
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_quick_draw import board, completed, declaration  # noqa: E402
from check_rules_core import fixture  # noqa: E402
import play_transaction as PT  # noqa: E402

AURA = {"aura_id": "everywhere-quick_draw", "keyword": "quick_draw",
        "criteria": {"kind": "gear", "tag": "Equipment", "controller_relation": "friendly", "everywhere": True}}


def scene(jax_on_board=True):
    s = board(quick_draw=False)
    s["objects"]["jax"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 3, "might_modifiers": [],
                           "damage": 0, "exhausted": False, "static_auras": [copy.deepcopy(AURA)]}
    s["players"]["p1"]["zones"]["base" if jax_on_board else "hand"].append("jax")
    s["objects"]["g2"] = {"owner": "p2", "controller": "p2", "kind": "gear", "base_might": 0, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "tags": ["Equipment"]}
    s["players"]["p2"]["zones"]["hand"].append("g2")
    return s


def main() -> int:
    errors: list[str] = []
    s = scene()
    if IR.validate_state(s):
        errors.append(f"board: {IR.validate_state(s)[:2]}")
    if not IR.has_keyword(s, "c1", "quick_draw"):
        errors.append("A1: c1 in p1's hand has no Quick-Draw")
    done = completed(s)
    items = [i.get("id") for i in done.get("next_timing_state", {}).get("chain", {}).get("items", [])]
    if not done.get("committed") or items != ["c1:quick_draw"]:
        errors.append(f"A2: {done.get('reason_code') or done.get('reason')} {items}")
    off = scene(jax_on_board=False)
    if IR.has_keyword(off, "c1", "quick_draw"):
        errors.append("A3: with jax off the board c1 still has Quick-Draw")
    refused = PT.play_card(fixture(), off, declaration("reaction"))
    if refused.get("committed") or refused.get("reason_code") != "timing_not_printed":
        errors.append(f"A3: Reaction timing with no Quick-Draw: {refused.get('committed')} {refused.get('reason_code')}")
    if IR.has_keyword(s, "g2", "quick_draw"):
        errors.append("A4: p2's Equipment has Quick-Draw from p1's jax")
    moved = scene()
    moved["objects"]["jax"]["controller"] = "p2"
    if IR.has_keyword(moved, "c1", "quick_draw") or not IR.has_keyword(moved, "g2", "quick_draw"):
        errors.append(f"A5: jax p2's - c1 {IR.has_keyword(moved, 'c1', 'quick_draw')}, "
                      f"g2 {IR.has_keyword(moved, 'g2', 'quick_draw')}")
    held = scene()
    for oid, owner, controller in (("borrowed", "p2", "p1"), ("lent", "p1", "p2")):
        held["objects"][oid] = {"owner": owner, "controller": controller, "kind": "gear", "base_might": 0,
                                "might_modifiers": [], "damage": 0, "exhausted": False, "tags": ["Equipment"]}
        held["players"][controller]["zones"]["base"].append(oid)
    if not IR.has_keyword(held, "borrowed", "quick_draw") or IR.has_keyword(held, "lent", "quick_draw"):
        errors.append(f"A6: p2-owned p1-controlled {IR.has_keyword(held, 'borrowed', 'quick_draw')}, "
                      f"p1-owned p2-controlled {IR.has_keyword(held, 'lent', 'quick_draw')}")
    hidden = scene()
    hidden["turn_id"] = "turn-2"
    hidden["battlefields"]["bf1"]["controller"] = "p1"
    hidden["players"]["p1"]["zones"]["hand"].remove("c1")
    hidden["battlefields"]["bf1"]["facedown"] = {"capacity": 1, "cards": [{"object_id": "c1", "controller": "p1",
                                                                           "hidden_on_turn": "turn-1"}]}
    if not IR.has_keyword(hidden, "c1", "quick_draw"):
        errors.append("A7: the hidden Equipment has no Quick-Draw")
    decl = declaration("reaction")
    decl.update({"source": {"kind": "facedown", "battlefield": "bf1"},
                 "cost_override": {"kind": "ignore_base_cost", "source": "hidden"},
                 "entry_location": {"kind": "battlefield", "battlefield": "bf1"}})
    decl.pop("payment_context", None)
    from check_rules_core import item  # noqa: E402
    from resolution_bridge import resolve_with_program  # noqa: E402
    played = PT.play_card(fixture(), hidden, decl)
    if not played.get("committed"):
        errors.append(f"A7: played from facedown at Reaction: {played.get('reason_code')} {played.get('reason')}")
    else:
        after = fixture(priority="p2", items=[item("gear-1", "p1", "gear", "reaction", "finalized")], passes=["p1", "p2"])
        got = resolve_with_program(after, "gear-1", played["next_effect_state"], None)
        ids = [i.get("id") for i in (got.get("next_timing_state") or {}).get("chain", {}).get("items", [])]
        if not got.get("committed") or ids != ["c1:quick_draw"]:
            errors.append(f"A7: from facedown the attach trigger: {got.get('reason')} {ids}")
    pending = completed(scene())
    if pending.get("committed"):
        from check_quick_draw import host  # noqa: E402
        from resolution_bridge import finalize_trigger  # noqa: E402
        from rules_core import pass_priority  # noqa: E402
        st = pending["next_effect_state"]
        st["players"]["p1"]["zones"]["base"].remove("jax")
        st["players"]["p1"]["zones"]["trash"].append("jax")
        qd = IR.quick_draw_program(pending["next_effect_state"], "c1", "p1")
        fin = finalize_trigger(pending["next_timing_state"], st, {qd["program_id"]: qd}, host(st, "u1"))
        res = {}
        if fin.get("committed"):
            timing = fin["next_timing_state"]
            for actor in ("p1", "p2"):
                timing = (pass_priority(timing, actor) or {}).get("next_state") or timing
            res = resolve_with_program(timing, "c1:quick_draw", fin["next_effect_state"], qd)
        if not res.get("committed") or res["next_effect_state"]["objects"]["c1"].get("attached_to") != "u1":
            errors.append(f"A8: jax gone, the pending Quick-Draw: {fin.get('reason')} {fin.get('message')} "
                          f"{res.get('reason')}")
    for label, aura in (("an everywhere Assault aura", {**AURA, "keyword": "assault"}),
                        ("a Quick-Draw aura over units", {**AURA, "criteria": {**AURA["criteria"], "kind": "unit"}})):
        bad = copy.deepcopy(s)
        bad["objects"]["jax"]["static_auras"] = [aura]
        if not any("static_auras" in p for p in IR.validate_state(bad)):
            errors.append(f"V: {label} validated")
    got = CG.compile_clause("Your Equipment everywhere have [Quick-Draw].", CG.load_grammar())
    if ((got.get("passive") or {}).get("object_fields") or {}).get("static_auras") != [AURA]:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    if errors:
        print("quick-draw aura checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("quick-draw aura checks passed: the controller's Equipment in hand has Quick-Draw while the source is on the board "
          "- played at Reaction, its attach trigger scheduled; not with the source away, not for the opponent's; friendly by "
          "control, not by zone (control change, borrowed and lent Equipment); a hidden one too, its trigger scheduled from "
          "facedown; a pending trigger outlives the source; validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
