import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

OUTPUT = Path("data/meta_posts.json")
MANAGED_PAGES_FILE = Path("meta_pages.json")
GRAPH_VERSION = os.getenv("META_GRAPH_API_VERSION", "v22.0")
PAGE_IDS = [
    page_id.strip()
    for page_id in os.getenv("META_PAGE_IDS", os.getenv("META_PAGE_ID", "")).split(",")
    if page_id.strip()
]
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()


def graph_params(**params):
    params["access_token"] = TOKEN
    if APP_SECRET:
        params["appsecret_proof"] = hmac.new(
            APP_SECRET.encode(), TOKEN.encode(), hashlib.sha256
        ).hexdigest()
    return params


def load_existing():
    if not OUTPUT.exists():
        return {}
    try:
        records = json.loads(OUTPUT.read_text(encoding="utf-8"))
        return {str(item["id"]): item for item in records if isinstance(item, dict) and item.get("id")}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def fetch(url, params):
    params = graph_params(**params)
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("data", [])


def collect():
    managed_pages = []
    if MANAGED_PAGES_FILE.exists():
        try:
            managed_pages = json.loads(MANAGED_PAGES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            managed_pages = []
    page_ids = list(dict.fromkeys(PAGE_IDS + [str(page.get("id")) for page in managed_pages if page.get("id")]))

    if not TOKEN or (not page_ids and not INSTAGRAM_USER_ID):
        print(
            "Meta collector is not configured: set META_ACCESS_TOKEN and "
            "META_PAGE_ID or a numeric INSTAGRAM_USER_ID; keeping existing data."
        )
        return

    if INSTAGRAM_USER_ID and not INSTAGRAM_USER_ID.isdigit():
        print(
            "INSTAGRAM_USER_ID must be the numeric Instagram Business/Creator "
            "account ID, not a username; keeping existing data."
        )
        return

    records = load_existing()
    base_url = f"https://graph.facebook.com/{GRAPH_VERSION}"
    collected_at = datetime.now(timezone.utc).isoformat()

    endpoints = []
    for page_id in page_ids:
        endpoints.append((f"{base_url}/{page_id}/feed", "Facebook"))
    instagram_ids = [INSTAGRAM_USER_ID] if INSTAGRAM_USER_ID else []
    instagram_ids.extend(
        str(page.get("instagram_business_account", {}).get("id"))
        for page in managed_pages
        if page.get("instagram_business_account", {}).get("id")
    )
    for instagram_id in dict.fromkeys(instagram_ids):
        if instagram_id.isdigit():
            endpoints.append((f"{base_url}/{instagram_id}/media", "Instagram"))

    succeeded = False
    for endpoint, platform in endpoints:
        try:
            fields = "id,message,created_time,permalink_url" if platform == "Facebook" else "id,caption,timestamp,permalink"
            for item in fetch(endpoint, {"access_token": TOKEN, "fields": fields, "limit": 100}):
                text = item.get("message") or item.get("caption") or ""
                records[str(item["id"])] = {
                    "id": str(item["id"]),
                    "source": platform,
                    "text": text,
                    "created_at": item.get("created_time") or item.get("timestamp"),
                    "collected_at": collected_at,
                    "url": item.get("permalink_url") or item.get("permalink"),
                    "data_type": "real_api_post",
                }
            succeeded = True
        except (requests.RequestException, KeyError, ValueError) as error:
            print(f"{platform} collection failed: {error}")

    if not succeeded:
        print("No Meta source succeeded; keeping the existing output file unchanged.")
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(list(records.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Meta records stored: {len(records)}")


if __name__ == "__main__":
    collect()