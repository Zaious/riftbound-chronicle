# Rule corpus engineering

Status: implemented retrieval baseline
Last reviewed: 2026-08-26

## Purpose

Rule Consult needs reproducible evidence retrieval without becoming a rules
engine. The tracked repository stores source metadata and tooling; Riot-owned
PDFs, extracted text, hashes, and the SQLite index remain local and ignored.

## Adopted engineering patterns

The public [Mercantec-GHC/riftbound-tcg](https://github.com/Mercantec-GHC/riftbound-tcg)
prototype was reviewed at commit `d802baedfb6f82bace5ec3ea42a6f9db200b4ed8`
(2026-06-26). It had no license file at that revision and its bundled rules
baseline was the older 2026-03-30 RUP3 document. Chronicle therefore copied no
code, Markdown, or rule text from it.

Chronicle independently applies three useful patterns:

1. **Addressable rules:** extracted passages preserve document, page, and rule
   locator instead of becoming an undifferentiated prompt dump.
2. **Coverage audit:** the manifest, local lock, and index can be compared to
   identify missing or installed-but-unindexed documents.
3. **Scenario tests:** bilingual retrieval, exact-locator ranking, authority
   labels, and superseded-source masking have deterministic regression tests.

Mercantec's legal-action engine, event-sourced match state, automatic
resolution, and simulation belong to the separately planned P2-S track. They
are not part of Rule Consult or the implemented P2-A protocol.

## Data flow

```text
tracked registry + tracked manifest
  -> explicit opt-in PDF download
  -> local SHA-256 lock
  -> page-aware extraction
  -> local SQLite passages
  -> bilingual evidence search
  -> Rule Consult facts + assumptions + cited analysis
```

Search never determines legality, mutates game state, or promotes judge/community
guidance into official authority. Current answers exclude `status: superseded`;
historical lookup requires an explicit flag and exposes `superseded_by`.

## Maintenance gate

When an official document changes:

1. update the registry status and successor pointer;
2. update or add the manifest record without overwriting historical provenance;
3. refresh the local install and rebuild the index;
4. run `check_rules_bootstrap.py`, `check_rules_index.py`, and
   `check_rule_consult.py`;
5. add a semantic case when the update changes an answer or precedence path.
