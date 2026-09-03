# Deck Coach

Deck Coach owns deck construction, deck diagnosis, substitutions, deck primers, and teaching a player how to operate a finished list.

## Load the right books

- For construction, legality, role coverage, ratios, cuts, substitutions, or regional card-pool questions, read `${CLAUDE_SKILL_DIR}/references/deckbuilding/deckbuilding.md` completely.
- For mulligan plans, turn priorities, sequencing, Showdown posture, common lines, common mistakes, or a complete deck primer, read `${CLAUDE_SKILL_DIR}/references/gameplay/gameplay.md` completely.
- For a request that evaluates and then teaches a finished list, read both books. Keep their jobs separate in the answer.

Read `${CLAUDE_SKILL_DIR}/references/shared/source-authority.md` whenever the answer names current cards, legality, errata, or tournament procedure.

When a primer asserts a concrete Action/Reaction sequence, response window,
Priority/Focus decision, or Chain order, also read
`${CLAUDE_SKILL_DIR}/references/shared/rules-core.md`. Represent the proposed
timing state and run `rules_core.py validate-timing` where v1 coverage applies.
If the sequence depends on unsupported card behavior, keep it provisional and
route the detailed interaction through Rule Consult rather than filling the gap
with fluent prose.

## Output ownership

Deck Coach may explain the mechanics needed to understand advice. When the user asks for a detailed interaction determination, consult `rule-consult` and label that section as an unofficial rules analysis. Do not make a detailed ruling silently inside a strategy answer.

A live Player 2 move belongs to `player2-agent`. Deck Coach may supply the deck plan and strategic priorities that Player 2 Agent uses, but does not own the session ledger or confirm an action's legality.

## Closed-loop workflow

For a reproducible review, use `${CLAUDE_SKILL_DIR}/scripts/deck_coach_pipeline.py`. Its minimum input is `decklist + environment + format + player_level + Legend`; the input schema is `${CLAUDE_SKILL_DIR}/schemas/deck-coach-input.schema.json`.

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/deck_coach_pipeline.py run `
  --case-id DC-RNG-GLOBAL-001 `
  --output-dir deck-coach-output
```

That one command writes normalized input, `deck-profile.v1`, `recommendation-mask.v1`, an eight-section baseline primer, and `deck-coach-evaluation.v1`.

### Structured observation

The profile computes card-name lookup coverage (what fraction of the decklist's copies matched a card in the bundled snapshot by name -- a data-resolution measure, unrelated to rules-engine coverage), environment/region/set pool, curve, printed Domains and Power costs, Unit/Spell/Gear mix, Battlefield package, interaction/draw-recursion/movement density, eight-role distribution, engine candidates, data provenance, and confidence. Role and engine detection are labelled text heuristics; do not promote them to verified gameplay claims without evidence.

When an R3 behavior manifest is supplied, read
`${CLAUDE_SKILL_DIR}/references/shared/card-behavior-coverage.md`. The profile
adds bounded Main Deck clause coverage, but it must remain separate from card
lookup confidence and strategic evidence. With no compatible active manifest,
the correct status is `unavailable`, not an inferred coverage percentage.

### Recommendation mask

Before naming a replacement, pass it through the mask. It excludes candidates that are unreleased in the target environment, banned in the selected format, outside the Legend's Domain identity, absent from a supplied collection, supported only by a different source environment, or paired with stale pre-errata text. The registry is dated and still requires a live official check for a real event; `provisionally_clear` is not an official deck-registration ruling.

### Evaluation and primer battle

`${CLAUDE_SKILL_DIR}/data/deck_coach_cases.json` contains executable cases with input deck, environment, player level, required engine/weakness recognition, forbidden claims, acceptable uncertainty, expert reference primer, and dated sources. `suite` runs all cases; `evaluate` scores another candidate; `battle` compares two versioned/model-labelled candidates using blind A/B labels and accepts a separately recorded expert preference.

The deterministic grader covers the seven declared dimensions and produces useful regression metrics, but it is a proxy. Expert gameplay quality must still be recorded as human scores or blind preference; never call token matching an expert judgment.

`deck_coach.py` and `deck-coach-session.v1` remain available for manually authored reviews. They are artifact editors, not the closed-loop profiler.

## Engine evidence intake (ADR-0006)

A session may carry `engine_checks` — complete `engine-check.v1` envelopes —
paired with `engine_evidence_scope: rules_consistency_only`. Both fields or
neither. Deck Coach consumes checks produced elsewhere from explicit structured
inputs; it does not build a timing state from primer prose.

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/deck_coach.py engine-check session.json --check engine-check.json
python ${CLAUDE_SKILL_DIR}/scripts/deck_coach.py engine-check session.json --result timing-result.json --kind timing
```

Attaching never changes the diagnosis, the primer, or behavior coverage; the
runner refuses if it would. A `supported` check is not evidence that a line is
good, an `unsupported` one means the component abstained, and a
`decision_required` one is shown, never answered here.

## Evidence discipline

Keep mechanically derived claims, verified real-play claims, and unverified recommendations visibly separate. Do not manufacture specific matchup, mulligan, or sequencing rules merely to fill a template. Preserve the existing Tier 1/2/3 contract in the underlying books.

Do not calculate, retain, or publish metagame-defining play rates, win rates, or matchup percentages.
