import json
from pathlib import Path

import pytest
from job_search_email.fixtures import fixture_queries, fixture_jobs, fixture_scores
from job_search_email.models import FilteredResult, JobAnalysis, JobListing


def test_fixture_queries_returns_eight_strings():
    queries = fixture_queries()
    assert len(queries) == 8
    assert all(isinstance(q, str) and q.strip() for q in queries)


def test_fixture_jobs_returns_five_listings():
    jobs = fixture_jobs()
    assert len(jobs) == 7
    assert all(isinstance(j, JobListing) for j in jobs)


def test_fixture_jobs_cover_expected_scenarios():
    jobs = fixture_jobs()
    types = [j.employment_type for j in jobs]
    assert "contract" in types, "need a contract job for employment-type rejection"
    titles_combined = " ".join(j.title for j in jobs)
    assert "Band 5" in titles_combined, "need a low-band NHS job for band-salary rejection"
    assert "Band 8b" in titles_combined, "need a passing NHS job"


def test_fixture_scores_output_length_matches_input():
    jobs = fixture_jobs()
    results = [
        FilteredResult(job=j, flags=[], rejected=False, reject_reason=None)
        for j in jobs
    ]
    scored = fixture_scores(results)
    assert len(scored) == len(results)


def test_fixture_scores_kept_known_jobs_have_analysis():
    jobs = fixture_jobs()
    results = [
        FilteredResult(job=j, flags=[], rejected=False, reject_reason=None)
        for j in jobs
    ]
    scored = fixture_scores(results)
    # All five inputs are "kept" here; known URLs should have an analysis
    known_url = "https://www.reed.co.uk/jobs/senior-business-manager/12345678"
    match = next(s for s in scored if s.job.url == known_url)
    assert match.analysis is not None
    assert isinstance(match.analysis.score, int)
    assert 1 <= match.analysis.score <= 10


def test_fixture_scores_rejected_jobs_have_no_analysis():
    jobs = fixture_jobs()
    results = [
        FilteredResult(job=j, flags=[], rejected=True, reject_reason="employment type: contract")
        if j.employment_type == "contract"
        else FilteredResult(job=j, flags=[], rejected=False, reject_reason=None)
        for j in jobs
    ]
    scored = fixture_scores(results)
    rejected = [s for s in scored if s.rejected]
    assert all(s.analysis is None for s in rejected)


def test_local_run_writes_email_preview(tmp_path, monkeypatch):
    import shutil

    # Copy the profile YAML into the temp directory
    project_root = Path(__file__).parent.parent
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    shutil.copy(project_root / "profiles" / "jie-zhou.yaml", profiles_dir / "jie-zhou.yaml")

    # Point cwd at tmp_path so all file writes land there
    monkeypatch.chdir(tmp_path)

    from job_search_email import local_run
    local_run.main()

    preview = tmp_path / "email_preview.html"
    assert preview.exists(), "email_preview.html was not created"
    content = preview.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Senior Business Manager" in content


def test_local_run_writes_json_artefacts(tmp_path, monkeypatch):
    import shutil

    project_root = Path(__file__).parent.parent
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    shutil.copy(project_root / "profiles" / "jie-zhou.yaml", profiles_dir / "jie-zhou.yaml")
    monkeypatch.chdir(tmp_path)

    from job_search_email import local_run
    local_run.main()

    assert (tmp_path / "search_plan.json").exists()
    assert (tmp_path / "job_results_filtered.json").exists()
    assert (tmp_path / "job_results_scored.json").exists()

    filtered = json.loads((tmp_path / "job_results_filtered.json").read_text())
    assert filtered["summary"]["kept"] >= 1

    scored = json.loads((tmp_path / "job_results_scored.json").read_text())
    assert "unanalysed" in scored["summary"]
    assert "analysis_failed" in scored["summary"]


from job_search_email.filter import filter_jobs
from job_search_email.fixtures import (
    fixture_jobs,
    fixture_location_classification,
    fixture_remote_verdicts,
)


def _remote_gate_results():
    from job_search_email.models import SearchPlan
    from profile_helpers import make_profile
    classification = fixture_location_classification()
    plan = SearchPlan(profile_fingerprint="fp", queries=[],
                      exclusions={"roles": [], "employment_types": []},
                      nhs_rules={}, evaluator_notes=[])
    return filter_jobs(
        fixture_jobs(), plan, make_profile(),
        rejected_locations=frozenset(l for l, v in classification.items() if v == "outside"),
        within_locations=frozenset(l for l, v in classification.items() if v == "within"),
        remote_verdicts=fixture_remote_verdicts(),
    )


def test_fixture_confirmed_remote_job_kept_with_flag():
    results = _remote_gate_results()
    remote = next(r for r in results if r.job.location == "Remote (UK)")
    assert remote.rejected is False
    assert "remote_confirmed" in remote.flags


def test_fixture_far_afield_hybrid_job_rejected():
    results = _remote_gate_results()
    manc = next(r for r in results if r.job.location == "Manchester")
    assert manc.rejected is True
    assert manc.reject_reason == "location outside radius and not confirmed fully remote: Manchester"


def test_fixture_classification_covers_all_fixture_locations():
    covered = set(fixture_location_classification())
    assert {j.location for j in fixture_jobs()} <= covered
