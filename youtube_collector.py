
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "youtube_posts.json"

SEARCH_QUERIES = [
    "Roma trasporto pubblico",
    "Roma raccolta rifiuti",
    "Roma emergenza abitativa",
    "Roma servizi comunali",
    "Roma sindaco politiche comunali",
]


def load_existing():
    if not OUTPUT_FILE.exists():
        return []

    try:
        return json.loads(
            OUTPUT_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        print("Existing output is invalid; starting fresh.")
        return []


def collect():
    api_key = os.getenv("YOUTUBE_API_KEY", "")

    if not api_key or api_key == "replace_with_your_actual_key":
        print("YouTube API key is not configured.")
        print("Set YOUTUBE_API_KEY in .env and run again.")
        return

    DATA_DIR.mkdir(exist_ok=True)
    youtube = build("youtube", "v3", developerKey=api_key)

    records = {item["id"]: item for item in load_existing()}

    for query in SEARCH_QUERIES:
        try:
            response = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                maxResults=10,
                regionCode="IT",
                relevanceLanguage="it",
            ).execute()

            for item in response.get("items", []):
                video_id = item["id"]["videoId"]
                snippet = item["snippet"]

                records[video_id] = {
                    "id": video_id,
                    "source": "youtube",
                    "record_type": "video_metadata",
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "published_at": snippet.get("publishedAt"),
                    "collected_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "query": query,
                    "url": (
                        "https://www.youtube.com/watch?v="
                        + video_id
                    ),
                }

        except HttpError as error:
            print(f"API error for '{query}': {error}")
            if error.resp.status in (401, 403):
                print(
                    "Check API-key validity, API restrictions, "
                    "permissions and quota."
                )
                break

    OUTPUT_FILE.write_text(
        json.dumps(
            list(records.values()),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(f"Unique videos saved: {len(records)}")
    print(f"Output: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    collect()
