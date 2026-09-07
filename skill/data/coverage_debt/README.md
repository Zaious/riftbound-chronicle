# Coverage debt (`coverage-debt.v1`)

Every clause in `card_program_packs/` that `clause-grammar.v1` does not parse,
ranked by what it costs to leave unparsed (ADR-0016 §3).

The ranking, in order: `deck_slots`, `deck_count`, `risk`,
`missing_capability`, `clause_id`.

- `deck_slots` counts copies of the card across the deck lists this repo
  carries (`tournament_lists/`). It is measured, not estimated: a card no list
  plays scores zero, and that zero means "no list here plays it", not "it does
  not matter".
- `risk` is `always_in_play` for a Legend, Champion or Battlefield — an
  unparsed clause on one of those shows in every game the card is in — and
  `main_deck` otherwise.
- `missing_capability` is the batch the inventory ledger says would unblock the
  clause; `rule_family` is the mechanics it recorded.

**There is no repayment quota.** Each packet reports what the debt gained
(`added`), lost (`repaid`) or reclassified, and that is all it is asked to do.
A quota would buy movement with immature semantics, which is the trade this
project does not make.

Rebuild with `python skill/scripts/coverage_debt.py build`; the gate
`check_coverage_debt.py` fails when the committed file is stale, when the debt
does not hold exactly the unparsed clauses, or when the ranking is out of
order.
