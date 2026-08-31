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

There is a concrete gap that follows. `skill/references/player2-agent/player2-agent.md`
step 5 says, uniformly: *mark legality as unverified and ask the human to confirm
it*. Every proposal gets the same request, whether `rules_core_check.outcome` is
`supported_legal_timing` (the core checked the timing and it holds) or
`unsupported` (the core has no model of this behaviour at all). Those two cases
carry completely different verification burdens and are presented identically —
which both maximizes the human's total verification cost and gives them no
signal about where to spend it. That is close to the worst configuration the
cost-benefit account predicts.

**What to consider.** Differentiate the confirmation request by
`rules_core_check.outcome`, so that `unsupported` visibly demands more of the
human than `supported_legal_timing` does. The point is not to weaken the human's
authority over legality — it stays theirs in all four cases — but to stop
spending it uniformly on cases where the core already has a grounded answer.

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

**How we would know it is real.** Before building R4, take a sample of real P2-A
`public_state` strings and ask how many support an unambiguous action
enumeration. If most do not, R4's contract is wrong on paper before any code is
written, and the interesting engineering is in what the state summary should ask
the human for — not in the enumerator.

---

## How to use this note

An entry earns its place by changing a decision, not by being interesting. When
one of these is acted on, record the decision (and any rejected alternative) as
an ADR, the way [ADR-0001](../decisions/ADR-0001-sovereign-rules-layer.md)
records the rules-layer decision — and, if the evidence turned out not to apply
here, say so, since "we checked and it did not transfer" is worth as much to the
next reader as an adoption.
