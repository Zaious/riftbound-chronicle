#!/usr/bin/env python3
"""A gate's failure lines, with the details of withheld questions removed.

A deployment can hold some corpus questions back from the people developing against them (a held-out evaluation
set). A gate that fails prints its failures, and a failure about such a question carries its contract - so reading
a red gate would be reading the held-out question.

CHRONICLE_WITHHOLD_IDS says which questions are withheld (comma-separated ids). With it set, a failure that names
one of them is printed as its ids and nothing else, and every other failure prints in full. Set to "none", nothing
is withheld and every failure prints in full - for a deployment that holds nothing back.

Unset (or empty), the gate cannot tell a withheld question from any other, so it withholds them all: a failure is
printed as the question ids it names and nothing else, or as a bare notice when it names none. Running a gate
directly, without the runner that names the withheld set, therefore never prints a question's details.
"""
from __future__ import annotations

import os
import re

ENV = "CHRONICLE_WITHHOLD_IDS"
NOTHING = "none"
_UNSET = f"a failure (details not printed; {ENV} is not set, so every question is withheld)"
_ID = re.compile(r"\bJC-[A-Z]+(?:-[A-Z0-9]+)*-\d+\b|\bJC-[A-Z]+-\d+\b")


def withheld() -> set[str] | None:
    """The withheld ids; None when nobody said which, so every question counts as withheld."""
    raw = os.environ.get(ENV, "").strip()
    if not raw:
        return None
    if raw.lower() == NOTHING:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def shown(failure: str) -> str:
    """The failure as it may be printed: in full, or only the question ids it names."""
    hidden = withheld()
    named = sorted(set(_ID.findall(failure)))
    if hidden is None:
        if named:
            return f"{', '.join(named)}: {_UNSET}"
        return _UNSET
    held = [qid for qid in named if qid in hidden]
    if not held:
        return failure
    return f"{', '.join(held)}: a failure about a withheld question (details not printed; {ENV})"
