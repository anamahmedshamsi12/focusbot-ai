"""
test_reminders.py
-----------------
Unit tests for focusbot.reminders.

Tests cover the two pure functions that have no external dependencies:
  - parse_reminder : extracts minutes from natural language strings
  - detect_intent  : classifies user messages into intent categories
"""

import pytest
from focusbot.reminders import detect_intent, parse_reminder


# ── parse_reminder ─────────────────────────────────────────────────────────

class TestParseReminder:
    """Tests for parse_reminder() — natural language time extraction."""

    def test_minutes_full_word(self):
        assert parse_reminder("remind me in 30 minutes") == 30

    def test_minutes_abbreviation(self):
        assert parse_reminder("remind me in 10 mins") == 10

    def test_hours_converted_to_minutes(self):
        assert parse_reminder("remind me in 2 hours") == 120

    def test_single_hour(self):
        assert parse_reminder("remind me in 1 hour") == 60

    def test_case_insensitive(self):
        assert parse_reminder("Remind Me In 45 Minutes") == 45

    def test_no_time_returns_none(self):
        assert parse_reminder("remind me to do my homework") is None

    def test_empty_string_returns_none(self):
        assert parse_reminder("") is None

    def test_hours_takes_priority_over_minutes(self):
        # "1 hour" should be matched before "30 minutes" even if both present
        result = parse_reminder("in 1 hour and 30 minutes")
        assert result == 60  # hours matched first


# ── detect_intent ──────────────────────────────────────────────────────────

class TestDetectIntent:
    """Tests for detect_intent() — message classification."""

    def test_reminder_keyword(self):
        assert detect_intent("remind me to take my medication") == "reminder"

    def test_dont_let_me_forget(self):
        assert detect_intent("don't let me forget to call mom") == "reminder"

    def test_focus_keyword(self):
        assert detect_intent("start a focus session") == "focus"

    def test_pomodoro_keyword(self):
        assert detect_intent("let's do a pomodoro") == "focus"

    def test_routine_morning(self):
        assert detect_intent("help with my morning routine") == "routine"

    def test_routine_evening(self):
        assert detect_intent("what's my evening routine?") == "routine"

    def test_stop_timer(self):
        assert detect_intent("stop the timer") == "stop"

    def test_cancel(self):
        assert detect_intent("cancel the session") == "stop"

    def test_general_chat_falls_through(self):
        assert detect_intent("what is the capital of France?") == "chat"

    def test_task_breakdown_falls_through_to_chat(self):
        # Task breakdowns don't need a special intent — Claude handles them
        assert detect_intent("I need to clean my room but don't know where to start") == "chat"

    def test_empty_string(self):
        assert detect_intent("") == "chat"

    def test_case_insensitive(self):
        assert detect_intent("REMIND ME to buy groceries") == "reminder"
