# Keyword catalogue (`keyword-catalog.v1`)

One entry per keyword the engine knows about (ADR-0013 §4).

An entry carries the official locator, the **production** that implements the
keyword — a module and a symbol that must exist in the live engine — the layer
it acts in, the zone it is active in, its identity and duration boundary, and
the gate that exercises it.

`production: null` means the engine does **not** implement the keyword. Codex's
G-2 ruling on DP-70 is that a keyword is never claimed because its string
appears on a card: asking for one of these answers
`unsupported: keyword_not_implemented`.

Nine keywords have productions today: Shield, Tank, Backline, Ganking,
Deflect, Hidden, Ambush, Repeat and Unique. Five are listed without one:
Temporary, Vision, Equip, Hunt, Level and Empower — the last three are P4/P5
work in progress, and each will gain its production in the commit that
implements it.

Keywords whose locator could not be verified against the Core rules are not in
the file at all. An entry without a checkable locator cannot be reviewed, and
an empty row is more honest than a guessed one.

```
python3 skill/scripts/keyword_catalog.py validate
python3 skill/scripts/keyword_catalog.py verify   # productions exist, engine keywords are all catalogued
```
