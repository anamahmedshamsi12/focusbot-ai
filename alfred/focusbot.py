"""
alfred.focusbot
------------------
Desktop entry point for Alfred: a Tkinter chat window for development
and for running on a regular computer (no Pi hardware required).

`FocusBotApp` wires together voice I/O, the Claude brain, ADHD focus
tools, and the personality/mood system into a single chat interface
with a mode toggle, quick-action buttons, mic input, and a live status
bar. For the headless robot equivalent of this same conversation loop,
see alfred.robot.

Run with:
    python -m alfred
or:
    python alfred/focusbot.py
"""

import random
import threading
import tkinter as tk
from tkinter import scrolledtext

import pyttsx3

from alfred.config.settings import FOCUS_MINUTES
from alfred.core.brain import (
    FOCUS_MODE_PROMPT,
    GENERAL_PROMPT,
    add_note,
    add_task,
    ask_alfred,
    clear_memory,
    create_client,
    load_memory,
    save_memory,
    update_name,
)
from alfred.core.focus import (
    detect_intent,
    parse_reminder,
    set_reminder,
    start_focus_timer,
)
from alfred.core.personality import Personality
from alfred.core.voice import init_listener, init_tts, speak, start_listening, start_wake_word

# Spoken when the wake word is heard but no command follows it within
# the listening window — keeps Alfred from going silent on a bare "hey
# alfred", the same way a real assistant would acknowledge you.
NO_COMMAND_GREETINGS: list[str] = [
    "Hey, how's it going?",
    "Hey there! What's up?",
    "Yeah? I'm listening.",
    "Hi! Need something?",
]


class FocusBotApp:
    """
    Main application window for alfred.ai.

    Responsibilities:
    - Build and manage all tkinter widgets
    - Route user messages to the correct handler (AI, timer, reminder)
    - Drive the personality system (eyes/arm) alongside the visible UI
    - Provide thread-safe display_message and update_status callbacks
      used by alfred.core.focus and other background threads
    """

    def __init__(self, root: tk.Tk) -> None:
        """
        Build the window, load memory, connect to Claude/voice/personality,
        and start the wake word listener.

        Args:
            root: The Tkinter root window to build the UI inside.
        """
        self.root = root
        self.root.title("alfred.ai")
        self.root.geometry("600x700")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        # State
        self.conversation_history: list[dict] = []
        self.focus_active: bool = False
        self.focus_mode: bool = False
        self.is_listening: bool = False
        self.memory: dict = load_memory()

        # External dependencies
        self.tts_engine: pyttsx3.Engine | None = init_tts()
        self.recognizer, self.active_flag = init_listener()
        self.client = create_client()
        # tk_master=self.root: the eye simulator (if used) attaches as
        # a Toplevel of this window instead of spawning its own thread
        # and Tk root — required on macOS, where creating an NSWindow
        # off the main thread is a fatal error.
        self.personality = Personality(tk_master=self.root)

        self._build_ui()
        self._welcome()
        start_wake_word(self._on_wake_word, self.active_flag)

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct all tkinter widgets and lay them out."""
        self._build_title_bar()
        self._build_quick_buttons()
        self._build_chat_display()
        self._build_input_area()
        self._build_status_bar()

    def _build_title_bar(self) -> None:
        """Build the top bar: title, mode toggle, and settings button."""
        frame = tk.Frame(self.root, bg="#16213e", pady=10)
        frame.pack(fill="x")

        tk.Label(
            frame, text="alfred.ai",
            font=("Helvetica", 22, "bold"),
            bg="#16213e", fg="#00d4ff",
        ).pack(side="left", padx=20)

        tk.Label(
            frame, text="AI Assistant",
            font=("Helvetica", 11),
            bg="#16213e", fg="#888888",
        ).pack(side="left")

        self.mode_btn = tk.Button(
            frame,
            text="Focus Mode: OFF",
            command=self._toggle_mode,
            bg="#0f3460", fg="#888888",
            font=("Helvetica", 10),
            relief="flat", padx=12, pady=4, cursor="hand2",
        )
        self.mode_btn.pack(side="right", padx=5)

        tk.Button(
            frame,
            text="Settings",
            command=self._open_settings,
            bg="#0f3460", fg="#888888",
            font=("Helvetica", 10),
            relief="flat", padx=12, pady=4, cursor="hand2",
        ).pack(side="right", padx=5)

    def _build_quick_buttons(self) -> None:
        """Build the row of one-click action buttons (focus, breakdown, etc)."""
        frame = tk.Frame(self.root, bg="#1a1a2e", pady=8)
        frame.pack(fill="x", padx=15)

        buttons = [
            ("Focus 25min", self._quick_focus),
            ("Breakdown",   self._quick_breakdown),
            ("Routine",     self._quick_routine),
            ("Stop Timer",  self._stop_focus),
        ]
        for label, cmd in buttons:
            tk.Button(
                frame, text=label, command=cmd,
                bg="#0f3460", fg="white",
                font=("Helvetica", 10),
                relief="flat", padx=10, pady=5, cursor="hand2",
                activebackground="#e94560", activeforeground="white",
            ).pack(side="left", padx=4)

    def _build_chat_display(self) -> None:
        """Build the scrollable chat transcript widget and its text styling tags."""
        frame = tk.Frame(self.root, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        self.chat_display = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            bg="#0d0d1a", fg="#e0e0e0",
            font=("Helvetica", 12),
            relief="flat", padx=12, pady=10,
            state="disabled", insertbackground="white",
        )
        self.chat_display.pack(fill="both", expand=True)

        self.chat_display.tag_configure("bot_name",  foreground="#00d4ff", font=("Helvetica", 12, "bold"))
        self.chat_display.tag_configure("bot_text",  foreground="#e0e0e0", font=("Helvetica", 12))
        self.chat_display.tag_configure("user_name", foreground="#ff6b9d", font=("Helvetica", 12, "bold"))
        self.chat_display.tag_configure("user_text", foreground="#cccccc", font=("Helvetica", 12))
        self.chat_display.tag_configure("system",    foreground="#888888", font=("Helvetica", 10, "italic"))

    def _build_input_area(self) -> None:
        """Build the mic button, text entry field, and send button."""
        frame = tk.Frame(self.root, bg="#16213e", pady=10)
        frame.pack(fill="x", padx=15, pady=(0, 5))

        self.mic_btn = tk.Button(
            frame, text="\U0001F399",
            command=self._on_mic,
            bg="#0f3460", fg="white",
            font=("Helvetica", 14),
            relief="flat", padx=10, pady=6, cursor="hand2",
            activebackground="#e94560", activeforeground="white",
        )
        self.mic_btn.pack(side="left", padx=(0, 8))

        self.input_field = tk.Entry(
            frame,
            bg="#0d0d1a", fg="white",
            font=("Helvetica", 13),
            relief="flat", insertbackground="white",
        )
        self.input_field.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.input_field.bind("<Return>", self._on_send)
        self.input_field.focus()

        tk.Button(
            frame, text="Send",
            command=self._on_send,
            bg="#e94560", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", padx=16, pady=8, cursor="hand2",
        ).pack(side="right")

    def _build_status_bar(self) -> None:
        """Build the bottom status label."""
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#0d0d1a", fg="#555555",
            font=("Helvetica", 10),
            anchor="w", padx=10,
        ).pack(fill="x")

    # ── Thread-safe UI Callbacks ─────────────────────────────────────────

    def display_message(self, sender: str, message: str) -> None:
        """
        Append a message to the chat display. Safe to call from any thread.

        Args:
            sender: 'Alfred', 'You', or anything else shown as system text.
            message: The message body to display.
        """
        def _update() -> None:
            self.chat_display.configure(state="normal")
            if sender == "Alfred":
                self.chat_display.insert("end", "\nAlfred  ", "bot_name")
                self.chat_display.insert("end", f"\n{message}\n", "bot_text")
            elif sender == "You":
                self.chat_display.insert("end", "\nYou  ", "user_name")
                self.chat_display.insert("end", f"\n{message}\n", "user_text")
            else:
                self.chat_display.insert("end", f"\n{message}\n", "system")
            self.chat_display.configure(state="disabled")
            self.chat_display.see("end")

        self.root.after(0, _update)

    def update_status(self, text: str) -> None:
        """
        Update the status bar text. Safe to call from any thread.

        Args:
            text: Status string to display.
        """
        self.root.after(0, lambda: self.status_var.set(text))

    # ── Wake Word ────────────────────────────────────────────────────────

    def _on_wake_word(self, command: str = "") -> None:
        """
        Called when 'hey alfred' is detected.

        Args:
            command: Anything the user said in the same breath right
                after "hey alfred" (e.g. "hey alfred what's the
                weather" -> "what's the weather"). When non-empty, it's
                processed immediately instead of opening the mic again.
        """
        if self.is_listening:
            return
        self.personality.on_wake_word()

        if command:
            self.display_message("System", "Wake word detected - command included")
            self.display_message("You", command)
            threading.Thread(target=self._process_message, args=(command,), daemon=True).start()
        else:
            self.display_message("System", "Wake word detected - listening...")
            self._on_mic()

    # ── Voice Input ──────────────────────────────────────────────────────

    def _on_mic(self) -> None:
        """Called when the mic button is clicked. Starts listening."""
        if self.is_listening:
            return

        start_listening(
            recognizer=self.recognizer,
            active_flag=self.active_flag,
            on_listening=self._on_listening,
            on_result=self._on_voice_result,
            on_done=self._on_listening_done,
            on_level=self.personality.on_audio_level,
            on_nothing_heard=self._on_nothing_heard,
        )

    def _on_nothing_heard(self) -> None:
        """
        Called when a listening session ends with no speech transcribed.

        Respond with a casual greeting rather than going quiet — covers
        both "hey alfred" with nothing after, and the manual mic button
        being clicked and then not spoken into.
        """
        reply = random.choice(NO_COMMAND_GREETINGS)
        self.display_message("Alfred", reply)
        self.personality.on_speaking()
        speak(reply, self.tts_engine)

    def _on_listening(self) -> None:
        """Called when the mic opens. Updates UI and eyes to show the listening state."""
        self.is_listening = True
        self.root.after(0, lambda: self.mic_btn.config(bg="#e94560", text="\U0001F534"))
        self.update_status("Listening...")
        self.personality.on_listening()

    def _on_listening_done(self) -> None:
        """Called when listening finishes. Resets the mic button and mood."""
        self.is_listening = False
        self.root.after(0, lambda: self.mic_btn.config(bg="#0f3460", text="\U0001F399"))
        self.update_status("Ready")
        self.personality.on_idle()

    def _on_voice_result(self, text: str) -> None:
        """
        Called when speech is successfully transcribed.

        Args:
            text: Transcribed speech string.
        """
        self.display_message("You", text)
        threading.Thread(target=self._process_message, args=(text,), daemon=True).start()

    # ── Message Routing ──────────────────────────────────────────────────

    def _on_send(self, event: tk.Event | None = None) -> None:
        """Called when the user presses Enter or clicks Send."""
        text = self.input_field.get().strip()
        if not text:
            return
        self.input_field.delete(0, tk.END)
        self.display_message("You", text)
        threading.Thread(target=self._process_message, args=(text,), daemon=True).start()

    def _process_message(self, text: str) -> None:
        """
        Route a user message to the correct handler based on detected
        intent. Runs in a background thread to keep the UI responsive.

        Args:
            text: The user's raw input string.
        """
        self.update_status("Alfred is thinking...")
        self.personality.on_thinking()
        intent = detect_intent(text)

        # Lightweight memory commands, checked before intent routing.
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
            self.display_message("Alfred", "Focus session stopped. Good effort!")
            self.personality.on_idle()
            speak("Focus session stopped. Good effort!", self.tts_engine)
            self.update_status("Ready")

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
            self.update_status("Ready")

        else:
            reply = ask_alfred(text, self.conversation_history, self.client, self._active_prompt(), self.memory)
            self.display_message("Alfred", reply)
            self._speak_reply(reply)
            self.update_status("Ready")

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

    # ── Mode Toggle ──────────────────────────────────────────────────────

    def _toggle_mode(self) -> None:
        """
        Switch between General Mode and ADHD Focus Mode.
        Clears conversation history on switch so the AI stays in context.
        """
        self.focus_mode = not self.focus_mode
        self.conversation_history = []

        if self.focus_mode:
            self.mode_btn.config(text="Focus Mode: ON", fg="#00d4ff")
            self.display_message("System", "Switched to Focus Mode. Conversation reset.")
            self.display_message("Alfred", "Focus Mode on. I will keep things short and break tasks down. What are we working on?")
        else:
            self.mode_btn.config(text="Focus Mode: OFF", fg="#888888")
            self.display_message("System", "Switched to General Mode. Conversation reset.")
            self.display_message("Alfred", "General mode on. I can help with anything now. What is on your mind?")

    def _active_prompt(self) -> str:
        """Return the system prompt for whichever mode is currently active."""
        return FOCUS_MODE_PROMPT if self.focus_mode else GENERAL_PROMPT

    # ── Quick Action Buttons ─────────────────────────────────────────────

    def _quick_focus(self) -> None:
        """Pre-fill and send a request to start a 25-minute focus session."""
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Start a 25-minute focus session")
        self._on_send()

    def _quick_breakdown(self) -> None:
        """Pre-fill and send a request for task breakdown help."""
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "I need help breaking down a task")
        self._on_send()

    def _quick_routine(self) -> None:
        """Pre-fill and send a request for morning routine guidance."""
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Help me with my morning routine")
        self._on_send()

    def _stop_focus(self) -> None:
        """Cancel the active focus timer, if any."""
        self.focus_active = False
        self.update_status("Ready")
        self.personality.on_idle()
        self.display_message("Alfred", "Timer stopped. That is okay, every minute counts!")

    # ── Settings Panel ───────────────────────────────────────────────────

    def _open_settings(self) -> None:
        """Open the settings window for editing name, timer length, voice, and memory."""
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("400x420")
        win.configure(bg="#1a1a2e")
        win.resizable(False, False)

        tk.Label(
            win, text="Settings",
            font=("Helvetica", 16, "bold"),
            bg="#1a1a2e", fg="#00d4ff",
        ).pack(pady=(20, 15))

        # Name field
        tk.Label(win, text="Your Name", bg="#1a1a2e", fg="#888888", font=("Helvetica", 11)).pack(anchor="w", padx=30)
        name_var = tk.StringVar(value=self.memory.get("name") or "")
        name_entry = tk.Entry(win, textvariable=name_var, bg="#0d0d1a", fg="white", font=("Helvetica", 12), relief="flat", insertbackground="white")
        name_entry.pack(fill="x", padx=30, ipady=8, pady=(4, 14))

        # Focus timer length
        tk.Label(win, text="Focus Timer (minutes)", bg="#1a1a2e", fg="#888888", font=("Helvetica", 11)).pack(anchor="w", padx=30)
        timer_var = tk.IntVar(value=self.memory.get("preferences", {}).get("focus_minutes", 25))
        timer_spin = tk.Spinbox(win, from_=5, to=90, increment=5, textvariable=timer_var, bg="#0d0d1a", fg="white", font=("Helvetica", 12), relief="flat", buttonbackground="#0f3460", width=5)
        timer_spin.pack(anchor="w", padx=30, ipady=6, pady=(4, 14))

        # Voice toggle
        tk.Label(win, text="Voice Output", bg="#1a1a2e", fg="#888888", font=("Helvetica", 11)).pack(anchor="w", padx=30)
        voice_var = tk.BooleanVar(value=self.memory.get("preferences", {}).get("voice_enabled", True))
        tk.Checkbutton(
            win, text="Enabled", variable=voice_var,
            bg="#1a1a2e", fg="white", selectcolor="#0f3460",
            font=("Helvetica", 11), activebackground="#1a1a2e",
        ).pack(anchor="w", padx=30, pady=(4, 14))

        # Memory summary
        notes = self.memory.get("notes", [])
        tasks = self.memory.get("tasks", [])
        summary = f"{len(notes)} note(s), {len(tasks)} task(s) stored"
        tk.Label(win, text=f"Memory: {summary}", bg="#1a1a2e", fg="#555555", font=("Helvetica", 10)).pack(anchor="w", padx=30)

        # Clear memory button
        def _clear_memory() -> None:
            clear_memory(self.memory)
            self.display_message("System", "Memory cleared.")
            win.destroy()

        tk.Button(
            win, text="Clear All Memory",
            command=_clear_memory,
            bg="#3a0a0a", fg="#ff6b6b",
            font=("Helvetica", 10),
            relief="flat", padx=10, pady=4, cursor="hand2",
        ).pack(anchor="w", padx=30, pady=(4, 20))

        # Save button
        def _save() -> None:
            name = name_var.get().strip()
            if name:
                update_name(self.memory, name)

            if "preferences" not in self.memory:
                self.memory["preferences"] = {}
            self.memory["preferences"]["focus_minutes"] = timer_var.get()
            self.memory["preferences"]["voice_enabled"] = voice_var.get()

            save_memory(self.memory)
            self.display_message("System", "Settings saved.")
            win.destroy()

        tk.Button(
            win, text="Save",
            command=_save,
            bg="#e94560", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", padx=20, pady=8, cursor="hand2",
        ).pack(pady=10)

    # ── Welcome Message ──────────────────────────────────────────────────

    def _welcome(self) -> None:
        """Display and speak the initial greeting when the app launches."""
        name = self.memory.get("name")
        greeting = f"Hey {name}!" if name else "Hey!"
        message = (
            f"{greeting} I am Alfred, your AI desk assistant.\n\n"
            "I can help with pretty much anything - questions, tasks,\n"
            "writing, ideas, or just a chat.\n\n"
            "Need ADHD focus support? Hit the Focus Mode button\n"
            "in the top right to switch modes anytime.\n\n"
            "Click the mic button or type to get started!"
        )
        self.display_message("Alfred", message)
        self.personality.on_speaking()
        speak(f"{greeting} I am Alfred. Click the mic or type to get started!", self.tts_engine)


def main() -> None:
    """Create the tkinter root window and launch alfred.ai's desktop GUI."""
    root = tk.Tk()
    FocusBotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
