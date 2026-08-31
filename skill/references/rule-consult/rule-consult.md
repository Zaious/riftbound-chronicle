# Rule Consult

Rule Consult is an unofficial rules research and explanation mode. It may answer detailed interaction questions; it is not the authority of record for a tournament.

Read `${CLAUDE_SKILL_DIR}/references/shared/source-authority.md` completely before researching a detailed or current interaction.

For exact clause work, also read `${CLAUDE_SKILL_DIR}/references/shared/local-rules.md` and check whether the local Core Rules and Tournament Rules PDFs exist. If they do not, stop at the supported source pointer and ask for the bootstrap or a current official link; do not invent page numbers or quote remembered wording.

For Open/Closed state, Showdown, Action/Reaction, Priority/Focus, Chain, or
HOT/FEPR questions, also read `${CLAUDE_SKILL_DIR}/references/shared/rules-core.md`.
For any executable timing, effect, resolution, or cleanup check, read
`${CLAUDE_SKILL_DIR}/references/shared/engine-check.md`. After retrieving the
controlling official text, use `engine_check.py` when the facts fit a supported
state/program contract. Treat a mismatch as a conformance defect and report it;
never prefer executable output over the official source.

For an auditable consultation, use `${CLAUDE_SKILL_DIR}/scripts/rule_consult.py` and the schema at `${CLAUDE_SKILL_DIR}/schemas/rule-consultation.schema.json`. Resolve source identifiers through `${CLAUDE_SKILL_DIR}/data/rules_source_registry.json`; the registry records versions and authority, but any source marked `resolve_at_query_time` must still be checked live.

Attach a completed shared check without hand-editing the consultation:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/rule_consult.py engine-check consultation.json `
  --check engine-check.json
```

New consultations store executable evidence in the `engine_checks` array. The
legacy nullable `rules_core_check` field remains accepted only so existing
`rule-consultation.v1` artifacts continue to validate. The deprecated
`core-check` CLI command normalizes a raw rules-core result into
`engine-check.v1`; it no longer creates new timing-only evidence.

Keep source confidence and engine coverage distinct. A `supported` engine check
does not raise source authority. `unsupported` means the executable component
abstained, not that no official answer exists. `decision_required` identifies
facts or controller choices needed for a retry; Rule Consult presents those
choices neutrally and does not choose on the player's behalf.

## Retrieve before interpreting

When the local corpus is installed, use `rules_index.py search` rather than
free-form scanning. Search exact rule/card names first, then mechanic synonyms.
For Chinese questions, retrieve Chinese terminology and the controlling English
text where available. Confirm the cited page and surrounding clause in the PDF.

Do not finalize from a single hit. Check, in order:

1. whether the source is `active` and applies to the requested region/format;
2. whether an official FAQ or errata specifically covers the interaction;
3. the current Tournament/Core rule clause and relevant definitions;
4. whether a translated result agrees with the controlling English text;
5. whether every card is using corrected current text;
6. whether the supplied facts are sufficient to apply the retrieved text.

The search index returns evidence candidates, not legal actions or game-state
transitions. Never cite a `superseded` source in a current consultation. Judge
guidance may support Medium-confidence analysis but cannot by itself satisfy the
final artifact's official-source requirement.

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

### Judge-prep handoff (non-authoritative)

Rule Consult may prepare a compact handoff for a live judge without becoming a judge. Use this when a player needs to ask a Head Judge a precise question at an event:

- include the exact question, event/OPL, format, turn/phase or chain state, actors and controllers, targets, timing, card text/errata, and every material assumption;
- attach official source locators first, then clearly label community sources as discovery or supporting analysis;
- show competing readings and the fact that would distinguish them;
- end with one neutral question for the Head Judge and a list of facts still needed.

The handoff must never assign a penalty, claim an official ruling, promise a strategic result (for example, whether an action will win), or write game state. Tournament Rules distinguish rules/interaction questions from strategic-result questions; the latter may be declined or rephrased by a floor judge at higher organized-play levels. The live Head Judge remains the final authority.

## Currentness

For a non-trivial interaction, verify current official FAQ, Core Rules, applicable Tournament Rules, card errata, and card text as needed. Cite the version or effective date when available. If the available local snapshot is older than a plausible rules update, use a live official source or say that currentness could not be established.

## Evaluation cases

`${CLAUDE_SKILL_DIR}/data/rule_consult_cases.json` contains the initial semantic regression corpus. Use it to test conclusion meaning, confidence, escalation, and source selection. Do not train an answer by copying its token list; the tokens are minimum semantic invariants, not a complete response.
