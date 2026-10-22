
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import feedparser

DATA_DIR = Path("data")
OUTPUT_FILE = DATA_DIR / "news.json"

FEED_URL = (
    "https://news.google.com/rss/search?"
    "q=Roma+trasporti+OR+mobilita&hl=it&gl=IT&ceid=IT:it"
)


def collect_news():
    
    DATA_DIR.mkdir(exist_ok=True)

    request = Request(
        FEED_URL,
        headers={"User-Agent": "RomeNewsResearch/1.0"}
    )

    with urlopen(request, timeout=30) as response:
        feed_content = response.read()

    feed = feedparser.parse(feed_content)

    if feed.bozo and not feed.entries:
        raise RuntimeError("Could not parse the RSS feed.")

    if OUTPUT_FILE.exists():
        existing = json.loads(
            OUTPUT_FILE.read_text(encoding="utf-8")
        )
    else:
        existing = []

    records = {item["id"]: item for item in existing}

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()

        if not title or not url:
            continue

        record_id = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:16]

        records[record_id] = {
            "id": record_id,
            "source_type": "news",
            "source_name": entry.get(
                "source", {}
            ).get("title", "News RSS"),
            "title": title,
            "url": url,
            "published_at": entry.get("published"),
            "collected_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "city": "Roma",
            "language": "it",
            "topic": "unclassified"
        }

    OUTPUT_FILE.write_text(
        json.dumps(
            list(records.values()),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(f"Feed entries received: {len(feed.entries)}")
    print(f"Unique articles saved: {len(records)}")
    print(f"Output file: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    try:
        collect_news()
    except Exception as error:
        print(f"Collection failed: {error}")
