# Search Plan Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all stub implementations with a working search plan generator that reads a rich candidate profile from `profile.yaml` and uses Claude to produce 8 targeted keyword search strings, plus profile-aware exclusions, NHS band rules, and evaluator notes.

**Architecture:** The plan assembler (`main.py`) orchestrates five focused modules. `Profile` is the shared data contract passed through all of them. `generate_queries` is the only function that calls an external API (Claude via `anthropic` SDK); all others are pure functions. The SHA-256 fingerprint of the full `Profile` gates the cache so Claude is only called when the profile changes.

**Tech Stack:** Python 3.11, PyYAML, anthropic SDK ≥ 0.40, pytest

## Global Constraints

- Python ≥ 3.11
- All tests run via `pytest` from the project root
- No mocking of filesystem — use `tmp_path` fixtures for file I/O
- `ANTHROPIC_API_KEY` must be in the environment for live runs; tests mock the client
- anthropic SDK ≥ 0.40

---

### Task 1: Expand Profile model, profile.yaml, and load_profile

**Files:**
- Modify: `src/job_search_email/models.py`
- Modify: `profile.yaml`
- Modify: `src/job_search_email/main.py` (`load_profile` only)
- Modify: `tests/test_main.py`

**Interfaces:**
- Produces: `Profile` dataclass with 14 fields — consumed by every subsequent task

- [ ] **Step 1: Write failing tests**

Replace the entire content of `tests/test_main.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_search_email.main import (
    fingerprint_profile,
    generate_search_plan,
    load_cached_plan,
    load_profile,
    save_cached_plan,
)
from job_search_email.models import Profile, SearchPlan


PROFILE_YAML = """
profile:
  name: Test User
  current_role: NHS Project Manager
  about: Experienced project manager in NHS.
  seniority: Senior
  industry: NHS / Private Sector
  skills:
    - stakeholder management
    - digital transformation
  previous_roles:
    - Business Manager
    - Project Lead
  target_roles:
    - Programme Manager
    - Digital Lead
  open_to:
    - Strategy Consultant
  not_open_to:
    - clinical roles
    - nursing
  qualifications:
    - MSc Project Management
  employment_type:
    - full-time

location: Bristol
min_salary: 60000
preamble: "Test preamble"
"""


def make_profile() -> Profile:
    return Profile(
        name="Test User",
        current_role="NHS Project Manager",
        about="Experienced project manager in NHS.",
        seniority="Senior",
        industry="NHS / Private Sector",
        skills=["stakeholder management", "digital transformation"],
        previous_roles=["Business Manager", "Project Lead"],
        target_roles=["Programme Manager", "Digital Lead"],
        open_to=["Strategy Consultant"],
        not_open_to=["clinical roles", "nursing"],
        qualifications=["MSc Project Management"],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )


def test_load_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")

    profile = load_profile(path=profile_path)

    assert profile.name == "Test User"
    assert profile.current_role == "NHS Project Manager"
    assert profile.seniority == "Senior"
    assert profile.location == "Bristol"
    assert profile.min_salary == 60000
    assert "clinical roles" in profile.not_open_to
    assert "stakeholder management" in profile.skills
    assert not hasattr(profile, "preamble")


def test_fingerprint_and_cache(tmp_path: Path) -> None:
    profile = make_profile()
    fingerprint = fingerprint_profile(profile)
    plan = generate_search_plan(profile, fingerprint)
    cache_path = tmp_path / "search_plan_cache.json"

    save_cached_plan(plan, cache_path=cache_path)
    cached = load_cached_plan(cache_path=cache_path, fingerprint=fingerprint)

    assert cached is not None
    assert cached["profile_fingerprint"] == fingerprint
    assert len(cached["queries"]) == 8
```

- [ ] **Step 2: Run tests to see them fail**

```
pytest tests/test_main.py -v
```

Expected: FAIL — `Profile.__init__() got an unexpected keyword argument 'current_role'`

- [ ] **Step 3: Update Profile dataclass**

Replace the entire content of `src/job_search_email/models.py`:

```python
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
```

- [ ] **Step 4: Update `load_profile` in `main.py`**

Replace only the `load_profile` function:

```python
def load_profile(path: Path = PROFILE_PATH) -> Profile:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)

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

- [ ] **Step 5: Update `profile.yaml`**

Replace the entire content of `profile.yaml`:

```yaml
profile:
  name: Jie
  current_role: NHS Digital Transformation
  about: |
    Experienced with health care project management, digital transformation and education
    facilities management. Technology and consulting acumen. Works closely with practitioners
    and IT professionals to develop new ways of working in order to improve patient access
    and patient experience. Works with stakeholders such as health providers, and local
    education and training boards to deliver value. Understands and responds to patients
    needs by positioning appropriate solutions and services to meet best outcomes. Sets up
    and leads projects that are vital to patient care being of the highest possible standard.
  seniority: Senior
  industry: NHS / Private Sector / Business
  skills:
    - Analytical Skills
    - digital transformation
    - Digital Marketing
    - Project Initiation and Planning
    - Operations and Supply Chain Decisions and Metrics
    - Business Strategy
  previous_roles:
    - Executive Secretary to the General Manager
    - Business Manager of Research Centre
    - Instructor of Clinical Skills
    - Workforce and Governance Manager for Digital Services
  target_roles:
    - Business Manager
    - Digital Transformation
    - Senior Management
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
    - Digital Marketing (DMS4all)
    - Project Initiation and Planning
    - Project Execution and Control
    - "Leading Teams: Developing as a Leader"
    - "Managerial Accounting: Cost Behaviors, Systems, and Analysis (with Honors)"
    - Operations and Supply Chain Decisions and Metrics
    - Business Strategy
    - Corporate Strategy
    - Masters Strategic Management of Projects
    - Master's degree Management
    - Bachelor of Arts - BA, English Language and Literature, General
  employment_type:
    - full-time

location: Bristol
min_salary: 60000

preamble: "Hey Jie, its The Job Mule. Lets go through todays jobs."
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest tests/test_main.py -v
```

Expected: PASS (all 2 tests)

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/main.py profile.yaml tests/test_main.py
git commit -m "feat: expand Profile model and load_profile for full profile.yaml structure"
```

---

### Task 2: Profile-aware exclusions

**Files:**
- Modify: `src/job_search_email/exclusions.py`
- Modify: `src/job_search_email/main.py` (update `get_exclusions` call in `generate_search_plan`)
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `Profile.not_open_to: list[str]` from Task 1
- Produces: `get_exclusions(profile: Profile) -> dict[str, list[str]]` with keys `"roles"` and `"employment_types"`

- [ ] **Step 1: Write failing tests**

Add to the **import block at the top** of `tests/test_main.py`:

```python
from job_search_email.exclusions import get_exclusions
```

Add to the **bottom** of `tests/test_main.py`:

```python
def test_get_exclusions_merges_not_open_to() -> None:
    profile = make_profile()  # not_open_to: ["clinical roles", "nursing"]
    result = get_exclusions(profile)

    assert "roles" in result
    assert "employment_types" in result
    assert "clinical roles" in result["roles"]
    assert "nursing" in result["roles"]
    assert "locum" in result["roles"]        # from STANDARD_CLINICAL_TERMS
    assert "fixed-term" in result["employment_types"]
    assert "bank" in result["employment_types"]


def test_get_exclusions_deduplicates() -> None:
    profile = make_profile()
    profile.not_open_to.append("locum")     # already in STANDARD_CLINICAL_TERMS
    result = get_exclusions(profile)
    assert result["roles"].count("locum") == 1
```

- [ ] **Step 2: Run tests to see them fail**

```
pytest tests/test_main.py::test_get_exclusions_merges_not_open_to -v
```

Expected: FAIL — `TypeError: get_exclusions() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: Implement `exclusions.py`**

Replace the entire content of `src/job_search_email/exclusions.py`:

```python
from .models import Profile

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


def get_exclusions(profile: Profile) -> dict[str, list[str]]:
    roles = sorted(set(STANDARD_CLINICAL_TERMS + profile.not_open_to))
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
```

- [ ] **Step 4: Update `generate_search_plan` in `main.py`**

Update the `exclusions` line to pass `profile`:

```python
def generate_search_plan(profile: Profile, fingerprint: str) -> SearchPlan:
    return SearchPlan(
        profile_fingerprint=fingerprint,
        queries=generate_queries(profile),
        exclusions=get_exclusions(profile),
        nhs_rules=get_nhs_rules(),
        evaluator_notes=get_evaluator_notes(),
    )
```

- [ ] **Step 5: Run all tests to verify they pass**

```
pytest tests/test_main.py -v
```

Expected: PASS (all 4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/exclusions.py src/job_search_email/main.py tests/test_main.py
git commit -m "feat: make exclusions profile-aware, merge clinical terms with not_open_to"
```

---

### Task 3: Richer NHS rules

**Files:**
- Modify: `src/job_search_email/nhs_rules.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Produces: `get_nhs_rules() -> dict[str, Any]` with keys `"default_floor"`, `"london_remote_floor"`, `"band_salary_map"`, `"rule"`

- [ ] **Step 1: Write failing test**

Add to the **import block at the top** of `tests/test_main.py`:

```python
from job_search_email.nhs_rules import get_nhs_rules
```

Add to the **bottom** of `tests/test_main.py`:

```python
def test_get_nhs_rules_has_salary_map() -> None:
    result = get_nhs_rules()

    assert result["default_floor"] == "Band 8a"
    assert result["london_remote_floor"] == "Band 7"
    assert "band_salary_map" in result
    assert result["band_salary_map"]["Band 8a"] == 53755
    assert result["band_salary_map"]["Band 7"] == 43742
    assert "rule" in result
```

- [ ] **Step 2: Run test to see it fail**

```
pytest tests/test_main.py::test_get_nhs_rules_has_salary_map -v
```

Expected: FAIL — `AssertionError: assert 'Band 8a+' == 'Band 8a'`

- [ ] **Step 3: Implement `nhs_rules.py`**

Replace the entire content of `src/job_search_email/nhs_rules.py`:

```python
from typing import Any


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

- [ ] **Step 4: Run all tests to verify they pass**

```
pytest tests/test_main.py -v
```

Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/nhs_rules.py tests/test_main.py
git commit -m "feat: expand NHS rules with real band salary figures"
```

---

### Task 4: Profile-aware evaluator notes

**Files:**
- Modify: `src/job_search_email/evaluator_notes.py`
- Modify: `src/job_search_email/main.py` (update `get_evaluator_notes` call in `generate_search_plan`)
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `Profile` from Task 1
- Produces: `get_evaluator_notes(profile: Profile) -> list[str]` — 8 scoring notes reflecting the actual candidate

- [ ] **Step 1: Write failing test**

Add to the **import block at the top** of `tests/test_main.py`:

```python
from job_search_email.evaluator_notes import get_evaluator_notes
```

Add to the **bottom** of `tests/test_main.py`:

```python
def test_get_evaluator_notes_is_profile_aware() -> None:
    profile = make_profile()
    notes = get_evaluator_notes(profile)

    assert len(notes) == 8
    assert any("Senior" in note for note in notes)
    assert any("60,000" in note for note in notes)
    assert any("clinical roles" in note for note in notes)
    assert any("Programme Manager" in note or "Digital Lead" in note for note in notes)
```

- [ ] **Step 2: Run test to see it fail**

```
pytest tests/test_main.py::test_get_evaluator_notes_is_profile_aware -v
```

Expected: FAIL — `TypeError: get_evaluator_notes() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: Implement `evaluator_notes.py`**

Replace the entire content of `src/job_search_email/evaluator_notes.py`:

```python
from .models import Profile


def get_evaluator_notes(profile: Profile) -> list[str]:
    return [
        f"Candidate is {profile.seniority} level — reject junior or entry-level roles.",
        f"Target industries: {profile.industry}.",
        f"Minimum salary £{profile.min_salary:,} — reject roles with explicit salary below this.",
        f"Exclude roles matching: {', '.join(profile.not_open_to)}.",
        (
            "For NHS roles: require Band 8a+ unless London-based and remote-friendly "
            "(Band 7+ acceptable)."
        ),
        "Prefer permanent positions — flag contract, locum, bank, or temporary roles.",
        f"Weight highly: {', '.join(profile.skills[:4])}.",
        f"Strong fit signals: {', '.join(profile.target_roles + profile.open_to)}.",
    ]
```

- [ ] **Step 4: Update `generate_search_plan` in `main.py`**

Update the `evaluator_notes` line to pass `profile`:

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

- [ ] **Step 5: Run all tests to verify they pass**

```
pytest tests/test_main.py -v
```

Expected: PASS (all 6 tests)

- [ ] **Step 6: Commit**

```bash
git add src/job_search_email/evaluator_notes.py src/job_search_email/main.py tests/test_main.py
git commit -m "feat: make evaluator notes profile-aware"
```

---

### Task 5: Query generation with Claude API

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/job_search_email/queries.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `Profile` from Task 1
- Produces: `generate_queries(profile: Profile) -> list[str]` — 8 keyword strings via Claude; `client` module-level `anthropic.Anthropic()` instance (patched in tests)

- [ ] **Step 1: Add anthropic to dependencies**

In `pyproject.toml`, update the `dependencies` line:

```toml
dependencies = ["PyYAML>=6.0", "anthropic>=0.40"]
```

Then install:

```
pip install -e ".[test]"
```

- [ ] **Step 2: Write failing tests**

Add to the **import block at the top** of `tests/test_main.py`:

```python
from job_search_email.queries import generate_queries
```

Add to the **bottom** of `tests/test_main.py`:

```python
def test_generate_queries_returns_eight_strings() -> None:
    mock_queries = [
        "Business Manager digital transformation NHS",
        "Senior Programme Manager healthcare",
        "Digital Transformation Lead NHS",
        "Strategy Consultant digital health",
        "Operations Manager NHS senior",
        "Workforce Governance Manager digital",
        "Project Planning Manager NHS",
        "Head of Digital Services NHS",
    ]
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(mock_queries))]

    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        result = generate_queries(make_profile())

    assert len(result) == 8
    assert all(isinstance(q, str) for q in result)
    assert result[0] == "Business Manager digital transformation NHS"


def test_generate_queries_prompt_includes_exclusions() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(["q"] * 8))]

    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        generate_queries(make_profile())
        prompt_content = mock_client.messages.create.call_args[1]["messages"][0]["content"]

    assert "clinical roles" in prompt_content
    assert "nursing" in prompt_content
```

**Replace** the existing `test_fingerprint_and_cache` function in `tests/test_main.py` with this version that mocks Claude (the stub `generate_queries` is now a real API call):

```python
def test_fingerprint_and_cache(tmp_path: Path) -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([f"query {i}" for i in range(8)]))]

    profile = make_profile()
    fingerprint = fingerprint_profile(profile)

    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        plan = generate_search_plan(profile, fingerprint)

    cache_path = tmp_path / "search_plan_cache.json"
    save_cached_plan(plan, cache_path=cache_path)
    cached = load_cached_plan(cache_path=cache_path, fingerprint=fingerprint)

    assert cached is not None
    assert cached["profile_fingerprint"] == fingerprint
    assert len(cached["queries"]) == 8
```

- [ ] **Step 3: Run tests to see them fail**

```
pytest tests/test_main.py::test_generate_queries_returns_eight_strings -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'anthropic'` (before install) or stub returns wrong strings

- [ ] **Step 4: Implement `queries.py`**

Replace the entire content of `src/job_search_email/queries.py`:

```python
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
    return json.loads(response.content[0].text)
```

- [ ] **Step 5: Run all tests to verify they pass**

```
pytest tests/test_main.py -v
```

Expected: PASS (all 8 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/job_search_email/queries.py tests/test_main.py
git commit -m "feat: implement query generation using Claude API (claude-haiku-4-5-20251001)"
```
