# Scorer Calibration + Prompt-Versioned Score Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI scorer weight seniority-level gatekeeping requirements over raw skills overlap, and version the score cache key by the scorer prompt so prompt changes automatically re-score.

**Architecture:** Two small changes. (1) `cache.py` gains `fingerprint_prompt` and `make_score_key` gains a required third argument, producing `{url12}_{profile12}_{prompt12}` keys; `score_jobs` in `scorer.py` passes the fingerprint of the system prompt it already builds. (2) `_build_system_prompt` gains a calibration paragraph after the score-guidance sentence. Spec: `docs/superpowers/specs/2026-07-04-scorer-calibration-design.md`.

**Tech Stack:** Python 3.11, pytest, `unittest.mock.patch` (existing test style — no live API calls in tests).

## Global Constraints

- Run tests with the project venv: `.venv\Scripts\python -m pytest <path> -q` from the repo root `c:\Code\job-search-email`.
- Tests must never call the live Anthropic API; follow the existing `patch("job_search_email.scorer.client", _mock_client())` pattern in `tests/test_scorer.py`.
- On Windows, `explain-job` output needs `$env:PYTHONIOENCODING='utf-8'` (cp1252 console can't print the report's box-drawing characters).
- End every commit message with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- The existing 8-10 / 5-7 / 1-4 score band definitions in the prompt must not change.

---

### Task 1: Prompt-versioned score cache key

The cache key currently ignores the scorer prompt, so prompt changes silently serve stale scores. Add a prompt fingerprint as a required third key component and wire it through `score_jobs`. This task changes `make_score_key`'s signature, which is used by `scorer.py` and two test files — all call sites are updated here so the suite is green at the end of the task.

**Files:**
- Modify: `src/job_search_email/cache.py:10-17`
- Modify: `src/job_search_email/scorer.py:11,213-234`
- Test: `tests/test_cache.py:61-101`
- Test: `tests/test_scorer.py:406,413,440,471,700,727` (+ one new test)

**Interfaces:**
- Consumes: existing `fingerprint_profile(profile: Profile) -> str` (sha256 hex, `cache.py`); existing `_build_system_prompt(profile: Profile) -> str` (`scorer.py`).
- Produces: `fingerprint_prompt(system_prompt: str) -> str` — 64-char sha256 hex digest of the prompt text. `make_score_key(url: str, profile_fingerprint: str, prompt_fingerprint: str) -> str` — returns `f"{sha256(url)[:12]}_{profile_fingerprint[:12]}_{prompt_fingerprint[:12]}"`. Task 3's verification relies on `score_jobs` keying the cache with all three parts.

- [ ] **Step 1: Update the `make_score_key` tests and add `fingerprint_prompt` tests in `tests/test_cache.py`**

Replace the four existing `make_score_key` tests (lines 61-84) with the following, and append the two `fingerprint_prompt` tests after `test_fingerprint_profile_is_hex_string` at the end of the file:

```python
def test_make_score_key_is_deterministic():
    key1 = make_score_key("https://example.com/job/1", "abc123fingerprint", "promptfp")
    key2 = make_score_key("https://example.com/job/1", "abc123fingerprint", "promptfp")
    assert key1 == key2


def test_make_score_key_differs_by_url():
    key1 = make_score_key("https://example.com/job/1", "fp", "pfp")
    key2 = make_score_key("https://example.com/job/2", "fp", "pfp")
    assert key1 != key2


def test_make_score_key_differs_by_fingerprint():
    key1 = make_score_key("https://example.com/job/1", "fp_a", "pfp")
    key2 = make_score_key("https://example.com/job/1", "fp_b", "pfp")
    assert key1 != key2


def test_make_score_key_differs_by_prompt_fingerprint():
    key1 = make_score_key("https://example.com/job/1", "fp", "prompt_fp_a")
    key2 = make_score_key("https://example.com/job/1", "fp", "prompt_fp_b")
    assert key1 != key2


def test_make_score_key_format():
    key = make_score_key("https://example.com/job/1", "abcdef123456789", "9876543210fedcba")
    parts = key.split("_")
    assert len(parts) == 3
    assert len(parts[0]) == 12
    assert len(parts[1]) == 12
    assert len(parts[2]) == 12
```

```python
def test_fingerprint_prompt_is_deterministic():
    assert fingerprint_prompt("some prompt") == fingerprint_prompt("some prompt")


def test_fingerprint_prompt_changes_with_text_and_is_hex():
    fp1 = fingerprint_prompt("prompt A")
    fp2 = fingerprint_prompt("prompt B")
    assert fp1 != fp2
    assert len(fp1) == 64
    int(fp1, 16)  # raises ValueError if not valid hex
```

Also extend the import at the top of `tests/test_cache.py` (lines 6-11):

```python
from job_search_email.cache import (
    fingerprint_profile,
    fingerprint_prompt,
    load_score_cache,
    make_score_key,
    save_score_cache,
)
```

- [ ] **Step 2: Run the cache tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_cache.py -q`
Expected: FAIL — `ImportError: cannot import name 'fingerprint_prompt'`.

- [ ] **Step 3: Implement `fingerprint_prompt` and the three-part key in `src/job_search_email/cache.py`**

Replace lines 15-17 (the current `make_score_key`) with:

```python
def fingerprint_prompt(system_prompt: str) -> str:
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


def make_score_key(url: str, profile_fingerprint: str, prompt_fingerprint: str) -> str:
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{url_hash}_{profile_fingerprint[:12]}_{prompt_fingerprint[:12]}"
```

- [ ] **Step 4: Run the cache tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_cache.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Update the scorer cache tests in `tests/test_scorer.py`**

Extend the mid-file import on line 406:

```python
from job_search_email.cache import load_score_cache, make_score_key, fingerprint_profile, fingerprint_prompt
```

(`_build_system_prompt` is already imported at the top of the file, line 9.)

There are five occurrences of the two-argument call, at lines 413, 440, 471, 700, and 727, each reading:

```python
    key = make_score_key(job.url, fp)
```

Replace every occurrence with:

```python
    key = make_score_key(job.url, fp, fingerprint_prompt(_build_system_prompt(profile)))
```

Then add this new test immediately after `test_score_jobs_cache_hit_without_exclude_fields_defaults_to_kept` (ends line 744):

```python
def test_score_jobs_prompt_change_invalidates_cache():
    # A cache entry keyed under a different prompt fingerprint must be a miss:
    # the job is re-scored by Claude instead of served from cache.
    job = make_job(url="https://example.com/stale-prompt")
    profile = make_profile()
    fp = fingerprint_profile(profile)
    stale_key = make_score_key(job.url, fp, "0" * 64)
    score_cache = {stale_key: {
        "score": 9,
        "matched_skills": [],
        "missing_essentials": [],
        "employment_type_note": "Permanent",
        "verdict": "Stale cached verdict",
    }}
    results = [make_kept(job)]
    m = _mock_client()
    with patch("job_search_email.scorer.client", m):
        scored = score_jobs(results, profile, score_cache=score_cache)
    m.messages.create.assert_called_once()
    assert scored[0].analysis.verdict != "Stale cached verdict"
    current_key = make_score_key(job.url, fp, fingerprint_prompt(_build_system_prompt(profile)))
    assert current_key in score_cache
```

- [ ] **Step 6: Run the scorer tests to verify the new test fails**

Run: `.venv\Scripts\python -m pytest tests/test_scorer.py -q`
Expected: FAIL — the cache-hit tests and the new test raise `TypeError: score_jobs ... make_score_key() missing 1 required positional argument: 'prompt_fingerprint'` (scorer.py still calls it with two arguments).

- [ ] **Step 7: Wire the prompt fingerprint through `score_jobs` in `src/job_search_email/scorer.py`**

Change the import on line 11:

```python
from .cache import fingerprint_profile, fingerprint_prompt, make_score_key, save_score_cache
```

After `system_prompt = _build_system_prompt(profile)` (line 213), add:

```python
    prompt_fp = fingerprint_prompt(system_prompt)
```

Change the cache-lookup call (line 218):

```python
        key = make_score_key(r.job.url, profile_fp, prompt_fp)
```

Change the cache-store call (line 234):

```python
                score_cache[make_score_key(r.job.url, profile_fp, prompt_fp)] = asdict(analysis)
```

- [ ] **Step 8: Run the full test suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 9: Commit**

```powershell
git add src/job_search_email/cache.py src/job_search_email/scorer.py tests/test_cache.py tests/test_scorer.py
git commit -m @'
feat: version score cache key by scorer prompt fingerprint

Prompt changes previously served stale cached scores forever; the key
is now {url}_{profile_fp}_{prompt_fp} so any prompt or profile-rendering
change re-scores automatically.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: Calibration instruction in the scorer system prompt

Add the spec's calibration paragraph to `_build_system_prompt` so gatekeeping requirements (e.g. a business-development track record at senior consultancy grade) cap the score at 6, regardless of skills overlap.

**Files:**
- Modify: `src/job_search_email/scorer.py:44-46`
- Test: `tests/test_scorer.py` (one new test; `_build_system_prompt` and `make_profile` already available in the file)

**Interfaces:**
- Consumes: `_build_system_prompt(profile: Profile) -> str` (`scorer.py`, imported in `tests/test_scorer.py:9`); `make_profile(**kwargs) -> Profile` test helper (defined near the top of `tests/test_scorer.py`).
- Produces: the system prompt contains a paragraph starting `"Calibration: "` between the score-guidance sentence and the qualification-analysis instructions. Task 3 relies on this being live for `explain-job`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scorer.py`, next to the existing `_build_system_prompt` tests (search the file for `_build_system_prompt` assertions; if none exist beyond the import, add it after the `JobAnalysis` field tests near the top):

```python
def test_system_prompt_contains_calibration_instruction():
    prompt = _build_system_prompt(make_profile())
    assert "Calibration: " in prompt
    assert "gatekeeping" in prompt
    assert "score it 6 or below" in prompt
    # calibration must sit with the score guidance, before qualification analysis
    assert prompt.index("Score guidance:") < prompt.index("Calibration: ") < prompt.index("Qualification analysis instructions:")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_scorer.py::test_system_prompt_contains_calibration_instruction -q`
Expected: FAIL — `AssertionError` on `"Calibration: " in prompt`.

- [ ] **Step 3: Add the calibration paragraph to `_build_system_prompt`**

In `src/job_search_email/scorer.py`, replace lines 44-46:

```python
        "Score guidance: 8-10 = strong match (profile clearly fits). "
        "5-7 = partial match (relevant but gaps present). "
        "1-4 = weak (missing essentials or significant misalignment).\n\n"
```

with:

```python
        "Score guidance: 8-10 = strong match (profile clearly fits). "
        "5-7 = partial match (relevant but gaps present). "
        "1-4 = weak (missing essentials or significant misalignment).\n\n"
        "Calibration: the score must reflect the candidate's realistic odds of "
        "being shortlisted, not just breadth of skills overlap. Identify any "
        "requirement a hiring manager would treat as gatekeeping at the role's "
        "stated seniority — for example a fee-earning or business-development "
        "track record for senior consultancy grades, statutory registration, or "
        "prior budget ownership at director level. If the candidate lacks a "
        "gatekeeping requirement, the job is at best a partial match: score it "
        "6 or below, however strong the remaining overlap.\n\n"
```

The score bands themselves are unchanged.

- [ ] **Step 4: Run the full test suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (all tests, including Task 1's — the prompt-fingerprint plumbing recomputes per call, so the prompt text change does not break any key assertions).

- [ ] **Step 5: Commit**

```powershell
git add src/job_search_email/scorer.py tests/test_scorer.py
git commit -m @'
feat: calibrate scorer to weight gatekeeping requirements over skills overlap

Jobs whose stated seniority implies a hard screen the candidate lacks
(e.g. BD track record at consultancy Associate Director grade) now cap
at 6/10 instead of scoring on skills overlap alone.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: End-to-end verification against the AECOM job

Replay the job that motivated the change through `explain-job` and confirm the score drops from 7 to ≤ 6 with a gatekeeping-related verdict. This makes live LLM calls, so `ANTHROPIC_API_KEY` must be available (the repo's `.env` provides it).

**Files:**
- Create: `C:\Users\Marc\AppData\Local\Temp\claude\c--Code-job-search-email\3569581c-2d4c-4ae7-aadb-1aeb9cf8c7a7\scratchpad\aecom-job.yaml` (recreate if missing — full content below; it is a scratchpad file, not committed)

**Interfaces:**
- Consumes: the `explain-job` console script (installed in `.venv`); Task 2's calibration prompt.
- Produces: verification evidence only — no source changes.

- [ ] **Step 1: Ensure the job file exists**

If the scratchpad file above is missing, recreate it with exactly this content:

```yaml
title: Business Architect & Org Design Lead
company: AECOM
location: Bristol
salary_min: null
description: |
  AECOM seeks an Associate Director-level consultant to lead strategy and
  organizational transformation engagements. The role combines hands-on problem
  solving, senior stakeholder management, team leadership with business
  development responsibilities. Hybrid working.

  Key Responsibilities:
  - Direct complex consulting projects from initial scoping through completion
  - Design methodologies for operating model development, governance, and transformation work
  - Establish trusted relationships with senior client stakeholders
  - Translate analysis into executive recommendations and implementation roadmaps
  - Facilitate workshops and coordinate cross-functional teams
  - Coach junior consultants and support team development
  - Identify follow-on business opportunities

  Required Qualifications:
  - Management consulting, advisory, or strategy/operational improvement background
  - Proven ability leading teams on complex, ambiguous problems
  - Strong executive communication and stakeholder management skills
  - Experience developing target operating models, capability maps, governance structures
  - Pragmatic, results-focused approach
  - Bachelor's degree minimum; postgraduate qualification advantageous

  Additional: In-person Day 1 onboarding at an AECOM office is mandatory for new hires.
url: https://uk.indeed.com/viewjob?jk=409e1c39c8400a00
source: indeed
employment_type: fulltime
```

- [ ] **Step 2: Run explain-job against it**

Run (PowerShell, from the repo root):

```powershell
$env:PYTHONIOENCODING='utf-8'; & .venv\Scripts\explain-job.exe --job-file "C:\Users\Marc\AppData\Local\Temp\claude\c--Code-job-search-email\3569581c-2d4c-4ae7-aadb-1aeb9cf8c7a7\scratchpad\aecom-job.yaml"
```

Expected: all six hard filters pass (as before), and the AI SUITABILITY section shows **Score: 6/10 or lower**, with a verdict citing the missing consulting business-development / fee-earning track record. The system prompt echoed in the "LLM CALL (verbatim)" section must contain the `Calibration:` paragraph.

LLM output is not fully deterministic. If the score comes back 7 or higher, do NOT tweak the prompt wording ad hoc — stop and report the actual output for review.

- [ ] **Step 3: Confirm the suite is still green and report**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS. Report the explain-job score and verdict verbatim as the task's evidence. No commit (nothing in the repo changes in this task).
