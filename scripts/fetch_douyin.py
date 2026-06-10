"""
Douyin video fetcher - GitHub Actions version.
Uses Playwright to scrape creator pages and extract video metadata.
Designed for Linux (GitHub Actions runner) environment.
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


SH_TZ = timezone(timedelta(hours=8))


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "creators.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def load_sent_history() -> dict:
    history_path = Path(__file__).parent.parent / "data" / "sent_history.json"
    if history_path.exists():
        return json.loads(history_path.read_text(encoding="utf-8"))
    return {"sent_video_ids": [], "last_run": None}


def save_sent_history(history: dict):
    history_path = Path(__file__).parent.parent / "data" / "sent_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_creator_videos(page, creator: dict, max_videos: int = 5) -> list[dict]:
    """Fetch videos from a single creator page."""
    url = creator["url"]
    name = creator.get("name", url.split("/")[-1][:20])
    videos = []

    try:
        print(f"  Fetching: {name} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)  # wait for JS rendering

        # Scroll down to load more content
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(1)

        # Strategy 1: Try video card links from the user profile
        selectors_to_try = [
            # Video cards on user profile page
            "a[href*='/video/']",
            "[class*='video-card'] a",
            "[class*='VideoCard']",
            "div[class*='videoFeed'] a",
            "div[class*='user-tab'] a[href*='/video/']",
            # New UI selectors
            "a[href*='www.douyin.com/video/']",
            "div[data-e2e='user-post-item']",
        ]

        video_links = []
        for selector in selectors_to_try:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    print(f"    Found {len(elements)} elements with selector: {selector}")
                    for el in elements[:max_videos * 2]:
                        href = el.get_attribute("href") or ""
                        text = el.inner_text().strip()[:200] if el.inner_text() else ""
                        if "/video/" in href:
                            video_links.append({"href": href, "text": text})
                    if video_links:
                        break
            except Exception as e:
                print(f"    Selector {selector} failed: {e}")
                continue

        # Strategy 2: Extract from page source if no structured elements found
        if not video_links:
            try:
                content = page.content()
                import re
                # Find video URLs in page source
                video_url_pattern = r'https://www\.douyin\.com/video/(\d+)'
                matches = re.findall(video_url_pattern, content)
                seen = set()
                for vid in matches[:max_videos]:
                    if vid not in seen:
                        seen.add(vid)
                        video_links.append({
                            "href": f"https://www.douyin.com/video/{vid}",
                            "text": "",
                        })
                if video_links:
                    print(f"    Found {len(video_links)} videos from page source")
            except Exception as e:
                print(f"    Page source extraction failed: {e}")

        # Strategy 3: Try extracting from __RENDER_DATA__ or window._SSR_HYDRATED_DATA
        if not video_links:
            try:
                render_data = page.evaluate("""() => {
                    try {
                        // Try __RENDER_DATA__
                        const renderEl = document.getElementById('RENDER_DATA');
                        if (renderEl) {
                            const decoded = decodeURIComponent(renderEl.textContent);
                            return decoded;
                        }
                    } catch(e) {}
                    try {
                        // Try _SSR_HYDRATED_DATA
                        if (window._SSR_HYDRATED_DATA) {
                            return JSON.stringify(window._SSR_HYDRATED_DATA);
                        }
                    } catch(e) {}
                    return '';
                }""")
                if render_data:
                    data = json.loads(render_data) if isinstance(render_data, str) and render_data else {}
                    # Navigate the data structure to find video list
                    video_ids = _extract_video_ids_from_data(data)
                    for vid in video_ids[:max_videos]:
                        video_links.append({
                            "href": f"https://www.douyin.com/video/{vid}",
                            "text": "",
                        })
                    if video_links:
                        print(f"    Found {len(video_ids)} videos from render data")
            except Exception as e:
                print(f"    Render data extraction failed: {e}")

        # Process found links into video objects
        for link in video_links[:max_videos]:
            href = link["href"]
            # Extract video ID from URL
            vid_id = ""
            if "/video/" in href:
                vid_id = href.split("/video/")[-1].split("?")[0].split("/")[0]

            # Try to get title from the video page (optional, may be slow)
            title = link.get("text", "") or f"Video {vid_id}"

            videos.append({
                "id": vid_id or href,
                "title": title[:100] if title else f"Video {vid_id}",
                "url": href if href.startswith("http") else f"https://www.douyin.com{href}",
                "creator_name": name,
            })

    except Exception as e:
        print(f"  Error fetching {name}: {e}")

    return videos


def _extract_video_ids_from_data(data, depth=0, max_depth=8) -> list[str]:
    """Recursively search for video IDs in the SSR/render data structure."""
    if depth > max_depth:
        return []
    ids = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("aweme_id", "awemeId", "video_id", "videoId") and isinstance(value, str) and value.isdigit():
                ids.append(value)
            elif isinstance(value, (dict, list)):
                ids.extend(_extract_video_ids_from_data(value, depth + 1, max_depth))
    elif isinstance(data, list):
        for item in data:
            ids.extend(_extract_video_ids_from_data(item, depth + 1, max_depth))
    return list(dict.fromkeys(ids))  # deduplicate preserving order


def fetch_all_videos() -> list[dict]:
    """Main entry: fetch videos from all configured creators."""
    config = load_config()
    creators = config.get("creators", [])
    settings = config.get("settings", {})
    max_videos = settings.get("max_videos_per_creator", 5)

    if not creators:
        print("No creators configured.")
        return []

    history = load_sent_history()
    sent_ids = set(history.get("sent_video_ids", []))

    # Calculate time window
    since_hours = settings.get("since_hours", 24)
    # Use last_run if available, otherwise use since_hours
    last_run = history.get("last_run")
    if last_run:
        try:
            since_time = datetime.fromisoformat(last_run)
        except (ValueError, TypeError):
            since_time = datetime.now(SH_TZ) - timedelta(hours=since_hours)
    else:
        since_time = datetime.now(SH_TZ) - timedelta(hours=since_hours)

    all_videos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = context.new_page()

        # Block unnecessary resources to speed up loading
        def route_handler(route):
            if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)

        for creator in creators:
            vids = fetch_creator_videos(page, creator, max_videos)
            # Filter out already-sent videos
            new_vids = [v for v in vids if v["id"] not in sent_ids]
            print(f"  {creator.get('name', '?')}: {len(vids)} found, {len(new_vids)} new")
            all_videos.extend(new_vids)

        browser.close()

    # Update sent history
    new_ids = [v["id"] for v in all_videos]
    history["sent_video_ids"] = (sent_ids | set(new_ids))
    # Keep only last 1000 IDs to prevent file from growing too large
    if len(history["sent_video_ids"]) > 1000:
        history["sent_video_ids"] = list(history["sent_video_ids"])[-1000:]
    history["last_run"] = datetime.now(SH_TZ).isoformat()
    save_sent_history(history)

    return all_videos


def format_for_email(videos: list[dict]) -> str:
    """Format video list into email body text."""
    if not videos:
        now = datetime.now(SH_TZ).strftime("%Y-%m-%d %H:%M")
        return f"抖音监控日报 - {now}\n\n今日没有检测到新视频更新。\n\n此邮件由 GitHub Actions 自动发送。"

    now = datetime.now(SH_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"抖音监控日报 - {now}", f"共检测到 {len(videos)} 条新视频：", ""]

    # Group by creator
    by_creator: dict[str, list] = {}
    for v in videos:
        name = v.get("creator_name", "未知博主")
        by_creator.setdefault(name, []).append(v)

    for name, vids in by_creator.items():
        lines.append(f"--- {name} ({len(vids)}条) ---")
        for i, v in enumerate(vids, 1):
            title = v.get("title", "无标题") or "无标题"
            url = v.get("url", "")
            lines.append(f"  {i}. {title}")
            lines.append(f"     链接: {url}")
        lines.append("")

    lines.append("---")
    lines.append("此邮件由 GitHub Actions 自动发送。")
    return "\n".join(lines)


if __name__ == "__main__":
    videos = fetch_all_videos()
    print(f"\nTotal new videos: {len(videos)}")
    email_body = format_for_email(videos)
    print(email_body)

    # Output summary for GitHub Actions
    summary_path = Path(__file__).parent.parent / "data" / "last_result.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({
        "new_count": len(videos),
        "videos": videos,
        "email_body": email_body,
        "run_time": datetime.now(SH_TZ).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
