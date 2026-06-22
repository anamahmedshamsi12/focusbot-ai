# Alfred — AI Desktop Companion Robot

[![Python CI](https://github.com/anamahmedshamsi12/focusbot-ai/actions/workflows/python-ci.yml/badge.svg)](https://github.com/anamahmedshamsi12/focusbot-ai/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

Alfred is an AI desktop companion powered by the Claude API, built to run either as a desktop chat app (today) or as a physical Raspberry Pi robot with OLED eyes and a servo arm (once the hardware is wired up). It includes a general AI assistant mode and an optional ADHD Focus Mode for task reminders, focus timers, task breakdowns, and daily routine support.

---

## Features

- **General AI assistant** — ask anything, powered by Claude
- **ADHD Focus Mode** — toggle on for short, structured responses designed around common ADHD challenges
- **Task breakdown** — any task broken into 3-4 small, actionable steps
- **Timed reminders** — spoken and visual reminders ("remind me in 30 minutes to...")
- **Focus timer** — 25-minute Pomodoro sessions with a live countdown
- **Daily routines** — morning and evening routine guidance
- **Wake word + voice input** — say "hey alfred" to start talking, no button required
- **Text-to-speech** — Alfred speaks every response aloud
- **Persistent memory** — remembers your name, ongoing tasks, and anything you ask it to remember, across sessions
- **Mood-reactive eyes** — a 128x64 OLED face that changes expression with what Alfred is doing (listening, thinking, focused, alert, ...)
- **Servo arm gestures** — waves, nods, and points alongside the conversation
- **Runs with or without the physical robot** — every hardware module simulates itself (a Tkinter eye window, console-logged servo angles) when no Pi hardware is attached, so the whole stack runs on a laptop too

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/anamahmedshamsi12/focusbot-ai.git
cd focusbot-ai
```

### 2. Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate   # Mac/Linux
.venv\Scripts\activate      # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```
Raspberry Pi only — also install the hardware drivers for the OLED and servo:
```bash
pip install -r requirements-pi.txt
```

### 4. Add your API key
```bash
cp alfred/config/settings.example.py alfred/config/settings.py
```
Then open `alfred/config/settings.py` and set:
```python
ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```
Get your key at [console.anthropic.com](https://console.anthropic.com). `settings.py` is gitignored, so your key never ends up in version control.

### 5. Run Alfred

Desktop GUI (any machine):
```bash
python -m alfred
```

Headless robot mode (Raspberry Pi, or to test the wake word/eyes/arm loop on a laptop without a chat window):
```bash
python -m alfred.robot
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

---

## Project Structure

```
focusbot-ai/
├── alfred/
│   ├── __init__.py
│   ├── __main__.py            # `python -m alfred` -> desktop GUI
│   ├── focusbot.py            # desktop GUI entry point (Tkinter)
│   ├── robot.py                # headless Raspberry Pi entry point
│   ├── core/
│   │   ├── voice.py            # wake word detection + speech-to-text + text-to-speech
│   │   ├── brain.py            # Claude API integration + persistent memory
│   │   ├── personality.py      # mood system — maps events to eyes/arm reactions
│   │   └── focus.py            # ADHD task management: reminders, focus timer, intent detection
│   ├── hardware/
│   │   ├── oled.py              # real SSD1306 OLED eye driver (I2C)
│   │   └── servo.py             # real SG90 servo arm driver (GPIO PWM)
│   ├── simulator/
│   │   ├── eyes_sim.py          # Tkinter window standing in for the OLED
│   │   └── servo_sim.py         # console logger standing in for the servo
│   └── config/
│       ├── settings.py          # your API key + all tunables (gitignored)
│       └── settings.example.py  # tracked template — copy to settings.py
├── tests/                       # unit tests (no hardware/display required)
├── assets/                      # sounds and icons (future)
├── docs/
│   └── hardware_setup.md        # Raspberry Pi wiring guide
├── .github/workflows/python-ci.yml
├── requirements.txt              # core runtime deps (any machine)
├── requirements-pi.txt           # OLED/servo deps (Raspberry Pi only)
├── requirements-dev.txt          # + pytest for running the test suite
└── README.md
```

---

## Roadmap

- [x] Phase 1 — Desktop software (Python + Claude API)
- [x] Phase 2 — Voice input, wake word, persistent memory
- [x] Phase 3 — OLED eyes and servo arm (with desktop simulators for development)
- [ ] Phase 4 — Wire up and test on real Raspberry Pi hardware
- [ ] Phase 5 — Fully wireless standalone robot

---

## Built With

- [Python](https://python.org) + [Tkinter](https://docs.python.org/3/library/tkinter.html)
- [Anthropic Claude API](https://anthropic.com)
- [SpeechRecognition](https://pypi.org/project/SpeechRecognition/) — wake word detection and speech-to-text
- [edge-tts](https://github.com/rany2/edge-tts) — primary text-to-speech, with offline [pyttsx3](https://pyttsx3.readthedocs.io/) fallback
- [Adafruit CircuitPython SSD1306](https://github.com/adafruit/Adafruit_CircuitPython_SSD1306) + [Pillow](https://python-pillow.org/) — OLED eye rendering
- [RPi.GPIO](https://pypi.org/project/RPi.GPIO/) — servo arm control
- [pytest](https://pytest.org) — testing