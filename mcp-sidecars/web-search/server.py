"""MCP Web Search sidecar — search the web, fetch URLs, extract text."""

import ipaddress
import os
import socket
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-web-search",
    "Search the web, fetch URLs, and extract text content from pages.",
)

MAX_CONTENT_CHARS = 12000

# --- SSRF Protection ---
_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})


def _validate_url(url: str) -> str | None:
    """Return an error message if URL targets a blocked destination, else None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"Only http/https URLs are allowed (got '{scheme}')"

    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname"

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return f"Hostname '{hostname}' is blocked"

    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"Could not resolve hostname '{hostname}'"

    for family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_IP_NETWORKS:
            if ip in network:
                return f"URL resolves to blocked IP range ({network})"
    return None


@server.tool()
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo and return results."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=min(max_results, 10)))
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"**{r.get('title', '')}**")
            lines.append(r.get("href", ""))
            lines.append(r.get("body", ""))
            lines.append("")
        return "\n".join(lines)[:MAX_CONTENT_CHARS]
    except ImportError:
        return "ERROR: duckduckgo_search not installed"
    except Exception as e:
        return f"ERROR: Search failed: {e}"


@server.tool()
def fetch_url(url: str) -> str:
    """Fetch a URL and return the raw text content."""
    url_err = _validate_url(url)
    if url_err:
        return f"BLOCKED: {url_err}"
    import requests
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "MCP-WebSearch/1.0"})
        resp.raise_for_status()
        return resp.text[:MAX_CONTENT_CHARS]
    except Exception as e:
        return f"ERROR: Failed to fetch URL: {e}"


@server.tool()
def extract_text(url: str) -> str:
    """Fetch a URL and extract readable text content (strips HTML)."""
    url_err = _validate_url(url)
    if url_err:
        return f"BLOCKED: {url_err}"
    import requests
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, timeout=15, headers={"User-Agent": "MCP-WebSearch/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:MAX_CONTENT_CHARS]
    except ImportError:
        return "ERROR: beautifulsoup4 not installed"
    except Exception as e:
        return f"ERROR: Failed to extract text: {e}"


if __name__ == "__main__":
    run_server(server)
