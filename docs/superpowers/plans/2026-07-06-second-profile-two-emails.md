# Second Profile → Two Daily Emails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the daily pipeline once per profile discovered in a new `profiles/` directory, sending each person their own job email; add a per-profile `filter_sponsors` toggle; add Marc Brookes as the second profile.

**Architecture:** `main()` loops over `sorted(profiles/*.yaml)`, calling the existing pipeline per profile with per-profile run artifacts under `runs/<stem>/`, wrapped so one profile's failure doesn't block the others. The three root cache files stay shared (their keys already namespace by profile/fingerprint). The sponsor filter becomes a per-profile toggle mirroring `filter_recruitment` (pass `sponsor_set=None` to skip — `filter_jobs` already supports this).

**Tech Stack:** Python 3.11, PyYAML, pytest, dataclasses. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-06-second-profile-two-emails-design.md`

## Global Constraints

- Python `>=3.11`; run tests with `python -m pytest -q` from the repo root (the venv is `.venv`).
- No new dependencies.
- Cache files keep their repo-root paths and names: `search_plan_cache.json`, `job_score_cache.json`, `location_cache.json` (the GitHub Action's cache step must need **no change**).
- `.github/workflows/daily_job.yml` is **not modified**.
- Per-run artifacts move to `runs/<profile-stem>/` and keep their filenames: `search_plan.json`, `job_results.json`, `job_results_filtered.json`, `job_results_scored.json`.
- `filter_sponsors` defaults to `True` (silent/existing profiles keep sponsor-only behaviour).
- Commit after every task; suite must be green at every commit.

---

### Task 1: `filter_sponsors` profile field

**Files:**
- Modify: `src/job_search_email/models.py:44` (Profile dataclass, after `filter_recruitment`)
- Modify: `src/job_search_email/profile.py:59` (loader, after `filter_recruitment`)
- Test: `tests/test_main.py` (next to the existing `filter_recruitment` loader tests at lines 407-419)

**Interfaces:**
- Produces: `Profile.filter_sponsors: bool = True`; `load_profile` reads top-level YAML key `filter_sponsors` (default `True`). Tasks 2 and 4 read `profile.filter_sponsors`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py` (after `test_load_profile_filter_recruitment_reads_false`):

```python
def test_load_profile_filter_sponsors_defaults_true(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.filter_sponsors is True


def test_load_profile_filter_sponsors_reads_false(tmp_path: Path) -> None:
    yaml_with_filter = PROFILE_YAML + "filter_sponsors: false\n"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml_with_filter, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.filter_sponsors is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py::test_load_profile_filter_sponsors_defaults_true tests/test_main.py::test_load_profile_filter_sponsors_reads_false -q`
Expected: FAIL — `AttributeError: 'Profile' object has no attribute 'filter_sponsors'` (first test) / value mismatch (second).

- [ ] **Step 3: Implement**

In `src/job_search_email/models.py`, add to `Profile` after `filter_recruitment: bool = True`:

```python
    filter_sponsors: bool = True
```

In `src/job_search_email/profile.py`, in `load_profile`'s `Profile(...)` call, after `filter_recruitment=...`:

```python
        filter_sponsors=data.get("filter_sponsors", True),
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (the field has a default, so no fixture breaks).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/profile.py tests/test_main.py
git commit -m "feat: add per-profile filter_sponsors toggle (default on)"
```

---

### Task 2: `run_pipeline(profile, output_dir)` + sponsor toggle wiring

**Files:**
- Modify: `src/job_search_email/main.py` (constants at lines 25-35, `run_pipeline` at 137-205, `main` at 208-226)
- Modify: `src/job_search_email/debug_run.py:23-25` (caller of `run_pipeline`)
- Test: `tests/test_main.py` (rewrite path-patching in `test_main_loads_and_saves_location_cache`, `_run_main_with_toggles`, `test_run_pipeline_writes_files_and_returns_tuple`; add sponsor-toggle tests)

**Interfaces:**
- Consumes: `profile.filter_sponsors` (Task 1).
- Produces: `run_pipeline(profile: Profile, output_dir: Path) -> tuple[dict[str, Any], list[ScoredResult]]` — creates `output_dir` and writes `search_plan.json`, `job_results.json`, `job_results_filtered.json`, `job_results_scored.json` inside it. New module constant `RUNS_DIR = ROOT / "runs"`. Module constants `PLAN_PATH`, `RESULTS_PATH`, `FILTERED_RESULTS_PATH`, `SCORED_RESULTS_PATH` are **deleted** (Task 3's tests patch `RUNS_DIR` instead). `write_filtered_results` / `write_scored_results` keep their signatures but lose default `path` values (path becomes required).

- [ ] **Step 1: Write the failing tests**

In `tests/test_main.py`, replace `test_run_pipeline_writes_files_and_returns_tuple` (lines 516-553) with:

```python
def test_run_pipeline_writes_files_to_output_dir(tmp_path, monkeypatch):
    import sys, importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")

    from job_search_email.models import JobListing, SearchPlan, ScoredResult, JobAnalysis
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

    output_dir = tmp_path / "runs" / "test-user"
    with (
        patch("job_search_email.main.generate_search_plan", return_value=plan),
        patch("job_search_email.main.fetch_all_jobs", return_value=[job]),
        patch("job_search_email.main.classify_locations", return_value={"Bristol": "within"}),
        patch("job_search_email.main.score_jobs", return_value=scored),
    ):
        classification, result = main_mod.run_pipeline(make_profile(), output_dir)

    assert classification == {"Bristol": "within"}
    assert result == scored
    assert (output_dir / "search_plan.json").exists()
    assert (output_dir / "job_results.json").exists()
    assert (output_dir / "job_results_filtered.json").exists()
    assert (output_dir / "job_results_scored.json").exists()


def _run_pipeline_capture_filter_call(tmp_path, monkeypatch, profile):
    """Run run_pipeline with everything mocked; return the filter_jobs call kwargs."""
    import sys, importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")

    from job_search_email.models import JobListing, SearchPlan
    job = JobListing(
        title="Manager", company="NHS", location="Bristol",
        salary_min=65000, description="", url="https://x.com/1",
        source="reed", employment_type="full-time",
    )
    plan = SearchPlan(profile_fingerprint="test", queries=["q"],
                      exclusions={"roles": [], "employment_types": []},
                      nhs_rules={}, evaluator_notes=[])

    with (
        patch("job_search_email.main.generate_search_plan", return_value=plan),
        patch("job_search_email.main.fetch_all_jobs", return_value=[job]),
        patch("job_search_email.main.classify_locations", return_value={"Bristol": "within"}),
        patch("job_search_email.main.score_jobs", return_value=[]),
        patch("job_search_email.main.filter_jobs", return_value=[]) as mock_filter,
        patch("job_search_email.main.load_sponsor_set", return_value=frozenset({"acme"})) as mock_load,
    ):
        main_mod.run_pipeline(profile, tmp_path / "out")

    return mock_filter.call_args.kwargs, mock_load


def test_run_pipeline_sponsor_filter_on_passes_set(tmp_path, monkeypatch):
    kwargs, mock_load = _run_pipeline_capture_filter_call(
        tmp_path, monkeypatch, make_profile(filter_sponsors=True))
    mock_load.assert_called_once()
    assert kwargs["sponsor_set"] == frozenset({"acme"})


def test_run_pipeline_sponsor_filter_off_passes_none(tmp_path, monkeypatch):
    kwargs, mock_load = _run_pipeline_capture_filter_call(
        tmp_path, monkeypatch, make_profile(filter_sponsors=False))
    mock_load.assert_not_called()
    assert kwargs["sponsor_set"] is None
```

`make_profile` in this file (line 62) delegates to `profile_helpers.make_profile(**overrides)`, so `make_profile(filter_sponsors=False)` works via the dataclass default — but the local wrapper takes no args. Change the local `make_profile` (lines 62-71) to accept and forward overrides:

```python
def make_profile(**overrides) -> Profile:
    defaults = dict(
        name="Test User",
        about="Experienced project manager in NHS.",
        industry="NHS / Private Sector",
        skills=["stakeholder management", "digital transformation"],
        target_roles=["Programme Manager", "Digital Lead"],
        open_to=["Strategy Consultant"],
        not_open_to=["clinical roles", "nursing"],
    )
    defaults.update(overrides)
    return make_profile_helper(**defaults)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -q -k "run_pipeline"`
Expected: FAIL — `TypeError: run_pipeline() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement in main.py**

Replace the constants block (lines 25-35) with (note: four artifact constants deleted, `RUNS_DIR` added):

```python
ROOT = Path.cwd()
PROFILE_PATH = ROOT / "profile.yaml"
RUNS_DIR = ROOT / "runs"
CACHE_PATH = ROOT / "search_plan_cache.json"
SCORE_CACHE_PATH = ROOT / "job_score_cache.json"
LOCATION_CACHE_PATH = ROOT / "location_cache.json"
SPONSOR_CACHE_PATH = ROOT / "assets" / "sponsor_cache.csv"
RECRUITMENT_CACHE_PATH = ROOT / "assets" / "recruitment_agencies.csv"
```

Remove the `path: Path = ...` defaults from `write_filtered_results` and `write_scored_results` (make `path: Path` required).

Change `run_pipeline` to take `output_dir` and use it for the four artifacts, and gate the sponsor set on the profile toggle:

```python
def run_pipeline(profile: Profile, output_dir: Path) -> tuple[dict[str, Any], list[ScoredResult]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "search_plan.json"
    results_path = output_dir / "job_results.json"
    filtered_results_path = output_dir / "job_results_filtered.json"
    scored_results_path = output_dir / "job_results_scored.json"

    fingerprint = fingerprint_profile(profile)
    cached = load_cached_plan(cache_path=CACHE_PATH, fingerprint=fingerprint)

    if cached:
        plan = SearchPlan(**cached)
    else:
        plan = generate_search_plan(profile, fingerprint)
        save_cached_plan(plan, cache_path=CACHE_PATH)
    write_search_plan(plan, plan_path)
```

The body keeps its existing print statements and logic, with these substitutions:
- `RESULTS_PATH` → `results_path` (both the `open` and the print)
- `FILTERED_RESULTS_PATH` → `filtered_results_path`
- `SCORED_RESULTS_PATH` → `scored_results_path`
- The sponsor-loading lines (177-178) become:

```python
    if profile.filter_sponsors:
        sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
        print(f"- sponsor list loaded: {len(sponsor_set):,} entries")
    else:
        sponsor_set = None
        print("- sponsor filter disabled (filter_sponsors=false)")
```

In `main()` (line 210), update the call:

```python
    classification, scored = run_pipeline(profile, RUNS_DIR / PROFILE_PATH.stem)
```

In `src/job_search_email/debug_run.py`, update imports and the call (lines 4, 24-25):

```python
from .main import PROFILE_PATH, RUNS_DIR, run_pipeline
```

```python
    profile = load_profile(PROFILE_PATH)
    classification, scored = run_pipeline(profile, RUNS_DIR / PROFILE_PATH.stem)
```

- [ ] **Step 4: Fix the two main()-level tests that patch deleted constants**

In `tests/test_main.py`:

In `test_main_loads_and_saves_location_cache` (lines 310-319), replace the four deleted-constant patches — the monkeypatch block becomes:

```python
    monkeypatch.setattr(main_mod, "ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(main_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")
```

In `_run_main_with_toggles` (lines 436-445), the attr list becomes:

```python
    for attr, val in [
        ("ROOT", tmp_path), ("PROFILE_PATH", tmp_path / "profile.yaml"),
        ("RUNS_DIR", tmp_path / "runs"),
        ("CACHE_PATH", tmp_path / "plan_cache.json"),
        ("SCORE_CACHE_PATH", tmp_path / "score_cache.json"),
        ("LOCATION_CACHE_PATH", tmp_path / "location_cache.json"),
    ]:
        monkeypatch.setattr(main_mod, attr, val)
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/main.py src/job_search_email/debug_run.py tests/test_main.py
git commit -m "feat: per-run output dir for pipeline artifacts + sponsor toggle wiring"
```

---

### Task 3: Multi-profile `main()` with failure isolation

**Files:**
- Modify: `src/job_search_email/main.py` (add `PROFILES_DIR` constant, `discover_profiles`, `process_profile`; rewrite `main()`)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `run_pipeline(profile, output_dir)` (Task 2).
- Produces:
  - `PROFILES_DIR = ROOT / "profiles"` (module constant)
  - `discover_profiles(profiles_dir: Path = PROFILES_DIR) -> list[Path]` — sorted `*.yaml` paths
  - `process_profile(profile_path: Path) -> None` — load → pipeline → emails for one profile
  - `main() -> None` — loops all profiles; `SystemExit(1)` if none found or any failed, after attempting all.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
MINIMAL_PROFILE_TMPL = (
    "profile:\n  name: {name}\n  employment_type: [full-time]\n"
    "location: Bristol\nmin_salary: 60000\n"
)


def _setup_multi_profile_main(tmp_path, monkeypatch, profile_names):
    import sys, importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    for name in profile_names:
        (profiles_dir / f"{name}.yaml").write_text(
            MINIMAL_PROFILE_TMPL.format(name=name), encoding="utf-8")

    monkeypatch.setattr(main_mod, "ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(main_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")
    return main_mod


def _multi_profile_patches(fetch_side_effect):
    from job_search_email.models import SearchPlan
    dummy_plan = SearchPlan(
        profile_fingerprint="test", queries=["q"],
        exclusions={"roles": [], "employment_types": []},
        nhs_rules={}, evaluator_notes=[],
    )
    return (
        _patch("job_search_email.main.fetch_all_jobs", side_effect=fetch_side_effect),
        _patch("job_search_email.main.generate_search_plan", return_value=dummy_plan),
        _patch("job_search_email.main.classify_locations", return_value={"Bristol": "within"}),
        _patch("job_search_email.main.score_jobs", return_value=[]),
        _patch("job_search_email.main.build_email_html", return_value=("<html/>", 0)),
        _patch("job_search_email.main.send_email"),
    )


def test_discover_profiles_returns_sorted_yaml(tmp_path):
    from job_search_email.main import discover_profiles
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "zeta.yaml").write_text("x", encoding="utf-8")
    (profiles_dir / "alpha.yaml").write_text("x", encoding="utf-8")
    (profiles_dir / "notes.txt").write_text("x", encoding="utf-8")

    result = discover_profiles(profiles_dir)

    assert [p.name for p in result] == ["alpha.yaml", "zeta.yaml"]


def test_main_processes_all_profiles(tmp_path, monkeypatch):
    main_mod = _setup_multi_profile_main(tmp_path, monkeypatch, ["alice", "bob"])
    fetch, plan, classify, score, build, send = _multi_profile_patches([[], []])
    with fetch as mock_fetch, plan, classify, score, build, send as mock_send:
        main_mod.main()

    assert mock_fetch.call_count == 2
    assert mock_send.call_count == 2
    assert (tmp_path / "runs" / "alice" / "job_results.json").exists()
    assert (tmp_path / "runs" / "bob" / "job_results.json").exists()


def test_main_isolates_profile_failure(tmp_path, monkeypatch):
    import pytest
    main_mod = _setup_multi_profile_main(tmp_path, monkeypatch, ["alice", "bob"])
    # alice's fetch blows up; bob's succeeds
    fetch, plan, classify, score, build, send = _multi_profile_patches(
        [RuntimeError("scrape failed"), []])
    with fetch, plan, classify, score, build, send as mock_send:
        with pytest.raises(SystemExit) as excinfo:
            main_mod.main()

    assert excinfo.value.code == 1
    assert mock_send.call_count == 1  # bob's email still went out
    assert (tmp_path / "runs" / "bob" / "job_results.json").exists()


def test_main_exits_nonzero_when_no_profiles(tmp_path, monkeypatch):
    import pytest
    main_mod = _setup_multi_profile_main(tmp_path, monkeypatch, [])
    with pytest.raises(SystemExit) as excinfo:
        main_mod.main()
    assert excinfo.value.code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main.py -q -k "discover_profiles or processes_all or isolates or no_profiles"`
Expected: FAIL — `ImportError: cannot import name 'discover_profiles'`.

- [ ] **Step 3: Implement in main.py**

Add `import traceback` to the imports (line 1 area). Add after the constants:

```python
PROFILES_DIR = ROOT / "profiles"
```

Add `discover_profiles` and `process_profile`, and rewrite `main()` (the email-routing body of the old `main()` moves verbatim into `process_profile`):

```python
def discover_profiles(profiles_dir: Path = PROFILES_DIR) -> list[Path]:
    return sorted(profiles_dir.glob("*.yaml"))


def process_profile(profile_path: Path) -> None:
    profile = load_profile(profile_path)
    classification, scored = run_pipeline(profile, RUNS_DIR / profile_path.stem)

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


def main() -> None:
    profile_paths = discover_profiles()
    if not profile_paths:
        print(f"[main] no profiles found in {PROFILES_DIR}", file=sys.stderr)
        raise SystemExit(1)

    failed: list[str] = []
    for profile_path in profile_paths:
        print(f"\n=== Profile: {profile_path.stem} ===")
        try:
            process_profile(profile_path)
        except Exception:
            print(f"[main] profile {profile_path.name} failed:", file=sys.stderr)
            traceback.print_exc()
            failed.append(profile_path.name)

    if failed:
        print(f"[main] {len(failed)} profile(s) failed: {', '.join(failed)}", file=sys.stderr)
        raise SystemExit(1)
```

Delete the now-unused `PROFILE_PATH` **only if** nothing else imports it — `debug_run.py` still does; leave `PROFILE_PATH` in place (Task 4 renames it).

- [ ] **Step 4: Update the two old main()-level tests to the profiles dir**

`test_main_loads_and_saves_location_cache` and `_run_main_with_toggles` write `tmp_path / "profile.yaml"` and patch `PROFILE_PATH` — `main()` no longer reads either.

In `test_main_loads_and_saves_location_cache`, replace the profile-writing block with:

```python
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "test.yaml").write_text(
        "profile:\n  name: Test\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n",
        encoding="utf-8",
    )
```

and replace `monkeypatch.setattr(main_mod, "PROFILE_PATH", tmp_path / "profile.yaml")` with `monkeypatch.setattr(main_mod, "PROFILES_DIR", profiles_dir)`.

In `_run_main_with_toggles`, replace the profile-writing block with:

```python
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "test.yaml").write_text(
        "profile:\n  name: Test\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n"
        f"send_main_email: {'true' if send_main else 'false'}\n"
        f"send_debug_email: {'true' if send_debug else 'false'}\n",
        encoding="utf-8",
    )
```

and in its monkeypatch list replace `("PROFILE_PATH", tmp_path / "profile.yaml")` with `("PROFILES_DIR", profiles_dir)`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "feat: run pipeline for every profile in profiles/ with failure isolation"
```

---

### Task 4: Sponsor-gate fidelity in the explain-job trace

When a profile has `filter_sponsors: false`, `explain-job` must not report a sponsor rejection the real pipeline would never make.

**Files:**
- Modify: `src/job_search_email/filter_trace.py:22-30,72-78`
- Modify: `src/job_search_email/explain_job.py:69`
- Test: `tests/test_filter_trace.py`

**Interfaces:**
- Consumes: `profile.filter_sponsors` (Task 1).
- Produces: `run_filter_gates(..., sponsor_set: frozenset[str] | None, ...)` — when `None`, the "Sponsor list" gate passes with detail `"disabled (filter_sponsors=false)"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_filter_trace.py` (reuse that file's existing job/profile fixture helpers if present; otherwise this standalone version):

```python
def test_sponsor_gate_disabled_when_sponsor_set_none():
    from job_search_email.filter_trace import run_filter_gates
    from job_search_email.models import JobListing
    from profile_helpers import make_profile

    job = JobListing(
        title="Senior Software Engineer", company="Tiny Startup Ltd",
        location="Cardiff", salary_min=85000, description="React role",
        url="https://x.com/1", source="reed", employment_type="full-time",
    )
    profile = make_profile(filter_sponsors=False, min_salary=80000, location="Cardiff")

    gates = run_filter_gates(
        job, profile,
        location_verdict="within",
        sponsor_set=None,
        nhs_rules={},
        exclusion_roles=[],
    )

    sponsor_gate = next(g for g in gates if g.name == "Sponsor list")
    assert sponsor_gate.passed is True
    assert sponsor_gate.detail == "disabled (filter_sponsors=false)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_filter_trace.py::test_sponsor_gate_disabled_when_sponsor_set_none -q`
Expected: FAIL — `_check_sponsor` receives `None` and raises (`TypeError: argument of type 'NoneType' is not iterable`) or the detail assertion fails.

- [ ] **Step 3: Implement**

In `src/job_search_email/filter_trace.py`, change the signature (line 27):

```python
    sponsor_set: frozenset[str] | None,
```

and replace the sponsor gate block (lines 72-78) with:

```python
    sponsor = _check_sponsor(job, sponsor_set) if sponsor_set is not None else None
    if sponsor_set is None:
        sponsor_detail = "disabled (filter_sponsors=false)"
    elif sponsor is None:
        sponsor_detail = "n/a (NHS source)" if job.source == "nhs" else "on approved sponsor list"
    else:
        sponsor_detail = sponsor.reject_reason or ""
    gates.append(GateResult("Sponsor list", sponsor is None, sponsor_detail, False))
```

In `src/job_search_email/explain_job.py`, line 69 becomes:

```python
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH) if profile.filter_sponsors else None
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (existing sponsor-gate tests pass a real frozenset and keep their behaviour).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/filter_trace.py src/job_search_email/explain_job.py tests/test_filter_trace.py
git commit -m "feat: explain-job sponsor gate respects filter_sponsors toggle"
```

---

### Task 5: Move profile to `profiles/jie-zhou.yaml`, repoint tools, update docs

**Files:**
- Move: `profile.yaml` → `profiles/jie-zhou.yaml` (`git mv`)
- Modify: `src/job_search_email/main.py` (rename `PROFILE_PATH` → `DEFAULT_PROFILE_PATH = PROFILES_DIR / "jie-zhou.yaml"`)
- Modify: `src/job_search_email/debug_run.py:4,24-25`
- Modify: `src/job_search_email/local_run.py:70`
- Modify: `src/job_search_email/explain_job.py:35,38,95-96,101-102`
- Modify: `tests/test_local_testing.py:71-73,91-92`
- Modify: `.gitignore`
- Modify: `README.md`, `CLAUDE.md`

**Interfaces:**
- Produces: `DEFAULT_PROFILE_PATH: Path` in `main.py` (consumed by `debug_run.py`). `explain-job` defaults: `--profile profiles/jie-zhou.yaml`, `--run-data runs/jie-zhou/job_results.json`.

- [ ] **Step 1: Move the profile**

```bash
git mv profile.yaml profiles/jie-zhou.yaml
```

- [ ] **Step 2: Repoint code**

`src/job_search_email/main.py` — replace the `PROFILE_PATH` constant with:

```python
DEFAULT_PROFILE_PATH = PROFILES_DIR / "jie-zhou.yaml"
```

(`PROFILES_DIR` must be defined before it; move the constant below `PROFILES_DIR` if needed. `main()` no longer references it — only `debug_run` does.)

`src/job_search_email/debug_run.py`:

```python
from .main import DEFAULT_PROFILE_PATH, RUNS_DIR, run_pipeline
```

```python
    profile = load_profile(DEFAULT_PROFILE_PATH)
    classification, scored = run_pipeline(profile, RUNS_DIR / DEFAULT_PROFILE_PATH.stem)
```

`src/job_search_email/local_run.py` line 70:

```python
    profile = load_profile(root / "profiles" / "jie-zhou.yaml")
```

`src/job_search_email/explain_job.py` — the `explain()` keyword defaults (lines 35, 38):

```python
    profile_path: str = "profiles/jie-zhou.yaml",
```
```python
    run_data_path: str = "runs/jie-zhou/job_results.json",
```

and the argparse defaults/help (lines 95-96, 101-102):

```python
    parser.add_argument("--profile", default="profiles/jie-zhou.yaml",
                        help="Path to the profile YAML (default: profiles/jie-zhou.yaml).")
```
```python
    parser.add_argument("--run-data", default="runs/jie-zhou/job_results.json",
                        help="Path to a run's job_results.json (default: runs/jie-zhou/job_results.json).")
```

- [ ] **Step 3: Update tests that copy the root profile**

`tests/test_local_testing.py` — in both `test_local_run_writes_email_preview` and `test_local_run_writes_json_artefacts`, replace the copy lines with:

```python
    project_root = Path(__file__).parent.parent
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    shutil.copy(project_root / "profiles" / "jie-zhou.yaml", profiles_dir / "jie-zhou.yaml")
```

- [ ] **Step 4: gitignore**

Add to `.gitignore` (keep the existing root-artifact lines; they're harmless):

```
runs/
email_preview.html
```

- [ ] **Step 5: Update docs**

`README.md`:
- Line 7: `- loads user profiles from `profiles/*.yaml` — one email per profile, each to its own recipient`
- Line 49: `Just pass the URL. `profiles/jie-zhou.yaml` is used by default; pass `--profile profiles/<name>.yaml` for another profile.`
- Options table `--profile` row default: `profiles/jie-zhou.yaml`; add a `--run-data` row: default `runs/jie-zhou/job_results.json`, purpose "Local run data to resolve the job from (written by the pipeline under `runs/<profile>/`)."
- In "What it does", add a bullet: `- filters to UK licensed sponsor companies per profile (disable with `filter_sponsors: false` in that profile's YAML)`

`CLAUDE.md`:
- First paragraph: change "hard coded in the profile.yaml file" to "hard coded in per-person YAML files under `profiles/` (one email per profile per run)".
- Sponsor paragraph: append "Profiles that don't need visa sponsorship can set `filter_sponsors: false`."
- Debug-tools section: update `--run-data` default to `runs/<profile>/job_results.json` and note `--profile profiles/<name>.yaml` selects the person.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass. Also sanity-check the offline runner end-to-end: `python -m pytest tests/test_local_testing.py -q`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: move profile to profiles/jie-zhou.yaml and repoint debug tools + docs"
```

---

### Task 6: Add Marc's profile

**Files:**
- Create: `profiles/marc-brookes.yaml`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `load_profile` (existing), `discover_profiles` (Task 3) — no new code, just data + a repo-level validation test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_profile.py`:

```python
def test_all_repo_profiles_load_and_are_complete():
    from pathlib import Path
    profiles_dir = Path(__file__).parent.parent / "profiles"
    paths = sorted(profiles_dir.glob("*.yaml"))
    assert [p.name for p in paths] == ["jie-zhou.yaml", "marc-brookes.yaml"]
    for path in paths:
        profile = load_profile(path)
        assert profile.name, path.name
        assert profile.recipient_email, path.name
        assert profile.location, path.name
        assert profile.min_salary > 0, path.name
        assert profile.experience, path.name


def test_marc_profile_has_sponsor_filter_off():
    from pathlib import Path
    profile = load_profile(Path(__file__).parent.parent / "profiles" / "marc-brookes.yaml")
    assert profile.filter_sponsors is False
    assert profile.filter_recruitment is True
    assert profile.min_salary == 80000
```

(Match `tests/test_profile.py`'s existing import style for `load_profile`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile.py -q -k "repo_profiles or marc"`
Expected: FAIL — `marc-brookes.yaml` missing.

- [ ] **Step 3: Create `profiles/marc-brookes.yaml`**

Content transcribed verbatim from Marc's LinkedIn PDF export (provided in-session); search preferences per the spec:

```yaml
profile:
  name: Marc Brookes
  headline: "Senior Software Engineer at Siemens"
  about: |
    Skilled and experienced software developer with a wide variety of technologies. Worked on projects using C# and VB .net, Java, Javascript, Flex among other technologies. Competent with SQL database querying and maintenance. Throughout working with model based architectures has now picked up the knowledge and understanding required for using AI to build maintainable and fast software solutions.
    More recently I've specialized in front end development. Overseeing large scale projects in React and Angular whilst working on AI ready applications for Siemens.
  seniority: Senior
  industry: Software / Technology

  experience:
    - title: Senior Software Engineer
      company: Siemens Digital Industries Customer Service UK&I
      start: "2023-10"
      end: present
    - title: Software Engineer
      company: The Safeguarding Company
      location: Talbot Green
      start: "2020-01"
      end: "2023-10"
    - title: Software Developer
      company: Web.com
      location: Cardiff, United Kingdom
      start: "2017-06"
      end: "2020-01"
    - title: Team Lead
      company: WCBS
      location: Cardiff
      start: "2016-06"
      end: "2017-05"
    - title: Software Developer
      company: WCBS
      location: Cardiff
      start: "2015-10"
      end: "2017-05"
    - title: Software Engineer
      company: Accelero Digital
      location: Bridgend
      start: "2009-09"
      end: "2015-10"
      description: |
        Software Engineer for Accelero Digital Solutions. I was involved in a wide variety of projects including software development, database management, software deployment and customer support. I also worked closely with many of the customers and sub contractors in turning their varied and complex requirements into reliable and suitable software solutions.
    - title: Placement Student
      company: Tata Steel
      location: Llanwern
      start: "2007-09"
      end: "2008-09"
      description: |
        Spent an industrial placement year working for Corus (now Tata Steel) Strip Products in the Materials Management department in Llanwern. Spent the year in a programming and modelling role using Visual Basic behind Microsoft Excel and mathematical skills at an advanced level for the duration, developing analysis, monitoring and modelling tools to solve industrial problems.

  education:
    - institution: Cardiff University / Prifysgol Caerdydd
      degree: Master of Science (MSc), Computing
    - institution: Cardiff University / Prifysgol Caerdydd
      degree: Bachelor of Science (BSc), Applied Mathematics

  certifications: []

  # LinkedIn top-3 skills + skill-like terms from the summary/experience
  # (LinkedIn's PDF export only lists the top 3 skills)
  skills:
    - Web Services
    - Software Development
    - Software Engineering
    - C#
    - JavaScript
    - React
    - Angular
    - Java
    - SQL
    - Front-end Development
    - AI-assisted development

  languages:
    - English

  target_roles:
    - Senior Software Engineer
    - Frontend Developer
    - Full-stack Developer
  open_to:
    - Software Architect
    - Lead Developer
    - Technical Lead
  not_open_to:
    - graduate / junior roles
    - QA / test analyst
    - first-line support / helpdesk
  employment_type:
    - full-time

location: Cardiff
radius_miles: 40
min_salary: 80000

preamble: "Hey Marc, its The Job Mule 2.0. Lets go through todays jobs."
recipient_email: marc.j.brookes@gmail.com
send_main_email: true
send_debug_email: false
filter_recruitment: true
filter_sponsors: false
```

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: `python -m pytest tests/test_profile.py -q` then `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Smoke-test the offline pipeline against Marc's profile**

Run: `python -c "from pathlib import Path; from job_search_email.profile import load_profile, render_profile; print(render_profile(load_profile(Path('profiles/marc-brookes.yaml'))))"`
Expected: rendered block shows name, headline, current role "Senior Software Engineer at Siemens Digital Industries Customer Service UK&I", all 7 experience entries, both degrees, skills.

- [ ] **Step 6: Commit**

```bash
git add profiles/marc-brookes.yaml tests/test_profile.py
git commit -m "feat: add Marc Brookes profile (sponsor filter off, Cardiff, 80k floor)"
```
