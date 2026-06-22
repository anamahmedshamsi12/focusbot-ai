"""
test_personality.py
---------------------
Unit tests for alfred.core.personality.

Every test disables both OLED_ENABLED and SERVO_ENABLED via
monkeypatch before constructing Personality. This is required for CI
safety: with hardware enabled but absent, OledEyes would fall back to
the Tkinter eye simulator, which needs a display — something headless
CI runners don't have. Disabling both confirms the no-hardware-at-all
path works cleanly, which is itself a real behavior worth covering
(e.g. running with a display-less Pi while the OLED is still on order).
"""

import pytest

from alfred.config import settings
from alfred.core.personality import Personality, _level_to_angle


@pytest.fixture
def disabled_hardware(monkeypatch):
    """Force both hardware backends off so Personality() builds with no eyes/arm."""
    monkeypatch.setattr(settings, "OLED_ENABLED", False)
    monkeypatch.setattr(settings, "SERVO_ENABLED", False)


class TestPersonalityWithoutHardware:
    """Every event hook should no-op cleanly when no hardware is configured."""

    def test_construction_does_not_raise(self, disabled_hardware):
        Personality()

    def test_on_wake_word_does_not_raise(self, disabled_hardware):
        Personality().on_wake_word()

    def test_on_listening_does_not_raise(self, disabled_hardware):
        Personality().on_listening()

    def test_on_thinking_does_not_raise(self, disabled_hardware):
        Personality().on_thinking()

    def test_on_speaking_does_not_raise(self, disabled_hardware):
        Personality().on_speaking()

    def test_on_idle_does_not_raise(self, disabled_hardware):
        Personality().on_idle()

    def test_on_focus_start_does_not_raise(self, disabled_hardware):
        Personality().on_focus_start()

    def test_on_focus_end_does_not_raise(self, disabled_hardware):
        Personality().on_focus_end()

    def test_on_error_does_not_raise(self, disabled_hardware):
        Personality().on_error()

    def test_close_does_not_raise(self, disabled_hardware):
        Personality().close()

    def test_on_audio_level_does_not_raise(self, disabled_hardware):
        Personality().on_audio_level(0.7)


class TestLevelToAngle:
    """_level_to_angle maps a 0.0-1.0 level onto the rest->max swing."""

    def test_silence_maps_to_rest(self):
        assert _level_to_angle(0.0, max_angle=180, rest_angle=90) == 90

    def test_full_volume_maps_to_max(self):
        assert _level_to_angle(1.0, max_angle=180, rest_angle=90) == 180

    def test_half_volume_maps_to_midpoint(self):
        assert _level_to_angle(0.5, max_angle=180, rest_angle=90) == 135

    def test_clamps_above_one(self):
        assert _level_to_angle(5.0, max_angle=180, rest_angle=90) == 180

    def test_clamps_below_zero(self):
        assert _level_to_angle(-2.0, max_angle=180, rest_angle=90) == 90
