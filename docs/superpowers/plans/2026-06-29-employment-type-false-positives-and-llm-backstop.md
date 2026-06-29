# Employment-Type False Positives & LLM Suitability Backstop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop non-permanent / unsuitable jobs reaching the email by (1) making reject indicators win over pass indicators in the deterministic employment-type check, and (2) letting the LLM analysis stage exclude any clearly-unsuitable job, surfaced in the debug email.

**Architecture:** Three layers. Layer 1 reorders `_check_employment_type` in `filter.py` to scan a combined employment-type + title + description text for disqualifying signals before honoring a pass type. Layer 2 adds `exclude` / `exclude_reason` to `JobAnalysis`, prompts the LLM to set them, and converts an excluded analysis into a rejected `ScoredResult` (analysis retained). Layer 3 routes scored results into the debug email and adds an AI-suitability section.

**Tech Stack:** Python 3, pytest, anthropic SDK (mocked in tests), dataclasses.

## Global Constraints

- No new dependencies.
- LLM exclusion reject reasons use the exact prefix `"AI suitability: "` (trailing space before the detail).
- Employment-type reject reasons are unchanged strings: `"employment type: {et}"` and `"description contains contract indicators"`.
- New `JobAnalysis` fields must have defaults so stale score-cache entries deserialize via `JobAnalysis(**cached)`.
- Tests must never call the live Anthropic API — patch `job_search_email.scorer.client`.
- Run tests with `python -m pytest` from the repo root (`c:\Code\job-search-email`).

---

### Task 1: Layer 1 — employment-type precedence fix

**Files:**
- Modify: `src/job_search_email/filter.py:13-45` (`_CONTRACT_PATTERNS` and `_check_employment_type`)
- Test: `tests/test_filter.py`

**Interfaces:**
- Consumes: `JobListing` (`title`, `company`, `description`, `employment_type`), `FilteredResult`.
- Produces: `_check_employment_type(job: JobListing) -> FilteredResult` — unchanged signature; behavior now rejects when any contract indicator appears in the employment-type field OR title OR first 500 chars of the description, even if the structured type is `permanent`/`full-time`.

- [ ] **Step 1: Write the failing tests**

Add to the end of the "Stage 2: text scan" group in `tests/test_filter.py` (after `test_employment_type_zero_hours_no_false_match`, before the `_check_role_suitability` import block):

```python
def test_employment_type_permanent_tag_with_contract_description_rejected():
    # Regression: a "permanent" structured type must NOT short-circuit the
    # description scan. A fixed-term phrase in the description still rejects.
    job = make_job(employment_type="permanent", description="This is a fixed term contract post.")
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_employment_type_full_time_tag_with_contract_description_rejected():
    job = make_job(employment_type="full-time", description="Offered on a fixed-term basis for 12 months.")
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_employment_type_combined_permanent_and_fixed_term_rejected():
    # Indeed can return a combined structured value.
    job = make_job(employment_type="Permanent, Fixed term contract")
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_employment_type_bare_fixed_term_phrase_rejected():
    job = make_job(description="This is a fixed term role within the team.")
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_employment_type_permanent_clean_still_passes():
    job = make_job(employment_type="permanent", description="A permanent senior management role.")
    result = _check_employment_type(job)
    assert result.rejected is False
    assert result.flags == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_filter.py -k "permanent_tag_with_contract or full_time_tag_with_contract or combined_permanent or bare_fixed_term or permanent_clean_still" -v`
Expected: the first four FAIL (currently `permanent`/`full-time` short-circuits to pass; combined value falls through to a scan that excludes the type field). `test_employment_type_permanent_clean_still_passes` may already PASS.

- [ ] **Step 3: Extend `_CONTRACT_PATTERNS`**

In `src/job_search_email/filter.py`, replace the `_CONTRACT_PATTERNS` definition (lines 13-24) with:

```python
_CONTRACT_PATTERNS = re.compile(
    r"fixed.?term (?:contract|post|appointment)"
    r"|fixed[\s\-]?term"
    r"|temporary (?:contract|post|role)"
    r"|contract basis"
    r"|maternity cover"
    r"|parental leave cover"
    r"|\d+[\s\-]month (?:contract|fixed)"
    r"|zero[\s\-]hours"
    r"|bank staff"
    r"|locum post",
    re.IGNORECASE,
)
```

- [ ] **Step 4: Rewrite `_check_employment_type` for reject-first ordering**

Replace the whole `_check_employment_type` function (lines 32-45) with:

```python
def _check_employment_type(job: JobListing) -> FilteredResult:
    et = (job.employment_type or "").lower().strip()
    # Scan the structured type field together with the title and the first
    # 500 chars of the description, so reject indicators win over pass
    # indicators (a "permanent" tag can't hide a fixed-term description).
    combined = f"{et} {job.title} {(job.description or '')[:500]}"

    if et in _REJECT_TYPES:
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=f"employment type: {et}")

    if _CONTRACT_PATTERNS.search(combined):
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason="description contains contract indicators")

    if et in _PASS_TYPES:
        return FilteredResult(job=job, flags=[], rejected=False, reject_reason=None)

    return FilteredResult(job=job, flags=["employment_type_unknown"], rejected=False, reject_reason=None)
```

- [ ] **Step 5: Run the new and existing employment-type tests**

Run: `python -m pytest tests/test_filter.py -v`
Expected: PASS (all new tests plus the existing employment-type, role, NHS-band, sponsor, and location tests).

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "fix: reject-first employment-type check so contract signals beat permanent tag"
```

---

### Task 2: Layer 2a — `exclude` fields on `JobAnalysis`

**Files:**
- Modify: `src/job_search_email/models.py:57-66` (`JobAnalysis` dataclass)
- Test: `tests/test_scorer.py`

**Interfaces:**
- Produces: `JobAnalysis.exclude: bool = False` and `JobAnalysis.exclude_reason: str = ""` — consumed by Task 3 (`scorer.py`) and Task 4 (`debug_email.py`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scorer.py` immediately after `test_job_analysis_new_fields_accept_values` (around line 56):

```python
def test_job_analysis_exclude_fields_default():
    a = make_analysis()
    assert a.exclude is False
    assert a.exclude_reason == ""


def test_job_analysis_exclude_fields_accept_values():
    a = make_analysis(exclude=True, exclude_reason="Fixed-term contract")
    assert a.exclude is True
    assert a.exclude_reason == "Fixed-term contract"


def test_job_analysis_exclude_backwards_compat_from_dict():
    old_cache_entry = {
        "score": 7,
        "matched_skills": [],
        "missing_essentials": [],
        "employment_type_note": "Permanent",
        "verdict": "Good match",
    }
    a = JobAnalysis(**old_cache_entry)
    assert a.exclude is False
    assert a.exclude_reason == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scorer.py -k "exclude_fields_default or exclude_fields_accept or exclude_backwards_compat" -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'exclude'` / `AttributeError`.

- [ ] **Step 3: Add the fields**

In `src/job_search_email/models.py`, add to the `JobAnalysis` dataclass after the `qualification_status` field (line 66):

```python
    qualification_status: str = ""
    exclude: bool = False
    exclude_reason: str = ""
```

(Replace the existing `qualification_status: str = ""` line with the three lines above.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scorer.py -k "exclude_fields_default or exclude_fields_accept or exclude_backwards_compat" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/models.py tests/test_scorer.py
git commit -m "feat: add exclude/exclude_reason fields to JobAnalysis"
```

---

### Task 3: Layer 2b — scorer prompt, parsing, and exclusion application

**Files:**
- Modify: `src/job_search_email/scorer.py` (`_build_system_prompt`, `_build_user_message`, `_analyse_job`, `score_jobs`)
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `JobAnalysis.exclude` / `JobAnalysis.exclude_reason` (Task 2).
- Produces: a new module-level helper `_build_scored_result(r: FilteredResult, analysis: JobAnalysis) -> ScoredResult` that marks the result `rejected=True, reject_reason="AI suitability: {analysis.exclude_reason}"` when `analysis.exclude` is true, retaining the analysis. Used by Task 4's debug section via the `"AI suitability:"` reason prefix.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scorer.py` after `test_score_jobs_parses_claude_response` (around line 183):

```python
_EXCLUDE_RESPONSE = json.dumps({
    "score": 6,
    "matched_skills": ["digital transformation"],
    "missing_essentials": [],
    "employment_type_note": "Listed as permanent but description says fixed-term",
    "verdict": "Fixed-term contract despite permanent tag.",
    "exclude": True,
    "exclude_reason": "Fixed-term contract",
})


def test_score_jobs_excludes_job_when_llm_flags_exclude():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client(_EXCLUDE_RESPONSE)):
        scored = score_jobs(results, make_profile())
    assert scored[0].rejected is True
    assert scored[0].reject_reason == "AI suitability: Fixed-term contract"
    assert scored[0].analysis is not None
    assert scored[0].analysis.exclude is True


def test_score_jobs_keeps_job_when_exclude_false():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client()):  # _GOOD_RESPONSE has no exclude
        scored = score_jobs(results, make_profile())
    assert scored[0].rejected is False
    assert scored[0].reject_reason is None
    assert scored[0].analysis.exclude is False


def test_score_jobs_cache_hit_exclude_applies():
    job = make_job(url="https://example.com/cached-exclude")
    profile = make_profile()
    fp = fingerprint_profile(profile)
    key = make_score_key(job.url, fp)
    cached_analysis = {
        "score": 6,
        "matched_skills": [],
        "missing_essentials": [],
        "employment_type_note": "",
        "verdict": "Fixed-term",
        "exclude": True,
        "exclude_reason": "Contract role",
    }
    score_cache = {key: cached_analysis}
    results = [make_kept(job)]
    m = _mock_client()
    with patch("job_search_email.scorer.client", m):
        scored = score_jobs(results, profile, score_cache=score_cache)
    m.messages.create.assert_not_called()
    assert scored[0].rejected is True
    assert scored[0].reject_reason == "AI suitability: Contract role"
    assert scored[0].analysis.exclude is True


def test_user_message_contains_exclude_schema():
    from job_search_email.scorer import _build_user_message
    msg = _build_user_message(make_job())
    assert "exclude" in msg
    assert "exclude_reason" in msg


def test_system_prompt_contains_exclusion_instructions():
    from job_search_email.scorer import _build_system_prompt
    prompt = _build_system_prompt(make_profile())
    assert "exclude" in prompt
```

Note: `fingerprint_profile`, `make_score_key` are already imported near the bottom of `tests/test_scorer.py` (line 382). If a test above that import runs first, the names resolve at call time because pytest imports the whole module before running — no action needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scorer.py -k "excludes_job_when_llm or keeps_job_when_exclude or cache_hit_exclude or user_message_contains_exclude or system_prompt_contains_exclusion" -v`
Expected: FAIL (`exclude` not parsed; reject_reason not set; schema/instructions absent).

- [ ] **Step 3: Add exclusion instructions to the system prompt**

In `src/job_search_email/scorer.py`, in `_build_system_prompt`, append this block to the returned string (after the qualification instructions, before the closing parenthesis — i.e. add it as a final concatenated string literal):

```python
        "\n\nExclusion instructions:\n"
        "- Set exclude=true when the job clearly fails a hard requirement that the "
        "upstream filters are meant to enforce but may have missed, based on the full "
        "description: the role is not permanent (fixed-term, contract, temporary, "
        "interim, maternity cover, locum, bank, or seasonal); the salary is clearly "
        "below the stated minimum; or the location is clearly outside the candidate's "
        "area.\n"
        "- Also set exclude=true when the job is clearly unsuitable for this candidate: "
        "wrong seniority level, a fundamentally different profession, or a domain the "
        "candidate is not open to.\n"
        "- When excluding, put a short human-readable reason (a few words) in "
        "exclude_reason, e.g. \"Fixed-term contract\" or \"Clinical nursing role\".\n"
        "- Otherwise set exclude=false and exclude_reason to an empty string; rank the "
        "job with the score instead."
```

- [ ] **Step 4: Add the exclude fields to the requested JSON in `_build_user_message`**

In `_build_user_message`, change the JSON template tail. Replace:

```python
        '  "qualification_status": "met|partial|mismatch|"\n'
        "}"
```

with:

```python
        '  "qualification_status": "met|partial|mismatch|",\n'
        '  "exclude": false,\n'
        '  "exclude_reason": ""\n'
        "}"
```

- [ ] **Step 5: Parse the exclude fields in `_analyse_job`**

In `_analyse_job`, add to the `JobAnalysis(...)` construction (after `qualification_status=qual_status,`):

```python
        qualification_status=qual_status,
        exclude=bool(data.get("exclude", False)),
        exclude_reason=data.get("exclude_reason", ""),
```

- [ ] **Step 6: Add the `_build_scored_result` helper and use it in `score_jobs`**

In `src/job_search_email/scorer.py`, add this helper directly above `def score_jobs(`:

```python
def _build_scored_result(r: FilteredResult, analysis: JobAnalysis) -> ScoredResult:
    rejected = r.rejected
    reject_reason = r.reject_reason
    if analysis.exclude:
        rejected = True
        reject_reason = f"AI suitability: {analysis.exclude_reason}"
    return ScoredResult(
        job=r.job, flags=r.flags, rejected=rejected,
        reject_reason=reject_reason, analysis=analysis,
    )
```

In the cache-hit branch of `score_jobs`, replace:

```python
        if key in score_cache:
            scored_map[i] = ScoredResult(
                job=r.job, flags=r.flags, rejected=r.rejected,
                reject_reason=r.reject_reason,
                analysis=JobAnalysis(**score_cache[key]),
            )
```

with:

```python
        if key in score_cache:
            scored_map[i] = _build_scored_result(r, JobAnalysis(**score_cache[key]))
```

In the fresh-analysis branch (inside the `as_completed` loop, the success path), replace:

```python
                analysis = future.result()
                scored_map[idx] = ScoredResult(
                    job=r.job, flags=r.flags, rejected=r.rejected,
                    reject_reason=r.reject_reason, analysis=analysis,
                )
                score_cache[make_score_key(r.job.url, profile_fp)] = asdict(analysis)
```

with:

```python
                analysis = future.result()
                scored_map[idx] = _build_scored_result(r, analysis)
                score_cache[make_score_key(r.job.url, profile_fp)] = asdict(analysis)
```

- [ ] **Step 7: Run the scorer tests**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: PASS (new exclusion tests plus all existing scorer/cache/qualification tests — the score cache now stores `exclude`/`exclude_reason`, which round-trips through `JobAnalysis(**...)`).

- [ ] **Step 8: Commit**

```bash
git add src/job_search_email/scorer.py tests/test_scorer.py
git commit -m "feat: LLM suitability backstop excludes unsuitable jobs via exclude flag"
```

---

### Task 4: Layer 3 — surface LLM exclusions in the debug email

**Files:**
- Modify: `src/job_search_email/debug_email.py` (imports, `build_debug_email_html`, new `_ai_suitability_section`)
- Modify: `src/job_search_email/main.py:240` (pass `scored` to `build_debug_email_html`)
- Test: `tests/test_debug_email.py`

**Interfaces:**
- Consumes: `ScoredResult` (with `analysis` retained) carrying reject reasons prefixed `"AI suitability:"` (Task 3).
- Produces: `_ai_suitability_section(scored) -> str`; `build_debug_email_html` now accepts `list[ScoredResult]` (duck-typed — existing `FilteredResult` inputs still work because the shared sections only read `job`/`rejected`/`reject_reason`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_debug_email.py`, update the imports at the top to also import `ScoredResult` and `JobAnalysis`:

```python
from job_search_email.debug_email import build_debug_email_html
from job_search_email.models import FilteredResult, JobAnalysis, JobListing, Profile, ScoredResult
```

Change `test_debug_email_has_five_details_sections` to expect six:

```python
def test_debug_email_has_six_details_sections():
    html = build_debug_email_html({}, [], _make_profile())
    assert html.count("<details") == 6
```

Add a helper and tests at the end of the file:

```python
def _ai_excluded(job: JobListing, reason: str, score: int = 6) -> ScoredResult:
    return ScoredResult(
        job=job, flags=[], rejected=True,
        reject_reason=f"AI suitability: {reason}",
        analysis=JobAnalysis(
            score=score, matched_skills=[], missing_essentials=[],
            employment_type_note="", verdict="", exclude=True, exclude_reason=reason,
        ),
    )


def test_ai_suitability_section_present():
    html = build_debug_email_html({}, [], _make_profile())
    assert "AI Suitability" in html


def test_ai_suitability_excluded_job_appears():
    html = build_debug_email_html(
        {"Bristol": "within"},
        [_ai_excluded(_make_job(), "Fixed-term contract", score=6)],
        _make_profile(),
    )
    assert "AI Suitability" in html
    assert "Business Manager" in html
    assert "Fixed-term contract" in html
    assert ">6<" in html  # score cell


def test_ai_suitability_ignores_non_ai_rejects():
    # A deterministic reject must not appear in the AI section's table.
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "employment type: contract")],
        _make_profile(),
    )
    assert "No AI suitability exclusions." in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_debug_email.py -k "six_details or ai_suitability" -v`
Expected: FAIL (`AI Suitability` text absent; only 5 `<details` sections).

- [ ] **Step 3: Update `debug_email.py` imports**

Change the top import in `src/job_search_email/debug_email.py`:

```python
from .models import Profile, ScoredResult
```

(`FilteredResult` is no longer referenced in this module after the type-hint change below; if any annotation still names it, keep it imported — but the helpers will be annotated with `ScoredResult`.)

- [ ] **Step 4: Add the `_ai_suitability_section` helper**

Add this function in `src/job_search_email/debug_email.py` just before `def build_debug_email_html(`:

```python
def _score_cell(r) -> str:
    analysis = getattr(r, "analysis", None)
    return str(analysis.score) if analysis is not None else "&#8212;"


def _ai_suitability_section(scored: list) -> str:
    prefix = "AI suitability:"
    excluded = [
        r for r in scored
        if r.rejected and r.reject_reason and r.reject_reason.startswith(prefix)
    ]

    if not excluded:
        body = '<p style="color:#999; font-size:13px;">No AI suitability exclusions.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px; text-align:right;">{_score_cell(r)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason.replace(prefix + " ", "", 1))}</td></tr>'
            for r in excluded
        )
        body = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:right;">Score</th>'
            '<th style="padding:4px 8px; text-align:left;">Reason</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "AI Suitability Filter</summary>" + body + "</details>"
    )
```

- [ ] **Step 5: Add the section to `build_debug_email_html` and update its signature**

In `build_debug_email_html`, change the parameter annotation `filtered: list[FilteredResult]` to `filtered: list[ScoredResult]`, and add the new section to the `sections` concatenation:

```python
    sections = (
        _location_section(classification, filtered)
        + _employment_type_section(filtered)
        + _role_suitability_section(filtered)
        + _nhs_band_section(filtered)
        + _sponsor_section(filtered)
        + _ai_suitability_section(filtered)
    )
```

(Optionally update the other helper annotations from `list[FilteredResult]` to `list[ScoredResult]` for consistency; not required for correctness.)

- [ ] **Step 6: Pass scored results from `main.py`**

In `src/job_search_email/main.py`, change the debug-email call (line ~240) from:

```python
        debug_html = build_debug_email_html(classification, filtered, profile)
```

to:

```python
        debug_html = build_debug_email_html(classification, scored, profile)
```

- [ ] **Step 7: Run the debug-email and main tests**

Run: `python -m pytest tests/test_debug_email.py tests/test_main.py -v`
Expected: PASS (new AI-suitability tests; six-section count; `test_main` debug toggles unaffected because it mocks `build_debug_email_html`).

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS — no regressions across filter, scorer, debug-email, main, and the rest.

- [ ] **Step 9: Commit**

```bash
git add src/job_search_email/debug_email.py src/job_search_email/main.py tests/test_debug_email.py
git commit -m "feat: surface LLM suitability exclusions in debug email"
```

---

## Self-Review

**Spec coverage:**
- Layer 1 deterministic precedence fix → Task 1. ✓ (combined text incl. employment-type field, reject-first order, bare `fixed[\s-]term` pattern)
- Layer 2 schema (`exclude`/`exclude_reason` with defaults) → Task 2. ✓
- Layer 2 prompt + parse + apply (`"AI suitability:"` reject, analysis retained, fresh + cache paths) → Task 3. ✓
- Layer 3 debug email consumes `ScoredResult`, new AI section, `main.py` passes `scored` → Task 4. ✓
- Edge cases: stale cache without `exclude` → Task 2 backwards-compat test ✓; beyond-cap / analysis_failed untouched → covered by existing scorer tests still passing in Task 3 Step 7 ✓; empty exclude_reason → reason renders as `"AI suitability:"` (helper still excludes) — implicitly handled, score cell guarded for missing analysis.

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `_build_scored_result(r, analysis)` defined in Task 3 and used only there; `_ai_suitability_section`/`_score_cell` defined and used in Task 4; `JobAnalysis.exclude`/`exclude_reason` names consistent across Tasks 2-4; reject prefix `"AI suitability: "` consistent between Task 3 (write) and Task 4 (read). ✓
