"""
reminders.py
------------
Reminder scheduling, focus timer, and intent detection for FocusBot.

All timer functions run in daemon threads so they never block the UI.
The `app` parameter in set_reminder and start_focus_timer is the live
FocusBotApp instance — used to push messages and status updates back
to the GUI thread safely.
"""

import re
import time
import threading
from typing import TYPE_CHECKING

from focusbot.voice import speak
from focusbot.config import FOCUS_MINUTES

# Avoid circular import — gui.py imports from here, so we only use the
# type for annotations (stripped at runtime).
if TYPE_CHECKING:
    from focusbot.gui import FocusBotApp


# ── Intent Detection ───────────────────────────────────────────────────────

def detect_intent(text: str) -> str:
    """
    Classify the user's message into one of five intent categories
    using simple keyword matching.

    Categories:
        'reminder' — user wants a timed reminder
        'focus'    — user wants to start a focus/Pomodoro session
        'routine'  — user is asking about a daily routine
        'stop'     — user wants to cancel an active timer
        'chat'     — everything else; passed directly to Claude

    Args:
        text: Raw user input string.

    Returns:
        One of: 'reminder', 'focus', 'routine', 'stop', 'chat'.
    """
    t = text.lower()

    if any(w in t for w in ["remind me", "reminder", "don't let me forget", "alert me"]):
        return "reminder"

    if any(w in t for w in ["focus", "pomodoro", "start timer", "work session", "focus mode"]):
        return "focus"

    if any(w in t for w in ["routine", "morning", "evening", "daily", "wake up", "bedtime"]):
        return "routine"

    if any(w in t for w in ["stop", "cancel", "end focus", "stop timer"]):
        return "stop"

    return "chat"


# ── Reminder Parser ────────────────────────────────────────────────────────

def parse_reminder(text: str) -> int | None:
    """
    Extract a duration in minutes from a natural language reminder string.

    Supports patterns like:
        "in 30 minutes", "in 2 hours", "in 5 mins"

    Args:
        text: The user's reminder request string.

    Returns:
        Duration in minutes as an int, or None if no time was found.
    """
    t = text.lower()

    hour_match = re.search(r"(\d+)\s*hour", t)
    if hour_match:
        return int(hour_match.group(1)) * 60

    min_match = re.search(r"(\d+)\s*(minute|min)", t)
    if min_match:
        return int(min_match.group(1))

    return None


# ── Reminder Scheduler ─────────────────────────────────────────────────────

def set_reminder(minutes: int, reminder_text: str, app: "FocusBotApp") -> None:
    """
    Schedule a reminder to fire after a given number of minutes.

    Runs in a daemon thread. When the timer expires, the reminder is
    displayed in the chat and spoken aloud.

    Args:
        minutes:       How long to wait before firing the reminder.
        reminder_text: The original reminder text to display.
        app:           Live FocusBotApp instance for UI callbacks.
    """
    def _wait_and_remind() -> None:
        time.sleep(minutes * 60)
        app.display_message("FocusBot", f"🔔 REMINDER: {reminder_text}")
        speak(f"Reminder! {reminder_text}. Just take the first tiny step.", app.tts_engine)

    threading.Thread(target=_wait_and_remind, daemon=True).start()


# ── Focus Timer ────────────────────────────────────────────────────────────

def start_focus_timer(minutes: int, app: "FocusBotApp") -> None:
    """
    Start a countdown focus session timer.

    Updates the status bar every second with the time remaining.
    When time is up, displays a completion message and speaks it aloud.
    The session can be cancelled early by setting app.focus_active = False.

    Args:
        minutes: Length of the focus session in minutes.
        app:     Live FocusBotApp instance for UI callbacks.
    """
    def _countdown() -> None:
        app.focus_active = True
        total_seconds = minutes * 60

        for remaining in range(total_seconds, 0, -1):
            if not app.focus_active:
                app.update_status("Focus session cancelled.")
                return
            m, s = divmod(remaining, 60)
            app.update_status(f"🎯 Focus session: {m:02d}:{s:02d} remaining")
            time.sleep(1)

        app.focus_active = False
        app.display_message("FocusBot", "✅ Focus session complete! Great work. Take a 5-minute break.")
        speak("Focus session complete! Great work. Take a five minute break.", app.tts_engine)
        app.update_status("Ready")

    threading.Thread(target=_countdown, daemon=True).start()
