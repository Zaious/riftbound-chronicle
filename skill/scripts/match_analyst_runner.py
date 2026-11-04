#!/usr/bin/env python3
"""Match Analyst runner.

  trace    replay a recorded game through the engine and write its riftbound-engine-trace.v1
             --record R --catalogue C --overlay-root O --out trace.json
           The recorder's Setup (Core 110-117, its chance receipts) belongs to the recorder, so the start state is
           built by the recorder's own code under --overlay-root (r5p_runner.start, r5p_audit.RecordedChance). The
           trace keeps card names and what happened; it never carries the catalogue.

  analyze  a match log or an engine trace -> match-analysis.v1, match-review.v1, match-commentary.v1
             (--log FILE | --trace FILE) [--perspective P] [--audience A] [--length L] --out-dir DIR
           Prints a short bilingual summary; exits 1 if the three artifacts fail their shape or agreement checks.

  demo     the bilingual demo's data: every fixture under skill/data/match_analyst_fixtures, each from its own
           perspective, plus any --trace given, written as a JavaScript file the no-build page loads from disk
             [--trace FILE --label TEXT]... [--no-fixtures] --out FILE
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import match_analyst as MA  # noqa: E402

FIXTURES = SCRIPT_DIR.parent / "data" / "match_analyst_fixtures"


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def cmd_trace(args) -> int:
    overlay = Path(args.overlay_root).resolve()
    sys.path[:0] = [str(overlay / "scripts")]
    import r5p_audit as AU  # noqa: E402 - the recorder's own Setup
    import r5p_runner as RN  # noqa: E402
    import match_trace as MT  # noqa: E402

    record, catalogue = _load(args.record), _load(args.catalogue)
    t, e, _ = RN.start(catalogue, record["specs"], AU.RecordedChance(record["env_seed"], record["setup"]))
    trace = MT.trace_record(record, catalogue, t, e)
    _write(Path(args.out), trace)
    print(json.dumps({"ok": True, "steps": len(trace["steps"]), "end": (trace.get("end") or {}).get("outcome"),
                      "trace_hash": trace["trace_hash"], "out": str(args.out)}))
    return 0


def _summary(out: dict) -> str:
    a, r, c = out["analysis"], out["review"], out["commentary"]
    counts = ", ".join(f"{k}={v}" for k, v in r["counts"].items() if v) or "none"
    lines = [f"analysis {a['analysis_id']}  perspective={a['perspective']}  events={len(a['timeline'])}  "
             f"withheld={len(a['information_boundary']['withheld'])}  contradictions={len(a['contradictions'])}  "
             f"decisions={len(a['decision_points'])}  turning_points={len(a['turning_points'])}",
             f"review {r['review_id']}  {counts}",
             f"commentary {c['commentary_id']}  segments={len(c['segments'])}",
             "", c["recap"]["zh-Hant"], c["recap"]["en"]]
    if out["problems"]:
        lines += ["", "PROBLEMS:"] + [f"  - {p}" for p in out["problems"]]
    return "\n".join(lines)


def cmd_analyze(args) -> int:
    source = _load(args.log or args.trace)
    out = MA.run(source, perspective=args.perspective, audience=args.audience, length=args.length)
    target = Path(args.out_dir)
    for name in ("analysis", "review", "commentary"):
        _write(target / f"{name}.json", out[name])
    sys.stdout.reconfigure(encoding="utf-8")
    print(_summary(out))
    return 1 if out["problems"] else 0


def bundle_entry(source: dict, label: str, perspective: str | None, length: str) -> dict:
    out = MA.run(source, perspective=perspective, length=length)
    if out["problems"]:
        raise SystemExit(f"{label}: " + "; ".join(out["problems"][:5]))
    a = out["analysis"]
    # the page needs the timeline, not the per-step state hashes of every event
    slim = dict(a)
    slim["timeline"] = [{k: v for k, v in ev.items() if k != "engine"} | (
        {"engine": {k: v for k, v in (ev.get("engine") or {}).items() if k not in ("before", "after")}}
        if ev.get("engine") else {}) | {"text": dict(zip(("zh-Hant", "en"), MA.say(ev)))} for ev in a["timeline"]]
    slim["ledger"] = [f for f in a["ledger"] if f["label"] != "observed"]
    return {"label": label, "analysis": slim, "review": out["review"], "commentary": out["commentary"]}


def cmd_demo(args) -> int:
    entries = []
    for path in [] if args.no_fixtures else sorted(FIXTURES.glob("*.json")):
        log = _load(path)
        entries.append(bundle_entry(log, log.get("title") or path.stem, None, "full"))
    for n, path in enumerate(args.trace or []):
        label = (args.label or [])[n] if n < len(args.label or []) else Path(path).stem
        trace = _load(path)
        for perspective in ("omniscient_replay", "player1"):
            entries.append(bundle_entry(trace, f"{label} · {perspective}", perspective, "standard"))
    var = args.var
    text = (f"// Generated by skill/scripts/match_analyst_runner.py demo. Do not edit by hand.\n"
            f"window.{var} = (window.{var} || []).concat({json.dumps(entries, ensure_ascii=False)});\n")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "entries": len(entries), "bytes": len(text.encode("utf-8")), "out": str(args.out)}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("trace")
    t.add_argument("--record", required=True)
    t.add_argument("--catalogue", required=True)
    t.add_argument("--overlay-root", required=True)
    t.add_argument("--out", required=True)
    a = sub.add_parser("analyze")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--log")
    g.add_argument("--trace")
    a.add_argument("--perspective", choices=MA.PERSPECTIVES)
    a.add_argument("--audience", choices=MA.AUDIENCES, default="player")
    a.add_argument("--length", choices=MA.LENGTHS, default="standard")
    a.add_argument("--out-dir", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--trace", action="append")
    d.add_argument("--label", action="append")
    d.add_argument("--var", default="MATCH_ANALYST_DEMO")
    d.add_argument("--no-fixtures", action="store_true", help="only the --trace games (for local-data.js)")
    d.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"trace": cmd_trace, "analyze": cmd_analyze, "demo": cmd_demo}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
