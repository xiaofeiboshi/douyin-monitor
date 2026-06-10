"""
Main entry point for GitHub Actions.
Runs fetch -> format -> send email pipeline.
"""

import json
import sys
from pathlib import Path

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).parent))

from fetch_douyin import fetch_all_videos, format_for_email
from send_email import send_email


def main():
    print("=" * 50)
    print("Douyin Monitor - GitHub Actions")
    print("=" * 50)

    # Step 1: Fetch videos
    print("\n[1/2] Fetching videos from Douyin creators...")
    videos = fetch_all_videos()
    print(f"Found {len(videos)} new videos")

    # Step 2: Format and send email
    print("\n[2/2] Sending email notification...")
    email_body = format_for_email(videos)
    
    from datetime import datetime, timedelta, timezone
    sh_tz = timezone(timedelta(hours=8))
    now = datetime.now(sh_tz).strftime("%Y-%m-%d")
    
    subject = f"[抖音监控] {now} - {len(videos)}条新视频" if videos else f"[抖音监控] {now} - 无新视频"
    
    # Always send email (even if no new videos, to confirm the task ran)
    success = send_email(subject, email_body)

    # Save result for debugging
    result_path = Path(__file__).parent.parent / "data" / "last_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({
        "new_count": len(videos),
        "videos": videos,
        "email_body": email_body,
        "email_sent": success,
        "run_time": datetime.now(sh_tz).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if success:
        print("\nDone! Email sent successfully.")
    else:
        print("\nFailed to send email!")
        sys.exit(1)


if __name__ == "__main__":
    main()
