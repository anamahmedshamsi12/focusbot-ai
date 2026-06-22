"""
alfred.core.personality
--------------------------
Alfred's emotional layer: a single coordinator that translates
conversation events (wake word heard, listening, thinking, speaking,
focus session, error, ...) into physical reactions across both the
OLED eyes and the servo arm.

Nothing else in the codebase imports alfred.hardware directly — both
alfred.focusbot (desktop GUI) and alfred.robot (headless mode) only
ever talk to the single `Personality` instance built here, calling
semantic methods like `on_wake_word()` or `on_thinking()`. That keeps
the mood-to-hardware mapping in exactly one place, and means new
hardware (e.g. an LED ring, a speaker grille animation) only needs a
new line in this file, not changes scattered across the app.
"""

import tkinter as tk

from alfred.config import settings
from alfred.hardware.oled import OledEyes
from alfred.hardware.servo import ServoArm

# Canonical mood names. These strings are the contract between this
# module and the rendering code in alfred.hardware.oled /
# alfred.simulator.eyes_sim — both keep a renderer keyed on each of
# these names.
MOOD_IDLE: str = "idle"
MOOD_LISTENING: str = "listening"
MOOD_THINKING: str = "thinking"
MOOD_SPEAKING: str = "speaking"
MOOD_FOCUS: str = "focus"
MOOD_ALERT: str = "alert"
MOOD_HAPPY: str = "happy"
MOOD_ERROR: str = "error"
MOOD_ASLEEP: str = "asleep"


def _level_to_angle(level: float, max_angle: int, rest_angle: int) -> int:
    """
    Map a normalized audio level to a servo angle, swinging up from
    rest toward max as the level increases — the arm "bobs" higher the
    louder the sound.

    Args:
        level: Normalized volume, 0.0 (silence) to 1.0 (loud). Values
            outside this range are clamped rather than raising.
        max_angle: Servo's configured maximum angle — the swing's ceiling.
        rest_angle: Servo's configured neutral angle — the swing's floor.

    Returns:
        An angle in degrees between rest_angle and max_angle.
    """
    clamped_level = max(0.0, min(level, 1.0))
    swing = max_angle - rest_angle
    return rest_angle + int(clamped_level * swing)


class Personality:
    """
    Owns Alfred's eyes and arm, and exposes one method per conversation
    event for the rest of the app to call.

    Each hardware backend is optional and independently configurable
    (see alfred.config.settings) — if OLED_ENABLED or SERVO_ENABLED is
    False, the corresponding calls below simply become no-ops rather
    than raising, so the app runs fine with only one piece of hardware
    attached, or none at all.
    """

    def __init__(self, tk_master: tk.Misc | None = None) -> None:
        """
        Construct the eyes and arm backends according to current settings.

        Must be called from the main thread — OLED simulation may need
        to create a Tk window, which on macOS is fatal from any other
        thread (see alfred.simulator.eyes_sim's module docstring).

        Args:
            tk_master: An existing Tk widget to attach the eye
                simulator to, if one is already running (e.g.
                alfred.focusbot's root window). Pass None in headless
                mode (alfred.robot) — see `owns_mainloop` afterward to
                find out whether the simulator created its own root
                that now needs its mainloop pumped.
        """
        self._eyes: OledEyes | None = None
        self._arm: ServoArm | None = None
        # Mirrors OledEyes.owns_mainloop/tk_root — see alfred.robot for
        # how the headless entry point uses these.
        self.owns_mainloop: bool = False
        self.tk_root: tk.Tk | tk.Toplevel | None = None

        if settings.OLED_ENABLED:
            self._eyes = OledEyes(
                width=settings.OLED_WIDTH,
                height=settings.OLED_HEIGHT,
                i2c_address=settings.OLED_I2C_ADDRESS,
                simulate_if_missing=settings.OLED_SIMULATE_IF_MISSING,
                tk_master=tk_master,
            )
            self.owns_mainloop = self._eyes.owns_mainloop
            self.tk_root = self._eyes.tk_root

        if settings.SERVO_ENABLED:
            self._arm = ServoArm(
                gpio_pin=settings.SERVO_GPIO_PIN,
                min_angle=settings.SERVO_MIN_ANGLE,
                max_angle=settings.SERVO_MAX_ANGLE,
                rest_angle=settings.SERVO_REST_ANGLE,
                simulate_if_missing=settings.SERVO_SIMULATE_IF_MISSING,
            )

    def set_mood(self, mood: str) -> None:
        """
        Render a mood on the eyes only, with no accompanying arm gesture.

        Exposed directly (in addition to the semantic `on_*` methods
        below) for moods that don't map to a single conversation event,
        such as an idle-timeout transition to MOOD_ASLEEP.

        Args:
            mood: One of the MOOD_* constants defined above.
        """
        if self._eyes is not None:
            self._eyes.set_mood(mood)

    # ── Semantic Event Hooks ────────────────────────────────────────────
    # These are what alfred.focusbot and alfred.robot actually call —
    # named after what happened in the conversation, not after which
    # mood/gesture combination it maps to.

    def on_wake_word(self) -> None:
        """React to the wake word ("hey alfred") being detected."""
        self.set_mood(MOOD_ALERT)
        if self._arm is not None:
            self._arm.wave()

    def on_listening(self) -> None:
        """React to the microphone opening to capture a user utterance."""
        self.set_mood(MOOD_LISTENING)

    def on_thinking(self) -> None:
        """React to a Claude API call being in flight."""
        self.set_mood(MOOD_THINKING)

    def on_speaking(self) -> None:
        """React to Alfred's reply being spoken aloud."""
        self.set_mood(MOOD_SPEAKING)
        if self._arm is not None:
            self._arm.nod()

    def on_idle(self) -> None:
        """Return to a neutral resting state once a conversational turn is complete."""
        self.set_mood(MOOD_IDLE)
        if self._arm is not None:
            self._arm.rest()

    def on_focus_start(self) -> None:
        """React to a Pomodoro focus session starting."""
        self.set_mood(MOOD_FOCUS)

    def on_focus_end(self) -> None:
        """React to a Pomodoro focus session completing successfully."""
        self.set_mood(MOOD_HAPPY)
        if self._arm is not None:
            self._arm.point()

    def on_error(self) -> None:
        """React to an API or hardware error the user should notice."""
        self.set_mood(MOOD_ERROR)

    def on_audio_level(self, level: float) -> None:
        """
        React to a live, normalized (0.0-1.0) microphone level while
        Alfred is actively listening.

        Drives both the OLED waveform and the arm's real-time bobbing
        from the same underlying signal — see
        alfred.core.voice._listen_with_level, the one shared mic-reading
        loop both ultimately come from. The eyes only render this
        visibly while the current mood is "listening" (see
        alfred.hardware.oled/alfred.simulator.eyes_sim); the arm always
        reacts immediately regardless of mood, since the caller only
        wires this in while a listening session is actually open.

        Args:
            level: Normalized volume, 0.0 (silence) to 1.0 (loud).
        """
        if self._eyes is not None:
            self._eyes.set_level(level)
        if self._arm is not None:
            angle = _level_to_angle(level, settings.SERVO_MAX_ANGLE, settings.SERVO_REST_ANGLE)
            self._arm.react_to_level(angle)

    def close(self) -> None:
        """Release both hardware backends (or their simulators) on shutdown."""
        if self._eyes is not None:
            self._eyes.close()
        if self._arm is not None:
            self._arm.close()
