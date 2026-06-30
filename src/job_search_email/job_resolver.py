import os
import re
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup

from .models import JobListing
from .search_api.reed import _parse_employment_type

_REED_DETAIL_URL = "https://www.reed.co.uk/api/1.0/jobs/{job_id}"
_REED_ID_RE = re.compile(r"/(\d+)/?$")
_NHS_SALARY_RE = re.compile(r"£([\d,]+)")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


class UnsupportedSourceError(Exception):
    """Raised when a URL's source cannot be auto-fetched."""


def _extract_reed_id(url: str) -> str:
    match = _REED_ID_RE.search(urlparse(url).path)
    if not match:
        raise ValueError(f"could not extract Reed job id from URL: {url!r}")
    return match.group(1)


def fetch_reed_job(url: str) -> JobListing:
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        raise ValueError("REED_API_KEY environment variable is not set")
    job_id = _extract_reed_id(url)
    response = requests.get(
        _REED_DETAIL_URL.format(job_id=job_id), auth=(api_key, ""), timeout=30
    )
    response.raise_for_status()
    item = response.json()
    return JobListing(
        title=item.get("jobTitle", ""),
        company=item.get("employerName", ""),
        location=item.get("locationName", ""),
        salary_min=item.get("minimumSalary"),
        description=item.get("jobDescription", ""),
        url=url,
        source="reed",
        employment_type=_parse_employment_type(item),
    )


def fetch_nhs_job(url: str) -> JobListing:
    response = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    def _text(selector: str) -> str:
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else ""

    title = _text("h1")
    salary_text = soup.get_text(" ", strip=True)
    salary_match = _NHS_SALARY_RE.search(salary_text)
    salary_min = int(salary_match.group(1).replace(",", "")) if salary_match else None

    return JobListing(
        title=title,
        company=_text("[data-test='employer-name']") or _text(".nhsuk-caption-l"),
        location=_text("[data-test='location']"),
        salary_min=salary_min,
        description="",  # mirrors the pipeline: NHS descriptions are never fetched
        url=url,
        source="nhs",
        employment_type=None,
    )


def load_job_file(path: str) -> JobListing:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return JobListing(
        title=data.get("title", ""),
        company=data.get("company", ""),
        location=data.get("location", ""),
        salary_min=data.get("salary_min"),
        description=data.get("description", ""),
        url=data.get("url", ""),
        source=data.get("source", "manual"),
        employment_type=data.get("employment_type"),
    )


def resolve_job(url: str | None, job_file: str | None = None) -> JobListing:
    if job_file:
        return load_job_file(job_file)
    if not url:
        raise ValueError("a job URL or --job-file is required")
    host = (urlparse(url).hostname or "").lower()
    if "reed.co.uk" in host:
        return fetch_reed_job(url)
    if "jobs.nhs.uk" in host:
        return fetch_nhs_job(url)
    raise UnsupportedSourceError(
        f"cannot auto-fetch jobs from {host or url!r}; "
        "supply the job details with --job-file"
    )
