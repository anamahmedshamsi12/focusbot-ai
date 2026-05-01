"""
config.py
---------
Central configuration for FocusBot.
Edit this file to set your API key and preferences.
"""

# ── Anthropic API ──────────────────────────────────────────────────────────
# Get your key at https://console.anthropic.com → API Keys
ANTHROPIC_API_KEY: str = "your-api-key-here"

# ── Voice ──────────────────────────────────────────────────────────────────
# Set to False if text-to-speech causes issues on your machine
VOICE_ENABLED: bool = True

# ── Focus Timer ────────────────────────────────────────────────────────────
# Default Pomodoro session length in minutes
FOCUS_MINUTES: int = 25
