from typing import Any


def get_nhs_rules() -> dict[str, Any]:
    return {
        "default_floor": "Band 8a",
        "london_remote_floor": "Band 7",
        "band_salary_map": {
            "Band 7":  43742,
            "Band 8a": 53755,
            "Band 8b": 62215,
            "Band 8c": 72293,
            "Band 8d": 83571,
            "Band 9":  96376,
        },
        "rule": (
            "Apply Band 8a floor by default. "
            "London-remote roles may accept Band 7+."
        ),
    }
