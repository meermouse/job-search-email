from unittest.mock import patch, MagicMock
from job_search_email.models import Profile
from job_search_email.search_api.nhs_jobs import search, _parse_salary


PROFILE = Profile(
    name="Jie", current_role="NHS Digital", about="", seniority="Senior",
    industry="NHS", skills=[], previous_roles=[], target_roles=[],
    open_to=[], not_open_to=[], qualifications=[],
    employment_type=["full-time"], location="Bristol", min_salary=60000,
)

NHS_HTML = """
<html><body><ul>
  <li>
    <div class="nhsuk-card nhsuk-card--clickable">
      <div class="nhsuk-card__content">
        <h2><a class="nhsuk-card__link" href="/candidate/jobadvert/view/1001">
          Digital Transformation Manager
        </a></h2>
        <p class="nhsuk-body">NHS Bristol Trust</p>
        <p class="nhsuk-body">Bristol, BS1 2AA</p>
        <p class="nhsuk-body">£65,000 - £75,000 a year</p>
      </div>
    </div>
  </li>
</ul></body></html>
"""


def test_search_returns_job_listings(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.text = NHS_HTML
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.nhs_jobs.requests.get", return_value=mock_resp):
        result = search("digital transformation", PROFILE)

    assert len(result) == 1
    job = result[0]
    assert job.title == "Digital Transformation Manager"
    assert job.company == "NHS Bristol Trust"
    assert job.location == "Bristol, BS1 2AA"
    assert job.salary_min == 65000
    assert job.url == "https://jobs.nhs.uk/candidate/jobadvert/view/1001"
    assert job.source == "nhs"
    assert job.description == ""
    assert job.employment_type is None


def test_search_filters_below_min_salary(monkeypatch):
    html = NHS_HTML.replace("£65,000 - £75,000 a year", "£40,000 a year")
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.nhs_jobs.requests.get", return_value=mock_resp):
        result = search("digital transformation", PROFILE)

    assert result == []


def test_search_includes_job_with_unknown_salary(monkeypatch):
    html = NHS_HTML.replace("£65,000 - £75,000 a year", "Competitive")
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status.return_value = None

    with patch("job_search_email.search_api.nhs_jobs.requests.get", return_value=mock_resp):
        result = search("digital transformation", PROFILE)

    assert len(result) == 1
    assert result[0].salary_min is None


def test_parse_salary_extracts_first_pound_figure():
    assert _parse_salary("£65,000 - £75,000 a year") == 65000
    assert _parse_salary("£60,000 pa") == 60000
    assert _parse_salary("Competitive") is None
    assert _parse_salary("") is None
