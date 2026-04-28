# PawPal+ System Architecture

This document describes how PawPal+ is structured and exactly where the two AI
features plug into that structure. Read this before looking at code — it maps
every file to the reason it exists and shows the data flow for each path.

---

## Current Architecture (Phase 7 — complete)

```
┌───────────────────────────────────────────────────────────────────┐
│                      Streamlit UI  (app.py)                       │
│                                                                   │
│  Section 1: Owner & Pet Registration                              │
│  Section 2: Tasks  [📋 Manual Entry | ✨ AI – Plain English]      │
│  Section 3: Build Schedule                                        │
│  Section 4: AI Care Planner                                       │
└────────┬──────────────────┬──────────────────┬────────────────────┘
         │                  │                  │
         ▼                  ▼                  ▼
  pawpal_system.py     ai_parser.py       ai_planner.py
  (domain logic —      (Feature 1 —       (Feature 2 —
   unchanged)           NL task entry)     care plan agent)
         │                  │                  │
         └──────────────────┴──────────────────┘
                            │
                            ▼
                    Ollama  (mistral)
                    running locally
                    http://localhost:11434
                    no API key required
```

**Three input paths to create tasks — all produce the same Task object:**

```
Path A (manual):  User fills form ──────────────────────────────────▶ Task() ──▶ Scheduler
Path B (NL):      User types sentence ──▶ ai_parser.py ──▶ Ollama ──▶ Task() ──▶ Scheduler
Path C (planner): User describes goal ──▶ ai_planner.py ──▶ Ollama ──▶ Task[]──▶ Scheduler
                                                                       (after user confirms)
```

`pawpal_system.py` is untouched across all three paths.

---

## Feature 1: Natural Language Task Entry

### What it does

The user types one sentence. Ollama extracts the task type, description, due date,
and recurrence from it. Those fields are validated in Python and used to construct
a `Task` object, which then goes through the same `Scheduler.add_task()` path as
the manual form — including conflict detection.

**The AI is in the critical path.** If Ollama fails or returns an invalid field,
no task is created.

### Data flow

```
1. User types: "Flea medication every two weeks starting tomorrow at 9am"

2. app.py calls:
   parse_task_from_text(user_text, pet_name="Mochi", owner_id="jordan")

3. ai_parser.py builds a prompt with today's date injected:
   System: "Today is 2026-04-28. Extract task as JSON. type must be one of [...]"
   User:   "Flea medication every two weeks starting tomorrow at 9am"
   → POST http://localhost:11434/api/chat  (model: mistral, temperature: 0)

4. Ollama returns:
   {"type": "medication", "description": "Flea medication",
    "due_date": "2026-04-29T09:00:00", "recurrence": "weekly"}

5. ai_parser.py validates every field:
   ✓ type in {"feeding","grooming","medication","vet","exercise"}
   ✓ due_date parses as datetime
   ✓ recurrence clamped to valid set
   Returns: (validated_dict, None)

6. app.py constructs:
   Task(type="medication", description="Flea medication",
        pet_id="Mochi", owner_id="jordan",
        due_date=datetime(2026,4,29,9,0), recurrence="weekly")

7. Scheduler.add_task(task, pet)
   → has_conflict() runs → task stored in scheduler.tasks[]
   → conflict warning shown in UI if any

8. UI shows: what the AI extracted (expandable) + success or conflict message
   Result persists across reruns via st.session_state.nl_parse_result
```

### Guardrails in `ai_parser.py`

All failures return `(None, error_string)` — the function never raises:

| Failure | Handled by |
|---|---|
| Ollama not running | `URLError` catch → "Start with: ollama serve" |
| Non-JSON response | `JSONDecodeError` catch → ask user to rephrase |
| Model returns `{"error": ...}` | Checked explicitly → message shown |
| Missing required fields | Field presence check → message shown |
| Invalid `type` value | Set membership check → rejected |
| Unparseable `due_date` | `fromisoformat` try/except → rejected |
| Invalid `recurrence` | Clamped to `None` (safe fallback, task still created) |

---

## Feature 2: AI Care Planner

### What it does

The user describes a care goal in one sentence. The planner:
1. **Fetches real data** from the live `Pet` and `Scheduler` objects in Python
2. **Sends that data as context** to Ollama alongside the goal
3. **Receives a JSON task array** from the model, reasoned over the real pet profile
   and existing schedule
4. **Validates every task** (type, date, recurrence) and conflict-checks each one
   against both the Scheduler and previously accepted tasks in the plan
5. **Returns proposed `Task` objects** — nothing enters the Scheduler until the
   user clicks **Confirm and add all tasks**

### Data flow

```
1. User types: "Set up a 2-week post-surgery recovery plan for Mochi"

2. app.py calls:
   run_planner_agent(goal, pet, owner, scheduler)

3. ai_planner.py fetches real data from live objects:
   profile  = {name, species, breed, age, medical_history}  ← from Pet object
   schedule = [{description, type, due_date, recurrence}…]  ← from scheduler.get_upcoming_tasks(14)

4. Builds prompt with real data embedded as context:
   System: "Today is 2026-04-28. Use pet profile and schedule to build a plan…"
   User:   "Pet profile: {...}\nExisting schedule: [...]\nGoal: Set up a 2-week…"
   → POST http://localhost:11434/api/chat  (model: mistral, temperature: 0)

5. Ollama returns a JSON array:
   [
     {"type": "medication", "description": "Post-op antibiotics",
      "due_date": "2026-04-29T08:00:00", "recurrence": "daily"},
     {"type": "vet", "description": "Follow-up checkup",
      "due_date": "2026-05-05T10:00:00", "recurrence": null},
     …
   ]

6. ai_planner.py validates each item:
   ✓ type in valid set           → skip with log warning if invalid
   ✓ due_date parses as datetime → skip with log warning if invalid
   ✓ recurrence clamped          → None if unrecognised
   ✓ has_conflict(temp_task)     → logged (task still included, user sees it)
   ✓ conflict vs. earlier items  → skipped if 30-min window overlaps

7. Returns (proposed_tasks: list[Task], None)
   Tasks have task_id="plan_N" — not yet in the Scheduler

8. app.py displays proposed tasks in a table
   Stored in st.session_state.planner_proposal (survives reruns)

9. User clicks "Confirm and add all tasks":
   for task in proposal:
       task.task_id = f"t{len(scheduler.tasks) + 1}"
       scheduler.add_task(task, pet)   ← same path as manual form
   Tasks appear immediately in Pending tab and Build Schedule
```

### Guardrails in `ai_planner.py`

| Failure | Handled by |
|---|---|
| Ollama not running | `URLError` catch → "Start with: ollama serve" |
| Non-JSON / non-array response | `JSONDecodeError` + isinstance check → user message |
| Invalid `type` in any item | Item skipped, warning logged |
| Unparseable `due_date` in any item | Item skipped, warning logged |
| Plan-internal conflict (30-min overlap) | Item skipped, warning logged |
| Model returns 0 valid tasks | Returns `([], error_string)` — UI shows message |
| Any other exception | Caught → user-friendly error string returned |

---

## File Map

| File | Role | Changed in Phase 7? |
|---|---|---|
| `pawpal_system.py` | Domain logic: Pet, Task, Owner, Scheduler | **No — untouched** |
| `app.py` | Streamlit UI and session state | Yes — Sections 2 & 4 added |
| `ai_parser.py` | NL text → validated Task fields via Ollama | **New — Feature 1** |
| `ai_planner.py` | Care plan generator via Ollama | **New — Feature 2** |
| `requirements.txt` | Python dependencies | Yes — added `python-dotenv` |
| `.gitignore` | Git exclusions | Yes — recreated |
| `ARCHITECTURE.md` | This document | Yes — created & updated |
| `pawpal_ai.log` | Runtime log of all AI calls | Generated at runtime |
| `tests/test_pawpal.py` | Unit tests for domain logic | No |
| `assets/` | UML diagrams (reorganised from root) | Moved |

---

## Setup

### Prerequisites

Ollama must be installed and running. No API key is required.

```bash
# Install Ollama: https://ollama.com
ollama pull mistral       # download the model (one-time, ~4 GB)
ollama serve              # start the local server (keep this running)
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run the app

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. All AI calls are logged to `pawpal_ai.log`.

### Optional configuration via `.env`

```
OLLAMA_URL=http://localhost:11434   # default — change if Ollama runs on a different port
OLLAMA_MODEL=mistral                # default — change to any model you have pulled
```

`.env` is excluded from git by `.gitignore`.

---

## Key Design Principles

| Principle | How it is applied |
|---|---|
| `pawpal_system.py` is untouched | AI is a new input layer — domain model has no API concerns |
| AI is in the critical path (Feature 1) | If parsing fails, no task is created — no silent bad data |
| Real data drives the plan (Feature 2) | Pet profile and schedule are fetched from live objects before the model is called |
| Guardrails at every AI boundary | Every field the model returns is validated in Python before a Task is constructed |
| Errors never crash the app | All failures are caught and returned as strings for the UI to display |
| Planner proposes, human confirms | Agent assembles a plan; tasks enter the Scheduler only after the user clicks Confirm |
| Results survive Streamlit reruns | AI outputs stored in `st.session_state` so one click is enough |
| All AI calls are logged | Every request, response, and validation outcome written to `pawpal_ai.log` |
