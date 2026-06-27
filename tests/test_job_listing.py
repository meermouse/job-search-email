from job_search_email.models import JobListing


def test_job_listing_all_fields():
    job = JobListing(
        title="Digital Transformation Manager",
        company="NHS Bristol",
        location="Bristol",
        salary_min=60000,
        description="A great role.",
        url="https://www.reed.co.uk/jobs/manager/12345",
        source="reed",
        employment_type="full-time",
    )
    assert job.title == "Digital Transformation Manager"
    assert job.salary_min == 60000
    assert job.source == "reed"
    assert job.employment_type == "full-time"


def test_job_listing_optional_fields_accept_none():
    job = JobListing(
        title="NHS Manager",
        company="NHS Trust",
        location="Bristol",
        salary_min=None,
        description="",
        url="https://jobs.nhs.uk/job/1",
        source="nhs",
        employment_type=None,
    )
    assert job.salary_min is None
    assert job.employment_type is None
