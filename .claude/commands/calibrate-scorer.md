---
description: Re-assess the top 5 scored jobs from a fresh test run and calibrate the scorer prompt
argument-hint: [profile-name]
---

# Calibrate the job scorer

You are auditing the AI job scorer against your own judgement, then fixing the
scorer prompt where it is miscalibrated. The profile stem is `$ARGUMENTS`; if
that is empty, use `jie-zhou`. All paths are relative to the repo root.

## 1. Fresh pipeline run

Run `job-search-debug --profile profiles/<stem>.yaml` (live scraping plus
Haiku scoring; requires `ANTHROPIC_API_KEY`; takes several minutes — use a
generous timeout and run it in the background if needed). If the run fails
(network, scraper, missing key), STOP and report the failure. Never analyse
stale run data silently.

## 2. Select the top 5

Read `runs/<stem>/job_results_scored.json`. It is an object with `kept` and
`rejected` arrays; `kept` is already sorted by `analysis.score` descending —
take its top 5 entries, the same ordering the email uses. Each entry's job
fields live under its `job` key, with the scorer's verdict alongside in
`analysis`. Skip any entry whose `analysis` is null (scoring failed) and note
it in the final summary. If fewer than 5 kept entries exist, use however many
there are and say so.

## 3. Blind re-assessment — anchoring discipline

Process the jobs ONE AT A TIME. For each job, read ONLY these fields from the entry's `job` object — `title`, `company`, `location`, `salary_min`, `employment_type`,
`description` — plus `profiles/<stem>.yaml`. Do NOT read the job's
`analysis` block yet.

Write down your own assessment first:

- your score (1–10) using the scorer's own bands: 8–10 strong match (would
  very likely survive the initial sift), 5–7 partial match (credible but real
  gaps), 1–4 weak (would not survive the sift);
- every gatekeeping requirement the candidate lacks (requirements a hiring
  manager screens on at the role's stated seniority);
- whether the job should have been excluded outright (not permanent, salary
  below minimum, wrong location, wrong profession);
- one or two sentences of reasoning.

Only after your assessment for that job is written down may you read its
`analysis` block and move to the comparison. Never read ahead to another
job's analysis either.

## 4. Compare and diagnose

For each job, compare your score with `analysis.score` and classify:

- **agree** — within ±1 and same exclude decision;
- **prompt gap** — the rubric in `_build_system_prompt`
  (`src/job_search_email/scorer.py`) does not cover this failure mode;
- **execution miss** — the rubric covers it but the scoring model misapplied
  it (a clarifying wording change may still help);
- **data problem** — truncated description, missing salary, scraper junk —
  not a prompt issue; flag it separately and do not propose prompt edits
  for it.

Remember `_parse_analysis` applies post-hoc caps (gatekeeping gaps cap the
score at 6; qualification mismatch caps it at 3) — account for these before
declaring a disagreement.

## 5. Propose

If every job is **agree**: report "no disagreements, no changes proposed",
write the summary (step 7, minus corpus entries), and stop. That is a valid,
useful outcome.

Otherwise, where disagreements share a pattern, draft a concrete edit to the
scorer system prompt in `_build_system_prompt`. Present to the user:

- the per-job verdict table (job, scorer's score, your score, diagnosis);
- the exact prompt wording you want to add or change, and why;
- a reminder that any system-prompt edit invalidates the score cache, so the
  next pipeline run re-scores everything up to `DEEP_ANALYSIS_LIMIT` — a
  one-off Haiku cost.

Ask for approval before touching any file. If the user declines, record the
analysis in the summary and stop.

## 6. Apply and verify (only after approval)

1. Edit `_build_system_prompt` in `src/job_search_email/scorer.py`.
2. Run `pytest` — the suite must pass (some tests assert on prompt content;
   update them only where the assertion is genuinely stale).
3. Save each disagreement job as a corpus case (step 7 format) BEFORE
   re-scoring, so the expectation is pinned.
4. Re-score every case file in `calibration/cases/` (including the new ones):
   `explain-job --job-file calibration/cases/<file> --profile profiles/<its
   calibration.profile>.yaml --force-score`
   (`--force-score` because explain-job replays the hard filters first and a
   case job might otherwise be rejected before scoring; each call makes live
   LLM calls, so this costs a few Haiku requests per case).
5. Compare each resulting score against the case's `expected_min` /
   `expected_max` bounds. A case outside its bounds is a REGRESSION: refine
   the edit or revert it and re-run this step. Never finish with a failing
   case in place.

## 7. Record and summarise

For each disagreement (regardless of whether a prompt edit was applied),
write `calibration/cases/<YYYY-MM-DD>-<job-slug>.yaml` — slug from the job
title, lowercase, hyphenated, ≤6 words. Build the YAML directly from the
entry's `job` fields in `job_results_scored.json` (do not re-fetch):

```yaml
title: ...
company: ...
location: ...
salary_min: ...
description: |
  ...full description...
url: ...
source: ...
employment_type: ...
calibration:
  profile: <stem>
  scored: <the score analysis.score gave this run>
  expected_max: <bound implied by your assessment>   # and/or expected_min
  reason: "<one line: why the original score was wrong>"
  date: <YYYY-MM-DD>
```

Use `expected_min`/`expected_max` bounds, not exact scores — Haiku wobbles
±1 between runs. Commit new case files together with any prompt edit.

Finish with a summary table: job, scorer score, your score, diagnosis,
action taken (prompt edited / case recorded / no change), plus any skipped
jobs and data problems.
