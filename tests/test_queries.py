import pytest
from job_search_email.queries import _strip_code_fence


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
