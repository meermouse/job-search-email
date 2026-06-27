import os
import requests
from ..models import JobListing, Profile

_REED_URL = "https://www.reed.co.uk/api/1.0/search"


def search(query: str, profile: Profile) -> list[JobListing]:
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        raise ValueError("REED_API_KEY environment variable is not set")

    params = {
        "keywords": query,
        "locationName": profile.location,
        "distancefromLocation": 50,
        "minimumSalary": profile.min_salary,
        "resultsToTake": 100,
    }
    response = requests.get(_REED_URL, params=params, auth=(api_key, ""), timeout=30)
    response.raise_for_status()

    return [_to_listing(item) for item in response.json().get("results", [])]


def _to_listing(item: dict) -> JobListing:
    return JobListing(
        title=item.get("jobTitle", ""),
        company=item.get("employerName", ""),
        location=item.get("locationName", ""),
        salary_min=item.get("minimumSalary"),
        description=item.get("jobDescription", ""),
        url=item.get("jobUrl", ""),
        source="reed",
        employment_type=_parse_employment_type(item),
    )


def _parse_employment_type(item: dict) -> str | None:
    if item.get("fullTime"):
        return "full-time"
    if item.get("partTime"):
        return "part-time"
    if item.get("contract"):
        return "contract"
    if item.get("permanent"):
        return "permanent"
    return None
