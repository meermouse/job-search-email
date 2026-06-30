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
