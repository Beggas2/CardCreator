"""Download seguro de documentos públicos (SEC-003: proteção contra SSRF).

- Só http/https, portas 80/443, sem credenciais na URL.
- Todo endereço resolvido precisa ser público; redirecionamentos são seguidos manualmente e revalidados.
- Tamanho e tipo de conteúdo limitados; nada é executado.
Risco residual documentado em SECURITY.md: troca de DNS entre a validação e a conexão (rebinding).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf", "text/markdown")
MAX_BYTES = 30 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "CardFactory/0.1 (+local)"

Resolver = Callable[[str, int], list[str]]


class FetchBlockedError(Exception):
    """A URL ou o destino não é permitido."""


class FetchFailedError(Exception):
    pass


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchFailedError(f"não foi possível resolver {host}: {e}") from e
    return sorted({i[4][0] for i in infos})


class ResolutionDelegatedError(Exception):
    """A resolução de nomes é feita por um proxy de saída que impõe a lista de hosts permitidos."""


def proxied_resolver(host: str, port: int) -> list[str]:
    """Para ambientes onde só o proxy resolve nomes (opt-in por CARDFACTORY_FETCH_VIA_PROXY=1).

    Se o nome resolve localmente, a verificação de IP público continua valendo; se não resolve e há proxy
    configurado, o destino é decidido pelo proxy (que só alcança hosts públicos permitidos).
    """
    try:
        return system_resolver(host, port)
    except FetchFailedError:
        if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            raise ResolutionDelegatedError(host) from None
        raise


def default_resolver() -> Resolver:
    return proxied_resolver if os.environ.get("CARDFACTORY_FETCH_VIA_PROXY") == "1" else system_resolver


def _check_ip(ip: str) -> None:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_multicast:
        raise FetchBlockedError(f"destino não público bloqueado: {addr}")


def validate_url(url: str, resolver: Resolver = system_resolver) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchBlockedError("só http/https são permitidos")
    if parts.username or parts.password:
        raise FetchBlockedError("credenciais na URL não são permitidas")
    host = parts.hostname
    if not host:
        raise FetchBlockedError("URL sem host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in (80, 443):
        raise FetchBlockedError("porta não permitida")
    if host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal", ".localhost")):
        raise FetchBlockedError("host local bloqueado")
    try:
        _check_ip(host)  # host literal
    except ValueError:
        try:
            ips = resolver(host, port)
        except ResolutionDelegatedError:
            return parts.geturl()
        if not ips:
            raise FetchFailedError(f"{host} não resolveu") from None
        for ip in ips:
            _check_ip(ip)
    return parts.geturl()


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content_type: str
    data: bytes


async def safe_fetch(url: str, *, resolver: Resolver | None = None, max_bytes: int = MAX_BYTES,
                     timeout_s: float = 30.0, transport: httpx.AsyncBaseTransport | None = None) -> Fetched:
    resolver = resolver or default_resolver()
    current = validate_url(url, resolver)
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False, transport=transport,
                                 headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        raise FetchFailedError("redirecionamento sem destino")
                    current = validate_url(urljoin(current, loc), resolver)
                    continue
                if resp.status_code != 200:
                    raise FetchFailedError(f"HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and ctype not in ALLOWED_TYPES:
                    raise FetchBlockedError(f"tipo de conteúdo não permitido: {ctype}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise FetchBlockedError("documento maior que o limite")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise FetchBlockedError("documento maior que o limite")
                return Fetched(url, current, resp.status_code, resp.headers.get("content-type", ""), bytes(buf))
        raise FetchFailedError("redirecionamentos demais")
