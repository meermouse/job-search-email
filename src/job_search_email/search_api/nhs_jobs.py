import re
import requests
from bs4 import BeautifulSoup
from ..models import JobListing, Profile

_NHS_URL = "https://jobs.nhs.uk/candidate/search/results"
_SALARY_RE = re.compile(r'£([\d,]+)')


def search(query: str, profile: Profile) -> list[JobListing]:
    params = {"keyword": query, "location": profile.location, "distance": 50, "language": "en"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    response = requests.get(_NHS_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for card in soup.select(".nhsuk-card.nhsuk-card--clickable"):
        link = card.select_one("a.nhsuk-card__link")
        paragraphs = card.select("p.nhsuk-body")

        title = link.get_text(strip=True) if link else ""
        href = link.get("href", "") if link else ""
        company = paragraphs[0].get_text(strip=True) if len(paragraphs) > 0 else ""
        location = paragraphs[1].get_text(strip=True) if len(paragraphs) > 1 else ""
        salary_text = paragraphs[2].get_text(strip=True) if len(paragraphs) > 2 else ""

        salary_min = _parse_salary(salary_text)
        if salary_min is not None and salary_min < profile.min_salary:
            continue

        results.append(JobListing(
            title=title,
            company=company,
            location=location,
            salary_min=salary_min,
            description="",
            url=f"https://jobs.nhs.uk{href}" if href else "",
            source="nhs",
            employment_type=None,
        ))

    return results


def _parse_salary(text: str) -> int | None:
    match = _SALARY_RE.search(text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None
