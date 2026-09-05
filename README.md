# Riftbound Chronicle

An evidence-aware AI assistant for building, learning, and practising physical
**Riftbound** decks.

[繁體中文](README.zh-TW.md) · [한국어](README.ko.md)

Keywords: Riftbound AI agent, deck coach, rule consult, Player 2 agent, TCG
deckbuilding, gameplay assistant, Claude Skill.

## Why this exists

A language model can "judge" a card interaction without any of this machinery.
It will just be judging by plausible-sounding text continuation, which is not
the same thing as legality. It will read a Reaction card and conclude you may
insert it at the end of a Showdown to add Might, because that reads fine — and
it is not a legal play.

So the program owns the mechanical part. When you may play what, what can be
responded to, how priority passes, what the current score and costs and Might
actually are: these are rule-governed and arithmetic, and handing them to a
model invites drift. Even the strongest model will still tell you 8.11 is
greater than 8.9 unless something checks the number.

The model then reasons inside the space the program has already constrained,
under the same external constraints as the real rules. That is the whole
design: **not translating the rules so the model can read them, but bounding
what the model is allowed to conclude.**

Today the program owns *timing and permission*. Full legality is still
confirmed by the human — see the Player 2 boundary below — and automated rules
enforcement is not currently approved by Riot in any case. Enumerating legal
actions is a planned release gated on conformance coverage, not on collecting
more game records first.

The project is split into three systems with deliberately different authority:

| System | Purpose | Authority boundary | Runnable artifact |
| --- | --- | --- | --- |
| `deck-coach` | Analyse a deck, suggest construction directions, and teach its game plan | Advice only; no win-rate or tier claims | Profile, recommendation mask, primer, evaluation, A/B primer battle |
| `rule-consult` | Explain a rule or interaction with dated sources and explicit assumptions | Unofficial consultation; never changes game state or replaces the Head Judge | Consultation record and evidence ledger |
| `player2-agent` | Propose Player 2 decisions during human-operated physical practice | The human owns hidden information, legality, resolution, and state updates | Append-only P2-A session ledger |

### Engine connection

A system counts as connected only when all six checklist conditions pass:
artifact accepts the envelope, runner produces it, validator rejects overclaims,
UI renders the outcomes, regressions cover a supported and an abstaining case,
and the authority boundary survives. `skill/scripts/check_readme_connection_claims.py`
derives this table from the artifacts and fails if the table drifts either way.

| System | Status | Conditions |
| --- | --- | ---: |
| `rule-consult` → `engine-check.v1` | `connected` | 6 / 6 |
| `player2-agent` → `engine-check.v1` | `connected` | 6 / 6 |
| `deck-coach` → `engine-check.v1` | `connected` | 6 / 6 |
| `match-analyst` → `engine-check.v1` | `planned` | 0 / 6 |

Deck Coach consumes the envelope as rules-consistency evidence only (ADR-0006):
attaching a check never changes the diagnosis or primer, and it produces no
checks of its own. Match Analyst is specified, fixtured, and not routed.

The current Player 2 implementation is **P2-A**: the Agent recommends and
explains an action, then waits for the human to confirm legality and the resulting
state. The future **P2-S** simulator is documented but is not implemented.

All systems share a **Chronicle-owned sovereign rules core**, and it only ever
claims what its conformance suite executes:

- a timing and permission kernel for the four turn states, Action/Reaction,
  Priority/Focus, and HOT/FEPR —
  21 executable cases (`skill/data/rules_core_cases.json`);
- a bounded typed-effect IR — 20 operations plus sequencing, targets, linked
  effects, lethal cleanup, and trigger emission, which **fails closed** on any
  card behaviour it does not model rather than guessing one;
- an atomic bridge between the two, so a timing decision and its typed effects
  commit together or roll back together.

It has no runtime dependency on another fan simulator, and it does not claim
complete card-effect resolution — the `unsupported` outcome is a first-class
result, not an error path. See the
[sovereign rules-layer architecture](docs/architecture/SOVEREIGN_RULES_LAYER.md)
and [ADR-0001](docs/decisions/ADR-0001-sovereign-rules-layer.md) for why this
layer exists at all after two audits advised against one.

A fourth system, `match-analyst` (post-game Review and Commentary over one
normalized timeline), is fully specified but **deliberately not routed** until
its activation gates pass — see
[the spec](docs/match-analyst/MATCH_ANALYST_PRODUCT_SPEC.md). The table above
lists what the Skill router actually exposes today.

**All four sit in the preparation phase; none of them plays the game.**
Construction, knowledge, practice, review — the game itself is played by people,
away from this. That is why an authoritative rules engine, including an official
digital client should one ship, would strengthen these rather than replace them:
such an engine serves play, and this serves preparation.

This is an assistant for preparation, built for research and educational use.
**Using it during an event is against tournament rules** — see
[the compliance boundary](docs/policy/RIOT_COMPLIANCE_BOUNDARY.md) for the
governing clauses.

The repository name intentionally stays `riftbound-chronicle`: it is the product
brand. Search terms such as `AI agent`, `deck coach`, and `rule consult` belong in
the GitHub description, topics, README, and Skill metadata rather than replacing
the brand name. See the [GitHub discovery metadata](docs/discovery/GITHUB_METADATA.md).

## Quick start

Requirements: Git and Python 3.10 or newer. The static demonstrations need no
package installation or build step.

Clone the repository, then run a complete Deck Coach case:

```powershell
git clone https://github.com/Zaious/riftbound-chronicle.git
cd riftbound-chronicle
python skill/scripts/deck_coach_pipeline.py run `
  --case-id DC-RNG-GLOBAL-001 `
  --output-dir deck-coach-output
```

The command writes five reviewable files:

```text
deck-coach-output/
  input.json
  profile.json
  mask.json
  primer.json
  evaluation.json
```

Open any demonstration directly in a browser:

- [Deck Coach review workspace](prototype/deck-coach/index.html)
- [Rule Consult evidence workspace](prototype/rule-consult/index.html)
- [P2-A practice workspace](prototype/p2a/index.html)

The pages are local, dependency-free demonstrations. They do not call a model,
persist browser data, or silently automate rules. Each one exposes the artifact
contract that a model or product integration would use.

## Deck Coach closed loop

Deck Coach does not send a bare card-name list directly to a language model. It
first creates a structured observation that can be inspected and graded:

```text
decklist + environment + player level
  -> structured deck profile
  -> recommendation mask
  -> eight-section primer
  -> seven-dimension evaluation
  -> optional blind A/B primer battle
```

The profile records:

- Legend and Chosen Champion;
- format, region, legal set pool, and player level;
- Energy curve, Domains, and Power requirements;
- unit, spell, Gear, and Battlefield mix;
- eight qualitative card roles;
- interaction, draw/selection, recursion, and movement density;
- engine anchors and candidates;
- provenance, confidence, and unresolved data gaps.

Before recommending cards, the mask rejects candidates that are known to be:

- unreleased in the selected environment;
- banned in the selected format;
- outside the Legend's Domain identity;
- unavailable in the player's collection;
- based on stale pre-errata text; or
- drawn from a mismatched tournament environment.

The bundled legality snapshot is only a dated input. A real recommendation must
still re-check current official sources.

There are 5 executable cases in `skill/data/deck_coach_cases.json`: a global
Rengar deck, a Taiwan Rengar environment, an Annie mask stress case, a Legend
that is legal in 1v1 and banned in 2v2, and a fully legal deck where the
player's collection is the only thing constraining the advice. The evaluation contract scores:

1. card and rules facts;
2. format and regional legality;
3. deck identity;
4. engine recognition;
5. actionable advice;
6. evidence and confidence; and
7. correct abstention.

The deterministic evaluator is a regression-test proxy, not an expert or a
claim of strategic truth. Primer battles therefore keep automatic preference and
human expert preference as separate fields.

See [Deck Coach evaluation plan](docs/evaluation/EVALUATION_PLAN.md) and the
[Deck Coach method](skill/references/deck-coach/deck-coach.md).

### Rift Atlas handoff

The repository also includes an offline bridge for a user-pasted Rift Atlas
decklist. It records a public deck URL as provenance, then writes the existing
Deck Coach input, profile, recommendation mask, eight-section primer scaffold,
and a human-readable brief:

```powershell
python skill/scripts/riftatlas_bridge.py `
  --source-url https://riftatlas.com/decks/community/DECK_ID `
  --deck-file decklist.txt `
  --environment global-vendetta `
  --player-level new `
  --output-dir riftatlas-output
```

The adapter does not scrape Rift Atlas, call a private API, or automate
gameplay. Partnership drafts and unaccepted localization material are kept
outside the public repository until the other maintainer agrees to publish
them.

## Rule Consult

Rule Consult is for players who need a careful explanation, including detailed
interactions, without pretending that the assistant is an official judge.

Every answer separates supplied facts from assumptions and records:

- the question and relevant game state;
- the controlling rule or tournament procedure;
- source URL, document version, and checked date;
- analysis and conclusion;
- confidence and unresolved ambiguity;
- escalation to the live Head Judge when appropriate;
- `official_status: unofficial` and `state_effect: none`.

For tournament procedure, the working precedence is event addendum, Tournament
Rules, Core Rules where unmodified, then the live Head Judge. The versioned
[source registry](skill/data/rules_source_registry.json) prevents the Core Rules
PDF from being treated as a complete or permanently current authority.

See [Rule Consult method](skill/references/rule-consult/rule-consult.md) and the
[rule corpus engineering note](docs/architecture/RULE_CORPUS_ENGINEERING.md).

### Optional local rule documents

The public repository does not commit Riot-owned rule documents. When exact clause
work is needed, install the controlling English pair locally. The optional
Simplified Chinese pack adds regional rules, FAQs, errata, and separately
labeled judge guidance:

```powershell
python skill/scripts/bootstrap_rules.py --yes
python skill/scripts/bootstrap_rules.py --include-supplemental-en --yes
python skill/scripts/bootstrap_rules.py --include-zh-cn --yes
python skill/scripts/rules_index.py build
python skill/scripts/rules_index.py search "連鎖 結算"
```

Selected files go into the ignored `skill/.local/rules/` directory with a local
SHA-256 lock and a page-addressable SQLite index. Results retain source,
version, locale, authority, page, and rule locator; they are evidence candidates,
not automated rulings. The English supplemental pack includes errata PDFs and
an HTML snapshot of the superseded Origins FAQ; default search masks that FAQ.
A custom location is available through
`RIFTBOUND_RULES_DIR` or `--rules-dir`. English controls translation conflicts,
and superseded sources are excluded from current search by default.

## Player2 Agent

P2-A supports one person practising with two physical decks while the Agent
chooses a strategic direction for Player 2. The ledger permits three event types:

```text
human confirms visible state
  -> Agent proposes an action and rationale
  -> human confirms legality
  -> human resolves it physically and confirms the new state
```

The Agent cannot inspect opponent hidden information, claim that its proposal is
legal, infer the post-resolution state, or enable P2-S behaviour. Automated
shuffling, draws, rules enforcement, combat resolution, scoring, winner
determination, self-play, and reinforcement learning are outside this runtime.

See the [P2-A product specification](docs/player2-agent/P2A_PRODUCT_SPEC.md) and
[P2-S future proposal](docs/player2-agent/P2S_FUTURE_PROPOSAL.md).

## Source authority

The shared authority model is:

1. current official Riot rules, tournament documents, errata, ban lists, and
   product announcements;
2. official card text available to the project;
3. reputable community material for observed play and terminology;
4. explicit inference, labelled as inference;
5. unknown, when the evidence does not support a conclusion.

Sources keep provenance and effective dates. Card facts, legal environments,
observed strategy, and model inference are not interchangeable.

The bundled card snapshot contains 1,451 rows and 1,304 unique card IDs from the
unofficial RiftCodex API. It makes this Skill portable, but a clean clone cannot
regenerate the file byte-for-byte and it is not official Riot API data. Read the
[data provenance and limitations](skill/data/README.md) before redistributing or
building a public product from it.

## Repository map

Design rationale worth reading before changing the rules layer:
[ADR-0001](docs/decisions/ADR-0001-sovereign-rules-layer.md) (why a rules layer
exists after two audits advised against one, and what it does *not* claim),
[RELATED_WORK](docs/architecture/RELATED_WORK.md) (where this sits in published
work), and [ITERATION_INPUTS](docs/research/ITERATION_INPUTS.md) (research that
should change what gets built next).

```text
skill/
  SKILL.md          mode router
  references/       system methods and shared source policy
  data/             cases, environment snapshots, registries, card snapshot
  schemas/          versioned JSON artifact contracts
  scripts/          CLIs, evaluators, and deterministic checks
prototype/
  deck-coach/       profile, mask, primer, and evaluation review
  rule-consult/     cited consultation and evidence ledger
  p2a/              human-confirmed practice session
docs/
  product/          product scope
  architecture/     three-system boundaries
  evaluation/       evaluation design
  player2-agent/    P2-A specification and gated P2-S proposal
  policy/           Riot boundary and application package
  audits/           dated independent and implementation reviews
```

Start with [product scope](docs/product/PRODUCT_SCOPE.md), then read the
[systems architecture](docs/architecture/SYSTEMS_ARCHITECTURE.md).

## Validation

Run every deterministic gate, exactly as CI does — the loop discovers the
checks on disk, so it cannot drift out of date the way a hand-copied list can
(this list previously omitted four gates, including the rules-core ones):

```powershell
Get-ChildItem skill/scripts/check_*.py | ForEach-Object {
  python $_.FullName
  if ($LASTEXITCODE -ne 0) { Write-Error "FAILED: $($_.Name)" }
}
```

`.github/workflows/ci.yml` is the authority on what runs on push; it also
re-runs the suite from a directory outside the repository to prove the scripts
do not depend on the working directory.

## Compliance

This repository intentionally does not publish or retain win rates, play rates,
matchup rates, or tier rankings. It does not claim official judge authority and
does not automate a Riftbound match. See the dated
[Riot compliance boundary](docs/policy/RIOT_COMPLIANCE_BOUNDARY.md) for the full
product interpretation and open questions.

Two important issues remain open:

- Riot product registration or written approval is not represented as granted.
- The bundled card data comes from an unofficial community API rather than an
  official Riot API source.

Those limitations are recorded plainly so a prototype cannot be mistaken for an
approved public deployment.

## Roadmap

- expand full-deck expert-reference cases and regional environments;
- collect blind expert preferences for real model-generated primers;
- replace unofficial card data with an approved, reproducible source adapter;
- connect the three artifact contracts to a model without weakening their
  authority boundaries;
- keep P2-S planned but unimplemented unless Riot approval and a separate product
  decision justify opening that gate.

## License and Riot notice

Original code and methodology are licensed under [MIT](LICENSE). The bundled card
names, rules text, and other Riot-owned material are not covered by that grant;
see [skill/data/README.md](skill/data/README.md) for provenance.

> Riftbound Chronicle was created under Riot Games' "Legal Jibber Jabber" policy
> using assets owned by Riot Games. Riot Games does not endorse or sponsor this
> project.

Riftbound Chronicle is an unofficial fan project and is not affiliated with Riot
Games.
