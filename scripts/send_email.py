"""
Notification sender - GitHub Actions version.
Primary: Create GitHub Issue (triggers email from GitHub automatically).
Fallback: SMTP email (for local runs or when GitHub API unavailable).
"""

import json
import os
import smtplib
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

SH_TZ = timezone(timedelta(hours=8))

# SMTP server configs (for local fallback)
SMTP_SERVERS = {
    "qq": {"host": "smtp.qq.com", "port": 465, "ssl": True},
    "163": {"host": "smtp.163.com", "port": 465, "ssl": True},
    "126": {"host": "smtp.126.com", "port": 465, "ssl": True},
    "gmail": {"host": "smtp.gmail.com", "port": 465, "ssl": True},
    "outlook": {"host": "smtp.office365.com", "port": 587, "ssl": False, "starttls": True},
}


def _is_github_actions() -> bool:
    """Check if running in GitHub Actions environment."""
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _get_github_token() -> str:
    """Get GitHub token from environment (auto-provided in Actions)."""
    return os.environ.get("GITHUB_TOKEN", "")


def _get_repo() -> str:
    """Get repo in owner/repo format from GITHUB_REPOSITORY env var."""
    return os.environ.get("GITHUB_REPOSITORY", "")


def create_github_issue(subject: str, body: str) -> bool:
    """Create a GitHub Issue to trigger email notification.
    
    GitHub automatically sends email to repo watchers/owners when an Issue is created.
    This works reliably from GitHub Actions since it uses HTTPS API (port 443),
    not SMTP which is blocked on Actions runners.
    """
    token = _get_github_token()
    repo = _get_repo()

    if not token or not repo:
        print("GitHub Issue: Missing GITHUB_TOKEN or GITHUB_REPOSITORY")
        return False

    url = f"https://api.github.com/repos/{repo}/issues"
    labels = ["douyin-monitor"]

    data = json.dumps({
        "title": subject,
        "body": body,
        "labels": labels,
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            issue_url = result.get("html_url", "")
            issue_number = result.get("number", "?")
            print(f"GitHub Issue #{issue_number} created: {issue_url}")
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"GitHub Issue creation failed (HTTP {e.code}): {err_body}")
        return False
    except Exception as e:
        print(f"GitHub Issue creation failed: {e}")
        return False


def close_old_monitor_issues() -> None:
    """Close previous douyin-monitor issues to keep the repo clean.
    Only keeps the latest issue open.
    """
    token = _get_github_token()
    repo = _get_repo()
    if not token or not repo:
        return

    url = (
        f"https://api.github.com/repos/{repo}/issues"
        f"?labels=douyin-monitor&state=open&per_page=10&sort=created&direction=desc"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            issues = json.loads(resp.read().decode("utf-8"))

        # Close all but skip the first one (most recent, just created)
        for issue in issues[1:]:
            close_url = f"https://api.github.com/repos/{repo}/issues/{issue['number']}"
            close_data = json.dumps({"state": "closed"}).encode("utf-8")
            close_headers = {**headers, "Content-Type": "application/json"}
            req = urllib.request.Request(
                close_url, data=close_data, headers=close_headers, method="PATCH"
            )
            urllib.request.urlopen(req, timeout=15)
            print(f"  Closed old issue #{issue['number']}")
    except Exception as e:
        print(f"  Warning: Could not close old issues: {e}")


def get_smtp_config() -> dict:
    """Get SMTP config from environment variables (set via GitHub Secrets)."""
    provider = os.environ.get("EMAIL_PROVIDER", "qq")
    smtp_user = os.environ.get("EMAIL_SMTP_USER", "")
    smtp_pass = os.environ.get("EMAIL_SMTP_PASS", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "")

    if not all([smtp_user, smtp_pass, recipient]):
        return {}

    server_cfg = SMTP_SERVERS.get(provider, SMTP_SERVERS["qq"])

    return {
        "provider": provider,
        "smtp_user": smtp_user,
        "smtp_pass": smtp_pass,
        "recipient": recipient,
        **server_cfg,
    }


def send_smtp_email(subject: str, body: str) -> bool:
    """Send email via SMTP (local fallback)."""
    cfg = get_smtp_config()
    if not cfg:
        print("SMTP: Missing email config in environment variables.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Douyin Monitor", cfg["smtp_user"]))
    msg["To"] = cfg["recipient"]

    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Simple HTML version
    html_body = f"""<html><body>
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
<pre style="white-space: pre-wrap; font-size: 14px; line-height: 1.6;">{body}</pre>
</div></body></html>"""
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        sent = False
        if cfg.get("ssl", True):
            try:
                server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30)
                server.login(cfg["smtp_user"], cfg["smtp_pass"])
                server.sendmail(cfg["smtp_user"], cfg["recipient"], msg.as_string())
                server.quit()
                sent = True
            except Exception as ssl_err:
                print(f"SMTP_SSL failed ({ssl_err}), trying STARTTLS on port 587...")

        if not sent:
            starttls_port = 587
            server = smtplib.SMTP(cfg["host"], starttls_port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg["smtp_user"], cfg["smtp_pass"])
            server.sendmail(cfg["smtp_user"], cfg["recipient"], msg.as_string())
            server.quit()
            sent = True

        print(f"SMTP email sent to {cfg['recipient']}")
        return True
    except Exception as e:
        print(f"SMTP failed: {e}")
        return False


def send_notification(subject: str, body: str) -> bool:
    """Send notification - uses GitHub Issue in Actions, SMTP as local fallback."""
    if _is_github_actions():
        print("Running in GitHub Actions - creating Issue notification...")
        success = create_github_issue(subject, body)
        if success:
            close_old_monitor_issues()
            return True
        else:
            print("GitHub Issue failed, trying SMTP fallback...")
            return send_smtp_email(subject, body)
    else:
        print("Running locally - sending SMTP email...")
        return send_smtp_email(subject, body)


if __name__ == "__main__":
    result_path = Path(__file__).parent.parent / "data" / "last_result.json"
    if not result_path.exists():
        print("No fetch result found. Run fetch_douyin.py first.")
        sys.exit(1)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    email_body = result.get("email_body", "")
    count = result.get("new_count", 0)

    now = datetime.now(SH_TZ).strftime("%Y-%m-%d")
    subject = f"[抖音监控] {now} - {count}条新视频" if count > 0 else f"[抖音监控] {now} - 无新视频"

    success = send_notification(subject, email_body)
    sys.exit(0 if success else 1)
