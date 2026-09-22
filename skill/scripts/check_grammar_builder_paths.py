#!/usr/bin/env python3
"""The grammar builder writes to its own checkout and to nothing else.

build_clause_grammar.py once had ROOT hard-coded to one delegation worktree's absolute
path, so running it from any other checkout rewrote THAT worktree's grammar and left
the running one stale (found 2026-09-22). This runs the real builder from a throwaway
second checkout - a temp copy of skill/scripts and the two data files it touches - and
holds that:

  - the builder's output lands at <that checkout>/skill/data/clause_grammar/clause_grammar.json
    and it reproduces this checkout's committed grammar byte for byte
  - this checkout's grammar is untouched (content and mtime)
  - no sibling worktree of this checkout (any directory next to it that carries a
    skill/data/clause_grammar/clause_grammar.json) changed
  - the temp checkout gained nothing outside its own grammar file

and mutates the builder once (ROOT pinned back to an absolute path elsewhere) to prove
the check goes red.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKOUT = SCRIPT_DIR.parent.parent
BUILDER = SCRIPT_DIR / "build_clause_grammar.py"
GRAMMAR = Path("skill") / "data" / "clause_grammar" / "clause_grammar.json"
CATALOGUE = Path("skill") / "data" / "keyword_catalog" / "keyword_catalog.json"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def siblings() -> dict[Path, tuple[str | None, int | None]]:
    """Every checkout next to this one that has a grammar file a stray write could hit."""
    # Two levels up as well as one: this engine is often a submodule (repo/engine), and
    # the delegation worktrees sit next to the superproject, not next to the submodule.
    found = {}
    for level in (CHECKOUT.parent, CHECKOUT.parent.parent):
        try:
            candidates = list(level.iterdir())
        except OSError:
            continue
        for candidate in candidates:
            for target in (candidate / GRAMMAR, candidate / "engine" / GRAMMAR):
                try:
                    if (candidate.is_dir() and target.exists()
                            and target.resolve() != (CHECKOUT / GRAMMAR).resolve()):
                        found[target] = (digest(target), target.stat().st_mtime_ns)
                except OSError:
                    continue
    return found


def run_from_copy(builder_source: str) -> tuple[list[str], dict]:
    problems: list[str] = []
    ours = CHECKOUT / GRAMMAR
    ours_before = (digest(ours), ours.stat().st_mtime_ns)
    siblings_before = siblings()
    with tempfile.TemporaryDirectory(prefix="grammar-builder-") as temp_name:
        second = Path(temp_name) / "second-checkout"
        shutil.copytree(SCRIPT_DIR, second / "skill" / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (second / "skill" / "scripts" / "build_clause_grammar.py").write_text(builder_source, encoding="utf-8")
        for rel in (GRAMMAR, CATALOGUE):
            (second / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CHECKOUT / rel, second / rel)
        (second / GRAMMAR).unlink()                     # it must be the builder that makes it
        before = snapshot(second)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        run = subprocess.run([sys.executable, str(second / "skill" / "scripts" / "build_clause_grammar.py")],
                             cwd=Path(temp_name), capture_output=True, text=True, env=env, check=False)
        if run.returncode != 0:
            problems.append(f"the builder failed from a second checkout: {run.stderr.strip()[-200:]}")
        produced = second / GRAMMAR
        if not produced.exists():
            problems.append("the builder did not write the second checkout's own grammar")
        elif digest(produced) != ours_before[0]:
            problems.append("the second checkout's grammar differs from this checkout's committed grammar")
        added = sorted(set(snapshot(second)) - set(before) - {str(GRAMMAR)})
        if added:
            problems.append(f"the builder wrote files outside its own grammar: {added[:3]}")
    if (digest(ours), ours.stat().st_mtime_ns) != ours_before:
        problems.append("the builder, run from a second checkout, rewrote THIS checkout's grammar")
    for target, state in siblings_before.items():
        if (digest(target), target.stat().st_mtime_ns) != state:
            problems.append(f"the builder rewrote a sibling worktree's grammar: {target}")
    return problems, {"siblings_watched": len(siblings_before)}


def main() -> int:
    source = BUILDER.read_text(encoding="utf-8")
    problems, facts = run_from_copy(source)

    # mutation: ROOT pinned to an absolute path that is not the running checkout
    anchor = "ROOT = Path(__file__).resolve().parent.parent.parent"
    if source.count(anchor) != 1:
        problems.append("the builder no longer derives ROOT from its own location")
        caught = False
    else:
        with tempfile.TemporaryDirectory(prefix="grammar-builder-elsewhere-") as elsewhere:
            (Path(elsewhere) / GRAMMAR).parent.mkdir(parents=True)
            (Path(elsewhere) / CATALOGUE).parent.mkdir(parents=True)
            shutil.copy2(CHECKOUT / CATALOGUE, Path(elsewhere) / CATALOGUE)
            (Path(elsewhere) / "skill" / "scripts").mkdir()
            pinned = source.replace(anchor, f"ROOT = Path({str(Path(elsewhere))!r})")
            mutated, _ = run_from_copy(pinned)
            caught = bool(mutated)
    if not caught:
        problems.append("mutation not caught: a builder pinned to another path still passed")

    if problems:
        print("FAILED: grammar builder paths" + chr(10) + "  - " + (chr(10) + "  - ").join(problems))
        return 1
    print(f"OK: build_clause_grammar.py run from a second checkout writes only that checkout's grammar, "
          f"reproduces the committed grammar, and leaves this checkout and {facts['siblings_watched']} "
          f"sibling worktree(s) untouched; a builder pinned to another path is caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
