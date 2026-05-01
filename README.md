# FocusBot AI Desktop Assistant

[![Python CI](https://github.com/your-username/focusbot/actions/workflows/python-ci.yml/badge.svg)](https://github.com/your-username/focusbot/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

FocusBot is an AI-powered desktop assistant with an optional ADHD Focus Mode. It combines a Claude AI backend with a local Python GUI to provide task reminders, focus timers, task breakdowns, and daily routine support.

> Not a medical device. Just a helpful robot buddy. 🤖

---

## Features

- **General AI assistant** — ask anything, powered by Claude
- ** ADHD Focus Mode** — toggle on for short, structured, ADHD-friendly responses
- **Task breakdown** — any task broken into 3–4 tiny first steps
- **Timed reminders** — spoken + visual reminders ("remind me in 30 minutes to...")
- **Focus timer** — 25-minute Pomodoro sessions with live countdown
- **Daily routines** — morning and evening routine guidance
- **Text-to-speech** — FocusBot speaks every response aloud

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/your-username/focusbot.git
cd focusbot
```

### 2. Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate   # Mac/Linux
.venv\Scripts\activate      # Windows
```

### 3. Install dependencies
```bash
pip install -e ".[dev]"
```

### 4. Add your API key
Copy the config template and add your key:
```bash
cp src/focusbot/config.py.example src/focusbot/config.py
```
Then open `src/focusbot/config.py` and set:
```python
ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```
Get your key at [console.anthropic.com](https://console.anthropic.com).

### 5. Run FocusBot
```bash
python -m focusbot
```

---

## Running Tests

```bash
pytest
```

---

## Project Structure

```
focusbot/
├── src/
│   └── focusbot/
│       ├── __init__.py      # package metadata
│       ├── main.py          # entry point
│       ├── gui.py           # tkinter UI
│       ├── assistant.py     # Claude AI integration + system prompts
│       ├── reminders.py     # reminder scheduling, focus timer, intent detection
│       ├── voice.py         # text-to-speech engine
│       └── config.py        # API key + settings (not committed)
├── tests/
│   └── test_reminders.py    # unit tests
├── assets/                  # sounds, icons (future)
├── docs/
│   └── hardware_setup.md    # Raspberry Pi wiring guide
├── .github/
│   └── workflows/
│       └── python-ci.yml    # CI pipeline
├── pyproject.toml
└── README.md
```

---

## Roadmap

- [x] Phase 1 — Desktop software (Python + Claude AI)
- [ ] Phase 2 — Raspberry Pi port
- [ ] Phase 3 — OLED face + servo head movement
- [ ] Phase 4 — Voice input (microphone)
- [ ] Phase 5 — Fully wireless standalone robot

---

## Built With

- [Python](https://python.org) + [Tkinter](https://docs.python.org/3/library/tkinter.html)
- [Anthropic Claude API](https://anthropic.com)
- [pyttsx3](https://pyttsx3.readthedocs.io/) — offline text-to-speech
- [pytest](https://pytest.org) — testing
