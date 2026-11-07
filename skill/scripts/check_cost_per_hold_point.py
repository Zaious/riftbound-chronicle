#!/usr/bin/env python3
"""Regression gate: "I cost [2][Calm] less for each point you scored from holding this turn." (set 2 package A2:
Needlessly Large Yordle). Two printed reductions over one count - the points its player gained this turn by Holding
(Core 471.2, 473.1), kept by battlefield_control.score_battlefield in hold_points_this_turn only in a game where some
card reads it. Each comes off its own component as the cost is determined (Core 356.4), never below 0 (356.6).

  H1 none        no hold this turn: the printed cost, [6] and [Calm][Calm], is paid
  H2 one hold    p1 Holds bf1 (a point): [4] and [Calm] - paid with exactly that, nothing left
  H3 conquer     p1 Conquers bf1 instead: not a hold point - the printed cost again
  H4 two holds   p1 Holds bf1 and bf2: [2] and no Calm
  H5 short       after one hold, a pool one Energy short of [4][Calm]: refused
  H6 untouched   a game where no card reads the count keeps no ledger after a hold
  V              a power_reduction with no domain does not validate; the grammar lowers the line exactly
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battlefield_control as BC  # noqa: E402
import clause_grammar as CG  # noqa: E402
import play_transaction as PT  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

TEXT = "I cost :rb_energy_2::rb_rune_calm: less for each point you scored from holding this turn."
MODS = CG.compile_clause(TEXT, CG.load_grammar())["passive"]["object_fields"]["printed_cost_modifications"]


def board(*, reads=True):
    s = base_state()
    s["mode"] = {"victory_score": 8}
    s["turn_id"] = "turn-3"
    s["battlefields"]["bf2"] = {"controller": None, "objects": []}
    s["objects"]["yd"] = {"owner": "p1", "controller": "p1", "kind": "unit", "base_might": 5, "might_modifiers": [],
                          "damage": 0, "exhausted": False, "domains": ["calm"],
                          "printed_cost": {"energy": 6, "power": {"calm": 2}},
                          **({"printed_cost_modifications": copy.deepcopy(MODS)} if reads else {})}
    s["players"]["p1"]["zones"]["hand"].append("yd")
    return s


def score(s, how, *bfs):
    for bf in bfs:
        s, record, _ = BC.score_battlefield(s, "p1", bf, how, "turn-3")
        assert record.get("scored"), record
    return s


def play(s, energy, calm):
    s = copy.deepcopy(s)
    s["players"]["p1"]["resources"] = {"energy": energy, "power": {"calm": calm}}
    decl = {"schema_version": PT.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-yd", "actor": "p1", "card": "yd",
            "chain_item": {"id": "unit-1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": {"energy": 6, "power": {"calm": 2}}}, "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}
    return PT.play_card(fixture(), s, decl)


def left(done):
    pool = ((done.get("next_effect_state") or {}).get("players") or {}).get("p1", {}).get("resources") or {}
    return pool.get("energy"), (pool.get("power") or {}).get("calm")


def main() -> int:
    errors: list[str] = []
    for label, s, energy, calm in (("H1 none", board(), 6, 2),
                                   ("H2 one hold", score(board(), "hold", "bf1"), 4, 1),
                                   ("H3 conquer", score(board(), "conquer", "bf1"), 6, 2),
                                   ("H4 two holds", score(board(), "hold", "bf1", "bf2"), 2, 0)):
        if validate_state(s):
            errors.append(f"{label}: board invalid {validate_state(s)[:2]}")
            continue
        done = play(s, energy, calm)
        if not done.get("committed") or left(done) != (0, 0):
            errors.append(f"{label}: {done.get('reason_code')} {done.get('reason')} left {left(done)}")
    short = play(score(board(), "hold", "bf1"), 3, 1)
    if short.get("committed"):
        errors.append("H5 short: [3][Calm] paid a [4][Calm] cost")
    plain = score(board(reads=False), "hold", "bf1")
    if "hold_points_this_turn" in plain["players"]["p1"]:
        errors.append("H6 untouched: a game with no reader kept a hold ledger")
    bad = board()
    bad["objects"]["yd"]["printed_cost_modifications"][1].pop("domain")
    if not any("domain" in p for p in validate_state(bad)):
        errors.append("V: a power_reduction with no domain validated")
    if [m["kind"] for m in MODS] != ["energy_reduction", "power_reduction"] or MODS[0]["amount"] != 2 \
            or MODS[1].get("domain") != "calm":
        errors.append(f"V: the grammar lowered {MODS}")
    if errors:
        print("cost-per-hold-point checks FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("cost-per-hold-point checks passed: each point gained by Holding this turn takes [2] and one [Calm] off the "
          "card's cost (never below 0); a Conquer does not count; short, refused; no reader, no ledger (H1-H6, V)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
