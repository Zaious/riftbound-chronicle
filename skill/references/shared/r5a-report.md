# R5-A report: coverage and abstention, measured

Status: implemented. The first tier of R5 in
[ENGINE_CAPABILITY_MILESTONES.md](../../../docs/plans/ENGINE_CAPABILITY_MILESTONES.md):
deterministic runners and metrics, which need no simulator, no policy, and no
Riot authorization.

The report answers one bounded question about the engine: **which exact
locators from its declared list do its own fixtures cite, do stored fixture
expectations still match, and when the engine declines, why?**

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/r5a_report.py build --output report.json
python ${CLAUDE_SKILL_DIR}/scripts/r5a_report.py validate report.json
```

## Denominators come from the engine

Locator exercise is *exact locator strings cited by executed fixtures* over
*exact locator strings the capability manifest declares*. The manifest is
derived from the engine, so the denominator cannot be padded by hand and a
locator the engine stops citing drops out of both sides at once.

Matching is exact: a fixture that cites `Core 310.1.a`
does not count toward the manifest's `Core 308–310`, and lands in
`fixture_citations_outside_declared_locators` instead. This is the governing
decision: a sub-clause proves only that exact citation was exercised; it never
proves an entire declared range. The metric is therefore named
`locator_exercise`, not rules coverage. Read both locator lists; the ratio
alone is not a correctness or completeness score.

Likewise, `fixture_conformance` only says the live code still matches stored
expectations. It does not independently validate those expectations against
the official rules.

## Abstention, split by cause

| Bucket | What lands there |
| --- | --- |
| `missing_state` | `invalid_input` checks; `indeterminate` legal-action candidates; Match Analyst logs with an uncertainty ledger |
| `unsupported_mechanic` | `unsupported` checks and candidates |
| `source_conflict` | Rule Consult `source_conflict` cases; Match Analyst logs with derived contradictions |
| `stale_data` | behavior-coverage manifests or entries whose text hash no longer matches |
| `decision_required` | checks waiting on a controller choice |

A bucket that goes empty fails the gate, because it means the fixture that
proved the engine can decline that way has gone missing.

## What it is not

`claims` are constants — `search`, `policy_strength`, `p2s`, `matchup_rates`,
`complete_game`, `complete_legality`, all `false` — and a report with any of
them set fails validation. R5-B (bounded local search) waits for R4 Phase B
and G3; R5-C stays outside the roadmap. This report is what can be said now.
