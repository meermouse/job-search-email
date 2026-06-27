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

## GitHub Actions

The repository includes a workflow to run the app daily and on push.
