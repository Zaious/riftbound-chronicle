# Card Behavior Coverage

Read this reference when an R3 card pack or Deck Coach output claims executable
support for card text. Card lookup, executable behavior, and strategic evidence
are three separate contracts:

1. `card_lookup_coverage` says a decklist name matched the bundled database.
2. `card-behavior-manifest.v1` says specified current-text clauses have typed
   programs, tests, and explicit unsupported mechanics.
3. Deck identity, mulligans, sequencing, and common mistakes require separate
   strategic/expert evidence. Engine coverage never establishes them by itself.

## Manifest rules

Each card is keyed by normalized canonical name and bound to a hash of its
current errata-applied text. Printing ids are provenance, not the behavior key:
reprints with the same current rules identity may share behavior, while a text
or errata change makes the old entry stale.

Each clause records an official source id/locator, its own text hash, status,
program id, implemented IR operations, unsupported mechanics, tests, and notes.

- `full`: tested program, no unsupported mechanic.
- `partial`: tested program plus explicit unsupported mechanics.
- `unsupported`: no program and at least one named missing mechanic.
- `stale`: no current executable claim may be consumed.

Card status is derived from its clauses. A manifest also binds the Core/FAQ
baseline, environment, region, and formats. Mismatched or non-active manifests
cannot contribute active coverage.

## Deriving statuses from programs (C-18)

For the R3-A1 batch, `r3a1_programs.py` runs every clause's fixtures
(`r3a1_programs.json`) through the same play / resolution / effect runners as
the engine-check CLI and derives `r3a1_behavior_manifest.json`. A clause is
`full` only when a positive and a negative fixture pass and no mechanic is
left unsupported; `partial` when they pass and one is named; a failing
fixture demotes the claim to `unsupported`; a clause the inventory marks
`stale` stays stale with no `program_id` whatever its fixtures do. Fixture
expectations cite the Core clause they follow, not the engine's behaviour.
The manifest stays `draft`.

The R3-A2 batch (C-25, ADR-0007) adds the state a card contributes while it
exists — play or move triggers, entry replacements, a play permission, a
keyword, a conditional passive, a Bonus Damage source — as a `passive` on the
clause, applied to the scenario and probed by fixtures; "When you play me" is
observed through a `play_entry` fixture that plays the permanent and resolves
its entry. A passive-only clause derives `passive:<clause_id>` with no
implemented ops. Legends are not modelled as objects, so a Legend's passive
is anchored to a stand-in gear and the clause stays `partial` naming that
limit; the four stale cards carry programs but derive no `program_id`.

The R3-A3 batch (C-32, ADR-0008) runs its clauses inside Combats the real
procedures stage and open: a fixture's `combat` block names the Battlefield
and who applied Contested, the Showdown can be closed by Focus passes, and
the clause is observed through `combat_open` (designations, the Combat
Chain, the Combat-relative Might reads), one `combat_step` such as the
damage assignment with the assigning player's decision, a `standard_move`
declaration, or a resolution on the Combat Chain with the Combat context.
A vanilla Unit derives `intrinsic:unit_combat:<clause_id>` from probes of
its inherent Combat behaviour; `(no rules text)` is never an invented
instruction. Tank derives full only with the Backline and Tank+Backline
fixtures beside it; the Master Yi Legend clause stays `partial`.

## Deck Coach projection

`deck-behavior-coverage.v1` currently covers resolved Main Deck copies only.
It reports copy-weighted `full`, `partial`, `unsupported`, `stale`, and
`uncovered` counts plus per-card clause ids and missing mechanics. A deck entry
that fails card-name lookup remains in the denominator as `uncovered`; it cannot
disappear merely because behavior matching is impossible. Legend,
Chosen Champion, Battlefield, sideboard, and cross-card line coverage remain R3
work and must not be inferred from this first projection.

The projection always carries:

```text
strategy_evidence: not_established_by_engine_coverage
```

Deck Coach may put the projection in its evidence ledger. It may not upgrade a
heuristic engine card, keep/ship rule, line, matchup, or mistake claim merely
because individual clauses are executable.

## Commands

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/card_behavior_coverage.py validate manifest.json
python ${CLAUDE_SKILL_DIR}/scripts/card_behavior_coverage.py summarize profile.json manifest.json --output coverage.json
python ${CLAUDE_SKILL_DIR}/scripts/deck_coach_pipeline.py run --input deck.json `
  --behavior-manifest manifest.json --output-dir deck-coach-output
```

No production manifest is bundled yet. Until an R3 pack passes its clause and
pack conformance gate, ordinary Deck Coach runs must report behavior coverage
as unavailable.

The first selected inventory is recorded in
`${CLAUDE_SKILL_DIR}/data/card_program_packs/global-core-origins-v1/selection.json`.
Its status is selection-only and pending decklist verification; it is not a
behavior manifest and cannot activate coverage.
