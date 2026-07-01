# Local Debug Run + Job Lookup for explain-job

**Date:** 2026-06-29
**Status:** Approved design, ready for planning

## Problem

`explain-job` (the rating diagnostic) can replay the filter and scorer logic for
a single job, but it has no faithful way to obtain the **input the pipeline
actually saw** for a LinkedIn/Indeed job. Those URLs cannot be re-fetched
reliably, so the current fallback is a hand-written `--job-file`. That defeats
the purpose when the suspected bug is in how the pipeline *parsed* the listing
(e.g. a mis-detected `employment_type`): typing the field in by hand masks the
very bug under investigation.

The production pipeline runs on GitHub Actions and emails the results; the
developer debugs locally and has none of that run's data.

## Goal

Let the developer **recreate the whole workflow locally** — the real fetch →
filter → score pipeline, minus the email — and then inspect, for any one job,
why it got its rating and exactly what data produced it.

Key realisation: every fetcher (including jobspy for LinkedIn/Indeed) is local
Python. Running the pipeline locally therefore parses each listing with its
*real* `employment_type`, `salary`, and `description` — no GitHub artifacts, no
scraping, no `gh` tooling required.

### Non-goals

- Reproducing the exact GitHub run that produced a specific email. A local run
  is a fresh run; a given job/rating can differ day-to-day as listings change.
  The goal is faithful logic and faithful *local* inputs, not byte-matching a
  past email.
- Sending or previewing email. The debug command never emails.

## Shape

Two steps: recreate once, explain many.

1. **Debug command** (`job-search-debug`): runs the real pipeline and emits
   the decisions — never an email. Writes the run data to disk and a local
   decisions report.
2. **Enhanced `explain-job`**: reads that local run data as its primary source,
   replays one job's trace, and can dump the exact `JobListing` used.

Recreating is the expensive part (real fetch + up to 100 LLM scores); the
developer does it once, then runs `explain-job` against the saved data as many
times as needed, cheaply.

## Component 1: `job-search-debug` command

A new console-script entry point that runs the identical pipeline as production
up to (but not including) the email.

### Pipeline reuse (refactor)

`main.main()` currently inlines the whole pipeline (load profile → fingerprint
→ plan → fetch → classify locations → filter → score → email). Extract the
fetch-through-score portion into a reusable function so the debug command and
production share one code path (DRY):

```python
def run_pipeline(profile: Profile) -> tuple[dict[str, str], list[ScoredResult]]:
    """Run fetch -> classify -> filter -> score; write run-data files; return
    (location_classification, scored_results). No email side effects."""
```

`run_pipeline` writes `job_results.json` and `job_results_scored.json` (as
`main` does today) and returns the location `classification` dict and the
`scored` list. `main.main()` is refactored to call `run_pipeline` and then do
its email steps; its observable behaviour is unchanged.

### Debug command behaviour

`job-search-debug`:
1. loads the profile (`load_profile`),
2. calls `run_pipeline(profile)`,
3. writes the decisions report to `debug_report.html` in the repo root, using
   the existing `build_debug_email_html(classification, scored, profile)` (the
   same content the debug email would have contained) — written, not sent,
4. prints a concise decisions summary to the terminal: kept jobs with score,
   rejected jobs with reject reason, and the output file paths,
5. never calls `send_email` or `send_debug_report`.

## Component 2: explain-job run-data lookup

`explain-job` gains a local-run-data lookup as its **primary** resolution
source, ahead of live fetching.

### Resolution precedence

1. `--job-file PATH` → explicit manual override (unchanged).
2. **Local run data** → find the URL in `job_results.json` (default repo-root
   path; `--run-data PATH` overrides). Returns the stored `JobListing`. Works
   for **all** sources, so a LinkedIn/Indeed job present in the run data now
   resolves with its real parsed `employment_type` and needs no `--job-file`.
3. Live fetch (Reed API / NHS scrape) → fallback when the URL is not in the run
   data (unchanged behaviour for those sources).
4. `UnsupportedSourceError` → message updated to suggest running
   `job-search-debug` first, or passing `--job-file`.

URL matching is exact first, then a normalised comparison (strip trailing slash
and query string) to absorb trivial differences.

### Run-data loader

A small function reads `job_results.json` (a JSON list of `JobListing` dicts,
the format `main`/`run_pipeline` already writes) and returns a
`dict[url, JobListing]` for lookup. Missing file → a clear error from the
resolver path telling the developer to do a debug run.

### Staleness note

When a job is resolved from run data, the trace header notes the age of
`job_results.json` (from its file mtime), so the developer knows whether they
are looking at a fresh run or stale data.

## Component 3: dump the job data

Add `--dump-job-file PATH` to `explain-job`. After resolving the job, write the
`JobListing` as a `--job-file`-format YAML (all fields, full description). This
lets the developer see exactly what data drove the rating and re-run with tweaks
(e.g. change `employment_type` and watch the gate flip). The dumped file
round-trips: loading it back via `load_job_file` yields an equal `JobListing`.

## Error handling

- `job_results.json` missing when run-data lookup is attempted and no live-fetch
  source matches: clear message — "no local run data; run `job-search-debug`
  first, or pass `--job-file`".
- The debug command surfaces missing `REED_API_KEY` / `ANTHROPIC_API_KEY` the
  same way the real pipeline does (the underlying fetchers/scorer already fail
  with clear messages).
- `--dump-job-file` write failure (bad path): surfaced as a clear error.

## Testing

- **`run_pipeline` extraction:** `main.main()` still emails per profile flags
  (existing main tests stay green); `run_pipeline` writes both JSON files and
  returns `(classification, scored)`. Network/LLM mocked.
- **Debug command:** runs `run_pipeline`, writes `debug_report.html`, prints a
  decisions summary, and never calls `send_email`/`send_debug_report` (assert
  not called). Mocked pipeline.
- **Run-data lookup:** URL present → stored `JobListing` returned; absent →
  falls through to live fetch; `--job-file` still wins; exact and normalised URL
  match; missing-file error.
- **explain-job precedence:** a LinkedIn URL present in run data resolves
  without `--job-file` and carries the stored `employment_type`.
- **`--dump-job-file`:** dumped YAML reloads via `load_job_file` to an equal
  `JobListing`.
- **Staleness note:** rendered with a known mtime.
