#!/usr/bin/env python3
"""Where card program packs live.

The public repo carries its own packs under `skill/data/card_program_packs/`.
A private overlay may carry more, and names them through the environment:

    CHRONICLE_PACK_PATHS=<dir>[<pathsep><dir>...]

Every gate that reads *all* packs — the corpus round trip, the event-coverage
run, the token-catalogue scan, the coverage debt — goes through this module,
so one setting changes the data every gate sees and none of the code.

The rule is fail closed, not fail quiet: a directory named here that does not
exist is an error, because a gate that silently ran on fewer packs than the
caller intended would report a clean result about the wrong corpus. Paths must
be absolute for the same reason — a relative one would depend on the cwd the
gate happened to run from, and the off-cwd CI leg exists to catch exactly
that.
"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PUBLIC_PACKS = SKILL_DIR / "data" / "card_program_packs"
ENV = "CHRONICLE_PACK_PATHS"


class PackPathError(ValueError):
    """A pack directory that was named but cannot be used."""


def extra_roots(value: str | None = None) -> list[Path]:
    """The overlay's pack directories, in the order named, validated."""
    raw = os.environ.get(ENV, "") if value is None else value
    roots: list[Path] = []
    for item in raw.split(os.pathsep):
        item = item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            raise PackPathError(f"{ENV} entries must be absolute paths; {item!r} is not")
        if not path.is_dir():
            raise PackPathError(f"{ENV} names {item!r}, which is not a directory")
        if path.resolve() == PUBLIC_PACKS.resolve():
            continue  # the public root is always first; naming it again changes nothing
        if path.resolve() not in [r.resolve() for r in roots]:
            roots.append(path)
    return roots


def pack_roots(value: str | None = None) -> list[Path]:
    """The public root first, then the overlay's, deduplicated."""
    return [PUBLIC_PACKS] + extra_roots(value)


def pack_files(name: str, value: str | None = None) -> list[Path]:
    """Every `<root>/<pack>/<name>` across all roots, sorted within each root
    so the order is stable whatever the filesystem returns."""
    found: list[Path] = []
    for root in pack_roots(value):
        found.extend(sorted(root.glob(f"*/{name}")))
    return found


def describe(value: str | None = None) -> dict[str, object]:
    roots = pack_roots(value)
    return {
        "env": ENV,
        "roots": [str(r) for r in roots],
        "packs": [str(p.parent.name) for p in pack_files("r3a1_programs.json", value)],
        "overlay_active": len(roots) > 1,
    }
