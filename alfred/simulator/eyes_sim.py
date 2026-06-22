"""
alfred.simulator.eyes_sim
---------------------------
A software stand-in for the physical OLED eye display.

`alfred.hardware.oled` is the public interface every other module
talks to; it tries to drive a real SSD1306 OLED over I2C first and
only imports this module as a fallback when that hardware isn't
present (no I2C bus, board not wired up yet, or simply running on a
development machine like a Mac). The simulator opens a small Tkinter
window with two animated "eyes" drawn on a canvas, scaled up from the
OLED's real 128x64 pixel resolution so it's comfortably visible on a
laptop screen.

This lets mood and animation logic be written, run, and watched before
the physical display exists, and continues to be useful afterward for
quick desktop testing without the Pi attached.

Main-thread requirement: Tkinter windows must be created and driven
from the process's main thread — on macOS this isn't just a style
guideline, AppKit raises a fatal NSInternalInconsistencyException if
an NSWindow is instantiated from any other thread. So this class never
spawns its own thread. Instead:

- If a `master` widget is given (alfred.focusbot already has a Tk root
  running its own mainloop), the eyes render in a `Toplevel` attached
  to it, riding that existing event loop for free.
- If no `master` is given (headless alfred.robot has no GUI of its
  own), this class creates and owns a bare `Tk()` root. The caller is
  then responsible for pumping it — check `owns_mainloop` and call
  `.root.mainloop()` from the main thread if it's True. `alfred.robot`
  does exactly this in place of its plain `while True: sleep(1)` loop
  when there's no physical OLED to fall back from.

Either way, `set_mood()` remains safe to call from background threads
(the wake word / voice / Claude threads) via `Tk.after(0, ...)`, which
is the standard thread-safe pattern for handing work back to a Tk
event loop from elsewhere.

While the mood is "listening", the eyes are replaced by a single
full-width waveform trace fed by `set_level()` — gentle and sine-like
while quiet, switching to a sharp EKG-style spike trace once real
voice is detected. Both `set_level` here and the servo's live bobbing
in alfred.hardware.servo are driven by the same underlying microphone
samples (see alfred.core.voice._listen_with_level and
alfred.core.personality.on_audio_level) — there's exactly one place
audio is actually read from the mic.
"""

import math
import tkinter as tk
from collections import deque

# How many real OLED pixels each simulator pixel represents on screen.
SCALE: int = 4

# Background/foreground match a monochrome OLED: black background,
# white "lit" pixels.
BG_COLOR: str = "#000000"
EYE_COLOR: str = "#FFFFFF"
ERROR_COLOR: str = "#FF4444"

# Redraw interval in milliseconds — fast enough for smooth blinking and
# look-around animation without burning CPU.
TICK_MS: int = 80

# How many recent level samples the listening-state waveform plots —
# higher is a denser trace, at the cost of a longer visible history.
LEVEL_HISTORY_LEN: int = 64
# Below this normalized level, the waveform renders as a calm idle
# sine wave instead of the voice-reactive EKG-style trace.
VOICE_LEVEL_THRESHOLD: float = 0.15


class EyeSimulator:
    """
    A Tkinter-based visual stand-in for the physical OLED eyes.

    Renders into a Toplevel of a provided master widget, or into its
    own owned Tk root if no master is given — see the module docstring
    for which case applies to the GUI vs. headless robot run modes.
    """

    def __init__(self, oled_width: int, oled_height: int, master: tk.Misc | None = None) -> None:
        """
        Build the simulator window immediately on the calling thread.

        Must be called from the main thread — see the module docstring.

        Args:
            oled_width: Width of the real OLED in pixels (e.g. 128),
                used to size the simulator window to scale.
            oled_height: Height of the real OLED in pixels (e.g. 64).
            master: An existing Tk widget whose event loop is already
                (or will be) running, e.g. alfred.focusbot's root
                window. When given, the eyes attach to it as a
                Toplevel. When omitted, this instance creates and owns
                a standalone Tk() root instead — see `owns_mainloop`.
        """
        self._oled_width = oled_width
        self._oled_height = oled_height
        self._mood: str = "idle"
        # Monotonically increasing tick counter driving all animation
        # (blink timing, look-around oscillation, speaking pulse, etc).
        self._phase: int = 0
        # Recent normalized (0.0-1.0) mic levels, oldest first — fed by
        # set_level(), plotted by the listening-state waveform.
        self._level_history: deque[float] = deque(maxlen=LEVEL_HISTORY_LEN)

        # True only when this instance had to create its own Tk root —
        # the caller is then responsible for calling root.mainloop().
        self.owns_mainloop: bool = master is None
        self.root: tk.Tk | tk.Toplevel = tk.Tk() if master is None else tk.Toplevel(master)

        self.root.title("Alfred — Eyes (simulated OLED)")
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(False, False)

        canvas_w = oled_width * SCALE
        canvas_h = oled_height * SCALE
        self._canvas = tk.Canvas(
            self.root, width=canvas_w, height=canvas_h,
            bg=BG_COLOR, highlightthickness=0,
        )
        self._canvas.pack()

        self._tick()

    def set_mood(self, mood: str) -> None:
        """
        Change the displayed mood. Safe to call from any thread.

        Args:
            mood: One of the mood names defined in
                alfred.core.personality (e.g. "idle", "listening",
                "thinking", "speaking", "focus", "alert", "happy",
                "error", "asleep"). Unrecognized moods render as idle.
        """
        self._mood = mood
        # root.after(0, ...) is thread-safe even when set_mood itself
        # is called from a non-Tk thread (the brain/voice threads),
        # as long as the Tk event loop this root belongs to is running.
        self.root.after(0, self._redraw)

    def set_level(self, level: float) -> None:
        """
        Record a live, normalized microphone level. Safe to call from
        any thread — see `alfred.core.personality.on_audio_level`,
        which is the only caller in practice.

        Only visibly affects anything while the mood is "listening";
        recorded unconditionally regardless so the waveform's history
        isn't empty the moment listening starts.

        Args:
            level: Normalized volume, 0.0 (silence) to 1.0 (loud).
        """
        self.root.after(0, lambda: self._record_level(level))

    def close(self) -> None:
        """Close the simulator window and stop its animation loop."""
        self.root.after(0, self.root.destroy)

    # ── Internal: animation ─────────────────────────────────────────────

    def _tick(self) -> None:
        """Advance the animation phase and redraw, then reschedule itself."""
        self._phase += 1
        self._redraw()
        self.root.after(TICK_MS, self._tick)

    def _record_level(self, level: float) -> None:
        """Append a level sample and, if it's currently visible, redraw immediately."""
        self._level_history.append(level)
        if self._mood == "listening":
            self._redraw()

    def _redraw(self) -> None:
        """Clear the canvas and draw the current mood — a waveform for "listening", eye shapes otherwise."""
        self._canvas.delete("all")

        if self._mood == "listening":
            canvas_w = self._oled_width * SCALE
            canvas_h = self._oled_height * SCALE
            _render_waveform(self._canvas, canvas_w, canvas_h, self._level_history, self._phase)
            return

        cx = self._oled_width * SCALE // 2
        cy = self._oled_height * SCALE // 2
        eye_gap = 18 * SCALE // 4

        left_cx = cx - eye_gap
        right_cx = cx + eye_gap

        draw_fn = _MOOD_RENDERERS.get(self._mood, _render_idle)
        draw_fn(self._canvas, left_cx, cy, right_cx, cy, self._phase)


# =============================================================================
# Mood Renderers
#
# Each renderer draws both eyes for one mood, given their center points
# and the current animation phase (a monotonically increasing tick
# counter used to drive blinking, look-around, and pulsing effects).
# =============================================================================

def _eye_size(mood_scale: float) -> tuple[int, int]:
    """
    Compute (half_width, half_height) for a single eye at a given mood scale.

    Args:
        mood_scale: Multiplier applied to the base eye size — 1.0 is
            normal, >1 widens the eye (alert), <1 narrows it (focus).

    Returns:
        Tuple of (half_width, half_height) in canvas pixels.
    """
    base_half_w = 10 * SCALE
    base_half_h = 14 * SCALE
    return int(base_half_w * mood_scale), int(base_half_h * mood_scale)


def _draw_eye_pair(
    canvas: tk.Canvas,
    lx: int, ly: int, rx: int, ry: int,
    half_w: int, half_h: int,
    color: str = EYE_COLOR,
) -> None:
    """Draw two identical rounded-rectangle eyes at the given centers."""
    for cx, cy in ((lx, ly), (rx, ry)):
        canvas.create_rectangle(
            cx - half_w, cy - half_h, cx + half_w, cy + half_h,
            fill=color, outline="", width=0,
        )


def _render_idle(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Relaxed open eyes with a slow periodic blink."""
    # Blink for 2 ticks out of every ~50 (roughly every 4 seconds at 80ms/tick).
    if phase % 50 < 2:
        _draw_eye_pair(canvas, lx, ly, rx, ry, 10 * SCALE, 2)
    else:
        half_w, half_h = _eye_size(1.0)
        _draw_eye_pair(canvas, lx, ly, rx, ry, half_w, half_h)


def _render_waveform(canvas: tk.Canvas, width: int, height: int, history: "deque[float]", phase: int) -> None:
    """
    Draw Alfred's "listening" state as a single full-width trace: a
    slow, gentle sine wave while quiet, switching to a sharp EKG-style
    spike trace once real voice is detected.

    Args:
        canvas: Target canvas, sized (width, height).
        width: Canvas width in pixels.
        height: Canvas height in pixels.
        history: Recent normalized (0.0-1.0) level samples, oldest
            first — see EyeSimulator.set_level.
        phase: Animation tick counter, used to animate the idle sine
            wave even when there's no audio history yet.
    """
    cy = height // 2
    recent_peak = max(history) if history else 0.0

    if recent_peak < VOICE_LEVEL_THRESHOLD or len(history) < 2:
        # Idle: a calm, purely decorative sine wave — nobody's talking.
        n = 48
        amplitude = height * 0.06
        points = [
            (i * width / (n - 1), cy + amplitude * math.sin((i / n) * 4 * math.pi + phase * 0.15))
            for i in range(n)
        ]
    else:
        # Voice detected: plot the real level history, amplitude scaled
        # by how loud each sample was — taller spikes for louder speech.
        amplitude = height * 0.45
        n = len(history)
        points = [
            (i * width / max(n - 1, 1), cy - lvl * amplitude)
            for i, lvl in enumerate(history)
        ]

    # create_line accepts a full flattened coordinate list and draws it
    # as one connected polyline — no need to loop per segment.
    canvas.create_line(*(coord for point in points for coord in point), fill=EYE_COLOR, width=2)


def _render_thinking(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Eyes drift side to side, as if looking up and thinking."""
    half_w, half_h = _eye_size(0.9)
    # Oscillate horizontally over an 8-tick cycle (~640ms) for a visible
    # "thinking" look-around without being distracting.
    offset = (phase % 8) - 4
    _draw_eye_pair(canvas, lx + offset, ly - 4 * SCALE, rx + offset, ry - 4 * SCALE, half_w, half_h)


def _render_speaking(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Eyes pulse in height, mimicking a simple talking rhythm."""
    pulse = 1.0 + 0.15 * ((phase % 6) / 6)
    half_w, half_h = _eye_size(pulse)
    _draw_eye_pair(canvas, lx, ly, rx, ry, half_w, half_h)


def _render_focus(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Narrowed, concentrating eyes — a focus/Pomodoro session is active."""
    half_w, half_h = _eye_size(0.8)
    half_h = max(half_h // 2, 3)
    _draw_eye_pair(canvas, lx, ly, rx, ry, half_w, half_h)


def _render_alert(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Wide, fully open eyes — the wake word was just heard."""
    half_w, half_h = _eye_size(1.3)
    _draw_eye_pair(canvas, lx, ly, rx, ry, half_w, half_h)


def _render_happy(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Upward-curved 'smiling' eyes, drawn as arcs rather than rectangles."""
    half_w, half_h = _eye_size(1.0)
    for cx, cy in ((lx, ly), (rx, ry)):
        canvas.create_arc(
            cx - half_w, cy - half_h, cx + half_w, cy + half_h,
            start=20, extent=140, style="chord", fill=EYE_COLOR, outline="",
        )


def _render_error(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """X-shaped eyes in red, signalling something went wrong (e.g. API error)."""
    half = 9 * SCALE
    for cx, cy in ((lx, ly), (rx, ry)):
        canvas.create_line(cx - half, cy - half, cx + half, cy + half, fill=ERROR_COLOR, width=4)
        canvas.create_line(cx - half, cy + half, cx + half, cy - half, fill=ERROR_COLOR, width=4)


def _render_asleep(canvas: tk.Canvas, lx: int, ly: int, rx: int, ry: int, phase: int) -> None:
    """Thin horizontal lines — Alfred is idle for a long time / powered down."""
    half_w = 10 * SCALE
    for cx, cy in ((lx, ly), (rx, ry)):
        canvas.create_rectangle(cx - half_w, cy - 2, cx + half_w, cy + 2, fill=EYE_COLOR, outline="")


_MOOD_RENDERERS = {
    "idle": _render_idle,
    # "listening" is handled specially in _redraw (full-width waveform,
    # not eye shapes) — intentionally absent from this dict.
    "thinking": _render_thinking,
    "speaking": _render_speaking,
    "focus": _render_focus,
    "alert": _render_alert,
    "happy": _render_happy,
    "error": _render_error,
    "asleep": _render_asleep,
}
