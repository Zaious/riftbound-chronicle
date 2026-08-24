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
