# ADR-0015 — P6 bounded legal-action enumeration, the Cleanup's Recall step, and free-for-all

- Status: Accepted (Codex G-3 ruling on the Round G packet, 2026-09-07)
- Scope: the P6 milestone — `enumerate(observation)` over the covered action
  families, Cleanup step 5 (Core 323, "Recall all Unattached non-Unit Gear…")
  on the P3 attachment and facedown topology, and free-for-all play for three
  and four players.
- Rules baseline: English Core Rules 2026-07-16, especially 196, 316–324, 429,
  431.2.c, 488, 811.
- Not decided here: team play, teammate scoring and team rewards, which stay
  unsupported; and the clause-grammar compiler, which is P7 (ADR-0016).

## Context

The legal-action service can classify candidates a caller supplies but cannot
produce them, so a client has to guess what to ask about. The Cleanup runs
steps 1–10a but fails the whole run closed the moment step 5 applies, because
the attachment model it needed did not exist when it was written — P3 built
that model, so the exit can go. And every procedure assumes two players: a
third player's concession is refused rather than resolved.

## Decisions

### 1. Enumeration is bounded, and silence is abstention (DP-78)

`enumerate(observation)` returns candidates only for families the engine
covers *and* the observation confirms: playing a card from hand whose cost is
payable, whose timing is legal and whose destination is legal; a Standard Move
including Ganking; an activated ability whose transaction can pay; passing
priority or focus; and Hide.

Every candidate carries the `checks` that produced it, the facts it required,
and the perspective it was enumerated from. Every family that could have
produced a candidate but did not carries an exclusion reason, so a caller can
tell "not legal" from "not known".

`complete_action_set` stays **false**. It is not a placeholder: the engine has
no machine-checkable proof that the enumeration is exhaustive, and until it
does the field says so. A family whose decision needs a private zone the
perspective cannot see, a fact the observation marks unknown, or a capability
the engine lacks, **abstains** — it reports why and produces no candidate.
Guessing is never the fallback.

Each family has a mutation gate: remove one observation the family needs and
it must abstain rather than answer.

### 2. Cleanup step 5 runs on the P3 topology, in the same transaction (DP-79)

The rule, in its own words:

> "Recall all Unattached non-Unit Gear and non-Unit Runes at Battlefields, and
> all Permanents and Runes in Bases other than their controller's. Remove all
> Hidden cards from all Battlefields that are not controlled by the same
> player and place them in their owner's Trash."

Three actions, one working state — the same one steps 4 and 8 already act on,
so the Cleanup stays one atomic run:

1. every non-Unit Gear and non-Unit Rune at a Battlefield that is **not
   attached** to anything is Recalled (429) — an attached one is not, because
   its location is its Top-Most card's (434.4);
2. every Permanent and Rune in a Base that is not its controller's is
   Recalled to the controller's own Base;
3. every Hidden card at a Battlefield whose controller is not the
   Battlefield's controller goes to its **owner's** Trash.

Each transition records the object, where it came from, where it went, and its
identity before and after (124). A Hidden card that stays facedown is never
named in the public trace — the trace records how many remain, not which.
`gear_rune_recall_cleanup` leaves the unsupported list.

### 3. Free-for-all first; teams stay unsupported (DP-80)

Skirmish (three players) and War (four players) run as free-for-all: the
existing Turn Order cycle already generalises, War's first-turn rule joins the
turn-progress catalogue, and a choice among several opponents is a
`player_selection` over the real opponent set rather than the "exactly one
opponent" shortcut.

**Concession removes a player and the game continues.** The engine does not
infer a winner from a concession: it records the removal, hands the remaining
players and the Mode of Play to the terminal procedure, and when that cannot
decide, the terminal is external. A conceding player's objects leave the game
with their owner.

Team play — teammate scoring, team rewards, the team Burn Out beneficiary —
stays `team_scoring`, refused by name.

## Implementation order

1. C-57: `enumerate(observation)` with per-family abstention.
2. C-58: Cleanup step 5 on the attachment and facedown topology.
3. C-59: free-for-all turn order, multi-opponent choice, and concession as
   player removal.

## Coverage boundary

`complete_action_set` and `complete_legality` stay false; `complete_game`
stays false. Team play stays unsupported. A concession the terminal procedure
cannot resolve is an external terminal, not a derived winner.

## Rejected alternatives

- Enumerating every family and marking the uncertain ones "maybe legal".
- A separate procedure for step 5, which would break the Cleanup's atomicity.
- Deriving the winner of a three-player game from a concession.
