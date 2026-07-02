# Recruitment Agency Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone, independently toggleable filter that rejects jobs posted by recruitment agencies (which don't disclose the client company, making sponsor verification impossible), running immediately before the sponsor check.

**Architecture:** A new `_check_recruitment` function joins the existing chain of `_check_*` functions in `filter.py`, gated by an optional `recruitment_set` argument to `filter_jobs` (mirroring the existing `sponsor_set` pattern). Detection is by two signals: Reed's `postedByRecruitmentAgency` response field (carried on a new `JobListing.posted_by_agency` field) and a normalized name match against `assets/recruitment_agencies.csv`, loaded by a new `recruitment_filter.py` module that reuses the sponsor filter's `_normalize`/`_build_entries`. A single `profile.filter_recruitment` flag (default ON) controls the whole thing.

**Tech Stack:** Python 3, pytest, PyYAML, dataclasses, csv stdlib.

## Global Constraints

- Python 3 with type hints; dataclasses for models (matching existing code).
- New `JobListing` field MUST be a trailing field with a default (`posted_by_agency: bool | None = None`) so existing keyword-arg constructors stay valid.
- Reuse `_normalize` and `_build_entries` from `sponsor_filter.py` — do NOT duplicate normalization logic (DRY).
- Reject reason string, used verbatim: `recruitment agency — client company not disclosed, cannot verify sponsor`
- Config flag `filter_recruitment` defaults to `True` (filter ON out of the box).
- Recruitment check runs AFTER employment/role/nhs checks and BEFORE the sponsor check.
- NHS-sourced jobs (`job.source == "nhs"`) are skipped by the recruitment check.
- Tests run with: `python -m pytest <path> -v` from repo root `c:\Code\job-search-email`.

---

### Task 1: Add `posted_by_agency` to JobListing and populate it from Reed

**Files:**
- Modify: `src/job_search_email/models.py` (JobListing dataclass, ~line 37-46)
- Modify: `src/job_search_email/search_api/reed.py` (`_to_listing`, ~line 26-36)
- Test: `tests/search_api/test_reed.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `JobListing.posted_by_agency: bool | None` (default `None`); Reed's `_to_listing` sets it from `item.get("postedByRecruitmentAgency")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/search_api/test_reed.py`:

```python
def test_search_sets_posted_by_agency_true(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    response = {"results": [{**REED_RESPONSE["results"][0], "postedByRecruitmentAgency": True}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = response
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("manager", PROFILE)

    assert result[0].posted_by_agency is True


def test_search_posted_by_agency_absent_defaults_none(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = REED_RESPONSE  # no postedByRecruitmentAgency key
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("manager", PROFILE)

    assert result[0].posted_by_agency is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/search_api/test_reed.py::test_search_sets_posted_by_agency_true -v`
Expected: FAIL — `TypeError` (unexpected keyword) or `AttributeError: 'JobListing' object has no attribute 'posted_by_agency'`.

- [ ] **Step 3: Add the field to JobListing**

In `src/job_search_email/models.py`, add a trailing field to `JobListing`:

```python
@dataclass
class JobListing:
    title: str
    company: str
    location: str
    salary_min: int | None
    description: str
    url: str
    source: str
    employment_type: str | None
    posted_by_agency: bool | None = None
```

- [ ] **Step 4: Populate it in Reed's `_to_listing`**

In `src/job_search_email/search_api/reed.py`, update `_to_listing`:

```python
def _to_listing(item: dict) -> JobListing:
    return JobListing(
        title=item.get("jobTitle", ""),
        company=item.get("employerName", ""),
        location=item.get("locationName", ""),
        salary_min=item.get("minimumSalary"),
        description=item.get("jobDescription", ""),
        url=item.get("jobUrl", ""),
        source="reed",
        employment_type=_parse_employment_type(item),
        posted_by_agency=item.get("postedByRecruitmentAgency"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/search_api/test_reed.py -v`
Expected: PASS (all existing Reed tests plus the two new ones).

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/search_api/reed.py tests/search_api/test_reed.py
git commit -m "feat: carry Reed postedByRecruitmentAgency on JobListing.posted_by_agency"
```

---

### Task 2: `recruitment_filter.py` — load the recruiter name set

**Files:**
- Create: `src/job_search_email/recruitment_filter.py`
- Test: `tests/test_recruitment_filter.py` (create)

**Interfaces:**
- Consumes: `_normalize`, `_build_entries` from `sponsor_filter.py`.
- Produces: `load_recruitment_set(csv_path: Path) -> frozenset[str]` — reads a CSV with an `Organisation Name` column, returns normalized names plus their word-prefixes (same expansion as `load_sponsor_set`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_recruitment_filter.py`:

```python
import pytest
from pathlib import Path
from job_search_email.recruitment_filter import load_recruitment_set


@pytest.fixture
def recruitment_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "recruiters.csv"
    csv_file.write_text(
        "Organisation Name\n"
        "\n"
        '"Hays Specialist Recruitment Limited"\n'
        "\n"
        '"1 Force Recruitment Ltd"\n'
        '"Short"\n',
        encoding="utf-8",
    )
    return csv_file


def test_load_recruitment_set_returns_frozenset(recruitment_csv: Path):
    assert isinstance(load_recruitment_set(recruitment_csv), frozenset)


def test_load_recruitment_set_contains_full_normalized_name(recruitment_csv: Path):
    assert "hays specialist recruitment" in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_contains_two_word_prefix(recruitment_csv: Path):
    assert "hays specialist" in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_does_not_add_single_word_prefix(recruitment_csv: Path):
    assert "hays" not in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_skips_blank_rows(recruitment_csv: Path):
    assert "" not in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_keeps_short_single_word(recruitment_csv: Path):
    assert "short" in load_recruitment_set(recruitment_csv)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_recruitment_filter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_search_email.recruitment_filter'`.

- [ ] **Step 3: Create the module**

Create `src/job_search_email/recruitment_filter.py`:

```python
import csv
from pathlib import Path

from .sponsor_filter import _normalize, _build_entries


def load_recruitment_set(csv_path: Path) -> frozenset[str]:
    entries: set[str] = set()
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw = (row.get("Organisation Name") or "").strip()
            if not raw:
                continue
            normalized = _normalize(raw)
            if not normalized:
                continue
            for entry in _build_entries(normalized):
                entries.add(entry)
    return frozenset(entries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_recruitment_filter.py -v`
Expected: PASS (all six tests).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/recruitment_filter.py tests/test_recruitment_filter.py
git commit -m "feat: add load_recruitment_set for recruiter name matching"
```

---

### Task 3: `_check_recruitment` and wire it into `filter_jobs`

**Files:**
- Modify: `src/job_search_email/filter.py` (add constant + `_check_recruitment`; extend `filter_jobs` signature and chain)
- Test: `tests/test_filter.py`

**Interfaces:**
- Consumes: `JobListing.posted_by_agency` (Task 1); `_normalize`, `_build_entries` from `sponsor_filter.py`; a recruiter set shaped like Task 2's output.
- Produces: `_check_recruitment(job: JobListing, recruitment_set: frozenset[str]) -> FilteredResult | None`; `filter_jobs(..., recruitment_set: frozenset[str] | None = None)` gains the new keyword-only-style optional arg (placed before `sponsor_set` in the signature).

- [ ] **Step 1: Write the failing test for `_check_recruitment`**

Add to `tests/test_filter.py` (after the sponsor tests near the end):

```python
from job_search_email.filter import _check_recruitment

_RECRUITERS = frozenset({"hays specialist recruitment", "hays specialist", "acme resourcing"})
_RECRUITMENT_MSG = "recruitment agency — client company not disclosed, cannot verify sponsor"


def test_check_recruitment_rejects_reed_agency_flag():
    job = make_job(source="reed", company="Some Direct Employer Ltd", posted_by_agency=True)
    result = _check_recruitment(job, _RECRUITERS)
    assert result is not None and result.rejected is True
    assert result.reject_reason == _RECRUITMENT_MSG


def test_check_recruitment_rejects_name_match():
    job = make_job(source="reed", company="Hays Specialist Recruitment Ltd", posted_by_agency=None)
    result = _check_recruitment(job, _RECRUITERS)
    assert result is not None and result.rejected is True
    assert result.reject_reason == _RECRUITMENT_MSG


def test_check_recruitment_rejects_name_match_with_extra_trailing_words():
    # Job company carries extra words the listed name omits; prefix match still hits.
    job = make_job(source="reed", company="Acme Resourcing Solutions UK", posted_by_agency=None)
    result = _check_recruitment(job, _RECRUITERS)
    assert result is not None and result.rejected is True


def test_check_recruitment_rejects_blank_company_with_agency_flag():
    job = make_job(source="reed", company="", posted_by_agency=True)
    result = _check_recruitment(job, _RECRUITERS)
    assert result is not None and result.rejected is True


def test_check_recruitment_passes_non_agency():
    job = make_job(source="reed", company="Totally Legitimate Widgets", posted_by_agency=False)
    assert _check_recruitment(job, _RECRUITERS) is None


def test_check_recruitment_skips_nhs_source():
    job = make_job(source="nhs", company="Hays Specialist Recruitment Ltd", posted_by_agency=True)
    assert _check_recruitment(job, _RECRUITERS) is None


def test_check_recruitment_passes_blank_company_no_flag():
    job = make_job(source="reed", company="", posted_by_agency=None)
    assert _check_recruitment(job, _RECRUITERS) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_filter.py::test_check_recruitment_rejects_name_match -v`
Expected: FAIL — `ImportError: cannot import name '_check_recruitment'`.

- [ ] **Step 3: Implement `_check_recruitment` and the constant**

In `src/job_search_email/filter.py`, update the sponsor-filter import (line 4) and add the function. Change:

```python
from .sponsor_filter import _normalize as _normalize_company
```

to:

```python
from .sponsor_filter import _normalize as _normalize_company, _build_entries
```

Add a module-level constant near the other constants (after `_MIN_COMPANY_WORDS`, ~line 30):

```python
_RECRUITMENT_REASON = "recruitment agency — client company not disclosed, cannot verify sponsor"
```

Add the check function immediately before `_check_sponsor` (~line 97):

```python
def _check_recruitment(job: JobListing, recruitment_set: frozenset[str]) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    if job.posted_by_agency:
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=_RECRUITMENT_REASON)

    normalized = _normalize_company(job.company or "")
    if not normalized:
        return None

    for candidate in _build_entries(normalized):
        if candidate in recruitment_set:
            return FilteredResult(job=job, flags=[], rejected=True, reject_reason=_RECRUITMENT_REASON)

    return None
```

- [ ] **Step 4: Run the `_check_recruitment` tests to verify they pass**

Run: `python -m pytest tests/test_filter.py -k check_recruitment -v`
Expected: PASS (all seven `_check_recruitment` tests).

- [ ] **Step 5: Write the failing integration tests for `filter_jobs`**

Add to `tests/test_filter.py`:

```python
def test_filter_jobs_rejects_recruitment_when_set_given():
    jobs = [make_job(source="reed", company="Hays Specialist Recruitment Ltd", employment_type="full-time")]
    results = filter_jobs(
        jobs, make_plan(), make_profile_stub(),
        recruitment_set=_RECRUITERS, sponsor_set=_SPONSORS,
    )
    assert results[0].rejected is True
    assert results[0].reject_reason == _RECRUITMENT_MSG


def test_filter_jobs_recruitment_checked_before_sponsor():
    # An agency that is ALSO on the sponsor list must be rejected as recruitment, not passed.
    sponsors = frozenset({"hays specialist recruitment", "hays specialist"})
    jobs = [make_job(source="reed", company="Hays Specialist Recruitment Ltd", employment_type="full-time")]
    results = filter_jobs(
        jobs, make_plan(), make_profile_stub(),
        recruitment_set=_RECRUITERS, sponsor_set=sponsors,
    )
    assert results[0].rejected is True
    assert results[0].reject_reason == _RECRUITMENT_MSG


def test_filter_jobs_skips_recruitment_when_no_set():
    jobs = [make_job(source="reed", company="Hays Specialist Recruitment Ltd",
                     employment_type="full-time", posted_by_agency=True)]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert results[0].rejected is False


def test_filter_jobs_employment_type_checked_before_recruitment():
    jobs = [make_job(source="reed", company="Hays Specialist Recruitment Ltd", employment_type="contract")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), recruitment_set=_RECRUITERS)
    assert results[0].reject_reason == "employment type: contract"
```

- [ ] **Step 6: Run to verify the integration tests fail**

Run: `python -m pytest tests/test_filter.py::test_filter_jobs_rejects_recruitment_when_set_given -v`
Expected: FAIL — `TypeError: filter_jobs() got an unexpected keyword argument 'recruitment_set'`.

- [ ] **Step 7: Extend `filter_jobs` signature and chain**

In `src/job_search_email/filter.py`, change the `filter_jobs` signature (~line 132) to add `recruitment_set` before `sponsor_set`:

```python
def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    rejected_locations: frozenset[str] = frozenset(),
    recruitment_set: frozenset[str] | None = None,
    sponsor_set: frozenset[str] | None = None,
) -> list[FilteredResult]:
```

Then insert the recruitment check into the loop, immediately after the `nhs_result` block and before the `if sponsor_set is not None:` block (~line 162):

```python
        if recruitment_set is not None:
            recruitment_result = _check_recruitment(job, recruitment_set)
            if recruitment_result is not None:
                results.append(recruitment_result)
                continue

        if sponsor_set is not None:
```

- [ ] **Step 8: Run the full filter test file to verify all pass**

Run: `python -m pytest tests/test_filter.py -v`
Expected: PASS (all existing tests plus the new recruitment ones).

- [ ] **Step 9: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "feat: reject recruitment-agency jobs before sponsor check"
```

---

### Task 4: Config flag and pipeline wiring

**Files:**
- Modify: `src/job_search_email/models.py` (Profile dataclass, ~line 5-25)
- Modify: `src/job_search_email/main.py` (`load_profile`, path constants, `run_pipeline`)
- Modify: `profile.yaml` (add flag)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `load_recruitment_set` (Task 2); `filter_jobs(..., recruitment_set=...)` (Task 3); `Profile.filter_recruitment`.
- Produces: `Profile.filter_recruitment: bool` (default `True`); `main.RECRUITMENT_CACHE_PATH`; `run_pipeline` passes `recruitment_set` into `filter_jobs` only when the flag is set.

- [ ] **Step 1: Write the failing test for `load_profile`**

First inspect `tests/test_main.py` to match the existing `load_profile` test style. Then add tests. If the file has an existing profile-yaml fixture/helper, reuse it; otherwise add:

```python
from pathlib import Path
from job_search_email.main import load_profile


def _write_profile(tmp_path: Path, extra: str = "") -> Path:
    p = tmp_path / "profile.yaml"
    p.write_text(
        "profile:\n"
        "  name: Test\n"
        "  employment_type:\n"
        "    - full-time\n"
        "location: Bristol\n"
        "min_salary: 60000\n"
        f"{extra}",
        encoding="utf-8",
    )
    return p


def test_load_profile_filter_recruitment_defaults_true(tmp_path: Path):
    profile = load_profile(_write_profile(tmp_path))
    assert profile.filter_recruitment is True


def test_load_profile_filter_recruitment_reads_false(tmp_path: Path):
    profile = load_profile(_write_profile(tmp_path, extra="filter_recruitment: false\n"))
    assert profile.filter_recruitment is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -k filter_recruitment -v`
Expected: FAIL — `AttributeError: 'Profile' object has no attribute 'filter_recruitment'`.

- [ ] **Step 3: Add the Profile field**

In `src/job_search_email/models.py`, add a trailing field to `Profile` (after `send_debug_email`):

```python
    send_debug_email: bool = False
    filter_recruitment: bool = True
```

- [ ] **Step 4: Read the flag in `load_profile`**

In `src/job_search_email/main.py`, add to the `Profile(...)` construction in `load_profile` (after the `send_debug_email` line, ~line 61):

```python
        send_debug_email=data.get("send_debug_email", False),
        filter_recruitment=data.get("filter_recruitment", True),
```

- [ ] **Step 5: Run the `load_profile` tests to verify they pass**

Run: `python -m pytest tests/test_main.py -k filter_recruitment -v`
Expected: PASS (both tests).

- [ ] **Step 6: Add the path constant and wire the pipeline**

In `src/job_search_email/main.py`, add the import (near line 23, next to `load_sponsor_set`):

```python
from .recruitment_filter import load_recruitment_set
```

Add the path constant (after `SPONSOR_CACHE_PATH`, ~line 34):

```python
RECRUITMENT_CACHE_PATH = ROOT / "assets" / "recruitment_agencies.csv"
```

In `run_pipeline`, in the "Filtering jobs..." block (~line 203-210), load the recruiter set conditionally and pass it to `filter_jobs`:

```python
    print("Filtering jobs...")
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    print(f"- sponsor list loaded: {len(sponsor_set):,} entries")
    recruitment_set = load_recruitment_set(RECRUITMENT_CACHE_PATH) if profile.filter_recruitment else None
    if recruitment_set is not None:
        print(f"- recruitment list loaded: {len(recruitment_set):,} entries")
    else:
        print("- recruitment filter disabled (filter_recruitment=false)")
    filtered = filter_jobs(
        jobs, plan, profile,
        rejected_locations=rejected_locations,
        recruitment_set=recruitment_set,
        sponsor_set=sponsor_set,
    )
```

- [ ] **Step 7: Add the flag to `profile.yaml`**

In `profile.yaml`, add after `send_debug_email: true`:

```yaml
send_debug_email: true
filter_recruitment: true
```

- [ ] **Step 8: Run the full test suite to verify nothing regressed**

Run: `python -m pytest -q`
Expected: PASS (entire suite green).

- [ ] **Step 9: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/main.py profile.yaml tests/test_main.py
git commit -m "feat: wire recruitment filter into pipeline with filter_recruitment flag"
```

---

## Self-Review

**Spec coverage:**
- Detection via Reed flag → Task 1 (field) + Task 3 (`_check_recruitment` flag branch). ✓
- Detection via name list → Task 2 (loader) + Task 3 (name/prefix match). ✓
- Reuse `_normalize`/`_build_entries` → Tasks 2 and 3. ✓
- Pipeline placement before sponsor, after employment/role/nhs → Task 3 Step 7 + ordering tests. ✓
- Reject reason verbatim → `_RECRUITMENT_REASON` constant, asserted in tests. ✓
- Single toggle `filter_recruitment` default ON → Task 4. ✓
- NHS skip, blank-company + flag, toggle-off no-op edge cases → Task 3 tests. ✓
- `assets/recruitment_agencies.csv` already exists (header `Organisation Name`) → consumed by Task 4 wiring; loader tested against an equivalent fixture in Task 2.

**Placeholder scan:** No TBD/TODO; every code and test step shows complete content. ✓

**Type consistency:** `posted_by_agency: bool | None` used identically in models, reed, and filter tests. `_check_recruitment(job, recruitment_set)` signature matches its call in `filter_jobs`. `load_recruitment_set(csv_path) -> frozenset[str]` matches its use in `main.py`. `filter_recruitment: bool` consistent across models/load_profile/yaml. ✓

**Note on Reed flag availability:** Reed's search *response* may not include `postedByRecruitmentAgency` for every deployment. `item.get("postedByRecruitmentAgency")` degrades safely to `None` (no effect), and detection falls back to name matching — verified by `test_search_posted_by_agency_absent_defaults_none`.
