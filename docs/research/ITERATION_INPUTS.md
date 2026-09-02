# Research Inputs for Iteration

Status: living note
Date: 2026-08-30

Distinct from [RELATED_WORK.md](../architecture/RELATED_WORK.md), which answers
"where does this sit relative to published work." This note answers a narrower,
more useful question: **which published results should change what we build
next, and how would we know whether they applied to us?**

Each entry names an open question that already exists in this repository, what
the literature says about it, the concrete implication, and a way to test
whether the concern is real here rather than merely plausible.

---

## 1. The human gate is the safety story, and the literature says it degrades

**The open question.** P2-A's entire safety argument rests on a human confirming
legality: `legality_authority: user_confirmed`, `legality_status` pinned to
`"unverified"`, and a separate `confirmationEvent` carrying `legal` and
`confirmed_by`. The invariant is enforced in schema and regression tests. What
none of that establishes is whether the human is *actually verifying* or merely
clicking through.

**What the literature says.** This failure has a name and a shape. Human
reviewers drift into rubber-stamping — they come to trust an accurate system,
stop verifying, and approve by default, *while the record still shows a human
decision*. That last clause is the dangerous part for us: our ledger would look
identical in both worlds. Work on explanation and reliance frames over-reliance
not as carelessness but as a rational cost-benefit choice — if engaging with the
justification costs more than following the recommendation, a reasonable person
stops engaging ([Vasconcelos et al. on over-reliance as a cost-benefit
decision](https://arxiv.org/pdf/2208.04181); [explanation style and
reliance](https://arxiv.org/pdf/2410.20067); [interface design in high-stakes
decisions](https://arxiv.org/pdf/2501.16627)). The counter-measure with the most
support is exposing the system's own confidence so the human can rely
*differentially* — more when the system is likely right, less when it is not.

**The implication, and it is counterintuitive.** *Improving the rules core makes
the human gate weaker.* The better `rules_core` gets, the more reliably its
proposals are fine, the faster the human learns that confirming is a formality.
The safety property and the engineering goal pull in opposite directions, and
nothing in the current design notices this.

This gap was present in the first P2-A implementation: every proposal requested
the same confirmation whether the timing core supported it or abstained. X-02
resolves the artifact-level problem with `engine_checks` plus a deterministic
`verification_requirement`. Supported, unsupported, decision-required,
invalid-input, and illegal outcomes now demand different next steps while
`legality_authority` remains `user_confirmed`.

**Implemented response.** Differentiate the confirmation request by shared
`engine-check.v1` outcome, so `unsupported` visibly demands more verification,
`decision_required` and `invalid_input` must be resolved before relying on the
proposal, and `illegal` demands official-source review before a human override.
The point is not to weaken human authority — it remains theirs in every case.

**How we would know it is real.** The P2-A ledger is append-only and timestamped,
so this is measurable without new instrumentation: the interval between
`action_proposed` and its `confirmationEvent`, and the rate at which humans
answer `legal: false`. Confirmation latency collapsing toward zero, or a
disagreement rate that trends to nil as the core improves, is the signature of
rubber-stamping rather than of the core getting good. Neither number is currently
reported — and, checked rather than assumed, **neither can be: there is no
stored P2-A session anywhere in the repository, not even a fixture.** So the
honest form of this item is not "measure it now" but "when a session store is
built, build these two counters with it, because retrofitting them means
retrofitting the evidence for the safety claim." **Treat "the human confirmed
it" as a claim requiring evidence, on the same principle this project already
applies to every other claim.**

---

## 2. Abstention is a first-class outcome here, and there is now a literature for it

**The open question.** `unsupported` is deliberately a first-class result rather
than an error path, and `EVALUATION_PLAN.md` scores "correct abstention" as one
of seven dimensions. But abstention is currently graded by a deterministic proxy
that the plan itself labels a regression test, not an expert.

**What the literature says.** Abstention has become a measured subfield rather
than a design preference.
[AbstentionBench](https://arxiv.org/pdf/2506.09038) evaluates it across 20
datasets covering unanswerable questions, underspecification, false premises,
and outdated information, and reports that abstention remains unsolved and that
scaling models does not help — which is directly relevant, because it means this
capability has to be engineered rather than waited for. More pointed for us:
[UA-Bench](https://arxiv.org/html/2604.17293) argues that binary refusal is the
wrong frame, and that a system should identify *the source* of its uncertainty —
uncertainty attribution as a multi-class decision. There is also formal work:
[conformal abstention](https://arxiv.org/pdf/2604.27914) offers finite-sample
guarantees bounding both how often the system declines and how often its
non-abstentions are wrong.

**The implication.** We are accidentally aligned with the better frame and are
not exploiting it. `rules_core_check.outcome` is already multi-class —
`supported_legal_timing`, `supported_illegal_timing`, `supported_procedure`,
`unsupported` — which is uncertainty attribution, not binary refusal. Likewise
`coverage: timing_permission_v1` states the *scope* of the claim. But the
evaluation collapses this into a single "correct abstention" score, and
`rule-consult`'s confidence levels are a separate, unconnected vocabulary.

**What to consider.** Score abstention per attribution class rather than as one
dimension: declining because a card is unmodelled is a different event from
declining because sources conflict, and conflating them hides which one is
getting worse. The conformal work is a plausible later target for R4 — a bounded
legal-action enumerator is exactly the kind of component for which "how often may
this refuse, and how often is it wrong when it does not" could carry a real
guarantee rather than a measured rate.

**How we would know it is real.** Split the existing abstention dimension by
`outcome` value in the next evaluation run and see whether the classes move
independently. If they do, the single score was hiding something.

---

## 3. Perspective-safe enumeration over a human-reported state (R4)

**The open question.** R4 has to enumerate legal actions from a state that is a
human-authored summary of a physical table, not a complete machine-resolvable
game graph — and it must not leak Player 1 information the agent is not entitled
to.

**What the literature offers, and does not.** LLM-with-legal-actions work supplies
enumerated legal actions in the prompt, but enumerates them from a complete
simulator ([UNO](https://arxiv.org/pdf/2509.09867), and the Hanabi agent work);
[Code World Models](https://arxiv.org/abs/2510.04542) likewise validates against a
complete executable specification. The imperfect-information line (public belief
states, information-set search) assumes a well-defined information set, which
presumes a complete state model underneath.

**The implication.** The gap is genuine rather than a matter of not having
looked: the published approaches derive an information set from a complete
state, and we would have to derive a *usable action set from an incomplete,
human-reported one* — where "incomplete" is not statistical uncertainty but a
person having summarized in prose. The likeliest honest shape is that R4
enumerates only over what the summary determines and returns an explicit
`indeterminate` for the rest, which is the same fail-closed discipline the effect
IR already uses, applied one level up.

**Decision recorded 2026-09-02.** ADR-0003 adopts that bounded shape: Phase A
classifies user-supplied candidates and never claims a complete set; Phase B
engine enumeration requires structured observation, action-family generators,
and a machine-checkable completeness proof.

**How we would know it is real.** Before building R4, take a sample of real P2-A
`public_state` strings and ask how many support an unambiguous action
enumeration. If most do not, R4's contract is wrong on paper before any code is
written, and the interesting engineering is in what the state summary should ask
the human for — not in the enumerator.

---

## 4. Is Riftbound the right subject — and what the youth of the game actually buys

**The open question.** Not a literature question but a framing one, and it
governs which of the entries above are worth acting on. Riftbound is roughly a
year old, has essentially no AI research around it, no tournament-data corpus,
and a live and restrictive platform policy. Magic and Hearthstone have all of
the opposite. It is worth writing down why this is nonetheless the better
subject *for this work* — and where that stops being true.

**The question splits, and the two halves give opposite answers.**

*If the research question is "can an agent play a TCG well," Riftbound is a poor
choice.* There are no baselines to compare against, almost no data, and — this
is the part usually left unsaid — no community that could replicate or dispute a
result, which in practice makes a playing-strength claim unfalsifiable by peers.
A one-year-old game may also not survive; Magic's thirty years is itself a
research asset, because it guarantees the domain persists. The platform policy
is *more* restrictive here than Wizards', not less. For that question, go where
the substrate and the community already are.

*If the research question is "how do you build and govern a knowledge and rules
layer for a live, evolving, regionally fragmented game, with an assistant whose
authority is bounded and whose uncertainty is attributed," Riftbound is unusually
good — plausibly better than Magic.* No incumbent engine, so owning the rules
layer is defensible rather than redundant. A bounded card pool that makes R3
finishable at all. A rules corpus that genuinely moves, which is the only
condition under which versioning, supersession, and a freshness gate are
interesting rather than ceremonial. And a live regional-lag natural experiment
that, as far as this note's searching found, nobody treats as an environment
variable.

Every substantial thing this repository has built belongs to the second
question: the 46-Legend verification pass, the evidence tiers, the freshness
gate, the regional model, the authority invariants. None of it is about playing
strength.

**What the youth of the game actually buys — the strong form.** "Young game, so
it is interesting" is too weak, and it is also how a project talks itself into a
subject. The defensible version is a forcing function:

> A knowledge system for a mature game can be built by accumulation. Scrape
> enough results, the meta is known, the rules have settled, and the hard
> questions never have to be answered — they are papered over by data. A
> knowledge system for a game this young **cannot do that**. Every hard question
> is live and unavoidable: what may the system claim when there is no data? how
> does it version rules that change underneath it? how does it distinguish "we
> do not know" from "nobody knows yet"? There is no data to cheat with, so the
> honesty machinery has to be real or the system visibly fails.

That is why abstention, evidence tiers, and freshness are load-bearing here and
would be decoration on a mature game. It is hard to demonstrate that a system
correctly says "I don't know" in a domain where it always knows.

**And the window closes.** In a few years Riftbound will have tournament data, a
settled meta, and community engines, and this condition will be unreproducible.
`verification-log.md` is, incidentally, already a longitudinal record of a
game's knowledge base forming from nothing — dated rows, launch-window flags,
inference-versus-observation scoring, and "no public result found" recorded as a
finding rather than a gap. Nobody has that for Magic, because nobody was doing
it in 1993 with this discipline. **Keeping that record complete and dated is
worth doing on its own terms, before and independently of any paper** — and it
is the one asset that survives even if the game does not, because it documents a
method rather than a metagame.

**Where the subject choice starts hurting: R5.** Search and learning is exactly
where Riftbound's disadvantages dominate — no baselines, no game records, no
peer replication. R5 is already gated behind R4 conformance for engineering
reasons; there is a second reason to keep it narrow. If it is built, the
defensible framing is *an existence proof that the rules core can carry a
search procedure* over a small reproducible bounded environment — a claim about
the rules layer, which is portable — rather than *a strong Riftbound agent*,
which is a claim whose entire value is staked on a one-year-old game.

**How we would know this framing is wrong.** If a Riftbound AI research
community appears, or a community engine ships, the first answer changes and
some of this repository's sovereignty argument weakens (ADR-0001's alternative B
would deserve re-examination). Worth re-checking at each set release rather than
assuming the current emptiness is permanent.

**The stronger scenario: an official engine, including an official digital
client.** A community engine is the weak version of this question. The strong
version is Riot shipping a complete and authoritative one. Written down in
advance, because "we would still be valuable" is easier to say afterwards than
to defend.

*What genuinely dies.* The rules core's legality-checking value — an official
client is not *an* engine, it is *the* engine, and any disagreement resolves
against us by definition. R4's legal-action enumeration, which the client would
do natively and authoritatively. Match Analyst's timeline reconstruction for
digital play, since the client would emit logs. And R5 entirely: anyone doing
search or learning would use the official substrate. ADR-0001 would need a new
version — not its reasoning about authority, which is unaffected, but its scope.

*What survives, and why the four systems are strengthened rather than replaced.*
The architecture's claim was never "we own a rules engine"; it is "we bound what
the assistant may conclude, on what evidence, at what scope." An authoritative
engine *moves* that boundary rather than removing the need for one. Today:
we bound conclusions because there is no authority to defer to. Then: we bound
conclusions and defer legality to the authority. The `coverage` field was built
for exactly this — writing `official_client_v3` there is structurally identical
to writing `timing_permission_v1`.

Three things get stronger rather than merely surviving. Physical play does not
go away: Arena has existed for years and paper Magic still has competitive
preparation needs, and an official client does nothing for someone at a table
with cards. An engine answers "is this legal," never "why should I do this" —
Hearthstone has a perfect rules engine and its players still read guides and use
trackers, because a correct engine makes the coaching layer *possible* rather
than redundant. And regional legality gets *worse*, not better: a digital client
is global-current while paper Taiwan is three sets behind, so the gap between
"the client says this is legal" and "my local paper pool allows this" is a
problem the client creates. Meanwhile the layer we would most like to stop
paying for — bounded rules coverage, `unsupported` everywhere, 14 conformance
cases — is precisely the one it would take over.

*The non-technical risk, which is the real one.* If Riot ships an official
client they may become **more** restrictive toward third-party tools, not less,
because "why do you need a third party for this" gets harder to answer. That has
nothing to do with technical value and would decide whether the work can
continue. Partial mitigation: the category has precedent inside Riot's own
portfolio — League of Legends' third-party preparation ecosystem — and P2-A's
use is confined to practice by the game's own rules (Tournament Rules 417.1;
see `../policy/RIOT_COMPLIANCE_BOUNDARY.md`). Neither transfers automatically to
the Riftbound policy, which currently prefers multi-game platforms.

---

## How to use this note

An entry earns its place by changing a decision, not by being interesting. When
one of these is acted on, record the decision (and any rejected alternative) as
an ADR, the way [ADR-0001](../decisions/ADR-0001-sovereign-rules-layer.md)
records the rules-layer decision — and, if the evidence turned out not to apply
here, say so, since "we checked and it did not transfer" is worth as much to the
next reader as an adoption.
