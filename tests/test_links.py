import pytest
from app.services.links import (
    _extract_short_url,
    _gplinks_endpoint,
    _shrtfly_endpoint,
    _shrtfly_params,
)


def test_gplinks_website_uses_official_api_endpoint():
    assert _gplinks_endpoint("https://gplinks.com") == "https://api.gplinks.com/st"
    assert _gplinks_endpoint("https://www.gplinks.in") == "https://api.gplinks.com/st"


def test_gplinks_api_endpoint_is_preserved():
    assert _gplinks_endpoint("https://api.gplinks.com/st") == "https://api.gplinks.com/st"


def test_generic_provider_is_not_misidentified_as_gplinks():
    assert _gplinks_endpoint("https://shortener.example/api") is None


@pytest.mark.parametrize("response", [
    {"short_url": "https://short.example/abc"},
    {"shortenedUrl": "https://short.example/abc"},
    {"shortlink": "https://short.example/abc"},
    "https://short.example/abc",
])
def test_supported_shortener_response_shapes(response):
    assert _extract_short_url(response) == "https://short.example/abc"


def test_invalid_shortener_response_fails():
    with pytest.raises(ValueError):
        _extract_short_url({"status": "error"})


def test_shrtfly_website_resolves_to_api_endpoint():
    assert _shrtfly_endpoint("https://shrtfly.com") == "https://shrtfly.com/api"
    assert _shrtfly_endpoint("https://www.shrtfly.com/") == "https://www.shrtfly.com/api"
    assert _shrtfly_endpoint("https://shrtfly.com/api") == "https://shrtfly.com/api"


def test_shrtfly_request_includes_compatibility_parameters():
    assert _shrtfly_params("test-token", "https://example.org/file") == {
        "api": "test-token",
        "url": "https://example.org/file",
        "ads_type": "mainstream",
        "is_text_format": "false",
    }


def test_nested_provider_response_shapes_are_supported():
    assert _extract_short_url({"data": {"short_url": "https://short.example/a"}}) == "https://short.example/a"
    assert _extract_short_url({"result": {"shortenedUrl": "https://short.example/b"}}) == "https://short.example/b"
    assert _extract_short_url({"shortLink": "https://short.example/c"}) == "https://short.example/c"


def test_provider_error_message_is_preserved_for_diagnostics():
    with pytest.raises(ValueError, match="Invalid API token"):
        _extract_short_url({"status": "error", "message": "Invalid API token"})
