from typing import Any


def get_nhs_rules() -> dict[str, Any]:
    """Return NHS band floor rules used in the plan."""
    return {
        "default_floor": "Band 8a+",
        "london_remote_exception": "Band 7+",
    }
