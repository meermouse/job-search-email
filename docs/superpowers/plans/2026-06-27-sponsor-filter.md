# Sponsor Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject job listings from companies not on the UK Government's approved sponsor register, using fuzzy prefix-based name matching so informal names like "Bossmans Retail" match legal entries like "Bossmans Retail Abergavenny Ltd".

**Architecture:** A new `sponsor_filter.py` module loads `assets/sponsor_cache.csv` once at startup, normalises every company name, and builds a `frozenset` that includes both full names and all valid word-boundary prefixes. `filter.py` gains a `_check_sponsor` function that does an O(1) set lookup. `main.py` loads the set once and passes it into `filter_jobs`.

**Tech Stack:** Python stdlib only (`re`, `csv`, `pathlib`). No new dependencies.

## Global Constraints

- Python 3.12+; type hints required on all public functions
- No new third-party dependencies
- All new code lives in `src/job_search_email/`
- Tests live in `tests/`; run with `pytest` from the repo root
- NHS-source jobs (`job.source == "nhs"`) always pass the sponsor check automatically
- The sponsor set is loaded once at startup; never re-read mid-run

---

### Task 1: Create `sponsor_filter.py` — normalization and sponsor set loading

**Files:**
- Create: `src/job_search_email/sponsor_filter.py`
- Create: `tests/test_sponsor_filter.py`

**Interfaces:**
- Produces:
  - `_normalize(name: str) -> str` (private — tested directly)
  - `load_sponsor_set(csv_path: Path) -> frozenset[str]` (public)

---

- [ ] **Step 1: Write the failing tests for `_normalize`**

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
    # hyphens between word chars are kept
    assert "f-secure" in _normalize("F-Secure UK Limited")


def test_normalize_collapses_whitespace():
    assert _normalize("  Big   Corp  Co  ") == "big   corp"


def test_normalize_empty_string_returns_empty():
    assert _normalize("") == ""


def test_normalize_strips_trailing_period_on_suffix():
    assert _normalize("Acme Co.") == "acme"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sponsor_filter.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Write the failing tests for `load_sponsor_set`**

Append to `tests/test_sponsor_filter.py`:

```python
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
    result = load_sponsor_set(sponsor_csv)
    assert isinstance(result, frozenset)


def test_load_sponsor_set_contains_full_normalized_name(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "bossmans retail abergavenny" in result


def test_load_sponsor_set_contains_two_word_prefix(sponsor_csv: Path):
    # "bossmans retail abergavenny" → prefix "bossmans retail" added
    result = load_sponsor_set(sponsor_csv)
    assert "bossmans retail" in result


def test_load_sponsor_set_does_not_add_single_word_prefix(sponsor_csv: Path):
    # "bossmans" alone must NOT be added as a prefix
    result = load_sponsor_set(sponsor_csv)
    assert "bossmans" not in result


def test_load_sponsor_set_contains_fsecure_entry(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "f-secure uk" in result


def test_load_sponsor_set_skips_blank_rows(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "" not in result


def test_load_sponsor_set_prefix_requires_8_chars(sponsor_csv: Path):
    # "nhs foundation trust" → prefix "nhs foundation" is 14 chars and 2 words → added
    # "nhs" alone (3 chars, 1 word) → NOT added
    result = load_sponsor_set(sponsor_csv)
    assert "nhs foundation" in result
    assert "nhs" not in result


def test_load_sponsor_set_skips_name_too_short_to_normalize(sponsor_csv: Path):
    # "Short" normalizes to "short" (5 chars) — full name still included
    result = load_sponsor_set(sponsor_csv)
    assert "short" in result
```

- [ ] **Step 4: Run to verify new tests fail**

```bash
pytest tests/test_sponsor_filter.py -v
```

Expected: `ImportError` — module still doesn't exist.

- [ ] **Step 5: Implement `sponsor_filter.py`**

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

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_sponsor_filter.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/sponsor_filter.py tests/test_sponsor_filter.py
git commit -m "feat: add sponsor_filter module with normalize and load_sponsor_set"
```

---

### Task 2: Add `_check_sponsor` to `filter.py` and update `filter_jobs`

**Files:**
- Modify: `src/job_search_email/filter.py`
- Modify: `tests/test_filter.py`

**Interfaces:**
- Consumes: `_normalize` from `src/job_search_email/sponsor_filter.py`
- Produces:
  - `_check_sponsor(job: JobListing, sponsor_set: frozenset[str]) -> FilteredResult | None`
  - Updated `filter_jobs(jobs: list[JobListing], plan: SearchPlan, profile: Profile, sponsor_set: frozenset[str] | None = None) -> list[FilteredResult]`

---

- [ ] **Step 1: Write failing tests for `_check_sponsor`**

Append to `tests/test_filter.py`:

```python
from job_search_email.filter import _check_sponsor

_SPONSOR_SET = frozenset({
    "bossmans retail abergavenny",
    "bossmans retail",          # prefix entry
    "acme digital solutions",
    "acme digital",             # prefix entry
})


def test_check_sponsor_nhs_source_passes():
    job = make_job(source="nhs", company="NHS Trust Bristol")
    assert _check_sponsor(job, _SPONSOR_SET) is None


def test_check_sponsor_exact_match_passes():
    job = make_job(source="reed", company="Bossmans Retail Abergavenny")
    assert _check_sponsor(job, _SPONSOR_SET) is None


def test_check_sponsor_prefix_match_passes():
    # "Bossmans Retail" matches because it's a prefix entry in the set
    job = make_job(source="reed", company="Bossmans Retail")
    assert _check_sponsor(job, _SPONSOR_SET) is None


def test_check_sponsor_not_in_list_rejected():
    job = make_job(source="reed", company="Unknown Corp Ltd")
    result = _check_sponsor(job, _SPONSOR_SET)
    assert result is not None
    assert result.rejected is True
    assert result.reject_reason == "company not on approved sponsor list"


def test_check_sponsor_empty_company_flagged_not_rejected():
    job = make_job(source="reed", company="")
    result = _check_sponsor(job, _SPONSOR_SET)
    assert result is not None
    assert result.rejected is False
    assert "sponsor_unknown_company" in result.flags


def test_check_sponsor_none_company_flagged_not_rejected():
    job = make_job(source="reed", company=None)
    result = _check_sponsor(job, _SPONSOR_SET)
    assert result is not None
    assert result.rejected is False
    assert "sponsor_unknown_company" in result.flags


def test_check_sponsor_short_company_flagged_not_rejected():
    # "NHS" normalizes to "nhs" — 3 chars, too short to match reliably
    job = make_job(source="reed", company="NHS")
    result = _check_sponsor(job, _SPONSOR_SET)
    assert result is not None
    assert result.rejected is False
    assert "sponsor_unknown_company" in result.flags


def test_check_sponsor_single_word_under_8_chars_flagged():
    # "acme" is 4 chars — below 8-char threshold
    job = make_job(source="reed", company="Acme")
    result = _check_sponsor(job, _SPONSOR_SET)
    assert result is not None
    assert result.rejected is False
    assert "sponsor_unknown_company" in result.flags


def test_check_sponsor_company_with_ltd_stripped_before_lookup():
    # "Bossmans Retail Ltd" → normalized → "bossmans retail" → in set
    job = make_job(source="indeed", company="Bossmans Retail Ltd")
    assert _check_sponsor(job, _SPONSOR_SET) is None


def test_filter_jobs_sponsor_check_rejects_unlisted_company():
    jobs = [make_job(source="reed", employment_type="full-time", company="Unknown Agency Ltd")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSOR_SET)
    assert results[0].rejected is True
    assert results[0].reject_reason == "company not on approved sponsor list"


def test_filter_jobs_sponsor_check_passes_listed_company():
    jobs = [make_job(source="reed", employment_type="full-time", company="Bossmans Retail")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSOR_SET)
    assert results[0].rejected is False


def test_filter_jobs_sponsor_check_skipped_when_set_is_none():
    # Existing tests pass sponsor_set=None; unlisted companies should still pass
    jobs = [make_job(source="reed", employment_type="full-time", company="Unknown Corp")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=None)
    assert results[0].rejected is False


def test_filter_jobs_employment_type_checked_before_sponsor():
    # Contract role: reject reason should be employment type, not sponsor
    jobs = [make_job(source="reed", employment_type="contract", company="Unknown Corp")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSOR_SET)
    assert results[0].reject_reason == "employment type: contract"


def test_filter_jobs_nhs_source_passes_sponsor_check():
    jobs = [make_job(source="nhs", employment_type="full-time", company="Unknown NHS Trust")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub(), sponsor_set=_SPONSOR_SET)
    assert results[0].rejected is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_filter.py::test_check_sponsor_nhs_source_passes -v
```

Expected: `ImportError: cannot import name '_check_sponsor'`

- [ ] **Step 3: Implement `_check_sponsor` and update `filter_jobs` in `filter.py`**

Add the import at the top of `src/job_search_email/filter.py` (after existing imports):

```python
from .sponsor_filter import _normalize as _normalize_company

_MIN_COMPANY_CHARS = 8
_MIN_COMPANY_WORDS = 2
```

Add the function after `_check_nhs_band_salary`:

```python
def _check_sponsor(job: JobListing, sponsor_set: frozenset[str]) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    normalized = _normalize_company(job.company or "")
    words = normalized.split()

    if len(normalized) < _MIN_COMPANY_CHARS or len(words) < _MIN_COMPANY_WORDS:
        return FilteredResult(job=job, flags=["sponsor_unknown_company"], rejected=False, reject_reason=None)

    if normalized in sponsor_set:
        return None

    return FilteredResult(job=job, flags=[], rejected=True, reject_reason="company not on approved sponsor list")
```

Update the `filter_jobs` signature and body. Replace the existing function:

```python
def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    sponsor_set: frozenset[str] | None = None,
) -> list[FilteredResult]:
    exclusion_roles = plan.exclusions.get("roles", [])
    results: list[FilteredResult] = []

    for job in jobs:
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

        if sponsor_set is not None:
            sponsor_result = _check_sponsor(job, sponsor_set)
            if sponsor_result is not None and sponsor_result.rejected:
                results.append(sponsor_result)
                continue

        flags = list(et_result.flags)
        if sponsor_set is not None:
            sponsor_flag_result = _check_sponsor(job, sponsor_set)
            if sponsor_flag_result is not None and not sponsor_flag_result.rejected:
                flags.extend(sponsor_flag_result.flags)

        results.append(FilteredResult(
            job=job,
            flags=flags,
            rejected=False,
            reject_reason=None,
        ))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_filter.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/filter.py tests/test_filter.py
git commit -m "feat: add _check_sponsor to filter pipeline"
```

---

### Task 3: Wire sponsor set into `main.py`

**Files:**
- Modify: `src/job_search_email/main.py`

**Interfaces:**
- Consumes: `load_sponsor_set(csv_path: Path) -> frozenset[str]` from `sponsor_filter`
- Consumes: updated `filter_jobs(..., sponsor_set)` from `filter.py`

---

- [ ] **Step 1: Add import and path constant to `main.py`**

At the top of `src/job_search_email/main.py`, add the import alongside the existing ones:

```python
from .sponsor_filter import load_sponsor_set
```

After the existing `FILTERED_RESULTS_PATH` constant, add:

```python
SPONSOR_CACHE_PATH = ROOT / "assets" / "sponsor_cache.csv"
```

- [ ] **Step 2: Load sponsor set and pass to `filter_jobs` in `main()`**

In the `main()` function, replace:

```python
    print("Filtering jobs...")
    filtered = filter_jobs(jobs, plan, profile)
```

With:

```python
    print("Filtering jobs...")
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    print(f"- sponsor list loaded: {len(sponsor_set):,} entries")
    filtered = filter_jobs(jobs, plan, profile, sponsor_set=sponsor_set)
```

- [ ] **Step 3: Run the full test suite**

```bash
pytest -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/job_search_email/main.py
git commit -m "feat: wire sponsor set into main filter pipeline"
```

---

## Self-Review Notes

**Spec coverage:**
- `load_sponsor_set` with normalization and prefix set construction → Task 1 ✓
- `_check_sponsor` per-job logic table (all 5 rows) → Task 2 ✓
- `filter_jobs` signature update → Task 2 ✓
- `main.py` integration (SPONSOR_CACHE_PATH, load once, pass to filter_jobs) → Task 3 ✓
- NHS auto-pass → covered in `_check_sponsor` (Task 2) ✓
- Blank rows skipped → covered in `load_sponsor_set` test (Task 1) ✓
- T/A clause stripping → covered in `_normalize` tests (Task 1) ✓
- Prefix entries (e.g. "bossmans retail" from 3-word name) → covered in Task 1 tests ✓

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:**
- `_normalize` used as `_normalize_company` in filter.py to avoid name collision — consistent across Task 1 and Task 2 ✓
- `frozenset[str]` return type from `load_sponsor_set` matches `sponsor_set` parameter in `_check_sponsor` and `filter_jobs` ✓
- `FilteredResult` constructor arguments match the dataclass in `models.py` ✓

**One implementation note:** Task 2 Step 3 calls `_check_sponsor` twice in `filter_jobs` — once to check for rejection and once to collect flags. Refactor this into a single call by checking both `rejected` and `flags` from the same result object. The corrected `filter_jobs` body:

```python
def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    sponsor_set: frozenset[str] | None = None,
) -> list[FilteredResult]:
    exclusion_roles = plan.exclusions.get("roles", [])
    results: list[FilteredResult] = []

    for job in jobs:
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

        flags = list(et_result.flags)

        if sponsor_set is not None:
            sponsor_result = _check_sponsor(job, sponsor_set)
            if sponsor_result is not None:
                if sponsor_result.rejected:
                    results.append(sponsor_result)
                    continue
                flags.extend(sponsor_result.flags)

        results.append(FilteredResult(job=job, flags=flags, rejected=False, reject_reason=None))

    return results
```

Use this version in Task 2 Step 3 instead of the double-call version shown there.
