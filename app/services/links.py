"""URL shortener adapters for common monetized and generic providers."""
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


def _shrtfly_endpoint(base_url: str) -> str | None:
    """Resolve a ShrtFly website URL to its API route."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host not in {"shrtfly.com", "www.shrtfly.com", "api.shrtfly.com"}:
        return None
    if parsed.path.rstrip("/").endswith("/api"):
        return base_url
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/api"


def _extract_short_url(data) -> str:
    """Read common response keys, including nested API response envelopes."""
    if isinstance(data, str):
        candidate = data.strip()
        if candidate.startswith(("https://", "http://")):
            return candidate
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            pass
    if isinstance(data, dict):
        keys = (
            "short_url", "shortUrl", "shortenedUrl", "shortened_url",
            "shortlink", "shortLink", "short_link", "shortened", "short",
        )
        for key in keys:
            candidate = data.get(key)
            if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
                return candidate
        for key in ("data", "result", "link", "output"):
            nested = data.get(key)
            if isinstance(nested, (dict, str)):
                try:
                    return _extract_short_url(nested)
                except ValueError:
                    pass
        candidate = data.get("url")
        if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
            return candidate
    raise ValueError("Provider response did not contain a valid short URL")


async def shorten_url(base_url: str, api_token: str, long_url: str) -> str:
    """Shorten a URL using a known provider adapter or a generic JSON API."""
    if not base_url or not api_token:
        raise ValueError("Shortener provider URL and API token are required")
    timeout = aiohttp.ClientTimeout(total=10)
    gplinks = _gplinks_endpoint(base_url)
    shrtfly = _shrtfly_endpoint(base_url)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if gplinks:
            async with session.get(gplinks, params={"api": api_token, "url": long_url}) as response:
                response.raise_for_status()
                body = await response.text()
            try:
                data = json.loads(body)
            except (TypeError, ValueError):
                data = body
            return _extract_short_url(data)

        if shrtfly:
            async with session.get(shrtfly, params={"api": api_token, "url": long_url}) as response:
                response.raise_for_status()
                body = await response.text()
            try:
                data = json.loads(body)
            except (TypeError, ValueError):
                data = body
            if isinstance(data, dict) and str(data.get("status", "")).lower() in {"error", "failed", "failure"}:
                raise ValueError(str(data.get("message") or data.get("error") or "ShrtFly rejected the API request"))
            return _extract_short_url(data)

        async with session.post(base_url, json={"url": long_url, "token": api_token}) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    return _extract_short_url(data)
