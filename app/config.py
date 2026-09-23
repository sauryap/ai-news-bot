"""
Central configuration for Tech Intelligence.

All environment-dependent settings (Ollama, Telegram, database path, tuning
knobs) are loaded from environment variables / .env here. The RSS feed list
lives in this file as plain data so it's easy to edit without touching any
other module.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root regardless of current working directory.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _google_news_search(query: str) -> str:
    """Build a Google News RSS search URL for a given query."""
    from urllib.parse import quote

    return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"


# ---------------------------------------------------------------------------
# Ollama (local LLM)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/news.db")
if not os.path.isabs(DATABASE_PATH):
    DATABASE_PATH = str(BASE_DIR / DATABASE_PATH)

# ---------------------------------------------------------------------------
# Collection / editorial tuning
# ---------------------------------------------------------------------------
MAX_ARTICLES_PER_FEED = int(os.getenv("MAX_ARTICLES_PER_FEED", "20"))
MAX_STORIES = int(os.getenv("MAX_STORIES", "10"))

# Local LLMs (especially small ones, or CPU-only setups with no GPU) can
# produce unreliable or extremely slow output when handed hundreds of
# articles in a single prompt. Cap how many deduplicated candidates get sent
# to the editor per run (across all batches, see EDITOR_BATCH_SIZE below);
# the most recent ones are kept. Raise this if you're running a larger/faster
# model or have GPU acceleration.
MAX_CANDIDATE_ARTICLES = int(os.getenv("MAX_CANDIDATE_ARTICLES", "30"))

# The editor processes candidates in small batches rather than one giant
# prompt: small local models are unreliable (or extremely slow) when asked to
# rank and summarize dozens of articles at once. Each batch's results are
# merged and re-ranked afterwards. Raise this if you're running a
# larger/faster model or have GPU acceleration.
EDITOR_BATCH_SIZE = int(os.getenv("EDITOR_BATCH_SIZE", "5"))

# Hard cap on tokens the model may generate per editor call. Without this,
# a struggling small model can loop indefinitely without ever emitting a
# stop token, hanging until the request timeout. This forces it to stop.
OLLAMA_MAX_OUTPUT_TOKENS = int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "2048"))

# How many days back an article can be published and still be considered
# "fresh" for collection. Kept generous since some feeds omit dates.
MAX_ARTICLE_AGE_DAYS = int(os.getenv("MAX_ARTICLE_AGE_DAYS", "3"))

# Network timeout (seconds) for fetching a single feed.
FEED_TIMEOUT_SECONDS = int(os.getenv("FEED_TIMEOUT_SECONDS", "15"))

# Timeout (seconds) for a single Ollama generate call (one batch's worth of
# articles, see EDITOR_BATCH_SIZE). CPU-only local inference can be genuinely
# slow (a few tokens/second on modest hardware), so this is generous.
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600"))

PROMPT_PATH = BASE_DIR / "prompts" / "tech_editor.txt"

# ---------------------------------------------------------------------------
# RSS feed list
# ---------------------------------------------------------------------------
# Each entry: (name, url, category). Category is a default/fallback; the AI
# editor may re-categorize stories during editorial processing.
FEEDS = [
    # --- General technology -------------------------------------------------
    ("TechCrunch", "https://techcrunch.com/feed/", "General Tech"),
    ("The Verge", "https://www.theverge.com/rss/index.xml", "General Tech"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "General Tech"),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/", "General Tech"),
    ("Wired", "https://www.wired.com/feed/rss", "General Tech"),
    ("Hacker News", "https://hnrss.org/frontpage", "General Tech"),

    # --- AI (Google News RSS searches) --------------------------------------
    ("Google News: Artificial Intelligence", _google_news_search("Artificial Intelligence"), "AI"),
    ("Google News: AI agents", _google_news_search("AI agents"), "AI"),
    ("Google News: OpenAI", _google_news_search("OpenAI"), "AI"),
    ("Google News: Anthropic", _google_news_search("Anthropic"), "AI"),
    ("Google News: Google AI", _google_news_search("Google AI"), "AI"),
    ("Google News: Microsoft AI", _google_news_search("Microsoft AI"), "AI"),
    ("Google News: NVIDIA AI", _google_news_search("NVIDIA AI"), "AI"),
    ("Google News: AI coding", _google_news_search("AI coding"), "Developer Tools"),
    ("Google News: RAG", _google_news_search("retrieval augmented generation RAG AI"), "AI"),
    ("Google News: MCP", _google_news_search("Model Context Protocol MCP AI"), "AI"),
    ("Google News: robotics", _google_news_search("robotics"), "Robotics"),
]
