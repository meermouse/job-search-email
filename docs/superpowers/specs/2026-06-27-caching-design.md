---
title: Caching Design — Avoid Duplicate Claude Calls
date: 2026-06-27
branch: feature/FE-008-caching
---

## Goal

Prevent duplicate Claude API calls across daily GitHub Actions runs. Two Claude call sites exist: query generation (one call per profile change) and job scoring (up to 20 calls per run). Query generation is already cached in `search_plan_cache.json` but the cache is never persisted between CI runs. Job scoring has no cache at all.

## Scope

- Add a per-job scoring cache (`job_score_cache.json`)
- Persist both cache files across GitHub Actions runs via `actions/cache@v4`
- No changes to scoring logic, filtering, or email output

## Cache Files

Both files live at the repo root (matching existing convention):

| File | Purpose | Key |
|---|---|---|
| `search_plan_cache.json` | Caches query generation output | `profile_fingerprint` (full SHA-256) |
| `job_score_cache.json` | Caches per-job Claude analysis | `{url_sha256[:12]}_{profile_fingerprint[:12]}` |

### Scoring cache entry structure

```json
{
  "a3f9c12b5e01_8d2e4f1a9c3b": {
    "score": 8,
    "matched_skills": ["Python", "Data Engineering"],
    "missing_essentials": [],
    "employment_type_note": "Permanent",
    "verdict": "Strong match"
  }
}
```

The composite key means a job's cached score is invalidated automatically when the profile changes — old scores from a different profile version are never reused.

## Python Changes

### New module: `src/job_search_email/cache.py`

Three functions:

- `load_score_cache(path: Path) -> dict` — reads JSON file; returns `{}` on missing file or `JSONDecodeError`
- `save_score_cache(cache: dict, path: Path) -> None` — writes atomically (temp file + rename) to avoid corruption on mid-run failure
- `make_score_key(url: str, profile_fingerprint: str) -> str` — builds the composite key

### Changes to `scorer.py`

`score_jobs()` gains a `score_cache: dict` parameter and a `cache_path: Path` parameter.

Before submitting jobs to the thread pool, each job is checked against `score_cache`. Cache hits bypass Claude entirely and are reconstructed as `ScoredResult` directly. Only misses enter the executor. After all futures resolve, the updated cache dict is written back once via `save_score_cache`.

`analysis_failed` results are **not** cached — failed analyses are retried on the next run.

### Changes to `main.py`

```python
SCORE_CACHE_PATH = ROOT / "job_score_cache.json"
```

`main()` loads the score cache before calling `score_jobs()` and passes both `score_cache` and `cache_path` through.

## GitHub Actions Workflow

Three new steps added to `.github/workflows/daily_job.yml`:

```yaml
- name: Get date
  id: date
  run: echo "date=$(date +'%Y-%m-%d')" >> $GITHUB_OUTPUT

- name: Restore cache
  uses: actions/cache@v4
  with:
    path: |
      search_plan_cache.json
      job_score_cache.json
    key: job-search-cache-${{ runner.os }}-${{ steps.date.outputs.date }}
    restore-keys: |
      job-search-cache-${{ runner.os }}-

- name: Save cache
  uses: actions/cache/save@v4
  if: always()
  with:
    path: |
      search_plan_cache.json
      job_score_cache.json
    key: job-search-cache-${{ runner.os }}-${{ steps.date.outputs.date }}
```

**Key strategy:** Daily key (`YYYY-MM-DD`) means each day creates a fresh cache entry. The `restore-keys` prefix means the previous day's cache is always restored as a starting point, so jobs that recur across days are not re-scored.

**`if: always()`** on the save step ensures partial scoring work is preserved even when the workflow fails mid-run.

## Error Handling

| Scenario | Behaviour |
|---|---|
| Cache file missing | `load_score_cache` returns `{}` — cold cache, normal run |
| Cache file corrupt | `JSONDecodeError` caught, returns `{}` — same as missing |
| Claude fails for a job | Result not written to cache; job is retried next run |
| Profile changes | Composite key changes for all jobs; old entries become unreachable (harmless dead weight) |

## Out of Scope

- Active cache pruning (file stays small at daily cadence)
- Caching raw job fetch results from job boards
- Caching filtered results
