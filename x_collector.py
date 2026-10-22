
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

OUTPUT = Path("data/x_posts.json")
ENDPOINT = "https://api.x.com/2/tweets/search/recent"

QUERIES = [
    'Roma (ATAC OR autobus OR metro OR trasporti) lang:it -is:retweet',
    'Roma (rifiuti OR AMA OR immondizia) lang:it -is:retweet',
    'Roma (affitti OR "case popolari" OR abitazioni) lang:it -is:retweet',
    'Roma (sindaco OR "Comune di Roma" OR "servizi pubblici") lang:it -is:retweet',
]


def load_existing():
    if not OUTPUT.exists():
        return []

    try:
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Expected a JSON list")
        return data
    except (json.JSONDecodeError, OSError, ValueError) as error:
        raise RuntimeError(
            f"Cannot safely read {OUTPUT}: {error}"
        ) from error


def collect():
    token = os.getenv("X_BEARER_TOKEN", "").strip()

    if not token:
        print(
            "Missing X_BEARER_TOKEN. Add your X Bearer Token "
            "to .env; no API request was made."
        )
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    end_time = datetime.now(timezone.utc).replace(microsecond=0)
    start_time = end_time - timedelta(hours=24)

    records = {str(p["id"]): p for p in load_existing() if "id" in p}
    headers = {"Authorization": f"Bearer {token}"}

    api_failed = False
    for query in QUERIES:
        params = {
            "query": query,
            "start_time": start_time.isoformat().replace("+00:00", "Z"),
            "end_time": end_time.isoformat().replace("+00:00", "Z"),
            "max_results": 100,
            "tweet.fields": "created_at,lang,public_metrics",
        }

        try:
            response = requests.get(
                ENDPOINT,
                headers=headers,
                params=params,
                timeout=30,
            )

            if response.status_code != 200:
                api_failed = True
                print(
                    f"X API returned HTTP {response.status_code} "
                    f"for query {query!r}: {response.text[:300]}"
                )
                continue

            payload = response.json()
            posts = payload.get("data", [])

            for post in posts:
                post_id = post["id"]
                records[post_id] = {
                    "id": post_id,
                    "source": "x",
                    "text": post.get("text", ""),
                    "created_at": post.get("created_at"),
                    "collected_at": end_time.isoformat(),
                    "language": post.get("lang"),
                    "public_metrics": post.get("public_metrics", {}),
                    "url": f"https://x.com/i/web/status/{post_id}",
                    "search_query": query,
                    "data_type": "real_api_post",
                }

            print(f"Query returned {len(posts)} posts.")

        except (requests.RequestException, ValueError) as error:
            print(f"Request or response error: {error}")

    if api_failed and not records:
        print("X collection failed; keeping the existing output file unchanged.")
        return

    OUTPUT.write_text(
        json.dumps(list(records.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Unique X posts stored: {len(records)}")
    print(f"Output file: {OUTPUT.resolve()}")


if __name__ == "__main__":
    collect()
