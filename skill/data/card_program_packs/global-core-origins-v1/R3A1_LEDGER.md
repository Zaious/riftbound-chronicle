# R3-A1 clause ledger — choices, costs, zones

Package C-13. 11 cards, 12 clauses, 48 fixture drafts, 11 decision packets. 8 clauses target under Core 355.10; decision points: {'at_play': 9, 'at_resolution': 2, 'at_trigger_finalization': 0, 'none': 1}.

Sources: Core Rules 2026-07-16 (installed locally, quoted); Origins errata 2025-10-28; Origins FAQ 2025-10-16 is locally captured as **superseded historical evidence** and excluded from default queries (DP-11).

Nothing here is a ruling. Every classification is input to X-09; every fixture draft omits the expected result by construction.

## Disintegrate — Spell · `ogn-005-298` · stale snapshot
### `d3d94631` Deal 3 to a unit at battlefield.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: deal_damage · packets: DP-01, DP-03
- why: 355.5 specific object choice at play; 355.10.b 'at battlefield' is a restriction, the unit is the target
  - `Core 355.5` — If a card requires you to specifically choose one or more Game Objects, that choice is made now.
  - `Core 355.8` — In order to put a spell or ability on the chain, valid choices must be made for all targets.
  - `Core 355.9.b` — It meets all targeting restrictions. e.g., a unit is a valid target for a spell that refers to a 'unit at a battlefield' only if it meets the appropriate criteria.
  - `Core 355.10.b` — 'Kill a unit at a battlefield' targets a unit, but not a battlefield, because the units are targets and 'at a battlefield' is a restriction.
  - `Core 359.3.e.5` — If any of the spell's targets are no longer legal, those game objects are unaffected by the spell as it resolves.
  - `Core 417.1.b` — To Deal Damage to Units, mark the specified amount of Damage on the Unit.
  - `Core 417.6.a` — If a game effect does not specify a source, the game effect describing the Deal action is the source.
  - `errata: Disintegrate OGN-005` — Deal 3 to a unit at battlefield. If this kills it, do this: draw 1.

## Flash — Spell · `ogs-011-024`
### `7a92a690` Move up to 2 friendly units to base.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: move_board_object · packets: DP-01, DP-02, DP-06
- why: 355.4 move destinations chosen at play; 355.13 'up to' may choose zero; 355.12 each chosen unit is a target
  - `Core 355.4` — For Spells and Abilities that Move one or more Units, choose a valid Location as the Move Destination for each Move that will be performed.
  - `Core 355.4.a` — A valid Location for a Move Effect is one other than the Units' current Location where they are allowed to be present.
  - `Core 355.13` — If a card specifies that a player chooses 'any number' or 'up to' some number of Game Objects to be affected, they may choose any number of available targets, including zero.
  - `Core 446.3.c` — Moving does not use the Chain, nor is it able to be Reacted to.
  - `Core 449.1` — The source of the Move will provide details on any restrictions on legality for Destination.
  - `Core 453` — When a Move action is complete, perform a Cleanup.

## Gentlemen's Duel — Spell · `ogs-008-024`
### `2ed49f33` Give a friendly unit +3 :rb_might: this turn.
- targets: **yes** · decision point: **at_play** · needs: target_choice, duration_expiry · ops: modify_might · packets: DP-01, DP-03
- why: friendly-unit choice at play; duration 'this turn' is R3-A2 but the target is A1
  - `Core 355.5` — If a card requires you to specifically choose one or more Game Objects, that choice is made now.
  - `Core 355.9.b` — A unit is a valid target for a spell that refers to a 'unit you control' only if it meets the appropriate criteria.
  - `Core 359.3.e.2` — A target is illegal as the spell resolves if it no longer meets the targeting requirements of the spell.
  - `Core 135.2.e.3` — (Might modifier accounting, as effect_ir already cites for modify_might)

### `fd48e5d0` Then choose an enemy unit.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: — · packets: DP-01, DP-03
- why: a second, independent target chosen at play (355.5); 'Then' orders execution, not the choice
  - `Core 355.5` — If a card requires you to specifically choose one or more Game Objects, that choice is made now.
  - `Core 355.16` — A player may not make choices during this step that will deterministically result in illegal choices or actions later in this process unless they have no choice.
  - `Core 359.3.e.7` — If all of an instruction's Targets become Invalid or Unavailable by the time the spell begins resolving, that instruction will not execute.

## Gust — Spell · `ogn-169-298`
### `e661650e` Return a unit at a battlefield with 3 :rb_might: or less to its owner's hand.
- targets: **yes** · decision point: **at_play** · needs: return_board_to_hand, target_choice · ops: — · packets: DP-01, DP-03, DP-06
- why: targeted choice with two restrictions; returning to hand is a zone change, not a Move (446.2), and the object becomes new (124)
  - `Core 355.9.b` — A unit is a valid target for a spell that refers to a 'unit with Might 4 or greater' only if it meets the appropriate criteria.
  - `Core 359.3.e.4` — A unit with 3 or less Might is no longer a legal target if it is no longer a unit or if its Might is greater than 3.
  - `Core 446.2` — A card changing game zones does not in itself constitute a Move.
  - `Core 124` — A Game Object that changes zones to or from a Non-Board Zone becomes a new object for the purposes of tracking that object.
  - `Core 124.1` — Whenever a Game Object changes zones to or from a Non-Board Zone, all Temporary Modifications of all kinds cease to be tracked on it.
  - `Core 056` — Cards a player owns may never be placed into a non-Board zone belonging to another player.

## Highlander — Spell · `ogs-020-024` · stale snapshot
### `d659b2ba` Choose a friendly unit.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: — · packets: DP-01, DP-03, DP-06
- why: 355.10.c's own example: 'Choose a friendly unit. The next time it would die this turn…' targets a friendly unit, because 'choose' is not part of the replacement effect
  - `Core 355.10.c` — 'Choose a friendly unit. The next time it would die this turn, return it to your hand instead' targets a friendly unit, because 'choose a friendly unit' is not part of the replacement effect.
  - `Core 355.5` — If a card requires you to specifically choose one or more Game Objects, that choice is made now.
  - `Core 359.3.e.5` — Any instructions related to an illegal target can't be followed.
  - `Core 455` — A Recall is when a Permanent is relocated from anywhere to its Base without it being a Move.
  - `Core 456.1` — They do not cause Triggered Abilities to trigger that are triggered by Move actions.
  - `errata: Highlander OGS-020` — Choose a friendly unit. The next time it would die this turn, heal it, exhaust it, and recall it instead.

## Incinerate — Spell · `ogs-003-024`
### `df9db2ea` Deal 2 to a unit at a battlefield.
- targets: **yes** · decision point: **at_play** · needs: target_choice · ops: deal_damage · packets: DP-01, DP-03
- why: same shape as Disintegrate without the linked instruction
  - `Core 355.5` — If a card requires you to specifically choose one or more Game Objects, that choice is made now.
  - `Core 355.10.b` — 'Kill a unit at a battlefield' targets a unit, but not a battlefield.
  - `Core 359.3.e.2` — A target is illegal as the spell resolves if it no longer meets the targeting requirements of the spell, or if it has changed Zones to or from a Non-Board Zone.
  - `Core 417.1.b` — To Deal Damage to Units, mark the specified amount of Damage on the Unit.

## Meditation — Spell · `ogn-048-298`
### `6ce549b5` As an additional cost to play this, you may exhaust a friendly unit.
- targets: **no** · decision point: **at_play** · needs: optional_additional_cost · ops: exhaust · packets: DP-02, DP-04, DP-05
- why: 355.1.a the choice to pay an optional additional cost is made at play; 355.10.c a cost does not target; 356.2.b/357.2 paid in step 4; 414.4 an exhausted unit cannot pay it
  - `Core 355.1.a` — This includes the choice of whether or not to pay an Optional Additional Cost.
  - `Core 355.10.c` — 'As an additional cost to play me, kill a friendly unit' doesn't target anything.
  - `Core 204.2.a` — Additional Costs must be paid to finalize the spell or ability, in addition to the base cost.
  - `Core 356.2.b.1` — Optional Costs … must be paid only if the player made the choice to pay them in step 2. They use the phrase 'as an additional cost' and the word 'may.'
  - `Core 356.4.f.1` — An optional additional cost was 'paid' if the player made the decision to pay it. It doesn't matter how much the player actually paid.
  - `Core 357.2` — In addition, pay any non-standard Cost summed in step 3 in any order.
  - `Core 357.2.a` — Costs that are replaced with other events by replacement effects are still considered paid.
  - `Core 414.4` — An exhausted friendly unit may not be exhausted again as the additional cost for the spell, and the additional cost has not been paid.
  - `Core 358.2` — Check that all costs were paid.
  - `Core 358.5` — If any of the above checks fail, the actions taken in this process are undone and the action is cancelled.
  - `Core 205` — An instruction that requires a player to pay resources … that does not also have a linked Effect, is not a Cost.

## Mobilize — Spell · `ogn-134-298`
### `3e791d2d` Channel 1 rune exhausted.
- targets: **no** · decision point: **none** · needs: channel_rune · ops: — · packets: DP-05, DP-08
- why: 430.1 channel takes the top rune (no choice); 430.2 the effect specifies entry state; 430.3 channel as many as possible
  - `Core 430.1` — Channeling is the action of taking one or more Runes from the top of a player's Rune Deck and putting them on the board.
  - `Core 430.2` — A spell reads 'Channel 1 rune exhausted.' As that spell resolves, its controller puts the top rune of their rune deck onto the board and that rune enters the board exhausted rather than ready.
  - `Core 430.3` — If there aren't sufficient runes in the Rune Deck, channel as many as possible.
  - `Core 430.5` — e.g., 'Channel 2 runes exhausted. If you couldn't channel 2 runes this way, draw 1.'
  - `Core 161.1.a` — despite remaining on the Board until Recycled or otherwise removed from the board, it is not a Permanent.

## Morbid Return — Spell · `ogn-170-298`
### `f3c76e58` Return a unit from your trash to your hand.
- targets: **yes** · decision point: **at_play** · needs: return_trash_to_hand, target_choice · ops: — · packets: DP-01, DP-03, DP-06
- why: 355.10.a: trash is Public, so a unit card in it is a target (the rule's own example)
  - `Core 355.9.a` — e.g., 'Recycle a unit from your trash' targets a unit card in your trash.
  - `Core 355.10.a` — 'Return a unit from your trash to your hand' targets a unit card in your trash, because your trash is Public.
  - `Core 355.10.a.1` — Public zones are Battlefield Zones, Bases, Trashes, Legend Zones, Champion Zones, and Facedown Zones.
  - `Core 359.3.e.2` — A target is illegal as the spell resolves if it has changed Zones to or from a Non-Board Zone.
  - `Core 108.2.c` — Cards in each player's Trash are unordered.

## Mystic Poro — Unit · `ogn-171-298`
### `f4a07c4d` [Vision]
- targets: **no** · decision point: **at_resolution** · needs: look, play_and_move_triggers · ops: recycle_one · packets: DP-02, DP-07
- why: 817.1.b Vision is a triggered ability short for 'When this is played, predict'; 436 the recycle choice is made as Predict executes; the top card is Secret (128.3) and does not target (355.10.a)
  - `Core 817.1.b` — It is functionally short for 'When this is played, predict.'
  - `Core 817.1.c` — The trigger is the permanent entering the Board.
  - `Core 817.2.a` — The player may choose to recycle or not recycle for each instance of Vision separately.
  - `Core 436.1` — Predicting a card is the act of looking at a single card from the top of the Main Deck and choosing whether or not to Recycle it.
  - `Core 436.4` — If a player attempts to Predict more cards than are available in their Main Deck, they will Predict as many as possible instead.
  - `Core 128.3` — Secret: This level of Privacy indicates that no player may read or look at the face of the card.
  - `Core 355.5.b` — This does not include making choices for Triggered Abilities of permanents, even if those abilities trigger when the chain item is played.

## Sai Scout — Unit · `ogn-174-298`
### `f4a07c4d` [Vision]
- targets: **no** · decision point: **at_resolution** · needs: look, play_and_move_triggers · ops: recycle_one · packets: DP-02, DP-07
- why: 817.1.b Vision is a triggered ability short for 'When this is played, predict'; 436 the recycle choice is made as Predict executes; the top card is Secret (128.3) and does not target (355.10.a)
  - `Core 817.1.b` — It is functionally short for 'When this is played, predict.'
  - `Core 817.1.c` — The trigger is the permanent entering the Board.
  - `Core 817.2.a` — The player may choose to recycle or not recycle for each instance of Vision separately.
  - `Core 436.1` — Predicting a card is the act of looking at a single card from the top of the Main Deck and choosing whether or not to Recycle it.
  - `Core 436.4` — If a player attempts to Predict more cards than are available in their Main Deck, they will Predict as many as possible instead.
  - `Core 128.3` — Secret: This level of Privacy indicates that no player may read or look at the face of the card.
  - `Core 355.5.b` — This does not include making choices for Triggered Abilities of permanents, even if those abilities trigger when the chain item is played.
