#!/usr/bin/env python3
"""Regression gate for a permanent's discount on its controller's cards of one tag (package 6).

"Your [Tag]s' Energy costs are reduced by [N], to a minimum of [M]." is printed on a permanent; it
works while the permanent is on the board (a passive, Core 363) and reduces the Energy cost of a card
its controller plays when that card has the tag, as printed (Core 133.8; object_tags). A discount may
come from a card other than the one played (356.4.a); its minimum is its own (356.4.e); nothing goes
below 0 (356.6).

Must hold (each has a failing case below):
  applies     the controller's tagged card costs N less, never below M by this discount
  scope       an untagged card, a card of another tag, the opponent's tagged card, and every card
              while the permanent is not on the board (in hand, in the trash) pay the printed cost
  power       the Power cost is untouched
  own         the card's own printed reduction still applies beside it
  enumerator  a card affordable only with the discount is offered; with the permanent gone, not
  shapes      validate_state holds tags and the discount to their contract
  grammar     the production lowers the sentence; near misses do not
Every fixture is synthetic.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import clause_grammar as cg  # noqa: E402
import legal_action as la  # noqa: E402
import play_transaction as pt  # noqa: E402
from check_effect_ir import base_state  # noqa: E402
from check_rules_core import fixture  # noqa: E402
from effect_ir import object_tags, validate_state  # noqa: E402
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

DISCOUNT = {"discount_id": "d", "applies_to": "energy", "amount": 2, "minimum": 1, "card_tag": "Dragon"}


def herald(owner):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": 3, "might_modifiers": [], "damage": 0,
            "exhausted": False, "granted_cost_discounts": [copy.deepcopy(DISCOUNT)]}


def state(*, energy_cost=4, tags=("Dragon",), herald_at=("p1", "base"), actor="p1", power_cost=None, own=None):
    s = base_state()
    s["turn_id"] = "turn-3"
    card = {"owner": actor, "controller": actor, "kind": "unit", "base_might": 2, "might_modifiers": [], "damage": 0,
            "exhausted": False, "printed_cost": {"energy": energy_cost, "power": dict(power_cost or {})},
            "domains": ["body"], "tags": list(tags)}
    if own:
        card["printed_cost_modifications"] = [own]
    s["objects"]["d1"] = card
    s["players"][actor]["zones"]["hand"].append("d1")
    s["objects"]["h1"] = herald(herald_at[0])
    s["players"][herald_at[0]]["zones"][herald_at[1]].append("h1")
    for player in ("p1", "p2"):
        s["players"][player]["resources"] = {"energy": 10, "power": {"body": 5}}
    return s


def declaration(s, actor="p1"):
    printed = s["objects"]["d1"]["printed_cost"]
    return {"schema_version": pt.DECLARATION_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "play_id": "play-d1", "actor": actor, "card": "d1",
            "chain_item": {"id": "unit-d1", "object_kind": "unit", "timing": "default"},
            "cost": {"base": copy.deepcopy(printed)}, "entry_location": {"kind": "base"},
            "payment_context": {"add_window_closed": True, "confirmed_by": "human"}}


def paid(s, actor="p1"):
    """(Energy paid, Power paid) for the play, or None when it did not commit."""
    timing = fixture() if actor == "p1" else {**fixture(priority=actor), "turn_player": actor}
    result = pt.play_card(timing, s, declaration(s, actor))
    if not result.get("committed"):
        return None
    after = result["next_effect_state"]["players"][actor]["resources"]
    return 10 - after["energy"], 5 - after["power"].get("body", 0)


def main() -> int:
    errors: list[str] = []

    # --- the discount applies, to its minimum -----------------------------------------------------------
    for cost, wanted in ((4, 2), (3, 1), (2, 1), (1, 1), (0, 0)):
        got = paid(state(energy_cost=cost))
        if got is None or got[0] != wanted:
            errors.append(f"a Dragon costing {cost} with the discount on the board paid {got}, not {wanted} Energy")

    # --- where it does not apply ----------------------------------------------------------------------
    for label, kwargs in (("an untagged card", {"tags": ()}), ("a card of another tag", {"tags": ("Poro",)}),
                          ("the discount's source in its owner's hand", {"herald_at": ("p1", "hand")}),
                          ("the discount's source in the trash", {"herald_at": ("p1", "trash")}),
                          ("the opponent's discount", {"herald_at": ("p2", "base")})):
        got = paid(state(**kwargs))
        if got is None or got[0] != 4:
            errors.append(f"{label}: the Dragon paid {got}, not its printed 4 Energy")
    opponent = state(herald_at=("p1", "base"), actor="p2")
    got = paid(opponent, actor="p2")
    if got is None or got[0] != 4:
        errors.append(f"the opponent's Dragon was discounted by p1's permanent: paid {got}")
    lowercase = state(tags=("dragon",))
    if paid(lowercase)[0] != 4:
        errors.append("a tag that is not the printed one ('dragon') was discounted")

    # --- Power untouched, and the card's own reduction still applies ----------------------------------
    got = paid(state(energy_cost=4, power_cost={"body": 2}))
    if got != (2, 2):
        errors.append(f"with a Power cost, the discount paid {got}, not (2 Energy, 2 Power)")
    own = {"modification_id": "m", "kind": "energy_reduction", "amount": 1}
    got = paid(state(energy_cost=5, own=own))
    if got is None or got[0] != 2:
        errors.append(f"the card's own reduction and the granted one did not both apply: paid {got}, not 2")
    if [d["id"] for d in pt.granted_cost_discounts(state(), "d1", "p1")] != ["granted:h1:d"]:
        errors.append("granted_cost_discounts did not name the one granted discount")

    # --- the enumerator reads the same discount ---------------------------------------------------------
    def offered(s):
        s["players"]["p1"]["resources"] = {"energy": 2, "power": {}}
        observation = la.build_observation(
            perspective="player1", source={"kind": "engine_state", "state_seq": 1},
            context={"ruleset_core": CORE_RULESET, "faq_as_of": FAQ_AS_OF, "format": "standard", "card_data_version": "synthetic"},
            timing_state=fixture(), effect_state=s, facts={}, pending_decisions=[],
            completeness={"hands": "complete", "board": "complete", "resources": "complete", "pending_decisions": "complete"})
        return any(a["candidate_id"] == "play:d1" for a in la.enumerate_actions(observation, "p1")["enumeration"]["actions"])
    if not offered(state()):
        errors.append("the enumerator did not offer a Dragon affordable only with the granted discount")
    if offered(state(herald_at=("p1", "hand"))):
        errors.append("the enumerator offered the discount while its source is not on the board")

    # --- shapes -------------------------------------------------------------------------------------------
    for label, change in (("tags not a list", lambda s: s["objects"]["d1"].update(tags="Dragon")),
                          ("a duplicated tag", lambda s: s["objects"]["d1"].update(tags=["Dragon", "Dragon"])),
                          ("a Power discount", lambda s: s["objects"]["h1"]["granted_cost_discounts"][0].update(applies_to="power:body")),
                          ("no tag", lambda s: s["objects"]["h1"]["granted_cost_discounts"][0].pop("card_tag")),
                          ("a zero amount", lambda s: s["objects"]["h1"]["granted_cost_discounts"][0].update(amount=0))):
        s = state()
        change(s)
        if not validate_state(s):
            errors.append(f"validate_state accepted {label}")
    if validate_state(state()):
        errors.append(f"validate_state refused a well-formed board: {validate_state(state())}")
    if object_tags(state(), "d1") != ["Dragon"] or object_tags(state(), "u1") not in (None, []):
        errors.append("object_tags did not read the printed tags")

    # --- "While I'm at a battlefield, the Energy costs for spells you play is reduced by [1], to a minimum of [1]."
    spell_discount = {"discount_id": "e", "applies_to": "energy", "amount": 1, "minimum": 1, "card_kind": "spell",
                      "source_at": "battlefield"}

    def apprentice_board(kind, cost, where=("p1", "bf1")):
        s = state(energy_cost=cost, tags=())
        s["objects"]["d1"]["kind"] = kind
        s["objects"]["h1"]["granted_cost_discounts"] = [dict(spell_discount)]
        s["objects"]["h1"]["owner"] = s["objects"]["h1"]["controller"] = where[0]
        s["players"]["p1"]["zones"]["base"].remove("h1")
        if where[1] == "base":
            s["players"][where[0]]["zones"]["base"].append("h1")
        else:
            s["battlefields"][where[1]] = {"controller": where[0], "objects": ["h1"]}
        return s

    def paid_as(s, kind):
        decl = declaration(s)
        decl["chain_item"]["object_kind"] = kind
        if kind == "spell":
            decl.pop("entry_location")
        result = pt.play_card(fixture(), s, decl)
        return (10 - result["next_effect_state"]["players"]["p1"]["resources"]["energy"]) if result.get("committed") else None

    for label, kind, cost, where, wanted in (("a spell costing 3, the source at a battlefield", "spell", 3, ("p1", "bf1"), 2),
                                             ("a spell costing 1 (the minimum)", "spell", 1, ("p1", "bf1"), 1),
                                             ("a unit costing 3", "unit", 3, ("p1", "bf1"), 3),
                                             ("a spell costing 3, the source in its Base", "spell", 3, ("p1", "base"), 3),
                                             ("a spell costing 3, the opponent's source at a battlefield", "spell", 3, ("p2", "bf2"), 3)):
        got = paid_as(apprentice_board(kind, cost, where), kind)
        if got != wanted:
            errors.append(f"{label}: paid {got}, not {wanted} Energy")
    bad = apprentice_board("spell", 3)
    bad["objects"]["h1"]["granted_cost_discounts"][0]["source_at"] = "base"
    if not validate_state(bad):
        errors.append("validate_state accepted a source_at other than battlefield")
    both = apprentice_board("spell", 3)
    both["objects"]["h1"]["granted_cost_discounts"][0]["card_tag"] = "Dragon"
    if not validate_state(both):
        errors.append("validate_state accepted a discount naming both a tag and a kind")

    # --- the grammar ------------------------------------------------------------------------------------
    grammar = cg.load_grammar()
    one = cg.compile_clause("Your Dragons' Energy costs are reduced by :rb_energy_2:, to a minimum of :rb_energy_1:.", grammar)
    if one.get("unsupported") or one["passive"]["object_fields"]["granted_cost_discounts"] != [
            {"discount_id": "$clause_id", "applies_to": "energy", "amount": 2, "minimum": 1, "card_tag": "Dragon"}]:
        errors.append(f"the sentence did not lower to the granted discount: {one}")
    for text in ("Your Dragons' Energy costs are reduced by :rb_energy_2:.", "Dragons' Energy costs are reduced by :rb_energy_2:, to a minimum of :rb_energy_1:.",
                 "Your Dragons' Power costs are reduced by :rb_energy_2:, to a minimum of :rb_energy_1:."):
        if not cg.compile_clause(text, grammar).get("unsupported"):
            errors.append(f"a near miss lowered anyway: {text!r}")

    if errors:
        print("FAILED: granted cost discounts")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("granted cost discount checks passed: the controller's tagged cards cost N less to the discount's own minimum "
          "while its source is on the board, and nothing else does; the enumerator and grammar agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
