# Deck Coach prototype

Open `index.html` directly. The no-build page demonstrates the `deck-coach-session.v1` workflow: context, parsed decklist, qualitative role coverage, evidence-tiered diagnosis, fixed eight-section primer, and JSON/Markdown export.

The computed closed loop runs in the portable CLI:

```powershell
python skill/scripts/deck_coach_pipeline.py run --case-id DC-RNG-GLOBAL-001 --output-dir deck-coach-output
```

Select `profile.json`, `mask.json`, and `evaluation.json` in the page's **Import pipeline artifacts** control to display the computed curve, type mix, mask status, and evaluation. Import is read-only and stays in the current tab.

The page makes no network or model calls, stores nothing between browser tabs, and does not compute rates or rankings. The CLI produces a provisional legality/recommendation mask from the dated environment registry; real event legality still requires a live official check. The Agent bridge remains deliberately manual.
