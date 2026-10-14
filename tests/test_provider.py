"""Provider tests using httpx's MockTransport -- no network."""
import httpx
import pytest

from husk.providers.openai_compat import OpenAICompatProvider


def _provider(handler):
    p = OpenAICompatProvider(base_url="http://test/v1", api_key="k", model="m")
    p._client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


def test_normal_response_returns_message():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]})
    assert _provider(handler).chat([{"role": "user", "content": "x"}])["content"] == "hi"


def test_null_keys_are_stripped():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None, "tool_calls": [{"id": "1"}]}}]})
    msg = _provider(handler).chat([{"role": "user", "content": "x"}])
    assert "content" not in msg and msg["tool_calls"] == [{"id": "1"}]


def test_200_with_error_body_raises_clear_error():
    def handler(request):
        return httpx.Response(200, json={"error": {"message": "model is loading"}})
    with pytest.raises(RuntimeError, match="no choices"):
        _provider(handler).chat([{"role": "user", "content": "x"}])


def test_empty_choices_raises():
    def handler(request):
        return httpx.Response(200, json={"choices": []})
    with pytest.raises(RuntimeError, match="no choices"):
        _provider(handler).chat([{"role": "user", "content": "x"}])


def test_http_500_raises_status_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})
    with pytest.raises(httpx.HTTPStatusError):
        _provider(handler).chat([{"role": "user", "content": "x"}])
