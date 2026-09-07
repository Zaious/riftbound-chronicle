#!/usr/bin/env python3
"""Regression gate for DP-90: `split_clauses` reads the text a card prints.

Printed card text is not tidy prose. A sentence ends and the next begins with
no space between them; reminder text sits in brackets in the middle of a card,
not only at the end; an em dash introduces a modal option; `[>]` binds a
keyword to the ability after it; and the snapshot still carries a few HTML
entities. Splitting on whitespace alone produced clauses that were neither the
printed sentence nor anything a grammar could read, and those clauses then sat
in the coverage debt looking like grammar gaps.

Every fixture here is **synthetic or Wave A**: real Wave B card text stays in
the private overlay (Codex's Round H repo-boundary ruling). The shapes are
real; the words are made up.

Must hold:
  - a sentence that runs straight into the next is two clauses, and a decimal
    or an ellipsis is not a sentence break;
  - reminder text is lifted out wherever it sits, so a break never lands
    inside it, and it is attached to the clause it followed — not the one that
    starts where it ends;
  - an em dash before a capital separates clauses, and a leading dash or
    binder is a bullet the clause does not keep;
  - but `[>]` after a keyword **binds** rather than separates: Core 135.2.e.7
    and 808.1.d make "[Deathknell][>] [Effect]" one triggered ability, so the
    keyword and the ability it modifies stay in one clause;
  - HTML entities are decoded before anything is split;
  - keyword blocks still come off the front, in order, with their reminders;
  - a card with no rules text still yields the one empty clause the inventory
    builder turns into its placeholder;
  - splitting is deterministic and never returns a clause that is only
    punctuation or a marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_r3_inventory import split_clauses  # noqa: E402


def texts(result):
    return [c["text"] for c in result if c["text"]]


def reminder_of(result, clause_text):
    return next((c["reminder"] for c in result if c["text"] == clause_text), None)


def main() -> int:
    errors: list[str] = []

    def check(label, text, expected_texts, expected_reminders=None):
        result = split_clauses(text)
        got = texts(result)
        if got != expected_texts:
            errors.append(f"{label}: clauses were {got}, expected {expected_texts}")
            return
        for clause, reminder in (expected_reminders or {}).items():
            actual = reminder_of(result, clause)
            if actual != reminder:
                errors.append(f"{label}: the reminder on {clause!r} was {actual!r}, expected {reminder!r}")

    # --- sentences that run together ------------------------------------------------------
    check("glued sentences",
          "Draw 1.Deal 2 to a widget.",
          ["Draw 1.", "Deal 2 to a widget."])
    check("glued after a bracket",
          "Do the thing. (A note about it.)Then do the other thing.",
          ["Do the thing.", "Then do the other thing."],
          {"Do the thing.": "A note about it."})
    check("spaced sentences still split",
          "Draw 1. Draw 2.",
          ["Draw 1.", "Draw 2."])
    check("a decimal is not a break",
          "Gain 1.5 widgets.",
          ["Gain 1.5 widgets."])
    check("a lowercase continuation is not a break",
          "Gain 1 widget.and then some",
          ["Gain 1 widget.and then some"])

    # --- reminder text, wherever it sits ---------------------------------------------------
    check("a reminder spanning a sentence break stays whole",
          "Do a thing. (Send it home. This is not a move.)Then ready me.",
          ["Do a thing.", "Then ready me."],
          {"Do a thing.": "Send it home. This is not a move."})
    check("a keyword's reminder belongs to the keyword",
          "[Tank] (I am hit first.)Draw 1.",
          ["[Tank]", "Draw 1."],
          {"[Tank]": "I am hit first.", "Draw 1.": ""})
    check("a trailing reminder still attaches to the last clause",
          "Draw 1. (Only once.)",
          ["Draw 1."],
          {"Draw 1.": "Only once."})

    # --- printed separators ---------------------------------------------------------------
    check("an em dash before a capital separates the options",
          "Choose one you have not chosen —Draw 1.Draw 2.",
          ["Choose one you have not chosen", "Draw 1.", "Draw 2."])
    check("a leading em dash is a bullet, not part of the clause",
          "— Draw 1.",
          ["Draw 1."])
    check("an em dash before a cost is not a break",
          "[Empower] — Discard 1",
          ["[Empower]", "Discard 1"])
    # Core 135.2.e.7 / 808.1.d: `[>]` binds, it does not merely separate.
    check("the binder keeps the keyword with the ability it modifies",
          "[Widget 3][>] I have a widget.",
          ["[Widget 3][>] I have a widget."])
    check("the binder takes one sentence, not the rest of the card",
          "[Widget][>] Draw 1.Draw 2.",
          ["[Widget][>] Draw 1.", "Draw 2."])
    check("a bare keyword before a bound one stays bare",
          "[Alpha] (A note.)[Beta 3][>] I have a widget.",
          ["[Alpha]", "[Beta 3][>] I have a widget."],
          {"[Alpha]": "A note."})
    check("a leading label marker is absorbed too",
          "[>] draw 1",
          ["draw 1"])

    # --- entities, keywords, emptiness -----------------------------------------------------
    # The binder only binds if the entity was decoded first, so this asserts
    # both at once.
    check("entities are decoded before splitting",
          "[Widget][&gt;] Draw 1.",
          ["[Widget][>] Draw 1."])
    check("keyword blocks come off the front in order",
          "[Alpha][Beta 2] Draw 1.",
          ["[Alpha]", "[Beta 2]", "Draw 1."])
    if split_clauses("") != [{"text": "", "reminder": ""}]:
        errors.append(f"a card with no rules text did not yield one empty clause: {split_clauses('')}")

    # --- nothing that is only punctuation or a marker ---------------------------------------
    for text in ("—", "[>]", "  —  [>] ", "()", "(a note)"):
        for clause in split_clauses(text):
            if clause["text"] and not any(ch.isalnum() for ch in clause["text"]):
                errors.append(f"{text!r} produced a clause that is only punctuation: {clause['text']!r}")

    # --- determinism -------------------------------------------------------------------------
    sample = "[Tank] (I am hit first.)Draw 1.Deal 2 to a widget. (A note.)"
    if split_clauses(sample) != split_clauses(sample):
        errors.append("splitting is not deterministic")

    if errors:
        print("FAILED: clause splitting checks")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("clause splitting checks passed: glued sentences, mid-text reminders, em dash and [>] separators, "
          "entities, and the empty card")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
