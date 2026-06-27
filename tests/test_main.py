from pathlib import Path

from job_search_email.main import (
    Profile,
    fingerprint_profile,
    generate_search_plan,
    load_profile,
    load_cached_plan,
    save_cached_plan,
)


def test_load_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        """
name: Test User
target_roles:
  - Data Scientist
skills:
  - Python
  - Machine Learning
location: Remote
preferred_nhs_band: Band 8a+
""",
        encoding="utf-8",
    )

    profile = load_profile(path=profile_path)

    assert profile.name == "Test User"
    assert "Data Scientist" in profile.target_roles
    assert profile.location == "Remote"


def test_fingerprint_and_cache(tmp_path: Path) -> None:
    profile = Profile(
        name="Cache User",
        target_roles=["Analyst"],
        skills=["Excel"],
        location="London",
        preferred_nhs_band="Band 8a+",
    )
    fingerprint = fingerprint_profile(profile)
    plan = generate_search_plan(profile, fingerprint)
    cache_path = tmp_path / "search_plan_cache.json"

    save_cached_plan(plan, cache_path=cache_path)
    cached = load_cached_plan(cache_path=cache_path, fingerprint=fingerprint)

    assert cached is not None
    assert cached["profile_fingerprint"] == fingerprint
    assert len(cached["queries"]) == 8
