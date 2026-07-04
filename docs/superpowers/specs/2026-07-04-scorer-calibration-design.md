# Scorer Calibration + Prompt-Versioned Score Cache — Design

**Date:** 2026-07-04
**Status:** Approved

## Problem

The AI scorer rates jobs primarily on skills overlap. For the AECOM "Business
Architect & Org Design Lead" job (Indeed `jk=409e1c39c8400a00`) it returned
7/10 despite the candidate lacking the requirement that would realistically
screen them out at that grade: a fee-earning / business-development track
record for an Associate Director consultancy role. A manual assessment rated
it 6/10 for exactly that reason, and the user agreed with the manual
assessment. The scorer should weight *gatekeeping* requirements — ones a
hiring manager screens on at the role's stated seniority — more heavily than
raw skills overlap.

A second, coupled problem: the score cache key (`cache.make_score_key`) is
built only from the job URL and the profile fingerprint. Changing the scorer
prompt does not invalidate cached scores, so previously scored jobs would keep
their old ratings indefinitely and the calibration change would silently not
take effect for them.

## Change 1: Calibration instruction in the scorer system prompt

In `_build_system_prompt` (`src/job_search_email/scorer.py`), immediately
after the existing score-guidance sentence ("8-10 = strong match … 1-4 =
weak…"), add:

> Calibration: the score must reflect the candidate's realistic odds of being
> shortlisted, not just breadth of skills overlap. Identify any requirement a
> hiring manager would treat as gatekeeping at the role's stated seniority —
> for example a fee-earning or business-development track record for senior
> consultancy grades, statutory registration, or prior budget ownership at
> director level. If the candidate lacks a gatekeeping requirement, the job is
> at best a partial match: score it 6 or below, however strong the remaining
> overlap.

The existing 8-10 / 5-7 / 1-4 band definitions are unchanged, so jobs without
gatekeeping gaps should not shift.

## Change 2: Prompt-versioned score cache key

In `src/job_search_email/cache.py`:

- Add `fingerprint_prompt(system_prompt: str) -> str` — sha256 hex digest of
  the prompt text, same shape as `fingerprint_profile`.
- Extend `make_score_key(url, profile_fingerprint, prompt_fingerprint)` to a
  required third argument, producing `{url_hash12}_{profile_fp12}_{prompt_fp12}`.

In `src/job_search_email/scorer.py`, `score_jobs` computes the prompt
fingerprint once (it already builds the system prompt before the cache loop)
and passes it at both `make_score_key` call sites (cache lookup and cache
store).

Because the system prompt embeds the rendered profile and search preferences,
any future change to prompt wording *or* profile rendering automatically
produces new cache keys and re-scores. Old cache entries never match again;
they linger in the JSON cache file harmlessly.

## Out of scope

- No change to the query-generation prompt (`queries.py`) — it finds jobs,
  it does not score them.
- No rewrite of the score bands (rejected as Approach 3: recalibrates every
  score at once, hard to attribute shifts).
- No cache-file pruning of orphaned entries.

## Testing

- Update existing `make_score_key` call sites in `tests/test_cache.py` and
  `tests/test_scorer.py` for the new three-argument signature.
- New tests:
  - key differs when the prompt fingerprint differs (same URL + profile fp);
  - `fingerprint_prompt` is deterministic and hex;
  - `_build_system_prompt` output contains the calibration instruction.
- End-to-end verification: re-run
  `explain-job --job-file <saved AECOM job YAML>` and confirm the score lands
  at ≤ 6 with a gatekeeping-related verdict.

## Expected side effect

The first pipeline run after this change re-scores every currently cached job
(up to `DEEP_ANALYSIS_LIMIT`, default 100) in one batch of Haiku calls — a
one-off API cost roughly equal to a normal run's scoring stage.
