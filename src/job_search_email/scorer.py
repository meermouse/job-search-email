import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic

from .cache import fingerprint_profile, fingerprint_prompt, make_score_key, save_score_cache
from .location_filter import _extract_json_object
from .models import FilteredResult, JobAnalysis, JobListing, Profile, ScoredResult
from .profile import render_profile

client = anthropic.Anthropic()

# Job descriptions routinely bury the "Essential Qualifications" / "Requirements"
# section in the second half, after the company blurb and responsibilities. The
# cap must be generous enough to reach it: real Indeed postings run ~5k chars.
_DESCRIPTION_LIMIT = 8000

# The JSON schema has six list fields plus a free-text verdict; 768 tokens
# truncates it often enough that ~1 in 8 haiku calls returned unparseable JSON
# ("Unterminated string"). Give it room, and retry the rest.
_MAX_TOKENS = 1536
_ANALYSIS_ATTEMPTS = 3


@dataclass
class AnalysisTrace:
    analysis: JobAnalysis
    system_prompt: str
    user_message: str
    raw_text: str


def _build_system_prompt(profile: Profile) -> str:
    base = (
        "You are a job suitability analyst. Evaluate whether the following job is a good "
        "match for this candidate. Respond only with valid JSON matching the schema provided.\n\n"
        "Candidate profile:\n"
        f"{render_profile(profile)}\n\n"
        "Search preferences:\n"
        f"- Seniority: {profile.seniority}\n"
        f"- Target roles: {', '.join(profile.target_roles)}\n"
        f"- Open to: {', '.join(profile.open_to)}\n"
        f"- Not open to: {', '.join(profile.not_open_to)}\n"
        "- Employment type wanted: full-time permanent only\n"
        f"- Min salary: £{profile.min_salary:,}\n\n"
        "Score guidance — score the candidate's realistic odds of being shortlisted, "
        "not the breadth of skills overlap: "
        "8-10 = strong match (would very likely survive the initial sift). "
        "5-7 = partial match (credible applicant but real gaps present). "
        "1-4 = weak (would not survive the initial sift: missing essentials, wrong "
        "profession, or significant misalignment).\n\n"
        "Calibration: the score must reflect the candidate's realistic odds of "
        "being shortlisted, not just breadth of skills overlap. Identify any "
        "requirement a hiring manager would treat as gatekeeping at the role's "
        "stated seniority — for example a fee-earning or business-development "
        "track record for senior consultancy grades, statutory registration, or "
        "prior budget ownership at director level. List every gatekeeping "
        "requirement the candidate lacks in gatekeeping_gaps (use an empty list "
        "if there are none). If the candidate lacks any gatekeeping requirement, "
        "the job is at best a partial match: score it 6 or below, however strong "
        "the remaining overlap. Then weigh how central that missing requirement "
        "is: a peripheral gap sits at 5-6; when the missing requirement is a "
        "core competency the role is built around (managing client accounts for "
        "an account-management role, a security-cleared defence delivery record "
        "for an MoD programme), the candidate would not clear the initial sift — "
        "score it 2-4.\n"
        "If the role's core discipline (e.g. HR, finance, legal, clinical, "
        "engineering, qualified accountancy, or a sales/business-development role "
        "carrying revenue accountability) is a profession the candidate has "
        "never held a post in, transferable skills do not survive the sift for a "
        "specialist role: score it 1-4 regardless of keyword overlap, and "
        "normally set exclude=true with exclude_reason \"Different profession\". "
        "Judge this on the discipline of the role, not the employer's industry: "
        "a general management, governance, transformation, programme/project, or "
        "operations role is not a different profession merely because the "
        "employer's sector (retail, legal, energy, defence, and so on) is one "
        "the candidate has not worked in — score those on transferable fit using "
        "the normal scale.\n\n"
        "Qualification analysis instructions:\n"
        "- Extract any explicitly stated qualification requirements from the job description\n"
        "- Compare each against the candidate's education and certifications using exact or near-exact matching only\n"
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
        "- A missing salary or unstated employment type is not itself grounds for "
        "exclusion — the upstream filters pass those through deliberately. Note the "
        "uncertainty in the verdict and rank on the score; only exclude when the "
        "posting states terms that fail a hard requirement.\n"
        "- \"FTC\" means fixed-term contract. Treat any posting that offers "
        "fixed-term as a possibility, including dual \"Permanent / FTC\" "
        "listings, as not a guaranteed permanent role: set exclude=true with "
        "exclude_reason \"Fixed-term contract (FTC)\".\n"
        "- Also set exclude=true when the job is clearly unsuitable for this candidate: "
        "wrong seniority level, a fundamentally different profession, or a domain the "
        "candidate is not open to.\n"
        "- When excluding, put a short human-readable reason (a few words) in "
        "exclude_reason, e.g. \"Fixed-term contract\" or \"Clinical nursing role\".\n"
        "- Otherwise set exclude=false and exclude_reason to an empty string; rank the "
        "job with the score instead."
    )
    if profile.remote_uk_wide or profile.remote_hubs:
        base += (
            "\n\nRemote preference: the candidate actively wants fully-remote work. "
            "Do NOT set exclude=true, and do NOT mark the score down, solely because "
            "the role's location is outside the candidate's home region when the "
            "posting is remote. A role that is remote-first with some client travel "
            "is acceptable.\n"
        )
    return base


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
        "Return JSON (populate the analysis fields first, then decide the score):\n"
        "{\n"
        '  "matched_skills": ["..."],\n'
        '  "missing_essentials": ["..."],\n'
        '  "gatekeeping_gaps": ["..."],\n'
        '  "required_qualifications": ["..."],\n'
        '  "qualification_gaps": ["..."],\n'
        '  "qualification_status": "met|partial|mismatch|",\n'
        '  "employment_type_note": "...",\n'
        '  "verdict": "...",\n'
        '  "score": <1-10>,\n'
        '  "exclude": false,\n'
        '  "exclude_reason": ""\n'
        "}"
    )


def _parse_analysis(text: str) -> JobAnalysis:
    # _extract_json_object tolerates a code fence or trailing prose around the
    # object ("Extra data" from json.loads), which haiku emits intermittently.
    data = _extract_json_object(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object from the scorer, got {type(data).__name__}")
    score = int(data["score"])
    gatekeeping_gaps = data.get("gatekeeping_gaps", [])
    if gatekeeping_gaps:
        score = min(score, 6)
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
        gatekeeping_gaps=gatekeeping_gaps,
        exclude=bool(data.get("exclude", False)),
        exclude_reason=data.get("exclude_reason", ""),
    )


def _request_analysis(system_prompt: str, user_message: str, model: str) -> tuple[JobAnalysis, str]:
    """Call the scorer model, retrying transient API and parse failures.

    haiku intermittently truncates the JSON or wraps it in prose; a retry
    clears both, and the wider max_tokens stops the truncation at source.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _ANALYSIS_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            if not response.content:
                raise ValueError(f"empty content list from Claude (stop_reason={response.stop_reason})")
            block = response.content[0]
            raw_text = getattr(block, "text", "")
            if not raw_text.strip():
                raise ValueError(f"empty text block from Claude (stop_reason={response.stop_reason}, type={type(block).__name__})")
            return _parse_analysis(raw_text), raw_text
        except Exception as exc:
            last_exc = exc
            if attempt < _ANALYSIS_ATTEMPTS:
                print(f"[scorer] analysis attempt {attempt}/{_ANALYSIS_ATTEMPTS} failed: {exc}", file=sys.stderr)
                time.sleep(2 ** attempt)
    assert last_exc is not None  # the loop runs at least once
    raise last_exc


def _analyse_job(job: JobListing, system_prompt: str, model: str) -> JobAnalysis:
    analysis, _ = _request_analysis(system_prompt, _build_user_message(job), model)
    return analysis


def analyse_job(job: JobListing, profile: Profile) -> AnalysisTrace:
    system_prompt = _build_system_prompt(profile)
    user_message = _build_user_message(job)
    model = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")
    analysis, raw_text = _request_analysis(system_prompt, user_message, model)
    return AnalysisTrace(
        analysis=analysis,
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
    # The fingerprint covers only the system prompt: a change to _build_user_message alone (e.g. the JSON schema) will NOT invalidate cached scores.
    prompt_fp = fingerprint_prompt(system_prompt)
    scored_map: dict[int, ScoredResult] = {}
    to_call: list[tuple[int, FilteredResult]] = []

    for i, r in enumerate(to_analyse):
        key = make_score_key(r.job.url, profile_fp, prompt_fp)
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
                score_cache[make_score_key(r.job.url, profile_fp, prompt_fp)] = asdict(analysis)
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
