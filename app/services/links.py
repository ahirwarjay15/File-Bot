from urllib.parse import quote
import aiohttp

async def shorten_url(base_url: str, api_token: str, long_url: str) -> str:
    """Generic JSON shortener adapter. Provider must accept url/token JSON fields and return short_url."""
    if not base_url or not api_token:
        return long_url
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(base_url, json={"url": long_url, "token": api_token}) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    result = data.get("short_url") or data.get("shortenedUrl") or data.get("shortlink")
    if not isinstance(result, str) or not result.startswith(("https://", "http://")):
        raise ValueError("Shortener response did not contain a valid short URL")
    return result
