import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic

from .cache import fingerprint_profile, make_score_key, save_score_cache
from .models import FilteredResult, JobAnalysis, JobListing, Profile, ScoredResult

client = anthropic.Anthropic()

_DESCRIPTION_LIMIT = 2500


@dataclass
class AnalysisTrace:
    analysis: JobAnalysis
    system_prompt: str
    user_message: str
    raw_text: str


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
        "1-4 = weak (missing essentials or significant misalignment).\n\n"
        "Qualification analysis instructions:\n"
        "- Extract any explicitly stated qualification requirements from the job description\n"
        "- Compare each against the candidate's qualifications using exact or near-exact matching only\n"
        '- "PRINCE2 required" is a gap if the candidate does not list PRINCE2 specifically\n'
        "- A Master's degree satisfies \"degree required\" but not \"MBA required\"\n"
        "- Set qualification_status to:\n"
        '    "met"      — all stated requirements are present in the candidate\'s profile\n'
        '    "partial"  — some gaps exist but not clearly disqualifying\n'
        '    "mismatch" — one or more hard requirements are clearly absent\n'
        '    ""         — no qualification requirements found in the description'
        "\n\nExclusion instructions:\n"
        "- Set exclude=true when the job clearly fails a hard requirement that the "
        "upstream filters are meant to enforce but may have missed, based on the full "
        "description: the role is not permanent (fixed-term, contract, temporary, "
        "interim, maternity cover, locum, bank, or seasonal); the salary is clearly "
        "below the stated minimum; or the location is clearly outside the candidate's "
        "area.\n"
        "- Also set exclude=true when the job is clearly unsuitable for this candidate: "
        "wrong seniority level, a fundamentally different profession, or a domain the "
        "candidate is not open to.\n"
        "- When excluding, put a short human-readable reason (a few words) in "
        "exclude_reason, e.g. \"Fixed-term contract\" or \"Clinical nursing role\".\n"
        "- Otherwise set exclude=false and exclude_reason to an empty string; rank the "
        "job with the score instead."
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
        '  "verdict": "...",\n'
        '  "required_qualifications": ["..."],\n'
        '  "qualification_gaps": ["..."],\n'
        '  "qualification_status": "met|partial|mismatch|",\n'
        '  "exclude": false,\n'
        '  "exclude_reason": ""\n'
        "}"
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        return "\n".join(lines[1:end]).strip()
    return stripped


def _parse_analysis(text: str) -> JobAnalysis:
    data = json.loads(_strip_code_fence(text))
    score = int(data["score"])
    qual_status = data.get("qualification_status", "")
    if qual_status == "mismatch":
        score = min(score, 3)
    return JobAnalysis(
        score=score,
        matched_skills=data.get("matched_skills", []),
        missing_essentials=data.get("missing_essentials", []),
        employment_type_note=data.get("employment_type_note", ""),
        verdict=data.get("verdict", ""),
        required_qualifications=data.get("required_qualifications", []),
        qualification_gaps=data.get("qualification_gaps", []),
        qualification_status=qual_status,
        exclude=bool(data.get("exclude", False)),
        exclude_reason=data.get("exclude_reason", ""),
    )


def _analyse_job(job: JobListing, system_prompt: str, model: str) -> JobAnalysis:
    response = client.messages.create(
        model=model,
        max_tokens=768,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_user_message(job)}],
    )
    if not response.content:
        raise ValueError(f"empty content list from Claude (stop_reason={response.stop_reason})")
    block = response.content[0]
    text = getattr(block, "text", "")
    if not text.strip():
        raise ValueError(f"empty text block from Claude (stop_reason={response.stop_reason}, type={type(block).__name__})")
    return _parse_analysis(text)


def analyse_job(job: JobListing, profile: Profile) -> AnalysisTrace:
    system_prompt = _build_system_prompt(profile)
    user_message = _build_user_message(job)
    model = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=768,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    if not response.content:
        raise ValueError(f"empty content list from Claude (stop_reason={response.stop_reason})")
    block = response.content[0]
    raw_text = getattr(block, "text", "")
    if not raw_text.strip():
        raise ValueError(f"empty text block from Claude (stop_reason={response.stop_reason}, type={type(block).__name__})")
    return AnalysisTrace(
        analysis=_parse_analysis(raw_text),
        system_prompt=system_prompt,
        user_message=user_message,
        raw_text=raw_text,
    )


def _build_scored_result(r: FilteredResult, analysis: JobAnalysis) -> ScoredResult:
    rejected = r.rejected
    reject_reason = r.reject_reason
    if analysis.exclude:
        rejected = True
        reject_reason = f"AI suitability: {analysis.exclude_reason}"
    return ScoredResult(
        job=r.job, flags=r.flags, rejected=rejected,
        reject_reason=reject_reason, analysis=analysis,
    )


def score_jobs(
    results: list[FilteredResult],
    profile: Profile,
    score_cache: dict | None = None,
    cache_path: Path | None = None,
) -> list[ScoredResult]:
    if score_cache is None:
        score_cache = {}

    limit = int(os.getenv("DEEP_ANALYSIS_LIMIT", "100"))
    model = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")
    profile_fp = fingerprint_profile(profile)

    rejected = [r for r in results if r.rejected]
    kept = [r for r in results if not r.rejected]

    # When the cap bites we analyse the highest-paid jobs first. Rank blank-salary
    # jobs at the median stated salary so they are not categorically dropped first.
    stated_salaries = [r.job.salary_min for r in kept if r.job.salary_min is not None]
    blank_rank = statistics.median(stated_salaries) if stated_salaries else profile.min_salary
    kept_sorted = sorted(
        kept,
        key=lambda r: r.job.salary_min if r.job.salary_min is not None else blank_rank,
        reverse=True,
    )
    to_analyse = kept_sorted[:limit]
    beyond_cap = kept_sorted[limit:]

    system_prompt = _build_system_prompt(profile)
    scored_map: dict[int, ScoredResult] = {}
    to_call: list[tuple[int, FilteredResult]] = []

    for i, r in enumerate(to_analyse):
        key = make_score_key(r.job.url, profile_fp)
        if key in score_cache:
            scored_map[i] = _build_scored_result(r, JobAnalysis(**score_cache[key]))
        else:
            to_call.append((i, r))

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_analyse_job, r.job, system_prompt, model): (i, r)
            for i, r in to_call
        }
        for future in as_completed(futures):
            idx, r = futures[future]
            try:
                analysis = future.result()
                scored_map[idx] = _build_scored_result(r, analysis)
                score_cache[make_score_key(r.job.url, profile_fp)] = asdict(analysis)
            except Exception as exc:
                print(f"[scorer] analysis failed for {r.job.url!r}: {exc}", file=sys.stderr)
                scored_map[idx] = ScoredResult(
                    job=r.job, flags=r.flags + ["analysis_failed"],
                    rejected=r.rejected, reject_reason=r.reject_reason,
                    analysis=None,
                )

    if cache_path is not None:
        save_score_cache(score_cache, cache_path)

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
