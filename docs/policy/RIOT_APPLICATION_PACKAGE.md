# Riot Application Package

Status: preparation checklist
Date: 2026-08-24

## Short product description

Riftbound Chronicle provides three AI-assisted knowledge modes: a deck coach, an unofficial rules consultant, and a Player 2 Agent for manually operated physical practice. In Player 2 mode, the human owns the physical cards, confirms the game state and legal actions, resolves every rule interaction, and records the resulting state. The software proposes strategy but does not enforce rules or automatically resolve gameplay.

## P2-A demonstration script

1. Show two physical decks and identify which one belongs to Player 2 Agent.
2. Create a P2-A session.
3. Enter a public board summary and Player 2's private hand.
4. Ask the Agent for candidate actions and a preferred choice.
5. Show that the proposal is marked `unverified`.
6. Have the human confirm legality and physically perform the action.
7. Enter the resulting position as a separate human-confirmed snapshot.
8. Export and display the event ledger.
9. Show validation rejecting `engine_derived`, `rules_engine`, or `p2s_enabled: true`.

## Materials to provide

- Working prototype or hosted rendering.
- Short screen-and-table video of the complete flow.
- User-flow diagram.
- Product responsibility matrix.
- Repository and distribution URL.
- Platform list.
- Data/asset source plan.
- Privacy and retention statement for private hands and session logs.
- Non-monetization statement for gameplay facilitation.
- Required fan-project disclaimer.
- Explicit statement that P2-S is planned but not implemented.

## Questions for Developer Support

1. Does the described P2-A flow qualify as manual gameplay facilitation when the human confirms legality and performs every resolution?
2. May the Agent suggest candidate strategic actions if each remains unverified until human confirmation?
3. Is storing a user-authored public-state summary and Player 2's own hand acceptable when the app performs no automatic resolution?
4. Should this capability be distributed only through a broader multi-game platform, even if the portable knowledge package is Riftbound-specific?
5. At which prototype stage should RSO integration begin, and what is expected before approval?
6. Which Riot API card/rules assets may be used during prototype review?

## Evidence to avoid overstating

- A submitted application is not approval.
- A prototype is not an authorized production release.
- A rules explanation is not a Riot or Head Judge ruling.
- A planned P2-S architecture is not a currently available capability.
