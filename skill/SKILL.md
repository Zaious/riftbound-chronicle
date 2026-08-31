---
name: riftbound
metadata:
  source: "original(2026-08-24 evolved from a two-book deckbuilding/gameplay library into three explicit systems: deck-coach, rule-consult, and player2-agent; P2-A implemented as a human-confirmed protocol, P2-S documented but not implemented)"
description: |
  Riftbound knowledge and decision-support library with three modes: deck-coach for construction and deck piloting, rule-consult for cited unofficial rules explanations and interaction analysis, and player2-agent for strategic Player 2 decisions in human-operated physical practice. Use for decklists, primers, mulligans, sequencing, rules questions, interaction analysis, or a manually confirmed Player 2 session. This skill does not provide automated rules enforcement or a Riftbound simulator; P2-S is planned only.
---

# Riftbound Library

Route every request to one primary mode. Read that mode's entrypoint completely before answering or acting. When a mode directs you to a supporting book, read that book completely as well.

Resolve paths from the directory containing this `SKILL.md`. In Claude Code, use `${CLAUDE_SKILL_DIR}` so the Skill remains portable when invoked away from its own directory.

## Choose the mode

- **Deck construction, deck review, substitutions, legality, deck primer, mulligan plan, or how to pilot a finished list** → read `${CLAUDE_SKILL_DIR}/references/deck-coach/deck-coach.md`.
- **How a rule works, what happens in a specific interaction, source precedence, or whether a tournament interpretation is supportable** → read `${CLAUDE_SKILL_DIR}/references/rule-consult/rule-consult.md`.
- **Act as the second player in a human-operated physical game, choose between actions, or maintain a P2-A decision record** → read `${CLAUDE_SKILL_DIR}/references/player2-agent/player2-agent.md`.

If a request spans modes, choose the mode that owns the final output, then consult the other entrypoint only for the needed sub-question. Examples:

- A deck primer that needs a keyword explanation remains a `deck-coach` output informed by `rule-consult`.
- A Player 2 decision that needs interaction research remains a `player2-agent` proposal informed by `rule-consult`.
- A ruling explanation never becomes a state transition unless a human separately confirms and records it.

## Sovereign rules core

For a claim about Open/Closed state, Showdown, Action/Reaction timing,
Priority, Focus, Pending/Finalized Chain Items, or HOT/FEPR, read
`${CLAUDE_SKILL_DIR}/references/shared/rules-core.md`. When the supplied state
is structured enough, use `${CLAUDE_SKILL_DIR}/scripts/rules_core.py` to derive
the timing permission or next procedure instead of reconstructing it from
general TCG intuition.

The executable core is Chronicle-owned and versioned, but bounded. Its result
is a consistency check under the stated rules baseline, not an authority that
can override a current official rule or scoped FAQ. Unsupported card effects
remain unknown. Player 2 outputs still require human confirmation unless a
separately approved state-owning runtime is explicitly introduced.

When a claim depends on what a card instruction actually changes, read
`${CLAUDE_SKILL_DIR}/references/shared/effect-ir.md`. Use
`${CLAUDE_SKILL_DIR}/scripts/effect_ir.py` only for operations listed as
supported there. An unsupported effect must lower confidence or stop the
sequence; never complete it from card-text intuition and present that state as
executable.

When Deck Coach, Rule Consult, Player 2 Agent, or the planned Match Analyst
needs to consume an executable result, read
`${CLAUDE_SKILL_DIR}/references/shared/engine-check.md`. Produce the shared
`engine-check.v1` envelope with `${CLAUDE_SKILL_DIR}/scripts/engine_check.py`
rather than embedding a component-specific raw result directly. The envelope
is a non-authoritative consistency check and never changes a consumer's state
or legality authority.

## Shared source authority

Before quoting current card text, legality, errata, or tournament procedure, read `${CLAUDE_SKILL_DIR}/references/shared/source-authority.md`. Use local data for routine lookup only within its documented freshness and provenance limits. Do not answer a live, time-sensitive question from memory.

For exact rule clauses, read `${CLAUDE_SKILL_DIR}/references/shared/local-rules.md`. The public repository does not bundle official PDFs. If the ignored local Core Rules and Tournament Rules files are absent, ask the user to run `python ${CLAUDE_SKILL_DIR}/scripts/bootstrap_rules.py --yes` (or provide a current official Rules Hub source) before making a precision claim. The optional `--include-zh-cn` pack supports bilingual retrieval; build and query its page-addressable index with `${CLAUDE_SKILL_DIR}/scripts/rules_index.py`.

## Non-negotiable boundaries

- This Skill is unofficial and never claims Riot endorsement or binding judge authority.
- `rule-consult` may give a reasoned answer to detailed interactions, but must cite sources, expose assumptions, calibrate confidence, and escalate tournament procedure or unresolved ambiguity.
- `player2-agent` is currently P2-A only: the human owns physical operations, legality, resolution, and authoritative state.
- Never claim that an Agent proposal is already legal. The human must confirm it.
- Never infer the resulting authoritative state from an accepted action; request a new human-confirmed snapshot.
- Do not reveal or use Player 1 hidden information.
- Do not implement or pretend to run P2-S, automated rules enforcement, automatic resolution, matchmaking, ranks, ladders, or metagame-defining rate analysis.

## Portable resources

- Bundled card snapshot and errata: `${CLAUDE_SKILL_DIR}/data/`
- Deterministic validation and artifact tooling: `${CLAUDE_SKILL_DIR}/scripts/`
- Chronicle-owned timing/permission core: `${CLAUDE_SKILL_DIR}/scripts/rules_core.py`
- Executable rules-core cases: `${CLAUDE_SKILL_DIR}/data/rules_core_cases.json`
- Chronicle-owned typed effect IR: `${CLAUDE_SKILL_DIR}/scripts/effect_ir.py`
- Atomic timing/effect bridge: `${CLAUDE_SKILL_DIR}/scripts/resolution_bridge.py`
- Shared engine-result envelope and runner: `${CLAUDE_SKILL_DIR}/scripts/engine_check.py`
- Deck Coach, Rule Consult, and P2-A schemas: `${CLAUDE_SKILL_DIR}/schemas/`
- Local official rule PDFs, when the user has opted in: `${CLAUDE_SKILL_DIR}/.local/rules/` (ignored, never committed)
- Rift Atlas deck handoff adapter: `${CLAUDE_SKILL_DIR}/scripts/riftatlas_bridge.py` (user-pasted list, no upstream scraping)

A deployment may provide a sibling private companion Skill for approved/current data bindings. Keep deployment-specific paths, credentials, and publishing behavior out of this public portable folder.
