import json

import anthropic

from .models import Profile

client = anthropic.Anthropic()

QUERY_GENERATION_PROMPT = """\
You are a job search assistant for {name}.

Generate exactly 8 keyword search strings for use across job boards (Reed, LinkedIn, \
Indeed, NHS Jobs). These strings are passed directly as the free-text search term. \
Location and salary are handled separately — do not include them.

Rules:
- Short keyword phrases, 3–6 words
- Vary the angle: exact target titles, adjacent titles, skills-led searches, seniority variants
- Reflect the candidate's seniority ({seniority}) — do not generate junior or entry-level terms
- Avoid terms from their exclusion list: {not_open_to}
- No duplicates or near-duplicates

Candidate profile:
  Current role: {current_role}
  Industry: {industry}
  Target roles: {target_roles}
  Open to: {open_to}
  Key skills: {skills}
  Previous roles: {previous_roles}

Return a JSON array of exactly 8 strings. No other text.\
"""


def generate_queries(profile: Profile) -> list[str]:
    prompt = QUERY_GENERATION_PROMPT.format(
        name=profile.name,
        seniority=profile.seniority,
        not_open_to=", ".join(profile.not_open_to),
        current_role=profile.current_role,
        industry=profile.industry,
        target_roles=", ".join(profile.target_roles),
        open_to=", ".join(profile.open_to),
        skills=", ".join(profile.skills),
        previous_roles=", ".join(profile.previous_roles),
    )
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    queries = json.loads(response.content[0].text)
    if not isinstance(queries, list) or len(queries) != 8:
        raise ValueError(f"Expected list of 8 strings from Claude, got: {queries!r}")
    return queries
