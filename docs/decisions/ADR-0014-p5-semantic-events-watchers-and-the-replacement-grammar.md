# ADR-0014 — P5 semantic events, watchers and delayed triggers, and the general replacement grammar

- Status: Accepted (Codex G-2 rulings on the Round G packet, 2026-09-07)
- Scope: the P5 milestone — one semantic event catalogue with causality and
  visibility, cross-object watchers, delayed triggers, per-turn counters and
  trigger multipliers, and the general replacement grammar with the Core
  ordering law.
- Rules baseline: English Core Rules 2026-07-16, especially 124, 303.2,
  319–324, 367–375, 383, 417–443.
- Not decided here: multi-player and per-player simultaneous choices,
  revealed-knowledge persistence, and the 323.7 Cleanup edges — Codex's G-2
  ruling puts those in P6; the clause-grammar compiler is P7.

## Context

After P4 the engine has one representation for continuous effects and a typed
condition language, but events are still implicit: a trace event is whatever
the operation happened to write, replacements are chosen by a hand-rolled
order, and nothing watches another object. Triggers exist only as typed lists
read at the four moments that schedule them. Every remaining family of card
text — "when another unit dies", "at the end of this turn", "the first time
each turn", "if it would die, instead …" — needs events that carry causality
and an ordering law that follows the rules rather than the code's convenience.

## Decisions

### 1. Events are semantic, not one per operation (DP-75, as modified)

One game action carries one `action_id` and emits one **or more** events
(`event.v1`). A Move emits `move`, `leave_location` and `enter_location`
under the same `action_id`; a Kill emits `die` and `leave_location`; a Draw
emits `drawn` and `leave_location`/`enter_location` for the card. Every event
carries: `event_id`, `action_id`, `kind` from the bounded catalogue, the
`source` that caused it, the `actor`/`controller`, the affected object with
its identity before and after (124), `location_before`/`location_after`, a
`causal_parent` naming the event it derives from — a replacement's events
name the event they replaced — and a `visibility` of `public` or the players
who may see it.

Different semantics are never merged into one generic operation event. An
event kind the engine does not have is `unsupported: event_kind_unknown`
rather than a generic fallback.

### 2. Watchers, delayed triggers, counters and multipliers (DP-76)

A trigger descriptor gains a `watch` block: the event `kinds` it reacts to, a
`scope` (`self`, `controller`, `location`, `any`) and an optional
`condition.v1`. That is what lets one object react to another object's events;
the descriptor still names its own source, and its controller is the source's
controller.

A **delayed trigger** is created by a resolving effect and carries the source
and target identities it was created with, the event or turn it waits for, and
the snapshot of anything its instructions need. It fires once; a target whose
identity changed no longer matches (124), and the delayed trigger is removed
with its reason.

**Counters**: a trigger or replacement marked `once each turn` or
`N times each turn` carries a per-turn count keyed by source identity, ability
id and turn id. A trigger that has already been performed that many times does
not trigger at all (383.3.e), and a "you may" the controller declines at
finalization was **not** performed, so it may still trigger later that turn
(383.3.e.2.b). The counters reset with the turn transition the G3 slice
already owns.

**Multipliers** ("trigger an additional time") carry a `causal_depth` and a
once guard: a multiplier never applies to the copies it produced, and a depth
beyond the declared bound is `unsupported: trigger_multiplier_depth`.

### 3. The replacement grammar follows the Core ordering law (DP-77, as modified)

The rules text this implements, verbatim, because the printed numbering is
ambiguous in the source PDF:

> "If more than one Replacement Effect applies to the same event being
> executed, then the controller of the object being acted on determines the
> order the Replacement Effects will apply. If it is a player being acted on,
> that player decides the order… If the affected object is an Uncontrolled
> Battlefield then the Current Turn Player decides the order…"

> "If more than one event occurs simultaneously that Replacement Effects could
> apply to, each event is treated separately and individually… Replacement
> Effects with the same controller are applied in the order of their
> controller's choosing… If multiple applied Replacement Effects with
> different controllers would execute simultaneously, they execute in turn
> order."

So ordering is two layered decisions, not one: **who orders** is the
controller of the affected object (372, the Current Turn Player for an
Uncontrolled Battlefield, 372.2), and **execution across controllers** is Turn
Order (373.1). The engine asks the right player for each event and never
mixes the two.

Three further laws are gates, not prose:

- A Replacement Effect applies **once** to an event and to the events that
  replace it (370.2); the Zhonya's Hourglass pair is a golden fixture.
- A replacement's own actions are performed **before** any simultaneous
  unmodified event (373.2).
- Across simultaneous events a replacement may be applied in only **one
  sequence** (374); the Soraka / Guardian Angel case is a golden fixture.
- "Once each turn" replacements consume their use only when actually applied;
  declining leaves the use available (372).

All-prevention allocation ("Prevent all damage") keeps its own fixture. A
combination none of these fixtures covers fails closed rather than guessing an
order.

## Implementation order

1. C-54: `event.v1`, the semantic catalogue, and the operations emitting
   events with causality and visibility.
2. C-55: watchers, delayed triggers, per-turn counters and multipliers.
3. C-56: the general replacement grammar with the layered ordering law and its
   golden fixtures.

## Coverage boundary

Declared unsupported: `event_kind_unknown`, `trigger_multiplier_depth`,
replacement combinations outside the golden fixtures, and everything G-2
assigned to P6 — multi-player choices, revealed-knowledge persistence and the
323.7 Cleanup edges. `complete_game` and `complete_legality` stay false.

## Rejected alternatives

- One event per effect operation, with the semantics inferred by consumers.
- A single Turn-Order rule for both who orders and who executes.
- Letting a multiplier apply to its own copies with a recursion limit as the
  only guard.
