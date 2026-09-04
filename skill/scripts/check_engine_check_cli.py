#!/usr/bin/env python3
"""
Run every engine-check CLI command that references/shared/engine-check.md
documents, against the bundled example inputs, and assert what it produces.

Documented commands rot silently: a reader discovers the breakage, not CI. So
the commands are not restated here -- they are parsed out of the reference
itself. A command added to the doc without an example input fails immediately,
and an example that stops producing its documented outcome fails just as loudly.

Also covers the failure surface, which the API-level checks in
check_engine_check.py cannot reach: a malformed input, a missing file, a missing
required payload, and `validate` on an artifact that overclaims its coverage
must each exit non-zero and write nothing. An engine that exits 0 on garbage
would hand a consumer an artifact that looks like a ruling.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
RUNNER = SCRIPT_DIR / "engine_check.py"
EXAMPLES = SKILL_DIR / "data" / "engine_check_examples"
DOC = SKILL_DIR / "references" / "shared" / "engine-check.md"

# What each documented command must produce. Keyed by the argument signature
# that identifies it, so adding a command to the doc without deciding what it
# should return is itself a failure.
EXPECTED = {
    ("timing", "timing-state.json", "--payload"): "supported",
    ("timing", "timing-state.json", "--operation", "permissions"): "supported",
    ("timing", "timing-state.json", "--operation", "next"): "supported",
    ("effect", "effect-state.json"): "supported",
    ("resolution", "closed-timing-state.json"): "supported",
    ("cleanup", "cleanup-state.json"): "decision_required",
    ("cleanup", "cleanup-state.json", "--cleanup-decisions"): "supported",
    ("play", "play-timing-state.json"): "supported",
}


def documented_commands() -> list[list[str]]:
    """Extract the runner block's commands, joining PowerShell continuations."""
    text = DOC.read_text(encoding="utf-8")
    commands: list[list[str]] = []
    for block in re.findall(r"```powershell\n(.*?)```", text, flags=re.S):
        joined = block.replace("`\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if not line.startswith("python "):
                continue
            tokens = line.split()
            if "engine_check.py" not in tokens[1]:
                continue
            commands.append(tokens[2:])
    return commands


def signature(argv: list[str]) -> tuple[str, ...]:
    """The identifying prefix of a command: subcommand, input, and mode flags."""
    parts = [argv[0]]
    for index, token in enumerate(argv[1:], start=1):
        if token.endswith(".json") and not argv[index - 1].startswith("--output"):
            if len(parts) == 1:
                parts.append(token)
            continue
        if token in ("--payload", "--cleanup-decisions"):
            parts.append(token)
        if token == "--operation":
            parts.extend(("--operation", argv[index + 1]))
    return tuple(parts)


def main() -> int:
    failures: list[str] = []

    if not EXAMPLES.is_dir():
        print(f"FAILED: missing {EXAMPLES.relative_to(SKILL_DIR.parent).as_posix()}")
        return 1

    commands = documented_commands()
    if not commands:
        failures.append("no engine-check CLI commands found in the reference; the doc-driven gate is not actually running anything")

    with tempfile.TemporaryDirectory(prefix="engine-check-cli-") as temp_name:
        temp = Path(temp_name)
        produced: dict[str, Path] = {}

        for argv in commands:
            resolved: list[str] = []
            for index, token in enumerate(argv):
                if not token.endswith(".json"):
                    resolved.append(token)
                    continue
                if index and argv[index - 1] == "--output":
                    resolved.append(str(temp / token))
                    continue
                candidate = EXAMPLES / token
                if candidate.is_file():
                    resolved.append(str(candidate))
                elif token in produced:
                    # `validate` consumes an artifact an earlier command wrote.
                    resolved.append(str(produced[token]))
                else:
                    failures.append(f"documented command references {token!r}, which is neither an example input nor produced by an earlier command")
                    resolved.append(str(EXAMPLES / token))

            run = subprocess.run([sys.executable, str(RUNNER), *resolved], cwd=temp, text=True, capture_output=True, check=False)
            printable = " ".join(argv)
            if run.returncode != 0:
                failures.append(f"documented command failed: {printable}: {run.stderr.strip()}")
                continue

            if argv[0] == "validate":
                continue
            output_index = argv.index("--output") + 1 if "--output" in argv else None
            if output_index is None:
                continue
            path = temp / argv[output_index]
            produced[argv[output_index]] = path
            if not path.is_file():
                failures.append(f"documented command wrote no artifact: {printable}")
                continue
            check = json.loads(path.read_text(encoding="utf-8"))
            key = signature(argv)
            if key not in EXPECTED:
                failures.append(f"documented command {printable} has no expected outcome recorded (signature {key})")
            elif check.get("outcome") != EXPECTED[key]:
                failures.append(f"documented command {printable} produced {check.get('outcome')!r}, expected {EXPECTED[key]!r}")
            if check.get("authority", {}).get("state_effect") != "none":
                failures.append(f"documented command {printable} emitted an artifact claiming a state effect")

        for key in EXPECTED:
            if not any(signature(argv) == key for argv in commands if argv[0] != "validate"):
                failures.append(f"expected command {key} is no longer documented; the example set and the reference have drifted")

        # Epistemic flags must reach the artifact, or a consumer cannot see the
        # boundary the operator declared.
        flagged = temp / "flagged.json"
        run = subprocess.run(
            [sys.executable, str(RUNNER), "effect", str(EXAMPLES / "effect-state.json"), str(EXAMPLES / "effect-program.json"),
             "--assumption", "Deck order is unknown.", "--missing-information", "Opponent hand contents.",
             "--include-raw", "--output", str(flagged)],
            cwd=temp, text=True, capture_output=True, check=False,
        )
        if run.returncode != 0 or not flagged.is_file():
            failures.append(f"flagged effect run failed: {run.stderr.strip()}")
        else:
            check = json.loads(flagged.read_text(encoding="utf-8"))
            if check.get("assumptions") != ["Deck order is unknown."]:
                failures.append("--assumption did not reach the artifact")
            if check.get("missing_information") != ["Opponent hand contents."]:
                failures.append("--missing-information did not reach the artifact")
            if "raw_result" not in check or check["trace_summary"].get("raw_result_included") is not True:
                failures.append("--include-raw did not reach the artifact")

        # Failure surface. Each of these must exit non-zero and write nothing.
        malformed = temp / "malformed.json"
        malformed.write_text("{ not json", encoding="utf-8")
        overclaim_source = json.loads((temp / "cleanup-check.json").read_text(encoding="utf-8")) if (temp / "cleanup-check.json").is_file() else None
        overclaim = temp / "overclaim.json"
        if overclaim_source is not None:
            overclaim_source["coverage"]["complete_game"] = True
            overclaim.write_text(json.dumps(overclaim_source), encoding="utf-8")

        negatives = [
            ("malformed input", ["effect", str(malformed), str(EXAMPLES / "effect-program.json")]),
            ("missing input file", ["effect", str(temp / "does-not-exist.json"), str(EXAMPLES / "effect-program.json")]),
            ("validate-timing without --payload", ["timing", str(EXAMPLES / "timing-state.json")]),
            ("invalid cleanup decisions", ["cleanup", str(EXAMPLES / "cleanup-state.json"), "--cleanup-decisions", str(EXAMPLES / "effect-program.json")]),
        ]
        if overclaim_source is not None:
            negatives.append(("validate a coverage overclaim", ["validate", str(overclaim)]))

        for label, argv in negatives:
            unwanted = temp / "should-not-exist.json"
            run = subprocess.run(
                [sys.executable, str(RUNNER), *argv] + ([] if argv[0] == "validate" else ["--output", str(unwanted)]),
                cwd=temp, text=True, capture_output=True, check=False,
            )
            if run.returncode == 0:
                failures.append(f"{label} exited 0; a bad input must never look like a completed check")
            if unwanted.exists():
                failures.append(f"{label} still wrote an artifact")
                unwanted.unlink()

    print(f"[info] engine-check CLI: {len(commands)} documented commands executed against bundled examples, "
          f"plus flag propagation and {5 if commands else 0} failure cases.")
    if failures:
        print("\n[errors]")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\nFAILED: {len(failures)} engine-check CLI violation(s).")
        return 1
    print("\nOK: every documented engine-check command runs, produces its stated outcome, and fails closed on bad input.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
