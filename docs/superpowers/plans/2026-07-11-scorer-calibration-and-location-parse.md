# Scorer Calibration + Location Parser Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the AI scorer from over-scoring wrong-profession/seniority jobs (e.g. a Deputy Chief People Officer role scored 7/10 for a governance manager), and stop the location classifier from silently failing when the LLM wraps its JSON in prose.

**Architecture:** Four independent, small changes to the existing pipeline: (1) a new `gatekeeping_gaps` field on `JobAnalysis` with a code-side score cap mirroring the existing `mismatch → 3` cap; (2) prompt changes — reorder the requested JSON so analysis fields precede the score, redefine score bands in shortlist-probability terms, and add an explicit different-profession rule; (3) render the new field in `explain-job` output; (4) a tolerant JSON extractor in the location filter.

**Tech Stack:** Python 3.11, dataclasses, pytest, Anthropic SDK (mocked in tests).

## Global Constraints

- Run tests with: `.venv/Scripts/python.exe -m pytest <path> -v` from the repo root (`c:\Code\job-search-email`). The full suite is `.venv/Scripts/python.exe -m pytest tests -q`.
- **Backwards compatibility with cached analyses is mandatory:** old `job_score_cache.json` entries lack `gatekeeping_gaps`; `JobAnalysis(**old_dict)` must still work. New fields therefore need `field(default_factory=list)` and must be read with `data.get(...)`.
- **These literal strings must survive in the system prompt** (existing tests assert them): `"Calibration: "`, `"gatekeeping"`, `"score it 6 or below"`, and the ordering `Score guidance:` < `Calibration: ` < `Qualification analysis instructions:` (see `tests/test_scorer.py::test_system_prompt_contains_calibration_instruction`).
- Prompt changes intentionally invalidate the score cache (cache keys include a prompt fingerprint). Do NOT edit `assets/job_score_cache.json` or any cache file.
- Do not change the existing `mismatch → min(score, 3)` cap behaviour.
- Commit after each task with a conventional-commit message ending in the Co-Authored-By line shown in each commit step.

---

### Task 1: `gatekeeping_gaps` field + code-side score cap

**Files:**
- Modify: `src/job_search_email/models.py:79-89` (JobAnalysis dataclass)
- Modify: `src/job_search_email/scorer.py:121-138` (`_parse_analysis`)
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: existing `JobAnalysis` dataclass and `_parse_analysis(text) -> JobAnalysis`.
- Produces: `JobAnalysis.gatekeeping_gaps: list[str]` (default `[]`), and the parsing rule: non-empty `gatekeeping_gaps` in the LLM JSON caps `score` at 6 (applied before the existing mismatch cap; mismatch still wins because 3 < 6).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scorer.py`:

```python
_GATEKEEPING_RESPONSE = json.dumps({
    "score": 7,
    "matched_skills": ["workforce planning"],
    "missing_essentials": ["HR function leadership"],
    "gatekeeping_gaps": ["No HR executive track record"],
    "employment_type_note": "Permanent full-time",
    "verdict": "Keyword overlap but wrong profession",
})


def test_job_analysis_gatekeeping_gaps_defaults_empty():
    a = make_analysis()
    assert a.gatekeeping_gaps == []


def test_job_analysis_gatekeeping_gaps_accepts_values():
    a = make_analysis(gatekeeping_gaps=["No HR executive track record"])
    assert a.gatekeeping_gaps == ["No HR executive track record"]


def test_job_analysis_gatekeeping_backwards_compat_from_dict():
    # Old cache entries without the field must still deserialise
    old_cache_entry = {
        "score": 7,
        "matched_skills": [],
        "missing_essentials": [],
        "employment_type_note": "Permanent",
        "verdict": "Good match",
    }
    a = JobAnalysis(**old_cache_entry)
    assert a.gatekeeping_gaps == []


def test_job_analysis_gatekeeping_serialises_with_asdict():
    a = make_analysis(gatekeeping_gaps=["No JNCC experience"])
    assert asdict(a)["gatekeeping_gaps"] == ["No JNCC experience"]


def test_score_jobs_caps_score_to_6_when_gatekeeping_gaps():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client(_GATEKEEPING_RESPONSE)):
        scored = score_jobs(results, make_profile())
    a = scored[0].analysis
    assert a.score == 6
    assert a.gatekeeping_gaps == ["No HR executive track record"]


def test_score_jobs_gatekeeping_cap_does_not_raise_score():
    low = json.dumps({
        "score": 3,
        "matched_skills": [],
        "missing_essentials": ["HR leadership"],
        "gatekeeping_gaps": ["No HR executive track record"],
        "employment_type_note": "",
        "verdict": "Weak",
    })
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client(low)):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis.score == 3


def test_score_jobs_no_gatekeeping_gaps_leaves_score_alone():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client(_GOOD_RESPONSE)):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis.score == 8
    assert scored[0].analysis.gatekeeping_gaps == []


def test_score_jobs_mismatch_cap_beats_gatekeeping_cap():
    both = json.dumps({
        "score": 9,
        "matched_skills": [],
        "missing_essentials": [],
        "gatekeeping_gaps": ["No PRINCE2 delivery record"],
        "employment_type_note": "",
        "verdict": "Weak",
        "required_qualifications": ["PRINCE2"],
        "qualification_gaps": ["PRINCE2"],
        "qualification_status": "mismatch",
    })
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client(both)):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis.score == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scorer.py -v -k gatekeeping`
Expected: FAIL — `TypeError: JobAnalysis.__init__() got an unexpected keyword argument 'gatekeeping_gaps'` (and the cap tests fail similarly).

- [ ] **Step 3: Implement**

In `src/job_search_email/models.py`, add the field to `JobAnalysis` after `qualification_status` (it must sit among the defaulted fields):

```python
@dataclass
class JobAnalysis:
    score: int
    matched_skills: list[str]
    missing_essentials: list[str]
    employment_type_note: str
    verdict: str
    required_qualifications: list[str] = field(default_factory=list)
    qualification_gaps: list[str] = field(default_factory=list)
    qualification_status: str = ""
    gatekeeping_gaps: list[str] = field(default_factory=list)
    exclude: bool = False
    exclude_reason: str = ""
```

In `src/job_search_email/scorer.py`, update `_parse_analysis`:

```python
def _parse_analysis(text: str) -> JobAnalysis:
    data = json.loads(_strip_code_fence(text))
    score = int(data["score"])
    gatekeeping_gaps = data.get("gatekeeping_gaps", [])
    if gatekeeping_gaps:
        score = min(score, 6)
    qual_status = data.get("qualification_status", "")
    if qual_status == "mismatch":
        score = min(score, 3)
    return JobAnalysis(
        score=score,
        matched_skills=data.get("matched_skills", []),
        missing_essentials=data.get("missing_essentials", []),
        employment_type_note=data.get("employment_type_note", ""),
        verdict=data.get("verdict", ""),
        required_qualifications=data.get("required_qualifications", []),
        qualification_gaps=data.get("qualification_gaps", []),
        qualification_status=qual_status,
        gatekeeping_gaps=gatekeeping_gaps,
        exclude=bool(data.get("exclude", False)),
        exclude_reason=data.get("exclude_reason", ""),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scorer.py -v`
Expected: ALL PASS (new tests plus every pre-existing test in the file).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/scorer.py tests/test_scorer.py
git commit -m "feat: add gatekeeping_gaps analysis field with score cap at 6

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Prompt calibration — reasoning before score, shortlist bands, different-profession rule

**Files:**
- Modify: `src/job_search_email/scorer.py:31-83` (`_build_system_prompt`) and `src/job_search_email/scorer.py:86-109` (`_build_user_message`)
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `_build_system_prompt(profile) -> str`, `_build_user_message(job) -> str`, and Task 1's `gatekeeping_gaps` JSON field.
- Produces: prompt text only — no signature changes. The user-message JSON schema now lists analysis fields before `score`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scorer.py`:

```python
def test_system_prompt_instructs_gatekeeping_gaps_field():
    prompt = _build_system_prompt(make_profile())
    assert "gatekeeping_gaps" in prompt


def test_system_prompt_contains_different_profession_rule():
    prompt = _build_system_prompt(make_profile())
    assert "core discipline" in prompt
    assert "1-4" in prompt
    assert "Different profession" in prompt


def test_system_prompt_score_bands_use_shortlist_terms():
    prompt = _build_system_prompt(make_profile())
    assert "initial sift" in prompt


def test_user_message_schema_puts_analysis_fields_before_score():
    from job_search_email.scorer import _build_user_message
    msg = _build_user_message(make_job())
    schema = msg[msg.index("Return JSON"):]
    assert schema.index('"matched_skills"') < schema.index('"score"')
    assert schema.index('"missing_essentials"') < schema.index('"score"')
    assert schema.index('"gatekeeping_gaps"') < schema.index('"score"')
    assert schema.index('"verdict"') < schema.index('"score"')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scorer.py -v -k "profession or shortlist or gatekeeping_gaps_field or before_score"`
Expected: FAIL — assertions on missing prompt strings and schema ordering.

- [ ] **Step 3: Implement**

In `_build_system_prompt`, replace the current score-guidance + calibration block (the two paragraphs from `"Score guidance: ..."` through `"...however strong the remaining overlap.\n\n"`, currently lines 44-54) with:

```python
        "Score guidance — score the candidate's realistic odds of being shortlisted, "
        "not the breadth of skills overlap: "
        "8-10 = strong match (would very likely survive the initial sift). "
        "5-7 = partial match (credible applicant but real gaps present). "
        "1-4 = weak (would not survive the initial sift: missing essentials, wrong "
        "profession, or significant misalignment).\n\n"
        "Calibration: the score must reflect the candidate's realistic odds of "
        "being shortlisted, not just breadth of skills overlap. Identify any "
        "requirement a hiring manager would treat as gatekeeping at the role's "
        "stated seniority — for example a fee-earning or business-development "
        "track record for senior consultancy grades, statutory registration, or "
        "prior budget ownership at director level. List every gatekeeping "
        "requirement the candidate lacks in gatekeeping_gaps (use an empty list "
        "if there are none). If the candidate lacks any gatekeeping requirement, "
        "the job is at best a partial match: score it 6 or below, however strong "
        "the remaining overlap.\n"
        "If the role's core discipline (e.g. HR, finance, legal, clinical, "
        "engineering) is a profession the candidate has never held a post in, "
        "transferable skills do not survive the sift for a specialist role: "
        "score it 1-4 regardless of keyword overlap, and normally set "
        "exclude=true with exclude_reason \"Different profession\".\n\n"
```

Everything before (`"Score guidance"`'s preceding text) and after (`"Qualification analysis instructions:"` onward) stays byte-identical. This preserves the test-required strings `"Calibration: "`, `"gatekeeping"`, `"score it 6 or below"` and the required section ordering.

In `_build_user_message`, replace the `"Return JSON:"` block with (analysis fields first, then score):

```python
        "Return JSON (populate the analysis fields first, then decide the score):\n"
        "{\n"
        '  "matched_skills": ["..."],\n'
        '  "missing_essentials": ["..."],\n'
        '  "gatekeeping_gaps": ["..."],\n'
        '  "required_qualifications": ["..."],\n'
        '  "qualification_gaps": ["..."],\n'
        '  "qualification_status": "met|partial|mismatch|",\n'
        '  "employment_type_note": "...",\n'
        '  "verdict": "...",\n'
        '  "score": <1-10>,\n'
        '  "exclude": false,\n'
        '  "exclude_reason": ""\n'
        "}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scorer.py tests/test_explain_scorer_seam.py -v`
Expected: ALL PASS — including the pre-existing `test_system_prompt_contains_calibration_instruction`, `test_user_message_contains_qualification_schema`, and `test_user_message_contains_exclude_schema`.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/scorer.py tests/test_scorer.py
git commit -m "feat: calibrate scorer prompt — reason-then-score ordering, shortlist bands, different-profession rule

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Show gatekeeping gaps in explain-job output

**Files:**
- Modify: `src/job_search_email/explain_render.py:21-35` (`_scorer_block`)
- Test: `tests/test_explain_render.py`

**Interfaces:**
- Consumes: `JobAnalysis.gatekeeping_gaps` from Task 1; `_format_list` helper already in the file.
- Produces: a `Gatekeeping gaps: ...` line in the AI SUITABILITY block of `render_explanation` output.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_explain_render.py`:

```python
def test_render_scorer_shows_gatekeeping_gaps():
    trace = AnalysisTrace(
        analysis=JobAnalysis(
            score=6, matched_skills=["workforce planning"], missing_essentials=[],
            employment_type_note="Permanent", verdict="Wrong profession",
            gatekeeping_gaps=["No HR executive track record"],
        ),
        system_prompt="SYS", user_message="USER", raw_text='{"score": 6}',
    )
    out = render_explanation(_job(), _gates_all_pass(), trace, None)
    assert "Gatekeeping gaps: No HR executive track record" in out


def test_render_scorer_gatekeeping_gaps_empty_shows_none():
    out = render_explanation(_job(), _gates_all_pass(), _scorer_trace(), None)
    assert "Gatekeeping gaps: (none)" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explain_render.py -v -k gatekeeping`
Expected: FAIL — `"Gatekeeping gaps: ..."` not in output.

- [ ] **Step 3: Implement**

In `_scorer_block` in `src/job_search_email/explain_render.py`, add one line between `Missing:` and `Qualifications:`:

```python
        f"Missing: {_format_list(a.missing_essentials)}\n"
        f"Gatekeeping gaps: {_format_list(a.gatekeeping_gaps)}\n"
        f"Qualifications: {qual} (gaps: {_format_list(a.qualification_gaps)})\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_explain_render.py tests/test_explain_job.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/explain_render.py tests/test_explain_render.py
git commit -m "feat: show gatekeeping gaps in explain-job scorer block

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Tolerant JSON extraction in the location classifier

**Files:**
- Modify: `src/job_search_email/location_filter.py:29-75`
- Test: `tests/test_location_filter.py`

**Interfaces:**
- Consumes: nothing from other tasks (fully independent).
- Produces: `_extract_json_object(text: str) -> object` in `location_filter.py` — returns the first balanced JSON value starting at the first `{`, ignoring leading and trailing prose; raises `ValueError` when no `{` is present. `classify_locations` uses it in place of `json.loads(_strip_code_fence(text))`.

Background: a live run failed with `[location_filter] classify call failed: Extra data: line 4 column 1` — the model returned a valid JSON object followed by extra text, `json.loads` rejected the whole response, and every location silently fell back to "uncertain" (defeating the filter). `json.JSONDecoder().raw_decode` parses the first complete JSON value and ignores whatever follows.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_location_filter.py`:

```python
def test_classify_locations_tolerates_trailing_prose_after_json():
    # Regression: live run failed with "Extra data: line 4 column 1" when the
    # model appended a note after the JSON object, and every location silently
    # fell back to "uncertain".
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        block = MagicMock()
        block.text = '{\n"Swindon, ENG, GB": "outside"\n}\n\nNote: Swindon is ~90 miles from home.'
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_locations(["Swindon, ENG, GB"], home="Swansea", radius_miles=40, cache=cache)
    assert result["Swindon, ENG, GB"] == "outside"
    assert cache["Swansea:40:Swindon, ENG, GB"] == "outside"


def test_classify_locations_tolerates_leading_prose_before_json():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        block = MagicMock()
        block.text = 'Here is the classification:\n{"Reading, RG1": "outside"}'
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_locations(["Reading, RG1"], home="Bristol", radius_miles=50, cache=cache)
    assert result["Reading, RG1"] == "outside"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_location_filter.py -v -k prose`
Expected: FAIL — both locations come back `"uncertain"` because `json.loads` raises.

- [ ] **Step 3: Implement**

In `src/job_search_email/location_filter.py`, replace the `_strip_code_fence` helper (lines 29-35) with:

```python
def _extract_json_object(text: str):
    # Models sometimes wrap the JSON in a code fence or surround it with prose
    # ("Extra data" from json.loads). Parse the first balanced JSON value
    # starting at the first brace and ignore everything around it.
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj
```

And in `classify_locations`, change line 69 from:

```python
        raw = json.loads(_strip_code_fence(text))
```

to:

```python
        raw = _extract_json_object(text)
```

`_strip_code_fence` has no other callers in this module — delete it. (Do NOT touch the separate `_strip_code_fence` copies in `scorer.py` and `queries.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_location_filter.py -v`
Expected: ALL PASS — including the pre-existing fenced-JSON and invalid-JSON tests (fenced works because the first `{` sits inside the fence; `"not valid json"` has no `{`, so `ValueError` is raised and caught by the existing except, defaulting to "uncertain").

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: ALL PASS.

```bash
git add src/job_search_email/location_filter.py tests/test_location_filter.py
git commit -m "fix: tolerate prose around JSON in location classifier response

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
