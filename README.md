# Riftbound Chronicle — AI skill for Riftbound

A Claude Code skill that gives an AI agent real Riftbound (Riot's League of Legends TCG) knowledge — deckbuilding judgment and turn-by-turn piloting, not card lookup.

## What it produces

Ask it *"how do I actually pilot this Nasus deck?"* and you get a **deck primer** in a fixed eight-section shape — identity, core loop, mulligan targets, turn-by-turn priorities, fight-or-hold verdict, common lines, common mistakes, evidence ledger. Here are three of the eight from [the real Nasus example](skill/references/gameplay/gameplay.md), unedited:

> **1. Identity** — High-cost control/ramp that holds ground while affording repeated 7+ Energy plays, then closes by scoring extra points off Empowered conquests. CONFIRMED against real play (`legends/nasus.md`, `verification-log.md`, 2026-08-18) — not a text-only hypothesis.

> **3. Mulligan targets** — Tier 1 only, translated from the archetype, not from a sourced decklist: […] **No verified basis yet** for which specific cheap cards this decklist actually runs to do that — that needs a real, sourced decklist, not a guess.

> **8. Evidence ledger** — […] Mulligan targets, common lines beyond the two listed, common mistakes: **Tier 3 — not yet researched.** A future pass with a real sourced Nasus decklist would upgrade these to Tier 1/2.

Section 3 is the point. A generic AI will happily invent a mulligan rule; this one says which parts are derived from card text (Tier 1), which are confirmed against real cited play (Tier 2), and which nobody has actually checked (Tier 3) — and a CI check enforces that every section of every published primer carries that tag. Four primers ship as worked examples, one per archetype posture: Nasus (control), Rengar (aggro), Kha'Zix (tempo), Zed (combo).

The same discipline drives the deckbuilding side: *"does this imported decklist still work here?"* runs a real workflow — check the Legend against the environment's legal sets, check every card against the current ban list, then substitute by **role** (what job did that card do?) rather than by cost, and give an honest verdict including "the archetype's core plan doesn't survive."

## What it deliberately doesn't do

- **Not a rules judge.** It explains how a mechanic works and gives a most-likely read on an interaction, then defers to the official Rules Hub or a Head Judge rather than presenting a guess as a ruling.
- **Doesn't predict a metagame.** It can tell you a deck is unbuildable in a lagged card pool (that's a fact about sets), but "what's strong here" is only ever a sourced observation — this repo tried inferring a regional meta from structure, [scored the attempt against real data, and got one of three right](skill/references/deckbuilding/references/regional-legality-model.md).
- **No win rates, play rates, or tier lists.** Riot's [developer policy](https://developer.riotgames.com/policies/riftbound) restricts publishing or retaining metagame-defining data; that's a design constraint here, not an afterthought — nothing in `skill/scripts/` computes a rate.

## Install

Copy or symlink `skill/` into `.claude/skills/riftbound/` in your project, or `~/.claude/skills/riftbound/` for a user-level install. Claude Code picks it up automatically — no build step, no dependencies. (Prefer the user-level location if your project uses git worktrees: deleting a worktree follows a junction placed inside it and will wipe the link target.)

## What's actually in here

```
skill/
  SKILL.md       the router
  references/    deckbuilding/ and gameplay/ books
  data/          a bundled English card database (see skill/data/README.md)
  scripts/       data-extraction and CI-gate tooling
```

Everything the skill needs *to operate* lives inside `skill/` itself — data and scripts included — so copying or symlinking that one folder anywhere gives a fully self-contained, portable skill. **That is not the same claim as "a clean clone can regenerate `skill/data/riftcodex_cards_raw.json` from scratch" — it can't.** The script that harvests that file from `api.riftcodex.com` lives in the maintainer's own site tooling and isn't published here; this repo ships the harvest's *output* as a point-in-time snapshot (2026-08-16), not the pipeline that produced it. `skill/data/README.md`'s Regenerating section documents the manual steps for anyone who wants a fresher or independently-verifiable copy, but running them won't reproduce this exact file byte-for-byte, and there's no commitment that the harvester will be published. Operating self-contained and being reproducible from zero are two different properties; this repo only has the first one.

`skill/` is a small library, not one giant prompt: a thin `SKILL.md` router plus two independent books —

- **`references/deckbuilding/`** — pre-game methodology (archetype theory, curve/rune ratios, Legend-first deckbuilding, an eight-role card taxonomy, a hypergeometric draw-probability table computed against the game's actual setup rules, and the ban-substitution workflow above). Two things worth calling out specifically:
  - [`regional-legality-model.md`](skill/references/deckbuilding/references/regional-legality-model.md) generalizes something first noticed in Taiwan's launch — a new region's day-one card pool doesn't just have fewer sets than the pioneer market, it inherits a ban list calibrated against a card pool it doesn't even have access to yet. That's a structural pattern, not a Taiwan quirk, and it'll recur every time this game (or most any live-service TCG) enters a new market.
  - [`legend-construction-logic.md`](skill/references/deckbuilding/references/legend-construction-logic.md) is a full-roster catalog (46 Legends) of gameplan direction derived from primary card text, one row per Legend, each linking to its own write-up under [`legends/`](skill/references/deckbuilding/references/legends/). It's paired with [`verification-log.md`](skill/references/deckbuilding/references/verification-log.md): a running, fully-cited record of checking those derivations against real established play. All 46 have now been through that check — **only 3 came back unchanged.** The rest needed a correction: a real "default Champion" the entry didn't emphasize, an archetype label that doesn't match how players actually talk, or — worst case — a real competitive deck built almost entirely from cards *outside* the Legend's own kit. A later audit of the extraction pipeline found it had been silently dropping a genuine third Champion print for 8 Legends whenever two prints shared a domain; that's fixed, each affected Legend got a follow-up check, and a CI gate now enforces the enumeration.
- **`references/gameplay/`** — in-game piloting: the six-phase turn structure, the chain/priority/focus system, combat and showdown resolution step by step, a mulligan decision framework, and the deck-primer format above — sourced from the official Core Rules plus cross-checked community explainers, cited as such throughout.

## The part that's actually interesting if you build agents

This isn't just game content — it's a small case study in a few things that matter for any knowledge-heavy AI skill:

- **Route, don't snapshot.** Anything that could go stale (the ban list, current errata) is treated as a live lookup with an explicit escalation path, not baked into the prompt as a fact — the failure mode this avoids is an agent confidently repeating something that was true when the skill was written and false by the time someone asks.
- **A derive-then-verify loop that feeds back into the method, not just the data.** `legend-construction-logic.md` is generated by structural derivation (fast, cheap, but unconfirmed); `verification-log.md` checks it against real play and sorts every finding into "fixes one entry" or "fixes the method that produced all of them." After all 46 checks, two method-level findings had accumulated enough evidence to change the derivation contract itself: stop emitting a three-way archetype label as a conclusion (real play uses labels the framework doesn't have), and stop claiming a Champion "split" at all (almost every one was wrong — enumerate the prints, leave "which is real" as an explicitly blank Tier 2 field). A third came from auditing the pipeline rather than the content: enumeration completeness needs its own scripted gate, because content research and data completeness have different blind spots.
- **Public library, private companion.** This repo names zero private paths and zero one-deployment-specific function names — anything that has to bind to a real file path (a production card database, a site's publishing conventions) lives in a private companion folder that never gets mirrored here. Both are linked from a user-level skills directory rather than from inside the consuming repo: a junction placed inside a repo gets followed by `git worktree remove` and will wipe the link target, which is not a hypothetical.
- **Don't invent official text, and don't let inference pass as verification either.** Every card-fact claim traces to a real local database or a live official source; the "measure, don't guess" discipline goes further than facts, though — the hypergeometric probability table is computed with `math.comb`, not estimated, and the Domain-personality table is a real statistical pass over the printed card pool, not a vibe.

## Card data

`skill/data/riftcodex_cards_raw.json` — 1,451 rows of full official English rules text, sourced from the unofficial [riftcodex.com](https://riftcodex.com) API. That's rows, not distinct cards — 1,304 unique `riftbound_id`s, the rest are reprint/variant printings (Metal, Overnumbered, Alternate Art, etc.) of a card already counted. Details, coverage, and known gaps are in [`skill/data/README.md`](skill/data/README.md).

## Status and what's next

This started as the deckbuilding/gameplay layer for one site's assistant. The longer-term direction is a fuller "coach agent" architecture for live, in-game piloting decisions, not just static methodology — this repo is the first piece of that, structured so the next pieces don't require tearing it apart.

Near-term, the honest gaps: three of the four shipped deck primers have Tier 3 sections (real mulligan and common-mistake data is thin for most Legends); the Taiwan environment has three sourced observations against sixteen buildable Legends; and every Tier 2 row in the log was checked inside Vendetta's launch window, so a re-check pass is due when Radiance lands (2026-10-23) — `skill/scripts/check_tier2_freshness.py` prints that worklist on demand.

## Compliance

> Riftbound Chronicle was created under Riot Games' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.

Unofficial fan project, not affiliated with Riot Games. This project deliberately never publishes or retains a win-rate, play-rate, or matchup-differential claim — Riot's [Developer Portal policy](https://developer.riotgames.com/policies/riftbound) explicitly restricts apps from publishing or retaining that kind of metagame-defining data, and the deckbuilding methodology and `verification-log.md` are built to stay clear of it as a design constraint, not an afterthought.

**Two compliance items are open, not resolved — stated plainly here rather than implied as settled:**

- **Product registration.** Riot's policy requires registering any player-facing product "regardless of whether or not your product uses official documented APIs." An application has been submitted; as of this writing it has been pending for an extended period with no indication of an active review timeline. A pending application is not an approval, and this project operates without confirmed registration status while it waits.
- **Card data source.** The bundled dataset is harvested from `api.riftcodex.com`, an unaffiliated fan project — not Riot's own API. Riot's policy states an app "may only use Riftbound assets (including cards) provided by the Riot API. No external or unofficial materials." This project doesn't currently meet that condition. Deck builders and card libraries are listed among Riot's approved use cases in principle, but that approval is conditioned specifically on API-sourced assets, which this repo doesn't yet use — see the License section below and [`skill/data/README.md`](skill/data/README.md) for the full provenance.

**Takedown**: `skill/data/riftcodex_cards_raw.json` and the errata/derived text built on top of it stay in this repo on the basis above — bundled as-is, not claimed as cleared. If Riot Games (or another rights holder) asks for the card data to be removed, it will be removed; open an issue or contact the maintainer and it comes down, no argument.

## License

This repo's own original work — the skill methodology in `skill/` and the data-processing scripts in `skill/scripts/` (which consume the already-harvested card data; the harvest script itself isn't part of this repo, see Card data source above) — is MIT, see [LICENSE](LICENSE).

**`skill/data/riftcodex_cards_raw.json` is not covered by that grant, and its standing under Riot's policy is unresolved rather than cleared — see Compliance above.** Card names, rules text, and game mechanics are Riot Games' copyrighted content regardless of what this repo's own license says about the surrounding code. If you build on this repo, the MIT grant covers the skill and tooling; the bundled card data carries Riot's rights, and its sourcing from an unofficial mirror rather than Riot's own API is a known, open compliance gap, not a settled permission — make your own determination before relying on it beyond personal/hobbyist use. See [`skill/data/README.md`](skill/data/README.md) for the data's actual provenance.
