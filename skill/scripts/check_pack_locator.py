#!/usr/bin/env python3
"""Regression gate for the pack search path (`pack_locator.py`).

The public repo's gates read every card program pack through one module, and
a private overlay adds its own packs by naming directories in
`CHRONICLE_PACK_PATHS`. Must hold:

  - with the variable unset, the roots are exactly the public directory and
    the packs are exactly the public packs — the public CI's data is the same
    as before this module existed;
  - naming an overlay directory adds its packs after the public ones, and
    every all-packs reader (the grammar round trip, the event corpus, the
    coverage debt) sees the union — measured by copying the public pack into a
    temporary overlay and watching the counts double;
  - a directory that does not exist, or a relative path, is refused by name
    instead of silently narrowing the corpus;
  - naming the public root again changes nothing, and a root named twice
    counts once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import pack_locator as pl  # noqa: E402


def main() -> int:
    errors: list[str] = []
    public = sorted(p.parent.name for p in pl.PUBLIC_PACKS.glob("*/r3a1_programs.json"))
    if not public:
        errors.append("the public pack directory holds no pack at all")

    # --- unset: exactly the public data ---------------------------------------------------------
    if pl.pack_roots("") != [pl.PUBLIC_PACKS]:
        errors.append(f"with nothing named, the roots are not exactly the public directory: {pl.pack_roots('')}")
    if [p.parent.name for p in pl.pack_files("r3a1_programs.json", "")] != public:
        errors.append("with nothing named, the packs are not exactly the public packs")
    if pl.describe("")["overlay_active"] is not False:
        errors.append("an overlay was reported active with nothing named")

    # --- an overlay doubles the corpus, and every reader sees it ---------------------------------
    with tempfile.TemporaryDirectory(prefix="chronicle-overlay-") as temp:
        overlay = Path(temp) / "packs"
        for pack in pl.PUBLIC_PACKS.iterdir():
            if (pack / "r3a1_programs.json").exists():
                shutil.copytree(pack, overlay / f"overlay-{pack.name}")
        value = str(overlay)
        names = [p.parent.name for p in pl.pack_files("r3a1_programs.json", value)]
        if names != public + [f"overlay-{n}" for n in public]:
            errors.append(f"the overlay's packs did not follow the public ones: {names}")
        if pl.pack_roots(value) != [pl.PUBLIC_PACKS, overlay]:
            errors.append(f"the roots are not public-then-overlay: {pl.pack_roots(value)}")
        # the readers, through the real environment, in a subprocess so the
        # module-level constants they hold are the ones under test
        env = {**os.environ, pl.ENV: value, "PYTHONIOENCODING": "utf-8"}
        probe = ("import sys; sys.path.insert(0, %r); import coverage_debt as cd; d = cd.build(); "
                 "print(d['counts']['clauses_parsed'], d['counts']['clauses_in_debt'])" % str(SCRIPT_DIR))
        with_overlay = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)
        without = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                                 env={k: v for k, v in env.items() if k != pl.ENV})
        try:
            a = [int(x) for x in with_overlay.stdout.split()]
            b = [int(x) for x in without.stdout.split()]
        except ValueError:
            errors.append(f"the coverage debt did not build through the search path: {with_overlay.stderr[-300:]} {without.stderr[-300:]}")
        else:
            if a != [2 * b[0], 2 * b[1]]:
                errors.append(f"the coverage debt did not see the union: with overlay {a}, without {b}")
        twice = pl.pack_roots(os.pathsep.join([value, value, str(pl.PUBLIC_PACKS)]))
        if twice != [pl.PUBLIC_PACKS, overlay]:
            errors.append(f"a root named twice, or the public root named again, was not deduplicated: {twice}")

    # --- fail closed, not fail quiet ---------------------------------------------------------------
    for bad, why in ((str(Path(tempfile.gettempdir()) / "chronicle-no-such-dir-x"), "a directory that does not exist"),
                     ("packs", "a relative path")):
        try:
            pl.pack_roots(bad)
            errors.append(f"{why} was accepted instead of refused")
        except pl.PackPathError:
            pass

    if errors:
        print("FAILED: pack locator checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"pack locator checks passed: public packs {public}, overlay via {pl.ENV} doubles the corpus, bad paths refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
