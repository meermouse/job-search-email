from unittest.mock import patch
import pandas as pd
from job_search_email.models import Profile
from job_search_email.search_api.jobspy_searcher import search


PROFILE = Profile(
    name="Jie", current_role="NHS Digital", about="", seniority="Senior",
    industry="NHS", skills=[], previous_roles=[], target_roles=[],
    open_to=[], not_open_to=[], qualifications=[],
    employment_type=["full-time"], location="Bristol", min_salary=60000,
)

SAMPLE_DF = pd.DataFrame([
    {
        "site": "linkedin",
        "job_url": "https://linkedin.com/jobs/1",
        "title": "Digital Transformation Manager",
        "company": "NHS Bristol",
        "location": "Bristol, UK",
        "description": "Lead digital transformation.",
        "min_amount": 65000.0,
        "max_amount": 75000.0,
        "job_type": "fulltime",
        "currency": "GBP",
    },
    {
        "site": "indeed",
        "job_url": "https://indeed.com/jobs/2",
        "title": "Business Manager",
        "company": "Accenture",
        "location": "Bristol, UK",
        "description": "Consulting role.",
        "min_amount": 55000.0,  # below min_salary — must be filtered
        "max_amount": 65000.0,
        "job_type": "fulltime",
        "currency": "GBP",
    },
])


def test_search_returns_job_listings():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs", return_value=SAMPLE_DF):
        result = search("digital transformation", PROFILE)

    assert len(result) == 1
    job = result[0]
    assert job.title == "Digital Transformation Manager"
    assert job.company == "NHS Bristol"
    assert job.salary_min == 65000
    assert job.source == "linkedin"
    assert job.employment_type == "fulltime"
    assert job.url == "https://linkedin.com/jobs/1"


def test_search_filters_below_min_salary():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs", return_value=SAMPLE_DF):
        result = search("manager", PROFILE)

    assert all(j.title != "Business Manager" for j in result)


def test_search_salary_regex_fallback():
    df = pd.DataFrame([{
        "site": "indeed",
        "job_url": "https://indeed.com/jobs/3",
        "title": "Project Manager",
        "company": "NHS",
        "location": "Bristol",
        "description": "Salary: £70,000 per annum",
        "min_amount": float("nan"),
        "max_amount": float("nan"),
        "job_type": None,
        "currency": "GBP",
    }])
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs", return_value=df):
        result = search("project manager", PROFILE)

    assert len(result) == 1
    assert result[0].salary_min == 70000


def test_search_passes_correct_params():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs", return_value=pd.DataFrame()) as mock_scrape:
        search("business manager", PROFILE)

    kwargs = mock_scrape.call_args.kwargs
    assert kwargs["search_term"] == "business manager"
    assert kwargs["location"] == "Bristol"
    assert kwargs["site_name"] == ["linkedin", "indeed"]
    assert kwargs["distance"] == 50
    assert kwargs["country_indeed"] == "UK"


def test_search_returns_empty_on_empty_dataframe():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs", return_value=pd.DataFrame()):
        result = search("nothing", PROFILE)
    assert result == []
