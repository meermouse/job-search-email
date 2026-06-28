# Location Debug Summary and Claude-Based Location Filter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a console location breakdown after job fetching, and a Claude-powered location classifier that rejects jobs from locations clearly outside the search radius.

**Architecture:** A new `location_filter.py` module handles Claude classification and per-location caching. `filter.py` gains a `rejected_locations` parameter used in a new `_check_location` step. `main.py` wires them together: print summary → classify → filter. Unknown/ambiguous locations are always allowed through; only explicit "outside" verdicts trigger rejection.

**Tech Stack:** Python 3.11+, `anthropic` SDK (already in project), `pytest` for tests.

## Global Constraints

- Model for classifier: `claude-haiku-4-5-20251001` (same as scorer — use `SCORER_MODEL` env var pattern if needed, but hardcode the same default)
- Cache file follows existing pattern: atomic write via `.tmp` + `os.replace`
- `filter_jobs` signature change must be backwards-compatible (new param has default `frozenset()`)
- Do not add geocoding libraries — classification is done entirely by Claude
- All location cache keys are `"{home}:{radius}:{location}"` strings; values are `"within" | "outside" | "uncertain"`
- Test files use `unittest.mock.patch` for Claude calls (matching `test_scorer.py` pattern)

---

## File Map

| File | Change |
|------|--------|
| `src/job_search_email/location_filter.py` | **Create** — Claude classifier, cache load/save, summary printer |
| `src/job_search_email/filter.py` | **Modify** — add `_check_location` + `rejected_locations` param to `filter_jobs` |
| `src/job_search_email/main.py` | **Modify** — call classifier, print summary, pass `rejected_locations` to `filter_jobs` |
| `tests/test_location_filter.py` | **Create** — unit tests for classifier and cache |
| `tests/test_filter.py` | **Modify** — tests for `_check_location` and `filter_jobs` with `rejected_locations` |

---

### Task 1: Console location summary in `main.py`

**Files:**
- Modify: `src/job_search_email/main.py` (after the `fetch_all_jobs` call, around line 159)

**Interfaces:**
- Consumes: `jobs: list[JobListing]` (already available after `fetch_all_jobs`)
- Produces: nothing — side effect only (stdout)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py  — add this test to the existing file
# (no new imports needed beyond what's already there)

from collections import Counter

def test_print_location_summary_outputs_counts(capsys):
    from job_search_email.main import _print_location_summary
    from job_search_email.models import JobListing

    def make_job(location, source):
        return JobListing(
            title="Manager", company="Corp", location=location,
            salary_min=60000, description="", url="https://x.com",
            source=source, employment_type="full-time",
        )

    jobs = [
        make_job("Bristol, BS1", "reed"),
        make_job("Bristol, BS1", "reed"),
        make_job("Reading, RG1", "linkedin"),
        make_job("Bath, BA1", "indeed"),
    ]

    _print_location_summary(jobs)
    out = capsys.readouterr().out

    assert "Bristol, BS1" in out
    assert "Reading, RG1" in out
    assert "Bath, BA1" in out
    assert "reed" in out
    assert "linkedin" in out
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_main.py::test_print_location_summary_outputs_counts -v
```

Expected: `FAILED` — `ImportError: cannot import name '_print_location_summary'`

- [ ] **Step 3: Add `_print_location_summary` to `main.py`**

Add this function before the `main()` function in `src/job_search_email/main.py`:

```python
from collections import Counter, defaultdict

def _print_location_summary(jobs: list[JobListing]) -> None:
    by_location: dict[str, Counter] = defaultdict(Counter)
    for job in jobs:
        by_location[job.location or "(blank)"][job.source] += 1

    total = len(jobs)
    print(f"[main] Location breakdown ({total} jobs fetched):")
    for location, sources in sorted(by_location.items(), key=lambda x: -sum(x[1].values())):
        count = sum(sources.values())
        source_detail = ", ".join(f"{s}: {n}" for s, n in sorted(sources.items()))
        print(f"  {location:<40} {count:>4}  ({source_detail})")
```

Also add the import `from collections import Counter, defaultdict` near the top of `main.py` (after the existing stdlib imports).

- [ ] **Step 4: Call it in `main()` after fetching**

In `main.py`, find the block that prints `"- jobs fetched: {len(jobs)}"` and add the call immediately after:

```python
    jobs = fetch_all_jobs(plan, profile)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump([asdict(job) for job in jobs], handle, indent=2)
    print(f"- jobs fetched: {len(jobs)}")
    print(f"- results written to: {RESULTS_PATH}")
    _print_location_summary(jobs)   # ← add this line
    print("Filtering jobs...")
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_main.py::test_print_location_summary_outputs_counts -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "feat: print location breakdown after job fetch"
```

---

### Task 2: `location_filter.py` — Claude classifier with per-location cache

**Files:**
- Create: `src/job_search_email/location_filter.py`
- Create: `tests/test_location_filter.py`

**Interfaces:**
- Produces for Task 3:
  - `classify_locations(locations: list[str], home: str, radius_miles: int, cache: dict[str, str]) -> dict[str, str]`
    - Returns a classification dict: `{location_string: "within" | "outside" | "uncertain"}`
    - Cache is mutated in-place with new verdicts
  - `load_location_cache(path: Path) -> dict[str, str]`
  - `save_location_cache(cache: dict[str, str], path: Path) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_location_filter.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_search_email.location_filter import (
    classify_locations,
    load_location_cache,
    save_location_cache,
)


def _mock_claude_response(payload: dict) -> MagicMock:
    block = MagicMock()
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def test_classify_locations_uses_cache_for_known_locations():
    cache = {"Bristol:50:Bath, BA1": "within", "Bristol:50:London": "outside"}
    with patch("job_search_email.location_filter.client") as mock_client:
        result = classify_locations(["Bath, BA1", "London"], home="Bristol", radius_miles=50, cache=cache)
    mock_client.messages.create.assert_not_called()
    assert result["Bath, BA1"] == "within"
    assert result["London"] == "outside"


def test_classify_locations_calls_claude_for_unknown():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({
            "Reading, RG1": "outside",
            "Bath, BA1": "within",
        })
        result = classify_locations(
            ["Reading, RG1", "Bath, BA1"], home="Bristol", radius_miles=50, cache=cache
        )
    mock_client.messages.create.assert_called_once()
    assert result["Reading, RG1"] == "outside"
    assert result["Bath, BA1"] == "within"


def test_classify_locations_updates_cache_after_claude_call():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({
            "Reading, RG1": "outside",
        })
        classify_locations(["Reading, RG1"], home="Bristol", radius_miles=50, cache=cache)
    assert cache["Bristol:50:Reading, RG1"] == "outside"


def test_classify_locations_treats_invalid_json_as_uncertain():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        block = MagicMock()
        block.text = "not valid json"
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_locations(["Reading, RG1"], home="Bristol", radius_miles=50, cache=cache)
    assert result["Reading, RG1"] == "uncertain"


def test_classify_locations_defaults_missing_keys_to_uncertain():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({})
        result = classify_locations(["Remote"], home="Bristol", radius_miles=50, cache=cache)
    assert result["Remote"] == "uncertain"


def test_load_location_cache_returns_empty_dict_when_file_missing(tmp_path):
    result = load_location_cache(tmp_path / "no_file.json")
    assert result == {}


def test_load_location_cache_reads_existing_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"Bristol:50:Bath": "within"}), encoding="utf-8")
    result = load_location_cache(path)
    assert result == {"Bristol:50:Bath": "within"}


def test_save_location_cache_writes_atomically(tmp_path):
    path = tmp_path / "cache.json"
    save_location_cache({"Bristol:50:Bath": "within"}, path)
    assert path.exists()
    assert not (tmp_path / "cache.tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"Bristol:50:Bath": "within"}
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_location_filter.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'job_search_email.location_filter'`

- [ ] **Step 3: Implement `location_filter.py`**

Create `src/job_search_email/location_filter.py`:

```python
import json
import os
from pathlib import Path

import anthropic

client = anthropic.Anthropic()

_MODEL = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")

_SYSTEM_PROMPT = (
    "You are a UK geography expert. Given a home city, a radius in miles, and a list of "
    "location strings from job listings, classify each string as:\n"
    '- "within": the location is clearly within the radius\n'
    '- "outside": the location is clearly outside the radius\n'
    '- "uncertain": the location is ambiguous, vague (e.g. "Remote", "United Kingdom", '
    '"Hybrid"), or too obscure to judge confidently\n\n'
    "When in doubt, use uncertain — it is always safer to allow a job through than to "
    "incorrectly reject it.\n"
    "Respond only with valid JSON: an object mapping each input string to its verdict."
)


def _cache_key(home: str, radius_miles: int, location: str) -> str:
    return f"{home}:{radius_miles}:{location}"


def classify_locations(
    locations: list[str],
    home: str,
    radius_miles: int,
    cache: dict[str, str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    to_classify: list[str] = []

    for loc in locations:
        key = _cache_key(home, radius_miles, loc)
        if key in cache:
            result[loc] = cache[key]
        else:
            to_classify.append(loc)

    if not to_classify:
        return result

    try:
        user_message = (
            f"Home location: {home}. Radius: {radius_miles} miles.\n"
            f"Classify these locations:\n{json.dumps(to_classify, ensure_ascii=False)}"
        )
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text if response.content else ""
        verdicts: dict[str, str] = json.loads(text)
    except Exception:
        verdicts = {}

    for loc in to_classify:
        verdict = verdicts.get(loc, "uncertain")
        if verdict not in ("within", "outside", "uncertain"):
            verdict = "uncertain"
        result[loc] = verdict
        cache[_cache_key(home, radius_miles, loc)] = verdict

    return result


def load_location_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_location_cache(cache: dict[str, str], path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_location_filter.py -v
```

Expected: all 8 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/location_filter.py tests/test_location_filter.py
git commit -m "feat: add Claude-based location classifier with per-location cache"
```

---

### Task 3: Add `_check_location` to `filter.py`

**Files:**
- Modify: `src/job_search_email/filter.py`
- Modify: `tests/test_filter.py`

**Interfaces:**
- Consumes from Task 2: `rejected_locations: frozenset[str]` — the set of location strings classified as "outside"
- Produces: `filter_jobs` now accepts optional `rejected_locations: frozenset[str] = frozenset()`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filter.py`:

```python
from job_search_email.filter import _check_location, filter_jobs


def test_check_location_rejects_outside_location():
    job = make_job(location="Reading, RG1")
    result = _check_location(job, rejected_locations=frozenset({"Reading, RG1"}))
    assert result is not None
    assert result.rejected is True
    assert result.reject_reason == "location outside radius: Reading, RG1"


def test_check_location_passes_within_location():
    job = make_job(location="Bath, BA1")
    result = _check_location(job, rejected_locations=frozenset({"Reading, RG1"}))
    assert result is None


def test_check_location_passes_empty_rejected_set():
    job = make_job(location="Reading, RG1")
    result = _check_location(job, rejected_locations=frozenset())
    assert result is None


def test_check_location_passes_blank_location():
    job = make_job(location="")
    result = _check_location(job, rejected_locations=frozenset({""}))
    assert result is None


def test_filter_jobs_rejects_outside_location():
    jobs = [
        make_job(employment_type="full-time", location="Reading, RG1"),
        make_job(employment_type="full-time", location="Bath, BA1"),
    ]
    plan = SearchPlan(
        profile_fingerprint="fp",
        queries=[],
        exclusions={"roles": []},
        nhs_rules={},
        evaluator_notes=[],
    )
    profile = Profile(
        name="Test", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=["full-time"],
        location="Bristol", min_salary=0,
    )
    results = filter_jobs(
        jobs, plan, profile,
        rejected_locations=frozenset({"Reading, RG1"}),
    )
    reading_result = next(r for r in results if r.job.location == "Reading, RG1")
    bath_result = next(r for r in results if r.job.location == "Bath, BA1")
    assert reading_result.rejected is True
    assert reading_result.reject_reason == "location outside radius: Reading, RG1"
    assert bath_result.rejected is False


def test_filter_jobs_default_no_location_rejection():
    jobs = [make_job(employment_type="full-time", location="Reading, RG1")]
    plan = SearchPlan(
        profile_fingerprint="fp", queries=[],
        exclusions={"roles": []}, nhs_rules={}, evaluator_notes=[],
    )
    profile = Profile(
        name="Test", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=["full-time"],
        location="Bristol", min_salary=0,
    )
    results = filter_jobs(jobs, plan, profile)
    assert results[0].rejected is False
```

Note: `SearchPlan` and `Profile` imports are already in `test_filter.py` — check the top of that file and add any missing imports.

- [ ] **Step 2: Check existing imports in `test_filter.py`**

Read the top of `tests/test_filter.py` and add any missing imports:

```python
from job_search_email.models import FilteredResult, JobListing, SearchPlan, Profile
from job_search_email.filter import _check_location, filter_jobs
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_filter.py::test_check_location_rejects_outside_location tests/test_filter.py::test_filter_jobs_rejects_outside_location -v
```

Expected: `FAILED` — `ImportError: cannot import name '_check_location'`

- [ ] **Step 4: Implement `_check_location` and update `filter_jobs` signature**

In `src/job_search_email/filter.py`, add `_check_location` after the existing `_check_nhs_band_salary` function:

```python
def _check_location(job: JobListing, rejected_locations: frozenset[str]) -> FilteredResult | None:
    if not job.location or job.location not in rejected_locations:
        return None
    return FilteredResult(
        job=job, flags=[], rejected=True,
        reject_reason=f"location outside radius: {job.location}",
    )
```

Update the `filter_jobs` signature and body to add the location check as the **first** step (before employment type — no point running other checks on a geographically invalid job):

```python
def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    rejected_locations: frozenset[str] = frozenset(),
) -> list[FilteredResult]:
    exclusion_roles = plan.exclusions.get("roles", [])
    results: list[FilteredResult] = []

    for job in jobs:
        loc_result = _check_location(job, rejected_locations)
        if loc_result is not None:
            results.append(loc_result)
            continue

        et_result = _check_employment_type(job)
        if et_result.rejected:
            results.append(et_result)
            continue

        role_result = _check_role_suitability(job, exclusion_roles)
        if role_result is not None:
            results.append(role_result)
            continue

        nhs_result = _check_nhs_band_salary(job, plan.nhs_rules, profile.min_salary)
        if nhs_result is not None:
            results.append(nhs_result)
            continue

        results.append(FilteredResult(
            job=job,
            flags=et_result.flags,
            rejected=False,
            reject_reason=None,
        ))

    return results
```

- [ ] **Step 5: Run all filter tests**

```
pytest tests/test_filter.py -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "feat: add location filter step to filter_jobs pipeline"
```

---

### Task 4: Wire everything together in `main.py`

**Files:**
- Modify: `src/job_search_email/main.py`

**Interfaces:**
- Consumes from Task 2: `classify_locations`, `load_location_cache`, `save_location_cache` from `location_filter`
- Consumes from Task 3: updated `filter_jobs(... rejected_locations=...)`

- [ ] **Step 1: Write the failing integration test**

In `tests/test_main.py`, find the existing integration test (likely around `test_main_runs_end_to_end` or similar). Add a test that verifies location cache is loaded and saved:

```python
from unittest.mock import patch, MagicMock, call
import json


def test_main_loads_and_saves_location_cache(tmp_path, monkeypatch):
    """Location cache is loaded before classify and saved after."""
    import job_search_email.main as main_mod

    # Point all file paths to tmp_path
    monkeypatch.setattr(main_mod, "ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "PLAN_PATH", tmp_path / "plan.json")
    monkeypatch.setattr(main_mod, "RESULTS_PATH", tmp_path / "results.json")
    monkeypatch.setattr(main_mod, "FILTERED_RESULTS_PATH", tmp_path / "filtered.json")
    monkeypatch.setattr(main_mod, "SCORED_RESULTS_PATH", tmp_path / "scored.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")

    # Write a minimal profile.yaml
    (tmp_path / "profile.yaml").write_text(
        "profile:\n  name: Test\n  current_role: ''\n  about: ''\n"
        "  seniority: ''\n  industry: ''\n  skills: []\n  previous_roles: []\n"
        "  target_roles: []\n  open_to: []\n  not_open_to: []\n"
        "  qualifications: []\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n",
        encoding="utf-8",
    )

    from job_search_email.models import JobListing

    dummy_job = JobListing(
        title="Manager", company="NHS", location="Bristol, BS1",
        salary_min=65000, description="", url="https://x.com/1",
        source="reed", employment_type="full-time",
    )

    with (
        patch("job_search_email.main.fetch_all_jobs", return_value=[dummy_job]),
        patch("job_search_email.main.generate_queries", return_value=["query"]),
        patch("job_search_email.main.classify_locations", return_value={"Bristol, BS1": "within"}) as mock_classify,
        patch("job_search_email.main.score_jobs", return_value=[]),
        patch("job_search_email.main.build_email_html", return_value=("<html/>", 0)),
        patch("job_search_email.main.send_email"),
    ):
        main_mod.main()

    mock_classify.assert_called_once()
    call_kwargs = mock_classify.call_args
    assert "Bristol" in str(call_kwargs)
    assert (tmp_path / "location_cache.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_main.py::test_main_loads_and_saves_location_cache -v
```

Expected: `FAILED` — `ImportError` or assertion error since `classify_locations` is not yet wired

- [ ] **Step 3: Add imports and `LOCATION_CACHE_PATH` constant to `main.py`**

At the top of `src/job_search_email/main.py`, add:

```python
from .location_filter import classify_locations, load_location_cache, save_location_cache
```

After the existing path constants (around line 28), add:

```python
LOCATION_CACHE_PATH = ROOT / "location_cache.json"
```

- [ ] **Step 4: Add classifier call in `main()`**

Replace the filtering block in `main()` with:

```python
    _print_location_summary(jobs)

    print("Classifying job locations...")
    location_cache = load_location_cache(LOCATION_CACHE_PATH)
    unique_locations = list({j.location for j in jobs if j.location})
    classification = classify_locations(
        unique_locations,
        home=profile.location,
        radius_miles=50,
        cache=location_cache,
    )
    save_location_cache(location_cache, LOCATION_CACHE_PATH)
    rejected_locations = frozenset(loc for loc, verdict in classification.items() if verdict == "outside")
    outside_count = len(rejected_locations)
    if outside_count:
        print(f"- {outside_count} location(s) classified as outside radius: {sorted(rejected_locations)}")

    print("Filtering jobs...")
    filtered = filter_jobs(jobs, plan, profile, rejected_locations=rejected_locations)
```

The full ordering in `main()` should be:
1. fetch → write results → print count
2. `_print_location_summary(jobs)`
3. classify locations → save cache → compute `rejected_locations`
4. filter (with `rejected_locations`) → write filtered → print counts
5. score → write scored → print counts
6. send email

- [ ] **Step 5: Run the full test suite**

```
pytest -v
```

Expected: all tests `PASSED`. Pay attention to any existing `test_main.py` tests that call `filter_jobs` directly — they should still pass because `rejected_locations` defaults to `frozenset()`.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "feat: wire location classifier into main pipeline"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Console location breakdown after fetch — Task 1
- ✅ Claude classifier returning within/outside/uncertain — Task 2
- ✅ Per-location caching keyed by `home:radius:location` — Task 2
- ✅ Unknown/obscure locations default to uncertain (allowed) — Task 2 (`_check_location` passes blank locations, `classify_locations` defaults missing keys to "uncertain")
- ✅ Location filter in `filter_jobs` pipeline — Task 3
- ✅ Reject reason surfaces in `job_results_filtered.json` — Task 3 (`reject_reason=f"location outside radius: {job.location}"`)
- ✅ Wired into `main.py` end-to-end — Task 4
- ✅ Cache saved atomically — Task 2 (`save_location_cache` uses `.tmp` + `os.replace`)

**Placeholder scan:** None found — all steps contain actual code.

**Type consistency:**
- `classify_locations` returns `dict[str, str]` in Task 2, consumed correctly in Task 4
- `filter_jobs` takes `rejected_locations: frozenset[str]` in Task 3, built correctly with `frozenset(...)` in Task 4
- `_check_location` takes `frozenset[str]` in Task 3, consistent with Task 4
