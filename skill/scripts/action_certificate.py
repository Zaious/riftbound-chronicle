#!/usr/bin/env python3
"""The per-state certificate of the closed environment's action set (C2, package 15; the owner's ruling of 2026-10-18:
certification state by state, never a claim over states not reached). For one state and one player it says whether that
player's set of actions - or, at a procedure point, of the point's options - is proved whole, and `complete_action_set`
is true only then. A simulation that meets a state whose certificate is false stops there (fail closed).

  the receipt       action_receipt.state_receipt: the state is one of the catalogue's environment, every action kind
                    enumerated, the published set computed on the player's view and equal to the true state's, no
                    unseen card named (GPT 2026-10-15 rulings 1, 5)
  an action point   for the player who acts, every family's differential: E(s) is exactly {d in D(s): V(s, d)}
                    (action_space.differential); the other player has no action and their receipt lists none
  a procedure point the decision differential: the procedure's ways are exactly D(s)'s, and every way holds exactly the
                    decisions its events need (decision_space.differential, event_ledger) - computed once per point and
                    shared by both players' certificates
  the binding       the receipt's state, catalogue and engine hashes; the certificate's own hash over all of it

    certify(timing_state, effect_state, actor, catalogue, decision_differential=None) -> certificate
"""
from __future__ import annotations

from typing import Any

import action_receipt as AR
import action_space as AS
import effect_ir as IR
import legal_action as LA
import rules_core

CERTIFICATE_VERSION = "c2-state-certificate.v1"


def over_cap_receipts(receipts: list[dict[str, Any]] | tuple) -> list[dict[str, Any]]:
    """The chance receipts of operations with more outcomes than decision_space.CHANCE_CAP (n! orders of n cards)."""
    import math
    import decision_space as DS
    return [r for r in receipts or [] if math.factorial(len(r.get("permutation") or [])) > DS.CHANCE_CAP]


def receipt_hash(receipt: dict[str, Any]) -> str:
    """A chance receipt's content - its operation, player and the permutation chance gave - hashed (the outcome itself,
    so a certificate given it can be replayed under exactly it; GPT PACKAGE15 ruling 6)."""
    return IR.hash_value({k: receipt.get(k) for k in ("operation", "operation_id", "player", "permutation")})


def _realized_prefix(timing_state, effect_state, catalogue, made, given) -> dict[str, Any] | None:
    """The pre-chance way the game's committed answer extends: the procedure's own prefix up to the chance node the
    receipt answers, with no outcome given (decision_space.procedure_ways to_chance), whose every answer the game made."""
    import decision_space as DS
    found = DS.procedure_ways(timing_state, effect_state, catalogue, (), to_chance=True)
    made_keys = {(d["decision_id"], IR.hash_value(d["value"])) for d in made.get("decisions") or []}
    made_settings = made.get("settings") or {}
    ops = {(r["operation_id"], tuple(sorted(r["permutation"]))) for r in given}
    for way in found.get("ways") or []:
        node = way.get("chance")
        if not node or (node["operation_id"], tuple(node["cards"])) not in ops:
            continue
        if all((d["decision_id"], IR.hash_value(d["value"])) in made_keys for d in way["decisions"]) \
                and all(made_settings.get(k) == v for k, v in way["settings"].items()):
            return {"decisions": way["decisions"], "settings": way["settings"]}
    return None


def _summary(diff: dict[str, Any]) -> dict[str, Any]:
    return {"complete": bool(diff.get("complete")), "stopped": diff.get("stopped"), "contract": diff.get("contract"),
            "discovered": diff.get("discovered"), "ledger": list(diff.get("ledger") or [])[:4],
            "missing": len(diff.get("missing") or []), "extra": len(diff.get("extra") or [])}


def decision_differential(timing_state: dict[str, Any], effect_state: dict[str, Any], catalogue: dict[str, Any],
                          receipts: list[dict[str, Any]] | tuple = (), made: dict[str, Any] | None = None) -> dict[str, Any]:
    """The procedure point's differential, summarized for its certificates.

    2026-10-19 (GPT PACKAGE15 ruling 6): a chance operation of more outcomes than CHANCE_CAP is never all tried, and the
    point is certified in two parts. Before it (`pre_chance`): every way up to that node, no outcome given - the
    decisions made there cannot read the outcome, so this part is whole over all of them. After it (`after_chance`):
    once the outcome is a receipt - `receipts`, the ones the game used - the point's ways given that outcome and the
    decisions the game made before it (`made`, the answer it committed: the pre-chance way it extends), the receipt bound
    by its content (receipt_hash). Without them the after part is not certified (named)."""
    import decision_space as DS
    given = over_cap_receipts(receipts)
    with IR.frozen_inputs(effect_state):
        # every way to its end or to a large chance node: with no such node met, these are the point's whole ways
        pre = DS.differential(timing_state, effect_state, catalogue, (), to_chance=True)
        if not pre.get("chance_prefixes"):
            return {**_summary(pre), "chance": None}
        prefix = _realized_prefix(timing_state, effect_state, catalogue, made, given) if given and made else None
        after = DS.differential(timing_state, effect_state, catalogue, given, given_prefix=prefix) if prefix is not None \
            else {"complete": False, "stopped": "after the chance: no receipt of its outcome, or no pre-chance way the "
                                                "game's answer extends, is given"}
    bound = [{"operation_id": r["operation_id"], "receipt_hash": receipt_hash(r)} for r in given]
    after_summary = {**_summary(after), "receipts": bound}
    after_summary["certificate_hash"] = IR.hash_value(after_summary)
    summary = _summary(pre)
    return {**summary, "complete": summary["complete"] and after_summary["complete"],
            "stopped": summary["stopped"] or (None if after_summary["complete"] else f"after_chance: {after_summary['stopped']}"),
            "chance": {"pre_chance": _summary(pre), "after_chance": after_summary}}


def certify(timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str, catalogue: dict[str, Any],
            decision_differential_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    receipt = AR.state_receipt(timing_state, effect_state, actor, catalogue)
    why = [f"receipt:{w}" for w in receipt["why"]]
    procedure = rules_core.next_procedure(timing_state)
    differentials: dict[str, Any] = {}
    if procedure.get("discretionary_actions_allowed") is True:
        if procedure.get("subject") == actor:
            result = LA.enumerate_actions(AR._observation(timing_state, effect_state, actor), actor, catalogue=catalogue)
            for family in AS.ACTION_KINDS:
                diff = AS.differential(family, timing_state, effect_state, actor, result, catalogue)
                differentials[family] = {"complete": bool(diff["complete"]), "stopped": diff.get("stopped"),
                                         "accepted": diff.get("accepted"), "enumerated": diff.get("enumerated"),
                                         "missing": len(diff.get("missing") or []), "extra": len(diff.get("extra") or [])}
                if not diff["complete"]:
                    why.append(f"differential:{family}:{diff.get('stopped') or 'missing/extra'}")
        elif receipt["actions"]:
            why.append(f"a player who does not act lists {len(receipt['actions'])} actions")
    else:
        summary = decision_differential_summary or decision_differential(timing_state, effect_state, catalogue)
        differentials["decision"] = summary
        if not summary["complete"]:
            why.append(f"differential:decision:{summary.get('stopped') or (summary.get('ledger') or ['missing/extra'])[0]}")
    certificate = {"schema_version": CERTIFICATE_VERSION, "actor": actor, "procedure": procedure.get("procedure"),
                   "receipt_hash": receipt["receipt_hash"], "timing_state_hash": receipt["timing_state_hash"],
                   "effect_state_hash": receipt["effect_state_hash"], "catalogue_hash": receipt["catalogue_hash"],
                   "engine": receipt["engine"], "actions": len(receipt["actions"]), "differentials": differentials,
                   "complete_action_set": not why, "why": why}
    certificate["certificate_hash"] = IR.hash_value({k: v for k, v in certificate.items() if k != "certificate_hash"})
    return certificate
