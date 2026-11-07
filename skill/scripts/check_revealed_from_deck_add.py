#!/usr/bin/env python3
"""Regression gate: Undertitan's Energy-on-reveal line (set 2 package A2). A card's own static
(revealed_from_deck_add_energy N): as a reveal instruction reveals it from its owner's Main Deck, its owner adds N
Energy (Core 425, 430).

  R1  p1 reveals the top card of its Main Deck - the card: p1's Energy 0 -> 2
  R2  a reveal_until that passes over the card: 2 added as well
  R3  a look at the top card (private, not a reveal): nothing added
  R4  the card second from the top, one card revealed: nothing added
  R5  (GPT A2 ruling 18) two such cards among the top three, one reveal of three: both add, at one moment (at_once), each
      recorded at its own place in the reveal
  R6  two such cards revealed by a reveal-until: each adds as it is revealed, one by one, in the deck's order
  V   a non-positive amount does not validate
  G   the printed line lowers to exactly that field
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clause_grammar as CG  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_effect_ir import base_state  # noqa: E402


def board(position=0):
    s = base_state()
    s["objects"]["ut"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 6, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "revealed_from_deck_add_energy": 2}
    s["players"]["p1"]["zones"]["main_deck"].insert(position, "ut")
    return s


def run(s, effect):
    return IR.apply_program(s, {"schema_version": IR.PROGRAM_VERSION, "ruleset": {"core": IR.CORE_RULESET,
                                                                                  "faq_as_of": IR.FAQ_AS_OF},
                                "program_id": "rv", "controller": "p1", "effects": [effect]})


def energy(done):
    return (done.get("next_state") or {}).get("players", {}).get("p1", {}).get("resources", {}).get("energy")


def main() -> int:
    errors: list[str] = []
    if IR.validate_state(board()):
        errors.append(f"board: {IR.validate_state(board())[:2]}")
    for label, s, effect, want in (
            ("R1 reveal", board(), {"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 1}, 2),
            ("R2 reveal_until", board(), {"op": "reveal_until", "effect_id": "ru", "player": "p1", "until": {"kind": "spell"}}, 2),
            ("R3 look", board(), {"op": "look_at_top", "effect_id": "lk", "player": "p1", "count": 1}, 0),
            ("R4 not reached", board(position=1),
             {"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 1}, 0)):
        done = run(s, effect)
        if not done.get("committed") or energy(done) != want:
            errors.append(f"{label}: {done.get('reason_code')} {done.get('errors') or done.get('reason')} energy {energy(done)}")
    two = board()
    two["objects"]["ut2"] = {**copy.deepcopy(two["objects"]["ut"])}
    two["players"]["p1"]["zones"]["main_deck"].insert(2, "ut2")
    done = run(copy.deepcopy(two), {"op": "reveal", "effect_id": "rv", "player": "p1", "from": "main_deck_top", "count": 3})
    adds = [(a["object_id"], a["mode"], a["revealed_at"]) for t in done.get("trace") or [] for a in t.get("revealed_adds") or []]
    if energy(done) != 4 or adds != [("ut", "at_once", 0), ("ut2", "at_once", 2)]:
        errors.append(f"R5 at once: energy {energy(done)}, adds {adds}")
    seq = copy.deepcopy(two)
    seq["players"]["p1"]["zones"]["main_deck"].remove("ut2")
    seq["players"]["p1"]["zones"]["main_deck"].insert(1, "ut2")
    done = run(seq, {"op": "reveal_until", "effect_id": "ru", "player": "p1", "until": {"kind": "spell"}})
    adds = [(a["object_id"], a["mode"], a["revealed_at"]) for t in done.get("trace") or [] for a in t.get("revealed_adds") or []]
    if energy(done) != 4 or adds != [("ut", "one_by_one", 0), ("ut2", "one_by_one", 1)]:
        errors.append(f"R6 one by one: energy {energy(done)}, adds {adds}")
    bad = board()
    bad["objects"]["ut"]["revealed_from_deck_add_energy"] = 0
    if not any("revealed_from_deck_add_energy" in p for p in IR.validate_state(bad)):
        errors.append("V: an amount of 0 validated")
    got = CG.compile_clause("As I'm revealed from your deck, [Add] :rb_energy_2:.", CG.load_grammar())
    if (got.get("passive") or {}).get("object_fields") != {"revealed_from_deck_add_energy": 2}:
        errors.append(f"G: lowered to {got.get('production_id')} {got.get('passive')}")
    if errors:
        print("revealed-from-deck add checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("revealed-from-deck add checks passed: revealed from its owner's Main Deck (a reveal or a reveal-until) it adds "
          "2 Energy; looked at, or not reached, nothing; validated; lowered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
