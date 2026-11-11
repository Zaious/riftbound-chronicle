# Match Analyst demo

A no-build, bilingual page over the Match Analyst artifacts: pick a match, then read its Commentary, its Review, the normalized timeline, and the information boundary (what the perspective could not see, contradictions, inferred and unknown facts, and the assumptions the engine checks needed). Every event id is a link into the timeline.

The page runs no engine. Its data is generated:

```bash
python skill/scripts/match_analyst_runner.py demo --out prototype/match-analyst/demo-data.js
```

`demo-data.js` holds the four synthetic fixture logs in `skill/data/match_analyst_fixtures/`, each from its own perspective, and one full set-1 game from the private R5-P research simulation (two research policies playing each other, replayed through the engine; published by the owner's decision of 2026-11-04). It is a synthetic game, not a real match, and the policies in it are research instruments, not a product. Regenerating it needs the private overlay that holds the record and the card catalogue:

```bash
python skill/scripts/match_analyst_runner.py trace --record <record.json> --catalogue <catalogue.json> --overlay-root <overlay> --out <trace.json>
python skill/scripts/match_analyst_runner.py demo --trace <trace.json> --label "<name>" --out prototype/match-analyst/demo-data.js
```

Running `demo` without `--trace` drops the R5-P game. A further game kept off the repository can sit in `local-data.js` (gitignored), written with `--no-fixtures`.

The page lists whatever both files hold. Match Analyst is a development preview and is not routed in `skill/SKILL.md`.
