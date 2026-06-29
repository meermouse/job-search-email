# Employment-Type False Positives & LLM Suitability Backstop

**Date:** 2026-06-29
**Feature:** FE-013 — Debug bad matches
**Branch:** `feature/FE-013-debug-bad-matches`
**Status:** Approved

## Overview

False positives are reaching the email: jobs that should have been filtered out but
weren't. The trigger case is an Indeed post
([example](https://uk.indeed.com/viewjob?jk=64c4347b587a0148)) labelled **both**
"Permanent" and "Fixed term contract". It should be treated as fixed-term and rejected.

This exposes two problems, addressed as two layers of one defense:

1. **Layer 1 (deterministic):** the employment-type check honors a `permanent`/`full-time`
   tag *before* scanning the description, so a disqualifying signal in the description is
   never seen. Reject indicators must win over pass indicators.
2. **Layer 2 (LLM backstop):** the existing per-job LLM analysis stage should also act as a
   safety net, excluding jobs that slip past the cheap deterministic filters because the
   relevant information only appears in the full description ("new information"). The LLM
   may exclude on any clear unsuitability — hard-constraint violations *and* poor fit.

The deterministic fix lands first and stands alone; the LLM net catches what rules miss.

## Problem

### Layer 1
`_check_employment_type` ([filter.py:32-45](../../../src/job_search_email/filter.py#L32-L45))
returns *pass* immediately when the structured `employment_type` field is exactly
`"permanent"` or `"full-time"` (the `_PASS_TYPES` branch), **before** the description is
scanned for contract indicators. The description scan only runs for *unknown* types. So a
job tagged `permanent` whose description says "fixed term contract" passes. Reject
indicators currently lose to pass indicators.

The structured field can also arrive as a combined Indeed string such as
`"Permanent, Fixed term contract"` (jobspy's `job_type` is lower-cased and passed through
`_normalise_job_type`, which only maps a fixed set of single tokens). Such a combined value
is neither in `_PASS_TYPES` nor `_REJECT_TYPES`, so today it falls through to the
description scan — but the scan text is the title+description, not the type field itself.

### Layer 2
The cheap filters operate on a capped slice of the description and structured fields. Some
disqualifying or clearly-unsuitable details only surface in the full description. There is
currently no second line of defense: anything the rules pass goes to the email (subject to
ranking). The LLM already reads up to 2500 chars of the description but only produces a
score and notes — it cannot drop a job.

## Architecture

Three touchpoints, no new dependencies:

- `filter.py` — reorder `_check_employment_type` so reject signals are evaluated before
  pass signals, scanning a combined text built from the employment-type field **and**
  title+description. Extend `_CONTRACT_PATTERNS` to catch the bare "fixed term"/"fixed-term"
  phrase.
- `models.py` / `scorer.py` — add `exclude` / `exclude_reason` to `JobAnalysis`; prompt the
  LLM to set them; in `score_jobs`, convert an `exclude=true` analysis into a rejected
  `ScoredResult` (analysis retained).
- `debug_email.py` / `main.py` — switch the debug builder to consume `list[ScoredResult]`
  and add an AI-suitability section so LLM exclusions are auditable.

## Layer 1 — Employment-Type Precedence Fix (`filter.py`)

Rewrite `_check_employment_type` with this order:

1. **Build combined text** from the employment-type field plus title plus the description
   (description capped at 500 chars, matching today's scan budget):
   `combined = f"{job.employment_type or ''} {job.title} {(job.description or '')[:500]}"`.
   The employment-type field is included in the scanned text so combined strings like
   `"Permanent, Fixed term contract"` are caught by the pattern scan, not just by exact-set
   membership.
2. **Reject first:**
   - if the normalized `employment_type` is in `_REJECT_TYPES` → reject, reason
     `"employment type: {et}"`.
   - else if `_CONTRACT_PATTERNS` matches the combined text → reject, reason
     `"description contains contract indicators"`.
   This step now runs **even when** the structured type is `permanent`/`full-time`.
3. **Then pass:** if the normalized `employment_type` is in `_PASS_TYPES` → pass (no flags).
4. **Unknown:** pass with the existing `["employment_type_unknown"]` flag.

**Pattern change:** `_CONTRACT_PATTERNS` currently requires `fixed.?term` to be followed by
`contract|post|appointment`. Add a bare `fixed[\s-]?term` alternative so "Fixed term
contract", "fixed-term", and "fixed term" standing alone all match. Keep all existing
alternatives.

Reject reasons are unchanged strings so the existing debug Employment Type section
(`_employment_type_section`, which keys off `"employment type:"` and
`"description contains contract indicators"` prefixes) continues to display these without
modification.

## Layer 2 — LLM Suitability Backstop (`models.py`, `scorer.py`)

### Schema (`models.py`)
Add to `JobAnalysis`:

```python
exclude: bool = False
exclude_reason: str = ""
```

Defaults preserve backward compatibility: stale score-cache entries written before this
change load via `JobAnalysis(**cached)` with `exclude=False` (a missing flag never causes a
wrong drop).

### Prompt (`scorer.py`)
- `_build_user_message` adds two fields to the requested JSON:
  `"exclude": <true|false>` and `"exclude_reason": "..."`.
- `_build_system_prompt` gains an exclusion instruction block: set `exclude=true` when the
  job clearly fails a hard constraint the upstream filters are meant to enforce
  (non-permanent / fixed-term / contract / temporary employment type; salary clearly below
  the stated minimum; location clearly outside the candidate's area) **or** is clearly
  unsuitable for this candidate (wrong seniority, wrong domain, fundamentally different
  role). Otherwise `exclude=false` and let the 1-10 score rank the job. The full
  description is the source of the "new information" the cheap filters lacked.

### Parsing & application (`scorer.py`)
- `_analyse_job` reads `data.get("exclude", False)` and `data.get("exclude_reason", "")`
  into the `JobAnalysis`. (The existing `qualification_status == "mismatch"` score-cap
  behavior is retained.)
- In `score_jobs`, after an analysis is obtained for a kept result, if
  `analysis.exclude` is true the produced `ScoredResult` is marked
  `rejected=True, reject_reason=f"AI suitability: {analysis.exclude_reason}"`, with the
  `analysis` object **retained**. This applies to both freshly-analysed and cache-hit
  results.

Effects:
- The main email already filters to `not r.rejected and r.analysis is not None`
  ([email.py:54](../../../src/job_search_email/email.py#L54)), so excluded jobs drop out
  automatically.
- The distinct `"AI suitability:"` reason prefix keeps LLM exclusions separable from every
  deterministic reject prefix downstream.
- Only analysed jobs can be excluded; `beyond_cap` and `analysis_failed` results have no
  analysis and are untouched.

## Layer 3 — Debug Email Surfacing (`debug_email.py`, `main.py`)

`build_debug_email_html` currently receives `filtered` (`list[FilteredResult]`) and cannot
see LLM exclusions (which happen at the later scoring stage).

- Change `build_debug_email_html` to accept `list[ScoredResult]`. The existing location /
  employment / role / NHS / sponsor sections only read `job`, `rejected`, and
  `reject_reason`, all present on `ScoredResult`, so they keep working unchanged.
- Add `_ai_suitability_section`: a Title / Company / Score / Reason table listing every
  scored result rejected with a `"AI suitability:"` reason prefix (score read from the
  retained `analysis`). Append it to the section stack.
- `main.py` passes `scored` to `build_debug_email_html` instead of `filtered`.

**Consequence:** the debug summary `kept` / `rejected` counts now reflect post-LLM state
(LLM-excluded jobs move kept→rejected). This is intended — the debug email becomes the
complete picture of every drop, deterministic and AI. The main email is otherwise
unaffected.

## Testing

### Layer 1 — `tests/test_filter.py`
- `employment_type="permanent"` + description contains "fixed term contract" → **rejected**
  (the regression case).
- `employment_type="full-time"` + clean permanent description → **passes**.
- `employment_type="permanent"`, no contract signals anywhere → **passes**.
- combined `"Permanent, Fixed term contract"` in the type field → **rejected**.
- unknown type, clean description → passes with `employment_type_unknown` flag (unchanged).

### Layer 2 — `tests/test_scorer.py`
- `_analyse_job` parses `exclude` / `exclude_reason`; missing fields default to
  `False` / `""` (back-compat). LLM client stubbed/mocked — no live API call.
- `score_jobs`: analysis with `exclude=true` → `ScoredResult.rejected is True`,
  `reject_reason` starts with `"AI suitability:"`, `analysis` retained.
- `exclude=false` → unchanged kept behavior.

### Layer 3 — `tests/test_debug_email.py`
- builder accepts `list[ScoredResult]`; AI-suitability section renders excluded jobs;
  existing sections still render their respective rejects from `ScoredResult` input.

## Edge Cases

| Case | Handling |
|---|---|
| Indeed "Permanent, Fixed term contract" combined type | Rejected by pattern scan over the combined text |
| `permanent` tag, contract phrase only in description | Rejected (reject-first ordering) |
| Job beyond the analysis cap (`beyond_cap`) | No analysis → no LLM exclusion; kept/ranked as today |
| `analysis_failed` | No exclusion applied; existing failure flag stands |
| LLM `exclude=true` with empty reason | Reason renders as `"AI suitability:"` (blank detail); still excluded |
| Stale score-cache entry without `exclude` | Loads with default `exclude=False`; never wrongly drops |

## Out of Scope

- Score-threshold auto-dropping (explicit LLM `exclude` flag is the only Layer-2 mechanism).
- Passing `job_type` / employment-type filters to jobspy or Reed at fetch time.
- Changing the analysis cap, model, or caching key strategy.
- NHS jobs (no description fetched, so the LLM backstop has little to act on there).
