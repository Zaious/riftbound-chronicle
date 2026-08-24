# Riftbound Chronicle

An evidence-aware AI assistant for building, learning, and practising physical
**Riftbound** decks.

[繁體中文](README.zh-TW.md) · [한국어](README.ko.md)

Keywords: Riftbound AI agent, deck coach, rule consult, Player 2 agent, TCG
deckbuilding, gameplay assistant, Claude Skill.

The project is split into three systems with deliberately different authority:

| System | Purpose | Authority boundary | Runnable artifact |
| --- | --- | --- | --- |
| `deck-coach` | Analyse a deck, suggest construction directions, and teach its game plan | Advice only; no win-rate or tier claims | Profile, recommendation mask, primer, evaluation, A/B primer battle |
| `rule-consult` | Explain a rule or interaction with dated sources and explicit assumptions | Unofficial consultation; never changes game state or replaces the Head Judge | Consultation record and evidence ledger |
| `player2-agent` | Propose Player 2 decisions during human-operated physical practice | The human owns hidden information, legality, resolution, and state updates | Append-only P2-A session ledger |

The current Player 2 implementation is **P2-A**: the Agent recommends and
explains an action, then waits for the human to confirm legality and the resulting
state. The future **P2-S** simulator is documented but is not implemented.

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

Three executable cases currently cover a global Rengar deck, a Taiwan Rengar
environment, and an Annie mask stress case. The evaluation contract scores:

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

See [Rule Consult method](skill/references/rule-consult/rule-consult.md).

### Optional local rule PDFs

The public repository does not commit Riot-owned rule PDFs. When exact clause
work is needed, install the two official documents locally:

```powershell
python skill/scripts/bootstrap_rules.py --yes
```

This downloads Core Rules and Tournament Rules into the ignored
`skill/.local/rules/` directory and writes a local SHA-256 lock file. A custom
location is available through `RIFTBOUND_RULES_DIR` or `--rules-dir`. The Skill
never silently downloads documents during a question; if the local pair is
missing, it asks for the bootstrap or a current official source.

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
[three-system architecture](docs/architecture/THREE_SYSTEMS_ARCHITECTURE.md).

## Validation

Run the same deterministic checks used by CI:

```powershell
python skill/scripts/check_data_integrity.py
python skill/scripts/check_links.py
python skill/scripts/check_deck_primer.py
python skill/scripts/check_legend_packets.py
python skill/scripts/check_tournament_lists.py
python skill/scripts/check_deck_coach.py
python skill/scripts/check_deck_coach_prototype.py
python skill/scripts/check_rule_consult.py
python skill/scripts/check_rule_consult_prototype.py
python skill/scripts/check_prototype_ui.py
python skill/scripts/check_rules_bootstrap.py
python skill/scripts/check_p2a_protocol.py
python skill/scripts/check_p2a_prototype.py
```

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
