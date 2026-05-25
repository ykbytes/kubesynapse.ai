"""MCP Messaging sidecar — send emails and Slack messages."""

import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server, check_egress_url

# Basic rate-limiting state: last send timestamp per recipient.
_last_sent: dict[str, float] = {}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SMTP_HOST_ALLOWLIST = os.environ.get("ALLOWED_SMTP_HOSTS", "").strip()

server = create_mcp_server(
    "mcp-messaging",
    "Send emails (SMTP) and Slack messages.",
)


@server.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    smtp_host: str = "",
    smtp_port: int = 587,
) -> str:
    """Send an email via SMTP. Uses SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS env vars as defaults."""
    import smtplib
    from email.mime.text import MIMEText

    host = smtp_host or os.environ.get("SMTP_HOST", "")
    port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")

    if not host:
        return "ERROR: SMTP_HOST not configured"
    if not user:
        return "ERROR: SMTP_USER not configured"

    if not _EMAIL_RE.match(to):
        return "ERROR: Invalid recipient email address"

    if _SMTP_HOST_ALLOWLIST:
        allowed_hosts = {h.strip() for h in _SMTP_HOST_ALLOWLIST.split(",") if h.strip()}
        if host not in allowed_hosts:
            return f"ERROR: SMTP host '{host}' is not in the allowlist"

    now = time.time()
    if now - _last_sent.get(to, 0) < 10:
        return f"ERROR: Rate limit exceeded for {to}. Please wait before retrying."
    _last_sent[to] = now

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to

        with smtplib.SMTP(host, port, timeout=15) as srv:
            srv.starttls()
            srv.login(user, password)
            srv.sendmail(user, [to], msg.as_string())
        return f"Email sent to {to}"
    except Exception as e:
        return f"ERROR: Failed to send email: {e}"


@server.tool()
def send_slack_message(channel: str, text: str) -> str:
    """Send a message to a Slack channel. Requires SLACK_TOKEN env var."""
    try:
        from slack_sdk import WebClient
        token = os.environ.get("SLACK_TOKEN", "")
        if not token:
            return "ERROR: SLACK_TOKEN not set"
        client = WebClient(token=token)
        resp = client.chat_postMessage(channel=channel, text=text)
        return f"Slack message sent to {channel} (ts: {resp['ts']})"
    except ImportError:
        return "ERROR: slack_sdk not installed"
    except Exception as e:
        return f"ERROR: Slack send failed: {e}"


@server.tool()
def list_slack_channels() -> str:
    """List public Slack channels. Requires SLACK_TOKEN env var."""
    try:
        from slack_sdk import WebClient
        token = os.environ.get("SLACK_TOKEN", "")
        if not token:
            return "ERROR: SLACK_TOKEN not set"
        client = WebClient(token=token)
        resp = client.conversations_list(types="public_channel", limit=50)
        channels = resp.get("channels", [])
        if not channels:
            return "(no channels found)"
        return "\n".join(f"#{c['name']} (id: {c['id']})" for c in channels)
    except ImportError:
        return "ERROR: slack_sdk not installed"
    except Exception as e:
        return f"ERROR: Slack list failed: {e}"


if __name__ == "__main__":
    run_server(server)
