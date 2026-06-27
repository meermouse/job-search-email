from .models import Profile


def get_evaluator_notes(profile: Profile) -> list[str]:
    return [
        f"Candidate is {profile.seniority} level — reject junior or entry-level roles.",
        f"Target industries: {profile.industry}.",
        f"Minimum salary £{profile.min_salary:,} — reject roles with explicit salary below this.",
        f"Exclude roles matching: {', '.join(profile.not_open_to)}.",
        (
            "For NHS roles: require Band 8a+ unless London-based and remote-friendly "
            "(Band 7+ acceptable)."
        ),
        "Prefer permanent positions — flag contract, locum, bank, or temporary roles.",
        f"Weight highly: {', '.join(profile.skills[:4])}.",
        f"Strong fit signals: {', '.join(profile.target_roles + profile.open_to)}.",
    ]
