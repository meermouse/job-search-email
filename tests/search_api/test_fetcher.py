# tests/search_api/test_fetcher.py
from unittest.mock import patch
from job_search_email.models import JobListing, Profile, SearchPlan
from job_search_email.search_api.fetcher import fetch_all_jobs


PROFILE = Profile(
    name="Jie", current_role="NHS Digital", about="", seniority="Senior",
    industry="NHS", skills=[], previous_roles=[], target_roles=[],
    open_to=[], not_open_to=[], qualifications=[],
    employment_type=["full-time"], location="Bristol", min_salary=60000,
)

PLAN = SearchPlan(
    profile_fingerprint="abc123",
    queries=["business manager", "digital transformation"],
    exclusions={}, nhs_rules={}, evaluator_notes=[],
)


def _job(title: str, source: str) -> JobListing:
    return JobListing(
        title=title, company="NHS", location="Bristol",
        salary_min=65000, description="", url="https://example.com",
        source=source, employment_type="full-time",
    )


def test_fetch_calls_all_searchers_with_all_queries():
    with (
        patch("job_search_email.search_api.fetcher.jobspy_searcher.search", return_value=[]) as mock_js,
        patch("job_search_email.search_api.fetcher.reed.search", return_value=[]) as mock_reed,
        patch("job_search_email.search_api.fetcher.nhs_jobs.search", return_value=[]) as mock_nhs,
    ):
        fetch_all_jobs(PLAN, PROFILE)

    assert mock_js.call_count == 2   # 2 queries × 1 searcher
    assert mock_reed.call_count == 2
    assert mock_nhs.call_count == 2


def test_fetch_concatenates_and_deduplicates():
    with (
        patch("job_search_email.search_api.fetcher.jobspy_searcher.search", return_value=[_job("Job A", "linkedin")]),
        patch("job_search_email.search_api.fetcher.reed.search", return_value=[_job("Job B", "reed")]),
        patch("job_search_email.search_api.fetcher.nhs_jobs.search", return_value=[_job("Job C", "nhs")]),
    ):
        result = fetch_all_jobs(PLAN, PROFILE)

    titles = {j.title for j in result}
    assert titles == {"Job A", "Job B", "Job C"}


def test_fetch_deduplicates_cross_source():
    with (
        patch("job_search_email.search_api.fetcher.jobspy_searcher.search", return_value=[_job("Same Job", "linkedin")]),
        patch("job_search_email.search_api.fetcher.reed.search", return_value=[_job("Same Job", "reed")]),
        patch("job_search_email.search_api.fetcher.nhs_jobs.search", return_value=[]),
    ):
        result = fetch_all_jobs(PLAN, PROFILE)

    same = [j for j in result if j.title == "Same Job"]
    assert len(same) == 1


def test_fetch_continues_on_per_task_failure(capsys):
    def fail(query, profile):
        raise ConnectionError("Reed API unreachable")

    with (
        patch("job_search_email.search_api.fetcher.jobspy_searcher.search", return_value=[]),
        patch("job_search_email.search_api.fetcher.reed.search", side_effect=fail),
        patch("job_search_email.search_api.fetcher.nhs_jobs.search", return_value=[_job("NHS Job", "nhs")]),
    ):
        result = fetch_all_jobs(PLAN, PROFILE)

    assert any(j.source == "nhs" for j in result)
    assert "reed" in capsys.readouterr().err.lower()
