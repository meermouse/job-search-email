from ..models import JobListing


def deduplicate(jobs: list[JobListing]) -> list[JobListing]:
    seen: set[tuple[str, str]] = set()
    result: list[JobListing] = []
    for job in jobs:
        key = (job.title.lower().strip(), job.company.lower().strip())
        if key not in seen:
            seen.add(key)
            result.append(job)
    return result
