from ..models import JobListing


def deduplicate(jobs: list[JobListing]) -> list[JobListing]:
    seen: dict[tuple[str, str], JobListing] = {}
    result: list[JobListing] = []
    for job in jobs:
        key = (job.title.lower().strip(), job.company.lower().strip())
        kept = seen.get(key)
        if kept is None:
            seen[key] = job
            result.append(job)
            continue
        for leg in job.search_legs:
            if leg not in kept.search_legs:
                kept.search_legs.append(leg)
    return result
