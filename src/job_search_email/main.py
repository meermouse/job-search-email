import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .evaluator_notes import get_evaluator_notes
from .exclusions import get_exclusions
from .filter import filter_jobs
from .models import FilteredResult, Profile, SearchPlan
from .nhs_rules import get_nhs_rules
from .queries import generate_queries
from .search_api.fetcher import fetch_all_jobs

ROOT = Path.cwd()
PROFILE_PATH = ROOT / "profile.yaml"
CACHE_PATH = ROOT / "search_plan_cache.json"
PLAN_PATH = ROOT / "search_plan.json"
RESULTS_PATH = ROOT / "job_results.json"
FILTERED_RESULTS_PATH = ROOT / "job_results_filtered.json"


def load_profile(path: Path = PROFILE_PATH) -> Profile:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)

    p = data["profile"]
    return Profile(
        name=p["name"],
        current_role=p.get("current_role", ""),
        about=p.get("about", ""),
        seniority=p.get("seniority", ""),
        industry=p.get("industry", ""),
        skills=p.get("skills", []),
        previous_roles=p.get("previous_roles", []),
        target_roles=p.get("target_roles", []),
        open_to=p.get("open_to", []),
        not_open_to=p.get("not_open_to", []),
        qualifications=p.get("qualifications", []),
        employment_type=p.get("employment_type", []),
        location=data.get("location", ""),
        min_salary=data.get("min_salary", 0),
    )


def fingerprint_profile(profile: Profile) -> str:
    canonical = json.dumps(asdict(profile), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_search_plan(profile: Profile, fingerprint: str) -> SearchPlan:
    return SearchPlan(
        profile_fingerprint=fingerprint,
        queries=generate_queries(profile),
        exclusions=get_exclusions(profile),
        nhs_rules=get_nhs_rules(),
        evaluator_notes=get_evaluator_notes(profile),
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
            try:
                cache = json.load(handle)
            except json.JSONDecodeError:
                cache = {}

    cache[plan.profile_fingerprint] = asdict(plan)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2)


def write_search_plan(plan: SearchPlan, path: Path = PLAN_PATH) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(plan), handle, indent=2)


def write_filtered_results(results: list[FilteredResult], path: Path = FILTERED_RESULTS_PATH) -> None:
    kept = [r for r in results if not r.rejected]
    rejected = [r for r in results if r.rejected]
    flagged = [r for r in kept if r.flags]

    output = {
        "summary": {
            "total": len(results),
            "kept": len(kept),
            "rejected": len(rejected),
            "flagged": len(flagged),
        },
        "kept": [asdict(r) for r in kept],
        "rejected": [asdict(r) for r in rejected],
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)


def main() -> None:
    profile = load_profile()
    fingerprint = fingerprint_profile(profile)
    cached = load_cached_plan(fingerprint=fingerprint)

    if cached:
        plan = SearchPlan(**cached)
    else:
        plan = generate_search_plan(profile, fingerprint)
        save_cached_plan(plan)
    write_search_plan(plan)

    print("Job search plan ready:")
    print(f"- profile: {profile.name}")
    print(f"- plan fingerprint: {fingerprint}")
    print(f"- queries: {len(plan.queries)}")

    print("Fetching jobs...")
    jobs = fetch_all_jobs(plan, profile)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump([asdict(job) for job in jobs], handle, indent=2)
    print(f"- jobs fetched: {len(jobs)}")
    print(f"- results written to: {RESULTS_PATH}")
    print("Filtering jobs...")
    filtered = filter_jobs(jobs, plan, profile)
    write_filtered_results(filtered)
    kept = [r for r in filtered if not r.rejected]
    flagged = [r for r in kept if r.flags]
    print(f"- filtered: {len(kept)} kept, {len(filtered) - len(kept)} rejected ({len(flagged)} flagged unknown employment type)")
    print(f"- filtered results written to: {FILTERED_RESULTS_PATH}")


if __name__ == "__main__":
    main()
