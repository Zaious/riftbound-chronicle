# ADR-0002 — Separate schema, ruleset, capability, and implementation versions

Status: accepted

Date: 2026-09-02

Applies to: R1/R2 engine state, programs, decisions, traces, card packs, and
`engine-check.v1`

## Context

Chronicle has several stable v1 artifacts and a growing effect vocabulary. If
every new operation forces a new major schema, consumers spend their time on
mechanical migrations. If additions silently change what “v1” means, an old
replay can produce a different result without any visible reason. Rules updates
create a third problem: a schema can remain identical while the normative rule
baseline changes underneath it.

These are different forms of change and must not share one version number.

## Decision

Every executable artifact is identified on four independent axes:

1. **Schema major** — the shape and meaning of fields, such as
   `riftbound-effect-program.v1`.
2. **Ruleset baseline** — controlling Core/FAQ/errata versions.
3. **Capability set** — the exact supported operations, procedures, clauses,
   and known exclusions used for this run.
4. **Implementation identity** — the reproducible code build or commit that
   executed the artifact.

Existing v1 artifacts remain valid. A future capability-manifest implementation
adds the missing third/fourth axes; it must not rewrite old artifacts in place.

### Change classification

| Change | Required action |
| --- | --- |
| Add an optional field with an unchanged default and unchanged old behavior | Same schema major; capability revision and tests |
| Add a new operation that old programs never invoke | Same program major may remain; capability revision required |
| Change an existing field's meaning, requiredness, type, outcome, ordering, or authority | New schema major or a new operation id |
| Fix an implementation that contradicted the pinned official baseline | Same schema may remain; new implementation identity and regression fixture |
| Adopt a newer official rules/FAQ/errata baseline | New ruleset id and conformance pass; schema changes only if structure requires them |
| Change a card's current text or errata | New text hash; affected behavior entry becomes stale until reverified |

“Bug fix” is not permission to change replay semantics invisibly. The release
note must say whether the old result was a conformance defect and which fixtures
changed.

### State composition

Do not merge timing, effects, perspective, provenance, and capabilities into one
monolithic state schema. Introduce a future `game-snapshot.v1` envelope that
contains versioned component states and their hashes. Components stay pure and
cross-component changes commit through an atomic coordinator such as the
existing resolution bridge.

The envelope is composition, not new authority. P2-A may reference a structured
snapshot while its authoritative state remains human-confirmed.

### Decisions and choices

Any player/controller choice that affects execution is represented as a
versioned decision artifact. The engine may list eligible options and identify
the decision owner; it may not ask a language model callback to choose inside a
state transition. Supplying the decision reruns the pure transition from the
same input hash.

### Card behavior

Card names never branch engine code. Card packs compile current text into typed
programs that pin schema major, ruleset, capability set, text hash, source
locator, and tests. Unsupported clauses remain explicit in the behavior
manifest.

## Feature acceptance contract

Every new mechanic must deliver together:

- state representation and invariants;
- instruction/event representation;
- validation and explicit decision shape;
- deterministic transition and before/after hashes;
- exact official locators and baseline;
- positive, negative, impossible-action, rollback, and off-cwd tests;
- capability-manifest entry and known exclusions;
- consumer-facing `unsupported` behavior before the capability is present.

A feature is not complete when only its happy-path operation exists.

## Migration policy

- Migrations are explicit, pure functions from one named schema version to
  another.
- They never edit archived artifacts in place.
- They preserve source ids, event ids, hashes of the original input, and a
  migration trace.
- A lossy migration returns `unsupported` or requires a human decision; it does
  not invent a value.
- Readers may retain legacy adapters, but writers emit only the current form.

## Consequences

Claude-ready implementation packages can add bounded operations without
re-deciding version governance. Consumers can distinguish “same structure, more
capabilities” from “new rules” and “new semantics.” The cost is an additional
capability manifest and migration test layer, which is intentional evidence,
not metadata decoration.

## Rejected alternatives

- **Bump the schema for every operation:** excessive consumer churn with no
  semantic benefit.
- **Keep only `.v1` forever:** unreproducible replays and invisible semantic
  drift.
- **Use Git commit alone as the version:** does not identify official rules or
  supported capabilities and is unsuitable for portable artifacts.
- **Let each system version engine evidence differently:** recreates the drift
  `engine-check.v1` was introduced to remove.
