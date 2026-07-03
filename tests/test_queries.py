import json
from unittest.mock import MagicMock, patch

import pytest

from profile_helpers import make_profile
from job_search_email.models import ExperienceEntry
from job_search_email.queries import _strip_code_fence, generate_queries


def test_strip_code_fence_plain_json():
    text = '["foo", "bar"]'
    assert _strip_code_fence(text) == '["foo", "bar"]'


def test_strip_code_fence_with_json_fence():
    text = '```json\n["foo", "bar"]\n```'
    assert _strip_code_fence(text) == '["foo", "bar"]'


def test_strip_code_fence_with_plain_fence():
    text = '```\n["foo", "bar"]\n```'
    assert _strip_code_fence(text) == '["foo", "bar"]'


def test_strip_code_fence_multiline():
    text = '```json\n[\n  "a",\n  "b"\n]\n```'
    assert _strip_code_fence(text) == '[\n  "a",\n  "b"\n]'


def test_strip_code_fence_with_surrounding_whitespace():
    text = '  ```json\n["foo"]\n```  '
    assert _strip_code_fence(text) == '["foo"]'


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
