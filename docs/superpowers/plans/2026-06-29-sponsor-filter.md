# Sponsor Filter (FE-012) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the approved-sponsor filter into the live pipeline, rejecting jobs whose company cannot be verified against the UK sponsor register (including recruitment posts that omit the company name).

**Architecture:** Forward-port the FE-005 `sponsor_filter` module verbatim, add a `_check_sponsor` step to `filter.py` (after the NHS-band check) that rejects unverifiable companies, and load the sponsor set once in `main.py`. Exact-set matching against a normalized `frozenset` built from `assets/sponsor_cache.csv`.

**Tech Stack:** Python 3, stdlib `csv`/`re`, pytest. No new dependencies.

## Global Constraints

- No new dependencies; stdlib only.
- Sponsor data source is the cached `assets/sponsor_cache.csv` (CSV columns: `Organisation Name,Town/City,County,Type & Rating,Route`). No network download.
- NHS-source jobs (`job.source == "nhs"`) bypass the sponsor check.
- Missing/unverifiable company → **reject** (not flag-and-pass); rejected jobs remain visible in output via a distinct `reject_reason`.
- Two reject reasons, exact strings:
  - `"company not specified — cannot verify approved sponsor"` (empty/too-short/too-few-words)
  - `"company not on approved sponsor list"` (named but unlisted)
- Run tests with `python -m pytest` from the repo root.

---

## File Structure

- `src/job_search_email/sponsor_filter.py` (**create**) — CSV loading + name normalization. Owns all sponsor-set construction.
- `tests/test_sponsor_filter.py` (**create**) — normalization + set-construction tests.
- `src/job_search_email/filter.py` (**modify**) — add `_check_sponsor`; thread `sponsor_set` through `filter_jobs`.
- `tests/test_filter.py` (**modify**) — add sponsor-check tests.
- `src/job_search_email/main.py` (**modify**) — load sponsor set, pass to `filter_jobs`.
- `tests/test_main.py` (**modify**) — smoke test that the real CSV loads via the constant.

---

### Task 1: Sponsor set module (port verbatim)

**Files:**
- Create: `src/job_search_email/sponsor_filter.py`
- Test: `tests/test_sponsor_filter.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `_normalize(name: str) -> str`
  - `load_sponsor_set(csv_path: pathlib.Path) -> frozenset[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sponsor_filter.py`:

```python
import pytest
from job_search_email.sponsor_filter import _normalize, load_sponsor_set
from pathlib import Path


def test_normalize_strips_leading_whitespace():
    assert _normalize(" Bossmans Retail Ltd") == "bossmans retail"


def test_normalize_strips_trailing_whitespace():
    assert _normalize("Bossmans Retail Ltd   ") == "bossmans retail"


def test_normalize_lowercases():
    assert _normalize("BOSSMANS RETAIL LTD") == "bossmans retail"


def test_normalize_strips_ltd():
    assert _normalize("Acme Ltd") == "acme"


def test_normalize_strips_limited():
    assert _normalize("Acme Limited") == "acme"


def test_normalize_strips_plc():
    assert _normalize("Tesco Plc") == "tesco"


def test_normalize_strips_llp():
    assert _normalize("Smith Partners LLP") == "smith partners"


def test_normalize_strips_llc():
    assert _normalize("Global Solutions LLC") == "global solutions"


def test_normalize_strips_corp():
    assert _normalize("Big Corp") == "big"


def test_normalize_strips_corporation():
    assert _normalize("Big Corporation") == "big"


def test_normalize_strips_inc():
    assert _normalize("Startup Inc") == "startup"


def test_normalize_strips_co_suffix():
    assert _normalize("John Lewis & Co") == "john lewis"


def test_normalize_strips_ta_clause():
    assert _normalize("HAH Hospitality Limited t/a Indian Affair Ancoats") == "hah hospitality"


def test_normalize_strips_ta_with_uppercase():
    assert _normalize("CASA BAMBOO LTD T/A Pho Le Vietnamese Restaurant") == "casa bamboo"


def test_normalize_removes_punctuation():
    assert _normalize("F-Secure (UK) Limited") == "f-secure uk"


def test_normalize_preserves_hyphen_within_word():
    assert "f-secure" in _normalize("F-Secure UK Limited")


def test_normalize_collapses_whitespace():
    assert _normalize("  Big   Corp  Co  ") == "big corp"


def test_normalize_empty_string_returns_empty():
    assert _normalize("") == ""


def test_normalize_strips_trailing_period_on_suffix():
    assert _normalize("Acme Co.") == "acme"


@pytest.fixture
def sponsor_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "sponsors.csv"
    csv_file.write_text(
        "Organisation Name,Town/City,County,Type & Rating,Route\n"
        "\n"
        '" Bossmans Retail Abergavenny Ltd",Abergavenny,,Worker (A rating),Skilled Worker\n'
        "\n"
        '" F-Secure (UK) Limited",Gerrards Cross,Buckinghamshire,Worker (A rating),Skilled Worker\n'
        "\n"
        '" NHS Foundation Trust",London,,Worker (A rating),Skilled Worker\n'
        "\n"
        '"Short",London,,Worker (A rating),Skilled Worker\n',
        encoding="utf-8",
    )
    return csv_file


def test_load_sponsor_set_returns_frozenset(sponsor_csv: Path):
    assert isinstance(load_sponsor_set(sponsor_csv), frozenset)


def test_load_sponsor_set_contains_full_normalized_name(sponsor_csv: Path):
    assert "bossmans retail abergavenny" in load_sponsor_set(sponsor_csv)


def test_load_sponsor_set_contains_two_word_prefix(sponsor_csv: Path):
    assert "bossmans retail" in load_sponsor_set(sponsor_csv)


def test_load_sponsor_set_does_not_add_single_word_prefix(sponsor_csv: Path):
    assert "bossmans" not in load_sponsor_set(sponsor_csv)


def test_load_sponsor_set_contains_fsecure_entry(sponsor_csv: Path):
    assert "f-secure uk" in load_sponsor_set(sponsor_csv)


def test_load_sponsor_set_skips_blank_rows(sponsor_csv: Path):
    assert "" not in load_sponsor_set(sponsor_csv)


def test_load_sponsor_set_prefix_requires_8_chars(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "nhs foundation" in result
    assert "nhs" not in result


def test_load_sponsor_set_skips_name_too_short_to_normalize(sponsor_csv: Path):
    assert "short" in load_sponsor_set(sponsor_csv)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sponsor_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.sponsor_filter'`

- [ ] **Step 3: Create the module**

Create `src/job_search_email/sponsor_filter.py`:

```python
import csv
import re
from pathlib import Path

_TA_RE = re.compile(r"\bt/a\b.*$", re.IGNORECASE)
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|plc|llp|llc|co|corp|corporation|inc|incorporated)\.?\s*$",
    re.IGNORECASE,
)
_PUNCTUATION_RE = re.compile(r"(?<!\w)-(?!\w)|[^\w\s-]")
_WHITESPACE_RE = re.compile(r"\s+")

_MIN_PREFIX_CHARS = 8
_MIN_PREFIX_WORDS = 2


def _normalize(name: str) -> str:
    name = name.strip()
    name = _TA_RE.sub("", name).strip()
    name = _LEGAL_SUFFIX_RE.sub("", name).strip()
    name = name.lower()
    name = _PUNCTUATION_RE.sub("", name)
    name = _WHITESPACE_RE.sub(" ", name).strip()
    return name


def _build_entries(normalized: str) -> list[str]:
    entries = [normalized]
    words = normalized.split()
    for i in range(_MIN_PREFIX_WORDS, len(words)):
        prefix = " ".join(words[:i])
        if len(prefix) >= _MIN_PREFIX_CHARS:
            entries.append(prefix)
    return entries


def load_sponsor_set(csv_path: Path) -> frozenset[str]:
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

Run: `python -m pytest tests/test_sponsor_filter.py -v`
Expected: PASS (all tests green)

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/sponsor_filter.py tests/test_sponsor_filter.py
git commit -m "feat: add sponsor_filter module with normalize and load_sponsor_set"
```

---

### Task 2: Sponsor check in the filter pipeline

**Files:**
- Modify: `src/job_search_email/filter.py`
- Test: `tests/test_filter.py`

**Interfaces:**
- Consumes: `_normalize`, `load_sponsor_set` from Task 1; `JobListing`, `FilteredResult` from `models`.
- Produces:
  - `_check_sponsor(job: JobListing, sponsor_set: frozenset[str]) -> FilteredResult | None`
  - `filter_jobs(jobs, plan, profile, rejected_locations=frozenset(), sponsor_set: frozenset[str] | None = None) -> list[FilteredResult]` (new trailing `sponsor_set` keyword param)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filter.py` (the existing `make_job`, `make_plan`, `make_profile_stub` helpers and the `filter_jobs` import are already present in the file):

```python
from job_search_email.filter import _check_sponsor

_SPONSORS = frozenset({"acme analytics", "bossmans retail abergavenny", "bossmans retail"})


def test_check_sponsor_passes_nhs_source_without_lookup():
    job = make_job(source="nhs", company="")
    assert _check_sponsor(job, frozenset()) is None


def test_check_sponsor_rejects_empty_company():
    job = make_job(source="reed", company="")
    result = _check_sponsor(job, _SPONSORS)
    assert result is not None and result.rejected is True
    assert result.reject_reason == "company not specified — cannot verify approved sponsor"


def test_check_sponsor_rejects_too_short_company():
    job = make_job(source="reed", company="Hays")
    result = _check_sponsor(job, _SPONSORS)
    assert result is not None and result.rejected is True
    assert result.reject_reason == "company not specified — cannot verify approved sponsor"


def test_check_sponsor_passes_listed_company():
    job = make_job(source="reed", company="Acme Analytics Ltd")
    assert _check_sponsor(job, _SPONSORS) is None


def test_check_sponsor_rejects_unlisted_company():
    job = make_job(source="reed", company="Totally Unlisted Widgets")
    result = _check_sponsor(job, _SPONSORS)
    assert result is not None and result.rejected is True
    assert result.reject_reason == "company not on approved sponsor list"


def test_filter_jobs_rejects_missing_company_when_sponsor_set_given():
    jobs = [make_job(source="reed", company="", employment_type="full-time")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSORS)
    assert results[0].rejected is True
    assert results[0].reject_reason == "company not specified — cannot verify approved sponsor"


def test_filter_jobs_keeps_listed_company_when_sponsor_set_given():
    jobs = [make_job(source="reed", company="Acme Analytics Ltd", employment_type="full-time")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSORS)
    assert results[0].rejected is False


def test_filter_jobs_skips_sponsor_check_when_no_set():
    jobs = [make_job(source="reed", company="", employment_type="full-time")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert results[0].rejected is False


def test_filter_jobs_employment_type_checked_before_sponsor():
    jobs = [make_job(source="reed", company="", employment_type="contract")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSORS)
    assert results[0].rejected is True
    assert results[0].reject_reason == "employment type: contract"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_filter.py -k sponsor -v`
Expected: FAIL with `ImportError: cannot import name '_check_sponsor'`

- [ ] **Step 3: Add `_check_sponsor` and constants to `filter.py`**

At the top of `src/job_search_email/filter.py`, add the import (alongside the existing `from .models import ...`):

```python
from .sponsor_filter import _normalize as _normalize_company
```

Add constants near the other module-level constants (after `_LONDON_WEIGHTING = 1.20`):

```python
_MIN_COMPANY_CHARS = 8
_MIN_COMPANY_WORDS = 2
```

Add the function immediately after `_check_nhs_band_salary` (before `_check_location` or `filter_jobs`):

```python
def _check_sponsor(job: JobListing, sponsor_set: frozenset[str]) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    normalized = _normalize_company(job.company or "")
    words = normalized.split()

    if len(normalized) < _MIN_COMPANY_CHARS or len(words) < _MIN_COMPANY_WORDS:
        return FilteredResult(
            job=job,
            flags=[],
            rejected=True,
            reject_reason="company not specified — cannot verify approved sponsor",
        )

    if normalized in sponsor_set:
        return None

    return FilteredResult(
        job=job,
        flags=[],
        rejected=True,
        reject_reason="company not on approved sponsor list",
    )
```

- [ ] **Step 4: Thread `sponsor_set` through `filter_jobs`**

Update the `filter_jobs` signature to add the trailing keyword param:

```python
def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    rejected_locations: frozenset[str] = frozenset(),
    sponsor_set: frozenset[str] | None = None,
) -> list[FilteredResult]:
```

Replace the final append in the per-job loop (currently the `results.append(FilteredResult(job=job, flags=et_result.flags, rejected=False, reject_reason=None))` block after the NHS-band check) with:

```python
        if sponsor_set is not None:
            sponsor_result = _check_sponsor(job, sponsor_set)
            if sponsor_result is not None:
                results.append(sponsor_result)
                continue

        results.append(FilteredResult(
            job=job,
            flags=et_result.flags,
            rejected=False,
            reject_reason=None,
        ))
```

- [ ] **Step 5: Run the full filter test file to verify pass + no regressions**

Run: `python -m pytest tests/test_filter.py -v`
Expected: PASS (new sponsor tests green, all pre-existing filter tests still green)

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "feat: reject jobs with unverifiable company in sponsor filter"
```

---

### Task 3: Wire the sponsor set into `main.py`

**Files:**
- Modify: `src/job_search_email/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `load_sponsor_set` (Task 1), `filter_jobs(..., sponsor_set=...)` (Task 2).
- Produces: `SPONSOR_CACHE_PATH` module constant in `main.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main.py`:

```python
def test_sponsor_cache_loads_from_real_asset():
    from job_search_email.main import SPONSOR_CACHE_PATH
    from job_search_email.sponsor_filter import load_sponsor_set

    assert SPONSOR_CACHE_PATH.name == "sponsor_cache.csv"
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    assert isinstance(sponsor_set, frozenset)
    assert len(sponsor_set) > 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py::test_sponsor_cache_loads_from_real_asset -v`
Expected: FAIL with `ImportError: cannot import name 'SPONSOR_CACHE_PATH'`

- [ ] **Step 3: Wire into `main.py`**

Add the import next to the other `from .` imports (with the `from .scorer import score_jobs` group):

```python
from .sponsor_filter import load_sponsor_set
```

Add the constant alongside the other `*_PATH` constants (after `LOCATION_CACHE_PATH = ROOT / "location_cache.json"`):

```python
SPONSOR_CACHE_PATH = ROOT / "assets" / "sponsor_cache.csv"
```

In `main()`, replace the existing filter step:

```python
    print("Filtering jobs...")
    filtered = filter_jobs(jobs, plan, profile, rejected_locations=rejected_locations)
```

with:

```python
    print("Filtering jobs...")
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    print(f"- sponsor list loaded: {len(sponsor_set):,} entries")
    filtered = filter_jobs(
        jobs, plan, profile,
        rejected_locations=rejected_locations,
        sponsor_set=sponsor_set,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py::test_sponsor_cache_loads_from_real_asset -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (entire suite green)

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "feat: load sponsor set and apply sponsor filter in main pipeline"
```

---

## Self-Review

**Spec coverage:**
- Sponsor set construction (normalize + prefix expansion) → Task 1. ✓
- `_check_sponsor` with NHS bypass, missing-company reject, listed pass, unlisted reject → Task 2. ✓
- Pipeline order (sponsor after NHS band) + `sponsor_set=None` skip → Task 2 (`test_filter_jobs_employment_type_checked_before_sponsor`, `test_filter_jobs_skips_sponsor_check_when_no_set`). ✓
- `main.py` loads set once and passes it in → Task 3. ✓
- Rejected missing-company jobs remain visible → they land in the `rejected` bucket with a distinct reason (existing `write_filtered_results`/`debug_email` already render rejected results); covered by reject_reason assertions. ✓
- NHS `source == "nhs"` (not `"nhs_jobs"`) used in tests → `test_check_sponsor_passes_nhs_source_without_lookup`. ✓

**Placeholder scan:** none — all steps contain concrete code/commands.

**Type consistency:** `_check_sponsor(job, sponsor_set) -> FilteredResult | None` and `filter_jobs(..., sponsor_set=...)` signatures match between Task 2 definition and Task 3 usage; `load_sponsor_set(Path) -> frozenset[str]` consistent across Tasks 1/3. ✓
