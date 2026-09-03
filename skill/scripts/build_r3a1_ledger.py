#!/usr/bin/env python3
"""
C-13: R3-A1 preparation — official locators, decision points, fixture drafts,
and decision packets for the eleven choices/costs/zones cards.

This runs *ahead of* X-09. Codex will rule on the semantics; this package
gives the ruling something concrete to rule on, and gives C-14..C-16 fixtures
to promote once the ruling lands. It therefore does three things and refuses
a fourth:

  1. For every R3-A1 clause in the inventory, records where the Core Rules
     speak to it — sub-clause locators with a short quoted excerpt, the source
     id and version, and whether the clause *targets* under 355.10.
  2. Records the expected decision point: made at play (355.1–355.5), made at
     resolution (355.17 / 436), made when a trigger is finalized (402), or
     none.
  3. Drafts four fixtures per clause — positive, negative, missing
     information, target invalidated — as state sketches over the real
     `check_effect_ir.base_state()` objects. They name the actor, the decision
     points, the mechanics required, and the locators.
  4. Does NOT write an expected outcome, an expected state, a program, or a
     new effect op anywhere. The fixture-draft shape has no field for them.
     Every judgement that would require a semantic contract is a decision
     packet instead, with the rule text on both sides and a proposed failure
     classification, so Codex can rule once for all eleven cards.

The judgement table below is keyed by clause-text hash. A clause whose text
changes gets a new hash, the table no longer covers it, and the build fails —
which is the correct response to a card's wording changing under a ruling.

Usage:
    python3 skill/scripts/build_r3a1_ledger.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PACK = SKILL_DIR / "data" / "card_program_packs" / "global-core-origins-v1"
INVENTORY_LEDGER = PACK / "inventory_ledger.json"
sys.path.insert(0, str(SCRIPT_DIR))

from effect_ir import SUPPORTED_OPS  # noqa: E402

BATCH = "R3-A1-choices-costs-zones"
CORE = {"source_id": "core-rules-2026-07-16", "version": "2026-07-16", "kind": "core_rules"}
ERRATA = {"source_id": "origins-errata-2025-10-28", "version": "2025-10-28", "kind": "errata"}
# Locally captured as an official HTML snapshot. The page itself warns that it
# may no longer reflect current rules, so default queries exclude it.
FAQ = {"source_id": "origins-faq-2025-10-16", "version": "2025-10-16", "kind": "official_clarification", "local": True, "status": "superseded"}

DECISION_POINTS = ("at_play", "at_resolution", "at_trigger_finalization", "none")
FIXTURE_KINDS = ("positive", "negative", "missing_information", "target_invalidated")
FAILURE_KINDS = ("illegal", "invalid_input", "unsupported", "decision_required")


def L(locator: str, excerpt: str, source: dict[str, Any] = CORE) -> dict[str, Any]:
    """A locator with the words it rests on. Excerpts are short by design."""
    return {"locator": locator, "excerpt": " ".join(excerpt.split()), **source}


# ---------------------------------------------------------------------------
# Judgement table, keyed by the inventory's clause-text hash.
# ---------------------------------------------------------------------------
CLAUSES: dict[str, dict[str, Any]] = {
    # Disintegrate — "Deal 3 to a unit at battlefield."
    "d3d94631": {
        "targets": True, "decision_point": "at_play",
        "why": "355.5 specific object choice at play; 355.10.b 'at battlefield' is a restriction, the unit is the target",
        "locators": [
            L("Core 355.5", "If a card requires you to specifically choose one or more Game Objects, that choice is made now."),
            L("Core 355.8", "In order to put a spell or ability on the chain, valid choices must be made for all targets."),
            L("Core 355.9.b", "It meets all targeting restrictions. e.g., a unit is a valid target for a spell that refers to a 'unit at a battlefield' only if it meets the appropriate criteria."),
            L("Core 355.10.b", "'Kill a unit at a battlefield' targets a unit, but not a battlefield, because the units are targets and 'at a battlefield' is a restriction."),
            L("Core 359.3.e.5", "If any of the spell's targets are no longer legal, those game objects are unaffected by the spell as it resolves."),
            L("Core 417.1.b", "To Deal Damage to Units, mark the specified amount of Damage on the Unit."),
            L("Core 417.6.a", "If a game effect does not specify a source, the game effect describing the Deal action is the source."),
            L("errata: Disintegrate OGN-005", "Deal 3 to a unit at battlefield. If this kills it, do this: draw 1.", ERRATA),
        ],
        "packets": ["DP-01", "DP-03"],
    },
    # Incinerate — "Deal 2 to a unit at a battlefield."
    "df9db2ea": {
        "targets": True, "decision_point": "at_play",
        "why": "same shape as Disintegrate without the linked instruction",
        "locators": [
            L("Core 355.5", "If a card requires you to specifically choose one or more Game Objects, that choice is made now."),
            L("Core 355.10.b", "'Kill a unit at a battlefield' targets a unit, but not a battlefield."),
            L("Core 359.3.e.2", "A target is illegal as the spell resolves if it no longer meets the targeting requirements of the spell, or if it has changed Zones to or from a Non-Board Zone."),
            L("Core 417.1.b", "To Deal Damage to Units, mark the specified amount of Damage on the Unit."),
        ],
        "packets": ["DP-01", "DP-03"],
    },
    # Flash — "Move up to 2 friendly units to base."
    "7a92a690": {
        "targets": True, "decision_point": "at_play",
        "why": "355.4 move destinations chosen at play; 355.13 'up to' may choose zero; 355.12 each chosen unit is a target",
        "locators": [
            L("Core 355.4", "For Spells and Abilities that Move one or more Units, choose a valid Location as the Move Destination for each Move that will be performed."),
            L("Core 355.4.a", "A valid Location for a Move Effect is one other than the Units' current Location where they are allowed to be present."),
            L("Core 355.13", "If a card specifies that a player chooses 'any number' or 'up to' some number of Game Objects to be affected, they may choose any number of available targets, including zero."),
            L("Core 446.3.c", "Moving does not use the Chain, nor is it able to be Reacted to."),
            L("Core 449.1", "The source of the Move will provide details on any restrictions on legality for Destination."),
            L("Core 453", "When a Move action is complete, perform a Cleanup."),
        ],
        "packets": ["DP-01", "DP-02", "DP-06"],
    },
    # Gust — "Return a unit at a battlefield with 3 Might or less to its owner's hand."
    "e661650e": {
        "targets": True, "decision_point": "at_play",
        "why": "targeted choice with two restrictions; returning to hand is a zone change, not a Move (446.2), and the object becomes new (124)",
        "locators": [
            L("Core 355.9.b", "A unit is a valid target for a spell that refers to a 'unit with Might 4 or greater' only if it meets the appropriate criteria."),
            L("Core 359.3.e.4", "A unit with 3 or less Might is no longer a legal target if it is no longer a unit or if its Might is greater than 3."),
            L("Core 446.2", "A card changing game zones does not in itself constitute a Move."),
            L("Core 124", "A Game Object that changes zones to or from a Non-Board Zone becomes a new object for the purposes of tracking that object."),
            L("Core 124.1", "Whenever a Game Object changes zones to or from a Non-Board Zone, all Temporary Modifications of all kinds cease to be tracked on it."),
            L("Core 056", "Cards a player owns may never be placed into a non-Board zone belonging to another player."),
        ],
        "packets": ["DP-01", "DP-03", "DP-06"],
    },
    # Morbid Return — "Return a unit from your trash to your hand."
    "f3c76e58": {
        "targets": True, "decision_point": "at_play",
        "why": "355.10.a: trash is Public, so a unit card in it is a target (the rule's own example)",
        "locators": [
            L("Core 355.9.a", "e.g., 'Recycle a unit from your trash' targets a unit card in your trash."),
            L("Core 355.10.a", "'Return a unit from your trash to your hand' targets a unit card in your trash, because your trash is Public."),
            L("Core 355.10.a.1", "Public zones are Battlefield Zones, Bases, Trashes, Legend Zones, Champion Zones, and Facedown Zones."),
            L("Core 359.3.e.2", "A target is illegal as the spell resolves if it has changed Zones to or from a Non-Board Zone."),
            L("Core 108.2.c", "Cards in each player's Trash are unordered."),
        ],
        "packets": ["DP-01", "DP-03", "DP-06"],
    },
    # Vision (Mystic Poro, Sai Scout) — keyword; "When this is played, predict."
    "f4a07c4d": {
        "targets": False, "decision_point": "at_resolution",
        "why": "817.1.b Vision is a triggered ability short for 'When this is played, predict'; 436 the recycle choice is made as Predict executes; the top card is Secret (128.3) and does not target (355.10.a)",
        "locators": [
            L("Core 817.1.b", "It is functionally short for 'When this is played, predict.'"),
            L("Core 817.1.c", "The trigger is the permanent entering the Board."),
            L("Core 817.2.a", "The player may choose to recycle or not recycle for each instance of Vision separately."),
            L("Core 436.1", "Predicting a card is the act of looking at a single card from the top of the Main Deck and choosing whether or not to Recycle it."),
            L("Core 436.4", "If a player attempts to Predict more cards than are available in their Main Deck, they will Predict as many as possible instead."),
            L("Core 128.3", "Secret: This level of Privacy indicates that no player may read or look at the face of the card."),
            L("Core 355.5.b", "This does not include making choices for Triggered Abilities of permanents, even if those abilities trigger when the chain item is played."),
        ],
        "packets": ["DP-02", "DP-07"],
    },
    # Gentlemen's Duel — "Give a friendly unit +3 Might this turn."
    "2ed49f33": {
        "targets": True, "decision_point": "at_play",
        "why": "friendly-unit choice at play; duration 'this turn' is R3-A2 but the target is A1",
        "locators": [
            L("Core 355.5", "If a card requires you to specifically choose one or more Game Objects, that choice is made now."),
            L("Core 355.9.b", "A unit is a valid target for a spell that refers to a 'unit you control' only if it meets the appropriate criteria."),
            L("Core 359.3.e.2", "A target is illegal as the spell resolves if it no longer meets the targeting requirements of the spell."),
            L("Core 135.2.e.3", "(Might modifier accounting, as effect_ir already cites for modify_might)"),
        ],
        "packets": ["DP-01", "DP-03"],
    },
    # Gentlemen's Duel — "Then choose an enemy unit."
    "fd48e5d0": {
        "targets": True, "decision_point": "at_play",
        "why": "a second, independent target chosen at play (355.5); 'Then' orders execution, not the choice",
        "locators": [
            L("Core 355.5", "If a card requires you to specifically choose one or more Game Objects, that choice is made now."),
            L("Core 355.16", "A player may not make choices during this step that will deterministically result in illegal choices or actions later in this process unless they have no choice."),
            L("Core 359.3.e.7", "If all of an instruction's Targets become Invalid or Unavailable by the time the spell begins resolving, that instruction will not execute."),
        ],
        "packets": ["DP-01", "DP-03"],
    },
    # Highlander — "Choose a friendly unit."
    "d659b2ba": {
        "targets": True, "decision_point": "at_play",
        "why": "355.10.c's own example: 'Choose a friendly unit. The next time it would die this turn…' targets a friendly unit, because 'choose' is not part of the replacement effect",
        "locators": [
            L("Core 355.10.c", "'Choose a friendly unit. The next time it would die this turn, return it to your hand instead' targets a friendly unit, because 'choose a friendly unit' is not part of the replacement effect."),
            L("Core 355.5", "If a card requires you to specifically choose one or more Game Objects, that choice is made now."),
            L("Core 359.3.e.5", "Any instructions related to an illegal target can't be followed."),
            L("Core 455", "A Recall is when a Permanent is relocated from anywhere to its Base without it being a Move."),
            L("Core 456.1", "They do not cause Triggered Abilities to trigger that are triggered by Move actions."),
            L("errata: Highlander OGS-020", "Choose a friendly unit. The next time it would die this turn, heal it, exhaust it, and recall it instead.", ERRATA),
        ],
        "packets": ["DP-01", "DP-03", "DP-06"],
    },
    # Meditation — "As an additional cost to play this, you may exhaust a friendly unit."
    "6ce549b5": {
        "targets": False, "decision_point": "at_play",
        "why": "355.1.a the choice to pay an optional additional cost is made at play; 355.10.c a cost does not target; 356.2.b/357.2 paid in step 4; 414.4 an exhausted unit cannot pay it",
        "locators": [
            L("Core 355.1.a", "This includes the choice of whether or not to pay an Optional Additional Cost."),
            L("Core 355.10.c", "'As an additional cost to play me, kill a friendly unit' doesn't target anything."),
            L("Core 204.2.a", "Additional Costs must be paid to finalize the spell or ability, in addition to the base cost."),
            L("Core 356.2.b.1", "Optional Costs … must be paid only if the player made the choice to pay them in step 2. They use the phrase 'as an additional cost' and the word 'may.'"),
            L("Core 356.4.f.1", "An optional additional cost was 'paid' if the player made the decision to pay it. It doesn't matter how much the player actually paid."),
            L("Core 357.2", "In addition, pay any non-standard Cost summed in step 3 in any order."),
            L("Core 357.2.a", "Costs that are replaced with other events by replacement effects are still considered paid."),
            L("Core 414.4", "An exhausted friendly unit may not be exhausted again as the additional cost for the spell, and the additional cost has not been paid."),
            L("Core 358.2", "Check that all costs were paid."),
            L("Core 358.5", "If any of the above checks fail, the actions taken in this process are undone and the action is cancelled."),
            L("Core 205", "An instruction that requires a player to pay resources … that does not also have a linked Effect, is not a Cost."),
        ],
        "packets": ["DP-02", "DP-04", "DP-05"],
    },
    # Mobilize — "Channel 1 rune exhausted."
    "3e791d2d": {
        "targets": False, "decision_point": "none",
        "why": "430.1 channel takes the top rune (no choice); 430.2 the effect specifies entry state; 430.3 channel as many as possible",
        "locators": [
            L("Core 430.1", "Channeling is the action of taking one or more Runes from the top of a player's Rune Deck and putting them on the board."),
            L("Core 430.2", "A spell reads 'Channel 1 rune exhausted.' As that spell resolves, its controller puts the top rune of their rune deck onto the board and that rune enters the board exhausted rather than ready."),
            L("Core 430.3", "If there aren't sufficient runes in the Rune Deck, channel as many as possible."),
            L("Core 430.5", "e.g., 'Channel 2 runes exhausted. If you couldn't channel 2 runes this way, draw 1.'"),
            L("Core 161.1.a", "despite remaining on the Board until Recycled or otherwise removed from the board, it is not a Permanent."),
        ],
        "packets": ["DP-05", "DP-08"],
    },
}

PACKETS: list[dict[str, Any]] = [
    {"id": "DP-01", "title": "Which choices are targets, and which are not",
     "question": "Confirm the per-clause targeting classification under 355.7–355.10, and whether a non-targeted choice (355.17, resolution-time) gets its own decision artifact.",
     "rule_text": [L("Core 355.7", "When a card Chooses one or more specific Game Objects to affect, it is Targeted unless indicated otherwise by the rules in this section."),
                   L("Core 355.10.a", "It is in a zone whose information status is not Public. … 'Return a unit from your trash to your hand' targets … because your trash is Public."),
                   L("Core 355.10.c", "It is included only as part of a cost, trigger condition, or replacement effect."),
                   L("Core 355.10.d.2", "This exception does not apply to objects that are the only valid choice at the moment a spell or ability is placed on the chain.")],
     "proposal": "typed selector carries `targeted: true|false` derived from 355.10; targeted selectors are validated at play (355.8) and re-validated at resolution (359.3.e); non-targeted resolution choices become a `play-decisions` entry with stage=resolution.",
     "failure_classification": {"missing selector on a targeted clause at play": "invalid_input", "selector names an object failing 355.9": "illegal", "selector on a zone the engine does not model": "unsupported", "resolution-time choice not yet supplied": "decision_required"}},
    {"id": "DP-02", "title": "When each choice is made: play, resolution, or trigger finalization",
     "question": "Adopt 355.1–355.5/355.17 and 402 as the stage model: optional-additional-cost and spell-target choices at play, triggered-ability targets/performance at trigger finalization, and Predict recycle during resolution. Is one decision artifact with a `stage` field acceptable, or one kind per stage?",
     "rule_text": [L("Core 355.1.a", "This includes the choice of whether or not to pay an Optional Additional Cost."),
                   L("Core 355.5.b", "This does not include making choices for Triggered Abilities of permanents … even if those abilities trigger when the chain item is played."),
                   L("Core 355.17", "If a spell or ability requires one or more players to make choices that are not outlined in this section, they are made on resolution."),
                   L("Core 402.1", "If the first part of a Triggered Ability's effect is 'you may' … its controller decides whether or not to perform the Triggered Ability now."),
                   L("Core 752.2", "This does not refer to any choices made 'as you play this' … or any choices made for Optional Additional Costs.")],
     "proposal": "one `engine-decisions.v1` artifact keyed by chain item, entries {decision_id, stage: play_declaration|trigger_finalization|resolution, kind, controller, options?}; a transition that reaches an unsupplied entry returns decision_required with the entry, never guesses. Vision's recycle choice is resolution-stage, not a 402.1 performance choice.",
     "failure_classification": {"decision for the wrong stage supplied early": "invalid_input", "decision owner mismatch": "illegal", "stage the engine cannot model": "unsupported", "entry absent when reached": "decision_required"}},
    {"id": "DP-03", "title": "Targets that become illegal before or during resolution",
     "question": "Adopt 359.3.e.1–359.3.e.9 as written: resolve anyway; illegal targets unaffected; instruction with all targets invalid does not execute; with some invalid executes on the valid subset; zone change to/from non-board makes a new object (124). How should the trace record a mistarget, and does a linked 'If this kills it' then evaluate false?",
     "rule_text": [L("Core 359.3.e.1", "The spell resolves even if some or all of its targets are illegal."),
                   L("Core 359.3.e.5", "Any instructions related to an illegal target can't be followed. Example: … Void Seeker's controller still draws 1."),
                   L("Core 359.3.e.8", "If an instruction has more than one Target and fewer than all of the Targets become Invalid … the instruction will execute, with only the Targets available and valid being operated on."),
                   L("Core 359.3.e.4", "If a target changes Zones to or from a Non-Board Zone and then returns to its original zone, it is no longer a legal target, because it's not treated as the same object."),
                   L("Core 758.1", "the spell or ability will mistarget on resolution. Any instructions related to that Game Object will be ignored as the spell resolves.")],
     "proposal": "outcome stays `supported`; per-instruction trace outcome `skipped_illegal_target` (all invalid) or `applied_to_subset` (some invalid) with the object ids. Linked instructions use typed predicates: mistargeting makes the prior instruction unexecuted, while 'If this kills it' additionally requires a causally attributed kill after the instruction's Cleanup; plain `if_applied` is insufficient.",
     "failure_classification": {"target invalid at play": "illegal", "target invalid at resolution": "supported (trace: skipped_illegal_target)", "object identity after zone change not tracked by the engine": "unsupported"}},
    {"id": "DP-04", "title": "Costs: atomic payment and the play-level transaction",
     "question": "Is 'play a card' the transaction boundary — costs paid in step 4 (357), legality checked in step 5 (358), everything undone on failure (358.5)? Today the atomic bridge spans timing + one effect program; a play with an optional additional cost and a linked effect needs the same guarantee across cost payment.",
     "rule_text": [L("Core 203.3", "If the game action associated with a Cost is impossible … they cannot pay the Cost and they will not execute the linked Effect."),
                   L("Core 357.2.a", "Costs that are replaced with other events by replacement effects are still considered paid."),
                   L("Core 414.4", "An exhausted friendly unit may not be exhausted again as the additional cost for the spell, and the additional cost has not been paid."),
                   L("Core 358.5", "If any of the above checks fail, the actions taken in this process are undone and the action is cancelled."),
                   L("Core 356.4.f.1", "An optional additional cost was 'paid' if the player made the decision to pay it.")],
     "proposal": "a `play` transaction in the resolution bridge: {decisions, cost_payments[], program}. A cost payment has an explicit cost context and receipt; it may reuse typed operations but is not merely an ordinary effect carrying a boolean flag. Any failed payment/check rolls the entire play back. Optional-cost 'paid' records the declared decision and successful payment semantics, including replacement/reduction rules.",
     "failure_classification": {"cost declared but unpayable": "illegal", "cost decision missing at play": "decision_required", "cost kind not typed": "unsupported", "malformed cost declaration": "invalid_input"}},
    {"id": "DP-05", "title": "'If you do', 'Otherwise', 'If you can't' — dependency vocabulary",
     "question": "The IR has dependency_mode if_applied|always. Meditation needs the negative branch (Otherwise); Mobilize needs 'couldn't fully perform' (430.3 channels as many as possible — is a partial channel a failure for 'If you can't'?). 055 says ignore impossible instructions; 430.5's example ties 'couldn't' to the requested count.",
     "rule_text": [L("Core 055", "When executing card text, do as much as you can, ignoring impossible instructions."),
                   L("Core 430.3", "If there aren't sufficient runes in the Rune Deck, channel as many as possible."),
                   L("Core 430.5", "e.g., 'Channel 2 runes exhausted. If you couldn't channel 2 runes this way, draw 1.'"),
                   L("Core 205", "The later instruction checks whether the game action was performed, not whether a cost was paid."),
                   L("Core 359.3.e.6", "Instructions that can't be followed, either because of illegal targets or other circumstances, are ignored.")],
     "proposal": "record instruction completion as full|partial|none, but use typed predicates rather than one generic `if_not_applied`: action_performed, action_not_performed, requested_count_not_reached, cost_paid, and caused_kill. Mobilize tests actual_count < requested_count; Meditation branches on its optional-cost receipt. ADR-0002: same program major, capability revision.",
     "failure_classification": {"dependency on an unknown effect_id": "invalid_input", "dependency mode not implemented": "unsupported"}},
    {"id": "DP-06", "title": "return, recall, move — three events, not one",
     "question": "Return-to-hand is a zone change (446.2) producing a new object (124); Recall relocates to Base without being a Move (455–456) and keeps damage/statuses (458.1); Move is 420/446 and triggers move abilities. Confirm three distinct event ops with distinct trigger classes, and Highlander's errata ordering (heal, exhaust, recall).",
     "rule_text": [L("Core 446.2", "A card changing game zones does not in itself constitute a Move."),
                   L("Core 124", "A Game Object that changes zones to or from a Non-Board Zone becomes a new object for the purposes of tracking that object."),
                   L("Core 456.1", "They do not cause Triggered Abilities to trigger that are triggered by Move actions."),
                   L("Core 458.1", "Unless otherwise stated by the source of the Recall, Damage and statuses of a permanent will all remain unaffected by a Recall."),
                   L("Core 056.2", "If a card would enter such a zone, it goes to its owner's corresponding zone instead."),
                   L("errata: Highlander OGS-020", "heal it, exhaust it, and recall it instead.", ERRATA)],
     "proposal": "new ops `return_to_hand` (board→owner's hand, new object identity, temporary modifications dropped per 124.1) and `recall` (to the permanent's current controller's base, not a Move, damage/status retained unless its source changes them), alongside existing `move_board_object`; trigger emission is keyed by event kind so Move triggers never fire on Recall.",
     "failure_classification": {"return of an object not on the board": "illegal", "recall destination not the controller's base": "invalid_input", "hand zone semantics beyond add-to-hand": "unsupported"}},
    {"id": "DP-07", "title": "Look / Predict and the information boundary",
     "question": "Predict (436) lets a player look at a Secret card and choose to recycle it. The looked-at card becomes own-private knowledge. Under ADR-0003, how does an observation record it, and may a player2 query ever contain player1's predicted card? (424.2.b: voluntarily showing private information is not a Reveal.)",
     "rule_text": [L("Core 436.1", "Predicting a card is the act of looking at a single card from the top of the Main Deck and choosing whether or not to Recycle it."),
                   L("Core 128.3", "Secret: … no player may read or look at the face of the card."),
                   L("Core 128.4", "Private: … only the controller of a card on the board or the owner of a card in any other zone may read or look at the face of the card."),
                   L("Core 424.2.b", "a player may choose to show Private information to one or more other players. This does not count as revealing.")],
     "proposal": "a `look` event yields an own-private fact {fact_id, zone, position, card_id?} in observation.v1 for the looking player only; the recycle choice is a resolution-stage decision (DP-02); P2-A's forbidden-key list gains `player1_predicted`/`opponent_predicted`.",
     "failure_classification": {"look on an empty deck": "supported (436.4: predict as many as possible)", "predicted card appearing in the other player's observation": "invalid_input (perspective violation)"}},
    {"id": "DP-08", "title": "Channel: a rune entering the board with an entry state",
     "question": "Channel moves the top rune from Rune Deck to the board (430.1) with an entry state the effect may specify (430.2). Is this a new op `channel_rune` reusing play_token's `event_modifiers.entry_state` vocabulary (375), and is the rune's arrival a zone change (new object) or a move?",
     "rule_text": [L("Core 430.1", "Channeling is the action of taking one or more Runes from the top of a player's Rune Deck and putting them on the board."),
                   L("Core 430.2.a", "By default, runes are channeled readied."),
                   L("Core 161.1.a", "it is not a Permanent."),
                   L("Core 164.2", "A Basic Rune always has the following two Abilities")],
     "proposal": "new op `channel_rune` {player, count, entry_state} — takes from rune_deck top, appends to base, sets exhausted per entry_state, records applied count for DP-05; rune identity preserved (Rune Deck is a zone the state already models).",
     "failure_classification": {"rune deck empty": "supported (applied: none/partial per 430.3)", "entry state other than ready|exhausted": "invalid_input"}},
    {"id": "DP-09", "title": "Versioning under ADR-0002",
     "question": "Everything above adds operations and one decision artifact; nothing changes an existing field's meaning. Confirm: effect-program stays v1 with a capability revision; `engine-decisions.v1` is a new decision schema; effect-state gains optional zone contents only through an additive state capability.",
     "rule_text": [L("ADR-0002 change table", "Add a new operation that old programs never invoke → same program major may remain; capability revision required.", {"source_id": "ADR-0002", "version": "2026-09-02", "kind": "decision"})],
     "proposal": "as stated; the capability manifest picks up the new ops automatically (C-09) and the R5-A report shows their fixture coverage (C-11).",
     "failure_classification": {}},
    {"id": "DP-10", "title": "Failure vocabulary for R3-A1 (bullet 12 of X-09)",
     "question": "Adopt one table for the whole batch so cards do not each invent a classification.",
     "rule_text": [],
     "proposal": "illegal = a supported rule rejects it (355.9, 414.4, 203.3); invalid_input = the artifact is malformed or a required decision was supplied at the wrong stage; unsupported = the engine lacks the semantics (named mechanic); decision_required = a listed decision is unsupplied when reached. Resolution-time mistargets are supported with a trace outcome, per DP-03.",
     "failure_classification": {}},
    {"id": "DP-11", "title": "The English Origins FAQ is locally captured as historical evidence",
     "question": "The official Origins FAQ is an HTML page whose own warning defers to newer rules. How should it be retained without overriding Core 2026-07-16?",
     "rule_text": [],
     "proposal": "capture the official HTML in supplemental-en, hash and index it locally, mark it superseded by Core 2026-07-16, exclude it from default search, and expose it only through explicit historical search. R3-A1 rulings cite current Core/errata; the FAQ is rationale, not controlling authority.",
     "failure_classification": {}},
]


def _load_inventory() -> dict[str, Any]:
    return json.loads(INVENTORY_LEDGER.read_text(encoding="utf-8"))


def _base_state():
    spec = importlib.util.spec_from_file_location("check_effect_ir", SCRIPT_DIR / "check_effect_ir.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.base_state()


def _fixtures_for(card: str, clause: dict[str, Any], judgement: dict[str, Any]) -> list[dict[str, Any]]:
    """Four sketches per clause. No expected outcome — the shape has no field for one."""
    base = {
        "card": card, "clause_id": clause["clause_id"], "clause_text": clause["text"],
        "required_mechanics": clause["mechanics"], "implemented_ops_involved": clause["implemented_ops"],
        "decision_point": judgement["decision_point"], "targets": judgement["targets"],
        "locators": [x["locator"] for x in judgement["locators"]], "packets": judgement["packets"],
        "state_sketch": {"from": "check_effect_ir.base_state()", "objects": {"u1": "p1 unit, 3 Might, 1 damage, base", "u2": "p2 unit, 4 Might, exhausted, base", "c3": "p1 spell in trash", "r1": "p1 rune in rune_deck", "bf1": "battlefield, uncontrolled, empty"}},
        "actor": "p1",
    }
    kinds = {
        "positive": "the clause's choice/cost/zone action is well-formed and every rule it cites is satisfied",
        "negative": "a supported rule rejects it (355.9 restriction unmet, 414.4 cost unpayable, 203.3 impossible cost)",
        "missing_information": "a required decision or fact is absent when reached — the transition must stop with decision_required or invalid_input, never guess",
        "target_invalidated": "the chosen object stops meeting 355.9 or changes zone (359.3.e.2) between play and resolution",
    }
    setup = {
        "d3d94631": {"positive": "move u2 to bf1; p1 chooses u2", "negative": "p1 chooses u2 while u2 is at base (not 'at battlefield')", "missing_information": "no selector supplied for the unit", "target_invalidated": "u2 chosen at bf1, then recalled to base before resolution"},
        "df9db2ea": {"positive": "move u2 to bf1; p1 chooses u2", "negative": "p1 chooses c3 (a card in trash, not a unit on the board)", "missing_information": "selector present but names no object", "target_invalidated": "u2 chosen at bf1, then returned to hand (zone change → new object)"},
        "7a92a690": {"positive": "move u1 to bf1; p1 chooses [u1] with destination base", "negative": "destination equals current location (355.4.a)", "missing_information": "destination omitted", "target_invalidated": "u1 chosen at bf1, then killed before resolution; 'up to 2' with zero valid → instruction does not execute (359.3.e.7)"},
        "e661650e": {"positive": "move u1 (3 Might) to bf1; p1 chooses u1", "negative": "p1 chooses u2 (4 Might > 3)", "missing_information": "u1's Might unknown in observation", "target_invalidated": "u1 chosen, then given +1 Might in reaction (359.3.e.4 example)"},
        "f3c76e58": {"positive": "p1 chooses c3 from trash (trash is Public, 355.10.a)", "negative": "p1 chooses c1 (in deck, not trash)", "missing_information": "trash contents not in observation", "target_invalidated": "c3 recycled out of trash before resolution (zone change → new object)"},
        "f4a07c4d": {"positive": "unit played; Vision triggers; p1 looks at c1 and decides recycle/keep at trigger finalization", "negative": "recycle decision supplied at play time (wrong stage, 355.5.b)", "missing_information": "recycle decision absent when the trigger resolves → decision_required", "target_invalidated": "not applicable: Predict targets nothing (355.10.a, deck is Secret); recorded as n/a"},
        "2ed49f33": {"positive": "p1 chooses u1 (friendly)", "negative": "p1 chooses u2 (enemy)", "missing_information": "selector missing", "target_invalidated": "u1 chosen, then returned to hand before resolution"},
        "fd48e5d0": {"positive": "p1 chooses u2 (enemy) as the second target", "negative": "p1 chooses u1 for both targets (355.16 deterministically illegal later)", "missing_information": "second selector missing", "target_invalidated": "u2 chosen, then killed before resolution → 'They deal damage…' does not execute (359.3.e.7)"},
        "d659b2ba": {"positive": "p1 chooses u1", "negative": "p1 chooses u2 (not friendly)", "missing_information": "selector missing", "target_invalidated": "u1 chosen, then returned to hand → replacement never attaches (359.3.e.5)"},
        "6ce549b5": {"positive": "p1 declares pay at play (355.1.a) naming u1 (ready); step 4 exhausts u1; 'paid' flag set", "negative": "p1 declares pay naming u2-like exhausted friendly unit → 414.4 unpaid → 358.5 undo", "missing_information": "pay/decline decision absent at play → decision_required", "target_invalidated": "not applicable: a cost does not target (355.10.c); recorded as n/a"},
        "3e791d2d": {"positive": "rune_deck [r1]; channel 1 exhausted → r1 enters base exhausted", "negative": "entry_state 'stunned' (not ready|exhausted) → invalid_input", "missing_information": "rune_deck contents unknown in observation", "target_invalidated": "not applicable: no target; rune_deck empty → applied none (430.3) — feeds DP-05"},
    }
    out = []
    for kind in FIXTURE_KINDS:
        out.append({**base, "kind": kind, "intent": kinds[kind], "setup": setup[clause["clause_id"].split("#")[1]][kind]})
    return out


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
    inv = _load_inventory()
    a1_cards = set(inv["cards_by_unblocking_batch"][BATCH])
    ledger_cards = []
    fixtures: list[dict[str, Any]] = []
    for card in inv["cards"]:
        if card["canonical_name"] not in a1_cards:
            continue
        entry = {"card": card["canonical_name"], "type": card["type"], "printing": card["printing_read"], "stale": card["snapshot_is_pre_errata"], "clauses": []}
        for cl in card["clauses"]:
            if cl["unblocked_by"] != BATCH:
                continue
            h = cl["clause_id"].split("#")[1]
            if h not in CLAUSES:
                raise SystemExit(f"no judgement for {card['canonical_name']} clause {h!r}: {cl['text']!r} — the wording changed or a card was added; review before rebuilding")
            j = CLAUSES[h]
            entry["clauses"].append({
                "clause_id": cl["clause_id"], "text": cl["text"], "required_mechanics": cl["mechanics"], "implemented_ops": cl["implemented_ops"],
                "targets": j["targets"], "decision_point": j["decision_point"], "rationale": j["why"], "locators": j["locators"], "packets": j["packets"],
            })
            fixtures.extend(_fixtures_for(card["canonical_name"], cl, j))
        ledger_cards.append(entry)
    ledger_cards.sort(key=lambda c: c["card"])
    fixtures.sort(key=lambda f: (f["card"], f["clause_id"], FIXTURE_KINDS.index(f["kind"])))

    ledger = {
        "schema_version": "r3a1-clause-ledger.v1", "batch": BATCH, "package": "C-13", "inventory_manifest_id": inv["manifest_id"],
        "sources": {"core": CORE, "errata": ERRATA, "faq": FAQ},
        "not_claimed": ["expected resolution results", "programs", "new effect ops", "schema changes", "any ruling — every judgement here is input to X-09"],
        "counts": {"cards": len(ledger_cards), "clauses": sum(len(c["clauses"]) for c in ledger_cards), "fixture_drafts": len(fixtures), "packets": len(PACKETS),
                   "targeted_clauses": sum(1 for c in ledger_cards for cl in c["clauses"] if cl["targets"]),
                   "decision_points": {dp: sum(1 for c in ledger_cards for cl in c["clauses"] if cl["decision_point"] == dp) for dp in DECISION_POINTS}},
        "cards": ledger_cards,
    }
    drafts = {"schema_version": "r3a1-fixture-drafts.v1", "batch": BATCH, "package": "C-13",
              "shape_note": "There is no expected_outcome, expected_state, or program field, by rule. Promotion to executable fixtures is C-14..C-16 work after X-09.",
              "kinds": list(FIXTURE_KINDS), "drafts": fixtures}
    packets = {"schema_version": "r3a1-decision-packets.v1", "batch": BATCH, "package": "C-13", "owner": "Codex (X-09)",
               "failure_kinds": list(FAILURE_KINDS), "packets": PACKETS}
    for doc in (ledger, drafts, packets):
        doc["content_hash"] = "sha256:" + hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ledger, drafts, packets, render_ledger_md(ledger), render_packets_md(packets, ledger)


def render_ledger_md(ledger: dict[str, Any]) -> str:
    c = ledger["counts"]
    out = ["# R3-A1 clause ledger — choices, costs, zones", "",
           f"Package C-13. {c['cards']} cards, {c['clauses']} clauses, {c['fixture_drafts']} fixture drafts, {c['packets']} decision packets. "
           f"{c['targeted_clauses']} clauses target under Core 355.10; decision points: {c['decision_points']}.", "",
           f"Sources: Core Rules {CORE['version']} (installed locally, quoted); Origins errata {ERRATA['version']}; Origins FAQ {FAQ['version']} is locally captured as **superseded historical evidence** and excluded from default queries (DP-11).", "",
           "Nothing here is a ruling. Every classification is input to X-09; every fixture draft omits the expected result by construction.", ""]
    for card in ledger["cards"]:
        out.append(f"## {card['card']} — {card['type']} · `{card['printing']}`" + (" · stale snapshot" if card["stale"] else ""))
        for cl in card["clauses"]:
            out.append(f"### `{cl['clause_id'].split('#')[1]}` {cl['text']}")
            out.append(f"- targets: **{'yes' if cl['targets'] else 'no'}** · decision point: **{cl['decision_point']}** · needs: {', '.join(cl['required_mechanics']) or '—'} · ops: {', '.join(cl['implemented_ops']) or '—'} · packets: {', '.join(cl['packets'])}")
            out.append(f"- why: {cl['rationale']}")
            for loc in cl["locators"]:
                out.append(f"  - `{loc['locator']}` — {loc['excerpt']}")
            out.append("")
    return "\n".join(out)


def render_packets_md(packets: dict[str, Any], ledger: dict[str, Any]) -> str:
    by_packet: dict[str, list[str]] = {}
    for card in ledger["cards"]:
        for cl in card["clauses"]:
            for p in cl["packets"]:
                by_packet.setdefault(p, []).append(f"{card['card']} `{cl['clause_id'].split('#')[1]}`")
    out = ["# Decision packets for X-09 (R3-A1 choices / costs / zones)", "",
           "Each packet is one question Codex can rule on once for every card it blocks. Rule text is quoted from the installed Core Rules; the proposal is Claude's, offered for the ruling to accept, amend, or reject. Failure classifications use the engine-check outcome vocabulary.", ""]
    for p in packets["packets"]:
        out += [f"## {p['id']} — {p['title']}", "", f"**Blocks:** {', '.join(by_packet.get(p['id'], ['(cross-cutting)']))}", "", f"**Question.** {p['question']}", ""]
        if p["rule_text"]:
            out.append("**Rule text.**")
            for r in p["rule_text"]:
                out.append(f"- `{r['locator']}` — {r['excerpt']}")
            out.append("")
        out += [f"**Proposal.** {p['proposal']}", ""]
        if p["failure_classification"]:
            out.append("| Situation | Proposed outcome |"); out.append("| --- | --- |")
            for k, v in p["failure_classification"].items():
                out.append(f"| {k} | `{v}` |")
            out.append("")
    return "\n".join(out)


def outputs() -> dict[Path, str]:
    ledger, drafts, packets, ledger_md, packets_md = build()
    dump = lambda d: json.dumps(d, ensure_ascii=False, indent=2) + "\n"  # noqa: E731
    return {PACK / "r3a1_clause_ledger.json": dump(ledger), PACK / "r3a1_fixture_drafts.json": dump(drafts), PACK / "decision_packets.json": dump(packets),
            PACK / "R3A1_LEDGER.md": ledger_md, PACK / "DECISION_PACKETS.md": packets_md}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outs = outputs()
    if args.check:
        stale = [p.name for p, text in outs.items() if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != text]
        if stale:
            print(f"FAILED: stale R3-A1 outputs {stale}; re-run build_r3a1_ledger.py and commit the diff", file=sys.stderr)
            return 1
        print("OK: R3-A1 ledger, fixture drafts and decision packets match the inventory")
        return 0
    for p, text in outs.items():
        p.write_text(text, encoding="utf-8")
    print(f"wrote {len(outs)} files to {PACK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
