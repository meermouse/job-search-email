# UK-Wide Remote Job Search Implementation Plan (FE-020)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search UK-wide for remote jobs per opted-in profile, keeping a far-afield job only when its description positively confirms fully-remote working.

**Architecture:** A new `include_remote` profile flag adds a UK-wide "remote leg" to the jobspy and Reed searchers. A new `remote_filter.py` module (mirroring `location_filter.py`) batch-classifies far-afield jobs' descriptions via Haiku as `remote`/`not_remote` with a persistent URL-keyed cache. The location hard-filter gate in `filter.py` then keeps far-afield jobs only on a confirmed `remote` verdict — strict, fail-closed.

**Tech Stack:** Python 3.10+, anthropic SDK (Haiku), python-jobspy, Reed REST API, pytest with `unittest.mock.patch`.

**Spec:** `docs/superpowers/specs/2026-07-15-remote-jobs-design.md`

## Global Constraints

- `include_remote` defaults to `false`; profiles with it off keep **exactly** today's behaviour (including the `uncertain`-location pass-through).
- Remote confirmation is strict: hybrid, "remote optional", set office days, vague, or silent-on-remote → `not_remote`. Silence is not confirmation.
- Fail closed: an API error during the remote check rejects the affected far-afield jobs with a distinct reject reason; the `unverified` verdict is **never cached**.
- Jobs with a blank location string are treated as `uncertain` under the gate.
- NHS Jobs gets **no** remote search leg (empty descriptions can never be confirmed).
- No live LLM or network calls in tests — always `patch` the client / `scrape_jobs` / `requests.get`.
- Tests run with `python -m pytest` from the repo root (`c:\Code\job-search-email`). Test files import helpers as `from profile_helpers import make_profile` (repo convention).
- All work on branch `feature/FE-020-remote-jobs`.

---

### Task 1: `include_remote` profile flag

**Files:**
- Modify: `src/job_search_email/models.py:44-45` (Profile dataclass)
- Modify: `src/job_search_email/profile.py:60` (load_profile)
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `Profile.include_remote: bool` (default `False`), read by every later task via the `profile` object already threaded through the pipeline.
- Note: `fingerprint_profile` uses `asdict(profile)`, so the new field automatically changes the fingerprint when toggled — that is desired (invalidates cached search plan) and needs no code change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py` (next to the existing `filter_sponsors` default tests at the end of the load_profile section):

```python
def test_load_profile_include_remote_defaults_false(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.include_remote is False


def test_load_profile_include_remote_reads_true(tmp_path: Path) -> None:
    yaml_with_flag = PROFILE_YAML + "include_remote: true\n"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml_with_flag, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.include_remote is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py::test_load_profile_include_remote_defaults_false tests/test_main.py::test_load_profile_include_remote_reads_true -v`
Expected: FAIL with `AttributeError: 'Profile' object has no attribute 'include_remote'`

- [ ] **Step 3: Implement**

In `src/job_search_email/models.py`, add to the `Profile` dataclass directly after `filter_sponsors: bool = True`:

```python
    include_remote: bool = False
```

In `src/job_search_email/profile.py`, in `load_profile`, add after `filter_sponsors=data.get("filter_sponsors", True),`:

```python
        include_remote=data.get("include_remote", False),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: all PASS (existing tests unaffected — the field has a default).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/profile.py tests/test_main.py
git commit -m "feat: add include_remote profile flag (default off)"
```

---

### Task 2: `remote_filter.py` — LLM remote-confirmation module

**Files:**
- Create: `src/job_search_email/remote_filter.py`
- Test: `tests/test_remote_filter.py` (new)

**Interfaces:**
- Consumes: `JobListing` from `.models`; `_extract_json_object` from `.location_filter` (existing helper, precedent: `filter.py` imports `_normalize` from `sponsor_filter`).
- Produces:
  - `classify_remote(jobs: list[JobListing], cache: dict[str, str]) -> dict[str, str]` — returns `{job.url: "remote" | "not_remote" | "unverified"}`. `"unverified"` = check could not run (API failure); never cached.
  - `load_remote_cache(path: Path) -> dict[str, str]`
  - `save_remote_cache(cache: dict[str, str], path: Path) -> None`
  - Module-level `client = anthropic.Anthropic()` — tests patch `job_search_email.remote_filter.client`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_remote_filter.py`:

```python
import json
from unittest.mock import MagicMock, patch

from job_search_email.models import JobListing
from job_search_email.remote_filter import (
    classify_remote,
    load_remote_cache,
    save_remote_cache,
)


def make_job(url: str, description: str = "", location: str = "Remote") -> JobListing:
    return JobListing(
        title="Digital Manager", company="Acme Analytics", location=location,
        salary_min=70000, description=description, url=url,
        source="reed", employment_type="permanent",
    )


def _mock_claude_response(payload: dict) -> MagicMock:
    block = MagicMock()
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def test_classify_remote_uses_cache_without_calling_claude():
    cache = {"https://x.com/1": "remote", "https://x.com/2": "not_remote"}
    jobs = [make_job("https://x.com/1"), make_job("https://x.com/2")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        result = classify_remote(jobs, cache=cache)
    mock_client.messages.create.assert_not_called()
    assert result == {"https://x.com/1": "remote", "https://x.com/2": "not_remote"}


def test_classify_remote_calls_claude_for_uncached():
    jobs = [
        make_job("https://x.com/1", description="This role is fully remote within the UK."),
        make_job("https://x.com/2", description="Hybrid: 3 days in our Leeds office."),
    ]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response(
            {"0": "remote", "1": "not_remote"})
        result = classify_remote(jobs, cache=cache)
    mock_client.messages.create.assert_called_once()
    assert result["https://x.com/1"] == "remote"
    assert result["https://x.com/2"] == "not_remote"


def test_classify_remote_updates_cache_after_call():
    jobs = [make_job("https://x.com/1")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "remote"})
        classify_remote(jobs, cache=cache)
    assert cache == {"https://x.com/1": "remote"}


def test_classify_remote_missing_key_defaults_not_remote():
    # The model answered but omitted a job: no positive confirmation → not_remote.
    jobs = [make_job("https://x.com/1")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({})
        result = classify_remote(jobs, cache=cache)
    assert result["https://x.com/1"] == "not_remote"
    assert cache["https://x.com/1"] == "not_remote"


def test_classify_remote_invalid_verdict_defaults_not_remote():
    jobs = [make_job("https://x.com/1")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "maybe"})
        result = classify_remote(jobs, cache={})
    assert result["https://x.com/1"] == "not_remote"


def test_classify_remote_api_failure_returns_unverified_and_does_not_cache():
    jobs = [make_job("https://x.com/1")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.side_effect = ConnectionError("api down")
        result = classify_remote(jobs, cache=cache)
    assert result["https://x.com/1"] == "unverified"
    assert cache == {}


def test_classify_remote_handles_fenced_json():
    jobs = [make_job("https://x.com/1")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        block = MagicMock()
        block.text = '```json\n{"0": "remote"}\n```'
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_remote(jobs, cache={})
    assert result["https://x.com/1"] == "remote"


def test_classify_remote_batches_large_input():
    jobs = [make_job(f"https://x.com/{i}") for i in range(25)]  # batch size is 20
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.side_effect = [
            _mock_claude_response({str(i): "not_remote" for i in range(20)}),
            _mock_claude_response({str(i): "not_remote" for i in range(5)}),
        ]
        result = classify_remote(jobs, cache={})
    assert mock_client.messages.create.call_count == 2
    assert len(result) == 25


def test_classify_remote_truncates_long_descriptions():
    jobs = [make_job("https://x.com/1", description="A" * 10000)]
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "not_remote"})
        classify_remote(jobs, cache={})
    sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "A" * 4001 not in sent


def test_load_remote_cache_missing_file_returns_empty(tmp_path):
    assert load_remote_cache(tmp_path / "nope.json") == {}


def test_load_remote_cache_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json", encoding="utf-8")
    assert load_remote_cache(path) == {}


def test_save_and_load_remote_cache_roundtrip(tmp_path):
    path = tmp_path / "cache.json"
    save_remote_cache({"https://x.com/1": "remote"}, path)
    assert not (tmp_path / "cache.tmp").exists()
    assert load_remote_cache(path) == {"https://x.com/1": "remote"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_remote_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.remote_filter'`

- [ ] **Step 3: Implement**

Create `src/job_search_email/remote_filter.py`:

```python
import json
import os
import sys
from pathlib import Path

import anthropic

from .location_filter import _extract_json_object
from .models import JobListing

client = anthropic.Anthropic()

_MODEL = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")
_BATCH_SIZE = 20
_DESCRIPTION_CHARS = 4000

_SYSTEM_PROMPT = (
    "You are vetting UK job postings for fully-remote working. For each job you are "
    "given an id, title, location string, and description. Classify each job as:\n"
    '- "remote": the posting positively and explicitly confirms fully-remote working '
    '(e.g. "fully remote", "100% remote", "work from anywhere in the UK"). Occasional '
    "pre-arranged visits such as quarterly team days do not disqualify.\n"
    '- "not_remote": everything else — hybrid, a set number of office days per week, '
    '"remote optional", on-site, or the posting never clearly confirms fully-remote '
    "working.\n\n"
    "Silence is not confirmation: when the text does not explicitly confirm fully-remote "
    'working, answer "not_remote".\n'
    "Respond only with valid JSON: an object mapping each job id to its verdict."
)


def _classify_batch(batch: list[JobListing]) -> dict | None:
    payload = [
        {
            "id": str(i),
            "title": job.title,
            "location": job.location,
            "description": (job.description or "")[:_DESCRIPTION_CHARS],
        }
        for i, job in enumerate(batch)
    ]
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": "Classify these jobs:\n" + json.dumps(payload, ensure_ascii=False),
            }],
        )
        text = response.content[0].text if response.content else ""
        raw = _extract_json_object(text)
        if not isinstance(raw, dict):
            raise ValueError(f"expected dict, got {type(raw).__name__}")
        return raw
    except Exception as exc:
        print(f"[remote_filter] classify call failed: {exc}", file=sys.stderr)
        return None


def classify_remote(jobs: list[JobListing], cache: dict[str, str]) -> dict[str, str]:
    """Map each job URL to "remote", "not_remote", or "unverified".

    "unverified" marks jobs whose check could not run (API failure). It is
    never cached, so the next run retries them — the filter gate fails closed
    on it rather than letting an unchecked far-afield job through.
    """
    result: dict[str, str] = {}
    to_check: list[JobListing] = []
    for job in jobs:
        if job.url in cache:
            result[job.url] = cache[job.url]
        else:
            to_check.append(job)

    for start in range(0, len(to_check), _BATCH_SIZE):
        batch = to_check[start:start + _BATCH_SIZE]
        verdicts = _classify_batch(batch)
        for i, job in enumerate(batch):
            if verdicts is None:
                result[job.url] = "unverified"
                continue
            verdict = verdicts.get(str(i))
            if verdict not in ("remote", "not_remote"):
                # Model omitted or garbled the verdict: no positive
                # confirmation exists, which is the strict default.
                verdict = "not_remote"
            result[job.url] = verdict
            cache[job.url] = verdict

    return result


def load_remote_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_remote_cache(cache: dict[str, str], path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_remote_filter.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/remote_filter.py tests/test_remote_filter.py
git commit -m "feat: add remote_filter module for strict fully-remote confirmation"
```

---

### Task 3: Location gate honours remote verdicts in `filter.py`

**Files:**
- Modify: `src/job_search_email/filter.py:161-167` (`_check_location`) and `filter.py:170-226` (`filter_jobs`)
- Test: `tests/test_filter.py`

**Interfaces:**
- Consumes: verdict strings `"remote" | "not_remote" | "unverified"` produced by Task 2 (as a plain `dict[str, str]` — this task has no import dependency on `remote_filter`).
- Produces (later tasks rely on these exact behaviours):
  - `_check_location(job, rejected_locations, within_locations=frozenset(), remote_verdicts=None) -> FilteredResult | None`. `remote_verdicts=None` → legacy behaviour, byte-identical reject reasons. Non-None → gate mode; may return a **non-rejected** `FilteredResult` carrying `flags=["remote_confirmed"]` to signal a pass-with-flag.
  - `filter_jobs(..., within_locations: frozenset[str] = frozenset(), remote_verdicts: dict[str, str] | None = None)`.
  - Flag constant: the literal string `"remote_confirmed"` (used by email/trace tasks).
  - Reject reasons (exact strings, used by tests and debug reports):
    - `f"location outside radius and not confirmed fully remote: {job.location}"`
    - `f"location uncertain and not confirmed fully remote: {job.location or 'not stated'}"`
    - `f"remote check unavailable — cannot confirm fully remote ({job.location or 'not stated'})"`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filter.py`:

```python
# --- Remote gate (include_remote profiles) ---

_WITHIN = frozenset({"Bristol", "Bath, BA1"})
_OUTSIDE = frozenset({"Manchester"})


def test_remote_gate_within_location_passes_without_verdict():
    job = make_job(location="Bristol")
    result = _check_location(job, _OUTSIDE, within_locations=_WITHIN, remote_verdicts={})
    assert result is None


def test_remote_gate_outside_confirmed_remote_passes_with_flag():
    job = make_job(location="Manchester", url="https://x.com/1")
    result = _check_location(
        job, _OUTSIDE, within_locations=_WITHIN,
        remote_verdicts={"https://x.com/1": "remote"},
    )
    assert result is not None
    assert result.rejected is False
    assert result.flags == ["remote_confirmed"]


def test_remote_gate_outside_not_remote_rejected():
    job = make_job(location="Manchester", url="https://x.com/1")
    result = _check_location(
        job, _OUTSIDE, within_locations=_WITHIN,
        remote_verdicts={"https://x.com/1": "not_remote"},
    )
    assert result is not None and result.rejected is True
    assert result.reject_reason == "location outside radius and not confirmed fully remote: Manchester"


def test_remote_gate_uncertain_not_remote_rejected():
    job = make_job(location="Remote, UK", url="https://x.com/1")
    result = _check_location(
        job, _OUTSIDE, within_locations=_WITHIN,
        remote_verdicts={"https://x.com/1": "not_remote"},
    )
    assert result is not None and result.rejected is True
    assert result.reject_reason == "location uncertain and not confirmed fully remote: Remote, UK"


def test_remote_gate_uncertain_confirmed_remote_passes():
    job = make_job(location="Remote, UK", url="https://x.com/1")
    result = _check_location(
        job, _OUTSIDE, within_locations=_WITHIN,
        remote_verdicts={"https://x.com/1": "remote"},
    )
    assert result is not None
    assert result.rejected is False
    assert result.flags == ["remote_confirmed"]


def test_remote_gate_blank_location_treated_as_uncertain():
    job = make_job(location="", url="https://x.com/1")
    result = _check_location(
        job, _OUTSIDE, within_locations=_WITHIN,
        remote_verdicts={"https://x.com/1": "not_remote"},
    )
    assert result is not None and result.rejected is True
    assert result.reject_reason == "location uncertain and not confirmed fully remote: not stated"


def test_remote_gate_missing_verdict_fails_closed():
    job = make_job(location="Manchester", url="https://x.com/1")
    result = _check_location(job, _OUTSIDE, within_locations=_WITHIN, remote_verdicts={})
    assert result is not None and result.rejected is True
    assert result.reject_reason == "remote check unavailable — cannot confirm fully remote (Manchester)"


def test_remote_gate_unverified_verdict_fails_closed():
    job = make_job(location="Manchester", url="https://x.com/1")
    result = _check_location(
        job, _OUTSIDE, within_locations=_WITHIN,
        remote_verdicts={"https://x.com/1": "unverified"},
    )
    assert result is not None and result.rejected is True
    assert "remote check unavailable" in result.reject_reason


def test_remote_gate_none_verdicts_keeps_legacy_behaviour():
    # remote_verdicts=None must behave exactly as before: uncertain passes.
    job = make_job(location="Remote, UK")
    assert _check_location(job, _OUTSIDE, within_locations=frozenset(), remote_verdicts=None) is None


def test_filter_jobs_remote_gate_keeps_confirmed_and_flags():
    jobs = [make_job(location="Manchester", url="https://x.com/1", employment_type="full-time")]
    results = filter_jobs(
        jobs, make_plan(), make_profile_stub(),
        rejected_locations=frozenset({"Manchester"}),
        within_locations=frozenset({"Bristol"}),
        remote_verdicts={"https://x.com/1": "remote"},
    )
    assert results[0].rejected is False
    assert "remote_confirmed" in results[0].flags


def test_filter_jobs_remote_gate_rejects_unconfirmed():
    jobs = [make_job(location="Remote", url="https://x.com/1", employment_type="full-time")]
    results = filter_jobs(
        jobs, make_plan(), make_profile_stub(),
        within_locations=frozenset({"Bristol"}),
        remote_verdicts={"https://x.com/1": "not_remote"},
    )
    assert results[0].rejected is True
    assert results[0].reject_reason == "location uncertain and not confirmed fully remote: Remote"


def test_filter_jobs_remote_gate_preserves_other_flags():
    # remote_confirmed and employment_type_unknown can coexist.
    jobs = [make_job(location="Manchester", url="https://x.com/1",
                     employment_type=None, description="A management position.")]
    results = filter_jobs(
        jobs, make_plan(), make_profile_stub(),
        rejected_locations=frozenset({"Manchester"}),
        within_locations=frozenset(),
        remote_verdicts={"https://x.com/1": "remote"},
    )
    assert results[0].rejected is False
    assert "remote_confirmed" in results[0].flags
    assert "employment_type_unknown" in results[0].flags


def test_filter_jobs_no_remote_verdicts_unchanged():
    # Default call: uncertain locations still pass, outside still rejected.
    jobs = [
        make_job(location="Remote", employment_type="full-time"),
        make_job(location="Manchester", employment_type="full-time", url="https://x.com/2"),
    ]
    results = filter_jobs(
        jobs, make_plan(), make_profile_stub(),
        rejected_locations=frozenset({"Manchester"}),
    )
    remote_r = next(r for r in results if r.job.location == "Remote")
    manc_r = next(r for r in results if r.job.location == "Manchester")
    assert remote_r.rejected is False
    assert manc_r.rejected is True
    assert manc_r.reject_reason == "location outside radius: Manchester"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_filter.py -v -k remote`
Expected: FAIL with `TypeError: _check_location() got an unexpected keyword argument 'within_locations'`

- [ ] **Step 3: Implement**

In `src/job_search_email/filter.py`, add near the other module constants (after `_RECRUITMENT_REASON`):

```python
_REMOTE_CONFIRMED_FLAG = "remote_confirmed"
```

Replace `_check_location` with:

```python
def _check_location(
    job: JobListing,
    rejected_locations: frozenset[str],
    within_locations: frozenset[str] = frozenset(),
    remote_verdicts: dict[str, str] | None = None,
) -> FilteredResult | None:
    if remote_verdicts is None:
        # Legacy behaviour (include_remote off): only definite "outside"
        # verdicts reject; vague/uncertain locations pass through.
        if not job.location or job.location not in rejected_locations:
            return None
        return FilteredResult(
            job=job, flags=[], rejected=True,
            reject_reason=f"location outside radius: {job.location}",
        )

    # Remote gate (include_remote on): anything not confirmed within the
    # radius must be positively confirmed fully remote. A non-rejected
    # result signals pass-with-flags.
    if job.location and job.location in within_locations:
        return None

    verdict = remote_verdicts.get(job.url, "unverified")
    if verdict == "remote":
        return FilteredResult(
            job=job, flags=[_REMOTE_CONFIRMED_FLAG], rejected=False, reject_reason=None,
        )

    loc_label = job.location or "not stated"
    if verdict == "unverified":
        reason = f"remote check unavailable — cannot confirm fully remote ({loc_label})"
    elif job.location and job.location in rejected_locations:
        reason = f"location outside radius and not confirmed fully remote: {job.location}"
    else:
        reason = f"location uncertain and not confirmed fully remote: {loc_label}"
    return FilteredResult(job=job, flags=[], rejected=True, reject_reason=reason)
```

In `filter_jobs`, change the signature and the location block:

```python
def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    rejected_locations: frozenset[str] = frozenset(),
    recruitment_set: frozenset[str] | None = None,
    sponsor_set: frozenset[str] | None = None,
    within_locations: frozenset[str] = frozenset(),
    remote_verdicts: dict[str, str] | None = None,
) -> list[FilteredResult]:
    exclusion_roles = plan.exclusions.get("roles", [])
    results: list[FilteredResult] = []

    for job in jobs:
        loc_result = _check_location(job, rejected_locations, within_locations, remote_verdicts)
        if loc_result is not None and loc_result.rejected:
            results.append(loc_result)
            continue
        loc_flags = loc_result.flags if loc_result is not None else []
```

and change the final append to merge the location flags:

```python
        results.append(FilteredResult(
            job=job,
            flags=loc_flags + et_result.flags,
            rejected=False,
            reject_reason=None,
        ))
```

(Everything between — employment type, role, NHS band, salary, recruitment, sponsor checks — stays exactly as it is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_filter.py -v`
Expected: all PASS, including all pre-existing location tests (legacy path unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "feat: location gate requires confirmed fully-remote for far-afield jobs"
```

---

### Task 4: Pipeline wiring in `main.py`

**Files:**
- Modify: `src/job_search_email/main.py` (constants block ~line 30, `run_pipeline` ~lines 166-198)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `classify_remote`, `load_remote_cache`, `save_remote_cache` from Task 2; `filter_jobs(..., within_locations=, remote_verdicts=)` from Task 3; `profile.include_remote` from Task 1.
- Produces: `REMOTE_CACHE_PATH = ROOT / "remote_check_cache.json"` module constant (tests monkeypatch it like `LOCATION_CACHE_PATH`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py` (reuses the `_run_pipeline_capture_filter_call` helper pattern — note that helper patches `classify_locations` to return `{"Bristol": "within"}` and fetches one Bristol job):

```python
def _run_pipeline_remote(tmp_path, monkeypatch, profile, remote_return):
    """Like _run_pipeline_capture_filter_call but also patches classify_remote."""
    import sys, importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")
    monkeypatch.setattr(main_mod, "REMOTE_CACHE_PATH", tmp_path / "remote_cache.json")

    from job_search_email.models import JobListing, SearchPlan
    jobs = [
        JobListing(title="Local", company="NHS", location="Bristol",
                   salary_min=65000, description="", url="https://x.com/1",
                   source="reed", employment_type="full-time"),
        JobListing(title="Far", company="Acme Analytics", location="Manchester",
                   salary_min=65000, description="Fully remote in the UK.", url="https://x.com/2",
                   source="reed", employment_type="full-time"),
    ]
    plan = SearchPlan(profile_fingerprint="test", queries=["q"],
                      exclusions={"roles": [], "employment_types": []},
                      nhs_rules={}, evaluator_notes=[])

    with (
        patch("job_search_email.main.generate_search_plan", return_value=plan),
        patch("job_search_email.main.fetch_all_jobs", return_value=jobs),
        patch("job_search_email.main.classify_locations",
              return_value={"Bristol": "within", "Manchester": "outside"}),
        patch("job_search_email.main.score_jobs", return_value=[]),
        patch("job_search_email.main.filter_jobs", return_value=[]) as mock_filter,
        patch("job_search_email.main.classify_remote", return_value=remote_return) as mock_remote,
    ):
        main_mod.run_pipeline(profile, tmp_path / "out")

    return mock_filter.call_args.kwargs, mock_remote


def test_run_pipeline_remote_on_checks_far_jobs_and_passes_verdicts(tmp_path, monkeypatch):
    kwargs, mock_remote = _run_pipeline_remote(
        tmp_path, monkeypatch,
        make_profile(include_remote=True),
        remote_return={"https://x.com/2": "remote"},
    )
    checked_jobs = mock_remote.call_args.args[0]
    assert [j.url for j in checked_jobs] == ["https://x.com/2"]  # only the far-afield job
    assert kwargs["remote_verdicts"] == {"https://x.com/2": "remote"}
    assert kwargs["within_locations"] == frozenset({"Bristol"})
    assert (tmp_path / "remote_cache.json").exists()


def test_run_pipeline_remote_off_skips_check(tmp_path, monkeypatch):
    kwargs, mock_remote = _run_pipeline_remote(
        tmp_path, monkeypatch,
        make_profile(include_remote=False),
        remote_return={},
    )
    mock_remote.assert_not_called()
    assert kwargs["remote_verdicts"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -v -k remote`
Expected: `test_load_profile_include_remote_*` from Task 1 PASS; the two new pipeline tests FAIL with `AttributeError: <module 'job_search_email.main'> does not have the attribute 'classify_remote'` (or `REMOTE_CACHE_PATH` monkeypatch failure).

- [ ] **Step 3: Implement**

In `src/job_search_email/main.py`:

Add to the imports:

```python
from .remote_filter import classify_remote, load_remote_cache, save_remote_cache
```

Add to the path constants (after `LOCATION_CACHE_PATH`):

```python
REMOTE_CACHE_PATH = ROOT / "remote_check_cache.json"
```

In `run_pipeline`, directly after the `rejected_locations = ...` / `outside_count` block (after line 179), insert:

```python
    within_locations = frozenset(loc for loc, verdict in classification.items() if verdict == "within")
    remote_verdicts: dict[str, str] | None = None
    if profile.include_remote:
        print("Checking remote confirmation for far-afield jobs...")
        far_jobs = [j for j in jobs if not (j.location and j.location in within_locations)]
        remote_cache = load_remote_cache(REMOTE_CACHE_PATH)
        remote_verdicts = classify_remote(far_jobs, cache=remote_cache)
        save_remote_cache(remote_cache, REMOTE_CACHE_PATH)
        confirmed = sum(1 for v in remote_verdicts.values() if v == "remote")
        unverified = sum(1 for v in remote_verdicts.values() if v == "unverified")
        print(f"- {len(far_jobs)} far-afield job(s) checked, {confirmed} confirmed fully remote"
              + (f", {unverified} unverified (API error — rejected)" if unverified else ""))
```

And extend the `filter_jobs(...)` call:

```python
    filtered = filter_jobs(
        jobs, plan, profile,
        rejected_locations=rejected_locations,
        recruitment_set=recruitment_set,
        sponsor_set=sponsor_set,
        within_locations=within_locations,
        remote_verdicts=remote_verdicts,
    )
```

(Note: `within_locations` is always passed but only consulted when `remote_verdicts is not None`, per Task 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: all PASS (existing pipeline tests unaffected — profiles default to `include_remote=False`).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "feat: wire remote confirmation stage into run_pipeline"
```

---

### Task 5: jobspy UK-wide remote search leg

**Files:**
- Modify: `src/job_search_email/search_api/jobspy_searcher.py`
- Test: `tests/search_api/test_jobspy_searcher.py`

**Interfaces:**
- Consumes: `profile.include_remote` (Task 1).
- Produces: `search(query, profile)` unchanged signature; when `include_remote` is on it makes a second `scrape_jobs` call with `location="United Kingdom"`, `is_remote=True`, no `distance`, and concatenates results. A remote-leg failure must not lose the radius-leg results.

- [ ] **Step 1: Write the failing tests**

Append to `tests/search_api/test_jobspy_searcher.py`:

```python
REMOTE_PROFILE = make_profile(name="Jie", include_remote=True)


def test_search_remote_off_single_scrape_call():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame()) as mock_scrape:
        search("manager", PROFILE)
    assert mock_scrape.call_count == 1


def test_search_remote_on_adds_uk_wide_remote_leg():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame()) as mock_scrape:
        search("manager", REMOTE_PROFILE)

    assert mock_scrape.call_count == 2
    radius_kwargs = mock_scrape.call_args_list[0].kwargs
    remote_kwargs = mock_scrape.call_args_list[1].kwargs
    assert radius_kwargs["location"] == "Bristol"
    assert radius_kwargs["distance"] == 50
    assert remote_kwargs["location"] == "United Kingdom"
    assert remote_kwargs["is_remote"] is True
    assert remote_kwargs["search_term"] == "manager"
    assert remote_kwargs["country_indeed"] == "UK"
    assert "distance" not in remote_kwargs


def test_search_remote_on_concatenates_both_legs():
    remote_df = pd.DataFrame([{
        "site": "linkedin",
        "job_url": "https://linkedin.com/jobs/99",
        "title": "Remote Digital Lead",
        "company": "Acme Analytics",
        "location": "United Kingdom (Remote)",
        "description": "Fully remote role.",
        "min_amount": 70000.0,
        "max_amount": 80000.0,
        "job_type": "fulltime",
        "currency": "GBP",
    }])
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               side_effect=[SAMPLE_DF, remote_df]):
        result = search("manager", REMOTE_PROFILE)

    titles = {j.title for j in result}
    assert "Digital Transformation Manager" in titles  # radius leg
    assert "Remote Digital Lead" in titles             # remote leg


def test_search_remote_leg_failure_keeps_radius_results(capsys):
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               side_effect=[SAMPLE_DF, ConnectionError("linkedin down")]):
        result = search("manager", REMOTE_PROFILE)

    assert any(j.title == "Digital Transformation Manager" for j in result)
    assert "remote leg failed" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/search_api/test_jobspy_searcher.py -v`
Expected: the four new tests FAIL (`call_count == 1` where 2 expected, etc.); existing tests PASS.

- [ ] **Step 3: Implement**

Replace the top of `src/job_search_email/search_api/jobspy_searcher.py` (imports and `search`) with:

```python
import math
import re
import sys
from jobspy import scrape_jobs
from ..models import JobListing, Profile

_SALARY_RE = re.compile(r'£([\d,]+)(k)?', re.IGNORECASE)

_JOB_TYPE_MAP = {
    "fulltime": "full-time",
    "parttime": "part-time",
    "contract": "contract",
    "internship": "internship",
}


def _normalise_job_type(value: str) -> str | None:
    if not value:
        return None
    return _JOB_TYPE_MAP.get(value.lower(), value.lower())


def search(query: str, profile: Profile) -> list[JobListing]:
    frames = [scrape_jobs(
        site_name=["linkedin", "indeed"],
        search_term=query,
        location=profile.location,
        distance=50,
        results_wanted=50,
        country_indeed="UK",
    )]

    if profile.include_remote:
        # UK-wide remote leg. Failure here must not lose the radius results.
        try:
            frames.append(scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location="United Kingdom",
                is_remote=True,
                results_wanted=50,
                country_indeed="UK",
            ))
        except Exception as exc:
            print(f"[jobspy_searcher] remote leg failed for {query!r}: {exc}", file=sys.stderr)

    results = []
    for df in frames:
        if df.empty:
            continue
        for _, row in df.iterrows():
            salary_min = _extract_salary_min(row)
            if salary_min is not None and salary_min < profile.min_salary:
                continue

            results.append(JobListing(
                title=_str(row.get("title")),
                company=_str(row.get("company")),
                location=_str(row.get("location")),
                salary_min=salary_min,
                description=_str(row.get("description")),
                url=_str(row.get("job_url")),
                source=_str(row.get("site")).lower(),
                employment_type=_normalise_job_type(_str(row.get("job_type"))),
            ))

    return results
```

(`_str` and `_extract_salary_min` stay unchanged below.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/search_api/test_jobspy_searcher.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/search_api/jobspy_searcher.py tests/search_api/test_jobspy_searcher.py
git commit -m "feat: add UK-wide is_remote jobspy search leg for include_remote profiles"
```

---

### Task 6: Reed UK-wide remote search leg

**Files:**
- Modify: `src/job_search_email/search_api/reed.py`
- Test: `tests/search_api/test_reed.py`

**Interfaces:**
- Consumes: `profile.include_remote` (Task 1).
- Produces: `search(query, profile)` unchanged signature; when `include_remote` is on it makes a second GET with `keywords=f"{query} remote"`, **no** `locationName`/`distancefromLocation`, same `minimumSalary`/`resultsToTake`. Remote-leg failure keeps radius results.

- [ ] **Step 1: Write the failing tests**

Append to `tests/search_api/test_reed.py`:

```python
REMOTE_PROFILE = make_profile(name="Jie", include_remote=True)


def test_search_remote_off_single_request(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_resp.raise_for_status.return_value = None
    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp) as mock_get:
        search("manager", PROFILE)
    assert mock_get.call_count == 1


def test_search_remote_on_adds_uk_wide_leg(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_resp.raise_for_status.return_value = None
    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp) as mock_get:
        search("business manager", REMOTE_PROFILE)

    assert mock_get.call_count == 2
    radius_params = mock_get.call_args_list[0].kwargs["params"]
    remote_params = mock_get.call_args_list[1].kwargs["params"]
    assert radius_params["locationName"] == "Bristol"
    assert remote_params["keywords"] == "business manager remote"
    assert "locationName" not in remote_params
    assert "distancefromLocation" not in remote_params
    assert remote_params["minimumSalary"] == 60000
    assert remote_params["resultsToTake"] == 100


def test_search_remote_on_concatenates_results(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    remote_item = {**REED_RESPONSE["results"][0],
                   "jobTitle": "Remote Digital Lead",
                   "locationName": "Remote",
                   "jobUrl": "https://www.reed.co.uk/jobs/remote-digital-lead/99"}
    radius_resp = MagicMock()
    radius_resp.json.return_value = REED_RESPONSE
    radius_resp.raise_for_status.return_value = None
    remote_resp = MagicMock()
    remote_resp.json.return_value = {"results": [remote_item]}
    remote_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get",
               side_effect=[radius_resp, remote_resp]):
        result = search("manager", REMOTE_PROFILE)

    titles = {j.title for j in result}
    assert titles == {"Digital Transformation Manager", "Remote Digital Lead"}


def test_search_remote_leg_failure_keeps_radius_results(monkeypatch, capsys):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    radius_resp = MagicMock()
    radius_resp.json.return_value = REED_RESPONSE
    radius_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get",
               side_effect=[radius_resp, ConnectionError("reed down")]):
        result = search("manager", REMOTE_PROFILE)

    assert len(result) == 1
    assert result[0].title == "Digital Transformation Manager"
    assert "remote leg failed" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/search_api/test_reed.py -v`
Expected: new tests FAIL (single call made where two expected); existing tests PASS.

- [ ] **Step 3: Implement**

Replace `search` in `src/job_search_email/search_api/reed.py` (add `import sys` to the imports):

```python
import os
import sys
import requests
from ..models import JobListing, Profile

_REED_URL = "https://www.reed.co.uk/api/1.0/search"


def _fetch(params: dict, api_key: str) -> list[JobListing]:
    response = requests.get(_REED_URL, params=params, auth=(api_key, ""), timeout=30)
    response.raise_for_status()
    return [_to_listing(item) for item in response.json().get("results", [])]


def search(query: str, profile: Profile) -> list[JobListing]:
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        raise ValueError("REED_API_KEY environment variable is not set")

    listings = _fetch({
        "keywords": query,
        "locationName": profile.location,
        "distancefromLocation": 50,
        "minimumSalary": profile.min_salary,
        "resultsToTake": 100,
    }, api_key)

    if profile.include_remote:
        # UK-wide remote leg: no location constraint, keyword-biased towards
        # remote listings. Failure here must not lose the radius results.
        try:
            listings += _fetch({
                "keywords": f"{query} remote",
                "minimumSalary": profile.min_salary,
                "resultsToTake": 100,
            }, api_key)
        except Exception as exc:
            print(f"[reed] remote leg failed for {query!r}: {exc}", file=sys.stderr)

    return listings
```

(`_to_listing` and `_parse_employment_type` stay unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/search_api/test_reed.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/search_api/reed.py tests/search_api/test_reed.py
git commit -m "feat: add UK-wide remote Reed search leg for include_remote profiles"
```

---

### Task 7: Remote verdict in filter trace and explain-job

**Files:**
- Modify: `src/job_search_email/filter_trace.py:22-41` (`run_filter_gates` location gate)
- Modify: `src/job_search_email/explain_job.py:58-76` (`explain`)
- Test: `tests/test_filter_trace.py`

**Interfaces:**
- Consumes: `_check_location` gate mode + `"remote_confirmed"` flag (Task 3); `classify_remote` (Task 2); `profile.include_remote` (Task 1).
- Produces: `run_filter_gates(..., remote_verdict: str | None = None)` keyword arg. `None` → legacy trace. Otherwise the Location gate applies the remote gate to this single job using `{job.url: remote_verdict}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filter_trace.py` (match the file's existing helper/style — it tests `run_filter_gates` with constructed jobs; reuse its existing job/profile helpers if present, otherwise define locally as below):

```python
from job_search_email.filter_trace import run_filter_gates
from job_search_email.models import JobListing
from profile_helpers import make_profile


def _remote_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Digital Manager", company="Acme Analytics Ltd", location="Manchester",
        salary_min=70000, description="", url="https://x.com/1",
        source="reed", employment_type="permanent",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def test_gates_remote_verdict_confirmed_passes_location():
    gates = run_filter_gates(
        _remote_job(), make_profile(),
        location_verdict="outside", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
        remote_verdict="remote",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is True
    assert "confirmed fully remote" in loc.detail


def test_gates_remote_verdict_not_remote_rejects_location():
    gates = run_filter_gates(
        _remote_job(), make_profile(),
        location_verdict="outside", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
        remote_verdict="not_remote",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is False
    assert loc.is_first_reject is True
    assert loc.detail == "location outside radius and not confirmed fully remote: Manchester"


def test_gates_remote_verdict_unverified_fails_closed():
    gates = run_filter_gates(
        _remote_job(), make_profile(),
        location_verdict="uncertain", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
        remote_verdict="unverified",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is False
    assert "remote check unavailable" in loc.detail


def test_gates_no_remote_verdict_keeps_legacy_detail():
    gates = run_filter_gates(
        _remote_job(location="Bristol"), make_profile(),
        location_verdict="within", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is True
    assert loc.detail == "within radius (Bristol)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_filter_trace.py -v`
Expected: new tests FAIL with `TypeError: run_filter_gates() got an unexpected keyword argument 'remote_verdict'`; existing tests PASS.

- [ ] **Step 3: Implement**

In `src/job_search_email/filter_trace.py`, change the signature and the Location block:

```python
def run_filter_gates(
    job: JobListing,
    profile: Profile,
    *,
    location_verdict: str,
    sponsor_set: frozenset[str] | None,
    nhs_rules: dict,
    exclusion_roles: list[str],
    remote_verdict: str | None = None,
) -> list[GateResult]:
    gates: list[GateResult] = []

    # Location — reuse the real gate by deriving the location sets from the verdict.
    rejected_locations = frozenset({job.location}) if location_verdict == "outside" else frozenset()
    if remote_verdict is None:
        loc = _check_location(job, rejected_locations)
    else:
        within_locations = frozenset({job.location}) if location_verdict == "within" else frozenset()
        loc = _check_location(job, rejected_locations, within_locations, {job.url: remote_verdict})

    if loc is not None and loc.rejected:
        loc_detail = loc.reject_reason or ""
    elif loc is not None and "remote_confirmed" in loc.flags:
        loc_detail = f"{location_verdict} radius, confirmed fully remote ({job.location or 'not stated'})"
    else:
        loc_detail = f"{location_verdict} radius ({job.location or 'not stated'})"
    gates.append(GateResult("Location", loc is None or not loc.rejected, loc_detail, False))
```

(The rest of the function is unchanged.)

In `src/job_search_email/explain_job.py`:

Add to imports:

```python
from .remote_filter import classify_remote
```

After the location-verdict block (after line 64) and before the `sponsor_set` line, insert:

```python
    # NOTE: classify_remote also makes a live LLM call (needs ANTHROPIC_API_KEY);
    # it only runs for include_remote profiles on far-afield jobs.
    remote_verdict = None
    if profile.include_remote and verdict != "within":
        remote_verdict = classify_remote([job], cache={}).get(job.url, "unverified")
```

And pass it through:

```python
    gates = run_filter_gates(
        job, profile,
        location_verdict=verdict,
        sponsor_set=sponsor_set,
        nhs_rules=get_nhs_rules(),
        exclusion_roles=get_exclusions(profile)["roles"],
        remote_verdict=remote_verdict,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_filter_trace.py tests/test_explain_job.py -v`
Expected: all PASS (explain_job tests unaffected: default profiles have `include_remote=False` so `remote_verdict` stays `None`).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/filter_trace.py src/job_search_email/explain_job.py tests/test_filter_trace.py
git commit -m "feat: surface remote-confirmation verdict in filter trace and explain-job"
```

---

### Task 8: Remote badge in the email

**Files:**
- Modify: `src/job_search_email/email.py:53-75` (`build_email_html` row loop)
- Test: `tests/test_email.py`

**Interfaces:**
- Consumes: the `"remote_confirmed"` flag on `ScoredResult.flags` (carried from `FilteredResult.flags` by the existing scorer passthrough).
- Produces: a `Remote` badge next to the job title for flagged rows. No signature changes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email.py` (reuse the file's existing result-building helpers if present; otherwise this self-contained test):

```python
from job_search_email.email import build_email_html
from job_search_email.models import JobAnalysis, JobListing, ScoredResult
from profile_helpers import make_profile


def _scored(flags: list[str]) -> ScoredResult:
    job = JobListing(
        title="Digital Lead", company="Acme Analytics", location="Remote (UK)",
        salary_min=70000, description="", url="https://x.com/1",
        source="reed", employment_type="permanent",
    )
    analysis = JobAnalysis(score=8, matched_skills=[], missing_essentials=[],
                           employment_type_note="", verdict="Good fit")
    return ScoredResult(job=job, flags=flags, rejected=False, reject_reason=None, analysis=analysis)


def test_email_shows_remote_badge_for_confirmed_remote():
    html, _ = build_email_html([_scored(["remote_confirmed"])], make_profile())
    assert ">Remote</span>" in html


def test_email_no_remote_badge_without_flag():
    html, _ = build_email_html([_scored([])], make_profile())
    assert ">Remote</span>" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_email.py -v -k remote`
Expected: `test_email_shows_remote_badge_for_confirmed_remote` FAILS (no badge in HTML); the negative test passes.

- [ ] **Step 3: Implement**

In `src/job_search_email/email.py`, add after `_score_badge`:

```python
_REMOTE_BADGE = (
    ' <span style="background:#17a2b8; color:#ffffff; padding:2px 6px; '
    'border-radius:4px; font-size:11px;">Remote</span>'
)
```

In the row loop of `build_email_html`, change the title cell:

```python
        remote = _REMOTE_BADGE if "remote_confirmed" in r.flags else ""
```

and in the `rows.append(...)` f-string, replace the title `<td>`:

```python
            f'<td {cell}><a href="{_escape(r.job.url, quote=True)}" style="color:#0066cc; text-decoration:none;">{_escape(r.job.title)}</a>{remote}</td>'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_email.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/email.py tests/test_email.py
git commit -m "feat: show Remote badge in email for confirmed fully-remote jobs"
```

---

### Task 9: Offline fixtures exercise the remote gate

**Files:**
- Modify: `src/job_search_email/fixtures.py`
- Modify: `src/job_search_email/local_run.py:84-90` (`main`)
- Test: `tests/test_local_testing.py`

**Interfaces:**
- Consumes: `filter_jobs(..., within_locations=, remote_verdicts=)` (Task 3).
- Produces:
  - `fixture_location_classification() -> dict[str, str]` — `{"Bristol": "within", "Remote (UK)": "uncertain", "Manchester": "outside"}` (covers every fixture-job location).
  - `fixture_remote_verdicts() -> dict[str, str]` — URL-keyed verdicts for the two new far-afield fixture jobs.
  - Two new fixture jobs (URLs below) so the offline dry run shows one confirmed-remote keep and one far-afield reject.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_local_testing.py`:

```python
from job_search_email.filter import filter_jobs
from job_search_email.fixtures import (
    fixture_jobs,
    fixture_location_classification,
    fixture_remote_verdicts,
)


def _remote_gate_results():
    from job_search_email.models import SearchPlan
    from profile_helpers import make_profile
    classification = fixture_location_classification()
    plan = SearchPlan(profile_fingerprint="fp", queries=[],
                      exclusions={"roles": [], "employment_types": []},
                      nhs_rules={}, evaluator_notes=[])
    return filter_jobs(
        fixture_jobs(), plan, make_profile(),
        rejected_locations=frozenset(l for l, v in classification.items() if v == "outside"),
        within_locations=frozenset(l for l, v in classification.items() if v == "within"),
        remote_verdicts=fixture_remote_verdicts(),
    )


def test_fixture_confirmed_remote_job_kept_with_flag():
    results = _remote_gate_results()
    remote = next(r for r in results if r.job.location == "Remote (UK)")
    assert remote.rejected is False
    assert "remote_confirmed" in remote.flags


def test_fixture_far_afield_hybrid_job_rejected():
    results = _remote_gate_results()
    manc = next(r for r in results if r.job.location == "Manchester")
    assert manc.rejected is True
    assert manc.reject_reason == "location outside radius and not confirmed fully remote: Manchester"


def test_fixture_classification_covers_all_fixture_locations():
    covered = set(fixture_location_classification())
    assert {j.location for j in fixture_jobs()} <= covered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_local_testing.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'fixture_location_classification'`; existing tests PASS.

- [ ] **Step 3: Implement**

In `src/job_search_email/fixtures.py`:

Append two entries to the `fixture_jobs()` return list:

```python
        JobListing(
            title="Head of Digital Transformation (Remote)",
            company="Acme Analytics",
            location="Remote (UK)",
            salary_min=78000,
            description=(
                "Lead our digital transformation practice. This role is fully remote "
                "within the UK, with quarterly team days in London. Permanent, full-time."
            ),
            url="https://www.reed.co.uk/jobs/head-of-digital-remote/12345681",
            source="reed",
            employment_type="permanent",
        ),
        JobListing(
            title="Senior Business Manager",
            company="KPMG UK",
            location="Manchester",
            salary_min=72000,
            description=(
                "Senior business manager role with hybrid working — three days per week "
                "in our Manchester office. Permanent, full-time."
            ),
            url="https://www.reed.co.uk/jobs/senior-business-manager-manchester/12345682",
            source="reed",
            employment_type="permanent",
        ),
```

Add to `_FIXTURE_ANALYSES`:

```python
    "https://www.reed.co.uk/jobs/head-of-digital-remote/12345681": JobAnalysis(
        score=8,
        matched_skills=["digital transformation", "Business Strategy"],
        missing_essentials=[],
        employment_type_note="Permanent full-time, fully remote — matches preference.",
        verdict="Strong match. Confirmed fully-remote senior digital transformation role.",
    ),
```

Add two functions at the end of the file:

```python
def fixture_location_classification() -> dict[str, str]:
    return {
        "Bristol": "within",
        "Remote (UK)": "uncertain",
        "Manchester": "outside",
    }


def fixture_remote_verdicts() -> dict[str, str]:
    return {
        "https://www.reed.co.uk/jobs/head-of-digital-remote/12345681": "remote",
        "https://www.reed.co.uk/jobs/senior-business-manager-manchester/12345682": "not_remote",
    }
```

In `src/job_search_email/local_run.py`:

Extend the fixtures import:

```python
from .fixtures import (
    fixture_jobs,
    fixture_location_classification,
    fixture_queries,
    fixture_remote_verdicts,
    fixture_scores,
)
```

Replace the `filtered = filter_jobs(jobs, plan, profile)` line in `main()` with:

```python
    # The offline run always exercises the remote gate with fixture verdicts,
    # regardless of the profile's include_remote flag — no network involved.
    classification = fixture_location_classification()
    filtered = filter_jobs(
        jobs, plan, profile,
        rejected_locations=frozenset(l for l, v in classification.items() if v == "outside"),
        within_locations=frozenset(l for l, v in classification.items() if v == "within"),
        remote_verdicts=fixture_remote_verdicts(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_local_testing.py -v`
Expected: all PASS. If any existing test in this file asserts exact fixture counts (e.g. kept/rejected totals), update those counts for the two new fixture jobs (one kept, one rejected) — the assertion intent stays the same.

- [ ] **Step 5: Smoke-run the offline dry run**

Run: `python -c "from job_search_email.local_run import main; main()"` (or `job-search-email-local` if the venv script is installed)
Expected: prints `[local-test] filtered: 4 kept, 3 rejected` (2 previous keeps + remote fixture + previous rejects + Manchester fixture) and writes `email_preview.html` containing the `Remote` badge. Verify: open `email_preview.html` and check "Head of Digital Transformation (Remote)" row shows the badge.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/fixtures.py src/job_search_email/local_run.py tests/test_local_testing.py
git commit -m "feat: exercise remote gate in offline fixture run"
```

---

### Task 10: Documentation and full verification

**Files:**
- Modify: `CLAUDE.md` (repo root)
- Modify: `src/job_search_email/search_api/CLAUDE.md`

**Interfaces:** none (docs only), but this task also runs the full test suite as the final gate.

- [ ] **Step 1: Update root `CLAUDE.md`**

In the first paragraph block (after the sentence about `filter_sponsors: false`), add:

```markdown
Profiles can opt in to UK-wide remote search with `include_remote: true` (default false): the searchers add a UK-wide remote leg, and any job not confirmed within the radius is kept only if an LLM check positively confirms the posting is fully remote (verdicts cached in `remote_check_cache.json`). Silence or hybrid wording rejects the job.
```

- [ ] **Step 2: Update `src/job_search_email/search_api/CLAUDE.md`**

- In the jobspy table/notes: move `is_remote` out of the "not currently used" list and document: `is_remote=True` + `location="United Kingdom"` used for the UK-wide remote leg when the profile sets `include_remote: true`.
- In the Reed section: document the second call (`keywords="<query> remote"`, no `locationName`/`distancefromLocation`) for `include_remote` profiles.
- In the NHS section: note NHS gets no remote leg because descriptions are empty and can never pass remote confirmation.
- Update the "Key Gap to Note" paragraph: remote-only is now used; employment type, posting date, and contract type remain unused.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest`
Expected: all tests PASS. Fix any stragglers before committing (most likely candidates: fixture-count assertions in `tests/test_local_testing.py` or `tests/test_debug_run.py`).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/job_search_email/search_api/CLAUDE.md
git commit -m "docs: document include_remote flag and remote search legs"
```

---

## Post-implementation note (for the human)

The feature ships **off** for both profiles. To turn it on for a person, add `include_remote: true` to their file under `profiles/` — this also invalidates their cached search plan and score cache (fingerprint change), which is expected. Decide with Marc which profile(s) to enable.
