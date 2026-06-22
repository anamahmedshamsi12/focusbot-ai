"""
alfred.hardware.oled
----------------------
Real driver for Alfred's physical eyes: a 128x64 SSD1306 OLED display
wired over I2C (see docs/hardware_setup.md for the pinout).

This module is the only thing the rest of the codebase talks to for
eye rendering — callers never need to know whether they're driving
real glass or a simulator window. `OledEyes.__init__` tries to import
the Adafruit CircuitPython SSD1306 driver and open the I2C bus; if
either step fails (most commonly because we're running on a Mac during
development, where there is no I2C bus at all), it transparently falls
back to `alfred.simulator.eyes_sim.EyeSimulator` so mood/animation
logic still has somewhere to render.
"""

import math
import tkinter as tk
from collections import deque
from typing import Callable

from alfred.simulator.eyes_sim import EyeSimulator

# Mirrors alfred.simulator.eyes_sim's matching constants — see that
# module's docstring for the full rationale.
LEVEL_HISTORY_LEN: int = 64
VOICE_LEVEL_THRESHOLD: float = 0.15

try:
    import adafruit_ssd1306
    import board
    import busio
    from PIL import Image, ImageDraw
    _HARDWARE_IMPORTS_OK = True
except (ImportError, NotImplementedError):
    # ImportError: the adafruit/board/busio packages aren't installed.
    # NotImplementedError: `board` raises this on non-Pi platforms when
    # it can't detect a matching pin layout.
    _HARDWARE_IMPORTS_OK = False


class OledEyes:
    """
    Drives Alfred's eyes — on real SSD1306 hardware when available,
    falling back to a Tkinter simulator window otherwise.
    """

    def __init__(
        self,
        width: int,
        height: int,
        i2c_address: int,
        simulate_if_missing: bool,
        tk_master: tk.Misc | None = None,
    ) -> None:
        """
        Set up the eye display, preferring real hardware.

        Must be called from the main thread if simulation may be used —
        see alfred.simulator.eyes_sim's module docstring for why.

        Args:
            width: OLED display width in pixels (e.g. 128).
            height: OLED display height in pixels (e.g. 64).
            i2c_address: I2C address of the SSD1306 (e.g. 0x3C).
            simulate_if_missing: If True and real hardware can't be
                reached, open the Tkinter simulator instead of going
                silent.
            tk_master: An existing Tk widget to attach the simulator
                window to as a Toplevel (e.g. alfred.focusbot's root).
                Pass None when there's no existing Tk app (headless
                alfred.robot) — the simulator will then create and own
                its own Tk root; check `owns_mainloop` afterward.
        """
        self._width = width
        self._height = height
        self._display = None
        self._simulator: EyeSimulator | None = None
        self.is_simulated: bool = False
        # Hardware path only — the simulator tracks its own mood/level
        # state. There's no animation timer driving the real display,
        # so the current mood and a phase counter are tracked here so
        # set_level() (called frequently while listening) knows whether
        # to redraw, and the idle sine wave still animates a bit.
        self._current_mood: str = "idle"
        self._level_history: deque[float] = deque(maxlen=LEVEL_HISTORY_LEN)
        self._waveform_phase: int = 0
        # Only meaningful when is_simulated is True and no tk_master was
        # given — see EyeSimulator's docstring for the main-loop contract.
        self.owns_mainloop: bool = False
        self.tk_root: tk.Tk | tk.Toplevel | None = None

        if _HARDWARE_IMPORTS_OK:
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                self._display = adafruit_ssd1306.SSD1306_I2C(width, height, i2c, addr=i2c_address)
                self._image = Image.new("1", (width, height))
                self._draw = ImageDraw.Draw(self._image)
                return
            except Exception as exc:
                print(f"[Alfred] OLED hardware init failed: {exc}")

        # Either the imports failed outright, or the I2C probe above did
        # (e.g. nothing wired up yet). Fall back to the simulator.
        if simulate_if_missing:
            self._simulator = EyeSimulator(width, height, master=tk_master)
            self.is_simulated = True
            self.owns_mainloop = self._simulator.owns_mainloop
            self.tk_root = self._simulator.root
        else:
            print("[Alfred] OLED disabled: no hardware found and simulation is off.")

    def set_mood(self, mood: str) -> None:
        """
        Render the given mood on whichever backend is active.

        Args:
            mood: One of the mood names defined in
                alfred.core.personality. Unrecognized moods render as
                a neutral idle face.
        """
        if self._simulator is not None:
            self._simulator.set_mood(mood)
        elif self._display is not None:
            self._render_hardware(mood)
        # else: OLED disabled entirely — nothing to do.

    def set_level(self, level: float) -> None:
        """
        Record a live, normalized microphone level for the listening
        waveform. See `alfred.core.personality.on_audio_level`, which
        is the only caller in practice.

        Args:
            level: Normalized volume, 0.0 (silence) to 1.0 (loud).
        """
        if self._simulator is not None:
            self._simulator.set_level(level)
            return
        if self._display is None:
            return
        self._level_history.append(level)
        if self._current_mood == "listening":
            self._render_hardware_waveform()

    def close(self) -> None:
        """Release whichever backend is active (simulator window or display)."""
        if self._simulator is not None:
            self._simulator.close()
        elif self._display is not None:
            self._draw.rectangle((0, 0, self._width, self._height), fill=0)
            self._display.image(self._image)
            self._display.show()

    # ── Internal: real hardware rendering ───────────────────────────────

    def _render_hardware(self, mood: str) -> None:
        """
        Draw the given mood to the real OLED's frame buffer and push it.

        Mirrors the simulator's mood set (idle/thinking/speaking/focus/
        alert/happy/error/asleep) using PIL drawing primitives instead
        of a Tkinter canvas. "listening" is handled separately by
        `_render_hardware_waveform`, the same way the simulator special-
        cases it in `_redraw`.

        Args:
            mood: The mood to render.
        """
        self._current_mood = mood
        if mood == "listening":
            self._render_hardware_waveform()
            return

        self._draw.rectangle((0, 0, self._width, self._height), fill=0)

        cx, cy = self._width // 2, self._height // 2
        gap = 18
        left, right = cx - gap, cx + gap

        renderer = _HARDWARE_RENDERERS.get(mood, _hw_render_idle)
        renderer(self._draw, left, cy, right, cy)

        self._display.image(self._image)
        self._display.show()

    def _render_hardware_waveform(self) -> None:
        """Draw the listening-state waveform to the real OLED's frame buffer and push it."""
        self._waveform_phase += 1
        self._draw.rectangle((0, 0, self._width, self._height), fill=0)
        _hw_render_waveform(self._draw, self._width, self._height, self._level_history, self._waveform_phase)
        self._display.image(self._image)
        self._display.show()


# =============================================================================
# Hardware Mood Renderers (PIL ImageDraw, 1-bit frame buffer)
# =============================================================================

def _hw_eye_size(mood_scale: float) -> tuple[int, int]:
    """Compute (half_width, half_height) for one eye at the given scale."""
    return int(10 * mood_scale), int(14 * mood_scale)


def _hw_draw_pair(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int, half_w: int, half_h: int) -> None:
    """Draw two identical filled rectangles (eyes) at the given centers."""
    for cx, cy in ((lx, ly), (rx, ry)):
        draw.rectangle((cx - half_w, cy - half_h, cx + half_w, cy + half_h), fill=1)


def _hw_render_idle(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Relaxed open eyes (hardware has no blink timer — see note below)."""
    # The simulator animates blinking using a tick counter; the
    # hardware path renders a single static frame per mood change since
    # personality.py calls set_mood on discrete events, not on a timer.
    half_w, half_h = _hw_eye_size(1.0)
    _hw_draw_pair(draw, lx, ly, rx, ry, half_w, half_h)


def _hw_render_waveform(draw: "ImageDraw.ImageDraw", width: int, height: int, history: "deque[float]", phase: int) -> None:
    """
    Draw the listening-state waveform: a gentle idle sine wave while
    quiet, switching to a sharp EKG-style spike trace once real voice
    is detected. Mirrors eyes_sim._render_waveform using PIL instead of
    a Tkinter canvas.

    Args:
        draw: Target ImageDraw bound to the OLED's 1-bit frame buffer.
        width: Frame buffer width in pixels.
        height: Frame buffer height in pixels.
        history: Recent normalized (0.0-1.0) level samples, oldest first.
        phase: Animation counter, incremented once per render call.
    """
    cy = height // 2
    recent_peak = max(history) if history else 0.0

    if recent_peak < VOICE_LEVEL_THRESHOLD or len(history) < 2:
        n = 32
        amplitude = height * 0.1
        points = [
            (i * width / (n - 1), cy + amplitude * math.sin((i / n) * 4 * math.pi + phase * 0.2))
            for i in range(n)
        ]
    else:
        amplitude = height * 0.4
        n = len(history)
        points = [
            (i * width / max(n - 1, 1), cy - lvl * amplitude)
            for i, lvl in enumerate(history)
        ]

    draw.line(points, fill=1, width=1)


def _hw_render_thinking(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Eyes shifted upward, as if looking up while thinking."""
    half_w, half_h = _hw_eye_size(0.9)
    _hw_draw_pair(draw, lx, ly - 4, rx, ry - 4, half_w, half_h)


def _hw_render_speaking(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Slightly enlarged eyes for the talking frame."""
    half_w, half_h = _hw_eye_size(1.1)
    _hw_draw_pair(draw, lx, ly, rx, ry, half_w, half_h)


def _hw_render_focus(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Narrowed, concentrating eyes."""
    half_w, half_h = _hw_eye_size(0.8)
    half_h = max(half_h // 2, 3)
    _hw_draw_pair(draw, lx, ly, rx, ry, half_w, half_h)


def _hw_render_alert(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Wide open eyes — wake word just heard."""
    half_w, half_h = _hw_eye_size(1.3)
    _hw_draw_pair(draw, lx, ly, rx, ry, half_w, half_h)


def _hw_render_happy(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Upward-curved 'smiling' eyes, drawn as arcs."""
    half_w, half_h = _hw_eye_size(1.0)
    for cx, cy in ((lx, ly), (rx, ry)):
        draw.arc((cx - half_w, cy - half_h, cx + half_w, cy + half_h), start=200, end=340, fill=1, width=3)


def _hw_render_error(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """X-shaped eyes signalling an error (monochrome display has no red, so shape carries the meaning)."""
    half = 9
    for cx, cy in ((lx, ly), (rx, ry)):
        draw.line((cx - half, cy - half, cx + half, cy + half), fill=1, width=2)
        draw.line((cx - half, cy + half, cx + half, cy - half), fill=1, width=2)


def _hw_render_asleep(draw: "ImageDraw.ImageDraw", lx: int, ly: int, rx: int, ry: int) -> None:
    """Thin horizontal lines — idle for a long time."""
    half_w = 10
    for cx, cy in ((lx, ly), (rx, ry)):
        draw.rectangle((cx - half_w, cy - 2, cx + half_w, cy + 2), fill=1)


_HARDWARE_RENDERERS: dict[str, Callable] = {
    "idle": _hw_render_idle,
    # "listening" is handled specially in _render_hardware (full-width
    # waveform via _render_hardware_waveform) — intentionally absent.
    "thinking": _hw_render_thinking,
    "speaking": _hw_render_speaking,
    "focus": _hw_render_focus,
    "alert": _hw_render_alert,
    "happy": _hw_render_happy,
    "error": _hw_render_error,
    "asleep": _hw_render_asleep,
}
