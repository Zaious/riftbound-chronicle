# Decision packets for X-09 (R3-A1 choices / costs / zones)

Each packet is one question Codex can rule on once for every card it blocks. Rules are cited by locator and summarized in the engine's own words (the licensed Core Rules text is not reproduced); the proposal is Claude's, offered for the ruling to accept, amend, or reject. Failure classifications use the engine-check outcome vocabulary.

## DP-01 — Which choices are targets, and which are not

**Blocks:** Disintegrate `d3d94631`, Flash `7a92a690`, Gentlemen's Duel `2ed49f33`, Gentlemen's Duel `fd48e5d0`, Gust `e661650e`, Highlander `d659b2ba`, Incinerate `df9db2ea`, Morbid Return `f3c76e58`

**Question.** Confirm the per-clause targeting classification under 355.7–355.10, and whether a non-targeted choice (355.17, resolution-time) gets its own decision artifact.

**Rules cited.**
- `Core 355.7` — Choosing specific Game Objects to affect makes them Targets unless this section says otherwise.
- `Core 355.10.a` — Objects in a non-Public zone are not targets; a unit card in your trash is one, since the trash is Public.
- `Core 355.10.c` — An object picked solely for a cost, a trigger condition or a replacement effect is not a target.
- `Core 355.10.d.2` — The exception does not cover an object that is the sole valid choice when the spell or ability goes on the chain.

**Proposal.** typed selector carries `targeted: true|false` derived from 355.10; targeted selectors are validated at play (355.8) and re-validated at resolution (359.3.e); non-targeted resolution choices become a `play-decisions` entry with stage=resolution.

| Situation | Proposed outcome |
| --- | --- |
| missing selector on a targeted clause at play | `invalid_input` |
| selector names an object failing 355.9 | `illegal` |
| selector on a zone the engine does not model | `unsupported` |
| resolution-time choice not yet supplied | `decision_required` |

## DP-02 — When each choice is made: play, resolution, or trigger finalization

**Blocks:** Flash `7a92a690`, Meditation `6ce549b5`, Mystic Poro `f4a07c4d`, Sai Scout `f4a07c4d`

**Question.** Adopt 355.1–355.5/355.17 and 402 as the stage model: optional-additional-cost and spell-target choices at play, triggered-ability targets/performance at trigger finalization, and Predict recycle during resolution. Is one decision artifact with a `stage` field acceptable, or one kind per stage?

**Rules cited.**
- `Core 355.1.a` — Deciding whether to pay an Optional Additional Cost happens in this step.
- `Core 355.5.b` — Choices for permanents' Triggered Abilities are not made here, even when playing the item is what triggers them.
- `Core 355.17` — Choices this section does not describe are made when the spell or ability resolves.
- `Core 402.1` — When a Triggered Ability's effect opens with 'you may', its controller decides at this point whether to perform it.
- `Core 752.2` — It does not cover choices made 'as you play this' or choices about Optional Additional Costs.

**Proposal.** one `engine-decisions.v1` artifact keyed by chain item, entries {decision_id, stage: play_declaration|trigger_finalization|resolution, kind, controller, options?}; a transition that reaches an unsupplied entry returns decision_required with the entry, never guesses. Vision's recycle choice is resolution-stage, not a 402.1 performance choice.

| Situation | Proposed outcome |
| --- | --- |
| decision for the wrong stage supplied early | `invalid_input` |
| decision owner mismatch | `illegal` |
| stage the engine cannot model | `unsupported` |
| entry absent when reached | `decision_required` |

## DP-03 — Targets that become illegal before or during resolution

**Blocks:** Disintegrate `d3d94631`, Gentlemen's Duel `2ed49f33`, Gentlemen's Duel `fd48e5d0`, Gust `e661650e`, Highlander `d659b2ba`, Incinerate `df9db2ea`, Morbid Return `f3c76e58`

**Question.** Adopt 359.3.e.1–359.3.e.9 as written: resolve anyway; illegal targets unaffected; instruction with all targets invalid does not execute; with some invalid executes on the valid subset; zone change to/from non-board makes a new object (124). How should the trace record a mistarget, and does a linked 'If this kills it' then evaluate false?

**Rules cited.**
- `Core 359.3.e.1` — Illegal targets, even all of them, do not stop the spell resolving.
- `Core 359.3.e.5` — Instructions tied to an illegal target are not followed; in the rule's example the card's other instruction (Void Seeker's draw) still happens.
- `Core 359.3.e.8` — If some but not all of an instruction's Targets go Invalid, it executes on the ones still valid and available.
- `Core 359.3.e.4` — A target that leaves for a Non-Board Zone (or arrives from one) and is then back is a different object, so no longer legal.
- `Core 758.1` — The spell or ability mistargets on resolution and ignores the instructions about that Game Object.

**Proposal.** outcome stays `supported`; per-instruction trace outcome `skipped_illegal_target` (all invalid) or `applied_to_subset` (some invalid) with the object ids. Linked instructions use typed predicates: mistargeting makes the prior instruction unexecuted, while 'If this kills it' additionally requires a causally attributed kill after the instruction's Cleanup; plain `if_applied` is insufficient.

| Situation | Proposed outcome |
| --- | --- |
| target invalid at play | `illegal` |
| target invalid at resolution | `supported (trace: skipped_illegal_target)` |
| object identity after zone change not tracked by the engine | `unsupported` |

## DP-04 — Costs: atomic payment and the play-level transaction

**Blocks:** Meditation `6ce549b5`

**Question.** Is 'play a card' the transaction boundary — costs paid in step 4 (357), legality checked in step 5 (358), everything undone on failure (358.5)? Today the atomic bridge spans timing + one effect program; a play with an optional additional cost and a linked effect needs the same guarantee across cost payment.

**Rules cited.**
- `Core 203.3` — If a Cost's game action is impossible, the Cost cannot be paid and the linked Effect does not happen.
- `Core 357.2.a` — A cost replaced by another event still counts as paid.
- `Core 414.4` — The rule's example: a friendly unit that is already exhausted cannot be exhausted to pay the additional cost, so that cost goes unpaid.
- `Core 358.5` — If a check fails, everything done in the process is undone and the action cancelled.
- `Core 356.4.f.1` — An optional additional cost counts as paid once the player chose to pay it.

**Proposal.** a `play` transaction in the resolution bridge: {decisions, cost_payments[], program}. A cost payment has an explicit cost context and receipt; it may reuse typed operations but is not merely an ordinary effect carrying a boolean flag. Any failed payment/check rolls the entire play back. Optional-cost 'paid' records the declared decision and successful payment semantics, including replacement/reduction rules.

| Situation | Proposed outcome |
| --- | --- |
| cost declared but unpayable | `illegal` |
| cost decision missing at play | `decision_required` |
| cost kind not typed | `unsupported` |
| malformed cost declaration | `invalid_input` |

## DP-05 — 'If you do', 'Otherwise', 'If you can't' — dependency vocabulary

**Blocks:** Meditation `6ce549b5`, Mobilize `3e791d2d`

**Question.** The IR has dependency_mode if_applied|always. Meditation needs the negative branch (Otherwise); Mobilize needs 'couldn't fully perform' (430.3 channels as many as possible — is a partial channel a failure for 'If you can't'?). 055 says ignore impossible instructions; 430.5's example ties 'couldn't' to the requested count.

**Rules cited.**
- `Core 055` — Carry out as much card text as possible and skip the instructions that are impossible.
- `Core 430.3` — Too few runes in the Rune Deck: channel all that are there.
- `Core 430.5` — The rule's example pairs a two-rune channel with a draw if fewer than two could be channeled.
- `Core 205` — A later instruction asks whether the game action happened, not whether a cost was paid.
- `Core 359.3.e.6` — Instructions that cannot be followed, for illegal targets or any other reason, are skipped.

**Proposal.** record instruction completion as full|partial|none, but use typed predicates rather than one generic `if_not_applied`: action_performed, action_not_performed, requested_count_not_reached, cost_paid, and caused_kill. Mobilize tests actual_count < requested_count; Meditation branches on its optional-cost receipt. ADR-0002: same program major, capability revision.

| Situation | Proposed outcome |
| --- | --- |
| dependency on an unknown effect_id | `invalid_input` |
| dependency mode not implemented | `unsupported` |

## DP-06 — return, recall, move — three events, not one

**Blocks:** Flash `7a92a690`, Gust `e661650e`, Highlander `d659b2ba`, Morbid Return `f3c76e58`

**Question.** Return-to-hand is a zone change (446.2) producing a new object (124); Recall relocates to Base without being a Move (455–456) and keeps damage/statuses (458.1); Move is 420/446 and triggers move abilities. Confirm three distinct event ops with distinct trigger classes, and Highlander's errata ordering (heal, exhaust, recall).

**Rules cited.**
- `Core 446.2` — Changing zones is not, by itself, a Move.
- `Core 124` — An object entering or leaving a Non-Board Zone is tracked as a new object.
- `Core 456.1` — Recalls do not trigger abilities that watch for Moves.
- `Core 458.1` — A Recall leaves a permanent's Damage and statuses as they were unless its source says otherwise.
- `Core 056.2` — A card that would go to another player's such zone goes to its owner's matching zone.
- `errata: Highlander OGS-020` — heal it, exhaust it, and recall it instead.

**Proposal.** new ops `return_to_hand` (board→owner's hand, new object identity, temporary modifications dropped per 124.1) and `recall` (to the permanent's current controller's base, not a Move, damage/status retained unless its source changes them), alongside existing `move_board_object`; trigger emission is keyed by event kind so Move triggers never fire on Recall.

| Situation | Proposed outcome |
| --- | --- |
| return of an object not on the board | `illegal` |
| recall destination not the controller's base | `invalid_input` |
| hand zone semantics beyond add-to-hand | `unsupported` |

## DP-07 — Look / Predict and the information boundary

**Blocks:** Mystic Poro `f4a07c4d`, Sai Scout `f4a07c4d`

**Question.** Predict (436) lets a player look at a Secret card and choose to recycle it. The looked-at card becomes own-private knowledge. Under ADR-0003, how does an observation record it, and may a player2 query ever contain player1's predicted card? (424.2.b: voluntarily showing private information is not a Reveal.)

**Rules cited.**
- `Core 436.1` — To Predict is to look at the Main Deck's top card and decide whether to Recycle it.
- `Core 128.3` — Secret: nobody may look at the card's face.
- `Core 128.4` — Private: the face may be read by the card's controller while it is on the board, or by its owner in any other zone.
- `Core 424.2.b` — Voluntarily showing Private information to other players is not a reveal.

**Proposal.** a `look` event yields an own-private fact {fact_id, zone, position, card_id?} in observation.v1 for the looking player only; the recycle choice is a resolution-stage decision (DP-02); P2-A's forbidden-key list gains `player1_predicted`/`opponent_predicted`.

| Situation | Proposed outcome |
| --- | --- |
| look on an empty deck | `supported (436.4: predict as many as possible)` |
| predicted card appearing in the other player's observation | `invalid_input (perspective violation)` |

## DP-08 — Channel: a rune entering the board with an entry state

**Blocks:** Mobilize `3e791d2d`

**Question.** Channel moves the top rune from Rune Deck to the board (430.1) with an entry state the effect may specify (430.2). Is this a new op `channel_rune` reusing play_token's `event_modifiers.entry_state` vocabulary (375), and is the rune's arrival a zone change (new object) or a move?

**Rules cited.**
- `Core 430.1` — Channel: take Runes from the top of the Rune Deck and put them onto the board.
- `Core 430.2.a` — Channeled runes enter ready unless told otherwise.
- `Core 161.1.a` — A rune is not a Permanent.
- `Core 164.2` — Every Basic Rune has the same two Abilities.

**Proposal.** new op `channel_rune` {player, count, entry_state} — takes from rune_deck top, appends to base, sets exhausted per entry_state, records applied count for DP-05; rune identity preserved (Rune Deck is a zone the state already models).

| Situation | Proposed outcome |
| --- | --- |
| rune deck empty | `supported (applied: none/partial per 430.3)` |
| entry state other than ready|exhausted | `invalid_input` |

## DP-09 — Versioning under ADR-0002

**Blocks:** (cross-cutting)

**Question.** Everything above adds operations and one decision artifact; nothing changes an existing field's meaning. Confirm: effect-program stays v1 with a capability revision; `engine-decisions.v1` is a new decision schema; effect-state gains optional zone contents only through an additive state capability.

**Rules cited.**
- `ADR-0002 change table` — Add a new operation that old programs never invoke → same program major may remain; capability revision required.

**Proposal.** as stated; the capability manifest picks up the new ops automatically (C-09) and the R5-A report shows their fixture coverage (C-11).

## DP-10 — Failure vocabulary for R3-A1 (bullet 12 of X-09)

**Blocks:** (cross-cutting)

**Question.** Adopt one table for the whole batch so cards do not each invent a classification.

**Proposal.** illegal = a supported rule rejects it (355.9, 414.4, 203.3); invalid_input = the artifact is malformed or a required decision was supplied at the wrong stage; unsupported = the engine lacks the semantics (named mechanic); decision_required = a listed decision is unsupplied when reached. Resolution-time mistargets are supported with a trace outcome, per DP-03.

## DP-11 — The English Origins FAQ is locally captured as historical evidence

**Blocks:** (cross-cutting)

**Question.** The official Origins FAQ is an HTML page whose own warning defers to newer rules. How should it be retained without overriding Core 2026-07-16?

**Proposal.** capture the official HTML in supplemental-en, hash and index it locally, mark it superseded by Core 2026-07-16, exclude it from default search, and expose it only through explicit historical search. R3-A1 rulings cite current Core/errata; the FAQ is rationale, not controlling authority.
