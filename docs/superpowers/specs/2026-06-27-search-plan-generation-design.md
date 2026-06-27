---
title: Search Plan Generation — Design Spec
date: 2026-06-27
branch: feature/FE-001-search-plan-generation
---

# Search Plan Generation — Design Spec

## Overview

Phase 0 of the job-search-email pipeline. Reads a candidate profile from `profile.yaml`, uses Claude to generate 8 targeted keyword search strings, assembles a `SearchPlan` containing those queries plus exclusion rules, NHS band rules, and evaluator guidance, then caches the plan keyed on a fingerprint of the profile so it only regenerates when the profile changes.

The plan is the input to all downstream phases (job fetching, filtering, scoring, email). Nothing downstream runs without it.

---

## Files Changed

| File | Change |
|---|---|
| `src/job_search_email/models.py` | Expand `Profile` dataclass to match full `profile.yaml` structure |
| `src/job_search_email/main.py` | Update `load_profile` to parse nested `profile:` block |
| `src/job_search_email/queries.py` | Real Claude API call replacing stub |
| `src/job_search_email/exclusions.py` | Profile-aware exclusion builder with real clinical terms |
| `src/job_search_email/nhs_rules.py` | Expanded with real band salary figures |
| `src/job_search_email/evaluator_notes.py` | Profile-aware evaluator notes |
| `profile.yaml` | Expanded to full candidate profile structure |
| `pyproject.toml` | Add `anthropic` to dependencies |

---

## 1. Profile Model

### `profile.yaml` structure

```yaml
profile:
  name: Jie
  current_role: NHS Digital Transformation
  about: |
    Free-text background paragraph...
  seniority: Senior
  industry: NHS / Private Sector / Business
  skills:
    - Analytical Skills
    - digital transformation
  previous_roles:
    - Executive Secretary to the General Manager
  target_roles:
    - Business Manager
    - Digital Transformation
  open_to:
    - Strategy Consultant
    - Project Planning
  not_open_to:
    - clinical roles
    - nursing
    - GP / medical practitioner
    - ward-based roles
    - surgical / theatre roles
  qualifications:
    - Masters Strategic Management of Projects
  employment_type:
    - full-time

location: Bristol
min_salary: 60000
preamble: "Hey Jie, its The Job Mule. Lets go through todays jobs."
```

`preamble` is email presentation only — it is not read into `Profile` and does not affect the plan fingerprint.

### `Profile` dataclass (`models.py`)

```python
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
```

### `load_profile` (`main.py`)

Reads the nested `profile:` block for candidate fields; reads top-level `location` and `min_salary` separately. `preamble` is ignored.

```python
def load_profile(path: Path = PROFILE_PATH) -> Profile:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    p = data["profile"]
    return Profile(
        name=p["name"],
        current_role=p.get("current_role", ""),
        about=p.get("about", ""),
        seniority=p.get("seniority", ""),
        industry=p.get("industry", ""),
        skills=p.get("skills", []),
        previous_roles=p.get("previous_roles", []),
        target_roles=p.get("target_roles", []),
        open_to=p.get("open_to", []),
        not_open_to=p.get("not_open_to", []),
        qualifications=p.get("qualifications", []),
        employment_type=p.get("employment_type", []),
        location=data.get("location", ""),
        min_salary=data.get("min_salary", 0),
    )
```

---

## 2. Query Generation (`queries.py`)

### Approach

Single Claude API call. The prompt is a named string constant at the top of the file — the thing to edit when tuning. Claude returns a JSON array of exactly 8 keyword strings. No location in the strings — location is passed separately by all three search sources (Reed, jobspy/LinkedIn+Indeed, NHS Jobs scraper).

### Prompt constant

```python
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

Return a JSON array of exactly 8 strings. No other text.
"""
```

### API call

```python
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
    return json.loads(response.content[0].text)
```

Model: `claude-haiku-4-5-20251001` — sufficient for structured generation at this prompt complexity; swap to `claude-sonnet-4-6` if query quality needs more nuance.

### Expected output for Jie's profile

```json
[
  "Business Manager digital transformation NHS",
  "Senior Programme Manager healthcare",
  "Digital Transformation Lead NHS private",
  "Strategy Consultant digital healthcare",
  "Operations Manager NHS senior",
  "Workforce Governance Manager digital",
  "Project Planning Manager NHS",
  "Head of Digital Services NHS"
]
```

---

## 3. Exclusions (`exclusions.py`)

Accepts the profile so it can merge the standard clinical term list with the candidate's `not_open_to` list. Employment type exclusions are hardcoded — they cover the standard non-permanent types regardless of profile.

```python
STANDARD_CLINICAL_TERMS = [
    "locum", "GP", "surgeon", "nurse", "clinical", "surgical",
    "physician", "dentist", "pharmacist", "physiotherapist",
    "radiographer", "midwife", "paramedic", "theatre", "ward",
    "medical officer", "occupational therapist",
]

def get_exclusions(profile: Profile) -> dict[str, list[str]]:
    roles = sorted(set(STANDARD_CLINICAL_TERMS + profile.not_open_to))
    employment = ["locum", "fixed-term", "temporary", "bank", "agency", "casual", "zero-hours"]
    return {"roles": roles, "employment_types": employment}
```

---

## 4. NHS Rules (`nhs_rules.py`)

Expanded with real 2024/25 band salary figures so the downstream scorer has numbers to reason against, not just band labels.

```python
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
```

---

## 5. Evaluator Notes (`evaluator_notes.py`)

Profile-aware. Accepts the profile so notes reflect the actual candidate's seniority, salary floor, exclusion list, and skills. Used by the AI scorer in the downstream evaluation phase.

```python
def get_evaluator_notes(profile: Profile) -> list[str]:
    return [
        f"Candidate is {profile.seniority} level — reject junior or entry-level roles.",
        f"Target industries: {profile.industry}.",
        f"Minimum salary £{profile.min_salary:,} — reject roles with explicit salary below this.",
        f"Exclude roles matching: {', '.join(profile.not_open_to)}.",
        "For NHS roles: require Band 8a+ unless London-based and remote-friendly (Band 7+ acceptable).",
        "Prefer permanent positions — flag contract, locum, bank, or temporary roles.",
        f"Weight highly: {', '.join(profile.skills[:4])}.",
        f"Strong fit signals: {', '.join(profile.target_roles + profile.open_to)}.",
    ]
```

---

## 6. Plan Assembly (`main.py`)

`generate_search_plan` passes the profile through to the three functions that now need it:

```python
def generate_search_plan(profile: Profile, fingerprint: str) -> SearchPlan:
    return SearchPlan(
        profile_fingerprint=fingerprint,
        queries=generate_queries(profile),
        exclusions=get_exclusions(profile),
        nhs_rules=get_nhs_rules(),
        evaluator_notes=get_evaluator_notes(profile),
    )
```

The caching and fingerprinting logic in `main.py` is unchanged — the fingerprint covers the full expanded `Profile` object so any change to the profile (including `not_open_to`, `min_salary`, etc.) invalidates the cache.

---

## 7. Caching Behaviour

| Scenario | Result |
|---|---|
| No cache file | Generate plan, write cache and `search_plan.json` |
| Cache hit (fingerprint matches) | Load from cache, skip Claude call |
| Cache miss (profile changed) | Regenerate plan, update cache entry, overwrite `search_plan.json` |
| `ANTHROPIC_API_KEY` not set | `anthropic.AuthenticationError` raised — fail loudly |
| Claude returns invalid JSON | `json.JSONDecodeError` propagated — fail loudly |

---

## 8. Dependencies

Add to `pyproject.toml`:

```toml
dependencies = ["PyYAML>=6.0", "anthropic>=0.40"]
```

---

## Out of Scope

- Prompt evaluation framework or A/B testing of query variants
- Per-profile prompt customisation via `profile.yaml`
- Downstream job fetching, filtering, scoring, or email formatting
- Multiple profiles or profile switching
