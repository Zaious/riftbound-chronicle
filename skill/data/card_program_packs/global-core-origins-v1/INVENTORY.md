# R3-A0 inventory — Annie and Master Yi

Generated from `selection.json` (global-core-origins-v1-selection-2026-09-03), the bundled card snapshot, and errata verified 2026-08-17. Draft only: no programs, no activation.

34 cards, 56 clauses. 4 cards carry pre-errata text in the snapshot; 2 have no rules text; 0 clauses matched no mechanic rule; 1 errata entries are unreachable by the catalog's name join.

## Findings for the overlay owner

- **Annie - Dark Child (Starter)**: errata `Dark Child, Starter` (card_ids ['OGN-?']) is reachable only via `subtitle`. Deck Coach's catalog applies errata by name only, so it reads this card's pre-errata text; fix the overlay entry's official_name or card_ids.

## What unblocks how many cards

| Batch | Cards |
| --- | --- |
| `E0` | 9 — Cannon Barrage, Confront, En Garde, Flash, Gentlemen's Duel, Gust, Incinerate, Meditation, Morbid Return |
| `R3-A1-choices-costs-zones` | 11 — Disintegrate, Flash, Gentlemen's Duel, Gust, Highlander, Incinerate, Meditation, Mobilize, Morbid Return, Mystic Poro, Sai Scout |
| `R3-A2-play-conditions-continuous` | 19 — Annie - Dark Child (Starter), Annie - Fiery, Annie - Stubborn, Confront, Disintegrate, En Garde, Firestorm, Highlander, Maddened Marauder, Master Yi - Honed, Master Yi - Meditative, Mobilize, Pouty Poro, Sai Scout, Sneaky Deckhand, Stormclaw Ursine, Tibbers, Traveling Merchant, Void Gate |
| `R3-A3-combat` | 12 — Cannon Barrage, Fortified Position, Gentlemen's Duel, Maddened Marauder, Master Yi - Honed, Master Yi - Wuju Bladesman (Starter), Mountain Drake, Playful Phantom, Stalwart Poro, Stormclaw Ursine, Wielder of Water, Zephyr Sage |

## Cards by mechanic

| Mechanic | Cards |
| --- | --- |
| `action_reaction_timing` | Cannon Barrage, Confront, En Garde, Flash, Gentlemen's Duel, Gust, Incinerate, Meditation, Morbid Return |
| `area_damage_in_combat` | Cannon Barrage |
| `area_targets` | Cannon Barrage, Firestorm, Tibbers |
| `attacking_defending_alone` | Master Yi - Wuju Bladesman (Starter), Wielder of Water |
| `bonus_damage` | Annie - Fiery, Void Gate |
| `channel_rune` | Mobilize, Stormclaw Ursine |
| `combat_state` | Cannon Barrage, Fortified Position, Maddened Marauder, Master Yi - Honed, Master Yi - Wuju Bladesman (Starter), Mountain Drake, Playful Phantom, Stalwart Poro, Stormclaw Ursine, Wielder of Water, Zephyr Sage |
| `conditional_effects` | Disintegrate, En Garde, Mobilize |
| `conditional_might` | Master Yi - Meditative, Master Yi - Wuju Bladesman (Starter), Wielder of Water |
| `continuous_effects` | Master Yi - Meditative, Master Yi - Wuju Bladesman (Starter), Wielder of Water |
| `deflect` | Pouty Poro |
| `discard` | Traveling Merchant |
| `duration_expiry` | En Garde, Fortified Position, Gentlemen's Duel |
| `end_of_turn_trigger` | Annie - Dark Child (Starter) |
| `enter_ready` | Confront, Master Yi - Honed |
| `ganking` | Master Yi - Honed |
| `if_cannot_fallback` | Mobilize |
| `linked_instruction` | Disintegrate |
| `look` | Mystic Poro, Sai Scout |
| `mutual_damage_equal_might` | Gentlemen's Duel |
| `next_death_replacement` | Highlander |
| `open_battlefield_play` | Sai Scout, Sneaky Deckhand |
| `optional_additional_cost` | Meditation |
| `play_and_move_triggers` | Annie - Stubborn, Fortified Position, Maddened Marauder, Mystic Poro, Sai Scout, Stormclaw Ursine, Tibbers, Traveling Merchant |
| `play_lifecycle` | Annie - Stubborn, Maddened Marauder, Sai Scout, Sneaky Deckhand, Stormclaw Ursine, Tibbers |
| `recall` | Highlander |
| `return_board_to_hand` | Gust |
| `return_trash_to_hand` | Annie - Stubborn, Morbid Return |
| `shield` | Fortified Position, Stalwart Poro, Zephyr Sage |
| `tank` | Maddened Marauder, Stormclaw Ursine |
| `target_choice` | Annie - Stubborn, Disintegrate, En Garde, Flash, Fortified Position, Gentlemen's Duel, Gust, Highlander, Incinerate, Maddened Marauder, Morbid Return |
| `vanilla_unit_combat_state` | Mountain Drake, Playful Phantom |

## proving-grounds-annie

### Annie - Dark Child (Starter) — Legend · `ogs-017-024` · **STALE snapshot** (pre-errata wording withheld; see inventory_ledger.json) · **catalog errata join missed** (reached via `subtitle`) · errata: origins (live-fetched)
- `223039b2` At the end of your turn, ready up to 2 runes.
  needs: end_of_turn_trigger · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **stale** — bundled snapshot still carries pre-errata wording; reverify text before any program

### Annie - Fiery — Unit · `ogs-001-024`
- `24035ea0` Your spells and abilities deal 1 Bonus Damage.
  needs: bonus_damage · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['bonus_damage']

### Annie - Stubborn — Unit · `ogs-010-024`
- `5086e61a` When you play me, return a spell from your trash to your hand.
  needs: return_trash_to_hand, target_choice, play_and_move_triggers, play_lifecycle · ops: emit_reflexive · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['emit_reflexive'] exist; blocked on ['return_trash_to_hand', 'target_choice', 'play_and_move_triggers', 'play_lifecycle']

### Disintegrate — Spell · `ogn-005-298` · **STALE snapshot** (pre-errata wording withheld; see inventory_ledger.json) · errata: origins (spot-checked)
- `d3d94631` Deal 3 to a unit at battlefield.
  needs: target_choice · ops: deal_damage · unblocked by `R3-A1-choices-costs-zones` · recommended: **stale** — bundled snapshot still carries pre-errata wording; reverify text before any program
- `033ec095` If this kills it, do this: draw 1.
  needs: conditional_effects, linked_instruction · ops: kill, draw · unblocked by `R3-A2-play-conditions-continuous` · recommended: **stale** — bundled snapshot still carries pre-errata wording; reverify text before any program

### Firestorm — Spell · `ogs-002-024`
- `95a3c682` Deal 3 to all enemy units at a battlefield.
  needs: area_targets · ops: deal_damage · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['deal_damage'] exist; blocked on ['area_targets']

### Flash — Spell · `ogs-011-024`
- `e7a1971e` [Reaction]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `7a92a690` Move up to 2 friendly units to base.
  needs: target_choice · ops: move_board_object · unblocked by `R3-A1-choices-costs-zones` · recommended: **partial** — ops ['move_board_object'] exist; blocked on ['target_choice']

### Gust — Spell · `ogn-169-298`
- `e7a1971e` [Reaction]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `e661650e` Return a unit at a battlefield with 3 :rb_might: or less to its owner's hand.
  needs: return_board_to_hand, target_choice · ops: — · unblocked by `R3-A1-choices-costs-zones` · recommended: **unsupported** — no implemented op applies; blocked on ['return_board_to_hand', 'target_choice']

### Incinerate — Spell · `ogs-003-024`
- `08866b32` [Action]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `df9db2ea` Deal 2 to a unit at a battlefield.
  needs: target_choice · ops: deal_damage · unblocked by `R3-A1-choices-costs-zones` · recommended: **partial** — ops ['deal_damage'] exist; blocked on ['target_choice']

### Maddened Marauder — Unit · `ogn-191-298`
- `7a66c5e8` [Tank]
  needs: tank, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['tank', 'combat_state']
- `8815ca64` When you play me, move a unit from a battlefield to its base.
  needs: play_and_move_triggers, play_lifecycle, target_choice · ops: emit_reflexive, move_board_object · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['emit_reflexive', 'move_board_object'] exist; blocked on ['play_and_move_triggers', 'play_lifecycle', 'target_choice']

### Morbid Return — Spell · `ogn-170-298`
- `08866b32` [Action]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `f3c76e58` Return a unit from your trash to your hand.
  needs: return_trash_to_hand, target_choice · ops: — · unblocked by `R3-A1-choices-costs-zones` · recommended: **unsupported** — no implemented op applies; blocked on ['return_trash_to_hand', 'target_choice']

### Mystic Poro — Unit · `ogn-171-298`
- `f4a07c4d` [Vision]
  needs: look, play_and_move_triggers · ops: recycle_one · unblocked by `R3-A1-choices-costs-zones` · recommended: **partial** — ops ['recycle_one'] exist; blocked on ['look', 'play_and_move_triggers']

### Pouty Poro — Unit · `ogn-013-298`
- `f8dcb74f` [Deflect]
  needs: deflect · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['deflect']

### Sai Scout — Unit · `ogn-174-298`
- `f4a07c4d` [Vision]
  needs: look, play_and_move_triggers · ops: recycle_one · unblocked by `R3-A1-choices-costs-zones` · recommended: **partial** — ops ['recycle_one'] exist; blocked on ['look', 'play_and_move_triggers']
- `0ede37d4` You may play me to an open battlefield.
  needs: open_battlefield_play, play_lifecycle · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['open_battlefield_play', 'play_lifecycle']

### Sneaky Deckhand — Unit · `ogn-176-298`
- `0ede37d4` You may play me to an open battlefield.
  needs: open_battlefield_play, play_lifecycle · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['open_battlefield_play', 'play_lifecycle']

### Tibbers — Unit · `ogs-018-024`
- `ca766089` When you play me, deal 3 to all units at battlefields.
  needs: area_targets, play_and_move_triggers, play_lifecycle · ops: deal_damage, emit_reflexive · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['deal_damage', 'emit_reflexive'] exist; blocked on ['area_targets', 'play_and_move_triggers', 'play_lifecycle']

### Traveling Merchant — Unit · `ogn-185-298`
- `92d985e1` When I move, discard 1, then draw 1.
  needs: play_and_move_triggers, discard · ops: emit_reflexive, draw · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['emit_reflexive', 'draw'] exist; blocked on ['play_and_move_triggers', 'discard']

### Void Gate — Battlefield · `ogn-296-298` · **STALE snapshot** (pre-errata wording withheld; see inventory_ledger.json) · errata: origins (spot-checked)
- `3aa2e8f7` Spells and abilities deal 1 Bonus Damage to units here.
  needs: bonus_damage · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **stale** — bundled snapshot still carries pre-errata wording; reverify text before any program


## proving-grounds-master-yi

### Master Yi - Wuju Bladesman (Starter) — Legend · `ogs-019-024`
- `96ecd8e6` While a friendly unit defends alone, it gets +2 :rb_might:.
  needs: conditional_might, continuous_effects, attacking_defending_alone, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['conditional_might', 'continuous_effects', 'attacking_defending_alone', 'combat_state']

### Cannon Barrage — Spell · `ogn-127-298`
- `e7a1971e` [Reaction]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `3c6691c9` Deal 2 to all enemy units in combat.
  needs: area_damage_in_combat, combat_state, area_targets · ops: deal_damage · unblocked by `R3-A3-combat` · recommended: **partial** — ops ['deal_damage'] exist; blocked on ['area_damage_in_combat', 'combat_state', 'area_targets']

### Confront — Spell · `ogn-129-298`
- `08866b32` [Action]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `5ee34de4` Units you play this turn enter ready.
  needs: enter_ready · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['enter_ready']
- `e8c50cd4` Draw 1.
  needs: — · ops: draw · unblocked by `E0` · recommended: **full** — composes from implemented ops ['draw'] with no missing mechanic

### En Garde — Spell · `ogn-046-298`
- `e7a1971e` [Reaction]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `6dd9b599` Give a friendly unit +1 :rb_might: this turn, then an additional +1 :rb_might: this turn if it is the only unit you control there.
  needs: target_choice, duration_expiry, conditional_effects · ops: modify_might · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['modify_might'] exist; blocked on ['target_choice', 'duration_expiry', 'conditional_effects']

### Gentlemen's Duel — Spell · `ogs-008-024`
- `08866b32` [Action]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `2ed49f33` Give a friendly unit +3 :rb_might: this turn.
  needs: target_choice, duration_expiry · ops: modify_might · unblocked by `R3-A1-choices-costs-zones` · recommended: **partial** — ops ['modify_might'] exist; blocked on ['target_choice', 'duration_expiry']
- `fd48e5d0` Then choose an enemy unit.
  needs: target_choice · ops: — · unblocked by `R3-A1-choices-costs-zones` · recommended: **unsupported** — no implemented op applies; blocked on ['target_choice']
- `26a3859b` They deal damage equal to their Mights to each other.
  needs: mutual_damage_equal_might, target_choice · ops: deal_damage · unblocked by `R3-A3-combat` · recommended: **partial** — ops ['deal_damage'] exist; blocked on ['mutual_damage_equal_might', 'target_choice']

### Highlander — Spell · `ogs-020-024` · **STALE snapshot** (pre-errata wording withheld; see inventory_ledger.json) · errata: origins (live-fetched)
- `d659b2ba` Choose a friendly unit.
  needs: target_choice · ops: — · unblocked by `R3-A1-choices-costs-zones` · recommended: **stale** — bundled snapshot still carries pre-errata wording; reverify text before any program
- `b9d95a9d` The next time it would die this turn, heal it, exhaust it, and recall it instead.
  needs: next_death_replacement, recall · ops: heal_damage, exhaust · unblocked by `R3-A2-play-conditions-continuous` · recommended: **stale** — bundled snapshot still carries pre-errata wording; reverify text before any program

### Master Yi - Honed — Unit · `ogs-009-024`
- `ba87989e` [Ganking]
  needs: ganking, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['ganking', 'combat_state']
- `0be72750` I enter ready.
  needs: enter_ready · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['enter_ready']

### Master Yi - Meditative — Unit · `ogs-004-024`
- `d767e9dd` While you have 8+ runes, I have +4 :rb_might:.
  needs: conditional_might, continuous_effects · ops: — · unblocked by `R3-A2-play-conditions-continuous` · recommended: **unsupported** — no implemented op applies; blocked on ['conditional_might', 'continuous_effects']

### Meditation — Spell · `ogn-048-298`
- `e7a1971e` [Reaction]
  needs: action_reaction_timing · ops: — · unblocked by `E0` · recommended: **full** — timing keyword only; already covered by the timing kernel (R1)
- `6ce549b5` As an additional cost to play this, you may exhaust a friendly unit.
  needs: optional_additional_cost · ops: exhaust · unblocked by `R3-A1-choices-costs-zones` · recommended: **partial** — ops ['exhaust'] exist; blocked on ['optional_additional_cost']
- `8be0efa4` If you do, draw 2.
  needs: — · ops: draw · unblocked by `E0` · recommended: **full** — composes from implemented ops ['draw'] with no missing mechanic
- `083ddaf7` Otherwise, draw 1.
  needs: — · ops: draw · unblocked by `E0` · recommended: **full** — composes from implemented ops ['draw'] with no missing mechanic

### Mobilize — Spell · `ogn-134-298`
- `3e791d2d` Channel 1 rune exhausted.
  needs: channel_rune · ops: — · unblocked by `R3-A1-choices-costs-zones` · recommended: **unsupported** — no implemented op applies; blocked on ['channel_rune']
- `27e88ae5` If you can't, draw 1.
  needs: if_cannot_fallback, conditional_effects · ops: draw · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['draw'] exist; blocked on ['if_cannot_fallback', 'conditional_effects']

### Mountain Drake — Unit · `ogn-142-298` · no rules text
- `a95a0531` (no rules text)
  needs: vanilla_unit_combat_state, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['vanilla_unit_combat_state', 'combat_state']

### Playful Phantom — Unit · `ogn-049-298` · no rules text
- `a95a0531` (no rules text)
  needs: vanilla_unit_combat_state, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['vanilla_unit_combat_state', 'combat_state']

### Stalwart Poro — Unit · `ogn-052-298`
- `8b9eb35a` [Shield]
  needs: shield, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['shield', 'combat_state']

### Stormclaw Ursine — Unit · `ogn-137-298`
- `7a66c5e8` [Tank]
  needs: tank, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['tank', 'combat_state']
- `2b579376` When you play me, channel 1 rune exhausted.
  needs: play_and_move_triggers, play_lifecycle, channel_rune · ops: emit_reflexive · unblocked by `R3-A2-play-conditions-continuous` · recommended: **partial** — ops ['emit_reflexive'] exist; blocked on ['play_and_move_triggers', 'play_lifecycle', 'channel_rune']

### Wielder of Water — Unit · `ogn-055-298`
- `d2dd9c3e` While I'm attacking or defending alone, I have +2 :rb_might:.
  needs: conditional_might, continuous_effects, attacking_defending_alone, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['conditional_might', 'continuous_effects', 'attacking_defending_alone', 'combat_state']

### Zephyr Sage — Unit · `ogs-005-024`
- `8b9eb35a` [Shield]
  needs: shield, combat_state · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['shield', 'combat_state']

### Fortified Position — Battlefield · `ogn-279-298`
- `d0ee5f77` When you defend here, choose a unit.
  needs: combat_state, play_and_move_triggers, target_choice · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['combat_state', 'play_and_move_triggers', 'target_choice']
- `9b46c0cf` It gains [Shield 2] this combat.
  needs: shield, combat_state, duration_expiry · ops: — · unblocked by `R3-A3-combat` · recommended: **unsupported** — no implemented op applies; blocked on ['shield', 'combat_state', 'duration_expiry']

## Not claimed

- executable programs
- production activation
- deck legality
- full or partial coverage in the manifest
