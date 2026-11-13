
import feedparser
import pandas as pd
import requests
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

NSE_RSS_URL = (
    "https://nsearchives.nseindia.com/"
    "content/RSS/Online_announcements.xml"
)

def classify_announcement(title):
    text = title.lower()

    categories = [
        ("management_change", [
            "resignation", "appointment", "director",
            "change in management"
        ]),
        ("M&A", [
            "acquisition", "merger", "amalgamation",
            "joint venture"
        ]),
        ("results", [
            "financial results", "quarterly results",
            "earnings"
        ]),
        ("litigation", [
            "litigation", "penalty", "regulatory order"
        ]),
        ("dividend", ["dividend"]),
        ("credit_rating", ["credit rating"]),
        ("capex", ["capacity expansion", "new plant"]),
    ]

    for category, keywords in categories:
        if any(word in text for word in keywords):
            return category

    return "unclassified"


def assign_priority(category):
    high = {
        "management_change", "M&A",
        "results", "litigation"
    }
    medium = {
        "dividend", "credit_rating", "capex"
    }

    if category in high:
        return "High"
    if category in medium:
        return "Medium"
    return "Low"


def fetch_live_announcements():
    headers = {
        "User-Agent": "FINN-Pulse/1.0",
        "Accept": "application/rss+xml, application/xml"
    }

    response = requests.get(
        NSE_RSS_URL,
        headers=headers,
        timeout=20
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if feed.bozo and not feed.entries:
        raise ValueError("Could not parse NSE RSS feed")

    rows = []

    for entry in feed.entries:
        title = entry.get("title", "Untitled")
        category = classify_announcement(title)

        published = entry.get("published", "")
        try:
            timestamp = parsedate_to_datetime(published)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(
                    tzinfo=timezone.utc
                )
            published = timestamp.isoformat()
        except (TypeError, ValueError, IndexError):
            published = ""

        rows.append({
            "title": title,
            "category": category,
            "priority": assign_priority(category),
            "published": published,
            "source": "NSE RSS",
            "url": entry.get("link", "")
        })

    return pd.DataFrame(
        rows,
        columns=[
            "title", "category", "priority",
            "published", "source", "url"
        ]
    )
