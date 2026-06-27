import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_search_email.main import (
    fingerprint_profile,
    generate_search_plan,
    load_cached_plan,
    load_profile,
    save_cached_plan,
)
from job_search_email.models import Profile, SearchPlan


PROFILE_YAML = """
profile:
  name: Test User
  current_role: NHS Project Manager
  about: Experienced project manager in NHS.
  seniority: Senior
  industry: NHS / Private Sector
  skills:
    - stakeholder management
    - digital transformation
  previous_roles:
    - Business Manager
    - Project Lead
  target_roles:
    - Programme Manager
    - Digital Lead
  open_to:
    - Strategy Consultant
  not_open_to:
    - clinical roles
    - nursing
  qualifications:
    - MSc Project Management
  employment_type:
    - full-time

location: Bristol
min_salary: 60000
preamble: "Test preamble"
"""


def make_profile() -> Profile:
    return Profile(
        name="Test User",
        current_role="NHS Project Manager",
        about="Experienced project manager in NHS.",
        seniority="Senior",
        industry="NHS / Private Sector",
        skills=["stakeholder management", "digital transformation"],
        previous_roles=["Business Manager", "Project Lead"],
        target_roles=["Programme Manager", "Digital Lead"],
        open_to=["Strategy Consultant"],
        not_open_to=["clinical roles", "nursing"],
        qualifications=["MSc Project Management"],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )


def test_load_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")

    profile = load_profile(path=profile_path)

    assert profile.name == "Test User"
    assert profile.current_role == "NHS Project Manager"
    assert profile.seniority == "Senior"
    assert profile.location == "Bristol"
    assert profile.min_salary == 60000
    assert "clinical roles" in profile.not_open_to
    assert "stakeholder management" in profile.skills
    assert not hasattr(profile, "preamble")


def test_fingerprint_and_cache(tmp_path: Path) -> None:
    profile = make_profile()
    fingerprint = fingerprint_profile(profile)
    plan = generate_search_plan(profile, fingerprint)
    cache_path = tmp_path / "search_plan_cache.json"

    save_cached_plan(plan, cache_path=cache_path)
    cached = load_cached_plan(cache_path=cache_path, fingerprint=fingerprint)

    assert cached is not None
    assert cached["profile_fingerprint"] == fingerprint
    assert len(cached["queries"]) == 8
