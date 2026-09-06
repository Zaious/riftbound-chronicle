# ADR-0013 — P4 continuous effects, the layer engine, typed conditions, the keyword catalogue, Empower and XP

- Status: Accepted (Codex G-2 rulings on the Round G packet, 2026-09-07)
- Scope: the P4 milestone — one canonical `continuous_effects[]` representation
  with the Core layer engine over it, a typed `condition.v1`, the reviewed
  `keyword-catalog.v1`, Empower and XP / Level primitives, the evaluated cost
  modification P2 consumes, the evaluated `counterable` flag P2's Counter
  consumes, the Effect Text of attached cards, and copy over the traits the
  engine models.
- Rules baseline: English Core Rules 2026-07-16, especially 124, 135–136,
  159, 364–365, 441–442, 476–480, 700–730, 800–828.
- Not decided here: the semantic event catalogue, cross-object watchers,
  delayed triggers, per-turn counters and the general replacement grammar
  (P5, ADR-0014); Hunt beyond a partial hook, which waits for P5's Conquer /
  Hold events (DP-72); multi-player and per-player choices, revealed-knowledge
  persistence and the 323.7 Cleanup edges (P6).

## Context

Six representations of a continuous effect grew one slice at a time:
`might_modifiers` and `keyword_modifiers` and `conditional_might` on objects,
`might_auras` and `damage_modifiers` and `turn_effects` on the state. Nine
functions read them (`current_might`, `effective_might`, `has_keyword`,
`shield_total`, `combat_might_contributions`, `bonus_damage`, the Expiration
Step, the entry-state procedure and the state validator), each with its own
notion of when a source is active and in what order values apply. None of them
implements Core 476–480: there is no layer, no timestamp, no dependency, and
no fixpoint. Card text that needs them is the largest remaining family in the
Taiwan T-list decks.

## Decisions

### 1. `continuous_effects[]` is the only representation (DP-73)

The effect state carries one top-level `continuous_effects` array. Every
entry is:

```
{ effect_id, kind, source: {object|battlefield, identity},
  affects: {scope: object|criteria, object?, identity?, criteria?},
  layer, sublayer?, timestamp, value, condition?, duration, snapshot? }
```

- `kind` is one of `might_set`, `might_arithmetic`, `keyword_grant`,
  `keyword_remove`, `ability_append`, `bonus_damage`, `entry_state`,
  `permission` — each bound to the layer the rules put it in.
- `source` names the object or Battlefield whose ability or resolved effect
  created it, with the identity it had then (124). An effect whose source
  identity no longer matches, or whose source is no longer active, stops
  applying and its removal is recorded with a reason.
- `affects` is one object (with the identity bound at creation) or a criteria
  set evaluated now — the aura case.
- `layer` is `trait`, `ability` or `arithmetic` (477.1–477.3). Arithmetic
  carries `sublayer` `increase` or `decrease`, derived from the sign, because
  increases apply before decreases (477.3.a).
- `timestamp` is a monotonic integer assigned when the effect begins applying.
  It is a relative comparison only and no rules text may read it (480.1.c).
- `duration` is `permanent`, `this_turn` (with `turn_id`), `this_combat`
  (with `combat_id`), `while_source_active` or `until_detached`.
- `snapshot` records the limited value of a non-passive arithmetic effect at
  application time (477.3.b); a passive ability never snapshots.

Legacy fields are translated **once, at the input boundary**, by
`migrate_legacy_effects`. The runtime reads `continuous_effects` and nothing
else; a state that carries a legacy field *and* a canonical effect derived
from the same source is `invalid_input`. There is no double read and no
double count.

### 2. The layer engine applies each effect once, repeatedly, to a fixpoint (DP-73)

`characteristics(state, object_id)` computes an object's current traits by
Core 476–480: the three layers in order, each applicable effect applied as
soon as it can be and **only once across every pass** (476.2), then the whole
sequence repeated until a pass changes nothing (476.1). Removal is separate
from application and also happens once (476.3).

Within a layer the engine derives dependencies (478): effect A depends on B
when applying B changes what A applies; the depended-on effect goes first and
the dependent immediately after (479). Mutual alteration establishes no
dependency (478.1) and falls back to timestamp order (480), as does every
independent pair. A cycle the engine cannot order, or a dependency it cannot
derive, is `unsupported: layer_dependency_unresolved` — the engine never picks
an order it cannot justify. The fixpoint is bounded by the number of effects;
exceeding it is the same refusal.

`current_might`, `effective_might`, `has_keyword` and `shield_total` become
thin readers of this one computation, so a Unit's Might in Combat, under an
aura, with a Buff and an attached Equipment is one answer with one trace.

### 3. `condition.v1` is a typed AST, never text (DP-74)

A condition is a tree of `and` / `or` / `not` over leaves that each name
explicit state: `controls_units {count, location, controller_relation}`,
`runes_at_least`, `might_at_least`, `has_keyword`, `is_empowered`,
`xp_at_least`, `attacking_or_defending_alone`, `friendly_unit_defends_alone`,
`battlefield_controlled`, `zone_count_at_least`. Every leaf declares the
identity it binds and the visibility it needs; a condition that would read a
zone the asking perspective cannot see is `unsupported:
condition_needs_hidden_information`. Free text and embedded programs are not
accepted. The same AST gates a continuous effect, an activation (377.2.b), a
cost modification and a `[Level N]` ability.

### 4. The keyword catalogue is reviewed, not inferred (DP-70)

`keyword-catalog.v1` carries one entry per keyword: stable id, the official
locator, the semantic hook that implements it (which layer and which
production), its active zone, its identity and duration boundary, and a
fixture template. A keyword with no production is **not** claimed because its
string appears on a card: it is listed with `production: null` and answers
`unsupported: keyword_not_implemented`. Promotion is the same manual review as
the token catalogue (ADR-0012 §6).

### 5. Empower, XP and Level are state with typed actions (DP-71, DP-72)

`empowered: bool` on an object, `xp: int` on a player. `empower` sets the
state and fails closed when the object is already Empowered — no second
application and no second event (441). `[Empowered]` is a condition leaf.
`spend_xp` becomes a real payment kind, `[Level N]` an ability-layer effect
gated by `xp_at_least`. The `become_empowered` event and the end-of-turn
disempower are P5's to emit and schedule; P4 records the state change and
leaves the hook. Hunt stays a partial hook until P5 lands Conquer / Hold
events.

### 6. The four consumers P2 and P3 left open

- **Cost modification** (`cost_modification.v1`): P4 evaluates the condition
  and emits `{modification_id, applies_to, amount, source, condition_result,
  provenance: {evaluated_by: p4_condition_layer}}`. P2 validates and consumes
  it; it still refuses anything carrying an unevaluated condition.
- **`counterable`**: a `permission` continuous effect writes the evaluated
  flag onto the chain entry, which is exactly what P2's Counter already reads.
- **Effect Text of attachments**: an `ability_append` effect in the ability
  layer (477.2) gives the Top-Most card the attached card's typed triggers
  while it stays attached; detaching removes it with provenance.
- **Copy**: a trait-layer effect over the copyable traits the engine models
  (477.1). A clause whose copy needs a trait the model does not carry — name,
  tags, printed cost, domain — is `unsupported: copy_unmodelled_traits`
  rather than a partial copy.

## Implementation order

1. C-49: `continuous_effects[]`, the input adapter, the layer engine, and the
   readers rewritten onto it.
2. C-50: `condition.v1` and its consumers (effects, activation, cost
   modification, `counterable`).
3. C-51: `keyword-catalog.v1` with its promotion tool and gate.
4. C-52: Empower, XP and Level primitives.
5. C-53: `ability_append` for attachments and copy over the modelled traits.

## Coverage boundary

Declared unsupported: `layer_dependency_unresolved`, `copy_unmodelled_traits`,
`keyword_not_implemented`, `condition_needs_hidden_information`, Hunt beyond
its hook, and everything the G-2 ruling assigned to P5 and P6.
`complete_game` and `complete_legality` stay false.

## Rejected alternatives

- Keeping the six legacy families and reading both representations.
- A fixed application order instead of the 476–480 fixpoint.
- Inferring keyword support from card text.
- A partial copy that silently drops the traits the model lacks.
