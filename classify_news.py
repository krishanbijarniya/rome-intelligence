
import json
import re
from pathlib import Path
from collections import Counter

INPUT_FILE = Path("data/news.json")

KEYWORDS = {
    "public_transport": [
        "trasport", "atac", "metro", "metropolitana",
        "autobus", "bus", "treno", "treni", "mobilità",
        "mobilita", "tram", "viabilità", "viabilita"
    ],
    "housing": [
        "casa", "case popolari", "affitto", "affitti",
        "abitazion", "edilizia residenziale", "sfratto",
        "sfratti", "alloggi"
    ],
    "waste_management": [
        "rifiuti", "ama", "raccolta differenziata",
        "spazzatura", "discarica", "riciclo", "immondizia"
    ],
    "public_safety": [
        "sicurezza", "polizia", "carabinieri", "furto",
        "furti", "rapina", "rapine", "incidente",
        "incidenti", "criminalità", "criminalita"
    ],
    "environment": [
        "ambiente", "inquinamento", "smog", "verde pubblico",
        "parchi", "alberi", "clima", "alluvione"
    ],
    "public_services": [
        "sanità", "sanita", "ospedale", "ospedali",
        "scuola", "scuole", "servizi pubblici",
        "manutenzione", "marciapiedi"
    ],
    "politics_government": [
        "comune di roma", "sindaco", "giunta",
        "assemblea capitolina", "consiglio comunale",
        "municipio", "delibera", "bilancio comunale"
    ]
}


def classify_title(title):
    text = title.casefold()
    scores = {}

    for topic, keywords in KEYWORDS.items():
        scores[topic] = sum(
            1 for keyword in keywords
            if re.search(
                r"(?<!\w)" + re.escape(keyword) + r"(?!\w)",
                text
            )
        )

    best_topic = max(scores, key=scores.get)

    if scores[best_topic] == 0:
        return "other"

    return best_topic


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Missing input file: {INPUT_FILE}"
        )

    records = json.loads(
        INPUT_FILE.read_text(encoding="utf-8")
    )

    for record in records:
        record["topic"] = classify_title(
            record.get("title", "")
        )

    INPUT_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    counts = Counter(
        record["topic"] for record in records
    )

    print(f"Classified {len(records)} articles.")
    print("\nArticles by topic:")

    for topic, count in counts.most_common():
        print(f"{topic}: {count}")


if __name__ == "__main__":
    main()
