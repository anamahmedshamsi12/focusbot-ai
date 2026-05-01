# Hardware Setup — Raspberry Pi Phase

This document covers wiring and setup for when you move FocusBot
from your laptop to a Raspberry Pi with physical components.

> Complete Phase 1 (software) first. Come back to this when your Pi arrives.

---

## Shopping List

| Part                        | Approx. Cost |
|-----------------------------|-------------|
| Raspberry Pi 4 (2GB) or Zero 2 W | $15–45  |
| MicroSD card (32GB)         | $8          |
| 128×64 OLED display (I2C)   | $6          |
| SG90 servo motor            | $4          |
| USB microphone              | $12         |
| Small speaker + PAM8403 amp | $8          |
| Portable USB battery pack   | $15         |
| Jumper wires + breadboard   | $5          |

**Total: ~$60–100**

---

## OLED Display Wiring (I2C)

```
OLED Pin  →  Raspberry Pi Pin
VCC       →  Pin 1  (3.3V)
GND       →  Pin 6  (GND)
SDA       →  Pin 3  (GPIO 2)
SCL       →  Pin 5  (GPIO 3)
```

Enable I2C on the Pi:
```bash
sudo raspi-config → Interface Options → I2C → Enable
sudo pip install adafruit-circuitpython-ssd1306
```

---

## Servo Motor Wiring

```
Servo Wire  →  Raspberry Pi Pin
Red (VCC)   →  Pin 4  (5V)
Brown (GND) →  Pin 9  (GND)
Orange (PWM)→  Pin 12 (GPIO 18)
```

Install RPi.GPIO:
```bash
sudo pip install RPi.GPIO
```

---

## Running FocusBot on the Pi

1. Copy this repo to the Pi (via USB or `git clone`)
2. Install dependencies: `pip install -e ".[dev]"`
3. Add your API key to `src/focusbot/config.py`
4. Run: `python -m focusbot`

To auto-start on boot, add to crontab:
```
@reboot cd /home/pi/focusbot && python -m focusbot
```
