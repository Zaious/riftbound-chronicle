# ADR-0004 — Card programs are global-core with regional overlays

Status: accepted

Date: 2026-09-02

Applies to: X-05/R3 card-program selection, Deck Coach environments, P2-A, and
future regional/localized products

## Context

The repository began from a Taiwan player need, while its portable Skill,
methodology, controlling rules language, and potential collaborators are
international. A Taiwan-only executable pack would duplicate card semantics
when another region is added. A global-only pack would erase the release,
translation, format, and availability differences the project was created to
handle.

## Decision

R3 uses two layers.

### Global core pack

One card's executable rules identity lives once under the controlling English
text and current global official baseline. It contains:

- canonical card identity and printing provenance;
- current-text hash and errata sources;
- typed programs and clause-level behavior status;
- official locators and behavior tests;
- no region-specific release or collection assumption.

The first pack is named as a bounded rules/conformance pack, not as a metagame
or country pack. Candidate name: `global-core-origins-v1`.

### Regional overlays

An overlay may add only regional facts:

- released/available set and product pool;
- applicable format and ban snapshot;
- official or community localization with provenance;
- region-specific source status and freshness;
- product/deck availability constraints.

Initial overlay: `taiwan-origins-v1`. A future Korean or other overlay reuses
the same global card programs.

An overlay cannot change card semantics. If a localized source appears to do
so, record a source conflict against the controlling text instead of forking the
program silently.

## Selection rule

Choose two to four real, relatively linear deck packages that maximize useful
mechanic overlap and minimize unsupported branching. Selection must include:

- at least one Deck Coach primer already backed by evidence;
- cards available in the global core and the first regional overlay;
- one interaction/replacement line so Rule Consult benefits;
- enough shared cards that the second deck adds fewer mechanics than the first;
- no claim that the selected decks represent the metagame or best decks.

The exact decks remain a separate recorded selection because they require a
current product-direction and player-review decision. This ADR freezes the
architecture, not that content choice.

## Acceptance gate

- every used clause is `full`, `partial`, `unsupported`, or `stale`;
- every full/partial clause pins a tested program and official source;
- pack and overlay versions are independently visible;
- a global program runs unchanged under every compatible overlay;
- a stale/mismatched overlay fails without staling the global program;
- Deck Coach may use overlay legality and global behavior coverage without
  conflating either with strategy evidence;
- P2-A and Match Analyst cannot claim pack support outside the exact combined
  pack/overlay coverage.

## Consequences

The public repository can be international and English-controlling while the
main site remains useful to Taiwan players. Regional expansion adds data and
localization, not another rules engine.

## Rejected alternatives

- **Taiwan-only programs:** duplicates semantics and weakens international
  collaboration.
- **Global-only programs:** loses the release/localization gap that is a core
  product need.
- **One forked program per language:** lets translation drift become executable
  truth.
