import json
import sys
import time

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

    for attempt in range(1, 4):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        if not response.content:
            print(f"[queries] attempt {attempt}: empty content list (stop_reason={response.stop_reason})", file=sys.stderr)
        else:
            block = response.content[0]
            text = getattr(block, "text", "")
            if not text.strip():
                print(f"[queries] attempt {attempt}: empty text block (stop_reason={response.stop_reason}, type={type(block).__name__})", file=sys.stderr)
            else:
                try:
                    queries = json.loads(text)
                except json.JSONDecodeError as exc:
                    print(f"[queries] attempt {attempt}: JSON parse failed: {exc}\nRaw: {text!r}", file=sys.stderr)
                else:
                    if not isinstance(queries, list) or len(queries) != 8:
                        raise ValueError(f"Expected list of 8 strings from Claude, got: {queries!r}")
                    return queries

        if attempt < 3:
            time.sleep(2 ** attempt)

    raise RuntimeError("[queries] generate_queries failed after 3 attempts")
