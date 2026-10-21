#!/usr/bin/env python3
"""A per-state completeness receipt for the closed environment's action set (C2, package 13; GPT 2026-10-15 rulings 1, 3
and 5). It says, for one state and one player, whether the list of that player's actions is proved whole - and when it
is not, why, by name. It fails closed: anything it cannot show makes `complete` false.

  the point      the timing kernel says discretionary actions are allowed now (rules_core.next_procedure) - an action
                 point; or a procedure is due (a pending item to finalize, a task, a Combat step) - a procedure point
                 (package 14): no one acts at will, and the receipt is of the procedure's next decision
                 (decision_space.decision_point): the player who decides it gets its options (`point`); any other
                 player, none - complete, for no choice of theirs is open; chance's move (a receipt) is no one's
  the state      a state of the catalogue's environment (closed_environment.environment_problems)
  the families   every action kind (action_space.ACTION_KINDS) enumerated - none abstained, none unproved
  information    (ruling 5; PACKAGE13 rulings 4 and round two) two states the player sees alike must list the same
                 actions, and no action may name what the player cannot see. Proved by information flow, not by trying
                 substitutes: the published set is computed on the player's view (actor_view) - every card the player
                 cannot see (PRIVATE_DIMENSIONS: the opponent's unseen hand and facedown cards, the unseen cards of
                 both Main Decks and Rune Decks) a mask carrying only whose it is and where, named by its place, not
                 its id - so no private value, id or order reaches the computation; the receipt is complete only when
                 that set is also the true state's set (else depends_on_hidden:). An action naming an unseen card is
                 leaks:; a card shown to someone other than the player outside those dimensions is unvaried_private:.
                 A request another player decides, or chance, makes a family unproved (play_space).

  a procedure   (package 14) a decision is made when it is asked - after whatever the procedure did first (a card drawn
  point          before "discard one" is in its chooser's hand by then). So the published options are the true state's,
                 and two checks hold them to what the decider knows then: every unseen card an option names must be one
                 the request itself shows its decider (the options it lists for them, Core 128.4) - else leaks:; and the
                 same point computed on the decider's view at the point's start, its place names read back as the cards
                 they stand for, must give the same decider, request and options - else depends_on_hidden: (legality
                 that would change with what the decider never sees). A decision this module cannot prove whole is
                 unproved:<why>

    state_receipt(timing_state, effect_state, actor, catalogue, made=None) -> receipt
"""
from __future__ import annotations

import copy
from typing import Any

import action_space as AS
import closed_environment as CE
import game_loop as GL
import effect_ir as IR
import legal_action as LA
import rules_core

RECEIPT_VERSION = "c2-state-receipt.v1"
# a stand-in for an opponent's hand card when the information check swaps it: any catalogued card, its own record
SWAP_FIELDS = ("card_ref",)


def _observation(timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str) -> dict[str, Any]:
    return LA.build_observation(
        perspective={"p1": "player1", "p2": "player2"}.get(actor, "omniscient_replay"),
        source={"kind": "engine_state", "state_seq": 1},
        context={"ruleset_core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF, "format": "standard",
                 "card_data_version": "closed-environment"},
        timing_state=timing_state, effect_state=effect_state, facts={}, pending_decisions=[],
        completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"})


def action_keys(timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str, catalogue: dict[str, Any]
                ) -> tuple[dict[str, Any], list[str]]:
    result = LA.enumerate_actions(_observation(timing_state, effect_state, actor), actor, catalogue=catalogue)
    keys = sorted(AS.action_key_hash(a) for family in AS.ACTION_KINDS for a in AS.enumerated_actions(result, family))
    return result, keys


PRIVATE_DIMENSIONS = ("the opponent's hand", "the opponent's facedown cards", "the Main Decks", "the Rune Decks")
# the zones whose cards a player cannot see (each named in PRIVATE_DIMENSIONS above), by whose they are
HIDDEN_ZONES = {"hand": "opponent", "main_deck": "anyone", "rune_deck": "anyone"}


def shown_to(state: dict[str, Any], object_id: str, actor: str) -> bool:
    """A card the player was shown (Core 424: a reveal to all, or a look or reveal to them)."""
    return any(m.get("object_id") == object_id and (m.get("visible_to") == "all" or actor in (m.get("visible_to") or []))
               for m in state.get("reveals") or [])


def private_objects(state: dict[str, Any], actor: str) -> dict[str, str]:
    """{object id: the private dimension it is in} - what the player cannot see."""
    out = {}
    for player, record in state["players"].items():
        zones = record["zones"]
        if player != actor:
            out.update({o: PRIVATE_DIMENSIONS[0] for o in zones.get("hand") or [] if not shown_to(state, o, actor)})
        out.update({o: PRIVATE_DIMENSIONS[2] for o in zones.get("main_deck") or [] if not shown_to(state, o, actor)})
        out.update({o: PRIVATE_DIMENSIONS[3] for o in zones.get("rune_deck") or [] if not shown_to(state, o, actor)})
    for bf in (state.get("battlefields") or {}).values():
        for entry in ((bf.get("facedown") or {}).get("cards") or []):
            if entry.get("controller") != actor and not shown_to(state, entry.get("object_id"), actor):
                out[entry["object_id"]] = PRIVATE_DIMENSIONS[1]
    return out


def unvaried(state: dict[str, Any], actor: str) -> list[str]:
    """Private parts of the state no dimension here varies: a card shown to someone, not to the player, outside those
    zones (it would be private and unvaried)."""
    covered = set(private_objects(state, actor))
    out = []
    for mark in state.get("reveals") or []:
        if mark.get("visible_to") != "all" and actor not in (mark.get("visible_to") or []) and mark.get("object_id") not in covered:
            out.append(f"{mark.get('object_id')} in {mark.get('zone')}")
    return out


def _named(value: Any, out: set) -> set:
    if isinstance(value, dict):
        for v in value.values():
            _named(v, out)
    elif isinstance(value, list):
        for v in value:
            _named(v, out)
    elif isinstance(value, str):
        out.add(value)
    return out


def actor_view(effect_state: dict[str, Any], actor: str, *, names_out: dict[str, str] | None = None,
               seen: set | frozenset = frozenset()) -> dict[str, Any]:
    """The state as the player sees it: every card in PRIVATE_DIMENSIONS (private_objects) a mask (closed_environment.mask)
    - its owner, controller, place and identity token kept, nothing else. A function of what the player sees only.
    `names_out`, when given, receives {original id: place name} (the trusted verifier's, to read a view's answer back)."""
    # `seen` (package 15): cards the player sees when they decide - shown to them by the request itself - are not masked
    hidden = {o: d for o, d in private_objects(effect_state, actor).items() if o not in seen}
    # each unseen card is named by its place, not by its id - an id or an order could carry what was seen before; the
    # k-th unseen card of a zone is hidden:<whose>:<zone>:<k>, in the zone's order of unseen slots (a shown card keeps
    # its place and its id)
    names: dict[str, str] = {}
    for player, record in sorted(effect_state["players"].items()):
        for zone in CE.MASK_ZONES:
            unseen = [o for o in record["zones"].get(zone) or [] if o in hidden]
            names.update({o: f"hidden:{player}:{zone}:{k}" for k, o in enumerate(unseen)})
    for bf, entry in sorted((effect_state.get("battlefields") or {}).items()):
        unseen = [c.get("object_id") for c in ((entry.get("facedown") or {}).get("cards") or []) if c.get("object_id") in hidden]
        names.update({o: f"hidden:facedown:{bf}:{k}" for k, o in enumerate(unseen)})
    view = copy.deepcopy(effect_state)
    for object_id, dimension in hidden.items():
        view["objects"][object_id] = CE.mask(view["objects"][object_id], rune=dimension == PRIVATE_DIMENSIONS[3])
    if names_out is not None:
        names_out.update(names)
    return _renamed(view, names)


def _renamed(value: Any, names: dict[str, str]) -> Any:
    """Every id in `names`, as a whole string or an identity token ('<id>@<n>'), and as a key, under its new name."""
    if isinstance(value, dict):
        return {_renamed(k, names) if isinstance(k, str) else k: _renamed(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_renamed(v, names) for v in value]
    if isinstance(value, str):
        if value in names:
            return names[value]
        head, at, generation = value.rpartition("@")
        if at and head in names and generation.isdigit():
            return f"{names[head]}@{generation}"
    return value


def option_key(point: dict[str, Any], option: dict[str, Any]) -> str:
    """One option of a procedure point, canonically: what it answers, not its system ids."""
    import decision_space as DS
    return DS.way_key({**option["answer"], "label": point.get("label")})


def _procedure_receipt(timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str, catalogue: dict[str, Any],
                       procedure: dict[str, Any], made: dict[str, Any] | None) -> dict[str, Any]:
    import decision_space as DS
    why: list[str] = []
    problems = CE.validate_catalogue(catalogue) or CE.environment_problems(effect_state, catalogue)
    if problems:
        why.append(f"not_an_environment_state:{problems[0]}")
    true = DS.decision_point(timing_state, effect_state, catalogue, made)
    shown: set = set()
    if true["status"] == "enumerated" and true.get("decider") == actor and true.get("request") is not None:
        step = DS._run(timing_state, effect_state, catalogue, made)
        request = step.get("request") or {}
        shown = {o.get("object_id") for o in list(((request.get("payload") or {}).get("choice") or {}).get("options") or [])
                 + [o for options in (request.get("private_options") or {}).values() for o in options]}
    # package 15 (found by the corpus: Baited Hook looks at five cards and then picks among them): the decider's view at
    # the point's start, with the cards the request shows the decider unmasked - they are what the decider sees when
    # deciding; every other unseen card stays masked
    names: dict[str, str] = {}
    view = actor_view(effect_state, actor, names_out=names, seen=shown)
    back = {name: original for original, name in names.items()}
    with IR.frozen_inputs(view):
        seen = DS.decision_point(timing_state, view, catalogue, _renamed(made, names) if made else None)
    point = {"procedure": procedure.get("procedure"), "label": true.get("label"), "status": true["status"],
             "request": true.get("request"), "decider": true.get("decider")}
    keys: list[str] = []
    if true["status"] != "enumerated":
        why.append(f"unproved:{true.get('reason') or true['status']}")
    elif true.get("decider") == actor:
        keys = sorted(option_key(true, o) for o in true["options"])
        hidden = private_objects(effect_state, actor)
        named = set()
        for option in true["options"]:
            named |= _named(option["answer"]["decisions"], set())
        for object_id in sorted((named & set(hidden)) - shown):
            why.append(f"leaks:{object_id} ({hidden[object_id]}) - an option names it, and the request does not show it")
    # package 15 (found by the corpus: a Combat's Deal step): a point no player decides at - the procedure commits with no
    # request - has no options to hold to the decider's view (its own bindings, a receipt bound to the true state's hash,
    # never hold on a masked copy)
    # (and only the decider's: a player who decides nothing here has no options that could depend on what they do not see)
    if true["status"] == "enumerated" and true.get("request") is not None and true.get("decider") == actor:
        # (an engine-made id - a Combat's, a batch's - is made from the public projection, effect_ir.public_id: the view
        # makes the very same one, and the options are compared as they are; GPT PACKAGE15 round 2 ruling 5)
        seen_keys = sorted(option_key(seen, {"answer": _renamed(o["answer"], back)}) for o in seen.get("options") or []) \
            if seen.get("decider") == actor else []
        if seen["status"] != "enumerated" or seen.get("decider") != true.get("decider") \
                or (seen.get("request") or {}).get("code") != (true.get("request") or {}).get("code") or seen_keys != keys:
            present = sorted(set(private_objects(effect_state, actor).values()), key=PRIVATE_DIMENSIONS.index)
            why.append(f"depends_on_hidden:{','.join(present) or 'nothing private'} - the decider's view at the point's "
                       f"start does not give the same decision ({seen.get('status')}: {str(seen.get('reason') or '')[:80]})")
    why += [f"unvaried_private:{where}" for where in unvaried(effect_state, actor)]
    receipt = {"schema_version": RECEIPT_VERSION, "actor": actor,
               "timing_state_hash": rules_core.state_hash(timing_state), "effect_state_hash": IR.hash_value(effect_state),
               "catalogue_hash": catalogue.get("catalogue_hash"),
               "engine": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF, "rule_numbering": IR.RULE_NUMBERING},
               "point": point, "families": {}, "information": {}, "actions": keys, "complete": not why, "why": why}
    receipt["receipt_hash"] = IR.hash_value({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return receipt


def state_receipt(timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str,
                  catalogue: dict[str, Any], made: dict[str, Any] | None = None) -> dict[str, Any]:
    # 2026-10-18 package 15: the state (and below, the player's view of it) is read many times over and never changed -
    # held frozen (effect_ir.frozen_inputs: its hash and derived characteristics computed once, checked unchanged after)
    with IR.frozen_inputs(effect_state):
        return _state_receipt(timing_state, effect_state, actor, catalogue, made)


def _state_receipt(timing_state: dict[str, Any], effect_state: dict[str, Any], actor: str,
                   catalogue: dict[str, Any], made: dict[str, Any] | None = None) -> dict[str, Any]:
    why: list[str] = []
    procedure = rules_core.next_procedure(timing_state)
    if procedure.get("discretionary_actions_allowed") is not True:
        return _procedure_receipt(timing_state, effect_state, actor, catalogue, procedure, made)
    problems = CE.validate_catalogue(catalogue) or CE.environment_problems(effect_state, catalogue)
    if problems:
        why.append(f"not_an_environment_state:{problems[0]}")
    # the published set is the view's (information flow: no private value reaches it); the true state's set is
    # computed only to check it is the same
    view = actor_view(effect_state, actor)
    with IR.frozen_inputs(view):
        result, keys = action_keys(timing_state, view, actor, catalogue)
    _, true_keys = action_keys(timing_state, effect_state, actor, catalogue)
    families = {}
    for record in result["enumeration"]["families"]:
        families[record["family"]] = {"status": record["status"], "reason": record["reason_code"],
                                      "count": len(record.get("candidates") or [])}
        if record["status"] != "enumerated":
            why.append(f"{record['family']}:{record['reason_code']}")
    if set(families) != set(AS.ACTION_KINDS):
        why.append(f"families {sorted(families)} are not the action kinds {sorted(AS.ACTION_KINDS)}")
    information = {}
    if not why:
        hidden = private_objects(effect_state, actor)
        named = set()
        for family in AS.ACTION_KINDS:
            for action in AS.enumerated_actions(result, family):
                named |= _named(AS.canonical_action_key(action), set())
        for object_id in sorted(named & set(hidden)):
            why.append(f"leaks:{object_id} ({hidden[object_id]})")
        for object_id in sorted(n for n in named if n.startswith("hidden:")):
            why.append(f"leaks:{object_id} (an unseen card of the player's view)")
        why += [f"unvaried_private:{where}" for where in unvaried(effect_state, actor)]
        present = sorted(set(hidden.values()), key=PRIVATE_DIMENSIONS.index)
        information = {dimension: "masked" for dimension in present}
        if keys != true_keys:
            # the true state's set differs from what the player's view gives: it depends on what the player cannot see
            why.append(f"depends_on_hidden:{','.join(present) or 'nothing private'} - the view lists {len(keys)}, "
                       f"the state {len(true_keys)}")
    receipt = {"schema_version": RECEIPT_VERSION, "actor": actor,
               "timing_state_hash": rules_core.state_hash(timing_state), "effect_state_hash": IR.hash_value(effect_state),
               "catalogue_hash": catalogue.get("catalogue_hash"),
               "engine": {"core": IR.CORE_RULESET, "faq_as_of": IR.FAQ_AS_OF, "rule_numbering": IR.RULE_NUMBERING},
               "point": {"procedure": procedure.get("procedure"), "label": "action_point", "status": "enumerated",
                         "request": None, "decider": actor},
               "families": families, "information": information, "actions": keys,
               "complete": not why, "why": why}
    receipt["receipt_hash"] = IR.hash_value({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return receipt
