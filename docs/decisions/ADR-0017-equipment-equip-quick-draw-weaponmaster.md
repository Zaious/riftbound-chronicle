# ADR-0017 — Equipment: Equip, Quick-Draw, Weaponmaster, and inactive rules text

- Status: Proposed (set 2 package A2, 2026-11-03)
- Scope: the Equipment rules the set-2 cards need — Equipment's Effect Text and Might Bonus as characteristics, rules
  text going Inactive while attached, the Equip activated ability, Quick-Draw, Weaponmaster, and Unique.
- Rules baseline: English Core Rules 2026-10-09: 136, 137, 150, 435, 436, 459, 716-725, 818, 819, 821, 825.
- Builds on: ADR-0012 §4 (attach, detach, Top-Most, derived detach destinations), ADR-0011 (choices and costs),
  ADR-0013 (continuous effects and keywords).

## Context

ADR-0012 §4 gave the engine the attachment lifecycle: `attached_to`, `attach` / `detach`, Effect Text and Might Bonus
applied to the Top-Most card, and the derived destination when a host leaves. It left Equip's activation to the P2
path and named the Weaponmaster discount and conditional Equip costs as later input. Set 2 is that input: 31 Gear with
`[Equip]`, 5 with `[Quick-Draw]`, 11 units with `[Weaponmaster]`, 3 cards with `[Unique]`.

Measured on the engine as it stands (2026-11-03):

1. Effect Text can only append trigger lists. The official Effect Texts are mostly keywords (`[Shield 2]`, `[Tank]`,
   `[Ganking]`, `[Deflect]`, `[Assault 2]`), statements ("I am a Mech.", "I have +2 Might while ...") and triggers.
2. An attached card's printed rules text stays active: its triggers fire and its activated abilities are offered.
   Core 435.1.e and 721.2 say they must not.
3. `attach` takes a literal host. Equip's host is a target chosen as the ability is played (818.1.b.1).
4. An activated ability's any-domain Power had no row form, so a `:rb_rune_rainbow:` Equip cost could not be
   catalogued, and Weaponmaster's "reduced by [A]" had nothing to reduce.
5. ADR-0012 §4 said the Equip host is "chosen at the same location". Core 818.1.c.2 puts no location on the host: any
   unit its controller controls will do. This ADR corrects it.

## Decisions

### 1. Equipment's printed characteristics (150, 136, 137)

A Gear object may carry `tags` containing `Equipment` (150.5), `might_bonus` (137; already summed over attachments by
`effective_might`) and `effect_text`. Effect Text becomes an ability bundle, not only trigger lists:

```
effect_text: {keywords: [...], keyword_values: {...}, triggers: {<appendable field>: [descriptor, ...]},
              statics: [continuous effect template, ...]}
```

Every part is written about "I / me", which is the Top-Most card once appended (435.1.c: the Top-Most card has the
Effect Text appended to its Rules Text). So an appended trigger's `source_object` is the Top-Most card, not the gear,
and a static's subject is the Top-Most card. While the gear is not attached its Effect Text is inactive (136.2.b, 724).

### 2. Rules text is Inactive while attached (435.1.e, 716-725)

An attached card's printed abilities are switched off entirely (721.2): its printed
triggers, statics, activated abilities and keyword functions are skipped wherever the engine collects active
abilities (`source_active`, `object_triggers`, `play_space.ability_skeletons`, keyword reads). Its keywords stay
present for reference (722.1): a rule or card that asks whether it has a keyword still sees it. One consequence the
rules intend: an attached Equipment cannot activate its own Equip; only an effect (Weaponmaster, a card that attaches)
moves it.

### 3. Equip (818)

`[Equip] <cost>` is an activated ability of the Gear (818.1.c.2: pay the cost, and the Gear attaches to one of your
units). It is a standard activated ability on the chain like any other; its catalogue row carries `keyword: "equip"`,
so Weaponmaster can find its cost (821.1.c.2). Its program is one instruction, `attach {object_id: $source_object,
target: {decision_ref, chosen_zone_class: board, kind: unit, controller_relation: friendly}}`: the host is a Target
chosen while the ability is played (818.1.b.1), any of your units on the board, wherever it is. `attach` gains this
target form (`to` or `target`, exactly one). "A unit you control" is written `friendly`, as the corpus writes every
"you control" target: the closed environment is 1v1 Duel, where the two are the same. When the attach completes the
host is Equipped (818.2); the `attached` event is what watchers see. Multiple Equip instances are separate rows
(818.4). An instruction to attach a unit does nothing (435.1.h.1).

Costs: an Equip cost's any-domain Power (`:rb_rune_rainbow:`) is a mandatory additional resource payment
`{kind: power_any, amount}` - the form [Deflect]'s and [Accelerate]'s any-domain Power already takes - so the base
cost keeps its domain-keyed Power. A resource payment names no object: the activation enumerator and the catalogued
declaration check treat it so.

### 4. Quick-Draw (819)

`quick_draw` is an object keyword. A card with it has Reaction timing (819.1.b) and a printed play trigger that
attaches it to one of your units (819.1.d); that host is a Target chosen when the trigger is put on the chain. Multiple instances add nothing (819.2).

### 5. Weaponmaster (821)

`weaponmaster` is a unit keyword whose function is a play trigger (821.1.c):

1. Optionally, pick one of your Equipment cards, attached or not (821.1.c.1).
2. Its Equip cost is worked out as for an Equip aimed at this unit, counting Equip cost modifiers that do not depend on
   the ability actually being played (821.1.c.2.b), and reduced by one any-domain Power if the cost
   has one (821.1.c.3). A card with no Equip cost cannot be paid (821.1.c.4).
3. If the cost is paid, the Equipment detaches from its current Top-Most card and attaches to this unit. If it cannot
   be paid, detached or attached, it stays where it is (821.1.c.5). The Equip ability is not activated and this unit
   is not chosen (821.1.c.6): no Equip-activation trigger fires and the Equipment's own inactive Equip ability is used
   only to read its cost (725.3).

The engine adds one instruction, `weaponmaster_attach {equipment: {decision_ref}, to: <self>}`, which reads the chosen
Equipment's Equip row, applies the reduction, asks for the payment as a decision of the trigger's controller, and
attaches. Each instance triggers separately (821.1.c.7, 821.1.d).

### 6. Unique (825) and the Recall of unattached Gear (459)

Unique is a deck-construction restriction (825.3) with no effect in play (825.4): the engine records the keyword; deck
validation (overlay, R5-P decks) enforces one copy per name. Rule 459 is already implemented: cleanup step 5 recalls
every non-unit Gear at a battlefield that is not attached (`battlefield_control._step_five`). `pending_recall`, which
nothing reads, is left as it is in this ADR.

## Not decided here

- Effect Text that copies its host's text (Svellsongur) and Effect Text that makes hold and conquer effects
  interchangeable (Skyfall of Areion) are named and stay unsupported until a later packet.
- Nested attachments stay outside the engine (ADR-0012 §4).

## Verification

Each decision lands with a check that fails on the engine before it: inactive printed text (a trigger of an attached
gear does not fire; its Equip is not offered), Effect Text keywords and statics on the host, the Equip target choice
(refuses a unit you do not control, accepts one at another location), `power_any` costs and discounts, Quick-Draw at
Reaction timing, Weaponmaster from base and from another host, with and without [A] in the cost, and the "cannot be
paid" path.
