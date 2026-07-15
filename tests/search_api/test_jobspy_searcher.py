from unittest.mock import patch
import pandas as pd
from job_search_email.search_api.jobspy_searcher import search
from profile_helpers import make_profile


PROFILE = make_profile(name="Jie")

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
    assert job.employment_type == "full-time"
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


REMOTE_PROFILE = make_profile(name="Jie", include_remote=True)


def test_search_remote_off_single_scrape_call():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame()) as mock_scrape:
        search("manager", PROFILE)
    assert mock_scrape.call_count == 1


def test_search_remote_on_adds_uk_wide_remote_leg():
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               return_value=pd.DataFrame()) as mock_scrape:
        search("manager", REMOTE_PROFILE)

    assert mock_scrape.call_count == 2
    radius_kwargs = mock_scrape.call_args_list[0].kwargs
    remote_kwargs = mock_scrape.call_args_list[1].kwargs
    assert radius_kwargs["location"] == "Bristol"
    assert radius_kwargs["distance"] == 50
    assert remote_kwargs["location"] == "United Kingdom"
    assert remote_kwargs["is_remote"] is True
    assert remote_kwargs["search_term"] == "manager"
    assert remote_kwargs["country_indeed"] == "UK"
    assert "distance" not in remote_kwargs


def test_search_remote_on_concatenates_both_legs():
    remote_df = pd.DataFrame([{
        "site": "linkedin",
        "job_url": "https://linkedin.com/jobs/99",
        "title": "Remote Digital Lead",
        "company": "Acme Analytics",
        "location": "United Kingdom (Remote)",
        "description": "Fully remote role.",
        "min_amount": 70000.0,
        "max_amount": 80000.0,
        "job_type": "fulltime",
        "currency": "GBP",
    }])
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               side_effect=[SAMPLE_DF, remote_df]):
        result = search("manager", REMOTE_PROFILE)

    titles = {j.title for j in result}
    assert "Digital Transformation Manager" in titles  # radius leg
    assert "Remote Digital Lead" in titles             # remote leg


def test_search_remote_leg_failure_keeps_radius_results(capsys):
    with patch("job_search_email.search_api.jobspy_searcher.scrape_jobs",
               side_effect=[SAMPLE_DF, ConnectionError("linkedin down")]):
        result = search("manager", REMOTE_PROFILE)

    assert any(j.title == "Digital Transformation Manager" for j in result)
    assert "remote leg failed" in capsys.readouterr().err
