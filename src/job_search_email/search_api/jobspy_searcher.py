import math
import re
from jobspy import scrape_jobs
from ..models import JobListing, Profile

_SALARY_RE = re.compile(r'£([\d,]+)(k)?', re.IGNORECASE)


def search(query: str, profile: Profile) -> list[JobListing]:
    df = scrape_jobs(
        site_name=["linkedin", "indeed"],
        search_term=query,
        location=profile.location,
        distance=50,
        results_wanted=50,
        country_indeed="UK",
    )

    if df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        salary_min = _extract_salary_min(row)
        if salary_min is not None and salary_min < profile.min_salary:
            continue

        results.append(JobListing(
            title=_str(row.get("title")),
            company=_str(row.get("company")),
            location=_str(row.get("location")),
            salary_min=salary_min,
            description=_str(row.get("description")),
            url=_str(row.get("job_url")),
            source=_str(row.get("site")).lower(),
            employment_type=_str(row.get("job_type")) or None,
        ))

    return results


def _str(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value)


def _extract_salary_min(row) -> int | None:
    min_amount = row.get("min_amount")
    if min_amount is not None and not (isinstance(min_amount, float) and math.isnan(min_amount)):
        return int(min_amount)

    match = _SALARY_RE.search(_str(row.get("description")))
    if match:
        value = int(match.group(1).replace(",", ""))
        if match.group(2):
            value *= 1000
        return value

    return None
