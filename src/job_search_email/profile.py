from pathlib import Path

import yaml

from .models import EducationEntry, ExperienceEntry, Profile

VALID_EMAIL_FREQUENCIES = ("daily", "weekly", "twice-weekly")


def _parse_email_frequency(raw: object) -> str:
    """Normalise and validate the profile's email cadence.

    Accepts loose spellings such as ``"twice weekly"`` or ``"twice_weekly"``
    and returns the canonical value. Defaults to ``"daily"`` when unset.
    """
    value = str(raw or "daily").strip().lower().replace("_", "-").replace(" ", "-")
    if value not in VALID_EMAIL_FREQUENCIES:
        raise ValueError(
            f"Invalid email_frequency {raw!r}; expected one of "
            f"{', '.join(VALID_EMAIL_FREQUENCIES)}"
        )
    return value


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
        about=(p.get("about") or "").strip(),
        seniority=p.get("seniority", ""),
        industry=p.get("industry", ""),
        skills=p.get("skills", []),
        target_roles=p.get("target_roles", []),
        open_to=p.get("open_to", []),
        not_open_to=p.get("not_open_to", []),
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
        filter_sponsors=data.get("filter_sponsors", True),
        include_remote=data.get("include_remote", False),
        email_frequency=_parse_email_frequency(data.get("email_frequency")),
    )


def render_profile(profile: Profile) -> str:
    lines = [f"Name: {profile.name}"]
    if profile.headline:
        lines.append(f"Headline: {profile.headline}")
    if profile.about:
        lines += ["", "About:", profile.about.strip()]
    current = next((e for e in profile.experience if e.end == "present"), None)
    if current:
        lines += ["", f"Current role: {current.title} at {current.company}"]
    if profile.experience:
        lines += ["", "Experience:"]
        for e in profile.experience:
            span = f"{e.start} – {e.end}" if e.start else e.end
            loc = f", {e.location}" if e.location else ""
            lines.append(f"- {e.title} — {e.company} ({span}{loc})")
            if e.description:
                lines += [f"  {d}" for d in e.description.strip().splitlines()]
    if profile.education:
        lines += ["", "Education:"]
        lines += [f"- {ed.degree} — {ed.institution}" for ed in profile.education]
    if profile.certifications:
        lines += ["", "Certifications:"]
        lines += [f"- {c}" for c in profile.certifications]
    if profile.skills:
        lines += ["", f"Skills: {', '.join(profile.skills)}"]
    if profile.languages:
        lines.append(f"Languages: {', '.join(profile.languages)}")
    return "\n".join(lines)
