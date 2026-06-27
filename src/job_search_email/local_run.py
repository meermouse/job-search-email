import json
from dataclasses import asdict
from pathlib import Path

import yaml

from .cache import fingerprint_profile
from .email import build_email_html
from .evaluator_notes import get_evaluator_notes
from .filter import filter_jobs
from .fixtures import fixture_jobs, fixture_queries, fixture_scores
from .models import FilteredResult, Profile, SearchPlan, ScoredResult
from .nhs_rules import get_nhs_rules

_EXCLUSION_ROLES = [
    "locum", "gp", "surgeon", "nurse", "clinical", "surgical", "physician",
    "dentist", "pharmacist", "physiotherapist", "radiographer", "midwife",
    "paramedic", "theatre", "ward", "medical officer", "occupational therapist",
    "nursing", "ward-based", "gp / medical practitioner",
]


def _load_profile(path: Path) -> Profile:
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
    )


def _write_search_plan(plan: SearchPlan, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(plan), handle, indent=2)


def _write_filtered_results(results: list[FilteredResult], path: Path) -> None:
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


def _write_scored_results(results: list[ScoredResult], path: Path) -> None:
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


def main() -> None:
    root = Path.cwd()
    profile = _load_profile(root / "profile.yaml")
    fingerprint = fingerprint_profile(profile)

    exclusion_roles = sorted(set(_EXCLUSION_ROLES + [t.lower() for t in profile.not_open_to]))
    plan = SearchPlan(
        profile_fingerprint=fingerprint,
        queries=fixture_queries(),
        exclusions={"roles": exclusion_roles, "employment_types": ["locum", "fixed-term", "temporary", "bank", "agency", "casual", "zero-hours"]},
        nhs_rules=get_nhs_rules(),
        evaluator_notes=get_evaluator_notes(profile),
    )
    _write_search_plan(plan, root / "search_plan.json")
    print("[local-test] search plan written")

    jobs = fixture_jobs()
    print(f"[local-test] fixture jobs loaded: {len(jobs)}")

    filtered = filter_jobs(jobs, plan, profile)
    _write_filtered_results(filtered, root / "job_results_filtered.json")
    kept = [r for r in filtered if not r.rejected]
    print(f"[local-test] filtered: {len(kept)} kept, {len(filtered) - len(kept)} rejected")

    scored = fixture_scores(filtered)
    _write_scored_results(scored, root / "job_results_scored.json")

    html, top_n = build_email_html(scored, profile)
    preview_path = root / "email_preview.html"
    preview_path.write_text(html, encoding="utf-8")
    print(f"[local-test] email preview written to {preview_path} ({top_n} jobs)")
