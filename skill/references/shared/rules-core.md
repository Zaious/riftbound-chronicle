# Chronicle Sovereign Rules Core

Read this reference when an answer depends on Open/Closed state, Showdown,
Action/Reaction timing, Priority, Focus, Pending/Finalized Chain Items, or the
HOT/FEPR procedure.  This is Chronicle-owned executable knowledge; it is not a
complete card-effect engine and never outranks the current official sources.

## Sovereignty contract

- Chronicle owns the schemas, terminology, executable cases, implementation,
  versioning, and release decisions in this repository.
- The core has no runtime dependency on another fan simulator, AI project,
  model vendor, or private API.
- Official rules and scoped official FAQs are normative.  If an executable
  result disagrees, record a conformance failure and fix or version the core.
- Every result identifies its rules baseline and source locators.
- Unsupported card behavior is unknown, never inferred as legal or resolved.

The initial implementation is `${CLAUDE_SKILL_DIR}/scripts/rules_core.py`; its
state schema is `${CLAUDE_SKILL_DIR}/schemas/rules-core-state.schema.json`, and
its executable fixtures are `${CLAUDE_SKILL_DIR}/data/rules_core_cases.json`.
A case may carry an optional `source` naming the official document, its version,
and the exact clause the case encodes; `check_rules_core.py` fails if a cited
version drifts from the corpus baseline, so a clause is re-read rather than
inherited when the baseline moves.
Supported card-state mutations live separately in
`${CLAUDE_SKILL_DIR}/references/shared/effect-ir.md`; timing permission does not
imply effect support.

## Four-state timing model

| State | Showdown/Combat | Chain | Timing permission |
| --- | --- | --- | --- |
| Neutral Open / 普通開環 | no | no | by default, the Turn Player with Priority in Main may play or activate legally timed cards/abilities |
| Neutral Closed / 普通閉環 | no | yes | the Priority holder may add only Reaction / 反應 items |
| Showdown Open / 法術對決開環 | yes | no | the player with Focus and Priority may start a Chain with Action / 迅捷 or Reaction / 反應 |
| Showdown Closed / 法術對決閉環 | yes | yes | the Priority holder may add only Reaction / 反應 items |

Do not confuse rules `Closed State / 閉環` with a Deck Coach evaluation
`closed loop`.  Machine fields use `chain_state` or the combined four-state
label for rules, and `evaluation_cycle` for product feedback loops.

## HOT/FEPR

The core must expose the next required procedure rather than jumping directly
from a proposed card to a guessed board state:

```text
Handle Outstanding Tasks
  -> Finalize pending items oldest-first
  -> Execute or pass Priority
  -> after every player passes in sequence
  -> Resolve the newest Finalized item in full
```

Units, Gear, and Add abilities require immediate resolution when finalized.
Their special handling must be explicit in the transition trace.  Pending
items finalize oldest-first, while Finalized items resolve newest-first.

## Safe use by each system

- **Deck Coach:** validate that a proposed sequence has a supported timing
  path; do not turn an unsupported effect into a strategic claim.
- **Rule Consult:** use the executable trace as a consistency check after
  retrieving official text.  The cited official source remains the answer's
  authority.
- **Player 2 Agent:** when a sufficiently structured state exists, remove
  timing-impossible candidates before strategy ranking.  Card-effect coverage
  or missing facts can still require human legality confirmation.
- **Match Analyst (planned):** reconstruct one perspective-safe timeline. Review
  distinguishes a rules execution error from a legal but strategically weak
  choice; Commentary explains confirmed sequences and turning points. Missing
  hidden information or timing facts must produce `unknown`, not a misplay or
  invented narration.

## Current coverage

Version 1 covers the four-state permission model, the next HOT/FEPR procedure,
and structural timing transitions: add a Pending item, finalize oldest-first,
pass Priority, complete exactly one newest Finalized resolution, and move or
retain Focus when the Chain empties. Every transition includes reproducible
before/after state hashes and rule locators.

Triggered Pending Items may bind an effect program and declare an optional
Finalize choice. The controller must explicitly perform or decline an optional
trigger; after the last Pending item finalizes, Priority is granted to the
controller of the newest Finalized item.

Trigger scheduling preserves chronological batches. Simultaneous triggers in
one batch use Turn Player／Turn Order controller blocks; separate event batches
remain ordered by `batch_sequence`. Self-death and Reflexive descriptors share
this scheduler without becoming the same kind of trigger.

It does not execute arbitrary card instructions, combat, scoring, replacement
effects, layers, or a complete game. `complete-resolution` requires the caller
to confirm that the effect was executed; the timing core never invents the
result of unsupported card behavior.
