# Three-system prototypes

These connected, no-build pages demonstrate the three mode contracts without a model API or rules engine:

- [`deck-coach/`](deck-coach/README.md) — qualitative deck diagnosis and eight-section primer;
- [`rule-consult/`](rule-consult/README.md) — cited unofficial rules consultation;
- [`p2a/`](p2a/README.md) — human-confirmed Player 2 decision ledger.

Open any `index.html` directly in a normal desktop browser. Each page keeps its working record only in the current tab and exports a versioned artifact. No page uses network requests or browser persistence.

All three pages share [`shared/theme.css`](shared/theme.css) and [`shared/i18n.js`](shared/i18n.js). The visual shell follows the RiftBoundC website's Ember & Aged Gold palette, 1560px product frame, Traditional Chinese font stack, square controls, and thin-border card language. Traditional Chinese is the default interface; the `EN` button switches the complete in-tab presentation to English without adding browser persistence.
