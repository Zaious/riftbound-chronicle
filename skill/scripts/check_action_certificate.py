#!/usr/bin/env python3
"""Gate (C2, package 15): the per-state certificate of the closed environment's action set (action_certificate).

  A1 whole      at Setup's Mulligan (a procedure point) both players' certificates are complete - the decision
                differential and its event ledger hold, p1's receipt lists its options and p2's none; at a priority point
                the actor's certificate is complete with every family's differential, and the other player's lists no
                action
  A2 action     a family whose differential does not hold (its accepted plays not the enumerator's) makes the actor's
                certificate false, by name
  A3 procedure  a decision differential that does not hold - or whose event ledger finds a needed decision missing -
                makes both players' certificates false, by name
  A4 sealed     the certificate's hash is over everything it says: changing any field gives another hash
  A5 chance     (GPT PACKAGE15 ruling 6) a choice of five of six, then chance orders them (120 outcomes): before the
                chance the six choices are whole with no outcome; after it the point is certified only given the
                choice the game made and the outcome's receipt, bound by the receipt's content

    python skill/scripts/check_action_certificate.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import action_certificate as AC  # noqa: E402
import action_space as AS  # noqa: E402
import check_decision_space as CD  # noqa: E402
import effect_ir as IR  # noqa: E402
from check_rules_core import fixture  # noqa: E402

errors: list[str] = []


def fail(gate: str, why: str) -> None:
    errors.append(f"{gate}: {why}")


def mulligan_point(cat):
    hand = [(f"h{i}", "Grunt", "p1", "hand") for i in range(4)] + [(f"k{i}", "Grunt", "p2", "hand") for i in range(4)]
    deck = [(f"d{i}", "Grunt", "p1", "main_deck") for i in range(6)] + [(f"e{i}", "Grunt", "p2", "main_deck") for i in range(6)]
    e = CD.environment(cat, hand + deck)
    t = {**fixture(priority=None), "phase": "setup", "turns_taken": {"p1": 0, "p2": 0}, "mulligans_pending": ["p1", "p2"]}
    return t, e


def a5_large_chance(cat) -> None:
    """A5 (GPT PACKAGE15 ruling 6): a point whose player chooses five of six cards in the trash, then chance orders those
    five (120 outcomes, past CHANCE_CAP). Before the chance: the six choices are its pre-chance ways, whole with no
    outcome given. After it: certified only given the choice the game made and the receipt of the outcome, bound by the
    receipt's content - with neither, the point is not certified, by name; another order of the same cards is another
    receipt hash."""
    t, e = CD.resolving_point(cat, "Shuffle5", [(f"t{i}", "Grunt", "p1", "trash") for i in range(6)])
    if t is None:
        fail("A5 chance", "the fixture was not reached")
        return
    bare = AC.decision_differential(t, e, cat)
    pre = (bare.get("chance") or {}).get("pre_chance") or {}
    if bare["complete"] or not pre.get("complete") or pre.get("contract") != 6 or "after the chance" not in str(bare.get("stopped")):
        fail("A5 chance", f"with no outcome: {bare['complete']} {bare.get('stopped')} pre {pre}")
        return
    import decision_space as DS
    prefix = next(w for w in DS.procedure_ways(t, e, cat, (), to_chance=True)["ways"])
    node = prefix["chance"]

    def receipt(order):
        return {"schema_version": "randomization-receipt.v1", "receipt_id": "game:1", "operation": node["operation"],
                "operation_id": node["operation_id"], "player": node["player"], "permutation": list(order),
                "provenance": {"provider": "check", "method": "seeded"}}
    made = {"decisions": prefix["decisions"], "settings": prefix["settings"]}
    given = AC.decision_differential(t, e, cat, [receipt(reversed(node["cards"]))], made)
    after = (given.get("chance") or {}).get("after_chance") or {}
    if not given["complete"] or not after.get("complete") or not after.get("receipts"):
        fail("A5 chance", f"given the choice and its outcome: {given['complete']} {given.get('stopped')} after {after}")
        return
    other = AC.decision_differential(t, e, cat, [receipt(node["cards"])], made)
    if other["chance"]["after_chance"]["receipts"][0]["receipt_hash"] == after["receipts"][0]["receipt_hash"]:
        fail("A5 chance", "two orders of the same cards were bound to one receipt hash")
    alone = AC.decision_differential(t, e, cat, [receipt(reversed(node["cards"]))])
    if alone["complete"]:
        fail("A5 chance", "the outcome without the choice the game made certified the point after the chance")


def main() -> int:
    cat = CD.catalogue()
    t, e = mulligan_point(cat)
    shared = AC.decision_differential(t, e, cat)
    p1, p2 = AC.certify(t, e, "p1", cat, shared), AC.certify(t, e, "p2", cat, shared)
    if not (p1["complete_action_set"] and p2["complete_action_set"]) or p1["actions"] != 11 or p2["actions"] != 0:
        fail("A1 whole", f"the Mulligan: p1 {p1['complete_action_set']} {p1['actions']} {p1['why'][:2]}; "
                         f"p2 {p2['complete_action_set']} {p2['actions']} {p2['why'][:2]}")
    board = CD.environment(cat, [("g1", "Grunt", "p1", "base"), ("g2", "Grunt", "p2", "base"),
                                 ("d1", "Grunt", "p1", "main_deck"), ("d2", "Grunt", "p2", "main_deck")])
    timing = fixture()
    actor = AC.certify(timing, board, "p1", cat)
    other = AC.certify(timing, board, "p2", cat)
    if not actor["complete_action_set"] or set(actor["differentials"]) != set(AS.ACTION_KINDS) \
            or not other["complete_action_set"] or other["actions"]:
        fail("A1 whole", f"a priority point: p1 {actor['complete_action_set']} {sorted(actor['differentials'])} "
                         f"{actor['why'][:2]}; p2 {other['complete_action_set']} {other['actions']} {other['why'][:2]}")
    real = AS.differential

    def broken(family, *args, **kwargs):
        got = real(family, *args, **kwargs)
        return {**got, "complete": False, "missing": [{"kind": family}]} if family == "standard_move" else got
    AS.differential = broken
    try:
        bad = AC.certify(timing, board, "p1", cat)
    finally:
        AS.differential = real
    if bad["complete_action_set"] or not any(w.startswith("differential:standard_move") for w in bad["why"]):
        fail("A2 action", f"a family's differential that does not hold left the certificate {bad['complete_action_set']} {bad['why'][:2]}")
    for label, summary in (("missing ways", {**shared, "complete": False, "missing": 1}),
                           ("a needed decision missing", {**shared, "complete": False, "ledger": ["trigger_order:b:p1 needs one decision"]})):
        one = AC.certify(t, e, "p1", cat, summary)
        if one["complete_action_set"] or not any(w.startswith("differential:decision") for w in one["why"]):
            fail("A3 procedure", f"{label}: the certificate is {one['complete_action_set']} {one['why'][:2]}")
    for field, value in (("actions", p1["actions"] + 1), ("complete_action_set", False), ("receipt_hash", "sha256:" + "0" * 64)):
        changed = {**copy.deepcopy(p1), field: value}
        if IR.hash_value({k: v for k, v in changed.items() if k != "certificate_hash"}) == p1["certificate_hash"]:
            fail("A4 sealed", f"changing {field} kept the certificate's hash")
    a5_large_chance(cat)
    if errors:
        print("FAILED: per-state certificate checks")
        for line in errors:
            print("  - " + line)
        return 1
    print("OK: the Mulligan and a priority point are certified whole for both players (A1); a family's differential or a "
          "procedure point's that does not hold, or a needed decision missing, makes the certificate false by name "
          "(A2, A3); its hash covers every field (A4); a large chance is certified before it whole and after it given the "
          "choice made and its bound receipt (A5)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
