#!/usr/bin/env python3
"""Chronicle-owned typed effect IR and bounded atomic interpreter.

R2 intentionally supports a small official-action vocabulary. Card definitions
compose these operations; the interpreter contains no card-name conditionals.
Unsupported actions fail closed and never fall back to natural-language guesses.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
import contextlib as _contextlib
import contextvars as _contextvars


STATE_VERSION = "riftbound-effect-state.v1"
PROGRAM_VERSION = "riftbound-effect-program.v1"
# 2026-10-14 package 12 (GPT's review, point 1): `ruleset.core` names the Core Rules whose BEHAVIOUR this engine
# executes - 2026-10-09, in effect 2026-10-16 - and nothing else. A state, program or decision labelled with another
# Core is refused, so an older label never runs the newer behaviour (check_semantics_version.py). The rule locators the
# engine cites are still numbered by the 2026-07-16 document until C3: RULE_NUMBERING, carried as its own field
# wherever locators reach a consumer (engine_check.rule_numbering, the capability manifest), never inside `ruleset`.
CORE_RULESET = "2026-10-09"
CORE_EFFECTIVE = "2026-10-16"
RULE_NUMBERING = "2026-07-16"
FAQ_AS_OF = "2026-08-14"
# 2026-10-15 package 13 (C2): the six Domains a Power is of (Core 805) - the names the resource pools use; a cost that
# lets the payer name a Domain ([A]) ranges over these
DOMAINS = ("body", "calm", "chaos", "fury", "mind", "order")
PLAYER_ZONES = {"main_deck", "hand", "trash", "banishment", "base", "rune_deck"}
# ADR-0012 §5: the Legend and Champion zones are public, are not Locations,
# and only appear in states that use them (Core 107.4.d, 108.3).
OPTIONAL_PLAYER_ZONES = {"legend_zone", "champion_zone"}
# ADR-0007 §3: compiled permissions that widen the valid play locations (355.2.b).
# ADR-0012 §2: Ambush (822.1) lets a Unit be played to a Battlefield where
# its controller has Units, with Reaction while it is being played there.
# DP-95 / Core 355.2.b: each way a card widens where it may enter, named.
# occupied_enemy_battlefield reads 170.11.a ("occupied" = a Unit is there) and
# the controller relation the card's own words already give.
PLAY_PERMISSIONS = {"open_battlefield", "ambush", "occupied_enemy_battlefield"}
# 2026-09-27 package 5 (Miss Fortune - Buccaneer, "Friendly units may be played to open
# battlefields."): a permission a permanent GRANTS, while it is on the board, to the unit cards its
# controller's side plays - one shape, closed: {permission: open_battlefield, kind: unit,
# controller_relation: friendly} (Core 355.2.b, 170.11.c).
GRANTED_PLAY_PERMISSION_SHAPES = [{"permission": "open_battlefield", "kind": "unit", "controller_relation": "friendly"}]
# Which of those a card gets from a *sentence* rather than from a bracketed
# keyword. [Ambush] is printed on the card and belongs in the keyword
# catalogue; "You may play me to an open / occupied enemy battlefield" is a
# sentence the grammar reads, and the permission is the engine's name for what
# it grants. Every new permission is classified here on purpose - the
# distinction is about the card frame, which no code fact can answer.
SENTENCE_PLAY_PERMISSIONS = {"open_battlefield", "occupied_enemy_battlefield"}
# ADR-0011 §4: what a restricted Add resource may be spent on ("Spend this Energy only to play spells").
RESOURCE_USES = ("play_spell", "play_unit", "play_gear", "activate_unit_ability", "activate_gear_ability")
# Keywords the state may carry on an object. `deflect` (Core 809) imposes a
# mandatory any-domain Power cost on opponents' spells that choose the object.
# ADR-0008 §5: Shield, Tank, Ganking (and Backline, required by the Tank
# contract) are characteristics printed on the object.
# Core 808 (last paragraph): Deathknell is a characteristic of the permanent,
# one other Game Effects can look at, so it is carried
# like any other keyword; its behaviour is the object's death triggers.
# Core 805 (last lines) does the same for Accelerate: it is a characteristic
# that may be checked, even though it only has a function while playing.
OBJECT_KEYWORDS = {"temporary", "deflect", "shield", "tank", "ganking", "backline", "deathknell", "accelerate", "assault", "legion", "vision"}
# Keywords with a value summed across sources: Shield (814.1.b, 814.2) and Assault
# (807.1.b, 807.2). An omitted X is 1 for both.
VALUED_KEYWORDS = {"shield", "assault"}
# ADR-0013 §1-2: one canonical representation for every continuous effect, and
# the Core 476-480 layer engine over it. The six legacy families are translated
# by `migrate_legacy_effects` at the input boundary; nothing at runtime reads
# them, so nothing is counted twice.
CONTINUOUS_KINDS = {"might_set", "might_arithmetic", "keyword_grant", "keyword_remove", "bonus_damage", "ability_append", "copy_traits"}
CONTINUOUS_LAYERS = ("trait", "ability", "arithmetic")  # Core 477.1, 477.2, 477.3
KIND_LAYER = {"might_set": "trait", "keyword_grant": "ability", "keyword_remove": "ability",
              "might_arithmetic": "arithmetic", "bonus_damage": "arithmetic",
              "ability_append": "ability", "copy_traits": "trait"}
# ADR-0013 §6 / Core 477.2: the typed abilities an Effect Text or a copy can
# append to another object. These are exactly the printed trigger lists.
APPENDABLE_TRIGGER_FIELDS = ("death_triggers", "play_triggers", "move_triggers", "attack_triggers", "defend_triggers",
                             "conquer_triggers", "hold_triggers", "beginning_phase_triggers", "main_phase_triggers",
                             "end_of_turn_triggers", "event_triggers",
                             # 2026-10-12 package 11 (Treasure Trove: "When this leaves the board, ...")
                             "leave_board_triggers")
COPYABLE_TRAITS = {"type", "rules_text"}

CONTINUOUS_DURATIONS = {"permanent", "this_turn", "this_combat", "while_source_active", "until_detached"}
MIGHT_MODES = {"delta", "increase_to"}
# ADR-0010 §6 / Core 484-489: the Modes of Play the state may name. One set,
# read here and by the state builder; a caller that restated it would drift.
SANCTIONED_MODES = frozenset({"duel", "match", "skirmish", "war", "magma_chamber"})
LEGACY_EFFECT_FIELDS = ("might_modifiers", "keyword_modifiers", "might_auras", "damage_modifiers")
# 2026-10-15 package 13 (C2): a card's own printed Might statics, read live from the object while it is on the Board
# (printed_aura_effects) - never migrated, so one played after the game began has them (Core 365.1)
PRINTED_MIGHT_FIELDS = ("conditional_might", "dynamic_might")
# "My Might is increased by your points." (Draven - Showboat): the amounts a passive
# arithmetic effect may read off the board each time it is computed (477.3.b: a
# passive source is not snapshotted). 2026-09-27: "for each buffed friendly unit at my
# battlefield" (a count of Units with a Buff counter, the source included, at the
# Battlefield the source is at - none while it is in a Base) and "the number of cards in
# your trash" (a public zone, 108.2.b).
MIGHT_PER_KINDS = {"controller_points", "buffed_friendly_units_at_source_battlefield", "controller_trash_count"}
COMBAT_ROLES = {"attacker", "defender"}
# ADR-0007 §6–8.
# DP-94 / Core 423: a Stun lasts the turn, so the Expiration Step is what
# ends it. `stunned` on the object stays as the readable status, but the entry
# here is what owns its lifetime - a status with no owner never comes off.
TURN_EFFECT_KINDS = {"entry_state_for_played_units", "stunned_unit", "cards_play_prohibited",
                     # 2026-09-27, Core 390.4 / 391 delayed passives that apply to the NEXT card
                     # played this turn and are then spent: "the next spell you play this turn
                     # costs [N] less" (Raging Firebrand; value = the Energy discount, read by the
                     # play transaction's cost step, 356.4) and "the next unit you play this turn
                     # enters ready" (Sun Disc; bound to that play as an entry replacement, 369.3)
                     "next_spell_cost_reduction", "entry_state_for_next_played_unit",
                     # 2026-10-06 package 9 (Ravenborn Tome): "the next spell you play this turn deals N Bonus
                     # Damage" - value N; spent by that play, it becomes a Bonus Damage bound to the spell (713)
                     "next_spell_bonus_damage",
                     # 2026-10-08 package 10 (Stand United: "Buffs give an additional +1 [M] to friendly units this
                     # turn."): value N - for the rest of the turn each buff on a unit of the granting player's side adds
                     # N more Might (Core 703: a buff adds +1), read live; it expires with the turn (317.2.c)
                     "buff_bonus_might",
                     # 2026-10-08 package 10 (Guerilla Warfare: "You can hide cards ignoring costs this turn."): for the
                     # rest of the turn the granting player's Hide actions may be taken with their cost ignored (value all)
                     "hide_ignoring_costs"}
# The values a granted turn effect may carry, per kind. 2026-09-27 package 5 (Brynhir Thundersong,
# "opponents can't play cards this turn"): cards_play_prohibited forbids the granting player's
# opponents to play cards - Main Deck cards (Core 052), not activated abilities - for the rest of
# the turn it is granted in; Can't beats Can (054.1). It expires with that turn (317.2.c).
TURN_EFFECT_VALUES = {"entry_state_for_played_units": {"ready", "exhausted"}, "cards_play_prohibited": {"opponents"},
                      "hide_ignoring_costs": {"all"}}
# what each kind's `value` may be; a kind not listed here takes ready | exhausted
NEXT_CARD_TURN_EFFECT_KINDS = {"next_spell_cost_reduction": "spell", "entry_state_for_next_played_unit": "unit",
                               "next_spell_bonus_damage": "spell"}
# ADR-0008 §5: attacking_or_defending_alone reads the Unit's own designation
# and company (740.2.a); friendly_unit_defends_alone is the bounded external
# aura of the Master Yi Legend clause, carried by a might_auras entry.
# 2026-09-27: is_buffed ("While I'm buffed, I have an additional +1 [M].") reads the Unit's
# own Buff counter (702.2.a).
CONDITION_KINDS = {"runes_at_least", "attacking_or_defending_alone", "is_buffed"}
AURA_CONDITION_KINDS = {"friendly_unit_defends_alone"}
# 2026-09-27: a printed keyword that the card has only under a condition (Core 364.3.a):
# "While I'm buffed, I have [Ganking].", "If you've discarded a card this turn, I have
# [Assault] and [Ganking].", "While I'm [Mighty], I have [Deflect], [Ganking], and [Shield]."
# Read live off the object (like static_auras), a keyword_grant in the Ability layer whose
# condition is evaluated there (476.2, 476.3). might_at_least on the card itself is read from
# the layer result in progress, never through effective_might (which would recurse).
CONDITIONAL_KEYWORD_CONDITIONS = {"is_buffed", "might_at_least", "cards_discarded_this_turn_at_least"}
# 2026-09-27: the conditions a printed "If ..., I enter ready." reads as the unit enters (369.3)
ENTRY_CONDITION_KINDS = {"score_within_of_victory", "controls_a_battlefield"}
# 2026-09-27: the keywords a printed static aura may give ("Units here have [Ganking].",
# "Other friendly units here have [Assault].", "Other friendly units have [Vision].") and a
# conditional printed keyword may carry. Each is read from the computed characteristics by
# whatever uses it (standard_move, assault_total, shield_total, vision_triggers,
# play_transaction.deflect_costs, combat's Tank assignment).
STATIC_AURA_KEYWORDS = {"ganking", "assault", "shield", "vision", "deflect", "tank"}
# the keywords whose value is summed across every instance (807.2, 809.2, 814.2); an omitted
# value is 1 (807.1.b.3, 809.1.b.3, 814.1.b.3)
SUMMED_VALUE_KEYWORDS = {"assault", "shield", "deflect"}
# "assault" (2026-09-27, Cleave: "Give a unit [Assault 3] this turn."): a granted Assault is
# summed with any other (Core 807.2 - its own example is Cleave on a unit that has Assault)
# and adds Might only while the Unit is an Attacker (807.1.c); the grant path already carried
# the value for every VALUED_KEYWORDS entry, the list was the only thing refusing it.
GRANTABLE_KEYWORDS = {"shield", "tank", "ganking", "backline", "assault", "temporary"}
# 2026-09-27 (Fading Memories): Temporary is present on Permanents (Core 816.1.a) - a Unit OR a Gear
# may be granted it; every other keyword here is still granted to Units only
PERMANENT_GRANTABLE_KEYWORDS = {"temporary"}
# a grant that states no duration lasts as long as the object stays on the board (Core 801.3.a.3):
# "permanent", bound to the identity it was granted to (124). Only for the keywords listed.
UNTIMED_GRANTABLE_KEYWORDS = {"temporary"}
KEYWORD_MODIFIER_DURATIONS = {"this_combat", "this_turn"}
GRANT_DURATIONS = KEYWORD_MODIFIER_DURATIONS | {"permanent"}
# Core 812.1.c: a Legion ability is active once its controller has Finalized another card
# this turn. On a trigger it is only read where "When you play me" triggers are collected.
# "moved_to_battlefield" (2026-09-24, "When I move to a battlefield"): read only on a move
# trigger, against the completed Move's destination
# "controls_facedown_card_at_battlefield" (2026-09-27, Mushroom Pouch: "At the start of your Beginning Phase, if
# you control a facedown card at a battlefield, draw 1."): the conditional statement right after the
# trigger condition is part of it (Core 383.2.a.1), read when the Beginning Step schedules - a facedown
# card (355.9.a.3) its controller controls in any Battlefield's Facedown Zone (107.3.f, 128.4)
TRIGGER_CONDITION_KINDS = {"at_battlefield", "another_card_finalized_this_turn", "moved_to_battlefield",
                           "controls_facedown_card_at_battlefield",
                           # 2026-09-27 package 6 (Poro Herder): "When you play me, if you control a
                           # Poro, ..." - read as the play completes (Core 383.2.a.1)
                           "controls_units",
                           # 2026-10-08 package 10 (Clockwork Keeper): "When you play me, if you paid the
                           # additional cost, ..." - the play's own receipt, read as the play completes
                           "paid_additional_cost",
                           # 2026-10-12 package 11 (Blitzcrank - Impassive): "When you play me to a battlefield" -
                           # the play put the card at a Battlefield, not its Base; read as the play completes
                           "played_to_battlefield",
                           # 2026-10-14 package 12 (Tryndamere - Barbarian): "When I conquer after an attack, if you
                           # assigned N or more excess damage to enemy units" - read off the Combat that ended in the
                           # conquer (battlefield_control.assigned_excess)
                           "assigned_excess_after_attack"}
DEFAULT_TURN_ID = "turn-0"
# 2026-10-12 package 11 (Symbol of the Solari): a permanent's printed replacement of a tied combat's result (Core 466.3.d)
# - every unit still at that Battlefield recalled - while its controller is the combat's attacker
COMBAT_TIE_RECALL_ALL = {"mode": "recall_all_units", "when": "controller_is_attacker"}
# ADR-0005 §5 named predicates. Only the cost pair is implemented; the rest are
# reserved so C-17 does not bump the program major.
# "state_holds" (2026-09-25, Jinx - Loose Cannon: "draw 1 if you have one or fewer cards in your
# hand"): a typed condition.v1 read from the state when the instruction executes, from its
# controller's perspective - not a link to an earlier instruction
PREDICATE_KINDS = ("cost_paid", "cost_not_paid", "action_performed", "action_not_performed", "requested_count_not_reached", "caused_kill", "sole_controlled_unit_at_referent_location", "state_holds",
                   # 2026-10-08 package 10 (Solari Chief: "If it is stunned, kill it. Otherwise, stun it."): a condition on
                   # this instruction's own target, read as it executes (Core 359.3.d); and "Otherwise" as the earlier
                   # instruction's CONDITION not having held - not whether its action was performed
                   "target_state_holds", "predicate_not_met")
IMPLEMENTED_PREDICATES = {"cost_paid", "cost_not_paid", "action_performed", "action_not_performed", "requested_count_not_reached", "sole_controlled_unit_at_referent_location", "state_holds",
                          "target_state_holds", "predicate_not_met"}
# the states a target_state_holds condition may read off its target (package 10)
TARGET_STATE_CONDITIONS = {"is_stunned"}
# Outcomes in which the *original* game action happened. A partly prevented
# deal still happened (359.3.e.14.c); a wholly prevented or replaced one did
# not (359.3.e.14.b, 205). `caused_kill` is not an in-program predicate: a
# kill by Cleanup is only known after the spell has left the chain (428.5.c),
# so it lives on `conditional_triggers` and is evaluated by the resolution
# bridge.
PERFORMED_OUTCOMES = {"applied", "replaced_modified_applied", "augmented_applied"}
# Instructions that carry a requested/applied count contract; only these may be
# referenced by requested_count_not_reached (Codex Round B, point 4).
COUNT_CONTRACT_OPS = {"channel_rune"}
# Core 441.1.a: Empowered is binary, and 441.1.b/c stop a second Empower - but
# 441.1.c.1 lets a card grant permission to be Empowered several times, and a
# card that does say so ("I can be Empowered up to three times") needs the
# engine to count. `empowered` stays the binary state those rules describe;
# `empowered_count` is how many times it has been Empowered and only matters
# when `empower_limit` is above the default of one.
# Core 355.6: a replacement worded "a spell or ability that CHOOSES me" must
# know whether the incoming effect chose this object at all. An effect that
# reaches an object through a back-reference - "move an enemy unit … then stun
# IT" - never chose it, so such a replacement does not apply. The field is
# explicit rather than guessed from the presence of a target: a program that
# does not say is treated as not having chosen, which is the fail-closed side.
CHOSEN_FIELD = "chosen"
# The replacement's side of the same question.
REQUIRES_CHOSEN_FIELD = "requires_chosen"
# Core 477: a Might change is a decrease or an increase, and a card may answer
# to only one of them - "if a spell or ability would give me -Might". The op is
# the same either way, so a replacement that matched on the op alone fired on
# a buff too. Optional, and only meaningful on a modify_might replacement.
MIGHT_DIRECTION_FIELD = "event_might_direction"
MIGHT_DIRECTIONS = {"decrease", "increase"}
# Core 828.1.b.1 / 828.1.c: "[Empowered][>] [Text]" grants [Text] for as long as
# this card has the Empowered status, and the Dependent Ability is
# active only as long as that status lasts. A Replacement Effect written this
# way is therefore not merely source-backed: losing the status turns it off
# without the source leaving the board.
DEPENDENT_ON_EMPOWERED_FIELD = "requires_source_empowered"
# Core 370.1.a: an event is what one Game Action or one state change produces,
# at a single instant. An action that changes nothing produces no event, so there
# is nothing for a Replacement Effect to replace: a Might change floored to
# zero, or a Stun on a Unit that is already Stunned.
ZERO_MAGNITUDE_OPS = {"modify_might"}
EMPOWER_LIMIT_FIELD = "empower_limit"
EMPOWER_COUNT_FIELD = "empowered_count"
DEFAULT_EMPOWER_LIMIT = 1
CONDITIONAL_TRIGGER_KINDS = {"caused_kill",
                             # 2026-10-12 (package 11, Dragon's Rage: "Move an enemy unit. Then do this: ..."): a
                             # Reflexive Trigger with no condition is always added (Core 387.2), once the instruction
                             # it follows is done; what that instruction did is handed to it (resolution_bridge)
                             "unconditional",
                             # 2026-10-13 (package 11, Twisted Fate - Gambler: "reveal the top rune of your rune deck,
                             # then recycle it. Do one of the following based on its domain:"): the Reflexive Trigger
                             # of one Domain goes on the Chain when the rune the named reveal showed was of it (Core
                             # 387.1.b), read off what the reveal noted - recycling the rune does not change it
                             "revealed_domain"}
# ADR-0012 §5: a Legend lives in the Legend Zone, which is not a Location.
OBJECT_KINDS = {"unit", "gear", "spell", "rune", "legend"}
SUPPORTED_OPS = {
    # 2026-10-08 package 10 (Bullet Time): a variable Power payment the controller sizes and makes at resolution
    "pay_any_amount",
    "draw",
    "recycle_one",
    "move_board_object",
    "modify_might",
    "deal_damage",
    "heal_damage",
    "ready",
    "exhaust",
    "add_resource",
    "play_token",
    "kill",
    "emit_reflexive",
    # C-16 (ADR-0005 §6, §8): three distinct events, not one "move".
    "return_to_hand",
    # Core 103.2.a.3, 108.3.c.1 (Hallowed Tomb, GPT 2026-09-27 ruling 15)
    "return_to_champion_zone",
    "recall",
    "channel_rune",
    # C-21 (ADR-0007 §6): a "this turn" effect such as Confront's, expiring at 317.2.
    "grant_turn_effect",
    # C-22 (ADR-0007 §10): hand → trash by the discarding player's private choice.
    "discard",
    # C-24 (ADR-0007 §12): a replacement created by an effect, bound to a target's identity for this turn.
    "grant_replacement",
    # package 9 (Unyielding Spirit: "Prevent all spell and ability damage this turn."): a replacement an effect
    # creates for the rest of this turn, applying to any object - typed and closed (create_turn_replacement)
    "create_turn_replacement",
    "heal_all_damage",
    # C-27 (ADR-0008 §5): a granted characteristic (Shield X, Tank, ...) for this combat or this turn.
    "grant_keyword",
    # C-29 (ADR-0008 §7): two chosen Units deal their current Might to each other, simultaneously.
    "mutual_damage_current_might",
    # C-33: "Swap the Might of two units this turn." Riot's own reading is that
    # the difference is worked out first and then applied as two Might changes -
    # a decrease on one, an increase on the other - which is why a replacement
    # that answers to "would give me -Might" can see it. Modelled exactly so:
    # one snapshot, two ordinary modify_might events.
    "swap_might",
    # 2026-10-06 package 9 (Convergent Mutation): "increase its Might to the Might of another friendly unit"
    "raise_might_to_match",
    # 2026-10-06 package 9 (Kai'Sa - Evolutionary): "Then recycle it." - a leave replacement bound to the Chain item
    "recycle_when_leaving_chain",
    # 2026-10-13 package 11 (Time Warp): "Take a turn after this one." - an Additional Turn queued after the current
    # turn (Core 735-738); "Banish this." - the resolving spell goes to its owner's banishment, not the trash
    "take_additional_turn", "banish_this",
    # 2026-10-13 package 11 (Possession, GPT ruling 12): "Take control of it" - a permanent's controller changes, its owner
    # does not (Core 189, 191.3); nothing else about it changes
    "gain_control",
    # 2026-10-13 package 11 (Reckoner's Arena, GPT ruling 15): "activate the conquer effects of units here" (Core
    # 383.4.g.1) - each unit's conquer effect checked as if it had conquered, put on the Chain if the rest holds
    "activate_conquer_effects",
    # 2026-10-13 package 11 (Promising Future, GPT ruling 16): "banishes one of them, then recycles the rest" - of the
    # cards its player looked at (Core 424.1, 427, 416)
    "banish_one_looked", "recycle_looked_rest",
    # 2026-10-13 package 11 (Mystic Reversal, GPT ruling 13): control of a spell on the Chain, and new choices for it
    # (Core 750-755)
    "gain_control_of_spell", "make_new_choices",
    # C-41 (ADR-0011 §3): look-at / reveal marks, the player's put-back order,
    # taking a looked-at card, Recycle as one action, Predict.
    "look_at_top",
    # 2026-10-04 (package 8): "reveal cards from the top of your Main Deck until you reveal a unit" (Dazzling Aurora)
    "reveal_until",
    "stun",
    "choose_player",
    "reveal",
    "put_back",
    "put_in_hand",
    "draw_it",
    "recycle",
    "predict",
    # C-43 (ADR-0011 §5): Banish, Counter and [Burn N].
    "banish",
    "counter",
    "burn",
    # C-46 (ADR-0012 §4): attachments and their Top-Most card.
    "attach",
    "detach",
    # C-47 (ADR-0012 §7): a typed copy request that fails closed until P4.
    "copy_object",
    # C-52 (ADR-0013 §5): Empowered and Buffed as binary states, and XP.
    "empower",
    "disempower",
    "buff",
    "gain_xp",
    # "you score 1 point" on a card. Core 471.1 has a Score do two things - the
    # player Gains up to one Point, and Score abilities trigger at the
    # Battlefield that Scored - and these cards have no Battlefield: "When I
    # hold, you score 1 point" is an ADDITIONAL point beside the one the Hold
    # already scored. So what the card does is the first half only, and
    # 471.1.a.1 says the restrictions on the Final Point do not reach it: they
    # bind only the points a Conquer gives. Named for what it does rather than for the word on
    # the card, so that nobody reads it as running 471.2.
    "gain_point",
    # package 9 (The Grand Plaza): an effect that instructs a player to win (Core 195); the game ends (196), right
    # away - not at the next Cleanup's victory check (194.2). The instruction emits a terminal_event, as a Burn Out
    # victory does; the effects after it are skipped.
    "win_game",
    # C-55 (ADR-0014 §2): a resolving effect creates a trigger that waits.
    "create_delayed_trigger",
    # C-58 (ADR-0015 §2): the Cleanup's step 5 removal of a Hidden card whose
    # Battlefield its controller no longer controls.
    "remove_hidden",
    # selection-binding.v1: "Choose a friendly unit." on its own. It changes no
    # game state; it establishes the selection that the clauses after it
    # ("Buff it.", "Kill it.") refer to, and records the binding they are
    # checked against.
    "establish_selection",
    # 2026-09-27: "[do X] to [do Y]" that opens a triggered ability's effect (or follows the
    # "you may" that opens it): [do X] is the ability's BASE cost (Core 204.3.a, 383.3.b,
    # 403.1.b.1), paid while the ability is finalized (383.3.b.1, 740.4.a.2) by
    # resolution_bridge.finalize_trigger (trigger_cost.py). It is the program's first
    # instruction so the content hash covers it; it changes nothing as the ability resolves -
    # apply_program only checks that the chain item's receipt says it was paid.
    "trigger_base_cost",
    # 2026-09-27 package 6: one instruction list run once per player (Core 303.2.a, 411.1), a choice of
    # objects that fills a group later instructions read, and a choice of a named option by a player.
    # All three are resolved by apply_program; none changes the board by itself.
    "each_player",
    "choose_objects",
    "choose_option",
    # 2026-09-28 (package 6): "Play a unit from your trash, ignoring its Energy cost." - a card
    # played as part of an effect's resolution (Core 419.3), a Limited Action (419.3.a) whose
    # steps are the normal ones except as the effect notes (419.3.b). The instruction performs
    # step 1 only: the card moves to the Chain as a Pending item (Core 354); the rest waits
    # until the resolving effect is done (354.3) and runs through the play transaction
    # (resolution_bridge.finalize_limited_play). It never puts a card on the board itself.
    "limited_play",
    # 2026-09-27 package 6: "Spend any number of buffs." as an INSTRUCTION, not a cost (Albus
    # Ferros: "When you play me, spend any number of buffs. For each buff spent, channel 1 rune
    # exhausted."). Its player chooses, as it resolves (Core 355.17), any number of Units they
    # control that have a buff (702.2.b.1, 702.2.b.2) - counters, not targets (704.1); each loses it
    # (702.2.b). How many it spent
    # is its receipt, which a linked later instruction counts (count_per linked_applied_count).
    "spend_buffs",
}
# Composite instructions resolved by apply_program itself (they consist of
# several Deal events that each pass through the replacement path).
COMPOSITE_OPS = {"mutual_damage_current_might", "swap_might", "raise_might_to_match"}
# ADR-0011 §1: instructions whose single object comes from a typed `choice`.
CHOICE_OPS = {"recycle_one", "choose_player"}
# selection-binding.v1: instructions that establish a selection rather than
# consume one. The eff_010 slice wires exactly one shape - a single, public,
# board choice of one object. Every other shape is recognised and refused as
# unsupported rather than run half-bound.
SELECTION_BINDING_OPS = {"establish_selection"}
# `from` is a set because Codex's eff_010 split gave "Choose a battlefield." its
# own candidate universe rather than a criteria on `board`; both are single,
# public choices of one object on the board.
SELECTION_SLICE = {"selection_kind": "single", "from": {"board", "battlefields"},
                   "count": {"one": True}, "visibility": "public"}
# Instructions that resolve their own choice into a set (they may need an order too).
SELF_RESOLVING_CHOICE_OPS = {"recycle", "banish"}
# 2026-09-27 package 6 (per-player iteration). "Each player kills one of their units." (Cull the
# Weak, Core 411.1's own example): an object chosen AS THE INSTRUCTION RESOLVES, by the player the
# instruction names, is not a target (Core 355.10.e) - the chosen object becomes the instruction's
# object, exactly as recycle_one's choice does, and a board choice is answered at the resolution stage.
RESOLUTION_CHOICE_OPS = {"kill", "return_to_hand"}
# 2026-10-08 package 10 (Mindsplitter): the one choice a discard may carry - a card of what a reveal showed, by the
# program's controller (_resolve_discard)
DISCARD_REVEALED_CHOICE = {"selection_kind": "single", "from": "revealed", "by": "controller", "count": {"one": True}}
# One instruction list run once per player: "Each player ...", "Each other player ...", "Starting with
# the next player, each player ...". Inside it, EACH_PLAYER_SENTINEL names the player of the iteration;
# the engine writes each iteration's copy with that player in place (EACH_PLAYER_FIELD records it, an
# engine-internal field like EXECUTION_FIELD). Core 303.2 / 303.2.a: game actions are never
# simultaneous, and actions that would be are sequenced in Turn Order starting with the Turn Player;
# "Starting with the next player" names another start. Core 411.1: each player is responsible for the
# game actions of their own iteration.
EACH_PLAYER_OP = "each_player"
EACH_PLAYER_SENTINEL = "$each_player"
EACH_PLAYER_FIELD = "_each_player"
# validate_program's marker on the synthetic program it checks an each_player's instructions as
EACH_PLAYER_BODY = "_each_player_body"
EACH_PLAYER_SETS = ("all", "others", "opponents")
EACH_PLAYER_ORDERS = ("turn_order", "after_controller")
EACH_PLAYER_NESTED_OPS = {"kill", "return_to_hand", "discard", "draw", "channel_rune", "choose_objects", "choose_option",
                          # 2026-10-04 (package 8): "Each opponent reveals the top card of their Main Deck." (Blind Fury)
                          "reveal",
                          # 2026-10-13 package 11 (Promising Future): each player looks at their own deck, banishes one of
                          # the cards, recycles the rest; then each plays the card they banished (limited_play linked
                          # per_player)
                          "look_at_top", "banish_one_looked", "recycle_looked_rest", "limited_play"}
EACH_PLAYER_RULES = ["Core 303.2", "Core 303.2.a", "Core 355.10.e", "Core 411.1"]
# "Each player chooses ..." / "each other player chooses a unit ... that hasn't been chosen for this
# spell": the objects chosen go into a GROUP of this program (ephemeral, like the selection bindings);
# "Kill those units" acts on the group (group_ref), "Recycle the rest" on what was offered and not
# chosen (rest_of). Neither is a target: other players chose them (Core 355.10.e).
GROUP_OPS = {"kill"}
# "Each other player chooses Cards or Runes.": a named option chosen at resolution by a player, recorded
# for "For each player that chooses Cards, ..." (each_player.only_chose).
OPTION_DECISION_KIND = "option_selection"


class EachPlayerUnsupported(ValueError):
    """An each_player instruction whose order the engine cannot establish: Turn Order and the Turn
    Player are a procedure's facts (the timing state's), carried in context["turn"]."""

    reason_code = "turn_order_unknown"


def each_player_order(state: dict[str, Any], program: dict[str, Any], context: dict[str, Any] | None,
                      effect: dict[str, Any]) -> list[str]:
    """The players an each_player instruction runs for, in the order it runs them.

    turn_order         Turn Order starting with the current Turn Player (Core 303.2.a)
    after_controller   Turn Order starting with the player after the program's controller
                       ("Starting with the next player")
    players others     every player but the program's controller ("each other player")
    players opponents  every player not on the controller's side ("each opponent", Core 303.2 order kept;
                       a teammate is not an opponent - package 8)"""
    turn = (context or {}).get("turn") or {}
    order, turn_player = turn.get("turn_order"), turn.get("turn_player")
    if not isinstance(order, list) or len(order) != len(set(order)) or set(order) != set(state["players"]) \
            or turn_player not in order:
        raise EachPlayerUnsupported("each player acts in Turn Order (Core 303.2.a); the Turn Order and the Turn "
                                    "Player are not known here (context.turn), and are not guessed")
    controller = program.get("controller")
    if effect.get("order") == "after_controller":
        if controller not in order:
            raise EachPlayerUnsupported(f"'the next player' is the one after the controller {controller!r}, who is "
                                        f"not in the Turn Order {order}")
        start = order[(order.index(controller) + 1) % len(order)]
    else:
        start = turn_player
    at = order.index(start)
    rotated = order[at:] + order[:at]
    if effect.get("players") == "others":
        rotated = [p for p in rotated if p != controller]
    if effect.get("players") == "opponents":
        rotated = [p for p in rotated if not same_side(state, controller, p)]
    return rotated


def _replace_sentinel(value: Any, player: str) -> Any:
    if isinstance(value, dict):
        return {k: _replace_sentinel(v, player) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_sentinel(v, player) for v in value]
    return player if value == EACH_PLAYER_SENTINEL else value


def each_player_copies(effect: dict[str, Any], player: str) -> list[dict[str, Any]]:
    """The instructions of one iteration: every decision reference and effect id suffixed by the
    player (each player makes their own choices, Core 355.10.e), the sentinel replaced by the player,
    and the iteration's player stamped on each copy. A group name is NOT suffixed: every player's
    choice goes into the one group the later instruction reads."""
    suffix = f"@{player}{execution_suffix(effect)}"
    copies = suffix_decision_refs(copy.deepcopy(effect["effects"]), suffix)
    out = []
    for copied in copies:
        copied = _replace_sentinel(copied, player)
        copied[EACH_PLAYER_FIELD] = player
        copied["each_player_of"] = effect.get("effect_id")
        if execution_suffix(effect):
            copied[EXECUTION_FIELD] = execution_suffix(effect)
        out.append(copied)
    return out


def _mentions_sentinel(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_mentions_sentinel(v) for v in value.values())
    if isinstance(value, list):
        return any(_mentions_sentinel(v) for v in value)
    return value == EACH_PLAYER_SENTINEL


def contains_each_player(program: dict[str, Any] | None) -> bool:
    """Whether a program iterates over players (and so needs context.turn)."""
    if not isinstance(program, dict):
        return False
    effects = list(program.get("effects") or [])
    for option in ((program.get("modal") or {}).get("options") or []):
        effects += list((option or {}).get("effects") or [])
    return any(isinstance(e, dict) and e.get("op") == EACH_PLAYER_OP for e in effects)


class ReplacementDecisionRequired(ValueError):
    def __init__(self, message: str, replacement_ids: list[str]):
        super().__init__(message)
        self.replacement_ids = replacement_ids


class IllegalOperation(ValueError):
    """A well-formed instruction the rules refuse for this object (ADR-0005 §10
    `illegal`), as opposed to a malformed one (`invalid_input`)."""


class CardSelectionRequired(ValueError):
    """A private-zone choice (Core 355.10.a) the deciding player has not made."""

    def __init__(self, message: str, decision_ids: list[str], controller: str | None):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller


class TargetDecisionRequired(ValueError):
    """A selector defers to a decision entry that was not supplied (ADR-0005 §1/§2)."""

    def __init__(self, message: str, decision_ids: list[str], controller: str | None):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller


class IllegalDecision(ValueError):
    """A well-formed supplied decision is owned by another controller."""


class SelectionBindingRefused(ValueError):
    """selection-binding.v1: the reference to a selection does not hold.

    It carries one of the contract's four refusal codes. The instruction does
    not run and nothing is re-chosen: an unbound reference is a refusal, never
    a licence to pick a substitute.
    """

    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


class SourceUnavailable(SelectionBindingRefused):
    """The program's own source - "me", "my Might" - is not there as the instruction executes: it
    left the board, the object at its id is a new one (Core 124), or, a token, it ceased to exist
    (186.1). That is a game event, not a malformed program: the instruction cannot be followed and
    is ignored, and the rest of the ability resolves (Core 359.3.e.6, 359.3.f.1, 359.3.f.2). Still a
    refusal where it is raised - the caller in apply_program records the instruction as ignored."""


# The outcome an instruction whose own source is unavailable is recorded with (SourceUnavailable).
SOURCE_UNAVAILABLE_OUTCOME = "ignored_source_unavailable"
SOURCE_UNAVAILABLE_RULES = ["Core 359.3.e.6", "Core 359.3.f.1", "Core 359.3.f.2"]


class ExternalInputRequired(ValueError):
    """ADR-0010 §2: an external randomization receipt the transition needs is absent. 2026-10-16 package 14: it says
    what chance orders - the operation, its player and the cards (`chance`) - so a caller can supply the receipt."""

    reason_code = "randomization_receipt_required"

    def __init__(self, message: str, decision_ids: list[str], controller: str | None,
                 chance: dict[str, Any] | None = None):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller
        self.chance = chance


def chance_fields(exc: Exception) -> dict[str, Any]:
    """The result field a randomization request's operation travels in: {operation, operation_id, player, permute}."""
    chance = getattr(exc, "chance", None)
    return {"chance": chance} if chance is not None else {}


class PlayerSelectionRequired(ValueError):
    """A choice of another player (the Burn Out beneficiary, 431.2.c) the deciding player has not made."""

    reason_code = "player_selection_required"

    def __init__(self, message: str, decision_ids: list[str], controller: str | None):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller


class ChoiceRequired(ValueError):
    """ADR-0011 §1: a typed choice the chooser has not supplied. The summary
    carries the specification and, for a public source only, the options."""

    def __init__(self, message: str, decision_ids: list[str], controller: str | None, summary: dict[str, Any]):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller
        self.summary = summary
        self.reason_code = f"{summary['decision_kind']}_required"


# 2026-10-16 package 14: what a choice private to its chooser offers never travels in a result or its summary (Core
# 128.4, 355.10.a - engine_check hands results on). A trusted verifier that must enumerate the choice opts in to a side
# record of it for the calls it makes (recording_private_options): {decision id: [{object_id, identity}]}
_PRIVATE_OPTIONS: _contextvars.ContextVar = _contextvars.ContextVar("private_choice_options", default=None)


@_contextlib.contextmanager
def recording_private_options():
    log: dict[str, list[dict[str, Any]]] = {}
    token = _PRIVATE_OPTIONS.set(log)
    try:
        yield log
    finally:
        _PRIVATE_OPTIONS.reset(token)


# 2026-10-19 package 15 (GPT PACKAGE15 ruling 3): the decisions an event needs, noted where the rules make them needed -
# before the procedure looks for the decision, so a procedure that stopped asking (took a default) still notes them. A
# trusted verifier opts in (recording_ledger) and holds a committed way to them: decision_space.event_ledger. Each note is
# (kind, decision id); nothing is noted outside a recording, and no result carries one
_LEDGER_NOTES: _contextvars.ContextVar = _contextvars.ContextVar("ledger_notes", default=None)


@_contextlib.contextmanager
def recording_ledger():
    log: list[tuple[str, str]] = []
    token = _LEDGER_NOTES.set(log)
    try:
        yield log
    finally:
        _LEDGER_NOTES.reset(token)


def _shown_to_chooser(ref: str, state: dict[str, Any], card: str) -> None:
    """A card a request asks its chooser about, private to them (package 15, found by the corpus: a card that may banish
    itself as its owner looks at it) - in the trusted side record of what a private choice offers, as resolve_choice
    puts its options there; never in a result."""
    log = _PRIVATE_OPTIONS.get()
    if log is not None:
        log[ref] = [{"object_id": card, "identity": object_identity(state, card)}]


# the Cleanup iteration a kill batch is run for (perform_lethal_cleanup): its replacement notes and requests name it
_CLEANUP_ITERATION: _contextvars.ContextVar = _contextvars.ContextVar("cleanup_iteration", default=0)


def _iteration_suffix() -> str:
    k = _CLEANUP_ITERATION.get()
    return f"#cleanup{k}" if k else ""


def public_projection(state: dict[str, Any]) -> dict[str, Any]:
    """2026-10-21 package 15 (GPT PACKAGE15 round 2, ruling 5): the state as both players see it - every card one of them
    may not see removed: each player's hand, Main Deck and Rune Deck down to their counts, a Battlefield's facedown cards
    down to their controllers, the look and reveal marks gone. An id the engine makes from a state (a Combat's, a batch's)
    is made from this, so no change to what a player cannot see changes it, and a player's view makes the same one."""
    out = copy.deepcopy(state)
    hidden: set[str] = set()
    for record in (out.get("players") or {}).values():
        zones = record.get("zones") or {}
        for zone in ("hand", "main_deck", "rune_deck"):
            cards = zones.get(zone) or []
            hidden |= set(cards)
            zones[zone] = len(cards)
    for battlefield in (out.get("battlefields") or {}).values():
        facedown = battlefield.get("facedown")
        if isinstance(facedown, dict):
            cards = facedown.get("cards") or []
            hidden |= {c.get("object_id") for c in cards}
            facedown["cards"] = [{"controller": c.get("controller")} for c in cards]
    out["objects"] = {o: v for o, v in (out.get("objects") or {}).items() if o not in hidden}
    out.pop("reveals", None)
    return out


def public_id(*states: dict[str, Any] | None) -> str:
    """Twelve hex digits of the public projection of these states (a timing state is public whole) - an engine-made id
    that depends on nothing a player cannot see."""
    parts = [s if s is None or "players" not in s or "objects" not in s else public_projection(s) for s in states]
    return hash_value({"public": parts}).split(":", 1)[1][:12]


def ledger_note(kind: str, decision_id: str) -> None:
    log = _LEDGER_NOTES.get()
    if log is not None:
        log.append((kind, decision_id))


class LocationSelectionRequired(ValueError):
    """Core 420 / 355.4: a Move whose destination the controller has not chosen. The
    candidates travel with it, generated from the board, so a caller never has
    to guess what the legal destinations were."""

    reason_code = "location_selection_required"

    def __init__(self, message: str, decision_ids: list[str], controller: str | None, candidates: list[str]):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller
        self.candidates = candidates


class ModeSelectionRequired(ValueError):
    """ADR-0011 §2: a modal program whose mode has not been chosen."""

    reason_code = "mode_selection_required"

    def __init__(self, message: str, decision_ids: list[str], controller: str | None, options: list[str]):
        super().__init__(message)
        self.decision_ids = decision_ids
        self.controller = controller
        self.options = options


def object_identity(state: dict[str, Any], object_id: str) -> str | None:
    """ADR-0005 §3: identity survives board moves and changes on any transition
    to or from a non-board zone. States written before this field existed carry
    none; they are read as generation 0 without being rewritten."""
    obj = state["objects"].get(object_id)
    if obj is None:
        return None
    return obj.get("identity", f"{object_id}@0")


def battlefield_identity(state: dict[str, Any], battlefield_id: str) -> str | None:
    """ADR-0007 §4: a Battlefield is a target with a bindable identity."""
    battlefield = state["battlefields"].get(battlefield_id)
    if battlefield is None:
        return None
    return battlefield.get("identity", f"{battlefield_id}@0")


def entity_identity(state: dict[str, Any], entity_id: str) -> str | None:
    """Identity of an object or, failing that, a Battlefield."""
    return object_identity(state, entity_id) if entity_id in state["objects"] else battlefield_identity(state, entity_id)


def _bump_identity(state: dict[str, Any], object_id: str) -> str:
    current = object_identity(state, object_id) or f"{object_id}@0"
    base, _, generation = current.rpartition("@")
    nxt = f"{base or object_id}@{int(generation) + 1 if generation.isdigit() else 1}"
    state["objects"][object_id]["identity"] = nxt
    if state.get("reveals"):
        _drop_reveals(state, [object_id])  # a new object carries no reveal mark (424.2, 128.2.a)
    return nxt

OP_RULES = {
    "draw": ["Core 413"],
    "recycle_one": ["Core 416"],
    "move_board_object": ["Core 420", "Core 445"],
    "modify_might": ["Core 135.2.e.3", "Core 477.3.a", "Core 477.3.b", "Core 143.2.b"],
    "deal_damage": ["Core 417"],
    "heal_damage": ["Core 418"],
    "stun": ["Core 423", "Core 423.1", "Core 423.1.b", "Core 423.2", "Core 317.2.d"],
    "choose_player": ["Core 355.1", "Core 355.17"],
    "establish_selection": ["Core 355.10.a", "Core 359.3.e"],
    "ready": ["Core 415"],
    "exhaust": ["Core 414"],
    "add_resource": ["Core 429"],
    "play_token": ["Core 143.4", "Core 149.1", "Core 184–186", "Core 349", "Core 375"],
    "kill": ["Core 428"],
    "emit_reflexive": ["Core 386–388"],
    "return_to_hand": ["Core 124", "Core 124.1", "Core 446.2"],
    "return_to_champion_zone": ["Core 103.2.a.3", "Core 108.3.c", "Core 108.3.c.1", "Core 124"],
    "recall": ["Core 455", "Core 456.1", "Core 458.1"],
    "channel_rune": ["Core 430.1", "Core 430.2.a", "Core 430.3", "Core 124"],
    "grant_turn_effect": ["Core 369.3", "Core 317.2.c"],
    "discard": ["Core 422.1", "Core 422.1.a", "Core 422.4", "Core 124"],
    "grant_replacement": ["Core 370", "Core 355.10.c", "Core 124", "Core 317.2.c"],
    "create_turn_replacement": ["Core 370", "Core 417.6.a", "Core 417.6.b.3", "Core 417.6.c", "Core 317.2.c"],
    "heal_all_damage": ["Core 418"],
    "grant_keyword": ["Core 814.2", "Core 466.7.c", "Core 317.2.c", "Core 124"],
    "mutual_damage_current_might": ["Core 417.1.d", "Core 417.6.b.3", "Core 417.6.b.4", "Core 143.2.b", "Core 359.3.e.5"],
    "raise_might_to_match": ["Core 477.3.a", "Core 355.8", "Core 359.3.e.5", "Core 370.1.a"],
    "recycle_when_leaving_chain": ["Core 390.3.a", "Core 416", "Core 124"],
    "take_additional_turn": ["Core 735", "Core 736", "Core 737", "Core 738"],
    "gain_control": ["Core 188", "Core 189", "Core 191.3", "Core 191.4.b"],
    "activate_conquer_effects": ["Core 383.4.g", "Core 383.4.g.1", "Core 383.4.c", "Core 383.2.a.1"],
    "banish_one_looked": ["Core 424.1", "Core 427.1", "Core 124"],
    "gain_control_of_spell": ["Core 191.2", "Core 191.4.b", "Core 359.3.f.4"],
    "make_new_choices": ["Core 751", "Core 751.1", "Core 752", "Core 752.1", "Core 753", "Core 753.1", "Core 753.2", "Core 755"],
    "recycle_looked_rest": ["Core 424.1", "Core 416", "Core 416.5"],
    "banish_this": ["Core 157", "Core 427.1", "Core 124"],
    "swap_might": ["Core 477.3.a", "Core 477.3.e.1.a", "Core 477.3.e.2.a", "Core 135.2.e.3",
                   "Core 370.1.a", "Core 373.2"],
    "look_at_top": ["Core 128.4", "Core 431.1.c", "Core 431.1.c.1"],
    "reveal_until": ["Core 424", "Core 431.1.c", "Core 128"],
    "reveal": ["Core 424.1", "Core 424.2", "Core 424.2.a", "Core 424.3.a", "Core 431.1.c"],
    "put_back": ["Core 424.2", "Core 436.1.a", "Core 355.10.a"],
    "put_in_hand": ["Core 424.4", "Core 128.2.a", "Core 124"],
    "draw_it": ["Core 413", "Core 428.5", "Core 124"],
    "recycle": ["Core 416.1", "Core 416.2", "Core 416.5", "Core 303.2", "Core 124"],
    "predict": ["Core 436.1", "Core 436.1.a", "Core 436.4", "Core 436.4.a", "Core 416.5"],
    "banish": ["Core 427.1", "Core 427.2", "Core 427.2.a", "Core 427.2.b", "Core 124"],
    "counter": ["Core 425.1", "Core 425.1.a", "Core 425.1.b", "Core 425.1.c", "Core 124"],
    "burn": ["Core 440.1", "Core 440.2", "Core 431.1.b", "Core 124"],
    "copy_object": ["Core 135.2.b", "Core 185.3.a", "Core 187.1"],
    # 441 is Empower, 442 Disempower (443 is Skip) - fourth adversarial review 2026-09-26
    "empower": ["Core 441.1", "Core 441.1.b", "Core 441.1.c", "Core 441.1.c.1", "Core 441.2.a"],
    "disempower": ["Core 442.1", "Core 442.1.a", "Core 442.1.a.1"],
    "buff": ["Core 426.1", "Core 426.1.b", "Core 426.1.c", "Core 702"],
    "gain_xp": ["Core 730.1", "Core 730.2"],
    "gain_point": ["Core 471.1", "Core 471.1.a.1", "Core 471.2"],
    "win_game": ["Core 195", "Core 196"],
    "attach": ["Core 434.1", "Core 434.2.a", "Core 434.2.b", "Core 434.4", "Core 434.5.a", "Core 136.2.c"],
    "detach": ["Core 435.1", "Core 435.4", "Core 435.4.a", "Core 435.4.b", "Core 136.2.c"],
    "create_delayed_trigger": ["Core 383.1", "Core 383.3", "Core 124"],
    "remove_hidden": ["Core 323.7", "Core 811", "Core 124"],
    "trigger_base_cost": ["Core 204.3.a", "Core 383.3.b", "Core 383.3.b.1", "Core 403.1.b.1", "Core 404.2", "Core 740.4.a.2"],
    "each_player": ["Core 303.2", "Core 303.2.a", "Core 411.1"],
    "choose_objects": ["Core 355.10.e", "Core 359.3.e"],
    "choose_option": ["Core 355.10.e"],
    "pay_any_amount": ["Core 204.3.b", "Core 355.10.e", "Core 417.1.e"],
    "limited_play": ["Core 419.3", "Core 419.3.a", "Core 419.3.b", "Core 354", "Core 354.3", "Core 124"],
    "spend_buffs": ["Core 702.2.b", "Core 702.2.b.1", "Core 702.2.b.2", "Core 704", "Core 704.1", "Core 355.17"],
}
# 2026-09-28 (package 6): what an effect-driven play changes about the card's cost (Core 356.1):
# "ignoring its Energy cost" / "ignoring its Power cost" set that base cost to zero and leave the
# other (356.1.b.2); "ignoring its cost" sets both to zero (356.1.b.1). Each is a base cost
# modification the play transaction applies before Core 356 runs.
LIMITED_PLAY_COST_BASES = {"ignore_energy": "Core 356.1.b.2", "ignore_power": "Core 356.1.b.2",
                           "ignore_all": "Core 356.1.b.1",
                           # 2026-10-04 (package 8, GPT ruling 1): "you may pay X to play me" - X is the trigger's
                           # base cost paid at finalization, and the card is then played paying its own cost: the
                           # effect changes nothing about it, the steps are the normal ones (Core 419.3.b)
                           "printed": "Core 419.3.b",
                           # 2026-10-04 (package 8, GPT ruling 6): "play it, reducing its cost by [5]" (Reinforce) - an
                           # Energy discount of `amount` (Core 356.4.b), applied in the discount step, Energy not below 0
                           # (356.6), the Power cost still paid; the base cost is the printed one
                           "discount_energy": "Core 356.4.b",
                           # 2026-10-06 (package 9, Nocturne - Horrifying): "play me for [A]" - the base cost replaced by
                           # N Power of any Domain (Core 356.1.a), paid as a mandatory power_any component
                           "for_power_any": "Core 356.1.a"}
# 2026-10-04 (package 8): "play me" - the card is the program's own source, in the zone its triggered ability
# works from (Core 383.2.c.1); not chosen, so not a target (355.7)
LIMITED_PLAY_SELF_ZONES = {"trash"}
# 2026-10-04 (package 8, group 3): "... banish it, then play it" (Baited Hook, Reinforce, Dazzling Aurora, Blind Fury) -
# the card an EARLIER instruction of the same program banished, played from its owner's Banishment (Core 427: banished
# cards go to their owner's Banishment; 127.1: the owner does not change). Bound by that instruction's result, never
# chosen again: it is not a target (355.7)
# 2026-10-13 package 11 (Promising Future): the one card a player banished from what they looked at
LIMITED_PLAY_LINKED_OPS = {"banish", "banish_one_looked"}
# where an effect-driven play may take a card from: a public zone, so the card is a target chosen as
# the effect is played or finalized (GPT 2026-09-25; Core 355.10.a, 355.9.a). A private zone (the
# hand) is a choice made as the effect resolves, which this instruction does not model yet.
LIMITED_PLAY_ZONES = {"trash"}
# 2026-09-28 (package 6, step 2): a card from a private zone - its controller's hand - is not a target
# (Core 355.10.a); it is chosen as the effect resolves, and a player cannot be made to take a card of a named
# type or quality from a hidden zone (128.6), so the choice is of at most one card
LIMITED_PLAY_CHOICE_ZONES = {"hand"}
LIMITED_PLAY_CARD_FILTER = {"kind", "hidden"}
LIMITED_PLAY_KINDS = {"unit", "gear", "spell"}
LIMITED_PLAY_RECORD_FIELDS = {"granted_by", "program_id", "effect_id", "source_zone", "zone_owner", "zone_index",
                              "identity_before", "controller_before", "cost_basis"}
# the location the effect named for the unit it plays ("play it here", Core 355.2.b), when it named one
LIMITED_PLAY_RECORD_OPTIONAL = {"entry_location"}
# "If it's a unit, play it here.": where the effect has a unit it plays enter - the program source's current
# Battlefield, read as the instruction executes (Core 359.3.f.2)
# 2026-10-06 (package 9, Portal Rescue): "plays it to their base" - the unit enters the Base of the player who plays it
LIMITED_PLAY_ENTRY_KINDS = {"unit_at_source_battlefield", "unit_at_players_base"}
# 2026-10-06 (package 9, GPT ruling 2): "its owner plays it" - who plays a linked card: its owner (Core 127.1), who then
# controls it (419.1). Only a linked play names it; without it the program's controller plays, as before
LIMITED_PLAY_PLAYERS = {"owner"}
# The payments a triggered ability's base cost is made of (trigger_cost.py pays them): Energy
# and Power, exhausting the ability's own source, spending a buff from a unit its controller
# controls (Core 702.2.b), and recycling the ability's own source from its owner's trash (Core
# 416; Ekko, Recurrent is 383.3.b's own example). Anything else is not modelled and refused.
TRIGGER_COST_PAYMENTS = {"energy": {"amount"}, "power": {"domain", "amount"}, "exhaust": {"object_id"},
                         "spend_buff": set(), "recycle": {"object_id"},
                         # 2026-09-28 (package 6): [C] - Power of the ability's own card's Domain, read off the
                         # source as the cost is paid (the errata's [C]; its one Domain, or not payable)
                         "power_own_domain": {"amount"},
                         # 2026-10-12 (package 11, Super Mega Death Rocket!): discard N cards of the paying player's hand,
                         # chosen as the ability is finalized (Core 383.3.b.1, 422.1)
                         "discard": {"amount"}}
# 2026-10-12 (package 11): return_to_hand's typed "this" from the zone the ability works from (Core 385.2) - the program's
# own source as its chain item recorded it, in its owner's zone named here
RETURN_SELF_ZONES = {"trash"}


def _hash_uncached(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


# 2026-10-18 package 15 (C2's corpus): a trusted verifier that hands the same, unchanged input state to the engine
# thousands of times (action_space.differential tries every declaration of D(s) on one state) opts in to computing that
# state's hash and validation once (frozen_inputs). Keyed by the object itself, never by value; the verifier holds the
# objects unchanged and checks it afterwards (frozen_inputs re-hashes them uncached on exit and raises if one moved), so
# every result is the one the engine would give without it.
_FROZEN: _contextvars.ContextVar = _contextvars.ContextVar("frozen_inputs", default=None)


class FrozenInputMoved(RuntimeError):
    """An input held frozen changed while it was frozen: every result computed under it is void."""


@_contextlib.contextmanager
def frozen_inputs(*values: Any):
    own: dict[int, dict[str, Any]] = {}
    for value in values:
        if _frozen(value) is None:
            own[id(value)] = {"object": value, "hash": _hash_uncached(value)}
    # an inner block keeps what the outer one holds frozen (and checks only its own on exit)
    memo = {**(_FROZEN.get() or {}), **own}
    token = _FROZEN.set(memo)
    try:
        yield memo
    finally:
        _FROZEN.reset(token)
        moved = [k for k, m in own.items() if _hash_uncached(m["object"]) != m["hash"]]
        if moved:
            raise FrozenInputMoved(f"{len(moved)} input(s) held frozen changed while frozen")


def _frozen(value: Any) -> dict[str, Any] | None:
    memo = _FROZEN.get()
    if memo is None:
        return None
    entry = memo.get(id(value))
    return entry if entry is not None and entry["object"] is value else None


def hash_value(value: Any) -> str:
    if (entry := _frozen(value)) is not None:
        return entry["hash"]
    return _hash_uncached(value)


def _ruleset_valid(value: Any) -> bool:
    return value == {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF}


def validate_state(state: Any) -> list[str]:
    if (entry := _frozen(state)) is not None:
        if "validation" not in entry:
            entry["validation"] = validate_state_uncached(state)
        return list(entry["validation"])
    return validate_state_uncached(state)


def validate_state_uncached(state: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, dict):
        return ["effect state must be an object"]
    if state.get("schema_version") != STATE_VERSION:
        errors.append(f"schema_version must be {STATE_VERSION}")
    if not _ruleset_valid(state.get("ruleset")):
        errors.append(f"ruleset must be {{'core': {CORE_RULESET!r}, 'faq_as_of': {FAQ_AS_OF!r}}}: the Core this engine "
                      f"executes; a state labelled with another Core is refused")
    players = state.get("players")
    objects = state.get("objects")
    battlefields = state.get("battlefields")
    replacements = state.get("replacement_effects")
    if not isinstance(players, dict) or len(players) < 2:
        errors.append("players must be an object with at least two entries")
        players = {}
    if not isinstance(objects, dict):
        errors.append("objects must be an object")
        objects = {}
    if not isinstance(battlefields, dict):
        errors.append("battlefields must be an object")
        battlefields = {}
    if not isinstance(replacements, list):
        errors.append("replacement_effects must be an array")
        replacements = []

    occupancy: dict[str, list[str]] = {object_id: [] for object_id in objects}
    for player_id, player in players.items():
        if not isinstance(player, dict):
            errors.append(f"players.{player_id} must be an object")
            continue
        zones = player.get("zones")
        if not isinstance(zones, dict) or not PLAYER_ZONES <= set(zones) or set(zones) - PLAYER_ZONES - OPTIONAL_PLAYER_ZONES:
            errors.append(f"players.{player_id}.zones must contain {sorted(PLAYER_ZONES)} and may add {sorted(OPTIONAL_PLAYER_ZONES)}")
            continue
        for zone, ids in zones.items():
            if not isinstance(ids, list) or len(ids) != len(set(ids)):
                errors.append(f"players.{player_id}.zones.{zone} must be a unique array")
                continue
            for object_id in ids:
                if object_id not in objects:
                    errors.append(f"unknown object {object_id!r} in {player_id}.{zone}")
                else:
                    occupancy[object_id].append(f"player:{player_id}:{zone}")
                    if zone == "legend_zone" and objects[object_id].get("kind") != "legend":
                        errors.append(f"players.{player_id}.zones.legend_zone holds {object_id!r}, which is not a legend (Core 107.4.d)")
        resources = player.get("resources")
        if not isinstance(resources, dict) or not isinstance(resources.get("energy"), int) or resources.get("energy", -1) < 0:
            errors.append(f"players.{player_id}.resources.energy must be a non-negative integer")
        power = resources.get("power") if isinstance(resources, dict) else None
        if not isinstance(power, dict) or any(not isinstance(v, int) or v < 0 for v in power.values()):
            errors.append(f"players.{player_id}.resources.power must map domains to non-negative integers")
        # 2026-09-27: Universal Power ([A] Added, Core 135.2.e.5.b, 163.2.b) pays a Power cost of any
        # Domain; it is no Domain's, so it is counted apart from `power`
        universal = resources.get("universal_power", 0) if isinstance(resources, dict) else 0
        if not isinstance(universal, int) or isinstance(universal, bool) or universal < 0:
            errors.append(f"players.{player_id}.resources.universal_power must be a non-negative integer (Core 163.2.b)")
        restricted = resources.get("restricted", []) if isinstance(resources, dict) else []
        if not isinstance(restricted, list):
            errors.append(f"players.{player_id}.resources.restricted must be an array")
        else:
            seen_restrictions: set[str] = set()
            for r_index, entry in enumerate(restricted):
                label = f"players.{player_id}.resources.restricted[{r_index}]"
                if not isinstance(entry, dict) or set(entry) - {"restriction_id", "kind", "domain", "universal", "amount", "uses", "source"} or not {"restriction_id", "kind", "amount", "uses"} <= set(entry):
                    errors.append(f"{label} must carry restriction_id, kind, amount, uses (and domain or universal / source)")
                    continue
                if not isinstance(entry["restriction_id"], str) or not entry["restriction_id"] or entry["restriction_id"] in seen_restrictions:
                    errors.append(f"{label}.restriction_id is invalid or duplicated")
                seen_restrictions.add(entry.get("restriction_id", ""))
                # power has a domain, or is Universal (2026-09-27, Core 163.2.b) - never both, never neither
                universal_entry = "universal" in entry
                if universal_entry and (entry["universal"] is not True or entry["kind"] != "power" or "domain" in entry):
                    errors.append(f"{label}.universal is `true` on power with no domain (Core 135.2.e.5.b)")
                elif entry["kind"] not in {"energy", "power"} or (entry["kind"] == "power" and not universal_entry and (not isinstance(entry.get("domain"), str) or not entry.get("domain"))) or (entry["kind"] == "energy" and "domain" in entry):
                    errors.append(f"{label}.kind must be energy, or power with a domain")
                if not isinstance(entry["amount"], int) or isinstance(entry["amount"], bool) or entry["amount"] < 1:
                    errors.append(f"{label}.amount must be a positive integer")
                if not isinstance(entry["uses"], list) or not entry["uses"] or any(u not in RESOURCE_USES for u in entry["uses"]) or len(entry["uses"]) != len(set(entry["uses"])):
                    errors.append(f"{label}.uses must be a non-empty unique subset of {RESOURCE_USES}")
        if "team_id" in player and (not isinstance(player["team_id"], str) or not player["team_id"]):
            errors.append(f"players.{player_id}.team_id must be a non-empty string when supplied")
        # ADR-0013 §5 / Core 730: XP is a value marked on the player.
        if "xp" in player and (not isinstance(player["xp"], int) or isinstance(player["xp"], bool) or player["xp"] < 0):
            errors.append(f"players.{player_id}.xp must be a non-negative integer (Core 730.1)")
        # ADR-0009 §1: points and the once-per-Battlefield-per-turn ledger (470).
        if "points" in player and (not isinstance(player["points"], int) or isinstance(player["points"], bool) or player["points"] < 0):
            errors.append(f"players.{player_id}.points must be a non-negative integer")
        ledger = player.get("scored_this_turn")
        if ledger is not None and (not isinstance(ledger, dict) or any(not isinstance(k, str) or not k or not isinstance(v, list) or len(v) != len(set(v)) or any(b not in battlefields for b in v) for k, v in ledger.items())):
            errors.append(f"players.{player_id}.scored_this_turn must map turn ids to unique known battlefield ids")
        # Core 419.4.b / 812.1.c: the cards this player Finalized, per turn.
        finalized = player.get("cards_finalized_this_turn")
        if finalized is not None and (not isinstance(finalized, dict) or any(not isinstance(k, str) or not k or not isinstance(v, list) or len(v) != len(set(v)) or any(o not in objects for o in v) for k, v in finalized.items())):
            errors.append(f"players.{player_id}.cards_finalized_this_turn must map turn ids to unique known object ids")
        # Core 422.1 (2026-09-27): the cards this player discarded, per turn - one entry per
        # discard, so a card discarded twice in a turn is there twice.
        discarded = player.get("cards_discarded_this_turn")
        if discarded is not None and (not isinstance(discarded, dict) or any(not isinstance(k, str) or not k or not isinstance(v, list) or any(o not in objects for o in v) for k, v in discarded.items())):
            errors.append(f"players.{player_id}.cards_discarded_this_turn must map turn ids to lists of known object ids")
        # Core 428.1 / 428.2.a: how many Units this player controlled when they died, per turn -
        # "if an enemy unit has died this turn" (Spoils of War). A count, not ids: a token that
        # dies ceases to exist (186.1) and would leave an id pointing at nothing.
        died = player.get("units_died_this_turn")
        if died is not None and (not isinstance(died, dict) or any(not isinstance(k, str) or not k or not isinstance(v, int)
                                                                  or isinstance(v, bool) or v < 1 for k, v in died.items())):
            errors.append(f"players.{player_id}.units_died_this_turn must map turn ids to a positive count (Core 428.1)")
        # 2026-09-27 (package 6): how many cards this player played this turn, one per play
        # Finalized (Core 419.4.b) - a count, since the same card played twice is two plays
        played_count = player.get("cards_played_count_this_turn")
        if played_count is not None and (not isinstance(played_count, dict) or any(
                not isinstance(k, str) or not k or not isinstance(v, int) or isinstance(v, bool) or v < 1
                for k, v in played_count.items())):
            errors.append(f"players.{player_id}.cards_played_count_this_turn must map turn ids to a positive count "
                          f"(Core 419.4.b)")

    for battlefield_id, battlefield in battlefields.items():
        if not isinstance(battlefield, dict) or not isinstance(battlefield.get("objects"), list):
            errors.append(f"battlefields.{battlefield_id}.objects must be an array")
            continue
        # ADR-0007 §1: a unit entering a Battlefield its controller does not
        # control marks it contested (190.3.a.1); who contests is recorded, and
        # nothing about control transfer is inferred.
        if "contested" in battlefield and not isinstance(battlefield["contested"], bool):
            errors.append(f"battlefields.{battlefield_id}.contested must be boolean when supplied")
        if "contested_by" in battlefield and battlefield["contested_by"] is not None and battlefield["contested_by"] not in players:
            errors.append(f"battlefields.{battlefield_id}.contested_by must be a player or null")
        if battlefield.get("contested") and battlefield.get("contested_by") is None:
            errors.append(f"battlefields.{battlefield_id} is contested without contested_by")
        for a_index, aura in enumerate(battlefield.get("static_auras", []) or []):
            if isinstance(aura, dict) and "keyword" in aura:
                # 2026-09-27: "Units here have [Ganking]." - a keyword instead of a Might amount
                if set(aura) - {"aura_id", "keyword", "value", "criteria"} or _static_keyword_problem(aura) \
                        or not isinstance(aura.get("criteria"), dict) or set(aura["criteria"]) - BATTLEFIELD_AURA_CRITERIA \
                        or aura["criteria"].get("kind", "unit") != "unit":
                    errors.append(f"battlefields.{battlefield_id}.static_auras[{a_index}] must be {{aura_id, keyword in "
                                  f"{sorted(STATIC_AURA_KEYWORDS)}, value? (summed keywords only), criteria over "
                                  f"{sorted(BATTLEFIELD_AURA_CRITERIA)}}}")
                continue
            if not isinstance(aura, dict) or set(aura) - {"aura_id", "amount", "criteria"} \
                    or not isinstance(aura.get("amount"), int) or isinstance(aura.get("amount"), bool) or aura.get("amount") == 0 \
                    or not isinstance(aura.get("criteria"), dict) or set(aura["criteria"]) - BATTLEFIELD_AURA_CRITERIA \
                    or aura["criteria"].get("kind", "unit") != "unit":
                errors.append(f"battlefields.{battlefield_id}.static_auras[{a_index}] must be {{aura_id, amount != 0, "
                              f"criteria over {sorted(BATTLEFIELD_AURA_CRITERIA)}}}")
        for p_index, modifier in enumerate(battlefield.get("printed_damage_modifiers", []) or []):
            # 2026-10-15 package 13 (C2): a Battlefield's own Bonus Damage, to units at itself (Void Gate)
            if not isinstance(modifier, dict) or set(modifier) != {"amount", "scope"} or not isinstance(modifier["amount"], int) \
                    or isinstance(modifier["amount"], bool) or modifier["amount"] < 1 \
                    or modifier["scope"] != {"kind": "location", "battlefield": battlefield_id}:
                errors.append(f"battlefields.{battlefield_id}.printed_damage_modifiers[{p_index}] must be {{amount >= 1, "
                              f"scope: location at itself}}")
        # Core 190.3.a / 190.3.a.1: a Unit whose controller does not control this
        # Battlefield applies Contested the moment it becomes present there. A Battlefield
        # controlled by one player with an enemy Unit on it and no Contested status is
        # therefore not a state the rules produce, and nothing - scoring least of all -
        # may take it as valid input.
        bf_controller = battlefield.get("controller")
        if bf_controller in players and not battlefield.get("contested"):
            enemies = [o for o in battlefield.get("objects", []) or []
                       if isinstance(state.get("objects", {}).get(o), dict)
                       and state["objects"][o].get("kind") == "unit"
                       and state["objects"][o].get("controller") in players
                       and not same_side(state, state["objects"][o]["controller"], bf_controller)]
            if enemies:
                errors.append(f"battlefields.{battlefield_id} is controlled by {bf_controller} with enemy Unit(s) "
                              f"{enemies} present but not contested (Core 190.3.a)")
        # An uncontrolled Battlefield is one nobody controls, so ANY Unit there applied
        # Contested when it arrived (190.3.a.1), and it stays until control is established
        # (190.3.b) or its applier is gone and Cleanup removes it (323.11, 323.11.a).
        if bf_controller is None and not battlefield.get("contested"):
            present = [o for o in battlefield.get("objects", []) or []
                       if isinstance(state.get("objects", {}).get(o), dict)
                       and state["objects"][o].get("kind") == "unit"]
            if present:
                errors.append(f"battlefields.{battlefield_id} is uncontrolled with Unit(s) {present} present "
                              f"but not contested (Core 190.3.a)")
        identity = battlefield.get("identity")
        if identity is not None and (not isinstance(identity, str) or "@" not in identity or not identity.rsplit("@", 1)[1].isdigit()):
            errors.append(f"battlefields.{battlefield_id}.identity must look like '<id>@<generation>' when supplied")
        # ADR-0008 §4: a Battlefield's own Attack / Defend triggers (Fortified
        # Position). Their controller is the Battlefield's controller at the
        # time they trigger (190.6.a), so the descriptor names none.
        # 2026-09-28: and its "When a unit moves from here" (watchers.BATTLEFIELD_WATCH_FIELDS)
        for trigger_field in ("attack_triggers", "defend_triggers", "conquer_triggers", "hold_triggers", "move_from_triggers"):
            triggers = battlefield.get(trigger_field, [])
            if not isinstance(triggers, list):
                errors.append(f"battlefields.{battlefield_id}.{trigger_field} must be an array")
                continue
            for trigger_index, trigger in enumerate(triggers):
                # effect_program_hash is optional, as on an object's descriptor: the ID names
                # the program, the hash says it is still that program (resolution_bridge).
                if isinstance(trigger, dict) and "effect_program_hash" in trigger and not (
                        isinstance(trigger["effect_program_hash"], str) and trigger["effect_program_hash"].startswith("sha256:")):
                    errors.append(f"battlefields.{battlefield_id}.{trigger_field}[{trigger_index}].effect_program_hash must be a sha256 content hash")
                    continue
                # package 9 (The Grand Plaza, Core 383.2.a.1): "When you hold here, if you have 7+ units here" - the
                # conditional statement right after the Condition is part of it, read as the Hold is processed;
                # only on a hold trigger, only {kind controls_units, count, location here}
                if isinstance(trigger, dict) and "condition" in trigger:
                    cond = trigger["condition"]
                    bad = (trigger_field != "hold_triggers" or not isinstance(cond, dict) or cond.get("kind") != "controls_units"
                           or set(cond) != {"kind", "count", "location"} or cond.get("location") != "here"
                           or bool(validate_condition(cond)))
                    if bad:
                        errors.append(f"battlefields.{battlefield_id}.{trigger_field}[{trigger_index}].condition is read only on a "
                                      f"hold trigger, as {{kind: controls_units, count, location: here}} (Core 383.2.a.1)")
                        continue
                if (not isinstance(trigger, dict) or set(trigger) - {"effect_program_hash", "condition"} != {"trigger_id", "controller_order", "effect_program_id", "optional_at_finalize"}
                        or not isinstance(trigger["trigger_id"], str) or not trigger["trigger_id"] or not isinstance(trigger["controller_order"], int) or trigger["controller_order"] < 0
                        or not isinstance(trigger["effect_program_id"], str) or not trigger["effect_program_id"] or not isinstance(trigger["optional_at_finalize"], bool)):
                    errors.append(f"battlefields.{battlefield_id}.{trigger_field}[{trigger_index}] must carry trigger_id, controller_order, effect_program_id, optional_at_finalize (the controller is the Battlefield's, 190.6.a)")
        # ADR-0012 §3 / Core 107.3.b: every Battlefield has one Facedown Zone
        # with a capacity. The zone is public; the cards in it are private to
        # the player who hid them (108.2.b, 128.4).
        if "move_restrictions" in battlefield:
            errors.extend(move_restriction_errors(battlefield_id, battlefield["move_restrictions"]))
        facedown = battlefield.get("facedown")
        if facedown is not None:
            if not isinstance(facedown, dict) or set(facedown) - {"capacity", "cards"}:
                errors.append(f"battlefields.{battlefield_id}.facedown must be {{capacity?, cards}}")
            else:
                capacity = facedown.get("capacity", 1)
                cards = facedown.get("cards", [])
                if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 0:
                    errors.append(f"battlefields.{battlefield_id}.facedown.capacity must be a non-negative integer")
                if not isinstance(cards, list):
                    errors.append(f"battlefields.{battlefield_id}.facedown.cards must be an array")
                    cards = []
                elif isinstance(capacity, int) and not isinstance(capacity, bool) and len(cards) > capacity:
                    errors.append(f"battlefields.{battlefield_id}.facedown holds {len(cards)} cards over its capacity {capacity} (Core 107.3.f)")
                seen_facedown: set[str] = set()
                for f_index, entry in enumerate(cards):
                    label = f"battlefields.{battlefield_id}.facedown.cards[{f_index}]"
                    if not isinstance(entry, dict) or set(entry) != {"object_id", "controller", "hidden_on_turn"}:
                        errors.append(f"{label} must carry object_id, controller, hidden_on_turn")
                        continue
                    if entry["object_id"] not in objects:
                        errors.append(f"{label} names an unknown object")
                    else:
                        occupancy[entry["object_id"]].append(f"facedown:{battlefield_id}")
                    if entry["object_id"] in seen_facedown:
                        errors.append(f"{label}.object_id is duplicated")
                    seen_facedown.add(entry["object_id"])
                    if entry["controller"] not in players:
                        errors.append(f"{label}.controller is not a player")
                    if not isinstance(entry["hidden_on_turn"], str) or not entry["hidden_on_turn"]:
                        errors.append(f"{label}.hidden_on_turn must be a non-empty turn id")
        ids = battlefield["objects"]
        if len(ids) != len(set(ids)):
            errors.append(f"battlefields.{battlefield_id}.objects contains duplicates")
        for object_id in ids:
            if object_id not in objects:
                errors.append(f"unknown object {object_id!r} at battlefield {battlefield_id}")
            else:
                occupancy[object_id].append(f"battlefield:{battlefield_id}")

    # The chain is one shared zone (Core 328), not a per-player zone: cards
    # played and not yet resolved sit here keyed by their timing item id.
    chain_items = state.get("chain_items", {})
    if not isinstance(chain_items, dict):
        errors.append("chain_items must be an object keyed by chain item id")
        chain_items = {}
    for item_id, entry in chain_items.items():
        is_ability = isinstance(entry, dict) and "source_object" in entry
        # DP-93: a chain item may carry the receipt of the play that made it, so
        # a cost comparison can read what that spell actually cost rather than
        # only what is printed on it.
        allowed = ({"source_object", "ability_id", "controller", "effect_program_id", "mode_selection", "repeat", "counterable", "cost_receipt", "played_targets"} if is_ability
                   else {"card", "controller", "effect_program_id", "entry_location", "mode_selection", "repeat", "counterable", "cost_receipt", "played_targets",
                         # Core 419.4.a: the play's event, recorded at Finalize, read when the card resolves
                         "played_event",
                         # Core 811.1.d.3: the battlefield the card was played from Hidden at
                         "played_from_hidden",
                         # package 12: how its choices were restricted there, when not the default (753.3 binds new choices)
                         "hidden_targeting",
                         "limited_play",
                         # 2026-10-06 package 9 (Kai'Sa - Evolutionary): Core 390.3.a, bound by recycle_when_leaving_chain
                         "leave_replacement",
                         # 2026-10-13 package 11 (Mystic Reversal): its control changed on the Chain {from, to}
                         "control_changed"})
        needed = {"source_object", "ability_id", "controller"} if is_ability else {"card", "controller"}
        if not isinstance(item_id, str) or not item_id or not isinstance(entry, dict) or set(entry) - allowed or not needed <= set(entry):
            errors.append(f"chain_items.{item_id} must carry card and controller (or source_object, ability_id and controller for an activated ability, ADR-0011 §4)")
            continue
        if "counterable" in entry and not isinstance(entry["counterable"], bool):
            errors.append(f"chain_items.{item_id}.counterable must be boolean (ADR-0011 §5)")
        leave = entry.get("leave_replacement")
        if leave is not None and (not isinstance(leave, dict) or set(leave) != {"kind", "created_by", "effect_id"}
                                  or leave.get("kind") not in {"recycle", "banish"} or not isinstance(leave.get("created_by"), str)):
            errors.append(f"chain_items.{item_id}.leave_replacement must be {{kind: recycle | banish, created_by, effect_id}} "
                          f"(Core 390.3.a; package 11: banish_this)")
        # Core 355.5 / 355.15: the targets chosen at play ride with the entry to resolution; GPT 2026-09-29
        # (Core 355.4): so do the Move destinations chosen there, each a location token
        played = entry.get("played_targets")

        def _played_entry_ok(e):
            if not isinstance(e, dict) or e.get("stage") != "play_declaration" or not isinstance(e.get("decision_id"), str):
                return False
            if e.get("kind") == "target_selection":
                return isinstance(e.get("value"), list)
            return e.get("kind") == "location_selection" and isinstance(e.get("value"), str) and ":" in e["value"]
        if played is not None and (not isinstance(played, list) or not played or not all(_played_entry_ok(e) for e in played)):
            errors.append(f"chain_items.{item_id}.played_targets must be the play_declaration target selections and Move "
                          f"destinations it was played with")
        if "cost_receipt" in entry:
            errors.extend(f"chain_items.{item_id}.cost_receipt {e}" for e in _receipt_errors(entry["cost_receipt"]))
        if "limited_play" in entry:
            # 2026-09-28 (package 6, Core 419.3, 354): a card an effect's resolution moved to the Chain -
            # who granted the play, where the card came from (to undo step 1 if the play is cancelled,
            # Core 358.5), and what the effect changes about its cost (356.1.b)
            errors.extend(f"chain_items.{item_id}.limited_play {e}"
                          for e in _limited_play_record_errors(entry["limited_play"], players))
        repeat = entry.get("repeat")
        if repeat is not None and (not isinstance(repeat, dict) or set(repeat) - {"executions", "modes"} or not isinstance(repeat.get("executions"), int) or isinstance(repeat.get("executions"), bool) or repeat["executions"] < 1
                                   or ("modes" in repeat and (not isinstance(repeat["modes"], list) or len(repeat["modes"]) != repeat["executions"] or any(not isinstance(m, dict) or set(m) != {"decision_id", "option_id"} for m in repeat["modes"])))):
            errors.append(f"chain_items.{item_id}.repeat must be {{executions >= 1, modes?: one per extra execution}} (Core 820.1.d)")
        if is_ability:
            # ADR-0011 §4 / Core 402: an ability on the chain has no card; its
            # source stays where it is (it may even have left the board as a cost).
            if entry["source_object"] not in objects:
                errors.append(f"chain_items.{item_id}.source_object is unknown")
            if not isinstance(entry["ability_id"], str) or not entry["ability_id"]:
                errors.append(f"chain_items.{item_id}.ability_id must be a non-empty string")
            if entry["controller"] not in players:
                errors.append(f"chain_items.{item_id}.controller is not a player")
            if "effect_program_id" in entry and (not isinstance(entry["effect_program_id"], str) or not entry["effect_program_id"]):
                errors.append(f"chain_items.{item_id}.effect_program_id must be a non-empty string when supplied")
            continue
        mode = entry.get("mode_selection")
        if mode is not None and (not isinstance(mode, dict) or set(mode) != {"decision_id", "option_id"} or any(not isinstance(mode[k], str) or not mode[k] for k in mode)):
            errors.append(f"chain_items.{item_id}.mode_selection must be {{decision_id, option_id}} (ADR-0011 §2)")
        location = entry.get("entry_location")
        if location is not None:
            if not isinstance(location, dict) or location.get("kind") not in {"base", "battlefield"} or set(location) - {"kind", "battlefield"}:
                errors.append(f"chain_items.{item_id}.entry_location must be {{kind: base}} or {{kind: battlefield, battlefield}}")
            elif location["kind"] == "battlefield" and location.get("battlefield") not in battlefields:
                errors.append(f"chain_items.{item_id}.entry_location names an unknown battlefield")
        if entry["controller"] not in players:
            errors.append(f"chain_items.{item_id}.controller is not a player")
        if entry["card"] not in objects:
            errors.append(f"unknown object {entry['card']!r} on the chain as {item_id}")
        else:
            occupancy[entry["card"]].append(f"chain:{item_id}")
        if "effect_program_id" in entry and (not isinstance(entry["effect_program_id"], str) or not entry["effect_program_id"]):
            errors.append(f"chain_items.{item_id}.effect_program_id must be a non-empty string when supplied")

    # ADR-0007 §8: every "this turn" effect is stamped with the turn it belongs
    # to, so an Expiration Step never clears another turn's effects.
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    if not isinstance(turn_id, str) or not turn_id:
        errors.append("turn_id must be a non-empty string when supplied")
    # 2026-10-13 package 11 (Time Warp, Core 735-738): the Additional Turns queued after the current turn, the next
    # first; and, while they are taken, the player whose regular turn the queue resumes after
    queued = state.get("additional_turns", [])
    if not isinstance(queued, list) or any(not isinstance(q, dict) or set(q) != {"player", "created_by", "effect_id", "turn_id"}
                                           or q.get("player") not in players for q in queued):
        errors.append("additional_turns must be an array of {player, created_by, effect_id, turn_id}, each a known player (Core 735)")
    if "turn_queue_resume_after" in state and state["turn_queue_resume_after"] not in players:
        errors.append("turn_queue_resume_after must be a known player (Core 737)")
    turn_effects = state.get("turn_effects", [])
    if not isinstance(turn_effects, list):
        errors.append("turn_effects must be an array")
        turn_effects = []
    effect_ids: set[str] = set()
    for index, effect in enumerate(turn_effects):
        label = f"turn_effects[{index}]"
        if not isinstance(effect, dict) or not {"effect_id", "kind", "controller", "turn_id"} <= set(effect) or set(effect) - {"effect_id", "kind", "controller", "turn_id", "value", "source", "object_id"}:
            errors.append(f"{label} must carry effect_id, kind, controller, turn_id (and value/source/object_id)")
            continue
        if not isinstance(effect["effect_id"], str) or not effect["effect_id"] or effect["effect_id"] in effect_ids:
            errors.append(f"{label}.effect_id is invalid or duplicated")
        effect_ids.add(effect.get("effect_id", ""))
        if effect["controller"] not in players:
            errors.append(f"{label}.controller is not a player")
        if not isinstance(effect["turn_id"], str) or not effect["turn_id"]:
            errors.append(f"{label}.turn_id must be a non-empty string")
        if effect["kind"] in {"entry_state_for_played_units", "entry_state_for_next_played_unit"} and effect.get("value") not in {"ready", "exhausted"}:
            errors.append(f"{label}.value must be ready or exhausted")
        if effect["kind"] == "hide_ignoring_costs" and effect.get("value") not in TURN_EFFECT_VALUES["hide_ignoring_costs"]:
            errors.append(f"{label}.value must be one of {sorted(TURN_EFFECT_VALUES['hide_ignoring_costs'])}")
        if effect["kind"] == "cards_play_prohibited" and effect.get("value") not in TURN_EFFECT_VALUES["cards_play_prohibited"]:
            errors.append(f"{label}.value must be one of {sorted(TURN_EFFECT_VALUES['cards_play_prohibited'])}")
        if effect["kind"] == "next_spell_cost_reduction" and (not isinstance(effect.get("value"), int)
                                                             or isinstance(effect.get("value"), bool) or effect["value"] < 1):
            errors.append(f"{label}.value must be the positive Energy amount of the discount (Core 356.4)")
        if effect["kind"] == "buff_bonus_might" and (not isinstance(effect.get("value"), int)
                                                    or isinstance(effect.get("value"), bool) or effect["value"] < 1):
            errors.append(f"{label}.value must be the positive extra Might each buff gives")
        if effect["kind"] == "next_spell_bonus_damage" and (not isinstance(effect.get("value"), int)
                                                           or isinstance(effect.get("value"), bool) or effect["value"] < 1):
            errors.append(f"{label}.value must be the positive Bonus Damage amount (Core 714.1)")
        if effect["kind"] == "stunned_unit":
            if effect.get("object_id") not in objects:
                errors.append(f"{label}.object_id must name an object in this state")
            elif not objects[effect["object_id"]].get("stunned"):
                errors.append(f"{label} says {effect['object_id']!r} is Stunned; the object does not")
    # A Stunned object with nothing to expire it would stay Stunned for the
    # rest of the game (Core 423.2). The status and its owner travel together.
    owned = {e.get("object_id") for e in turn_effects if isinstance(e, dict) and e.get("kind") == "stunned_unit"}
    for object_id, obj in objects.items():
        if isinstance(obj, dict) and obj.get("stunned") and object_id not in owned:
            errors.append(f"objects.{object_id}.stunned has no turn_effects entry to expire it (Core 423.2, 317.2.d)")
    # ADR-0009 §1: the Mode of Play; scoring never guesses a Victory Score.
    mode = state.get("mode")
    if mode is not None and (not isinstance(mode, dict) or set(mode) - {"victory_score", "teams", "id", "first_turn"} or not isinstance(mode.get("victory_score"), int) or isinstance(mode.get("victory_score"), bool) or mode["victory_score"] < 1 or not isinstance(mode.get("teams", False), bool)):
        errors.append("mode must be {victory_score: positive integer, teams?: boolean, id?, first_turn?} (Core 456.3, 483)")
    elif mode is not None:
        # ADR-0010 §6: the sanctioned Mode of Play or explicit First Turn facts.
        if "id" in mode and mode["id"] not in SANCTIONED_MODES:
            errors.append("mode.id must name a sanctioned Mode of Play (Core 484–489)")
        first = mode.get("first_turn")
        if first is not None and (not isinstance(first, dict) or set(first) - {"extra_channel", "skip_draw"} or any(not isinstance(first.get(k, []), list) or any(p not in state["players"] for p in first.get(k, [])) for k in ("extra_channel", "skip_draw"))):
            errors.append("mode.first_turn must be {extra_channel?: [players], skip_draw?: [players]} (Core 483.7)")
    # ADR-0007 §5: Bonus Damage sources. A source is an object (active while on
    # the board) or a Battlefield (active while it exists) — never pruned by the
    # object rule.
    modifiers = state.get("damage_modifiers", [])
    if not isinstance(modifiers, list):
        errors.append("damage_modifiers must be an array")
        modifiers = []
    modifier_ids: set[str] = set()
    for index, modifier in enumerate(modifiers):
        label = f"damage_modifiers[{index}]"
        if not isinstance(modifier, dict) or set(modifier) != {"modifier_id", "source_object", "controller", "amount", "scope"}:
            errors.append(f"{label} must carry exactly modifier_id, source_object, controller, amount, scope")
            continue
        if not isinstance(modifier["modifier_id"], str) or not modifier["modifier_id"] or modifier["modifier_id"] in modifier_ids:
            errors.append(f"{label}.modifier_id is invalid or duplicated")
        modifier_ids.add(modifier.get("modifier_id", ""))
        if modifier["source_object"] not in objects and modifier["source_object"] not in battlefields:
            errors.append(f"{label}.source_object is neither an object nor a battlefield")
        if modifier["controller"] not in players:
            errors.append(f"{label}.controller is not a player")
        if not isinstance(modifier["amount"], int) or modifier["amount"] < 1:
            errors.append(f"{label}.amount must be a positive integer (Core 714.1)")
        scope = modifier["scope"]
        if not isinstance(scope, dict) or not isinstance(scope.get("kind"), str):
            errors.append(f"{label}.scope must carry a kind")
        elif scope["kind"] == "location" and (set(scope) != {"kind", "battlefield"} or scope.get("battlefield") not in battlefields):
            errors.append(f"{label}.scope.location must name a known battlefield")
        elif scope["kind"] == "controller_sources" and set(scope) != {"kind"}:
            errors.append(f"{label}.scope.controller_sources carries no other fields")

    # ADR-0013 §1: the canonical continuous effects. A state may arrive with the
    # legacy families instead (they are translated at the boundary), but never
    # with both — that is the shape that would be read twice.
    continuous = state.get("continuous_effects")
    if continuous is not None:
        legacy_present = [f for f in LEGACY_EFFECT_FIELDS if state.get(f)] + [
            f"objects.{oid}.{f}" for oid, obj in objects.items() if isinstance(obj, dict) for f in LEGACY_EFFECT_FIELDS if obj.get(f)]
        if legacy_present:
            errors.append(f"continuous_effects is the canonical representation; a state carrying it may not also carry {sorted(legacy_present)[:4]} (ADR-0013 §1)")
        if not isinstance(continuous, list):
            errors.append("continuous_effects must be an array")
            continuous = []
        seen_effects: set[str] = set()
        for index, effect in enumerate(continuous):
            label = f"continuous_effects[{index}]"
            required = {"effect_id", "kind", "source", "affects", "layer", "timestamp", "value", "duration"}
            optional = {"sublayer", "condition", "snapshot", "passive"}
            if not isinstance(effect, dict) or not required <= set(effect) or set(effect) - required - optional:
                errors.append(f"{label} must carry exactly {sorted(required)} (and optionally {sorted(optional)})")
                continue
            if not isinstance(effect["effect_id"], str) or not effect["effect_id"] or effect["effect_id"] in seen_effects:
                errors.append(f"{label}.effect_id is invalid or duplicated")
            seen_effects.add(effect.get("effect_id", ""))
            if effect["kind"] not in CONTINUOUS_KINDS:
                errors.append(f"{label}.kind must be one of {sorted(CONTINUOUS_KINDS)}")
            elif effect["layer"] != KIND_LAYER[effect["kind"]]:
                errors.append(f"{label}.layer must be {KIND_LAYER[effect['kind']]} for {effect['kind']} (Core 477)")
            source = effect["source"]
            if not isinstance(source, dict) or set(source) - {"object", "identity", "name"} or "object" not in source:
                errors.append(f"{label}.source must be {{object, identity?, name?}}")
            elif source["object"] not in objects and source["object"] not in battlefields:
                errors.append(f"{label}.source.object is neither an object nor a battlefield")
            affects = effect["affects"]
            if not isinstance(affects, dict) or affects.get("scope") not in {"object", "criteria"}:
                errors.append(f"{label}.affects.scope must be object or criteria")
            elif affects["scope"] == "object":
                if set(affects) - {"scope", "object", "identity"} or "object" not in affects:
                    errors.append(f"{label}.affects must be {{scope: object, object, identity?}}")
                elif affects["object"] not in objects:
                    errors.append(f"{label}.affects.object is unknown")
            elif set(affects) - {"scope", "criteria"} or not isinstance(affects.get("criteria"), dict):
                errors.append(f"{label}.affects.criteria must be an object")
            if not isinstance(effect["timestamp"], int) or isinstance(effect["timestamp"], bool) or effect["timestamp"] < 0:
                errors.append(f"{label}.timestamp must be a non-negative integer (Core 480)")
            duration = effect["duration"]
            if not isinstance(duration, dict) or duration.get("kind") not in CONTINUOUS_DURATIONS or set(duration) - {"kind", "turn_id", "combat_id"}:
                errors.append(f"{label}.duration.kind must be one of {sorted(CONTINUOUS_DURATIONS)}")
            elif duration["kind"] == "this_turn" and not duration.get("turn_id"):
                errors.append(f"{label}.duration this_turn carries its turn_id (317.2.c)")
            elif duration["kind"] == "this_combat" and not duration.get("combat_id"):
                errors.append(f"{label}.duration this_combat carries its combat_id (466.7.c)")
            value = effect["value"]
            kind = effect["kind"]
            if kind in {"might_set", "might_arithmetic"}:
                if not isinstance(value, dict) or set(value) - {"amount", "mode", "minimum", "maximum", "snapshot_amount", "per"} or not isinstance(value.get("amount"), int) or isinstance(value.get("amount"), bool):
                    errors.append(f"{label}.value must be {{amount, mode?, minimum?, maximum?, snapshot_amount?, per?}}")
                elif "per" in value and (not isinstance(value["per"], dict) or set(value["per"]) != {"kind"}
                                         or value["per"]["kind"] not in MIGHT_PER_KINDS or not effect.get("passive", False)
                                         or kind != "might_arithmetic" or value.get("mode", "delta") != "delta" or "snapshot_amount" in value):
                    errors.append(f"{label}.value.per must be one of {sorted(MIGHT_PER_KINDS)} on a passive delta arithmetic effect (Core 477.3.b)")
                elif "snapshot_amount" in value and (not isinstance(value["snapshot_amount"], int) or isinstance(value["snapshot_amount"], bool)):
                    errors.append(f"{label}.value.snapshot_amount must be an integer (Core 477.3.b)")
                elif "snapshot_amount" in value and effect.get("passive", False):
                    errors.append(f"{label} is passive and carries a snapshot_amount; a passive "
                                  f"ability's limitation is not snapshotted (Core 477.3.b)")
                elif "snapshot_amount" in value and not {"minimum", "maximum"} & set(value):
                    errors.append(f"{label}.value.snapshot_amount without a minimum or maximum; "
                                  f"there is no limitation to snapshot (Core 477.3.b)")
                elif value.get("mode", "delta") not in MIGHT_MODES:
                    errors.append(f"{label}.value.mode must be one of {sorted(MIGHT_MODES)}")
                elif kind == "might_arithmetic" and effect.get("sublayer") not in {"increase", "decrease"}:
                    errors.append(f"{label}.sublayer must be increase or decrease (Core 477.3.a)")
            elif kind in {"keyword_grant", "keyword_remove"}:
                if not isinstance(value, dict) or set(value) - {"keyword", "value"} or not isinstance(value.get("keyword"), str) or not value["keyword"]:
                    errors.append(f"{label}.value must be {{keyword, value?}}")
                elif "value" in value and (not isinstance(value["value"], int) or isinstance(value["value"], bool) or value["value"] < 1):
                    errors.append(f"{label}.value.value must be a positive integer")
            elif kind == "bonus_damage":
                if not isinstance(value, dict) or set(value) != {"amount"} or not isinstance(value["amount"], int) or value["amount"] < 1:
                    errors.append(f"{label}.value must be {{amount: positive integer}} (Core 714.1)")
            elif kind == "ability_append":
                triggers = value.get("triggers") if isinstance(value, dict) else None
                if not isinstance(value, dict) or set(value) != {"triggers"} or not isinstance(triggers, dict) or not triggers:
                    errors.append(f"{label}.value must be {{triggers: {{field: [descriptor]}}}} (Core 477.2)")
                elif any(field not in APPENDABLE_TRIGGER_FIELDS or not isinstance(rows, list) or not rows for field, rows in triggers.items()):
                    errors.append(f"{label}.value.triggers names a field that is not an appendable ability list")
            elif kind == "copy_traits":
                if (not isinstance(value, dict) or set(value) - {"source_object", "traits", "request_id"} or not {"source_object", "traits"} <= set(value)
                        or value["source_object"] not in objects or not isinstance(value["traits"], list) or not value["traits"]):
                    errors.append(f"{label}.value must be {{source_object, traits, request_id?}} (Core 477.1)")
                elif set(value["traits"]) - COPYABLE_TRAITS:
                    errors.append(f"{label}.value.traits {sorted(set(value['traits']) - COPYABLE_TRAITS)} are not modelled (unsupported: copy_unmodelled_traits)")
            if "passive" in effect and not isinstance(effect["passive"], bool):
                errors.append(f"{label}.passive must be boolean")
            if effect.get("condition") is not None:
                errors.extend(f"{label}.{e}" for e in validate_condition(effect["condition"]))
    # ADR-0008 §5: bounded external Might auras (a source on the board or a
    # Battlefield; a named condition read by effective_might).
    auras = state.get("might_auras", [])
    if not isinstance(auras, list):
        errors.append("might_auras must be an array")
        auras = []
    aura_ids: set[str] = set()
    for index, aura in enumerate(auras):
        label = f"might_auras[{index}]"
        if not isinstance(aura, dict) or set(aura) != {"modifier_id", "source_object", "controller", "amount", "condition"}:
            errors.append(f"{label} must carry exactly modifier_id, source_object, controller, amount, condition")
            continue
        if not isinstance(aura["modifier_id"], str) or not aura["modifier_id"] or aura["modifier_id"] in aura_ids:
            errors.append(f"{label}.modifier_id is invalid or duplicated")
        aura_ids.add(aura.get("modifier_id", ""))
        if aura["source_object"] not in objects and aura["source_object"] not in battlefields:
            errors.append(f"{label}.source_object is neither an object nor a battlefield")
        if aura["controller"] not in players:
            errors.append(f"{label}.controller is not a player")
        if not isinstance(aura["amount"], int) or isinstance(aura["amount"], bool):
            errors.append(f"{label}.amount must be an integer")
        if not isinstance(aura["condition"], dict) or aura["condition"].get("kind") not in AURA_CONDITION_KINDS or set(aura["condition"]) != {"kind"}:
            errors.append(f"{label}.condition.kind must be one of {sorted(AURA_CONDITION_KINDS)}")

    for object_id, obj in objects.items():
        if not isinstance(obj, dict):
            errors.append(f"objects.{object_id} must be an object")
            continue
        if obj.get("owner") not in players or obj.get("controller") not in players:
            errors.append(f"objects.{object_id} has unknown owner/controller")
        if obj.get("kind") not in OBJECT_KINDS:
            errors.append(f"objects.{object_id}.kind is invalid")
        elif obj["kind"] == "legend":
            # Core 107.4.d: a legend exists only in the Legend Zone or Banishment.
            where = occupancy.get(object_id, [])
            if where and not all(place.endswith(":legend_zone") or place.endswith(":banishment") for place in where):
                errors.append(f"objects.{object_id} is a legend; a legend exists only in a Legend Zone or Banishment (Core 107.4.d), not {where}")
        if "champion_legend" in obj and not isinstance(obj["champion_legend"], bool):
            errors.append(f"objects.{object_id}.champion_legend must be boolean when supplied (Core 107.4.d)")
        if "champion_unit" in obj and not isinstance(obj["champion_unit"], bool):
            errors.append(f"objects.{object_id}.champion_unit must be boolean when supplied (Core 103.2.a.2)")
        if "name" in obj and (not isinstance(obj["name"], str) or not obj["name"]):
            errors.append(f"objects.{object_id}.name must be a non-empty string when supplied")
        for field in ("base_might", "damage"):
            if not isinstance(obj.get(field), int) or obj.get(field, -1) < 0:
                errors.append(f"objects.{object_id}.{field} must be a non-negative integer")
        if not isinstance(obj.get("exhausted"), bool):
            errors.append(f"objects.{object_id}.exhausted must be boolean")
        # ADR-0008 §1: a Unit's current Combat designation, kept in step by Cleanup (323.2).
        designation = obj.get("combat_designation")
        if designation is not None and (not isinstance(designation, dict) or set(designation) != {"combat_id", "role"} or not isinstance(designation["combat_id"], str)
                                        or not designation["combat_id"] or designation["role"] not in COMBAT_ROLES):
            errors.append(f"objects.{object_id}.combat_designation must be {{combat_id, role: attacker|defender}}")
        elif designation is not None and obj.get("kind") != "unit":
            errors.append(f"objects.{object_id}.combat_designation applies to Units only (464.2.c.3)")
        if "stunned" in obj and not isinstance(obj["stunned"], bool):
            errors.append(f"objects.{object_id}.stunned must be boolean (Core 423.1.a)")
        # 2026-09-27 package 6: a card's printed tags, as printed ("Poro", "Dragon") - a characteristic
        # (Core 133.8, 133.8.a, 143.1), read through object_tags()
        if "tags" in obj and (not isinstance(obj["tags"], list) or any(not isinstance(t, str) or not t for t in obj["tags"])
                              or len(set(obj["tags"])) != len(obj["tags"])):
            errors.append(f"objects.{object_id}.tags must be a list of distinct non-empty strings, as printed (Core 133.8)")
        # Round H: an optional additional cost the card itself offers, of
        # which Accelerate is one printed instance. Only the card may offer it,
        # and only for its own play (Core 356.2.b, 820.1).
        for o_index, offer in enumerate(obj.get("optional_additional_costs", []) or []):
            label = f"objects.{object_id}.optional_additional_costs[{o_index}]"
            if not isinstance(offer, dict) or set(offer) - {"cost_offer_id", "energy", "payment"} or "cost_offer_id" not in offer or "payment" not in offer:
                errors.append(f"{label} must be {{cost_offer_id, payment, energy?}}")
                continue
            if not isinstance(offer["cost_offer_id"], str) or not offer["cost_offer_id"]:
                errors.append(f"{label}.cost_offer_id must be a non-empty string")
            if "energy" in offer and (not isinstance(offer["energy"], int) or isinstance(offer["energy"], bool) or offer["energy"] < 0):
                errors.append(f"{label}.energy must be a non-negative integer")
            payment = offer["payment"]
            if not isinstance(payment, dict) or payment.get("kind") not in {"power_own_domain", "power_any", "energy", "power"}:
                errors.append(f"{label}.payment.kind must be power_own_domain, power_any, energy or power")
            elif payment.get("kind") == "power":
                # 2026-10-08 package 10 (Clockwork Keeper): Power of one printed Domain
                if set(payment) != {"kind", "domain", "amount"} or not isinstance(payment.get("domain"), str) \
                        or not isinstance(payment.get("amount"), int) or isinstance(payment.get("amount"), bool) or payment["amount"] < 1:
                    errors.append(f"{label}.payment must be {{kind: power, domain, amount >= 1}}")
            elif not isinstance(payment.get("amount"), int) or isinstance(payment.get("amount"), bool) or payment["amount"] < 1 or set(payment) - {"kind", "amount"}:
                errors.append(f"{label}.payment must be {{kind, amount >= 1}}")
        offer_ids = [o.get("cost_offer_id") for o in (obj.get("optional_additional_costs") or []) if isinstance(o, dict)]
        if len(offer_ids) != len(set(offer_ids)):
            errors.append(f"objects.{object_id}.optional_additional_costs have duplicate cost_offer_ids")
        errors.extend(_printed_cost_errors(object_id, obj, offer_ids))
        errors.extend(_granted_discount_errors(object_id, obj))

        # Round H / Core 805: a card's printed Domains. Absent means the data
        # does not say, which is not the same as "no Domain" - an empty list
        # says that, and only an empty list lets Accelerate take any Power.
        # 2026-10-13 package 11 (Heimerdinger - Inventor): the activated abilities a permanent prints, by id - what a copy
        # of one is checked against - and the kinds whose [Exhaust] abilities a permanent has as well (Core 377)
        printed = obj.get("activated_abilities")
        # 2026-10-15 package 13 (C2): a row also says the ability's timing, its kind (standard or [Add]), its text costs
        # (cost.additional, as an activation declares them) and its own activation conditions (Core 377.2.b) - what a
        # catalogued object's activation must declare (play_transaction.catalogued_declaration_problem)
        if printed is not None and (not isinstance(printed, dict) or any(
                not isinstance(a, dict) or set(a) - {"cost", "effect_program_id", "timing", "ability_kind", "activation_conditions"}
                or not isinstance(a.get("effect_program_id"), str)
                or not isinstance(a.get("cost"), dict) or set(a["cost"]) - {"energy", "power", "exhaust", "additional"}
                or not isinstance(a["cost"].get("energy", 0), int) or not isinstance(a["cost"].get("power", {}), dict)
                or not isinstance(a["cost"].get("exhaust", False), bool)
                or not isinstance(a["cost"].get("additional", []), list)
                or any(not isinstance(c, dict) or not {"cost_id", "mandatory", "payment"} <= set(c) for c in a["cost"].get("additional", []))
                or a.get("timing", "default") not in {"default", "action", "reaction"}
                or a.get("ability_kind", "standard") not in {"standard", "add"}
                or not isinstance(a.get("activation_conditions", []), list) for a in printed.values())):
            errors.append(f"objects.{object_id}.activated_abilities maps ability ids to {{cost: {{energy, power, exhaust, "
                          f"additional?}}, effect_program_id, timing?, ability_kind?, activation_conditions?}}")
        # 2026-10-15 package 13 (C2): the closed environment's catalogue key of the card this object is - a catalogued
        # object is played and activated exactly as its record says
        if "card_ref" in obj and (not isinstance(obj["card_ref"], str) or not obj["card_ref"]):
            errors.append(f"objects.{object_id}.card_ref must be a non-empty string")
        # package 12 (Udyr - Wildman): the modes chosen this turn with this object's "choose one you've not chosen this
        # turn" ability - {identity, turn_id, by: {player: [option ids]}}; read only while identity and turn are current
        chosen = obj.get("modes_chosen")
        if chosen is not None and (not isinstance(chosen, dict) or set(chosen) != {"identity", "turn_id", "by"}
                                   or not isinstance(chosen["by"], dict)
                                   or any(not isinstance(v, list) or any(not isinstance(o, str) for o in v)
                                          for v in chosen["by"].values())):
            errors.append(f"objects.{object_id}.modes_chosen must be {{identity, turn_id, by: {{player: [option ids]}}}}")
        copies = obj.get("has_exhaust_abilities_of")
        if copies is not None and (not isinstance(copies, list) or not copies or set(copies) - {"legend", "unit", "gear"}
                                   or len(copies) != len(set(copies))):
            errors.append(f"objects.{object_id}.has_exhaust_abilities_of lists kinds among legend, unit, gear")
        for flag in [*BATTLEFIELD_RESTRICTIONS.values(), *HERE_RESTRICTIONS.values()]:
            if flag in obj and obj[flag] is not True:
                errors.append(f"objects.{object_id}.{flag} is true when present (package 11, Mageseeker Warden)")
        domains = obj.get("domains")
        if domains is not None and (not isinstance(domains, list)
                                    or any(not isinstance(d, str) or not d for d in domains)
                                    or len(domains) != len(set(domains))):
            errors.append(f"objects.{object_id}.domains must be a list of distinct non-empty domain names")

        # Round H: a fixed Energy reduction the card's own text declares, gated
        # by a condition.v1 leaf. Deliberately narrow: no X, no value read off
        # the board, no Power or Domain, and no source but this card.
        # GPT 2026-09-22 (Legion, option b): an activated ability gated by a Dependent
        # Keyword does not exist while its condition fails (812.1.b.1). The condition is
        # the source's, per ability id, so a declaration cannot leave it out.
        ability_conditions = obj.get("ability_conditions")
        if ability_conditions is not None:
            if not isinstance(ability_conditions, dict) or any(not isinstance(k, str) or not k for k in ability_conditions):
                errors.append(f"objects.{object_id}.ability_conditions must map ability ids to condition.v1")
            else:
                for ability_id, condition in ability_conditions.items():
                    errors.extend(f"objects.{object_id}.ability_conditions[{ability_id}] {e}" for e in validate_condition(condition, "condition"))
        for m_index, modification in enumerate(obj.get("printed_cost_modifications", []) or []):
            label = f"objects.{object_id}.printed_cost_modifications[{m_index}]"
            if not isinstance(modification, dict) or set(modification) - {"modification_id", "kind", "amount", "condition", "per_each"} \
                    or not {"modification_id", "kind", "amount"} <= set(modification):
                errors.append(f"{label} must be {{modification_id, kind, amount, condition?, per_each?}}")
                continue
            per_each = modification.get("per_each")
            if per_each is not None and per_each != {"kind": HIGHEST_MIGHT_YOU_CONTROL} and (
                    not isinstance(per_each, dict) or per_each.get("kind") != "zone_count_at_least"
                    or set(per_each) - {"kind", "zone", "player"} or per_each.get("zone") not in PUBLIC_COUNT_ZONES):
                errors.append(f"{label}.per_each must count a public zone of the controller ({sorted(PUBLIC_COUNT_ZONES)}), "
                              f"or be {{kind: {HIGHEST_MIGHT_YOU_CONTROL}}} (Core 356.4)")
            if modification["kind"] != "energy_reduction":
                errors.append(f"{label}.kind must be energy_reduction; nothing else is modelled (Round H)")
            if not isinstance(modification["amount"], int) or isinstance(modification["amount"], bool) or modification["amount"] < 1:
                errors.append(f"{label}.amount must be a positive fixed number of Energy")
            if "condition" in modification:
                errors.extend(f"{label}.condition {e}" for e in validate_condition(modification["condition"], "condition"))

        # C-57 (ADR-0015 §1): the printed cost, when the observation carries
        # it. Optional, so every state written before this stays valid; the
        # enumeration abstains on a card that does not have one.
        printed = obj.get("printed_cost")
        if printed is not None:
            if not isinstance(printed, dict) or set(printed) != {"energy", "power"} or not isinstance(printed.get("energy"), int)                     or isinstance(printed.get("energy"), bool) or printed["energy"] < 0 or not isinstance(printed.get("power"), dict)                     or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in printed["power"].values()):
                errors.append(f"objects.{object_id}.printed_cost must be {{energy: non-negative int, power: {{domain: non-negative int}}}}")
        if "shield_value" in obj and (not isinstance(obj["shield_value"], int) or isinstance(obj["shield_value"], bool) or obj["shield_value"] < 1):
            errors.append(f"objects.{object_id}.shield_value must be a positive integer (Core 814.1.b)")
        if "assault_value" in obj and (not isinstance(obj["assault_value"], int) or isinstance(obj["assault_value"], bool) or obj["assault_value"] < 1):
            errors.append(f"objects.{object_id}.assault_value must be a positive integer (Core 807.1.b)")
        # 2026-10-12 package 11 (Symbol of the Solari): "If a combat where you are the attacker ends in a tie, recall ALL
        # units instead." - read by combat.determine_combat_result; one shape only
        if "combat_tie_replacement" in obj and obj["combat_tie_replacement"] != COMBAT_TIE_RECALL_ALL:
            errors.append(f"objects.{object_id}.combat_tie_replacement must be {COMBAT_TIE_RECALL_ALL}")
        # Typed trigger lists: death (self-death, 808), play (419.4.a), move (383.1),
        # end of turn (317.1), attack / defend (383.4.e–f).
        for trigger_field in ("death_triggers", "play_triggers", "move_triggers", "end_of_turn_triggers", "attack_triggers", "defend_triggers", "conquer_triggers", "hold_triggers", "beginning_phase_triggers", "main_phase_triggers",
                              # 2026-10-12 package 11 (Treasure Trove)
                              "leave_board_triggers"):
            triggers = obj.get(trigger_field, [])
            if not isinstance(triggers, list):
                errors.append(f"objects.{object_id}.{trigger_field} must be an array")
                continue
            for trigger_index, trigger in enumerate(triggers):
                required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize"}
                if not isinstance(trigger, dict) or not required.issubset(trigger):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}] has invalid shape")
                elif trigger.get("source_object") != object_id or trigger.get("controller") not in players:
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}] has invalid source/controller")
                elif not isinstance(trigger.get("effect_program_id"), str) or not trigger.get("effect_program_id") or not isinstance(trigger.get("optional_at_finalize"), bool):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}] has invalid program/optional binding")
                elif "effect_program_hash" in trigger and not (isinstance(trigger["effect_program_hash"], str) and trigger["effect_program_hash"].startswith("sha256:")):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].effect_program_hash must be a sha256 content hash")
                elif "condition" in trigger and (not isinstance(trigger["condition"], dict) or trigger["condition"].get("kind") not in TRIGGER_CONDITION_KINDS):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].condition.kind must be one of {sorted(TRIGGER_CONDITION_KINDS)} (Core 383.2.a.1)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "paid_additional_cost" and (trigger_field != "play_triggers" or set(trigger["condition"]) != {"kind"}):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: 'if you paid the additional cost' is read only on a play trigger, as {{kind}} (Core 383.2.a.1, 356.4.f.1)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "another_card_finalized_this_turn" and (trigger_field != "play_triggers" or set(trigger["condition"]) != {"kind"}):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: a Legion condition is read only on a play trigger, as {{kind}} (Core 812.1.c)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "controls_units" \
                        and trigger_field == "conquer_triggers" and (
                        trigger.get("scope") != "controller" or set(trigger["condition"]) != {"kind", "count", "location"}
                        or trigger["condition"].get("location") != "here" or validate_condition(trigger["condition"])):
                    # 2026-10-08 package 10 (Garen - Might of Demacia (Starter)): "When you conquer, if you have N+ units at
                    # that battlefield" - a player-level Conquer's condition, read with the conquered Battlefield as here
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: a Conquer's unit count is read only "
                                  f"on a player-level conquer trigger (scope controller), as {{kind, count, location here}} "
                                  f"(Core 383.2.a.1)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "controls_units" and trigger_field != "conquer_triggers" and (
                        trigger_field != "play_triggers" or set(trigger["condition"]) != {"kind", "count", "tag"}
                        or validate_condition(trigger["condition"])):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: 'if you control a <tag>' is read only on a play trigger, as {{kind, count, tag}} (Core 383.2.a.1)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "controls_facedown_card_at_battlefield" and (trigger_field != "beginning_phase_triggers" or set(trigger["condition"]) != {"kind"}):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: 'if you control a facedown card at a battlefield' is read only on a Beginning Phase trigger, as {{kind}} (Core 383.2.a.1)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "assigned_excess_after_attack" and (
                        trigger_field != "conquer_triggers" or trigger.get("scope", "unit_here") != "unit_here"
                        or set(trigger["condition"]) != {"kind", "at_least"}
                        or not isinstance(trigger["condition"]["at_least"], int) or isinstance(trigger["condition"]["at_least"], bool)
                        or trigger["condition"]["at_least"] < 1):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: 'after an attack, if you assigned N or more "
                                  f"excess damage' is read only on a unit's own conquer trigger, as {{kind, at_least >= 1}}")
                elif "condition" in trigger and trigger["condition"].get("kind") == "played_to_battlefield" and (trigger_field != "play_triggers" or set(trigger["condition"]) != {"kind"}):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: 'to a battlefield' on a play is read only on a play trigger, as {{kind}} (Core 383.1, 419.4.a)")
                elif "condition" in trigger and trigger["condition"].get("kind") == "moved_to_battlefield" and (trigger_field != "move_triggers" or set(trigger["condition"]) != {"kind"}):
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}]: 'to a battlefield' is read only on a move trigger, as {{kind}} (Core 383.1, 428)")
                elif "scope" in trigger and trigger_field in {"conquer_triggers", "hold_triggers"} and trigger["scope"] not in {"unit_here", "controller"}:
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].scope must be unit_here or controller on a Score trigger (Core 383.4.c.2)")
                elif "scope" in trigger and trigger_field in {"beginning_phase_triggers", "main_phase_triggers"} and trigger["scope"] not in {"your_beginning_phase", "your_main_phase"}:
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].scope must be your_beginning_phase or your_main_phase (ADR-0010 §8)")
                elif "scope" in trigger and trigger_field not in {"conquer_triggers", "hold_triggers", "beginning_phase_triggers", "main_phase_triggers"}:
                    errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].scope is not a field of this trigger kind")
                elif "functions_from" in trigger:
                    # 2026-09-27 (package 6, Core 385.2): a player-level Conquer Effect of a card
                    # outside the board ("When you conquer, ... this from your trash ...") - the
                    # only typed field read from a zone that is not the board (battlefield_control
                    # ._score_triggers); watched triggers carry it in event_triggers (watchers.py)
                    import watchers as _watchers
                    if trigger_field != "conquer_triggers" or trigger.get("scope") != "controller":
                        errors.append(f"objects.{object_id}.{trigger_field}[{trigger_index}].functions_from is read only on a "
                                      f"conquer trigger of scope controller (Core 383.4.c.2.b, 385.2)")
                    else:
                        errors.extend(_watchers.functions_from_errors(trigger, obj, f"objects.{object_id}.{trigger_field}[{trigger_index}]"))
        entry_ids: set[str] = set()
        for r_index, replacement in enumerate(obj.get("entry_replacements", []) or []):
            if not isinstance(replacement, dict) or replacement.get("mode") != "entry_state" or replacement.get("value") not in {"ready", "exhausted"} or set(replacement) - {"replacement_id", "mode", "value", "source", "chain_item", "card", "condition"}:
                errors.append(f"objects.{object_id}.entry_replacements[{r_index}] must be {{replacement_id?, mode: entry_state, value: ready|exhausted, source?, chain_item?, card?, condition?}}")
            elif "condition" in replacement and (validate_condition(replacement["condition"])
                                                 or replacement["condition"].get("kind") not in ENTRY_CONDITION_KINDS):
                # 2026-09-27: a printed conditional entry (Core 364.3.a), read as the unit
                # enters (369.3)
                errors.append(f"objects.{object_id}.entry_replacements[{r_index}].condition must be a condition.v1 of "
                              f"{sorted(ENTRY_CONDITION_KINDS)}")
            elif replacement.get("card") is not None and replacement["card"] != object_id:
                # Core 805.2.b: the delayed replacement a paid Accelerate makes
                # belongs to the card that paid it. One bound to another card
                # is a mis-binding, not a rule.
                errors.append(f"objects.{object_id}.entry_replacements[{r_index}].card names {replacement['card']!r}, not this object")
            elif "replacement_id" in replacement and (not isinstance(replacement["replacement_id"], str) or not replacement["replacement_id"] or replacement["replacement_id"] in entry_ids):
                errors.append(f"objects.{object_id}.entry_replacements[{r_index}].replacement_id is invalid or duplicated")
            elif "replacement_id" in replacement:
                entry_ids.add(replacement["replacement_id"])
        # 2026-09-27 package 6: "Other friendly units enter ready." - a replacement this permanent
        # applies, while it is on the board (365.1), to the entry of the other Units its side plays
        # (369.3); read by granted_entry_states. One closed shape: the only one printed.
        granted_ids: set[str] = set()
        for g_index, grant in enumerate(obj.get("granted_entry_states", []) or []):
            if (not isinstance(grant, dict) or set(grant) != {"replacement_id", "value", "criteria"}
                    or not isinstance(grant["replacement_id"], str) or not grant["replacement_id"]
                    or grant["replacement_id"] in granted_ids or grant["value"] != "ready"
                    or grant["criteria"] != GRANTED_ENTRY_CRITERIA):
                errors.append(f"objects.{object_id}.granted_entry_states[{g_index}] must be {{replacement_id, value: ready, "
                              f"criteria: {GRANTED_ENTRY_CRITERIA}}} (Core 369.3)")
            else:
                granted_ids.add(grant["replacement_id"])
        for d_index, dynamic in enumerate(obj.get("dynamic_might", []) or []):
            label = f"objects.{object_id}.dynamic_might[{d_index}]"
            if (not isinstance(dynamic, dict) or set(dynamic) != {"modifier_id", "amount", "per"} or not isinstance(dynamic["modifier_id"], str)
                    or not isinstance(dynamic["amount"], int) or isinstance(dynamic["amount"], bool) or dynamic["amount"] < 1
                    or not isinstance(dynamic["per"], dict) or set(dynamic["per"]) != {"kind"} or dynamic["per"]["kind"] not in MIGHT_PER_KINDS):
                errors.append(f"{label} must be {{modifier_id, amount >= 1, per: {{kind in {sorted(MIGHT_PER_KINDS)}}}}}")
        for a_index, aura in enumerate(obj.get("static_auras", []) or []):
            label = f"objects.{object_id}.static_auras[{a_index}]"
            criteria = aura.get("criteria") if isinstance(aura, dict) else None
            if isinstance(aura, dict) and "keyword" in aura:
                # 2026-09-27: "Other friendly units here have [Assault]." - a keyword, granted in
                # the Ability layer (477.2.b), instead of a Might amount
                # (2026-10-08 package 10, Spirit's Refuge: only_if_absent - "... if they didn't already")
                if (set(aura) - {"aura_id", "keyword", "value", "criteria", "only_if_absent"} or not isinstance(aura.get("aura_id"), str)
                        or aura.get("only_if_absent") not in (None, True) or ("only_if_absent" in aura and "value" in aura)
                        or _static_keyword_problem(aura)
                        or not isinstance(criteria, dict) or set(criteria) - STATIC_AURA_CRITERIA
                        or criteria.get("kind", "unit") != "unit"
                        or criteria.get("controller_relation", "friendly") not in {"friendly", "enemy"}
                        or any(criteria.get(k) not in (None, True) for k in STATIC_AURA_FLAGS)):
                    errors.append(f"{label} must be {{aura_id, keyword in {sorted(STATIC_AURA_KEYWORDS)}, value? (summed "
                                  f"keywords only), criteria over {sorted(STATIC_AURA_CRITERIA)} (units)}}")
                continue
            # 2026-09-27 package 6: "Stunned enemy units here have -8 [M], to a minimum of 1 [M]." - a
            # decrease may carry the floor it is limited to; a passive's limit is applied fresh each
            # time the Might is computed, never snapshotted (Core 477.3.b, its second example)
            floor = aura.get("minimum") if isinstance(aura, dict) else None
            if (not isinstance(aura, dict) or set(aura) - {"minimum"} != {"aura_id", "amount", "criteria"}
                    or not isinstance(aura["aura_id"], str)
                    or not isinstance(aura["amount"], int) or isinstance(aura["amount"], bool) or aura["amount"] == 0
                    or ("minimum" in aura and (not isinstance(floor, int) or isinstance(floor, bool) or floor < 0
                                               or aura["amount"] >= 0))
                    or not isinstance(criteria, dict) or set(criteria) - STATIC_AURA_CRITERIA
                    or criteria.get("kind", "unit") not in {"unit", "gear"}
                    or criteria.get("controller_relation", "friendly") not in {"friendly", "enemy"}
                    or any(criteria.get(k) not in (None, True) for k in STATIC_AURA_FLAGS)):
                errors.append(f"{label} must be {{aura_id, amount != 0, minimum >= 0 (a decrease only)?, criteria over "
                              f"{sorted(STATIC_AURA_CRITERIA)}}}")
        # 2026-10-15 package 13 (C2): a card's own printed Bonus Damage, Might aura and Replacement Effects, read live
        # (printed_aura_effects) or materialized while it is where it works (materialize_printed_replacements)
        for p_index, modifier in enumerate(obj.get("printed_damage_modifiers", []) or []):
            if not isinstance(modifier, dict) or set(modifier) != {"amount", "scope"} or not isinstance(modifier["amount"], int) \
                    or isinstance(modifier["amount"], bool) or modifier["amount"] < 1 or modifier["scope"] != {"kind": "controller_sources"}:
                errors.append(f"objects.{object_id}.printed_damage_modifiers[{p_index}] must be {{amount >= 1, scope: "
                              f"controller_sources}} (Core 714.1)")
        for p_index, aura in enumerate(obj.get("printed_might_auras", []) or []):
            if not isinstance(aura, dict) or set(aura) != {"amount", "condition"} or not isinstance(aura["amount"], int) \
                    or isinstance(aura["amount"], bool) or aura["amount"] == 0 or not isinstance(aura["condition"], dict) \
                    or aura["condition"].get("kind") not in AURA_CONDITION_KINDS or set(aura["condition"]) != {"kind"}:
                errors.append(f"objects.{object_id}.printed_might_auras[{p_index}] must be {{amount != 0, condition: one of "
                              f"{sorted(AURA_CONDITION_KINDS)}}}")
        templates = obj.get("printed_replacements")
        if templates is not None and (not isinstance(templates, list) or not templates
                                      or any(not isinstance(t, dict) or set(t) & set(PRINTED_REPLACEMENT_BOUND) for t in templates)):
            errors.append(f"objects.{object_id}.printed_replacements must be templates without "
                          f"{list(PRINTED_REPLACEMENT_BOUND)} (where it is supplies them)")
        seen_conditional: set[str] = set()
        for c_index, conditional in enumerate(obj.get("conditional_might", []) or []):
            label = f"objects.{object_id}.conditional_might[{c_index}]"
            if not isinstance(conditional, dict) or set(conditional) != {"modifier_id", "amount", "condition"} or not isinstance(conditional["amount"], int):
                errors.append(f"{label} must carry modifier_id, amount, condition")
                continue
            if not isinstance(conditional["modifier_id"], str) or not conditional["modifier_id"] or conditional["modifier_id"] in seen_conditional:
                errors.append(f"{label}.modifier_id is invalid or duplicated")
            seen_conditional.add(conditional.get("modifier_id", ""))
            condition = conditional["condition"]
            if not isinstance(condition, dict) or condition.get("kind") not in CONDITION_KINDS:
                errors.append(f"{label}.condition.kind must be one of {sorted(CONDITION_KINDS)}")
            elif condition["kind"] == "runes_at_least" and (set(condition) != {"kind", "count"} or not isinstance(condition["count"], int) or condition["count"] < 0):
                errors.append(f"{label}.condition.runes_at_least needs a non-negative count")
            elif condition["kind"] == "attacking_or_defending_alone" and set(condition) != {"kind"}:
                errors.append(f"{label}.condition.attacking_or_defending_alone carries no other fields")
            elif condition["kind"] == "is_buffed" and set(condition) != {"kind"}:
                errors.append(f"{label}.condition.is_buffed reads the card's own Buff counter and carries no other fields")
        # 2026-09-27: a printed keyword the card has only while its condition holds (Core 364.3.a)
        seen_conditional_keywords: set[str] = set()
        for k_index, conditional in enumerate(obj.get("conditional_keywords", []) or []):
            label = f"objects.{object_id}.conditional_keywords[{k_index}]"
            if not isinstance(conditional, dict) or {"modifier_id", "keyword", "condition"} - set(conditional) \
                    or set(conditional) - {"modifier_id", "keyword", "value", "condition"}:
                errors.append(f"{label} must carry modifier_id, keyword, condition (and value for a summed keyword)")
                continue
            if not isinstance(conditional["modifier_id"], str) or not conditional["modifier_id"] or conditional["modifier_id"] in seen_conditional_keywords:
                errors.append(f"{label}.modifier_id is invalid or duplicated")
            seen_conditional_keywords.add(conditional.get("modifier_id", ""))
            if _static_keyword_problem(conditional):
                errors.append(f"{label}.keyword must be one of {sorted(STATIC_AURA_KEYWORDS)}, with a positive value only on {sorted(SUMMED_VALUE_KEYWORDS)}")
            condition = conditional["condition"]
            problems = validate_condition(condition, f"{label}.condition")
            if problems:
                errors.extend(problems)
            elif condition["kind"] not in CONDITIONAL_KEYWORD_CONDITIONS or "object" in condition \
                    or (condition["kind"] == "cards_discarded_this_turn_at_least" and "player" in condition):
                # the card's own facts, and its own controller's discards - nothing else is read
                errors.append(f"{label}.condition must be one of {sorted(CONDITIONAL_KEYWORD_CONDITIONS)} about the card itself "
                              f"(no object; no player)")
        # ADR-0008 §5: granted characteristics, each bound to the object identity
        # it was granted to and to the Combat or turn it lasts for.
        seen_keyword_modifiers: set[str] = set()
        for k_index, modifier in enumerate(obj.get("keyword_modifiers", []) or []):
            label = f"objects.{object_id}.keyword_modifiers[{k_index}]"
            if not isinstance(modifier, dict) or {"modifier_id", "keyword", "source", "duration", "target_identity"} - set(modifier) or set(modifier) - {"modifier_id", "keyword", "value", "source", "duration", "combat_id", "turn_id", "target_identity"}:
                errors.append(f"{label} must carry modifier_id, keyword, source, duration, target_identity (and value, combat_id or turn_id)")
                continue
            if not isinstance(modifier["modifier_id"], str) or not modifier["modifier_id"] or modifier["modifier_id"] in seen_keyword_modifiers:
                errors.append(f"{label}.modifier_id is invalid or duplicated")
            seen_keyword_modifiers.add(modifier.get("modifier_id", ""))
            if modifier["keyword"] not in GRANTABLE_KEYWORDS:
                errors.append(f"{label}.keyword must be one of {sorted(GRANTABLE_KEYWORDS)}")
            if "value" in modifier and (not isinstance(modifier["value"], int) or isinstance(modifier["value"], bool) or modifier["value"] < 1):
                errors.append(f"{label}.value must be a positive integer (Core 814.1.b)")
            if not isinstance(modifier["source"], str) or not modifier["source"]:
                errors.append(f"{label}.source must be a non-empty string")
            if modifier["duration"] not in KEYWORD_MODIFIER_DURATIONS:
                errors.append(f"{label}.duration must be one of {sorted(KEYWORD_MODIFIER_DURATIONS)}")
            elif modifier["duration"] == "this_combat" and (not isinstance(modifier.get("combat_id"), str) or not modifier.get("combat_id") or "turn_id" in modifier):
                errors.append(f"{label}: a this_combat grant carries its combat_id (466.7.c)")
            elif modifier["duration"] == "this_turn" and (not isinstance(modifier.get("turn_id"), str) or not modifier.get("turn_id") or "combat_id" in modifier):
                errors.append(f"{label}: a this_turn grant carries its turn_id (317.2.c)")
            if not isinstance(modifier["target_identity"], str) or "@" not in modifier["target_identity"]:
                errors.append(f"{label}.target_identity must be an identity token")
        deflect_value = obj.get("deflect_value")
        if deflect_value is not None and (not isinstance(deflect_value, int) or deflect_value < 1):
            errors.append(f"objects.{object_id}.deflect_value must be a positive integer (Core 809.1.b)")
        permissions = obj.get("play_permissions", [])
        if not isinstance(permissions, list) or len(permissions) != len(set(permissions)) or any(p not in PLAY_PERMISSIONS for p in permissions):
            errors.append(f"objects.{object_id}.play_permissions must be a unique array drawn from {sorted(PLAY_PERMISSIONS)}")
        granted = obj.get("granted_play_permissions")
        if granted is not None and (not isinstance(granted, list) or not granted
                                    or any(g not in GRANTED_PLAY_PERMISSION_SHAPES for g in granted)):
            errors.append(f"objects.{object_id}.granted_play_permissions must be a non-empty array of "
                          f"{GRANTED_PLAY_PERMISSION_SHAPES}")
        # ADR-0012 §4 / Core 434: an attached card names its Top-Most card. The
        # engine derives the other direction, so the two can never disagree.
        host_id = obj.get("attached_to")
        if host_id is not None:
            if host_id == object_id or host_id not in objects:
                errors.append(f"objects.{object_id}.attached_to must name another object in this state")
            elif objects[host_id].get("attached_to") is not None:
                errors.append(f"objects.{object_id}.attached_to names {host_id!r}, which is itself attached; nested attachments are outside this slice")
            elif zone_class(find_location(state, object_id)) != "board":
                # 2026-09-25 (GPT): an attached card that left the board kept its link and
                # kept buffing its host; attaching links two cards ON the board (434.1.a)
                errors.append(f"objects.{object_id} is attached to {host_id!r} but is not on the board (Core 434.1.a, 435.1.b)")
        if "might_bonus" in obj and (not isinstance(obj["might_bonus"], int) or isinstance(obj["might_bonus"], bool) or obj["might_bonus"] < 0):
            errors.append(f"objects.{object_id}.might_bonus must be a non-negative integer (Core 159.1)")
        recall = obj.get("pending_recall")
        if recall is not None and (not isinstance(recall, dict) or set(recall) - {"reason", "battlefield"} or recall.get("reason") != "detached_gear_at_battlefield" or recall.get("battlefield") not in battlefields):
            errors.append(f"objects.{object_id}.pending_recall must be {{reason: detached_gear_at_battlefield, battlefield}} (Core 435.4.a)")
        if not isinstance(obj.get("is_token", False), bool):
            errors.append(f"objects.{object_id}.is_token must be boolean when supplied")
        # 2026-09-27 (package 6): the tags the object has (Core 133.8), when they were observed -
        # what "a non-Recruit unit" reads (watchers.WATCH_FILTERS object_not_tagged)
        tags = obj.get("tags")
        if tags is not None and (not isinstance(tags, list) or len(tags) != len(set(tags))
                                 or any(not isinstance(t, str) or not t for t in tags)):
            errors.append(f"objects.{object_id}.tags must be a unique array of non-empty tag names (Core 133.8)")
        # ADR-0012 §1 / Core 825.3: Unique is a deck-construction constraint,
        # not a play restriction; the engine only records the characteristic.
        effect_text = obj.get("effect_text")
        if effect_text is not None and (not isinstance(effect_text, dict) or not effect_text
                                        or any(field not in APPENDABLE_TRIGGER_FIELDS or not isinstance(rows, list) or not rows for field, rows in effect_text.items())):
            errors.append(f"objects.{object_id}.effect_text must map appendable ability lists to non-empty descriptor arrays (Core 477.2)")
        seen = obj.get("banish_when_seen")
        if seen is not None and (not isinstance(seen, dict) or set(seen) != {"play_for_power_any"}
                                 or not isinstance(seen["play_for_power_any"], int) or isinstance(seen["play_for_power_any"], bool)
                                 or seen["play_for_power_any"] < 1):
            errors.append(f"objects.{object_id}.banish_when_seen must be {{play_for_power_any: positive integer}}")
        for flag in ("empowered", "buffed", "any_number_of_buffs"):
            if flag in obj and not isinstance(obj[flag], bool):
                errors.append(f"objects.{object_id}.{flag} must be boolean when supplied (Core 441.1.a, 426.1.b)")
        # 2026-10-06 package 9 (Lee Sin - Ascetic): more than one buff, only with the permission (Core 426.1.b.2)
        if "buff_count" in obj and (not isinstance(obj["buff_count"], int) or isinstance(obj["buff_count"], bool)
                                    or obj["buff_count"] < 2 or obj.get("buffed") is not True
                                    or obj.get("any_number_of_buffs") is not True):
            errors.append(f"objects.{object_id}.buff_count must be an integer of at least 2, on a buffed object that may "
                          f"have any number of buffs (Core 426.1.b.2)")
        limit = obj.get(EMPOWER_LIMIT_FIELD, DEFAULT_EMPOWER_LIMIT)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            errors.append(f"objects.{object_id}.{EMPOWER_LIMIT_FIELD} must be an integer of at least 1 "
                          f"when supplied (Core 441.1.c.1)")
            limit = DEFAULT_EMPOWER_LIMIT
        count = obj.get(EMPOWER_COUNT_FIELD)
        if count is not None:
            if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > limit:
                errors.append(f"objects.{object_id}.{EMPOWER_COUNT_FIELD} must be an integer from 0 to "
                              f"{EMPOWER_LIMIT_FIELD} (Core 441.1.c.1)")
            elif bool(count) != bool(obj.get("empowered")):
                errors.append(f"objects.{object_id}.{EMPOWER_COUNT_FIELD} disagrees with .empowered; "
                              f"a Game Object is Empowered exactly while its count is above zero (Core 441.1.a)")
        if obj.get("buffed") and obj.get("kind") != "unit":
            errors.append(f"objects.{object_id}.buffed applies to Units only (Core 702)")
        if not isinstance(obj.get("hidden", False), bool):
            errors.append(f"objects.{object_id}.hidden must be boolean when supplied (Core 811)")
        if not isinstance(obj.get("unique", False), bool):
            errors.append(f"objects.{object_id}.unique must be boolean when supplied (Core 825.3: a deck constraint, not a play restriction)")
        identity = obj.get("identity")
        if identity is not None and (not isinstance(identity, str) or "@" not in identity or not identity.rsplit("@", 1)[1].isdigit()):
            errors.append(f"objects.{object_id}.identity must look like '<id>@<generation>' when supplied")
        keywords = obj.get("keywords", [])
        if not isinstance(keywords, list) or len(keywords) != len(set(keywords)) or any(keyword not in OBJECT_KEYWORDS for keyword in keywords):
            errors.append(f"objects.{object_id}.keywords must be a unique supported-keyword array")
        modifiers = obj.get("might_modifiers")
        if not isinstance(modifiers, list):
            errors.append(f"objects.{object_id}.might_modifiers must be an array")
        elif any(not isinstance(item, dict) or not {"amount", "duration", "source"} <= set(item) or set(item) - {"amount", "duration", "source", "turn_id"}
                 or ("turn_id" in item and (not isinstance(item["turn_id"], str) or not item["turn_id"])) for item in modifiers):
            errors.append(f"objects.{object_id}.might_modifiers has invalid entries (amount, duration, source, optional turn_id)")
        places = occupancy.get(object_id, [])
        if len(places) != 1:
            errors.append(f"object {object_id!r} must occupy exactly one zone/location, got {places}")
    # ADR-0011 §3: reveal / look marks last while a program runs (424.3.a);
    # each is bound to the object's current identity and its zone.
    reveals = state.get("reveals", [])
    if not isinstance(reveals, list):
        errors.append("reveals must be an array")
        reveals = []
    for index, mark in enumerate(reveals):
        label = f"reveals[{index}]"
        if not isinstance(mark, dict) or set(mark) != {"object_id", "identity", "zone", "visible_to", "session", "kind"}:
            errors.append(f"{label} must carry object_id, identity, zone, visible_to, session, kind")
            continue
        obj = objects.get(mark["object_id"])
        if obj is None:
            errors.append(f"{label} names an unknown object")
            continue
        if mark["identity"] != (obj.get("identity") or f"{mark['object_id']}@0"):
            errors.append(f"{label} is bound to a stale identity")
        # package 11 (Twisted Fate - Gambler): a rune revealed on top of its Rune Deck stays there, marked
        if mark["zone"] not in {"main_deck", "hand", "rune_deck"} or mark["object_id"] not in players.get(obj.get("owner"), {}).get("zones", {}).get(mark["zone"], []):
            errors.append(f"{label} names a zone the object is not in")
        if not (mark["visible_to"] == "all" or (isinstance(mark["visible_to"], list) and mark["visible_to"] and all(p in players for p in mark["visible_to"]))):
            errors.append(f"{label}.visible_to must be 'all' or a non-empty player list")
        if mark["kind"] not in {"look", "reveal"} or not isinstance(mark["session"], str) or not mark["session"]:
            errors.append(f"{label}.kind must be look or reveal with a session")
    replacement_ids: set[str] = set()
    for index, replacement in enumerate(replacements):
        label = f"replacement_effects[{index}]"
        required = {"replacement_id", "controller", "mode", "event_op", "optional", "uses_remaining"}
        if not isinstance(replacement, dict) or not required.issubset(replacement):
            errors.append(f"{label} has invalid shape")
            continue
        replacement_id = replacement.get("replacement_id")
        if not isinstance(replacement_id, str) or not replacement_id or replacement_id in replacement_ids:
            errors.append(f"{label}.replacement_id is invalid or duplicated")
        else:
            replacement_ids.add(replacement_id)
        # ADR-0007 §12: a replacement is either source-backed (a permanent's own
        # ability, active while it is on the board) or granted by an effect to
        # one object's identity for this turn — exactly one of the two.
        source_backed, granted = "source_object" in replacement, "granted" in replacement
        created = "created" in replacement     # package 9: an effect's replacement for this turn, any object
        if source_backed + granted + created != 1:
            errors.append(f"{label} must be exactly one of source-backed (source_object), granted (granted) or "
                          f"created (created)")
            continue
        if created:
            made = replacement["created"]
            if not isinstance(made, dict) or set(made) != {"duration", "turn_id", "created_by"} or made.get("duration") != "this_turn" \
                    or not isinstance(made.get("turn_id"), str) or not made.get("turn_id") or not isinstance(made.get("created_by"), str):
                errors.append(f"{label}.created must carry duration this_turn, turn_id, created_by")
            if replacement.get("mode") != "prevent_event" or replacement.get("event_op") != "deal_damage" \
                    or replacement.get("damage_sources") != ["spell", "ability"]:
                errors.append(f"{label}: a created replacement is the typed spell-and-ability damage prevention only")
        if "damage_sources" in replacement and (replacement.get("event_op") != "deal_damage" or not isinstance(
                replacement["damage_sources"], list) or not replacement["damage_sources"]
                or set(replacement["damage_sources"]) - {"spell", "ability"}):
            errors.append(f"{label}.damage_sources is a non-empty subset of [spell, ability] on a deal_damage replacement")
        if replacement.get("controller") not in players:
            errors.append(f"{label} has unknown controller")
        if created:
            pass
        elif source_backed:
            if replacement.get("source_object") not in objects:
                errors.append(f"{label} has unknown source")
            elif objects[replacement["source_object"]].get("controller") != replacement.get("controller"):
                errors.append(f"{label}.controller must control its source object")
        else:
            grant = replacement["granted"]
            if not isinstance(grant, dict) or set(grant) != {"target_object", "target_identity", "duration", "turn_id", "granted_by"}:
                errors.append(f"{label}.granted must carry target_object, target_identity, duration, turn_id, granted_by")
            else:
                if grant["target_object"] not in objects:
                    errors.append(f"{label}.granted.target_object is unknown")
                if not isinstance(grant["target_identity"], str) or "@" not in grant["target_identity"]:
                    errors.append(f"{label}.granted.target_identity must be an identity token")
                if grant["duration"] != "this_turn":
                    errors.append(f"{label}.granted.duration must be this_turn")
                if not isinstance(grant["turn_id"], str) or not grant["turn_id"] or not isinstance(grant["granted_by"], str) or not grant["granted_by"]:
                    errors.append(f"{label}.granted needs turn_id and granted_by")
                if replacement.get("uses_remaining") != 1:
                    errors.append(f"{label} granted replacements apply once (uses_remaining 1)")
                if replacement.get("target_object_id") != grant["target_object"]:
                    errors.append(f"{label}.target_object_id must equal granted.target_object")
        if replacement.get("mode") not in {"prevent_event", "replace_with", "augment_with", "reduce_damage"}:
            errors.append(f"{label}.mode is unsupported")
        if replacement.get("event_op") not in SUPPORTED_OPS:
            errors.append(f"{label}.event_op is unsupported")
        if not isinstance(replacement.get("optional"), bool):
            errors.append(f"{label}.optional must be boolean")
        requires_chosen = replacement.get(REQUIRES_CHOSEN_FIELD)
        if requires_chosen is not None and not isinstance(requires_chosen, bool):
            errors.append(f"{label}.{REQUIRES_CHOSEN_FIELD} must be boolean when supplied (Core 355.6)")
        dependent = replacement.get(DEPENDENT_ON_EMPOWERED_FIELD)
        if dependent is not None and not isinstance(dependent, bool):
            errors.append(f"{label}.{DEPENDENT_ON_EMPOWERED_FIELD} must be boolean when supplied (Core 828.1.c)")
        direction = replacement.get(MIGHT_DIRECTION_FIELD)
        if direction is not None:
            if direction not in MIGHT_DIRECTIONS:
                errors.append(f"{label}.{MIGHT_DIRECTION_FIELD} must be decrease or increase (Core 477)")
            if replacement.get("event_op") != "modify_might":
                errors.append(f"{label}.{MIGHT_DIRECTION_FIELD} only means something on a modify_might replacement (Core 477)")
        uses = replacement.get("uses_remaining")
        if uses is not None and (not isinstance(uses, int) or uses < 0):
            errors.append(f"{label}.uses_remaining must be null or non-negative integer")
        # Core 372: "once each turn" / "N times each turn". The ledger is
        # separate from uses_remaining, which is the whole-game allowance.
        per_turn = replacement.get("uses_per_turn")
        if per_turn is not None and (not isinstance(per_turn, int) or isinstance(per_turn, bool) or per_turn < 1):
            errors.append(f"{label}.uses_per_turn must be a positive integer (Core 372)")
        spent = replacement.get("applied_this_turn")
        if spent is not None and (not isinstance(spent, dict) or any(
                not isinstance(k, str) or not isinstance(v, int) or isinstance(v, bool) or v < 0 for k, v in spent.items())):
            errors.append(f"{label}.applied_this_turn must map a turn id to a non-negative count")
        if "condition" in replacement:
            errors.extend(f"{label}.condition {e}" for e in validate_condition(replacement["condition"], "condition"))
        relation = replacement.get("target_controller_relation")
        if relation not in {None, "friendly", "enemy"}:
            errors.append(f"{label}.target_controller_relation is invalid")
        if "cost" in replacement:
            errors.extend(f"{label}.{e}" for e in replacement_cost_errors(replacement, source_backed))
        replacement_effects = replacement.get("replacement_effects")
        if replacement.get("mode") in {"replace_with", "augment_with"} and (not isinstance(replacement_effects, list) or not replacement_effects):
            errors.append(f"{label}.replacement_effects must be non-empty for {replacement.get('mode')}")
        if replacement.get("mode") == "reduce_damage":
            if replacement.get("event_op") != "deal_damage":
                errors.append(f"{label}.reduce_damage may only replace deal_damage")
            if not isinstance(replacement.get("prevent_remaining"), int) or replacement.get("prevent_remaining", 0) <= 0:
                errors.append(f"{label}.prevent_remaining must be a positive integer")
        if "source_object" in replacement:
            source_places = occupancy.get(replacement.get("source_object"), [])
            legend = (objects.get(replacement.get("source_object")) or {}).get("kind") == "legend"
            if source_places and not any(place.startswith("battlefield:") or place.endswith(":base")
                                         or (legend and place.endswith(":legend_zone")) for place in source_places):
                errors.append(f"{label}.source_object must be active on the board (a Legend: in its Legend Zone)")
    # ADR-0014 §2: watchers, delayed triggers, per-turn counters, multipliers.
    import watchers
    errors.extend(watchers.validate_watch_state(state))
    return errors


# 2026-09-27 package 6: a card's own printed NON-RESOURCE additional costs (Core 356.2.a.1,
# 356.2.b.1, 356.7) - "As an additional cost to play me, kill a friendly unit", "As you play me,
# you may discard 1 as an additional cost" - and the cost modifications a paid offer switches on
# ("If you do, reduce my cost by [2]", "If you do, ignore this spell's cost", "Reduce my cost by
# [C] for each killed this way"). The payment is a typed kind; what it is paid WITH (which unit,
# which card) is the payer's choice as the card is played (Core 355.1.a, 357.2.a's own example).
PRINTED_COST_KINDS = {"kill", "exhaust", "spend_buff", "discard"}
# the kinds whose object is a Unit on the board (kill / exhaust: a friendly unit; spend_buff: a unit
# its payer controls with a buff, Core 702.2.b.1-b.2); discard names cards in the payer's hand
PRINTED_COST_UNIT_KINDS = {"kill", "exhaust", "spend_buff"}
OFFER_LINK_KINDS = {"energy_reduction", "ignore_base_cost", "power_reduction_per_paid"}


def _printed_cost_errors(object_id: str, obj: dict[str, Any], resource_offer_ids: list[Any]) -> list[str]:
    errors: list[str] = []
    printed = obj.get("printed_additional_costs")
    if printed is not None and not isinstance(printed, list):
        return [f"objects.{object_id}.printed_additional_costs must be a list"]
    offers: dict[str, dict[str, Any]] = {}
    for index, offer in enumerate(printed or []):
        label = f"objects.{object_id}.printed_additional_costs[{index}]"
        if not isinstance(offer, dict) or set(offer) != {"cost_offer_id", "mandatory", "payment"}:
            errors.append(f"{label} must be {{cost_offer_id, mandatory, payment}}")
            continue
        offer_id, payment = offer["cost_offer_id"], offer["payment"]
        if not isinstance(offer_id, str) or not offer_id or offer_id in offers or offer_id in resource_offer_ids:
            errors.append(f"{label}.cost_offer_id must be a non-empty string no other offer of this card uses")
            continue
        if not isinstance(offer["mandatory"], bool):
            errors.append(f"{label}.mandatory must be boolean")
            continue
        if not isinstance(payment, dict) or payment.get("kind") not in PRINTED_COST_KINDS:
            errors.append(f"{label}.payment.kind must be one of {sorted(PRINTED_COST_KINDS)}")
            continue
        if payment.get("any_number") is True:
            # "any number" (Core 355.13) is a count the payer chooses; only an optional offer of a
            # Unit kind prints it, and a mandatory cost of "any number" would be no cost at all
            if set(payment) != {"kind", "any_number"} or payment["kind"] not in PRINTED_COST_UNIT_KINDS or offer["mandatory"]:
                errors.append(f"{label}.payment {{kind, any_number: true}} is an optional offer of a unit kind")
                continue
        elif set(payment) != {"kind", "amount"} or not isinstance(payment["amount"], int) or isinstance(payment["amount"], bool) \
                or payment["amount"] < 1 or (payment["kind"] in PRINTED_COST_UNIT_KINDS and payment["amount"] != 1):
            errors.append(f"{label}.payment must be {{kind, amount}} (discard N >= 1; one unit for a unit kind) "
                          "or {kind, any_number: true}")
            continue
        offers[offer_id] = offer
    links = obj.get("offer_linked_cost_modifications")
    if links is not None and not isinstance(links, list):
        return errors + [f"objects.{object_id}.offer_linked_cost_modifications must be a list"]
    for index, link in enumerate(links or []):
        label = f"objects.{object_id}.offer_linked_cost_modifications[{index}]"
        if not isinstance(link, dict) or link.get("kind") not in OFFER_LINK_KINDS:
            errors.append(f"{label}.kind must be one of {sorted(OFFER_LINK_KINDS)}")
            continue
        offer = offers.get(link.get("cost_offer_id"))
        if offer is None or offer["mandatory"]:
            # "If you do" reads the decision to pay an OPTIONAL cost (356.4.f.1); a mandatory one is always paid
            errors.append(f"{label}.cost_offer_id must name an optional printed offer of this card")
            continue
        any_number = offer["payment"].get("any_number") is True
        wanted = {"energy_reduction": {"cost_offer_id", "kind", "amount"}, "ignore_base_cost": {"cost_offer_id", "kind"},
                  "power_reduction_per_paid": {"cost_offer_id", "kind", "domain", "amount"}}[link["kind"]]
        if set(link) != wanted:
            errors.append(f"{label} must be exactly {sorted(wanted)}")
        elif "amount" in link and (not isinstance(link["amount"], int) or isinstance(link["amount"], bool) or link["amount"] < 1):
            errors.append(f"{label}.amount must be a positive integer")
        elif link["kind"] == "power_reduction_per_paid" and (not any_number or not isinstance(link["domain"], str) or not link["domain"]):
            errors.append(f"{label} counts what an 'any number' offer paid, per Domain")
        elif link["kind"] != "power_reduction_per_paid" and any_number:
            errors.append(f"{label} applies once, so it links an offer of one payment")
    return errors


def _granted_discount_errors(object_id: str, obj: dict[str, Any]) -> list[str]:
    """2026-09-27 package 6: a permanent's printed discount on its controller's cards of one tag ("Your
    Dragons' Energy costs are reduced by [2], to a minimum of [1]" - Core 356.4.a, 356.4.b, 356.4.e).
    Read only while its source is on the board (a passive works there, Core 363); the tag is as
    printed (object_tags)."""
    granted = obj.get("granted_cost_discounts")
    if granted is None:
        return []
    if not isinstance(granted, list):
        return [f"objects.{object_id}.granted_cost_discounts must be a list"]
    errors, ids = [], set()
    for index, entry in enumerate(granted):
        label = f"objects.{object_id}.granted_cost_discounts[{index}]"
        if not isinstance(entry, dict) or set(entry) - {"discount_id", "applies_to", "amount", "minimum", "card_tag", "card_kind", "source_at"} \
                or not {"discount_id", "applies_to", "amount"} <= set(entry) or len({"card_tag", "card_kind"} & set(entry)) != 1:
            errors.append(f"{label} must be {{discount_id, applies_to, amount, card_tag | card_kind, minimum?, source_at?}}")
            continue
        if "card_kind" in entry and entry["card_kind"] not in {"spell", "unit", "gear"}:
            errors.append(f"{label}.card_kind must be spell, unit or gear")
        if "source_at" in entry and entry["source_at"] != "battlefield":
            errors.append(f"{label}.source_at may only be battlefield (the source's own location, 'while I'm at a battlefield')")
        if not isinstance(entry["discount_id"], str) or not entry["discount_id"] or entry["discount_id"] in ids:
            errors.append(f"{label}.discount_id must be a non-empty string no other discount of this object uses")
        ids.add(entry.get("discount_id"))
        if entry["applies_to"] != "energy":
            errors.append(f"{label}.applies_to must be energy; nothing else is modelled")
        for field in ("amount", "minimum"):
            value = entry.get(field)
            if field in entry and (not isinstance(value, int) or isinstance(value, bool) or value < (1 if field == "amount" else 0)):
                errors.append(f"{label}.{field} must be a {'positive' if field == 'amount' else 'non-negative'} integer")
        if "card_tag" in entry and (not isinstance(entry["card_tag"], str) or not entry["card_tag"]):
            errors.append(f"{label}.card_tag names the tag, as printed")
    return errors


def _offer_binding_errors(program: dict[str, Any]) -> list[str]:
    """Round H: a `cost_paid` naming a card-self offer must be reading *this*
    card's receipt for *this* play. Codex's three-way binding - source_object,
    chain_item, cost_offer_id - is checked here, statically, so a program that
    borrows another card's payment never reaches execution."""
    receipt = program.get("cost_receipt")
    named = [e["predicate"] for e in (program.get("effects") or [])
             if isinstance(e, dict) and isinstance(e.get("predicate"), dict)
             and e["predicate"].get("cost_offer_id") is not None]
    if not named:
        return []
    if not isinstance(receipt, dict):
        return ["a cost_offer_id predicate needs this program to carry the receipt it reads"]
    errors: list[str] = []
    source = program.get("source_object")
    if source is not None and receipt.get("card") != source:
        errors.append(f"the receipt is for card {receipt.get('card')!r} but this program's source is {source!r}; "
                      "one card's additional cost does not satisfy another's")
    chain_item = program.get("chain_item")
    if chain_item is not None and receipt.get("chain_item") is None:
        errors.append("this program names a chain item but the receipt it reads names none; "
                      "an additional cost is bound to the play that paid it")
    elif chain_item is not None and receipt.get("chain_item") != chain_item:
        errors.append(f"the receipt is for chain item {receipt.get('chain_item')!r} but this program belongs to "
                      f"{chain_item!r}; an additional cost is bound to the play that paid it")
    for predicate in named:
        component = next((c for c in receipt.get("components", []) if c.get("cost_id") == predicate["cost_id"]), None)
        if component is None:
            errors.append(f"predicate names cost_id {predicate['cost_id']!r}, which this receipt has no component for")
        elif component.get("cost_offer_id") != predicate["cost_offer_id"]:
            errors.append(f"predicate names offer {predicate['cost_offer_id']!r}; the receipt's component for "
                          f"{predicate['cost_id']!r} records {component.get('cost_offer_id')!r}")
    return errors


def _trigger_base_cost_errors(effect: dict[str, Any], index: int, count: int) -> list[str]:
    """The shape of a triggered ability's base cost (Core 204.3.a, 383.3.b): the program's first
    instruction, followed by the effect it pays for, carrying only the typed payments
    TRIGGER_COST_PAYMENTS names."""
    errors: list[str] = []
    if index != 0:
        errors.append("must be the program's first instruction: a triggered ability's base cost opens its "
                      "effect (Core 383.3.b); a cost in a later part is paid on resolution (Core 740.4.a.2.a), "
                      "which this instruction does not model")
    if count < 2:
        errors.append("needs the effect it pays for after it ([do X] to [do Y], Core 740.4.a)")
    extra = set(effect) - {"op", "effect_id", "payment"}
    if extra:
        errors.append(f"carries its payment only, not {sorted(extra)}")
    payment = effect.get("payment")
    if not isinstance(payment, list) or not payment:
        return errors + ["payment must be a non-empty array"]
    seen: set[tuple[str, str | None]] = set()
    for position, part in enumerate(payment):
        kind = part.get("kind") if isinstance(part, dict) else None
        if kind not in TRIGGER_COST_PAYMENTS:
            errors.append(f"payment[{position}].kind must be one of {sorted(TRIGGER_COST_PAYMENTS)}")
            continue
        if set(part) - {"kind"} != TRIGGER_COST_PAYMENTS[kind]:
            errors.append(f"payment[{position}] ({kind}) must carry exactly {sorted(TRIGGER_COST_PAYMENTS[kind])}")
            continue
        if kind in {"energy", "power", "power_own_domain", "discard"} and (not isinstance(part["amount"], int) or isinstance(part["amount"], bool)
                                                                or part["amount"] < 1):
            errors.append(f"payment[{position}] ({kind}) needs a positive amount")
        if kind == "power" and (not isinstance(part["domain"], str) or not part["domain"]):
            errors.append(f"payment[{position}] (power) needs a domain")
        if kind in {"exhaust", "recycle"} and part["object_id"] != {"object_ref": "program_source"}:
            errors.append(f"payment[{position}] ({kind}) is paid with the ability's own source only "
                          f"({{object_ref: program_source}})")
        key = (kind, part.get("domain") if kind == "power" else None)
        if key in seen:
            errors.append(f"payment[{position}] repeats a {kind} payment; write its amount once")
        seen.add(key)
    return errors


def _limited_play_cost_basis_errors(value: Any) -> list[str]:
    if isinstance(value, dict) and value.get("kind") == "for_power_any":
        if set(value) != {"kind", "amount"} or not isinstance(value.get("amount"), int) or isinstance(value.get("amount"), bool) \
                or value["amount"] < 1:
            return ["cost_basis for_power_any must be {kind, amount} with a positive integer amount (Core 356.1.a)"]
        return []
    if isinstance(value, dict) and value.get("kind") == "discount_energy":
        if set(value) != {"kind", "amount"} or not isinstance(value.get("amount"), int) or isinstance(value.get("amount"), bool) \
                or value["amount"] < 1:
            return ["cost_basis discount_energy must be {kind, amount} with a positive integer amount (Core 356.4.b)"]
        return []
    if not isinstance(value, dict) or set(value) != {"kind"} or value.get("kind") not in LIMITED_PLAY_COST_BASES:
        return [f"cost_basis must be {{kind}} with kind in {sorted(LIMITED_PLAY_COST_BASES)} (Core 356.1.b)"]
    return []


def _limited_play_errors(effect: dict[str, Any]) -> list[str]:
    """The shape of an effect-driven play (Core 419.3): one target in a public zone of its
    controller's, chosen as the effect is played or finalized (GPT 2026-09-25), and what the effect
    changes about the card's cost. Nothing else - an entry location is chosen as the play itself is
    finalized (Core 355.2), and a card chosen from a private zone is not this instruction."""
    errors: list[str] = []
    extra = set(effect) - {"op", "effect_id", "target", "choice", "self", "linked", "decision_ref", "card_filter", "entry",
                           "player", "cost_basis", "depends_on", "dependency_mode", "predicate", "_execution"}
    if extra:
        errors.append(f"carries only its target, choice or self, entry and cost_basis, not {sorted(extra)}")
    errors.extend(_limited_play_cost_basis_errors(effect.get("cost_basis")))
    entry = effect.get("entry")
    if entry is not None and (not isinstance(entry, dict) or set(entry) != {"kind"} or entry.get("kind") not in LIMITED_PLAY_ENTRY_KINDS):
        errors.append(f"entry must be {{kind}} with kind in {sorted(LIMITED_PLAY_ENTRY_KINDS)} (Core 355.2.b)")
    if "player" in effect and (effect["player"] not in LIMITED_PLAY_PLAYERS or "linked" not in effect):
        errors.append(f"player must be one of {sorted(LIMITED_PLAY_PLAYERS)}, and only on a linked play: the card an "
                      f"earlier banish moved, played by its owner (Core 127.1, 419.1)")
    if sum(field in effect for field in ("target", "choice", "self", "linked")) != 1:
        return errors + ["needs exactly one of target (a card in a public zone, Core 355.10.a), choice (a card in "
                         "a private zone, chosen as the effect resolves), self (the program's own source card) or linked "
                         "(the card an earlier banish of the program moved)"]
    if "linked" in effect:
        linked = effect["linked"]
        # package 11 (Promising Future): per_player - inside "each player plays those cards", the banish of THIS
        # iteration's player (the earlier each_player copy of that banish, effect_id@player)
        if not isinstance(linked, dict) or set(linked) - {"per_player"} != {"effect_id", "from"} \
                or linked.get("per_player", True) is not True or linked.get("from") != "banishment" \
                or not isinstance(linked.get("effect_id"), str) or not linked["effect_id"]:
            errors.append("linked must be {effect_id, from: banishment}: the earlier banish whose card is played")
        if "decision_ref" in effect or "card_filter" in effect:
            errors.append("linked chooses nothing: no decision_ref or card_filter")
        return errors
    if "self" in effect:
        if not isinstance(effect["self"], dict) or set(effect["self"]) != {"from"} or effect["self"]["from"] not in LIMITED_PLAY_SELF_ZONES:
            errors.append(f"self must be {{from}} with from in {sorted(LIMITED_PLAY_SELF_ZONES)}: the zone the source card "
                          f"is played from")
        if "decision_ref" in effect or "card_filter" in effect:
            errors.append("self chooses nothing: no decision_ref or card_filter")
        return errors
    if "choice" in effect:
        choice = effect["choice"]
        if (not isinstance(choice, dict) or choice.get("from") not in LIMITED_PLAY_CHOICE_ZONES
                or choice.get("by", "controller") != "controller" or choice.get("selection_kind") != "unordered_set"
                or choice.get("count") != {"up_to": 1} or choice.get("visibility") != "private_to_chooser"):
            errors.append(f"choice must be at most one card (count up_to 1, Core 128.6) of the controller's own "
                          f"{sorted(LIMITED_PLAY_CHOICE_ZONES)}, private to the chooser")
        card_filter = effect.get("card_filter", {})
        if (not isinstance(card_filter, dict) or set(card_filter) - LIMITED_PLAY_CARD_FILTER
                or card_filter.get("kind", "unit") not in LIMITED_PLAY_KINDS or card_filter.get("hidden", True) is not True):
            errors.append(f"card_filter is over {sorted(LIMITED_PLAY_CARD_FILTER)}: a kind, and hidden (the card has [Hidden])")
        if not isinstance(effect.get("decision_ref"), str) or not effect.get("decision_ref"):
            errors.append("a choice names its decision_ref")
        return errors
    if "decision_ref" in effect or "card_filter" in effect:
        errors.append("a target carries its decision_ref and its criteria on the target")
    target = effect.get("target")
    if not isinstance(target, dict):
        return errors + ["needs a target: the card to play, chosen in a public zone (Core 355.10.a)"]
    if target.get("location") not in LIMITED_PLAY_ZONES or target.get("chosen_zone_class") != "non_board":
        errors.append(f"target.location must be one of {sorted(LIMITED_PLAY_ZONES)}, chosen_zone_class non_board: a "
                      f"card the effect plays from a public zone (Core 355.9.a, 355.10.a)")
    if target.get("zone_owner_relation") != "own":
        errors.append("target.zone_owner_relation must be own: the effect's controller plays from their own zone")
    if "kind" in target and target["kind"] not in LIMITED_PLAY_KINDS:
        errors.append(f"target.kind must be one of {sorted(LIMITED_PLAY_KINDS)}")
    if "controller_relation" in target:
        errors.append("target.controller_relation does not apply to a card in a zone; zone_owner_relation says whose")
    return errors


def _limited_play_record_errors(record: Any, players: dict[str, Any]) -> list[str]:
    if not isinstance(record, dict) or not LIMITED_PLAY_RECORD_FIELDS <= set(record) \
            or set(record) - LIMITED_PLAY_RECORD_FIELDS - LIMITED_PLAY_RECORD_OPTIONAL:
        return [f"must carry exactly {sorted(LIMITED_PLAY_RECORD_FIELDS)} (and {sorted(LIMITED_PLAY_RECORD_OPTIONAL)})"]
    errors: list[str] = []
    for key in ("granted_by", "program_id", "effect_id"):
        if not isinstance(record[key], str) or not record[key]:
            errors.append(f"{key} must be a non-empty string")
    # package 8: a card banished by the effect and then played from its owner's Banishment (limited_play linked)
    if record["source_zone"] not in LIMITED_PLAY_ZONES | LIMITED_PLAY_CHOICE_ZONES | {"banishment"}:
        errors.append(f"source_zone must be one of {sorted(LIMITED_PLAY_ZONES | LIMITED_PLAY_CHOICE_ZONES | {'banishment'})}")
    entry = record.get("entry_location")
    if entry is not None and entry != {"kind": "base"} and (
            not isinstance(entry, dict) or set(entry) != {"kind", "battlefield"} or entry.get("kind") != "battlefield"
            or not isinstance(entry.get("battlefield"), str) or not entry["battlefield"]):
        errors.append("entry_location must be {kind: base} or {kind: battlefield, battlefield}")
    if record["zone_owner"] not in players or record["controller_before"] not in players:
        errors.append("zone_owner and controller_before must be players")
    if not isinstance(record["zone_index"], int) or isinstance(record["zone_index"], bool) or record["zone_index"] < 0:
        errors.append("zone_index must be a non-negative integer")
    if not isinstance(record["identity_before"], str) or "@" not in record["identity_before"]:
        errors.append("identity_before must be an identity token")
    errors.extend(_limited_play_cost_basis_errors(record["cost_basis"]))
    return errors


def noted_location_errors(value: Any) -> list[str]:
    """2026-10-12 (package 11, Kog'Maw - Caustic): where a death trigger's source was as its abilities were noted, before
    it moved (Core 808.1.d.3) - a Battlefield, or a player's Base."""
    if isinstance(value, dict) and value.get("kind") == "battlefield" and set(value) == {"kind", "battlefield"} \
            and isinstance(value["battlefield"], str) and value["battlefield"]:
        return []
    if isinstance(value, dict) and value.get("kind") == "base" and set(value) == {"kind", "player"} \
            and isinstance(value["player"], str) and value["player"]:
        return []
    return ["noted_location must be {kind: battlefield, battlefield} or {kind: base, player}, each a non-empty string"]


def validate_program(program: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(program, dict):
        return ["effect program must be an object"]
    if program.get("schema_version") != PROGRAM_VERSION:
        errors.append(f"schema_version must be {PROGRAM_VERSION}")
    if not _ruleset_valid(program.get("ruleset")):
        errors.append("program ruleset must match the R2 v1 baseline")
    if not isinstance(program.get("program_id"), str) or not program.get("program_id"):
        errors.append("program_id must be non-empty")
    errors.extend(_receipt_errors(program.get("cost_receipt")))
    errors.extend(_offer_binding_errors(program))
    # 2026-09-28: the event a watched trigger's chain item recorded, bound in by the engine at
    # resolution (resolution_bridge.bind_trigger_event) - four non-empty strings, nothing else
    trigger_event = program.get("trigger_event")
    if trigger_event is not None and (
            not isinstance(trigger_event, dict) or set(trigger_event) != {"event_id", "kind", "object", "identity"}
            or any(not isinstance(v, str) or not v for v in trigger_event.values())):
        errors.append("trigger_event must be {event_id, kind, object, identity}, each a non-empty string")
    # 2026-10-12 (package 11): a death trigger's noted location, bound in by the engine at resolution
    if program.get("noted_location") is not None:
        errors.extend(noted_location_errors(program["noted_location"]))
    conditional = program.get("conditional_triggers")
    if conditional is not None:
        effect_ids = {e.get("effect_id", f"effect-{i}") for i, e in enumerate(program.get("effects") or []) if isinstance(e, dict)}
        if not isinstance(conditional, list):
            errors.append("conditional_triggers must be an array")
        else:
            required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize", "condition"}
            ids: set[str] = set()
            for i, ct in enumerate(conditional):
                if not isinstance(ct, dict) or not required <= set(ct) or set(ct) - required:
                    errors.append(f"conditional_triggers[{i}] must carry exactly {sorted(required)}")
                    continue
                if not isinstance(ct["trigger_id"], str) or not ct["trigger_id"] or ct["trigger_id"] in ids:
                    errors.append(f"conditional_triggers[{i}].trigger_id is invalid or duplicated")
                ids.add(ct.get("trigger_id", ""))
                cond = ct["condition"]
                keys = {"kind", "effect_id", "domain"} if isinstance(cond, dict) and cond.get("kind") == "revealed_domain" \
                    else {"kind", "effect_id"}
                if isinstance(cond, dict) and cond.get("kind") == "revealed_domain" and (
                        not isinstance(cond.get("domain"), str) or not cond.get("domain")
                        or next((e.get("op") for e in program.get("effects") or [] if isinstance(e, dict)
                                 and e.get("effect_id") == cond.get("effect_id")), None) != "reveal"):
                    errors.append(f"conditional_triggers[{i}].condition revealed_domain names a Domain and a reveal of "
                                  f"this program (Core 387.1.b)")
                if not isinstance(cond, dict) or cond.get("kind") not in CONDITIONAL_TRIGGER_KINDS or set(cond) != keys:
                    errors.append(f"conditional_triggers[{i}].condition must be {{kind, effect_id}} with kind in "
                                  f"{sorted(CONDITIONAL_TRIGGER_KINDS)}")
                elif cond["effect_id"] not in effect_ids:
                    errors.append(f"conditional_triggers[{i}].condition.effect_id {cond['effect_id']!r} is not an instruction of this program")
                if not isinstance(ct["optional_at_finalize"], bool) or not isinstance(ct["controller_order"], int) or ct["controller_order"] < 0:
                    errors.append(f"conditional_triggers[{i}] optional_at_finalize/controller_order are invalid")
    modal = program.get("modal")
    if modal is not None:
        # ADR-0011 §2: the instructions live in the options; each option has a
        # stable id the mode_selection decision names.
        if not isinstance(modal, dict) or not {"choose", "timing", "decision_ref", "options"} <= set(modal) \
                or set(modal) - {"choose", "timing", "decision_ref", "options", "not_chosen_this_turn"} \
                or modal.get("not_chosen_this_turn", True) is not True:
            errors.append("modal must be {choose, timing, decision_ref, options, not_chosen_this_turn?: true}")
        else:
            if modal["choose"] != 1:
                errors.append("modal.choose must be 1 (choose one)")
            if modal["timing"] not in {"play_declaration", "trigger_finalization"}:
                errors.append("modal.timing must be play_declaration or trigger_finalization (Core 402.2)")
            if not isinstance(modal["decision_ref"], str) or not modal["decision_ref"]:
                errors.append("modal.decision_ref must be non-empty")
            options = modal["options"]
            if not isinstance(options, list) or len(options) < 2:
                errors.append("modal.options must list at least two options")
            else:
                seen_options: set[str] = set()
                for o_index, option in enumerate(options):
                    if not isinstance(option, dict) or set(option) != {"option_id", "effects"} or not isinstance(option["option_id"], str) or not option["option_id"]:
                        errors.append(f"modal.options[{o_index}] must be {{option_id, effects}}")
                        continue
                    if option["option_id"] in seen_options:
                        errors.append(f"modal.options[{o_index}].option_id {option['option_id']!r} is duplicated")
                    seen_options.add(option["option_id"])
                    if any(isinstance(e, dict) and e.get("op") == "trigger_base_cost" for e in option["effects"] or []):
                        errors.append(f"modal.options[{o_index}] carries a trigger_base_cost; a base cost inside a "
                                      f"mode is not modelled (the cost belongs to the ability, Core 383.3.b)")
                    synthetic = {k: v for k, v in program.items() if k not in {"modal", "effects"}}
                    synthetic["effects"] = option["effects"]
                    errors.extend(f"modal.options[{o_index}] {e}" for e in validate_program(synthetic))
        if program.get("effects"):
            errors.append("a modal program carries its instructions in modal.options, not in effects")
        return errors
    effects = program.get("effects")
    if not isinstance(effects, list) or not effects:
        errors.append("effects must be a non-empty array")
    elif any(not isinstance(effect, dict) or not isinstance(effect.get("op"), str) for effect in effects):
        errors.append("each effect must be an object with op")
    else:
        seen: set[str] = set()
        for index, effect in enumerate(effects):
            effect_id = effect.get("effect_id", f"effect-{index}")
            if not isinstance(effect_id, str) or not effect_id:
                errors.append(f"effects[{index}].effect_id must be non-empty when supplied")
                continue
            if effect_id in seen:
                errors.append(f"effects[{index}].effect_id is duplicated")
            dependency = effect.get("depends_on")
            if dependency is not None and dependency not in seen:
                errors.append(f"effects[{index}].depends_on must reference an earlier effect")
            if effect.get("dependency_mode", "if_applied") not in DEPENDENCY_MODES:
                errors.append(f"effects[{index}].dependency_mode is invalid")
            # an instruction its controller MAY perform, decided as it resolves (Core 355.12)
            optional = effect.get("optional")
            if optional is not None:
                # package 6: "each player may ..." - decided by the player of the iteration (`by`), not
                # the program's controller; `by` is written only inside each_player (the sentinel)
                if not isinstance(optional, dict) or set(optional) - {"by"} != {"decision_ref"} \
                        or not isinstance(optional.get("decision_ref"), str) or not optional["decision_ref"] \
                        or ("by" in optional and (not isinstance(optional["by"], str) or not optional["by"])):
                    errors.append(f"effects[{index}].optional must be {{decision_ref}} (and by, inside each_player)")
                if effect.get("op") in SELECTION_BINDING_OPS:
                    errors.append(f"effects[{index}].optional is on an instruction, not on a choice")
            subject_identity = effect.get("subject_identity")
            if subject_identity is not None and (not isinstance(subject_identity, str)
                                                 or ("@" not in subject_identity and not subject_identity.startswith("$"))):
                errors.append(f"effects[{index}].subject_identity must be an identity token or a binding")
            if subject_identity is not None and not effect.get("object_id"):
                errors.append(f"effects[{index}].subject_identity needs the object_id it pins")
            predicate = effect.get("predicate")
            if predicate is not None:
                errors.extend(f"effects[{index}].predicate {e}" for e in _predicate_errors(predicate, program.get("cost_receipt"), seen, {e.get("effect_id", f"effect-{i}"): e for i, e in enumerate(effects[:index]) if isinstance(e, dict)}))
            if effect.get("op") == "trigger_base_cost":
                errors.extend(f"effects[{index}].trigger_base_cost {e}"
                              for e in _trigger_base_cost_errors(effect, index, len(effects)))
            if effect.get("op") == "limited_play":
                errors.extend(f"effects[{index}].limited_play {e}" for e in _limited_play_errors(effect))
            if effect.get("op") == "recycle_when_leaving_chain":
                linked = effect.get("linked")
                earlier = {e.get("effect_id"): e for e in effects[:index] if isinstance(e, dict)}
                if set(effect) - {"op", "effect_id", "linked", "depends_on", "dependency_mode", "_execution"} \
                        or not isinstance(linked, dict) or set(linked) != {"effect_id"} \
                        or (earlier.get(linked.get("effect_id")) or {}).get("op") != "limited_play":
                    errors.append(f"effects[{index}].recycle_when_leaving_chain carries only linked {{effect_id}}: an "
                                  f"earlier limited_play of this program, whose card it binds (Core 390.3.a)")
            if effect.get("op") == "gain_control_of_spell":
                targeted = effect.get("target")
                if not isinstance(effect.get("player"), str) or not isinstance(targeted, dict) \
                        or targeted.get("location") != "chain" or targeted.get("chosen_zone_class") != "non_board" \
                        or targeted.get("kind") != "spell":
                    errors.append(f"effects[{index}].gain_control_of_spell targets a spell on the Chain "
                                  f"{{chosen_zone_class: non_board, location: chain, kind: spell}} and names the player")
            if effect.get("op") == "make_new_choices":
                earlier = {e.get("effect_id"): e for e in effects[:index] if isinstance(e, dict)}
                linked = effect.get("linked")
                if set(effect) - {"op", "effect_id", "linked", "optional", "depends_on", "dependency_mode", "_execution"} \
                        or not isinstance(effect.get("optional"), dict) or not isinstance(linked, dict) or set(linked) != {"effect_id"} \
                        or (earlier.get(linked.get("effect_id")) or {}).get("op") != "gain_control_of_spell":
                    errors.append(f"effects[{index}].make_new_choices is optional and linked to an earlier "
                                  f"gain_control_of_spell of this program (Core 751)")
            if effect.get("op") in {"banish_one_looked", "recycle_looked_rest"} and (
                    set(effect) - {"op", "effect_id", "player", "decision_ref", "order_ref", "depends_on", "dependency_mode",
                                   "_execution", EACH_PLAYER_FIELD, "each_player_of"}
                    or not isinstance(effect.get("player"), str)):
                errors.append(f"effects[{index}].{effect.get('op')} names the player whose looked-at cards it reads")
            if effect.get("op") == "activate_conquer_effects" and (
                    set(effect) - {"op", "effect_id", "location_ref", "depends_on", "dependency_mode", "_execution"}
                    or not is_location_ref(effect.get("location_ref"))):
                errors.append(f"effects[{index}].activate_conquer_effects names the Battlefield by location_ref (Core 383.4.g.1)")
            if effect.get("op") == "gain_control" and not isinstance(effect.get("player"), str):
                errors.append(f"effects[{index}].gain_control names the player who takes control (Core 189)")
            if effect.get("op") == "take_additional_turn":
                if set(effect) - {"op", "effect_id", "player", "depends_on", "dependency_mode", "_execution"} \
                        or not isinstance(effect.get("player"), str):
                    errors.append(f"effects[{index}].take_additional_turn carries only the player who takes it (Core 735)")
            if effect.get("op") == "banish_this":
                if set(effect) - {"op", "effect_id", "depends_on", "dependency_mode", "_execution"}:
                    errors.append(f"effects[{index}].banish_this carries nothing: it is the resolving card itself")
            if effect.get("op") == "swap_might":
                units = effect.get("units")
                if not isinstance(units, list) or len(units) != 2:
                    errors.append(f"effects[{index}].swap_might needs exactly two unit selectors")
                else:
                    for position, selector in enumerate(units):
                        for problem in _selector_errors(selector):
                            errors.append(f"effects[{index}].swap_might.units[{position}] {problem}")
                if {"target", "targets", "object_id", "affected"} & set(effect):
                    errors.append(f"effects[{index}].swap_might carries its two units, not target/targets/object_id/affected")
                if "amount" in effect or "value" in effect:
                    errors.append(f"effects[{index}].swap_might takes no amount or value: the change is the "
                                  f"difference between the two Mights, read once at resolution (Core 477)")
                if effect.get("duration") not in {"this_turn", None}:
                    errors.append(f"effects[{index}].swap_might may only last this_turn")
            if effect.get("op") == "raise_might_to_match":
                units = effect.get("units")
                if not isinstance(units, list) or len(units) != 2:
                    errors.append(f"effects[{index}].raise_might_to_match needs exactly two unit selectors: the one "
                                  f"raised, then the one whose Might it is raised to")
                else:
                    for position, selector in enumerate(units):
                        for problem in _selector_errors(selector):
                            errors.append(f"effects[{index}].raise_might_to_match.units[{position}] {problem}")
                if {"target", "targets", "object_id", "affected", "amount", "value", "minimum", "maximum"} & set(effect):
                    errors.append(f"effects[{index}].raise_might_to_match carries its two units and nothing else: the "
                                  f"increase is the difference read once at resolution (Core 477)")
                if effect.get("duration") != "this_turn":
                    errors.append(f"effects[{index}].raise_might_to_match lasts this_turn")
            if effect.get("op") == "mutual_damage_current_might":
                units = effect.get("units")
                if not isinstance(units, list) or len(units) != 2:
                    errors.append(f"effects[{index}].mutual_damage_current_might needs exactly two unit selectors")
                else:
                    for j, sel in enumerate(units):
                        if isinstance(sel, dict) and is_object_ref(sel.get("object_id")):
                            # the source in one slot (OBJECT_REF_UNIT_SLOT_OPS): a Unit on the board, nothing chosen
                            # package 11: or the trigger's referent (Dragon's Rage's moved unit), the same shape
                            if sel["object_id"] not in ({"object_ref": "program_source"}, {"object_ref": TRIGGER_EVENT_OBJECT}) \
                                    or set(sel) != {"object_id", "chosen_zone_class", "kind"} \
                                    or sel.get("chosen_zone_class") != "board" or sel.get("kind") != "unit":
                                errors.append(f"effects[{index}].units[{j}] names the source (or the trigger's referent) as "
                                              f"exactly {{object_id: {{object_ref: program_source | trigger_event_object}}, "
                                              f"chosen_zone_class: board, kind: unit}}")
                        else:
                            errors.extend(f"effects[{index}].units[{j}] {e}" for e in _selector_errors(sel))
                    if sum(1 for sel in units if isinstance(sel, dict) and is_object_ref(sel.get("object_id"))) > 1:
                        errors.append(f"effects[{index}].mutual_damage_current_might names the source in one slot at most")
                if effect.get("target") is not None or effect.get("targets") is not None or effect.get("object_id") is not None or effect.get("affected") is not None:
                    errors.append(f"effects[{index}].mutual_damage_current_might carries its two units, not target/targets/object_id/affected")
                if "amount" in effect:
                    # The damage IS each Unit's effective Might read at
                    # resolution (417.6.b.3); there is no authored amount. The
                    # field was tolerated and never read by this op's own
                    # branch, but the generic reduce_damage replacement path
                    # reads `amount` off whatever effect it is applied to, so
                    # leaving it accepted left a field that looks authoritative
                    # and is not. Refused rather than ignored.
                    errors.append(f"effects[{index}].mutual_damage_current_might takes no `amount`: the damage is each Unit's current Might, read at resolution")
            if "amount_ref" in effect:
                if not is_amount_ref(effect["amount_ref"]):
                    errors.append(f"effects[{index}].amount_ref must be {{kind}} with kind in {list(AMOUNT_REF_KINDS)} "
                                  f"({{kind, effect_id}} for {sorted(LINKED_AMOUNT_REF_KINDS)})")
                elif effect["amount_ref"]["kind"] in LINKED_AMOUNT_REF_KINDS and effect["amount_ref"]["effect_id"] not in seen:
                    errors.append(f"effects[{index}].amount_ref.effect_id must name an earlier instruction")
                if effect["amount_ref"].get("kind") == LINKED_PAID_AMOUNT:
                    producer = next((e for e in effects[:index] if isinstance(e, dict)
                                     and e.get("effect_id") == effect["amount_ref"].get("effect_id")), None)
                    if (producer or {}).get("op") != "pay_any_amount":
                        errors.append(f"effects[{index}].amount_ref {LINKED_PAID_AMOUNT} names an earlier pay_any_amount")
                    if ((effect.get("affected") or {}).get("criteria") or {}).get("location") != "target_battlefield" \
                            or effect.get("targets") is not None:
                        errors.append(f"effects[{index}].amount_ref {LINKED_PAID_AMOUNT} is read by a deal over a targeted "
                                      f"battlefield's group only")
                if effect["amount_ref"].get("kind") == "object_current_might":
                    if effect.get("op") != "modify_might" or effect.get("duration") != "this_turn" \
                            or not isinstance(effect.get("target"), dict) or {"minimum", "maximum"} & set(effect):
                        errors.append(f"effects[{index}].amount_ref object_current_might is read by a this-turn "
                                      f"modify_might on one target only, with no bounds")
                elif effect.get("op") != "deal_damage":
                    errors.append(f"effects[{index}].amount_ref is read by deal_damage only")
                if "amount" in effect:
                    errors.append(f"effects[{index}] carries both amount and amount_ref; the amount is one or the other")
                # 2026-10-08 package 10 (Stormbringer: "Deal damage equal to its Might to all enemy units at a
                # battlefield"): a LINKED Might read once as the instruction executes, dealt to each unit of a targeted
                # Battlefield's group - the one group shape it is admitted on
                group_might = (effect.get("affected") is not None and effect.get("targets") is None
                               and effect["amount_ref"].get("kind") in ("linked_object_current_might", LINKED_PAID_AMOUNT)
                               and ((effect.get("affected") or {}).get("criteria") or {}).get("location") == "target_battlefield")
                if (effect.get("affected") is not None or effect.get("targets") is not None) and not group_might:
                    errors.append(f"effects[{index}].amount_ref: one chosen object only (affected/targets are not accepted)")
            if effect.get("op") == "modify_might":
                for bound in ("minimum", "maximum"):
                    value = effect.get(bound)
                    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                        errors.append(f"effects[{index}].modify_might.{bound} must be an integer when supplied (Core 477)")
            if effect.get("op") == "grant_keyword":
                if effect.get("keyword") not in GRANTABLE_KEYWORDS:
                    errors.append(f"effects[{index}].grant_keyword.keyword must be one of {sorted(GRANTABLE_KEYWORDS)}")
                if effect.get("duration") not in KEYWORD_MODIFIER_DURATIONS and not (
                        effect.get("duration") == "permanent" and effect.get("keyword") in UNTIMED_GRANTABLE_KEYWORDS):
                    errors.append(f"effects[{index}].grant_keyword.duration must be one of {sorted(KEYWORD_MODIFIER_DURATIONS)}"
                                  f" (or permanent, for {sorted(UNTIMED_GRANTABLE_KEYWORDS)})")
                if "value" in effect and (not isinstance(effect["value"], int) or isinstance(effect["value"], bool) or effect["value"] < 1):
                    errors.append(f"effects[{index}].grant_keyword.value must be a positive integer")
                if not isinstance(effect.get("source"), str) or not effect.get("source"):
                    errors.append(f"effects[{index}].grant_keyword requires a source")
            if effect.get("op") == "create_delayed_trigger":
                import watchers
                spec = effect.get("delayed")
                if not isinstance(spec, dict):
                    errors.append(f"effects[{index}].create_delayed_trigger needs a `delayed` descriptor")
                else:
                    supplied = set(spec)
                    required = {"delayed_id", "controller", "source_object", "waits_for", "effect_program_id",
                                "optional_at_finalize", "controller_order"}
                    if not required <= supplied or supplied - (watchers.DELAYED_FIELDS - {"source_identity", "created_turn",
                                                                                         "effect_program_hash"}):
                        errors.append(f"effects[{index}].delayed must carry {sorted(required)} and may add "
                                      "target_object, target_identity and snapshot; the identities, the turn and the "
                                      "program's hash are bound by the engine")
                    # 2026-09-27 package 6: "at the end of THIS turn" (Targon's Peak) - the turn is the
                    # one the instruction runs in, bound by the engine as it creates the trigger
                    waits = spec.get("waits_for")
                    if isinstance(waits, dict) and "turn" in waits and (
                            waits.get("turn") != "this_turn" or waits.get("kind") != "turn"
                            or waits.get("moment") != "end_of_turn" or set(waits) != {"kind", "moment", "turn"}):
                        errors.append(f"effects[{index}].delayed.waits_for may name only {{kind: turn, moment: end_of_turn, "
                                      "turn: this_turn}} - the end of the turn it is created in (Core 390.2)")
                # 2026-09-27 package 6: the delayed trigger's own instructions, carried by the
                # instruction that creates it - its content hash is bound on the trigger, so what
                # resolves at the end of the turn is exactly this program (resolution_bridge.dispatch_program)
                if "effects" in effect:
                    nested = effect["effects"]
                    if not isinstance(nested, list) or not nested:
                        errors.append(f"effects[{index}].create_delayed_trigger.effects must be a non-empty list of instructions")
                    elif any(isinstance(e, dict) and e.get("op") == "create_delayed_trigger" for e in nested):
                        errors.append(f"effects[{index}].create_delayed_trigger.effects may not create another delayed trigger")
                    else:
                        errors.extend(f"effects[{index}].effects: {problem}" for problem in validate_program(
                            {"schema_version": PROGRAM_VERSION, "ruleset": program.get("ruleset"),
                             "program_id": f"{program.get('program_id')}:delayed", "effects": nested}))
            if effect.get("op") == "add_resource" and effect.get("restriction") is not None:
                restriction = effect["restriction"]
                if not isinstance(restriction, dict) or set(restriction) != {"uses"} or not isinstance(restriction["uses"], list) or not restriction["uses"] or any(u not in RESOURCE_USES for u in restriction["uses"]) or len(restriction["uses"]) != len(set(restriction["uses"])):
                    errors.append(f"effects[{index}].add_resource.restriction must be {{uses: non-empty unique subset of {RESOURCE_USES}}}")
                if effect.get("resource") not in {"energy", "power"}:
                    errors.append(f"effects[{index}].add_resource.restriction applies to energy or power")
            if effect.get("op") == "add_resource" and "universal" in effect:
                # 2026-09-27: "[Add] [A]" - Power of any Domain (Core 135.2.e.5, 135.2.e.5.b, 163.2.b): Power,
                # no Domain named, `universal: true`
                if effect["universal"] is not True or effect.get("resource") != "power" or "domain" in effect:
                    errors.append(f"effects[{index}].add_resource.universal is `true` on power with no domain "
                                  f"(Core 135.2.e.5.b)")
            # Sabotage: "they" - a player an earlier instruction of this same
            # program chose. Deferring is only legal to a decision reference;
            # anything else is a player named, or an error.
            player_field = effect.get("player")
            if is_object_player(player_field):
                # 2026-09-27: "its controller" / "its owner" - an EARLIER instruction of this
                # program named by effect_id (Core 359.3.e.14); a later or unknown one is refused
                if player_field["object_player"]["effect_id"] not in seen:
                    errors.append(f"effects[{index}].player.object_player.effect_id must name an earlier instruction")
            elif isinstance(player_field, dict) and (set(player_field) != {"decision_ref"}
                                                     or not isinstance(player_field.get("decision_ref"), str)
                                                     or not player_field["decision_ref"]):
                errors.append(f"effects[{index}].player must be a player id, {{decision_ref}} or "
                              f"{{object_player: {{effect_id, relation}}}} with relation in {list(OBJECT_PLAYER_RELATIONS)}")
            if "count_per" in effect and isinstance(effect["count_per"], dict) \
                    and effect["count_per"].get("kind") == LINKED_REVEALED_COUNT:
                # package 11 (Teemo - Strategist): the cards an earlier reveal of this program showed, with the keyword
                earlier = next((e for e in effects[:index] if isinstance(e, dict)
                                and e.get("effect_id") == effect["count_per"].get("effect_id")), None)
                if not is_count_per(effect["count_per"]):
                    errors.append(f"effects[{index}].count_per {LINKED_REVEALED_COUNT} is {{kind, effect_id, keyword}} "
                                  f"with keyword in {sorted(LINKED_REVEALED_KEYWORDS)}")
                elif earlier is None or earlier.get("op") != "reveal" or earlier.get("from") != "main_deck_top":
                    errors.append(f"effects[{index}].count_per.effect_id must name an earlier reveal of the Main Deck's top")
                if effect.get("op") not in LINKED_REVEALED_READERS:
                    errors.append(f"effects[{index}].count_per {LINKED_REVEALED_COUNT} is read by {sorted(LINKED_REVEALED_READERS)} only")
                if not isinstance(effect.get("amount"), int) or isinstance(effect.get("amount"), bool) or effect.get("amount", 0) < 1:
                    errors.append(f"effects[{index}].count_per multiplies a positive printed amount")
            elif "count_per" in effect:
                linked_count = isinstance(effect["count_per"], dict) and effect["count_per"].get("kind") == "linked_applied_count"
                if not is_count_per(effect["count_per"]):
                    errors.append(f"effects[{index}].count_per must be {{kind: units_you_control, mighty: true}} "
                                  f"or {{kind: linked_applied_count, effect_id}}")
                elif linked_count:
                    earlier = next((e for e in effects[:index] if isinstance(e, dict)
                                    and e.get("effect_id") == effect["count_per"]["effect_id"]), None)
                    if earlier is None or earlier.get("op") not in LINKED_COUNT_OPS:
                        errors.append(f"effects[{index}].count_per.effect_id must name an earlier instruction whose "
                                      f"receipt is a count ({sorted(LINKED_COUNT_OPS)})")
                if linked_count and effect.get("op") not in LINKED_COUNT_READERS:
                    errors.append(f"effects[{index}].count_per linked_applied_count is read by {sorted(LINKED_COUNT_READERS)} only")
                elif not linked_count and effect.get("op") != "draw":
                    errors.append(f"effects[{index}].count_per is read by draw only")
                if not isinstance(effect.get("count"), int) or isinstance(effect.get("count"), bool) or effect.get("count", 0) < 1:
                    errors.append(f"effects[{index}].count_per multiplies a positive printed count")
            if effect.get("op") == "spend_buffs":
                # package 10 (Sett - The Boss: "spend ITS buff"): one named Unit's buff - not a choice - by object_id
                # (its subject_identity pins it inside a replacement), never together with a decision
                extra = set(effect) - {"op", "effect_id", "player", "decision_ref", "order", EXECUTION_FIELD,
                                       "object_id", "subject_identity"}
                if "object_id" in effect and "decision_ref" in effect:
                    errors.append(f"effects[{index}].spend_buffs names one Unit (object_id) or chooses (decision_ref), "
                                  f"not both")
                if extra:
                    errors.append(f"effects[{index}].spend_buffs takes only player and decision_ref; not {sorted(extra)} "
                                  "(what it spends is chosen as it resolves, Core 355.17)")
                if not isinstance(effect.get("player"), str) or not effect.get("player"):
                    errors.append(f"effects[{index}].spend_buffs names the player who spends")
                if "decision_ref" in effect and (not isinstance(effect.get("decision_ref"), str) or not effect.get("decision_ref")):
                    errors.append(f"effects[{index}].spend_buffs.decision_ref names the resolution-stage choice")
            if "source_ref" in effect:
                if not is_source_ref(effect["source_ref"]):
                    errors.append(f"effects[{index}].source_ref must be {{effect_id}}")
                elif effect["source_ref"]["effect_id"] not in seen:
                    errors.append(f"effects[{index}].source_ref.effect_id must name an earlier instruction")
                if effect.get("op") != "deal_damage":
                    errors.append(f"effects[{index}].source_ref is read by deal_damage only")
                if "source_object" in effect:
                    errors.append(f"effects[{index}] carries both source_object and source_ref; the source is one or the other")
            choice = effect.get("choice")
            if choice is not None:
                import engine_decisions as ed
                errors.extend(f"effects[{index}].choice {e}" for e in ed.validate_choice_spec(choice))
                if effect.get("op") not in CHOICE_OPS | SELF_RESOLVING_CHOICE_OPS | SELECTION_BINDING_OPS \
                        | RESOLUTION_CHOICE_OPS | {"choose_objects", "limited_play"} \
                        and not (effect.get("op") == "discard" and choice == DISCARD_REVEALED_CHOICE):
                    # (package 10, Mindsplitter: a discard carries exactly DISCARD_REVEALED_CHOICE, checked with the op)
                    errors.append(f"effects[{index}].choice is not supported for {effect.get('op')!r}")
                elif effect.get("op") in {"recycle_one"} and not errors and (choice["selection_kind"] != "single" or choice["from"] not in {"trash", "hand"}):
                    errors.append(f"effects[{index}].{effect.get('op')} chooses a single card from trash or hand")
                elif effect.get("op") in RESOLUTION_CHOICE_OPS and isinstance(choice, dict) and (
                        choice.get("selection_kind") != "single" or choice.get("from") != "board"
                        or not isinstance(effect.get("decision_ref"), str) or not effect.get("decision_ref")):
                    # package 6: one object on the board, chosen as it resolves (Core 355.10.e), answered
                    # under the instruction's own decision_ref
                    errors.append(f"effects[{index}].{effect.get('op')} chooses a single object from the board "
                                  f"as it resolves, under its own decision_ref")
                if effect.get("object_id") is not None or effect.get("target") is not None or effect.get("targets") is not None:
                    errors.append(f"effects[{index}].choice excludes object_id, target and targets")
            op_name = effect.get("op")
            if op_name == "establish_selection":
                # It names the selection later instructions refer to, and the
                # decision that answers it. Whether the SHAPE of the choice is
                # wired is a resolution-time question (`unsupported`), not a
                # malformed-program one.
                if not isinstance(effect.get("selection_id"), str) or not effect.get("selection_id"):
                    errors.append(f"effects[{index}].establish_selection needs the selection_id later instructions refer to")
                if not isinstance(effect.get("choice"), dict):
                    errors.append(f"effects[{index}].establish_selection needs the typed choice it establishes")
                if not isinstance(effect.get("decision_ref"), str) or not effect.get("decision_ref"):
                    errors.append(f"effects[{index}].establish_selection needs the decision_ref that answers it")
                if effect.get("affected") is not None:
                    errors.append(f"effects[{index}].establish_selection establishes one selection; affected is not accepted")
            if effect.get("op") == "each_player":
                # package 6: "Each player ..." (Core 303.2.a, 411.1)
                if effect.get("players") not in EACH_PLAYER_SETS:
                    errors.append(f"effects[{index}].each_player.players must be one of {list(EACH_PLAYER_SETS)}")
                if effect.get("order") not in EACH_PLAYER_ORDERS:
                    errors.append(f"effects[{index}].each_player.order must be one of {list(EACH_PLAYER_ORDERS)}")
                only = effect.get("only_chose")
                if only is not None and (not isinstance(only, dict) or set(only) != {"record", "option"}
                                         or any(not isinstance(only[k], str) or not only[k] for k in ("record", "option"))):
                    errors.append(f"effects[{index}].each_player.only_chose must be {{record, option}}")
                stray = {"target", "targets", "affected", "choice", "optional", "object_id", "player", "predicate",
                         "depends_on", "decision_ref", "count", "amount"} & set(effect)
                if stray:
                    errors.append(f"effects[{index}].each_player carries its instructions in effects; {sorted(stray)} "
                                  f"belong to them")
                nested = effect.get("effects")
                if not isinstance(nested, list) or not nested or any(not isinstance(e, dict) for e in nested):
                    errors.append(f"effects[{index}].each_player.effects must be a non-empty array of instructions")
                else:
                    for n_index, inner in enumerate(nested):
                        if inner.get("op") not in EACH_PLAYER_NESTED_OPS:
                            errors.append(f"effects[{index}].each_player.effects[{n_index}] op {inner.get('op')!r} is not "
                                          f"run per player; one of {sorted(EACH_PLAYER_NESTED_OPS)}")
                    # (package 11: a play linked per_player names the iteration's player through its link)
                    if not _mentions_sentinel(nested) and not any(
                            inner.get("op") == "limited_play" and (inner.get("linked") or {}).get("per_player") for inner in nested):
                        errors.append(f"effects[{index}].each_player: no instruction names the player of the "
                                      f"iteration ({EACH_PLAYER_SENTINEL})")
                    synthetic = {k: v for k, v in program.items() if k not in {"effects", "modal"}}
                    synthetic["effects"] = nested
                    synthetic[EACH_PLAYER_BODY] = True
                    errors.extend(f"effects[{index}].each_player.{e}" for e in validate_program(synthetic))
            elif _mentions_sentinel(effect) and not program.get(EACH_PLAYER_BODY):
                errors.append(f"effects[{index}] names {EACH_PLAYER_SENTINEL} outside an each_player instruction")
            if effect.get("op") == "choose_objects":
                # package 6: a choice that fills a group ("each player chooses 2 units", "chooses a unit ...
                # that hasn't been chosen for this spell"); it changes no state
                if not isinstance(effect.get("group"), str) or not effect.get("group"):
                    errors.append(f"effects[{index}].choose_objects needs the group its objects go into")
                if not isinstance(effect.get("choice"), dict) or effect["choice"].get("from") not in {"board", "hand"}:
                    errors.append(f"effects[{index}].choose_objects chooses from the board or a hand")
                if not isinstance(effect.get("decision_ref"), str) or not effect.get("decision_ref"):
                    errors.append(f"effects[{index}].choose_objects needs the decision_ref that answers it")
                if effect.get("distinct_in_group") not in (None, True):
                    errors.append(f"effects[{index}].choose_objects.distinct_in_group is true when present")
            if effect.get("only_if_chose") is not None:
                # package 9 (Qiyana - Victorious): this instruction runs only if the controller's recorded option, made
                # by an EARLIER choose_option of this program, is this option
                only = effect["only_if_chose"]
                earlier = [e for e in effects[:index] if isinstance(e, dict) and e.get("op") == "choose_option"
                           and e.get("record") == (only or {}).get("record") if isinstance(only, dict)]
                if not isinstance(only, dict) or set(only) != {"record", "option"} or not earlier \
                        or only["option"] not in (earlier[-1].get("options") or []):
                    errors.append(f"effects[{index}].only_if_chose must be {{record, option}} naming an earlier "
                                  f"choose_option's record and one of its options")
            if effect.get("op") == "choose_option":
                options = effect.get("options")
                if not isinstance(options, list) or len(options) < 2 or len(options) != len(set(options)) \
                        or any(not isinstance(o, str) or not o for o in options):
                    errors.append(f"effects[{index}].choose_option.options must list two or more distinct names")
                for field in ("record", "decision_ref", "by"):
                    if not isinstance(effect.get(field), str) or not effect.get(field):
                        errors.append(f"effects[{index}].choose_option needs {field}")
            if effect.get("group_ref") is not None:
                if effect.get("op") not in GROUP_OPS or not isinstance(effect["group_ref"], str) or not effect["group_ref"]:
                    errors.append(f"effects[{index}].group_ref names a group for one of {sorted(GROUP_OPS)}")
                if {"target", "targets", "affected", "choice", "object_id"} & set(effect):
                    errors.append(f"effects[{index}].group_ref acts on the group; it chooses and targets nothing")
            if op_name == "copy_object":
                if not isinstance(effect.get("source_object"), str) or not effect.get("source_object"):
                    errors.append(f"effects[{index}].copy_object needs the object it copies")
                if not isinstance(effect.get("request_id"), str) or not effect.get("request_id"):
                    errors.append(f"effects[{index}].copy_object needs a request_id so the copy can be traced")
                if not isinstance(effect.get("object_id"), str) or not effect.get("object_id"):
                    errors.append(f"effects[{index}].copy_object needs the object that becomes the copy")
                traits = effect.get("traits")
                if traits is not None and (not isinstance(traits, list) or not traits or any(not isinstance(t, str) for t in traits)):
                    errors.append(f"effects[{index}].copy_object.traits must be a non-empty array of trait names")
            if op_name in {"empower", "disempower", "buff"}:
                # These act on ONE object, named either literally (`object_id`,
                # the "Buff me." path) or through the same typed decision_ref
                # target stun/kill/ready/exhaust accept; resolution then writes
                # target.object_id onto the effect before _apply_one reads it.
                # Until 2026-09-09 this branch demanded a literal object_id, so
                # clause-grammar.v1's own buff_selector output for "Buff a
                # friendly unit." failed this validator. Still one object: an
                # `affected` or `targets` form ("Buff all ...") stays refused.
                has_object = ((isinstance(effect.get("object_id"), str) and bool(effect.get("object_id")))
                              or is_object_ref(effect.get("object_id")))
                has_target = isinstance(effect.get("target"), dict)
                # 2026-09-27 package 6: a buff over a bounded set of Targets or a set found by criteria
                # (MULTI_TARGET_OPS) is expanded into one single-object buff per object, each exactly
                # the one-object form above; empower and disempower still act on one object only
                many = op_name == "buff" and (effect.get("affected") is not None or effect.get("targets") is not None)
                if not (has_object or has_target or many):
                    errors.append(f"effects[{index}].{op_name} needs the object it acts on")
                if not many and (effect.get("affected") is not None or effect.get("targets") is not None):
                    errors.append(f"effects[{index}].{op_name} acts on one object; affected/targets are not accepted")
            if op_name == "gain_xp":
                if not isinstance(effect.get("player"), str) or not effect.get("player"):
                    errors.append(f"effects[{index}].gain_xp needs a player")
                if not isinstance(effect.get("amount"), int) or isinstance(effect.get("amount"), bool) or effect.get("amount", 0) < 1:
                    errors.append(f"effects[{index}].gain_xp needs a positive amount")
            if op_name == "create_turn_replacement":
                spec = effect.get("replacement")
                if not isinstance(spec, dict) or spec != {"mode": "prevent_event", "event_op": "deal_damage",
                                                          "damage_sources": ["spell", "ability"]}:
                    errors.append(f"effects[{index}].create_turn_replacement takes exactly {{mode prevent_event, event_op "
                                  f"deal_damage, damage_sources [spell, ability]}} (the one typed shape)")
                if not isinstance(effect.get("controller"), str) or not effect.get("controller"):
                    errors.append(f"effects[{index}].create_turn_replacement needs its controller")
            if op_name == "win_game":
                if not isinstance(effect.get("player"), str) or not effect.get("player"):
                    errors.append(f"effects[{index}].win_game needs the player it makes win")
                if set(effect) - {"op", "effect_id", "player", "order"}:
                    errors.append(f"effects[{index}].win_game takes only a player")
            if op_name == "gain_point":
                if not isinstance(effect.get("player"), str) or not effect.get("player"):
                    errors.append(f"effects[{index}].gain_point needs a player")
                if not isinstance(effect.get("amount"), int) or isinstance(effect.get("amount"), bool) or effect.get("amount", 0) < 1:
                    errors.append(f"effects[{index}].gain_point needs a positive amount")
                if effect.get("battlefield") is not None:
                    errors.append(f"effects[{index}].gain_point names a battlefield; a point "
                                  f"gained from a card is not a Battlefield being Scored, and "
                                  f"naming one would read as running 471.2's Score triggers")
            if op_name in {"attach", "detach"}:
                if not isinstance(effect.get("object_id"), str) or not effect.get("object_id"):
                    errors.append(f"effects[{index}].{op_name} needs the object it links or unlinks")
                if op_name == "attach" and (not isinstance(effect.get("to"), str) or not effect.get("to")):
                    errors.append(f"effects[{index}].attach needs the Top-Most card in `to` (Core 434.1.b)")
                if op_name == "detach" and "to" in effect:
                    errors.append(f"effects[{index}].detach carries no `to`")
            if op_name in {"banish", "counter", "burn"}:
                errors.extend(f"effects[{index}].{op_name} {e}" for e in _zone_op_errors(effect))
            if op_name in {"look_at_top", "reveal", "put_back", "put_in_hand", "draw_it", "recycle", "predict"}:
                errors.extend(f"effects[{index}].{op_name} {e}" for e in _reveal_op_errors(effect))
            if op_name == "reveal_until":
                if not isinstance(effect.get("player"), str) or not effect.get("player"):
                    errors.append(f"effects[{index}].reveal_until requires a player")
                if effect.get("until") not in ({"kind": "unit"}, {"kind": "gear"}, {"kind": "spell"}):
                    errors.append(f"effects[{index}].reveal_until until must be {{kind}} of a card kind")
                if set(effect) - {"op", "effect_id", "player", "until", "depends_on", "dependency_mode", "predicate", "_execution"}:
                    errors.append(f"effects[{index}].reveal_until carries only player and until")
            if effect.get("op") == "discard" and effect.get("choice") is not None:
                # 2026-10-08 package 10 (Mindsplitter): "Choose a card from it, and they discard that card." - the
                # program's controller chooses ONE card of what an earlier HAND reveal of this program showed (Core
                # 424.2.b), named by that reveal's effect_id (reveal_ref); "they" - the player whose hand it revealed -
                # discards it (422.1). The player is the reveal's, never named again; nothing else of the discard form
                if effect["choice"] != DISCARD_REVEALED_CHOICE:
                    errors.append(f"effects[{index}].discard.choice must be {DISCARD_REVEALED_CHOICE}")
                revealer = next((e for e in effects[:index] if isinstance(e, dict) and e.get("effect_id") == effect.get("reveal_ref")),
                                None)
                if revealer is None or revealer.get("op") != "reveal" or revealer.get("from") != "hand":
                    errors.append(f"effects[{index}].discard from a reveal names, as reveal_ref, an earlier hand reveal "
                                  f"of this program")
                if not isinstance(effect.get("decision_ref"), str) or not effect["decision_ref"]:
                    errors.append(f"effects[{index}].discard from a reveal needs its decision_ref")
                if {"player", "count", "whole_hand", "objects", "target", "targets"} & set(effect):
                    errors.append(f"effects[{index}].discard from a reveal is one chosen card of the revealed hand: no "
                                  f"player, count, whole_hand, objects or target")
            elif effect.get("op") == "discard":
                # package 6: "discards their hand" - every card in it, however many there are at
                # execution (whole_hand, no count); an empty hand discards nothing (Core 422.4)
                whole = effect.get("whole_hand")
                if whole is not None and (whole is not True or "count" in effect or "decision_ref" in effect):
                    errors.append(f"effects[{index}].discard.whole_hand is true, with no count and no decision_ref")
                elif not isinstance(effect.get("player"), str) or (whole is None and (
                        not isinstance(effect.get("count"), int) or effect.get("count", 0) < 1)):
                    errors.append(f"effects[{index}].discard requires player and a positive count")
                if "decision_ref" in effect and (not isinstance(effect["decision_ref"], str) or not effect["decision_ref"]):
                    errors.append(f"effects[{index}].discard.decision_ref must be a non-empty string")
                if effect.get("target") is not None or effect.get("targets") is not None or effect.get("objects") is not None:
                    errors.append(f"effects[{index}].discard is not a targeted instruction (Core 355.10.a) and resolves its own selection")
            modifiers = effect.get("event_modifiers")
            if modifiers is not None:
                if effect.get("op") != "play_token" or not isinstance(modifiers, dict) or not modifiers or set(modifiers) - {"entry_state", "result_keywords"}:
                    errors.append(f"effects[{index}].event_modifiers is unsupported for this operation")
                else:
                    if modifiers.get("entry_state") not in {None, "ready", "exhausted"}:
                        errors.append(f"effects[{index}].event_modifiers.entry_state is invalid")
                    result_keywords = modifiers.get("result_keywords", [])
                    if not isinstance(result_keywords, list) or len(result_keywords) != len(set(result_keywords)) or any(keyword not in {"temporary"} for keyword in result_keywords):
                        errors.append(f"effects[{index}].event_modifiers.result_keywords is invalid")
            if effect.get("op") == "pay_any_amount":
                # a variable payment of any Domains' Power, sized and made at resolution - whether to pay at all
                # (pay_ref, an optional_choice) and the complete allocation (decision_ref, a resource_allocation; {} is 0)
                if set(effect) - {"op", "effect_id", "resource", "decision_ref", "pay_ref"} or effect.get("resource") != "power_any" \
                        or not all(isinstance(effect.get(k), str) and effect.get(k) for k in ("decision_ref", "pay_ref")):
                    errors.append(f"effects[{index}].pay_any_amount is {{resource power_any, decision_ref, pay_ref}}")
            if "unless" in effect:
                unless = effect["unless"]
                instead = (unless or {}).get("instead") if isinstance(unless, dict) else None
                if effect.get("op") not in UNLESS_OPS or not isinstance(effect.get("target"), dict):
                    errors.append(f"effects[{index}].unless is read on a targeted {sorted(UNLESS_OPS)} only")
                if not isinstance(unless, dict) or set(unless) != {"decision_ref", "instead"} \
                        or not isinstance(unless.get("decision_ref"), str) or not unless["decision_ref"]:
                    errors.append(f"effects[{index}].unless is {{decision_ref, instead}}")
                elif not isinstance(instead, list) or len(instead) != 1 or not isinstance(instead[0], dict) \
                        or instead[0].get("op") != "draw" or set(instead[0]) != {"op", "effect_id", "player", "count"} \
                        or not isinstance(instead[0].get("player"), str) or not isinstance(instead[0].get("count"), int) \
                        or instead[0]["count"] < 1:
                    errors.append(f"effects[{index}].unless.instead is one draw {{op, effect_id, player, count}}")
            if "linked_each" in effect:
                producer = next((e for e in effects[:index] if isinstance(e, dict) and e.get("effect_id") == effect["linked_each"]), None)
                if effect.get("op") not in LINKED_EACH_OPS or (producer or {}).get("op") not in LINKED_EACH_PRODUCERS:
                    errors.append(f"effects[{index}].linked_each applies {sorted(LINKED_EACH_OPS)} to each object an earlier "
                                  f"{sorted(LINKED_EACH_PRODUCERS)} acted on")
                if {"target", "targets", "object_id", "affected"} & set(effect):
                    errors.append(f"effects[{index}].linked_each names its objects; no target, targets, object_id or affected")
            if effect.get("op") == "return_to_hand" and "self" in effect:
                # 2026-10-12 (package 11): "return this from your trash to your hand" - the program's own source
                if not isinstance(effect["self"], dict) or set(effect["self"]) != {"from"} \
                        or effect["self"]["from"] not in RETURN_SELF_ZONES:
                    errors.append(f"effects[{index}].self must be {{from}} with from in {sorted(RETURN_SELF_ZONES)}")
                if {"target", "targets", "object_id", "affected", "subject_ref"} & set(effect):
                    errors.append(f"effects[{index}].self names the object; no target, targets, object_id or affected")
            if "subject_ref" in effect:
                ref = effect["subject_ref"]
                earlier_ids = {e.get("effect_id") for e in effects[:index] if isinstance(e, dict)}
                if effect.get("op") not in LINKED_SUBJECT_OPS:
                    errors.append(f"effects[{index}].subject_ref is read by {sorted(LINKED_SUBJECT_OPS)} only")
                if not isinstance(ref, dict) or set(ref) != {"kind", "effect_id"} or ref.get("kind") != "linked_object" \
                        or ref.get("effect_id") not in earlier_ids:
                    errors.append(f"effects[{index}].subject_ref is {{kind linked_object, effect_id}} naming an earlier "
                                  f"instruction of this program")
                if {"target", "targets", "object_id", "affected"} & set(effect):
                    errors.append(f"effects[{index}].subject_ref names the object; no target, targets, object_id or affected")
            if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                    and effect["destination"].get("kind") == LINKED_TARGETED_BATTLEFIELD_DESTINATION:
                # 2026-10-08 package 10 (Stormbringer): "move your unit there" - the Battlefield an earlier instruction of
                # this program targeted (its area's targeted_battlefield)
                linked = effect["destination"]
                earlier = {e.get("effect_id"): e for e in effects[:index] if isinstance(e, dict)}
                producer = earlier.get(linked.get("effect_id"))
                if set(linked) != {"kind", "effect_id"} or producer is None \
                        or (producer.get("target") or {}).get("kind") != "battlefield":
                    errors.append(f"effects[{index}].move_board_object destination {LINKED_TARGETED_BATTLEFIELD_DESTINATION} "
                                  f"is {{kind, effect_id}} naming an earlier instruction that targets a battlefield")
            if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                    and effect["destination"].get("kind") == LINKED_BATTLEFIELD_DESTINATION:
                # 2026-10-08 package 10 (Zenith Blade): "to that enemy unit's battlefield" - the Battlefield where the
                # object an EARLIER instruction of this program acted on is, read as this Move executes
                linked = effect["destination"]
                earlier = {e.get("effect_id") for e in effects[:index] if isinstance(e, dict)}
                if set(linked) != {"kind", "effect_id"} or linked.get("effect_id") not in earlier:
                    errors.append(f"effects[{index}].move_board_object destination {LINKED_BATTLEFIELD_DESTINATION} is "
                                  f"{{kind, effect_id}} naming an earlier instruction of this program")
            if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                    and (effect["destination"].get("restriction") == "location_of_target") != (
                        isinstance(effect["destination"].get("target_ref"), str) and effect["destination"]["target_ref"] in {
                            (e.get("target") or {}).get("decision_ref") for e in effects if isinstance(e, dict)}):
                errors.append(f"effects[{index}].move_board_object destination location_of_target names, in target_ref, "
                              f"the decision of a target of this program - and only that restriction carries one")
            if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                    and "bound_location" in effect["destination"]:
                errors.append(f"effects[{index}].move_board_object destination bound_location is bound by the engine, "
                              f"never by a program")
            if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                    and "here_battlefield" in effect["destination"]:
                errors.append(f"effects[{index}].move_board_object destination here_battlefield is bound by the engine, "
                              f"never by a program")
            if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                    and "restriction" in effect["destination"] and (
                        effect["destination"]["restriction"] not in MOVE_DESTINATION_RESTRICTIONS
                        or "decision_ref" not in effect["destination"]):
                errors.append(f"effects[{index}].move_board_object destination restriction must be one of "
                              f"{sorted(MOVE_DESTINATION_RESTRICTIONS)}, on a chosen destination (decision_ref)")
            if effect.get("op") == "play_token":
                if "token_id" in effect and (not isinstance(effect["token_id"], str) or not effect["token_id"]):
                    errors.append(f"effects[{index}].play_token.token_id must be a non-empty catalogue id (ADR-0012 §6)")
                destination = effect.get("destination")
                # 2026-09-24: a card program cannot name its token's id - it resolves once per
                # copy and per replay. object_id_ref {kind: fresh} has the engine mint one at
                # execution (Core 124: every token is a new object), deterministically.
                fresh = effect.get("object_id_ref") == {"kind": "fresh"}
                if effect.get("object_id_ref") is not None and not fresh:
                    errors.append(f"effects[{index}].play_token.object_id_ref must be {{kind: fresh}}")
                if fresh and effect.get("object_id") is not None:
                    errors.append(f"effects[{index}].play_token carries both object_id and object_id_ref")
                if not fresh and (not isinstance(effect.get("object_id"), str) or not effect.get("object_id")):
                    errors.append(f"effects[{index}].play_token requires object_id")
                if isinstance(destination, dict) and "location_ref" in destination and (
                        destination.get("kind") != "battlefield" or "battlefield" in destination
                        or not is_location_ref(destination["location_ref"])):
                    errors.append(f"effects[{index}].play_token destination location_ref must be a battlefield "
                                  f"with a location_ref and no literal battlefield")
                if not isinstance(effect.get("owner"), str) or not effect.get("owner"):
                    errors.append(f"effects[{index}].play_token requires owner")
                if not isinstance(effect.get("controller"), str) or effect.get("token_kind") not in {"unit", "gear"}:
                    errors.append(f"effects[{index}].play_token requires controller and unit/gear token_kind")
                if not isinstance(effect.get("base_might"), int) or effect.get("base_might", -1) < 0:
                    errors.append(f"effects[{index}].play_token requires non-negative base_might")
                tags = effect.get("tags")
                if tags is not None and (not isinstance(tags, list) or not tags or len(tags) != len(set(tags))
                                         or any(not isinstance(t, str) or not t for t in tags)):
                    errors.append(f"effects[{index}].play_token tags must be a non-empty unique array of tag names")
                chosen_place = isinstance(destination, dict) and set(destination) == {"decision_ref"} \
                    and isinstance(destination["decision_ref"], str) and bool(destination["decision_ref"])
                if chosen_place:
                    pass   # the controller's location_selection at execution (token_play_locations)
                elif not isinstance(destination, dict) or destination.get("kind") not in {"base", "battlefield"}:
                    errors.append(f"effects[{index}].play_token requires a base or battlefield destination, "
                                  f"or {{decision_ref}} for its controller's choice")
                elif effect.get("token_kind") == "gear" and destination.get("kind") != "base":
                    errors.append(f"effects[{index}].non-Unit Gear token must enter a Base")
                elif destination.get("kind") == "base" and destination.get("player") != effect.get("controller"):
                    errors.append(f"effects[{index}].Base destination must match token controller")
            target = effect.get("target")
            if target is not None:
                errors.extend(f"effects[{index}].target {e}" for e in _selector_errors(target))
            affected = effect.get("affected")
            if affected is not None:
                criteria = affected.get("criteria") if isinstance(affected, dict) else None
                has_location = isinstance(criteria, dict) and "location" in criteria
                has_location_ref = isinstance(criteria, dict) and "location_ref" in criteria
                if (not isinstance(affected, dict) or set(affected) != {"criteria"} or not isinstance(criteria, dict)
                        or set(criteria) - {"kind", "controller_relation", "location", "location_ref", *AFFECTED_NARROWING_FIELDS,
                                            "exclude_targets_of"}
                        or ("exclude_targets_of" in criteria and not (
                            isinstance(criteria["exclude_targets_of"], str) and any(
                                isinstance(e, dict) and e.get("effect_id") == criteria["exclude_targets_of"] and e.get("target")
                                for e in effects[:index])))
                        or has_location == has_location_ref):
                    errors.append(f"effects[{index}].affected must be {{criteria: {{location, kind?, controller_relation?}}}} "
                                  "or {{criteria: {{location_ref, kind?, controller_relation?}}}}, never both, never neither")
                elif any(field in criteria and not isinstance(criteria[field], bool) for field in SELECTOR_STATE_FIELDS) \
                        or criteria.get("exclude_source_identity", SOURCE_IDENTITY_SENTINEL) != SOURCE_IDENTITY_SENTINEL:
                    # 2026-09-27 package 6: "all damaged enemy units here", "all other friendly units there" -
                    # a state is true or false; "other" names the program's own source, by the sentinel only
                    errors.append(f"effects[{index}].affected.criteria: exhausted / damaged are true or false, and "
                                  f"exclude_source_identity is {SOURCE_IDENTITY_SENTINEL!r}")
                elif has_location_ref:
                    ref = criteria["location_ref"]
                    if not is_location_ref(ref):
                        errors.append(f"effects[{index}].affected.criteria.location_ref must be {{kind}} with kind in {list(LOCATION_REF_KINDS)}")
                    if target is not None:
                        errors.append(f"effects[{index}].affected over location_ref targets nothing (Core 355.10.b, 355.10.d)")
                    if "kind" in criteria and criteria["kind"] not in {"unit", "gear"}:
                        errors.append(f"effects[{index}].affected.criteria.kind is invalid")
                    if "controller_relation" in criteria and criteria["controller_relation"] not in {"friendly", "enemy"}:
                        errors.append(f"effects[{index}].affected.criteria.controller_relation is invalid")
                else:
                    if criteria["location"] not in {"target_battlefield", "any_battlefield", "active_combat", "board"}:
                        errors.append(f"effects[{index}].affected.criteria.location is invalid")
                    if criteria["location"] == "board" and target is not None:
                        errors.append(f"effects[{index}].affected over the whole board targets nothing (Core 355.10.b)")
                    if criteria["location"] == "active_combat" and target is not None:
                        errors.append(f"effects[{index}].affected over active_combat targets nothing (Core 355.10.d, 740.2.c)")
                    if "kind" in criteria and criteria["kind"] not in {"unit", "gear", "rune"}:
                        errors.append(f"effects[{index}].affected.criteria.kind is invalid")
                    # 2026-09-27 ("ready your runes", Ekko - Recurrent): a player's Runes are on the board
                    # in their Base (Core 430.1), so a set of Runes is read over the whole board, and only
                    # readied or exhausted
                    if criteria.get("kind") == "rune" and (criteria["location"] != "board" or effect.get("op") not in {"ready", "exhaust"}):
                        errors.append(f"effects[{index}].affected over runes reads the whole board and only readies or exhausts them")
                    # "own": controlled by the program's controller ("your runes") - not "friendly", which
                    # also takes a teammate's (same_side); a teammate's Runes are not "yours"
                    if "controller_relation" in criteria and criteria["controller_relation"] not in {"friendly", "enemy", "own"}:
                        errors.append(f"effects[{index}].affected.criteria.controller_relation is invalid")
                    if criteria["location"] == "target_battlefield" and (not isinstance(target, dict) or target.get("kind") != "battlefield"):
                        errors.append(f"effects[{index}].affected over target_battlefield needs a battlefield target")
                    if criteria["location"] == "any_battlefield" and target is not None:
                        errors.append(f"effects[{index}].affected over any_battlefield targets nothing (Core 355.10.b)")
                if effect.get("op") not in MULTI_TARGET_OPS:
                    errors.append(f"effects[{index}].affected is not supported for {effect.get('op')!r}")
                if effect.get("targets") is not None or effect.get("object_id") is not None:
                    errors.append(f"effects[{index}].affected excludes targets and object_id")
            targets = effect.get("targets")
            if targets is not None:
                if target is not None:
                    errors.append(f"effects[{index}] may carry target or targets, not both")
                if effect.get("op") not in MULTI_TARGET_OPS:
                    errors.append(f"effects[{index}].targets is not supported for {effect.get('op')!r}")
                split = effect.get("division_ref") is not None
                if split:
                    # 2026-09-27 package 5, Core 355.14: "deal N damage split among any number of ...".
                    # The targets are one decision made at finalization; how many may be chosen is
                    # capped by the damage itself (355.14.c), so the split carries no max of its own
                    # (the amount is the cap); the division is a resolution decision (355.14.e).
                    if effect.get("op") != "deal_damage" or not isinstance(effect["division_ref"], str) or not effect["division_ref"]:
                        errors.append(f"effects[{index}].division_ref splits a deal_damage's amount; it must be a non-empty decision id")
                    if not isinstance(effect.get("amount"), int) or isinstance(effect.get("amount"), bool) or effect.get("amount", 0) < 1 \
                            or effect.get("amount_ref") is not None:
                        errors.append(f"effects[{index}] a split deal needs a fixed positive amount (Core 355.14.c)")
                    if not isinstance(targets, dict) or "decision_ref" not in targets or "selectors" in targets or "max" in targets:
                        errors.append(f"effects[{index}].targets of a split deal is one decision_ref with min and no max: "
                                      f"the amount caps the targets (Core 355.14.b, 355.14.c)")
                    elif isinstance(effect.get("amount"), int) and isinstance(targets.get("min"), int) and targets["min"] > effect["amount"]:
                        errors.append(f"effects[{index}].targets.min exceeds the damage to split (Core 355.14.c)")
                    targets = {**targets, "max": effect.get("amount")} if isinstance(targets, dict) else targets
                any_number = (isinstance(targets, dict) and "max" not in targets
                              and isinstance(targets.get("group"), dict) and "total_might_at_most" in targets["group"])
                if any_number:
                    # package 10 (Fox-Fire, "any number of units ... with total Might 4 or less"): no count of its own -
                    # the group's total bounds it (Core 355.13, 355.11)
                    targets = {**targets, "max": None}
                if not isinstance(targets, dict) or set(targets) - {"selectors", "decision_ref", "min", "max", "restrictions", "group", "subset_ref"} or not {"min", "max"} <= set(targets):
                    errors.append(f"effects[{index}].targets must carry min, max, and selectors or decision_ref")
                    targets = None
                if targets is not None and ("group" in targets or "subset_ref" in targets):
                    # package 10 (Core 355.11): a group requirement over chosen targets, and the subset kept as it resolves
                    group = targets.get("group")
                    if not isinstance(group, dict) or not group or set(group) - TARGET_GROUP_FIELDS \
                            or ("same_battlefield" in group and group["same_battlefield"] is not True) \
                            or ("total_might_at_most" in group and (not isinstance(group["total_might_at_most"], int)
                                                                    or isinstance(group["total_might_at_most"], bool)
                                                                    or group["total_might_at_most"] < 0)) \
                            or ("one_per_relation" in group and (not isinstance(group["one_per_relation"], list)
                                                                 or not group["one_per_relation"]
                                                                 or any(r not in ("friendly", "enemy") for r in group["one_per_relation"])
                                                                 or targets.get("min") != len(group["one_per_relation"])
                                                                 or targets.get("max") != len(group["one_per_relation"]))):
                        errors.append(f"effects[{index}].targets.group is {{same_battlefield: true?, total_might_at_most: N?, "
                                      f"one_per_relation: [friendly|enemy, ...]? (as many as min and max)}} (Core 355.11)")
                    if not isinstance(targets.get("subset_ref"), str) or not targets.get("subset_ref") or "decision_ref" not in targets:
                        errors.append(f"effects[{index}].targets with a group needs a decision_ref and a subset_ref: the subset "
                                      f"its controller keeps if the group stops meeting it (Core 355.11.b)")
                    if effect.get("division_ref") is not None:
                        errors.append(f"effects[{index}] a split deal's targets carry no group requirement")
                if targets is not None:
                    if not isinstance(targets["min"], int) or targets["min"] < 0 or (
                            targets["max"] is not None or not any_number) and (
                            not isinstance(targets["max"], int) or targets["max"] < max(1, targets["min"])):
                        errors.append(f"effects[{index}].targets.min/max are invalid")
                    if any_number and "selectors" in targets:
                        errors.append(f"effects[{index}].targets: 'any number' is chosen (a decision_ref), not listed")
                    if ("selectors" in targets) == ("decision_ref" in targets):
                        errors.append(f"effects[{index}].targets needs exactly one of selectors or decision_ref")
                    for j, sel in enumerate(targets.get("selectors", []) or []):
                        errors.extend(f"effects[{index}].targets.selectors[{j}] {e}" for e in _selector_errors(sel))
                    if "selectors" in targets and isinstance(targets["max"], int) and len(targets["selectors"]) > targets["max"]:
                        errors.append(f"effects[{index}].targets has more selectors than max")
                    if "decision_ref" in targets and (not isinstance(targets["decision_ref"], str) or not targets["decision_ref"]):
                        errors.append(f"effects[{index}].targets.decision_ref must be non-empty")
            if effect.get("division_ref") is not None and effect.get("targets") is None:
                errors.append(f"effects[{index}].division_ref splits the damage among chosen targets; it needs targets")
            seen.add(effect_id)
    return errors


# 2026-09-27 package 6: `buff` joins - "buff up to two other friendly units" (a bounded set of
# Targets, Core 355.13) and "buff all friendly units" (a set found by criteria, Core 355.10.b) each
# buff every object one at a time, exactly as a single "Buff a unit." does (Core 426.1.b-c, 702.3)
MULTI_TARGET_OPS = {"deal_damage", "heal_damage", "ready", "exhaust", "move_board_object", "kill", "modify_might", "recycle_one", "return_to_hand", "recall", "grant_replacement", "heal_all_damage", "grant_keyword", "buff",
                    # 2026-10-08 package 10 (Facebreaker: "Stun a friendly unit and an enemy unit at the same battlefield")
                    "stun"}
# 2026-10-08 package 10 (Facebreaker; Fox-Fire's shape, GPT 2026-10-08 ruling 5): a requirement the chosen targets meet as
# a GROUP (Core 355.11) - all at one Battlefield; their Mights together at most N; one of each controller relation named.
# Met by the whole group as it is chosen (355.11.a); as it resolves, a group that no longer meets it is cut to a subset of
# the original targets, chosen by the controller, that does (355.11.b) - nothing new is added
TARGET_GROUP_FIELDS = {"same_battlefield", "total_might_at_most", "one_per_relation"}


def target_group_holds(state: dict[str, Any], object_ids: list[str], group: dict[str, Any], controller: str | None,
                       *, subset: bool = False) -> tuple[bool, str]:
    """(True, "ok") or (False, why) - whether these objects meet the group requirement now. `subset`: a part of the
    original group (355.11.b), so one_per_relation asks at most one of each relation rather than exactly one."""
    if group.get("same_battlefield"):
        places = [find_location(state, o) for o in object_ids]
        if any(p is None or p[0] != "battlefield" for p in places) or len({p[1] for p in places}) > 1:
            return False, "target_group_not_at_one_battlefield"
    limit = group.get("total_might_at_most")
    if limit is not None and sum(effective_might(state, o) for o in object_ids) > limit:
        return False, "target_group_might_over_limit"
    relations = group.get("one_per_relation")
    if relations is not None:
        sides = ["friendly" if same_side(state, controller, (state["objects"].get(o) or {}).get("controller")) else "enemy"
                 for o in object_ids]
        if any(sides.count(r) > relations.count(r) for r in set(sides)) or (not subset and sorted(sides) != sorted(relations)):
            return False, "target_group_relations_not_met"
    return True, "ok"


def target_group_subset(state: dict[str, Any], effect: dict[str, Any], valid_sels: list[dict[str, Any]],
                        decisions: dict[str, Any] | None, controller: str | None) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Core 355.11.b: the targets still legal no longer meet the group requirement - the controller chooses, as it resolves,
    a subset of them that does (a card_selection named by targets.subset_ref). (kept ids, None) or (None, a refusal)."""
    import engine_decisions as ed
    spec = effect["targets"]
    ref, legal = spec["subset_ref"], [sel["object_id"] for sel in valid_sels]
    ledger_note("choice", ref)
    entry = next((e for e in ed.entries(decisions, kind="card_selection") if e.get("decision_id") == ref), None)
    if entry is None:
        return None, {"valid": True, "committed": False, "target_group_subset_required": True,
                      "reason_code": "target_group_subset_required",
                      "reason": f"the targets {legal} no longer meet their group requirement; which of them are kept is "
                                f"chosen as it resolves (Core 355.11.b)",
                      "decision_ids": [ref], "decision_controller": controller, "subset_candidates": legal}
    if entry.get("controller") != controller or entry.get("stage") != "resolution":
        return None, {"valid": False, "committed": False,
                      "errors": [f"target group subset {ref!r} is the controller's, chosen as it resolves (Core 355.11.b)"]}
    value = list(entry["value"])
    problems = []
    if set(value) - set(legal):
        problems.append(f"it names {sorted(set(value) - set(legal))}, which are not original targets still legal (355.11.b)")
    identities = entry.get("selection_identities") or {}
    if any(identities.get(o) != object_identity(state, o) for o in value if o in legal):
        problems.append("it was made for other objects than these are now (Core 124)")
    if not problems:
        ok, why = target_group_holds(state, value, spec["group"], controller, subset=True)
        if not ok:
            problems.append(f"the subset does not meet the group requirement either ({why})")
    if not problems:
        # Core 2026-10-09 355.11.b.1 (in effect 10-16): the subset kept has as many of the legal targets as it can - no
        # original target still legal is left out when keeping it too would still meet the requirement
        could_add = [o for o in legal if o not in value
                     and target_group_holds(state, value + [o], spec["group"], controller, subset=True)[0]]
        if could_add:
            problems.append(f"the subset leaves out {could_add}, which it could keep and still meet the requirement "
                            f"(Core 355.11.b.1)")
    if problems:
        return None, {"valid": False, "committed": False, "errors": [f"target group subset {ref!r}: {p}" for p in problems]}
    return value, None
# 2026-09-27 package 6: `exhausted` / `damaged` - a STATE the chosen object must be in, read off the
# board when it is chosen and again when it is used: "an exhausted friendly unit" (exhausted: true,
# Core 414.2), "a ready unit" (exhausted: false, Core 415.2), "a damaged unit" (damaged: true -
# damage marked on it, Core 142). Only objects on the board have these states.
SELECTOR_STATE_FIELDS = ("exhausted", "damaged")
# ... and the same states narrow a set found by criteria ("kill all damaged enemy units here"), as
# does "other" - the program's own source left out ("buff all other friendly units there")
AFFECTED_NARROWING_FIELDS = (*SELECTOR_STATE_FIELDS, "exclude_source_identity")
SELECTOR_FIELDS = {"object_id", "bound_object_id", "bound_identity", "chosen_zone_class", "kind", "location", "controller_relation", "zone_owner_relation", "targeted", "decision_ref", "max_might", "exclude_source_identity", "max_cost", "selection_ref", "location_ref", "any_of", *SELECTOR_STATE_FIELDS,
                   # Core 103.2.a.3: a Champion Unit named as its controller's Chosen Champion
                   "chosen_champion",
                   # package 12 (Core 2026-10-09 811.1.d.2-811.1.d.3.a, 359.3.e.2.a): a choice of a card played from
                   # facedown, or of the on-play trigger of a permanent that came from facedown, is made at that battlefield and
                   # checked there again as it resolves; the play effect whose source left the board reads no battlefield.
                   # Only the engine sets these (restrict_to_facedown_battlefield), never a program's author
                   "at_battlefield", "facedown_source_gone",
                   # 2026-10-08 package 10 (Guerilla Warfare): "a card with [Hidden]" - the card has the keyword (Core 811)
                   "with_hidden",
                   # GPT 2026-10-02: a kind-less board target that also admits a Legend in its Legend Zone
                   # ("Ready something else that's exhausted" - Core 107.4, 355.9.a.4, 415.1)
                   "include_legend_zone",
                   # 2026-10-06 package 9 (Kai'Sa - Evolutionary): "with Energy cost less than your points"
                   "energy_cost_below_points",
                   # 2026-10-08 package 10 (Teemo - Swift Scout): "a Teemo unit you own" - a tag the object carries
                   # (Core 133.8) and the player who owns it (as against controls it)
                   "with_tag", "owner_relation",
                   # 2026-10-12 package 11 (Dragon's Rage: "another enemy unit at its destination"): not the object
                   # the trigger's event was about, by the identity the event recorded (resolution_bridge)
                   "exclude_trigger_event_object"}
# 2026-09-27 (Fading Memories, "a unit at a battlefield or a gear"): one chosen object that fits ONE of
# the alternatives; each names a kind and may narrow the location and the controller relation
ANY_OF_FIELDS = {"kind", "location", "controller_relation",
                 # 2026-10-08 package 10 (Teemo - Swift Scout, "from your Champion Zone or the board"): an alternative
                 # in the controller's own Champion Zone names its own zone class (non_board); the others stay on the board
                 "chosen_zone_class", "zone_owner_relation"}
# Round H: "another unit" is *this* unit excluded, by identity. The clause
# writes the sentinel; the engine resolves it from the program's own
# source_object when the selection is made, so the exclusion can never be a
# name match and can never quietly pick a substitute.
SOURCE_IDENTITY_SENTINEL = "$source_identity"

# selector-group `self` (Codex 2026-09-10). "Give me +3 Might this turn." names
# the resolving source object and makes no decision at all.
#
# It is a TYPED reference, `{"object_ref": "program_source"}`, and deliberately
# not a magic string. A string sentinel is forgeable by anything that can write
# a string: a decision artifact, a mapping's expected IR, a hand-edited program.
# The engine is the only thing that may resolve this shape, and the decision
# validator refuses it outright, so an artifact cannot inject one.
OBJECT_REF_KINDS = ("program_source", "trigger_event_object")
# 2026-09-28: "When a friendly unit attacks alone, give IT +1 Might this turn." - the object the
# event that met a watched trigger's condition is about, as it was then: the identity it had once
# that event was processed (Core 383.2.c; 359.3.f.3: information referenced from the trigger
# condition is checked when the condition is fulfilled). The chain item records it
# (watchers.trigger_event_of) and resolution hands it to the program as `trigger_event`
# (resolution_bridge.bind_trigger_event); it is never chosen, so it is not a target (Core 355.7 -
# nothing is selected). As the instruction executes it must still be that object on the board: one
# that left the board or became a new object (Core 124) cannot be followed, and the instruction is
# ignored (359.3.e.6, 359.3.f.2.a). Its own op adoption, separate from program_source's: each op
# proved by its own fixture (engine check_trigger_referent.py).
TRIGGER_EVENT_OBJECT = "trigger_event_object"
# 2026-10-08 (package 10, Mistfall: "When you buff a friendly unit, ... ready it"): `ready` adopted, its fixture in engine
# check_ready_buff_watch.py (T1-T2)
TRIGGER_EVENT_OBJECT_OPS = {"modify_might", "ready",
                            # 2026-10-08 package 10 (Noxian Guillotine, Imperial Decree): "kill it" - the damaged unit
                            "kill",
                            # 2026-10-12 package 11 (Dragon's Rage: "They deal damage ... to each other"): the moved
                            # unit in ONE of the pair's slots; its fixture is engine check_reflexive_move.py
                            "mutual_damage_current_might"}
OBJECT_REF_NO_TRIGGER_EVENT = "object_ref_no_trigger_event"
OBJECT_REF_REFERENT_ABSENT = "object_ref_referent_absent"
OBJECT_REF_REFERENT_IDENTITY_CHANGED = "object_ref_referent_identity_changed"
OBJECT_REF_REFERENT_LEFT_PLAY = "object_ref_referent_left_play"
# Which ops may carry it. Codex's boundary: adoption is proved per op with an
# executor audit AND a real resolution fixture. `ready` working says nothing
# about `kill`, so an op is added here only once its fixture exists.
# 2026-09-27: return_to_hand ("return me to my owner's hand", Vayne, Hunter) - its fixtures are
# check_object_ref_self.py (the source leaves the board for its owner's hand) and
# check_trigger_cost.py (a Conquer-shaped trigger whose base cost is [1], resolved for real).
OBJECT_REF_OPS = {"ready", "buff", "modify_might", "banish", "return_to_hand", "kill",
                  # 2026-10-12 package 11 (Tideturner: "Move me to its location ..."): its fixture is engine
                  # check_swap_locations.py (S1, S4)
                  "move_board_object"}
# A Spell is not a permanent; it is not on the board to be acted on when its own
# program resolves. The default is deliberately narrow (Core 355.4.a: the Board's
# Locations are the Battlefields and the Bases).
OBJECT_REF_PERMANENT_KINDS = {"unit", "gear", "rune"}
# 2026-10-08 package 10 (Sett - The Boss: "When you conquer, ready me."): a Legend in its controller's Legend Zone is
# exhausted and readied there (Core 107.4, 415.1; the ready op already acts on it), so its own "ready me" may name it - for
# these ops only, and only there
OBJECT_REF_LEGEND_OPS = {"ready"}
# 2026-10-09 package 10 (Carnivorous Snapvine: "We deal damage equal to our Mights to each other."): an op whose objects
# are a list of Unit slots may name the source in ONE slot, `{"object_id": {"object_ref": "program_source"}, ...}`. The
# source is not a target: it is resolved as the instruction executes, and a source that is gone makes the pair ignored
# as source-unavailable, never an illegal target
OBJECT_REF_UNIT_SLOT_OPS = {"mutual_damage_current_might"}

OBJECT_REF_ABSENT = "object_ref_source_absent"
OBJECT_REF_IDENTITY_CHANGED = "object_ref_source_identity_changed"
OBJECT_REF_LEFT_PLAY = "object_ref_source_left_play"
OBJECT_REF_NOT_SELF = "object_ref_not_self_referential"
# A separate code from NOT_SELF on purpose: "this op has no reviewed
# adoption" and "this clause is not talking about itself" are different
# failures, and one refusal code covering both would hide which happened.
OBJECT_REF_OP_NOT_ADOPTED = "object_ref_op_not_adopted"

# GPT 2026-09-23: the relational locator "here" (Core 359.3.f.1: read from the
# ability's own SOURCE, alongside "my"/"its") is deliberately NOT a value of the
# existing literal `location` vocabulary above - that vocabulary names classes the
# engine independently enforces against an EARLIER target choice ("at a
# battlefield", 355.10.d) or a fixed context ("active_combat"); "here" names
# neither. It is a first, narrow cut: ONLY "the resolving program's source's
# current Battlefield," checked at INSTRUCTION EXECUTION (Core 359.3.f.2's own
# worked example - Yasuo, Remorseful moved back to Base after his attack trigger
# is scheduled, and "here" mistargets because it is no longer a Battlefield, not
# because the old one is remembered and gone). This is NOT the trigger CONDITION
# kind of relational reference (Core 359.3.f.3, Lillia Fae Fawn's "there" - a
# location captured once, when the trigger's condition is fulfilled, immune to
# a later move): that is a separate referent this capability does not resolve,
# and no production may be widened to use this one for a 359.3.f.3 shape.
LOCATION_REF_KINDS = ("program_source_current_battlefield",
                      # 2026-10-12 (package 11, Kog'Maw - Caustic): a death trigger's "my battlefield" - where its
                      # source was as the trigger was noted (Core 808.1.d.3), not where anything is now
                      "program_source_noted_battlefield",
                      # 2026-10-12 (package 11, Dragon's Rage: "Choose another enemy unit at its destination"): where
                      # the object a reflexive trigger's instruction moved was moved to - a Battlefield or a Base - as
                      # the trigger's chain item recorded it (resolution_bridge); fixed then, not read again
                      "trigger_event_destination")

LOCATION_REF_ABSENT = "location_ref_source_absent"
LOCATION_REF_IDENTITY_CHANGED = "location_ref_source_identity_changed"
# Deliberately its own code, not OBJECT_REF_LEFT_PLAY's "board" (battlefield OR
# base, Core 355.4.a): "here" (Core 053.3) names a Battlefield specifically. A
# source sitting in Base is still on the board, but it is not "at" anything -
# 359.3.f.2's own example is exactly a source moved to Base, mistargeting.
LOCATION_REF_NOT_AT_BATTLEFIELD = "location_ref_source_not_at_battlefield"
# package 11: a reflexive trigger whose instruction moved nothing has no destination - no object is "at" it, so a target
# that must be there has no legal option (Core 402.4), unlike an unbindable "here", which is refused by name
LOCATION_REF_NO_DESTINATION = "location_ref_no_destination"

# "deal damage equal to my Might" (Yasuo, Remorseful): a typed reference to a number the
# program's own source carries, read on EXECUTION of the instruction - Core 359.3.f.2's
# own example: Stupefied in reaction, Yasuo's attack trigger deals damage equal to his
# current Might. One kind; identity mandatory, exactly as location_ref.
#
# 2026-09-27, two LINKED kinds (Core 359.3.e.14: "its" in a later instruction references the
# object an earlier instruction of the same card acted on). Each names that earlier
# instruction by effect_id:
#   linked_object_current_might  "It deals damage equal to its Might" (Last Breath): the
#                                object's current Might, read as THIS instruction executes
#                                (359.3.f.2); off the board, or a new object, it is null
#                                (359.3.e.12) and nothing is dealt
#   linked_card_printed_energy   "Deal its Energy cost as damage" (Get Excited!): the printed
#                                Energy cost of the card the earlier instruction discarded
#                                (Core 206: printed or copied cost, whatever was paid)
# If the earlier instruction was ignored, this one is too (359.3.e.14.a).
# 2026-10-08 package 10 (Bullet Time - a variable Power payment whose total sets the damage dealt to each enemy unit
# at a targeted Battlefield; GPT 2026-10-08 ruling 8): the amount an earlier pay_any_amount of this program paid. Paid 0, the Deal
# deals nothing (Core 417.1.e); not paid at all (declined, a receipt of its own), the Deal is ignored with it (359.3.e.14.a)
LINKED_PAID_AMOUNT = "linked_paid_amount"
AMOUNT_REF_KINDS = ("program_source_current_might", "linked_object_current_might", "linked_card_printed_energy",
                    LINKED_PAID_AMOUNT,
                    # 2026-10-08 package 10 (Last Stand: "Double a friendly unit's Might this turn."): the instruction's
                    # OWN object's current Might, read as it executes (Core 477.3.c, GPT 2026-10-08 ruling 11) - a fixed
                    # this-turn +X, never a running x2; a Might below 0 adds nothing
                    "object_current_might")
# 2026-10-08 package 10 (Zenith Blade: "Stun an enemy unit at a battlefield. You may move a friendly unit to that enemy
# unit's battlefield."): a Move's destination named by the object an earlier instruction acted on (Core 359.3.e.14) -
# the Battlefield it is at as THIS Move executes (359.3.f.2); off the board, a new object, or in a Base, the destination
# reads null (359.3.e.12) and the Move is not carried out; the earlier instruction ignored, this one is too (359.3.e.14.a)
LINKED_BATTLEFIELD_DESTINATION = "linked_object_battlefield"
# 2026-10-08 package 10 (Stormbringer: "... to all enemy units at a battlefield, then move your unit there."): "there" is
# the Battlefield an earlier instruction of this program TARGETED (Core 359.3.e.14) - read off that instruction's own
# event; the earlier instruction ignored (its target illegal), this Move is too (359.3.e.14.a)
LINKED_TARGETED_BATTLEFIELD_DESTINATION = "linked_targeted_battlefield"
# 2026-10-08 package 10 (Stormbringer: "Choose a friendly unit in your base. ... then move your unit there."): the Move's
# object is the one an earlier instruction of this program chose or acted on - named by that instruction (subject_ref
# {kind linked_object, effect_id}), never chosen again (Core 359.3.e.14); gone from the board or a new object, the Move
# is not carried out (359.3.e.12); the earlier instruction ignored, this one is too (359.3.e.14.a)
LINKED_SUBJECT_OPS = {"move_board_object"}
# 2026-10-08 package 10 (Noxian Guillotine): a delayed trigger bound to the creating instruction's own target
DELAYED_OWN_TARGET = "$own_target"
# 2026-10-08 package 10 (Overt Operation: "For each friendly unit, you may spend its buff to ready it."): an instruction
# applied to EACH object an earlier instruction of this program acted on - the units whose buff was spent (Core
# 359.3.e.14); none spent, nothing readied; the earlier instruction ignored, this one is too (359.3.e.14.a)
LINKED_EACH_OPS = {"ready"}
LINKED_EACH_PRODUCERS = {"spend_buffs"}
# 2026-10-08 package 10 (Shakedown: "Deal 6 to it unless its controller has you draw 2."; GPT 2026-10-08 ruling 7): a
# targeted instruction its TARGET's controller may replace, as it resolves, by the instruction(s) the card names instead
# (unless {decision_ref, instead}). The option is "instruction" or "instead"; chosen "instead", the named instructions run
# (the program's controller draws; a short deck Draws / Burns Out as usual) and the instruction itself does not happen.
# The target illegal, the instruction is ignored whole and nobody chooses. Only a Draw by a named player is an "instead".
UNLESS_OPTIONS = ["instruction", "instead"]
UNLESS_OPS = {"deal_damage"}
LINKED_AMOUNT_REF_KINDS = {"linked_object_current_might", "linked_card_printed_energy", LINKED_PAID_AMOUNT}
AMOUNT_REF_ABSENT = "amount_ref_source_absent"
AMOUNT_REF_IDENTITY_CHANGED = "amount_ref_source_identity_changed"
# "Its controller draws 2." (Hidden Blade) / "Its owner channels 1 rune exhausted." (Retreat):
# a player named by an object an earlier instruction of this program acted on (Core 359.3.e.14,
# 355.10.d - that player is not a target). Read from the state as it stood just BEFORE that
# instruction executed - the killed unit's controller is the one it had when it was killed.
OBJECT_PLAYER_RELATIONS = ("controller", "owner")
# The outcomes that mean an instruction was ignored - it did not execute - rather than executed.
# A later instruction linked to it is ignored too (Core 359.3.e.14.a), whether it reads the earlier
# one's object ("its controller": linked_objects) or runs only unless the earlier one was ignored
# (depends_on with dependency_mode unless_ignored): ONE set for both. A declined optional
# instruction (355.12) did not execute; an instruction whose own source is gone was ignored
# (359.3.e.6). A REPLACED instruction still counts as executed for the link (359.3.e.14.b).
IGNORED_OUTCOMES = frozenset({"ignored_illegal_target", "skipped_illegal_target", "skipped_linked_dependency",
                              "ignored_subject_changed", "skipped_after_terminal",
                              # package 9: the branch its controller did not choose (only_if_chose)
                              "skipped_option_not_chosen",
                              "declined", SOURCE_UNAVAILABLE_OUTCOME})
LINKED_IGNORED_OUTCOMES = IGNORED_OUTCOMES
# Core 2026-10-09 (in effect 2026-10-16), 359.3.e.6 and 359.3.e.14.a/b: an instruction that cannot be followed for a
# reason other than an illegal target or unavailable information is Negated, not Ignored, and a later linked
# instruction still executes unless it names the negated action itself. A Move a restriction forbids is the rules' own
# example (Ride the Wind at Vilemaw's Lair: the Move is negated, "ready it" still readies the unit). Under the 07-16
# text the same Move was ignored and took its linked instructions with it. A replaced event (replaced_prevented and
# the other replacement outcomes) was never in IGNORED_OUTCOMES: negated too, as before.
NEGATED_OUTCOMES = frozenset({"skipped_restricted_move"})
# "draw 1 for each of your [Mighty] units" (Kadregrin the Infernal): a draw whose count is its
# printed number times a count read as the instruction executes. One kind: the units the
# program's controller controls on the board that are Mighty - Might 5 or greater (Core 708),
# by their current Might (710).
COUNT_PER_KINDS = {"units_you_control"}
MIGHTY_AT = 5


# 2026-09-27 package 6: "For each buff spent, channel 1 rune exhausted." - the count is how many an
# EARLIER instruction of this program spent (its applied_count), a linked instruction (Core
# 359.3.e.14): ignored when that one was ignored (359.3.e.14.a). Only instructions whose receipt is a
# count of what they did are read (LINKED_COUNT_OPS); only these ops multiply by it.
LINKED_COUNT_OPS = {"spend_buffs"}
# ops whose own decision_ref is a choice made as they resolve, never a target (resolution_bridge keeps such a
# resolution-stage selection apart from the targets bound at finalization). Named apart from package 6 f1's
# RESOLUTION_CHOICE_OPS (kill / return_to_hand whose `choice` is made as they resolve, Core 355.10.e)
DECISION_REF_CHOICE_OPS = {"spend_buffs"}
LINKED_COUNT_READERS = {"channel_rune", "draw"}
# 2026-10-12 package 11 (Teemo - Strategist: "Deal 1 to that unit for each card with [Hidden] revealed this way"): how
# many of the cards an EARLIER reveal of this program showed carry the keyword - each still the object it was when
# revealed (Core 124) - multiplying a Deal's printed amount (a linked instruction, Core 359.3.e.14: ignored when the
# reveal was). One keyword so far
LINKED_REVEALED_COUNT = "linked_revealed_with_keyword"
LINKED_REVEALED_KEYWORDS = {"hidden"}
LINKED_REVEALED_READERS = {"deal_damage"}


def is_count_per(value: Any) -> bool:
    if isinstance(value, dict) and value.get("kind") == LINKED_REVEALED_COUNT:
        return (set(value) == {"kind", "effect_id", "keyword"} and isinstance(value.get("effect_id"), str)
                and bool(value["effect_id"]) and value.get("keyword") in LINKED_REVEALED_KEYWORDS)
    if isinstance(value, dict) and value.get("kind") == "linked_applied_count":
        return set(value) == {"kind", "effect_id"} and isinstance(value.get("effect_id"), str) and bool(value["effect_id"])
    return isinstance(value, dict) and value == {"kind": "units_you_control", "mighty": True}


def count_per_value(state: dict[str, Any], spec: dict[str, Any], controller: str | None) -> tuple[int, list[str]]:
    """(how many, which) for a count_per, read now (Core 708, 710)."""
    counted = sorted(object_id for object_id, obj in state["objects"].items()
                     if obj.get("kind") == "unit" and obj.get("controller") == controller
                     and zone_class(find_location(state, object_id)) == "board"
                     and effective_might(state, object_id) >= MIGHTY_AT)
    return len(counted), counted


def is_object_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"object_ref"}


def is_location_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"kind"} and value.get("kind") in LOCATION_REF_KINDS


def is_amount_ref(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("kind") not in AMOUNT_REF_KINDS:
        return False
    if value["kind"] in LINKED_AMOUNT_REF_KINDS:
        return set(value) == {"kind", "effect_id"} and isinstance(value.get("effect_id"), str) and bool(value["effect_id"])
    return set(value) == {"kind"}


def is_object_player(value: Any) -> bool:
    """{"object_player": {"effect_id", "relation"}} - see OBJECT_PLAYER_RELATIONS."""
    if not isinstance(value, dict) or set(value) != {"object_player"}:
        return False
    spec = value["object_player"]
    return (isinstance(spec, dict) and set(spec) == {"effect_id", "relation"} and isinstance(spec.get("effect_id"), str)
            and bool(spec["effect_id"]) and spec.get("relation") in OBJECT_PLAYER_RELATIONS)


def is_source_ref(value: Any) -> bool:
    """{"effect_id"} - "It deals damage ...": the object an earlier instruction acted on is the
    source of this Deal (Core 417.6.b.3), not the spell."""
    return isinstance(value, dict) and set(value) == {"effect_id"} and isinstance(value.get("effect_id"), str) \
        and bool(value["effect_id"])


def on_board_as_linked(state: dict[str, Any], snapshots: list[dict[str, Any]], object_id: str,
                       linked_event: dict[str, Any]) -> bool:
    """Still on the board, and the same object the linked instruction acted on: its identity now
    is the one it had right after that instruction (Core 124, 359.3.e.12)."""
    import game_events
    at = linked_event.get("index")
    after_link = snapshots[at + 1] if isinstance(at, int) and at + 1 < len(snapshots) else game_events.snapshot(state)
    return (object_id in state["objects"] and zone_class(find_location(state, object_id)) == "board"
            and object_identity(state, object_id) == (after_link.get(object_id) or {}).get("identity"))


def linked_identity(snapshots: list[dict[str, Any]], object_id: str, linked_event: dict[str, Any], *, after: bool) -> str | None:
    """The identity of the object the linked instruction acted on (GPT 2026-09-27, group 乙: "its"
    is bound by identity, not only by which instruction came before) - as that instruction found it
    (after=False) or as it left it (after=True)."""
    at = linked_event.get("index")
    if not isinstance(at, int):
        return None
    position = at + 1 if after else at
    if not 0 <= position < len(snapshots):
        return None
    return (snapshots[position].get(object_id) or {}).get("identity")


def linked_objects(trace: list[dict[str, Any]], effect_id: str) -> tuple[list[str] | None, dict[str, Any] | None]:
    """The objects an earlier instruction of this program acted on, and its trace event - or
    (None, event) when that instruction was ignored or acted on nothing (Core 359.3.e.14.a).
    A discard names the cards it discarded; every other instruction the object it acted on,
    or, when a replacement took its place, the object the replaced event was acting on
    (359.3.e.14.b)."""
    event = next((e for e in trace if e.get("effect_id") == effect_id), None)
    if event is None:
        return None, None
    if event.get("outcome") in LINKED_IGNORED_OUTCOMES or event.get("reason") == "bound_object_left_board":
        return None, event
    if isinstance(event.get("objects"), list):
        found = [o for o in event["objects"] if isinstance(o, str)]
    else:
        single = event.get("object_id") if isinstance(event.get("object_id"), str) else event.get("affected_object_id")
        found = [single] if isinstance(single, str) else []
    return (found or None), event


def contains_object_ref(value: Any) -> bool:
    """Anywhere in a nested structure. Used to keep the shape OUT of decision
    artifacts: only the engine may create or resolve one."""
    if is_object_ref(value):
        return True
    if isinstance(value, dict):
        return any(contains_object_ref(v) for v in value.values()) or "object_ref" in value
    if isinstance(value, list):
        return any(contains_object_ref(v) for v in value)
    return False


def derive_targeted(selector: dict[str, Any]) -> bool:
    """ADR-0005 §1: target status is compiled from the selector, never set by the caller.
    A chosen object in a public zone (the board, or a public non-board zone such as
    the trash) is a target; a choice from a non-public zone is not (Core 355.10.a)."""
    if selector.get("chosen_zone_class") == "board":
        return True
    # 2026-10-18 package 15 (found by C2's differential: Defy's "Counter a spell" took any object as its target): the
    # Chain is Public too (Core 108.1.b), so a spell or ability chosen there is a target (355.10; 355.9.c's own example
    # is "Counter a spell") - checked as it is chosen like any other
    return selector.get("location") in {"trash", "banishment", "chain"}


def _object_id_errors(value: Any, label: str) -> list[str]:
    """A literal id, or the engine's own typed self-reference."""
    if is_object_ref(value):
        if value["object_ref"] not in OBJECT_REF_KINDS:
            return [f"{label}.object_ref must be one of {list(OBJECT_REF_KINDS)}"]
        return []
    if not isinstance(value, str) or not value:
        return [f"{label} must be a non-empty object id or {{object_ref}}"]
    return []


def _selector_errors(selector: Any) -> list[str]:
    if not isinstance(selector, dict):
        return ["must be an object"]
    errors = []
    if set(selector) - SELECTOR_FIELDS:
        errors.append(f"has unsupported fields {sorted(set(selector) - SELECTOR_FIELDS)}")
    if "decision_ref" in selector and "selection_ref" in selector:
        errors.append("carries both decision_ref and selection_ref; a reference names one or the other")
    if "decision_ref" in selector:
        if not isinstance(selector["decision_ref"], str) or not selector["decision_ref"]:
            errors.append("decision_ref must be non-empty")
    elif "selection_ref" in selector:
        # selection-binding.v1: it refers to a selection an EARLIER instruction
        # of this program established, not to a decision id it may read by name.
        if not isinstance(selector["selection_ref"], str) or not selector["selection_ref"]:
            errors.append("selection_ref must be non-empty")
    elif not isinstance(selector.get("object_id"), str) or not selector.get("object_id"):
        errors.append("must identify an object, defer to a decision_ref, or refer to a selection_ref")
    if selector.get("chosen_zone_class") not in {"board", "non_board"}:
        errors.append("chosen_zone_class is required")
    if "location" in selector and selector["location"] not in {"board", "battlefield", "base", "non_board", "main_deck", "hand", "trash", "banishment", "rune_deck", "chain", "champion_zone", "facedown"}:
        errors.append("location is invalid")
    if "location_ref" in selector:
        # the single-target "an enemy unit here" (Crackshot Corsair's shape): the
        # target must be at the source's CURRENT Battlefield, bound from the program
        # when the target is chosen and checked again when it is used (Core 359.3.f.2)
        if not is_location_ref(selector["location_ref"]):
            errors.append(f"location_ref must be {{kind}} with kind in {list(LOCATION_REF_KINDS)}")
        if "location" in selector:
            errors.append("carries both location and location_ref; a selector names one or the other")
        if selector.get("kind") == "battlefield":
            errors.append("location_ref narrows where an object is; a Battlefield target has no location")
    if "controller_relation" in selector and selector["controller_relation"] not in {"friendly", "enemy"}:
        errors.append("controller_relation is invalid")
    if "any_of" in selector:
        alternatives = selector["any_of"]
        def champion_zone_alternative(a):
            # package 10: the one non-board alternative - the controller's own Champion Zone (Core 108.3, public: 355.10.a.1)
            return (a.get("location") == "champion_zone" and a.get("chosen_zone_class") == "non_board"
                    and a.get("zone_owner_relation") == "own" and "controller_relation" not in a)

        def facedown_alternative(a):
            # package 10 (Pack of Wonders, "a facedown card"): a card in a Facedown Zone (Core 107.3; public: 355.10.a.1),
            # of no kind the chooser can see - so it names none
            return (a.get("location") == "facedown" and a.get("chosen_zone_class") == "non_board" and "kind" not in a
                    and "zone_owner_relation" not in a)

        if not isinstance(alternatives, list) or len(alternatives) < 2 or any(
                not isinstance(a, dict) or set(a) - ANY_OF_FIELDS
                or not (facedown_alternative(a)
                        or ("kind" in a and a.get("kind") in OBJECT_KINDS
                            and (champion_zone_alternative(a)
                                 or (a.get("location", "board") in {"board", "battlefield", "base"}
                                     and a.get("chosen_zone_class", "board") == "board" and "zone_owner_relation" not in a))))
                or a.get("controller_relation", "friendly") not in {"friendly", "enemy"} for a in alternatives):
            errors.append(f"any_of must list two or more {{kind, location?, controller_relation?}} alternatives (or the "
                          f"controller's own Champion Zone: {{kind, location champion_zone, chosen_zone_class non_board, "
                          f"zone_owner_relation own}}; or a Facedown Zone: {{location facedown, chosen_zone_class "
                          f"non_board, controller_relation?}})")
        if {"kind", "location", "controller_relation"} & set(selector):
            errors.append("any_of carries the kind, location and relation; the selector itself names none of them")
        if selector.get("chosen_zone_class") != "board":
            errors.append("any_of chooses among objects on the board")
    if "zone_owner_relation" in selector and selector["zone_owner_relation"] not in {"own", "opponent"}:
        errors.append("zone_owner_relation is invalid")
    if "with_hidden" in selector and selector["with_hidden"] is not True:
        errors.append("with_hidden is true when present (a card with the Hidden keyword, Core 811)")
    if "with_tag" in selector and (not isinstance(selector["with_tag"], str) or not selector["with_tag"]):
        errors.append("with_tag is a tag name, as printed (Core 133.8)")
    if "owner_relation" in selector and selector["owner_relation"] != "own":
        errors.append("owner_relation is own when present (an object its controller's player owns, Core 132)")
    if "chosen_champion" in selector and selector["chosen_champion"] is not True:
        errors.append("chosen_champion is true when present (Core 103.2.a.3)")
    if "include_legend_zone" in selector and (selector["include_legend_zone"] is not True
                                              or selector.get("chosen_zone_class") != "board" or "kind" in selector
                                              or "location" in selector):
        errors.append("include_legend_zone is true when present, on a kind-less board target with no location: it adds "
                      "a Legend in its Legend Zone to the objects on the board (Core 107.4, 355.9.a.4)")
    if "targeted" in selector and selector["targeted"] != derive_targeted(selector):
        errors.append("targeted is derived from the selector and cannot be overridden")
    if "bound_identity" in selector and (not isinstance(selector["bound_identity"], str) or "@" not in selector["bound_identity"]):
        errors.append("bound_identity must be an identity token")
    if "max_might" in selector and (not isinstance(selector["max_might"], int) or selector["max_might"] < 0):
        errors.append("max_might must be a non-negative integer")
    for state_field in SELECTOR_STATE_FIELDS:
        if state_field in selector and (not isinstance(selector[state_field], bool) or selector.get("chosen_zone_class") != "board"):
            errors.append(f"{state_field} is true or false, on an object chosen on the board (Core 414.2, 415.2, 142)")
    exclude = selector.get("exclude_source_identity")
    if "exclude_source_identity" in selector and (not isinstance(exclude, str)
                                                  or (exclude != SOURCE_IDENTITY_SENTINEL and "@" not in exclude)):
        errors.append(f"exclude_source_identity must be {SOURCE_IDENTITY_SENTINEL!r} or an identity token")
    if "max_cost" in selector:
        from cost_comparison import validate_limit  # standalone module; no cycle
        errors.extend(f"max_cost {e}" for e in validate_limit(selector["max_cost"]))
    if "energy_cost_below_points" in selector and selector["energy_cost_below_points"] is not True:
        errors.append("energy_cost_below_points is true when present (the printed Energy cost below the controller's points)")
    return errors


def _receipt_errors(receipt: Any) -> list[str]:
    if receipt is None:
        return []
    from cost_receipt import validate_cost_receipt  # standalone module; no cycle
    return [f"cost_receipt {e}" for e in validate_cost_receipt(receipt)]


def _predicate_errors(predicate: Any, receipt: Any, earlier: set[str] | None = None, earlier_effects: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """ADR-0005 §5: named predicates, not one ambiguous negative dependency.
    A cost predicate must name a component of the program's receipt; an
    action predicate must name an earlier instruction; an unknown id is
    invalid_input. Recognized-but-unimplemented kinds validate here and
    answer `unsupported` at execution."""
    if isinstance(predicate, dict) and predicate.get("kind") == "state_holds":
        if set(predicate) != {"kind", "condition"}:
            return ["state_holds must carry exactly {kind, condition}"]
        return [f"condition {e}" for e in validate_condition(predicate["condition"])]
    if isinstance(predicate, dict) and predicate.get("kind") == "target_state_holds":
        # package 10: {kind, condition {kind in TARGET_STATE_CONDITIONS}} - read off the instruction's own target
        condition = predicate.get("condition")
        if set(predicate) != {"kind", "condition"} or not isinstance(condition, dict) or set(condition) != {"kind"} \
                or condition.get("kind") not in TARGET_STATE_CONDITIONS:
            return [f"target_state_holds must carry exactly {{kind, condition {{kind in {sorted(TARGET_STATE_CONDITIONS)}}}}}"]
        return []
    if isinstance(predicate, dict) and predicate.get("kind") == "predicate_not_met":
        # package 10: "Otherwise" - the referenced earlier instruction must itself carry a condition
        if set(predicate) != {"kind", "effect_id"} or not isinstance(predicate.get("effect_id"), str):
            return ["predicate_not_met must carry exactly {kind, effect_id}"]
        if earlier is not None and predicate["effect_id"] not in earlier:
            return [f"effect_id {predicate['effect_id']!r} must reference an earlier instruction"]
        if earlier_effects is not None and not (earlier_effects.get(predicate["effect_id"]) or {}).get("predicate"):
            return [f"'otherwise' reads an earlier instruction's condition; {predicate['effect_id']!r} has none"]
        return []
    if not isinstance(predicate, dict) or predicate.get("kind") not in PREDICATE_KINDS or set(predicate) - {"kind", "cost_id", "effect_id", "cost_offer_id"}:
        return ["must carry a known kind"]
    if "cost_offer_id" in predicate and predicate["kind"] not in {"cost_paid", "cost_not_paid"}:
        return ["cost_offer_id belongs to a cost predicate"]
    if predicate["kind"] in {"cost_paid", "cost_not_paid"}:
        if not isinstance(predicate.get("cost_id"), str) or not predicate["cost_id"]:
            return ["cost_id is required for cost predicates"]
        if "cost_offer_id" in predicate and (not isinstance(predicate["cost_offer_id"], str) or not predicate["cost_offer_id"]):
            return ["cost_offer_id must be a non-empty string"]
        if receipt is None:
            return ["needs the program's cost_receipt"]
        if predicate["cost_id"] not in {c.get("cost_id") for c in receipt.get("components", [])}:
            return [f"cost_id {predicate['cost_id']!r} is not on the receipt"]
    else:
        if not isinstance(predicate.get("effect_id"), str) or not predicate["effect_id"]:
            return ["effect_id is required for action predicates"]
        if earlier is not None and predicate["effect_id"] not in earlier:
            return [f"effect_id {predicate['effect_id']!r} must reference an earlier instruction"]
        if predicate["kind"] == "requested_count_not_reached" and earlier_effects is not None:
            referenced = earlier_effects.get(predicate["effect_id"], {})
            if referenced.get("op") not in COUNT_CONTRACT_OPS and not isinstance(referenced.get("targets"), dict):
                return [f"requested_count_not_reached may only reference an instruction with a count contract (channel_rune or bounded targets); {predicate['effect_id']!r} is {referenced.get('op')!r}"]
    return []


def _zone_op_errors(effect: dict[str, Any]) -> list[str]:
    """Shape of the C-43 zone instructions (ADR-0011 §5)."""
    op = effect.get("op")
    errors: list[str] = []
    if op == "banish":
        holders = [k for k in ("object_id", "objects", "target", "targets", "choice", "linked") if effect.get(k) is not None]
        if len(holders) != 1:
            errors.append("needs exactly one of object_id, objects, target, targets, choice or linked")
        linked = effect.get("linked")
        if linked is not None and (not isinstance(linked, dict) or set(linked) != {"effect_id"}
                                   or not isinstance(linked["effect_id"], str) or not linked["effect_id"]):
            errors.append("linked must be {effect_id}: the earlier reveal_until whose card is banished")
        if effect.get("objects") is not None and (not isinstance(effect["objects"], list) or not effect["objects"]
                                                  or any(not isinstance(o, str) or not o for o in effect["objects"]) or len(effect["objects"]) != len(set(effect["objects"]))):
            errors.append("objects must be a non-empty unique array")
    elif op == "counter":
        # 2026-10-08 (package 10, Wind Wall / Defy: "Counter a spell [that costs no more than ...]"): or a TARGET - a spell
        # on the Chain chosen as the countering card is played (Core 355.7, 355.5), its legality (and any max_cost) read
        # by evaluate_target; the instruction counters the Chain item that card is
        targeted = effect.get("target")
        if targeted is not None:
            if effect.get("chain_item_id") is not None:
                errors.append("names its chain item OR targets a spell on the Chain, not both")
            if not isinstance(targeted, dict) or targeted.get("location") != "chain" \
                    or targeted.get("chosen_zone_class") != "non_board" or targeted.get("kind") != "spell":
                errors.append("a counter's target is {chosen_zone_class: non_board, location: chain, kind: spell} (Core 425.1)")
        elif not isinstance(effect.get("chain_item_id"), str) or not effect.get("chain_item_id"):
            errors.append("needs the chain_item_id it clears (Core 425.1)")
        if effect.get("card_to", "trash") not in {"trash", "hand"}:
            errors.append("card_to must be trash (Core 425.1.a) or hand when the effect says so")
        if effect.get("targets") is not None or effect.get("object_id") is not None:
            errors.append("names a chain item or targets one spell on the Chain, not objects")
    elif op == "burn":
        if not isinstance(effect.get("player"), str) or not effect.get("player"):
            errors.append("needs a player")
        if not isinstance(effect.get("count"), int) or isinstance(effect.get("count"), bool) or effect.get("count", 0) < 1:
            errors.append("needs a positive count")
        if effect.get("target") is not None or effect.get("targets") is not None or effect.get("object_id") is not None:
            errors.append("is not a targeted instruction")
    return errors


def _reveal_op_errors(effect: dict[str, Any]) -> list[str]:
    """Shape of the C-41 instructions (ADR-0011 §3)."""
    op = effect.get("op")
    errors: list[str] = []

    def positive(field: str, required: bool = True) -> None:
        value = effect.get(field)
        if value is None and not required:
            return
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(f"needs a positive {field}")

    def ref(field: str, required: bool = False) -> None:
        value = effect.get(field)
        if value is None and not required:
            return
        if not isinstance(value, str) or not value:
            errors.append(f"{field} must be a non-empty string")

    player = effect.get("player")
    # package 6: "Recycle the rest." after "Each player chooses ...": what the group's choices were
    # offered and did not take (rest_of). Each card goes to its owner's deck (Core 416.1.c), and each
    # owner orders their own deck's cards (416.5.a) - no single player is named
    # 2026-10-12 package 11 (Teemo - Strategist: "then recycle the revealed cards"): the cards an EARLIER reveal of this
    # program showed, each still that object (revealed_by); not chosen and not targets (Core 355.10.a)
    revealed_by = effect.get("revealed_by")
    if op == "recycle" and revealed_by is not None:
        if not isinstance(revealed_by, str) or not revealed_by:
            errors.append("revealed_by names the reveal whose cards are recycled")
        if {"objects", "choice", "decision_ref", "rest_of"} & set(effect):
            errors.append("revealed_by recycles what the reveal showed; it names no objects, choice, decision or group")
    elif revealed_by is not None:
        errors.append("revealed_by is read by recycle only")
    rest_of = effect.get("rest_of")
    if op == "recycle" and rest_of is not None:
        if not isinstance(rest_of, str) or not rest_of:
            errors.append("rest_of names the group whose unchosen objects are recycled")
        if {"objects", "choice", "player", "decision_ref"} & set(effect):
            errors.append("rest_of recycles what the group left; it names no objects, choice, player or decision")
        return errors
    elif rest_of is not None:
        errors.append("rest_of is read by recycle only")
    # Sabotage: "they reveal their hand" - the player an earlier instruction
    # chose. A reference is only legal to a decision, never to a rule for
    # finding a player again.
    if not ((isinstance(player, str) and player)
            or (isinstance(player, dict) and set(player) == {"decision_ref"}
                and isinstance(player.get("decision_ref"), str) and player["decision_ref"])):
        errors.append("needs a player, or a {decision_ref} naming the one an earlier instruction chose")
    if op == "look_at_top":
        positive("count")
    elif op == "reveal":
        # 2026-10-13 package 11 (Twisted Fate - Gambler): the top of the Rune Deck too
        if effect.get("from") not in {"main_deck_top", "rune_deck_top", "hand"}:
            errors.append("from must be main_deck_top, rune_deck_top or hand")
        if effect.get("from") in {"main_deck_top", "rune_deck_top"}:
            positive("count")
        elif "count" in effect:
            errors.append("a hand reveal shows every card (Core 424.2.b); count does not apply")
    elif op == "put_back":
        if effect.get("position", "top") not in {"top", "bottom"}:
            errors.append("position must be top or bottom")
        ref("decision_ref")
    elif op == "put_in_hand":
        positive("count", required=False)
        ref("decision_ref")
    elif op == "draw_it":
        ref("decision_ref")
    elif op == "choose_player":
        choice = effect.get("choice")
        if not isinstance(choice, dict) or choice.get("from") != "players" or choice.get("selection_kind") != "single":
            errors.append("choose_player needs a single choice from players")
        ref("decision_ref")
        if effect.get("player") is not None:
            errors.append("choose_player is the instruction that picks the player; it does not name one")
    elif op == "recycle":
        objects = effect.get("objects")
        if (objects is None) == (effect.get("choice") is None) and revealed_by is None:
            errors.append("needs exactly one of objects or choice")
        if objects is not None and (not isinstance(objects, list) or not objects or any(not isinstance(o, str) or not o for o in objects) or len(objects) != len(set(objects))):
            errors.append("objects must be a non-empty unique array")
        ref("order_ref")
        ref("decision_ref")
    elif op == "predict":
        positive("count", required=False)
        ref("recycle_ref")
        ref("order_ref")
        ref("put_back_ref")
    if effect.get("target") is not None or effect.get("targets") is not None or effect.get("object_id") is not None:
        errors.append("is not a targeted instruction (Core 355.10.a)")
    return errors


def action_performed(event: dict[str, Any]) -> bool:
    """Did the original game action of this instruction happen (359.3.e.14.b, 205)?"""
    return event.get("outcome") in PERFORMED_OUTCOMES


def sole_controlled_unit_at_referent_location(state: dict[str, Any], controller: str | None, event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """ADR-0007 §9 (En Garde): the earlier instruction's legal referent must be
    the only unit its controller — the effect's controller, teammates
    excluded — controls at the referent's current location."""
    referent = event.get("object_id") if action_performed(event) else None
    if not isinstance(referent, str) or referent not in state["objects"]:
        return False, {"referent": None, "reason": "no legal referent"}
    location = find_location(state, referent)
    if location is None:
        return False, {"referent": referent, "reason": "referent has no location"}
    if location[0] == "battlefield":
        present = list(state["battlefields"][location[1]]["objects"])
    else:
        present = list(state["players"][location[1]]["zones"][location[2]])
    controlled = [o for o in present if state["objects"][o].get("kind") == "unit" and state["objects"][o].get("controller") == controller]
    holds = controlled == [referent]
    return holds, {"referent": referent, "location": location, "controlled_units_there": controlled}


def _local_predicate(predicate: dict[str, Any], effect: dict[str, Any], state: dict[str, Any],
                     decisions: dict[str, Any] | None, trace: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """package 10 (Solari Chief). target_state_holds: the instruction's own target - its object_id, or the object its
    target decision chose (at play or at the trigger's finalization) - read now, as it executes (Core 359.3.d); a target
    no longer on the board does not hold. predicate_not_met: "Otherwise" - the referenced earlier instruction was skipped
    because ITS condition did not hold; when its condition held, otherwise does not run, whether or not its action then
    happened (a replaced kill is still a stunned unit)."""
    import engine_decisions as ed
    if predicate["kind"] == "predicate_not_met":
        event = next((e for e in trace if e.get("effect_id") == predicate["effect_id"]), None)
        if event is None:
            raise ValueError(f"'otherwise' reads {predicate['effect_id']!r}, which has not run")
        return event.get("predicate_result") is False, ["Core 359.3.e.14"]
    target = effect.get("target") or {}
    object_id = effect.get("object_id") if isinstance(effect.get("object_id"), str) else target.get("object_id")
    if object_id is None and target.get("decision_ref"):
        entry = ed.target_selection(decisions, target["decision_ref"])
        object_id = (entry or {}).get("value", [None])[0] if entry else None
    obj = state["objects"].get(object_id or "") or {}
    on_board = object_id is not None and zone_class(find_location(state, object_id)) == "board"
    if predicate["condition"]["kind"] == "is_stunned":
        return bool(on_board and obj.get("stunned") is True), ["Core 359.3.d", "Core 423"]
    return False, ["Core 359.3.d"]


def _names_another_card(condition: Any) -> bool:
    """Whether a condition (possibly under not / all / any) reads another_card_finalized_this_turn."""
    if not isinstance(condition, dict):
        return False
    if condition.get("kind") == "another_card_finalized_this_turn":
        return True
    nested = [condition.get("of")] + list(condition.get("conditions") or [])
    return any(_names_another_card(c) for c in nested)


def evaluate_predicate(predicate: dict[str, Any], receipt: dict[str, Any] | None, events: dict[str, dict[str, Any]] | None = None, state: dict[str, Any] | None = None, controller: str | None = None, source: str | None = None) -> tuple[bool | None, list[str]]:
    """Returns (holds, locators); holds is None when the kind is not implemented. `source` is the
    program's own source object: a state_holds condition about an object it does not name is about
    that source (2026-09-27 package 6: "if I am at a battlefield", "a ready enemy unit here")."""
    kind = predicate["kind"]
    if kind not in IMPLEMENTED_PREDICATES:
        return None, []
    if kind in {"cost_paid", "cost_not_paid"}:
        component = next((c for c in (receipt or {}).get("components", []) if c["cost_id"] == predicate["cost_id"]), None)
        if component is None:
            # No component, no receipt to read. "Not paid" is the honest answer
            # for cost_not_paid; "paid" would be a claim about a payment this
            # program has no evidence of.
            return (kind == "cost_not_paid"), ["Core 356.4.f.1"]
        wanted = predicate.get("cost_offer_id")
        if wanted is not None and component.get("cost_offer_id") != wanted:
            # The receipt names a different offer - another card's, or another
            # offer on this one. It does not satisfy this predicate.
            return (kind == "cost_not_paid"), ["Core 356.4.f.1", "Core 820.1"]
        paid = bool(component["paid"])
        return (paid if kind == "cost_paid" else not paid), ["Core 356.4.f.1", "Core 356.2.b.1"]
    if kind == "state_holds":
        # read now, as the instruction executes, from the controller's own perspective (a
        # condition on a zone that player may not see is refused by evaluate_condition)
        return evaluate_condition(state or {}, predicate["condition"], controller=controller,
                                  object_id=source, perspective=controller), ["Core 359.3.d"]
    event = (events or {}).get(predicate["effect_id"])
    if event is None:
        return False, ["Core 359.3.e.14.a"]
    if kind == "action_performed":
        return action_performed(event), ["Core 359.3.e.14.b", "Core 359.3.e.14.c", "Core 205"]
    if kind == "action_not_performed":
        return not action_performed(event), ["Core 359.3.e.14.b", "Core 205"]
    if kind == "sole_controlled_unit_at_referent_location":
        holds, _ = sole_controlled_unit_at_referent_location(state or {}, controller, event)
        return holds, ["Core 135.2.b.5.a", "Core 359.3.e.14.a"]
    # requested_count_not_reached: "If you couldn't" tests actual < requested
    # (430.5); an instruction that did not happen at all also did not reach it.
    requested = event.get("requested_count", event.get("requested_targets"))
    applied = event.get("applied_count", event.get("applied_targets"))
    if not (isinstance(requested, int) and isinstance(applied, int)):
        # validate_program keeps this unreachable for well-formed programs; a
        # referenced event without counts is a malformed program, never a guess.
        raise ValueError(f"requested_count_not_reached references {predicate['effect_id']!r}, whose event carries no count contract")
    return applied < requested, ["Core 430.3", "Core 430.5", "Core 055"]


# "source_card" (2026-10-06, package 9, Ravenborn Tome): the Deals of ONE spell - the object and the identity it had
# as it was played - and of nothing else (713, 715.1)
BONUS_SCOPES = {"controller_sources", "location", "source_card"}


def source_active(state: dict[str, Any], source_id: str) -> bool:
    """ADR-0012 §5: a passive's source is active while it is a Battlefield, a
    board object, or a Legend in the Legend Zone — which is not a Location but
    holds a continuously active Game Object (Core 107.4.d, 365.1)."""
    if source_id in state["battlefields"]:
        return True
    location = find_location(state, source_id)
    if zone_class(location) == "board":
        return True
    return location is not None and location[0] == "player" and location[2] == "legend_zone"


GRANTED_ENTRY_CRITERIA = {"kind": "unit", "controller_relation": "friendly", "exclude_source": True}


def granted_entry_states(state: dict[str, Any], entering: str | None, kind: str, controller: str) -> list[dict[str, Any]]:
    """2026-09-27 package 6: the entry replacements other permanents grant a Unit entering the board
    ("Other friendly units enter ready.", Core 369.3): one per grant of each source that is on the
    board now (365.1), on the entering Unit's controller's side, that is not the entering object
    itself. `entering` is the object entering (None for a token not yet made); `kind` its type."""
    found = []
    for source_id in sorted(state.get("objects") or {}):
        source = state["objects"][source_id]
        grants = source.get("granted_entry_states") or []
        if not grants or source_id == entering or zone_class(find_location(state, source_id)) != "board":
            continue
        for grant in grants:
            criteria = grant["criteria"]
            if kind != criteria["kind"] or not same_side(state, source.get("controller"), controller):
                continue
            found.append({"replacement_id": f"{source_id}:{grant['replacement_id']}", "source": source_id,
                          "mode": "granted_entry_state", "value": grant["value"], "rule_locators": ["Core 369.3", "Core 365.1"]})
    return found


def bonus_damage(state: dict[str, Any], controller: str | None, object_id: str | None,
                 source_object: str | None = None) -> tuple[int, list[dict[str, Any]]]:
    """Core 713-715: every active Bonus Damage that applies to this Deal,
    summed once (714). `controller_sources` follows the spell's or ability's
    controller; `location` follows the affected unit's current Battlefield.
    An inactive source contributes nothing; an unknown scope is a mechanic
    the engine does not have."""
    total = 0
    sources: list[dict[str, Any]] = []
    location = find_location(state, object_id) if object_id is not None else None
    for effect in canonical_effects(state) + printed_aura_effects(state):
        if effect["kind"] != "bonus_damage":
            continue
        active, _ = _effect_active(state, effect)
        if not active:
            continue
        criteria = effect["affects"]["criteria"]
        scope = criteria["bonus_scope"]
        kind = scope["kind"]
        if kind not in BONUS_SCOPES:
            raise NotImplementedError(f"Bonus Damage scope {kind!r} is not modelled")
        if kind == "controller_sources" and criteria["controller"] != controller:
            continue
        if kind == "location" and not (location is not None and location[0] == "battlefield" and location[1] == scope["battlefield"]):
            continue
        if kind == "source_card" and not (source_object == scope.get("object") and source_object is not None
                                          and object_identity(state, source_object) == scope.get("identity")):
            continue
        total += effect["value"]["amount"]
        sources.append({"modifier_id": effect["effect_id"], "source_object": effect["source"]["object"],
                        "amount": effect["value"]["amount"], "scope": dict(scope)})
    return total, sources


SPLIT_BONUS_RULES = ["Core 713", "Core 714", "Core 715.3", "Core 355.14.c", "Core 437.1.a.1"]


def split_bonus_damage(state: dict[str, Any], controller: str | None, object_ids: list[str],
                       source_object: str | None = None) -> tuple[int, list[dict[str, Any]]]:
    """Core 715.3: a Deal that Splits its damage has its Bonus Damage added ONCE, to the amount
    being split - never to each share - so the bonus also raises how many Targets may be chosen
    (355.14.c). What applies is what applies to the Deal (713, 714 - summed once): the
    controller's own ("your spells and abilities"), and a Battlefield's "to units here" when the
    Targets are there. `object_ids` are the Targets the split is over; none means no Deal, and no
    Bonus Damage (715.4). A Battlefield's bonus over a split whose Targets are only partly at that
    Battlefield is a case the rules do not settle; it is refused as a mechanic the engine does not
    have, never guessed."""
    return _split_bonus(state, controller, object_ids, strict=True, source_object=source_object)


def split_target_cap(state: dict[str, Any], effect: dict[str, Any], controller: str | None, object_ids: list[str]) -> int:
    """Core 355.14.c with 715.3: how many Targets a split may have - its printed amount plus the
    Bonus Damage its Deal would have. Asked where the Targets are chosen (play, or a trigger's
    finalization), over the chosen objects. As an upper bound it counts a Battlefield's bonus
    when any chosen Target is there; how the amount is really divided is settled as it resolves
    (split_bonus_damage, 355.14.h)."""
    amount = effect.get("amount", 0)
    if effect.get("source_kind") == "unit":
        return amount
    return amount + _split_bonus(state, controller, object_ids, strict=False)[0]


def _split_bonus(state: dict[str, Any], controller: str | None, object_ids: list[str], *,
                 strict: bool, source_object: str | None = None) -> tuple[int, list[dict[str, Any]]]:
    object_ids = list(object_ids)
    if not object_ids:
        return 0, []
    total = 0
    sources: list[dict[str, Any]] = []
    locations = [find_location(state, object_id) for object_id in object_ids]
    for effect in canonical_effects(state) + printed_aura_effects(state):
        if effect["kind"] != "bonus_damage":
            continue
        active, _ = _effect_active(state, effect)
        if not active:
            continue
        criteria = effect["affects"]["criteria"]
        scope = criteria["bonus_scope"]
        kind = scope["kind"]
        if kind not in BONUS_SCOPES:
            raise NotImplementedError(f"Bonus Damage scope {kind!r} is not modelled")
        if kind == "controller_sources" and criteria["controller"] != controller:
            continue
        if kind == "source_card":
            # package 9: one spell's own Bonus Damage on a Deal that splits - the target cap it would raise (355.14.c)
            # was set before the bonus was bound to the spell; refused by name, never guessed
            if source_object is not None and source_object == scope.get("object"):
                raise NotImplementedError("a split Deal of a spell carrying its own Bonus Damage (next_spell_bonus_damage) "
                                          "is not modelled (Core 715.3, 355.14.c)")
            continue
        if kind == "location":
            there = [location is not None and location[0] == "battlefield" and location[1] == scope["battlefield"]
                     for location in locations]
            if not any(there):
                continue
            if strict and not all(there):
                raise NotImplementedError(
                    f"Bonus Damage {effect['effect_id']!r} is dealt to units at {scope['battlefield']!r}; a split whose "
                    f"Targets are only partly there is not modelled (Core 715.3 adds the bonus once, to the amount split)")
        total += effect["value"]["amount"]
        sources.append({"modifier_id": effect["effect_id"], "source_object": effect["source"]["object"],
                        "amount": effect["value"]["amount"], "scope": dict(scope)})
    return total, sources


def drop_play_bound_replacements(obj: dict[str, Any], item_id: str) -> None:
    """Remove from a card the entry replacements bound to the play `item_id` (Core 805.2.b, 391):
    that play has ended - the card entered, or it was countered (425.1) - and the replacement
    does not outlive it. Printed (unbound) entry replacements stay."""
    kept = [r for r in obj.get("entry_replacements") or [] if r.get("chain_item") != item_id]
    if kept:
        obj["entry_replacements"] = kept
    else:
        obj.pop("entry_replacements", None)


def same_side(state: dict[str, Any], left: str | None, right: str | None) -> bool:
    """Module-level friendliness for criteria expansion: the same player, or the
    same declared team_id (2v2)."""
    if left is None or right is None:
        return False
    if left == right:
        return True
    left_team = state["players"].get(left, {}).get("team_id")
    right_team = state["players"].get(right, {}).get("team_id")
    return left_team is not None and left_team == right_team


class TeamContestUnsupported(NotImplementedError):
    """A Unit arrived at a Battlefield, or Contested would change, in a state with
    teams. Team contest and scoring are not modelled, so the engine stops rather than
    continuing on a guess (GPT, capability 006 ruling)."""


def team_state(state: dict[str, Any]) -> bool:
    """A state with teams: any player carries a team_id, or the Mode of Play names teams."""
    return (any(isinstance(p, dict) and p.get("team_id") is not None for p in state.get("players", {}).values())
            or bool((state.get("mode") or {}).get("teams")))


def apply_arrival_contested(state: dict[str, Any], battlefield_id: str, object_id: str) -> str | None:
    """Core 190.3.a / 190.3.a.1: a Unit moving or played to a Battlefield applies
    Contested if the Battlefield is not already Contested and the Unit's controller
    does not control it. An uncontrolled Battlefield is one its controller does not
    control. In a team state this raises TeamContestUnsupported: the team rules are
    not modelled and a teammate's arrival is not silently skipped. Returns the applier."""
    obj = state["objects"].get(object_id) or {}
    battlefield = state["battlefields"][battlefield_id]
    controller = obj.get("controller")
    if obj.get("kind") != "unit" or controller is None:
        return None
    if team_state(state):
        raise TeamContestUnsupported(
            f"team_contest_unsupported: {object_id} arrived at {battlefield_id} in a state with teams; "
            f"team contest and scoring are not modelled (Core 190.3.a.1)")
    if battlefield.get("contested"):
        return None
    if battlefield.get("controller") == controller:
        return None
    battlefield["contested"] = True
    battlefield["contested_by"] = controller
    return controller


# --------------------------------------------------------------------------
# Move restrictions (Core 144, 359.3.e.6) - DP-96
# --------------------------------------------------------------------------

# The one shape this wave reads: Vilemaw's Lair, "Units can't move from here
# to base." Printed on the Battlefield, because that is where the restriction
# is printed. Every field is a closed vocabulary; a restriction this cannot
# express stays unparsed rather than being approximated.
MOVE_RESTRICTION_FIELDS = {"source_location", "destination_kind", "affected_kind"}
MOVE_RESTRICTION_VALUES = {"source_location": {"here"}, "destination_kind": {"base"}, "affected_kind": {"unit"}}


def move_restriction_errors(battlefield_id: str, restrictions: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(restrictions, list):
        return [f"battlefields.{battlefield_id}.move_restrictions must be an array"]
    for index, entry in enumerate(restrictions):
        label = f"battlefields.{battlefield_id}.move_restrictions[{index}]"
        if not isinstance(entry, dict) or set(entry) != MOVE_RESTRICTION_FIELDS:
            errors.append(f"{label} must carry exactly {sorted(MOVE_RESTRICTION_FIELDS)}")
            continue
        for field, allowed in MOVE_RESTRICTION_VALUES.items():
            if entry[field] not in allowed:
                errors.append(f"{label}.{field} must be one of {sorted(allowed)}; "
                              "a restriction this vocabulary cannot express is not approximated")
    return errors


def move_restricted(state: dict[str, Any], object_id: str, destination: dict[str, Any]) -> dict[str, Any] | None:
    """The restriction that stops this object making this move, or None.

    One predicate, read by both paths, because Core 359.3.e.6 makes them
    *behave* differently rather than *decide* differently: a Standard Move to a
    restricted destination is simply not an action the player may take, while a
    spell may still choose that destination and have the move instruction
    ignored when it resolves. Two predicates would eventually disagree about
    which moves are restricted at all, which is a different bug from either
    behaviour.
    """
    obj = (state.get("objects") or {}).get(object_id)
    if not isinstance(obj, dict):
        return None
    location = find_location(state, object_id)
    if location is None or location[0] != "battlefield":
        return None
    battlefield = (state.get("battlefields") or {}).get(location[1]) or {}
    for entry in battlefield.get("move_restrictions", []) or []:
        if entry.get("affected_kind") != obj.get("kind"):
            continue
        if entry.get("source_location") != "here":
            continue
        if entry.get("destination_kind") != (destination or {}).get("kind"):
            continue
        return {"reason_code": "move_restricted_by_location", "battlefield": location[1],
                "restriction": dict(entry), "object_id": object_id,
                "rule_locators": ["Core 144.4", "Core 359.3.e.6"]}
    return None


def location_token(location: tuple[str, str, str | None] | None) -> str | None:
    """The full name of a board Location, or None for anything off the board."""
    if location is None:
        return None
    if location[0] == "battlefield":
        return f"battlefield:{location[1]}"
    if location[0] == "player" and location[2] == "base":
        return f"base:{location[1]}"
    return None


# "to or from its base" (2026-09-25, Yasuo - Unforgiven): a chosen Move destination narrowed to
# the unit's own Base when it is at a Battlefield, and to a Battlefield when it is in its Base.
# "to a battlefield" (2026-09-27 package 5, Showstopper): a chosen destination that is a
# Battlefield - never a Base (Core 355.4.a, 144.4.b).
# "to here" (2026-10-12 package 11, Blitzcrank - Impassive: "you may move an enemy unit to here"): a chosen destination
# that can only be the program's source's current Battlefield, read where the destination is chosen and again where the
# Move executes (Core 355.4, 359.3.f.2) - bound by bind_move_here, never by the program; no Battlefield there, no
# destination at all, never its Base
# "to its location" / "to my original location" (2026-10-12 package 11, Tideturner; package 10 ruling 4): a chosen
# destination that, as the ability is finalized, can only be where the unit its `target_ref` decision chose is, or
# where the program's source is - bound then (bind_move_here) and fixed, never read again: as the Move executes the
# recorded place only has to be a legal destination (Core 355.4.a, 355.15)
MOVE_DESTINATION_RESTRICTIONS = {"to_or_from_own_base", "battlefield", "here", "location_of_target", "source_location"}
# How a later instruction depends on the earlier one it names in depends_on:
#   if_applied      only when the earlier one was applied (the long-standing default)
#   always          regardless
#   unless_ignored  2026-09-27 package 5 - Core 359.3.e.14.a: a later LINKED instruction ("Buff a
#                   friendly unit in your base, then move IT ...") executes only if the earlier
#                   one executed; it is skipped when the earlier one was ignored (an illegal
#                   target, 359.3.e.6) or itself skipped - but not when the earlier one executed
#                   and changed nothing (a Unit already Buffed is still chosen, 426.1.c).
DEPENDENCY_MODES = {"if_applied", "always", "unless_ignored"}
# unless_ignored reads IGNORED_OUTCOMES, the one set linked_objects reads too (defined above).


def token_play_locations(state: dict[str, Any], controller: str, token_kind: str) -> list[str]:
    """Core 185.2.a, 355.2.a: where a token with no stated place may be played - as its card
    type would be: its controller's Base, and for a Unit each Battlefield that player controls.
    Generated from the board, never supplied."""
    locations = [f"base:{controller}"]
    if token_kind == "unit":
        locations += [f"battlefield:{bf}" for bf, battlefield in sorted((state.get("battlefields") or {}).items())
                      if battlefield.get("controller") == controller]
    return locations


def move_destination_candidates(state: dict[str, Any], object_id: str, destination: dict[str, Any]) -> list[str]:
    """The legal destinations of THIS Move (Core 355.4.a): legal_move_destinations, narrowed by the
    instruction's own restriction - "to a battlefield" offers only Battlefields; "to or from its base" is its
    own Base from a Battlefield and a Battlefield from its Base (144.4.b). One definition, read where the
    destination is chosen (play, finalization) and again where the Move executes."""
    candidates = legal_move_destinations(state, object_id)
    if destination.get("restriction") == "battlefield":
        candidates = [c for c in candidates if c.startswith("battlefield:")]
    if destination.get("restriction") == "here":
        # package 11: only the source's current Battlefield, as bind_move_here read it; unbound or none - no destination
        here = destination.get("here_battlefield")
        candidates = [c for c in candidates if isinstance(here, str) and c == f"battlefield:{here}"]
    if destination.get("restriction") in ("location_of_target", "source_location") and "bound_location" in destination:
        # package 11: only the place bound as the destination is chosen; unbound - as the Move executes - no narrowing
        candidates = [c for c in candidates if c == destination["bound_location"]]
    if destination.get("restriction") == "to_or_from_own_base":
        own_base = f"base:{state['objects'][object_id]['owner']}"
        at = location_token(find_location(state, object_id))
        candidates = ([c for c in candidates if c == own_base] if at != own_base
                      else [c for c in candidates if c.startswith("battlefield:")])
    return candidates


def bind_move_here(destination: dict[str, Any], state: dict[str, Any], program: dict[str, Any],
                   chosen: dict[str, str] | None = None) -> dict[str, Any]:
    """2026-10-12 (package 11): a "to here" destination with the source's current Battlefield read NOW (Core 359.3.f.2)
    as `here_battlefield` - None when the source is gone, a new object, or at no Battlefield (its Base included).
    Tideturner's two (package 10 ruling 4), read where the destination is chosen: "location_of_target" - where the unit
    `chosen` names for its target_ref is now; "source_location" - where the program's source is now; each as
    `bound_location` (None when there is nothing to read). Any other destination is returned as it is."""
    if isinstance(destination, dict) and destination.get("restriction") in ("location_of_target", "source_location"):
        if destination["restriction"] == "source_location":
            whose = program.get("source_object")
        else:
            whose = (chosen or {}).get(destination.get("target_ref"))
        place = location_token(find_location(state, whose)) if isinstance(whose, str) and whose in state["objects"] else None
        return {**destination, "bound_location": place}
    if not isinstance(destination, dict) or destination.get("restriction") != "here":
        return destination
    try:
        here = resolve_location_ref({"kind": "program_source_current_battlefield"}, state, program)
    except SelectionBindingRefused:
        here = None
    return {**destination, "here_battlefield": here}


def legal_move_destinations(state: dict[str, Any], object_id: str) -> list[str]:
    """Core 420.1 / 355.4.a: a Move goes from one board Location to *another*.
    The candidates are every Battlefield and every Base except the one the
    object is already at - generated from the state, never supplied, so a
    decision cannot name a destination the board does not have."""
    here = location_token(find_location(state, object_id))
    if here is None:
        return []
    candidates = [f"battlefield:{bf}" for bf in sorted(state.get("battlefields") or {})]
    # 2026-10-08 (package 10): a permanent resides in its CONTROLLER's Base (Core 107.1.c), so another player's Base is no
    # location it is allowed to be present at, and no Move destination for it (355.4.a). Every player's Base was offered
    controller = (state["objects"].get(object_id) or {}).get("controller")
    candidates += [f"base:{player}" for player in sorted(state.get("players") or {}) if player == controller]
    out = []
    for candidate in candidates:
        if candidate == here:
            continue
        kind, _, name = candidate.partition(":")
        destination = {"kind": kind, "battlefield": name} if kind == "battlefield" else {"kind": "base", "player": name}
        if move_restricted(state, object_id, destination) is None:
            out.append(candidate)
    return out


def find_location(state: dict[str, Any], object_id: str) -> tuple[str, str, str | None] | None:
    for player_id, player in state["players"].items():
        for zone, ids in player["zones"].items():
            if object_id in ids:
                return ("player", player_id, zone)
    for battlefield_id, battlefield in state["battlefields"].items():
        if object_id in battlefield["objects"]:
            return ("battlefield", battlefield_id, None)
        for entry in (battlefield.get("facedown") or {}).get("cards", []):
            if entry["object_id"] == object_id:
                # ADR-0012 §3: a sub-zone of the Battlefield, not the Board.
                return ("facedown", battlefield_id, entry["controller"])
    for item_id, entry in (state.get("chain_items") or {}).items():
        if entry.get("card") == object_id:
            return ("chain", item_id, None)
    return None


def zone_class(location: tuple[str, str, str | None] | None) -> str | None:
    if location is None:
        return None
    if location[0] == "battlefield" or location[2] == "base":
        return "board"
    return "non_board"


def object_state_holds(obj: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """2026-09-27 package 6: the states a selector, a criteria set or a condition may ask of an
    object on the board - `exhausted` (true: Exhausted, Core 414.2; false: Ready, 415.2) and
    `damaged` (true: damage is marked on it, Core 142). A field that is absent asks nothing."""
    if "exhausted" in wanted and bool(obj.get("exhausted")) != wanted["exhausted"]:
        return False
    if "damaged" in wanted and ((obj.get("damage") or 0) > 0) != wanted["damaged"]:
        return False
    return True


def evaluate_target(state: dict[str, Any], target: dict[str, Any], controller: str | None) -> tuple[bool, str]:
    object_id = target["object_id"]
    # package 12 (Core 2026-10-09 811.1.d.3.a, 359.3.e.2.a): see restrict_to_facedown_battlefield
    if target.get("facedown_source_gone"):
        return False, "facedown_source_left_board"
    if target.get("at_battlefield") is not None \
            and find_location(state, object_id) != ("battlefield", target["at_battlefield"], None):
        return False, "target_outside_facedown_battlefield"
    if target.get("kind") == "battlefield":
        # ADR-0007 §4: "all units at a battlefield" targets the Battlefield
        # (355.10.b), which has a bindable identity like any target.
        if object_id not in state["battlefields"]:
            return False, "target_battlefield_missing"
        if target.get("chosen_zone_class") != "board":
            return False, "target_changed_board_zone_class"
        bound = target.get("bound_identity")
        if bound is not None and battlefield_identity(state, object_id) != bound:
            return False, "target_identity_changed"
        return True, "ok"
    if "any_of" in target:
        # one of the alternatives, each checked exactly as a plain selector would be
        base = {k: v for k, v in target.items() if k != "any_of"}
        reasons = []
        for alternative in target["any_of"]:
            ok, reason = evaluate_target(state, {**base, **alternative}, controller)
            if ok:
                return True, "ok"
            reasons.append(reason)
        return False, reasons[0] if len(set(reasons)) == 1 else "target_any_of_requirement_failed"
    obj = state["objects"].get(object_id)
    if obj is None:
        return False, "target_object_missing"
    location = find_location(state, object_id)
    current_class = zone_class(location)
    in_legend_zone = location is not None and location[0] == "player" and location[2] == "legend_zone"
    if current_class != target.get("chosen_zone_class") and not (target.get("include_legend_zone") is True and in_legend_zone):
        return False, "target_changed_board_zone_class"
    required_kind = target.get("kind")
    if required_kind is not None and obj.get("kind") != required_kind:
        return False, "target_kind_requirement_failed"
    if target.get("with_hidden") and not obj.get("hidden"):
        return False, "target_hidden_requirement_failed"
    if target.get("with_tag") is not None:
        # package 10 (Teemo - Swift Scout): a tag never observed is refused, not guessed
        tags = object_tags(state, object_id)
        if tags is None:
            return False, "target_tags_not_observed"
        if target["with_tag"] not in tags:
            return False, "target_tag_requirement_failed"
    if target.get("owner_relation") == "own" and (controller is None or obj.get("owner") != controller):
        return False, "target_owner_requirement_failed"
    if not object_state_holds(obj, target):
        # 2026-09-27 package 6: "an exhausted friendly unit", "something ... that's exhausted" -
        # the state is read now, so an object readied since it was chosen is no longer a legal
        # target when the instruction is used (Core 359.3.e.2)
        return False, "target_state_requirement_failed"
    required_location = target.get("location")
    if required_location == "battlefield" and (location is None or location[0] != "battlefield"):
        return False, "target_location_requirement_failed"
    if required_location == "base" and (location is None or location[0] != "player" or location[2] != "base"):
        return False, "target_location_requirement_failed"
    if required_location == "board" and current_class != "board":
        return False, "target_location_requirement_failed"
    if required_location == "non_board" and current_class != "non_board":
        return False, "target_location_requirement_failed"
    # 2026-10-08 (package 10, Pack of Wonders): a facedown card must still be in a Facedown Zone
    if required_location == "facedown" and (location is None or location[0] != "facedown"):
        return False, "target_location_requirement_failed"
    # 2026-10-08 (package 10, "Counter a spell"): a target on the Chain must still be on the Chain
    if required_location == "chain" and (location is None or location[0] != "chain"):
        return False, "target_location_requirement_failed"
    if required_location in (PLAYER_ZONES | OPTIONAL_PLAYER_ZONES) - {"base"} and (location is None or location[0] != "player" or location[2] != required_location):
        return False, "target_location_requirement_failed"
    def friendly_players(left: str | None, right: str | None) -> bool:
        if left is None or right is None:
            return False
        if left == right:
            return True
        left_team = state["players"].get(left, {}).get("team_id")
        right_team = state["players"].get(right, {}).get("team_id")
        return bool(left_team and right_team and left_team == right_team)
    relation = target.get("controller_relation")
    if relation is not None and controller not in state["players"]:
        return False, "target_controller_context_missing"
    if relation == "friendly" and not friendly_players(controller, obj.get("controller")):
        return False, "target_controller_requirement_failed"
    if relation == "enemy" and friendly_players(controller, obj.get("controller")):
        return False, "target_controller_requirement_failed"
    zone_owner_relation = target.get("zone_owner_relation")
    if zone_owner_relation is not None and controller not in state["players"]:
        return False, "target_controller_context_missing"
    zone_owner = location[1] if location is not None and location[0] == "player" else None
    if zone_owner_relation == "own" and zone_owner != controller:
        return False, "target_zone_owner_requirement_failed"
    if zone_owner_relation == "opponent" and friendly_players(controller, zone_owner):
        return False, "target_zone_owner_requirement_failed"
    if target.get("chosen_champion"):
        # Core 103.2.a.3: the card chosen for the slot, and any Champion Unit with its name
        chosen_name = (state["players"].get(controller) or {}).get("chosen_champion")
        if not (chosen_name and obj.get("champion_unit") is True and obj.get("kind") == "unit" and obj.get("name") == chosen_name):
            return False, "target_chosen_champion_requirement_failed"
    if target.get("object_id") != target.get("bound_object_id", target.get("object_id")):
        return False, "target_identity_changed"
    # ADR-0005 §3 / Core 359.3.e.4: the same physical card back in the same zone
    # is a different object once it has been through a non-board zone.
    bound = target.get("bound_identity")
    if bound is not None and object_identity(state, object_id) != bound:
        return False, "target_identity_changed"
    max_might = target.get("max_might")
    if max_might is not None and effective_might(state, object_id) > max_might:
        return False, "target_might_requirement_failed"
    if target.get("energy_cost_below_points") is True:
        # package 9 (Kai'Sa - Evolutionary): Core 206 - the PRINTED Energy cost, against the controller's points now
        printed = ((state["objects"].get(object_id) or {}).get("printed_cost") or {}).get("energy")
        if not isinstance(printed, int) or isinstance(printed, bool):
            return False, "target_cost_not_observed:printed_energy"
        points = int((state["players"].get(controller) or {}).get("points", 0)) if controller else 0
        if printed >= points:
            return False, "target_energy_cost_not_below_points"
    limit = target.get("max_cost")
    if limit is not None:
        from cost_comparison import compare  # standalone module; no cycle
        verdict = compare(state, object_id, limit)
        if verdict["holds"] is None:
            # DP-93: the basis this card reads is not observable here. Refusing
            # is the only safe answer - treating "cannot see" as "qualifies"
            # would let a spell be countered on no evidence at all.
            return False, f"target_cost_not_observed:{verdict['reason']}"
        if verdict["holds"] is False:
            return False, f"target_cost_over_limit:{verdict['reason']}"
    # "here" on a target (location_ref): bound from the program by _bind_location_ref
    # into `location_battlefield` (not an authorable field), or into the named reason
    # it could not be bound. Reaching the check unbound is refused, never read as "anywhere".
    if "location_ref" in target:
        return False, "target_location_ref_unresolved"
    if target.get("location_ref_refused"):
        return False, target["location_ref_refused"]
    at = target.get("location_battlefield")
    if at is not None and (location is None or location[0] != "battlefield" or location[1] != at):
        return False, "target_not_at_source_battlefield"
    # package 11: a destination that is a Base (trigger_event_destination) - the object must be in that player's Base
    in_base = target.get("location_base")
    if in_base is not None and (location is None or location[0] != "player" or location[1] != in_base
                                or location[2] != "base"):
        return False, "target_not_at_referent_location"
    exclude = target.get("exclude_source_identity")
    if exclude == SOURCE_IDENTITY_SENTINEL:
        # The sentinel reached the check unresolved: nobody bound it to a
        # source. Refusing is the only safe answer - allowing it would make
        # "another unit" silently mean "any unit".
        return False, "target_source_exclusion_unresolved"
    if exclude is not None and object_identity(state, object_id) == exclude:
        return False, "target_excludes_source"
    # package 11: "another" than the trigger's referent, bound by _bind_referent_exclusion; never authored
    if "exclude_trigger_event_object" in target:
        return False, "target_referent_exclusion_unresolved"
    if target.get("referent_exclusion_refused"):
        return False, target["referent_exclusion_refused"]
    if target.get("excluded_referent_identity") is not None \
            and object_identity(state, object_id) == target["excluded_referent_identity"]:
        return False, "target_is_the_trigger_referent"
    return True, "ok"


def restrict_to_facedown_battlefield(program: dict[str, Any], battlefield: str, *, source_gone: bool = False) -> dict[str, Any]:
    """Package 12 (Core 2026-10-09 811.1.d.2, 811.1.d.3, 811.1.d.3.a, 811.1.d.4, 359.3.e.2.a): the program of a card played
    from facedown, or the on-play trigger of a permanent that came from facedown, chooses its targets at that battlefield - each
    target separately - and a target found elsewhere as it resolves is illegal. A target whose own restriction can never
    be met there (one in a Base) is left free. An on-play trigger whose permanent has left the board reads no battlefield
    at all: every target it chooses mistargets (source_gone). Choices that are not targets are left as they are."""
    def tighten(selector: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(selector, dict) or selector.get("location") == "base":
            return selector
        return {**selector, **({"facedown_source_gone": True} if source_gone else {"at_battlefield": battlefield})}

    def walk(value: Any) -> Any:
        if isinstance(value, list):
            return [walk(v) for v in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for key, item in value.items():
            if key == "target" and isinstance(item, dict) and isinstance(item.get("decision_ref"), str):
                out[key] = tighten(item)
            elif key == "targets" and isinstance(item, dict):
                out[key] = {**item,
                            **({"restrictions": tighten(item["restrictions"])} if isinstance(item.get("restrictions"), dict) else {}),
                            **({"selectors": [tighten(s) for s in item["selectors"]]} if isinstance(item.get("selectors"), list) else {})}
            else:
                out[key] = walk(item)
        return out

    return {**program, **({"effects": walk(program["effects"])} if "effects" in program else {}),
            **({"modal": walk(program["modal"])} if "modal" in program else {})}


def _new_target_legal(state: dict[str, Any], selector: dict[str, Any], object_id: str, chooser: str,
                      hidden_at: str | None) -> tuple[bool, str]:
    """A new choice for a Chain item's target (Core 753.1, 753.3, 10-09 text): legal for the new controller now, and, for
    a card played from facedown whose choices are restricted, at the battlefield it was played from."""
    legal, why = evaluate_target(state, {**selector, "object_id": object_id}, chooser)
    if not legal:
        return legal, why
    if hidden_at is not None and find_location(state, object_id) != ("battlefield", hidden_at, None):
        return False, "new_choice_outside_hidden_battlefield"
    return True, "ok"


def _new_choice_effects(spell: dict[str, Any], option_id: str | None) -> list[dict[str, Any]]:
    modal = spell.get("modal")
    if modal:
        return list(next((o["effects"] for o in modal["options"] if o["option_id"] == option_id), []))
    return list(spell.get("effects") or [])


def _new_choice_refs(spell: dict[str, Any], entry: dict[str, Any]) -> set[str]:
    """Every choice of the Chain item as it stands: its mode, and its mode's targets and Move destinations (753)."""
    modal = spell.get("modal")
    option = (entry.get("mode_selection") or {}).get("option_id")
    refs = {modal["decision_ref"]} if modal else set()
    for e in _new_choice_effects(spell, option):
        for field in ("target", "targets", "destination"):
            if isinstance(e.get(field), dict) and isinstance(e[field].get("decision_ref"), str):
                refs.add(e[field]["decision_ref"])
    return refs


def _new_choices_possible(state: dict[str, Any], spell: dict[str, Any], entry: dict[str, Any], chooser: str) -> bool:
    """Core 753.2 (10-09 text): is there a legal set of new choices at all? Some mode (the one chosen, for a spell with
    none) whose every target has a legal object for the new controller - at the facedown battlefield where that binds -
    and every Move a legal destination. A Chain item with no choice at all has none to remake."""
    hidden_at = entry.get("played_from_hidden") if entry.get("hidden_targeting", "restricted") == "restricted" else None
    modal = spell.get("modal")
    options = [o["option_id"] for o in modal["options"]] if modal else [None]
    board_objects = [o for o in state.get("objects") or {} if find_location(state, o) is not None
                     and find_location(state, o)[0] in {"battlefield", "base"}]
    for option in options:
        effects = _new_choice_effects(spell, option)
        targets = [e[f] for e in effects for f in ("target", "targets")
                   if isinstance(e.get(f), dict) and isinstance(e[f].get("decision_ref"), str)]
        moves = [e for e in effects if isinstance(e.get("destination"), dict)
                 and isinstance(e["destination"].get("decision_ref"), str)]
        if not modal and not targets and not moves:
            return False
        chosen = {}
        for selector in targets:
            plain = {k: v for k, v in selector.items() if k != "decision_ref"}
            found = [o for o in board_objects if _new_target_legal(state, plain, o, chooser, hidden_at)[0]]
            if not found:
                break
            chosen[selector["decision_ref"]] = found[0]
        else:
            if all(move_destination_candidates(state, chosen.get(((m.get("target") or {}).get("decision_ref"))), m["destination"])
                   for m in moves if chosen.get(((m.get("target") or {}).get("decision_ref"))) is not None):
                return True
    return False


def _remove_from_location(state: dict[str, Any], object_id: str) -> None:
    location = find_location(state, object_id)
    if location is None:
        raise ValueError(f"object {object_id!r} has no location")
    if location[0] == "player":
        state["players"][location[1]]["zones"][location[2]].remove(object_id)
    elif location[0] == "chain":
        del state["chain_items"][location[1]]
    elif location[0] == "facedown":
        zone = state["battlefields"][location[1]]["facedown"]
        zone["cards"] = [c for c in zone["cards"] if c["object_id"] != object_id]
    else:
        state["battlefields"][location[1]]["objects"].remove(object_id)


def replacement_active(state: dict[str, Any], replacement: dict[str, Any]) -> bool:
    """Source-backed: the source is on the board. Granted: the target still
    exists on the board with the identity it had when granted (ADR-0007 §12);
    a used-up granted replacement is gone."""
    if "created" in replacement:
        # package 9: an effect's replacement for this turn - active on that turn only
        return replacement["created"].get("turn_id") == state.get("turn_id", DEFAULT_TURN_ID)
    if "granted" in replacement:
        grant = replacement["granted"]
        target = grant["target_object"]
        if replacement.get("uses_remaining") == 0:
            return False
        if grant.get("duration") == "this_turn" and grant.get("turn_id") != state.get("turn_id", DEFAULT_TURN_ID):
            return False
        return (target in state["objects"] and zone_class(find_location(state, target)) == "board"
                and object_identity(state, target) == grant["target_identity"])
    # Core 828.1.c is deliberately NOT read here: an Empowered Ability that is
    # switched off is still there, and pruning would delete it for good, so
    # re-Empowering could never bring it back. The matcher reads the status.
    return replacement_source_present(state, replacement["source_object"])


def replacement_source_present(state: dict[str, Any], source: str | None) -> bool:
    """Where a source-backed Replacement Effect's source must be for it to work: on the board - or, a Legend's own (package
    10, Sett - The Boss), in its controller's Legend Zone, where a Legend's abilities work (Core 107.4)."""
    location = find_location(state, source) if source in state.get("objects", {}) else None
    if zone_class(location) == "board":
        return True
    return (location is not None and location[0] == "player" and location[2] == "legend_zone"
            and state["objects"][source].get("kind") == "legend")


# 2026-10-15 package 13 (C2): a card's own Replacement Effect, printed on the object as a template; the fields a
# materialized entry takes from where it is
PRINTED_REPLACEMENT_BOUND = ("replacement_id", "controller", "source_object")


def printed_replacement_id(object_id: str, index: int) -> str:
    return f"{object_id}:printed:{index}"


def materialize_printed_replacements(state: dict[str, Any]) -> list[str]:
    """Each object's printed_replacements, added to replacement_effects while the object is where its abilities work
    (replacement_source_present) and not already there - its controller the object's, its own references to itself
    bound. Pruning removes it when the object leaves; a card that enters again gets a fresh one (Core 124). Returns the
    ids added."""
    present = {r.get("replacement_id") for r in state.get("replacement_effects") or []}
    added = []
    for object_id in sorted(state.get("objects") or {}):
        obj = state["objects"][object_id]
        templates = obj.get("printed_replacements") or []
        if not templates or not replacement_source_present(state, object_id):
            continue
        for index, template in enumerate(templates):
            replacement_id = printed_replacement_id(object_id, index)
            if replacement_id in present:
                continue
            entry = _bind_source_object(copy.deepcopy(template), object_id)
            entry.update(replacement_id=replacement_id, controller=obj["controller"], source_object=object_id)
            state.setdefault("replacement_effects", []).append(entry)
            added.append(replacement_id)
    return added


def _bind_source_object(value: Any, object_id: str) -> Any:
    if isinstance(value, dict):
        return {k: _bind_source_object(v, object_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_bind_source_object(v, object_id) for v in value]
    return object_id if value == "$source_object" else value


def _prune_inactive_replacements(state: dict[str, Any]) -> list[str]:
    removed = []
    active = []
    for replacement in state["replacement_effects"]:
        if replacement_active(state, replacement):
            active.append(replacement)
        else:
            removed.append(replacement["replacement_id"])
    state["replacement_effects"] = active
    return removed


def _is_zero_magnitude(state: dict[str, Any], effect: dict[str, Any]) -> bool:
    """Whether this effect would change nothing at all, so that Core 370.1.a
    leaves no event behind. Two cases the rules name:

      * a Might change whose amount is floored or capped away - Stupefy's
        "-1 Might, to a minimum of 1" on a 1 Might Unit moves nothing;
      * a Stun on a Unit that is already Stunned (423.2), which the stun op
        itself already reports as a no_op.
    """
    op = effect.get("op")
    object_id = effect.get("object_id")
    obj = state["objects"].get(object_id) if object_id is not None else None
    if obj is None:
        return False
    if op == "stun":
        return bool(obj.get("stunned"))
    if op == "modify_might":
        amount = effect.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool):
            return False
        return _floored_might_amount(effective_might(state, object_id), amount, effect) == 0
    return False


def _bound(effect: dict[str, Any], name: str) -> int | None:
    value = effect.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _floored_might_amount(current: int, amount: int, effect: dict[str, Any]) -> int:
    """How much a Might change actually moves, after the card's own floor or cap.

    "Give a Unit -1 Might, to a minimum of 1" moves nothing on a 1 Might Unit,
    and Core 370.1.a leaves no event where nothing moved. A floor limits a
    decrease and a cap an increase; neither turns the change around - a Unit
    already at 0 given "-8, to a minimum of 1" stays at 0 (GPT 2026-10-02)."""
    return _bounded_amount(current, amount, _bound(effect, "minimum"), _bound(effect, "maximum"))


def _bounded_amount(current: int, amount: int, minimum: int | None, maximum: int | None) -> int:
    """The part of `amount` a floor / cap lets through: a decrease stops at the floor (never below 0 moved), an
    increase stops at the cap (never above 0 moved). The direction of the change is never reversed."""
    if minimum is not None and amount < 0 and current + amount < minimum:
        amount = min(0, minimum - current)
    if maximum is not None and amount > 0 and current + amount > maximum:
        amount = max(0, maximum - current)
    return amount


def _applicable_replacements(state: dict[str, Any], effect: dict[str, Any],
                             applied: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """`applied` is the sequence memory of Core 370.2: one Replacement Effect never
    applies twice to the same event, nor to an event that replaced it."""
    object_id = effect.get("object_id")
    obj = state["objects"].get(object_id) if object_id is not None else None
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    applicable = []
    for replacement in state["replacement_effects"]:
        if replacement["event_op"] != effect.get("op"):
            continue
        if replacement["uses_remaining"] == 0:
            continue
        if replacement["replacement_id"] in applied:
            continue
        per_turn = replacement.get("uses_per_turn")
        if per_turn is not None and int((replacement.get("applied_this_turn") or {}).get(turn_id, 0)) >= per_turn:
            continue
        condition = replacement.get("condition")
        if condition is not None:
            try:
                if not evaluate_condition(state, condition, controller=replacement["controller"], object_id=object_id,
                                          perspective=replacement["controller"]):
                    continue
            except ConditionUnsupported:
                raise
        if replacement["mode"] == "reduce_damage" and replacement.get("prevent_remaining", 0) <= 0:
            continue
        if "granted" in replacement and not replacement_active(state, replacement):
            continue
        # Core 828.1.b.1, 828.1.c: "[Empowered][>] …" grants its text only while
        # the card has the Empowered status, so the ability is switched
        # off the moment the source is Disempowered - and on again if it is
        # Empowered anew, which is why this is read here and not at pruning.
        if replacement.get(DEPENDENT_ON_EMPOWERED_FIELD):
            source_obj = state["objects"].get(replacement.get("source_object"))
            if not (source_obj or {}).get("empowered"):
                continue
        # Core 355.6: it must have been this effect that chose the object.
        if replacement.get(REQUIRES_CHOSEN_FIELD) and effect.get(CHOSEN_FIELD) is not True:
            continue
        # Core 370.1.a: no change, no event, nothing to replace.
        if _is_zero_magnitude(state, effect):
            continue
        # Core 477: "would give me -Might" answers to a decrease, not to every
        # Might change. The sign that counts is the one after the card's own
        # floor, since that is what actually moves.
        direction = replacement.get(MIGHT_DIRECTION_FIELD)
        if direction is not None:
            amount = effect.get("amount")
            if not isinstance(amount, int) or isinstance(amount, bool) or obj is None:
                continue
            moved = _floored_might_amount(effective_might(state, object_id), amount, effect)
            if (moved < 0) != (direction == "decrease"):
                continue
        required_object = replacement.get("target_object_id")
        if required_object is not None and required_object != object_id:
            continue
        sources = replacement.get("damage_sources")
        if sources is not None and (effect.get("source_kind") == "unit" or effect.get("combat")):
            # package 9 (Core 417.6.b.3, 417.6.c): a Deal whose source is a Unit - named by the spell, or assigned in
            # combat - is not the spell's or ability's damage; only a Deal the game effect itself makes is (417.6.a)
            continue
        if "created" in replacement and not replacement_active(state, replacement):
            continue
        relation = replacement.get("target_controller_relation")
        if relation is not None:
            if obj is None:
                continue
            friendly = obj.get("controller") == replacement["controller"]
            if relation == "friendly" and not friendly:
                continue
            if relation == "enemy" and friendly:
                continue
        # package 10 (Sett - The Boss, Unlicensed Armory): "you may pay X to ... instead" - a cost its controller cannot
        # pay now is no option to choose (Core 370.1, 356.1): the replacement does not apply to this event
        if "cost" in replacement and replacement_cost_unpayable(state, replacement) is not None:
            continue
        applicable.append(replacement)
    return applicable


# 2026-10-08 package 10 (Sett - The Boss: "you may pay [A] and exhaust me to ... instead"; Unlicensed Armory: "you may pay
# [Fury] to ... instead"): an OPTIONAL Replacement Effect whose application costs something, paid by its controller as it
# applies - Power of a Domain, Power of any Domain, exhausting its own source. Declined, nothing is paid; unpayable now,
# it is no option at all. Power of any Domain is taken from the one Domain that can pay it; with more than one, which
# is the payer's choice, and is not modelled here (refused by name: replacement_cost_domain_choice_unsupported)
REPLACEMENT_COST_FIELDS = {"power", "power_any", "exhaust_source"}
REPLACEMENT_COST_DOMAINS = {"fury", "calm", "mind", "body", "chaos", "order"}


def replacement_cost_errors(replacement: dict[str, Any], source_backed: bool) -> list[str]:
    cost = replacement.get("cost")
    errors = []
    if not isinstance(cost, dict) or not cost or set(cost) - REPLACEMENT_COST_FIELDS:
        return [f"cost is {{power?: {{domain: n}}, power_any?: n, exhaust_source?: true}} (Core 356.1)"]
    if replacement.get("optional") is not True:
        errors.append("cost: only an optional replacement ('you may pay ... instead') carries a cost")
    power = cost.get("power")
    if power is not None and (not isinstance(power, dict) or not power or any(
            d not in REPLACEMENT_COST_DOMAINS or not isinstance(n, int) or isinstance(n, bool) or n < 1 for d, n in power.items())):
        errors.append("cost.power maps Domains to positive amounts")
    if "power_any" in cost and (not isinstance(cost["power_any"], int) or isinstance(cost["power_any"], bool)
                                or cost["power_any"] < 1):
        errors.append("cost.power_any is a positive amount")
    if "exhaust_source" in cost and (cost["exhaust_source"] is not True or not source_backed):
        errors.append("cost.exhaust_source is true, on a source-backed replacement ('exhaust me')")
    return errors


def replacement_cost_unpayable(state: dict[str, Any], replacement: dict[str, Any]) -> str | None:
    """Why the replacement's cost cannot be paid now, or None."""
    cost = replacement.get("cost") or {}
    pool = (state["players"].get(replacement["controller"]) or {}).get("resources") or {}
    power = dict(pool.get("power") or {})
    for domain, amount in (cost.get("power") or {}).items():
        if power.get(domain, 0) < amount:
            return f"{amount} {domain} Power"
        power[domain] -= amount
    if cost.get("power_any") and sum(power.values()) < cost["power_any"]:
        return f"{cost['power_any']} Power of any Domain"
    if cost.get("exhaust_source"):
        source = replacement.get("source_object")
        if source not in state["objects"] or state["objects"][source].get("exhausted") \
                or not replacement_source_present(state, source):
            return "its source, ready on the board (a Legend: in its Legend Zone), to exhaust"
    return None


def pay_replacement_cost(state: dict[str, Any], replacement: dict[str, Any]) -> dict[str, Any]:
    """Pay the cost into `state` (changed in place); what was paid."""
    cost = replacement.get("cost") or {}
    pool = state["players"][replacement["controller"]].setdefault("resources", {"energy": 0, "power": {}})
    power = pool.setdefault("power", {})
    paid: dict[str, int] = {}
    for domain, amount in (cost.get("power") or {}).items():
        power[domain] -= amount
        paid[domain] = paid.get(domain, 0) + amount
    if cost.get("power_any"):
        able = [d for d, n in power.items() if n >= cost["power_any"]]
        if len([d for d, n in power.items() if n > 0]) != 1 or len(able) != 1:
            raise NotImplementedError("replacement_cost_domain_choice_unsupported: the Power of any Domain this "
                                      "replacement costs could come from more than one Domain - the payer's choice, "
                                      "not modelled")
        power[able[0]] -= cost["power_any"]
        paid[able[0]] = paid.get(able[0], 0) + cost["power_any"]
    receipt = {"power": paid}
    if cost.get("exhaust_source"):
        state["objects"][replacement["source_object"]]["exhausted"] = True
        receipt["exhausted"] = replacement["source_object"]
    return receipt


REPLACEMENT_BINDINGS = ("$affected", "$source", "$affected_identity")


def _bind_replacement_effects(effects: list[dict[str, Any]], affected: str | None, source: str | None,
                             affected_identity: str | None = None) -> list[dict[str, Any]]:
    """C-56 (ADR-0014 §3): a Replacement Effect's instructions say "it" and
    "me". `$affected` is the object the replaced event was acting on and
    `$source` the Replacement Effect's own source; a binding the event cannot
    supply is a program the engine refuses rather than half-substitutes.

    Round H adds `$affected_identity`: the identity the subject had when the
    replacement applied (Core 359.3.e.4). Instructions that name the subject
    carry it as their bound_identity, so "heal that unit" cannot land on some
    other object that happens to hold the same id later in the resolution."""
    bound = {"$affected": affected, "$source": source, "$affected_identity": affected_identity}

    def substitute(value: Any, path: str) -> Any:
        if isinstance(value, str) and value in REPLACEMENT_BINDINGS:
            if bound[value] is None:
                raise IllegalOperation(f"{path} names {value}, which this event does not bind")
            return bound[value]
        if isinstance(value, dict):
            return {key: substitute(item, f"{path}.{key}") for key, item in value.items()}
        if isinstance(value, list):
            return [substitute(item, f"{path}[{index}]") for index, item in enumerate(value)]
        return value

    return [substitute(effect, f"replacement_effects[{index}]") for index, effect in enumerate(effects)]


def _inherit_event_modifiers(original_effect: dict[str, Any], replacement_effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the bounded Core 375 modifier vocabulary to compatible child events."""
    inherited = original_effect.get("event_modifiers")
    children = copy.deepcopy(replacement_effects)
    if not inherited:
        return children
    for child in children:
        if child.get("op") != "play_token":
            continue
        applicable: dict[str, Any] = {}
        if "entry_state" in inherited:
            applicable["entry_state"] = inherited["entry_state"]
        inherited_keywords = inherited.get("result_keywords", [])
        if child.get("token_kind") == "unit" and inherited_keywords:
            applicable["result_keywords"] = copy.deepcopy(inherited_keywords)
        if not applicable:
            continue
        existing = child.get("event_modifiers", {})
        for key, value in applicable.items():
            if key in existing and existing[key] != value:
                raise NotImplementedError(f"conflicting inherited event modifier {key!r}")
        child["event_modifiers"] = {**applicable, **copy.deepcopy(existing)}
        child["modifier_inheritance"] = {"rule": "Core 375", "from_effect_id": original_effect.get("effect_id")}
    return children


def _select_replacement(state: dict[str, Any], effect: dict[str, Any],
                        applied: frozenset[str] = frozenset()) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    applicable = _applicable_replacements(state, effect, applied)
    if not applicable:
        return None
    ids = [replacement["replacement_id"] for replacement in applicable]
    supplied_order = effect.get("replacement_order")
    if len(applicable) > 1:
        object_id = effect.get("object_id")
        affected_controller = state["objects"].get(object_id, {}).get("controller") if object_id is not None else None
        if affected_controller is None or effect.get("replacement_decider") != affected_controller:
            raise ReplacementDecisionRequired("the affected object's controller must decide replacement order", ids)
        if not isinstance(supplied_order, list) or len(supplied_order) != len(set(supplied_order)) or set(supplied_order) != set(ids):
            raise ReplacementDecisionRequired("affected controller must order all applicable replacement effects", ids)
        by_id = {replacement["replacement_id"]: replacement for replacement in applicable}
        applicable = [by_id[replacement_id] for replacement_id in supplied_order]
    choices = effect.get("replacement_choices", {})
    if not isinstance(choices, dict):
        raise ValueError("replacement_choices must be an object")
    for replacement in applicable:
        replacement_id = replacement["replacement_id"]
        if replacement["optional"]:
            if replacement_id not in choices or not isinstance(choices[replacement_id], bool):
                raise ReplacementDecisionRequired("optional replacement requires an explicit apply/decline choice", [replacement_id])
            if choices[replacement_id] is False:
                continue
        new_state = copy.deepcopy(state)
        stored = next(item for item in new_state["replacement_effects"] if item["replacement_id"] == replacement_id)
        cost_paid = pay_replacement_cost(new_state, replacement) if "cost" in replacement else None
        if stored["uses_remaining"] is not None:
            stored["uses_remaining"] -= 1
        if stored.get("uses_per_turn") is not None:
            # Core 372: the use is spent when the Replacement Effect is
            # actually applied; declining above never reaches here.
            turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
            ledger = stored.setdefault("applied_this_turn", {})
            ledger[turn_id] = int(ledger.get(turn_id, 0)) + 1
        outcome = {
            "prevent_event": "replaced_prevented",
            "replace_with": "replaced_with",
            "augment_with": "augmented_with",
            "reduce_damage": "replaced_modified",
        }[replacement["mode"]]
        return new_state, {
            "op": effect["op"],
            "outcome": outcome,
            "replacement_id": replacement_id,
            "affected_object_id": effect.get("object_id"),
            **({"replacement_cost_paid": cost_paid} if cost_paid is not None else {}),
            "rule_locators": ["Core 367–375", "Core 370.1.b–370.2"] + (["Core 443"] if replacement["mode"] == "prevent_event" else []),
        }, copy.deepcopy(replacement)
    return None


def _burn_out_bound(state: dict[str, Any], player_id: str, victory_score: int) -> int:
    """ADR-0010 §2 (Codex review-fix): a provable bound on repeated Burn Outs
    with an empty Trash. The Burning Out player may hand the points to any
    opponent in any order, so the worst legal sequence lifts every opponent
    to the target — the Victory Score or the current top score, whichever is
    higher — before one of them takes a strict lead: the sum of every
    opponent's gap plus one. Exceeding it without an immediate winner is a
    contradiction."""
    points = {p: int(pl.get("points", 0)) for p, pl in state["players"].items()}
    target = max(victory_score, max(points.values()))
    bound = sum(max(0, target - v) for p, v in points.items() if p != player_id) + 1
    return max(bound, 1)


def perform_draw(state: dict[str, Any], player_id: str, count: int, *, decisions: dict[str, Any] | None = None, operation_prefix: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Core 413.4 / 431: draw as many as possible; when the Main Deck runs out,
    Burn Out — Recycle the Trash in the order of an external randomization
    receipt (431.2.b; missing → ExternalInputRequired), one opponent gains a
    point (431.2.c; automatic with exactly one opponent, else a
    player_selection), then draw the remainder (431.2.d). With an empty Trash
    each further attempt Burns Out again (431.3); from the second Burn Out of
    the sequence a beneficiary at or above the Victory Score with a strict
    lead wins at once (431.3.c–431.3.c.1) and the event carries a
    terminal_event for the caller's two-state commit. Returns (state, event)."""
    import engine_decisions as ed
    if player_id not in state["players"] or not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("draw requires a known player and positive count")
    new_state = copy.deepcopy(state)
    player = new_state["players"][player_id]
    deck, trash, hand = player["zones"]["main_deck"], player["zones"]["trash"], player["zones"]["hand"]
    turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
    prefix = operation_prefix or f"burn_out:{player_id}:{turn_id}"
    mode = new_state.get("mode") if isinstance(new_state.get("mode"), dict) else {}
    victory_score = mode.get("victory_score") if isinstance(mode.get("victory_score"), int) else None
    opponents = sorted(p for p in new_state["players"] if p != player_id)
    drawn: list[str] = []
    burn_outs: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    bound: int | None = None
    remaining = count
    while remaining > 0:
        if deck:
            card = deck.pop(0)
            hand.append(card)
            _bump_identity(new_state, card)
            drawn.append(card)
            remaining -= 1
            continue
        # 431.1.a: the deck is short — Burn Out, then complete the draw.
        sequence = len(burn_outs) + 1
        operation_id = f"{prefix}:{sequence}"
        if mode.get("teams") or any(isinstance(pl, dict) and pl.get("team_id") for pl in new_state["players"].values()):
            raise NotImplementedError("a Burn Out with teammates (431.2.c, 489.8.d) is not modelled")
        recycled: list[str] = []
        receipt_id = None
        provenance = None
        if trash:
            receipt = ed.randomization_receipt(decisions, operation_id)
            if receipt is None:
                raise ExternalInputRequired(f"{player_id} Burns Out: the Trash is recycled into the Main Deck in a randomized order (431.2.b) that must arrive as a randomization receipt for {operation_id}", [operation_id], None,
                                            chance={"operation": "recycle_trash", "operation_id": operation_id, "player": player_id,
                                                    "permute": list(trash)})
            from randomization_receipt import permutation_matches
            problem = permutation_matches(receipt, trash)
            if problem is not None or receipt.get("player") != player_id:
                raise ValueError(problem or f"receipt {receipt['receipt_id']} names {receipt.get('player')!r}, not the Burning Out player {player_id!r}")
            recycled = list(receipt["permutation"])
            deck[:] = recycled
            trash.clear()
            for card in recycled:
                _bump_identity(new_state, card)  # 124: a new object on the way back to the deck
            receipt_id, provenance = receipt["receipt_id"], dict(receipt["provenance"])
        if len(opponents) == 1:
            beneficiary, chosen_by = opponents[0], "sole_opponent"
        else:
            decision_id = f"{prefix}:beneficiary:{sequence}"
            entry = ed.player_selection(decisions, decision_id)
            if entry is None:
                raise PlayerSelectionRequired(f"{player_id} Burns Out and chooses an opponent to gain 1 point (431.2.c): decision {decision_id}", [decision_id], player_id)
            if entry["controller"] != player_id:
                raise IllegalDecision(f"player selection {decision_id!r} was made by {entry['controller']!r}, not the Burning Out player")
            if entry["value"] not in opponents:
                raise ValueError(f"player selection {decision_id!r} names {entry['value']!r}, who is not an opponent of {player_id}")
            beneficiary, chosen_by = entry["value"], "player_selection"
        new_state["players"][beneficiary]["points"] = int(new_state["players"][beneficiary].get("points", 0)) + 1
        record = {"operation_id": operation_id, "sequence": sequence, "recycled": recycled, "receipt_id": receipt_id, "provenance": provenance,
                  "beneficiary": beneficiary, "chosen_by": chosen_by, "points_after": new_state["players"][beneficiary]["points"], "immediate_victory": False,
                  "rule_locators": ["Core 431.1.a", "Core 431.2", "Core 431.2.a", "Core 431.2.b", "Core 431.2.c", "Core 431.2.d", "Core 194.1.d"]}
        if not deck and victory_score is not None and bound is None:
            bound = _burn_out_bound(state, player_id, victory_score)
        if sequence >= 2:
            # 431.3.c: from the second Burn Out of one sequence, reaching the
            # Victory Score with a strict lead wins immediately (431.3.c.1).
            if victory_score is None:
                raise NotImplementedError("a repeated Burn Out (431.3) needs the Mode of Play's Victory Score to judge the immediate win (431.3.c); none is in the state")
            points = {p: int(pl.get("points", 0)) for p, pl in new_state["players"].items()}
            if points[beneficiary] >= victory_score and all(points[beneficiary] > v for p, v in points.items() if p != beneficiary):
                record["immediate_victory"] = True
                record["rule_locators"] += ["Core 431.3", "Core 431.3.a", "Core 431.3.b", "Core 431.3.c", "Core 431.3.c.1"]
                terminal = {"kind": "terminal_event", "reason": "burn_out_victory", "winner": beneficiary, "immediate": True, "source": operation_id,
                            "rule_locators": ["Core 431.3.c", "Core 431.3.c.1", "Core 196"]}
            elif not deck:
                if sequence > bound:
                    raise ValueError(f"{sequence} Burn Outs without an immediate winner exceed the provable bound {bound}; the state is contradictory")
        burn_outs.append(record)
        if terminal is not None:
            break
    event: dict[str, Any] = {"op": "draw", "outcome": "applied", "objects": drawn, "identities_after": {c: object_identity(new_state, c) for c in drawn},
                             "requested": count, "drawn": len(drawn), "burn_outs": burn_outs, "terminal_event": terminal, "loop_bound": bound,
                             "skipped_after_terminal": remaining if terminal is not None else 0,
                             "completion": "full" if remaining == 0 else ("partial" if drawn else "none"),
                             "rule_locators": list(dict.fromkeys(OP_RULES["draw"] + ["Core 124"] + [loc for b in burn_outs for loc in b["rule_locators"]]))}
    return new_state, event


def attachments(state: dict[str, Any], object_id: str) -> list[str]:
    """The cards attached to `object_id`, which is their Top-Most card (434.1.b)."""
    return sorted(other for other, obj in state["objects"].items() if obj.get("attached_to") == object_id)


def _last_board_location(location: tuple[str, str, str | None] | None) -> dict[str, Any] | None:
    if location is None:
        return None
    if location[0] == "battlefield":
        return {"kind": "battlefield", "battlefield": location[1]}
    if location[0] == "player" and location[2] == "base":
        return {"kind": "base", "player": location[1]}
    return None


def _place_on_board(state: dict[str, Any], object_id: str, destination: dict[str, Any]) -> str:
    if destination["kind"] == "battlefield":
        state["battlefields"][destination["battlefield"]]["objects"].append(object_id)
        return f"battlefield:{destination['battlefield']}"
    state["players"][destination["player"]]["zones"]["base"].append(object_id)
    return f"base:{destination['player']}"


def detach_records(state: dict[str, Any], host_id: str, host_location: dict[str, Any] | None, *, host_left_board: bool) -> list[dict[str, Any]]:
    """Core 435.4: a detached card's location is its Top-Most card's. When the
    host left the board for a non-board zone, that is the last board location
    the host occupied (435.4.b). A detached Gear that would then sit at a
    Battlefield is Recalled by the next Cleanup (435.4.a) — recorded, not moved
    early, because that Cleanup step is not modelled yet."""
    records: list[dict[str, Any]] = []
    # 2026-09-25 (GPT): the leaving object may itself be an ATTACHED card (a Gear killed by
    # "Kill all gear"). Every op that sends a board object to a non-board zone calls this for
    # that object, so the link is cut here, once: it ceases to be attached (435.1.b), its Top-
    # Most card loses its appended Effect Text (435.1.d) and its Might Bonus (435.1.e - read
    # through attachments(), which no longer lists it). It stays where the op sends it.
    leaving = state["objects"].get(host_id) or {}
    if host_left_board and leaving.get("attached_to") is not None:
        former = leaving.pop("attached_to")
        leaving.pop("pending_recall", None)
        own = {"object_id": host_id, "detached_from": former, "attached_card_left_board": True,
               "rule_locators": ["Core 435.1.b", "Core 435.1.d", "Core 435.1.e"]}
        appended_id = f"effect_text:{host_id}:{former}"
        if any(e["effect_id"] == appended_id for e in state.get("continuous_effects", []) or []):
            state["continuous_effects"] = [e for e in state["continuous_effects"] if e["effect_id"] != appended_id]
            own["removed_effect_text"] = appended_id
        records.append(own)
    for attached_id in attachments(state, host_id):
        obj = state["objects"][attached_id]
        record = {"object_id": attached_id, "detached_from": host_id, "host_left_board": host_left_board}
        del obj["attached_to"]
        # Core 477.2 / 435.4: the appended Effect Text goes with the link.
        appended_id = f"effect_text:{attached_id}:{host_id}"
        if any(e["effect_id"] == appended_id for e in state.get("continuous_effects", []) or []):
            state["continuous_effects"] = [e for e in state["continuous_effects"] if e["effect_id"] != appended_id]
            record["removed_effect_text"] = appended_id
        if host_location is None:
            # A host that was never on the board leaves nothing to derive from.
            record.update({"destination": None, "unsupported": "detach_destination_unknown"})
            records.append(record)
            continue
        _remove_from_location(state, attached_id)
        record["destination"] = _place_on_board(state, attached_id, host_location)
        record["rule_locators"] = ["Core 435.4"] + (["Core 435.4.b"] if host_left_board else [])
        if obj.get("kind") == "gear" and host_location["kind"] == "battlefield":
            obj["pending_recall"] = {"reason": "detached_gear_at_battlefield", "battlefield": host_location["battlefield"]}
            record["pending_recall"] = dict(obj["pending_recall"])
            record["rule_locators"] = record["rule_locators"] + ["Core 435.4.a"]
        records.append(record)
    return records


def _ids_hash(state: dict[str, Any], ids: list[str]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps([[i, object_identity(state, i)] for i in ids], separators=(",", ":")).encode("utf-8")).hexdigest()


def _mark_reveals(state: dict[str, Any], player_id: str, zone: str, ids: list[str], visible_to: Any, session: str, kind: str) -> list[str]:
    """Mark cards as looked at / revealed for this program (424.3.a). Cards
    stay where they are, in order (424.2)."""
    marks = state.setdefault("reveals", [])
    for object_id in ids:
        existing = next((m for m in marks if m["object_id"] == object_id), None)
        if existing is not None:
            if visible_to == "all":
                existing["visible_to"] = "all"
            elif existing["visible_to"] != "all":
                existing["visible_to"] = list(dict.fromkeys(existing["visible_to"] + list(visible_to)))
            continue
        marks.append({"object_id": object_id, "identity": object_identity(state, object_id) or f"{object_id}@0", "zone": zone, "visible_to": visible_to if visible_to == "all" else list(visible_to), "session": session, "kind": kind})
    return list(ids)


def _session_cards(state: dict[str, Any], player_id: str, zone: str) -> list[str]:
    """The marked cards of this player's zone, in the zone's order."""
    marked = {m["object_id"] for m in state.get("reveals", []) if m["zone"] == zone}
    return [c for c in state["players"][player_id]["zones"][zone] if c in marked]


def _drop_reveals(state: dict[str, Any], ids: list[str]) -> None:
    if state.get("reveals"):
        state["reveals"] = [m for m in state["reveals"] if m["object_id"] not in set(ids)]
        if not state["reveals"]:
            del state["reveals"]


def _reorder_deck(state: dict[str, Any], player_id: str, order: list[str], position: str) -> None:
    deck = state["players"][player_id]["zones"]["main_deck"]
    rest = [c for c in deck if c not in set(order)]
    state["players"][player_id]["zones"]["main_deck"] = (list(order) + rest) if position == "top" else (rest + list(order))


def _recycle_batch(state: dict[str, Any], ids: list[str], player_id: str | None, decisions: dict[str, Any] | None, order_ref: str, session: str, choice_session: dict[str, Any] | None = None,
                   per_deck_refs: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Core 416: Recycle several cards as one Game Action (303.2) — each to its
    owner's Main Deck or Rune Deck bottom (416.1–416.2). Two or more to the same
    Main Deck go in a RANDOM order (416.5), which arrives as a randomization
    receipt for `order_ref` naming that owner (ADR-0010 §2) - no player orders
    them; two or more to the same Rune Deck go in the order of their OWNER's
    choosing (416.5.a), whoever was told to recycle. Tokens cease to exist.

    `per_deck_refs` (package 6, "Recycle the rest" over every player's cards): several decks may each
    take two or more cards, so each deck gets its OWN operation or decision (order_ref:<owner>.<deck>):
    a Main Deck its own randomization receipt, a Rune Deck its owner's own ordering."""
    import engine_decisions as ed
    order_used = None
    orders_used: list[dict[str, Any]] = []
    per_deck: dict[tuple[str, str], list[str]] = {}
    for object_id in ids:
        obj = state["objects"][object_id]
        if not obj.get("is_token"):
            per_deck.setdefault((obj["owner"], "rune_deck" if obj["kind"] == "rune" else "main_deck"), []).append(object_id)
    ordered_ids = list(ids)
    for (owner, deck), group in per_deck.items():
        if len(group) < 2:
            continue
        if deck == "main_deck":
            operation_id = (f"{order_ref}:{owner}.{deck}" if per_deck_refs
                            else order_ref if len([k for k in per_deck if k[1] == "main_deck" and len(per_deck[k]) >= 2]) == 1
                            else f"{order_ref}:{owner}")
            receipt = ed.randomization_receipt(decisions, operation_id)
            if receipt is None:
                raise ExternalInputRequired(f"{len(group)} cards are recycled to {owner}'s Main Deck at once: they go to the bottom in a random order (Core 416.5), "
                                            f"which must arrive as a randomization receipt for {operation_id}", [operation_id], None,
                                            chance={"operation": "recycle_simultaneous", "operation_id": operation_id, "player": owner,
                                                    "permute": list(group)})
            from randomization_receipt import permutation_matches
            problem = permutation_matches(receipt, group)
            if problem is None and receipt.get("operation") != "recycle_simultaneous":
                problem = f"receipt {receipt['receipt_id']} is for {receipt.get('operation')!r}, not a simultaneous recycle (416.5)"
            if problem is not None or receipt.get("player") != owner:
                raise ValueError(problem or f"receipt {receipt['receipt_id']} names {receipt.get('player')!r}, not the Main Deck's owner {owner!r}")
            order = list(receipt["permutation"])
            order_used = {"randomization_receipt": receipt["receipt_id"], "operation_id": operation_id, "deck": f"{owner}.{deck}",
                          "rule_locators": ["Core 416.5"]}
        else:
            ref = f"{order_ref}:{owner}.{deck}" if per_deck_refs else order_ref
            spec = {"selection_kind": "ordered_permutation", "count": {"any_number": True}, "from": "revealed", "by": owner, "visibility": "private_to_chooser", "identity_binding": True}
            order, meta = resolve_choice(state, spec, decision_ref=ref, decisions=decisions, controller=owner, candidates=group, session=choice_session)
            order_used = {"decision_id": meta.get("decision_id"), "forced": meta["forced"], "deck": f"{owner}.{deck}", "rule_locators": ["Core 416.5.a"]}
        orders_used.append(order_used)
        ordered_ids = [c for c in ordered_ids if c not in set(group)] + list(order)
    identities: dict[str, str] = {}
    destinations: dict[str, str] = {}
    detached_all: list[dict[str, Any]] = []
    for object_id in ordered_ids:
        obj = state["objects"][object_id]
        source = find_location(state, object_id)
        detached_all.extend(detach_records(state, object_id, _last_board_location(source), host_left_board=True))
        _remove_from_location(state, object_id)
        if obj.get("is_token"):
            del state["objects"][object_id]
            destinations[object_id] = "ceased_to_exist"
            continue
        deck = "rune_deck" if obj["kind"] == "rune" else "main_deck"
        state["players"][obj["owner"]]["zones"][deck].append(object_id)
        destinations[object_id] = f"{obj['owner']}.{deck}.bottom"
        if source is not None and (source[0] == "battlefield" or (source[0] == "player" and source[2] != deck)):
            identities[object_id] = _bump_identity(state, object_id)
    _drop_reveals(state, ordered_ids)
    return state, {"objects_count": len(ids), "objects_hash": _ids_hash(state, [i for i in ordered_ids if i in state["objects"]]), "destinations": destinations,
                   **({"detached": detached_all} if detached_all else {}),
                   "identities_after": identities, "simultaneous": True, "order_decision": order_used,
                   **({"order_decisions": orders_used} if per_deck_refs else {}),
                   "completion": "full" if ids else "none"}


def _apply_one(state: dict[str, Any], effect: dict[str, Any], decisions: dict[str, Any] | None = None,
               controller: str | None = None, program_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    op = effect.get("op")
    if op not in SUPPORTED_OPS:
        raise NotImplementedError(f"unsupported effect op {op!r}")
    new_state = copy.deepcopy(state)
    trace: dict[str, Any] = {"op": op, "outcome": "applied", "rule_locators": OP_RULES[op]}

    if op == "draw":
        new_state, event = perform_draw(new_state, effect.get("player"), effect.get("count"), decisions=decisions, operation_prefix=effect.get("burn_out_operation_prefix"))
        trace.update(event)

    elif op == "recycle_one":
        object_id = effect.get("object_id")
        if object_id is None and (effect.get("selection_meta") or {}).get("empty"):
            trace.update({"outcome": "no_op", "completion": "none", "reason": "nothing to choose from (Core 359.3.e)", "selection": effect.get("selection_meta")})
            return new_state, trace
        if object_id not in new_state["objects"]:
            raise ValueError("recycle_one requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
        detached = detach_records(new_state, object_id, _last_board_location(source), host_left_board=True)
        if detached:
            trace["detached"] = detached
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 435.4", "Core 435.4.b"]))
        _remove_from_location(new_state, object_id)
        if obj.get("is_token"):
            del new_state["objects"][object_id]
            destination = "ceased_to_exist"
            trace.update({"object_id": object_id, "destination": destination})
            trace["rule_locators"] = ["Core 416", "Core 186.1"]
        else:
            destination = "rune_deck" if obj["kind"] == "rune" else "main_deck"
            new_state["players"][obj["owner"]]["zones"][destination].append(object_id)
            trace.update({"object_id": object_id, "destination": f"{obj['owner']}.{destination}.bottom"})
            source_zone = source[2] if source and source[0] == "player" else None
            if source is not None and (source[0] == "battlefield" or source_zone != destination):
                trace["identity_after"] = _bump_identity(new_state, object_id)
                trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 124"]))
        if effect.get("selection_meta") is not None:
            trace["selection"] = copy.deepcopy(effect["selection_meta"])  # ADR-0011 §1: which choice picked it

    elif op == "move_board_object":
        object_id, destination = effect.get("object_id"), effect.get("destination")
        if object_id not in new_state["objects"] or not isinstance(destination, dict):
            raise ValueError("move_board_object requires a known object and destination")
        if "decision_ref" in destination:
            # Charm: "Move an enemy unit." The player chooses where, from the
            # destinations this board actually offers.
            import engine_decisions as _ed
            candidates = move_destination_candidates(new_state, object_id, destination)
            entry = next((e for e in _ed.entries(decisions, kind="location_selection")
                          if e["decision_id"] == destination["decision_ref"]), None)
            if entry is None:
                raise LocationSelectionRequired(
                    f"a Move destination for {object_id!r} is required (Core 355.4)",
                    [destination["decision_ref"]], controller, candidates)
            if entry["controller"] != controller:
                raise IllegalDecision(f"location selection {destination['decision_ref']!r} was made by "
                                      f"{entry['controller']!r}, not the program controller")
            if entry["value"] not in candidates and entry.get("stage") in ("play_declaration", "trigger_finalization"):
                # GPT 2026-09-29, Core 355.4 / 355.15 / 359.3.e.9: a destination chosen as the card was played
                # or the ability finalized stands; if it is no longer a legal destination when the Move would
                # execute, that Move is not carried out - it is never re-chosen - and the rest of the program runs
                trace.update({"outcome": "skipped_illegal_destination", "completion": "none", "object_id": object_id,
                              "chosen_destination": entry["value"], "legal_destinations_now": list(candidates),
                              "reason": "move_destination_no_longer_legal",
                              "rule_locators": list(dict.fromkeys(trace["rule_locators"] + ["Core 355.4.a", "Core 355.15",
                                                                                            "Core 359.3.e.9"]))})
                return new_state, trace
            if entry["value"] not in candidates:
                raise ValueError(f"location selection {destination['decision_ref']!r} names "
                                 f"{entry['value']!r}; the legal Move destinations are {candidates}")
            kind, _, name = entry["value"].partition(":")
            destination = {"kind": kind, "battlefield": name} if kind == "battlefield" else {"kind": "base", "player": name}
        # Core 359.3.e.6, and the whole of DP-96: a spell may legally *choose*
        # a destination this Battlefield forbids. The choice stands; it is the
        # move instruction that cannot be carried out, so this one instruction
        # is negated (10-09 text; "ignored" in 07-16) and everything else in the
        # program still runs - an instruction linked to it as well (NEGATED_OUTCOMES).
        restriction = move_restricted(new_state, object_id, destination)
        if restriction is not None:
            trace.update({"outcome": "skipped_restricted_move", "completion": "none", "negated": True,
                          "object_id": object_id, "destination": destination,
                          "reason": restriction["reason_code"], "restriction": restriction["restriction"],
                          "restricted_by": restriction["battlefield"],
                          "rule_locators": list(dict.fromkeys(trace["rule_locators"] + restriction["rule_locators"]))})
            return new_state, trace
        source = find_location(new_state, object_id)
        if source is None or not (source[0] == "battlefield" or source[2] == "base"):
            raise ValueError("Move applies only between board locations")
        _remove_from_location(new_state, object_id)
        destination = dict(destination)
        if destination.get("kind") == "base" and destination.get("player_relation") == "object_controller":
            # "Move ... to base" names each unit's own controller's Base (Core
            # 355.4.a valid Location), not the spell controller's; resolved per
            # object so a 2v2 teammate's unit goes home, not to the caster.
            destination["player"] = new_state["objects"][object_id]["controller"]
        trace_contested = None
        if destination.get("kind") == "base" and destination.get("player") in new_state["players"]:
            new_state["players"][destination["player"]]["zones"]["base"].append(object_id)
            target = f"base:{destination['player']}"
        elif destination.get("kind") == "battlefield" and destination.get("battlefield") in new_state["battlefields"]:
            new_state["battlefields"][destination["battlefield"]]["objects"].append(object_id)
            target = f"battlefield:{destination['battlefield']}"
            if applier := apply_arrival_contested(new_state, destination["battlefield"], object_id):
                trace_contested = {"battlefield": destination["battlefield"], "applied_by": applier,
                                   "rule_locators": ["Core 190.3.a", "Core 190.3.a.1"]}
        else:
            raise ValueError("unknown board destination")
        carried = []
        for attached_id in attachments(new_state, object_id):
            # Core 434.4: an attached card's location is its Top-Most card's, so
            # it travels with it; the Move itself is the host's (383.1).
            _remove_from_location(new_state, attached_id)
            _place_on_board(new_state, attached_id, {"kind": "battlefield", "battlefield": destination["battlefield"]} if destination.get("kind") == "battlefield" else {"kind": "base", "player": destination["player"]})
            carried.append(attached_id)
        trace.update({"object_id": object_id, "from": source, "to": target, **({"carried_attachments": carried} if carried else {}),
                      **({"contested_applied": trace_contested} if trace_contested else {})})
        # ADR-0007 §10: only a completed Move raises "When I move" (383.1, 319.8);
        # Recall, return to hand and board entry are not Moves.
        moved = new_state["objects"][object_id]
        move_triggers = []
        for descriptor in object_triggers(new_state, object_id, "move_triggers"):
            if (descriptor.get("condition") or {}).get("kind") == "moved_to_battlefield" and destination.get("kind") != "battlefield":
                continue        # "When I move to a battlefield": a Move to a Base does not meet it
            copied = copy.deepcopy(descriptor)
            copied.pop("condition", None)
            copied.setdefault("trigger_kind", "triggered")
            copied["move"] = {"from": source, "to": target}
            # the mover's identity (a Move keeps it), so a program reading "here" or "me" is
            # bound to THIS object, as a play trigger's is (2026-09-24, Noxian Drummer)
            copied["source_identity"] = object_identity(new_state, object_id) or f"{object_id}@0"
            move_triggers.append(copied)
        if move_triggers:
            trace["pending_triggers"] = move_triggers

    elif op == "return_to_hand":
        # DP-06 / Q1: a zone change (446.2 — not a Move), so a new object (124)
        # that keeps nothing of the old one (124.1). Board or the owner's trash
        # only; a token entering a non-board zone ceases to exist (186.1).
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("return_to_hand requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
        on_board = source is not None and (source[0] == "battlefield" or source[2] == "base")
        detached = detach_records(new_state, object_id, _last_board_location(source), host_left_board=True) if on_board else []
        # package 11: noted before it moves (leave_board_triggers)
        leaving_triggers = leave_board_triggers(new_state, object_id) if on_board else []
        in_owner_trash = source == ("player", obj["owner"], "trash")
        # package 10 (Teemo - Swift Scout): "into your hand from your Champion Zone" - its owner's Champion Zone (Core 108.3)
        in_owner_champion_zone = source == ("player", obj["owner"], "champion_zone")
        # package 10 (Pack of Wonders): "a facedown card ... to its owner's hand" - out of a Facedown Zone (Core 107.3)
        facedown = source is not None and source[0] == "facedown"
        if not (on_board or in_owner_trash or in_owner_champion_zone or facedown):
            raise IllegalOperation(f"return_to_hand applies only to a board object, a facedown card, or a card in its "
                                   f"owner's trash or Champion Zone; {object_id!r} is at {source}")
        _remove_from_location(new_state, object_id)
        if obj.get("is_token"):
            del new_state["objects"][object_id]
            trace.update({"object_id": object_id, "from": source, "destination": "ceased_to_exist", "not_a_move": True})
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 186.1"]))
        else:
            obj["damage"] = 0
            obj["might_modifiers"] = []
            obj["exhausted"] = False
            for transient in ("statuses", "counters", "combat_designation"):
                obj.pop(transient, None)  # a new object carries no designation (124.1, 464.2.c.3)
            new_state["players"][obj["owner"]]["zones"]["hand"].append(object_id)
            trace.update({"object_id": object_id, "from": source, "destination": f"{obj['owner']}.hand",
                          "identity_after": _bump_identity(new_state, object_id), "not_a_move": True})
        if on_board:
            trace["disabled_replacements"] = _prune_inactive_replacements(new_state)
        if leaving_triggers:
            trace["pending_triggers"] = leaving_triggers
        if detached:
            trace["detached"] = detached  # Core 435.4.b: to the host's last board location
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 435.4", "Core 435.4.b"]))

    elif op == "return_to_champion_zone":
        # Core 103.2.a.3 / 108.3.c.1 (Hallowed Tomb, GPT 2026-09-27 ruling 15): a Chosen Champion from its
        # owner's trash to its owner's Champion Zone - only into an empty one, checked as this executes
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("return_to_champion_zone requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
        if source != ("player", obj["owner"], "trash"):
            raise IllegalOperation(f"return_to_champion_zone takes a card from its owner's trash; {object_id!r} is at {source}")
        zone = new_state["players"][obj["owner"]]["zones"].setdefault("champion_zone", [])
        if zone:
            trace.update({"outcome": "no_op", "object_id": object_id, "reason": "champion_zone_occupied",
                          "occupied_by": list(zone), "rule_locators": ["Core 108.3.c.1"]})
        else:
            _remove_from_location(new_state, object_id)
            obj["damage"] = 0
            obj["might_modifiers"] = []
            obj["exhausted"] = False
            for transient in ("statuses", "counters", "combat_designation"):
                obj.pop(transient, None)
            zone.append(object_id)
            trace.update({"object_id": object_id, "from": source, "destination": f"{obj['owner']}.champion_zone",
                          "identity_after": _bump_identity(new_state, object_id), "not_a_move": True})

    elif op == "gain_control_of_spell":
        # 2026-10-13 package 11 (Mystic Reversal, GPT ruling 13): the Chain item that card is changes controller - its
        # card too (Core 191.2); what was paid for it stays paid and moves nowhere; the choices it was played with are now
        # its new controller's; the timing chain follows in the same commit (resolution_bridge)
        card = effect.get("object_id")
        item_id = next((k for k, v in (new_state.get("chain_items") or {}).items() if v.get("card") == card), None)
        player = controller if effect.get("player") == "$controller" else effect.get("player")
        if item_id is None or player not in new_state["players"]:
            raise IllegalOperation(f"{card!r} is not a spell on the Chain, or {player!r} is no player (Core 191.2)")
        entry = new_state["chain_items"][item_id]
        before = entry["controller"]
        original = (entry.get("control_changed") or {}).get("from", before)
        entry["controller"] = player
        new_state["objects"][card]["controller"] = player
        if player != original:
            entry["control_changed"] = {"from": original, "to": player}
        else:
            entry.pop("control_changed", None)
        for made in entry.get("played_targets") or []:
            made["controller"] = player
        trace.update({"object_id": card, "chain_item_id": item_id, "controller_before": before, "controller_after": player,
                      "costs_transferred": False, "controlled_chain_items": [{"chain_item_id": item_id, "to": player}]})
        if before == player:
            trace["outcome"] = "no_op"

    elif op == "gain_control":
        # 2026-10-13 package 11 (Possession, GPT ruling 12): the permanent's controller becomes the player; its owner, its
        # place, damage, exhaustion, buff and modifiers stay (Core 189, 191.3); an ability of it already on the Chain keeps
        # its controller (191.4.b) - nothing on the Chain is touched. A Combat's designations follow its Cleanup (323.2)
        object_id = effect.get("object_id")
        player = controller if effect.get("player") == "$controller" else effect.get("player")
        if object_id not in new_state["objects"] or player not in new_state["players"]:
            raise ValueError("gain_control requires a known object and a known player")
        obj = new_state["objects"][object_id]
        if zone_class(find_location(new_state, object_id)) != "board" or obj["kind"] not in {"unit", "gear"}:
            raise IllegalOperation(f"gain_control takes a permanent on the board; {object_id!r} is not one")
        before = obj["controller"]
        obj["controller"] = player
        follow_controller(new_state, object_id, player)
        trace.update({"object_id": object_id, "controller_before": before, "controller_after": player,
                      "owner": obj["owner"], "retained": {"damage": obj["damage"], "exhausted": obj["exhausted"],
                                                         "buffed": bool(obj.get("buffed"))}})
        if before == player:
            trace["outcome"] = "no_op"

    elif op == "recall":
        # DP-06 / Q2: relocation to the current controller's Base (455); not a
        # Move (456.1), so Move triggers never fire; damage, exhaustion and
        # modifiers stay (458.1); the object is the same object.
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("recall requires a known object")
        obj = new_state["objects"][object_id]
        source = find_location(new_state, object_id)
        if source is None or not (source[0] == "battlefield" or source[2] == "base"):
            raise IllegalOperation(f"recall applies only to a board object; {object_id!r} is at {source}")
        controller = obj["controller"]
        retained = {"damage": obj["damage"], "exhausted": obj["exhausted"], "might_modifiers": len(obj.get("might_modifiers", []))}
        if source == ("player", controller, "base"):
            trace.update({"object_id": object_id, "from": source, "to": f"base:{controller}", "not_a_move": True, "retained": retained, "outcome": "no_op"})
        else:
            _remove_from_location(new_state, object_id)
            new_state["players"][controller]["zones"]["base"].append(object_id)
            trace.update({"object_id": object_id, "from": source, "to": f"base:{controller}", "not_a_move": True, "retained": retained,
                          "identity_after": object_identity(new_state, object_id)})

    elif op == "channel_rune":
        # DP-08 / Q3: top runes of the Rune Deck enter the board (430.1) with the
        # stated entry state (430.2, ready by default 430.2.a); as many as
        # possible when short (430.3); a non-board → board change, so new
        # objects (124). Not a Move; runes are not permanents.
        player_id, count = effect.get("player"), effect.get("count")
        entry_state = effect.get("entry_state", "ready")
        if player_id not in new_state["players"] or not isinstance(count, int) or count < 1:
            raise ValueError("channel_rune requires a known player and positive count")
        if entry_state not in {"ready", "exhausted"}:
            raise ValueError("channel_rune entry_state must be ready or exhausted")
        rune_deck = new_state["players"][player_id]["zones"]["rune_deck"]
        taken = rune_deck[:count]
        del rune_deck[:count]
        for rune_id in taken:
            new_state["objects"][rune_id]["exhausted"] = entry_state == "exhausted"
            new_state["players"][player_id]["zones"]["base"].append(rune_id)
            _bump_identity(new_state, rune_id)
        applied = len(taken)
        trace.update({"player": player_id, "requested_count": count, "applied_count": applied, "entry_state": entry_state,
                      "objects": taken, "identities_after": {rune_id: object_identity(new_state, rune_id) for rune_id in taken},
                      "completion": "full" if applied == count else ("partial" if applied else "none"), "not_a_move": True})
        if applied == 0:
            trace["outcome"] = "no_op"

    elif op == "modify_might":
        object_id, amount = effect.get("object_id"), effect.get("amount")
        duration, source = effect.get("duration"), effect.get("source")
        if object_id not in new_state["objects"] or not isinstance(amount, int):
            raise ValueError("modify_might requires a known object and integer amount")
        if duration not in {"this_turn", "persistent"} or not isinstance(source, str) or not source:
            raise ValueError("modify_might requires duration and source")
        # Core 477 with the card's own floor: "give a Unit -1 Might, to a minimum
        # of 1" moves nothing on a 1 Might Unit. The floor is worked out here so
        # that what gets recorded is what actually happened, and the entry
        # carries the bounds for the layer code that already reads them.
        # Read plainly, not through a helper: an executor audit that scans for
        # what a branch reads off `effect` must be able to SEE these two, or a
        # contract claiming they are existing fields could not be re-verified.
        minimum, maximum = effect.get("minimum"), effect.get("maximum")
        floored = _floored_might_amount(effective_might(new_state, object_id), amount, effect)
        minimum = minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else None
        maximum = maximum if isinstance(maximum, int) and not isinstance(maximum, bool) else None
        if floored == 0:
            # Core 370.1.a: nothing moved, so there is no event. No continuous
            # effect is recorded either - an entry of +0 would still be an entry
            # that other rules could read.
            trace.update({"object_id": object_id, "amount": 0, "requested_amount": amount,
                          "duration": duration, "outcome": "no_op", "completion": "none",
                          "floored_by": {"minimum": minimum, "maximum": maximum},
                          "reason": "the change is floored or capped away; nothing moves, so there is no "
                                    "event to read (Core 370.1.a)"})
            return new_state, trace
        # ADR-0013 §1: one canonical continuous effect in the Arithmetic layer.
        turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
        # Core 477.3.b: this op's source is never a passive ability - a passive
        # contributes through might_auras and conditional entries, not through
        # an instruction - so the limit it took is snapshotted. The raw amount
        # and the bounds stay on the entry as the record of what the card said;
        # `snapshot_amount` is what it actually contributes from here on.
        bounds = {name: value for name, value in (("minimum", minimum), ("maximum", maximum)) if value is not None}
        if bounds:
            bounds["snapshot_amount"] = floored
        entry = {
            "effect_id": f"might:{source}:{object_id}:{len(canonical_effects(new_state))}", "kind": "might_arithmetic",
            "source": {"object": source if source in new_state["objects"] or source in new_state["battlefields"] else object_id, "identity": None, "name": source},
            "affects": {"scope": "object", "object": object_id, "identity": object_identity(new_state, object_id) or f"{object_id}@0"},
            "layer": "arithmetic", "sublayer": "increase" if floored >= 0 else "decrease",  # what it contributes, not what was asked
            "timestamp": _next_timestamp(new_state), "value": {"amount": amount, "mode": "delta", **bounds},
            "duration": {"kind": "this_turn", "turn_id": turn_id} if duration == "this_turn" else {"kind": "permanent"},
            "passive": False,
        }
        new_state.setdefault("continuous_effects", []).append(entry)
        trace.update({"object_id": object_id, "amount": floored, "requested_amount": amount,
                      "duration": duration, "turn_id": turn_id if duration == "this_turn" else None,
                      "effect_id": entry["effect_id"], "layer": "arithmetic", "timestamp": entry["timestamp"]})
        if floored != amount:
            trace["floored_by"] = {"minimum": minimum, "maximum": maximum}

    elif op == "discard":
        player_id, objects = effect.get("player"), effect.get("objects")
        if player_id not in new_state["players"] or not isinstance(objects, list):
            raise ValueError("discard requires a known player and a resolved selection")
        hand = new_state["players"][player_id]["zones"]["hand"]
        identities = {}
        for object_id in objects:
            if object_id not in hand:
                raise IllegalOperation(f"{object_id!r} is not in {player_id}'s hand")
            hand.remove(object_id)
            owner = new_state["objects"][object_id]["owner"]
            new_state["players"][owner]["zones"]["trash"].append(object_id)
            identities[object_id] = _bump_identity(new_state, object_id)
        # Core 422.1 (2026-09-27): "if you've discarded a card this turn" reads this ledger
        record_discarded_cards(new_state, player_id, list(objects))
        requested = effect.get("count")
        trace.update({"player": player_id, "requested_count": requested, "applied_count": len(objects), "objects": list(objects), "identities_after": identities,
                      "not_a_target": True, "selection": effect.get("selection_meta", {}),
                      "completion": "full" if len(objects) == requested else ("partial" if objects else "none")})
        if effect.get("whole_hand"):
            # package 6: the whole hand, as it stood when the instruction executed (Core 422.1)
            trace["whole_hand"] = True
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 422.4"]))
        if not objects:
            trace["outcome"] = "no_op"

    elif op == "spend_buffs":
        # Core 702.2.b: each chosen Unit loses its one buff; one it no longer has, or that its
        # player does not control, cannot be spent from (702.2.b.1, 702.2.b.2)
        player_id, objects = effect.get("player"), effect.get("objects")
        if player_id not in new_state["players"] or not isinstance(objects, list):
            raise ValueError("spend_buffs requires a known player and a resolved selection")
        for object_id in objects:
            obj = new_state["objects"].get(object_id) or {}
            if not obj.get("buffed") or obj.get("controller") != player_id or zone_class(find_location(new_state, object_id)) != "board":
                raise IllegalOperation(f"{player_id} cannot spend a buff from {object_id!r} (702.2.b.1, 702.2.b.2)")
            spend_one_buff(obj)
        trace.update({"player": player_id, "objects": list(objects), "applied_count": len(objects),
                      "selection": effect.get("selection_meta", {}), "not_a_target": True,
                      "completion": "full" if objects else "none"})
        if not objects:
            trace["outcome"] = "no_op"

    elif op == "heal_all_damage":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("heal_all_damage requires a known object")
        before = new_state["objects"][object_id]["damage"]
        new_state["objects"][object_id]["damage"] = 0
        trace.update({"object_id": object_id, "before": before, "after": 0})
        if before == 0:
            trace["outcome"] = "no_op"

    elif op == "grant_replacement":
        # ADR-0007 §12 (Highlander): "Choose a friendly unit. The next time it
        # would die this turn, ... instead." creates a replacement bound to the
        # chosen object's identity, once, for this turn; the spell itself is
        # gone by then, so the replacement is granted, not source-backed.
        object_id, spec, controller = effect.get("object_id"), effect.get("replacement"), effect.get("controller")
        if object_id not in new_state["objects"] or not isinstance(spec, dict) or controller not in new_state["players"]:
            raise ValueError("grant_replacement requires a known object, a replacement spec and a controller")
        if zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"grant_replacement applies only to a board object; {object_id!r} is not on the board")
        if not isinstance(effect.get("granted_by"), str) or not effect.get("granted_by"):
            raise ValueError("grant_replacement requires granted_by")

        def bind_target(value):
            if isinstance(value, dict):
                return {k: bind_target(v) for k, v in value.items()}
            if isinstance(value, list):
                return [bind_target(v) for v in value]
            return object_id if value == "$granted_target" else value

        granted = {
            "replacement_id": spec.get("replacement_id") or f"granted:{effect.get('granted_by')}:{object_id}",
            "controller": controller, "mode": spec.get("mode"), "event_op": spec.get("event_op"), "optional": bool(spec.get("optional", False)),
            "uses_remaining": 1, "target_object_id": object_id,
            "granted": {"target_object": object_id, "target_identity": object_identity(new_state, object_id) or f"{object_id}@0", "duration": "this_turn",
                        "turn_id": new_state.get("turn_id", DEFAULT_TURN_ID), "granted_by": effect["granted_by"]},
        }
        if spec.get("replacement_effects") is not None:
            granted["replacement_effects"] = bind_target(copy.deepcopy(spec["replacement_effects"]))
        if spec.get("cost") is not None:
            # package 10 (Unlicensed Armory): "you may pay [Fury] to ... instead"
            granted["cost"] = copy.deepcopy(spec["cost"])
        if any(r["replacement_id"] == granted["replacement_id"] for r in new_state["replacement_effects"]):
            raise ValueError(f"replacement {granted['replacement_id']!r} already exists")
        new_state["replacement_effects"].append(granted)
        trace.update({"object_id": object_id, "replacement_id": granted["replacement_id"], "granted": copy.deepcopy(granted["granted"])})

    elif op == "create_turn_replacement":
        # package 9 (Unyielding Spirit): the replacement lasts the rest of this turn and applies to any object, a
        # spell played later this turn included (GPT 2026-10-06 ruling 9); it is neither a permanent's own ability
        # (source_object) nor granted to one object (granted): `created`, cleared by the turn's Expiration Step
        controller, spec = effect.get("controller"), effect.get("replacement")
        if controller not in new_state["players"] or not isinstance(spec, dict):
            raise ValueError("create_turn_replacement requires its controller and the replacement")
        turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
        created = {"replacement_id": f"created:{effect.get('created_by') or 'effect'}:{effect.get('effect_id')}:{turn_id}",
                   "controller": controller, "mode": spec["mode"], "event_op": spec["event_op"], "optional": False,
                   "uses_remaining": None, "damage_sources": list(spec["damage_sources"]),
                   "created": {"duration": "this_turn", "turn_id": turn_id,
                               "created_by": effect.get("created_by") or str(effect.get("effect_id"))}}
        if any(r["replacement_id"] == created["replacement_id"] for r in new_state["replacement_effects"]):
            raise ValueError(f"replacement {created['replacement_id']!r} already exists")
        new_state["replacement_effects"].append(created)
        trace.update({"player": controller, "replacement_id": created["replacement_id"],
                      "created": copy.deepcopy(created["created"])})

    elif op == "grant_keyword":
        # ADR-0008 §5 (Fortified Position: "It gains [Shield 2] this combat."):
        # a granted characteristic bound to the object's identity now and to
        # the Combat in progress (expires with it, 466.7.c) or to this turn.
        object_id, keyword, duration = effect.get("object_id"), effect.get("keyword"), effect.get("duration")
        if object_id not in new_state["objects"] or keyword not in GRANTABLE_KEYWORDS or duration not in GRANT_DURATIONS \
                or (duration == "permanent" and keyword not in UNTIMED_GRANTABLE_KEYWORDS):
            raise ValueError("grant_keyword requires a known object, a grantable keyword and a duration")
        kinds = {"unit", "gear"} if keyword in PERMANENT_GRANTABLE_KEYWORDS else {"unit"}
        if new_state["objects"][object_id].get("kind") not in kinds or zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"grant_keyword {keyword} applies only to a {' or '.join(sorted(kinds))} on the board; "
                                   f"{object_id!r} is not one")
        value = effect.get("value")
        if keyword not in VALUED_KEYWORDS and value is not None:
            raise ValueError(f"{keyword} carries no value")
        # ADR-0013 §1: a granted characteristic is an Ability-layer effect
        # bound to the identity it was granted to (Core 477.2, 124).
        effect_id = f"{keyword}:{effect.get('source')}:{object_id}:{len(canonical_effects(new_state))}"
        if duration == "this_combat":
            combat = effect.get("combat_context")
            if not isinstance(combat, dict) or not combat.get("combat_id"):
                raise NotImplementedError("a 'this combat' grant needs the Combat in progress as context (466.7.c); none was supplied")
            effect_duration = {"kind": "this_combat", "combat_id": combat["combat_id"]}
        elif duration == "permanent":
            # Core 801.3.a.3: no duration - while it stays on the board; the identity binding below ends it (124)
            effect_duration = {"kind": "permanent"}
        else:
            effect_duration = {"kind": "this_turn", "turn_id": new_state.get("turn_id", DEFAULT_TURN_ID)}
        entry = {
            "effect_id": effect_id, "kind": "keyword_grant",
            "source": {"object": effect.get("source") if effect.get("source") in new_state["objects"] else object_id, "identity": None, "name": effect.get("source")},
            "affects": {"scope": "object", "object": object_id, "identity": object_identity(new_state, object_id) or f"{object_id}@0"},
            "layer": "ability", "timestamp": _next_timestamp(new_state),
            "value": {"keyword": keyword, **({"value": value if value is not None else 1} if keyword in VALUED_KEYWORDS else {})},
            "duration": effect_duration, "passive": False,
        }
        new_state.setdefault("continuous_effects", []).append(entry)
        trace.update({"object_id": object_id, "keyword": keyword, "value": entry["value"].get("value"), "duration": duration,
                      "combat_id": effect_duration.get("combat_id"), "turn_id": effect_duration.get("turn_id"), "modifier_id": effect_id,
                      "shield_total": shield_total(new_state, object_id) if keyword == "shield" else None,
                      **({"assault_total": assault_total(new_state, object_id)} if keyword == "assault" else {})})

    elif op == "grant_turn_effect":
        kind, value, controller = effect.get("turn_effect_kind"), effect.get("value"), effect.get("controller")
        if kind not in TURN_EFFECT_KINDS:
            raise NotImplementedError(f"turn effect {kind!r} is not modelled")
        if kind in {"next_spell_cost_reduction", "next_spell_bonus_damage", "buff_bonus_might"}:
            # the Energy the next spell's cost is reduced by (Core 356.4, 356.6); the Bonus Damage each of the next
            # spell's own Deals gets (713, 714.1)
            if controller not in new_state["players"] or not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{kind} requires a known controller and a positive value")
        elif controller not in new_state["players"] or value not in TURN_EFFECT_VALUES.get(kind, {"ready", "exhausted"}):
            raise ValueError(f"grant_turn_effect requires a known controller and a value in "
                             f"{sorted(TURN_EFFECT_VALUES.get(kind, {'ready', 'exhausted'}))}")
        turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
        taken = {e.get("effect_id") for e in new_state.get("turn_effects", []) or []}
        serial = len(new_state.get("turn_effects", []))
        # a spent next-card effect leaves the list, so a count alone could name a live one twice
        while f"{kind}:{controller}:{turn_id}:{serial}" in taken:
            serial += 1
        granted = {"effect_id": f"{kind}:{controller}:{turn_id}:{serial}", "kind": kind, "controller": controller,
                   "value": value, "turn_id": turn_id, "source": effect.get("source", "effect")}
        new_state.setdefault("turn_effects", []).append(granted)
        trace.update({"turn_effect": granted})

    elif op == "mutual_damage_current_might":
        raise ValueError("mutual_damage_current_might is resolved by apply_program as two simultaneous Deal events")

    elif op == "swap_might":
        raise ValueError("swap_might is resolved by apply_program as two Might changes over one snapshot")

    elif op == "raise_might_to_match":
        raise ValueError("raise_might_to_match is resolved by apply_program as one Might change over one snapshot")

    elif op == "recycle_when_leaving_chain":
        raise ValueError("recycle_when_leaving_chain is bound by apply_program to the chain item its linked play started")

    elif op in {"take_additional_turn", "banish_this", "activate_conquer_effects", "make_new_choices"}:
        raise ValueError(f"{op} is applied by apply_program (the turn queue; the resolving chain item)")

    elif op == "trigger_base_cost":
        # paid at finalization (trigger_cost.py); apply_program only checks the receipt
        raise ValueError("trigger_base_cost is paid when the triggered ability is finalized (Core 383.3.b.1); "
                         "apply_program checks its receipt and never runs it as an instruction")

    elif op == "limited_play":
        # step 1 of the play is apply_program's (_start_limited_play), which knows the program that
        # grants it; the rest is the play transaction's (resolution_bridge.finalize_limited_play)
        raise ValueError("limited_play is started by apply_program (Core 354) and finished by the play "
                         "transaction (Core 419.3.b); it is never run as a bare instruction")

    elif op == "establish_selection":
        # apply_program runs it before selector resolution, because it produces
        # the binding later selectors read. Reaching here means that ordering
        # broke, and a silent fall-through would establish nothing while the
        # clauses after it went looking for a selection.
        raise ValueError("establish_selection is resolved by apply_program before selectors; it changes no state")

    elif op == "each_player":
        # package 6: expanded by apply_program into one copy of its instructions per player
        raise ValueError("each_player is expanded by apply_program into its per-player instructions (Core 303.2.a)")

    elif op == "choose_objects":
        raise ValueError("choose_objects is resolved by apply_program; it fills a group and changes no state")

    elif op == "choose_option":
        raise ValueError("choose_option is resolved by apply_program; it records a player's option and changes no state")

    elif op == "pay_any_amount":
        raise ValueError("pay_any_amount is resolved by apply_program, which asks for and makes the payment as it resolves")

    elif op in {"deal_damage", "heal_damage"}:
        object_id, amount = effect.get("object_id"), effect.get("amount")
        if object_id not in new_state["objects"] or not isinstance(amount, int) or amount < 1:
            raise ValueError(f"{op} requires a known object and positive amount")
        before = new_state["objects"][object_id]["damage"]
        after = before + amount if op == "deal_damage" else max(0, before - amount)
        new_state["objects"][object_id]["damage"] = after
        trace.update({"object_id": object_id, "before": before, "after": after})
        if effect.get("source_object") is not None:
            # Core 417.6.b.3: a Unit named as the source is the source, not the spell.
            trace.update({"source_object": effect["source_object"], "source_kind": effect.get("source_kind", "object"),
                          "responsible_player": new_state["objects"].get(effect["source_object"], {}).get("controller")})
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 417.6.b.3", "Core 417.6.b.4"]))
        if effect.get("bonus_damage"):
            trace["bonus_damage"] = copy.deepcopy(effect["bonus_damage"])
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 713–715"]))
        if before == after:
            trace["outcome"] = "no_op"

    elif op in {"ready", "exhaust"}:
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError(f"{op} requires a known object")
        location = find_location(new_state, object_id)
        # a Legend is exhausted and readied in its Legend Zone (Core 107.4, 415.1; GPT 2026-10-02)
        if location is None or not (location[0] == "battlefield" or location[2] in ("base", "legend_zone")):
            raise ValueError(f"{op} applies only to board objects and a Legend in its Legend Zone")
        desired = op == "exhaust"
        before = new_state["objects"][object_id]["exhausted"]
        prevented = (battlefield_restriction(new_state, "no_ready_enemy_units_gear",
                                             new_state["objects"][object_id].get("controller"))
                     if op == "ready" and new_state["objects"][object_id]["kind"] in {"unit", "gear"} else None)
        if prevented is not None:
            # package 11 (Mageseeker Warden, 358.3.a): an impossible instruction, skipped as it resolves
            trace.update({"object_id": object_id, "before": before, "after": before, "outcome": "no_op",
                          "reason": "ready_prevented", "prevented_by": prevented,
                          "rule_locators": list(dict.fromkeys(trace["rule_locators"] + ["Core 358.3.a"]))})
            return new_state, trace
        new_state["objects"][object_id]["exhausted"] = desired
        trace.update({"object_id": object_id, "before": before, "after": desired})
        if before == desired:
            trace["outcome"] = "no_op"

    elif op == "add_resource":
        player_id, resource, amount = effect.get("player"), effect.get("resource"), effect.get("amount")
        if player_id not in new_state["players"] or not isinstance(amount, int) or amount < 1:
            raise ValueError("add_resource requires a known player and positive amount")
        resources = new_state["players"][player_id]["resources"]
        restriction = effect.get("restriction")
        # 2026-09-27: "[Add] [A]" adds Universal Power, which pays a Power cost of any Domain
        # (Core 135.2.e.5.b, 163.2.b); validate_program holds its shape
        universal = effect.get("universal") is True and resource == "power" and "domain" not in effect
        if restriction is not None:
            # ADR-0011 §4: "Spend this Energy only to play spells" — the resource
            # sits in a restricted pool the payment consumes only for a matching use.
            if resource == "power" and not universal and not (isinstance(effect.get("domain"), str) and effect["domain"]):
                raise ValueError("power addition requires a domain")
            entry = {"restriction_id": effect.get("restriction_id") or f"{effect.get('effect_id', 'add')}:{player_id}", "kind": resource, "amount": amount, "uses": list(restriction["uses"])}
            if universal:
                entry["universal"] = True
            elif resource == "power":
                entry["domain"] = effect["domain"]
            if effect.get("source") or effect.get("_source"):
                entry["source"] = effect.get("source") or effect.get("_source")
            resources.setdefault("restricted", []).append(entry)
            trace.update({"player": player_id, "resource": resource, "amount": amount, "restricted": {k: v for k, v in entry.items()},
                          **({"universal": True} if universal else {"domain": effect["domain"]} if resource == "power" else {})})
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 166.1", "Core 168"]
                                                        + (["Core 135.2.e.5.b", "Core 163.2.b"] if universal else [])))
        elif resource == "energy":
            resources["energy"] += amount
            trace.update({"player": player_id, "resource": resource, "amount": amount})
        elif universal:
            resources["universal_power"] = resources.get("universal_power", 0) + amount
            trace.update({"player": player_id, "resource": resource, "universal": True, "amount": amount})
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 135.2.e.5.b", "Core 163.2.b"]))
        elif resource == "power" and isinstance(effect.get("domain"), str) and effect["domain"]:
            domain = effect["domain"]
            resources["power"][domain] = resources["power"].get(domain, 0) + amount
            trace.update({"player": player_id, "resource": resource, "domain": domain, "amount": amount})
        else:
            raise ValueError("power addition requires a domain")

    elif op == "play_token":
        object_id = effect.get("object_id")
        owner = effect.get("owner")
        controller = effect.get("controller")
        token_kind = effect.get("token_kind")
        base_might = effect.get("base_might")
        destination = effect.get("destination")
        if not isinstance(object_id, str) or not object_id or object_id in new_state["objects"]:
            raise ValueError("play_token requires a new unique object_id")
        if owner not in new_state["players"] or controller not in new_state["players"]:
            raise ValueError("play_token requires known owner/controller players")
        if token_kind not in {"unit", "gear"} or not isinstance(base_might, int) or base_might < 0:
            raise ValueError("play_token requires a supported kind and non-negative base_might")
        if not isinstance(destination, dict):
            raise ValueError("play_token requires a destination")
        if "decision_ref" in destination:
            # 2026-09-25 (GPT): a token the card places nowhere is played as its card type is
            # (Core 185.2.a): its controller chooses among the locations legal right now - its
            # Base, or a Battlefield it controls for a Unit (355.2.a) - each token on its own
            # decision, no default. The candidates travel with the request, from the board.
            import engine_decisions as _ed
            candidates = token_play_locations(new_state, controller, token_kind)
            if token_kind == "unit" and effect.get("hidden_battlefield"):
                # Core 811.1.d.3: played from Hidden, the unit must be played at that battlefield
                candidates = [c for c in candidates if c == f"battlefield:{effect['hidden_battlefield']}"]
                if not candidates:
                    raise ValueError(f"the unit token must be played at {effect['hidden_battlefield']!r}, where the card was "
                                     f"hidden (Core 811.1.d.3), and it cannot be played there")
            entry = next((e for e in _ed.entries(decisions, kind="location_selection")
                          if e["decision_id"] == destination["decision_ref"]), None)
            if entry is None:
                raise LocationSelectionRequired(
                    f"where the token {object_id!r} is played is its controller's choice (Core 185.2.a, 355.2.a)",
                    [destination["decision_ref"]], controller, candidates)
            if entry["controller"] != controller:
                raise IllegalDecision(f"location selection {destination['decision_ref']!r} was made by "
                                      f"{entry['controller']!r}, not the token's controller {controller!r}")
            if entry["value"] not in candidates:
                raise ValueError(f"location selection {destination['decision_ref']!r} names {entry['value']!r}; "
                                 f"the token may be played to {candidates}")
            kind, _, name = entry["value"].partition(":")
            destination = {"kind": "battlefield", "battlefield": name} if kind == "battlefield" else {"kind": "base", "player": name}
        if token_kind == "gear" and destination.get("kind") != "base":
            raise ValueError("non-Unit Gear token must enter a Base")
        if destination.get("kind") == "base" and destination.get("player") != controller:
            raise ValueError("play_token Base destination must match token controller")
        modifiers = copy.deepcopy(effect.get("event_modifiers", {}))
        default_entry_state = "exhausted" if token_kind == "unit" else "ready"
        entry_state = modifiers.get("entry_state", default_entry_state)
        # Core 350.2 (GPT 2026-09-27, group 乙): a unit token is Played, so this turn's entry-state
        # effects for units its controller plays apply to it as to a card - and "the next unit you
        # play" is spent by it
        token_turn_effects: list[dict[str, Any]] = []
        if token_kind == "unit":
            current_turn = new_state.get("turn_id", DEFAULT_TURN_ID)
            token_turn_effects = [e for e in new_state.get("turn_effects", []) or []
                                  if e.get("kind") in {"entry_state_for_played_units", "entry_state_for_next_played_unit"}
                                  and e.get("controller") == controller and e.get("turn_id") == current_turn
                                  and e.get("value") in {"ready", "exhausted"}]
            # the next unit is ONE unit: the first such effect is spent by this token
            nexts = [e for e in token_turn_effects if e["kind"] == "entry_state_for_next_played_unit"]
            token_turn_effects = [e for e in token_turn_effects if e["kind"] == "entry_state_for_played_units"] + nexts
            values = {e["value"] for e in token_turn_effects} | ({modifiers["entry_state"]} if "entry_state" in modifiers else set())
            if len(values) > 1:
                raise ValueError(f"the token's entry state is disputed by {sorted(values)} ({[e['effect_id'] for e in token_turn_effects]}); "
                                 f"their order is its controller's (Core 369.3) and is not guessed")
            if token_turn_effects:
                entry_state = next(iter(values))
                spent = {e["effect_id"] for e in nexts}
                if spent:
                    new_state["turn_effects"] = [e for e in new_state.get("turn_effects", []) or [] if e.get("effect_id") not in spent]
                    if not new_state["turn_effects"]:
                        new_state.pop("turn_effects")
        # 2026-09-27 package 6: a token Unit enters the board too - a grant on the board ("Other
        # friendly units enter ready.", Core 369.3) replaces its default when the instruction names none;
        # beside this turn's entry-state effects (350.2, above) a different value is disputed, never guessed
        granted = (granted_entry_states(new_state, None, token_kind, controller)
                   if token_kind == "unit" and "entry_state" not in modifiers else [])
        if granted:
            if token_turn_effects and granted[-1]["value"] != entry_state:
                raise ValueError(f"the token's entry state is disputed by a grant on the board ({granted[-1]['value']}) and this "
                                 f"turn's effects ({entry_state}); their order is its controller's (Core 369.3) and is not guessed")
            entry_state = granted[-1]["value"]
            trace["granted_entry_states"] = [g["replacement_id"] for g in granted]
        keywords = modifiers.get("result_keywords", []) if token_kind == "unit" else []
        new_state["objects"][object_id] = {
            "owner": owner,
            "controller": controller,
            "kind": token_kind,
            "is_token": True,
            "base_might": base_might,
            "might_modifiers": [],
            "damage": 0,
            "exhausted": entry_state == "exhausted",
            "keywords": copy.deepcopy(keywords),
            "identity": f"{object_id}@0",
            # which catalogued token this is, on the object itself (ADR-0012 §6), so a later
            # rule can ask what the token is - not only the trace of its making
            **({"token_id": effect["token_id"]} if effect.get("token_id") else {}),
            # package 7 (GPT 2026-10-02): the token card's printed tags, carried by the instruction from the
            # reviewed catalogue (token_catalog.carry_tags), so object_tags reads them like any printed tag
            **({"tags": list(effect["tags"])} if effect.get("tags") else {}),
        }
        if destination.get("kind") == "base" and destination.get("player") in new_state["players"]:
            new_state["players"][destination["player"]]["zones"]["base"].append(object_id)
            destination_label = f"{destination['player']}.base"
        elif destination.get("kind") == "battlefield" and destination.get("battlefield") in new_state["battlefields"]:
            new_state["battlefields"][destination["battlefield"]]["objects"].append(object_id)
            destination_label = f"battlefield:{destination['battlefield']}"
            apply_arrival_contested(new_state, destination["battlefield"], object_id)
        else:
            raise ValueError("play_token destination is unknown")
        if token_turn_effects:
            trace["entry_turn_effects"] = [{"effect_id": e["effect_id"], "kind": e["kind"], "value": e["value"],
                                            **({"spent": True} if e["kind"] == "entry_state_for_next_played_unit" else {})}
                                           for e in token_turn_effects]
            trace.setdefault("rule_locators", list(OP_RULES[op]))
            trace["rule_locators"] = list(trace["rule_locators"]) + ["Core 350.2", "Core 369.3", "Core 390.4", "Core 391"]
        trace.update({
            "object_id": object_id,
            "token_kind": token_kind,
            "base_might": base_might,
            "destination": destination_label,
            "event_modifiers": modifiers,
            "modifier_inheritance": copy.deepcopy(effect.get("modifier_inheritance")),
            # ADR-0012 §6: which reviewed catalogue entry these characteristics
            # were compiled from, so a program's provenance stays checkable.
            **({"token_id": effect["token_id"]} if effect.get("token_id") else {}),
        })

    elif op == "kill" and effect.get("if_identity") is not None and (
            effect.get("object_id") not in new_state["objects"]
            or object_identity(new_state, effect["object_id"]) != effect["if_identity"]
            or zone_class(find_location(new_state, effect["object_id"])) != "board"):
        # "Kill this." bound to the permanent as it was when the instruction was made:
        # once it has left the Board it is a new object (124), and the instruction has
        # nothing to act on - ignored, not refused (Temporary, GPT 2026-09-22)
        trace.update({"outcome": "no_op", "object_id": effect.get("object_id"), "reason": "bound_object_left_board",
                      "rule_locators": ["Core 124", "Core 816.1.b"]})

    elif op == "kill":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("kill requires a known object")
        obj = new_state["objects"][object_id]
        location = find_location(new_state, object_id)
        if location is None or not (location[0] == "battlefield" or location[2] == "base"):
            raise ValueError("Kill applies only to a permanent on the board")
        if obj.get("kind") not in {"unit", "gear"}:
            raise ValueError("effect IR v1 only kills supported Unit/Gear permanents")
        # Core 323 step 3a / 808.2: the abilities are noted *before* the card
        # moves to the Trash, with its location and attributes as they are now.
        pending_triggers = copy.deepcopy(object_triggers(new_state, object_id, "death_triggers"))
        # package 11: leaving the board by dying is leaving it (leave_board_triggers)
        leaving_triggers = leave_board_triggers(new_state, object_id)
        # 2026-10-12 (package 11, Kog'Maw - Caustic; GPT PACKAGE11 ruling 3): where it was as its abilities were noted,
        # before it moves (Core 808.1.d.3) - what its "my battlefield" reads when the trigger resolves
        noted = ({"kind": "battlefield", "battlefield": location[1]} if location[0] == "battlefield"
                 else {"kind": "base", "player": location[1]})
        for trigger in pending_triggers:
            trigger["noted_location"] = dict(noted)
        deathknell = {trigger["trigger_id"] for trigger in deathknell_instances(new_state, object_id)}
        for trigger in pending_triggers:
            trigger["deathknell"] = trigger["trigger_id"] in deathknell
        # Core 428.1: a Unit died - counted for its controller as it died, before it leaves the
        # board (a token ceases to exist below, 186.1, and still died)
        died_as_unit = characteristics(new_state, object_id).get("kind") == "unit"
        controller_at_death = obj.get("controller")
        extra_at_death = obj.get(DEATHKNELL_EXTRA_FIELD)
        # 2026-10-04 (package 8, GPT ruling 7): the Might it had as it died, for an instruction that compares with "the
        # killed unit" afterwards (Core 359.3.e.12: information about an object that changed zones is its last known)
        might_at_death = effective_might(new_state, object_id) if died_as_unit else None
        detached = detach_records(new_state, object_id, _last_board_location(location), host_left_board=True)
        _remove_from_location(new_state, object_id)
        if died_as_unit:
            record_unit_death(new_state, controller_at_death)
        if obj.get("is_token"):
            del new_state["objects"][object_id]
            destination = "ceased_to_exist"
            trace["rule_locators"] = ["Core 428", "Core 186.1"]
        else:
            new_state["players"][obj["owner"]]["zones"]["trash"].append(object_id)
            destination = f"{obj['owner']}.trash"
            obj.pop("combat_designation", None)
            trace["identity_after"] = _bump_identity(new_state, object_id)
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 124"]))
        disabled_replacements = _prune_inactive_replacements(new_state)
        if detached:
            trace["detached"] = detached
            trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 435.4", "Core 435.4.b"]))
        trace.update({
            "object_id": object_id,
            **({"might_at_death": might_at_death} if might_at_death is not None else {}),
            "kill_mode": effect.get("kill_mode", "active"),
            "destination": destination,
            "attributed_sources": effect.get("attributed_sources", []),
            "pending_triggers": pending_triggers + leaving_triggers,
            "disabled_replacements": disabled_replacements,
            **({"deathknell_extra_source": {"controller": controller_at_death, "extra_times": extra_at_death}}
               if _extra_times(extra_at_death) else {}),
        })

    elif op == "look_at_top":
        player_id, count = effect.get("player"), effect.get("count")
        if player_id not in new_state["players"]:
            raise ValueError("look_at_top requires a known player")
        controller = effect.get("_controller") or new_state["objects"].get(effect.get("_source") or "", {}).get("controller") or player_id
        looked = _mark_reveals(new_state, player_id, "main_deck", new_state["players"][player_id]["zones"]["main_deck"][:count], [controller], effect.get("effect_id", "look"), "look")
        trace.update({"player": player_id, "requested_count": count, "looked_count": len(looked), "objects_visible_to": [controller],
                      "objects_hash": _ids_hash(new_state, looked), "deck_order_unchanged": True, "burn_out": False,
                      "completion": "full" if len(looked) == count else ("partial" if looked else "none")})
        if not looked:
            trace["outcome"] = "no_op"

    elif op == "banish_one_looked":
        # 2026-10-13 package 11 (Promising Future): one of the cards its player looked at - chosen by that player,
        # privately - leaves the Main Deck for its owner's Banishment as a new object (Core 427.1, 124). Nothing looked
        # at, nothing banished
        player_id = effect.get("player")
        if player_id not in new_state["players"]:
            raise ValueError("banish_one_looked requires a known player")
        candidates = _session_cards(new_state, player_id, "main_deck")
        spec = {"selection_kind": "single", "from": "revealed", "by": player_id, "visibility": "private_to_chooser",
                "identity_binding": True}
        chosen, meta = (resolve_choice(new_state, spec, decision_ref=effect.get("decision_ref") or f"{effect.get('effect_id')}:pick",
                                       decisions=decisions, controller=player_id, candidates=candidates)
                        if candidates else ([], {}))
        identities = {}
        for object_id in chosen:
            new_state["players"][player_id]["zones"]["main_deck"].remove(object_id)
            new_state["players"][new_state["objects"][object_id]["owner"]]["zones"]["banishment"].append(object_id)
            identities[object_id] = _bump_identity(new_state, object_id)
        _drop_reveals(new_state, chosen)
        trace.update({"player": player_id, "objects": list(chosen), "identities_after": identities,
                      "objects_visible_to": [player_id], "selection": {k: v for k, v in meta.items() if k != "choice"},
                      "completion": "full" if chosen else "none"})
        if not chosen:
            trace["outcome"] = "no_op"

    elif op == "recycle_looked_rest":
        # 2026-10-13 package 11 (Promising Future): the cards its player looked at that are still in that Main Deck - as
        # one Recycle (Core 416), in a random order (416.5)
        player_id = effect.get("player")
        if player_id not in new_state["players"]:
            raise ValueError("recycle_looked_rest requires a known player")
        rest = _session_cards(new_state, player_id, "main_deck")
        new_state, sub = _recycle_batch(new_state, rest, player_id, decisions,
                                        effect.get("order_ref") or f"{effect.get('effect_id', 'rest')}:order",
                                        effect.get("effect_id", "rest"))
        trace.update(sub)
        if not rest:
            trace["outcome"] = "no_op"

    elif op == "stun":
        # Core 423: a binary status, applied by an effect that chooses a Unit
        # on the board. It is not a Might change - what it does to Combat is
        # read at damage assignment (423.1.b), and everything else reads the
        # Unit's Might unchanged.
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("stun requires a known object")
        obj = new_state["objects"][object_id]
        if obj.get("kind") != "unit" or zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"Stun applies to a Unit on the board; {object_id!r} is not one (423.1)")
        if obj.get("stunned"):
            # 423.2: already Stunned. The choice was legal and nothing happens -
            # no refreshed duration, no second entry, and no event for a
            # "when you stun" to read.
            trace.update({"object_id": object_id, "outcome": "no_op", "completion": "none",
                          "already_stunned": True, "was_stunned": False,
                          "reason": "the Unit is already Stunned; Stun is a binary status (423.2)"})
            return new_state, trace
        obj["stunned"] = True
        turn_id = new_state.get("turn_id", DEFAULT_TURN_ID)
        entry = {"effect_id": f"stunned:{object_id}:{turn_id}", "kind": "stunned_unit",
                 "controller": obj.get("controller"), "turn_id": turn_id, "object_id": object_id}
        new_state.setdefault("turn_effects", []).append(entry)
        trace.update({"object_id": object_id, "was_stunned": True, "already_stunned": False,
                      "expires": {"turn_id": turn_id, "step": "expiration_3d"}})

    elif op == "choose_player":
        # Core 355.1: an instruction whose whole content is a choice. It changes
        # nothing; what it produces is the receipt every later instruction of
        # this program reads instead of choosing again.
        chosen, meta = resolve_choice(new_state, effect["choice"], decision_ref=effect.get("decision_ref"),
                                      decisions=decisions, controller=controller, execution=execution_suffix(effect))
        if len(chosen) != 1:
            raise ValueError("choose_player chooses exactly one player")
        trace.update({"player": chosen[0], "decision_ref": effect.get("decision_ref"),
                      "selection": {k: v for k, v in meta.items() if k != "choice"}, "completion": "full"})

    elif op == "reveal":
        player_id = resolve_player_ref(effect.get("player"), decisions, new_state, controller)
        if player_id not in new_state["players"]:
            raise ValueError("reveal requires a known player")
        zone = {"main_deck_top": "main_deck", "rune_deck_top": "rune_deck"}.get(effect.get("from"), "hand")
        ids = new_state["players"][player_id]["zones"][zone]
        wanted = ids[: effect["count"]] if zone != "hand" else list(ids)
        revealed = _mark_reveals(new_state, player_id, zone, wanted, "all", effect.get("effect_id", "reveal"), "reveal")
        # package 11 (Twisted Fate - Gambler): a rune revealed from the Rune Deck carries its Domains as they were
        # then - what "based on its domain" reads, even once it is recycled (GPT PACKAGE11 ruling 18)
        noted = (lambda o: {"domains": list(new_state["objects"][o].get("domains") or [])}) if zone == "rune_deck" \
            else (lambda o: {})
        trace.update({"player": player_id, "from": effect.get("from"),
                      "revealed": [{"object_id": o, "identity": object_identity(new_state, o), **noted(o)} for o in revealed],
                      "visible_to": "all", "zone_unchanged": True, "burn_out": False,
                      **({"requested_count": effect["count"]} if zone != "hand" else {}),
                      "completion": "full" if (zone == "hand" or len(revealed) == effect["count"]) else ("partial" if revealed else "none")})
        if not revealed:
            trace["outcome"] = "no_op"
            if zone == "rune_deck":
                trace["reason"] = "rune_deck_empty"

    elif op == "reveal_until":
        # 2026-10-04 (package 8): the Main Deck's top card, then the next, and so on, until one of the kind is revealed
        # - it included - or the deck runs out (Core 431.1.c: as many as there are). Revealed to all (424); nothing
        # moves: what happens to them is the instructions after this one's
        player_id = resolve_player_ref(effect.get("player"), decisions, new_state, controller)
        if player_id not in new_state["players"]:
            raise ValueError("reveal_until requires a known player")
        deck = new_state["players"][player_id]["zones"]["main_deck"]
        wanted, found = [], None
        for object_id in deck:
            wanted.append(object_id)
            if (new_state["objects"].get(object_id) or {}).get("kind") == effect["until"]["kind"]:
                found = object_id
                break
        revealed = _mark_reveals(new_state, player_id, "main_deck", wanted, "all", effect.get("effect_id", "reveal_until"), "reveal")
        trace.update({"player": player_id, "until": dict(effect["until"]),
                      "revealed": [{"object_id": o, "identity": object_identity(new_state, o)} for o in revealed],
                      "found": found, **({"found_identity": object_identity(new_state, found)} if found else {}),
                      "visible_to": "all", "zone_unchanged": True,
                      "completion": "full" if found else ("partial" if revealed else "none")})
        if not revealed:
            trace["outcome"] = "no_op"

    elif op == "put_back":
        player_id = effect.get("player")
        if player_id not in new_state["players"]:
            raise ValueError("put_back requires a known player")
        candidates = _session_cards(new_state, player_id, "main_deck")
        spec = {"selection_kind": "ordered_permutation", "count": {"any_number": True}, "from": "revealed", "by": player_id, "visibility": "private_to_chooser", "identity_binding": True}
        order, meta = resolve_choice(new_state, spec, decision_ref=effect.get("decision_ref") or f"{effect.get('effect_id', 'put_back')}:order", decisions=decisions, controller=player_id, candidates=candidates)
        position = effect.get("position", "top")
        _reorder_deck(new_state, player_id, order, position)
        _drop_reveals(new_state, order)
        trace.update({"player": player_id, "count": len(order), "position": position, "ordering_hash": _ids_hash(new_state, order), "order_visible_to": [player_id],
                      "identities_unchanged": True, "selection": {k: v for k, v in meta.items() if k != "choice"} | {"choice": {k: v for k, v in meta["choice"].items() if k != "options"}},
                      "completion": "full" if order else "none"})
        if not order:
            trace["outcome"] = "no_op"

    elif op in {"put_in_hand", "draw_it"}:
        player_id = effect.get("player")
        if player_id not in new_state["players"]:
            raise ValueError(f"{op} requires a known player")
        candidates = _session_cards(new_state, player_id, "main_deck")
        count = 1 if op == "draw_it" else effect.get("count", 1)
        spec = {"selection_kind": "single" if count == 1 else "unordered_set", **({"count": {"exactly": count}} if count != 1 else {}), "from": "revealed", "by": player_id, "visibility": "private_to_chooser", "identity_binding": True}
        chosen, meta = resolve_choice(new_state, spec, decision_ref=effect.get("decision_ref") or f"{effect.get('effect_id', op)}:pick", decisions=decisions, controller=player_id, candidates=candidates)
        identities = {}
        for object_id in chosen:
            new_state["players"][player_id]["zones"]["main_deck"].remove(object_id)
            new_state["players"][player_id]["zones"]["hand"].append(object_id)
            identities[object_id] = _bump_identity(new_state, object_id)
        trace.update({"player": player_id, "requested_count": count, "applied_count": len(chosen), "objects_hash": _ids_hash(new_state, chosen), "objects_visible_to": [player_id],
                      "identities_after_visible_to": [player_id], "draw_event": op == "draw_it", "drawn": len(chosen) if op == "draw_it" else 0,
                      "selection": {k: v for k, v in meta.items() if k != "choice"}, "completion": "full" if len(chosen) == count else ("partial" if chosen else "none")})
        if not chosen:
            trace["outcome"] = "no_op"

    elif op == "recycle":
        rest_of = effect.get("rest_of")
        if rest_of is not None:
            # package 6: apply_program has resolved "the rest" of the group into objects (Core 416.4:
            # as many as possible); each goes to its owner's deck, each owner ordering their own
            chosen, meta = list(effect.get("objects") or []), {"forced": True, "reason": f"what group {rest_of!r} left (Core 416.4)"}
        elif effect.get("objects") is not None:
            chosen, meta = list(effect["objects"]), {"forced": True, "reason": "the instruction names the cards"}
            for object_id in chosen:
                if object_id not in new_state["objects"]:
                    raise ValueError(f"recycle names unknown object {object_id!r}")
        else:
            chosen, meta = resolve_choice(new_state, effect["choice"], decision_ref=effect.get("decision_ref"), decisions=decisions, controller=effect.get("player"),
                                          execution=execution_suffix(effect))
        new_state, sub = _recycle_batch(new_state, chosen, effect.get("player"), decisions, effect.get("order_ref") or f"{effect.get('effect_id', 'recycle')}:order", effect.get("effect_id", "recycle"),
                                        per_deck_refs=rest_of is not None)
        if rest_of is not None:
            sub["rest_of"] = rest_of
            sub["rule_locators"] = list(dict.fromkeys(OP_RULES["recycle"] + ["Core 416.1.c", "Core 416.4", "Core 416.5.a"]))
        trace.update(sub)
        trace["selection"] = {k: v for k, v in meta.items() if k != "choice"}
        if not chosen:
            trace["outcome"] = "no_op"

    elif op == "predict":
        # Core 436: look at X, Recycle any number, put the rest back in any
        # order; a short deck Predicts as many as possible without a Burn Out.
        player_id, count = effect.get("player"), effect.get("count", 1)
        if player_id not in new_state["players"]:
            raise ValueError("predict requires a known player")
        session = effect.get("effect_id", "predict")
        seen = _mark_reveals(new_state, player_id, "main_deck", new_state["players"][player_id]["zones"]["main_deck"][:count], [player_id], session, "look")
        # GPT 2026-10-08 (second): looked_hash binds the objects as they were seen - each card's identity NOW, before a
        # banish (a new object, Core 124) or a recycle changes it; the new identities stay with the banishment/play
        seen_hash = _ids_hash(new_state, seen)
        # package 9 (GPT 2026-10-07, Nocturne - Horrifying): a card that may banish itself as its owner looks at it is
        # offered NOW - before Predict decides what to recycle or put back; banished, it is no longer among them.
        # GPT 2026-10-08: the banish does not undo the look - `seen` (every card looked at) is the receipt's looked_count,
        # looked_hash, completion and outcome; `looked` (those still there) is only what Predict may recycle or put back
        looked, seen_banished = offer_seen_banish_now(new_state, player_id, list(seen), decisions,
                                                      f"seen-banish:{program_id}:{session}")
        if seen_banished:
            trace["seen_banished"] = seen_banished
        spec = {"selection_kind": "unordered_set", "count": {"any_number": True}, "from": "revealed", "by": player_id, "visibility": "private_to_chooser", "identity_binding": True}
        recycled, r_meta = resolve_choice(new_state, spec, decision_ref=effect.get("recycle_ref") or f"{session}:recycle", decisions=decisions, controller=player_id, candidates=looked)
        new_state, sub = _recycle_batch(new_state, recycled, player_id, decisions, effect.get("order_ref") or f"{session}:order", session)
        rest = [c for c in looked if c not in recycled]
        order_spec = {"selection_kind": "ordered_permutation", "count": {"any_number": True}, "from": "revealed", "by": player_id, "visibility": "private_to_chooser", "identity_binding": True}
        order, o_meta = resolve_choice(new_state, order_spec, decision_ref=effect.get("put_back_ref") or f"{session}:put_back", decisions=decisions, controller=player_id, candidates=rest)
        _reorder_deck(new_state, player_id, order, "top")
        _drop_reveals(new_state, order)
        trace.update({"player": player_id, "requested_count": count, "looked_count": len(seen), "looked_hash": seen_hash, "burn_out": False,
                      "recycled_count": len(recycled), "recycled_hash": sub.get("objects_hash"), "recycle_order_decision": sub.get("order_decision"),
                      "put_back_count": len(order), "put_back_ordering_hash": _ids_hash(new_state, order), "visible_to": [player_id],
                      "selection": {"recycle": {k: v for k, v in r_meta.items() if k != "choice"}, "put_back": {k: v for k, v in o_meta.items() if k != "choice"}},
                      "completion": "full" if len(seen) == count else ("partial" if seen else "none")})
        if seen_banished:
            trace["disposable_count"] = len(looked)
        if not seen:
            trace["outcome"] = "no_op"

    elif op == "banish":
        # Core 427: straight from any zone into Banishment, as a new object
        # (124). Not a Kill (427.2.a), not a Discard (427.2.b).
        ids = list(effect.get("objects") or ([effect["object_id"]] if effect.get("object_id") else []))
        selection = effect.get("selection_meta")
        if effect.get("choice") is not None and not ids:
            chosen, selection = resolve_choice(new_state, effect["choice"], decision_ref=effect.get("decision_ref"), decisions=decisions, controller=effect.get("player") or effect.get("_controller"),
                                               execution=execution_suffix(effect))
            ids = list(chosen)
        identities: dict[str, str] = {}
        destinations: dict[str, str] = {}
        detached_all: list[dict[str, Any]] = []
        for object_id in ids:
            if object_id not in new_state["objects"]:
                raise ValueError(f"banish requires a known object; {object_id!r} is not in the state")
            obj = new_state["objects"][object_id]
            left_from = find_location(new_state, object_id)
            if zone_class(left_from) == "board":
                # package 11: noted before it moves (leave_board_triggers)
                trace.setdefault("pending_triggers", []).extend(leave_board_triggers(new_state, object_id))
            detached_all.extend(detach_records(new_state, object_id, _last_board_location(left_from), host_left_board=True))
            _remove_from_location(new_state, object_id)
            if obj.get("is_token"):
                del new_state["objects"][object_id]
                destinations[object_id] = "ceased_to_exist"
                continue
            if zone_class(left_from) == "board":
                # package 9 (Portal Rescue): a Unit banished from the board is a new object (Core 124) - its damage,
                # Might changes, exhaustion and designations stay behind, as for return_to_hand
                obj["damage"] = 0
                obj["might_modifiers"] = []
                obj["exhausted"] = False
                for transient in ("statuses", "counters", "combat_designation"):
                    obj.pop(transient, None)
            new_state["players"][obj["owner"]]["zones"]["banishment"].append(object_id)
            destinations[object_id] = f"{obj['owner']}.banishment"
            identities[object_id] = _bump_identity(new_state, object_id)
        _drop_reveals(new_state, ids)
        trace.update({"objects": ids, "destinations": destinations, "identities_after": identities, "not_kill": True, "not_discard": True,
                      **({"detached": detached_all} if detached_all else {}),
                      **({"selection": {k: v for k, v in selection.items() if k != "choice"}} if selection else {}),
                      "completion": "full" if ids else "none"})
        if not ids:
            trace["outcome"] = "no_op"

    elif op == "counter":
        # Core 425: a countered item has no effect and leaves the chain; its
        # card is put in the trash (425.1.a) unless the effect returns it; it
        # was not played (425.1.b) and no cost is refunded (425.1.c). The
        # timing chain is the caller's to update in the same commit.
        item_id = effect.get("chain_item_id")
        if item_id is None and isinstance(effect.get("object_id"), str):
            # package 10: the targeted spell - the Chain item that card is (its legality was checked as a target)
            item_id = next((k for k, v in (new_state.get("chain_items") or {}).items()
                            if v.get("card") == effect["object_id"]), None)
        entry = (new_state.get("chain_items") or {}).get(item_id)
        if entry is None:
            raise IllegalOperation(f"chain item {item_id!r} is not on the chain; only a chain item can be countered (Core 425.1)")
        if entry.get("counterable") is False:
            raise NotImplementedError(f"chain item {item_id!r} carries 'can't be countered'; the static that grants it is a P4 contract (unsupported: cannot_be_countered)")
        destination = effect.get("card_to", "trash")
        del new_state["chain_items"][item_id]
        if not new_state["chain_items"]:
            del new_state["chain_items"]
        card = entry.get("card")
        trace.update({"chain_item_id": item_id, "controller": entry.get("controller"), "not_played": True, "costs_refunded": False,
                      "countered_chain_items": [item_id]})
        if card is None:
            trace.update({"ability_id": entry.get("ability_id"), "source_object": entry.get("source_object"), "no_card": True, "destination": None})
        elif (entry.get("leave_replacement") or {}).get("kind") == "recycle":
            # package 9 (Kai'Sa - Evolutionary): Core 390.3.a - it leaves the Chain other than by its own instructions,
            # so it is recycled instead: the bottom of its owner's Main Deck (416), a new object (124)
            owner = new_state["objects"][card]["owner"]
            new_state["players"][owner]["zones"]["main_deck"].append(card)
            drop_play_bound_replacements(new_state["objects"][card], item_id)
            trace.update({"card": card, "destination": f"{owner}.main_deck", "recycled_instead": True,
                          "identity_after": _bump_identity(new_state, card),
                          "rule_locators": list(dict.fromkeys(trace["rule_locators"] + ["Core 390.3.a", "Core 416"]))})
        else:
            owner = new_state["objects"][card]["owner"]
            zone = "trash" if destination == "trash" else "hand"
            new_state["players"][owner]["zones"][zone].append(card)
            # 2026-09-28: a replacement bound to the countered play (Accelerate, "the next unit you
            # play enters ready") ends with it; the card played again is a new object (Core 124)
            drop_play_bound_replacements(new_state["objects"][card], item_id)
            trace.update({"card": card, "destination": f"{owner}.{zone}", "identity_after": _bump_identity(new_state, card)})
            if destination != "trash":
                trace["rule_locators"] = list(dict.fromkeys(trace["rule_locators"] + ["Core 359.3"]))

    elif op == "burn":
        # Core 440.1: the top cards of a Main Deck go to the trash as new
        # objects. A deck shorter than the count would Burn Out on a non-Draw
        # path (431.1.b), which this slice does not model.
        player_id, count = effect.get("player"), effect.get("count")
        if player_id not in new_state["players"]:
            raise ValueError("burn requires a known player")
        deck = new_state["players"][player_id]["zones"]["main_deck"]
        if len(deck) < count:
            raise NotImplementedError(f"[Burn {count}] would move more cards than {player_id}'s Main Deck holds ({len(deck)}); Burn Out outside a Draw is not modelled (unsupported: burn_out_non_draw)")
        burned = list(deck[:count])
        del deck[:count]
        identities = {}
        for object_id in burned:
            owner = new_state["objects"][object_id]["owner"]
            new_state["players"][owner]["zones"]["trash"].append(object_id)
            identities[object_id] = _bump_identity(new_state, object_id)
        trace.update({"player": player_id, "requested_count": count, "burned_count": len(burned), "objects": burned,
                      "identities_after": identities, "burn_out": False, "completion": "full"})

    elif op == "empower":
        # Core 441: a binary state for a Game Object on the board (441.1.a, 441.2). An
        # object that is already Empowered cannot be Empowered again — nothing
        # additional happens (441.1.b, 441.1.c) — UNLESS its own text grants the
        # permission 441.1.c.1 describes, in which case a further level is added
        # while it has room. Only the first one is the "becomes Empowered" event
        # of 441.2.a: the object is already Empowered for every level after it.
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("empower requires a known object")
        obj = new_state["objects"][object_id]
        if zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"Empowered is a state for objects on the board; {object_id!r} is not on it (441.2)")
        limit = obj.get(EMPOWER_LIMIT_FIELD, DEFAULT_EMPOWER_LIMIT)
        count = obj.get(EMPOWER_COUNT_FIELD, 1 if obj.get("empowered") else 0)
        if obj.get("empowered") and count >= limit:
            trace.update({"object_id": object_id, "outcome": "no_op", "completion": "none", "already_empowered": True,
                          "became_empowered": False, "empowered_count": count, "empower_limit": limit,
                          "reason": ("an Empowered object cannot be Empowered again (441.1.b, 441.1.c)"
                                     if limit == DEFAULT_EMPOWER_LIMIT else
                                     "the permission of 441.1.c.1 is spent: the object is at its limit")})
            return new_state, trace
        became = not obj.get("empowered")
        obj["empowered"] = True
        if limit > DEFAULT_EMPOWER_LIMIT:
            obj[EMPOWER_COUNT_FIELD] = count + 1
        trace.update({"object_id": object_id, "became_empowered": became, "already_empowered": not became,
                      "empowered_count": count + 1, "empower_limit": limit})
        if became:
            trace["event_hook"] = {"kind": "become_empowered", "object_id": object_id,
                                   "note": "P5 emits the event (441.2.a)"}

    elif op == "disempower":
        # Core 442.1: removes the Empowered status. Where a card was Empowered
        # several times under 441.1.c.1, one Disempower removes one level: the
        # object stays Empowered while any level remains.
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("disempower requires a known object")
        obj = new_state["objects"][object_id]
        if not obj.get("empowered"):
            trace.update({"object_id": object_id, "outcome": "no_op", "completion": "none",
                          "reason": "disempowering a card that is not Empowered does nothing (442.1.a.1)"})
            return new_state, trace
        count = obj.get(EMPOWER_COUNT_FIELD, 1)
        remaining = count - 1
        if remaining > 0:
            obj[EMPOWER_COUNT_FIELD] = remaining
        else:
            del obj["empowered"]
            obj.pop(EMPOWER_COUNT_FIELD, None)
        trace.update({"object_id": object_id, "disempowered": True, "levels_removed": 1,
                      "empowered_count": remaining, "still_empowered": remaining > 0})

    elif op == "buff":
        # Core 426.1.b: a Unit either has a Buff counter or it does not; a Unit
        # that already has one is still chosen, but is not Buffed (426.1.c).
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("buff requires a known object")
        obj = new_state["objects"][object_id]
        if obj.get("kind") != "unit" or zone_class(find_location(new_state, object_id)) != "board":
            raise IllegalOperation(f"Buffs are counters on Units on the board; {object_id!r} is not one (702)")
        if obj.get("buffed") and obj.get("any_number_of_buffs") is True:
            # package 9 (Lee Sin - Ascetic): permission to be Buffed several times (Core 426.1.b.2) - one more
            obj["buff_count"] = buff_count(obj) + 1
            trace.update({"object_id": object_id, "was_buffed": True, "already_buffed": True,
                          "buff_count": obj["buff_count"], "rule_locators": list(trace.get("rule_locators") or []) + ["Core 426.1.b.2"]})
            return new_state, trace
        if obj.get("buffed"):
            trace.update({"object_id": object_id, "outcome": "no_op", "completion": "none", "already_buffed": True,
                          "was_buffed": False, "reason": "the Unit already has a Buff counter (426.1.b)"})
            return new_state, trace
        obj["buffed"] = True
        trace.update({"object_id": object_id, "was_buffed": True, "already_buffed": False})

    elif op == "gain_point":
        # Core 471.1: a Score has the player Gain up to one Point. This op is
        # the Gain alone: the card names no Battlefield, so 471.2's Score
        # abilities have nothing to trigger at, and 470's once-per-Battlefield
        # limit has no Battlefield to count. 471.1.a.1 puts it beyond the Final
        # Point restrictions of 471.1.b, which reach Conquer only.
        #
        # Whether the new total ends the game is the victory procedure's
        # business (Core 196): this records the points and says what they are
        # now, and does not decide a winner from inside an effect.
        player_id, amount = effect.get("player"), effect.get("amount")
        if player_id not in new_state["players"] or not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise ValueError("gain_point requires a known player and a positive amount")
        before = int(new_state["players"][player_id].get("points", 0))
        new_state["players"][player_id]["points"] = before + amount
        trace.update({"player": player_id, "amount": amount, "before": before,
                      "after": before + amount, "source_is_conquer": False,
                      "scored_a_battlefield": False,
                      "note": "a point Gained from a source that is not Conquer (471.1.a.1); no "
                              "Battlefield was Scored, so no Score ability triggers (471.2) and "
                              "the once-per-Battlefield limit of 470 does not apply"})

    elif op == "win_game":
        # Core 195: an effect that instructs a player to win makes them win; 196: the game ends. The terminal
        # event is handed to the caller's two-state commit (resolution_bridge), exactly as a Burn Out victory's is.
        player_id = effect.get("player")
        if player_id not in new_state["players"]:
            raise ValueError("win_game requires a known player")
        trace.update({"player": player_id,
                      "terminal_event": {"kind": "terminal_event", "reason": "effect_victory", "winner": player_id,
                                         "immediate": True, "source": effect.get("effect_id"),
                                         "rule_locators": ["Core 195", "Core 196"]}})

    elif op == "gain_xp":
        player_id, amount = effect.get("player"), effect.get("amount")
        if player_id not in new_state["players"] or not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
            raise ValueError("gain_xp requires a known player and a positive amount")
        before = int(new_state["players"][player_id].get("xp", 0))
        new_state["players"][player_id]["xp"] = before + amount
        trace.update({"player": player_id, "amount": amount, "before": before, "after": before + amount})

    elif op == "remove_hidden":
        # Core 323 step 5: a Hidden card at a Battlefield its controller does not
        # also control goes to its owner's Trash. It leaves a hidden zone for a public one, so the card becomes
        # known here and the event says so.
        object_id = effect.get("object_id")
        location = find_location(new_state, object_id) if object_id in new_state["objects"] else None
        if location is None or location[0] != "facedown":
            raise ValueError("remove_hidden applies to a card in a Battlefield's Facedown Zone")
        obj = new_state["objects"][object_id]
        hidden_controller = location[2]
        _remove_from_location(new_state, object_id)
        new_state["players"][obj["owner"]]["zones"]["trash"].append(object_id)
        trace.update({"object_id": object_id, "from": f"facedown:{location[1]}", "battlefield": location[1],
                      "hidden_controller": hidden_controller, "destination": f"{obj['owner']}.trash",
                      "identity_after": _bump_identity(new_state, object_id)})

    elif op == "create_delayed_trigger":
        # ADR-0014 §2 / Core 124: the delayed trigger is bound to the identities
        # it was created with, so a target that becomes a new object no longer
        # matches it and the trigger is dropped instead of firing on a stranger.
        spec = copy.deepcopy(effect["delayed"])
        if spec["controller"] not in new_state["players"]:
            raise ValueError("create_delayed_trigger requires a known controller")
        this_turn = new_state.get("turn_id", DEFAULT_TURN_ID)
        waits = spec.get("waits_for") or {}
        if waits.get("turn") == "this_turn" and effect.get("ending_step_context") == this_turn:
            # 2026-09-27 package 6, Core 359.3.e.16 (its own example is Targon's Peak): "at the end of
            # this turn" once this turn's Ending Step has begun - the delayed ability's duration ended
            # before it was generated, so it is not generated and its instructions are ignored
            trace.update({"outcome": "no_op", "not_generated": True, "delayed_id": spec["delayed_id"],
                          "reason": "the Ending Step of this turn has begun; the delayed trigger's window has passed",
                          "rule_locators": OP_RULES[op] + ["Core 359.3.e.16"]})
            return new_state, trace
        if waits.get("turn") == "this_turn":
            # the end of the turn it is created in, bound now (Core 390.2)
            spec["waits_for"] = {"kind": "turn", "moment": "end_of_turn", "turn_id": this_turn}
        if effect.get("instance_context"):
            # GPT 2026-10-02 (package 6): the trigger instance that makes it is part of its id - the same source can
            # legally trigger twice in one turn, and each makes its own delayed trigger
            spec["delayed_id"] = f"{spec['delayed_id']}@{effect['instance_context']}"
        if any(entry["delayed_id"] == spec["delayed_id"] for entry in new_state.get("delayed_triggers", [])):
            raise ValueError(f"delayed trigger {spec['delayed_id']!r} already exists")
        spec["source_identity"] = object_identity(new_state, spec["source_object"]) or spec["source_object"]
        if spec.get("target_object") == DELAYED_OWN_TARGET:
            # package 10 (Noxian Guillotine): bound to the object this instruction targets (chosen at play)
            if effect.get("object_id") not in new_state["objects"]:
                raise ValueError("create_delayed_trigger bound to its own target needs that target resolved")
            spec["target_object"] = effect["object_id"]
        if spec.get("target_object") is not None:
            spec["target_identity"] = object_identity(new_state, spec["target_object"])
        spec["created_turn"] = this_turn
        if effect.get("effects"):
            # package 6: the program the trigger will run is the one this instruction carries - its
            # content hash rides on the trigger to the Chain (dispatch_program refuses any other)
            spec["effect_program_hash"] = hash_value(effect["effects"])
        new_state.setdefault("delayed_triggers", []).append(spec)
        trace.update({"player": spec["controller"], "delayed_id": spec["delayed_id"],
                      "source_object": spec["source_object"], "source_identity": spec["source_identity"],
                      "target_object": spec.get("target_object"), "target_identity": spec.get("target_identity"),
                      "waits_for": copy.deepcopy(spec["waits_for"]), "created_turn": spec["created_turn"]})

    elif op == "copy_object":
        # ADR-0013 §6 / Core 477.1: a Trait-layer effect over the copyable
        # traits the engine models. A clause that needs one it does not model —
        # name, tags, printed cost, domain — is refused rather than half-copied.
        source_object, request_id = effect.get("source_object"), effect.get("request_id")
        traits = set(effect.get("traits") or ["type", "rules_text"])
        if source_object not in new_state["objects"] or effect.get("object_id") not in new_state["objects"]:
            raise ValueError("copy_object requires a known source and target object")
        unmodelled = sorted(traits - COPYABLE_TRAITS)
        if unmodelled:
            raise NotImplementedError(
                f"copying {unmodelled} needs traits this model does not carry (Core 477.1); the engine refuses rather "
                "than copying half of it (unsupported: copy_unmodelled_traits)")
        target = effect["object_id"]
        entry = {
            "effect_id": f"copy:{request_id}", "kind": "copy_traits",
            "source": {"object": source_object, "identity": object_identity(new_state, source_object), "name": request_id},
            "affects": {"scope": "object", "object": target, "identity": object_identity(new_state, target) or f"{target}@0"},
            "layer": "trait", "timestamp": _next_timestamp(new_state),
            "value": {"source_object": source_object, "traits": sorted(traits), "request_id": request_id},
            "duration": {"kind": "permanent"}, "passive": False,
        }
        new_state.setdefault("continuous_effects", []).append(entry)
        trace.update({"object_id": target, "source_object": source_object, "request_id": request_id,
                      "traits": sorted(traits), "effect_id": entry["effect_id"], "layer": "trait"})

    elif op == "attach":
        # Core 434: linking two board cards. The attached card takes the
        # Top-Most card's location (434.4, not a Move) and nothing else about
        # either card changes (434.5.a) — an exhausted Equipment stays exhausted.
        object_id, host_id = effect.get("object_id"), effect.get("to")
        if object_id not in new_state["objects"] or host_id not in new_state["objects"]:
            raise ValueError("attach requires two known objects")
        if object_id == host_id:
            raise IllegalOperation("a card cannot be attached to itself (434.1.d)")
        obj, host = new_state["objects"][object_id], new_state["objects"][host_id]
        host_location = _last_board_location(find_location(new_state, host_id))
        if host_location is None:
            raise IllegalOperation(f"{host_id!r} is not on the board; attaching links two cards on the board (434.1.a)")
        if host.get("attached_to") is not None:
            raise NotImplementedError(f"{host_id!r} is itself attached; nested attachments are outside this slice (unsupported: nested_attachments)")
        if obj.get("attached_to") == host_id:
            trace.update({"object_id": object_id, "to": host_id, "outcome": "no_op", "completion": "none",
                          "reason": "already attached to that Top-Most card (434.2.b)"})
            return new_state, trace
        previous = obj.get("attached_to")
        if previous is not None:
            del obj["attached_to"]  # 434.2.a: attaching to a new host detaches from the old one
        _remove_from_location(new_state, object_id)
        destination = _place_on_board(new_state, object_id, host_location)
        obj["attached_to"] = host_id
        # ADR-0013 §6 / Core 477.2: the attached card's Effect Text is appended
        # to its Top-Most card while it stays attached.
        appended = None
        effect_text = {field: obj[field] for field in APPENDABLE_TRIGGER_FIELDS if obj.get(field) and (obj.get("effect_text_fields") is None or field in obj["effect_text_fields"])}
        if obj.get("effect_text"):
            effect_text = copy.deepcopy(obj["effect_text"])
        if effect_text:
            appended = {
                "effect_id": f"effect_text:{object_id}:{host_id}", "kind": "ability_append",
                "source": {"object": object_id, "identity": object_identity(new_state, object_id), "name": "effect_text"},
                "affects": {"scope": "object", "object": host_id, "identity": object_identity(new_state, host_id) or f"{host_id}@0"},
                "layer": "ability", "timestamp": _next_timestamp(new_state),
                "value": {"triggers": effect_text}, "duration": {"kind": "until_detached"}, "passive": True,
            }
            new_state.setdefault("continuous_effects", []).append(appended)
        trace.update({"object_id": object_id, "to": host_id, "detached_from": previous, "destination": destination,
                      "not_a_move": True, "state_unchanged": {"exhausted": obj.get("exhausted", False), "damage": obj.get("damage", 0)},
                      "might_bonus": obj.get("might_bonus", 0), "top_most": host_id,
                      **({"appended_effect_text": appended["effect_id"]} if appended else {})})

    elif op == "detach":
        object_id = effect.get("object_id")
        if object_id not in new_state["objects"]:
            raise ValueError("detach requires a known object")
        obj = new_state["objects"][object_id]
        host_id = obj.get("attached_to")
        if host_id is None:
            # Core 435.1.a: detaching a card that is not attached does nothing.
            trace.update({"object_id": object_id, "outcome": "no_op", "completion": "none", "reason": "the card is not attached (435.1.a)"})
            return new_state, trace
        host_location = _last_board_location(find_location(new_state, host_id))
        records = detach_records(new_state, host_id, host_location, host_left_board=False)
        record = next(r for r in records if r["object_id"] == object_id)
        for other in records:
            if other["object_id"] != object_id:
                # Only the named card detaches; put the others back.
                new_state["objects"][other["object_id"]]["attached_to"] = host_id
                new_state["objects"][other["object_id"]].pop("pending_recall", None)
        trace.update({"object_id": object_id, "detached_from": host_id, "destination": record.get("destination"),
                      **({"pending_recall": record["pending_recall"]} if record.get("pending_recall") else {}),
                      "top_most_remaining": [a for a in attachments(new_state, host_id)]})

    elif op == "emit_reflexive":
        triggers = effect.get("triggers")
        if not isinstance(triggers, list) or not triggers:
            raise ValueError("emit_reflexive requires one or more trigger descriptors")
        copied = copy.deepcopy(triggers)
        for index, descriptor in enumerate(copied):
            required = {"trigger_id", "controller", "source_object", "controller_order", "effect_program_id", "optional_at_finalize"}
            if not isinstance(descriptor, dict) or not required.issubset(descriptor):
                raise ValueError(f"reflexive trigger {index} has invalid shape")
            descriptor["trigger_kind"] = "reflexive"
        trace.update({"pending_triggers": copied, "reflexive_count": len(copied)})

    # 2026-10-15 package 13 (C2, PACKAGE13 ruling 2): a card this effect put in a non-Board zone is its owner's again
    returned = owners_again(new_state)
    if returned:
        trace["control_returned_to_owner"] = returned
    # 2026-10-15 package 13 (C2): a card this effect put where its abilities work has its own Replacement Effects
    materialized = materialize_printed_replacements(new_state)
    if materialized:
        trace["printed_replacements_added"] = materialized
    errors = validate_state(new_state)
    if errors:
        raise ValueError("effect produced invalid state: " + "; ".join(errors))
    return new_state, trace


# ---------------------------------------------------------- continuous effects --

def _legacy_timestamp(family_index: int, position: int) -> int:
    """A stable relative order for translated effects: families in the order
    they were added to the engine, positions within a family in list order.
    Timestamps are relative comparisons only (Core 480.1.a)."""
    return family_index * 1000 + position


def migrate_legacy_effects(state: dict[str, Any]) -> dict[str, Any]:
    """ADR-0013 §1: translate the legacy families into the canonical list, once,
    at the input boundary. Idempotent: a state that already carries
    `continuous_effects` is returned unchanged."""
    if state.get("continuous_effects") is not None:
        return state
    effects: list[dict[str, Any]] = []
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    for object_id in sorted(state["objects"]):
        obj = state["objects"][object_id]
        identity = obj.get("identity") or f"{object_id}@0"
        for position, modifier in enumerate(obj.get("might_modifiers", []) or []):
            amount = modifier["amount"]
            duration = ({"kind": "this_turn", "turn_id": modifier.get("turn_id", turn_id)}
                        if modifier.get("duration") == "this_turn" else {"kind": "permanent"})
            effects.append({
                "effect_id": f"legacy:might:{object_id}:{position}", "kind": "might_arithmetic",
                "source": {"object": modifier.get("source") if modifier.get("source") in state["objects"] or modifier.get("source") in state["battlefields"] else object_id,
                           "identity": None, "name": modifier.get("source")},
                "affects": {"scope": "object", "object": object_id, "identity": identity},
                "layer": "arithmetic", "sublayer": "increase" if amount >= 0 else "decrease",
                "timestamp": _legacy_timestamp(0, position), "value": {"amount": amount, "mode": "delta"},
                "duration": duration, "passive": False,
            })
        for position, modifier in enumerate(obj.get("keyword_modifiers", []) or []):
            duration = ({"kind": "this_combat", "combat_id": modifier["combat_id"]}
                        if modifier["duration"] == "this_combat" else {"kind": "this_turn", "turn_id": modifier.get("turn_id", turn_id)})
            value = {"keyword": modifier["keyword"]}
            if "value" in modifier:
                value["value"] = modifier["value"]
            effects.append({
                "effect_id": f"legacy:keyword:{object_id}:{modifier['modifier_id']}", "kind": "keyword_grant",
                "source": {"object": modifier.get("source") if modifier.get("source") in state["objects"] else object_id, "identity": None, "name": modifier.get("source")},
                "affects": {"scope": "object", "object": object_id, "identity": modifier["target_identity"]},
                "layer": "ability", "timestamp": _legacy_timestamp(2, position), "value": value,
                "duration": duration, "passive": False,
            })
    for position, aura in enumerate(state.get("might_auras", []) or []):
        effects.append({
            "effect_id": f"legacy:aura:{aura['modifier_id']}", "kind": "might_arithmetic",
            "source": {"object": aura["source_object"], "identity": None},
            "affects": {"scope": "criteria", "criteria": {"aura_controller": aura["controller"], "relation": "same_side"}},
            "layer": "arithmetic", "sublayer": "increase" if aura["amount"] >= 0 else "decrease",
            "timestamp": _legacy_timestamp(3, position), "value": {"amount": aura["amount"], "mode": "delta"},
            "condition": copy.deepcopy(aura["condition"]), "duration": {"kind": "while_source_active"}, "passive": True,
        })
    for position, modifier in enumerate(state.get("damage_modifiers", []) or []):
        effects.append({
            "effect_id": f"legacy:bonus:{modifier['modifier_id']}", "kind": "bonus_damage",
            "source": {"object": modifier["source_object"], "identity": None},
            "affects": {"scope": "criteria", "criteria": {"bonus_scope": copy.deepcopy(modifier["scope"]), "controller": modifier["controller"]}},
            "layer": "arithmetic", "sublayer": "increase",
            "timestamp": _legacy_timestamp(4, position), "value": {"amount": modifier["amount"]},
            "duration": {"kind": "while_source_active"}, "passive": True,
        })
    if not effects:
        # Nothing to translate: the state is already canonical in the only sense
        # that matters, and a no-op transition must not rewrite it.
        return state
    migrated = copy.deepcopy(state)
    for object_id in migrated["objects"]:
        migrated["objects"][object_id].pop("keyword_modifiers", None)
        migrated["objects"][object_id]["might_modifiers"] = []  # the schema still requires the list; it stays empty
    for field in ("might_auras", "damage_modifiers"):
        migrated.pop(field, None)
    migrated["continuous_effects"] = effects
    return migrated


def _next_timestamp(state: dict[str, Any]) -> int:
    """Core 480: a relative comparison, so one past every effect that already applies."""
    return max((e["timestamp"] for e in canonical_effects(state)), default=-1) + 1


def leave_board_triggers(state: dict[str, Any], object_id: str) -> list[dict[str, Any]]:
    """2026-10-12 package 11 (Treasure Trove: "When this leaves the board, draw 1 and channel 1 rune exhausted."; GPT
    PACKAGE11 ruling 8): the object's abilities that trigger as it leaves the board, however it leaves - killed,
    returned to a hand, banished - noted before it moves, as a death trigger is (Core 359.3.e.13: what moves can be
    looked back at). Each is one Pending trigger of the game action that moved it."""
    return [{**copy.deepcopy(t), "trigger_kind": t.get("trigger_kind", "triggered")}
            for t in object_triggers(state, object_id, "leave_board_triggers")]


# The state-level lists whose entries are a permanent's own abilities (each names its source_object and controller)
SOURCE_LISTS = ("damage_modifiers", "might_auras", "replacement_effects")


def follow_controller(state: dict[str, Any], object_id: str, player: str) -> None:
    """Core 191.5.a: an ability's controller is its source's - so when a permanent changes controller, its own triggered
    abilities (the printed descriptors) and the state-level entries it adds as its source become the new controller's.
    An ability already on the Chain is not touched (gain_control); a granted or created replacement names no source."""
    obj = state["objects"][object_id]
    for field in APPENDABLE_TRIGGER_FIELDS:
        # a printed descriptor's source is its own object (validate_state); one that works from a non-Board zone
        # (functions_from / active_zone, Core 385.2) is its owner's wherever the card is (Core 191.5.a.1)
        for descriptor in obj.get(field) or []:
            if "functions_from" in descriptor or "active_zone" in descriptor:
                continue
            descriptor["controller"] = player
    for name in SOURCE_LISTS:
        for entry in state.get(name) or []:
            if isinstance(entry, dict) and entry.get("source_object") == object_id:
                entry["controller"] = player
    # the same entries once migrated (a passive translated from damage_modifiers / might_auras); the printed ones on the
    # object are read live and need nothing
    for effect in state.get("continuous_effects") or []:
        if effect.get("passive") and (effect.get("source") or {}).get("object") == object_id:
            criteria = (effect.get("affects") or {}).get("criteria") or {}
            for key in ("controller", "aura_controller"):
                if key in criteria:
                    criteria[key] = player


# The zones a card is its owner's in (Core 191.5.a.1): not the Board, not a Legend Zone, not the Chain or a facedown zone
OWNER_ZONES = ("hand", "trash", "main_deck", "banishment", "rune_deck", "champion_zone")


def owners_again(state: dict[str, Any]) -> list[str]:
    """Every object in one of its player's OWNER_ZONES whose controller is not its owner becomes its owner's again, its
    own abilities too (Core 191.5.a.1) - what it triggered as it left the Board was made before it moved, and an ability
    on the Chain keeps its controller. Returns the ids changed."""
    changed = []
    for object_id in sorted(state.get("objects") or {}):
        obj = state["objects"][object_id]
        where = find_location(state, object_id)
        if where is None or where[0] != "player" or where[2] not in OWNER_ZONES:
            continue
        if obj.get("controller") != obj.get("owner") and obj.get("owner") in state.get("players", {}):
            obj["controller"] = obj["owner"]
            follow_controller(state, object_id, obj["owner"])
            changed.append(object_id)
    return changed


def object_triggers(state: dict[str, Any], object_id: str, field: str) -> list[dict[str, Any]]:
    """The object's printed abilities of that kind plus everything the Ability
    layer appended — the Effect Text of attached cards (Core 477.2) and a copy's
    rules text (477.1). Every scheduler reads through here."""
    printed = list(state["objects"].get(object_id, {}).get(field, []) or [])
    appended = characteristics(state, object_id)["triggers"].get(field, [])
    return printed + [copy.deepcopy(descriptor) for descriptor in appended]


def prune_dead_effects(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Core 124.1 / 476.3: an effect bound to an identity that has changed can
    never apply again, so it is removed with its reason. A source that is
    merely inactive is left alone — it can become active again (365.1)."""
    removed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for effect in state.get("continuous_effects", []) or []:
        active, reason = _effect_active(state, effect)
        if not active and reason in {"identity_changed", "source_identity_changed"}:
            removed.append({"effect_id": effect["effect_id"], "kind": effect["kind"], "removal": {"reason": reason}})
        else:
            kept.append(effect)
    if removed:
        state["continuous_effects"] = kept
    return removed


def effects_for(state: dict[str, Any], object_id: str, kind: str | None = None, *, active_only: bool = False) -> list[dict[str, Any]]:
    """Every canonical continuous effect that names this object, optionally of
    one kind and optionally only those still applying. The read side callers
    and gates use instead of reaching into the state."""
    found = [e for e in canonical_effects(state)
             if (kind is None or e["kind"] == kind) and _effect_applies_to(state, e, object_id)]
    return [e for e in found if _effect_active(state, e)[0]] if active_only else found


def canonical_effects(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The state's continuous effects, translating a legacy state on the way.
    Every runtime reader goes through here, so nothing is read twice."""
    if state.get("continuous_effects") is not None:
        return state["continuous_effects"]
    return migrate_legacy_effects(state).get("continuous_effects", [])


def _effect_active(state: dict[str, Any], effect: dict[str, Any]) -> tuple[bool, str]:
    """Duration and source activity (Core 317.2.c, 466.7.c, 365.1)."""
    duration = effect["duration"]
    if duration["kind"] == "this_turn" and duration.get("turn_id") != state.get("turn_id", DEFAULT_TURN_ID):
        return False, "expired_turn"
    if duration["kind"] == "while_source_active" and not source_active(state, effect["source"]["object"]):
        return False, "source_inactive"
    if duration["kind"] == "this_combat":
        target = effect["affects"].get("object")
        designation = state["objects"].get(target, {}).get("combat_designation") if target else None
        if designation is None or designation.get("combat_id") != duration.get("combat_id"):
            return False, "other_combat"
    identity = effect["affects"].get("identity")
    if identity is not None and effect["affects"].get("scope") == "object":
        current = object_identity(state, effect["affects"]["object"]) or f"{effect['affects']['object']}@0"
        if current != identity:
            return False, "identity_changed"
    source_identity = effect["source"].get("identity")
    if source_identity is not None:
        current = object_identity(state, effect["source"]["object"])
        if current is not None and current != source_identity:
            return False, "source_identity_changed"
    return True, "active"


def printed_aura_effects(state: dict[str, Any]) -> list[dict[str, Any]]:
    """A card's printed static aura ("Other friendly units have +1 [M] here.") as the
    continuous effect it is while its source is on the board (Core 365.1, 476-480), read
    live from the object - never stored, so an aura that entered after the state's legacy
    fields were migrated is still read, and one that left stops at once (2026-09-24)."""
    # package 15: on a state held frozen (frozen_inputs), computed once - a pure function of the state; a copy handed out
    if (entry := _frozen(state)) is not None:
        if "auras" not in entry:
            entry["auras"] = _printed_aura_effects(state)
        return copy.deepcopy(entry["auras"])
    return _printed_aura_effects(state)


def _printed_aura_effects(state: dict[str, Any]) -> list[dict[str, Any]]:
    effects = []
    for object_id in sorted(state.get("objects") or {}):
        obj = state["objects"][object_id]
        for position, aura in enumerate(obj.get("static_auras", []) or []):
            if "keyword" in aura:
                # 2026-09-27: a keyword aura is granted in the Ability layer (477.2, 477.2.b)
                effects.append({
                    "effect_id": f"printed:aura:{object_id}:{aura.get('aura_id', position)}", "kind": "keyword_grant",
                    "source": {"object": object_id, "identity": obj.get("identity") or f"{object_id}@0"},
                    "affects": {"scope": "criteria", "criteria": {**copy.deepcopy(aura["criteria"]), "printed_aura_source": object_id,
                                                                  "aura_controller": obj.get("controller")}},
                    "layer": "ability", "timestamp": _legacy_timestamp(6, position), "value": _keyword_value(aura),
                    "duration": {"kind": "while_source_active"}, "passive": True,
                })
                continue
            amount = aura["amount"]
            effects.append({
                "effect_id": f"printed:aura:{object_id}:{aura.get('aura_id', position)}", "kind": "might_arithmetic",
                "source": {"object": object_id, "identity": obj.get("identity") or f"{object_id}@0"},
                "affects": {"scope": "criteria", "criteria": {**copy.deepcopy(aura["criteria"]), "printed_aura_source": object_id,
                                                              "aura_controller": obj.get("controller")}},
                "layer": "arithmetic", "sublayer": "increase" if amount >= 0 else "decrease",
                "timestamp": _legacy_timestamp(6, position),
                # package 6: the aura's own floor, applied fresh (a passive does not snapshot, 477.3.b)
                "value": {"amount": amount, "mode": "delta", **({"minimum": aura["minimum"]} if "minimum" in aura else {})},
                "duration": {"kind": "while_source_active"}, "passive": True,
            })
    # a Battlefield's own printed aura ("Units here have +1 [M]."): every Unit at it, either side
    for battlefield_id in sorted(state.get("battlefields") or {}):
        for position, aura in enumerate(state["battlefields"][battlefield_id].get("static_auras", []) or []):
            if "keyword" in aura:
                # 2026-09-27: "Units here have [Ganking]."
                effects.append({
                    "effect_id": f"printed:aura:{battlefield_id}:{aura.get('aura_id', position)}", "kind": "keyword_grant",
                    "source": {"object": battlefield_id, "identity": f"{battlefield_id}@0"},
                    "affects": {"scope": "criteria", "criteria": {**copy.deepcopy(aura["criteria"]), "printed_aura_battlefield": battlefield_id}},
                    "layer": "ability", "timestamp": _legacy_timestamp(7, position), "value": _keyword_value(aura),
                    "duration": {"kind": "while_source_active"}, "passive": True,
                })
                continue
            amount = aura["amount"]
            effects.append({
                "effect_id": f"printed:aura:{battlefield_id}:{aura.get('aura_id', position)}", "kind": "might_arithmetic",
                "source": {"object": battlefield_id, "identity": f"{battlefield_id}@0"},
                "affects": {"scope": "criteria", "criteria": {**copy.deepcopy(aura["criteria"]), "printed_aura_battlefield": battlefield_id}},
                "layer": "arithmetic", "sublayer": "increase" if amount >= 0 else "decrease",
                "timestamp": _legacy_timestamp(7, position), "value": {"amount": amount, "mode": "delta"},
                "duration": {"kind": "while_source_active"}, "passive": True,
            })
    # 2026-09-27: a card's own conditional keyword ("While I'm buffed, I have [Ganking].") - on
    # the card itself, while it is on the board (365.1), applied only while its condition holds
    for object_id in sorted(state.get("objects") or {}):
        obj = state["objects"][object_id]
        identity = obj.get("identity") or f"{object_id}@0"
        for position, conditional in enumerate(obj.get("conditional_keywords", []) or []):
            effects.append({
                "effect_id": f"printed:conditional_keyword:{object_id}:{conditional['modifier_id']}", "kind": "keyword_grant",
                "source": {"object": object_id, "identity": identity},
                "affects": {"scope": "object", "object": object_id, "identity": identity},
                "layer": "ability", "timestamp": _legacy_timestamp(8, position), "value": _keyword_value(conditional),
                "condition": copy.deepcopy(conditional["condition"]),
                "duration": {"kind": "while_source_active"}, "passive": True,
            })
        # 2026-10-15 package 13 (C2): the card's own printed Might statics and Bonus Damage - the same effects the legacy
        # families translated to (same layer, same relative order), read from the object as it is now
        for position, conditional in enumerate(obj.get("conditional_might", []) or []):
            amount = conditional["amount"]
            effects.append({
                "effect_id": f"printed:conditional:{object_id}:{conditional['modifier_id']}", "kind": "might_arithmetic",
                "source": {"object": object_id, "identity": identity},
                "affects": {"scope": "object", "object": object_id, "identity": identity},
                "layer": "arithmetic", "sublayer": "increase" if amount >= 0 else "decrease",
                "timestamp": _legacy_timestamp(1, position), "value": {"amount": amount, "mode": "delta"},
                "condition": copy.deepcopy(conditional["condition"]), "duration": {"kind": "while_source_active"}, "passive": True,
            })
        for position, dynamic in enumerate(obj.get("dynamic_might", []) or []):
            effects.append({
                "effect_id": f"printed:dynamic:{object_id}:{dynamic['modifier_id']}", "kind": "might_arithmetic",
                "source": {"object": object_id, "identity": identity},
                "affects": {"scope": "object", "object": object_id, "identity": identity},
                "layer": "arithmetic", "sublayer": "increase",
                "timestamp": _legacy_timestamp(5, position), "value": {"amount": dynamic["amount"], "mode": "delta", "per": dict(dynamic["per"])},
                "duration": {"kind": "while_source_active"}, "passive": True,
            })
        for position, aura in enumerate(obj.get("printed_might_auras", []) or []):
            effects.append({
                "effect_id": f"printed:might_aura:{object_id}:{position}", "kind": "might_arithmetic",
                "source": {"object": object_id, "identity": identity},
                "affects": {"scope": "criteria", "criteria": {"aura_controller": obj.get("controller"), "relation": "same_side"}},
                "layer": "arithmetic", "sublayer": "increase" if aura["amount"] >= 0 else "decrease",
                "timestamp": _legacy_timestamp(3, position), "value": {"amount": aura["amount"], "mode": "delta"},
                "condition": copy.deepcopy(aura["condition"]), "duration": {"kind": "while_source_active"}, "passive": True,
            })
        effects += _printed_bonus(object_id, identity, obj.get("controller"), obj.get("printed_damage_modifiers"))
    for battlefield_id in sorted(state.get("battlefields") or {}):
        battlefield = state["battlefields"][battlefield_id]
        effects += _printed_bonus(battlefield_id, f"{battlefield_id}@0", battlefield.get("controller"),
                                  battlefield.get("printed_damage_modifiers"))
    return effects


def _printed_bonus(source: str, identity: str, controller: str | None, modifiers: list | None) -> list[dict[str, Any]]:
    """A card's own Bonus Damage (Core 713-715), as the legacy damage_modifiers translated to - its controller the
    source's current one."""
    return [{"effect_id": f"printed:bonus:{source}:{position}", "kind": "bonus_damage",
             "source": {"object": source, "identity": identity},
             "affects": {"scope": "criteria", "criteria": {"bonus_scope": copy.deepcopy(modifier["scope"]), "controller": controller}},
             "layer": "arithmetic", "sublayer": "increase",
             "timestamp": _legacy_timestamp(4, position), "value": {"amount": modifier["amount"]},
             "duration": {"kind": "while_source_active"}, "passive": True}
            for position, modifier in enumerate(modifiers or [])]


def _keyword_value(entry: dict[str, Any]) -> dict[str, Any]:
    """The {keyword, value?} a keyword aura or a conditional keyword grants."""
    return {"keyword": entry["keyword"], **({"value": entry["value"]} if "value" in entry else {}),
            **({"only_if_absent": True} if entry.get("only_if_absent") is True else {})}


def _static_keyword_problem(entry: dict[str, Any]) -> bool:
    """A printed keyword aura / conditional keyword names a keyword the engine reads off the
    computed characteristics, and a value only where values are summed (807.2, 809.2, 814.2)."""
    keyword = entry.get("keyword")
    if keyword not in STATIC_AURA_KEYWORDS:
        return True
    if "value" in entry:
        value = entry["value"]
        return keyword not in SUMMED_VALUE_KEYWORDS or not isinstance(value, int) or isinstance(value, bool) or value < 1
    return False


STATIC_AURA_CRITERIA = {"kind", "controller_relation", "exclude_source", "at_source_battlefield", "buffed", "stunned"}
# the criteria that are flags (true, or absent); package 6 (2026-09-27): `stunned` - only a Unit
# that is Stunned right now (Core 423.1.a: a binary state)
STATIC_AURA_FLAGS = ("exclude_source", "at_source_battlefield", "buffed", "stunned")
BATTLEFIELD_AURA_CRITERIA = {"kind"}


def _battlefield_aura_applies(state: dict[str, Any], criteria: dict[str, Any], object_id: str) -> bool:
    where = find_location(state, object_id)
    if where is None or where[0] != "battlefield" or where[1] != criteria["printed_aura_battlefield"]:
        return False
    return "kind" not in criteria or (state["objects"].get(object_id) or {}).get("kind") == criteria["kind"]


def _printed_aura_applies(state: dict[str, Any], criteria: dict[str, Any], object_id: str) -> bool:
    source = criteria["printed_aura_source"]
    obj = state["objects"].get(object_id) or {}
    where = find_location(state, object_id)
    if zone_class(where) != "board":
        return False
    if "kind" in criteria and obj.get("kind") != criteria["kind"]:
        return False
    relation = criteria.get("controller_relation")
    if relation is not None and same_side(state, criteria["aura_controller"], obj.get("controller")) != (relation == "friendly"):
        return False
    if criteria.get("exclude_source") and object_id == source:
        return False
    if criteria.get("at_source_battlefield"):
        at = find_location(state, source)
        if at is None or at[0] != "battlefield" or where[0] != "battlefield" or where[1] != at[1]:
            return False
    if criteria.get("buffed") and not obj.get("buffed"):
        return False
    if criteria.get("stunned") and not obj.get("stunned"):
        return False
    return True


def _effect_applies_to(state: dict[str, Any], effect: dict[str, Any], object_id: str) -> bool:
    affects = effect["affects"]
    if affects["scope"] == "object":
        return affects["object"] == object_id
    criteria = affects.get("criteria") or {}
    if "printed_aura_source" in criteria:
        return _printed_aura_applies(state, criteria, object_id)
    if "printed_aura_battlefield" in criteria:
        return _battlefield_aura_applies(state, criteria, object_id)
    if "aura_controller" in criteria:
        return same_side(state, criteria["aura_controller"], state["objects"][object_id].get("controller"))
    return False


def _condition_holds(state: dict[str, Any], effect: dict[str, Any], object_id: str) -> bool:
    """The two conditions the legacy families carry; C-50 replaces this with the
    typed condition.v1 AST."""
    condition = effect.get("condition")
    if condition is None:
        return True
    return evaluate_condition(state, condition, controller=state["objects"][object_id]["controller"], object_id=object_id)


def _read_per(state: dict[str, Any], effect: dict[str, Any]) -> dict[str, Any]:
    """A passive "increased by <quantity>" effect with its amount as the board has it
    now (477.3.b: no snapshot). controller_points: the points of the source's
    controller (Draven - Showboat, "your points")."""
    value = effect["value"]
    per = value.get("per")
    if per is None:
        return effect
    count = per_count(state, effect["source"]["object"], per["kind"])
    return {**effect, "value": {k: v for k, v in value.items() if k != "per"} | {"amount": value["amount"] * count}}


def per_count(state: dict[str, Any], source_id: str, kind: str) -> int:
    """The quantity a passive "for each" / "increased by" reads, as the board has it now.
    controller_points: the source's controller's points. buffed_friendly_units_at_source_battlefield
    (2026-09-27): Units with a Buff counter (702.2.a) at the Battlefield the source is at, friendly
    to its controller - the source itself included, since the text says "friendly", not "other";
    none while the source is not at a Battlefield. controller_trash_count (2026-09-27): the cards
    in the source's controller's Trash, a public zone (108.2.b)."""
    source = state["objects"].get(source_id) or {}
    controller = source.get("controller")
    if kind == "controller_points":
        return int((state["players"].get(controller) or {}).get("points", 0))
    if kind == "controller_trash_count":
        return len(((state["players"].get(controller) or {}).get("zones") or {}).get("trash", []))
    if kind == "buffed_friendly_units_at_source_battlefield":
        at = find_location(state, source_id)
        if at is None or at[0] != "battlefield":
            return 0
        return sum(1 for other in state["battlefields"][at[1]].get("objects", []) or []
                   if (state["objects"].get(other) or {}).get("kind") == "unit"
                   and state["objects"][other].get("buffed")
                   and same_side(state, controller, state["objects"][other].get("controller")))
    raise ConditionUnsupported(f"a passive per-each over {kind!r} is not counted (unsupported: might_per_kind_unknown)")


def _applied_amount(effect: dict[str, Any], current: int) -> int:
    """Core 477.3: a delta, or an 'increased to N' that computes what it adds
    now; a player never increases by a negative amount (477.3.c).

    477.3.b is the subtle half. A limited arithmetic effect whose source is NOT
    a passive ability takes its limit once, when it is applied, and keeps that
    limited amount for as long as it lasts - Riot calls this snapshotting. So once such an effect has a `snapshot_amount`,
    that is what it contributes, and the board moving afterwards cannot change
    it. Recomputing the bound on every evaluation is a different game: a Unit
    that was at 5 when "-4 to a minimum of 1" hit it keeps the whole -4 when a
    buff later falls off, and ends at -2 (read as 0 by 143.2.b), not at 1.

    A PASSIVE source does not snapshot, so its bounds are applied fresh every
    time - which is why 479.1's example can have two limited effects each
    altering what the other applies."""
    value = effect["value"]
    if value.get("mode", "delta") == "increase_to":
        return max(0, value["amount"] - current)
    if "snapshot_amount" in value:
        return value["snapshot_amount"]
    # a floor limits a decrease and a cap an increase, never reversing it (GPT 2026-10-02, Leona - Zealot)
    return _bounded_amount(current, value["amount"], value.get("minimum"), value.get("maximum"))


# ------------------------------------------------------------------ condition.v1 --
# ADR-0013 §3: a restricted typed AST. Every leaf names explicit state and the
# visibility it needs; free text and embedded programs are not accepted, and a
# leaf that would read a zone the asking perspective cannot see is refused.
CONDITION_NODES = {"and", "or", "not"}
CONDITION_LEAVES = {
    "runes_at_least": {"count"},
    "attacking_or_defending_alone": set(),
    "friendly_unit_defends_alone": set(),
    # 2026-09-27 package 6: "if there is a ready enemy unit here" - the units counted may be narrowed
    # by a state (exhausted / damaged, Core 414.2, 415.2, 142) and located "here": at the Battlefield
    # where the condition's object - by default the program's own source - stands now (Core 359.3.f.2)
    "controls_units": {"count", "location", "controller_relation", "exhausted", "damaged", "tag"},
    # 2026-09-27 package 6: "if I am at a battlefield" - the object (default: the program's source)
    # stands at a Battlefield now, not in a Base or off the board (Core 107.2.b)
    "at_a_battlefield": {"object"},
    # 2026-09-27 package 6: `tag` - "if you control a Poro": only Units whose printed tags hold it (Core 133.8.a)
    "might_at_least": {"count", "object"},
    "has_keyword": {"keyword", "object"},
    "is_empowered": {"object"},
    "xp_at_least": {"count", "player"},
    "battlefield_controlled": {"battlefield", "controller_relation"},
    "zone_count_at_least": {"zone", "count", "player"},
    # C-56: "another unit you control *here*" and "less Might than me" are the
    # two comparisons the Core's own replacement examples are written in.
    "same_location_as": {"object", "as"},
    "might_less_than": {"object", "than"},
    # "another *unit* you control": the type as the layers compute it (477.1),
    # so a card copying a Unit counts as one.
    "object_kind": {"object", "value"},
    # Round H: the first leaf of the narrow self-card cost reduction. Every
    # fact it needs is on the state the play is being judged against.
    "score_within_of_victory": {"count", "who"},
    # Legion (Core 812.1.b.1, 812.1.c): some other card already played by you this turn -
    # a card other than `object` Finalized by `player` this turn (419.4.b).
    "another_card_finalized_this_turn": {"object", "player"},
    # 2026-09-27: "While I'm buffed" - the object has a Buff counter (702.2.a)
    "is_buffed": {"object"},
    # 2026-09-27: "If you've discarded a card this turn" - `player` (default: the effect's
    # controller) discarded at least `count` cards this turn (422.1), from the per-turn ledger
    "cards_discarded_this_turn_at_least": {"count", "player"},
    # 2026-09-27: "If an opponent controls a battlefield" - some Battlefield is controlled by a
    # player on that side of the effect's controller (190.2.b: controlled by a specific player or by no one)
    "controls_a_battlefield": {"controller_relation"},
    # "If an enemy unit has died this turn" (Spoils of War): a Unit controlled - when it died -
    # by a player on the given side of the asking controller died this turn (Core 428.1, 428.2.a).
    # Read off the per-turn ledger the Kill action writes (units_died_this_turn); a death a
    # Replacement Effect replaced never happened (370.1.a.1) and is not in it.
    "unit_died_this_turn": {"controller_relation"},
    # package 9 (Kayn - Unleashed): "If I have moved twice this turn" - the object's real Moves this turn
    # (moves_this_turn, per identity), at least `count`
    "moved_this_turn_at_least": {"count", "object"},
}
CONDITION_REQUIRED = {"moved_this_turn_at_least": {"count"}, "runes_at_least": {"count"}, "controls_units": {"count"}, "might_at_least": {"count"},
                      "has_keyword": {"keyword"}, "xp_at_least": {"count"}, "battlefield_controlled": {"battlefield"},
                      "zone_count_at_least": {"zone", "count"}, "same_location_as": {"as"},
                      "might_less_than": {"than"}, "object_kind": {"value"},
                      "score_within_of_victory": {"count"}, "cards_discarded_this_turn_at_least": {"count"},
                      "controls_a_battlefield": {"controller_relation"}, "unit_died_this_turn": {"controller_relation"}}
PRIVATE_ZONES = {"hand", "main_deck", "rune_deck"}
# "for each card in your trash" (Rhasa the Sunderer): the zones a printed per-each
# reduction may count - public ones, so no perspective is needed to count them.
PUBLIC_COUNT_ZONES = {"trash"}
# "This spell's Energy cost is reduced by the highest Might among units you control." (Sky
# Splitter): a printed reduction of 1 per point of the highest Might among the Units the
# player playing it controls on the board (Core 355.9.a.1: "unit" is a Unit on the board),
# read as the cost is determined (356.4, 356.4.b); 0 with no Unit, and 356.6 keeps the cost
# at 0 or above. The Might is the Unit's Might as the layers compute it (476-480).
HIGHEST_MIGHT_YOU_CONTROL = "highest_might_among_units_you_control"


class ConditionUnsupported(NotImplementedError):
    """A condition the engine will not evaluate: an unknown leaf, or one that
    needs information the asking perspective cannot see."""


def validate_condition(condition: Any, path: str = "condition") -> list[str]:
    if not isinstance(condition, dict) or not isinstance(condition.get("kind"), str):
        return [f"{path} must be an object with a kind"]
    kind = condition["kind"]
    if kind in CONDITION_NODES:
        if kind == "not":
            if set(condition) != {"kind", "of"}:
                return [f"{path}.not must carry exactly of"]
            return validate_condition(condition["of"], f"{path}.of")
        if set(condition) != {"kind", "of"} or not isinstance(condition["of"], list) or len(condition["of"]) < 2:
            return [f"{path}.{kind} must carry an `of` array of at least two conditions"]
        return [e for index, child in enumerate(condition["of"]) for e in validate_condition(child, f"{path}.of[{index}]")]
    if kind not in CONDITION_LEAVES:
        return [f"{path}.kind {kind!r} is not a condition.v1 leaf"]
    allowed = CONDITION_LEAVES[kind] | {"kind"}
    if set(condition) - allowed or not CONDITION_REQUIRED.get(kind, set()) <= set(condition):
        return [f"{path}.{kind} must carry {sorted(CONDITION_REQUIRED.get(kind, set()))} and only {sorted(allowed - {'kind'})}"]
    for field in ("count",):
        if field in condition and (not isinstance(condition[field], int) or isinstance(condition[field], bool) or condition[field] < 0):
            return [f"{path}.{field} must be a non-negative integer"]
    if "controller_relation" in condition and condition["controller_relation"] not in {"friendly", "enemy"}:
        return [f"{path}.controller_relation must be friendly or enemy"]
    if "location" in condition and condition["location"] not in {"board", "battlefield", "base", "here"}:
        return [f"{path}.location must be board, battlefield, base or here"]
    if kind == "controls_units" and any(
            field in condition and not isinstance(condition[field], bool) for field in ("exhausted", "damaged")):
        return [f"{path}.exhausted / damaged must be true or false"]
    if "zone" in condition and condition["zone"] not in PLAYER_ZONES:
        return [f"{path}.zone must be one of {sorted(PLAYER_ZONES)}"]
    if "tag" in condition and (not isinstance(condition["tag"], str) or not condition["tag"]):
        return [f"{path}.tag must be a non-empty string, as printed"]
    return []


def evaluate_condition(state: dict[str, Any], condition: dict[str, Any], *, controller: str | None = None,
                       object_id: str | None = None, perspective: str | None = None) -> bool:
    """ADR-0013 §3. `controller` is the effect's controller, `object_id` the
    object it is about, `perspective` the player asking — a leaf that needs a
    private zone of anyone else is refused rather than answered."""
    problems = validate_condition(condition)
    if problems:
        raise ValueError("; ".join(problems))
    kind = condition["kind"]
    if kind == "not":
        return not evaluate_condition(state, condition["of"], controller=controller, object_id=object_id, perspective=perspective)
    if kind in {"and", "or"}:
        results = [evaluate_condition(state, child, controller=controller, object_id=object_id, perspective=perspective) for child in condition["of"]]
        return all(results) if kind == "and" else any(results)
    subject = condition.get("object", object_id)
    if kind == "runes_at_least":
        owner = controller or (state["objects"][subject]["controller"] if subject else None)
        return runes_on_board(state, owner) >= condition["count"]
    if kind == "attacking_or_defending_alone":
        designation = state["objects"][subject].get("combat_designation") if subject else None
        return designation is not None and is_alone(state, subject)
    if kind == "friendly_unit_defends_alone":
        designation = state["objects"][subject].get("combat_designation") if subject else None
        return designation is not None and designation.get("role") == "defender" and is_alone(state, subject)
    if kind == "score_within_of_victory":
        # "if an opponent's score is within N points of the Victory Score".
        # Every part of that is on the state, or the condition abstains: the
        # Mode of Play carries the Victory Score, and teams and several
        # opponents are cases this leaf deliberately does not decide.
        mode = state.get("mode") if isinstance(state.get("mode"), dict) else {}
        victory = mode.get("victory_score")
        if not isinstance(victory, int) or isinstance(victory, bool):
            raise ConditionUnsupported("the Mode of Play does not say the Victory Score (cost_condition_not_observed)")
        if mode.get("teams") or any(isinstance(p, dict) and p.get("team_id") for p in state["players"].values()):
            raise ConditionUnsupported("team scoring is not modelled, so 'an opponent's score' has no single answer")
        who = condition.get("who", "opponent")
        if who != "opponent":
            raise ConditionUnsupported(f"score_within_of_victory does not model {who!r}")
        if controller is None:
            raise ConditionUnsupported("score_within_of_victory needs to know whose opponents to read")
        opponents = [p for p in sorted(state["players"]) if p != controller]
        if len(opponents) != 1:
            raise ConditionUnsupported(f"{len(opponents)} opponents; which one's score counts is not decided here")
        points = int(state["players"][opponents[0]].get("points", 0))
        return victory - points <= condition["count"]
    if kind == "another_card_finalized_this_turn":
        player = condition.get("player", controller)
        if player is None:
            raise ConditionUnsupported("another_card_finalized_this_turn needs to know whose plays to read")
        return legion_active(state, player, subject)
    if kind == "unit_died_this_turn":
        if controller is None:
            raise ConditionUnsupported("unit_died_this_turn needs to know whose friends and enemies to read")
        friendly = condition["controller_relation"] == "friendly"
        return any(units_died_this_turn(state, player_id) > 0 for player_id in sorted(state["players"])
                   if same_side(state, controller, player_id) == friendly)
    if kind == "object_kind":
        return subject is not None and characteristics(state, subject).get("kind") == condition["value"]
    if kind == "same_location_as":
        other = condition["as"]
        return (subject is not None and other in state["objects"]
                and find_location(state, subject) == find_location(state, other))
    if kind == "might_less_than":
        other = condition["than"]
        return (subject is not None and other in state["objects"]
                and effective_might(state, subject) < effective_might(state, other))
    if kind == "might_at_least":
        return subject is not None and effective_might(state, subject) >= condition["count"]
    if kind == "has_keyword":
        return subject is not None and has_keyword(state, subject, condition["keyword"])
    if kind == "is_empowered":
        return bool(state["objects"].get(subject, {}).get("empowered")) if subject else False
    if kind == "is_buffed":
        # Core 702.2.a: whether the object carries a Buff counter now
        return bool(state["objects"].get(subject, {}).get("buffed")) if subject else False
    if kind == "controls_a_battlefield":
        if controller is None:
            raise ConditionUnsupported("controls_a_battlefield needs to know whose side to read")
        holders = [bf.get("controller") for bf in state["battlefields"].values() if bf.get("controller") is not None]
        if condition["controller_relation"] == "friendly":
            return any(same_side(state, controller, holder) for holder in holders)
        return any(not same_side(state, controller, holder) for holder in holders)
    if kind == "cards_discarded_this_turn_at_least":
        player = condition.get("player", controller)
        if player is None:
            raise ConditionUnsupported("cards_discarded_this_turn_at_least needs to know whose discards to read")
        return len(cards_discarded_this_turn(state, player)) >= condition["count"]
    if kind == "xp_at_least":
        player = condition.get("player", controller)
        return int(state["players"].get(player, {}).get("xp", 0)) >= condition["count"]
    if kind == "battlefield_controlled":
        holder = state["battlefields"].get(condition["battlefield"], {}).get("controller")
        relation = condition.get("controller_relation", "friendly")
        return same_side(state, controller, holder) if relation == "friendly" else (holder is not None and not same_side(state, controller, holder))
    if kind == "at_a_battlefield":
        # 2026-09-27 package 6: "if I am at a battlefield" - read now (Core 359.3.f.2); an object
        # in a Base, off the board, or unknown is not at one
        where = find_location(state, subject) if subject in state["objects"] else None
        return where is not None and where[0] == "battlefield"
    if kind == "moved_this_turn_at_least":
        # package 9 (Kayn - Unleashed, GPT ruling 8): the object's real Moves this turn, counted per identity (Core 124:
        # a new object with the same id starts at zero); a Recall or a change of zone is not a Move
        identity = object_identity(state, subject) if subject in state["objects"] else None
        turn_id = state.get("turn_id", DEFAULT_TURN_ID)
        moved = int(((state.get("moves_this_turn") or {}).get(turn_id) or {}).get(identity or "", 0))
        return moved >= condition["count"]
    if kind == "controls_units":
        location = condition.get("location", "board")
        relation = condition.get("controller_relation", "friendly")
        here = None
        if location == "here" and subject in (state.get("battlefields") or {}):
            # package 9 (The Grand Plaza): a Battlefield's own condition - "here" is that Battlefield
            here = subject
        elif location == "here":
            # 2026-09-27 package 6: the Battlefield the condition's object stands at NOW (Core
            # 359.3.f.2); an object not at one has no "here", and no unit is there (359.3.e.12)
            at = find_location(state, subject) if subject in state["objects"] else None
            if at is None or at[0] != "battlefield":
                return 0 >= condition["count"]
            here = at[1]
        count = 0
        for object_id_, obj in state["objects"].items():
            if obj.get("kind") != "unit":
                continue
            where = find_location(state, object_id_)
            if zone_class(where) != "board":
                continue
            if location == "battlefield" and where[0] != "battlefield":
                continue
            if location == "base" and where[0] != "player":
                continue
            if here is not None and (where[0] != "battlefield" or where[1] != here):
                continue
            if not object_state_holds(obj, condition):
                continue
            friendly = same_side(state, controller, obj.get("controller"))
            if (relation == "friendly") != friendly:
                continue
            # package 6 (f7): a Unit with no tags recorded has none printed (object_tags is the one reader: a
            # token's come from its rule, Core 187.1); no effect the engine models grants or removes a tag
            if "tag" in condition and condition["tag"] not in (object_tags(state, object_id_) or []):
                continue
            count += 1
        return count >= condition["count"]
    if kind == "zone_count_at_least":
        player = condition.get("player", controller)
        zone = condition["zone"]
        if zone in PRIVATE_ZONES and perspective is not None and perspective != player:
            raise ConditionUnsupported(
                f"counting {player}'s {zone} needs private information that {perspective} cannot see (Core 128.4) "
                "(unsupported: condition_needs_hidden_information)")
        return len(state["players"].get(player, {}).get("zones", {}).get(zone, [])) >= condition["count"]
    raise ConditionUnsupported(f"condition leaf {kind!r} is recognised but not evaluated (unsupported: condition_kind_unknown)")


def cards_finalized_this_turn(state: dict[str, Any], player: str) -> list[str]:
    """Core 419.4.b: the cards `player` has Finalized this turn, in order. A
    countered card still counts - it was Finalized; an activated ability is not
    a card and never appears here."""
    ledger = (state["players"].get(player) or {}).get("cards_finalized_this_turn") or {}
    return list(ledger.get(state.get("turn_id", DEFAULT_TURN_ID), []))


def another_card_finalized_this_turn(state: dict[str, Any], player: str, card: str | None) -> bool:
    """Core 812.1.c: Legion is on once its controller has Finalized some other
    card this turn. 812.2:
    one such card satisfies every Legion that player controls."""
    return any(other != card for other in cards_finalized_this_turn(state, player))


def legion_active(state: dict[str, Any], player: str, card: str | None) -> bool:
    """Core 812.1.c on the card that has Legion (812.3: Legion is a
    characteristic of that card). A card named here must still have the
    keyword; the condition is asked with no card only by a caller that has
    none to name, and then reads the ledger alone."""
    if card is not None and card in state["objects"] and not has_keyword(state, card, "legion"):
        return False
    return another_card_finalized_this_turn(state, player, card)


def record_finalized_card(state: dict[str, Any], player: str, card: str) -> None:
    """Called once, when a card play is Finalized (358.4). Only this turn's
    entry is kept: the ledger is read for "this turn" and nothing else."""
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    ledger = (state["players"][player].get("cards_finalized_this_turn") or {}).get(turn_id, [])
    state["players"][player]["cards_finalized_this_turn"] = {turn_id: ledger + ([card] if card not in ledger else [])}


def cards_discarded_this_turn(state: dict[str, Any], player: str) -> list[str]:
    """Core 422.1 (2026-09-27): the cards `player` discarded this turn, one entry per
    discard - by an instruction (422.2.a, 422.4) or as a cost (422.3)."""
    ledger = (state["players"].get(player) or {}).get("cards_discarded_this_turn") or {}
    return list(ledger.get(state.get("turn_id", DEFAULT_TURN_ID), []))


def record_discarded_cards(state: dict[str, Any], player: str, cards: list[str]) -> None:
    """Called where a discard happens (the discard op, and a Discard cost paid). Only this
    turn's entry is kept: the ledger is read for "this turn" and nothing else."""
    if not cards:
        return
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    ledger = (state["players"][player].get("cards_discarded_this_turn") or {}).get(turn_id, [])
    state["players"][player]["cards_discarded_this_turn"] = {turn_id: ledger + list(cards)}
def units_died_this_turn(state: dict[str, Any], player: str) -> int:
    """Core 428.1: how many Units `player` controlled when they died, this turn."""
    ledger = (state["players"].get(player) or {}).get("units_died_this_turn") or {}
    return int(ledger.get(state.get("turn_id", DEFAULT_TURN_ID), 0))


def cards_played_count_this_turn(state: dict[str, Any], player: str) -> int:
    """2026-09-27 (package 6): how many cards `player` has played this turn - one per play completed by the
    card's resolution (Core 419.4.a; a countered card was not played, 419.4.a.1 - GPT 2026-09-27), so a card
    played twice in a turn counts twice. An activated ability is not a card."""
    ledger = (state["players"].get(player) or {}).get("cards_played_count_this_turn") or {}
    return int(ledger.get(state.get("turn_id", DEFAULT_TURN_ID), 0))


def record_card_played(state: dict[str, Any], player: str) -> int:
    """Called once, when a card's play completes as the card resolves (resolution_bridge; Core 419.4.a) -
    never for a countered card (419.4.a.1). Returns the play's ordinal this turn - what "When you play your
    second card in a turn" reads off the `played` event (watchers card_played_ordinal). Only this turn's
    entry is kept."""
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    ordinal = cards_played_count_this_turn(state, player) + 1
    state["players"][player]["cards_played_count_this_turn"] = {turn_id: ordinal}
    return ordinal


def object_tags(state: dict[str, Any], object_id: str) -> list[str] | None:
    """The object's tags (Core 133.8), as it carries them. A token gets its printed tags from the
    instruction that played it (play_token's `tags`, carried from the reviewed token catalogue - package 7;
    the TOKEN_RULE_TAGS table of package 6 is gone). None when never observed: a caller that needs them
    refuses rather than guessing."""
    obj = (state.get("objects") or {}).get(object_id)
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("tags"), list):
        return list(obj["tags"])
    return None


def record_unit_death(state: dict[str, Any], controller: str) -> None:
    """Called by the Kill action (the one place a permanent goes from the board to the trash,
    Core 428.1, 428.2) for a Unit, with its controller as it died. Only this turn's entry is
    kept, as record_finalized_card does."""
    if controller not in state["players"]:
        return
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    state["players"][controller]["units_died_this_turn"] = {turn_id: units_died_this_turn(state, controller) + 1}


def play_prohibition(state: dict[str, Any], player: str) -> dict[str, Any] | None:
    """The turn effect, if any, that forbids `player` to play cards this turn: a
    cards_play_prohibited granted this turn by a player `player` is an opponent of (Core 054.1;
    052: cards are Main Deck cards). None when nothing forbids it."""
    turn_id = state.get("turn_id", DEFAULT_TURN_ID)
    for effect in state.get("turn_effects", []) or []:
        if (effect.get("kind") == "cards_play_prohibited" and effect.get("turn_id") == turn_id
                and effect.get("value") == "opponents" and not same_side(state, effect.get("controller"), player)):
            return effect
    return None


# 2026-10-13 package 11 (Mageseeker Warden): restrictions a permanent imposes while it is at a Battlefield - the closed
# set, each read where its action happens (GPT PACKAGE11 ruling 17):
#   opponent_units_to_base_only  355.2: an opponent's Unit has no Battlefield among its valid locations as it is played
#                                (play_transaction); an effect that instructs such a play to a Battlefield is still
#                                played and finalized, and the play is skipped as it resolves (358.3.a)
#   no_ready_enemy_units_gear    358.3.a: a spell or ability's "ready" on an enemy Unit or Gear is skipped as it
#                                resolves; the Awaken Step is neither (turn_cycle readies directly)
# each kind is its own boolean field on the permanent, so two statements of one card merge without loss
BATTLEFIELD_RESTRICTIONS = {"opponent_units_to_base_only": "restricts_opponent_units_to_base",
                            "no_ready_enemy_units_gear": "prevents_ready_enemy_units_gear"}
# package 12 (Noxus Saboteur, the site owner's reading 2026-10-14): a restriction on the battlefield its source is at -
# an opponent's facedown card there cannot be turned face up by its owner, so it cannot be played from facedown there.
# A facedown card changing zones is still shown as it goes (the zone change's own procedure, not a play); a card
# merely mentioning the keyword elsewhere is untouched
HERE_RESTRICTIONS = {"opponent_hidden_not_revealed_here": "prevents_opponent_hidden_reveals_here"}


def hidden_reveal_prohibited(state: dict[str, Any], battlefield_id: str, player: str | None) -> str | None:
    """The source - a permanent at `battlefield_id` carrying the restriction, controlled by an opponent of `player` - that
    keeps `player`'s facedown cards there from being played, or None."""
    for source in sorted((state.get("battlefields") or {}).get(battlefield_id, {}).get("objects") or []):
        obj = state["objects"].get(source) or {}
        if obj.get(HERE_RESTRICTIONS["opponent_hidden_not_revealed_here"]) is True and player is not None \
                and not same_side(state, obj.get("controller"), player):
            return source
    return None


def battlefield_restriction(state: dict[str, Any], kind: str, player: str | None) -> str | None:
    """The source of an active `kind` restriction that binds `player` - a permanent at a Battlefield, carrying it,
    controlled by an opponent of `player` - or None."""
    for source, obj in sorted(state["objects"].items()):
        if obj.get(BATTLEFIELD_RESTRICTIONS[kind]) is not True:
            continue
        where = find_location(state, source)
        if where is not None and where[0] == "battlefield" and player is not None \
                and not same_side(state, obj.get("controller"), player):
            return source
    return None


def granted_play_permissions(state: dict[str, Any], card: str, actor: str) -> list[str]:
    """The play permissions permanents on the board grant to `card` played by `actor` (Core
    355.2.b): each friendly permanent - one on `actor`'s side - on the board whose
    granted_play_permissions names the card's kind. The card itself grants nothing to itself
    here: its own permission is its play_permissions."""
    kind = (state["objects"].get(card) or {}).get("kind")
    found = []
    for source, obj in sorted(state["objects"].items()):
        if source == card or not obj.get("granted_play_permissions") \
                or zone_class(find_location(state, source)) != "board":
            continue
        for grant in obj["granted_play_permissions"]:
            if grant["kind"] == kind and grant["controller_relation"] == "friendly" \
                    and same_side(state, obj.get("controller"), actor) and grant["permission"] not in found:
                found.append(grant["permission"])
    return found


def highest_might_you_control(state: dict[str, Any], player: str) -> int:
    """The highest Might among the Units `player` controls on the board (Core 355.9.a.1), as the
    layers compute it (476-480); 0 when they control none. A negative Might counts as 0: it can
    only lower nothing (356.6)."""
    mights = [effective_might(state, object_id) for object_id, obj in state["objects"].items()
              if obj.get("controller") == player and zone_class(find_location(state, object_id)) == "board"
              and characteristics(state, object_id).get("kind") == "unit"]
    return max([0] + mights)


def evaluate_cost_modification(state: dict[str, Any], modification: dict[str, Any], actor: str) -> dict[str, Any]:
    """ADR-0013 §6 / cost_modification.v1: P4 evaluates the condition and the
    per-each count; P2 consumes the result and never evaluates a source."""
    result = {"modification_id": modification.get("id"), "applies": True, "amount": modification.get("amount", 0),
              "provenance": {"evaluated_by": "p4_condition_layer"}}
    condition = modification.get("condition")
    if condition is not None:
        result["applies"] = evaluate_condition(state, condition, controller=actor)
        result["condition_result"] = result["applies"]
    per_each = modification.get("per_each")
    if per_each == {"kind": HIGHEST_MIGHT_YOU_CONTROL}:
        # Sky Splitter: 1 per point of the highest Might among the actor's Units, read now
        # (356.4); 356.6 floors the total later, in determine_total_cost
        count = highest_might_you_control(state, actor)
        result["per_each_count"] = count
        result["amount"] = modification.get("amount", 0) * count
        result["applies"] = result["applies"] and count > 0
        return result
    if per_each is not None:
        problems = validate_condition({**per_each, "count": 0} if "count" not in per_each else per_each)
        if problems:
            raise ValueError("; ".join(problems))
        if per_each.get("kind") == "zone_count_at_least" and per_each.get("zone") in PUBLIC_COUNT_ZONES:
            # a public zone is counted outright; 356.6 keeps the total at 0 or above
            player = per_each.get("player", actor)
            count = len((state["players"].get(player) or {}).get("zones", {}).get(per_each["zone"], []))
            result["per_each_count"] = count
            result["amount"] = modification.get("amount", 0) * count
            result["applies"] = count > 0
            return result
        if per_each.get("kind") != "controls_units":
            raise ConditionUnsupported(f"per-each over {per_each.get('kind')!r} is not counted by this slice (unsupported: cost_modification_per_each_scope)")
        count = 0
        while evaluate_condition(state, {**per_each, "count": count + 1}, controller=actor):
            count += 1
            if count > 64:
                raise ConditionUnsupported("a per-each count exceeded the bounded search (unsupported: cost_modification_per_each_bound)")
        result["per_each_count"] = count
        result["amount"] = modification.get("amount", 0) * count
        result["applies"] = count > 0
    return result


def characteristics(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    """Core 476-480: apply the three layers in order, each effect once across
    every pass, repeating until a pass changes nothing. Within a layer the
    engine derives dependencies (478) and falls back to timestamp order (480);
    an order it cannot justify is refused rather than guessed."""
    # package 15: on a state held frozen (frozen_inputs), each object's computed once - a pure function of the state and
    # the object; a copy handed out (an exception it raises is not kept: it is raised again each time)
    if (entry := _frozen(state)) is not None:
        cache = entry.setdefault("characteristics", {})
        if object_id not in cache:
            cache[object_id] = _characteristics(state, object_id)
        return copy.deepcopy(cache[object_id])
    return _characteristics(state, object_id)


def _characteristics(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    obj = state["objects"][object_id]
    effects = [e for e in canonical_effects(state) + printed_aura_effects(state)
               if _effect_applies_to(state, e, object_id) and _effect_active(state, e)[0]]
    # 2026-10-08 package 10 (Spirit's Refuge: "Friendly buffed units have [Deflect] if they didn't already."): a keyword
    # grant that applies only to an object that does not otherwise have the keyword - held back until every other keyword
    # source has applied (whatever its timestamp), then given only if the keyword is still absent; never summed onto one
    only_if_absent = [e for e in effects if e.get("kind") == "keyword_grant" and (e.get("value") or {}).get("only_if_absent")]
    effects = [e for e in effects if e not in only_if_absent]
    # Core 703: every Buff on a Unit adds +1 to its Might. A Buff
    # is a counter, not a continuous effect, so it is not in the effect list at
    # all - it has to be added here or it contributes nothing. 476.3's own
    # example is exactly this: a buffed Fiora, Victorious is 4 printed + 1 = 5,
    # and 5 is what makes her Mighty, which turns on Deflect, Ganking and
    # Shield. Miss the +1 and three keywords silently stay off.
    #
    # 702.3 allows a Unit only one Buff at a time, so the state carries a
    # boolean and the contribution is +1. 426.1.b.2 lets a card grant
    # permission to be Buffed several times; no card in the pinned corpus does,
    # and when one appears this needs a count the way Empower needed
    # empowered_count, not a second boolean.
    buffs = buff_count(obj)
    # 2026-10-08 package 10 (Stand United): this turn's "buffs give an additional +N" of the unit's side, per buff
    buff_bonus = sum(e["value"] for e in state.get("turn_effects", []) or []
                     if e.get("kind") == "buff_bonus_might" and e.get("turn_id") == state.get("turn_id", DEFAULT_TURN_ID)
                     and same_side(state, e.get("controller"), obj.get("controller"))) if buffs else 0
    buffs = buffs * (1 + buff_bonus)
    result = {"might": obj["base_might"] + buffs,
              "keywords": {k: (obj.get(f"{k}_value") or 1) if k in VALUED_KEYWORDS else None for k in (obj.get("keywords") or [])},
              "kind": obj.get("kind"), "triggers": {}, "applied": [], "passes": 0,
              "buff_might": buffs}
    if buffs:
        result["applied"].append({"effect_id": f"buff:{object_id}", "layer": "arithmetic",
                                  "amount": buffs, "rule_locators": ["Core 703", "Core 476.3"]})
    # 2026-09-27, Core 476.2-476.3: an effect conditioned on the object's OWN Might ("While I'm
    # [Mighty], I have ...", 708) is not asked through effective_might - that is this function,
    # and asking it recursed forever. It is read from the layer result in progress, at the start
    # of each Ability layer: applied once when the Might there reaches the count, removed
    # (disqualified) once if it later falls below, never re-applied. Every other effect takes
    # the path below unchanged.
    own_might = sorted((e for e in effects if _reads_own_might(e, object_id)), key=lambda e: (e["timestamp"], e["effect_id"]))
    own_status = {e["effect_id"]: "unapplied" for e in own_might}
    buff_in_might = bool(buffs)      # the Buff is an Arithmetic-layer application (476.3)
    arithmetic_ran = False
    pending = {e["effect_id"]: e for e in effects if e["effect_id"] not in own_status}
    applied: set[str] = set()
    for _ in range(len(effects) + 2 * len(own_might) + 1):
        result["passes"] += 1
        changed = False
        for layer in CONTINUOUS_LAYERS:
            if layer == "ability" and own_might:
                layered = _layered_own_might(state, object_id, result, own_might, own_status,
                                             pending_buff=buffs if buff_in_might and not arithmetic_ran else 0,
                                             arithmetic_ran=arithmetic_ran)
            ready = [e for e in pending.values() if e["effect_id"] not in applied and e["layer"] == layer and _condition_holds(state, e, object_id)]
            for effect in _layer_order(state, ready, object_id, result):
                if effect["kind"] == "might_set":
                    result["might"] = effect["value"]["amount"]
                    buff_in_might = False
                elif effect["kind"] == "might_arithmetic":
                    amount = _applied_amount(_read_per(state, effect), result["might"])
                    result["might"] += amount
                    # Only a stored snapshot is reported as one. The field used to
                    # carry whatever the bound produced on this pass, which read
                    # as a record of 477.3.b while being the opposite of it.
                    limited = {"minimum", "maximum"} & set(effect["value"])
                    result["applied"].append({"effect_id": effect["effect_id"], "layer": layer, "amount": amount,
                                              **({"snapshot": effect["value"]["snapshot_amount"]}
                                                 if "snapshot_amount" in effect["value"] else {}),
                                              **({"recomputed_limit": True}
                                                 if limited and "snapshot_amount" not in effect["value"] else {})})
                    applied.add(effect["effect_id"])
                    changed = True
                    continue
                elif effect["kind"] == "ability_append":
                    # Core 477.2: the Effect Text of an attached card, and a
                    # copy's rules text, are appended in the Ability layer.
                    for field, descriptors in (effect["value"].get("triggers") or {}).items():
                        result["triggers"].setdefault(field, []).extend(copy.deepcopy(descriptors))
                elif effect["kind"] == "copy_traits":
                    # Core 477.1: the copyable traits the engine models.
                    source = state["objects"].get(effect["value"]["source_object"], {})
                    if "type" in effect["value"]["traits"]:
                        result["kind"] = source.get("kind")
                    if "rules_text" in effect["value"]["traits"]:
                        for field in APPENDABLE_TRIGGER_FIELDS:
                            descriptors = source.get(field) or []
                            if descriptors:
                                result["triggers"].setdefault(field, []).extend(copy.deepcopy(descriptors))
                elif effect["kind"] == "keyword_grant":
                    keyword = effect["value"]["keyword"]
                    if keyword in VALUED_KEYWORDS:
                        result["keywords"][keyword] = (result["keywords"].get(keyword) or 0) + (effect["value"].get("value") or 1)
                    else:
                        result["keywords"].setdefault(keyword, None)
                elif effect["kind"] == "keyword_remove":
                    result["keywords"].pop(effect["value"]["keyword"], None)
                elif effect["kind"] == "bonus_damage":
                    applied.add(effect["effect_id"])
                    continue
                result["applied"].append({"effect_id": effect["effect_id"], "layer": layer})
                applied.add(effect["effect_id"])
                changed = True
            if layer == "ability" and own_might:
                for effect in own_might:
                    before = own_status[effect["effect_id"]]
                    own_status[effect["effect_id"]] = _own_might_step(before, layered >= effect["condition"]["count"])
                    changed = changed or own_status[effect["effect_id"]] != before
            if layer == "arithmetic":
                if own_might and not arithmetic_ran:
                    changed = True      # 476.2: the Ability layer is evaluated again after it
                arithmetic_ran = True
        if not changed:
            break
    for effect in sorted(only_if_absent, key=lambda e: (e["timestamp"], e["effect_id"])):
        keyword = effect["value"]["keyword"]
        if _condition_holds(state, effect, object_id) and keyword not in result["keywords"]:
            result["keywords"][keyword] = 1 if keyword in VALUED_KEYWORDS else None
            result["applied"].append({"effect_id": effect["effect_id"], "layer": "ability", "only_if_absent": True})
    if own_might:
        result["keywords"] = _with_own_might_grants(result["keywords"], own_might, own_status)
        for effect in own_might:
            if own_status[effect["effect_id"]] == "applied":
                result["applied"].append({"effect_id": effect["effect_id"], "layer": "ability"})
        result["disqualified"] = [e["effect_id"] for e in own_might if own_status[e["effect_id"]] == "removed"]
    # Core 143.2.b: the arithmetic value stays as it is; the rules-facing read
    # clamps at zero, which `effective_might` does.
    return result


def _own_might_step(status: str, holds: bool) -> str:
    """Core 476.1 / 476.3: applied as soon as its condition holds, once; removed (disqualified)
    when it stops holding, once; never applied again after that."""
    if status == "unapplied" and holds:
        return "applied"
    if status == "applied" and not holds:
        return "removed"
    return status


def _reads_own_might(effect: dict[str, Any], object_id: str) -> bool:
    """A keyword grant whose condition is the affected object's own Might (Core 708: Mighty)."""
    condition = effect.get("condition") or {}
    return (effect["kind"] == "keyword_grant" and condition.get("kind") == "might_at_least"
            and condition.get("object", object_id) == object_id)


def _with_own_might_grants(keywords: dict[str, Any], own_might: list[dict[str, Any]], status: dict[str, str]) -> dict[str, Any]:
    merged = dict(keywords)
    for effect in own_might:
        if status[effect["effect_id"]] != "applied":
            continue
        keyword = effect["value"]["keyword"]
        if keyword in VALUED_KEYWORDS:
            merged[keyword] = (merged.get(keyword) or 0) + (effect["value"].get("value") or 1)
        else:
            merged.setdefault(keyword, None)
    return merged


def _layered_own_might(state: dict[str, Any], object_id: str, result: dict[str, Any], own_might: list[dict[str, Any]],
                       status: dict[str, str], *, pending_buff: int, arithmetic_ran: bool) -> int:
    """The object's Might as the layers have it at the start of an Ability layer (476.2): before
    any Arithmetic layer has run, without the Buff; after, with everything the Arithmetic layer
    applied - the effects, the Buff, and the Might a Defender's Shield / an Attacker's Assault
    and attached cards contribute there (476.3, 477.3.d), from the keywords the object has at
    that point."""
    might = result["might"] - pending_buff
    if not arithmetic_ran or zone_class(find_location(state, object_id)) != "board":
        return might
    keywords = _with_own_might_grants(result["keywords"], own_might, status)
    designation = state["objects"][object_id].get("combat_designation") or {}
    if designation.get("role") == "defender":
        might += keywords.get("shield") or 0
    if designation.get("role") == "attacker":
        might += keywords.get("assault") or 0
    might += sum(state["objects"][attached].get("might_bonus", 0) for attached in attachments(state, object_id))
    return might


def _layer_order(state: dict[str, Any], effects: list[dict[str, Any]], object_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Core 478-480: increases before decreases (477.3.a), then dependency,
    then timestamp. A dependency the engine cannot order is refused."""
    ordered = sorted(effects, key=lambda e: (0 if e.get("sublayer", "increase") == "increase" else 1, e["timestamp"], e["effect_id"]))
    limited = [e for e in ordered if e["kind"] == "might_arithmetic" and (e["value"].get("mode") == "increase_to" or {"minimum", "maximum"} & set(e["value"]))]
    if len(limited) < 2 and not (limited and len(ordered) > 1):
        return ordered
    # 478: A depends on B when applying B changes what A applies.
    def altered_by(a: dict[str, Any], b: dict[str, Any]) -> bool:
        base = result["might"]
        a, b = _read_per(state, a), _read_per(state, b)
        return _applied_amount(a, base) != _applied_amount(a, base + _applied_amount(b, base))

    depends: dict[str, set[str]] = {e["effect_id"]: set() for e in ordered}
    for a in ordered:
        for b in ordered:
            if a is b or a.get("sublayer") != b.get("sublayer"):
                continue
            if altered_by(a, b) and not altered_by(b, a):
                depends[a["effect_id"]].add(b["effect_id"])
    resolved: list[dict[str, Any]] = []
    remaining = list(ordered)
    guard = len(remaining) + 1
    while remaining and guard:
        guard -= 1
        free = [e for e in remaining if not (depends[e["effect_id"]] - {r["effect_id"] for r in resolved})]
        if not free:
            raise NotImplementedError(
                "two continuous effects in the same layer depend on each other in a way this engine cannot order "
                f"({[e['effect_id'] for e in remaining]}); Core 478-479 (unsupported: layer_dependency_unresolved)")
        resolved.append(free[0])
        remaining.remove(free[0])
    return resolved


def current_might(obj: dict[str, Any]) -> int:
    """The object's printed Might. Since ADR-0013 §1 every modification is a
    continuous effect, so a rules-facing value comes from `effective_might`,
    which runs the layers."""
    return obj["base_might"]


DEATHKNELL_EXTRA_FIELD = "deathknell_extra_times"


def _extra_times(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 0


def group_pending_triggers(events: list[dict[str, Any]], after: dict[str, Any]) -> list[dict[str, Any]]:
    """2026-10-12 package 11 (Karthus - Eternal: "Your [Deathknell] effects trigger an additional time."; GPT PACKAGE11
    ruling 1). `events` are the events of ONE game action - deaths from one instruction or one Cleanup are simultaneous
    (Core 370.1.a.2) - and `after` the state once all of them were applied. Each Deathknell trigger among them triggers
    once more for every such static its controller has that was on the board as these deaths were noted, before any of
    them moved (Core 808.1.d.2; Cleanup 323.4 before 323.5): a source still on the board afterwards, or one that died in
    this same group (its kill recorded it, deathknell_extra_source). A source that left the board by a Replacement Effect
    instead of dying does not count (the replacement is applied first); one that died in an earlier, separate action is
    not here at all. The result does not depend on the order the deaths were applied in: any copies an inner,
    one-object application added are dropped and computed again for the whole group. Only real Deathknell triggers are
    multiplied - not another death trigger of the same object. Returns every pending trigger of the group, the copies
    included, and leaves each event's own list with its copies."""
    sources: list[tuple[str, str | None, int]] = []
    died = {}
    for event in events:
        record = event.get("deathknell_extra_source") if event.get("op") == "kill" else None
        if isinstance(record, dict) and _extra_times(record.get("extra_times")):
            died[event.get("object_id")] = record
    for oid in sorted(set(after.get("objects") or {}) | set(died)):
        obj = (after.get("objects") or {}).get(oid)
        if obj is not None and zone_class(find_location(after, oid)) == "board" and _extra_times(obj.get(DEATHKNELL_EXTRA_FIELD)):
            sources.append((oid, obj.get("controller"), obj[DEATHKNELL_EXTRA_FIELD]))
        elif oid in died:
            sources.append((oid, died[oid].get("controller"), died[oid]["extra_times"]))
    every = []
    for event in events:
        if "pending_triggers" not in event:
            continue
        own = [t for t in event["pending_triggers"] if not t.get("multiplied_by")]
        copies = []
        for trigger in own:
            if not trigger.get("deathknell"):
                continue
            for oid, controller, extra in sources:
                if controller != trigger.get("controller"):
                    continue
                for k in range(extra):
                    copies.append({**copy.deepcopy(trigger), "trigger_id": f"{trigger['trigger_id']}#extra:{oid}:{k + 1}",
                                   "multiplied_by": oid, "rule_locators": ["Core 383.3", "Core 808.1.d.2", "Core 370.1.a.2"]})
        event["pending_triggers"] = own + copies
        every.extend(event["pending_triggers"])
    return every


def deathknell_instances(state: dict[str, Any], object_id: str) -> list[dict[str, Any]]:
    """Core 808: which of a dying permanent's death triggers are Deathknell.

    808.2 makes "[Deathknell][>] [Effect]" short for "When I die, [Effect]", so
    the ability *is* a death trigger; 808.3 makes each instance trigger
    separately with its controller choosing the order, which is why they are
    distinguished rather than merged. The keyword is read from the computed
    characteristics, so one granted or copied counts (808's last paragraph).
    """
    if not has_keyword(state, object_id, "deathknell"):
        return []
    triggers = object_triggers(state, object_id, "death_triggers")
    # 2026-10-12 (package 11, GPT PACKAGE11 ruling 1): an object with a Deathknell AND another ability that triggers on
    # its own death (Core 323.4 names both) says which is which on each descriptor (`keyword`); only the Deathknell one
    # is Deathknell. An object whose descriptors name none is read as before - every death trigger is its Deathknell
    if any("keyword" in trigger for trigger in triggers):
        return [dict(trigger) for trigger in triggers if trigger.get("keyword") == "deathknell"]
    return [dict(trigger) for trigger in triggers]


VISION_PROGRAM_PREFIX = "keyword:vision"


def vision_program(state: dict[str, Any], object_id: str, controller: str) -> dict[str, Any]:
    """Core 817.1.b: Vision is short for "When this is played, predict." - Predict
    with no number is Predict 1 (436.1). The program is the engine's, not a card's:
    the keyword is the whole ability."""
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": f"{VISION_PROGRAM_PREFIX}:{object_id}", "controller": controller, "source_object": object_id,
            "effects": [{"op": "predict", "effect_id": "vision", "player": controller, "count": 1}]}


def vision_triggers(state: dict[str, Any], object_id: str, controller: str) -> list[dict[str, Any]]:
    """Core 817.1.c: Vision triggers when its permanent enters the Board; the engine
    models the entry of a PLAYED permanent only (see below). Read from the computed
    characteristics, so a granted Vision counts too. The
    descriptor binds the program's content hash, so dispatch refuses any other
    program under the same id. 817.2 (several instances trigger separately) is
    not modelled: the keyword list carries Vision once."""
    if not has_keyword(state, object_id, "vision"):
        return []
    # Scope (GPT 2026-09-22): only a permanent entering the Board by being played is
    # modelled. Whether one put onto the Board without being played triggers is NOT
    # decided here - that case is an exception awaiting a more direct source.
    program = vision_program(state, object_id, controller)
    first = {"trigger_id": f"{object_id}:vision", "controller": controller, "source_object": object_id, "controller_order": 0,
             "effect_program_id": program["program_id"], "effect_program_hash": hash_value(program["effects"]),
             "optional_at_finalize": False}
    # 2026-09-27, Core 817.2: multiple instances trigger separately - a printed Vision and one
    # granted by "Other friendly units have [Vision].", or two such grants, are two triggers
    # (each its own recycle choice, 817.2.a). The first keeps the id it always had.
    extra = [{**first, "trigger_id": f"{object_id}:vision:{k}", "controller_order": k - 1}
             for k in range(2, keyword_instances(state, object_id, "vision") + 1)]
    return [first] + extra


def _applied_grants(state: dict[str, Any], object_id: str, keyword: str) -> tuple[bool, list[dict[str, Any]]]:
    """(has the keyword after the layers, the keyword grants the Ability layer applied to it)."""
    computed = characteristics(state, object_id)
    if keyword not in computed["keywords"]:
        return False, []
    by_id = {e["effect_id"]: e for e in canonical_effects(state) + printed_aura_effects(state)}
    grants = [by_id[r["effect_id"]] for r in computed["applied"]
              if (by_id.get(r["effect_id"]) or {}).get("kind") == "keyword_grant"
              and by_id[r["effect_id"]]["value"]["keyword"] == keyword]
    return True, grants


def keyword_instances(state: dict[str, Any], object_id: str, keyword: str) -> int:
    """Core 817.2 (2026-09-27): how many instances of a keyword the object has - the printed
    one, plus one per grant the Ability layer applied; 0 when it does not have it."""
    has, grants = _applied_grants(state, object_id, keyword)
    if not has:
        return 0
    printed = 1 if keyword in (state["objects"][object_id].get("keywords") or []) else 0
    return max(1, printed + len(grants))


def deflect_total(state: dict[str, Any], object_id: str) -> int:
    """Core 809.2 (2026-09-27): the Deflect Value of every Deflect the object has or was granted,
    summed; an omitted X is 1 (809.1.b.3). A printed-only Deflect is its printed value, as before."""
    has, grants = _applied_grants(state, object_id, "deflect")
    if not has:
        return 0
    obj = state["objects"][object_id]
    printed = obj.get("deflect_value", 1) if "deflect" in (obj.get("keywords") or []) else 0
    return printed + sum(g["value"].get("value") or 1 for g in grants)


TEMPORARY_PROGRAM_PREFIX = "keyword:temporary"


def temporary_program(state: dict[str, Any], object_id: str, controller: str) -> dict[str, Any]:
    """Core 816.1.b: Temporary kills the permanent at the start of its controller's
    Beginning Phase, ahead of that phase's scoring. The program is the
    engine's: the keyword is the whole ability."""
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": f"{TEMPORARY_PROGRAM_PREFIX}:{object_id}", "controller": controller, "source_object": object_id,
            "effects": [{"op": "kill", "effect_id": "temporary", "object_id": object_id,
                         "if_identity": object_identity(state, object_id) or f"{object_id}@0"}]}


def temporary_triggers(state: dict[str, Any], object_id: str, controller: str) -> list[dict[str, Any]]:
    """Core 816.1.c: the trigger condition is its controller's Beginning Phase
    starting; 816.2.a: however many instances, it triggers once. Read from the
    computed characteristics, so a granted Temporary counts. The descriptor binds
    the program's content hash."""
    if not has_keyword(state, object_id, "temporary"):
        return []
    program = temporary_program(state, object_id, controller)
    return [{"trigger_id": f"{object_id}:temporary", "controller": controller, "source_object": object_id, "controller_order": 0,
             "effect_program_id": program["program_id"], "effect_program_hash": hash_value(program["effects"]),
             "optional_at_finalize": False}]


def keyword_values(state: dict[str, Any], object_id: str) -> dict[str, Any]:
    return characteristics(state, object_id)["keywords"]


def has_keyword(state: dict[str, Any], object_id: str, keyword: str) -> bool:
    """Printed or granted, after the ability layer has run (Core 477.2)."""
    return keyword in characteristics(state, object_id)["keywords"]


def assault_total(state: dict[str, Any], object_id: str) -> int:
    """Core 807.2: every Assault value the Unit has or was granted, summed; an omitted
    X is 1 (807.1.b.3). It adds to Might only while the Unit is an Attacker (807.1.c)."""
    return characteristics(state, object_id)["keywords"].get("assault") or 0


def shield_total(state: dict[str, Any], object_id: str) -> int:
    """Core 814.2: every Shield value the Unit has or was granted, summed; an
    omitted X is 1 (814.1.b.3)."""
    return characteristics(state, object_id)["keywords"].get("shield") or 0


def runes_on_board(state: dict[str, Any], controller: str) -> int:
    """ADR-0007 §7: every Rune the player controls on the Board — Base or any
    Board Location, ready or exhausted; nothing in Non-Board Zones; a
    teammate's runes are not "yours"."""
    count = 0
    for object_id, obj in state["objects"].items():
        if obj.get("kind") != "rune" or obj.get("controller") != controller:
            continue
        if zone_class(find_location(state, object_id)) == "board":
            count += 1
    return count


def keyword_modifier_active(state: dict[str, Any], object_id: str, modifier: dict[str, Any]) -> bool:
    """Legacy read-side helper: whether a translated grant still applies. The
    runtime asks `characteristics`; this stays for callers holding a legacy
    modifier dict."""
    effect = next((e for e in canonical_effects(state)
                   if e["kind"] == "keyword_grant" and e["affects"].get("object") == object_id
                   and e["value"]["keyword"] == modifier.get("keyword")), None)
    return effect is not None and _effect_active(state, effect)[0]


def is_alone(state: dict[str, Any], object_id: str) -> bool:
    """Core 740.2.a: no other friendly Unit (team-aware, 740.1.a) at the same location."""
    obj = state["objects"][object_id]
    location = find_location(state, object_id)
    if location is None:
        return False
    for other_id, other in state["objects"].items():
        if other_id == object_id or other.get("kind") != "unit":
            continue
        if find_location(state, other_id) == location and same_side(state, obj["controller"], other["controller"]):
            return False
    return True


def combat_might_contributions(state: dict[str, Any], object_id: str) -> list[dict[str, Any]]:
    """ADR-0008 §5, now read off the layer engine: Shield while the Unit is a
    Defender (814.1.c), and every continuous effect whose condition is a
    Combat one (740.2.a, 365.1)."""
    obj = state["objects"][object_id]
    designation = obj.get("combat_designation")
    parts: list[dict[str, Any]] = []
    if designation is not None and designation.get("role") == "defender":
        shield = shield_total(state, object_id)
        if shield:
            parts.append({"kind": "shield", "amount": shield, "rule_locators": ["Core 814.1.c", "Core 814.2"]})
    if designation is not None and designation.get("role") == "attacker":
        assault = assault_total(state, object_id)
        if assault:
            parts.append({"kind": "assault", "amount": assault, "rule_locators": ["Core 807.1.c", "Core 807.2"]})
    computed = characteristics(state, object_id)
    by_id = {e["effect_id"]: e for e in canonical_effects(state)}
    for record in computed["applied"]:
        effect = by_id.get(record["effect_id"])
        condition = (effect or {}).get("condition") or {}
        if condition.get("kind") == "attacking_or_defending_alone":
            parts.append({"kind": "attacking_or_defending_alone", "modifier_id": effect["effect_id"], "amount": record.get("amount", 0),
                          "rule_locators": ["Core 740.2.a", "Core 364.3"]})
        elif condition.get("kind") == "friendly_unit_defends_alone":
            parts.append({"kind": "friendly_unit_defends_alone", "modifier_id": effect["effect_id"], "source_object": effect["source"]["object"],
                          "amount": record.get("amount", 0), "rule_locators": ["Core 740.2.a", "Core 365.1"]})
    return parts


def effective_might(state: dict[str, Any], object_id: str) -> int:
    """Core 476-480 through `characteristics`, plus the two intrinsic
    contributions that are rules, not stored effects: a Defender's Shield
    (814.1.c) and the Might Bonus of attached cards (159.1, applied in the
    Arithmetic layer). Clamped at zero when the rules read it (143.2.b)."""
    might = characteristics(state, object_id)["might"]
    if zone_class(find_location(state, object_id)) != "board":
        return max(0, might)
    designation = state["objects"][object_id].get("combat_designation")
    if designation is not None and designation.get("role") == "defender":
        might += shield_total(state, object_id)
    if designation is not None and designation.get("role") == "attacker":
        might += assault_total(state, object_id)     # Core 807.1.c
    might += sum(state["objects"][attached].get("might_bonus", 0) for attached in attachments(state, object_id))
    return max(0, might)


def _replacement_ids_applied(trace: list[dict[str, Any]]) -> set[str]:
    """Every Replacement Effect an application actually applied, including the
    ones applied inside a replacement's own sequence (Core 370.2, 374)."""
    found: set[str] = set()
    for entry in trace or []:
        if isinstance(entry.get("replacement_id"), str) and entry.get("outcome") != "replacement_declined":
            found.add(entry["replacement_id"])
        for nested in ("replacement_trace", "expansion_trace"):
            found |= _replacement_ids_applied(entry.get(nested) or [])
    return found


def apply_simultaneous_kill_batch(
    state: dict[str, Any],
    object_ids: list[str],
    *,
    replacement_event_order: dict[str, list[str]] | None = None,
    replacement_choices: dict[str, dict[str, bool]] | None = None,
    kill_mode: str = "simultaneous",
    attributed_sources: list[str] | None = None,
    attributed_sources_by_object: dict[str, list[str]] | None = None,
    event_replacement_order: dict[str, list[str]] | None = None,
    replacement_sequence_order: dict[str, list[str]] | None = None,
    turn_order: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a bounded Core 373 batch with at most one prevent descriptor.
    `attributed_sources_by_object` names the sources of each kill separately
    (Combat Damage: the opposing side's Units, 428.5.c.2); the flat list stays
    the default for every object it does not name."""
    base = {
        "schema_version": "riftbound-simultaneous-kill-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": hash_value(state),
    }
    errors = validate_state(state)
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "trace": []}
    if not isinstance(object_ids, list) or not object_ids or len(object_ids) != len(set(object_ids)):
        return {**base, "valid": False, "committed": False, "errors": ["object_ids must be a non-empty unique array"], "trace": []}
    for object_id in object_ids:
        obj = state["objects"].get(object_id)
        if obj is None or obj.get("kind") not in {"unit", "gear"} or zone_class(find_location(state, object_id)) != "board":
            return {**base, "valid": False, "committed": False, "errors": [f"{object_id!r} is not a supported board permanent"], "trace": []}
    if isinstance(replacement_event_order, dict):
        # 2026-10-16 package 14: a resolution-stage replacement_order names its order by what it orders (engine_decisions
        # carries one map) - a Replacement Effect's events (keyed by the replacement), a controller's own sequences
        # (keyed by that player, Core 372) or one object's Replacement Effects (keyed by the object) - split here, so
        # every order the batch can ask for has an answer
        players, objects = set(state["players"]), set(state["objects"])
        if replacement_sequence_order is None and any(k in players for k in replacement_event_order):
            replacement_sequence_order = {k: v for k, v in replacement_event_order.items() if k in players}
        if event_replacement_order is None and any(k in objects for k in replacement_event_order):
            event_replacement_order = {k: v for k, v in replacement_event_order.items() if k in objects}
        replacement_event_order = {k: v for k, v in replacement_event_order.items() if k not in players and k not in objects}
    if replacement_event_order is not None and not isinstance(replacement_event_order, dict):
        return {**base, "valid": False, "committed": False, "errors": ["replacement_event_order must be an object"], "trace": []}
    if replacement_choices is not None and not isinstance(replacement_choices, dict):
        return {**base, "valid": False, "committed": False, "errors": ["replacement_choices must be an object"], "trace": []}

    events = {
        object_id: {
            "effect_id": f"simultaneous-kill:{object_id}", "op": "kill", "object_id": object_id,
            "kill_mode": kill_mode, "attributed_sources": list((attributed_sources_by_object or {}).get(object_id, attributed_sources or [])),
        }
        for object_id in object_ids
    }
    qualifying: dict[str, list[str]] = {}
    descriptors: dict[str, dict[str, Any]] = {}
    for object_id in object_ids:
        for descriptor in _applicable_replacements(state, events[object_id]):
            replacement_id = descriptor["replacement_id"]
            descriptors[replacement_id] = descriptor
            qualifying.setdefault(replacement_id, []).append(object_id)
    supplied_order_ids = set((replacement_event_order or {}).keys())
    supplied_choice_ids = set((replacement_choices or {}).keys())
    stale_decision_ids = (supplied_order_ids | supplied_choice_ids) - set(descriptors)
    if stale_decision_ids:
        return {
            **base, "valid": False, "committed": False,
            "errors": [f"cleanup decisions reference non-applicable replacements: {sorted(stale_decision_ids)}"],
            "trace": [],
        }
    # ADR-0014 §3: the Core ordering law, in the two layers the rules write it
    # in. *Who orders* the Replacement Effects that apply to one event is the
    # player controlling the affected object; *when* the sequences of
    # different controllers execute is Turn Order. Each Replacement Effect is
    # applied in exactly one sequence (374), and inside a sequence its own
    # replacing events may be replaced by others (370.2) — that recursion, and
    # the memory that stops a Replacement Effect applying to the event that
    # replaced it, live in apply_program.
    unsupported_modes = sorted({rid for rid, item in descriptors.items() if item["mode"] not in {"prevent_event", "replace_with"}})
    if unsupported_modes:
        return {
            **base, "valid": True, "committed": False, "unsupported": True,
            "reason_code": "batch_replacement_mode",
            "reason": f"a simultaneous batch applies prevent_event and replace_with; {unsupported_modes} are outside that slice",
            "replacement_ids": unsupported_modes, "trace": [],
        }
    controllers = sorted({item["controller"] for item in descriptors.values()})
    if len(controllers) > 1 and not turn_order:
        return {
            **base, "valid": True, "committed": False, "unsupported": True,
            "reason_code": "turn_order_unknown",
            "reason": "Replacement Effects of different controllers execute in Turn Order; this batch was given none",
            "replacement_ids": sorted(descriptors), "trace": [],
        }
    if turn_order is not None and (not isinstance(turn_order, list) or set(controllers) - set(turn_order)):
        return {**base, "valid": False, "committed": False,
                "errors": [f"turn_order {turn_order!r} does not cover the replacement controllers {controllers}"], "trace": []}
    if event_replacement_order is not None and not isinstance(event_replacement_order, dict):
        return {**base, "valid": False, "committed": False, "errors": ["event_replacement_order must be an object"], "trace": []}

    current = copy.deepcopy(state)
    trace: list[dict[str, Any]] = []
    prevented: set[str] = set()
    spent: set[str] = set()  # Core 374: one sequence per Replacement Effect

    # A sequence is one Replacement Effect's uninterrupted series of
    # applications to the simultaneous events it qualifies for (Core 374), so
    # the batch iterates *replacements*, not events: within its own sequence a
    # Replacement Effect may apply to any number of the qualifying events, and
    # once that sequence ends it may not start another.
    turn_position = {player: index for index, player in enumerate(turn_order or controllers)}
    # Core 373: a controller picks the order of its own Replacement Effects:
    # with more than one of its own in the batch,
    # that controller must say which sequence runs first.
    by_controller: dict[str, list[str]] = {}
    for replacement_id, item in descriptors.items():
        by_controller.setdefault(item["controller"], []).append(replacement_id)
    sequence_rank: dict[str, int] = {}
    for controller, ids in by_controller.items():
        if len(ids) == 1:
            sequence_rank[ids[0]] = 0
            continue
        # one order per controller and set of its Replacement Effects: a follow-up iteration's batch reads the same
        # supplied order (it is keyed by the player, _iteration_decisions) and asks for no other
        ledger_note("replacement", f"replacement:sequence_order:{'+'.join(sorted(ids))}{_iteration_suffix()}")
        supplied = (replacement_sequence_order or {}).get(controller)
        if not isinstance(supplied, list) or len(supplied) != len(set(supplied)) or set(supplied) != set(ids):
            return {
                **base, "valid": True, "committed": False, "replacement_decision_required": True,
                "reason": "a controller with several Replacement Effects in one batch orders its own sequences",
                "replacement_decision": "sequence_order", "replacement_ids": sorted(ids), "event_ids": sorted(object_ids),
                "decision_controller": controller, "trace": [],
            }
        for position, replacement_id in enumerate(supplied):
            sequence_rank[replacement_id] = position
    sequences = [replacement_id for _, _, replacement_id in
                 sorted((turn_position.get(descriptors[rid]["controller"], 0), sequence_rank[rid], rid) for rid in descriptors)]

    sequence_index = -1
    for sequence_id in sequences:
        if sequence_id in spent:
            continue  # Core 374: it was already applied in an earlier sequence
        descriptor = descriptors[sequence_id]
        # The qualifying set is read when the sequence starts, not before the
        # batch: an earlier sequence may have moved the Replacement Effect's
        # source, and "another unit you control *here*" then means somewhere
        # else. This is the Soraka / Guardian Angel example's whole point.
        qualified_ids = [object_id for object_id in object_ids
                         if object_id not in prevented
                         and any(item["replacement_id"] == sequence_id
                                 for item in _applicable_replacements(current, events[object_id]))]
        if not qualified_ids:
            continue
        supplied = (replacement_event_order or {}).get(sequence_id)
        if len(qualified_ids) > 1:
            ledger_note("replacement", f"replacement:event_order:{sequence_id}:{'+'.join(qualified_ids)}{_iteration_suffix()}")
            if not isinstance(supplied, list) or len(supplied) != len(set(supplied)) or set(supplied) != set(qualified_ids):
                return {
                    **base, "valid": True, "committed": False, "replacement_decision_required": True,
                    "reason": "replacement controller must order every qualifying simultaneous event",
                    "replacement_decision": "event_order", "replacement_ids": [sequence_id], "event_ids": qualified_ids,
                    "decision_controller": descriptor["controller"], "trace": trace,
                }
            qualified_ids = supplied
        sequence_applied: set[str] = set()
        for object_id in qualified_ids:
            sequence_index += 1
            if object_id in prevented:
                continue
            applicable_now = [item for item in _applicable_replacements(current, events[object_id])
                              if item["replacement_id"] not in spent]
            if not applicable_now or sequence_id not in {item["replacement_id"] for item in applicable_now}:
                continue
            # Core 373.1: this event's order is the affected object's controller's.
            decider = current["objects"][object_id].get("controller")
            event = copy.deepcopy(events[object_id])
            choices: dict[str, bool] = {}
            for item in applicable_now:
                if not item["optional"]:
                    continue
                ledger_note("replacement", f"replacement:choice:{item['replacement_id']}:{object_id}{_iteration_suffix()}")
                choice = ((replacement_choices or {}).get(item["replacement_id"]) or {}).get(object_id)
                if not isinstance(choice, bool):
                    return {
                        **base, "valid": True, "committed": False, "replacement_decision_required": True,
                        "reason": "optional simultaneous replacement requires an explicit choice for the next qualifying event",
                        "replacement_decision": "choice", "replacement_ids": [item["replacement_id"]], "event_ids": [object_id],
                        "decision_controller": item["controller"], "trace": trace,
                    }
                choices[item["replacement_id"]] = choice
            if not any(choices.get(item["replacement_id"], True) for item in applicable_now):
                # Core 372: every applicable one was declined, so none was applied
                # and none spent its use; the event dies unmodified with the rest.
                unchanged_hash = hash_value(current)
                trace.append({
                    "phase": "replacement_sequence", "sequence_index": sequence_index,
                    "effect_id": event["effect_id"], "object_id": object_id, "op": "kill",
                    "outcome": "replacement_declined",
                    "replacement_id": sorted(choices)[0] if choices else None,
                    "declined": sorted(choices),
                    "before_state_hash": unchanged_hash, "after_state_hash": unchanged_hash,
                    "rule_locators": ["Core 371.2–371.2.b", "Core 373–373.2.a.1"],
                })
                continue
            if len(applicable_now) > 1:
                ids = [item["replacement_id"] for item in applicable_now]
                ledger_note("replacement", f"replacement:object_order:{'+'.join(sorted(ids))}:{object_id}{_iteration_suffix()}")
                supplied = (event_replacement_order or {}).get(object_id)
                if not isinstance(supplied, list) or len(supplied) != len(set(supplied)) or set(supplied) != set(ids):
                    return {
                        **base, "valid": True, "committed": False, "replacement_decision_required": True,
                        "reason": "the player controlling the affected object picks the order of the Replacement Effects on it",
                        "replacement_decision": "object_order", "replacement_ids": sorted(ids), "event_ids": [object_id],
                        "decision_controller": decider, "trace": trace,
                    }
                event["replacement_order"] = list(supplied)
                event["replacement_decider"] = decider
            if choices:
                event["replacement_choices"] = choices
            before_hash = hash_value(current)
            sequence_program = {
                "schema_version": PROGRAM_VERSION,
                "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "program_id": f"simultaneous:{event['effect_id']}",
                "controller": decider,
                "effects": [event],
            }
            sequence_result = apply_program(current, sequence_program, _applied_replacements=frozenset(spent))
            if sequence_result.get("committed") is not True:
                return {
                    **base, "valid": sequence_result.get("valid", True), "committed": False,
                    "unsupported": sequence_result.get("unsupported", False),
                    "reason_code": sequence_result.get("reason_code", "replacement_sequence_failed"),
                    "reason": sequence_result.get("reason", "; ".join(sequence_result.get("errors", [])) or "replacement sequence failed"),
                    "sequence_result": sequence_result, "trace": trace,
                }
            applied_here = _replacement_ids_applied(sequence_result.get("trace", []))
            if not applied_here:
                continue
            current = sequence_result["next_state"]
            sequence_applied |= applied_here
            entry = dict(sequence_result["trace"][0])
            sequence_locators = ["Core 373–373.2.a.1", "Core 374"]
            if any(descriptors[rid]["source_object"] in object_ids for rid in applied_here if rid in descriptors):
                sequence_locators.insert(0, "Core 370.4")
            entry.update({
                "phase": "replacement_sequence", "sequence_index": sequence_index,
                "effect_id": event["effect_id"], "object_id": object_id,
                "applied_replacements": sorted(applied_here),
                "before_state_hash": before_hash, "after_state_hash": hash_value(current),
                "rule_locators": list(dict.fromkeys(entry.get("rule_locators", []) + sequence_locators)),
            })
            trace.append(entry)
            prevented.add(object_id)
        # The sequence has ended: everything it applied is spent for the batch.
        spent |= sequence_applied | ({sequence_id} if sequence_applied else set())

    import game_events

    log = game_events.EventLog(f"kill-batch:{base['input_state_hash'][:12]}", actor=None,
                               source_object=(attributed_sources or [None])[0])
    killed = []
    for object_id in object_ids:
        if object_id in prevented:
            continue
        before_snapshot = game_events.snapshot(current)
        current, event_trace = _apply_one(current, events[object_id])
        event_trace.update({
            "phase": "unmodified_simultaneous_events", "effect_id": events[object_id]["effect_id"],
            "simultaneous_group": copy.deepcopy(object_ids),
            "before_state_hash": trace[-1]["after_state_hash"] if trace else hash_value(state),
            "after_state_hash": hash_value(current),
            "rule_locators": list(dict.fromkeys(event_trace["rule_locators"] + ["Core 373.1.a"])),
        })
        trace.append(event_trace)
        # ADR-0014 §1: these deaths are simultaneous, so every one of them is an
        # event of the same batch, each with its own causality.
        try:
            log.record(before_snapshot, game_events.snapshot(current), event_trace)
        except game_events.EventKindUnknown as exc:
            return {**base, "valid": True, "committed": False, "unsupported": True,
                    "reason_code": exc.reason_code, "reason": str(exc), "trace": trace}
        killed.append(object_id)
    group_pending_triggers([event for event in trace if event.get("phase") == "unmodified_simultaneous_events"], current)
    pending_triggers = [trigger for event in trace for trigger in event.get("pending_triggers", [])]
    return {
        **base, "valid": True, "committed": True, "unsupported": False,
        "next_state": current, "next_state_hash": hash_value(current),
        "killed_objects": killed, "prevented_objects": [object_id for object_id in object_ids if object_id in prevented],
        "trace": trace, "pending_triggers": pending_triggers,
        "events": log.events, "event_coverage": log.problems or "complete",
        "coverage": "single-prevention-descriptor-simultaneous-kill-batch",
    }


def _decision_keys(maps: dict[str, Any]) -> set:
    """Every (map, key) a caller's cleanup decisions supply."""
    return {(name, key) for name, given in maps.items() if isinstance(given, dict) for key in given}


def _iteration_decisions(state: dict[str, Any], group: list[str], attributed_sources, attributed_sources_by_object,
                         maps: dict[str, Any]) -> dict[str, Any]:
    """The part of a cleanup's decisions one iteration's kill batch can use: keyed by a Replacement Effect that applies
    to one of its deaths, by one of its dying objects, or by a player whose sequence order is exactly that player's
    Replacement Effects here (Core 372) - and '_consumed', the (map, key) pairs taken. Malformed maps pass through whole,
    for the batch to refuse."""
    applicable: dict[str, str] = {}
    for object_id in group:
        event = {"effect_id": f"simultaneous-kill:{object_id}", "op": "kill", "object_id": object_id,
                 "kill_mode": "passive_lethal_cleanup",
                 "attributed_sources": list((attributed_sources_by_object or {}).get(object_id, attributed_sources or []))}
        for descriptor in _applicable_replacements(state, event):
            applicable[descriptor["replacement_id"]] = descriptor.get("controller")
    players = set(state.get("players") or {})
    out: dict[str, Any] = {"_consumed": set()}
    for name, given in maps.items():
        if not isinstance(given, dict):
            out[name] = given
            continue
        kept = {}
        for key, value in given.items():
            if key in applicable or key in group:
                kept[key] = value
            elif key in players and isinstance(value, list) \
                    and set(value) == {rid for rid, controller in applicable.items() if controller == key}:
                kept[key] = value
            else:
                continue
            out["_consumed"].add((name, key))
        out[name] = kept or None
    return out


def perform_lethal_cleanup(
    state: dict[str, Any],
    *,
    attributed_sources: list[str] | None = None,
    replacement_event_order: dict[str, list[str]] | None = None,
    replacement_choices: dict[str, dict[str, bool]] | None = None,
    attributed_sources_by_object: dict[str, list[str]] | None = None,
    event_replacement_order: dict[str, list[str]] | None = None,
    replacement_sequence_order: dict[str, list[str]] | None = None,
    turn_order: list[str] | None = None,
    later_iterations: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`later_iterations` (package 15, GPT PACKAGE15 round 2 ruling 1): {k: the decision maps of follow-up iteration k}
    (engine_decisions.later_iteration_maps) - given, an iteration from the second on reads only its own, so each batch's
    choices are made as it is met (Core 373) and a request names its iteration (`cleanup_iteration`); not given (a caller
    with no decisions), every iteration reads the maps above, as before."""
    base = {
        "schema_version": "riftbound-lethal-cleanup-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "input_state_hash": hash_value(state),
    }
    errors = validate_state(state)
    if errors:
        return {**base, "valid": False, "committed": False, "errors": errors, "trace": []}
    current = copy.deepcopy(state)
    trace: list[dict[str, Any]] = []
    pending_triggers: list[dict[str, Any]] = []
    initial_group: list[str] = []
    killed_objects: list[str] = []
    stable_prevented: list[str] = []
    # 2026-09-28: the deaths' events (ADR-0014), which the kill batch records and this dropped - so a
    # unit dead of lethal damage never woke a "when a unit dies" watcher (Core 428; review 5 R2-6)
    events: list[dict[str, Any]] = []
    iterations = 0
    consumed: set = set()
    while iterations < 16:
        lethal = []
        for object_id, obj in current["objects"].items():
            location = find_location(current, object_id)
            if obj["kind"] != "unit" or location is None or not (location[0] == "battlefield" or location[2] == "base"):
                continue
            might = effective_might(current, object_id)
            if obj["damage"] > 0 and obj["damage"] >= might:
                lethal.append((object_id, might, obj["damage"]))
        group = [object_id for object_id, _, _ in sorted(lethal)]
        if not group:
            break
        if not initial_group:
            initial_group = copy.deepcopy(group)
        facts = {object_id: (might, damage) for object_id, might, damage in lethal}
        before_iteration_hash = hash_value(current)
        # 2026-10-18 package 15 (GPT PACKAGE14 ruling 7): every iteration gets the decisions of its own batch - those
        # that name a Replacement Effect that applies to one of its deaths, one of its dying objects, or (a controller's
        # sequence order) exactly its Replacement Effects of that controller; until now only the first iteration got any,
        # so a follow-up iteration that asked again could never be answered
        if later_iterations is not None and iterations >= 1:
            maps = {"replacement_event_order": None, "replacement_choices": None, "event_replacement_order": None,
                    "replacement_sequence_order": None, **(later_iterations.get(iterations) or {})}
        else:
            maps = {"replacement_event_order": replacement_event_order, "replacement_choices": replacement_choices,
                    "event_replacement_order": event_replacement_order, "replacement_sequence_order": replacement_sequence_order}
        scoped = _iteration_decisions(current, group, attributed_sources, attributed_sources_by_object, maps)
        consumed |= {(iterations,) + key if later_iterations is not None and iterations >= 1 else key
                     for key in scoped.pop("_consumed")}
        token = _CLEANUP_ITERATION.set(iterations if later_iterations is not None else 0)
        try:
            batch = apply_simultaneous_kill_batch(
                current,
                group,
                replacement_event_order=scoped["replacement_event_order"],
                replacement_choices=scoped["replacement_choices"],
                event_replacement_order=scoped["event_replacement_order"],
                replacement_sequence_order=scoped["replacement_sequence_order"],
                turn_order=turn_order,
                kill_mode="passive_lethal_cleanup",
                attributed_sources=attributed_sources,
                attributed_sources_by_object=attributed_sources_by_object,
            )
        finally:
            _CLEANUP_ITERATION.reset(token)
        if batch.get("committed") is not True:
            return {
                **base, "valid": batch.get("valid", True), "committed": False,
                "unsupported": batch.get("unsupported", False),
                "replacement_decision_required": batch.get("replacement_decision_required", False),
                "cleanup_iteration": iterations if later_iterations is not None else 0,
                "reason": batch.get("reason", "; ".join(batch.get("errors", [])) or "simultaneous lethal batch failed"),
                # ADR-0014 §3: the caller has to know which player is being
                # asked to order which Replacement Effects, over which events.
                **{key: batch[key] for key in ("reason_code", "replacement_decision", "replacement_ids", "event_ids",
                                               "decision_controller") if key in batch},
                "batch_result": batch, "trace": trace,
            }
        current = batch["next_state"]
        batch_id = f"lethal-cleanup:{public_id(state)}:{iterations}"
        for event in batch["trace"]:
            copied_event = copy.deepcopy(event)
            object_id = copied_event.get("object_id")
            if object_id in facts:
                copied_event["lethal_might"], copied_event["marked_damage"] = facts[object_id]
            copied_event["cleanup_iteration"] = iterations
            copied_event["rule_locators"] = list(dict.fromkeys(copied_event.get("rule_locators", []) + ["Core 142.4", "Core 322–323.5", "Core 428"]))
            trace.append(copied_event)
        for trigger in batch.get("pending_triggers", []):
            copied_trigger = copy.deepcopy(trigger)
            copied_trigger["batch_sequence"] = iterations
            copied_trigger["batch_id"] = batch_id
            copied_trigger.setdefault("trigger_kind", "self_death")
            pending_triggers.append(copied_trigger)
        killed_objects.extend(batch.get("killed_objects", []))
        # Core 383.3.d (GPT 2026-09-27): a watcher of one of these deaths triggers with the death
        # triggers of the same Cleanup iteration - the events name that batch
        events.extend({**copy.deepcopy(e), "trigger_batch_id": batch_id} for e in batch.get("events") or [])
        iterations += 1
        if hash_value(current) == before_iteration_hash:
            stable_prevented = batch.get("prevented_objects", [])
            break
    else:
        return {
            **base, "valid": True, "committed": False, "unsupported": True,
            "reason": "lethal cleanup replacement loop exceeded 16 iterations", "trace": trace,
        }
    # a decision no iteration's batch had any use for names a Replacement Effect, object or order that never applied -
    # refused, as the batch itself refused one before every iteration got its own (fail closed, never ignored)
    supplied = _decision_keys({"replacement_event_order": replacement_event_order, "replacement_choices": replacement_choices,
                               "event_replacement_order": event_replacement_order,
                               "replacement_sequence_order": replacement_sequence_order})
    for k, maps in (later_iterations or {}).items():
        supplied |= {(k,) + key for key in _decision_keys(maps)}
    # (only once a batch ran: a Cleanup with nothing lethal reads none of them, as before - other procedures share the maps)
    if iterations and supplied - consumed:
        return {**base, "valid": False, "committed": False,
                "errors": [f"cleanup decisions reference non-applicable replacements: {sorted(k[1] for k in supplied - consumed)}"],
                "trace": trace}
    return {
        **base,
        "valid": True,
        "committed": True,
        "unsupported": False,
        "next_state": current,
        "next_state_hash": hash_value(current),
        "lethal_objects": initial_group,
        "killed_objects": killed_objects,
        "stable_prevented_objects": stable_prevented,
        "cleanup_iterations": iterations,
        "trace": trace,
        "pending_triggers": pending_triggers,
        "events": events,
        "coverage": "lethal-damage-with-single-prevention-descriptor-sequencing",
    }


def _resolve_discard(state: dict[str, Any], effect: dict[str, Any], decisions: dict[str, Any] | None,
                     program: dict[str, Any] | None = None) -> dict[str, Any]:
    """ADR-0007 §10 / Core 422: the discarding player chooses from their own
    hand with private information (422.1.a) — a card_selection decision, never
    a target. When the whole hand must go and only one set is legal, the
    engine proceeds; otherwise it stops for the decision. Since ADR-0011 §1
    the choice is the generic specification {unordered_set, exactly count,
    from hand, by the player, private}.

    2026-10-08 package 10 (Mindsplitter): a discard carrying DISCARD_REVEALED_CHOICE is chosen by the PROGRAM'S
    controller, among the cards an earlier reveal showed (Core 424.2.b: candidates are the reveal's own marks, so
    nothing still private is choosable) that are in the hand of the player an earlier instruction chose; that
    player discards it (422.1). Nothing revealed there: nothing is discarded."""
    if effect.get("choice") is not None:
        controller = (program or {}).get("controller")
        # "they": the player whose hand the named reveal revealed - read off that reveal instruction itself
        revealer = next((e for e in (program or {}).get("effects") or [] if e.get("effect_id") == effect.get("reveal_ref")), None)
        player_id = resolve_player_ref(revealer.get("player"), decisions, state, controller) if revealer else None
        if player_id not in state["players"]:
            raise ValueError("discard from a reveal requires the hand reveal it names (reveal_ref)")
        hand = state["players"][player_id]["zones"]["hand"]
        revealed, _ = choice_candidates(state, effect["choice"], controller)
        candidates = [o for o in revealed if o in hand]
        if not candidates:
            return {**effect, "player": player_id, "count": 1, "objects": [],
                    "selection_meta": {"forced": True, "reason": "nothing revealed is in that player's hand"}}
        chosen, meta = resolve_choice(state, effect["choice"], decision_ref=effect["decision_ref"], decisions=decisions,
                                      controller=controller, candidates=candidates)
        return {**effect, "player": player_id, "count": 1, "objects": chosen,
                "selection_meta": {"forced": bool(meta.get("forced")), "decision_id": meta.get("decision_id"),
                                   "chosen_by": controller, "choice": meta.get("choice")}}
    player_id, count = effect.get("player"), effect.get("count")
    if effect.get("whole_hand") is True and player_id in state["players"]:
        # package 6: "discards their hand" - every card in it now; nothing to choose. An empty hand
        # discards nothing, and the instruction is ignored (Core 422.4)
        hand = list(state["players"][player_id]["zones"]["hand"])
        return {**effect, "count": len(hand), "objects": hand,
                "selection_meta": {"forced": True, "reason": "the whole hand is discarded (Core 422.1, 422.4)"}}
    if player_id not in state["players"] or not isinstance(count, int) or count < 1:
        raise ValueError("discard requires a known player and a resolved selection")
    spec = {"selection_kind": "unordered_set", "count": {"exactly": count}, "from": "hand", "by": player_id, "visibility": "private_to_chooser", "identity_binding": True}
    chosen, meta = resolve_choice(state, spec, decision_ref=effect.get("decision_ref") or f"discard:{player_id}{execution_suffix(effect)}",
                                  decisions=decisions, controller=player_id)
    if meta["forced"]:
        return {**effect, "objects": chosen, "selection_meta": {"forced": True, "reason": "every card in hand must be discarded (Core 422.4)", "choice": meta["choice"]}}
    return {**effect, "objects": chosen, "selection_meta": {"forced": False, "decision_id": meta["decision_id"], "choice": meta["choice"]}}


def buff_count(obj: dict[str, Any]) -> int:
    """How many buffs the object has (Core 702.3; 426.1.b.2 with any_number_of_buffs): 0, 1, or its buff_count."""
    if not obj.get("buffed"):
        return 0
    return obj.get("buff_count", 1) if obj.get("any_number_of_buffs") is True else 1


def spend_one_buff(obj: dict[str, Any]) -> None:
    """Spend ONE of the object's buffs (Core 702.2.b): the count drops by one; the last one removes the flag."""
    count = buff_count(obj)
    if count > 2:
        obj["buff_count"] = count - 1
    elif count == 2:
        obj.pop("buff_count", None)
    else:
        obj.pop("buff_count", None)
        del obj["buffed"]


# 2026-10-06 package 9 (Nocturne - Horrifying): the instructions that make a player look at or reveal cards from the TOP
# of a Main Deck (a plain draw is not a look)
SEEN_FROM_TOP_OPS = {"look_at_top", "predict", "reveal", "reveal_until"}


def seen_from_top(prior: dict[str, Any], effect: dict[str, Any], event: dict[str, Any],
                  controller: str | None) -> tuple[str | None, list[str]]:
    """(the deck's owner, the cards that player looked at or revealed from the top of their own Main Deck) for one
    executed instruction; (None, []) when nobody looked at their own deck's top."""
    op = effect.get("op")
    if op in ("look_at_top", "predict"):
        player = effect.get("player")
        seer = effect.get("_controller") or controller if op == "look_at_top" else player
        if player not in prior["players"] or seer != player:
            return None, []
        return player, list(prior["players"][player]["zones"]["main_deck"][: int(effect.get("count") or 0)])
    if op == "reveal" and effect.get("from") != "main_deck_top":
        return None, []
    player = event.get("player")
    if player not in prior["players"]:
        return None, []
    return player, [r["object_id"] for r in event.get("revealed") or [] if isinstance(r, dict)]


def offer_seen_banish_now(state: dict[str, Any], player_id: str, looked: list[str], decisions: dict[str, Any] | None,
                          ref_prefix: str) -> tuple[list[str], list[dict[str, Any]]]:
    """package 9 (GPT 2026-10-07): inside an instruction that disposes of what it looks at (predict) - each looked-at
    card of `player_id`'s own deck that may banish itself (banish_when_seen) is offered to its owner (optional_choice
    "<ref_prefix>:<card>") before anything is done with it; banished (in place, a new object in its owner's Banishment),
    it leaves `looked`. Returns (the looked-at cards still there, the banished records)."""
    import engine_decisions as ed
    still, banished = [], []
    for card in looked:
        obj = state["objects"].get(card) or {}
        if not obj.get("banish_when_seen") or obj.get("owner") != player_id:
            still.append(card)
            continue
        ref = f"{ref_prefix}:{card}"
        ledger_note("seen_banish", ref)
        _shown_to_chooser(ref, state, card)
        entry = next((e for e in ed.entries(decisions, kind="optional_choice") if e.get("decision_id") == ref), None)
        if entry is None:
            raise ChoiceRequired(f"{card!r} is being looked at from the top of {player_id}'s Main Deck; its owner may "
                                 f"banish it now, before the instruction does anything with it", [ref], player_id,
                                 {"decision_kind": "optional_choice", "decision_id": ref, "card": card})
        if entry.get("controller") != player_id:
            raise IllegalDecision(f"{ref!r} was decided by {entry.get('controller')!r}, not the card's owner {player_id!r}")
        if entry.get("stage") != "resolution":
            raise ValueError(f"{ref!r} is decided as the card is looked at; it was supplied for stage {entry.get('stage')!r}")
        if entry["value"] is not True:
            still.append(card)
            continue
        working, done = banish_seen(state, card, player_id)
        state.clear()
        state.update(working)
        banished.append({"card": card, "owner": player_id, "identity": done["identities_after"][card],
                         "amount": obj["banish_when_seen"]["play_for_power_any"], "decision_id": ref})
    return still, banished


def banish_seen(state: dict[str, Any], card: str, owner: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Banish `card` from its owner's Main Deck (Core 427: a new object in its owner's Banishment, 124)."""
    working = copy.deepcopy(state)
    working["players"][owner]["zones"]["main_deck"].remove(card)
    _drop_reveals(working, [card])
    working["players"][owner]["zones"]["banishment"].append(card)
    identity = _bump_identity(working, card)
    return working, {"objects": [card], "destinations": {card: f"{owner}.banishment"}, "identities_after": {card: identity},
                     "not_kill": True, "not_discard": True}


def spend_buff_candidates(state: dict[str, Any], player_id: str) -> list[str]:
    """The Units a player may spend a buff from: on the board, controlled by that player, with a buff
    (Core 702.2.b.1, 702.2.b.2)."""
    return sorted(o for o, obj in state["objects"].items()
                  if obj.get("kind") == "unit" and obj.get("controller") == player_id and obj.get("buffed")
                  and zone_class(find_location(state, o)) == "board")


def _resolve_spend_buffs(state: dict[str, Any], effect: dict[str, Any], decisions: dict[str, Any] | None) -> dict[str, Any]:
    """Package 6: "Spend any number of buffs." - its player chooses, as it resolves (Core 355.17),
    any number of the Units they could spend a buff from (a public choice: the buffs are on the
    board). With none to choose from there is nothing to decide."""
    player_id = effect.get("player")
    if player_id not in state["players"]:
        raise ValueError("spend_buffs requires a known player")
    if effect.get("object_id") is not None:
        # package 10: "spend its buff" - the one named Unit's, nothing chosen
        return {**effect, "objects": [effect["object_id"]], "selection_meta": {"forced": True, "named": effect["object_id"]}}
    spec = {"selection_kind": "unordered_set", "count": {"any_number": True}, "from": "board", "by": player_id,
            "criteria": {"kind": "unit"}, "visibility": "public", "identity_binding": True}
    candidates = spend_buff_candidates(state, player_id)
    if not candidates:
        return {**effect, "objects": [], "selection_meta": {"forced": True, "reason": "no Unit its player controls has a buff"}}
    several = [o for o in candidates if buff_count(state["objects"][o]) > 1]
    ref = effect.get("decision_ref") or f"spend_buffs:{player_id}{execution_suffix(effect)}"
    import engine_decisions as ed
    supplied = ed.decision_entry(decisions, ref)
    if several:
        # 2026-10-16 package 14 (GPT PACKAGE11's named debt): a Unit that may have any number of buffs (Core 426.1.b.2,
        # Lee Sin - Ascetic) can spend several, one at a time (702.2.b) - so the choice is how many of each Unit's buffs,
        # a buff_spend {unit: how many}, each at most what the Unit has; the Units with one buff are chosen the same way
        counts = {o: buff_count(state["objects"][o]) for o in candidates}
        identities = {o: object_identity(state, o) or f"{o}@0" for o in candidates}
        summary = {"decision_kind": "buff_spend", "selection_kind": "buff_counts", "count": {"any_number": True},
                   "from": "board", "chooser": player_id, "visibility": "public", "identity_binding": True,
                   "options_count": len(candidates), "options_enumerated": True, "buff_counts": counts,
                   "options": [{"object_id": o, "identity": identities[o], "buffs": counts[o]} for o in candidates]}
        if supplied is None:
            raise ChoiceRequired(f"{player_id} chooses how many buffs to spend from each of {candidates}", [ref], player_id, summary)
        if supplied.get("kind") != "buff_spend" or supplied.get("stage") != "resolution":
            raise ValueError(f"decision {ref!r} must be a resolution-stage buff_spend: a Unit here has more than one buff")
        if supplied["controller"] != player_id:
            raise IllegalDecision(f"buff_spend {ref!r} was made by {supplied['controller']!r}, not {player_id!r}")
        value = supplied["value"]
        for unit, n in value.items():
            if unit not in counts or n > counts[unit]:
                raise IllegalOperation(f"{unit!r} cannot spend {n} buff(s) here: it has {counts.get(unit, 0)} (702.2.b.1)")
            if (supplied.get("selection_identities") or {}).get(unit) != identities[unit]:
                raise ValueError(f"buff_spend {ref!r} binds {unit!r} to another object than the one there now (Core 124)")
        objects = [unit for unit in sorted(value) for _ in range(value[unit])]
        return {**effect, "objects": objects, "selection_meta": {"forced": False, "decision_id": ref, "buff_counts": dict(value)}}
    if supplied is not None and supplied.get("stage") != "resolution":
        raise ValueError(f"decision {ref!r} must be a resolution-stage decision: buffs are counters, not targets "
                         "(Core 704.1), so what is spent is chosen as the instruction resolves (355.17)")
    chosen, meta = resolve_choice(state, spec, decision_ref=ref, decisions=decisions, controller=player_id, candidates=candidates)
    return {**effect, "objects": chosen, "selection_meta": meta}


def _resolve_choice_object(state: dict[str, Any], effect: dict[str, Any], program: dict[str, Any], decisions: dict[str, Any] | None) -> dict[str, Any]:
    """An instruction whose single object comes from a `choice` (recycle_one
    from the trash, banish a card from hand): the chosen id becomes object_id."""
    chosen, meta = resolve_choice(state, effect["choice"], decision_ref=effect.get("decision_ref"), decisions=decisions, controller=program.get("controller"),
                                  execution=execution_suffix(effect))
    if not chosen:
        return {**effect, "object_id": None, "selection_meta": {**meta, "empty": True}}
    return {**effect, "object_id": chosen[0], "selection_meta": meta}


def candidate_identity(state: dict[str, Any], source: str, candidate_id: str) -> str | None:
    """The identity token a choice binds a candidate to.

    One function so the enumeration and any later re-check cannot disagree.
    Battlefields keep their own identity (they are not in `state["objects"]`, so
    object_identity would read None for every one of them and silently defeat
    identity binding); players have none.
    """
    if source == "players":
        return None
    if source == "battlefields":
        return battlefield_identity(state, candidate_id)
    return object_identity(state, candidate_id)


def choice_candidates(state: dict[str, Any], spec: dict[str, Any], chooser: str, session: dict[str, Any] | None = None,
                      program: dict[str, Any] | None = None) -> tuple[list[str], dict[str, str | None]]:
    """The ordered candidate list of a choice source and the current identity
    of each candidate (None for players).

    `program` is needed only when the choice's criteria carries a
    `location_ref` ("here") - GPT 2026-09-23. A caller with no program in
    scope simply cannot resolve that shape, which SelectionBindingRefused
    (raised by resolve_location_ref, propagated to the caller) makes explicit
    rather than silently returning an empty or unfiltered candidate set."""
    source = spec["from"]
    if source == "hand":
        ids = list(state["players"][chooser]["zones"]["hand"])
    elif source == "trash":
        ids = list(state["players"][chooser]["zones"]["trash"])
    elif source == "trashes":
        # 2026-10-12 (package 11, Forge of the Future; GPT PACKAGE11 ruling 7): "cards from trashes" - every player's
        # trash, read as the instruction executes (Core 416.6: chosen then, not targets)
        ids = [c for player in sorted(state["players"]) for c in state["players"][player]["zones"].get("trash", [])]
    elif source == "main_deck_top":
        ids = list(state["players"][chooser]["zones"]["main_deck"][: spec["top"]])
    elif source == "revealed":
        # The candidates are exactly what a reveal actually put on the table for
        # this chooser. Nothing else in the zone is choosable, which is what
        # keeps a hand private until it is revealed (Core 424.2.b, 128.4).
        ids = [r["object_id"] for r in (session or state).get("reveals", [])
               if r.get("visible_to") == "all" or chooser in (r.get("visible_to") or [])]
        excluded = set((spec.get("criteria") or {}).get("excluded_kinds") or [])
        if excluded:
            ids = [object_id for object_id in ids
                   if state["objects"].get(object_id, {}).get("kind") not in excluded]
        # 2026-10-04 (package 8): "a unit from among them" - the kind; "that has Might up to N" - a ceiling on the
        # card's printed Might (a card off the board has no other, Core 359.3.e.12). A ceiling resolved to None
        # (its reference is null: no unit was killed, GPT ruling 7) admits nothing
        criteria = spec.get("criteria") or {}
        if "kind" in criteria:
            ids = [o for o in ids if state["objects"].get(o, {}).get("kind") == criteria["kind"]]
        if "max_might" in criteria:
            ceiling = criteria["max_might"]
            ids = [] if ceiling is None else [o for o in ids if isinstance(state["objects"].get(o, {}).get("base_might"), int)
                                              and state["objects"][o]["base_might"] <= ceiling]
    elif source == "board":
        criteria = spec.get("criteria") or {}
        resolved_battlefield = None
        if criteria.get("location_ref") is not None:
            resolved_battlefield = resolve_location_ref(criteria["location_ref"], state, program or {})
        ids = []
        places = [("base", pid, state["players"][pid]["zones"]["base"]) for pid in state["players"]] + [("battlefield", bid, bf["objects"]) for bid, bf in state["battlefields"].items()]
        for where, zone_owner, objects in places:
            if resolved_battlefield is not None and (where != "battlefield" or zone_owner != resolved_battlefield):
                continue
            if criteria.get("location") == "battlefield" and where != "battlefield":
                continue
            if criteria.get("location") == "base" and where != "base":
                continue
            # Whose Base. "in your base" is narrower than location=base, which
            # admits every player's; without this the phrase would lower to a
            # wider candidate set than the card describes.
            owner_relation = criteria.get("zone_owner_relation")
            if owner_relation == "own" and zone_owner != chooser:
                continue
            if owner_relation == "opponent" and zone_owner == chooser:
                continue
            for object_id in objects:
                obj = state["objects"][object_id]
                if "kind" in criteria and obj["kind"] != criteria["kind"]:
                    continue
                relation = criteria.get("controller_relation")
                if relation == "friendly" and not same_side(state, chooser, obj.get("controller")):
                    continue
                if relation == "enemy" and same_side(state, chooser, obj.get("controller")):
                    continue
                # package 6: "one of THEIR units" - controlled by the chooser, not a teammate's (411.1)
                if relation == "own" and obj.get("controller") != chooser:
                    continue
                # package 6: "a unit YOU don't control" - named by the program's controller, not the chooser
                if "not_controlled_by" in criteria and obj.get("controller") == criteria["not_controlled_by"]:
                    continue
                ids.append(object_id)
    elif source == "battlefields":
        # Core 355.4.a, ADR-0007 §4: a Battlefield is a Location on the board and
        # a target with a bindable identity, but it is NOT one of the objects a
        # `board` choice walks - that source iterates the objects standing AT a
        # Battlefield, so "Choose a battlefield." can never be answered through
        # it. This is its own candidate universe.
        ids = sorted(state["battlefields"])
    elif source == "players":
        ids = [p for p in state["players"] if spec.get("players", "opponents") == "any" or p != chooser]
    else:
        raise ValueError(f"unknown choice source {source!r}")
    identities = {c: candidate_identity(state, source, c) for c in ids}
    return ids, identities


def resolve_player_ref(player: Any, decisions: dict[str, Any] | None, state: dict[str, Any],
                       controller: str | None) -> str:
    """A player named directly, or the one an earlier instruction of this same
    program chose. The reference is to the *decision*, not to a re-run of the
    choice: "they" means the opponent already chosen, and choosing again could
    land on somebody else."""
    if isinstance(player, str):
        return player
    if not isinstance(player, dict) or not isinstance(player.get("decision_ref"), str):
        raise ValueError("a player must be named, or deferred to a decision_ref")
    import engine_decisions as ed
    entry = ed.player_selection(decisions, player["decision_ref"])
    if entry is None:
        raise PlayerSelectionRequired(
            f"player selection {player['decision_ref']!r} is required", [player["decision_ref"]], controller)
    if entry["controller"] != controller:
        raise IllegalDecision(f"player selection {player['decision_ref']!r} was made by "
                              f"{entry['controller']!r}, not the program controller")
    if entry["value"] not in state["players"]:
        raise ValueError(f"player selection {player['decision_ref']!r} names {entry['value']!r}, "
                         "who is not in this game")
    return entry["value"]


def resolve_choice(state: dict[str, Any], spec: dict[str, Any], *, decision_ref: str | None, decisions: dict[str, Any] | None,
                   controller: str | None, session: dict[str, Any] | None = None, chooser: str | None = None, candidates: list[str] | None = None,
                   execution: str = "") -> tuple[list[str], dict[str, Any]]:
    """ADR-0011 §1. Returns (chosen ids, meta). Raises ChoiceRequired when the
    decision is absent, IllegalDecision when another player made it,
    IllegalOperation when it names a non-candidate, ValueError when it is
    malformed, stale or the wrong count, NotImplementedError for a chooser
    rule this slice does not have.

    `execution` is the Repeat execution's suffix ("#1", ...; execution_suffix). A choice with no
    decision_ref of its own is answered under a default ref; a Repeat copy's default carries the
    suffix, so the copy makes its own choice and never reads the first execution's (Core 820.2.a)."""
    import engine_decisions as ed
    problems = ed.validate_choice_spec(spec)
    if problems:
        raise ValueError("choice: " + "; ".join(problems))
    by = spec.get("by", "controller")
    if chooser is None:
        if by == "controller":
            chooser = controller
        elif by == "opponent":
            others = [p for p in state["players"] if p != controller]
            if len(others) != 1:
                raise NotImplementedError("a choice by 'opponent' with several opponents needs a player_selection first (unsupported: multi_opponent_choice)")
            chooser = others[0]
        elif by == "each_player":
            raise NotImplementedError("each_player choices are outside this slice (unsupported: each_player_choice)")
        else:
            chooser = by
    if chooser not in state["players"]:
        raise ValueError(f"choice chooser {chooser!r} is not a player")
    if candidates is None:
        candidates, identities = choice_candidates(state, spec, chooser, session)
    else:
        identities = {c: candidate_identity(state, spec["from"], c) for c in candidates}
    forced = ed.forced_choice(spec, candidates)
    summary = ed.choice_summary(spec, chooser, candidates, identities)
    if forced is not None:
        return forced, {"forced": True, "reason": "no alternative: every candidate is taken or there is none (Core 359.3.e)", "choice": summary}
    ref = decision_ref or f"choice:{spec['from']}:{chooser}{execution}"
    # every choice that is not forced is noted as needed (package 15: a slot the procedure meets no need of is one it
    # does not read here - decision_space.contract_ways); an order of cards is also held to the ledger (event_ledger)
    ledger_note("choice", ref)
    if spec.get("selection_kind") == "ordered_permutation":
        ledger_note("card_ordering", ref)
    entry = ed.decision_entry(decisions, ref)
    if entry is None:
        log = _PRIVATE_OPTIONS.get()
        if log is not None and "options" not in summary:
            log[ref] = [{"object_id": c, "identity": identities.get(c)} for c in candidates]
        raise ChoiceRequired(f"{chooser} chooses from {spec['from']} ({spec['selection_kind']})", [ref], chooser, summary)
    chosen, failure, message = ed.check_choice_entry(spec, entry, chooser, candidates, identities)
    if failure == "controller":
        raise IllegalDecision(message)
    if failure == "illegal":
        raise IllegalOperation(message)
    if failure == "invalid":
        raise ValueError(message)
    if entry["stage"] != "resolution" and entry["kind"] in {"card_selection", "card_ordering"} and not (session or {}).get("allow_play_stage"):
        raise ValueError(f"decision {ref!r} must be a resolution-stage decision")
    return chosen, {"forced": False, "decision_id": entry["decision_id"], "choice": {k: v for k, v in summary.items() if k != "options"}}


# The Repeat execution an instruction belongs to ("#1", ...), stamped on a copy by
# _resolve_executions. Engine-internal: never authored, read only by execution_suffix.
EXECUTION_FIELD = "_execution"


def execution_suffix(effect: dict[str, Any]) -> str:
    value = effect.get(EXECUTION_FIELD)
    return value if isinstance(value, str) else ""


def suffix_decision_refs(effects: list[dict[str, Any]], suffix: str) -> list[dict[str, Any]]:
    """ADR-0011 §4 / Core 820.2.a: an additional Repeat execution makes its own
    choices — every decision reference and effect id of the copy carries the
    execution suffix, and internal references follow.

    2026-09-28 (review 5, R1-4): the linked references (Core 359.3.e.14) follow too - "its
    controller" (player.object_player), "its Might" / "its Energy cost" (amount_ref), "it deals"
    (source_ref) name the COPY's earlier instruction, never the first execution's - and so do the
    copy's own choices: an optional instruction's decision, a split's division, a chosen
    destination, a chosen player, and a selection it establishes with the references to it."""
    out: list[dict[str, Any]] = []
    for index, effect in enumerate(effects):
        copied = copy.deepcopy(effect)
        copied["effect_id"] = copied.get("effect_id", f"effect-{index}") + suffix
        for key in ("depends_on",):
            if isinstance(copied.get(key), str):
                copied[key] = copied[key] + suffix
        if isinstance(copied.get("predicate"), dict) and isinstance(copied["predicate"].get("effect_id"), str):
            copied["predicate"]["effect_id"] += suffix
        # (package 10: reveal_ref, subject_ref and a linked destination name an instruction OUTSIDE the renamed part when
        # the overlay's assembler renames a colliding part with this function - they are left as they are; no Repeat
        # card carries them)
        for key in ("decision_ref", "recycle_ref", "order_ref", "put_back_ref", "division_ref", "selection_id"):
            if isinstance(copied.get(key), str):
                copied[key] += suffix
        for holder in ("target", "targets", "optional", "destination"):
            if isinstance(copied.get(holder), dict) and isinstance(copied[holder].get("decision_ref"), str):
                copied[holder]["decision_ref"] += suffix
        if isinstance(copied.get("target"), dict) and isinstance(copied["target"].get("selection_ref"), str):
            copied["target"]["selection_ref"] += suffix
        if isinstance(copied.get("units"), list):
            for unit in copied["units"]:
                if isinstance(unit, dict) and isinstance(unit.get("decision_ref"), str):
                    unit["decision_ref"] += suffix
                if isinstance(unit, dict) and isinstance(unit.get("selection_ref"), str):
                    unit["selection_ref"] += suffix
        player = copied.get("player")
        if is_object_player(player):
            player["object_player"]["effect_id"] += suffix
        elif isinstance(player, dict) and isinstance(player.get("decision_ref"), str):
            player["decision_ref"] += suffix
        amount_ref = copied.get("amount_ref")
        if isinstance(amount_ref, dict) and amount_ref.get("kind") in LINKED_AMOUNT_REF_KINDS \
                and isinstance(amount_ref.get("effect_id"), str):
            amount_ref["effect_id"] += suffix
        if is_source_ref(copied.get("source_ref")):
            copied["source_ref"]["effect_id"] += suffix
        out.append(copied)
    return out


def _resolve_executions(program: dict[str, Any], decisions: dict[str, Any] | None, context: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """One execution, plus one more per paid Repeat recorded on the chain
    entry (820.1.d); each has its own mode and suffixed choices (820.2.a)."""
    repeat = (context or {}).get("repeat") or {}
    executions = int(repeat.get("executions", 1)) if repeat else 1
    effects_to_run: list[dict[str, Any]] = []
    modes: list[dict[str, Any] | None] = []
    for k in range(executions):
        suffix = "" if k == 0 else f"#{k}"
        program_k = program
        if suffix and program.get("modal"):
            program_k = {**program, "modal": {**program["modal"], "decision_ref": program["modal"]["decision_ref"] + suffix}}
        context_k = context
        if suffix and repeat.get("modes"):
            context_k = {**(context or {}), "mode_selection": repeat["modes"][k]}
        effects, mode = _resolve_mode(program_k, decisions, context_k)
        if suffix:
            # a choice with no decision_ref of its own is answered under a default ref (resolve_choice,
            # discard): the copy's default carries the suffix too (execution_suffix). Stamped here, on
            # the executions only - suffix_decision_refs also composes a card's parts (overlay), whose
            # programs must not carry an engine-internal field
            effects_to_run.extend({**effect, EXECUTION_FIELD: suffix} for effect in suffix_decision_refs(effects, suffix))
        else:
            effects_to_run.extend(effects)
        modes.append(mode)
    repeat_meta = {"executions": executions, "modes": modes, "rule_locators": ["Core 820.1.d", "Core 820.2.a"]} if executions > 1 else None
    return effects_to_run, modes[0], repeat_meta


def _resolve_mode(program: dict[str, Any], decisions: dict[str, Any] | None, context: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """ADR-0011 §2: a modal program runs the instructions of the option a
    mode_selection decision names by stable id. A mode recorded at play (on
    the chain entry) is supplied through the context; an envelope entry must
    agree with it."""
    import engine_decisions as ed
    modal = program.get("modal")
    if not modal:
        return list(program.get("effects") or []), None
    ref = modal["decision_ref"]
    option_ids = [o["option_id"] for o in modal["options"]]
    entry = ed.mode_selection(decisions, ref)
    recorded = (context or {}).get("mode_selection")
    if entry is not None and entry["controller"] != program.get("controller"):
        raise IllegalDecision(f"mode {ref!r} was chosen by {entry['controller']!r}, not the program controller")
    if entry is not None and entry["stage"] != modal["timing"]:
        raise ValueError(f"mode {ref!r} was chosen at stage {entry['stage']!r}; this clause chooses it at {modal['timing']}")
    chosen = entry["value"] if entry is not None else (recorded or {}).get("option_id")
    if entry is not None and recorded is not None and recorded.get("decision_id") == ref and recorded.get("option_id") != entry["value"]:
        raise ValueError(f"mode {ref!r} was recorded as {recorded.get('option_id')!r} when the card was played; the envelope now says {entry['value']!r}")
    if chosen is None:
        raise ModeSelectionRequired(f"{program.get('controller')} chooses a mode of {program.get('program_id')} (Core 402.2)", [ref], program.get("controller"), option_ids)
    option = next((o for o in modal["options"] if o["option_id"] == chosen), None)
    if option is None:
        raise ValueError(f"mode {ref!r} names option {chosen!r}, which this program does not have; options are {option_ids}")
    return list(option["effects"]), {"decision_id": ref, "option_id": chosen, "options": option_ids, "recorded_at_play": entry is None, "rule_locators": ["Core 402.2", "Core 820.2.a"]}


def resolve_object_ref(effect: dict[str, Any], state: dict[str, Any],
                       program: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Turn `{"object_ref": "program_source"}` into the source object, or refuse.

    Returns (effect with a concrete object_id, meta). Raises
    SelectionBindingRefused with one of four named codes; the instruction then
    does not run, and nothing is substituted.

    The reference binds the source's FULL identity, not its id. An id can be
    reused after the object leaves and returns; the identity token cannot, which
    is the whole reason the engine tracks one.
    """
    ref = effect.get("object_id")
    if not is_object_ref(ref):
        return effect, {}
    if ref["object_ref"] not in OBJECT_REF_KINDS:
        raise SelectionBindingRefused(
            f"unknown object_ref {ref['object_ref']!r}; the engine resolves "
            f"{list(OBJECT_REF_KINDS)}", OBJECT_REF_ABSENT)
    if ref["object_ref"] == TRIGGER_EVENT_OBJECT:
        return resolve_trigger_event_object(effect, state, program)
    if effect.get("op") not in OBJECT_REF_OPS | OBJECT_REF_UNIT_SLOT_OPS:
        raise SelectionBindingRefused(
            f"op {effect.get('op')!r} has no reviewed object_ref adoption. Each op needs its own "
            f"executor audit and a real resolution fixture; one op resolving it proves nothing "
            f"about another", OBJECT_REF_OP_NOT_ADOPTED)
    # A clause that also names a target is not talking about itself.
    for field in ("target", "targets", "affected", "decision_ref"):
        if effect.get(field) is not None:
            raise SelectionBindingRefused(
                f"the instruction carries {field!r} beside a program_source reference; "
                f"'me' is self-referential and chooses nothing", OBJECT_REF_NOT_SELF)

    # 2026-09-28 (review 5, R1-2): the three ways the source can be GONE as the instruction
    # executes - no longer in the state though the program was bound to it, a new object at its
    # id, off the board - are game events (Core 359.3.e.6): SourceUnavailable, which apply_program
    # records as an ignored instruction and resolves the rest. A reference with no source, to a
    # non-permanent, or of the wrong shape is still refused whole.
    source = program.get("source_object")
    declared = program.get("source_identity")
    if not isinstance(source, str) or source not in state["objects"]:
        if isinstance(source, str) and source and isinstance(declared, str) and declared:
            raise SourceUnavailable(
                f"the program's source {declared!r} is no longer in the state (a token that left the board "
                f"ceased to exist, Core 186.1); 'me' cannot be acted on", OBJECT_REF_ABSENT)
        raise SelectionBindingRefused(
            f"the program declares source_object {source!r}, which the state does not contain; "
            f"a self-reference with no source is refused, never guessed", OBJECT_REF_ABSENT)

    now = object_identity(state, source)
    obj = state["objects"][source]
    where = find_location(state, source)
    legend_here = (obj.get("kind") == "legend" and effect.get("op") in OBJECT_REF_LEGEND_OPS
                   and where is not None and where[0] == "player" and where[2] == "legend_zone")
    if obj.get("kind") not in OBJECT_REF_PERMANENT_KINDS and not legend_here:
        raise SelectionBindingRefused(
            f"the source is a {obj.get('kind')!r}, not a permanent; only a permanent source is "
            f"wired for a self-reference", OBJECT_REF_LEFT_PLAY)
    if declared is not None and declared != now:
        raise SourceUnavailable(
            f"the program's source was {declared!r} and is now {now!r}; the object at that id is "
            f"not the one this instruction is about", OBJECT_REF_IDENTITY_CHANGED)
    if zone_class(where) != "board" and not legend_here:
        raise SourceUnavailable(
            f"the source {source!r} is not on the board any more, so it cannot be acted on by "
            f"its own instruction", OBJECT_REF_LEFT_PLAY)

    return ({**effect, "object_id": source, "subject_identity": now},
            {"object_ref": "program_source", "resolved_to": source, "bound_identity": now})


def resolve_trigger_event_object(effect: dict[str, Any], state: dict[str, Any],
                                 program: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """`{"object_ref": "trigger_event_object"}` - the triggered ability's "it": the object the event
    that met its trigger condition is about (TRIGGER_EVENT_OBJECT above). Returns (effect with a
    concrete object_id and subject_identity, meta).

    Refused whole (SelectionBindingRefused) - a malformed program, not a game event: an op with no
    reviewed adoption of this reference, an instruction that also names a target (it would be
    talking about something else), a program run with no `trigger_event` (it is not a watched
    trigger's program, or it was not run through its chain item), and a referent that is not a
    permanent. Ignored (SourceUnavailable, the instruction is recorded as not followed and the rest
    resolves - Core 359.3.e.6, 359.3.f.2.a): the object is no longer in the state, is a new object
    at that id (Core 124), or is off the board."""
    if effect.get("op") not in TRIGGER_EVENT_OBJECT_OPS:
        raise SelectionBindingRefused(
            f"op {effect.get('op')!r} has no reviewed adoption of the trigger's referent; each op needs its "
            f"own fixture (adopted: {sorted(TRIGGER_EVENT_OBJECT_OPS)})", OBJECT_REF_OP_NOT_ADOPTED)
    for field in ("target", "targets", "affected", "decision_ref"):
        if effect.get(field) is not None:
            raise SelectionBindingRefused(
                f"the instruction carries {field!r} beside the trigger's referent; 'it' names the object the "
                f"trigger event was about and chooses nothing", OBJECT_REF_NOT_SELF)
    event = program.get("trigger_event")
    if not isinstance(event, dict) or not isinstance(event.get("object"), str) or not isinstance(event.get("identity"), str):
        raise SelectionBindingRefused(
            "the program carries no trigger_event: 'it' names the object of the event that met a watched "
            "trigger's condition, which only that trigger's chain item records (resolution_bridge."
            "bind_trigger_event); it is never guessed", OBJECT_REF_NO_TRIGGER_EVENT)
    referent, bound = event["object"], event["identity"]
    if referent not in state["objects"]:
        raise SourceUnavailable(
            f"the trigger's referent {bound!r} is no longer in the state (a token that left the board ceased "
            f"to exist, Core 186.1); 'it' cannot be acted on", OBJECT_REF_REFERENT_ABSENT)
    now = object_identity(state, referent)
    obj = state["objects"][referent]
    if obj.get("kind") not in OBJECT_REF_PERMANENT_KINDS:
        raise SelectionBindingRefused(
            f"the trigger's referent is a {obj.get('kind')!r}, not a permanent; only a permanent is wired for "
            f"this reference", OBJECT_REF_REFERENT_LEFT_PLAY)
    if now != bound:
        raise SourceUnavailable(
            f"the trigger's referent was {bound!r} when its condition was met and is now {now!r}; the object "
            f"at that id is a new one (Core 124), not the one the trigger saw", OBJECT_REF_REFERENT_IDENTITY_CHANGED)
    if zone_class(find_location(state, referent)) != "board":
        raise SourceUnavailable(
            f"the trigger's referent {referent!r} is not on the board any more; the instruction cannot be "
            f"followed (Core 359.3.e.6)", OBJECT_REF_REFERENT_LEFT_PLAY)
    return ({**effect, "object_id": referent, "subject_identity": now},
            {"object_ref": TRIGGER_EVENT_OBJECT, "resolved_to": referent, "bound_identity": now,
             "trigger_event": event.get("event_id")})


def resolve_amount_ref(ref: dict[str, Any], state: dict[str, Any], program: dict[str, Any]) -> tuple[int, str]:
    """(amount, source) for `{"kind": "program_source_current_might"}`: the source's
    effective Might NOW, at execution (Core 359.3.f.2) - after any change made in
    response. Identity is mandatory; a source that is gone or is a new object is refused
    by name, never read off whatever holds that id now."""
    source = program.get("source_object")
    declared = program.get("source_identity")
    if not isinstance(source, str) or not source:
        raise SelectionBindingRefused(
            f"the program declares source_object {source!r}; 'my Might' with no source is refused, never guessed",
            AMOUNT_REF_ABSENT)
    if not isinstance(declared, str) or not declared:
        raise SelectionBindingRefused("the program declares no source_identity; 'my Might' requires one",
                                      AMOUNT_REF_ABSENT)
    # 2026-09-28 (review 5, R1-2): the source bound by identity and now gone - ceased to exist, or a
    # new object at its id - has no Might to read (Core 359.3.e.12): the Deal cannot be followed and
    # is ignored (359.3.e.6, SourceUnavailable); it is never read off whatever holds the id now
    if source not in state["objects"]:
        raise SourceUnavailable(
            f"the program's source {declared!r} is no longer in the state; 'my Might' reads null", AMOUNT_REF_ABSENT)
    if object_identity(state, source) != declared:
        raise SourceUnavailable(
            f"the program's source was {declared!r} and is now {object_identity(state, source)!r}; "
            f"'my Might' is not read off a different object", AMOUNT_REF_IDENTITY_CHANGED)
    return effective_might(state, source), source


def resolve_location_ref(ref: dict[str, Any], state: dict[str, Any], program: dict[str, Any]) -> str:
    """Turn `{"kind": "program_source_current_battlefield"}` into a concrete
    Battlefield id, read fresh from the state at INSTRUCTION EXECUTION (Core
    359.3.f.1, 359.3.f.2) - never bound earlier and reused. Raises
    SelectionBindingRefused with one of three named codes; nothing is
    substituted, exactly resolve_object_ref's contract for the same class of
    self-referential problem (a typed reference, never a magic string, that
    only the engine may create or resolve).

    Identity is MANDATORY, unlike resolve_object_ref's own `source_identity`
    (a recorded, still-open gap: optional there, so a program that omits it
    commits with no identity check at all). GPT 2026-09-23 requires this
    capability not repeat that gap: a program with no declared source_identity
    cannot resolve "here" at all, and one that declared it is refused the
    moment the object at that id is no longer that object - never resolved
    against whatever sits there now (Core 355.7's own principle - a reference
    does not silently retarget to a substitute)."""
    if ref.get("kind") == "trigger_event_destination":
        # package 11: a target reads this through _bind_location_ref (a Base destination too); found by criteria, only a
        # Battlefield destination is a place to look
        destination = program.get("noted_location")
        if not isinstance(destination, dict):
            raise SourceUnavailable("the trigger's instruction moved nothing; there is no destination", LOCATION_REF_NO_DESTINATION)
        if destination.get("kind") != "battlefield":
            raise SelectionBindingRefused(f"a Base destination ({destination}) is read by a target selector only",
                                          LOCATION_REF_NOT_AT_BATTLEFIELD)
        return destination["battlefield"]
    if ref.get("kind") == "program_source_noted_battlefield":
        # 2026-10-12 (package 11, GPT PACKAGE11 ruling 3): the Battlefield the death trigger's source was at as its
        # abilities were noted (Core 808.1.d.3), as its chain item recorded it; a source that died in a Base has no
        # battlefield - 'my battlefield' reads null (359.3.e.12) and nothing is chosen instead. A program with no
        # noted location is not a death trigger's, and is refused by name
        noted = program.get("noted_location")
        if not isinstance(noted, dict):
            raise SelectionBindingRefused(
                "'my battlefield' of a death trigger reads the location noted as it died; the program carries none",
                LOCATION_REF_ABSENT)
        if noted.get("kind") != "battlefield":
            raise SourceUnavailable(
                f"the source died at no battlefield ({noted}); 'my battlefield' reads null", LOCATION_REF_NOT_AT_BATTLEFIELD)
        if noted["battlefield"] not in (state.get("battlefields") or {}):
            raise SourceUnavailable(f"the noted battlefield {noted['battlefield']!r} is not in the game", LOCATION_REF_ABSENT)
        return noted["battlefield"]
    source = program.get("source_object")
    declared = program.get("source_identity")
    if isinstance(source, str) and source in (state.get("battlefields") or {}) and source not in state["objects"]:
        # 2026-10-08 package 10 (Navori Fighting Pit: "When you hold here, buff a unit here."): a Battlefield's own
        # ability - its "here" is that Battlefield itself (Core 190.6), bound by the Battlefield's identity
        if not isinstance(declared, str) or not declared:
            raise SelectionBindingRefused(
                f"the program declares no source_identity; 'here' requires one", LOCATION_REF_ABSENT)
        if battlefield_identity(state, source) != declared:
            raise SourceUnavailable(
                f"the program's source was {declared!r} and is now {battlefield_identity(state, source)!r}; 'here' is "
                f"not about whatever Battlefield now sits at that id", LOCATION_REF_IDENTITY_CHANGED)
        return source
    if not isinstance(source, str) or source not in state["objects"]:
        if isinstance(source, str) and source and isinstance(declared, str) and declared:
            # GPT 2026-09-27 ruling 10: a source bound by identity and gone (a token ceased to exist,
            # 186.1) has no location - 'here' reads null (359.3.e.12); the instruction is ignored
            raise SourceUnavailable(
                f"the program's source {declared!r} is no longer in the state; 'here' reads null", LOCATION_REF_ABSENT)
        raise SelectionBindingRefused(
            f"the program declares source_object {source!r}, which the state does not contain; "
            f"'here' with no source is refused, never guessed", LOCATION_REF_ABSENT)
    if not isinstance(declared, str) or not declared:
        raise SelectionBindingRefused(
            f"the program declares no source_identity; 'here' requires one, unlike "
            f"resolve_object_ref's own optional one", LOCATION_REF_ABSENT)
    now = object_identity(state, source)
    if declared != now:
        raise SourceUnavailable(
            f"the program's source was {declared!r} and is now {now!r}; 'here' is not about "
            f"whatever object now sits at that id", LOCATION_REF_IDENTITY_CHANGED)
    location = find_location(state, source)
    if location is None or location[0] != "battlefield":
        raise SourceUnavailable(
            f"the source {source!r} is not at a Battlefield right now ({location}); 'here' (Core "
            f"053.3) names a Battlefield specifically - Base or anywhere else the source could be "
            f"is not a Battlefield to mean (Core 359.3.f.2's own worked example)",
            LOCATION_REF_NOT_AT_BATTLEFIELD)
    return location[1]


def _bind_location_ref(selector: dict[str, Any], state: dict[str, Any], program: dict[str, Any]) -> dict[str, Any]:
    """Resolve a target's `location_ref` against the program's source NOW - at the
    moment the target is chosen, and again every time it is checked, so a source that
    has since moved makes the target illegal and the instruction mistargets (Core
    359.3.f.2) rather than following a Battlefield recorded earlier. The result is a
    Battlefield id in `location_battlefield`, or the named reason in
    `location_ref_refused`; neither is an authorable selector field."""
    if "location_ref" not in selector:
        return selector
    concrete = {k: v for k, v in selector.items() if k != "location_ref"}
    if selector["location_ref"].get("kind") == "trigger_event_destination":
        # package 11 (Dragon's Rage): "at its destination" - where the trigger's instruction moved its object, a
        # Battlefield or a Base, as the chain item recorded it; nothing moved: no object is at it (Core 402.4)
        destination = program.get("noted_location")
        if not isinstance(destination, dict):
            concrete["location_ref_refused"] = LOCATION_REF_NO_DESTINATION
        elif destination.get("kind") == "battlefield":
            concrete["location_battlefield"] = destination["battlefield"]
        else:
            concrete["location_base"] = destination["player"]
        return concrete
    try:
        concrete["location_battlefield"] = resolve_location_ref(selector["location_ref"], state, program)
    except SelectionBindingRefused as refusal:
        concrete["location_ref_refused"] = refusal.reason_code
    return concrete


def bind_program_context(selector: dict[str, Any], state: dict[str, Any], program: dict[str, Any]) -> dict[str, Any]:
    """Everything a selector reads from its own program: the source it excludes
    ("another"), and the source's current Battlefield ("here")."""
    return _bind_location_ref(_bind_referent_exclusion(_bind_source_exclusion(selector, state, program), program),
                              state, program)


def _bind_referent_exclusion(selector: dict[str, Any], program: dict[str, Any]) -> dict[str, Any]:
    """2026-10-12 (package 11, Dragon's Rage): "another enemy unit" than the one the trigger's event was about - bound to
    the identity the event recorded (resolution_bridge.bind_trigger_event). A program with no event cannot say which
    object is excluded: the target is illegal by name, never "any unit"."""
    if not selector.get("exclude_trigger_event_object"):
        return selector
    concrete = {k: v for k, v in selector.items() if k != "exclude_trigger_event_object"}
    event = program.get("trigger_event")
    if isinstance(event, dict) and isinstance(event.get("identity"), str):
        concrete["excluded_referent_identity"] = event["identity"]
    else:
        concrete["referent_exclusion_refused"] = OBJECT_REF_NO_TRIGGER_EVENT
    return concrete


def _bind_source_exclusion(selector: dict[str, Any], state: dict[str, Any], program: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$source_identity` to the identity the program's own source
    object has right now. A program that excludes its source without naming
    one is an authoring error, not a selector that excludes nothing."""
    if selector.get("exclude_source_identity") != SOURCE_IDENTITY_SENTINEL:
        return selector
    source = program.get("source_object")
    if not isinstance(source, str) or source not in state["objects"]:
        raise ValueError("exclude_source_identity needs the program's source_object to be a known object")
    return {**selector, "exclude_source_identity": object_identity(state, source)}


def _establish_selection(state: dict[str, Any], effect: dict[str, Any], program: dict[str, Any],
                         decisions: dict[str, Any] | None, order_index: int,
                         bindings: dict[str, Any]) -> dict[str, Any]:
    """selection-binding.v1: run "Choose a friendly unit." and record what the
    clauses after it are allowed to refer to.

    It changes no game state. What it produces is the binding: the selected
    objects with their identities, the hash of the candidate set AND the rule
    that selected them, the visibility, and the origin - which program and
    instruction made the choice. A supplied decision must carry that same
    binding, and a mismatch is refused by name instead of quietly reused.
    """
    import engine_decisions as ed
    import selection_binding as sb

    spec = effect["choice"]
    actual = {"selection_kind": spec.get("selection_kind"), "from": spec.get("from"),
              "count": spec.get("count", {"one": True} if spec.get("selection_kind") == "single" else None),
              "visibility": ed.choice_visibility(spec)}
    unwired = {key: value for key, value in actual.items()
               if (value not in SELECTION_SLICE[key] if isinstance(SELECTION_SLICE[key], set)
                   else value != SELECTION_SLICE[key])}
    if unwired or spec.get("by", "controller") != "controller":
        raise NotImplementedError(
            f"establish_selection wires a single, public choice of one object from the board "
            f"or from the Battlefields; {unwired or {'by': spec.get('by')}} is outside the "
            f"eff_010 slice (unsupported: selection_binding_slice)")

    selection_id = effect["selection_id"]
    effect_id = effect.get("effect_id", f"effect-{order_index}")
    program_id = program.get("program_id") or ""
    chooser = program.get("controller")
    candidates, identities = choice_candidates(state, spec, chooser, program=program)
    visibility = ed.choice_visibility(spec)

    chosen, meta = resolve_choice(state, spec, decision_ref=effect["decision_ref"],
                                  decisions=decisions, controller=chooser, candidates=candidates)
    if not chosen:
        # 359.3.e: nothing to choose from. No selection is established, so every
        # later reference to it is refused as unbound rather than left dangling.
        return {"op": "establish_selection", "outcome": "no_op", "completion": "none",
                "selection_id": selection_id, "rule_locators": OP_RULES["establish_selection"],
                "reason": "there is nothing to choose from; no selection is established (Core 359.3.e)",
                "selection": meta.get("choice")}

    if selection_id in bindings:
        raise SelectionBindingRefused(
            f"selection {selection_id!r} is already established; a later instruction must "
            f"reference its result, not make the selection a second time", sb.ALREADY_CONSUMED)

    claim = None
    if not meta.get("forced"):
        entry = ed.decision_entry(decisions, effect["decision_ref"]) or {}
        claim = entry.get("binding")
        if claim is None:
            raise SelectionBindingRefused(
                f"decision {effect['decision_ref']!r} establishes selection {selection_id!r} but "
                f"carries no binding; an unbound selection cannot be referred to later",
                sb.ORIGIN_UNBOUND)
        refusal, message = sb.check_claim(
            claim, spec=spec, candidates=candidates, identities=identities, visibility=visibility,
            program_id=program_id, effect_id=effect_id, selection_id=selection_id,
            established=set(bindings))
        if refusal is not None:
            raise SelectionBindingRefused(message, refusal)

    record = {
        "selection_id": selection_id,
        "selection_result_ref": sb.result_ref(selection_id),
        "value": list(chosen),
        "selection_identities": {object_id: identities.get(object_id) for object_id in chosen},
        "candidate_set_hash": sb.candidate_set_hash(spec, candidates, identities),
        "visibility": visibility,
        "origin": {"program_id": program_id, "effect_id": effect_id},
        "order_index": order_index,
        "decision_id": meta.get("decision_id"),
        "forced": bool(meta.get("forced")),
    }
    bindings[selection_id] = record
    return {"op": "establish_selection", "outcome": "applied", "completion": "full",
            "selection_id": selection_id, "objects": list(chosen),
            "rule_locators": OP_RULES["establish_selection"],
            "selection_binding": copy.deepcopy(record), "selection": meta.get("choice")}


def _resolve_selectors(state: dict[str, Any], effect: dict[str, Any], program: dict[str, Any], decisions: dict[str, Any] | None,
                       *, bindings: dict[str, Any] | None = None, order_index: int = 0,
                       counted_when_chosen: Any = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn `targets` (or a decision_ref on `target`) into concrete selectors,
    consuming a target_selection decision when the program defers to one.
    Returns (selectors, meta) where meta says which decision was used.

    `bindings` are the selections earlier instructions of this program have
    established (selection-binding.v1); `order_index` is this instruction's
    position, so a reference can only look backwards. `counted_when_chosen` names
    the target selections the resolution bridge took from the chain item's record -
    counted and checked where they were chosen (play, or the trigger's finalization).
    """
    import engine_decisions as ed  # local import keeps effect_ir importable on its own
    controller = program.get("controller")
    targets = effect.get("targets")
    template = {k: v for k, v in (targets or {}).get("restrictions", {}).items()} if targets else {}
    if targets is None:
        target = effect.get("target")
        # selection-binding.v1: a reference to a selection an earlier
        # instruction established. Reading it is NOT consuming it - "Buff it."
        # and "Kill it." both read the same immutable result.
        if target is not None and "selection_ref" in target:
            import selection_binding as sb
            bound, refusal, message = sb.check_reference(
                target["selection_ref"], bindings or {}, program_id=program.get("program_id") or "",
                order_index=order_index, referencing_visibility=target.get("visibility", "public"))
            if refusal is not None:
                raise SelectionBindingRefused(message, refusal)
            concrete = {k: v for k, v in target.items() if k not in {"selection_ref", "visibility"}}
            concrete["object_id"] = bound["value"][0]
            concrete.setdefault("bound_identity", bound["selection_identities"][concrete["object_id"]])
            return [bind_program_context(concrete, state, program)], {
                "selection_result_ref": bound["selection_result_ref"],
                "selection_id": target["selection_ref"],
                "decision_id": bound.get("decision_id")}
        if target is not None and "decision_ref" in target:
            entry = ed.target_selection(decisions, target["decision_ref"])
            if entry is None:
                raise TargetDecisionRequired(f"target selection {target['decision_ref']!r} is required", [target["decision_ref"]], controller)
            if entry["controller"] != controller:
                raise IllegalDecision(f"target selection {target['decision_ref']!r} was made by {entry['controller']!r}, not the program controller")
            if entry["stage"] not in {"play_declaration", "trigger_finalization"}:
                raise ValueError(f"target selection {target['decision_ref']!r} was supplied at the wrong stage")
            if len(entry["value"]) != 1:
                raise ValueError(f"target selection {target['decision_ref']!r} must name exactly one object for a single-target instruction")
            concrete = {k: v for k, v in target.items() if k != "decision_ref"}
            concrete["object_id"] = entry["value"][0]
            concrete.setdefault("bound_identity", entry["selection_identities"][concrete["object_id"]])
            if concrete.get("kind") == "battlefield":
                concrete.setdefault("chosen_zone_class", "board")
            return [bind_program_context(concrete, state, program)], {"decision_id": entry["decision_id"]}
        return ([bind_program_context(target, state, program)] if target is not None else []), {}
    if "selectors" in targets:
        return [bind_program_context(dict(sel), state, program) for sel in targets["selectors"]], {}
    entry = ed.target_selection(decisions, targets["decision_ref"])
    if entry is None:
        raise TargetDecisionRequired(f"target selection {targets['decision_ref']!r} is required", [targets["decision_ref"]], controller)
    if entry["controller"] != controller:
        raise IllegalDecision(f"target selection {targets['decision_ref']!r} was made by {entry['controller']!r}, not the program controller")
    if entry["stage"] not in {"play_declaration", "trigger_finalization"}:
        raise ValueError(f"target selection {targets['decision_ref']!r} was supplied at the wrong stage")
    chosen = list(entry["value"])
    if "max" in targets:
        cap = targets["max"]
    elif isinstance(targets.get("group"), dict) and "total_might_at_most" in targets["group"]:
        # package 10 (Fox-Fire): "any number" - the group's total bounds it, checked where it is chosen (355.11.a)
        cap = len(chosen)
    elif entry["decision_id"] in (counted_when_chosen or ()):
        # a split whose Targets were counted where they were chosen, against the damage available
        # then (355.14.c, 715.3); if the amount has shrunk since, 355.14.h settles it as it resolves
        cap = len(chosen)
    else:
        # a split: its damage, with the Bonus Damage its Deal would have, is the cap (355.14.c, 715.3)
        cap = split_target_cap(state, effect, controller, chosen)
    if not (targets["min"] <= len(chosen) <= cap):
        raise ValueError(f"target selection {targets['decision_ref']!r} chose {len(chosen)} objects; allowed {targets['min']}..{cap}")
    selectors = []
    for object_id in chosen:
        sel = dict(template)
        sel["object_id"] = object_id
        sel.setdefault("chosen_zone_class", zone_class(find_location(state, object_id)) or "non_board")
        sel.setdefault("bound_identity", entry["selection_identities"][object_id])
        selectors.append(bind_program_context(sel, state, program))
    return selectors, {"decision_id": entry["decision_id"]}


def split_division(state: dict[str, Any], effect: dict[str, Any], valid_sels: list[dict[str, Any]],
                   decisions: dict[str, Any] | None, controller: str | None) -> tuple[dict[str, int] | None, dict[str, Any] | None]:
    """Core 355.14.e-h: how the controller divides a split deal among the Targets still legal,
    decided as it resolves. (division, None), or (None, a refusal to return). The division names
    each legal Target it keeps with a positive amount (355.14.f, 355.14.g), all of the damage
    (the whole amount is dealt), and - when more Targets are legal than damage - exactly as many
    Targets as there is damage, the rest ceasing to be Targets (355.14.h, 355.14.h.1)."""
    import engine_decisions as ed
    ref, amount = effect["division_ref"], effect["amount"]
    legal = [sel["object_id"] for sel in valid_sels]
    keep = min(len(legal), amount)
    entry = next((e for e in ed.entries(decisions, kind="damage_division") if e.get("decision_id") == ref), None)
    if entry is None:
        return None, {"valid": True, "committed": False, "damage_division_required": True,
                      "reason_code": "damage_division_required",
                      "reason": f"how {amount} damage is divided among {legal} is decided as it resolves (Core 355.14.e)",
                      "decision_ids": [ref], "decision_controller": controller,
                      "division_candidates": legal, "division_amount": amount, "division_keeps": keep}
    if entry.get("controller") != controller:
        return None, {"valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch",
                      "reason": f"damage division {ref!r} was made by {entry.get('controller')!r}, not the program controller"}
    value = entry["value"]
    problems = []
    if set(value) - set(legal):
        problems.append(f"it names {sorted(set(value) - set(legal))}, which are not legal Targets now (359.3.e)")
    if len(value) != keep:
        problems.append(f"it keeps {len(value)} Targets; with {len(legal)} legal and {amount} damage it must keep {keep} "
                        f"(355.14.f, 355.14.h.1)")
    if sum(value.values()) != amount:
        problems.append(f"it divides {sum(value.values())}, not the {amount} damage (355.14.e)")
    identities = entry.get("selection_identities") or {}
    stale = sorted(o for o in value if o in legal and identities.get(o) != object_identity(state, o))
    if stale:
        problems.append(f"it was made for other objects than {stale} are now (Core 124)")
    if problems:
        return None, {"valid": False, "committed": False, "errors": [f"damage division {ref!r}: {p}" for p in problems]}
    return {o: value[o] for o in legal if o in value}, None


def nested_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """The context a program run INSIDE one instruction gets - a multi-target instruction's
    per-object application, a replacement's or augmentation's events. The facts of the moment
    carry over (the Combat in progress); the executions of the resolving card do not: a paid
    Repeat (820.1.d) and a mode chosen at play (402.2) belong to the outer program, which already
    runs one execution per Repeat. Passed down, each nested application ran once per Repeat
    again - "deal 1 to each of up to two units" with one Repeat dealt 4, not 2 (2026-09-28)."""
    if not context:
        return context
    return {k: v for k, v in context.items() if k not in {"repeat", "mode_selection"}} or None


def sb_module():
    """selection_binding, imported lazily so this module stays import-cycle free."""
    import selection_binding as sb
    return sb


def apply_program(state: dict[str, Any], program: dict[str, Any], *, decisions: dict[str, Any] | None = None, context: dict[str, Any] | None = None, _replacement_depth: int = 0, _applied_replacements: frozenset[str] = frozenset()) -> dict[str, Any]:
    """`context` carries facts only a procedure knows — today the Combat in
    progress ({"combat": {"combat_id", "battlefield"}}) that a 'this combat'
    grant binds to. The bridge supplies it; a bare effect run has none."""
    state_errors = validate_state(state)
    program_errors = validate_program(program)
    if decisions is not None:
        import engine_decisions as ed
        program_errors = program_errors + ed.validate_engine_decisions(decisions)
        if not program_errors and decisions.get("input_hash") != hash_value(state):
            program_errors = program_errors + ["engine_decisions.input_hash does not match the state being transitioned"]
    base = {
        "schema_version": "riftbound-effect-result.v1",
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "program_id": program.get("program_id") if isinstance(program, dict) else None,
        "input_state_hash": hash_value(state),
    }
    if state_errors or program_errors:
        return {**base, "valid": False, "committed": False, "errors": state_errors + program_errors, "trace": []}
    if _replacement_depth > 8:
        return {**base, "valid": True, "committed": False, "unsupported": True, "reason": "replacement recursion depth exceeded", "trace": []}
    # ADR-0013 §1: the legacy families are translated once, here, and the
    # working state is canonical from this point on. The input hash above was
    # taken over the caller's state, so envelopes still bind.
    current = migrate_legacy_effects(copy.deepcopy(state))
    trace = []
    # ADR-0014 §1: one snapshot per instruction, taken before it runs. Scalars
    # only, so a later in-place edit of the state cannot rewrite history; the
    # snapshot at position i+1 is the after-state of the entry at position i.
    import game_events
    snapshots: list[dict[str, Any]] = []
    outcomes: dict[str, str] = {}
    # selection-binding.v1: the selections this program has established, in the
    # order they were made. It is per-program and ephemeral: it is not state,
    # and a nested program is given only what it may legitimately read.
    selection_bindings: dict[str, Any] = {}
    # package 6: what this program's choose_objects put in each group ({"chosen", "offered"}), the
    # options its choose_option recorded ({record: {player: option}}), and which player each
    # each_player copy runs for (the player responsible for its game actions, Core 411.1). Per program
    # and ephemeral, like the selection bindings.
    chosen_groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    recorded_options: dict[str, dict[str, str]] = {}
    copy_players: dict[str, str] = {}
    # Selections an establish_selection in THIS program attempted and found
    # empty. A reference to one of these is a game event, not a bad artifact.
    empty_selections: set[str] = set()
    terminal: dict[str, Any] | None = None
    # package 9 (Nocturne - Horrifying): the cards banished as they were seen, offered a play once the effect is done
    seen_banished: list[dict[str, Any]] = []
    try:
        effects_to_run, mode, repeat_meta = _resolve_executions(program, decisions, context)
    except ModeSelectionRequired as exc:
        return {**base, "valid": True, "committed": False, "mode_selection_required": True, "reason_code": exc.reason_code, "reason": str(exc),
                "decision_ids": exc.decision_ids, "decision_controller": exc.controller, "mode_options": exc.options, "trace": []}
    except IllegalDecision as exc:
        return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch", "reason": str(exc), "trace": []}
    except ValueError as exc:
        return {**base, "valid": False, "committed": False, "errors": [str(exc)], "trace": []}
    for index, effect in enumerate(effects_to_run):
        before_hash = hash_value(current)
        snapshots.append(game_events.snapshot(current))
        effect_id = effect.get("effect_id", f"effect-{index}")
        if terminal is not None:
            # ADR-0010 §4: the game ended inside this program; nothing after runs.
            event = {"index": index, "effect_id": effect_id, "op": effect.get("op"), "outcome": "skipped_after_terminal", "completion": "none",
                     "rule_locators": ["Core 196"], "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        only = effect.get("only_if_chose")
        if only is not None:
            # package 9: the branch runs only if the controller chose it (recorded by an earlier choose_option)
            record = recorded_options.get(only["record"])
            if record is None:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "option_record_unbound",
                        "reason": f"no instruction of this program recorded the options {only['record']!r}",
                        "failed_effect_index": index, "trace": trace}
            if record.get(program.get("controller")) != only["option"]:
                event = {"index": index, "effect_id": effect_id, "op": effect.get("op"), "outcome": "skipped_option_not_chosen",
                         "completion": "none", "only_if_chose": dict(only), "rule_locators": ["Core 355.10.e"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
        predicate = effect.get("predicate")
        if predicate is not None:
            try:
                if predicate.get("kind") in ("target_state_holds", "predicate_not_met"):
                    holds, predicate_locators = _local_predicate(predicate, effect, current, decisions, trace)
                else:
                    source = program.get("source_object") if isinstance(program.get("source_object"), str) else None
                    # 2026-10-12 (package 11, Noxian Guillotine): "another card" read on a resolving spell is another than
                    # that spell (Core 812.1.c) - the chain item's card (resolution_bridge), for that condition only
                    if source is None and _names_another_card(predicate.get("condition")):
                        source = (context or {}).get("resolving_card")
                    holds, predicate_locators = evaluate_predicate(predicate, program.get("cost_receipt"), {e.get("effect_id"): e for e in trace}, current, program.get("controller"),
                                                                  source=source)
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
            if holds is None:
                return {
                    **base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                    "reason": f"predicate kind {predicate['kind']!r} is recognized but not implemented", "trace": trace,
                }
            if not holds:
                # package 10 (Solari Chief): an instruction whose condition on its own target did not hold was not
                # ignored - it had nothing to do (skipped_condition_not_met, outside IGNORED_OUTCOMES), so an "it" linked
                # to it still runs and its "Otherwise" reads predicate_result. Every other predicate's skip is as before
                event = {
                    "index": index, "effect_id": effect_id, "op": effect["op"],
                    "outcome": ("skipped_condition_not_met" if predicate.get("kind") == "target_state_holds"
                                else "skipped_linked_dependency"),
                    "predicate": copy.deepcopy(predicate), "predicate_result": False,
                    "completion": "none", "rule_locators": predicate_locators + ["Core 359.3.e.14"],
                    "before_state_hash": before_hash, "after_state_hash": before_hash,
                }
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
        dependency = effect.get("depends_on")
        linked_mode = effect.get("dependency_mode", "if_applied")
        if dependency is not None and ((linked_mode == "if_applied" and outcomes.get(dependency) != "applied")
                                       or (linked_mode == "unless_ignored" and (dependency not in outcomes
                                                                         or outcomes[dependency] in IGNORED_OUTCOMES))):
            event = {
                "index": index,
                "effect_id": effect_id,
                "op": effect["op"],
                "outcome": "skipped_linked_dependency",
                "depends_on": dependency,
                "rule_locators": ["Core 359.3.e.14"],
                "before_state_hash": before_hash,
                "after_state_hash": before_hash,
            }
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "trigger_base_cost":
            # Core 383.3.b.1 / 740.4.a.2: the base cost was paid as the ability was finalized, or
            # the ability never reached the Chain as a Finalized item (404.2). Resolution pays
            # nothing again: it reads the payment the chain item's receipt settled, and a program
            # run without that receipt - or with one for another cost - is refused, never paid here.
            payment = copy.deepcopy(effect.get("payment"))
            paid = (context or {}).get("trigger_base_cost_paid")
            if paid != hash_value(effect):
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "trigger_base_cost_unpaid",
                        "reason": "this program opens with a triggered ability's base cost, which is paid when the "
                                  "ability is finalized (Core 383.3.b.1, 740.4.a.2); no receipt for this cost came "
                                  "with the resolution" + (" (the receipt is for a different cost)" if paid else ""),
                        "failed_effect_index": index, "trace": trace}
            event = {"index": index, "effect_id": effect_id, "op": "trigger_base_cost", "outcome": "paid_at_finalization",
                     "completion": "full", "payment": payment, "cost_hash": paid,
                     "rule_locators": list(OP_RULES["trigger_base_cost"]),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        # 2026-09-27 package 6: "Each player ...". The instruction list runs once per player, in the
        # order the rules give (Core 303.2.a: Turn Order from the Turn Player; "Starting with the next
        # player": from the player after the controller), each copy with that player in place and
        # its own choices (355.10.e). The copies run next, as ordinary instructions.
        if effect.get("op") == "each_player":
            try:
                players = each_player_order(current, program, context, effect)
            except EachPlayerUnsupported as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True, "reason_code": exc.reason_code,
                        "reason": str(exc), "failed_effect_index": index, "trace": trace}
            only = effect.get("only_chose")
            if only is not None:
                # "For each player that chooses Cards": the players whose recorded option, made by an
                # earlier instruction of this program, is that option - in the same order
                record = recorded_options.get(only["record"])
                if record is None:
                    return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "option_record_unbound",
                            "reason": f"no instruction of this program recorded the options {only['record']!r}",
                            "failed_effect_index": index, "trace": trace}
                players = [p for p in players if record.get(p) == only["option"]]
            expanded = []
            for player in players:
                for copied in each_player_copies(effect, player):
                    copy_players[copied["effect_id"]] = player
                    expanded.append(copied)
            event = {"index": index, "effect_id": effect_id, "op": "each_player",
                     "outcome": "expanded" if expanded else "no_op", "completion": "full" if expanded else "none",
                     "players": list(players), "players_rule": effect.get("players"), "order_rule": effect.get("order"),
                     **({"only_chose": dict(only)} if only is not None else {}),
                     "expanded_into": [e["effect_id"] for e in expanded],
                     "rule_locators": list(dict.fromkeys(OP_RULES["each_player"] + ["Core 355.10.e"])),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            effects_to_run[index + 1:index + 1] = expanded
            continue
        if isinstance(effect.get("linked_each"), str):
            objects, linked_event = linked_objects(trace, effect["linked_each"])
            if linked_event is None or linked_event.get("outcome") in LINKED_IGNORED_OUTCOMES:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                         "completion": "none", "linked_effect_id": effect["linked_each"],
                         "reason": "the linked instruction was ignored, so this one is too",
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            sub_trace, working = [], current
            for object_id in objects or []:
                single = {k: v for k, v in effect.items() if k not in {"linked_each", "effect_id"}}
                single.update({"object_id": object_id, "effect_id": f"{effect_id}:{object_id}"})
                sub = apply_program(working, {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                                              "program_id": f"linked-each:{program['program_id']}:{effect_id}",
                                              "controller": program.get("controller"), "source_object": program.get("source_object"),
                                              "effects": [single]}, decisions=None, context=nested_context(context),
                                    _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    return {**base, "valid": sub.get("valid", True), "committed": False, "failed_effect_index": index,
                            "reason": sub.get("reason") or "; ".join(sub.get("errors") or []), "expansion_result": sub, "trace": trace}
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") == "applied")
            event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "applied" if applied else "no_op",
                     "completion": "full" if objects and applied == len(objects) else ("partial" if applied else "none"),
                     "linked_effect_id": effect["linked_each"], "objects": list(objects or []), "expansion_trace": sub_trace,
                     "pending_triggers": group_pending_triggers(sub_trace, current),
                     "rule_locators": ["Core 359.3.e.14"], "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "pay_any_amount":
            import engine_decisions as ed
            payer = program.get("controller")
            pay = next((e for e in ed.entries(decisions, kind="optional_choice") if e.get("decision_id") == effect["pay_ref"]), None)
            if pay is None:
                return {**base, "valid": True, "committed": False, "optional_choice_required": True,
                        "reason_code": "optional_choice_required",
                        "reason": f"{payer} decides as it resolves whether to pay any amount at all (Core 204.3.b)",
                        "decision_ids": [effect["pay_ref"]], "decision_controller": payer,
                        "failed_effect_index": index, "trace": trace}
            if pay["controller"] != payer or pay["stage"] != "resolution":
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch",
                        "reason": f"{effect['pay_ref']!r} is {payer}'s, made as it resolves", "failed_effect_index": index,
                        "trace": trace}
            if pay["value"] is False:
                event = {"index": index, "effect_id": effect_id, "op": "pay_any_amount", "outcome": "declined",
                         "completion": "none", "decision_id": effect["pay_ref"], "paid_total": None,
                         "rule_locators": ["Core 204.3.b"], "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            allocation = next((e for e in ed.entries(decisions, kind="resource_allocation")
                               if e.get("decision_id") == effect["decision_ref"]), None)
            if allocation is None:
                return {**base, "valid": True, "committed": False, "resource_allocation_required": True,
                        "reason_code": "resource_allocation_required",
                        "reason": f"{payer} names how much Power of which Domains to pay ({{}} pays 0)",
                        "decision_ids": [effect["decision_ref"]], "decision_controller": payer,
                        "failed_effect_index": index, "trace": trace}
            pool = current["players"][payer]["resources"]["power"]
            spend = allocation["value"]
            if allocation["controller"] != payer or allocation["stage"] != "resolution" \
                    or any(pool.get(d, 0) < n for d, n in spend.items()):
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation",
                        "reason": f"{payer} cannot pay {spend} from {pool} as it resolves", "failed_effect_index": index,
                        "trace": trace}
            current = copy.deepcopy(current)
            for domain, n in spend.items():
                current["players"][payer]["resources"]["power"][domain] -= n
            paid = sum(spend.values())
            event = {"index": index, "effect_id": effect_id, "op": "pay_any_amount", "outcome": "applied",
                     "completion": "full", "player": payer, "paid": dict(spend), "paid_total": paid,
                     "decision_id": effect["decision_ref"], "rule_locators": list(OP_RULES["pay_any_amount"]),
                     "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "choose_option":
            # "Each other player chooses Cards or Runes.": the player names one option as the
            # instruction resolves; the program records it for "for each player that chooses ..."
            import engine_decisions as ed
            chooser = effect.get("by")
            if chooser == "controller":
                chooser = program.get("controller")
            ref = effect.get("decision_ref")
            entry = ed.option_selection(decisions, ref)
            if chooser not in current["players"]:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [f"choose_option by {chooser!r}, who is not a player"], "trace": trace}
            if entry is None:
                return {**base, "valid": True, "committed": False, "option_selection_required": True,
                        "reason_code": "option_selection_required",
                        "reason": f"{chooser} chooses one of {effect.get('options')} as the instruction resolves",
                        "decision_ids": [ref], "decision_controller": chooser, "options": list(effect.get("options") or []),
                        "failed_effect_index": index, "trace": trace}
            if entry["controller"] != chooser:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch",
                        "reason": f"option {ref!r} was chosen by {entry['controller']!r}, not {chooser!r}",
                        "failed_effect_index": index, "trace": trace}
            if entry["value"] not in (effect.get("options") or []):
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation",
                        "reason": f"option {ref!r} names {entry['value']!r}, not one of {effect.get('options')}",
                        "failed_effect_index": index, "trace": trace}
            recorded_options.setdefault(effect["record"], {})[chooser] = entry["value"]
            event = {"index": index, "effect_id": effect_id, "op": "choose_option", "outcome": "applied", "completion": "full",
                     "player": chooser, "option": entry["value"], "options": list(effect["options"]), "record": effect["record"],
                     "decision_id": ref, "rule_locators": list(OP_RULES["choose_option"]),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "choose_objects":
            # "Each player chooses 2 units ..." / "chooses a unit you don't control that hasn't been
            # chosen for this spell": objects chosen as the instruction resolves by the player it
            # names - not targets (Core 355.10.e) - into a group of this program. Changes no state.
            import engine_decisions as ed
            spec = effect["choice"]
            chooser = spec.get("by", "controller")
            if chooser == "controller":
                chooser = program.get("controller")
            if chooser not in current["players"]:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                        "reason": f"choose_objects by {spec.get('by')!r}: the chooser is not a player here", "trace": trace}
            group = chosen_groups.setdefault(effect["group"], {"chosen": [], "offered": []})
            try:
                candidates, identities = choice_candidates(current, spec, chooser, program=program)
            except SelectionBindingRefused as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": exc.reason_code,
                        "reason": str(exc), "failed_effect_index": index, "trace": trace}
            if effect.get("distinct_in_group"):
                taken = {(m["object_id"], m["identity"]) for m in group["chosen"]}
                candidates = [c for c in candidates if (c, identities.get(c)) not in taken]
            try:
                chosen, meta = resolve_choice(current, spec, decision_ref=effect["decision_ref"], decisions=decisions,
                                              controller=program.get("controller"), chooser=chooser, candidates=candidates,
                                              execution=execution_suffix(effect))
                entry = ed.decision_entry(decisions, effect["decision_ref"]) if not meta.get("forced") else None
                if entry is not None and entry.get("stage") != "resolution":
                    raise ValueError(f"decision {effect['decision_ref']!r} is made as the instruction resolves "
                                     f"(Core 355.10.e), not at {entry.get('stage')!r}")
            except ChoiceRequired as exc:
                return {**base, "valid": True, "committed": False, "choice_required": True,
                        f"{exc.summary['decision_kind']}_required": True, "reason_code": exc.reason_code,
                        "reason": str(exc), "choice": exc.summary, "decision_ids": exc.decision_ids,
                        "decision_controller": exc.controller, "failed_effect_index": index, "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch",
                        "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except IllegalOperation as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation",
                        "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except NotImplementedError as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                        "reason": str(exc), "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
            for object_id in candidates:
                group["offered"].append({"object_id": object_id, "identity": identities.get(object_id),
                                         "chosen_by": chooser, "effect_id": effect_id})
            for object_id in chosen:
                group["chosen"].append({"object_id": object_id, "identity": identities.get(object_id),
                                        "chosen_by": chooser, "effect_id": effect_id})
            private = ed.choice_visibility(spec) != "public"
            event = {"index": index, "effect_id": effect_id, "op": "choose_objects",
                     "outcome": "applied" if chosen else "no_op", "completion": "full" if chosen else "none",
                     "player": chooser, "group": effect["group"], "chosen_count": len(chosen), "offered_count": len(candidates),
                     **({"objects_hash": _ids_hash(current, list(chosen)), "objects_visible_to": [chooser]} if private
                        else {"chosen_objects": list(chosen)}),
                     "selection": {k: v for k, v in meta.items() if k != "choice"},
                     "rule_locators": list(OP_RULES["choose_objects"]),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            if not chosen:
                event["reason"] = "there was nothing to choose from (Core 359.3.e)"
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        # 2026-09-27: "its controller" / "its owner" (Core 359.3.e.14). The player is read off
        # the object the linked earlier instruction acted on, as that object stood just before
        # the instruction executed (its snapshot); an ignored earlier instruction makes this
        # one ignored as well (359.3.e.14.a), a replaced one does not (359.3.e.14.b).
        linked_reads: dict[str, Any] = {}
        if is_object_player(effect.get("player")):
            spec = effect["player"]["object_player"]
            objects, linked = linked_objects(trace, spec["effect_id"])
            if objects is None or len(objects) != 1:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"],
                         "outcome": "skipped_linked_dependency", "completion": "none",
                         "linked_effect_id": spec["effect_id"],
                         "reason": ("the linked instruction was ignored, so this one is too" if objects is None
                                    else "the linked instruction acted on more than one object; 'its' names one"),
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            at = linked.get("index")
            record = (snapshots[at].get(objects[0]) or {}) if isinstance(at, int) and 0 <= at < len(snapshots) else {}
            player_id = record.get(spec["relation"])
            if player_id not in current["players"]:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                        "reason": f"the {spec['relation']} of {objects[0]!r} as the linked instruction found it is not "
                                  f"observed; 'its {spec['relation']}' is not guessed", "trace": trace}
            effect = {**effect, "player": player_id}
            linked_reads["player_read"] = {"relation": spec["relation"], "object_id": objects[0],
                                           "linked_effect_id": spec["effect_id"], "player": player_id,
                                           "read_as": "before_the_linked_instruction",
                                           "bound_identity": record.get("identity"),
                                           "rule_locators": ["Core 359.3.e.14", "Core 355.10.d"]}
        # 2026-09-27 package 6: "for each buff spent" - the count an earlier instruction's receipt says
        if isinstance(effect.get("count_per"), dict) and effect["count_per"].get("kind") == "linked_applied_count":
            linked_id = effect["count_per"]["effect_id"]
            linked_event = next((e for e in trace if e.get("effect_id") == linked_id), None)
            if linked_event is None or linked_event.get("outcome") in IGNORED_OUTCOMES:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                         "completion": "none", "linked_effect_id": linked_id,
                         "reason": "the instruction whose count this one reads was ignored",
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            found = int(linked_event.get("applied_count") or 0)
            if found < 1:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "linked_count_zero", "linked_effect_id": linked_id,
                         "rule_locators": ["Core 359.3.e.14"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            per = dict(effect["count_per"])
            effect = {**{k: v for k, v in effect.items() if k != "count_per"}, "count": effect["count"] * found}
            linked_reads["count_read"] = {"per": per, "linked_count": found, "printed_count": effect["count"] // found,
                                          "rule_locators": ["Core 359.3.e.14"]}
        # 2026-10-12 package 11 (Teemo - Strategist): "for each card with [Hidden] revealed this way"
        if isinstance(effect.get("count_per"), dict) and effect["count_per"].get("kind") == LINKED_REVEALED_COUNT:
            spec = effect["count_per"]
            shown = next((e for e in trace if e.get("effect_id") == spec["effect_id"] and e.get("op") == "reveal"), None)
            if shown is None or shown.get("outcome") in IGNORED_OUTCOMES:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                         "completion": "none", "linked_effect_id": spec["effect_id"],
                         "reason": "the reveal whose cards this counts did not happen",
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            counted = [r["object_id"] for r in shown.get("revealed") or []
                       if r.get("object_id") in current["objects"]
                       and object_identity(current, r["object_id"]) == r.get("identity")
                       # a card with [Hidden] is one with the keyword (Core 811), as `with_hidden` reads it
                       and current["objects"][r["object_id"]].get(spec["keyword"]) is True]
            if not counted:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "linked_count_zero", "linked_effect_id": spec["effect_id"],
                         "counted": [], "rule_locators": ["Core 359.3.e.14"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            printed = effect["amount"]
            effect = {**{k: v for k, v in effect.items() if k != "count_per"}, "amount": printed * len(counted)}
            linked_reads["count_read"] = {"per": dict(spec), "counted": counted, "printed_amount": printed,
                                          "rule_locators": ["Core 359.3.e.14"]}
        # 2026-09-27: "draw 1 for each of your [Mighty] units" - the count read now (708, 710)
        if effect.get("count_per") is not None:
            found, counted = count_per_value(current, effect["count_per"], program.get("controller"))
            if found < 1:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "count_per_zero", "counted": [],
                         "rule_locators": ["Core 708", "Core 710"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            per = dict(effect["count_per"])
            effect = {**{k: v for k, v in effect.items() if k != "count_per"}, "count": effect["count"] * found}
            linked_reads["count_read"] = {"per": per, "counted": counted, "printed_count": effect["count"] // found,
                                          "rule_locators": ["Core 708", "Core 710"]}
        # "You may kill up to one gear.": an instruction the card leaves to its controller.
        # Its targets were chosen as the card was played, whatever the controller will decide
        # (Core 355.12); whether to perform it is decided now, as it resolves - an optional_choice
        # decision at the resolution stage, by the program's controller. Declined, it is not
        # performed and changes nothing; the instructions after it run as they would.
        optional = effect.get("optional")
        if optional is not None:
            import engine_decisions as ed
            ref = optional["decision_ref"]
            # package 6: "each player may ..." - the player of the iteration decides (optional.by)
            decider = optional.get("by") or program.get("controller")
            entry = next((e for e in ed.entries(decisions, kind="optional_choice") if e.get("decision_id") == ref), None)
            if entry is None:
                return {**base, "valid": True, "committed": False, "optional_choice_required": True,
                        "reason_code": "optional_choice_required",
                        "reason": f"instruction {effect_id!r} is optional; its controller decides as it resolves (Core 355.12)",
                        "decision_ids": [ref], "decision_controller": decider,
                        "failed_effect_index": index, "trace": trace}
            if entry["controller"] != decider:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "decision_controller_mismatch",
                        "reason": f"optional instruction {effect_id!r} was decided by {entry['controller']!r}, not {decider!r}",
                        "failed_effect_index": index, "trace": trace}
            if entry["stage"] != "resolution":
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [f"optional instruction {effect_id!r} is decided as it resolves; the decision was "
                                   f"supplied for stage {entry['stage']!r}"], "trace": trace}
            if entry["value"] is False:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "declined",
                         "completion": "none", "decision_id": ref, "rule_locators": ["Core 355.12"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
        # selector-group `self`: resolve a typed program_source reference into
        # the concrete object before anything else looks at object_id.
        if is_object_ref(effect.get("object_id")):
            try:
                effect, object_ref_meta = resolve_object_ref(effect, current, program)
            except SourceUnavailable as exc:
                # "me" is gone: the instruction cannot be followed and is ignored; the rest of the
                # ability resolves (Core 359.3.e.6), and an instruction linked to this one is
                # ignored with it (359.3.e.14.a, IGNORED_OUTCOMES)
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": SOURCE_UNAVAILABLE_OUTCOME,
                         "completion": "none", "reason": exc.reason_code, "message": str(exc),
                         "source_object": program.get("source_object"), "rule_locators": list(SOURCE_UNAVAILABLE_RULES),
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            except SelectionBindingRefused as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": exc.reason_code, "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
        else:
            object_ref_meta = {}
        # selection-binding.v1: "Choose a friendly unit." on its own. It runs
        # before selector resolution because it has no selectors of its own -
        # it produces the binding the instructions after it refer to.
        if effect.get("op") == "establish_selection":
            try:
                event = _establish_selection(current, effect, program, decisions, index, selection_bindings)
            except ChoiceRequired as exc:
                return {
                    **base, "valid": True, "committed": False, "choice_required": True,
                    f"{exc.summary['decision_kind']}_required": True,
                    "reason_code": exc.reason_code, "reason": str(exc), "choice": exc.summary,
                    "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                    "failed_effect_index": index, "trace": trace,
                }
            except SelectionBindingRefused as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": exc.reason_code, "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "decision_controller_mismatch", "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            except IllegalOperation as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "illegal_operation", "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            except NotImplementedError as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True,
                        "failed_effect_index": index, "reason": str(exc), "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [str(exc)], "trace": trace}
            event = {"index": index, "effect_id": effect_id, **event,
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            # 359.3.e: the choice had nothing to choose from. That is a game
            # event, not a malformed program, and the instructions that refer
            # to this selection have to be ignored one by one rather than
            # taking the whole card down with them (359.3.e.6, 359.3.e.10).
            if event.get("outcome") == "no_op" and event.get("selection_id"):
                empty_selections.add(event["selection_id"])
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        # ADR-0005 §1–3: resolve selectors (possibly from a decision), then either
        # run the legacy single-target path unchanged or expand a multi-target
        # instruction into per-object applications with a typed instruction outcome.
        try:
            selectors, selector_meta = _resolve_selectors(current, effect, program, decisions,
                                                          bindings=selection_bindings, order_index=index,
                                                          counted_when_chosen=(context or {}).get("targets_counted_when_chosen"))
        except SelectionBindingRefused as exc:
            # Narrow, and only here: the selection this instruction refers to is
            # one THIS program tried to establish and could not, because there
            # was nothing to choose from (359.3.e). Then 359.3.e.6 ignores this
            # instruction and 359.3.e.10 lets the rest of the card run. Every
            # other unbound reference - an artifact naming another program,
            # another effect, a candidate set taken under a different rule - is
            # still refused whole, because a lying artifact is not a game event.
            referenced = (effect.get("target") or {}).get("selection_ref")
            if exc.reason_code == sb_module().ORIGIN_UNBOUND and referenced in empty_selections:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"],
                         "outcome": "ignored_illegal_target",
                         "target_outcome": "skipped_illegal_target", "completion": "none",
                         "selection_id": referenced,
                         "reason": f"the selection {referenced!r} was never established - there "
                                   f"was nothing to choose from - so this instruction is "
                                   f"ignored (359.3.e, 359.3.e.6)",
                         "rule_locators": ["Core 359.3.e", "Core 359.3.e.6", "Core 359.3.e.10"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": exc.reason_code, "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
            }
        except TargetDecisionRequired as exc:
            return {
                **base, "valid": True, "committed": False, "target_decision_required": True,
                "reason_code": "target_selection_required", "reason": str(exc),
                "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                "failed_effect_index": index, "trace": trace,
            }
        except IllegalDecision as exc:
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": "decision_controller_mismatch", "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
            }
        except ValueError as exc:
            return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
        if effect.get("op") == "grant_keyword" and context is not None and context.get("combat") is not None:
            effect = {**effect, "combat_context": context["combat"]}
        # 2026-09-27 package 6 (Core 359.3.e.16): whether this turn's Ending Step has begun - only a
        # procedure knows; a delayed trigger "at the end of this turn" is then not generated
        if effect.get("op") == "create_delayed_trigger" and context is not None and context.get("ending_step_begun") is not None:
            effect = {**effect, "ending_step_context": context["ending_step_begun"]}
        # GPT 2026-10-02: the chain item whose resolution makes the delayed trigger - its instance in the id
        if effect.get("op") == "create_delayed_trigger" and context is not None and context.get("creating_chain_item"):
            effect = {**effect, "instance_context": context["creating_chain_item"]}
        if effect.get("op") in {"discard", "spend_buffs"} or (effect.get("choice") is not None and effect.get("op") in CHOICE_OPS | RESOLUTION_CHOICE_OPS):
            try:
                effect = (_resolve_discard(current, effect, decisions, program) if effect.get("op") == "discard"
                          else _resolve_spend_buffs(current, effect, decisions) if effect.get("op") == "spend_buffs"
                          else _resolve_choice_object(current, effect, program, decisions))
                if effect.get("op") in RESOLUTION_CHOICE_OPS:
                    # package 6: an object chosen as the instruction resolves (Core 355.10.e) is chosen
                    # then - a decision made for another stage is not that choice
                    import engine_decisions as ed
                    meta = effect.get("selection_meta") or {}
                    entry = ed.decision_entry(decisions, meta["decision_id"]) if meta.get("decision_id") else None
                    if entry is not None and entry.get("stage") != "resolution":
                        raise ValueError(f"decision {meta['decision_id']!r} is made as the instruction resolves "
                                         f"(Core 355.10.e), not at {entry.get('stage')!r}")
            except ChoiceRequired as exc:
                # ADR-0011 §1: the summary lists options only for a public source.
                return {
                    **base, "valid": True, "committed": False, "choice_required": True, f"{exc.summary['decision_kind']}_required": True,
                    "reason_code": exc.reason_code, "reason": str(exc), "choice": exc.summary,
                    "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                    "failed_effect_index": index, "trace": trace,
                }
            except NotImplementedError as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index, "reason": str(exc), "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch", "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except IllegalOperation as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation", "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
        if effect.get("op") in RESOLUTION_CHOICE_OPS and effect.get("choice") is not None and effect.get("object_id") is None:
            # package 6: nothing to choose from (a player with no unit): the instruction does nothing
            # for that player (Core 359.3.e), and the rest of the program runs
            event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op", "completion": "none",
                     "reason": "nothing to choose from (Core 359.3.e)", "selection": effect.get("selection_meta"),
                     "rule_locators": ["Core 359.3.e", "Core 355.10.e"],
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "recycle" and effect.get("revealed_by") is not None:
            # package 11: "the revealed cards" - what that reveal showed, each still the object it was (Core 124)
            shown = next((e for e in trace if e.get("effect_id") == effect["revealed_by"] and e.get("op") == "reveal"), None)
            if shown is None or shown.get("outcome") in IGNORED_OUTCOMES:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                         "completion": "none", "linked_effect_id": effect["revealed_by"],
                         "reason": "the reveal whose cards this recycles did not happen",
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            still = [r["object_id"] for r in shown.get("revealed") or []
                     if r.get("object_id") in current["objects"] and object_identity(current, r["object_id"]) == r.get("identity")]
            effect = {**{k: v for k, v in effect.items() if k != "revealed_by"}, "objects": still}
            if not still:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "none of the revealed cards is still that card",
                         "rule_locators": ["Core 124"], "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
        if effect.get("op") == "recycle" and effect.get("rest_of") is not None:
            # package 6: "Recycle the rest." - what the group's choices were offered and did not take,
            # each still the object it was when offered (Core 124: a card that changed zones since is
            # a new object, and not "the rest" any more)
            group = chosen_groups.get(effect["rest_of"])
            if group is None:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "group_unbound",
                        "reason": f"no instruction of this program chose into group {effect['rest_of']!r}",
                        "failed_effect_index": index, "trace": trace}
            kept = {(m["object_id"], m["identity"]) for m in group["chosen"]}
            rest: list[str] = []
            for offered in group["offered"]:
                object_id = offered["object_id"]
                if (object_id, offered["identity"]) in kept or object_id in rest:
                    continue
                if object_id in current["objects"] and object_identity(current, object_id) == offered["identity"]:
                    rest.append(object_id)
            effect = {**effect, "objects": rest}
        if effect.get("group_ref") is not None and effect.get("op") in GROUP_OPS:
            # package 6: "Kill those units." - every object the group holds, each still the object that
            # was chosen and still on the board; not targets (Core 355.10.e), so nothing is re-checked
            # beyond being the same object (Core 124). One instruction over the set.
            group = chosen_groups.get(effect["group_ref"])
            if group is None:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "group_unbound",
                        "reason": f"no instruction of this program chose into group {effect['group_ref']!r}",
                        "failed_effect_index": index, "trace": trace}
            members, gone = [], []
            for member in group["chosen"]:
                object_id = member["object_id"]
                if object_id in members:
                    continue            # chosen twice (a group that allows it): it is one object, acted on once
                if object_id in current["objects"] and object_identity(current, object_id) == member["identity"] \
                        and zone_class(find_location(current, object_id)) == "board":
                    members.append(object_id)
                else:
                    gone.append({"object_id": object_id, "reason": "no longer the chosen object on the board (Core 124)"})
            sub_trace, working, failure = [], current, None
            for object_id in members:
                single = {k: v for k, v in effect.items() if k not in {"group_ref", "effect_id"}}
                single["object_id"] = object_id
                single["effect_id"] = f"{effect_id}:{object_id}"
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"group:{program['program_id']}:{effect_id}", "controller": program.get("controller"),
                               "source_object": program.get("source_object"), "effects": [single]}
                sub = apply_program(working, sub_program, decisions=None, context=nested_context(context),
                                    _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    failure = sub
                    break
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            if failure is not None:
                return {**base, "valid": failure.get("valid", True), "committed": False,
                        "unsupported": failure.get("unsupported", False),
                        "replacement_decision_required": failure.get("replacement_decision_required", False),
                        "replacement_ids": failure.get("replacement_ids", []), "failed_effect_index": index,
                        "reason": failure.get("reason", "; ".join(failure.get("errors", [])) or "group expansion failed"),
                        "expansion_result": failure, "trace": trace}
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in PERFORMED_OUTCOMES)
            event = {"index": index, "effect_id": effect_id, "op": effect["op"],
                     "outcome": "applied" if applied else "no_op",
                     "completion": "full" if members and applied == len(members) else ("partial" if applied else "none"),
                     "group": effect["group_ref"], "affected_objects": members, "not_in_play": gone,
                     "affected_are_targets": False, "expansion_trace": sub_trace,
                     "pending_triggers": group_pending_triggers(sub_trace, current),
                     "rule_locators": list(dict.fromkeys(["Core 355.10.e", "Core 124"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                     "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "raise_might_to_match":
            # package 9 (Convergent Mutation, GPT 2026-10-06 ruling 7): both Units revalidated, both Mights read once,
            # now; the first raised by the difference this turn when the second's is higher - an ordinary modify_might,
            # so replacements see it - and nothing when it is not (an increase only, 370.1.a). One illegal Unit skips
            # the whole instruction: the increase relates to both (359.3.e.5)
            try:
                pair = []
                for selector in effect["units"]:
                    resolved, _meta = _resolve_selectors(current, {"target": selector}, program, decisions)
                    pair.append(resolved[0])
            except TargetDecisionRequired as exc:
                return {**base, "valid": True, "committed": False, "target_decision_required": True,
                        "reason_code": "target_selection_required", "reason": str(exc),
                        "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                        "failed_effect_index": index, "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "decision_controller_mismatch", "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [str(exc)], "trace": trace}
            verdicts = [(sel, *evaluate_target(current, sel, program.get("controller"))) for sel in pair]
            ids = [sel["object_id"] for sel, _, _ in verdicts]
            invalid = [{"object_id": sel["object_id"], "reason": reason} for sel, ok, reason in verdicts if not ok]
            if ids[0] == ids[1] and not invalid:
                invalid = [{"object_id": ids[0], "reason": "same_unit_twice"}]
            if invalid:
                event = {"index": index, "effect_id": effect_id, "op": "raise_might_to_match",
                         "outcome": "ignored_illegal_target", "target_outcome": "skipped_illegal_target",
                         "completion": "none", "units": ids, "invalid_targets": invalid,
                         "reason": "a Unit of the pair is not a legal referent; the increase relates to both (359.3.e.5)",
                         "rule_locators": ["Core 359.3.e.1–359.3.e.5"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            snapshot = {object_id: effective_might(current, object_id) for object_id in ids}
            delta = max(0, snapshot[ids[1]] - snapshot[ids[0]])
            expanded = [{"op": "modify_might", "effect_id": f"{effect_id}:raise", "object_id": ids[0], "amount": delta,
                         "duration": "this_turn", "source": effect.get("source") or effect_id,
                         CHOSEN_FIELD: effect.get(CHOSEN_FIELD, True), "raise_of": effect_id}]
            event = {"index": index, "effect_id": effect_id, "op": "raise_might_to_match",
                     "outcome": "expanded" if delta else "no_op", "completion": "full" if delta else "none",
                     "units": ids, "might_before": snapshot, "delta": delta,
                     "expanded_into": [child["effect_id"] for child in expanded] if delta else [],
                     "reason": None if delta else "its Might is already at least the other's; an increase only (370.1.a)",
                     "rule_locators": list(OP_RULES["raise_might_to_match"]),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            if delta:
                effects_to_run[index + 1:index + 1] = expanded
            continue
        if effect.get("op") == "swap_might":
            # Core 477 with Riot's reading: read both Mights BEFORE either moves,
            # then run the two changes as ordinary modify_might events. Because
            # they are ordinary, each passes the replacement machinery on its own
            # - which is what lets "if a spell would give me -Might" see the
            # decrease - and because the amounts come from one snapshot, the
            # second is not computed from a Might the first already changed.
            try:
                pair = []
                for selector in effect["units"]:
                    resolved, _meta = _resolve_selectors(current, {"target": selector}, program, decisions)
                    pair.append(resolved[0])
            except TargetDecisionRequired as exc:
                return {**base, "valid": True, "committed": False, "target_decision_required": True,
                        "reason_code": "target_selection_required", "reason": str(exc),
                        "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                        "failed_effect_index": index, "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "decision_controller_mismatch", "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [str(exc)], "trace": trace}
            verdicts = [(sel, *evaluate_target(current, sel, program.get("controller"))) for sel in pair]
            ids = [sel["object_id"] for sel, _, _ in verdicts]
            invalid = [{"object_id": sel["object_id"], "reason": reason} for sel, ok, reason in verdicts if not ok]
            if ids[0] == ids[1] and not invalid:
                invalid = [{"object_id": ids[0], "reason": "same_unit_twice"}]
            if invalid:
                event = {"index": index, "effect_id": effect_id, "op": "swap_might",
                         "outcome": "ignored_illegal_target", "target_outcome": "skipped_illegal_target",
                         "completion": "none", "units": ids, "invalid_targets": invalid,
                         "reason": "a Unit of the pair is not a legal referent; the swap relates to both (359.3.e.5)",
                         "rule_locators": ["Core 359.3.e.1–359.3.e.5"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            snapshot = {object_id: effective_might(current, object_id) for object_id in ids}
            delta = snapshot[ids[1]] - snapshot[ids[0]]
            duration = effect.get("duration", "this_turn")
            source = effect.get("source") or effect_id
            expanded = [
                {"op": "modify_might", "effect_id": f"{effect_id}:a", "object_id": ids[0],
                 "amount": delta, "duration": duration, "source": source,
                 CHOSEN_FIELD: effect.get(CHOSEN_FIELD, True), "swap_of": effect_id},
                {"op": "modify_might", "effect_id": f"{effect_id}:b", "object_id": ids[1],
                 "amount": -delta, "duration": duration, "source": source,
                 CHOSEN_FIELD: effect.get(CHOSEN_FIELD, True), "swap_of": effect_id},
            ]
            event = {"index": index, "effect_id": effect_id, "op": "swap_might",
                     "outcome": "expanded" if delta else "no_op",
                     "completion": "full" if delta else "none",
                     "units": ids, "might_before": snapshot, "delta": delta,
                     "expanded_into": [child["effect_id"] for child in expanded],
                     "reason": None if delta else "both Units already have the same Might, so nothing changes (370.1.a)",
                     "rule_locators": list(OP_RULES["swap_might"]),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            if delta:
                effects_to_run[index + 1:index + 1] = expanded
            continue
        if effect.get("op") == "mutual_damage_current_might":
            # ADR-0008 §7 (Gentlemen's Duel): both Units are revalidated, both
            # rules-facing Mights are read before either Deal, then the two Deal
            # events happen as one simultaneous action with the Units as sources
            # (417.6.b.3); one illegal Unit skips the whole pair (each Deal
            # relates to both). Never Combat Damage, never sequential reads.
            pair = []
            source_meta = {}
            try:
                for position, selector in enumerate(effect["units"]):
                    if is_object_ref(selector.get("object_id")):
                        # the source's slot (OBJECT_REF_UNIT_SLOT_OPS): resolved now, not chosen; gone - left the board or a
                        # new object - its Might and the object to deal to cannot be read, so neither Deal of the pair
                        # happens (Core 359.3.e.6, 359.3.e.12); it was never a target, so not an illegal one
                        _, source_meta = resolve_object_ref({"op": effect["op"], "object_id": selector["object_id"]}, current, program)
                        selector = {**{k: v for k, v in selector.items() if k != "object_id"}, "object_id": source_meta["resolved_to"]}
                    resolved, meta = _resolve_selectors(current, {"target": selector}, program, decisions)
                    pair.append((resolved[0], meta))
            except SourceUnavailable as exc:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": SOURCE_UNAVAILABLE_OUTCOME,
                         "completion": "none", "reason": exc.reason_code, "message": str(exc),
                         "source_object": program.get("source_object"),
                         "rule_locators": list(SOURCE_UNAVAILABLE_RULES) + ["Core 359.3.e.12"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            except SelectionBindingRefused as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": exc.reason_code, "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            except TargetDecisionRequired as exc:
                return {**base, "valid": True, "committed": False, "target_decision_required": True, "reason_code": "target_selection_required", "reason": str(exc),
                        "decision_ids": exc.decision_ids, "decision_controller": exc.controller, "failed_effect_index": index, "trace": trace}
            except IllegalDecision as exc:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch", "reason": str(exc), "failed_effect_index": index, "trace": trace}
            except ValueError as exc:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": [str(exc)], "trace": trace}
            verdicts = [(sel, *evaluate_target(current, sel, program.get("controller"))) for sel, _ in pair]
            ids = [sel["object_id"] for sel, _, _ in verdicts]
            invalid = [{"object_id": sel["object_id"], "reason": reason} for sel, ok, reason in verdicts if not ok]
            if ids[0] == ids[1] and not invalid:
                invalid = [{"object_id": ids[0], "reason": "same_unit_twice"}]
            if invalid:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "ignored_illegal_target", "target_outcome": "skipped_illegal_target",
                         "completion": "none", "units": ids, "invalid_targets": invalid, "reason": "a Unit of the pair is not a legal referent; both Deals relate to it (359.3.e.5)",
                         "rule_locators": ["Core 359.3.e.1–359.3.e.5", "Core 359.3.e.14"], "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            snapshot = {object_id: effective_might(current, object_id) for object_id in ids}
            # One simultaneous Deal batch (417.1.d): every replacement's
            # applicability is read from the same pre-Deal state, and only
            # Prevent values that belong to exactly one of the two events are
            # applied; anything else (other modes, optional descriptors, one
            # descriptor over both events) is outside the bounded batch and is
            # refused rather than resolved one Deal after the other.
            plans = []
            seen_descriptors: set[str] = set()
            batch_problem = None
            for source, receiver in ((ids[0], ids[1]), (ids[1], ids[0])):
                amount = snapshot[source]
                applicable = _applicable_replacements(current, {"op": "deal_damage", "object_id": receiver, "amount": amount}) if amount >= 1 else []
                for descriptor in applicable:
                    if descriptor["mode"] != "reduce_damage" or descriptor.get("optional"):
                        batch_problem = f"replacement {descriptor['replacement_id']} on {receiver} is not a mandatory Prevent value; the simultaneous Deal batch cannot apply it"
                    elif descriptor["replacement_id"] in seen_descriptors:
                        batch_problem = f"replacement {descriptor['replacement_id']} applies to both Deals of the pair; one descriptor over two simultaneous events is outside the bounded batch"
                    seen_descriptors.add(descriptor["replacement_id"])
                plans.append((source, receiver, amount, applicable))
            if batch_problem is not None:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index, "reason": batch_problem, "trace": trace}
            working = copy.deepcopy(current)
            sub_trace = []
            for source, receiver, amount, applicable in plans:
                sub_id = f"{effect_id}:{source}->{receiver}"
                responsible = working["objects"][source]["controller"]
                if amount < 1:
                    sub_trace.append({"op": "deal_damage", "effect_id": sub_id, "object_id": receiver, "source_object": source, "source_kind": "unit", "responsible_player": responsible,
                                      "amount": amount, "outcome": "no_op", "completion": "none", "reason": "no valid damage: the source's Might reads as 0 (417.1.e, 143.2.b)",
                                      "rule_locators": ["Core 417.1.e", "Core 143.2.b"]})
                    continue
                remaining, prevented, consumed = amount, 0, []
                for descriptor in applicable:
                    stored = next(r for r in working["replacement_effects"] if r["replacement_id"] == descriptor["replacement_id"])
                    take = min(remaining, stored.get("prevent_remaining", 0))
                    if take > 0:
                        stored["prevent_remaining"] -= take
                        remaining -= take
                        prevented += take
                        consumed.append({"replacement_id": descriptor["replacement_id"], "prevented": take})
                before = working["objects"][receiver]["damage"]
                working["objects"][receiver]["damage"] = before + remaining
                outcome = "applied" if not applicable else ("replaced_modified_applied" if remaining > 0 else "replaced_prevented")
                sub_trace.append({"op": "deal_damage", "effect_id": sub_id, "object_id": receiver, "source_object": source, "source_kind": "unit", "responsible_player": responsible,
                                  "amount": amount, "prevented": prevented, "applied": remaining, "before": before, "after": before + remaining, "outcome": outcome,
                                  "completion": "full" if remaining > 0 else "none", "consumed_replacements": consumed,
                                  "rule_locators": ["Core 417.1.b", "Core 417.1.d", "Core 417.6.b.3", "Core 417.6.b.4"] + (["Core 437.1–437.4"] if applicable else [])})
            working["replacement_effects"] = [r for r in working["replacement_effects"] if not (r.get("mode") == "reduce_damage" and r.get("prevent_remaining", 0) <= 0)]
            if found := validate_state(working):
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": found, "trace": trace}
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in PERFORMED_OUTCOMES)
            event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "applied" if applied else "no_op",
                     "completion": "full" if applied == 2 else ("partial" if applied else "none"), "units": ids, "might_snapshot": snapshot,
                     "simultaneous": True, "batch": "one_pre_deal_state_prevent_only", "not_combat_damage": True, "sources": {ids[0]: ids[1], ids[1]: ids[0]}, "expansion_trace": sub_trace,
                     "pending_triggers": group_pending_triggers(sub_trace, current),
                     "rule_locators": list(dict.fromkeys(OP_RULES["mutual_damage_current_might"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                     "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            for _, meta in pair:
                event.update(meta)
            if source_meta:
                event["source_slot"] = source_meta
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "make_new_choices":
            # 2026-10-13 package 11 (Mystic Reversal, GPT ruling 13; Core 751-755), moved to the 10-09 text by package 12:
            # its new controller remakes every one of the spell's targets, Move destinations and mode, each legal now for
            # the new controller (753.1) - the same one again allowed (753); costs a new choice would incur are ignored
            # (755). The spell's own program comes from the caller (context chain_programs), checked against the Chain
            # item's program id
            import engine_decisions as ed
            got = next((e for e in trace if e.get("effect_id") == effect["linked"]["effect_id"]), {})
            item_id, chooser = got.get("chain_item_id"), got.get("controller_after")
            entry = (current.get("chain_items") or {}).get(item_id) if item_id else None
            base_event = {"index": index, "effect_id": effect_id, "op": "make_new_choices", "chain_item_id": item_id,
                          "player": chooser, "rule_locators": list(OP_RULES["make_new_choices"]),
                          "before_state_hash": before_hash, "after_state_hash": before_hash}
            if entry is None or got.get("outcome") not in {"applied", None}:
                event = {**base_event, "outcome": "skipped_linked_dependency", "completion": "none",
                         "reason": "no spell changed control"}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            # ("You may": the instruction's own optional decision, asked of its controller before it runs - the program's
            # controller is the player who took the spell)
            # Core 2026-10-09 (in effect 10-16), 753-755: having chosen to make new choices, the player remakes EVERY choice
            # of the Chain item - the same one again is allowed (753); with no legal set of new choices the instruction is
            # negated (753.2); the item's restrictions bind the new choices too (753.3: a card played from facedown still
            # chooses at that battlefield). The 07-16 text (751.1) asked for choices not made before, and for any subset
            asked = [d for kind in ("target_selection", "location_selection", "option_selection")
                     for d in ed.entries(decisions, kind=kind) if str(d.get("decision_id", "")).startswith("new:")]
            spell = ((context or {}).get("chain_programs") or {}).get(item_id)
            if not isinstance(spell, dict) or spell.get("program_id") != entry.get("effect_program_id"):
                return {**base, "valid": True, "committed": False, "unsupported": True,
                        "reason_code": "new_choices_program_unknown",
                        "reason": f"the program of {item_id!r} ({entry.get('effect_program_id')!r}) is not supplied, so its "
                                  f"choices cannot be checked (Core 753.1)", "failed_effect_index": index, "trace": trace}
            if not asked:
                if not _new_choices_possible(current, spell, entry, chooser):
                    event = {**base_event, "outcome": "no_op", "completion": "none", "negated": True,
                             "reason": "no_legal_new_choices", "rule_locators": base_event["rule_locators"] + ["Core 753.2"]}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                required = sorted(_new_choice_refs(spell, entry))
                return {**base, "valid": True, "committed": False, "reason_code": "new_choices_required",
                        "reason": f"{chooser} chose to make new choices; every choice of {item_id!r} is remade (Core 753)",
                        "decision_ids": [f"new:{r}" for r in required], "decision_controller": chooser,
                        "failed_effect_index": index, "trace": trace}
            current = copy.deepcopy(current)
            entry = current["chain_items"][item_id]
            played = [dict(p) for p in entry.get("played_targets") or []]
            hidden_at = entry.get("played_from_hidden") if entry.get("hidden_targeting", "restricted") == "restricted" else None
            remade, problem, remade_refs = [], None, set()
            # the mode (752.1)
            modal = spell.get("modal")
            option_effects = list(spell.get("effects") or [])
            if modal:
                ref = modal["decision_ref"]
                now = (entry.get("mode_selection") or {}).get("option_id")
                new_mode = next((e for e in ed.entries(decisions, kind="option_selection") if e.get("decision_id") == f"new:{ref}"), None)
                if new_mode is not None:
                    options = {o["option_id"]: o for o in modal["options"]}
                    if new_mode.get("controller") != chooser or new_mode.get("value") not in options:
                        problem = f"the new mode {new_mode.get('value')!r} is not one of the spell's modes chosen by {chooser}"
                    else:
                        entry["mode_selection"] = {"decision_id": ref, "option_id": new_mode["value"]}
                        remade.append({"mode": new_mode["value"], "was": now})
                        remade_refs.add(ref)
                        now = new_mode["value"]
                option_effects = list(next((o["effects"] for o in modal["options"] if o["option_id"] == now), []))
            selectors = {}
            for e in option_effects:
                for field in ("target", "targets"):
                    if isinstance(e.get(field), dict) and isinstance(e[field].get("decision_ref"), str):
                        selectors[e[field]["decision_ref"]] = (e[field], e)
            destinations = {e["destination"]["decision_ref"]: e for e in option_effects
                            if isinstance(e.get("destination"), dict) and isinstance(e["destination"].get("decision_ref"), str)}
            # targets (752.1): legal for the new controller now - the same one again allowed (753)
            for d in ed.entries(decisions, kind="target_selection"):
                if problem or not str(d.get("decision_id", "")).startswith("new:"):
                    continue
                ref = d["decision_id"][4:]
                if ref not in selectors or d.get("controller") != chooser or d.get("stage") != "resolution":
                    problem = f"{ref!r} is not one of the spell's target choices, remade by {chooser} as this resolves"
                    break
                values = list(d.get("value") or [])
                if not values:
                    problem = f"no new choice given for {ref!r}"
                    break
                selector = {k: v for k, v in selectors[ref][0].items() if k != "decision_ref"}
                for v in values:
                    legal, why = _new_target_legal(current, selector, v, chooser, hidden_at)
                    if not legal:
                        problem = f"{v!r} is not a legal new choice for {ref!r} ({why}; Core 753.1, 753.3)"
                        break
                if problem:
                    break
                remade_refs.add(ref)
                record = {"decision_id": ref, "stage": "play_declaration", "kind": "target_selection", "controller": chooser,
                          "value": values, "selection_identities": {v: object_identity(current, v) for v in values}}
                was = next((p.get("value") for p in played if p.get("decision_id") == ref), None)
                played = [p for p in played if p.get("decision_id") != ref] + [record]
                remade.append({"target": ref, "was": was, "now": values})
            # Move destinations (752.1): a legal one - the same one again allowed (753)
            for d in ed.entries(decisions, kind="location_selection"):
                if problem or not str(d.get("decision_id", "")).startswith("new:"):
                    continue
                ref = d["decision_id"][4:]
                old = next((p for p in played if p.get("decision_id") == ref and p.get("kind") == "location_selection"), None)
                move = destinations.get(ref)
                moved_ref = ((move or {}).get("target") or {}).get("decision_ref")
                moved = next((p["value"][0] for p in played if p.get("decision_id") == moved_ref and p.get("value")), None)
                offered = move_destination_candidates(current, moved, move["destination"]) if move and moved else []
                if move is None or d.get("controller") != chooser or d.get("value") not in offered:
                    problem = f"the new destination {d.get('value')!r} is not a legal one for {ref!r} (Core 753.1)"
                    break
                played = [p for p in played if p.get("decision_id") != ref] + [
                    {"decision_id": ref, "stage": "play_declaration", "kind": "location_selection", "controller": chooser,
                     "value": d["value"]}]
                remade.append({"destination": ref, "was": (old or {}).get("value"), "now": d["value"]})
                remade_refs.add(ref)
            if problem:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "new_choice_illegal",
                        "reason": problem, "failed_effect_index": index, "trace": trace}
            # every choice remade (753): the mode, each target and each destination of the mode now chosen
            required = ({modal["decision_ref"]} if modal else set()) | set(selectors) | set(destinations)
            if required - remade_refs:
                missing = sorted(required - remade_refs)
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "new_choices_incomplete",
                        "reason": f"every choice of {item_id!r} is remade, the same one again allowed (Core 753); "
                                  f"not remade: {missing}",
                        "decision_ids": [f"new:{r}" for r in missing], "decision_controller": chooser,
                        "failed_effect_index": index, "trace": trace}
            if played:
                entry["played_targets"] = played
            else:
                entry.pop("played_targets", None)   # a mode with no target choices (validate_state wants none, not [])
            event = {**base_event, "outcome": "applied" if remade else "no_op", "completion": "full" if remade else "none",
                     "remade": remade, "costs_incurred_ignored": True, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "activate_conquer_effects":
            # 2026-10-13 package 11 (Reckoner's Arena, GPT ruling 15; Core 383.4.g.1): for each unit at the Battlefield -
            # of either side - each of its conquer effects is checked as if its conquer part were fulfilled: its own
            # "When I conquer" and a "When you conquer" it carries (383.4.c.2.b, the player being its controller); any
            # other part of its condition is read now, with that Battlefield as "there"; met, it becomes a Pending item just
            # as a fresh trigger does, controlled by the unit's controller. A conquer effect working from another zone, or
            # of anything that is not a unit there, is not one of these
            try:
                at = resolve_location_ref(effect["location_ref"], current, program)
            except (SourceUnavailable, SelectionBindingRefused) as exc:
                at = None
                why = str(exc)
            battlefield = (at or {}).get("battlefield") if isinstance(at, dict) else at
            activated, skipped = [], []
            if battlefield in current.get("battlefields", {}):
                for unit_id in list(current["battlefields"][battlefield]["objects"]):
                    obj = current["objects"].get(unit_id) or {}
                    if obj.get("kind") != "unit":
                        continue
                    for descriptor in obj.get("conquer_triggers") or []:
                        if descriptor.get("functions_from"):
                            continue
                        condition = descriptor.get("condition")
                        if condition is not None and not evaluate_condition(current, condition, controller=obj["controller"],
                                                                            object_id=battlefield):
                            skipped.append({"unit": unit_id, "trigger_id": descriptor.get("trigger_id"),
                                            "why": "the rest of its condition is not met"})
                            continue
                        copied = {k: v for k, v in descriptor.items() if k not in ("scope", "condition")}
                        copied.update({"controller": obj["controller"], "source_object": unit_id,
                                       "trigger_kind": "triggered", "batch_id": f"activate:{battlefield}:{effect_id}",
                                       "batch_sequence": 0, "scored_battlefield": battlefield, "how": "conquer",
                                       "scope": descriptor.get("scope", "unit_here"), "activated_by": effect_id,
                                       "source_identity": object_identity(current, unit_id) or f"{unit_id}@0"})
                        activated.append(copied)
            event = {"index": index, "effect_id": effect_id, "op": "activate_conquer_effects",
                     "outcome": "applied" if activated else "no_op", "completion": "full" if activated else "none",
                     "battlefield": battlefield, "activated": [(d["source_object"], d["trigger_id"]) for d in activated],
                     "not_activated": skipped, "pending_triggers": activated,
                     **({} if battlefield else {"reason": "no_battlefield_here"}),
                     "rule_locators": list(OP_RULES["activate_conquer_effects"]),
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "take_additional_turn":
            # 2026-10-13 package 11 (Time Warp, Core 735-738): an Additional Turn owned by the player, inserted after
            # the current turn - ahead of any queued before it (738: each is inserted after the current turn), the Turn
            # Order unchanged (737). The turn transition (turn_cycle.begin_turn) takes it
            player = program.get("controller") if effect.get("player") == "$controller" else effect.get("player")
            if player not in current["players"]:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [f"take_additional_turn: unknown player {player!r}"], "trace": trace}
            current = copy.deepcopy(current)
            made = {"player": player, "created_by": str(program.get("program_id")), "effect_id": effect_id,
                    "turn_id": current.get("turn_id", DEFAULT_TURN_ID)}
            current["additional_turns"] = [made] + list(current.get("additional_turns") or [])
            event = {"index": index, "effect_id": effect_id, "op": "take_additional_turn", "outcome": "applied",
                     "completion": "full", "player": player, "queued": [q["player"] for q in current["additional_turns"]],
                     "rule_locators": list(OP_RULES["take_additional_turn"]),
                     "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "banish_this":
            # 2026-10-13 package 11 (Time Warp): the resolving card's own instruction - it leaves the Chain for its
            # owner's banishment instead of the trash (Core 157, 427.1); the resolution bridge moves it once its
            # instructions are done. Not resolving from the Chain (context resolving_chain_item): nothing to banish
            item = (context or {}).get("resolving_chain_item")
            entry = (current.get("chain_items") or {}).get(item) if item else None
            if not entry or not entry.get("card"):
                event = {"index": index, "effect_id": effect_id, "op": "banish_this", "outcome": "no_op", "completion": "none",
                         "reason": "not_a_resolving_card", "player": program.get("controller"),
                         "rule_locators": list(OP_RULES["banish_this"]), "before_state_hash": before_hash,
                         "after_state_hash": before_hash}
            else:
                current = copy.deepcopy(current)
                current["chain_items"][item]["leave_replacement"] = {
                    "kind": "banish", "created_by": str(program.get("program_id")), "effect_id": effect_id}
                event = {"index": index, "effect_id": effect_id, "op": "banish_this", "outcome": "applied", "completion": "full",
                         "chain_item_id": item, "card": entry["card"], "player": program.get("controller"),
                         "replacement_id": f"leave:{item}", "rule_locators": list(OP_RULES["banish_this"]),
                         "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "recycle_when_leaving_chain":
            # package 9 (Kai'Sa - Evolutionary, GPT 2026-10-04 ruling 2): the card the linked play put on the Chain is
            # recycled instead of leaving it other than by its own instructions, once it is Finalized (Core 390.3.a)
            started = next((e for e in reversed(trace) if e.get("effect_id") == effect["linked"]["effect_id"]
                            and e.get("op") == "limited_play" and e.get("outcome") == "applied"), None)
            item = (started or {}).get("chain_item_id")
            if item is None or item not in (current.get("chain_items") or {}):
                event = {"index": index, "effect_id": effect_id, "op": "recycle_when_leaving_chain", "outcome": "no_op",
                         "completion": "none", "reason": "nothing_played", "player": program.get("controller"),
                         "rule_locators": ["Core 390.3.a", "Core 419.3.c"], "before_state_hash": before_hash,
                         "after_state_hash": before_hash}
            else:
                current = copy.deepcopy(current)
                current["chain_items"][item]["leave_replacement"] = {
                    "kind": "recycle", "created_by": str(program.get("program_id")), "effect_id": effect_id}
                event = {"index": index, "effect_id": effect_id, "op": "recycle_when_leaving_chain", "outcome": "applied",
                         "completion": "full", "chain_item_id": item, "card": current["chain_items"][item].get("card"),
                         "player": program.get("controller"), "replacement_id": f"leave:{item}",
                         "rule_locators": list(OP_RULES["recycle_when_leaving_chain"]),
                         "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("op") == "limited_play":
            # 2026-09-28 (package 6, Core 419.3): an effect-driven play. Its card was chosen as a target
            # when the effect was played or finalized (GPT 2026-09-25). No longer a legal target - it
            # left the zone, or left and came back as a new object (Core 359.3.e.2, 359.3.e.4) - the
            # instruction is ignored and nothing is played (359.3.e.6, 419.3.c). Legal, this is the
            # play's step 1 (Core 354): the card moves to the Chain as a Pending item and is a new
            # object (124); the rest of the play waits until this effect has finished resolving (354.3).
            if effect.get("self") is not None:
                # 2026-10-04 (package 8): "play me" from the zone the triggered ability works from (Immortal
                # Phoenix, Flame Chompers). The card is the program's own source as the chain item recorded it
                # (bind_source_identity): gone from that zone, or back as a new object (Core 124), it is no longer
                # the "me" the ability is about, and nothing is played (359.3.e.6, 419.3.c) - never another card
                source = program.get("source_object")
                declared = program.get("source_identity")
                source_obj = current["objects"].get(source) if isinstance(source, str) else None
                owner = (source_obj or {}).get("owner")
                in_zone = (source_obj is not None and owner in current["players"]
                           and source in current["players"][owner]["zones"].get(effect["self"]["from"], []))
                same = not declared or object_identity(current, source) == declared
                if not (in_zone and same):
                    event = {"index": index, "effect_id": effect_id, "op": "limited_play", "outcome": "no_op",
                             "completion": "none",
                             "reason": "source_not_in_zone" if not in_zone else "source_identity_changed",
                             "source_object": source, "rule_locators": ["Core 124", "Core 359.3.e.6", "Core 419.3.c"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                target = {"object_id": source}
                legal, reason = True, "ok"
            elif effect.get("linked") is not None:
                # 2026-10-04 (package 8, group 3): the card the named earlier banish moved - exactly one, still the object
                # it became in its owner's Banishment (Core 124, 427). Nothing banished, or the card moved on since:
                # nothing is played (419.3.c, 359.3.e.6); the instruction never picks another card
                ref = effect["linked"]["effect_id"]
                if effect["linked"].get("per_player"):
                    # package 11 (Promising Future): this iteration's player's own banish (its each_player copy)
                    ref = f"{ref}@{effect.get(EACH_PLAYER_FIELD)}"
                source_event = next((e for e in trace if e.get("effect_id") == ref), None)
                if source_event is None or source_event.get("op") not in LIMITED_PLAY_LINKED_OPS:
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index, "trace": trace,
                            "errors": [f"effects[{index}].limited_play linked names {ref!r}, which is not an earlier "
                                       f"{sorted(LIMITED_PLAY_LINKED_OPS)} instruction of this program"]}
                moved = [o for o in source_event.get("objects") or [] if o in (source_event.get("identities_after") or {})]
                card = moved[0] if len(moved) == 1 else None
                card_obj = current["objects"].get(card) if card else None
                owner = (card_obj or {}).get("owner")
                here = (card_obj is not None and owner in current["players"]
                        and card in current["players"][owner]["zones"].get("banishment", [])
                        and object_identity(current, card) == source_event["identities_after"][card])
                if not here:
                    event = {"index": index, "effect_id": effect_id, "op": "limited_play", "outcome": "no_op",
                             "completion": "none",
                             "reason": ("nothing_banished" if not moved else "more_than_one_banished" if len(moved) > 1
                                        else "linked_card_moved"),
                             "linked": dict(effect["linked"]), "rule_locators": ["Core 419.3.c", "Core 359.3.e.6", "Core 124"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                target = {"object_id": card}
                legal, reason = True, "ok"
            elif effect.get("choice") is not None:
                # 2026-09-28 (package 6, step 2): a card of the controller's hand, chosen now (Core 355.10.a) - or
                # none: a player cannot be made to take a card of a named quality from a hidden zone (128.6)
                controller = program.get("controller")
                criteria = effect.get("card_filter") or {}
                candidates = [c for c in current["players"][controller]["zones"][effect["choice"]["from"]]
                              if (current["objects"].get(c) or {}).get("kind") in LIMITED_PLAY_KINDS
                              and ("kind" not in criteria or current["objects"][c]["kind"] == criteria["kind"])
                              and (not criteria.get("hidden") or current["objects"][c].get("hidden") is True)]
                try:
                    chosen, choice_meta = resolve_choice(current, effect["choice"], decision_ref=effect.get("decision_ref"),
                                                         decisions=decisions, controller=controller, candidates=candidates,
                                                         execution=execution_suffix(effect))
                except ChoiceRequired as exc:
                    return {**base, "valid": True, "committed": False, "choice_required": True,
                            f"{exc.summary['decision_kind']}_required": True, "reason_code": exc.reason_code,
                            "reason": str(exc), "choice": exc.summary, "decision_ids": exc.decision_ids,
                            "decision_controller": exc.controller, "failed_effect_index": index, "trace": trace}
                except IllegalDecision as exc:
                    return {**base, "valid": True, "committed": False, "applied": False,
                            "reason_code": "decision_controller_mismatch", "reason": str(exc),
                            "failed_effect_index": index, "trace": trace}
                except IllegalOperation as exc:
                    return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation",
                            "reason": str(exc), "failed_effect_index": index, "trace": trace}
                except ValueError as exc:
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                            "errors": [str(exc)], "trace": trace}
                if not chosen:
                    event = {"index": index, "effect_id": effect_id, "op": "limited_play", "outcome": "no_op",
                             "completion": "none",
                             "reason": "no_eligible_card" if not candidates else "declined",
                             "rule_locators": ["Core 419.3.c"] if not candidates else ["Core 128.6"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                target = {"object_id": chosen[0]}
                legal, reason = True, "ok"
                selector_meta = {**selector_meta, "choice": choice_meta.get("choice"),
                                 **({"decision_id": choice_meta["decision_id"]} if choice_meta.get("decision_id") else {})}
            else:
                target = selectors[0] if selectors else None
                legal, reason = (evaluate_target(current, target, program.get("controller")) if target is not None
                                 else (False, "target_missing"))
            if legal and (current["objects"].get(target["object_id"]) or {}).get("kind") not in LIMITED_PLAY_KINDS:
                legal, reason = False, "target_not_a_playable_card"
            if not legal:
                event = {"index": index, "effect_id": effect_id, "op": "limited_play", "outcome": "ignored_illegal_target",
                         "target_outcome": "skipped_illegal_target", "completion": "none", "reason": reason,
                         "target_object_id": (target or {}).get("object_id"),
                         "rule_locators": ["Core 359.3.e.2", "Core 359.3.e.4", "Core 359.3.e.6", "Core 419.3.c"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash, **selector_meta}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            try:
                current, event = _start_limited_play(current, effect.get("cost_basis"), target, program, effect_id,
                                                     entry=effect.get("entry"), player=effect.get("player"))
            except NotImplementedError as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                        "reason": str(exc), "trace": trace}
            event.update({"index": index, "effect_id": effect_id, "before_state_hash": before_hash,
                          "after_state_hash": hash_value(current), **selector_meta})
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("affected") is not None:
            # ADR-0007 §4: two layers. The Battlefield (if any) is the target and is
            # revalidated; the units are found by criteria now and are NOT targets —
            # no 355.9 revalidation, no Deflect, no untargetability (355.10.b, 355.10.d).
            criteria = effect["affected"]["criteria"]
            battlefield_ids: list[str] = []
            targeted_battlefield = None
            active_combat = None
            if criteria.get("location_ref") is not None:
                # GPT 2026-09-23: "here" - the resolving program's own source's
                # current Battlefield, read fresh right now (Core 359.3.f.1,
                # 359.3.f.2), never bound earlier and reused.
                try:
                    battlefield_ids = [resolve_location_ref(criteria["location_ref"], current, program)]
                except SourceUnavailable as exc:
                    # GPT 2026-09-27 ruling 10: the source is gone or not at a Battlefield, so "here"
                    # reads null (359.3.e.12) - THIS instruction cannot be followed and is ignored
                    # (359.3.e.6), with any instruction linked to it (359.3.e.14.a); the rest of the
                    # ability resolves. Not a refusal of the whole resolution: a paid trigger would
                    # otherwise stay on the Chain.
                    event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": SOURCE_UNAVAILABLE_OUTCOME,
                             "completion": "none", "reason": exc.reason_code, "message": str(exc),
                             "source_object": program.get("source_object"),
                             "rule_locators": list(SOURCE_UNAVAILABLE_RULES) + ["Core 359.3.e.12"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                except SelectionBindingRefused as exc:
                    return {**base, "valid": True, "committed": False, "applied": False,
                            "reason_code": exc.reason_code, "reason": str(exc),
                            "failed_effect_index": index, "trace": trace}
            elif criteria["location"] == "active_combat":
                # ADR-0008 §7 (Cannon Barrage): Units at the Combat Battlefield that
                # carry that Combat's designation (740.2.c). No Combat in progress
                # is an empty set — a supported no-op; a claimed Combat whose
                # Battlefield or identity the state cannot confirm is unsupported.
                active_combat = (context or {}).get("combat")
                if active_combat is not None:
                    combat_battlefield = active_combat.get("battlefield")
                    if combat_battlefield not in current["battlefields"] or (active_combat.get("battlefield_identity") is not None and battlefield_identity(current, combat_battlefield) != active_combat["battlefield_identity"]):
                        return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                                "reason": f"the Combat context names Battlefield {combat_battlefield!r}, which the state cannot confirm; 'in combat' is not inferred", "trace": trace}
                    battlefield_ids = [combat_battlefield]
            elif criteria["location"] == "target_battlefield":
                sel = selectors[0]
                legal, reason = evaluate_target(current, sel, program.get("controller"))
                targeted_battlefield = sel["object_id"]
                if not legal:
                    event = {
                        "index": index, "effect_id": effect_id, "op": effect["op"],
                        "outcome": "skipped_illegal_target", "target_outcome": "skipped_illegal_target", "completion": "none",
                        "targeted_battlefield": targeted_battlefield, "target_reason": reason, "affected_objects": [], "affected_are_targets": False,
                        "criteria": dict(criteria), "rule_locators": ["Core 355.10.b", "Core 359.3.e.2", "Core 359.3.e.5"],
                        "before_state_hash": before_hash, "after_state_hash": before_hash, **selector_meta,
                    }
                    trace.append(event)
                    outcomes[effect_id] = "skipped_illegal_target"
                    continue
                battlefield_ids = [targeted_battlefield]
            else:
                battlefield_ids = sorted(current["battlefields"])
            candidates = [o for battlefield_id in battlefield_ids for o in current["battlefields"][battlefield_id]["objects"]]
            if criteria.get("location") == "board":
                # "Give friendly units +2 Might this turn": every such unit on the Board - the
                # Bases as well as the Battlefields (Core 105), not only the Battlefields
                # (2026-09-24; the clause grammar has always emitted this location)
                for player_id in sorted(current["players"]):
                    candidates += list(current["players"][player_id]["zones"].get("base") or [])
            affected_ids: list[str] = []
            # 2026-09-27 package 6: "other" - the program's own source, as it is now, is left out
            # (the sentinel is the only value validate_program admits here)
            # 2026-10-13 package 11 (Twisted Fate - Gambler: "1 to all other enemy units here"): what an earlier
            # instruction of this program targeted is left out, as it was when that instruction acted
            excluded_targets: set[str] = set()
            if criteria.get("exclude_targets_of"):
                acted = next((e for e in trace if e.get("effect_id") == criteria["exclude_targets_of"]), {})
                excluded_targets = {acted["object_id"]} if isinstance(acted.get("object_id"), str) else set()
                excluded_targets |= {x.get("object_id") for x in acted.get("expansion_trace") or [] if x.get("object_id")}
            excluded_identity = None
            if criteria.get("exclude_source_identity") == SOURCE_IDENTITY_SENTINEL:
                source = program.get("source_object")
                if not isinstance(source, str) or source not in current["objects"]:
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                            "errors": ["affected.criteria.exclude_source_identity needs the program's source_object to be a known object"],
                            "trace": trace}
                excluded_identity = object_identity(current, source)
            for battlefield_id in [None]:
                for candidate in candidates:
                    obj = current["objects"][candidate]
                    if "kind" in criteria and obj["kind"] != criteria["kind"]:
                        continue
                    # 2026-09-27 package 6: a state the set is narrowed by, read now (Core 414.2, 415.2, 142)
                    if not object_state_holds(obj, criteria):
                        continue
                    if excluded_identity is not None and object_identity(current, candidate) == excluded_identity:
                        continue
                    if candidate in excluded_targets:
                        continue
                    if active_combat is not None and (obj.get("combat_designation") or {}).get("combat_id") != active_combat.get("combat_id"):
                        continue  # present but not yet designated: not "in combat" (740.2.c)
                    relation = criteria.get("controller_relation")
                    if relation == "friendly" and not same_side(current, program.get("controller"), obj.get("controller")):
                        continue
                    if relation == "enemy" and same_side(current, program.get("controller"), obj.get("controller")):
                        continue
                    if relation == "own" and obj.get("controller") != program.get("controller"):
                        continue
                    affected_ids.append(candidate)
            group_read = None
            if isinstance(effect.get("amount_ref"), dict) and effect["amount_ref"].get("kind") == LINKED_PAID_AMOUNT:
                # package 10 (Bullet Time): "that much" - what the earlier payment paid; declined, this is ignored with it
                paid_event = next((e for e in trace if e.get("effect_id") == effect["amount_ref"]["effect_id"]), None)
                if paid_event is None or paid_event.get("outcome") in LINKED_IGNORED_OUTCOMES:
                    event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                             "completion": "none", "linked_effect_id": effect["amount_ref"]["effect_id"],
                             "reason": "the payment was declined, so this is ignored with it",
                             "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                group_read = {"kind": LINKED_PAID_AMOUNT, "linked_effect_id": effect["amount_ref"]["effect_id"],
                              "might": paid_event.get("paid_total")}
                if not paid_event.get("paid_total"):
                    event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                             "completion": "none", "reason": "amount_ref_not_positive", "amount_read": 0,
                             "amount_read_from": group_read, "targeted_battlefield": targeted_battlefield,
                             "rule_locators": ["Core 417.1.e"], "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                effect = {**{k: v for k, v in effect.items() if k != "amount_ref"}, "amount": paid_event["paid_total"]}
            if isinstance(effect.get("amount_ref"), dict) and effect["amount_ref"].get("kind") == "linked_object_current_might":
                # package 10 (Stormbringer): "equal to its Might" - the linked object's Might read ONCE, now (Core
                # 359.3.f.2), and dealt to each unit of the group; the earlier instruction ignored, this one is too
                # (359.3.e.14.a); the object no longer there reads null (359.3.e.12) and nothing is dealt
                linked_ids, linked_event = linked_objects(trace, effect["amount_ref"]["effect_id"])
                if linked_ids is None or len(linked_ids) != 1:
                    event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                             "completion": "none", "linked_effect_id": effect["amount_ref"]["effect_id"],
                             "reason": "the linked instruction was ignored, so this one is too",
                             "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                linked_id = linked_ids[0]
                read = effective_might(current, linked_id) if on_board_as_linked(current, snapshots, linked_id, linked_event) else None
                group_read = {"kind": "linked_object_current_might", "object_id": linked_id,
                              "linked_effect_id": effect["amount_ref"]["effect_id"], "might": read,
                              "bound_identity": linked_identity(snapshots, linked_id, linked_event, after=True)}
                if read is None or read < 1:
                    event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                             "completion": "none", "reason": "amount_ref_not_positive" if read is not None else "amount_ref_null",
                             "amount_read": read, "amount_read_from": group_read, "targeted_battlefield": targeted_battlefield,
                             "rule_locators": ["Core 359.3.e.12", "Core 359.3.f.2", "Core 417.1.e"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                effect = {**{k: v for k, v in effect.items() if k != "amount_ref"}, "amount": read}
            snapshot_hash = hash_value({"state": before_hash, "criteria": criteria, "battlefields": battlefield_ids, "affected": affected_ids})
            sub_trace = []
            working = current
            failure = None
            for object_id in affected_ids:
                single = {k: v for k, v in effect.items() if k not in {"affected", "target", "targets", "effect_id", "optional"}}
                single["object_id"] = object_id
                single["effect_id"] = f"{effect_id}:{object_id}"
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"affected:{program['program_id']}:{effect_id}", "controller": program.get("controller"),
                               "source_object": program.get("source_object"), "effects": [single]}
                sub = apply_program(working, sub_program, decisions=None, context=nested_context(context), _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    failure = sub
                    break
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            if failure is not None:
                return {
                    **base, "valid": failure.get("valid", True), "committed": False,
                    "unsupported": failure.get("unsupported", False),
                    "replacement_decision_required": failure.get("replacement_decision_required", False),
                    "replacement_ids": failure.get("replacement_ids", []),
                    "failed_effect_index": index, "reason": failure.get("reason", "; ".join(failure.get("errors", [])) or "criteria expansion failed"),
                    "expansion_result": failure, "trace": trace,
                }
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in {"applied", "replaced_modified_applied", "augmented_applied"})
            event = {
                "index": index, "effect_id": effect_id, "op": effect["op"],
                "outcome": "applied" if applied else "no_op",
                "completion": "full" if (applied == len(affected_ids)) else ("partial" if applied else "none") if affected_ids else "full",
                "targeted_battlefield": targeted_battlefield, "affected_objects": affected_ids, "affected_are_targets": False,
                "criteria": dict(criteria), "criteria_snapshot_hash": snapshot_hash, "expansion_trace": sub_trace,
                **({"amount_read": group_read["might"], "amount_read_from": group_read} if group_read else {}),
                **({"active_combat": dict(active_combat) if active_combat else None} if criteria.get("location") == "active_combat" else {}),
                "pending_triggers": group_pending_triggers(sub_trace, current),
                "rule_locators": list(dict.fromkeys(["Core 355.5.a", "Core 355.10.b", "Core 355.10.d"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                "before_state_hash": before_hash, "after_state_hash": hash_value(current), **selector_meta,
            }
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        if effect.get("targets") is not None:
            verdicts = [(sel, *evaluate_target(current, sel, program.get("controller"))) for sel in selectors]
            valid_sels = [sel for sel, ok, _ in verdicts if ok]
            invalid = [{"object_id": sel.get("object_id"), "reason": reason} for sel, ok, reason in verdicts if not ok]
            requested = len(selectors)
            group_subset = None
            if effect["targets"].get("group") and valid_sels and not target_group_holds(
                    current, [sel["object_id"] for sel in valid_sels], effect["targets"]["group"], program.get("controller"),
                    subset=True)[0]:
                # package 10, Core 355.11.b: the targets still legal no longer meet the group requirement together - the
                # controller keeps a subset of them that does; the rest are left unaffected
                group_subset, refusal = target_group_subset(current, effect, valid_sels, decisions, program.get("controller"))
                if refusal is not None:
                    return {**base, **refusal, "failed_effect_index": index, "trace": trace}
                invalid += [{"object_id": sel["object_id"], "reason": "target_group_subset_left_out"}
                            for sel in valid_sels if sel["object_id"] not in group_subset]
                valid_sels = [sel for sel in valid_sels if sel["object_id"] in group_subset]
            if requested and not valid_sels:
                event = {
                    "index": index, "effect_id": effect_id, "op": effect["op"],
                    "outcome": "skipped_illegal_target", "target_outcome": "skipped_illegal_target", "completion": "none",
                    "requested_targets": requested, "applied_targets": 0, "invalid_targets": invalid,
                    "rule_locators": ["Core 359.3.e.5", "Core 359.3.e.7"],
                    "before_state_hash": before_hash, "after_state_hash": before_hash, **selector_meta,
                }
                trace.append(event)
                outcomes[effect_id] = "skipped_illegal_target"
                continue
            division = None
            split_bonus = None
            if effect.get("division_ref") is not None and valid_sels:
                # Core 715.3: the Bonus Damage is added once, to the amount split, over the Targets
                # still legal - before it is divided; no share has it added again below
                if effect.get("source_kind") != "unit":
                    try:
                        bonus, bonus_sources = split_bonus_damage(current, program.get("controller"),
                                                                  [sel["object_id"] for sel in valid_sels],
                                                                  source_object=program.get("source_object"))
                    except NotImplementedError as exc:
                        return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                                "reason": str(exc), "trace": trace}
                    if bonus:
                        split_bonus = {"base_amount": effect["amount"], "amount": bonus, "sources": bonus_sources,
                                       "rule_locators": list(SPLIT_BONUS_RULES)}
                        effect = {**effect, "amount": effect["amount"] + bonus}
                division, refusal = split_division(current, effect, valid_sels, decisions, program.get("controller"))
                if refusal is not None:
                    return {**base, **refusal, "failed_effect_index": index, "trace": trace}
            sub_trace = []
            working = current
            expansion_failed = None
            for sel in valid_sels:
                if division is not None and sel["object_id"] not in division:
                    # Core 355.14.h: more Targets than damage - this one ceased to be a Target
                    continue
                single = {k: v for k, v in effect.items() if k not in {"targets", "effect_id", "division_ref", "optional"}}
                if division is not None:
                    single["amount"] = division[sel["object_id"]]
                    # the share already holds its part of the split's Bonus Damage (715.3): marked,
                    # so the single-target Deal does not add a bonus of its own (715.1)
                    single["bonus_damage"] = {"included_in_split": effect_id, "split_bonus": (split_bonus or {}).get("amount", 0),
                                              "rule_locators": ["Core 715.3"]}
                single["object_id"] = sel["object_id"]
                # a "here" restriction (location_ref) was bound and checked above, for this Target, now;
                # the bound Battlefield is engine-internal and never an authorable field of the
                # sub-program (package 5: a split's Targets carry "here")
                single["target"] = {k: v for k, v in sel.items() if k != "location_battlefield"}
                single["effect_id"] = f"{effect_id}:{sel['object_id']}"
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"expand:{program['program_id']}:{effect_id}", "controller": program.get("controller"),
                               "source_object": program.get("source_object"), "effects": [single]}
                sub = apply_program(working, sub_program, decisions=None, context=nested_context(context), _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    expansion_failed = sub
                    break
                working = sub["next_state"]
                sub_trace.extend(sub["trace"])
            if expansion_failed is not None:
                return {
                    **base, "valid": expansion_failed.get("valid", True), "committed": False,
                    "unsupported": expansion_failed.get("unsupported", False),
                    "replacement_decision_required": expansion_failed.get("replacement_decision_required", False),
                    "replacement_ids": expansion_failed.get("replacement_ids", []),
                    "failed_effect_index": index, "reason": expansion_failed.get("reason", "; ".join(expansion_failed.get("errors", [])) or "multi-target expansion failed"),
                    "expansion_result": expansion_failed, "trace": trace,
                }
            current = working
            applied = sum(1 for ev in sub_trace if ev.get("outcome") in {"applied", "replaced_modified_applied", "augmented_applied"})
            target_outcome = "applied_full" if not invalid and applied == requested else "applied_to_subset"
            below_min = len(valid_sels) < effect["targets"]["min"]
            if division is not None:
                requested = len(division)
                target_outcome = "applied_full" if applied == requested else "applied_to_subset"
            event = {
                "index": index, "effect_id": effect_id, "op": effect["op"],
                "outcome": "applied" if applied else "no_op",
                "target_outcome": target_outcome,
                "completion": "full" if (applied == requested and not invalid) else ("partial" if applied else "none"),
                "requested_targets": requested, "applied_targets": applied, "invalid_targets": invalid,
                "below_minimum": below_min,
                "expansion_trace": sub_trace,
                "pending_triggers": group_pending_triggers(sub_trace, current),
                "rule_locators": list(dict.fromkeys(["Core 355.13", "Core 359.3.e.8"] + [loc for ev in sub_trace for loc in ev.get("rule_locators", [])])),
                "before_state_hash": before_hash, "after_state_hash": hash_value(current), **selector_meta,
            }
            if group_subset is not None:
                event["group_subset"] = list(group_subset)
                event["rule_locators"] = list(dict.fromkeys(event["rule_locators"] + ["Core 355.11", "Core 355.11.b"]))
            if division is not None:
                event["division"] = dict(division)
                event["division_amount"] = effect["amount"]
                event["rule_locators"] = list(dict.fromkeys(event["rule_locators"] + [
                    "Core 355.14.a", "Core 355.14.e", "Core 355.14.f", "Core 355.14.h"]))
                if split_bonus is not None:
                    event["bonus_damage"] = split_bonus
                    event["rule_locators"] = list(dict.fromkeys(event["rule_locators"] + split_bonus["rule_locators"]))
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue
        # Round H: an instruction that names a captured subject rather than a
        # chosen target. It is not targeting (355.10.a) - nobody chose it - but
        # it still must be the *same* object the capture named, so a later
        # instruction cannot land on something else holding that id now.
        subject_identity = effect.get("subject_identity")
        if subject_identity is not None:
            subject = effect.get("object_id")
            if subject not in current["objects"] or object_identity(current, subject) != subject_identity:
                event = {
                    "index": index, "effect_id": effect_id, "op": effect["op"],
                    "outcome": "ignored_subject_changed", "completion": "none",
                    "reason": "subject_identity_changed", "object_id": subject,
                    "rule_locators": ["Core 359.3.e.4", "Core 370.1.b"],
                    "before_state_hash": before_hash, "after_state_hash": before_hash,
                }
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
        target = selectors[0] if selectors else None
        if target is not None:
            effect = {**effect, "target": target, "object_id": effect.get("object_id", target.get("object_id"))}
            legal_target, reason = evaluate_target(current, target, program.get("controller"))
            if not legal_target:
                event = {
                    "index": index,
                    "effect_id": effect_id,
                    "op": effect["op"],
                    "outcome": "ignored_illegal_target",
                    "target_outcome": "skipped_illegal_target",
                    "completion": "none",
                    "reason": reason,
                    "target_object_id": target["object_id"],
                    "rule_locators": ["Core 359.3.e.1–359.3.e.5", "Core 359.3.e.14"],
                    "before_state_hash": before_hash,
                    "after_state_hash": before_hash,
                }
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            if effect.get("object_id") is not None and effect.get("object_id") != target["object_id"]:
                return {
                    **base,
                    "valid": False,
                    "committed": False,
                    "failed_effect_index": index,
                    "errors": ["effect object_id must match target.object_id"],
                    "trace": trace,
                }
        # 2026-09-27: the LINKED references (Core 359.3.e.14) - "It deals damage equal to its
        # Might" names the earlier instruction's object as the Deal's source (417.6.b.3) and its
        # Might as the amount; "Deal its Energy cost" names the discarded card's printed cost.
        # Read now, once the target is known legal; an ignored earlier instruction ignores this
        # one (359.3.e.14.a); an object no longer there reads null and nothing is dealt (359.3.e.12).
        unless = effect.get("unless")
        if isinstance(unless, dict) and isinstance(effect.get("target"), dict):
            import engine_decisions as ed
            target_id = selectors[0]["object_id"] if selectors else None
            chooser = (current["objects"].get(target_id) or {}).get("controller")
            entry = ed.option_selection(decisions, unless["decision_ref"])
            if chooser not in current["players"]:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index,
                        "errors": [f"unless: the target {target_id!r} has no controller to choose"], "trace": trace}
            if entry is None:
                return {**base, "valid": True, "committed": False, "option_selection_required": True,
                        "reason_code": "option_selection_required",
                        "reason": f"{chooser} (the target's controller) chooses {UNLESS_OPTIONS} as the instruction resolves",
                        "decision_ids": [unless["decision_ref"]], "decision_controller": chooser,
                        "options": list(UNLESS_OPTIONS), "failed_effect_index": index, "trace": trace}
            if entry["controller"] != chooser:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch",
                        "reason": f"'unless' was chosen by {entry['controller']!r}, not the target's controller {chooser!r}",
                        "failed_effect_index": index, "trace": trace}
            if entry["value"] not in UNLESS_OPTIONS:
                return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "illegal_operation",
                        "reason": f"'unless' names {entry['value']!r}, not one of {UNLESS_OPTIONS}",
                        "failed_effect_index": index, "trace": trace}
            if entry["value"] == "instead":
                sub_program = {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                               "program_id": f"unless:{program['program_id']}:{effect_id}", "controller": program.get("controller"),
                               "source_object": program.get("source_object"), "effects": copy.deepcopy(unless["instead"])}
                sub = apply_program(current, sub_program, decisions=decisions, context=nested_context(context),
                                    _replacement_depth=_replacement_depth + 1)
                if sub.get("committed") is not True:
                    # the "instead" stopped where its own instructions stop (a Burn Out's randomization, a decision):
                    # that stop is passed on as it is, so the caller supplies what the Draw itself would ask for
                    return {**base, **{k: v for k, v in sub.items() if k not in base and k not in ("trace", "next_state")},
                            "valid": sub.get("valid", True), "committed": False, "failed_effect_index": index,
                            "expansion_result": sub, "trace": trace}
                current = sub["next_state"]
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "chose_instead",
                         "completion": "none", "chosen_by": chooser, "decision_id": unless["decision_ref"],
                         "target_object_id": target_id, "instead_trace": sub["trace"],
                         "rule_locators": ["Core 355.10.e", "Core 359.3.e.14"],
                         "before_state_hash": before_hash, "after_state_hash": hash_value(current)}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect = {k: v for k, v in effect.items() if k != "unless"}
        linked_refs = []
        if is_source_ref(effect.get("source_ref")):
            linked_refs.append(("source", effect["source_ref"]["effect_id"]))
        if isinstance(effect.get("amount_ref"), dict) and effect["amount_ref"].get("kind") in LINKED_AMOUNT_REF_KINDS:
            linked_refs.append(("amount", effect["amount_ref"]["effect_id"]))
        if isinstance(effect.get("subject_ref"), dict):
            linked_refs.append(("subject", effect["subject_ref"]["effect_id"]))
        if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                and effect["destination"].get("kind") == LINKED_BATTLEFIELD_DESTINATION:
            linked_refs.append(("destination", effect["destination"]["effect_id"]))
        if effect.get("op") == "move_board_object" and isinstance(effect.get("destination"), dict) \
                and effect["destination"].get("kind") == LINKED_TARGETED_BATTLEFIELD_DESTINATION:
            producer_event = next((e for e in trace if e.get("effect_id") == effect["destination"]["effect_id"]), None)
            there = (producer_event or {}).get("targeted_battlefield")
            if producer_event is None or producer_event.get("outcome") in LINKED_IGNORED_OUTCOMES or there not in current["battlefields"]:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                         "completion": "none", "linked_effect_id": effect["destination"]["effect_id"],
                         "reason": "the instruction whose targeted Battlefield 'there' names was ignored",
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect = {**effect, "destination": {"kind": "battlefield", "battlefield": there}}
        skipped_link = None
        linked_now: dict[str, tuple[str, dict[str, Any]]] = {}
        for role, ref_id in linked_refs:
            objects, linked = linked_objects(trace, ref_id)
            if objects is None or len(objects) != 1:
                skipped_link = (ref_id, objects)
                break
            linked_now[role] = (objects[0], linked)
        if skipped_link is not None:
            event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "skipped_linked_dependency",
                     "completion": "none", "linked_effect_id": skipped_link[0],
                     "reason": ("the linked instruction was ignored, so this one is too" if skipped_link[1] is None
                                else "the linked instruction acted on more than one object; 'its' names one"),
                     "rule_locators": ["Core 359.3.e.14", "Core 359.3.e.14.a"],
                     "before_state_hash": before_hash, "after_state_hash": before_hash}
            trace.append(event)
            outcomes[effect_id] = event["outcome"]
            continue


        if "source" in linked_now:
            source_id, source_event = linked_now["source"]
            if not on_board_as_linked(current, snapshots, source_id, source_event):
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "source_ref_object_unavailable", "source_object": source_id,
                         "rule_locators": ["Core 359.3.e.12", "Core 417.6.b.3"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect = {k: v for k, v in effect.items() if k != "source_ref"}
            effect.update({"source_object": source_id, "source_kind": "unit"})
            linked_reads["source_read"] = {"object_id": source_id, "linked_effect_id": source_event.get("effect_id"),
                                           "rule_locators": ["Core 359.3.e.14", "Core 417.6.b.3"]}
        if "subject" in linked_now:
            subject_id, subject_event = linked_now["subject"]
            if not on_board_as_linked(current, snapshots, subject_id, subject_event):
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "subject_ref_object_unavailable", "object_id": subject_id,
                         "rule_locators": ["Core 359.3.e.12", "Core 359.3.e.14"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect = {**{k: v for k, v in effect.items() if k != "subject_ref"}, "object_id": subject_id}
            linked_reads["subject_read"] = {"object_id": subject_id, "linked_effect_id": subject_event.get("effect_id"),
                                            "bound_identity": linked_identity(snapshots, subject_id, subject_event, after=True),
                                            "rule_locators": ["Core 359.3.e.14"]}
        if effect.get("op") == "return_to_hand" and isinstance(effect.get("self"), dict):
            # 2026-10-12 (package 11, Super Mega Death Rocket!; GPT PACKAGE11 ruling 6): "return this from your trash to your
            # hand" - the program's own source as its chain item recorded it (bind_source_identity), still in its owner's
            # zone. Gone from it, or back as a new object (Core 124), it is not the "this" the ability is about: the
            # instruction is ignored (359.3.e.6) - whatever was paid for it stays paid, and no other card is taken
            source = program.get("source_object")
            declared = program.get("source_identity")
            source_obj = current["objects"].get(source) if isinstance(source, str) else None
            owner = (source_obj or {}).get("owner")
            in_zone = (source_obj is not None and owner in current["players"]
                       and source in current["players"][owner]["zones"].get(effect["self"]["from"], []))
            same = not declared or object_identity(current, source) == declared
            if not (in_zone and same):
                event = {"index": index, "effect_id": effect_id, "op": "return_to_hand", "outcome": "no_op",
                         "completion": "none", "reason": "source_not_in_zone" if not in_zone else "source_identity_changed",
                         "source_object": source, "rule_locators": ["Core 124", "Core 359.3.e.6"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect = {**{k: v for k, v in effect.items() if k != "self"}, "object_id": source}
        if "destination" in linked_now:
            object_id, destination_event = linked_now["destination"]
            where = find_location(current, object_id) if on_board_as_linked(current, snapshots, object_id, destination_event) else None
            read_from = {"kind": LINKED_BATTLEFIELD_DESTINATION, "object_id": object_id,
                         "linked_effect_id": effect["destination"]["effect_id"],
                         "bound_identity": linked_identity(snapshots, object_id, destination_event, after=True),
                         "battlefield": where[1] if where and where[0] == "battlefield" else None,
                         "rule_locators": ["Core 359.3.e.14", "Core 359.3.f.2"]}
            if not where or where[0] != "battlefield":
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "destination_ref_not_at_battlefield", "destination_read_from": read_from,
                         "rule_locators": ["Core 359.3.e.12", "Core 359.3.f.2"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect = {**effect, "destination": {"kind": "battlefield", "battlefield": where[1]}}
            linked_reads["destination_read"] = read_from
        if "amount" in linked_now:
            ref = effect["amount_ref"]
            object_id, amount_event = linked_now["amount"]
            if ref["kind"] == "linked_object_current_might":
                read = effective_might(current, object_id) if on_board_as_linked(current, snapshots, object_id, amount_event) else None
                read_from = {"kind": ref["kind"], "object_id": object_id, "linked_effect_id": ref["effect_id"], "might": read}
                read_from["bound_identity"] = linked_identity(snapshots, object_id, amount_event, after=True)
            else:
                # bound by identity (GPT 2026-09-27): the card the linked instruction left, and only
                # while the object at that id is still that card - a card that has since moved on is a
                # new object (Core 124) and its cost reads null (359.3.e.12)
                bound = linked_identity(snapshots, object_id, amount_event, after=True)
                same = object_id in current["objects"] and bound is not None and object_identity(current, object_id) == bound
                printed = (current["objects"].get(object_id) or {}).get("printed_cost") if same else None
                energy = printed.get("energy") if isinstance(printed, dict) else None
                if same and (not isinstance(energy, int) or isinstance(energy, bool)):
                    return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                            "reason": f"the printed Energy cost of {object_id!r} is not observed; 'its Energy cost' "
                                      f"is not guessed (Core 206)", "trace": trace}
                read = energy if same else None
                read_from = {"kind": ref["kind"], "object_id": object_id, "linked_effect_id": ref["effect_id"], "energy": read,
                             "bound_identity": bound}
            effect = {k: v for k, v in effect.items() if k != "amount_ref"}
            if read is None or read < 1:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "amount_ref_not_positive" if read is not None else "amount_ref_null",
                         "amount_read": read, "amount_read_from": read_from,
                         "rule_locators": ["Core 359.3.e.12", "Core 359.3.f.2", "Core 417.1.e"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect["amount"] = read
            effect["amount_read_from"] = read_from
            # on the event too: what was read, off which object, bound to which identity (GPT 2026-09-27)
            linked_reads["amount_read"] = copy.deepcopy(read_from)
        # "equal to my Might": read now, on execution, once the target is known legal
        # (Core 359.3.f.2); an illegal target was already skipped above, unread
        if (effect.get("amount_ref") or {}).get("kind") == "object_current_might":
            # package 10 (Last Stand): the target's current Might, read now (Core 477.3.c); not positive, nothing is
            # given (a +0 is no change, Core 370.1.a) - the instruction is a no_op, never a negative modifier
            read = effective_might(current, effect["object_id"])
            effect = {k: v for k, v in effect.items() if k != "amount_ref"}
            read_from = {"kind": "object_current_might", "object_id": effect["object_id"], "might": read,
                         "rule_locators": ["Core 477.3.c", "Core 359.3.f.2"]}
            if read < 1:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "amount_ref_not_positive", "amount_read": read,
                         "amount_read_from": read_from, "rule_locators": ["Core 477.3.c", "Core 370.1.a"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect["amount"] = read
            effect["amount_read_from"] = read_from
        if effect.get("amount_ref") is not None:
            try:
                read, read_from = resolve_amount_ref(effect["amount_ref"], current, program)
            except SourceUnavailable as exc:
                # "my Might" of a source that is gone reads null (359.3.e.12): the Deal is ignored
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": SOURCE_UNAVAILABLE_OUTCOME,
                         "completion": "none", "reason": exc.reason_code, "message": str(exc),
                         "source_object": program.get("source_object"),
                         "rule_locators": list(SOURCE_UNAVAILABLE_RULES) + ["Core 359.3.e.12"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            except SelectionBindingRefused as exc:
                return {**base, "valid": True, "committed": False, "applied": False,
                        "reason_code": exc.reason_code, "reason": str(exc),
                        "failed_effect_index": index, "trace": trace}
            effect = {k: v for k, v in effect.items() if k != "amount_ref"}
            if read < 1:
                event = {"index": index, "effect_id": effect_id, "op": effect["op"], "outcome": "no_op",
                         "completion": "none", "reason": "amount_ref_not_positive", "amount_read": read,
                         "amount_read_from": read_from, "rule_locators": ["Core 359.3.f.2"],
                         "before_state_hash": before_hash, "after_state_hash": before_hash}
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            effect["amount"] = read
            effect["amount_read_from"] = {"kind": "program_source_current_might", "object_id": read_from, "might": read}
        # A token the program cannot name: a fresh id, minted now (Core 124), and "here" as
        # where it enters - the source's current Battlefield, read now (Core 359.3.f.2); a
        # source that is not at a Battlefield plays no token (2026-09-24)
        if effect.get("op") == "move_board_object" and (effect.get("destination") or {}).get("restriction") == "here":
            # package 11 (Blitzcrank - Impassive): "to here" read as the Move executes (Core 359.3.f.2); a destination chosen
            # at finalization that is no longer here is not carried out (move_destination_no_longer_legal)
            effect = {**effect, "destination": bind_move_here(effect["destination"], current, program)}
        if effect.get("op") == "play_token" and (effect.get("object_id_ref") is not None
                                                  or isinstance((effect.get("destination") or {}).get("location_ref"), dict)):
            effect = dict(effect)
            if effect.pop("object_id_ref", None) is not None:
                stem = f"token:{effect.get('token_id') or 'token'}"
                serial = 1
                while f"{stem}:{serial}" in current["objects"]:
                    serial += 1
                effect["object_id"] = f"{stem}:{serial}"
            destination = effect.get("destination") or {}
            if isinstance(destination.get("location_ref"), dict):
                try:
                    here = resolve_location_ref(destination["location_ref"], current, program)
                except SelectionBindingRefused as exc:
                    event = {"index": index, "effect_id": effect_id, "op": "play_token", "outcome": "no_op",
                             "completion": "none", "reason": exc.reason_code,
                             "rule_locators": ["Core 359.3.f.1", "Core 359.3.f.2"],
                             "before_state_hash": before_hash, "after_state_hash": before_hash}
                    trace.append(event)
                    outcomes[effect_id] = event["outcome"]
                    continue
                effect["destination"] = {"kind": "battlefield", "battlefield": here}
        affected_before_damage = current["objects"].get(effect.get("object_id"), {}).get("damage")
        # ADR-0007 §5: Bonus Damage is a property of the Deal action — added
        # once the Deal is known to happen with a non-zero base (715.4), before
        # any replacement or Prevent looks at the amount (437.1.a.1).
        if effect.get("op") == "deal_damage" and isinstance(effect.get("amount"), int) and effect["amount"] >= 1 and "bonus_damage" not in effect and effect.get("source_kind") != "unit":
            try:
                bonus, bonus_sources = bonus_damage(current, program.get("controller"), effect.get("object_id"),
                                                    source_object=program.get("source_object"))
            except NotImplementedError as exc:
                return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index, "reason": str(exc), "trace": trace}
            if bonus:
                effect = {**effect, "amount": effect["amount"] + bonus,
                          "bonus_damage": {"base_amount": effect["amount"], "amount": bonus, "sources": bonus_sources, "rule_locators": ["Core 713", "Core 714", "Core 715.1", "Core 715.2", "Core 437.1.a.1"]}}
        if decisions is not None and (effect.get("replacement_order") is None or effect.get("replacement_choices") is None):
            import engine_decisions as ed
            order_map, choice_map = ed.replacement_maps(decisions)
            effect = dict(effect)
            key = effect.get("effect_id", effect_id)
            if effect.get("replacement_order") is None and order_map and key in order_map:
                effect["replacement_order"] = list(order_map[key])
                effect.setdefault("replacement_decider", next((e["controller"] for e in ed.entries(decisions, kind="replacement_order")), None))
            if effect.get("replacement_choices") is None and choice_map:
                merged = {rid: by_event.get(key, by_event.get("*")) for rid, by_event in choice_map.items()}
                merged = {rid: v for rid, v in merged.items() if isinstance(v, bool)}
                if merged:
                    effect["replacement_choices"] = merged
        try:
            replacement_selection = _select_replacement(current, effect, _applied_replacements)
        except ReplacementDecisionRequired as exc:
            return {
                **base,
                "valid": True,
                "committed": False,
                "replacement_decision_required": True,
                "failed_effect_index": index,
                "reason": str(exc),
                "replacement_ids": exc.replacement_ids,
                "trace": trace,
            }
        except IllegalOperation as exc:
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": "illegal_operation", "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
            }
        except NotImplementedError as exc:
            # package 10: a replacement cost whose Domain is the payer's choice (replacement_cost_domain_choice_unsupported)
            return {**base, "valid": True, "committed": False, "unsupported": True, "failed_effect_index": index,
                    "reason": str(exc), "trace": trace}
        except ValueError as exc:
            return {
                **base,
                "valid": False,
                "committed": False,
                "failed_effect_index": index,
                "errors": [str(exc)],
                "trace": trace,
            }
        if replacement_selection is not None:
            selected_state, event, replacement = replacement_selection
            if replacement["mode"] == "prevent_event":
                current = selected_state
                event.update({"index": index, "effect_id": effect_id, "before_state_hash": before_hash, "after_state_hash": hash_value(current)})
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            replacement_id = replacement["replacement_id"]
            replacement_index = next(i for i, item in enumerate(selected_state["replacement_effects"]) if item["replacement_id"] == replacement_id)
            stored_replacement = copy.deepcopy(selected_state["replacement_effects"][replacement_index])
            if replacement["mode"] == "augment_with":
                recursive_state = copy.deepcopy(selected_state)
                del recursive_state["replacement_effects"][replacement_index]
                original_effect = copy.deepcopy(effect)
                supplied_order = original_effect.get("replacement_order")
                if isinstance(supplied_order, list):
                    original_effect["replacement_order"] = [item for item in supplied_order if item != replacement_id]
                original_program = {
                    "schema_version": PROGRAM_VERSION,
                    "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                    "program_id": f"augmentation-original:{replacement_id}:{program['program_id']}:{effect_id}",
                    "controller": program.get("controller"),
                    "source_object": program.get("source_object"),
                    "effects": [original_effect],
                }
                original_result = apply_program(recursive_state, original_program, context=nested_context(context),
                                                _replacement_depth=_replacement_depth + 1,
                                                _applied_replacements=_applied_replacements | {replacement_id})
                if original_result.get("committed") is not True:
                    return {
                        **base, "valid": original_result.get("valid", True), "committed": False,
                        "unsupported": original_result.get("unsupported", False), "failed_effect_index": index,
                        "reason": original_result.get("reason", "; ".join(original_result.get("errors", [])) or "augmented original event failed"),
                        "replacement_id": replacement_id, "replacement_result": original_result, "trace": trace,
                    }
                try:
                    try:
                        augmentation_effects = _bind_replacement_effects(
                            _inherit_event_modifiers(effect, replacement["replacement_effects"]),
                            effect.get("object_id"), replacement.get("source_object"))
                    except IllegalOperation as exc:
                        return {
                            **base, "valid": True, "committed": False, "applied": False,
                            "reason_code": "replacement_binding_unbound", "reason": str(exc),
                            "replacement_id": replacement_id, "failed_effect_index": index, "trace": trace,
                        }
                except NotImplementedError as exc:
                    return {
                        **base, "valid": True, "committed": False, "unsupported": True,
                        "failed_effect_index": index, "reason": str(exc), "replacement_id": replacement_id, "trace": trace,
                    }
                augmentation_program = {
                    "schema_version": PROGRAM_VERSION,
                    "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                    "program_id": f"augmentation-extra:{replacement_id}:{program['program_id']}:{effect_id}",
                    "controller": replacement["controller"],
                    **({"source_object": replacement["source_object"]} if "source_object" in replacement else {}),
                    "effects": augmentation_effects,
                }
                augmentation_result = apply_program(original_result["next_state"], augmentation_program, context=nested_context(context),
                                                    _replacement_depth=_replacement_depth + 1,
                                                    _applied_replacements=_applied_replacements | {replacement_id})
                if augmentation_result.get("committed") is not True:
                    return {
                        **base, "valid": augmentation_result.get("valid", True), "committed": False,
                        "unsupported": augmentation_result.get("unsupported", False), "failed_effect_index": index,
                        "reason": augmentation_result.get("reason", "; ".join(augmentation_result.get("errors", [])) or "augmentation program failed"),
                        "replacement_id": replacement_id, "replacement_result": augmentation_result, "trace": trace,
                    }
                current = augmentation_result["next_state"]
                source_still_active = replacement_active(current, stored_replacement)
                active_uses = stored_replacement.get("uses_remaining") is None or stored_replacement.get("uses_remaining", 0) > 0
                if source_still_active and active_uses:
                    current["replacement_effects"].insert(min(replacement_index, len(current["replacement_effects"])), stored_replacement)
                if found := validate_state(current):
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": found, "trace": trace}
                original_trace = original_result.get("trace", [])
                augmentation_trace = augmentation_result.get("trace", [])
                original_happened = any(child.get("outcome") in {"applied", "replaced_modified_applied", "augmented_applied"} for child in original_trace)
                pending = []
                for offset, child_result in enumerate((original_result, augmentation_result)):
                    for trigger in child_result.get("pending_triggers", []):
                        copied_trigger = dict(trigger)
                        copied_trigger["batch_sequence"] = index * 1000 + offset * 500 + copied_trigger.get("batch_sequence", 0)
                        copied_trigger["batch_id"] = f"augmentation:{replacement_id}:{copied_trigger.get('batch_id', 'batch')}"
                        pending.append(copied_trigger)
                nested_locators = [locator for child in original_trace + augmentation_trace for locator in child.get("rule_locators", [])]
                event.update({
                    "outcome": "augmented_applied" if original_happened else "augmented_original_replaced",
                    "original_event_happened": original_happened,
                    "index": index,
                    "effect_id": effect_id,
                    "before_state_hash": before_hash,
                    "after_state_hash": hash_value(current),
                    "original_trace": original_trace,
                    "augmentation_trace": augmentation_trace,
                    "pending_triggers": pending,
                    "rule_locators": list(dict.fromkeys(event["rule_locators"] + nested_locators + ["Core 370.1.b.1"])),
                })
                trace.append(event)
                outcomes[effect_id] = "applied" if original_happened else event["outcome"]
                continue
            try:
                try:
                    replacement_program_effects = _bind_replacement_effects(
                        _inherit_event_modifiers(effect, replacement.get("replacement_effects", [])),
                        effect.get("object_id"), replacement.get("source_object"),
                        object_identity(selected_state, effect["object_id"])
                        if effect.get("object_id") in selected_state["objects"] else None)
                except IllegalOperation as exc:
                    return {
                        **base, "valid": True, "committed": False, "applied": False,
                        "reason_code": "replacement_binding_unbound", "reason": str(exc),
                        "replacement_id": replacement_id, "failed_effect_index": index, "trace": trace,
                    }
            except NotImplementedError as exc:
                return {
                    **base, "valid": True, "committed": False, "unsupported": True,
                    "failed_effect_index": index, "reason": str(exc), "replacement_id": replacement_id, "trace": trace,
                }
            original_damage = None
            prevented_damage = None
            if replacement["mode"] == "reduce_damage":
                original_damage = effect.get("amount")
                if not isinstance(original_damage, int) or original_damage < 1:
                    return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": ["reduce_damage requires positive deal_damage amount"], "trace": trace}
                prevented_damage = min(original_damage, stored_replacement["prevent_remaining"])
                stored_replacement["prevent_remaining"] -= prevented_damage
                reduced = copy.deepcopy(effect)
                reduced["amount"] = original_damage - prevented_damage
                reduced.pop("replacement_order", None)
                reduced.pop("replacement_decider", None)
                reduced.pop("replacement_choices", None)
                replacement_program_effects = [] if reduced["amount"] == 0 else [reduced]
            recursive_state = copy.deepcopy(selected_state)
            del recursive_state["replacement_effects"][replacement_index]
            if replacement["mode"] == "reduce_damage" and not replacement_program_effects:
                current = recursive_state
                if replacement_active(current, stored_replacement) and stored_replacement.get("prevent_remaining", 0) > 0:
                    current["replacement_effects"].insert(min(replacement_index, len(current["replacement_effects"])), stored_replacement)
                event.update({
                    "outcome": "replaced_prevented",
                    "index": index,
                    "effect_id": effect_id,
                    "original_damage": original_damage,
                    "prevented_damage": prevented_damage,
                    "remaining_damage": 0,
                    "before_state_hash": before_hash,
                    "after_state_hash": hash_value(current),
                    "rule_locators": list(dict.fromkeys(event["rule_locators"] + ["Core 437.1–437.4"])),
                })
                trace.append(event)
                outcomes[effect_id] = event["outcome"]
                continue
            recursive_program = {
                "schema_version": PROGRAM_VERSION,
                "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
                "program_id": f"replacement:{replacement_id}:{program['program_id']}:{effect_id}",
                "controller": replacement["controller"],
                **({"source_object": replacement["source_object"]} if "source_object" in replacement else {}),
                "effects": replacement_program_effects,
            }
            # Core 370.2: the replacing events carry the memory of what has
            # already been applied in this sequence, so a Replacement Effect
            # cannot apply to the event that replaced its own application.
            recursive_result = apply_program(recursive_state, recursive_program, context=nested_context(context),
                                             _replacement_depth=_replacement_depth + 1,
                                             _applied_replacements=_applied_replacements | {replacement_id})
            if recursive_result.get("committed") is not True:
                return {
                    **base,
                    "valid": recursive_result.get("valid", True),
                    "committed": False,
                    "unsupported": recursive_result.get("unsupported", False),
                    "failed_effect_index": index,
                    "reason": recursive_result.get("reason", "; ".join(recursive_result.get("errors", [])) or "replacement program failed"),
                    "replacement_id": replacement_id,
                    "replacement_result": recursive_result,
                    "trace": trace,
                }
            current = recursive_result["next_state"]
            replacement_still_active = replacement["mode"] != "reduce_damage" or stored_replacement.get("prevent_remaining", 0) > 0
            if replacement_active(current, stored_replacement) and replacement_still_active:
                current["replacement_effects"].insert(min(replacement_index, len(current["replacement_effects"])), stored_replacement)
            if found := validate_state(current):
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "errors": found, "trace": trace}
            nested_locators = [locator for child in recursive_result.get("trace", []) for locator in child.get("rule_locators", [])]
            nested_triggers = [dict(trigger) for trigger in recursive_result.get("pending_triggers", [])]
            for trigger in nested_triggers:
                trigger["batch_sequence"] = index * 1000 + trigger.get("batch_sequence", 0)
                trigger["batch_id"] = f"replacement:{replacement_id}:{trigger.get('batch_id', 'batch')}"
            event.update({
                "index": index,
                "effect_id": effect_id,
                "before_state_hash": before_hash,
                "after_state_hash": hash_value(current),
                "replacement_trace": recursive_result.get("trace", []),
                "pending_triggers": nested_triggers,
                "rule_locators": list(dict.fromkeys(event["rule_locators"] + nested_locators)),
            })
            if replacement["mode"] == "reduce_damage":
                affected = effect.get("object_id")
                before_damage = affected_before_damage
                after_damage = current["objects"].get(affected, {}).get("damage")
                damage_applied = isinstance(before_damage, int) and isinstance(after_damage, int) and after_damage > before_damage
                event.update({
                    "outcome": "replaced_modified_applied" if damage_applied else "replaced_modified_prevented",
                    "original_damage": original_damage,
                    "prevented_damage": prevented_damage,
                    "remaining_damage": original_damage - prevented_damage,
                    "rule_locators": list(dict.fromkeys(event["rule_locators"] + ["Core 437.1–437.4"])),
                })
            trace.append(event)
            outcomes[effect_id] = "applied" if event["outcome"] == "replaced_modified_applied" else event["outcome"]
            continue
        if effect.get("op") == "banish" and effect.get("linked") is not None:
            # 2026-10-04 (package 8): "... until you reveal a unit and banish it" - the card the named reveal_until stopped
            # at, while it is still that object in its Main Deck (Core 124); none found, or moved since: nothing banished
            ref = effect["linked"]["effect_id"]
            source_event = next((e for e in trace if e.get("effect_id") == ref and e.get("op") == "reveal_until"), None)
            if source_event is None:
                return {**base, "valid": False, "committed": False, "failed_effect_index": index, "trace": trace,
                        "errors": [f"effects[{index}].banish linked names {ref!r}, which is not an earlier reveal_until"]}
            found = source_event.get("found")
            still = (found is not None and found in current["objects"]
                     and object_identity(current, found) == source_event.get("found_identity")
                     and find_location(current, found) == ("player", current["objects"][found]["owner"], "main_deck"))
            effect = {k: v for k, v in effect.items() if k != "linked"}
            effect["objects"] = [found] if still else []
        ceiling_of = ((effect.get("choice") or {}).get("criteria") or {}).get("max_might_of")
        if ceiling_of is not None:
            # 2026-10-04 (package 8, GPT ruling 7): "up to N more than the killed unit" - the Might the named earlier
            # Kill's unit had as it died; no unit killed by it (replaced, or nothing to kill) -> null, nothing admitted
            killed = next((e for e in trace if e.get("effect_id") == ceiling_of.get("effect_id") and e.get("op") == "kill"
                           and e.get("outcome") == "applied" and isinstance(e.get("might_at_death"), int)), None)
            criteria = {k: v for k, v in effect["choice"]["criteria"].items() if k != "max_might_of"}
            criteria["max_might"] = killed["might_at_death"] + ceiling_of.get("plus", 0) if killed else None
            effect = {**effect, "choice": {**effect["choice"], "criteria": criteria}}
        if effect.get("op") == "play_token" and (context or {}).get("hidden_battlefield"):
            # Core 811.1.d.3 (GPT 2026-09-27): a unit this hidden card makes its controller play is
            # played at the battlefield it was hidden at
            effect = {**effect, "hidden_battlefield": context["hidden_battlefield"]}
        prior = current
        try:
            current, event = _apply_one(current, effect, decisions=decisions,
                                        controller=program.get("controller"), program_id=program.get("program_id"))
        except NotImplementedError as exc:
            return {
                **base,
                "valid": True,
                "committed": False,
                "unsupported": True,
                "failed_effect_index": index,
                "reason": str(exc),
                "trace": trace,
            }
        except LocationSelectionRequired as exc:
            return {
                **base, "valid": True, "committed": False, "location_selection_required": True,
                "reason_code": exc.reason_code, "reason": str(exc),
                "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                "location_candidates": exc.candidates,
                "failed_effect_index": index, "trace": trace,
            }
        except (ExternalInputRequired, PlayerSelectionRequired) as exc:
            return {
                **base, "valid": True, "committed": False, "external_input_required": isinstance(exc, ExternalInputRequired),
                "reason_code": exc.reason_code, "reason": str(exc), **chance_fields(exc),
                "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                "failed_effect_index": index, "trace": trace,
            }
        except ChoiceRequired as exc:
            return {
                **base, "valid": True, "committed": False, "choice_required": True, f"{exc.summary['decision_kind']}_required": True,
                "reason_code": exc.reason_code, "reason": str(exc), "choice": exc.summary,
                "decision_ids": exc.decision_ids, "decision_controller": exc.controller,
                "failed_effect_index": index, "trace": trace,
            }
        except IllegalDecision as exc:
            return {**base, "valid": True, "committed": False, "applied": False, "reason_code": "decision_controller_mismatch", "reason": str(exc), "failed_effect_index": index, "trace": trace}
        except IllegalOperation as exc:
            return {
                **base, "valid": True, "committed": False, "applied": False,
                "reason_code": "illegal_operation", "reason": str(exc),
                "failed_effect_index": index, "trace": trace,
            }
        except ValueError as exc:
            return {
                **base,
                "valid": False,
                "committed": False,
                "failed_effect_index": index,
                "errors": [str(exc)],
                "trace": trace,
            }
        if event.get("terminal_event") is not None:
            terminal = event["terminal_event"]
        if event.get("op") == "kill" and "pending_triggers" in event:
            group_pending_triggers([event], current)
        event.update({"index": index, "effect_id": effect_id, "before_state_hash": before_hash, "after_state_hash": hash_value(current)})
        if linked_reads:
            # 2026-09-27: what a linked reference read (the player, the source), on the event itself
            event.update(copy.deepcopy(linked_reads))
        event.setdefault("completion", "full" if event.get("outcome") == "applied" else "none")
        if effect.get("target") is not None:
            event.setdefault("target_outcome", "applied_full")
        for trigger in event.get("pending_triggers", []):
            trigger.setdefault("batch_sequence", index)
            trigger.setdefault("batch_id", f"{program['program_id']}:{effect_id}")
            trigger.setdefault("trigger_kind", "self_death")
        # ADR-0013 §1 / Core 124.1: an effect whose binding died with this
        # instruction is removed here, with its reason on the event.
        dead = prune_dead_effects(current)
        if dead:
            event["removed_continuous_effects"] = dead
        trace.append(event)
        outcomes[effect_id] = event["outcome"]
        for record in event.get("seen_banished") or []:
            # package 9 (GPT 2026-10-07): banished inside the instruction, as it was looked at (predict)
            seen_banished.append({k: record[k] for k in ("card", "owner", "identity", "amount")})
        if effect.get("op") in SEEN_FROM_TOP_OPS - {"predict"} and event.get("outcome") not in IGNORED_OUTCOMES:
            # package 9 (Nocturne - Horrifying): a card its owner just looked at or revealed from the top of their own
            # Main Deck, that may banish itself as that happens - decided now, before the next instruction
            import engine_decisions as ed
            owner, seen = seen_from_top(prior, effect, event, program.get("controller"))
            for card in seen:
                obj = current["objects"].get(card) or {}
                if not obj.get("banish_when_seen") or obj.get("owner") != owner \
                        or card not in current["players"][owner]["zones"]["main_deck"]:
                    continue
                ref = f"seen-banish:{program.get('program_id')}:{effect_id}:{card}"
                ledger_note("seen_banish", ref)
                _shown_to_chooser(ref, current, card)
                entry = next((e for e in ed.entries(decisions, kind="optional_choice") if e.get("decision_id") == ref), None)
                if entry is None or entry.get("controller") != owner or entry.get("stage") != "resolution":
                    return {**base, "valid": True, "committed": False, "optional_choice_required": True,
                            "reason_code": "optional_choice_required" if entry is None else "decision_controller_mismatch",
                            "reason": f"{card!r} was looked at or revealed from the top of {owner}'s Main Deck; its owner "
                                      f"may banish it now (its printed statement)",
                            "decision_ids": [ref], "decision_controller": owner, "failed_effect_index": index, "trace": trace}
                if entry["value"] is not True:
                    continue
                snapshots.append(game_events.snapshot(current))
                before_banish = hash_value(current)
                current, done = banish_seen(current, card, owner)
                banish_event = {"index": index, "effect_id": f"{effect_id}:seen:{card}", "op": "banish", "outcome": "applied",
                                "completion": "full", "seen_banish": True, "decision_id": ref, **done,
                                "rule_locators": ["Core 427", "Core 124"], "before_state_hash": before_banish,
                                "after_state_hash": hash_value(current)}
                trace.append(banish_event)
                outcomes[banish_event["effect_id"]] = "applied"
                seen_banished.append({"card": card, "owner": owner,
                                      "identity": done["identities_after"][card],
                                      "amount": obj["banish_when_seen"]["play_for_power_any"]})
    if seen_banished and terminal is None:
        # package 9 (Nocturne - Horrifying): "If you do, you may play me for [A]" - the effect that looked has finished;
        # the owner may play each card banished as it was seen, from Banishment, for its Power of any Domain
        import engine_decisions as ed
        for offer in seen_banished:
            card, owner = offer["card"], offer["owner"]
            ref = f"seen-play:{program.get('program_id')}:{card}"
            ledger_note("seen_banish", ref)
            _shown_to_chooser(ref, current, card)
            entry = next((e for e in ed.entries(decisions, kind="optional_choice") if e.get("decision_id") == ref), None)
            if entry is None or entry.get("controller") != owner or entry.get("stage") != "resolution":
                return {**base, "valid": True, "committed": False, "optional_choice_required": True,
                        "reason_code": "optional_choice_required" if entry is None else "decision_controller_mismatch",
                        "reason": f"{card!r} was banished as it was seen; its owner may play it for [A] now",
                        "decision_ids": [ref], "decision_controller": owner, "trace": trace}
            if entry["value"] is not True or card not in current["players"][owner]["zones"]["banishment"] \
                    or object_identity(current, card) != offer["identity"]:
                continue
            snapshots.append(game_events.snapshot(current))
            before_play = hash_value(current)
            current, play_event = _start_limited_play(
                current, {"kind": "for_power_any", "amount": offer["amount"]}, {"object_id": card},
                {**program, "controller": owner, "source_object": card}, f"seen-play:{card}")
            play_event.update({"index": len(effects_to_run), "effect_id": f"seen-play:{card}", "decision_id": ref,
                               "before_state_hash": before_play, "after_state_hash": hash_value(current)})
            trace.append(play_event)
            outcomes[play_event["effect_id"]] = play_event["outcome"]
    # package 6 (Core 411.1): an each_player copy's game actions are the iteration player's -
    # "Each player kills one of their units": each is responsible for their own unit's death
    for entry in trace:
        if isinstance(entry, dict) and entry.get("effect_id") in copy_players:
            entry["performed_by"] = copy_players[entry["effect_id"]]
    log = game_events.EventLog(program.get("program_id"), actor=program.get("controller"),
                               source_object=program.get("source_object"))
    for position, entry in enumerate(trace):
        after_snapshot = snapshots[position + 1] if position + 1 < len(snapshots) else game_events.snapshot(current)
        try:
            log.record(snapshots[position], after_snapshot, entry)
        except game_events.EventKindUnknown as exc:
            # Fail closed: the instruction ran, but the engine will not hand
            # back a state whose events it cannot name (ADR-0014 §1).
            return {**base, "valid": True, "committed": False, "unsupported": True,
                    "reason_code": exc.reason_code, "reason": str(exc), "trace": trace}
    reveals_ended = 0
    if _replacement_depth == 0 and current.get("reveals"):
        # Core 424.3.a: a reveal / look lasts until this resolution finishes.
        reveals_ended = len(current["reveals"])
        del current["reveals"]
    return {
        **base,
        "valid": True,
        "committed": True,
        "unsupported": False,
        "conditional_triggers": copy.deepcopy(program.get("conditional_triggers", [])),
        **({"mode": mode} if mode is not None else {}),
        **({"repeat": repeat_meta} if repeat_meta is not None else {}),
        **({"reveals_ended": reveals_ended} if reveals_ended else {}),
        # selection-binding.v1: what this program's later clauses were allowed
        # to refer to, in the artifact rather than only in the engine's head.
        **({"selection_bindings": copy.deepcopy(selection_bindings)} if selection_bindings else {}),
        **({"countered_chain_items": [i for e in trace for i in e.get("countered_chain_items", [])]} if any(e.get("countered_chain_items") for e in trace) else {}),
        # package 11 (Mystic Reversal): the Chain items whose control changed, for the timing chain
        **({"controlled_chain_items": [i for e in trace for i in e.get("controlled_chain_items", [])]} if any(e.get("controlled_chain_items") for e in trace) else {}),
        "next_state": current,
        "next_state_hash": hash_value(current),
        "trace": trace,
        "events": log.events,
        "event_coverage": log.problems or "complete",
        "pending_triggers": [trigger for event in trace for trigger in event.get("pending_triggers", [])],
        "terminal_event": terminal,
        # 2026-09-28 (package 6): the effect-driven plays this program started (Core 354, 419.3) - each
        # card now on the Chain awaiting its play's steps 2 to 5, for the resolution bridge to put on
        # the timing Chain as a Pending item (354.2)
        **({"limited_plays": [{"chain_item_id": e["chain_item_id"], "card": e["object_id"],
                               "controller": e["controller"], "object_kind": e["object_kind"]}
                              for e in trace if e.get("op") == "limited_play" and e.get("outcome") == "applied"]}
           if any(e.get("op") == "limited_play" and e.get("outcome") == "applied" for e in trace) else {}),
    }


def _start_limited_play(state: dict[str, Any], cost_basis: dict[str, Any], target: dict[str, Any],
                        program: dict[str, Any], effect_id: str, entry: dict[str, Any] | None = None,
                        player: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Step 1 of an effect-driven play (Core 354, 419.3): the card leaves its zone for the Chain as a
    Pending item, a new object (Core 124). The record on the chain entry says who granted the play,
    where the card came from - so a play cancelled at its legality check can be undone (358.5) - and
    what the effect changes about its cost (356.1.b). The card's cost is read off its printed cost
    (Core 206); a card whose printed cost the state does not carry is refused by name, never guessed."""
    card = target["object_id"]
    obj = state["objects"][card]
    printed = obj.get("printed_cost")
    if not isinstance(printed, dict):
        raise NotImplementedError(f"the printed cost of {card!r} is not observed; an effect-driven play determines its "
                                  f"cost from it (Core 206, 356.1) and does not guess it")
    location = find_location(state, card)
    if location is None or location[0] != "player":
        raise NotImplementedError(f"{card!r} is not in a player's zone; an effect-driven play takes it from one")
    zone_owner, zone = location[1], location[2]
    # "If it's a unit, play it here." - "here" is read as this instruction executes (Core 359.3.f.2), before the card
    # is touched. 2026-10-12 (GPT PACKAGE11 ruling 2, replacing PACKAGE8 ruling 3's named refusal): a source gone, a new
    # object, or at no Battlefield - its Base included - gives no "here"; the check reads null (359.3.e.12) and the
    # unit branch cannot be followed, so it is ignored (359.3.e.6). The card stays where it was; what the ability's
    # controller paid to put it on the Chain stays paid; nothing is put elsewhere instead. A program that declares no
    # source to read is a malformed program, refused by name as before
    here = None
    if entry is not None and entry.get("kind") == "unit_at_source_battlefield" and obj["kind"] == "unit":
        try:
            here = resolve_location_ref({"kind": "program_source_current_battlefield"}, state, program)
        except SourceUnavailable as exc:
            return state, {"op": "limited_play", "outcome": SOURCE_UNAVAILABLE_OUTCOME, "completion": "none",
                           "object_id": card, "object_kind": obj["kind"], "reason": "limited_play_here_absent",
                           "reason_code": exc.reason_code, "message": str(exc), "card_stays": [zone_owner, zone],
                           "source_object": program.get("source_object"),
                           "rule_locators": ["Core 359.3.f.2", "Core 359.3.e.12", "Core 359.3.e.6"]}
        except SelectionBindingRefused as exc:
            raise NotImplementedError(
                f"limited_play_here_unreadable: the effect plays the unit {card!r} 'here', and the program gives no "
                f"source to read it from ({exc.reason_code})") from exc
    # 2026-10-13 package 11 (Mageseeker Warden, GPT ruling 17, Core 358.3.a): the effect still resolves; a unit it would
    # play to a Battlefield its player may not play units to is not played - the card stays where it was
    plays_as = obj["owner"] if player == "owner" else program.get("controller")
    if here is not None and obj["kind"] == "unit":
        blocked = battlefield_restriction(state, "opponent_units_to_base_only", plays_as)
        if blocked is not None:
            return state, {"op": "limited_play", "outcome": "no_op", "completion": "none", "object_id": card,
                           "object_kind": obj["kind"], "reason": "limited_play_units_to_base_only",
                           "prevented_by": blocked, "card_stays": [zone_owner, zone],
                           "source_object": program.get("source_object"),
                           "rule_locators": ["Core 358.3.a", "Core 355.2"]}
    working = copy.deepcopy(state)
    ids = working["players"][zone_owner]["zones"][zone]
    zone_index = ids.index(card)
    identity_before = object_identity(working, card) or f"{card}@0"
    ids.remove(card)
    # package 9: "its owner plays it" - the card's owner is the player who plays it (Core 127.1, 419.1)
    controller = obj["owner"] if player == "owner" else program.get("controller")
    item_id = f"limited-play:{program.get('program_id')}:{effect_id}"
    serial = 1
    while item_id in (working.get("chain_items") or {}):
        serial += 1
        item_id = f"limited-play:{program.get('program_id')}:{effect_id}:{serial}"
    record = {"granted_by": program.get("source_object") or program.get("program_id"),
              "program_id": program.get("program_id"), "effect_id": effect_id, "source_zone": zone,
              "zone_owner": zone_owner, "zone_index": zone_index, "identity_before": identity_before,
              "controller_before": working["objects"][card]["controller"], "cost_basis": copy.deepcopy(cost_basis)}
    working.setdefault("chain_items", {})[item_id] = {"card": card, "controller": controller, "limited_play": record}
    # the player who plays a card controls it on the Chain (Core 419.1); its owner does not change
    working["objects"][card]["controller"] = controller
    identity_after = _bump_identity(working, card)
    # 2026-09-28 (package 6, step 2): "If it's a unit, play it here." - the effect names where the unit it
    # plays enters (Core 355.2.b): the source's Battlefield as this instruction executes (359.3.f.2), read above.
    # The card's other branch (a non-unit) is not touched: it enters where it would.
    entry_note = None
    if entry is not None and entry.get("kind") == "unit_at_players_base" and obj["kind"] == "unit":
        # package 9 (Portal Rescue): "to their base" - the Base of the player who plays it (Core 355.2.b); nothing to
        # choose, and a Battlefield is not where the card says
        record["entry_location"] = {"kind": "base"}
        entry_note = {"entry_location": {"kind": "base"}, "player": controller, "rule_locators": ["Core 355.2.b"]}
    elif entry is not None and obj["kind"] == "unit":
        record["entry_location"] = {"kind": "battlefield", "battlefield": here}
        entry_note = {"entry_location": dict(record["entry_location"]), "rule_locators": ["Core 355.2.b", "Core 359.3.f.2"]}
    kind = cost_basis["kind"]
    event = {"op": "limited_play", "outcome": "applied", "completion": "full", "object_id": card,
             "chain_item_id": item_id, "controller": controller, "object_kind": obj["kind"],
             "identity_before": identity_before, "identity_after": identity_after,
             "play_started": copy.deepcopy(record), "play_completes_at": "finalization",
             **({"entry": entry_note} if entry_note is not None else {}),
             "rule_locators": list(OP_RULES["limited_play"]) + [LIMITED_PLAY_COST_BASES[kind]]}
    return working, event


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Chronicle typed Riftbound effect IR")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect-state")
    inspect.add_argument("state", type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("state", type=Path)
    apply.add_argument("program", type=Path)
    args = parser.parse_args()
    try:
        state = _load(args.state)
        if args.command == "inspect-state":
            errors = validate_state(state)
            output = {"valid": not errors, "errors": errors, "state_hash": hash_value(state)}
        else:
            output = apply_program(state, _load(args.program))
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output.get("valid") else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
