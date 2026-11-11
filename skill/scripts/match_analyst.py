#!/usr/bin/env python3
"""Match Analyst: one normalized timeline from a match log or an engine trace, and two projections over it.

    analyze(source, perspective=None) -> match-analysis.v1
    review(analysis) -> match-review.v1
    commentary(analysis, audience="player", length="standard") -> match-commentary.v1
    agreement_problems(analysis, review, commentary) -> [str]

Sources:
  riftbound-match-log-fixture.v1   a hand or spectator record (skill/data/match_analyst_fixtures)
  riftbound-engine-trace.v1        a recorded game replayed through the engine (match_trace.py)

The pipeline follows docs/match-analyst/MATCH_ANALYST_PRODUCT_SPEC.md:

  normalize      every source event becomes one or more timeline events with a stable id (ev-NNNN), in source order,
                 each naming the source event(s) it came from. A private event that has a public side (a card hidden
                 face down, a card drawn) also yields a public shadow event, so a perspective that cannot see the card
                 still sees that something happened - without the private event's id or content.
  perspective    events the perspective cannot read are left out of the artifact entirely; only their ids and the
                 reason are listed (information_boundary.withheld).
  contradictions re-derived from the events (an object acting after it was killed in the same turn; two adjacent
                 assertions about the same moment naming different Priority or Focus holders). Contested events are
                 never narrated or graded as confirmed.
  engine         an engine trace is bound step by step to the replay's state hashes. A hand record has no executable
                 state, so each discretionary action in it gets an engine-check.v1 timing check on the timing state the
                 record describes, with the assumptions that state needed.
  ledger         observed / inferred / unknown / hindsight_only facts.
  decisions      a hand record's declared decision points; in an engine trace, every action point where the actor had
                 two or more choices other than tapping a rune for resources (an [Add] ability).
  turning points scoring, Battlefield control, kills and reveals, ranked by how much they moved the public position.
  review         one item per decision, graded only on events at or before it; never strategic_misplay, because this
                 system has no strategy evaluator.
  commentary     narration segments at four levels, each linked to event ids and carrying one certainty label.
"""
from __future__ import annotations

import copy
from typing import Any

import effect_ir as IR
import engine_check as EC
import rules_core as RC

ANALYSIS_VERSION = "match-analysis.v1"
REVIEW_VERSION = "match-review.v1"
COMMENTARY_VERSION = "match-commentary.v1"
MODULE = {"name": "match_analyst", "version": "1.0.0"}
LOG_VERSION = "riftbound-match-log-fixture.v1"
TRACE_VERSION = "riftbound-engine-trace.v1"

PERSPECTIVES = ("player1", "player2", "public_observer", "omniscient_replay")
SEAT = {"player1": "p1", "player2": "p2"}
PLAYERS = ("p1", "p2")
CLASSIFICATIONS = ("rules_execution_error", "missed_response_window", "strategic_misplay", "reasonable_alternative",
                   "outcome_bias", "insufficient_information", "unsupported_engine_behavior")
FACT_LABELS = ("observed", "inferred", "unknown", "hindsight_only")
CLAIM_LABELS = ("confirmed", "inferred", "unknown", "hindsight_only")
LEVELS = ("event", "sequence", "turning_point", "match_summary")
LENGTHS = ("short", "standard", "full")
AUDIENCES = ("player", "spectator", "reader")

HIGH = {"play_card", "move_unit", "hide_card", "scored", "control_changed", "showdown_opened", "died", "game_over",
        "revealed", "object_killed", "chain_resolved", "resolve_chain_item", "reveal_hidden", "attack",
        "unrecorded_response", "banished", "hidden_action", "state_assertion"}
LOW = {"drew", "channeled", "recycled", "returned_to_deck", "zone_change", "ceased_to_exist", "milled"}
PASSES = {"pass_priority", "pass_focus", "end_main_phase"}
TRACE_ACTION_KIND = {"standard_move": "move_unit", "hide": "hide_card"}


def _hash(value: Any) -> str:
    return IR.hash_value(value)


def _short(name: str | None) -> str:
    return (name or "").split(" - ")[0].split(",")[0].strip() or "?"


# --------------------------------------------------------------------------------------------- normalization

def _visible(visibility: str, perspective: str) -> bool:
    if perspective == "omniscient_replay" or visibility in ("public", "revealed_later"):
        return True
    if visibility.startswith("private:"):
        return SEAT.get(perspective) in visibility.split(":", 1)[1].split(",")
    return False


def _salience(kind: str, data: dict) -> str:
    if kind == "activate_ability":
        return "low" if data.get("ability_kind") == "add" else "high"
    if kind in HIGH:
        return "high"
    if kind in LOW:
        return "low"
    return "normal"


def _event(seq: int, source_ids: list[str], kind: str, data: dict, *, ctx: dict, actor: str | None,
           visibility: str = "public", certainty: str = "confirmed", **extra) -> dict[str, Any]:
    ev = {"event_id": f"ev-{seq:04d}", "seq": seq, "source_event_ids": source_ids, "kind": kind, "actor": actor,
          "data": data, "visibility": visibility, "certainty": certainty, "salience": _salience(kind, data), **ctx}
    ev.update({k: v for k, v in extra.items() if v is not None})
    return ev


def normalize_log(log: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in log.get("events") or []:
        action = dict(source.get("action") or {})
        kind = action.pop("kind", "unknown")
        ctx = {k: copy.deepcopy(source.get(k)) for k in ("turn", "phase", "state_label", "priority", "focus",
                                                          "outstanding_tasks", "chain")}
        sid = source["event_id"]
        out.append(_event(len(out) + 1, [sid], kind, action, ctx=ctx, actor=source.get("actor"),
                          visibility=source.get("visibility", "public"), certainty=source.get("certainty", "confirmed"),
                          gap=source.get("gap"), recorder=source.get("recorder")))
        shadow = source.get("public_shadow")
        if shadow and not out[-1]["visibility"] == "public":
            out.append(_event(len(out) + 1, [f"{sid}#public_shadow"], "hidden_action",
                              {"original_kind": kind, "description": shadow.get("description")}, ctx=ctx,
                              actor=source.get("actor"), visibility=shadow.get("visibility", "public"),
                              shadow_of=out[-1]["event_id"]))
    return out


def _trace_ctx(view: dict) -> dict[str, Any]:
    return {"turn": view.get("turn"), "turn_player": view.get("turn_player"), "phase": view.get("phase"),
            "state_label": view.get("state_label"), "priority": view.get("priority"), "focus": view.get("focus"),
            "outstanding_tasks": [], "chain": [c.get("card") or c.get("object_kind") for c in view.get("chain") or []],
            "points": dict(view.get("points") or {})}


def _shadow_of_change(change: dict) -> dict:
    return {k: v for k, v in change.items() if k not in ("card", "object", "visibility")}


def normalize_trace(trace: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in trace.get("steps") or []:
        k = step["k"]
        ctx = _trace_ctx(step.get("view") or {})
        engine = {"mode": "replayed", "step": k, "before": step.get("before"), "after": step.get("after")}
        if step.get("kind") == "action":
            desc = dict(step.get("action") or {})
            kind = TRACE_ACTION_KIND.get(desc.get("kind"), desc.get("kind"))
            desc.pop("kind", None)
            visibility = "private:" + step["actor"] if kind == "hide_card" else "public"
            out.append(_event(len(out) + 1, [f"step:{k}"], kind, desc, ctx=ctx, actor=step["actor"],
                              visibility=visibility, engine=engine, options=step.get("options")))
            if kind == "hide_card":
                out.append(_event(len(out) + 1, [f"step:{k}#public_shadow"], "hidden_action",
                                  {"original_kind": kind, "description": "hid a card face down",
                                   "battlefield": desc.get("battlefield")}, ctx=ctx, actor=step["actor"],
                                  engine=engine, shadow_of=out[-1]["event_id"]))
        for i, answer in enumerate(step.get("answers") or []):
            if answer.get("chance"):
                continue
            data = {"request": answer.get("request"), "label": answer.get("label"), "options": answer.get("options"),
                    "selected_cards": answer.get("selected_cards")}
            out.append(_event(len(out) + 1, [f"step:{k}/answer:{i}"], "decision", data, ctx=ctx,
                              actor=answer.get("decider"), visibility=answer.get("visibility", "public"), engine=engine))
            out.append(_event(len(out) + 1, [f"step:{k}/answer:{i}#public_shadow"], "decision",
                              {"request": answer.get("request"), "label": answer.get("label"),
                               "selected_count": len(answer.get("selected_cards") or [])}, ctx=ctx,
                              actor=answer.get("decider"), engine=engine, shadow_of=out[-1]["event_id"]))
        for i, change in enumerate(step.get("changes") or []):
            data = {k2: v for k2, v in change.items() if k2 not in ("kind", "visibility")}
            actor = change.get("owner") or change.get("player")
            vis = change.get("visibility", "public")
            if change["kind"] == "turn_began":
                ctx = {**ctx, "turn": change.get("turn"), "turn_player": change.get("player")}
            out.append(_event(len(out) + 1, [f"step:{k}/change:{i}"], change["kind"], data, ctx=ctx, actor=actor,
                              visibility=vis, engine=engine))
            if vis != "public":
                out.append(_event(len(out) + 1, [f"step:{k}/change:{i}#public_shadow"], change["kind"],
                                  _shadow_of_change(change), ctx=ctx, actor=actor, engine=engine,
                                  shadow_of=out[-1]["event_id"]))
    return out


# --------------------------------------------------------------------------------------------- contradictions

def derive_contradictions(events: list[dict]) -> list[dict[str, Any]]:
    found: list[tuple[str, str, str, str | None]] = []
    killed: dict[str, dict] = {}
    for ev in events:
        if ev["kind"] == "object_killed" and ev["data"].get("object"):
            killed[ev["data"]["object"]] = ev
    for ev in events:
        obj = ev["data"].get("unit") or ev["data"].get("object")
        if not obj or obj not in killed or ev is killed[obj]:
            continue
        k = killed[obj]
        if ev.get("turn") == k.get("turn") and ev["seq"] > k["seq"]:
            found.append((k["event_id"], ev["event_id"], "object_liveness", obj))
    for a, b in zip(events, events[1:]):
        if "state_assertion" not in {a["kind"], b["kind"]}:
            continue
        if (a.get("turn"), a.get("phase"), a.get("state_label")) != (b.get("turn"), b.get("phase"), b.get("state_label")):
            continue
        for field in ("priority", "focus"):
            if a.get(field) is not None and b.get(field) is not None and a[field] != b[field]:
                found.append((a["event_id"], b["event_id"], field, None))
    out = []
    for n, (x, y, field, obj) in enumerate(sorted(set(found)), 1):
        entry = {"contradiction_id": f"c{n}", "events": [x, y], "field": field}
        if obj:
            entry["object"] = obj
        out.append(entry)
    return out


# --------------------------------------------------------------------------------------------- engine binding

LOG_TIMING = {"play_card": "play_card", "reveal_hidden": "play_card", "move_unit": "standard_move",
              "pass_priority": "pass_priority", "pass_focus": "pass_focus", "end_main_phase": "end_main_phase"}


def _turn_players(events: list[dict]) -> dict[Any, tuple[str, str]]:
    """Each turn's Turn Player, inferred: the first actor to take a neutral-state action that turn."""
    out: dict[Any, tuple[str, str]] = {}
    for ev in events:
        if ev.get("turn") in out or ev.get("actor") not in PLAYERS:
            continue
        if str(ev.get("state_label", "")).startswith("neutral") and ev["kind"] in ("play_card", "move_unit", "hide_card"):
            out[ev["turn"]] = (ev["actor"], ev["event_id"])
    return out


def timing_check(ev: dict, events: list[dict], turn_players: dict) -> dict[str, Any]:
    """An engine-check.v1 timing check of one recorded discretionary action, or why there is none."""
    missing = [f for f in ("state_label", "phase", "chain", "outstanding_tasks") if ev.get(f) is None]
    if ev.get("state_label") and ev["state_label"].startswith("showdown") and ev.get("focus") is None:
        missing.append("focus")
    if ev["kind"] != "pass_focus" and ev.get("priority") is None and ev["kind"] != "move_unit":
        missing.append("priority")
    if ev.get("turn") not in turn_players:
        missing.append("turn_player")
    if missing:
        return {"status": "not_reconstructable", "missing_information": sorted(set(missing))}
    assumptions = [f"Turn {ev['turn']}'s Turn Player is {turn_players[ev['turn']][0]}, inferred from "
                   f"{turn_players[ev['turn']][1]} (the first neutral-state action of the turn)"]
    phase = ev["phase"]
    if phase not in RC.PHASES:
        assumptions.append(f"the record's phase {phase!r} is read as the Main Phase: a Showdown or Combat happens in it")
        phase = "main"
    showdown = ev["state_label"].startswith("showdown")
    items = []
    for i, name in enumerate(ev["chain"] or []):
        origin = next((p for p in reversed(events[:ev["seq"] - 1]) if p["kind"] in ("play_card", "reveal_hidden")
                       and p["data"].get("card") == name), None)
        controller = origin["actor"] if origin else ("p2" if ev.get("actor") == "p1" else "p1")
        timing = (origin["data"].get("timing") if origin else None) or "action"
        if not origin:
            assumptions.append(f"Chain item {name!r} is taken to be the other player's, at Action timing")
        items.append({"id": f"chain-{i + 1}", "controller": controller, "object_kind": "spell",
                      "timing": "reaction" if timing == "reaction" else ("action" if timing == "action" else "default"),
                      "status": "finalized", "ability_kind": None})
    priority = ev.get("priority")
    if ev["kind"] == "move_unit" and priority is None:
        priority = turn_players[ev["turn"]][0]
    state = {"schema_version": RC.SCHEMA_VERSION, "ruleset": {"core": RC.CORE_RULESET, "faq_as_of": RC.FAQ_AS_OF},
             "players": list(PLAYERS), "turn_order": list(PLAYERS), "turn_player": turn_players[ev["turn"]][0],
             "phase": phase,
             "showdown": {"active": True, "kind": "non_combat", "focus": ev["focus"], "battlefield": None, "focus_passes": []}
             if showdown else {"active": False, "kind": None, "focus": None},
             "priority": priority, "outstanding_tasks": list(ev["outstanding_tasks"]),
             "chain": {"initiated_by": "played_card" if items else None, "items": items, "consecutive_passes": []},
             "turns_taken": {p: 0 for p in PLAYERS}}
    if showdown:
        state["showdown"].pop("battlefield")
        assumptions.append("the Showdown is taken as Non-Combat; the four-state label does not depend on its kind")
    action = {"kind": LOG_TIMING[ev["kind"]], "actor": ev["actor"],
              "timing": "reaction" if ev["kind"] == "reveal_hidden" else (ev["data"].get("timing") or "default")}
    if action["timing"] not in RC.TIMINGS:
        action["timing"] = "default"
    result = RC.validate_timing(state, action)
    check = EC.build_engine_check("timing", result, input_hashes={"timing_state": RC.state_hash(state)},
                                  assumptions=assumptions)
    return {"status": "checked", "check": check, "legal": result.get("legal"),
            "explanation": result.get("explanation"), "reason_code": result.get("reason_code")}


# --------------------------------------------------------------------------------------------- narration text

def _p(player: str | None) -> tuple[str, str]:
    if player in PLAYERS:
        return player.upper(), player.upper()
    return "某位玩家", "a player"


def _q(name: Any) -> str:
    return f"「{name}」" if name else "一張牌"


def _dest(name: Any) -> tuple[str, str]:
    if name in (None, "base"):
        return "基地", "base"
    return f"「{name}」", str(name)


def say(ev: dict) -> tuple[str, str]:
    """One confirmed event in plain words (zh-Hant, en)."""
    k, d = ev["kind"], ev["data"]
    pz, pe = _p(ev.get("actor"))
    card = d.get("card")
    if k == "play_card":
        zh, en = f"{pz} 打出{_q(card)}", f"{pe} plays {card or 'a card'}"
        if d.get("destination") and d.get("destination") != "base":
            dz, de = _dest(d["destination"])
            zh, en = zh + f"到{dz}", en + f" to {de}"
        if d.get("target"):
            zh, en = zh + f"，目標是{_q(d['target'])}", en + f", targeting {d['target']}"
        return zh, en
    if k == "activate_ability":
        if d.get("ability_kind") == "add":
            return f"{pz} 用{_q(card)}產生資源", f"{pe} taps {card} for resources"
        return f"{pz} 啟動{_q(card)}的能力", f"{pe} activates {card}'s ability"
    if k == "move_unit":
        units = d.get("units") or ([d["unit"]] if d.get("unit") else [])
        dz, de = _dest(d.get("destination"))
        names_z = "、".join(_q(u) for u in units) or "單位"
        names_e = ", ".join(str(u) for u in units if u) or "a unit"
        zh, en = f"{pz} 把{names_z}移動到{dz}", f"{pe} moves {names_e} to {de}"
        if d.get("initiates") == "showdown":
            zh, en = zh + "，展開對決", en + ", opening a Showdown"
        return zh, en
    if k == "hide_card":
        return f"{pz} 把{_q(card)}蓋在戰場上", f"{pe} hides {card or 'a card'} face down"
    if k == "hidden_action":
        if d.get("original_kind") == "hide_card":
            return f"{pz} 蓋下一張牌（身分未公開）", f"{pe} hides a card face down (identity not public)"
        return f"{pz} 有一個未公開內容的動作", f"{pe} takes an action whose content is not public"
    if k == "pass_priority":
        return f"{pz} 讓過優先權", f"{pe} passes Priority"
    if k == "pass_focus":
        return f"{pz} 讓過焦點", f"{pe} passes Focus"
    if k == "end_main_phase":
        return f"{pz} 結束主要階段", f"{pe} ends their Main Phase"
    if k == "focus_passed":
        return f"焦點從 {d.get('from', '?').upper()} 移到 {d.get('to', '?').upper()}", \
            f"Focus passes from {d.get('from', '?').upper()} to {d.get('to', '?').upper()}"
    if k == "resolve_chain_item":
        return f"{_q(d.get('item'))}結算：{d.get('result', '')}", f"{d.get('item')} resolves: {d.get('result', '')}"
    if k == "chain_resolved":
        return f"連鎖結算完畢：{d.get('result', '')}", f"The Chain resolves: {d.get('result', '')}"
    if k == "object_killed":
        return f"{_q(d.get('object'))}被擊殺（{d.get('reason', '')}）", f"{d.get('object')} is killed ({d.get('reason', '')})"
    if k == "reveal_hidden":
        return f"{pz} 翻開蓋牌{_q(card)}作為反應", f"{pe} reveals the hidden {card} as a Reaction"
    if k == "attack":
        return f"{pz} 以{_q(d.get('unit'))}在{_q(d.get('battlefield'))}攻擊", f"{pe} attacks with {d.get('unit')} at {d.get('battlefield')}"
    if k == "state_assertion":
        return f"紀錄聲稱：{d.get('detail', '')}", f"The record asserts: {d.get('detail', '')}"
    if k == "unrecorded_response":
        return f"{pz} 做了某個動作，但紀錄沒有寫是什麼", f"{pe} did something the record does not describe"
    if k == "hand_snapshot":
        hz, he = _p(d.get("player"))
        return f"{hz} 的手牌：{'、'.join(_q(c) for c in d.get('cards') or [])}", f"{he}'s hand: {', '.join(d.get('cards') or [])}"
    if k == "scored":
        return f"{_p(d.get('player'))[0]} 得 {d.get('delta')} 分（{d.get('from')}→{d.get('to')}）", \
            f"{_p(d.get('player'))[1]} scores {d.get('delta')} ({d.get('from')}→{d.get('to')})"
    if k == "control_changed":
        if d.get("to") in PLAYERS:
            return f"{d['to'].upper()} 取得{_q(d.get('battlefield_card'))}的控制權", \
                f"{d['to'].upper()} takes control of {d.get('battlefield_card')}"
        return f"{_q(d.get('battlefield_card'))}不再有人控制", f"{d.get('battlefield_card')} is no longer controlled"
    if k == "showdown_opened":
        return f"在{_q(d.get('battlefield_card'))}展開對決", f"A Showdown opens at {d.get('battlefield_card')}"
    if k == "showdown_closed":
        return f"{_q(d.get('battlefield_card'))}的對決結束", f"The Showdown at {d.get('battlefield_card')} ends"
    if k == "turn_began":
        tz, te = _p(d.get("player"))
        return f"第 {d.get('turn')} 回合，輪到 {tz}", f"Turn {d.get('turn')}: {te}'s turn"
    if k == "entered":
        dz, de = _dest(((d.get("to") or {}).get("battlefield_card")) or "base")
        return f"{_q(card)}進入{dz}", f"{card} enters the {de}" if de == "base" else f"{card} enters {de}"
    if k == "resolved":
        return f"{_q(card)}結算完畢", f"{card} resolves"
    if k == "created":
        return f"{pz} 產生一個{_q(card)}", f"{pe} creates a {card}"
    if k == "died":
        return f"{_q(card)}陣亡", f"{card} dies"
    if k == "moved":
        dz, de = _dest(((d.get("to") or {}).get("battlefield_card")) or "base")
        return f"{_q(card) if card else pz + ' 的單位'}移動到{dz}", f"{card or pe + chr(39) + 's unit'} moves to {de}"
    if k == "drew":
        return (f"{pz} 抽到{_q(card)}", f"{pe} draws {card}") if card else (f"{pz} 抽一張牌", f"{pe} draws a card")
    if k == "channeled":
        return f"{pz} 導入一張符文", f"{pe} channels a rune"
    if k == "recycled":
        return f"{pz} 把一張符文放回符文牌庫", f"{pe} recycles a rune"
    if k == "returned_to_deck":
        return (f"{pz} 把{_q(card)}放回牌庫", f"{pe} puts {card} back into the deck") if card else \
            (f"{pz} 把一張牌放回牌庫", f"{pe} puts a card back into the deck")
    if k == "decision":
        if d.get("request") == "card_selection_required" and str(d.get("label", "")).startswith("setup:mulligan"):
            n = len(d["selected_cards"]) if "selected_cards" in d else d.get("selected_count", 0)
            cards = "、".join(_q(c) for c in d.get("selected_cards") or [])
            return (f"{pz} 調度：放回 {n} 張" + (f"（{cards}）" if cards else ""),
                    f"{pe} mulligans {n} card(s)" + (f" ({', '.join(d.get('selected_cards') or [])})" if d.get('selected_cards') else ""))
        return f"{pz} 做出選擇（{d.get('label')}）", f"{pe} makes a choice ({d.get('label')})"
    if k == "damaged":
        return f"{_q(card)}受到 {d.get('amount')} 點傷害", f"{card} takes {d.get('amount')} damage"
    if k == "game_over":
        fp = d.get("final_points") or {}
        wz, we = _p(d.get("winner"))
        win = d.get("winner")
        lose = next((p for p in PLAYERS if p != win), None)
        score = f"{fp.get(win, '?')}：{fp.get(lose, '?')}"
        return f"比賽結束：{wz} 以 {score} 獲勝", f"Game over: {we} wins {score.replace('：', '-')}"
    if k == "banished":
        return f"{_q(card)}被放逐", f"{card} is banished"
    if k == "discarded":
        return f"{pz} 棄掉{_q(card)}", f"{pe} discards {card or 'a card'}"
    return f"{k}", f"{k}"


def say_option(item: dict) -> tuple[str, str]:
    kind = item.get("kind")
    ev = {"kind": TRACE_ACTION_KIND.get(kind, kind), "data": item, "actor": None}
    zh, en = say(ev)
    return zh.replace("某位玩家 ", ""), en.replace("a player ", "")


# --------------------------------------------------------------------------------------------- analysis

def _source_meta(source: dict) -> dict[str, Any]:
    if source.get("schema_version") == LOG_VERSION:
        prov = source.get("provenance") or {}
        return {"kind": "match_log", "format": source["schema_version"], "log_format": prov.get("log_format"),
                "completeness": prov.get("completeness"), "provenance": copy.deepcopy(prov),
                "fixture_id": source.get("fixture_id"), "title": source.get("title"), "input_hash": _hash(source)}
    src = source.get("source") or {}
    return {"kind": "engine_trace", "format": source["schema_version"], "log_format": "engine replay",
            "completeness": "complete" if (source.get("end") or {}).get("outcome") == "game_over" else "partial",
            "provenance": {"log_source": src.get("kind"), "record_schema": src.get("record_schema"),
                           "record_hash": src.get("record_hash"), "catalogue_hash": src.get("catalogue_hash"),
                           "is_real_match": bool(src.get("is_real_match"))},
            "input_hash": source.get("trace_hash") or _hash(source)}


def _facts(events: list[dict], contested: set[str], log: dict | None, decisions: list[dict],
           turn_players: dict) -> list[dict[str, Any]]:
    facts = []
    for ev in events:
        zh, en = say(ev)
        if ev["event_id"] in contested:
            label, why = "unknown", "contradicted by another event"
        elif ev["certainty"] == "unknown":
            label, why = "unknown", "the record does not establish it"
        elif ev["certainty"] in FACT_LABELS:
            label, why = ev["certainty"], None
        else:
            label, why = ("inferred", None) if ev["certainty"] == "inferred" else ("observed", None)
        fact = {"fact_id": f"f-{ev['event_id']}", "event_id": ev["event_id"], "label": label, "statement": en,
                "statement_zh": zh}
        if why:
            fact["why"] = why
        facts.append(fact)
        if ev.get("gap"):
            facts.append({"fact_id": f"f-{ev['event_id']}-gap", "event_id": ev["event_id"], "label": "unknown",
                          "statement": f"Not recorded: {ev['gap']}", "statement_zh": f"紀錄缺漏：{ev['gap']}"})
        if ev["visibility"] == "revealed_later":
            before = [d["decision_id"] for d in decisions if d["seq"] < ev["seq"]]
            if before:
                facts.append({"fact_id": f"f-{ev['event_id']}-hindsight", "event_id": ev["event_id"],
                              "label": "hindsight_only", "relative_to": before,
                              "statement": f"Revealed at {ev['event_id']}; unavailable at the time of {', '.join(before)}",
                              "statement_zh": f"在 {ev['event_id']} 才公開；{', '.join(before)} 當下無法得知"})
    for turn, (player, eid) in sorted(turn_players.items(), key=lambda x: str(x[0])):
        if log is not None:
            facts.append({"fact_id": f"f-turn-{turn}", "event_id": eid, "label": "inferred",
                          "statement": f"Turn {turn}'s Turn Player is {player} (the first neutral-state action)",
                          "statement_zh": f"第 {turn} 回合的回合玩家推定為 {player.upper()}（該回合第一個中立狀態動作）"})
    for n, entry in enumerate((log or {}).get("uncertainty_ledger") or [], 1):
        facts.append({"fact_id": f"f-record-{n}", "event_id": None, "about_source": entry.get("about"),
                      "label": "hindsight_only" if entry.get("kind") == "hindsight_only" else "unknown",
                      "statement": entry.get("detail"), "statement_zh": None, "record_kind": entry.get("kind")})
    return facts


def _trace_decisions(events: list[dict], seats: set[str]) -> list[dict[str, Any]]:
    out = []
    for ev in events:
        opts = ev.get("options")
        if not opts or ev.get("actor") not in seats:
            continue
        substantive = [o for o in opts["items"] if not o.get("add_ability")]
        if ev["kind"] == "activate_ability" and ev["data"].get("ability_kind") == "add":
            continue
        if len(substantive) < 2:
            continue
        zh, en = say(ev)
        out.append({"decision_id": f"d-{ev['source_event_ids'][0].split(':')[1]}", "at_event": ev["event_id"],
                    "seq": ev["seq"], "actor": ev["actor"], "turn": ev.get("turn"),
                    "question": f"{ev['actor'].upper()}'s choice at an action point ({ev.get('state_label')})",
                    "recorded_choice": en, "recorded_choice_zh": zh,
                    "alternatives": {"source": "engine_enumeration", "complete_action_set": False,
                                     "items": [{**{k: v for k, v in o.items() if k in ("kind", "card", "units", "destination", "timing", "ability_kind", "chosen")},
                                                "text": say_option(o)[1], "text_zh": say_option(o)[0]} for o in substantive],
                                     "add_abilities": len(opts["items"]) - len(substantive),
                                     "abstained": opts.get("abstained") or []},
                    "window": {"state_label": ev.get("state_label"), "chain": ev.get("chain"), "phase": ev.get("phase")}})
    return out


def _log_decisions(log: dict, events: list[dict], by_source: dict[str, list[str]], seq_of: dict[str, int]) -> list[dict]:
    out = []
    for d in log.get("decision_points") or []:
        eid = by_source.get(d.get("at_event"), [None])[0]
        out.append({"decision_id": d["decision_id"], "at_event": eid, "source_event": d.get("at_event"),
                    "seq": seq_of.get(eid, 0), "actor": d.get("actor"),
                    "turn": next((e.get("turn") for e in events if e["event_id"] == eid), None),
                    "question": d.get("question"), "recorded_choice": d.get("recorded_choice"),
                    "information_available": list(d.get("information_available") or []),
                    "information_withheld": list(d.get("information_withheld") or []),
                    "unknown_at_decision_time": list(d.get("unknown_at_decision_time") or []),
                    "alternatives": {"source": "record", "complete_action_set": False, "items": []}})
    return out


def _turning_points(events: list[dict], contested: set[str]) -> list[dict[str, Any]]:
    cands = []
    lead = 0
    points = {p: 0 for p in PLAYERS}
    first_score = True
    for ev in events:
        if ev["event_id"] in contested or ev["certainty"] != "confirmed":
            continue
        k, d = ev["kind"], ev["data"]
        swing, why_zh, why_en = 0, "", ""
        if k == "scored":
            points[d["player"]] = d.get("to", points[d["player"]])
            new_lead = points["p1"] - points["p2"]
            swing = 3 * abs(d.get("delta") or 0)
            if first_score:
                swing += 3
                why_zh, why_en = "本局第一次得分", "the first points of the game"
                first_score = False
            elif (lead > 0) != (new_lead > 0) and new_lead != 0:
                swing += 3
                why_zh, why_en = "領先易手", "the lead changes hands"
            else:
                why_zh, why_en = f"比分差距變成 {abs(new_lead)} 分", f"the margin becomes {abs(new_lead)}"
            lead = new_lead
        elif k == "control_changed":
            swing = 4
            why_zh, why_en = "控制戰場後，之後的回合可以從這裡得分（Core 規則：守住戰場得分）", \
                "controlling a Battlefield lets its controller score from it on later turns"
        elif k in ("died", "object_killed"):
            swing = 2
            why_zh, why_en = "場上少了一個單位", "a unit leaves the board"
        elif k in ("reveal_hidden", "chain_resolved", "resolve_chain_item"):
            swing = 2
            why_zh, why_en = "這一步決定了對決的結果", "this decided how the Showdown went"
        elif k == "game_over":
            swing = 10
            why_zh, why_en = "比賽在此結束", "the game ends here"
        if swing:
            cands.append((swing, ev, why_zh, why_en))
    top = sorted(cands, key=lambda c: (-c[0], c[1]["seq"]))[:6]
    out = []
    for n, (swing, ev, why_zh, why_en) in enumerate(sorted(top, key=lambda c: c[1]["seq"]), 1):
        zh, en = say(ev)
        out.append({"turning_point_id": f"t{n}", "at_event": ev["event_id"], "turn": ev.get("turn"), "kind": ev["kind"],
                    "swing": swing, "summary": f"{en} - {why_en}", "summary_zh": f"{zh}：{why_zh}"})
    return out


def analyze(source: dict, perspective: str | None = None) -> dict[str, Any]:
    version = source.get("schema_version")
    if version == LOG_VERSION:
        events = normalize_log(source)
        perspective = perspective or source.get("perspective") or "public_observer"
        players = copy.deepcopy(source.get("players") or {})
        ruleset = copy.deepcopy(source.get("ruleset") or {})
    elif version == TRACE_VERSION:
        events = normalize_trace(source)
        perspective = perspective or "omniscient_replay"
        players = copy.deepcopy(source.get("players") or {})
        ruleset = copy.deepcopy(source.get("ruleset") or {})
    else:
        raise ValueError(f"unknown source schema {version!r}")
    if perspective not in PERSPECTIVES:
        raise ValueError(f"unknown perspective {perspective!r}")
    log = source if version == LOG_VERSION else None

    contradictions = derive_contradictions(events)
    contested = {eid for c in contradictions for eid in c["events"]}
    for ev in events:
        if ev["event_id"] in contested:
            ev["contested_by"] = [c["contradiction_id"] for c in contradictions if ev["event_id"] in c["events"]]

    withheld = [{"event_id": ev["event_id"], "source_event_ids": ev["source_event_ids"], "reason": ev["visibility"]}
                for ev in events if not _visible(ev["visibility"], perspective)]
    hidden_ids = {w["event_id"] for w in withheld}
    usable = [ev for ev in events if ev["event_id"] not in hidden_ids]
    if perspective != "omniscient_replay":
        for ev in usable:
            if ev.get("options") and ev.get("actor") != SEAT.get(perspective):
                ev.pop("options")
    seq_of = {ev["event_id"]: ev["seq"] for ev in events}
    by_source: dict[str, list[str]] = {}
    for ev in events:
        for sid in ev["source_event_ids"]:
            by_source.setdefault(sid, []).append(ev["event_id"])

    checks = []
    turn_players = _turn_players(usable) if log is not None else {}
    if log is not None:
        reconstruction = {"mode": "timing_checks", "status": "partial",
                          "detail": "a hand record carries no executable game state; each discretionary action is checked "
                                    "for timing on the timing state the record describes (engine-check.v1)"}
        for ev in usable:
            if ev["kind"] not in LOG_TIMING:
                ev["engine"] = {"mode": "none", "reason": "not a discretionary action the timing kernel checks"}
                continue
            if ev["event_id"] in contested:
                ev["engine"] = {"mode": "none", "reason": "contested by a contradiction"}
                continue
            bound = timing_check(ev, usable, turn_players)
            if bound["status"] != "checked":
                ev["engine"] = {"mode": "timing_check", "status": "not_reconstructable",
                                "missing_information": bound["missing_information"]}
                continue
            check = bound["check"]
            checks.append({"event_id": ev["event_id"], **check})
            ev["engine"] = {"mode": "timing_check", "status": "checked", "check_id": check["check_id"],
                            "outcome": check["outcome"], "legal": bound["legal"], "reason_code": bound["reason_code"],
                            "explanation": bound["explanation"], "rule_locators": check["rule_locators"]}
    else:
        src = source.get("source") or {}
        reconstruction = {"mode": "engine_replay", "status": "replayed", "steps_replayed": src.get("steps_replayed"),
                          "hashes_verified": bool(src.get("hashes_verified")), "start": source.get("start"),
                          "final": source.get("final"),
                          "detail": "every step re-executed by the engine; each state hash matched the record"}

    seats = {SEAT[perspective]} if perspective in SEAT else set(PLAYERS)
    if log is not None:
        decisions = [d for d in _log_decisions(log, usable, by_source, seq_of) if d["at_event"] is not None]
    else:
        decisions = _trace_decisions(usable, seats)
    facts = _facts(usable, contested, log, decisions, turn_players)
    turning = _turning_points(usable, contested)
    coverage = {"complete_game": False, "complete_legality": False, "strategy_evaluator": "none",
                "engine_scope": "timing kernel (R1) on recorded states" if log is not None else
                "full engine replay of the recorded closed-environment game",
                "abstained_families": sorted({a["family"] for d in decisions for a in d["alternatives"].get("abstained") or []})}
    timeline = [{k: v for k, v in ev.items() if k != "options"} for ev in usable]
    analysis = {
        "schema_version": ANALYSIS_VERSION,
        "generated_by": dict(MODULE),
        "source": _source_meta(source),
        "ruleset": ruleset,
        "perspective": perspective,
        "players": players,
        "information_boundary": {
            "perspective": perspective, "withheld": withheld,
            "rules": ["events the perspective cannot read are not in this artifact; only their ids and reasons are",
                      "a decision is graded only on events at or before it; later reveals are hindsight_only for it",
                      "a contested event is never narrated or graded as confirmed"]},
        "timeline": timeline,
        "timeline_hash": _hash(timeline),
        "source_map": {sid: ids for sid, ids in by_source.items() if all(i not in hidden_ids for i in ids)},
        "reconstruction": reconstruction,
        "engine_checks": checks,
        "ledger": facts,
        "contradictions": contradictions,
        "decision_points": decisions,
        "turning_points": turning,
        "coverage": coverage,
        "assumptions": sorted({a for c in checks for a in c.get("assumptions", [])}),
        "uncertainty": [{"about": e.get("about"), "kind": e.get("kind"), "detail": e.get("detail")}
                        for e in (log or {}).get("uncertainty_ledger") or []],
        "end": copy.deepcopy(source.get("end")) if log is None else None,
    }
    analysis["confirmed_digest"] = _hash(sorted(confirmed_events(analysis)))
    analysis["analysis_id"] = "match-analysis:" + _hash({k: v for k, v in analysis.items()})[7:31]
    analysis["projections"] = {}
    return analysis


def confirmed_events(analysis: dict) -> set[str]:
    contested = {e for c in analysis["contradictions"] for e in c["events"]}
    return {ev["event_id"] for ev in analysis["timeline"]
            if ev["certainty"] == "confirmed" and ev["event_id"] not in contested}


def _ref(analysis: dict) -> dict[str, str]:
    return {"analysis_id": analysis["analysis_id"], "timeline_hash": analysis["timeline_hash"],
            "confirmed_digest": analysis["confirmed_digest"]}


# --------------------------------------------------------------------------------------------- review

FEEDBACK = {"rules_execution_error": "rules_core", "unsupported_engine_behavior": "rules_core",
            "missed_response_window": "player2_policy", "strategic_misplay": "deck_coach",
            "reasonable_alternative": None, "outcome_bias": None, "insufficient_information": None}
NO_EVALUATOR_ZH = "本系統沒有策略評估器，不判定這一步好不好。"
NO_EVALUATOR_EN = "This system has no strategy evaluator, so it does not grade this choice as good or bad."


def _review_item(analysis: dict, d: dict) -> dict[str, Any]:
    by_id = {ev["event_id"]: ev for ev in analysis["timeline"]}
    ev = by_id.get(d["at_event"]) or {}
    contested = {e for c in analysis["contradictions"] for e in c["events"]}
    later_reveals = [e["event_id"] for e in analysis["timeline"]
                     if e["seq"] > d["seq"] and (e["visibility"] == "revealed_later" or e["kind"] in ("reveal_hidden", "revealed"))]
    evidence = [e["event_id"] for e in analysis["timeline"] if e["seq"] <= d["seq"] and e["event_id"] not in contested
                and e["certainty"] == "confirmed" and e.get("turn") == d.get("turn")]
    engine = ev.get("engine") or {}
    item = {"decision_id": d["decision_id"], "at_event": d["at_event"], "actor": d["actor"],
            "decision_time_perspective": analysis["perspective"],
            "information": {"cutoff_event": d["at_event"], "evidence_events": evidence,
                            "available": d.get("information_available", []),
                            "withheld": d.get("information_withheld", []),
                            "hindsight_excluded": later_reveals},
            "selected_action": {"text": d.get("recorded_choice"), "text_zh": d.get("recorded_choice_zh")},
            "alternatives": copy.deepcopy(d["alternatives"]),
            "engine_check": engine.get("check_id"),
            "strategy_reasoning": {"zh": NO_EVALUATOR_ZH, "en": NO_EVALUATOR_EN}}
    rules_zh, rules_en = "", ""

    def done(cls: str, confidence: str, rz: str, re_: str, improve: tuple[str, str] | None = None):
        item.update({"classification": cls, "confidence": confidence,
                     "rules_reasoning": {"zh": rz, "en": re_},
                     "improvement": {"zh": improve[0], "en": improve[1]} if improve else None,
                     "feedback_target": FEEDBACK[cls]})
        if later_reveals and cls not in ("insufficient_information",):
            item["hindsight_guard"] = {
                "later_events": later_reveals, "classification_if_used": "outcome_bias",
                "zh": f"之後才公開的資訊（{', '.join(later_reveals)}）不拿來評這一步；若以它批評這個決定，屬於結果論（outcome_bias）。",
                "en": f"Information revealed later ({', '.join(later_reveals)}) is not used here; criticising this decision "
                      "with it would be outcome bias."}
        return item

    if d["at_event"] in contested:
        return done("insufficient_information", "high", "這一步所在的紀錄與另一筆紀錄互相矛盾，無法判定當時的局面。",
                    "The event this decision sits on is contradicted by another record; the state at the time cannot be established.")
    if ev.get("certainty") == "unknown" or d.get("recorded_choice") in (None, ""):
        return done("insufficient_information", "high", "紀錄沒有寫出這一步實際做了什麼。",
                    "The record does not say what was actually done.")
    if d.get("unknown_at_decision_time"):
        missing = "、".join(d["unknown_at_decision_time"])
        return done("insufficient_information", "high", f"判斷這一步需要的資訊紀錄裡沒有：{missing}。",
                    f"The information needed to grade it is not in the record: {', '.join(d['unknown_at_decision_time'])}.")
    if ev.get("gap"):
        return done("insufficient_information", "high", f"紀錄在這裡有缺漏：{ev['gap']}。", f"The record has a gap here: {ev['gap']}.")
    if engine.get("mode") == "timing_check":
        if engine.get("status") != "checked":
            return done("insufficient_information", "medium",
                        f"引擎無法重建這一步的時機狀態，缺：{'、'.join(engine.get('missing_information', []))}。",
                        f"The engine cannot rebuild this step's timing state; missing: {', '.join(engine.get('missing_information', []))}.")
        if engine.get("outcome") == "illegal":
            return done("rules_execution_error", "medium", f"引擎時機檢查不允許這個動作：{engine.get('explanation')}",
                        f"The engine's timing check does not allow this action: {engine.get('explanation')}",
                        ("回頭查這一步的時機規則：" + "、".join(engine.get("rule_locators") or []), "Check the timing rules: " + ", ".join(engine.get("rule_locators") or [])))
        if engine.get("outcome") == "unsupported":
            return done("unsupported_engine_behavior", "high", "引擎不支援這種動作的檢查，不判。",
                        "The engine does not support checking this kind of action, so no verdict is given.")
        if engine.get("outcome") == "invalid_input":
            return done("insufficient_information", "medium", "紀錄描述的時機狀態本身不成立，無法檢查。",
                        "The timing state the record describes is not a valid state, so it cannot be checked.")
        rules_zh = f"時機合法（引擎檢查 {engine.get('check_id')}）：{engine.get('explanation')}"
        rules_en = f"Legal timing (engine check {engine.get('check_id')}): {engine.get('explanation')}"
        return done("reasonable_alternative", "medium", rules_zh, rules_en)
    # engine trace
    alts = d["alternatives"]
    chosen_kind = next((a["kind"] for a in alts["items"] if a.get("chosen")), None)
    others = [a for a in alts["items"] if not a.get("chosen")]
    rules_zh = "引擎重播確認這一步合法（重播每一步雜湊都對上紀錄）。"
    rules_en = "The engine replay confirms this action was legal (every replayed state hash matched the record)."
    if not others:
        return done("unsupported_engine_behavior", "medium", rules_zh + "但引擎沒有列出其他選擇，無法比較。",
                    rules_en + " The engine listed no other choice to compare.")
    window = d.get("window") or {}
    response = str(window.get("state_label", "")).endswith("closed") or str(window.get("state_label", "")).startswith("showdown")
    plays = [a for a in others if a["kind"] in ("play_card", "hide", "activate_ability")]
    if chosen_kind in ("pass_priority", "pass_focus") and response and plays:
        names_zh = "；".join(a["text_zh"] for a in plays[:5])
        names_en = "; ".join(a["text"] for a in plays[:5])
        return done("missed_response_window", "low", rules_zh + f"當時還有合法的回應可用：{names_zh}。",
                    rules_en + f" Legal responses were available: {names_en}.",
                    (f"回頭看這個回應時機：可以考慮 {names_zh}。是否該用，本系統不評估。",
                     f"Revisit this response window: {names_en} were available. Whether to use them is not evaluated here."))
    names_zh = "；".join(a["text_zh"] for a in others[:5])
    names_en = "; ".join(a["text"] for a in others[:5])
    return done("reasonable_alternative", "medium", rules_zh + f"其他合法選擇：{names_zh}。",
                rules_en + f" Other legal choices: {names_en}.")


def review(analysis: dict) -> dict[str, Any]:
    items = [_review_item(analysis, d) for d in analysis["decision_points"]]
    counts = {c: sum(1 for i in items if i["classification"] == c) for c in CLASSIFICATIONS}
    reviewed = sorted({d["actor"] for d in analysis["decision_points"] if d.get("actor")})
    out = {"schema_version": REVIEW_VERSION, "analysis": _ref(analysis), "generated_by": dict(MODULE),
           "perspective": analysis["perspective"], "reviewed_players": reviewed,
           "strategy_evaluator": "none", "items": items, "counts": counts,
           "notes": {"zh": "覆盤只用每個決定當下及之前的事件；之後才公開的資訊不拿來評分。引擎不支援或紀錄不足的地方明講不判。",
                     "en": "Each decision is graded only on events at or before it. Where the engine has no support or the record is short, the review says so and gives no verdict."}}
    out["review_id"] = "match-review:" + _hash(out)[7:31]
    return out


# --------------------------------------------------------------------------------------------- commentary

def _segment(n: int, level: str, event_ids: list[str], zh: str, en: str, label: str, **extra) -> dict[str, Any]:
    seg = {"segment_id": f"s{n:03d}", "level": level, "event_ids": event_ids, "label": label,
           "text": {"zh-Hant": zh, "en": en}}
    seg.update({k: v for k, v in extra.items() if v is not None})
    return seg


RULE_ZH = {"ok": "時機合法", "priority_required": "只有持有優先權的玩家能這樣做",
           "reaction_required_in_closed_state": "連鎖存在時只能打出反應",
           "focus_required": "對決中只有持有焦點的玩家能開啟新連鎖"}


def commentary(analysis: dict, audience: str = "player", length: str = "standard") -> dict[str, Any]:
    if audience not in AUDIENCES or length not in LENGTHS:
        raise ValueError("audience or length is not one this module defines")
    tl = analysis["timeline"]
    contested = {e for c in analysis["contradictions"] for e in c["events"]}
    segs: list[dict] = []

    def add(level, ids, zh, en, label, **extra):
        segs.append(_segment(len(segs) + 1, level, ids, zh, en, label, **extra))

    # match summary first: what the record is, and what it can and cannot tell
    src = analysis["source"]
    players = analysis.get("players") or {}
    names = {p: _short((players.get(p) or {}).get("legend")) for p in PLAYERS}
    who = f"P1（{names['p1']}）對 P2（{names['p2']}）"
    who_en = f"P1 ({names['p1']}) vs P2 ({names['p2']})"
    end = next((e for e in tl if e["kind"] == "game_over"), None)
    turns = sorted({e.get("turn") for e in tl if isinstance(e.get("turn"), int)})
    if any(e["kind"] == "turn_began" for e in tl):
        turns = [t for t in turns if t >= 1]
    plays = {p: [] for p in PLAYERS}
    for e in tl:
        if e["kind"] in ("play_card", "reveal_hidden") and e.get("actor") in plays and e["event_id"] not in contested \
                and e["data"].get("card") and e["data"]["card"] not in plays[e["actor"]]:
            plays[e["actor"]].append(e["data"]["card"])
    summary_ids = [end["event_id"]] if end else []
    if end:
        zh, en = say(end)
        sz = f"{who}，共 {len(turns)} 個回合。{zh}。"
        se = f"{who_en}, {len(turns)} turns. {en}."
    else:
        span = (f"第 {turns[0]} 回合" if len(turns) == 1 else f"第 {turns[0]}–{turns[-1]} 回合") if turns else "片段"
        span_en = (f"turn {turns[0]}" if len(turns) == 1 else f"turns {turns[0]}-{turns[-1]}") if turns else "a fragment"
        sz = f"{who}。這份紀錄只涵蓋{span}，看不出整局結果。"
        se = f"{who_en}. This record covers only {span_en}; the result of the game is not in it."
    for p in PLAYERS:
        if plays[p]:
            sz += f"{p.upper()} 公開打出的牌：{'、'.join(_q(c) for c in plays[p])}。"
            se += f" {p.upper()} played: {', '.join(plays[p])}."
    if analysis["information_boundary"]["withheld"]:
        n = len(analysis["information_boundary"]["withheld"])
        sz += f"依 {analysis['perspective']} 視角，有 {n} 則看不到的資訊沒有使用。"
        se += f" From the {analysis['perspective']} perspective, {n} event(s) it could not see are not used."
    if analysis["contradictions"]:
        sz += f"紀錄中有 {len(analysis['contradictions'])} 處互相矛盾，相關段落不當成事實講述。"
        se += f" The record contradicts itself in {len(analysis['contradictions'])} place(s); those parts are not narrated as fact."
    add("match_summary", summary_ids, sz, se, "confirmed")

    # turning points
    for tp in analysis["turning_points"]:
        add("turning_point", [tp["at_event"]], tp["summary_zh"] + "。", tp["summary"] + ".", "confirmed",
            turning_point_id=tp["turning_point_id"])

    # contradictions and unknowns, always
    by_id = {e["event_id"]: e for e in tl}
    for c in analysis["contradictions"]:
        a, b = (by_id[i] for i in c["events"])
        fz = {"object_liveness": f"{_q(c.get('object'))}是否還活著", "priority": "誰持有優先權", "focus": "誰持有焦點"}[c["field"]]
        fe = {"object_liveness": f"whether {c.get('object')} was still alive", "priority": "who held Priority",
              "focus": "who held Focus"}[c["field"]]
        add("sequence", c["events"], f"紀錄在這裡互相矛盾：{a['event_id']} 與 {b['event_id']} 對「{fz}」說法不同，無法判定哪一份正確，這段不講述。",
            f"The record contradicts itself: {a['event_id']} and {b['event_id']} disagree about {fe}. Which is right cannot be told, so this part is not narrated.",
            "unknown", contradiction_id=c["contradiction_id"])
    for e in tl:
        if e["certainty"] == "unknown" and e["event_id"] not in contested:
            zh, en = say(e)
            add("event", [e["event_id"]], zh + "。", en + ".", "unknown")
        if e.get("gap") and e["event_id"] not in contested:
            add("event", [e["event_id"]], f"紀錄缺漏：{e['gap']}。這部分不推測。", f"Not recorded: {e['gap']}. This is not guessed at.", "unknown")

    # hindsight: a reveal that tells what an earlier hidden card was
    for e in tl:
        if e["kind"] == "reveal_hidden" or e["visibility"] == "revealed_later":
            shadow = next((s for s in tl if s["kind"] == "hidden_action" and s["seq"] < e["seq"]
                           and s.get("actor") == e.get("actor")), None)
            if shadow:
                add("sequence", [shadow["event_id"], e["event_id"]],
                    f"回頭看：{shadow['event_id']} 蓋下的牌就是{_q(e['data'].get('card'))}。這是事後才知道的，對手在當下看不到。",
                    f"In hindsight: the card hidden at {shadow['event_id']} was {e['data'].get('card')}. This was known only afterwards; the opponent could not see it then.",
                    "hindsight_only")

    # per-turn sequences
    if length in ("standard", "full"):
        for turn in turns:
            evs = [e for e in tl if e.get("turn") == turn and e["salience"] == "high" and e["event_id"] not in contested
                   and e["certainty"] == "confirmed"]
            if not evs:
                continue
            parts = [say(e) for e in evs]
            tp_player = next((e["data"].get("player") for e in tl if e["kind"] == "turn_began" and e["data"].get("turn") == turn), None) \
                or evs[0].get("turn_player")
            head_z = f"第 {turn} 回合" + (f"（{tp_player.upper()}）" if tp_player in PLAYERS else "")
            head_e = f"Turn {turn}" + (f" ({tp_player.upper()})" if tp_player in PLAYERS else "")
            add("sequence", [e["event_id"] for e in evs], head_z + "：" + "；".join(p[0] for p in parts) + "。",
                head_e + ": " + "; ".join(p[1] for p in parts) + ".", "confirmed")

    # event level
    if length == "full":
        for e in tl:
            if e["salience"] == "low" or e["event_id"] in contested or e["certainty"] != "confirmed":
                continue
            zh, en = say(e)
            eng = e.get("engine") or {}
            rules = None
            if eng.get("status") == "checked":
                rules = {"check_id": eng["check_id"], "outcome": eng["outcome"], "rule_locators": eng.get("rule_locators"),
                         "en": eng.get("explanation"), "zh": RULE_ZH.get(eng.get("reason_code"), eng.get("reason_code"))}
            add("event", [e["event_id"]], zh + "。", en + ".", "confirmed", rules=rules)

    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    first = {s["segment_id"]: min((by_id[i]["seq"] for i in s["event_ids"] if i in by_id), default=0) for s in segs}
    segs.sort(key=lambda s: (s["level"] != "match_summary", first[s["segment_id"]], order[s["level"]]))
    for n, s in enumerate(segs, 1):
        s["segment_id"] = f"s{n:03d}"
    out = {"schema_version": COMMENTARY_VERSION, "analysis": _ref(analysis), "generated_by": dict(MODULE),
           "perspective": analysis["perspective"], "audience": audience, "tone": "neutral", "length": length,
           "levels": [lvl for lvl in LEVELS if any(s["level"] == lvl for s in segs)],
           "segments": segs,
           "recap": {"zh-Hant": segs[0]["text"]["zh-Hant"], "en": segs[0]["text"]["en"]},
           "notes": {"zh": "講評不推測動機，也不使用該視角看不到的資訊；不把任何一步說成失誤。",
                     "en": "Commentary does not guess at motives or use what the perspective could not see, and calls no play a mistake."}}
    out["commentary_id"] = "match-commentary:" + _hash(out)[7:31]
    return out


# --------------------------------------------------------------------------------------------- agreement and shape

def agreement_problems(analysis: dict, rev: dict, com: dict) -> list[str]:
    """Review and Commentary must be projections of the same confirmed timeline."""
    problems = []
    ref = _ref(analysis)
    for name, art in (("review", rev), ("commentary", com)):
        if art.get("analysis") != ref:
            problems.append(f"{name} names another analysis or another confirmed state")
    ids = {e["event_id"]: e for e in analysis["timeline"]}
    confirmed = confirmed_events(analysis)
    withheld = {w["event_id"] for w in analysis["information_boundary"]["withheld"]}
    for item in rev.get("items", []):
        d = next((x for x in analysis["decision_points"] if x["decision_id"] == item["decision_id"]), None)
        if d is None:
            problems.append(f"review item {item['decision_id']} is not a decision point of the analysis")
            continue
        for eid in item["information"]["evidence_events"]:
            if eid not in confirmed:
                problems.append(f"review {item['decision_id']} uses {eid}, which is not confirmed")
            elif ids[eid]["seq"] > d["seq"]:
                problems.append(f"review {item['decision_id']} uses {eid}, which is after the decision (hindsight)")
    for seg in com.get("segments", []):
        for eid in seg["event_ids"]:
            if eid in withheld or eid not in ids:
                problems.append(f"commentary {seg['segment_id']} names {eid}, which this perspective may not use")
            elif seg["label"] == "confirmed" and eid not in confirmed:
                problems.append(f"commentary {seg['segment_id']} calls {eid} confirmed; the analysis does not")
    return problems


def _require(value: dict, keys: tuple[str, ...], where: str) -> list[str]:
    return [f"{where}: missing {k}" for k in keys if k not in value]


def validate_analysis(a: Any) -> list[str]:
    if not isinstance(a, dict) or a.get("schema_version") != ANALYSIS_VERSION:
        return ["not a match-analysis.v1"]
    errs = _require(a, ("analysis_id", "source", "ruleset", "perspective", "information_boundary", "timeline",
                        "timeline_hash", "source_map", "reconstruction", "ledger", "contradictions", "decision_points",
                        "turning_points", "coverage", "confirmed_digest"), "analysis")
    if a.get("perspective") not in PERSPECTIVES:
        errs.append("analysis: unknown perspective")
    seen = set()
    for ev in a.get("timeline", []):
        errs += _require(ev, ("event_id", "seq", "source_event_ids", "kind", "visibility", "certainty"), ev.get("event_id", "event"))
        if ev.get("event_id") in seen:
            errs.append(f"duplicate event id {ev.get('event_id')}")
        seen.add(ev.get("event_id"))
        if not ev.get("source_event_ids"):
            errs.append(f"{ev.get('event_id')}: no source event id")
        if not _visible(ev.get("visibility", ""), a.get("perspective", "")):
            errs.append(f"{ev.get('event_id')}: the perspective may not read this event, yet it is in the timeline")
    for f in a.get("ledger", []):
        if f.get("label") not in FACT_LABELS:
            errs.append(f"{f.get('fact_id')}: label {f.get('label')!r}")
    if a.get("coverage", {}).get("complete_game") is not False:
        errs.append("analysis: coverage.complete_game must be false")
    if a.get("timeline_hash") != _hash(a.get("timeline")):
        errs.append("analysis: timeline_hash is not the timeline's")
    return errs


def validate_review(r: Any) -> list[str]:
    if not isinstance(r, dict) or r.get("schema_version") != REVIEW_VERSION:
        return ["not a match-review.v1"]
    errs = _require(r, ("review_id", "analysis", "perspective", "items", "strategy_evaluator"), "review")
    for item in r.get("items", []):
        errs += _require(item, ("decision_id", "at_event", "actor", "classification", "confidence", "rules_reasoning",
                                "strategy_reasoning", "alternatives", "information"), item.get("decision_id", "item"))
        if item.get("classification") not in CLASSIFICATIONS:
            errs.append(f"{item.get('decision_id')}: classification {item.get('classification')!r}")
        if item.get("classification") == "strategic_misplay" and r.get("strategy_evaluator") == "none":
            errs.append(f"{item.get('decision_id')}: strategic_misplay without a strategy evaluator")
    return errs


def validate_commentary(c: Any) -> list[str]:
    if not isinstance(c, dict) or c.get("schema_version") != COMMENTARY_VERSION:
        return ["not a match-commentary.v1"]
    errs = _require(c, ("commentary_id", "analysis", "audience", "tone", "length", "segments", "recap"), "commentary")
    for s in c.get("segments", []):
        errs += _require(s, ("segment_id", "level", "event_ids", "label", "text"), s.get("segment_id", "segment"))
        if s.get("level") not in LEVELS:
            errs.append(f"{s.get('segment_id')}: level {s.get('level')!r}")
        if s.get("label") not in CLAIM_LABELS:
            errs.append(f"{s.get('segment_id')}: label {s.get('label')!r}")
        if not (s.get("text") or {}).get("zh-Hant") or not (s.get("text") or {}).get("en"):
            errs.append(f"{s.get('segment_id')}: needs both zh-Hant and en text")
    return errs


def run(source: dict, perspective: str | None = None, audience: str = "player", length: str = "standard") -> dict:
    """The whole pipeline: analysis, review and commentary, cross-linked and checked."""
    a = analyze(source, perspective)
    r = review(a)
    c = commentary(a, audience=audience, length=length)
    a["projections"] = {"review": r["review_id"], "commentary": c["commentary_id"]}
    problems = validate_analysis(a) + validate_review(r) + validate_commentary(c) + agreement_problems(a, r, c)
    return {"analysis": a, "review": r, "commentary": c, "problems": problems}
