# tests/profile_helpers.py
from job_search_email.models import Profile


def make_profile(**overrides) -> Profile:
    kwargs = dict(
        name="Test",
        current_role="Manager",
        about="",
        seniority="Senior",
        industry="NHS",
        skills=[],
        previous_roles=[],
        target_roles=[],
        open_to=[],
        not_open_to=[],
        qualifications=[],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )
    kwargs.update(overrides)
    return Profile(**kwargs)
