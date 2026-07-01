from dataclasses import dataclass, field
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
    radius_miles: int = 50
    preamble: str = ""
    recipient_email: str = ""
    send_main_email: bool = True
    send_debug_email: bool = False


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
    posted_by_agency: bool | None = None


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
    required_qualifications: list[str] = field(default_factory=list)
    qualification_gaps: list[str] = field(default_factory=list)
    qualification_status: str = ""
    exclude: bool = False
    exclude_reason: str = ""


@dataclass
class ScoredResult:
    job: JobListing
    flags: list[str]
    rejected: bool
    reject_reason: str | None
    analysis: JobAnalysis | None
