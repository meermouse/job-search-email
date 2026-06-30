import json as _json
from dataclasses import asdict
from unittest.mock import patch

from job_search_email import job_resolver
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
    [p.start() for p in ps]
    try:
        return explain_job.explain(
            "https://www.reed.co.uk/jobs/x/1",
            run_data_path="__no_such_run_data__.json",
            **kw,
        )
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
    [p.start() for p in ps]
    try:
        code = explain_job.main(["https://www.reed.co.uk/jobs/x/1", "--run-data", "__no_such_run_data__.json"])
    finally:
        for p in ps:
            p.stop()
    assert code == 0
    assert "Score: 8/10" in capsys.readouterr().out


def test_main_returns_2_on_unsupported_source(capsys):
    from job_search_email import explain_job
    with (
        patch("job_search_email.explain_job.load_profile", return_value=_profile()),
        patch(
            "job_search_email.explain_job.resolve_job",
            side_effect=job_resolver.UnsupportedSourceError("cannot auto-fetch jobs from uk.linkedin.com"),
        ),
    ):
        code = explain_job.main(["https://uk.linkedin.com/jobs/view/1"])
    assert code == 2
    assert "cannot auto-fetch jobs from uk.linkedin.com" in capsys.readouterr().err


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
