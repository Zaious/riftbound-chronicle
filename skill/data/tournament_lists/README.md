# Tournament decklists (public event records, per-list, per-environment)

> **Licensing/compliance note:** card names are Riot Games' content (see the root [README.md](../../../README.md#compliance) and [`../README.md`](../README.md)). The lists themselves are public tournament results, stored one-by-one with their source. This folder exists so Tier 2 claims and deck primers can point at *specific real lists* instead of re-scraping the same pages each pass; it is deliberately **not** a statistics dataset — see "What this folder must never do" below, which is the whole design constraint. Same takedown commitment as the card data: it comes down on request.

## What this is

One JSON file per Legend, each holding a small number of **individually-sourced public tournament decklists** with placement, event, date, and — mandatory — the **format environment** the list was played in. It answers "show me a real list for X, in environment Y, and where it came from." It does not answer "how popular is X" or "what's the best list."

## Environments (only these two, short-term — 2026-08-18 decision)

Every list carries an `environment` field with exactly one of:

- **`global-vendetta`** — Global Standard with Vendetta (Set 4) legal: OGS + OGN + SFD + UNL + VEN, current Constructed ban list. Event date must be on/after **2026-07-31** (VEN release). Lists from before that date belong to a *different* environment (Unleashed-era) and are **not** collected here — they'd silently mix a pre-VEN meta into a post-VEN folder.
- **`taiwan-set1-banned`** — Taiwan's regionally-lagged pool: OGN + OGS only, with the *global* Constructed ban list applied (see `regional-legality-model.md` — bans are company-wide, the pool is not). This is the environment Taiwan players actually build in. **Expect very few or zero lists here for now**: Taiwan's competitive scene is young and its results are rarely published in a scrapable form. An empty environment is a true statement about available public data, not a gap to fill with global lists relabelled — a global list is *not* a Taiwan-pool list even if every card in it happens to be OGN/OGS.

Anything else (Unleashed-era global, Spiritforged-era, other regions' lagged pools, ladder/homebrew, casual events) is out of scope until there's a reason to add an environment tag for it. Don't collect first and tag later.

## Shelf life — this data expires, and says when

Each list has an `event_date`, and each environment has a real "valid until an event happens" horizon:

- `global-vendetta` lists go stale at the **next set release** (RAD, 2026-10-23) and at any **ban-list update** in between. `skill/scripts/check_tier2_freshness.py`'s `FORMAT_EVENTS` list is the single source of truth for those dates — the validator below reuses it.
- `taiwan-set1-banned` lists go stale when Taiwan gets its **next set** (no confirmed date as of 2026-08-18) or when a **ban update** touches an OGN/OGS card. Note the asymmetry the environment definition implies: a global ban wave that only hits SFD/UNL/VEN cards doesn't change this pool at all, and one that hits an OGN/OGS card changes it completely — so "ban update happened" isn't automatically "Taiwan lists are stale"; the validator can only flag the date, a human has to check *which* cards.

A stale list isn't deleted — it's still a true historical record — but the validator reports it, and a primer or Tier 2 row citing it should say the environment has moved since.

## What this folder must never do

These are the compliance line (Riot Developer Portal policy: no publishing or retaining metagame-defining data — win rate, play rate, matchup differential), restated as concrete rules for this folder:

1. **No rates, ever.** No script in this repo computes, stores, or prints "card X appears in N% of lists," "Champion Y presence," win rates, or matchup numbers from this data. Not even as an intermediate. `check_tournament_lists.py` can answer *"which lists contain card X"* (an enumeration with sources) — never *"what fraction."*
2. **No rankings.** No "best list," "tier," or ordering by strength derived here. Placement is a fact about one event, recorded per list; it is not aggregated.
3. **Small N, on purpose.** Cap of **8 lists per Legend per environment**. This is a citation store, not a sample. A cap this low also makes it structurally impossible to compute anything statistically meaningful from it, which is the point.
4. **Every list has a source URL and access date.** A list without provenance doesn't go in.
5. **Environment is mandatory and validated.** No list without a legal `environment` value; `global-vendetta` lists must have `event_date >= 2026-07-31`.

If a future need genuinely requires aggregate numbers, that's a *different product* with a *different compliance posture* (registered, Riot-API-sourced), not an extension of this folder.

## File shape

`<legend-slug>.json` — slug matches the `legends/*.md` filename (e.g. `rengar.json`, `miss-fortune.json`):

```json
{
  "legend": "Rengar - Pridestalker",
  "lists": [
    {
      "environment": "global-vendetta",
      "event": "Riftbound Showdown Ottawa",
      "event_date": "2026-08-08",
      "placement": "1st",
      "player": "…",
      "source_url": "https://…",
      "source_name": "hextechanalytics.com",
      "accessed": "2026-08-18",
      "chosen_champion": "Rengar - Trophy Hunter",
      "runes": {"Fury": 4, "Body": 8},
      "battlefields": ["Emperor's Dais", "Seat of Power", "Star Spring"],
      "main_deck": [{"name": "Inferna", "count": 3}, …],
      "sideboard": [],
      "notes": "optional — anything the source said that a primer might cite"
    }
  ]
}
```

`main_deck` counts must sum to 40 (the Chosen Champion is part of the 40 per Tournament Rules 601.1); `runes` must sum to 12; `battlefields` must be exactly 3. Card names should match `riftcodex_cards_raw.json` names where possible (the validator warns on non-matches; it doesn't fail, since the local card data has known gaps).

## Regenerating

Hand-entered from the cited source, one list at a time — there is no scraper, and by design there won't be one here (a scraper invites "collect everything," which is exactly what the cap and the two-environment rule forbid). `check_tournament_lists.py` validates shape, environment, date-vs-environment, count sums, cap, and reports staleness against `check_tier2_freshness.py`'s event list.
