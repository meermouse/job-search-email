# Job Search Email

A minimal Python application that generates a structured job search plan from a hardcoded profile and caches the results.

## What it does

- loads a user profile from `profile.yaml`
- generates a structured search plan with:
  - 8 tailored search queries
  - exclusion keywords for clinical roles
  - employment type exclusion terms
  - NHS band floor rules
  - evaluator notes for scoring
- caches the plan in `search_plan_cache.json` keyed by a profile fingerprint
- writes the active plan to `search_plan.json`

## Setup

```powershell
python -m pip install --upgrade pip
pip install -e .
```

## Run locally

```powershell
job-search-email
```

## Explain a job's rating

`explain-job` is a local developer tool that answers "why did this job get the
rating it did?". Give it a job URL (the same URL from your results email) and it
replays the real filter and scorer pipeline for that one job, printing a
stage-by-stage trace: every hard-filter gate (location, employment type, role
suitability, NHS band salary, sponsor list), then the AI suitability score,
verdict, and the verbatim LLM prompt and raw response.

> Note: this runs the scorer fresh, so the score may differ slightly from the
> one in your email (LLM nondeterminism). The goal is to understand the decision
> logic, not to reproduce the exact number.

It makes live LLM calls (location classification and the scorer), so
`ANTHROPIC_API_KEY` must be set; `REED_API_KEY` is also needed to fetch Reed
jobs.

### Reed and NHS URLs (fetch automatically)

Just pass the URL. `profile.yaml` in the repo root is used by default.

```powershell
explain-job https://www.reed.co.uk/jobs/senior-project-manager/53819371
```

### LinkedIn and Indeed URLs (use --job-file)

LinkedIn and Indeed listings cannot be fetched reliably from their URL, so
passing one of those URLs alone fails with:

```
explain-job: cannot auto-fetch jobs from 'uk.indeed.com'; supply the job details with --job-file
```

This is expected. Copy the job's details into a small YAML file and pass it with
`--job-file` instead (the URL can be omitted):

```yaml
# linkedin-job.yaml
title: Senior Project Manager
company: Acme Industries Ltd
location: Bristol
salary_min: 65000          # integer, no £ or commas; omit if not stated
description: |
  Lead digital delivery across multiple teams. PRINCE2 required.
  Permanent, full-time. Stakeholder management, Agile, budgeting...
employment_type: permanent  # permanent | full-time | contract | part-time | ...
source: linkedin            # informational; shown in the trace header
```

```powershell
explain-job --job-file linkedin-job.yaml
```

All keys are optional, but `description`, `salary_min`, `location`, and
`employment_type` are what the filter gates and the AI scorer actually read — so
the more you fill in (especially the full `description`), the more faithful the
replay.

### Options

| Flag | Default | Purpose |
| --- | --- | --- |
| `<url>` | — | Job URL (omit only when using `--job-file`). |
| `--profile` | `profile.yaml` | Candidate profile to evaluate against. |
| `--job-file` | — | YAML job details; fallback for LinkedIn/Indeed. Takes precedence over the URL. |
| `--force-score` | off | Run the AI scorer even when a hard filter rejected the job ("what would the AI have said?"). |

## GitHub Actions

The repository includes a workflow to run the app daily and on push.
