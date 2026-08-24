# Rule Consult

Rule Consult is an unofficial rules research and explanation mode. It may answer detailed interaction questions; it is not the authority of record for a tournament.

Read `${CLAUDE_SKILL_DIR}/references/shared/source-authority.md` completely before researching a detailed or current interaction.

For exact clause work, also read `${CLAUDE_SKILL_DIR}/references/shared/local-rules.md` and check whether the local Core Rules and Tournament Rules PDFs exist. If they do not, stop at the supported source pointer and ask for the bootstrap or a current official link; do not invent page numbers or quote remembered wording.

For an auditable consultation, use `${CLAUDE_SKILL_DIR}/scripts/rule_consult.py` and the schema at `${CLAUDE_SKILL_DIR}/schemas/rule-consultation.schema.json`. Resolve source identifiers through `${CLAUDE_SKILL_DIR}/data/rules_source_registry.json`; the registry records versions and authority, but any source marked `resolve_at_query_time` must still be checked live.

## Classify the question

1. **General mechanic:** explain from the current official rules and give a concise example.
2. **Specific interaction:** separate facts from assumptions, retrieve the relevant card text and rules, then analyze the sequence.
3. **Tournament procedure or penalty:** explain the governing source but defer the actual event decision to its Head Judge.
4. **Source conflict or missing fact:** state what is missing, give conditional outcomes when possible, and escalate instead of guessing.

## Required answer shape for a specific interaction

1. **Most likely answer** — direct, conditional when necessary.
2. **Facts supplied** — only what the user or authoritative source establishes.
3. **Assumptions** — phase, priority, targets, controller, timing, format, errata, or other facts that could change the result.
4. **Rule basis** — exact current sources and precedence.
5. **Analysis** — the resolution sequence in plain language.
6. **Confidence** — High, Medium, or Low, with a reason.
7. **Official status / escalation** — say this is unofficial; identify when an event Head Judge or Riot clarification is required.

For a simple general-mechanic question, compress this structure without dropping the source or unofficial status when the answer could be mistaken for a ruling.

## Confidence

- **High:** current official text directly covers the facts and no material fact is missing.
- **Medium:** the conclusion is a strong reading but depends on an interpretation, scoped community ruling, or disclosed assumption.
- **Low:** source conflict, incomplete facts, or no authoritative coverage; present possibilities and escalate.

Do not raise confidence merely because multiple community pages repeat one another.

## Authority boundary

- Never claim to be Riot, a certified judge, or the event's Head Judge.
- Never overrule a live Head Judge.
- Never assign tournament penalties.
- Never convert the consultation result into a P2-A state change. Return the analysis to the human, who decides what to record.
- A community rulings database is supporting analysis, not an official source.

## Currentness

For a non-trivial interaction, verify current official FAQ, Core Rules, applicable Tournament Rules, card errata, and card text as needed. Cite the version or effective date when available. If the available local snapshot is older than a plausible rules update, use a live official source or say that currentness could not be established.

## Evaluation cases

`${CLAUDE_SKILL_DIR}/data/rule_consult_cases.json` contains the initial semantic regression corpus. Use it to test conclusion meaning, confidence, escalation, and source selection. Do not train an answer by copying its token list; the tokens are minimum semantic invariants, not a complete response.
