# Token catalogue (`token-catalog.v1`)

The tokens a compiled card program may play, and the only place their
characteristics come from (ADR-0012 §6).

The catalogue is **empty on purpose**. Codex's G-1 ruling on DP-67 is that a
clause inventory may only produce *candidates*: every entry is promoted by
hand from official text, with a review record naming the reviewer, the date
and the source document. Nothing is promoted automatically, and a token that
is not here is `unsupported: token_not_in_catalogue`.

To promote one reviewed token:

```
python3 skill/scripts/token_catalog.py promote reviewed-entry.json
```

The tool derives `text_sha256` from the text the reviewer approved and
refuses an entry without a review record or with an id that already exists.
`token_catalog.py validate` checks shape, hashes and review records;
`token_catalog.py verify-pack <pack.json>` checks that every `play_token` a
pack compiles names a catalogued token.

Candidates listed from the card snapshot live outside this repository, in the
private working notes, until someone reviews them.
