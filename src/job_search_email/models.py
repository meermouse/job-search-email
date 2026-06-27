from dataclasses import dataclass
from typing import Any


@dataclass
class Profile:
    name: str
    target_roles: list[str]
    skills: list[str]
    location: str
    preferred_nhs_band: str


@dataclass
class SearchPlan:
    profile_fingerprint: str
    queries: list[str]
    exclusions: dict[str, list[str]]
    nhs_rules: dict[str, Any]
    evaluator_notes: list[str]
