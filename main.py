#!/usr/bin/env python3
"""
Tech Intelligence - a free, local, personal daily tech news briefing.

Usage:
    python main.py                 # run the full pipeline (collect -> process -> send)
    python main.py --send          # send the most recently generated briefing only
    python main.py collect         # fetch RSS feeds and store new articles
    python main.py process         # deduplicate + run the AI editor, save a briefing
    python main.py briefing        # print the latest saved briefing
    python main.py send            # send the latest saved briefing to Telegram
    python main.py run             # collect -> process -> send
"""
import argparse
import logging
import sys

# Windows terminals often default to a legacy codepage (e.g. cp1252) that
# can't encode the emoji used in briefing messages; force UTF-8 so printing
# a briefing doesn't crash.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from app import briefing as briefing_module
from app import collector
from app import database
from app import notifier
from app.editor import EditorOutputError, OllamaUnavailableError
from app.notifier import TelegramConfigError, TelegramSendError

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger("tech_intelligence")


def cmd_collect(_args) -> int:
    database.init_db()
    inserted, total = collector.collect_articles()
    logger.info("Collected %d new articles (of %d fetched)", inserted, total)
    return 0


def cmd_process(_args) -> int:
    database.init_db()
    try:
        result = briefing_module.process_unprocessed_articles()
    except OllamaUnavailableError as exc:
        logger.error(str(exc))
        return 1
    except EditorOutputError as exc:
        logger.error(str(exc))
        return 1
    if result is None:
        return 0
    return 0


def cmd_briefing(_args) -> int:
    database.init_db()
    chunks = briefing_module.get_latest_briefing_message()
    if not chunks:
        logger.error("No briefing found yet. Run 'python main.py process' first.")
        return 1
    for chunk in chunks:
        print(chunk)
        print("\n----------------------------------------\n")
    return 0


def cmd_send(_args) -> int:
    database.init_db()
    row = database.get_latest_briefing()
    if not row:
        logger.error("No briefing found yet. Run 'python main.py process' first.")
        return 1
    chunks = row["message_text"].split("\n\n<!-- split -->\n\n")
    try:
        notifier.send_briefing(chunks)
    except (TelegramConfigError, TelegramSendError) as exc:
        logger.error(str(exc))
        return 1
    database.mark_briefing_sent(row["id"])
    return 0


def cmd_run(_args) -> int:
    database.init_db()
    inserted, total = collector.collect_articles()
    logger.info("Collected %d new articles (of %d fetched)", inserted, total)

    try:
        result = briefing_module.process_unprocessed_articles()
    except OllamaUnavailableError as exc:
        logger.error(str(exc))
        return 1
    except EditorOutputError as exc:
        logger.error(str(exc))
        return 1

    if result is None:
        logger.info("Nothing new to brief on today.")
        return 0

    row = database.get_latest_briefing()
    chunks = row["message_text"].split("\n\n<!-- split -->\n\n")
    try:
        notifier.send_briefing(chunks)
    except (TelegramConfigError, TelegramSendError) as exc:
        logger.error(str(exc))
        return 1
    database.mark_briefing_sent(row["id"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Tech Intelligence - free local AI daily tech news briefing.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the most recently generated briefing to Telegram and exit "
             "(no collection or AI processing). Only used when no subcommand is given.",
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("collect", help="Fetch RSS feeds and store new articles.").set_defaults(func=cmd_collect)
    subparsers.add_parser("process", help="Deduplicate and run the AI editor, save a briefing.").set_defaults(func=cmd_process)
    subparsers.add_parser("briefing", help="Print the latest saved briefing.").set_defaults(func=cmd_briefing)
    subparsers.add_parser("send", help="Send the latest saved briefing to Telegram.").set_defaults(func=cmd_send)
    subparsers.add_parser("run", help="Run the full pipeline: collect -> process -> send.").set_defaults(func=cmd_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command:
        return args.func(args)

    if args.send:
        return cmd_send(args)

    # No subcommand, no flags: run the full pipeline.
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
