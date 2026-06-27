from job_search_email.models import JobListing
from job_search_email.search_api.dedup import deduplicate


def _job(**kwargs) -> JobListing:
    defaults = dict(
        title="Manager", company="NHS", location="Bristol",
        salary_min=60000, description="", url="https://example.com",
        source="reed", employment_type="full-time",
    )
    return JobListing(**{**defaults, **kwargs})


def test_unique_jobs_all_kept():
    jobs = [
        _job(title="Manager", company="NHS"),
        _job(title="Director", company="NHS"),
        _job(title="Manager", company="Accenture"),
    ]
    assert len(deduplicate(jobs)) == 3


def test_exact_duplicate_removed_first_wins():
    jobs = [
        _job(title="Manager", company="NHS", source="reed"),
        _job(title="Manager", company="NHS", source="linkedin"),
    ]
    result = deduplicate(jobs)
    assert len(result) == 1
    assert result[0].source == "reed"


def test_case_insensitive_dedup():
    jobs = [
        _job(title="Digital Manager", company="NHS Bristol"),
        _job(title="digital manager", company="nhs bristol"),
    ]
    assert len(deduplicate(jobs)) == 1


def test_whitespace_stripped_before_dedup():
    jobs = [
        _job(title="  Manager  ", company="NHS"),
        _job(title="Manager", company="NHS"),
    ]
    assert len(deduplicate(jobs)) == 1


def test_empty_list_returns_empty():
    assert deduplicate([]) == []
