"""
alfred.simulator.servo_sim
-----------------------------
A software stand-in for the physical servo motor.

`alfred.hardware.servo` is the public interface every other module
talks to; it tries to drive a real SG90 servo over GPIO PWM first and
only imports this module as a fallback when RPi.GPIO isn't importable
(e.g. running on a Mac during development, where there is no GPIO at
all). Rather than silently doing nothing, this module logs every angle
the real servo would have moved to, so gesture logic can be verified by
reading console output before the physical arm exists.
"""


class ServoSimulator:
    """Logs servo movement to the console instead of driving real GPIO PWM."""

    def __init__(self, gpio_pin: int, min_angle: int, max_angle: int) -> None:
        """
        Record the servo's configuration for use in log messages.

        Args:
            gpio_pin: The BCM GPIO pin the real servo would be wired to.
            min_angle: Minimum allowed angle in degrees.
            max_angle: Maximum allowed angle in degrees.
        """
        self._gpio_pin = gpio_pin
        self._min_angle = min_angle
        self._max_angle = max_angle
        self._current_angle: int | None = None
        print(f"[Alfred] Servo simulator active (no RPi.GPIO found) — would drive GPIO{gpio_pin}.")

    def move_to(self, angle: int) -> None:
        """
        Log a move to the given angle, clamped to the configured range.

        Args:
            angle: Target angle in degrees.
        """
        clamped = max(self._min_angle, min(self._max_angle, angle))
        self._current_angle = clamped
        print(f"[Alfred] (simulated) servo on GPIO{self._gpio_pin} -> {clamped} degrees")

    def react_to_level(self, angle: int) -> None:
        """
        Record a live, high-frequency move without logging it.

        Used for audio-reactive bobbing, which calls this many times a
        second — printing every call the way `move_to` does would flood
        the console. `_current_angle` still updates, so the last live
        position remains inspectable.

        Args:
            angle: Target angle in degrees.
        """
        self._current_angle = max(self._min_angle, min(self._max_angle, angle))

    def close(self) -> None:
        """No real hardware to release; logs that the simulator is shutting down."""
        print("[Alfred] Servo simulator stopped.")
