#!/usr/bin/env python3
"""Run the Deck Coach closed loop: profile, mask, primer, evaluation, battle.

The profiler and mask are deterministic and dependency-free. The generated
primer is an evidence-labelled baseline, not a substitute for expert or model
reasoning. A richer candidate primer can be evaluated or battled through the
same contracts without changing the factual observation layer.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SKILL_DIR = Path(__file__).resolve().parent.parent
CARDS_PATH = SKILL_DIR / "data" / "riftcodex_cards_raw.json"
ERRATA_PATH = SKILL_DIR / "data" / "errata_overlay.json"
ENVIRONMENTS_PATH = SKILL_DIR / "data" / "deck_coach_environments.json"
ROLES_PATH = SKILL_DIR / "data" / "deck_coach_roles.json"
CASES_PATH = SKILL_DIR / "data" / "deck_coach_cases.json"
PRIMER_SECTIONS = (
    "identity", "core_loop", "mulligan_targets", "turn_priorities",
    "fight_or_hold", "common_lines", "common_mistakes", "evidence_ledger",
)
UNCERTAINTY_MARKERS = (
    "no verified", "not verified", "unknown", "not established", "requires a live check",
    "hypothesis", "cannot determine", "needs expert", "insufficient",
)
VARIANT_SUFFIX = re.compile(r"\s+\((?:alternate art|metal|overnumbered|signature)\)$", re.I)


class PipelineError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load JSON {path}: {exc}") from exc


def save_json(path: Path, value: Any) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def clean_name(name: str) -> str:
    return VARIANT_SUFFIX.sub("", name.strip())


def name_key(name: str) -> str:
    value = clean_name(name).casefold().replace("’", "'")
    value = re.sub(r"\s*[,–—]\s*", " - ", value)
    return re.sub(r"\s+", " ", value).strip()


def text_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


class CardCatalog:
    def __init__(self):
        self.cards = load_json(CARDS_PATH)
        self.errata = load_json(ERRATA_PATH)
        self.environments = load_json(ENVIRONMENTS_PATH)
        self.roles = load_json(ROLES_PATH)
        self.by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for card in self.cards:
            self.by_name[name_key(card["name"])].append(card)
        self.errata_by_name = {name_key(item["official_name"]): item for item in self.errata["entries"]}

    def resolve_all(self, name: str) -> list[dict[str, Any]]:
        return self.by_name.get(name_key(name), [])

    def resolve(self, name: str, legal_sets: set[str] | None = None) -> dict[str, Any] | None:
        rows = self.resolve_all(name)
        if not rows:
            return None
        def rank(card):
            set_id = card.get("set", {}).get("set_id")
            legal_rank = 0 if legal_sets and set_id in legal_sets else 1
            variant_rank = 1 if VARIANT_SUFFIX.search(card.get("name", "")) else 0
            promo_rank = 1 if set_id in {"OPP", "PR", "JDG"} else 0
            return (legal_rank, variant_rank, promo_rank, card.get("collector_number") or 0)
        return sorted(rows, key=rank)[0]

    def current_text(self, card: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        item = self.errata_by_name.get(name_key(card["name"]))
        if item:
            return item["new_text"], item
        return card.get("text", {}).get("plain") or "", None

    def environment(self, environment_id: str, format_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        environment = self.environments.get("environments", {}).get(environment_id)
        format_config = self.environments.get("formats", {}).get(format_name)
        if not environment:
            raise PipelineError(f"unknown environment {environment_id!r}")
        if not format_config:
            raise PipelineError(f"unknown format {format_name!r}")
        return environment, format_config


def normalize_input(value: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    defaults = {
        "chosen_champion": None, "runes": {}, "battlefields": [], "sideboard": [],
        "owned_cards": None, "source_environment": None, "recommendation_candidates": [],
    }
    for field, default in defaults.items():
        normalized.setdefault(field, default)
    return normalized


def validate_input(value: Any, catalog: CardCatalog | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["input must be an object"]
    required = {"schema_version", "deck_id", "environment", "format", "player_level", "legend", "main_deck"}
    allowed = required | {"chosen_champion", "runes", "battlefields", "sideboard", "owned_cards", "source_environment", "recommendation_candidates"}
    if missing := required - set(value):
        errors.append(f"missing fields: {sorted(missing)}")
    if unknown := set(value) - allowed:
        errors.append(f"unknown fields: {sorted(unknown)}")
    if value.get("schema_version") != "deck-coach-input.v1":
        errors.append("schema_version must be deck-coach-input.v1")
    if value.get("player_level") not in {"new", "intermediate", "advanced"}:
        errors.append("player_level must be new, intermediate, or advanced")
    for field in ("deck_id", "environment", "format", "legend"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            errors.append(f"{field} must be non-empty")
    for field in ("main_deck", "sideboard"):
        entries = value.get(field)
        if not isinstance(entries, list):
            errors.append(f"{field} must be an array")
            continue
        for index, item in enumerate(entries):
            if not isinstance(item, dict) or set(item) != {"name", "count"}:
                errors.append(f"{field}[{index}] must contain exactly name and count")
            elif not isinstance(item["count"], int) or isinstance(item["count"], bool) or item["count"] < 1:
                errors.append(f"{field}[{index}].count must be a positive integer")
    if catalog:
        try:
            catalog.environment(value.get("environment"), value.get("format"))
        except PipelineError as exc:
            errors.append(str(exc))
    return errors


def case_input(value: dict[str, Any]) -> dict[str, Any]:
    return value["input"] if "input" in value else value


def detect_features(card_type: str, text: str, energy: int | None, might: int | None) -> tuple[set[str], set[str]]:
    lower = text.casefold()
    features: set[str] = set()
    roles: set[str] = set()
    if re.search(r"\bdraw\b|look at the top|reveal the top", lower):
        features.add("draw_selection"); roles.add("resource_economy")
    if re.search(r"\btrash\b|\brecycle\b|\bflow\b|play .* from (?:your )?trash", lower):
        features.add("recursion"); roles.add("resource_economy")
    if re.search(r"\bmove\b|\bganking\b|location", lower):
        features.add("movement"); roles.add("mobility")
    if re.search(r"\bkill\b|deal \d|\bbanish an enemy|return .*enemy|enemy unit", lower):
        features.add("interaction"); roles.add("showdown_interaction")
    if re.search(r"\[action\]|\breaction\b|showdown|give .*\+|assault", lower):
        features.add("showdown_access"); roles.add("showdown_interaction")
    if re.search(r"\bheal\b|can't be chosen|cannot be chosen|would die|recall .* instead|prevent", lower):
        features.add("protection"); roles.add("protection")
    if re.search(r"ready .*rune|ignoring (?:its|their) cost|reducing .*cost|additional rune", lower):
        features.add("resource_acceleration"); roles.add("resource_economy")
    if card_type == "Unit" or re.search(r"play (?:a|two|three|an) .*unit|unit token|buff a friendly unit", lower):
        roles.add("battlefield_presence")
    if re.search(r"when you play|the first time|each time|whenever|when i conquer", lower):
        roles.add("core_engine")
    if (isinstance(energy, int) and energy >= 6) or (isinstance(might, int) and might >= 6) or re.search(r"score .*point|extra point", lower):
        roles.add("closer")
    return features, roles


def _distribution(counter: Counter[str], total: int) -> dict[str, Any]:
    return {
        key: {"count": count, "share": round(count / total, 4) if total else 0.0}
        for key, count in sorted(counter.items())
    }


def build_profile(deck_input: dict[str, Any], catalog: CardCatalog | None = None) -> dict[str, Any]:
    catalog = catalog or CardCatalog()
    errors = validate_input(deck_input, catalog)
    if errors:
        raise PipelineError("invalid input:\n- " + "\n- ".join(errors))
    deck_input = normalize_input(deck_input)
    env, _ = catalog.environment(deck_input["environment"], deck_input["format"])
    legal_sets = set(env["legal_set_ids"])
    entries = list(deck_input["main_deck"])
    total_copies = sum(item["count"] for item in entries)
    known_copies = 0
    curve = Counter()
    domains = Counter()
    powers = Counter()
    types = Counter()
    features = Counter()
    roles = Counter()
    resolved, unknown = [], []
    engine_scored = []

    legend_card = catalog.resolve(deck_input["legend"], legal_sets)
    legend_domains = [d for d in (legend_card or {}).get("classification", {}).get("domain", []) if d != "Colorless"]
    legend_text, _ = catalog.current_text(legend_card) if legend_card else ("", None)
    legend_terms = set(re.findall(r"\b[a-z]{4,}\b", legend_text.casefold())) - {"when", "your", "this", "that", "with", "from", "then", "play"}

    for item in entries:
        card = catalog.resolve(item["name"], legal_sets)
        if not card:
            unknown.append({"name": item["name"], "count": item["count"], "reason": "not_found_in_snapshot"})
            continue
        known_copies += item["count"]
        current_text, errata = catalog.current_text(card)
        attrs, classification = card.get("attributes", {}), card.get("classification", {})
        energy, power, might = attrs.get("energy"), attrs.get("power"), attrs.get("might")
        card_type = classification.get("type") or "Unknown"
        card_features, card_roles = detect_features(card_type, current_text, energy, might)
        bucket = "unknown" if energy is None else ("7+" if energy >= 7 else str(energy))
        curve[bucket] += item["count"]
        types[card_type] += item["count"]
        for domain in classification.get("domain") or []:
            domains[domain] += item["count"]
        if power is not None:
            powers[str(power)] += item["count"]
        for feature in card_features:
            features[feature] += item["count"]
        for role in card_roles:
            roles[role] += item["count"]
        terms = set(re.findall(r"\b[a-z]{4,}\b", current_text.casefold()))
        overlap = sorted(legend_terms & terms)
        score = item["count"] + min(3, len(overlap)) + (2 if "core_engine" in card_roles else 0)
        reasons = []
        if item["count"] >= 3:
            reasons.append("three-copy commitment")
        if overlap:
            reasons.append("shares Legend-text terms: " + ", ".join(overlap[:4]))
        if "core_engine" in card_roles:
            reasons.append("repeat-trigger text matched the engine heuristic")
        if reasons:
            engine_scored.append({"name": clean_name(card["name"]), "count": item["count"], "score": score, "reasons": reasons, "confidence": "heuristic"})
        resolved.append({
            "input_name": item["name"], "canonical_name": clean_name(card["name"]), "count": item["count"],
            "set_id": card.get("set", {}).get("set_id"), "type": card_type, "domains": classification.get("domain") or [],
            "energy": energy, "power": power, "might": might, "features": sorted(card_features), "roles": sorted(card_roles),
            "errata_applied": bool(errata),
        })

    battlefields = []
    for name in deck_input["battlefields"]:
        card = catalog.resolve(name, legal_sets)
        battlefields.append({
            "input_name": name,
            "canonical_name": clean_name(card["name"]) if card else None,
            "resolved": bool(card),
            "set_id": card.get("set", {}).get("set_id") if card else None,
        })

    structural_anchors = list(dict.fromkeys([
        deck_input["legend"],
        *([deck_input["chosen_champion"]] if deck_input.get("chosen_champion") else []),
    ]))
    engine_scored.sort(key=lambda item: (-item["score"], item["name"]))
    coverage = known_copies / total_copies if total_copies else 0.0
    warnings = []
    if unknown:
        warnings.append("Some deck entries were not found in the bundled snapshot.")
    if not legend_card:
        warnings.append("Legend was not resolved; Domain identity cannot be established.")
    if coverage == 1 and legend_card:
        overall = "High"
    elif coverage >= 0.9:
        overall = "Medium"
    else:
        overall = "Low"
    role_result = {role["role_id"]: {"copies": roles.get(role["role_id"], 0), "method": "text heuristic"} for role in catalog.roles["roles"]}
    return {
        "schema_version": "deck-profile.v1",
        "deck_id": deck_input["deck_id"],
        "generated_at": now_iso(),
        "context": {
            "legend": deck_input["legend"], "chosen_champion": deck_input["chosen_champion"],
            "format": deck_input["format"], "environment": deck_input["environment"],
            "region": env["region"], "set_pool": env["legal_set_ids"], "player_level": deck_input["player_level"],
            "legend_domains": legend_domains, "runes": deck_input["runes"],
        },
        "data_provenance": {
            "card_snapshot": "riftcodex_cards_raw.json", "card_snapshot_rows": len(catalog.cards),
            "errata_last_verified": catalog.errata["last_verified"],
            "environment_registry_last_checked": catalog.environments["last_checked"],
            "official_legality_source": catalog.environments["official_legality_source"],
        },
        "resolution": {"total_main_deck_copies": total_copies, "known_copies": known_copies, "resolved_entries": resolved, "unknown_entries": unknown},
        "curve": {"buckets": _distribution(curve, known_copies), "average_known_energy": round(sum((r["energy"] or 0) * r["count"] for r in resolved if r["energy"] is not None) / max(1, sum(r["count"] for r in resolved if r["energy"] is not None)), 3)},
        "domain_requirements": {"printed_domain_copies": dict(sorted(domains.items())), "power_cost_copies": dict(sorted(powers.items())), "legend_domains": legend_domains},
        "type_distribution": _distribution(types, known_copies),
        "battlefield_package": battlefields,
        "feature_density": {name: {"copies": count, "density": round(count / known_copies, 4) if known_copies else 0.0, "method": "text heuristic"} for name, count in sorted(features.items())},
        "role_distribution": role_result,
        "engine_cards": {"structural_anchors": structural_anchors, "inferred_candidates": engine_scored[:12], "inference_is_authoritative": False},
        "confidence": {"overall": overall, "card_resolution_coverage": round(coverage, 4), "role_method": "heuristic", "warnings": warnings},
    }


def _ban_keys(format_config: dict[str, Any]) -> set[str]:
    return {name_key(name) for name in format_config["banned_names"]}


def _card_mask_reasons(
    name: str,
    catalog: CardCatalog,
    legal_sets: set[str],
    banned: set[str],
    legend_domains: set[str],
    owned: dict[str, int] | None = None,
    requested_count: int = 1,
    source_environment: str | None = None,
    target_environment: str | None = None,
    cited_text: str | None = None,
) -> tuple[list[str], dict[str, Any] | None, dict[str, Any] | None]:
    rows = catalog.resolve_all(name)
    if not rows:
        return ["unknown_card"], None, None
    card = catalog.resolve(name, legal_sets)
    reasons = []
    if not any(row.get("set", {}).get("set_id") in legal_sets for row in rows):
        reasons.append("not_released_in_environment")
    if name_key(name) in banned or name_key(card["name"]) in banned:
        reasons.append("banned_in_format")
    domains = set(card.get("classification", {}).get("domain") or []) - {"Colorless"}
    if legend_domains and not domains.issubset(legend_domains):
        reasons.append("outside_legend_domain_identity")
    if owned is not None:
        owned_by_key = {name_key(owned_name): count for owned_name, count in owned.items()}
        available = owned_by_key.get(name_key(name), owned_by_key.get(name_key(card["name"]), 0))
        if available < requested_count:
            reasons.append("not_enough_owned_copies")
    if source_environment and target_environment and source_environment != target_environment:
        reasons.append("source_environment_mismatch")
    _, errata = catalog.current_text(card)
    if cited_text and errata and text_key(errata["old_text"]) in text_key(cited_text):
        reasons.append("stale_pre_errata_text")
    return reasons, card, errata


def build_mask(deck_input: dict[str, Any], profile: dict[str, Any] | None = None, catalog: CardCatalog | None = None) -> dict[str, Any]:
    catalog = catalog or CardCatalog()
    deck_input = normalize_input(deck_input)
    profile = profile or build_profile(deck_input, catalog)
    env, format_config = catalog.environment(deck_input["environment"], deck_input["format"])
    legal_sets, banned = set(env["legal_set_ids"]), _ban_keys(format_config)
    legend_domains = set(profile["context"]["legend_domains"])
    owned = deck_input["owned_cards"]

    deck_checks = []
    deck_items = (
        [(deck_input["legend"], 1, "legend")]
        + ([(deck_input["chosen_champion"], 1, "chosen_champion")] if deck_input.get("chosen_champion") else [])
        + [(item["name"], item["count"], "main_deck") for item in deck_input["main_deck"]]
        + [(name, 1, "battlefield") for name in deck_input["battlefields"]]
        + [(item["name"], item["count"], "sideboard") for item in deck_input["sideboard"]]
    )
    for name, count, zone in deck_items:
        reasons, card, errata = _card_mask_reasons(name, catalog, legal_sets, banned, legend_domains)
        deck_checks.append({"name": name, "zone": zone, "count": count, "allowed": not reasons, "reasons": reasons, "resolved_name": clean_name(card["name"]) if card else None, "errata_applied": bool(errata)})

    candidate_results = []
    for candidate in deck_input["recommendation_candidates"]:
        reasons, card, errata = _card_mask_reasons(
            candidate["name"], catalog, legal_sets, banned, legend_domains, owned,
            candidate["requested_count"], candidate["source_environment"], deck_input["environment"], candidate["cited_text"],
        )
        candidate_results.append({
            "name": candidate["name"], "requested_count": candidate["requested_count"], "allowed": not reasons,
            "reasons": reasons, "resolved_name": clean_name(card["name"]) if card else None,
            "errata_applied": bool(errata), "source_environment": candidate["source_environment"],
        })

    unique_names: dict[str, dict[str, Any]] = {}
    for card in catalog.cards:
        key = name_key(card["name"])
        if key not in unique_names or card.get("set", {}).get("set_id") in legal_sets:
            unique_names[key] = card
    eligible_names, by_role = [], defaultdict(list)
    for card in unique_names.values():
        name = clean_name(card["name"])
        reasons, selected, _ = _card_mask_reasons(name, catalog, legal_sets, banned, legend_domains, owned)
        if reasons or not selected or selected.get("classification", {}).get("type") in {"Rune", "Legend"}:
            continue
        eligible_names.append(name)
        current_text, _ = catalog.current_text(selected)
        _, card_roles = detect_features(selected.get("classification", {}).get("type") or "Unknown", current_text, selected.get("attributes", {}).get("energy"), selected.get("attributes", {}).get("might"))
        for role in card_roles:
            by_role[role].append(name)
    eligible_names = sorted(set(eligible_names))
    stale_date = env.get("stale_on_or_after")
    today = dt.date.today().isoformat()
    registry_stale = bool(stale_date and today >= stale_date)
    blocked = [item for item in deck_checks if not item["allowed"]]
    source_environment = deck_input.get("source_environment")
    source_reasons = ["source_environment_mismatch"] if source_environment and source_environment != deck_input["environment"] else []
    source_check = {"source_environment": source_environment, "target_environment": deck_input["environment"], "allowed": not source_reasons, "reasons": source_reasons}
    return {
        "schema_version": "recommendation-mask.v1",
        "deck_id": deck_input["deck_id"],
        "generated_at": now_iso(),
        "environment": deck_input["environment"],
        "format": deck_input["format"],
        "legend_domains": sorted(legend_domains),
        "deck_legality": {"status": "blocked" if blocked or source_reasons else "provisionally_clear", "checks": deck_checks, "blocked_count": len(blocked), "source_environment_check": source_check},
        "candidate_results": candidate_results,
        "eligible_pool": {"count": len(eligible_names), "names": eligible_names, "by_role": {role: sorted(set(names)) for role, names in sorted(by_role.items())}},
        "live_check": {
            "required_for_real_event": True,
            "registry_last_checked": catalog.environments["last_checked"],
            "ban_list_last_updated": catalog.environments["ban_list_last_updated"],
            "source": catalog.environments["official_legality_source"],
            "registry_stale": registry_stale,
            "status": "needs_live_check" if registry_stale else "provisional_only",
            "note": "The mask is a recommendation filter, not an official deck registration ruling.",
        },
    }


def generate_baseline_primer(deck_input: dict[str, Any], profile: dict[str, Any], mask: dict[str, Any], candidate_id: str, skill_version: str, model: str) -> dict[str, Any]:
    deck_input = normalize_input(deck_input)
    known = profile["resolution"]["known_copies"]
    units = profile["type_distribution"].get("Unit", {"count": 0, "share": 0})
    low_cards = [entry["canonical_name"] for entry in profile["resolution"]["resolved_entries"] if entry["energy"] is not None and entry["energy"] <= 2]
    anchors = profile["engine_cards"]["structural_anchors"]
    inferred = [item["name"] for item in profile["engine_cards"]["inferred_candidates"][:4]]
    blocked = mask["deck_legality"]["blocked_count"]
    feature = profile["feature_density"]
    interaction = feature.get("interaction", {"density": 0})["density"] + feature.get("showdown_access", {"density": 0})["density"]
    identity = (
        f"Tier 1 profile: {deck_input['legend']} in {deck_input['environment']} uses "
        f"{', '.join(profile['context']['legend_domains']) or 'unresolved Domains'}; the known main deck is "
        f"{units['count']}/{known} units ({units['share']:.0%}). Player level: {deck_input['player_level']}. "
        "A strategic archetype label still needs card-text/real-play interpretation."
    )
    core_loop = (
        "Tier 1 structural anchors: " + (", ".join(anchors) if anchors else "none resolved") + ". "
        "Tier 3 heuristic candidates: " + (", ".join(inferred) if inferred else "none resolved") + ". "
        "The heuristic is a review queue, not proof that every listed card is a true engine piece."
    )
    mulligan = (
        "Tier 3 hypothesis: begin testing hands containing an early action from "
        + (", ".join(dict.fromkeys(low_cards[:8])) if low_cards else "the unresolved low-cost package")
        + ". No verified keep/ship rule is established by the structural profile alone."
    )
    priorities = (
        f"Tier 3 teaching scaffold for a {deck_input['player_level']} player: first establish the declared engine, "
        "then spend cards only when they advance the deck's stated loop, and preserve the closer. "
        "Exact turn sequencing needs a researched primer or expert candidate."
    )
    fight = (
        f"Tier 1 profile observation: interaction/showdown feature density is approximately {interaction:.0%} across known copies. "
        "Tier 3: fight when those pieces change a scoring contest; hold when committing them does not. "
        "No matchup-specific verdict is inferred."
    )
    common_lines = (
        "Tier 3 abstention: no verified card-by-card sequence was supplied to the deterministic profiler. "
        "Use the declared engine cards as research anchors and require an Agent or expert to cite each proposed line."
    )
    mistakes = (
        "Tier 3 review prompts: keeping too few units or low-cost actions for a unit-driven plan, treating heuristic engine candidates as proven, "
        f"and ignoring {blocked} blocked deck entry or entries from the recommendation mask. Do not turn these prompts into factual matchup claims without evidence."
    )
    evidence = (
        f"Tier 1: bundled card snapshot ({profile['data_provenance']['card_snapshot_rows']} rows), errata verified "
        f"{profile['data_provenance']['errata_last_verified']}, card-resolution coverage {profile['confidence']['card_resolution_coverage']:.0%}. "
        f"Tier 1 provisional legality: environment registry checked {profile['data_provenance']['environment_registry_last_checked']}; live event use still requires the official Rules Hub check. "
        "Tier 3: role, engine, mulligan, sequencing, and mistake inferences unless a separate cited source upgrades them."
    )
    return {
        "schema_version": "deck-coach-candidate.v1",
        "candidate_id": candidate_id,
        "metadata": {"skill_version": skill_version, "model": model, "generator": "deterministic-profile-baseline", "generated_at": now_iso()},
        "primer": dict(zip(PRIMER_SECTIONS, (identity, core_loop, mulligan, priorities, fight, common_lines, mistakes, evidence))),
    }


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    hay = text_key(text)
    return any(text_key(needle) in hay for needle in needles)


def _fraction(items: list[str], predicate) -> float:
    return sum(1 for item in items if predicate(item)) / len(items) if items else 1.0


def evaluate_candidate(case: dict[str, Any], candidate: dict[str, Any], profile: dict[str, Any], mask: dict[str, Any], human_scores: dict[str, float] | None = None) -> dict[str, Any]:
    expected = case["expected"]
    primer = candidate.get("primer", {})
    combined = "\n".join(str(primer.get(key, "")) for key in PRIMER_SECTIONS)
    failures, warnings = [], []
    forbidden_hits = [claim for claim in expected["forbidden_claims"] if _contains_any(combined, [claim])]
    unknown_count = len(profile["resolution"]["unknown_entries"])
    fact_score = 1.0 if not forbidden_hits and unknown_count == 0 else max(0.0, 1 - 0.25 * len(forbidden_hits) - 0.1 * unknown_count)
    expected_reasons = set(expected["expected_mask_reasons"])
    observed_reasons = {reason for item in mask["deck_legality"]["checks"] + mask["candidate_results"] for reason in item["reasons"]}
    observed_reasons.update(mask["deck_legality"]["source_environment_check"]["reasons"])
    legality_score = _fraction(sorted(expected_reasons), lambda reason: reason in observed_reasons)
    if not expected_reasons:
        legality_score = 1.0 if mask["deck_legality"]["blocked_count"] == expected["expected_blocked_deck_entries"] else 0.0
    identity_score = _fraction(expected["identity_tokens"], lambda token: _contains_any(primer.get("identity", ""), [token]))
    engine_score = _fraction(expected["must_identify_engine"], lambda token: _contains_any(primer.get("core_loop", "") + "\n" + primer.get("identity", ""), [token]))
    weakness_score = _fraction(expected["must_mention_weakness"], lambda token: _contains_any(primer.get("common_mistakes", "") + "\n" + primer.get("fight_or_hold", ""), [token]))
    filled = [key for key in PRIMER_SECTIONS if isinstance(primer.get(key), str) and len(primer[key].strip()) >= 35]
    actionable_score = round((len(filled) / len(PRIMER_SECTIONS) + weakness_score) / 2, 4)
    tiered = [key for key in PRIMER_SECTIONS if re.search(r"\bTier [123]\b", primer.get(key, ""))]
    evidence_score = len(tiered) / len(PRIMER_SECTIONS)
    uncertainty_expected = expected["acceptable_uncertainty"]
    abstention_score = _fraction(uncertainty_expected, lambda topic: _contains_any(combined, [topic]) and _contains_any(combined, UNCERTAINTY_MARKERS))
    if forbidden_hits:
        failures.append("forbidden claims present: " + ", ".join(forbidden_hits))
    if unknown_count:
        warnings.append(f"profile contains {unknown_count} unresolved deck entrie(s)")
    if mask["live_check"]["status"] != "provisional_only":
        warnings.append("environment registry requires a fresh live check")
    dimensions = {
        "card_and_rule_factual_accuracy": round(fact_score, 4),
        "format_and_region_legality": round(legality_score, 4),
        "deck_identity": round(identity_score, 4),
        "core_loop_identification": round(engine_score, 4),
        "recommendation_actionability": round(actionable_score, 4),
        "evidence_and_confidence": round(evidence_score, 4),
        "abstention_correctness": round(abstention_score, 4),
    }
    grader = "deterministic-proxy"
    if human_scores:
        invalid = set(human_scores) - set(dimensions)
        if invalid:
            raise PipelineError(f"unknown human score dimensions: {sorted(invalid)}")
        for key, score in human_scores.items():
            if not isinstance(score, (int, float)) or not 0 <= score <= 1:
                raise PipelineError(f"human score {key} must be between 0 and 1")
            dimensions[key] = round(float(score), 4)
        grader = "hybrid"
    score = round(sum(dimensions.values()) / len(dimensions), 4)
    metrics = {
        "factual_pass_rate": round(fact_score, 4),
        "unsupported_claim_rate": round(1 - evidence_score, 4),
        "evidence_coverage": round(evidence_score, 4),
        "abstention_correctness": round(abstention_score, 4),
        "deck_identity_agreement": round(identity_score, 4),
        "engine_identification": round(engine_score, 4),
        "forbidden_claim_hits": forbidden_hits,
    }
    return {
        "schema_version": "deck-coach-evaluation.v1",
        "case_id": case["case_id"], "candidate_id": candidate["candidate_id"], "generated_at": now_iso(), "grader": grader,
        "dimensions": dimensions, "metrics": metrics, "failures": failures, "warnings": warnings,
        "overall": {"score": score, "passed": score >= case["pass_threshold"] and not failures},
    }


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    data = load_json(path)
    if data.get("schema_version") != "deck-coach-eval-suite.v2":
        raise PipelineError("deck-coach case file must use deck-coach-eval-suite.v2")
    return data["cases"]


def run_case(case: dict[str, Any], output_dir: Path, candidate_id: str, skill_version: str, model: str) -> dict[str, Any]:
    catalog = CardCatalog()
    deck_input = case_input(case)
    profile = build_profile(deck_input, catalog)
    mask = build_mask(deck_input, profile, catalog)
    candidate = generate_baseline_primer(deck_input, profile, mask, candidate_id, skill_version, model)
    evaluation = evaluate_candidate(case, candidate, profile, mask)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("input", deck_input), ("profile", profile), ("mask", mask), ("primer", candidate), ("evaluation", evaluation)):
        save_json(output_dir / f"{name}.json", value)
    return {"profile": profile, "mask": mask, "candidate": candidate, "evaluation": evaluation}


def battle(case: dict[str, Any], candidate_a: dict[str, Any], candidate_b: dict[str, Any], expert_preference: str = "not_scored") -> dict[str, Any]:
    catalog = CardCatalog()
    deck_input = case_input(case)
    profile = build_profile(deck_input, catalog)
    mask = build_mask(deck_input, profile, catalog)
    eval_a = evaluate_candidate(case, candidate_a, profile, mask)
    eval_b = evaluate_candidate(case, candidate_b, profile, mask)
    delta = {key: round(eval_a["dimensions"][key] - eval_b["dimensions"][key], 4) for key in eval_a["dimensions"]}
    score_a, score_b = eval_a["overall"]["score"], eval_b["overall"]["score"]
    automatic = "A" if score_a > score_b else ("B" if score_b > score_a else "tie")
    return {
        "schema_version": "primer-battle.v1", "battle_id": str(uuid.uuid4()), "case_id": case["case_id"],
        "generated_at": now_iso(), "blind_labels": True,
        "candidate_a": {"candidate_id": candidate_a["candidate_id"], "metadata": candidate_a.get("metadata", {}), "evaluation": eval_a},
        "candidate_b": {"candidate_id": candidate_b["candidate_id"], "metadata": candidate_b.get("metadata", {}), "evaluation": eval_b},
        "automatic_preference": automatic, "expert_preference": expert_preference, "metric_delta": delta,
    }


def _find_case(case_id: str, path: Path = CASES_PATH) -> dict[str, Any]:
    for case in load_cases(path):
        if case["case_id"] == case_id:
            return case
    raise PipelineError(f"unknown case id {case_id!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("profile", "mask"):
        child = sub.add_parser(command)
        child.add_argument("--input", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--input", type=Path, help="deck-coach-input.v1; omit when using --case-id")
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--candidate-id", default="deterministic-baseline")
    run.add_argument("--skill-version", default="working-tree")
    run.add_argument("--model", default="none")
    run.add_argument("--case-id", help="use this built-in eval case, or evaluate a matching plain input")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--case-id", required=True)
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--human-scores", type=Path)
    battle_cmd = sub.add_parser("battle")
    battle_cmd.add_argument("--case-id", required=True)
    battle_cmd.add_argument("--candidate-a", type=Path, required=True)
    battle_cmd.add_argument("--candidate-b", type=Path, required=True)
    battle_cmd.add_argument("--expert-preference", choices=["A", "B", "tie", "not_scored"], default="not_scored")
    battle_cmd.add_argument("--output", type=Path, required=True)
    suite = sub.add_parser("suite")
    suite.add_argument("--output-dir", type=Path, required=True)
    suite.add_argument("--skill-version", default="working-tree")
    suite.add_argument("--model", default="none")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"profile", "mask"}:
            raw = load_json(args.input)
            deck_input = case_input(raw)
            profile = build_profile(deck_input)
            value = profile if args.command == "profile" else build_mask(deck_input, profile)
            save_json(args.output, value)
            print(f"OK: wrote {args.command} to {args.output}")
            return 0
        if args.command == "run":
            if not args.input and not args.case_id:
                raise PipelineError("run requires --input or --case-id")
            selected_case = _find_case(args.case_id) if args.case_id else None
            raw = load_json(args.input) if args.input else selected_case
            deck_input = case_input(raw)
            case = raw if "expected" in raw else selected_case
            catalog = CardCatalog()
            profile = build_profile(deck_input, catalog)
            mask = build_mask(deck_input, profile, catalog)
            candidate = generate_baseline_primer(deck_input, profile, mask, args.candidate_id, args.skill_version, args.model)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for name, value in (("input", deck_input), ("profile", profile), ("mask", mask), ("primer", candidate)):
                save_json(args.output_dir / f"{name}.json", value)
            if case:
                evaluation = evaluate_candidate(case, candidate, profile, mask)
                save_json(args.output_dir / "evaluation.json", evaluation)
                print(f"OK: closed loop complete; evaluation score={evaluation['overall']['score']:.3f}, passed={evaluation['overall']['passed']}")
            else:
                print("OK: profile, mask, and baseline primer written; no eval case selected")
            return 0
        if args.command == "evaluate":
            case = _find_case(args.case_id)
            deck_input = case_input(case)
            catalog = CardCatalog(); profile = build_profile(deck_input, catalog); mask = build_mask(deck_input, profile, catalog)
            human = load_json(args.human_scores) if args.human_scores else None
            result = evaluate_candidate(case, load_json(args.candidate), profile, mask, human)
            save_json(args.output, result)
            print(f"OK: evaluation score={result['overall']['score']:.3f}, passed={result['overall']['passed']}")
            return 0
        if args.command == "battle":
            result = battle(_find_case(args.case_id), load_json(args.candidate_a), load_json(args.candidate_b), args.expert_preference)
            save_json(args.output, result)
            print(f"OK: battle preference={result['automatic_preference']}, expert={result['expert_preference']}")
            return 0
        if args.command == "suite":
            summary = []
            for case in load_cases():
                result = run_case(case, args.output_dir / case["case_id"], f"baseline-{case['case_id']}", args.skill_version, args.model)
                summary.append({"case_id": case["case_id"], **result["evaluation"]["overall"]})
            save_json(args.output_dir / "summary.json", {"schema_version": "deck-coach-suite-summary.v1", "generated_at": now_iso(), "cases": summary})
            print(f"OK: ran {len(summary)} cases; {sum(1 for item in summary if item['passed'])} passed")
            return 0
        raise PipelineError(f"unsupported command {args.command}")
    except PipelineError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
