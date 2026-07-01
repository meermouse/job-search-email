# Explain-Job Rating Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local `explain-job` command that takes a job URL and explains why that job got its rating by replaying the real filter and scorer logic with a readable stage-by-stage trace.

**Architecture:** Two new modules (`job_resolver.py` for URL→`JobListing`, `explain_job.py` for orchestration/CLI) plus a small public seam added to `scorer.py` that exposes the LLM prompt and raw response. The filter trace reuses the existing private `_check_*` gate functions from `filter.py` so it cannot drift from production behaviour.

**Tech Stack:** Python 3.11, `requests`, `beautifulsoup4`, `PyYAML`, `anthropic`, `pytest` (with `unittest.mock` / `monkeypatch`).

## Global Constraints

- Python `>=3.11`; only existing dependencies (`PyYAML`, `anthropic`, `python-jobspy`, `requests`, `beautifulsoup4`) — add none.
- Reuse existing logic; do not duplicate filter or scorer behaviour. The filter trace calls the real `filter._check_*` functions; the scorer trace shares parsing with the production path.
- Console scripts are registered under `[project.scripts]` in `pyproject.toml`. The package lives under `src/job_search_email/`.
- Tests live under `tests/`, mirror the package layout, and mock all network/LLM calls (`requests.get`, the `anthropic` client). No test makes a real network or API call.
- The local replay deliberately does **not** reproduce the exact emailed score (LLM nondeterminism is acceptable); it explains the decision logic.
- Profile loading uses the existing `job_search_email.main.load_profile(path)` (it includes `radius_miles`). Default profile path is `profile.yaml` in the repo root.

---

### Task 1: Scorer seam — expose prompt and raw response

Extract the response-parsing from the private `_analyse_job` into a shared
`_parse_analysis`, then add a public `analyse_job(job, profile)` that returns the
analysis **plus** the exact system prompt, user message, and raw model text. The
existing `_analyse_job(job, system_prompt, model)` signature is preserved
(a test patches it with that exact signature), and `score_jobs` is unchanged in
behaviour.

**Files:**
- Modify: `src/job_search_email/scorer.py`
- Test: `tests/test_explain_scorer_seam.py` (Create)

**Interfaces:**
- Consumes: existing `_build_system_prompt(profile)`, `_build_user_message(job)`, `client` (module-level `anthropic.Anthropic()`), `JobAnalysis`, `JobListing`, `Profile`.
- Produces:
  - `AnalysisTrace` dataclass with fields `analysis: JobAnalysis`, `system_prompt: str`, `user_message: str`, `raw_text: str`.
  - `analyse_job(job: JobListing, profile: Profile) -> AnalysisTrace`.
  - `_parse_analysis(text: str) -> JobAnalysis` (internal; applies the mismatch score cap).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_explain_scorer_seam.py`:

```python
import json
from unittest.mock import MagicMock, patch

from job_search_email.models import JobListing, Profile
from job_search_email.scorer import AnalysisTrace, analyse_job


def _job() -> JobListing:
    return JobListing(
        title="Project Manager", company="Acme Ltd", location="Bristol",
        salary_min=65000, description="Lead delivery. PRINCE2 required.",
        url="https://example.com/1", source="reed", employment_type="permanent",
    )


def _profile() -> Profile:
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=["delivery"], previous_roles=[],
        target_roles=["Project Manager"], open_to=[], not_open_to=[],
        qualifications=["MSc"], employment_type=["full-time"],
        location="Bristol", min_salary=60000,
    )


_RESPONSE = json.dumps({
    "score": 8,
    "matched_skills": ["delivery"],
    "missing_essentials": ["PRINCE2"],
    "employment_type_note": "Permanent",
    "verdict": "Strong match",
})


def _mock_client(text: str = _RESPONSE) -> MagicMock:
    m = MagicMock()
    m.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return m


def test_analyse_job_returns_trace_with_prompt_and_raw():
    with patch("job_search_email.scorer.client", _mock_client()):
        trace = analyse_job(_job(), _profile())
    assert isinstance(trace, AnalysisTrace)
    assert trace.analysis.score == 8
    assert "job suitability analyst" in trace.system_prompt
    assert "Project Manager" in trace.user_message
    assert trace.raw_text == _RESPONSE


def test_analyse_job_applies_mismatch_cap():
    mismatch = json.dumps({
        "score": 9, "matched_skills": [], "missing_essentials": ["PRINCE2"],
        "employment_type_note": "", "verdict": "x",
        "required_qualifications": ["PRINCE2"], "qualification_gaps": ["PRINCE2"],
        "qualification_status": "mismatch",
    })
    with patch("job_search_email.scorer.client", _mock_client(mismatch)):
        trace = analyse_job(_job(), _profile())
    assert trace.analysis.score == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_explain_scorer_seam.py -v`
Expected: FAIL with `ImportError: cannot import name 'AnalysisTrace'` (and `analyse_job`).

- [ ] **Step 3: Refactor `scorer.py` to add the seam**

In `src/job_search_email/scorer.py`, add a dataclass import and the new types.
At the top, ensure `from dataclasses import asdict, dataclass` (the file already
imports `asdict`; add `dataclass`).

Add after the imports / before `_build_system_prompt`:

```python
@dataclass
class AnalysisTrace:
    analysis: JobAnalysis
    system_prompt: str
    user_message: str
    raw_text: str
```

Add a shared parser (move the JSON parse + mismatch cap out of `_analyse_job`):

```python
def _parse_analysis(text: str) -> JobAnalysis:
    data = json.loads(_strip_code_fence(text))
    score = int(data["score"])
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
        exclude=bool(data.get("exclude", False)),
        exclude_reason=data.get("exclude_reason", ""),
    )
```

Replace the body of `_analyse_job` so it reuses `_parse_analysis` (signature
**unchanged**):

```python
def _analyse_job(job: JobListing, system_prompt: str, model: str) -> JobAnalysis:
    response = client.messages.create(
        model=model,
        max_tokens=768,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_user_message(job)}],
    )
    if not response.content:
        raise ValueError(f"empty content list from Claude (stop_reason={response.stop_reason})")
    block = response.content[0]
    text = getattr(block, "text", "")
    if not text.strip():
        raise ValueError(f"empty text block from Claude (stop_reason={response.stop_reason}, type={type(block).__name__})")
    return _parse_analysis(text)
```

Add the public seam used by the explainer:

```python
def analyse_job(job: JobListing, profile: Profile) -> AnalysisTrace:
    system_prompt = _build_system_prompt(profile)
    user_message = _build_user_message(job)
    model = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=768,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    if not response.content:
        raise ValueError(f"empty content list from Claude (stop_reason={response.stop_reason})")
    block = response.content[0]
    raw_text = getattr(block, "text", "")
    if not raw_text.strip():
        raise ValueError(f"empty text block from Claude (stop_reason={response.stop_reason}, type={type(block).__name__})")
    return AnalysisTrace(
        analysis=_parse_analysis(raw_text),
        system_prompt=system_prompt,
        user_message=user_message,
        raw_text=raw_text,
    )
```

- [ ] **Step 4: Run the new tests and the full scorer suite**

Run: `python -m pytest tests/test_explain_scorer_seam.py tests/test_scorer.py -v`
Expected: PASS — new tests pass and all existing scorer tests stay green
(notably `test_score_jobs_sorts_kept_by_score_desc`, which patches
`_analyse_job(job, system_prompt, model)`).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/scorer.py tests/test_explain_scorer_seam.py
git commit -m "feat: add analyse_job seam exposing LLM prompt and raw response"
```

---

### Task 2: Job resolver — URL/job-file → JobListing

Resolve a single job for replay: Reed via its job-detail API, NHS via advert
scrape (description left empty to mirror the pipeline), a `--job-file` YAML
fallback for any source, and a clear error for LinkedIn/Indeed URLs.

**Files:**
- Create: `src/job_search_email/job_resolver.py`
- Test: `tests/test_job_resolver.py` (Create)

**Interfaces:**
- Consumes: `JobListing` from `models`; `reed._parse_employment_type` (DRY reuse of Reed's employment mapping); `requests`, `bs4.BeautifulSoup`, `yaml`.
- Produces:
  - `class UnsupportedSourceError(Exception)`.
  - `resolve_job(url: str | None, job_file: str | None = None) -> JobListing`.
  - `_extract_reed_id(url: str) -> str`.
  - `fetch_reed_job(url: str) -> JobListing`.
  - `fetch_nhs_job(url: str) -> JobListing`.
  - `load_job_file(path: str) -> JobListing`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_job_resolver.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from job_search_email.job_resolver import (
    UnsupportedSourceError,
    _extract_reed_id,
    fetch_reed_job,
    load_job_file,
    resolve_job,
)


REED_DETAIL = {
    "jobId": 53819371,
    "jobTitle": "Senior Project Manager",
    "employerName": "Acme Ltd",
    "locationName": "Bristol",
    "minimumSalary": 65000,
    "jobDescription": "Lead delivery teams.",
    "fullTime": False, "partTime": False, "contract": False, "permanent": True,
}


def test_extract_reed_id_from_url():
    url = "https://www.reed.co.uk/jobs/senior-project-manager/53819371"
    assert _extract_reed_id(url) == "53819371"


def test_extract_reed_id_with_trailing_slash_or_query():
    assert _extract_reed_id("https://www.reed.co.uk/jobs/x/53819371/") == "53819371"
    assert _extract_reed_id("https://www.reed.co.uk/jobs/x/53819371?utm=1") == "53819371"


def test_fetch_reed_job_maps_fields(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "k")
    resp = MagicMock()
    resp.json.return_value = REED_DETAIL
    resp.raise_for_status.return_value = None
    with patch("job_search_email.job_resolver.requests.get", return_value=resp):
        job = fetch_reed_job("https://www.reed.co.uk/jobs/x/53819371")
    assert job.title == "Senior Project Manager"
    assert job.company == "Acme Ltd"
    assert job.location == "Bristol"
    assert job.salary_min == 65000
    assert job.description == "Lead delivery teams."
    assert job.source == "reed"
    assert job.employment_type == "permanent"
    assert job.url == "https://www.reed.co.uk/jobs/x/53819371"


def test_fetch_reed_job_requires_api_key(monkeypatch):
    monkeypatch.delenv("REED_API_KEY", raising=False)
    with pytest.raises(ValueError, match="REED_API_KEY"):
        fetch_reed_job("https://www.reed.co.uk/jobs/x/53819371")


def test_resolve_job_linkedin_is_unsupported():
    with pytest.raises(UnsupportedSourceError, match="job-file"):
        resolve_job("https://uk.linkedin.com/jobs/view/123456")


def test_resolve_job_indeed_is_unsupported():
    with pytest.raises(UnsupportedSourceError, match="job-file"):
        resolve_job("https://uk.indeed.com/viewjob?jk=abc123")


def test_load_job_file(tmp_path):
    p = tmp_path / "job.yaml"
    p.write_text(
        "title: Programme Lead\n"
        "company: Beta Corp\n"
        "location: Bath\n"
        "salary_min: 70000\n"
        "description: Run programmes.\n"
        "employment_type: permanent\n"
        "source: linkedin\n",
        encoding="utf-8",
    )
    job = load_job_file(str(p))
    assert job.title == "Programme Lead"
    assert job.company == "Beta Corp"
    assert job.salary_min == 70000
    assert job.source == "linkedin"
    assert job.employment_type == "permanent"


def test_resolve_job_prefers_job_file_over_url(tmp_path):
    p = tmp_path / "job.yaml"
    p.write_text("title: X\ncompany: Y\nlocation: Z\nsalary_min: 60000\n"
                 "description: d\nemployment_type: permanent\nsource: reed\n",
                 encoding="utf-8")
    job = resolve_job("https://uk.linkedin.com/jobs/view/1", job_file=str(p))
    assert job.title == "X"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_job_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.job_resolver'`.

- [ ] **Step 3: Implement `job_resolver.py`**

Create `src/job_search_email/job_resolver.py`:

```python
import os
import re
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup

from .models import JobListing
from .search_api.reed import _parse_employment_type

_REED_DETAIL_URL = "https://www.reed.co.uk/api/1.0/jobs/{job_id}"
_REED_ID_RE = re.compile(r"/(\d+)/?(?:\?|$)")
_NHS_SALARY_RE = re.compile(r"£([\d,]+)")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class UnsupportedSourceError(Exception):
    """Raised when a URL's source cannot be auto-fetched."""


def _extract_reed_id(url: str) -> str:
    match = _REED_ID_RE.search(urlparse(url).path)
    if not match:
        raise ValueError(f"could not extract Reed job id from URL: {url!r}")
    return match.group(1)


def fetch_reed_job(url: str) -> JobListing:
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        raise ValueError("REED_API_KEY environment variable is not set")
    job_id = _extract_reed_id(url)
    response = requests.get(
        _REED_DETAIL_URL.format(job_id=job_id), auth=(api_key, ""), timeout=30
    )
    response.raise_for_status()
    item = response.json()
    return JobListing(
        title=item.get("jobTitle", ""),
        company=item.get("employerName", ""),
        location=item.get("locationName", ""),
        salary_min=item.get("minimumSalary"),
        description=item.get("jobDescription", ""),
        url=url,
        source="reed",
        employment_type=_parse_employment_type(item),
    )


def fetch_nhs_job(url: str) -> JobListing:
    response = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    def _text(selector: str) -> str:
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else ""

    title = _text("h1")
    salary_text = soup.get_text(" ", strip=True)
    salary_match = _NHS_SALARY_RE.search(salary_text)
    salary_min = int(salary_match.group(1).replace(",", "")) if salary_match else None

    return JobListing(
        title=title,
        company=_text("[data-test='employer-name']") or _text(".nhsuk-caption-l"),
        location=_text("[data-test='location']"),
        salary_min=salary_min,
        description="",  # mirrors the pipeline: NHS descriptions are never fetched
        url=url,
        source="nhs",
        employment_type=None,
    )


def load_job_file(path: str) -> JobListing:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return JobListing(
        title=data.get("title", ""),
        company=data.get("company", ""),
        location=data.get("location", ""),
        salary_min=data.get("salary_min"),
        description=data.get("description", ""),
        url=data.get("url", ""),
        source=data.get("source", "manual"),
        employment_type=data.get("employment_type"),
    )


def resolve_job(url: str | None, job_file: str | None = None) -> JobListing:
    if job_file:
        return load_job_file(job_file)
    if not url:
        raise ValueError("a job URL or --job-file is required")
    host = (urlparse(url).hostname or "").lower()
    if "reed.co.uk" in host:
        return fetch_reed_job(url)
    if "jobs.nhs.uk" in host:
        return fetch_nhs_job(url)
    raise UnsupportedSourceError(
        f"cannot auto-fetch jobs from {host or url!r}; "
        "supply the job details with --job-file"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_job_resolver.py -v`
Expected: PASS (all 8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/job_resolver.py tests/test_job_resolver.py
git commit -m "feat: add job_resolver for URL/job-file to JobListing"
```

---

### Task 3: Filter trace — run every gate, report each verdict

Produce a `GateResult` per hard filter, in pipeline order, reusing the real
`filter._check_*` functions so the trace matches production. Unlike
`filter_jobs`, this runs **all** gates (it does not short-circuit) and flags
which gate would be the first to reject.

**Files:**
- Create: `src/job_search_email/filter_trace.py`
- Test: `tests/test_filter_trace.py` (Create)

**Interfaces:**
- Consumes: `filter._check_location`, `filter._check_employment_type`, `filter._check_role_suitability`, `filter._check_nhs_band_salary`, `filter._check_sponsor`; `JobListing`, `Profile`.
- Produces:
  - `GateResult` dataclass: `name: str`, `passed: bool`, `detail: str`, `is_first_reject: bool`.
  - `run_filter_gates(job: JobListing, profile: Profile, *, location_verdict: str, sponsor_set: frozenset[str], nhs_rules: dict, exclusion_roles: list[str]) -> list[GateResult]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_filter_trace.py`:

```python
from job_search_email.filter_trace import GateResult, run_filter_gates
from job_search_email.models import JobListing, Profile
from job_search_email.nhs_rules import get_nhs_rules


def _job(**kw) -> JobListing:
    defaults = dict(
        title="Project Manager", company="Acme Industries Ltd", location="Bristol",
        salary_min=65000, description="Lead delivery.", url="https://x/1",
        source="reed", employment_type="permanent",
    )
    defaults.update(kw)
    return JobListing(**defaults)


def _profile() -> Profile:
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=[], previous_roles=[], target_roles=[],
        open_to=[], not_open_to=[], qualifications=[],
        employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


_SPONSORS = frozenset({"acme industries"})


def _gates(job, **over):
    kw = dict(location_verdict="within", sponsor_set=_SPONSORS,
              nhs_rules=get_nhs_rules(), exclusion_roles=["nurse"])
    kw.update(over)
    return run_filter_gates(job, _profile(), **kw)


def test_all_gates_reported_in_order():
    gates = _gates(_job())
    names = [g.name for g in gates]
    assert names == [
        "Location", "Employment type", "Role suitability",
        "NHS band salary", "Sponsor list",
    ]


def test_clean_job_passes_every_gate():
    gates = _gates(_job())
    assert all(g.passed for g in gates)
    assert not any(g.is_first_reject for g in gates)


def test_contract_job_fails_employment_gate():
    gates = _gates(_job(employment_type="contract"))
    by_name = {g.name: g for g in gates}
    assert by_name["Employment type"].passed is False
    assert by_name["Employment type"].is_first_reject is True


def test_reports_all_gates_even_after_first_reject():
    # Outside location AND non-sponsor: both fail, but only the first is flagged.
    job = _job(location="Aberdeen", company="Tiny")
    gates = _gates(job, location_verdict="outside", sponsor_set=frozenset())
    by_name = {g.name: g for g in gates}
    assert by_name["Location"].passed is False
    assert by_name["Location"].is_first_reject is True
    assert by_name["Sponsor list"].passed is False
    assert by_name["Sponsor list"].is_first_reject is False
    assert len(gates) == 5  # every gate still reported
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_filter_trace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.filter_trace'`.

- [ ] **Step 3: Implement `filter_trace.py`**

Create `src/job_search_email/filter_trace.py`:

```python
from dataclasses import dataclass

from .filter import (
    _check_employment_type,
    _check_location,
    _check_nhs_band_salary,
    _check_role_suitability,
    _check_sponsor,
)
from .models import JobListing, Profile


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    is_first_reject: bool


def run_filter_gates(
    job: JobListing,
    profile: Profile,
    *,
    location_verdict: str,
    sponsor_set: frozenset[str],
    nhs_rules: dict,
    exclusion_roles: list[str],
) -> list[GateResult]:
    gates: list[GateResult] = []

    # Location — reuse the real gate by deriving rejected_locations from the verdict.
    rejected_locations = frozenset({job.location}) if location_verdict == "outside" else frozenset()
    loc = _check_location(job, rejected_locations)
    gates.append(GateResult(
        "Location", loc is None,
        f"{location_verdict} radius ({job.location or 'not stated'})"
        if loc is None else (loc.reject_reason or ""),
        False,
    ))

    et = _check_employment_type(job)
    gates.append(GateResult(
        "Employment type", not et.rejected,
        (et.reject_reason or f"{job.employment_type or 'unknown'}"),
        False,
    ))

    role = _check_role_suitability(job, exclusion_roles)
    gates.append(GateResult(
        "Role suitability", role is None,
        "no excluded term matched" if role is None else (role.reject_reason or ""),
        False,
    ))

    nhs = _check_nhs_band_salary(job, nhs_rules, profile.min_salary)
    gates.append(GateResult(
        "NHS band salary", nhs is None,
        "n/a (no NHS band in title/description)" if nhs is None else (nhs.reject_reason or ""),
        False,
    ))

    sponsor = _check_sponsor(job, sponsor_set)
    gates.append(GateResult(
        "Sponsor list", sponsor is None,
        "n/a (NHS source)" if job.source == "nhs" and sponsor is None
        else ("on approved sponsor list" if sponsor is None else (sponsor.reject_reason or "")),
        False,
    ))

    for gate in gates:
        if not gate.passed:
            gate.is_first_reject = True
            break

    return gates
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_filter_trace.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/filter_trace.py tests/test_filter_trace.py
git commit -m "feat: add filter_trace reporting every hard gate verdict"
```

---

### Task 4: Renderer — readable text trace

Render a `JobListing`, its gate results, and (optionally) the scorer trace into
the terminal output described in the spec. Pure function, no I/O.

**Files:**
- Create: `src/job_search_email/explain_render.py`
- Test: `tests/test_explain_render.py` (Create)

**Interfaces:**
- Consumes: `JobListing`; `filter_trace.GateResult`; `scorer.AnalysisTrace`.
- Produces:
  - `render_explanation(job: JobListing, gates: list[GateResult], scorer_trace: AnalysisTrace | None, skipped_reason: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_explain_render.py`:

```python
from job_search_email.explain_render import render_explanation
from job_search_email.filter_trace import GateResult
from job_search_email.models import JobAnalysis, JobListing
from job_search_email.scorer import AnalysisTrace


def _job() -> JobListing:
    return JobListing(
        title="Senior Project Manager", company="Acme Ltd", location="Bristol",
        salary_min=65000, description="d", url="https://x/1",
        source="reed", employment_type="permanent",
    )


def _gates_all_pass() -> list[GateResult]:
    return [
        GateResult("Location", True, "within radius (Bristol)", False),
        GateResult("Employment type", True, "permanent", False),
        GateResult("Role suitability", True, "no excluded term matched", False),
        GateResult("NHS band salary", True, "n/a", False),
        GateResult("Sponsor list", True, "on approved sponsor list", False),
    ]


def _scorer_trace() -> AnalysisTrace:
    return AnalysisTrace(
        analysis=JobAnalysis(
            score=8, matched_skills=["delivery"], missing_essentials=["PRINCE2"],
            employment_type_note="Permanent", verdict="Strong match",
        ),
        system_prompt="SYS", user_message="USER", raw_text='{"score": 8}',
    )


def test_render_kept_job_includes_score_and_verbatim_llm():
    out = render_explanation(_job(), _gates_all_pass(), _scorer_trace(), None)
    assert "Senior Project Manager" in out
    assert "Acme Ltd" in out
    assert "Score: 8/10" in out
    assert "Strong match" in out
    assert "SYS" in out and "USER" in out and '{"score": 8}' in out
    assert "✓ Location" in out


def test_render_rejected_job_marks_first_reject_and_skips_scorer():
    gates = [
        GateResult("Location", True, "within radius (Bristol)", False),
        GateResult("Employment type", False, "employment type: contract", True),
        GateResult("Role suitability", True, "no excluded term matched", False),
        GateResult("NHS band salary", True, "n/a", False),
        GateResult("Sponsor list", True, "on approved sponsor list", False),
    ]
    out = render_explanation(_job(), gates, None, "rejected by Employment type")
    assert "✗ Employment type" in out
    assert "first reject" in out.lower()
    assert "rejected by Employment type" in out
    assert "AI SUITABILITY" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_explain_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.explain_render'`.

- [ ] **Step 3: Implement `explain_render.py`**

Create `src/job_search_email/explain_render.py`:

```python
from .filter_trace import GateResult
from .models import JobListing
from .scorer import AnalysisTrace

_RULE = "─" * 46


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "(none)"


def _gates_block(gates: list[GateResult]) -> str:
    lines = []
    for g in gates:
        mark = "✓" if g.passed else "✗"
        suffix = "   ← first reject" if g.is_first_reject else ""
        lines.append(f"{mark} {g.name:<18} {g.detail}{suffix}")
    return "\n".join(lines)


def _scorer_block(trace: AnalysisTrace) -> str:
    a = trace.analysis
    qual = a.qualification_status or "n/a"
    return (
        f"Score: {a.score}/10\n"
        f"Verdict: {a.verdict}\n"
        f"Matched: {_format_list(a.matched_skills)}\n"
        f"Missing: {_format_list(a.missing_essentials)}\n"
        f"Qualifications: {qual} (gaps: {_format_list(a.qualification_gaps)})\n"
        f"Exclude: {'yes — ' + a.exclude_reason if a.exclude else 'no'}\n"
        f"\n── LLM CALL (verbatim) {_RULE[:24]}\n"
        f"[system prompt]\n{trace.system_prompt}\n\n"
        f"[user message]\n{trace.user_message}\n\n"
        f"[raw response]\n{trace.raw_text}"
    )


def render_explanation(
    job: JobListing,
    gates: list[GateResult],
    scorer_trace: AnalysisTrace | None,
    skipped_reason: str | None,
) -> str:
    salary = f"£{job.salary_min:,}" if job.salary_min else "not stated"
    header = (
        f"JOB: {job.title} — {job.company}  ({job.source})\n"
        f"URL: {job.url or '(none)'}\n"
        f"Salary: {salary} | Type: {job.employment_type or 'not stated'} "
        f"| Location: {job.location or 'not stated'}\n"
    )

    parts = [header, f"── HARD FILTERS {_RULE}", _gates_block(gates)]

    if scorer_trace is not None:
        parts.append(f"\n── AI SUITABILITY {_RULE}")
        parts.append(_scorer_block(scorer_trace))
    elif skipped_reason is not None:
        parts.append(f"\n→ AI scorer skipped ({skipped_reason}). "
                     "Re-run with --force-score to score anyway.")

    return "\n".join(parts) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_explain_render.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/explain_render.py tests/test_explain_render.py
git commit -m "feat: add readable renderer for the explain-job trace"
```

---

### Task 5: Orchestration, CLI, and entry point

Wire the pieces together: parse args, load the profile, resolve the job,
classify its location, run the filter gates, run the scorer (unless rejected and
`--force-score` not set), and print the rendered trace. Register the
`explain-job` console script.

**Files:**
- Create: `src/job_search_email/explain_job.py`
- Modify: `pyproject.toml:25-27` (`[project.scripts]`)
- Test: `tests/test_explain_job.py` (Create)

**Interfaces:**
- Consumes: `main.load_profile`; `job_resolver.resolve_job`; `location_filter.classify_locations`; `sponsor_filter.load_sponsor_set`; `nhs_rules.get_nhs_rules`; `exclusions.get_exclusions`; `filter_trace.run_filter_gates`; `scorer.analyse_job`; `explain_render.render_explanation`.
- Produces:
  - `explain(url: str | None, *, profile_path: str = "profile.yaml", job_file: str | None = None, force_score: bool = False) -> str` (returns the rendered text).
  - `main(argv: list[str] | None = None) -> int` (CLI entry point; prints the text).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_explain_job.py`:

```python
from unittest.mock import patch

from job_search_email.models import JobAnalysis, JobListing, Profile
from job_search_email.scorer import AnalysisTrace


def _job(**kw) -> JobListing:
    defaults = dict(
        title="Project Manager", company="Acme Industries Ltd", location="Bristol",
        salary_min=65000, description="Lead delivery.", url="https://www.reed.co.uk/jobs/x/1",
        source="reed", employment_type="permanent",
    )
    defaults.update(kw)
    return JobListing(**defaults)


def _profile() -> Profile:
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=[], previous_roles=[], target_roles=[],
        open_to=[], not_open_to=[], qualifications=[],
        employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


def _trace() -> AnalysisTrace:
    return AnalysisTrace(
        analysis=JobAnalysis(
            score=8, matched_skills=[], missing_essentials=[],
            employment_type_note="", verdict="Strong match",
        ),
        system_prompt="SYS", user_message="USER", raw_text='{"score": 8}',
    )


def _patches(job, *, verdict="within"):
    return [
        patch("job_search_email.explain_job.load_profile", return_value=_profile()),
        patch("job_search_email.explain_job.resolve_job", return_value=job),
        patch("job_search_email.explain_job.classify_locations",
              return_value={job.location: verdict}),
        patch("job_search_email.explain_job.load_sponsor_set",
              return_value=frozenset({"acme industries"})),
        patch("job_search_email.explain_job.get_exclusions",
              return_value={"roles": ["nurse"], "employment_types": []}),
        patch("job_search_email.explain_job.analyse_job", return_value=_trace()),
    ]


def _run_explain(job, **kw):
    from job_search_email import explain_job
    ps = _patches(job, verdict=kw.pop("verdict", "within"))
    started = [p.start() for p in ps]
    try:
        return explain_job.explain("https://www.reed.co.uk/jobs/x/1", **kw)
    finally:
        for p in ps:
            p.stop()


def test_explain_scores_a_clean_job():
    out = _run_explain(_job())
    assert "Score: 8/10" in out
    assert "Strong match" in out
    assert "✓ Location" in out


def test_explain_skips_scorer_for_rejected_job():
    out = _run_explain(_job(employment_type="contract"))
    assert "AI SUITABILITY" not in out
    assert "scorer skipped" in out.lower()


def test_explain_force_scores_rejected_job():
    out = _run_explain(_job(employment_type="contract"), force_score=True)
    assert "Score: 8/10" in out


def test_main_prints_and_returns_zero(capsys):
    from job_search_email import explain_job
    ps = _patches(_job())
    started = [p.start() for p in ps]
    try:
        code = explain_job.main(["https://www.reed.co.uk/jobs/x/1"])
    finally:
        for p in ps:
            p.stop()
    assert code == 0
    assert "Score: 8/10" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_explain_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.explain_job'`.

- [ ] **Step 3: Implement `explain_job.py`**

Create `src/job_search_email/explain_job.py`:

```python
import argparse
import sys
from pathlib import Path

from .exclusions import get_exclusions
from .explain_render import render_explanation
from .filter_trace import run_filter_gates
from .job_resolver import UnsupportedSourceError, resolve_job
from .location_filter import classify_locations
from .main import SPONSOR_CACHE_PATH, load_profile
from .nhs_rules import get_nhs_rules
from .scorer import analyse_job
from .sponsor_filter import load_sponsor_set


def explain(
    url: str | None,
    *,
    profile_path: str = "profile.yaml",
    job_file: str | None = None,
    force_score: bool = False,
) -> str:
    profile = load_profile(Path(profile_path))
    job = resolve_job(url, job_file)

    if job.location:
        verdict = classify_locations(
            [job.location], home=profile.location,
            radius_miles=profile.radius_miles, cache={},
        ).get(job.location, "uncertain")
    else:
        verdict = "uncertain"

    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    gates = run_filter_gates(
        job, profile,
        location_verdict=verdict,
        sponsor_set=sponsor_set,
        nhs_rules=get_nhs_rules(),
        exclusion_roles=get_exclusions(profile)["roles"],
    )

    first_reject = next((g for g in gates if g.is_first_reject), None)
    if first_reject is not None and not force_score:
        return render_explanation(
            job, gates, None, f"rejected by {first_reject.name}"
        )

    scorer_trace = analyse_job(job, profile)
    return render_explanation(job, gates, scorer_trace, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="explain-job",
        description="Explain why a job got its rating by replaying the pipeline.",
    )
    parser.add_argument("url", nargs="?", help="Job URL (from the email).")
    parser.add_argument("--profile", default="profile.yaml",
                        help="Path to the profile YAML (default: profile.yaml).")
    parser.add_argument("--job-file",
                        help="YAML with job fields; fallback for LinkedIn/Indeed.")
    parser.add_argument("--force-score", action="store_true",
                        help="Run the AI scorer even if a hard filter rejected the job.")
    args = parser.parse_args(argv)

    try:
        output = explain(
            args.url, profile_path=args.profile,
            job_file=args.job_file, force_score=args.force_score,
        )
    except (UnsupportedSourceError, ValueError) as exc:
        print(f"explain-job: {exc}", file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Register the console script**

In `pyproject.toml`, under `[project.scripts]` (currently lines 25-27), add the
third entry so the block reads:

```toml
[project.scripts]
job-search-email = "job_search_email.main:main"
job-search-email-local = "job_search_email.local_run:main"
explain-job = "job_search_email.explain_job:main"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_explain_job.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 6: Run the full suite and reinstall the entry point**

Run: `python -m pytest -q`
Expected: PASS (entire suite green).

Run: `pip install -e .`
Expected: succeeds and registers the `explain-job` command.

Run: `explain-job --help`
Expected: prints usage showing `url`, `--profile`, `--job-file`, `--force-score`.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/explain_job.py pyproject.toml tests/test_explain_job.py
git commit -m "feat: add explain-job CLI command and entry point"
```

---

## Self-Review

**Spec coverage:**
- Interface (`explain-job <url>`, optional `--profile`/`--job-file`/`--force-score`) → Task 5.
- Local replay, no GitHub artifacts → Tasks 3–5 (reuses real logic locally).
- Reed fetch via job-detail API; NHS best-effort with empty description; LinkedIn/Indeed unsupported with `--job-file` fallback → Task 2.
- Scorer trace exposing verbatim system prompt + user message + raw response → Tasks 1 & 4.
- Filter trace running every gate with first-reject marker → Tasks 3 & 4.
- Rejected job skips scorer unless `--force-score` → Task 5; rendered note → Task 4.
- Missing `REED_API_KEY` fails fast → Task 2 (`fetch_reed_job`); surfaced as exit code 2 → Task 5 `main`.
- Tests for resolver, filter trace, scorer seam, renderer → Tasks 1–4; orchestration → Task 5.

**Placeholder scan:** No TBD/TODO; every code step contains full implementation and test code.

**Type consistency:** `AnalysisTrace(analysis, system_prompt, user_message, raw_text)` defined in Task 1 and consumed identically in Tasks 4 & 5. `GateResult(name, passed, detail, is_first_reject)` defined in Task 3 and consumed identically in Tasks 4 & 5. `resolve_job(url, job_file)`, `run_filter_gates(...)` keyword signature, `analyse_job(job, profile)`, `render_explanation(job, gates, scorer_trace, skipped_reason)`, and `explain(...)` signatures match across producer and consumer tasks.
