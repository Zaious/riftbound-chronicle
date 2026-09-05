#!/usr/bin/env python3
"""
Engine capability manifest: what this build of the engine actually supports.

ADR-0002 identifies every executable artifact on four independent axes —
schema major, ruleset baseline, capability set, implementation identity. The
first two already live on every `engine-check.v1`. This module adds the other
two, as a manifest that is *derived from the engine's own declarations* rather
than written by hand:

  - operations   from `effect_ir.SUPPORTED_OPS` and their `OP_RULES` locators;
  - procedures   from `rules_core.SUPPORTED_PROCEDURES` (callable bounded
                 entry points, never the broader RULES topic dictionary);
  - components   from `engine_check.KIND_CONFIG` (coverage ids, supported and
                 unsupported scope per check kind);
  - features     from `engine_check.FEATURE_RULES`, binding cross-operation
                 capabilities to their official locators;
  - clauses      the union of every official locator the above cite;
  - exclusions   the union of every unsupported scope the above declare.

A hand-written manifest would be one more place for capability claims to drift
from code. Deriving it means the manifest can only ever say what the engine
says about itself — and `verify` fails the moment the two disagree.

Two identities come out of that:

  capability_set_id       sha256 over the capability content alone. Two builds
                          that support exactly the same things share it, so a
                          consumer can ask "same capabilities?" without caring
                          which commit produced them.
  implementation_identity sha256 over the engine source files themselves, with
                          line endings normalised so a Windows checkout and a
                          Linux CI runner agree. No git required: this has to
                          work off-cwd, in CI, and from a copied skill directory
                          where there is no repository at all.

Both are carried into `engine-check.v1` as an optional `capability` block. It
is optional because ADR-0002's first row says so: an added field with an
unchanged default keeps the schema major, and every artifact emitted before
this module existed stays valid exactly as written.

Usage:
    python3 skill/scripts/capability_manifest.py build   [--output manifest.json]
    python3 skill/scripts/capability_manifest.py validate manifest.json
    python3 skill/scripts/capability_manifest.py verify   manifest.json

`validate` checks shape. `verify` rebuilds from the live engine and reports
every way the file disagrees with it — a stale implementation hash, an
operation the engine no longer has, one it has gained, a changed locator. Both
exit non-zero on any finding and write nothing.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import effect_ir  # noqa: E402
import rules_core  # noqa: E402
from engine_check import FEATURE_RULES, KIND_CONFIG  # noqa: E402

SCHEMA_VERSION = "engine-capability-manifest.v1"

# The files whose bytes define "this implementation". lethal cleanup lives in
# effect_ir, so four files cover all four check kinds. Order is fixed; the
# identity hash covers the list as well as the contents.
ENGINE_SOURCES = ("rules_core.py", "effect_ir.py", "resolution_bridge.py", "engine_check.py", "combat.py", "battlefield_control.py")

DEFAULT_OUTPUT = SKILL_DIR / "data" / "engine_capability_manifest" / "manifest.json"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _file_sha256(path: Path) -> str:
    # CRLF → LF before hashing. Git may check the same file out either way, and
    # an identity that changes with the checkout's autocrlf setting is not one.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def implementation_identity(script_dir: Path = SCRIPT_DIR) -> dict[str, Any]:
    files = [{"path": name, "sha256": _file_sha256(script_dir / name)} for name in ENGINE_SOURCES]
    return {"kind": "source_sha256", "value": canonical_hash(files), "files": files}


def _locators(*groups: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for group in groups:
        for locator in group:
            seen.setdefault(locator, None)
    return sorted(seen)


def build_manifest(script_dir: Path = SCRIPT_DIR) -> dict[str, Any]:
    missing = sorted(effect_ir.SUPPORTED_OPS - set(effect_ir.OP_RULES))
    if missing:
        # An operation the engine executes but cannot cite is exactly the kind
        # of silent capability this manifest exists to expose. Fail closed.
        raise ValueError(f"supported operations without rule locators: {missing}")

    operations = [{"id": op, "rule_locators": list(effect_ir.OP_RULES[op])} for op in sorted(effect_ir.SUPPORTED_OPS)]
    procedures = [
        {"id": name, "rule_locators": list(locs)}
        for name, locs in sorted(rules_core.SUPPORTED_PROCEDURES.items())
    ]
    components = [
        {
            "check_kind": kind,
            "name": config["component"][0],
            "version": config["component"][1],
            "coverage_id": config["coverage"],
            "supported_scope": list(config["supported"]),
            "unsupported_scope": list(config["unsupported"]),
        }
        for kind, config in sorted(KIND_CONFIG.items())
    ]
    declared_scopes = {scope for component in components for scope in component["supported_scope"]}
    unknown_features = sorted(set(FEATURE_RULES) - declared_scopes)
    if unknown_features:
        raise ValueError(f"feature rules name undeclared supported scopes: {unknown_features}")
    features = [{"id": name, "rule_locators": list(locs)} for name, locs in sorted(FEATURE_RULES.items())]

    capability_content = {
        "ruleset": {"core": rules_core.CORE_RULESET, "faq_as_of": rules_core.FAQ_AS_OF},
        "components": components,
        "operations": operations,
        "procedures": procedures,
        "features": features,
        "clauses": _locators(
            *(op["rule_locators"] for op in operations),
            *(p["rule_locators"] for p in procedures),
            *(feature["rule_locators"] for feature in features),
        ),
        "exclusions": sorted({item for c in components for item in c["unsupported_scope"]}),
        "claims": {"complete_game": False, "complete_legality": False},
    }
    capability_set_id = canonical_hash(capability_content)

    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": f"capability-manifest:{capability_set_id.split(':', 1)[1][:24]}",
        "capability_set_id": capability_set_id,
        "implementation": implementation_identity(script_dir),
        **capability_content,
    }


def validate_manifest(value: Any) -> list[str]:
    """Shape only. Whether it matches the live engine is `verify_manifest`."""
    if not isinstance(value, dict):
        return ["manifest must be an object"]
    required = {
        "schema_version", "manifest_id", "capability_set_id", "implementation", "ruleset",
        "components", "operations", "procedures", "clauses", "exclusions", "claims",
    }
    optional = {"features"}
    errors: list[str] = []
    if set(value) - required - optional or not required.issubset(value):
        errors.append("manifest top-level fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(value.get("manifest_id"), str) or not value["manifest_id"].startswith("capability-manifest:"):
        errors.append("manifest_id is invalid")
    if not _is_hash(value.get("capability_set_id")):
        errors.append("capability_set_id must be a sha256 hash")

    impl = value.get("implementation")
    if not isinstance(impl, dict) or impl.get("kind") != "source_sha256" or not _is_hash(impl.get("value")):
        errors.append("implementation identity is invalid")
    else:
        files = impl.get("files")
        if not isinstance(files, list) or [f.get("path") for f in files if isinstance(f, dict)] != list(ENGINE_SOURCES):
            errors.append("implementation must list exactly the engine source files, in order")
        elif any(not _is_hash(f.get("sha256")) for f in files):
            errors.append("implementation file hashes are invalid")
        elif canonical_hash(files) != impl.get("value"):
            errors.append("implementation value does not hash its file list")

    ruleset = value.get("ruleset")
    if not isinstance(ruleset, dict) or set(ruleset) != {"core", "faq_as_of"} or not all(isinstance(v, str) and v for v in ruleset.values()):
        errors.append("ruleset is invalid")

    for key in ("components", "operations", "procedures", "features"):
        items = value.get(key)
        if key == "features" and items is None:
            continue
        if not isinstance(items, list) or not items:
            errors.append(f"{key} must be a non-empty array")
            continue
        ids = [item.get("id") if key != "components" else item.get("check_kind") for item in items if isinstance(item, dict)]
        if len(ids) != len(items) or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
            errors.append(f"{key} entries must have unique non-empty ids")
        if key == "components":
            for item in items:
                if not isinstance(item, dict) or set(item) != {"check_kind", "name", "version", "coverage_id", "supported_scope", "unsupported_scope"}:
                    errors.append("component entry fields are invalid")
                    break
                if not _string_list(item.get("supported_scope")) or not _string_list(item.get("unsupported_scope")):
                    errors.append("component scopes must be string arrays")
                    break
        else:
            for item in items:
                if not isinstance(item, dict) or set(item) != {"id", "rule_locators"} or not _string_list(item.get("rule_locators")) or not item["rule_locators"]:
                    errors.append(f"{key} entries must carry non-empty rule_locators")
                    break

    for key in ("clauses", "exclusions"):
        if not _string_list(value.get(key)) or value.get(key) != sorted(set(value.get(key, []))):
            errors.append(f"{key} must be a sorted, unique string array")

    if value.get("claims") != {"complete_game": False, "complete_legality": False}:
        errors.append("claims must reject complete-game and complete-legality")

    if not errors:
        content_keys = ["ruleset", "components", "operations", "procedures"]
        if "features" in value:
            content_keys.append("features")
        content_keys += ["clauses", "exclusions", "claims"]
        content = {k: value[k] for k in content_keys}
        if canonical_hash(content) != value["capability_set_id"]:
            errors.append("capability_set_id does not hash the capability content")
        if not value["manifest_id"].endswith(value["capability_set_id"].split(":", 1)[1][:24]):
            errors.append("manifest_id does not derive from capability_set_id")
    return errors


def verify_manifest(value: dict[str, Any], script_dir: Path = SCRIPT_DIR) -> list[str]:
    """Every way the file disagrees with the engine as it is right now."""
    errors = validate_manifest(value)
    if errors:
        return errors
    live = build_manifest(script_dir)
    findings: list[str] = []
    if value["implementation"]["value"] != live["implementation"]["value"]:
        changed = [
            f["path"] for f, g in zip(value["implementation"]["files"], live["implementation"]["files"])
            if f["sha256"] != g["sha256"]
        ]
        findings.append(f"stale implementation identity; changed sources: {changed}")
    if value["capability_set_id"] != live["capability_set_id"]:
        for key in ("operations", "procedures", "features"):
            if key not in value:
                findings.append("features: manifest predates cited feature capabilities")
                continue
            have = {item["id"]: item["rule_locators"] for item in value[key]}
            want = {item["id"]: item["rule_locators"] for item in live[key]}
            for gained in sorted(set(want) - set(have)):
                findings.append(f"{key}: engine supports {gained!r} but the manifest does not list it")
            for lost in sorted(set(have) - set(want)):
                findings.append(f"{key}: manifest claims {lost!r} but the engine does not support it")
            for same in sorted(set(have) & set(want)):
                if have[same] != want[same]:
                    findings.append(f"{key}: {same!r} locators differ from the engine")
        for key in ("components", "clauses", "exclusions", "ruleset", "claims"):
            if value[key] != live[key]:
                findings.append(f"{key} differ from the engine")
        if not findings:
            findings.append("capability_set_id differs from the engine for an unlisted reason")
    return findings


def capability_binding(manifest: dict[str, Any]) -> dict[str, str]:
    """The three identifiers an engine-check carries to say which build produced it."""
    return {
        "manifest_id": manifest["manifest_id"],
        "capability_set_id": manifest["capability_set_id"],
        "implementation_identity": manifest["implementation"]["value"],
    }


def binding_matches(check: dict[str, Any], manifest: dict[str, Any]) -> bool:
    """True only when the check names this exact manifest — same capabilities and same build."""
    bound = check.get("capability")
    return isinstance(bound, dict) and bound == capability_binding(manifest)


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == len("sha256:") + 64


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read manifest {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit(f"manifest {path} is not an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="derive the manifest from the live engine")
    build.add_argument("--output", type=Path, default=None, help=f"write here (default: {DEFAULT_OUTPUT})")
    build.add_argument("--stdout", action="store_true", help="print instead of writing")
    for name in ("validate", "verify"):
        p = sub.add_parser(name)
        p.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        manifest = build_manifest()
        errors = validate_manifest(manifest)
        if errors:
            print("FAILED: built manifest is invalid: " + "; ".join(errors), file=sys.stderr)
            return 1
        text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        if args.stdout:
            sys.stdout.write(text)
            return 0
        target = args.output or DEFAULT_OUTPUT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target} ({manifest['manifest_id']})")
        return 0

    value = _load(args.manifest)
    findings = validate_manifest(value) if args.command == "validate" else verify_manifest(value)
    if findings:
        print(f"FAILED: {args.command} {args.manifest}:\n  - " + "\n  - ".join(findings), file=sys.stderr)
        return 1
    print(f"OK: {args.command} {args.manifest} ({value['manifest_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
