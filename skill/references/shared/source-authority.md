# Shared Source Authority

> Last verified: 2026-08-24. Read this reference for current card text, legality, errata, detailed rules, or tournament procedure.

## Two authority axes

Do not flatten all questions into “the Core Rules PDF is the source.”

### Competitive procedure

Use, in order:

1. the specific event addendum, when applicable;
2. the current Tournament Rules;
3. the current Core Rules where Tournament Rules do not modify them;
4. the event's Head Judge as final authority for live tournament procedure.

Tournament Rules can add to or override Core Rules for competitive play, and an event addendum can further override Tournament Rules within its scope.

### Game mechanics and card text

Use, in order:

1. a current official FAQ or clarification within its stated scope;
2. the latest Core Rules;
3. corrected card text with current official errata applied.

A scoped FAQ may explicitly govern over the then-current Core Rules until a later revision supersedes it. Check dates and scope, not just document titles.

## Live official entrypoint

The official Rules Hub is:

https://playriftbound.com/en-us/rules-hub/

It routes to the current Core Rules, Tournament Rules, FAQs, ban lists, and errata. Follow current official links rather than trusting an old PDF URL or stale mirror.

The machine-readable registry at `${CLAUDE_SKILL_DIR}/data/rules_source_registry.json` records the currently checked official documents and supporting community source. Use its `source_id` values in Rule Consult artifacts. A registry entry is provenance metadata, not a substitute for a live check when `resolve_at_query_time` is true.

## Local card data

For routine card lookup, use `${CLAUDE_SKILL_DIR}/data/riftcodex_cards_raw.json`, then check `${CLAUDE_SKILL_DIR}/data/errata_overlay.json` by `official_name`. If an overlay entry exists, its `new_text` supersedes the raw snapshot.

The bundled card file is an unofficial RiftCodex-derived snapshot, not Riot API data. Read `${CLAUDE_SKILL_DIR}/data/README.md` before relying on its coverage. It is portable and useful for research, but not proof that a player-facing app satisfies Riot's official asset/data requirements.

Check a private companion source first when one exists and is explicitly documented as more current or approved. Never invent official wording in an unavailable language; distinguish a translation or paraphrase from official printed text.

Ban status is a separate live axis. The bundled card dataset does not establish that a card is currently legal. For competitive legality, check the current official ban list and the applicable region/format/set release state.

## Freshness rule

- Routine meaning of a card: local snapshot plus errata overlay is normally sufficient.
- Detailed interaction: check whether a newer official FAQ or clarification exists.
- Tournament legality or procedure: read the current applicable official source before answering.
- Any stale or contradictory source: disclose the conflict and avoid false certainty.

## Community sources

Community analysis, deck guides, and rulings databases may explain real play and edge cases. Label them as community sources. They do not override Riot's official documents or a live event's Head Judge.

## Evidence language

- **Tier 1:** official rules/card text or a direct mechanical derivation.
- **Tier 2:** verified real-play or community evidence with provenance.
- **Tier 3:** plausible but not yet verified.

For rules consultation, use the separate confidence scale in `references/rule-consult/rule-consult.md`; evidence tier and answer confidence are related but not interchangeable.
