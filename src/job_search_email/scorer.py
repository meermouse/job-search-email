import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from .models import FilteredResult, JobAnalysis, JobListing, Profile, ScoredResult

client = anthropic.Anthropic()

_DESCRIPTION_LIMIT = 1500


def _build_system_prompt(profile: Profile) -> str:
    return (
        "You are a job suitability analyst. Evaluate whether the following job is a good "
        "match for this candidate. Respond only with valid JSON matching the schema provided.\n\n"
        "Candidate profile:\n"
        f"- Seniority: {profile.seniority}\n"
        f"- Target roles: {', '.join(profile.target_roles)}\n"
        f"- Open to: {', '.join(profile.open_to)}\n"
        f"- Not open to: {', '.join(profile.not_open_to)}\n"
        f"- Skills: {', '.join(profile.skills)}\n"
        f"- Qualifications: {', '.join(profile.qualifications)}\n"
        "- Employment type wanted: full-time permanent only\n"
        f"- Min salary: £{profile.min_salary:,}\n\n"
        "Score guidance: 8-10 = strong match (profile clearly fits). "
        "5-7 = partial match (relevant but gaps present). "
        "1-4 = weak (missing essentials or significant misalignment)."
    )


def _build_user_message(job: JobListing) -> str:
    salary = f"£{job.salary_min:,}" if job.salary_min else "not stated"
    description = (job.description or "")[:_DESCRIPTION_LIMIT]
    return (
        f"Job title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'not stated'}\n"
        f"Salary: {salary}\n"
        f"Employment type: {job.employment_type or 'not stated'}\n"
        f"Description:\n{description}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "score": <1-10>,\n'
        '  "matched_skills": ["..."],\n'
        '  "missing_essentials": ["..."],\n'
        '  "employment_type_note": "...",\n'
        '  "verdict": "..."\n'
        "}"
    )


def _analyse_job(job: JobListing, system_prompt: str, model: str) -> JobAnalysis:
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_user_message(job)}],
    )
    data = json.loads(response.content[0].text)
    return JobAnalysis(
        score=int(data["score"]),
        matched_skills=data.get("matched_skills", []),
        missing_essentials=data.get("missing_essentials", []),
        employment_type_note=data.get("employment_type_note", ""),
        verdict=data.get("verdict", ""),
    )


def score_jobs(results: list[FilteredResult], profile: Profile) -> list[ScoredResult]:
    limit = int(os.getenv("DEEP_ANALYSIS_LIMIT", "20"))
    model = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")

    rejected = [r for r in results if r.rejected]
    kept = [r for r in results if not r.rejected]

    kept_sorted = sorted(kept, key=lambda r: r.job.salary_min or 0, reverse=True)
    to_analyse = kept_sorted[:limit]
    beyond_cap = kept_sorted[limit:]

    system_prompt = _build_system_prompt(profile)
    scored_map: dict[int, ScoredResult] = {}

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_analyse_job, r.job, system_prompt, model): (i, r)
            for i, r in enumerate(to_analyse)
        }
        for future in as_completed(futures):
            idx, r = futures[future]
            try:
                analysis = future.result()
                scored_map[idx] = ScoredResult(
                    job=r.job, flags=r.flags, rejected=r.rejected,
                    reject_reason=r.reject_reason, analysis=analysis,
                )
            except Exception:
                scored_map[idx] = ScoredResult(
                    job=r.job, flags=r.flags + ["analysis_failed"],
                    rejected=r.rejected, reject_reason=r.reject_reason,
                    analysis=None,
                )

    scored_analysed = [scored_map[i] for i in range(len(to_analyse))]
    scored_analysed.sort(
        key=lambda r: r.analysis.score if r.analysis else 0,
        reverse=True,
    )

    scored_beyond = [
        ScoredResult(
            job=r.job, flags=r.flags, rejected=r.rejected,
            reject_reason=r.reject_reason, analysis=None,
        )
        for r in beyond_cap
    ]

    scored_rejected = [
        ScoredResult(
            job=r.job, flags=r.flags, rejected=r.rejected,
            reject_reason=r.reject_reason, analysis=None,
        )
        for r in rejected
    ]

    return scored_analysed + scored_beyond + scored_rejected
