# Debug Email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a debug email that logs each filter's decisions, controlled by two new boolean toggles in `profile.yaml`.

**Architecture:** Add `send_main_email` / `send_debug_email` booleans to `Profile`; create `debug_email.py` for the debug HTML builder; extend `email.py` with `override_to` on `send_email()` and a new `send_debug_report()` function; wire four-case routing logic into `main()`.

**Tech Stack:** Python 3.11+, smtplib, HTML email (`<details>`/`<summary>`), pytest

## Global Constraints

- All new source code lives under `src/job_search_email/`
- All tests live under `tests/`
- Run tests with `pytest` from project root
- No new dependencies — stdlib + existing packages only
- Follow existing code style: no comments unless the WHY is non-obvious

---

### Task 1: Profile config toggles

**Files:**
- Modify: `src/job_search_email/models.py` — add two fields to `Profile`
- Modify: `src/job_search_email/main.py` — read new fields in `load_profile()`
- Modify: `profile.yaml` — add explicit values
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `Profile.send_main_email: bool = True`, `Profile.send_debug_email: bool = False`

---

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_main.py`:

```python
def test_load_profile_send_flags_default_to_main_on_debug_off(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.send_main_email is True
    assert profile.send_debug_email is False


def test_load_profile_reads_explicit_send_flags(tmp_path: Path) -> None:
    yaml_with_flags = PROFILE_YAML + "send_main_email: false\nsend_debug_email: true\n"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml_with_flags, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.send_main_email is False
    assert profile.send_debug_email is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_main.py::test_load_profile_send_flags_default_to_main_on_debug_off tests/test_main.py::test_load_profile_reads_explicit_send_flags -v
```

Expected: FAIL — `TypeError` (unexpected keyword argument) or `AttributeError` (no attribute `send_main_email`).

- [ ] **Step 3: Add fields to `Profile` in `models.py`**

In `src/job_search_email/models.py`, after `recipient_email: str = ""`, add:

```python
    send_main_email: bool = True
    send_debug_email: bool = False
```

- [ ] **Step 4: Update `load_profile()` in `main.py`**

In `src/job_search_email/main.py`, inside the `return Profile(...)` call in `load_profile()`, after `recipient_email=data.get("recipient_email", ""),` add:

```python
        send_main_email=data.get("send_main_email", True),
        send_debug_email=data.get("send_debug_email", False),
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_main.py::test_load_profile_send_flags_default_to_main_on_debug_off tests/test_main.py::test_load_profile_reads_explicit_send_flags -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite to check for regressions**

```
pytest -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 7: Add fields to `profile.yaml`**

After `recipient_email: jillcn@hotmail.com`, add:

```yaml
send_main_email: true
send_debug_email: false
```

- [ ] **Step 8: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/main.py profile.yaml tests/test_main.py
git commit -m "feat: add send_main_email and send_debug_email config toggles"
```

---

### Task 2: Debug email HTML builder

**Files:**
- Create: `src/job_search_email/debug_email.py`
- Create: `tests/test_debug_email.py`

**Interfaces:**
- Consumes: `Profile` (from `models.py`), `FilteredResult` (from `models.py`)
- Produces: `build_debug_email_html(classification: dict[str, str], filtered: list[FilteredResult], profile: Profile) -> str`

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_debug_email.py`:

```python
from job_search_email.debug_email import build_debug_email_html
from job_search_email.models import FilteredResult, JobListing, Profile


def _make_profile() -> Profile:
    return Profile(
        name="Jie", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=[], location="Bristol", min_salary=60000,
    )


def _make_job(location: str = "Bristol") -> JobListing:
    return JobListing(
        title="Business Manager", company="NHS Trust", location=location,
        salary_min=65000, description="", url="https://example.com/1",
        source="reed", employment_type="full-time",
    )


def _kept(job: JobListing, flags: list[str] | None = None) -> FilteredResult:
    return FilteredResult(job=job, flags=flags or [], rejected=False, reject_reason=None)


def _rejected(job: JobListing, reason: str) -> FilteredResult:
    return FilteredResult(job=job, flags=[], rejected=True, reject_reason=reason)


def test_location_within_appears_in_html():
    html = build_debug_email_html({"Bristol": "within"}, [_kept(_make_job("Bristol"))], _make_profile())
    assert "Bristol" in html
    assert "Within" in html


def test_location_outside_appears_in_html():
    html = build_debug_email_html(
        {"London": "outside"},
        [_rejected(_make_job("London"), "location outside radius: London")],
        _make_profile(),
    )
    assert "London" in html
    assert "Outside" in html


def test_location_uncertain_appears_in_html():
    html = build_debug_email_html({"Remote": "uncertain"}, [_kept(_make_job("Remote"))], _make_profile())
    assert "Remote" in html
    assert "Uncertain" in html


def test_location_job_count_includes_kept_and_rejected():
    filtered = [
        _kept(_make_job("Bristol")),
        _rejected(_make_job("Bristol"), "employment type: contract"),
    ]
    html = build_debug_email_html({"Bristol": "within"}, filtered, _make_profile())
    assert ">2<" in html


def test_employment_type_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "employment type: contract")],
        _make_profile(),
    )
    assert "Business Manager" in html
    assert "employment type: contract" in html


def test_contract_indicator_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "description contains contract indicators")],
        _make_profile(),
    )
    assert "description contains contract indicators" in html


def test_employment_type_unknown_flag_summary_appears():
    html = build_debug_email_html(
        {},
        [_kept(_make_job(), flags=["employment_type_unknown"])],
        _make_profile(),
    )
    assert "unknown employment type" in html.lower()


def test_role_suitability_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "unsuitable role: nurse")],
        _make_profile(),
    )
    assert "Business Manager" in html
    assert "nurse" in html


def test_nhs_band_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "nhs band salary below threshold: Band 6 (~£35,000)")],
        _make_profile(),
    )
    assert "Business Manager" in html
    assert "Band 6" in html


def test_debug_email_has_four_details_sections():
    html = build_debug_email_html({}, [], _make_profile())
    assert html.count("<details") == 4


def test_debug_email_includes_profile_name():
    html = build_debug_email_html({}, [], _make_profile())
    assert "Jie" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_debug_email.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'job_search_email.debug_email'`

- [ ] **Step 3: Create `src/job_search_email/debug_email.py`**

```python
from collections import Counter
from datetime import date
from html import escape as _escape

from .models import FilteredResult, Profile


def _location_section(classification: dict[str, str], filtered: list[FilteredResult]) -> str:
    job_counts: Counter[str] = Counter(r.job.location for r in filtered if r.job.location)

    def _table(verdict: str, header_bg: str) -> str:
        locs = sorted(loc for loc, v in classification.items() if v == verdict)
        if not locs:
            return f'<p style="color:#999; font-size:13px;">No locations classified as {verdict}.</p>'
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(loc)}</td>'
            f'<td style="padding:4px 8px; text-align:right;">{job_counts.get(loc, 0)}</td></tr>'
            for loc in locs
        )
        return (
            f'<table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:12px;">'
            f'<thead><tr style="background:{header_bg}; color:#fff;">'
            f'<th style="padding:4px 8px; text-align:left;">{verdict.title()}</th>'
            f'<th style="padding:4px 8px; text-align:right;">Jobs</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details open><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "Location Filter</summary>"
        + _table("within", "#28a745")
        + _table("uncertain", "#e6a817")
        + _table("outside", "#dc3545")
        + "</details>"
    )


def _employment_type_section(filtered: list[FilteredResult]) -> str:
    et_prefixes = ("employment type:", "description contains contract indicators")
    rejected = [
        r for r in filtered
        if r.rejected and r.reject_reason and any(r.reject_reason.startswith(p) for p in et_prefixes)
    ]
    unknown_count = sum(1 for r in filtered if not r.rejected and "employment_type_unknown" in r.flags)

    if not rejected and unknown_count == 0:
        body = '<p style="color:#999; font-size:13px;">No employment type rejections.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason or "")}</td></tr>'
            for r in rejected
        )
        table = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:left;">Reason</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        ) if rejected else ""
        unknown_note = (
            f'<p style="font-size:13px; color:#666; margin-top:8px;">'
            f'{unknown_count} job(s) passed through with unknown employment type.</p>'
        ) if unknown_count else ""
        body = table + unknown_note

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "Employment Type Filter</summary>" + body + "</details>"
    )


def _role_suitability_section(filtered: list[FilteredResult]) -> str:
    rejected = [
        r for r in filtered
        if r.rejected and r.reject_reason and r.reject_reason.startswith("unsuitable role:")
    ]

    if not rejected:
        body = '<p style="color:#999; font-size:13px;">No role suitability rejections.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason.replace("unsuitable role: ", "", 1))}</td></tr>'
            for r in rejected
        )
        body = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:left;">Matched Term</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "Role Suitability Filter</summary>" + body + "</details>"
    )


def _nhs_band_section(filtered: list[FilteredResult]) -> str:
    prefix = "nhs band salary below threshold:"
    rejected = [
        r for r in filtered
        if r.rejected and r.reject_reason and r.reject_reason.startswith(prefix)
    ]

    if not rejected:
        body = '<p style="color:#999; font-size:13px;">No NHS band salary rejections.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason.replace(prefix + " ", "", 1))}</td></tr>'
            for r in rejected
        )
        body = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:left;">Band / Salary</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "NHS Band Salary Filter</summary>" + body + "</details>"
    )


def build_debug_email_html(
    classification: dict[str, str],
    filtered: list[FilteredResult],
    profile: Profile,
) -> str:
    today = date.today().strftime("%Y-%m-%d")
    total = len(filtered)
    kept = sum(1 for r in filtered if not r.rejected)
    rejected = total - kept

    sections = (
        _location_section(classification, filtered)
        + _employment_type_section(filtered)
        + _role_suitability_section(filtered)
        + _nhs_band_section(filtered)
    )

    return (
        f'<!DOCTYPE html>\n<html>\n<head><meta charset="UTF-8"></head>\n'
        f'<body style="font-family:Arial,sans-serif; background:#ffffff; color:#333333; '
        f'max-width:920px; margin:0 auto; padding:20px;">\n'
        f'  <h2 style="margin-bottom:4px;">[DEBUG] Job Search – {today}</h2>\n'
        f'  <p style="font-size:13px; color:#666; margin-top:0;">'
        f'Profile: {_escape(profile.name)} &nbsp;| {total} jobs total &nbsp;| '
        f'{kept} kept &nbsp;| {rejected} rejected</p>\n'
        f'  <hr style="border:none; border-top:1px solid #ddd; margin:16px 0;">\n'
        f'  {sections}\n'
        f'  <p style="font-size:11px; color:#999; margin-top:24px;">Generated on {today}</p>\n'
        f'</body>\n</html>'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_debug_email.py -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite**

```
pytest -v
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/debug_email.py tests/test_debug_email.py
git commit -m "feat: add debug email HTML builder with four filter sections"
```

---

### Task 3: Email send functions — `override_to` and `send_debug_report`

**Files:**
- Modify: `src/job_search_email/email.py` — add `override_to` param to `send_email()`; add `send_debug_report()`
- Modify: `tests/test_email.py` — add tests for both

**Interfaces:**
- Produces:
  - `send_email(html: str, profile: Profile, n: int = 0, override_to: str | None = None) -> None`
  - `send_debug_report(html: str) -> None`

---

- [ ] **Step 1: Write the failing tests**

At the top of `tests/test_email.py`, add to the existing imports:

```python
from unittest.mock import patch
```

Update the existing import line:

```python
from job_search_email.email import build_email_html, send_email, send_debug_report
```

Add these test functions at the bottom of `tests/test_email.py`:

```python
def test_send_email_uses_recipient_email_by_default(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    profile = _make_profile(recipient_email="recipient@test.com")
    captured = []

    class FakeSMTP:
        def __init__(self, host, port): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, u, p): pass
        def send_message(self, msg): captured.append(msg)

    with patch("smtplib.SMTP", FakeSMTP):
        send_email("<html/>", profile)

    assert captured[0]["To"] == "recipient@test.com"


def test_send_email_override_to_replaces_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    profile = _make_profile(recipient_email="recipient@test.com")
    captured = []

    class FakeSMTP:
        def __init__(self, host, port): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, u, p): pass
        def send_message(self, msg): captured.append(msg)

    with patch("smtplib.SMTP", FakeSMTP):
        send_email("<html/>", profile, override_to="override@test.com")

    assert captured[0]["To"] == "override@test.com"


def test_send_debug_report_sends_to_smtp_user(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    captured = []

    class FakeSMTP:
        def __init__(self, host, port): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, u, p): pass
        def send_message(self, msg): captured.append(msg)

    with patch("smtplib.SMTP", FakeSMTP):
        send_debug_report("<html/>")

    assert captured[0]["To"] == "sender@test.com"
    assert "[DEBUG]" in captured[0]["Subject"]


def test_send_debug_report_skips_when_no_credentials(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    send_debug_report("<html/>")
    assert "skipping" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_email.py::test_send_email_uses_recipient_email_by_default tests/test_email.py::test_send_email_override_to_replaces_recipient tests/test_email.py::test_send_debug_report_sends_to_smtp_user tests/test_email.py::test_send_debug_report_skips_when_no_credentials -v
```

Expected: FAIL — `ImportError: cannot import name 'send_debug_report'` or `TypeError` on `override_to`.

- [ ] **Step 3: Update `send_email()` in `src/job_search_email/email.py`**

Replace the existing `send_email` function with:

```python
def send_email(html: str, profile: Profile, n: int = 0, override_to: str | None = None) -> None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    if not all([host, port, user, password]):
        print("[email] SMTP credentials not configured — skipping email send", file=sys.stderr)
        return

    to = override_to if override_to else profile.recipient_email
    if not to:
        print("[email] recipient_email not configured — skipping email send", file=sys.stderr)
        return

    today = date.today().strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["Subject"] = f"Job Search Results – {today} ({n} jobs found)"
    msg["From"] = user
    msg["To"] = to
    msg.set_content("Please view this email in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, int(port)) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"[email] sent to {to}")
    except Exception as exc:
        print(f"[email] failed to send: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Add `send_debug_report()` to `src/job_search_email/email.py`**

Append after `send_email()`:

```python
def send_debug_report(html: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    if not all([host, port, user, password]):
        print("[email] SMTP credentials not configured — skipping debug report", file=sys.stderr)
        return

    today = date.today().strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["Subject"] = f"[DEBUG] Job Search – {today}"
    msg["From"] = user
    msg["To"] = user
    msg.set_content("Please view this email in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, int(port)) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"[email] debug report sent to {user}")
    except Exception as exc:
        print(f"[email] failed to send debug report: {exc}", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_email.py -v
```

Expected: all PASS

- [ ] **Step 6: Run full test suite**

```
pytest -v
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/email.py tests/test_email.py
git commit -m "feat: add override_to param to send_email and send_debug_report function"
```

---

### Task 4: Wire routing logic in `main()`

**Files:**
- Modify: `src/job_search_email/main.py` — update imports; replace send block with routing logic
- Modify: `tests/test_main.py` — add routing tests

**Interfaces:**
- Consumes:
  - `Profile.send_main_email: bool` and `Profile.send_debug_email: bool` (Task 1)
  - `build_debug_email_html(classification: dict[str, str], filtered: list[FilteredResult], profile: Profile) -> str` (Task 2)
  - `send_email(html: str, profile: Profile, n: int = 0, override_to: str | None = None) -> None` (Task 3)
  - `send_debug_report(html: str) -> None` (Task 3)

---

- [ ] **Step 1: Write the failing routing tests**

Add to `tests/test_main.py` (after existing imports, add `from unittest.mock import patch as _patch`):

```python
from unittest.mock import patch as _patch
```

Add the helper and four routing tests at the bottom of `tests/test_main.py`:

```python
def _run_main_with_toggles(tmp_path: Path, monkeypatch, send_main: bool, send_debug: bool):
    import sys
    import importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    (tmp_path / "profile.yaml").write_text(
        "profile:\n  name: Test\n  current_role: ''\n  about: ''\n"
        "  seniority: ''\n  industry: ''\n  skills: []\n  previous_roles: []\n"
        "  target_roles: []\n  open_to: []\n  not_open_to: []\n"
        "  qualifications: []\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n"
        f"send_main_email: {'true' if send_main else 'false'}\n"
        f"send_debug_email: {'true' if send_debug else 'false'}\n",
        encoding="utf-8",
    )

    for attr, val in [
        ("ROOT", tmp_path), ("PROFILE_PATH", tmp_path / "profile.yaml"),
        ("CACHE_PATH", tmp_path / "plan.json"), ("PLAN_PATH", tmp_path / "plan.json"),
        ("RESULTS_PATH", tmp_path / "results.json"),
        ("FILTERED_RESULTS_PATH", tmp_path / "filtered.json"),
        ("SCORED_RESULTS_PATH", tmp_path / "scored.json"),
        ("SCORE_CACHE_PATH", tmp_path / "score_cache.json"),
        ("LOCATION_CACHE_PATH", tmp_path / "location_cache.json"),
    ]:
        monkeypatch.setattr(main_mod, attr, val)

    from job_search_email.models import JobListing, SearchPlan
    dummy_job = JobListing(
        title="Manager", company="NHS", location="Bristol",
        salary_min=65000, description="", url="https://x.com/1",
        source="reed", employment_type="full-time",
    )
    dummy_plan = SearchPlan(
        profile_fingerprint="test", queries=["q"],
        exclusions={"roles": [], "employment_types": []},
        nhs_rules={}, evaluator_notes=[],
    )

    with (
        _patch("job_search_email.main.fetch_all_jobs", return_value=[dummy_job]),
        _patch("job_search_email.main.generate_search_plan", return_value=dummy_plan),
        _patch("job_search_email.main.classify_locations", return_value={"Bristol": "within"}),
        _patch("job_search_email.main.score_jobs", return_value=[]),
        _patch("job_search_email.main.build_email_html", return_value=("<html/>", 0)),
        _patch("job_search_email.main.send_email") as mock_send,
        _patch("job_search_email.main.send_debug_report") as mock_debug,
        _patch("job_search_email.main.build_debug_email_html", return_value="<debug/>"),
    ):
        main_mod.main()
        return mock_send.call_count, mock_debug.call_count, mock_send.call_args_list


def test_routing_main_on_debug_off_sends_only_main(tmp_path: Path, monkeypatch):
    send_count, debug_count, _ = _run_main_with_toggles(tmp_path, monkeypatch, send_main=True, send_debug=False)
    assert send_count == 1
    assert debug_count == 0


def test_routing_main_on_debug_on_sends_both(tmp_path: Path, monkeypatch):
    send_count, debug_count, _ = _run_main_with_toggles(tmp_path, monkeypatch, send_main=True, send_debug=True)
    assert send_count == 1
    assert debug_count == 1


def test_routing_main_off_debug_on_sends_main_to_smtp_user(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    send_count, debug_count, call_args = _run_main_with_toggles(tmp_path, monkeypatch, send_main=False, send_debug=True)
    assert send_count == 1
    assert debug_count == 1
    assert call_args[0].kwargs.get("override_to") == "sender@test.com"


def test_routing_main_off_debug_off_sends_nothing(tmp_path: Path, monkeypatch):
    send_count, debug_count, _ = _run_main_with_toggles(tmp_path, monkeypatch, send_main=False, send_debug=False)
    assert send_count == 0
    assert debug_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_main.py::test_routing_main_on_debug_off_sends_only_main tests/test_main.py::test_routing_main_on_debug_on_sends_both tests/test_main.py::test_routing_main_off_debug_on_sends_main_to_smtp_user tests/test_main.py::test_routing_main_off_debug_off_sends_nothing -v
```

Expected: FAIL — `AttributeError` (attributes not yet imported in `main.py`) or assertion errors.

- [ ] **Step 3: Update imports in `src/job_search_email/main.py`**

Replace:
```python
from .email import build_email_html, send_email
```
With:
```python
from .email import build_email_html, send_email, send_debug_report
from .debug_email import build_debug_email_html
```

- [ ] **Step 4: Replace the send block in `main()` in `src/job_search_email/main.py`**

Replace:
```python
    print("Sending email...")
    html, top_n = build_email_html(scored, profile)
    send_email(html, profile, n=top_n)
```

With:
```python
    print("Sending emails...")
    main_html, top_n = build_email_html(scored, profile)

    if profile.send_main_email:
        send_email(main_html, profile, n=top_n)
    elif profile.send_debug_email:
        send_email(main_html, profile, n=top_n, override_to=os.getenv("SMTP_USER", ""))

    if profile.send_debug_email:
        debug_html = build_debug_email_html(classification, filtered, profile)
        send_debug_report(debug_html)
```

- [ ] **Step 5: Run the routing tests**

```
pytest tests/test_main.py::test_routing_main_on_debug_off_sends_only_main tests/test_main.py::test_routing_main_on_debug_on_sends_both tests/test_main.py::test_routing_main_off_debug_on_sends_main_to_smtp_user tests/test_main.py::test_routing_main_off_debug_off_sends_nothing -v
```

Expected: all PASS

- [ ] **Step 6: Run full test suite**

```
pytest -v
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/main.py tests/test_main.py
git commit -m "feat: wire debug email routing into main pipeline"
```
