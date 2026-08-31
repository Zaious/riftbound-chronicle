# ADR-0001 — Own a programmatic rules layer, after two audits advised against one

Status: accepted
Date: 2026-08-30
Supersedes: the "no rules engine" guidance in
`docs/audits/INDEPENDENT_AUDIT_2026-08-17.zh-TW.md` and
`docs/audits/INDEPENDENT_AUDIT_2026-08-18.zh-TW.md`
Implements: `docs/architecture/SOVEREIGN_RULES_LAYER.md`

## Why this record exists

Two independent audits explicitly told this project not to build one. The
2026-08-17 audit listed under "should not borrow": *"MTG `rules-lawyer`'s
per-clause ruling commitment — this pushes the Riftbound assistant back toward
Judge / Rules Engine, violating the confirmed product positioning,"* and put
"Judge agent, win-rate model, full match simulation, competitive ruling engine"
under "not scheduled near-term." The 2026-08-18 re-audit repeated it in shorter
form: not "MTG rules-lawyer or Judge replacement," not a "detailed rules
engine."

A programmatic rules layer now exists. Without this record, the next reader —
or the next audit — sees a repository that quietly did the thing its own
audits ruled out, and has to re-derive whether that was a decision or a drift.
It was a decision. The reasoning below is the part that was previously only in
conversation.

## What the audits were actually protecting against

Re-read in context, both audits object to a **product promise**, not to code:

- that the assistant would settle disputed rulings, i.e. become the authority
  of record a Head Judge is;
- that it would resolve gameplay automatically, taking over state and legality
  from the player;
- that it would claim coverage it could not demonstrate.

Those three objections are still in force and are still enforced — see
`skill/SKILL.md`'s "Non-negotiable boundaries," the excluded rows in
`docs/policy/RIOT_COMPLIANCE_BOUNDARY.md`'s responsibility matrix, and
`docs/product/PRODUCT_SCOPE.md`'s explicit non-goals. Nothing in this decision
relaxes them.

What the audits did not distinguish — because at the time the project had no
such component — is between *an engine that rules* and *a kernel that models*.
The layer built here answers "which timing states permit this action, and what
does this typed effect program do to this state," with an executable
conformance suite and rule locators. It never answers "you are right and your
opponent is wrong." A `rule-consult` answer still carries confidence,
assumptions, and an escalation path to the event's Head Judge.

## Decision

Chronicle owns the rules layer, bounded by what the conformance suite proves.

Published work bearing on this decision — including an independent group
arriving at the same propose-and-validate split, and the 2016 result that makes
the learned alternative unattractive for a rules layer — is collected in
[RELATED_WORK.md](../architecture/RELATED_WORK.md).

## Alternatives rejected

**A. Stay escalation-only (no rules code at all).** The status quo the audits
assumed. Rejected because three of the four systems need a shared, checkable
model of timing to be correct at all, not merely to sound correct: Deck Coach's
piloting advice depends on when a Reaction can be played; Player 2 Agent must
bind a proposal to a confirmed state and sequence number; Match Analyst must
reconstruct a timeline before it can evaluate a decision. Prose in a markdown
book cannot be tested. The 46-Legend verification pass is the precedent — plausible
prose survived until something executable checked it, and then most of it did not.

**B. Depend on a third-party fan simulator for rules semantics.** Rejected on
availability and authority. An external engine's correctness, versioning, and
continued existence would become load-bearing for our product claims, and a
disagreement would have no principled resolution. The current design instead
treats external engines as comparable implementations: a mismatch is classified
`kernel_failure`, `external_engine_failure`, `unsupported`, or `stale_ruleset`,
and is never resolved by silently changing the rule source. Optional engines may
be tested against Chronicle cases; they do not define truth.

**C. Full automated resolution / legal-action enumeration.** This is the thing
the audits actually feared, and it stays rejected — on product grounds (it
would take state and legality away from the human, which is the entire P2-A
invariant) and on compliance grounds (Riot's Digital Tools documentation states
automated rules enforcement is not currently approved; see
`RIOT_COMPLIANCE_BOUNDARY.md`). P2-S remains documented and unimplemented, with
`p2s_enabled: false` validated as a negative capability rather than left as an
absence.

**D. Ship the kernel but describe it as complete.** Rejected as the failure mode
this repository has already been audited for twice — "every card across every
set," "battle-tested," "can't go stale" were all corrected findings. The release
boundary is therefore stated as a rule: the public product never claims
capabilities the executable conformance suite does not prove. Version 1 is a
timing and permission kernel with 14 executable cases and a bounded typed-effect
IR; it is described as exactly that.

## What this decision does not claim

Worth stating explicitly, because the volume of rules-core code invites the
opposite reading: **this project does not claim its value lies in owning a rules
engine, and could not.**

**A rules engine is a hygiene factor, not a differentiator.** Correct is the
expectation; incorrect is disqualifying; there is no upside above correct. It is
also derivative — the rules are Riot's, and an implementation of them is a
translation, however good. Anyone claiming a competitive position on "our rules
engine is right" is claiming something closer to "our program does not crash."

**So why build one at all.** Two reasons, and the second is the load-bearing one:

1. Without it the four systems would be reasoning about legality by plausible
   text continuation, which produces confident errors — the failure this
   repository's `README` opens with.
2. **Without it, "I do not know" is not sayable.** Text continuation always
   produces an answer; it has no mechanism for declining. `unsupported` is only
   meaningful because something with a *declared scope* is the one saying it, and
   `coverage: timing_permission_v1` is only a meaningful sentence if a formal
   model backs the boundary. The evidence tiers, the abstention outcomes, and the
   authority separation all rest on that. The engine is the floor those stand on,
   not the thing being sold.

**This is what an external engine would have to replicate.** An engine that
answered legality with perfect accuracy but returned only legal/illegal would
*not* substitute for this layer, because the four systems consume `coverage` and
`outcome` as **evidence**, not merely as a gate. The requirement on any
replacement is therefore not "is it accurate" but "**can it speak with a stated
scope, and can it decline**" — which play-oriented engines have no reason to do,
since for playing, "illegal" and "unmodelled" both just mean "you cannot do
that."

**The quality bar that follows, and it is not the obvious one.** "The engine is
not where the value is" must not decay into "the engine can be rough," because
the evidence layer is standing on the truth of its scope declarations. If
`coverage: timing_permission_v1` is asserted while gaps remain *inside*
timing-permission, the layer above is built on a false floor. So:

- **Breadth of coverage is a roadmap item** (R2 → R3 → R4). Having less of it is
  a known state, not a defect.
- **Truthfulness within the declared scope is a correctness requirement**, with
  no room to trade. Narrowing the claim is always available; overstating it is
  not.

The `unsupported`-as-first-class design already encodes this: prefer a smaller
claim to a wrong one.

## Consequences

- Every capability claim is now gated on conformance coverage, which is why
  Match Analyst is specified but not routed until rules-core R2/R4 land.
- The audits' three underlying objections are preserved as testable boundaries
  rather than as a prohibition on code.
- A future audit reading only the 2026-08-17/18 documents will reach the wrong
  conclusion; this ADR is the pointer that keeps that from happening.
- If the kernel ever begins settling disputes, enumerating legal actions as
  authoritative, or resolving effects without human confirmation, this decision
  has been violated — those are the tripwires, not the amount of code.
