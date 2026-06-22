"""
alfred.robot
--------------
Headless entry point for Alfred running as the physical Raspberry Pi
robot — no Tkinter window, no monitor required. The OLED eyes and
servo arm are the only "display" this mode has.

The loop is: wake word -> speech-to-text -> Claude -> text-to-speech,
with alfred.core.personality reacting at each step so the eyes/arm
always reflect what Alfred is currently doing. This mirrors
alfred.focusbot's desktop GUI logic closely on purpose — same intents,
same memory, same personalities — just without any widgets.

Run with:
    python -m alfred.robot
"""

import random
import time

from alfred.config.settings import FOCUS_MINUTES
from alfred.core.brain import (
    FOCUS_MODE_PROMPT,
    GENERAL_PROMPT,
    add_note,
    add_task,
    ask_alfred,
    create_client,
    load_memory,
    update_name,
)
from alfred.core.focus import (
    detect_intent,
    parse_reminder,
    set_reminder,
    start_focus_timer,
)
from alfred.core.personality import Personality
from alfred.core.voice import (
    init_listener,
    init_tts,
    speak,
    start_listening,
    start_wake_word,
)

# Spoken when the wake word is heard but no command follows it within
# the listening window — keeps Alfred from going silent on a bare "hey
# alfred", the same way a real assistant would acknowledge you.
NO_COMMAND_GREETINGS: list[str] = [
    "Hey, how's it going?",
    "Hey there! What's up?",
    "Yeah? I'm listening.",
    "Hi! Need something?",
]


class Robot:
    """
    Owns all live state for the headless robot: conversation history,
    focus mode, the active focus timer flag, and the personality/voice
    backends. Implements the same minimal interface alfred.core.focus
    expects from an "app" — `display_message`, `update_status`,
    `tts_engine`, and `focus_active` — so the exact same focus/reminder
    code path runs in both the GUI and headless robot modes.
    """

    def __init__(self) -> None:
        """Load memory, connect to Claude, and bring up voice + personality hardware."""
        self.conversation_history: list[dict] = []
        self.focus_mode: bool = False
        self.focus_active: bool = False
        self.is_listening: bool = False
        self._status: str = "Ready"

        self.memory: dict = load_memory()
        self.client = create_client()
        self.tts_engine = init_tts()
        self.recognizer, self.active_flag = init_listener()
        self.personality = Personality()

    # ── Minimal "app" interface required by alfred.core.focus ──────────

    def display_message(self, sender: str, message: str) -> None:
        """
        Print a conversation line to the console.

        There's no chat window in headless mode, so stdout (which on a
        Pi is typically captured by journald/systemd) is the transcript.

        Args:
            sender: 'Alfred', 'You', or 'System'.
            message: The message body to display.
        """
        print(f"\n{sender}: {message}")

    def update_status(self, text: str) -> None:
        """
        Record the current status text without printing it.

        The focus timer calls this once per second with a countdown
        string — printing that every second would flood the console.
        In headless mode the physical eyes already convey "Alfred is
        busy with a focus session" visually, so a textual status bar
        has no equivalent here; we just keep the latest value around
        in case future code wants to inspect it.

        Args:
            text: Status string (e.g. "Focus session: 24:59 remaining").
        """
        self._status = text

    # ── Wake Word -> Listening Handoff ──────────────────────────────────

    def on_wake_word_detected(self, command: str = "") -> None:
        """
        Called by the wake word loop when "hey alfred" is heard.

        Args:
            command: Anything the user said in the same breath right
                after "hey alfred" (e.g. "hey alfred what's the
                weather" -> "what's the weather"). When non-empty, it's
                processed immediately instead of opening a second
                listening session.
        """
        if self.is_listening:
            return
        self.personality.on_wake_word()

        if command:
            self.display_message("System", "Wake word detected — command included")
            self.display_message("You", command)
            self._process_message(command)
        else:
            self.display_message("System", "Wake word detected — listening...")
            self._begin_listening()

    def _begin_listening(self) -> None:
        """Open a full listening session and route the result to `_process_message`."""
        start_listening(
            recognizer=self.recognizer,
            active_flag=self.active_flag,
            on_listening=self._on_listening_start,
            on_result=self._on_voice_result,
            on_done=self._on_listening_done,
            on_level=self.personality.on_audio_level,
            on_nothing_heard=self._on_nothing_heard,
        )

    def _on_listening_start(self) -> None:
        """Called the moment the microphone opens for a full utterance."""
        self.is_listening = True
        self.personality.on_listening()

    def _on_listening_done(self) -> None:
        """Called when the listening session ends, whether or not speech was understood."""
        self.is_listening = False

    def _on_voice_result(self, text: str) -> None:
        """
        Called with the transcribed text once speech recognition succeeds.

        Args:
            text: Transcribed user speech.
        """
        self.display_message("You", text)
        self._process_message(text)

    def _on_nothing_heard(self) -> None:
        """
        Called when a listening session ends with no speech transcribed.

        The wake word was heard (that's the only way listening starts),
        but nothing followed it — respond with a casual greeting rather
        than going quiet, the way a real assistant would.
        """
        reply = random.choice(NO_COMMAND_GREETINGS)
        self.display_message("Alfred", reply)
        self.personality.on_speaking()
        speak(reply, self.tts_engine)

    # ── Message Routing (mirrors alfred.focusbot's logic) ───────────────

    def _process_message(self, text: str) -> None:
        """
        Route a transcribed (or otherwise received) message to the
        correct handler based on detected intent, updating memory and
        personality mood along the way.

        Args:
            text: The user's raw input string.
        """
        self.personality.on_thinking()
        intent = detect_intent(text)

        # Lightweight memory commands — same keyword rules as the GUI.
        low = text.lower()
        if "my name is" in low:
            name = text.lower().split("my name is")[-1].strip().split()[0]
            update_name(self.memory, name)
        elif "remember that" in low:
            note = text.lower().split("remember that")[-1].strip()
            add_note(self.memory, note)
        elif any(w in low for w in ["i need to", "i have to", "i should"]):
            add_task(self.memory, text.strip())

        if intent == "stop":
            self.focus_active = False
            reply = "Focus session stopped. Good effort!"
            self.display_message("Alfred", reply)
            self._speak_reply(reply)

        elif intent == "focus":
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            self._speak_reply(reply)
            self.personality.on_focus_start()
            start_focus_timer(FOCUS_MINUTES, self, on_complete=self.personality.on_focus_end)

        elif intent == "reminder":
            minutes = parse_reminder(text)
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            self._speak_reply(reply)
            if minutes:
                set_reminder(minutes, text, self, on_fire=self.personality.on_wake_word)
                self.display_message("System", f"Reminder set for {minutes} minutes from now.")
            else:
                self.display_message("System", "Could not find a time. Try: Remind me in 20 minutes to...")

        else:
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            self._speak_reply(reply)

    def _speak_reply(self, reply: str) -> None:
        """
        Speak a Claude reply aloud, reacting with an error mood instead
        of a normal speaking mood if the API call itself failed.

        Args:
            reply: The text returned by `ask_alfred` (may be an error
                message rather than a real reply — see brain.ask_alfred).
        """
        if reply.startswith("API key error") or reply.startswith("Error connecting to AI:"):
            self.personality.on_error()
        else:
            self.personality.on_speaking()
        speak(reply, self.tts_engine)

    def _active_prompt(self) -> str:
        """Return the system prompt for whichever mode is currently active."""
        return FOCUS_MODE_PROMPT if self.focus_mode else GENERAL_PROMPT

    # ── Lifecycle ────────────────────────────────────────────────────────

    def greet(self) -> None:
        """Speak and log the startup greeting, using the user's name if known."""
        name = self.memory.get("name")
        greeting = f"Hey {name}!" if name else "Hey!"
        message = f"{greeting} I am Alfred. Say 'hey alfred' any time to talk to me."
        self.display_message("Alfred", message)
        self.personality.on_speaking()
        speak(message, self.tts_engine)

    def shutdown(self) -> None:
        """Release hardware (or simulator) resources on exit."""
        self.personality.close()


def main() -> None:
    """Bring up the robot, start the wake word loop, and block forever."""
    # Personality()/OledEyes() must be constructed on the main thread —
    # this happens inside Robot(), called here before any background
    # thread starts, which is exactly what the Tk-on-main-thread
    # requirement needs.
    robot = Robot()
    robot.greet()
    start_wake_word(robot.on_wake_word_detected, robot.active_flag)

    print("[Alfred] Robot running. Say 'hey alfred' to start a conversation. Ctrl+C to stop.")

    if robot.personality.owns_mainloop:
        # The eye simulator created its own Tk root (no real OLED, and
        # no desktop GUI already running one) — that root's mainloop
        # must run on the main thread, so it replaces the sleep loop
        # below. The wake word loop and every gesture/animation still
        # run on their own daemon threads in the background.
        robot.personality.tk_root.protocol("WM_DELETE_WINDOW", robot.shutdown)
        try:
            robot.personality.tk_root.mainloop()
        except KeyboardInterrupt:
            print("\n[Alfred] Shutting down.")
            robot.shutdown()
    else:
        try:
            # No Tk root to pump — either real OLED hardware is in use,
            # or the OLED is disabled outright. The wake word loop and
            # every gesture/animation run on daemon threads, so the
            # main thread just needs to stay alive.
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Alfred] Shutting down.")
            robot.shutdown()


if __name__ == "__main__":
    main()
