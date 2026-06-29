# Sponsor Filter — Forward-Port with Reject-on-Missing-Company

**Date:** 2026-06-29
**Feature:** FE-012 — Approved Sponsor Filter (live integration)
**Branch:** `feature/FE-012-sponsor-filter`
**Status:** Approved
**Supersedes handling in:** [2026-06-27 FE-005 sponsor-filter design](../../../../job-search/docs/superpowers/specs/2026-06-27-sponsor-filter-design.md)

## Overview

The approved-sponsor filter (UK Government Worker-route register, `assets/sponsor_cache.csv`)
was fully built on the stale `feature/FE-005-sponsor-filter` branch but never merged. That
branch was cut from an old `main` (merge base `85943e4`) and a raw merge would regress the
location filter and the FE-006–FE-012 work. Instead we **forward-port** the sponsor-specific
pieces onto current `main` on a new branch, and change one behaviour: jobs whose company
cannot be verified (empty or too-ambiguous company name, e.g. recruitment-agency posts that
omit the represented employer) are now **rejected** rather than flagged-and-passed.

## Problem

Recruitment-posted jobs frequently omit the name of the company they represent. Under the
FE-005 design these were flagged `sponsor_unknown_company` and **passed**, so they could
reach the email despite being unverifiable against the sponsor register. The application's
core constraint is to only surface jobs from approved sponsors, so an unverifiable company
must be treated as **not meeting** the filter.

## Architecture

- New module `src/job_search_email/sponsor_filter.py` owns CSV loading and name normalization
  (ported verbatim from FE-005 — no behaviour change).
- `filter.py` gains `_check_sponsor` and threads a `sponsor_set` parameter through `filter_jobs`.
- `main.py` loads the sponsor set once before filtering and passes it in.

No new dependencies.

## Sponsor Set Construction (`sponsor_filter.py`)

Ported unchanged from FE-005:

- `_normalize(name)` — strip; remove `t/a …` trading-as clauses; strip trailing legal suffixes
  (`ltd`, `limited`, `plc`, `llp`, `llc`, `co`, `corp`, `corporation`, `inc`, `incorporated`);
  lowercase; remove punctuation (keep intra-word hyphens); collapse whitespace.
- `load_sponsor_set(csv_path) -> frozenset[str]` — reads `Organisation Name`, normalizes each,
  and adds every word-boundary prefix of **≥2 words AND ≥8 chars** (so
  `"bossmans retail abergavenny"` also contributes `"bossmans retail"`). Blank rows skipped.

## Per-Job Check (`filter.py`)

`_check_sponsor(job, sponsor_set) -> FilteredResult | None`, run **after** the existing
location → employment-type → role → NHS-band checks.

| Condition | Result |
|---|---|
| `job.source == "nhs"` | `None` — pass (NHS/public-health bodies are inherently sponsor-eligible) |
| company empty/None, **or** normalized `< 8` chars / `< 2` words | **REJECT**, `reject_reason="company not specified — cannot verify approved sponsor"` |
| normalized company in `sponsor_set` | `None` — pass |
| normalized company NOT in `sponsor_set` | **REJECT**, `reject_reason="company not on approved sponsor list"` |

**Change from FE-005:** the empty/too-short branch is now a rejection instead of a
flag-and-pass. The `sponsor_unknown_company` flag is removed. The rejection carries a
distinct `reject_reason` so these jobs remain **visible in the debug email** for auditing
(they appear in the `rejected` bucket, distinguishable from genuine "not on list" rejects).

`filter_jobs` gains `sponsor_set: frozenset[str] | None = None`; when `None` the sponsor check
is skipped (keeps existing tests and callers that don't pass a set working). Employment-type
`flags` continue to propagate to passing results as today.

## Integration (`main.py`)

- `SPONSOR_CACHE_PATH = ROOT / "assets" / "sponsor_cache.csv"`
- Before the filter step: `sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)` and print the
  entry count.
- `filter_jobs(jobs, plan, profile, rejected_locations=rejected_locations, sponsor_set=sponsor_set)`

Filter pipeline order within `filter_jobs`: location → employment type → role → NHS band →
**sponsor** (new).

## Pre-existing Bug Fixed Along the Way

The live NHS scraper tags jobs `source="nhs"` ([nhs_jobs.py:47](../../../src/job_search_email/search_api/nhs_jobs.py)),
but `fixtures.py` uses `source="nhs_jobs"`. The NHS bypass keys on `"nhs"`, so the real
pipeline is correct; tests must use `"nhs"`. Fixtures' `"nhs_jobs"` value is noted as a
mismatch (out of scope to change here unless it breaks a test).

## Testing

- Port `tests/test_sponsor_filter.py` (normalization + set construction).
- Filter tests: missing/empty company → rejected with the missing-company reason; short/
  one-word company → rejected; NHS-source job → passes without a sponsor lookup; listed
  sponsor → passes; unlisted real company → rejected with the "not on approved sponsor list"
  reason; `sponsor_set=None` → sponsor check skipped.

## Edge Cases

| Case | Handling |
|---|---|
| Recruitment agency post, no company named | Rejected (missing-company reason), still visible in debug email |
| Recruitment agency named but not a licensed sponsor | Rejected ("not on approved sponsor list") |
| NHS trust posting on LinkedIn/Indeed | `source` is not `"nhs"`; goes through normal sponsor lookup |
| NHS-source job | Bypassed via `source == "nhs"` |
| Company `None` / very short | Rejected (missing-company reason) |

## Out of Scope

- Fuzzy matching (the sibling `job-search` repo uses rapidfuzz; this repo stays exact-set).
- Changing `fixtures.py` `source` values.
- Network download of the sponsor CSV (the cached `assets/sponsor_cache.csv` is the source).
