"""
Email sender - GitHub Actions version.
Reads SMTP credentials from environment variables (GitHub Secrets).
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

SH_TZ = timezone(timedelta(hours=8))

# SMTP server configs
SMTP_SERVERS = {
    "qq": {"host": "smtp.qq.com", "port": 465, "ssl": True},
    "163": {"host": "smtp.163.com", "port": 465, "ssl": True},
    "126": {"host": "smtp.126.com", "port": 465, "ssl": True},
    "gmail": {"host": "smtp.gmail.com", "port": 465, "ssl": True},
    "outlook": {"host": "smtp.office365.com", "port": 587, "ssl": False, "starttls": True},
}


def get_smtp_config() -> dict:
    """Get SMTP config from environment variables (set via GitHub Secrets)."""
    provider = os.environ.get("EMAIL_PROVIDER", "qq")
    smtp_user = os.environ.get("EMAIL_SMTP_USER", "")
    smtp_pass = os.environ.get("EMAIL_SMTP_PASS", "")
    recipient = os.environ.get("EMAIL_RECIPIENT", "")

    if not all([smtp_user, smtp_pass, recipient]):
        print("ERROR: Missing email config in environment variables.")
        print("Required: EMAIL_SMTP_USER, EMAIL_SMTP_PASS, EMAIL_RECIPIENT")
        sys.exit(1)

    server_cfg = SMTP_SERVERS.get(provider, SMTP_SERVERS["qq"])

    return {
        "provider": provider,
        "smtp_user": smtp_user,
        "smtp_pass": smtp_pass,
        "recipient": recipient,
        **server_cfg,
    }


def send_email(subject: str, body: str, html_body: str = "") -> bool:
    """Send email using configured SMTP server."""
    cfg = get_smtp_config()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Douyin Monitor", cfg["smtp_user"]))
    msg["To"] = cfg["recipient"]

    # Plain text version
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # HTML version (better rendering in email clients)
    if not html_body:
        html_body = f"""<html><body>
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
<pre style="white-space: pre-wrap; font-size: 14px; line-height: 1.6;">{body}</pre>
</div></body></html>"""
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        # Try SMTP_SSL first (port 465), fallback to STARTTLS (port 587)
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

        print(f"Email sent successfully to {cfg['recipient']}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


if __name__ == "__main__":
    # Read result from fetch_douyin.py output
    result_path = Path(__file__).parent.parent / "data" / "last_result.json"
    if not result_path.exists():
        print("No fetch result found. Run fetch_douyin.py first.")
        sys.exit(1)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    email_body = result.get("email_body", "")
    count = result.get("new_count", 0)

    now = datetime.now(SH_TZ).strftime("%Y-%m-%d")
    subject = f"[抖音监控] {now} - {count}条新视频" if count > 0 else f"[抖音监控] {now} - 无新视频"

    success = send_email(subject, email_body)
    sys.exit(0 if success else 1)
