import json
import re
import subprocess
import sys
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
NEWS_FILE = DATA_DIR / "news.json"
SOCIAL_FILE = DATA_DIR / "social_posts.json"
X_FILE = DATA_DIR / "x_posts.json"
META_FILE = DATA_DIR / "meta_posts.json"
YOUTUBE_FILE = DATA_DIR / "youtube_posts.json"
MUNICIPI_FILE = DATA_DIR / "municipi.geojson"

st.set_page_config(
    page_title="Rome City Intelligence",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Colosseum-inspired full-page background. The dark overlay keeps text readable.
st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background-image: linear-gradient(
            120deg, rgba(7, 12, 20, 0.90), rgba(7, 12, 20, 0.70)
        ), url("https://commons.wikimedia.org/wiki/Special:FilePath/Colosseum-panoramic.view.jpg?width=1920");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    [data-testid="stHeader"] {
        background: rgba(7, 12, 20, 0.35);
    }
    [data-testid="stSidebar"] {
        background: rgba(10, 16, 25, 0.88);
        border-right: 1px solid rgba(255, 255, 255, 0.10);
    }
    [data-testid="stMainBlockContainer"] {
        background: rgba(8, 13, 22, 0.28);
        border-radius: 18px;
        padding-top: 1.5rem;
    }
    h1, h2, h3, p, label, [data-testid="stMetricLabel"] {
        text-shadow: 0 1px 8px rgba(0, 0, 0, 0.30);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

CATEGORY_RULES = {
    "Public transport": [
        "trasport", "atac", "autobus", "bus", "metro", "metropolitana",
        "tram", "mobilita", "treno", "sciopero", "ferrovia", "pendolari",
    ],
    "Waste management": [
        "rifiut", "ama", "immondizia", "spazzatura",
        "raccolta differenziata", "discarica", "cassonetti", "degrado urbano",
    ],
    "Housing": [
        "affitt", "abitazion", "casa popolare", "case popolari",
        "emergenza abitativa", "alloggi", "sfratt",
    ],
    "City government": [
        "sindaco", "comune di roma", "campidoglio",
        "assemblea capitolina", "giunta comunale",
        "politiche comunali", "amministrazione capitolina",
    ],
    "Public services": [
        "servizi comunali", "servizi pubblici", "municipio",
        "anagrafe", "scuola", "asilo nido", "uffici comunali",
    ],
    "Environment": [
        "ambiente", "verde pubblico", "parchi", "alberi",
        "inquinamento", "smog", "clima",
    ],
    "Public safety": [
        "sicurezza", "polizia locale", "criminalita",
        "incidenti", "illuminazione pubblica",
    ],
}
CATEGORY_OPTIONS = ["All categories", *CATEGORY_RULES.keys(), "Other"]
TOPIC_LABELS = {
    "public_transport": "Public transport",
    "waste_management": "Waste management",
    "housing": "Housing",
    "politics_government": "City government",
    "public_services": "Public services",
    "public_safety": "Public safety",
    "environment": "Environment",
    "other": "Other",
}
POSITIVE_WORDS = {
    "migliora", "migliorato", "successo", "positivo", "positiva",
    "bene", "buono", "buona", "nuovo", "nuova", "potenziato", "potenziati",
    "approvato", "approvata", "apertura", "apre", "vittoria",
}
NEGATIVE_WORDS = {
    "problema", "problemi", "ritardo", "ritardi", "sciopero", "disagi",
    "disagio", "emergenza", "crisi", "rifiuti", "spazzatura", "incidente",
    "incidenti", "furto", "furti", "sfratto", "sfratti", "inquinamento",
    "protesta", "proteste", "multa", "carenza", "guasto", "guasti",
}


# ============================================================
# DATA AND TEXT HELPERS
# ============================================================

def load_json(path):
    """Read a JSON list. Missing or invalid files return an empty list."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items", [])
            return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError) as error:
        st.warning(f"Could not read {path.name}: {error}")
    return []


def first_value(record, *keys, default=""):
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return value
    return default


def searchable_text(record):
    fields = (
        "title", "description", "summary", "text", "content",
        "headline", "query", "topic", "category", "message",
        "display_title", "display_summary", "display_description",
        "display_text",
    )
    return " ".join(
        str(record.get(field, ""))
        for field in fields
        if record.get(field) is not None
    ).lower()


def classify_record(record):
    text = searchable_text(record)
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "Other"


def display_category(value, record):
    label = TOPIC_LABELS.get(str(value).strip().casefold())
    if label:
        return label
    if value and str(value).strip().casefold() in {
        option.casefold() for option in CATEGORY_RULES
    }:
        return str(value).strip()
    return classify_record(record)


def sentiment_label(record):
    text = searchable_text(record)
    words = set(re.findall(r"[a-zàèéìòù]+", text.casefold()))
    score = len(words & POSITIVE_WORDS) - len(words & NEGATIVE_WORDS)
    if score > 0:
        return "Positive"
    if score < 0:
        return "Negative"
    return "Neutral"


def normalise_news(records):
    output = []
    for record in records:
        item = dict(record)
        item["display_title"] = first_value(
            item, "title", "headline", "name", default="Untitled article"
        )
        item["display_source"] = first_value(
            item,
            "source_name",
            "source",
            "publisher",
            "publication",
            default="Unknown source",
        )
        item["display_date"] = first_value(
            item, "published_at", "published", "date", default=""
        )
        item["display_url"] = first_value(
            item, "url", "link", "article_url", default=""
        )
        item["display_summary"] = first_value(
            item, "summary", "description", "content", default=""
        )
        item["display_category"] = display_category(
            first_value(item, "topic", "category", default=""), item
        )
        item["display_sentiment"] = sentiment_label(item)
        output.append(item)
    return output


def normalise_social(records):
    output = []
    for record in records:
        item = dict(record)
        item["display_text"] = first_value(
            item, "text", "content", "message", "title", "description",
            default="No text available",
        )
        item["display_platform"] = first_value(
            item, "platform", "source", default="Unknown platform"
        )
        item["display_date"] = first_value(
            item, "published_at", "created_at", "collected_at", "date", default=""
        )
        item["display_url"] = first_value(
            item, "url", "link", "permalink", default=""
        )
        item["display_category"] = display_category(
            first_value(item, "topic", "category", default=""), item
        )
        item["display_sentiment"] = sentiment_label(item)
        output.append(item)
    return output


def extract_youtube_id(record):
    raw_id = str(record.get("id", "")).strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw_id):
        return raw_id
    url = str(record.get("url", "")).strip()
    patterns = (
        r"(?:youtube\.com/watch\?.*?v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def normalise_youtube(records):
    unique = {}
    for record in records:
        item = dict(record)
        video_id = extract_youtube_id(item)
        if not video_id:
            continue
        item["video_id"] = video_id
        item["video_url"] = f"https://www.youtube.com/watch?v={video_id}"
        item["display_title"] = first_value(item, "title", default="Untitled video")
        item["display_date"] = first_value(
            item, "published_at", "published", "date", default=""
        )
        item["display_description"] = first_value(
            item, "description", "summary", default=""
        )
        item["display_category"] = display_category(
            first_value(item, "topic", "category", default=""), item
        )
        item["display_sentiment"] = sentiment_label(item)
        unique[video_id] = item
    return list(unique.values())


def normalise_place_text(value):
    value = str(value or "").lower().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value)


# ============================================================
# MUNICIPIO BOUNDARIES AND GEOGRAPHIC MATCHING
# ============================================================

def load_municipi_features():
    """Load the 15 Rome Municipi and exclude the Vatican feature."""
    if not MUNICIPI_FILE.exists():
        return []
    try:
        with MUNICIPI_FILE.open("r", encoding="utf-8") as file:
            geojson = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        st.warning(f"Could not read Municipio boundaries: {error}")
        return []

    features = []
    for original in geojson.get("features", []):
        feature = deepcopy(original)
        props = feature.get("properties") or {}
        if str(props.get("CITTA", "")).strip().lower() != "roma":
            continue
        raw_id = str(props.get("MUNICIPIO", "")).strip()
        if not raw_id.isdigit():
            continue
        feature["_municipio_id"] = int(raw_id)
        feature["_municipio_name"] = (
            props.get("DENOMINAZI") or f"Municipio {raw_id}"
        )
        feature.setdefault("properties", {})["_display_name"] = feature["_municipio_name"]
        features.append(feature)

    # Deduplicate by Municipio ID in case the source has duplicate records.
    by_id = {feature["_municipio_id"]: feature for feature in features}
    return [by_id[key] for key in sorted(by_id)]


def municipio_place_names(feature):
    props = feature.get("properties", {})
    names = set()
    for field in ("QUARTIERI", "ZONE", "SUBURBI", "RIONI"):
        value = props.get(field)
        if not value:
            continue
        for part in str(value).split(","):
            name = normalise_place_text(part)
            if len(name) >= 4 and name not in {
                "roma", "italia", "municipio", "della", "delle", "degli"
            }:
                names.add(name)
    return sorted(names, key=len, reverse=True)


def detect_municipio(record, features):
    """
    Match text against place names from the boundary dataset.
    This is a heuristic, not authoritative geocoding.
    """
    text = normalise_place_text(searchable_text(record))
    matches = set()
    for feature in features:
        for place in municipio_place_names(feature):
            # Word-boundary matching prevents short names matching inside words.
            pattern = r"(?<!\w)" + re.escape(place) + r"(?!\w)"
            if re.search(pattern, text):
                matches.add(feature["_municipio_name"])
                break
    return next(iter(matches)) if len(matches) == 1 else "Unassigned / Rome-wide"


def make_municipio_map(features, selected_name):
    map_object = folium.Map(
        location=[41.90, 12.50],
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True,
    )

    def style_feature(feature):
        name = (feature.get("properties") or {}).get("_display_name", "")
        selected = name == selected_name
        return {
            "fillColor": "#f59e0b" if selected else "#3388ff",
            "color": "#d97706" if selected else "#ffffff",
            "weight": 3 if selected else 1.2,
            "fillOpacity": 0.55 if selected else 0.20,
        }

    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Rome Municipi",
        style_function=style_feature,
        highlight_function=lambda feature: {
            "weight": 3,
            "fillOpacity": 0.6,
            "color": "#f97316",
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["_display_name"],
            aliases=["Municipio:"],
            sticky=True,
        ),
        popup=folium.GeoJsonPopup(
            fields=["_display_name"],
            aliases=["Municipio:"],
        ),
    ).add_to(map_object)
    folium.LayerControl().add_to(map_object)
    return map_object


def safe_url(url):
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def refresh_data():
    """Collect and classify fresh data before rendering the dashboard."""
    commands = (
        ("news", "collector.py"),
        ("X", "x_collector.py"),
        ("Facebook and Instagram", "meta_collector.py"),
        ("YouTube", "youtube_collector.py"),
        ("classification", "classify_news.py"),
    )
    for source_name, script_name in commands:
        try:
            result = subprocess.run(
                [sys.executable, script_name],
                cwd=BASE_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = f"{result.stdout}\n{result.stderr}".casefold()
            status_terms = (
                "credits depleted",
                "collection failed",
                "failed:",
                "not configured",
                "missing ",
                "no meta source succeeded",
            )
            if any(term in output for term in status_terms):
                st.warning(
                    f"{source_name} update unavailable. Existing records were kept."
                )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            st.warning(f"Could not refresh {source_name} data: {error}")


def build_event_frame(news, social, youtube):
    rows = []
    for item in news:
        rows.append({
            "Event date": item.get("display_date", ""),
            "Source": item.get("display_source", "News"),
            "Content type": "News",
            "Category": item.get("display_category", "Other"),
            "Sentiment": item.get("display_sentiment", "Neutral"),
            "Title": item.get("display_title", "Untitled article"),
            "URL": item.get("display_url", ""),
        })
    for item in social:
        rows.append({
            "Event date": item.get("display_date", ""),
            "Source": item.get("display_platform", "Social"),
            "Content type": "Social",
            "Category": item.get("display_category", "Other"),
            "Sentiment": item.get("display_sentiment", "Neutral"),
            "Title": item.get("display_text", "No text available"),
            "URL": item.get("display_url", ""),
        })
    for item in youtube:
        rows.append({
            "Event date": item.get("display_date", ""),
            "Source": "YouTube",
            "Content type": "Video",
            "Category": item.get("display_category", "Other"),
            "Sentiment": item.get("display_sentiment", "Neutral"),
            "Title": item.get("display_title", "Untitled video"),
            "URL": item.get("video_url", ""),
        })
    events = pd.DataFrame(rows)
    if events.empty:
        events["Parsed date"] = pd.Series(dtype="datetime64[ns, UTC]")
        return events
    events["Parsed date"] = pd.to_datetime(
        events["Event date"], errors="coerce", utc=True
    )
    events["Event date"] = events["Parsed date"].dt.date
    return events.sort_values("Parsed date", ascending=False)


def render_news_card(item):
    title = str(item.get("display_title", "Untitled article"))
    url = item.get("display_url", "")
    if safe_url(url):
        st.markdown(f"**[{title}]({url})**")
    else:
        st.markdown(f"**{title}**")
    st.caption(
        f"{item.get('display_source', 'Unknown source')} · "
        f"{item.get('display_category', 'Other')} · "
        f"{item.get('display_date', '')}"
    )
    summary = item.get("display_summary", "")
    if summary:
        st.write(str(summary)[:400])


# Load all data after all helper functions have been defined.
refresh_data()
news_records = normalise_news(load_json(NEWS_FILE))
social_records = normalise_social(
    load_json(SOCIAL_FILE) + load_json(X_FILE) + load_json(META_FILE)
)
youtube_records = normalise_youtube(load_json(YOUTUBE_FILE))
municipio_features = load_municipi_features()
event_frame = build_event_frame(news_records, social_records, youtube_records)


# ============================================================
# SIDEBAR AND NAVIGATION
# ============================================================

with st.sidebar:
    st.title("🏛️ Rome Intelligence")
    st.caption("City news and public discussion")
    st.divider()
    st.subheader("Data sources")
    st.write(f"📰 News articles: **{len(news_records)}**")
    st.write(f"💬 Social records: **{len(social_records)}**")
    st.write(f"▶️ YouTube videos: **{len(youtube_records)}**")
    st.write(f"🗺️ Municipio boundaries: **{len(municipio_features)} / 15**")
    st.divider()
    st.subheader("Dashboard filters")
    available_dates = event_frame["Event date"].dropna()
    if available_dates.empty:
        default_dates = (datetime.now().date(), datetime.now().date())
    else:
        default_dates = (available_dates.min(), available_dates.max())
    date_range = st.date_input("Date range", value=default_dates)
    selected_sources = st.multiselect(
        "Sources",
        sorted(event_frame["Source"].dropna().unique()),
        default=sorted(event_frame["Source"].dropna().unique()),
    )
    selected_categories = st.multiselect(
        "Categories",
        sorted(event_frame["Category"].dropna().unique()),
        default=sorted(event_frame["Category"].dropna().unique()),
    )
    selected_sentiments = st.multiselect(
        "Sentiment",
        ["Positive", "Neutral", "Negative"],
        default=["Positive", "Neutral", "Negative"],
    )
    st.caption("Sentiment is a keyword-based signal, not representative polling.")

filtered_events = event_frame.copy()
if isinstance(date_range, tuple) and len(date_range) == 2:
    filtered_events = filtered_events[
        filtered_events["Event date"].between(date_range[0], date_range[1])
    ]
if selected_sources:
    filtered_events = filtered_events[filtered_events["Source"].isin(selected_sources)]
if selected_categories:
    filtered_events = filtered_events[
        filtered_events["Category"].isin(selected_categories)
    ]
if selected_sentiments:
    filtered_events = filtered_events[
        filtered_events["Sentiment"].isin(selected_sentiments)
    ]

st.title("Rome City Intelligence Dashboard")
st.caption(
    "Explore news coverage and public online content about Rome's civic "
    "services and local administration."
)

tab_overview, tab_news, tab_social, tab_youtube, tab_map = st.tabs(
    [
        "📊 Overview",
        "📰 News analysis",
        "💬 Social discussion",
        "▶️ YouTube videos",
        "🗺️ Municipio Map",
    ]
)


# ============================================================
# TAB 1 — OVERVIEW
# ============================================================

with tab_overview:
    st.header("Rome civic intelligence")
    st.caption("A cross-source view of news, public discussion, events, and sentiment.")
    metric_row = st.container(horizontal=True)
    with metric_row:
        st.metric("Tracked events", len(filtered_events), border=True)
        st.metric(
            "News coverage",
            int((filtered_events["Content type"] == "News").sum()),
            border=True,
        )
        st.metric(
            "Social signals",
            int((filtered_events["Content type"] == "Social").sum()),
            border=True,
        )
        st.metric(
            "Video coverage",
            int((filtered_events["Content type"] == "Video").sum()),
            border=True,
        )

    if filtered_events.empty:
        st.warning("No events match the current dashboard filters.")
    else:
        trend_col, sentiment_col = st.columns(2)
        with trend_col:
            with st.container(border=True):
                st.subheader("Coverage over time")
                trend = (
                    filtered_events.groupby("Event date")
                    .size()
                    .rename("Events")
                    .sort_index()
                )
                st.line_chart(trend, alt="Number of tracked events over time")
        with sentiment_col:
            with st.container(border=True):
                st.subheader("Sentiment mix")
                sentiment_counts = (
                    filtered_events["Sentiment"].value_counts()
                    .reindex(["Positive", "Neutral", "Negative"], fill_value=0)
                )
                st.bar_chart(sentiment_counts, alt="Events grouped by sentiment")

        category_col, source_col = st.columns(2)
        with category_col:
            with st.container(border=True):
                st.subheader("Issues attracting attention")
                category_counts = filtered_events["Category"].value_counts()
                st.bar_chart(category_counts, alt="Events grouped by civic issue")
        with source_col:
            with st.container(border=True):
                st.subheader("Coverage by source")
                source_counts = filtered_events["Source"].value_counts().head(12)
                st.bar_chart(source_counts, alt="Events grouped by source")

        st.subheader("Latest tracked events")
        display_events = filtered_events[
            ["Event date", "Source", "Content type", "Category", "Sentiment", "Title", "URL"]
        ].head(50)
        st.dataframe(
            display_events,
            width="stretch",
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Open", display_text="View source"),
            },
        )
        st.download_button(
            "Download filtered events",
            data=filtered_events.to_csv(index=False).encode("utf-8"),
            file_name="rome_intelligence_events.csv",
            mime="text/csv",
            icon=":material/download:",
        )
    st.caption("Counts describe collected content volume; they do not measure public opinion.")


# ============================================================
# TAB 2 — NEWS ANALYSIS
# ============================================================

with tab_news:
    st.header("News analysis")
    if not news_records:
        st.info("No news records found. Run collector.py and classify_news.py.")
    else:
        filter_col, search_col = st.columns([1, 2])
        with filter_col:
            news_category = st.selectbox(
                "Category", CATEGORY_OPTIONS, key="news_category"
            )
        with search_col:
            news_search = st.text_input(
                "Search news", placeholder="Search titles or summaries...",
                key="news_search",
            )

        filtered_news = news_records.copy()
        if news_category != "All categories":
            filtered_news = [
                item for item in filtered_news
                if item["display_category"] == news_category
            ]
        if news_search.strip():
            term = news_search.lower()
            filtered_news = [
                item for item in filtered_news
                if term in searchable_text(item)
            ]

        st.write(f"**{len(filtered_news)}** matching articles")
        rows = [
            {
                "Published": item.get("display_date", ""),
                "Title": item.get("display_title", ""),
                "Source": item.get("display_source", ""),
                "Category": item.get("display_category", ""),
                "Article URL": item.get("display_url", ""),
            }
            for item in filtered_news
        ]
        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Article URL": st.column_config.LinkColumn(
                        "Article", display_text="Open article"
                    )
                },
            )
            st.subheader("Category distribution")
            st.bar_chart(pd.Series(
                [item["display_category"] for item in filtered_news]
            ).value_counts())


# ============================================================
# TAB 3 — SOCIAL DISCUSSION AND X SEARCH
# ============================================================

with tab_social:
    st.header("Social discussion")
    if not social_records:
        st.info(
            "No records found in data/social_posts.json. "
            "Configure a permitted source collector to add real posts."
        )
    else:
        filter_col, platform_col = st.columns(2)
        with filter_col:
            social_category = st.selectbox(
                "Issue category", CATEGORY_OPTIONS, key="social_category"
            )
        platforms = sorted({str(item["display_platform"]) for item in social_records})
        with platform_col:
            selected_platform = st.selectbox(
                "Source / platform", ["All platforms", *platforms],
                key="social_platform",
            )
        social_search = st.text_input("Search posts", key="social_search")
        filtered_social = social_records.copy()
        if social_category != "All categories":
            filtered_social = [
                item for item in filtered_social
                if item["display_category"] == social_category
            ]
        if selected_platform != "All platforms":
            filtered_social = [
                item for item in filtered_social
                if item["display_platform"] == selected_platform
            ]
        if social_search.strip():
            term = social_search.lower()
            filtered_social = [
                item for item in filtered_social
                if term in str(item.get("display_text", "")).lower()
            ]
        st.write(f"**{len(filtered_social)}** matching records")
        for item in filtered_social:
            st.markdown(
                f"**{item['display_platform']}** · {item['display_category']}"
            )
            st.write(item["display_text"])
            if item.get("display_date"):
                st.caption(str(item["display_date"]))
            if safe_url(item.get("display_url", "")):
                st.markdown(f"[Open original post]({item['display_url']})")
            st.divider()

    st.caption(
        "Social posts are not representative polling. Distinguish test records "
        "from real public content and respect source terms."
    )
    st.divider()
    st.subheader("𝕏 — Public discussion search")
    st.caption("These links open X search results; they do not collect or save posts.")
    x_searches = {
        "Public transport": "Roma (ATAC OR autobus OR metro OR trasporti)",
        "Waste management": "Roma (rifiuti OR AMA OR immondizia)",
        "Housing": 'Roma (affitti OR "case popolari" OR abitazioni)',
        "City government": 'Roma (sindaco OR Campidoglio OR "Comune di Roma")',
    }
    for category, query in x_searches.items():
        url = "https://x.com/search?q=" + quote(query) + "&src=typed_query"
        st.markdown(f"**{category}**")
        st.markdown(f"[Search public posts on X ↗]({url})")


# ============================================================
# TAB 4 — YOUTUBE VIDEOS
# ============================================================

with tab_youtube:
    st.header("YouTube — Rome Civic Issues")
    st.caption("Videos are embedded from YouTube; playback requires an internet connection.")
    if not youtube_records:
        st.warning("No playable videos found. Run youtube_collector.py.")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Playable videos", len(youtube_records))
        col2.metric(
            "Categories represented",
            len({item["display_category"] for item in youtube_records}),
        )
        filter_col, search_col = st.columns([1, 2])
        with filter_col:
            youtube_category = st.selectbox(
                "Filter by category", CATEGORY_OPTIONS, key="youtube_category"
            )
        with search_col:
            youtube_search = st.text_input(
                "Search videos", placeholder="ATAC, rifiuti, case popolari...",
                key="youtube_search",
            )
        filtered_videos = youtube_records.copy()
        if youtube_category != "All categories":
            filtered_videos = [
                item for item in filtered_videos
                if item["display_category"] == youtube_category
            ]
        if youtube_search.strip():
            term = youtube_search.lower()
            filtered_videos = [
                item for item in filtered_videos
                if term in searchable_text(item)
            ]
        filtered_videos.sort(
            key=lambda item: str(item.get("display_date", "")), reverse=True
        )
        st.write(f"**{len(filtered_videos)}** matching videos")
        for start in range(0, len(filtered_videos), 2):
            columns = st.columns(2)
            for column, video in zip(columns, filtered_videos[start:start + 2]):
                with column:
                    st.markdown(f"### {video['display_title']}")
                    st.caption(f"Category: {video['display_category']}")
                    st.video(video["video_url"])
                    if video.get("display_date"):
                        try:
                            parsed = datetime.fromisoformat(
                                str(video["display_date"]).replace("Z", "+00:00")
                            )
                            st.caption("Published: " + parsed.strftime("%d %b %Y"))
                        except ValueError:
                            st.caption(f"Published: {video['display_date']}")
                    if video.get("query"):
                        st.caption(f"Collected via search: {video['query']}")
                    st.markdown(f"[Open on YouTube]({video['video_url']})")
                    description = video.get("display_description", "")
                    if description:
                        with st.expander("Video description"):
                            st.write(str(description)[:2000])
                    st.divider()


# ============================================================
# TAB 5 — INTERACTIVE MUNICIPIO MAP
# ============================================================

with tab_map:
    st.header("Rome — Municipio Intelligence")
    st.write(
        "Choose one of Rome's 15 Municipi to view matching news and videos. "
        "The boundary map supports hover and popups; use the selector below "
        "to change the selected Municipio and update the results."
    )

    if not municipio_features:
        st.error(
            "No Municipio boundaries loaded. Check that "
            "data/municipi.geojson exists and contains valid GeoJSON."
        )
    else:
        if len(municipio_features) != 15:
            st.warning(
                f"Expected 15 Municipi, but loaded {len(municipio_features)}. "
                "Please verify data/municipi.geojson."
            )

        municipio_names = [
            feature["_municipio_name"] for feature in municipio_features
        ]
        default_name = st.session_state.get(
            "municipio_selector", municipio_names[0]
        )
        if default_name not in municipio_names:
            default_name = municipio_names[0]

        selected_municipio = st.selectbox(
            "Select Municipio",
            municipio_names,
            index=municipio_names.index(default_name),
            key="municipio_selector",
        )

        map_object = make_municipio_map(municipio_features, selected_municipio)
        st_folium(
            map_object,
            height=560,
            use_container_width=True,
            key="rome_municipio_map",
        )

        st.info(
            f"Selected area: **{selected_municipio}**. "
            "The selected boundary is highlighted in orange."
        )

        tagged_news = [
            {**item, "_matched_municipio": detect_municipio(item, municipio_features)}
            for item in news_records
        ]
        tagged_videos = [
            {**item, "_matched_municipio": detect_municipio(item, municipio_features)}
            for item in youtube_records
        ]

        matching_news = [
            item for item in tagged_news
            if item["_matched_municipio"] == selected_municipio
        ]
        matching_videos = [
            item for item in tagged_videos
            if item["_matched_municipio"] == selected_municipio
        ]
        unmatched_news = [
            item for item in tagged_news
            if item["_matched_municipio"] == "Unassigned / Rome-wide"
        ]
        unmatched_videos = [
            item for item in tagged_videos
            if item["_matched_municipio"] == "Unassigned / Rome-wide"
        ]

        metric1, metric2 = st.columns(2)
        metric1.metric("Matching news articles", len(matching_news))
        metric2.metric("Matching YouTube videos", len(matching_videos))

        st.divider()
        news_column, video_column = st.columns(2)

        with news_column:
            st.subheader("📰 Local news")
            if not matching_news:
                st.info(
                    "No articles explicitly matched this Municipio. "
                    "This does not mean there are no local issues."
                )
            for item in matching_news:
                render_news_card(item)
                st.divider()

        with video_column:
            st.subheader("▶️ YouTube videos")
            if not matching_videos:
                st.info(
                    "No videos explicitly matched this Municipio. "
                    "Check the unassigned section for Rome-wide content."
                )
            for item in matching_videos:
                st.markdown(f"**{item['display_title']}**")
                st.video(item["video_url"])
                if item.get("display_date"):
                    st.caption(f"Published: {item['display_date']}")
                st.markdown(f"[Open on YouTube]({item['video_url']})")
                st.divider()

        with st.expander("Unassigned / Rome-wide content"):
            st.caption(
                "Items without a unique match to a known neighborhood remain "
                "unassigned. This is a limitation of text-based matching, not "
                "evidence that the item is irrelevant to a Municipio."
            )
            st.write(
                f"Unassigned news: **{len(unmatched_news)}** · "
                f"Unassigned videos: **{len(unmatched_videos)}**"
            )
            if unmatched_news:
                st.markdown("**News headlines**")
                for item in unmatched_news[:15]:
                    st.write(f"• {item.get('display_title', 'Untitled')}")
            if unmatched_videos:
                st.markdown("**Video titles**")
                for item in unmatched_videos[:15]:
                    st.write(f"• {item.get('display_title', 'Untitled')}")


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.caption(
    "Rome City Intelligence · Aggregated public content for civic issue "
    "monitoring. Geographic and topic assignments are heuristic. Collected "
    "content is not a representative measure of public opinion."
)
