"""
AI editorial processing: sends a batch of candidate articles to a local
Ollama model and asks it to behave like a technology editor, returning a
structured JSON briefing.
"""
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import requests

from app import config

logger = logging.getLogger(__name__)


class OllamaUnavailableError(RuntimeError):
    """Raised when Ollama cannot be reached or the configured model is missing."""


class EditorOutputError(RuntimeError):
    """Raised when the model's JSON output is invalid even after a retry."""


# Ceiling for the automatic higher-limit retry after a truncated response.
MAX_RETRY_OUTPUT_TOKENS = 4096

REQUIRED_STORY_FIELDS ={"title", "category", "importance", "what_happened", "why_it_matters", "source_urls"}


def check_ollama_available() -> None:
    """Verify Ollama is reachable and the configured model exists. Raises with a clear message otherwise."""
    if not config.OLLAMA_MODEL:
        raise OllamaUnavailableError(
            "No OLLAMA_MODEL configured. Set OLLAMA_MODEL in your .env file, e.g.:\n"
            "  OLLAMA_MODEL=llama3.1\n"
            "Then pull it with: ollama pull llama3.1"
        )

    try:
        response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise OllamaUnavailableError(
            f"Could not reach Ollama at {config.OLLAMA_BASE_URL} ({exc}).\n"
            "Is Ollama installed and running? Start it with: ollama serve\n"
            "Install instructions: https://ollama.com/download"
        ) from exc

    models = [m.get("name", "") for m in response.json().get("models", [])]
    # Model names may include a ":tag" suffix (e.g. "llama3.1:latest"); match loosely.
    configured = config.OLLAMA_MODEL
    if not any(m == configured or m.startswith(f"{configured}:") for m in models):
        available = ", ".join(models) if models else "(none installed)"
        raise OllamaUnavailableError(
            f"Model '{configured}' not found in Ollama.\n"
            f"Installed models: {available}\n"
            f"Pull it with: ollama pull {configured}"
        )


def _estimate_num_ctx(prompt: str) -> int:
    """
    Ollama defaults to a 2048-token context window regardless of what the
    model actually supports, unless 'num_ctx' is passed explicitly. With a
    batch of articles that silently truncates the prompt and the model never
    sees most of the input. Estimate the tokens needed (~3.5 chars/token for
    English, plus headroom for the JSON response) and round up.
    """
    estimated_prompt_tokens = int(len(prompt) / 3.5)
    needed = estimated_prompt_tokens + 2048  # headroom for the JSON output
    # Round up to the next multiple of 1024, within a sane floor/ceiling.
    rounded = ((needed // 1024) + 1) * 1024
    return max(4096, min(rounded, 32768))


def _call_ollama(prompt: str, max_output_tokens: Optional[int] = None) -> Tuple[str, bool]:
    """
    Returns (response_text, truncated). truncated is True when generation
    stopped because it hit the token cap rather than finishing naturally; in
    that case the JSON is cut off mid-way and will fail to parse.
    """
    max_output_tokens = max_output_tokens or config.OLLAMA_MAX_OUTPUT_TOKENS
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                # Disable "thinking" for reasoning-capable models (e.g. qwen3,
                # deepseek-r1). Ollama ignores this field for models that
                # don't support it. Without this, small reasoning models can
                # spend many minutes generating chain-of-thought before ever
                # producing the JSON answer.
                "think": False,
                "options": {
                    "temperature": 0.2,
                    "num_ctx": _estimate_num_ctx(prompt),
                    # Hard cap on generated tokens. A struggling small model
                    # can otherwise loop indefinitely without ever emitting a
                    # stop token, hanging until the request timeout.
                    "num_predict": max_output_tokens,
                },
            },
            timeout=config.OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise OllamaUnavailableError(
            f"Ollama request failed ({exc}). Is 'ollama serve' still running?"
        ) from exc

    data = response.json()
    return data.get("response", ""), data.get("done_reason") == "length"


def _extract_json(text: str) -> str:
    """Strip markdown code fences etc, in case the model doesn't return raw JSON."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # Fall back to the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _validate(data: Dict) -> None:
    if not isinstance(data, dict):
        raise EditorOutputError("Top-level JSON is not an object")
    if "stories" not in data or not isinstance(data["stories"], list):
        raise EditorOutputError("Missing or invalid 'stories' array")
    if len(data["stories"]) == 0:
        raise EditorOutputError("'stories' array is empty")
    for i, story in enumerate(data["stories"]):
        if not isinstance(story, dict):
            raise EditorOutputError(f"Story {i} is not an object")
        missing = REQUIRED_STORY_FIELDS - story.keys()
        if missing:
            raise EditorOutputError(f"Story {i} missing fields: {missing}")
    data.setdefault("briefing_title", "Today's Tech Intelligence")
    data.setdefault("trends", [])
    data.setdefault("watch_next", [])


def _build_prompt(articles: List[Dict], template: str, max_stories: int) -> str:
    slim = [
        {
            "index": i,
            "title": a["title"],
            "source": a.get("source") or ", ".join(a.get("sources", [])),
            "category": a.get("category", ""),
            "published_at": a.get("published_at") or "",
            "description": (a.get("description") or "")[:600],
            "urls": a.get("urls") or [a["url"]],
        }
        for i, a in enumerate(articles)
    ]
    return template.format(
        max_stories=max_stories,
        articles_json=json.dumps(slim, ensure_ascii=False, indent=2),
    )


def load_prompt_template() -> str:
    try:
        return config.PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Prompt file not found: {config.PROMPT_PATH}") from exc


def run_editor(articles: List[Dict], max_stories: Optional[int] = None) -> Optional[Dict]:
    """
    Send candidate articles to the local LLM and get back a validated
    editorial JSON structure. Retries once with a correction prompt if the
    first response isn't valid JSON matching the schema.

    max_stories caps how many stories the model should select from this
    batch; defaults to config.MAX_STORIES but callers processing small
    batches should pass a smaller number so the model isn't pressured into
    inventing filler stories to fill a quota.
    """
    check_ollama_available()
    template = load_prompt_template()
    prompt = _build_prompt(articles, template, max_stories or config.MAX_STORIES)

    logger.info("Sending %d articles to local editor (model=%s)...", len(articles), config.OLLAMA_MODEL)
    raw, truncated = _call_ollama(prompt)

    first_error: Optional[str] = None
    try:
        data = json.loads(_extract_json(raw))
        _validate(data)
        return data
    except (json.JSONDecodeError, EditorOutputError) as exc:
        first_error = str(exc)

    retry_cap = config.OLLAMA_MAX_OUTPUT_TOKENS
    if truncated:
        # The JSON was cut off at the token cap, so it's incomplete, not
        # malformed. Re-sending with the same cap would fail the same way:
        # raise the cap and ask for shorter text instead.
        retry_cap = min(config.OLLAMA_MAX_OUTPUT_TOKENS * 2, MAX_RETRY_OUTPUT_TOKENS)
        logger.warning(
            "Editor output was cut off at the %d-token limit (%s); retrying once with a %d-token limit and shorter text",
            config.OLLAMA_MAX_OUTPUT_TOKENS, first_error, retry_cap,
        )
        correction_prompt = (
            prompt
            + "\n\nYour previous response was cut off because it was too long. "
            "Return the COMPLETE JSON object again, keeping every what_happened and "
            "why_it_matters to one short sentence. Return ONLY the JSON, with no "
            "explanation and no markdown code fences."
        )
    else:
        logger.warning("Editor output invalid (%s); retrying once with a correction prompt", first_error)
        correction_prompt = (
            prompt
            + "\n\nYour previous response was not valid JSON matching the schema "
            f"(error: {first_error}). Return ONLY the corrected valid JSON object, "
            "with no explanation and no markdown code fences."
        )

    raw_retry, truncated_retry = _call_ollama(correction_prompt, max_output_tokens=retry_cap)
    try:
        data = json.loads(_extract_json(raw_retry))
        _validate(data)
        return data
    except (json.JSONDecodeError, EditorOutputError) as exc:
        hint = (
            f" (output hit the {retry_cap}-token limit; raise OLLAMA_MAX_OUTPUT_TOKENS in .env)"
            if truncated_retry else ""
        )
        logger.error("Editor output still invalid after retry: %s%s", exc, hint)
        raise EditorOutputError(f"AI editor did not return valid JSON after retry: {exc}{hint}") from exc
