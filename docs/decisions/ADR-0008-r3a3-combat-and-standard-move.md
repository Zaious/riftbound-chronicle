# ADR-0008 — R3-A3 Combat, combat-relative characteristics, and Standard Move

- Status: Accepted (Codex rulings, 2026-09-05)
- Scope: `R3-A3-combat`, the G1 Combat milestone, and the minimum Standard
  Move procedure required by Ganking.
- Rules baseline: English Core Rules 2026-07-16, especially 143–144,
  190.6, 323, 341–348, 383.4.e–f, 417, 428.5.c.2, 459–466, 740.2,
  810, and 814–815.
- Not decided here: Battlefield control/Conquer/scoring (G2), terminal state
  and Burn Out (G3), Hidden, attachment, or a general continuous-effect layer
  engine.

## Context

R3-A3 contains 13 clauses on 12 cards, but those clauses do not form one
mechanic. Cannon Barrage and the two conditional-Might cards need a truthful
active-Combat context; Fortified Position needs a Battlefield-controlled
Defend trigger and a `this combat` characteristic grant; Tank needs the actual
Combat Damage assignment rules; Ganking changes Standard Move outside Combat;
Gentlemen's Duel is simultaneous non-Combat Deal based on current Might.

The implementation must not fabricate a small `in_combat: true` flag merely
to make the card fixtures pass. The state and procedures below are the
Chronicle-owned rules layer that makes those claims observable.

## Decisions

### 1. Combat procedure state is separate from card-effect state (DP-25)

The timing state gains one optional `combat` record with a stable `combat_id`,
Battlefield identity, status, attacker, defender, and procedure progress. The
effect state stores each Unit's current combat designation as
`{combat_id, role}`. Procedures that touch both states return both next states
and both hashes atomically, following the turn-step precedent.

Absence means no active/staged Combat. It is not equivalent to an unknown
Combat fact. A consumer that says Combat is happening but cannot provide the
participants, Battlefield identity, procedure status, and designations must
receive `unsupported`/insufficient observation, never an inferred context.

The new fields and decision kinds are additive under the current schema
majors. A replay-changing reinterpretation of an existing field requires a
new ADR and migration.

### 2. Staging and opening Combat are explicit procedures (DP-26)

`stage_combat` runs only from a quiet Cleanup boundary. A Battlefield is a
candidate when Units controlled by exactly two opposing players are present
(461–462). Zero candidates is a supported no-op. More than one candidate
requires a Turn Player `location_selection`; the engine never chooses the
first key. A Battlefield involving more than two players is not silently
reduced to a pair.

`open_combat` requires the selected Battlefield still to qualify. The attacker
is the player recorded as having applied Contested; the defender is the other
participant (464.2.c). Missing or contradictory attribution is insufficient
state, not a guessed attacker. A new Combat Showdown gives Focus to the
attacker; an already-open Showdown at the same Battlefield keeps its Focus
(464.2.c.1.a–b). Other active Showdowns/Combats block opening.

The procedure then assigns player and Unit designations, evaluates start /
Attack / Defend triggers, gives the attacker Focus, and schedules the resulting
Combat Chain in the order required by 464.2.e. A Chain opens only when an item
was actually scheduled.

### 3. Designations are synchronized by Cleanup and trigger once per identity
(DP-27)

At opening, every Unit at the Combat Battlefield controlled by the attacker or
defender gains the matching designation. A later Unit of either participant
that becomes present gains it during the following Cleanup; a Unit no longer
there loses it (323.2, 464.2.c.3.a). The Combat record stores which object
identity has already produced its Attack/Defend trigger. Losing and regaining
the designation does not trigger twice for the same identity in one Combat
(383.4.e.2.a, 383.4.f.2.a). Leaving through a non-Board zone and returning is a
new identity and is evaluated as a new object.

Trigger descriptors preserve `combat_id`, role, Battlefield identity, and the
source identity. Same-controller collisions use `trigger_order`; no ordering
is compiled into card data.

### 4. Battlefield Defend triggers follow Battlefield control (DP-28)

Fortified Position is represented on the Battlefield entity, not as a fake
Unit/Gear. While controlled, its controller controls the ability and makes its
choices (190.6.a). In `When you defend here`, `you` is the Battlefield's
controller (190.6.d); the trigger occurs only when that player gains Defender
at that Battlefield. If it is uncontrolled, `you` refers to no one and the
condition does not trigger, even though the Turn Player would administer other
uncontrolled Battlefield abilities (190.6.b, 190.6.d).

`choose a unit` is a target choice made at trigger finalization. The text does
not say `here`, so the engine must not add a same-Battlefield restriction. The
granted Shield is bound to the chosen identity and the current `combat_id`.

### 5. Combat-relative Might is read, not baked into base state (DP-29)

`effective_might` remains the rules-facing read path and adds:

- Shield X while the Unit has the Defender designation; multiple Shield values
  sum, omitted X is 1 (814).
- `attacking_or_defending_alone`: the Unit has either designation and no other
  friendly Unit is at the same location (740.2.a). Friendly is team-aware.
- `friendly_unit_defends_alone`: a bounded external aura used by the Master Yi
  Legend clause; it applies to each friendly Unit that is a lone Defender.

Combat contributions clamp a negative final Might to zero without changing
the stored arithmetic value (143.2.b). `current_might` keeps its existing
context-free compatibility contract.

Shield/Tank/Ganking are characteristics. Permanent printed instances live on
the object. Granted instances use typed `keyword_modifiers` with source,
optional value, duration, and `combat_id`/`turn_id`; `this combat` grants are
active only for the matching Combat and expire together at 466.7.c.

The Legend-object gap remains real. Master Yi - Wuju Bladesman's clause may be
tested through a clearly marked probe, but stays `partial:
legend_zone_object` until Legends are first-class state.

### 6. Ganking belongs to Standard Move, not the Combat procedure (DP-30)

Add a `standard_move` procedure instead of treating `move_board_object` as a
player action. It is legal only in the controller's Main Phase, in an Open
State, outside Showdown/Combat; exhausting every selected Unit is the cost
(144.1–144.3). All selected Units share one destination and costs are paid
simultaneously. Base→Battlefield and Battlefield→own Base are normally legal;
Battlefield→Battlefield requires active Ganking (144.4, 810). Ganking adds that
destination permission only: it creates no extra move and waives no other
destination restriction.

The result delegates the actual relocation to the existing Move operation so
Move triggers and Cleanup behavior remain one implementation. Missing choice
or cost confirmation is `decision_required`; a well-formed forbidden route is
`illegal`; malformed or stale identities are `invalid_input`.

### 7. Combat-scoped area effects and mutual Might damage are typed (DP-31)

`affected.criteria.location = active_combat` selects Units at the active
Combat Battlefield that currently carry that Combat's designation. They are
affected objects, not targets. Controller relation remains team-aware. With no
active Combat the set is empty and Cannon Barrage resolves as a supported
no-op; an alleged active Combat with incomplete identity/participant data is
unsupported.

Gentlemen's Duel uses a typed simultaneous `mutual_damage_current_might`
operation. It revalidates both chosen Units, snapshots both rules-facing Might
values before either Deal, then performs the two Deal events atomically. The
Units, not the spell, are the named damage sources. One invalid target skips
only instructions related to it under the ordinary referent rules; the engine
must not quietly turn the action into sequential damage or reuse Combat Damage.

### 8. Combat Damage assignment is a complete player decision artifact (DP-32)

At Showdown close, if both sides still have designated Units at the Battlefield,
sum the non-negative rules-facing Might of all non-Stunned Units on each side
(423.1.b, 465.1–465.2.b). Starting with the attacker, each player supplies a
`damage_assignment` decision mapping every opposing Unit identity to a
non-negative raw amount. The sum must equal that side's available Combat
Damage. The engine may auto-advance only when exactly one legal assignment
exists; otherwise it stops and names the assigning player.

Validation enforces 465.2.c in full:

- lethal before moving to another Unit;
- no over-assignment above minimum lethal while another eligible Unit remains;
- existing marked damage and active Prevent/replacement effects are considered
  when calculating minimum applied lethal;
- a Unit that cannot be dealt damage is exempt;
- Tank before non-Tank and Backline after non-Backline;
- equal-priority Units are the assigning player's order choice;
- mutually exclusive assignment requirements (for example Tank+Backline) need
  an explicit per-Unit choice.

Tank cannot be promoted to full from a fixture that omits these competing
requirements. Backline is implemented even though the first R3-A3 cards do not
print it, because the official Tank contract and examples require the
interaction.

### 9. Assignment previews consume replacements exactly once (DP-33)

Assignment is not Deal (417.1.a), but replacement effects that would alter the
resulting damage are considered during assignment (465.2.c.5). Chronicle uses
the existing replacement descriptors in a non-committing preview. If order or
choice changes legal minimum lethal, the affected Unit's controller supplies
the existing replacement decision for the assignment event. The preview emits
a receipt recording the transformed/prevented assigned amount and consumed
replacement effects.

When assignment completes, damage is Dealt simultaneously (465.2.c.1.a,
465.2.d). The Deal step consumes the assignment receipt and must not apply the
same replacement a second time. Any descriptor the preview engine cannot
evaluate makes the assignment `unsupported`; it must not be ignored to produce
a seemingly legal allocation.

### 10. Combat Cleanup, result, and closure are separate refusable steps
(DP-34)

After simultaneous Deal, skip FEPR and enter Combat Resolution (465.3). Run one
Combat Special Cleanup: ordinary lethal Cleanup, heal all Units, then Recall
Attackers still present if Defenders remain (466.1). Combat-damage kills are
attributed to the Combat Damage source Units and their controllers
(428.5.c.2). Pending death/reflexive items and associated FEPR finish before
result determination.

`determine_combat_result` follows 466.3 exactly: win/loss only when one of the
two designated players alone has Units remaining; otherwise No Result,
including the Recall case. A No Result with both sides remaining stages a new
Showdown and Combat. G2 control establishment and points do not run here; the
procedure returns `unsupported: battlefield_control_resolution` at that
boundary rather than inventing control or scoring.

`close_combat` removes all player/Unit designations, clears the Combat and
Showdown records, and expires all matching `this combat` effects simultaneously
(466.7.a, 466.7.c). It may run only after the result and any required G2 handoff
are recorded. No generic turn advance is implied.

### 11. R3-A3 status is derived from procedure coverage (DP-35)

The 13 clauses receive positive, negative, decision-required, and adversarial
fixtures as applicable. No card status is copied from this ADR.

- Cannon Barrage, Fortified Position, Gentlemen's Duel, Ganking, Shield, Tank,
  Wielder of Water, and the two vanilla Units may become full only when their
  corresponding procedure gates above pass.
- Master Yi - Wuju Bladesman stays partial on `legend_zone_object`.
- Tank stays partial if any required 465.2 assignment interaction remains
  unsupported.
- A vanilla Unit uses a named intrinsic Unit-Combat program/probe; `(no rules
  text)` is never represented as a fabricated card instruction.
- `supported` applies to a clause under the frozen pack and rules baseline, not
  to an entire deck, arbitrary game, or complete simulator.

## Implementation order

1. C-26: state/decision schemas, staging and opening, designations, trigger
   synchronization.
2. C-27: Battlefield Defend trigger, Shield/alone reads, typed `this combat`
   keyword modifiers.
3. C-28: atomic Standard Move and Ganking permission.
4. C-29: active-Combat criteria and mutual Might damage.
5. C-30: assignment enumeration/validation, Tank/Backline, replacement preview
   receipts.
6. C-31: simultaneous Combat Deal, Combat Cleanup, result and closure boundary.
7. C-32: R3-A3 card programs, manifest derivation, capability/R5 regeneration.

Each package is one focused commit with in-repo and off-cwd gates. C-30 must
encode the official Tank/Backline and replacement-assignment examples as
goldens. C-31 must prove that death triggers settle before result, that Recall
causes No Result, and that no G2 control/point mutation occurs. C-32 keeps
symbolic bindings and mirrored player runs.

## Rejected alternatives

- A caller-supplied `in_combat` boolean with no participant/designation proof.
- Treating Ganking as a Combat keyword action.
- Adding Shield directly to stored Might or forgetting its Defender condition.
- Calling criteria-found Combat Units targets.
- Sequentially resolving simultaneous mutual or Combat Damage.
- Validating Tank without Backline, lethal ordering, and replacement-aware
  assignment.
- Applying damage replacements once during assignment and again during Deal.
- Folding G2 control, scoring, or G3 victory into the first Combat milestone.
