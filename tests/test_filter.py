from dataclasses import asdict
from job_search_email.models import FilteredResult, JobListing


def make_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Business Manager",
        company="NHS Trust",
        location="Bristol",
        salary_min=65000,
        description="",
        url="https://example.com/job/1",
        source="reed",
        employment_type=None,
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def test_filtered_result_rejected():
    job = make_job(employment_type="contract")
    result = FilteredResult(job=job, flags=[], rejected=True, reject_reason="employment type: contract")
    assert result.rejected is True
    assert result.reject_reason == "employment type: contract"
    assert result.flags == []


def test_filtered_result_kept_with_flag():
    job = make_job()
    result = FilteredResult(job=job, flags=["employment_type_unknown"], rejected=False, reject_reason=None)
    assert result.rejected is False
    assert result.reject_reason is None
    assert "employment_type_unknown" in result.flags


def test_filtered_result_serialises_with_asdict():
    job = make_job(employment_type="full-time")
    result = FilteredResult(job=job, flags=[], rejected=False, reject_reason=None)
    data = asdict(result)
    assert data["rejected"] is False
    assert data["job"]["title"] == "Business Manager"
    assert data["flags"] == []
