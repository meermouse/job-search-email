# Explain-Job: Diagnose Why a Job Got Its Rating

**Date:** 2026-06-29
**Status:** Approved design, ready for planning

## Problem

The pipeline rates jobs through a chain of hard filters (location, employment
type, role suitability, NHS band salary, sponsor list) followed by an LLM
suitability scorer. When a developer sees a job in the emailed results and
wonders *why* it got the score it did — or why an expected job never appeared —
there is no way to interrogate that decision for a single job.

The real pipeline runs on GitHub Actions. It persists only three cache files
(`search_plan_cache.json`, `job_score_cache.json`, `location_cache.json`) into
the Actions cache, and even those are not committed to the repo. The full run
artifacts (`job_results.json`, `job_results_scored.json`) are generated inside
the runner and discarded. **The developer's local machine has none of the real
run's data.** Any debugging tool must therefore work locally without depending
on GitHub artifacts.

## Goal

A local, developer-facing command that takes a job URL (the same URL that
appeared in the email) and explains the rating by replaying the **real** filter
and scorer logic on the developer's machine, printing a readable stage-by-stage
trace.

### Non-goals

- **Reproducing the exact emailed score.** A local replay re-runs the LLM scorer
  fresh, so its number may differ from the email's (LLM nondeterminism, or the
  listing changed). The goal is to understand the decision *logic*, not to
  forensically reproduce a past number.
- Re-fetching from sources that cannot be addressed by URL reliably
  (LinkedIn/Indeed) — these are handled by a manual fallback, not scraping.

## Interface

A new console command `explain-job`, registered in `pyproject.toml` alongside
the existing `job-search-email` and `job-search-email-local` entry points.

```
explain-job <job-url> [--profile profile.yaml] [--job-file path.yaml] [--force-score]
```

- **`<job-url>`** — required (unless `--job-file` is supplied). The job URL,
  typically copied from the email.
- **`--profile`** — optional. Path to the candidate profile YAML. Defaults to
  `profile.yaml` in the repo root — the same file the real pipeline loads. Only
  needed to test against a different profile.
- **`--job-file`** — optional. Path to a small YAML describing the job's fields.
  Used as the fallback when the URL cannot be auto-fetched (LinkedIn/Indeed), or
  to drive the tool from hand-entered data for any source. When supplied, the
  URL argument becomes optional.
- **`--force-score`** — optional flag. Run the LLM scorer even when the job was
  rejected by a hard gate (the real pipeline never scores rejected jobs). Lets
  the developer ask "what would the AI have said anyway?".

Normal case is just the URL:

```
explain-job https://www.reed.co.uk/jobs/senior-project-manager/53819371
```

## Architecture

The design adds two new modules and a small surgical seam to the existing
scorer, reusing the real production filter and scorer logic so the trace cannot
drift from what the pipeline actually does.

### Module layout

- **`explain_job.py`** (new) — orchestration and `main()` entry point. Resolves
  the job, runs the filter trace, runs the scorer trace, and renders the text
  output.
- **`job_resolver.py`** (new) — `resolve_job(url, job_file) -> JobListing`.
  Reed via the job-detail API; NHS best-effort advert scrape; LinkedIn/Indeed
  raise a clear "unsupported, use `--job-file`" error. `--job-file` overrides or
  satisfies any URL.
- **`scorer.py`** (edit) — extract the body of the existing private
  `_analyse_job` into a public `analyse_job(job, profile) -> AnalysisTrace` that
  returns the analysis plus the exact system prompt, user message, and raw model
  text. `score_jobs` is refactored to call this so there is no behavioural change
  to the pipeline.
- **`filter.py`** (no change) — the explainer imports the existing per-gate
  `_check_*` functions and runs them in pipeline order, so the trace uses the
  real gate logic.

### Why this structure

Two alternatives were considered and rejected:

- **Reuse `filter_jobs`/`score_jobs` as-is.** Simplest, but `filter_jobs`
  short-circuits at the *first* failing gate and `score_jobs` hides the LLM
  prompt/response — the trace would be too thin to explain a rating.
- **Bespoke trace reaching into private helpers and re-implementing the scorer
  call.** Richest output but duplicates logic and couples tightly to internals.

The chosen approach adds one thin public seam (`analyse_job`) and reuses the
existing gate functions, giving full LLM visibility and an exhaustive filter
trace with minimal, surgical change to core files.

## Job resolution (URL → JobListing)

`resolve_job` maps a URL (or `--job-file`) to the same `JobListing` dataclass the
searchers produce.

- **Reed** — extract the trailing numeric id from the URL, call
  `https://www.reed.co.uk/api/1.0/jobs/{id}` authenticated with `REED_API_KEY`,
  and map the response to `JobListing` (full description, salary, employment
  type) using the same field mapping as `reed.py`.
- **NHS** — fetch the advert page and scrape title/company/location/salary. The
  **description stays empty**, mirroring exactly what the pipeline scored (NHS
  descriptions are never fetched in production).
- **LinkedIn / Indeed** — detect the host and raise `UnsupportedSourceError`
  with a message instructing the developer to pass `--job-file`.
- **`--job-file`** — a small YAML with fields `title`, `company`, `location`,
  `salary_min`, `description`, `employment_type`, `source` → `JobListing`.
  Source-agnostic, and the documented fallback. When provided, the URL argument
  is optional.

## Filter trace

Run each hard gate in the real pipeline order — location, employment type, role
suitability, NHS band salary, sponsor — reusing the existing `_check_*`
functions. Report **every** gate's verdict (pass / reject + reason), not just the
first failure, so the developer sees the full picture, with a note that in the
real run the first reject is what stops the job. Location classification reuses
`classify_locations` for the single job's location.

## Scorer trace

If the job passes all hard gates (or always, when `--force-score` is set), call
the new public `analyse_job`. Print the score, verdict, matched skills, missing
essentials, qualification status and gaps, the `exclude` flag and reason, **and**
the exact system prompt, user message, and raw JSON the model returned. This is
the core of explaining *why* a job got its rating.

## Output format (readable trace)

```
JOB: Senior Project Manager — Acme Ltd  (reed)
URL: https://www.reed.co.uk/jobs/.../53819371
Salary: £65,000 | Type: permanent | Location: Bristol

── HARD FILTERS ──────────────────────────────
✓ Location          within radius (Bristol)
✓ Employment type   permanent
✓ Role suitability  no excluded term matched
✓ NHS band salary   n/a (not an NHS band role)
✓ Sponsor list      Acme Ltd on approved sponsor list
→ Passed all filters; sent to AI scorer

── AI SUITABILITY ────────────────────────────
Score: 8/10
Verdict: Strong match — PM background fits...
Matched: stakeholder mgmt, Agile, budgeting
Missing: PRINCE2
Qualifications: partial (PRINCE2 mentioned, not held)
Exclude: no

── LLM CALL (verbatim) ───────────────────────
[system prompt]
...
[user message]
...
[raw response]
{ "score": 8, ... }
```

## Error handling and edge cases

- **Job rejected by a hard gate:** still show the full filter trace; **skip** the
  LLM call by default (matching the real pipeline, which never scores rejected
  jobs), with a one-line note. `--force-score` scores it anyway.
- **Missing `REED_API_KEY` or `ANTHROPIC_API_KEY`:** fail fast with a clear
  message naming the missing variable.
- **Fetch failure / job not found / unsupported host:** clear error pointing at
  `--job-file`.

## Testing

- **`job_resolver`:** Reed URL→id parsing; Reed API response mapping (mocked
  HTTP); NHS advert scrape (fixture HTML); unsupported-host error;
  `--job-file` loading.
- **Filter trace:** a job that fails one gate still reports all gates; order is
  correct.
- **`analyse_job` seam:** returns prompt + raw text; `score_jobs` still behaves
  (existing scorer tests stay green).
- **Renderer:** snapshot of the text output for a kept job and a rejected job,
  with the LLM call mocked.
