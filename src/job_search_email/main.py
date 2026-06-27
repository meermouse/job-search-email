import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path.cwd()
PROFILE_PATH = ROOT / "profile.yaml"
CACHE_PATH = ROOT / "search_plan_cache.json"
PLAN_PATH = ROOT / "search_plan.json"


@dataclass
class Profile:
    name: str
    target_roles: list[str]
    skills: list[str]
    location: str
    preferred_nhs_band: str


@dataclass
class SearchPlan:
    profile_fingerprint: str
    queries: list[str]
    exclusions: dict[str, list[str]]
    nhs_rules: dict[str, Any]
    evaluator_notes: list[str]


def load_profile(path: Path = PROFILE_PATH) -> Profile:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)

    return Profile(
        name=data.get("name", "Anonymous"),
        target_roles=data.get("target_roles", []),
        skills=data.get("skills", []),
        location=data.get("location", ""),
        preferred_nhs_band=data.get("preferred_nhs_band", "Band 8a+"),
    )


def fingerprint_profile(profile: Profile) -> str:
    canonical = json.dumps(asdict(profile), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_search_plan(profile: Profile, fingerprint: str) -> SearchPlan:
    # Future logic will produce richer, tailored queries.
    target = ", ".join(profile.target_roles[:2]) or "job search"
    skills = ", ".join(profile.skills[:3])
    queries = [
        f"{target} {skills} opportunity {i + 1}" for i in range(8)
    ]

    exclusions = {
        "clinical_roles": ["doctor", "nurse", "consultant"],
        "employment_types": ["locum", "fixed-term", "temporary"],
    }

    nhs_rules = {
        "default_floor": "Band 8a+",
        "london_remote_exception": "Band 7+",
    }

    evaluator_notes = [
        "Score opportunities on seniority, skills fit, and remote flexibility.",
        "Exclude clinical roles unless explicitly requested.",
    ]

    return SearchPlan(
        profile_fingerprint=fingerprint,
        queries=queries,
        exclusions=exclusions,
        nhs_rules=nhs_rules,
        evaluator_notes=evaluator_notes,
    )


def load_cached_plan(cache_path: Path = CACHE_PATH, fingerprint: str = "") -> dict[str, Any] | None:
    if not cache_path.exists():
        return None

    with cache_path.open("r", encoding="utf-8") as handle:
        cache = json.load(handle)

    return cache.get(fingerprint)


def save_cached_plan(plan: SearchPlan, cache_path: Path = CACHE_PATH) -> None:
    cache: dict[str, Any] = {}
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)

    cache[plan.profile_fingerprint] = asdict(plan)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2)


def write_search_plan(plan: SearchPlan, path: Path = PLAN_PATH) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(plan), handle, indent=2)


def main() -> None:
    profile = load_profile()
    fingerprint = fingerprint_profile(profile)
    cached = load_cached_plan(fingerprint=fingerprint)

    if cached:
        plan_data = cached
    else:
        plan = generate_search_plan(profile, fingerprint)
        save_cached_plan(plan)
        write_search_plan(plan)
        plan_data = asdict(plan)

    print("Job search plan ready:")
    print(f"- profile: {profile.name}")
    print(f"- plan fingerprint: {fingerprint}")
    print(f"- queries: {len(plan_data['queries'])}")


if __name__ == "__main__":
    main()
