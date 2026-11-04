#!/usr/bin/env python3
"""Match Analyst, engine side: replay a recorded game through the engine and write what happened at every step
(`riftbound-engine-trace.v1`).

A game record holds, per step, the chosen option's key and the chance receipts it used, and the state hashes before it
(the shape of `r5p-game-record.v1`). This module replays it with the engine's own transitions - the same calls the
record was played with - checks every state hash against the record, and keeps, per step:

  view      turn, phase, the four-state label, Priority, Focus, the Chain, both scores, each Battlefield's controller
  action    an action point's action, by card name (never an object's program)
  options   the actor's enumerated alternatives at an action point, by card name, with the families that abstained
  answers   a procedure point's player decisions (a Mulligan, a target), and how many options each had
  changes   what the step changed, read from the states before and after: zone changes (each with who may see the
            card's identity), points, Battlefield control, Showdowns, the turn, damage, the game's end
  hashes    the timing and effect state hashes before and after

The start state is the caller's (the record's Setup is the recorder's procedure, not the engine's), so the trace does
not depend on any recorder. The catalogue is read and never written into the trace.

    trace_record(record, catalogue, start_timing, start_effect, players=None) -> trace
"""
from __future__ import annotations

import copy
from typing import Any

import action_receipt as AR
import action_space as AS
import decision_space as DS
import effect_ir as IR
import game_events as GE
import game_loop as GL
import legal_action as LA
import rules_core as RC

TRACE_VERSION = "riftbound-engine-trace.v1"
PLAYERS = ("p1", "p2")


class TraceError(Exception):
    pass


def hashes(t: dict, e: dict) -> dict[str, str]:
    return {"timing": RC.state_hash(t), "effect": IR.hash_value(e)}


def turn_number(e: dict) -> int:
    try:
        return int(str(e.get("turn_id", "turn-0")).rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def _name(e: dict, object_id: str | None) -> str | None:
    if object_id is None:
        return None
    obj = (e.get("objects") or {}).get(object_id)
    if obj is None:
        return None
    if obj.get("card_ref"):
        return obj["card_ref"]
    if obj.get("is_token") or object_id.startswith("token:"):
        tags = obj.get("tags") or []
        stem = tags[0] if tags else (object_id.split(":")[1] if object_id.count(":") >= 2 else "")
        return f"{stem.title()} Token".strip()
    return None


def _bf_name(e: dict, bf: str | None) -> str | None:
    if bf is None:
        return None
    return (e.get("battlefields") or {}).get(bf, {}).get("card_ref") or bf


def view(t: dict, e: dict) -> dict[str, Any]:
    showdown = t.get("showdown") or {}
    chain = []
    for item in (t.get("chain") or {}).get("items", []):
        card = None
        for cid, entry in (e.get("chain_items") or {}).items():
            if cid == item.get("id") and isinstance(entry, dict):
                card = _name(e, entry.get("card"))
        chain.append({"id": item.get("id"), "controller": item.get("controller"), "object_kind": item.get("object_kind"),
                      "timing": item.get("timing"), "status": item.get("status"), "card": card})
    battlefields = {}
    for bf, entry in sorted((e.get("battlefields") or {}).items()):
        units = {p: [] for p in PLAYERS}
        for oid in entry.get("objects") or []:
            obj = e["objects"].get(oid) or {}
            if obj.get("controller") in units:
                units[obj["controller"]].append(_name(e, oid))
        battlefields[bf] = {"card": entry.get("card_ref"), "controller": entry.get("controller"),
                            "units": {p: sorted(n for n in v if n) for p, v in units.items()},
                            "facedown": len((entry.get("facedown") or {}).get("cards") or [])}
    return {"turn": turn_number(e), "turn_player": t.get("turn_player"), "phase": t.get("phase"),
            "state_label": RC.state_label(t), "priority": t.get("priority"), "focus": showdown.get("focus"),
            "showdown": {"active": bool(showdown.get("active")), "kind": showdown.get("kind"),
                         "battlefield": showdown.get("battlefield")},
            "chain": chain, "points": {p: e["players"][p].get("points", 0) for p in PLAYERS},
            "battlefields": battlefields}


def _location_text(e: dict, loc: dict | None) -> dict | None:
    if not isinstance(loc, dict):
        return None
    if loc["kind"] == "player_zone":
        return {"zone": loc["zone"], "player": loc["player"]}
    if loc["kind"] == "battlefield":
        return {"zone": "battlefield", "battlefield": loc["battlefield"], "battlefield_card": _bf_name(e, loc["battlefield"])}
    if loc["kind"] == "facedown":
        return {"zone": "facedown", "battlefield": loc["battlefield"], "battlefield_card": _bf_name(e, loc["battlefield"])}
    if loc["kind"] == "chain":
        return {"zone": "chain"}
    return {"zone": loc["kind"]}


BOARD = {"base", "battlefield"}


def _zone_kind(src: str | None, dst: str | None, obj_kind: str | None) -> str:
    pair = (src, dst)
    if pair == ("main_deck", "hand"):
        return "drew"
    if pair == ("hand", "main_deck"):
        return "returned_to_deck"
    if pair == ("rune_deck", "base"):
        return "channeled"
    if src == "base" and dst == "rune_deck":
        return "recycled"
    if src == "hand" and dst == "chain":
        return "played"
    if src == "hand" and dst in BOARD:
        return "played"
    if src == "chain" and dst in BOARD:
        return "entered"
    if src == "chain" and dst == "trash":
        return "resolved"
    if src in BOARD and dst in BOARD:
        return "moved"
    if src in BOARD and dst == "trash":
        return "died" if obj_kind == "unit" else "trashed"
    if src == "hand" and dst == "trash":
        return "discarded"
    if src == "hand" and dst == "facedown":
        return "hid"
    if src == "facedown":
        return "revealed"
    if src in BOARD and dst == "hand":
        return "returned_to_hand"
    if dst == "banishment":
        return "banished"
    if src == "main_deck" and dst == "trash":
        return "milled"
    return "zone_change"


def changes(t0: dict, e0: dict, t1: dict, e1: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if turn_number(e1) != turn_number(e0):
        out.append({"kind": "turn_began", "turn": turn_number(e1), "player": t1.get("turn_player"), "visibility": "public"})
    s0, s1 = GE.snapshot(e0), GE.snapshot(e1)
    for oid in sorted(set(s0) | set(s1)):
        a, b = s0.get(oid, {}), s1.get(oid, {})
        la, lb = a.get("location"), b.get("location")
        owner = (e1["objects"].get(oid) or e0["objects"].get(oid) or {}).get("owner")
        kind = (e1["objects"].get(oid) or e0["objects"].get(oid) or {}).get("kind")
        name = _name(e1, oid) or _name(e0, oid)
        if a.get("exists") and not b.get("exists"):
            out.append({"kind": "ceased_to_exist", "object": oid, "card": name, "owner": owner,
                        "from": _location_text(e0, la), "visibility": "public"})
            continue
        if not a.get("exists") and b.get("exists"):
            out.append({"kind": "created", "object": oid, "card": name, "owner": owner, "object_kind": kind,
                        "to": _location_text(e1, lb), "visibility": "public"})
            continue
        if la != lb:
            src, dst = _location_text(e0, la), _location_text(e1, lb)
            identity = GE.identity_visibility(la, lb, owner)
            out.append({"kind": _zone_kind((src or {}).get("zone"), (dst or {}).get("zone"), kind), "object": oid,
                        "card": name, "owner": owner, "object_kind": kind, "from": src, "to": dst,
                        "visibility": "public" if identity == "public" else "private:" + ",".join(identity)})
        elif b.get("exists") and isinstance(lb, dict) and (lb["kind"] == "battlefield" or lb.get("zone") == "base"):
            d0 = (e0["objects"].get(oid) or {}).get("damage", 0) or 0
            d1 = (e1["objects"].get(oid) or {}).get("damage", 0) or 0
            if d1 > d0:
                out.append({"kind": "damaged", "object": oid, "card": name, "owner": owner, "amount": d1 - d0,
                            "total": d1, "visibility": "public"})
    for p in PLAYERS:
        p0, p1 = e0["players"][p].get("points", 0), e1["players"][p].get("points", 0)
        if p1 != p0:
            out.append({"kind": "scored", "player": p, "from": p0, "to": p1, "delta": p1 - p0, "visibility": "public"})
    for bf in sorted(e1.get("battlefields") or {}):
        c0 = (e0.get("battlefields") or {}).get(bf, {}).get("controller")
        c1 = e1["battlefields"][bf].get("controller")
        if c0 != c1:
            out.append({"kind": "control_changed", "battlefield": bf, "battlefield_card": _bf_name(e1, bf),
                        "from": c0, "to": c1, "visibility": "public"})
    sd0, sd1 = t0.get("showdown") or {}, t1.get("showdown") or {}
    if not sd0.get("active") and sd1.get("active"):
        out.append({"kind": "showdown_opened", "battlefield": sd1.get("battlefield"),
                    "battlefield_card": _bf_name(e1, sd1.get("battlefield")), "showdown_kind": sd1.get("kind"),
                    "focus": sd1.get("focus"), "visibility": "public"})
    if sd0.get("active") and not sd1.get("active"):
        out.append({"kind": "showdown_closed", "battlefield": sd0.get("battlefield"),
                    "battlefield_card": _bf_name(e0, sd0.get("battlefield")), "showdown_kind": sd0.get("kind"),
                    "visibility": "public"})
    if t1.get("terminal") and not t0.get("terminal"):
        term = t1["terminal"]
        out.append({"kind": "game_over", "winner": term.get("winner"), "reason": term.get("reason"),
                    "final_points": term.get("final_points"), "visibility": "public"})
    return out


def describe_action(e: dict, action: dict) -> dict[str, Any]:
    kind = action.get("kind")
    out: dict[str, Any] = {"kind": kind}
    decl = action.get("declaration") or {}
    if kind == "play_card":
        out.update({"card": _name(e, decl.get("card")), "object": decl.get("card"),
                    "timing": (decl.get("chain_item") or {}).get("timing"),
                    "object_kind": (decl.get("chain_item") or {}).get("object_kind"),
                    "cost": (decl.get("cost") or {}).get("base")})
        loc = decl.get("entry_location") or {}
        if loc:
            out["destination"] = "base" if loc.get("kind") == "base" else _bf_name(e, loc.get("battlefield"))
    elif kind == "activate_ability":
        act = decl.get("activation") or {}
        out.update({"card": _name(e, act.get("source_object")), "object": act.get("source_object"),
                    "ability": str(act.get("ability_id", "")).rsplit(":", 1)[-1],
                    "ability_kind": (decl.get("chain_item") or {}).get("ability_kind"),
                    "timing": (decl.get("chain_item") or {}).get("timing")})
    elif kind == "standard_move":
        dest = decl.get("destination") or {}
        out.update({"units": [_name(e, u) for u in decl.get("units") or []], "objects": list(decl.get("units") or []),
                    "destination": "base" if dest.get("kind") == "base" else _bf_name(e, dest.get("battlefield")),
                    "battlefield": dest.get("battlefield")})
    elif kind == "hide":
        out.update({"card": _name(e, decl.get("card") or decl.get("object_id")),
                    "battlefield": decl.get("battlefield")})
    return out


def _is_add(desc: dict) -> bool:
    return desc.get("kind") == "activate_ability" and desc.get("ability_kind") == "add"


def options_summary(e: dict, found: dict, actions: list[dict], chosen_key: str) -> dict[str, Any]:
    items = []
    for a in actions:
        desc = describe_action(e, a)
        desc.pop("object", None)
        desc.pop("objects", None)
        items.append({**desc, "chosen": AS.action_key_hash(a) == chosen_key, "add_ability": _is_add(desc)})
    families = (found.get("enumeration") or {}).get("families") or []
    return {"complete_action_set": bool(found.get("complete_action_set")), "count": len(items), "items": items,
            "abstained": [{"family": f.get("family"), "reason_code": f.get("reason_code")}
                          for f in families if f.get("status") != "enumerated"]}


def trace_record(record: dict, catalogue: dict, start_timing: dict, start_effect: dict,
                 players: dict | None = None) -> dict[str, Any]:
    t, e = copy.deepcopy(start_timing), copy.deepcopy(start_effect)
    if record.get("start") and hashes(t, e) != record["start"]:
        raise TraceError("the start state is not the record's start")
    steps_out: list[dict[str, Any]] = []
    for index, step in enumerate(record.get("steps") or []):
        before = hashes(t, e)
        if step.get("before") and before != step["before"]:
            raise TraceError(f"step {index}: the state before it is not the record's")
        entry: dict[str, Any] = {"k": index, "kind": step.get("kind"), "view": view(t, e), "before": before}
        if step["kind"] == "action":
            actor = step["actor"]
            found = LA.enumerate_actions(AR._observation(t, e, actor), actor, catalogue=catalogue)
            actions = [a for f in AS.ACTION_KINDS for a in AS.enumerated_actions(found, f)]
            hits = [a for a in actions if AS.action_key_hash(a) == step["true_key"]]
            if len(hits) != 1:
                raise TraceError(f"step {index}: {len(hits)} enumerated actions have the recorded key")
            action = {**hits[0], "actor": actor}
            given: list[dict] = []
            pending = list(step.get("receipts") or [])
            st = GL.run_action(t, e, catalogue, action)
            while not st["committed"] and (st["request"] or {}).get("code") == "randomization_receipt_required":
                if not pending:
                    raise TraceError(f"step {index}: the action asks for chance the record does not hold")
                given.append(pending.pop(0))
                st = GL.run_action(t, e, catalogue, action, receipts=given)
            if pending or not st["committed"]:
                raise TraceError(f"step {index}: the action does not commit with the recorded receipts")
            entry.update({"actor": actor, "action": describe_action(e, action),
                          "options": options_summary(e, found, actions, step["true_key"])})
        else:
            made = DS._answer()
            answers = []
            for answer in step.get("answers") or []:
                if "chance" in answer:
                    made = DS._plus(made, DS._answer(receipts=[answer["chance"]]))
                    answers.append({"chance": True, "operation": answer["chance"].get("operation")})
                    continue
                point = DS.decision_point(t, e, catalogue, made)
                hits = [o for o in point.get("options") or [] if AR.option_key(point, o) == answer["true_key"]]
                if point.get("decider") != answer.get("decider") or len(hits) != 1:
                    raise TraceError(f"step {index}: the recorded answer is not one option of the request")
                chosen = hits[0]["answer"]
                selected = []
                for d in chosen.get("decisions") or []:
                    value = d.get("value")
                    for oid in value if isinstance(value, list) else [value]:
                        if isinstance(oid, str) and oid in e["objects"]:
                            selected.append(_name(e, oid))
                answers.append({"decider": answer["decider"], "request": (point.get("request") or {}).get("code"),
                                "label": point.get("label"), "options": len(point.get("options") or []),
                                "selected_cards": selected, "visibility": "private:" + answer["decider"]})
                made = DS._plus(made, chosen)
            st = GL.run_procedure(t, e, catalogue, made["decisions"], made["settings"], made["receipts"])
            if not st["committed"]:
                raise TraceError(f"step {index}: the procedure does not commit with the recorded answers")
            entry.update({"label": step.get("label") or st.get("label"), "answers": answers})
        t1, e1 = st["next_timing_state"], st["next_effect_state"]
        entry["changes"] = changes(t, e, t1, e1)
        entry["after"] = hashes(t1, e1)
        t, e = t1, e1
        steps_out.append(entry)
    final = hashes(t, e)
    if record.get("final") and final != record["final"]:
        raise TraceError("the final state is not the record's")
    if players is None:
        players = {p: {"legend": (record.get("specs") or {}).get(p, {}).get("legend"),
                       "chosen_champion": (record.get("specs") or {}).get(p, {}).get("chosen_champion")} for p in PLAYERS}
    end = copy.deepcopy(record.get("end") or {})
    end.pop("rewards", None)
    trace = {"schema_version": TRACE_VERSION,
             "source": {"kind": "engine_replay", "record_schema": record.get("schema_version"),
                        "record_hash": record.get("record_hash"), "catalogue_hash": catalogue.get("catalogue_hash"),
                        "steps_replayed": len(steps_out), "hashes_verified": bool(record.get("final")),
                        "is_real_match": False},
             "ruleset": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF, "rule_numbering": IR.RULE_NUMBERING},
             "players": players,
             "battlefields": {bf: entry.get("card_ref") for bf, entry in sorted((start_effect.get("battlefields") or {}).items())},
             "start": hashes(start_timing, start_effect), "steps": steps_out, "final": final,
             "final_view": view(t, e), "end": end}
    trace["trace_hash"] = IR.hash_value({k: v for k, v in trace.items() if k != "trace_hash"})
    return trace
