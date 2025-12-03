from __future__ import annotations

import ipaddress
import socket
from typing import Dict, List, Tuple
from urllib.parse import urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context


class SecurityError(RuntimeError):
    """Raised when an unsafe network request is detected."""


def is_private_ip(ip: str) -> bool:
    """Return True if the IP address belongs to a private or unsafe range."""
    try:
        ip_obj = ipaddress.ip_address(ip)
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
        )
    except ValueError:
        return True


def resolve_and_validate_domain(domain: str) -> Tuple[str, List[str]]:
    """Resolve the given domain and verify that all IPs are public."""
    try:
        addr_info = socket.getaddrinfo(
            domain,
            None,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:  # pragma: no cover - network errors
        raise SecurityError(f"Failed to resolve domain '{domain}': {exc}") from exc
    except Exception as exc:  # pragma: no cover - unexpected errors
        raise SecurityError(f"Resolution error for '{domain}': {exc}") from exc

    all_ips = sorted({str(info[4][0]) for info in addr_info if info and info[4]})
    if not all_ips:
        raise SecurityError(f"No IPs resolved for domain: {domain}")

    dangerous_ips = [ip for ip in all_ips if is_private_ip(ip)]
    if dangerous_ips:
        raise SecurityError(
            f"DNS rebinding detected! Domain '{domain}' resolves to private/internal IPs: {dangerous_ips}"
        )

    return all_ips[0], all_ips


class HostHeaderSSLAdapter(HTTPAdapter):
    """Adapter that preserves the original hostname for HTTPS + SNI."""

    def __init__(self, hostname: str, *args, **kwargs):
        self.hostname = hostname
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        kwargs["ssl_context"] = ctx
        kwargs["assert_hostname"] = self.hostname
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):  # pragma: no cover - proxy not in tests
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        kwargs["ssl_context"] = ctx
        kwargs["assert_hostname"] = self.hostname
        return super().proxy_manager_for(*args, **kwargs)


_DEFAULT_USER_AGENT = "CodeBot/ObservabilityDashboard"


def _format_locked_netloc(ip: str, port: int | None) -> str:
    if ":" in ip and not ip.startswith("["):
        host = f"[{ip}]"
    else:
        host = ip
    if port:
        return f"{host}:{port}"
    return host


def fetch_graph_securely(
    graph_url_template: str,
    *,
    timeout: int = 10,
    allow_redirects: bool = False,
    headers: Dict[str, str] | None = None,
    **url_params,
) -> bytes:
    """
    Fetch a graph/JSON endpoint while protecting against DNS rebinding / SSRF.

    Args:
        graph_url_template: URL template (format-style) from configuration.
        timeout: Request timeout in seconds.
        allow_redirects: Whether to follow redirects (default False).
        headers: Optional base headers to attach to the request.
        **url_params: Values used to render the template.
    """

    try:
        url = graph_url_template.format(**url_params)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"Missing template parameter: {missing}") from exc

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SecurityError("Only http/https URLs are allowed")
    if not parsed.hostname:
        raise SecurityError("Invalid URL - missing hostname")

    locked_ip, _ = resolve_and_validate_domain(parsed.hostname)

    netloc_with_ip = _format_locked_netloc(locked_ip, parsed.port)
    parsed_with_ip = parsed._replace(netloc=netloc_with_ip)
    url_with_locked_ip = urlunparse(parsed_with_ip)

    base_headers: Dict[str, str] = {}
    if headers:
        try:
            base_headers.update({str(k): str(v) for k, v in headers.items() if k and v})
        except Exception:
            # Fall back silently if headers contain non-serializable values
            pass
    base_headers.setdefault("Host", parsed.hostname)
    base_headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)

    verify_cert = True

    with requests.Session() as session:
        if parsed.scheme == "https":
            session.mount("https://", HostHeaderSSLAdapter(parsed.hostname))
        response = session.get(
            url_with_locked_ip,
            headers=base_headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
            verify=verify_cert,
        )
        response.raise_for_status()
        return response.content
