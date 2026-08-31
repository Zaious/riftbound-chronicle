# Related Work

Status: living note
Date: 2026-08-30

Where this project's sovereign rules layer sits relative to published work. The
point of the note is to answer, in advance, the question any reviewer or
collaborator asks first: *this problem has been worked on before — what is
different here, and what is merely re-done?*

Everything below was checked by reading the source, not recalled. One
frequently-circulated item is a hoax and is flagged as such at the bottom so it
does not get picked up again.

## 1. Card text to executable implementation

**Ling et al., *Latent Predictor Networks for Code Generation*, ACL 2016
(DeepMind + Oxford).** [arXiv:1603.06744](https://arxiv.org/abs/1603.06744)

This is the closest published ancestor of `effect_ir.py`, and it is the same
task: take a card's natural-language text plus its structured fields, and emit
the code that implements it. The paper introduced the datasets that are still
the standard reference for this problem — roughly 10,000 Magic: The Gathering
cards implemented in Java and about 500 Hearthstone cards in Python.

The difference is the direction of the arrow. Ling et al. *learn* the mapping;
this project *declares* it. That choice is not a claim that learning is
uninteresting — it follows from what the artifact is for. The paper reports
approximately 61% BLEU on Magic and 66% on Hearthstone, and the reported
qualitative failure is the instructive part: the model produced correct code for
the Hearthstone card **Madder Bomber** because the near-identical **Mad Bomber**
was in its training set, while failing on cards with no close neighbour.

That is success by surface similarity rather than by understanding the effect —
precisely the failure mode a rules layer cannot tolerate. **A 61%-accurate
effect implementation is worse than none for this purpose, because nothing tells
you which 39% is wrong.** It is the direct argument for `unsupported` being a
first-class outcome in this repository rather than an error path: refusing to
model a card is a usable answer; silently modelling it incorrectly is not.

Worth stating because it is widely misremembered: this line of work was never a
Magic-playing agent. Contemporary coverage
([Kotaku](https://kotaku.com/google-deepmind-is-now-analysing-magic-and-hearthstone-1767628685),
[Inverse](https://www.inverse.com/article/13400-google-deepmind-creates-bizarre-magic-the-gathering-and-hearthstone-cards))
records explicitly that there were no plans to have the system play. "DeepMind
tried to build an MTG AI and it went nowhere" is not what happened; the work was
code generation, and it succeeded at what it set out to measure.

## 2. LLM proposes, executable rules validate

**Lehrach, Hennes, Lazaro-Gredilla, Lou, Wendelken, Li, Dedieu, Grau-Moya,
Lanctot, Iscen, Schultz, Chiam, Gemp, Zielinski, Singh, Murphy, *Code World
Models for General Game Playing*.**
[arXiv:2510.04542](https://arxiv.org/abs/2510.04542)

The nearest current analogue to this project's core architectural claim. The
LLM proposes candidate actions; an executable formal representation of the rules
is the authority that validates them, and the system fails closed — rejecting
moves — when the executable model cannot represent the rule in question, rather
than letting a possibly-invalid action through.

That is the same division of labour this repository states as its design
principle: bound what the model is allowed to conclude rather than translate the
rules for it to read. The convergence is worth naming honestly — this is not a
novel architecture, it is an application of a pattern independent groups arrived
at for the same reason.

What differs is the setting rather than the mechanism, and the differences are
what any contribution has to rest on:

- **The authority boundary is human, not merely formal.** Here, legality is
  confirmed by a person (`legality_authority: user_confirmed`), and a proposal
  carries `legality_status: "unverified"` as a schema constant. The formal core
  returns a bounded verdict — its `coverage` field is likewise a constant,
  `timing_permission_v1` — and does not become the arbiter. This is a deliberate
  product and compliance constraint (automated rules enforcement is not
  currently approved by Riot), not a limitation being worked around.
- **Physical play, not a simulator.** The state is a human-authored summary of a
  real table, so the system cannot assume a complete machine-resolvable game
  graph. See [SYSTEMS_ARCHITECTURE.md](SYSTEMS_ARCHITECTURE.md).
- **A living rules corpus with provenance.** Rules here are dated, versioned,
  supersedable documents carrying an authority label, not a fixed specification.

## 3. Why the rules of a real TCG resist a complete engine

**Churchill, Biderman, Herrick, *Magic: The Gathering is Turing Complete*, FUN
2021.** [arXiv:1904.09828](https://arxiv.org/abs/1904.09828) ·
[LIPIcs](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.FUN.2021.9)

Optimal play in real Magic is at least as hard as the halting problem; an
arbitrary Turing machine can be embedded in a game using tournament-legal decks,
without relying on stochasticity or hidden information.

This is not a claim about Riftbound, and it is not an excuse. It is the reason
the release boundary in [SOVEREIGN_RULES_LAYER.md](SOVEREIGN_RULES_LAYER.md) is
phrased as it is: for a sufficiently expressive TCG, "we implement the rules" is
not a finishable statement, so the honest form of the claim is always *this
bounded set, with this conformance coverage, and an explicit `unsupported`
outcome for the rest*. Bounded coverage plus a refusal is not a weaker position
than completeness — for this class of game it is the only defensible one.

## 4. Supplying legal actions to an LLM player

**Multiplayer UNO with LLM agents.**
[arXiv:2509.09867](https://arxiv.org/abs/2509.09867) — the prompt carries the
rules, the current state, *and the enumerated legal actions*. The same pattern
appears in Hanabi-based LLM agent work, and structured-output constraints
(JSON-schema-shaped actions) are used elsewhere to reduce illegal-move parsing.

Two things follow. First, supplying legal actions to the model is established
practice rather than an open question — the interesting part is who computes
them and who is accountable for them, which is exactly what R4 (legal-action
enumeration) and the P2-A human gate are about. Second, those settings enumerate
actions from a complete simulator; this project cannot, because the state is a
human summary of a physical table. R4 therefore has to produce a
*perspective-safe* enumeration over an incomplete state, which is a harder and
less-studied version of the same step.

A broader map of this area:
[git-disl/awesome-LLM-game-agent-papers](https://github.com/git-disl/awesome-LLM-game-agent-papers)
(survey, ACM CSUR).

## 5. What appears not to be covered

Stated as an open question rather than a claim of novelty. This note is not a
systematic survey, and an absence here is weak evidence.

- **Authority separation as an implementation invariant.** The
  `state_confirmed` / `action_proposed` / `action_confirmed` split, where the
  resulting position is never inferred from an accepted action but must be
  re-confirmed by the human, is enforced by schema and regression tests here
  rather than stated in a disclaimer. Human-in-the-loop AI is well studied; a
  *machine-checked* record of which party held authority over each transition
  during physical play is where an HCI contribution would sit, if one exists.
- **Evidence-tier accuracy as an evaluation dimension.**
  [EVALUATION_PLAN.md](../evaluation/EVALUATION_PLAN.md) scores unsupported-claim
  rate and evidence-tier accuracy alongside task correctness, and keeps automatic
  and human expert preference in separate fields. Grading an assistant on
  *whether it correctly represented its own uncertainty* is less common than
  grading the answer.
- **A regionally-lagged legal card pool as a first-class environment.**
  [regional-legality-model.md](../../skill/references/deckbuilding/references/regional-legality-model.md)
  treats "this market is three sets behind and inherits a ban list calibrated
  against cards it cannot buy" as a modelled condition. This is a real and
  recurring situation for localized TCGs and does not appear to be treated as an
  environment variable in the work above.

## Not usable — flagged so it is not picked up again

[`tmikonen.github.io/quantitatively/2019-04-01-deep-ai/`](https://tmikonen.github.io/quantitatively/2019-04-01-deep-ai/)
circulates as a description of a deep-RL agent trained on Magic's Alpha set. It
is an **April Fools' Day piece**, labelled as such by its own author in an update
at the top ("this special post, published on April 1st, is just that"). The
"Alpha Alpha" project it describes does not exist. Do not cite it, and do not
use it as narrative material.
