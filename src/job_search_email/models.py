from dataclasses import dataclass
from typing import Any


@dataclass
class Profile:
    name: str
    current_role: str
    about: str
    seniority: str
    industry: str
    skills: list[str]
    previous_roles: list[str]
    target_roles: list[str]
    open_to: list[str]
    not_open_to: list[str]
    qualifications: list[str]
    employment_type: list[str]
    location: str
    min_salary: int


@dataclass
class SearchPlan:
    profile_fingerprint: str
    queries: list[str]
    exclusions: dict[str, list[str]]
    nhs_rules: dict[str, Any]
    evaluator_notes: list[str]


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    salary_min: int | None
    description: str
    url: str
    source: str
    employment_type: str | None


@dataclass
class FilteredResult:
    job: JobListing
    flags: list[str]
    rejected: bool
    reject_reason: str | None


@dataclass
class JobAnalysis:
    score: int
    matched_skills: list[str]
    missing_essentials: list[str]
    employment_type_note: str
    verdict: str


@dataclass
class ScoredResult:
    job: JobListing
    flags: list[str]
    rejected: bool
    reject_reason: str | None
    analysis: JobAnalysis | None
