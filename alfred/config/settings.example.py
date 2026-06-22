"""
alfred.config.settings (example/template)
-------------------------------------------
Copy this file to settings.py in the same directory and fill in your
own Anthropic API key:

    cp alfred/config/settings.example.py alfred/config/settings.py

settings.py is listed in .gitignore and is never tracked by git, so
your real key never ends up in version control — only this placeholder
template does.
"""

# ── Anthropic API ────────────────────────────────────────────────────────────
# Get your key at https://console.anthropic.com -> API Keys
ANTHROPIC_API_KEY: str = "your-api-key-here"

# ── Voice ────────────────────────────────────────────────────────────────────
# Set to False if text-to-speech causes issues on your machine.
VOICE_ENABLED: bool = True

# Which input device to listen on, matched by case-insensitive substring
# against the names from `speech_recognition.Microphone.list_microphone_names()`
# (e.g. "MacBook Pro Microphone"). Leave as None to use whatever the OS
# reports as the current default input device.
#
# Why this exists: the OS default can silently change — e.g. pairing
# Bluetooth headphones often switches the system default input to their
# (frequently low-quality or inactive) mic, which makes the wake word
# loop look "broken" with no error at all, since recognition failures
# are caught and ignored by design. Pinning a device name here avoids
# that whole class of problem.
MIC_DEVICE_NAME: str | None = None

# ── Focus Timer ──────────────────────────────────────────────────────────────
# Default Pomodoro session length in minutes.
FOCUS_MINUTES: int = 25

# ── OLED Eyes (alfred.hardware.oled / alfred.simulator.eyes_sim) ────────────
# Master switch — set False to disable eye rendering entirely (no hardware
# calls, no simulator window).
OLED_ENABLED: bool = True

# I2C address of the SSD1306 OLED. 0x3C is the common default for the
# 128x64 boards listed in docs/hardware_setup.md; some clones use 0x3D.
OLED_I2C_ADDRESS: int = 0x3C
OLED_WIDTH: int = 128
OLED_HEIGHT: int = 64

# If the adafruit-circuitpython-ssd1306 import or I2C bus probe fails
# (e.g. we're developing on a Mac with no I2C bus), open a Tkinter window
# that mirrors the eye animation instead of silently doing nothing. This
# lets mood/animation logic be written and watched before the physical
# OLED display exists.
OLED_SIMULATE_IF_MISSING: bool = True

# ── Servo Arm (alfred.hardware.servo / alfred.simulator.servo_sim) ──────────
SERVO_ENABLED: bool = True

# BCM-numbered GPIO pin driving the SG90 servo's PWM (orange) wire —
# matches the wiring table in docs/hardware_setup.md.
SERVO_GPIO_PIN: int = 18
SERVO_MIN_ANGLE: int = 0
SERVO_MAX_ANGLE: int = 180
SERVO_REST_ANGLE: int = 90

# If RPi.GPIO can't be imported (e.g. we're developing on a Mac, not a
# Pi), log the angles the servo would have moved to instead of doing
# nothing.
SERVO_SIMULATE_IF_MISSING: bool = True
