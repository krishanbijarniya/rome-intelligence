
import json
import re
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

NEWS_FILE = DATA_DIR / "news.json"
SOCIAL_FILE = DATA_DIR / "social_posts.json"
YOUTUBE_FILE = DATA_DIR / "youtube_posts.json"

st.set_page_config(
    page_title="Rome City Intelligence",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CATEGORIES
# ============================================================

CATEGORY_RULES = {
    "Public transport": [
        "trasport", "atac", "autobus", "bus", "metro",
        "metropolitana", "tram", "mobilita", "mobilità",
        "treno", "sciopero", "ferrovia", "pendolari",
    ],
    "Waste management": [
        "rifiut", "ama", "immondizia", "spazzatura",
        "raccolta differenziata", "discarica", "cassonetti",
        "degrado urbano",
    ],
    "Housing": [
        "affitt", "abitazion", "casa popolare",
        "case popolari", "emergenza abitativa", "alloggi",
        "sfratt", "casa",
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
        "inquinamento", "smog", "clima", "parco",
    ],
    "Public safety": [
        "sicurezza", "polizia locale", "criminalita",
        "criminalità", "incidenti", "illuminazione pubblica",
    ],
}

CATEGORY_OPTIONS = ["All categories", *CATEGORY_RULES.keys(), "Other"]


# ============================================================
# DATA LOADING
# ============================================================

def load_json(path):
    """Load a JSON file and return a list of records."""
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            return data.get("items", [])

        return []

    except (json.JSONDecodeError, OSError) as error:
        st.warning(f"Could not read {path.name}: {error}")
        return []


def first_value(record, *keys, default=""):
    """Return the first non-empty value from a record."""
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return value
    return default


def searchable_text(record):
    """Combine common text fields for searching and classification."""
    fields = [
        "title", "description", "summary", "text", "content",
        "headline", "query", "topic", "category", "message",
    ]

    return " ".join(
        str(record.get(field, ""))
        for field in fields
        if record.get(field) is not None
    ).lower()


def classify_record(record):
    """Assign a best-match category using simple keyword rules."""
    text = searchable_text(record)

    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in text for keyword in keywords):
            return category

    return "Other"


def normalise_news(records):
    """Standardise news records without discarding original fields."""
    output = []

    for record in records:
        item = dict(record)

        item["display_title"] = first_value(
            item, "title", "headline", "name",
            default="Untitled article",
        )

        item["display_source"] = first_value(
            item, "source", "publisher", "publication",
            default="Unknown source",
        )

        item["display_date"] = first_value(
            item, "published_at", "published", "date",
            default="",
        )

        item["display_url"] = first_value(
            item, "url", "link", "article_url",
            default="",
        )

        item["display_summary"] = first_value(
            item, "summary", "description", "content",
            default="",
        )

        # Prefer a category already assigned by classify_news.py.
        item["display_category"] = first_value(
            item, "topic", "category",
            default="",
        )

        if not item["display_category"]:
            item["display_category"] = classify_record(item)

        output.append(item)

    return output


def normalise_social(records):
    """Standardise social records, including test records."""
    output = []

    for record in records:
        item = dict(record)

        item["display_text"] = first_value(
            item, "text", "content", "message", "title",
            "description",
            default="No text available",
        )

        item["display_platform"] = first_value(
            item, "platform", "source",
            default="Unknown platform",
        )

        item["display_date"] = first_value(
            item, "published_at", "created_at",
            "collected_at", "date",
            default="",
        )

        item["display_url"] = first_value(
            item, "url", "link", "permalink",
            default="",
        )

        item["display_category"] = first_value(
            item, "topic", "category",
            default="",
        )

        if not item["display_category"]:
            item["display_category"] = classify_record(item)

        output.append(item)

    return output


def extract_youtube_id(record):
    """Extract a YouTube video ID from an ID field or URL."""
    raw_id = str(record.get("id", "")).strip()

    # A valid YouTube video ID has 11 URL-safe characters.
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw_id):
        return raw_id

    url = str(record.get("url", "")).strip()

    patterns = [
        r"(?:youtube\.com/watch\?.*?v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def normalise_youtube(records):
    """Standardise YouTube records and remove duplicate videos."""
    unique = {}

    for record in records:
        item = dict(record)

        video_id = extract_youtube_id(item)
        if not video_id:
            continue

        item["video_id"] = video_id
        item["video_url"] = (
            f"https://www.youtube.com/watch?v={video_id}"
        )

        item["display_title"] = first_value(
            item, "title",
            default="Untitled video",
        )

        item["display_date"] = first_value(
            item, "published_at", "published", "date",
            default="",
        )

        item["display_description"] = first_value(
            item, "description", "summary",
            default="",
        )

        item["display_category"] = classify_record(item)

        # If the same video was found by multiple searches,
        # retain one copy.
        unique[video_id] = item

    return list(unique.values())


# Load data once per Streamlit rerun.
news_records = normalise_news(load_json(NEWS_FILE))
social_records = normalise_social(load_json(SOCIAL_FILE))
youtube_records = normalise_youtube(load_json(YOUTUBE_FILE))


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.title("🏛️ Rome Intelligence")
    st.caption("City news and public discussion")

    st.divider()

    st.subheader("Data sources")
    st.write(f"📰 News articles: **{len(news_records)}**")
    st.write(f"💬 Social records: **{len(social_records)}**")
    st.write(f"▶️ YouTube videos: **{len(youtube_records)}**")

    st.divider()

    st.caption(
        "Categories are assigned using keyword rules. "
        "Results may need manual verification."
    )

    if st.button("🔄 Refresh dashboard", width="stretch"):
        st.rerun()


# ============================================================
# HEADER AND NAVIGATION
# ============================================================

st.title("Rome City Intelligence Dashboard")
st.caption(
    "Monitor news coverage and publicly available online content "
    "about Rome's civic services and local administration."
)

tab_overview, tab_news, tab_social, tab_youtube = st.tabs(
    [
        "📊 Overview",
        "📰 News analysis",
        "💬 Social discussion",
        "▶️ YouTube videos",
    ]
)


# ============================================================
# TAB 1 — OVERVIEW
# ============================================================

with tab_overview:
    st.header("Overview")

    metric1, metric2, metric3 = st.columns(3)

    metric1.metric("News articles", len(news_records))
    metric2.metric("Social records", len(social_records))
    metric3.metric("YouTube videos", len(youtube_records))

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("News by category")

        if news_records:
            news_df = pd.DataFrame(news_records)
            category_counts = (
                news_df["display_category"]
                .fillna("Other")
                .value_counts()
            )

            st.bar_chart(category_counts)
        else:
            st.info("No news data available yet.")

    with right:
        st.subheader("YouTube videos by category")

        if youtube_records:
            yt_df = pd.DataFrame(youtube_records)
            yt_counts = (
                yt_df["display_category"]
                .fillna("Other")
                .value_counts()
            )

            st.bar_chart(yt_counts)
        else:
            st.info(
                "No YouTube data available. "
                "Run youtube_collector.py to collect videos."
            )

    st.divider()

    st.subheader("Latest collected news")

    if news_records:
        latest_news = sorted(
            news_records,
            key=lambda item: str(item.get("display_date", "")),
            reverse=True,
        )[:10]

        for item in latest_news:
            title = item["display_title"]
            url = item["display_url"]
            category = item["display_category"]
            source = item["display_source"]

            if url:
                st.markdown(f"**[{title}]({url})**")
            else:
                st.markdown(f"**{title}**")

            st.caption(f"{source} · {category}")

            if item["display_summary"]:
                st.write(str(item["display_summary"])[:300])

            st.divider()
    else:
        st.info("No news records are available yet.")

    st.caption(
        "Article counts and video counts measure collected content, "
        "not the percentage of Rome residents who hold a view."
    )


# ============================================================
# TAB 2 — NEWS ANALYSIS
# ============================================================

with tab_news:
    st.header("News analysis")
    st.caption(
        "Browse collected news articles and filter by civic issue."
    )

    if not news_records:
        st.info(
            "No news records found. Run collector.py, "
            "then classify_news.py."
        )
    else:
        news_df = pd.DataFrame(news_records)

        filter_col, search_col = st.columns([1, 2])

        with filter_col:
            news_category = st.selectbox(
                "Category",
                CATEGORY_OPTIONS,
                key="news_category",
            )

        with search_col:
            news_search = st.text_input(
                "Search news",
                placeholder="Search titles, summaries, or publishers...",
                key="news_search",
            )

        filtered_news = news_df.copy()

        if news_category != "All categories":
            filtered_news = filtered_news[
                filtered_news["display_category"] == news_category
            ]

        if news_search.strip():
            mask = filtered_news.apply(
                lambda row: news_search.lower()
                in " ".join(str(value) for value in row.values).lower(),
                axis=1,
            )
            filtered_news = filtered_news[mask]

        st.write(f"**{len(filtered_news)}** matching articles")

        display_columns = [
            "display_date",
            "display_title",
            "display_source",
            "display_category",
            "display_url",
        ]

        available_columns = [
            column for column in display_columns
            if column in filtered_news.columns
        ]

        st.dataframe(
            filtered_news[available_columns],
            width="stretch",
            hide_index=True,
            column_config={
                "display_date": st.column_config.TextColumn(
                    "Published"
                ),
                "display_title": st.column_config.TextColumn(
                    "Title",
                    width="large",
                ),
                "display_source": st.column_config.TextColumn(
                    "Source"
                ),
                "display_category": st.column_config.TextColumn(
                    "Category"
                ),
                "display_url": st.column_config.LinkColumn(
                    "Article",
                    display_text="Open article",
                ),
            },
        )

        st.subheader("Category distribution")
        category_counts = (
            filtered_news["display_category"]
            .fillna("Other")
            .value_counts()
        )

        if not category_counts.empty:
            st.bar_chart(category_counts)


# ============================================================
# TAB 3 — SOCIAL DISCUSSION
# ============================================================

with tab_social:
    st.header("Social discussion")
    st.caption(
        "Browse records from configured social sources. "
        "The available records depend on which collectors have run."
    )

    if not social_records:
        st.info(
            "No social records found in data/social_posts.json. "
            "Configure a source collector before expecting live posts."
        )
    else:
        social_df = pd.DataFrame(social_records)

        filter_col, platform_col = st.columns(2)

        with filter_col:
            social_category = st.selectbox(
                "Issue category",
                CATEGORY_OPTIONS,
                key="social_category",
            )

        with platform_col:
            platforms = sorted(
                social_df["display_platform"]
                .fillna("Unknown platform")
                .astype(str)
                .unique()
            )

            selected_platform = st.selectbox(
                "Source / platform",
                ["All platforms", *platforms],
                key="social_platform",
            )

        social_search = st.text_input(
            "Search posts",
            placeholder="Search post text or keywords...",
            key="social_search",
        )

        filtered_social = social_df.copy()

        if social_category != "All categories":
            filtered_social = filtered_social[
                filtered_social["display_category"] == social_category
            ]

        if selected_platform != "All platforms":
            filtered_social = filtered_social[
                filtered_social["display_platform"] == selected_platform
            ]

        if social_search.strip():
            mask = filtered_social["display_text"].astype(str).str.contains(
                social_search,
                case=False,
                na=False,
                regex=False,
            )
            filtered_social = filtered_social[mask]

        st.write(f"**{len(filtered_social)}** matching records")

        for _, post in filtered_social.iterrows():
            st.markdown(
                f"**{post.get('display_platform', 'Unknown platform')}**"
                f" · {post.get('display_category', 'Other')}"
            )

            st.write(post.get("display_text", "No text available"))

            if post.get("display_date"):
                st.caption(str(post["display_date"]))

            url = post.get("display_url", "")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                st.markdown(f"[Open original post]({url})")

            st.divider()

    st.caption(
        "Social posts are not representative polling. "
        "Check each source's authenticity, terms, and collection method. "
        "Clearly distinguish test records from real public content."
    )
from urllib.parse import quote

st.header("X — Public Discussion")

searches = {
    "Public transport": 'Roma (ATAC OR autobus OR metro OR trasporti)',
    "Waste management": 'Roma (rifiuti OR AMA OR immondizia)',
    "Housing": 'Roma (affitti OR "case popolari" OR abitazioni)',
    "City government": 'Roma (sindaco OR Campidoglio OR "Comune di Roma")',
}

for category, query in searches.items():
    st.subheader(category)
    url = "https://x.com/search?q=" + quote(query) + "&src=typed_query"
    st.markdown(f"[Search public posts on X ↗]({url})")

# ============================================================
# TAB 4 — YOUTUBE VIDEOS
# ============================================================

with tab_youtube:
    st.header("YouTube — Rome Civic Issues")
    st.write(
        "Watch collected videos about Rome's transport, waste management, "
        "housing, public services, environment, and local government."
    )

    if not youtube_records:
        st.warning(
            "No playable YouTube videos found. "
            "Run youtube_collector.py and check data/youtube_posts.json."
        )
    else:
        metric1, metric2 = st.columns(2)

        metric1.metric("Playable videos", len(youtube_records))

        categories_present = len({
            video["display_category"]
            for video in youtube_records
        })

        metric2.metric("Categories represented", categories_present)

        st.divider()

        filter_col, search_col = st.columns([1, 2])

        with filter_col:
            youtube_category = st.selectbox(
                "Filter by category",
                CATEGORY_OPTIONS,
                key="youtube_category",
            )

        with search_col:
            youtube_search = st.text_input(
                "Search videos",
                placeholder="e.g. ATAC, rifiuti, case popolari...",
                key="youtube_search",
            )

        filtered_videos = youtube_records.copy()

        if youtube_category != "All categories":
            filtered_videos = [
                video for video in filtered_videos
                if video["display_category"] == youtube_category
            ]

        if youtube_search.strip():
            term = youtube_search.strip().lower()

            filtered_videos = [
                video for video in filtered_videos
                if term in (
                    str(video.get("display_title", "")) + " "
                    + str(video.get("display_description", "")) + " "
                    + str(video.get("query", ""))
                ).lower()
            ]

        # Sort by publication date, newest first.
        filtered_videos.sort(
            key=lambda video: str(video.get("display_date", "")),
            reverse=True,
        )

        st.write(f"**{len(filtered_videos)}** matching videos")

        if not filtered_videos:
            st.info(
                "No videos match your filters. "
                "Try a different category or search term."
            )
        else:
            # Two video players per row.
            for start in range(0, len(filtered_videos), 2):
                columns = st.columns(2)

                for column, video in zip(
                    columns,
                    filtered_videos[start:start + 2],
                ):
                    with column:
                        st.markdown(
                            f"### {video['display_title']}"
                        )

                        st.caption(
                            f"Category: {video['display_category']}"
                        )

                        # Streamlit embeds the actual YouTube player.
                        st.video(video["video_url"])

                        published = video.get("display_date", "")

                        if published:
                            try:
                                parsed_date = datetime.fromisoformat(
                                    str(published).replace("Z", "+00:00")
                                )

                                st.caption(
                                    "Published: "
                                    + parsed_date.strftime("%d %b %Y")
                                )
                            except ValueError:
                                st.caption(f"Published: {published}")

                        query = video.get("query", "")
                        if query:
                            st.caption(f"Collected via search: {query}")

                        st.markdown(
                            f"[Open on YouTube]({video['video_url']})"
                        )

                        description = video.get(
                            "display_description", ""
                        )

                        if description:
                            with st.expander("Video description"):
                                st.write(description[:2000])

                        st.divider()

    st.caption(
        "Video categories are assigned with keyword rules and may "
        "misclassify videos. Videos can be older than the collection date."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Rome City Intelligence · Aggregated public content for civic issue "
    "monitoring. Collected content is not a representative measure of "
    "public opinion."
)
