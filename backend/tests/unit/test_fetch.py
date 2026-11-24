import httpx
import pytest

from cardfactory.security.fetch import FetchBlockedError, FetchFailedError, safe_fetch, validate_url


def public(host, port):
    return {"gov.example": ["200.130.5.5"], "evil.example": ["10.0.0.5"], "mixed.example": ["8.8.8.8", "127.0.0.1"],
            "v6.example": ["::ffff:127.0.0.1"], "meta.example": ["169.254.169.254"]}.get(host, ["93.184.216.34"])


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://gov.example/x", "http://user:pw@gov.example/", "http://gov.example:8080/",
    "http://127.0.0.1/", "http://[::1]/", "http://localhost/", "http://router.local/", "http://evil.example/",
    "http://mixed.example/", "http://v6.example/", "http://meta.example/latest", "http://0.0.0.0/",
    "http://192.168.0.1/",
])
def test_blocked_urls(url):
    with pytest.raises(FetchBlockedError):
        validate_url(url, public)


def test_allowed_url():
    assert validate_url("https://gov.example/pcdt.pdf", public) == "https://gov.example/pcdt.pdf"


async def test_fetch_follows_safe_redirect_and_blocks_internal():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        if req.url.path == "/b":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 x")
        if req.url.path == "/to-internal":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(404)

    t = httpx.MockTransport(handler)
    r = await safe_fetch("https://gov.example/a", resolver=public, transport=t)
    assert r.final_url.endswith("/b") and r.data.startswith(b"%PDF")
    with pytest.raises(FetchBlockedError):
        await safe_fetch("https://gov.example/to-internal", resolver=public, transport=t)
    with pytest.raises(FetchFailedError):
        await safe_fetch("https://gov.example/missing", resolver=public, transport=t)


async def test_fetch_limits_size_and_type():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/big":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 5000)
        return httpx.Response(200, headers={"content-type": "application/x-msdownload"}, content=b"MZ")

    t = httpx.MockTransport(handler)
    with pytest.raises(FetchBlockedError):
        await safe_fetch("https://gov.example/big", resolver=public, transport=t, max_bytes=1000)
    with pytest.raises(FetchBlockedError):
        await safe_fetch("https://gov.example/app.exe", resolver=public, transport=t)


async def test_redirect_loop():
    t = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "/loop"}))
    with pytest.raises(FetchFailedError):
        await safe_fetch("https://gov.example/loop", resolver=public, transport=t)
