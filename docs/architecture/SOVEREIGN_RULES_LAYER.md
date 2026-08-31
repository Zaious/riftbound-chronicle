# Chronicle Sovereign Rules Layer

Status: implementation baseline
Date: 2026-08-30

## Decision

> Two independent audits (2026-08-17, 2026-08-18) advised against building any
> rules engine. That guidance was deliberately overridden, and the rejected
> alternatives are recorded in
> [ADR-0001](../decisions/ADR-0001-sovereign-rules-layer.md). Read it before
> concluding this layer contradicts the audits.


Chronicle owns a programmatic Riftbound rules layer.  It is shared
infrastructure beneath Deck Coach, Rule Consult, Player 2 Agent, and the planned
Match Analyst.  It is not an adapter whose truth or availability belongs to a
third-party simulator.

The first deliverable is a timing and permission kernel.  Full card resolution,
simulation, and learning environments may be added in bounded versions, but
the public product never claims capabilities that the executable conformance
suite does not prove.

## Authority and dependency direction

```text
official rules / FAQs / errata
              ↓
Chronicle source registry + executable conformance cases
              ↓
Chronicle sovereign rules core
              ↓
Deck Coach · Rule Consult · Player 2 · Match Analyst
              ↓
optional simulation / search / learning implementations
```

No external engine is a normative source.  Optional engines may be tested
against the same Chronicle cases.  A disagreement is classified as
`kernel_failure`, `external_engine_failure`, `unsupported`, or
`stale_ruleset`; it is never resolved by silently changing the rule source.

## What was absorbed and what was only referenced

### Legally absorbable

- `samelliottdlt/riftbound-simulator` is MIT.  Chronicle adopts its useful
  architectural ideas: immutable snapshots, pure transitions, explicit
  choices, deterministic fixtures, structured errors, and separation of state
  from choice derivation.  Chronicle's Python implementation is independently
  maintained against current rules; copied MIT code, if introduced later,
  must retain its copyright and license notice.
- `google-deepmind/open_spiel` is Apache-2.0 and may later supply a separately
  licensed research interface.  It is not required by the portable Skill.
- `hlynurd/open-mtg` is MIT and is a useful small example of Monte Carlo move
  evaluation.  MTG-specific rules and card behavior are not imported.

### Architecture reference only

- `chorlick/alpharune` has no current license (`License: TBD`).  Chronicle may
  study its public descriptions and independently implement ideas such as an
  Intent vocabulary, event traces, observation features, replay, batch
  evaluation, and OpenSpiel separation.  No source is copied, modified, or
  redistributed without an explicit compatible license.
- `Card-Forge/forge` and `magarena/magarena` are GPL-3.0.  Chronicle references
  their mature patterns—card definitions separated from engine flow,
  deterministic game state, AI-vs-AI batch evaluation, replay, minimax/MCTS,
  and policy-dependent deck-strength caveats—but does not copy or link GPL
  implementation into the MIT portable core.
- `Mercantec-GHC/riftbound-tcg` currently exposes no repository license.
  Server-authoritative state, legal-action, event-log, and scenario-test ideas
  are reference material only.

## Product effect

### Deck Coach

Sequence claims gain an executable timing check.  Later bounded goldfish runs
may measure consistency, but engine coverage and policy version must accompany
every result.

### Rule Consult

Official text remains primary.  The core provides an executable timeline and
regression target, turning written expected answers into real conformance
checks.

### Player 2 Agent

The Agent can rank candidates inside a mechanically permitted timing set when
the supplied state is complete enough.  P2-A keeps human authority for physical
operations and unsupported card interactions.

### Match Analyst

The planned Match Analyst uses one normalized timeline for two projections:
Review identifies response windows and classifies rules errors, missed
opportunities, strategic mistakes, and insufficient-information cases;
Commentary turns the same confirmed events into play-by-play, sequence
explanations, turning points, and match summaries without fabricating motive.

## Release boundary

The sovereign core can exist before a complete simulator.  The portable public
runtime currently exposes advisory inspection and validation; it does not own
shuffle, hidden information, automatic card-effect resolution, scoring, or a
full game loop.  A future state-owning P2-S or public gameplay implementation
remains gated by a separate product decision and Riot review.

## Development plan

### R0 — Timing and permission kernel (implemented)

- four combined turn states;
- Action/Reaction and Priority/Focus gates;
- Outstanding Task and Pending Item blocking;
- next HOT/FEPR procedure;
- oldest-pending finalization;
- Unit/Gear/Add immediate-resolution classification;
- bilingual terminology aliases and executable cases.

### R1 — Structural transition trace (implemented)

- structured events for play, finalize, pass, resolve, and Focus movement;
- explicit Chain origin (`spell`, `activated`, `triggered`, `add`);
- removal of exactly one newest Finalized item after full execution;
- Focus-pass exceptions for triggered/Add initiated Chains;
- before/after state hashes and rule locators;
- unknown/unsupported transition rather than a guessed board update.

The v1 core exposes `add`, `finalize`, `pass-priority`, and
`complete-resolution`. Completion requires an explicit caller assertion that
the card effect was executed. This keeps the timing trace useful without
pretending the current kernel owns arbitrary card semantics.

### R2 — Effect intermediate representation (v1 implemented)

Chronicle will own a small typed effect vocabulary before implementing cards:

```text
choose · pay · move · draw · recycle · add-resource · modify-might
damage · heal · kill · counter · attach · ready · exhaust · score
create-token · schedule-trigger · replace-event
```

Effects are data interpreted by Chronicle code. Card packs may compose these
operations but may not add card-name conditionals to the turn/Chain engine.
Replacement effects, layers, and delayed/reflexive triggers receive explicit
types rather than free-text matching.

The first executable slice implements draw-without-Burn-Out, one-card recycle,
board movement, Might modifiers, damage/healing, ready/exhaust, and resource
addition. It emits deterministic state hashes and rule-grounded traces and
fails closed on every unsupported operation. Targeting, instruction linkage,
kill/cleanup, countering, attachment, replacement, layers, triggers, scoring,
tokens, and Burn Out remain later R2 increments.

The atomic resolution bridge now combines an eligible Chain Item and an effect
program. Timing and effect states are exposed only when both pure transitions
succeed; unsupported effects cannot silently remove a Chain Item, and a
non-newest Finalized item cannot mutate effect state.

The second R2 slice adds bounded target snapshots and linked-instruction gates.
It can detect board/non-board target movement plus kind, location, and
controller-relation failures; ignored targets do not mutate state, and a later
`if_applied` instruction is skipped when its dependency was ignored or a no-op.

The third R2 slice adds supported active Kill and the lethal-damage portion of
Cleanup. Non-token permanents move to owner Trash, killed tokens cease to exist,
and passive lethal kills retain a simultaneous group plus source attribution.
At that stage death-trigger scheduling and the rest of Cleanup were
fail-closed gates; the following slice opens only the typed self-death subset.

The fourth R2 slice adds typed self-death trigger descriptors and Pending Chain
scheduling. Trigger blocks follow Turn Player/Turn Order and require explicit
controller-local order. The combined resolution remains atomic when order is
missing or ambiguous. Cross-object watchers, optional finalization, reflexive
triggers, and replacements remain future increments.

The fifth R2 slice binds every typed trigger to its controller, source, and
effect-program id. Rules-level optional triggers require an explicit perform or
decline choice during Finalize; mismatched programs are rejected before state
mutation. A new regression also corrected Priority assignment when an off-turn
player controls the newly Finalized top item.

### R3 — Bounded Origins/Taiwan card pack

- select two to four linear decks plus their relevant Battlefields;
- implement only cards used by the bounded environment;
- mark every card behavior `full`, `partial`, `unsupported`, or `stale`;
- require an official-text/errata locator and at least one behavior test per
  implemented clause;
- cross-check deck sequences against Deck Coach primers and real player review.

### R4 — Legal-action and review services

- enumerate timing- and effect-legal actions from a perspective-safe state;
- return an explanation trace, not only an action id;
- let P2-A rank inside the supported legal set while retaining the human gate;
- let Match Analyst reconstruct response windows, produce Review and Commentary
  from one timeline, and abstain on missing facts;
- feed confirmed Reviewer corrections back into the conformance corpus.

### R5 — Search and learning research

- deterministic batch runner and replay corpus;
- Random and transparent heuristic baselines;
- MCTS/ISMCTS through a Chronicle-owned interface, optionally backed by
  Apache-licensed OpenSpiel;
- imitation/RL only after legal-action masks, observation boundaries, and
  state transitions pass conformance for the bounded environment.

## Pattern absorption matrix

| Source | Absorbed into Chronicle | Explicitly not inherited |
| --- | --- | --- |
| MIT `riftbound-simulator` | pure functions, immutable snapshots, deterministic RNG/fixtures, explicit choices, structured validation results | stale rule text, incomplete card flow, `100% accurate` claim |
| unlicensed AlphaRune | Intent vocabulary, event/effect separation, perspective observations, batch/replay and OpenSpiel-facing design as clean-room requirements | source code, card implementations, stale rules/card pool, unverifiable completeness claims |
| GPL Forge | rules flow separated from card definitions, scripted/typed card behavior, headless batch, replay, AI-policy caveats | GPL implementation or runtime linkage in the MIT portable core |
| GPL Magarena | reversible/cloneable states, separate Random/Minimax/Monte-Carlo policies, decision-time search limits | GPL implementation or Magic-specific evaluation heuristics |
| unlicensed Mercantec | scenario tests, legal-action service boundary, server-authoritative event-log thinking | source code and automatic authority claims |

The target is not a composite of these projects. It is a Chronicle-maintained
Riftbound implementation whose useful design ancestry and legal provenance are
documented and whose correctness is established by Chronicle's own official-
source conformance suite.
