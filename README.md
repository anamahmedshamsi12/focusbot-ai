# FocusBot — AI Desktop Assistant

[![Python CI](https://github.com/anamahmedshamsi12/focusbot-ai/actions/workflows/python-ci.yml/badge.svg)](https://github.com/anamahmedshamsi12/focusbot-ai/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

FocusBot is a desktop assistant powered by the Claude API. It includes a general AI assistant mode and an optional ADHD Focus Mode for task reminders, focus timers, task breakdowns, and daily routine support.

---

## Features

- **General AI assistant** — ask anything, powered by Claude
- **ADHD Focus Mode** — toggle on for short, structured responses designed around common ADHD challenges
- **Task breakdown** — any task broken into 3-4 small, actionable steps
- **Timed reminders** — spoken and visual reminders ("remind me in 30 minutes to...")
- **Focus timer** — 25-minute Pomodoro sessions with a live countdown
- **Daily routines** — morning and evening routine guidance
- **Text-to-speech** — FocusBot speaks every response aloud

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
pip install -e ".[dev]"
```

### 4. Add your API key
Open `src/focusbot/config.py` and set:
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
focusbot-ai/
├── src/
│   └── focusbot/
│       ├── __init__.py      # package metadata
│       ├── main.py          # entry point
│       ├── gui.py           # tkinter UI
│       ├── assistant.py     # Claude API integration and system prompts
│       ├── reminders.py     # reminder scheduling, focus timer, intent detection
│       ├── voice.py         # text-to-speech engine
│       └── config.py        # API key and settings (not committed)
├── tests/
│   └── test_reminders.py    # unit tests
├── assets/                  # sounds and icons (future)
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

- [x] Phase 1 — Desktop software (Python + Claude API)
- [ ] Phase 2 — Raspberry Pi port
- [ ] Phase 3 — OLED face and servo head movement
- [ ] Phase 4 — Voice input via microphone
- [ ] Phase 5 — Fully wireless standalone robot

---

## Built With

- [Python](https://python.org) + [Tkinter](https://docs.python.org/3/library/tkinter.html)
- [Anthropic Claude API](https://anthropic.com)
- [pyttsx3](https://pyttsx3.readthedocs.io/) — offline text-to-speech
- [pytest](https://pytest.org) — testing