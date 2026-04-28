"""
ai_parser.py — Natural Language Task Entry for PawPal+

Converts a free-text pet care description into a validated dict of Task fields
using a locally running Ollama model (default: mistral). No API key required.
Ollama must be running: `ollama serve`

All calls and validation outcomes are logged to pawpal_ai.log.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ─── Logging ────────────────────────────────────────────────────────────────
logger = logging.getLogger("pawpal.ai_parser")
if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    _fh = logging.FileHandler("pawpal_ai.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_fh)
    logger.addHandler(_sh)
    logger.setLevel(logging.INFO)

# ─── Ollama config ──────────────────────────────────────────────────────────
# Override via .env if needed: OLLAMA_URL or OLLAMA_MODEL
OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")

# ─── Constants ──────────────────────────────────────────────────────────────
VALID_TYPES       = {"feeding", "grooming", "medication", "vet", "exercise"}
VALID_RECURRENCES = {"daily", "weekly", "monthly", None}

# ─── System prompt ──────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a pet care task parser. Respond with ONLY a valid JSON object — no explanation, \
no markdown, no code fences. Do not include any text before or after the JSON.

Today's date is {today}. The pet's name is {pet_name}.

Required JSON fields:
  "type"        — exactly one of: "feeding", "grooming", "medication", "vet", "exercise"
  "description" — short task label, do NOT include the pet name
  "due_date"    — ISO 8601 string, e.g. "2026-04-28T09:00:00"

Optional JSON field:
  "recurrence"  — one of: "daily", "weekly", "monthly", or null

Rules:
  - "tomorrow"           → {today} + 1 day
  - "next week"          → {today} + 7 days
  - "every day"          → recurrence "daily"
  - "every 2 weeks"      → recurrence "weekly"
  - "once a month"       → recurrence "monthly"
  - No time stated       → use 09:00:00

If you cannot determine "type" or "due_date", return: {{"error": "reason"}}

Example — input: "Flea medication every two weeks starting tomorrow at 9am"
Example — output: {{"type":"medication","description":"Flea medication","due_date":"2026-04-28T09:00:00","recurrence":"weekly"}}
"""


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that the model may add despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text


def _extract_json_object(text: str) -> str:
    """Pull out the first {...} block from text in case the model adds surrounding words."""
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_task_from_text(
    user_text: str,
    pet_name:  str,
    owner_id:  str,
) -> tuple[Optional[dict], Optional[str]]:
    """Parse a natural language task description into validated Task field values.

    Args:
        user_text: Free-text description from the user.
        pet_name:  Name of the pet (injected into the system prompt).
        owner_id:  Owner ID (used for log correlation only).

    Returns:
        On success: (dict with type/description/due_date/recurrence, None)
        On failure: (None, human-readable error string)

        Never raises — all errors are caught and returned as strings.
    """
    logger.info(
        "parse_task_from_text | owner=%s pet=%s model=%s input=%r",
        owner_id, pet_name, OLLAMA_MODEL, user_text,
    )

    today_str = datetime.now().strftime("%Y-%m-%d")
    system    = _SYSTEM_PROMPT.format(today=today_str, pet_name=pet_name)

    payload = json.dumps({
        "model":    OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_text},
        ],
        "stream":  False,
        "options": {"temperature": 0},   # deterministic — better for JSON extraction
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # ── Call Ollama ──────────────────────────────────────────────────────────
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        raw = _strip_fences(result["message"]["content"])
        raw = _extract_json_object(raw)
        logger.info("Ollama raw response: %s", raw)

    except urllib.error.URLError as exc:
        logger.error("Ollama connection error: %s", exc)
        if "Connection refused" in str(exc):
            return None, (
                "Ollama is not running. "
                "Start it with: ollama serve"
            )
        return None, f"Could not reach Ollama at {OLLAMA_URL}: {exc}"
    except Exception as exc:
        logger.error("Ollama unexpected error: %s", exc)
        return None, f"Ollama error: {exc}"

    # ── Parse JSON ───────────────────────────────────────────────────────────
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("JSON parse failed | raw=%r | error=%s", raw, exc)
        return None, (
            "The model returned an unexpected format. "
            "Try rephrasing — include a task type (e.g. medication, feeding) and a date."
        )

    if "error" in data:
        logger.warning("Model returned error field: %s", data["error"])
        return None, (
            f"Couldn't parse: {data['error']}. "
            "Try being more specific — include a task type and a date."
        )

    # ── Validate required fields ─────────────────────────────────────────────
    missing = [f for f in ("type", "description", "due_date") if f not in data]
    if missing:
        logger.error("Missing fields %s in: %s", missing, data)
        return None, f"Response was missing: {', '.join(missing)}. Try rephrasing."

    if data["type"] not in VALID_TYPES:
        logger.error("Invalid type %r", data["type"])
        return None, (
            f"'{data['type']}' is not a valid task type. "
            f"Must be one of: {', '.join(sorted(VALID_TYPES))}."
        )

    try:
        due_date = datetime.fromisoformat(data["due_date"])
    except (ValueError, TypeError) as exc:
        logger.error("Invalid due_date %r: %s", data.get("due_date"), exc)
        return None, (
            f"Unparseable date: '{data.get('due_date')}'. "
            "Try including a specific date (e.g. 'tomorrow', 'May 5th')."
        )

    recurrence = data.get("recurrence")
    if recurrence not in VALID_RECURRENCES:
        logger.warning("Invalid recurrence %r — defaulting to None", recurrence)
        recurrence = None

    result = {
        "type":        data["type"],
        "description": data["description"],
        "due_date":    due_date,
        "recurrence":  recurrence,
    }
    logger.info(
        "parse_task_from_text success | owner=%s pet=%s result=%s",
        owner_id, pet_name, result,
    )
    return result, None
