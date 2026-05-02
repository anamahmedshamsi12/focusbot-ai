"""
wakeword.py

Wake word detection for alfred.ai using pocketsphinx.
Continuously listens in the background for "hey alfred" and
fires a callback when detected so the main app can start listening.
"""

import threading
from pocketsphinx import LiveSpeech


# Keyword to listen for and detection threshold.
# Lower threshold = more sensitive but more false positives.
WAKE_PHRASE = "hey alfred"
THRESHOLD   = 1e-20


def start_wake_word(on_detected) -> None:
    """
    Start listening for the wake word in a background thread.

    Runs continuously until the app closes. When "hey alfred" is
    heard, calls on_detected() so the app can open the mic and
    start a full voice interaction.

    Args:
        on_detected: Callback with no arguments, fired on wake word detection.
    """
    def _listen() -> None:
        speech = LiveSpeech(
            keyphrase=WAKE_PHRASE,
            kws_threshold=THRESHOLD,
        )
        for phrase in speech:
            on_detected()

    thread = threading.Thread(target=_listen, daemon=True)
    thread.start()
