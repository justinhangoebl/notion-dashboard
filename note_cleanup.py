"""Tidies up a dictated note with a small local LLM (Ollama).

Spoken notes wander: filler words, false starts, the same point made three
times. The model turns the raw transcript into a short heading (the TODO
title) and a cleaned-up body. Everything stays on this PC; if Ollama isn't
running or the model misbehaves, the caller falls back to the raw text.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

CLEANUP_DEFAULTS = {
    "cleanup": True,
    "cleanup_model": "qwen3:8b",
    "ollama_url": "http://127.0.0.1:11434",
    "keep_transcript": True,
}

TIMEOUT_SECONDS = 60
KEEP_ALIVE = "15m"  # keeps the model in memory between notes

SYSTEM_PROMPT = """\
You tidy up notes that someone dictated by voice while thinking aloud.
The transcript may contain filler words, false starts, self-corrections,
speech-recognition mistakes, and the same thought repeated or circled back to.

Return JSON with two fields:
- "title": a short, clear heading for the note (at most 8 words, sentence
  case, no trailing period). If the note is a task, phrase it as the task
  ("Send reviewer comments to Tom"). Otherwise name the idea or topic.
- "body": the cleaned-up note. Merge repeated points into one, drop filler
  and false starts. When the speaker corrects themselves, the LAST version
  wins ("on Monday, no, Tuesday actually" means Tuesday). Keep every distinct fact, name, number, date and open
  question. Do not add anything that wasn't said, and don't comment on the
  note. Write short plain-text paragraphs; if there are several separate
  points or steps, write one per line starting with "- ". If the title
  already says everything, the body must be an empty string.

Never translate: write the title and body in the language of the transcript."""

# One worked example: small models follow a demonstration far more
# reliably than the rules alone, especially for self-corrections.
EXAMPLE = [
    {
        "role": "user",
        "content": "ok so uh I have to send the the reviewer comments to Tom, "
        "to Tom, by the end of the month, no, by next Friday actually, and uh "
        "maybe also ask him if he wants, if he wants to be on the paper, yeah",
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "title": "Send reviewer comments to Tom by next Friday",
            "body": "- Send the reviewer comments to Tom by next Friday.\n"
            "- Ask him whether he wants to be on the paper.",
        }),
    },
]

LANGUAGES = {"en": "English", "de": "German"}

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["title", "body"],
}


class CleanupError(Exception):
    pass


def _post(settings: dict, path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        settings["ollama_url"].rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except ValueError:
            detail = ""
        raise CleanupError(detail or f"Ollama returned HTTP {exc.code}") from exc
    except TimeoutError as exc:
        raise CleanupError("Ollama took too long") from exc
    except (urllib.error.URLError, ConnectionError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise CleanupError("Ollama took too long") from exc
        raise CleanupError("Ollama isn't running") from exc
    except ValueError as exc:
        raise CleanupError("unexpected reply from Ollama") from exc


def warm_up(settings: dict) -> None:
    """Loads the model while the user is still talking. Errors are ignored:
    clean_note() reports them properly later."""
    try:
        _post(settings, "/api/generate", {"model": settings["cleanup_model"], "keep_alive": KEEP_ALIVE}, timeout=5)
    except CleanupError:
        pass


def clean_note(text: str, settings: dict, language: str = "") -> tuple[str, str]:
    """(title, body) for a raw transcript. `language` is the speech model's
    language code, if it detected one. Raises CleanupError on failure."""

    if language:
        name = LANGUAGES.get(language, language)
        text = f"(Dictated in {name}; write the title and body in {name}.)\n\n{text}"

    reply = _post(
        settings,
        "/api/chat",
        {
            "model": settings["cleanup_model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *EXAMPLE,
                {"role": "user", "content": text},
            ],
            "format": SCHEMA,
            "stream": False,
            "think": False,  # thinking models get it right but take ~20 s
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0.2},
        },
        timeout=TIMEOUT_SECONDS,
    )

    try:
        result = json.loads(reply["message"]["content"])
        title = " ".join(str(result["title"]).split()).rstrip(".")
        body = str(result.get("body", "")).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise CleanupError("the model didn't return a usable note") from exc

    if not title:
        raise CleanupError("the model returned an empty title")
    if len(title) > 100:
        title = title[:80].rsplit(" ", 1)[0] + "…"

    # Drop blank lines between bullets and collapse runs of empty lines.
    lines: list[str] = []
    for line in (l.rstrip() for l in body.splitlines()):
        if not line and (not lines or not lines[-1] or lines[-1].startswith("- ")):
            continue
        lines.append(line)
    body = "\n".join(lines).strip()

    # Small models like to repeat a one-line note as its body.
    def bare(s: str) -> str:
        return "".join(c for c in s.lower() if c.isalnum())

    if bare(body) == bare(title):
        body = ""
    return title, body
