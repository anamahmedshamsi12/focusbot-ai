"""
alfred.core.focus
-------------------
ADHD focus and task management for Alfred: reminder scheduling, the
Pomodoro focus timer, intent detection, and natural-language time
parsing.

All timer functions run in daemon threads so they never block whatever
loop is driving Alfred (the Tkinter GUI's event loop in desktop mode,
or the plain `while True` loop in headless robot mode). The `app`
parameter accepted by `set_reminder` and `start_focus_timer` is the
live application instance — either `alfred.focusbot.FocusBotApp` or
`alfred.robot.Robot` — used to push messages and status updates back
to the right place safely. Both expose the same minimal interface:
`display_message`, `update_status`, `tts_engine`, and `focus_active`.
"""

import re
import threading
import time
from typing import Callable, TYPE_CHECKING

from alfred.core.voice import speak

# Avoid a circular import — focusbot.py and robot.py both import from
# this module, so the app type is only used for type checking and is
# stripped at runtime.
if TYPE_CHECKING:
    from alfred.focusbot import FocusBotApp


# =============================================================================
# Intent Detection
# =============================================================================

def detect_intent(text: str) -> str:
    """
    Classify a user's message into one of five intent categories using
    simple keyword matching.

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


# =============================================================================
# Reminder Parser
# =============================================================================

def parse_reminder(text: str) -> int | None:
    """
    Extract a duration in minutes from a natural language reminder string.

    Supports patterns like "in 30 minutes", "in 2 hours", "in 5 mins".
    Hour patterns are checked first, so a string containing both ("in 1
    hour and 30 minutes") matches on the hour value only.

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


# =============================================================================
# Reminder Scheduler
# =============================================================================

def set_reminder(
    minutes: int,
    reminder_text: str,
    app: "FocusBotApp",
    on_fire: Callable[[], None] | None = None,
) -> None:
    """
    Schedule a reminder to fire after a given number of minutes.

    Runs in a daemon thread so the caller returns immediately. When the
    timer expires, the reminder is displayed and spoken aloud.

    Args:
        minutes: How long to wait before firing the reminder.
        reminder_text: The original reminder text to display.
        app: The live application instance (GUI or headless robot) used
            for display/voice callbacks.
        on_fire: Optional callback invoked (with no arguments) the
            moment the reminder fires, after the message is displayed
            and before it's spoken. Used by callers to trigger a mood
            change (e.g. alfred.core.personality.on_wake_word) without
            this module needing to know hardware exists.
    """
    def _wait_and_remind() -> None:
        time.sleep(minutes * 60)
        app.display_message("Alfred", f"REMINDER: {reminder_text}")
        if on_fire is not None:
            on_fire()
        speak(f"Reminder! {reminder_text}. Just take the first tiny step.", app.tts_engine)

    threading.Thread(target=_wait_and_remind, daemon=True).start()


# =============================================================================
# Focus Timer
# =============================================================================

def start_focus_timer(
    minutes: int,
    app: "FocusBotApp",
    on_complete: Callable[[], None] | None = None,
) -> None:
    """
    Start a countdown focus session timer.

    Updates the application's status every second with the time
    remaining. When time is up, displays a completion message and
    speaks it aloud. The session can be cancelled early by setting
    `app.focus_active = False` from anywhere (e.g. a "stop" intent or a
    UI button) — `on_complete` is only invoked on a natural finish, not
    on cancellation.

    Args:
        minutes: Length of the focus session in minutes.
        app: The live application instance (GUI or headless robot) used
            for display/voice/status callbacks.
        on_complete: Optional callback invoked (with no arguments) when
            the session finishes naturally. Used by callers to trigger
            a mood change (e.g. alfred.core.personality.on_focus_end)
            without this module needing to know hardware exists.
    """
    def _countdown() -> None:
        app.focus_active = True
        total_seconds = minutes * 60

        for remaining in range(total_seconds, 0, -1):
            if not app.focus_active:
                app.update_status("Focus session cancelled.")
                return
            m, s = divmod(remaining, 60)
            app.update_status(f"Focus session: {m:02d}:{s:02d} remaining")
            time.sleep(1)

        app.focus_active = False
        app.display_message("Alfred", "Focus session complete! Great work. Take a 5-minute break.")
        if on_complete is not None:
            on_complete()
        speak("Focus session complete! Great work. Take a five minute break.", app.tts_engine)
        app.update_status("Ready")

    threading.Thread(target=_countdown, daemon=True).start()
