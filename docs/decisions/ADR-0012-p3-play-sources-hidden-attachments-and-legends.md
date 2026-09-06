# ADR-0012 — P3 play sources, Hidden and Facedown Zones, attachments, Legends and the token catalogue

- Status: Accepted (Codex G-1 rulings on the Round G packet, 2026-09-06)
- Scope: the P3 milestone — where a card is played from and what may override
  its cost, Ambush, the Facedown Zone of each Battlefield with the Hide action
  and playing from Hidden, attachments with Top-Most and Equip, the Legend and
  Champion zones as engine objects, the manually promoted token catalogue, and
  a typed copy request that fails closed.
- Rules baseline: English Core Rules 2026-07-16, especially 103.2, 107.3,
  107.4, 108.2–108.3, 124, 128–129, 136, 159, 349, 354–359, 377, 421,
  434–435, 469.1, 811, 818–819, 822, 825.
- Not decided here: the characteristics and layers of a copy (P4); the
  Weaponmaster discount and other conditional Equip costs (P4/P5);
  Empower / XP / Level (P4); the Cleanup steps that remove Hidden cards when
  control changes (323.14, 469.1) and 323.7 generally; the facedown reveal at
  game end (421.4); deck construction itself.

## Context

After ADR-0011 the play transaction still assumes one source — the actor's
hand — and one cost model. Four of the mechanics the Taiwan T-list decks need
are about *where a card comes from* and *what it is attached to*: Hidden
(spells and permanents hidden facedown at a Battlefield), Ambush (a Unit
played as a Reaction to a Battlefield where you have Units), Equip
(attachments that move between hosts), and the Champion Zone (a Legend or
Chosen Champion played from outside the hand). The engine also has no object
for a Legend, so clauses on Annie - Fiery and Master Yi stay `partial` for
`legend_zone_object`.

## Decisions

### 1. A play declares its source; the cost override is typed (DP-69)

The declaration gains `source: {kind, battlefield?}` with `kind` in `hand`
(the default), `trash`, `champion_zone`, `legend_zone` and `facedown`. The
transaction checks the card is in that zone and that the zone permits play:
the Champion Zone plays as normal (108.3.e), a trash or facedown source needs
a permission the card or an effect granted, recorded as
`source_permission: {granted_by}`. A source the declaration does not justify
is `illegal: play_source_not_permitted`; a card that is not in the named zone
is `illegal: card_not_in_source`.

`cost_override: {kind: ignore_base_cost | for_cost, cost?, source}` replaces
the base cost before 356 runs, exactly like the existing base modifications,
and the receipt records which override applied. This is the same mechanism
Hidden (811: "ignoring its base cost") and Flow use; the *conditions* under
which an effect grants one stay P4.

**Unique is not a play restriction.** Core 825.3 makes Unique a deck
construction constraint — a deck may contain only one card of that name — so
the engine records `unique: true` as a characteristic and exposes it to deck
validation, and the play transaction imposes nothing. The Round G packet's
proposal (a same-name limit at play) does not match the rules text and is not
implemented.

### 2. Ambush is a play permission that also changes the timing (DP-65)

`ambush` joins `open_battlefield` in `play_permissions`. A Unit with it may
be played to a Battlefield where its controller has Units, and while it is
being played there it has Reaction (822.1). The transaction derives both from
the same fact: the entry Battlefield holds at least one Unit the actor
controls at declaration time. A declared Reaction timing that Ambush does not
justify is refused by the timing kernel as usual; an Ambush entry to a
Battlefield without a friendly Unit is `illegal: ambush_location_invalid`.
Losing the last friendly Unit before finalization invalidates the location
(822.3); the engine re-derives the permission at commit and refuses the play
rather than letting it finalize.

### 3. Hidden is the Battlefield's Facedown Zone, not a player zone (DP-65)

Each Battlefield carries `facedown: {capacity, cards: [{object_id,
controller, hidden_on_turn}]}` (107.3.b: one logical space per Battlefield,
capacity 1 by default and adjustable). The Facedown Zone is public — its
occupancy and controller are public information — while the cards in it are
private to the player who hid them (108.2.b, 128.4). Every observation and
engine-check treats a facedown card the way it treats a hand: count and
controller only.

`hide_card` (in `hidden.py`, engine-check kind `hide_step`) is a
Discretionary Action, not a play (811.2): it needs the actor's own turn in an
Open State, the card in their hand or Champion Zone with the Hidden
characteristic, a Battlefield they control with a free facedown slot, and the
Hide cost paid through the ordinary receipt. It opens no chain and the card
becomes a new object (124).

Playing from Hidden is an ordinary play with `source: {kind: facedown,
battlefield}`, `cost_override: {kind: ignore_base_cost}` and the 811
restrictions: it is legal from the turn after the card was hidden; the card
has Reaction; a permanent must enter that Battlefield — Gear included, which
overrides the Base-only rule; and every choice the card makes at play must
come from that Battlefield unless the clause's own restriction makes that
impossible, which the compiled clause states as
`hidden_targeting: restricted | free_by_restriction`. A spell with no legal
target under the restriction cannot be played from Hidden
(`illegal: hidden_no_legal_target`). Removing hidden cards when control of
the Battlefield changes (323.14, 469.1) and the reveal at game end (421.4)
stay `unsupported`.

### 4. Attachments: Top-Most, attach, detach and Equip (DP-66)

An object may carry `attached_to`; the object it names is the **Top-Most**
card (434.1.b). The engine derives `attachments` rather than storing both
directions. Attaching links two board cards (434.1): the attached card's
location becomes the Top-Most card's (434.4, not a Move), its printed rules
text goes inactive and its Effect Text and Might Bonus apply to the Top-Most
card (136.2.c, 159.2); nothing else about either card changes — an exhausted
Equipment stays exhausted (434.5.a). Attaching to a new Top-Most card
detaches it from the old one (434.2.a); attaching to its current Top-Most
card does nothing (434.2.b).

Detaching (435) is the reverse, and **its destination is derived, never
assumed**: a detached card's location is the Top-Most card's location
(435.4); a detached Gear that would then sit at a Battlefield is Recalled by
the next Cleanup (435.4.a) — the engine records the pending Recall rather
than moving it early; and when the card detached because the Top-Most card
left the board for a non-board zone, it detaches to the last board location
that card occupied (435.4.b). `move_board_object`, `kill`, `banish`,
`return_to_hand`, `recycle` and `recycle_one` all route a host's departure
through this one derivation.

`[Equip]` is an activated ability (818.1) and goes through the P2 activation
path with its own cost; its instruction is `attach {object_id, to}` with the
host chosen at the same location. The Weaponmaster discount and any
conditional Equip cost are P4 input; P3 only supplies the lifecycle and the
`attach` / `detach` events a trigger layer can watch.

### 5. Legends and the Champion Zone are objects outside the Board (DP-68)

`legend_zone` and `champion_zone` become optional player zones, and `legend`
joins the object kinds. A Legend in the Legend Zone is a continuously active,
**public** object that is not on the Board and not a Location (107.4.d): a
Champion Legend can never leave it, other legends may only move between it
and Banishment. Selectors therefore never reach a Legend through a Board
criterion — `unit`, `gear` and `rune` mean Board objects (355.9.b) — and a
clause that means the Legend must say so with `kind: legend` and
`location: legend_zone`. "Ready a legend" targets, because the zone is public
(355.10.d). A Legend's activated ability is the P2 activation path with the
Legend as `source_object`, and "exhaust your Legend" is the ordinary
`exhaust` payment against it.

The Champion Zone holds the Chosen Champion, is public (108.4.c) and is a
legal play source (108.3.e). It is not a Location either.

### 6. The token catalogue is promoted by hand (DP-67)

`token-catalog.v1` is a versioned data file. Each entry carries a stable
`token_id`, the official text it was promoted from with a `text_sha256`, its
`kind`, `base_might`, `keywords`, an optional `effect_program_id`, the
`source_cards` locators, and a `review: {reviewer, date, source}` record. The
clause inventory only produces *candidates*, in the private repo; nothing
enters the catalogue without a review record. `play_token` accepts a
`token_id` and takes the entry's characteristics; a token id that is not in
the catalogue is `unsupported: token_not_in_catalogue`, and an entry whose
text hash does not match its recorded text fails the catalogue gate. No
automatic promotion, ever.

### 7. Copy is a typed request that fails closed (DP-69)

`copy_object {source_object, request_id}` records that a copy was requested
and answers `unsupported: copy_characteristics` without changing anything.
The characteristics and layer semantics of a copy are P4; until then the
engine refuses rather than half-copying. The request's provenance is kept in
the trace so the P4 slice can bind to it.

## Implementation order

1. C-44: play sources, cost overrides, Ambush, Unique as a deck constraint.
2. C-45: Facedown Zones, `hide_card`, playing from Hidden.
3. C-46: `attached_to` / Top-Most, attach / detach with derived destinations,
   the Equip activation path.
4. C-47: Legend and Champion zones, Legend objects and activation, the typed
   copy request.
5. C-48: `token-catalog.v1`, the promotion tool and its gate.

## Coverage boundary

Declared unsupported: copy characteristics and layers, Weaponmaster and
conditional Equip costs, Hidden removal on control change (323.14, 469.1),
323.7, the facedown reveal at game end (421.4), Legend abilities that need
P4 conditions, tokens outside the catalogue, deck construction. `complete_game`
and `complete_legality` stay false.

## Rejected alternatives

- A player-level `hidden` zone instead of the Battlefield's Facedown Zone.
- Detaching everything to the controller's Base when the host leaves.
- Treating Unique as a play-time same-name restriction.
- Automatic token promotion from card reminder text.
- A partial copy implementation ahead of the P4 layer contract.
