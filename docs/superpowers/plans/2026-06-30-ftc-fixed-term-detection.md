# FTC Fixed-Term Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject job postings that mention "FTC"/fixed-term (including dual "Permanent / FTC" listings), which currently slip through to the email.

**Architecture:** Two independent layers matching the existing design — a deterministic regex addition to the employment-type filter (primary), and a strengthened exclusion instruction in the LLM scorer prompt (backstop).

**Tech Stack:** Python 3.11, `re`, `anthropic`, `pytest`.

## Global Constraints

- Python `>=3.11`; add no new dependencies.
- Any FTC / fixed-term mention rejects, even alongside a "permanent" option.
- The employment-type filter's description scan keeps its existing 500-char cap (`(job.description or "")[:500]`); do not widen it.
- `_CONTRACT_PATTERNS` is compiled once with `re.IGNORECASE`; the new token is case-insensitive and word-bounded (`\bftc\b`) so it never matches "ftc" inside another word.
- Tests mock all LLM calls; no test makes a real network/API call.

---

### Task 1: Filter recognises "FTC" (deterministic layer)

Add `\bftc\b` to `_CONTRACT_PATTERNS` so `_check_employment_type` rejects a job whose title or first 500 description chars contain the FTC token.

**Files:**
- Modify: `src/job_search_email/filter.py:13-24` (`_CONTRACT_PATTERNS`)
- Test: `tests/test_filter.py`

**Interfaces:**
- Consumes: existing `_check_employment_type(job) -> FilteredResult`, `make_job(**kwargs)` test helper (already in `tests/test_filter.py`).
- Produces: no new public symbols (regex content change only).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filter.py` (the `make_job` helper and `_check_employment_type` import already exist in this file):

```python
def test_check_employment_type_rejects_ftc_in_description():
    # Indeed "Job Type: Permanent / FTC" with no structured type — the real miss.
    job = make_job(
        employment_type=None,
        description="Basic information\nJob Type\nPermanent / FTC\nDate published 30-Jun-2026",
    )
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_check_employment_type_rejects_ftc_in_title():
    job = make_job(title="Project Manager (FTC)", employment_type=None, description="")
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_check_employment_type_ftc_requires_word_boundary():
    # "softclose" contains the substring f-t-c but is not the FTC token;
    # \bftc\b must NOT match it, so a permanent job is not falsely rejected.
    job = make_job(
        employment_type=None,
        description="The cabinet uses softclose hinges and aftercare support.",
    )
    result = _check_employment_type(job)
    assert result.rejected is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_filter.py::test_check_employment_type_rejects_ftc_in_description tests/test_filter.py::test_check_employment_type_rejects_ftc_in_title -v`
Expected: FAIL — both currently return `rejected=False` (the regex doesn't know "FTC"). The word-boundary test already passes.

- [ ] **Step 3: Add the pattern**

In `src/job_search_email/filter.py`, add a `\bftc\b` alternative to `_CONTRACT_PATTERNS`:

```python
_CONTRACT_PATTERNS = re.compile(
    r"fixed[\s\-]?term"
    r"|temporary (?:contract|post|role)"
    r"|contract basis"
    r"|maternity cover"
    r"|parental leave cover"
    r"|\d+[\s\-]month (?:contract|fixed)"
    r"|zero[\s\-]hours"
    r"|bank staff"
    r"|locum post"
    r"|\bftc\b",
    re.IGNORECASE,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_filter.py -v`
Expected: PASS — the two new rejection tests pass, the word-boundary test passes, and all existing filter tests stay green.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "fix: reject FTC (fixed-term) postings in employment-type filter"
```

---

### Task 2: Scorer prompt excludes FTC/dual postings (LLM backstop)

Strengthen the scorer's exclusion instructions so the LLM treats FTC / dual "Permanent / FTC" postings as non-permanent and sets `exclude=true`.

**Files:**
- Modify: `src/job_search_email/scorer.py` (`_build_system_prompt`, the "Exclusion instructions" block)
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: existing `_build_system_prompt(profile) -> str`, `make_profile()` test helper (already in `tests/test_scorer.py`).
- Produces: no new public symbols (prompt text change only).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scorer.py` (the `make_profile` helper already exists in this file):

```python
def test_system_prompt_contains_ftc_exclusion_guidance():
    from job_search_email.scorer import _build_system_prompt
    prompt = _build_system_prompt(make_profile())
    assert "FTC" in prompt
    assert "fixed-term contract" in prompt
    assert "Permanent / FTC" in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scorer.py::test_system_prompt_contains_ftc_exclusion_guidance -v`
Expected: FAIL — the prompt does not yet mention "FTC".

- [ ] **Step 3: Add the exclusion guidance**

In `src/job_search_email/scorer.py`, inside `_build_system_prompt`, add a new bullet to the "Exclusion instructions" block, immediately after the first bullet (the one ending `"...candidate's area.\n"`) and before the `"- Also set exclude=true when the job is clearly unsuitable..."` bullet:

```python
        "- \"FTC\" means fixed-term contract. Treat any posting that offers "
        "fixed-term as a possibility, including dual \"Permanent / FTC\" "
        "listings, as not a guaranteed permanent role: set exclude=true with "
        "exclude_reason \"Fixed-term contract (FTC)\".\n"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: PASS — the new prompt-content test passes and all existing scorer tests stay green (including `test_system_prompt_contains_exclusion_instructions`).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/scorer.py tests/test_scorer.py
git commit -m "fix: instruct scorer to exclude FTC/dual permanent-FTC postings"
```

---

## Self-Review

**Spec coverage:**
- Layer 1 deterministic `\bftc\b` filter addition → Task 1.
- Layer 2 LLM exclusion guidance for FTC/dual postings → Task 2.
- 500-char cap kept, word-boundary guard against false positives → Task 1 (test + pattern).
- Filter tests (description FTC, title FTC, no false positive) → Task 1; scorer prompt-content test → Task 2.

**Placeholder scan:** No TBD/TODO; every step has full code and exact commands.

**Type consistency:** No new symbols introduced; both tasks change only the content of an existing compiled regex and an existing prompt string, and use test helpers (`make_job`, `make_profile`) and imports (`_check_employment_type`, `_build_system_prompt`) that already exist in the respective test files.
