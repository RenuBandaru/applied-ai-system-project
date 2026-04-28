"""
ai_planner.py — AI Pet Care Planner Agent for PawPal+

Builds a multi-task care plan from a plain-English goal using Ollama (mistral).

How it works:
  1. Fetches the pet's real profile (species, age, medical history) from the Pet object
  2. Fetches the current 14-day schedule from the Scheduler
  3. Sends both as context to the model alongside the user's goal
  4. Model reasons over the real data and returns a JSON array of proposed tasks
  5. Each proposed task is validated and conflict-checked in Python before being returned
  6. Tasks are NOT added to the Scheduler until the user confirms in the UI

The AI actively uses the retrieved data — it reads the pet profile and existing
schedule in its context window and generates tasks tailored to them.

No API key required — Ollama must be running: ollama serve

All calls and outcomes are logged to pawpal_ai.log.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv

from pawpal_system import Owner, Pet, Scheduler, Task

load_dotenv()

# ─── Logging ────────────────────────────────────────────────────────────────
logger = logging.getLogger("pawpal.ai_planner")
if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    _fh = logging.FileHandler("pawpal_ai.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_fh)
    logger.addHandler(_sh)
    logger.setLevel(logging.INFO)

# ─── Config ─────────────────────────────────────────────────────────────────
OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")

VALID_TYPES       = {"feeding", "grooming", "medication", "vet", "exercise"}
VALID_RECURRENCES = {"daily", "weekly", "monthly", None}

# ─── System prompt ──────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an expert pet care planner for the PawPal+ scheduling app.
Today is {today}.

You will receive:
  - A pet's profile (name, species, breed, age, medical history)
  - Their existing schedule for the next 14 days
  - A care goal from the owner

Your job: return ONLY a valid JSON array of proposed tasks. \
No explanation, no markdown, no text before or after the array.

Each task object must have:
  "type"        — exactly one of: "feeding", "grooming", "medication", "vet", "exercise"
  "description" — concise task label (do NOT include the pet name)
  "due_date"    — ISO 8601 datetime string, e.g. "2026-04-29T09:00:00"
  "recurrence"  — one of: "daily", "weekly", "monthly", or null

Planning rules:
  - Use the pet's species, age, and medical history to tailor the tasks
  - Avoid times already occupied in the existing schedule
  - Spread tasks sensibly across the care period (do not pile on day 1)
  - Propose between 3 and 8 tasks — quality over quantity
  - Default time is 09:00:00 unless the goal implies otherwise

Example output (return exactly this structure, nothing else):
[
  {{"type": "medication", "description": "Post-op antibiotics", "due_date": "2026-04-29T08:00:00", "recurrence": "daily"}},
  {{"type": "vet", "description": "Follow-up checkup", "due_date": "2026-05-05T10:00:00", "recurrence": null}}
]
"""


def _strip_fences(text: str) -> str:
    """Remove markdown code fences the model may add despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text


def _extract_json_array(text: str) -> str:
    """Pull out the first [...] block in case the model adds surrounding words."""
    start = text.find("[")
    end   = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def run_planner_agent(
    goal:      str,
    pet:       Pet,
    owner:     Owner,
    scheduler: Scheduler,
) -> tuple[list[Task], Optional[str]]:
    """Build a care plan by giving the model real pet and schedule data as context.

    Steps:
      1. Fetch pet profile from the Pet object (real data)
      2. Fetch current schedule from the Scheduler (real data)
      3. Send both + the goal to the model
      4. Parse the model's JSON task list
      5. Validate types and dates; conflict-check each task in Python
      6. Return validated Task objects (not yet in the Scheduler)

    Args:
        goal:      Plain-English care goal from the user.
        pet:       The registered Pet object.
        owner:     The registered Owner object.
        scheduler: The Scheduler holding all existing tasks.

    Returns:
        On success: (list of proposed Task objects, None)
        On failure: ([], human-readable error string)

        Never raises — all errors are caught and returned as strings.
    """
    logger.info(
        "run_planner_agent | owner=%s pet=%s model=%s goal=%r",
        owner.owner_id, pet.name, OLLAMA_MODEL, goal,
    )

    # ── Step 1: Fetch real pet profile ───────────────────────────────────────
    profile = {
        "name":            pet.name,
        "species":         pet.species,
        "breed":           pet.breed,
        "age_years":       pet.age,
        "medical_history": pet.medical_history if pet.medical_history else ["No history recorded"],
    }
    logger.info("Pet profile fetched: %s", profile)

    # ── Step 2: Fetch real current schedule ──────────────────────────────────
    existing = scheduler.get_upcoming_tasks(14)
    schedule = [
        {
            "description": t.description,
            "type":        t.type,
            "due_date":    t.due_date.strftime("%Y-%m-%d %H:%M"),
            "recurrence":  t.recurrence or "none",
        }
        for t in existing
    ]
    logger.info("Schedule fetched: %d existing tasks", len(schedule))

    # ── Step 3: Build prompt with real data as context ───────────────────────
    today      = datetime.now().strftime("%Y-%m-%d")
    system     = _SYSTEM_PROMPT.format(today=today)
    user_msg   = (
        f"Pet profile:\n{json.dumps(profile, indent=2)}\n\n"
        f"Existing schedule (next 14 days):\n{json.dumps(schedule, indent=2)}\n\n"
        f"Care goal: {goal}"
    )

    payload = json.dumps({
        "model":   OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        "stream":  False,
        "options": {"temperature": 0},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # ── Step 4: Call Ollama and parse the JSON array ─────────────────────────
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())["message"]["content"]
        raw = _strip_fences(raw)
        raw = _extract_json_array(raw)
        logger.info("Model raw response: %s", raw)

    except urllib.error.URLError as exc:
        logger.error("Ollama connection error: %s", exc)
        if "Connection refused" in str(exc):
            return [], "Ollama is not running. Start it with: ollama serve"
        return [], f"Could not reach Ollama at {OLLAMA_URL}: {exc}"
    except Exception as exc:
        logger.error("Ollama unexpected error: %s", exc)
        return [], f"Ollama error: {exc}"

    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            raise ValueError("Expected a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("JSON parse failed | raw=%r | error=%s", raw, exc)
        return [], (
            "The model returned an unexpected format. "
            "Try a more specific goal, e.g. 'Set up a 2-week post-surgery recovery plan.'"
        )

    # ── Step 5: Validate + conflict-check each proposed task ─────────────────
    proposed_tasks: list[Task] = []

    for i, item in enumerate(items):
        # Validate type
        task_type = item.get("type", "")
        if task_type not in VALID_TYPES:
            logger.warning("Item %d skipped — invalid type %r", i, task_type)
            continue

        # Validate due_date
        try:
            due_date = datetime.fromisoformat(item["due_date"])
        except (KeyError, ValueError, TypeError):
            logger.warning("Item %d skipped — invalid due_date %r", i, item.get("due_date"))
            continue

        # Clamp recurrence
        recurrence = item.get("recurrence")
        if recurrence not in VALID_RECURRENCES:
            logger.warning("Item %d recurrence %r clamped to None", i, recurrence)
            recurrence = None

        description = item.get("description", f"{task_type} task")

        temp = Task(
            task_id  = f"plan_{i}",
            type     = task_type,
            description = description,
            pet_id   = pet.name,
            owner_id = owner.owner_id,
            due_date = due_date,
            recurrence = recurrence,
        )

        # Conflict check against the live Scheduler
        conflict = scheduler.has_conflict(temp)
        if conflict:
            logger.warning("Item %d conflict with scheduler: %s", i, conflict)

        # Conflict check against tasks already accepted into the proposed list
        plan_conflict = None
        new_end = due_date + timedelta(minutes=30)
        for accepted in proposed_tasks:
            ex_end = accepted.due_date + timedelta(minutes=30)
            if accepted.due_date < new_end and due_date < ex_end:
                plan_conflict = (
                    f"overlaps with proposed '{accepted.description}' "
                    f"at {accepted.due_date.strftime('%H:%M')}"
                )
                break

        if plan_conflict:
            logger.warning("Item %d skipped — plan conflict: %s", i, plan_conflict)
            continue

        proposed_tasks.append(temp)
        logger.info(
            "Task accepted: type=%s desc=%r date=%s rec=%s",
            task_type, description, due_date, recurrence,
        )

    if not proposed_tasks:
        return [], (
            "The model returned tasks but none passed validation. "
            "Try a more specific goal, e.g. 'Set up a 2-week post-surgery recovery plan for Mochi.'"
        )

    logger.info("run_planner_agent complete | %d tasks proposed", len(proposed_tasks))
    return proposed_tasks, None
