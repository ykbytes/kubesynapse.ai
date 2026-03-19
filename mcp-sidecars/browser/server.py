"""MCP Browser sidecar — browse web pages, take screenshots, interact with forms."""

import ipaddress
import logging
import os
import socket
import sys
import tempfile
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

log = logging.getLogger("mcp-browser")

server = create_mcp_server(
    "mcp-browser",
    "Browse web pages, take screenshots, click elements, and fill forms using Playwright.",
)

WORK_DIR = os.environ.get("MCP_WORK_DIR", tempfile.gettempdir())
MAX_TEXT_CHARS = 12000

# --- SSRF Protection ---
# Block private/internal IP ranges and cloud metadata endpoints.
_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),     # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),             # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),            # IPv6 private
    ipaddress.ip_network("fe80::/10"),           # IPv6 link-local
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

    # Block known internal hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return f"Hostname '{hostname}' is blocked"

    # Resolve hostname to IP and check against blocked ranges
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
def browse_url(url: str, wait_seconds: int = 3) -> str:
    """Navigate to a URL and return the visible text content."""
    url_err = _validate_url(url)
    if url_err:
        return f"BLOCKED: {url_err}"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            page.wait_for_timeout(min(wait_seconds, 10) * 1000)
            text = page.inner_text("body")
            browser.close()
            return text[:MAX_TEXT_CHARS]
    except ImportError:
        return "ERROR: playwright not installed (run: playwright install chromium)"
    except Exception as e:
        log.exception("browse_url failed")
        return "ERROR: Failed to browse URL"


@server.tool()
def screenshot(url: str, full_page: bool = False) -> str:
    """Take a screenshot of a URL. Returns the file path of the saved PNG."""
    url_err = _validate_url(url)
    if url_err:
        return f"BLOCKED: {url_err}"
    try:
        from playwright.sync_api import sync_playwright
        out_path = os.path.join(WORK_DIR, "screenshot.png")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(url, timeout=15000)
            page.wait_for_timeout(2000)
            page.screenshot(path=out_path, full_page=full_page)
            browser.close()
        return f"Screenshot saved: {out_path}"
    except ImportError:
        return "ERROR: playwright not installed"
    except Exception as e:
        log.exception("screenshot failed")
        return "ERROR: Screenshot failed"


@server.tool()
def click_element(url: str, selector: str) -> str:
    """Navigate to a URL, click an element by CSS selector, and return resulting text."""
    url_err = _validate_url(url)
    if url_err:
        return f"BLOCKED: {url_err}"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            page.wait_for_timeout(1000)
            page.click(selector, timeout=5000)
            page.wait_for_timeout(2000)
            text = page.inner_text("body")
            browser.close()
            return text[:MAX_TEXT_CHARS]
    except Exception as e:
        log.exception("click_element failed")
        return "ERROR: Click failed"


@server.tool()
def fill_form(url: str, selector: str, value: str) -> str:
    """Navigate to a URL, fill a form field by CSS selector, and return page text."""
    url_err = _validate_url(url)
    if url_err:
        return f"BLOCKED: {url_err}"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            page.wait_for_timeout(1000)
            page.fill(selector, value, timeout=5000)
            page.wait_for_timeout(1000)
            text = page.inner_text("body")
            browser.close()
            return text[:MAX_TEXT_CHARS]
    except Exception as e:
        log.exception("fill_form failed")
        return "ERROR: Fill form failed"


if __name__ == "__main__":
    run_server(server)
