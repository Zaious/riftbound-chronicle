# R3 First Pack Selection

Status: selected pending physical/independent decklist verification

Date: 2026-09-03

Machine record:
[`selection.json`](../../skill/data/card_program_packs/global-core-origins-v1/selection.json)

## Selection

The first `global-core-origins-v1` implementation wave is the Annie and Master
Yi decks from Origins: Proving Grounds. Lux and Garen remain the second wave of
the same pack.

This is not a strength or metagame ranking. Riot identifies Proving Grounds as
a fixed starter product for two to four players featuring Annie, Garen, Lux,
and Master Yi and positions it as a way to learn the game. That makes it a more
stable physical-practice boundary than a tournament list whose cards or
Battlefields may later be banned. See Riot's
[How to buy Riftbound](https://playriftbound.com/en-us/news/announcements/how-to-buy-riftbound/).

The candidate card-by-card lists and deck codes are transcribed by
[Rift Mana](https://riftmana.com/riftbound-proving-grounds-decklists/), not
published as a list on the Riot page. They are therefore stored as candidate
content, not as an official fact. Before a production behavior manifest is
activated, compare them against a physical Proving Grounds product or a second
independent source. The chosen Champion is counted inside each 40-card Main
Deck; it is not an additional forty-first card.

## Why Annie and Master Yi first

- Both exist in the same teaching product and can support a repeatable physical
  P2-A practice setup.
- Chronicle already has a worked Annie construction example and multiple Master
  Yi deck/regional verification findings. This does not prove the preconstructed
  lines, but it gives expert-review context that Lux/Garen currently lack.
- They span Fury/Chaos and Calm/Body, so Wave A does not overfit one Domain pair.
- Their cards reuse implemented damage, draw, movement, Might, ready/exhaust,
  Kill, target, and replacement primitives.
- Their unsupported clauses force the next architecture in a useful order:
  choices/costs/zones, card-play and continuous semantics, then Combat.

Lux and Garen are deliberately deferred, not rejected. Adding them after the
Wave A inventory completes the same product and adds Mind/Order without changing
pack architecture. Selecting all four immediately would double clause inventory
before Wave A reveals which engine contracts are genuinely blocking.

## What this selection does not claim

- It does not claim either deck is legal as submitted in every Constructed
  format. Product practice and tournament registration are different contexts.
- It does not claim the public transcription is authoritative.
- It does not claim every card is executable.
- It does not claim a full game, legal-action set, matchup result, mulligan rule,
  or deck strength.
- It does not activate a production `card-behavior-manifest.v1`.

## Capability path

### R3-A0 — inventory, Claude-ready

Verify current errata-applied text, split every card into stable clause ids, and
label every clause `full`, `partial`, `unsupported`, or `stale`. This batch must
not add guessed programs for missing mechanics.

### R3-A1 — choices, costs, and zones

Define and implement the smallest typed support needed for targets, optional
additional costs, return-to-hand/from-trash, discard, look, channel, and recall.
Each semantic contract follows ADR-0002 and is reviewed before card programs use
it. The accepted cross-card semantics and implementation order are fixed by
[ADR-0005](../decisions/ADR-0005-r3a1-choices-costs-and-zones.md).

### R3-A2 — play, conditions, and continuous effects

Add full play lifecycle, area targets, play/move triggers, conditional effects,
Bonus Damage, Deflect, enter-ready behavior, and duration expiry.

### R3-A3 — G1 Combat

Implement Combat state, attacker/defender designations, Tank, Shield, Ganking,
damage assignment/dealing, and Combat Cleanup. A source-only rules explanation
may precede this; executable Combat claims may not.

## Activation rule

The pack becomes useful scenario by scenario. A named scenario may be supported
when all of its required clauses are `full` and its cross-card conformance test
passes. The repository does not wait for every card to become full, but it also
never upgrades a partial deck into a “supported deck” label.
