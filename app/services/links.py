"""URL shortener adapters.

GPlinks uses its documented GET endpoint; other providers may use the generic
JSON API contract (POST {url, token} -> short_url/shortenedUrl/shortlink).
"""
import json
from urllib.parse import urlparse
import aiohttp


def _gplinks_endpoint(base_url: str) -> str | None:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host in {"gplinks.com", "www.gplinks.com", "gplinks.in", "www.gplinks.in"}:
        return "https://api.gplinks.com/st"
    if host == "api.gplinks.com" and parsed.path.rstrip("/") == "/st":
        return base_url
    return None


def _extract_short_url(data) -> str:
    if isinstance(data, str):
        candidate = data.strip()
        if candidate.startswith(("https://", "http://")):
            return candidate
    if isinstance(data, dict):
        candidate = (
            data.get("short_url") or data.get("shortenedUrl") or
            data.get("shortlink") or data.get("shortened_url")
        )
        if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
            return candidate
    raise ValueError("Provider response did not contain a valid short URL")


async def shorten_url(base_url: str, api_token: str, long_url: str) -> str:
    """Shorten a URL through a supported provider adapter."""
    if not base_url or not api_token:
        raise ValueError("Shortener provider URL and API token are required")
    timeout = aiohttp.ClientTimeout(total=10)
    endpoint = _gplinks_endpoint(base_url)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if endpoint:
            async with session.get(endpoint, params={"api": api_token, "url": long_url}) as response:
                response.raise_for_status()
                body = await response.text()
            try:
                data = json.loads(body)
            except (TypeError, ValueError):
                data = body
            return _extract_short_url(data)

        async with session.post(base_url, json={"url": long_url, "token": api_token}) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    return _extract_short_url(data)
