# Evaluation Plan

Status: initial executable baseline
Date: 2026-08-24

Evaluation is mode-specific. A fluent answer is not sufficient evidence that the system did the correct job.

## Deck Coach

Current executable fixtures: `skill/data/deck_coach_cases.json` contains three closed-loop cases covering a verified global list, a cross-environment import, and the complete recommendation-mask failure surface. Each includes player level, required engine/weakness recognition, forbidden claims, acceptable uncertainty, an eight-section expert reference, and dated sources. The four published worked primers remain separately checked by `check_deck_primer.py`.

`deck_coach_pipeline.py suite` produces machine-readable reports in seven dimensions. `battle` compares two candidates with blind A/B labels and records automatic and expert preference separately. The deterministic grader is a regression proxy, not an expert; human overrides/preferences must remain visibly attributed.

Evaluate on fixed decklists and deck-construction prompts:

- card and legality factual accuracy;
- correct environment and freshness handling;
- engine and functional-role identification;
- internal consistency between deck diagnosis and primer;
- unsupported-claim rate;
- evidence-tier accuracy;
- expert preference on usefulness and clarity.

Do not use or publish metagame-defining win-rate or matchup-rate metrics.

## Rule Consult

Current deterministic fixtures: `skill/data/rule_consult_cases.json` covers mechanics, interactions, tournament procedure, source conflicts, translations, errata, and supersession against the dated source registry. `check_rules_index.py` separately tests bilingual retrieval, exact-locator ranking, authority labels, and stale-source masking. Expert grading of free-form Agent answers remains a separate eval.

Build a versioned interaction-case corpus from current official rules, Tournament Rules, FAQs, errata, and clearly labeled community rulings.

Measure:

- conclusion accuracy;
- citation correctness;
- source-precedence correctness;
- stated-assumption completeness;
- uncertainty calibration;
- correct escalation to Head Judge or official support;
- absence of false claims of official authority.

## Player 2 Agent P2-A

Use manually authored scenarios whose candidate actions have already been checked by humans.

Measure:

- visibility-boundary compliance;
- agreement with expert-preferred actions, reported as scenario agreement rather than game win rate;
- quality of alternatives and explanation;
- consistency with the deck's declared plan;
- state-ledger integrity;
- correct request for human legality and post-resolution confirmation;
- refusal to infer or enforce a missing state transition.

## Compliance regression

The deterministic P2-A validator must reject:

- `automation_level` other than `P2-A`;
- `p2s_enabled: true`;
- engine-derived state or rules-engine legality authority;
- proposals marked legal before human confirmation;
- action confirmations that claim to produce an authoritative derived state;
- unknown event types that could bypass the protocol;
- stored Player 1 hidden information fields.

The Rule Consult validator must reject official impersonation, game-state fields, final answers without an official source, High confidence with a material assumption, and invalid escalation. The Deck Coach validator must reject unknown role IDs, fabricated role coverage, missing primer sections, and metagame rate/score fields.

## P2-S research metrics

Not active. Any future self-play or reinforcement-learning evaluation requires a separate approved policy. No P2-S metric or dataset is part of the current implementation.
