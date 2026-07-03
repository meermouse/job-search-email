# Enhanced LinkedIn-Style Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape `profile.yaml` into a LinkedIn-style profile (structured experience, education, certifications, languages) and wire the richer detail into the query-generation and job-scoring prompts.

**Architecture:** New nested dataclasses (`ExperienceEntry`, `EducationEntry`) on `Profile`; a new `src/job_search_email/profile.py` module holding one shared `load_profile` (replacing duplicates in `main.py`/`local_run.py`) and one `render_profile` text renderer consumed by the LLM prompts. Legacy fields (`current_role`, `previous_roles`, `qualifications`) are kept temporarily with the new fields added alongside, then removed in the final task so the test suite stays green after every task.

**Tech Stack:** Python 3.11, PyYAML, pytest, dataclasses. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-03-enhanced-linkedin-profile-design.md`

## Global Constraints

- Python >= 3.11; dependencies limited to those already in `pyproject.toml`.
- Run tests with `python -m pytest -q` from the repo root; the full suite must pass at the end of every task.
- All LLM-calling tests mock `client` — never make live API calls in tests.
- The profile fingerprint (`cache.fingerprint_profile`) uses `asdict(profile)`; no cache migration is needed — schema changes create new fingerprints automatically.
- `assets/Profile.pdf` (untracked) is the content source; it must be deleted in Task 4 and never committed.
- Commit after every task with the message given in the task.

---

### Task 1: Shared test profile factory

Every schema change currently requires editing 14 test files that construct `Profile` by hand. Centralise construction in one factory first (no production changes, no behavior changes), so later tasks touch one place.

**Files:**
- Create: `tests/profile_helpers.py`
- Modify: `tests/test_filter.py`, `tests/test_filter_trace.py`, `tests/test_cache.py`, `tests/test_main.py`, `tests/test_scorer.py`, `tests/test_email.py`, `tests/test_debug_email.py`, `tests/test_debug_run.py`, `tests/test_explain_job.py`, `tests/test_explain_scorer_seam.py`, `tests/search_api/test_fetcher.py`, `tests/search_api/test_nhs_jobs.py`, `tests/search_api/test_jobspy_searcher.py`, `tests/search_api/test_reed.py`

**Interfaces:**
- Produces: `make_profile(**overrides) -> Profile` in `tests/profile_helpers.py`. All later tasks' tests import it as `from profile_helpers import make_profile` (works from both `tests/` and `tests/search_api/` because pytest inserts `tests/` on `sys.path` — `tests/` has no `__init__.py`, `tests/search_api/` does).

- [ ] **Step 1: Create the factory**

```python
# tests/profile_helpers.py
from job_search_email.models import Profile


def make_profile(**overrides) -> Profile:
    kwargs = dict(
        name="Test",
        current_role="Manager",
        about="",
        seniority="Senior",
        industry="NHS",
        skills=[],
        previous_roles=[],
        target_roles=[],
        open_to=[],
        not_open_to=[],
        qualifications=[],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )
    kwargs.update(overrides)
    return Profile(**kwargs)
```

- [ ] **Step 2: Migrate every hand-built Profile to the factory**

In each file add `from profile_helpers import make_profile` (rename the import if the file defines its own `make_profile`) and replace the constructions. Keep only overrides that differ from the factory defaults — the tests do not assert on the dropped values:

- `tests/test_filter_trace.py` — `_profile()` body becomes `return make_profile()`.
- `tests/test_filter.py` — `make_profile_stub()` body becomes `return make_profile()`; the two inline `Profile(...)` constructions (~lines 493, 516) become `make_profile(min_salary=0)`.
- `tests/test_cache.py` — delete the local `make_profile` and its `Profile` import; replace with:

```python
from profile_helpers import make_profile as _shared_profile


def make_profile(**kwargs) -> Profile:
    defaults = dict(skills=["python"], target_roles=["Lead"])
    defaults.update(kwargs)
    return _shared_profile(**defaults)
```

  (keep the `Profile` import — the annotation still uses it).
- `tests/test_main.py` — delete the local `make_profile()` function and use the shared import instead. It is only used by fingerprint/cache tests that don't assert on field values.
- `tests/test_scorer.py` — local `make_profile()` body becomes:

```python
def make_profile() -> Profile:
    return _shared_profile(
        skills=["digital transformation"], target_roles=["Business Manager"],
        not_open_to=["clinical roles"], qualifications=["MSc Management"],
    )
```

  with `from profile_helpers import make_profile as _shared_profile` at the top.
- `tests/test_explain_scorer_seam.py` — its profile helper becomes `make_profile(skills=["delivery"], target_roles=["Project Manager"], qualifications=["MSc"])`.
- `tests/test_email.py` — `_make_profile(**kwargs)` keeps its signature but delegates:

```python
def _make_profile(**kwargs) -> Profile:
    defaults = dict(
        name="Jie", employment_type=[],
        preamble="Hey Jie!", recipient_email="jie@example.com",
    )
    defaults.update(kwargs)
    return make_profile(**defaults)
```

- `tests/test_debug_email.py` — its helper becomes `make_profile(name="Jie", seniority="", industry="", employment_type=[])` (simplify to `make_profile(name="Jie", employment_type=[])` — no test asserts seniority/industry).
- `tests/test_debug_run.py` — its helper becomes `make_profile()`.
- `tests/test_explain_job.py` — its helper becomes `make_profile()`.
- `tests/search_api/test_fetcher.py`, `test_nhs_jobs.py`, `test_jobspy_searcher.py`, `test_reed.py` — each module-level `PROFILE = Profile(...)` becomes `PROFILE = make_profile(name="Jie")`. (Reed tests assert `locationName == "Bristol"` and `minimumSalary == 60000` — both factory defaults.)

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass (same count as before the change).

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: centralise Profile construction in shared make_profile factory"
```

---

### Task 2: New profile schema (models) + shared loader

Add the LinkedIn-shaped dataclasses and fields (keeping legacy fields for now so nothing breaks), and create the single shared YAML loader with tests. Production code does not use the new module yet.

**Files:**
- Modify: `src/job_search_email/models.py`
- Create: `src/job_search_email/profile.py`
- Create: `tests/test_profile.py`

**Interfaces:**
- Produces: `ExperienceEntry(title, company, start, end, location="", description="")` and `EducationEntry(institution, degree)` dataclasses in `models.py`; `Profile` gains `headline: str = ""`, `experience: list[ExperienceEntry]`, `education: list[EducationEntry]`, `certifications: list[str]`, `languages: list[str]` (all defaulted). `load_profile(path: Path) -> Profile` in `job_search_email.profile`.
- Consumes: nothing from earlier tasks (the factory keeps working — new fields all have defaults).

- [ ] **Step 1: Write failing loader tests**

```python
# tests/test_profile.py
from pathlib import Path

from job_search_email.models import EducationEntry, ExperienceEntry
from job_search_email.profile import load_profile

FULL_YAML = """\
profile:
  name: Jie Zhou
  headline: "NHS Digital Transformation | Business Governance"
  about: |
    Governance meets data.
  seniority: Senior
  industry: NHS / Healthcare
  experience:
    - title: Workforce and Governance Manager
      company: Swansea Bay University Health Board
      location: United Kingdom
      start: "2023-09"
      end: present
      description: |
        Leads business governance.
        Owns the Risk Register.
    - title: Co-Founder
      company: Guangxian Education
      start: "2019-01"
      end: "2021-07"
  education:
    - institution: UCL
      degree: Masters, Strategic Management of Projects
  certifications:
    - Corporate Strategy
  skills:
    - SharePoint
  languages:
    - English (Native or Bilingual)
  target_roles:
    - Business Manager
  open_to:
    - Strategy Consultant
  not_open_to:
    - clinical roles
  employment_type:
    - full-time

location: Bristol
radius_miles: 40
min_salary: 60000
preamble: "Hi"
recipient_email: jie@example.com
send_main_email: false
send_debug_email: true
filter_recruitment: true
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "profile.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_profile_parses_linkedin_sections(tmp_path):
    profile = load_profile(_write(tmp_path, FULL_YAML))
    assert profile.name == "Jie Zhou"
    assert profile.headline == "NHS Digital Transformation | Business Governance"
    assert "Governance meets data." in profile.about
    assert profile.experience[0] == ExperienceEntry(
        title="Workforce and Governance Manager",
        company="Swansea Bay University Health Board",
        start="2023-09",
        end="present",
        location="United Kingdom",
        description="Leads business governance.\nOwns the Risk Register.",
    )
    assert profile.experience[1].description == ""
    assert profile.experience[1].location == ""
    assert profile.education == [
        EducationEntry(institution="UCL", degree="Masters, Strategic Management of Projects")
    ]
    assert profile.certifications == ["Corporate Strategy"]
    assert profile.skills == ["SharePoint"]
    assert profile.languages == ["English (Native or Bilingual)"]
    assert profile.target_roles == ["Business Manager"]
    assert profile.location == "Bristol"
    assert profile.radius_miles == 40
    assert profile.min_salary == 60000
    assert profile.preamble == "Hi"
    assert profile.recipient_email == "jie@example.com"
    assert profile.send_main_email is False
    assert profile.send_debug_email is True
    assert profile.filter_recruitment is True


def test_load_profile_defaults_missing_optional_sections(tmp_path):
    minimal = "profile:\n  name: Test\nlocation: Bristol\nmin_salary: 0\n"
    profile = load_profile(_write(tmp_path, minimal))
    assert profile.headline == ""
    assert profile.about == ""
    assert profile.experience == []
    assert profile.education == []
    assert profile.certifications == []
    assert profile.languages == []
    assert profile.skills == []
    assert profile.employment_type == []
    assert profile.radius_miles == 50
    assert profile.send_main_email is True
    assert profile.filter_recruitment is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_search_email.profile'` (or ImportError for `ExperienceEntry`).

- [ ] **Step 3: Add dataclasses to models.py**

In `src/job_search_email/models.py`, add above `Profile`:

```python
@dataclass
class ExperienceEntry:
    title: str
    company: str
    start: str
    end: str  # "present" for current roles
    location: str = ""
    description: str = ""


@dataclass
class EducationEntry:
    institution: str
    degree: str
```

Change `Profile` to (legacy fields kept for now; new fields defaulted and placed after `min_salary` so dataclass default ordering stays valid):

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
    headline: str = ""
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    radius_miles: int = 50
    preamble: str = ""
    recipient_email: str = ""
    send_main_email: bool = True
    send_debug_email: bool = False
    filter_recruitment: bool = True
```

(`field` is already imported in models.py.)

- [ ] **Step 4: Create the loader**

```python
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
```

Note: `current_role`, `previous_roles`, `qualifications` are deliberately loaded as empty — the new schema does not carry them, and they are removed entirely in Task 8.

Note on `about`: the loader strips it, so the FULL_YAML test asserts with `in` rather than exact match.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_profile.py -q`
Expected: 2 passed.

- [ ] **Step 6: Run the full suite (nothing else should break)**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/profile.py tests/test_profile.py
git commit -m "feat: add LinkedIn-shaped profile schema and shared loader"
```

---

### Task 3: Profile renderer

One function that renders the profile into the consistent text block used by the LLM prompts.

**Files:**
- Modify: `src/job_search_email/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `Profile`, `ExperienceEntry`, `EducationEntry` from Task 2; `make_profile` from Task 1.
- Produces: `render_profile(profile: Profile) -> str` in `job_search_email.profile`. Output format (asserted by tests, relied on by Tasks 5–6):
  - `Name: <name>` / `Headline: <headline>`
  - `About:` block
  - `Current role: <title> at <company>` (first experience entry whose `end == "present"`)
  - `Experience:` bullets `- <title> — <company> (<start> – <end>[, <location>])` with description lines indented two spaces
  - `Education:` bullets `- <degree> — <institution>`
  - `Certifications:` bullets
  - `Skills: a, b, c` and `Languages: a, b` single lines
  - Empty sections are omitted entirely.

- [ ] **Step 1: Write failing renderer tests (append to tests/test_profile.py)**

```python
from profile_helpers import make_profile

from job_search_email.profile import render_profile


def _rich_profile():
    return make_profile(
        name="Jie Zhou",
        headline="NHS Digital Transformation",
        about="Governance meets data.",
        experience=[
            ExperienceEntry(
                title="Governance Manager", company="Swansea Bay UHB",
                start="2023-09", end="present", location="United Kingdom",
                description="Leads governance.\nBuilds dashboards.",
            ),
            ExperienceEntry(
                title="Co-Founder", company="Guangxian Education",
                start="2019-01", end="2021-07",
            ),
        ],
        education=[EducationEntry(institution="UCL", degree="Masters, Strategic Management of Projects")],
        certifications=["Corporate Strategy"],
        skills=["SharePoint", "Power BI"],
        languages=["English", "Chinese"],
    )


def test_render_profile_includes_all_sections():
    text = render_profile(_rich_profile())
    assert "Name: Jie Zhou" in text
    assert "Headline: NHS Digital Transformation" in text
    assert "Governance meets data." in text
    assert "Current role: Governance Manager at Swansea Bay UHB" in text
    assert "- Governance Manager — Swansea Bay UHB (2023-09 – present, United Kingdom)" in text
    assert "  Leads governance." in text
    assert "  Builds dashboards." in text
    assert "- Co-Founder — Guangxian Education (2019-01 – 2021-07)" in text
    assert "- Masters, Strategic Management of Projects — UCL" in text
    assert "- Corporate Strategy" in text
    assert "Skills: SharePoint, Power BI" in text
    assert "Languages: English, Chinese" in text


def test_render_profile_omits_empty_sections():
    text = render_profile(make_profile(name="Test", about=""))
    assert text.startswith("Name: Test")
    assert "Headline:" not in text
    assert "About:" not in text
    assert "Current role:" not in text
    assert "Experience:" not in text
    assert "Education:" not in text
    assert "Certifications:" not in text
    assert "Skills:" not in text
    assert "Languages:" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_profile'`.

- [ ] **Step 3: Implement render_profile (append to src/job_search_email/profile.py)**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_profile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/profile.py tests/test_profile.py
git commit -m "feat: add render_profile text block for LLM prompts"
```

---

### Task 4: Switch the app to the shared loader and rewrite profile.yaml

Replace both duplicate loaders with `job_search_email.profile.load_profile`, rewrite `profile.yaml` in the new schema with the content transcribed from the LinkedIn PDF, and delete the PDF.

**Files:**
- Modify: `src/job_search_email/main.py`, `src/job_search_email/local_run.py`, `src/job_search_email/explain_job.py`, `src/job_search_email/debug_run.py`, `tests/test_main.py`, `profile.yaml`
- Delete: `assets/Profile.pdf` (untracked — plain file delete, no git rm)

**Interfaces:**
- Consumes: `load_profile(path)` from Task 2.
- Produces: `main.py` no longer defines `load_profile`; all entry points import it from `job_search_email.profile`. `profile.yaml` is in the new schema.

- [ ] **Step 1: Update failing tests first (tests/test_main.py)**

1. Change the import block: remove `load_profile` from the `job_search_email.main` import and add `from job_search_email.profile import load_profile`.
2. Replace `PROFILE_YAML` with the new schema:

```python
PROFILE_YAML = """
profile:
  name: Test User
  headline: "NHS Project Manager | Digital"
  about: Experienced project manager in NHS.
  seniority: Senior
  industry: NHS / Private Sector
  experience:
    - title: NHS Project Manager
      company: Test Trust
      start: "2022-01"
      end: present
      description: Delivers digital projects.
  education:
    - institution: Test University
      degree: MSc Project Management
  certifications:
    - PRINCE2
  skills:
    - stakeholder management
    - digital transformation
  languages:
    - English
  target_roles:
    - Programme Manager
    - Digital Lead
  open_to:
    - Strategy Consultant
  not_open_to:
    - clinical roles
    - nursing
  employment_type:
    - full-time

location: Bristol
min_salary: 60000
preamble: "Test preamble"
"""
```

3. Update `test_load_profile` assertions: replace `assert profile.current_role == "NHS Project Manager"` with:

```python
    assert profile.headline == "NHS Project Manager | Digital"
    assert profile.experience[0].company == "Test Trust"
    assert profile.experience[0].end == "present"
    assert profile.education[0].institution == "Test University"
    assert profile.certifications == ["PRINCE2"]
```

4. Replace both inline minimal-profile YAML strings (in the pipeline test around line 316 and in `_run_main_with_toggles` around line 425) with the minimal new-schema equivalent — the loader defaults everything else:

```python
        "profile:\n  name: Test\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n"
```

(keep the `send_main_email`/`send_debug_email` suffix lines in `_run_main_with_toggles` unchanged).

- [ ] **Step 2: Run test_main.py**

Run: `python -m pytest tests/test_main.py -q`
Expected: PASS — the updated tests import the Task 2 loader directly, and the pipeline tests tolerate the old loader reading new-format YAML (missing keys default to empty). This task is a refactor plus content change, not new behavior; the deliverable check is Step 5's parse of the real profile.yaml.

- [ ] **Step 3: Switch production code to the shared loader**

- `src/job_search_email/main.py`:
  - Delete the whole `load_profile` function and the `import yaml` line.
  - Add `from .profile import load_profile` to the imports.
  - `main()` already calls `load_profile(PROFILE_PATH)` — unchanged.
- `src/job_search_email/local_run.py`:
  - Delete `_load_profile` and the `import yaml` line; add `from .profile import load_profile`; change the call in `main()` to `profile = load_profile(root / "profile.yaml")`.
- `src/job_search_email/explain_job.py`:
  - Change `from .main import SPONSOR_CACHE_PATH, load_profile` to two lines: `from .main import SPONSOR_CACHE_PATH` and `from .profile import load_profile`.
- `src/job_search_email/debug_run.py`:
  - Change `from .main import PROFILE_PATH, load_profile, run_pipeline` to `from .main import PROFILE_PATH, run_pipeline` plus `from .profile import load_profile`.

- [ ] **Step 4: Rewrite profile.yaml with the transcribed LinkedIn content**

Replace the entire file with:

```yaml
profile:
  name: Jie Zhou
  headline: "NHS Digital Transformation | Strategic Workforce Planning | Business Governance | UCL"
  about: |
    I work where governance meets data — managing governance frameworks, workforce planning, and policy while building the digital infrastructure that makes them actually useful.
    My career has spanned NHS Wales, an NHS Foundation Trust, and an international private hospital in China. In every setting, I have solved the same problem: governance, day-to-day operating and reporting that are manual, fragmented, and hard to act on.
    I fix it by implementing systems people can trust. By combining end-to-end project management with direct line management, I build high-performing teams. By bridging the gap between strict statutory compliance and digital innovation — specifically leveraging Power BI and automated data infrastructures — I transform legacy manual governance processes into streamlined, actionable operations.
  seniority: Senior
  industry: NHS / Healthcare / Business

  experience:
    - title: Workforce and Governance Manager for Digital Services
      company: Swansea Bay University Health Board
      location: United Kingdom
      start: "2023-09"
      end: present
      description: |
        1. Governance, Committees & Assurance Reporting
        - Leads business governance and workforce planning — owning the governance framework, policies and processes, ensuring compliance with statutory requirements, national policy and internal standards, and providing expert advice to senior management.
        - Owns and runs the governance arrangements end-to-end: Risk Register, incident and complaint, FOIA, audit responses and policy management. Maintains a single, consistent governance framework across the function.
        - Builds dashboards to analyse workforce and governance data to identify risks and trends, producing reports for the Senior Leaders, Business Meeting, Digital Leadership Group, and Audit Committee to support decision-making, contributing to board-level governance assurance.
        2. Infrastructure Design & Data Analytics
        - Architects and maintains the Directorate's infrastructure for records, repositories and data, to be compliant with the Health Board's information governance and cyber security policies — embedding access controls, version control and audit trails by design.
        - Initiated and leads the digitisation and re-designing of the governance reporting processes by replacing manual document-based processes with automated Power BI dashboards, Power Automate and a structured SharePoint data infrastructure, improving data accuracy, security and leadership visibility of risk.
        3. Policy Management & Regulatory Compliance
        - Manages the Directorate's policy framework in line with the Health Board's Policy on Policies — ensuring all policies are reviewed, updated and kept current against review cycles and legislative framework.
        - Coordinates responses to internal and external audit, monitoring outstanding recommendations through to completion and providing assurance on consistency and timeliness.
        4. Line management & stakeholder engagement
        - Provides line management to staff and maintains effective relationships with stakeholders including service directors and other NHS bodies.
    - title: Instructor of Clinical Skills
      company: Zhejiang University
      start: "2020-01"
      end: present
      description: |
        Responsible for the training of medical students; evaluates students' practical application of clinical skills, proficiency in required techniques, quality of communication, and ability to deliver high quality care.
    - title: Business Manager of Research Centre in Mental Health
      company: Cheshire & Wirral Partnership NHS Foundation Trust
      location: United Kingdom
      start: "2022-04"
      end: "2023-09"
      description: |
        1. Governance & Reporting & Financial Control
        - Owned risk management, project governance, and performed as the department budget holder to manage budget control across a portfolio of academic and research projects, defining change-control processes and ensuring delivery against scope, deadlines and the Trust's Standing Financial Instructions.
        - Prepared and presented regular progress and performance reports to senior stakeholders and funders, supporting decision-making and oversight.
        - Provided operational governance and business management to a complex mental-health and neurodevelopmental research centre, advising senior leadership and coordinating a network of clinical, academic and partner organisations.
        2. Digital Transformation & Improvement
        - Led cross-disciplinary teams to deliver projects end-to-end, identifying improvements to how teams worked; introduced collaborative digital platforms and remote-working tools that cut coordination and administrative workload by 50%.
        3. Operational & Stakeholder Management
        - Provided operational leadership across workforce, planning and service delivery, and managed relationships with a complex network of clinical, academic and partner organisations across the Northwest region.
        - Line-managed department and project teams in line with Trust policy, with responsibility for recruitment, retention and appraisals.
    - title: Executive Secretary to the General Manager
      company: American-Sino Healthcare
      location: China
      start: "2018-01"
      end: "2021-08"
      description: |
        Operational management of acute medical services. Responsibilities include digital transformation, project management, workforce management, finance oversight, hospital information systems and service improvement & redesign.
    - title: Co-Founder
      company: Guangxian Education
      start: "2019-01"
      end: "2021-07"

  education:
    - institution: UCL
      degree: Masters, Strategic Management of Projects
    - institution: University of Illinois Urbana-Champaign
      degree: Master's degree, Management
    - institution: Zhejiang University
      degree: Bachelor of Arts (BA), English Language and Literature

  certifications:
    - Operations and Supply Chain Decisions and Metrics
    - "Managerial Accounting: Cost Behaviors, Systems, and Analysis (with Honors)"
    - Corporate Strategy
    - "Leading Teams: Developing as a Leader"
    - Digital Marketing (DMS4all)

  skills:
    - SharePoint
    - Microsoft Power Automate
    - Microsoft Power BI
    - Digital Transformation
    - Workforce Planning
    - Business Governance
    - Project Management
    - Data Analytics / Dashboards

  languages:
    - English (Native or Bilingual)
    - Chinese (Native or Bilingual)
    - Japanese (Elementary)
    - French (Elementary)

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
  employment_type:
    - full-time

location: Bristol
radius_miles: 40
min_salary: 60000

preamble: "Hey Jie, its The Job Mule 2.0. Lets go through todays jobs."
recipient_email: jillcn@hotmail.com
send_main_email: false
send_debug_email: false
filter_recruitment: true
```

- [ ] **Step 5: Sanity-check the real profile.yaml parses**

Run: `python -c "from pathlib import Path; from job_search_email.profile import load_profile, render_profile; p = load_profile(Path('profile.yaml')); print(render_profile(p)[:400]); assert len(p.experience) == 5 and len(p.education) == 3"`
Expected: prints the rendered header, no assertion error.

- [ ] **Step 6: Delete the PDF and run the full suite**

Delete `assets/Profile.pdf` (plain filesystem delete — it is untracked).

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/main.py src/job_search_email/local_run.py src/job_search_email/explain_job.py src/job_search_email/debug_run.py tests/test_main.py profile.yaml
git commit -m "feat: adopt shared profile loader and LinkedIn-style profile.yaml"
```

---

### Task 5: Wire renderer into query generation

**Files:**
- Modify: `src/job_search_email/queries.py`
- Test: `tests/test_queries.py`

**Interfaces:**
- Consumes: `render_profile` from Task 3; `make_profile` from Task 1.
- Produces: `generate_queries(profile)` unchanged signature; the prompt now embeds the rendered profile block.

- [ ] **Step 1: Write failing prompt test (append to tests/test_queries.py)**

```python
import json
from unittest.mock import MagicMock, patch

from profile_helpers import make_profile

from job_search_email.models import ExperienceEntry
from job_search_email.queries import generate_queries


def test_generate_queries_prompt_contains_rendered_profile():
    profile = make_profile(
        headline="NHS Digital Transformation",
        experience=[ExperienceEntry(
            title="Governance Manager", company="Swansea Bay UHB",
            start="2023-09", end="present",
        )],
        target_roles=["Business Manager"],
        open_to=["Strategy Consultant"],
        not_open_to=["nursing"],
    )
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([f"q{i}" for i in range(8)]))]
    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        generate_queries(profile)
    prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Headline: NHS Digital Transformation" in prompt
    assert "- Governance Manager — Swansea Bay UHB (2023-09 – present)" in prompt
    assert "Target roles: Business Manager" in prompt
    assert "nursing" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_queries.py -q`
Expected: FAIL — `assert "Headline: ..." in prompt` (old prompt has no Headline line).

- [ ] **Step 3: Rewire the prompt**

In `src/job_search_email/queries.py`, add `from .profile import render_profile` and replace `QUERY_GENERATION_PROMPT` and the `format(...)` call:

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
{profile_block}

Search preferences:
  Target roles: {target_roles}
  Open to: {open_to}

Return a JSON array of exactly 8 strings. No other text.\
"""
```

```python
    prompt = QUERY_GENERATION_PROMPT.format(
        name=profile.name,
        seniority=profile.seniority,
        not_open_to=", ".join(profile.not_open_to),
        profile_block=render_profile(profile),
        target_roles=", ".join(profile.target_roles),
        open_to=", ".join(profile.open_to),
    )
```

(The rendered block is passed as a format *argument*, so braces inside profile text are safe.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_queries.py tests/test_main.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/queries.py tests/test_queries.py
git commit -m "feat: feed rendered LinkedIn profile into query generation prompt"
```

---

### Task 6: Wire renderer into job scoring

**Files:**
- Modify: `src/job_search_email/scorer.py:30-74` (`_build_system_prompt`)
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `render_profile` from Task 3.
- Produces: `_build_system_prompt(profile) -> str` embedding the rendered profile; qualification instructions reference "education and certifications".

- [ ] **Step 1: Write failing prompt test (append to tests/test_scorer.py)**

```python
from profile_helpers import make_profile as shared_profile

from job_search_email.models import EducationEntry, ExperienceEntry
from job_search_email.scorer import _build_system_prompt


def test_build_system_prompt_includes_rendered_profile():
    profile = shared_profile(
        about="Governance meets data.",
        headline="NHS Digital Transformation",
        experience=[ExperienceEntry(
            title="Governance Manager", company="Swansea Bay UHB",
            start="2023-09", end="present",
        )],
        education=[EducationEntry(institution="UCL", degree="Masters")],
        certifications=["Corporate Strategy"],
        target_roles=["Business Manager"],
        not_open_to=["nursing"],
    )
    prompt = _build_system_prompt(profile)
    assert "Governance meets data." in prompt
    assert "- Governance Manager — Swansea Bay UHB (2023-09 – present)" in prompt
    assert "- Masters — UCL" in prompt
    assert "- Corporate Strategy" in prompt
    assert "education and certifications" in prompt
    assert "Target roles: Business Manager" in prompt
    assert "Not open to: nursing" in prompt
    assert "Min salary: £60,000" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scorer.py -q`
Expected: the new test FAILS (old prompt lacks the rendered block); all existing tests still pass.

- [ ] **Step 3: Rewire _build_system_prompt**

Add `from .profile import render_profile` to scorer imports. Replace the "Candidate profile" section of `_build_system_prompt` — the function becomes:

```python
def _build_system_prompt(profile: Profile) -> str:
    return (
        "You are a job suitability analyst. Evaluate whether the following job is a good "
        "match for this candidate. Respond only with valid JSON matching the schema provided.\n\n"
        "Candidate profile:\n"
        f"{render_profile(profile)}\n\n"
        "Search preferences:\n"
        f"- Seniority: {profile.seniority}\n"
        f"- Target roles: {', '.join(profile.target_roles)}\n"
        f"- Open to: {', '.join(profile.open_to)}\n"
        f"- Not open to: {', '.join(profile.not_open_to)}\n"
        "- Employment type wanted: full-time permanent only\n"
        f"- Min salary: £{profile.min_salary:,}\n\n"
        "Score guidance: 8-10 = strong match (profile clearly fits). "
        "5-7 = partial match (relevant but gaps present). "
        "1-4 = weak (missing essentials or significant misalignment).\n\n"
        "Qualification analysis instructions:\n"
        "- Extract any explicitly stated qualification requirements from the job description\n"
        "- Compare each against the candidate's education and certifications using exact or near-exact matching only\n"
        '- "PRINCE2 required" is a gap if the candidate does not list PRINCE2 specifically\n'
        "- A Master's degree satisfies \"degree required\" but not \"MBA required\"\n"
        "- Set qualification_status to:\n"
        '    "met"      — all stated requirements are present in the candidate\'s profile\n'
        '    "partial"  — some gaps exist but not clearly disqualifying\n'
        '    "mismatch" — one or more hard requirements are clearly absent\n'
        '    ""         — no qualification requirements found in the description'
        "\n\nExclusion instructions:\n"
        "- Set exclude=true when the job clearly fails a hard requirement that the "
        "upstream filters are meant to enforce but may have missed, based on the full "
        "description: the role is not permanent (fixed-term, contract, temporary, "
        "interim, maternity cover, locum, bank, or seasonal); the salary is clearly "
        "below the stated minimum; or the location is clearly outside the candidate's "
        "area.\n"
        "- \"FTC\" means fixed-term contract. Treat any posting that offers "
        "fixed-term as a possibility, including dual \"Permanent / FTC\" "
        "listings, as not a guaranteed permanent role: set exclude=true with "
        "exclude_reason \"Fixed-term contract (FTC)\".\n"
        "- Also set exclude=true when the job is clearly unsuitable for this candidate: "
        "wrong seniority level, a fundamentally different profession, or a domain the "
        "candidate is not open to.\n"
        "- When excluding, put a short human-readable reason (a few words) in "
        "exclude_reason, e.g. \"Fixed-term contract\" or \"Clinical nursing role\".\n"
        "- Otherwise set exclude=false and exclude_reason to an empty string; rank the "
        "job with the score instead."
    )
```

(Only the profile block and the "education and certifications" phrase change; the guidance text is otherwise identical to the current implementation.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scorer.py tests/test_explain_scorer_seam.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/scorer.py tests/test_scorer.py
git commit -m "feat: feed rendered LinkedIn profile into job scoring prompt"
```

---

### Task 7: Use headline in exclusions prompt

**Files:**
- Modify: `src/job_search_email/exclusions.py`
- Create: `tests/test_exclusions.py`

**Interfaces:**
- Consumes: `Profile.headline` from Task 2; `make_profile` from Task 1.
- Produces: `get_exclusions(profile)` unchanged signature; prompt uses `Headline:` instead of `Current role:`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_exclusions.py
from unittest.mock import MagicMock, patch

from profile_helpers import make_profile

from job_search_email.exclusions import get_exclusions


def test_exclusions_prompt_uses_headline():
    profile = make_profile(headline="NHS Digital Transformation | Governance")
    with patch("job_search_email.exclusions.client") as mock_client:
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="[]")]
        )
        result = get_exclusions(profile)
    prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Headline: NHS Digital Transformation | Governance" in prompt
    assert "roles" in result and "employment_types" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_exclusions.py -q`
Expected: FAIL — prompt contains `Current role:` not `Headline:`.

- [ ] **Step 3: Swap the field**

In `src/job_search_email/exclusions.py`, in `_EXCLUSION_ROLES_PROMPT` change the line `  Current role: {current_role}` to `  Headline: {headline}`, and in `_generate_exclusion_roles` change `current_role=profile.current_role,` to `headline=profile.headline,`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_exclusions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/job_search_email/exclusions.py tests/test_exclusions.py
git commit -m "feat: use LinkedIn headline in exclusions prompt"
```

---

### Task 8: Remove legacy profile fields and verify end-to-end

Nothing references `current_role`, `previous_roles`, or `qualifications` on `Profile` any more except the transitional defaults. Remove them everywhere and verify.

**Files:**
- Modify: `src/job_search_email/models.py`, `src/job_search_email/profile.py`, `tests/profile_helpers.py`, `tests/test_scorer.py`, `tests/test_explain_scorer_seam.py`

**Interfaces:**
- Produces: final `Profile` dataclass without `current_role`/`previous_roles`/`qualifications`.

- [ ] **Step 1: Remove the fields from models.py**

`Profile` becomes:

```python
@dataclass
class Profile:
    name: str
    about: str
    seniority: str
    industry: str
    skills: list[str]
    target_roles: list[str]
    open_to: list[str]
    not_open_to: list[str]
    employment_type: list[str]
    location: str
    min_salary: int
    headline: str = ""
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    radius_miles: int = 50
    preamble: str = ""
    recipient_email: str = ""
    send_main_email: bool = True
    send_debug_email: bool = False
    filter_recruitment: bool = True
```

- [ ] **Step 2: Remove the transitional kwargs from the loader**

In `src/job_search_email/profile.py` `load_profile`, delete the three lines `current_role="",`, `previous_roles=[],`, `qualifications=[],`.

- [ ] **Step 3: Update the test factory and remaining overrides**

- `tests/profile_helpers.py` — delete `current_role="Manager",`, `previous_roles=[],`, `qualifications=[],` from the defaults dict.
- `tests/test_scorer.py` — in the local `make_profile`, delete the `qualifications=["MSc Management"],` override (no test asserts on it).
- `tests/test_explain_scorer_seam.py` — delete the `qualifications=["MSc"]` override.

- [ ] **Step 4: Grep for stragglers**

Run: `git grep -nE "current_role|previous_roles" -- src tests` and `git grep -nE "(^|[^_d])qualifications" -- src tests`
Expected: no hits in the first; the second matches only `required_qualifications`/`qualification_gaps`/`qualification_status` (JobAnalysis fields — unrelated) and prose in prompts. Fix any genuine stragglers.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: End-to-end smoke check via the fixture-based local run**

Run: `python -c "from job_search_email.local_run import main; main()"` from the repo root (no API key needed — it uses fixtures).
Expected: prints `[local-test] search plan written`, filter counts, and writes `email_preview.html`. The generated `search_plan.json` should show `evaluator_notes` built from the new profile.

- [ ] **Step 7: Commit**

```bash
git add src/job_search_email/models.py src/job_search_email/profile.py tests/profile_helpers.py tests/test_scorer.py tests/test_explain_scorer_seam.py
git commit -m "feat: remove legacy current_role/previous_roles/qualifications profile fields"
```
