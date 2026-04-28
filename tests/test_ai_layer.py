"""
tests/test_ai_layer.py — Automated tests for ai_parser.py and ai_planner.py

All tests mock urllib.request.urlopen so they run without a running Ollama server.
The mock simulates what Ollama returns: {"message": {"content": "<model output>"}}.
"""

import json
import urllib.error
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from ai_parser import parse_task_from_text
from ai_planner import run_planner_agent
from pawpal_system import Owner, Pet, Scheduler, Task


# ─── Shared helpers ──────────────────────────────────────────────────────────

def mock_ollama_response(content: str) -> MagicMock:
    """Return a mock that behaves like urllib.urlopen's context-manager response."""
    body = json.dumps({"message": {"content": content}}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def future_iso(days: int = 1, hour: int = 9) -> str:
    """ISO 8601 datetime string N days from now at the given hour."""
    dt = (datetime.now() + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def planner_item(task_type: str, description: str, days: int = 1,
                 hour: int = 9, recurrence=None) -> dict:
    """Build a single task dict in the format the planner model returns."""
    return {
        "type": task_type,
        "description": description,
        "due_date": future_iso(days, hour),
        "recurrence": recurrence,
    }


# ─── Shared fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def scheduler():
    return Scheduler()


@pytest.fixture
def pet():
    return Pet(name="Mochi", species="Cat", breed="Ragdoll",
               age=3, weight=4.5, owner_id="o1")


@pytest.fixture
def owner(scheduler):
    o = Owner(owner_id="o1", name="Alex",
              email="alex@example.com", phone="555-1234",
              scheduler=scheduler)
    return o


# ═══════════════════════════════════════════════════════════════════════════════
# ai_parser — parse_task_from_text
# ═══════════════════════════════════════════════════════════════════════════════

class TestParserValidResponse:
    """Happy-path: model returns well-formed JSON."""

    def test_returns_dict_with_all_fields(self):
        content = json.dumps({
            "type": "medication",
            "description": "Flea treatment",
            "due_date": future_iso(),
            "recurrence": "weekly",
        })
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Flea meds weekly starting tomorrow", "Mochi", "o1")

        assert err is None
        assert result["type"] == "medication"
        assert result["description"] == "Flea treatment"
        assert result["recurrence"] == "weekly"
        assert isinstance(result["due_date"], datetime)

    def test_null_recurrence_is_returned_as_none(self):
        content = json.dumps({
            "type": "vet",
            "description": "Annual checkup",
            "due_date": future_iso(),
            "recurrence": None,
        })
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Vet visit tomorrow", "Mochi", "o1")

        assert err is None
        assert result["recurrence"] is None

    def test_all_five_valid_task_types_accepted(self):
        for task_type in ("feeding", "grooming", "medication", "vet", "exercise"):
            content = json.dumps({
                "type": task_type,
                "description": f"{task_type} task",
                "due_date": future_iso(),
            })
            with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
                result, err = parse_task_from_text("some task", "Mochi", "o1")

            assert err is None, f"Valid type '{task_type}' should not produce an error"
            assert result["type"] == task_type


class TestParserOutputCleaning:
    """Model sometimes adds fences or surrounding text despite instructions."""

    def test_strips_markdown_code_fences(self):
        inner = json.dumps({
            "type": "feeding",
            "description": "Morning meal",
            "due_date": future_iso(),
        })
        fenced = f"```json\n{inner}\n```"
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(fenced)):
            result, err = parse_task_from_text("Feed Mochi tomorrow morning", "Mochi", "o1")

        assert err is None
        assert result["type"] == "feeding"

    def test_extracts_json_from_surrounding_prose(self):
        inner = json.dumps({
            "type": "exercise",
            "description": "Morning walk",
            "due_date": future_iso(),
        })
        with_text = f"Here is the extracted task: {inner} Hope that helps!"
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(with_text)):
            result, err = parse_task_from_text("Walk Mochi tomorrow", "Mochi", "o1")

        assert err is None
        assert result["type"] == "exercise"


class TestParserFieldValidation:
    """Validation errors for bad or missing fields."""

    def test_missing_type_returns_error(self):
        content = json.dumps({"description": "Some task", "due_date": future_iso()})
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("some task tomorrow", "Mochi", "o1")

        assert result is None
        assert "type" in err

    def test_missing_due_date_returns_error(self):
        content = json.dumps({"type": "feeding", "description": "Morning meal"})
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Feed Mochi", "Mochi", "o1")

        assert result is None
        assert "due_date" in err

    def test_missing_description_returns_error(self):
        content = json.dumps({"type": "feeding", "due_date": future_iso()})
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Feed Mochi tomorrow", "Mochi", "o1")

        assert result is None
        assert "description" in err

    def test_invalid_task_type_returns_error_naming_the_value(self):
        content = json.dumps({
            "type": "bath",
            "description": "Bubble bath",
            "due_date": future_iso(),
        })
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Bath Mochi tomorrow", "Mochi", "o1")

        assert result is None
        assert "bath" in err

    def test_unparseable_due_date_returns_error(self):
        content = json.dumps({
            "type": "feeding",
            "description": "Lunch",
            "due_date": "tomorrow morning",   # not ISO 8601
        })
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Feed Mochi tomorrow", "Mochi", "o1")

        assert result is None
        assert err is not None

    def test_invalid_recurrence_is_clamped_to_none_not_an_error(self):
        """Unknown recurrence values should silently become None rather than blocking the task."""
        content = json.dumps({
            "type": "medication",
            "description": "Flea meds",
            "due_date": future_iso(),
            "recurrence": "biweekly",   # not in the valid set
        })
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("Flea meds every two weeks", "Mochi", "o1")

        assert err is None
        assert result["recurrence"] is None

    def test_model_error_field_returns_error_to_caller(self):
        """Model can signal its own failure with {"error": "reason"}."""
        content = json.dumps({"error": "Could not determine task type or date"})
        with patch("urllib.request.urlopen", return_value=mock_ollama_response(content)):
            result, err = parse_task_from_text("do the thing", "Mochi", "o1")

        assert result is None
        assert err is not None

    def test_plain_text_response_returns_rephrase_suggestion(self):
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response("I don't understand that request.")):
            result, err = parse_task_from_text("???", "Mochi", "o1")

        assert result is None
        assert err is not None


class TestParserConnectionErrors:
    """Network failures should be caught and returned as strings, never raised."""

    def test_connection_refused_mentions_ollama_serve(self):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")):
            result, err = parse_task_from_text("Feed Mochi tomorrow", "Mochi", "o1")

        assert result is None
        assert "ollama" in err.lower()

    def test_generic_url_error_returns_error_string(self):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Network unreachable")):
            result, err = parse_task_from_text("Feed Mochi tomorrow", "Mochi", "o1")

        assert result is None
        assert err is not None

    def test_unexpected_exception_returns_error_string(self):
        with patch("urllib.request.urlopen",
                   side_effect=RuntimeError("Unexpected crash")):
            result, err = parse_task_from_text("Feed Mochi tomorrow", "Mochi", "o1")

        assert result is None
        assert err is not None


# ═══════════════════════════════════════════════════════════════════════════════
# ai_planner — run_planner_agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlannerValidResponse:
    """Happy-path: model returns a well-formed JSON array."""

    def test_returns_task_objects(self, pet, owner, scheduler):
        items = [
            planner_item("medication", "Post-op antibiotics", days=1, hour=8, recurrence="daily"),
            planner_item("vet", "Surgical site check", days=3, hour=10),
        ]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Recovery plan after surgery", pet, owner, scheduler)

        assert err is None
        assert len(tasks) == 2
        assert all(isinstance(t, Task) for t in tasks)
        assert tasks[0].type == "medication"
        assert tasks[1].type == "vet"

    def test_proposed_tasks_have_plan_prefixed_ids(self, pet, owner, scheduler):
        items = [planner_item("feeding", "Morning meal", days=1, hour=7)]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Daily feeding routine", pet, owner, scheduler)

        assert err is None
        assert tasks[0].task_id == "plan_0"

    def test_tasks_linked_to_correct_pet_and_owner(self, pet, owner, scheduler):
        items = [planner_item("grooming", "Brush coat", days=2, hour=10)]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Grooming plan", pet, owner, scheduler)

        assert err is None
        assert tasks[0].pet_id == pet.name
        assert tasks[0].owner_id == owner.owner_id

    def test_strips_markdown_fences_from_array(self, pet, owner, scheduler):
        items = [planner_item("exercise", "Short walk", days=2, hour=8)]
        fenced = f"```json\n{json.dumps(items)}\n```"
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(fenced)):
            tasks, err = run_planner_agent("Exercise plan", pet, owner, scheduler)

        assert err is None
        assert len(tasks) == 1
        assert tasks[0].type == "exercise"


class TestPlannerItemValidation:
    """Invalid items should be skipped; valid siblings should still be returned."""

    def test_skips_item_with_invalid_type(self, pet, owner, scheduler):
        items = [
            planner_item("bath", "Bubble bath", days=1, hour=9),   # invalid type
            planner_item("feeding", "Lunch", days=1, hour=12),     # valid — different hour avoids plan conflict
        ]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Bath and feed", pet, owner, scheduler)

        assert err is None
        assert len(tasks) == 1
        assert tasks[0].type == "feeding"

    def test_skips_item_with_unparseable_due_date(self, pet, owner, scheduler):
        items = [
            {"type": "vet", "description": "Checkup", "due_date": "not-a-date", "recurrence": None},
            planner_item("medication", "Meds", days=1, hour=8),
        ]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Vet and meds", pet, owner, scheduler)

        assert err is None
        assert len(tasks) == 1
        assert tasks[0].type == "medication"

    def test_clamps_invalid_recurrence_to_none(self, pet, owner, scheduler):
        items = [planner_item("medication", "Meds", days=1, hour=9, recurrence="fortnightly")]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Medication plan", pet, owner, scheduler)

        assert err is None
        assert tasks[0].recurrence is None

    def test_all_items_invalid_returns_empty_list_and_error(self, pet, owner, scheduler):
        items = [{"type": "INVALID", "description": "x", "due_date": "bad", "recurrence": None}]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Whatever", pet, owner, scheduler)

        assert tasks == []
        assert err is not None


class TestPlannerConflictHandling:
    """Conflict rules: internal plan conflicts drop the second item;
    conflicts against the existing Scheduler are logged but the task is kept."""

    def test_internal_plan_conflict_drops_second_item(self, pet, owner, scheduler):
        """Two items at the exact same time: first is accepted, second dropped."""
        same_time = future_iso(days=1, hour=9)
        items = [
            {"type": "feeding",    "description": "Breakfast",    "due_date": same_time, "recurrence": None},
            {"type": "medication", "description": "Morning meds", "due_date": same_time, "recurrence": None},
        ]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Morning routine", pet, owner, scheduler)

        assert err is None
        assert len(tasks) == 1
        assert tasks[0].type == "feeding"

    def test_scheduler_conflict_task_still_included_in_proposal(self, pet, owner, scheduler):
        """A conflict with an already-scheduled task should NOT drop the proposed item —
        the user needs to see it so they can decide whether to confirm."""
        conflict_time = datetime.now() + timedelta(hours=2)
        existing = Task("e1", "feeding", "Existing feeding", pet.name, "o1", conflict_time)
        scheduler.add_task(existing, pet)

        items = [{
            "type": "medication",
            "description": "Meds at conflict time",
            "due_date": conflict_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "recurrence": None,
        }]
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(json.dumps(items))):
            tasks, err = run_planner_agent("Give meds", pet, owner, scheduler)

        assert err is None
        assert len(tasks) == 1   # still in the proposal for the user to review


class TestPlannerConnectionAndFormatErrors:
    """Network and format failures should return ([], error_string) and never raise."""

    def test_connection_refused_returns_empty_list_and_error(self, pet, owner, scheduler):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")):
            tasks, err = run_planner_agent("Any goal", pet, owner, scheduler)

        assert tasks == []
        assert "ollama" in err.lower()

    def test_json_object_not_array_returns_error(self, pet, owner, scheduler):
        """Model returns a single object instead of an array."""
        content = json.dumps({"type": "medication", "description": "Meds"})
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response(content)):
            tasks, err = run_planner_agent("Any goal", pet, owner, scheduler)

        assert tasks == []
        assert err is not None

    def test_plain_text_response_returns_error(self, pet, owner, scheduler):
        with patch("urllib.request.urlopen",
                   return_value=mock_ollama_response("Sorry, I can't help with that.")):
            tasks, err = run_planner_agent("Any goal", pet, owner, scheduler)

        assert tasks == []
        assert err is not None

    def test_unexpected_exception_returns_error_string(self, pet, owner, scheduler):
        with patch("urllib.request.urlopen",
                   side_effect=RuntimeError("Unexpected crash")):
            tasks, err = run_planner_agent("Any goal", pet, owner, scheduler)

        assert tasks == []
        assert err is not None
