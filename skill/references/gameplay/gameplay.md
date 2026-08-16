> Book: gameplay (new, 2026-08-16 — companion to deckbuilding; deckbuilding decides what goes in a deck before the game, this book decides what to do with it once the game is live)
> x-source: original(2026-08-16 built from official Riftbound Core Rules content at playriftbound.com/en-us/rules-hub/ plus community explainer sites — learnriftbound.gg's chain/priority breakdown, riftbound.zone's combat/showdown breakdown, runesandrift.com's turn-phase breakdown, and mulligan-heuristic writeups referenced across the community — cross-checked against each other where they overlapped, cited as community analysis throughout since none of these sites are Riot)
> last-verified: 2026-08-16
>
> Summary: In-game piloting advisor for Riftbound — turn structure, the chain/priority/focus system, combat and showdown resolution, mulligan decisions, and a tiered method for piloting a specific finished decklist (mechanical synthesis vs. cross-referenced sourcing vs. plainly-unverified, kept explicitly separate). Different concern from the deckbuilding book: that book is about what a deck contains before the game starts, this one is about what to actually do, turn by turn, once it's live. Use when: reviewing whether a play or sequencing decision was correct, explaining what happens in a specific chain/showdown interaction, deciding whether to attack or hold a battlefield, evaluating a mulligan, or asking how to actually pilot a specific deck.

# Gameplay

Deckbuilding answers "what should be in this deck." This book answers "given this board, this hand, and this phase, what's the right move." They fail in different ways: a deckbuilding mistake shows up over many games as a structural weakness, a gameplay mistake is a single wrong decision in a single turn. Don't reach for deckbuilding-methodology language ("this deck wants to be aggro") when the actual question is a live tactical one ("should this unit attack now or wait one more turn").

Base mechanics below (turn phases, the chain, combat resolution) are stable enough to state directly. Anything that depends on current card text or current legality is a different question — check it against the live sources in the library's top-level "route, don't snapshot" section, not against memory of a specific card's effect.

## Turn structure: the six phases

A turn belongs to one player (the Turn Player); the other is the Off-Turn Player for that turn. Control passes after End of Turn completes. Six phases, in order, every turn:

1. **Awaken** — ready all Runes, Units, and Gear you control (undo exhaustion from last turn).
2. **Beginning** — score one point for each Battlefield you control uncontested; any "start of turn" triggered abilities resolve here.
3. **Channel** — draw 2 Rune cards from your Rune Deck into your Base, ready. (The second player channels 3 on their very first turn, to offset going second.)
4. **Draw** — draw one card from your Main Deck; your Rune Pool (unspent Energy/Power) empties at the end of this phase — resources don't carry over. If your Main Deck is empty when you'd draw, your opponent scores a point instead of you drawing.
5. **Main** — the phase with actual decisions: play Units/Spells/Gear, activate abilities, move Units, initiate Showdowns and Combat. No fixed action limit — resources and legality are the only constraints.
6. **End of Turn** — temporary effects expire, Marked Damage clears from all Units, the Rune Pool empties again, turn passes.

Players alternate turns until someone reaches the win condition. Because scoring happens in Beginning (not at the end of a turn), a Battlefield you're about to lose still needs to be defended *before* your opponent's next Beginning phase, not just "at some point" — the scoring clock is tighter than it first looks.

*(Source: runesandrift.com's turn-order breakdown, community analysis — cross-check phase names/order against the official Core Rules PDF if a specific ruling hinges on exact phase boundaries.)*

## The chain, priority, and focus

This is the response/interaction system — the part of the rules most likely to get misplayed by someone reasoning from a different TCG's stack rules.

**Two states.** *Open*: no active chain. The player who currently has priority can play an Action, activate an ability, move a unit, or pass — Actions are the only card type playable in this state, and playing one opens a chain. *Closed*: a chain is active. From here, players may only add *Reactions*, each stacking on top of the last.

**Priority vs. focus — different jobs, don't conflate them.** *Priority* governs who can respond within an already-open chain; it alternates between players as the chain builds and resolves. *Focus* governs who can *start* a new chain in the first place, which matters most during a Showdown — only the Focus holder can initiate. In a Showdown, the **attacker gets Focus first**.

**Chain resolution is LIFO** — last added, first resolved, one link at a time, with priority handed back after each resolution so a player can respond again before the next link resolves. A chain closes only once both players pass consecutively.

**Sequencing is the actual skill here.** Acting last in a chain gives you the most information and the most control — you get to see what your opponent committed before you commit further. The practical heuristic community sources converge on: *pass last, spend last* — let the opponent commit resources first whenever the situation allows it. Holding priority to play multiple reactions before passing is legal and often correct when you want to commit several effects as a single, harder-to-answer block rather than telegraphing them one at a time.

*(Source: learnriftbound.gg's chain/priority explainer, cross-checked against app.riftjudge.com rulings on specific priority-in-showdown questions — both community-tier, verify against the Core Rules PDF for a ruling that actually matters in a sanctioned event.)*

## Combat and showdowns

A Showdown starts when ready units move toward a Battlefield during the Main phase — the moving units become **attackers**, units already there become **defenders**.

**Two kinds.** *Open Showdown*: moving onto a Battlefield nobody controls grants control immediately, no Might comparison at all. *Combat Showdown*: moving onto a Battlefield the opponent controls triggers an actual fight.

**Combat Showdown resolution, in order:**

1. **Sum Might** — add up combined Might on each side. Purely arithmetic at this step.
2. **Spell window** — before the comparison locks in, both players can chain spells that buff, debuff, or otherwise disrupt the coming comparison. This is where the actual decision-making in a showdown happens, not the arithmetic itself.
3. **Simultaneous damage assignment** — both sides assign damage at the same time; nobody strikes first. You must assign lethal damage to fully kill one unit before you're allowed to spread damage onto another — you cannot chip multiple units instead of finishing one.
4. **Determine the winner** — whichever side has the greater combined Might destroys correspondingly more of the opposing units. On a tie, **all units on both sides are destroyed** — a dead-even Showdown is not a non-event, it's a mutual wipe.
5. **Healing, then Deathknell** — surviving units return to full health *before* "when this dies" (Deathknell) effects resolve. This ordering matters for combo timing: don't assume a unit that's about to die can't first trigger something, and don't assume a survivor is still damaged going into the next step.
6. **Claim** — an attacker only claims the Battlefield by destroying *all* defenders. Partial damage that doesn't clear the defense doesn't flip control.

**Tactical read**: because damage assignment is simultaneous and lethal-first, "trading down" (accepting a worse Might total to bait a spell response, or to force the defender to over-commit a spell that could matter more later) is a real, deliberate line — not just a losing attack. Whether to fight for a Battlefield now versus waiting a turn to build a bigger Might total is the actual decision this section supports; there is no universal answer, it depends on the race (see deckbuilding book's archetype framing — an aggro plan wants to force early Showdowns before the opponent stabilizes, a control plan is fine holding back and forcing the opponent to commit first).

*(Source: riftbound.zone's combat/showdown breakdown, community analysis, cross-checked against the general chain/priority sourcing above since a Showdown's spell window runs on chain rules.)*

## Mulligan

Mechanic: take up to 2 cards from your opening hand, bottom them into your Main Deck, and draw one replacement for each card bottomed. One mulligan opportunity, and it's all-or-nothing per card you choose — you can't ship the whole hand and start over, and you can't take multiple mulligan passes. The entire skill is in choosing which cards to swap, not in the mechanical action itself.

**What makes a hand keepable** — three things to check for, per community heuristics:

1. **A turn-1 play** — something credible to do on the very first action, typically a unit or a piece of Gear. A hand with no turn-1 play is already behind on tempo in a game where board/Battlefield presence is the win condition (see deckbuilding book).
2. **A turn-2 plan** — a second unit, a removal spell, a combat trick, or a counter — something that keeps developing rather than passing.
3. **A line into the deck's actual win condition** — anything that either advances the current game plan or starts pulling the engine (whatever this specific deck's archetype depends on) toward relevance from turn two onward.

If any of the three is missing from the hand, that's the signal for what to consider swapping — identify the worst 0, 1, or 2 cards against those three criteria and replace exactly those, not a blanket "this hand feels bad" call. Before seeing what the opponent is doing, evaluate generically against these three; once the opponent's Legend/first plays are visible, re-evaluate — a card that's fine in the abstract but dead against what's actually on the table is now a mulligan target too.

*(Source: mulligan-heuristic writeups referenced across multiple community sites, converging on the same three-part framework — treat as settled community consensus rather than one site's opinion, but it's still not official Riot guidance.)*

## Piloting a specific decklist

Someone hands you a finished decklist and asks how to actually play it — not "what does this deck do" (deckbuilding's question) but "given this exact list, what's my sequencing priority, what do I hold, what do I race for." This book is card-agnostic mechanics by design (see "Process discipline" below), so answering this well means combining two things this library already has solidly grounded — deckbuilding's archetype/Legend-construction-logic analysis and this book's own turn/chain/combat mechanics — rather than inventing tactical judgment from nothing. Three tiers, and don't blur them together:

**Tier 1 — mechanically derived, always available, no external lookup needed.** Once a decklist is classified by archetype and Legend construction-logic (per the deckbuilding book's methods), its general sequencing priorities follow directly from mechanics already established in this book. An aggro deck wants to initiate Showdowns early (deckbuilding's archetype framing) — combined with the fact that scoring happens in the Beginning phase and combat damage is simultaneous-and-lethal-first (this book's combat section), the concrete instruction is "contest Battlefields before your opponent's board stabilizes, and don't be shy about a Might-losing trade if it removes what would otherwise out-tempo you next turn." A control deck's "hold back and let the opponent commit first" instinct is the same "pass last, spend last" chain-sequencing principle already stated generically, just applied with this specific deck's removal/answers in mind. A deck whose Legend construction-logic implies a compounding, turn-over-turn resource edge (the Annie pattern, in the deckbuilding book) should generally prioritize surviving to accumulate that edge over racing — that's a synthesis of two already-grounded facts, not a new claim.

**Tier 2 — requires the same cross-referenced-sourcing discipline as a Legend's role-level pattern, and for the same reason.** Anything more specific than the mechanical synthesis above — a particular matchup's plan, a specific sequencing trick against a specific opposing archetype, "hold this card until turn X because of Y" — is exactly the kind of tacit, play-tested knowledge that doesn't come from reading text alone. Get it the same way the deckbuilding book's Annie example does: cross-reference multiple independent real sources (tournament reports, matchup write-ups) and state the pattern, not a single author's opinion. Citing one stray forum post as if it settles a matchup is worse than not answering.

**Tier 3 — say so.** If neither tier produces a real answer — no mechanical synthesis reaches the specific question, and no independently-corroborated source exists — the honest answer is "there's no verified basis for that yet," not a confident-sounding guess dressed up as advice. This is not a hypothetical caution: most decklists for a young, fast-changing card pool won't have Tier 2 material behind them at all, especially outside Global Standard's more-played environment — expect to lean on Tier 1 alone most of the time, and say so rather than papering over the gap.

## Process discipline

- Don't answer a "what happens if…" interaction question from card-text-plus-general-TCG-intuition alone if the interaction is non-obvious (timing of triggered abilities, whether an effect can target something already removed from the chain, etc.) — check `app.riftjudge.com` for an existing ruling before inventing one.
- A single bad Showdown doesn't diagnose a deck or a line of play as wrong — same discipline as the deckbuilding book's "don't judge after one or two games." Look for a pattern across repeated attempts before concluding a specific sequencing choice was the mistake versus just a bad matchup or bad luck on the Might comparison.
- When reviewing a play retroactively, separate "was this legal/did it resolve correctly" (a rules question — verify against the Core Rules PDF or RiftJudge) from "was this the right decision given the information available at the time" (a strategy question — this book's actual subject matter). Don't let uncertainty about the first one leak into a strategy verdict.
- This book's core mechanics sections above are deliberately card-agnostic. "Piloting a specific decklist" is the one place this book does get archetype- and card-specific, and it inherits the library's card-pool discipline accordingly (see the library's top-level rule and the deckbuilding book's `regional-legality-model.md`): a tactic described by a source predating Riftbound's first ban wave (2026-03-31) may already be describing something banned everywhere, in every region, including ones that haven't launched yet. That section's Tier 2/3 split exists specifically to keep this contained — mechanical synthesis stays evergreen, sourced tactics carry the same staleness risk as everything else that names a real card.
