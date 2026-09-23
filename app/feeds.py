"""
RSS/Atom feed fetching and normalization.

Wraps `feedparser` so the rest of the app deals with a small, predictable
dict shape instead of feedparser's loosely-typed entries. Every feed is
fetched independently and defensively - one broken feed never raises out of
this module.
"""
import hashlib
import logging
import socket
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser
import requests

from app import config

logger = logging.getLogger(__name__)

USER_AGENT = "TechIntelligence/1.0 (personal RSS reader; +https://github.com/)"

# Query params that are pure tracking noise and safe to strip when
# normalizing a URL for duplicate detection.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
    "cmpid", "guccounter", "guce_referrer", "guce_referrer_sig",
}


def normalize_url(url: str) -> str:
    """Lowercase scheme/host, drop tracking params and fragments, strip trailing slash."""
    if not url:
        return url
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower() or "https"
        netloc = parts.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parts.path.rstrip("/") or ""
        query_pairs = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
        query = urlencode(sorted(query_pairs))
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return url.strip()


def make_content_hash(title: str, url: str) -> str:
    normalized_title = " ".join((title or "").lower().split())
    normalized = f"{normalized_title}|{normalize_url(url)}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_published(entry) -> Optional[str]:
    """Best-effort extraction of a publish date as an ISO 8601 string."""
    for field in ("published_parsed", "updated_parsed"):
        struct_time = getattr(entry, field, None)
        if struct_time:
            try:
                dt = datetime(*struct_time[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                continue
    return None


def _extract_description(entry) -> str:
    for field in ("summary", "description"):
        value = getattr(entry, field, None)
        if value:
            return value
    if getattr(entry, "content", None):
        try:
            return entry.content[0].value
        except Exception:
            pass
    return ""


def _extract_author(entry) -> Optional[str]:
    author = getattr(entry, "author", None)
    if author:
        return author
    return None


def fetch_feed(name: str, url: str, category: str, max_articles: int) -> List[Dict]:
    """Fetch and normalize a single feed. Never raises - returns [] on any failure."""
    articles: List[Dict] = []
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=config.FEED_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_bytes = response.content
    except requests.exceptions.RequestException as exc:
        logger.warning("Feed '%s' unreachable (%s): %s", name, url, exc)
        return articles
    except socket.timeout:
        logger.warning("Feed '%s' timed out: %s", name, url)
        return articles

    try:
        parsed = feedparser.parse(raw_bytes)
    except Exception as exc:
        logger.warning("Feed '%s' failed to parse: %s", name, exc)
        return articles

    if parsed.bozo and not getattr(parsed, "entries", None):
        logger.warning(
            "Feed '%s' malformed and produced no entries: %s", name, parsed.get("bozo_exception")
        )
        return articles

    entries = parsed.entries[:max_articles]
    for entry in entries:
        try:
            title = (getattr(entry, "title", "") or "").strip()
            link = (getattr(entry, "link", "") or "").strip()
            if not title or not link:
                continue
            description = _extract_description(entry).strip()
            articles.append({
                "title": title,
                "url": link,
                "source": name,
                "author": _extract_author(entry),
                "published_at": _parse_published(entry),
                "description": description,
                "category": category,
                "content_hash": make_content_hash(title, link),
            })
        except Exception as exc:
            logger.warning("Feed '%s': skipping malformed entry (%s)", name, exc)
            continue

    logger.info("%s: %d articles", name, len(articles))
    return articles


def fetch_all_feeds() -> List[Dict]:
    """Fetch every configured feed, tolerating individual failures."""
    all_articles: List[Dict] = []
    for name, url, category in config.FEEDS:
        try:
            articles = fetch_feed(name, url, category, config.MAX_ARTICLES_PER_FEED)
            all_articles.extend(articles)
        except Exception as exc:
            # Belt-and-suspenders: a single feed must never take down collection.
            logger.error("Unexpected error fetching feed '%s': %s", name, exc)
            continue
    logger.info("Total collected: %d", len(all_articles))
    return all_articles
