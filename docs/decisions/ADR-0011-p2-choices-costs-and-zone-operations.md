# ADR-0011 — P2 choice grammar, modal abilities, look / reveal, costs, activated abilities and zone operations

- Status: Accepted (Codex G-1 rulings on the Round G packet, 2026-09-06)
- Scope: the P2 milestone — a typed choice specification over the decision
  envelope, modal abilities, look-at / reveal / put-back with a player-owned
  ordering decision, the cost catalogue with activated abilities, Repeat, Add
  and resource restrictions, and the Banish / multi-card Recycle / Counter /
  Burn zone operations.
- Rules baseline: English Core Rules 2026-07-16, especially 124, 128–130,
  204, 303.2, 355, 376–377, 398–404, 416, 422, 424–429, 431.1.c, 436, 440,
  446–447, 820.
- Not decided here: the sources, conditions and layers of cost modifications
  ("costs less if / for each", P4); XP, Buff and Empower costs (P4);
  "choose one that hasn't been chosen this turn" (P5 counters); "can't be
  countered" (P4 static); Burn Out from a non-Draw instruction (a G3
  extension); what a player remembers of a revealed card after the reveal
  ends (observation layer); Hidden, Legend and Champion zones, attachments
  and tokens (P3, ADR-0012).

## Context

After ADR-0010 the engine has one decision envelope with ten kinds but no
grammar for what a choice is: `discard` resolves its own `card_selection`,
targets are checked by a hand-written path, and every new instruction
would add another special case. Card text in the four sets needs "Choose
one —" (9 cards), look-at / reveal / put-back (16), Predict (10), Repeat
(27), [Burn N] (13), Counter (9), Banish (7), restricted Add resources (16)
and activated abilities on Units, Gear and Legends. The clause inventory
counts P2 as the largest demand of the Taiwan T-list decks (143 slots).

## Decisions

### 1. A choice is a typed specification, not a special case (DP-60)

An instruction that lets a player choose carries `choice: {selection_kind,
count, from, by, visibility, identity_binding, enumerable_cap}`.
`selection_kind` is `single`, `unordered_set` or `ordered_permutation`;
`count` is `{exactly: n}`, `{up_to: n}`, `{any_number: true}` or `{one:
true}`; `from` names the candidate source — `hand`, `trash`, `main_deck_top`
(with `count`), `revealed` (this program's look / reveal session), `board`
with criteria, or `players` with `opponents` / `any` — and `by` names the
chooser: `controller`, `opponent`, `each_player` or an explicit player id.
`visibility` is `public` or `private_to_chooser`; `identity_binding: true`
means the decision must carry `selection_identities`. The engine enumerates
the candidates when the source is enumerable and at most `enumerable_cap`
(default 64) objects long; a `decision_required` result names the decision,
its controller, the specification and — for a public source only — the
option list. A private source (a hand, a looked-at top) is never listed in
the engine result nor in any engine-check; the result carries the option
count and a hash of the option identities, and only the chooser's own
private observation may enumerate them (128.4, 355.10.a).

A supplied decision is checked against the specification: kind must match
(`card_selection` for sets, `card_ordering` for permutations,
`player_selection` for players, `target_selection` for board targets), the
controller must be the chooser (`decision_controller_mismatch`), the count
must fit (`invalid_input`), every value must be a candidate
(`invalid_input`; a candidate that has left the source is
`illegal_operation`), and bound identities must be current
(`invalid_input`). "Each player" choices are one decision per player in the
same envelope, applied in Turn Order (303.2.a). "Not chosen this turn" is
`unsupported: distinct_per_turn_choice`.

### 2. Modal abilities choose by stable option id (DP-61)

A program with `modal: {choose: 1, timing, decision_ref, options:
[{option_id, effects}]}` carries its instructions inside the options and an
empty top-level `effects`. The mode is a `mode_selection` decision whose
value is the option's stable `option_id`, never an index; its stage is the
`timing` the compiled clause states — `play_declaration` for a spell (402.2:
targets and modes are chosen while playing) or `trigger_finalization` for a
triggered ability. The play transaction requires the mode at play and checks
only the chosen option's targets; the resolver refuses a mode chosen at
another stage, by another player (`decision_controller_mismatch`) or naming
an unknown option (`invalid_input`). A missing mode is `decision_required`
(`mode_choice`). When Repeat executes a program again, each execution has its
own mode and target decisions (820.2.a) under the `#<n>` suffix.

### 3. Look-at, reveal and put-back; the order is the player's `card_ordering` (DP-62)

`look_at_top {player, count}` makes the top cards of a Main Deck readable by
the program's controller (128.4: private to them); `reveal {player, from:
main_deck_top | hand | object}` makes cards readable by every player (424.1,
424.2: they stay in their zone, in order). Both stop at the deck's end
without a Burn Out (431.1.c) and record the shortfall as `partial`. Reveals
last until the resolution finishes (424.3.a): the marks live in the effect
state's `reveals` list only while the program runs and are cleared when it
returns. What a player remembers afterwards is
`unsupported: revealed_knowledge_persistence`.

`put_back {player, decision_ref, position: top | bottom}` returns the
still-present looked / revealed cards in the order given by a
**`card_ordering`** decision: a complete permutation of exactly those cards,
identities bound, owned by the chooser, stage `resolution`. The order is a
player choice — it is never a `card_selection`, whose value is a set, and it
is strictly not the external randomization receipt of Burn Out (ADR-0010
§2). The trace records the ordering's hash and who may see it, never the
order. A single remaining card needs no decision. `put_in_hand {player,
decision_ref | objects}` and `draw_it {player, object_id}` take a
looked-at card into the hand as a new object (124); `draw_it` is a Draw
(413) and emits the Draw event. `predict {player, count, recycle_ref,
order_ref}` is the 436 composite — look, Recycle any number (a
`card_selection` over the looked cards; two or more Recycled cards need
their own `card_ordering` for the bottom, 416.5), put the rest back — with
no Burn Out for a short deck (436.4).

### 4. The cost catalogue, activated abilities, Repeat, Add and restrictions (DP-63)

The declaration's non-standard payment kinds grow from `exhaust` / `kill` to
`discard {amount}` (422.1.a: the payer's private `card_selection` at
`play_declaration` stage; 423.1.b: the whole amount must be payable),
`recycle_trash {amount}` (416.3, a public `card_selection` from the payer's
trash), `kill_this`, `recall_self` and `banish_self` (the chain item's own
source, 204.2). `spend_xp`, `spend_buff` and `disempower_self` stay
`unsupported: xp_buff_costs` until P4. Every payment is a receipt event with
the objects and identities it consumed.

An activated ability is a chain item of `object_kind: ability` declared
with `activation: {source_object, ability_id}` through the same transaction
(377: it goes onto the chain and resolves like a played card; 402: a Closed
State with no card). The source must be a permanent the actor controls on
the Board; the chain entry binds `source_object` instead of a card, nothing
leaves the hand, and the item's resolution never sends a card to the trash.
An `[Add]` ability (`ability_kind: add`) finalizes and resolves at once
(400.2, 429.2) — the timing kernel already refuses reactions to it. An
activation condition ("use only while I'm at a battlefield", 377.2.b) is a
P4 condition; a declaration that carries one is `unsupported`.

`[Repeat] cost` is an optional additional cost (820.1.a) declared with
`repeat: true`; each instance may be paid once (820.1.c). The receipt records
it, and the resolver executes the program's instructions once more per paid
Repeat (820.1.d), with separate choices per execution (820.2.a) — a mode or
target decision for execution *n* is the same decision id with the `#n`
suffix. Repeat does not let an ability be activated twice; activated
abilities are repeatable by 377 without it.

A resource an Add ability restricts ("Spend this Energy only to play
spells") is a `resources.restricted[]` entry `{restriction_id, kind: energy
| power, domain?, amount, uses}` with `uses` drawn from `play_spell`,
`play_unit`, `play_gear`, `activate_unit_ability`, `activate_gear_ability`.
`add_resource` with `restriction` deposits there. Payment spends the
restricted pool first when the play's use matches, then the general pool;
a use that does not match never touches it, and a total the general pool
cannot cover is `illegal: cost_unpayable` with the restricted amount named.
Payment events record `restricted_from`.

Cost modifications remain typed declaration input: each increase and
discount may carry `provenance: {evaluated_by: declaration |
p4_condition_layer, source}`. A modification carrying a `condition` or
`per_each` field — a source the engine would have to evaluate — is
`unsupported: cost_modification_sources` (P4). The engine never invents a
temporary condition grammar.

### 5. Banish, multi-card Recycle, Counter and Burn (DP-64)

`banish` moves a card or permanent from any zone straight into its owner's
Banishment (427.1, 427.2) as a new object (124); a token ceases to exist;
Banish is not Kill nor Discard (427.2.a–b). `recycle {objects |
decision_ref, order_ref?}` Recycles several cards as one Game Action
(303.2): to the owner's Main Deck or Rune Deck bottom (416.1–416.2); two
or more cards to one deck need the player's `card_ordering` for the bottom
order (416.5); a single card needs none. `counter {chain_item_id, card_to}`
clears the chain item (425.1): its card goes to the owner's trash (425.1.a)
unless the countering effect names `card_to: hand`; it was not played
(425.1.b) so no play trigger fires; no cost is refunded (425.1.c). The
effect IR removes the effect-side entry and reports
`countered_chain_items`; the resolution bridge removes the timing item in
the same commit through `rules_core.remove_chain_item` and commits neither
state when the timing chain does not carry it. A chain entry marked
`counterable: false` is `unsupported: cannot_be_countered` — the static
that grants it is a P4 contract. `burn {player, count}`
moves the top cards of a Main Deck to the trash (440.1) as new objects; a
deck shorter than the count is `unsupported: burn_out_non_draw` and nothing
changes — the Draw-path receipt is not borrowed (Codex G-1).

### 6. Engine-check and privacy

`mode_selection_required` → `mode_choice`, `card_ordering_required` →
`card_ordering`, `choice_required` → `card_choice` / `player_choice` /
`target_choice` by the specification's decision kind. A check never carries
a private option list: the engine result does not contain one, so neither
does `raw_result`. The effect scope declares `choice_grammar`,
`modal_abilities`, `card_ordering`, `look_reveal_put_back`, `predict`,
`banish`, `multi_recycle`, `counter`, `burn`; the play scope declares
`activated_abilities`, `repeat_costs`, `discard_recycle_costs`,
`self_costs`, `restricted_resources`, `typed_cost_modification_input`.

## Implementation order

1. C-40: the choice specification, `mode_selection` and `card_ordering`
   decision kinds, modal programs, private-option redaction.
2. C-41: `look_at_top`, `reveal`, `put_back`, `put_in_hand`, `draw_it`,
   multi-card `recycle`, `predict`, the transient `reveals` state.
3. C-42: payment kinds, activated abilities, Repeat, Add, restricted
   resources, the typed cost-modification gate, the receipt extension.
4. C-43: `banish`, `counter` with the bridge removal, `burn`, scopes,
   documentation and the bounded checklist patch.

## Coverage boundary

Declared unsupported: cost modification sources and conditions, XP / Buff /
Empower costs, activation conditions, distinct-per-turn choices, revealed
knowledge persistence, "can't be countered", Burn Out outside Draw, Hidden
and Legend sources for activation (P3). `complete_game` and
`complete_legality` stay false.

## Rejected alternatives

- Expressing a put-back order as a `card_selection` whose array order is
  read as the deck order.
- Listing a hand's or a looked-at top's option ids in the engine result.
- A modal option chosen by array index.
- A once-per-turn default for activated abilities, or reading Repeat as a
  permission to activate again.
- Claiming `[Burn N]` support on a short deck through the Draw-path Burn
  Out receipt.
- A hand-written condition grammar for "costs less if" inside P2.
