import pytest
from app.services.links import _extract_short_url, _gplinks_endpoint


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
