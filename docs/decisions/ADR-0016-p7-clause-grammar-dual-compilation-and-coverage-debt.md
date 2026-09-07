# ADR-0016 — P7 the clause grammar, dual compilation, and the coverage debt

- Status: Accepted (Codex G-3 ruling on the Round G packet, 2026-09-07)
- Scope: the P7 milestone — `clause-grammar.v1` as a public versioned
  contract, `compile_card` with canonical dual-compilation agreement, and the
  coverage debt ledger.
- Rules baseline: English Core Rules 2026-07-16; every production carries its
  own locators.
- Not decided here: which cards enter the corpus, which is a packet decision.

## Context

Every card program in the corpus is hand-written. That does not scale, and
worse, it hides the question a rules engine has to answer out loud: *which
forms of card text does this engine actually understand?* A grammar makes that
question answerable and auditable — and makes the answer a file rather than a
claim.

## Decisions

### 1. The grammar is a versioned contract, not an implementation detail (DP-81)

`clause-grammar.v1` ships in the public repo as data. Each production carries:
a stable `production_id`, the official rule locators it implements, its
normalization rule, the typed AST it produces, the engine capability it
requires, a fixture template, and its known boundary.

**A production without a golden fixture and a negative fixture is not
promoted.** The golden fixture is the clause text and the program it must
produce; the negative fixture is a near-miss text the production must *not*
match. A production that matches its negative fixture is a gate failure, not a
warning — that is what stops a pattern quietly widening until it swallows
clauses it does not understand.

### 2. Agreement is canonical, not structural (DP-82, as modified)

`compile_card(card_text)` is deterministic and returns a program plus the
fixtures the clause implies. A clause no production parses is `unsupported`
with its own text attached, never a guess.

Two independent compilations agree only under **canonical equality**, over:
production ids, the complete AST, every parameter and identity binding, the
source/target relation, timing, cost, duration, visibility, and the
unsupported reason. Two trees of the same shape carrying different bindings do
not agree.

The canonicalizer erases what is genuinely naming rather than meaning —
instruction ids, decision references, the order of an unordered set. A
difference that survives canonicalization is a **disagreement**, and
disagreements are classified rather than escalated wholesale:

- a *new semantic difference*, a production ambiguity, or anything that would
  change coverage or a fixture result → escalated to Codex;
- a format, ordering, or already-known equivalent rewrite → closed
  automatically **after** the canonicalizer, with an audit record that keeps
  what was closed and why.

The disagreement list is deduplicated across rounds by a stable signature, so
the same difference is not re-escalated.

### 3. The debt is ranked, and never repaid to satisfy a quota (DP-83)

`coverage_debt.json` holds every clause no production parses, ranked by deck
slots, the number of decks that play the card, its rule family, its risk, and
the engine capability it is missing. Each packet reports what the debt gained,
lost or reclassified.

There is no "at least one repayment per packet" rule: a quota would buy
movement with immature semantics, which is exactly the trade this project does
not make.

## The evidence a production stands on

A production is promoted only when the round trip closes: clause text →
normalization → production match → typed AST → lowered program → canonical
comparison against the corpus's own hand-written program for that clause.
The corpus is the golden set. A production that cannot reproduce the program a
human wrote for the same clause is not understood well enough to promote, and
the comparison says exactly where it differs.

## Coverage boundary

The grammar starts small and states its size. `complete_grammar` is false and
stays false. A clause outside the grammar is `unsupported: clause_unparsed`
and goes into the debt with its text; it never becomes a guessed program.

## Rejected alternatives

- Structural-only agreement between two compilations.
- Promoting a production on a golden fixture alone, with no near-miss.
- A per-packet repayment quota for the debt.
