# Match Analyst demo

A no-build, bilingual page over the Match Analyst artifacts: pick a match, then read its Commentary, its Review, the normalized timeline, and the information boundary (what the perspective could not see, contradictions, inferred and unknown facts, and the assumptions the engine checks needed). Every event id is a link into the timeline.

The page runs no engine. Its data is generated:

```bash
python skill/scripts/match_analyst_runner.py demo --out prototype/match-analyst/demo-data.js
```

`demo-data.js` holds the four synthetic fixture logs in `skill/data/match_analyst_fixtures/`, each from its own perspective. A game replayed from a private record can sit beside it in `local-data.js`, which is gitignored and never committed:

```bash
python skill/scripts/match_analyst_runner.py trace --record <record.json> --catalogue <catalogue.json> --overlay-root <overlay> --out <trace.json>
python skill/scripts/match_analyst_runner.py demo --trace <trace.json> --label "<name>" --no-fixtures --out prototype/match-analyst/local-data.js
```

The page lists whatever both files hold. Match Analyst is a development preview and is not routed in `skill/SKILL.md`.
