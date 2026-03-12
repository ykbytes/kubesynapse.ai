"""MCP Browser sidecar — browse web pages, take screenshots, interact with forms."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-browser",
    "Browse web pages, take screenshots, click elements, and fill forms using Playwright.",
)

WORK_DIR = os.environ.get("MCP_WORK_DIR", tempfile.gettempdir())
MAX_TEXT_CHARS = 12000


@server.tool()
def browse_url(url: str, wait_seconds: int = 3) -> str:
    """Navigate to a URL and return the visible text content."""
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
        return f"ERROR: Failed to browse URL: {e}"


@server.tool()
def screenshot(url: str, full_page: bool = False) -> str:
    """Take a screenshot of a URL. Returns the file path of the saved PNG."""
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
        return f"ERROR: Screenshot failed: {e}"


@server.tool()
def click_element(url: str, selector: str) -> str:
    """Navigate to a URL, click an element by CSS selector, and return resulting text."""
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
        return f"ERROR: Click failed: {e}"


@server.tool()
def fill_form(url: str, selector: str, value: str) -> str:
    """Navigate to a URL, fill a form field by CSS selector, and return page text."""
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
        return f"ERROR: Fill form failed: {e}"


if __name__ == "__main__":
    run_server(server)
