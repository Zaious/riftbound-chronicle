# ADR-0006 — Deck Coach first consumes, but does not produce, engine evidence

Status: accepted

Date: 2026-09-03

Applies to: `deck-coach-session.v1`, Deck Coach runners and prototype, shared
`engine-check.v1`, and connection-status documentation

## Context

Deck Coach displays card-behavior coverage but currently satisfies none of the
six shared engine-connection conditions. Its first integration must make
bounded rules evidence inspectable without converting rules consistency into
strategy quality or inventing a representative game state from a primer.

## Decision

### Artifact

Add two optional, paired fields to `deck-coach-session.v1`:

- `engine_checks`: an array of complete `engine-check.v1` envelopes;
- `engine_evidence_scope`: constant `rules_consistency_only`.

If either field is present, both are required. Existing sessions without the
pair remain valid under the same schema major. The existing behavior-coverage
constant `strategy_evidence: not_established_by_engine_coverage` remains
unchanged and must survive attaching any check.

### First implementation: intake only

The first Deck Coach connection validates and attaches checks produced from
explicit structured inputs elsewhere. It does not generate a timing state from
primer prose and does not manufacture a “representative” game state.

A later producer may be added only through an explicit scenario input contract
that pins state, proposed action, ruleset, capability, and provenance. It may
never derive a timing check merely because prose mentions a Reaction.

### Validation and UI

- Reuse `validate_engine_check`; do not create a Deck Coach interpretation of
  the five outcomes.
- Reject malformed and overclaiming checks without writing a session.
- Attaching a check cannot mutate diagnosis, primer, recommendation mask, or
  behavior coverage.
- Render through the shared read-only bilingual viewer.
- `decision_required` is presented only; Deck Coach cannot supply or rank the
  decision.
- Update README connection claims only after the artifact, runner, validator,
  UI, regressions, and authority boundary all pass.

## Consequences

Claude can implement the bounded consumer without waiting for R3-A1 card
programs. Deck Coach gains reproducible rules evidence while its strategic
recommendations remain a separate evidence class. Producing checks remains a
later package because Deck Coach does not own live game state.

## Rejected alternatives

- Put the authority constant only inside behavior coverage: timing-only checks
  may exist when no card-behavior manifest is available.
- Always require engine fields: this would break existing session artifacts.
- Generate timing checks from natural-language primer claims: the missing
  structured state would be hidden rather than resolved.
- Let a supported check improve strategy confidence automatically.
