# PawPal+ System Architecture

This document describes how PawPal+ is structured, and exactly where the two AI features
(Natural Language Task Entry and AI Pet Care Planner Agent) plug into that structure.
Read this before looking at code — it maps every file change to the reason it exists.

---

## Current Architecture (Phases 1–6)

Four classes, one UI layer, no persistence.

```
┌──────────────────────────────────────────────────────────┐
│                  Streamlit UI  (app.py)                  │
│                                                          │
│  [Owner & Pet form] → [Task form] → [Schedule view]      │
└────────────────────────┬─────────────────────────────────┘
                         │ creates objects, calls methods
┌────────────────────────▼─────────────────────────────────┐
│             Domain Logic  (pawpal_system.py)              │
│                                                          │
│   Owner ──owns──▶ Pet ──has──▶ Task                      │
│                                  │                       │
│                    Scheduler ◀───┘  (master task list)   │
│                        │                                 │
│                        ├─ add_task()                     │
│                        ├─ get_upcoming_tasks()            │
│                        ├─ has_conflict()                  │
│                        └─ check_overdue_tasks()           │
└──────────────────────────────────────────────────────────┘
```

**Current task-creation data flow (form path):**
```
User fills dropdowns/date pickers
  → Task(type, description, due_date, recurrence, ...) created in app.py
  → Scheduler.add_task(task, pet)
  → conflict check runs (has_conflict)
  → task stored in scheduler.tasks[]
  → conflict warning shown in UI (if any)
```

Everything is rule-based. No AI anywhere in the pipeline.

---

## Phase 7: AI Integration — Overview

Two features are being added. Neither changes `pawpal_system.py` — the domain model is
untouched. AI is a new *input layer* that produces the same Task objects the Scheduler
already knows how to handle.

```
                        BEFORE (Phase 1–6)
User ──[form]──────────────────────────────────▶ Task() ──▶ Scheduler

                        AFTER (Phase 7)
User ──[form]──────────────────────────────────▶ Task() ──▶ Scheduler
User ──[text]──▶ ai_parser.py ──▶ Claude API ──▶ Task() ──▶ Scheduler  ← Feature 1
User ──[goal]──▶ ai_planner.py ──▶ Claude (tool-use loop)              ← Feature 2
                                       │ calls tools that call Scheduler methods
                                       ▼
                              Task() created for each step ──▶ Scheduler
```

---

## Feature 1: Natural Language Task Entry

### What changes and why

Right now the user must fill out five form fields (title, type, date, time, recurrence)
to create one task. The AI replaces that entire flow: the user types one sentence and
the system extracts all five fields automatically.

**The AI is in the critical path.** If Claude fails or returns an invalid field,
no task is created. This prevents silent bad data from entering the Scheduler.

### Where the new code lives

```
┌─────────────────────────────────────────────────────────────────┐
│                   Streamlit UI  (app.py)  — MODIFIED            │
│                                                                 │
│  Section 2: Tasks                                               │
│  ┌────────────────────┐  ┌──────────────────────────────────┐  │
│  │  📋 Manual Entry   │  │  ✨ AI – Describe in Plain English│  │
│  │  (unchanged form)  │  │                                  │  │
│  │                    │  │  text_area("Task description")   │  │
│  │                    │  │  button("Add task from desc.")   │  │
│  │                    │  │         │                        │  │
│  └────────────────────┘  │         ▼                        │  │
│                           │  parse_task_from_text()         │  │
│                           │    (ai_parser.py)               │  │
│                           └──────────────────────────────────┘  │
│                                      │                          │
│                                      │ validated dict           │
│                                      ▼                          │
│                         Task() ──▶ Scheduler.add_task()         │
└─────────────────────────────────────────────────────────────────┘
                                   │ unchanged
┌──────────────────────────────────▼──────────────────────────────┐
│                   Domain Logic  (pawpal_system.py)               │
│                   NO CHANGES — same Task and Scheduler as before │
└─────────────────────────────────────────────────────────────────┘
```

### New file: `ai_parser.py`

Single responsibility: convert free text → validated field dict.

```
parse_task_from_text(user_text, pet_name, owner_id)
  │
  ├─ Check ANTHROPIC_API_KEY is set          ← guardrail
  ├─ Log: input text, owner, pet            ← logging
  ├─ Call Claude API (claude-haiku-4-5)
  │     system prompt: today's date, valid types, JSON-only output
  ├─ Log: raw Claude response               ← logging
  ├─ Parse JSON from response
  ├─ Validate required fields present       ← guardrail
  ├─ Validate type in allowed set           ← guardrail
  ├─ Parse due_date as datetime             ← guardrail
  ├─ Clamp recurrence to valid values       ← guardrail
  ├─ Log: final validated result            ← logging
  └─ Return (result_dict, None)
       OR (None, "human-readable error")    ← never raises
```

All errors are caught and returned as strings so the UI can display them without crashing.

### Data flow (NL path, step by step)

```
1. User types: "Buddy needs flea medication every two weeks starting tomorrow at 9am"

2. app.py calls:
   parse_task_from_text(text="Buddy needs flea...", pet_name="Buddy", owner_id="jordan")

3. ai_parser.py sends to Claude:
   System: "Today is 2026-04-27. Extract task as JSON. type must be one of [...]"
   User:   "Buddy needs flea medication every two weeks starting tomorrow at 9am"

4. Claude returns:
   {"type": "medication", "description": "Flea medication",
    "due_date": "2026-04-28T09:00:00", "recurrence": "weekly"}

5. ai_parser.py validates each field, parses due_date to datetime object.
   Returns: ({"type": "medication", "description": "Flea medication",
              "due_date": datetime(2026,4,28,9,0), "recurrence": "weekly"}, None)

6. app.py creates:
   Task(task_id="t3", type="medication", description="Flea medication",
        pet_id="Buddy", owner_id="jordan",
        due_date=datetime(2026,4,28,9,0), recurrence="weekly")

7. Scheduler.add_task(task, pet) — same path as the manual form.
   Conflict check runs. Task stored in scheduler.tasks[].

8. UI shows: extracted fields (transparent) + success or conflict message.
```

### Logging & guardrails

Every call to `parse_task_from_text()` writes to `pawpal_ai.log`:

```
2026-04-27 10:15:32 [INFO]  pawpal.ai_parser: parse_task_from_text called | owner=jordan pet=Buddy input='Buddy needs flea...'
2026-04-27 10:15:33 [INFO]  pawpal.ai_parser: Claude raw response: {"type": "medication", ...}
2026-04-27 10:15:33 [INFO]  pawpal.ai_parser: parse_task_from_text success | result={...}
```

Guardrails (all return `(None, error_string)` — never crash):
- Missing `ANTHROPIC_API_KEY` → error message shown in UI
- API connection failure → user-friendly message
- Invalid API key → user-friendly message
- Rate limit hit → retry suggestion
- Non-JSON response from Claude → error message
- Claude returns `{"error": "..."}` → that message shown to user
- Missing required fields in response → error message
- `type` not in valid set → rejected
- `due_date` not parseable as datetime → rejected
- Invalid `recurrence` → silently defaulted to `None` (safe fallback)

---

## Feature 2: AI Pet Care Planner Agent *(implemented next)*

### What changes and why

The user describes a care situation in one sentence. An agent with tools calls your
existing Scheduler methods iteratively — checking pet profiles, detecting conflicts,
creating tasks — until it assembles a complete care plan. The plan is shown for review
before the user confirms it.

The key difference from Feature 1: the Planner **calls multiple Scheduler methods
in a loop** (tool use), not just once. The agent reasons about conflicts and adjusts
its plan before presenting it.

### New file: `ai_planner.py`

```
run_planner_agent(goal, pet, owner, scheduler)
  │
  ├─ Build tool definitions wrapping Scheduler methods:
  │     get_pet_profile()   → pet.get_profile() + medical_history
  │     get_schedule()      → scheduler.get_upcoming_tasks(7)
  │     check_conflict()    → scheduler.has_conflict(task)
  │     create_task()       → builds Task object, adds to proposed list
  │
  ├─ Send goal + tools to Claude (claude-sonnet-4-6)
  ├─ Tool-use loop:
  │     Agent calls tools → tools call real Scheduler methods
  │     Results returned to agent → agent reasons → calls more tools
  │     Loop ends when agent returns final plan
  ├─ Log every tool call + agent reasoning step
  └─ Return list of proposed Task objects (NOT yet in Scheduler)

app.py shows the plan → user clicks "Confirm plan" → tasks added to Scheduler
```

### Integration point

```
┌─────────────────────────────────────────────────────────────────┐
│                   Streamlit UI  (app.py)  — MODIFIED            │
│                                                                 │
│  Section 4: AI Care Planner  (NEW SECTION)                      │
│                                                                 │
│  text_area("Describe the situation")                            │
│  button("Generate care plan")                                   │
│         │                                                       │
│         ▼                                                       │
│  run_planner_agent(goal, pet, owner, scheduler)                 │
│    (ai_planner.py — tool-use loop)                              │
│         │                                                       │
│         ▼                                                       │
│  Display proposed tasks (type, description, date, recurrence)   │
│  button("Confirm and add all tasks")                            │
│         │                                                       │
│         ▼                                                       │
│  For each proposed task: Scheduler.add_task(task, pet)          │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Map

| File | Role | Status |
|---|---|---|
| `pawpal_system.py` | Domain logic: Pet, Task, Owner, Scheduler | **Unchanged** |
| `app.py` | Streamlit UI and session state | Modified (Features 1 & 2) |
| `ai_parser.py` | NL text → structured Task fields via Claude | **New — Feature 1** |
| `ai_planner.py` | Agentic care plan generator via Claude tool use | **New — Feature 2** |
| `requirements.txt` | Python dependencies | Modified (adds `anthropic`) |
| `pawpal_ai.log` | Runtime log of all AI calls and outcomes | Generated at runtime |
| `tests/test_pawpal.py` | Unit tests for domain logic | Unchanged |

---

## Setup (with AI Features)

### Prerequisites

You need an Anthropic API key. Get one at [console.anthropic.com](https://console.anthropic.com).

### Step 1 — Set the API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add this to your shell profile (`~/.zshrc` or `~/.bashrc`) to avoid setting it every session.

### Step 2 — Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3 — Run the app

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`. The AI tab appears in the Tasks section.
All AI calls are logged to `pawpal_ai.log` in the project root.

### Verifying the setup

If `ANTHROPIC_API_KEY` is not set, the AI tab will show a clear error message instead
of crashing. The manual form tab continues to work without any API key.

---

## Key Design Principles

| Principle | How it's applied |
|---|---|
| `pawpal_system.py` is untouched | AI is a new input adapter — the domain model is not polluted with API concerns |
| AI is in the critical path | If parsing fails, no task is created — no silent bad data enters the Scheduler |
| Guardrails at the AI boundary | Every field Claude returns is validated before a Task object is constructed |
| Transparent extraction | The UI shows what the AI extracted before confirming the task, so the user can see exactly what happened |
| Errors never crash the app | All API and parse errors are caught, logged, and returned as user-friendly strings |
| Planner proposes, human confirms | The agent assembles a plan but the user clicks "Confirm" before tasks enter the Scheduler |
