from unittest.mock import patch, MagicMock
import pytest
from job_search_email.models import Profile
from job_search_email.search_api.reed import search


PROFILE = Profile(
    name="Jie", current_role="NHS Digital", about="", seniority="Senior",
    industry="NHS", skills=[], previous_roles=[], target_roles=[],
    open_to=[], not_open_to=[], qualifications=[],
    employment_type=["full-time"], location="Bristol", min_salary=60000,
)

REED_RESPONSE = {
    "results": [
        {
            "jobId": 12345,
            "jobTitle": "Digital Transformation Manager",
            "employerName": "NHS Bristol",
            "locationName": "Bristol, BS1",
            "minimumSalary": 65000,
            "maximumSalary": 75000,
            "jobDescription": "Lead digital transformation.",
            "jobUrl": "https://www.reed.co.uk/jobs/digital-transformation-manager/12345",
            "fullTime": True,
            "partTime": False,
            "contract": False,
            "permanent": True,
        }
    ]
}


def test_search_returns_job_listings(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = REED_RESPONSE
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("digital transformation manager", PROFILE)

    assert len(result) == 1
    job = result[0]
    assert job.title == "Digital Transformation Manager"
    assert job.company == "NHS Bristol"
    assert job.location == "Bristol, BS1"
    assert job.salary_min == 65000
    assert job.url == "https://www.reed.co.uk/jobs/digital-transformation-manager/12345"
    assert job.source == "reed"
    assert job.employment_type == "full-time"


def test_search_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("REED_API_KEY", raising=False)
    with pytest.raises(ValueError, match="REED_API_KEY"):
        search("manager", PROFILE)


def test_search_empty_results(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("no results query", PROFILE)

    assert result == []


def test_search_passes_correct_params(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp) as mock_get:
        search("business manager", PROFILE)

    params = mock_get.call_args.kwargs["params"]
    assert params["keywords"] == "business manager"
    assert params["locationName"] == "Bristol"
    assert params["minimumSalary"] == 60000
    assert params["distancefromLocation"] == 50
    assert params["resultsToTake"] == 100


def test_employment_type_part_time(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    response = {"results": [{**REED_RESPONSE["results"][0], "fullTime": False, "partTime": True}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = response
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("manager", PROFILE)

    assert result[0].employment_type == "part-time"


def test_employment_type_unknown_returns_none(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    response = {"results": [{**REED_RESPONSE["results"][0], "fullTime": False, "partTime": False, "contract": False, "permanent": False}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = response
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("manager", PROFILE)

    assert result[0].employment_type is None


def test_search_sets_posted_by_agency_true(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    response = {"results": [{**REED_RESPONSE["results"][0], "postedByRecruitmentAgency": True}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = response
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("manager", PROFILE)

    assert result[0].posted_by_agency is True


def test_search_posted_by_agency_absent_defaults_none(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.json.return_value = REED_RESPONSE  # no postedByRecruitmentAgency key
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.reed.requests.get", return_value=mock_resp):
        result = search("manager", PROFILE)

    assert result[0].posted_by_agency is None
