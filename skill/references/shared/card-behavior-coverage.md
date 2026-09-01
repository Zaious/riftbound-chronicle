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
