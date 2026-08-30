# Local official rule documents

The public repository does not bundle Riot-owned rule PDFs. It ships a source
manifest and an explicit opt-in downloader instead:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/bootstrap_rules.py --yes
```

The default destination is `${CLAUDE_SKILL_DIR}/.local/rules/`, which is ignored
by Git. Set `RIFTBOUND_RULES_DIR` or pass `--rules-dir` when the Skill is
read-only, symlinked, or managed outside the repository:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/bootstrap_rules.py `
  --rules-dir "$env:USERPROFILE/.riftbound-chronicle/rules" --yes
```

The default bootstrap installs exactly the two controlling English documents:

- `riftbound-core-rules-2026-07-16.pdf`
- `riftbound-tournament-rules-2026-07-16.pdf`

It writes `rules.lock.json` with the download timestamp, local paths, byte
counts, and SHA-256 values. The lock file is local-only; it is not an authority
claim and it does not replace a current Rules Hub check.

Install the optional Simplified Chinese research pack, or every available PDF:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/bootstrap_rules.py --include-zh-cn --yes
python ${CLAUDE_SKILL_DIR}/scripts/bootstrap_rules.py --all --yes
```

The `zh-cn` group contains current Chinese Core/Tournament Rules, the regional
ban list, available official FAQs and errata, and separately labeled judge-team
guidance. It does not change the controlling language: if an English rule and a
translation diverge, use the English source and disclose the conflict.

## Page-addressable local search

After installing documents, build the ignored SQLite index:

```powershell
python ${CLAUDE_SKILL_DIR}/scripts/rules_index.py build
python ${CLAUDE_SKILL_DIR}/scripts/rules_index.py search "339.1"
python ${CLAUDE_SKILL_DIR}/scripts/rules_index.py search "連鎖 結算" --json
python ${CLAUDE_SKILL_DIR}/scripts/rules_index.py search "勘誤" --document-class card_errata
```

Each result includes `source_id`, version, locale, authority, page, locator,
status, and an excerpt. Search is evidence retrieval, not an automatic ruling.
Default search excludes superseded sources. Use `--include-superseded` only for
provenance or historical comparison and never as the basis of a current answer.

For a precision consultation, retrieve both the best local-language passage and
the controlling English passage when available. Open the cited page to confirm
the surrounding text before quoting it. Then apply source precedence, current
errata, disclosed facts, and assumptions through Rule Consult.

If these files are missing, do not reconstruct exact clauses from memory. Tell
the player to run the bootstrap or provide a current official source. For a
competitive procedure, use this precedence:

```text
event addendum > Tournament Rules > Core Rules where unmodified > live Head Judge
```

The official Rules Hub is the canonical entry point for refreshing the manifest
and checking whether newer documents have replaced the indexed files. Run
`rules_index.py audit` after any refresh to find installed-but-unindexed files.
