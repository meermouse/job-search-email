# src/job_search_email/search_api/fetcher.py
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..models import JobListing, Profile, SearchPlan
from . import jobspy_searcher, reed, nhs_jobs
from .dedup import deduplicate

_SEARCHERS = [jobspy_searcher, reed, nhs_jobs]


def fetch_all_jobs(plan: SearchPlan, profile: Profile) -> list[JobListing]:
    tasks = [
        (searcher, query)
        for searcher in _SEARCHERS
        for query in plan.queries
    ]

    all_jobs: list[JobListing] = []

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(searcher.search, query, profile): (searcher.__name__, query)
            for searcher, query in tasks
        }
        for future in as_completed(futures):
            module_name, query = futures[future]
            try:
                all_jobs.extend(future.result())
            except Exception as exc:
                print(f"[{module_name}] query {query!r} failed: {exc}", file=sys.stderr)

    return deduplicate(all_jobs)
