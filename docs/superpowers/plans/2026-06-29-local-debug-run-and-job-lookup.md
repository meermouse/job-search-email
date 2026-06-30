# Local Debug Run + explain-job Job Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a developer recreate the pipeline locally without emailing (`job-search-debug`), and have `explain-job` resolve a job from that local run data — with its real parsed `employment_type` — and dump the exact `JobListing` it used.

**Architecture:** Extract the fetch→filter→score body of `main.main()` into a reusable `run_pipeline(profile)`. A new `debug_run` module calls it, writes a local decisions report, and never emails. `job_resolver` gains a run-data loader, URL lookup, and a `JobListing`→YAML dump; `resolve_job` consults run data before live fetching. `explain_job` wires the run-data path, a staleness note, and `--dump-job-file`.

**Tech Stack:** Python 3.11, `PyYAML`, `requests`, `beautifulsoup4`, `anthropic`, `pytest` (`unittest.mock` / `monkeypatch`).

## Global Constraints

- Python `>=3.11`; add no new dependencies.
- Console scripts live in `pyproject.toml` `[project.scripts]`. The new command is named exactly `job-search-debug`.
- `run_pipeline` MUST live in `job_search_email/main.py` and reference the module-level names (`fetch_all_jobs`, `classify_locations`, `score_jobs`, etc.) and the module-level path constants (`RESULTS_PATH`, `SCORED_RESULTS_PATH`, `LOCATION_CACHE_PATH`, `SCORE_CACHE_PATH`, `SPONSOR_CACHE_PATH`, `CACHE_PATH`, `PLAN_PATH`) directly — existing `tests/test_main.py` patches `job_search_email.main.*` and monkeypatches those constants, and must stay green.
- `main.main()`'s observable behaviour (email routing per profile flags) is unchanged.
- The debug command never calls `send_email` or `send_debug_report`.
- `job_results.json` is a JSON list of `JobListing` dicts (the format `main`/`run_pipeline` writes via `asdict`).
- Tests mock all network/LLM calls; no test makes a real network or API call.
- A local run is a fresh run, not the GitHub email run; the tool surfaces run-data age but does not claim exact-email fidelity.

---

### Task 1: Extract `run_pipeline` from `main.main()`

Move the fetch-through-score body of `main()` into a reusable `run_pipeline(profile)` that writes the run-data files and returns `(classification, scored)`. `main()` keeps loading the profile and doing the email routing.

**Files:**
- Modify: `src/job_search_email/main.py:164-245`
- Test: `tests/test_main.py` (add one test)

**Interfaces:**
- Consumes: existing module-level `fingerprint_profile`, `load_cached_plan`, `generate_search_plan`, `save_cached_plan`, `write_search_plan`, `fetch_all_jobs`, `load_location_cache`, `classify_locations`, `save_location_cache`, `load_sponsor_set`, `filter_jobs`, `write_filtered_results`, `load_score_cache`, `score_jobs`, `write_scored_results`, `_print_location_summary`, and the path constants; `Profile`, `ScoredResult`, `SearchPlan` (already imported).
- Produces: `run_pipeline(profile: Profile) -> tuple[dict[str, str], list[ScoredResult]]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py` (after the imports near the top it already has `from unittest.mock import patch`; reuse `make_profile`):

```python
def test_run_pipeline_writes_files_and_returns_tuple(tmp_path, monkeypatch):
    import sys, importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "PLAN_PATH", tmp_path / "plan.json")
    monkeypatch.setattr(main_mod, "RESULTS_PATH", tmp_path / "results.json")
    monkeypatch.setattr(main_mod, "FILTERED_RESULTS_PATH", tmp_path / "filtered.json")
    monkeypatch.setattr(main_mod, "SCORED_RESULTS_PATH", tmp_path / "scored.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")

    from job_search_email.models import JobListing, SearchPlan, ScoredResult, JobAnalysis, FilteredResult
    job = JobListing(
        title="Manager", company="NHS", location="Bristol",
        salary_min=65000, description="", url="https://x.com/1",
        source="reed", employment_type="full-time",
    )
    plan = SearchPlan(profile_fingerprint="test", queries=["q"],
                      exclusions={"roles": [], "employment_types": []},
                      nhs_rules={}, evaluator_notes=[])
    scored = [ScoredResult(job=job, flags=[], rejected=False, reject_reason=None,
                           analysis=JobAnalysis(score=7, matched_skills=[], missing_essentials=[],
                                                employment_type_note="", verdict="ok"))]

    with (
        patch("job_search_email.main.generate_search_plan", return_value=plan),
        patch("job_search_email.main.fetch_all_jobs", return_value=[job]),
        patch("job_search_email.main.classify_locations", return_value={"Bristol": "within"}),
        patch("job_search_email.main.score_jobs", return_value=scored),
    ):
        classification, result = main_mod.run_pipeline(make_profile())

    assert classification == {"Bristol": "within"}
    assert result == scored
    assert (tmp_path / "results.json").exists()
    assert (tmp_path / "scored.json").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_main.py::test_run_pipeline_writes_files_and_returns_tuple -v`
Expected: FAIL with `AttributeError: module 'job_search_email.main' has no attribute 'run_pipeline'`.

- [ ] **Step 3: Refactor `main.py`**

Replace the current `def main() -> None:` body (`main.py:164-245`) with a `run_pipeline` function plus a slimmed `main`. The pipeline code is moved verbatim; only the profile-load and email steps stay in `main`:

```python
def run_pipeline(profile: Profile) -> tuple[dict[str, Any], list[ScoredResult]]:
    fingerprint = fingerprint_profile(profile)
    cached = load_cached_plan(fingerprint=fingerprint)

    if cached:
        plan = SearchPlan(**cached)
    else:
        plan = generate_search_plan(profile, fingerprint)
        save_cached_plan(plan)
    write_search_plan(plan)

    print("Job search plan ready:")
    print(f"- profile: {profile.name}")
    print(f"- plan fingerprint: {fingerprint}")
    print(f"- queries: {len(plan.queries)}")

    print("Fetching jobs...")
    jobs = fetch_all_jobs(plan, profile)
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        json.dump([asdict(job) for job in jobs], handle, indent=2)
    print(f"- jobs fetched: {len(jobs)}")
    print(f"- results written to: {RESULTS_PATH}")
    _print_location_summary(jobs)

    print("Classifying job locations...")
    location_cache = load_location_cache(LOCATION_CACHE_PATH)
    unique_locations = list({j.location for j in jobs if j.location})
    classification = classify_locations(
        unique_locations,
        home=profile.location,
        radius_miles=profile.radius_miles,
        cache=location_cache,
    )
    save_location_cache(location_cache, LOCATION_CACHE_PATH)
    rejected_locations = frozenset(loc for loc, verdict in classification.items() if verdict == "outside")
    outside_count = len(rejected_locations)
    if outside_count:
        print(f"- {outside_count} location(s) classified as outside radius: {sorted(rejected_locations)}")

    print("Filtering jobs...")
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    print(f"- sponsor list loaded: {len(sponsor_set):,} entries")
    filtered = filter_jobs(
        jobs, plan, profile,
        rejected_locations=rejected_locations,
        sponsor_set=sponsor_set,
    )
    write_filtered_results(filtered)
    kept = [r for r in filtered if not r.rejected]
    flagged = [r for r in kept if r.flags]
    print(f"- filtered: {len(kept)} kept, {len(filtered) - len(kept)} rejected ({len(flagged)} flagged unknown employment type)")
    print(f"- filtered results written to: {FILTERED_RESULTS_PATH}")

    print("Scoring jobs...")
    score_cache = load_score_cache(SCORE_CACHE_PATH)
    scored = score_jobs(filtered, profile, score_cache=score_cache, cache_path=SCORE_CACHE_PATH)
    write_scored_results(scored)
    kept_scored = [r for r in scored if not r.rejected]
    top_score = max((r.analysis.score for r in kept_scored if r.analysis), default="n/a")
    print(f"- scored: {len(kept_scored)} kept, top score: {top_score}")
    print(f"- scored results written to: {SCORED_RESULTS_PATH}")

    return classification, scored


def main() -> None:
    profile = load_profile(PROFILE_PATH)
    classification, scored = run_pipeline(profile)

    print("Sending emails...")
    main_html, top_n = build_email_html(scored, profile)

    if profile.send_main_email:
        send_email(main_html, profile, n=top_n)
    elif profile.send_debug_email:
        smtp_user = os.getenv("SMTP_USER")
        if smtp_user:
            send_email(main_html, profile, n=top_n, override_to=smtp_user)
        else:
            print("[main] send_main_email=False but SMTP_USER not set — skipping main email redirect", file=sys.stderr)

    if profile.send_debug_email:
        debug_html = build_debug_email_html(classification, scored, profile)
        send_debug_report(debug_html)
```

`Any` is already imported (`from typing import Any` at `main.py:7`).

- [ ] **Step 4: Run the new test and the full main suite**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS — the new test passes and all existing main tests (location cache, email routing toggles) stay green.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "refactor: extract run_pipeline from main for reuse"
```

---

### Task 2: `job-search-debug` command

A new command that recreates the pipeline locally, writes a decisions report, prints a decisions summary, and never emails.

**Files:**
- Create: `src/job_search_email/debug_run.py`
- Modify: `pyproject.toml` `[project.scripts]`
- Test: `tests/test_debug_run.py` (Create)

**Interfaces:**
- Consumes: `main.load_profile`, `main.run_pipeline`, `main.PROFILE_PATH` (Task 1); `debug_email.build_debug_email_html`; `ScoredResult`.
- Produces: `main(argv: list[str] | None = None) -> int`; module-level `DEBUG_REPORT_PATH`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_debug_run.py`:

```python
from unittest.mock import patch

from job_search_email.models import JobAnalysis, JobListing, Profile, ScoredResult


def _profile() -> Profile:
    return Profile(
        name="Test", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


def _scored() -> list[ScoredResult]:
    job = JobListing(title="Manager", company="NHS Trust", location="Bristol",
                     salary_min=65000, description="", url="https://x/1",
                     source="reed", employment_type="full-time")
    rej = JobListing(title="Nurse", company="NHS", location="Bristol",
                     salary_min=30000, description="", url="https://x/2",
                     source="reed", employment_type="contract")
    return [
        ScoredResult(job=job, flags=[], rejected=False, reject_reason=None,
                     analysis=JobAnalysis(score=8, matched_skills=[], missing_essentials=[],
                                          employment_type_note="", verdict="ok")),
        ScoredResult(job=rej, flags=[], rejected=True,
                     reject_reason="employment type: contract", analysis=None),
    ]


def test_debug_run_writes_report_summary_and_never_emails(tmp_path, capsys, monkeypatch):
    from job_search_email import debug_run
    monkeypatch.setattr(debug_run, "DEBUG_REPORT_PATH", tmp_path / "debug_report.html")

    with (
        patch("job_search_email.debug_run.load_profile", return_value=_profile()),
        patch("job_search_email.debug_run.run_pipeline", return_value=({"Bristol": "within"}, _scored())),
        patch("job_search_email.debug_run.build_debug_email_html", return_value="<html>report</html>"),
        patch("job_search_email.main.send_email") as mock_send,
        patch("job_search_email.main.send_debug_report") as mock_debug,
    ):
        code = debug_run.main([])

    assert code == 0
    assert (tmp_path / "debug_report.html").read_text(encoding="utf-8") == "<html>report</html>"
    out = capsys.readouterr().out
    assert "Manager" in out and "NHS Trust" in out          # kept job listed
    assert "Nurse" in out and "employment type: contract" in out  # rejected job + reason
    mock_send.assert_not_called()
    mock_debug.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_debug_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'job_search_email.debug_run'`.

- [ ] **Step 3: Implement `debug_run.py`**

Create `src/job_search_email/debug_run.py`:

```python
from pathlib import Path

from .debug_email import build_debug_email_html
from .main import PROFILE_PATH, load_profile, run_pipeline
from .models import ScoredResult

DEBUG_REPORT_PATH = Path.cwd() / "debug_report.html"


def _print_decisions(scored: list[ScoredResult]) -> None:
    kept = [r for r in scored if not r.rejected]
    rejected = [r for r in scored if r.rejected]
    print("\nDecisions:")
    print(f"  {len(kept)} kept, {len(rejected)} rejected")
    for r in sorted(kept, key=lambda r: (r.analysis.score if r.analysis else 0), reverse=True):
        score = r.analysis.score if r.analysis else "—"
        print(f"  [keep] {score:>3}  {r.job.title} — {r.job.company}")
    for r in rejected:
        print(f"  [drop]      {r.job.title} — {r.job.company}  ({r.reject_reason})")


def main(argv: list[str] | None = None) -> int:
    profile = load_profile(PROFILE_PATH)
    classification, scored = run_pipeline(profile)

    html = build_debug_email_html(classification, scored, profile)
    DEBUG_REPORT_PATH.write_text(html, encoding="utf-8")

    _print_decisions(scored)
    print(f"\nDecisions report written to: {DEBUG_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Register the console script**

In `pyproject.toml`, add the entry so `[project.scripts]` reads:

```toml
[project.scripts]
job-search-email = "job_search_email.main:main"
job-search-email-local = "job_search_email.local_run:main"
explain-job = "job_search_email.explain_job:main"
job-search-debug = "job_search_email.debug_run:main"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_debug_run.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/debug_run.py pyproject.toml tests/test_debug_run.py
git commit -m "feat: add job-search-debug command (recreate pipeline, no email)"
```

---

### Task 3: Run-data loader, URL lookup, and job-file dump in `job_resolver`

Add the ability to load a `job_results.json` into a URL→`JobListing` map, look a URL up (exact then normalised), dump a `JobListing` back to a `--job-file`-format YAML, and consult run data inside `resolve_job` before live fetch.

**Files:**
- Modify: `src/job_search_email/job_resolver.py`
- Test: `tests/test_job_resolver.py` (add tests)

**Interfaces:**
- Consumes: existing `JobListing`, `load_job_file`, `urlparse`, `yaml`; add `import json` and `from pathlib import Path`.
- Produces:
  - `load_run_data(path) -> dict[str, JobListing]`
  - `lookup_job(url: str, run_data: dict[str, JobListing]) -> JobListing | None`
  - `dump_job_file(job: JobListing, path: str) -> None`
  - `resolve_job(url, job_file=None, *, run_data=None) -> JobListing` (run-data consulted before live fetch)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_job_resolver.py`:

```python
import json as _json

from job_search_email.job_resolver import (
    dump_job_file,
    load_job_file,
    load_run_data,
    lookup_job,
)
from job_search_email.models import JobListing


def _stored_job(**kw) -> JobListing:
    defaults = dict(
        title="Programme Lead", company="Beta Corp", location="Bristol",
        salary_min=70000, description="Run programmes.", url="https://uk.indeed.com/viewjob?jk=abc",
        source="indeed", employment_type="contract",
    )
    defaults.update(kw)
    return JobListing(**defaults)


def _write_run_data(path, jobs):
    from dataclasses import asdict
    path.write_text(_json.dumps([asdict(j) for j in jobs]), encoding="utf-8")


def test_load_run_data_maps_url_to_job(tmp_path):
    p = tmp_path / "job_results.json"
    _write_run_data(p, [_stored_job()])
    data = load_run_data(p)
    assert set(data) == {"https://uk.indeed.com/viewjob?jk=abc"}
    assert data["https://uk.indeed.com/viewjob?jk=abc"].employment_type == "contract"


def test_lookup_job_exact_and_normalised():
    job = _stored_job(url="https://www.reed.co.uk/jobs/x/123")
    data = {job.url: job}
    assert lookup_job("https://www.reed.co.uk/jobs/x/123", data) is job
    assert lookup_job("https://www.reed.co.uk/jobs/x/123/", data) is job   # trailing slash
    assert lookup_job("https://www.reed.co.uk/jobs/x/123?utm=1", data) is job  # query
    assert lookup_job("https://www.reed.co.uk/jobs/x/999", data) is None


def test_resolve_job_uses_run_data_for_unsupported_source():
    from job_search_email.job_resolver import resolve_job
    job = _stored_job()  # indeed url
    data = {job.url: job}
    resolved = resolve_job(job.url, run_data=data)
    assert resolved is job
    assert resolved.employment_type == "contract"


def test_resolve_job_run_data_precedes_live_fetch(monkeypatch):
    from unittest.mock import patch
    from job_search_email.job_resolver import resolve_job
    job = _stored_job(url="https://www.reed.co.uk/jobs/x/55", source="reed")
    data = {job.url: job}
    with patch("job_search_email.job_resolver.requests.get") as mock_get:
        resolved = resolve_job(job.url, run_data=data)
    assert resolved is job
    mock_get.assert_not_called()   # run data wins, no Reed call


def test_resolve_job_falls_through_to_live_fetch_when_not_in_run_data(monkeypatch):
    from job_search_email.job_resolver import resolve_job, UnsupportedSourceError
    import pytest
    data = {"https://other/1": _stored_job(url="https://other/1")}
    with pytest.raises(UnsupportedSourceError):
        resolve_job("https://uk.linkedin.com/jobs/view/9", run_data=data)


def test_dump_job_file_round_trips(tmp_path):
    job = _stored_job()
    out = tmp_path / "dumped.yaml"
    dump_job_file(job, str(out))
    reloaded = load_job_file(str(out))
    assert reloaded == job
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_job_resolver.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_run_data'` (and the others).

- [ ] **Step 3: Implement the additions in `job_resolver.py`**

Add `import json` and `from pathlib import Path` to the imports. Add these functions (e.g. after `load_job_file`):

```python
def load_run_data(path) -> dict[str, JobListing]:
    with Path(path).open("r", encoding="utf-8") as handle:
        items = json.load(handle)
    return {item["url"]: JobListing(**item) for item in items}


def _normalize_url(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}".lower()


def lookup_job(url: str, run_data: dict[str, JobListing]) -> JobListing | None:
    if url in run_data:
        return run_data[url]
    target = _normalize_url(url)
    for stored_url, job in run_data.items():
        if _normalize_url(stored_url) == target:
            return job
    return None


def dump_job_file(job: JobListing, path: str) -> None:
    data = {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "salary_min": job.salary_min,
        "description": job.description,
        "url": job.url,
        "source": job.source,
        "employment_type": job.employment_type,
    }
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
```

Replace `resolve_job` to consult run data before live fetch:

```python
def resolve_job(
    url: str | None,
    job_file: str | None = None,
    *,
    run_data: dict[str, JobListing] | None = None,
) -> JobListing:
    if job_file:
        return load_job_file(job_file)
    if not url:
        raise ValueError("a job URL or --job-file is required")
    if run_data:
        hit = lookup_job(url, run_data)
        if hit is not None:
            return hit
    host = (urlparse(url).hostname or "").lower()
    if "reed.co.uk" in host:
        return fetch_reed_job(url)
    if "jobs.nhs.uk" in host:
        return fetch_nhs_job(url)
    raise UnsupportedSourceError(
        f"cannot auto-fetch jobs from {host or url!r}; run `job-search-debug` first "
        "to populate local run data, or supply the job details with --job-file"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_job_resolver.py -v`
Expected: PASS (new tests plus the existing resolver tests, including the LinkedIn/Indeed unsupported-source tests, which still raise because those URLs aren't in run data).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/job_resolver.py tests/test_job_resolver.py
git commit -m "feat: run-data lookup and job-file dump in job_resolver"
```

---

### Task 4: Wire run-data + dump + staleness into explain-job

`explain` loads run data (default `job_results.json`, `--run-data` override), passes it to `resolve_job`, notes the run-data age in the trace, and writes the resolved `JobListing` to YAML with `--dump-job-file`.

**Files:**
- Modify: `src/job_search_email/explain_job.py`
- Modify: `src/job_search_email/explain_render.py` (optional `run_data_note` param)
- Modify: `tests/test_explain_job.py` (keep existing tests deterministic; add new tests)

**Interfaces:**
- Consumes: `job_resolver.load_run_data`, `job_resolver.lookup_job`, `job_resolver.dump_job_file`, `resolve_job` (Task 3); `render_explanation` (extended).
- Produces:
  - `render_explanation(job, gates, scorer_trace, skipped_reason, *, run_data_note: str | None = None) -> str`
  - `explain(url, *, profile_path="profile.yaml", job_file=None, force_score=False, run_data_path="job_results.json", dump_job_file_path=None) -> str`
  - `main` gains `--run-data` and `--dump-job-file`.

- [ ] **Step 1: Write the failing tests**

First, keep the existing tests deterministic: in `tests/test_explain_job.py`, the helper `_run_explain` and `test_main_prints_and_returns_zero` must not pick up a stray `job_results.json` from the cwd. Update both call sites to pass a non-existent run-data path.

In `_run_explain`, change the `explain` call to:

```python
        return explain_job.explain(
            "https://www.reed.co.uk/jobs/x/1",
            run_data_path="__no_such_run_data__.json",
            **kw,
        )
```

In `test_main_prints_and_returns_zero`, change the `main` call to:

```python
        code = explain_job.main(["https://www.reed.co.uk/jobs/x/1", "--run-data", "__no_such_run_data__.json"])
```

Then add new tests:

```python
import json as _json
from dataclasses import asdict


def _write_run_data(path, jobs):
    path.write_text(_json.dumps([asdict(j) for j in jobs]), encoding="utf-8")


def test_explain_resolves_from_run_data(tmp_path):
    from job_search_email import explain_job
    indeed_job = _job(
        url="https://uk.indeed.com/viewjob?jk=abc",
        source="indeed", employment_type="contract",
    )
    rd = tmp_path / "job_results.json"
    _write_run_data(rd, [indeed_job])

    ps = [
        patch("job_search_email.explain_job.load_profile", return_value=_profile()),
        patch("job_search_email.explain_job.classify_locations", return_value={"Bristol": "within"}),
        patch("job_search_email.explain_job.load_sponsor_set", return_value=frozenset({"acme industries"})),
        patch("job_search_email.explain_job.get_exclusions", return_value={"roles": [], "employment_types": []}),
        patch("job_search_email.explain_job.analyse_job", return_value=_trace()),
    ]
    for p in ps:
        p.start()
    try:
        out = explain_job.explain(
            "https://uk.indeed.com/viewjob?jk=abc",
            run_data_path=str(rd),
        )
    finally:
        for p in ps:
            p.stop()

    # Resolved an Indeed URL with no --job-file, and the employment-type gate saw "contract"
    assert "contract" in out
    assert str(rd.name) in out  # staleness/source note mentions the run-data file


def test_explain_dump_job_file_round_trips(tmp_path):
    from job_search_email import explain_job
    from job_search_email.job_resolver import load_job_file
    indeed_job = _job(url="https://uk.indeed.com/viewjob?jk=abc", source="indeed", employment_type="contract")
    rd = tmp_path / "job_results.json"
    _write_run_data(rd, [indeed_job])
    dump = tmp_path / "dumped.yaml"

    ps = [
        patch("job_search_email.explain_job.load_profile", return_value=_profile()),
        patch("job_search_email.explain_job.classify_locations", return_value={"Bristol": "within"}),
        patch("job_search_email.explain_job.load_sponsor_set", return_value=frozenset({"acme industries"})),
        patch("job_search_email.explain_job.get_exclusions", return_value={"roles": [], "employment_types": []}),
        patch("job_search_email.explain_job.analyse_job", return_value=_trace()),
    ]
    for p in ps:
        p.start()
    try:
        explain_job.explain("https://uk.indeed.com/viewjob?jk=abc",
                            run_data_path=str(rd), dump_job_file_path=str(dump))
    finally:
        for p in ps:
            p.stop()

    assert load_job_file(str(dump)) == indeed_job
```

(The `_job`, `_profile`, `_trace` helpers already exist in this file.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_explain_job.py -v`
Expected: FAIL — `explain()` does not yet accept `run_data_path`/`dump_job_file_path` (TypeError).

- [ ] **Step 3: Extend `explain_render.render_explanation`**

In `src/job_search_email/explain_render.py`, add an optional keyword param and render it in the header. Change the signature and the header block:

```python
def render_explanation(
    job: JobListing,
    gates: list[GateResult],
    scorer_trace: AnalysisTrace | None,
    skipped_reason: str | None,
    *,
    run_data_note: str | None = None,
) -> str:
    salary = f"£{job.salary_min:,}" if job.salary_min else "not stated"
    header = (
        f"JOB: {job.title} — {job.company}  ({job.source})\n"
        f"URL: {job.url or '(none)'}\n"
        f"Salary: {salary} | Type: {job.employment_type or 'not stated'} "
        f"| Location: {job.location or 'not stated'}\n"
    )
    if run_data_note is not None:
        header += f"Source: {run_data_note}\n"
    ...
```

(The rest of the function is unchanged.)

- [ ] **Step 4: Extend `explain_job.explain` and `main`**

In `src/job_search_email/explain_job.py`, add the imports and logic. Update the imports line:

```python
from .job_resolver import (
    UnsupportedSourceError,
    dump_job_file,
    load_run_data,
    lookup_job,
    resolve_job,
)
```

Add a small age formatter and rework `explain`:

```python
import time


def _format_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)}m old"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h old"
    return f"{int(seconds // 86400)}d old"


def explain(
    url: str | None,
    *,
    profile_path: str = "profile.yaml",
    job_file: str | None = None,
    force_score: bool = False,
    run_data_path: str = "job_results.json",
    dump_job_file_path: str | None = None,
) -> str:
    profile = load_profile(Path(profile_path))

    run_data = None
    run_data_note = None
    rd = Path(run_data_path)
    if rd.exists():
        run_data = load_run_data(rd)

    job = resolve_job(url, job_file, run_data=run_data)

    if run_data is not None and job_file is None and url is not None and lookup_job(url, run_data) is not None:
        age = _format_age(time.time() - rd.stat().st_mtime)
        run_data_note = f"{rd.name} (local run data, {age})"

    if dump_job_file_path:
        dump_job_file(job, dump_job_file_path)

    if job.location:
        verdict = classify_locations(
            [job.location], home=profile.location,
            radius_miles=profile.radius_miles, cache={},
        ).get(job.location, "uncertain")
    else:
        verdict = "uncertain"

    # NOTE: classify_locations and get_exclusions both make live LLM calls and
    # therefore require ANTHROPIC_API_KEY to be set, even when the job is
    # ultimately rejected by a hard filter gate (sponsor, employment-type, etc.).
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
            job, gates, None, f"rejected by {first_reject.name}",
            run_data_note=run_data_note,
        )

    scorer_trace = analyse_job(job, profile)
    return render_explanation(job, gates, scorer_trace, None, run_data_note=run_data_note)
```

Add the two CLI flags in `main` (after the existing `--force-score` arg) and pass them through:

```python
    parser.add_argument("--run-data", default="job_results.json",
                        help="Path to a local run's job_results.json (default: job_results.json).")
    parser.add_argument("--dump-job-file",
                        help="Write the resolved job's data to this YAML path.")
    args = parser.parse_args(argv)

    try:
        output = explain(
            args.url, profile_path=args.profile,
            job_file=args.job_file, force_score=args.force_score,
            run_data_path=args.run_data, dump_job_file_path=args.dump_job_file,
        )
    except (UnsupportedSourceError, ValueError) as exc:
        print(f"explain-job: {exc}", file=sys.stderr)
        return 2
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_explain_job.py tests/test_explain_render.py -v`
Expected: PASS — new run-data and dump tests pass; existing explain-job and renderer tests stay green.

- [ ] **Step 6: Run the full suite and reinstall the entry points**

Run: `python -m pytest -q`
Expected: PASS (entire suite green).

Run: `pip install -e .`
Expected: succeeds and registers `job-search-debug`.

Run: `job-search-debug --help` is not applicable (no argparse); instead verify import: `python -c "import job_search_email.debug_run"`
Expected: no error.

Run: `explain-job --help`
Expected: usage now lists `--run-data` and `--dump-job-file`.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/explain_job.py src/job_search_email/explain_render.py tests/test_explain_job.py
git commit -m "feat: explain-job resolves from local run data and dumps job-file"
```

---

## Self-Review

**Spec coverage:**
- `run_pipeline` extraction, behaviour-preserving → Task 1.
- `job-search-debug` command: real pipeline, decisions summary, `debug_report.html`, never emails → Task 2.
- Run-data loader, URL lookup (exact + normalised), resolver precedence (job-file → run data → live fetch → error), updated error message → Task 3.
- LinkedIn/Indeed URL in run data resolves without `--job-file`, carrying real `employment_type` → Tasks 3 & 4.
- `--dump-job-file` round-trips → Tasks 3 & 4.
- Staleness note from mtime → Task 4.
- Entry point registration → Task 2.

**Placeholder scan:** No TBD/TODO; every code step has full implementation and test code.

**Type consistency:** `run_pipeline(profile) -> tuple[dict, list[ScoredResult]]` produced in Task 1, consumed in Task 2. `load_run_data -> dict[str, JobListing]`, `lookup_job`, `dump_job_file`, and `resolve_job(..., run_data=...)` defined in Task 3 and consumed identically in Task 4. `render_explanation`'s new `run_data_note` keyword is added (Task 4) without breaking existing 4-positional-arg callers. `explain(...)` new keyword params are threaded through `main` consistently.
