import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_search_email.location_filter import (
    classify_locations,
    load_location_cache,
    save_location_cache,
)


def _mock_claude_response(payload: dict) -> MagicMock:
    block = MagicMock()
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


def test_classify_locations_uses_cache_for_known_locations():
    cache = {"Bristol:50:Bath, BA1": "within", "Bristol:50:London": "outside"}
    with patch("job_search_email.location_filter.client") as mock_client:
        result = classify_locations(["Bath, BA1", "London"], home="Bristol", radius_miles=50, cache=cache)
    mock_client.messages.create.assert_not_called()
    assert result["Bath, BA1"] == "within"
    assert result["London"] == "outside"


def test_classify_locations_calls_claude_for_unknown():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({
            "Reading, RG1": "outside",
            "Bath, BA1": "within",
        })
        result = classify_locations(
            ["Reading, RG1", "Bath, BA1"], home="Bristol", radius_miles=50, cache=cache
        )
    mock_client.messages.create.assert_called_once()
    assert result["Reading, RG1"] == "outside"
    assert result["Bath, BA1"] == "within"


def test_classify_locations_updates_cache_after_claude_call():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({
            "Reading, RG1": "outside",
        })
        classify_locations(["Reading, RG1"], home="Bristol", radius_miles=50, cache=cache)
    assert cache["Bristol:50:Reading, RG1"] == "outside"


def test_classify_locations_treats_invalid_json_as_uncertain():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        block = MagicMock()
        block.text = "not valid json"
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_locations(["Reading, RG1"], home="Bristol", radius_miles=50, cache=cache)
    assert result["Reading, RG1"] == "uncertain"


def test_classify_locations_defaults_missing_keys_to_uncertain():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        mock_client.messages.create.return_value = _mock_claude_response({})
        result = classify_locations(["Remote"], home="Bristol", radius_miles=50, cache=cache)
    assert result["Remote"] == "uncertain"


def test_load_location_cache_returns_empty_dict_when_file_missing(tmp_path):
    result = load_location_cache(tmp_path / "no_file.json")
    assert result == {}


def test_load_location_cache_reads_existing_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"Bristol:50:Bath": "within"}), encoding="utf-8")
    result = load_location_cache(path)
    assert result == {"Bristol:50:Bath": "within"}


def test_save_location_cache_writes_atomically(tmp_path):
    path = tmp_path / "cache.json"
    save_location_cache({"Bristol:50:Bath": "within"}, path)
    assert path.exists()
    assert not (tmp_path / "cache.tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"Bristol:50:Bath": "within"}


def test_classify_locations_handles_fenced_json():
    cache: dict[str, str] = {}
    with patch("job_search_email.location_filter.client") as mock_client:
        block = MagicMock()
        block.text = '```json\n{"Reading, RG1": "outside"}\n```'
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response
        result = classify_locations(["Reading, RG1"], home="Bristol", radius_miles=50, cache=cache)
    assert result["Reading, RG1"] == "outside"
