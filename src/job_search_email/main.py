import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .evaluator_notes import get_evaluator_notes
from .exclusions import get_exclusions
from .models import Profile, SearchPlan
from .nhs_rules import get_nhs_rules
from .queries import generate_queries

ROOT = Path.cwd()
PROFILE_PATH = ROOT / "profile.yaml"
CACHE_PATH = ROOT / "search_plan_cache.json"
PLAN_PATH = ROOT / "search_plan.json"


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
    return SearchPlan(
        profile_fingerprint=fingerprint,
        queries=generate_queries(profile),
        exclusions=get_exclusions(),
        nhs_rules=get_nhs_rules(),
        evaluator_notes=get_evaluator_notes(),
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
