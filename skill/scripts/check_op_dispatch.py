#!/usr/bin/env python3
"""
Source-level uniqueness gate for the effect IR (Codex Round B, point B).

Must hold:
  - every op in SUPPORTED_OPS has exactly one dispatch branch in
    `_apply_one` (`if/elif op == "x"` or `op in {...}`), and no branch names
    an op outside SUPPORTED_OPS;
  - no top-level `def` or `class` name is defined twice in effect_ir.py,
    resolution_bridge.py, play_transaction.py, or engine_check.py;
  - the same holds off-cwd (the gate reads the files by absolute path).

A patch applied twice once left a dead second copy of three operations; an
`elif` chain hides that silently, so the check is textual.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from effect_ir import SUPPORTED_OPS  # noqa: E402

FILES = ["effect_ir.py", "resolution_bridge.py", "play_transaction.py", "engine_check.py", "engine_decisions.py", "cost_receipt.py"]


def dispatch_branches(source: str) -> Counter:
    start = source.index("def _apply_one(")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    seen: Counter = Counter()
    for match in re.finditer(r'^\s+(?:if|elif) op == "([a-z_]+)":', body, flags=re.M):
        seen[match.group(1)] += 1
    for match in re.finditer(r'^\s+(?:if|elif) op in \{([^}]*)\}:', body, flags=re.M):
        for op in re.findall(r'"([a-z_]+)"', match.group(1)):
            seen[op] += 1
    return seen


def main() -> int:
    errors: list[str] = []
    source = (SCRIPT_DIR / "effect_ir.py").read_text(encoding="utf-8")
    branches = dispatch_branches(source)
    for op in sorted(SUPPORTED_OPS):
        if branches.get(op, 0) != 1:
            errors.append(f"{op}: {branches.get(op, 0)} dispatch branches in _apply_one, expected 1")
    for op, n in branches.items():
        if op not in SUPPORTED_OPS:
            errors.append(f"_apply_one dispatches {op!r}, which is not a supported op")
    for name in FILES:
        text = (SCRIPT_DIR / name).read_text(encoding="utf-8")
        counts = Counter(m.group(2) for m in re.finditer(r"^(def|class) (\w+)", text, flags=re.M))
        for symbol, n in counts.items():
            if n > 1:
                errors.append(f"{name}: {symbol} defined {n} times")
    if errors:
        print("FAILED: op dispatch / symbol uniqueness" + chr(10) + "  - " + (chr(10) + "  - ").join(errors))
        return 1
    print(f"OK: {len(SUPPORTED_OPS)} supported ops each dispatch exactly once in _apply_one; no duplicated top-level symbols across {len(FILES)} engine modules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
