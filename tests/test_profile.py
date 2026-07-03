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
