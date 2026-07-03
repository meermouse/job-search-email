# Enhanced LinkedIn-Style Profile — Design

**Date:** 2026-07-03
**Branch:** feature/FE-016-enhanced-profile

## Goal

Reshape `profile.yaml` to mirror a LinkedIn profile — structured experience history
with companies, dates, and descriptions; separated education, certifications, and
languages — and wire that richer detail into the job-matching pipeline so it
actually influences query generation and job scoring. Content is transcribed from
the candidate's real LinkedIn PDF export (`assets/Profile.pdf`).

## Problems with the current profile

1. `previous_roles` is a flat list of titles with no companies, dates, or
   descriptions — and one entry ("Cheshire & Wirral Partnership NHS Foundation
   Trust") is a company name, not a role.
2. `current_role: NHS Digital Transformation` is actually the LinkedIn headline;
   the real current role is "Workforce and Governance Manager for Digital
   Services" at Swansea Bay University Health Board.
3. `qualifications` mixes degrees with short courses/certifications.
4. `skills` is mostly course names; LinkedIn's top skills (SharePoint, Power
   Automate, Power BI) are stronger matching signals.
5. The `about` text is loaded but **never used** by any prompt.
6. Each LLM prompt hand-picks a different subset of profile fields, so they see
   inconsistent views of the candidate.
7. `load_profile` is duplicated in `main.py` and `local_run.py` and has already
   drifted risk.

## New profile.yaml schema

The `profile:` block becomes LinkedIn-shaped. Top-level keys (`location`,
`radius_miles`, `min_salary`, `preamble`, `recipient_email`, `send_main_email`,
`send_debug_email`, `filter_recruitment`) are unchanged.

```yaml
profile:
  name: Jie Zhou
  headline: NHS Digital Transformation | Strategic Workforce Planning | Business Governance | UCL
  about: |
    <LinkedIn Summary, verbatim>
  seniority: Senior
  industry: NHS / Healthcare / Business

  experience:            # ordered most-recent first, replaces previous_roles
    - title: Workforce and Governance Manager for Digital Services
      company: Swansea Bay University Health Board
      location: United Kingdom     # optional
      start: 2023-09               # YYYY or YYYY-MM, quoted as needed
      end: present                 # or YYYY-MM
      description: |               # optional, LinkedIn description verbatim
        ...
    # + Zhejiang University (Instructor of Clinical Skills, 2020-01–present)
    # + Cheshire & Wirral Partnership NHS FT (Business Manager of Research
    #   Centre in Mental Health, 2022-04–2023-09)
    # + American-Sino Healthcare (Executive Secretary to the General Manager,
    #   2018-01–2021-08)
    # + Guangxian Education (Co-Founder, 2019-01–2021-07, no description)

  education:              # split out of qualifications
    - institution: UCL
      degree: Masters, Strategic Management of Projects
    - institution: University of Illinois Urbana-Champaign
      degree: Master's degree, Management
    - institution: Zhejiang University
      degree: Bachelor of Arts (BA), English Language and Literature

  certifications:         # plain strings, the non-degree half of old qualifications
    - Operations and Supply Chain Decisions and Metrics
    - "Managerial Accounting: Cost Behaviors, Systems, and Analysis (with Honors)"
    - Corporate Strategy
    - "Leading Teams: Developing as a Leader"
    - Digital Marketing (DMS4all)

  skills:                 # LinkedIn top skills + skill-like terms from experience
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

  # Search preferences — not LinkedIn fields, unchanged values:
  target_roles: [Business Manager, Digital Transformation, Senior Management]
  open_to: [Strategy Consultant, Project Planning]
  not_open_to: [clinical roles, nursing, GP / medical practitioner, ward-based roles, surgical / theatre roles]
  employment_type: [full-time]
```

Removed fields: `current_role` (superseded by `headline` + first experience
entry), `previous_roles` (superseded by `experience`), `qualifications`
(split into `education` + `certifications`).

## Code changes

### models.py

New dataclasses:

```python
@dataclass
class ExperienceEntry:
    title: str
    company: str
    start: str
    end: str                 # "present" for current roles
    location: str = ""
    description: str = ""

@dataclass
class EducationEntry:
    institution: str
    degree: str
```

`Profile` gains `headline`, `experience: list[ExperienceEntry]`,
`education: list[EducationEntry]`, `certifications: list[str]`,
`languages: list[str]`; drops `current_role`, `previous_roles`,
`qualifications`. All other fields unchanged.

### New module: profile.py (loader + renderer)

- `load_profile(path) -> Profile` — single YAML loader replacing the duplicate
  loaders in `main.py` and `local_run.py` (and used by `explain_job.py`).
  Parses nested
  experience/education into the dataclasses; missing optional fields default
  cleanly.
- `render_profile(profile) -> str` — renders one consistent text block used by
  the LLM prompts:

  ```
  Name / Headline
  About (verbatim)
  Current role: <first experience entry with end == "present">
  Experience: one block per entry — title, company, dates, description
  Education / Certifications / Skills / Languages
  ```

  Descriptions are included in full for the scorer; entries without a
  description render as a single line.

### Prompt wiring

- **queries.py** — `QUERY_GENERATION_PROMPT` replaces its hand-picked field
  list (`current_role`, `previous_roles`, etc.) with the rendered profile
  block, keeping the search-specific instructions and
  `target_roles`/`open_to`/`not_open_to`/`seniority` guidance.
- **scorer.py** — `_build_system_prompt` embeds the rendered profile block
  (finally including `about` and full work history). The qualification-gap
  instructions now reference "education and certifications" instead of
  "qualifications". Employment-type/min-salary lines unchanged.
- **exclusions.py** — the `{current_role}` placeholder becomes `{headline}`;
  everything else unchanged (structured fields, not the renderer, since this
  prompt is about generating exclusion terms).
- **evaluator_notes.py** — unchanged logic; it already uses only surviving
  fields (`seniority`, `industry`, `min_salary`, `not_open_to`, `skills`,
  `target_roles`, `open_to`).
- **email.py / debug_email.py** — unchanged (use only `name`, `preamble`,
  `recipient_email`).

### Caching

`fingerprint_profile` uses `asdict(profile)`, which handles nested dataclasses.
The new schema + content produce a new fingerprint, so the search-plan cache and
job-score cache invalidate automatically. No migration needed; stale entries are
simply never read again.

## Content source

`assets/Profile.pdf` (LinkedIn "Save to PDF" export, already in the working
tree) is the source of truth for content. It is transcribed verbatim into
profile.yaml and then **deleted — the PDF is not committed** (profile.yaml
already carries the personal data the pipeline needs).

Known limitation: LinkedIn's PDF export lists only the top 3 skills. The
`skills` list therefore merges those three with skill-like terms taken from the
experience descriptions, as shown above.

## Testing

- Unit tests for `load_profile` (nested parsing, optional-field defaults) and
  `render_profile` (sections present, current role derived, no-description
  entries).
- Update existing tests that build `Profile` fixtures or assert on prompt
  contents (`test_main.py`, `test_scorer.py`, `test_local_testing.py`,
  `tests/test_explain_scorer_seam.py`, etc.) to the new field set.
- Full suite green before merge.

## Out of scope

- Automatic re-sync from LinkedIn.
- Changing filter logic, search APIs, or email formatting.
- Using `languages` in matching (recorded for completeness; no current prompt
  need).
