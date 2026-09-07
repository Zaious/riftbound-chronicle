# Clause grammar (`clause-grammar.v1`)

The forms of card text this engine understands, as a versioned public contract
(ADR-0016 §1). One entry per production.

Each production carries a stable `production_id`, the official `rule_locators`
it implements, the `normalization` rule it is matched under (this grammar's
own, `clause-grammar.v1/normalize`), the `ast_node` it produces, the engine
`required_capability` it needs, its `boundary` — what it deliberately does not
cover — and the two fixtures it is promoted on:

- `golden`: clause texts this production must compile.
- `negative`: near-miss texts it must **not** match.

A production without both is not promoted. The negative fixture is what stops
a pattern quietly widening until it swallows clauses it does not understand,
so `check_clause_grammar.py` fails when a production matches its own near-miss.

The lowering from AST to an effect program lives in
`skill/scripts/clause_grammar.py`, keyed by `production_id`. A production with
no lowering, or a lowering with no production, is a gate failure.

**The corpus is the golden set.** A production is trusted because
`compile_clause` reproduces, under canonical equality, the program a human
wrote for that same clause in `card_program_packs/`. The gate reports how many
of those hand-written programs the grammar reproduces.

`complete_grammar` is `false` and stays false. A clause outside the grammar is
`unsupported: clause_unparsed`, carries its own text, and goes into
`coverage_debt/coverage_debt.json`. It never becomes a guessed program.
