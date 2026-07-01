# Recruitment Agency Filter — Design

**Date:** 2026-07-01
**Repo:** `job-search-email`
**Branch:** `feature/FE-015-recruitment`

## Problem

Recruitment agencies post jobs without naming the actual client/employer. Because the
approved-sponsor check verifies the *company that appears on the listing*, an agency posting
either (a) can't be verified against the sponsor list at all, or (b) passes falsely because the
*agency itself* is on the sponsor list — even though the real employer (the undisclosed client)
is unknown. Either way the sponsor guarantee is meaningless for agency-posted jobs, so they
should be removed.

## Goal

Add a standalone, independently toggleable filter that rejects jobs posted by recruitment
agencies, before the sponsor check runs.

## Non-Goals

- Keyword/substring matching on tell-tale words (e.g. "resourcing", "talent"). Considered and
  dropped in favour of a curated name list plus Reed's flag.
- Detecting the true client behind an agency posting.
- Any change to scoring or email rendering.

## Detection

A job is treated as posted by a recruiter if **any** of:

1. **Reed API flag** — the Reed search item has `postedByRecruitmentAgency == true`. Only
   Reed-sourced jobs carry this signal.
2. **Name match** — the job's company name matches an entry in
   `assets/recruitment_agencies.csv` (see Matching below).

NHS-sourced jobs are skipped entirely — they are direct employers.

## Matching

The name list is `assets/recruitment_agencies.csv` — a single column with header
`Organisation Name` (same header as `sponsor_cache.csv`), ~66.7k UK recruiter legal names
(carrying `LTD`/`LIMITED` suffixes).

Mirror the sponsor filter's proven mechanism:

- `load_recruitment_set(csv_path)` reads each row, normalizes it with the sponsor filter's
  `_normalize` (strips `t/a`, legal suffixes like `Ltd`/`plc`/`llp`, punctuation; lowercases;
  collapses whitespace), and expands prefixes via the sponsor filter's `_build_entries` so a long
  legal name still matches a shorter job company. Returns a `frozenset[str]`.
- `_check_recruitment(job, recruitment_set)` normalizes the job's company and tests **both** the
  full normalized company **and its own word-prefixes** against the set — because a recruiter's
  legal name can carry extra trailing words the job posting omits. Any hit → reject.

The existing 2-word / 8-char prefix guard (reused from the sponsor filter) keeps generic short
prefixes (e.g. `"1 force"`) from causing false positives. Lookups are O(1) set membership; 66.7k
entries is fine.

## Pipeline Placement

`_check_recruitment` is a standalone check in `filter.py`, added to the `filter_jobs` chain
**immediately before the sponsor check**:

```
location → employment_type → role → nhs_band → recruitment → sponsor → keep
```

It runs before sponsor deliberately: a recruiter may itself be on the sponsor list and pass the
sponsor check falsely, so it must be caught first with the accurate reason.

**Reject reason:** `"recruitment agency — client company not disclosed, cannot verify sponsor"`

## Toggle

A single flag controls the whole filter (name match **and** Reed flag), mirroring the existing
`sponsor_set` pattern:

- `filter_jobs` gains an optional arg `recruitment_set: frozenset[str] | None = None`.
- `_check_recruitment` returns `None` (skip) when the set is `None`.
- In `main.py`:
  `recruitment_set = load_recruitment_set(RECRUITMENT_CACHE_PATH) if profile.filter_recruitment else None`,
  passed into `filter_jobs`.
- New path constant: `RECRUITMENT_CACHE_PATH = ROOT / "assets" / "recruitment_agencies.csv"`.

Config lives in `profile.yaml` as `filter_recruitment: true` (default **ON**).

## Data Model Changes

**`JobListing`** (`models.py`) gains a trailing, defaulted field (backward compatible):

```python
posted_by_agency: bool | None = None
```

- `reed.py` `_to_listing` sets it from `item.get("postedByRecruitmentAgency")`.
- jobspy / nhs sources leave it `None` (no such signal).
- Serializes into `job_results.json` via `asdict` — additive, no consumer breakage.

**`Profile`** (`models.py`) gains `filter_recruitment: bool = True`; `load_profile` reads
`data.get("filter_recruitment", True)`. `profile.yaml` gets the `filter_recruitment: true` line.

## New Files / Modules

- `assets/recruitment_agencies.csv` — already created (66.7k rows, header `Organisation Name`).
- `src/job_search_email/recruitment_filter.py` — standalone module holding
  `load_recruitment_set`, reusing `_normalize` / `_build_entries` from `sponsor_filter.py`.
  (`_check_recruitment` lives in `filter.py` alongside the other `_check_*` functions, matching how
  `_check_sponsor` and `load_sponsor_set` are split today.)

## Edge Cases

- Blank company but Reed agency flag `true` → still rejected (flag alone suffices).
- NHS-sourced jobs → skipped.
- Toggle off (`recruitment_set is None`) → check is a no-op; Reed flag ignored too.
- Company matches a listed agency **and** would also fail sponsor → rejected as recruitment
  (runs first), giving the more accurate reason.

## Testing (TDD)

- `load_recruitment_set`: parsing, normalization, prefix-entry expansion, blank-row skipping.
- `_check_recruitment`: Reed flag reject; exact name match; prefix match (long legal name vs short
  company and vice-versa); non-match passes; NHS skip; `None`-set skip; blank-company + flag reject.
- `filter_jobs` integration: recruitment rejected before sponsor; still ordered after
  employment/role/nhs checks; toggle-off no-op.
- `reed.py`: `_to_listing` populates `posted_by_agency` from the API field.
- `load_profile`: reads `filter_recruitment`, defaults `True` when absent.
