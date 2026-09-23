# Tech Intelligence

A free, personal, local-first AI workflow that collects the latest technology
news from RSS feeds, deduplicates it, uses a **local** LLM (via [Ollama](https://ollama.com))
to act as a technology editor, and sends you a daily briefing on Telegram.

**Cost to run: $0.** No paid APIs, no cloud infrastructure. Everything runs
on your own machine.

## How it works

```
collect  -->  deduplicate  -->  AI editor (Ollama)  -->  briefing  -->  Telegram
(RSS)         (level 1+2)       (local LLM, JSON)        (saved)       (send)
```

1. **Collect** — `app/feeds.py` fetches every RSS/Atom feed listed in
   `app/config.py` (general tech sites + Google News searches for AI topics).
   Broken feeds, missing dates/descriptions, and network errors are all
   handled gracefully — one bad feed never stops the run.
2. **Deduplicate (level 1)** — `app/deduplicator.py` drops exact duplicate
   URLs, normalized URLs, and content hashes, both within the batch and
   against everything already stored in SQLite. New articles are stored in
   the `articles` table.
3. **Deduplicate (level 2)** — before sending articles to the LLM, titles are
   normalized and grouped by similarity (no embeddings, no vector DB) so
   near-duplicate headlines about the same event are merged into one
   candidate entry with multiple sources.
4. **AI editor** — `app/editor.py` sends candidates to your local Ollama
   model using the prompt in `prompts/tech_editor.txt`, in small batches
   (`EDITOR_BATCH_SIZE`, default 5) rather than one giant prompt. Small/CPU-only
   models are unreliable — or extremely slow — when asked to rank and
   summarize dozens of articles at once; batching keeps each call small,
   fast, and reliable. The model acts as an editor for each batch: merges
   duplicate coverage, drops low-value/clickbait stories, ranks by
   importance, and returns strict JSON (with a hard cap on generated tokens
   so a struggling model can't loop forever without ever finishing). If a
   batch's JSON is invalid, it retries once with a correction prompt; if a
   whole batch still fails, it's skipped with a warning rather than aborting
   the run.
5. **Briefing** — `app/briefing.py` merges and re-ranks the stories from all
   batches (collapsing any that turned out to be duplicates across batches),
   saves them to the `stories` table (linked back to their source `articles`
   via `story_articles`), and renders a phone-readable HTML message, splitting
   it into multiple Telegram messages if it's too long.
6. **Telegram** — `app/notifier.py` sends the briefing via the Telegram Bot
   API. If your network/ISP DNS-blocks Telegram (resolving `api.telegram.org`
   to a bogus address, which happens in some countries), it automatically
   falls back to resolving the real address via Cloudflare's
   DNS-over-HTTPS (`1.1.1.1`) rather than failing outright.

## Project structure

```
tech-intelligence/
├── app/
│   ├── config.py       # feeds list + all settings (.env-driven)
│   ├── database.py     # SQLite schema + queries
│   ├── models.py       # Article / Story dataclasses
│   ├── feeds.py        # RSS fetching + normalization
│   ├── collector.py    # collect step (fetch + level-1 dedup + store)
│   ├── deduplicator.py # level-1 + level-2 dedup logic
│   ├── editor.py        # Ollama call + JSON schema validation
│   ├── notifier.py      # Telegram Bot API
│   └── briefing.py      # story persistence + message formatting
├── prompts/
│   └── tech_editor.txt  # the editorial system prompt (editable, no code changes needed)
├── data/
│   └── news.db          # created automatically on first run
├── .env.example
├── requirements.txt
└── main.py
```

## Setup

### 1. Clone / download the project

### 2. Create a virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Ollama

Download and install from https://ollama.com/download (Windows, macOS, Linux
all supported). Then make sure the Ollama server is running:

```bash
ollama serve
```

(On Windows/macOS, installing Ollama usually sets it up to run automatically
in the background — you can skip `ollama serve` if it's already running.)

### 5. Pull a local model

Any Ollama model works — pick one that fits your machine's RAM. Good default
choices:

```bash
ollama pull llama3.1        # solid general-purpose choice, ~8B params
# or a smaller/faster option:
ollama pull qwen3:1.7b
```

Whatever you pull, set it in `.env` as `OLLAMA_MODEL` (see below).

### 6. Create a Telegram bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot` and follow the prompts to name it.
3. BotFather gives you a token like `123456789:ABCdefGhIJKlmNoPQRstuVwxyz`. This is your `TELEGRAM_BOT_TOKEN`.
4. Find your chat ID: **open a chat with your new bot and send it any message first** (e.g. "hi") —
   Telegram only records a chat once you've messaged the bot. Then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser. Look
   for `"chat":{"id": ...}` in the response — that number is your
   `TELEGRAM_CHAT_ID`. (If the page is empty (`"result":[]`), you haven't
   messaged the bot yet, or Telegram is blocked on your network — see
   Troubleshooting below.) Don't confuse this with the bot's own numeric ID
   (the number before the `:` in your bot token) — sending to that ID fails
   with `403 Forbidden: the bot can't send messages to the bot`.

### 7. Configure `.env`

```bash
copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux
```

Edit `.env` and fill in:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:1.7b        # whatever model you pulled
TELEGRAM_BOT_TOKEN=your-token-here
TELEGRAM_CHAT_ID=your-chat-id-here
DATABASE_PATH=data/news.db
MAX_ARTICLES_PER_FEED=20
MAX_STORIES=10
```

Never commit `.env` — it's already in `.gitignore`.

### 8. Run collection

```bash
python main.py collect
```

You should see log output like:

```
[INFO] Collecting RSS feeds...
[INFO] TechCrunch: 18 articles
[INFO] Ars Technica: 15 articles
[INFO] Total collected: 73
[INFO] Collected 51 new articles (of 73 fetched)
```

### 9. Run AI processing

```bash
python main.py process
```

This deduplicates, sends articles to your local model in small batches, and
saves a briefing.

**A note on speed:** this can take anywhere from under a minute (GPU, or a
fast machine) to 15-30+ minutes on a slow CPU-only setup with no GPU
acceleration — local LLM inference without a GPU can run as slow as a few
tokens per second. That's fine for a once-a-day cron job; it's just not
instant. If it's painfully slow, try a smaller/faster model
(`ollama pull qwen3:1.7b` or similar) and/or lower `EDITOR_BATCH_SIZE` and
`MAX_CANDIDATE_ARTICLES` in `.env`.

### 10. Send a test briefing

```bash
python main.py send
```

Check Telegram — you should receive the formatted briefing, split into
multiple messages if it's long.

### 11. Run the whole pipeline at once

```bash
python main.py
# or explicitly:
python main.py run
```

## CLI reference

```bash
python main.py collect    # fetch RSS feeds, dedupe, store new articles
python main.py process    # dedupe + AI editor pass, save a briefing
python main.py briefing   # print the latest saved briefing to the terminal
python main.py send       # send the latest saved briefing to Telegram
python main.py run        # collect -> process -> send
python main.py            # same as 'run'
python main.py --send     # send the latest saved briefing only (skip collect/process)
python main.py --help
```

## Scheduling with cron

Run it once a day, e.g. at 8:00 AM:

```cron
0 8 * * * cd /path/to/tech-intelligence && /path/to/.venv/bin/python main.py run >> logs/tech_intelligence.log 2>&1
```

To change the time, edit the first five fields (`minute hour day month
weekday`). For example, 7:30 AM:

```cron
30 7 * * * cd /path/to/tech-intelligence && /path/to/.venv/bin/python main.py run >> logs/tech_intelligence.log 2>&1
```

Edit your crontab with `crontab -e`. Create the `logs/` directory first if
you want to keep output (`mkdir logs`).

### Scheduling on Windows (Task Scheduler)

Cron isn't available on Windows. Run this in PowerShell to create a daily 8:00 AM
task (adjust `$proj` to your project folder):

```powershell
$proj = "C:\path\to\ai-news-workflow"
New-Item -ItemType Directory -Force "$proj\logs" | Out-Null

$py = "$proj\.venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
  -Argument "/c `"`"$py`" main.py run >> logs\tech_intelligence.log 2>&1 & `"$py`" prices.py fetch >> logs\tech_intelligence.log 2>&1`"" `
  -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName "TechIntelligenceDaily" -Action $action -Trigger $trigger -Settings $settings -Description "Daily tech news briefing (collect -> AI editor -> Telegram) + gold/silver price fetch"
```

The `&` chains a second command so the gold/silver rates (`prices.py fetch`) get refreshed in the same
daily run as the news briefing — otherwise the widget's price strip only updates when you run it by hand.

Notes:

- If the PC is off or asleep at 8:00 AM, the task runs as soon as it's back on
  (`-StartWhenAvailable`). It only runs while you're logged in.
- Ollama must be running when the task fires. The Ollama Windows app normally
  starts at login; if it doesn't, the run fails with the "Ollama not running" error.
- Output is appended to `logs\tech_intelligence.log`.

Change the time (e.g. 7:30 AM):

```powershell
Set-ScheduledTask -TaskName TechIntelligenceDaily -Trigger (New-ScheduledTaskTrigger -Daily -At 7:30AM)
```

Test it now (this sends a real Telegram briefing), then check the log:

```powershell
Start-ScheduledTask -TaskName TechIntelligenceDaily
Get-Content logs\tech_intelligence.log -Tail 30
```

Check status / next run time:

```powershell
Get-ScheduledTaskInfo -TaskName TechIntelligenceDaily
```

Remove it:

```powershell
Unregister-ScheduledTask -TaskName TechIntelligenceDaily -Confirm:$false
```

## Configuration

All settings live in `.env` (see `.env.example`). The RSS feed list itself
lives in `app/config.py` as a plain Python list — edit it directly to add,
remove, or change feeds/searches; no other code needs to change.

The editorial prompt lives in `prompts/tech_editor.txt` — edit it to change
tone, priorities, or the number of stories, without touching any Python.

Key tuning knobs for the AI editor step (all in `.env`):

| Variable                   | Default | What it does                                                                                                                                            |
| -------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MAX_CANDIDATE_ARTICLES`   | 30      | Total articles considered per run, across all batches.                                                                                                  |
| `EDITOR_BATCH_SIZE`        | 5       | Articles sent to the model per call. Raise this if you have a fast/GPU setup.                                                                           |
| `OLLAMA_MAX_OUTPUT_TOKENS` | 2048    | Hard cap on generated tokens per call, so a struggling model can't hang forever. Too low and the JSON gets cut off mid-way (`Expecting ',' delimiter`). |
| `OLLAMA_TIMEOUT_SECONDS`   | 600     | How long to wait for one batch's response.                                                                                                              |
| `MAX_STORIES`              | 10      | Final number of stories in the briefing, after merging all batches.                                                                                     |

## Troubleshooting

**Ollama not running**

```
Could not reach Ollama at http://localhost:11434 (...)
```

Start it with `ollama serve`, or check that the Ollama desktop app/service is running.

**Model not found**

```
Model 'xyz' not found in Ollama.
```

Pull it first: `ollama pull xyz` (and make sure `OLLAMA_MODEL` in `.env`
matches exactly, including any `:tag`).

**Telegram authentication failure (401)**
Your `TELEGRAM_BOT_TOKEN` is wrong or was regenerated. Get a fresh one from
@BotFather with `/token`.

**Invalid chat ID (400 from Telegram) / "the bot can't send messages to the bot" (403)**
Double check `TELEGRAM_CHAT_ID`. Message your bot first (Telegram only
records a chat once you've sent it a message), then reload
`https://api.telegram.org/bot<TOKEN>/getUpdates` — the ID must come from a
chat where the bot has received at least one message. The 403 specifically
means `TELEGRAM_CHAT_ID` was set to the bot's own numeric ID (the digits
before the `:` in the token) rather than your personal chat ID.

**Telegram seems unreachable / connection refused, but your internet works fine**
Some ISPs and networks DNS-block Telegram (`api.telegram.org` resolves to
`127.0.0.1` or another bogus address instead of failing outright). The app
detects this automatically and falls back to resolving the real address via
Cloudflare's DNS-over-HTTPS (`1.1.1.1`), so this usually resolves itself. If
your network also blocks Telegram's IPs directly (not just DNS), you'll need
a VPN.

**RSS feed failure**
Individual feed errors (timeouts, 404s, malformed XML) are logged as
warnings and skipped — they won't stop the rest of the pipeline. Check the
log line naming the feed for the specific error.

**Malformed AI JSON**
The editor automatically retries once if a batch's output isn't valid JSON; if
a batch still fails, it's skipped (you'll see a warning) and the rest of the
run continues.

The most common cause is **truncation**, not bad JSON: if the model's answer
hits `OLLAMA_MAX_OUTPUT_TOKENS` mid-way, the JSON is cut off and you'll see
errors like `Expecting ',' delimiter: line 33 column 6`. The log line will say
"cut off at the N-token limit", and the retry automatically doubles the limit
and asks for shorter text. To avoid the wasted first attempt, set
`OLLAMA_MAX_OUTPUT_TOKENS=2048` (or higher) in `.env`.

If it still happens often, try a larger/more capable model, or lower
`EDITOR_BATCH_SIZE` in `.env` so each call asks less of the model.

**Editor call hangs for a very long time / times out**
CPU-only inference on modest hardware can run at just a few tokens/second —
a full run can legitimately take 15-30+ minutes. If a batch still exceeds
`OLLAMA_TIMEOUT_SECONDS`, lower `EDITOR_BATCH_SIZE` and/or
`MAX_CANDIDATE_ARTICLES` in `.env`, or use a smaller/faster model.

## Design constraints (by design, not oversights)

This is intentionally a small, single-machine MVP. It does **not** use
LangChain, vector databases, Docker, Kubernetes, Redis, PostgreSQL, Celery,
authentication, or a frontend — just Python, SQLite, RSS, and a local LLM.
