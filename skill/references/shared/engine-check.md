# Shared Engine Check

Read this reference when a Chronicle system consumes executable timing, effect,
resolution, cleanup, or future legal-action evidence. `engine-check.v1` is the
stable integration envelope between sovereign engine components and product
artifacts. It is not a new rules authority and does not apply a state change.

## Contract

Every check declares:

- check kind and producing component/version;
- Core/FAQ baseline;
- input and result hashes;
- one bounded coverage id with `complete_game: false` and
  `complete_legality: false`;
- one of five outcomes;
- reason, official rule locators, compact trace summary, assumptions, and
  missing information;
- an actionable but neutral decision descriptor when input is required;
- optional raw engine result for debugging or replay reconstruction.

| Outcome | Meaning | Consumer behavior |
| --- | --- | --- |
| `supported` | The bounded component completed the requested check | May cite as executable consistency evidence inside its exact coverage |
| `illegal` | A supported timing/procedure rejects the attempted action | Explain the bounded rejection; do not generalize to unsupported card legality |
| `unsupported` | The component lacks required semantics | Abstain or fall back to sourced prose with lower engine confidence |
| `decision_required` | A controller/human choice is required before retry | Present choices neutrally; never choose merely to make execution continue |
| `invalid_input` | State, program, binding, or decision artifact is malformed | Repair/recollect input; do not interpret it as a game ruling |

The envelope itself always carries:

```text
official_status: unofficial
role: consistency_check
state_effect: none
```

Even when an optional raw result contains proposed `next_state` fields, a
consumer must apply its own authority contract. P2-A still requires human
physical resolution and a new confirmed snapshot.

## Runner

The dependency-free runner wraps existing pure components:

Every command below runs as written against the bundled example inputs in
`${CLAUDE_SKILL_DIR}/data/engine_check_examples/`, and `check_engine_check.py`
executes each one and asserts its outcome. Substitute your own files in the same
argument positions.

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py timing timing-state.json `
  --payload proposed-action.json --output timing-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py timing timing-state.json `
  --operation permissions --output permissions-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py timing timing-state.json `
  --operation next --output next-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py effect effect-state.json `
  effect-program.json --output effect-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py resolution closed-timing-state.json `
  spell-1 effect-state.json effect-program.json --output resolution-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py cleanup cleanup-state.json `
  --output cleanup-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py cleanup cleanup-state.json `
  --cleanup-decisions cleanup-decisions.json --output resolved-cleanup-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py play play-timing-state.json `
  play-effect-state.json play-declaration.json --decisions play-decisions.json `
  --output play-check.json
python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py validate cleanup-check.json
```

The two `cleanup` commands are the same state twice, and are worth running in
order: without decisions it returns `decision_required` naming the events whose
order a controller owns, and with those decisions supplied it completes. That
is the whole abstention contract in two commands — the component stops and says
what it needs rather than picking an order to keep going.

Use `--include-raw` only when the consumer needs the full trace/state proposal.
Use repeatable `--assumption` and `--missing-information` flags to keep the
artifact's epistemic boundary explicit. The check id is deterministic for the
same kind, inputs, and underlying result.

A malformed input, a missing file, or `validate` on an artifact that overclaims
its coverage exits non-zero and writes no artifact. Failure is never a ruling.

## Consumer projections

### Deck Coach

Use supported checks only to verify bounded sample lines, timing claims, and
card-program behavior. Engine evidence does not replace deck identity, expert
strategy evidence, or current format legality. Show unsupported mechanics in
the primer evidence ledger.

### Rule Consult

Place the check beside controlling official passages. The official source is
the answer's authority; the check is a reproducible consistency test. Source
uncertainty and engine-coverage uncertainty must remain separate fields.

Store the envelope in the consultation's `engine_checks` array. When a surface
displays one, use the shared read-only viewer in
`prototype/shared/engine-check-view.js` rather than a per-system renderer, so
one outcome does not acquire a different meaning in each place it appears. The
viewer always shows the coverage limits and the authority triple with the
result, and presents `decision_required` options without choosing among them.

### Player 2 Agent

Use supported/illegal timing results to remove impossible candidates only
inside exact coverage. `unsupported` increases the human verification burden.
`decision_required` must be returned to the human. No outcome changes
`legality_authority: user_confirmed` or infers the resulting physical state.

Actionable identifiers retain their type: `replacement_ids` identifies
replacement effects, `event_ids` identifies events awaiting an order, and
`decision_ids` identifies an unresolved decision from a consuming service.
Consumers must not relabel one kind as another merely to fit the envelope.

### Match Analyst (planned)

Bind each normalized source event to the check that reconstructed it. Review
may classify a rules error only inside supported coverage; Commentary may
explain confirmed traces. Unsupported or missing input becomes an uncertainty
label, never a fabricated event or misplay.

## Capability manifest (ADR-0002)

`engine-check.v1` names its schema major and ruleset baseline. ADR-0002 adds
two more axes, carried in an optional `capability` block:

| Field | Meaning |
| --- | --- |
| `manifest_id` | The capability manifest this check was produced under |
| `capability_set_id` | Hash of exactly which operations, procedures, clauses and exclusions the engine supports |
| `implementation_identity` | Hash of the engine source files that ran |

The manifest is derived from the engine, never written by hand:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/capability_manifest.py build `
  --output manifest.json

python ${CLAUDE_SKILL_DIR}/scripts/capability_manifest.py verify manifest.json
```

`verify` rebuilds from the live engine and lists every disagreement — a stale
implementation hash, an operation the engine gained or lost, a changed
locator — and exits non-zero without writing anything. The committed copy lives
in `data/engine_capability_manifest/manifest.json` and CI fails when it is stale.

The block is optional. A check without it is still valid; a check with it must
carry all three fields, and binding one never changes the check's outcome or
`result_hash`. Two builds that support the same things share a
`capability_set_id` and differ only in `implementation_identity`.

## Combat steps (ADR-0008)

`check_kind: combat_step` wraps `combat.py`: `combat-step <timing> <effect>
--step stage|open|sync`. Supported scope names staging, opening, designations
and Attack/Defend triggers; Combat Damage, the Combat Cleanup, the result, and
G2 control or scoring stay in the unsupported scope until their packages land.
A `location_selection_required` result wraps as `decision_required` of kind
`location_choice` naming the Turn Player; a Battlefield with three
controllers, an active Showdown of unknown location, or a `contested_by`
outside the participants wraps as `unsupported`, never as a guessed Combat.

`check_kind: standard_move` wraps `combat.standard_move`: `standard-move
<timing> <effect> <declaration>` with a `riftbound-standard-move-declaration.v1`
naming actor, units, destination and the exhaust-cost confirmation. A
forbidden route (Battlefield to Battlefield without Ganking, a Unit already
at its Base, an exhausted Unit, the wrong turn or state) is `illegal`; a
missing cost confirmation is `decision_required` of kind `cost_choice`;
a malformed declaration or a stale unit identity is `invalid_input`.

## Version and extension rule

The schema reserves `legal_action`/`legal_action_v1`, but the current runner
does not produce it. R4 must add a real service and conformance cases before
that kind is emitted. Adding a component, coverage id, outcome, or authority
meaning requires a schema/version decision; a consumer-specific field belongs
in the consumer artifact, not this shared envelope.
