# Play Reviewer Product Specification

Status: planned; depends on sovereign rules-core R2/R4
Date: 2026-08-30

## Purpose

Play Reviewer analyzes a completed or partially recorded game from the
information actually available to the reviewed player. It separates rules
execution errors, missed response windows, strategic mistakes, and outcomes
that cannot be judged from the record.

It is the planned fourth user-facing Chronicle system. It is not enabled in the
Skill router until the sovereign rules core can reconstruct the required timing
window with executable conformance coverage.

## Required input

- ruleset, format, region, and effective date;
- player perspective being reviewed;
- public state snapshots or a replay/event log;
- that player's own private information at each decision point, when known;
- turn, phase, four-state label, Priority, Focus, Outstanding Tasks, and Chain;
- action attempted or chosen;
- optional stated objective or player reasoning;
- explicit markers for missing, inferred, and hidden information.

Opponent hidden information must not be used unless the review is explicitly an
omniscient post-game analysis and the output separates that hindsight from the
player's decision-time information.

## Review classifications

1. `rules_execution_error` — the recorded action or resolution conflicts with
   supported executable rules and cited official sources.
2. `missed_response_window` — another supported legal timing action existed and
   was available from the reviewed player's perspective.
3. `strategic_misplay` — the action was legal, but a better-supported choice was
   available under the information known at the time.
4. `reasonable_alternative` — several choices remain supportable.
5. `outcome_bias` — the criticism relies on information revealed only later.
6. `insufficient_information` — the record cannot establish legality or quality.
7. `unsupported_engine_behavior` — the rules core does not implement the card or
   interaction needed for a verdict.

## Dependency contract

```text
official source retrieval (Rule Consult)
  -> Chronicle rules-core state reconstruction
  -> timing/effect legal actions with coverage labels
  -> Deck Coach identity and strategic priorities
  -> Reviewer classification and explanation
```

The Reviewer may not convert an unsupported engine result into a confident
misplay. Official rules outrank executable output; an engine/source mismatch is
a conformance defect. Strategic criticism must be conditioned on the reviewed
player's information, not the final outcome.

## Initial artifact

The eventual `play-review.v1` record should contain:

- normalized timeline;
- decision points;
- rules-core checks and state hashes;
- legal timing candidates and coverage;
- selected action;
- classification;
- suggested alternative;
- official source locators;
- assumptions, unknowns, and confidence;
- feedback targets for Deck Coach, Player 2 policy, or rules-core fixtures.

## Activation gate

Do not add Play Reviewer to `skill/SKILL.md` as an available mode until:

- R2 typed effect IR exists for the bounded interaction set;
- R4 legal-action enumeration passes the official conformance suite;
- incomplete-information abstention cases pass;
- a human expert reviews the first bounded replay corpus;
- the public product boundary has been checked against the applicable Riot
  decision.
