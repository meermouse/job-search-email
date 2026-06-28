import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .cache import fingerprint_profile, load_score_cache
from .email import build_email_html, send_email
from .evaluator_notes import get_evaluator_notes
from .exclusions import get_exclusions
from .filter import filter_jobs
from .location_filter import classify_locations, load_location_cache, save_location_cache
from .models import FilteredResult, JobListing, Profile, SearchPlan, ScoredResult
from .nhs_rules import get_nhs_rules
from .scorer import score_jobs
from .queries import generate_queries
from .search_api.fetcher import fetch_all_jobs

ROOT = Path.cwd()
PROFILE_PATH = ROOT / "profile.yaml"
CACHE_PATH = ROOT / "search_plan_cache.json"
PLAN_PATH = ROOT / "search_plan.json"
RESULTS_PATH = ROOT / "job_results.json"
FILTERED_RESULTS_PATH = ROOT / "job_results_filtered.json"
SCORED_RESULTS_PATH = ROOT / "job_results_scored.json"
SCORE_CACHE_PATH = ROOT / "job_score_cache.json"
LOCATION_CACHE_PATH = ROOT / "location_cache.json"


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
        preamble=data.get("preamble", ""),
        recipient_email=data.get("recipient_email", ""),
        send_main_email=data.get("send_main_email", True),
        send_debug_email=data.get("send_debug_email", False),
    )


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
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            cache = json.load(handle)
    except json.JSONDecodeError:
        return None
    return cache.get(fingerprint)


def save_cached_plan(plan: SearchPlan, cache_path: Path = CACHE_PATH) -> None:
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            with cache_path.open("r", encoding="utf-8") as handle:
                cache = json.load(handle)
        except json.JSONDecodeError:
            cache = {}
    cache[plan.profile_fingerprint] = asdict(plan)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, cache_path)


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


def write_scored_results(results: list[ScoredResult], path: Path = SCORED_RESULTS_PATH) -> None:
    kept = [r for r in results if not r.rejected]
    rejected = [r for r in results if r.rejected]
    analysed = [r for r in kept if r.analysis is not None and "analysis_failed" not in r.flags]
    unanalysed = [r for r in kept if r.analysis is None and "analysis_failed" not in r.flags]
    failed = [r for r in kept if "analysis_failed" in r.flags]

    kept_sorted = sorted(kept, key=lambda r: (r.analysis.score if r.analysis else 0), reverse=True)

    output = {
        "summary": {
            "total": len(results),
            "kept": len(kept),
            "rejected": len(rejected),
            "analysed": len(analysed),
            "unanalysed": len(unanalysed),
            "analysis_failed": len(failed),
        },
        "kept": [asdict(r) for r in kept_sorted],
        "rejected": [asdict(r) for r in rejected],
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)


def _print_location_summary(jobs: list[JobListing]) -> None:
    by_location: dict[str, Counter] = defaultdict(Counter)
    for job in jobs:
        by_location[job.location or "(blank)"][job.source] += 1

    total = len(jobs)
    print(f"[main] Location breakdown ({total} jobs fetched):")
    for location, sources in sorted(by_location.items(), key=lambda x: -sum(x[1].values())):
        count = sum(sources.values())
        source_detail = ", ".join(f"{s}: {n}" for s, n in sorted(sources.items()))
        print(f"  {location:<40} {count:>4}  ({source_detail})")


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
    _print_location_summary(jobs)

    print("Classifying job locations...")
    location_cache = load_location_cache(LOCATION_CACHE_PATH)
    unique_locations = list({j.location for j in jobs if j.location})
    classification = classify_locations(
        unique_locations,
        home=profile.location,
        radius_miles=50,
        cache=location_cache,
    )
    save_location_cache(location_cache, LOCATION_CACHE_PATH)
    rejected_locations = frozenset(loc for loc, verdict in classification.items() if verdict == "outside")
    outside_count = len(rejected_locations)
    if outside_count:
        print(f"- {outside_count} location(s) classified as outside radius: {sorted(rejected_locations)}")

    print("Filtering jobs...")
    filtered = filter_jobs(jobs, plan, profile, rejected_locations=rejected_locations)
    write_filtered_results(filtered)
    kept = [r for r in filtered if not r.rejected]
    flagged = [r for r in kept if r.flags]
    print(f"- filtered: {len(kept)} kept, {len(filtered) - len(kept)} rejected ({len(flagged)} flagged unknown employment type)")
    print(f"- filtered results written to: {FILTERED_RESULTS_PATH}")

    print("Scoring jobs...")
    score_cache = load_score_cache(SCORE_CACHE_PATH)
    scored = score_jobs(filtered, profile, score_cache=score_cache, cache_path=SCORE_CACHE_PATH)
    write_scored_results(scored)
    kept_scored = [r for r in scored if not r.rejected]
    top_score = max((r.analysis.score for r in kept_scored if r.analysis), default="n/a")
    print(f"- scored: {len(kept_scored)} kept, top score: {top_score}")
    print(f"- scored results written to: {SCORED_RESULTS_PATH}")

    print("Sending email...")
    html, top_n = build_email_html(scored, profile)
    send_email(html, profile, n=top_n)


if __name__ == "__main__":
    main()
