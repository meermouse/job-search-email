# tests/profile_helpers.py
from job_search_email.models import Profile


def make_profile(**overrides) -> Profile:
    kwargs = dict(
        name="Test",
        about="",
        seniority="Senior",
        industry="NHS",
        skills=[],
        target_roles=[],
        open_to=[],
        not_open_to=[],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )
    # Back-compat: tests written against the old bool.
    if "include_remote" in overrides:
        overrides.setdefault("remote_uk_wide", overrides.pop("include_remote"))
    kwargs.update(overrides)
    return Profile(**kwargs)
