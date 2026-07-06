from pathlib import Path

from job_search_email.models import EducationEntry, ExperienceEntry
from job_search_email.profile import load_profile, render_profile
from profile_helpers import make_profile

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


def test_render_profile_experience_without_start_renders_end_only():
    profile = make_profile(
        name="Test",
        experience=[ExperienceEntry(title="Advisor", company="Acme", start="", end="present")],
    )
    text = render_profile(profile)
    assert "- Advisor — Acme (present)" in text


def test_all_repo_profiles_load_and_are_complete():
    from pathlib import Path
    profiles_dir = Path(__file__).parent.parent / "profiles"
    paths = sorted(profiles_dir.glob("*.yaml"))
    assert [p.name for p in paths] == ["jie-zhou.yaml", "marc-brookes.yaml"]
    for path in paths:
        profile = load_profile(path)
        assert profile.name, path.name
        assert profile.recipient_email, path.name
        assert profile.location, path.name
        assert profile.min_salary > 0, path.name
        assert profile.experience, path.name


def test_marc_profile_has_sponsor_filter_off():
    from pathlib import Path
    profile = load_profile(Path(__file__).parent.parent / "profiles" / "marc-brookes.yaml")
    assert profile.filter_sponsors is False
    assert profile.filter_recruitment is True
    assert profile.min_salary == 80000
