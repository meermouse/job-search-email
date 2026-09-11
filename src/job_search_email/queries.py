import json
import sys
import time

import anthropic

from .models import Profile
from .profile import render_profile

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
- Two of the eight phrases must be the candidate's exact target-role titles ({target_roles}) \
— verbatim or near-verbatim — even if they read as generic. These are known-good anchors for \
this candidate and are exempt from the single-concept restriction below.
- At least four of the eight phrases must carry a domain or specialism anchor — the \
candidate's sector ({industry}) or a named function drawn from their profile (e.g. governance, \
workforce planning, information governance, assurance) — not just a bare seniority word plus a \
generic verb
- Aside from the two exact target-role phrases above, do not use broad single-concept terms \
on their own ("consultant", "manager", "lead", "strategy", "operations", "transformation", \
"project management", "analytics", "change"): alone they match a wide pool of unrelated \
management-consultancy and vendor-implementation roles. Each must be qualified by something \
specific to this candidate
- A hiring manager reading the phrase should be able to picture this exact person applying
- Avoid terms from their exclusion list: {not_open_to}
{remote_rule}- No duplicates or near-duplicates

Candidate profile:
{profile_block}

Search preferences:
  Target roles: {target_roles}
  Open to: {open_to}

Return a JSON array of exactly 8 strings. No other text.\
"""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        return "\n".join(lines[1:end]).strip()
    return stripped


def generate_queries(profile: Profile) -> list[str]:
    remote_rule = (
        "- The candidate is open to fully-remote roles nationally — favour "
        "target-title, adjacent-title, skills-led and seniority angles; do not "
        "narrow to location-bound title variants\n"
        if (profile.remote_uk_wide or profile.remote_hubs) else ""
    )
    prompt = QUERY_GENERATION_PROMPT.format(
        name=profile.name,
        seniority=profile.seniority,
        industry=profile.industry,
        not_open_to=", ".join(profile.not_open_to),
        profile_block=render_profile(profile),
        target_roles=", ".join(profile.target_roles),
        open_to=", ".join(profile.open_to),
        remote_rule=remote_rule,
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
                    queries = json.loads(_strip_code_fence(text))
                except json.JSONDecodeError as exc:
                    print(f"[queries] attempt {attempt}: JSON parse failed: {exc}\nRaw: {text!r}", file=sys.stderr)
                else:
                    if not isinstance(queries, list) or len(queries) != 8:
                        raise ValueError(f"Expected list of 8 strings from Claude, got: {queries!r}")
                    return queries

        if attempt < 3:
            time.sleep(2 ** attempt)

    raise RuntimeError("[queries] generate_queries failed after 3 attempts")
