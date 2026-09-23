"""
Two-level deduplication.

Level 1 (deterministic): drop exact duplicate URLs / normalized URLs /
content hashes, both within the current batch and against what's already in
the database.

Level 2 (editorial pre-grouping): cheap title-similarity clustering so
obviously-the-same-story articles ("OpenAI launches new model" / "OpenAI
releases its latest AI model") are merged into one candidate entry with
multiple sources *before* we spend LLM tokens on them. No embeddings, no
vector store - just normalization + a similarity ratio. The LLM still makes
the final editorial call on anything this doesn't catch.
"""
import logging
import re
from difflib import SequenceMatcher
from typing import Dict, List, Set

from app import database
from app.feeds import normalize_url

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "to", "of", "in", "on",
    "for", "with", "and", "or", "its", "it's", "at", "by", "as", "new",
    "news", "report", "reports", "reportedly", "says", "how", "why", "what",
    "this", "that", "after", "over", "into", "amid", "amidst", "vs",
}


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    tokens = [t for t in title.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


def title_similarity(a: str, b: str) -> float:
    """Blend of sequence-ratio and token-Jaccard so both wording and word overlap count."""
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if tokens_a and tokens_b:
        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    else:
        jaccard = 0.0
    return max(ratio, jaccard)


def deterministic_dedupe(articles: List[Dict]) -> List[Dict]:
    """Level 1: drop exact URL / content-hash duplicates, in-batch and vs. the DB."""
    seen_urls: Set[str] = set()
    seen_hashes: Set[str] = set()
    unique: List[Dict] = []

    for article in articles:
        norm_url = normalize_url(article["url"])
        content_hash = article["content_hash"]

        if norm_url in seen_urls or content_hash in seen_hashes:
            continue
        if database.url_exists(article["url"]) or database.content_hash_exists(content_hash):
            continue

        seen_urls.add(norm_url)
        seen_hashes.add(content_hash)
        unique.append(article)

    logger.info("After deterministic dedup: %d (from %d)", len(unique), len(articles))
    return unique


def group_similar_articles(articles: List[Dict], threshold: float = 0.6) -> List[Dict]:
    """
    Level 2: cluster articles with highly similar titles into one merged
    candidate entry. Uses a simple greedy O(n^2) clustering, which is fine at
    the scale of a few hundred articles per run.
    """
    normalized = [normalize_title(a["title"]) for a in articles]
    assigned = [False] * len(articles)
    merged: List[Dict] = []

    for i, article in enumerate(articles):
        if assigned[i]:
            continue
        group = [article]
        assigned[i] = True
        for j in range(i + 1, len(articles)):
            if assigned[j]:
                continue
            if title_similarity(normalized[i], normalized[j]) >= threshold:
                group.append(articles[j])
                assigned[j] = True

        if len(group) == 1:
            merged.append(article)
            continue

        # Prefer the longest title as the representative (usually the most descriptive).
        primary = max(group, key=lambda a: len(a["title"]))
        descriptions = [a["description"] for a in group if a.get("description")]
        merged.append({
            "title": primary["title"],
            "url": primary["url"],
            "source": primary["source"],
            "author": primary.get("author"),
            "published_at": primary.get("published_at"),
            "description": descriptions[0] if descriptions else "",
            "category": primary["category"],
            "content_hash": primary["content_hash"],
            "sources": sorted({a["source"] for a in group}),
            "urls": [a["url"] for a in group],
        })

    logger.info("After similarity grouping: %d candidate stories (from %d)", len(merged), len(articles))
    return merged


def dedupe_and_group(articles: List[Dict], threshold: float = 0.6) -> List[Dict]:
    unique = deterministic_dedupe(articles)
    return group_similar_articles(unique, threshold=threshold)
