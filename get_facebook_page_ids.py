"""
Resolve Facebook Page IDs for entries in facebook_sources.json using Meta Graph API.

Usage:
  pip install requests python-dotenv
  # Put META_ACCESS_TOKEN=... in .env
  python get_facebook_page_ids.py

Notes:
- Uses each source's facebook_url to derive the Page username/URL.
- Sources with blank facebook_url are skipped; fill in their official Page URLs first.
- Meta may deny lookups for Pages you don't manage unless the app has the required
  public Page metadata/content access. This script does not bypass permissions.
- Review each result before relying on it; redirects and non-Page URLs can fail.
"""

import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "facebook_sources.json"
TOKEN = os.getenv("META_ACCESS_TOKEN", "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
VERSION = os.getenv("META_GRAPH_API_VERSION", "v26.0").strip()
API_BASE = f"https://graph.facebook.com/{VERSION}"


def graph_params(**params):
    params["access_token"] = TOKEN
    if APP_SECRET:
        params["appsecret_proof"] = hmac.new(
            APP_SECRET.encode(), TOKEN.encode(), hashlib.sha256
        ).hexdigest()
    return params
MANAGED_PAGES_FILE = BASE_DIR / "meta_pages.json"


def extract_page_username(url: str) -> str | None:
    """Extract a candidate Page username from a Facebook URL."""
    if not url or not url.strip():
        return None

    url = url.strip()
    if not url.startswith(("https://", "http://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"facebook.com", "m.facebook.com", "web.facebook.com", "fb.com"}:
        return None

    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return None

    # Common Facebook routes that are not Page usernames.
    reserved = {
        "watch", "events", "groups", "photo", "photos", "videos", "reel",
        "reels", "stories", "share", "sharer", "login", "help", "business",
        "marketplace", "people", "profile.php", "permalink.php",
    }
    first = parts[0]
    if first.lower() in reserved or first.lower().startswith("profile.php"):
        return None

    # Numeric page IDs in a URL may already be the ID.
    if first.isdigit():
        return first

    # Query-style profile.php?id=... URLs are handled separately.
    if first.lower() == "profile.php":
        return None

    return first


def resolve_page(username_or_id: str) -> dict:
    response = requests.get(
        f"{API_BASE}/{username_or_id}",
        params={
            "fields": "id,name",
            **graph_params(),
        },
        timeout=25,
    )

    try:
        body = response.json()
    except ValueError:
        body = {"error": {"message": response.text[:500]}}

    if not response.ok or "error" in body:
        error = body.get("error", {})
        return {
            "ok": False,
            "lookup": username_or_id,
            "http_status": response.status_code,
            "error": error.get("message", f"HTTP {response.status_code}"),
            "error_code": error.get("code"),
        }

    return {
        "ok": True,
        "lookup": username_or_id,
        "id": str(body.get("id", "")),
        "name": body.get("name", ""),
    }


def fetch_managed_pages() -> list[dict]:
    """Return every Facebook Page available to the current token."""
    response = requests.get(
        f"{API_BASE}/me/accounts",
        params={
            "fields": "id,name,access_token,instagram_business_account",
            "limit": 100,
            **graph_params(),
        },
        timeout=25,
    )
    body = response.json()
    if not response.ok or "error" in body:
        error = body.get("error", {})
        raise RuntimeError(error.get("message", f"HTTP {response.status_code}"))
    return [page for page in body.get("data", []) if page.get("id")]


def main() -> int:
    if not TOKEN:
        print("ERROR: META_ACCESS_TOKEN is missing.")
        print("Add META_ACCESS_TOKEN=your_token to a .env file in this folder.")
        return 2

    try:
        managed_pages = fetch_managed_pages()
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        print(f"MANAGED PAGES FAILED: {exc}")
        managed_pages = []
    else:
        safe_pages = [
            {
                "id": str(page["id"]),
                "name": page.get("name", ""),
                "instagram_business_account": (
                    page.get("instagram_business_account") or {}
                ),
            }
            for page in managed_pages
        ]
        MANAGED_PAGES_FILE.write_text(
            json.dumps(safe_pages, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"MANAGED PAGES: found {len(safe_pages)} page(s)")
        for page in safe_pages:
            instagram_id = page["instagram_business_account"].get("id")
            suffix = f"; Instagram ID {instagram_id}" if instagram_id else ""
            print(f"  {page['name']} — Page ID {page['id']}{suffix}")

    if not SOURCES_FILE.exists():
        print(f"ERROR: Cannot find {SOURCES_FILE}")
        print("Put this script in the same folder as facebook_sources.json.")
        return 2

    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Could not read JSON: {exc}")
        return 2

    sources = data.get("sources", [])
    if not isinstance(sources, list):
        print("ERROR: JSON field 'sources' must be a list.")
        return 2

    successes = 0
    failures = 0
    skipped = 0

    for source in sources:
        name = source.get("name", "(unnamed source)")
        url = source.get("facebook_url", "")
        candidate = extract_page_username(url)

        if not candidate:
            print(f"\nSKIP  {name}: no usable facebook_url. Add the official Page URL first.")
            skipped += 1
            continue

        print(f"\nLOOKUP {name}: {candidate}")
        result = resolve_page(candidate)

        if result["ok"]:
            # Only fill a blank ID automatically; don't silently replace existing IDs.
            existing_id = str(source.get("page_id", "")).strip()
            if not existing_id:
                source["page_id"] = result["id"]
            source["resolved_name"] = result["name"]
            source["lookup_status"] = "resolved" if not existing_id else "resolved_checked"
            print(f"  OK: {result['name']} — ID {result['id']}")
            if existing_id and existing_id != result["id"]:
                print(f"  WARNING: Existing ID ({existing_id}) differs; it was not overwritten.")
            successes += 1
        else:
            source["lookup_status"] = "needs_manual_verification"
            source["lookup_error"] = result["error"]
            if result.get("error_code") is not None:
                source["lookup_error_code"] = result["error_code"]
            print(f"  FAILED: {result['error']}")
            if result.get("error_code") == 100:
                print("  Hint: check the URL/username and whether your app has the required access.")
            failures += 1

    # Save an updated copy, retaining all existing fields.
    output_file = SOURCES_FILE.with_name("facebook_sources_resolved.json")
    output_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\n--- Summary ---")
    print(f"Resolved/looked up: {successes}")
    print(f"Failed: {failures}")
    print(f"Skipped (missing/unsupported URL): {skipped}")
    print(f"Output: {output_file}")
    print("Review IDs and source names before using them in production.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
