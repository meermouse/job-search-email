# Remote Location Hubs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deliberate remote-only search of named location hubs (starting with London), fix the location-classifier foundation it depends on, and stop the sponsor gate from silently discarding confirmed-remote roles whose sponsor status only needs manual checking.

**Architecture:** The `include_remote` bool becomes a `remote: { uk_wide, hubs }` profile block. jobspy gains one remote-only search leg per hub. `JobListing` carries `search_legs` provenance that `deduplicate` unions on collision. `remote_filter` gains a `remote_with_travel` verdict. `filter.py` keeps confirmed-remote jobs whose sponsor is merely *unverifiable* (agency / sparse company string), flagging them `sponsor_unverified`. `email.py` splits its output into a main table plus "Remote — London" and "Remote — sponsor not verified" sections. The scorer and query generator are told the candidate wants remote work.

**Tech Stack:** Python 3.11, dataclasses, `anthropic` (Haiku via `SCORER_MODEL`), `python-jobspy`, Reed REST API, `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-06-london-remote-hubs-design.md`

## Global Constraints

- Python `>=3.11`. No new runtime dependencies.
- Run tests with the repo virtualenv: `.venv/Scripts/python.exe -m pytest ...` (Windows). Every task ends green on the files it touched; the full suite (`.venv/Scripts/python.exe -m pytest -q`) must pass before the final task's commit.
- No live network or LLM calls in tests — patch `job_search_email.<module>.client` / `scrape_jobs` / `requests`, or inject verdict dicts, exactly as the existing tests in that file do.
- Controlled `search_legs` vocabulary — use these exact strings: `jobspy:radius`, `jobspy:uk-remote`, `jobspy:hub:<hub>`, `reed:radius`, `reed:uk-remote`, `nhs:radius`.
- Remote-confirmation verdicts are exactly `remote`, `remote_with_travel`, `not_remote`; API failure yields `unverified` and is never written to the cache.
- Filter flags in play: `remote_confirmed`, `remote_with_travel`, `sponsor_unverified`, plus the existing `employment_type_unknown`.
- Commit after every task with the message shown in its final step. Conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- Do not restructure files beyond what a task specifies. Match surrounding code style (module-level `_CONSTANTS`, small pure `_helpers`, dataclasses).

---

## File Structure

**Modified — config & model**
- `src/job_search_email/models.py` — `Profile` gets `remote_uk_wide: bool`, `remote_hubs: list[str]`, an `include_remote` compatibility property (the plain field is removed); `JobListing` gets `search_legs: list[str]`.
- `src/job_search_email/profile.py` — parse the `remote:` block; hard-error on the legacy `include_remote:` key.
- `profiles/jie-zhou.yaml` — add `remote: { uk_wide: true, hubs: [London] }`.
- `tests/profile_helpers.py` — `make_profile` maps a legacy `include_remote=` kwarg to `remote_uk_wide=`.

**Modified — Tier 1 foundation**
- `src/job_search_email/location_filter.py` — batch `classify_locations` at 50; never cache a fallback verdict; new `normalise_location`.
- `src/job_search_email/main.py` — apply `normalise_location` when building `unique_locations`.
- `src/job_search_email/debug_run.py` — console/report writes survive non-cp1252 characters.

**Modified — Tier 2 hub search**
- `src/job_search_email/search_api/jobspy_searcher.py` — tag every leg; add one `jobspy:hub:<hub>` leg per configured hub.
- `src/job_search_email/search_api/reed.py` — tag `reed:radius` / `reed:uk-remote`.
- `src/job_search_email/search_api/nhs_jobs.py` — tag `nhs:radius`.
- `src/job_search_email/search_api/dedup.py` — union `search_legs` when a duplicate is dropped.

**Modified — Tier 3 gate & verdict**
- `src/job_search_email/remote_filter.py` — `remote_with_travel` verdict.
- `src/job_search_email/filter.py` — gate keeps `remote_with_travel`; sponsor/recruitment carve-out for confirmed-remote jobs.
- `src/job_search_email/filter_trace.py` — surface the new verdict and the `sponsor_unverified` disposition.

**Modified — email, scorer, queries, fixtures, docs**
- `src/job_search_email/email.py` — `job_hub` helper; three-group partition; per-verdict badges.
- `src/job_search_email/scorer.py` — remote-aware line in the system prompt.
- `src/job_search_email/queries.py` — remote-aware rule in the generation prompt.
- `src/job_search_email/fixtures.py` — hub job, `remote_with_travel` job, `sponsor_unverified` job, matching verdicts.
- `CLAUDE.md`, `src/job_search_email/search_api/CLAUDE.md` — document the `remote:` block, hub legs, and the sponsor-not-verified group.

**New test files**
- `tests/test_location_normalise.py`

---

## Task 1: `remote:` profile block replaces the `include_remote` bool

**Files:**
- Modify: `src/job_search_email/models.py` (`Profile` dataclass, ~line 24-47)
- Modify: `src/job_search_email/profile.py` (`load_profile`, ~line 54-80)
- Modify: `profiles/jie-zhou.yaml`
- Modify: `tests/profile_helpers.py`
- Modify: `tests/test_main.py` (replace the two `test_load_profile_include_remote_*` tests, ~line 439-452)
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Profile.remote_uk_wide: bool` (default `False`)
  - `Profile.remote_hubs: list[str]` (default `[]`)
  - `Profile.include_remote` — read-only `@property` returning `remote_uk_wide or bool(remote_hubs)`
  - `profile._parse_remote(data: dict) -> tuple[bool, list[str]]`
  - `make_profile(include_remote=True)` continues to work (maps to `remote_uk_wide=True`)

- [ ] **Step 1: Write failing tests in `tests/test_profile.py`**

Append:

```python
def test_remote_block_absent_defaults(tmp_path: Path):
    p = _write(tmp_path, FULL_YAML)
    profile = load_profile(p)
    assert profile.remote_uk_wide is False
    assert profile.remote_hubs == []
    assert profile.include_remote is False


def test_remote_block_uk_wide_and_hubs(tmp_path: Path):
    p = _write(tmp_path, FULL_YAML + "\nremote:\n  uk_wide: true\n  hubs: [London, Manchester]\n")
    profile = load_profile(p)
    assert profile.remote_uk_wide is True
    assert profile.remote_hubs == ["London", "Manchester"]
    assert profile.include_remote is True


def test_remote_block_hubs_only(tmp_path: Path):
    p = _write(tmp_path, FULL_YAML + "\nremote:\n  hubs: [London]\n")
    profile = load_profile(p)
    assert profile.remote_uk_wide is False
    assert profile.remote_hubs == ["London"]
    assert profile.include_remote is True


def test_legacy_include_remote_key_raises(tmp_path: Path):
    p = _write(tmp_path, FULL_YAML + "\ninclude_remote: true\n")
    with pytest.raises(ValueError, match="remote:"):
        load_profile(p)


def test_remote_hubs_must_be_strings(tmp_path: Path):
    p = _write(tmp_path, FULL_YAML + "\nremote:\n  hubs: [1, 2]\n")
    with pytest.raises(ValueError, match="hubs"):
        load_profile(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile.py -q -k "remote or legacy_include"`
Expected: FAIL — `AttributeError: 'Profile' object has no attribute 'remote_uk_wide'` / no `ValueError` raised.

- [ ] **Step 3: Update `Profile` in `models.py`**

Replace the line `    include_remote: bool = False` with:

```python
    remote_uk_wide: bool = False
    remote_hubs: list[str] = field(default_factory=list)
```

Add this property to the `Profile` class body (after the fields, before the class ends):

```python
    @property
    def include_remote(self) -> bool:
        """Compatibility shim: any remote search configured at all."""
        return self.remote_uk_wide or bool(self.remote_hubs)
```

`field` is already imported in `models.py`.

- [ ] **Step 4: Update `profile.py`**

Add near the other `_parse_*` helpers:

```python
def _parse_remote(data: dict) -> tuple[bool, list[str]]:
    """Parse the ``remote:`` block into (uk_wide, hubs).

    The legacy top-level ``include_remote:`` key is no longer accepted.
    """
    if "include_remote" in data:
        raise ValueError(
            "Profile key 'include_remote' is no longer supported. Use a "
            "'remote:' block instead:\n  remote:\n    uk_wide: true\n    hubs: [London]"
        )
    block = data.get("remote") or {}
    if not isinstance(block, dict):
        raise ValueError(f"Profile 'remote' must be a mapping, got {type(block).__name__}")
    uk_wide = bool(block.get("uk_wide", False))
    hubs_raw = block.get("hubs") or []
    if not isinstance(hubs_raw, list) or any(
        not isinstance(h, str) or not h.strip() for h in hubs_raw
    ):
        raise ValueError("Profile 'remote.hubs' must be a list of non-empty strings")
    return uk_wide, [h.strip() for h in hubs_raw]
```

In `load_profile`, remove the line `        include_remote=data.get("include_remote", False),` and add, before the `return Profile(`:

```python
    remote_uk_wide, remote_hubs = _parse_remote(data)
```

Then in the `Profile(...)` constructor call, replace nothing/add:

```python
        remote_uk_wide=remote_uk_wide,
        remote_hubs=remote_hubs,
```

- [ ] **Step 5: Update `tests/profile_helpers.py`**

Replace the body of `make_profile` with:

```python
def make_profile(**overrides) -> Profile:
    kwargs = dict(
        name="Test",
        about="",
        seniority="Senior",
        industry="NHS",
        skills=[],
        target_roles=[],
        open_to=[],
        not_open_to=[],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )
    # Back-compat: tests written against the old bool.
    if "include_remote" in overrides:
        overrides.setdefault("remote_uk_wide", overrides.pop("include_remote"))
    kwargs.update(overrides)
    return Profile(**kwargs)
```

- [ ] **Step 6: Replace the two obsolete tests in `tests/test_main.py`**

Delete `test_load_profile_include_remote_defaults_false` and `test_load_profile_include_remote_reads_true` (~line 439-452) and put in their place:

```python
def test_load_profile_remote_defaults_absent(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.remote_uk_wide is False
    assert profile.remote_hubs == []
    assert profile.include_remote is False


def test_load_profile_remote_block_read(tmp_path: Path) -> None:
    yaml_with_block = PROFILE_YAML + "remote:\n  uk_wide: true\n  hubs: [London]\n"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml_with_block, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.remote_uk_wide is True
    assert profile.remote_hubs == ["London"]


def test_load_profile_legacy_include_remote_key_raises(tmp_path: Path) -> None:
    yaml_with_flag = PROFILE_YAML + "include_remote: true\n"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml_with_flag, encoding="utf-8")
    with pytest.raises(ValueError, match="remote:"):
        load_profile(path=profile_path)
```

`pytest` is already imported in `tests/test_main.py`; if not, add `import pytest` at the top.

- [ ] **Step 7: Add the block to `profiles/jie-zhou.yaml`**

After the `filter_recruitment: true` line (and before the `email_frequency` comment/line), add:

```yaml
remote:
  uk_wide: true
  hubs: [London]
```

- [ ] **Step 8: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile.py tests/test_main.py -q`
Expected: PASS.

- [ ] **Step 9: Run the full suite (catches other `include_remote` call-sites)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. The `include_remote` property keeps `main.py`, `explain_job.py`, `jobspy_searcher.py`, `reed.py` working unchanged.

- [ ] **Step 10: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/profile.py profiles/jie-zhou.yaml tests/profile_helpers.py tests/test_profile.py tests/test_main.py
git commit -m "feat: replace include_remote bool with a remote: { uk_wide, hubs } profile block"
```

---

## Task 2: `JobListing.search_legs` provenance + dedup leg-union

**Files:**
- Modify: `src/job_search_email/models.py` (`JobListing` dataclass, ~line 60-70)
- Modify: `src/job_search_email/search_api/jobspy_searcher.py` (`search`, ~line 20-58)
- Modify: `src/job_search_email/search_api/reed.py` (`_fetch`, `search`, `_to_listing`)
- Modify: `src/job_search_email/search_api/nhs_jobs.py` (`search`, listing construction ~line 40-48)
- Modify: `src/job_search_email/search_api/dedup.py`
- Test: `tests/test_job_listing.py`, `tests/search_api/test_dedup.py`, `tests/search_api/test_jobspy_searcher.py`, `tests/search_api/test_reed.py`, `tests/search_api/test_nhs_jobs.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `JobListing.search_legs: list[str]` (default `[]`, `field(default_factory=list)`)
  - Every searcher sets `search_legs=[<leg>]` on listings it creates, using the vocabulary in Global Constraints. jobspy uses `jobspy:radius` / `jobspy:uk-remote` here (hub leg added in Task 3).
  - `deduplicate` preserves first-seen job but merges dropped duplicates' `search_legs` into it (order-preserving union).

- [ ] **Step 1: Write failing tests**

`tests/test_job_listing.py` — append:

```python
def test_job_listing_search_legs_defaults_empty():
    from job_search_email.models import JobListing
    j = JobListing(title="t", company="c", location="l", salary_min=None,
                   description="", url="u", source="reed", employment_type=None)
    assert j.search_legs == []
```

`tests/search_api/test_dedup.py` — append:

```python
def test_duplicate_merges_search_legs():
    jobs = [
        _job(title="Manager", company="NHS", search_legs=["jobspy:radius"]),
        _job(title="Manager", company="NHS", search_legs=["jobspy:uk-remote"]),
        _job(title="Manager", company="NHS", search_legs=["jobspy:uk-remote"]),
    ]
    result = deduplicate(jobs)
    assert len(result) == 1
    assert result[0].search_legs == ["jobspy:radius", "jobspy:uk-remote"]
```

`tests/search_api/test_jobspy_searcher.py` — append (near the other remote-leg tests):

```python
def test_search_tags_legs_radius_and_uk_wide():
    row = {"title": "M", "company": "C", "location": "London", "job_url": "u",
           "site": "linkedin", "job_type": "fulltime", "min_amount": 90000}
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame([row])) as mock_scrape:
        results = search("manager", REMOTE_PROFILE)
    legs = {leg for r in results for leg in r.search_legs}
    assert "jobspy:radius" in legs
    assert "jobspy:uk-remote" in legs
```

`tests/search_api/test_reed.py` — append:

```python
def test_reed_tags_radius_leg():
    with patch("job_search_email.search_api.reed.requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"results": [
            {"jobTitle": "M", "employerName": "C", "locationName": "Bristol",
             "minimumSalary": 65000, "jobDescription": "d", "jobUrl": "u",
             "fullTime": True}
        ]}
        mock_get.return_value.raise_for_status = lambda: None
        results = search("manager", PROFILE)
    assert results and results[0].search_legs == ["reed:radius"]
```

`tests/search_api/test_nhs_jobs.py` — append a check that returned listings carry `search_legs == ["nhs:radius"]` (mirror the file's existing HTML-fixture test; if the file has no parsing test, add `assert all(j.search_legs == ["nhs:radius"] for j in results)` to the closest existing success test).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_listing.py tests/search_api/test_dedup.py tests/search_api/test_jobspy_searcher.py tests/search_api/test_reed.py tests/search_api/test_nhs_jobs.py -q`
Expected: FAIL — `search_legs` attribute / merge behaviour missing.

- [ ] **Step 3: Add the field in `models.py`**

In `JobListing`, after `posted_by_agency: bool | None = None` add:

```python
    search_legs: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Tag legs in `jobspy_searcher.py`**

Change `frames` to carry the leg name and thread it into `JobListing`:

```python
def search(query: str, profile: Profile) -> list[JobListing]:
    frames: list[tuple[str, object]] = [("jobspy:radius", scrape_jobs(
        site_name=["linkedin", "indeed"],
        search_term=query,
        location=profile.location,
        distance=50,
        results_wanted=50,
        country_indeed="UK",
    ))]

    if profile.remote_uk_wide:
        try:
            frames.append(("jobspy:uk-remote", scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location="United Kingdom",
                is_remote=True,
                results_wanted=50,
                country_indeed="UK",
            )))
        except Exception as exc:
            print(f"[jobspy_searcher] remote leg failed for {query!r}: {exc}", file=sys.stderr)

    results = []
    for leg, df in frames:
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
                search_legs=[leg],
            ))
    return results
```

Note the `if profile.include_remote:` guard becomes `if profile.remote_uk_wide:` — the UK-wide leg is now gated on that specific field, not the umbrella property.

- [ ] **Step 5: Tag legs in `reed.py`**

Give `_fetch` a `leg` parameter and pass it to `_to_listing`:

```python
def _fetch(params: dict, api_key: str, leg: str) -> list[JobListing]:
    response = requests.get(_REED_URL, params=params, auth=(api_key, ""), timeout=30)
    response.raise_for_status()
    return [_to_listing(item, leg) for item in response.json().get("results", [])]
```

In `search`, pass `"reed:radius"` to the first `_fetch`, and change the `if profile.include_remote:` guard to `if profile.remote_uk_wide:` with `"reed:uk-remote"` on that call.

In `_to_listing`, add `leg: str = ""` parameter and `search_legs=[leg] if leg else []` in the `JobListing(...)`.

- [ ] **Step 6: Tag the leg in `nhs_jobs.py`**

In the `JobListing(...)` built inside `search`, add `search_legs=["nhs:radius"]`.

- [ ] **Step 7: Union legs in `dedup.py`**

```python
from ..models import JobListing


def deduplicate(jobs: list[JobListing]) -> list[JobListing]:
    seen: dict[tuple[str, str], JobListing] = {}
    result: list[JobListing] = []
    for job in jobs:
        key = (job.title.lower().strip(), job.company.lower().strip())
        kept = seen.get(key)
        if kept is None:
            seen[key] = job
            result.append(job)
            continue
        for leg in job.search_legs:
            if leg not in kept.search_legs:
                kept.search_legs.append(leg)
    return result
```

- [ ] **Step 8: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_listing.py tests/search_api/ -q`
Expected: PASS. If an existing jobspy/reed test asserted `call_count`/kwargs and now sees `remote_uk_wide` instead of `include_remote`, it still passes because `make_profile(include_remote=True)` maps to `remote_uk_wide=True` (Task 1).

- [ ] **Step 9: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/search_api/ tests/test_job_listing.py tests/search_api/
git commit -m "feat: track search_legs provenance on JobListing and union them on dedup"
```

---

## Task 3: jobspy London hub search legs

**Files:**
- Modify: `src/job_search_email/search_api/jobspy_searcher.py` (`search`)
- Test: `tests/search_api/test_jobspy_searcher.py`

**Interfaces:**
- Consumes: `Profile.remote_hubs` (Task 1); `JobListing.search_legs` (Task 2).
- Produces: for each `hub` in `profile.remote_hubs`, one `scrape_jobs(location=hub, is_remote=True, ...)` leg whose listings carry `search_legs=["jobspy:hub:<hub>"]`. A hub-leg exception is caught and logged; it never drops the radius/UK-wide results.

- [ ] **Step 1: Write failing tests in `tests/search_api/test_jobspy_searcher.py`**

```python
HUB_PROFILE = make_profile(name="Jie", remote_hubs=["London"])


def test_search_adds_one_hub_leg_per_hub():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame()) as mock_scrape:
        search("manager", make_profile(name="Jie", remote_uk_wide=True, remote_hubs=["London", "Leeds"]))
    # radius + uk-wide + 2 hubs
    assert mock_scrape.call_count == 4
    hub_calls = [c.kwargs for c in mock_scrape.call_args_list if c.kwargs.get("is_remote") and c.kwargs.get("location") in ("London", "Leeds")]
    assert {c["location"] for c in hub_calls} == {"London", "Leeds"}
    assert all(c["is_remote"] is True and "distance" not in c for c in hub_calls)


def test_hub_leg_tags_search_legs():
    row = {"title": "M", "company": "C", "location": "London", "job_url": "u",
           "site": "linkedin", "job_type": "fulltime", "min_amount": 90000}
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame([row])):
        results = search("manager", HUB_PROFILE)
    assert any(r.search_legs == ["jobspy:hub:London"] for r in results)


def test_hub_leg_failure_keeps_radius_results():
    radius_df = pd.DataFrame([{"title": "R", "company": "C", "location": "Bristol",
                               "job_url": "u", "site": "linkedin", "job_type": "fulltime",
                               "min_amount": 90000}])

    def flaky(*args, **kwargs):
        if kwargs.get("location") == "London":
            raise RuntimeError("hub boom")
        return radius_df

    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs", side_effect=flaky):
        results = search("manager", HUB_PROFILE)
    assert [r.title for r in results] == ["R"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/search_api/test_jobspy_searcher.py -q -k hub`
Expected: FAIL — only 1-2 `scrape_jobs` calls; no `jobspy:hub:London` leg.

- [ ] **Step 3: Add the hub legs in `jobspy_searcher.py`**

After the `remote_uk_wide` block, before the `results = []` line:

```python
    for hub in profile.remote_hubs:
        try:
            frames.append((f"jobspy:hub:{hub}", scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location=hub,
                is_remote=True,
                results_wanted=50,
                country_indeed="UK",
            )))
        except Exception as exc:
            print(f"[jobspy_searcher] hub leg {hub!r} failed for {query!r}: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/search_api/test_jobspy_searcher.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/search_api/jobspy_searcher.py tests/search_api/test_jobspy_searcher.py
git commit -m "feat: add one jobspy remote-only search leg per configured hub"
```

---

## Task 4: batch `classify_locations`, never cache fallback verdicts

**Files:**
- Modify: `src/job_search_email/location_filter.py` (`classify_locations`, ~line 39-90)
- Test: `tests/test_location_filter.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `classify_locations` unchanged signature/return. New module constant `_BATCH_SIZE = 50`. On a batch's API error or a missing/invalid verdict, the location resolves to `"uncertain"` for that run **and is not written to `cache`**. Verdicts the model returned are still cached.

- [ ] **Step 1: Write failing tests in `tests/test_location_filter.py`**

```python
def test_classify_locations_batches_at_50():
    locs = [f"Place {i}, PL{i}" for i in range(120)]
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response(
            {loc: "uncertain" for loc in locs}
        )
        classify_locations(locs, home="Bristol", radius_miles=40, cache={})
    assert mock_client.messages.create.call_count == 3  # 50 + 50 + 20


def test_classify_locations_does_not_cache_on_api_failure():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.side_effect = RuntimeError("boom")
        result = classify_locations(["Nowhere, NW1"], home="Bristol", radius_miles=40, cache=cache)
    assert result["Nowhere, NW1"] == "uncertain"
    assert cache == {}  # transient fallback is not persisted


def test_classify_locations_does_not_cache_missing_verdict():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"A, A1": "within"})
        result = classify_locations(["A, A1", "B, B1"], home="Bristol", radius_miles=40, cache=cache)
    assert result["B, B1"] == "uncertain"
    assert "Bristol:40:B, B1" not in cache
    assert cache["Bristol:40:A, A1"] == "within"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_location_filter.py -q -k "batches or does_not_cache"`
Expected: FAIL — one call not three; `cache` populated with `"uncertain"` on failure.

- [ ] **Step 3: Rewrite the body of `classify_locations`**

Keep the cache-hit loop that fills `result` and `to_classify`. Replace the single-call block with:

```python
    _BATCH_SIZE = 50  # module-level constant is fine too; keep near the others

    for start in range(0, len(to_classify), _BATCH_SIZE):
        batch = to_classify[start:start + _BATCH_SIZE]
        try:
            user_message = (
                f"Home location: {home}. Radius: {radius_miles} miles.\n"
                f"Classify these locations:\n{json.dumps(batch, ensure_ascii=False)}"
            )
            response = client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text if response.content else ""
            raw = _extract_json_object(text)
            if not isinstance(raw, dict):
                raise ValueError(f"expected dict, got {type(raw).__name__}")
            verdicts: dict[str, str] = raw
        except Exception as exc:
            print(f"[location_filter] classify call failed: {exc}", file=sys.stderr)
            verdicts = {}

        for loc in batch:
            verdict = verdicts.get(loc)
            if verdict not in ("within", "outside", "uncertain"):
                # No usable verdict — resolve transiently, do NOT cache, so the
                # next run retries (mirrors remote_filter's "unverified").
                result[loc] = "uncertain"
                continue
            result[loc] = verdict
            cache[_cache_key(home, radius_miles, loc)] = verdict

    return result
```

Move `_BATCH_SIZE = 50` to a module-level constant alongside `_MODEL` if the surrounding style prefers that (it does — match `remote_filter._BATCH_SIZE`).

- [ ] **Step 4: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_location_filter.py -q`
Expected: PASS (existing single-batch tests still pass — one batch of ≤50 = one call).

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/location_filter.py tests/test_location_filter.py
git commit -m "fix: batch classify_locations at 50 and stop caching fallback verdicts"
```

---

## Task 5: `normalise_location` — London postcode → "London"

**Files:**
- Modify: `src/job_search_email/location_filter.py` (new helper near the top)
- Modify: `src/job_search_email/main.py` (`run_pipeline`, ~line 188-190 where `unique_locations` is built)
- Create: `tests/test_location_normalise.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `location_filter.normalise_location(raw: str) -> str`. London outward areas `EC WC E N NW SE SW W` (matched against the parsed outward code, not substring) → `"London"`. Other bare postcodes and all non-postcode strings → returned unchanged (whitespace-collapsed).

- [ ] **Step 1: Write failing tests in `tests/test_location_normalise.py`**

```python
import pytest
from job_search_email.location_filter import normalise_location


@pytest.mark.parametrize("raw", [
    "EC3A 5AT", "EC3A5AT", "WC2A3LH", "E20 1JN", "N1 9GU", "NW1 6XE",
    "SE1 7PB", "SW1A 1AA", "W1D 3QU", "ec1a 1bb",
])
def test_london_postcodes_map_to_london(raw):
    assert normalise_location(raw) == "London"


@pytest.mark.parametrize("raw", [
    "EN1 1AA", "SL1 2AB", "SG1 3CD", "WD17 1EF", "SM1 4GH", "RG1 1AA", "OX1 1AA",
])
def test_home_counties_postcodes_unchanged(raw):
    assert normalise_location(raw) == raw.strip()


@pytest.mark.parametrize("raw", [
    "London, England, UK", "Bristol", "Greater London, England, UK", "",
])
def test_non_postcodes_unchanged(raw):
    assert normalise_location(raw) == raw.strip()


def test_whitespace_collapsed():
    assert normalise_location("  London,   England  ") == "London, England"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_location_normalise.py -q`
Expected: FAIL — `ImportError: cannot import name 'normalise_location'`.

- [ ] **Step 3: Implement `normalise_location` in `location_filter.py`**

Add near the top (after imports, before `classify_locations`):

```python
import re

_LONDON_OUTWARD_AREAS = frozenset({"EC", "WC", "E", "N", "NW", "SE", "SW", "W"})
_UK_POSTCODE_RE = re.compile(
    r"^([A-Z]{1,2})(\d[A-Z\d]?)\s*(\d[A-Z]{2})?$", re.IGNORECASE
)


def normalise_location(raw: str) -> str:
    """Collapse whitespace; map bare London postcodes to ``"London"``.

    Non-London postcodes and any non-postcode string are returned unchanged
    (aside from whitespace normalisation).
    """
    cleaned = " ".join((raw or "").split())
    m = _UK_POSTCODE_RE.match(cleaned)
    if not m:
        return cleaned
    area = m.group(1).upper()
    if area in _LONDON_OUTWARD_AREAS:
        return "London"
    return cleaned
```

`re` may already be unused-imported elsewhere; add the import if missing.

- [ ] **Step 4: Wire into `main.py`**

In `run_pipeline`, the line that builds `unique_locations` currently reads:

```python
    unique_locations = list({j.location for j in jobs if j.location})
```

Change to:

```python
    from .location_filter import normalise_location
    unique_locations = list({normalise_location(j.location) for j in jobs if j.location})
```

(Prefer adding `normalise_location` to the existing `from .location_filter import ...` line at the top of `main.py` rather than a local import — match the file's style.)

- [ ] **Step 5: Run affected tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_location_normalise.py tests/test_main.py -q`
Then: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/location_filter.py src/job_search_email/main.py tests/test_location_normalise.py
git commit -m "feat: normalise London postcodes to London before location classification"
```

---

## Task 6: `job-search-debug` survives non-cp1252 characters

**Files:**
- Modify: `src/job_search_email/debug_run.py` (`_print_decisions`, `main`)
- Test: `tests/test_debug_run.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_print_decisions` never raises `UnicodeEncodeError`; the debug report is written UTF-8 (already is). New helper `debug_run._safe(text: str) -> str`.

- [ ] **Step 1: Write a failing test in `tests/test_debug_run.py`**

```python
def test_print_decisions_handles_narrow_nbsp(capsys):
    from job_search_email.debug_run import _print_decisions
    from job_search_email.models import JobListing, JobAnalysis, ScoredResult
    job = JobListing(title="Programme Lead PMO", company="X", location="London",
                     salary_min=None, description="", url="u", source="reed",
                     employment_type=None)
    scored = [ScoredResult(job=job, flags=[], rejected=False, reject_reason=None,
                           analysis=JobAnalysis(score=7, matched_skills=[], missing_essentials=[],
                                                employment_type_note="", verdict="ok"))]
    _print_decisions(scored)  # must not raise
    assert "Programme Lead" in capsys.readouterr().out
```

If the existing suite's console is already UTF-8 and cannot reproduce the crash, still add the test — it documents intent and passes trivially after the fix — and additionally assert the helper directly:

```python
def test_safe_replaces_unencodable(monkeypatch):
    import job_search_email.debug_run as dr
    assert dr._safe("a b")  # returns a string, no raise
```

- [ ] **Step 2: Run to verify current behaviour**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debug_run.py -q -k "narrow_nbsp or safe"`
Expected: FAIL (`_safe` undefined; on a cp1252 console the print test raises).

- [ ] **Step 3: Add the helper and use it in `debug_run.py`**

```python
import sys


def _safe(text: str) -> str:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(enc, "replace").decode(enc, "replace")
```

In `_print_decisions`, wrap every interpolated job field: `f"  [keep] {score:>3}  {_safe(r.job.title)} — {_safe(r.job.company)}"` and likewise for the `[drop]` line and its `reject_reason`.

`DEBUG_REPORT_PATH.write_text(html, encoding="utf-8")` in `main` already specifies UTF-8 — leave it, but confirm the argument is present.

- [ ] **Step 4: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debug_run.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/debug_run.py tests/test_debug_run.py
git commit -m "fix: debug run tolerates job titles with non-console characters"
```

---

## Task 7: `remote_with_travel` verdict in `remote_filter`

**Files:**
- Modify: `src/job_search_email/remote_filter.py` (`_SYSTEM_PROMPT`, `classify_remote`)
- Test: `tests/test_remote_filter.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `classify_remote` may now return `remote_with_travel` for a URL. Accepted/cached values: `remote`, `remote_with_travel`, `not_remote`. Any other model output still collapses to `not_remote`. API failure still yields `unverified`, still never cached.

- [ ] **Step 1: Write failing tests in `tests/test_remote_filter.py`**

```python
def test_classify_remote_accepts_remote_with_travel():
    jobs = [make_job("https://x.com/1", description="Remote-first with regular travel to client sites.")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "remote_with_travel"})
        result = classify_remote(jobs, cache=cache)
    assert result["https://x.com/1"] == "remote_with_travel"
    assert cache["https://x.com/1"] == "remote_with_travel"


def test_classify_remote_unknown_verdict_falls_back_to_not_remote():
    jobs = [make_job("https://x.com/9")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "maybe"})
        result = classify_remote(jobs, cache={})
    assert result["https://x.com/9"] == "not_remote"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_remote_filter.py -q -k "with_travel or unknown_verdict"`
Expected: FAIL — `remote_with_travel` collapses to `not_remote` under the current `if verdict not in ("remote", "not_remote")` check.

- [ ] **Step 3: Update `remote_filter.py`**

In `_SYSTEM_PROMPT`, add a third bullet between the `remote` and `not_remote` bullets:

```
- "remote_with_travel": the posting confirms remote-first / home-based working
  but names recurring travel to client sites, regional offices, or customer
  locations as a routine expectation (not just occasional team days).
```

Update the trailing instruction so it lists all three verdicts.

In `classify_remote`, change the guard:

```python
            verdict = verdicts.get(str(i))
            if verdict not in ("remote", "remote_with_travel", "not_remote"):
                verdict = "not_remote"
            result[job.url] = verdict
            cache[job.url] = verdict
```

- [ ] **Step 4: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_remote_filter.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/remote_filter.py tests/test_remote_filter.py
git commit -m "feat: add remote_with_travel verdict to remote_filter"
```

---

## Task 8: filter gate keeps `remote_with_travel`

**Files:**
- Modify: `src/job_search_email/filter.py` (`_check_location`, ~line 162-198; module constants ~line 32)
- Modify: `src/job_search_email/filter_trace.py` (`run_filter_gates` location detail)
- Test: `tests/test_filter.py`, `tests/test_filter_trace.py`

**Interfaces:**
- Consumes: `remote_with_travel` verdict strings (Task 7) passed via the `remote_verdicts` dict.
- Produces: `_check_location` returns a non-rejected `FilteredResult` with flag `_REMOTE_WITH_TRAVEL_FLAG = "remote_with_travel"` when the verdict is `remote_with_travel`; `remote` still yields `_REMOTE_CONFIRMED_FLAG = "remote_confirmed"`. New module constant `_REMOTE_WITH_TRAVEL_FLAG`.

- [ ] **Step 1: Write failing tests**

`tests/test_filter.py` — in the remote-gate section (after line 735):

```python
def test_remote_with_travel_is_kept_with_flag():
    from job_search_email.filter import _check_location
    job = make_job(url="https://x/1", location="London")
    res = _check_location(job, frozenset(), frozenset(), {"https://x/1": "remote_with_travel"})
    assert res is not None and res.rejected is False
    assert "remote_with_travel" in res.flags


def test_not_remote_still_rejected_under_gate():
    from job_search_email.filter import _check_location
    job = make_job(url="https://x/2", location="London")
    res = _check_location(job, frozenset(), frozenset(), {"https://x/2": "not_remote"})
    assert res is not None and res.rejected is True
```

`tests/test_filter_trace.py` — add:

```python
def test_trace_location_detail_for_remote_with_travel():
    from job_search_email.filter_trace import run_filter_gates
    job = make_job(url="https://x/3", location="London")  # use this file's job helper
    gates = run_filter_gates(
        job, make_profile(remote_hubs=["London"]),
        location_verdict="uncertain", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[], remote_verdict="remote_with_travel",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is True
    assert "travel" in loc.detail.lower()
```

(Match the job/profile helpers already used in `tests/test_filter_trace.py`.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_filter.py tests/test_filter_trace.py -q -k "remote_with_travel or not_remote_still"`
Expected: FAIL — `remote_with_travel` currently hits the reject branch.

- [ ] **Step 3: Update `filter.py`**

Add beside `_REMOTE_CONFIRMED_FLAG`:

```python
_REMOTE_WITH_TRAVEL_FLAG = "remote_with_travel"
```

In `_check_location`, in the remote-gate branch, after the `within_locations` early-return and before the current `verdict == "remote"` check:

```python
    verdict = remote_verdicts.get(job.url, "unverified")
    if verdict == "remote":
        return FilteredResult(
            job=job, flags=[_REMOTE_CONFIRMED_FLAG], rejected=False, reject_reason=None,
        )
    if verdict == "remote_with_travel":
        return FilteredResult(
            job=job, flags=[_REMOTE_WITH_TRAVEL_FLAG], rejected=False, reject_reason=None,
        )
```

Leave the rest (`unverified` / outside / uncertain → rejected) unchanged.

- [ ] **Step 4: Update `filter_trace.py`**

In `run_filter_gates`, the location-detail branch currently checks `"remote_confirmed" in loc.flags`. Broaden it:

```python
    if loc is not None and loc.rejected:
        loc_detail = loc.reject_reason or ""
    elif loc is not None and "remote_confirmed" in loc.flags:
        loc_detail = f"{location_verdict} radius, confirmed fully remote ({job.location or 'not stated'})"
    elif loc is not None and "remote_with_travel" in loc.flags:
        loc_detail = f"{location_verdict} radius, remote with regular travel ({job.location or 'not stated'})"
    else:
        loc_detail = f"{location_verdict} radius ({job.location or 'not stated'})"
```

- [ ] **Step 5: Run the affected tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_filter.py tests/test_filter_trace.py -q`
Then: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/filter.py src/job_search_email/filter_trace.py tests/test_filter.py tests/test_filter_trace.py
git commit -m "feat: keep remote_with_travel jobs at the location gate"
```

---

## Task 9: sponsor / recruitment carve-out for confirmed-remote jobs

**Files:**
- Modify: `src/job_search_email/filter.py` (`_check_recruitment`, `_check_sponsor`, `filter_jobs`)
- Modify: `src/job_search_email/filter_trace.py` (`run_filter_gates` — sponsor gate detail)
- Test: `tests/test_filter.py`, `tests/test_filter_trace.py`

**Interfaces:**
- Consumes: the `remote_confirmed` / `remote_with_travel` flags produced by `_check_location` (Task 8).
- Produces:
  - `_check_recruitment(job, recruitment_set, remote_ok: bool = False)` — when `remote_ok`, a would-be `_RECRUITMENT_REASON` rejection becomes a kept `FilteredResult` with `flags=["sponsor_unverified"]`.
  - `_check_sponsor(job, sponsor_set, remote_ok: bool = False)` — when `remote_ok`, the *"company not specified — cannot verify approved sponsor"* branch becomes a kept `FilteredResult` with `flags=["sponsor_unverified"]`. The *"company not on approved sponsor list"* branch is unchanged (still a hard reject).
  - `filter_jobs` computes `remote_ok = bool({"remote_confirmed", "remote_with_travel"} & set(loc_flags))` and passes it to both checks. `sponsor_unverified` is merged into the final kept result's flags.
  - Non-remote jobs (`remote_ok` False, incl. every job when the profile has no `remote:` block) are filtered exactly as before.

- [ ] **Step 1: Write failing tests in `tests/test_filter.py`**

```python
def test_confirmed_remote_agency_job_kept_as_sponsor_unverified():
    from job_search_email.filter import _check_recruitment
    job = make_job(company="Hays", posted_by_agency=True)
    res = _check_recruitment(job, frozenset({"hays"}), remote_ok=True)
    assert res is not None and res.rejected is False
    assert res.flags == ["sponsor_unverified"]


def test_agency_job_without_remote_ok_still_rejected():
    from job_search_email.filter import _check_recruitment
    job = make_job(company="Hays", posted_by_agency=True)
    res = _check_recruitment(job, frozenset({"hays"}), remote_ok=False)
    assert res is not None and res.rejected is True


def test_confirmed_remote_sparse_company_kept_as_sponsor_unverified():
    from job_search_email.filter import _check_sponsor
    job = make_job(company="Reed")  # too short/one word -> "not specified" branch
    res = _check_sponsor(job, frozenset(), remote_ok=True)
    assert res is not None and res.rejected is False
    assert res.flags == ["sponsor_unverified"]


def test_confirmed_remote_named_non_sponsor_still_rejected():
    from job_search_email.filter import _check_sponsor
    job = make_job(company="Definitely Not A Sponsor Ltd")
    res = _check_sponsor(job, frozenset(), remote_ok=True)
    assert res is not None and res.rejected is True
    assert "not on approved sponsor list" in res.reject_reason


def test_filter_jobs_end_to_end_sponsor_unverified_flag():
    # A confirmed-remote, agency-posted job survives filter_jobs with the flag.
    job = make_job(company="Michael Page", location="London", posted_by_agency=True,
                   url="https://x/rm1", salary_min=90000, employment_type="permanent")
    plan = SearchPlan(profile_fingerprint="", queries=[], exclusions={"roles": []},
                      nhs_rules={}, evaluator_notes=[])
    out = filter_jobs(
        [job], plan, make_profile(remote_hubs=["London"]),
        recruitment_set=frozenset(),
        sponsor_set=frozenset(),
        within_locations=frozenset(),
        remote_verdicts={"https://x/rm1": "remote"},
    )
    assert len(out) == 1 and out[0].rejected is False
    assert "sponsor_unverified" in out[0].flags
    assert "remote_confirmed" in out[0].flags
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_filter.py -q -k "sponsor_unverified or agency_job_without or named_non_sponsor"`
Expected: FAIL — `_check_recruitment` / `_check_sponsor` take no `remote_ok`; jobs are rejected.

- [ ] **Step 3: Update `_check_recruitment` in `filter.py`**

```python
def _check_recruitment(
    job: JobListing, recruitment_set: frozenset[str], remote_ok: bool = False
) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    def _result() -> FilteredResult:
        if remote_ok:
            return FilteredResult(job=job, flags=["sponsor_unverified"], rejected=False, reject_reason=None)
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=_RECRUITMENT_REASON)

    if job.posted_by_agency:
        return _result()

    normalized = _normalize_company(job.company or "")
    if not normalized:
        return None

    for candidate in _build_entries(normalized):
        if candidate in recruitment_set:
            return _result()

    return None
```

- [ ] **Step 4: Update `_check_sponsor` in `filter.py`**

```python
def _check_sponsor(
    job: JobListing, sponsor_set: frozenset[str], remote_ok: bool = False
) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    normalized = _normalize_company(job.company or "")
    words = normalized.split()

    if normalized in sponsor_set:
        return None

    if len(normalized) < _MIN_COMPANY_CHARS or len(words) < _MIN_COMPANY_WORDS:
        if remote_ok:
            return FilteredResult(job=job, flags=["sponsor_unverified"], rejected=False, reject_reason=None)
        return FilteredResult(
            job=job, flags=[], rejected=True,
            reject_reason="company not specified — cannot verify approved sponsor",
        )

    return FilteredResult(
        job=job, flags=[], rejected=True,
        reject_reason="company not on approved sponsor list",
    )
```

- [ ] **Step 5: Thread `remote_ok` through `filter_jobs`**

In the per-job loop, after `loc_flags = loc_result.flags if loc_result is not None else []`:

```python
        remote_ok = bool({_REMOTE_CONFIRMED_FLAG, _REMOTE_WITH_TRAVEL_FLAG} & set(loc_flags))
```

Change the two calls:

```python
            recruitment_result = _check_recruitment(job, recruitment_set, remote_ok)
            ...
            sponsor_result = _check_sponsor(job, sponsor_set, remote_ok)
```

When a carve-out result comes back non-rejected with `sponsor_unverified`, it must not `continue` the loop as a rejection. Update each block so only a *rejected* result short-circuits, and a non-rejected carve-out result contributes its flag:

```python
        carve_flags: list[str] = []
        if recruitment_set is not None:
            recruitment_result = _check_recruitment(job, recruitment_set, remote_ok)
            if recruitment_result is not None:
                if recruitment_result.rejected:
                    results.append(recruitment_result)
                    continue
                carve_flags += recruitment_result.flags

        if sponsor_set is not None:
            sponsor_result = _check_sponsor(job, sponsor_set, remote_ok)
            if sponsor_result is not None:
                if sponsor_result.rejected:
                    results.append(sponsor_result)
                    continue
                carve_flags += sponsor_result.flags

        results.append(FilteredResult(
            job=job,
            flags=loc_flags + et_result.flags + carve_flags,
            rejected=False,
            reject_reason=None,
        ))
```

- [ ] **Step 6: Update `filter_trace.py` sponsor gate**

`run_filter_gates` should show the carve-out. Derive `remote_ok` from the location result and pass it to `_check_sponsor`; when the returned result is non-rejected with `sponsor_unverified`, render detail `"kept — sponsor unverified (confirmed remote)"` and `passed=True`:

```python
    remote_ok = bool({"remote_confirmed", "remote_with_travel"} & set(loc.flags)) if loc is not None else False
    sponsor = _check_sponsor(job, sponsor_set, remote_ok) if sponsor_set is not None else None
    if sponsor_set is None:
        sponsor_detail = "disabled (filter_sponsors=false)"
    elif sponsor is None:
        sponsor_detail = "n/a (NHS source)" if job.source == "nhs" else "on approved sponsor list"
    elif not sponsor.rejected:
        sponsor_detail = "kept — sponsor unverified (confirmed remote)"
    else:
        sponsor_detail = sponsor.reject_reason or ""
    gates.append(GateResult("Sponsor list", sponsor is None or not sponsor.rejected, sponsor_detail, False))
```

- [ ] **Step 7: Run the affected tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_filter.py tests/test_filter_trace.py -q`
Then: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Existing `_check_sponsor` / `_check_recruitment` call-sites pass positionally or by keyword; the new `remote_ok` defaults to `False`, so untouched call-sites keep their behaviour.

- [ ] **Step 8: Commit**

```bash
git add src/job_search_email/filter.py src/job_search_email/filter_trace.py tests/test_filter.py tests/test_filter_trace.py
git commit -m "feat: keep confirmed-remote jobs with unverifiable sponsor as sponsor_unverified"
```

---

## Task 10: email — `job_hub` + three-group partition

**Files:**
- Modify: `src/job_search_email/email.py` (`build_email_html`, badges; new `job_hub`)
- Test: `tests/test_email.py`

**Interfaces:**
- Consumes: `Profile.remote_hubs` (Task 1); `JobListing.search_legs` (Task 2); flags `remote_confirmed`, `remote_with_travel`, `sponsor_unverified` (Tasks 8-9); `location_filter.normalise_location` (Task 5).
- Produces:
  - `email.job_hub(job: JobListing, hubs: list[str]) -> str | None` — returns the hub name if `search_legs` contains `f"jobspy:hub:{hub}"` or `normalise_location(job.location)` case-insensitively equals a hub; else `None`.
  - `build_email_html` still returns `(html, n)` where `n` is the count of the **main** table. HTML now contains, when non-empty: the main table, a `Remote — London` section, and a `Remote — sponsor not verified` section. No job appears in more than one.

- [ ] **Step 1: Write failing tests in `tests/test_email.py`**

```python
def _remote_result(title, url, *, flags, legs=(), location="London", score=7):
    job = JobListing(title=title, company="Acme", location=location, salary_min=80000,
                     description="", url=url, source="linkedin", employment_type="full-time",
                     search_legs=list(legs))
    analysis = JobAnalysis(score=score, matched_skills=[], missing_essentials=[],
                           employment_type_note="", verdict="ok")
    return ScoredResult(job=job, flags=list(flags), rejected=False, reject_reason=None, analysis=analysis)


def test_job_hub_matches_by_leg_and_by_location():
    from job_search_email.email import job_hub
    from job_search_email.models import JobListing
    by_leg = JobListing(title="t", company="c", location="Anywhere", salary_min=None,
                        description="", url="u", source="linkedin", employment_type=None,
                        search_legs=["jobspy:hub:London"])
    by_loc = JobListing(title="t", company="c", location="EC3A 5AT", salary_min=None,
                        description="", url="u2", source="reed", employment_type=None)
    assert job_hub(by_leg, ["London"]) == "London"
    assert job_hub(by_loc, ["London"]) == "London"
    assert job_hub(by_loc, ["Manchester"]) is None


def test_email_has_remote_london_section():
    profile = _make_profile(remote_hubs=["London"])
    results = [
        _make_result(6, title="Local Job", url="https://x/local"),
        _remote_result("Remote London Job", "https://x/rl", flags=["remote_confirmed"],
                       legs=["jobspy:hub:London"]),
    ]
    html, n = build_email_html(results, profile)
    assert "Remote &#8212; London" in html or "Remote — London" in html
    assert "Remote London Job" in html
    assert n == 1  # only the local job is in the main table


def test_email_sponsor_unverified_section_separate():
    profile = _make_profile(remote_hubs=["London"])
    results = [
        _remote_result("Verified Remote", "https://x/v", flags=["remote_confirmed"],
                       legs=["jobspy:hub:London"]),
        _remote_result("Unverified Remote", "https://x/u",
                       flags=["remote_confirmed", "sponsor_unverified"], legs=["jobspy:hub:London"]),
    ]
    html, _ = build_email_html(results, profile)
    assert "sponsor not verified" in html.lower()
    # the unverified job is not in the London section's rows twice
    assert html.count("Unverified Remote") == 1


def test_email_no_remote_sections_when_no_hubs():
    profile = _make_profile()  # no remote block
    results = [_make_result(7, title="Plain Job", url="https://x/p")]
    html, n = build_email_html(results, profile)
    assert "Remote — London" not in html
    assert "sponsor not verified" not in html.lower()
    assert n == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email.py -q -k "job_hub or remote_london or sponsor_unverified_section or no_remote_sections"`
Expected: FAIL — `job_hub` undefined; single-table output.

- [ ] **Step 3: Add `job_hub` to `email.py`**

```python
from .location_filter import normalise_location


def job_hub(job, hubs):
    for hub in hubs:
        if f"jobspy:hub:{hub}" in job.search_legs:
            return hub
        if normalise_location(job.location or "").lower() == hub.lower():
            return hub
    return None
```

- [ ] **Step 4: Add badges**

```python
_REMOTE_TRAVEL_BADGE = (
    ' <span style="background:#6f42c1; color:#ffffff; padding:2px 6px; '
    'border-radius:4px; font-size:11px;">Remote · some travel</span>'
)
```

Helper for a row's remote badge:

```python
def _remote_badge(flags: list[str]) -> str:
    if "remote_with_travel" in flags:
        return _REMOTE_TRAVEL_BADGE
    if "remote_confirmed" in flags:
        return _REMOTE_BADGE
    return ""
```

Replace the existing `remote = _REMOTE_BADGE if "remote_confirmed" in r.flags else ""` with `remote = _remote_badge(r.flags)`.

- [ ] **Step 5: Partition in `build_email_html`**

After `eligible` is computed (non-rejected, analysis present), before building rows:

```python
    hubs = profile.remote_hubs
    def _is_confirmed_remote(r):
        return {"remote_confirmed", "remote_with_travel"} & set(r.flags)

    unverified = [r for r in eligible if "sponsor_unverified" in r.flags]
    rest = [r for r in eligible if "sponsor_unverified" not in r.flags]
    london = [r for r in rest if _is_confirmed_remote(r) and hubs and job_hub(r.job, hubs)]
    london_urls = {r.job.url for r in london}
    main = [r for r in rest if r.job.url not in london_urls]

    main.sort(key=lambda r: r.analysis.score, reverse=True)
    london.sort(key=lambda r: r.analysis.score, reverse=True)
    unverified.sort(key=lambda r: r.analysis.score, reverse=True)
    top = main[:20]
```

Render the existing table from `top`. Then append, only when non-empty, a `Remote — London` section built from `london` and a `Remote — sponsor not verified` section built from `unverified`, each reusing the same row-rendering helper (extract the per-row `<tr>` construction into a local `def _rows(items): ...` to avoid duplication — DRY). Section headings:

```python
    if hubs and london:
        parts.append('<h2 style="font-size:16px; margin-top:28px;">Remote &#8212; London</h2>')
        parts.append(_table(london))
    if unverified:
        parts.append('<h2 style="font-size:16px; margin-top:28px;">Remote &#8212; sponsor not verified</h2>')
        parts.append('<p style="font-size:12px; color:#666;">Sponsor status could not be verified from the listing — check the employer manually.</p>')
        parts.append(_table(unverified))
```

`n` (the returned count) stays `len(top)`.

- [ ] **Step 6: Run the affected tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email.py -q`
Then: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/email.py tests/test_email.py
git commit -m "feat: split email into main / Remote-London / sponsor-not-verified sections"
```

---

## Task 11: scorer & query-generation remote awareness

**Files:**
- Modify: `src/job_search_email/scorer.py` (`_build_system_prompt`)
- Modify: `src/job_search_email/queries.py` (`QUERY_GENERATION_PROMPT`, `generate_queries`)
- Test: `tests/test_scorer.py`, `tests/test_queries.py`

**Interfaces:**
- Consumes: `Profile.remote_uk_wide`, `Profile.remote_hubs` (Task 1).
- Produces: when the profile has any remote config, `_build_system_prompt` output contains a sentence telling the scorer not to penalise a confirmed-remote role for being outside the home region; `QUERY_GENERATION_PROMPT` rendering contains a remote-orientation rule. No signature changes.

- [ ] **Step 1: Write failing tests**

`tests/test_scorer.py`:

```python
def test_system_prompt_mentions_remote_when_configured():
    from job_search_email.scorer import _build_system_prompt
    from profile_helpers import make_profile
    p = make_profile(remote_hubs=["London"])
    prompt = _build_system_prompt(p)
    assert "remote" in prompt.lower()
    assert "outside" in prompt.lower()


def test_system_prompt_no_remote_line_when_not_configured():
    from job_search_email.scorer import _build_system_prompt
    from profile_helpers import make_profile
    prompt = _build_system_prompt(make_profile())
    assert "actively wants fully-remote" not in prompt
```

`tests/test_queries.py` — add a test that when `make_profile(remote_uk_wide=True)` is passed, the rendered prompt string (call `QUERY_GENERATION_PROMPT.format(...)` the same way `generate_queries` does, or expose a small `_render_prompt(profile)` helper) contains `"remote"`. Match the existing test style in that file.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scorer.py tests/test_queries.py -q -k "remote"`
Expected: FAIL.

- [ ] **Step 3: Update `scorer.py`**

In `_build_system_prompt`, build the base string as today, then append when remote is configured:

```python
    if profile.remote_uk_wide or profile.remote_hubs:
        base += (
            "\n\nRemote preference: the candidate actively wants fully-remote work. "
            "Do NOT set exclude=true, and do NOT mark the score down, solely because "
            "the role's location is outside the candidate's home region when the "
            "posting is remote. A role that is remote-first with some client travel "
            "is acceptable.\n"
        )
    return base
```

(Adjust to however the function currently returns — if it `return (...)` a single expression, refactor to a local `base = (...)` then the conditional append then `return base`.)

- [ ] **Step 4: Update `queries.py`**

Add a `{remote_rule}` placeholder into `QUERY_GENERATION_PROMPT` in the Rules block, and in `generate_queries` compute:

```python
    remote_rule = (
        "- The candidate is open to fully-remote roles nationally — favour "
        "target-title, adjacent-title, skills-led and seniority angles; do not "
        "narrow to location-bound title variants\n"
        if (profile.remote_uk_wide or profile.remote_hubs) else ""
    )
```

and pass `remote_rule=remote_rule` to `.format(...)`.

- [ ] **Step 5: Run the affected tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scorer.py tests/test_queries.py -q`
Then: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/scorer.py src/job_search_email/queries.py tests/test_scorer.py tests/test_queries.py
git commit -m "feat: make scorer and query generation aware of remote preference"
```

---

## Task 12: fixtures, offline dry run, documentation

**Files:**
- Modify: `src/job_search_email/fixtures.py`
- Modify: `CLAUDE.md`
- Modify: `src/job_search_email/search_api/CLAUDE.md`
- Test: `tests/test_local_testing.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `fixture_jobs()` includes a hub job (`search_legs=["jobspy:hub:London"]`), a `remote_with_travel` job, and a job that will land as `sponsor_unverified`; `fixture_remote_verdicts()` returns matching verdicts; `fixture_location_classification()` covers the new locations. `job-search-email-local` renders all three email groups.

- [ ] **Step 1: Write a failing test in `tests/test_local_testing.py`**

Add (matching the file's existing approach of running `local_run.main` in a tmp cwd, or calling the writers directly):

```python
def test_local_run_email_has_all_three_groups(tmp_path, monkeypatch):
    # arrange cwd + profile as the existing local-run test does, then:
    import job_search_email.local_run as lr
    monkeypatch.chdir(tmp_path)
    # (copy profiles/jie-zhou.yaml into tmp_path/profiles as the existing test does)
    lr.main()
    html = (tmp_path / "email_preview.html").read_text(encoding="utf-8")
    assert "Remote &#8212; London" in html
    assert "sponsor not verified" in html.lower()
    assert "some travel" in html.lower()
```

If the existing local-run test already sets up cwd/profile via a helper, reuse it verbatim.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_local_testing.py -q -k "three_groups"`
Expected: FAIL — fixtures have no hub / travel / unverified jobs.

- [ ] **Step 3: Extend `fixtures.py`**

Add three `JobListing`s to `fixture_jobs()`:

```python
        JobListing(
            title="Remote Programme Director (London)",
            company="Baringa",
            location="London",
            salary_min=90000,
            description="Fully remote within the UK. Permanent, full-time.",
            url="https://www.linkedin.com/jobs/view/hub-london-1",
            source="linkedin",
            employment_type="permanent",
            search_legs=["jobspy:hub:London"],
        ),
        JobListing(
            title="Transformation Lead (Remote, some travel)",
            company="Mott MacDonald",
            location="London",
            salary_min=85000,
            description="Home-based with regular travel to client sites. Permanent.",
            url="https://www.linkedin.com/jobs/view/hub-london-2",
            source="linkedin",
            employment_type="permanent",
            search_legs=["jobspy:hub:London"],
        ),
        JobListing(
            title="Head of PMO",
            company="Reed",  # sparse company string -> sponsor_unverified when remote-confirmed
            location="London",
            salary_min=80000,
            description="Fully remote (UK based). Permanent, full-time.",
            url="https://www.reed.co.uk/jobs/head-of-pmo/hub-london-3",
            source="reed",
            employment_type="permanent",
            search_legs=["jobspy:hub:London", "reed:uk-remote"],
        ),
```

Update `fixture_location_classification()` to add `"London": "uncertain"`, and `fixture_remote_verdicts()` to add:

```python
        "https://www.linkedin.com/jobs/view/hub-london-1": "remote",
        "https://www.linkedin.com/jobs/view/hub-london-2": "remote_with_travel",
        "https://www.reed.co.uk/jobs/head-of-pmo/hub-london-3": "remote",
```

Give `hub-london-1` a strong `_FIXTURE_ANALYSES` entry (score 8) so it sorts into the London section; the fallback analysis (score 5) is fine for the other two.

The offline `local_run.main` must exercise the carve-out: confirm it passes `recruitment_set` / `sponsor_set` to `filter_jobs`. It currently passes neither, so `Head of PMO`/`Reed` would be kept without the `sponsor_unverified` flag. Add to `local_run.main` the same `sponsor_set=frozenset()` and `recruitment_set=frozenset()` arguments (empty sets — enough to route through `_check_sponsor`, which flags the sparse "Reed" company as `sponsor_unverified` because the job is remote-confirmed). Keep it offline — no CSV loads.

- [ ] **Step 4: Update `CLAUDE.md`**

Replace the sentence beginning "Profiles can opt in to UK-wide remote search with `include_remote: true`…" with:

```
Profiles configure remote search with a `remote:` block (default: absent = no remote
search). `remote.uk_wide: true` adds a UK-wide remote leg to jobspy and Reed;
`remote.hubs: [London, ...]` adds one jobspy remote-only leg per named hub. Any job
not confirmed within the radius is kept only if an LLM check positively confirms the
posting is fully remote or remote-with-regular-travel (verdicts cached in
`remote_check_cache.json`); silence or hybrid wording rejects it. Confirmed-remote
jobs whose employer cannot be matched to the sponsor list (agency-posted, or company
string too sparse) are kept and shown in a separate "Remote — sponsor not verified"
email group rather than dropped. Hub jobs that clear the checks appear in a
"Remote — <hub>" section.
```

- [ ] **Step 5: Update `src/job_search_email/search_api/CLAUDE.md`**

Update the three `include_remote` references: jobspy now also issues one `location="<hub>", is_remote=True` call per `remote.hubs` entry; the UK-wide leg is gated on `remote.uk_wide`; Reed's UK-wide `" remote"` leg is likewise gated on `remote.uk_wide` and gets no hub leg.

- [ ] **Step 5b: Surface `sponsor_unverified` in the debug email**

In `src/job_search_email/debug_email.py`, `_sponsor_section` — after computing the rejected list, add a count of kept carve-out jobs and append a note, mirroring `_employment_type_section`'s `unknown_note` pattern:

```python
    unverified_count = sum(1 for r in filtered if not r.rejected and "sponsor_unverified" in r.flags)
```

and, when `unverified_count`, append `f'<p style="font-size:13px; color:#666; margin-top:8px;">{unverified_count} confirmed-remote job(s) kept as sponsor-unverified.</p>'` to that section's body. Add an assertion for this string to the existing `tests/test_debug_email.py` sponsor-section test (or a new small test) using a filtered result that carries `["remote_confirmed", "sponsor_unverified"]`.

- [ ] **Step 6: Run the affected tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_local_testing.py -q`
Then: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — full green.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/fixtures.py src/job_search_email/local_run.py src/job_search_email/debug_email.py CLAUDE.md src/job_search_email/search_api/CLAUDE.md tests/test_local_testing.py tests/test_debug_email.py
git commit -m "feat: fixtures and docs for remote hubs and sponsor-unverified group"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task(s) |
|---|---|
| 1 — `remote:` block, legacy key error, fingerprint | 1 |
| 2a — batch `classify_locations` | 4 |
| 2b — never cache fallback verdict | 4 |
| 2c — one-time cache purge | Execution note below (not code) |
| 2d — `normalise_location` | 5 |
| 2e — unicode crash | 6 |
| 3a — jobspy hub legs, no Reed hub leg | 3 (Reed left unchanged by 2/3) |
| 3b — `search_legs` vocabulary | 2 |
| 3c — dedup unions legs | 2 |
| 3d — `job_hub` helper | 10 |
| 4a — `remote_with_travel` verdict | 7 |
| 4b — gate keeps `remote_with_travel` | 8 |
| 4c — sponsor/recruitment carve-out, scope = all confirmed-remote | 9 |
| 5 — three email groups, badges, trace surfacing | 10 (email), 8 + 9 (filter_trace), 12 step 5b (debug_email) |
| 6a — scorer remote line | 11 |
| 6b — query-gen remote rule | 11 |
| 7 — tests | every task; fixtures/offline in 12 |
| 7 — `CLAUDE.md` + `search_api/CLAUDE.md` | 12 |
| Out of scope items | untouched |

**2c is not a code change.** Execution note: after Task 12, before the first real
`job-search-debug` run, delete `location_cache.json` once (gitignored, regenerated) to
clear the poisoned `"…London… → uncertain"` entries from the earlier probe.

**2. Placeholder scan** — no "TBD"/"handle edge cases"/"similar to Task N". Every code
step shows the code. Test steps show test bodies. The two places that say "match the
file's existing helper" (`test_filter_trace.py` job helper, `test_local_testing.py`
cwd setup) name the exact existing thing to copy, not an invention.

**3. Type consistency**
- `search_legs: list[str]` — same name/type in Task 2 (definition), 3, 10, 12.
- Flags `remote_confirmed` / `remote_with_travel` / `sponsor_unverified` — spelled
  identically in Tasks 8, 9, 10, 12 and Global Constraints.
- `_REMOTE_WITH_TRAVEL_FLAG` defined in Task 8, used in Task 9.
- `job_hub(job, hubs) -> str | None` — Task 10 defines, same signature in its tests
  and Task 12 fixture reasoning.
- `_check_recruitment(job, recruitment_set, remote_ok=False)` /
  `_check_sponsor(job, sponsor_set, remote_ok=False)` — Task 9 defines the third
  param with a default; `filter_trace.py` (Task 9 step 6) and existing call-sites use
  it consistently.
- `Profile.remote_uk_wide` / `remote_hubs` / `include_remote` property — Task 1
  defines; Tasks 2, 3, 10, 11 consume the exact names.
- `normalise_location` — Task 5 defines in `location_filter`; Tasks 10 and (indirectly)
  12 import from there.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-06-london-remote-hubs.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
