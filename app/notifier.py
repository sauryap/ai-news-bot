"""Telegram Bot API notifications."""
import ipaddress
import logging
import socket
import time
from contextlib import contextmanager
from typing import List, Optional

import requests

from app import config

logger = logging.getLogger(__name__)

TELEGRAM_HOST = "api.telegram.org"

# Cached per-process once resolved, so we don't re-check/re-resolve for every
# message chunk in a multi-part briefing.
_dns_override_ip: Optional[str] = None
_dns_checked = False


class TelegramConfigError(RuntimeError):
    """Raised when Telegram credentials are missing."""


class TelegramSendError(RuntimeError):
    """Raised when the Telegram API rejects a message."""


def _check_config() -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise TelegramConfigError(
            "TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are not set in .env.\n"
            "Create a bot with @BotFather on Telegram, then set both values. See README for details."
        )


def _redact(text: str) -> str:
    """Strip the bot token out of error text before it's logged or raised."""
    if config.TELEGRAM_BOT_TOKEN:
        text = text.replace(config.TELEGRAM_BOT_TOKEN, "***")
    return text


def _is_bogus_ip(ip: str) -> bool:
    """True if an IP looks like DNS blocking/hijacking rather than a real Telegram address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_loopback or addr.is_unspecified or addr.is_private


def _doh_resolve(hostname: str) -> Optional[str]:
    """
    Resolve a hostname via Cloudflare's DNS-over-HTTPS (1.1.1.1), bypassing
    the system/ISP resolver. Used only as a fallback when the normal
    resolver returns a bogus address (some ISPs/networks DNS-block Telegram
    by resolving it to 127.0.0.1 instead of a real refusal).
    """
    try:
        resp = requests.get(
            "https://1.1.1.1/dns-query",
            params={"name": hostname, "type": "A"},
            headers={"Accept": "application/dns-json"},
            timeout=10,
        )
        resp.raise_for_status()
        for answer in resp.json().get("Answer", []):
            if answer.get("type") == 1:  # A record
                return answer["data"]
    except (requests.exceptions.RequestException, ValueError, KeyError):
        return None
    return None


def _get_dns_override() -> Optional[str]:
    """
    Check once per process whether the default resolver for Telegram's API
    is broken/blocked, and if so, resolve a working IP via DNS-over-HTTPS.
    Returns None if the default resolver works fine, or if the fallback
    couldn't find a working address either (caller falls back to the normal,
    likely-failing request so the real error still surfaces).
    """
    global _dns_override_ip, _dns_checked
    if _dns_checked:
        return _dns_override_ip

    _dns_checked = True
    try:
        default_ip = socket.gethostbyname(TELEGRAM_HOST)
        if not _is_bogus_ip(default_ip):
            return None  # normal DNS works fine, nothing to override
    except socket.gaierror:
        pass  # default resolution failed outright; still worth trying the fallback

    logger.warning(
        "Default DNS resolution for %s looks blocked; trying DNS-over-HTTPS fallback...",
        TELEGRAM_HOST,
    )
    resolved = _doh_resolve(TELEGRAM_HOST)
    if resolved:
        logger.info("Resolved %s to %s via DNS-over-HTTPS fallback", TELEGRAM_HOST, resolved)
        _dns_override_ip = resolved
    return _dns_override_ip


@contextmanager
def _resolve_override(hostname: str, ip: Optional[str]):
    """Temporarily force socket resolution of `hostname` to `ip` (like curl --resolve)."""
    if not ip:
        yield
        return

    original_getaddrinfo = socket.getaddrinfo

    def patched(host, *args, **kwargs):
        if host == hostname:
            host = ip
        return original_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = patched
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def send_message(text: str) -> None:
    _check_config()
    url = f"https://{TELEGRAM_HOST}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    override_ip = _get_dns_override()

    try:
        with _resolve_override(TELEGRAM_HOST, override_ip):
            response = requests.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
    except requests.exceptions.RequestException as exc:
        raise TelegramSendError(
            f"Could not reach Telegram API: {_redact(str(exc))}\n"
            "If you're on a network/ISP that blocks Telegram, try a VPN."
        ) from exc

    if response.status_code == 401:
        raise TelegramSendError(
            "Telegram authentication failed (401). Check TELEGRAM_BOT_TOKEN is correct."
        )
    if response.status_code == 400:
        body = _redact(response.text)
        raise TelegramSendError(
            f"Telegram rejected the request (400): {body}\n"
            "This often means TELEGRAM_CHAT_ID is wrong, or the message has invalid formatting."
        )
    if not response.ok:
        raise TelegramSendError(f"Telegram API error {response.status_code}: {_redact(response.text)}")


def send_briefing(message_chunks: List[str]) -> None:
    """Send each chunk of a (possibly multi-part) briefing, in order."""
    _check_config()
    for i, chunk in enumerate(message_chunks):
        if not chunk.strip():
            continue
        send_message(chunk)
        logger.info("Sent Telegram message %d/%d", i + 1, len(message_chunks))
        if i < len(message_chunks) - 1:
            time.sleep(1)  # be gentle with Telegram's rate limits
    logger.info("Telegram notification sent")
