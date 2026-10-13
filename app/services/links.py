"""Async URL shortener adapters for AdLinkFly-compatible and common providers."""
import json
from urllib.parse import urlparse

import aiohttp


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def _normalized_provider_url(base_url: str) -> str:
    """Normalize a provider URL and add /api when only a domain was supplied."""
    value = (base_url or "").strip()
    if not value:
        raise ValueError("Shortener provider URL is required")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Shortener provider URL must be a valid HTTP(S) URL")
    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/")
    if host in {"gplinks.com", "www.gplinks.com", "gplinks.in", "www.gplinks.in"} and path in {"", "/api"}:
        return "https://api.gplinks.com/st"
    if host == "api.gplinks.com" and path in {"", "/st"}:
        return "https://api.gplinks.com/st"
    if host in {"ouo.io", "www.ouo.io", "ouo.press", "www.ouo.press"}:
        return f"{parsed.scheme}://{parsed.netloc}"
    if path:
        return value.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}/api"


def _shrtfly_endpoint(base_url: str) -> str | None:
    """Backward-compatible ShrtFly endpoint resolver."""
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    if (parsed.hostname or "").lower() in {"shrtfly.com", "www.shrtfly.com", "api.shrtfly.com"}:
        return _normalized_provider_url(base_url)
    return None


def _shrtfly_params(api_token: str, long_url: str) -> dict[str, str]:
    """Legacy helper retained for tests and integrations."""
    return {"api": api_token, "url": long_url}


def _extract_short_url(data) -> str:
    """Extract a valid short URL from common provider response formats."""
    if isinstance(data, str):
        candidate = data.strip()
        if candidate.startswith(("https://", "http://")):
            return candidate
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            if candidate and candidate.lstrip().startswith(("<!DOCTYPE", "<html", "<HTML")):
                raise ValueError("Provider returned HTML instead of JSON; a firewall or Cloudflare page may be blocking the API")
            raise ValueError(f"Provider returned an unrecognized response: {candidate[:120] or 'empty response'}")
    if isinstance(data, dict):
        for key in (
            "short_url", "shortUrl", "shortenedUrl", "shortened_url",
            "shortenedLink", "shortened_link", "shortlink", "shortLink",
            "short_link", "shortened", "short", "shortenedLinkUrl",
        ):
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
        status = str(data.get("status", "")).lower()
        if status in {"error", "failed", "failure"}:
            message = data.get("message") or data.get("error") or data.get("msg")
            raise ValueError(str(message or "Provider rejected the API request"))
        message = data.get("message") or data.get("error") or data.get("msg")
        if message:
            raise ValueError(str(message))
    raise ValueError("Provider response did not contain a valid short URL")


async def _get_provider_response(session, endpoint: str, params: dict[str, str]) -> str:
    async with session.get(endpoint, params=params) as response:
        body = await response.text()
        if response.status >= 400:
            detail = body.strip().replace("\n", " ")[:160]
            if detail.startswith(("<!DOCTYPE", "<html", "<HTML")):
                detail = "HTML/firewall response"
            raise ValueError(f"Provider returned HTTP {response.status}: {detail or response.reason}")
        return body


async def shorten_url(base_url: str, api_token: str, long_url: str) -> str:
    """Shorten a URL via AdLinkFly-compatible, ShareUs, Ouo, or generic JSON APIs."""
    if not api_token:
        raise ValueError("Shortener API token is required")
    endpoint = _normalized_provider_url(base_url)
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    timeout = aiohttp.ClientTimeout(total=12)

    async with aiohttp.ClientSession(timeout=timeout, headers=_BROWSER_HEADERS) as session:
        if host in {"shareus.io", "www.shareus.io"} or "shareus" in host:
            body = await _get_provider_response(
                session,
                "https://api.shareus.io/easy_api",
                {"key": api_token, "link": long_url},
            )
        elif host in {"ouo.io", "www.ouo.io", "ouo.press", "www.ouo.press"}:
            body = await _get_provider_response(
                session,
                f"http://{host}/api/{api_token}",
                {"s": long_url},
            )
        else:
            # AdLinkFly-family providers share the /api?api=KEY&url=LONG_URL contract.
            body = await _get_provider_response(
                session,
                endpoint,
                {"api": api_token, "url": long_url},
            )

    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        data = body
    return _extract_short_url(data)
