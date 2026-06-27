from .models import Profile


def generate_queries(profile: Profile) -> list[str]:
    """Generate eight tailored search queries from the profile."""
    target = ", ".join(profile.target_roles[:2]) or "job search"
    skills = ", ".join(profile.skills[:3])
    return [
        f"{target} {skills} opportunity {i + 1}" for i in range(8)
    ]
