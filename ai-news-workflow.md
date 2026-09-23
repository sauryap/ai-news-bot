Instead, give it a batch of collected articles.

Its job is to behave like a technology editor.

It should:

Identify the underlying news events.
Merge duplicate coverage.
Remove low-value stories.
Remove clickbait.
Rank stories by importance.
Categorize them.
Select the top 5–10 stories.
Explain why each story matters.
Identify larger trends when possible.

Prioritize:

AI
AI agents
software development
cloud
cybersecurity
semiconductors
startups
major technology companies
developer tools
robotics
important research
major product launches
acquisitions
significant funding
major policy/regulatory developments affecting technology

Deprioritize:

celebrity news
generic opinion pieces
minor product updates
repetitive press releases
clickbait
affiliate-heavy articles
trivial software updates
articles without meaningful new information 6. AI output format

Force the LLM to return valid JSON.

Use a schema similar to:

{
"briefing_title": "Today's Tech Intelligence",
"stories": [
{
"title": "...",
"category": "AI",
"importance": 9,
"what_happened": "...",
"why_it_matters": "...",
"source_urls": ["..."]
}
],
"trends": [
"...",
"..."
],
"watch_next": [
"...",
"..."
]
}

Validate the JSON before using it.

If parsing fails, retry once with a correction prompt.

7. Editorial prompt

Create:

prompts/tech_editor.txt

Use a strong system prompt along these lines:

"You are the editor of a high-quality daily technology intelligence briefing.

You are given articles collected from multiple technology news sources.

Do not simply summarize every article.

Your job is to identify the most important underlying developments.

Merge articles covering the same event.

Prefer primary reporting and credible sources.

Ignore clickbait, trivial updates, duplicated reporting and stories that have little significance.

Rank stories according to their likely impact on technology, software developers, startups, businesses and the broader technology ecosystem.

For every selected story explain:

what happened
why it matters

Do not invent facts.
Do not infer information that is not supported by the supplied articles.
If sources disagree, explicitly indicate uncertainty.

Return valid JSON matching the provided schema."

Make the prompt configurable rather than hard-coding it inside Python.

8. Telegram

Implement Telegram notifications using the Telegram Bot API.

Configuration:

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

Create a clean Markdown or HTML formatted message.

Example:

🧠 TECH INTELLIGENCE
13 September 2026

🔥 TOP STORIES

1. OpenAI ...

Importance: 9/10

What happened:
...

Why it matters:
...

Source: ...

━━━━━━━━━━━━

2. NVIDIA ...

...

📈 TREND

AI coding tools are increasingly...

👀 WATCH NEXT

• ...
• ...

Keep the message readable on a phone.

If the briefing is too long for Telegram's message limit, split it into multiple messages automatically.

9. CLI

Implement:

python main.py collect

Collect RSS articles.

python main.py process

Deduplicate and process articles through the AI editor.

python main.py briefing

Generate the latest briefing.

python main.py send

Send the latest briefing to Telegram.

python main.py run

Run the entire pipeline:

collect
→ deduplicate
→ AI editorial processing
→ save briefing
→ send Telegram

Also support:

python main.py --help 10. Scheduling

Do not build an internal scheduler.

Provide a cron example in README.

For example:

0 8 \* \* \* cd /path/to/tech-intelligence && python main.py run

The README should explain how to change the time.

11. Configuration

Create:

.env.example

with:

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DATABASE_PATH=data/news.db
MAX_ARTICLES_PER_FEED=20
MAX_STORIES=10

Never commit .env.

12. Logging

Use Python logging.

Show useful progress:

[INFO] Collecting RSS feeds...
[INFO] TechCrunch: 18 articles
[INFO] Ars Technica: 15 articles
[INFO] Total collected: 73
[INFO] After deduplication: 51
[INFO] Sending 51 articles to local editor...
[INFO] Selected 8 important stories
[INFO] Briefing generated
[INFO] Telegram notification sent

Handle errors clearly.

13. Important constraint

Keep this as a genuinely small MVP.

Do not add:

authentication
frontend
Docker unless absolutely necessary
Redis
PostgreSQL
Celery
LangChain
LangGraph
vector databases
paid APIs
cloud infrastructure

Everything should work locally.

14. README

The README must contain exact setup instructions:

Clone/download project.
Create Python virtual environment.
Install dependencies.
Install Ollama.
Pull an appropriate local model.
Create Telegram bot using BotFather.
Configure .env.
Run collection.
Run AI processing.
Send a test Telegram briefing.
Configure cron.

Also include troubleshooting for:

Ollama not running
model not found
Telegram authentication failure
invalid chat ID
RSS feed failure
malformed AI JSON 15. Build philosophy

Build the simplest working version first.

Do not stop to ask me unnecessary questions.

Make reasonable defaults.

After implementation, give me:

Files created.
Commands to install dependencies.
Commands to run the first test.
How to configure Ollama.
How to configure Telegram.
How to schedule it daily.
A short explanation of how the pipeline works.

If something cannot be implemented exactly as requested, choose the simplest free alternative and explain the tradeoff.

Start by creating the project and implementing the complete MVP.
