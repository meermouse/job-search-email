# src/job_search_email/profile.py
from pathlib import Path

import yaml

from .models import EducationEntry, ExperienceEntry, Profile


def _parse_experience(entries: list[dict]) -> list[ExperienceEntry]:
    return [
        ExperienceEntry(
            title=e.get("title", ""),
            company=e.get("company", ""),
            start=str(e.get("start", "")),
            end=str(e.get("end", "")),
            location=e.get("location", ""),
            description=(e.get("description") or "").strip(),
        )
        for e in entries
    ]


def _parse_education(entries: list[dict]) -> list[EducationEntry]:
    return [
        EducationEntry(
            institution=e.get("institution", ""),
            degree=e.get("degree", ""),
        )
        for e in entries
    ]


def load_profile(path: Path) -> Profile:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)

    p = data["profile"]
    return Profile(
        name=p["name"],
        current_role="",
        about=(p.get("about") or "").strip(),
        seniority=p.get("seniority", ""),
        industry=p.get("industry", ""),
        skills=p.get("skills", []),
        previous_roles=[],
        target_roles=p.get("target_roles", []),
        open_to=p.get("open_to", []),
        not_open_to=p.get("not_open_to", []),
        qualifications=[],
        employment_type=p.get("employment_type", []),
        location=data.get("location", ""),
        min_salary=data.get("min_salary", 0),
        headline=p.get("headline", ""),
        experience=_parse_experience(p.get("experience", [])),
        education=_parse_education(p.get("education", [])),
        certifications=p.get("certifications", []),
        languages=p.get("languages", []),
        radius_miles=data.get("radius_miles", 50),
        preamble=data.get("preamble", ""),
        recipient_email=data.get("recipient_email", ""),
        send_main_email=data.get("send_main_email", True),
        send_debug_email=data.get("send_debug_email", False),
        filter_recruitment=data.get("filter_recruitment", True),
    )
