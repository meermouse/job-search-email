# Detect "FTC" as Fixed-Term

**Date:** 2026-06-30
**Status:** Approved design, ready for planning

## Problem

A Deloitte role posted on Indeed (jk=5a88fb2e2626b4ae) reached the email even
though its listing states *"Job Type: Permanent / FTC"* — FTC = fixed-term
contract — which the candidate (permanent-only) does not want. The
`explain-job` diagnostic showed exactly why it slipped through all three
employment-type checks:

1. **No structured type.** jobspy returned `employment_type = None` for the
   listing, so `_check_employment_type` treated it as *unknown* — which passes
   with an `employment_type_unknown` flag, not a rejection.
2. **Regex didn't know "FTC".** `_CONTRACT_PATTERNS` matches the spelled-out
   "fixed term" (and "temporary contract", "maternity cover", etc.) but has no
   entry for the abbreviation **FTC**, so the description scan missed it.
3. **LLM backstop accepted it.** The scorer saw "Permanent / FTC", reasoned a
   permanent option exists ("Permanent option available"), set `exclude=false`,
   and scored it 8.

## Decision

A posting that mentions FTC or fixed-term **at all** — even alongside a
permanent option — must be rejected. The candidate wants guaranteed-permanent
roles; a dual "Permanent / FTC" listing does not guarantee that.

## Fix

Two layers, mirroring the existing design (a deterministic filter as the
guarantee, the LLM as a backstop). Either alone catches this job; together they
are robust to variants.

### Layer 1 — deterministic filter (primary)

In `src/job_search_email/filter.py`, add `\bftc\b` to `_CONTRACT_PATTERNS`. That
pattern is already compiled with `re.IGNORECASE` and scanned against
`f"{job.title} {(job.description or '')[:500]}"` inside `_check_employment_type`.
"Job Type: Permanent / FTC" sits at the top of the description (well within 500
chars), so this rejects the job deterministically with the existing reason
`"description contains contract indicators"`. The `\b` word-boundaries prevent
matching "ftc" embedded inside other words.

### Layer 2 — LLM backstop (defense in depth)

In `src/job_search_email/scorer.py` `_build_system_prompt`, extend the exclusion
instructions to state: **"FTC" means fixed-term contract; a posting that offers
fixed-term as a possibility — including dual "Permanent / FTC" listings — is not
a guaranteed permanent role, so set `exclude=true`** (with a short
`exclude_reason` such as "Fixed-term contract (FTC)"). This covers cases where
the abbreviation appears beyond the 500-char regex window, or is phrased in a way
the regex misses.

## Scope notes

- The existing 500-char cap on the description scan is kept; the "Job Type" line
  is always near the top, and the LLM layer covers anything deeper. Not widening
  it, to avoid new false positives.
- No change to how a structured `employment_type` of `None` is handled (still a
  non-rejecting "unknown" flag) — the FTC signal in the description is what now
  drives the rejection.

## Testing

- **Filter (`tests/test_filter.py`):**
  - A job with `employment_type=None` and a description containing
    "Permanent / FTC" → `rejected` with reason "description contains contract
    indicators".
  - "FTC" appearing in the title → rejected.
  - A normal permanent job with no FTC token (and no other contract indicator) →
    **not** rejected (guards against false positives; e.g. "ftc" inside another
    word does not trigger).
- **Scorer (`tests/test_scorer.py`):**
  - `_build_system_prompt` output contains the FTC / fixed-term-contract
    exclusion guidance. (The exclude→reject pipeline is already covered by
    existing scorer tests.)
