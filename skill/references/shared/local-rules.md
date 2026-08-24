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

The bootstrap installs exactly two local documents:

- `riftbound-core-rules-2026-07-16.pdf`
- `riftbound-tournament-rules-2026-07-16.pdf`

It writes `rules.lock.json` with the download timestamp, local paths, byte
counts, and SHA-256 values. The lock file is local-only; it is not an authority
claim and it does not replace a current Rules Hub check.

If these files are missing, do not reconstruct exact clauses from memory. Tell
the player to run the bootstrap or provide a current official source. For a
competitive procedure, use this precedence:

```text
event addendum > Tournament Rules > Core Rules where unmodified > live Head Judge
```

The official Rules Hub is the canonical entry point for refreshing the manifest
and checking whether a newer pair of documents has replaced these files.
