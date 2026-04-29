# PawPal+ — AI-Powered Pet Care Scheduling System

A full-stack AI application that helps multi-pet owners plan, schedule, and track consistent care routines — combining a robust domain model with locally-run LLM features that understand natural language and generate context-aware care plans.

---

## Original Project (Modules 1–3): PawPal

The foundation of this project is **PawPal**, a Python-based pet care scheduling system built across the first three modules of the Applied AI Systems course. The original system modeled the real-world complexity of managing care for multiple pets: an `Owner` registers one or more `Pet` profiles, creates `Task` objects for feeding, grooming, medication, vet visits, and exercise, and relies on a central `Scheduler` to detect time conflicts, sort tasks by medical priority, and automatically advance recurring tasks. The core goals were to produce a well-tested, cleanly separated domain model that could later serve as a stable base for AI integration without requiring a database, API key, or external service for the core logic to function.

---

## Title and Summary

**PawPal+** extends that foundation with two AI-powered input modes, both running on a local Ollama/Mistral instance:

- **Natural Language Task Entry** — Instead of filling out a form, an owner types a sentence like *"Flea medication every two weeks starting tomorrow at 9 a.m."* The AI extracts structured fields (task type, due date, recurrence) and creates the task automatically.
- **AI Care Planner** — An owner describes a care goal such as *"Set up a 2-week post-surgery recovery plan for Mochi."* The AI reads the pet's live profile and current schedule, then proposes a full multi-task plan. The owner reviews and confirms before anything is saved.

Both features keep the human in control: the AI proposes, the owner decides. This reflects a deliberate design philosophy where AI should reduce friction, not remove agency.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      UI Layer  (app.py)                         │
│   Section 1: Owner & Pet Registration                           │
│   Section 2: Task Management                                    │
│     ├── Manual Entry                                            │
│     ├── Natural Language Entry  ──► ai_parser.py                │
│     └── AI Care Planner         ──► ai_planner.py               │
│   Section 3: Schedule Builder                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │  all paths produce identical Task objects
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               Domain Layer  (pawpal_system.py)                  │
│   Owner ──► Pet ──► Task ──► Scheduler                          │
│   • Priority-aware chronological sorting                        │
│   • 30-minute conflict detection (same-pet & cross-pet)         │
│   • Recurring task auto-advance anchored to today               │
│   • Status history (pending / completed tabs)                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  AI Layer  (ai_parser.py, ai_planner.py)        │
│   Ollama REST API  →  Mistral 7B (local, no API key required)   │
│   http://localhost:11434                                        │
│   All calls logged to pawpal_ai.log                             │
└─────────────────────────────────────────────────────────────────┘
```

The three input paths (manual, natural language, care planner) all converge on the same `Scheduler.add_task()` method, ensuring conflict detection and priority sorting are applied consistently regardless of how a task originated. The domain layer has no knowledge of Ollama; the AI layer has no knowledge of the UI. This clean separation means the core scheduling system works even when Ollama is unavailable.

---

## Setup Instructions

### Prerequisites

1. **Python 3.10+**
2. **Ollama** — download from [ollama.com](https://ollama.com) and install for your OS
3. Pull the Mistral model (one-time download, ~4 GB):
   ```bash
   ollama pull mistral
   ```

### Install and Run

```bash
# 1. Clone the repository
git clone https://github.com/renubandaru/applied-ai-system-project.git
cd applied-ai-system-project

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start Ollama in a separate terminal (keep it running)
ollama serve

# 5. Launch the app
streamlit run app.py
```

The app opens at **http://localhost:8501**.

### Optional Configuration

Create a `.env` file in the project root to override Ollama defaults:

```
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral
```

### Run Tests

```bash
python -m pytest tests/ -v
```

---

## Sample Interactions

### Interaction 1 — Natural Language Task Entry

**User types in the AI text box:**
> "Flea medication every two weeks starting tomorrow at 9am"

**System response (extracted fields shown in an expandable panel, then task saved):**
```
Task type:    medication
Description:  Flea medication
Due date:     2026-04-29 09:00
Recurrence:   weekly

✅ Task added successfully for Mochi.
```
The AI returns a structured JSON object; the app validates every field before constructing a `Task` and passing it to the Scheduler.

---

### Interaction 2 — AI Care Planner (Post-Surgery Recovery)

**User types a care goal:**
> "Set up a 2-week post-surgery recovery plan for Mochi. She just had a splenectomy."

**Proposed task table displayed before confirmation:**

| # | Type | Description | Due Date | Recurrence |
|---|---|---|---|---|
| 1 | medication | Pain medication (Buprenorphine) | 2026-04-29 08:00 | daily |
| 2 | vet | Surgical site check — Day 3 | 2026-05-01 10:00 | None |
| 3 | feeding | Small, frequent meals — soft food only | 2026-04-29 07:00 | daily |
| 4 | medication | Antibiotic course (Amoxicillin) | 2026-04-29 08:30 | daily |
| 5 | vet | Suture removal appointment | 2026-05-13 10:00 | None |

The owner clicks **"Confirm and add all tasks"** — all five enter the Scheduler at once. Any conflicts with existing tasks surface as warnings before the button is shown.

---

### Interaction 3 — Conflict Detection

**Scenario:** Owner adds a grooming session for Luna at 3:00 PM. An existing feeding task for Max (a different pet, same owner) is already at 3:10 PM.

**System response:**
```
⚠️ Owner conflict: you already have a task for Max (feeding) at 3:10 PM 
on the same day. Task added, but review your schedule.
```

The task is saved and the owner retains full control, but the warning is prominently shown so they can adjust if needed.

---

### Interaction 4 — Overdue Recurring Task Auto-Advance

**Scenario:** A weekly nail trim was last completed on 2026-03-01. The owner opens the app several weeks later.

**System behavior:**  
The Scheduler automatically calculates the next occurrence anchored to today, so the task appears due soon rather than weeks overdue. No manual rescheduling is required; the system never schedules a recurring task in the past.

---

## Demo

<video src="https://github.com/user-attachments/assets/3ee92b5d-d114-4bb0-9fa9-5f965fbf7035" controls width="100%"></video>

> If the video does not play, view the walkthrough directly in the [assets/](assets/) folder.

---

## Design Decisions

### 1. AI as an Input Layer, Not a Core Dependency

The AI features sit entirely above the domain model. `pawpal_system.py` was written in Module 1 and was never modified when adding AI. This means the app degrades gracefully ensuring that if Ollama is not running, manual task entry still works perfectly.

**Trade-off:** All validation work to bridge the model's open-ended output to strict Python types (task type enum, ISO 8601 datetime, recurrence enum) lives in `ai_parser.py` and `ai_planner.py`. The mapping layer is non-trivial, but it kept the domain model clean and stable.

### 2. Local LLM via Ollama — No API Key, No Cloud

Using Ollama with Mistral means the app runs entirely offline, with no API costs and no data leaving the machine which is appropriate for a pet health app that may contain sensitive medical history.

**Trade-off:** Mistral's capabilities are lower than GPT-4 or Claude. Complex care plan requests occasionally produce malformed JSON. The validation layer handles this gracefully, but prompt engineering had to be more precise than it would be with a frontier model.

### 3. Human-in-the-Loop for the Care Planner

Feature 2 deliberately separates proposal from confirmation. Proposed tasks are held in `st.session_state` and shown to the user before any task enters the Scheduler. The owner must click "Confirm" explicitly.

**Trade-off:** One extra click. But for a healthcare-adjacent domain, where a wrongly scheduled medication could cause real harm, keeping the user in control is the right call. Auto-scheduling would be faster but less safe.

### 4. Temperature 0 for Structured Extraction

Both AI modules call Ollama with `temperature: 0`. Deterministic output is necessary for structured data extraction and creativity is a liability when the model needs to return a specific JSON schema with an ISO 8601 date and a valid enum value.

### 5. Persistent Session State for AI Results

Streamlit reruns the entire script on every interaction. Without explicit session state management, the Care Planner's proposed tasks would vanish the moment the user scrolled. All AI results are stored in `st.session_state` with stable keys that survive reruns.

### 6. Conflict Detection That Warns Without Blocking

The Scheduler always adds a task, even when a conflict is detected. It returns a warning string instead of raising an exception. Owners of multiple pets legitimately need to handle overlapping care windows, and hard blocks would force frustrating workarounds.

---

## Testing Summary

**43 tests total, all passing** across two test files.

### Domain Layer — [tests/test_pawpal.py](tests/test_pawpal.py) — 13 tests

| Category | Tests |
|---|---|
| Chronological task sorting | 3 |
| Medical-priority tie-breaking | 2 |
| Recurrence logic (daily / weekly / monthly) | 3 |
| Overdue recurring task rescheduling | 1 |
| Conflict detection (same-pet, cross-pet, different owners) | 3 |
| Completed tasks vacating conflict slots | 1 |

### AI Layer — [tests/test_ai_layer.py](tests/test_ai_layer.py) — 30 tests

All AI tests mock `urllib.request.urlopen` so they run without Ollama running — the mock simulates any model output or failure mode deterministically.

**`ai_parser` (16 tests)**

| Category | Tests |
|---|---|
| Valid response → correct dict with all fields | 3 |
| Output cleaning (markdown fences, surrounding prose) | 2 |
| Missing required fields (type, due_date, description) | 3 |
| Invalid field values (bad type, bad date, bad recurrence) | 3 |
| Model returns `{"error": ...}` or plain text | 2 |
| Connection refused, network error, unexpected exception | 3 |

**`ai_planner` (14 tests)**

| Category | Tests |
|---|---|
| Valid response → Task objects with correct IDs and ownership | 4 |
| Invalid items skipped (bad type, bad date, all invalid) | 3 |
| Invalid recurrence clamped to None | 1 |
| Internal plan conflict drops second overlapping item | 1 |
| Scheduler conflict keeps item in proposal for user review | 1 |
| Connection refused, object-not-array, plain text, unexpected exception | 4 |

### What Worked

- **Priority tie-breaking** — The sorting key `(due_date, PRIORITY_MAP.get(task.type, 99))` handles unknown task types gracefully by sorting them last rather than crashing.
- **Recurrence anchoring** — Anchoring `get_next_occurrence()` to today rather than the original due date ensures overdue recurring tasks never schedule themselves in the past. This was explicitly verified in a test before the AI features were added.
- **Conflict detection** — Correctly distinguishes same-pet and cross-pet conflicts, and correctly ignores completed tasks when checking overlaps.
- **Testing the AI validation layer without Ollama** — Mocking the HTTP call let every validation and error-handling path be tested in isolation, fast and reproducibly. Each distinct failure mode (missing field, bad enum, non-JSON, connection refused) got its own test.
- **Separation of concerns paid off in testing** — Because the AI modules never raise exceptions and always return `(result, error_string)`, every test could assert on the return value without try/except boilerplate. The clean interface made the tests simple to write.
- **Testing before AI integration** — Having a verified domain layer made debugging the AI features significantly faster. When an AI-generated task behaved unexpectedly, the Scheduler logic could be ruled out immediately.

### What Didn't Work / Known Limitations

- **Month-boundary recurrence** uses a fixed 30-day delta rather than calendar-aware logic. A task due January 31 advanced by one "month" lands March 2, not February 28.
- **Streamlit UI layer** is not covered by automated tests. Feature correctness was verified manually through the running app.
- **No end-to-end integration test** covers the full path from text input → AI parsing → Task creation → Scheduler conflict detection. Each layer is tested in isolation.
- **No real model calls in tests** — the mocked tests verify that the validation logic handles bad output correctly, but they don't test whether the prompts actually produce good output from Mistral. That gap can only be closed with a separate manual or integration test that hits a live Ollama instance.

### What I Learned About Testing AI Systems

Testing the validation layer with mocks was straightforward as it's just regular Python unit testing. The harder insight was recognizing what mocks *cannot* test: prompt quality, model consistency across phrasings, and latency under load. Those require a live model and human evaluation. The automated tests give confidence that the system handles bad output gracefully; they say nothing about how often bad output actually occurs. A complete test strategy needs both.

---

## Critical Reflection

### Limitations and Biases

The task type enum (`feeding`, `grooming`, `medication`, `vet`, `exercise`) is a hardcoded bias. It reflects assumptions about dogs and cats and breaks down for exotic pets. The medical priority order (`medication > vet > feeding > ...`) is an opinion baked into code: a diabetic pet's feeding is more urgent than a grooming appointment, but the system can't know that. Most critically, the Care Planner has no real medical knowledge, it suggests drug names and dosages that sound plausible but are not verified. It presents a post-surgery medication schedule with the same confidence it presents a feeding routine.

### Could It Be Misused?

The most realistic risk is an owner treating the Care Planner's output as veterinary advice. The model will confidently propose specific medications for complex conditions without any clinical grounding. Mitigations are already in place. The human-in-the-loop confirmation step prevents anything from being scheduled without explicit owner approval, and the app runs entirely locally so no data leaves the machine. What's missing is a visible disclaimer on Care Planner output stating it is not veterinary advice, and filtering that flags or suppresses specific drug names before they reach the user.

### What Surprised Me About AI Reliability

The model failed *consistently*, not randomly. With temperature 0, Mistral would reliably wrap JSON in markdown fences despite being told not to, reliably use `"task_type"` instead of `"type"` for certain phrasings, and reliably add a sentence of explanation before the JSON object. Once the failure modes were known, defensive code could be written for each one — `_strip_fences()` and `_extract_json_object()` both exist because of observed, repeatable failures. The other surprise was a 3 a.m. medication reminder generated during early testing, when the planner was allowed to auto-schedule. The model had no concept of realistic care hours. That single output is why the confirmation step exists.

### Collaboration with AI

**Helpful:** Using `unittest.mock.patch("urllib.request.urlopen")` to mock the Ollama HTTP call entirely, rather than running tests against a live server, was the right structural call. Every test runs in under a second, works without any local setup, and can simulate failure modes that would be hard to trigger against a real server.

**Flawed:** The README's sample Care Planner output table lists specific medication names ("Buprenorphine", "Amoxicillin") as if they represent typical model output. Those were fabricated for illustration. A real Mistral response for the same prompt produces different names and wording depending on slight context variations. The example makes the output look more consistent and clinically precise than it actually is in practice.

---

## Reflection

### What This Project Taught Me About AI

The most surprising realization was how much engineering lives *outside* the model. Writing a good prompt took a few tries. Writing the validation, error handling, session state management, and graceful degradation code took days. The model is a small fraction of a working AI system whilee the real engineering challenge is everything around it: how you feed data in, how you validate what comes out, how you keep the user informed when things go wrong, and how you make the overall system feel reliable even when the model occasionally isn't.

I also learned that local models like Mistral are genuinely capable for structured extraction tasks when prompted carefully. Temperature 0 and an explicit JSON schema in the system prompt made a significant difference in output reliability. Mistral's failures were predictable and handleable rather than mysterious, that predictability made it a valuable learning environment.

### What This Project Taught Me About Problem-Solving

The best technical decision I made was not modifying `pawpal_system.py` when adding AI features. It was tempting to add AI-specific fields to `Task` or shortcuts to `Scheduler`. Resisting that kept the domain model clean and made the AI integration genuinely modular. The guiding question — *does this change belong to the domain, or to the input layer?* — is a principle I'll carry into future projects.

The human-in-the-loop design for the Care Planner came from a concrete failure during development: I let the planner auto-schedule a set of proposed tasks and watched it create a medication reminder at 3 a.m. It was technically valid output; it was also completely useless in practice. That moment made the value of a confirmation step immediately obvious. AI systems operating in real-world domains — especially health-adjacent ones — need human review, not because the model is untrustworthy in general, but because the model doesn't know what the user actually needs.

Finally, building the UI taught me that functional correctness and user-experience correctness are different problems. A feature can pass all its unit tests and still feel broken because a loading spinner disappears too fast or a result disappears on the next interaction. Testing the golden path manually across realistic scenarios is irreplaceable.

---

## Project Structure

```
applied-ai-system-project/
├── app.py                  # Streamlit UI (4 sections, session state management)
├── pawpal_system.py        # Core domain model — Owner, Pet, Task, Scheduler
├── ai_parser.py            # Feature 1: natural language → validated task fields
├── ai_planner.py           # Feature 2: care goal + pet context → multi-task plan
├── requirements.txt        # streamlit, pytest, python-dotenv
├── ARCHITECTURE.md         # Detailed system diagrams and design notes
├── reflection.md           # Extended project reflection
├── tests/
│   ├── test_pawpal.py      # 13 unit tests covering core scheduler behaviors
│   └── test_ai_layer.py    # 30 unit tests for ai_parser.py and ai_planner.py
└── .env (optional)         # OLLAMA_URL and OLLAMA_MODEL overrides
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Domain logic | Python 3.10+ dataclasses |
| AI inference | Ollama (local) + Mistral 7B |
| Testing | pytest |
| Configuration | python-dotenv |

---

*Built by Venkata Sai Renusree Bandaru as the capstone project for an Applied AI Systems course.*
