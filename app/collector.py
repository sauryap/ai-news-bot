"""Collection step: fetch all feeds, apply level-1 dedup, store new articles."""
import logging
from typing import Tuple

from app import database
from app.deduplicator import deterministic_dedupe
from app.feeds import fetch_all_feeds
from app.models import Article

logger = logging.getLogger(__name__)


def collect_articles() -> Tuple[int, int]:
    """
    Fetch every configured feed, drop exact duplicates, and store the rest.

    Returns (num_new_articles, num_total_fetched).
    """
    logger.info("Collecting RSS feeds...")
    raw_articles = fetch_all_feeds()

    unique_articles = deterministic_dedupe(raw_articles)

    inserted = 0
    for article_dict in unique_articles:
        article = Article(
            id=None,
            title=article_dict["title"],
            url=article_dict["url"],
            source=article_dict["source"],
            author=article_dict.get("author"),
            published_at=article_dict.get("published_at"),
            description=article_dict.get("description"),
            category=article_dict.get("category"),
            content_hash=article_dict["content_hash"],
        )
        if database.insert_article(article) is not None:
            inserted += 1

    logger.info("Stored %d new articles (after dedup) out of %d fetched", inserted, len(raw_articles))
    return inserted, len(raw_articles)
