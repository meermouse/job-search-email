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
