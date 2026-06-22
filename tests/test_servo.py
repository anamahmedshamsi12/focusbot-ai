"""
test_servo.py
---------------
Unit tests for alfred.hardware.servo.

These run safely in CI (no GPIO, no display) because:
  - _angle_to_duty_cycle is a pure function.
  - ServoArm with simulate_if_missing=True falls back to
    alfred.simulator.servo_sim.ServoSimulator, which only prints to
    the console — unlike the OLED simulator, it never opens a window.
"""

from alfred.hardware.servo import ServoArm, _angle_to_duty_cycle


class TestAngleToDutyCycle:
    """Tests for the angle -> PWM duty cycle conversion formula."""

    def test_zero_degrees(self):
        assert _angle_to_duty_cycle(0) == 2.0

    def test_max_degrees(self):
        assert _angle_to_duty_cycle(180) == 12.0

    def test_midpoint(self):
        assert _angle_to_duty_cycle(90) == 7.0


class TestServoArmClamping:
    """Tests that ServoArm clamps requested angles to its configured range."""

    def _make_arm(self) -> ServoArm:
        return ServoArm(gpio_pin=18, min_angle=0, max_angle=180, rest_angle=90, simulate_if_missing=True)

    def test_runs_in_simulated_mode_without_gpio(self):
        arm = self._make_arm()
        assert arm.is_simulated is True

    def test_move_to_clamps_above_max(self, capsys):
        arm = self._make_arm()
        arm.move_to(999)
        captured = capsys.readouterr()
        assert "180 degrees" in captured.out

    def test_move_to_clamps_below_min(self, capsys):
        arm = self._make_arm()
        arm.move_to(-50)
        captured = capsys.readouterr()
        assert "0 degrees" in captured.out

    def test_move_to_within_range_is_unchanged(self, capsys):
        arm = self._make_arm()
        arm.move_to(45)
        captured = capsys.readouterr()
        assert "45 degrees" in captured.out


class TestServoArmReactToLevel:
    """react_to_level clamps like move_to, but is silent (no console spam)."""

    def _make_arm(self) -> ServoArm:
        return ServoArm(gpio_pin=18, min_angle=0, max_angle=180, rest_angle=90, simulate_if_missing=True)

    def test_clamps_above_max(self):
        arm = self._make_arm()
        arm.react_to_level(999)
        assert arm._simulator._current_angle == 180

    def test_clamps_below_min(self):
        arm = self._make_arm()
        arm.react_to_level(-50)
        assert arm._simulator._current_angle == 0

    def test_does_not_print(self, capsys):
        arm = self._make_arm()
        capsys.readouterr()  # discard the simulator's init message
        arm.react_to_level(120)
        captured = capsys.readouterr()
        assert captured.out == ""
