# Card data

> **Licensing note**: card names, rules text, and game mechanics in this file are Riot Games' copyrighted content, not this repository's. They're reproduced here under Riot's [Developer Portal policy](https://developer.riotgames.com/policies/riftbound) for the approved "Card libraries" use case. This repo's MIT license (see [`../LICENSE`](../LICENSE)) covers the skill and tooling around this data, not the card content itself.

`riftcodex_cards_raw.json` — full official English rules text for Riftbound cards, harvested from `api.riftcodex.com` (an unauthenticated public API run by an unaffiliated fan project — "RIFTCODEX — An unofficial fan project. Not affiliated with Riot Games.").

This is the `riftbound` skill's own bundled local dataset — read it directly rather than fetching per card question (see `../skill/SKILL.md`'s "route, don't snapshot" section).

## What's in it

- 1451 cards as of the 2026-08-16 harvest.
- Coverage: OGN (Origins), OGS (Proving Grounds), SFD (Spiritforged), UNL (Unleashed), VEN (Vendetta), plus promo pools OPP (Organized Play, 133 cards), PR (general Promo, 13), JDG (Judge Promo, 3).
- Not covered: RAD (Radiance, unreleased as of this harvest), ARC and FND (riftcodex doesn't carry these at all).
- Each card has `text.plain` and `text.rich` (HTML) rules text using `:rb_*:` icon tokens (e.g. `:rb_energy_1:`, `:rb_rune_fury:`) for keyword/mana symbols — these are riftcodex's own placeholder syntax, not a standard.
- No ban-status field. The ban list is a separate, Riot-official, frequently-updated axis — always cross-check the live Rules Hub (`https://playriftbound.com/en-us/rules-hub/`) or a deployment's private companion binding, never assume this file's absence of a ban field means a card is legal.
- ID shape: `riftbound_id` is lowercase with a total-set-size suffix (e.g. `ogn-001-298`) and `*`/letter suffixes for alternate-art variants (e.g. `unl-229*-219`) — not the same shape as other Riftbound tools' `OGN-001`-style IDs. Match on `set.set_id` (uppercase) + zero-padded `collector_number` if cross-referencing against another dataset.

## Regenerating

The harvest script that produced this file isn't part of this public repo — it lives in the maintainer's own site tooling, unrelated to any card data specific to that deployment. To regenerate or refresh this dataset yourself: page through `api.riftcodex.com`'s public card endpoint (unauthenticated, ~15 pages at 100/page as of this harvest, gentle rate limiting recommended since there's no documented limit) and write the result to `riftcodex_cards_raw.json` in this folder. `scripts/extract_legend_packets.py` is the part of that pipeline that *is* in this repo — it consumes this file's format directly.
