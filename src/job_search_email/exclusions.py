def get_exclusions() -> dict[str, list[str]]:
    """Return exclusion keyword groups for the job search plan."""
    return {
        "clinical_roles": ["doctor", "nurse", "consultant"],
        "employment_types": ["locum", "fixed-term", "temporary"],
    }
