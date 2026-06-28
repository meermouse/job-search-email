import pytest
from unittest.mock import patch
from job_search_email.email import build_email_html, send_email, send_debug_report, _quals_badge
from job_search_email.models import JobAnalysis, JobListing, Profile, ScoredResult


def _make_profile(**kwargs) -> Profile:
    defaults = dict(
        name="Jie", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=[], previous_roles=[], target_roles=[],
        open_to=[], not_open_to=[], qualifications=[], employment_type=[],
        location="Bristol", min_salary=60000,
        preamble="Hey Jie!", recipient_email="jie@example.com",
    )
    defaults.update(kwargs)
    return Profile(**defaults)


def _make_result(
    score: int,
    title: str = "Job Title",
    url: str = "https://example.com/job/1",
    salary: int | None = 70000,
    rejected: bool = False,
) -> ScoredResult:
    job = JobListing(
        title=title, company="Acme Corp", location="Bristol",
        salary_min=salary, description="",
        url=url, source="reed", employment_type="full-time",
    )
    analysis = JobAnalysis(
        score=score, matched_skills=[], missing_essentials=[],
        employment_type_note="Permanent", verdict=f"Good match for {title}",
    )
    return ScoredResult(
        job=job, flags=[], rejected=rejected,
        reject_reason="employment type: contract" if rejected else None,
        analysis=None if rejected else analysis,
    )


def test_build_email_html_includes_preamble():
    profile = _make_profile(preamble="Hey Jie, welcome!")
    html, n = build_email_html([], profile)
    assert "Hey Jie, welcome!" in html


def test_build_email_html_limits_to_20_jobs():
    profile = _make_profile()
    results = [_make_result(score=5, title=f"Position{i:02d}") for i in range(25)]
    html, n = build_email_html(results, profile)
    assert "Position00" in html
    assert "Position19" in html
    assert "Position20" not in html
    assert "Position24" not in html


def test_build_email_html_sorted_by_score_desc():
    profile = _make_profile()
    results = [
        _make_result(score=3, title="LowScore"),
        _make_result(score=9, title="HighScore"),
    ]
    html, n = build_email_html(results, profile)
    assert html.index("HighScore") < html.index("LowScore")


def test_build_email_html_excludes_rejected():
    profile = _make_profile()
    results = [
        _make_result(score=8, title="GoodJob"),
        _make_result(score=7, title="RejectedJob", rejected=True),
    ]
    html, n = build_email_html(results, profile)
    assert "GoodJob" in html
    assert "RejectedJob" not in html


def test_build_email_html_excludes_no_analysis():
    profile = _make_profile()
    no_analysis = ScoredResult(
        job=JobListing(
            title="NoAnalysisJob", company="Corp", location="Bristol",
            salary_min=70000, description="", url="https://example.com/2",
            source="reed", employment_type="full-time",
        ),
        flags=[], rejected=False, reject_reason=None, analysis=None,
    )
    results = [_make_result(score=8, title="AnalysedJob"), no_analysis]
    html, n = build_email_html(results, profile)
    assert "AnalysedJob" in html
    assert "NoAnalysisJob" not in html


def test_build_email_html_links_job_url():
    profile = _make_profile()
    results = [_make_result(score=8, url="https://jobs.example.com/abc123")]
    html, n = build_email_html(results, profile)
    assert 'href="https://jobs.example.com/abc123"' in html


def test_build_email_html_salary_not_stated_when_none():
    profile = _make_profile()
    results = [_make_result(score=8, salary=None)]
    html, n = build_email_html(results, profile)
    assert "Not stated" in html


def test_build_email_html_formats_salary_with_commas():
    profile = _make_profile()
    results = [_make_result(score=8, salary=75000)]
    html, n = build_email_html(results, profile)
    assert "£75,000" in html


def test_build_email_html_green_badge_for_high_score():
    profile = _make_profile()
    results = [_make_result(score=9)]
    html, n = build_email_html(results, profile)
    assert "#28a745" in html


def test_build_email_html_amber_badge_for_mid_score():
    profile = _make_profile()
    results = [_make_result(score=6)]
    html, n = build_email_html(results, profile)
    assert "#ffc107" in html


def test_build_email_html_red_badge_for_low_score():
    profile = _make_profile()
    results = [_make_result(score=3)]
    html, n = build_email_html(results, profile)
    assert "#dc3545" in html


def test_build_email_html_includes_verdict():
    profile = _make_profile()
    results = [_make_result(score=8, title="MyJob")]
    html, n = build_email_html(results, profile)
    assert "Good match for MyJob" in html


def test_build_email_html_zero_results_shows_count():
    profile = _make_profile()
    html, n = build_email_html([], profile)
    assert "0 jobs" in html


def test_send_email_skips_and_warns_when_no_credentials(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    profile = _make_profile()
    send_email("<html></html>", profile, n=5)  # must not raise
    captured = capsys.readouterr()
    assert "skipping" in captured.err


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


# --- _quals_badge unit tests ---

def _make_analysis(status: str = "", gaps: list[str] | None = None) -> JobAnalysis:
    return JobAnalysis(
        score=7, matched_skills=[], missing_essentials=[],
        employment_type_note="", verdict="",
        required_qualifications=gaps or [],
        qualification_gaps=gaps or [],
        qualification_status=status,
    )


def test_quals_badge_empty_status_shows_dash():
    badge = _quals_badge(_make_analysis(status=""))
    assert "&#8212;" in badge


def test_quals_badge_met_shows_green_and_checkmark():
    badge = _quals_badge(_make_analysis(status="met"))
    assert "#28a745" in badge
    assert "&#10003;" in badge


def test_quals_badge_partial_shows_amber_and_warning():
    badge = _quals_badge(_make_analysis(status="partial", gaps=["PRINCE2"]))
    assert "#ffc107" in badge
    assert "&#9888;" in badge
    assert "PRINCE2" in badge


def test_quals_badge_mismatch_shows_red_and_cross():
    badge = _quals_badge(_make_analysis(status="mismatch", gaps=["MBA"]))
    assert "#dc3545" in badge
    assert "&#10007;" in badge
    assert "MBA" in badge


def test_quals_badge_shows_first_two_gaps_only():
    gaps = ["PRINCE2", "MBA", "CFA"]
    badge = _quals_badge(_make_analysis(status="mismatch", gaps=gaps))
    assert "PRINCE2" in badge
    assert "MBA" in badge
    assert "CFA" not in badge
    assert "+1 more" in badge


def test_quals_badge_shows_all_gaps_when_two_or_fewer():
    gaps = ["PRINCE2", "MBA"]
    badge = _quals_badge(_make_analysis(status="mismatch", gaps=gaps))
    assert "PRINCE2" in badge
    assert "MBA" in badge
    assert "more" not in badge


def test_quals_badge_escapes_html_in_gap_text():
    gaps = ['<PRINCE2>', '"MBA"']
    badge = _quals_badge(_make_analysis(status="mismatch", gaps=gaps))
    assert "<PRINCE2>" not in badge
    assert "&lt;PRINCE2&gt;" in badge


# --- Email table integration tests ---

def _make_result_with_quals(
    score: int,
    status: str = "met",
    gaps: list[str] | None = None,
    title: str = "Job Title",
    url: str = "https://example.com/job/1",
    salary: int | None = 70000,
) -> ScoredResult:
    job = JobListing(
        title=title, company="Acme Corp", location="Bristol",
        salary_min=salary, description="",
        url=url, source="reed", employment_type="full-time",
    )
    analysis = JobAnalysis(
        score=score, matched_skills=[], missing_essentials=[],
        employment_type_note="Permanent", verdict=f"Good match for {title}",
        required_qualifications=gaps or [],
        qualification_gaps=gaps or [],
        qualification_status=status,
    )
    return ScoredResult(job=job, flags=[], rejected=False, reject_reason=None, analysis=analysis)


def test_build_email_html_has_quals_column_header():
    profile = _make_profile()
    results = [_make_result_with_quals(score=8)]
    html, _ = build_email_html(results, profile)
    assert "Quals" in html


def test_build_email_html_shows_green_badge_for_met():
    profile = _make_profile()
    results = [_make_result_with_quals(score=8, status="met")]
    html, _ = build_email_html(results, profile)
    assert "#28a745" in html
    assert "&#10003;" in html


def test_build_email_html_shows_red_badge_for_mismatch():
    profile = _make_profile()
    results = [_make_result_with_quals(score=3, status="mismatch", gaps=["MBA"])]
    html, _ = build_email_html(results, profile)
    assert "#dc3545" in html
    assert "MBA" in html


def test_build_email_html_shows_dash_for_no_requirements():
    profile = _make_profile()
    results = [_make_result_with_quals(score=8, status="")]
    html, _ = build_email_html(results, profile)
    assert "&#8212;" in html
