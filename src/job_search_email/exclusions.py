from .models import Profile

STANDARD_CLINICAL_TERMS: list[str] = [
    "locum",
    "GP",
    "surgeon",
    "nurse",
    "clinical",
    "surgical",
    "physician",
    "dentist",
    "pharmacist",
    "physiotherapist",
    "radiographer",
    "midwife",
    "paramedic",
    "theatre",
    "ward",
    "medical officer",
    "occupational therapist",
]


def get_exclusions(profile: Profile) -> dict[str, list[str]]:
    roles = sorted(set(STANDARD_CLINICAL_TERMS + profile.not_open_to))
    employment = [
        "locum",
        "fixed-term",
        "temporary",
        "bank",
        "agency",
        "casual",
        "zero-hours",
    ]
    return {"roles": roles, "employment_types": employment}
