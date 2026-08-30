# Match Analyst Product Specification

Status: planned; depends on sovereign rules-core R2/R4
Date: 2026-08-30

## Purpose

Match Analyst is the planned fourth user-facing Chronicle system. It consumes a
completed or partially recorded match log and reconstructs the game from the
information available to the selected perspective.

It has two output modes over one shared normalized timeline:

1. `review` — evaluates rules execution, response windows, and decision quality.
2. `commentary` — explains the match as a clear narrative for players, readers,
   viewers, articles, or video narration.

This is not called Combat Reviewer because Combat is one formal Riftbound
procedure. Match analysis also covers mulligans, development, resource use,
movement, Showdowns, Chains, scoring, and endgame decisions.

Match Analyst is not enabled in the Skill router until the sovereign rules core
can reconstruct the required timing window with executable conformance
coverage.

## Shared ingestion pipeline

```text
match log / replay / human record
  -> source and perspective declaration
  -> event normalization
  -> rules-core timeline reconstruction
  -> observed / inferred / unknown separation
  -> decision points and turning points
  -> review or commentary projection
```

Review and commentary must use the same event identifiers, state hashes,
ruleset, card text, and uncertainty ledger. They may phrase and select evidence
differently, but they may not reconstruct two incompatible matches from one
input.

## Required input

- log source, format, completeness, and provenance;
- ruleset, FAQ/errata date, format, and region;
- perspective: `player1`, `player2`, `public_observer`, or
  `omniscient_replay`;
- public state snapshots or an ordered replay/event log;
- perspective-owned private information at each decision point, when known;
- turn, phase, four-state label, Priority, Focus, Outstanding Tasks, and Chain;
- actions proposed, attempted, passed, finalized, and resolved;
- optional player objective or reasoning;
- explicit markers for missing, inferred, later-revealed, and hidden facts.

Opponent hidden information must not be used in a player-perspective review. An
omniscient post-game output may use both players' revealed information, but it
must not use hindsight to claim that a decision was wrong under information the
player did not possess.

## Mode: Review

Review answers:

- Was the recorded action or resolution supported by the rules?
- Which response windows and supported legal alternatives existed?
- Did the player miss a response, sequence poorly, or spend the wrong resource?
- Was the selected action reasonable under the information available then?
- Is a criticism merely outcome bias?

### Review classifications

1. `rules_execution_error` — the action or resolution conflicts with supported
   executable rules and cited official sources.
2. `missed_response_window` — another supported legal timing action existed and
   was available from the reviewed perspective.
3. `strategic_misplay` — the action was legal, but a better-supported choice was
   available under the information known at the time.
4. `reasonable_alternative` — several choices remain supportable.
5. `outcome_bias` — the criticism relies on information revealed only later.
6. `insufficient_information` — the record cannot establish legality or quality.
7. `unsupported_engine_behavior` — the rules core does not implement the card or
   interaction needed for a verdict.

The Reviewer may not convert an unsupported engine result into a confident
misplay. Official rules outrank executable output; an engine/source mismatch is
a conformance defect.

## Mode: Commentary

Commentary explains rather than prosecutes. It may produce:

- chronological play-by-play from the normalized event stream;
- turn, phase, Showdown, and Chain summaries;
- plain-language explanations of important legal responses and resolutions;
- each deck's visible plan and how it developed;
- resource exchanges, battlefield pressure, and score progression;
- turning points, momentum changes, and unresolved forks;
- short recap, article narrative, spectator notes, or video-ready narration.

Commentary does not label a play a mistake by default. When analysis is useful,
it uses neutral phrasing such as “the player chose X while Y was also available”
unless Review mode has established a supported classification.

### Commentary levels

- `event`: literal, concise description of one confirmed event.
- `sequence`: groups related actions into a Chain, Showdown, Combat, or turn arc.
- `turning_point`: explains why a sequence materially changed public position.
- `match_summary`: explains the full game plan, adaptations, and result.

Every commentary claim carries one of:

- `confirmed` — directly present in the log or executable trace;
- `inferred` — a disclosed interpretation of public behavior;
- `unknown` — the log cannot establish motive, hidden information, or legality;
- `hindsight_only` — known after the decision but unavailable at the time.

## Shared dependency contract

```text
official source retrieval (Rule Consult)
  -> Chronicle rules-core reconstruction
  -> perspective-safe observations and supported legal timings
  -> Deck Coach identity and strategic priorities
  -> Match Analyst
       ├─ Review projection
       └─ Commentary projection
```

Rule Consult owns source-grounded interaction explanation. Deck Coach supplies
deck identity and intended game plan. Match Analyst owns the normalized match
timeline and post-game projections; it does not change the original match or a
P2-A session ledger.

## Artifacts

### `match-analysis.v1`

Shared machine-readable record:

- normalized timeline and source-event mapping;
- perspective and information boundary;
- rules-core checks and state hashes;
- observed, inferred, unknown, and hindsight-only facts;
- decision points and turning points;
- supported legal timing candidates and engine coverage;
- official source locators;
- assumptions and uncertainty;
- links to any generated projections.

### `match-review.v1`

- reviewed player and decision-time perspective;
- selected action and supported alternatives;
- classification and confidence;
- rules versus strategy reasoning;
- improvement suggestion;
- feedback target: Deck Coach, Player 2 policy, rules corpus, or rules-core.

### `match-commentary.v1`

- audience and tone;
- commentary level and requested length;
- ordered narration segments linked to event ids;
- rules explanations and uncertainty labels;
- turning-point summaries;
- final recap without fabricated motive or hidden information.

## Activation gate

Do not add Match Analyst to `skill/SKILL.md` as an available mode until:

- R2 typed effect IR exists for the bounded interaction set;
- R4 legal-action enumeration passes the official conformance suite;
- timeline normalization is deterministic and preserves source event ids;
- incomplete-information and hindsight-bias abstention cases pass;
- Review and Commentary generated from one log agree on confirmed state;
- a human expert reviews the first bounded replay corpus;
- the public product boundary has been checked against the applicable Riot
  decision.

Post-game log commentary and review are two modes of this one system. A future
live broadcast commentator may require a separate latency/UI runtime, but it
should still consume the same Match Analyst contract rather than become a fifth
knowledge system.
