import json
import os
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .cache import fingerprint_profile, load_score_cache
from .email import build_email_html, send_email, send_debug_report
from .debug_email import build_debug_email_html
from .evaluator_notes import get_evaluator_notes
from .exclusions import get_exclusions
from .filter import filter_jobs
from .location_filter import classify_locations, load_location_cache, save_location_cache
from .models import FilteredResult, JobListing, Profile, SearchPlan, ScoredResult
from .nhs_rules import get_nhs_rules
from .profile import load_profile
from .scorer import score_jobs
from .queries import generate_queries
from .search_api.fetcher import fetch_all_jobs
from .sponsor_filter import load_sponsor_set
from .recruitment_filter import load_recruitment_set

ROOT = Path.cwd()
PROFILES_DIR = ROOT / "profiles"
DEFAULT_PROFILE_PATH = PROFILES_DIR / "jie-zhou.yaml"
RUNS_DIR = ROOT / "runs"
CACHE_PATH = ROOT / "search_plan_cache.json"
SCORE_CACHE_PATH = ROOT / "job_score_cache.json"
LOCATION_CACHE_PATH = ROOT / "location_cache.json"
SPONSOR_CACHE_PATH = ROOT / "assets" / "sponsor_cache.csv"
RECRUITMENT_CACHE_PATH = ROOT / "assets" / "recruitment_agencies.csv"


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


def write_search_plan(plan: SearchPlan, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(plan), handle, indent=2)


def write_filtered_results(results: list[FilteredResult], path: Path) -> None:
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


def write_scored_results(results: list[ScoredResult], path: Path) -> None:
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


def run_pipeline(profile: Profile, output_dir: Path) -> tuple[dict[str, Any], list[ScoredResult]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "search_plan.json"
    results_path = output_dir / "job_results.json"
    filtered_results_path = output_dir / "job_results_filtered.json"
    scored_results_path = output_dir / "job_results_scored.json"

    fingerprint = fingerprint_profile(profile)
    cached = load_cached_plan(cache_path=CACHE_PATH, fingerprint=fingerprint)

    if cached:
        plan = SearchPlan(**cached)
    else:
        plan = generate_search_plan(profile, fingerprint)
        save_cached_plan(plan, cache_path=CACHE_PATH)
    write_search_plan(plan, plan_path)

    print("Job search plan ready:")
    print(f"- profile: {profile.name}")
    print(f"- plan fingerprint: {fingerprint}")
    print(f"- queries: {len(plan.queries)}")

    print("Fetching jobs...")
    jobs = fetch_all_jobs(plan, profile)
    with results_path.open("w", encoding="utf-8") as handle:
        json.dump([asdict(job) for job in jobs], handle, indent=2)
    print(f"- jobs fetched: {len(jobs)}")
    print(f"- results written to: {results_path}")
    _print_location_summary(jobs)

    print("Classifying job locations...")
    location_cache = load_location_cache(LOCATION_CACHE_PATH)
    unique_locations = list({j.location for j in jobs if j.location})
    classification = classify_locations(
        unique_locations,
        home=profile.location,
        radius_miles=profile.radius_miles,
        cache=location_cache,
    )
    save_location_cache(location_cache, LOCATION_CACHE_PATH)
    rejected_locations = frozenset(loc for loc, verdict in classification.items() if verdict == "outside")
    outside_count = len(rejected_locations)
    if outside_count:
        print(f"- {outside_count} location(s) classified as outside radius: {sorted(rejected_locations)}")

    print("Filtering jobs...")
    if profile.filter_sponsors:
        sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
        print(f"- sponsor list loaded: {len(sponsor_set):,} entries")
    else:
        sponsor_set = None
        print("- sponsor filter disabled (filter_sponsors=false)")
    recruitment_set = load_recruitment_set(RECRUITMENT_CACHE_PATH) if profile.filter_recruitment else None
    if recruitment_set is not None:
        print(f"- recruitment list loaded: {len(recruitment_set):,} entries")
    else:
        print("- recruitment filter disabled (filter_recruitment=false)")
    filtered = filter_jobs(
        jobs, plan, profile,
        rejected_locations=rejected_locations,
        recruitment_set=recruitment_set,
        sponsor_set=sponsor_set,
    )
    write_filtered_results(filtered, filtered_results_path)
    kept = [r for r in filtered if not r.rejected]
    flagged = [r for r in kept if r.flags]
    print(f"- filtered: {len(kept)} kept, {len(filtered) - len(kept)} rejected ({len(flagged)} flagged unknown employment type)")
    print(f"- filtered results written to: {filtered_results_path}")

    print("Scoring jobs...")
    score_cache = load_score_cache(SCORE_CACHE_PATH)
    scored = score_jobs(filtered, profile, score_cache=score_cache, cache_path=SCORE_CACHE_PATH)
    write_scored_results(scored, scored_results_path)
    kept_scored = [r for r in scored if not r.rejected]
    top_score = max((r.analysis.score for r in kept_scored if r.analysis), default="n/a")
    print(f"- scored: {len(kept_scored)} kept, top score: {top_score}")
    print(f"- scored results written to: {scored_results_path}")

    return classification, scored


def discover_profiles(profiles_dir: Path) -> list[Path]:
    return sorted(profiles_dir.glob("*.yaml"))


def process_profile(profile_path: Path) -> None:
    profile = load_profile(profile_path)
    classification, scored = run_pipeline(profile, RUNS_DIR / profile_path.stem)

    print("Sending emails...")
    main_html, top_n = build_email_html(scored, profile)

    if profile.send_main_email:
        send_email(main_html, profile, n=top_n)
    elif profile.send_debug_email:
        smtp_user = os.getenv("SMTP_USER")
        if smtp_user:
            send_email(main_html, profile, n=top_n, override_to=smtp_user)
        else:
            print("[main] send_main_email=False but SMTP_USER not set — skipping main email redirect", file=sys.stderr)

    if profile.send_debug_email:
        debug_html = build_debug_email_html(classification, scored, profile)
        send_debug_report(debug_html)


def main() -> None:
    profile_paths = discover_profiles(PROFILES_DIR)
    if not profile_paths:
        print(f"[main] no profiles found in {PROFILES_DIR}", file=sys.stderr)
        raise SystemExit(1)

    failed: list[str] = []
    for profile_path in profile_paths:
        print(f"\n=== Profile: {profile_path.stem} ===")
        try:
            process_profile(profile_path)
        except Exception:
            print(f"[main] profile {profile_path.name} failed:", file=sys.stderr)
            traceback.print_exc()
            failed.append(profile_path.name)

    if failed:
        print(f"[main] {len(failed)} profile(s) failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
