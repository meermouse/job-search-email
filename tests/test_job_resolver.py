import json as _json
from unittest.mock import MagicMock, patch

import pytest

from job_search_email.job_resolver import (
    UnsupportedSourceError,
    _extract_reed_id,
    dump_job_file,
    fetch_nhs_job,
    fetch_reed_job,
    load_job_file,
    load_run_data,
    lookup_job,
    resolve_job,
)
from job_search_email.models import JobListing


REED_DETAIL = {
    "jobId": 53819371,
    "jobTitle": "Senior Project Manager",
    "employerName": "Acme Ltd",
    "locationName": "Bristol",
    "minimumSalary": 65000,
    "jobDescription": "Lead delivery teams.",
    "fullTime": False, "partTime": False, "contract": False, "permanent": True,
}


def test_extract_reed_id_from_url():
    url = "https://www.reed.co.uk/jobs/senior-project-manager/53819371"
    assert _extract_reed_id(url) == "53819371"


def test_extract_reed_id_with_trailing_slash_or_query():
    assert _extract_reed_id("https://www.reed.co.uk/jobs/x/53819371/") == "53819371"
    assert _extract_reed_id("https://www.reed.co.uk/jobs/x/53819371?utm=1") == "53819371"


def test_fetch_reed_job_maps_fields(monkeypatch):
    monkeypatch.setenv("REED_API_KEY", "k")
    resp = MagicMock()
    resp.json.return_value = REED_DETAIL
    resp.raise_for_status.return_value = None
    with patch("job_search_email.job_resolver.requests.get", return_value=resp):
        job = fetch_reed_job("https://www.reed.co.uk/jobs/x/53819371")
    assert job.title == "Senior Project Manager"
    assert job.company == "Acme Ltd"
    assert job.location == "Bristol"
    assert job.salary_min == 65000
    assert job.description == "Lead delivery teams."
    assert job.source == "reed"
    assert job.employment_type == "permanent"
    assert job.url == "https://www.reed.co.uk/jobs/x/53819371"


def test_fetch_reed_job_requires_api_key(monkeypatch):
    monkeypatch.delenv("REED_API_KEY", raising=False)
    with pytest.raises(ValueError, match="REED_API_KEY"):
        fetch_reed_job("https://www.reed.co.uk/jobs/x/53819371")


def test_resolve_job_linkedin_is_unsupported():
    with pytest.raises(UnsupportedSourceError, match="job-file"):
        resolve_job("https://uk.linkedin.com/jobs/view/123456")


def test_resolve_job_indeed_is_unsupported():
    with pytest.raises(UnsupportedSourceError, match="job-file"):
        resolve_job("https://uk.indeed.com/viewjob?jk=abc123")


def test_load_job_file(tmp_path):
    p = tmp_path / "job.yaml"
    p.write_text(
        "title: Programme Lead\n"
        "company: Beta Corp\n"
        "location: Bath\n"
        "salary_min: 70000\n"
        "description: Run programmes.\n"
        "employment_type: permanent\n"
        "source: linkedin\n",
        encoding="utf-8",
    )
    job = load_job_file(str(p))
    assert job.title == "Programme Lead"
    assert job.company == "Beta Corp"
    assert job.salary_min == 70000
    assert job.source == "linkedin"
    assert job.employment_type == "permanent"


def test_fetch_nhs_job_scrapes_fields():
    nhs_url = "https://jobs.nhs.uk/xi/vacancy/916964468"
    html = (
        "<html><body>"
        "<h1>Band 8a Programme Manager</h1>"
        "<span data-test='employer-name'>NHS Foundation Trust</span>"
        "<span data-test='location'>Leeds, LS1 3EX</span>"
        "<p>Salary: £55,000 per annum</p>"
        "</body></html>"
    )
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status.return_value = None
    with patch("job_search_email.job_resolver.requests.get", return_value=resp):
        job = fetch_nhs_job(nhs_url)
    assert job.title == "Band 8a Programme Manager"
    assert job.company == "NHS Foundation Trust"
    assert job.location == "Leeds, LS1 3EX"
    assert job.salary_min == 55000
    assert job.description == ""
    assert job.source == "nhs"
    assert job.url == nhs_url


def test_resolve_job_prefers_job_file_over_url(tmp_path):
    p = tmp_path / "job.yaml"
    p.write_text("title: X\ncompany: Y\nlocation: Z\nsalary_min: 60000\n"
                 "description: d\nemployment_type: permanent\nsource: reed\n",
                 encoding="utf-8")
    job = resolve_job("https://uk.linkedin.com/jobs/view/1", job_file=str(p))
    assert job.title == "X"


def _stored_job(**kw) -> JobListing:
    defaults = dict(
        title="Programme Lead", company="Beta Corp", location="Bristol",
        salary_min=70000, description="Run programmes.", url="https://uk.indeed.com/viewjob?jk=abc",
        source="indeed", employment_type="contract",
    )
    defaults.update(kw)
    return JobListing(**defaults)


def _write_run_data(path, jobs):
    from dataclasses import asdict
    path.write_text(_json.dumps([asdict(j) for j in jobs]), encoding="utf-8")


def test_load_run_data_maps_url_to_job(tmp_path):
    p = tmp_path / "job_results.json"
    _write_run_data(p, [_stored_job()])
    data = load_run_data(p)
    assert set(data) == {"https://uk.indeed.com/viewjob?jk=abc"}
    assert data["https://uk.indeed.com/viewjob?jk=abc"].employment_type == "contract"


def test_lookup_job_exact_and_normalised():
    job = _stored_job(url="https://www.reed.co.uk/jobs/x/123")
    data = {job.url: job}
    assert lookup_job("https://www.reed.co.uk/jobs/x/123", data) is job
    assert lookup_job("https://www.reed.co.uk/jobs/x/123/", data) is job   # trailing slash
    assert lookup_job("https://www.reed.co.uk/jobs/x/123?utm=1", data) is job  # query
    assert lookup_job("https://www.reed.co.uk/jobs/x/999", data) is None


def test_resolve_job_uses_run_data_for_unsupported_source():
    job = _stored_job()  # indeed url
    data = {job.url: job}
    resolved = resolve_job(job.url, run_data=data)
    assert resolved is job
    assert resolved.employment_type == "contract"


def test_resolve_job_run_data_precedes_live_fetch(monkeypatch):
    from unittest.mock import patch
    job = _stored_job(url="https://www.reed.co.uk/jobs/x/55", source="reed")
    data = {job.url: job}
    with patch("job_search_email.job_resolver.requests.get") as mock_get:
        resolved = resolve_job(job.url, run_data=data)
    assert resolved is job
    mock_get.assert_not_called()   # run data wins, no Reed call


def test_resolve_job_falls_through_to_live_fetch_when_not_in_run_data(monkeypatch):
    data = {"https://other/1": _stored_job(url="https://other/1")}
    with pytest.raises(UnsupportedSourceError):
        resolve_job("https://uk.linkedin.com/jobs/view/9", run_data=data)


def test_dump_job_file_round_trips(tmp_path):
    job = _stored_job()
    out = tmp_path / "dumped.yaml"
    dump_job_file(job, str(out))
    reloaded = load_job_file(str(out))
    assert reloaded == job
