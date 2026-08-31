# Riot Compliance Boundary

Status: engineering interpretation, not legal advice
Last checked: 2026-08-24

## Official sources

- [Riftbound Digital Tools documentation](https://developer.riotgames.com/docs/riftbound)
- [Riftbound Developer API Policy](https://developer.riotgames.com/policies/riftbound)
- [Riot Legal Jibber Jabber](https://www.riotgames.com/en/legal)

Riot's current documentation says player-serving products must be registered, applications may use a functional prototype or detailed mock-up, automated rules enforcement is not currently approved, and manual gameplay tools are reviewed case by case. It also says gameplay-facilitation tools should live within platforms broadly applicable to multiple games rather than a standalone Riftbound-only client.

## Product responsibility matrix

| Capability | Human | Software | Current status |
|---|---|---|---|
| Shuffle, draw, physical card movement | Performs | Records a summary only | Included |
| State truth | Describes and confirms | Stores append-only record | Included |
| Strategic Player 2 choice | May supply options | Proposes and explains | Included |
| Legal-action authority | Confirms | Marks proposal unverified | Included |
| Rules explanation | Asks and evaluates | Cites and explains | Included |
| Effect/combat/scoring resolution | Performs and confirms | Does not calculate or enforce | Excluded |
| Automated legal-action enumeration | — | Would own legality | Excluded |
| Full automated simulator/self-play | — | Would own state and rules | P2-S, planned only |

## Preparation, not play — and the game enforces it

The four systems all sit in the preparation phase (see
`../product/PRODUCT_SCOPE.md`). For P2-A specifically, that is not a
self-imposed limit but a consequence of the game's own tournament rules:

- **417.1** — "Players may use electronic devices during competitions, but can't
  use them during matches." This settles the question without needing to argue
  about what counts as assistance: the device may not be in use during a
  sanctioned match.
- **703.9** — Outside Assistance is defined as a player receiving advice or
  strategic assistance from an individual outside the match; **703.9.c** extends
  the penalty to a spectator who is also a player in the event; **703.9.e**
  carves out teammates in 2v2 and other specified team formats; **703.9.f**
  allows physical logistics help at a judge's discretion.
- **602.3.b–c**, **602.4.b.2.d–e** — high-OPL restrictions on electronic aids and
  outside assistance during deckbuilding and drafting, with head-judge discretion
  at low OPL.

This matters for the application in two ways. It is a *bounding* argument — the
tool cannot be used to gain an advantage inside a sanctioned match, because
using it there is already a rules violation independent of this product. And it
places the product in a category with precedent inside Riot's own portfolio:
League of Legends has a long-standing, tolerated third-party preparation-tool
ecosystem. The category precedent should not be overstated into a policy
precedent — that ecosystem operates under its own API and policy regime, and the
Riftbound policy currently prefers gameplay-facilitation tools to live in
platforms broadly applicable to multiple games.

Clause text above was read from the 2026-07-16 Tournament Rules through the local
rules index. **Re-verify against the current published version before submitting
anything that relies on it**; this document is an engineering interpretation, not
legal advice, and rule numbering can move between revisions.

## Risk classification

### Lower-risk product functions

- deck construction and deck education;
- card and rules explanation with sources;
- qualitative strategy;
- human-confirmed manual-session logging.

These still require current product registration and approved data/asset decisions when player-facing.

### Approval-sensitive manual gameplay

P2-A may be considered simulation or replication of gameplay even though it does not enforce rules. Riot's policy contains a case-by-case approval path for such tools. Therefore P2-A is a prototype for application review, not evidence that approval has already been granted.

### Not implemented

- automated rules enforcement;
- standalone Riftbound-only digital gameplay;
- matchmaking, ranks, or ladders;
- monetization of simulated/replicated gameplay;
- retained or published metagame-defining rates;
- P2-S.

## Data and asset boundary

The repository currently bundles an unofficial RiftCodex-derived card-text snapshot and already discloses that unresolved gap. A player-facing approved app must use the sources and assets Riot authorizes for that app. The portable Skill's provenance disclosures do not convert unofficial data into approved Riot API data.

Application code must therefore keep card data behind a replaceable source adapter. The P2-A ledger prototype stores user-authored summaries and does not render card assets.

## Required disclaimer

> Riftbound Chronicle was created under Riot Games' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.

## Change control

This document and the application description must be rechecked when:

- Riot changes the Riftbound policy or Digital Tools documentation;
- P2-A gains a new tracking or decision capability;
- an app begins using Riot API assets;
- RSO, monetization, public hosting, or P2-S is considered.
