# Deep Job Scoring — Design Spec

**Date:** 2026-06-27
**Status:** Approved

## Overview

A new LLM-powered scoring step sits after `filter_jobs` in the pipeline. It takes the jobs that survived the rule-based filter and evaluates each one against the user's full profile using the Anthropic API, producing a numeric score (1–10) and a structured suitability analysis. The score enables downstream ranking, and the analysis text is intended for display in the job email.

## Pipeline Position

```
fetch_all_jobs → filter_jobs → score_jobs → write_scored_results
```

- `filter_jobs` continues to operate as-is (rule-based: employment type, role exclusions, NHS band salary).
- `score_jobs` operates only on the **kept** results from `filter_jobs`. Already-rejected jobs skip scoring entirely.
- `write_scored_results` writes `job_results_scored.json` — the new terminal output file for the pipeline.

## Cap & Pre-sorting

Before scoring, kept jobs are sorted by `salary_min` descending (nulls last). The top N are analysed; jobs beyond the cap receive `analysis=None` and are kept in results as unanalysed.

- **Default cap:** 20 jobs
- **Configuration:** `DEEP_ANALYSIS_LIMIT` environment variable (integer). Defaults to `"20"` if unset.

## Data Models

Two new dataclasses added to `models.py`:

```python
@dataclass
class JobAnalysis:
    score: int                    # 1–10 suitability score
    matched_skills: list[str]     # candidate skills/experience that match the role
    missing_essentials: list[str] # essential requirements not met (empty if none)
    employment_type_note: str     # confirms permanent/full-time, or flags anomalies
    verdict: str                  # 1-sentence plain-English summary for the email

@dataclass
class ScoredResult:
    job: JobListing
    flags: list[str]
    rejected: bool
    reject_reason: str | None
    analysis: JobAnalysis | None  # None = not analysed (beyond cap, or already rejected)
```

`FilteredResult` is unchanged. `score_jobs` converts each `FilteredResult` to a `ScoredResult`, adding `analysis`.

### Score guidance

| Score | Meaning |
|-------|---------|
| 8–10 | Strong match — profile clearly fits the role |
| 5–7 | Partial match — relevant experience but gaps present |
| 1–4 | Weak match — missing essentials or significant misalignment |

A job with missing essential requirements gets `missing_essentials` populated and a score of 1–4. It is **not** hard-rejected — it stays in results with a low score. The email step (future task) can threshold at a minimum score (e.g., 7+) to decide which jobs to include.

## New Module: `scorer.py`

**Location:** `src/job_search_email/scorer.py`

**Public interface:**
```python
def score_jobs(
    results: list[FilteredResult],
    profile: Profile,
) -> list[ScoredResult]:
```

**Internal flow:**
1. Separate rejected vs. kept results.
2. Sort kept by `salary_min` descending (None → 0 for sort key).
3. Read `DEEP_ANALYSIS_LIMIT` from env (default 20).
4. Split kept into `to_analyse` (top N) and `beyond_cap` (remainder).
5. Build the system prompt once from the profile.
6. Dispatch concurrent Claude API calls via `ThreadPoolExecutor` — one call per job in `to_analyse`.
7. Parse each JSON response into a `JobAnalysis`.
8. Assemble and return the full `list[ScoredResult]` (rejected + scored + unanalysed), sorted by score descending within kept.

## API Call Design

**Model:** `claude-haiku-4-5-20251001` (default). Configurable via `SCORER_MODEL` env var.

**System prompt** (built once, reused for all calls):
```
You are a job suitability analyst. Evaluate whether the following job is a good match
for this candidate. Respond only with valid JSON matching the schema provided.

Candidate profile:
- Seniority: <seniority>
- Target roles: <target_roles joined>
- Open to: <open_to joined>
- Not open to: <not_open_to joined>
- Skills: <skills joined>
- Qualifications: <qualifications joined>
- Employment type wanted: full-time permanent only
- Min salary: £<min_salary>

Score 8–10 = strong match. Score 5–7 = partial match. Score 1–4 = weak or missing essentials.
```

**User message** (per job, description truncated to 1,500 characters):
```
Job title: <title>
Company: <company>
Location: <location>
Salary: <salary_min or "not stated">
Employment type: <employment_type or "not stated">
Description:
<description[:1500]>

Return JSON:
{
  "score": <1-10>,
  "matched_skills": ["..."],
  "missing_essentials": ["..."],
  "employment_type_note": "...",
  "verdict": "..."
}
```

## Error Handling

If a single Claude API call fails (network error, malformed JSON, rate limit):
- That job receives `analysis=None`.
- `"analysis_failed"` is appended to its `flags`.
- All other concurrent calls are unaffected.
- No exception is raised from `score_jobs`.

## Output File: `job_results_scored.json`

Written by a new `write_scored_results` function in `main.py`. Structure:

```json
{
  "summary": {
    "total": 45,
    "kept": 18,
    "rejected": 24,
    "analysed": 18,      // kept jobs that received an API call and succeeded
    "unanalysed": 0,     // kept jobs beyond the DEEP_ANALYSIS_LIMIT cap
    "analysis_failed": 0 // kept jobs where the API call failed
  },
  "kept": [ ...ScoredResult dicts, sorted by score descending... ],
  "rejected": [ ...ScoredResult dicts... ]
}
```

## `main.py` Changes

Minimal additions after the existing filter step:

```python
from .scorer import score_jobs

scored = score_jobs(filtered, profile)
write_scored_results(scored)
kept_scored = [r for r in scored if not r.rejected]
print(f"- scored: {len(kept_scored)} kept, top score: {max((r.analysis.score for r in kept_scored if r.analysis), default='n/a')}")
print(f"- scored results written to: {SCORED_RESULTS_PATH}")
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEP_ANALYSIS_LIMIT` | `20` | Max jobs to deep-analyse per run |
| `SCORER_MODEL` | `claude-haiku-4-5-20251001` | Claude model used for scoring |
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key |

## Files Changed / Created

| File | Change |
|------|--------|
| `src/job_search_email/models.py` | Add `JobAnalysis`, `ScoredResult` dataclasses |
| `src/job_search_email/scorer.py` | New module — `score_jobs` function |
| `src/job_search_email/main.py` | Wire in `score_jobs`, add `write_scored_results`, add `SCORED_RESULTS_PATH` |
