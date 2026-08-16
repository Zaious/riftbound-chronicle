# Riftbound Chronicle — AI skill for Riftbound

A Claude Code skill that gives an AI agent real Riftbound (Riot's League of Legends TCG) knowledge — not rules-lookup, but the kind of judgment a serious player or a site editor actually needs: how to build a deck around a Legend's ability instead of a pile of strong cards, how to tell someone their imported decklist won't survive the current ban list before they build it, how the chain/priority system actually resolves a showdown.

Built and battle-tested as the deckbuilding/gameplay brain behind [Riftbound Chronicle](https://riftbound.chroniclecore.com) (符文戰場編年史), an unofficial Traditional-Chinese community site for Taiwan Riftbound players — this repo is the generalized, portable version of that same knowledge, stripped of anything specific to that one deployment.

## What's actually in here

```
skill/    the Claude Code skill itself (SKILL.md + references/)
data/     a bundled English card database (see data/README.md)
```

`skill/` is a small library, not one giant prompt: a thin `SKILL.md` router plus two independent books —

- **`references/deckbuilding/`** — pre-game methodology (archetype theory, curve/rune ratios, Legend-first deckbuilding, a full ban-substitution workflow for "does this classic decklist still work") plus a genuinely reusable finding: [`regional-legality-model.md`](skill/references/deckbuilding/references/regional-legality-model.md), which generalizes something first noticed in Taiwan's launch — a new region's day-one card pool doesn't just have fewer sets than the pioneer market, it inherits a ban list calibrated against a card pool it doesn't even have access to yet. That's a structural pattern, not a Taiwan quirk, and it'll recur every time this game (or most any live-service TCG) enters a new market.
- **`references/gameplay/`** — in-game piloting: the six-phase turn structure, the chain/priority/focus system, combat and showdown resolution step by step, and a mulligan decision framework — sourced from the official Core Rules plus cross-checked community explainers, cited as such throughout.

## The part that's actually interesting if you build agents

This isn't just game content — it's a small case study in a few things that matter for any knowledge-heavy AI skill:

- **Route, don't snapshot.** Anything that could go stale (the ban list, current errata) is treated as a live lookup with an explicit escalation path, not baked into the prompt as a fact — the failure mode this avoids is an agent confidently repeating something that was true when the skill was written and false by the time someone asks.
- **Public library, private companion.** This repo is written to name zero private paths, zero one-deployment-specific function names — anything that has to bind to a real file path (a production card database, a specific site's publishing conventions) lives in a private companion file that never gets mirrored here. The private deployment (Riftbound Chronicle's own repo) reaches this content through a local directory junction rather than a copy — edit once, both places are correct, nothing to keep in sync by hand.
- **Don't invent official text.** Every card-fact claim traces to a real local database or a live official source; the deckbuilding book explicitly documents a known gap (this bundled dataset has no English rules text before the harvest that produced `data/`) rather than quietly translating around it.

## Card data

`data/riftcodex_cards_raw.json` — 1451 cards' worth of full official English rules text, sourced from the unofficial [riftcodex.com](https://riftcodex.com) API. Details, coverage, and known gaps are in [`data/README.md`](data/README.md).

## Using this as a Claude Code skill

Copy or symlink `skill/` into `.claude/skills/riftbound/` in your project (or `~/.claude/skills/riftbound/` for a user-level install). Claude Code picks it up automatically — no build step, no dependencies.

## Status and what's next

This started as the deckbuilding/gameplay layer for one site's assistant. The longer-term direction is a fuller "coach agent" architecture for live, in-game piloting decisions, not just static methodology — this repo is the first piece of that, structured so the next pieces don't require tearing it apart.

## Compliance

Unofficial fan project. Not affiliated with, endorsed by, or sponsored by Riot Games. Built to stay inside Riot's [Developer Portal policy](https://developer.riotgames.com/policies/riftbound) for Riftbound apps — in particular, the deckbuilding book deliberately never makes a win-rate, play-rate, or Tier claim, since Riot's policy explicitly restricts apps that publish or retain metagame-defining data.

## License

MIT — see [LICENSE](LICENSE).
