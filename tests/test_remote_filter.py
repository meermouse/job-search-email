import json
from unittest.mock import MagicMock, patch

from job_search_email.models import JobListing
from job_search_email.remote_filter import (
    classify_remote,
    load_remote_cache,
    save_remote_cache,
)


def make_job(url: str, description: str = "", location: str = "Remote") -> JobListing:
    return JobListing(
        title="Digital Manager", company="Acme Analytics", location=location,
        salary_min=70000, description=description, url=url,
        source="reed", employment_type="permanent",
    )


def _mock_claude_response(payload: dict) -> MagicMock:
    block = MagicMock()
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def test_classify_remote_uses_cache_without_calling_claude():
    cache = {"https://x.com/1": "remote", "https://x.com/2": "not_remote"}
    jobs = [make_job("https://x.com/1"), make_job("https://x.com/2")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        result = classify_remote(jobs, cache=cache)
    mock_client.messages.create.assert_not_called()
    assert result == {"https://x.com/1": "remote", "https://x.com/2": "not_remote"}


def test_classify_remote_calls_claude_for_uncached():
    jobs = [
        make_job("https://x.com/1", description="This role is fully remote within the UK."),
        make_job("https://x.com/2", description="Hybrid: 3 days in our Leeds office."),
    ]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response(
            {"0": "remote", "1": "not_remote"})
        result = classify_remote(jobs, cache=cache)
    mock_client.messages.create.assert_called_once()
    assert result["https://x.com/1"] == "remote"
    assert result["https://x.com/2"] == "not_remote"


def test_classify_remote_updates_cache_after_call():
    jobs = [make_job("https://x.com/1")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "remote"})
        classify_remote(jobs, cache=cache)
    assert cache == {"https://x.com/1": "remote"}


def test_classify_remote_missing_key_defaults_not_remote():
    # The model answered but omitted a job: no positive confirmation → not_remote.
    jobs = [make_job("https://x.com/1")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({})
        result = classify_remote(jobs, cache=cache)
    assert result["https://x.com/1"] == "not_remote"
    assert cache["https://x.com/1"] == "not_remote"


def test_classify_remote_invalid_verdict_defaults_not_remote():
    jobs = [make_job("https://x.com/1")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "maybe"})
        result = classify_remote(jobs, cache={})
    assert result["https://x.com/1"] == "not_remote"


def test_classify_remote_api_failure_returns_unverified_and_does_not_cache():
    jobs = [make_job("https://x.com/1")]
    cache: dict[str, str] = {}
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.side_effect = ConnectionError("api down")
        result = classify_remote(jobs, cache=cache)
    assert result["https://x.com/1"] == "unverified"
    assert cache == {}


def test_classify_remote_handles_fenced_json():
    jobs = [make_job("https://x.com/1")]
    with patch("job_search_email.remote_filter.client") as mock_client:
        block = MagicMock()
        block.text = '```json\n{"0": "remote"}\n```'
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_remote(jobs, cache={})
    assert result["https://x.com/1"] == "remote"


def test_classify_remote_batches_large_input():
    jobs = [make_job(f"https://x.com/{i}") for i in range(25)]  # batch size is 20
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.side_effect = [
            _mock_claude_response({str(i): "not_remote" for i in range(20)}),
            _mock_claude_response({str(i): "not_remote" for i in range(5)}),
        ]
        result = classify_remote(jobs, cache={})
    assert mock_client.messages.create.call_count == 2
    assert len(result) == 25


def test_classify_remote_truncates_long_descriptions():
    jobs = [make_job("https://x.com/1", description="A" * 10000)]
    with patch("job_search_email.remote_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({"0": "not_remote"})
        classify_remote(jobs, cache={})
    sent = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "A" * 4001 not in sent


def test_load_remote_cache_missing_file_returns_empty(tmp_path):
    assert load_remote_cache(tmp_path / "nope.json") == {}


def test_load_remote_cache_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json", encoding="utf-8")
    assert load_remote_cache(path) == {}


def test_save_and_load_remote_cache_roundtrip(tmp_path):
    path = tmp_path / "cache.json"
    save_remote_cache({"https://x.com/1": "remote"}, path)
    assert not (tmp_path / "cache.tmp").exists()
    assert load_remote_cache(path) == {"https://x.com/1": "remote"}
