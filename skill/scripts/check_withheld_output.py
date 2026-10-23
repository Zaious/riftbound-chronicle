#!/usr/bin/env python3
"""Executable checks: a gate run on its own, with nobody naming the withheld questions, prints no question's details.

withheld_output.shown is how the corpus gates print a failure. These checks use a synthetic question id and a
synthetic contract text (never a real question), and refuse:

  D1 unset       with CHRONICLE_WITHHOLD_IDS unset or empty, a failure prints as the ids it names and nothing else,
                 and a failure naming none prints as a bare notice
  D2 named       with it naming a question, a failure about that question prints as its id alone, and a failure
                 about another question prints in full; "none" prints every failure in full
  D3 direct run  each corpus gate run directly as a process, with the variable removed from its environment and a
                 synthetic failure in place of its first validation, exits non-zero, names the synthetic id and
                 prints none of the synthetic text

    python3 skill/scripts/check_withheld_output.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import withheld_output as W  # noqa: E402

QID = "JC-ZZ-998"
OTHER = "JC-ZZ-997"
DETAIL = "SYNTHETIC-CONTRACT-DETAIL rule_step_order"
FAILURE = f"{QID} runs to differs: the contract requires {DETAIL}"

# Each gate, imported in a fresh process, with its first validation replaced by one that reports FAILURE.
DIRECT = {
    "check_judge_corpus.py":
        "import check_judge_corpus as m; m.validate_corpus = lambda corpus: [FAILURE]; raise SystemExit(m.main())",
    "check_source_semantic_bindings.py":
        "import check_source_semantic_bindings as m; m.ssb.validate_registry = lambda registry: [FAILURE]; "
        "raise SystemExit(m.main())",
}


def _with(value: str | None, failure: str) -> str:
    saved = os.environ.get(W.ENV)
    if value is None:
        os.environ.pop(W.ENV, None)
    else:
        os.environ[W.ENV] = value
    try:
        return W.shown(failure)
    finally:
        if saved is None:
            os.environ.pop(W.ENV, None)
        else:
            os.environ[W.ENV] = saved


def main() -> int:
    errors: list[str] = []
    for value in (None, "", "  "):
        printed = _with(value, FAILURE)
        if DETAIL in printed or not printed.startswith(f"{QID}: "):
            errors.append(f"D1 unset ({value!r}): a failure printed as {printed!r}")
        printed = _with(value, f"a failure naming no question: {DETAIL}")
        if DETAIL in printed:
            errors.append(f"D1 unset ({value!r}): a failure naming no question printed its text")
    printed = _with(QID, FAILURE)
    if printed != f"{QID}: a failure about a withheld question (details not printed; {W.ENV})":
        errors.append(f"D2 named: a failure about the named question printed as {printed!r}")
    if _with(QID, f"{OTHER} {DETAIL}") != f"{OTHER} {DETAIL}":
        errors.append("D2 named: a failure about a question not named was changed")
    if _with("none", FAILURE) != FAILURE:
        errors.append("D2 named: with 'none' a failure was changed")

    env = {key: value for key, value in os.environ.items() if key != W.ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    for gate, code in DIRECT.items():
        out = subprocess.run([sys.executable, "-c", f"FAILURE = {FAILURE!r}\n{code}"], cwd=SCRIPTS, env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        text = out.stdout + out.stderr
        if out.returncode == 0:
            errors.append(f"D3 direct run: {gate} passed with a synthetic failure in place")
        if QID not in text:
            errors.append(f"D3 direct run: {gate} did not name the failing question")
        if DETAIL in text:
            errors.append(f"D3 direct run: {gate} printed the failure's details with {W.ENV} unset")

    if errors:
        print("FAILED: withheld output")
        for error in errors:
            print("  - " + error)
        return 1
    print(f"OK: unset, a failure prints only the ids it names (D1); named, only the named question's details are "
          f"withheld (D2); {len(DIRECT)} corpus gates run directly with {W.ENV} removed print none of a "
          f"synthetic failure's details (D3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
