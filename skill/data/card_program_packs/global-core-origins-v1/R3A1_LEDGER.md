# R3-A1 clause ledger — choices, costs, zones

Package C-13. 11 cards, 12 clauses, 48 fixture drafts, 11 decision packets. 8 clauses target under Core 355.10; decision points: {'at_play': 9, 'at_resolution': 2, 'at_trigger_finalization': 0, 'none': 1}.

Sources: Core Rules 2026-07-16 (cited by locator, summarized in the engine's own words); Origins errata 2025-10-28; Origins FAQ 2025-10-16 is locally captured as **superseded historical evidence** and excluded from default queries (DP-11).

Nothing here is a ruling. Every classification is input to X-09; every fixture draft omits the expected result by construction.

## Disintegrate — Spell · `ogn-005-298` · stale snapshot
### `d3d94631` Deal 3 to a unit at battlefield.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: deal_damage · packets: DP-01, DP-03
- why: 355.5 specific object choice at play; 355.10.b 'at battlefield' is a restriction, the unit is the target
  - `Core 355.5` — Choices of specific Game Objects are made in this step of playing.
  - `Core 355.8` — Every target needs a valid choice before the spell or ability can go on the Chain.
  - `Core 355.9.b` — A target must satisfy every restriction the text puts on it (the rule's example is a unit 'at a battlefield').
  - `Core 355.10.b` — In 'kill a unit at a battlefield' the unit is the target; the battlefield only restricts it.
  - `Core 359.3.e.5` — Targets gone illegal by resolution are left untouched by the spell.
  - `Core 417.1.b` — Damage dealt to a Unit is marked on it.
  - `Core 417.6.a` — With no source named, the effect doing the dealing counts as the source.
  - `errata: Disintegrate OGN-005` — Deal 3 to a unit at battlefield. If this kills it, do this: draw 1.

## Flash — Spell · `ogs-011-024`
### `7a92a690` Move up to 2 friendly units to base.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: move_board_object · packets: DP-01, DP-02, DP-06
- why: 355.4 move destinations chosen at play; 355.13 'up to' may choose zero; 355.12 each chosen unit is a target
  - `Core 355.4` — A spell or ability that Moves Units picks a legal destination for each Move it will make.
  - `Core 355.4.a` — A legal Move destination is a Location the Units may be in, other than where they already are.
  - `Core 355.13` — 'Up to N' or 'any number' lets the player pick anything from zero to the limit.
  - `Core 446.3.c` — A Move does not go on the Chain and cannot be responded to.
  - `Core 449.1` — Limits on where a Move may go come from whatever caused the Move.
  - `Core 453` — A finished Move is followed by a Cleanup.

## Gentlemen's Duel — Spell · `ogs-008-024`
### `2ed49f33` Give a friendly unit +3 :rb_might: this turn.
- targets: **yes** · decision point: **at_play** · needs: target_choice, duration_expiry · ops: modify_might · packets: DP-01, DP-03
- why: friendly-unit choice at play; duration 'this turn' is R3-A2 but the target is A1
  - `Core 355.5` — Choices of specific Game Objects are made in this step of playing.
  - `Core 355.9.b` — A target must meet the criteria the text states (the rule's example is a unit its player controls).
  - `Core 359.3.e.2` — A target that no longer fits the spell's targeting requirements is illegal at resolution.
  - `Core 135.2.e.3` — (Might modifier accounting, as effect_ir already cites for modify_might)

### `fd48e5d0` Then choose an enemy unit.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: — · packets: DP-01, DP-03
- why: a second, independent target chosen at play (355.5); 'Then' orders execution, not the choice
  - `Core 355.5` — Choices of specific Game Objects are made in this step of playing.
  - `Core 355.16` — Choices here may not force an illegal choice or action later in the process, unless there is no alternative.
  - `Core 359.3.e.7` — An instruction whose every target is Invalid or Unavailable when resolution begins does not execute.

## Gust — Spell · `ogn-169-298`
### `e661650e` Return a unit at a battlefield with 3 :rb_might: or less to its owner's hand.
- targets: **yes** · decision point: **at_play** · needs: return_board_to_hand, target_choice · ops: — · packets: DP-01, DP-03, DP-06
- why: targeted choice with two restrictions; returning to hand is a zone change, not a Move (446.2), and the object becomes new (124)
  - `Core 355.9.b` — A target must meet the criteria the text states (the rule's example is a Might threshold).
  - `Core 359.3.e.4` — A unit chosen as having 3 Might or less stops being legal if its Might goes above 3 or it stops being a unit.
  - `Core 446.2` — Changing zones is not, by itself, a Move.
  - `Core 124` — An object entering or leaving a Non-Board Zone is tracked as a new object.
  - `Core 124.1` — That zone change drops every Temporary Modification on it.
  - `Core 056` — A card never goes to a non-Board zone of a player other than its owner.

## Highlander — Spell · `ogs-020-024` · stale snapshot
### `d659b2ba` Choose a friendly unit.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: — · packets: DP-01, DP-03, DP-06
- why: 355.10.c's own example: 'Choose a friendly unit. The next time it would die this turn…' targets a friendly unit, because 'choose' is not part of the replacement effect
  - `Core 355.10.c` — The rule's example: the 'choose a friendly unit' that precedes a replacement effect is a target, because the choice is not part of the replacement.
  - `Core 355.5` — Choices of specific Game Objects are made in this step of playing.
  - `Core 359.3.e.5` — Instructions tied to an illegal target are not followed.
  - `Core 455` — A Recall puts a Permanent into its Base from anywhere, and is not a Move.
  - `Core 456.1` — Recalls do not trigger abilities that watch for Moves.
  - `errata: Highlander OGS-020` — Choose a friendly unit. The next time it would die this turn, heal it, exhaust it, and recall it instead.

## Incinerate — Spell · `ogs-003-024`
### `df9db2ea` Deal 2 to a unit at a battlefield.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: deal_damage · packets: DP-01, DP-03
- why: same shape as Disintegrate without the linked instruction
  - `Core 355.5` — Choices of specific Game Objects are made in this step of playing.
  - `Core 355.10.b` — Only the unit is targeted; 'at a battlefield' restricts which unit.
  - `Core 359.3.e.2` — At resolution a target is illegal once it fails the targeting requirements or has gone to or come from a Non-Board Zone.
  - `Core 417.1.b` — Damage dealt to a Unit is marked on it.

## Meditation — Spell · `ogn-048-298`
### `6ce549b5` As an additional cost to play this, you may exhaust a friendly unit.
- targets: **no** · decision point: **at_play** · needs: optional_additional_cost · ops: exhaust · packets: DP-02, DP-04, DP-05
- why: 355.1.a the choice to pay an optional additional cost is made at play; 355.10.c a cost does not target; 356.2.b/357.2 paid in step 4; 414.4 an exhausted unit cannot pay it
  - `Core 355.1.a` — Deciding whether to pay an Optional Additional Cost happens in this step.
  - `Core 355.10.c` — The rule's example: an additional cost that kills a friendly unit targets nothing.
  - `Core 204.2.a` — Additional Costs are paid on top of the base cost to finalize the spell or ability.
  - `Core 356.2.b.1` — Optional Costs are paid only if chosen in step 2; their wording pairs 'as an additional cost' with 'may'.
  - `Core 356.4.f.1` — An optional additional cost counts as paid once the player chose to pay it, whatever amount was actually paid.
  - `Core 357.2` — Non-standard costs totalled in step 3 are paid as well, in any order.
  - `Core 357.2.a` — A cost replaced by another event still counts as paid.
  - `Core 414.4` — The rule's example: a friendly unit that is already exhausted cannot be exhausted to pay the additional cost, so that cost goes unpaid.
  - `Core 358.2` — Confirm every cost was paid.
  - `Core 358.5` — If a check fails, everything done in the process is undone and the action cancelled.
  - `Core 205` — A resource-paying instruction with no linked Effect is not a Cost.

## Mobilize — Spell · `ogn-134-298`
### `3e791d2d` Channel 1 rune exhausted.
- targets: **no** · decision point: **none** · needs: channel_rune · ops: — · packets: DP-05, DP-08
- why: 430.1 channel takes the top rune (no choice); 430.2 the effect specifies entry state; 430.3 channel as many as possible
  - `Core 430.1` — Channel: take Runes from the top of the Rune Deck and put them onto the board.
  - `Core 430.2` — The rule's example: 'Channel 1 rune exhausted' puts the top rune onto the board exhausted instead of ready.
  - `Core 430.3` — Too few runes in the Rune Deck: channel all that are there.
  - `Core 430.5` — The rule's example pairs a two-rune channel with a draw if fewer than two could be channeled.
  - `Core 161.1.a` — A rune is not a Permanent, even though it stays on the Board until Recycled or removed.

## Morbid Return — Spell · `ogn-170-298`
### `f3c76e58` Return a unit from your trash to your hand.
- targets: **yes** · decision point: **at_play** · needs: return_trash_to_hand, target_choice · ops: — · packets: DP-01, DP-03, DP-06
- why: 355.10.a: trash is Public, so a unit card in it is a target (the rule's own example)
  - `Core 355.9.a` — The rule's example: recycling a unit from your trash targets that card.
  - `Core 355.10.a` — A unit card in your trash can be a target because the trash is Public.
  - `Core 355.10.a.1` — Public zones: Trashes, Bases, Battlefield Zones, Facedown Zones, and the Legend and Champion Zones.
  - `Core 359.3.e.2` — A target that has entered or left a Non-Board Zone is illegal at resolution.
  - `Core 108.2.c` — Trash contents have no order.

## Mystic Poro — Unit · `ogn-171-298`
### `f4a07c4d` [Vision]
- targets: **no** · decision point: **at_resolution** · needs: look, play_and_move_triggers · ops: recycle_one · packets: DP-02, DP-07
- why: 817.1.b Vision is a triggered ability short for 'When this is played, predict'; 436 the recycle choice is made as Predict executes; the top card is Secret (128.3) and does not target (355.10.a)
  - `Core 817.1.b` — Vision stands for a trigger that predicts when the card is played.
  - `Core 817.1.c` — It triggers on the permanent entering the Board.
  - `Core 817.2.a` — With several Vision instances, the recycle choice is made separately for each.
  - `Core 436.1` — To Predict is to look at the Main Deck's top card and decide whether to Recycle it.
  - `Core 436.4` — Predicting more cards than the Main Deck holds predicts all that remain.
  - `Core 128.3` — Secret: nobody may look at the card's face.
  - `Core 355.5.b` — Choices for permanents' Triggered Abilities are not made here, even when playing the item is what triggers them.

## Sai Scout — Unit · `ogn-174-298`
### `f4a07c4d` [Vision]
- targets: **no** · decision point: **at_resolution** · needs: look, play_and_move_triggers · ops: recycle_one · packets: DP-02, DP-07
- why: 817.1.b Vision is a triggered ability short for 'When this is played, predict'; 436 the recycle choice is made as Predict executes; the top card is Secret (128.3) and does not target (355.10.a)
  - `Core 817.1.b` — Vision stands for a trigger that predicts when the card is played.
  - `Core 817.1.c` — It triggers on the permanent entering the Board.
  - `Core 817.2.a` — With several Vision instances, the recycle choice is made separately for each.
  - `Core 436.1` — To Predict is to look at the Main Deck's top card and decide whether to Recycle it.
  - `Core 436.4` — Predicting more cards than the Main Deck holds predicts all that remain.
  - `Core 128.3` — Secret: nobody may look at the card's face.
  - `Core 355.5.b` — Choices for permanents' Triggered Abilities are not made here, even when playing the item is what triggers them.
