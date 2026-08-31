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

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py timing timing-state.json `
  --payload proposed-action.json --output timing-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py effect effect-state.json `
  effect-program.json --output effect-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py resolution timing-state.json `
  chain-item-id effect-state.json effect-program.json `
  --cleanup-decisions cleanup-decisions.json --output resolution-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py cleanup effect-state.json `
  --cleanup-decisions cleanup-decisions.json --output cleanup-check.json

python ${CLAUDE_SKILL_DIR}/scripts/engine_check.py validate engine-check.json
```

Use `--include-raw` only when the consumer needs the full trace/state proposal.
Use repeatable `--assumption` and `--missing-information` flags to keep the
artifact's epistemic boundary explicit. The check id is deterministic for the
same kind, inputs, and underlying result.

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

### Player 2 Agent

Use supported/illegal timing results to remove impossible candidates only
inside exact coverage. `unsupported` increases the human verification burden.
`decision_required` must be returned to the human. No outcome changes
`legality_authority: user_confirmed` or infers the resulting physical state.

### Match Analyst (planned)

Bind each normalized source event to the check that reconstructed it. Review
may classify a rules error only inside supported coverage; Commentary may
explain confirmed traces. Unsupported or missing input becomes an uncertainty
label, never a fabricated event or misplay.

## Version and extension rule

The schema reserves `legal_action`/`legal_action_v1`, but the current runner
does not produce it. R4 must add a real service and conformance cases before
that kind is emitted. Adding a component, coverage id, outcome, or authority
meaning requires a schema/version decision; a consumer-specific field belongs
in the consumer artifact, not this shared envelope.
