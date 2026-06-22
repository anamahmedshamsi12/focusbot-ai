"""
alfred.hardware.servo
------------------------
Real driver for Alfred's arm: a single SG90 hobby servo on a GPIO PWM
pin (see docs/hardware_setup.md for the wiring table).

Like alfred.hardware.oled, this module is the only thing the rest of
the codebase talks to for arm movement. `ServoArm.__init__` tries to
import RPi.GPIO and claim the configured pin; if that fails (most
commonly because we're running on a Mac during development, which has
no GPIO at all), it transparently falls back to
`alfred.simulator.servo_sim.ServoSimulator`, which logs the angles the
real servo would have moved to instead.

Gesture methods (`wave`, `nod`, `point`, `rest`) run their movement
sequences in a background thread so callers — typically
alfred.core.personality reacting to a conversation event — never block
waiting for the arm to physically finish moving.
"""

import threading
import time

from alfred.simulator.servo_sim import ServoSimulator

try:
    import RPi.GPIO as GPIO
    _HARDWARE_IMPORTS_OK = True
except ImportError:
    _HARDWARE_IMPORTS_OK = False

# Standard PWM frequency for analog hobby servos like the SG90.
PWM_FREQUENCY_HZ: int = 50

# Seconds to hold a position before either moving again or cutting the
# PWM signal — enough time for a small hobby servo to physically arrive.
SETTLE_SECONDS: float = 0.3


def _angle_to_duty_cycle(angle: int) -> float:
    """
    Convert a servo angle in degrees to an RPi.GPIO PWM duty cycle percent.

    SG90-class servos expect a ~1ms-2ms pulse width within a 20ms (50Hz)
    period, corresponding to roughly 2%-12% duty cycle for 0-180 degrees.
    This is the standard linear mapping used across most RPi servo
    tutorials: duty% = angle / 18 + 2.

    Args:
        angle: Target angle in degrees (0-180).

    Returns:
        Duty cycle as a percentage (float) suitable for
        `PWM.ChangeDutyCycle`.
    """
    return (angle / 18) + 2


class ServoArm:
    """
    Drives Alfred's arm — on a real SG90 servo when GPIO is available,
    falling back to a console-logging simulator otherwise.
    """

    def __init__(
        self,
        gpio_pin: int,
        min_angle: int,
        max_angle: int,
        rest_angle: int,
        simulate_if_missing: bool,
    ) -> None:
        """
        Set up the arm, preferring real hardware.

        Args:
            gpio_pin: BCM-numbered GPIO pin driving the servo's PWM line.
            min_angle: Minimum allowed angle in degrees.
            max_angle: Maximum allowed angle in degrees.
            rest_angle: Neutral "arm down" angle used by `rest()` and as
                the starting position.
            simulate_if_missing: If True and real hardware can't be
                reached, log simulated movement instead of going silent.
        """
        self._min_angle = min_angle
        self._max_angle = max_angle
        self._rest_angle = rest_angle
        self._gpio_pin = gpio_pin
        self._pwm = None
        self._simulator: ServoSimulator | None = None
        self.is_simulated: bool = False
        # Serializes movement so two gestures triggered in quick
        # succession (e.g. two mood changes) don't fight over the PWM
        # signal from different threads.
        self._lock = threading.Lock()

        if _HARDWARE_IMPORTS_OK:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(gpio_pin, GPIO.OUT)
                self._pwm = GPIO.PWM(gpio_pin, PWM_FREQUENCY_HZ)
                self._pwm.start(_angle_to_duty_cycle(rest_angle))
                return
            except Exception as exc:
                print(f"[Alfred] Servo hardware init failed: {exc}")

        if simulate_if_missing:
            self._simulator = ServoSimulator(gpio_pin, min_angle, max_angle)
            self.is_simulated = True
        else:
            print("[Alfred] Servo disabled: no hardware found and simulation is off.")

    def move_to(self, angle: int) -> None:
        """
        Move the arm directly to an angle, clamped to the configured range.

        Blocks for `SETTLE_SECONDS` to give the physical servo time to
        arrive before the PWM signal is cut — callers that don't want to
        block should use the gesture methods instead, which already run
        on a background thread.

        Args:
            angle: Target angle in degrees.
        """
        clamped = max(self._min_angle, min(self._max_angle, angle))

        if self._simulator is not None:
            self._simulator.move_to(clamped)
            return

        if self._pwm is None:
            return

        with self._lock:
            self._pwm.ChangeDutyCycle(_angle_to_duty_cycle(clamped))
            time.sleep(SETTLE_SECONDS)
            # Cut the signal once settled — holding a constant duty
            # cycle on a cheap analog servo causes an audible buzz.
            self._pwm.ChangeDutyCycle(0)

    def react_to_level(self, angle: int) -> None:
        """
        Move directly to an angle for live, frequent updates — e.g.
        reacting to microphone level while Alfred is listening.

        Unlike `move_to`, this skips the settle delay and PWM-signal
        cutoff: the caller will keep calling this many times a second
        rather than holding one discrete position, so sleeping or
        zeroing the signal between calls would just fight the next
        update and add needless latency.

        Args:
            angle: Target angle in degrees.
        """
        clamped = max(self._min_angle, min(self._max_angle, angle))

        if self._simulator is not None:
            self._simulator.react_to_level(clamped)
            return

        if self._pwm is None:
            return

        with self._lock:
            self._pwm.ChangeDutyCycle(_angle_to_duty_cycle(clamped))

    def rest(self) -> None:
        """Move the arm to its neutral resting angle."""
        threading.Thread(target=self.move_to, args=(self._rest_angle,), daemon=True).start()

    def wave(self) -> None:
        """Sweep the arm up and down twice, then return to rest — a greeting gesture."""
        threading.Thread(target=self._wave_sequence, daemon=True).start()

    def nod(self) -> None:
        """Dip the arm once and return to rest — an acknowledgement gesture."""
        threading.Thread(target=self._nod_sequence, daemon=True).start()

    def point(self) -> None:
        """Extend the arm to its maximum angle and hold — used for emphasis."""
        threading.Thread(target=self.move_to, args=(self._max_angle,), daemon=True).start()

    def close(self) -> None:
        """Release whichever backend is active (real PWM or simulator)."""
        if self._simulator is not None:
            self._simulator.close()
        elif self._pwm is not None:
            self._pwm.stop()
            GPIO.cleanup(self._gpio_pin)

    # ── Internal: gesture sequences (run on a background thread) ───────

    def _wave_sequence(self) -> None:
        """Move between min and max angle twice, then settle at rest."""
        for _ in range(2):
            self.move_to(self._max_angle)
            self.move_to(self._min_angle)
        self.move_to(self._rest_angle)

    def _nod_sequence(self) -> None:
        """Dip toward the minimum angle once, then return to rest."""
        self.move_to(self._min_angle)
        self.move_to(self._rest_angle)
