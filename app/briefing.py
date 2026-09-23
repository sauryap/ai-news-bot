"""
Turns unprocessed articles into an AI-curated briefing: runs level-2
deduplication, calls the local editor, persists the resulting stories, and
renders a phone-readable Telegram message (split across multiple messages if
needed).
"""
import html
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app import config, database
from app.deduplicator import group_similar_articles, normalize_title, title_similarity
from app.editor import EditorOutputError, OllamaUnavailableError, run_editor
from app.models import Story

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096
STORY_MERGE_THRESHOLD = 0.6


def process_unprocessed_articles() -> Optional[Dict]:
    """
    Level-2 dedup + AI editorial pass over everything collected since the
    last run. Persists stories and a rendered briefing. Returns the merged
    editor JSON, or None if there was nothing to process.

    Articles are sent to the local model in small batches rather than one
    large prompt: small and/or CPU-only local models are unreliable (or
    extremely slow, sometimes never terminating) when asked to rank and
    summarize dozens of articles in a single call. Each batch's results are
    merged and re-ranked afterwards.
    """
    rows = database.get_unprocessed_articles()
    if not rows:
        logger.info("No unprocessed articles found. Run 'collect' first.")
        return None

    articles = [dict(row) for row in rows]
    logger.info("Found %d unprocessed articles", len(articles))

    candidates = group_similar_articles(articles)

    if len(candidates) > config.MAX_CANDIDATE_ARTICLES:
        # Keep the pipeline fast and reliable on small/local models: prefer
        # the most recently published candidates (undated ones sort last).
        candidates.sort(key=lambda a: a.get("published_at") or "", reverse=True)
        logger.info(
            "Trimming %d candidates down to the %d most recent for the editor",
            len(candidates), config.MAX_CANDIDATE_ARTICLES,
        )
        candidates = candidates[:config.MAX_CANDIDATE_ARTICLES]

    batches = [
        candidates[i:i + config.EDITOR_BATCH_SIZE]
        for i in range(0, len(candidates), config.EDITOR_BATCH_SIZE)
    ]
    logger.info(
        "Sending %d articles to local editor in %d batch(es) of up to %d...",
        len(candidates), len(batches), config.EDITOR_BATCH_SIZE,
    )

    all_stories: List[Dict] = []
    all_trends: List[str] = []
    all_watch_next: List[str] = []
    per_batch_max_stories = max(1, min(3, config.MAX_STORIES))

    for batch_num, batch in enumerate(batches, start=1):
        logger.info("Editor batch %d/%d (%d articles)...", batch_num, len(batches), len(batch))
        try:
            result = run_editor(batch, max_stories=per_batch_max_stories)
        except (OllamaUnavailableError, EditorOutputError) as exc:
            # One bad/slow batch shouldn't sink the whole briefing - skip it
            # and keep whatever other batches produced.
            logger.warning("Editor batch %d/%d failed, skipping it (%s)", batch_num, len(batches), exc)
            continue
        all_stories.extend(result.get("stories", []))
        all_trends.extend(result.get("trends", []))
        all_watch_next.extend(result.get("watch_next", []))

    if not all_stories:
        raise EditorOutputError("The local editor did not return any usable stories from any batch")

    merged_stories = _merge_similar_stories(all_stories)
    merged_stories.sort(key=lambda s: s.get("importance", 0), reverse=True)
    merged_stories = merged_stories[:config.MAX_STORIES]

    editor_json = {
        "briefing_title": "Today's Tech Intelligence",
        "stories": merged_stories,
        "trends": _dedupe_text_list(all_trends)[:4],
        "watch_next": _dedupe_text_list(all_watch_next)[:5],
    }
    logger.info("Selected %d important stories", len(editor_json["stories"]))

    _persist_stories(editor_json)
    database.mark_articles_processed([a["id"] for a in articles])

    message_chunks = format_briefing_message(editor_json)
    database.save_briefing(
        title=editor_json.get("briefing_title", "Today's Tech Intelligence"),
        raw=editor_json,
        message_text="\n\n<!-- split -->\n\n".join(message_chunks),
    )
    logger.info("Briefing generated")
    return editor_json


def _merge_similar_stories(stories: List[Dict]) -> List[Dict]:
    """Collapse near-duplicate stories (e.g. the same event surfacing in two batches)."""
    normalized = [normalize_title(s.get("title", "")) for s in stories]
    assigned = [False] * len(stories)
    merged: List[Dict] = []

    for i, story in enumerate(stories):
        if assigned[i]:
            continue
        group = [story]
        assigned[i] = True
        for j in range(i + 1, len(stories)):
            if assigned[j]:
                continue
            if title_similarity(normalized[i], normalized[j]) >= STORY_MERGE_THRESHOLD:
                group.append(stories[j])
                assigned[j] = True

        if len(group) == 1:
            merged.append(story)
            continue

        # Keep the highest-importance version, but combine all source URLs.
        primary = max(group, key=lambda s: s.get("importance", 0))
        urls = []
        for s in group:
            for u in s.get("source_urls") or []:
                if u not in urls:
                    urls.append(u)
        merged.append({**primary, "source_urls": urls})

    return merged


def _dedupe_text_list(items: List[str]) -> List[str]:
    seen = set()
    unique = []
    for item in items:
        key = normalize_title(item)
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _persist_stories(editor_json: Dict) -> None:
    for story_data in editor_json["stories"]:
        story = Story(
            id=None,
            title=story_data["title"],
            summary=story_data.get("what_happened", ""),
            why_it_matters=story_data.get("why_it_matters", ""),
            importance=int(story_data.get("importance", 0) or 0),
            category=story_data.get("category", "General"),
        )
        source_urls = story_data.get("source_urls") or []
        article_ids = [database.get_article_id_by_url(u) for u in source_urls]
        database.insert_story(story, article_ids, source_urls)


def _esc(text: str) -> str:
    """Escape for Telegram's HTML parse mode (only &, <, > are special)."""
    return html.escape(str(text), quote=False)


def format_briefing_message(editor_json: Dict, generated_at: Optional[datetime] = None) -> List[str]:
    """
    Render the editor's JSON into one or more Telegram-ready HTML messages.
    HTML mode is used (rather than Markdown) because real article titles and
    descriptions routinely contain '_', '*', '[' etc., which break Telegram's
    legacy Markdown parser; HTML only requires escaping &, < and >.
    """
    generated_at = generated_at or datetime.now()
    date_str = generated_at.strftime("%d %B %Y")

    header = f"🧠 <b>TECH INTELLIGENCE</b>\n{date_str}\n\n🔥 <b>TOP STORIES</b>\n"
    blocks = [header]

    stories = sorted(editor_json.get("stories", []), key=lambda s: s.get("importance", 0), reverse=True)
    for i, story in enumerate(stories, start=1):
        title = _esc(story.get("title", "Untitled"))
        importance = _esc(story.get("importance", "?"))
        what_happened = _esc(story.get("what_happened", ""))
        why_it_matters = _esc(story.get("why_it_matters", ""))
        urls = story.get("source_urls") or []
        source_line = _esc(urls[0]) if urls else ""

        block = (
            f"\n<b>{i}. {title}</b>\n"
            f"Importance: {importance}/10\n\n"
            f"<b>What happened:</b>\n{what_happened}\n\n"
            f"<b>Why it matters:</b>\n{why_it_matters}\n"
        )
        if source_line:
            block += f"\nSource: {source_line}\n"
        block += "\n━━━━━━━━━━━━\n"
        blocks.append(block)

    trends = editor_json.get("trends") or []
    if trends:
        trend_text = "\n📈 <b>TRENDS</b>\n" + "\n".join(f"• {_esc(t)}" for t in trends) + "\n"
        blocks.append(trend_text)

    watch_next = editor_json.get("watch_next") or []
    if watch_next:
        watch_text = "\n👀 <b>WATCH NEXT</b>\n" + "\n".join(f"• {_esc(w)}" for w in watch_next) + "\n"
        blocks.append(watch_text)

    return _split_into_messages(blocks)


def _split_into_messages(blocks: List[str], max_length: int = TELEGRAM_MAX_LENGTH) -> List[str]:
    """Pack blocks into as few messages as possible without exceeding Telegram's limit."""
    messages: List[str] = []
    current = ""
    for block in blocks:
        if len(block) > max_length:
            # A single block is pathologically long (shouldn't normally happen);
            # hard-split it so we never send something Telegram will reject.
            if current:
                messages.append(current)
                current = ""
            for start in range(0, len(block), max_length):
                messages.append(block[start:start + max_length])
            continue

        if len(current) + len(block) > max_length:
            messages.append(current)
            current = block
        else:
            current += block

    if current:
        messages.append(current)

    return messages if messages else [""]


def get_latest_briefing_message() -> Optional[List[str]]:
    row = database.get_latest_briefing()
    if not row:
        return None
    return row["message_text"].split("\n\n<!-- split -->\n\n")
