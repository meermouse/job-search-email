# Deep Job Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-powered scoring step that rates each kept job 1–10 against the candidate profile, producing a structured analysis (matched skills, missing essentials, employment-type confirmation, verdict) for display in the email.

**Architecture:** After `filter_jobs` produces `FilteredResult` objects, a new `score_jobs` function in `scorer.py` sorts kept jobs by salary, takes the top N (env-configured), fires concurrent Claude API calls (one per job), and returns `ScoredResult` objects with a `JobAnalysis` attached. Jobs that fail or are beyond the cap get `analysis=None`.

**Tech Stack:** Python 3.11, `anthropic>=0.40` (already installed), `ThreadPoolExecutor` (stdlib), `unittest.mock` for tests, `pytest`.

## Global Constraints

- Python 3.11+ — use `list[X]`, `X | None` union syntax (no `Optional`)
- `anthropic` client instantiated at module level as `client = anthropic.Anthropic()`
- Mock at `patch("job_search_email.scorer.client")` or `patch("job_search_email.scorer._analyse_job")` — never mock at the `anthropic` package level
- Description truncated to 1,500 characters per job
- Cap read from `DEEP_ANALYSIS_LIMIT` env var (default `"20"`)
- Model read from `SCORER_MODEL` env var (default `"claude-haiku-4-5-20251001"`)
- All tests in `tests/test_scorer.py`
- Follow existing test style: flat functions, `make_job`/`make_profile` helpers, `assert` statements

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/job_search_email/models.py` | Modify | Add `JobAnalysis` and `ScoredResult` dataclasses |
| `src/job_search_email/scorer.py` | Create | `score_jobs`, `_analyse_job`, prompt builders |
| `src/job_search_email/main.py` | Modify | Wire in `score_jobs`, add `write_scored_results`, `SCORED_RESULTS_PATH` |
| `tests/test_scorer.py` | Create | All tests for models, scorer, and write_scored_results |

---

## Task 1: Data Models

**Files:**
- Modify: `src/job_search_email/models.py`
- Create: `tests/test_scorer.py`

**Interfaces:**
- Produces:
  - `JobAnalysis(score: int, matched_skills: list[str], missing_essentials: list[str], employment_type_note: str, verdict: str)`
  - `ScoredResult(job: JobListing, flags: list[str], rejected: bool, reject_reason: str | None, analysis: JobAnalysis | None)`

- [ ] **Step 1: Write failing tests for the new dataclasses**

Create `tests/test_scorer.py`:

```python
from dataclasses import asdict
from job_search_email.models import JobAnalysis, JobListing, ScoredResult


def make_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Business Manager", company="NHS Trust", location="Bristol",
        salary_min=65000, description="Senior role.", url="https://example.com/1",
        source="reed", employment_type="full-time",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def make_analysis(**kwargs) -> JobAnalysis:
    defaults = dict(
        score=7,
        matched_skills=["digital transformation"],
        missing_essentials=[],
        employment_type_note="Permanent full-time confirmed",
        verdict="Strong match for senior management roles.",
    )
    defaults.update(kwargs)
    return JobAnalysis(**defaults)


def test_job_analysis_fields():
    a = make_analysis()
    assert a.score == 7
    assert a.matched_skills == ["digital transformation"]
    assert a.missing_essentials == []
    assert a.employment_type_note == "Permanent full-time confirmed"
    assert a.verdict == "Strong match for senior management roles."


def test_scored_result_with_analysis():
    result = ScoredResult(
        job=make_job(), flags=[], rejected=False,
        reject_reason=None, analysis=make_analysis(),
    )
    assert result.analysis.score == 7
    assert result.rejected is False


def test_scored_result_analysis_can_be_none():
    result = ScoredResult(
        job=make_job(), flags=[], rejected=True,
        reject_reason="employment type: contract", analysis=None,
    )
    assert result.analysis is None
    assert result.rejected is True


def test_scored_result_serialises_with_asdict():
    result = ScoredResult(
        job=make_job(), flags=[], rejected=False,
        reject_reason=None, analysis=make_analysis(),
    )
    data = asdict(result)
    assert data["analysis"]["score"] == 7
    assert data["job"]["title"] == "Business Manager"
    assert data["analysis"]["matched_skills"] == ["digital transformation"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_scorer.py -v
```

Expected: `ImportError` — `JobAnalysis` and `ScoredResult` not yet defined.

- [ ] **Step 3: Add the two dataclasses to models.py**

Open `src/job_search_email/models.py`. Append after the existing `FilteredResult` dataclass:

```python
@dataclass
class JobAnalysis:
    score: int
    matched_skills: list[str]
    missing_essentials: list[str]
    employment_type_note: str
    verdict: str


@dataclass
class ScoredResult:
    job: JobListing
    flags: list[str]
    rejected: bool
    reject_reason: str | None
    analysis: JobAnalysis | None
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_scorer.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/models.py tests/test_scorer.py
git commit -m "feat: add JobAnalysis and ScoredResult dataclasses"
```

---

## Task 2: scorer.py

**Files:**
- Create: `src/job_search_email/scorer.py`
- Modify: `tests/test_scorer.py`

**Interfaces:**
- Consumes:
  - `FilteredResult` from `models.py`
  - `Profile` from `models.py`
  - `anthropic.Anthropic()` client (module-level `client`)
- Produces:
  - `score_jobs(results: list[FilteredResult], profile: Profile) -> list[ScoredResult]`
  - `_analyse_job(job: JobListing, system_prompt: str, model: str) -> JobAnalysis` (internal, but patchable in tests)

- [ ] **Step 1: Add failing tests for scorer.py**

Append to `tests/test_scorer.py`:

```python
import json
from unittest.mock import MagicMock, patch

from job_search_email.models import FilteredResult, Profile
from job_search_email.scorer import score_jobs


def make_profile() -> Profile:
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=["digital transformation"],
        previous_roles=[], target_roles=["Business Manager"],
        open_to=[], not_open_to=["clinical roles"],
        qualifications=["MSc Management"],
        employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


def make_kept(job=None, flags=None) -> FilteredResult:
    return FilteredResult(
        job=job or make_job(), flags=flags or [],
        rejected=False, reject_reason=None,
    )


def make_rejected(job=None) -> FilteredResult:
    return FilteredResult(
        job=job or make_job(), flags=[],
        rejected=True, reject_reason="employment type: contract",
    )


_GOOD_RESPONSE = json.dumps({
    "score": 8,
    "matched_skills": ["digital transformation", "Project management"],
    "missing_essentials": [],
    "employment_type_note": "Permanent full-time confirmed",
    "verdict": "Strong match for this senior management role.",
})


def _mock_client(text: str = _GOOD_RESPONSE) -> MagicMock:
    m = MagicMock()
    m.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return m


def test_score_jobs_empty_returns_empty():
    assert score_jobs([], make_profile()) == []


def test_score_jobs_rejected_result_gets_no_analysis():
    results = [make_rejected()]
    with patch("job_search_email.scorer.client", _mock_client()):
        scored = score_jobs(results, make_profile())
    assert len(scored) == 1
    assert scored[0].analysis is None
    assert scored[0].rejected is True


def test_score_jobs_parses_claude_response():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client()):
        scored = score_jobs(results, make_profile())
    assert len(scored) == 1
    a = scored[0].analysis
    assert a is not None
    assert a.score == 8
    assert a.matched_skills == ["digital transformation", "Project management"]
    assert a.missing_essentials == []
    assert a.employment_type_note == "Permanent full-time confirmed"
    assert "senior management" in a.verdict


def test_score_jobs_sorts_by_salary_before_cap():
    high = make_job(salary_min=80000, url="https://example.com/high")
    mid = make_job(salary_min=70000, url="https://example.com/mid")
    low = make_job(salary_min=60000, url="https://example.com/low")
    results = [make_kept(low), make_kept(high), make_kept(mid)]

    with patch("job_search_email.scorer.client", _mock_client()), \
         patch.dict("os.environ", {"DEEP_ANALYSIS_LIMIT": "2"}):
        scored = score_jobs(results, make_profile())

    analysed_urls = {r.job.url for r in scored if r.analysis is not None}
    assert "https://example.com/high" in analysed_urls
    assert "https://example.com/mid" in analysed_urls
    assert "https://example.com/low" not in analysed_urls


def test_score_jobs_beyond_cap_gets_none_analysis():
    results = [make_kept() for _ in range(3)]
    with patch("job_search_email.scorer.client", _mock_client()), \
         patch.dict("os.environ", {"DEEP_ANALYSIS_LIMIT": "2"}):
        scored = score_jobs(results, make_profile())
    none_kept = [r for r in scored if not r.rejected and r.analysis is None]
    assert len(none_kept) == 1


def test_score_jobs_api_failure_adds_flag():
    results = [make_kept()]
    m = MagicMock()
    m.messages.create.side_effect = ConnectionError("API unreachable")
    with patch("job_search_email.scorer.client", m):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis is None
    assert "analysis_failed" in scored[0].flags


def test_score_jobs_bad_json_adds_flag():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client("not valid json")):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis is None
    assert "analysis_failed" in scored[0].flags


def test_score_jobs_sorts_kept_by_score_desc():
    jobs = [
        make_job(salary_min=65000, url="https://example.com/a"),
        make_job(salary_min=65000, url="https://example.com/b"),
        make_job(salary_min=65000, url="https://example.com/c"),
    ]
    results = [make_kept(j) for j in jobs]

    score_map = {
        "https://example.com/a": 5,
        "https://example.com/b": 9,
        "https://example.com/c": 3,
    }

    def fake_analyse(job, system_prompt, model):
        return JobAnalysis(
            score=score_map[job.url],
            matched_skills=[], missing_essentials=[],
            employment_type_note="", verdict="",
        )

    with patch("job_search_email.scorer._analyse_job", side_effect=fake_analyse):
        scored = score_jobs(results, make_profile())

    kept = [r for r in scored if not r.rejected and r.analysis is not None]
    scores = [r.analysis.score for r in kept]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_scorer.py -v -k "score_jobs"
```

Expected: `ModuleNotFoundError: No module named 'job_search_email.scorer'`

- [ ] **Step 3: Create scorer.py**

Create `src/job_search_email/scorer.py`:

```python
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from .models import FilteredResult, JobAnalysis, JobListing, Profile, ScoredResult

client = anthropic.Anthropic()

_DESCRIPTION_LIMIT = 1500


def _build_system_prompt(profile: Profile) -> str:
    return (
        "You are a job suitability analyst. Evaluate whether the following job is a good "
        "match for this candidate. Respond only with valid JSON matching the schema provided.\n\n"
        "Candidate profile:\n"
        f"- Seniority: {profile.seniority}\n"
        f"- Target roles: {', '.join(profile.target_roles)}\n"
        f"- Open to: {', '.join(profile.open_to)}\n"
        f"- Not open to: {', '.join(profile.not_open_to)}\n"
        f"- Skills: {', '.join(profile.skills)}\n"
        f"- Qualifications: {', '.join(profile.qualifications)}\n"
        "- Employment type wanted: full-time permanent only\n"
        f"- Min salary: £{profile.min_salary:,}\n\n"
        "Score guidance: 8-10 = strong match (profile clearly fits). "
        "5-7 = partial match (relevant but gaps present). "
        "1-4 = weak (missing essentials or significant misalignment)."
    )


def _build_user_message(job: JobListing) -> str:
    salary = f"£{job.salary_min:,}" if job.salary_min else "not stated"
    description = (job.description or "")[:_DESCRIPTION_LIMIT]
    return (
        f"Job title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'not stated'}\n"
        f"Salary: {salary}\n"
        f"Employment type: {job.employment_type or 'not stated'}\n"
        f"Description:\n{description}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "score": <1-10>,\n'
        '  "matched_skills": ["..."],\n'
        '  "missing_essentials": ["..."],\n'
        '  "employment_type_note": "...",\n'
        '  "verdict": "..."\n'
        "}"
    )


def _analyse_job(job: JobListing, system_prompt: str, model: str) -> JobAnalysis:
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_user_message(job)}],
    )
    data = json.loads(response.content[0].text)
    return JobAnalysis(
        score=int(data["score"]),
        matched_skills=data.get("matched_skills", []),
        missing_essentials=data.get("missing_essentials", []),
        employment_type_note=data.get("employment_type_note", ""),
        verdict=data.get("verdict", ""),
    )


def score_jobs(results: list[FilteredResult], profile: Profile) -> list[ScoredResult]:
    limit = int(os.getenv("DEEP_ANALYSIS_LIMIT", "20"))
    model = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")

    rejected = [r for r in results if r.rejected]
    kept = [r for r in results if not r.rejected]

    kept_sorted = sorted(kept, key=lambda r: r.job.salary_min or 0, reverse=True)
    to_analyse = kept_sorted[:limit]
    beyond_cap = kept_sorted[limit:]

    system_prompt = _build_system_prompt(profile)
    scored_map: dict[int, ScoredResult] = {}

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_analyse_job, r.job, system_prompt, model): (i, r)
            for i, r in enumerate(to_analyse)
        }
        for future in as_completed(futures):
            idx, r = futures[future]
            try:
                analysis = future.result()
                scored_map[idx] = ScoredResult(
                    job=r.job, flags=r.flags, rejected=r.rejected,
                    reject_reason=r.reject_reason, analysis=analysis,
                )
            except Exception:
                scored_map[idx] = ScoredResult(
                    job=r.job, flags=r.flags + ["analysis_failed"],
                    rejected=r.rejected, reject_reason=r.reject_reason,
                    analysis=None,
                )

    scored_analysed = [scored_map[i] for i in range(len(to_analyse))]
    scored_analysed.sort(
        key=lambda r: r.analysis.score if r.analysis else 0,
        reverse=True,
    )

    scored_beyond = [
        ScoredResult(
            job=r.job, flags=r.flags, rejected=r.rejected,
            reject_reason=r.reject_reason, analysis=None,
        )
        for r in beyond_cap
    ]

    scored_rejected = [
        ScoredResult(
            job=r.job, flags=r.flags, rejected=r.rejected,
            reject_reason=r.reject_reason, analysis=None,
        )
        for r in rejected
    ]

    return scored_analysed + scored_beyond + scored_rejected
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_scorer.py -v -k "score_jobs"
```

Expected: 9 tests PASS.

- [ ] **Step 5: Run full test suite to check no regressions**

```
pytest -q
```

Expected: all existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/scorer.py tests/test_scorer.py
git commit -m "feat: add scorer.py with concurrent LLM-powered job scoring"
```

---

## Task 3: Wire into main.py

**Files:**
- Modify: `src/job_search_email/main.py`
- Modify: `tests/test_scorer.py`

**Interfaces:**
- Consumes:
  - `score_jobs(results: list[FilteredResult], profile: Profile) -> list[ScoredResult]` from `scorer.py`
  - `ScoredResult` from `models.py`
- Produces:
  - `write_scored_results(results: list[ScoredResult], path: Path) -> None`
  - `SCORED_RESULTS_PATH: Path`

- [ ] **Step 1: Add failing tests for write_scored_results**

Append to `tests/test_scorer.py`:

```python
import json
from pathlib import Path

from job_search_email.main import write_scored_results
from job_search_email.models import ScoredResult


def make_scored_kept(score: int = 7, url: str = "https://example.com/1") -> ScoredResult:
    return ScoredResult(
        job=make_job(url=url), flags=[], rejected=False, reject_reason=None,
        analysis=make_analysis(score=score),
    )


def make_scored_rejected() -> ScoredResult:
    return ScoredResult(
        job=make_job(), flags=[], rejected=True,
        reject_reason="employment type: contract", analysis=None,
    )


def make_scored_unanalysed() -> ScoredResult:
    return ScoredResult(
        job=make_job(), flags=[], rejected=False, reject_reason=None, analysis=None,
    )


def test_write_scored_results_creates_file(tmp_path: Path):
    results = [make_scored_kept(), make_scored_rejected()]
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results(results, path=output_path)

    assert output_path.exists()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "summary" in data
    assert "kept" in data
    assert "rejected" in data


def test_write_scored_results_summary_counts(tmp_path: Path):
    results = [
        make_scored_kept(score=8, url="https://example.com/a"),
        make_scored_kept(score=5, url="https://example.com/b"),
        make_scored_rejected(),
        make_scored_unanalysed(),
    ]
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results(results, path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    s = data["summary"]
    assert s["total"] == 4
    assert s["kept"] == 3       # 2 scored + 1 unanalysed
    assert s["rejected"] == 1
    assert s["analysed"] == 2
    assert s["unanalysed"] == 1
    assert s["analysis_failed"] == 0


def test_write_scored_results_kept_sorted_by_score_desc(tmp_path: Path):
    results = [
        make_scored_kept(score=4, url="https://example.com/low"),
        make_scored_kept(score=9, url="https://example.com/high"),
        make_scored_kept(score=6, url="https://example.com/mid"),
    ]
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results(results, path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    scores = [r["analysis"]["score"] for r in data["kept"] if r["analysis"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9


def test_write_scored_results_analysis_failed_counted(tmp_path: Path):
    failed = ScoredResult(
        job=make_job(), flags=["analysis_failed"], rejected=False,
        reject_reason=None, analysis=None,
    )
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results([failed], path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["summary"]["analysis_failed"] == 1
    assert data["summary"]["unanalysed"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_scorer.py -v -k "write_scored"
```

Expected: `ImportError: cannot import name 'write_scored_results' from 'job_search_email.main'`

- [ ] **Step 3: Update main.py**

In `src/job_search_email/main.py`, make the following changes:

**3a.** Add `SCORED_RESULTS_PATH` alongside the other path constants (after `FILTERED_RESULTS_PATH`):

```python
SCORED_RESULTS_PATH = ROOT / "job_results_scored.json"
```

**3b.** Add import of `ScoredResult` to the models import line (it currently imports `FilteredResult, Profile, SearchPlan`):

```python
from .models import FilteredResult, Profile, SearchPlan, ScoredResult
```

**3c.** Add import of `score_jobs` alongside the other local imports:

```python
from .scorer import score_jobs
```

**3d.** Add `write_scored_results` function after the existing `write_filtered_results` function:

```python
def write_scored_results(results: list[ScoredResult], path: Path = SCORED_RESULTS_PATH) -> None:
    kept = [r for r in results if not r.rejected]
    rejected = [r for r in results if r.rejected]
    analysed = [r for r in kept if r.analysis is not None and "analysis_failed" not in r.flags]
    unanalysed = [r for r in kept if r.analysis is None and "analysis_failed" not in r.flags]
    failed = [r for r in kept if "analysis_failed" in r.flags]

    kept_sorted = sorted(kept, key=lambda r: (r.analysis.score if r.analysis else 0), reverse=True)

    output = {
        "summary": {
            "total": len(results),
            "kept": len(kept),
            "rejected": len(rejected),
            "analysed": len(analysed),
            "unanalysed": len(unanalysed),
            "analysis_failed": len(failed),
        },
        "kept": [asdict(r) for r in kept_sorted],
        "rejected": [asdict(r) for r in rejected],
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
```

**3e.** In the `main()` function, add the scoring step after the existing filter block (after the `write_filtered_results` call and its print statements):

```python
    print("Scoring jobs...")
    scored = score_jobs(filtered, profile)
    write_scored_results(scored)
    kept_scored = [r for r in scored if not r.rejected]
    top_score = max((r.analysis.score for r in kept_scored if r.analysis), default="n/a")
    print(f"- scored: {len(kept_scored)} kept, top score: {top_score}")
    print(f"- scored results written to: {SCORED_RESULTS_PATH}")
```

- [ ] **Step 4: Run write_scored_results tests to verify they pass**

```
pytest tests/test_scorer.py -v -k "write_scored"
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full test suite**

```
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/main.py tests/test_scorer.py
git commit -m "feat: wire score_jobs into main pipeline and add write_scored_results"
```

---

## Self-Review

**Spec coverage:**
- ✅ LLM call per job, concurrent — Task 2 `_analyse_job` + `ThreadPoolExecutor`
- ✅ Cap to top N, sorted by salary — Task 2 `score_jobs` pre-sort + slice
- ✅ `DEEP_ANALYSIS_LIMIT` env var (default 20) — Task 2
- ✅ `SCORER_MODEL` env var — Task 2
- ✅ Score 1–10 — `JobAnalysis.score`
- ✅ Matched skills — `JobAnalysis.matched_skills`
- ✅ Missing essentials — `JobAnalysis.missing_essentials`
- ✅ Employment type confirmation — `JobAnalysis.employment_type_note`
- ✅ 1-sentence verdict — `JobAnalysis.verdict`
- ✅ API failure → `analysis=None` + `"analysis_failed"` flag — Task 2 error handler
- ✅ Beyond cap → `analysis=None` — Task 2 `beyond_cap` list
- ✅ `job_results_scored.json` output — Task 3 `write_scored_results`
- ✅ Output sorted by score descending — Task 3 `write_scored_results`
- ✅ Summary counts (analysed / unanalysed / analysis_failed) — Task 3
- ✅ `main()` wired up — Task 3 step 3e

**Type consistency:** `ScoredResult` uses `JobAnalysis | None` for `analysis` in all three tasks. `score_jobs` returns `list[ScoredResult]`. `write_scored_results` accepts `list[ScoredResult]`. All consistent.

**No placeholders:** All steps contain actual code. No TBDs.
