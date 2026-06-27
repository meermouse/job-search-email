import re
from .models import FilteredResult, JobListing, Profile, SearchPlan

_REJECT_TYPES = frozenset({
    "contract", "fixed-term", "temporary", "locum", "bank",
    "agency", "casual", "zero-hours", "part-time", "internship",
})

_PASS_TYPES = frozenset({"full-time", "permanent"})

_CONTRACT_PATTERNS = re.compile(
    r"fixed.?term (?:contract|post|appointment)"
    r"|temporary (?:contract|post|role)"
    r"|on a contract basis"
    r"|contract basis"
    r"|maternity cover"
    r"|parental leave cover"
    r"|\d+[\s\-]month (?:contract|fixed)"
    r"|zero.hours"
    r"|bank staff"
    r"|locum post",
    re.IGNORECASE,
)


def _check_employment_type(job: JobListing) -> FilteredResult:
    et = (job.employment_type or "").lower().strip()

    if et in _REJECT_TYPES:
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=f"employment type: {et}")

    if et in _PASS_TYPES:
        return FilteredResult(job=job, flags=[], rejected=False, reject_reason=None)

    text = f"{job.title} {job.description}"[:500]
    if _CONTRACT_PATTERNS.search(text):
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason="description contains contract indicators")

    return FilteredResult(job=job, flags=["employment_type_unknown"], rejected=False, reject_reason=None)


def _check_role_suitability(job: JobListing, exclusion_roles: list[str]) -> FilteredResult | None:
    raise NotImplementedError


def filter_jobs(jobs: list[JobListing], plan: SearchPlan, profile: Profile) -> list[FilteredResult]:
    raise NotImplementedError
