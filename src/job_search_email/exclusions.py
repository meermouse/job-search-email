import json

import anthropic

from .models import Profile

client = anthropic.Anthropic()

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

_EXCLUSION_ROLES_PROMPT = """\
You are helping filter job search results for {name}.

Generate a list of role title keywords that would be UNSUITABLE for this candidate.
Focus especially on NHS clinical and ward-based titles that a non-clinical NHS manager might surface in searches.

Candidate:
  Current role: {current_role}
  Industry: {industry}
  Target roles: {target_roles}
  Not open to: {not_open_to}
  Skills: {skills}

Return a JSON array of lowercase strings (1-4 words each, aim for 20-30 items).
Do not include generic terms that might match legitimate management roles.
No other text.\
"""


def _generate_exclusion_roles(profile: Profile) -> list[str]:
    prompt = _EXCLUSION_ROLES_PROMPT.format(
        name=profile.name,
        current_role=profile.current_role,
        industry=profile.industry,
        target_roles=", ".join(profile.target_roles),
        not_open_to=", ".join(profile.not_open_to),
        skills=", ".join(profile.skills),
    )
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        result = json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        return []
    if not isinstance(result, list):
        return []
    return [str(term).lower() for term in result]


def get_exclusions(profile: Profile) -> dict[str, list[str]]:
    claude_roles = _generate_exclusion_roles(profile)
    roles = sorted(set(STANDARD_CLINICAL_TERMS + profile.not_open_to + claude_roles))
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
